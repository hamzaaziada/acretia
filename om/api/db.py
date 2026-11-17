"""SQLite helpers for the product API: connect, migrate, ids, clock, transactions."""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import importlib
import os
import secrets
import sqlite3
from pathlib import Path

SCHEMA_MODULES: tuple[str, ...] = (
    "om.api.auth",
    "om.api.audit",
    "om.api.deals",
    "om.api.library",
    "om.api.notify",
    "om.api.jobs",
    "om.api.agents.library",
    "om.api.citations",
    "om.api.viewers",
    "om.api.firm",
    "om.api.mail",
    "om.api.grid",
    "om.api.decks",
)


def connect(path) -> sqlite3.Connection:
    """WAL SQLite connection (Row factory, FKs on, 5 s busy timeout, shareable across threads).

    Autocommit mode (isolation_level=None); use `tx(conn)` for explicit transactions."""
    p = str(path)
    if p != ":memory:":
        Path(p).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, check_same_thread=False, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    if p != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection, modules=SCHEMA_MODULES) -> list[str]:
    """Run each module's `SCHEMA` (idempotent DDL). Returns the names of modules applied.

    A module that does not exist yet is skipped; any other import error propagates."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_versions (module TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied: list[str] = []
    for name in modules:
        try:
            mod = importlib.import_module(name)
        except ModuleNotFoundError as e:
            if e.name and (name == e.name or name.startswith(e.name + ".")):
                continue
            raise
        schema = getattr(mod, "SCHEMA", None)
        if not schema:
            continue
        conn.executescript(schema)
        digest = hashlib.sha256(schema.encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO schema_versions(module, sha256, applied_at) VALUES(?,?,?) "
            "ON CONFLICT(module) DO UPDATE SET sha256=excluded.sha256, applied_at=excluded.applied_at",
            (name, digest, now()),
        )
        applied.append(name)
    return applied


def new_id(prefix: str) -> str:
    """`<prefix>_<16 hex>`. Deal ids come from DealStore, never from here."""
    if prefix == "deal":
        raise ValueError("deal ids are made by DealStore, not new_id()")
    return f"{prefix}_{secrets.token_hex(8)}"


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextlib.contextmanager
def tx(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT, ROLLBACK on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
