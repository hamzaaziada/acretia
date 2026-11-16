"""Excel MCP server. Run: python3 -m src.harness.mcp.excel_server  (paths confined to ACRETIA_MCP_ROOT)."""
from __future__ import annotations

import importlib
import os
import re
import sys

from ..router import ToolRegistry
from .paths import PathError, resolve_in_root
from .server import MCPServer, ToolFailure

XLSX = (".xlsx", ".xlsm")
MAX_CELLS = 5000


def _path(p) -> "os.PathLike":
    try:
        return resolve_in_root(p, suffixes=XLSX)
    except PathError as e:
        raise ToolFailure(str(e)) from None


def _plain(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)  # formula error objects etc.


def xlsx_evaluate(path: str, cells: list) -> dict:
    """Compute values for cells like "Sheet1!B4" via om.formula (formulas re-evaluated from scratch)."""
    from om import formula as fx
    from om import xlsx
    if len(cells) > MAX_CELLS:
        raise ToolFailure(f"too many cells (max {MAX_CELLS})")
    book = xlsx.read(_path(path).read_bytes())
    eng = fx.from_book(book)
    eng.calculate(iterate=True)
    out = {}
    for ref in cells:
        m = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^'!]+))!(\$?[A-Z]{1,3}\$?\d+)", str(ref))
        if not m:
            raise ToolFailure(f"bad cell reference {ref!r}; use Sheet!A1")
        sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
        if sheet not in book.sheets:
            raise ToolFailure(f"no such sheet {sheet!r}")
        r, c = xlsx.split_ref(m.group(3))
        raw = book.sheets[sheet].get((r, c))
        out[str(ref)] = {"value": _plain(eng.values.get((sheet, r, c), raw.value if raw else None)),
                         "formula": raw.formula if raw else None}
    return {"path": str(path), "values": out, "unsupported_functions": sorted(map(str, eng.unsupported))[:50]}


def xlsx_grade(path: str) -> dict:
    """Grade a workbook with om.modelcheck."""
    from om import modelcheck
    return modelcheck.grade(_path(path).read_bytes())


def xlsx_recalc(path: str) -> dict:
    """Three-engine recalculation via om.recalc when present."""
    p = _path(path)
    try:
        mod = importlib.import_module("om.recalc")
    except ImportError:
        return {"available": False, "reason": "om.recalc is not installed"}
    for name in ("recalc_file", "recalc", "recalculate", "three_engine", "check"):
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                try:
                    res = fn(str(p))
                except TypeError:
                    res = fn(p.read_bytes())
            except Exception as e:
                return {"available": False, "reason": f"om.recalc.{name} failed: {type(e).__name__}: {e}"}
            return {"available": True, "result": res}
    return {"available": False, "reason": "om.recalc exposes no recalc entry point"}


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    path = {"type": "string"}
    reg.register("xlsx_evaluate", xlsx_evaluate, {
        "type": "object", "required": ["path", "cells"], "additionalProperties": False,
        "properties": {"path": path, "cells": {"type": "array", "items": {"type": "string"}}}},
        task_types=["modeling"], description="Compute values for cells (Sheet!A1 refs) of an xlsx via om.formula.")
    for n, f, d in (("xlsx_grade", xlsx_grade, "Grade a workbook with om.modelcheck."),
                    ("xlsx_recalc", xlsx_recalc, "Recalculate with om.recalc if available.")):
        reg.register(n, f, {"type": "object", "required": ["path"], "additionalProperties": False,
                            "properties": {"path": path}}, task_types=["modeling"], description=d)
    return reg


def make_server(evidence_path=None) -> MCPServer:
    return MCPServer("acretia-excel", build_registry(), evidence_path or os.environ.get("ACRETIA_EVIDENCE_PATH"))


if __name__ == "__main__":
    make_server().serve_stdio()
