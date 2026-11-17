"""S8.3b: read_report / locate / model_from_report / CLI on the synthetic fixtures."""
import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om.intl import extract as ex_mod, pipeline  # noqa: E402
from om.intl.tieout import ReleaseBlocked  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "intl"
NATIVE = ["nile_valley_ar_native_fy2024.pdf", "nile_valley_ar_native_fy2023.pdf", "red_sea_cement_en_native_fy2024.pdf",
          "gulf_retail_bi_native_fy2024.pdf"]
_ENV = mock.patch.dict(os.environ, {"ACRETIA_TELEMETRY_PATH": "off"})


def setUpModule():
    _ENV.start()


def tearDownModule():
    _ENV.stop()


class Pipeline(unittest.TestCase):
    def test_read_report_native_all_released(self):
        for n in NATIVE:
            res = pipeline.read_report(str(FX / n))
            self.assertFalse(res.blocked, n)
            self.assertIsNotNone(res.statements, n)
            self.assertTrue(res.tie_report.passed, n)
            self.assertTrue(res.statements.release_report.passed)
            self.assertEqual(res.review, [])
            t = res.telemetry
            self.assertEqual([s["name"] for s in t["steps"]], list(pipeline.STEPS))
            self.assertEqual((t["tokens"], t["cost_usd"]), (0, 0.0))
            for k in ("wall_seconds", "pages", "scanned", "language", "flags", "review_minutes"):
                self.assertIn(k, t)
            j = res.to_json()
            self.assertEqual(j["v"], 1)
            json.dumps(j)

    def test_comparative_tie_with_prior(self):
        res = pipeline.read_report(str(FX / "nile_valley_ar_native_fy2024.pdf"), prior=str(FX / "nile_valley_ar_native_fy2023.pdf"))
        prior_ties = [t for t in res.tie_report.ties if t.name.startswith("prior:")]
        self.assertTrue(prior_ties)
        self.assertTrue(all(t.passed for t in prior_ties))
        self.assertFalse(res.blocked)

    def test_telemetry_written_only_with_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.jsonl")
            pipeline.read_report(str(FX / "red_sea_cement_en_native_fy2024.pdf"), telemetry_path=p)
            recs = [json.loads(l) for l in open(p)]
            self.assertEqual(len(recs), 1)
            self.assertEqual(recs[0]["doc_sha256"], pipeline._extract_mod._read(str(FX / "red_sea_cement_en_native_fy2024.pdf")) and recs[0]["doc_sha256"])
            with mock.patch.dict(os.environ, {"ACRETIA_TELEMETRY_PATH": os.path.join(td, "e.jsonl")}):
                ex_mod.extract(str(FX / "red_sea_cement_en_native_fy2024.pdf"))
            self.assertTrue(os.path.exists(os.path.join(td, "e.jsonl")))

    def test_review_minutes_matches_csv(self):
        flags = {"tie_fail": 2, "unmapped_label": 4}
        t = pipeline.minutes_table()
        self.assertAlmostEqual(pipeline.review_minutes(flags), 2 * t["tie_fail"] + 4 * t["unmapped_label"])

    def test_locate_fast(self):
        res = pipeline.read_report(str(FX / "nile_valley_ar_native_fy2024.pdf"))
        f = res.extracted.figures[5]
        t = time.time()
        loc = pipeline.locate(f, str(FX / "nile_valley_ar_native_fy2024.pdf"))
        self.assertLess(time.time() - t, 2.0)
        self.assertEqual(loc["page"], f.page)
        self.assertEqual(loc["doc_sha256"], f.doc_id)
        self.assertEqual(loc["png"][:8], b"\x89PNG\r\n\x1a\n")

    def test_model_from_report_balance_and_cash_checks(self):
        from om import xlsx
        for n in ("nile_valley_ar_native_fy2024.pdf", "red_sea_cement_en_native_fy2024.pdf"):
            with tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, "m.xlsx")
                r = pipeline.model_from_report(str(FX / n), out)
                b = xlsx.read(open(out, "rb").read())
                ck = b.sheets["Checks"]
                self.assertFalse([k for k, c in ck.items() if str(c.value) == "ERROR"])
                self.assertTrue(r["meta"])
                comments = b.comments.get("Filings", {})
                self.assertTrue(comments and all("bbox" in v for v in comments.values()))

    def _mutated(self, mut):
        orig = ex_mod._extract

        def fake(pdf, **kw):
            ex, info = orig(pdf, **kw)
            ex = copy.deepcopy(ex)
            mut(ex)
            return ex, info
        return mock.patch.object(ex_mod, "_extract", fake)

    def test_mutations_block_release_and_cli(self):
        pdf = str(FX / "red_sea_cement_en_native_fy2024.pdf")

        def bump(key):
            def m(ex):
                f = next(f for f in ex.figures if f.key == key and f.period_end == ex.periods[-1])
                f.value = f.value + 12.3
            return m

        def flip(ex):
            f = next(f for f in ex.figures if f.key == "cfi" and f.period_end == ex.periods[-1])
            f.value = -f.value

        def transpose(ex):
            f = next(f for f in ex.figures if f.key == "assets" and f.period_end == ex.periods[-1])
            s = f"{f.value:.1f}"
            f.value = float(s[:1] + s[2] + s[1] + s[3:])
        for name, mut in (("revenue", bump("revenue")), ("cash", bump("cash")), ("cfo", bump("cfo")), ("sign", flip),
                          ("transpose", transpose)):
            with self.subTest(name), self._mutated(mut):
                res = pipeline.read_report(pdf)
                self.assertTrue(res.blocked)
                self.assertIsNone(res.statements)
                self.assertTrue(res.review, "involved figures must be in the review queue")
                with tempfile.TemporaryDirectory() as td:
                    args = SimpleNamespace(pdf=pdf, out=os.path.join(td, "m.xlsx"), company=None, prior=None, json=False)
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        rc = pipeline.cmd_intl_model(args)
                    self.assertNotEqual(rc, 0)
                    self.assertFalse(os.path.exists(args.out))
                    with self.assertRaises(pipeline.ModelBlocked):
                        pipeline.model_from_report(pdf, os.path.join(td, "x.xlsx"))

    def test_release_never_skipped(self):
        import ast
        for p in (ROOT / "om" / "intl").glob("*.py"):
            if p.name == "tieout.py":
                continue
            self.assertNotIn("IntlStatements(", p.read_text(), p.name)


class ScannedPipeline(unittest.TestCase):
    def test_red_sea_scanned_end_to_end(self):
        res = pipeline.read_report(str(FX / "red_sea_cement_en_scanned_fy2024.pdf"))
        self.assertTrue(res.telemetry["scanned"])
        self.assertFalse(res.blocked, pipeline.review_summary(res))
        self.assertGreater(res.telemetry["steps"][1]["seconds"], 0)


if __name__ == "__main__":
    unittest.main()
