"""Resumable HTTP GET (stdlib). Survives truncated responses by resuming with a Range request.

A body counts as complete only when its length matches a known total (Content-Length or the
Content-Range total) or the server closed a non-chunked 200 response cleanly.
Callers that expect JSON should still validate it (see SecClient.get_json).
"""
from __future__ import annotations

import http.client
import re
import time
import urllib.error
import urllib.request


def _total_from(resp) -> int | None:
    cr = resp.headers.get("Content-Range") or ""
    m = re.search(r"/(\d+)\s*$", cr)
    if m:
        return int(m.group(1))
    if resp.status == 200 and resp.headers.get("Content-Length"):
        return int(resp.headers["Content-Length"])
    return None


def fetch_bytes(url: str, headers: dict | None = None, timeout: int = 60, attempts: int = 10) -> bytes:
    headers = {"Accept-Encoding": "identity", **(headers or {})}
    buf = b""
    total = None
    for attempt in range(attempts):
        h = dict(headers)
        if buf:
            h["Range"] = f"bytes={len(buf)}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                if buf and r.status != 206:  # server ignored Range: start over
                    buf = b""
                total = _total_from(r) or total
                try:
                    buf += r.read()
                except http.client.IncompleteRead as e:
                    buf += e.partial
                    raise
                if total is None or len(buf) >= total:
                    return buf
        except http.client.IncompleteRead:
            pass
        except urllib.error.HTTPError as e:
            if e.code == 416 and total and len(buf) >= total:
                return buf
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            pass
        time.sleep(min(30, 1.5 * (attempt + 1)))
    raise ConnectionError(f"could not fully download {url} ({len(buf)} of {total} bytes)")
