"""Firm setup API: definitions, templates (style cloned), connectors, mailbox, limits, memory (SF.6)."""
import io
import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from om.api import firm, mail, security
try:
    from tests.test_api_auth import PASSWORD, ServerCase  # noqa: F401
except ImportError:
    from test_api_auth import PASSWORD, ServerCase  # noqa: F401

P = "/api/v1"


def make_pptx(accent="1F6FEB", title="Quarterly review") -> bytes:
    from pptx import Presentation
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def png() -> bytes:
    import base64
    return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FirmCase(ServerCase):
    def setUp(self):
        super().setUp()
        self.org, self.owner_id = self.make_org("Meridian", "owner@meridian.example")
        self.add_user(self.org, "member@meridian.example", "member")
        self.add_user(self.org, "viewer@meridian.example", "viewer")
        self.owner = self.client("owner@meridian.example")
        self.member = self.client("member@meridian.example")
        self.viewer = self.client("viewer@meridian.example")

    def deal(self, name="Project Atlas"):
        s, d, _ = self.owner.j("POST", f"{P}/deals", {"name": name})
        self.assertEqual(s, 201, d)
        return d["deal_id"]

    def defs_of(self, deal_id):
        return self.st.deal_store(self.conn, self.org).get(deal_id).definitions

    def upload(self, client, data, name, kind):
        return client.j("POST", f"{P}/firm/assets", raw=data, headers={"X-Filename": name, "X-Asset-Kind": kind,
                                                                         "Content-Type": "application/octet-stream"})


class DefinitionTests(FirmCase):
    def put(self, ebitda, net_debt="Debt less cash."):
        return self.owner.j("PUT", f"{P}/firm/definitions", {"items": [
            {"key": "adjusted_ebitda", "label": "Adjusted EBITDA", "text": ebitda, "formula_hint": "EBIT + D&A + SBC"},
            {"key": "net_debt", "label": "Net debt", "text": net_debt}]})

    def test_seeded_then_crud_and_new_deal_inherits(self):
        s, d, _ = self.member.j("GET", f"{P}/firm/definitions")
        self.assertEqual(s, 200)
        self.assertEqual({i["key"] for i in d["items"]}, {"adjusted_ebitda", "net_debt"})
        s, d, _ = self.put("EBITDA plus SBC (v1).")
        self.assertEqual(s, 200, d)
        self.assertEqual(d["changed"], ["adjusted_ebitda", "net_debt"])
        item = next(i for i in d["items"] if i["key"] == "adjusted_ebitda")
        self.assertEqual(item["updated_by"], self.owner_id)
        d1 = self.deal()
        self.assertEqual(self.defs_of(d1)["adjusted_ebitda"], "EBITDA plus SBC (v1).")
        self.assertEqual(self.defs_of(d1)["net_debt"], "Debt less cash.")
        # add and remove
        s, d, _ = self.owner.j("PUT", f"{P}/firm/definitions", {"items": [
            {"key": "adjusted_ebitda", "label": "Adjusted EBITDA", "text": "EBITDA plus SBC (v1).", "formula_hint": "EBIT + D&A + SBC"},
            {"key": "arr", "label": "ARR", "text": "Annualised recurring revenue."}]})
        self.assertEqual(d["removed"], ["net_debt"])
        self.assertEqual({i["key"] for i in d["items"]}, {"adjusted_ebitda", "arr"})

    def test_change_flags_old_deals_and_apply(self):
        self.put("v1 text")
        d1, d2 = self.deal("A"), self.deal("B")
        self.owner.j("PATCH", f"{P}/deals/{d2}", {})  # no-op
        self.st.deal_store(self.conn, self.org).set_definition(d2, "adjusted_ebitda", "deal-specific override")
        s, d, _ = self.put("v2 text")
        item = next(i for i in d["items"] if i["key"] == "adjusted_ebitda")
        self.assertEqual(item["outdated_deals"], 1, "only the deal on the old firm text counts; the override does not")
        self.assertEqual(item["outdated_deal_ids"], [d1])
        self.assertEqual(self.defs_of(d1)["adjusted_ebitda"], "v1 text", "changing a definition never mutates deals")
        s, r, _ = self.owner.j("POST", f"{P}/firm/definitions/apply", {"deal_ids": [d1, d2]})
        self.assertEqual(s, 200, r)
        self.assertEqual(r["applied"], [{"deal_id": d1, "keys": ["adjusted_ebitda"]}])
        self.assertEqual(self.defs_of(d1)["adjusted_ebitda"], "v2 text")
        self.assertEqual(self.defs_of(d2)["adjusted_ebitda"], "deal-specific override")
        self.assertEqual(next(i for i in r["items"] if i["key"] == "adjusted_ebitda")["outdated_deals"], 0)

    def test_validation_and_rbac(self):
        for body in ({"items": [{"key": "Bad Key", "text": "x"}]}, {"items": [{"key": "ok", "text": ""}]},
                     {"items": [{"key": "a", "text": "x"}, {"key": "a", "text": "y"}]}, {"items": "no"}):
            s, d, _ = self.owner.j("PUT", f"{P}/firm/definitions", body)
            self.assertEqual(s, 400, body)
            self.assertTrue(d["error"]["hint"])
        for c in (self.member, self.viewer):
            s, d, _ = c.j("PUT", f"{P}/firm/definitions", {"items": []})
            self.assertEqual(s, 403)
        self.assertEqual(self.viewer.j("GET", f"{P}/firm/definitions")[0], 403)
        s, _, _ = self.owner.j("POST", f"{P}/firm/definitions/apply", {"deal_ids": ["deal-nope"]})
        self.assertEqual(s, 404)


