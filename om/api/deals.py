"""Deals and documents: workspace header, uploads (multipart/raw/zip), indexing pool, page text (SPEC §3, §4)."""
from __future__ import annotations

import email
import email.policy
import io
import json
import re
import sqlite3
import sys
import threading
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, wait as _wait

from om.contracts import ContractError
from om.deals import DealError, _SCHEMA as _CORE_DEALS_SCHEMA

from . import db, notify, security
from .http import ApiError, Response, Route, parse_multipart, sanitize_filename

SCHEMA = _CORE_DEALS_SCHEMA + """
CREATE TABLE IF NOT EXISTS deal_meta(
  org_id TEXT NOT NULL, deal_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', sector TEXT NOT NULL DEFAULT '',
  target TEXT NOT NULL DEFAULT '', created_by TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(org_id, deal_id));
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, pages INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','indexing','indexed','failed')),
  progress REAL NOT NULL DEFAULT 0, lang TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
  folder TEXT NOT NULL DEFAULT '', hint TEXT NOT NULL DEFAULT '', uploaded_by TEXT);
CREATE INDEX IF NOT EXISTS idx_documents_deal ON documents(org_id, deal_id);
CREATE TABLE IF NOT EXISTS document_pages(
  org_id TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL DEFAULT '',
  lines_json TEXT NOT NULL DEFAULT '[]', tables_json TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(org_id, doc_id, page));
"""

DEAL_STATUSES = ("active", "on_hold", "closed")
MAX_UPLOAD = 200 * 1024 * 1024
P = "/api/v1"


# =========================================================================== helpers
def _limit(ctx, default=50) -> int:
    try:
        return max(1, min(200, int(ctx.query.get("limit", default))))
    except ValueError:
        raise ApiError(400, "bad_request", "limit must be a number.", "Use ?limit=50 (max 200).") from None


def _offset(ctx) -> int:
    try:
        return max(0, int(ctx.query.get("cursor") or 0))
    except ValueError:
        raise ApiError(400, "bad_request", "cursor is not valid.", "Use the next_cursor value from the previous page.") from None


def _body(ctx) -> dict:
    if ctx.json is None:
        return {}
    if not isinstance(ctx.json, dict):
        raise ApiError(400, "bad_request", "A JSON object body is required.", "Send a JSON object.")
    return ctx.json


def _str(b, key, maxlen=200, required=False) -> str | None:
    if key not in b:
        if required:
            raise ApiError(400, "bad_request", f"`{key}` is required.", f"Include a non-empty `{key}`.")
        return None
    v = b[key]
    if not isinstance(v, str) or (required and not v.strip()):
        raise ApiError(400, "bad_request", f"`{key}` must be a {'non-empty ' if required else ''}string.", f"Send `{key}` as text.")
    return v.strip()[:maxlen]


def require_deal(conn, org_id, deal_id) -> sqlite3.Row:
    r = conn.execute("SELECT * FROM deals WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such deal.")
    return r


def firm_definitions(conn, org_id) -> dict:
    r = conn.execute("SELECT settings_json FROM orgs WHERE id=?", (org_id,)).fetchone()
    try:
        defs = (json.loads(r["settings_json"] or "{}") if r else {}).get("definitions") or {}
    except ValueError:
        defs = {}
    out = {}
    for k, v in (defs.items() if isinstance(defs, dict) else []):
        if isinstance(v, dict):
            v = v.get("text") or v.get("definition") or ""
        if isinstance(v, str) and str(k).strip():
            out[str(k)] = v
    return out


def _scalar(conn, sql, args, default=0):
    try:
        r = conn.execute(sql, args).fetchone()
        return r[0] if r else default
    except sqlite3.Error:
        return default


def _counts(conn, org_id, deal_id) -> dict:
    d = conn.execute("SELECT COUNT(*) n, SUM(status='indexed') ix, SUM(status='failed') fl FROM documents "
                     "WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    return {"documents": d["n"] or 0, "indexed": d["ix"] or 0, "failed": d["fl"] or 0,
            "deliverables": _scalar(conn, "SELECT COUNT(DISTINCT name) FROM deal_deliverables WHERE org_id=? AND deal_id=?", (org_id, deal_id)),
            "jobs": _scalar(conn, "SELECT COUNT(*) FROM jobs WHERE org_id=? AND deal_id=?", (org_id, deal_id))}


