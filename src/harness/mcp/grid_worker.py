"""Child-process worker for the grid MCP server. Reads one JSON job on stdin, writes one JSON result on stdout.

The parent starts it under RLIMIT_AS / RLIMIT_CPU and a wall-clock kill, so list and unnest allocations that
DuckDB's buffer manager does not account for cannot exhaust the host. The hardened engine setup lives here."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.parse

MAX_ROWS = 1000
MAX_RESULT_BYTES = 4 * 1024 * 1024
GRID_TABLES = ("grid_cells", "grid_runs")
DUCKDB_CONFIG = {"enable_external_access": False, "lock_configuration": True, "autoload_known_extensions": False,
                 "autoinstall_known_extensions": False, "max_memory": "512MB", "threads": 2}


class _Shim:
    def __init__(self, backend, conn):
        self.backend, self._conn = backend, conn

    def execute(self, sql, params=()):
        self._conn.execute(sql, list(params or ()))


class OpenFailed(Exception):
    pass


def _load_snapshot(conn, snapshot):
    for t, rows in snapshot.items():
        if rows:
            cols = list(rows[0])
            conn.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [[r[c] for c in cols] for r in rows])


def _open_duckdb(job):
    import duckdb
    from om.storage import ensure_grid_schema
    if job.get("path"):
        try:
            return duckdb.connect(job["path"], read_only=True, config=dict(DUCKDB_CONFIG))
        except Exception as e:
            raise OpenFailed(type(e).__name__) from None
    conn = duckdb.connect(":memory:", config=dict(DUCKDB_CONFIG))
    ensure_grid_schema(_Shim("duckdb", conn))
    _load_snapshot(conn, job.get("snapshot") or {})
    return conn


_SQLITE_BAD_FUNCS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


def _sqlite_authorizer(action, a1, a2, dbname, source):
    ok = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
    if action in ok:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and a1 == "table_info":
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(a2).lower() not in _SQLITE_BAD_FUNCS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _open_sqlite(job):
    from om.storage import ensure_grid_schema
    conn = None
    if job.get("path"):
        try:
            uri = "file:" + urllib.parse.quote(os.path.abspath(job["path"])) + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
        except Exception as e:
            raise OpenFailed(type(e).__name__) from None
    else:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        ensure_grid_schema(_Shim("sqlite", conn))
        _load_snapshot(conn, job.get("snapshot") or {})
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


def run(job: dict) -> dict:
    secs = float(job["timeout"])
    duck = job["backend"] == "duckdb"
    try:
        conn = _open_duckdb(job) if duck else _open_sqlite(job)
    except OpenFailed as e:
        return {"failure": f"cannot open grid database read-only: {e}", "code": "open_failed"}
    except Exception as e:
        return {"failure": f"cannot open grid database read-only: {type(e).__name__}"}
    timed_out = threading.Event()
    timer = None
    if duck:
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
    limit = job["limit"]
    try:
        cur = conn.execute(job["sql"], job["params"])
        cols = [d[0] for d in (cur.description or [])]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(limit + 1)]
    except Exception as e:
        if timed_out.is_set():
            return {"failure": f"query exceeded the {secs:g}s timeout", "code": "grid_timeout"}
        if isinstance(e, MemoryError) or "out of memory" in str(e).lower():
            return {"failure": "query exceeded the memory limit", "code": "grid_memory_limit"}
        return {"failure": f"query failed: {type(e).__name__}: {str(e)[:300]}"}
    finally:
        if timer is not None:
            timer.cancel()
    if timed_out.is_set():
        return {"failure": f"query exceeded the {secs:g}s timeout", "code": "grid_timeout"}
    out, size, byte_trunc = [], 0, False
    for r in rows[:limit]:
        n = len(json.dumps(r, ensure_ascii=False, default=str))
        if size + n > MAX_RESULT_BYTES:
            if not out:
                return {"failure": f"a single row exceeds the {MAX_RESULT_BYTES} byte result cap"}
            byte_trunc = True
            break
        size += n
        out.append(r)
    return {"rows": out, "row_count": len(out), "truncated": len(rows) > limit or byte_trunc,
            "bytes_truncated": byte_trunc}


def main() -> None:
    job = json.loads(sys.stdin.read())
    try:
        res = run(job)
    except MemoryError:
        res = {"failure": "query exceeded the memory limit", "code": "grid_memory_limit"}
    except Exception as e:
        res = {"failure": f"{type(e).__name__}: {str(e)[:300]}"}
    sys.stdout.write("\n@@RESULT@@" + json.dumps(res, default=str) + "\n")
    sys.stdout.flush()
    os._exit(0)  # skip interpreter teardown (duckdb threads) for latency


if __name__ == "__main__":
    main()