class AssetTests(FirmCase):
    def test_template_style_extracted_and_default(self):
        s, a, _ = self.upload(self.owner, make_pptx(), "House Template.pptx", "template")
        self.assertEqual(s, 201, a)
        self.assertTrue(a["is_default"])
        st = a["style"]
        self.assertTrue(len(st["palette"]) >= 4 and all(p["hex"].startswith("#") for p in st["palette"]))
        self.assertIn("major", st["fonts"])
        self.assertTrue(st["layouts"])
        self.assertEqual(len(st["slide_size_in"]), 2)
        prof = firm.house_profile(self.conn, self.org)
        self.assertIn("theme", prof)
        s, b, _ = self.upload(self.owner, make_pptx(title="Second"), "Alt.pptx", "template")
        self.assertFalse(b["is_default"])
        s, c, _ = self.owner.j("PATCH", f"{P}/firm/assets/{b['id']}", {"is_default": True})
        self.assertEqual(s, 200)
        s, lst, _ = self.member.j("GET", f"{P}/firm/assets")
        self.assertEqual({i["id"]: i["is_default"] for i in lst["items"] if i["kind"] == "template"}, {a["id"]: False, b["id"]: True})
        # sample deck is cloned too and re-derives the template style
        s, sd, _ = self.upload(self.owner, make_pptx(title="Sample"), "Sample.pptx", "sample_deck")
        self.assertEqual(s, 201, sd)
        self.assertTrue(sd["style"]["palette"])
        s, h, f = self.member.req("GET", f"{P}/firm/assets/{a['id']}/file")
        self.assertEqual(s, 200)
        self.assertIn("attachment", h["content-disposition"])
        s, _, _ = self.owner.j("DELETE", f"{P}/firm/assets/{b['id']}")
        self.assertEqual(s, 200)
        self.assertTrue(self.owner.j("GET", f"{P}/firm/assets")[1]["items"])

    def test_sniffing_and_clone_failure_hints(self):
        s, d, _ = self.upload(self.owner, b"<html><script>alert(1)</script></html>", "evil.pptx", "template")
        self.assertEqual(s, 415)
        self.assertTrue(d["error"]["hint"])
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:                    # looks like an Office package, is not a presentation
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("ppt/presentation.xml", "<x/>")
        s, d, _ = self.upload(self.owner, buf.getvalue(), "broken.pptx", "template")
        self.assertEqual(s, 422, d)
        self.assertEqual(d["error"]["code"], "template_unreadable")
        self.assertIn("save it", d["error"]["hint"])
        self.assertEqual(self.owner.j("GET", f"{P}/firm/assets")[1]["items"], [])
        s, d, _ = self.upload(self.owner, make_pptx(), "t.pptx", "nonsense")
        self.assertEqual(s, 400)
        s, d, _ = self.upload(self.owner, png(), "logo.png", "logo")
        self.assertEqual(s, 201, d)
        s, h, f = self.member.req("GET", f"{P}/firm/assets/{d['id']}/file")
        self.assertEqual(h["content-type"], "image/png")

    def test_rbac(self):
        for c in (self.member, self.viewer):
            self.assertEqual(self.upload(c, make_pptx(), "t.pptx", "template")[0], 403)
        self.assertEqual(self.viewer.j("GET", f"{P}/firm/assets")[0], 403)
        s, a, _ = self.upload(self.owner, make_pptx(), "t.pptx", "template")
        self.assertEqual(self.member.j("DELETE", f"{P}/firm/assets/{a['id']}")[0], 403)


