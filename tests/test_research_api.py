"""S6.0 research job interface: offline, fake adapter/tools, no sockets."""
import copy
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om.contracts import ContractError  # noqa: E402
from src.harness import evidence  # noqa: E402
from src.harness.research import api, jobs  # noqa: E402
from src.harness.router import ToolRegistry  # noqa: E402

CIT = {"doc_id": "doc1", "sha256_span_hash": "a" * 64, "url": "https://www.sec.gov/x", "as_of": "2025-09-27"}
FIG = {"label": "Revenue", "value": 391035.0, "units": "USD_m", "period": "FY2024", "citation": CIT}


def fake_socket(*a, **k):
    raise AssertionError("network access attempted")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ev = os.path.join(self.tmp.name, "ev")
        self.env = mock.patch.dict(os.environ, {"ACRETIA_JOBS_DB": os.path.join(self.tmp.name, "jobs.sqlite"),
                                                "ACRETIA_EVIDENCE_DIR": self.ev})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(jobs.close_all)
        p = mock.patch.object(socket.socket, "connect", fake_socket)
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch("socket.create_connection", fake_socket)
        p2.start()
        self.addCleanup(p2.stop)


class ContractTests(unittest.TestCase):
    def test_request_defaults_and_roundtrip(self):
        r = api.ResearchRequest(question="Q")
        self.assertEqual(r.outputs, list(api.OUTPUT_KINDS))
        self.assertEqual((r.budget_usd, r.max_steps, r.org_id, r.v), (2.0, 12, "local", 1))
        self.assertEqual(api.ResearchRequest.from_json(r.to_json()), r)

    def test_request_adversarial(self):
        for bad in ({"budget_usd": 0}, {"budget_usd": -1}, {"max_steps": 0}, {"max_steps": 51}, {"outputs": []},
                    {"outputs": ["essay"]}, {"as_of": "2025-02-30"}, {"v": 2}, {"question": ""},
                    {"summary": "prose"}, {"tickers": ["AAPL", "AAPL"]}, {"org_id": "a b"}):
            with self.assertRaises(ContractError, msg=str(bad)):
                api.ResearchRequest.from_dict({"question": "Q", **bad})

    def test_figure_roundtrip_and_adversarial(self):
        f = api.SourcedFigure.from_dict(FIG)
        self.assertEqual(api.SourcedFigure.from_json(f.to_json()), f)
        no_asof = copy.deepcopy(FIG)
        del no_asof["citation"]["as_of"]
        no_src = copy.deepcopy(FIG)
        del no_src["citation"]["url"]
        for bad in (no_asof, no_src, {**FIG, "value": "1"}, {**FIG, "value": float("nan")}):
            with self.assertRaises(ContractError):
                api.SourcedFigure.from_dict(bad)
        doc = copy.deepcopy(FIG)
        del doc["citation"]["url"]
        doc["citation"]["page"] = 3
        api.SourcedFigure.from_dict(doc)

    def test_partition_rejects_instead_of_dropping(self):
        no_asof = copy.deepcopy(FIG)
        del no_asof["citation"]["as_of"]
        ok, bad = api.partition_figures([FIG, no_asof, "junk"])
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(bad), 2)
        self.assertIn("as_of", bad[0]["reason"])

    def test_excel_payload(self):
        p = api.ExcelInputPayload.from_dict({"model_type": "dcf", "ticker": "AAPL", "inputs": {"revenue": FIG}})
        self.assertEqual(p.inputs["revenue"].value, 391035.0)

    def test_result_rejects_prose_and_unsourced(self):
        base = {"job_id": "j1", "status": "succeeded", "evidence_head": "0" * 64}
        api.ResearchResult.from_dict(base)
        with self.assertRaises(ContractError) as c:
            api.ResearchResult.from_dict({**base, "summary": "Apple is great"})
        self.assertIn("prose", str(c.exception))
        bad = copy.deepcopy(FIG)
        del bad["citation"]["as_of"]
        with self.assertRaises(ContractError):
            api.ResearchResult.from_dict({**base, "figures": [bad]})
        with self.assertRaises(ContractError):
            api.ResearchResult.from_dict({**base, "evidence_head": "xyz"})
        with self.assertRaises(ContractError):
            api.ResearchResult.from_dict({**base, "slide_specs": [{"id": "s", "layout": "title", "left": 3}]})

    def test_event_contract(self):
        e = api.ResearchEvent(type="done", job_id="j1", ts="2026-01-01T00:00:00Z", data={"status": "succeeded"})
        self.assertEqual(api.ResearchEvent.from_json(e.to_json()), e)
        with self.assertRaises(ContractError):
            api.ResearchEvent.from_dict({"type": "nope", "job_id": "j1", "ts": "2026-01-01T00:00:00Z"})


