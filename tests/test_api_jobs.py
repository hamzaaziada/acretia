"""Job runtime: lifecycle, events, SSE replay, cancel, approvals, crash-resume, telemetry, schedules, tenancy. Offline, replay, zero sockets."""
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["ACRETIA_LLM_MODE"] = "replay"

from om.api import citations, db, jobs  # noqa: E402
from om.api.agents import engines, library  # noqa: E402
from om.api.http import ApiError, RequestContext  # noqa: E402
from om.deals import DealStore  # noqa: E402
from om.storage import LocalBlobStore  # noqa: E402

_real_connect = socket.socket.connect


def _no_net(self, *a, **k):
    raise AssertionError("network access attempted in an offline test")


def setUpModule():
    socket.socket.connect = _no_net
    os.environ.setdefault("ACRETIA_LLM_FIXTURES", str(engines.REPLAY_DIR))


def tearDownModule():
    socket.socket.connect = _real_connect


DOC_TABLES = """
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT, name TEXT, folder TEXT, kind TEXT, status TEXT, sha256 TEXT);
CREATE TABLE IF NOT EXISTS document_pages(org_id TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER, text TEXT, lines_json TEXT, tables_json TEXT);
"""


def make_state(tmp: Path, demo: bool = True):
    conn = db.connect(tmp / "app.db")
    db.migrate(conn, modules=("om.api.jobs", "om.api.agents.library", "om.api.citations"))
    conn.executescript(DOC_TABLES)
    blobs = LocalBlobStore(str(tmp / "blobs"))
    log = SimpleNamespace(notes=[], audits=[])
    st = SimpleNamespace(db_path=str(tmp / "app.db"), data_dir=tmp / "data", blobs=blobs, secret_key="test", llm_mode="replay", demo=demo, conn=lambda: conn,
                         notify=lambda c, org, uid, kind, title, body, link="": log.notes.append((org, uid, kind, link)),
                         audit=lambda c, org, uid, action, target="", detail=None, ip="", ua="": log.audits.append((org, action, target, detail)),
                         deal_store=lambda c, org: DealStore(c, blobs, org), log=log, _conn=conn)
    return st


def ctx_for(st, org="org_a", role="member", uid="usr_1", **kw):
    return RequestContext(conn=st._conn, blobs=st.blobs, user={"id": uid, "email": "x@example.com", "name": "X", "locale": "en"}, org_id=org, role=role, **kw)


