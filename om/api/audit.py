"""Append-only, hash-chained audit log per org (SPEC §2.2(10))."""
from __future__ import annotations

import csv
import hashlib
import io
import json

from . import db
from .http import ApiError, Response, Route

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log(
  org_id TEXT NOT NULL, seq INTEGER NOT NULL, user_id TEXT, action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}', ip TEXT NOT NULL DEFAULT '', ua TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(org_id, seq));
"""
GENESIS = "0" * 64


def _canon(org_id, seq, user_id, action, target, detail_json, ip, ua, at) -> str:
    return json.dumps({"org_id": org_id, "seq": seq, "user_id": user_id, "action": action, "target": target,
                       "detail": detail_json, "ip": ip, "ua": ua, "at": at},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev: str, canon: str) -> str:
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def append(conn, org_id, user_id, action, target="", detail=None, ip="", ua="") -> int:
    """Append one row; returns its seq. Serialised with BEGIN IMMEDIATE (or the caller's open transaction)."""
    detail_json = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    ua = (ua or "")[:300]
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        last = conn.execute("SELECT seq, hash FROM audit_log WHERE org_id=? ORDER BY seq DESC LIMIT 1", (org_id,)).fetchone()
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        at = db.now()
        h = _hash(prev, _canon(org_id, seq, user_id, action, target, detail_json, ip, ua, at))
        conn.execute("INSERT INTO audit_log(org_id,seq,user_id,action,target,detail_json,ip,ua,at,prev_hash,hash) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (org_id, seq, user_id, action, target, detail_json, ip, ua, at, prev, h))
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    if own:
        conn.execute("COMMIT")
    return seq


def verify(conn, org_id) -> dict:
    """Re-walk the chain. `bad_seq` is the first row that does not verify (a deleted row shows up as the
    row after the gap)."""
    prev, expect, n = GENESIS, 1, 0
    for r in conn.execute("SELECT * FROM audit_log WHERE org_id=? ORDER BY seq", (org_id,)):
        n += 1
        if r["seq"] != expect or r["prev_hash"] != prev:
            return {"ok": False, "bad_seq": r["seq"], "count": n}
        want = _hash(prev, _canon(r["org_id"], r["seq"], r["user_id"], r["action"], r["target"], r["detail_json"],
                                  r["ip"], r["ua"], r["at"]))
        if want != r["hash"]:
            return {"ok": False, "bad_seq": r["seq"], "count": n}
        prev, expect = r["hash"], expect + 1
    return {"ok": True, "bad_seq": None, "count": n}


def _item(r) -> dict:
    d = dict(r)
    try:
        d["detail"] = json.loads(d.pop("detail_json") or "{}")
    except ValueError:
        d["detail"] = {}
    return d


def list_audit(ctx):
    try:
        lim = max(1, min(200, int(ctx.query.get("limit", 50))))
        before = int(ctx.query["before"]) if ctx.query.get("before") else None
    except ValueError:
        raise ApiError(400, "bad_request", "limit and before must be numbers.", "Use ?limit=50&before=<seq>.") from None
    sql, args = "SELECT * FROM audit_log WHERE org_id=?", [ctx.org_id]
    if before is not None:
        sql += " AND seq < ?"
        args.append(before)
    rows = ctx.conn.execute(sql + " ORDER BY seq DESC LIMIT ?", args + [lim + 1]).fetchall()
    items = [_item(r) for r in rows[:lim]]
    return {"items": items, "next_cursor": str(items[-1]["seq"]) if len(rows) > lim and items else None}


def verify_route(ctx):
    return verify(ctx.conn, ctx.org_id)


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(ctx):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["seq", "at", "user_id", "action", "target", "detail", "ip", "ua", "prev_hash", "hash"])
    for r in ctx.conn.execute("SELECT * FROM audit_log WHERE org_id=? ORDER BY seq", (ctx.org_id,)):
        w.writerow([r["seq"], r["at"], _csv_safe(r["user_id"]), _csv_safe(r["action"]), _csv_safe(r["target"]),
                    _csv_safe(r["detail_json"]), _csv_safe(r["ip"]), _csv_safe(r["ua"]), r["prev_hash"], r["hash"]])
    return Response(200, out.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
                    {"Content-Disposition": 'attachment; filename="audit-log.csv"'})


ROUTES = [
    Route("GET", "/api/v1/audit", list_audit, role="owner"),
    Route("GET", "/api/v1/audit/verify", verify_route, role="owner"),
    Route("GET", "/api/v1/audit/export.csv", export_csv, role="owner"),
]
