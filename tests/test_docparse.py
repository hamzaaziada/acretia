import http.server
import json
import os
import re
import threading
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from om import docparse, parse_services, pdfdoc
from om.pdfwrite import PDFWriter

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HF = os.path.expanduser("~/.cache/huggingface/hub/models--docling-project--docling-layout-heron")


def make_pdf():
    w = PDFWriter()
    w.page()
    w.text(72, 760, "ACME Corp Annual Report", 8)
    w.text(72, 700, "Overview of results", 16, "Helvetica-Bold")
    w.text(72, 670, "Net revenue increased strongly during the", 10)
    w.text(72, 656, "fiscal year driven by services growth.", 10)
    w.text(72, 630, "The pharma-", 10)
    w.text(72, 616, "ceutical segment grew too.", 10)
    w.text(72, 590, "She said “profit rose” – a record.", 10)
    for r, y in enumerate((540, 526, 512)):
        for c, x in enumerate((72, 220, 360, 480)):
            w.text(x, y, f"R{r}C{c}", 9)
    w.text(72, 30, "Page 1 of 2 footer", 8)
    w.page()
    w.text(72, 720, "Second page unique zebra phrase", 10)
    w.text(72, 700, "Another line here", 10)
    w.page()
    for i in range(8):
        w.text(72, 700 - 14 * i, f"leftcol alpha{i} beta{i} gamma{i}", 10)
        w.text(330, 700 - 14 * i, f"rightcol delta{i} eps{i} zeta{i}", 10)
    return w.to_bytes()


PDF = make_pdf()
HAVE_DOCLING = parse_dl = docparse.docling_available()


class TestPdfdocBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = docparse.parse(PDF, backend="pdfdoc")

    def test_blocks_valid(self):
        self.assertEqual(self.doc.backend, "pdfdoc")
        self.assertEqual(len(self.doc.pages), 3)
        kinds = set()
        for p in self.doc.pages:
            self.assertTrue(p.blocks)
            for b in p.blocks:
                kinds.add(b.kind)
                x0, y0, x1, y1 = b.bbox_norm
                self.assertTrue(0 <= x0 <= x1 <= 1 and 0 <= y0 <= y1 <= 1)
                self.assertRegex(b.sha256_span_hash, HEX64)
                self.assertEqual(b.source, "pdfdoc")
        self.assertTrue({"header", "footer", "heading", "table"} <= kinds, kinds)

    def test_completeness_full(self):
        for p in self.doc.pages:
            self.assertGreaterEqual(p.completeness, 0.97)
        self.assertEqual(self.doc.page(1).number, 1)
        self.assertIn("\f", self.doc.text())

    def _chk(self, loc):
        self.assertIsNotNone(loc)
        self.assertTrue(0 <= loc.bbox_norm[0] <= loc.bbox_norm[2] <= 1)
        self.assertRegex(loc.sha256_span_hash, HEX64)
        self.assertEqual(loc.sha256_span_hash, pdfdoc.span_hash(loc.page, loc.text, loc.bbox_norm))

    def test_locate_single_line(self):
        loc = docparse.locate(self.doc, 1, "Overview of results")
        self._chk(loc)
        self.assertEqual(len(loc.rects), 1)

    def test_locate_multi_line(self):
        loc = docparse.locate(self.doc, 1, "increased strongly during the fiscal year driven")
        self._chk(loc)
        self.assertEqual(len(loc.rects), 2)
        self.assertGreater(loc.rects[1][1], loc.rects[0][1])

    def test_locate_hyphenated(self):
        loc = docparse.locate(self.doc, 1, "pharmaceutical segment grew")
        self._chk(loc)
        self.assertEqual(len(loc.rects), 2)
        self._chk(docparse.locate(self.doc, 1, "pharma- ceutical"))

    def test_locate_unicode_variants(self):
        self._chk(docparse.locate(self.doc, 1, 'She said "profit rose" - a record.'))
        self._chk(docparse.locate(self.doc, 1, "She said “profit rose” – a record."))

    def test_locate_case_sensitive_and_page_scoped(self):
        self.assertIsNone(docparse.locate(self.doc, 1, "overview of results"))
        self.assertIsNone(docparse.locate(self.doc, 1, "unique zebra phrase"))
        self._chk(docparse.locate(self.doc, 2, "unique zebra phrase"))
        hits = docparse.find_quote(self.doc, "unique zebra phrase")
        self.assertEqual([h.page for h in hits], [2])
        self.assertEqual(docparse.find_quote(self.doc, "unique zebra phrase", pages=[1]), [])
        self.assertIsNone(docparse.locate(self.doc, 1, ""))

    def test_locate_two_columns(self):
        loc = docparse.locate(self.doc, 3, "leftcol alpha0 beta0 gamma0 leftcol alpha1 beta1")
        self._chk(loc)
        self.assertLess(loc.bbox_norm[2], 0.5)
        self._chk(docparse.locate(self.doc, 3, "rightcol delta2 eps2 zeta2"))

    def test_round_trip(self):
        d2 = docparse.ParsedDoc.from_dict(json.loads(json.dumps(self.doc.to_dict())))
        self.assertEqual(d2.to_dict(), self.doc.to_dict())
        self._chk(docparse.locate(d2, 1, "Overview of results"))


