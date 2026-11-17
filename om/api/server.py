"""HTTP server for the product API: host guard, CSRF, sessions, RBAC, errors, SSE, static/SPA (SPEC §2)."""
from __future__ import annotations

import gzip
import importlib
import importlib.util
import mimetypes
import os
import queue
import socket
import sys
import threading
import traceback
import urllib.parse
from collections.abc import Mapping
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__, auth, db, security
from . import state as state_mod
from .http import (ApiError, RequestContext, Response, Route, Router, SSE, SSE_KEEPALIVE, parse_json, render,
                   sse_format)

ROUTE_MODULES: tuple[str, ...] = (
    "om.api.auth", "om.api.audit", "om.api.deals", "om.api.library", "om.api.notify", "om.api.jobs",
    "om.api.agents.library", "om.api.citations", "om.api.viewers", "om.api.firm", "om.api.mail", "om.api.grid", "om.api.decks",
)
API_PREFIX = "/api/"
MAX_BODY = 200 * 1024 * 1024
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_EXT = {".js", ".mjs", ".css", ".html", ".svg", ".json", ".map", ".txt", ".xml", ".webmanifest"}
EXTRA_TYPES = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
               ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
               ".json": "application/json; charset=utf-8", ".woff2": "font/woff2", ".woff": "font/woff",
               ".map": "application/json; charset=utf-8", ".wasm": "application/wasm", ".ico": "image/x-icon",
               ".webmanifest": "application/manifest+json", ".png": "image/png", ".txt": "text/plain; charset=utf-8"}

NO_FRONTEND = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    "<title>Acretia</title></head><body><main><h1>Acretia is running</h1>"
    "<p>The web interface has not been built yet. Build it once with:</p>"
    "<pre>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</pre>"
    '<p>Then reload this page. The API is already available: <a href="/api/v1/healthz">/api/v1/healthz</a>.</p>'
    "</main></body></html>")