def _summary(conn, r) -> dict:
    return {"deal_id": r["deal_id"], "name": r["name"], "target": r["target"] or "", "sector": r["sector"] or "",
            "status": r["status"] or "active", "created_at": r["created_at"], "updated_at": r["updated_at"] or r["created_at"],
            "counts": _counts(conn, r["org_id"], r["deal_id"])}


_DEAL_SQL = ("SELECT d.org_id, d.deal_id, d.name, d.created_at, m.status, m.sector, m.target, m.updated_at "
             "FROM deals d LEFT JOIN deal_meta m ON m.org_id=d.org_id AND m.deal_id=d.deal_id WHERE d.org_id=?")


def _names(conn, ids) -> dict:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {r["id"]: r["name"] for r in conn.execute(f"SELECT id, name FROM users WHERE id IN ({q})", ids)}


def activity(conn, org_id, deal_id, limit=50) -> list:
    """Recent jobs, uploads, deliverable versions, comments and deal events for the Activity tab (parity item 57)."""
    items, actors = [], []
    try:
        for r in conn.execute("SELECT id, kind, status, prompt, user_id, COALESCE(finished_at, started_at, '') at FROM jobs "
                              "WHERE org_id=? AND deal_id=? ORDER BY rowid DESC LIMIT ?", (org_id, deal_id, limit)):
            items.append({"at": r["at"], "type": "job", "title": (r["prompt"] or r["kind"] or "Run")[:140],
                          "status": r["status"], "ref": r["id"], "actor_id": r["user_id"]})
    except sqlite3.Error:
        pass
    for r in conn.execute("SELECT id, name, status, created_at, uploaded_by FROM documents WHERE org_id=? AND deal_id=? "
                          "ORDER BY created_at DESC, id LIMIT ?", (org_id, deal_id, limit)):
        items.append({"at": r["created_at"], "type": "upload", "title": r["name"], "status": r["status"], "ref": r["id"],
                      "actor_id": r["uploaded_by"]})
    for r in conn.execute("SELECT name, version, kind, note, created_at FROM deal_deliverables WHERE org_id=? AND deal_id=? "
                          "ORDER BY created_at DESC, version DESC LIMIT ?", (org_id, deal_id, limit)):
        items.append({"at": r["created_at"], "type": "deliverable", "title": f"{r['name']} v{r['version']}",
                      "status": r["note"] or "", "ref": r["name"], "actor_id": None})
    try:
        for r in conn.execute("SELECT id, body, author_id, created_at FROM comments WHERE org_id=? AND deal_id=? "
                              "ORDER BY created_at DESC LIMIT ?", (org_id, deal_id, limit)):
            items.append({"at": r["created_at"], "type": "comment", "title": (r["body"] or "")[:140], "status": "",
                          "ref": r["id"], "actor_id": r["author_id"]})
    except sqlite3.Error:
        pass
    for r in conn.execute("SELECT action, target, user_id, at, seq FROM audit_log WHERE org_id=? AND target LIKE ? "
                          "AND (action LIKE 'deal.%' OR action LIKE 'comment.%') ORDER BY seq DESC LIMIT ?",
                          (org_id, f"deal:{deal_id}%", limit)):
        items.append({"at": r["at"], "type": "comment" if r["action"].startswith("comment.") else "event",
                      "title": r["action"], "status": "", "ref": str(r["seq"]), "actor_id": r["user_id"]})
    items.sort(key=lambda i: (i["at"] or "", i["ref"] or ""), reverse=True)
    items = items[:limit]
    names = _names(conn, [i["actor_id"] for i in items])
    for i in items:
        i["actor"] = names.get(i.pop("actor_id"), "")
    return items


def deal_detail(conn, store, org_id, deal_id) -> dict:
    row = conn.execute(_DEAL_SQL + " AND d.deal_id=?", (org_id, deal_id)).fetchone()
    mem = store.get(deal_id)
    out = _summary(conn, row)
    out["definitions"], out["formatting"] = mem.definitions, mem.formatting
    out["memory_version"] = mem.versions[-1].version if mem.versions else 0
    dl = []
    for name in store.deliverables(deal_id):
        h = store.history(deal_id, name)
        dl.append({"name": name, "kind": h[-1]["kind"], "latest_version": h[-1]["version"], "size": h[-1]["size"],
                   "updated_at": h[-1]["created_at"]})
    out["deliverables"] = dl
    out["activity"] = activity(conn, org_id, deal_id)
    return out


