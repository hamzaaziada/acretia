"""DeckSpec v2: load (JSON/YAML), validate (top-level schema, forbidden geometry/font/colour keys, archetype blocks), dump.

A spec says WHAT goes on each slide. Geometry, fonts and colours belong to the engine, so they are rejected anywhere
in the tree. Errors carry JSON-path style locations such as ``$.slides[3].blocks.chart.series[0].values``."""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_KEYS = frozenset("x y w h left top width height font font_size size color colour fill rgb hex".split())
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_FORBIDDEN_MSG = "geometry/fonts/colours come from the engine, not the spec"
VISUAL_KINDS = ("illustration", "hero", "diagram", "icon_system", "none")
warnings: list[str] = []   # non-fatal notes from the last validate() call (e.g. archetype registry unavailable)


@dataclass(frozen=True)
class SpecError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _yaml():
    try:
        import yaml
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("PyYAML is required to read/write YAML decks: pip install pyyaml") from e
    return yaml


def load(path_or_text) -> dict:
    """Parse a DeckSpec from a file path (.json/.yaml/.yml) or a JSON/YAML string."""
    text = str(path_or_text)
    p = None
    if isinstance(path_or_text, Path) or ("\n" not in text and len(text) < 1024 and Path(text).is_file()):
        p = Path(text)
        text = p.read_text(encoding="utf-8")
    if p is not None and p.suffix.lower() == ".json" or (p is None and text.lstrip().startswith(("{", "["))):
        data = json.loads(text)
    else:
        data = _yaml().safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("a DeckSpec must be a mapping at the top level")
    return data


def dump_json(deck: dict) -> str:
    return json.dumps(deck, indent=2, ensure_ascii=False) + "\n"


def dump_yaml(deck: dict) -> str:
    return _yaml().safe_dump(deck, sort_keys=False, allow_unicode=True, width=100)


def _scan(node, path: str, errs: list[SpecError]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            sub = f"{path}.{k}"
            if isinstance(k, str) and k.lower() in FORBIDDEN_KEYS:
                errs.append(SpecError(sub, f"forbidden key {k!r}: {_FORBIDDEN_MSG}"))
            _scan(v, sub, errs)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan(v, f"{path}[{i}]", errs)
    elif isinstance(node, str) and (_HEX.search(node) or "rgb(" in node.lower()):
        errs.append(SpecError(path, f"colour value {node!r}: {_FORBIDDEN_MSG}"))


def _registry():
    try:
        from om.deck import archetypes
        return archetypes.REGISTRY
    except Exception:
        return None


def _type_err(errs, path, val, typ, key=None):
    if not isinstance(val, typ):
        errs.append(SpecError(path, f"expected {typ.__name__}, got {type(val).__name__}"))
        return False
    return True


def _is_date(s) -> bool:
    try:
        _dt.date.fromisoformat(s)
        return isinstance(s, str)
    except (TypeError, ValueError):
        return False


def validate(deck: dict, *, skeleton: bool = False) -> list[SpecError]:
    """Return all problems. `skeleton=True` (ghost-deck output) skips empty-blocks/source checks."""
    warnings.clear()
    errs: list[SpecError] = []
    if not isinstance(deck, dict):
        return [SpecError("$", "deck must be a mapping")]
    _scan(deck, "$", errs)
    for k in ("deck_id", "title", "lang", "slides"):
        if k not in deck:
            errs.append(SpecError(f"$.{k}", "missing required key"))
    for k in ("deck_id", "title", "client", "art_direction", "theme"):
        if k in deck and not isinstance(deck[k], str):
            errs.append(SpecError(f"$.{k}", "expected string"))
    if "lang" in deck and deck["lang"] not in ("en", "ar"):
        errs.append(SpecError("$.lang", f"{deck['lang']!r} not in ['en', 'ar']"))
    if "as_of" in deck and not _is_date(deck["as_of"]):
        errs.append(SpecError("$.as_of", "expected ISO date YYYY-MM-DD"))
    slides = deck.get("slides")
    if slides is None:
        return errs
    if not _type_err(errs, "$.slides", slides, list):
        return errs
    if not slides:
        errs.append(SpecError("$.slides", "at least one slide required"))
    reg = _registry()
    if reg is None:
        warnings.append("om.deck.archetypes not importable: archetype ids and blocks not checked")
    seen: set = set()
    for i, s in enumerate(slides):
        p = f"$.slides[{i}]"
        if not _type_err(errs, p, s, dict):
            continue
        for k in ("id", "archetype", "title"):
            if k not in s:
                errs.append(SpecError(f"{p}.{k}", "missing required key"))
            elif not isinstance(s[k], str) or not s[k].strip():
                errs.append(SpecError(f"{p}.{k}", "expected non-empty string"))
        if isinstance(s.get("id"), str):
            if s["id"] in seen:
                errs.append(SpecError(f"{p}.id", f"duplicate slide id {s['id']!r}"))
            seen.add(s["id"])
        for k in ("source", "notes"):
            if k in s and not isinstance(s[k], str):
                errs.append(SpecError(f"{p}.{k}", "expected string"))
        if "as_of" in s and not _is_date(s["as_of"]):
            errs.append(SpecError(f"{p}.as_of", "expected ISO date YYYY-MM-DD"))
        blocks = s.get("blocks", {})
        if "blocks" in s and not isinstance(blocks, dict):
            errs.append(SpecError(f"{p}.blocks", "expected object"))
            blocks = {}
        v = s.get("visual")
        if v is not None:
            if not isinstance(v, dict):
                errs.append(SpecError(f"{p}.visual", "expected object"))
            else:
                if "concept" in v and not isinstance(v["concept"], str):
                    errs.append(SpecError(f"{p}.visual.concept", "expected string"))
                if "kind" in v and v["kind"] not in VISUAL_KINDS:
                    errs.append(SpecError(f"{p}.visual.kind", f"{v['kind']!r} not in {list(VISUAL_KINDS)}"))
        aid = s.get("archetype")
        if reg is not None and isinstance(aid, str):
            if aid not in reg:
                close = difflib.get_close_matches(aid, list(reg), n=3, cutoff=0.5)
                hint = f"; did you mean {', '.join(close)}?" if close else ""
                errs.append(SpecError(f"{p}.archetype", f"unknown archetype {aid!r}{hint}"))
                continue
            a = reg[aid]
            if not skeleton:
                schema = getattr(a, "schema", None)
                if schema:
                    from om.llm import validate as jsv
                    msg = jsv(blocks, schema, f"{p}.blocks")
                    if msg:
                        loc, _, rest = msg.partition(": ")
                        errs.append(SpecError(loc, rest or msg))
                if getattr(a, "data", False):
                    for k in ("source", "as_of"):
                        if not s.get(k):
                            errs.append(SpecError(f"{p}.{k}", f"data archetype {aid!r} requires {k}"))
    return errs
