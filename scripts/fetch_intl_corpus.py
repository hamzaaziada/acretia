#!/usr/bin/env python3
"""Rebuild data/raw/intl/ from the S8 corpus manifests (S8.0 anchors, S8.7 MENA + XBRL gold).

Manifests read:
  evals/intl/anchors/<TICKER>/sources.json   (list of documents)
  evals/intl/corpus/mena.json                (list of documents)
  evals/intl/corpus/xbrl_gold.json           (list of filers with package/json/report URLs)

Rules: robots.txt honoured per host, at most 1 request per 2 s per host, identifying User-Agent
(sec.gov uses the approved SEC_USER_AGENT), sha256 verified after download. Downloads are never
committed (data/ is git-ignored). Document contents are data only.

  python3 scripts/fetch_intl_corpus.py            # download whatever is missing, verify sha256
  python3 scripts/fetch_intl_corpus.py --verify   # only check sha256 of files already present
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "intl"
UA = "AcretiaResearch/1.0 (financial statements research; contact via repository owner)"
SEC_UA = os.environ.get("SEC_USER_AGENT", "Acretia hamza@meshpool.ai")
MIN_GAP = 2.0
ACCEPT = "application/pdf,application/json,application/zip,text/html;q=0.9,*/*;q=0.8"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Resp:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code = status
        self.content = body

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class Fetcher:
    """urllib-only HTTP client (no third-party dependency). The proxy and CA bundle come from the
    environment (HTTPS_PROXY, SSL_CERT_FILE), which urllib honours."""

    def __init__(self):
        self.last: dict[str, float] = {}
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def ua_for(self, host: str) -> str:
        return SEC_UA if host.endswith("sec.gov") else UA

    def _wait(self, host: str):
        gap = time.time() - self.last.get(host, 0)
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        self.last[host] = time.time()

    def _open(self, url: str, headers: dict, data: bytes | None = None, timeout: int = 120):
        """Return (status, headers, file-like). HTTP errors come back as a status, not an exception."""
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, r, r
        except urllib.error.HTTPError as e:
            return e.code, e, e

    def request(self, url: str, accept: str = ACCEPT, timeout: int = 60) -> Resp:
        host = urlparse(url).netloc
        self._wait(host)
        st, _, fh = self._open(url, {"User-Agent": self.ua_for(host), "Accept": accept,
                                     "Accept-Language": "en,ar;q=0.8"}, timeout=timeout)
        with fh:
            return Resp(st, fh.read())

    def allowed(self, url: str) -> bool:
        u = urlparse(url)
        host = u.netloc
        if host not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.request(f"{u.scheme}://{host}/robots.txt", "text/plain,*/*", 30)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self.robots[host] = rp
                elif r.status_code >= 500:
                    self.robots[host] = False  # type: ignore[assignment]  # fail closed
                else:
                    # RFC 9309 s2.3.1.3: 4xx = robots.txt unavailable, crawling allowed (CDN/object
                    # stores answer AccessDenied XML here).
                    self.robots[host] = None
            except Exception:
                self.robots[host] = False  # type: ignore[assignment]  # unreachable: fail closed
        rp = self.robots[host]
        if rp is None:
            return True
        if rp is False:
            return False
        return rp.can_fetch(UA, url) or rp.can_fetch("*", url)

    def get(self, url: str, dest: Path | None = None, retries: int = 2):
        host = urlparse(url).netloc
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        last: Exception | None = None
        for _ in range(retries + 1):
            self._wait(host)
            try:
                st, _, fh = self._open(url, {"User-Agent": self.ua_for(host), "Accept": ACCEPT,
                                             "Accept-Language": "en,ar;q=0.8"})
                with fh:
                    if st != 200:
                        last = RuntimeError(f"HTTP {st} for {url}")
                        if st in (403, 404, 406, 410):
                            break
                        continue
                    if dest is None:
                        return Resp(st, fh.read())
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        while True:
                            chunk = fh.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                    tmp.replace(dest)
                    return Resp(st)
            except Exception as e:  # noqa: BLE001
                last = e
        raise RuntimeError(str(last))


def manifest_items():
    """Yield (url, relative dest under data/raw/intl, expected sha256, label)."""
    for p in sorted((ROOT / "evals/intl/anchors").glob("*/sources.json")):
        tk = p.parent.name
        for d in json.loads(p.read_text()):
            yield d["url"], d["local_path"], d.get("sha256"), f"anchor {tk}"
    mp = ROOT / "evals/intl/corpus/mena.json"
    if mp.exists():
        for d in json.loads(mp.read_text()):
            yield d["url"], d["local_path"], d.get("sha256"), f"mena {d.get('ticker')}"
    gp = ROOT / "evals/intl/corpus/xbrl_gold.json"
    if gp.exists():
        for d in json.loads(gp.read_text()):
            for k_url, k_loc, k_sha in (("package_url", "package_local_path", "package_sha256"),
                                        ("json_url", "json_local_path", "json_sha256")):
                if d.get(k_url) and d.get(k_loc):
                    yield d[k_url], d[k_loc], d.get(k_sha), f"gold {d.get('fxo_id') or d.get('entity')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="only check sha256 of files already present")
    a = ap.parse_args()
    ok = missing = bad = failed = 0
    f = None
    for url, rel, sha, label in manifest_items():
        dest = RAW / rel
        if not dest.exists():
            if a.verify:
                missing += 1
                print(f"MISSING {label}: {rel}")
                continue
            f = f or Fetcher()
            try:
                f.get(url, dest)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAILED  {label}: {url}: {e}")
                continue
        got = sha256_file(dest)
        if sha and got != sha:
            bad += 1
            print(f"SHA MISMATCH {label}: {rel}")
        else:
            ok += 1
    print(f"{ok} ok, {missing} missing, {bad} sha-mismatch, {failed} failed")
    return 0 if (bad == 0 and failed == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
