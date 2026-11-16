"""Evidence bundle: an append-only, hash-chained JSONL file per job (stdlib only).

One record per tool call: ``{job_id, seq, tool, args_sha256, source, page, bbox_norm, timestamp, output_sha256,
prev_hash, record_hash}``. Raw args/output are never stored (only SHA-256 over canonical JSON) unless the bundle is
opened with ``store_payloads=True``, which writes them to a sibling content-addressed directory.

``job_id`` is the file stem, so swapping in a valid chain from another job is detected by ``verify``.
"""
from __future__ import annotations

import functools
import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

from om.contracts import ContractError, sha256_hex

GENESIS_HASH = "0" * 64
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_KEYS = ("job_id", "seq", "tool", "args_sha256", "source", "page", "bbox_norm", "timestamp", "output_sha256",
         "prev_hash", "record_hash")


def canonical_bytes(obj) -> bytes:
    """Canonical JSON bytes; ``bytes``/``bytearray`` are returned raw."""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _canon_str(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_hash(rec: dict) -> str:
    return sha256_hex(_canon_str({k: v for k, v in rec.items() if k != "record_hash"}))


def _bbox_error(bbox) -> str | None:
    if bbox is None:
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return "bbox_norm must be a list of 4 numbers"
    for v in bbox:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "bbox_norm entries must be finite numbers"
        if v < 0 or v > 1:
            return f"bbox_norm entry {v} outside [0,1]"
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    n_records: int
    first_bad_seq: int | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _read_lines(path) -> list[bytes]:
    data = Path(path).read_bytes()
    if not data:
        return []
    lines = data.split(b"\n")
    # a well-formed file ends with "\n" -> final element is empty; otherwise the last line is truncated
    return lines[:-1] + ([lines[-1]] if lines[-1] else [])


def verify(path) -> VerifyResult:
    """Check the whole chain. ``first_bad_seq`` is the zero-based position of the first offending line."""
    path = Path(path)
    if not path.exists():
        return VerifyResult(False, 0, 0, "file does not exist")
    data = path.read_bytes()
    lines = _read_lines(path)
    job_id = path.stem
    prev_hash, prev_ts, n = GENESIS_HASH, "", 0
    for i, raw in enumerate(lines):
        def bad(reason, i=i, n=n):
            return VerifyResult(False, n, i, reason)
        last = i == len(lines) - 1
        if last and not data.endswith(b"\n"):
            return bad("truncated last line")
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return bad("line is not valid JSON")
        if not isinstance(rec, dict) or set(rec) != set(_KEYS):
            return bad("record has missing or unexpected fields")
        if rec["job_id"] != job_id:
            return bad(f"job_id {rec['job_id']!r} does not match bundle {job_id!r}")
        if rec["seq"] != i or isinstance(rec["seq"], bool):
            return bad(f"seq {rec['seq']!r} != expected {i} (deleted, inserted, reordered or duplicated line)")
        if rec["prev_hash"] != prev_hash:
            return bad("prev_hash does not match previous record")
        if not isinstance(rec["record_hash"], str) or rec["record_hash"] != _record_hash(rec):
            return bad("record_hash mismatch (record edited)")
        ts = rec["timestamp"]
        try:
            datetime.strptime(ts, _TS_FORMAT)
        except (TypeError, ValueError):
            return bad("timestamp is not UTC ISO-8601 with 'Z'")
        if ts < prev_ts:
            return bad(f"timestamp {ts} earlier than previous {prev_ts}")
        err = _bbox_error(rec["bbox_norm"])
        if err:
            return bad(err)
        prev_hash, prev_ts, n = rec["record_hash"], ts, n + 1
    return VerifyResult(True, n, None, "")


def head_hash(path) -> str:
    """record_hash of the last record (genesis zeros for an empty/missing bundle)."""
    lines = _read_lines(path) if Path(path).exists() else []
    return json.loads(lines[-1])["record_hash"] if lines else GENESIS_HASH


def export(path) -> list[dict]:
    """All records, parsed. Raises ``ContractError`` if the chain does not verify."""
    res = verify(path)
    if not res.ok:
        raise ContractError(f"{path}: seq {res.first_bad_seq}: {res.reason}")
    return [json.loads(line) for line in _read_lines(path)]


class EvidenceBundle:
    """Append-only evidence log for one job. ``job_id`` is the file stem."""

    def __init__(self, path, *, store_payloads: bool = False):
        self.path = Path(path)
        self.job_id = self.path.stem
        self.store_payloads = store_payloads
        self.payload_dir = self.path.with_name(self.path.stem + ".payloads")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self.path, "ab+")
        if store_payloads:
            self.payload_dir.mkdir(parents=True, exist_ok=True)

    # -- lifecycle -------------------------------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- internals -------------------------------------------------------------------------------------------
    def _last_record(self) -> dict | None:
        """Read the final line from disk (so another process's appends are seen). Caller holds the locks."""
        fh = self._fh
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == 0:
            return None
        pos, buf = size, b""
        while pos > 0 and buf.count(b"\n") < 2:
            step = min(8192, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
        if not buf.endswith(b"\n"):
            raise ContractError(f"{self.path}: last line is truncated; refusing to append")
        last = buf[:-1].rsplit(b"\n", 1)[-1]
        try:
            return json.loads(last.decode("utf-8"))
        except ValueError as e:
            raise ContractError(f"{self.path}: last line is corrupt: {e}") from None

    def _store(self, payload: bytes) -> str:
        digest = sha256_hex(payload)
        target = self.payload_dir / digest
        if not target.exists():
            tmp = self.payload_dir / f".{digest}.{os.getpid()}.{threading.get_ident()}.tmp"
            tmp.write_bytes(payload)
            os.replace(tmp, target)
        return digest

    def load_payload(self, sha256: str) -> bytes:
        """Return the stored payload bytes for a hash (requires ``store_payloads=True`` at write time)."""
        data = (self.payload_dir / sha256).read_bytes()
        if sha256_hex(data) != sha256:
            raise ContractError(f"payload {sha256}: content does not match its hash")
        return data

    # -- API -------------------------------------------------------------------------------------------------
    def append(self, tool, args, *, source, page=None, bbox_norm=None, output) -> dict:
        if not isinstance(tool, str) or not tool:
            raise ContractError("tool: must be a non-empty string")
        err = _bbox_error(bbox_norm)
        if err:
            raise ContractError(err)
        if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
            raise ContractError("page: must be an int or None")
        args_b, out_b = canonical_bytes(args), canonical_bytes(output)
        with self._lock:
            if fcntl:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            try:
                last = self._last_record()
                seq = 0 if last is None else last["seq"] + 1
                prev_hash = GENESIS_HASH if last is None else last["record_hash"]
                ts = _now()
                if last is not None and ts < last["timestamp"]:
                    ts = last["timestamp"]  # clock stepped back: keep timestamps monotonic
                rec = {
                    "job_id": self.job_id, "seq": seq, "tool": tool, "args_sha256": sha256_hex(args_b),
                    "source": source, "page": page,
                    "bbox_norm": None if bbox_norm is None else [float(v) for v in bbox_norm],
                    "timestamp": ts, "output_sha256": sha256_hex(out_b), "prev_hash": prev_hash,
                }
                rec["record_hash"] = _record_hash(rec)
                if self.store_payloads:
                    self._store(args_b)
                    self._store(out_b)
                self._fh.seek(0, os.SEEK_END)
                self._fh.write((_canon_str(rec) + "\n").encode("utf-8"))
                self._fh.flush()
                os.fsync(self._fh.fileno())
            finally:
                if fcntl:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        return rec

    def head_hash(self) -> str:
        return head_hash(self.path)

    def verify(self) -> VerifyResult:
        return verify(self.path)

    def export(self) -> list[dict]:
        return export(self.path)


def traced(bundle: EvidenceBundle, tool_name: str, source_fn=None):
    """Decorator: record each call of the wrapped function in ``bundle``.

    ``source_fn(result, *args, **kwargs)`` may return a source string or a dict with ``source`` and optional
    ``page`` / ``bbox_norm``; default source is ``tool_name``. If the function raises, nothing is recorded.
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            src = source_fn(result, *args, **kwargs) if source_fn else tool_name
            extra = {}
            if isinstance(src, dict):
                extra = {k: src[k] for k in ("page", "bbox_norm") if k in src}
                src = src.get("source", tool_name)
            bundle.append(tool_name, {"args": list(args), "kwargs": kwargs}, source=src, output=result, **extra)
            return result
        return wrapper
    return deco
