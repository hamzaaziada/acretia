"""Evidence bundle: an append-only, hash-chained JSONL file per job (stdlib only).

One record per tool call: ``{job_id, seq, tool, args_sha256, source, page, bbox_norm, timestamp, output_sha256,
prev_hash, record_hash}``. Raw args/output are never stored (only SHA-256 over canonical JSON) unless the bundle is
opened with ``store_payloads=True``, which writes them to a sibling content-addressed directory.

``job_id`` is the file stem, so swapping in a valid chain from another job is detected by ``verify``.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
from dataclasses import asdict, dataclass
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


def verify(path, anchor=None, *, key=None, anchor_dir=None) -> VerifyResult:
    """Check the whole chain. ``first_bad_seq`` is the zero-based position of the first offending line.

    ``anchor`` (F4) pins the chain to a signed external head. The default (``None``) is ``"auto"`` whenever an
    ``anchors.jsonl`` exists in ``anchor_dir`` (default: next to the bundle), so a truncated or rolled-back bundle
    cannot pass by accident. ``"auto"`` requires and checks every anchor sealed for this job; an ``Anchor`` or its
    dict is checked directly. Plain chain-only checking needs an explicit ``anchor=False``."""
    res, hashes = _verify_chain(path)
    if not res.ok or anchor is False:
        return res
    if anchor is None:
        if not anchor_log_path(anchor_dir or Path(path).parent).exists():
            return res
        anchor = "auto"
    return _check_anchors(Path(path), res, hashes, anchor, key, anchor_dir)


def _verify_chain(path) -> tuple[VerifyResult, list[str]]:
    path = Path(path)
    if not path.exists():
        return VerifyResult(False, 0, 0, "file does not exist"), []
    data = path.read_bytes()
    lines = _read_lines(path)
    job_id = path.stem
    prev_hash, prev_ts, n = GENESIS_HASH, "", 0
    hashes: list[str] = []
    for i, raw in enumerate(lines):
        def bad(reason, i=i, n=n):
            return VerifyResult(False, n, i, reason), []
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
        hashes.append(prev_hash)
    return VerifyResult(True, n, None, ""), hashes


# --------------------------------------------------------------------------- anchoring (F4)

_ANCHOR_FIELDS = ("job_id", "n_records", "head_hash", "sealed_at")

KEY_FILE_DEFAULT = "storage/keys/evidence.key"   # deliberately NOT under storage/evidence (N3 key custody)


@dataclass(frozen=True)
class Anchor:
    """A signed claim "job ``job_id`` had ``n_records`` records ending in ``head_hash`` at ``sealed_at``".

    ``seq`` is monotonic per job (1, 2, ...) and is covered by the signature: ``verify`` rejects a bundle that only
    matches an older anchor than the latest one (rollback). ``None`` marks a legacy anchor sealed before ``seq``."""
    job_id: str
    n_records: int
    head_hash: str
    sealed_at: str
    signature: str
    seq: int | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        if d["seq"] is None:
            del d["seq"]
        return d

    @classmethod
    def from_dict(cls, d) -> "Anchor":
        if isinstance(d, Anchor):
            return d
        base = set(_ANCHOR_FIELDS) | {"signature"}
        if not isinstance(d, dict) or set(d) not in (base, base | {"seq"}):
            raise ContractError("anchor: missing or unexpected fields")
        seq = d.get("seq")
        if "seq" in d and (isinstance(seq, bool) or not isinstance(seq, int) or seq < 1):
            raise ContractError("anchor: seq must be an int >= 1")
        return cls(d["job_id"], d["n_records"], d["head_hash"], d["sealed_at"], d["signature"], seq)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _key_file_path() -> Path:
    return Path(os.environ.get("ACRETIA_EVIDENCE_KEY_FILE") or KEY_FILE_DEFAULT)


def _check_key_file(kp: Path, data_dir) -> None:
    """Key custody (N3): refuse a key file inside the evidence data dir or readable by group/others."""
    if data_dir is not None and _is_under(kp, Path(data_dir)):
        raise ContractError(f"evidence key file {kp} lives under the evidence data dir {data_dir}; anyone who can "
                            "write the bundle could read it and forge anchors. Keep it in storage/keys/ (or set "
                            "ACRETIA_EVIDENCE_KEY from a secret store)")
    if os.name == "posix" and kp.exists() and kp.stat().st_mode & 0o077:
        raise ContractError(f"evidence key file {kp} is group- or world-accessible (mode "
                            f"{kp.stat().st_mode & 0o777:03o}); run chmod 600 {kp}. Refusing to use it")


def _key_bytes(key=None, *, create: bool = True, data_dir=None) -> bytes | None:
    """Per-deployment HMAC key: explicit ``key`` > ``ACRETIA_EVIDENCE_KEY`` > ``storage/keys/evidence.key``
    (``ACRETIA_EVIDENCE_KEY_FILE`` overrides the path; created 0600 in a 0700 dir on first use when ``create``).
    The key file must not be under ``data_dir`` and must not be group/world readable. Production should set
    ``ACRETIA_EVIDENCE_KEY`` from a secret store so no key file exists at all. Never logged or written to a bundle."""
    if key is not None:
        return key if isinstance(key, bytes) else str(key).encode("utf-8")
    env = os.environ.get("ACRETIA_EVIDENCE_KEY")
    if env:
        return env.encode("utf-8")
    kp = _key_file_path()
    _check_key_file(kp, data_dir)
    if kp.exists():
        data = kp.read_bytes().strip()
        return data or None
    if not create:
        return None
    if not kp.parent.exists():
        kp.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(kp.parent, 0o700)
    try:
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # lost a creation race: read the winner's key
        for _ in range(50):
            data = kp.read_bytes().strip()
            if data:
                return data
            threading.Event().wait(0.02)
        return None
    with os.fdopen(fd, "wb") as fh:
        fh.write(secrets.token_hex(32).encode("ascii"))
    return kp.read_bytes().strip()


def _state_dir() -> Path | None:
    """Where per-job anchor high-water marks live (rollback guard): ``ACRETIA_EVIDENCE_STATE_DIR``, else the key
    file's directory when a key file (not an env key) is in use. Outside the evidence data dir by construction."""
    env = os.environ.get("ACRETIA_EVIDENCE_STATE_DIR")
    if env:
        return Path(env)
    if os.environ.get("ACRETIA_EVIDENCE_KEY"):
        return None
    return _key_file_path().parent


