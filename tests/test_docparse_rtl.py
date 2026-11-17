"""S5.F3a: Arabic/RTL lines come out in logical order; Arabic quotes locate with word-accurate rects."""
import glob
import os
import re
import shutil
import subprocess
import unicodedata
import unittest

from om import docparse, pdfdoc
from om.docparse import _logical_word

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AR = sorted(glob.glob(os.path.join(ROOT, "evals", "vdr50", "docs", "**", "*(Arabic).pdf"), recursive=True))
AAPL = os.path.join(ROOT, "evals", "tenk", "pdfs", "AAPL.pdf")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
CTL = re.compile("[‎‏‪-‮⁦-⁩]")


def ws(t):
    return " ".join(CTL.sub("", t).split())


def cmp_key(t):
    """pdftotext reverses the internals of lam-alef ligature glyphs ('اإلدارة'), so compare words as
    sorted-letter multisets (word order and boundaries still have to agree)."""
    t = "".join(c if unicodedata.category(c)[0] not in "PSM" else " " for c in CTL.sub("", t))
    return [tuple(sorted(w)) for w in t.split()]


def pdftotext_lines(path, page=1):
    r = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), path, "-"], capture_output=True)
    return [ws(x) for x in r.stdout.decode("utf-8").splitlines() if ws(x)]


class TestLogicalWord(unittest.TestCase):
    def test_reverses_rtl_keeps_ltr_and_brackets(self):
        self.assertEqual(_logical_word("داوملل"), "للمواد")
        self.assertEqual(_logical_word(".)يرتشملا("), "(المشتري).")
        self.assertEqual(_logical_word(")دروملا("), "(المورد)")
        self.assertEqual(_logical_word("2024"), "2024")
        self.assertEqual(_logical_word("SUP-AR-07"), "SUP-AR-07")

    def test_ligature_glyph_keeps_internal_order(self):
        # lam-alef-hamza is ONE glyph that the extractor emits in logical order
        self.assertEqual(_logical_word("موينمللأا", ["م", "و", "ي", "ن", "م", "ل", "لأ", "ا"]), "الألمنيوم")


