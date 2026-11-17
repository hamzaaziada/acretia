"""Ireland CRO open data portal (CKAN, CC BY 4.0): financial-statement submission records. The CRO sells the images of
the statements (from EUR 2.50), so we keep the record (company number, name, accounts date, file name) and never fetch the
document. Company address and contact fields are not kept."""
from __future__ import annotations

import json
import urllib.parse

from .common import Fetcher, SourceError

API = "https://opendata.cro.ie/api/3/action"
RESOURCE_2024 = "4dc79788-845b-4373-aaf9-77be6feb049b"      # financial_statements_2024.csv datastore


class CroSource:
    source = "cro"
    hosts = ("opendata.cro.ie",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, query=None, resource_id=RESOURCE_2024, limit=50,
                 min_interval=None, clock=None, sleep=None, urlopen=None):
        self.query, self.resource_id, self.limit = query, resource_id, limit
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("cro", self.hosts, min_interval=self.min_interval, replay=replay, raw_dir=data_dir,
                                          clock=clock, sleep=sleep, urlopen=urlopen)

    def _records(self, **extra) -> list:
        q = {"resource_id": self.resource_id, "limit": self.limit, **extra}
        if self.query:
            q["q"] = self.query
        d, _ = self.fetcher.get_json(f"{API}/datastore_search?{urllib.parse.urlencode(q)}")
        if not d.get("success"):
            raise SourceError("CRO datastore_search was not successful")
        return d["result"]["records"]

    @staticmethod
    def _fact(r: dict) -> dict:
        return {"company_number": r.get("company_num"), "company_name": r.get("company_name"), "file_name": r.get("file_name"),
                "submission": r.get("submission_num"), "received": r.get("submission_rec_date"),
                "accounts_to": r.get("submissions_accounts_to_date")}

    def list_items(self):
        for r in self._records():
            yield {"id": str(r.get("file_name")), "name": f"{r.get('company_num')}_{r.get('submissions_accounts_to_date', '')[:10]}.json",
                   "meta": {**self._fact(r), "document": "paid image at CRO; not fetched"}}

    def fetch(self, item_id: str):
        for r in self._records(filters=json.dumps({"file_name": item_id})):
            if str(r.get("file_name")) == item_id:
                body = json.dumps(self._fact(r), sort_keys=True).encode()
                return body, {"name": f"{item_id}.json", "source": "cro", "licence": "CC BY 4.0", "bytes": len(body)}
        raise SourceError(f"CRO record {item_id} not found")
