"""Server: headers on every response, host guard, static/SPA/traversal, healthz, SSE, audit chain, CSV safety."""
import csv
import gzip
import http.client
import io
import json
import os
import pathlib
import socket
import threading
import time
import unittest
from unittest import mock

from om.api import audit, notify, security, server
from om.api.http import ApiError, Route, SSE
try:
    from tests.test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401
except ImportError:
    from test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401

REQUIRED = dict(security.SECURITY_HEADERS)


def raw_request(port, text: bytes, read=65536) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        s.sendall(text)
        out = b""
        while True:
            try:
                chunk = s.recv(read)
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


class ServerTests(ServerCase):
    def assert_headers(self, headers, where):
        for k, v in REQUIRED.items():
            self.assertEqual(headers.get(k.lower()), v, f"{where}: {k}")

    def test_security_headers_everywhere(self):
        self.make_org()
        owner = self.client("owner@acme.example")
        calls = [("GET", "/api/v1/healthz", {}), ("GET", "/api/v1/nope", {}), ("POST", "/api/v1/healthz", {}),
                 ("GET", "/api/v1/auth/me", {"cookie": False}), ("GET", "/api/v1/deals", {}),
                 ("POST", "/api/v1/deals", {"csrf": False}), ("GET", "/", {}), ("GET", "/some/spa/route", {}),
                 ("GET", "/assets/missing.js", {}), ("OPTIONS", "/api/v1/deals", {}), ("PUT", "/", {}),
                 ("GET", "/api/v1/audit/export.csv", {})]
        for m, p, kw in calls:
            s, h, _ = owner.req(m, p, **kw)
            self.assert_headers(h, f"{m} {p} -> {s}")
            if p.startswith("/api/"):
                self.assertEqual(h.get("cache-control"), "no-store", f"{m} {p}")
        s, h, b = Client(self.port).req("GET", "/api/v1/nope")
        self.assertEqual(s, 404)
        err = json.loads(b)["error"]
        self.assertEqual(err["code"], "not_found")
        s, h, b = owner.req("POST", "/api/v1/healthz", {})
        self.assertEqual((s, h["allow"]), (405, "GET"))
        self.assertTrue(json.loads(b)["error"]["hint"])

    def test_healthz(self):
        s, d, _ = Client(self.port).j("GET", "/api/v1/healthz")
        self.assertEqual(s, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(d["llm_mode"], "replay")
        self.assertEqual(set(d["engines"]), {"deck", "grid", "excel", "research", "intl", "parser"})
        self.assertTrue(all(isinstance(v, bool) for v in d["engines"].values()))

    def test_host_guard(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1:1", "localhost:9", "", "127.0.0.1.evil.example"):
            req = f"GET /api/v1/healthz HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
            out = raw_request(self.port, req)
            self.assertIn(b" 403 ", out.split(b"\r\n", 1)[0], host)
            self.assertIn(b"bad_host", out)
            self.assertIn(b"Content-Security-Policy", out)
        for host in (f"localhost:{self.port}", f"127.0.0.1:{self.port}"):
            out = raw_request(self.port, f"GET /api/v1/healthz HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            self.assertIn(b" 200 ", out.split(b"\r\n", 1)[0], host)
        out = raw_request(self.port, f"GET / HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n".encode())
        self.assertIn(b" 403 ", out.split(b"\r\n", 1)[0])

    def test_non_local_bind_requires_allowed_hosts(self):
        os.environ.pop("ACRETIA_ALLOWED_HOSTS", None)
        with self.assertRaises(RuntimeError):
            server.make_server(self.st, "0.0.0.0", 0)

    def test_oversized_body_is_refused_without_reading_it(self):
        out = raw_request(self.port, f"POST /api/v1/auth/login HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                                     f"Origin: http://127.0.0.1:{self.port}\r\nContent-Type: application/json\r\n"
                                     f"Content-Length: 400000000\r\nConnection: close\r\n\r\n".encode())
        self.assertIn(b" 413 ", out.split(b"\r\n", 1)[0])
        self.assertIn(b"too_large", out)

    def test_500_hides_internals(self):
        def boom(ctx):
            raise RuntimeError("secret internal detail /etc/passwd")
        self.srv.router.routes.append(Route("GET", "/api/v1/_test/boom", boom, role="public"))
        with mock.patch.object(server.traceback, "print_exc"):
            s, h, b = Client(self.port).req("GET", "/api/v1/_test/boom")
        self.assertEqual(s, 500)
        self.assertNotIn(b"secret internal", b)
        self.assertTrue(json.loads(b)["error"]["hint"])
        self.assert_headers(h, "500")

    def test_bad_json_and_validation_have_hints(self):
        self.make_org()
        c = self.client("owner@acme.example")
        s, h, b = c.req("POST", "/api/v1/deals", raw=b"{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(s, 400)
        self.assertEqual(json.loads(b)["error"]["code"], "bad_json")
        s, d, _ = c.j("POST", "/api/v1/deals", {"name": ""})
        self.assertEqual(s, 400)
        self.assertTrue(d["error"]["hint"])


class StaticTests(ServerCase):
    def setUp(self):
        super().setUp()
        self.dist = pathlib.Path(self.tmp) / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text('<!doctype html><html lang="en"><head><title>Acretia</title>'
                                              '<script type="module" src="/assets/app-1.js"></script></head><body><div id="root"></div></body></html>')
        (self.dist / "assets" / "app-1.js").write_text("console.log('hello');\n" * 200)
        (self.dist / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 600)
        (pathlib.Path(self.tmp) / "secret.txt").write_text("TOP-SECRET-MARKER")
        self.st.static_dir = self.dist

    def get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, body

    def test_spa_fallback_and_assets(self):
        s, h, b = self.get("/")
        self.assertEqual(s, 200)
        self.assertIn(b'id="root"', b)
        self.assertEqual(h["cache-control"], "no-cache")
        for p in ("/deals/deal-123", "/settings/audit", "/runs/job_abc"):
            s, h, b = self.get(p)
            self.assertEqual((s, b"id=\"root\"" in b), (200, True), p)
            self.assertEqual(h["content-security-policy"], security.CSP)
        s, h, b = self.get("/assets/app-1.js")
        self.assertEqual(s, 200)
        self.assertIn("immutable", h["cache-control"])
        self.assertTrue(h["content-type"].startswith("text/javascript"))
        self.assertEqual(h["x-content-type-options"], "nosniff")
        s, h, b = self.get("/assets/app-1.js", {"Accept-Encoding": "gzip"})
        self.assertEqual(h.get("content-encoding"), "gzip")
        self.assertIn(b"hello", gzip.decompress(b))
        s, h, _ = self.get("/assets/logo.png", {"Accept-Encoding": "gzip"})
        self.assertNotIn("content-encoding", h)
        s, h, b = self.get("/assets/missing.js")
        self.assertEqual(s, 404)
        self.assertNotIn(b"root", b)
        s, h, b = self.get("/")
        etag = h["etag"]
        s, h, b = self.get("/", {"If-None-Match": etag})
        self.assertEqual((s, b), (304, b""))

    def test_traversal_attempts_never_leak(self):
        attempts = ["/../secret.txt", "/../../etc/passwd", "/%2e%2e/secret.txt", "/%2e%2e%2fsecret.txt", "/assets/../../secret.txt",
                    "/assets/..%2f..%2fsecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/..%5csecret.txt", "/assets/..%5c..%5csecret.txt",
                    "/%252e%252e/secret.txt", "//etc/passwd", "/assets/%00../secret.txt", "/assets//..//..//secret.txt",
                    "/api/../../secret.txt", "/\\..\\secret.txt", "/assets/....//....//secret.txt"]
        for p in attempts:
            out = raw_request(self.port, f"GET {p} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\n\r\n".encode())
            self.assertNotIn(b"TOP-SECRET-MARKER", out, p)
            self.assertNotIn(b"root:x:", out, p)
            head = out.split(b"\r\n", 1)[0]
            self.assertTrue(b" 200 " in head or b" 404 " in head or b" 400 " in head, (p, head))
            self.assertIn(b"X-Content-Type-Options", out, p)

    def test_missing_build_page_has_no_inline_code(self):
        self.st.static_dir = pathlib.Path(self.tmp) / "nope"
        s, h, b = self.get("/")
        self.assertEqual(s, 200)
        text = b.decode()
        self.assertIn("npm run build", text)
        for bad in ("<script", "<style", "style=", "onclick", "javascript:"):
            self.assertNotIn(bad, text.lower())
        self.assertEqual(h["content-security-policy"], security.CSP)


class SseTests(ServerCase):
    def test_org_events_and_keepalive_and_last_event_id(self):
        org, _ = self.make_org()
        self.srv.keepalive = 0.3
        seen = []

        def handler(ctx):
            def gen():
                yield ("hello", {"last_event_id": ctx.headers.get("Last-Event-ID")})
                yield (7, "numbered", {"n": 7})
            return SSE(gen(), last_event_id=ctx.headers.get("last-event-id"))
        self.srv.router.routes.append(Route("GET", "/api/v1/_test/sse", handler, role="viewer"))
        c = self.client("owner@acme.example")

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/v1/_test/sse", headers={"Cookie": f"acr_session={c.cookie}", "Last-Event-ID": "42"})
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Content-Type"), "text/event-stream")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        blob = b""
        deadline = time.time() + 5
        while b"event: numbered" not in blob and time.time() < deadline:
            blob += r.fp.readline()
        self.assertIn(b'"last_event_id":"42"', blob)
        self.assertIn(b"id: 7\nevent: numbered", blob.replace(b"\r", b""))
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/v1/events", headers={"Cookie": f"acr_session={c.cookie}"})
        r = conn.getresponse()
        lines = []

        def reader():
            try:
                while len(lines) < 40:
                    ln = r.fp.readline()
                    if not ln:
                        break
                    lines.append(ln.decode())
            except (AttributeError, ValueError, OSError):
                pass
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        deadline = time.time() + 5
        while notify.subscriber_count(org) == 0 and time.time() < deadline:
            time.sleep(0.02)
        notify.notify(self.conn, org, None, "info", "Hello team", "body")
        notify.publish(org, "job", {"job_id": "job_1", "status": "running"})
        notify.publish("org_other", "job", {"job_id": "leak"})
        time.sleep(1.0)
        text = "".join(lines)
        self.assertIn("event: ready", text)
        self.assertIn("event: notification", text)
        self.assertIn("Hello team", text)
        self.assertIn("event: job", text)
        self.assertNotIn("leak", text)
        self.assertIn(": keep-alive", text)
        r.close()
        conn.close()
        deadline = time.time() + 8
        while notify.subscriber_count(org) and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(notify.subscriber_count(org), 0, "subscription must be released after the client disconnects")

    def test_events_requires_login(self):
        s, d, _ = Client(self.port).j("GET", "/api/v1/events")
        self.assertEqual(s, 401)


class AuditTests(ServerCase):
    def test_every_mutation_is_audited_and_chain_verifies_and_detects_tamper(self):
        org, owner_id = self.make_org()
        c = self.client("owner@acme.example")
        s, deal, _ = c.j("POST", "/api/v1/deals", {"name": "Audited Deal"})
        c.j("POST", "/api/v1/notifications/read-all", {})
        c.j("POST", "/api/v1/deals", {"name": ""})  # a failed mutation is audited too
        rows = self.conn.execute("SELECT * FROM audit_log WHERE org_id=? ORDER BY seq", (org,)).fetchall()
        actions = [r["action"] for r in rows]
        self.assertIn("auth.login", actions)
        self.assertIn("deal.create", actions)
        self.assertIn("POST /notifications/read-all", actions)
        self.assertEqual(actions.count("POST /deals"), 1)
        self.assertEqual([r["seq"] for r in rows], list(range(1, len(rows) + 1)))
        self.assertTrue(all(r["ip"] == "127.0.0.1" for r in rows))
        self.assertIn(f"deal:{deal['deal_id']}", [r["target"] for r in rows])
        s, v, _ = c.j("GET", "/api/v1/audit/verify")
        self.assertEqual((s, v["ok"], v["bad_seq"]), (200, True, None))
        s, page, _ = c.j("GET", "/api/v1/audit?limit=2")
        self.assertEqual(len(page["items"]), 2)
        self.assertGreater(page["items"][0]["seq"], page["items"][1]["seq"])
        self.assertIsNotNone(page["next_cursor"])
        # tamper with one row's content
        victim = rows[1]["seq"]
        self.conn.execute("UPDATE audit_log SET detail_json='{\"forged\":true}' WHERE org_id=? AND seq=?", (org, victim))
        s, v, _ = c.j("GET", "/api/v1/audit/verify")
        self.assertEqual((v["ok"], v["bad_seq"]), (False, victim))
        self.conn.execute("UPDATE audit_log SET detail_json=? WHERE org_id=? AND seq=?", (rows[1]["detail_json"], org, victim))
        self.assertTrue(c.j("GET", "/api/v1/audit/verify")[1]["ok"])
        # tamper by deleting a row
        gone = rows[2]["seq"]
        self.conn.execute("DELETE FROM audit_log WHERE org_id=? AND seq=?", (org, gone))
        v = c.j("GET", "/api/v1/audit/verify")[1]
        self.assertEqual((v["ok"], v["bad_seq"]), (False, gone + 1))

    def test_chain_is_per_org_and_concurrent_appends_stay_valid(self):
        a, _ = self.make_org("A", "a@a.example")
        b, _ = self.make_org("B", "b@b.example")

        def work(org):
            conn = self.st.conn()
            for i in range(25):
                audit.append(conn, org, None, "test.concurrent", f"t:{i}", {"i": i})
        ts = [threading.Thread(target=work, args=(o,)) for o in (a, a, b)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(audit.verify(self.conn, a), {"ok": True, "bad_seq": None, "count": 50})
        self.assertEqual(audit.verify(self.conn, b)["count"], 25)

    def test_csv_export_is_injection_safe(self):
        org, uid = self.make_org()
        c = self.client("owner@acme.example")
        audit.append(self.conn, org, uid, '=cmd|\' /C calc\'!A0', "+SUM(1+1)", {"x": 1}, "1.2.3.4", "@evil\tagent")
        audit.append(self.conn, org, "-2+3", "\t=1+1", "@SUM(A1)", {}, "", "")
        s, h, body = c.req("GET", "/api/v1/audit/export.csv")
        self.assertEqual(s, 200)
        self.assertTrue(h["content-type"].startswith("text/csv"))
        self.assertIn("attachment", h["content-disposition"])
        rows = list(csv.reader(io.StringIO(body.decode())))
        self.assertEqual(rows[0][:5], ["seq", "at", "user_id", "action", "target"])
        for row in rows[1:]:
            for cell in row:
                self.assertFalse(cell[:1] in ("=", "+", "-", "@", "\t", "\r"), f"unsafe cell {cell!r}")
        flat = [cell for row in rows for cell in row]
        self.assertIn("'=cmd|' /C calc'!A0", flat)
        self.assertIn("'+SUM(1+1)", flat)


if __name__ == "__main__":
    unittest.main()
