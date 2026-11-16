"""DealMemory workspace (P1.4): per-deal accounting definitions, formatting preferences and a versioned,
content-addressed deliverable history with inspectable diffs and non-destructive undo.

Every table carries ``org_id`` (default "local") and every query filters on it (M6 multi-tenancy hook).
"""
from __future__ import annotations

import difflib
import io
import json
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

from . import xlsx as _xlsx
from .contracts import ContractError, DealMemory, MemoryVersion, sha256_hex
from .storage import connect

KINDS = ("xlsx", "pptx", "docx", "json", "other")
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deals(
  org_id TEXT NOT NULL DEFAULT 'local', deal_id TEXT NOT NULL, name TEXT NOT NULL,
  definitions TEXT NOT NULL DEFAULT '{}', formatting TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
  PRIMARY KEY(org_id, deal_id));
CREATE TABLE IF NOT EXISTS deal_memory_versions(
  org_id TEXT NOT NULL DEFAULT 'local', deal_id TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '', definitions TEXT NOT NULL, formatting TEXT NOT NULL,
  PRIMARY KEY(org_id, deal_id, version));
CREATE TABLE IF NOT EXISTS deal_deliverables(
  org_id TEXT NOT NULL DEFAULT 'local', deal_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL,
  kind TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, PRIMARY KEY(org_id, deal_id, name, version));
