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


def xlsx_recalc(path: str, engines: list | None = None) -> dict:
    """Three-engine recalculation via om.recalc.compare: LibreOffice + formulon + om.formula + cached values.

    Returns per-cell divergences. Engines that are not installed are reported in `engines` with a reason and
    are simply not compared, so this never fails just because LibreOffice is missing.
    """
    p = _path(path)
    try:
        mod = importlib.import_module("om.recalc")
    except ImportError:
        return {"available": False, "reason": "om.recalc is not installed"}
    if engines is not None:
        bad = [e for e in engines if e not in mod.DEFAULT_ENGINES]
        if bad:
            raise ToolFailure(f"unknown engine(s) {bad}; choose from {list(mod.DEFAULT_ENGINES)}")
    try:
        report = mod.compare(p.read_bytes(), engines=engines)
    except Exception as e:                                    # noqa: BLE001
        return {"available": False, "reason": f"om.recalc.compare failed: {type(e).__name__}: {e}"}
    return {"available": True, "result": report}


def xlsx_engine_status() -> dict:
    """Which recalculation engines are installed and running right now (no recalculation performed)."""
    try:
        mod = importlib.import_module("om.recalc")
    except ImportError:
        return {"available": False, "reason": "om.recalc is not installed"}
    return {"available": True, "result": mod.engine_status()}


def xlsx_engine_restart() -> dict:
    """Restart the persistent headless LibreOffice daemon and report the new engine status."""
    try:
        mod = importlib.import_module("om.recalc")
    except ImportError:
        return {"available": False, "reason": "om.recalc is not installed"}
    try:
        return {"available": True, "result": mod.restart_daemon()}
    except Exception as e:                                    # noqa: BLE001
        return {"available": False, "reason": f"restart failed: {type(e).__name__}: {e}"}


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    path = {"type": "string"}
    reg.register("xlsx_evaluate", xlsx_evaluate, {
        "type": "object", "required": ["path", "cells"], "additionalProperties": False,
        "properties": {"path": path, "cells": {"type": "array", "items": {"type": "string"}}}},
        task_types=["modeling"], description="Compute values for cells (Sheet!A1 refs) of an xlsx via om.formula.")
    reg.register("xlsx_grade", xlsx_grade, {"type": "object", "required": ["path"], "additionalProperties": False,
                                            "properties": {"path": path}}, task_types=["modeling"],
                 description="Grade a workbook with om.modelcheck.")
    reg.register("xlsx_recalc", xlsx_recalc, {
        "type": "object", "required": ["path"], "additionalProperties": False,
        "properties": {"path": path, "engines": {"type": "array", "items": {"type": "string"}}}},
        task_types=["modeling"],
        description="Recalculate a workbook with every available engine and report per-cell divergences.")
    reg.register("xlsx_engine_status", xlsx_engine_status, {
        "type": "object", "required": [], "additionalProperties": False, "properties": {}},
        task_types=["modeling"], description="Which recalculation engines are installed and running.")
    reg.register("xlsx_engine_restart", xlsx_engine_restart, {
        "type": "object", "required": [], "additionalProperties": False, "properties": {}},
        task_types=["modeling"], description="Restart the headless LibreOffice daemon.")
    return reg


def make_server(evidence_path=None) -> MCPServer:
    return MCPServer("acretia-excel", build_registry(), evidence_path or os.environ.get("ACRETIA_EVIDENCE_PATH"))


if __name__ == "__main__":
    make_server().serve_stdio()
