"""Data-room connectors (S2.5): local folder, S3/MinIO prefix, uploaded archive -> om.rooms.Rooms.ingest.

Items are staged into a private temp directory (names sanitised, archives unpacked safely) and handed to
`Rooms.ingest`. Anything fetched is untrusted data."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from .base import Connector, ConnectorError, ConnectorItem, register
from .unpack import Limits, UnpackError, check_member_path, sanitize_component, unpack

_ARCHIVES = {".zip", ".eml", ".msg"}
MAX_STAGE_FILE = 512 * 1024 * 1024


@register("local_room")
class LocalFolderRoom(Connector):
    name = "local_room"

    def __init__(self, path: str, follow_symlinks: bool = False):
        self.root = Path(path).expanduser().resolve()
        if not self.root.is_dir():
            raise ConnectorError(f"folder not found: {self.root}")
        self.follow = follow_symlinks

    def _safe(self, p: Path) -> bool:
        if p.is_symlink() and not self.follow:
            return False
        rp = p.resolve()
        return rp == self.root or self.root in rp.parents

    def list(self):
        for f in sorted(self.root.rglob("*")):
            if f.is_file() and self._safe(f):
                st = f.stat()
                rel = f.relative_to(self.root).as_posix()
                yield ConnectorItem(rel, rel, st.st_size, f"{st.st_mtime_ns}:{st.st_size}")

    def fetch(self, item_id: str):
        p = (self.root / item_id)
        if not p.is_file() or not self._safe(p):
            raise ConnectorError(f"not a file inside the room: {item_id!r}")
        return p.read_bytes(), {"name": item_id, "source": "local_room"}


class S3ObjectLister:
    """Prefix listing + GET over S3/MinIO using om.storage's SigV4 signer. S3BlobStore only accepts sha256 keys, so
    this subclass relaxes the key check to ordinary object keys (no `..`, no NUL, no leading slash)."""

    def __new__(cls, *a, **kw):
        from om.storage import S3BlobStore

        class _Store(S3BlobStore):
            def _path(self, key=None):
                p = f"/{self.bucket}"
                if key is None:
                    return p + "/"
                if (not isinstance(key, str) or not key or "\x00" in key or key.startswith("/")
                        or ".." in key.split("/") or len(key.encode()) > 1024):
                    raise ValueError(f"unsafe object key {key!r}")
                return p + f"/{self.prefix}{key}"

            def list_objects(self, prefix: str = ""):
                token, out = None, []
                while True:
                    q = {"list-type": "2", "prefix": self.prefix + prefix}
                    if token:
                        q["continuation-token"] = token
                    _s, data = self._request("GET", None, query=q)
                    root = ET.fromstring(data)
                    ns = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
                    for c in root.iter(f"{ns}Contents"):
                        k = c.findtext(f"{ns}Key") or ""
                        if k.endswith("/"):
                            continue
                        out.append((k[len(self.prefix):], int(c.findtext(f"{ns}Size") or 0), c.findtext(f"{ns}ETag") or ""))
                    if (root.findtext(f"{ns}IsTruncated") or "").lower() == "true" and (
                            token := root.findtext(f"{ns}NextContinuationToken")):
                        continue
                    return sorted(out)
        return _Store(*a, **kw)


@register("s3_room")
class S3Room(Connector):
    """S3/MinIO prefix. Credentials come from ACRETIA_S3_ACCESS_KEY/SECRET_KEY (never from config)."""
    name = "s3_room"

    def __init__(self, endpoint: str, bucket: str, prefix: str = "", region: str = "us-east-1", transport=None,
                 store=None, **_ignored):
        for k in ("access_key", "secret_key"):
            if k in _ignored:
                raise ConnectorError("do not pass S3 credentials in config; use ACRETIA_S3_ACCESS_KEY/SECRET_KEY")
        self.store = store or S3ObjectLister(endpoint, bucket, region=region, transport=transport)
        self.prefix = prefix.lstrip("/")
        self.bucket = bucket

    def list(self):
        for key, size, etag in self.store.list_objects(self.prefix):
            rel = key[len(self.prefix):].lstrip("/") if key.startswith(self.prefix) else key
            yield ConnectorItem(key, rel or PurePosixPath(key).name, size, etag.strip('"'))

    def fetch(self, item_id: str):
        return self.store.get(item_id), {"name": item_id, "source": "s3_room", "bucket": self.bucket}


@register("archive_room")
class ArchiveRoom(Connector):
    """An uploaded .zip/.eml/.msg (bytes or path). Unpacked safely into `workdir` on first list()."""
    name = "archive_room"

    def __init__(self, data: bytes | None = None, path: str | None = None, filename: str = "upload.zip",
                 limits: Limits | None = None, workdir: str | None = None):
        if (data is None) == (path is None):
            raise ConnectorError("give exactly one of data= or path=")
        self.data, self.path, self.filename, self.limits = data, path, filename, limits
        self._own = workdir is None
        self.workdir = Path(workdir or tempfile.mkdtemp(prefix="acretia-archive-"))
        self._res = None

    def _unpack(self):
        if self._res is None:
            self._res = unpack(self.data if self.data is not None else self.path, self.workdir / "x",
                               name=self.filename, limits=self.limits)
        return self._res

    def list(self):
        for f in self._unpack().files:
            yield ConnectorItem(f["path"], f["path"], f["size"], f["sha256"], {"origin": f["origin"]})

    def fetch(self, item_id: str):
        self._unpack()
        p = (self.workdir / "x" / item_id).resolve()
        if (self.workdir / "x").resolve() not in p.parents or not p.is_file():
            raise ConnectorError(f"unknown item {item_id!r}")
        return p.read_bytes(), {"name": item_id, "source": "archive_room"}

    def close(self):
        if self._own:
            shutil.rmtree(self.workdir, ignore_errors=True)


def stage(connector: Connector, dest: Path, limits: Limits | None = None, max_file: int = MAX_STAGE_FILE) -> dict:
    """Materialise a connector into `dest`: sanitised names, nested archives unpacked safely. Returns a receipt
    {"staged": n, "rejected": [(name, reason)], "notes": [...]}."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    staged, rejected, notes = 0, [], []
    used = set()
    for item in connector.list():
        try:
            if item.size > max_file:
                raise UnpackError(f"{item.size} bytes exceeds {max_file}")
            data, _meta = connector.fetch(item.id)
            parts = check_member_path(item.name) or [sanitize_component(item.id)]
            rel = "/".join(parts)
            if rel in used:
                rel = f"{hashlib.sha256(item.id.encode()).hexdigest()[:8]}_{rel}"
            used.add(rel)
            if PurePosixPath(rel).suffix.lower() in _ARCHIVES:
                sub = dest / (rel + ".d")
                res = unpack(data, sub, name=PurePosixPath(rel).name, limits=limits)
                notes += res.notes
                staged += len(res.files)
            else:
                p = dest.joinpath(*parts)
                if dest.resolve() not in p.resolve().parents:
                    raise UnpackError("path escapes staging dir")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                staged += 1
        except Exception as e:  # one bad item never aborts the room
            rejected.append((item.name, f"{type(e).__name__}: {e}"[:200]))
    return {"staged": staged, "rejected": rejected, "notes": notes}


def ingest(rooms, room, connector: Connector, *, limits: Limits | None = None, workers: int = 8, progress=None,
           keep_stage: str | None = None, **kw):
    """connector -> staging dir -> `om.rooms.Rooms.ingest`. Returns (IngestReport, stage_receipt)."""
    tmp = Path(keep_stage) if keep_stage else Path(tempfile.mkdtemp(prefix="acretia-stage-"))
    try:
        receipt = stage(connector, tmp, limits)
        rep = rooms.ingest(room, tmp, workers=workers, progress=progress, source=f"connector:{connector.name}", **kw)
        for name, why in receipt["rejected"]:
            rep.failed.append((name, why))
        return rep, receipt
    finally:
        if not keep_stage:
            shutil.rmtree(tmp, ignore_errors=True)
