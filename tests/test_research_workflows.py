"""S6.1 research workflows: hermetic (fake SEC/web tools, sockets patched to raise, no LLM)."""
import copy
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from src.harness.evidence import verify as verify_chain
from src.harness.research import tools as T
from src.harness.research import workflows as W
from src.harness.research.api import ResearchRequest, ResearchResult, run_research
from src.harness.research.workflows import base as B
from src.harness.research.workflows import catalog as C
from tests.test_research_tools import FakeSec, FakeWeb, _no_net, load


def facts(years=2):
    """The TestCo fixture extended backwards: earlier years are the oldest year scaled by 0.9**k."""
    cf = copy.deepcopy(load("companyfacts_testco.json"))
    for tax in cf["facts"].values():
        for node in tax.values():
            for unit, rows in node["units"].items():
                base = sorted(rows, key=lambda r: r["end"])[0]
                for k in range(1, years - 1):
                    r = dict(base)
                    for key in ("end", "start", "filed"):
                        if key in r:
                            r[key] = str(int(r[key][:4]) - k) + r[key][4:]
                    r["val"] = base["val"] * 0.9 ** k
                    rows.append(r)
    return cf


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ev = self.tmp.name
        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            p = mock.patch(target, _no_net)
            p.start()
            self.addCleanup(p.stop)
        self.reg = T.build_registry(sec=FakeSec(facts(5)), web=FakeWeb())

    def run_wf(self, wf, tickers=("TEST",), tools=None, job="job1", options=None, **kw):
        opts = {"source_review": False}
        opts.update(options or {})
        rq = {"question": "x", "tickers": list(tickers), "workflow": wf, "options": opts, "as_of": "2025-06-01"}
        rq.update(kw.pop("req", {}))
        req = ResearchRequest(**rq)
        return run_research(req, tools=tools or self.reg, evidence_dir=self.ev, job_id=job, **kw)

    def chain_ok(self, job="job1"):
        v = verify_chain(Path(self.ev) / f"{job}.jsonl")
        self.assertTrue(v, getattr(v, "reason", v))


