"""Image-endpoint probe: one tiny real generation request per process (cached); never touches the network offline/replay."""
from __future__ import annotations

import os
import time

_CACHE: dict = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _status(available: bool, provider: str | None, reason: str) -> dict:
    return {"available": available, "provider": provider, "reason": reason, "checked_at": _now()}


def _probe(adapter, transport, offline=False) -> dict:
    from ... import images
    if offline:
        return _status(False, None, "offline: no model adapter, no network call")
    mode = (getattr(adapter, "mode", None) or os.environ.get("ACRETIA_LLM_MODE") or "live").strip().lower()
    if mode == "replay":
        return _status(False, None, "replay mode: no network")
    spec = images.configured_spec()
    if not spec:
        return _status(False, None, "no image provider configured")
    if spec.startswith("svg:"):
        return _status(False, "svg", "SVG designer only; no image endpoint")
    name = spec.partition(":")[0].strip().lower()
    try:
        provider = images.make_image_provider(spec, transport=transport)
        data = provider.generate("A plain flat light-grey square, no text.", aspect="1:1", size="1K")
    except Exception as e:  # any failure (gateway_path_not_exposed, HTTP, auth, unreachable) means: use the fallback tiers
        return _status(False, name, str(e)[:300] or type(e).__name__)
    if not data:
        return _status(False, name, "empty image response")
    return _status(True, name, "ok")


def image_endpoint(*, adapter=None, transport=None, force: bool = False, offline: bool = False) -> dict:
    """Image endpoints are not chat, so the probe uses `om.images` providers; `adapter` only supplies the run mode.
    In replay mode, or with offline=True, no call is ever made."""
    if _CACHE and not force:
        return dict(_CACHE["status"])
    st = _probe(adapter, transport, offline)
    _CACHE["status"] = st
    return dict(st)
