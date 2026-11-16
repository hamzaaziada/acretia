"""Data-room connectors: keep a room in sync with where the deal documents live.

  synced_folder   any folder on disk: Box Drive, OneDrive/SharePoint sync, Dropbox, Google Drive for desktop,
                  or an unzipped VDR export. No credentials needed.
  box             Box API (folder id). Token from env var (developer token or OAuth access token).
  sharepoint      Microsoft Graph: SharePoint document library or OneDrive folder (drive id + folder path,
                  or a sharing link). Token from env var (OAuth access token with Files.Read.All / Sites.Read.All).
  dropbox         Dropbox API (folder path). Token from env var.

Datasite, Intralinks, Ansarada, Firmex and DealRoom only offer APIs through partner agreements; their
bulk ZIP export (which keeps the index-numbered folder tree) imports directly with `room import`.

Tokens are never stored: a connector's config names the environment variable that holds the token.
Sync downloads only items whose remote version changed since the last sync (state kept per item).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

from .net import fetch_bytes
from .rooms import ImportResult, Rooms

TYPES = ("synced_folder", "box", "sharepoint", "dropbox")


class HTTP:
    """Tiny JSON/bytes client; injectable for tests."""

    def __init__(self, token: str | None = None):
        self.token = token

    def _h(self, extra=None):
        h = {"User-Agent": "OpenMultiples/0.1"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return {**h, **(extra or {})}

    def get_json(self, url: str) -> dict:
        return json.loads(fetch_bytes(url, self._h({"Accept": "application/json"})))

    def get_bytes(self, url: str, headers: dict | None = None) -> bytes:
        return fetch_bytes(url, self._h(headers), timeout=300)

    def post_json(self, url: str, body: dict | None, headers: dict | None = None, raw: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        h = self._h({"Content-Type": "application/json"} if body is not None else {})
        h.update(headers or {})
        with urllib.request.urlopen(urllib.request.Request(url, data=data or b"", headers=h, method="POST"), timeout=300) as r:
            out = r.read()
        return out if raw else json.loads(out)


def _token(cfg: dict) -> str:
    env = cfg.get("token_env")
    tok = os.environ.get(env or "")
    if not tok:
        raise SystemExit(f"{cfg['type']} connector needs an access token in the environment variable {env!r} (.env)")
    return tok


# --------------------------------------------------------------------------- item listing per provider
# each yields (item_id, relative_path, version, size, fetch_fn)

def _list_folder(cfg: dict, http=None):
    base = Path(cfg["path"]).expanduser()
    if not base.is_dir():
        raise SystemExit(f"folder not found: {base}")
    for f in sorted(base.rglob("*")):
        if f.is_file():
            st = f.stat()
            yield str(f.relative_to(base)), str(f.relative_to(base)), f"{st.st_mtime_ns}:{st.st_size}", st.st_size, f.read_bytes


def _list_box(cfg: dict, http: HTTP):
    api = "https://api.box.com/2.0"

    def walk(folder_id: str, prefix: str):
        offset = 0
        while True:
            j = http.get_json(f"{api}/folders/{folder_id}/items?fields=id,type,name,size,modified_at,sha1,etag&limit=1000&offset={offset}")
            for e in j.get("entries", []):
                rel = f"{prefix}{e['name']}"
                if e["type"] == "folder":
                    yield from walk(e["id"], rel + "/")
                elif e["type"] == "file":
                    yield (f"box:{e['id']}", rel, e.get("sha1") or e.get("etag") or e.get("modified_at"), e.get("size") or 0,
                           (lambda fid=e["id"]: http.get_bytes(f"{api}/files/{fid}/content")))
            offset += len(j.get("entries", []))
            if offset >= j.get("total_count", 0) or not j.get("entries"):
                break
    yield from walk(str(cfg.get("folder_id", "0")), "")


def _list_sharepoint(cfg: dict, http: HTTP):
    g = "https://graph.microsoft.com/v1.0"
    if cfg.get("share_url"):
        enc = "u!" + base64.urlsafe_b64encode(cfg["share_url"].encode()).decode().rstrip("=")
        root = http.get_json(f"{g}/shares/{enc}/driveItem")
        drive_id, item_id = root["parentReference"]["driveId"], root["id"]
    else:
        drive_id = cfg["drive_id"]
        path = cfg.get("folder", "").strip("/")
        root = http.get_json(f"{g}/drives/{drive_id}/root" + (f":/{urllib.parse.quote(path)}" if path else ""))
        item_id = root["id"]

    def walk(iid: str, prefix: str):
        url = f"{g}/drives/{drive_id}/items/{iid}/children?$top=999&$select=id,name,size,eTag,lastModifiedDateTime,folder,file"
        while url:
            j = http.get_json(url)
            for e in j.get("value", []):
                rel = f"{prefix}{e['name']}"
                if "folder" in e:
                    yield from walk(e["id"], rel + "/")
                elif "file" in e:
                    yield (f"graph:{e['id']}", rel, e.get("eTag") or e.get("lastModifiedDateTime"), e.get("size") or 0,
                           (lambda fid=e["id"]: http.get_bytes(f"{g}/drives/{drive_id}/items/{fid}/content")))
            url = j.get("@odata.nextLink")
    yield from walk(item_id, "")


def _list_dropbox(cfg: dict, http: HTTP):
    api, content = "https://api.dropboxapi.com/2", "https://content.dropboxapi.com/2"
    root = cfg.get("path", "").rstrip("/")
    j = http.post_json(f"{api}/files/list_folder", {"path": root, "recursive": True, "limit": 2000})
    while True:
        for e in j.get("entries", []):
            if e.get(".tag") != "file":
                continue
            rel = e["path_display"][len(root):].lstrip("/") if root else e["path_display"].lstrip("/")
            arg = json.dumps({"path": e["id"]})
            yield (f"dropbox:{e['id']}", rel, e.get("content_hash") or e.get("rev"), e.get("size") or 0,
                   (lambda a=arg: http.post_json(f"{content}/files/download", None, {"Dropbox-API-Arg": a}, raw=True)))
        if not j.get("has_more"):
            break
        j = http.post_json(f"{api}/files/list_folder/continue", {"cursor": j["cursor"]})


LISTERS: dict[str, Callable] = {"synced_folder": _list_folder, "box": _list_box, "sharepoint": _list_sharepoint, "dropbox": _list_dropbox}


# --------------------------------------------------------------------------- connector management + sync
def add_connector(rooms: Rooms, room_id: int, cfg: dict) -> dict:
    if cfg.get("type") not in TYPES:
        raise ValueError(f"connector type must be one of {TYPES}")
    if cfg["type"] != "synced_folder" and not cfg.get("token_env"):
        cfg["token_env"] = {"box": "BOX_ACCESS_TOKEN", "sharepoint": "MS_GRAPH_TOKEN", "dropbox": "DROPBOX_ACCESS_TOKEN"}[cfg["type"]]
    for k in ("token", "access_token", "password", "secret"):
        if k in cfg:
            raise ValueError("don't put credentials in the connector config; use token_env and .env")
    conns = json.loads(rooms.get(room_id)["connectors"] or "[]")
    cfg["id"] = max([c.get("id", 0) for c in conns] + [0]) + 1
    cfg["state"] = {}
    conns.append(cfg)
    rooms.db.execute("UPDATE rooms SET connectors=? WHERE id=?", (json.dumps(conns), room_id))
    rooms.db.commit()
    return cfg


def connectors(rooms: Rooms, room_id: int) -> list[dict]:
    return [{k: v for k, v in c.items() if k != "state"} | {"items_tracked": len(c.get("state", {}))}
            for c in json.loads(rooms.get(room_id)["connectors"] or "[]")]


def sync(rooms: Rooms, room_id: int, connector_id: int | None = None, http_factory=None, progress=None) -> dict:
    conns = json.loads(rooms.get(room_id)["connectors"] or "[]")
    results = {}
    for cfg in conns:
        if connector_id and cfg["id"] != connector_id:
            continue
        http = (http_factory or (lambda c: HTTP(_token(c) if c["type"] != "synced_folder" else None)))(cfg)
        state = cfg.setdefault("state", {})
        res = ImportResult(warnings=[])
        seen = set()
        n = 0
        for item_id, rel, version, size, fetch in LISTERS[cfg["type"]](cfg, http):
            seen.add(item_id)
            if state.get(item_id) == version:
                res.unchanged += 1
                continue
            try:
                rooms.add_file(room_id, rel, fetch(), source=cfg["type"], res=res)
                state[item_id] = version
            except Exception as e:  # one bad file doesn't stop the sync
                res.failed += 1
                res.warnings.append(f"{rel}: {e!r:.160}")
            n += 1
            if progress and n % 10 == 0:
                progress(n)
        removed = [k for k in state if k not in seen]
        for k in removed:  # remote deletions are reported, not auto-deleted (a VDR revoking access shouldn't wipe work)
            state.pop(k)
        out = res.as_dict()
        out["removed_remotely"] = len(removed)
        results[cfg["id"]] = out
        rooms.log(room_id, "sync", {"connector": cfg["id"], "type": cfg["type"], **{k: out[k] for k in ("added", "updated", "unchanged", "failed")}})
    rooms.db.execute("UPDATE rooms SET connectors=? WHERE id=?", (json.dumps(conns), room_id))
    rooms.db.commit()
    return results
