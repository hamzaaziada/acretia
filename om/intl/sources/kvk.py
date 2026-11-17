"""Netherlands KvK open dataset of annual accounts (bulk zips). Licence: data.overheid.nl lists CC-0 1.0 (the KvK page
and desk research said CC-BY 4.0); we attribute KvK either way. We list and download the bulk zips to
data/raw/intl/kvk/ and keep facts and hashes. The XML schema is [UNKNOWN], so no figures are parsed here."""
from __future__ import annotations

import json
import re

from .common import Fetcher, extract_links, safe_name

PAGE = "https://www.kvk.nl/en/ordering-products/kvk-financial-statements-open-data-set/"


class KvkSource:
    source = "kvk"
    hosts = ("kvk.nl",)
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, min_interval=None, clock=None, sleep=None, urlopen=None):
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher("kvk", self.hosts, min_interval=self.min_interval, replay=replay, raw_dir=data_dir,
                                          clock=clock, sleep=sleep, urlopen=urlopen)

    def list_items(self):
        r = self.fetcher.get(PAGE)
        _t, links = extract_links(r.body, PAGE)
        for l in links:
            if re.search(r"/download/kvk-open-data-set-jaarrekeningen\d+\.zip$", l["url"]):
                yield {"id": l["url"], "name": safe_name(l["url"]),
                       "meta": {"licence": "CC-0 1.0 (data.overheid.nl); attribute KvK", "kind": "bulk_annual_accounts"}}

    def fetch(self, item_id: str):
        r = self.fetcher.download(item_id, safe_name(item_id))
        body = json.dumps({"url": item_id, "sha256": r.sha256, "bytes": r.size, "saved_path": r.saved_path}).encode()
        return body, {"name": safe_name(item_id), "source": "kvk", **r.record()}
