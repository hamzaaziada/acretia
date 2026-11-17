"""Earnings roll-forward: manual trigger, watcher with an injected filing provider, completion notifications (SF.6, P-J5)."""
import json
import unittest
from unittest import mock

from om import xlsx
from om.api import jobs, server, watch
try:
    from tests.test_api_auth import PASSWORD, ServerCase  # noqa: F401
except ImportError:
    from test_api_auth import PASSWORD, ServerCase  # noqa: F401

P = "/api/v1"
MODEL = "AAPL_three_statement_model.xlsx"


def book(rev, ebitda):
    wb = xlsx.Workbook()
    s = wb.sheet("IS")
    s.set("A1", "Revenue")
    s.set("B1", rev)
    s.set("A2", "EBITDA")
    s.set("B2", ebitda)
    s.set("A3", "Net income")
    s.set("B3", 100)
    return wb.to_bytes()


def filing(accn, label, filed="2026-11-01"):
    return {"accn": accn, "form": "10-Q", "filed": filed, "period_end": "2026-09-30", "fy": 2026, "fp": "Q4", "label": label}


class WatchCase(ServerCase):
    def setUp(self):
        self._routes = mock.patch.object(server, "ROUTE_MODULES", server.ROUTE_MODULES + ("om.api.watch",))
        self._routes.start()
        self.addCleanup(self._routes.stop)
        super().setUp()
        self.org, self.owner_id = self.make_org("Meridian", "owner@meridian.example")
        self.member_id = self.add_user(self.org, "analyst@meridian.example", "member")
        self.viewer_id = self.add_user(self.org, "lp@meridian.example", "viewer")
        self.owner = self.client("owner@meridian.example")
        self.member = self.client("analyst@meridian.example")
        self.viewer = self.client("lp@meridian.example")
        s, d, _ = self.owner.j("POST", f"{P}/deals", {"name": "Project Atlas"})
        self.deal = d["deal_id"]
        self.store = self.st.deal_store(self.conn, self.org)
        self.store.save_deliverable(self.deal, MODEL, book(1000, 300), "xlsx")
        self._enq = mock.patch.object(jobs.SERVICE, "_enqueue")
        self._enq.start()
        self.addCleanup(self._enq.stop)
        self.provider_value = filing("0000320193-26-000001", "Q3 FY2026", "2026-08-01")
        watch.PROVIDER = lambda state, ticker: self.provider_value
        self.addCleanup(setattr, watch, "PROVIDER", None)

    def jobs(self):
        return self.conn.execute("SELECT * FROM jobs WHERE org_id=? ORDER BY rowid", (self.org,)).fetchall()

    def finish(self, job_id, version_bump=True):
        """Pretend the earnings_update run finished: a new model version (and a deck) land in the library."""
        rec = self.store.save_deliverable(self.deal, MODEL, book(1100, 340), "xlsx", note=f"Agent run {job_id}")
        deck = self.store.save_deliverable(self.deal, "AAPL_profile.pptx", b"PK\x03\x04", "pptx")
        steps = [{"id": "e.roll_forward", "status": "done", "detail": "rolled forward to FY2026",
                  "output": {"deliverables": [{"deal_id": self.deal, "name": MODEL, "version": rec["version"], "kind": "xlsx"},
                                              {"deal_id": self.deal, "name": "AAPL_profile.pptx", "version": deck["version"], "kind": "pptx"}]}}]
        self.conn.execute("UPDATE jobs SET status='done', steps_json=? WHERE id=?", (json.dumps(steps), job_id))
        return rec