def _hw_path(job_id: str) -> Path | None:
    d = _state_dir()
    return None if d is None else d / "anchor-heads" / f"{job_id}.seq"


def _read_hw(job_id: str) -> int:
    p = _hw_path(job_id)
    try:
        return int(p.read_text().split()[0]) if p and p.exists() else 0
    except (OSError, ValueError, IndexError):
        return 0


def _write_hw(job_id: str, seq: int) -> None:
    p = _hw_path(job_id)
    if p is None:
        return
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(f"{seq}\n")
    os.replace(tmp, p)


def _sign(key: bytes, job_id, n_records, head, sealed_at, seq=None) -> str:
    body = {"job_id": job_id, "n_records": n_records, "head_hash": head, "sealed_at": sealed_at}
    if seq is not None:
        body["seq"] = seq
    return hmac.new(key, _canon_str(body).encode("utf-8"), hashlib.sha256).hexdigest()


def anchor_log_path(directory) -> Path:
    return Path(directory) / "anchors.jsonl"


def _entry_hash(entry: dict) -> str:
    return sha256_hex(_canon_str({k: v for k, v in entry.items() if k != "entry_hash"}))


def _read_anchor_log(directory) -> tuple[list[Anchor], str | None]:
    """All anchors in log order; second item is an error string if the log chain is broken."""
    p = anchor_log_path(directory)
    if not p.exists():
        return [], None
    prev, out = GENESIS_HASH, []
    for i, raw in enumerate(p.read_bytes().split(b"\n")):
        if not raw:
            continue
        try:
            e = json.loads(raw.decode("utf-8"))
            a = Anchor.from_dict(e["anchor"])
            ok = e["prev_hash"] == prev and e["entry_hash"] == _entry_hash(e) and set(e) == {"anchor", "prev_hash", "entry_hash"}
        except (ValueError, KeyError, TypeError, ContractError, UnicodeDecodeError):
            return out, f"anchor log line {i} is corrupt"
        if not ok:
            return out, f"anchor log line {i} breaks the anchor chain"
        prev = e["entry_hash"]
        out.append(a)
    return out, None


