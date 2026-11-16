"""Record/replay for LLM calls, keyed by a hash of the provider-agnostic, already-masked request.

  ACRETIA_LLM_MODE=live     call the provider (default)
  ACRETIA_LLM_MODE=record   call the provider, then store the (masked) reply as tests/fixtures/llm/<hash>.json
  ACRETIA_LLM_MODE=replay   never touch the network: serve the fixture or raise ReplayMiss
  ACRETIA_LLM_FIXTURES=<dir>  override the fixture directory

The key is sha256 of a canonical JSON of (task-or-stage, system, part texts + image digests, schema). Because the
router masks PII before hashing, fixtures never contain it.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import pii

MODES = ("live", "record", "replay")
DEFAULT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "llm"


class ReplayMiss(Exception):
    """Replay mode and no fixture exists for this request (carries the key so it can be recorded)."""

    def __init__(self, key: str, task: str, path: Path):
        super().__init__(f"no LLM replay fixture for task {task!r} (key {key}); record it with ACRETIA_LLM_MODE=record -> {path}")
        self.key, self.task, self.path = key, task, path


class FixturePII(ValueError):
    """Refused to save a fixture whose reply still contains raw PII (mask it first)."""


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def find_pii(obj) -> list[str]:
    """Placeholder kinds (EMAIL, CARD, ...) of raw PII found in any string of a JSON-like object; [] when clean."""
    kinds = []
    for t in _strings(obj):
        m = pii.Masker()
        m.mask(t)
        kinds += [ph.strip("[]").rsplit("_", 1)[0] for ph in m.mapping]
    return sorted(set(kinds))


def mode(explicit: str | None = None) -> str:
    m = (explicit or os.environ.get("ACRETIA_LLM_MODE") or "live").strip().lower()
    if m not in MODES:
        raise ValueError(f"ACRETIA_LLM_MODE must be one of {MODES}, got {m!r}")
    return m


def fixtures_dir() -> Path:
    return Path(os.environ.get("ACRETIA_LLM_FIXTURES") or DEFAULT_DIR)


def canonical(task: str, system: str, parts, schema: dict) -> str:
    """parts: iterable of objects with .text and optional .image (cache flags are provider details and excluded)."""
    ps = [{"text": p.text, "image": hashlib.sha256(p.image).hexdigest() if getattr(p, "image", None) is not None else None}
          for p in parts]
    return json.dumps({"task": task, "system": system, "parts": ps, "schema": schema}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)


def request_key(task: str, system: str, parts, schema: dict) -> str:
    return hashlib.sha256(canonical(task, system, parts, schema).encode()).hexdigest()


def fixture_path(key: str) -> Path:
    return fixtures_dir() / f"{key}.json"


def load(key: str, task: str = "") -> dict:
    path = fixture_path(key)
    if not path.is_file():
        raise ReplayMiss(key, task, path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReplayMiss(key, f"{task} (corrupt fixture: {type(e).__name__})", path) from None
    if not isinstance(doc, dict) or doc.get("key") != key:
        raise ReplayMiss(key, f"{task} (fixture key mismatch)", path)
    return doc


def save(key: str, task: str, data: dict, usage: dict | None, model: str) -> Path:
    found = find_pii([data, usage, model])
    if found:
        raise FixturePII(f"refusing to save fixture {key[:12]}: the reply contains unmasked PII ({', '.join(found)}); "
                         "mask it (om.pii) before recording")
    path = fixture_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"key": key, "task": task, "model": model, "usage": usage or {}, "data": data}
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path
