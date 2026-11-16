"""Settings: model routing and provider keys, stored in the project's local .env (gitignored).

Only whitelisted variables can be written. Key values are never returned to the browser — only whether
each is set and its last 4 characters. Changes apply to the running server immediately (os.environ) and
persist in .env for the next start.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .llm import PRESETS

KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", **{n: p["key_env"] for n, p in PRESETS.items() if p.get("key_env")},
            "custom": "CUSTOM_API_KEY"}
MODEL_VARS = ["OM_MODEL_DEFAULT", "OM_MODEL_ASK", "OM_MODEL_MATRIX", "OM_MODEL_SHEETS_AGENT", "OM_MODEL_CHECK", "OM_MODEL_RERANK",
              "OM_MODEL_STORYBOARD", "OM_MODEL_SLIDE_REVIEW", "OM_MODEL_SLIDE_BUILD", "OM_MODEL_VISION", "OM_IMAGE_MODEL"]
OTHER_VARS = ["OM_PROVIDER_CUSTOM_BASE_URL", "OM_PROVIDER_CUSTOM_API_KEY_ENV", "OM_BRAND"]
SECRET_VARS = set(KEY_VARS.values())       # stored in the Keychain, never in .env
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ALLOWED = set(KEY_VARS.values()) | set(MODEL_VARS) | set(OTHER_VARS) | {"OM_PROVIDER_CUSTOM_KEY_HOST"}
SPEC_RE = re.compile(r"^(svg:)?[a-z][a-z0-9_-]*(:[\w./:@-]+)?$")


def _mask(v: str | None) -> dict:
    return {"set": bool(v), "hint": ("••••" + v[-4:]) if v and len(v) >= 8 else ("set" if v else "")}


def _image_describe() -> str:
    from .images import describe
    return describe()


def brand() -> str:
    """Firm name printed on slide footers and covers."""
    return (os.environ.get("OM_BRAND") or "").strip() or "Research"


def _host(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).hostname or "").lower()


def check_base_url(url: str) -> None:
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("base URL must look like https://host/v1")
    if u.username or u.password:
        raise ValueError("don't put credentials in the URL; use the API key field")


def migrate(env_path: Path) -> list[str]:
    """Move any API key found in .env into the key store and remove it from the file."""
    from . import keystore
    if not env_path.exists():
        return []
    moved, keep = [], []
    for line in env_path.read_text().splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
        if m and m.group(1) in SECRET_VARS and m.group(2).strip().strip('"').strip("'"):
            keystore.put(m.group(1), m.group(2).strip().strip('"').strip("'"))
            moved.append(m.group(1))
            continue
        keep.append(line)
    if moved:
        _write_env(env_path, keep)
    return moved


def _write_env(env_path: Path, lines: list[str]) -> None:
    tmp = env_path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    tmp.replace(env_path)


def status() -> dict:
    from . import keystore
    return {
        "key_store": keystore.backend(),
        "custom_key_host": os.environ.get("OM_PROVIDER_CUSTOM_KEY_HOST", ""),
        "keys": {name: {"env": var, **_mask(os.environ.get(var))} for name, var in KEY_VARS.items()},
        "models": {var: os.environ.get(var, "") for var in MODEL_VARS},
        "custom_base_url": os.environ.get("OM_PROVIDER_CUSTOM_BASE_URL", ""),
        "custom_key": _mask(os.environ.get(os.environ.get("OM_PROVIDER_CUSTOM_API_KEY_ENV") or "CUSTOM_API_KEY")),
        "brand": brand(),
        "image_model": _image_describe(),
        "providers": ["anthropic", *PRESETS.keys(), "custom"],
        "defaults": {"anthropic": "claude-opus-5-5", **{n: p["default"] for n, p in PRESETS.items()}},
    }


def save(env_path: Path, updates: dict) -> dict:
    """updates: {VAR: value}; value "" removes the variable. API keys go to the key store (Keychain), everything
    else to .env. A custom-endpoint key is bound to the endpoint's host. Returns the new status."""
    from . import keystore
    clean = {}
    for k, v in updates.items():
        if k not in ALLOWED:
            raise ValueError(f"{k} cannot be set here")
        v = (v or "").strip()
        if any(ch in v for ch in "\r\n\0"):
            raise ValueError(f"{k}: invalid characters")
        if k in MODEL_VARS and v and not SPEC_RE.match(v):
            raise ValueError(f"{k}: use provider or provider:model, e.g. deepseek:deepseek-chat")
        if k == "OM_BRAND" and len(v) > 40:
            raise ValueError("firm name: 40 characters at most")
        if k == "OM_PROVIDER_CUSTOM_BASE_URL" and v:
            check_base_url(v)
        if k in SECRET_VARS and v and (len(v) < 8 or any(c.isspace() for c in v)):
            raise ValueError("that doesn't look like an API key")
        clean[k] = v
    if "OM_PROVIDER_CUSTOM_BASE_URL" in clean and clean["OM_PROVIDER_CUSTOM_BASE_URL"]:
        clean.setdefault("OM_PROVIDER_CUSTOM_API_KEY_ENV", "CUSTOM_API_KEY")
    # a saved key is only ever sent to the host it was entered for: moving the endpoint means entering the key again
    new_base = clean.get("OM_PROVIDER_CUSTOM_BASE_URL")
    bound = os.environ.get("OM_PROVIDER_CUSTOM_KEY_HOST", "")
    key_given = bool(clean.get("CUSTOM_API_KEY"))
    if new_base and bound and _host(new_base) != bound and not key_given and os.environ.get("CUSTOM_API_KEY"):
        raise ValueError(f"the saved key belongs to {bound}; enter the key again to use it with {_host(new_base)}")
    if key_given:
        base = new_base or os.environ.get("OM_PROVIDER_CUSTOM_BASE_URL", "")
        if not base:
            raise ValueError("enter the base URL with the key, so the key is tied to that endpoint")
        if base.lower().startswith("http://") and _host(base) not in LOCAL_HOSTS:
            raise ValueError("this endpoint uses plain http, which would send the key unencrypted; use its https:// address")
        clean["OM_PROVIDER_CUSTOM_KEY_HOST"] = _host(base)
    elif "CUSTOM_API_KEY" in clean and not clean["CUSTOM_API_KEY"]:
        clean["OM_PROVIDER_CUSTOM_KEY_HOST"] = ""
    # secrets -> key store; never into the file
    for k in [k for k in clean if k in SECRET_VARS]:
        v = clean.pop(k)
        if v:
            keystore.put(k, v)
            os.environ[k] = v
        else:
            keystore.delete(k)
            os.environ.pop(k, None)
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    out, done = [], set()
    for line in lines:
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in clean:
            k = m.group(1)
            if k not in done and clean[k]:
                out.append(f'{k}="{clean[k]}"')
            done.add(k)
            continue
        out.append(line)
    new = [k for k in clean if k not in done and clean[k]]
    if new:
        out.append(f"# added from Settings {time.strftime('%Y-%m-%d %H:%M')}")
        out += [f'{k}="{clean[k]}"' for k in new]
    _write_env(env_path, out)
    for k, v in clean.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    return status()