class TestCompleteness(unittest.TestCase):
    def test_metric(self):
        self.assertEqual(docparse.completeness("", ""), 1.0)
        self.assertEqual(docparse.completeness("x", "  ... --"), 1.0)
        self.assertEqual(docparse.completeness("Revenue 1,234", "REVENUE (1234)"), 1.0)
        self.assertAlmostEqual(docparse.completeness("a b", "a b c d"), 0.5)
        self.assertAlmostEqual(docparse.completeness("a", "a a"), 0.5)

    def test_raw_page_texts(self):
        raws = docparse.raw_page_texts(PDF)
        self.assertEqual(len(raws), 3)
        self.assertIn("zebra", raws[1])

    def test_recovery_of_dropped_column(self):
        orig = docparse._pdfdoc_blocks

        def drop_right(pg):
            out = []
            for b in orig(pg):
                if pg.number == 3:
                    b.text = "\n".join(re.sub(r"rightcol.*", "", t).strip() for t in b.text.split("\n"))
                out.append(b)
            return out
        with mock.patch.object(docparse, "_pdfdoc_blocks", drop_right):
            d = docparse.parse(PDF, backend="pdfdoc", threshold=0.97)
        p = d.page(3)
        self.assertLess(p.completeness_before_recovery, 0.97)
        self.assertGreaterEqual(p.completeness, 0.97)
        self.assertTrue([b for b in p.blocks if b.kind == "recovered"])
        self.assertTrue(any(w.startswith("page 3: pdfdoc dropped") and "recovered" in w for w in d.warnings))
        self.assertFalse(any(w.startswith("page 1:") for w in d.warnings))
        for b in p.blocks:
            self.assertRegex(b.sha256_span_hash, HEX64)


class TestDoclingMapping(unittest.TestCase):
    def test_bbox_conversion_bottomleft(self):
        bb = NS(l=72.0, t=700.0, r=172.0, b=680.0, coord_origin="BOTTOMLEFT")
        x0, y0, x1, y1 = docparse._dl_bbox(bb, 612.0, 792.0)
        self.assertAlmostEqual(x0, 72 / 612)
        self.assertAlmostEqual(y0, 92 / 792)
        self.assertAlmostEqual(y1, 112 / 792)
        self.assertAlmostEqual(x1, 172 / 612)

    def test_bbox_topleft_and_clamp(self):
        bb = NS(l=-5.0, t=10.0, r=700.0, b=20.0, coord_origin=NS(name="TOPLEFT"))
        x0, y0, x1, y1 = docparse._dl_bbox(bb, 612.0, 792.0)
        self.assertEqual((x0, x1), (0.0, 1.0))
        self.assertAlmostEqual(y0, 10 / 792)

    def test_stub_document(self):
        def item(label, text, page, l, t, r, b):
            return NS(label=NS(value=label), text=text,
                      prov=[NS(page_no=page, bbox=NS(l=l, t=t, r=r, b=b, coord_origin="BOTTOMLEFT"))])
        table = NS(label=NS(value="table"), text="",
                   data=NS(table_cells=[NS(text="A"), NS(text="B")]),
                   prov=[NS(page_no=1, bbox=NS(l=10, t=300, r=100, b=250, coord_origin="BOTTOMLEFT"))])
        stub = NS(pages={1: NS(size=NS(width=612.0, height=792.0))},
                  iterate_items=lambda **kw: iter([
                      (item("section_header", "Title", 1, 72, 700, 172, 680), 0),
                      (item("page_footer", "foot", 1, 72, 40, 120, 30), 0), (table, 0),
                      (item("picture", "x", 1, 0, 0, 1, 1), 0)]))
        blocks = docparse._docling_blocks(stub)[1]
        self.assertEqual([b.kind for b in blocks], ["heading", "footer", "table"])
        self.assertEqual(blocks[2].text, "A B")
        self.assertAlmostEqual(blocks[0].bbox_norm[1], 92 / 792)
        self.assertEqual(blocks[0].source, "docling")

    def test_docling_failure_falls_back(self):
        with mock.patch.object(docparse, "_docling_run", side_effect=RuntimeError("boom")):
            d = docparse.parse(PDF, backend="docling")
        self.assertEqual(d.backend, "pdfdoc")
        self.assertTrue(any("docling failed" in w for w in d.warnings))

    def test_auto_without_docling(self):
        with mock.patch.object(docparse, "docling_available", return_value=False):
            self.assertEqual(docparse._resolve_backend(None), "pdfdoc")

    @unittest.skipUnless(HAVE_DOCLING and os.path.isdir(HF), "docling or cached weights unavailable")
    def test_real_docling_matches_pdfdoc_geometry(self):
        d = docparse.parse(PDF, backend="docling")
        self.assertEqual(d.backend, "docling")
        p = d.page(2)
        words = {w.text: w for w in p.lines[0].words}
        blk = next(b for b in p.blocks if "zebra" in b.text)
        zw = words["zebra"].bbox_norm
        cx, cy = (zw[0] + zw[2]) / 2, (zw[1] + zw[3]) / 2
        self.assertTrue(blk.bbox_norm[0] - 0.02 <= cx <= blk.bbox_norm[2] + 0.02)
        self.assertTrue(blk.bbox_norm[1] - 0.02 <= cy <= blk.bbox_norm[3] + 0.02)
        self.assertGreaterEqual(p.completeness, 0.97)
        self.assertIsNotNone(docparse.locate(d, 2, "unique zebra phrase"))