# =========================================================================== deal routes
def list_deals(ctx):
    lim, off = _limit(ctx), _offset(ctx)
    sql, args = _DEAL_SQL, [ctx.org_id]
    if ctx.query.get("status"):
        sql += " AND COALESCE(m.status,'active')=?"
        args.append(ctx.query["status"])
    if ctx.query.get("q"):
        sql += " AND d.name LIKE ? ESCAPE '\\'"
        args.append("%" + re.sub(r"([%_\\])", r"\\\1", ctx.query["q"]) + "%")
    rows = ctx.conn.execute(sql + " ORDER BY COALESCE(m.updated_at, d.created_at) DESC, d.deal_id LIMIT ? OFFSET ?",
                            args + [lim + 1, off]).fetchall()
    items = [_summary(ctx.conn, r) for r in rows[:lim]]
    return {"items": items, "next_cursor": str(off + lim) if len(rows) > lim else None}


def create_deal_record(conn, store, org_id, user_id, name, target="", sector="", status="active", definitions=None) -> str:
    defs = firm_definitions(conn, org_id)
    defs.update(definitions or {})
    mem = store.create_deal(name, defs)
    conn.execute("INSERT INTO deal_meta(org_id,deal_id,status,sector,target,created_by,updated_at) VALUES(?,?,?,?,?,?,?)",
                 (org_id, mem.deal_id, status, sector, target, user_id, db.now()))
    return mem.deal_id


def create_deal(ctx):
    b = _body(ctx)
    name = _str(b, "name", 160, required=True)
    status = _str(b, "status") or "active"
    if status not in DEAL_STATUSES:
        raise ApiError(400, "bad_request", "Unknown deal status.", f"Use one of: {', '.join(DEAL_STATUSES)}.")
    defs = b.get("definitions") or {}
    if not isinstance(defs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in defs.items()):
        raise ApiError(400, "bad_request", "`definitions` must map names to text.", 'Send {"Adjusted EBITDA": "..."}.')
    store = _store(ctx)
    try:
        deal_id = create_deal_record(ctx.conn, store, ctx.org_id, ctx.user["id"], name, _str(b, "target") or "",
                                     _str(b, "sector") or "", status, defs)
    except (ContractError, DealError) as e:
        raise ApiError(400, "bad_request", str(e)[:200], "Check the deal name and definitions.") from None
    ctx.audit("deal.create", f"deal:{deal_id}", {"name": name})
    return 201, deal_detail(ctx.conn, store, ctx.org_id, deal_id)


def _store(ctx):
    from om.deals import DealStore
    return DealStore(ctx.conn, ctx.blobs, ctx.org_id)


def get_deal(ctx):
    require_deal(ctx.conn, ctx.org_id, ctx.params["deal_id"])
    return deal_detail(ctx.conn, _store(ctx), ctx.org_id, ctx.params["deal_id"])


def patch_deal(ctx):
    deal_id = ctx.params["deal_id"]
    require_deal(ctx.conn, ctx.org_id, deal_id)
    b = _body(ctx)
    store = _store(ctx)
    name, target, sector, status = _str(b, "name", 160), _str(b, "target"), _str(b, "sector"), _str(b, "status")
    if name is not None and not name:
        raise ApiError(400, "bad_request", "`name` cannot be empty.", "Send a deal name.")
    if status is not None and status not in DEAL_STATUSES:
        raise ApiError(400, "bad_request", "Unknown deal status.", f"Use one of: {', '.join(DEAL_STATUSES)}.")
    defs, fmt = b.get("definitions"), b.get("formatting")
    if defs is not None and (not isinstance(defs, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in defs.items())):
        raise ApiError(400, "bad_request", "`definitions` must map names to text.", 'Send {"Net Debt": "..."}.')
    if fmt is not None and not isinstance(fmt, dict):
        raise ApiError(400, "bad_request", "`formatting` must be an object.", "Send preference key/values.")
    try:
        for k, v in (defs or {}).items():
            store.set_definition(deal_id, k, v)
        if fmt:
            store.set_formatting(deal_id, **fmt)
    except (DealError, ValueError) as e:
        raise ApiError(400, "bad_request", str(e)[:200], "Check the values and try again.") from None
    if name is not None:
        ctx.conn.execute("UPDATE deals SET name=? WHERE org_id=? AND deal_id=?", (name, ctx.org_id, deal_id))
    ctx.conn.execute("INSERT INTO deal_meta(org_id,deal_id,status,sector,target,updated_at) VALUES(?,?,?,?,?,?) "
                     "ON CONFLICT(org_id,deal_id) DO UPDATE SET status=COALESCE(?,status), sector=COALESCE(?,sector), "
                     "target=COALESCE(?,target), updated_at=?",
                     (ctx.org_id, deal_id, status or "active", sector or "", target or "", db.now(),
                      status, sector, target, db.now()))
    ctx.audit("deal.update", f"deal:{deal_id}", {k: b[k] for k in ("name", "target", "sector", "status") if k in b}
              | ({"definitions": sorted(defs)} if defs else {}))
    return deal_detail(ctx.conn, store, ctx.org_id, deal_id)