class ConnectorTests(FirmCase):
    SECRET = "s3-super-secret-0123456789abcdef"

    def make(self, **over):
        body = {"kind": "s3", "name": "Deal archive", "config": {"endpoint": "https://s3.eu-west-1.amazonaws.com", "bucket": "meridian-deals"},
                "secret": self.SECRET}
        body.update(over)
        return self.owner.j("POST", f"{P}/firm/connectors", body)

    def test_secret_masked_encrypted_never_returned(self):
        s, c, h = self.make()
        self.assertEqual(s, 201, c)
        self.assertEqual(c["secret"], "••••cdef")
        self.assertTrue(c["has_secret"])
        blobs = [json.dumps(c)]
        s, lst, _ = self.member.j("GET", f"{P}/firm/connectors")
        blobs.append(json.dumps(lst))
        self.assertEqual(lst["summary"]["total"], 1)
        raw = self.conn.execute("SELECT secret_enc, config_json FROM connectors").fetchone()
        self.assertNotIn(self.SECRET, raw["secret_enc"] + raw["config_json"])
        self.assertTrue(raw["secret_enc"].startswith("v1$"))
        self.assertEqual(security.decrypt_secret(self.st.secret_key, raw["secret_enc"]), self.SECRET)
        self.assertEqual(firm.decrypt_connector_secret(self.conn, self.org, c["id"]), self.SECRET)
        # the secret is nowhere in the database file at all
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")
        self.assertNotIn(self.SECRET.encode(), Path(self.st.db_path).read_bytes())
        for b in blobs:
            self.assertNotIn(self.SECRET, b)
        # sending the mask back keeps the stored secret; a new value rotates it
        s, p, _ = self.owner.j("PATCH", f"{P}/firm/connectors/{c['id']}", {"secret": c["secret"], "name": "Renamed"})
        self.assertEqual(p["name"], "Renamed")
        self.assertEqual(firm.decrypt_connector_secret(self.conn, self.org, c["id"]), self.SECRET)
        s, p, _ = self.owner.j("PATCH", f"{P}/firm/connectors/{c['id']}", {"secret": "rotated-token-value-9999"})
        self.assertEqual(p["secret"], "••••9999")
        self.assertEqual(firm.decrypt_connector_secret(self.conn, self.org, c["id"]), "rotated-token-value-9999")

    def test_validation_guards(self):
        s, d, _ = self.make(config={"endpoint": "https://s3.example.com", "bucket": "b", "token": "abc"})
        self.assertEqual(s, 400)
        self.assertIn("secret", d["error"]["hint"])
        s, d, _ = self.make(config={"endpoint": "https://169.254.169.254", "bucket": "b"})
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "host_not_allowed")
        s, d, _ = self.make(config={"endpoint": "https://10.0.0.5", "bucket": "b"})
        self.assertEqual(s, 400)
        s, d, _ = self.make(config={"endpoint": "http://s3.example.com", "bucket": "b"})
        self.assertEqual(s, 400)
        s, d, _ = self.make(secret=None)
        self.assertEqual(s, 400)
        s, d, _ = self.make(kind="local_folder", config={"path": "/etc"}, secret=None)
        self.assertEqual(s, 400)
        self.assertEqual(d["error"]["code"], "path_not_allowed")
        s, d, _ = self.make(kind="nope", config={})
        self.assertEqual(s, 400)
        s, kinds, _ = self.member.j("GET", f"{P}/firm/connectors/kinds")
        self.assertEqual({k["kind"] for k in kinds["items"]}, {"local_folder", "s3", "sharepoint", "google_drive", "vdr_export", "box", "dropbox"})

    def test_local_connector_test_reports_sync_fields(self):
        room = Path(self.tmp) / "room"
        (room / "sub").mkdir(parents=True)
        (room / "a.pdf").write_bytes(b"%PDF-1.4 x")
        (room / "sub" / "b.txt").write_bytes(b"hello")
        s, c, _ = self.make(kind="local_folder", name="VDR drop", config={"path": str(room)}, secret=None)
        self.assertEqual(s, 201, c)
        s, t, _ = self.owner.j("POST", f"{P}/firm/connectors/{c['id']}/test")
        self.assertEqual(s, 200, t)
        self.assertTrue(t["ok"])
        self.assertEqual(t["status"], "ok")
        self.assertEqual(t["items"], 2)
        con = t["connector"]
        self.assertEqual((con["item_count"], con["bytes"]), (2, 15))
        self.assertTrue(con["last_sync"])
        s, lst, _ = self.member.j("GET", f"{P}/firm/connectors")
        self.assertEqual(lst["summary"]["ok"], 1)
        self.assertEqual(lst["summary"]["items"], 2)
        s, c2, _ = self.make(kind="google_drive", config={"path": str(room / "missing")}, secret=None)
        s, t, _ = self.owner.j("POST", f"{P}/firm/connectors/{c2['id']}/test")
        self.assertFalse(t["ok"])
        self.assertEqual(t["status"], "error")
        self.assertTrue(t["hint"])
        # a network connector is only validated, not dialled
        s, c3, _ = self.make()
        s, t, _ = self.owner.j("POST", f"{P}/firm/connectors/{c3['id']}/test")
        self.assertEqual(t["status"], "configured")
        self.assertFalse(t["live"])

    def test_rbac_and_delete(self):
        s, c, _ = self.make()
        for cl in (self.member, self.viewer):
            self.assertEqual(cl.j("POST", f"{P}/firm/connectors", {"kind": "s3"})[0], 403)
            self.assertEqual(cl.j("DELETE", f"{P}/firm/connectors/{c['id']}")[0], 403)
            self.assertEqual(cl.j("POST", f"{P}/firm/connectors/{c['id']}/test")[0], 403)
        self.assertEqual(self.viewer.j("GET", f"{P}/firm/connectors")[0], 403)
        self.assertEqual(self.owner.j("DELETE", f"{P}/firm/connectors/{c['id']}")[0], 200)
        self.assertEqual(self.owner.j("GET", f"{P}/firm/connectors")[1]["items"], [])


