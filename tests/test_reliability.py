"""om.reliability: classification, resumability, report shape and timing fields. Offline: synthetic companyfacts,
monkeypatched fetch, no SEC and no LibreOffice required."""
import json
import tempfile
import unittest
from pathlib import Path

from om import reliability as rel
from tests.test_model3 import synthetic_companyfacts


def _rec(**kw):
    base = {"ticker": "X", "ifrs": False, "audit_flags": [], "timings": {"total": 1.0}}
    base.update(kw)
    return base


class Universe(unittest.TestCase):
    def test_size_deterministic_and_mixed(self):
        u = rel.universe(120)
        self.assertEqual(u, rel.universe(120))
        self.assertGreaterEqual(len(u), 100)
        self.assertEqual(len(u), len(set(u)))
        self.assertGreaterEqual(sum(t in rel.IFRS_TICKERS for t in u), 15)
        self.assertFalse(set(u) & set(rel.OUT_OF_SCOPE))

    def test_small_n_keeps_both_populations(self):
        u = rel.universe(20)
        self.assertEqual(len(u), 20)
        self.assertTrue(any(t in rel.IFRS_TICKERS for t in u))


class Classify(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(rel.classify(_rec(grade={"failed_critical": []}, validate={"passed": True}, recalc={"agree": True},
                                           update={"seconds": 3.0}))[0], "pass")

    def test_unsupported_is_not_a_failure(self):
        out, cause, detail = rel.classify(_rec(unsupported="bank"))
        self.assertEqual((out, cause, detail), ("unsupported", "unsupported", "bank"))

    def test_fetch(self):
        self.assertEqual(rel.classify(_rec(error={"step": "fetch", "type": "FileNotFoundError", "message": "x"}))[:2], ("fail", "fetch"))

    def test_missing_concept_us_vs_ifrs(self):
        flags = ["FY2024: Revenue is not tagged", "FY2023: Revenue is not tagged", "FY2024: Total assets is not tagged"]
        err = {"step": "model", "type": "KeyError", "message": "revenue"}
        out = rel.classify(_rec(error=err, audit_flags=flags))
        self.assertEqual(out[1], "mapping/missing concept")
        self.assertIn("Revenue", out[2])
        self.assertEqual(rel.classify(_rec(error=err, audit_flags=flags, ifrs=True))[1], "IFRS concept gap")
        self.assertEqual(rel.missing_concepts(flags), ["Revenue", "Total assets"])

    def test_untagged_unsupported_is_a_failure_but_bank_is_not(self):
        # model3 raises UnsupportedCompany for both; only the "doesn't tag" kind is a concept gap that must count against us
        m = rel._DOESNT_TAG.search("SAP: the latest filing doesn't tag Revenue, Operating income (reported); can't build a tied model.")
        self.assertEqual(m.group(1), "Revenue, Operating income (reported)")
        out = rel.classify(_rec(ifrs=True, missing_concepts=["Revenue"], error={"step": "model", "type": "UnsupportedCompany", "message": "x"}))
        self.assertEqual(out[:2], ("fail", "IFRS concept gap"))
        self.assertEqual(rel.classify(_rec(ifrs=False, error={"step": "statements", "type": "NoAnnualData", "message": "none"}))[1],
                         "mapping/missing concept")

    def test_tie_out(self):
        flags = ["FY2024: total assets ≠ total liabilities & equity in the filing"]
        out = rel.classify(_rec(error={"step": "statements", "type": "ValueError", "message": "m"}, audit_flags=flags))
        self.assertEqual(out[1], "tie-out")

    def test_exception_type(self):
        out = rel.classify(_rec(error={"step": "checks", "type": "ZeroDivisionError", "message": "m"}))
        self.assertEqual(out[1], "exception:ZeroDivisionError")

    def test_grader_validate_divergence(self):
        self.assertEqual(rel.classify(_rec(grade={"failed_critical": ["checks", "calculates"]}))[1], "grader:checks")
        self.assertEqual(rel.classify(_rec(grade={"failed_critical": []}, validate={"passed": False, "failed": ["errors"]}))[1], "validate:errors")
        self.assertEqual(rel.classify(_rec(grade={"failed_critical": []}, validate={"passed": True},
                                           recalc={"agree": False, "divergences": 2, "examples": ["IS!C5"]}))[1], "engine divergence")

    def test_update_too_slow(self):
        out = rel.classify(_rec(grade={"failed_critical": []}, validate={"passed": True}, recalc={"agree": True},
                                update={"seconds": rel.TARGET_UPDATE_SECONDS + 1}))
        self.assertEqual(out[:2], ("fail", "update too slow"))


class RunOne(unittest.TestCase):
    def test_synthetic_company_timings_and_outcome(self):
        rec = rel.run_one("SYN", facts=synthetic_companyfacts(years=(2021, 2022, 2023, 2024)), engines=("cached", "om"))
        self.assertIn(rec["outcome"], ("pass", "fail", "unsupported"))
        for k in ("fetch", "statements", "audit", "total"):
            self.assertIn(k, rec["timings"])
            self.assertIsInstance(rec["timings"][k], float)
        if rec["outcome"] != "unsupported":
            for k in ("model", "model_circ0", "grade", "validate", "recalc"):
                self.assertIn(k, rec["timings"])
            self.assertIsNotNone(rec["model_seconds"])
            self.assertIn("update", rec)
            if rec["outcome"] == "pass":
                self.assertIsNotNone(rec["update"]["seconds"])
                self.assertEqual(rec["flagged"], bool(rec["audit_flags"]))

    def test_fetch_failure_is_recorded_not_raised(self):
        orig = rel.fetch
        rel.fetch = lambda t: (_ for _ in ()).throw(FileNotFoundError("nope"))
        try:
            rec = rel.run_one("ZZZZ")
        finally:
            rel.fetch = orig
        self.assertEqual((rec["outcome"], rec["cause"]), ("fail", "fetch"))
        self.assertIn("fetch", rec["timings"])

    def test_empty_facts_never_raises(self):
        rec = rel.run_one("EMPTY", facts={"facts": {}, "entityName": "E", "cik": 1})
        self.assertEqual(rec["outcome"], "fail")
        self.assertTrue(rec["cause"])

    def test_untagged_revenue_is_a_concept_gap_failure(self):
        cf = synthetic_companyfacts(years=(2022, 2023, 2024))
        for c in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"):
            cf["facts"]["us-gaap"].pop(c, None)
        rec = rel.run_one("NOREV", facts=cf, engines=("om",))
        self.assertEqual((rec["outcome"], rec["cause"]), ("fail", "mapping/missing concept"))
        self.assertIn("Revenue", rec["detail"])


class Corpus(unittest.TestCase):
    def _runner(self, calls):
        def runner(t):
            calls.append(t)
            if t == "BAD":
                return {"ticker": t, "ifrs": True, "outcome": "fail", "cause": "IFRS concept gap", "detail": "untagged: Revenue",
                        "missing_concepts": ["Revenue"], "audit_flags": ["FY2024: Revenue is not tagged"], "timings": {"total": 2.0}}
            if t == "BANK":
                return {"ticker": t, "ifrs": False, "outcome": "unsupported", "cause": "unsupported", "detail": "financial company",
                        "audit_flags": [], "timings": {"total": 0.5}}
            return {"ticker": t, "ifrs": False, "outcome": "pass", "cause": "", "detail": "", "audit_flags": [], "model_seconds": 1.0 + len(calls),
                    "update": {"seconds": 10.0 + len(calls)}, "timings": {"total": 3.0}}
        return runner

    def test_resume_force_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            calls: list = []
            res = rel.run(["A", "B", "BAD", "BANK"], d, workers=2, runner=self._runner(calls))
            self.assertEqual(sorted(calls), ["A", "B", "BAD", "BANK"])
            self.assertEqual(set(json.loads((Path(d) / "results.json").read_text())), {"A", "B", "BAD", "BANK"})
            # resume: nothing re-run, a new ticker is
            calls.clear()
            rel.run(["A", "B", "C"], d, workers=2, runner=self._runner(calls))
            self.assertEqual(calls, ["C"])
            # force: everything re-run
            calls.clear()
            rel.run(["A", "B"], d, workers=1, force=True, runner=self._runner(calls))
            self.assertEqual(sorted(calls), ["A", "B"])
            self.assertEqual(set(json.loads((Path(d) / "results.json").read_text())), {"A", "B"})

    def test_summary_and_report_shape(self):
        with tempfile.TemporaryDirectory() as d:
            calls: list = []
            res = rel.run(["A", "B", "BAD", "BANK"], d, workers=1, runner=self._runner(calls))
            S = rel.summarize(res)
            self.assertEqual((S["attempted"], S["supported"], S["unsupported"], S["passed"], S["failed"]), (4, 3, 1, 2, 1))
            self.assertAlmostEqual(S["critical_pass_rate"], 2 / 3)
            self.assertAlmostEqual(S["pass_rate_all_attempted"], 0.5)
            self.assertEqual(S["causes"], {"IFRS concept gap": ["BAD"]})
            self.assertEqual(S["split"]["IFRS"]["attempted"], 1)
            self.assertEqual(S["ifrs_gap"]["share_explained"], 1.0)
            self.assertEqual(S["ifrs_gap"]["concepts"], {"Revenue": ["BAD"]})
            for k in ("p50", "p95", "n"):
                self.assertIn(k, S["build_seconds"])
                self.assertIn(k, S["update_seconds"])
            md = (Path(d) / "report.md").read_text()
            for needle in ("Critical-pass rate over supported", "Pass rate over all attempted", "## Failures by cause", "IFRS concept gap",
                           "BAD", "p50", "p95", "## US vs IFRS", "out of scope", "BANK"):
                self.assertIn(needle, md)

    def test_percentile(self):
        self.assertEqual(rel._pct([1, 2, 3, 4, 5], .5), 3)
        self.assertIsNone(rel._pct([], .5))
        self.assertEqual(rel._pct([7], .95), 7)


if __name__ == "__main__":
    unittest.main()