# =========================================================================== documents
def _doc_dict(r) -> dict:
    return {"id": r["id"], "deal_id": r["deal_id"], "name": r["name"], "kind": r["kind"], "size": r["size"],
            "pages": r["pages"], "status": r["status"], "progress": round(float(r["progress"]), 3), "lang": r["lang"],
            "folder": r["folder"], "created_at": r["created_at"], "error": r["error"] or None, "hint": r["hint"] or None,
            "sha256": r["sha256"], "uploaded_by": r["uploaded_by"], "file_url": f"{P}/documents/{r['id']}/file"}


def get_document(conn, org_id, doc_id):
    r = conn.execute("SELECT * FROM documents WHERE id=? AND org_id=?", (doc_id, org_id)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such document.")
    return r


def overall(conn, org_id, deal_id) -> dict:
    r = conn.execute("SELECT COUNT(*) AS total, SUM(status='indexed') AS n_indexed, SUM(status='indexing') AS n_indexing, "
                     "SUM(status='queued') AS n_queued, SUM(status='failed') AS n_failed, AVG(progress) AS progress FROM documents "
                     "WHERE org_id=? AND deal_id=?", (org_id, deal_id)).fetchone()
    return {"total": r["total"] or 0, "indexed": r["n_indexed"] or 0, "indexing": r["n_indexing"] or 0,
            "queued": r["n_queued"] or 0, "failed": r["n_failed"] or 0,
            "progress": round(r["progress"] if r["progress"] is not None else 1.0, 3)}


def list_documents(ctx):
    deal_id = ctx.params["deal_id"]
    require_deal(ctx.conn, ctx.org_id, deal_id)
    lim, off = _limit(ctx, 200), _offset(ctx)
    sql, args = "SELECT * FROM documents WHERE org_id=? AND deal_id=?", [ctx.org_id, deal_id]
    for key, col in (("status", "status"), ("kind", "kind")):
        if ctx.query.get(key):
            sql += f" AND {col}=?"
            args.append(ctx.query[key])
    if ctx.query.get("folder") is not None and ctx.query.get("folder") != "":
        f = ctx.query["folder"].strip("/")
        sql += " AND (folder=? OR folder LIKE ? ESCAPE '\\')"
        args += [f, re.sub(r"([%_\\])", r"\\\1", f) + "/%"]
    if ctx.query.get("q"):
        sql += " AND name LIKE ? ESCAPE '\\'"
        args.append("%" + re.sub(r"([%_\\])", r"\\\1", ctx.query["q"]) + "%")
    rows = ctx.conn.execute(sql + " ORDER BY folder, name, id LIMIT ? OFFSET ?", args + [lim + 1, off]).fetchall()
    folders = [{"path": r["folder"], "count": r["n"]} for r in ctx.conn.execute(
        "SELECT folder, COUNT(*) n FROM documents WHERE org_id=? AND deal_id=? GROUP BY folder ORDER BY folder",
        (ctx.org_id, deal_id))]
    return {"items": [_doc_dict(r) for r in rows[:lim]], "next_cursor": str(off + lim) if len(rows) > lim else None,
            "summary": overall(ctx.conn, ctx.org_id, deal_id), "folders": folders}


def get_document_route(ctx):
    r = get_document(ctx.conn, ctx.org_id, ctx.params["doc_id"])
    d = _doc_dict(r)
    d["deal_name"] = ctx.conn.execute("SELECT name FROM deals WHERE org_id=? AND deal_id=?", (ctx.org_id, r["deal_id"])).fetchone()[0]
    return d


def document_file(ctx):
    r = get_document(ctx.conn, ctx.org_id, ctx.params["doc_id"])
    try:
        data = ctx.blobs.get(r["sha256"])
    except KeyError:
        raise ApiError(404, "not_found", "The stored file is missing.") from None
    inline = r["kind"] in ("pdf", "png", "jpg")
    ascii_name = r["name"].encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    disp = f"{'inline' if inline else 'attachment'}; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(r['name'])}"
    return Response(200, data, security.MIME.get(r["kind"], "application/octet-stream"),
                    {"Content-Disposition": disp, "Cache-Control": "private, max-age=3600"})


def page_text(ctx):
    r = get_document(ctx.conn, ctx.org_id, ctx.params["doc_id"])
    try:
        n = int(ctx.params["n"])
    except ValueError:
        raise ApiError(404, "not_found", "No such page.") from None
    if r["status"] != "indexed":
        if r["status"] == "failed":
            raise ApiError(409, "not_indexed", "This document could not be indexed.", r["hint"] or "Upload it again.")
        raise ApiError(409, "not_indexed", "This document is still being indexed.",
                       f"Indexing is {int(r['progress'] * 100)}% done; try again in a moment.")
    p = ctx.conn.execute("SELECT * FROM document_pages WHERE org_id=? AND doc_id=? AND page=?", (ctx.org_id, r["id"], n)).fetchone()
    if p is None:
        raise ApiError(404, "not_found", "No such page.")
    return {"doc_id": r["id"], "doc_name": r["name"], "page": n, "pages": r["pages"], "lang": r["lang"], "text": p["text"],
            "lines": json.loads(p["lines_json"]), "tables": json.loads(p["tables_json"])}


def delete_document(ctx):
    r = get_document(ctx.conn, ctx.org_id, ctx.params["doc_id"])
    ctx.conn.execute("DELETE FROM document_pages WHERE org_id=? AND doc_id=?", (ctx.org_id, r["id"]))
    ctx.conn.execute("DELETE FROM documents WHERE org_id=? AND id=?", (ctx.org_id, r["id"]))
    ctx.audit("document.delete", f"deal:{r['deal_id']}/doc:{r['id']}", {"name": r["name"]})
    return {"ok": True}


# --------------------------------------------------------------------------- upload
def _clean_folder(*parts) -> str:
    comps = []
    for part in parts:
        for c in re.split(r"[\\/]+", str(part or "")):
            c = c.strip()
            if c in ("", ".", ".."):
                continue
            comps.append(sanitize_filename(c)[:80])
    return "/".join(comps[:8])


def _extract_files(ctx) -> tuple[list, str]:
    """-> ([(filename, bytes)], folder) from multipart or a raw body with X-Filename."""
    ct = ctx.headers.get("Content-Type") or ""
    if ct.lower().startswith("multipart/form-data"):
        parts = parse_multipart(ctx.body, ct, MAX_UPLOAD)
        folder = next((d.decode("utf-8", "replace") for n, fn, _t, d in parts if fn is None and n in ("folder", "path")), "")
        files = [(fn, d) for n, fn, _t, d in parts if fn is not None]
        if not files:
            raise ApiError(400, "no_file", "The upload contains no file.", "Attach at least one file.")
        return files, folder
    raw = ctx.headers.get("X-Filename")
    if not raw:
        raise ApiError(400, "no_file", "No file name was given.",
                       "Send multipart/form-data, or a raw body with an X-Filename header.")
    if not ctx.body:
        raise ApiError(400, "no_file", "The upload is empty.", "Attach a non-empty file.")
    return [(urllib.parse.unquote(raw), ctx.body)], ctx.headers.get("X-Folder") or ""


def upload_documents(ctx):
    deal_id = ctx.params["deal_id"]
    require_deal(ctx.conn, ctx.org_id, deal_id)
    files, base_folder = _extract_files(ctx)
    accepted, skipped = [], []

    def consider(name, data, folder):
        rawname = str(name)
        name = sanitize_filename(name)
        if rawname in (".DS_Store", "Thumbs.db") or rawname.startswith("._") or "__MACOSX" in folder:
            return
        if not data:
            skipped.append({"name": name, "reason": "empty file"})
            return
        kind = security.sniff(data, name)
        if kind is None:
            skipped.append({"name": name, "reason": "unsupported file type"})
        elif kind == "zip":
            skipped.append({"name": name, "reason": "nested archive; upload it on its own"})
        else:
            accepted.append((name, kind, data, folder))

    for fname, data in files:
        fname = str(fname or "file")
        sub = ""
        if "/" in fname.replace("\\", "/"):
            sub = fname.replace("\\", "/").rsplit("/", 1)[0]
        name = sanitize_filename(fname)
        kind = security.sniff(data, name)
        if kind == "zip":
            try:
                for rel, blob in security.iter_zip(data):
                    d, _, base = rel.rpartition("/")
                    consider(base, blob, _clean_folder(base_folder, sub, d))
            except security.UnsafeArchive as e:
                raise ApiError(400, "unsafe_archive", f"The zip was refused: {e}.",
                               "Re-create the archive without absolute paths, '..', links or huge compression ratios.") from None
        else:
            consider(fname, data, _clean_folder(base_folder, sub))
    if not accepted:
        if skipped:
            raise ApiError(415, "unsupported_type", "None of the files could be accepted.",
                           "Upload PDF, Excel, PowerPoint, Word, CSV/TXT, email (.eml), PNG/JPEG, or a zip of those.")
        raise ApiError(400, "no_file", "The upload contains no files.", "Attach at least one file.")
    conn, ts, items = ctx.conn, db.now(), []
    with db.tx(conn):
        for name, kind, data, folder in accepted:
            key = ctx.blobs.put(data)
            doc_id = db.new_id("doc")
            conn.execute("INSERT INTO documents(id,org_id,deal_id,name,kind,sha256,size,created_at,folder,uploaded_by) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?)", (doc_id, ctx.org_id, deal_id, name, kind, key, len(data), ts, folder,
                                                          ctx.user["id"]))
            items.append(doc_id)
        conn.execute("UPDATE deal_meta SET updated_at=? WHERE org_id=? AND deal_id=?", (ts, ctx.org_id, deal_id))
    ctx.audit("document.upload", f"deal:{deal_id}", {"count": len(items), "names": [a[0] for a in accepted[:20]],
                                                      "skipped": len(skipped)})
    from . import state as state_mod
    st = state_mod.STATE
    for doc_id in items:
        _publish(ctx.conn, ctx.org_id, doc_id)
        enqueue_index(st, doc_id)
    rows = [get_document(conn, ctx.org_id, i) for i in items]
    return 201, {"items": [_doc_dict(r) for r in rows], "skipped": skipped, "count": len(rows),
                 "summary": overall(conn, ctx.org_id, deal_id)}


# =========================================================================== indexing
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()
_pending: set = set()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="acretia-index")
        return _pool


