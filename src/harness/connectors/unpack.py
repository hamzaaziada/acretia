"""Safe nested unpacking of .zip, .eml and .msg (S2.5). Standard library only.

Every archive is hostile until proven otherwise. Guards:
  * ZipSlip: `..`, absolute paths, drive letters, backslash tricks and symlink entries abort the archive.
  * Bombs: caps on total uncompressed bytes, per-file bytes, compression ratio, entry count and nesting depth.
    Declared sizes are checked up front AND enforced while streaming, because headers can lie.
  * Encrypted zips are rejected with EncryptedArchiveError (we never guess passwords).
  * Output names are sanitised (NUL, control chars, reserved device names, trailing dots) and every write is
    verified to resolve inside the destination directory.
.msg: no ledger row exists for extract_msg, so it is NOT added. A minimal stdlib OLE/CFB reader (subject, body,
attachments) is implemented below instead. Embedded .msg attachments are skipped with a note (not recursed).
Unstructured/Tika are optional isolated HTTP services (TikaClient); never imported, off unless ACRETIA_TIKA_URL."""
from __future__ import annotations

import email
import email.errors
import email.policy
import hashlib
import os
import re
import shutil
import stat
import struct
import tempfile
import zlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

GiB, MiB = 1 << 30, 1 << 20


class UnpackError(Exception):
    pass


class UnsafePathError(UnpackError):
    pass


class ArchiveBombError(UnpackError):
    pass


class EncryptedArchiveError(UnpackError):
    pass


class UnsupportedFormatError(UnpackError):
    pass


@dataclass(frozen=True)
class Limits:
    max_total_bytes: int = 2 * GiB
    max_file_bytes: int = 512 * MiB
    max_ratio: float = 100.0
    max_entries: int = 10_000
    max_depth: int = 5
    ratio_floor_bytes: int = 64 * 1024     # ratio is only meaningful above this size (tiny zero files hit 100:1)
    max_mime_depth: int = 20               # multipart / message/rfc822 nesting inside one .eml


@dataclass
class UnpackResult:
    files: list = field(default_factory=list)       # {"path": rel, "size", "sha256", "origin"}
    notes: list = field(default_factory=list)       # non-fatal (skipped embedded msg, directories...)

    def as_dict(self):
        return {"files": self.files, "notes": self.notes}


# --------------------------------------------------------------------------- names
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD = re.compile(r'[\x00-\x1f\x7f<>:"|?*\\]')
_DRIVE = re.compile(r"^[A-Za-z]:")


def sanitize_component(name: str, maxlen: int = 120) -> str:
    n = _BAD.sub("_", name or "").strip(" .")
    if not n:
        return "_"
    stem, dot, ext = n.rpartition(".")
    if not dot:
        stem, ext = n, ""
    if stem.split(".")[0].upper() in _RESERVED:
        stem = "_" + stem
    if len(stem) + len(ext) + 1 > maxlen:
        stem = stem[: max(1, maxlen - len(ext) - 1)]
    return f"{stem}.{ext}" if ext else stem


def check_member_path(name: str) -> list[str]:
    """Validate an archive member path (reject, don't repair, traversal) and return sanitised components."""
    if "\x00" in name:
        raise UnsafePathError(f"NUL byte in entry name {name!r}")
    norm = name.replace("\\", "/")
    if norm.startswith("/") or _DRIVE.match(norm) or norm.startswith("//"):
        raise UnsafePathError(f"absolute path in archive: {name!r}")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafePathError(f"path traversal in archive: {name!r}")
    if any(_DRIVE.match(p) for p in parts):
        raise UnsafePathError(f"drive letter in archive path: {name!r}")
    return [sanitize_component(p) for p in parts]


