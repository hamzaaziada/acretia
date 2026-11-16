"""Thin Connector wrapper over om/connectors.py listers (S2.5): SharePoint (Graph), Box, Dropbox and any synced folder
(Google Drive for desktop, OneDrive, Box Drive). om/connectors has no native Google Drive API lister: use
`synced_folder` pointed at the Drive-for-desktop mount. Tokens come from the environment (`token_env`), never config."""
from __future__ import annotations

from om import connectors as _om

from .base import Connector, ConnectorError, ConnectorItem, register


class DriveConnector(Connector):
    def __init__(self, type: str, http=None, **cfg):
        if type not in _om.LISTERS:
            raise ConnectorError(f"drive type must be one of {sorted(_om.LISTERS)}")
        for k in ("token", "access_token", "password", "secret"):
            if k in cfg:
                raise ConnectorError("don't put credentials in connector config; use token_env and the environment")
        self.name = type
        cfg["type"] = type
        cfg.setdefault("token_env", {"box": "BOX_ACCESS_TOKEN", "sharepoint": "MS_GRAPH_TOKEN",
                                     "dropbox": "DROPBOX_ACCESS_TOKEN"}.get(type, ""))
        self.cfg = cfg
        self._http = http
        self._fetchers: dict = {}

    def _client(self):
        if self._http is None:
            self._http = _om.HTTP(_om._token(self.cfg) if self.cfg["type"] != "synced_folder" else None)
        return self._http

    def list(self):
        for item_id, rel, version, size, fetch in _om.LISTERS[self.cfg["type"]](self.cfg, self._client()):
            self._fetchers[item_id] = (rel, fetch)
            yield ConnectorItem(item_id, rel, int(size or 0), str(version or ""))

    def fetch(self, item_id: str):
        if item_id not in self._fetchers:
            raise ConnectorError(f"unknown item {item_id!r}; call list() first")
        rel, fn = self._fetchers[item_id]
        return fn(), {"name": rel, "source": self.name}


def _factory(t):
    return lambda **cfg: DriveConnector(t, **cfg)


for _t in ("synced_folder", "sharepoint", "box", "dropbox"):
    register(_t, _factory(_t))