def _append_anchor(directory, make) -> Anchor:
    """Append the anchor returned by ``make(next_seq)`` under the log's exclusive lock, so seqs are gap-free and
    monotonic per job even across processes."""
    p = anchor_log_path(directory)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab+") as fh:
        if fcntl:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            existing, err = _read_anchor_log(directory)
            if err:
                raise ContractError(f"{p}: {err}; refusing to append")
            probe = make(None)
            seqs = [a.seq or 0 for a in existing if a.job_id == probe.job_id]
            anchor = make(max(seqs + [_read_hw(probe.job_id)]) + 1)
            fh.seek(0)
            lines = [ln for ln in fh.read().split(b"\n") if ln]
            prev = json.loads(lines[-1])["entry_hash"] if lines else GENESIS_HASH
            e = {"anchor": anchor.as_dict(), "prev_hash": prev}
            e["entry_hash"] = _entry_hash(e)
            fh.seek(0, os.SEEK_END)
            fh.write((_canon_str(e) + "\n").encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
            _write_hw(anchor.job_id, anchor.seq)
            return anchor
        finally:
            if fcntl:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _check_anchors(path: Path, res: VerifyResult, hashes: list[str], anchor, key, anchor_dir) -> VerifyResult:
    def fail(reason):
        return VerifyResult(False, res.n_records, None, reason)
    job_id = path.stem
    auto = anchor == "auto"
    if auto:
        anchors, err = _read_anchor_log(anchor_dir or path.parent)
        if err:
            return fail(err)
        anchors = [a for a in anchors if a.job_id == job_id]
        if not anchors:
            return fail(f"missing anchor: no sealed anchor for job {job_id!r}")
    else:
        try:
            anchors = [Anchor.from_dict(anchor)]
        except ContractError as e:
            return fail(str(e))
    try:
        k = _key_bytes(key, create=False, data_dir=anchor_dir or path.parent)
    except ContractError as e:
        return fail(str(e))
    if k is None:
        return fail("cannot check anchor signature: no evidence key available")
    for a in anchors:
        if not isinstance(a.n_records, int) or isinstance(a.n_records, bool) or a.n_records < 0:
            return fail("anchor n_records is invalid")
        if not isinstance(a.signature, str) or not hmac.compare_digest(
                a.signature, _sign(k, a.job_id, a.n_records, a.head_hash, a.sealed_at, a.seq)):
            return fail("anchor signature mismatch")
        if a.job_id != job_id:
            return fail(f"anchor is for job {a.job_id!r}, not {job_id!r}")
    if auto:
        latest = max(a.seq or 0 for a in anchors)
        floor = _read_hw(job_id)
        if floor > latest:
            return fail(f"rollback: the anchor log ends at seq {latest} but seq {floor} was sealed "
                        "(anchor log truncated)")
    for a in anchors:
        if res.n_records < a.n_records:
            return fail(_trunc_reason(res, a, anchors, hashes))
        expect = GENESIS_HASH if a.n_records == 0 else hashes[a.n_records - 1]
        if expect != a.head_hash:
            return fail(f"head differs from anchor at record {a.n_records} (re-chained or rewritten history)")
    return res


def _trunc_reason(res, a, anchors, hashes) -> str:
    older = [o for o in anchors if o.n_records == res.n_records and o.seq != a.seq
             and (GENESIS_HASH if o.n_records == 0 else hashes[o.n_records - 1]) == o.head_hash]
    if older:
        return (f"rollback: bundle matches anchor seq {older[0].seq} but anchor seq {a.seq} sealed "
                f"{a.n_records} records")
    return f"truncated: bundle has {res.n_records} records but {a.n_records} were anchored"


def head_hash(path) -> str:
    """record_hash of the last record (genesis zeros for an empty/missing bundle)."""
    lines = _read_lines(path) if Path(path).exists() else []
    return json.loads(lines[-1])["record_hash"] if lines else GENESIS_HASH


def check_custody(data_dir=None) -> None:
    """Refuse to run with an unsafe evidence key (file under ``data_dir``, or group/world accessible). A no-op when
    the key comes from ``ACRETIA_EVIDENCE_KEY``. Call at process/job start; raises ``ContractError``."""
    _key_bytes(create=False, data_dir=data_dir)


def export(path) -> list[dict]:
    """All records, parsed. Raises ``ContractError`` if the chain does not verify."""
    res = verify(path, False)
    if not res.ok:
        raise ContractError(f"{path}: seq {res.first_bad_seq}: {res.reason}")
    return [json.loads(line) for line in _read_lines(path)]


class EvidenceBundle:
    """Append-only evidence log for one job. ``job_id`` is the file stem."""

    def __init__(self, path, *, store_payloads: bool = False, repair: bool = False):
        self.path = Path(path)
        self.job_id = self.path.stem
        self.store_payloads = store_payloads
        self.recovery: dict | None = None   # set when repair=True found and cut a torn tail (F20)
        self.payload_dir = self.path.with_name(self.path.stem + ".payloads")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = open(self.path, "ab+")
        if store_payloads:
            self.payload_dir.mkdir(parents=True, exist_ok=True)
        if repair:
            self._repair_torn_tail()

    def _repair_torn_tail(self) -> None:
        """If the last line is truncated (crash mid-write), move it to ``<path>.torn-<ts>``, resume the chain from
        the last valid record and log a ``recovery`` record."""
        with self._lock:
            if fcntl:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
            try:
                self._fh.seek(0)
                data = self._fh.read()
                if not data or data.endswith(b"\n"):
                    return
                cut = data.rfind(b"\n") + 1
                torn = data[cut:]
                torn_path = self.path.with_name(f"{self.path.name}.torn-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}")
                torn_path.write_bytes(torn)
                os.ftruncate(self._fh.fileno(), cut)
                self._fh.flush()
                os.fsync(self._fh.fileno())
                info = {"discarded_bytes": len(torn), "torn_file": torn_path.name, "kept_bytes": cut}
            finally:
                if fcntl:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        rec = self.append("recovery", info, source="evidence.repair", output=info)
        self.recovery = {**info, "seq": rec["seq"], "record_hash": rec["record_hash"]}

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

    def verify(self, anchor=None, *, key=None, anchor_dir=None) -> VerifyResult:
        return verify(self.path, anchor, key=key, anchor_dir=anchor_dir)

    def seal(self, anchor_dir=None, *, key=None) -> Anchor:
        """Sign ``(job_id, n_records, head_hash, sealed_at, seq)`` with the deployment key and append it to the
        hash-chained ``anchors.jsonl`` in ``anchor_dir`` (default: the bundle's directory). ``seq`` is monotonic per
        job. Refuses a bad chain, and refuses a key file inside the data dir or readable by others."""
        res = verify(self.path, False)
        if not res.ok:
            raise ContractError(f"{self.path}: cannot seal a chain that does not verify: {res.reason}")
        data_dir = anchor_dir or self.path.parent
        k = _key_bytes(key, data_dir=data_dir)
        head, ts, n = head_hash(self.path), _now(), res.n_records

        def make(seq):
            return Anchor(self.job_id, n, head, ts, _sign(k, self.job_id, n, head, ts, seq), seq)
        return _append_anchor(data_dir, make)

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