class Workflows(Base):
    def check(self, r, n_slides=1):
        self.assertIsInstance(r, ResearchResult)
        self.assertEqual(r.status, "succeeded", r.error)
        r.validate()
        ResearchResult.from_json(r.to_json())
        self.assertGreaterEqual(len(r.slide_specs), n_slides)
        self.assertTrue(r.figures)
        self.chain_ok()
        self.assertEqual(set(r.timings), {s.name for s in r.steps})

    def test_company_profile(self):
        r = self.run_wf("company_profile")
        self.check(r, 3)
        arch = {s.get("archetype") for s in r.slide_specs}
        self.assertTrue({"kpi_row", "scorecard", "chart_takeaways"} <= arch)
        from om.deck import archetypes
        self.assertTrue(all(s["archetype"] in archetypes.REGISTRY for s in r.slide_specs if s.get("archetype")))
        self.assertEqual(r.excel_inputs[0].to_dict()["ticker"], "TEST")
        self.assertEqual(r.rejected, [])
        for s in r.slide_specs:
            self.assertFalse(re.search(r"\d", re.sub(r"FY\d{4}", "", s["action_title"])), s["action_title"])

    def test_earnings_recap(self):
        r = self.run_wf("earnings_recap")
        self.check(r, 2)
        labels = {f.label for f in r.figures}
        self.assertIn("TEST EarningsPerShareDiluted", labels)
        self.assertIn("TEST Revenue change vs prior year", labels)
        self.assertFalse([s for s in r.slide_specs if s["id"].endswith("guidance")])     # no sourced guidance

    def test_earnings_recap_guidance_only_when_sourced(self):
        r = self.run_wf("earnings_recap", options={"guidance_url": "https://example.com/guide"})
        self.check(r, 2)
        self.assertTrue(any(s["id"].endswith("guidance") for s in r.slide_specs))
        self.assertTrue(any(f.citation.url == "https://example.com/guide" or "example.com" in (f.citation.url or "")
                            for f in r.figures))

    def test_buyer_list_ranks_and_never_invents(self):
        cands = [{"name": "Alpha Corp", "type": "strategic", "ticker": "TEST"},
                 {"name": "Beta Capital", "type": "financial"},
                 {"name": "Gamma Corp", "type": "strategic"}]
        r = self.run_wf("buyer_list", tickers=(), options={"candidates": cands})
        self.check(r, 2)
        names = set()
        for s in r.slide_specs:
            names |= {row["name"] for row in s["blocks"][0]["rows"]}
        self.assertEqual(names, {"Alpha Corp", "Beta Capital", "Gamma Corp"})
        strat = [s for s in r.slide_specs if "strategic" in s["id"]][0]["blocks"][0]["rows"]
        self.assertEqual([x["name"] for x in strat], ["Alpha Corp", "Gamma Corp"])       # scored first, unscored last
        self.assertEqual(strat[1]["status"], "unscored")
        self.assertEqual(strat[0]["rank"], 1)

    def test_buyer_list_unverifiable_metric_is_rejected_not_shown(self):
        bad = {"label": "Delta Cash", "value": 5000.0, "units": "USD millions", "period": "FY2024",
               "citation": {"doc_id": "d", "sha256_span_hash": "a" * 64, "url": "https://example.com/d",
                            "quote": "Delta holds $5,000 million in cash", "as_of": "2024-12-31"}}
        r = self.run_wf("buyer_list", tickers=(), options={"candidates": [
            {"name": "Delta Fund", "type": "financial", "metrics": [bad]}]})
        self.assertEqual(r.status, "succeeded", r.error)
        self.assertTrue(any(x["figure"].get("label") == "Delta Cash" for x in r.rejected))
        self.assertNotIn("Delta Cash", {f.label for f in r.figures})
        row = r.slide_specs[0]["blocks"][0]["rows"][0]
        self.assertEqual((row["status"], row["capacity"]), ("unscored", None))

    def test_qa(self):
        r = self.run_wf("qa", req={"question": "What was revenue and gross margin over the last 2 years?"})
        self.check(r, 1)
        labels = {f.label for f in r.figures}
        self.assertEqual(labels, {"TEST Revenue", "TEST Gross profit", "TEST Gross margin"} & labels)
        self.assertIn("TEST Gross margin", labels)
        self.assertNotIn("TEST Total assets", labels)
        self.assertEqual(len([f for f in r.figures if f.label == "TEST Revenue"]), 2)

    def test_qa_eps_uses_targeted_facts_call(self):
        r = self.run_wf("qa", req={"question": "What was diluted EPS per share?"})
        self.assertEqual(r.status, "succeeded", r.error)
        self.assertTrue(any(f.label.endswith("EarningsPerShareDiluted") for f in r.figures))

    PAGES = {"doc1": {"1": "Revenue was $1,100 million in FY2024.\nGross profit was $495 million.",
                      "2": "Revenue was $1,150 million. Gross margin was 45.0%. Headcount was 12,345 people."}}

    def test_tick_and_tie_flags_planted_mismatch_on_right_page(self):
        r = self.run_wf("tick_and_tie", req={"doc_ids": ["doc1"]}, options={"pages": self.PAGES})
        self.check(r, 2)
        rows = {}
        for s in r.slide_specs:
            for row in s["blocks"][0]["rows"]:
                rows.setdefault(row["page"], []).append(row)
        self.assertEqual([x["status"] for x in rows[1]], ["ok", "ok"])
        by = {x["number"]["value"]: x for x in rows[2] if x["number"]}
        self.assertEqual(by["$1,150 million"]["status"], "mismatch")
        self.assertEqual(by["45.0%"]["status"], "ok")
        self.assertEqual(by["12,345"]["status"], "unsourced")
        self.assertIn("TEST Revenue", by["$1,150 million"]["model"]["label"])
        titles = {s["id"]: s["action_title"] for s in r.slide_specs}
        self.assertIn("do not tie", [t for i, t in titles.items() if "_p2_" in i][0])
        self.assertIn("matched", [t for i, t in titles.items() if "_p1_" in i][0])

    def test_tick_and_tie_needs_source_and_pages(self):
        r = self.run_wf("tick_and_tie", tickers=(), req={"doc_ids": ["doc1"]}, options={"pages": self.PAGES})
        self.assertEqual(r.status, "failed")
        self.assertIn("model or figures", r.error)
        r = self.run_wf("tick_and_tie", req={"doc_ids": ["nope"]}, job="job2")
        self.assertEqual(r.status, "failed")
        self.assertIn("no page text", r.error)

    def test_requires_inputs(self):
        r = self.run_wf("company_profile", tickers=())
        self.assertEqual(r.status, "failed")
        self.assertIn("tickers is required", r.error)