def enqueue_index(state, doc_id: str):
    fut = _get_pool().submit(_run_index, state, doc_id)
    with _pool_lock:
        _pending.add(fut)
    fut.add_done_callback(lambda f: _pending.discard(f))
    return fut


def wait_idle(timeout: float = 120.0) -> bool:
    """Block until every queued indexing task has finished (tests, demo seeding)."""
    with _pool_lock:
        futs = list(_pending)
    done, not_done = _wait(futs, timeout=timeout)
    return not not_done


def shutdown() -> None:
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def resume_indexing(state) -> int:
    """Re-queue documents left queued/indexing by a previous process."""
    conn = state.conn()
    ids = [r[0] for r in conn.execute("SELECT id FROM documents WHERE status IN ('queued','indexing') ORDER BY created_at, id")]
    for i in ids:
        conn.execute("UPDATE documents SET status='queued', progress=0 WHERE id=?", (i,))
        enqueue_index(state, i)
    return len(ids)


def _publish(conn, org_id, doc_id):
    r = conn.execute("SELECT * FROM documents WHERE id=? AND org_id=?", (doc_id, org_id)).fetchone()
    if r is None:
        return
    d = _doc_dict(r)
    d["overall"] = overall(conn, org_id, r["deal_id"])
    d["doc_id"] = r["id"]
    notify.publish(org_id, "document", d)


