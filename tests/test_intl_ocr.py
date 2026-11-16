import json
import os
import re
import shutil
import unittest

from om.intl.numparse import normalise_digits

HAVE_OCR = bool(shutil.which("tesseract") and shutil.which("pdftoppm") and shutil.which("pdfinfo"))
FIX = os.path.join(os.path.dirname(__file__), "fixtures", "intl")


def _manifest():
    with open(os.path.join(FIX, "manifest.json"), encoding="utf-8") as fh:
        return {f["file"]: f for f in json.load(fh)["fixtures"]}


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def digit_accuracy(entry, doc):
    """Character accuracy over the digits of every printed figure (greedy one-to-one token matching)."""
    total = err = 0
    for pg in sorted({g["page"] for g in entry["ground_truth"]}):
        truth = [re.sub(r"\D", "", normalise_digits(g["raw"])) for g in entry["ground_truth"] if g["page"] == pg]
        truth = [t for t in truth if t]
        cand = [re.sub(r"\D", "", normalise_digits(w.text)) for w in doc.pages[pg - 1].words]
        cand = [c for c in cand if c]
        for t in truth:
            if cand:
                best = min(range(len(cand)), key=lambda i: lev(t, cand[i]))
                err += lev(t, cand[best])
                cand.pop(best)
            else:
                err += len(t)
            total += len(t)
    return 1 - err / total


@unittest.skipUnless(HAVE_OCR, "tesseract / pdftoppm not installed")
class OcrFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from om.intl import ocr
        cls.ocr = ocr
        cls.man = _manifest()
        cls.docs = {}

    def doc(self, name):
        if name not in self.docs:
            self.docs[name] = self.ocr.ocr_pdf(os.path.join(FIX, name), dpi=300)
        return self.docs[name]

    def test_scanned_arabic_digit_accuracy(self):
        name = "nile_valley_ar_scanned_fy2024.pdf"
        acc = digit_accuracy(self.man[name], self.doc(name))
        print(f"\nArabic scanned digit accuracy: {acc:.4%}")
        self.assertGreaterEqual(acc, 0.99)

    def test_scanned_english_digit_accuracy(self):
        name = "red_sea_cement_en_scanned_fy2024.pdf"
        self.assertGreaterEqual(digit_accuracy(self.man[name], self.doc(name)), 0.99)

    def test_words_flagged_and_bboxes_normalised(self):
        for name in ("nile_valley_ar_scanned_fy2024.pdf", "red_sea_cement_en_scanned_fy2024.pdf"):
            doc = self.doc(name)
            self.assertEqual(len(doc.pages), self.man[name]["pages"])
            n = 0
            for p in doc.pages:
                for w in p.words:
                    n += 1
                    x0, y0, x1, y1 = w.bbox_norm
                    self.assertTrue(0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, (name, w.text, w.bbox_norm))
                    self.assertTrue(w.ocr)
                    self.assertTrue(0.0 <= w.conf <= 1.0)
                    self.assertEqual(doc.word_conf[w.sha256_span_hash], w.conf)
                    self.assertEqual(len(w.sha256_span_hash), 64)
            self.assertGreater(n, 100)

    def test_arabic_words_recognised(self):
        doc = self.doc("nile_valley_ar_scanned_fy2024.pdf")
        txt = " ".join(w.text for p in doc.pages for w in p.words)
        for word in ("الإيرادات", "الأصول", "التدفقات"):
            self.assertIn(word, txt)

    def test_page_image_api_and_reocr(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-f", "2", "-l", "2", "-singlefile",
                            os.path.join(FIX, "red_sea_cement_en_scanned_fy2024.pdf"), os.path.join(td, "p")],
                           check=True, capture_output=True, shell=False)
            with open(os.path.join(td, "p.png"), "rb") as fh:
                out = fh.read()
        words = self.ocr.ocr_page_image(out, psm=6)
        nums = [w for w in words if re.fullmatch(r"\(?[\d,]+\.\d\)?", w.text)]
        self.assertGreater(len(nums), 10)
        agreed = 0
        for w in nums[:6]:
            text, conf, ok = self.ocr.reocr_number(out, w.bbox_norm, w.text, w.conf)
            self.assertTrue(0 <= conf <= 1)
            if ok:
                agreed += 1
                self.assertEqual(re.sub(r"\D", "", text), re.sub(r"\D", "", w.text))
        self.assertGreaterEqual(agreed, 4)

    def test_deskew_maps_bbox_back(self):
        # skewed scan: the 'Revenue' row label must sit at the same height as the native layout (+-1.5% of page)
        doc = self.doc("red_sea_cement_en_scanned_fy2024.pdf")
        ys = [w.bbox_norm[1] for w in doc.pages[0].words if w.text == "Revenue"]
        self.assertTrue(ys)
        self.assertLess(min(ys), 0.5)


class NoTesseractLeak(unittest.TestCase):
    def test_no_python_wrapper_imports(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "om", "intl", "ocr.py"), encoding="utf-8").read()
        self.assertNotIn("pytesseract", src.replace("never pytesseract", ""))
        self.assertNotIn("tesserocr", src.replace("tesserocr)", ""))
        self.assertNotIn("shell=True", src)


if __name__ == "__main__":
    unittest.main()
