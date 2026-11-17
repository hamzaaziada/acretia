"""Tenancy: route-table driven cross-org probes. Every route with a {param} must answer 404 for another org's
real ids, and no list may leak the other org's ids. Routes added by later packets are covered automatically."""
import json
import re
import unittest
import uuid

from om.api import deals, notify, server
from om.pdfwrite import PDFWriter
try:
    from tests.test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401
except ImportError:  # `unittest discover -s tests` puts tests/ itself on sys.path
    from test_api_auth import Client, PASSWORD, ServerCase  # noqa: F401

STREAMING = ("/events",)


def tiny_pdf(text="Confidential change of control clause"):
    w = PDFWriter()
    w.text(72, 700, text, size=12)
    w.text(72, 680, "Revenue 1,200 1,100", size=10)
    return w.to_bytes()


class TenancyTests(ServerCase):
    def setUp(self):
        super().setUp()
        self.org_a, self.owner_a = self.make_org("Org A", "a-owner@a.example")
        self.org_b, self.owner_b = self.make_org("Org B", "b-owner@b.example")
        self.a, self.b = self.client("a-owner@a.example"), self.client("b-owner@b.example")
        s, deal, _ = self.a.j("POST", "/api/v1/deals", {"name": "Secret Deal A"})
        self.assertEqual(s, 201, deal)
        self.deal_id = deal["deal_id"]
        s, up, _ = self.a.j("POST", f"/api/v1/deals/{self.deal_id}/documents", raw=tiny_pdf(),
                              headers={"X-Filename": "secret-a.pdf", "Content-Type": "application/pdf"})
        self.assertEqual(s, 201, up)
        self.doc_id = up["items"][0]["id"]
        self.assertTrue(deals.wait_idle(60))
        store = self.st.deal_store(self.conn, self.org_a)
        store.save_deliverable(self.deal_id, "Model A.txt", b"v1", "other")
        store.save_deliverable(self.deal_id, "Model A.txt", b"v2", "other")
        self.ntf = notify.notify(self.conn, self.org_a, None, "info", "Secret A notice", "body")["id"]
        s, inv, _ = self.a.j("POST", "/api/v1/org/invites", {"email": "secret-invitee@a.example", "role": "viewer"})
        self.invite_id = inv["invite"]["id"]
        self.secrets = [self.deal_id, self.doc_id, self.ntf, self.invite_id, self.owner_a, "secret-a.pdf",
                        "Secret Deal A", "Model A.txt", "a-owner@a.example", "secret-invitee@a.example", self.org_a]

    def real_params(self, pattern):
        known = {"deal_id": self.deal_id, "doc_id": self.doc_id, "user_id": self.owner_a, "name": "Model A.txt",
                 "v": "1", "n": "1", "invite_id": self.invite_id}
        out, complete = {}, True
        for p in re.findall(r"\{(\w+)\}", pattern):
            if p == "id" and "/notifications/" in pattern:
                out[p] = self.ntf
            elif p in known:
                out[p] = known[p]
            else:
                out[p] = "x" + uuid.uuid4().hex[:12]
                complete = False
        return out, complete

    @staticmethod
    def fill(pattern, params):
        from urllib.parse import quote
        for k, v in params.items():
            pattern = pattern.replace("{" + k + "}", quote(v, safe=""))
        return pattern

    def test_cross_org_ids_are_404_on_every_parametrised_route(self):
        tested, skipped = [], []
        for r in server.all_routes():
            if "{" not in r.pattern or r.role == "public":
                continue
            if r.pattern.endswith(STREAMING):
                skipped.append(f"{r.method} {r.pattern} (stream)")
                continue
            params, complete = self.real_params(r.pattern)
            path = self.fill(r.pattern, params)
            body = {} if r.method in ("POST", "PUT", "PATCH", "DELETE") else None
            s, data, _ = self.b.j(r.method, path, body)
            self.assertEqual(s, 404, f"{r.method} {r.pattern} as org B -> {s} {data!r}")
            self.assertNotIn("hint_leak", json.dumps(data))
            for secret in self.secrets:
                self.assertNotIn(secret, json.dumps(data) if not isinstance(data, bytes) else data.decode("utf-8", "replace"))
            tested.append(f"{r.method} {r.pattern}")
            if r.method == "GET" and complete:  # positive control: the real owner is not told 404
                s, _, _ = self.a.j(r.method, path)
                self.assertNotEqual(s, 404, f"control failed: {r.method} {r.pattern} as org A -> {s}")
        self.assertGreaterEqual(len(tested), 15)
        print(f"\ntenancy: {len(tested)} parametrised routes probed cross-org; skipped: {skipped or 'none'}")

    def test_lists_never_leak(self):
        probed = []
        for r in server.all_routes():
            if r.method != "GET" or "{" in r.pattern or r.role == "public" or r.pattern.endswith(STREAMING):
                continue
            if r.pattern.endswith(("/auth/me",)):
                continue
            s, h, body = self.b.req("GET", r.pattern)
            text = body.decode("utf-8", "replace")
            self.assertNotEqual(s, 500, r.pattern)
            if s == 200:
                for secret in self.secrets:
                    self.assertNotIn(secret, text, f"{r.pattern} leaked {secret!r} to org B")
            probed.append(r.pattern)
        self.assertIn("/api/v1/deals", probed)
        self.assertIn("/api/v1/library", probed)
        s, d, _ = self.b.j("GET", "/api/v1/deals")
        self.assertEqual(d["items"], [])
        s, d, _ = self.a.j("GET", "/api/v1/deals")
        self.assertEqual([x["deal_id"] for x in d["items"]], [self.deal_id])
        s, d, _ = self.a.j("GET", "/api/v1/library")
        self.assertEqual([x["name"] for x in d["items"]], ["Model A.txt"])
        s, d, _ = self.b.j("GET", "/api/v1/library")
        self.assertEqual(d["items"], [])
        s, d, _ = self.b.j("GET", "/api/v1/notifications")
        self.assertEqual(d["items"], [])
        s, d, _ = self.a.j("GET", "/api/v1/notifications")
        self.assertEqual([x["id"] for x in d["items"]], [self.ntf])

    def test_org_b_cannot_act_on_a_resources(self):
        s, _, _ = self.b.j("POST", f"/api/v1/deals/{self.deal_id}/documents", raw=tiny_pdf(), headers={"X-Filename": "x.pdf"})
        self.assertEqual(s, 404)
        s, _, _ = self.b.j("PATCH", f"/api/v1/deals/{self.deal_id}", {"name": "pwned"})
        self.assertEqual(s, 404)
        s, d, _ = self.a.j("GET", f"/api/v1/deals/{self.deal_id}")
        self.assertEqual(d["name"], "Secret Deal A")
        s, _, _ = self.b.j("POST", f"/api/v1/deals/{self.deal_id}/deliverables/Model%20A.txt/undo", {})
        self.assertEqual(s, 404)
        self.assertEqual(len(self.st.deal_store(self.conn, self.org_a).history(self.deal_id, "Model A.txt")), 2)
        s, _, _ = self.b.j("POST", "/api/v1/auth/switch-org", {"org_id": self.org_a})
        self.assertEqual(s, 404)
        s, _, _ = self.b.j("POST", f"/api/v1/notifications/{self.ntf}/read", {})
        self.assertEqual(s, 404)
        self.assertIsNone(self.conn.execute("SELECT read_at FROM notifications WHERE id=?", (self.ntf,)).fetchone()[0])

    def test_session_of_removed_member_is_dead(self):
        member = self.add_user(self.org_a, "gone@a.example", "member")
        c = self.client("gone@a.example")
        self.assertEqual(c.j("GET", "/api/v1/deals")[0], 200)
        self.a.j("DELETE", f"/api/v1/org/members/{member}")
        self.assertEqual(c.j("GET", "/api/v1/deals")[0], 401)


if __name__ == "__main__":
    unittest.main()
