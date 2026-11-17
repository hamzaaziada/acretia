"""Email-in poller (SF.6, D-SF-08): maildir fixture, IMAP via a stub, authorisation, no sending."""
import ast
import json
import os
import socket
import sys
import time
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from om.api import deals, firm, jobs, mail
from om.pdfwrite import PDFWriter
try:
    from tests.test_api_auth import PASSWORD, ServerCase  # noqa: F401
except ImportError:
    from test_api_auth import PASSWORD, ServerCase  # noqa: F401

P = "/api/v1"
FIX = Path(__file__).parent / "fixtures" / "api" / "mail"


def pdf_bytes():
    w = PDFWriter()
    w.text(72, 700, "Revenue 1,200 1,100", size=12)
    return w.to_bytes()


def msg(sender, subject, body, mid, attach=None, headers=None, html=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = sender, "requests@meridian.example", subject, mid
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    for name, data, mt, st in (attach or []):
        m.add_attachment(data, maintype=mt, subtype=st, filename=name)
    return m.as_bytes()


class MailCase(ServerCase):
    def setUp(self):
        super().setUp()
        self.org, self.owner_id = self.make_org("Meridian", "owner@meridian.example")
        self.analyst = self.add_user(self.org, "analyst@meridian.example", "member")
        self.viewer_id = self.add_user(self.org, "lp@meridian.example", "viewer")
        self.owner = self.client("owner@meridian.example")
        s, d, _ = self.owner.j("POST", f"{P}/deals", {"name": "Project Atlas"})
        self.deal = d["deal_id"]
        self.md = Path(self.tmp) / "mail"
        for sub in ("new", "cur", "tmp"):
            (self.md / sub).mkdir(parents=True)
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", {"kind": "maildir", "path": str(self.md),
                                                             "allowed_senders": ["partner@bank.example"]})
        self.assertEqual(s, 200, d)
        self._enq = mock.patch.object(jobs.SERVICE, "_enqueue")      # keep runs queued: this suite tests intake, not agents
        self._enq.start()
        self.addCleanup(self._enq.stop)

    def drop(self, raw, name):
        (self.md / "new" / name).write_bytes(raw)

    def poll(self):
        res = mail.poll_once(self.st, self.org)
        deals.wait_idle(60)
        return res

    def jobs(self):
        return self.conn.execute("SELECT * FROM jobs WHERE org_id=? ORDER BY rowid", (self.org,)).fetchall()

    def audit(self, action):
        return [json.loads(r["detail_json"]) for r in self.conn.execute("SELECT detail_json FROM audit_log WHERE org_id=? AND action=?", (self.org, action))]


