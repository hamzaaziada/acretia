"""Auth, sessions, CSRF, RBAC, invites and security primitives (SPEC §2.2, §4). Offline; real HTTP on port 0."""
import http.client
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from unittest import mock

from om.api import auth, db, deals, security, server, state as state_mod

PASSWORD = "correct-horse-battery"


class Client:
    def __init__(self, port):
        self.port, self.cookie, self.csrf = port, None, None

    def req(self, method, path, body=None, headers=None, origin=True, csrf=True, raw=None, cookie=True):
        h = dict(headers or {})
        if origin and "Origin" not in h:
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        if cookie and self.cookie:
            h["Cookie"] = f"acr_session={self.cookie}"
        if csrf and self.csrf and "X-CSRF-Token" not in h:
            h["X-CSRF-Token"] = self.csrf
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            payload = r.read()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, payload
        finally:
            c.close()

    def j(self, method, path, body=None, **kw):
        s, h, b = self.req(method, path, body, **kw)
        try:
            return s, (json.loads(b) if b else None), h
        except ValueError:
            return s, b, h

    def login(self, email, password=PASSWORD, org_id=None):
        body = {"email": email, "password": password}
        if org_id:
            body["org_id"] = org_id
        s, data, h = self.j("POST", "/api/v1/auth/login", body, csrf=False, cookie=False)
        if s == 200:
            sc = h["set-cookie"]
            self.cookie = sc.split(";")[0].split("=", 1)[1]
            self.csrf = data["csrf_token"]
        return s, data, h


class ServerCase(unittest.TestCase):
    def setUp(self):
        auth.LIMITER.reset_all() if hasattr(auth.LIMITER, "reset_all") else auth.LIMITER._fails.clear()
        self.tmp = tempfile.mkdtemp(prefix="acretia-test-")
        self.st = state_mod.create(self.tmp, llm_mode="replay")
        self.conn = self.st.conn()
        self.srv = server.make_server(self.st, "127.0.0.1", 0)
        self.port = self.srv.bound_port
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        deals.wait_idle(30)
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_org(self, name="Acme Capital", owner="owner@acme.example"):
        res = auth.create_org(self.conn, name, owner, PASSWORD, "Olive Owner")
        return res["org_id"], res["user_id"]

    def add_user(self, org_id, email, role, name="Test User"):
        uid = self.conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        uid = uid["id"] if uid else auth.create_user(self.conn, email, PASSWORD, name)
        auth.add_membership(self.conn, org_id, uid, role)
        return uid

    def client(self, email, org_id=None):
        c = Client(self.port)
        s, data, _ = c.login(email, org_id=org_id)
        assert s == 200, (s, data)
        return c


