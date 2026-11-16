"""Document Grid MCP server (read-only over grid_cells). Run: python3 -m src.harness.mcp.grid_server [--db PATH]

DB path: ``--db`` or env ACRETIA_GRID_DB (must resolve inside ACRETIA_MCP_ROOT); default in-memory.
Backend: env ACRETIA_GRID_BACKEND = duckdb (default) | sqlite.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse

from om.storage import AnalyticsDB, ensure_grid_schema

from ..router import ToolRegistry
from .paths import resolve_in_root
from .server import MCPServer, ToolFailure

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


# ------------------------------------------------------------------------------------------------ hardened engine
class _Shim:
    """Just enough of AnalyticsDB for ensure_grid_schema."""

    def __init__(self, backend, conn):
        self.backend, self._conn = backend, conn

    def execute(self, sql, params=()):
        self._conn.execute(sql, list(params or ()))


def _cursor_rows(cur, n):
    cols = [d[0] for d in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchmany(n)]


def _open_duckdb(db):
    import duckdb
    path = getattr(db, "path", ":memory:")
    if path != ":memory:" and os.path.exists(path) and getattr(db, "_conn", None) is None:
        try:
            return duckdb.connect(path, read_only=True, config=dict(DUCKDB_CONFIG))
        except Exception:
            pass  # file held open with another configuration in this process: fall back to a snapshot
    conn = duckdb.connect(":memory:", config=dict(DUCKDB_CONFIG))
    ensure_grid_schema(_Shim("duckdb", conn))
    for t in GRID_TABLES:
        rows = db.query(f"SELECT * FROM {t}")
        if rows:
            cols = list(rows[0])
            conn.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [[r[c] for c in cols] for r in rows])
    return conn


_SQLITE_BAD_FUNCS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


def _sqlite_authorizer(action, a1, a2, dbname, source):
    ok = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
    if action in ok:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and a1 == "table_info":  # schema metadata only (grid_schema)
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(a2).lower() not in _SQLITE_BAD_FUNCS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _open_sqlite(db):
    path = getattr(db, "path", ":memory:")
    conn = None
    if path != ":memory:" and os.path.exists(path):
        try:
            uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        except Exception:
            conn = None
    if conn is None:
        with db._lock:
            src = db._c()
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            src.backup(conn)
    try:
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.Error):
        pass
    conn.execute("PRAGMA query_only=1")
    try:
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_RESULT_BYTES)
    except (AttributeError, sqlite3.Error):
        pass
    conn.set_authorizer(_sqlite_authorizer)
    return conn


def _timeout_value(timeout):
    if timeout is None:
        try:
            timeout = float(os.environ.get("ACRETIA_GRID_TIMEOUT", DEFAULT_TIMEOUT_S))
        except ValueError:
            timeout = DEFAULT_TIMEOUT_S
    return max(0.05, min(float(timeout), MAX_TIMEOUT_S))


def run_select(db, sql: str, params=None, limit: int = 200, timeout=None, check: bool = True) -> dict:
    """Run one read-only SELECT on a hardened, throw-away connection: engine-level no external access, read-only,
    wall-clock timeout, row and byte caps. Raises ToolFailure."""
    q = check_select(sql) if check else sql
    limit = max(1, min(int(limit), MAX_ROWS))
    params = [] if params is None else params
    if not isinstance(params, list) or not all(p is None or isinstance(p, (str, int, float, bool)) for p in params):
        raise ToolFailure("params must be a list of scalars")
    secs = _timeout_value(timeout)
    wrapped = f"SELECT * FROM ({q}) AS _q LIMIT {limit + 1}"
    conn = None
    timed_out = threading.Event()
    timer = None
    try:
        try:
            conn = _open_duckdb(db) if db.backend == "duckdb" else _open_sqlite(db)
        except Exception as e:
            raise ToolFailure(f"cannot open grid database read-only: {type(e).__name__}") from None
        if db.backend == "duckdb":
            def fire():
                timed_out.set()
                try:
                    conn.interrupt()
                except Exception:
                    pass
            timer = threading.Timer(secs, fire)
            timer.daemon = True
            timer.start()
        else:
            deadline = time.monotonic() + secs

            def progress():
                if time.monotonic() > deadline:
                    timed_out.set()
                    return 1
                return 0
            conn.set_progress_handler(progress, 1000)
        try:
            cur = conn.execute(wrapped, params)
            rows = _cursor_rows(cur, limit + 1)
        except Exception as e:
            if timed_out.is_set():
                raise ToolFailure(f"query exceeded the {secs:g}s timeout") from None
            raise ToolFailure(f"query failed: {type(e).__name__}: {str(e)[:300]}") from None
        if timed_out.is_set():
            raise ToolFailure(f"query exceeded the {secs:g}s timeout")
    finally:
        if timer is not None:
            timer.cancel()
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    out, size, byte_trunc = [], 0, False
    for r in rows[:limit]:
        n = len(json.dumps(r, ensure_ascii=False, default=str))
        if size + n > MAX_RESULT_BYTES:
            if not out:
                raise ToolFailure(f"a single row exceeds the {MAX_RESULT_BYTES} byte result cap")
            byte_trunc = True
            break
        size += n
        out.append(r)
    return {"rows": out, "row_count": len(out), "truncated": len(rows) > limit or byte_trunc,
            "bytes_truncated": byte_trunc}


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
