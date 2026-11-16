"""Deck MCP server. Run: python3 -m src.harness.mcp.deck_server  (paths confined to ACRETIA_MCP_ROOT).

pptx_validate: delegates to a ``validate_pptx`` module (om.validate_pptx / src.validate_pptx / validate_pptx) when
importable; otherwise, for a layout JSON file (.json), runs the om.spacing checks; otherwise unavailable.
deck_render: unavailable unless a deck engine module (om.deck, om.deck_engine, src.deck) exists.
"""
from __future__ import annotations

import importlib
import json
import os

from ..router import ToolRegistry
from .paths import PathError, resolve_in_root
from .server import MCPServer, ToolFailure

_VALIDATORS = ("om.validate_pptx", "src.validate_pptx", "validate_pptx")
_ENGINES = ("om.deck", "om.deck_engine", "src.deck")


def _import_first(names):
    for n in names:
        try:
            return importlib.import_module(n)
        except ImportError:
            continue
    return None


def _path(p, suffixes):
    try:
        return resolve_in_root(p, suffixes=suffixes)
    except PathError as e:
        raise ToolFailure(str(e)) from None


def _call(mod, names, p):
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            try:
                return {"available": True, "result": fn(str(p))}
            except Exception as e:
                return {"available": False, "reason": f"{mod.__name__}.{n} failed: {type(e).__name__}: {e}"}
    return {"available": False, "reason": f"{mod.__name__} exposes none of {list(names)}"}


def pptx_validate(path: str) -> dict:
    """Validate a deck (.pptx) or check a layout JSON (.json) against the spacing rules."""
    p = _path(path, (".pptx", ".json"))
    if p.suffix.lower() == ".pptx":
        mod = _import_first(_VALIDATORS)
        if mod is None:
            return {"available": False, "reason": "no validate_pptx module is installed"}
        return _call(mod, ("validate_pptx", "validate", "check"), p)
    from om import spacing
    try:
        layout = json.loads(p.read_text(encoding="utf-8"))
        issues = spacing.check(layout)
    except Exception as e:
        raise ToolFailure(f"layout check failed: {type(e).__name__}: {e}") from None
    return {"available": True, "engine": "om.spacing", "issues": issues, "ok": not issues}


def deck_render(path: str) -> dict:
    """Render a deck to images via the deck engine, if installed."""
    p = _path(path, (".pptx", ".json"))
    mod = _import_first(_ENGINES)
    if mod is None:
        return {"available": False, "reason": "the deck engine module is not installed"}
    return _call(mod, ("render", "render_deck"), p)


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    schema = {"type": "object", "required": ["path"], "additionalProperties": False, "properties": {"path": {"type": "string"}}}
    reg.register("pptx_validate", pptx_validate, schema, task_types=["reasoning", "vision_critic"],
                 description="Validate a pptx, or spacing-check a layout JSON.")
    reg.register("deck_render", deck_render, schema, task_types=["reasoning", "vision_critic"],
                 description="Render a deck (needs the deck engine).")
    return reg


def make_server(evidence_path=None) -> MCPServer:
    return MCPServer("acretia-deck", build_registry(), evidence_path or os.environ.get("ACRETIA_EVIDENCE_PATH"))


if __name__ == "__main__":
    make_server().serve_stdio()