class Verification(Base):
    def test_tampered_tool_figure_is_rejected_and_not_on_a_slide(self):
        reg = self.reg

        class Tamper:
            def call(self, name, args=None):
                res = reg.call(name, args)
                if name == "sec_statements":
                    res = json.loads(json.dumps(res))
                    for f in res["figures"]:
                        if f["label"] == "TEST Revenue" and f["period"].endswith("2024-12-31"):
                            f["value"] = 9999.0
                return res
        r = self.run_wf("company_profile", tools=Tamper())
        self.assertEqual(r.status, "succeeded", r.error)
        self.assertTrue(any(x["figure"].get("value") == 9999.0 for x in r.rejected))
        self.assertNotIn(9999.0, [f.value for f in r.figures])
        self.assertNotIn("9,999", json.dumps(r.slide_specs))

    def test_slide_with_unverified_number_is_rejected(self):
        def bad(ctx):
            ctx.slides.append({"id": "bad", "layout": "table", "title": "TEST increased revenue sharply in FY2024",
                               "action_title": "TEST increased revenue sharply in FY2024",
                               "blocks": [{"type": "table", "rows": [{"label": "TEST Revenue", "value": "$9,999m"}]}]})
        B.ASSEMBLERS["_bad"] = bad
        self.addCleanup(B.ASSEMBLERS.pop, "_bad")
        wf = W.Workflow("bad", "Bad", "bad", {}, (W.Step("review", "review_gate"), W.Step("statements", "tool", "sec_statements",
                        {"ticker": "{{request.tickers[0]}}", "years": 2}), W.Step("asm", "assemble", "_bad"),
                        W.Step("verify", "verify")))
        req = ResearchRequest(question="x", tickers=["TEST"], options={"source_review": False}, as_of="2025-06-01")
        r = W.run_request(wf, req, tools=self.reg, evidence_dir=self.ev, job_id="job9")
        self.assertEqual(r.status, "succeeded", r.error)
        self.assertEqual(r.slide_specs, [])
        self.assertTrue(any(x["figure"].get("id") == "bad" and "unverified numbers" in x["reason"] for x in r.rejected))

    def test_unsourced_user_figure_in_tick_and_tie_is_rejected(self):
        fig = {"label": "Model Revenue", "value": 1100.0, "units": "USD millions", "period": "FY2024",
               "citation": {"doc_id": "m", "sha256_span_hash": "b" * 64, "url": "https://example.com/m",
                            "quote": "Revenue 1,100", "as_of": "2024-12-31"}}
        r = self.run_wf("tick_and_tie", tickers=(), req={"doc_ids": ["d"]},
                        options={"figures": [fig], "pages": {"d": {"1": "Model Revenue was $1,100 million."}}})
        self.assertEqual(r.status, "failed")         # the only source is unverifiable: nothing to tie to
        self.assertIn("model or figures", r.error)


