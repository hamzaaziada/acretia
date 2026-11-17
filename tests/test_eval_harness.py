"""Measurement harnesses (SF.4): TSB runner and reliability runner, reduced sets, replay mode, zero sockets."""
import csv
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.reliability import (Audit, audit_docx, audit_pptx, audit_xlsx, circularity_check, diff_count, fingerprint,  # noqa: E402
                              iqr, median, pct)
from eval.reliability import run as rel  # noqa: E402
from eval.tsb import baselines  # noqa: E402
from eval.tsb import run as tsb  # noqa: E402

_real_connect = socket.socket.connect
_real_create = socket.create_connection


def _no_net(self, *a, **k):
    raise AssertionError("network access attempted in an offline test")


def _no_create(*a, **k):
    raise AssertionError("socket.create_connection attempted in an offline test")


def setUpModule():
    socket.socket.connect = _no_net
    socket.create_connection = _no_create


def tearDownModule():
    socket.socket.connect = _real_connect
    socket.create_connection = _real_create


TSB_REQUIRED = {"brief_id", "task_id", "outcome", "wall_min", "review_fix_min", "t_a_min", "t_h_low_min", "t_h_mid_min", "t_h_high_min", "saved_low",
                "saved_mid", "saved_high", "gates_pass", "silent_numbers", "client_ready", "status"}
REL_REQUIRED = {"brief_id", "task_id", "perturbation", "outcome", "success", "wall_seconds", "silent_numbers", "deterministic", "resume_ok", "cost_usd"}