class RunTests(Base):
    def test_placeholder_valid_and_chain_verifies(self):
        evs = []
        r = api.run_research(api.ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="job1",
                             on_event=evs.append)
        self.assertEqual(r.status, "succeeded")
        self.assertEqual((r.figures, r.slide_specs, r.excel_inputs), ([], [], []))
        self.assertIn("agent not yet implemented (S6.1)", [s.detail for s in r.steps])
        path = Path(self.ev) / "job1.jsonl"
        self.assertTrue(evidence.verify(path).ok)
        self.assertEqual(r.evidence_head, evidence.head_hash(path))
        self.assertNotEqual(r.evidence_head, "0" * 64)
        api.ResearchResult.from_json(r.to_json())

    def test_event_order(self):
        evs = []
        api.run_research(api.ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="job2", on_event=evs.append)
        types = [e["type"] for e in evs]
        self.assertEqual(types, ["step_started", "step_finished"] * 2 + ["done"])
        self.assertTrue(all(e["job_id"] == "job2" and e["v"] == 1 for e in evs))
        for e in evs:
            api.ResearchEvent.from_dict(e)

    def test_cancel_before_start(self):
        ev = threading.Event()
        ev.set()
        r = api.run_research(api.ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="job3", cancel=ev)
        self.assertEqual(r.status, "cancelled")

    def test_cancel_between_steps(self):
        ev = threading.Event()
        seen = []

        def on(e):
            seen.append(e["type"])
            if e["type"] == "step_finished":
                ev.set()
        r = api.run_research(api.ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="job4", cancel=ev,
                             on_event=on)
        self.assertEqual(r.status, "cancelled")
        self.assertEqual(len(r.steps), 1)
        self.assertEqual(seen[-1], "done")

    def test_adapter_and_tools_plumbing(self):
        reg = ToolRegistry()
        calls = []
        reg.register("ping", lambda x: calls.append(x) or {"ok": x},
                     {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]})
        adapter = SimpleNamespace(chat=lambda msgs, **kw: SimpleNamespace(
            data={"tool": "ping", "args": {"x": 7}}, cost_usd=0.01, usage={"total_tokens": 42}))
        r = api.run_research(api.ResearchRequest(question="Q"), adapter=adapter, tools=reg, evidence_dir=self.ev,
                             job_id="job5")
        self.assertEqual(calls, [7])
        self.assertEqual((r.tokens, r.cost_usd, r.status), (42, 0.01, "succeeded"))
        self.assertTrue(evidence.verify(Path(self.ev) / "job5.jsonl").ok)
        self.assertEqual(evidence.export(Path(self.ev) / "job5.jsonl")[-1]["tool"], "tool:ping")

    def test_budget_exceeded_fails(self):
        adapter = SimpleNamespace(chat=lambda msgs, **kw: SimpleNamespace(data={}, cost_usd=5.0, usage={}))
        r = api.run_research(api.ResearchRequest(question="Q", budget_usd=1), adapter=adapter, evidence_dir=self.ev,
                             job_id="job6")
        self.assertEqual(r.status, "failed")
        self.assertIn("budget", r.error)

    def test_bad_job_id(self):
        with self.assertRaises(ContractError):
            api.run_research(api.ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="../x")


