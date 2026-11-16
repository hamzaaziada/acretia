"""Data rooms: private document workspaces fed by uploads, VDR exports and connectors.

Each room keeps its original files under data/rooms/<id>/files/ (so citations can open the source) and
indexes their text into the shared search index with room_id set. Re-importing a file with identical
bytes (same SHA-256 and path) is a no-op; a changed file replaces its previous version.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .docs import DocRef, passages
from .extract import SUPPORTED, extract

ROOMS_SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms(id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, created_at REAL,
                                 connectors TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS room_events(id INTEGER PRIMARY KEY, room_id INTEGER, at REAL, kind TEXT, detail TEXT);
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


class Rooms:
    def __init__(self, index, data_dir: Path):
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