class SessionTests(ServerCase):
    def test_signup_gating(self):
        c = Client(self.port)
        body = {"email": "first@fund.example", "password": PASSWORD, "name": "First", "org_name": "Fund One"}
        s, data, h = c.j("POST", "/api/v1/auth/signup", body, csrf=False)
        self.assertEqual(s, 201, data)
        self.assertEqual(data["role"], "owner")
        self.assertIn("acr_session=", h["set-cookie"])
        s, data, _ = Client(self.port).j("POST", "/api/v1/auth/signup", dict(body, email="second@fund.example"), csrf=False)
        self.assertEqual(s, 403)
        self.assertEqual(data["error"]["code"], "signup_disabled")
        self.assertTrue(data["error"]["hint"])
        with mock.patch.dict(os.environ, {"ACRETIA_ALLOW_SIGNUP": "1"}):
            s, data, _ = Client(self.port).j("POST", "/api/v1/auth/signup", dict(body, email="second@fund.example", org_name="Fund Two"), csrf=False)
            self.assertEqual(s, 201, data)
            s, data, _ = Client(self.port).j("POST", "/api/v1/auth/signup", dict(body, email="third@fund.example", password="short"), csrf=False)
            self.assertEqual(s, 400)
            self.assertEqual(data["error"]["code"], "weak_password")
            s, data, _ = Client(self.port).j("POST", "/api/v1/auth/signup", dict(body, email="SECOND@fund.example"), csrf=False)
            self.assertEqual(s, 409)

    def test_login_ok_and_401(self):
        self.make_org()
        c = Client(self.port)
        s, data, h = c.login("owner@acme.example")
        self.assertEqual(s, 200)
        self.assertEqual(data["user"]["email"], "owner@acme.example")
        self.assertEqual(data["role"], "owner")
        self.assertTrue(data["csrf_token"])
        s, data, _ = Client(self.port).login("owner@acme.example", "wrong-password-here")
        self.assertEqual(s, 401)
        self.assertEqual(data["error"]["code"], "invalid_credentials")
        self.assertTrue(data["error"]["hint"])
        s, data, _ = Client(self.port).login("nobody@acme.example")
        self.assertEqual(s, 401)

    def test_rate_limit_on_eleventh_failure_even_with_spoofed_header(self):
        self.make_org()
        c = Client(self.port)
        for i in range(10):
            s, _, _ = c.j("POST", "/api/v1/auth/login", {"email": "owner@acme.example", "password": f"bad-password-{i}"},
                          csrf=False, headers={"X-Acretia-Client-Ip": f"9.9.9.{i}"})
            self.assertEqual(s, 401, i)
        s, data, h = c.j("POST", "/api/v1/auth/login", {"email": "owner@acme.example", "password": PASSWORD}, csrf=False)
        self.assertEqual(s, 429)
        self.assertEqual(data["error"]["code"], "rate_limited")
        self.assertTrue(data["error"]["hint"])
        self.assertIn("retry-after", h)

    def test_cookie_flags_and_no_token_in_json(self):
        self.make_org()
        c = Client(self.port)
        s, data, h = c.login("owner@acme.example")
        sc = h["set-cookie"]
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, sc)
        self.assertNotIn("Secure", sc)
        token = c.cookie
        self.assertGreaterEqual(len(token), 40)
        s, raw, _ = c.req("GET", "/api/v1/auth/me")
        self.assertNotIn(token.encode(), raw)
        self.assertNotIn(token, json.dumps(data))
        # only sha256 is stored
        rows = self.conn.execute("SELECT token_hash, csrf_hash FROM sessions").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["token_hash"], security.token_hash(token))
        self.assertNotEqual(rows[0]["csrf_hash"], data["csrf_token"])
        s, _, h2 = Client(self.port).j("POST", "/api/v1/auth/login", {"email": "owner@acme.example", "password": PASSWORD},
                                       csrf=False, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", h2["set-cookie"])

    def test_logout_and_forged_cookie(self):
        self.make_org()
        c = self.client("owner@acme.example")
        old = c.cookie
        self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 200)
        s, _, h = c.j("POST", "/api/v1/auth/logout")
        self.assertEqual(s, 200)
        self.assertIn("Max-Age=0", h["set-cookie"])
        c.cookie = old
        s, data, _ = c.j("GET", "/api/v1/auth/me")
        self.assertEqual(s, 401)
        self.assertEqual(data["error"]["code"], "unauthenticated")
        self.assertEqual(data["error"]["hint"], "Sign in again.")
        for forged in ("x" * 43, "AAAA", old[:-1] + ("A" if old[-1] != "A" else "B"), "../../etc/passwd"):
            c.cookie = forged
            self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 401, forged)

    def test_idle_and_absolute_expiry(self):
        self.make_org()
        c = self.client("owner@acme.example")
        real = auth.clock
        t0 = real()
        with mock.patch.object(auth, "clock", lambda: t0 + 11 * 3600):
            self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 200)
        with mock.patch.object(auth, "clock", lambda: t0 + 11 * 3600 + 13 * 3600):
            self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 401)
        c = self.client("owner@acme.example")
        t0 = real()
        for hours in range(10, 7 * 24, 10):  # keep the session warm, never idle > 12 h
            with mock.patch.object(auth, "clock", lambda hours=hours: t0 + hours * 3600):
                self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 200, hours)
        with mock.patch.object(auth, "clock", lambda: t0 + 7 * 86400 + 600):
            self.assertEqual(c.j("GET", "/api/v1/auth/me")[0], 401)

    def test_switch_org_and_membership_removal_kills_session(self):
        a, _ = self.make_org("Org A", "a@acme.example")
        b, _ = self.make_org("Org B", "b@acme.example")
        self.add_user(a, "b@acme.example", "viewer")
        c = self.client("b@acme.example", org_id=b)
        s, data, _ = c.j("GET", "/api/v1/auth/me")
        self.assertEqual((data["org"]["id"], data["role"], len(data["orgs"])), (b, "owner", 2))
        s, data, _ = c.j("POST", "/api/v1/auth/switch-org", {"org_id": a})
        self.assertEqual((s, data["role"]), (200, "viewer"))
        s, data, _ = c.j("POST", "/api/v1/auth/switch-org", {"org_id": "org_0000000000000000"})
        self.assertEqual(s, 404)

    def test_preferences(self):
        self.make_org()
        c = self.client("owner@acme.example")
        s, data, _ = c.j("GET", "/api/v1/me/preferences")
        self.assertEqual(data, {"theme": "system", "locale": "en", "digits": "latn"})
        s, data, _ = c.j("PUT", "/api/v1/me/preferences", {"theme": "dark", "locale": "ar", "digits": "arab"})
        self.assertEqual((s, data["theme"], data["locale"], data["digits"]), (200, "dark", "ar", "arab"))
        self.assertEqual(c.j("GET", "/api/v1/auth/me")[1]["user"]["preferences"]["theme"], "dark")
        s, data, _ = c.j("PUT", "/api/v1/me/preferences", {"theme": "neon"})
        self.assertEqual((s, data["error"]["code"]), (400, "bad_preference"))
        s, data, _ = c.j("PUT", "/api/v1/me/preferences", {"unknown": 1})
        self.assertEqual(s, 400)


