"""Excel MCP server. Run: python3 -m src.harness.mcp.excel_server  (paths confined to ACRETIA_MCP_ROOT)."""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

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


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_XLSX_CELLS = 2_000_000
MAX_ZIP_ENTRIES = 5000
CHILD_MEM_BYTES = int(1.5 * 1024 ** 3)
CHILD_TIMEOUT_S = 60.0
_CELL = re.compile(rb"<c[ >/]")
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _limit(msg: str, which: str, **extra) -> ToolFailure:
    return ToolFailure(msg, {"code": "xlsx_limit_exceeded", "limit": which, **extra})


def precheck_xlsx(p, *, max_file=MAX_FILE_BYTES, max_unzipped=MAX_UNCOMPRESSED_BYTES, max_cells=MAX_XLSX_CELLS) -> dict:
    """Refuse oversize/over-ratio workbooks before anything is parsed: file size, zip entry sizes, and a streamed
    count of `<c ` cell elements read through a bounded reader (never more than the declared size)."""
    size = os.path.getsize(p)
    if size > max_file:
        raise _limit(f"file is {size} bytes; the limit is {max_file}", "file_bytes", observed=size)
    try:
        zf = zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        raise ToolFailure("not a valid xlsx (zip) file", {"code": "xlsx_invalid"}) from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise _limit(f"{len(infos)} zip entries; the limit is {MAX_ZIP_ENTRIES}", "zip_entries")
        total = sum(i.file_size for i in infos)
        if total > max_unzipped:
            raise _limit(f"uncompressed content is {total} bytes; the limit is {max_unzipped}", "uncompressed_bytes",
                         observed=total)
        cells = 0
        for i in infos:
            if not (i.filename.startswith("xl/worksheets/") and i.filename.endswith(".xml")):
                continue
            read, tail = 0, b""
            with zf.open(i) as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    read += len(chunk)
                    if read > i.file_size + (1 << 20):
                        raise _limit("zip entry larger than its declared size", "uncompressed_bytes")
                    buf = tail + chunk
                    cells += len(_CELL.findall(buf))
                    tail = buf[-2:]  # a 3-byte pattern cannot fit in the tail, so nothing is counted twice
                    if cells > max_cells:
                        raise _limit(f"more than {max_cells} cells", "cells", observed=cells)
        if cells > max_cells:
            raise _limit(f"more than {max_cells} cells", "cells", observed=cells)
    return {"file_bytes": size, "uncompressed_bytes": total, "cells": cells}


def _preexec(mem_bytes):
    def fn():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except Exception:
            pass
    return fn


def run_isolated(job: dict, *, mem_bytes: int = CHILD_MEM_BYTES, timeout: float = CHILD_TIMEOUT_S) -> dict:
    """Run one worker job in a child process under RLIMIT_AS with a wall-clock timeout."""
    from .client import child_env
    env = child_env({"PYTHONPATH": str(_REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")})
    try:
        proc = subprocess.run([sys.executable, "-m", "src.harness.mcp.excel_worker"], input=json.dumps(job),
                              capture_output=True, text=True, timeout=timeout, env=env, cwd=str(_REPO_ROOT),
                              preexec_fn=_preexec(mem_bytes) if os.name == "posix" else None)
    except subprocess.TimeoutExpired:
        raise ToolFailure(f"workbook evaluation exceeded the {timeout:g}s timeout",
                          {"code": "xlsx_timeout", "limit": "seconds"}) from None
    marker = "@@RESULT@@"
    out = proc.stdout or ""
    if marker not in out:
        oom = proc.returncode in (-9, -11) or "MemoryError" in (proc.stderr or "")
        raise ToolFailure("workbook evaluation exceeded the memory limit" if oom else
                          f"workbook worker failed (exit {proc.returncode})",
                          {"code": "xlsx_memory_limit" if oom else "xlsx_worker_failed", "limit": "memory" if oom else None})
    res = json.loads(out.rsplit(marker, 1)[1].strip().splitlines()[0])
    if "failure" in res:
        code = res.get("code")
        raise ToolFailure(res["failure"], {"code": code or "xlsx_error"} if code else None)
    return res


def xlsx_evaluate(path: str, cells: list) -> dict:
    """Compute values for cells like "Sheet1!B4" via om.formula (formulas re-evaluated from scratch)."""
    if len(cells) > MAX_CELLS:
        raise ToolFailure(f"too many cells (max {MAX_CELLS})")
    p = _path(path)
    precheck_xlsx(p)
    res = run_isolated({"op": "evaluate", "path": str(p), "cells": [str(c) for c in cells]})
    return {"path": str(path), "values": res["values"], "unsupported_functions": res["unsupported_functions"]}


def xlsx_grade(path: str) -> dict:
    """Grade a workbook with om.modelcheck."""
    p = _path(path)
    precheck_xlsx(p)
    return run_isolated({"op": "grade", "path": str(p)})["result"]


def xlsx_recalc(path: str) -> dict:
    """Three-engine recalculation via om.recalc when present."""
    p = _path(path)
    precheck_xlsx(p)
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
