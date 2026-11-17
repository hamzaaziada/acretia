"""Document Grid MCP server (read-only over grid_cells). Run: python3 -m src.harness.mcp.grid_server [--db PATH]

DB path: ``--db`` or env ACRETIA_GRID_DB (must resolve inside ACRETIA_MCP_ROOT); default in-memory.
Backend: env ACRETIA_GRID_BACKEND = duckdb (default) | sqlite.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from om.storage import AnalyticsDB, ensure_grid_schema

from ..router import ToolRegistry
from .paths import resolve_in_root
from .server import MCPServer, ToolFailure  # noqa: F401

MAX_ROWS = 1000
MAX_RESULT_BYTES = 4 * 1024 * 1024
DEFAULT_TIMEOUT_S = 5.0
MAX_TIMEOUT_S = 60.0
GRID_TABLES = ("grid_cells", "grid_runs")
DUCKDB_CONFIG = {"enable_external_access": False, "lock_configuration": True, "autoload_known_extensions": False,
                 "autoinstall_known_extensions": False, "max_memory": "512MB", "threads": 2}
# Defence in depth only: the engine settings (external access off, read-only, authorizer) are the real control.
_FORBIDDEN_FUNC = re.compile(
    r"\b(read_\w+|\w+_scan|query|query_table|duckdb_\w+|pragma_\w+|sqlite_\w+|current_setting|getenv|"
    r"load_extension|readfile|writefile|glob|list_files)\b", re.I)
_FORBIDDEN = {
    "attach", "detach", "copy", "pragma", "insert", "update", "delete", "drop", "create", "alter", "replace",
    "truncate", "install", "load", "export", "import", "call", "set", "reset", "vacuum", "checkpoint", "begin",
    "commit", "rollback", "grant", "revoke", "merge", "use", "glob", "read_csv", "read_csv_auto", "read_json",
    "read_parquet", "read_text", "read_blob", "parquet_scan", "csv_scan", "sqlite_scan", "json_scan", "load_extension",
    "readfile", "writefile", "duckdb_secrets", "pg_read_file", "into",
}


def _strip_literals(sql: str) -> str:
    """Replace '...' string literals with a placeholder so keywords inside data are not mistaken for SQL."""
    return re.sub(r"'(?:[^']|'')*'", "\x01", sql)


def check_select(sql) -> str:
    """Return the cleaned SQL or raise ToolFailure unless it is a single read-only SELECT."""
    if not isinstance(sql, str) or not sql.strip():
        raise ToolFailure("sql must be a non-empty string")
    if len(sql) > 20000 or "\x00" in sql:
        raise ToolFailure("sql too long or contains NUL")
    bare = _strip_literals(sql)
    if "'" in bare:
        raise ToolFailure("unterminated string literal")
    if ";" in bare:
        raise ToolFailure("only a single statement is allowed (no ';')")
    if "--" in bare or "/*" in bare or "*/" in bare:
        raise ToolFailure("SQL comments are not allowed")
    if "$" in bare or re.search(r"\b(from|join)\s*(\(\s*)?['\"`\x01]", bare, re.I):
        raise ToolFailure("file or string table sources are not allowed")
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", bare.lower())
    if not words or words[0] not in ("select", "with"):
        raise ToolFailure("only SELECT queries are allowed")
    if _FORBIDDEN_FUNC.search(bare):
        raise ToolFailure("file, system and meta table functions are not allowed")
    bad = sorted(set(words) & _FORBIDDEN)
    if bad:
        raise ToolFailure(f"forbidden keyword(s): {', '.join(bad)}")
    return sql.strip()


# ------------------------------------------------------------------------------------------ isolated execution
# The engine hardening (external access off, read-only, authorizer, caps) lives in grid_worker.py, which runs in a
# child process under RLIMIT_AS / RLIMIT_CPU: DuckDB's max_memory does not bound list or unnest allocations.
_REPO_ROOT = Path(__file__).resolve().parents[3]
# DuckDB reserves about 1.2 GB of address space at start-up (measured), so RLIMIT_AS below ~1.3 GB cannot even open it;
# 2 GB leaves about 0.8 GB for data. Configurable through ACRETIA_GRID_MEM_MB.
CHILD_MEM_BYTES = int(os.environ.get("ACRETIA_GRID_MEM_MB", "2048")) * 1024 * 1024
KILL_GRACE_S = 2.0


def _preexec(mem_bytes, cpu_s):
    def fn():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        except Exception:
            pass
    return fn


def _snapshot(db):
    return {t: db.query(f"SELECT * FROM {t}") for t in GRID_TABLES}


def _run_child(job: dict, secs: float, mem_bytes: int) -> dict:
    from .client import child_env
    env = child_env({"PYTHONPATH": str(_REPO_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")})
    cpu_s = int(secs * 2 + 3)
    try:
        proc = subprocess.run([sys.executable, "-m", "src.harness.mcp.grid_worker"], input=json.dumps(job, default=str),
                              capture_output=True, text=True, timeout=secs + KILL_GRACE_S, env=env, cwd=str(_REPO_ROOT),
                              preexec_fn=_preexec(mem_bytes, cpu_s) if os.name == "posix" else None)
    except subprocess.TimeoutExpired:
        raise ToolFailure(f"query exceeded the {secs:g}s timeout", {"code": "grid_timeout", "limit": "seconds"}) from None
    marker = "@@RESULT@@"
    out = proc.stdout or ""
    if marker not in out:
        err = (proc.stderr or "")
        if proc.returncode == -24:  # SIGXCPU
            raise ToolFailure(f"query exceeded the {secs:g}s timeout", {"code": "grid_timeout", "limit": "cpu"})
        oom = proc.returncode in (-9, -11, -6) or "MemoryError" in err or "bad_alloc" in err or "out of memory" in err.lower()
        if proc.returncode == -9 and not oom:
            oom = True
        raise ToolFailure("query exceeded the memory limit" if oom else f"grid worker failed (exit {proc.returncode})",
                          {"code": "grid_memory_limit" if oom else "grid_worker_failed",
                           "limit": "memory" if oom else None})
    return json.loads(out.rsplit(marker, 1)[1].strip().splitlines()[0])


def _timeout_value(timeout):
    if timeout is None:
        try:
            timeout = float(os.environ.get("ACRETIA_GRID_TIMEOUT", DEFAULT_TIMEOUT_S))
        except ValueError:
            timeout = DEFAULT_TIMEOUT_S
    return max(0.05, min(float(timeout), MAX_TIMEOUT_S))


def run_select(db, sql: str, params=None, limit: int = 200, timeout=None, check: bool = True) -> dict:
    """Run one read-only SELECT in a resource-limited child process (RLIMIT_AS, RLIMIT_CPU, wall-clock kill) on a
    hardened throw-away connection: no external access, read-only, row and byte caps. Raises ToolFailure with code
    grid_memory_limit or grid_timeout on a breach."""
    q = check_select(sql) if check else sql
    limit = max(1, min(int(limit), MAX_ROWS))
    params = [] if params is None else params
    if not isinstance(params, list) or not all(p is None or isinstance(p, (str, int, float, bool)) for p in params):
        raise ToolFailure("params must be a list of scalars")
    secs = _timeout_value(timeout)
    job = {"backend": db.backend, "sql": f"SELECT * FROM ({q}) AS _q LIMIT {limit + 1}", "params": params,
           "limit": limit, "timeout": secs}
    path = getattr(db, "path", ":memory:")
    if path != ":memory:" and os.path.exists(path) and getattr(db, "_conn", None) is None:
        res = _run_child(dict(job, path=os.path.abspath(path)), secs, CHILD_MEM_BYTES)
        if res.get("code") != "open_failed":
            return _finish(res)
    # in-memory or open handle: hand the child a snapshot of the grid tables
    return _finish(_run_child(dict(job, snapshot=_snapshot(db)), secs, CHILD_MEM_BYTES))


def _finish(res: dict) -> dict:
    if "failure" in res:
        code = res.get("code")
        raise ToolFailure(res["failure"], {"code": code} if code else None)
    return res


def build_registry(db: AnalyticsDB, timeout=None) -> ToolRegistry:
    reg = ToolRegistry()

    def grid_query(sql: str, params: list | None = None, limit: int = 200) -> dict:
        """Run one read-only SELECT over the grid tables. Rows are capped at `limit` (max 1000)."""
        return run_select(db, sql, params, limit, timeout)

    def grid_cell(grid_id: str, doc_id: str, question_id: str) -> dict:
        """Fetch one grid cell (answer, quote, page, bbox, confidence) by its key."""
        rows = run_select(db, "SELECT * FROM grid_cells WHERE grid_id = ? AND doc_id = ? AND question_id = ?",
                          [grid_id, doc_id, question_id], 1, timeout, check=False)["rows"]
        return {"found": bool(rows), "cell": rows[0] if rows else None}

    def grid_schema() -> dict:
        """Describe the grid tables and their columns."""
        out = {}
        for t in GRID_TABLES:
            if db.backend == "duckdb":
                cols = run_select(db, "SELECT column_name AS name, data_type AS type FROM information_schema.columns "
                                      f"WHERE table_name = '{t}' ORDER BY ordinal_position", None, MAX_ROWS, timeout,
                                  check=False)["rows"]
            else:
                cols = [{"name": r["name"], "type": r["type"]} for r in run_select(
                    db, f"SELECT name, type FROM pragma_table_info('{t}')", None, MAX_ROWS, timeout, check=False)["rows"]]
            n = run_select(db, f"SELECT COUNT(*) AS n FROM {t}", None, 1, timeout, check=False)["rows"][0]["n"]
            out[t] = {"columns": cols, "rows": n}
        return {"backend": db.backend, "tables": out}

    reg.register("grid_query", grid_query, {
        "type": "object", "required": ["sql"], "additionalProperties": False,
        "properties": {"sql": {"type": "string"}, "params": {"type": "array"}, "limit": {"type": "integer"}}},
        task_types=["extraction"], description="Read-only single SELECT over grid_cells/grid_runs.")
    reg.register("grid_cell", grid_cell, {
        "type": "object", "required": ["grid_id", "doc_id", "question_id"], "additionalProperties": False,
        "properties": {k: {"type": "string"} for k in ("grid_id", "doc_id", "question_id")}},
        task_types=["extraction"], description="Get one grid cell by grid_id, doc_id and question_id.")
    reg.register("grid_schema", grid_schema, {"type": "object", "properties": {}, "additionalProperties": False},
                 task_types=["extraction"], description="Describe grid tables, columns and row counts.")
    return reg


def open_db(path: str | None = None) -> AnalyticsDB:
    path = path or os.environ.get("ACRETIA_GRID_DB")
    p = ":memory:" if not path or path == ":memory:" else str(resolve_in_root(path, must_exist=False))
    db = AnalyticsDB(p, prefer=os.environ.get("ACRETIA_GRID_BACKEND", "duckdb"))
    ensure_grid_schema(db)
    if p != ":memory:" and db._conn is not None:
        db._conn.close()  # release the read-write handle: queries open their own read-only hardened connections
        db._conn = None
    return db


def make_server(db_path: str | None = None, evidence_path=None) -> MCPServer:
    return MCPServer("acretia-grid", build_registry(open_db(db_path)),
                     evidence_path or os.environ.get("ACRETIA_EVIDENCE_PATH"))


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    db = argv[argv.index("--db") + 1] if "--db" in argv else None
    make_server(db).serve_stdio()


if __name__ == "__main__":
    main()
