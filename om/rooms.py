"""Data rooms: private document workspaces fed by uploads, VDR exports and connectors.

Each room keeps its original files under data/rooms/<id>/files/ (so citations can open the source) and
indexes their text into the shared search index with room_id set. Re-importing a file with identical
bytes (same SHA-256 and path) is a no-op; a changed file replaces its previous version.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .docs import DocRef, passages
from .extract import SUPPORTED, extract

ROOMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms(id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, created_at REAL,
                                 connectors TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS room_events(id INTEGER PRIMARY KEY, room_id INTEGER, at REAL, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS ingest_state(room_id INTEGER, path TEXT, sha256 TEXT, status TEXT, reason TEXT, at REAL,
                                        PRIMARY KEY(room_id, path));
"""
SKIP_PARTS = {"__MACOSX", ".DS_Store", "Thumbs.db"}
MAX_FILE_BYTES = 200 * 1024 * 1024


@dataclass
class ImportResult:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list = None

    def as_dict(self):
        return {**self.__dict__, "warnings": (self.warnings or [])[:50]}


@dataclass
class IngestReport:
    added: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: list = field(default_factory=list)      # [(name, reason)]
    elapsed_s: float = 0.0
    files_per_s: float = 0.0
    interrupted: bool = False

    def as_dict(self):
        return {**self.__dict__, "failed": [list(f) for f in self.failed[:200]]}