class Review(Base):
    def req(self, **o):
        return ResearchRequest(question="x", tickers=["TEST"], workflow="company_profile", as_of="2025-06-01",
                               options=o)

    def test_gate_blocks_until_approved(self):
        out, evs = {}, []

        def go():
            out["r"] = run_research(self.req(), tools=self.reg, evidence_dir=self.ev, job_id="rv1",
                                    on_event=evs.append)
        t = threading.Thread(target=go)
        t.start()
        for _ in range(200):
            if "rv1" in W.pending():
                break
            time.sleep(0.01)
        self.assertIn("rv1", W.pending())
        time.sleep(0.1)
        self.assertNotIn("r", out)                                        # still blocked
        self.assertTrue([e for e in evs if e["type"] == "source_review"])
        self.assertFalse([e for e in evs if e["type"] == "step_started" and e["data"]["name"] == "statements"])
        W.approve("rv1")
        t.join(10)
        self.assertEqual(out["r"].status, "succeeded", out["r"].error)
        src = [e for e in evs if e["type"] == "source_review"][0]["data"]
        self.assertEqual(src["status"], "awaiting_review")
        self.assertIn("sec_statements", {s.get("tool") for s in src["sources"]})
        self.chain_ok("rv1")

    def test_callback_and_rejection(self):
        seen = []
        r = run_research(self.req(), tools=self.reg, evidence_dir=self.ev, job_id="rv2",
                         review=lambda src: seen.append(src) or True)
        self.assertEqual(r.status, "succeeded")
        self.assertTrue(seen and seen[0])
        r = run_research(self.req(), tools=self.reg, evidence_dir=self.ev, job_id="rv3", review=lambda src: False)
        self.assertEqual(r.status, "cancelled")
        self.assertEqual(r.slide_specs, [])
        self.chain_ok("rv3")

    def test_cancel_while_waiting_and_file_flag_approval(self):
        cancel = threading.Event()
        out = {}
        t = threading.Thread(target=lambda: out.update(r=run_research(
            self.req(), tools=self.reg, evidence_dir=self.ev, job_id="rv4", cancel=cancel)))
        t.start()
        time.sleep(0.15)
        cancel.set()
        t.join(10)
        self.assertEqual(out["r"].status, "cancelled")
        # another process approves through the flag file beside the evidence chain
        out2 = {}
        t = threading.Thread(target=lambda: out2.update(r=run_research(
            self.req(), tools=self.reg, evidence_dir=self.ev, job_id="rv5")))
        t.start()
        for _ in range(200):
            if "rv5" in W.pending():
                break
            time.sleep(0.01)
        W.approve("rv5", evidence_dir=self.ev)
        t.join(10)
        self.assertEqual(out2["r"].status, "succeeded")

    def test_review_off_skips_gate(self):
        evs = []
        r = run_research(self.req(source_review=False), tools=self.reg, evidence_dir=self.ev, job_id="rv6",
                         on_event=evs.append)
        self.assertEqual(r.status, "succeeded")
        self.assertFalse([e for e in evs if e["type"] == "source_review"])