"""


class DealError(ValueError):
    """Unknown deal/version, bad kind, or an unreadable deliverable."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DealStore:
    def __init__(self, db, blobs, org_id: str = "local"):
        self.db = connect(db) if isinstance(db, str) else db
        self.blobs = blobs
        self.org_id = org_id
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def for_org(self, org_id: str) -> "DealStore":
        """A view of the same database/blobs scoped to another org."""
        return DealStore(self.db, self.blobs, org_id)

    # ------------------------------------------------------------------ deals
    def _row(self, deal_id):
        r = self.db.execute("SELECT * FROM deals WHERE org_id=? AND deal_id=?", (self.org_id, deal_id)).fetchone()
        if r is None:
            raise DealError(f"unknown deal {deal_id!r}")
        return r

    def _memory(self, r) -> DealMemory:
        vs = self.db.execute("SELECT version, created_at, note FROM deal_memory_versions WHERE org_id=? AND deal_id=? "
                             "ORDER BY version", (self.org_id, r["deal_id"])).fetchall()
        return DealMemory(r["deal_id"], r["name"], json.loads(r["definitions"]), json.loads(r["formatting"]),
                          [MemoryVersion(v["version"], v["created_at"], v["note"]) for v in vs]).validate()

    def _snapshot(self, deal_id, note):
        r = self._row(deal_id)
        n = self.db.execute("SELECT COALESCE(MAX(version),0)+1 FROM deal_memory_versions WHERE org_id=? AND deal_id=?",
                            (self.org_id, deal_id)).fetchone()[0]
        self.db.execute("INSERT INTO deal_memory_versions VALUES(?,?,?,?,?,?,?)",
                        (self.org_id, deal_id, n, _now(), note, r["definitions"], r["formatting"]))

    def create_deal(self, name: str, definitions: dict | None = None, formatting: dict | None = None) -> DealMemory:
        deal_id = "deal-" + uuid.uuid4().hex[:12]
        DealMemory(deal_id, name, dict(definitions or {}), dict(formatting or {})).validate()
        with self.db:
            self.db.execute("INSERT INTO deals VALUES(?,?,?,?,?,?)",
                            (self.org_id, deal_id, name, json.dumps(definitions or {}, sort_keys=True),
                             json.dumps(formatting or {}, sort_keys=True), _now()))
            self._snapshot(deal_id, "created")
        return self.get(deal_id)

    def get(self, deal_id: str) -> DealMemory:
        return self._memory(self._row(deal_id))

    def list(self) -> list:
        rows = self.db.execute("SELECT * FROM deals WHERE org_id=? ORDER BY created_at, deal_id", (self.org_id,)).fetchall()
        return [self._memory(r) for r in rows]

    def _update(self, deal_id, col, mutate, note):
        r = self._row(deal_id)
        cur = json.loads(r[col])
        mutate(cur)
        mem = self._memory(r)
        setattr(mem, col, cur)
        mem.validate()
        with self.db:
            self.db.execute(f"UPDATE deals SET {col}=? WHERE org_id=? AND deal_id=?",
                            (json.dumps(cur, sort_keys=True), self.org_id, deal_id))
            self._snapshot(deal_id, note)
        return self.get(deal_id)

    def set_definition(self, deal_id: str, key: str, text: str) -> DealMemory:
        if not isinstance(key, str) or not key.strip():
            raise DealError("definition key must be a non-empty string")
        return self._update(deal_id, "definitions", lambda d: d.__setitem__(key, text), f"definition: {key}")

    def set_formatting(self, deal_id: str, **prefs) -> DealMemory:
        """e.g. units="USD m", negative_style="(1.0)", decimals=1, fiscal_year_end="12-31"."""
        return self._update(deal_id, "formatting", lambda d: d.update(prefs), "formatting: " + ", ".join(sorted(prefs)))

    def memory_at(self, deal_id: str, version: int) -> dict:
        self._row(deal_id)
        r = self.db.execute("SELECT * FROM deal_memory_versions WHERE org_id=? AND deal_id=? AND version=?",
                            (self.org_id, deal_id, version)).fetchone() if _posint(version) else None
        if r is None:
            raise DealError(f"deal {deal_id!r} has no memory version {version!r}")
        return {"definitions": json.loads(r["definitions"]), "formatting": json.loads(r["formatting"])}

    def diff_definitions(self, deal_id: str, v_a: int, v_b: int) -> dict:
        a, b = self.memory_at(deal_id, v_a), self.memory_at(deal_id, v_b)
        out = {}
        for sec in ("definitions", "formatting"):
            x, y = a[sec], b[sec]
            out[sec] = {"added": {k: y[k] for k in y.keys() - x.keys()},
                        "removed": {k: x[k] for k in x.keys() - y.keys()},
                        "changed": {k: {"old": x[k], "new": y[k]} for k in x.keys() & y.keys() if x[k] != y[k]}}
        return out

    # ------------------------------------------------------------------ deliverables
    def save_deliverable(self, deal_id: str, name: str, data: bytes, kind: str, note: str = "") -> dict:
        self._row(deal_id)
        if kind not in KINDS:
            raise DealError(f"kind must be one of {KINDS}, got {kind!r}")
        if not isinstance(name, str) or not name.strip():
            raise DealError("deliverable name must be a non-empty string")
        if not isinstance(data, (bytes, bytearray)):
            raise DealError("data must be bytes")
        return self._append(deal_id, name, bytes(data), kind, note)

    def _append(self, deal_id, name, data, kind, note):
        sha = self.blobs.put(data)
        with self.db:
            n = self.db.execute("SELECT COALESCE(MAX(version),0)+1 FROM deal_deliverables WHERE org_id=? AND deal_id=? AND name=?",
                                (self.org_id, deal_id, name)).fetchone()[0]
            ts = _now()
            self.db.execute("INSERT INTO deal_deliverables VALUES(?,?,?,?,?,?,?,?,?)",
                            (self.org_id, deal_id, name, n, kind, sha, len(data), note, ts))
        return {"name": name, "version": n, "kind": kind, "sha256": sha, "size": len(data), "note": note, "created_at": ts}

    def history(self, deal_id: str, name: str) -> list:
        self._row(deal_id)
        rows = self.db.execute("SELECT name, version, kind, sha256, size, note, created_at FROM deal_deliverables "
                               "WHERE org_id=? AND deal_id=? AND name=? ORDER BY version",
                               (self.org_id, deal_id, name)).fetchall()
        return [dict(r) for r in rows]

    def deliverables(self, deal_id: str) -> list:
        self._row(deal_id)
        return [r[0] for r in self.db.execute("SELECT DISTINCT name FROM deal_deliverables WHERE org_id=? AND deal_id=? "
                                              "ORDER BY name", (self.org_id, deal_id))]

    def _meta(self, deal_id, name, version):
        self._row(deal_id)
        r = self.db.execute("SELECT * FROM deal_deliverables WHERE org_id=? AND deal_id=? AND name=? AND version=?",
                            (self.org_id, deal_id, name, version)).fetchone() if _posint(version) else None
        if r is None:
            raise DealError(f"deliverable {name!r} of deal {deal_id!r} has no version {version!r}")
        return r

    def get_version(self, deal_id: str, name: str, version: int) -> bytes:
        return self.blobs.get(self._meta(deal_id, name, version)["sha256"])

    def restore(self, deal_id: str, name: str, version: int, note: str = "") -> dict:
        m = self._meta(deal_id, name, version)
        return self._append(deal_id, name, self.blobs.get(m["sha256"]), m["kind"], note or f"restore of v{version}")

    def undo(self, deal_id: str, name: str) -> dict:
        h = self.history(deal_id, name)
        if len(h) < 2:
            raise DealError(f"nothing to undo for {name!r}: needs at least 2 versions, has {len(h)}")
        return self.restore(deal_id, name, h[-2]["version"], note=f"undo of v{h[-1]['version']}")

    # ------------------------------------------------------------------ diffs
    def diff(self, deal_id: str, name: str, v_a: int, v_b: int) -> dict:
        """{"kind", "name", "v_a", "v_b", "identical", "changes": [...]}.
        xlsx change: {sheet, ref, old, new} (old/new = value, or the formula string starting "=" when present).
        pptx change: {slide, removed: [text], added: [text]}. Text kinds: {"unified": [lines]}."""
        ma, mb = self._meta(deal_id, name, v_a), self._meta(deal_id, name, v_b)
        a, b = self.blobs.get(ma["sha256"]), self.blobs.get(mb["sha256"])
        kind = mb["kind"]
        res = {"kind": kind, "name": name, "v_a": v_a, "v_b": v_b, "identical": a == b, "changes": []}
        if a == b:
            return res
        try:
            if kind == "xlsx":
                res["changes"] = diff_xlsx(a, b)
            elif kind == "pptx":
                res["changes"] = diff_pptx(a, b)
            else:
                res["changes"] = [{"unified": diff_text(a, b, f"v{v_a}", f"v{v_b}")}]
        except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
            raise DealError(f"cannot diff {name!r} as {kind}: unreadable file ({type(e).__name__}: {e})") from None
        return res


