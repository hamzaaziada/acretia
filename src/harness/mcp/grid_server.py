"""Document Grid MCP server (read-only over grid_cells). Run: python3 -m src.harness.mcp.grid_server [--db PATH]

DB path: ``--db`` or env ACRETIA_GRID_DB (must resolve inside ACRETIA_MCP_ROOT); default in-memory.
Backend: env ACRETIA_GRID_BACKEND = duckdb (default) | sqlite.
"""
from __future__ import annotations

import os
import re
import sys

from om.storage import AnalyticsDB, ensure_grid_schema

from ..router import ToolRegistry
from .paths import resolve_in_root
from .server import MCPServer, ToolFailure

MAX_ROWS = 1000
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
    if re.search(r"\b(from|join)\s*(\(\s*)?['\"`\x01]", bare, re.I) or re.search(r"\b(from|join)\s+\$", bare, re.I):
        raise ToolFailure("file or string table sources are not allowed")
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", bare.lower())
    if not words or words[0] not in ("select", "with"):
        raise ToolFailure("only SELECT queries are allowed")
    bad = sorted(set(words) & _FORBIDDEN)
    if bad:
        raise ToolFailure(f"forbidden keyword(s): {', '.join(bad)}")
    return sql.strip()


def build_registry(db: AnalyticsDB) -> ToolRegistry:
    reg = ToolRegistry()

    def grid_query(sql: str, params: list | None = None, limit: int = 200) -> dict:
        """Run one read-only SELECT over the grid tables. Rows are capped at `limit` (max 1000)."""
        q = check_select(sql)
        limit = max(1, min(int(limit), MAX_ROWS))
        try:
            rows = db.query(f"SELECT * FROM ({q}) AS _q LIMIT {limit + 1}", params or [])
        except Exception as e:
            raise ToolFailure(f"query failed: {type(e).__name__}: {e}") from None
        return {"rows": rows[:limit], "row_count": min(len(rows), limit), "truncated": len(rows) > limit}

    def grid_cell(grid_id: str, doc_id: str, question_id: str) -> dict:
        """Fetch one grid cell (answer, quote, page, bbox, confidence) by its key."""
        rows = db.query("SELECT * FROM grid_cells WHERE grid_id = ? AND doc_id = ? AND question_id = ?",
                        [grid_id, doc_id, question_id])
        return {"found": bool(rows), "cell": rows[0] if rows else None}

    def grid_schema() -> dict:
        """Describe the grid tables and their columns."""
        out = {}
        for t in ("grid_cells", "grid_runs"):
            if db.backend == "duckdb":
                cols = db.query("SELECT column_name AS name, data_type AS type FROM information_schema.columns "
                                "WHERE table_name = ? ORDER BY ordinal_position", [t])
            else:
                cols = [{"name": r["name"], "type": r["type"]} for r in db.query(f"PRAGMA table_info({t})")]
            out[t] = {"columns": cols, "rows": db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]}
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
