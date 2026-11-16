import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from om import pdfdoc
from om.pdfdoc import PdfError, load
from om.pdfwrite import PDFWriter

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HAVE_PLUMBER = pdfdoc.pdfplumber is not None
HAVE_POPPLER = bool(shutil.which("pdftotext"))
HAVE_OCR = bool(shutil.which("tesseract") and shutil.which("pdftoppm"))

FONT = {  # 5x7 block letters
    "H": ["X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
    "E": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
    "L": ["X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"],
    "O": [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
    "T": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."],
}


def bitmap_text(s, scale=14, margin=90):
    cols = len(s) * 6 - 1
    pw, ph = cols * scale + 2 * margin, 7 * scale + 2 * margin
    px = bytearray(b"\xff" * (pw * ph))
    for i, ch in enumerate(s):
        for r, row in enumerate(FONT[ch]):
            for c, v in enumerate(row):
                if v == "X":
                    for dy in range(scale):
                        y = margin + r * scale + dy
                        x0 = margin + (i * 6 + c) * scale
                        px[y * pw + x0:y * pw + x0 + scale] = b"\x00" * scale
    return bytes(px), pw, ph


def sample_pdf():
    w = PDFWriter()
    w.page()
    w.text(72, 720, "Consolidated Statements of Income", 12, "Helvetica-Bold")
    w.text(72, 700, "Revenue", 9)
    w.text(300, 700, "1,234", 9)
    w.text(400, 700, "(1,234)", 9)
    w.text(72, 686, "Cost (net) of \\ sales", 9)
    for y in (710, 695, 680):
        w.line(72, y, 500, y)
    for x in (72, 290, 390, 500):
        w.line(x, 710, x, 680)
    w.rect(72, 500, 100, 40, fill=(0.9, 0.9, 0.9))
    w.page()
    w.text(72, 720, "Second page", 10)
    w.text(500, 20, "edge", 6)
    return w.to_bytes()


class TestPdfWriter(unittest.TestCase):
    def test_structure(self):
        b = sample_pdf()
        self.assertTrue(b.startswith(b"%PDF-1.4"))
        self.assertTrue(b.rstrip().endswith(b"%%EOF"))
        sx = int(re.search(rb"startxref\n(\d+)", b).group(1))
        self.assertEqual(b[sx:sx + 4], b"xref")
        # every xref offset points at "N 0 obj"
        lines = b[sx:].split(b"\n")
        n = int(lines[1].split()[1])
        for k in range(1, n):
            off = int(lines[2 + k].split()[0])
            self.assertTrue(b[off:].startswith(b"%d 0 obj" % k))

    def test_bad_args(self):
        with self.assertRaises(ValueError):
            PDFWriter().page().text(0, 0, "x", font="Comic")
        with self.assertRaises(ValueError):
            PDFWriter().page().image_gray(0, 0, 1, 1, b"\x00", 2, 2)


class _Base:
    backend = None

    def setUp(self):
        p = mock.patch.dict(os.environ, {"ACRETIA_PDF_BACKEND": self.backend})
        p.start()
        self.addCleanup(p.stop)

    def test_words_bounds_hashes(self):
        doc = load(sample_pdf())
        self.assertEqual(doc.backend, self.backend)
        self.assertEqual(len(doc.pages), 2)
        n = 0
        for p in doc.pages:
            self.assertTrue(p.chars_present)
            self.assertFalse(p.ocr)
            for sp in p.words + p.lines:
                n += 1
                x0, y0, x1, y1 = sp.bbox_norm
                self.assertTrue(0 <= x0 <= x1 <= 1 and 0 <= y0 <= y1 <= 1, sp)
                self.assertRegex(sp.sha256_span_hash, HEX64)
                self.assertEqual(sp.page, p.number)
        self.assertGreaterEqual(n, 20)

    def test_positions(self):
        doc = load(sample_pdf())
        w = {x.text: x for x in doc.pages[0].words}
        # "Revenue" 9pt at x=72, baseline y=700 on a 612x792 page
        x0, y0, x1, y1 = w["Revenue"].bbox_norm
        self.assertAlmostEqual(x0, 72 / 612, delta=0.01)
        self.assertAlmostEqual((y0 + y1) / 2, (792 - 700 - 2.5) / 792, delta=0.01)
        self.assertAlmostEqual(w["1,234"].bbox_norm[0], 300 / 612, delta=0.01)
        self.assertIn("(1,234)", w)
        self.assertIn("Consolidated", w)

    def test_lines_text_citations(self):
        doc = load(sample_pdf())
        texts = [l.text for l in doc.pages[0].lines]
        if self.backend == "pdfplumber":
            self.assertIn("Revenue 1,234 (1,234)", texts)
        else:  # poppler splits widely spaced columns into separate lines
            self.assertIn("Revenue", texts)
        self.assertIn("Cost (net) of \\ sales", texts)
        self.assertIn("Second page", doc.text())
        cits = doc.to_citations()
        self.assertEqual(len(cits), sum(len(p.lines) for p in doc.pages))
        for c in cits:
            c.validate()
            self.assertEqual(c.doc_id, doc.doc_id)
        self.assertRegex(doc.doc_id, HEX64)

    def test_deterministic(self):
        a, b = load(sample_pdf()), load(sample_pdf())
        self.assertEqual([w.sha256_span_hash for w in a.pages[0].words],
                         [w.sha256_span_hash for w in b.pages[0].words])

    def test_path_input(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a.pdf")
            with open(p, "wb") as fh:
                fh.write(sample_pdf())
            self.assertEqual(len(load(p).pages), 2)

    def test_bad_input(self):
        good = sample_pdf()
        for bad in (b"", b"hello world", b"<html>%PDF</html>" * 3, good[: len(good) // 2], b"%PDF-1.4\ngarbage\n%%EOF"):
            with self.assertRaises(PdfError, msg=bad[:20]):
                load(bad)
        with self.assertRaises(PdfError):
            load("/nonexistent/x.pdf")

    def test_limits(self):
        with self.assertRaises(PdfError):
            load(sample_pdf(), max_pages=1)
        with self.assertRaises(PdfError):
            load(sample_pdf(), max_bytes=100)

    def test_encrypted_rejected(self):
        enc = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R /Encrypt 5 0 R >>\n%%EOF"
        with self.assertRaises(PdfError):
            load(enc)


@unittest.skipUnless(HAVE_PLUMBER, "pdfplumber not installed")
class TestPlumber(_Base, unittest.TestCase):
    backend = "pdfplumber"

    def test_font_size_and_rulings(self):
        doc = load(sample_pdf())
        w = {x.text: x for x in doc.pages[0].words}
        self.assertEqual(w["Revenue"].font_size, 9.0)
        self.assertEqual(w["Consolidated"].font_size, 12.0)
        self.assertEqual(len(doc.pages[0].rulings), 7)
        self.assertEqual(len(doc.pages[0].rects), 1)
        for b in doc.pages[0].rulings + doc.pages[0].rects:
            self.assertTrue(0 <= b[0] <= b[2] <= 1 and 0 <= b[1] <= b[3] <= 1)


@unittest.skipUnless(HAVE_POPPLER, "poppler not installed")
class TestPoppler(_Base, unittest.TestCase):
    backend = "poppler"

    def test_no_rulings(self):
        doc = load(sample_pdf())
        self.assertEqual(doc.pages[0].rulings, [])


@unittest.skipUnless(HAVE_PLUMBER and HAVE_POPPLER, "both backends needed")
class TestAgreement(unittest.TestCase):
    def test_backends_agree(self):
        res, boxes = {}, {}
        for b in ("pdfplumber", "poppler"):
            with mock.patch.dict(os.environ, {"ACRETIA_PDF_BACKEND": b}):
                d = load(sample_pdf())
            res[b] = [[w.text for w in p.words] for p in d.pages]
            boxes[b] = {w.text: w.bbox_norm for w in d.pages[0].words}
        self.assertEqual(boxes["pdfplumber"].keys(), boxes["poppler"].keys())
        for t, a in boxes["pdfplumber"].items():
            for u, v in zip(a, boxes["poppler"][t]):
                self.assertAlmostEqual(u, v, delta=0.01, msg=t)
        for pa, pb in zip(res["pdfplumber"], res["poppler"]):
            self.assertEqual(sorted(pa), sorted(pb))

    def test_forced_missing_backend(self):
        with mock.patch.dict(os.environ, {"ACRETIA_PDF_BACKEND": "bogus"}):
            with self.assertRaises(PdfError):
                load(sample_pdf())


class TestOcr(unittest.TestCase):
    def pdf(self):
        px, pw, ph = bitmap_text("HELLO")
        w = PDFWriter().page()
        w.image_gray(72, 500, pw * 0.4, ph * 0.4, px, pw, ph)
        return w.to_bytes()

    @unittest.skipUnless(HAVE_OCR, "tesseract/pdftoppm not installed")
    def test_image_only_page_ocr(self):
        doc = load(self.pdf())
        p = doc.pages[0]
        self.assertFalse(p.chars_present)
        self.assertTrue(p.ocr, doc.warnings)
        self.assertTrue(p.words and all(w.ocr for w in p.words))
        self.assertIn("HELLO", doc.text().upper().replace(" ", ""))
        for sp in p.words + p.lines:
            x0, y0, x1, y1 = sp.bbox_norm
            self.assertTrue(0 <= x0 <= x1 <= 1 and 0 <= y0 <= y1 <= 1)
            self.assertRegex(sp.sha256_span_hash, HEX64)
        # image spans x 72..72+0.4*pw pt, near y=500..; word sits inside the image box
        self.assertGreater(p.words[0].bbox_norm[0], 72 / 612 - 0.01)

    def test_ocr_unavailable_warns(self):
        with mock.patch.object(pdfdoc.shutil, "which", lambda n: None if n in ("tesseract", "pdftoppm") else shutil.which(n)):
            doc = load(self.pdf())
        self.assertFalse(doc.pages[0].ocr)
        self.assertEqual(doc.pages[0].words, [])
        self.assertTrue(doc.warnings)

    def test_ocr_disabled(self):
        doc = load(self.pdf(), ocr=False)
        self.assertFalse(doc.pages[0].ocr)
        self.assertEqual(doc.warnings, [])


class TestHash(unittest.TestCase):
    def test_hash_and_clamp(self):
        h = pdfdoc.span_hash(1, "a", (0, 0, 0.5, 0.5))
        self.assertRegex(h, HEX64)
        self.assertEqual(h, pdfdoc.span_hash(1, "a", (0, 0, 0.5, 0.5)))
        self.assertNotEqual(h, pdfdoc.span_hash(2, "a", (0, 0, 0.5, 0.5)))
        self.assertEqual(pdfdoc.norm_bbox(-5, 900, 700, -3, 612, 792), (0.0, 0.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