class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.server.got = (self.headers.get("Content-Type"), self.rfile.read(n))
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/x")
            self.end_headers()
            return
        if self.path == "/big":
            body = b"x" * 5000
        else:
            body = json.dumps(self.server.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestServices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        cls.srv.payload = {"pages": [
            {"number": 1, "width": 612, "height": 792, "blocks": [
                {"kind": "heading", "text": "Overview of results", "bbox": [72, 80, 300, 100]},
                {"kind": "weird", "text": "Net revenue", "bbox": [72, 110, 300, 125]}]},
            {"number": 2, "width": 612, "height": 792, "blocks": []}]}
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_parse_pages(self):
        pages = parse_services.ServiceParser("marker", self.base + "/p").parse_pages(PDF)
        self.assertEqual(self.srv.got, ("application/pdf", PDF))
        self.assertEqual(pages[0]["blocks"][1]["kind"], "other")

    def test_refuse_bad_scheme_and_redirect_and_size(self):
        with self.assertRaises(parse_services.ServiceError):
            parse_services.ServiceParser("marker", "file:///etc/passwd")
        with self.assertRaises(parse_services.ServiceError) as cm:
            parse_services.ServiceParser("marker", self.base + "/redir").parse_pages(PDF)
        self.assertIn("redirect", str(cm.exception))
        with self.assertRaises(parse_services.ServiceError) as cm:
            parse_services.ServiceParser("marker", self.base + "/big", max_bytes=1000).parse_pages(b"%PDF-")
        self.assertIn("exceeds", str(cm.exception))

    def test_env_required(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ACRETIA_MINERU_URL", None)
            with self.assertRaises(parse_services.ServiceError):
                parse_services.ServiceParser.from_env("mineru")

    def test_parse_with_marker_backend_applies_recovery(self):
        with mock.patch.dict(os.environ, {"ACRETIA_MARKER_URL": self.base + "/p"}):
            d = docparse.parse(PDF, backend="marker")
        self.assertEqual(d.backend, "marker")
        p1 = d.page(1)
        self.assertEqual(p1.blocks[0].source, "marker")
        self.assertAlmostEqual(p1.blocks[0].bbox_norm[1], 80 / 792)
        self.assertLess(p1.completeness_before_recovery, 0.97)
        self.assertTrue(any(b.kind == "recovered" for b in p1.blocks))
        self.assertTrue(any("page 1: marker dropped" in w for w in d.warnings))
        self.assertIsNotNone(docparse.locate(d, 2, "unique zebra phrase"))

    def test_unconfigured_service_falls_back(self):
        env = {k: v for k, v in os.environ.items() if k != "ACRETIA_MINERU_URL"}
        with mock.patch.dict(os.environ, env, clear=True):
            d = docparse.parse(PDF, backend="mineru")
        self.assertEqual(d.backend, "pdfdoc")
        self.assertTrue(any("mineru unavailable" in w for w in d.warnings))


if __name__ == "__main__":
    unittest.main()
