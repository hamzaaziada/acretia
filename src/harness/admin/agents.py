"""Item 58: admins toggle agents per org. Default is enabled."""
from __future__ import annotations

import time

from . import AdminError, audit, conn, need_org, require_admin


def _agent(agent_id) -> str:
    if not isinstance(agent_id, str) or not agent_id.strip() or len(agent_id) > 128:
        raise AdminError("agent_id must be a non-empty string up to 128 chars")
    return agent_id


def set_enabled(org_id: str, agent_id: str, enabled: bool, actor, *, db=None) -> dict:
    need_org(org_id), _agent(agent_id)
    uid, _ = require_admin(actor)
    with conn(db) as c:
        before = is_enabled(org_id, agent_id, db=c)
        c.execute("INSERT INTO admin_agents(org_id,agent_id,enabled,updated_by,updated_at) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(org_id,agent_id) DO UPDATE SET enabled=excluded.enabled, updated_by=excluded.updated_by, "
                  "updated_at=excluded.updated_at", (org_id, agent_id, int(bool(enabled)), uid, time.time()))
        audit(c, org_id, actor, "agent.set_enabled", agent_id, {"enabled": before}, {"enabled": bool(enabled)})
    return {"org_id": org_id, "agent_id": agent_id, "enabled": bool(enabled)}


def is_enabled(org_id: str, agent_id: str, *, db=None) -> bool:
    need_org(org_id), _agent(agent_id)
    with conn(db) as c:
        r = c.execute("SELECT enabled FROM admin_agents WHERE org_id=? AND agent_id=?", (org_id, agent_id)).fetchone()
    return True if r is None else bool(r["enabled"])


def list_agents(org_id: str, known: list[str] | None = None, *, db=None) -> list[dict]:
    """Agents with an explicit setting, plus any in `known` (the catalog) at their default of enabled."""
    need_org(org_id)
    with conn(db) as c:
        rows = c.execute("SELECT agent_id, enabled, updated_by, updated_at FROM admin_agents WHERE org_id=? ORDER BY agent_id",
                         (org_id,)).fetchall()
    out = {r["agent_id"]: {"agent_id": r["agent_id"], "enabled": bool(r["enabled"]), "updated_by": r["updated_by"],
                           "updated_at": r["updated_at"]} for r in rows}
    for a in known or ():
        out.setdefault(a, {"agent_id": a, "enabled": True, "updated_by": None, "updated_at": None})
    return [out[k] for k in sorted(out)]


def filter_enabled(org_id: str, agents, key: str = "id", *, db=None) -> list:
    """For the research catalog search: drop disabled agents. Items are ids (str) or dicts carrying `key`."""
    with conn(db) as c:
        return [a for a in agents if is_enabled(org_id, a if isinstance(a, str) else a[key], db=c)]