def run_worker(test, until, timeout=10, **kw):
    stop = threading.Event()
    t = threading.Thread(target=jobs.worker_loop, args=(stop,), kwargs=dict(poll=0.02, **kw))
    t.start()
    end = time.time() + timeout
    try:
        while time.time() < end and not until():
            time.sleep(0.02)
    finally:
        stop.set()
        t.join(5)
    test.assertTrue(until(), "worker did not finish in time")


class JobTests(Base):
    def test_submit_worker_result(self):
        jid = jobs.submit(api.ResearchRequest(question="Q"))
        st = jobs.status(jid)
        self.assertEqual((st.status, st.kind), ("queued", "research"))
        self.assertIsNone(jobs.result(jid))
        run_worker(self, lambda: jobs.result(jid) is not None)
        self.assertEqual(jobs.status(jid).status, "succeeded")
        self.assertEqual(jobs.result(jid).status, "succeeded")
        evs = jobs.events(jid)
        self.assertEqual([e["seq"] for e in evs], list(range(1, len(evs) + 1)))
        self.assertEqual(evs[-1]["type"], "done")
        self.assertEqual([e["seq"] for e in jobs.events(jid, after_seq=2)], list(range(3, len(evs) + 1)))
        self.assertEqual(jobs._kv().qsize(jobs.QUEUE), 0)
        self.assertTrue(evidence.verify(Path(self.ev) / f"{jid}.jsonl").ok)

    def test_cancel_queued_job(self):
        jid = jobs.submit(api.ResearchRequest(question="Q"))
        self.assertTrue(jobs.cancel(jid))
        run_worker(self, lambda: jobs.result(jid) is not None)
        self.assertEqual(jobs.result(jid).status, "cancelled")
        self.assertEqual(jobs.status(jid).status, "cancelled")
        self.assertFalse(jobs.cancel(jid))

    def test_crash_lease_expiry_reruns_once(self):
        jid = jobs.submit(api.ResearchRequest(question="Q"))
        lost = jobs._kv().dequeue(jobs.QUEUE, lease=0.2)      # a worker took it, then died
        self.assertIsNotNone(lost)
        self.assertIsNone(jobs._kv().dequeue(jobs.QUEUE))     # still leased
        time.sleep(0.3)
        run_worker(self, lambda: jobs.result(jid) is not None)
        self.assertEqual(jobs.status(jid).attempts, 2)
        self.assertEqual(jobs.result(jid).status, "succeeded")
        self.assertEqual(jobs._kv().qsize(jobs.QUEUE), 0)

    def test_duplicate_delivery_is_idempotent(self):
        jid = jobs.submit(api.ResearchRequest(question="Q"))
        run_worker(self, lambda: jobs.result(jid) is not None)
        first = jobs.result(jid).to_json()
        n = len(jobs.events(jid))
        jobs._kv().enqueue(jobs.QUEUE, json.dumps({"org_id": "local", "job_id": jid}))
        run_worker(self, lambda: jobs._kv().qsize(jobs.QUEUE) == 0)
        self.assertEqual(jobs.result(jid).to_json(), first)
        self.assertEqual(len(jobs.events(jid)), n)

    def test_cross_org_isolation(self):
        jid = jobs.submit(api.ResearchRequest(question="Q", org_id="acme"))
        for fn in (jobs.status, jobs.result, jobs.events, jobs.cancel):
            with self.assertRaises(jobs.JobNotFound):
                fn(jid, org_id="other")
            with self.assertRaises(jobs.JobNotFound):
                fn(jid)                                      # default org "local" is also not acme
        self.assertEqual(jobs.status(jid, org_id="acme").status, "queued")
        run_worker(self, lambda: jobs.result(jid, org_id="acme") is not None)
        self.assertIsNone(jobs._kv().get(f"result:other:{jid}"))
        with self.assertRaises(jobs.JobNotFound):
            jobs.result(jid, org_id="other")

    def test_unknown_job(self):
        with self.assertRaises(jobs.JobNotFound):
            jobs.status("res_nope")

    def test_submit_validates(self):
        with self.assertRaises(ContractError):
            jobs.submit({"question": "Q", "budget_usd": 0})


