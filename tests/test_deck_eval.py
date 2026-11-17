"""S3.10 deck eval: corpus shape, reliability generator, eval keys, scorecard writer. Offline."""
import unittest

try:
    import pptx, PIL, fontTools, yaml  # noqa: F401,E401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om.deck import eval as ev  # noqa: E402
from om.deck import spec as specmod  # noqa: E402


class TestCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = ev.load_corpus()

    def test_twenty_valid_briefs_three_arabic(self):
        self.assertEqual(len(self.corpus), 20)
        self.assertEqual(sum(c["brief"]["spec"]["lang"] == "ar" for c in self.corpus), 3)
        for c in self.corpus:
            b = c["brief"]
            self.assertEqual(set(b), {"brief", "ghost", "spec"}, c["name"])
            self.assertEqual(specmod.validate(b["spec"]), [], c["name"])
            self.assertTrue(b["ghost"]["approved"], c["name"])
            self.assertTrue(8 <= len(b["spec"]["slides"]) <= 12, c["name"])
        self.assertGreaterEqual(sum(len(c["brief"]["spec"]["slides"]) == 10 for c in self.corpus), 5)

    def test_archetype_and_art_variety(self):
        archs = {s["archetype"] for c in self.corpus for s in c["brief"]["spec"]["slides"]}
        self.assertGreaterEqual(len(archs), 25)
        pinned = {c["brief"]["spec"]["art_direction"] for c in self.corpus} - {"auto"}
        self.assertGreaterEqual(len(pinned), 6)

    def test_sources_say_synthetic(self):
        for c in self.corpus:
            for s in c["brief"]["spec"]["slides"]:
                if s.get("source"):
                    self.assertIn("synthetic", s["source"], (c["name"], s["id"]))


class TestReliabilityGenerator(unittest.TestCase):
    def test_deterministic_and_varied(self):
        from evals.decks.reliability import generate
        a, b = generate.specs(100, 7), generate.specs(100, 7)
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 100)
        self.assertGreaterEqual(sum(s["lang"] == "ar" for s in a), 3)
        self.assertGreaterEqual(sum(len(s["slides"]) == 10 for s in a) / len(a), 0.30)
        self.assertTrue(all(6 <= len(s["slides"]) <= 12 for s in a))
        self.assertNotEqual(a[0], generate.specs(1, 8)[0])
        for s in a[:12]:
            self.assertEqual(specmod.validate(s), [], s["deck_id"])


class TestEval(unittest.TestCase):
    def test_two_corpus_decks_have_expected_keys(self):
        recs = ev.run_corpus(limit=2)
        self.assertEqual(len(recs), 2)
        for r in recs:
            for k in ("slides", "critical", "major", "variety", "unsourced", "art_direction", "build_seconds", "numbers_digest"):
                self.assertIn(k, r)
            self.assertEqual(r["critical"], 0, r["findings"])
            self.assertEqual(r["unsourced"], 0)
            self.assertEqual(r["numbers_digest"].__len__(), 64)

    def test_scorecard_keeps_other_stages(self):
        recs = [{"name": "01-x", "critical": 0, "major": 1, "variety": 0, "unsourced": 0, "build_seconds": 2.0, "ok": True}]
        rel = {"n": 10, "success_rate": 1.0, "p50_10_slide_s": 2.0, "p90_10_slide_s": 3.0, "unsourced": 0}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scorecard.csv"
            p.write_text('stage,eval,n,score,notes\nS8,standards_qa,50,0.980,"keep me"\nS3,old,1,0.5,"replace me"\n', encoding="utf-8")
            ev.write_scorecard(recs, rel, p)
            ev.write_scorecard(recs, rel, p)                       # idempotent
            lines = p.read_text(encoding="utf-8").splitlines()
        self.assertIn('S8,standards_qa,50,0.980,"keep me"', lines)
        self.assertFalse(any(l.startswith("S3,old") for l in lines))
        s3 = [l for l in lines if l.startswith("S3,")]
        self.assertEqual(len(s3), 3 + 1 + 1 + 3)
        for l in s3:
            if "not run live" in l:
                self.assertTrue(l.split(",")[3] == "", l)          # no score on a not-run-live row
        self.assertEqual(len(set(s3)), len(s3))


if __name__ == "__main__":
    unittest.main()
