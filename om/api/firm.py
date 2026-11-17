"""Firm setup (SPEC §3/§4, P-J7): accounting definitions, templates and sample decks (style cloned with
`om.deck.house_clone`), connectors, mailbox settings, spend limits and visible memory.

Owner writes, member reads, every query is `org_id`-scoped (another org's id is a 404), every mutation is audited.
Secrets (connector tokens, mailbox passwords) are encrypted at rest with the org secret key and are write-only:
responses carry only a mask such as ``••••wxyz``.

For other modules:
  * `spend_limit(conn, org_id, deal_id)`   jobs call this before starting a run (cost guard, parity 61).
  * `house_profile(conn, org_id)`          the default template's cloned `HouseProfile` dict (or None).
  * `decrypt_connector_secret(...)`        for sync workers that need the plaintext.
"""
from __future__ import annotations

import datetime as _dt
import ipaddress
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse
from pathlib import Path

from . import db, mail, security
from . import state as state_mod
from .http import ApiError, Response, Route, parse_multipart, sanitize_filename

P = "/api/v1"
MAX_ASSET = 50 * 1024 * 1024
MAX_LOGO = 5 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS firm_assets(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('template','sample_deck','sample_model','logo')),
  name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
  style_json TEXT NOT NULL DEFAULT '{}', is_default INTEGER NOT NULL DEFAULT 0, created_by TEXT,
  file_kind TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_firm_assets_org ON firm_assets(org_id, kind);
CREATE TABLE IF NOT EXISTS connectors(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}', secret_enc TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
  last_sync TEXT, created_at TEXT NOT NULL, updated_at TEXT, item_count INTEGER NOT NULL DEFAULT 0,
  bytes INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '', permissions TEXT NOT NULL DEFAULT 'firm',
  created_by TEXT);
CREATE INDEX IF NOT EXISTS idx_connectors_org ON connectors(org_id);
CREATE TABLE IF NOT EXISTS memory(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, scope TEXT NOT NULL CHECK(scope IN ('org','deal')), deal_id TEXT,
  text TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'manual', source_ref TEXT NOT NULL DEFAULT '',
  created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT, updated_by TEXT);
CREATE INDEX IF NOT EXISTS idx_memory_org ON memory(org_id, scope, deal_id);
"""


# =========================================================================== helpers
def _body(ctx) -> dict:
    b = ctx.json
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(400, "bad_body", "The request body must be a JSON object.", "Send a JSON object such as {\"name\": \"...\"}.")
    return b


def _bad(msg: str, hint: str) -> ApiError:
    return ApiError(400, "bad_request", msg, hint)


def _str(b: dict, key: str, maxlen: int, required=False, default: str = "") -> str:
    v = b.get(key, default)
    if v is None:
        v = default
    if not isinstance(v, str):
        raise _bad(f"`{key}` must be text.", f"Send {key} as a string.")
    v = v.strip()
    if required and not v:
        raise _bad(f"`{key}` is required.", f"Provide a non-empty {key}.")
    if len(v) > maxlen:
        raise _bad(f"`{key}` is longer than {maxlen} characters.", f"Shorten {key} to {maxlen} characters or fewer.")
    return v


def _settings(conn, org_id) -> dict:
    r = conn.execute("SELECT settings_json FROM orgs WHERE id=?", (org_id,)).fetchone()
    try:
        s = json.loads((r["settings_json"] if r else "") or "{}")
    except ValueError:
        s = {}
    return s if isinstance(s, dict) else {}


def _save_settings(conn, org_id, s: dict) -> None:
    conn.execute("UPDATE orgs SET settings_json=? WHERE id=?", (json.dumps(s, sort_keys=True, ensure_ascii=False), org_id))


def _state():
    st = state_mod.STATE
    if st is None:
        raise ApiError(503, "unavailable", "The application state is not initialised.", "Start the server first.")
    return st


def _name(ctx) -> str:
    return (ctx.user or {}).get("id") or ""


# ---- paths and hosts a tenant may point the server at (SSRF / local-file guard)
def connector_roots(data_dir) -> list[Path]:
    roots = [Path(data_dir).resolve()]
    for p in (os.environ.get("ACRETIA_CONNECTOR_ROOTS") or "").split(os.pathsep):
        if p.strip():
            roots.append(Path(p.strip()).expanduser().resolve())
    return roots


def check_local_path(data_dir, raw: str, what: str = "folder") -> str:
    """The path must exist-or-not but resolve inside the data dir or an `ACRETIA_CONNECTOR_ROOTS` entry."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise _bad(f"The {what} path is empty.", f"Enter the absolute path of the {what} on the server.")
    p = Path(raw.strip()).expanduser().resolve()
    for root in connector_roots(data_dir):
        if p == root or root in p.parents:
            return str(p)
    raise ApiError(400, "path_not_allowed", f"The {what} path is outside the folders this server may read.",
                   "Place the data under the Acretia data directory, or ask the administrator to list its parent in "
                   "ACRETIA_CONNECTOR_ROOTS.")


def check_public_host(host: str, field: str = "host") -> str:
    """Reject empty hosts, IP literals in private/loopback/link-local ranges and internal-only names."""
    h = (host or "").strip().lower().rstrip(".")
    if not h or len(h) > 253 or not re.fullmatch(r"[a-z0-9.\-:\[\]]+", h):
        raise _bad(f"`{field}` is not a valid host name.", "Enter a host name such as imap.example.com.")
    if os.environ.get("ACRETIA_ALLOW_PRIVATE_HOSTS") == "1":
        return h
    bare = h.strip("[]")
    try:
        ip = ipaddress.ip_address(bare)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise ApiError(400, "host_not_allowed", "Private, loopback and link-local addresses are not allowed.",
                           "Use the public host name of the server (set ACRETIA_ALLOW_PRIVATE_HOSTS=1 only on a trusted self-hosted install).")
        return bare
    if h == "localhost" or h.endswith((".local", ".internal", ".localhost", ".lan", ".home.arpa")) or "." not in h:
        raise ApiError(400, "host_not_allowed", "Internal host names are not allowed.",
                       "Use the public host name of the server (set ACRETIA_ALLOW_PRIVATE_HOSTS=1 only on a trusted self-hosted install).")
    return h