class ReviewJobTests(Base):
    """S6.1c: pre-run source review in jobs mode (parity item 24)."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(jobs, "REVIEW_POLL_S", 0.02)
        p.start()
        self.addCleanup(p.stop)

    def submit(self, org="local", **opts):
        return jobs.submit(api.ResearchRequest(question="x", tickers=["TEST"], org_id=org, workflow="company_profile",
                                               options=dict(opts)))

    def wait(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end and not cond():
            time.sleep(0.02)
        self.assertTrue(cond(), "condition not reached")

    def in_worker(self, fn):
        from src.harness.research import tools as T
        from tests.test_research_tools import FakeSec
        stop = threading.Event()
        t = threading.Thread(target=jobs.worker_loop, args=(stop,),
                             kwargs=dict(poll=0.02, tools=T.build_registry(sec=FakeSec())))
        t.start()
        try:
            fn()
        finally:
            stop.set()
            t.join(5)

    def test_status_enum_has_awaiting_review(self):
        from om.contracts import STATUS, Job
        self.assertIn("awaiting_review", STATUS)
        self.assertEqual(Job.from_dict(Job(id="j", kind="research", status="awaiting_review").to_dict()).status,
                         "awaiting_review")

    def test_submit_await_approve_succeeds(self):
        jid = self.submit()

        def go():
            self.wait(lambda: jobs.status(jid).status == "awaiting_review")
            srcs = jobs.review_sources(jid)
            self.assertIsInstance(srcs, list)
            self.assertTrue([e for e in jobs.events(jid) if e["type"] == "source_review"
                             and e["data"]["status"] == "awaiting_review" and e["data"]["sources"] == srcs])
            self.assertIsNone(jobs.result(jid))
            self.assertTrue(jobs.approve(jid, approver="usr_7"))
            self.assertFalse(jobs.approve(jid, approver="usr_8"))            # decided once
            self.wait(lambda: jobs.result(jid) is not None)
        self.in_worker(go)
        self.assertEqual(jobs.result(jid).status, "succeeded", jobs.result(jid).error)
        self.assertEqual(jobs.status(jid).status, "succeeded")
        rec = json.loads(jobs._kv().get(f"review:local:{jid}"))
        self.assertEqual((rec["decision"], rec["approver"]), ("approved", "usr_7"))
        decided = [e for e in jobs.events(jid) if e["type"] == "source_review" and e["data"]["status"] == "approved"]
        self.assertEqual(decided[0]["data"]["approver"], "usr_7")

    def test_reject_cancels(self):
        jid = self.submit()

        def go():
            self.wait(lambda: jobs.status(jid).status == "awaiting_review")
            self.assertTrue(jobs.reject(jid, "wrong sources"))
            self.wait(lambda: jobs.result(jid) is not None)
        self.in_worker(go)
        self.assertEqual(jobs.result(jid).status, "cancelled")
        self.assertEqual(jobs.status(jid).status, "cancelled")
        self.assertFalse(jobs.approve(jid))
        self.assertEqual(json.loads(jobs._kv().get(f"review:local:{jid}"))["reason"], "wrong sources")

    def test_cross_org_approve_refused(self):
        jid = self.submit(org="acme")

        def go():
            self.wait(lambda: jobs.status(jid, org_id="acme").status == "awaiting_review")
            with self.assertRaises(jobs.JobNotFound):
                jobs.approve(jid, org_id="other", approver="mallory")
            with self.assertRaises(jobs.JobNotFound):
                jobs.approve(jid)                                            # default org "local" is not acme
            with self.assertRaises(jobs.JobNotFound):
                jobs.reject(jid, "x", org_id="other")
            self.assertEqual(jobs.status(jid, org_id="acme").status, "awaiting_review")
            self.assertIsNone(jobs._kv().get(f"review:other:{jid}"))
            self.assertTrue(jobs.approve(jid, org_id="acme", approver="usr_1"))
            self.wait(lambda: jobs.result(jid, org_id="acme") is not None)
        self.in_worker(go)
        self.assertNotEqual(jobs.result(jid, org_id="acme").status, "cancelled")

    def leave_crashed_in_review(self, jid):
        """What a worker that died inside the gate leaves behind: lease held, status awaiting_review, no result."""
        kv = jobs._kv()
        lost = kv.dequeue(jobs.QUEUE, lease=0.2)
        self.assertIsNotNone(lost)
        row = jobs._load(kv, jid, "local")
        row["job"].update(status="awaiting_review", attempts=1)
        jobs._save(kv, "local", row)
        jobs._persist_event(kv, "local", {"v": 1, "type": "source_review", "job_id": jid, "ts": "t",
                                          "data": {"status": "awaiting_review", "sources": []}})
        time.sleep(0.3)

    def test_crash_during_awaiting_review_resumes_waiting(self):
        jid = self.submit()
        self.leave_crashed_in_review(jid)
        self.assertEqual(jobs.status(jid).status, "awaiting_review")

        def go():
            self.wait(lambda: jobs.status(jid).attempts == 2)
            self.assertEqual(jobs.status(jid).status, "awaiting_review")     # redelivered run keeps waiting
            self.assertIsNone(jobs.result(jid))
            self.assertTrue(jobs.approve(jid, approver="usr_2"))
            self.wait(lambda: jobs.result(jid) is not None)
        self.in_worker(go)
        self.assertNotEqual(jobs.result(jid).status, "cancelled")
        self.assertEqual(jobs.status(jid).attempts, 2)
        self.assertEqual(jobs._kv().qsize(jobs.QUEUE), 0)
        self.assertTrue(evidence.verify(Path(self.ev) / f"{jid}.jsonl").ok)

    def test_approved_before_redelivery_finishes_without_second_wait(self):
        jid = self.submit()
        self.leave_crashed_in_review(jid)
        self.assertTrue(jobs.approve(jid, approver="usr_3"))                 # approver acts while no worker is alive
        self.assertEqual(jobs.status(jid).status, "running")
        self.in_worker(lambda: self.wait(lambda: jobs.result(jid) is not None))
        self.assertNotEqual(jobs.result(jid).status, "cancelled")

    def test_source_review_disabled_skips_the_gate(self):
        jid = self.submit(source_review=False)
        self.in_worker(lambda: self.wait(lambda: jobs.result(jid) is not None))
        self.assertFalse([e for e in jobs.events(jid) if e["type"] == "source_review"])
        self.assertNotEqual(jobs.status(jid).status, "awaiting_review")

    def test_cancel_while_awaiting_review(self):
        jid = self.submit()

        def go():
            self.wait(lambda: jobs.status(jid).status == "awaiting_review")
            self.assertTrue(jobs.cancel(jid))
            self.wait(lambda: jobs.result(jid) is not None)
        self.in_worker(go)
        self.assertEqual(jobs.status(jid).status, "cancelled")

    def test_review_timeout_cancels(self):
        jid = self.submit(review_timeout_s=0.2)
        self.in_worker(lambda: self.wait(lambda: jobs.result(jid) is not None))
        self.assertEqual(jobs.status(jid).status, "cancelled")


if __name__ == "__main__":
    unittest.main()