class StatsTests(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(median([1, 2, 3, 4]), 2.5)
        self.assertEqual(pct([1, 2, 3, 4, 5], 95), 4.8)
        self.assertEqual(iqr([1, 2, 3, 4, 5]), (2, 4))
        self.assertIsNone(pct([], 50))

    def test_edit_minutes_table_is_all_labelled(self):
        with open(tsb.HERE / "edit_minutes.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0].keys()), ["edit_class", "minutes", "source_or_inference", "note"])
        want = {"typo/label", "number fix", "formula fix", "link/reference fix", "chart change", "slide restructure", "missing section", "sourcing fix", "formatting"}
        self.assertEqual({r["edit_class"] for r in rows}, want)
        for r in rows:
            self.assertGreater(float(r["minutes"]), 0)
            self.assertTrue(r["source_or_inference"].startswith("[INFERENCE]") or r["source_or_inference"].startswith("http"), r)

    def test_review_fix_minutes_uses_table_and_rejects_unknown_class(self):
        m = tsb.load_edit_minutes()
        self.assertEqual(tsb.review_fix_minutes([{"edit_class": "number fix", "count": 2}, {"edit_class": "formatting", "count": 1}], m), 2 * m["number fix"] + m["formatting"])
        with self.assertRaises(KeyError):
            tsb.review_fix_minutes([{"edit_class": "rewrite everything", "count": 1}], m)

    def test_canned_persona_fixtures_are_labelled_and_match_the_catalogue_estimate(self):
        from om.api.agents import catalogue
        m = tsb.load_edit_minutes()
        for t in catalogue.TASK_IDS_14:
            p = json.loads((tsb.PERSONA_DIR / f"{t}.json").read_text(encoding="utf-8"))
            self.assertIn("CANNED PLACEHOLDER", p["label"])
            self.assertIsNone(p["persona_score"])
            self.assertEqual(tsb.review_fix_minutes(p["edits"], m), catalogue.CATALOGUE[t]["review_minutes_estimate"], t)

    def test_briefs_and_corpus_shape(self):
        from om.api.agents import catalogue
        briefs = tsb.load_briefs()
        for t in catalogue.TASK_IDS_14:
            self.assertGreaterEqual(len([b for b in briefs if b["task_id"] == t and not b.get("fixed_wsp")]), 10, t)
        self.assertTrue(all(b["data"] in ("real", "synthetic", "needs_live") for b in briefs))
        self.assertEqual(len([b for b in briefs if b.get("fixed_wsp")]), 1)
        corpus = rel.load_corpus()
        self.assertGreaterEqual(len(corpus), 100)
        self.assertTrue({b["perturbation"] for b in corpus} >= {"base", "phrasing", "override", "deal_context", "arabic_mixed", "arabic_only"})
        self.assertTrue(any(b["lang"].startswith("ar") for b in corpus))


class AuditTests(unittest.TestCase):
    def test_pptx_figure_without_source_is_silent_and_with_source_is_not(self):
        from pptx import Presentation
        from pptx.util import Inches

        def deck(with_source):
            prs = Presentation()
            sl = prs.slides.add_slide(prs.slide_layouts[6])
            sl.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text_frame.text = "Revenue grew 15% to $479bn"
            if with_source:
                sl.shapes.add_textbox(Inches(1), Inches(6), Inches(5), Inches(1)).text_frame.text = "Source: Apple Inc. 10-K FY2026, filed 2026-11-03 (SEC EDGAR)"
            b = io.BytesIO()
            prs.save(b)
            return b.getvalue()
        self.assertEqual(audit_pptx(deck(False)).silent, 2)
        a = audit_pptx(deck(True))
        self.assertEqual((a.silent, a.sourced), (0, 2))

    def test_docx_figures_need_a_source_line_or_a_flag(self):
        from om.api.agents import engines
        silent = audit_docx(engines.docx_bytes("Memo", ["Revenue was $478.8 billion, up 15.1%."]))
        self.assertGreater(silent.silent, 0)
        flagged = audit_docx(engines.docx_bytes("Memo", ["REPLAY FIXTURE: canned.", "Revenue was $478.8 billion."]))
        self.assertEqual((flagged.silent, flagged.flagged > 0), (0, True))
        sourced = audit_docx(engines.docx_bytes("Memo", ["Revenue was $478.8 billion."], footer="Figures from Apple Inc. filings, filed 2026-11-03."))
        self.assertEqual(sourced.silent, 0)

    def test_xlsx_unsourced_constant_is_silent(self):
        try:
            import openpyxl
            from openpyxl.comments import Comment
            from openpyxl.styles import Font
        except ImportError:
            self.skipTest("openpyxl not installed")

        def book(comment: bool, blue: bool):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Model"
            ws["A1"], ws["C5"], ws["D5"], ws["E5"] = "Revenue", "FY2023A", "FY2024A", "FY2025A"
            for col in "CDE":
                ws[f"{col}6"] = 100.0
            ws["A6"] = "Revenue"
            if comment:
                ws["D6"].comment = Comment("us-gaap:Revenues", "t")
            if blue:
                ws["C6"].font = Font(color="0000FF")
            b = io.BytesIO()
            wb.save(b)
            return b.getvalue()
        base = audit_xlsx(book(False, False))
        self.assertEqual(base.silent, 3)
        self.assertEqual(audit_xlsx(book(True, False)).silent, 2)
        # a blue constant in an actual-period time-series row is still silent: historicals need a source, not a colour
        self.assertEqual(audit_xlsx(book(True, True)).silent, 2)

    def test_diff_count_xlsx_cellwise(self):
        a = {"S": {(1, 1): (None, 1.0), (1, 2): ("=A1", 2.0)}}
        b = {"S": {(1, 1): (None, 1.0), (1, 2): ("=A1", 3.0)}}
        self.assertEqual(diff_count(a, a), 0)
        self.assertEqual(diff_count(a, b), 1)


class TsbRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.res = tsb.run_all(["three_statement", "dcf", "profile"], n=2, out_dir=cls.out)
        cls.rows = cls.res["rows"]

    def test_files_and_required_columns(self):
        with open(self.out / "results.csv", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            self.assertTrue(TSB_REQUIRED <= set(r.fieldnames), TSB_REQUIRED - set(r.fieldnames))
            data = list(r)
        self.assertEqual({d["task_id"] for d in data}, {"three_statement", "dcf", "profile"})
        txt = (self.out / "report.md").read_text(encoding="utf-8")
        for needle in ("Per-task results (estimate)", "Competitor claims beside each task", "WSP Apple 3-statement", "[independent]", "own timing study needed"):
            self.assertIn(needle, txt)

    def test_two_briefs_per_task_ran_and_were_graded(self):
        for t in ("three_statement", "dcf", "profile"):
            done = [r for r in self.rows if r["task_id"] == t and r["outcome"] == "done" and not r["brief_id"].startswith("wsp-")]
            self.assertEqual(len(done), 2, t)
            for r in done:
                self.assertGreater(float(r["t_a_min"]), float(r["wall_min"]))                  # review time is included
                self.assertEqual(r["silent_numbers"], 0)
                self.assertTrue(r["gates_pass"])

    def test_no_row_is_human_validated_and_client_ready_is_not_inflated(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertEqual(r["status"], "estimate")
            self.assertNotEqual(r.get("client_ready"), "yes")                                 # no persona ran, so nothing can be 'yes'
        with open(self.out / "results.csv", newline="", encoding="utf-8") as f:
            self.assertFalse([1 for d in csv.DictReader(f) if "human-validated" in " ".join(d.values())])
        for a in self.res["agg"]:
            self.assertNotIn("human-validated", json.dumps(a))

    def test_savings_use_the_baselines_table(self):
        bl = baselines.load()["tasks"]["dcf"]
        r = next(r for r in self.rows if r["task_id"] == "dcf" and r["outcome"] == "done")
        self.assertAlmostEqual(float(r["saved_mid"]), 1 - float(r["t_a_min"]) / bl["t_h_mid"], places=3)
        prof = next(r for r in self.rows if r["task_id"] == "profile" and r["outcome"] == "done")
        self.assertEqual(prof["baseline"], "own timing study needed")
        self.assertEqual(prof["saved_mid"], "")                                               # no baseline, no number

    def test_wsp_row_circularity(self):
        self.assertIsNotNone(self.res["wsp"])
        self.assertTrue(self.res["wsp"]["circularity"]["pass"], self.res["wsp"])

    def test_missing_engine_reports_blocked_not_a_number(self):
        from om.api.agents import engines
        if engines._has("om.precedents"):
            self.skipTest("om.precedents has landed")
        out = Path(tempfile.mkdtemp())
        res = tsb.run_all(["precedents"], n=1, out_dir=out)
        r = res["rows"][0]
        self.assertEqual(r["outcome"], "blocked")
        self.assertEqual(r["t_a_min"], "")
        self.assertIn("blocked", (out / "report.md").read_text(encoding="utf-8"))

    def test_live_refuses_without_env(self):
        keep = {k: os.environ.pop(k, None) for k in ("ACRETIA_LLM_MODE", "ACRETIA_LLM_API_KEY")}
        try:
            self.assertEqual(tsb.main(["--live", "--out", tempfile.mkdtemp()]), 2)
        finally:
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v


class ReliabilityRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.res = rel.run_all(n=10, out_dir=cls.out)
        cls.s = cls.res["summary"]
        cls.rows = cls.res["rows"]

    def test_reduced_set_ran_and_reports_have_required_columns(self):
        self.assertEqual(len(self.rows), 10)
        with open(self.out / "results.csv", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            self.assertTrue(REL_REQUIRED <= set(r.fieldnames), REL_REQUIRED - set(r.fieldnames))
        txt = (self.out / "report.md").read_text(encoding="utf-8")
        for needle in ("Headline versus SLO targets", "Silent wrong numbers", "Determinism", "Failed jobs resume cleanly", "p95 latency", "Cost per deliverable"):
            self.assertIn(needle, txt)

    def test_silent_wrong_numbers_zero_and_determinism_100(self):
        done = [r for r in self.rows if r["outcome"] == "done"]
        self.assertGreaterEqual(len(done), 6)
        self.assertEqual(self.s["silent"], 0, [r.get("_audit_examples") for r in done if r["silent_numbers"]])
        self.assertGreater(self.s["numbers_checked"], 0)
        self.assertEqual(self.s["determinism"], 1.0, [r["notes"] for r in done if r["deterministic"] is False])
        self.assertEqual(self.s["n_det"], len(done))

    def test_resume_after_injected_failure_matches_clean_run(self):
        self.assertGreater(self.s["n_resume"], 0)
        self.assertEqual(self.s["resume_rate"], 1.0, [r["resume_detail"] for r in self.rows if r["resume_ok"] is False])

    def test_latency_cost_and_no_human_validated_label(self):
        self.assertIsNotNone(self.s["p95"])
        txt = (self.out / "report.md").read_text(encoding="utf-8").lower()
        self.assertIn("not a live measurement", txt)                                         # replay cost is priced fixture usage, never a bill
        for r in self.rows:
            if r["outcome"] == "done" and r["task_id"] not in ("ic_memo", "earnings_recap", "buyer_list"):
                self.assertEqual(float(r["cost_usd"] or 0), 0.0, r["brief_id"])
        self.assertNotIn("human-validated", txt)

    def test_injected_failure_actually_fails_then_resumes(self):
        # guards the resume check against passing vacuously: a patched step must raise once and the job must end 'failed' first
        from eval.reliability import Harness
        with Harness() as h:
            calls, restore = h.inject_failure("build_dcf")
            try:
                run = h.run("DCF for Apple")
                self.assertEqual(run.status, "failed")
                again = h.resume(run)
            finally:
                restore()
            self.assertEqual(again.status, "done")
            self.assertEqual(calls["n"], 2)
            clean = h.run("DCF for Apple")
            self.assertEqual(diff_count(fingerprint("xlsx", clean.deliverables[0]["data"]), fingerprint("xlsx", again.deliverables[0]["data"])), 0)


if __name__ == "__main__":
    unittest.main()
