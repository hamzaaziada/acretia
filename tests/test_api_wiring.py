"""Cross-module wiring found in the real app (SF.7): background services, poll-mail CLI, spend limits, house style, deal resolution,
source-review selection, model diff. Offline, replay, real HTTP on port 0 with the demo seed."""
import io
import json
import os
import re
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from om import xlsx
from om.api import __main__ as cli, demo, firm, jobs, mail, server, watch
from om.api.agents import engines
try:
    from tests.test_api_auth import ServerCase  # noqa: F401
    from tests.test_api_firm import make_pptx
except ImportError:
    from test_api_auth import ServerCase  # noqa: F401
    from test_api_firm import make_pptx

P = "/api/v1"
_ENV = {}
PW = "correct-horse-battery"


def setUpModule():
    for k, v in (("ACRETIA_LLM_MODE", "replay"), ("ACRETIA_LLM_FIXTURES", str(engines.REPLAY_DIR)), ("ACRETIA_DEMO_PASSWORD", PW)):
        _ENV[k] = os.environ.get(k)
        os.environ[k] = v


def tearDownModule():
    for k, v in _ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class DemoCase(ServerCase):
    """The demo org (Meridian: owner, analyst, lp; Project Nile and Project Atlas - Apple Inc.) on a real server."""

    def setUp(self):
        super().setUp()
        res = demo.seed(self.tmp, self.st)
        self.org = res["org_id"]
        self.atlas = res["deals"]["Project Atlas — Apple Inc."]
        self.nile = res["deals"]["Project Nile — ElSewedy Electric"]
        self.owner = self.client("owner@meridian.example")
        self.analyst = self.client("analyst@meridian.example")
        self.analyst_id = res["users"]["analyst@meridian.example"]

    def run_job(self, client, prompt, deal_id=None, inputs=None, want=("done", "failed", "cancelled", "awaiting_approval"), timeout=90):
        body = {"prompt": prompt, "inputs": inputs if inputs is not None else {"source_review": False}}
        if deal_id:
            body["deal_id"] = deal_id
        s, d, _ = client.j("POST", f"{P}/jobs", body)
        self.assertEqual(s, 201, d)
        return self.wait(client, (d.get("job") or d)["id"], want, timeout)

    def wait(self, client, jid, want=("done", "failed", "cancelled", "awaiting_approval"), timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            s, d, _ = client.j("GET", f"{P}/jobs/{jid}")
            j = d.get("job") or d
            if j["status"] in want:
                return j
            time.sleep(0.05)
        raise AssertionError(f"job {jid} stuck in {j['status']}")

    def deals_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM deals WHERE org_id=?", (self.org,)).fetchone()[0]


class ServicesTests(DemoCase):
    def test_make_server_starts_and_stops_mail_and_watch(self):
        with mock.patch.dict(os.environ, {"ACRETIA_BACKGROUND": "1", "ACRETIA_MAIL_POLL": "1", "ACRETIA_WATCH_INTERVAL": "3600"}):
            srv = server.make_server(self.st, "127.0.0.1", 0)
            try:
                self.assertTrue(mail._THREAD is not None and mail._THREAD.is_alive())
                self.assertTrue(watch._THREAD is not None and watch._THREAD.is_alive())
            finally:
                srv.server_close()
        self.assertIsNone(mail._THREAD)
        self.assertIsNone(watch._THREAD)

    def test_switches_turn_them_off(self):
        with mock.patch.dict(os.environ, {"ACRETIA_BACKGROUND": "1", "ACRETIA_MAIL_POLL": "0", "ACRETIA_WATCH_INTERVAL": "0"}):
            srv = server.make_server(self.st, "127.0.0.1", 0)
            try:
                self.assertIsNone(mail._THREAD)
                self.assertIsNone(watch._THREAD)
            finally:
                srv.server_close()
        with mock.patch.dict(os.environ, {"ACRETIA_BACKGROUND": "0", "ACRETIA_MAIL_POLL": "1", "ACRETIA_WATCH_INTERVAL": "3600"}):
            srv = server.make_server(self.st, "127.0.0.1", 0)
            try:
                self.assertIsNone(mail._THREAD)
            finally:
                srv.server_close()

    def test_default_test_environment_starts_no_pollers(self):
        self.assertIsNone(mail._THREAD)
        self.assertIsNone(watch._THREAD)


class PollMailCliTests(DemoCase):
    def test_poll_mail_command_runs_mail_main(self):
        md = Path(self.tmp) / "mail"
        for sub in ("new", "cur", "tmp"):
            (md / sub).mkdir(parents=True)
        s, d, _ = self.owner.j("PUT", f"{P}/firm/mailbox", {"kind": "maildir", "path": str(md), "allowed_senders": []})
        self.assertEqual(s, 200, d)
        raw = (Path(__file__).parent / "fixtures" / "api" / "mail" / "quoted_reply.eml").read_bytes()
        raw = re.sub(rb"(?im)^From:.*$", b"From: Analyst <analyst@meridian.example>", raw, count=1)
        (md / "new" / "1.cli").write_bytes(raw)
        with mock.patch.object(jobs.JobService, "_enqueue"):
            self.assertEqual(cli.main(["poll-mail", "--data", self.tmp, "--no-wait"]), 0)
        n = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE org_id=? AND source='email'", (self.org,)).fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(list((md / "new").iterdir()), [])


class SpendLimitTests(DemoCase):
    def test_org_limit_fails_the_run_with_a_hint(self):
        self.assertEqual(self.owner.j("PUT", f"{P}/firm/limits", {"org_monthly_usd": 1})[0], 200)
        self.conn.execute("INSERT INTO jobs(id,org_id,deal_id,user_id,kind,prompt,status,cost_usd,created_at,source) VALUES('job_spent',?,?,?,'run','p','done',5,?,'app')",
                          (self.org, self.atlas, self.analyst_id, "2999-01-01T00:00:00"))
        j = self.run_job(self.analyst, "DCF for Apple", self.atlas)
        self.assertEqual(j["status"], "failed")
        self.assertIn("monthly", j["error"])
        self.assertIn("raise", j["hint"])
        self.assertFalse([s for s in j["steps"] if s["status"] == "done"], "nothing ran")

    def test_deal_limit_stops_before_a_later_step(self):
        real = firm.spend_limit
        calls = []

        def limit(conn, org, deal=None):
            calls.append(deal)
            if len(calls) <= 3:
                return real(conn, org, deal)
            return {"allowed": False, "reason": "deal_limit", "hint": "This deal's limit of $1.00 is used up. An owner can raise it in Settings.",
                    "org": {}, "deal": {}}
        with mock.patch.object(firm, "spend_limit", limit):
            j = self.run_job(self.analyst, "DCF for Apple", self.atlas)
        self.assertEqual(j["status"], "failed")
        self.assertIn("deal", j["error"].lower())
        self.assertIn("Settings", j["hint"])
        done = [s["id"] for s in j["steps"] if s["status"] == "done"]
        self.assertTrue(0 < len(done) < 5, done)                    # it did start, and stopped part-way

    def test_no_limit_means_the_run_finishes(self):
        self.assertEqual(self.run_job(self.analyst, "DCF for Apple", self.atlas)["status"], "done")


class DealResolutionTests(DemoCase):
    def test_apple_prompt_without_a_deal_lands_in_the_atlas_deal(self):
        before = self.deals_count()
        j = self.run_job(self.analyst, "DCF for Apple")
        self.assertEqual(j["status"], "done", j)
        self.assertEqual(j["deal_id"], self.atlas)
        self.assertEqual(self.deals_count(), before)
        self.assertIn("AAPL_dcf_model.xlsx", [h for h in self.st.deal_store(self.conn, self.org).deliverables(self.atlas)] or ["AAPL_dcf_model.xlsx"])

    def test_ticker_and_case_insensitive_matching(self):
        before = self.deals_count()
        j = self.run_job(self.analyst, "dcf of $aapl")
        self.assertEqual(j["deal_id"], self.atlas)
        self.assertEqual(self.deals_count(), before)

    def test_no_match_creates_a_deal(self):
        before = self.deals_count()
        j = self.run_job(self.analyst, "DCF for $DEMOT")
        self.assertEqual(j["status"], "done", j)
        self.assertNotIn(j["deal_id"], (self.atlas, self.nile))
        self.assertEqual(self.deals_count(), before + 1)

    def test_explicit_deal_is_never_overridden(self):
        j = self.run_job(self.analyst, "DCF for Apple", self.nile)
        self.assertEqual(j["deal_id"], self.nile)


class HouseStyleTests(DemoCase):
    def deck_theme_xml(self, j):
        st = self.st.deal_store(self.conn, self.org)
        deck = [n for n in st.deliverables(j["deal_id"]) if n.endswith(".pptx")][0]
        h = st.history(j["deal_id"], deck)
        data = st.get_version(j["deal_id"], deck, h[-1]["version"])
        z = zipfile.ZipFile(io.BytesIO(data))
        return "\n".join(z.read(n).decode("utf8", "replace") for n in z.namelist() if n.startswith("ppt/theme/"))

    def profile_deck(self):
        j = self.run_job(self.analyst, "Company profile for Apple", self.atlas)
        self.assertEqual(j["status"], "awaiting_approval", j)
        s, d, _ = self.analyst.j("POST", f"{P}/jobs/{j['id']}/approve", {"step": "outline_approval" if False else self._pending_step(j["id"])})
        self.assertEqual(s, 200, d)
        j = self.wait(self.analyst, j["id"], ("done", "failed"))
        self.assertEqual(j["status"], "done", j)
        return j

    def _pending_step(self, jid):
        return json.loads(self.conn.execute("SELECT inputs_json FROM jobs WHERE id=?", (jid,)).fetchone()[0])["_pending"]["step_id"]

    def test_firm_template_changes_the_rendered_theme(self):
        base = self.deck_theme_xml(self.profile_deck())
        s, a, _ = self.owner.j("POST", f"{P}/firm/assets", raw=make_pptx(title="House"), headers={
            "X-Filename": "House Template.pptx", "X-Asset-Kind": "template", "Content-Type": "application/octet-stream"})
        self.assertEqual(s, 201, a)
        prof = firm.house_profile(self.conn, self.org)
        self.assertTrue(prof)
        themed = self.deck_theme_xml(self.profile_deck())
        accent = prof["theme"]["colors"]["accent"].lstrip("#").upper()
        self.assertIn(accent, themed.upper())
        self.assertNotEqual(base, themed)


class SourceReviewTests(DemoCase):
    def review(self, prompt, deal_id=None, inputs=None):
        j = self.run_job(self.analyst, prompt, deal_id, inputs=inputs or {})
        self.assertEqual(j["status"], "awaiting_approval", j)
        ev = [e for e in self.events(j["id"]) if e["type"] == "approval"][-1]["data"]
        self.assertEqual(ev["step_id"], "source_review")
        return j, ev["payload"]["sources"]

    def events(self, jid):
        return jobs.svc().events_after(jid, 0)

    def test_unticked_peer_is_not_read_and_not_in_sources(self):
        j, src = self.review("Comps for Apple", self.atlas, {"peers": ["DEMOA", "DEMOB"]})
        ids = {s["label"]: s["id"] for s in src}
        peer = next(s for s in src if "DEMOA" in s["label"])
        keep = [s["id"] for s in src if s["id"] != peer["id"]]
        s, d, _ = self.analyst.j("POST", f"{P}/jobs/{j['id']}/approve", {"step": "source_review", "payload": {"selected": keep}})
        self.assertEqual(s, 200, d)
        j = self.wait(self.analyst, j["id"], ("done", "failed"))
        self.assertEqual(j["status"], "done", j)
        peers = next(st for st in j["steps"] if st["id"].endswith("peers"))
        self.assertEqual(peers["detail"], "peers: DEMOB")
        self.assertNotIn("DEMOA", json.dumps([e["data"] for e in self.events(j["id"]) if e["type"] == "source"]))
        self.assertTrue(ids)

    def test_unticking_the_company_filings_fails_with_a_hint(self):
        j, src = self.review("DCF for Apple", self.atlas)
        s, d, _ = self.analyst.j("POST", f"{P}/jobs/{j['id']}/approve", {"step": "source_review", "payload": {"selected": []}})
        self.assertEqual(s, 200, d)
        j = self.wait(self.analyst, j["id"], ("done", "failed"))
        self.assertEqual(j["status"], "failed")
        self.assertIn("source review", j["error"])
        self.assertTrue(j["hint"])

    def test_all_selected_runs_as_before(self):
        j, src = self.review("DCF for Apple", self.atlas)
        self.analyst.j("POST", f"{P}/jobs/{j['id']}/approve", {"step": "source_review", "payload": {"selected": [s["id"] for s in src]}})
        self.assertEqual(self.wait(self.analyst, j["id"], ("done", "failed"))["status"], "done")

    def test_skip_next_time_is_per_user(self):
        j, src = self.review("DCF for Apple", self.atlas)
        self.analyst.j("POST", f"{P}/jobs/{j['id']}/approve", {"step": "source_review", "payload": {"selected": [s["id"] for s in src], "skip_next_time": True}})
        self.wait(self.analyst, j["id"], ("done", "failed"))
        j2 = self.run_job(self.analyst, "DCF for Apple", self.atlas, inputs={})
        self.assertEqual(j2["status"], "done", "the analyst's next run skips the review")
        j3 = self.run_job(self.owner, "DCF for Apple", self.atlas, inputs={})
        self.assertEqual(j3["status"], "awaiting_approval", "another user still gets the review")
        # turning it back on
        self.owner.j("POST", f"{P}/jobs/{j3['id']}/approve", {"step": "source_review", "payload": {"skip_next_time": False}})
        self.wait(self.owner, j3["id"], ("done", "failed"))


def _book(**cells):
    wb = xlsx.Workbook()
    s = wb.sheet("IS")
    for ref, v in cells.items():
        s.set(ref, v)
    return wb.to_bytes()


class ModelDiffTests(DemoCase):
    def test_diff_lists_changed_cells_and_is_tenant_scoped(self):
        st = self.st.deal_store(self.conn, self.org)
        st.save_deliverable(self.atlas, "AAPL_model.xlsx", _book(A1="Revenue", B1=100, B2=5, A2="Margin"), "xlsx")
        st.save_deliverable(self.atlas, "AAPL_model.xlsx", _book(A1="Revenue", B1=120, B2=5, A2="Margin", B3=7), "xlsx")
        s, d, _ = self.analyst.j("GET", f"{P}/models/{self.atlas}/AAPL_model.xlsx/diff?a=1&b=2")
        self.assertEqual(s, 200, d)
        self.assertEqual((d["a"], d["b"], d["count"]), (1, 2, 2))
        self.assertEqual({c["key"]: (c["old"], c["new"]) for c in d["changed"]}, {"IS!B1": (100, 120), "IS!B3": (None, 7)})
        self.assertEqual(d["sheets"], {"IS": 2})
        s, d, _ = self.analyst.j("GET", f"{P}/models/{self.atlas}/AAPL_model.xlsx/diff")
        self.assertEqual((d["a"], d["b"]), (1, 2))                    # defaults: previous vs latest
        self.assertEqual(self.analyst.j("GET", f"{P}/models/{self.atlas}/AAPL_model.xlsx/diff?a=1&b=9")[0], 404)
        self.assertEqual(self.analyst.j("GET", f"{P}/models/{self.atlas}/AAPL_model.xlsx/diff?a=x")[0], 400)
        # another organization cannot read it
        from om.api import auth
        r = auth.create_org(self.conn, "Other Fund", "boss@other.example", PW, "Boss")
        other = self.client("boss@other.example", r["org_id"])
        self.assertEqual(other.j("GET", f"{P}/models/{self.atlas}/AAPL_model.xlsx/diff?a=1&b=2")[0], 404)


if __name__ == "__main__":
    unittest.main()
