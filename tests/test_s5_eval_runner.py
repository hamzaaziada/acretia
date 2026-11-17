"""S5.4b: scorer unit tests + VDR50 manifest integrity. Fast (< 30 s); heavy parts skip with a reason."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("eval_s5", ROOT / "scripts" / "eval_s5.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

VDR = ROOT / "evals" / "vdr50"


def cell(answer="", value=None, status="extracted", quote="q", page=1, unit=None):
    return {"answer": answer, "value": value, "status": status, "exact_quote": quote, "page": page, "unit": unit}


class FakeDoc:
    """docparse.locate stand-in: quotes in `ok` are located."""


class ScorerTests(unittest.TestCase):
    def setUp(self):
        self._loc = ev.docparse.locate
        ev.docparse.locate = lambda doc, page, quote: object() if quote == "q" else None

    def tearDown(self):
        ev.docparse.locate = self._loc

    def gold(self, **kw):
        g = {"cell_id": "c", "room": "tenk", "expect": "found", "type": "currency", "gold_answer": 478834, "unit": "usd_millions", "gold_page": 1}
        g.update(kw)
        return g

    def test_unit_normalisation(self):
        self.assertEqual(ev.parse_numbers("$48.2 million and 1,250 thousand"), [48200000.0, 1250000.0])
        g = self.gold()
        self.assertTrue(ev.value_matches(g, cell("Total net sales 478,834", 478834)))
        self.assertTrue(ev.value_matches(g, cell("net sales were $478.8 billion", None)))     # 478.8bn within 0.5%
        self.assertTrue(ev.value_matches(g, cell("x", 478834000000.0)))
        self.assertFalse(ev.value_matches(g, cell("Total net sales 416,161", 416161)))

    def test_numeric_tolerance(self):
        g = self.gold(gold_answer=1000, unit="usd")
        self.assertTrue(ev.value_matches(g, cell("1,004", 1004.0)))
        self.assertFalse(ev.value_matches(g, cell("1,006", 1006.0)))
        eps = self.gold(type="number", gold_answer=8.98, unit="usd_per_share")
        self.assertTrue(ev.value_matches(eps, cell("Diluted $ 8.98", 8.98)))
        self.assertFalse(ev.value_matches(eps, cell("Diluted $ 8.20", 8.2)))

    def test_dates_and_text(self):
        d = self.gold(type="date", gold_answer="2026-09-26", unit="iso_date")
        self.assertTrue(ev.value_matches(d, cell("For the fiscal year ended September 26, 2026")))
        self.assertTrue(ev.value_matches(d, cell("expires 26 September 2026")))
        self.assertFalse(ev.value_matches(d, cell("fiscal year ended September 27, 2026")))
        t = self.gold(type="text", gold_answer="Ernst & Young LLP", unit=None)
        self.assertTrue(ev.value_matches(t, cell("/s/ Ernst & Young LLP")))
        self.assertFalse(ev.value_matches(t, cell("/s/ KPMG LLP")))

    def test_not_found_scoring(self):
        g = self.gold(expect="not_found", gold_answer=None, gold_page=None)
        self.assertEqual(ev.score_cell(g, cell(status="not_found"), None)["outcome"], "success")
        r = ev.score_cell(g, cell("some sentence", status="extracted"), None)
        self.assertEqual(r["outcome"], "wrong_but_confident")
        self.assertEqual(ev.score_cell(g, cell(status="unverified"), None)["outcome"], "missed")

    def test_success_wrong_and_silent(self):
        g = self.gold()
        ok = ev.score_cell(g, cell("Total net sales 478,834", 478834), None)
        self.assertEqual((ok["outcome"], ok["page_ok"], ok["silent"]), ("success", True, False))
        wrong = ev.score_cell(g, cell("Total net sales 416,161", 416161), None)
        self.assertEqual(wrong["outcome"], "wrong_but_confident")
        silent = ev.score_cell(g, cell("Total net sales 478,834", 478834, quote="not located"), None)
        self.assertTrue(silent["silent"])
        self.assertNotEqual(silent["outcome"], "success")
        missed = ev.score_cell(g, cell(status="not_found"), None)
        self.assertEqual(missed["outcome"], "missed")
        s = ev.summarise([ok, wrong, silent, missed])
        self.assertEqual((s["n"], s["success"], s["wrong_but_confident"], s["silent"]), (4, 1, 1, 1))

    def test_scorecard_only_touches_s5_rows(self):
        import tempfile
        old = ev.SCORECARD
        with tempfile.TemporaryDirectory() as td:
            ev.SCORECARD = Path(td) / "scorecard.csv"
            ev.SCORECARD.write_text('stage,eval,n,score,notes\nS8,x,1,1.0,"a, b"\nS5,old,1,1,z\n')
            ev.update_scorecard([["S5", "new", 2, "0.5", "n"]])
            self.assertEqual(ev.SCORECARD.read_text(), 'stage,eval,n,score,notes\nS8,x,1,1.0,"a, b"\nS5,new,2,0.5,n\n')
        ev.SCORECARD = old


@unittest.skipUnless((VDR / "manifest.json").exists(), "run scripts/build_vdr50.py first")
class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man = json.loads((VDR / "manifest.json").read_text())
        cls.gold = [json.loads(l) for l in (VDR / "gold.jsonl").read_text().splitlines()]

    def test_fifty_docs_and_hashes(self):
        import hashlib
        files = self.man["files"]
        self.assertEqual(len(files), 50)
        self.assertEqual(sum(f["room"] == "tenk" for f in files), 10)
        self.assertGreaterEqual(sum(f["room"] != "tenk" for f in files), 30)
        for f in files:
            self.assertEqual(hashlib.sha256((ROOT / f["ref"]).read_bytes()).hexdigest(), f["sha256"], f["path"])

    def test_scanned_have_no_text_layer_and_arabic_has_arabic(self):
        from om import pdfdoc
        scanned = [f for f in self.man["files"] if f["scanned"]]
        arabic = [f for f in self.man["files"] if f["language"] == "ar"]
        self.assertGreaterEqual(len(scanned), 3)
        self.assertGreaterEqual(len(arabic), 3)
        import re
        for f in scanned:     # no text layer: raw poppler/pdfplumber text is empty (OCR is applied only by pdfdoc.load)
            doc = pdfdoc.load((ROOT / f["ref"]).read_bytes(), ocr=False)
            self.assertTrue(all(not p.words for p in doc.pages), f["path"])
        for f in arabic:
            doc = pdfdoc.load((ROOT / f["ref"]).read_bytes(), ocr=False)
            self.assertTrue(re.search(r"[؀-ۿ]", doc.text()), f["path"])

    def test_gold_shape_and_quotes_on_gold_pages(self):
        from om import docparse
        found = [g for g in self.gold if g["expect"] == "found"]
        self.assertGreaterEqual(len(self.gold), 100)
        by = {}
        for g in found:
            by.setdefault(g["doc"], []).append(g)
        digital = [d for d in by if not by[d][0]["scanned"]]            # scanned quotes need OCR (slow): checked by build_vdr50
        checked = 0
        for d in digital[:12]:
            parsed = docparse.parse((ROOT / "evals" / "vdr50" / "docs" / d).read_bytes(), backend="pdfdoc", ocr=False)
            for g in by[d]:
                self.assertIsNotNone(docparse.locate(parsed, g["gold_page"], g["gold_quote"]), (d, g["question_id"]))
                checked += 1
        self.assertGreater(checked, 10)
        for g in self.gold:
            self.assertIn(g["expect"], ("found", "not_found"))
            if g["expect"] == "not_found":
                self.assertIsNone(g["gold_page"])

    def test_total_gold_across_three_rooms(self):
        tenk = sum(1 for _ in (ROOT / "evals" / "tenk" / "gold.jsonl").read_text().splitlines())
        rooms = {g["room"] for g in self.gold} | {"tenk"}
        self.assertGreaterEqual(tenk + len(self.gold), 200)
        self.assertGreaterEqual(len(rooms), 3)


if __name__ == "__main__":
    unittest.main()