class MailboxTests(FirmCase):
    def test_send_disabled_by_default_and_owner_only(self):
        s, d, _ = self.member.j("GET", f"{P}/firm/mailbox")
        self.assertEqual(s, 200)
        self.assertFalse(d["send_enabled"])
        self.assertFalse(d["configured"])
        md = Path(self.tmp) / "mail"
        for sub in ("new", "cur", "tmp"):
            (md / sub).mkdir(parents=True)
        body = {"kind": "maildir", "path": str(md), "allowed_senders": ["Client@Partner.example", "client@partner.example"]}
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", body)
        self.assertEqual(s, 200, d)
        self.assertFalse(d["send_enabled"])
        self.assertEqual(d["allowed_senders"], ["client@partner.example"])
        for c in (self.member, self.viewer):
            s, _, _ = c.j("PUT", f"{P}/firm/mailbox", dict(body, send_enabled=True))
            self.assertEqual(s, 403)
        self.assertFalse(self.owner.j("GET", f"{P}/firm/mailbox")[1]["send_enabled"])
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", dict(body, send_enabled=True))
        self.assertTrue(d["send_enabled"])
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", dict(body, send_enabled="yes"))
        self.assertEqual(s, 400)
        s, t, _ = self.owner.j("POST", f"{P}/firm/mailbox/test")
        self.assertTrue(t["ok"], t)
        self.assertEqual(t["messages"], 0)
        audit = [r["action"] for r in self.conn.execute("SELECT action FROM audit_log WHERE org_id=?", (self.org,))]
        self.assertIn("firm.mailbox.update", audit)

    def test_imap_secret_write_only_and_host_guard(self):
        body = {"kind": "imap", "host": "imap.meridian-mail.example", "port": 993, "username": "requests@meridian.example",
                "secret": "mailbox-password-WXYZ", "folder": "INBOX", "poll_seconds": 120}
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", body)
        self.assertEqual(s, 200, d)
        self.assertEqual(d["secret"], "••••WXYZ")
        self.assertNotIn("mailbox-password-WXYZ", json.dumps(self.member.j("GET", f"{P}/firm/mailbox")[1]))
        raw = self.conn.execute("SELECT secret_enc FROM mailbox").fetchone()[0]
        self.assertNotIn("mailbox-password", raw)
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", {"host": "imap.meridian-mail.example", "poll_seconds": 300})   # secret kept
        self.assertEqual(d["secret"], "••••WXYZ")
        for bad in (dict(body, host="127.0.0.1"), dict(body, host="192.168.1.10"), dict(body, host="localhost"),
                    dict(body, host="[::1]"), dict(body, poll_seconds=30), dict(body, port=0), dict(body, allowed_senders=["not-an-email"]),
                    dict(body, allowed_senders=["*@partner.example"])):
            s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", bad)
            self.assertEqual(s, 400, bad)
            self.assertTrue(d["error"]["hint"])
        # test goes through the verified-TLS connector; here it is stubbed
        class FakeImap:
            def select(self, folder, readonly=False):
                return "OK", [b"3"]

            def logout(self):
                return "BYE", []

        with mock.patch.object(mail, "connect_imap", return_value=FakeImap()) as ci:
            s, t, _ = self.owner.j("POST", f"{P}/firm/mailbox/test")
        self.assertTrue(t["ok"], t)
        self.assertEqual(t["messages"], 3)
        self.assertEqual(ci.call_args[0][1], "mailbox-password-WXYZ")

    def test_test_without_config_is_409(self):
        s, d, _ = self.owner.j("POST", f"{P}/firm/mailbox/test")
        self.assertEqual(s, 409)
        self.assertTrue(d["error"]["hint"])