class Execution(Base):
    def test_progress_events_timing_and_cancel(self):
        evs = []
        cancel = threading.Event()

        def on(e):
            evs.append(e)
            if e["type"] == "step_finished" and e["data"]["name"] == "statements":
                cancel.set()
        r = self.run_wf("company_profile", on_event=on, cancel=cancel)
        self.assertEqual(r.status, "cancelled")
        self.assertEqual(r.slide_specs, []) and self.assertEqual(r.figures, [])
        self.chain_ok()
        started = [e["data"]["progress"] for e in evs if e["type"] == "step_started"]
        self.assertEqual(started, ["1/6", "2/6"])
        fin = [e for e in evs if e["type"] == "step_finished"]
        self.assertTrue(all(isinstance(e["data"]["wall_clock_s"], float) for e in fin))
        self.assertEqual(evs[-1]["data"]["status"], "cancelled")
        self.assertEqual(set(r.timings), {"review", "statements"})

    def test_progress_events_complete_run(self):
        evs = []
        r = self.run_wf("earnings_recap", on_event=evs.append)
        self.assertEqual(r.status, "succeeded")
        self.assertEqual([e["data"]["progress"] for e in evs if e["type"] == "step_finished"][-1], "7/7")
        self.assertTrue(any(e["type"] == "figure" for e in evs))
        self.assertEqual(evs[-1]["type"], "done")

    def test_evidence_has_one_record_per_tool_call(self):
        self.run_wf("company_profile")
        tools = [x["tool"] for x in __import__("src.harness.evidence", fromlist=["export"]).export(
            Path(self.ev) / "job1.jsonl")]
        self.assertEqual(tools.count("sec_statements"), 1)
        self.assertIn("verify", tools)

    def test_optional_failure_is_not_fatal_required_failure_is(self):
        reg = self.reg

        class Flaky:
            def __init__(self, fail):
                self.fail = fail

            def call(self, name, args=None):
                if name == self.fail:
                    raise RuntimeError("boom")
                return reg.call(name, args)
        r = self.run_wf("earnings_recap", tools=Flaky("sec_facts"))
        self.assertEqual(r.status, "succeeded")
        self.assertTrue([s for s in r.steps if s.name == "eps" and s.status == "failed"])
        r = self.run_wf("earnings_recap", tools=Flaky("sec_statements"), job="job2")
        self.assertEqual(r.status, "failed")
        self.assertIn("step statements", r.error)
        self.chain_ok("job2")

    def test_tool_timeout(self):
        class Slow:
            def call(self, name, args=None):
                time.sleep(0.5)
        wf = W.Workflow("slow", "S", "s", {}, (W.Step("t", "tool", "sec_statements", {"ticker": "TEST"}, timeout_s=0.05),
                                              W.Step("verify", "verify")))
        req = ResearchRequest(question="x", options={"source_review": False})
        r = W.run_request(wf, req, tools=Slow(), evidence_dir=self.ev, job_id="job8")
        self.assertEqual(r.status, "failed")
        self.assertIn("timeout", r.error)

    def test_max_steps(self):
        r = self.run_wf("company_profile", req={"max_steps": 2})
        self.assertEqual(r.status, "failed")
        self.assertIn("max_steps", r.error)

    def test_outputs_filter(self):
        r = self.run_wf("company_profile", req={"outputs": ["excel_inputs"]})
        self.assertEqual((r.slide_specs, bool(r.excel_inputs)), ([], True))

    def test_adapter_titles_pass_lint_and_numbers_are_refused(self):
        class A:
            def __init__(self, titles):
                self.t = iter(titles)

            def chat(self, messages, json_schema=None, job_id=None):
                return mock.Mock(data={"title": next(self.t)}, cost_usd=0.001, usage={"total_tokens": 10})
        r = self.run_wf("company_profile", adapter=A(["TEST delivered steady revenue growth in FY2024",
                                                      "TEST revenue jumped 50% over the years",
                                                      "Revenue."]))
        self.assertEqual(r.status, "succeeded", r.error)
        titles = [s["action_title"] for s in r.slide_specs]
        self.assertIn("TEST delivered steady revenue growth in FY2024", titles)
        self.assertFalse([t for t in titles if "50%" in t])
        self.assertGreater(r.tokens, 0)

    def test_agent_runtime_delegation(self):
        called = {}

        def rt(workflow, ctx):
            called["wf"] = workflow.id
            return B.execute(workflow, ctx)
        with mock.patch.object(B, "agent_runtime", return_value=rt):
            r = self.run_wf("company_profile")
        self.assertEqual((called["wf"], r.status), ("company_profile", "succeeded"))


class Composition(Base):
    def test_parse_command(self):
        p = C.parse_command("/company_profile /earnings_recap AAPL MSFT")
        self.assertEqual((p["workflows"], p["tickers"]), (["company_profile", "earnings_recap"], ["AAPL", "MSFT"]))
        with self.assertRaises(W.WorkflowError):
            C.parse_command("/nope AAPL")

    def test_compose_merges_steps_and_outputs(self):
        w = W.compose(["company_profile", "earnings_recap"])
        ids = [s.id for s in w.steps]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids.count("statements"), 1)
        self.assertEqual(ids[0], "review")
        self.assertEqual(ids[-1], "verify")
        self.assertIn("assemble_company_profile", ids)
        self.assertIn("assemble_earnings_recap", ids)

    def test_slash_command_through_run_research(self):
        req = ResearchRequest(question="/company_profile /earnings_recap TEST", options={"source_review": False},
                              as_of="2025-06-01")
        r = run_research(req, tools=self.reg, evidence_dir=self.ev, job_id="c1")
        self.assertEqual(r.status, "succeeded", r.error)
        ids = {s["id"] for s in r.slide_specs}
        self.assertTrue({"company_profile_test_kpis", "earnings_recap_test_compare"} <= ids)
        self.assertEqual(len([s for s in r.steps if s.name == "statements"]), 1)

    def test_unknown_workflow_is_a_contract_error(self):
        from om.contracts import ContractError
        with self.assertRaises(ContractError):
            run_research(ResearchRequest(question="x", workflow="/nope"), evidence_dir=self.ev, job_id="c2")

    def test_routing_and_backward_compat(self):
        wf, _ = C.route(ResearchRequest(question="Please build a buyer list for Acme"))
        self.assertEqual(wf.id, "buyer_list")
        wf, _ = C.route(ResearchRequest(question="What drove AAPL margin?", tickers=["AAPL"]))
        self.assertIsNone(wf)
        r = run_research(ResearchRequest(question="Q"), evidence_dir=self.ev, job_id="c3")
        self.assertEqual([s.name for s in r.steps], ["plan", "note"])
        d = ResearchRequest(question="Q").to_dict()
        self.assertNotIn("workflow", d)
        self.assertNotIn("options", d)
        self.assertNotIn("timings", r.to_dict())


