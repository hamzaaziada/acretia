"""Polite fetcher shared by every international source (S8.5, D-024).

Rules enforced in code, not by convention:
  * https only, no URL credentials, host must match the source's allow-list (redirect hops re-checked);
  * robots.txt is fetched once per host and cached; a disallowed path is refused BEFORE any request to it.
    robots 4xx = allow (401/403 = refuse, an edge block is not "no robots file"), 5xx/unreachable = refuse;
  * a per-host minimum interval (default 2 s, robots Crawl-delay raises it) with an injectable clock;
  * User-Agent `AcretiaResearch/1.0 (+financial statements research)`; no email address except for sec.gov, where
    the SEC's approved UA is read from SEC_USER_AGENT (the same rule as om.sec);
  * timeouts and size caps; bytes are written only under data/raw/intl/<source>/;
  * replay mode reads tests/fixtures/intl_connectors/<source>/ (index `_index.json`: URL -> file) and never
    touches the network, robots or the disk.
Returns facts + links + sha256 (`Fetched.record()`); nothing here republishes a document."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USER_AGENT = "AcretiaResearch/1.0 (+financial statements research)"
RAW_ROOT = ROOT / "data" / "raw" / "intl"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "intl_connectors"
MIB = 1024 * 1024


class SourceError(RuntimeError):
    status: int | None = None


class RobotsDisallowed(SourceError):
    pass


class TooLarge(SourceError):
    pass


class HttpError(SourceError):
    def __init__(self, msg, status):
        super().__init__(msg)
        self.status = status


class NotConfigured(SourceError):
    """A credential, approval or agreement the source needs is not present."""


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    sha256: str
    content_type: str = ""
    saved_path: str | None = None
    size: int = 0
    replayed: bool = False

    def record(self) -> dict:
        """The facts we keep about a fetch: where it came from and a hash, never the content."""
        return {"url": self.url, "status": self.status, "sha256": self.sha256, "bytes": self.size or len(self.body),
                "content_type": self.content_type, "saved_path": self.saved_path}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_REAL_URLOPEN = urllib.request.urlopen


def _default_open(req, timeout=None):
    """Never auto-follow a redirect (every hop is re-checked by Fetcher._open). When urllib.request.urlopen has been
    replaced (tests and the S8 gate script the network that way) the replacement is used so nothing leaves the process."""
    if urllib.request.urlopen is not _REAL_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def safe_name(name: str, limit: int = 120) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(str(name).split("?")[0]) or "item").lstrip(".") or "item"
    return n[-limit:]


def user_agent_for(host: str, env=None) -> str:
    if host == "sec.gov" or host.endswith(".sec.gov"):
        ua = (env if env is not None else os.environ).get("SEC_USER_AGENT", "").strip()
        if not ua:
            raise NotConfigured("SEC_USER_AGENT is not set; refusing to contact sec.gov")
        return ua
    return USER_AGENT


def host_ok(host: str, allowed) -> bool:
    host = (host or "").lower()
    return any(host == a or host.endswith("." + a) for a in allowed)


class Fetcher:
    def __init__(self, source: str, hosts, *, min_interval: float = 2.0, replay: bool = False, fixture_dir=None,
                 raw_dir=None, clock=None, sleep=None, urlopen=None, timeout: float = 30, max_bytes: int = 25 * MIB,
                 redirect_hosts=()):
        self.source, self.hosts = source, tuple(h.lower() for h in hosts)
        self.redirect_hosts = tuple(h.lower() for h in redirect_hosts)
        self.min_interval, self.replay, self.timeout, self.max_bytes = float(min_interval), replay, timeout, max_bytes
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_ROOT / source
        self.raw_dir = Path(raw_dir) if raw_dir else RAW_ROOT
        self._clock, self._sleep, self._urlopen = clock, sleep, urlopen
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._index = None

    # ------------------------------------------------------------------ url + robots + pacing
    def _check_url(self, url: str, redirect: bool = False) -> urllib.parse.SplitResult:
        u = urllib.parse.urlsplit(url)
        if u.scheme != "https" or not u.hostname or u.username or u.password:
            raise SourceError(f"refused {url!r}: https URLs without credentials only")
        allowed = self.hosts + (self.redirect_hosts if redirect else ())
        if not host_ok(u.hostname, allowed):
            raise SourceError(f"refused {url!r}: host not in the {self.source} allow-list")
        return u

    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    def _throttle(self, host: str, interval: float) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = last + interval - self._now()
            if wait > 0:
                (self._sleep or time.sleep)(wait + 0.001)
        self._last[host] = self._now()

    def _robots_for(self, host: str) -> urllib.robotparser.RobotFileParser:
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        self._throttle(host, self.min_interval)
        try:
            with self._http(f"https://{host}/robots.txt", {}, None, None, host) as r:
                rp.parse(r.read(512 * 1024).decode("utf-8", "replace").splitlines())
        except HttpError as e:
            if e.status in (401, 403) or (e.status or 0) >= 500:
                rp.disallow_all = True
            else:
                rp.allow_all = True
        except SourceError:
            rp.disallow_all = True      # unreachable robots.txt: refuse, do not guess
        rp.modified()
        self._robots[host] = rp
        return rp

    def can_fetch(self, url: str) -> bool:
        u = self._check_url(url, redirect=True)
        return self._robots_for(u.hostname).can_fetch(USER_AGENT, url)

    # ------------------------------------------------------------------ transport
    def _http(self, url, headers, data, method, host):
        hdrs = {"User-Agent": user_agent_for(host), "Accept-Encoding": "identity", **(headers or {})}
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        opener = self._urlopen or _default_open
        try:
            return opener(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise HttpError(f"HTTP {e.code} for {url}", e.code) from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise SourceError(f"could not reach {url}: {e}") from e

    def _open(self, url: str, headers=None, data=None, method=None):
        """robots check, pacing, request; authenticated requests never follow a redirect with the credential."""
        headers, hops = dict(headers or {}), 0
        while True:
            u = self._check_url(url, redirect=hops > 0)
            rp = self._robots_for(u.hostname)
            if not rp.can_fetch(USER_AGENT, url):
                raise RobotsDisallowed(f"robots.txt on {u.hostname} disallows {u.path or '/'}")
            delay = rp.crawl_delay(USER_AGENT)
            self._throttle(u.hostname, max(self.min_interval, float(delay or 0)))
            try:
                resp = self._http(url, headers, data if hops == 0 else None, method if hops == 0 else None, u.hostname)
            except HttpError as e:
                loc = (getattr(e.__cause__, "headers", None) or {}).get("Location")
                if e.status in (301, 302, 303, 307, 308) and loc and hops < 5:
                    nxt = urllib.parse.urljoin(url, loc)
                    if urllib.parse.urlsplit(nxt).hostname != u.hostname:
                        headers.pop("Authorization", None)          # a credential never follows a cross-host redirect
                    url, hops = nxt, hops + 1
                    continue
                raise
            final = urllib.parse.urlsplit(getattr(resp, "geturl", lambda: url)() or url)
            if not host_ok(final.hostname, self.hosts + self.redirect_hosts):
                resp.close()
                raise SourceError(f"{url} redirected to {final.hostname}, not in the allow-list")
            return resp

    # ------------------------------------------------------------------ replay
    def _replay_file(self, url: str) -> Path:
        if self._index is None:
            p = self.fixture_dir / "_index.json"
            if not p.exists():
                raise SourceError(f"no replay fixtures for {self.source} at {self.fixture_dir}")
            self._index = json.loads(p.read_text(encoding="utf-8"))
        name = self._index.get(url) or self._index.get(url.split("?")[0])
        if not name:
            raise SourceError(f"no replay fixture for {url}")
        return self.fixture_dir / name

    # ------------------------------------------------------------------ public
    def get(self, url, *, headers=None, data=None, method=None, max_bytes=None, save_as=None) -> Fetched:
        cap = max_bytes or self.max_bytes
        self._check_url(url)
        if self.replay:
            body = self._replay_file(url).read_bytes()
            if len(body) > cap:
                raise TooLarge(f"{url}: {len(body)} bytes over the {cap} cap")
            return Fetched(url, 200, body, hashlib.sha256(body).hexdigest(), "", None, len(body), True)
        with self._open(url, headers, data, method) as resp:
            cl = (getattr(resp, "headers", None) or {}).get("Content-Length")
            if cl and cl.isdigit() and int(cl) > cap:
                raise TooLarge(f"{url}: Content-Length {cl} over the {cap} cap")
            body = resp.read(cap + 1)
            ctype = (getattr(resp, "headers", None) or {}).get("Content-Type", "") or ""
        if len(body) > cap:
            raise TooLarge(f"{url}: body over the {cap} cap")
        path = self.save(save_as, body) if save_as else None
        return Fetched(url, 200, body, hashlib.sha256(body).hexdigest(), ctype, path, len(body))

    def get_json(self, url, **kw):
        r = self.get(url, **kw)
        try:
            return json.loads(r.body.decode("utf-8")), r
        except ValueError as e:
            raise SourceError(f"{url}: response is not JSON ({e})") from e

    def download(self, url, name, *, max_bytes=2048 * MIB) -> Fetched:
        """Stream a large file (bulk zips) to data/raw/intl/<source>/<name>; memory use stays one chunk."""
        self._check_url(url)
        if self.replay:
            body = self._replay_file(url).read_bytes()
            return Fetched(url, 200, b"", hashlib.sha256(body).hexdigest(), "", None, len(body), True)
        dest = self._dest(name)
        h, n = hashlib.sha256(), 0
        tmp = dest.with_name(dest.name + ".part")
        with self._open(url) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 * MIB)
                if not chunk:
                    break
                n += len(chunk)
                if n > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise TooLarge(f"{url}: over the {max_bytes} cap")
                h.update(chunk)
                f.write(chunk)
        os.replace(tmp, dest)
        return Fetched(url, 200, b"", h.hexdigest(), "", str(dest), n)

    # ------------------------------------------------------------------ the only disk writes
    def _dest(self, name: str) -> Path:
        base = (self.raw_dir / self.source).resolve()
        dest = (base / safe_name(name)).resolve()
        if base != dest.parent:
            raise SourceError(f"refused to write outside {base}")
        base.mkdir(parents=True, exist_ok=True)
        return dest

    def save(self, name: str, body: bytes) -> str:
        dest = self._dest(name)
        dest.write_bytes(body)
        return str(dest)


# ---------------------------------------------------------------------------------------- html links
class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.links, self._href, self._txt, self._in_title = "", [], None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._txt = dict(attrs).get("href"), []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._txt).split())))
            self._href = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._href is not None:
            self._txt.append(data)


def extract_links(body: bytes, base_url: str) -> tuple[str, list[dict]]:
    """(page title, [{"url", "text"}]) with absolute http(s) URLs only; no page text is kept."""
    p = _Links()
    p.feed(body.decode("utf-8", "replace"))
    out, seen = [], set()
    for href, text in p.links:
        url = urllib.parse.urljoin(base_url, href.strip())
        if urllib.parse.urlsplit(url).scheme in ("http", "https") and url not in seen:
            seen.add(url)
            out.append({"url": url, "text": text[:200]})
    return " ".join(p.title.split())[:200], out


# ---------------------------------------------------------------------------------------- personal data
def minimise_person(rec: dict, name=("name",), role=("officer_role", "role", "kind"), appointed=("appointed_on", "notified_on"),
                    resigned=("resigned_on", "ceased_on")) -> dict:
    """Whitelist projection: name, role, appointed, resigned. Every other field of a person record is dropped."""
    def first(keys):
        return next((rec[k] for k in keys if rec.get(k) not in (None, "")), None)
    return {"name": first(name), "role": first(role), "appointed": first(appointed), "resigned": first(resigned)}


def iter_zip_members(path, suffixes=(".xhtml", ".html", ".htm", ".xml", ".json"), max_member=30 * MIB, max_members=200000):
    """Yield (name, bytes) for members with a wanted suffix; skips oversize members (zip-bomb guard)."""
    with zipfile.ZipFile(path) as z:
        for i, info in enumerate(z.infolist()):
            if i >= max_members:
                break
            if info.is_dir() or info.file_size > max_member or not info.filename.lower().endswith(suffixes):
                continue
            with z.open(info) as f:
                yield info.filename, f.read(max_member + 1)[:max_member]