class _Run:
    """Budget shared by one top-level unpack, including every nested archive."""

    def __init__(self, dest: Path, limits: Limits):
        self.dest = Path(dest).resolve()
        self.limits = limits
        self.total = 0
        self.entries = 0
        self.result = UnpackResult()

    def count_entry(self):
        self.entries += 1
        if self.entries > self.limits.max_entries:
            raise ArchiveBombError(f"more than {self.limits.max_entries} entries")

    def charge(self, n: int):
        self.total += n
        if self.total > self.limits.max_total_bytes:
            raise ArchiveBombError(f"total uncompressed size exceeds {self.limits.max_total_bytes} bytes")

    def target(self, rel_parts: list[str]) -> Path:
        """Collision-free path under dest for the sanitised components. A file/directory name clash
        (`a` then `a/b`, or `a/b` then `a`) is rejected, never repaired."""
        base = self.dest.joinpath(*rel_parts) if rel_parts else self.dest / "_"
        for parent in list(base.parents):
            if parent == self.dest:
                break
            if parent.is_symlink():
                raise UnsafePathError(f"symlinked directory in output path: {parent}")
            if parent.exists() and not parent.is_dir():
                raise UnpackError(f"name clash: {parent.relative_to(self.dest).as_posix()!r} is a file but is also "
                                  f"used as a directory")
        p = base
        i = 1
        while p.exists() or p.is_symlink():
            if p.is_dir():
                raise UnpackError(f"name clash: {p.relative_to(self.dest).as_posix()!r} is a directory but is also "
                                  f"used as a file")
            i += 1
            p = base.with_name(f"{base.stem}__{i}{base.suffix}")
        rp = p.resolve()
        if rp != self.dest and self.dest not in rp.parents:
            raise UnsafePathError(f"{p} escapes the destination")
        return p

    def write(self, rel_parts: list[str], data: bytes, origin: str) -> Path:
        if len(data) > self.limits.max_file_bytes:
            raise ArchiveBombError(f"file {origin!r} exceeds {self.limits.max_file_bytes} bytes")
        self.count_entry()
        self.charge(len(data))
        p = self.target(rel_parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "xb") as fh:
            fh.write(data)
        self.result.files.append({"path": p.relative_to(self.dest).as_posix(), "size": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest(), "origin": origin})
        return p


# --------------------------------------------------------------------------- public API
def _load(src, name, limits):
    if isinstance(src, (bytes, bytearray)):
        return bytes(src), name or "archive.zip"
    p = Path(src)
    if p.stat().st_size > limits.max_file_bytes:
        raise ArchiveBombError(f"{p.name} exceeds {limits.max_file_bytes} bytes")
    return p.read_bytes(), name or p.name


def _commit(tmp: Path, dest: Path):
    """Move the finished tree into `dest`: one atomic rename when dest is empty, else per-entry after a clash check."""
    kids = list(tmp.iterdir())
    if not dest.exists() or not any(dest.iterdir()):
        if dest.exists():
            dest.rmdir()
        os.replace(tmp, dest)
        return
    clash = [k.name for k in kids if (dest / k.name).exists() or (dest / k.name).is_symlink()]
<<<<<<< Updated upstream
    if any((dest / c).is_symlink() for c in clash):
        raise UnsafePathError("symlink in the destination collides with an output name; refusing to follow it")
=======
>>>>>>> Stashed changes
    if clash:
        raise UnpackError(f"destination already contains {sorted(clash)[:5]}")
    for k in kids:
        os.replace(k, dest / k.name)
    tmp.rmdir()


def unpack(src, dest, *, name: str | None = None, limits: Limits | None = None) -> UnpackResult:
    """Unpack `src` (path or bytes; `name` gives the extension for bytes) into `dest`, recursing into nested
    .zip/.eml/.msg. Non-container files are copied through. Transactional: output is built in a temp directory next
    to `dest` and renamed into place only on success, so a failure leaves `dest` untouched. Every violation or
    OS/parser error surfaces as an UnpackError subclass."""
    limits = limits or Limits()
    dest = Path(dest)
    tmp = None
    try:
        data, name = _load(src, name, limits)
        dest.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.unpack-", dir=dest.resolve().parent))
        run = _Run(tmp, limits)
        _handle(run, data, [sanitize_component(PurePosixPath(name.replace("\\", "/")).name)], depth=0, origin=name)
        _commit(tmp, dest)
        tmp = None
        return run.result
    except UnpackError:
        raise
    except RecursionError as e:
        raise ArchiveBombError("nesting too deep for the parser") from e
    except MemoryError as e:
        raise ArchiveBombError("archive needs more memory than allowed") from e
    except (OSError, zlib.error, zipfile.BadZipFile, zipfile.LargeZipFile, email.errors.MessageError, EOFError,
            struct.error, ValueError, LookupError, TypeError, AttributeError, NotImplementedError, RuntimeError) as e:
        raise UnpackError(f"cannot unpack {name or src!r}: {type(e).__name__}: {e}") from e
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _kind(parts: list[str]) -> str:
    return PurePosixPath(parts[-1]).suffix.lower()