# --------------------------------------------------------------------------- routes
def _import_tolerant(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and (name == e.name or name.startswith(e.name + ".")):
            return None
        raise


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def healthz(ctx):
    engines = {"deck": "om.deck.render", "grid": "om.grid", "excel": "om.model3", "research": "src.harness.research",
               "intl": "om.intl", "parser": "om.docparse"}
    st = state_mod.STATE
    return {"ok": True, "version": __version__, "llm_mode": st.llm_mode if st else "replay",
            "engines": {k: _has(v) for k, v in engines.items()}}


def all_routes() -> list[Route]:
    routes = [Route("GET", "/api/v1/healthz", healthz, role="public")]
    for name in ROUTE_MODULES:
        mod = _import_tolerant(name)
        if mod is not None:
            routes.extend(getattr(mod, "ROUTES", None) or [])
    return routes


# --------------------------------------------------------------------------- request helpers
class Headers(Mapping):
    """Case-insensitive read-only header mapping; `X-Acretia-*` is server-controlled (client copies are dropped)."""

    def __init__(self, msg, extra: dict):
        d: dict[str, str] = {}
        for k in msg.keys():
            lk = k.lower()
            if lk.startswith("x-acretia-") or lk in d:
                continue
            d[lk] = msg[k]
        d.update({k.lower(): v for k, v in extra.items()})
        self._d = d

    def __getitem__(self, k):
        return self._d[str(k).lower()]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


def _query(qs: str) -> dict:
    out = {}
    for k, vs in urllib.parse.parse_qs(qs, keep_blank_values=True).items():
        out[k] = vs[0]
    return out


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return EXTRA_TYPES.get(ext) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


class ApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120
    sys_version = ""
    server_version = "Acretia"

    def log_message(self, *a):
        pass

    def finish(self):
        try:
            super().finish()
        finally:
            self.server.state.close_conn()

    # ------------------------------------------------------------------ output
    def _write(self, status: int, headers: dict, body: bytes, api: bool, head: bool = False):
        merged = dict(security.SECURITY_HEADERS)
        if api:
            merged["Cache-Control"] = "no-store"
        low = {k.lower() for k in merged}
        for k, v in headers.items():
            if k.lower() in low:
                for mk in [mk for mk in merged if mk.lower() == k.lower()]:
                    del merged[mk]
            merged[k] = v
        unread = getattr(self, "_unread_body", False)
        if unread:
            merged["Connection"] = "close"
            self.close_connection = True
        self.send_response(status)
        for k, v in merged.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def _error(self, e: ApiError, api: bool, head: bool = False):
        body = render((e.status, e.body()))[2]
        self._write(e.status, {"Content-Type": "application/json; charset=utf-8", **e.headers}, body, api, head)

    # ------------------------------------------------------------------ entry points
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self._unread_body = int(self.headers.get("Content-Length") or 0) > 0
        self._write(204, {"Allow": "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"}, b"", True)

    def _dispatch(self, method: str):
        cl = self.headers.get("Content-Length") or ""
        self._unread_body = (cl.isdigit() and int(cl) > 0) or bool(self.headers.get("Transfer-Encoding"))
        api = self.path.startswith(API_PREFIX) or self.path == "/api"
        try:
            raw = self.path.split("#", 1)[0]
            if not raw.startswith("/"):
                raise ApiError(400, "bad_request", "The request target is not a path.", "Send a path such as /api/v1/healthz.")
            path, _, qs = raw.partition("?")
            self._host_guard()
            if api:
                self._api(method, path, qs)
            else:
                self._static(method, path)
        except ApiError as e:
            self._error(e, api, head=(method == "HEAD"))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, socket.timeout):
            self.close_connection = True
        except Exception:
            traceback.print_exc(file=sys.stderr)
            try:
                self._error(ApiError(500, "internal_error", "Something went wrong on our side.",
                                     "Try again; if it keeps happening, tell your administrator."), api)
            except Exception:
                self.close_connection = True

    # ------------------------------------------------------------------ guards
    def _host_guard(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if not self.server.host_allowed(host):
            raise ApiError(403, "bad_host", "This host name is not allowed.",
                           "Open the app at the address it was started on, or add the host to ACRETIA_ALLOWED_HOSTS.")

    def _origin_ok(self) -> bool:
        src = self.headers.get("Origin") or self.headers.get("Referer")
        if not src or src == "null":
            return False
        p = urllib.parse.urlsplit(src)
        if not p.netloc:
            return False
        host = (self.headers.get("Host") or "").strip().lower()
        if p.netloc.lower() == host:
            return True
        return f"{p.scheme}://{p.netloc}".lower() in self.server.allowed_origins

    def _client_ip(self) -> str:
        if os.environ.get("ACRETIA_TRUST_PROXY") == "1":
            xf = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if xf:
                return xf
        return self.client_address[0]

    def _read_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise ApiError(411, "length_required", "Chunked uploads are not supported.", "Send a Content-Length header.")
        cl = self.headers.get("Content-Length")
        if not cl:
            self._unread_body = False
            return b""
        if not cl.isdigit():
            raise ApiError(400, "bad_request", "Content-Length is not a number.", "Send a valid Content-Length.")
        n = int(cl)
        if n > MAX_BODY:
            raise ApiError(413, "too_large", f"The request is larger than {MAX_BODY // 2**20} MB.",
                           "Split the upload into smaller parts.")
        body = self.rfile.read(n) if n else b""
        if len(body) < n:
            self.close_connection = True
            raise ApiError(400, "bad_request", "The request body ended early.", "Re-send the request.")
        self._unread_body = False
        return body

    # ------------------------------------------------------------------ API
    def _api(self, method: str, path: str, qs: str):
        srv = self.server
        st = srv.state
        head = method == "HEAD"
        route, params = srv.router.resolve("GET" if head else method, path)
        conn = st.conn()
        headers = Headers(self.headers, {"X-Acretia-Client-Ip": self._client_ip()})
        ctx = RequestContext(method="GET" if head else method, path=path, params=params, query=_query(qs),
                             headers=headers, conn=conn, blobs=st.blobs, data_dir=st.data_dir)
        sess = auth.resolve_session(conn, auth._cookie_token(headers))
        if sess:
            ctx.user, ctx.org_id, ctx.role, ctx.session_id = sess["user"], sess["org_id"], sess["role"], sess["session_id"]
        ip, ua = headers.get("X-Acretia-Client-Ip") or "", headers.get("User-Agent") or ""
        calls: list[str] = []

        def _audit(c, action, target="", detail=None):
            if c.org_id is None:
                return
            calls.append(action)
            st.audit(conn, c.org_id, c.user["id"] if c.user else None, action, target, detail, ip, ua)
        ctx._audit = _audit

        mutating = method not in ("GET", "HEAD", "OPTIONS")
        status = 500
        try:
            if route.role != "public" and sess is None:
                raise ApiError(401, "unauthenticated", "You are not signed in.", "Sign in again.")
            if mutating and route.csrf:
                if not self._origin_ok():
                    raise ApiError(403, "csrf_failed", "This request did not come from the app.",
                                   "Reload the page and try again.")
                if route.role != "public":
                    tok = headers.get("X-CSRF-Token") or ""
                    if not tok or not security.ct_equal(security.token_hash(tok), sess["csrf_hash"]):
                        raise ApiError(403, "csrf_failed", "The CSRF token is missing or wrong.",
                                       "Reload the page to get a fresh token and try again.")
            if route.role != "public":
                ctx.require(route.role)
            body = self._read_body()
            ctx.body = body
            ctype = (self.headers.get("Content-Type") or "").lower()
            ctx.json = parse_json(body) if (body and "json" in ctype) else None
            result = route.handler(ctx)
            status, hdrs, out = render(result)
        except ApiError as e:
            status = e.status
            self._auto_audit(ctx, st, conn, mutating, calls, route, status, ip, ua)
            raise
        except BaseException:
            self._auto_audit(ctx, st, conn, mutating, calls, route, 500, ip, ua)
            raise
        self._auto_audit(ctx, st, conn, mutating, calls, route, status, ip, ua)
        if isinstance(out, SSE):
            return self._stream(out, hdrs)
        self._write(status, hdrs, out, True, head)

    def _auto_audit(self, ctx, st, conn, mutating, calls, route, status, ip, ua):
        if not mutating or calls or ctx.org_id is None or ctx.user is None:
            return
        try:
            st.audit(conn, ctx.org_id, ctx.user["id"], f"{ctx.method} {route.pattern[len('/api/v1'):]}", ctx.path,
                     {"status": status}, ip, ua)
        except Exception:
            traceback.print_exc(file=sys.stderr)

    # ------------------------------------------------------------------ SSE
    def _stream(self, sse: SSE, hdrs: dict):
        self.close_connection = True
        merged = dict(security.SECURITY_HEADERS)
        merged.update(hdrs)
        merged["Connection"] = "close"
        merged["Cache-Control"] = "no-store"
        self.send_response(200)
        for k, v in merged.items():
            self.send_header(k, v)
        self.end_headers()
        q: queue.Queue = queue.Queue()
        stop = threading.Event()
        it = iter(sse.iterator)

        def pump():
            try:
                for item in it:
                    if stop.is_set():
                        break
                    q.put(("item", item))
                q.put(("end", None))
            except Exception as e:  # surfaced to the client as an error event
                q.put(("err", e))
            finally:
                close = getattr(it, "close", None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass

        threading.Thread(target=pump, daemon=True, name="sse-pump").start()
        ka = getattr(self.server, "keepalive", 15.0)
        try:
            self.wfile.write(b": connected\n\n")
            while True:
                try:
                    kind, val = q.get(timeout=ka)
                except queue.Empty:
                    self.wfile.write(SSE_KEEPALIVE)
                    continue
                if kind == "end":
                    break
                if kind == "err":
                    self.wfile.write(sse_format(None, "error", {"code": "stream_failed", "message": "The stream ended unexpectedly.",
                                                                "hint": "Reconnect to resume."}))
                    break
                if val is None:
                    continue
                if isinstance(val, (bytes, bytearray)):
                    self.wfile.write(bytes(val))
                elif isinstance(val, tuple) and len(val) == 3:
                    self.wfile.write(sse_format(*val))
                elif isinstance(val, tuple) and len(val) == 2:
                    self.wfile.write(sse_format(None, *val))
                else:
                    continue
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            stop.set()

    # ------------------------------------------------------------------ static / SPA
    def _static(self, method: str, path: str):
        head = method == "HEAD"
        if method not in ("GET", "HEAD"):
            raise ApiError(405, "method_not_allowed", f"{method} is not allowed here.", "Use GET.", headers={"Allow": "GET, HEAD"})
        st = self.server.state
        root = st.static_dir or Path(os.environ.get("ACRETIA_FRONTEND_DIST") or REPO_ROOT / "frontend" / "dist")
        rel = urllib.parse.unquote(path)
        if "\x00" in rel or "\\" in rel or any(p == ".." for p in rel.split("/")):
            raise ApiError(404, "not_found", "Not found.")
        if not (root / "index.html").is_file():
            return self._write(200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache"},
                               NO_FRONTEND.encode("utf-8"), False, head)
        root_r = root.resolve()
        target = None
        if rel not in ("", "/"):
            cand = (root_r / rel.lstrip("/")).resolve()
            try:
                cand.relative_to(root_r)
            except ValueError:
                raise ApiError(404, "not_found", "Not found.") from None
            if cand.is_file():
                target = cand
            elif rel.startswith("/assets/") or Path(rel).suffix.lower() in (".js", ".css", ".map", ".woff2", ".png", ".svg"):
                raise ApiError(404, "not_found", "Not found.")
        immutable = target is not None and rel.startswith("/assets/")
        if target is None:
            target = root_r / "index.html"
        data = target.read_bytes()
        stt = target.stat()
        etag = f'"{stt.st_mtime_ns:x}-{stt.st_size:x}"'
        headers = {"Content-Type": _content_type(target), "ETag": etag,
                   "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache",
                   "Last-Modified": formatdate(stt.st_mtime, usegmt=True), "Vary": "Accept-Encoding"}
        if self.headers.get("If-None-Match") == etag:
            return self._write(304, {k: v for k, v in headers.items() if k != "Content-Type"}, b"", False, head)
        if target.suffix.lower() in TEXT_EXT and len(data) > 512 and "gzip" in (self.headers.get("Accept-Encoding") or "").lower():
            data = self.server.gzip_cached(str(target), stt.st_mtime_ns, data)
            headers["Content-Encoding"] = "gzip"
        self._write(200, headers, data, False, head)


# --------------------------------------------------------------------------- server
class AcretiaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def host_allowed(self, host: str) -> bool:
        if not host:
            return False
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        if host in self.extra_hosts or name in self.extra_hosts:
            return True
        if not self.local_only:
            return False
        port = host.rsplit(":", 1)[1] if (":" in host and not host.endswith("]")) else ""
        if name not in ("localhost", "127.0.0.1", "[::1]"):
            return False
        return port == str(self.bound_port) or (port == "" and self.bound_port == 80)

    def gzip_cached(self, key: str, mtime: int, data: bytes) -> bytes:
        hit = self._gz.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        z = gzip.compress(data, 6, mtime=0)
        self._gz[key] = (mtime, z)
        return z

    def server_close(self):
        try:
            jobs = _import_tolerant("om.api.jobs")
            if jobs is not None and hasattr(jobs, "shutdown"):
                jobs.shutdown()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        try:
            from . import deals
            deals.shutdown()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        super().server_close()


class AcretiaServer6(AcretiaServer):
    address_family = socket.AF_INET6


def make_server(state, host: str = "127.0.0.1", port: int = 8791) -> AcretiaServer:
    """Bind (port 0 = pick a free one), migrate the DB, start jobs and indexing resume."""
    extra = {h.strip().lower() for h in os.environ.get("ACRETIA_ALLOWED_HOSTS", "").split(",") if h.strip()}
    local = host in LOCAL_HOSTS
    if not local and not extra:
        raise RuntimeError(f"Binding to {host!r} needs ACRETIA_ALLOWED_HOSTS (comma-separated host names) so the "
                           "app can refuse DNS-rebinding requests.")
    srv = (AcretiaServer6 if ":" in host else AcretiaServer)((host, port), ApiHandler)
    srv.state, srv.local_only, srv.extra_hosts = state, local, extra
    srv.bound_port = srv.server_address[1]
    srv.allowed_origins = {o.strip().lower().rstrip("/") for o in os.environ.get("ACRETIA_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    srv.router = Router(all_routes())
    srv.keepalive = 15.0
    srv._gz = {}
    state_mod.STATE = state
    db.migrate(state.conn())
    jobs = _import_tolerant("om.api.jobs")
    if jobs is not None and hasattr(jobs, "init"):
        jobs.init(state)
    from . import deals
    deals.resume_indexing(state)
    return srv


def serve(state, host: str = "127.0.0.1", port: int = 8791) -> None:
    srv = make_server(state, host, port)
    print(f"Acretia API on http://{host}:{srv.bound_port}  (data: {state.data_dir}, llm_mode={state.llm_mode})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
