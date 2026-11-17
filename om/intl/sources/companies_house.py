"""UK Companies House: REST API (key from COMPANIES_HOUSE_API_KEY only, HTTP basic auth, key as username) plus the free
bulk iXBRL accounts (download.companieshouse.gov.uk). 600 requests per 5 minutes is the published limit, so the default
interval is 2 s. Officer and PSC records are minimised to name, role, appointed and resigned dates."""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import quote

from .. import ixbrl
from .common import MIB, Fetcher, NotConfigured, SourceError, extract_links, iter_zip_members, minimise_person

API = "https://api.company-information.service.gov.uk"
DOC_API = "https://document-api.company-information.service.gov.uk"
BULK_PAGE = "https://download.companieshouse.gov.uk/en_accountsdata.html"
ENV_KEY = "COMPANIES_HOUSE_API_KEY"
NUMBER = re.compile(r"^[A-Z0-9]{8}$")


class CompaniesHouseSource:
    source = "companies_house"
    hosts = ("company-information.service.gov.uk", "download.companieshouse.gov.uk")
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, api_key=None, company_numbers=None, min_interval=None,
                 clock=None, sleep=None, urlopen=None, env=None):
        self.replay = replay
        self._key = api_key
        self._env = env if env is not None else os.environ
        self.company_numbers = tuple(company_numbers or (("00000006",) if replay else ()))
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("companies_house", self.hosts, min_interval=self.min_interval, replay=replay,
                                          raw_dir=data_dir, clock=clock, sleep=sleep, urlopen=urlopen, max_bytes=40 * MIB,
                                          redirect_hosts=("amazonaws.com",))

    # ------------------------------------------------------------------ credentials
    def _auth(self) -> dict:
        if self.replay:
            return {}
        key = (self._key or self._env.get(ENV_KEY, "")).strip()
        if not key:
            raise NotConfigured(f"Companies House needs a free API key in the {ENV_KEY} environment variable "
                                "(register at developer.company-information.service.gov.uk); none is set")
        return {"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}

    def _get(self, url, accept=None, **kw):
        h = self._auth()
        if accept:
            h["Accept"] = accept
        return self.fetcher.get(url, headers=h, **kw)

    def _json(self, url):
        r = self._get(url)
        try:
            return json.loads(r.body.decode("utf-8")), r
        except ValueError as e:
            raise SourceError(f"{url}: not JSON") from e

    # ------------------------------------------------------------------ API
    def profile(self, number: str) -> dict:
        n = self._number(number)
        d, r = self._json(f"{API}/company/{n}")
        return {"number": d.get("company_number"), "name": d.get("company_name"), "status": d.get("company_status"),
                "type": d.get("type"), "created": d.get("date_of_creation"), "sic": d.get("sic_codes", []),
                "accounts": (d.get("accounts") or {}).get("last_accounts"), "sha256": r.sha256}

    def officers(self, number: str) -> list[dict]:
        d, _ = self._json(f"{API}/company/{self._number(number)}/officers")
        return [minimise_person(i, role=("officer_role",)) for i in d.get("items", [])]

    def psc(self, number: str) -> list[dict]:
        d, _ = self._json(f"{API}/company/{self._number(number)}/persons-with-significant-control")
        return [minimise_person(i, role=("kind",)) for i in d.get("items", [])]

    @staticmethod
    def _number(n: str) -> str:
        n = str(n).strip().upper()
        if not NUMBER.match(n):
            raise SourceError(f"not a Companies House number: {n!r}")
        return n

    def list_items(self):
        """Accounts filings of the configured company numbers (key required)."""
        self._auth()
        for n in self.company_numbers:
            d, _ = self._json(f"{API}/company/{self._number(n)}/filing-history?category=accounts&items_per_page=25")
            for f in d.get("items", []):
                meta_url = (f.get("links") or {}).get("document_metadata")
                yield {"id": f"{n}/{f['transaction_id']}", "name": f"{n}_{f.get('date', '')}_accounts.xhtml",
                       "version": f.get("transaction_id", ""),
                       "meta": {"company_number": n, "filing_date": f.get("date"), "type": f.get("type"),
                                "description": f.get("description"), "has_document": bool(meta_url), "document_metadata": meta_url}}

    def fetch(self, item_id: str):
        if item_id.startswith("bulk:"):
            return self.fetch_bulk(item_id[5:])
        n, _, tid = item_id.partition("/")
        d, _ = self._json(f"{API}/company/{self._number(n)}/filing-history/{quote(tid)}")
        meta_url = (d.get("links") or {}).get("document_metadata")
        if not meta_url:
            raise SourceError(f"filing {item_id} has no document")
        md, _ = self._json(meta_url)
        res = md.get("resources") or {}
        ctype = "application/xhtml+xml" if "application/xhtml+xml" in res else ("application/pdf" if "application/pdf" in res else None)
        if ctype is None:
            raise SourceError(f"filing {item_id} offers no xhtml or pdf resource")
        r = self._get(meta_url.rstrip("/") + "/content", accept=ctype, save_as=f"{n}_{tid}.{'xhtml' if 'xhtml' in ctype else 'pdf'}")
        route = "ixbrl" if "xhtml" in ctype else "pdf"
        return r.body, {"name": f"{n}_{tid}", "source": "companies_house", "content_type": ctype, "route": route, **r.record()}

    def statements(self, item_id: str) -> dict:
        body, meta = self.fetch(item_id)
        if meta["route"] != "ixbrl":
            raise SourceError("this filing is a PDF: route it with route_pdf_accounts()")
        return ixbrl.to_statements(ixbrl.parse_ixbrl(body))

    # ------------------------------------------------------------------ bulk iXBRL accounts (no key needed)
    def list_bulk(self):
        r = self.fetcher.get(BULK_PAGE)
        _t, links = extract_links(r.body, BULK_PAGE)
        for l in links:
            m = re.search(r"(Accounts_(?:Bulk|Monthly)_Data-[A-Za-z0-9-]+\.zip)$", l["url"])
            if m:
                yield {"id": "bulk:" + m.group(1), "name": m.group(1), "meta": {"url": l["url"], "kind": "bulk_ixbrl"}}

    def fetch_bulk(self, name: str):
        if not re.fullmatch(r"Accounts_(?:Bulk|Monthly)_Data-[A-Za-z0-9-]+\.zip", name):
            raise SourceError(f"not a Companies House bulk file name: {name!r}")
        url = f"https://download.companieshouse.gov.uk/{name}"
        r = self.fetcher.download(url, name)
        manifest = json.dumps({"file": name, "url": url, "sha256": r.sha256, "bytes": r.size, "saved_path": r.saved_path}).encode()
        return manifest, {"name": name, "source": "companies_house", "route": "bulk_ixbrl", **r.record()}

    @staticmethod
    def parse_bulk(zip_path, limit=None):
        """Yield (member name, statements dict) for each iXBRL accounts file in a bulk zip."""
        for i, (name, body) in enumerate(iter_zip_members(zip_path, (".html", ".xhtml", ".htm"))):
            if limit is not None and i >= limit:
                return
            yield name, ixbrl.to_statements(ixbrl.parse_ixbrl(body))