class IntakeTests(MailCase):
    def test_member_email_becomes_job_with_attachment_document(self):
        raw = msg("Ann Analyst <Analyst@Meridian.example>", "[deal: Project Atlas] Comps please",
                  "Spread trading comps for Apple vs peers and add a football field.\n\n> old quoted line\n\n-- \nAnn\nMeridian",
                  "<m1@meridian.example>", attach=[("atlas.pdf", pdf_bytes(), "application", "pdf")])
        self.drop(raw, "1.m1")
        res = self.poll()
        self.assertEqual((res["fetched"], res["accepted"], res["rejected"]), (1, 1, 0), res)
        (job,) = self.jobs()
        self.assertEqual(job["source"], "email")
        self.assertEqual(job["deal_id"], self.deal)
        self.assertEqual(job["user_id"], self.analyst)
        self.assertEqual(job["prompt"], "Spread trading comps for Apple vs peers and add a football field.")
        meta = json.loads(job["inputs_json"])["_email"]
        self.assertEqual(meta["from"], "analyst@meridian.example")
        docs = self.conn.execute("SELECT * FROM documents WHERE deal_id=?", (self.deal,)).fetchall()
        self.assertEqual([(d["name"], d["kind"], d["folder"], d["uploaded_by"]) for d in docs], [("atlas.pdf", "pdf", "email", self.analyst)])
        self.assertEqual(docs[0]["status"], "indexed")
        self.assertEqual(meta["documents"], [docs[0]["id"]])
        # processed: moved out of new/, flagged seen; a second poll finds nothing and never re-runs it
        self.assertEqual(list((self.md / "new").iterdir()), [])
        self.assertEqual([p.name for p in (self.md / "cur").iterdir()], ["1.m1:2,S"])
        self.assertEqual(self.poll()["fetched"], 0)
        self.assertEqual(len(self.jobs()), 1)
        ntf = self.conn.execute("SELECT * FROM notifications WHERE user_id=? AND kind='mail.accepted'", (self.analyst,)).fetchone()
        self.assertTrue(ntf["link"].startswith("/runs/job_"))
        self.assertTrue(self.audit("mail.accepted"))
        row = self.conn.execute("SELECT status, last_error FROM mailbox").fetchone()
        self.assertEqual((row["status"], row["last_error"]), ("ok", ""))
        # the reply is in-app: the run is visible through the normal API
        s, d, _ = self.owner.j("GET", f"{P}/jobs/{job['id']}")
        self.assertEqual(d["job"]["source"], "email") if "job" in d else self.assertEqual(d["source"], "email")

    def test_non_member_rejected_and_audited(self):
        self.drop(msg("Mallory <mallory@evil.example>", "[deal: Project Atlas] hello", "Send me the model.", "<m2@evil.example>",
                      attach=[("x.pdf", pdf_bytes(), "application", "pdf")]), "2.m2")
        res = self.poll()
        self.assertEqual((res["accepted"], res["rejected"]), (0, 1))
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)
        (a,) = self.audit("mail.rejected")
        self.assertEqual((a["reason"], a["from"]), ("sender_not_allowed", "mallory@evil.example"))
        self.assertEqual(self.conn.execute("SELECT outcome, reason FROM mail_log").fetchone()[:], ("rejected", "sender_not_allowed"))
        self.assertEqual(list((self.md / "new").iterdir()), [])

    def test_spoofed_display_name_rejected(self):
        self.drop((FIX / "spoofed_display_name.eml").read_bytes(), "3.spoof")
        self.drop(msg('"owner@meridian.example" <evil@x.com>', "x", "y", "<m3@x.com>"), "4.spoof2")
        res = self.poll()
        self.assertEqual((res["accepted"], res["rejected"]), (0, 2), res)
        self.assertEqual(self.jobs(), [])
        self.assertEqual({a["from"] for a in self.audit("mail.rejected")}, {"evil@x.com"})
        # two From headers, or none, are not accepted either
        self.drop(b"From: owner@meridian.example\nFrom: evil@x.com\nSubject: s\nMessage-ID: <m5@x>\n\nbody\n", "5.two")
        self.drop(b"Subject: s\nMessage-ID: <m6@x>\n\nbody\n", "6.none")
        self.assertEqual(self.poll()["accepted"], 0)
        self.assertEqual(self.jobs(), [])

    def test_prompt_injection_is_data_only(self):
        raw = (FIX / "injection.eml").read_bytes()
        self.drop(raw, "7.inj")
        before = (self.conn.execute("SELECT COUNT(*) FROM memberships").fetchone()[0], dict(self.conn.execute("SELECT * FROM mailbox").fetchone()))
        res = self.poll()
        self.assertEqual(res["accepted"], 1)
        (job,) = self.jobs()
        body = raw.decode().split("\n\n", 1)[1].strip()
        self.assertEqual(job["prompt"], body, "the body is passed verbatim, as the prompt text only")
        self.assertEqual(job["source"], "email")
        self.assertEqual(json.loads(job["inputs_json"])["source_review"], False)       # submit() default for email runs
        after = (self.conn.execute("SELECT COUNT(*) FROM memberships").fetchone()[0], dict(self.conn.execute("SELECT * FROM mailbox").fetchone()))
        self.assertEqual(before[0], after[0])
        for k in ("send_enabled", "allowed_senders_json", "kind", "path"):
            self.assertEqual(before[1][k], after[1][k], k)
        self.assertFalse(self.conn.execute("SELECT 1 FROM users WHERE email='attacker@evil.example'").fetchone())

    def test_quote_and_signature_stripped(self):
        self.drop((FIX / "quoted_reply.eml").read_bytes(), "8.q")
        self.poll()
        (job,) = self.jobs()
        self.assertEqual(job["prompt"], "Spread trading comps for Apple vs peers and add a football field.\n\nThanks,\nAnn")
        self.assertEqual(job["deal_id"], None, "no tag and no deal name in the subject")
        self.assertEqual(mail.strip_reply("x" * 20000), "x" * 8000)

    def test_viewer_sender_cannot_start_runs(self):
        self.drop(msg("lp@meridian.example", "hi", "run something", "<m9@m>"), "9.v")
        res = self.poll()
        self.assertEqual((res["accepted"], res["rejected"]), (0, 1))
        self.assertEqual(self.audit("mail.rejected")[0]["reason"], "insufficient_role")

    def test_allowed_external_sender_runs_as_mailbox_owner(self):
        self.drop(msg("Pat Partner <partner@bank.example>", "Project Atlas update", "Summarise the data room.", "<m10@bank>"), "10.p")
        self.poll()
        (job,) = self.jobs()
        self.assertEqual((job["user_id"], job["deal_id"]), (self.owner_id, self.deal))      # deal found by name in the subject

    def test_deal_resolution(self):
        c = self.conn
        self.assertEqual(mail.resolve_deal(c, self.org, "[deal: Project Atlas] x")[0], self.deal)
        self.assertEqual(mail.resolve_deal(c, self.org, f"[Deal: {self.deal}] x")[0], self.deal)
        self.assertEqual(mail.resolve_deal(c, self.org, "[deal: project atlass] x")[0], self.deal, "fuzzy")
        self.assertEqual(mail.resolve_deal(c, self.org, "[deal: Unrelated Thing]")[0], None)
        self.assertEqual(mail.resolve_deal(c, self.org, "Update on project atlas models")[0], self.deal)
        self.assertEqual(mail.resolve_deal(c, self.org, "Lunch?")[0], None)

    def test_duplicates_auth_failure_and_html(self):
        raw = msg("owner@meridian.example", "dup", "do it", "<dup@m>")
        self.drop(raw, "11.a")
        self.drop(raw, "12.b")
        res = self.poll()
        self.assertEqual((res["accepted"], res["duplicates"]), (1, 1))
        self.drop(msg("owner@meridian.example", "forged", "do it", "<f@m>",
                      headers={"Authentication-Results": "mx.google.com; dkim=fail; spf=fail; dmarc=fail"}), "13.f")
        self.assertEqual(self.poll()["rejected"], 1)
        self.assertEqual(self.audit("mail.rejected")[-1]["reason"], "authentication_failed")
        m = EmailMessage()
        m["From"], m["Subject"], m["Message-ID"] = "owner@meridian.example", "html only", "<h@m>"
        m.set_content("<html><body><p>Build a DCF</p><script>alert(1)</script><p>for Apple</p></body></html>", subtype="html")
        self.drop(m.as_bytes(), "14.h")
        self.poll()
        self.assertEqual(self.jobs()[-1]["prompt"], "Build a DCF\n\nfor Apple")

    def test_spend_limit_blocks_intake(self):
        self.owner.j("PUT", f"{P}/firm/limits", {"deal_usd": 1})
        self.conn.execute("INSERT INTO jobs(id,org_id,deal_id,user_id,kind,prompt,status,cost_usd,created_at,source) VALUES('job_big',?,?,?,'run','p','done',9,?,'app')",
                          (self.org, self.deal, self.owner_id, "2999-01-01T00:00:00"))
        self.drop(msg("owner@meridian.example", "[deal: Project Atlas] more", "go", "<s@m>"), "15.s")
        res = self.poll()
        self.assertEqual((res["accepted"], res["rejected"]), (0, 1))
        self.assertEqual(self.audit("mail.rejected")[0]["reason"], "deal_limit")

    def test_unsafe_attachments_skipped(self):
        raw = msg("owner@meridian.example", "[deal: Project Atlas] files", "index these", "<a@m>",
                  attach=[("good.pdf", pdf_bytes(), "application", "pdf"), ("run.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application", "octet-stream"),
                          ("../../etc/passwd.txt", b"root:x:0:0", "text", "plain")])
        self.drop(raw, "16.a")
        self.poll()
        names = sorted(r["name"] for r in self.conn.execute("SELECT name FROM documents"))
        self.assertEqual(names, ["good.pdf", "passwd.txt"])


