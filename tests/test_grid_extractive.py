"""S5.F2: the extractive engine is precise and abstains. Synthetic statements + a real-corpus bar test (evals/tenk)."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om import docparse, grid  # noqa: E402
from om.grid import ExtractiveEngine, GridStore  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402

TENK = ROOT / "evals" / "tenk"


def pdf(pages):
    """pages: list of [(y, [(x, text), ...]), ...] -> PDF bytes."""
    w = PDFWriter()
    for rows in pages:
        w.page()
        for y, cells in rows:
            for x, t in cells:
                w.text(x, y, t, 9)
    return w.to_bytes()


def income_page(unit="(in millions, except per share)", years=("2024", "2023", "2022"), rev=("391,035", "383,285", "394,328")):
    r = [(740, [(72, "Consolidated Statements of Operations")]), (725, [(72, unit)]),
         (710, [(300, years[0]), (360, years[1]), (420, years[2])]),
         (695, [(72, "Net sales"), (300, rev[0]), (360, rev[1]), (420, rev[2])]),
         (680, [(72, "Total net sales"), (300, rev[0]), (360, rev[1]), (420, rev[2])]),
         (665, [(72, "Cost of sales"), (300, "210,352"), (360, "214,137"), (420, "223,546")]),
         (650, [(72, "Other income"), (300, "(1,234)"), (360, "(565)"), (420, "(334)")]),
         (635, [(72, "Net income"), (300, "93,736"), (360, "96,995"), (420, "99,803")]),
         (620, [(72, "Earnings per share:")]),
         (605, [(72, "Diluted"), (300, "6.08"), (360, "6.13"), (420, "6.11")])]
    return r


def run(doc_bytes, text, typ="text", qid="q"):
    st = GridStore(":memory:", parser_backend="pdfdoc")
    did = st.add_document(doc_bytes)
    doc = st.document(did)
    eng = ExtractiveEngine()
    c = st._finalize(doc, eng, eng.answer(doc, {"id": qid, "text": text, "type": typ}))
    return c, doc


class SyntheticStatements(unittest.TestCase):
    def test_current_period_column_and_unit(self):
        c, doc = run(pdf([income_page()]), "What was total net revenue for the latest fiscal year?", "currency")
        self.assertEqual(c["status"], "extracted")
        self.assertEqual(c["value"], 391035.0)                      # first column, not 383,285 / 394,328
        self.assertEqual(c["unit"], "USD millions")
        self.assertIsNotNone(docparse.locate(doc, c["page"], c["exact_quote"]))
        self.assertGreaterEqual(c["confidence"], 0.85)

    def test_parenthesised_negative(self):
        c, _ = run(pdf([income_page()]), "What was net income?", "currency")
        self.assertEqual(c["value"], 93736.0)
        w = pdf([[(740, [(72, "Consolidated Statements of Operations")]), (725, [(72, "(in millions)")]),
                  (710, [(300, "2024"), (360, "2023")]), (695, [(72, "Net income"), (300, "(1,390)"), (360, "1,143")])]])
        c, _ = run(w, "What was net income?", "currency")
        self.assertEqual(c["value"], -1390.0)

    def test_eps_is_not_the_share_count(self):
        c, _ = run(pdf([income_page()]), "What was diluted earnings per share?", "number")
        self.assertEqual((c["status"], c["value"], c["unit"]), ("extracted", 6.08, "USD per share"))

    def test_ascending_column_header_picks_last_column(self):
        c, _ = run(pdf([income_page(years=("2022", "2023", "2024"), rev=("394,328", "383,285", "391,035"))]),
                   "What was total net sales?", "currency")
        self.assertEqual(c["value"], 391035.0)

    def test_thousands_unit(self):
        c, _ = run(pdf([income_page(unit="(in thousands)")]), "What was total revenue?", "currency")
        self.assertEqual(c["unit"], "USD thousands")


class Abstention(unittest.TestCase):
    PROSE = pdf([[(700, [(72, "Our gasoline business represented 11% of total net sales in 2026.")]),
                  (680, [(72, "Pension cost was $121 million in the year and sales of widgets grew.")])]])

    def test_prose_only_weak_match_abstains_with_suggestion(self):
        c, _ = run(self.PROSE, "What was total net revenue for the latest fiscal year?", "currency")
        self.assertEqual(c["status"], "not_found")
        self.assertEqual(c["answer"], "Not found in document")
        self.assertIsNone(c["value"])

    def test_absent_concept_has_no_flag(self):
        c, _ = run(self.PROSE, "What is the zeppelin fleet maintenance budget?")
        self.assertEqual(c["status"], "not_found")
        self.assertEqual(c["flags"], [])

    def test_low_evidence_keeps_a_non_presented_suggestion(self):
        # a revenue row in an untitled, unit-less table: located, but too weak to present
        w = pdf([[(700, [(72, "Revenue"), (300, "3,910")]), (685, [(72, "Gross margin"), (300, "1,485"), (360, "1,524")]),
                  (670, [(72, "Revenue"), (300, "3,910"), (360, "4,066")])]])
        c, _ = run(w, "What was total revenue?", "currency")
        self.assertEqual(c["status"], "not_found")
        self.assertIn("low_evidence", c["flags"])
        self.assertEqual(c["exact_quote"], "")
        sg = [x for x in c["extra"] if x.get("suggestion")]
        self.assertEqual(len(sg), 1)
        self.assertIn("Revenue", sg[0]["quote"])
        self.assertIsNotNone(sg[0]["page"])

    def test_clause_question_without_the_concept_abstains(self):
        w = pdf([[(700, [(72, "This Agreement is governed by the laws of Delaware.")]),
                  (685, [(72, "All amounts are exclusive of value added tax.")])]])
        for t in ("Is there a most favoured nation (MFN) pricing clause?", "Is there an exclusivity or non-compete obligation?"):
            self.assertEqual(run(w, t)[0]["status"], "not_found", t)
        c, _ = run(w, "What is the governing law?")
        self.assertEqual((c["status"], c["answer"]), ("extracted", "Delaware"))


class HeaderRepetitionRule(unittest.TestCase):
    def _doc(self, repeat):
        pages = []
        for i in range(repeat):
            pages.append([(790, [(72, "ACME Confidential Running Header")]), (700, [(72, f"Filler text number {i} about nothing.")])])
        pages.append([(790, [(72, "Total net sales were $55 million in fiscal 2023.")]), (700, [(72, "Body text.")])])
        return pages

    def test_unique_top_line_is_kept_and_repeated_one_is_dropped(self):
        st = GridStore(":memory:", parser_backend="pdfdoc")
        doc = st.document(st.add_document(pdf(self._doc(4))))
        run_hdr = grid._running_headers(doc)
        texts = [b.text for p in doc.pages for b in p.blocks]
        self.assertTrue(any("Total net sales" in t for t in texts))
        self.assertIn(grid._norm_hdr("ACME Confidential Running Header"), run_hdr)
        self.assertFalse(any("Total net sales" in t for t in run_hdr))
        eng = grid.LLMEngine(adapter=type("A", (), {"model": "m"})())
        joined = " ".join(t for _p, t in eng.passages(doc, {"id": "q", "text": "What were total net sales?"}))
        self.assertIn("Total net sales were $55 million", joined)          # a real first line is not lost
        self.assertNotIn("Running Header", joined)                           # repeated on >= 3 pages: dropped

    def test_two_page_repeat_is_not_a_running_header(self):
        st = GridStore(":memory:", parser_backend="pdfdoc")
        doc = st.document(st.add_document(pdf(self._doc(2))))
        self.assertEqual(grid._running_headers(doc), set())


class Determinism(unittest.TestCase):
    def test_engine_version_bumped(self):
        self.assertNotEqual(grid.ENGINE_VERSION, "grid-1")


def _score(gold, cell):
    v = cell["value"]
    t = gold["type"]
    if t in ("currency", "number"):
        return isinstance(v, (int, float)) and abs(float(v) - float(gold["gold_answer"])) <= 0.005 * abs(float(gold["gold_answer"])) + 0.006
    if t == "date":
        return v == gold["gold_answer"]
    norm = lambda s: re.sub(r"[^\w&]+", " ", str(s).lower()).strip()  # noqa: E731
    return norm(gold["gold_answer"]) in norm(cell["answer"])


@unittest.skipUnless((TENK / "gold.jsonl").exists() and (TENK / "pdfs").exists(), "evals/tenk absent")
class RealCorpusBars(unittest.TestCase):
    def test_tenk_bars(self):
        qs = {q["id"]: {"id": q["id"], "text": q["question"], "type": q["type"]} for q in json.loads((TENK / "questions.json").read_text())["questions"]}
        golds = [json.loads(l) for l in (TENK / "gold.jsonl").read_text().splitlines() if l.strip()]
        st = GridStore(":memory:", parser_backend="pdfdoc")
        docs = {}
        eng = ExtractiveEngine()
        answered = correct = wrong = 0
        for g in golds:
            if g["ticker"] not in docs:
                docs[g["ticker"]] = st.document(st.add_document((TENK / g["pdf"]).read_bytes(), name=g["ticker"]))
            d = docs[g["ticker"]]
            c = st._finalize(d, eng, eng.answer(d, dict(qs[g["question_id"]])))
            if c["status"] == "extracted":
                answered += 1
                self.assertIsNotNone(docparse.locate(d, c["page"], c["exact_quote"]), g["cell_id"])
                if _score(g, c):
                    correct += 1
                else:
                    wrong += 1
        n = len(golds)
        self.assertGreaterEqual(correct / n, 0.70, f"accuracy {correct}/{n}")
        self.assertGreaterEqual(correct / max(1, answered), 0.95, f"precision {correct}/{answered}")
        self.assertLessEqual(wrong, 2, "wrong-but-confident")


if __name__ == "__main__":
    unittest.main()