def wait_status(svc, jid, want=("done", "failed", "cancelled"), timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        r = svc._row(jid)
        if r["status"] in want:
            return r
        time.sleep(0.02)
    raise AssertionError(f"job {jid} stuck in {svc._row(jid)['status']}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = make_state(self.tmp)
        self.svc = jobs.init(self.st)

    def tearDown(self):
        jobs.shutdown()
        time.sleep(0.05)
        self.st._conn.close()

    def run_job(self, prompt, **inputs):
        inputs.setdefault("source_review", False)
        j = self.svc.submit("org_a", "usr_1", prompt, inputs=inputs)
        wait_status(self.svc, j["id"])
        return j["id"]

    def evs(self, jid):
        return self.svc.events_after(jid, 0)


class LifecycleTests(Base):
    def check_order(self, jid):
        evs = self.evs(jid)
        self.assertEqual([e["seq"] for e in evs], list(range(1, len(evs) + 1)))
        types = [e["type"] for e in evs]
        self.assertEqual(types[0], "plan")
        self.assertEqual((types[-1], evs[-1]["data"]["status"]), ("status", "done"))
        last_step = max(i for i, t in enumerate(types) if t == "step")
        first_deliv = types.index("deliverable")
        self.assertLess(last_step, first_deliv)
        self.assertLess(max(i for i, t in enumerate(types) if t == "deliverable"), len(types) - 1)
        self.assertTrue(all(t in ("plan", "step", "source", "log", "approval", "deliverable", "cost", "status") for t in types))
        return evs

    def test_three_statement_aapl(self):
        jid = self.run_job("Three-statement model for Apple")
        evs = self.check_order(jid)
        d = [e for e in evs if e["type"] == "deliverable"][0]["data"]
        self.assertEqual(d["name"], "AAPL_three_statement_model.xlsx")
        self.assertEqual(d["version"], 1)
        data = self.st.deal_store(self.st._conn, "org_a").get_version(d["deal_id"], d["name"], 1)
        self.assertEqual(data[:2], b"PK")

    def test_dcf_aapl_with_overrides_and_sources(self):
        jid = self.run_job("DCF for Apple at 9% WACC and terminal growth 2.5%")
        evs = self.check_order(jid)
        facts = [s for s in self.svc._row(jid)["steps_json"] and json.loads(self.svc._row(jid)["steps_json"]) if s["fn"] == "build_dcf"][0]["output"]["facts"]
        self.assertAlmostEqual(facts["wacc"], 0.09, places=6)
        self.assertAlmostEqual(facts["terminal_growth"], 0.025, places=6)
        srcs = [e["data"] for e in evs if e["type"] == "source"]
        self.assertGreater(len(srcs), 10)
        self.assertEqual(len({s["citation_token"] for s in srcs}), len(srcs))           # deduped
        self.assertTrue(all(s["url"].startswith("https://www.sec.gov/") and s["as_of"] for s in srcs))
        self.assertTrue(any(s["xbrl_concept"] == "us-gaap:Revenues" or s["xbrl_concept"] for s in srcs))

    def test_model_edit_new_version(self):
        j1 = self.run_job("DCF for Apple")
        deal = self.svc._row(j1)["deal_id"]
        j2 = self.svc.submit("org_a", "usr_1", "Set WACC to 8.5% in the model", deal_id=deal, inputs={"source_review": False})["id"]
        wait_status(self.svc, j2)
        d = [e for e in self.evs(j2) if e["type"] == "deliverable"][0]["data"]
        self.assertEqual(d["version"], 2)
        store = self.st.deal_store(self.st._conn, "org_a")
        self.assertNotEqual(store.get_version(deal, d["name"], 1), store.get_version(deal, d["name"], 2))

    def test_football_field_output(self):
        jid = self.run_job("DCF for Apple with a football field")
        names = [e["data"]["name"] for e in self.evs(jid) if e["type"] == "deliverable"]
        self.assertIn("AAPL_football_field.pptx", names)
        step = [s for s in json.loads(self.svc._row(jid)["steps_json"]) if s["fn"] == "football_field"][0]
        self.assertIn("ranges", step["output"]["facts"])

    def test_multi_skill_run(self):
        jid = self.run_job("/comps /dcf Apple")
        names = [e["data"]["name"] for e in self.evs(jid) if e["type"] == "deliverable"]
        self.assertIn("AAPL_trading_comps.xlsx", names)
        self.assertIn("AAPL_dcf_model.xlsx", names)

    def test_replay_prose_is_labelled_canned(self):
        jid = self.run_job("IC memo for Apple")
        r = self.svc._row(jid)
        self.assertEqual(r["status"], "done")
        step = [s for s in json.loads(r["steps_json"]) if s["fn"] == "prose_memo"][0]
        self.assertTrue(any("REPLAY FIXTURE" in n for n in step["output"]["notes"]))
        d = [e for e in self.evs(jid) if e["type"] == "deliverable"][0]["data"]
        docx = self.st.deal_store(self.st._conn, "org_a").get_version(d["deal_id"], d["name"], d["version"])
        self.assertIn(b"REPLAY FIXTURE", zipfile.ZipFile(io.BytesIO(docx)).read("word/document.xml"))

    def test_unplannable_prompt_hint(self):
        jid = self.run_job("Tell me a joke about elephants")
        r = self.svc._row(jid)
        self.assertEqual(r["status"], "failed")
        self.assertIn("Try naming a task", r["hint"])
        self.assertIn("DCF for Apple", r["hint"])

    def test_unknown_company_hint(self):
        jid = self.run_job("DCF for $ZZZZ")
        r = self.svc._row(jid)
        self.assertEqual(r["status"], "failed")
        self.assertIn("open_multiples.py", r["hint"])


class SseTests(Base):
    def test_replay_from_last_event_id_has_no_duplicates(self):
        jid = self.run_job("DCF for Apple")
        full = list(jobs._events(ctx_for(self.st, params={"job_id": jid})).iterator)
        seqs = [d["seq"] for _, d in full]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))
        half = seqs[len(seqs) // 2]
        part = list(jobs._events(ctx_for(self.st, params={"job_id": jid}, headers={"Last-Event-ID": str(half)})).iterator)
        self.assertEqual([d["seq"] for _, d in part], [s for s in seqs if s > half])
        self.assertEqual(set(seqs[:half]) & {d["seq"] for _, d in part}, set())
        self.assertEqual(part[-1][0], "status")

    def test_tail_a_live_job(self):
        j = self.svc.submit("org_a", "usr_1", "DCF for Apple", inputs={"source_review": False})
        got = [(e, d["seq"]) for e, d in jobs._events(ctx_for(self.st, params={"job_id": j["id"]})).iterator]
        seqs = [s for _, s in got]
        self.assertEqual(seqs, sorted(set(seqs)))
        self.assertEqual(got[-1][0], "status")
        self.assertEqual(got[0][0], "plan")

    def test_bad_last_event_id(self):
        jid = self.run_job("DCF for Apple")
        with self.assertRaises(ApiError) as cm:
            jobs._events(ctx_for(self.st, params={"job_id": jid}, headers={"last-event-id": "abc"}))
        self.assertEqual(cm.exception.status, 400)
        self.assertTrue(cm.exception.hint)


class CancelAndApprovalTests(Base):
    def test_cancel_running_job(self):
        orig = engines.STEP_FNS["statements"]
        gate = threading.Event()

        def slow(cx):
            gate.set()
            for _ in range(500):
                cx.check_cancel()
                time.sleep(0.01)
            return orig(cx)
        engines.STEP_FNS["statements"] = slow
        try:
            j = self.svc.submit("org_a", "usr_1", "DCF for Apple", inputs={"source_review": False})
            self.assertTrue(gate.wait(10))
            self.svc.cancel("org_a", j["id"])
            r = wait_status(self.svc, j["id"])
        finally:
            engines.STEP_FNS["statements"] = orig
        self.assertEqual(r["status"], "cancelled")
        steps = json.loads(r["steps_json"])
        self.assertTrue(all(s["status"] in ("done", "skipped", "pending") for s in steps))
        self.assertEqual(self.evs(j["id"])[-1]["data"]["status"], "cancelled")
        with self.assertRaises(ApiError) as cm:
            self.svc.cancel("org_a", j["id"])
        self.assertEqual(cm.exception.status, 409)

    def test_ghost_deck_approval_gate_pause_and_resume(self):
        j = self.svc.submit("org_a", "usr_1", "Company profile for Apple", inputs={"source_review": False})
        r = wait_status(self.svc, j["id"], ("awaiting_approval", "done", "failed"))
        self.assertEqual(r["status"], "awaiting_approval")
        ap = [e for e in self.evs(j["id"]) if e["type"] == "approval"][0]["data"]
        self.assertEqual(ap["kind"], "ghost_deck")
        titles = ap["payload"]["titles"]
        self.assertGreaterEqual(len(titles), 4)
        self.assertTrue(all(t["title"] for t in titles))
        self.assertFalse([e for e in self.evs(j["id"]) if e["type"] == "deliverable"])      # nothing rendered before approval
        with self.assertRaises(ApiError) as cm:
            self.svc.approve("org_a", j["id"], "wrong.step", {}, "usr_1")
        self.assertEqual(cm.exception.status, 409)
        new_title = "Revenue grew 6% to $479bn in FY2026 on services"
        self.svc.approve("org_a", j["id"], ap["step_id"], {"titles": {"s2": new_title}}, "usr_1")
        r = wait_status(self.svc, j["id"])
        self.assertEqual(r["status"], "done")
        d = [e for e in self.evs(j["id"]) if e["type"] == "deliverable"][0]["data"]
        self.assertEqual(d["kind"], "pptx")
        self.assertIn("ok", d["badges"])                                        # validator badges ride on the deliverable event
        self.assertEqual(d["badges"]["critical"], 0)
        from pptx import Presentation
        prs = Presentation(io.BytesIO(self.st.deal_store(self.st._conn, "org_a").get_version(d["deal_id"], d["name"], d["version"])))
        self.assertIn(new_title, " ".join(sh.text_frame.text for sh in prs.slides[1].shapes if sh.has_text_frame))
        notified = [n[2] for n in self.st.log.notes]
        self.assertIn("job.awaiting_approval", notified)
        self.assertIn("job.done", notified)

    def test_source_review_default_on_and_skippable(self):
        j = self.svc.submit("org_a", "usr_1", "DCF for Apple")
        r = wait_status(self.svc, j["id"], ("awaiting_approval", "done", "failed"))
        self.assertEqual(r["status"], "awaiting_approval")
        ap = [e for e in self.evs(j["id"]) if e["type"] == "approval"][0]["data"]
        self.assertEqual(ap["step_id"], "source_review")
        labels = [s["label"] for s in ap["payload"]["sources"]]
        self.assertTrue(any("AAPL" in x for x in labels))
        self.assertFalse(any(s["type"] == "step" and s["data"].get("status") == "running" for s in map(lambda e: {"type": e["type"], "data": e["data"]}, self.evs(j["id"]))))
        self.svc.approve("org_a", j["id"], "source_review", {}, "usr_1")
        self.assertEqual(wait_status(self.svc, j["id"])["status"], "done")
        j2 = self.run_job("DCF for Apple", source_review=False)
        self.assertFalse([e for e in self.evs(j2) if e["type"] == "approval"])

    def test_cancel_while_awaiting_approval(self):
        j = self.svc.submit("org_a", "usr_1", "DCF for Apple")
        wait_status(self.svc, j["id"], ("awaiting_approval",))
        v = self.svc.cancel("org_a", j["id"])
        self.assertEqual(v["status"], "cancelled")


class ResumeTests(Base):
    def test_crash_after_step_two_resumes_and_matches_clean_run(self):
        clean = self.run_job("Three-statement model for Apple")
        clean_sha = [e for e in self.evs(clean) if e["type"] == "deliverable"][0]["data"]["sha256"]
        calls = {"resolve": 0, "statements": 0, "build": 0}
        origs = {k: engines.STEP_FNS[k] for k in ("resolve", "statements", "build_three_statement")}

        def count(name, key, fail_once=False):
            def f(cx):
                calls[key] += 1
                if fail_once and calls[key] == 1:
                    raise RuntimeError("injected crash after step 2")
                return origs[name](cx)
            return f
        engines.STEP_FNS["resolve"] = count("resolve", "resolve")
        engines.STEP_FNS["statements"] = count("statements", "statements")
        engines.STEP_FNS["build_three_statement"] = count("build_three_statement", "build", fail_once=True)
        try:
            jid = self.run_job("Three-statement model for Apple")
            r = self.svc._row(jid)
            self.assertEqual(r["status"], "failed")
            self.assertEqual(r["resume_from"], 2)
            steps = json.loads(r["steps_json"])
            self.assertEqual([s["status"] for s in steps[:3]], ["done", "done", "failed"])
            self.svc.resume("org_a", jid)
            r = wait_status(self.svc, jid)
        finally:
            engines.STEP_FNS.update(origs)
        self.assertEqual(r["status"], "done")
        self.assertEqual(calls, {"resolve": 1, "statements": 1, "build": 2})          # steps 1 and 2 were not re-run
        sha = [e for e in self.evs(jid) if e["type"] == "deliverable"][0]["data"]["sha256"]
        self.assertEqual(sha, clean_sha)                                              # determinism: byte-identical deliverable
        self.assertEqual(len([e for e in self.evs(jid) if e["type"] == "deliverable"]), 1)

    def test_restart_recovery_requeues_running_jobs(self):
        orig = engines.STEP_FNS["build_three_statement"]
        engines.STEP_FNS["build_three_statement"] = lambda cx: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            jid = self.run_job("Three-statement model for Apple")
        finally:
            engines.STEP_FNS["build_three_statement"] = orig
        self.assertEqual(self.svc._row(jid)["status"], "failed")
        steps = json.loads(self.svc._row(jid)["steps_json"])
        steps[2]["status"] = "pending"
        steps[2]["error"] = None
        self.svc._x("UPDATE jobs SET status='running', steps_json=? WHERE id=?", (json.dumps(steps), jid))      # a crash left it 'running'
        self.svc._recover()
        r = wait_status(self.svc, jid)
        self.assertEqual(r["status"], "done")
        self.assertTrue(any(e["type"] == "log" and "restart" in e["data"]["message"] for e in self.evs(jid)))

    def test_resume_only_failed(self):
        jid = self.run_job("DCF for Apple")
        with self.assertRaises(ApiError) as cm:
            self.svc.resume("org_a", jid)
        self.assertEqual(cm.exception.status, 409)
        self.assertTrue(cm.exception.hint)


class MissingEngineTests(Base):
    def test_precedents_fails_with_s4_hint_while_dcf_runs(self):
        jid = self.run_job("/precedents /dcf Apple")
        r = self.svc._row(jid)
        self.assertEqual(r["status"], "failed")
        self.assertIn("S4", r["hint"])
        steps = json.loads(r["steps_json"])
        self.assertEqual([s["status"] for s in steps if s["task"] == "dcf"], ["done"] * 5)
        self.assertEqual([s["status"] for s in steps if s["task"] == "precedents"][-1], "skipped")
        names = [e["data"]["name"] for e in self.evs(jid) if e["type"] == "deliverable"]
        self.assertEqual(names, ["AAPL_dcf_model.xlsx"])

    def test_lbo_runs_now_because_the_module_exists(self):
        jid = self.run_job("LBO for Apple")
        self.assertEqual(self.svc._row(jid)["status"], "done")

    def test_no_synthetic_peers_outside_demo_mode(self):
        jobs.shutdown()
        self.st._conn.close()
        self.st = make_state(Path(tempfile.mkdtemp()), demo=False)
        self.svc = jobs.init(self.st)
        os.environ.pop("ACRETIA_SYNTHETIC_PEERS", None)
        jid = self.run_job("Comps for Apple")
        r = self.svc._row(jid)
        self.assertEqual(r["status"], "failed")
        self.assertIn("peer", r["hint"].lower())


class TelemetryTests(Base):
    def test_step_telemetry_and_cost_monotonic(self):
        jid = self.run_job("IC memo for Apple")
        r = self.svc._row(jid)
        for s in json.loads(r["steps_json"]):
            for k in ("started_at", "finished_at", "seconds", "tokens", "cost_usd", "engine"):
                self.assertIn(k, s)
                self.assertIsNotNone(s[k], k)
        evs = self.evs(jid)
        step_evs = [e["data"] for e in evs if e["type"] == "step" and e["data"]["status"] == "done"]
        for d in step_evs:
            for k in ("started_at", "finished_at", "seconds", "tokens", "cost_usd", "engine"):
                self.assertIn(k, d)
        costs = [e["data"]["cost_usd"] for e in evs if e["type"] == "cost"]
        self.assertEqual(costs, sorted(costs))
        self.assertGreater(costs[-1], 0)                                 # the canned reply booked its replay usage
        self.assertAlmostEqual(costs[-1], self.svc.ledger.total(jid)["cost_usd"], places=8)
        self.assertAlmostEqual(r["cost_usd"], costs[-1], places=8)
        self.assertGreater(r["wall_seconds"], 0)

    def test_time_saved_estimate_with_baseline(self):
        jid = self.run_job("DCF for Apple")
        ts = json.loads(self.svc._row(jid)["time_saved_json"])
        self.assertEqual(ts["task_id"], "dcf")
        self.assertEqual(ts["basis"], "estimate")
        self.assertAlmostEqual(ts["t_h_minutes"]["mid"], 90, delta=1)
        self.assertGreater(ts["t_a_minutes"], 15)                         # wall time plus the 15-minute review estimate
        self.assertLess(ts["t_a_minutes"], 30)
        done = self.evs(jid)[-1]["data"]
        self.assertEqual(done["time_saved"]["task_id"], "dcf")

    def test_time_saved_no_baseline_marker(self):
        jid = self.run_job("Earnings recap for Apple")
        ts = json.loads(self.svc._row(jid)["time_saved_json"])
        self.assertEqual(ts["baseline"], "own timing study needed")
        self.assertNotIn("pct", ts)

    def test_audit_row_per_step(self):
        jid = self.run_job("DCF for Apple")
        steps = [a for a in self.st.log.audits if a[1] == "agent.step" and a[2] == jid]
        self.assertEqual(len(steps), 5)


class ScheduleTests(Base):
    def test_once_schedule_fires_with_fake_clock(self):
        t0 = 1_800_000_000.0
        self.svc.clock = lambda: t0
        run_at = jobs._iso(t0 + 3600)
        s = self.svc.create_schedule("org_a", "usr_1", "DCF for Apple", {"kind": "once", "run_at": run_at})
        self.assertEqual(s["schedule"]["next_run"], run_at)
        self.assertEqual(self.svc.tick(t0 + 10), [])
        fired = self.svc.tick(t0 + 3601)
        self.assertEqual(len(fired), 1)
        r = wait_status(self.svc, fired[0])
        self.assertEqual((r["status"], r["source"]), ("done", "schedule"))               # unattended runs skip the source review
        self.assertEqual(self.svc.tick(t0 + 7200), [])                                    # a once-schedule never fires twice
        self.assertEqual(self.svc.schedule_view(self.svc._row(s["id"]))["status"], "finished")

    def test_daily_and_weekly_reschedule(self):
        t0 = 1_800_000_000.0                                              # a Tuesday at 03:20 UTC
        self.svc.clock = lambda: t0
        d = self.svc.create_schedule("org_a", "usr_1", "Earnings recap for Apple", {"kind": "daily", "at": "07:30"})
        w = self.svc.create_schedule("org_a", "usr_1", "Earnings recap for Apple", {"kind": "weekly", "at": "07:30", "weekday": 0})
        nd = d["schedule"]["next_run"]
        self.assertTrue(nd.endswith("07:30:00Z"))
        self.assertEqual(len(self.svc.tick(t0 + 86400 * 8)), 2)
        d2 = self.svc.schedule_view(self.svc._row(d["id"]))["schedule"]
        w2 = self.svc.schedule_view(self.svc._row(w["id"]))["schedule"]
        self.assertGreater(d2["next_run"], jobs._iso(t0 + 86400 * 8))
        self.assertGreater(w2["next_run"], jobs._iso(t0 + 86400 * 8))
        self.assertEqual(d2["runs"], 1)

    def test_bad_schedule_has_hint(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.create_schedule("org_a", "usr_1", "DCF for Apple", {"kind": "daily", "at": "25:99x"})
        self.assertEqual(cm.exception.status, 400)
        self.assertTrue(cm.exception.hint)

    def test_disabled_agent_schedule_does_not_crash(self):
        t0 = 1_800_000_000.0
        self.svc.clock = lambda: t0
        aid = "agt_builtin_dcf"
        self.svc.create_schedule("org_a", "usr_1", "", {"kind": "once", "run_at": jobs._iso(t0 + 60)}, agent_id=aid, inputs={"ticker": "AAPL"})
        self.st._conn.execute("INSERT INTO agent_prefs(org_id, agent_id, enabled) VALUES('org_a', ?, 0)", (aid,))
        self.assertEqual(self.svc.tick(t0 + 120), [])


class TenancyAndRoutesTests(Base):
    def test_cross_org_is_404_on_every_job_route(self):
        jid = self.run_job("DCF for Apple")
        other = dict(org="org_b", uid="usr_9")
        for h, extra in ((jobs._get, {}), (jobs._events, {}), (jobs._cancel, {}), (jobs._resume, {}), (jobs._approve, {"json": {"step": "x"}}),
                         (citations.sources_zip, {})):
            with self.assertRaises(ApiError, msg=h.__name__) as cm:
                h(ctx_for(self.st, params={"job_id": jid}, **other, **extra))
            self.assertEqual(cm.exception.status, 404, h.__name__)
        listing = jobs._list(ctx_for(self.st, **other))
        self.assertEqual(listing["items"], [])
        self.assertEqual(len(jobs._list(ctx_for(self.st))["items"]), 1)
        with self.assertRaises(ApiError) as cm:
            jobs._create(ctx_for(self.st, **other, json={"prompt": "DCF for Apple", "deal_id": self.svc._row(jid)["deal_id"]}))
        self.assertEqual(cm.exception.status, 404)

    def test_create_requires_member_and_validates(self):
        with self.assertRaises(ApiError) as cm:
            jobs._create(ctx_for(self.st, role="viewer", json={"prompt": "DCF for Apple"}))
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ApiError) as cm:
            jobs._create(ctx_for(self.st, json={"prompt": "  "}))
        self.assertEqual(cm.exception.status, 400)
        self.assertTrue(cm.exception.hint)
        status, body = jobs._create(ctx_for(self.st, json={"prompt": "DCF for Apple", "inputs": {"source_review": False}}))
        self.assertEqual(status, 201)
        wait_status(self.svc, body["job"]["id"])
        got = jobs._get(ctx_for(self.st, params={"job_id": body["job"]["id"]}, role="viewer"))["job"]
        self.assertEqual(got["status"], "done")
        self.assertEqual(got["deliverables"][0]["name"], "AAPL_dcf_model.xlsx")

    def test_list_filters_and_pagination(self):
        ids = [self.run_job("DCF for Apple") for _ in range(3)]
        page = jobs._list(ctx_for(self.st, query={"limit": "2"}))
        self.assertEqual(len(page["items"]), 2)
        self.assertIsNotNone(page["next_cursor"])
        rest = jobs._list(ctx_for(self.st, query={"limit": "2", "cursor": page["next_cursor"]}))
        self.assertEqual(len(rest["items"]), 1)
        self.assertEqual({j["id"] for j in page["items"] + rest["items"]}, set(ids))
        self.assertEqual(len(jobs._list(ctx_for(self.st, query={"status": "failed"}))["items"]), 0)

    def test_sources_zip_download_all_sources(self):
        jid = self.run_job("DCF for Apple")
        resp = citations.sources_zip(ctx_for(self.st, params={"job_id": jid}, role="viewer"))
        z = zipfile.ZipFile(io.BytesIO(resp.body))
        csv_text = z.read("sources.csv").decode()
        self.assertIn("us-gaap:", csv_text)
        self.assertGreater(csv_text.count("\n"), 10)
        self.assertEqual(resp.content_type, "application/zip")

    def test_citation_route_and_tenancy(self):
        jid = self.run_job("DCF for Apple")
        tok = [e["data"]["citation_token"] for e in self.evs(jid) if e["type"] == "source"][0]
        self.assertEqual(len(tok), 22)
        c = citations.get_citation(ctx_for(self.st, params={"token": tok}, role="viewer"))
        self.assertTrue(c["url"] and c["as_of"] and c["xbrl_concept"])
        with self.assertRaises(ApiError) as cm:
            citations.get_citation(ctx_for(self.st, params={"token": tok}, org="org_b"))
        self.assertEqual(cm.exception.status, 404)

    def test_citation_validation(self):
        conn = self.st._conn
        with self.assertRaises(ValueError):
            citations.mint(conn, "org_a", url="ftp://x", doc_id="d1")
        with self.assertRaises(ValueError):
            citations.mint(conn, "org_a", quote="orphan")
        t1 = citations.mint(conn, "org_a", doc_id="doc_1", page=3, quote="Revenue was 5", doc_name="CIM.pdf", bbox=[0.1, 0.1, 0.5, 0.2])
        t2 = citations.mint(conn, "org_a", doc_id="doc_1", page=3, quote="Revenue was 5", doc_name="CIM.pdf", bbox=[0.1, 0.1, 0.5, 0.2])
        self.assertEqual(t1, t2)


class DeterminismTests(Base):
    def test_pptx_and_xlsx_bytes_are_stable(self):
        s, cf, info = engines.get_statements(self.st, "AAPL")
        from om import model3
        a = engines.stable_zip(model3.build(s)[0])
        b = engines.stable_zip(model3.build(s)[0])
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
