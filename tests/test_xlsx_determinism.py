"""Deterministic workbook bytes, native logo images and values-only export (S4.fix1)."""
import io
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import zipfile
import zlib

import openpyxl

from om import formula as fx
from om import model3, xlsx
from om import statements as stm
from tests.test_model3 import synthetic_companyfacts
from tests.test_xlsx_polish import build as polish_build


def tiny_png(w=40, h=20, rgb=(200, 30, 30)) -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * w
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * h)) + chunk(b"IEND", b""))


def model3_workbook():
    s = stm.build(synthetic_companyfacts(), "SYN")
    wb, _ = model3.build_workbook(s, circ=0)
    return wb


def sheet_xml(data: bytes) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(data))
    return b"".join(z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/sheet"))


class Determinism(unittest.TestCase):
    def test_model3_bytes_identical_across_clock(self):
        a = model3_workbook().to_bytes()
        time.sleep(2.1)
        self.assertEqual(a, model3_workbook().to_bytes())

    def test_feature_workbook_bytes_identical_across_clock(self):
        a = polish_build().to_bytes()
        time.sleep(2.1)
        self.assertEqual(a, polish_build().to_bytes())

    def test_zip_metadata_fixed(self):
        z = zipfile.ZipFile(io.BytesIO(polish_build().to_bytes()))
        infos = z.infolist()
        self.assertEqual(infos[0].filename, "[Content_Types].xml")
        self.assertEqual(infos[1].filename, "_rels/.rels")
        self.assertEqual([i.filename for i in infos[2:]], sorted(i.filename for i in infos[2:]))
        for i in infos:
            self.assertEqual(i.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual((i.create_system, i.external_attr >> 16), (3, 0o600))


def with_image(chart=True):
    wb = xlsx.Workbook()
    sh = wb.sheet("Model")
    sh.set("A1", "Revenue", kind="text")
    for j, v in enumerate([1.0, 2.0, 3.0]):
        sh.set((2, 2 + j), v, fmt="num0")
        sh.set((1, 2 + j), f"Y{j}", kind="header")
    if chart:
        sh.chart("column", title="R", series=[{"name": "R", "cats": "'Model'!$B$1:$D$1", "vals": "'Model'!$B$2:$D$2"}],
                 anchor=("B5", "H20"))
    sh.image(tiny_png(), "F1", name="Logo", max_height_px=10)
    return wb


class Images(unittest.TestCase):
    def test_rejects_non_png(self):
        sh = xlsx.Workbook().sheet("A")
        for bad in (b"", b"GIF89a" + b"0" * 30, b"\xff\xd8\xff" + b"0" * 30, tiny_png()[:10], "text"):
            with self.assertRaises(ValueError):
                sh.image(bad, "A1")

    def test_parts_and_aspect(self):
        z = zipfile.ZipFile(io.BytesIO(with_image().to_bytes()))
        self.assertIn("xl/media/image1.png", z.namelist())
        self.assertIn('Extension="png"', z.read("[Content_Types].xml").decode())
        d = z.read("xl/drawings/drawing1.xml").decode()
        self.assertIn("<xdr:pic>", d)
        self.assertIn("graphicFrame", d)
        self.assertIn(f'cx="{20 * 9525}" cy="{10 * 9525}"', d)  # 40x20 scaled to height 10
        self.assertIn("image1.png", z.read("xl/drawings/_rels/drawing1.xml.rels").decode())

    def test_openpyxl_loads_chart_and_image(self):
        ws = openpyxl.load_workbook(io.BytesIO(with_image().to_bytes()))["Model"]
        self.assertEqual(len(ws._images), 1)
        self.assertEqual(len(ws._charts), 1)

    def test_box_anchor_fits_and_image_only_sheet(self):
        wb = xlsx.Workbook()
        wb.sheet("S").image(tiny_png(400, 100), ("A1", "B2"))
        ws = openpyxl.load_workbook(io.BytesIO(wb.to_bytes()))["S"]
        ext = ws._images[0].anchor.ext
        w, h = ext.width / 9525, ext.height / 9525
        self.assertAlmostEqual(w / h, 4.0, delta=0.1)
        self.assertLessEqual(h, 36)

    def test_deterministic_with_image(self):
        a = with_image().to_bytes()
        time.sleep(1.1)
        self.assertEqual(a, with_image().to_bytes())

    @unittest.skipUnless(shutil.which("soffice"), "LibreOffice not installed")
    def test_libreoffice_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.xlsx")
            with open(p, "wb") as f:
                f.write(with_image().to_bytes())
            r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", d, p],
                               capture_output=True, timeout=180, env=dict(os.environ, HOME=d))
            self.assertTrue(os.path.exists(os.path.join(d, "x.pdf")), r.stderr)


class ValuesOnly(unittest.TestCase):
    def check(self, data):
        out = xlsx.values_only(data)
        wf = openpyxl.load_workbook(io.BytesIO(out))
        for ws in wf:
            for row in ws.iter_rows():
                for c in row:
                    self.assertNotEqual(c.data_type, "f", (ws.title, c.coordinate))
        a = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        b = openpyxl.load_workbook(io.BytesIO(out), data_only=True)
        n = 0
        for ws in a:
            for row in ws.iter_rows():
                for c in row:
                    self.assertEqual(c.value, b[ws.title][c.coordinate].value, (ws.title, c.coordinate))
                    n += c.value is not None
        self.assertGreater(n, 0)
        self.assertNotIn(b"fullCalcOnLoad", zipfile.ZipFile(io.BytesIO(out)).read("xl/workbook.xml"))
        self.assertNotIn(b"<f>", sheet_xml(out))
        return out

    def test_model3(self):
        wb = model3_workbook()
        fx.calculate_workbook(wb)
        data = wb.to_bytes()
        self.assertIn(b"<f>", sheet_xml(data))
        out = self.check(data)
        self.assertEqual(xlsx.values_only(data), out)

    def test_all_types_and_extras(self):
        wb = with_image()
        sh = wb["Model"]
        sh.set("A3", "=B2+C2", fmt="num0")
        sh.cells[(3, 1)].cached = 3.0
        sh.set("A4", '="x"&A1', kind="calc")
        sh.cells[(4, 1)].cached = "xRevenue & <co>"
        sh.set("A5", "=B2>1", kind="calc")
        sh.cells[(5, 1)].cached = True
        sh.set("A6", "=1/0", kind="calc", comment="why", link="https://example.com")
        sh.cells[(6, 1)].cached = fx.Err("#DIV/0!")
        sh.set("A7", "=B2", kind="calc")  # no cached value
        sh.print_setup(area="A1:H20", header="H")
        out = self.check(wb.to_bytes())
        ws = openpyxl.load_workbook(io.BytesIO(out), data_only=True)["Model"]
        self.assertEqual(ws["A4"].value, "xRevenue & <co>")
        self.assertIs(ws["A5"].value, True)
        self.assertEqual(ws["A6"].value, "#DIV/0!")
        self.assertEqual(ws["A6"].comment.text, "why")
        self.assertEqual(len(ws._images), 1)
        self.assertEqual(len(ws._charts), 1)
        self.assertIsNone(xlsx.read(out).cell("Model", "A3").formula)
        self.assertEqual(xlsx.read(out).value("Model", "A3"), 3.0)

    def test_polish_workbook(self):
        self.check(polish_build().to_bytes())


if __name__ == "__main__":
    unittest.main()