class ManualTests(WatchCase):
    def test_rollforward_submits_earnings_update(self):
        s, d, _ = self.member.j("POST", f"{P}/deals/{self.deal}/rollforward", {})
        self.assertEqual(s, 202, d)
        self.assertEqual(d["ticker"], "AAPL")                         # inferred from the model's file name
        (j,) = self.jobs()
        self.assertEqual((j["source"], j["agent_id"], j["deal_id"], j["user_id"]), ("app", "agt_builtin_earnings_update", self.deal, self.member_id))
        ins = json.loads(j["inputs_json"])
        self.assertEqual((ins["ticker"], ins["model"]), ("AAPL", MODEL))
        self.assertEqual(self.conn.execute("SELECT trigger_kind FROM watch_runs").fetchone()[0], "manual")

    def test_completion_notifies_all_members_with_diff_link(self):
        s, d, _ = self.member.j("POST", f"{P}/deals/{self.deal}/rollforward", {"ticker": "aapl"})
        job_id = d["job"]["id"]
        self.assertEqual(watch.check_completions(self.st), [], "still queued: nothing to announce")
        rec = self.finish(job_id)
        sent = watch.check_completions(self.st)
        self.assertEqual(len(sent), 1, sent)
        self.assertEqual(sent[0]["changed"], 2)                       # revenue and EBITDA moved
        title = sent[0]["title"]
        self.assertTrue(title.startswith("Model and deck rolled forward to FY2026"), title)
        self.assertTrue(title.endswith("2 cells changed"), title)
        rows = self.conn.execute("SELECT user_id, link, kind FROM notifications WHERE kind='rollforward.done'").fetchall()
        self.assertEqual({r["user_id"] for r in rows}, {self.owner_id, self.member_id, self.viewer_id})
        self.assertEqual({r["link"] for r in rows}, {f"/deals/{self.deal}/models/{MODEL}?diff={rec['version'] - 1}..{rec['version']}"})
        self.assertEqual(watch.check_completions(self.st), [], "announced exactly once")
        # the diff the link points to is real
        s, diff, _ = self.owner.j("GET", f"{P}/deals/{self.deal}/deliverables/{MODEL}/diff?a=1&b=2")
        self.assertEqual(s, 200, diff)

    def test_failure_notifies_requester_only(self):
        s, d, _ = self.member.j("POST", f"{P}/deals/{self.deal}/rollforward", {})
        self.conn.execute("UPDATE jobs SET status='failed', error='No filings are available for AAPL.' WHERE id=?", (d["job"]["id"],))
        watch.check_completions(self.st)
        rows = self.conn.execute("SELECT user_id, title, body FROM notifications WHERE kind='rollforward.failed'").fetchall()
        self.assertEqual([r["user_id"] for r in rows], [self.member_id])
        self.assertIn("No filings", rows[0]["body"])

    def test_errors_and_rbac(self):
        s, d, _ = self.viewer.j("POST", f"{P}/deals/{self.deal}/rollforward", {})
        self.assertEqual(s, 403)
        s, d, _ = self.owner.j("POST", f"{P}/deals/deal-nope/rollforward", {})
        self.assertEqual(s, 404)
        s, d, _ = self.owner.j("POST", f"{P}/deals", {"name": "Empty"})
        s, d, _ = self.owner.j("POST", f"{P}/deals/{d['deal_id']}/rollforward", {"ticker": "AAPL"})
        self.assertEqual(s, 409)
        self.assertEqual(d["error"]["code"], "no_model")
        self.assertTrue(d["error"]["hint"])
        s, d, _ = self.owner.j("POST", f"{P}/deals/{self.deal}/rollforward", {"ticker": "not a ticker!"})
        self.assertEqual(s, 400)
        self.assertEqual(self.viewer.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": True})[0], 403)
        self.assertEqual(self.viewer.j("GET", f"{P}/deals/{self.deal}/watch")[0], 200)

    def test_spend_limit_stops_a_manual_run(self):
        self.owner.j("PUT", f"{P}/firm/limits", {"org_monthly_usd": 0})
        s, d, _ = self.member.j("POST", f"{P}/deals/{self.deal}/rollforward", {})
        self.assertEqual(s, 402, d)
        self.assertEqual(self.jobs(), [])


class WatcherTests(WatchCase):
    def enable(self, **kw):
        return self.member.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": True, **kw})

    def test_new_filing_triggers_scheduled_run_then_notification(self):
        s, w, _ = self.enable()
        self.assertEqual(s, 200, w)
        self.assertTrue(w["enabled"])
        self.assertEqual((w["ticker"], w["last_filing"]["label"]), ("AAPL", "Q3 FY2026"))
        self.assertEqual(watch.tick(self.st), [], "the filing that existed when the watch was enabled is the baseline")
        self.assertEqual(self.jobs(), [])
        self.provider_value = filing("0000320193-26-000002", "FY2026", "2026-11-02")
        ids = watch.tick(self.st)
        self.assertEqual(len(ids), 1)
        (j,) = self.jobs()
        self.assertEqual((j["source"], j["user_id"], j["agent_id"]), ("schedule", self.member_id, "agt_builtin_earnings_update"))
        self.assertIn("FY2026", j["prompt"])
        self.assertEqual(watch.tick(self.st), [], "the same filing never triggers twice")
        self.assertEqual(len(self.jobs()), 1)
        self.finish(j["id"])
        sent = watch.check_completions(self.st)
        self.assertEqual(sent[0]["period"], "FY2026")
        self.assertIn("rolled forward to FY2026", sent[0]["title"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM notifications WHERE kind='rollforward.done'").fetchone()[0], 3)
        s, w, _ = self.viewer.j("GET", f"{P}/deals/{self.deal}/watch")
        self.assertEqual(w["runs"][0]["trigger"], "schedule")
        self.assertEqual(w["runs"][0]["status"], "done")
        self.assertIn("rolled forward", w["runs"][0]["title"])
        self.assertTrue(any(json.loads(r["detail_json"])["accn"] == "0000320193-26-000002"
                            for r in self.conn.execute("SELECT detail_json FROM audit_log WHERE action='rollforward.scheduled'")))

    def test_disabled_deals_and_failures_are_quiet(self):
        self.enable()
        self.member.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": False})
        self.provider_value = filing("new-accn", "FY2027")
        self.assertEqual(watch.tick(self.st), [])
        self.enable()
        self.provider_value = filing("another-accn", "FY2028")
        watch.PROVIDER = mock.Mock(side_effect=RuntimeError("sec down"))
        self.assertEqual(watch.tick(self.st), [])
        s, w, _ = self.member.j("GET", f"{P}/deals/{self.deal}/watch")
        self.assertIn("lookup failed", w["last_error"])
        watch.PROVIDER = lambda st, t: None
        watch.tick(self.st)
        self.assertIn("No filings", self.member.j("GET", f"{P}/deals/{self.deal}/watch")[1]["last_error"])

    def test_enable_needs_a_ticker_and_a_model(self):
        s, d, _ = self.owner.j("POST", f"{P}/deals", {"name": "No model"})
        s, d, _ = self.owner.j("PUT", f"{P}/deals/{d['deal_id']}/watch", {"enabled": True, "ticker": "MSFT"})
        self.assertEqual((s, d["error"]["code"]), (409, "no_model"))
        self.store.save_deliverable(self.deal, "model.xlsx", book(1, 2), "xlsx")
        self.assertEqual(self.owner.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": True})[0], 200)   # AAPL_ model still wins
        s, d, _ = self.owner.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": "yes"})
        self.assertEqual(s, 400)

    def test_scheduled_run_when_creator_left_falls_back_to_owner(self):
        self.enable()
        self.conn.execute("DELETE FROM memberships WHERE user_id=?", (self.member_id,))
        self.provider_value = filing("newer", "Q1 FY2027")
        self.assertEqual(len(watch.tick(self.st)), 1)
        self.assertEqual(self.jobs()[0]["user_id"], self.owner_id)

    def test_default_provider_reads_the_sec_cache(self):
        cf = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"accn": "A-1", "form": "10-K", "filed": "2025-11-01", "end": "2025-09-27", "fy": 2025, "fp": "FY", "val": 1},
            {"accn": "A-2", "form": "10-Q", "filed": "2026-02-01", "end": "2025-12-27", "fy": 2026, "fp": "Q1", "val": 1},
            {"accn": "A-3", "form": "8-K", "filed": "2026-05-01", "end": "2026-03-28", "fy": 2026, "fp": "Q2", "val": 1}]}}}}}
        with mock.patch("om.api.agents.engines.load_cf", return_value=(cf, {})):
            f = watch.sec_cache_latest(self.st, "AAPL")
        self.assertEqual((f["accn"], f["label"]), ("A-2", "Q1 FY2026"))
        with mock.patch("om.api.agents.engines.load_cf", return_value=None):
            self.assertIsNone(watch.sec_cache_latest(self.st, "AAPL"))

    def test_thread_is_off_when_interval_is_zero(self):
        with mock.patch.dict("os.environ", {"ACRETIA_WATCH_INTERVAL": "0"}):
            self.assertIsNone(watch.init(self.st))
        with mock.patch.dict("os.environ", {"ACRETIA_WATCH_INTERVAL": "3600"}):
            t = watch.init(self.st, completion_every=0.05)
            try:
                self.assertTrue(t.is_alive())
            finally:
                watch.shutdown()
        self.assertFalse(t.is_alive())


class TenantTests(WatchCase):
    def test_other_org_gets_404(self):
        org_b, _ = self.make_org("Rival", "owner@rival.example")
        b = self.client("owner@rival.example")
        self.assertEqual(b.j("POST", f"{P}/deals/{self.deal}/rollforward", {})[0], 404)
        self.assertEqual(b.j("GET", f"{P}/deals/{self.deal}/watch")[0], 404)
        self.assertEqual(b.j("PUT", f"{P}/deals/{self.deal}/watch", {"enabled": True, "ticker": "AAPL"})[0], 404)


if __name__ == "__main__":
    unittest.main()