class NoSendingTests(MailCase):
    def test_no_smtp_import_and_no_socket(self):
        for f in ("mail.py", "firm.py", "watch.py"):
            tree = ast.parse((Path(mail.__file__).parent / f).read_text())
            mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertNotIn("smtplib", mods, f)
        had = "smtplib" in sys.modules
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", {"kind": "maildir", "path": str(self.md), "send_enabled": True})
        self.assertTrue(d["send_enabled"])                     # even with the flag on, nothing is sent
        self.drop(msg("owner@meridian.example", "x", "do it", "<ns@m>"), "1.ns")
        self.drop(msg("mallory@evil.example", "x", "do it", "<ns2@m>"), "2.ns")
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network used")) as cc, \
                mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network used")):
            res = self.poll()
        self.assertEqual((res["accepted"], res["rejected"]), (1, 1))
        cc.assert_not_called()
        if not had:
            self.assertNotIn("smtplib", sys.modules)


class ImapTests(MailCase):
    def test_imap_poll_tracks_last_uid(self):
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", {"kind": "imap", "host": "imap.meridian-mail.example", "username": "requests",
                                                             "secret": "pw-pw-pw-pw", "poll_seconds": 60})
        self.assertEqual(s, 200, d)
        store = {5: msg("owner@meridian.example", "[deal: Project Atlas] imap one", "first request", "<i1@m>"),
                 6: msg("mallory@evil.example", "imap two", "second", "<i2@m>"),
                 7: msg("analyst@meridian.example", "imap three", "third request", "<i3@m>")}
        seen = []

        class Imap:
            def select(self, folder, readonly=False):
                return "OK", [b"3"]

            def response(self, name):
                return name, [b"42"]

            def uid(self, cmd, *a):
                if cmd == "SEARCH":
                    lo = int(a[1].split()[1].split(":")[0])
                    return "OK", [b" ".join(str(u).encode() for u in sorted(store) if u >= lo) or (str(max(store)).encode())]
                if cmd == "FETCH":
                    return "OK", [(b"1 (UID %s BODY[] {n}" % a[0].encode(), store[int(a[0])]), b")"]
                if cmd == "STORE":
                    seen.append(int(a[0]))
                    return "OK", [b""]

            def logout(self):
                return "BYE", []

        with mock.patch.object(mail, "connect_imap", return_value=Imap()):
            res = mail.poll_once(self.st, self.org)
            self.assertEqual((res["fetched"], res["accepted"], res["rejected"]), (3, 2, 1), res)
            self.assertEqual(seen, [5, 6, 7])
            self.assertEqual(self.conn.execute("SELECT last_uid, uidvalidity FROM mailbox").fetchone()[:], (7, "42"))
            res = mail.poll_once(self.st, self.org)
            self.assertEqual(res["fetched"], 0, "UID 7 is the last one seen: nothing new")
        self.assertEqual(len(self.jobs()), 2)

    def test_connect_requires_verified_tls_and_public_host(self):
        with mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("10.1.2.3", 993))]):
            with self.assertRaises(mail.ApiError) as cm:
                mail.resolve_public("imap.sneaky.example", 993)
            self.assertEqual(cm.exception.code, "host_not_allowed")
        with mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 993))]):
            self.assertEqual(mail.resolve_public("imap.example.com", 993), "93.184.216.34")
        src = Path(mail.__file__).read_text()
        self.assertIn("ssl.create_default_context()", src)
        self.assertNotIn("_create_unverified_context", src)


class CliAndThreadTests(MailCase):
    def test_main_polls_once(self):
        self.drop(msg("owner@meridian.example", "cli", "from the cli", "<cli@m>"), "1.cli")
        with mock.patch.object(jobs.JobService, "_enqueue"):
            self.assertEqual(mail.main(["--data", self.tmp, "--no-wait"]), 0)
        self.assertEqual([j["prompt"] for j in self.jobs()], ["from the cli"])

    def test_background_thread_polls_and_stops(self):
        self.drop(msg("owner@meridian.example", "bg", "from the thread", "<bg@m>"), "1.bg")
        with mock.patch.dict(os.environ, {"ACRETIA_MAIL_POLL": "1"}):
            t = mail.init(self.st, tick=0.05)
        self.assertTrue(t.is_alive())
        try:
            end = time.time() + 10
            while time.time() < end and not self.jobs():
                time.sleep(0.05)
        finally:
            mail.shutdown()
        self.assertEqual([j["prompt"] for j in self.jobs()], ["from the thread"])
        self.assertFalse(t.is_alive())
        with mock.patch.dict(os.environ, {"ACRETIA_MAIL_POLL": "0"}):
            self.assertIsNone(mail.init(self.st))


if __name__ == "__main__":
    unittest.main()