def _handle(run: _Run, data: bytes, rel: list[str], depth: int, origin: str):
    ext = _kind(rel)
    if ext in (".zip", ".eml", ".msg"):
        if depth >= run.limits.max_depth:   # top-level container is level 1; the 6th level is refused
            raise ArchiveBombError(f"archive nesting deeper than {run.limits.max_depth} levels")
        sub = rel[:-1] + [rel[-1] + ".d"] if depth else []
        {".zip": _zip, ".eml": _eml, ".msg": _msg}[ext](run, data, sub, depth, origin, rel)
    else:
        run.write(rel, data, origin)


# --------------------------------------------------------------------------- zip
def _zip(run: _Run, data: bytes, base: list[str], depth: int, origin: str, rel: list[str]):
    import io
    lim = run.limits
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UnpackError(f"{origin}: not a valid zip ({e})")
    with zf:
        infos = zf.infolist()
        if len(infos) > lim.max_entries:
            raise ArchiveBombError(f"{origin}: {len(infos)} entries exceeds {lim.max_entries}")
        # pass 1: validate every entry before writing anything
        plan = []
        declared = 0
        for zi in infos:
            parts = check_member_path(zi.filename)
            mode = (zi.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise UnsafePathError(f"{origin}: symlink entry {zi.filename!r}")
            if stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise UnsafePathError(f"{origin}: special file entry {zi.filename!r}")
            if zi.flag_bits & 0x1:
                raise EncryptedArchiveError(f"{origin}: encrypted entry {zi.filename!r}; encrypted archives are not supported")
            if zi.is_dir():
                continue
            if not parts:
                raise UnsafePathError(f"{origin}: empty entry name")
            if zi.file_size > lim.max_file_bytes:
                raise ArchiveBombError(f"{origin}: {zi.filename!r} declares {zi.file_size} bytes (cap {lim.max_file_bytes})")
            declared += zi.file_size
            if declared > lim.max_total_bytes:
                raise ArchiveBombError(f"{origin}: declared uncompressed total exceeds {lim.max_total_bytes}")
            if zi.file_size >= lim.ratio_floor_bytes and zi.file_size / max(zi.compress_size, 1) > lim.max_ratio:
                raise ArchiveBombError(f"{origin}: {zi.filename!r} compression ratio "
                                       f"{zi.file_size / max(zi.compress_size, 1):.0f}:1 exceeds {lim.max_ratio:.0f}:1")
            plan.append((zi, parts))
        files, dirs = set(), set()
        for _zi, parts in plan:           # `a` then `a/b` (or the reverse) can never both be written
            t = tuple(parts)
            for k in range(1, len(t)):
                if t[:k] in files:
                    raise UnpackError(f"{origin}: name clash: {'/'.join(t[:k])!r} is a file and a directory")
                dirs.add(t[:k])
            if t in dirs:
                raise UnpackError(f"{origin}: name clash: {'/'.join(t)!r} is a file and a directory")
            files.add(t)
        # pass 2: stream with enforced caps (headers may understate)
        for zi, parts in plan:
            buf = bytearray()
            try:
                fh = zf.open(zi)
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as e:   # encrypted / unsupported method
                raise UnpackError(f"{origin}: cannot open {zi.filename!r}: {e}")
            try:
                with fh:
                    while chunk := fh.read(1 << 20):
                        buf += chunk
                        if len(buf) > lim.max_file_bytes:
                            raise ArchiveBombError(f"{origin}: {zi.filename!r} exceeds {lim.max_file_bytes} bytes while reading")
                        if len(buf) >= lim.ratio_floor_bytes and len(buf) / max(zi.compress_size, 1) > lim.max_ratio:
                            raise ArchiveBombError(f"{origin}: {zi.filename!r} compression ratio exceeds {lim.max_ratio:.0f}:1")
            except (zipfile.BadZipFile, zlib.error, EOFError) as e:      # corrupt data / header sizes that lie
                raise UnpackError(f"{origin}: corrupt entry {zi.filename!r}: {e}")
            _handle(run, bytes(buf), base + parts, depth + 1, f"{origin}!{zi.filename}")


# --------------------------------------------------------------------------- eml
def _mime_scan(msg, limits: Limits, run: "_Run", origin: str):
    """Iterative walk of the MIME tree (no recursion): enforce the depth limit and cap decoded sizes BEFORE any
    part is decoded. Estimates come from the raw payload length, so a base64 bomb is refused without allocating."""
    stack, seen_total = [(msg, 1)], 0
    while stack:
        part, depth = stack.pop()
        if depth > limits.max_mime_depth:
            raise ArchiveBombError(f"{origin}: MIME nesting deeper than {limits.max_mime_depth} levels")
        if part.is_multipart():
            stack.extend((c, depth + 1) for c in part.get_payload())
            continue
        raw = part.get_payload()
        n = len(raw) if isinstance(raw, (str, bytes)) else 0
        cte = str(part.get("Content-Transfer-Encoding", "")).strip().lower()
        est = n * 3 // 4 if cte == "base64" else n
        if est > limits.max_file_bytes:
            raise ArchiveBombError(f"{origin}: MIME part decodes to about {est} bytes (cap {limits.max_file_bytes})")
        seen_total += est
        if run.total + seen_total > limits.max_total_bytes:
            raise ArchiveBombError(f"{origin}: MIME parts decode to more than {limits.max_total_bytes} bytes in total")


def _eml(run: _Run, data: bytes, base: list[str], depth: int, origin: str, rel: list[str]):
    try:
        msg = email.message_from_bytes(data, policy=email.policy.default)
    except RecursionError:
        raise ArchiveBombError(f"{origin}: MIME nesting too deep") from None
    _mime_scan(msg, run.limits, run, origin)
    stem = PurePosixPath(rel[-1]).stem
    head = "".join(f"{k}: {msg.get(k, '')}\n" for k in ("From", "To", "Cc", "Date", "Subject"))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    out = base or []
    run.write(out + [f"{stem}.body.txt"], (head + "\n" + text).encode("utf-8", "replace"), origin)
    html = msg.get_body(preferencelist=("html",))
    if html is not None and body is not None and html is not body:
        run.write(out + [f"{stem}.body.html"], html.get_content().encode("utf-8", "replace"), origin)
    for i, part in enumerate(msg.iter_attachments(), 1):
        fn = part.get_filename() or f"attachment_{i}"
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            inner = part.get_payload(0)
            payload = inner.as_bytes(policy=email.policy.default)
            fn = fn if fn.lower().endswith(".eml") else f"{fn}.eml"
        else:
            payload = part.get_payload(decode=True) or b""
        if len(payload) > run.limits.max_file_bytes:
            raise ArchiveBombError(f"{origin}: attachment {fn!r} exceeds {run.limits.max_file_bytes} bytes")
        _handle(run, payload, out + [sanitize_component(PurePosixPath(fn.replace("\\", "/")).name)], depth + 1,
                f"{origin}#{fn}")


# --------------------------------------------------------------------------- msg (minimal OLE/CFB reader)
_CFB_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_END, _FREE = 0xFFFFFFFE, 0xFFFFFFFF
_MAX_CFB_ENTRIES = 4096
_MAX_CFB_READ = 256 * MiB       # absolute cap on bytes read from all streams; also file size x 4


class _Cfb:
    """Read-only Compound File Binary reader: just enough to walk storages and read streams. Chains are
    cycle-checked and bounded by the file size, so a malicious header cannot loop or allocate unboundedly."""

    def __init__(self, data: bytes, max_stream: int = 512 * MiB):
        self.max_stream = max_stream
        self.budget = min(len(data) * 4, _MAX_CFB_READ)
        self.spent = 0
        self.used = set()          # big sectors already claimed by a chain: reuse means overlapping chains
        self.used_mini = set()     # same for mini-stream sectors
        if len(data) < 512 or data[:8] != _CFB_SIG:
            raise UnpackError("not an OLE compound file (.msg)")
        self.d = data
        ver, = struct.unpack_from("<H", data, 26)
        ss, ms = struct.unpack_from("<HH", data, 30)
        if ver not in (3, 4) or ss not in (9, 12) or ms != 6:
            raise UnpackError("unsupported compound file geometry")
        self.ss, self.ms = 1 << ss, 1 << ms
        n_fat, first_dir, _tx, self.cutoff, first_mini, n_mini, first_dif, n_dif = struct.unpack_from("<IIIIIIII", data, 44)
        self.max_sectors = len(data) // self.ss + 2
        difat = list(struct.unpack_from("<109I", data, 76))
        s, seen = first_dif, set()
        for _ in range(n_dif):
            if s in seen or s >= self.max_sectors:
                break
            seen.add(s)
            vals = struct.unpack_from(f"<{self.ss // 4}I", self._sec(s))
            difat += vals[:-1]
            s = vals[-1]
        self.fat = []
        for sid in difat[:n_fat] if n_fat <= len(difat) else difat:
            if sid >= self.max_sectors:
                continue
            self.fat += struct.unpack_from(f"<{self.ss // 4}I", self._sec(sid))
        dirdata = self._chain(first_dir)
        self.entries = []
        for off in range(0, len(dirdata), 128):
            raw = dirdata[off:off + 128]
            if len(raw) < 128:
                break
            nlen, typ = struct.unpack_from("<HB", raw, 64)
            if typ and len(self.entries) >= _MAX_CFB_ENTRIES:
                raise ArchiveBombError(f"compound file has more than {_MAX_CFB_ENTRIES} directory entries")
            name = raw[:max(0, min(nlen, 64) - 2)].decode("utf-16-le", "replace")
            left, right, child = struct.unpack_from("<III", raw, 68)
            start, size = struct.unpack_from("<IQ", raw, 116)
            self.entries.append({"name": name, "type": typ, "left": left, "right": right, "child": child,
                                 "start": start, "size": size & 0xFFFFFFFF if ver == 3 else size})
        self.mini = []
        if n_mini and self.entries:
            mraw = self._chain(first_mini)
            self.mini = list(struct.unpack_from(f"<{len(mraw) // 4}I", mraw))
            self.ministream = self._chain(self.entries[0]["start"], self.entries[0]["size"])

    def _sec(self, n: int) -> bytes:
        off = (n + 1) * self.ss
        if off + self.ss > len(self.d):
            raise UnpackError("compound file sector out of range")
        return self.d[off:off + self.ss]

    def _spend(self, n: int):
        self.spent += n
        if self.spent > self.budget:
            raise ArchiveBombError(f"compound file streams ask for more than {self.budget} bytes "
                                   f"(file size x 4, absolute cap {_MAX_CFB_READ})")

    def _chain(self, start: int, nbytes: int | None = None) -> bytes:
        """Follow a FAT chain, claiming each sector exactly once across the whole file. `nbytes` (a stream's declared
        size) bounds how many sectors are walked."""
        want = None if nbytes is None else (nbytes + self.ss - 1) // self.ss
        out, seen, s = [], set(), start
        while s < 0xFFFFFFFA and (want is None or len(out) < want):
            if s in seen or s >= len(self.fat) or len(seen) > self.max_sectors:
                raise UnpackError("corrupt compound file chain")
            if s in self.used:
                raise ArchiveBombError("compound file has overlapping sector chains (shared sectors)")
            seen.add(s)
            self.used.add(s)
            self._spend(self.ss)
            out.append(self._sec(s))
            s = self.fat[s]
        return b"".join(out)

    def read(self, e: dict) -> bytes:
        size = e["size"]
        if size > self.max_stream:
            raise ArchiveBombError(f"compound stream declares {size} bytes (cap {self.max_stream})")
        if size > len(self.d):
            raise ArchiveBombError("compound stream size implausible")
        if size == 0:
            return b""
        if size < self.cutoff and e["type"] != 5:
            self._spend(size)
            out, seen, s = [], set(), e["start"]
            while s < 0xFFFFFFFA and len(out) * self.ms < size:
                if s in seen or s >= len(self.mini):
                    raise UnpackError("corrupt mini stream chain")
                if s in self.used_mini:
                    raise ArchiveBombError("compound file has overlapping mini-stream chains (shared sectors)")
                seen.add(s)
                self.used_mini.add(s)
                out.append(self.ministream[s * self.ms:(s + 1) * self.ms])
                s = self.mini[s]
            return b"".join(out)[:size]
        return self._chain(e["start"], size)[:size]

    def children(self, idx: int) -> dict:
        """name -> entry index for the direct children of storage `idx` (tree walked, order ignored)."""
        out, seen, stack = {}, set(), [self.entries[idx]["child"]]
        while stack:
            i = stack.pop()
            if i >= len(self.entries) or i in seen:
                continue
            seen.add(i)
            out[self.entries[i]["name"]] = i
            stack += [self.entries[i]["left"], self.entries[i]["right"]]
        return out


def _prop(cfb: _Cfb, kids: dict, tag: str) -> str | bytes | None:
    """Read property `tag` (4 hex digits) as text (001F unicode / 001E ansi) or raw bytes (0102)."""
    for suffix, kind in (("001F", "u"), ("001E", "a"), ("0102", "b")):
        e = kids.get(f"__substg1.0_{tag}{suffix}")
        if e is not None:
            raw = cfb.read(cfb.entries[e])
            if kind == "u":
                return raw.decode("utf-16-le", "replace").rstrip("\x00")
            if kind == "a":
                return raw.decode("cp1252", "replace").rstrip("\x00")
            return raw
    return None


def read_msg(data: bytes, limits: Limits | None = None) -> dict:
    """-> {"subject","body","html","sender","attachments":[(filename, bytes)],"skipped":[names]}"""
    cfb = _Cfb(data, (limits or Limits()).max_file_bytes)
    root = cfb.children(0)
    html = _prop(cfb, root, "1013")
    out = {"subject": _prop(cfb, root, "0037") or "", "body": _prop(cfb, root, "1000") or "",
           "sender": _prop(cfb, root, "0C1A") or "",
           "html": html.decode("utf-8", "replace") if isinstance(html, bytes) else (html or ""),
           "attachments": [], "skipped": []}
    for name, idx in sorted(root.items()):
        if not name.startswith("__attach_version1.0_"):
            continue
        a = cfb.children(idx)
        fn = _prop(cfb, a, "3707") or _prop(cfb, a, "3704") or name
        if "__substg1.0_3701000D" in a or any(k.startswith("__substg1.0_3701000D") for k in a):
            out["skipped"].append(f"{fn}: embedded .msg attachment not expanded")
            continue
        payload = _prop(cfb, a, "3701")
        if isinstance(payload, bytes):
            out["attachments"].append((fn, payload))
        else:
            out["skipped"].append(f"{fn}: attachment has no binary data")
    return out


def _msg(run: _Run, data: bytes, base: list[str], depth: int, origin: str, rel: list[str]):
    m = read_msg(data, run.limits)
    stem = PurePosixPath(rel[-1]).stem
    text = f"From: {m['sender']}\nSubject: {m['subject']}\n\n{m['body']}"
    run.write(base + [f"{stem}.body.txt"], text.encode("utf-8", "replace"), origin)
    if m["html"]:
        run.write(base + [f"{stem}.body.html"], m["html"].encode("utf-8", "replace"), origin)
    run.result.notes += [f"{origin}: {s}" for s in m["skipped"]]
    for fn, payload in m["attachments"]:
        _handle(run, payload, base + [sanitize_component(PurePosixPath(fn.replace("\\", "/")).name)], depth + 1,
                f"{origin}#{fn}")


# --------------------------------------------------------------------------- optional isolated Tika service
class TikaClient:
    """Client for an isolated Apache Tika (or Unstructured API) HTTP service. OFF by default: constructed only when
    ACRETIA_TIKA_URL is set. Never imports either package; sends bytes to the configured URL only."""

    def __init__(self, url: str | None = None, timeout: int = 60, transport=None):
        self.url = (url or os.environ.get("ACRETIA_TIKA_URL") or "").rstrip("/")
        self.timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def extract_text(self, data: bytes, content_type: str = "application/octet-stream") -> str:
        if not self.enabled:
            raise UnpackError("Tika service disabled: set ACRETIA_TIKA_URL")
        headers = {"Content-Type": content_type, "Accept": "text/plain"}
        if self._transport:
            return self._transport("PUT", f"{self.url}/tika", headers, data)
        import urllib.request
        req = urllib.request.Request(f"{self.url}/tika", data=data, headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read(64 * MiB).decode("utf-8", "replace")