# =========================================================================== definitions
SEEDS = (
    ("adjusted_ebitda", "Adjusted EBITDA",
     "Operating income plus depreciation and amortisation, adding back stock-based compensation, restructuring and "
     "other non-recurring items disclosed in the filings. Always shown with a bridge from reported EBITDA.",
     "Operating income + D&A + SBC + non-recurring items"),
    ("net_debt", "Net debt",
     "Total borrowings including lease liabilities, less cash, cash equivalents and short-term investments. "
     "Restricted cash is excluded.",
     "Debt + leases - cash - short-term investments"),
)
KEY_RX = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _seeded(s: dict) -> dict:
    defs = s.get("definitions")
    if isinstance(defs, dict) and defs:
        return defs
    ts = db.now()
    return {k: {"key": k, "label": lab, "text": txt, "formula_hint": hint, "updated_by": None, "updated_at": ts, "history": []}
            for k, lab, txt, hint in SEEDS}


def _clean_def(d: dict) -> dict:
    text = d.get("text") if isinstance(d.get("text"), str) else d.get("definition") if isinstance(d.get("definition"), str) else ""
    return {"key": d.get("key", ""), "label": d.get("label") or d.get("key", ""), "text": text,
            "formula_hint": d.get("formula_hint") or "", "updated_by": d.get("updated_by"), "updated_at": d.get("updated_at"),
            "history": [h for h in (d.get("history") or []) if isinstance(h, str)]}


def _deal_definitions(conn, org_id) -> dict:
    out = {}
    for r in conn.execute("SELECT deal_id, name, definitions FROM deals WHERE org_id=?", (org_id,)).fetchall():
        try:
            out[r["deal_id"]] = (r["name"], json.loads(r["definitions"] or "{}"))
        except ValueError:
            out[r["deal_id"]] = (r["name"], {})
    return out


def _outdated(defn: dict, deal_defs: dict) -> list[str]:
    """Deal ids whose copy is missing or equals an earlier firm version (a deliberate deal override is left alone)."""
    out = []
    for did, (_n, dd) in deal_defs.items():
        have = dd.get(defn["key"])
        if have == defn["text"]:
            continue
        if have is None or have in defn["history"]:
            out.append(did)
    return out


def _defs_view(conn, org_id) -> dict:
    s = _settings(conn, org_id)
    defs = _seeded(s)
    dd = _deal_definitions(conn, org_id)
    items = []
    for k, v in defs.items():
        d = _clean_def({"key": k, **v}) if isinstance(v, dict) else _clean_def({"key": k, "text": str(v)})
        stale = _outdated(d, dd)
        items.append({k2: d[k2] for k2 in ("key", "label", "text", "formula_hint", "updated_by", "updated_at")}
                     | {"outdated_deals": len(stale), "outdated_deal_ids": stale[:200]})
    return {"items": items, "deals": [{"deal_id": i, "name": n} for i, (n, _d) in dd.items()]}


def get_definitions(ctx):
    return _defs_view(ctx.conn, ctx.org_id)


def put_definitions(ctx):
    ctx.require("owner")
    b = _body(ctx)
    raw = b.get("items", b.get("definitions"))
    if isinstance(raw, dict):
        raw = [{"key": k, **(v if isinstance(v, dict) else {"text": v})} for k, v in raw.items()]
    if not isinstance(raw, list) or len(raw) > 100:
        raise _bad("`items` must be a list of at most 100 definitions.", 'Send {"items": [{"key": "adjusted_ebitda", "label": "...", "text": "..."}]}.')
    s = _settings(ctx.conn, ctx.org_id)
    cur = {k: _clean_def({"key": k, **v}) for k, v in _seeded(s).items() if isinstance(v, dict)}
    new, changed, ts = {}, [], db.now()
    for it in raw:
        if not isinstance(it, dict):
            raise _bad("Each definition must be an object.", "Send {key, label, text, formula_hint}.")
        key = _str(it, "key", 48, required=True)
        if not KEY_RX.match(key):
            raise _bad(f"`{key}` is not a valid key.", "Use lowercase letters, digits and underscores, starting with a letter.")
        if key in new:
            raise _bad(f"The key `{key}` appears twice.", "Keep one entry per key.")
        label = _str(it, "label", 80) or key.replace("_", " ").capitalize()
        text = _str(it, "text", 2000, required=True)
        hint = _str(it, "formula_hint", 300)
        old = cur.get(key)
        hist = list(old["history"]) if old else []
        if old and old["text"] != text:
            hist = ([old["text"]] + hist)[:20]
            changed.append(key)
        elif not old:
            changed.append(key)
        same = old and old["text"] == text and old["label"] == label and old["formula_hint"] == hint
        new[key] = {"key": key, "label": label, "text": text, "formula_hint": hint, "history": hist,
                    "updated_by": old["updated_by"] if same else _name(ctx), "updated_at": old["updated_at"] if same else ts}
    removed = sorted(set(cur) - set(new))
    with db.tx(ctx.conn):
        s["definitions"] = new
        _save_settings(ctx.conn, ctx.org_id, s)
    ctx.audit("firm.definitions.update", f"org:{ctx.org_id}", {"changed": changed, "removed": removed, "count": len(new)})
    return _defs_view(ctx.conn, ctx.org_id) | {"changed": changed, "removed": removed}


