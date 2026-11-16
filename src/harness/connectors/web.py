"""IR page and press-release crawler (S2.5, D-024).

Stores FACTS and LINKS only: title, publish date, URL, sha256 of the fetched body and a <=300-char snippet. Never
the article text. Rules enforced here, in code:
  * identifies as "AcretiaBot/1.0 (+research crawler)" (no personal contact details);
  * honours robots.txt (urllib.robotparser) incl. Crawl-delay; robots 4xx = allow, 5xx/unreachable = disallow;
  * >=1 s between requests to the same host (robots.txt fetches included);
  * only http/https, no URL credentials; every host is resolved and ALL addresses must be globally routable
    (blocks loopback, private, link-local incl. 169.254.169.254, CGNAT, multicast, IPv4-mapped IPv6); the
    connection is pinned to the validated IP (no DNS rebinding); redirects are followed manually and each hop is
    re-validated and re-checked against robots.txt (max 5);
  * responses are capped at 10 MiB.
crawl4ai (Apache-2.0 + attribution clause, ledger: borrow_ideas) is OFF by default. It is only used as a renderer for
an already-validated URL when ACRETIA_CRAWL4AI=1 and the package imports; the stdlib path is the default.
Fetched pages are untrusted data, never instructions."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.robotparser
from dataclasses import asdict, dataclass
from html.parser import HTMLParser

from .base import Connector, ConnectorError, ConnectorItem, register

USER_AGENT = "AcretiaBot/1.0 (+research crawler)"
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5
MIN_INTERVAL = 1.0
SNIPPET = 300


class CrawlError(ConnectorError):
    pass


class SsrfError(CrawlError):
    pass


class RobotsDisallowed(CrawlError):
    pass


class ResponseTooLarge(CrawlError):
    pass


# --------------------------------------------------------------------------- SSRF guard
def _ip_ok(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and (ip.sixtofour or ip.teredo):
        return False
    return ip.is_global and not ip.is_multicast


def default_resolver(host: str, port: int) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def validate_url(url: str, resolver=default_resolver) -> tuple[urllib.parse.SplitResult, list[str]]:
    """-> (parts, validated addresses). Raises SsrfError for anything that is not a public http(s) host."""
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError as e:
        raise SsrfError(f"bad URL: {e}")
    if u.scheme not in ("http", "https"):
        raise SsrfError(f"scheme {u.scheme!r} not allowed")
    if not u.hostname:
        raise SsrfError("URL has no host")
    if u.username or u.password:
        raise SsrfError("URL credentials not allowed")
    host = u.hostname
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        addrs = None
        if re.fullmatch(r"[0-9a-fA-Fx.]+", host):       # legacy numeric forms (2130706433, 0x7f.1, 017700000001)
            try:
                addrs = [socket.inet_ntoa(socket.inet_aton(host))]
            except OSError:
                addrs = None
        if addrs is None:
            try:
                addrs = list(resolver(host, port or (443 if u.scheme == "https" else 80)))
            except OSError as e:
                raise CrawlError(f"cannot resolve {host}: {e}")
    if not addrs:
        raise CrawlError(f"{host} did not resolve")
    for a in addrs:
        try:
            ok = _ip_ok(a)
        except ValueError:
            ok = False
        if not ok:
            raise SsrfError(f"{host} resolves to non-public address {a}")
    return u, addrs


# --------------------------------------------------------------------------- transport
def default_transport(method, url, headers, ip, timeout, max_bytes):
    """One request, no redirects, connection pinned to `ip`, body capped. -> (status, headers, body)"""
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    sock = socket.create_connection((ip, port), timeout=timeout)
    if u.scheme == "https":
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
    conn = http.client.HTTPConnection(u.hostname, port, timeout=timeout)
    conn.sock = sock
    try:
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        conn.request(method, path, headers={"Host": u.netloc.rpartition("@")[2], **headers})
        r = conn.getresponse()
        cl = r.getheader("Content-Length")
        if cl and cl.isdigit() and int(cl) > max_bytes:
            raise ResponseTooLarge(f"Content-Length {cl} exceeds {max_bytes}")
        body = r.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ResponseTooLarge(f"response exceeds {max_bytes} bytes")
        return r.status, {k.lower(): v for k, v in r.getheaders()}, body
    finally:
        conn.close()


class RateLimiter:
    """Per-host minimum spacing. Thread-safe; `clock`/`sleep` are injectable for tests."""

    def __init__(self, min_interval: float = MIN_INTERVAL, clock=time.monotonic, sleep=time.sleep):
        self.min = max(float(min_interval), MIN_INTERVAL)   # never below 1 s
        self._clock, self._sleep = clock, sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, interval: float | None = None):
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + max(self.min, interval or 0.0)
        if start > now:
            self._sleep(start - now)


# --------------------------------------------------------------------------- HTML facts
class _Facts(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.meta, self.links = base, {}, []
        self.title, self._in_title, self._in_p, self._p, self._a = "", False, False, [], None
        self._ld, self._ldbuf, self.time = False, [], None
        self.first_p = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content"):
                self.meta.setdefault(k, a["content"].strip())
        elif tag == "a" and a.get("href"):
            self._a = [urllib.parse.urljoin(self.base, a["href"].strip()), []]
        elif tag == "time" and a.get("datetime") and not self.time:
            self.time = a["datetime"].strip()
        elif tag == "p" and not self.first_p:
            self._in_p, self._p = True, []
        elif tag == "script" and "ld+json" in (a.get("type") or ""):
            self._ld, self._ldbuf = True, []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._a:
            self.links.append((self._a[0], " ".join("".join(self._a[1]).split())))
            self._a = None
        elif tag == "p" and self._in_p:
            self._in_p = False
            t = " ".join("".join(self._p).split())
            if len(t) > 40:
                self.first_p = t
        elif tag == "script" and self._ld:
            self._ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._a:
            self._a[1].append(data)
        if self._in_p:
            self._p.append(data)
        if self._ld:
            self._ldbuf.append(data)

    def jsonld_date(self):
        try:
            j = json.loads("".join(self._ldbuf))
        except ValueError:
            return None
        for o in (j if isinstance(j, list) else [j]):
            if isinstance(o, dict) and o.get("datePublished"):
                return str(o["datePublished"])
        return None


_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class PageFacts:
    url: str
    title: str
    published: str | None
    sha256: str
    snippet: str
    fetched_at: str
    links: list | None = None

    def as_dict(self):
        return {k: v for k, v in asdict(self).items() if k != "links" or v}


def extract_facts(url: str, body: bytes, now: str = "") -> tuple[PageFacts, list]:
    """Facts + outgoing links from an HTML body. The body itself is discarded (D-024)."""
    text = body.decode("utf-8", "replace")
    p = _Facts(url)
    try:
        p.feed(text)
        p.close()
    except Exception:  # malformed markup is data, not control flow
        pass
    m = p.meta
    title = " ".join((m.get("og:title") or p.title or "").split())[:300]
    pub = m.get("article:published_time") or m.get("og:published_time") or m.get("datepublished") or p.jsonld_date() \
        or m.get("date") or p.time
    mm = _DATE.search(pub or "")
    published = mm.group(0) if mm else None
    desc = m.get("og:description") or m.get("description") or p.first_p
    snippet = " ".join(desc.split())[:SNIPPET]
    now = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return PageFacts(url, title, published, hashlib.sha256(body).hexdigest(), snippet, now), p.links


_PR_HINT = re.compile(r"press|news|release|announce|earnings|results|investor", re.I)


# --------------------------------------------------------------------------- crawler
class Crawler:
    def __init__(self, resolver=default_resolver, transport=default_transport, limiter: RateLimiter | None = None,
                 timeout: float = 20.0, max_bytes: int = MAX_BYTES, user_agent: str = USER_AGENT, renderer=None):
        self.resolver, self.transport = resolver, transport
        self.limiter = limiter or RateLimiter()
        self.timeout, self.max_bytes, self.ua = timeout, max_bytes, user_agent
        self._robots: dict[str, tuple[urllib.robotparser.RobotFileParser | None, float]] = {}
        self.renderer = renderer if renderer is not None else _crawl4ai_renderer()

    def _send(self, u, url, ip, headers, max_bytes, delay=None):
        self.limiter.wait(f"{u.scheme}://{u.netloc}", delay)
        h = {"User-Agent": self.ua, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
             "Accept-Encoding": "identity", **(headers or {})}
        return self.transport("GET", url, h, ip, self.timeout, max_bytes or self.max_bytes)

    def _robots_for(self, u) -> tuple[urllib.robotparser.RobotFileParser | None, float]:
        key = f"{u.scheme}://{u.netloc}"
        if key not in self._robots:
            rurl = f"{key}/robots.txt"
            rp, delay = urllib.robotparser.RobotFileParser(), 0.0
            try:
                ru, addrs = validate_url(rurl, self.resolver)
                status, hdrs, body = self._send(ru, rurl, addrs[0], None, 512 * 1024)
                if 300 <= status < 400:       # robots redirects: follow once, re-validated
                    loc = urllib.parse.urljoin(rurl, hdrs.get("location", ""))
                    ru, addrs = validate_url(loc, self.resolver)
                    status, hdrs, body = self._send(ru, loc, addrs[0], None, 512 * 1024)
                if status == 200:
                    rp.parse(body.decode("utf-8", "replace").splitlines())
                    delay = float(rp.crawl_delay(self.ua) or 0)
                elif 400 <= status < 500:
                    rp.parse([])              # no robots.txt: allowed (RFC 9309)
                else:
                    rp = None                 # 5xx: treat as disallow-all
            except (CrawlError, OSError):
                rp = None                     # unreachable: be conservative
            self._robots[key] = (rp, delay)
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        rp, _ = self._robots_for(u)
        return rp is not None and rp.can_fetch(self.ua, url)

    def fetch(self, url: str) -> tuple[str, bytes, dict]:
        """GET with robots, SSRF and redirect re-checks. -> (final_url, body, headers)"""
        for _hop in range(MAX_REDIRECTS + 1):
            u, addrs = validate_url(url, self.resolver)
            rp, delay = self._robots_for(u)
            if rp is None or not rp.can_fetch(self.ua, url):
                raise RobotsDisallowed(f"robots.txt disallows (or is unavailable for) {url}")
            status, hdrs, body = self._send(u, url, addrs[0], None, None, delay)
            if status in (301, 302, 303, 307, 308):
                loc = hdrs.get("location")
                if not loc:
                    raise CrawlError(f"redirect without Location from {url}")
                url = urllib.parse.urljoin(url, loc)
                continue
            if status != 200:
                raise CrawlError(f"HTTP {status} for {url}")
            ctype = hdrs.get("content-type", "text/html").split(";")[0].strip().lower()
            if not (ctype.startswith("text/") or ctype in ("application/xhtml+xml", "application/xml", "application/rss+xml",
                                                          "application/atom+xml", "application/json")):
                raise CrawlError(f"content type {ctype!r} not accepted")
            if self.renderer is not None:     # already validated; JS-rendered HTML replaces the body
                body = self.renderer(url) or body
            return url, body, hdrs
        raise CrawlError("too many redirects")

    def page_facts(self, url: str) -> tuple[PageFacts, list]:
        final, body, _ = self.fetch(url)
        facts, links = extract_facts(final, body)
        return facts, links

    def crawl_releases(self, index_url: str, max_items: int = 10, same_host: bool = True, allow_hosts=()) -> list[dict]:
        """Fetch an IR/press index page, follow likely press-release links, return fact records (no article text)."""
        idx_facts, links = self.page_facts(index_url)
        host = urllib.parse.urlsplit(idx_facts.url).hostname
        out, seen = [], {idx_facts.url}
        for href, text in links:
            if len(out) >= max_items:
                break
            hu = urllib.parse.urlsplit(href)
            if hu.scheme not in ("http", "https") or href in seen:
                continue
            if same_host and hu.hostname != host and hu.hostname not in allow_hosts:
                continue
            if not (_PR_HINT.search(hu.path) or _PR_HINT.search(text)) or hu.path in ("", "/"):
                continue
            seen.add(href)
            try:
                f, _l = self.page_facts(href)
            except CrawlError as e:
                out.append({"url": href, "error": str(e)[:200]})
                continue
            d = f.as_dict()
            d["link_text"] = text[:200]
            out.append(d)
        return out


def _crawl4ai_renderer():
    """Optional JS renderer; off unless ACRETIA_CRAWL4AI=1 and crawl4ai imports. Only ever given validated URLs."""
    if os.environ.get("ACRETIA_CRAWL4AI") != "1":
        return None
    try:
        import asyncio

        from crawl4ai import AsyncWebCrawler  # noqa: F401  (attribution required if adopted: see ledger)
    except Exception:
        return None

    def render(url: str) -> bytes | None:
        async def go():
            async with AsyncWebCrawler() as c:
                r = await c.arun(url=url)
                return (r.html or "").encode("utf-8")[:MAX_BYTES]
        try:
            return asyncio.run(go())
        except Exception:
            return None
    return render


@register("web")
class WebConnector(Connector):
    """list() = press-release fact records for an IR index URL; fetch(url) = JSON facts bytes (never article text)."""
    name = "web"

    def __init__(self, index_url: str, max_items: int = 10, crawler: Crawler | None = None):
        self.index_url, self.max_items = index_url, max_items
        self.crawler = crawler or Crawler()
        self._facts: dict = {}

    def list(self):
        for r in self.crawler.crawl_releases(self.index_url, self.max_items):
            if "error" in r:
                continue
            self._facts[r["url"]] = r
            yield ConnectorItem(r["url"], r["title"] or r["url"], 0, r["sha256"], r)

    def fetch(self, item_id: str):
        r = self._facts.get(item_id)
        if r is None:
            raise ConnectorError(f"unknown item {item_id!r}; call list() first")
        return json.dumps(r, sort_keys=True).encode(), {"name": item_id, "source": "web", **r}