@unittest.skipUnless(AR and shutil.which("pdftotext"), "needs evals/vdr50 Arabic PDFs and pdftotext")
class TestArabicDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {p: docparse.parse(p, backend="pdfdoc") for p in AR}

    def test_first_line_matches_pdftotext(self):
        for p, d in self.docs.items():
            with self.subTest(os.path.basename(p)):
                self.assertEqual(cmp_key(d.pages[0].lines[0].text), cmp_key(pdftotext_lines(p)[0]))

    def test_blocks_are_logical_too(self):
        for p, d in self.docs.items():
            with self.subTest(os.path.basename(p)):
                self.assertEqual(cmp_key(d.pages[0].blocks[0].text.split("\n")[0]), cmp_key(pdftotext_lines(p)[0]))

    def test_mixed_line_code_and_date(self):
        p = next(x for x in AR if "Gulf Materials" in x)
        line = ws(self.docs[p].pages[0].lines[1].text)
        self.assertEqual(line, "الرقم المرجعي: SUP-AR-07 | التاريخ: March 2024 1")
        self.assertIn("SUP-AR-07", [w.text for w in self.docs[p].pages[0].lines[1].words])

    def test_brackets_not_flipped(self):
        p = next(x for x in AR if "Gulf Materials" in x)
        self.assertIn("(المورد)", " ".join(l.text for l in self.docs[p].pages[0].lines))

    def test_locate_arabic_quotes_from_pdftotext(self):
        for p, d in self.docs.items():
            have = {w for l in d.pages[0].lines for w in l.text.split()}
            quotes = []
            for l in pdftotext_lines(p):
                t = l.split()
                for i in range(len(t) - 2):
                    q = t[i:i + 3]
                    if all(w in have for w in q) and any(re.search("[\u0600-\u06ff]", w) for w in q):
                        quotes.append(" ".join(q))
                        break
            self.assertGreaterEqual(len(quotes), 3, os.path.basename(p))
            for q in quotes[:3]:
                with self.subTest(q):
                    loc = docparse.locate(d, 1, q)
                    self.assertIsNotNone(loc)
                    self.assertEqual(loc.page, 1)
                    self.assertTrue(loc.rects)

    def test_locate_phrases_word_accurate(self):
        p = next(x for x in AR if "Gulf Materials" in x)
        d = self.docs[p]
        for q, n in (("عقد توريد", 2), ("شركة الخليج للمواد", 3), ("SUP-AR-07", 1), ("2,300,000 درهم", 2)):
            with self.subTest(q):
                loc = docparse.locate(d, 1, q)
                self.assertIsNotNone(loc)
                self.assertEqual(len(loc.text.split()), n)
                x0, y0, x1, y1 = loc.bbox_norm
                self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1)
                self.assertTrue(loc.rects)
                self.assertRegex(loc.sha256_span_hash, HEX64)
        self.assertIsNone(docparse.locate(d, 1, "داوملل جيلخلا"))   # visual order must no longer match
        self.assertIsNotNone(docparse.find_quote(d, "شركة الخليج للمواد"))

    def test_bbox_and_hash_validity(self):
        for p, d in self.docs.items():
            for pg in d.pages:
                for l in pg.lines:
                    self.assertRegex(l.sha256_span_hash, HEX64)
                    self.assertEqual(l.sha256_span_hash, pdfdoc.span_hash(l.page, l.text, l.bbox_norm))
                    self.assertEqual(l.bbox_norm, (min(w.bbox_norm[0] for w in l.words), min(w.bbox_norm[1] for w in l.words),
                                                   max(w.bbox_norm[2] for w in l.words), max(w.bbox_norm[3] for w in l.words)))
                    self.assertEqual(l.text, " ".join(w.text for w in l.words))
                    for w in l.words:
                        self.assertEqual(w.sha256_span_hash, pdfdoc.span_hash(w.page, w.text, w.bbox_norm))
                for b in pg.blocks:
                    self.assertRegex(b.sha256_span_hash, HEX64)
                    self.assertEqual(b.sha256_span_hash, pdfdoc.span_hash(b.page, b.text, b.bbox_norm))

    def test_completeness_rtl_tolerant(self):
        for p, d in self.docs.items():
            with self.subTest(os.path.basename(p)):
                for pg in d.pages:
                    self.assertGreaterEqual(pg.completeness, docparse.COMPLETENESS_MIN)


@unittest.skipUnless(AR and docparse.docling_available(), "needs docling + vdr50 Arabic PDFs")
class TestDoclingConsistent(unittest.TestCase):
    def test_docling_and_pdfdoc_agree_on_logical_order(self):
        p = next(x for x in AR if "Gulf Materials" in x)
        dl = docparse.parse(p, backend="docling")
        texts = " ".join(b.text for b in dl.pages[0].blocks)
        self.assertIn("شركة الخليج للمواد", texts)        # docling text is already logical
        for b in dl.pages[0].blocks:                      # recovered lines come from the logical pdfdoc lines
            self.assertNotIn("داوملل", b.text)
        self.assertIsNotNone(docparse.locate(dl, 1, "شركة الخليج للمواد"))


@unittest.skipUnless(os.path.exists(AAPL), "needs evals/tenk/pdfs/AAPL.pdf")
class TestLatinUnchanged(unittest.TestCase):
    def test_latin_lines_are_visual_order_untouched(self):
        pdf = pdfdoc.load(AAPL, ocr=False)
        want = [[l.text for l in pg.lines] for pg in pdf.pages[:5]]
        with open(AAPL, "rb") as fh:
            pdf2 = docparse._to_logical(pdfdoc.load(AAPL, ocr=False), fh.read())
        self.assertEqual([[l.text for l in pg.lines] for pg in pdf2.pages[:5]], want)
        for a, b in zip(pdf.pages[:5], pdf2.pages[:5]):
            self.assertEqual([l.sha256_span_hash for l in a.lines], [l.sha256_span_hash for l in b.lines])


if __name__ == "__main__":
    unittest.main()
