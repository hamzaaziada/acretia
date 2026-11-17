"""S5.4a: integrity of the 10-K QA gold set (evals/tenk). Offline; no network, no LLM."""
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TENK = ROOT / "evals" / "tenk"


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


@unittest.skipUnless((TENK / "pdfs").is_dir(), "evals/tenk/pdfs absent (rebuild with scripts/build_tenk_corpus.py)")
class TenKCorpusIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from om import pdfdoc
        cls.manifest = json.loads((TENK / "manifest.json").read_text())
        cls.questions = json.loads((TENK / "questions.json").read_text())["questions"]
        cls.gold = [json.loads(l) for l in (TENK / "gold.jsonl").read_text().splitlines() if l.strip()]
        cls.files = {f["ticker"]: f for f in cls.manifest["filings"]}
        cls.docs = {t: pdfdoc.load(str(TENK / f["pdf"])) for t, f in cls.files.items()}

    def test_shape(self):
        self.assertEqual(len(self.files), 10)
        self.assertEqual(len(self.questions), 10)
        self.assertEqual(len(self.gold), 100)
        ids = [g["cell_id"] for g in self.gold]
        self.assertEqual(len(set(ids)), 100)
        for t in self.files:
            self.assertEqual(sorted(g["question_id"] for g in self.gold if g["ticker"] == t),
                             sorted(q["id"] for q in self.questions), t)

    def test_pdfs_match_manifest_sha256(self):
        total = 0
        for t, f in self.files.items():
            p = TENK / f["pdf"]
            self.assertTrue(p.exists(), p)
            data = p.read_bytes()
            total += len(data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), f["sha256"], t)
            self.assertLessEqual(len(data), 1_500_000, t)
            self.assertLessEqual(len(f["page_map"]), 25, t)
            self.assertEqual(len(f["page_map"]), len(self.docs[t].pages), t)
            self.assertTrue(f["primary_document"].startswith("https://www.sec.gov/Archives/edgar/data/"))
        self.assertLessEqual(total, 12_000_000)

    def test_every_quote_is_on_its_page(self):
        for g in self.gold:
            doc = self.docs[g["ticker"]]
            self.assertTrue(1 <= g["gold_page"] <= len(doc.pages), g["cell_id"])
            page = doc.pages[g["gold_page"] - 1]
            self.assertEqual(page.number, g["gold_page"])
            text = _norm(" ".join(l.text for l in page.lines))
            self.assertIn(_norm(g["gold_quote"]), text, g["cell_id"])
            self.assertTrue(3 <= len(g["gold_quote"].split()) <= 40, g["cell_id"])
            om = {m["page"]: m["orig_page"] for m in self.files[g["ticker"]]["page_map"]}
            self.assertEqual(om[g["gold_page"]], g["orig_page"], g["cell_id"])

    def test_answers_typed_and_in_quote(self):
        for g in self.gold:
            a = g["gold_answer"]
            if g["type"] in ("currency", "number"):
                self.assertIsInstance(float(a), float, g["cell_id"])
                self.assertTrue(g["unit"], g["cell_id"])
            elif g["type"] == "date":
                self.assertRegex(a, r"^\d{4}-\d{2}-\d{2}$")
            else:
                self.assertIsInstance(a, str)
                self.assertTrue(a.strip())

    def test_numeric_answers_appear_in_quote(self):
        for g in self.gold:
            if g["type"] == "currency" or (g["type"] == "number" and g["unit"] == "usd_per_share"):
                a = float(g["gold_answer"])
                forms = {f"{a:,.0f}", f"{a:,.2f}", f"{a:.2f}"}
                self.assertTrue(any(f in g["gold_quote"] for f in forms), (g["cell_id"], g["gold_quote"]))

    def test_xbrl_checks_match(self):
        n = 0
        for g in self.gold:
            if g["xbrl_check"] is not None:
                n += 1
                self.assertTrue(g["xbrl_check"]["match"], g["cell_id"])
                self.assertTrue(g["xbrl_check"]["concept"], g["cell_id"])
            else:
                self.assertNotIn(g["question_id"], {"q01", "q02", "q03", "q04", "q05", "q10"}, g["cell_id"])
        self.assertEqual(n, 60)


if __name__ == "__main__":
    unittest.main()
