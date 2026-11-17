"""Time-saved baselines parser: the real doc, no-baseline rows, malformed tables. Offline."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.tsb import baselines as B  # noqa: E402

TASKS14 = ("comps", "precedents", "three_statement", "dcf", "lbo", "merger", "vdr_review", "profile", "pitchbook_section",
           "teaser", "ic_memo", "earnings_update", "earnings_recap", "buyer_list")


class RangeTests(unittest.TestCase):
    def test_free_text_ranges(self):
        self.assertEqual(B.parse_range("2–3 hrs (strong analyst)"), (120, 180))
        self.assertEqual(B.parse_range("~90 min"), (90, 90))
        self.assertEqual(B.parse_range("15 min–2 hrs"), (15, 120))
        self.assertEqual(B.parse_range("20–30 hrs (at ~0.4–0.6 hr per doc)"), (1200, 1800))
        self.assertEqual(B.parse_range("30–60 min simple; 3–6 hrs first pass"), (30, 60))

    def test_no_range_raises(self):
        with self.assertRaises(B.BaselineParseError):
            B.parse_range("a few hours-ish")


class RealDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = B.load()
        cls.t = cls.d["tasks"]

    def test_all_14_tasks_present(self):
        for t in TASKS14:
            self.assertIn(t, self.t)

    def test_known_values(self):
        self.assertAlmostEqual(self.t["dcf"]["t_h_mid"], 90, delta=1)
        self.assertEqual((self.t["three_statement"]["t_h_low"], self.t["three_statement"]["t_h_high"]), (120, 180))
        self.assertEqual((self.t["vdr_review"]["t_h_low"], self.t["vdr_review"]["t_h_high"]), (1200, 1800))
        self.assertEqual((self.t["earnings_update"]["t_h_low"], self.t["earnings_update"]["t_h_high"]), (15, 120))
        self.assertEqual((self.t["lbo"]["t_h_low"], self.t["lbo"]["t_h_high"]), (480, 720))

    def test_geometric_mid(self):
        r = self.t["three_statement"]
        self.assertAlmostEqual(r["t_h_mid"], (120 * 180) ** 0.5, delta=0.1)
        self.assertLess(r["t_h_low"], r["t_h_mid"])
        self.assertLess(r["t_h_mid"], r["t_h_high"])

    def test_no_baseline_tasks_have_no_number(self):
        for t in ("profile", "pitchbook_section", "teaser", "buyer_list", "earnings_recap"):
            self.assertEqual(self.t[t]["baseline"], "own timing study needed")
            self.assertNotIn("t_h_mid", self.t[t])

    def test_confidence_and_source(self):
        self.assertEqual(self.t["dcf"]["confidence"], "low")
        self.assertEqual(self.t["three_statement"]["confidence"], "medium")
        self.assertIn("WSP", self.t["three_statement"]["source"])

    def test_competitor_claims(self):
        c = self.d["competitor_claims"]
        self.assertGreaterEqual(len(c), 10)
        types = {x["type"] for x in c}
        self.assertIn("independent", types)
        self.assertTrue(any(x["who"].startswith("Rogo") for x in c))

    def test_time_saved_helpers(self):
        ts = B.time_saved("dcf", 9)
        self.assertEqual(ts["basis"], "estimate")
        self.assertAlmostEqual(ts["pct"]["mid"], 0.9, delta=0.01)
        self.assertEqual(B.time_saved("teaser", 5)["baseline"], "own timing study needed")
        self.assertEqual(B.time_saved("deck_edit", 5)["baseline"], "own timing study needed")


class MalformedTests(unittest.TestCase):
    def doc(self, body):
        d = tempfile.mkdtemp()
        p = Path(d) / "b.md"
        p.write_text(body, encoding="utf-8")
        return p

    def test_missing_table_raises(self):
        with self.assertRaises(B.BaselineParseError):
            B.load(self.doc("# x\n\n## 2. Human baselines\n\nno table here\n"))

    def test_bad_range_raises(self):
        real = B.DEFAULT_PATH.read_text(encoding="utf-8").replace("~90 min", "about an hour or so")
        with self.assertRaises(B.BaselineParseError):
            B.load(self.doc(real))

    def test_missing_task_row_raises(self):
        real = "\n".join(ln for ln in B.DEFAULT_PATH.read_text(encoding="utf-8").splitlines() if not ln.startswith("| DCF"))
        with self.assertRaises(B.BaselineParseError):
            B.load(self.doc(real))

    def test_short_row_raises(self):
        real = B.DEFAULT_PATH.read_text(encoding="utf-8").replace("| DCF | ~90 min | Shortcut time cap [vendor] | low |", "| DCF | ~90 min |")
        with self.assertRaises(B.BaselineParseError):
            B.load(self.doc(real))


if __name__ == "__main__":
    unittest.main()
