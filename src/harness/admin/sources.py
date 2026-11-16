"""Item 60: sources dashboard data. Secrets are stored by reference only."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from ..connectors import base as connectors
from . import AdminError, audit, conn, need_org, ref_ok, require_admin

STALE_SECONDS = 24 * 3600
STATUSES = ("ok", "error", "partial", "running")


def register_source(org_id: str, connector_name: str, config_ref: str, actor, *, db=None) -> str:
    need_org(org_id)
    uid, _ = require_admin(actor)
    if connector_name not in connectors.available():
        raise AdminError(f"unknown connector {connector_name!r}; available: {', '.join(connectors.available())}")
    if not ref_ok(config_ref):
        raise AdminError("config_ref must be a secret reference (env:NAME or scheme://path), never the secret value")
    sid = uuid.uuid4().hex
    with conn(db) as c:
        c.execute("INSERT INTO admin_sources(id,org_id,connector,config_ref,created_by,created_at) VALUES (?,?,?,?,?,?)",
                  (sid, org_id, connector_name, config_ref, uid, time.time()))
        audit(c, org_id, actor, "source.register", sid, None, {"connector": connector_name, "config_ref": config_ref})
    return sid


def _ts(at) -> float:
    if at is None:
        return time.time()
    if isinstance(at, datetime):
        return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()
    if isinstance(at, str):
        d = datetime.fromisoformat(at.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    return float(at)


def record_sync(org_id: str, source_id: str, status: str, items: int, errors: int, at=None, *, db=None) -> None:
    need_org(org_id)
    if status not in STATUSES:
        raise AdminError(f"status must be one of {STATUSES}")
    for n in (items, errors):
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise AdminError("items and errors must be non-negative integers")
    with conn(db) as c:
        if c.execute("SELECT 1 FROM admin_sources WHERE id=? AND org_id=?", (source_id, org_id)).fetchone() is None:
            raise AdminError(f"unknown source {source_id!r} for this org")
        c.execute("INSERT INTO admin_source_syncs(org_id,source_id,status,items,errors,at) VALUES (?,?,?,?,?,?)",
                  (org_id, source_id, status, items, errors, _ts(at)))


def dashboard(org_id: str, *, now=None, db=None) -> list[dict]:
    """One row per source: connector, status, last sync, last/total item and error counts, `stale` (>24h or never synced)."""
    need_org(org_id)
    now_ts = _ts(now)
    out = []
    with conn(db) as c:
        for s in c.execute("SELECT * FROM admin_sources WHERE org_id=? ORDER BY created_at, id", (org_id,)).fetchall():
            syncs = c.execute("SELECT * FROM admin_source_syncs WHERE org_id=? AND source_id=? ORDER BY at DESC, id DESC",
                              (org_id, s["id"])).fetchall()
            last = syncs[0] if syncs else None
            age = None if last is None else now_ts - last["at"]
            out.append({
                "source_id": s["id"], "connector": s["connector"], "config_ref": s["config_ref"],
                "status": last["status"] if last else "never_synced",
                "last_sync_at": None if last is None else datetime.fromtimestamp(last["at"], timezone.utc).isoformat(),
                "last_items": last["items"] if last else 0, "last_errors": last["errors"] if last else 0,
                "total_items": sum(r["items"] for r in syncs), "total_errors": sum(r["errors"] for r in syncs),
                "sync_count": len(syncs), "age_seconds": age,
                "stale": last is None or age > STALE_SECONDS,
            })
    return out
