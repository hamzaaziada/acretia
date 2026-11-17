"""Security primitives for the product API (SPEC §2.2): headers, cookies, passwords, rate limiting,
secret encryption at rest, upload sniffing and a safe zip unpacker. Standard library only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
import stat
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Iterator

SESSION_COOKIE = "acr_session"

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; "
       "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'self'")

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


# --------------------------------------------------------------------------- tokens and compares
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def ct_equal(a: str | bytes, b: str | bytes) -> bool:
    a = a.encode("utf-8") if isinstance(a, str) else a
    b = b.encode("utf-8") if isinstance(b, str) else b
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------------- cookies
def is_secure(headers) -> bool:
    if os.environ.get("ACRETIA_SECURE_COOKIES") == "1":
        return True
    try:
        return str(headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() == "https"
    except Exception:
        return False


def build_cookie(value: str, secure: bool = False, max_age: int | None = None, name: str = SESSION_COOKIE) -> str:
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Strict"]
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie(secure: bool = False) -> str:
    return build_cookie("", secure=secure, max_age=0) + "; Expires=Thu, 01 Jan 1970 00:00:00 GMT"


def parse_cookies(header: str | None) -> dict:
    out = {}
    for part in (header or "").split(";"):
        k, sep, v = part.strip().partition("=")
        if sep and k and k not in out:
            out[k] = v.strip().strip('"')
    return out


# --------------------------------------------------------------------------- passwords (scrypt)
SCRYPT_N, SCRYPT_R, SCRYPT_P, MIN_PASSWORD = 2 ** 14, 8, 1, 10


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(),
                                        base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b, hash_b = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        salt, want = base64.b64decode(salt_b), base64.b64decode(hash_b)
        dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(want),
                            maxmem=128 * n * r * 2 + (1 << 20))
        return hmac.compare_digest(dk, want)
    except Exception:
        return False


_DUMMY_HASH: str | None = None


def burn_password_time(password: str) -> None:
    """Equalise timing for unknown emails (one scrypt, result discarded)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    verify_password(password, _DUMMY_HASH)


# --------------------------------------------------------------------------- login rate limiter
class RateLimiter:
    """N failures per window per key; `blocked(key)` is True once the limit is reached."""

    def __init__(self, limit: int = 10, window: float = 15 * 60, clock: Callable[[], float] = time.time):
        self.limit, self.window, self.clock = limit, window, clock
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key):
        cutoff = self.clock() - self.window
        lst = [t for t in self._fails.get(key, []) if t > cutoff]
        if lst:
            self._fails[key] = lst
        else:
            self._fails.pop(key, None)
        return lst

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key)) >= self.limit

    def retry_after(self, key: str) -> int:
        with self._lock:
            lst = self._prune(key)
            return max(1, int(lst[0] + self.window - self.clock())) if lst else 0

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key)
            self._fails.setdefault(key, []).append(self.clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


# --------------------------------------------------------------------------- secrets at rest
def load_secret_key(data_dir) -> bytes:
    """`ACRETIA_SECRET_KEY` (hex of >=32 bytes, or any string -> sha256), else a random key in
    `<data_dir>/secret.key` created with mode 0600."""
    env = os.environ.get("ACRETIA_SECRET_KEY")
    if env:
        try:
            raw = bytes.fromhex(env.strip())
            if len(raw) >= 32:
                return raw
        except ValueError:
            pass
        return hashlib.sha256(env.encode("utf-8")).digest()
    path = Path(data_dir) / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return bytes.fromhex(path.read_text().strip())
    key = os.urandom(32)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # lost a race with another starter
        return bytes.fromhex(path.read_text().strip())
    with os.fdopen(fd, "w") as fh:
        fh.write(key.hex())
    return key


def _keystream(key: bytes, nonce: bytes, n: int) -> bytes:
    out, ctr = bytearray(), 0
    while len(out) < n:
        out += hmac.new(key, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:n])


def _subkeys(key: bytes):
    return (hmac.new(key, b"acretia-enc", hashlib.sha256).digest(),
            hmac.new(key, b"acretia-mac", hashlib.sha256).digest())


def encrypt_secret(key: bytes, plaintext: str) -> str:
    """HMAC-SHA256 counter-mode keystream + random nonce + HMAC tag (encrypt-then-MAC)."""
    ek, mk = _subkeys(key)
    nonce = os.urandom(16)
    data = plaintext.encode("utf-8")
    ct = bytes(a ^ b for a, b in zip(data, _keystream(ek, nonce, len(data))))
    tag = hmac.new(mk, nonce + ct, hashlib.sha256).digest()
    return "v1$" + base64.urlsafe_b64encode(nonce + ct + tag).decode()


def decrypt_secret(key: bytes, blob: str) -> str:
    try:
        ver, _, b = blob.partition("$")
        raw = base64.urlsafe_b64decode(b.encode())
        if ver != "v1" or len(raw) < 48:
            raise ValueError
        nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
    except Exception:
        raise ValueError("secret is corrupt") from None
    ek, mk = _subkeys(key)
    if not hmac.compare_digest(tag, hmac.new(mk, nonce + ct, hashlib.sha256).digest()):
        raise ValueError("secret failed authentication (wrong key or tampered)")
    return bytes(a ^ b for a, b in zip(ct, _keystream(ek, nonce, len(ct)))).decode("utf-8")