def apply_definitions(ctx):
    ctx.require("owner")
    b = _body(ctx)
    ids = b.get("deal_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 500 or not all(isinstance(i, str) for i in ids):
        raise _bad("`deal_ids` must be a non-empty list of deal ids.", 'Send {"deal_ids": ["deal-..."]}.')
    keys = b.get("keys")
    if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
        raise _bad("`keys` must be a list of definition keys.", "Omit it to apply every outdated definition.")
    dd = _deal_definitions(ctx.conn, ctx.org_id)
    for i in ids:
        if i not in dd:
            raise ApiError(404, "not_found", "No such deal.")
    s = _settings(ctx.conn, ctx.org_id)
    defs = {k: _clean_def({"key": k, **v}) for k, v in _seeded(s).items() if isinstance(v, dict)}
    store = _state().deal_store(ctx.conn, ctx.org_id)
    applied = []
    for did in dict.fromkeys(ids):
        done = []
        for k, d in defs.items():
            if keys is not None and k not in keys:
                continue
            if did in _outdated(d, {did: dd[did]}):
                store.set_definition(did, k, d["text"])
                done.append(k)
        if done:
            applied.append({"deal_id": did, "keys": done})
    ctx.audit("firm.definitions.apply", f"org:{ctx.org_id}", {"deals": [a["deal_id"] for a in applied], "count": len(applied)})
    return {"applied": applied, **_defs_view(ctx.conn, ctx.org_id)}


# =========================================================================== assets (templates, sample decks)
ASSET_KINDS = {"template": ("pptx",), "sample_deck": ("pptx",), "sample_model": ("xlsx",), "logo": ("png", "jpg")}


def _asset_view(r, with_style=True) -> dict:
    try:
        style = json.loads(r["style_json"] or "{}")
    except ValueError:
        style = {}
    d = {"id": r["id"], "kind": r["kind"], "name": r["name"], "size": r["size"], "created_at": r["created_at"],
         "is_default": bool(r["is_default"]), "file_kind": r["file_kind"], "created_by": r["created_by"]}
    if with_style:
        prev = style.get("preview")
        d["style"] = prev
        d["style_error"] = style.get("error")
        d["style_hint"] = style.get("hint")
    return d


def _get_asset(conn, org_id, asset_id):
    r = conn.execute("SELECT * FROM firm_assets WHERE org_id=? AND id=?", (org_id, asset_id)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such file.")
    return r


def _preview(profile, prs) -> dict:
    th = profile.theme
    palette = [{"token": k, "hex": v} for k, v in th.colors.items()]
    layouts = []
    try:
        layouts = [lay.name for lay in prs.slide_layouts][:40]
    except Exception:                                                  # noqa: BLE001
        pass
    return {"palette": palette, "fonts": dict(th.fonts), "layouts": layouts, "layout_used": profile.layout_name,
            "slide_size_in": [profile.grid.get("canvas_w"), profile.grid.get("canvas_h")],
            "sizes": {k: v for k, v in profile.sizes.items() if isinstance(v, (int, float))},
            "evidence": list(profile.evidence)[:30]}


def _clone(blobs, name: str, data: bytes, sample_datas: list) -> dict:
    """Run the S3.9 cloner on `data`; returns style_json. Raises ApiError(422) with a hint when it cannot be read."""
    from om.deck import house_clone
    suffix = ".potx" if name.lower().endswith((".potx", ".potm")) else ".pptx"
    with tempfile.TemporaryDirectory(prefix="acr-clone-") as td:
        p = Path(td) / ("template" + suffix)
        p.write_bytes(data)
        samples = []
        for i, sd in enumerate(sample_datas[:3]):
            sp = Path(td) / f"sample{i}.pptx"
            sp.write_bytes(sd)
            samples.append(str(sp))
        try:
            prof = house_clone.clone(str(p), samples)
            prs, _ = house_clone._open(str(p))
            return {"profile": prof.to_dict(), "preview": _preview(prof, prs)}
        except house_clone.CloneError as e:
            raise ApiError(422, "template_unreadable", f"The file could not be read as a template: {str(e)[:160]}.",
                           "Save it from PowerPoint as .pptx or .potx and upload it again.") from None
        except Exception as e:                                          # noqa: BLE001
            raise ApiError(422, "template_unreadable", f"The file could not be read as a template ({type(e).__name__}).",
                           "Open it in PowerPoint, save it as .pptx or .potx, and upload it again.") from None


def _sample_blobs(conn, blobs, org_id) -> list:
    out = []
    for r in conn.execute("SELECT sha256 FROM firm_assets WHERE org_id=? AND kind='sample_deck' ORDER BY created_at DESC LIMIT 3", (org_id,)):
        try:
            out.append(blobs.get(r["sha256"]))
        except Exception:                                               # noqa: BLE001
            continue
    return out


def _reclone_template(conn, blobs, org_id) -> None:
    """After the sample decks change, re-derive the default (or newest) template's style from them."""
    r = conn.execute("SELECT * FROM firm_assets WHERE org_id=? AND kind='template' ORDER BY is_default DESC, created_at DESC LIMIT 1", (org_id,)).fetchone()
    if r is None:
        return
    try:
        style = _clone(blobs, r["name"], blobs.get(r["sha256"]), _sample_blobs(conn, blobs, org_id))
    except ApiError:
        return
    conn.execute("UPDATE firm_assets SET style_json=? WHERE id=?", (json.dumps(style), r["id"]))


def list_assets(ctx):
    rows = ctx.conn.execute("SELECT * FROM firm_assets WHERE org_id=? ORDER BY kind, is_default DESC, created_at DESC", (ctx.org_id,)).fetchall()
    return {"items": [_asset_view(r) for r in rows], "next_cursor": None}


def _read_upload(ctx):
    ct = ctx.headers.get("Content-Type") or ""
    kind = ctx.query.get("kind") or ctx.headers.get("X-Asset-Kind") or ""
    if ct.lower().startswith("multipart/form-data"):
        parts = parse_multipart(ctx.body, ct, MAX_ASSET + 4096)
        for n, fn, _t, d in parts:
            if fn is None and n == "kind":
                kind = d.decode("utf-8", "replace").strip()
        files = [(fn, d) for n, fn, _t, d in parts if fn is not None]
        if not files:
            raise ApiError(400, "no_file", "The upload contains no file.", "Attach the template or sample file.")
        fname, data = files[0]
    else:
        raw = ctx.headers.get("X-Filename")
        if not raw or not ctx.body:
            raise ApiError(400, "no_file", "No file was sent.", "Send multipart/form-data, or a raw body with an X-Filename header.")
        fname, data = urllib.parse.unquote(raw), ctx.body
    return str(fname), data, kind.strip().lower()


def upload_asset(ctx):
    ctx.require("owner")
    fname, data, kind = _read_upload(ctx)
    if kind not in ASSET_KINDS:
        raise _bad("Say what the file is.", "Pass kind as template, sample_deck, sample_model or logo.")
    if len(data) > (MAX_LOGO if kind == "logo" else MAX_ASSET):
        raise ApiError(413, "too_large", "The file is too large.", "Logos can be 5 MB, other files 50 MB.")
    name = sanitize_filename(fname)
    sniffed = security.sniff(data, name)
    if sniffed not in ASSET_KINDS[kind]:
        want = " or ".join(ASSET_KINDS[kind]).upper()
        raise ApiError(415, "unsupported_type", f"A {kind.replace('_', ' ')} must be a {want} file.",
                       f"Upload a {want} file (the file's contents are checked, not just its name).")
    style: dict = {}
    if kind in ("template", "sample_deck"):
        samples = _sample_blobs(ctx.conn, ctx.blobs, ctx.org_id) if kind == "template" else []
        style = _clone(ctx.blobs, name, data, samples)
    key = ctx.blobs.put(data)
    aid = db.new_id("tpl")
    first = ctx.conn.execute("SELECT COUNT(*) FROM firm_assets WHERE org_id=? AND kind=?", (ctx.org_id, kind)).fetchone()[0] == 0
    with db.tx(ctx.conn):
        ctx.conn.execute("INSERT INTO firm_assets(id,org_id,kind,name,sha256,size,created_at,style_json,is_default,created_by,file_kind) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (aid, ctx.org_id, kind, name, key, len(data), db.now(), json.dumps(style),
                                                           1 if first and kind in ("template", "logo") else 0, _name(ctx), sniffed))
        if kind == "sample_deck":
            _reclone_template(ctx.conn, ctx.blobs, ctx.org_id)
    ctx.audit("firm.asset.upload", f"asset:{aid}", {"kind": kind, "name": name, "size": len(data)})
    return 201, _asset_view(_get_asset(ctx.conn, ctx.org_id, aid))


def patch_asset(ctx):
    ctx.require("owner")
    r = _get_asset(ctx.conn, ctx.org_id, ctx.params["asset_id"])
    b = _body(ctx)
    if "is_default" in b:
        if r["kind"] not in ("template", "logo"):
            raise _bad("Only templates and logos can be the default.", "Set the default on a template or logo.")
        with db.tx(ctx.conn):
            if b["is_default"]:
                ctx.conn.execute("UPDATE firm_assets SET is_default=0 WHERE org_id=? AND kind=?", (ctx.org_id, r["kind"]))
            ctx.conn.execute("UPDATE firm_assets SET is_default=? WHERE id=?", (1 if b["is_default"] else 0, r["id"]))
    if "name" in b:
        ctx.conn.execute("UPDATE firm_assets SET name=? WHERE id=?", (sanitize_filename(_str(b, "name", 120, required=True)), r["id"]))
    ctx.audit("firm.asset.update", f"asset:{r['id']}", {k: b[k] for k in ("is_default", "name") if k in b})
    return _asset_view(_get_asset(ctx.conn, ctx.org_id, r["id"]))


def delete_asset(ctx):
    ctx.require("owner")
    r = _get_asset(ctx.conn, ctx.org_id, ctx.params["asset_id"])
    with db.tx(ctx.conn):
        ctx.conn.execute("DELETE FROM firm_assets WHERE id=?", (r["id"],))
        if r["is_default"]:
            nxt = ctx.conn.execute("SELECT id FROM firm_assets WHERE org_id=? AND kind=? ORDER BY created_at DESC LIMIT 1", (ctx.org_id, r["kind"])).fetchone()
            if nxt:
                ctx.conn.execute("UPDATE firm_assets SET is_default=1 WHERE id=?", (nxt["id"],))
        if r["kind"] == "sample_deck":
            _reclone_template(ctx.conn, ctx.blobs, ctx.org_id)
    ctx.audit("firm.asset.delete", f"asset:{r['id']}", {"kind": r["kind"], "name": r["name"]})
    return {"deleted": r["id"]}


def asset_file(ctx):
    r = _get_asset(ctx.conn, ctx.org_id, ctx.params["asset_id"])
    data = ctx.blobs.get(r["sha256"])
    inline = r["file_kind"] in ("png", "jpg")
    fn = sanitize_filename(r["name"])
    return Response(200, data, security.MIME.get(r["file_kind"], "application/octet-stream"),
                    {"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{fn}"'})


def house_profile(conn, org_id) -> dict | None:
    """The default template's cloned `HouseProfile.to_dict()`, or None when the firm has no usable template."""
    r = conn.execute("SELECT style_json FROM firm_assets WHERE org_id=? AND kind='template' ORDER BY is_default DESC, created_at DESC LIMIT 1", (org_id,)).fetchone()
    if r is None:
        return None
    try:
        return (json.loads(r["style_json"] or "{}") or {}).get("profile")
    except ValueError:
        return None


# =========================================================================== connectors
# kind -> (harness connector name, required config fields, token-based, local path field)
KINDS = {
    "local_folder": {"label": "Local folder", "harness": "local_room", "required": ["path"], "path": "path", "secret": False,
                     "fields": ["path"]},
    "s3": {"label": "S3 / MinIO", "harness": "s3_room", "required": ["endpoint", "bucket"], "host": "endpoint", "secret": True,
           "fields": ["endpoint", "bucket", "prefix", "region", "access_key_id"]},
    "sharepoint": {"label": "SharePoint / OneDrive", "harness": "sharepoint", "required": ["drive_id"], "secret": True,
                   "fields": ["drive_id", "folder"]},
    "google_drive": {"label": "Google Drive (Drive for desktop mount)", "harness": "synced_folder", "required": ["path"], "path": "path",
                     "secret": False, "fields": ["path"]},
    "vdr_export": {"label": "VDR export (Datasite, Intralinks, Ansarada)", "harness": "archive_room", "required": ["path"], "path": "path",
                   "secret": False, "fields": ["path"]},
    "box": {"label": "Box", "harness": "box", "required": ["folder_id"], "secret": True, "fields": ["folder_id"]},
    "dropbox": {"label": "Dropbox", "harness": "dropbox", "required": ["folder"], "secret": True, "fields": ["folder"]},
}
SECRETISH = re.compile(r"(token|secret|password|passwd|api[_-]?key|credential)", re.I)
PERMISSIONS = ("firm", "mirror")      # mirror: search results follow the source system's permissions (parity 62)


def _conn_view(r, key: bytes | None = None) -> dict:
    cfg = json.loads(r["config_json"] or "{}")
    masked = ""
    if r["secret_enc"]:
        try:
            masked = security.mask_secret(security.decrypt_secret(key or _state().secret_key, r["secret_enc"])) or "••••"
        except ValueError:
            masked = "••••"
    return {"id": r["id"], "kind": r["kind"], "kind_label": KINDS.get(r["kind"], {}).get("label", r["kind"]), "name": r["name"],
            "config": cfg, "secret": masked, "has_secret": bool(r["secret_enc"]), "status": r["status"], "last_sync": r["last_sync"],
            "item_count": r["item_count"], "bytes": r["bytes"], "last_error": r["last_error"], "permissions": r["permissions"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def _validate_config(ctx, kind: str, cfg) -> dict:
    spec = KINDS.get(kind)
    if spec is None:
        raise _bad(f"Unknown connector kind `{kind}`.", f"Use one of: {', '.join(KINDS)}.")
    if not isinstance(cfg, dict):
        raise _bad("`config` must be an object.", "Send the connector settings as a JSON object.")
    out = {}
    for k, v in cfg.items():
        if SECRETISH.search(str(k)):
            raise _bad(f"`{k}` looks like a credential and cannot go in config.", "Send it in the write-only `secret` field instead.")
        if k not in spec["fields"]:
            raise _bad(f"`{k}` is not a setting of {spec['label']}.", f"Allowed settings: {', '.join(spec['fields'])}.")
        if not isinstance(v, str) or len(v) > 500:
            raise _bad(f"`{k}` must be text up to 500 characters.", f"Send {k} as a short string.")
        out[k] = v.strip()
    for k in spec["required"]:
        if not out.get(k):
            raise _bad(f"`{k}` is required for {spec['label']}.", f"Fill in {k}.")
    if spec.get("path"):
        out[spec["path"]] = check_local_path(ctx.data_dir, out[spec["path"]], "folder" if kind != "vdr_export" else "export")
    if spec.get("host"):
        u = urllib.parse.urlparse(out[spec["host"]] if "://" in out[spec["host"]] else "https://" + out[spec["host"]])
        if u.scheme != "https" and os.environ.get("ACRETIA_ALLOW_PRIVATE_HOSTS") != "1":
            raise _bad("The endpoint must use https.", "Use an https:// endpoint.")
        check_public_host(u.hostname or "", spec["host"])
    return out


def _perm(b: dict, default="firm") -> str:
    v = b.get("permissions", default)
    if v not in PERMISSIONS:
        raise _bad("`permissions` must be firm or mirror.", "firm: everyone in the firm can search it. mirror: search follows the source's access rules.")
    return v


def _summary(rows: list) -> dict:
    total = len(rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    err = sum(1 for r in rows if r["status"] == "error")
    syncs = [r["last_sync"] for r in rows if r["last_sync"]]
    return {"total": total, "ok": ok, "errors": err, "never_synced": sum(1 for r in rows if not r["last_sync"]),
            "items": sum(r["item_count"] for r in rows), "bytes": sum(r["bytes"] for r in rows), "last_sync": max(syncs) if syncs else None}


def list_connectors(ctx):
    rows = ctx.conn.execute("SELECT * FROM connectors WHERE org_id=? ORDER BY created_at, id", (ctx.org_id,)).fetchall()
    key = _state().secret_key
    return {"items": [_conn_view(r, key) for r in rows], "next_cursor": None, "summary": _summary(rows)}


def connector_kinds(ctx):
    return {"items": [{"kind": k, "label": v["label"], "fields": v["fields"], "required": v["required"], "secret": v["secret"],
                       "local": bool(v.get("path"))} for k, v in KINDS.items()]}


def create_connector(ctx):
    ctx.require("owner")
    b = _body(ctx)
    kind = _str(b, "kind", 30, required=True)
    cfg = _validate_config(ctx, kind, b.get("config") or {})
    name = _str(b, "name", 120) or KINDS[kind]["label"]
    secret = b.get("secret")
    if secret is not None and not isinstance(secret, str):
        raise _bad("`secret` must be text.", "Send the token or password as a string.")
    if KINDS[kind]["secret"] and not secret:
        raise _bad(f"{KINDS[kind]['label']} needs an access token.", "Paste the token into `secret`; it is stored encrypted and never shown again.")
    perm = _perm(b)
    cid = db.new_id("con")
    enc = security.encrypt_secret(_state().secret_key, secret) if secret else ""
    ctx.conn.execute("INSERT INTO connectors(id,org_id,kind,name,config_json,secret_enc,status,created_at,updated_at,permissions,created_by) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, ctx.org_id, kind, name, json.dumps(cfg, sort_keys=True), enc, "new", db.now(), db.now(), perm, _name(ctx)))
    ctx.audit("firm.connector.create", f"connector:{cid}", {"kind": kind, "name": name, "has_secret": bool(secret)})
    return 201, _conn_view(_get_connector(ctx.conn, ctx.org_id, cid))


def _get_connector(conn, org_id, cid):
    r = conn.execute("SELECT * FROM connectors WHERE org_id=? AND id=?", (org_id, cid)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such connector.")
    return r


def patch_connector(ctx):
    ctx.require("owner")
    r = _get_connector(ctx.conn, ctx.org_id, ctx.params["connector_id"])
    b = _body(ctx)
    sets, args, audit = [], [], {}
    if "name" in b:
        sets.append("name=?"); args.append(_str(b, "name", 120, required=True)); audit["name"] = args[-1]
    if "config" in b:
        sets.append("config_json=?"); args.append(json.dumps(_validate_config(ctx, r["kind"], b["config"]), sort_keys=True)); audit["config"] = True
        sets.append("status=?"); args.append("new")
    if "permissions" in b:
        sets.append("permissions=?"); args.append(_perm(b)); audit["permissions"] = args[-1]
    if "secret" in b:
        sec = b["secret"]
        if sec in (None, ""):
            if KINDS[r["kind"]]["secret"]:
                raise _bad("This connector needs an access token.", "Send a new token, or leave `secret` out to keep the current one.")
            sets.append("secret_enc=?"); args.append("")
        elif isinstance(sec, str):
            if not sec.startswith("••••"):          # the masked value coming back from GET means "unchanged"
                sets.append("secret_enc=?"); args.append(security.encrypt_secret(_state().secret_key, sec))
                audit["secret"] = "rotated"
        else:
            raise _bad("`secret` must be text.", "Send the token as a string.")
    if sets:
        sets.append("updated_at=?"); args.append(db.now())
        ctx.conn.execute(f"UPDATE connectors SET {', '.join(sets)} WHERE id=?", args + [r["id"]])
    ctx.audit("firm.connector.update", f"connector:{r['id']}", audit)
    return _conn_view(_get_connector(ctx.conn, ctx.org_id, r["id"]))


def delete_connector(ctx):
    ctx.require("owner")
    r = _get_connector(ctx.conn, ctx.org_id, ctx.params["connector_id"])
    ctx.conn.execute("DELETE FROM connectors WHERE id=?", (r["id"],))
    ctx.audit("firm.connector.delete", f"connector:{r['id']}", {"kind": r["kind"], "name": r["name"]})
    return {"deleted": r["id"]}


def decrypt_connector_secret(conn, org_id, connector_id) -> str:
    r = _get_connector(conn, org_id, connector_id)
    return security.decrypt_secret(_state().secret_key, r["secret_enc"]) if r["secret_enc"] else ""


def test_connector(ctx):
    ctx.require("owner")
    r = _get_connector(ctx.conn, ctx.org_id, ctx.params["connector_id"])
    spec, cfg = KINDS.get(r["kind"]), json.loads(r["config_json"] or "{}")
    ts, ok, msg, hint, items, size, live = db.now(), True, "", "", 0, 0, False
    if spec is None:
        ok, msg, hint = False, f"Unknown connector kind {r['kind']}.", "Delete it and add it again."
    elif spec["secret"] and not r["secret_enc"]:
        ok, msg, hint = False, "No access token is stored.", "Edit the connector and paste a token."
    elif spec.get("path"):
        live = True
        try:
            path = check_local_path(ctx.data_dir, cfg.get(spec["path"], ""))
            p = Path(path)
            if not p.exists():
                raise FileNotFoundError(path)
            if p.is_file():
                items, size = 1, p.stat().st_size
            else:
                for f in p.rglob("*"):
                    if f.is_file() and not f.is_symlink():
                        items += 1
                        size += f.stat().st_size
                        if items >= 50000:
                            break
            msg = f"Found {items} file{'s' if items != 1 else ''}."
        except ApiError as e:
            ok, msg, hint = False, e.message, e.hint or ""
        except OSError:
            ok, msg, hint = False, "The folder does not exist or cannot be read.", "Check the path on the server and its permissions."
    else:
        msg = "Settings and token are saved. The live connection is checked on the first sync."
    status = ("ok" if live else "configured") if ok else "error"
    ctx.conn.execute("UPDATE connectors SET status=?, last_error=?, item_count=?, bytes=?, last_sync=? WHERE id=?",
                     (status, "" if ok else msg, items if live and ok else r["item_count"], size if live and ok else r["bytes"],
                      ts if ok and live else r["last_sync"], r["id"]))
    ctx.audit("firm.connector.test", f"connector:{r['id']}", {"ok": ok, "status": status})
    return {"ok": ok, "status": status, "message": msg, "hint": hint, "live": live, "items": items, "bytes": size,
            "connector": _conn_view(_get_connector(ctx.conn, ctx.org_id, r["id"]))}


# =========================================================================== mailbox
def _mailbox_row(conn, org_id):
    return conn.execute("SELECT * FROM mailbox WHERE org_id=?", (org_id,)).fetchone()


def _mailbox_view(r) -> dict:
    if r is None:
        return {"configured": False, "kind": "imap", "host": "", "port": 993, "username": "", "secret": "", "has_secret": False,
                "folder": "INBOX", "path": "", "poll_seconds": 300, "allowed_senders": [], "send_enabled": False,
                "status": "unconfigured", "last_poll": None}
    masked = ""
    if r["secret_enc"]:
        try:
            masked = security.mask_secret(security.decrypt_secret(_state().secret_key, r["secret_enc"])) or "••••"
        except ValueError:
            masked = "••••"
    return {"configured": True, "kind": r["kind"], "host": r["host"] or "", "port": r["port"] or 993, "username": r["username"] or "",
            "secret": masked, "has_secret": bool(r["secret_enc"]), "folder": r["folder"] or "INBOX", "path": r["path"] or "",
            "poll_seconds": r["poll_seconds"], "allowed_senders": json.loads(r["allowed_senders_json"] or "[]"),
            "send_enabled": bool(r["send_enabled"]), "status": r["status"] or "new", "last_poll": r["last_poll"]}


def get_mailbox(ctx):
    return _mailbox_view(_mailbox_row(ctx.conn, ctx.org_id))


EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def put_mailbox(ctx):
    ctx.require("owner")                     # also guards send_enabled: only an owner can ever set it
    b = _body(ctx)
    cur = _mailbox_row(ctx.conn, ctx.org_id)
    kind = _str(b, "kind", 10, default=(cur["kind"] if cur else "imap"))
    if kind not in ("imap", "maildir"):
        raise _bad("`kind` must be imap or maildir.", "Use imap for a hosted mailbox, or maildir for a folder of messages.")
    host = _str(b, "host", 253, default=(cur["host"] if cur else "") or "")
    path = _str(b, "path", 500, default=(cur["path"] if cur else "") or "")
    username = _str(b, "username", 200, default=(cur["username"] if cur else "") or "")
    folder = _str(b, "folder", 200, default=(cur["folder"] if cur else "") or "INBOX") or "INBOX"
    port = b.get("port", cur["port"] if cur else 993)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise _bad("`port` must be a number from 1 to 65535.", "IMAP over TLS normally uses 993.")
    poll = b.get("poll_seconds", cur["poll_seconds"] if cur else 300)
    if not isinstance(poll, int) or isinstance(poll, bool) or poll < 60 or poll > 86400:
        raise _bad("`poll_seconds` must be between 60 and 86400.", "Polling more than once a minute is not allowed.")
    senders_in = b.get("allowed_senders", json.loads(cur["allowed_senders_json"] or "[]") if cur else [])
    if not isinstance(senders_in, list) or len(senders_in) > 100:
        raise _bad("`allowed_senders` must be a list of email addresses.", "Add exact addresses, one per entry.")
    senders = []
    for s in senders_in:
        s = str(s).strip().lower()
        if not EMAIL_RX.match(s):
            raise _bad(f"`{s[:60]}` is not an email address.", "Use exact addresses like name@firm.com (no names, no wildcards).")
        if s not in senders:
            senders.append(s)
    if kind == "imap":
        if not host:
            raise _bad("An IMAP mailbox needs a host.", "Enter the IMAP server, for example imap.example.com.")
        host = check_public_host(host)
        path = ""
    else:
        path = check_local_path(ctx.data_dir, path, "mailbox folder")
        host = ""
    send = b.get("send_enabled", bool(cur["send_enabled"]) if cur else False)
    if not isinstance(send, bool):
        raise _bad("`send_enabled` must be true or false.", "It is off by default.")
    enc = cur["secret_enc"] if cur else ""
    if "secret" in b:
        sec = b["secret"]
        if sec in (None, ""):
            enc = ""
        elif not isinstance(sec, str):
            raise _bad("`secret` must be text.", "Send the mailbox password as a string.")
        elif not sec.startswith("••••"):
            enc = security.encrypt_secret(_state().secret_key, sec)
    if kind == "imap" and not enc:
        raise _bad("An IMAP mailbox needs a password or app password.", "Paste it into `secret`; it is stored encrypted and never shown again.")
    ts = db.now()
    ctx.conn.execute(
        "INSERT INTO mailbox(org_id,kind,host,port,username,secret_enc,folder,path,poll_seconds,allowed_senders_json,send_enabled,status,owner_id,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(org_id) DO UPDATE SET kind=excluded.kind, host=excluded.host, port=excluded.port, "
        "username=excluded.username, secret_enc=excluded.secret_enc, folder=excluded.folder, path=excluded.path, poll_seconds=excluded.poll_seconds, "
        "allowed_senders_json=excluded.allowed_senders_json, send_enabled=excluded.send_enabled, owner_id=excluded.owner_id, updated_at=excluded.updated_at, "
        "status=CASE WHEN mailbox.kind=excluded.kind AND mailbox.host=excluded.host AND mailbox.path=excluded.path THEN mailbox.status ELSE 'new' END, "
        "last_uid=CASE WHEN mailbox.kind=excluded.kind AND mailbox.host=excluded.host AND mailbox.folder=excluded.folder THEN mailbox.last_uid ELSE 0 END",
        (ctx.org_id, kind, host, port, username, enc, folder, path, poll, json.dumps(senders), 1 if send else 0, "new", _name(ctx), ts))
    ctx.audit("firm.mailbox.update", f"org:{ctx.org_id}", {"kind": kind, "host": host, "send_enabled": send, "senders": len(senders),
                                                           "secret": "set" if enc else "none"})
    return _mailbox_view(_mailbox_row(ctx.conn, ctx.org_id))


def test_mailbox(ctx):
    ctx.require("owner")
    r = _mailbox_row(ctx.conn, ctx.org_id)
    if r is None:
        raise ApiError(409, "not_configured", "No mailbox is configured yet.", "Save the mailbox settings first, then test them.")
    res = mail.test_mailbox(_state(), dict(r))
    ctx.conn.execute("UPDATE mailbox SET status=? WHERE org_id=?", ("ok" if res["ok"] else "error", ctx.org_id))
    ctx.audit("firm.mailbox.test", f"org:{ctx.org_id}", {"ok": res["ok"]})
    return res


def mailbox_log(ctx):
    ctx.require("owner")
    try:
        lim = max(1, min(200, int(ctx.query.get("limit", 50))))
    except ValueError:
        lim = 50
    rows = ctx.conn.execute("SELECT * FROM mail_log WHERE org_id=? ORDER BY at DESC, rowid DESC LIMIT ?", (ctx.org_id, lim)).fetchall()
    return {"items": [dict(r) for r in rows], "next_cursor": None}


# =========================================================================== spend limits (parity 61)
def _month_start() -> str:
    n = _dt.datetime.now(_dt.timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def _limits(s: dict) -> dict:
    lim = s.get("limits") if isinstance(s.get("limits"), dict) else {}
    return {"org_monthly_usd": lim.get("org_monthly_usd"), "deal_usd": lim.get("deal_usd"),
            "deals": dict(lim.get("deals") or {})}


def _spent(conn, org_id, deal_id=None, since=None) -> float:
    sql, args = "SELECT COALESCE(SUM(cost_usd),0) FROM jobs WHERE org_id=?", [org_id]
    if deal_id:
        sql += " AND deal_id=?"; args.append(deal_id)
    if since:
        sql += " AND created_at>=?"; args.append(since)
    try:
        return float(conn.execute(sql, args).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0.0


def spend_limit(conn, org_id, deal_id=None) -> dict:
    """Jobs call this before they start. -> {allowed, reason, hint, org:{limit,spent}, deal:{limit,spent}}."""
    lim = _limits(_settings(conn, org_id))
    org_spent = _spent(conn, org_id, since=_month_start())
    deal_limit = lim["deals"].get(deal_id) if deal_id else None
    if deal_limit is None and deal_id:
        deal_limit = lim["deal_usd"]
    deal_spent = _spent(conn, org_id, deal_id) if deal_id else 0.0
    out = {"allowed": True, "reason": None, "hint": None, "org": {"limit": lim["org_monthly_usd"], "spent": round(org_spent, 4)},
           "deal": {"limit": deal_limit, "spent": round(deal_spent, 4)}}
    if lim["org_monthly_usd"] is not None and org_spent >= lim["org_monthly_usd"]:
        out.update(allowed=False, reason="org_limit",
                   hint=f"The firm's monthly limit of ${lim['org_monthly_usd']:,.2f} is used up. An owner can raise it in Settings.")
    elif deal_limit is not None and deal_spent >= deal_limit:
        out.update(allowed=False, reason="deal_limit", hint=f"This deal's limit of ${deal_limit:,.2f} is used up. An owner can raise it in Settings.")
    return out


def _limit_val(v, field):
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v > 10_000_000:
        raise _bad(f"`{field}` must be a dollar amount of 0 or more, or null for no limit.", "Send a number such as 250.")
    return round(float(v), 2)


def _limits_view(conn, org_id) -> dict:
    lim = _limits(_settings(conn, org_id))
    rows = conn.execute("SELECT d.deal_id, d.name FROM deals d WHERE d.org_id=? ORDER BY d.created_at DESC LIMIT 200", (org_id,)).fetchall()
    usage = []
    for r in rows:
        sp = _spent(conn, org_id, r["deal_id"])
        usage.append({"deal_id": r["deal_id"], "name": r["name"], "spent": round(sp, 4),
                      "limit": lim["deals"].get(r["deal_id"], lim["deal_usd"])})
    return {**lim, "org_spent_month": round(_spent(conn, org_id, since=_month_start()), 4), "usage": usage, "currency": "USD"}


def get_limits(ctx):
    return _limits_view(ctx.conn, ctx.org_id)


def put_limits(ctx):
    ctx.require("owner")
    b = _body(ctx)
    s = _settings(ctx.conn, ctx.org_id)
    cur = _limits(s)
    if "org_monthly_usd" in b:
        cur["org_monthly_usd"] = _limit_val(b["org_monthly_usd"], "org_monthly_usd")
    if "deal_usd" in b:
        cur["deal_usd"] = _limit_val(b["deal_usd"], "deal_usd")
    if "deals" in b:
        if not isinstance(b["deals"], dict):
            raise _bad("`deals` must map deal ids to limits.", 'Send {"deals": {"deal-...": 50}}.')
        known = {r["deal_id"] for r in ctx.conn.execute("SELECT deal_id FROM deals WHERE org_id=?", (ctx.org_id,))}
        for did, v in b["deals"].items():
            if did not in known:
                raise ApiError(404, "not_found", "No such deal.")
            val = _limit_val(v, "deals")
            if val is None:
                cur["deals"].pop(did, None)
            else:
                cur["deals"][did] = val
    with db.tx(ctx.conn):
        s["limits"] = cur
        _save_settings(ctx.conn, ctx.org_id, s)
    ctx.audit("firm.limits.update", f"org:{ctx.org_id}", {"org_monthly_usd": cur["org_monthly_usd"], "deal_usd": cur["deal_usd"], "deal_overrides": len(cur["deals"])})
    return _limits_view(ctx.conn, ctx.org_id)


# =========================================================================== memory (parity 53)
SOURCE_KINDS = ("manual", "job", "document", "email", "agent", "comment")


def _mem_view(r) -> dict:
    link = ""
    if r["source_kind"] == "job" and r["source_ref"]:
        link = f"/runs/{r['source_ref']}"
    elif r["source_kind"] == "document" and r["source_ref"] and r["deal_id"]:
        link = f"/deals/{r['deal_id']}/docs/{r['source_ref']}"
    return {"id": r["id"], "scope": r["scope"], "deal_id": r["deal_id"], "text": r["text"], "source_kind": r["source_kind"],
            "source_ref": r["source_ref"], "source_link": link, "created_by": r["created_by"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "updated_by": r["updated_by"]}


def _get_memory(conn, org_id, mid):
    r = conn.execute("SELECT * FROM memory WHERE org_id=? AND id=?", (org_id, mid)).fetchone()
    if r is None:
        raise ApiError(404, "not_found", "No such memory entry.")
    return r


def list_memory(ctx):
    sql, args = "SELECT * FROM memory WHERE org_id=?", [ctx.org_id]
    if ctx.query.get("scope") in ("org", "deal"):
        sql += " AND scope=?"; args.append(ctx.query["scope"])
    if ctx.query.get("deal_id"):
        sql += " AND deal_id=?"; args.append(ctx.query["deal_id"])
    try:
        lim = max(1, min(200, int(ctx.query.get("limit", 100))))
    except ValueError:
        lim = 100
    rows = ctx.conn.execute(sql + " ORDER BY created_at DESC, id LIMIT ?", args + [lim]).fetchall()
    return {"items": [_mem_view(r) for r in rows], "next_cursor": None}


def create_memory(ctx):
    ctx.require("member")
    b = _body(ctx)
    text = _str(b, "text", 2000, required=True)
    scope = b.get("scope", "org")
    if scope not in ("org", "deal"):
        raise _bad("`scope` must be org or deal.", "org applies to every deal; deal applies to one.")
    deal_id = None
    if scope == "deal":
        deal_id = _str(b, "deal_id", 80, required=True)
        if ctx.conn.execute("SELECT 1 FROM deals WHERE org_id=? AND deal_id=?", (ctx.org_id, deal_id)).fetchone() is None:
            raise ApiError(404, "not_found", "No such deal.")
    kind = b.get("source_kind", "manual")
    if kind not in SOURCE_KINDS:
        raise _bad("Unknown `source_kind`.", f"Use one of: {', '.join(SOURCE_KINDS)}.")
    ref = _str(b, "source_ref", 200)
    mid = db.new_id("mem")
    ts = db.now()
    ctx.conn.execute("INSERT INTO memory(id,org_id,scope,deal_id,text,source_kind,source_ref,created_by,created_at,updated_at,updated_by) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (mid, ctx.org_id, scope, deal_id, text, kind, ref, _name(ctx), ts, ts, _name(ctx)))
    ctx.audit("firm.memory.create", f"memory:{mid}", {"scope": scope, "deal_id": deal_id, "source_kind": kind})
    return 201, _mem_view(_get_memory(ctx.conn, ctx.org_id, mid))


def _own_or_owner(ctx, r) -> None:
    if ctx.role != "owner" and r["created_by"] != _name(ctx):
        raise ApiError(403, "forbidden", "Only an owner or the person who added this entry can change it.",
                       "Ask an owner, or add your own entry instead.")


def patch_memory(ctx):
    ctx.require("member")
    r = _get_memory(ctx.conn, ctx.org_id, ctx.params["memory_id"])
    _own_or_owner(ctx, r)
    b = _body(ctx)
    text = _str(b, "text", 2000, required=True)
    ctx.conn.execute("UPDATE memory SET text=?, updated_at=?, updated_by=? WHERE id=?", (text, db.now(), _name(ctx), r["id"]))
    ctx.audit("firm.memory.update", f"memory:{r['id']}", {"scope": r["scope"]})
    return _mem_view(_get_memory(ctx.conn, ctx.org_id, r["id"]))


def delete_memory(ctx):
    ctx.require("member")
    r = _get_memory(ctx.conn, ctx.org_id, ctx.params["memory_id"])
    _own_or_owner(ctx, r)
    ctx.conn.execute("DELETE FROM memory WHERE id=?", (r["id"],))
    ctx.audit("firm.memory.delete", f"memory:{r['id']}", {"scope": r["scope"]})
    return {"deleted": r["id"]}


# =========================================================================== routes
ROUTES = [
    Route("GET", f"{P}/firm/definitions", get_definitions, "member"),
    Route("PUT", f"{P}/firm/definitions", put_definitions, "owner"),
    Route("POST", f"{P}/firm/definitions/apply", apply_definitions, "owner"),
    Route("GET", f"{P}/firm/assets", list_assets, "member"),
    Route("POST", f"{P}/firm/assets", upload_asset, "owner"),
    Route("PATCH", f"{P}/firm/assets/{{asset_id}}", patch_asset, "owner"),
    Route("DELETE", f"{P}/firm/assets/{{asset_id}}", delete_asset, "owner"),
    Route("GET", f"{P}/firm/assets/{{asset_id}}/file", asset_file, "member"),
    Route("GET", f"{P}/firm/connectors", list_connectors, "member"),
    Route("GET", f"{P}/firm/connectors/kinds", connector_kinds, "member"),
    Route("POST", f"{P}/firm/connectors", create_connector, "owner"),
    Route("PATCH", f"{P}/firm/connectors/{{connector_id}}", patch_connector, "owner"),
    Route("DELETE", f"{P}/firm/connectors/{{connector_id}}", delete_connector, "owner"),
    Route("POST", f"{P}/firm/connectors/{{connector_id}}/test", test_connector, "owner"),
    Route("GET", f"{P}/firm/mailbox", get_mailbox, "member"),
    Route("PUT", f"{P}/firm/mailbox", put_mailbox, "owner"),
    Route("POST", f"{P}/firm/mailbox/test", test_mailbox, "owner"),
    Route("GET", f"{P}/firm/mailbox/log", mailbox_log, "owner"),
    Route("GET", f"{P}/firm/limits", get_limits, "member"),
    Route("PUT", f"{P}/firm/limits", put_limits, "owner"),
    Route("GET", f"{P}/firm/memory", list_memory, "member"),
    Route("POST", f"{P}/firm/memory", create_memory, "member"),
    Route("PATCH", f"{P}/firm/memory/{{memory_id}}", patch_memory, "member"),
    Route("DELETE", f"{P}/firm/memory/{{memory_id}}", delete_memory, "member"),
]
