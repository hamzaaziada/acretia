"""SEC EDGAR client: rate-limited, disk-cached, stdlib only.

Endpoints (all free, US-government data):
  https://www.sec.gov/files/company_tickers_exchange.json   ticker -> CIK map (needs contact UA)
  https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
  https://data.sec.gov/submissions/CIK##########.json
  https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip   nightly bulk (~1 GB+)
SEC fair-access policy: max 10 requests/second and a User-Agent that identifies you with a contact email.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .net import fetch_bytes

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
BULK_FACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"


class SecClient:
    def __init__(self, user_agent: str, cache_dir: Path, max_rps: float = 8.0, ttl_hours: float = 20.0):
        if not user_agent or "@" not in user_agent:
            # data.sec.gov tolerates a generic UA, www.sec.gov does not; SEC policy asks for an email.
            self.ua_ok = False
        else:
            self.ua_ok = True
        self.ua = user_agent or "Acretia/0.1 (research prototype)"
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_gap = 1.0 / max_rps
        self.ttl = ttl_hours * 3600
        self._lock = threading.Lock()
        self._last = 0.0

    # --------------------------------------------------------------- low level
    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.min_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    def _get(self, url: str, timeout: int = 60) -> bytes:
        for attempt in range(5):
            self._throttle()
            try:
                return fetch_bytes(url, {"User-Agent": self.ua}, timeout=timeout)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise FileNotFoundError(url)
                if e.code == 403 and "www.sec.gov" in url and not self.ua_ok:
                    raise SystemExit("SEC refused the request: set SEC_USER_AGENT in .env to "
                                     "'<Your name or org> <contact email>' (SEC fair-access policy).")
                if e.code in (403, 429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as e:
                if attempt < 4:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise RuntimeError(f"{url}: {e}")
        raise RuntimeError(f"{url}: retries exhausted")

    def get_json(self, url: str, cache_name: str, max_age: float | None = None) -> dict:
        """Fetch JSON, keeping the raw bytes (gzipped) plus a SHA-256 in the raw document store."""
        path = self.cache / f"{cache_name}.json.gz"
        max_age = self.ttl if max_age is None else max_age
        if path.exists() and time.time() - path.stat().st_mtime < max_age:
            with gzip.open(path, "rb") as fh:
                return json.loads(fh.read())
        for attempt in range(3):
            raw = self._get(url)
            try:
                parsed = json.loads(raw)
                break
            except json.JSONDecodeError:
                if attempt == 2:
                    raise RuntimeError(f"{url}: response was not complete JSON after 3 tries")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(raw)
        tmp.replace(path)
        meta = {"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        path.with_name(path.name.replace(".json.gz", ".meta.json")).write_text(json.dumps(meta))
        return parsed

    def get_text(self, url: str, cache_name: str) -> str:
        """Fetch a filing document (HTML/text), cached forever: filed documents never change."""
        path = self.cache / f"{cache_name}.gz"
        if path.exists():
            with gzip.open(path, "rb") as fh:
                return fh.read().decode("utf-8", "ignore")
        raw = self._get(url, timeout=120)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wb") as fh:
            fh.write(raw)
        return raw.decode("utf-8", "ignore")

    # --------------------------------------------------------------- endpoints
    def tickers(self) -> list[dict]:
        j = self.get_json(TICKERS_URL, "company_tickers_exchange")
        f = j["fields"]
        return [dict(zip(f, row)) for row in j["data"]]

    def companyfacts(self, cik: int, bulk: Path | None = None) -> dict:
        if bulk and bulk.exists():
            with zipfile.ZipFile(bulk) as z:
                name = f"CIK{cik:010d}.json"
                if name in z.namelist():
                    return json.loads(z.read(name))
        return self.get_json(FACTS_URL.format(cik=cik), f"companyfacts/CIK{cik:010d}")

    def submissions(self, cik: int) -> dict:
        return self.get_json(SUBMISSIONS_URL.format(cik=cik), f"submissions/CIK{cik:010d}")

    def download_bulk_facts(self, dest: Path) -> Path:
        """Stream the nightly companyfacts.zip (SEC rebuilds it ~03:00 ET)."""
        if not self.ua_ok:
            raise SystemExit("Set SEC_USER_AGENT (with a contact email) before bulk downloads.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._throttle()
        req = urllib.request.Request(BULK_FACTS_URL, headers={"User-Agent": self.ua})
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  companyfacts.zip {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
        print()
        tmp.replace(dest)
        return dest