def mask_secret(secret: str | None) -> str:
    """Write-only display form: bullets plus the last four characters."""
    if not secret:
        return ""
    return "••••" + (secret[-4:] if len(secret) >= 8 else "")


# --------------------------------------------------------------------------- upload sniffing
OFFICE_PREFIX = {"xl/": "xlsx", "ppt/": "pptx", "word/": "docx"}
ALLOWED_KINDS = ("pdf", "xlsx", "pptx", "docx", "zip", "eml", "png", "jpg", "csv", "txt")
MIME = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "zip": "application/zip", "eml": "message/rfc822", "png": "image/png", "jpg": "image/jpeg",
        "csv": "text/csv; charset=utf-8", "txt": "text/plain; charset=utf-8"}


def sniff(data: bytes, filename: str = "") -> str | None:
    """Return a kind from ALLOWED_KINDS judged by magic bytes (the extension only breaks text ties)."""
    head = data[:2048]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile:
            return None
        if "[Content_Types].xml" in names:
            for pre, kind in OFFICE_PREFIX.items():
                if any(n.startswith(pre) for n in names):
                    return kind
        return "zip"
    if b"\x00" in head:
        return None
    try:
        text = data[:8192].decode("utf-8")
    except UnicodeDecodeError:
        try:
            data[:8192].decode("cp1252")
            text = data[:8192].decode("cp1252")
        except UnicodeDecodeError:
            return None
    low = text.lower()
    first = low.lstrip()[:400]
    if (first.startswith(("from:", "received:", "return-path:", "message-id:", "mime-version:", "date:", "subject:"))
            and "\n" in first):
        return "eml"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "csv" or (ext != "txt" and text.count(",") > 3 and text.count("\n") > 1 and "<" not in text[:50]):
        return "csv"
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<svg", "<?xml", "<script")):
        return None  # markup is never accepted as a document
    return "txt"


# --------------------------------------------------------------------------- safe zip
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_BYTES = 2 * 1024 ** 3
MAX_ZIP_RATIO = 200
_RATIO_FLOOR = 1024 * 1024  # ratios only matter once an archive/entry is bigger than 1 MiB


class UnsafeArchive(ValueError):
    """The archive breaks a safety limit (ZipSlip, bomb, symlink, too many entries, bad nesting)."""


def _safe_member(name: str) -> str:
    n = name.replace("\\", "/")
    if not n or n.startswith("/") or (len(n) > 1 and n[1] == ":") or "\x00" in n:
        raise UnsafeArchive(f"unsafe path in archive: {name!r}")
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafeArchive(f"path traversal in archive: {name!r}")
    return "/".join(parts)


def iter_zip(data: bytes, _depth: int = 0, _budget: list | None = None) -> Iterator[tuple[str, bytes]]:
    """Yield (relative_path, bytes) for each file; one nested archive level is unpacked, deeper is refused."""
    budget = _budget if _budget is not None else [0]
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UnsafeArchive("the archive is not a valid zip file") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise UnsafeArchive(f"too many entries ({len(infos)} > {MAX_ZIP_ENTRIES})")
        total = sum(i.file_size for i in infos)
        comp = max(1, sum(i.compress_size for i in infos))
        if total > MAX_ZIP_BYTES:
            raise UnsafeArchive("archive expands to more than 2 GB")
        if total > _RATIO_FLOOR and total / comp > MAX_ZIP_RATIO:
            raise UnsafeArchive(f"compression ratio {total // comp}:1 exceeds {MAX_ZIP_RATIO}:1 (zip bomb)")
        for info in infos:
            rel = _safe_member(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UnsafeArchive(f"symlink in archive: {info.filename!r}")
            if info.is_dir() or not rel:
                continue
            if info.file_size > _RATIO_FLOOR and info.file_size / max(1, info.compress_size) > MAX_ZIP_RATIO:
                raise UnsafeArchive(f"entry {info.filename!r} exceeds the compression ratio limit")
            with zf.open(info) as fh:  # read at most declared size + 1 so a lying header is caught
                blob = fh.read(info.file_size + 1)
            if len(blob) != info.file_size:
                raise UnsafeArchive(f"entry {info.filename!r} is larger than its header says")
            budget[0] += len(blob)
            if budget[0] > MAX_ZIP_BYTES:
                raise UnsafeArchive("archive expands to more than 2 GB")
            if blob[:4] in (b"PK\x03\x04", b"PK\x05\x06") and rel.lower().endswith(".zip"):
                if _depth >= 1:
                    raise UnsafeArchive("archives nested more than one level deep are refused")
                base = rel[:-4]
                for sub, sdata in iter_zip(blob, _depth + 1, budget):
                    yield f"{base}/{sub}", sdata
                continue
            yield rel, blob
