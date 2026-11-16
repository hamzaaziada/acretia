"""HTTP clients for isolated document-parsing services (Marker, MinerU).

Marker and MinerU are GPL/AGPL-class tools: they run only as separate
services (ledger decision ``isolated_service``) and are NEVER imported here.
This module only speaks HTTP to them.

Configuration: ``ACRETIA_MARKER_URL`` and ``ACRETIA_MINERU_URL`` (http/https
only). The client POSTs the PDF bytes as ``application/pdf`` (raw body) and
expects a JSON adapter response::

    {"pages": [
        {"number": 1, "width": 612.0, "height": 792.0,
         "blocks": [
            {"kind": "heading|text|table|list|caption|footnote|header|footer|other",
             "text": "...",
             "bbox": [x0, y0, x1, y1]}      # PDF points, TOP-LEFT origin
         ]}
    ]}

A thin adapter in front of each real service converts its native output to
this schema. Redirects to another host are refused, and the response size is
bounded (``max_bytes``).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
KINDS = {"heading", "text", "table", "list", "caption", "footnote", "header", "footer", "other"}
ENV = {"marker": "ACRETIA_MARKER_URL", "mineru": "ACRETIA_MINERU_URL"}


class ServiceError(Exception):
    """The parsing service is unconfigured, unreachable, or answered badly."""


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme not in ("http", "https") or u.netloc.lower() != self.host:
            raise ServiceError(f"refusing redirect off-host to {u.netloc or newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ServiceParser:
    def __init__(self, name, url, timeout=120, max_bytes=DEFAULT_MAX_BYTES):
        u = urllib.parse.urlparse(url or "")
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ServiceError(f"{name}: only http/https URLs are allowed (got {url!r})")
        self.name, self.url, self.timeout, self.max_bytes = name, url, timeout, max_bytes
        self._host = u.netloc.lower()

    @classmethod
    def from_env(cls, name, **kw):
        var = ENV.get(name)
        if not var:
            raise ServiceError(f"unknown parse service {name!r}")
        url = os.environ.get(var, "").strip()
        if not url:
            raise ServiceError(f"{name}: {var} is not set")
        return cls(name, url, **kw)

    def parse_pages(self, data):
        """POST PDF bytes; return validated ``[{number,width,height,blocks:[{kind,text,bbox}]}]``."""
        if len(data) > self.max_bytes:
            raise ServiceError(f"{self.name}: PDF too large to send ({len(data)} bytes)")
        req = urllib.request.Request(self.url, data=data, method="POST",
                                     headers={"Content-Type": "application/pdf",
                                              "Accept": "application/json"})
        opener = urllib.request.build_opener(_SameHostRedirect(self._host))
        try:
            with opener.open(req, timeout=self.timeout) as r:
                body = r.read(self.max_bytes + 1)
        except ServiceError:
            raise
        except urllib.error.HTTPError as e:
            raise ServiceError(f"{self.name}: HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise ServiceError(f"{self.name}: request failed: {e}")
        if len(body) > self.max_bytes:
            raise ServiceError(f"{self.name}: response exceeds {self.max_bytes} bytes")
        try:
            obj = json.loads(body.decode("utf-8"))
        except ValueError as e:
            raise ServiceError(f"{self.name}: invalid JSON: {e}")
        return _validate(self.name, obj)


def _validate(name, obj):
    pages = obj.get("pages") if isinstance(obj, dict) else None
    if not isinstance(pages, list):
        raise ServiceError(f"{name}: response has no 'pages' list")
    out = []
    for p in pages:
        try:
            num, w, h = int(p["number"]), float(p["width"]), float(p["height"])
            blocks = []
            for b in p.get("blocks", []):
                x0, y0, x1, y1 = (float(v) for v in b["bbox"])
                kind = b.get("kind", "other")
                blocks.append({"kind": kind if kind in KINDS else "other",
                               "text": str(b.get("text", "")), "bbox": (x0, y0, x1, y1)})
        except (KeyError, TypeError, ValueError) as e:
            raise ServiceError(f"{name}: malformed page entry: {e}")
        if num < 1 or w <= 0 or h <= 0:
            raise ServiceError(f"{name}: bad page geometry for page {num}")
        out.append({"number": num, "width": w, "height": h, "blocks": blocks})
    return out