def _lang(text: str) -> str:
    ar = sum(1 for c in text if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ﭐ" <= c <= "﷿" or "ﹰ" <= c <= "﻿")
    la = sum(1 for c in text if c.isascii() and c.isalpha())
    return "ar" if ar and ar / (ar + la) > 0.3 else "en"


def _cells(line) -> list:
    cells, cur = [], []
    for w in line.words:
        if cur and w.bbox_norm[0] - cur[-1].bbox_norm[2] > 0.03:
            cells.append(" ".join(x.text for x in cur))
            cur = []
        cur.append(w)
    if cur:
        cells.append(" ".join(x.text for x in cur))
    return cells


def _pdf_pages(data: bytes):
    """-> list of (text, lines, tables). Prefers om.docparse (S5.1), falls back to om.pdfdoc."""
    from om import pdfdoc
    parsed = None
    try:
        from om import docparse
        parsed = docparse.parse(data)
    except pdfdoc.PdfError:
        raise
    except Exception:
        parsed = None
    out = []
    if parsed is not None:
        for p in parsed.pages:
            text = "\n".join(b.text for b in p.blocks if b.text).strip() or (p.raw_text or "").strip()
            lines = [{"text": l.text, "bbox_norm": [round(v, 5) for v in l.bbox_norm]} for l in p.lines]
            tables = []
            for b in p.blocks:
                if b.kind == "table":
                    x0, y0, x1, y1 = b.bbox_norm
                    rows = [_cells(l) for l in p.lines if l.bbox_norm[0] >= x0 - 1e-3 and l.bbox_norm[2] <= x1 + 1e-3
                            and l.bbox_norm[1] >= y0 - 1e-3 and l.bbox_norm[3] <= y1 + 1e-3]
                    tables.append({"bbox_norm": [round(v, 5) for v in b.bbox_norm], "text": b.text, "rows": rows})
            out.append((text, lines, tables))
        return out
    doc = pdfdoc.load(data)
    for p in doc.pages:
        lines = [{"text": l.text, "bbox_norm": [round(v, 5) for v in l.bbox_norm]} for l in p.lines]
        out.append(("\n".join(l.text for l in p.lines), lines, []))
    return out


def _chunks(text: str, n: int = 60):
    ls = text.splitlines()
    return ["\n".join(ls[i:i + n]) for i in range(0, max(len(ls), 1), n)] or [""]


def _xml_text(data: bytes, tag_suffix: str) -> list:
    out = []
    for el in ET.fromstring(data).iter():
        if el.tag.endswith(tag_suffix):
            out.append(el.text or "")
    return out


def _office_pages(kind: str, data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.file_size > 200 * 1024 * 1024:
                raise ValueError("a part of the file is unreasonably large")
        if kind == "docx":
            root = ET.fromstring(z.read("word/document.xml"))
            paras = ["".join(t.text or "" for t in p.iter() if t.tag.endswith("}t")) for p in root.iter() if p.tag.endswith("}p")]
            return [("\n".join(paras[i:i + 40]), [], []) for i in range(0, max(len(paras), 1), 40)] or [("", [], [])]
        if kind == "pptx":
            slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                            key=lambda n: int(re.findall(r"\d+", n)[0]))
            return [("\n".join(t for t in _xml_text(z.read(n), "}t") if t.strip()), [], []) for n in slides] or [("", [], [])]
    return [("", [], [])]


def _xlsx_pages(data: bytes):
    from om import xlsx
    book = xlsx.read(data)
    out = []
    for name in book.order:
        grid = book.sheets[name]
        rows: dict = {}
        for (r, c), cell in grid.items():
            if cell.value not in (None, ""):
                rows.setdefault(r, {})[c] = cell.value
        lines, table = [], []
        for r in sorted(rows)[:2000]:
            cols = rows[r]
            vals = [("" if cols.get(c) is None else (f"{cols[c]:g}" if isinstance(cols.get(c), float) else str(cols[c])))
                    for c in range(1, max(cols) + 1)]
            lines.append("\t".join(vals))
            if len(table) < 200:
                table.append(vals)
        out.append((f"{name}\n" + "\n".join(lines), [], [{"sheet": name, "rows": table}]))
    return out or [("", [], [])]


def _text_pages(kind: str, data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
    if kind == "eml":
        msg = email.message_from_bytes(data, policy=email.policy.default)
        head = "\n".join(f"{k}: {msg[k]}" for k in ("From", "To", "Cc", "Date", "Subject") if msg[k])
        body = msg.get_body(preferencelist=("plain", "html"))
        text = head + "\n\n" + (body.get_content() if body is not None else "")
    return [(c, [], []) for c in _chunks(text)]


def extract_pages(kind: str, data: bytes):
    if kind == "pdf":
        return _pdf_pages(data)
    if kind == "xlsx":
        return _xlsx_pages(data)
    if kind in ("docx", "pptx"):
        return _office_pages(kind, data)
    if kind in ("txt", "csv", "eml"):
        return _text_pages(kind, data)
    return [("", [], [])]  # images: stored, not text-indexed (no OCR here)


def _fail_hint(e: Exception) -> str:
    m = str(e).lower()
    if "encrypt" in m or "password" in m:
        return "Remove the password protection and upload the file again."
    if isinstance(e, (zipfile.BadZipFile, KeyError, ET.ParseError)):
        return "The file looks damaged. Re-export it from the source application and upload it again."
    return "Open the file locally to check it is not corrupt, then upload it again."


def _run_index(state, doc_id: str) -> None:
    conn = state.conn()
    r = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if r is None:
        return
    org_id = r["org_id"]
    last = [0.0]

    def set_progress(p: float, force=False):
        now = time.monotonic()
        conn.execute("UPDATE documents SET progress=? WHERE id=?", (p, doc_id))
        if force or now - last[0] > 0.25:
            last[0] = now
            _publish(conn, org_id, doc_id)
    try:
        conn.execute("UPDATE documents SET status='indexing', progress=0.05, error='', hint='' WHERE id=?", (doc_id,))
        _publish(conn, org_id, doc_id)
        data = state.blobs.get(r["sha256"])
        pages = extract_pages(r["kind"], data)
        set_progress(0.5, force=True)
        alltext = []
        with db.tx(conn):
            conn.execute("DELETE FROM document_pages WHERE org_id=? AND doc_id=?", (org_id, doc_id))
            for i, (text, lines, tables) in enumerate(pages, 1):
                conn.execute("INSERT INTO document_pages(org_id,doc_id,page,text,lines_json,tables_json) VALUES(?,?,?,?,?,?)",
                             (org_id, doc_id, i, text, json.dumps(lines, separators=(",", ":")),
                              json.dumps(tables, separators=(",", ":"))))
                alltext.append(text)
        set_progress(0.95)
        conn.execute("UPDATE documents SET status='indexed', progress=1, pages=?, lang=? WHERE id=?",
                     (len(pages), _lang("\n".join(alltext)), doc_id))
    except Exception as e:  # never crash the pool; report on the document
        if not isinstance(e, (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError)) and e.__class__.__name__ != "PdfError":
            traceback.print_exc(file=sys.stderr)
        hint = _fail_hint(e)
        conn.execute("UPDATE documents SET status='failed', progress=0, error=?, hint=? WHERE id=?",
                     (str(e)[:300] or e.__class__.__name__, hint, doc_id))
        try:
            notify.notify(conn, org_id, r["uploaded_by"], "document_failed", f"Could not index {r['name']}",
                          f"{str(e)[:160]}. {hint}", f"/deals/{r['deal_id']}/docs/{doc_id}")
        except Exception:
            traceback.print_exc(file=sys.stderr)
    _publish(conn, org_id, doc_id)


def index_document_sync(state, doc_id: str) -> None:
    _run_index(state, doc_id)


ROUTES = [
    Route("GET", P + "/deals", list_deals, role="viewer"),
    Route("POST", P + "/deals", create_deal, role="member"),
    Route("GET", P + "/deals/{deal_id}", get_deal, role="viewer"),
    Route("PATCH", P + "/deals/{deal_id}", patch_deal, role="member"),
    Route("GET", P + "/deals/{deal_id}/documents", list_documents, role="viewer"),
    Route("POST", P + "/deals/{deal_id}/documents", upload_documents, role="member"),
    Route("GET", P + "/documents/{doc_id}", get_document_route, role="viewer"),
    Route("DELETE", P + "/documents/{doc_id}", delete_document, role="member"),
    Route("GET", P + "/documents/{doc_id}/file", document_file, role="viewer"),
    Route("GET", P + "/documents/{doc_id}/pages/{n}/text", page_text, role="viewer"),
]