class CsrfTests(ServerCase):
    def test_csrf_matrix(self):
        self.make_org()
        c = self.client("owner@acme.example")
        deal = {"name": "Project CSRF"}
        s, data, _ = c.j("POST", "/api/v1/deals", deal, csrf=False)
        self.assertEqual((s, data["error"]["code"]), (403, "csrf_failed"))
        s, data, _ = c.j("POST", "/api/v1/deals", deal, headers={"X-CSRF-Token": "0" * 64})
        self.assertEqual((s, data["error"]["code"]), (403, "csrf_failed"))
        s, data, _ = c.j("POST", "/api/v1/deals", deal, headers={"Origin": "https://evil.example"})
        self.assertEqual((s, data["error"]["code"]), (403, "csrf_failed"))
        s, data, _ = c.j("POST", "/api/v1/deals", deal, origin=False)
        self.assertEqual(s, 403)
        s, data, _ = c.j("POST", "/api/v1/deals", deal, origin=False, headers={"Referer": "https://evil.example/x"})
        self.assertEqual(s, 403)
        s, data, _ = c.j("POST", "/api/v1/deals", deal, origin=False, headers={"Origin": "null"})
        self.assertEqual(s, 403)
        self.assertTrue(data["error"]["hint"])
        # another session's token is wrong for this one
        other = self.client("owner@acme.example")
        s, _, _ = c.j("POST", "/api/v1/deals", deal, headers={"X-CSRF-Token": other.csrf})
        self.assertEqual(s, 403)
        # correct token + Origin; Referer is accepted when Origin is absent
        s, data, _ = c.j("POST", "/api/v1/deals", deal)
        self.assertEqual(s, 201, data)
        s, data, _ = c.j("POST", "/api/v1/deals", {"name": "Project Referer"}, origin=False,
                         headers={"Referer": f"http://127.0.0.1:{self.port}/deals"})
        self.assertEqual(s, 201, data)
        # GET needs no token
        self.assertEqual(c.j("GET", "/api/v1/deals", csrf=False, origin=False)[0], 200)
        # the token from /auth/me works as well
        me = c.j("GET", "/api/v1/auth/me")[1]
        self.assertEqual(me["csrf_token"], c.csrf)
        # login is Origin-checked
        s, data, _ = Client(self.port).j("POST", "/api/v1/auth/login", {"email": "owner@acme.example", "password": PASSWORD},
                                         csrf=False, headers={"Origin": "https://evil.example"})
        self.assertEqual((s, data["error"]["code"]), (403, "csrf_failed"))


