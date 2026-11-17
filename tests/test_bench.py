"""S4.6a: OM-Bench 10 and the planted-error audit extended to LBO, merger and comps. Offline: synthetic fixtures only, no network."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from om import bench, validate_xlsx as vx  # noqa: E402
from tests.test_model3 import synthetic_companyfacts  # noqa: E402


class AuditNew(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = bench.synthetic_builds()
        cls.audit = bench.audit_all(cls.builds)
        cls.rows = {r["kind"]: r for m in cls.audit["models"] for r in m["rows"] if m["model"] != "model3"}

    def test_totals(self):
        t = self.audit["totals"]
        self.assertEqual(t["three_statement"], "10/10")
        self.assertEqual(t["new"], "9/9")
        self.assertGreaterEqual(t["new_planted"], 9)
        self.assertEqual(t["new_caught"], t["new_planted"])
        self.assertGreaterEqual(t["located_pct"], 90.0)
        self.assertGreaterEqual(t["new_located_pct"], 90.0)
        self.assertTrue(self.audit["ok"])

    def test_every_planned_plant_ran(self):
        self.assertEqual(set(self.rows), {k for _, k, _ in bench.NEW_PLANTS})
        self.assertEqual({m["model"] for m in self.audit["models"]}, {"model3", "lbo", "merger", "comps"})

    def test_each_new_plant_is_caught_and_located_on_its_cell(self):
        for kind, r in self.rows.items():
            self.assertTrue(r["caught"], kind)
            self.assertTrue(r["located"], f"{kind} not located at {r['cell']}")
            self.assertTrue(r["findings"] or r["graders_failed"], kind)

    def test_expected_detectors(self):
        want = {"lbo_sweep": {"hardcode.calc"}, "lbo_pik": {"consistency.columns", "modelcheck.consistency"},
                "lbo_exit": {"hardcode.typed"}, "mrg_shares": {"hardcode.calc"}, "mrg_goodwill": {"hardcode.isolated"},
                "mrg_synergy_tax": {"consistency.columns"}, "cmp_tsm": {"consistency.columns", "modelcheck.consistency"},
                "cmp_bridge": {"consistency.columns", "modelcheck.consistency"}, "cmp_nm": {"consistency.rows"}}
        for kind, ids in want.items():
            self.assertTrue(ids & set(self.rows[kind]["findings"]), (kind, self.rows[kind]["findings"]))

    def test_clean_lbo_and_merger_have_no_findings(self):
        by = {m["model"]: m for m in self.audit["models"]}
        for name in ("model3", "lbo", "merger"):
            self.assertTrue(by[name]["clean_passes"], (name, by[name].get("clean_ids")))

    def test_clean_comps_only_has_the_known_builder_finding(self):
        # BLOCKER (comps.py is outside this packet): the Checks sheet links to other sheets in black, not green.
        comps = next(m for m in self.audit["models"] if m["model"] == "comps")
        self.assertLessEqual(set(comps["clean_ids"]), {"links.green"})

    def test_plants_change_exactly_the_planted_cell(self):
        for m, kind, _ in bench.NEW_PLANTS:
            wb, meta = self.builds[m]
            w, (sh, rc) = bench.plant_new(wb, meta, kind)
            self.assertNotEqual((w[sh].cells[rc].value, w[sh].cells[rc].cached), (wb[sh].cells[rc].value, wb[sh].cells[rc].cached), kind)

    def test_original_workbook_untouched_by_planting(self):
        wb, meta = self.builds["lbo"]
        before = {k: c.value for k, c in wb["Debt"].cells.items()}
        bench.plant_new(wb, meta, "lbo_sweep")
        self.assertEqual(before, {k: c.value for k, c in wb["Debt"].cells.items()})

    def test_unknown_plant_rejected(self):
        wb, meta = self.builds["lbo"]
        with self.assertRaises(ValueError):
            bench.plant_new(wb, meta, "nope")

    def test_builder_outputs_pass_require_sources(self):
        for name in ("model3", "lbo", "merger"):
            res = vx.validate(self.builds[name][0].to_bytes(), require_sources=True)
            self.assertEqual([f for f in res["findings"] if f["severity"] == "critical"], [], name)
        res = vx.validate(self.builds["comps"][0].to_bytes(), require_sources=True)
        self.assertNotIn("sources.missing", {f["id"] for f in res["findings"]})


class RunS4Offline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.res = bench.run_s4(["AAPL", "KO"], cls.out, libreoffice=False, offline=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_shape(self):
        res = self.res
        self.assertEqual(res["universe"], ["AAPL", "KO"])
        kinds = [m["kind"] for m in res["models"]]
        self.assertEqual(kinds.count("model3"), 2)
        self.assertEqual(kinds.count("lbo"), 3)
        self.assertEqual(kinds.count("merger"), 2)
        self.assertEqual(kinds.count("comps"), 1)
        for m in res["models"]:
            self.assertTrue(m["supported"], m)
            for k in ("score", "production_ready", "validate_passed", "agree", "compared_cells", "seconds", "formulas", "three_engine", "engines"):
                self.assertIn(k, m)
            self.assertGreater(m["formulas"], 100)
            self.assertGreater(m["compared_cells"], 0)
            self.assertTrue(m["agree"], m["divergence_examples"])
            self.assertGreaterEqual(m["seconds"], 0)

    def test_every_workbook_passes_except_the_known_comps_finding(self):
        for m in self.res["models"]:
            if m["kind"] == "comps":
                self.assertLessEqual(set(m["validate_ids"]), {"links.green"})
            else:
                self.assertTrue(m["validate_passed"], m)
                self.assertTrue(m["production_ready"], m)
                self.assertGreaterEqual(m["score"], 95)

    def test_audit_included(self):
        self.assertTrue(self.res["audit"]["ok"])
        self.assertEqual(self.res["audit"]["totals"]["new"], "9/9")

    def test_files_written(self):
        data = json.loads((self.out / "results.json").read_text())
        self.assertEqual(len(data["models"]), len(self.res["models"]))
        md = (self.out / "report.md").read_text()
        self.assertIn("| Workbook | Score | Critical pass | Validate | Three-engine agree |", md)
        self.assertIn("## Planted-error audit", md)
        self.assertIn("AAPL three-statement model", md)
        self.assertTrue((self.out / "KO LBO.xlsx").exists())

    def test_defaults(self):
        self.assertEqual(bench.DEFAULT_10, ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "KO", "PG", "HD", "CAT"])
        self.assertEqual(bench.DEFAULT_OUT.parts[-4:], ("data", "out", "s4", "bench"))


class Substitution(unittest.TestCase):
    def test_unsupported_ticker_is_substituted_and_recorded(self):
        bank = synthetic_companyfacts()
        for c in ("AssetsCurrent", "LiabilitiesCurrent"):
            bank["facts"]["us-gaap"].pop(c)

        def loader(t):
            return bank if t == "BANK" else synthetic_companyfacts()
        with tempfile.TemporaryDirectory() as d:
            res = bench.run_s4(["BANK"], d, libreoffice=False, offline=True, loader=loader, deals=False)
        self.assertEqual(res["substitutions"][0]["from"], "BANK")
        self.assertEqual(res["substitutions"][0]["to"], bench.SUBSTITUTES[0])
        self.assertEqual(res["models"][0]["ticker"], bench.SUBSTITUTES[0])
        self.assertIn("BANK -> " + bench.SUBSTITUTES[0], bench.report_s4(res))

    def test_missing_ticker_without_substitute_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            res = bench.run_s4(["ZZZZ"], d, libreoffice=False, loader=lambda t: None, deals=False)
        self.assertFalse(res["models"][0]["supported"])
        self.assertEqual(len(res["substitutions"]), len(bench.SUBSTITUTES))


class Cli(unittest.TestCase):
    def test_main_offline(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as buf:
            rc = bench.main(["s4", "--offline", "--no-libreoffice", "--out", d, "AAPL"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(d) / "results.json").exists())
        self.assertIn("OM-Bench 10", buf.getvalue())

    def test_live_loader_requires_user_agent(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            with self.assertRaises(RuntimeError):
                bench._live_loader()
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old


if __name__ == "__main__":
    unittest.main()