class LimitTests(FirmCase):
    def test_limits_roundtrip_and_enforcement_helper(self):
        d1 = self.deal()
        s, d, _ = self.owner.j("PUT", f"{P}/firm/limits", {"org_monthly_usd": 100, "deal_usd": 20, "deals": {d1: 5}})
        self.assertEqual(s, 200, d)
        self.assertEqual((d["org_monthly_usd"], d["deal_usd"], d["deals"]), (100.0, 20.0, {d1: 5.0}))
        self.assertEqual(self.member.j("GET", f"{P}/firm/limits")[1]["usage"][0]["limit"], 5.0)
        self.assertTrue(firm.spend_limit(self.conn, self.org, d1)["allowed"])
        self.conn.execute("INSERT INTO jobs(id,org_id,deal_id,user_id,kind,prompt,status,cost_usd,created_at,source) VALUES('job_x1',?,?,?,'run','p','done',5.5,?,'app')",
                          (self.org, d1, self.owner_id, "2999-01-01T00:00:00"))
        lim = firm.spend_limit(self.conn, self.org, d1)
        self.assertFalse(lim["allowed"])
        self.assertEqual(lim["reason"], "deal_limit")
        self.assertIn("raise", lim["hint"])
        self.assertTrue(firm.spend_limit(self.conn, self.org, None)["allowed"])
        self.owner.j("PUT", f"{P}/firm/limits", {"org_monthly_usd": 5})
        self.assertEqual(firm.spend_limit(self.conn, self.org, None)["reason"], "org_limit")
        s, d, _ = self.owner.j("PUT", f"{P}/firm/limits", {"org_monthly_usd": None, "deals": {d1: None}})
        self.assertIsNone(d["org_monthly_usd"])
        lim = firm.spend_limit(self.conn, self.org, d1)
        self.assertTrue(lim["allowed"], "with the per-deal override cleared the $20 default applies and $5.50 is under it")
        self.assertEqual(lim["deal"]["limit"], 20.0)
        for bad in ({"org_monthly_usd": -1}, {"deal_usd": "ten"}, {"deals": {"deal-nope": 3}}, {"org_monthly_usd": True}):
            s, d, _ = self.owner.j("PUT", f"{P}/firm/limits", bad)
            self.assertIn(s, (400, 404), bad)
        self.assertEqual(self.member.j("PUT", f"{P}/firm/limits", {"deal_usd": 1})[0], 403)


