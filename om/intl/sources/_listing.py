"""Shared reader for exchange disclosure pages (EGX, Tadawul): lists document links, stores facts and links only."""
from __future__ import annotations

import urllib.parse

from .common import Fetcher, extract_links, host_ok, safe_name

DOC_EXTS = (".pdf", ".xlsx", ".xls", ".xbrl", ".xml", ".zip", ".xhtml")
KEYWORDS = ("annual", "financial", "disclosure", "report", "statement", "xbrl")


class ListingSource:
    source = ""
    hosts: tuple = ()
    default_pages: tuple = ()
    min_interval = 2.0

    def __init__(self, replay=False, data_dir=None, fetcher=None, pages=None, min_interval=None, clock=None, sleep=None,
                 urlopen=None, max_items=200):
        self.pages = tuple(pages or self.default_pages)
        self.max_items = max_items
        if min_interval is not None:
            self.min_interval = float(min_interval)
        self.fetcher = fetcher or Fetcher(self.source, self.hosts, min_interval=self.min_interval, replay=replay,
                                          raw_dir=data_dir, clock=clock, sleep=sleep, urlopen=urlopen)

    @staticmethod
    def _kind(url: str, text: str) -> str:
        path = urllib.parse.urlsplit(url).path.lower()
        t = text.lower()
        if "annual" in t or "annual" in path:
            return "annual_report"
        if "financial" in t or "statement" in t or path.endswith((".xbrl", ".xlsx", ".xls")):
            return "financial_statements"
        return "disclosure"

    def list_items(self):
        n, seen = 0, set()
        for page in self.pages:
            r = self.fetcher.get(page)
            _title, links = extract_links(r.body, page)
            for l in links:
                u = urllib.parse.urlsplit(l["url"])
                if l["url"] in seen or not host_ok(u.hostname, self.hosts):
                    continue
                seen.add(l["url"])
                low = (u.path + " " + l["text"]).lower()
                if not (u.path.lower().endswith(DOC_EXTS) or any(k in low for k in KEYWORDS)):
                    continue
                yield {"id": l["url"], "name": safe_name(u.path) or "document",
                       "meta": {"title": l["text"], "kind": self._kind(l["url"], l["text"]), "source_page": page,
                                "page_sha256": r.sha256, "source": self.source}}
                n += 1
                if n >= self.max_items:
                    return

    def fetch(self, item_id: str):
        """Download to data/raw/intl/<source>/ for local extraction. The bytes are never re-hosted."""
        r = self.fetcher.get(item_id, save_as=safe_name(urllib.parse.urlsplit(item_id).path))
        meta = {"name": safe_name(urllib.parse.urlsplit(item_id).path), "source": self.source, **r.record()}
        return r.body, meta
