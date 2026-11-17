"""Where API keys live: the macOS Keychain (encrypted at rest, outside the project), never the project's .env.

On macOS keys are written and read through the Security framework directly (ctypes), so a key never appears
on a command line, in a log or in a temp file. Elsewhere (or if the Keychain is unavailable) they go to
~/.config/acretia/secrets.env with owner-only permissions — still outside the project folder, so
they can't be committed, zipped or shared with it.

Each key is also bound to the host it was entered for (see settings.py): if an endpoint's address changes,
the key is not sent until it is entered again.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path

SERVICE = "acretia"
FALLBACK = Path.home() / ".config" / "acretia" / "secrets.env"
# Keys saved before the rename live under the old names; they are still read (and deleted) there.
LEGACY_SERVICE = "open-" + "multiples"
LEGACY_FALLBACK = Path.home() / ".config" / LEGACY_SERVICE / "secrets.env"

_NOT_FOUND = -25300
_sec = None
_cf = None


def _fallback() -> Path:
    if os.environ.get("OM_KEYSTORE_FILE"):
        return Path(os.environ["OM_KEYSTORE_FILE"])
    return LEGACY_FALLBACK if (not FALLBACK.exists() and LEGACY_FALLBACK.exists()) else FALLBACK


def _security():
    global _sec, _cf
    if sys.platform != "darwin" or os.environ.get("OM_KEYSTORE") == "file":
        return None
    if _sec is not None:
        return _sec
    try:
        _sec = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Security.framework/Security")
        _cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        _sec = None
        return None
    vp, u32, cp = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p
    _sec.SecKeychainAddGenericPassword.argtypes = [vp, u32, cp, u32, cp, u32, cp, ctypes.POINTER(vp)]
    _sec.SecKeychainFindGenericPassword.argtypes = [vp, u32, cp, u32, cp, ctypes.POINTER(u32), ctypes.POINTER(vp), ctypes.POINTER(vp)]
    _sec.SecKeychainItemModifyAttributesAndData.argtypes = [vp, vp, u32, cp]
    _sec.SecKeychainItemFreeContent.argtypes = [vp, vp]
    _sec.SecKeychainItemDelete.argtypes = [vp]
    for f in (_sec.SecKeychainAddGenericPassword, _sec.SecKeychainFindGenericPassword, _sec.SecKeychainItemModifyAttributesAndData,
              _sec.SecKeychainItemFreeContent, _sec.SecKeychainItemDelete):
        f.restype = ctypes.c_int32
    _cf.CFRelease.argtypes = [vp]
    return _sec


def backend() -> str:
    return "macOS Keychain" if _security() else f"private file {_fallback()} (owner-only)"


def _find(name: str, service: str = SERVICE):
    sec = _security()
    svc, acct = service.encode(), name.encode()
    n, data, item = ctypes.c_uint32(0), ctypes.c_void_p(), ctypes.c_void_p()
    st = sec.SecKeychainFindGenericPassword(None, len(svc), svc, len(acct), acct, ctypes.byref(n), ctypes.byref(data), ctypes.byref(item))
    if st == _NOT_FOUND:
        return None, None
    if st != 0:
        raise OSError(f"Keychain read failed (OSStatus {st})")
    value = ctypes.string_at(data, n.value).decode("utf-8")
    sec.SecKeychainItemFreeContent(None, data)
    return value, item


def get(name: str) -> str | None:
    if _security():
        for service in (SERVICE, LEGACY_SERVICE):
            value, item = _find(name, service)
            if item:
                _cf.CFRelease(item)
            if value is not None:
                return value
        return None
    return _file_read().get(name)


def put(name: str, value: str) -> None:
    if not value:
        return delete(name)
    if _security():
        sec = _security()
        old, item = _find(name)
        raw = value.encode("utf-8")
        if item:
            st = sec.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
            _cf.CFRelease(item)
        else:
            svc, acct = SERVICE.encode(), name.encode()
            st = sec.SecKeychainAddGenericPassword(None, len(svc), svc, len(acct), acct, len(raw), raw, None)
        if st != 0:
            raise OSError(f"Keychain write failed (OSStatus {st})")
        return
    d = _file_read()
    d[name] = value
    _file_write(d)


def delete(name: str) -> None:
    if _security():
        for service in (SERVICE, LEGACY_SERVICE):
            _, item = _find(name, service)
            if item:
                st = _security().SecKeychainItemDelete(item)
                _cf.CFRelease(item)
                if st != 0:
                    raise OSError(f"Keychain delete failed (OSStatus {st})")
        return
    d = _file_read()
    if d.pop(name, None) is not None:
        _file_write(d)


def load_into_env(names) -> list[str]:
    """Put stored keys into this process's environment (never written back to disk). Returns the names loaded."""
    loaded = []
    for n in names:
        if os.environ.get(n):
            continue
        try:
            v = get(n)
        except OSError:
            v = None
        if v:
            os.environ[n] = v
            loaded.append(n)
    return loaded


def _file_read() -> dict:
    f = _fallback()
    if not f.exists():
        return {}
    out = {}
    for line in f.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _file_write(d: dict) -> None:
    f = _fallback()
    f.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(f.parent, 0o700)
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(f"{k}={v}\n" for k, v in sorted(d.items())))
    tmp.replace(f)