class MemoryTests(FirmCase):
    def test_crud_with_sources(self):
        d1 = self.deal()
        s, m, _ = self.member.j("POST", f"{P}/firm/memory", {"text": "Prefers net debt incl. leases.", "scope": "org"})
        self.assertEqual(s, 201, m)
        s, m2, _ = self.owner.j("POST", f"{P}/firm/memory", {"text": "Target's FY ends in March.", "scope": "deal", "deal_id": d1,
                                                              "source_kind": "document", "source_ref": "doc_123"})
        self.assertEqual(m2["source_link"], f"/deals/{d1}/docs/doc_123")
        s, m3, _ = self.owner.j("POST", f"{P}/firm/memory", {"text": "From a run", "source_kind": "job", "source_ref": "job_abc"})
        self.assertEqual(m3["source_link"], "/runs/job_abc")
        s, lst, _ = self.viewer.j("GET", f"{P}/firm/memory")
        self.assertEqual(s, 403)
        s, lst, _ = self.member.j("GET", f"{P}/firm/memory?scope=deal&deal_id={d1}")
        self.assertEqual([i["id"] for i in lst["items"]], [m2["id"]])
        s, p, _ = self.member.j("PATCH", f"{P}/firm/memory/{m['id']}", {"text": "Prefers net debt excl. leases."})
        self.assertEqual(p["text"], "Prefers net debt excl. leases.")
        self.assertEqual(p["updated_by"], self.conn.execute("SELECT id FROM users WHERE email='member@meridian.example'").fetchone()[0])
        self.assertEqual(self.member.j("PATCH", f"{P}/firm/memory/{m2['id']}", {"text": "hijack"})[0], 403)
        self.assertEqual(self.member.j("DELETE", f"{P}/firm/memory/{m2['id']}")[0], 403)
        self.assertEqual(self.owner.j("DELETE", f"{P}/firm/memory/{m['id']}")[0], 200)
        self.assertEqual(self.owner.j("DELETE", f"{P}/firm/memory/{m['id']}")[0], 404)
        s, d, _ = self.owner.j("POST", f"{P}/firm/memory", {"text": "x", "scope": "deal", "deal_id": "deal-nope"})
        self.assertEqual(s, 404)
        self.assertEqual(self.owner.j("POST", f"{P}/firm/memory", {"text": ""})[0], 400)


class TenantTests(FirmCase):
    def test_other_org_sees_404_and_nothing(self):
        org_b, _ = self.make_org("Rival", "owner@rival.example")
        b = self.client("owner@rival.example")
        s, a, _ = self.upload(self.owner, make_pptx(), "t.pptx", "template")
        s, c, _ = self.owner.j("POST", f"{P}/firm/connectors", {"kind": "local_folder", "config": {"path": self.tmp}})
        s, m, _ = self.owner.j("POST", f"{P}/firm/memory", {"text": "secret note"})
        for method, path in (("PATCH", f"/firm/assets/{a['id']}"), ("DELETE", f"/firm/assets/{a['id']}"), ("GET", f"/firm/assets/{a['id']}/file"),
                             ("PATCH", f"/firm/connectors/{c['id']}"), ("DELETE", f"/firm/connectors/{c['id']}"),
                             ("POST", f"/firm/connectors/{c['id']}/test"), ("PATCH", f"/firm/memory/{m['id']}"), ("DELETE", f"/firm/memory/{m['id']}")):
            s, d, _ = b.j(method, P + path, {"text": "x"} if "memory" in path else {})
            self.assertEqual(s, 404, (method, path))
        for path in ("/firm/assets", "/firm/connectors", "/firm/memory"):
            self.assertEqual(b.j("GET", P + path)[1]["items"], [], path)
        self.assertNotIn("secret note", json.dumps(b.j("GET", f"{P}/firm/memory")[1]))
        self.assertEqual(b.j("GET", f"{P}/firm/definitions")[1]["deals"], [])


if __name__ == "__main__":
    unittest.main()
