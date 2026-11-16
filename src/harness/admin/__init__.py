"""Org admin core (S6.5a): agent toggles, spend limits, sources dashboard, custom MCP tools.

Shared plumbing: SQLite via `om.storage.connect`, role checks, and an append-only audit log. Every table carries
`org_id`; every function takes `org_id` and (for mutations) an `actor` = {"user_id": ..., "role": ...}.
Every public function accepts an optional keyword `db=` (an open sqlite connection or a DSN); without it the DSN
comes from `ACRETIA_ADMIN_DB`, then `ACRETIA_DB`, then `storage/acretia.sqlite`.
"""
from __future__ import annotations

import contextlib
import json
import os
import time

MUTATING_ROLES = ("owner", "admin")


class AdminError(ValueError):
    """Invalid input (bad name, unknown connector, refused command...)."""


class PermissionDenied(PermissionError):
    """The actor's role may not perform this mutation."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL, before TEXT, after TEXT, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_admin_audit_org ON admin_audit(org_id, id);
CREATE TRIGGER IF NOT EXISTS admin_audit_no_update BEFORE UPDATE ON admin_audit
  BEGIN SELECT RAISE(ABORT, 'admin_audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_delete BEFORE DELETE ON admin_audit
  BEGIN SELECT RAISE(ABORT, 'admin_audit is append-only'); END;
CREATE TABLE IF NOT EXISTS admin_agents (
  org_id TEXT NOT NULL, agent_id TEXT NOT NULL, enabled INTEGER NOT NULL, updated_by TEXT, updated_at REAL,
  PRIMARY KEY (org_id, agent_id));
CREATE TABLE IF NOT EXISTS admin_spend_limits (
  org_id TEXT NOT NULL, scope TEXT NOT NULL, scope_id TEXT NOT NULL, period TEXT NOT NULL, limit_usd REAL NOT NULL,
  updated_by TEXT, updated_at REAL, PRIMARY KEY (org_id, scope, scope_id, period));
CREATE TABLE IF NOT EXISTS admin_spend_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, team_id TEXT, deal_id TEXT, job_id TEXT,
  cost_usd REAL NOT NULL, at REAL NOT NULL, month TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_admin_spend_usage ON admin_spend_usage(org_id, month);
CREATE TABLE IF NOT EXISTS admin_sources (
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, connector TEXT NOT NULL, config_ref TEXT NOT NULL,
  created_by TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS admin_source_syncs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL, source_id TEXT NOT NULL, status TEXT NOT NULL,
  items INTEGER NOT NULL, errors INTEGER NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_admin_source_syncs ON admin_source_syncs(org_id, source_id, at);
CREATE TABLE IF NOT EXISTS admin_mcp_servers (
  org_id TEXT NOT NULL, name TEXT NOT NULL, transport TEXT NOT NULL, command TEXT, url TEXT, env_refs TEXT NOT NULL,
  allow_tools TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at REAL,
  PRIMARY KEY (org_id, name));
CREATE TABLE IF NOT EXISTS admin_mcp_allowlist (
  org_id TEXT PRIMARY KEY, executables TEXT NOT NULL, updated_by TEXT, updated_at REAL);
"""
_ready: set = set()


@contextlib.contextmanager
def conn(db=None):
    """Yield a sqlite connection with the admin schema in place; close it only when we opened it."""
    own = False
    if db is None or isinstance(db, (str, os.PathLike)):
        from om import storage
        db = storage.connect(str(db or os.environ.get("ACRETIA_ADMIN_DB") or os.environ.get("ACRETIA_DB")
                                 or "storage/acretia.sqlite"))
        own = True
    try:
        db.executescript(_SCHEMA)
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        if own:
            db.close()


def actor_parts(actor) -> tuple[str, str]:
    if isinstance(actor, dict):
        uid, role = actor.get("user_id") or actor.get("id"), actor.get("role")
    elif isinstance(actor, (tuple, list)) and len(actor) == 2:
        uid, role = actor
    else:
        uid, role = getattr(actor, "user_id", None), getattr(actor, "role", None)
    if not uid or not isinstance(uid, str) or not isinstance(role, str):
        raise PermissionDenied("actor must carry a user_id and a role")
    return uid, role


def require_admin(actor) -> tuple[str, str]:
    uid, role = actor_parts(actor)
    if role not in MUTATING_ROLES:
        raise PermissionDenied(f"role {role!r} may not change admin settings (needs owner or admin)")
    return uid, role


def need_org(org_id) -> str:
    if not isinstance(org_id, str) or not org_id.strip():
        raise AdminError("org_id must be a non-empty string")
    return org_id


def audit(db, org_id: str, actor, action: str, target: str, before=None, after=None) -> None:
    uid, role = actor_parts(actor)
    db.execute("INSERT INTO admin_audit(org_id,actor_id,actor_role,action,target,before,after,at) VALUES (?,?,?,?,?,?,?,?)",
               (org_id, uid, role, action, target,
                None if before is None else json.dumps(before, sort_keys=True, default=str),
                None if after is None else json.dumps(after, sort_keys=True, default=str), time.time()))


def audit_log(org_id: str, *, action: str | None = None, db=None) -> list[dict]:
    """Audit rows of one org, oldest first (before/after decoded)."""
    need_org(org_id)
    with conn(db) as c:
        q, a = "SELECT * FROM admin_audit WHERE org_id=?", [org_id]
        if action:
            q, a = q + " AND action=?", a + [action]
        rows = c.execute(q + " ORDER BY id", a).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["before"] = None if d["before"] is None else json.loads(d["before"])
        d["after"] = None if d["after"] is None else json.loads(d["after"])
        out.append(d)
    return out


def ref_ok(ref) -> bool:
    """A secret reference (`env:NAME`, `secret://x`, `vault://x`...), never a raw value."""
    import re
    return isinstance(ref, str) and bool(re.fullmatch(r"(env:[A-Za-z_][A-Za-z0-9_]*|[a-z][a-z0-9+.-]*://[^\s]+)", ref))