class Catalog(unittest.TestCase):
    def test_search_ranks_by_description(self):
        self.assertEqual(C.search("tie out document page by page")[0]["id"], "tick_and_tie")
        self.assertEqual(C.search("rank strategic buyers for an acquisition")[0]["id"], "buyer_list")
        self.assertEqual(C.search("earnings recap eps")[0]["id"], "earnings_recap")
        self.assertEqual(C.search("zzzz"), [])
        self.assertEqual(C.search("company profile"), C.search("company profile"))

    def test_search_respects_admin_disabled(self):
        with mock.patch("src.harness.admin.agents.is_enabled", lambda org, aid, **k: not (
                org == "acme" and aid == "buyer_list")):
            self.assertNotIn("buyer_list", [x["id"] for x in C.search("buyers acquirers", "acme")])
            self.assertIn("buyer_list", [x["id"] for x in C.search("buyers acquirers", "other")])

    def test_disabled_workflow_does_not_run(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("src.harness.admin.agents.is_enabled",
                                                           lambda org, aid, **k: aid != "company_profile"):
            r = run_research(ResearchRequest(question="x", tickers=["TEST"], workflow="company_profile"),
                             evidence_dir=d, job_id="d1")
            self.assertEqual(r.status, "failed")
            self.assertIn("disabled", r.error)

    def test_every_workflow_validates_and_shares_step_definitions(self):
        defs = {}
        for w in C.CATALOG.values():
            w.validate()
            self.assertEqual(w.steps[-1].kind, "verify")
            for s in w.steps:
                self.assertEqual(defs.setdefault(s.id, s.to_dict()), s.to_dict(), s.id)
        self.assertEqual(W.get("qa").content_hash(), W.get("qa").content_hash())


class Templates(unittest.TestCase):
    def test_resolution(self):
        scope = {"request": {"tickers": ["AAPL", "MSFT"], "options": {"years": 3}}, "steps": {}, "plan": {"c": []}}
        self.assertEqual(B.resolve({"t": "{{request.tickers[1]}}", "y": "{{request.options.years|5}}",
                                    "z": "{{request.options.missing|5}}", "s": "x {{request.tickers[0]}}"}, scope),
                         {"t": "MSFT", "y": 3, "z": 5, "s": "x AAPL"})
        with self.assertRaises(W.TemplateError):
            B.resolve("{{request.tickers[5]}}", scope)

    def test_step_and_workflow_validation(self):
        with self.assertRaises(W.WorkflowError):
            W.Step("Bad Id", "tool", "x")
        with self.assertRaises(W.WorkflowError):
            W.Step("a", "tool")
        with self.assertRaises(W.WorkflowError):
            W.Workflow("w", "t", "d", {}, (W.Step("a", "assemble", "x"),))
        with self.assertRaises(W.WorkflowError):
            W.Workflow("w", "t", "d", {}, (W.Step("a", "review_gate", depends_on=("later",)), W.Step("verify", "verify")))


class Determinism(Base):
    def test_same_inputs_same_outputs(self):
        for wf, extra in (("company_profile", {}), ("earnings_recap", {}),
                          ("tick_and_tie", {"req": {"doc_ids": ["doc1"]}, "options": {"pages": Workflows.PAGES}})):
            a = self.run_wf(wf, job="d_a", **extra)
            b = self.run_wf(wf, job="d_b", tools=T.build_registry(sec=FakeSec(facts(5)), web=FakeWeb()), **extra)
            self.assertEqual(a.status, "succeeded", a.error)
            self.assertEqual(W.output_digest(a), W.output_digest(b), wf)
            self.assertEqual(a.to_dict()["slide_specs"], b.to_dict()["slide_specs"])


if __name__ == "__main__":
    unittest.main()