class InviteAndRoleTests(ServerCase):
    def test_invite_flow(self):
        org, _ = self.make_org()
        owner = self.client("owner@acme.example")
        s, data, _ = owner.j("POST", "/api/v1/org/invites", {"email": "new@acme.example", "role": "viewer"})
        self.assertEqual(s, 201, data)
        token = data["token"]
        self.assertNotIn("token", json.dumps(owner.j("GET", "/api/v1/org/invites")[1]))
        new = Client(self.port)
        s, d, h = new.j("POST", "/api/v1/auth/invites/accept", {"token": "nope", "name": "N", "password": PASSWORD}, csrf=False)
        self.assertEqual((s, d["error"]["code"]), (400, "invite_invalid"))
        s, d, h = new.j("POST", "/api/v1/auth/invites/accept", {"token": token, "name": "New Person", "password": PASSWORD}, csrf=False)
        self.assertEqual((s, d["role"], d["org"]["id"]), (200, "viewer", org))
        self.assertIn("acr_session", h["set-cookie"])
        s, d, _ = new.j("POST", "/api/v1/auth/invites/accept", {"token": token, "name": "N", "password": PASSWORD}, csrf=False)
        self.assertEqual(s, 400)  # single use
        s, d, _ = owner.j("GET", "/api/v1/org/members")
        self.assertEqual({m["email"]: m["role"] for m in d["items"]}["new@acme.example"], "viewer")
        # an invite for an existing user needs that user's password
        s, data, _ = owner.j("POST", "/api/v1/org/invites", {"email": "owner@acme.example", "role": "member"})
        s, d, _ = Client(self.port).j("POST", "/api/v1/auth/invites/accept", {"token": data["token"], "password": "wrong"}, csrf=False)
        self.assertEqual(s, 401)

    def test_last_owner_guard(self):
        org, owner_id = self.make_org()
        owner = self.client("owner@acme.example")
        s, d, _ = owner.j("PATCH", f"/api/v1/org/members/{owner_id}", {"role": "member"})
        self.assertEqual((s, d["error"]["code"]), (409, "last_owner"))
        self.assertTrue(d["error"]["hint"])
        s, d, _ = owner.j("DELETE", f"/api/v1/org/members/{owner_id}")
        self.assertEqual((s, d["error"]["code"]), (409, "last_owner"))
        other = self.add_user(org, "second@acme.example", "member")
        s, d, _ = owner.j("PATCH", f"/api/v1/org/members/{other}", {"role": "owner"})
        self.assertEqual((s, d["role"]), (200, "owner"))
        s, d, _ = owner.j("PATCH", f"/api/v1/org/members/{owner_id}", {"role": "member"})
        self.assertEqual((s, d["role"]), (200, "member"))
        # remove the member: their sessions die
        m = self.client("second@acme.example")
        s, _, _ = m.j("DELETE", f"/api/v1/org/members/{owner_id}")
        self.assertEqual(s, 200)
        self.assertEqual(self.client("second@acme.example").j("DELETE", f"/api/v1/org/members/{other}")[0], 409)

    def test_viewer_and_member_restrictions(self):
        org, owner_id = self.make_org()
        viewer_id = self.add_user(org, "viewer@acme.example", "viewer")
        self.add_user(org, "member@acme.example", "member")
        viewer, member = self.client("viewer@acme.example"), self.client("member@acme.example")
        exempt = {("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/switch-org"), ("PUT", "/api/v1/me/preferences"),
                  ("POST", "/api/v1/notifications/read-all"), ("POST", "/api/v1/notifications/{id}/read"),
                  ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/signup"), ("POST", "/api/v1/auth/invites/accept")}
        checked = 0
        for r in server.all_routes():
            if r.method in ("GET", "HEAD") or (r.method, r.pattern) in exempt or r.role == "public":
                continue
            path = r.pattern.replace("{user_id}", viewer_id)
            for k in ("deal_id", "doc_id", "name", "v", "n", "id", "job_id", "invite_id"):
                path = path.replace("{" + k + "}", "x")
            if r.role in ("member", "owner"):
                s, d, _ = viewer.j(r.method, path, {})
                self.assertEqual(s, 403, (r.method, r.pattern, s))
                self.assertTrue(d["error"]["hint"])
                checked += 1
            if r.role == "owner":
                s, d, _ = member.j(r.method, path, {})
                self.assertEqual(s, 403, (r.method, r.pattern, s))
                checked += 1
        self.assertGreater(checked, 10)
        for path in ("/api/v1/audit", "/api/v1/audit/verify", "/api/v1/audit/export.csv", "/api/v1/org/invites"):
            self.assertEqual(member.j("GET", path)[0], 403, path)
            self.assertEqual(viewer.j("GET", path)[0], 403, path)
        self.assertEqual(member.j("GET", "/api/v1/org/members")[0], 200)
        self.assertEqual(viewer.j("GET", "/api/v1/org/members")[0], 403)
        self.assertEqual(viewer.j("GET", "/api/v1/deals")[0], 200)
        self.assertEqual(member.j("POST", "/api/v1/deals", {"name": "Member deal"})[0], 201)


class SecurityUnitTests(unittest.TestCase):
    def test_password_hash_format_and_verify(self):
        h = security.hash_password(PASSWORD)
        parts = h.split("$")
        self.assertEqual(parts[:4], ["scrypt", "16384", "8", "1"])
        self.assertTrue(security.verify_password(PASSWORD, h))
        self.assertFalse(security.verify_password(PASSWORD + "x", h))
        self.assertFalse(security.verify_password(PASSWORD, "garbage"))
        self.assertNotEqual(h, security.hash_password(PASSWORD))

    def test_secret_encryption(self):
        key = os.urandom(32)
        blob = security.encrypt_secret(key, "imap-pass-1234")
        self.assertNotIn("imap-pass", blob)
        self.assertEqual(security.decrypt_secret(key, blob), "imap-pass-1234")
        self.assertNotEqual(blob, security.encrypt_secret(key, "imap-pass-1234"))
        with self.assertRaises(ValueError):
            security.decrypt_secret(os.urandom(32), blob)
        tampered = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
        with self.assertRaises(ValueError):
            security.decrypt_secret(key, tampered)
        self.assertEqual(security.mask_secret("imap-pass-1234"), "••••1234")
        self.assertEqual(security.mask_secret(""), "")
        long_text = "é" * 200
        self.assertEqual(security.decrypt_secret(key, security.encrypt_secret(key, long_text)), long_text)

    def test_secret_key_file_mode(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACRETIA_SECRET_KEY", None)
            k1 = security.load_secret_key(d)
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "secret.key")).st_mode), 0o600)
            self.assertEqual(k1, security.load_secret_key(d))
            with mock.patch.dict(os.environ, {"ACRETIA_SECRET_KEY": "x" * 10}):
                self.assertNotEqual(security.load_secret_key(d), k1)

    def test_rate_limiter_window(self):
        now = [1000.0]
        lim = security.RateLimiter(limit=3, window=60, clock=lambda: now[0])
        for _ in range(3):
            self.assertFalse(lim.blocked("k"))
            lim.fail("k")
        self.assertTrue(lim.blocked("k"))
        now[0] += 61
        self.assertFalse(lim.blocked("k"))

    def test_sniff(self):
        self.assertEqual(security.sniff(b"%PDF-1.7\n..."), "pdf")
        self.assertEqual(security.sniff(b"\x89PNG\r\n\x1a\n...."), "png")
        self.assertEqual(security.sniff(b"\xff\xd8\xff\xe0...."), "jpg")
        self.assertEqual(security.sniff(b"From: a@b.c\nSubject: hi\n\nbody"), "eml")
        self.assertEqual(security.sniff(b"a,b,c,d\n1,2,3,4\n5,6,7,8\n", "x.csv"), "csv")
        self.assertEqual(security.sniff(b"just some notes", "n.txt"), "txt")
        self.assertIsNone(security.sniff(b"<html><script>alert(1)</script>", "x.pdf"))
        self.assertIsNone(security.sniff(b"MZ\x90\x00\x03\x00\x00\x00", "x.pdf"))
        self.assertIsNone(security.sniff(b"\x7fELF\x00\x01", "x.txt"))


if __name__ == "__main__":
    unittest.main()