def _swatch() -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes((200, 30, 30)) * 32 for _ in range(32))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")


def list_models() -> dict:
    """GET {base}/models on the OpenAI-compatible endpoint, so the user can pick model ids."""
    import json as _json
    import urllib.error
    import urllib.request
    base = (os.environ.get("OM_PROVIDER_CUSTOM_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get(os.environ.get("OM_PROVIDER_CUSTOM_API_KEY_ENV") or "CUSTOM_API_KEY") or "").strip()
    if not base:
        return {"ok": False, "detail": "save the base URL first"}
    from .llm import LLMError, key_host_guard
    try:
        key_host_guard(base)
    except LLMError as e:
        return {"ok": False, "detail": str(e)}
    req = urllib.request.Request(base + "/models", headers={"Authorization": f"Bearer {key}", "User-Agent": "OpenMultiples/0.1"} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = _json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "detail": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:200]}
    items = j.get("data") if isinstance(j, dict) else j
    ids = sorted({(m.get("id") if isinstance(m, dict) else str(m)) for m in items or [] if m})
    return {"ok": True, "models": ids}


def test(stage: str) -> dict:
    """One tiny structured call through the router for this stage."""
    from .llm import LLMError, Part, Router
    r = Router()
    if not r.available(stage):
        return {"ok": False, "detail": f"no model configured for {stage}: {r.describe(stage)}"}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "model_says": {"type": "string"}},
              "required": ["ok", "model_says"], "additionalProperties": False}
    t0 = time.time()
    try:
        parts = [Part('Reply with {"ok": true, "model_says": "ready"}.')]
        if stage in ("slide_review", "slide_build"):          # vision stages: prove the model can see
            parts = [Part("", image=_swatch()), Part('Reply with {"ok": true, "model_says": "<the colour of this image, one word>"}.')]
        res = r.complete_json(stage, "You are a connectivity check.", parts, schema, max_tokens=200)
    except LLMError as e:
        return {"ok": False, "model": r.describe(stage), "detail": str(e)[:300]}
    except Exception as e:
        return {"ok": False, "model": r.describe(stage), "detail": repr(e)[:300]}
    return {"ok": bool(res.data.get("ok")), "model": res.model, "seconds": round(time.time() - t0, 1),
            "detail": res.data.get("model_says", "")}
