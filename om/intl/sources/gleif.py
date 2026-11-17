"""GLEIF LEI lookup: the cross-registry entity-resolution spine. Terms: CC0 for LEI data (gleif.org LEI Data Terms of
Use, reviewed 2026-11-17). `resolve(name | lei | reg_id)` returns one legal entity with the registries it appears in:
GLEIF itself plus the national business register named by its `registeredAt` authority code, mapped to our connector
(Companies House, KvK, INPI/Sirene, Brønnøysund, CRO). Addresses and other fields are not kept."""
from __future__ import annotations

import json
import re
import urllib.parse

from .common import Fetcher, SourceError

API = "https://api.gleif.org/api/v1"
LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
# GLEIF registration-authority code -> (our connector, register name). Codes confirmed against api.gleif.org 2026-11-17.
AUTHORITIES = {
    "RA000585": ("companies_house", "UK Companies House"),
    "RA000463": ("kvk", "NL KvK Business Register"),
    "RA000189": ("inpi", "FR Sirene / RNE"),
    "RA000472": ("bronnoysund", "NO Register of Business Enterprises"),
    "RA000402": ("cro", "IE Companies Registration Office"),
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def entity_from_record(rec: dict) -> dict:
    a = rec["attributes"]
    e = a["entity"]
    ra, rid = (e.get("registeredAt") or {}).get("id"), e.get("registeredAs")
    regs = [{"registry": "gleif", "id": a["lei"], "name": "GLEIF Global LEI Index"}]
    if ra:
        conn, rname = AUTHORITIES.get(ra, (None, ra))
        regs.append({"registry": conn or "other", "authority": ra, "name": rname,
                     "id": re.sub(r"\s", "", rid) if conn in ("bronnoysund", "inpi") and rid else rid})
    out = {"lei": a["lei"], "legal_name": (e.get("legalName") or {}).get("name"), "jurisdiction": e.get("jurisdiction"),
           "entity_status": e.get("status"), "legal_form": (e.get("legalForm") or {}).get("id"), "registries": regs,
           "esef_lookup_key": a["lei"]}
    out["links"] = {r["registry"]: r["id"] for r in regs if r["registry"] not in ("other",)}
    return out


class GleifSource:
    source = "gleif"
    hosts = ("api.gleif.org",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, leis=None, min_interval=None, clock=None, sleep=None,
                 urlopen=None):
        self.leis = tuple(leis or ())
        self.replay = replay
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("gleif", self.hosts, min_interval=self.min_interval, replay=replay, raw_dir=data_dir,
                                          clock=clock, sleep=sleep, urlopen=urlopen)

    def _records(self, **flt) -> list:
        q = urllib.parse.urlencode({f"filter[{k}]": v for k, v in flt.items()} | {"page[size]": "10"})
        d, _ = self.fetcher.get_json(f"{API}/lei-records?{q}")
        return d.get("data", [])

    def resolve(self, query: str, authority: str | None = None) -> dict:
        """query = LEI, registry number (give `authority` to narrow it) or legal name."""
        query = query.strip()
        if LEI.match(query.upper()):
            d, _ = self.fetcher.get_json(f"{API}/lei-records/{query.upper()}")
            recs = [d["data"]] if isinstance(d.get("data"), dict) else d.get("data", [])
        elif authority or re.fullmatch(r"[0-9A-Za-z .-]{3,20}", query) and any(c.isdigit() for c in query):
            flt = {"entity.registeredAs": query}
            if authority:
                flt["entity.registeredAt.id"] = authority
            recs = self._records(**flt)
        else:
            recs = self._records(**{"entity.legalName": query})
        ents = [entity_from_record(r) for r in recs]
        exact = [e for e in ents if _norm(e["legal_name"]) == _norm(query)]
        pick = exact or ents
        if not pick:
            return {"status": "not_found", "query": query}
        if len(pick) > 1:
            return {"status": "ambiguous", "query": query, "candidates": pick}
        return {"status": "resolved", "query": query, **pick[0]}

    def list_items(self):
        leis = self.leis or (("213800LH1BZH3DI6G760",) if self.replay else ())
        for lei in leis:
            r = self.resolve(lei)
            if r["status"] == "resolved":
                yield {"id": r["lei"], "name": f"{r['lei']}.json", "meta": {"legal_name": r["legal_name"], "registries": r["registries"]}}

    def fetch(self, item_id: str):
        r = self.resolve(item_id)
        if r["status"] != "resolved":
            raise SourceError(f"LEI {item_id}: {r['status']}")
        body = json.dumps(r, ensure_ascii=False, sort_keys=True).encode()
        return body, {"name": f"{item_id}.json", "source": "gleif", "licence": "CC0", "registries": r["registries"]}
