"""France INPI RNE: non-confidential annual accounts (bilans). Credentials from INPI_RNE_USERNAME / INPI_RNE_PASSWORD
only. The endpoint shapes below follow the published RNE API as best known and are [UNKNOWN] until checked against a
live account; confidential accounts are never listed or fetched. Accounts arrive as PDFs: route them with
route_pdf_accounts()."""
from __future__ import annotations

import json
import os
import re

from .common import Fetcher, NotConfigured, SourceError

API = "https://registre-national-entreprises.inpi.fr/api"
SIREN = re.compile(r"^\d{9}$")


class InpiSource:
    source = "inpi"
    hosts = ("registre-national-entreprises.inpi.fr",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, sirens=None, min_interval=None, clock=None, sleep=None,
                 urlopen=None, env=None):
        self.replay, self._env = replay, (env if env is not None else os.environ)
        self.sirens = tuple(sirens or (("552100554",) if replay else ()))
        self._token = None
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("inpi", self.hosts, min_interval=self.min_interval, replay=replay, raw_dir=data_dir,
                                          clock=clock, sleep=sleep, urlopen=urlopen)

    def _headers(self) -> dict:
        if self.replay:
            return {}
        if self._token is None:
            user, pw = self._env.get("INPI_RNE_USERNAME", ""), self._env.get("INPI_RNE_PASSWORD", "")
            if not user or not pw:
                raise NotConfigured("INPI RNE needs INPI_RNE_USERNAME and INPI_RNE_PASSWORD in the environment; none is set")
            d, _ = self.fetcher.get_json(f"{API}/sso/login", method="POST", data=json.dumps({"username": user, "password": pw}).encode(),
                                         headers={"Content-Type": "application/json"})
            self._token = d.get("token")
            if not self._token:
                raise SourceError("INPI login returned no token")
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _public(b: dict) -> bool:
        return not b.get("confidentiel") and str(b.get("confidentialite", "")).strip().lower() in ("", "public", "non confidentiel")

    def list_items(self):
        h = self._headers()
        for s in self.sirens:
            if not SIREN.match(s):
                raise SourceError(f"not a SIREN: {s!r}")
            d, _ = self.fetcher.get_json(f"{API}/companies/{s}/attachments", headers=h)
            for b in d.get("bilans", []):
                if self._public(b):
                    yield {"id": f"{s}/{b['id']}", "name": f"{s}_{b.get('dateCloture', '')}_bilan.pdf",
                           "meta": {"siren": s, "closing_date": b.get("dateCloture"), "filed": b.get("dateDepot"), "route": "pdf"}}

    def fetch(self, item_id: str):
        s, _, bid = item_id.partition("/")
        if not SIREN.match(s) or not re.fullmatch(r"[A-Za-z0-9_-]+", bid):
            raise SourceError(f"bad INPI item id {item_id!r}")
        r = self.fetcher.get(f"{API}/bilans/{bid}/download", headers=self._headers(), save_as=f"{s}_{bid}.pdf")
        return r.body, {"name": f"{s}_{bid}.pdf", "source": "inpi", "route": "pdf", **r.record()}
