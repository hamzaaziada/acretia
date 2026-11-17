"""Deliverable library: versions, diff, undo, restore, download; org-wide library listing (SPEC §4, parity item 52)."""
from __future__ import annotations

import re
import urllib.parse

from om.deals import DealError

from . import security
from .deals import P, _limit, _offset, require_deal
from .http import ApiError, Response, Route

SCHEMA = ""  # tables live in om.deals (deals, deal_memory_versions, deal_deliverables)

KIND_MIME = {"xlsx": security.MIME["xlsx"], "pptx": security.MIME["pptx"], "docx": security.MIME["docx"],
             "json": "application/json", "other": "application/octet-stream"}


def _store(ctx):
    from om.deals import DealStore
    return DealStore(ctx.conn, ctx.blobs, ctx.org_id)


def _history(ctx, deal_id, name) -> list:
    require_deal(ctx.conn, ctx.org_id, deal_id)
    h = _store(ctx).history(deal_id, name)
    if not h:
        raise ApiError(404, "not_found", "No such deliverable.")
    return h


def _int(v, what) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", f"{what} must be a version number.", "Use whole numbers such as 1 or 2.") from None


def list_deliverables(ctx):
    deal_id = ctx.params["deal_id"]
    require_deal(ctx.conn, ctx.org_id, deal_id)
    store, items = _store(ctx), []
    for name in store.deliverables(deal_id):
        h = store.history(deal_id, name)
        last = h[-1]
        items.append({"name": name, "kind": last["kind"], "latest_version": last["version"], "versions": len(h),
                      "size": last["size"], "sha256": last["sha256"], "note": last["note"], "updated_at": last["created_at"]})
    items.sort(key=lambda i: i["updated_at"], reverse=True)
    return {"items": items, "next_cursor": None}


def versions(ctx):
    h = _history(ctx, ctx.params["deal_id"], ctx.params["name"])
    return {"name": ctx.params["name"], "items": list(reversed(h)), "next_cursor": None}


def download(ctx):
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    h = _history(ctx, deal_id, name)
    v = _int(ctx.params["v"], "Version")
    meta = next((x for x in h if x["version"] == v), None)
    if meta is None:
        raise ApiError(404, "not_found", "No such version.")
    data = _store(ctx).get_version(deal_id, name, v)
    fname = re.sub(r"[^\w.\- ]", "_", name).strip() or "deliverable"
    if "." not in fname:
        fname += "." + (meta["kind"] if meta["kind"] != "other" else "bin")
    disp = f"attachment; filename=\"{fname.encode('ascii', 'replace').decode().replace('?', '_')}\"; filename*=UTF-8''{urllib.parse.quote(fname)}"
    return Response(200, data, KIND_MIME.get(meta["kind"], "application/octet-stream"),
                    {"Content-Disposition": disp, "X-Deliverable-Version": str(v), "X-Content-Sha256": meta["sha256"]})


def diff(ctx):
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    h = _history(ctx, deal_id, name)
    a, b = _int(ctx.query.get("a"), "a"), _int(ctx.query.get("b"), "b")
    have = {x["version"] for x in h}
    if a not in have or b not in have:
        raise ApiError(404, "not_found", "No such version.")
    try:
        return _store(ctx).diff(deal_id, name, a, b)
    except DealError as e:
        raise ApiError(422, "diff_failed", str(e)[:200], "Download both versions to compare them by hand.") from None


def undo(ctx):
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    h = _history(ctx, deal_id, name)
    if len(h) < 2:
        raise ApiError(409, "nothing_to_undo", "There is no earlier version to go back to.", "Make another edit first.")
    new = _store(ctx).undo(deal_id, name)
    ctx.audit("deliverable.undo", f"deal:{deal_id}/deliverable:{name}", {"version": new["version"]})
    return 201, new


def restore(ctx):
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    h = _history(ctx, deal_id, name)
    if not isinstance(ctx.json, dict) or "version" not in ctx.json:
        raise ApiError(400, "bad_request", "`version` is required.", 'Send {"version": 1}.')
    v = _int(ctx.json["version"], "version")
    if v not in {x["version"] for x in h}:
        raise ApiError(404, "not_found", "No such version.")
    new = _store(ctx).restore(deal_id, name, v)
    ctx.audit("deliverable.restore", f"deal:{deal_id}/deliverable:{name}", {"from": v, "version": new["version"]})
    return 201, new


def org_library(ctx):
    """Every artifact across the org's deals: latest version per deliverable; filter by kind/deal, search by name."""
    lim, off = _limit(ctx), _offset(ctx)
    sql = ("SELECT x.deal_id, d.name AS deal_name, x.name, x.kind, x.version AS latest_version, x.size, x.sha256, x.note, "
           "x.created_at AS updated_at, (SELECT COUNT(*) FROM deal_deliverables y WHERE y.org_id=x.org_id AND y.deal_id=x.deal_id "
           "AND y.name=x.name) AS versions FROM deal_deliverables x JOIN deals d ON d.org_id=x.org_id AND d.deal_id=x.deal_id "
           "WHERE x.org_id=? AND x.version=(SELECT MAX(version) FROM deal_deliverables z WHERE z.org_id=x.org_id "
           "AND z.deal_id=x.deal_id AND z.name=x.name)")
    args = [ctx.org_id]
    if ctx.query.get("kind"):
        sql += " AND x.kind=?"
        args.append(ctx.query["kind"])
    if ctx.query.get("deal_id"):
        sql += " AND x.deal_id=?"
        args.append(ctx.query["deal_id"])
    if ctx.query.get("q"):
        sql += " AND x.name LIKE ? ESCAPE '\\'"
        args.append("%" + re.sub(r"([%_\\])", r"\\\1", ctx.query["q"]) + "%")
    rows = ctx.conn.execute(sql + " ORDER BY x.created_at DESC, x.deal_id, x.name LIMIT ? OFFSET ?", args + [lim + 1, off]).fetchall()
    kinds = [r[0] for r in ctx.conn.execute("SELECT DISTINCT kind FROM deal_deliverables WHERE org_id=? ORDER BY kind", (ctx.org_id,))]
    return {"items": [dict(r) for r in rows[:lim]], "next_cursor": str(off + lim) if len(rows) > lim else None, "kinds": kinds}


D = P + "/deals/{deal_id}/deliverables"
ROUTES = [
    Route("GET", P + "/library", org_library, role="viewer"),
    Route("GET", D, list_deliverables, role="viewer"),
    Route("GET", D + "/{name}/versions", versions, role="viewer"),
    Route("GET", D + "/{name}/versions/{v}/download", download, role="viewer"),
    Route("GET", D + "/{name}/diff", diff, role="viewer"),
    Route("POST", D + "/{name}/undo", undo, role="member"),
    Route("POST", D + "/{name}/restore", restore, role="member"),
]
