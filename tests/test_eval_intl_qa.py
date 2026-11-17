import collections
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("eval_intl_qa", ROOT / "scripts" / "eval_intl_qa.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

Q = {"id": "t1", "key_points": ["right.of.use", "lease liabilit", "single model", "depreciation"], "must_cite": ["IFRS 16"]}
C = [{"standard": "IFRS 16", "ref": "para 22", "url": "https://x.org/a"}]
FULL = "The lessee recognises a Right-of-Use asset and a lease liability under a single model with depreciation."


class Scorer(unittest.TestCase):
    def test_full_pass(self):
        self.assertTrue(ev.score_answer(Q, FULL, C)["pass"])

    def test_threshold_edges(self):
        three = "right of use asset, lease liability, single model"
        self.assertTrue(ev.score_answer(Q, three, C)["pass"])  # 3/4 = 0.75 passes
        two = "right of use asset, lease liability"
        self.assertFalse(ev.score_answer(Q, two, C)["pass"])  # 2/4 fails

    def test_missing_cite_fails(self):
        self.assertFalse(ev.score_answer(Q, FULL, [{"standard": "IAS 2", "ref": "", "url": "https://x"}])["pass"])
        self.assertFalse(ev.score_answer(Q, FULL, [])["pass"])

    def test_missing_url_fails(self):
        bad = C + [{"standard": "IAS 1", "ref": "", "url": ""}]
        self.assertFalse(ev.score_answer(Q, FULL, bad)["pass"])
        self.assertFalse(ev.score_answer(Q, FULL, [{"standard": "IFRS 16", "ref": "x"}])["pass"])

    def test_case_and_arabic_normalisation(self):
        self.assertTrue(ev.point_matches("LEASE LIABILIT", "Lease Liability"))
        self.assertTrue(ev.point_matches("زكاه", "الزكاة"))
        self.assertTrue(ev.point_matches("2024", "عام ٢٠٢٤"))

    def test_percent_normalisation(self):
        for txt in ("rate of 2.5 percent", "rate of 2.5 per cent", "rate of 2.5 pct", "rate of 2.5 %", "rate of 2.5%"):
            self.assertTrue(ev.point_matches(r"2\.5 ?%", txt), txt)
        self.assertTrue(ev.point_matches("9 percent", "tax at 9%"))
        self.assertFalse(ev.point_matches(r"2\.5 ?%", "rate of 25 percent"))

    def test_bad_regex_falls_back_to_literal(self):
        self.assertTrue(ev.point_matches("a(b", "xa(by"))

    def test_scorecard_replace_keeps_others(self):
        import tempfile
        p = Path(tempfile.mkdtemp()) / "scorecard.csv"
        p.write_text("stage,eval,n,score,notes\nS3,x,1,0.5,keep\nS8,standards_qa,9,0.1,old\n")
        ev.write_scorecard(50, 0.9, p)
        lines = p.read_text().splitlines()
        self.assertEqual(lines[0], "stage,eval,n,score,notes")
        self.assertIn("S3,x,1,0.5,keep", lines)
        s8 = [l for l in lines if l.startswith("S8,standards_qa")]
        self.assertEqual(len(s8), 1)
        self.assertIn("50,0.900", s8[0])
        self.assertIn("live_model=no", s8[0])


class Schema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qs = ev.load_questions()

    def test_count_and_ids(self):
        self.assertEqual(len(self.qs), 50)
        self.assertEqual(len({q["id"] for q in self.qs}), 50)

    def test_fields(self):
        for q in self.qs:
            for k in ("id", "question", "topic", "frameworks", "key_points", "must_cite"):
                self.assertTrue(q.get(k), (q["id"], k))
            self.assertTrue(2 <= len(q["key_points"]) <= 4, q["id"])
            self.assertIsInstance(q["frameworks"], list)
            for p in q["key_points"]:
                import re
                re.compile(p)

    def test_topic_spread(self):
        def n(pred):
            return sum(1 for q in self.qs if pred(q))
        fw = lambda q, f: f in q["frameworks"]
        self.assertGreaterEqual(n(lambda q: q["frameworks"] == ["IFRS"]), 18)
        self.assertGreaterEqual(n(lambda q: fw(q, "EAS")), 10)
        self.assertGreaterEqual(n(lambda q: fw(q, "SOCPA-IFRS") or fw(q, "UAE-IFRS")), 8)
        self.assertGreaterEqual(n(lambda q: fw(q, "USGAAP")), 6)
        self.assertGreaterEqual(n(lambda q: fw(q, "FRS102")), 3)
        self.assertGreaterEqual(n(lambda q: fw(q, "IndAS")), 3)
        mc = collections.Counter(c for q in self.qs for c in q["must_cite"])
        for s in ("IFRS 15", "IFRS 16", "IFRS 9", "IFRS 3", "IFRS 10", "IAS 2", "IAS 7", "IAS 12", "IAS 16", "IAS 19", "IAS 21",
                  "IAS 23", "IAS 28", "IAS 29", "IAS 36", "IAS 37", "IAS 38", "IAS 40", "IFRS 8", "IAS 24", "IAS 33",
                  "EAS 47", "EAS 48", "EAS 49", "EAS 13"):
            self.assertIn(s, mc)


if __name__ == "__main__":
    unittest.main()
