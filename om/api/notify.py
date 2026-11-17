"""Notifications: persistence, in-process pub/sub, org SSE stream (`GET /api/v1/events`)."""
from __future__ import annotations

import itertools
import queue
import threading

from . import db
from .http import ApiError, Route, SSE

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, user_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, read_at TEXT);
CREATE INDEX IF NOT EXISTS idx_ntf_org ON notifications(org_id, created_at);
"""

# ------------------------------------------------------------------ pub/sub (per process)
_lock = threading.Lock()
_subs: dict[str, set] = {}
_ids = itertools.count(1)


class Subscription:
    def __init__(self, org_id: str):
        self.org_id = org_id
        self.q: queue.Queue = queue.Queue(maxsize=1000)
        self.closed = False

    def get(self, timeout: float = 1.0):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self.closed = True
        with _lock:
            s = _subs.get(self.org_id)
            if s is not None:
                s.discard(self)
                if not s:
                    _subs.pop(self.org_id, None)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def subscribe(org_id: str) -> Subscription:
    sub = Subscription(org_id)
    with _lock:
        _subs.setdefault(org_id, set()).add(sub)
    return sub


def publish(org_id: str, event: str, data: dict) -> int:
    """Deliver (event, data) to every subscriber of the org. Returns the number of subscribers reached."""
    item = (next(_ids), event, data)
    with _lock:
        targets = list(_subs.get(org_id, ()))
    n = 0
    for s in targets:
        try:
            s.q.put_nowait(item)
            n += 1
        except queue.Full:
            pass
    return n


def subscriber_count(org_id: str) -> int:
    with _lock:
        return len(_subs.get(org_id, ()))


# ------------------------------------------------------------------ persistence
def _row(r) -> dict:
    d = dict(r)
    d["read"] = d.get("read_at") is not None
    return d


def notify(conn, org_id, user_id, kind, title, body="", link="") -> dict:
    """Persist a notification (user_id None = whole org) and publish it on the org stream."""
    nid = db.new_id("ntf")
    ts = db.now()
    conn.execute("INSERT INTO notifications(id,org_id,user_id,kind,title,body,link,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (nid, org_id, user_id, kind, title, body or "", link or "", ts))
    item = {"id": nid, "org_id": org_id, "user_id": user_id, "kind": kind, "title": title, "body": body or "",
            "link": link or "", "created_at": ts, "read_at": None, "read": False}
    publish(org_id, "notification", item)
    return item


# ------------------------------------------------------------------ routes
def _limit(ctx, default=50):
    try:
        return max(1, min(200, int(ctx.query.get("limit", default))))
    except ValueError:
        raise ApiError(400, "bad_request", "limit must be a number.", "Use ?limit=50 (max 200).") from None


def list_notifications(ctx):
    lim = _limit(ctx)
    sql = "SELECT * FROM notifications WHERE org_id=? AND (user_id IS NULL OR user_id=?)"
    args: list = [ctx.org_id, ctx.user["id"]]
    if ctx.query.get("unread") in ("1", "true"):
        sql += " AND read_at IS NULL"
    cur = ctx.query.get("cursor")
    if cur:
        row = ctx.conn.execute("SELECT created_at FROM notifications WHERE id=? AND org_id=?", (cur, ctx.org_id)).fetchone()
        if row:
            sql += " AND (created_at < ? OR (created_at = ? AND id < ?))"
            args += [row[0], row[0], cur]
    rows = ctx.conn.execute(sql + " ORDER BY created_at DESC, id DESC LIMIT ?", args + [lim + 1]).fetchall()
    more = len(rows) > lim
    items = [_row(r) for r in rows[:lim]]
    unread = ctx.conn.execute("SELECT COUNT(*) FROM notifications WHERE org_id=? AND (user_id IS NULL OR user_id=?) "
                              "AND read_at IS NULL", (ctx.org_id, ctx.user["id"])).fetchone()[0]
    return {"items": items, "next_cursor": items[-1]["id"] if more and items else None, "unread_count": unread}


def mark_read(ctx):
    r = ctx.conn.execute("SELECT id FROM notifications WHERE id=? AND org_id=? AND (user_id IS NULL OR user_id=?)",
                         (ctx.params["id"], ctx.org_id, ctx.user["id"])).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such notification.")
    ctx.conn.execute("UPDATE notifications SET read_at=COALESCE(read_at, ?) WHERE id=? AND org_id=?",
                     (db.now(), r["id"], ctx.org_id))
    return {"ok": True}


def read_all(ctx):
    cur = ctx.conn.execute("UPDATE notifications SET read_at=? WHERE org_id=? AND read_at IS NULL "
                           "AND (user_id IS NULL OR user_id=?)", (db.now(), ctx.org_id, ctx.user["id"]))
    return {"ok": True, "updated": cur.rowcount}


def events(ctx):
    org_id, uid = ctx.org_id, ctx.user["id"]

    def gen():
        sub = subscribe(org_id)
        try:
            yield ("ready", {"org_id": org_id})
            while not sub.closed:
                item = sub.get(timeout=1.0)
                if item is None:
                    yield None  # tick: lets the server notice a closed client
                    continue
                eid, event, data = item
                if isinstance(data, dict) and data.get("user_id") not in (None, uid):
                    continue
                yield (eid, event, data)
        finally:
            sub.close()
    return SSE(gen(), last_event_id=ctx.headers.get("Last-Event-ID"))


ROUTES = [
    Route("GET", "/api/v1/notifications", list_notifications, role="viewer"),
    Route("POST", "/api/v1/notifications/read-all", read_all, role="viewer"),
    Route("POST", "/api/v1/notifications/{id}/read", mark_read, role="viewer"),
    Route("GET", "/api/v1/events", events, role="viewer"),
]
