"""ESEF / UK IFRS filings via the filings.xbrl.org JSON:API (list by country, LEI or period; fetch xBRL-JSON or the
report package). The filings are public regulatory filings; the site shows "(c) XBRL" and states no API licence, so we
keep facts and links, honour robots.txt (it allows all) and fetch politely."""
from __future__ import annotations

import json
import re
import urllib.parse

from .. import ixbrl
from .common import MIB, Fetcher, SourceError

BASE = "https://filings.xbrl.org"
KINDS = {"json": "json_url", "package": "package_url", "report": "report_url", "viewer": "viewer_url"}


def filings_url(country=None, lei=None, period_end=None, limit=20, page=1) -> str:
    flt = []
    if country:
        flt.append({"name": "country", "op": "eq", "val": country.upper()})
    if lei:
        flt.append({"name": "fxo_id", "op": "like", "val": f"{lei}-%"})
    if period_end:
        flt.append({"name": "period_end", "op": "eq", "val": period_end})
    q = [("page[size]", str(limit)), ("sort", "-date_added")]
    if page > 1:
        q.append(("page[number]", str(page)))
    if flt:
        q.insert(0, ("filter", json.dumps(flt, separators=(",", ":"))))
    return f"{BASE}/api/filings?{urllib.parse.urlencode(q)}"


class EsefSource:
    source = "esef"
    hosts = ("filings.xbrl.org",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, country=None, lei=None, period_end=None, limit=20,
                 min_interval=None, clock=None, sleep=None, urlopen=None):
        self.query = dict(country=country, lei=lei, period_end=period_end, limit=limit)
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("esef", self.hosts, min_interval=self.min_interval, replay=replay, raw_dir=data_dir,
                                          clock=clock, sleep=sleep, urlopen=urlopen, max_bytes=64 * MIB)

    @staticmethod
    def _abs(path):
        return urllib.parse.urljoin(BASE + "/", path) if path else None

    def _item(self, d: dict) -> dict:
        a = d["attributes"]
        m = re.match(r"(.+?)-\d{4}-\d{2}-\d{2}-", a.get("fxo_id", ""))
        return {"id": str(d["id"]), "name": f"{a.get('fxo_id', d['id'])}.json", "version": a.get("sha256", ""),
                "meta": {"entity_id": m.group(1) if m else None, "country": a.get("country"), "period_end": a.get("period_end"),
                         "fxo_id": a.get("fxo_id"), "date_added": a.get("date_added"), "errors": a.get("error_count"),
                         **{k: self._abs(a.get(v)) for k, v in KINDS.items()}}}

    def list_items(self):
        data, _ = self.fetcher.get_json(filings_url(**self.query))
        for d in data.get("data", []):
            yield self._item(d)

    def filing(self, filing_id: str) -> dict:
        data, _ = self.fetcher.get_json(f"{BASE}/api/filings/{filing_id}")
        return self._item(data["data"])

    def fetch(self, item_id: str, kind: str = "json"):
        """item_id is the filing id, optionally '<id>#package|#report|#json'."""
        fid, _, frag = item_id.partition("#")
        kind = frag or kind
        if kind not in KINDS:
            raise SourceError(f"unknown ESEF artefact {kind!r}; use one of {sorted(KINDS)}")
        it = self.filing(fid)
        url = it["meta"].get(kind)
        if not url:
            raise SourceError(f"filing {fid} has no {kind}")
        r = self.fetcher.get(url, save_as=f"{fid}_{kind}_{url.rsplit('/', 1)[-1]}")
        return r.body, {"name": url.rsplit("/", 1)[-1], "source": "esef", "kind": kind, **it["meta"], **r.record()}

    def statements(self, filing_id: str) -> dict:
        body, meta = self.fetch(filing_id, "json")
        out = ixbrl.to_statements(ixbrl.parse_xbrl_json(body))
        out["meta"] = {k: meta.get(k) for k in ("fxo_id", "period_end", "country", "sha256")}
        return out