def _posint(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _cellval(c):
    return c.formula if c.formula else c.value


def diff_xlsx(a: bytes, b: bytes) -> list:
    ba, bb = _xlsx.read(a), _xlsx.read(b)
    out = []
    for sheet in list(ba.order or ba.sheets) + [s for s in (bb.order or bb.sheets) if s not in ba.sheets]:
        ga, gb = ba.sheets.get(sheet, {}), bb.sheets.get(sheet, {})
        for rc in sorted(set(ga) | set(gb)):
            ca, cb = ga.get(rc), gb.get(rc)
            va, vb = (_cellval(ca) if ca else None), (_cellval(cb) if cb else None)
            if va != vb:
                out.append({"sheet": sheet, "ref": _xlsx.ref(*rc), "old": va, "new": vb})
    return out


def _slide_texts(data: bytes) -> list:
    z = zipfile.ZipFile(io.BytesIO(data))
    parts = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                   key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    return [[(t.text or "") for t in ET.fromstring(z.read(p)).iter(f"{_A}t") if (t.text or "").strip()] for p in parts]


def diff_pptx(a: bytes, b: bytes) -> list:
    sa, sb = _slide_texts(a), _slide_texts(b)
    out = []
    for i in range(max(len(sa), len(sb))):
        ta, tb = (sa[i] if i < len(sa) else []), (sb[i] if i < len(sb) else [])
        if ta != tb:
            removed, added = [t for t in ta if t not in tb], [t for t in tb if t not in ta]
            out.append({"slide": i + 1, "removed": removed, "added": added})
    return out


def diff_text(a: bytes, b: bytes, la="a", lb="b") -> list:
    x = a.decode("utf-8", "replace").splitlines()
    y = b.decode("utf-8", "replace").splitlines()
    return list(difflib.unified_diff(x, y, la, lb, lineterm=""))