class Rooms:
    def __init__(self, index, data_dir: Path):
        self._lock = threading.RLock()
        self.index = index
        self.db = index.db
        self.root = Path(data_dir) / "rooms"
        self.db.executescript(ROOMS_SCHEMA)

    # ------------------------------------------------------------------ rooms
    def create(self, name: str, description: str = "") -> int:
        cur = self.db.execute("INSERT INTO rooms(name, description, created_at) VALUES(?,?,?)", (name, description, time.time()))
        self.db.commit()
        return cur.lastrowid

    def get(self, name_or_id) -> dict:
        r = self.db.execute("SELECT * FROM rooms WHERE name=? OR id=?", (str(name_or_id), name_or_id)).fetchone()
        if not r:
            raise KeyError(f"no data room {name_or_id!r}")
        return dict(r)

    def list(self) -> list[dict]:
        rows = self.db.execute("""SELECT r.*, COUNT(d.doc_id) AS documents, COALESCE(SUM(d.pages),0) AS pages,
                                         MAX(d.ingested_at) AS last_import
                                  FROM rooms r LEFT JOIN documents d ON d.room_id = r.id GROUP BY r.id ORDER BY r.created_at DESC""")
        return [dict(r) for r in rows]

    def documents(self, room_id: int) -> list[dict]:
        rows = self.db.execute("""SELECT d.doc_id, d.path, d.title, d.form, d.pages, d.n_chars, d.source, d.filed, d.warnings,
                                         (SELECT COUNT(*) FROM chunks c WHERE c.doc_id=d.doc_id) AS passages
                                  FROM documents d WHERE d.room_id=? ORDER BY d.path""", (room_id,))
        return [dict(r) for r in rows]

    def file_path(self, doc_id: int) -> Path | None:
        r = self.db.execute("SELECT room_id, path FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if not r or r["room_id"] is None:
            return None
        p = (self.root / str(r["room_id"]) / "files" / r["path"]).resolve()
        base = (self.root / str(r["room_id"]) / "files").resolve()
        return p if base in p.parents and p.exists() else None

    def log(self, room_id: int, kind: str, detail) -> None:
        self.db.execute("INSERT INTO room_events(room_id, at, kind, detail) VALUES(?,?,?,?)",
                        (room_id, time.time(), kind, json.dumps(detail)))
        self.db.commit()

    def events(self, room_id: int, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM room_events WHERE room_id=? ORDER BY at DESC LIMIT ?", (room_id, limit))]

    # ------------------------------------------------------------------ import
    def add_file(self, room_id: int, rel_path: str, data: bytes, source: str = "upload",
                 modified: float | None = None, res: ImportResult | None = None) -> ImportResult:
        res = res or ImportResult(warnings=[])
        rel = _safe_rel(rel_path)
        if rel is None or any(part in SKIP_PARTS or part.startswith("._") for part in PurePosixPath(rel).parts):
            res.skipped += 1
            return res
        ext = PurePosixPath(rel).suffix.lower()
        if ext == ".zip":
            return self.add_zip(room_id, data, source=source, prefix=str(PurePosixPath(rel).with_suffix("")), res=res)
        if ext not in SUPPORTED:
            res.skipped += 1
            return res
        if len(data) > MAX_FILE_BYTES:
            res.skipped += 1
            res.warnings.append(f"{rel}: larger than {MAX_FILE_BYTES // 2**20} MB, skipped")
            return res
        sha = hashlib.sha256(data).hexdigest()
        prev = self.db.execute("SELECT doc_id, sha256 FROM documents WHERE room_id=? AND path=?", (room_id, rel)).fetchone()
        if prev and prev["sha256"] == sha:
            res.unchanged += 1
            return res
        dest = self.root / str(room_id) / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        try:
            ex = extract(dest)
        except Exception as e:
            res.failed += 1
            res.warnings.append(f"{rel}: {e}")
            return res
        ps, n = passages(ex.text, paged=True)
        if prev:
            self._delete_doc(prev["doc_id"])
        room = self.get(room_id)
        filed = time.strftime("%Y-%m-%d", time.localtime(modified or time.time()))
        ref = DocRef(cik=0, ticker=None, company=room["name"], form=ex.kind.upper(), filed=filed, report_date=None,
                     accession=sha[:20], file=PurePosixPath(rel).name, url=f"room://{room_id}/{rel}",
                     title=PurePosixPath(rel).name, items=None)
        self.index.add(ref, ps, n)
        self.db.execute("UPDATE documents SET room_id=?, source=?, path=?, pages=?, sha256=?, warnings=? WHERE url=?",
                        (room_id, source, rel, ex.pages, sha, json.dumps(ex.warnings) if ex.warnings else None, ref.url))
        self.db.commit()
        for w in ex.warnings:
            res.warnings.append(f"{rel}: {w}")
        if prev:
            res.updated += 1
        else:
            res.added += 1
        return res

    def add_zip(self, room_id: int, data: bytes, source: str = "zip", prefix: str = "", res: ImportResult | None = None) -> ImportResult:
        """A VDR bulk export (Datasite, Intralinks, Ansarada, Box…) keeps its folder index in the paths."""
        import io
        res = res or ImportResult(warnings=[])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                if info.file_size > MAX_FILE_BYTES:
                    res.skipped += 1
                    continue
                name = info.filename
                try:
                    name = name.encode("cp437").decode("utf-8")  # zips without the UTF-8 flag
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                mtime = time.mktime(info.date_time + (0, 0, -1))
                self.add_file(room_id, f"{prefix}/{name}" if prefix else name, z.read(info), source=source, modified=mtime, res=res)
        return res

    def add_path(self, room_id: int, path: Path, source: str = "folder") -> ImportResult:
        path = Path(path).expanduser()
        res = ImportResult(warnings=[])
        if path.is_file():
            if path.suffix.lower() == ".zip":
                return self.add_zip(room_id, path.read_bytes(), source=source, res=res)
            return self.add_file(room_id, path.name, path.read_bytes(), source=source, modified=path.stat().st_mtime, res=res)
        for f in sorted(path.rglob("*")):
            if f.is_file():
                self.add_file(room_id, str(f.relative_to(path)), f.read_bytes(), source=source, modified=f.stat().st_mtime, res=res)
        return res

    # ------------------------------------------------------------------ concurrent ingest
    def ingest(self, room, paths_or_dir, workers: int = 8, progress=None, *, max_bytes: int = MAX_FILE_BYTES,
               stop_after: int | None = None, source: str = "ingest") -> IngestReport:
        """Ingest many files: hash and extract in a thread pool, commit from this thread only (single writer).

        Content-hash dedupe within the room, idempotent re-runs (no writes when nothing is new) and resumable:
        each file's outcome is committed with its document, so an interrupted run continues where it stopped.
        progress(done, total, rel_path, status) is called after each file; an exception it raises aborts the run
        (finished files stay committed). stop_after=k stops cleanly after k files (test/resume hook)."""
        t0 = time.time()
        room_id = self.get(room)["id"]
        rep = IngestReport()
        items, rejected = _scan(paths_or_dir)
        total = len(items) + len(rejected)
        done = 0

        def tick(rel, status):
            nonlocal done
            done += 1
            if progress:
                progress(done, total, rel, status)

        def fail(rel, sha, reason):
            rep.failed.append((rel, reason))
            with self._lock:
                row = self.db.execute("SELECT status, reason FROM ingest_state WHERE room_id=? AND path=?", (room_id, rel)).fetchone()
                if not row or (row["status"], row["reason"]) != ("failed", reason):
                    self._state(room_id, rel, sha, "failed", reason)
                    self.db.commit()
            tick(rel, "failed")

        def finish():
            rep.elapsed_s = round(time.time() - t0, 4)
            rep.files_per_s = round(done / rep.elapsed_s, 2) if rep.elapsed_s > 0 else float(done)
            if rep.added:
                self.log(room_id, "ingest", {"added": rep.added, "duplicates": rep.duplicates, "skipped": rep.skipped,
                                             "failed": len(rep.failed)})
            return rep

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            try:
                for rel, reason in rejected:
                    fail(rel, None, reason)
                # phase 1: hash in parallel (cheap), classify deterministically in path order
                def hash_one(it):
                    rel, path = it
                    ext = PurePosixPath(rel).suffix.lower()
                    if ext not in SUPPORTED:
                        return rel, None, f"unsupported file type {ext or '(none)'}"
                    size = path.stat().st_size
                    if size == 0:
                        return rel, None, "empty file"
                    if size > max_bytes:
                        return rel, None, f"larger than {max_bytes // 2**20} MB"
                    h = hashlib.sha256()
                    with open(path, "rb") as f:
                        for block in iter(lambda: f.read(1 << 20), b""):
                            h.update(block)
                    return rel, h.hexdigest(), None
                hashed = []
                for it, fut in zip(items, [pool.submit(_guard, hash_one, it) for it in items]):
                    hashed.append((it[1], *fut.result()))
                with self._lock:
                    known = {r["sha256"] for r in self.db.execute("SELECT sha256 FROM documents WHERE room_id=? AND sha256 IS NOT NULL", (room_id,))}
                    state = {r["path"]: (r["sha256"], r["status"]) for r in self.db.execute(
                        "SELECT path, sha256, status FROM ingest_state WHERE room_id=?", (room_id,))}
                    docs = {r["path"]: r["sha256"] for r in self.db.execute("SELECT path, sha256 FROM documents WHERE room_id=?", (room_id,))}
                plan, seen = [], set()
                for path, rel, sha, err in hashed:
                    if err:
                        plan.append((rel, path, sha, "fail", err))
                    elif docs.get(rel) == sha or state.get(rel) in ((sha, "done"), (sha, "duplicate")):
                        plan.append((rel, path, sha, "skip", None))
                    elif sha in known or sha in seen:
                        plan.append((rel, path, sha, "dup", None))
                    else:
                        seen.add(sha)
                        plan.append((rel, path, sha, "new", None))
                # phase 2: extract the new, unique files in parallel; commit in order
                futs = {rel: pool.submit(_guard, _extract_one, path) for rel, path, sha, kind, _ in plan if kind == "new"}
                for rel, path, sha, kind, err in plan:
                    if stop_after is not None and done - len(rejected) >= stop_after:
                        rep.interrupted = True
                        break
                    if kind == "fail":
                        fail(rel, sha, err)
                    elif kind == "skip":
                        rep.skipped += 1
                        tick(rel, "skipped")
                    elif kind == "dup":
                        with self._lock:
                            self._state(room_id, rel, sha, "duplicate", None)
                            self.db.commit()
                        rep.duplicates += 1
                        tick(rel, "duplicate")
                    else:
                        ex = futs[rel].result()
                        if isinstance(ex, Exception):
                            fail(rel, sha, f"extract failed: {ex}")
                            continue
                        self._commit_ingested(room_id, rel, path, sha, ex, source)
                        rep.added += 1
                        tick(rel, "added")
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        return finish()

    def _state(self, room_id, rel, sha, status, reason):
        self.db.execute("INSERT OR REPLACE INTO ingest_state(room_id, path, sha256, status, reason, at) VALUES(?,?,?,?,?,?)",
                        (room_id, rel, sha, status, reason, time.time()))

    def _commit_ingested(self, room_id, rel, path: Path, sha, ex, source):
        with self._lock:
            dest = self.root / str(room_id) / "files" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            url = f"room://{room_id}/{rel}"
            old = self.db.execute("SELECT doc_id FROM documents WHERE url=?", (url,)).fetchone()
            if old:  # changed content under the same path, or a half-written doc from an interrupted run
                self._delete_doc(old["doc_id"])
            ps, n = passages(ex.text, paged=True)
            filed = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
            ref = DocRef(cik=0, ticker=None, company=self.get(room_id)["name"], form=ex.kind.upper(), filed=filed,
                         report_date=None, accession=sha[:20], file=PurePosixPath(rel).name, url=url,
                         title=PurePosixPath(rel).name, items=None)
            self.index.add(ref, ps, n)
            self.db.execute("UPDATE documents SET room_id=?, source=?, path=?, pages=?, sha256=?, warnings=? WHERE url=?",
                            (room_id, source, rel, ex.pages, sha, json.dumps(ex.warnings) if ex.warnings else None, url))
            self._state(room_id, rel, sha, "done", None)
            self.db.commit()

    def remove(self, doc_id: int) -> None:
        p = self.file_path(doc_id)
        self._delete_doc(doc_id)
        if p:
            p.unlink(missing_ok=True)

    def _delete_doc(self, doc_id: int) -> None:
        for (cid,) in self.db.execute("SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,)).fetchall():
            self.db.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
        self.db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        self.db.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
        self.db.commit()


def _safe_rel(p: str) -> str | None:
    parts = [x for x in PurePosixPath(p.replace("\\", "/")).parts if x not in ("", ".", "/")]
    if not parts or any(x == ".." for x in parts):
        return None
    return str(PurePosixPath(*parts))


def _guard(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # per-file failures are data, not control flow
        return e if fn is _extract_one else (a[0][0], None, f"{type(e).__name__}: {e}")


def _extract_one(path: Path):
    return extract(path)


def _hidden(parts) -> bool:
    return any(x in SKIP_PARTS or x.startswith(".") for x in parts)


def _scan(paths_or_dir) -> tuple[list, list]:
    """-> ([(rel, real_path)], [(rel, reason)]). Regular files only; hidden/__MACOSX skipped; symlinks must stay inside the root."""
    inputs = [paths_or_dir] if isinstance(paths_or_dir, (str, os.PathLike)) else list(paths_or_dir)
    items, rejected, names = [], [], set()

    def add(rel, p):
        if rel not in names:
            names.add(rel)
            items.append((rel, p))
    for inp in inputs:
        top = Path(inp).expanduser()
        prefix = top.name if len(inputs) > 1 else ""
        if top.is_file():
            if not _hidden([top.name]):
                add(top.name if not prefix else f"{top.parent.name}/{top.name}", top.resolve())
            continue
        base = top.resolve()
        for dp, dns, fns in os.walk(top, followlinks=False):
            rel_dir = Path(dp).relative_to(top)
            keep = []
            for d in sorted(dns):
                if _hidden([d]):
                    continue
                if (Path(dp) / d).is_symlink():
                    rejected.append((str(PurePosixPath(*rel_dir.parts, d)), "symlinked directory not followed"))
                else:
                    keep.append(d)
            dns[:] = keep
            for fn in sorted(fns):
                f = Path(dp) / fn
                rel = str(PurePosixPath(*rel_dir.parts, fn))
                if _hidden(PurePosixPath(rel).parts):
                    continue
                if prefix:
                    rel = f"{prefix}/{rel}"
                real = f.resolve()
                if f.is_symlink() and base not in real.parents:
                    rejected.append((rel, "symlink points outside the ingest folder"))
                elif not real.is_file():
                    continue
                elif base != real.parent and base not in real.parents:
                    rejected.append((rel, "path escapes the ingest folder"))
                else:
                    add(rel, real)
    return sorted(items), rejected
