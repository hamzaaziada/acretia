"""Norway Brønnøysund Register Centre: Regnskapsregisteret JSON API (open, no key). The API is a preview that may
change or be withdrawn without notice, so the connector is marked fragile and turns any surprise into a clear error."""
from __future__ import annotations

import json
import re

from .common import Fetcher, SourceError

API = "https://data.brreg.no/regnskapsregisteret/regnskap"
ORGNR = re.compile(r"^\d{9}$")


class BronnoysundSource:
    source = "bronnoysund"
    fragile = True
    hosts = ("data.brreg.no",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, org_numbers=None, min_interval=None, clock=None, sleep=None,
                 urlopen=None):
        self.org_numbers = tuple(org_numbers or (("923609016",) if replay else ()))
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("bronnoysund", self.hosts, min_interval=self.min_interval, replay=replay,
                                          raw_dir=data_dir, clock=clock, sleep=sleep, urlopen=urlopen)

    def _accounts(self, org: str) -> list:
        org = org.replace(" ", "")
        if not ORGNR.match(org):
            raise SourceError(f"not a Norwegian organisation number: {org!r}")
        try:
            d, _ = self.fetcher.get_json(f"{API}/{org}")
        except SourceError as e:
            raise SourceError(f"Brønnøysund accounts API failed (fragile preview API, may have changed): {e}") from e
        if not isinstance(d, list):
            raise SourceError("Brønnøysund accounts API changed shape (expected a list); it is a fragile preview API")
        return d

    def list_items(self):
        for org in self.org_numbers:
            for a in self._accounts(org):
                p = a.get("regnskapsperiode") or {}
                yield {"id": f"{org}/{a.get('id')}", "name": f"{org}_{p.get('tilDato', '')}_{a.get('regnskapstype', '')}.json",
                       "meta": {"org_number": org, "period_end": p.get("tilDato"), "currency": a.get("valuta"),
                                "basis": (a.get("regnkapsprinsipper") or {}).get("regnskapsregler"), "type": a.get("regnskapstype"),
                                "fragile": True}}

    def fetch(self, item_id: str):
        org, _, rid = item_id.partition("/")
        for a in self._accounts(org):
            if str(a.get("id")) == rid:
                body = json.dumps(a, ensure_ascii=False, sort_keys=True).encode()
                return body, {"name": f"{org}_{rid}.json", "source": "bronnoysund", "fragile": True, "bytes": len(body)}
        raise SourceError(f"accounts {item_id} not found")
