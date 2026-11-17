"""Offline tests for om/grid_export.py (S5.5b): banker-grade Excel export of the grid and of extracted tables."""
import csv
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from om import grid_export, xlsx  # noqa: E402
from om.grid import ExtractiveEngine, GridStore  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402
from test_grid import PDF_A, PDF_B  # noqa: E402
from test_grid_parity import pdf_table  # noqa: E402

try:
    import openpyxl
except Exception:  # pragma: no cover
    openpyxl = None

QS = [
    {"id": "revenue", "text": "What were total net sales?", "type": "currency", "label": "Net sales"},
    {"id": "staff", "text": "How many full-time equivalent employees did the company have?", "type": "number"},
    {"id": "auditor", "text": "Who is the auditor and what opinion was issued?"},
    {"id": "quantum", "text": "Describe the quantum flux capacitor."},
]


def png(w=40, h=12) -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x0b\x2a\x4a" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def pdf_neg_table() -> bytes:
    w = PDFWriter()
    w.page()
    w.text(72, 700, "Selected financial data for the period", 12)
    rows = [("Item", "2024", "2023"), ("Revenue", "1,234", "(1,234)"), ("Margin", "12.5%", "$5.50")]
    for i, r in enumerate(rows):
        for x, t in zip((72, 260, 380), r):
            w.text(x, 640 - 14 * i, t, 10)
    return w.to_bytes()


class Base(unittest.TestCase):
    def setUp(self):
        self.s = GridStore(":memory:", backend="sqlite", parser_backend="pdfdoc")
        self.a = self.s.add_document(PDF_A, "a.pdf", source_path="Data room/Financials/a.pdf")
        self.b = self.s.add_document(PDF_B, "b.pdf")
        self.t = self.s.add_document(pdf_table(), "tab.pdf")
        self.n = self.s.add_document(pdf_neg_table(), "neg.pdf")
        self.gid = self.s.create_grid("G1", [self.a, self.b], QS)
        self.s.run(self.gid, ExtractiveEngine())

    def tearDown(self):
        self.s.close()


class GridExport(Base):
    def book(self, **kw):
        data = grid_export.export_grid_xlsx(self.s, self.gid, **kw)
        return data, xlsx.read(data)

    def answered(self):
        return [c for c in self.s.cells(self.gid) if c["status"] in ("ok", "extracted")]

    def test_header_freeze_filter_print(self):
        data, bk = self.book()
        self.assertEqual(bk.order, ["Matrix", "Sources", "Run log"])
        h = grid_export.HEADER_ROW
        self.assertEqual([bk.value("Matrix", f"{c}{h}") for c in "ABCDEF"],
                         ["Document", "Document Source", "Net sales", "staff", "auditor", "quantum"])
        z = zipfile.ZipFile(io.BytesIO(data))
        sh = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn(f'ySplit="{h}"', sh)
        self.assertIn('xSplit="1"', sh)
        self.assertIn(f'<autoFilter ref="A{h}:F{h + 2}"/>', sh)
        self.assertIn('showGridLines="0"', sh)
        self.assertNotIn("mergeCell", sh)
        self.assertIn('orientation="landscape"', sh)
        self.assertIn("Source: Acretia grid G1", sh)
        self.assertIn("_FilterDatabase", z.read("xl/workbook.xml").decode())
        self.assertIn("Print_Titles", z.read("xl/workbook.xml").decode())
        self.assertEqual(bk.value("Matrix", f"B{h + 1}"), "Data room/Financials")

    def test_typed_numbers_and_notes_exact_quotes(self):
        _, bk = self.book()
        h = grid_export.HEADER_ROW
        rev = bk.cell("Matrix", f"C{h + 1}")
        self.assertIsInstance(rev.value, float)
        self.assertGreater(rev.value, 1000)
        by = {(c["doc_id"], c["question_id"]): c for c in self.s.cells(self.gid)}
        notes = bk.comments["Matrix"]
        n = 0
        for i, d in enumerate((self.a, self.b)):
            for j, q in enumerate(QS):
                c = by[(d, q["id"])]
                note = notes.get((h + 1 + i, 3 + j))
                if c["status"] in ("ok", "extracted"):
                    n += 1
                    self.assertIsNotNone(note, (d, q["id"]))
                    self.assertTrue(note.startswith(f"p.{c['page']}: “"), note)
                    quote = c["exact_quote"]
                    self.assertIn(quote if len(quote) <= 250 else quote[:240], note)
                    self.assertIn("[extractive, ", note)
        self.assertGreaterEqual(n, 4)

    def test_not_found_rendering(self):
        _, bk = self.book()
        h = grid_export.HEADER_ROW
        self.assertEqual(bk.value("Matrix", f"F{h + 1}"), "Not found")

    def test_unverified_hidden_unless_opted_in(self):
        self.s.db.run("UPDATE grid_cells SET status='unverified', raw_answer='SECRET-RAW-CLAIM', exact_quote='' "
                      "WHERE doc_id=? AND question_id='staff'", (self.a,))
        h = grid_export.HEADER_ROW
        data, bk = self.book()
        self.assertEqual(bk.value("Matrix", f"D{h + 1}"), "Needs review")
        self.assertNotIn(b"SECRET-RAW-CLAIM", b"".join(zipfile.ZipFile(io.BytesIO(data)).read(n) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()))
        data2, bk2 = self.book(include_unverified=True)
        self.assertEqual(bk2.value("Matrix", f"D{h + 1}"), "UNVERIFIED: SECRET-RAW-CLAIM")
        # the Sources sheet never lists an unverified cell
        rows = [r for r in range(2, 40) if bk2.value("Sources", f"A{r}")]
        self.assertEqual(len(rows), len(self.answered()) - 0)

    def test_skipped_and_error_rendering(self):
        self.s.db.run("UPDATE grid_cells SET status='skipped', answer='' WHERE doc_id=? AND question_id='auditor'", (self.a,))
        self.s.db.run("UPDATE grid_cells SET status='error' WHERE doc_id=? AND question_id='staff'", (self.b,))
        _, bk = self.book()
        h = grid_export.HEADER_ROW
        self.assertEqual(bk.value("Matrix", f"E{h + 1}"), "Skipped (condition)")
        self.assertEqual(bk.value("Matrix", f"D{h + 2}"), "Needs review")

    def test_sources_sheet_traceable(self):
        _, bk = self.book()
        ans = self.s.cells(self.gid)
        ans = [c for c in ans if c["status"] in ("ok", "extracted")]
        rows = [r for r in range(2, 100) if bk.value("Sources", f"A{r}")]
        self.assertEqual(len(rows), len(ans))
        quotes = sorted(bk.value("Sources", f"D{r}") for r in rows)
        self.assertEqual(quotes, sorted(c["exact_quote"] for c in ans))
        r0 = rows[0]
        for col in "EFGH":
            self.assertIsInstance(bk.value("Sources", f"{col}{r0}"), float)
        self.assertRegex(bk.value("Sources", f"I{r0}"), r"^[0-9a-f]{64}$")
        self.assertEqual(bk.value("Sources", f"J{r0}"), "extractive")

    def test_run_log(self):
        _, bk = self.book()
        self.assertEqual(bk.value("Run log", "A1"), "Run")
        self.assertTrue(str(bk.value("Run log", "A2")).startswith("run_"))
        self.assertEqual(bk.value("Run log", "B2"), "extractive")

    def test_conditional_format_fill_applied(self):
        self.s.set_format_rules(self.gid, [{"id": "big", "when": {"column": "staff", "op": "exists"},
                                            "style": {"fill": "#C6EFCE", "font": "#006100", "bold": True}, "apply_to": "staff"}])
        data, bk = self.book()
        h = grid_export.HEADER_ROW
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIn("C6EFCE", z.read("xl/styles.xml").decode())
        c = bk.cell("Matrix", f"D{h + 1}")
        self.assertEqual(c.color, "006100")
        self.assertTrue(c.bold)
        if openpyxl:
            wb = openpyxl.load_workbook(io.BytesIO(data))
            self.assertEqual(wb["Matrix"][f"D{h + 1}"].fill.fgColor.rgb, "FFC6EFCE")

    def test_logo_part_present(self):
        data, _ = self.book(logo_png=png(), title="Deal X matrix")
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertTrue(any(n.startswith("xl/media/") for n in names))
        data0, bk0 = self.book()
        self.assertFalse(any(n.startswith("xl/media/") for n in zipfile.ZipFile(io.BytesIO(data0)).namelist()))
        _, bk = self.book(logo_png=png(), title="Deal X matrix")
        self.assertEqual(bk.value("Matrix", "B1"), "Deal X matrix")

    def test_writes_path_and_openpyxl_readback(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.xlsx"
            data = grid_export.export_grid_xlsx(self.s, self.gid, p)
            self.assertEqual(p.read_bytes(), data)
            if openpyxl:
                wb = openpyxl.load_workbook(p)
                ws = wb["Matrix"]
                self.assertEqual(ws.freeze_panes, f"B{grid_export.HEADER_ROW + 1}")
                self.assertEqual(ws.auto_filter.ref, f"A{grid_export.HEADER_ROW}:F{grid_export.HEADER_ROW + 2}")
                cm = ws[f"C{grid_export.HEADER_ROW + 1}"].comment
                self.assertIsNotNone(cm)
                self.assertIn("p.", cm.text)

    def test_long_quote_truncated_only_in_note(self):
        long_q = "word " * 80
        self.assertTrue(grid_export._trunc(long_q.strip()).endswith("…"))
        self.assertEqual(len(grid_export._trunc(long_q.strip())), 250)
        self.assertEqual(grid_export._trunc("short quote"), "short quote")

    @unittest.skipUnless(shutil.which("soffice"), "soffice not installed")
    def test_opens_in_libreoffice(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.xlsx"
            grid_export.export_grid_xlsx(self.s, self.gid, p)
            subprocess.run(["soffice", "--headless", "--convert-to", "csv", "--outdir", d, str(p)], check=True,
                           capture_output=True, timeout=120)
            with open(Path(d) / "g.csv", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertTrue(any(r and r[0] == "Document" for r in rows))
            self.assertTrue(any("Not found" in r for r in rows))


class TablesExport(Base):
    def test_parse_number(self):
        P = grid_export.parse_number
        self.assertEqual(P("1,234")[0], 1234.0)
        self.assertEqual(P("(1,234)")[0], -1234.0)
        self.assertEqual(P("-5")[0], -5.0)
        self.assertEqual(P("$5.50")[0], 5.5)
        self.assertIn("$", P("$5.50")[1])
        self.assertAlmostEqual(P("12.5%")[0], 0.125)
        self.assertEqual(P("($3.2)")[0], -3.2)
        self.assertEqual(P("2024"), (2024.0, "0"))
        for bad in ("Revenue", "1,23", "12 apples", "", "1.2.3", "Q1"):
            self.assertIsNone(P(bad), bad)

    def test_tables_workbook(self):
        data = grid_export.export_tables_xlsx(self.s, [self.t, self.n])
        bk = xlsx.read(data)
        self.assertEqual(bk.order[0], "Index")
        tabs = bk.order[1:]
        self.assertEqual(len(tabs), len(set(t.lower() for t in tabs)))
        self.assertTrue(all(len(t) <= 31 for t in tabs))
        self.assertTrue(all(" p1 T1" in t or t.startswith("p1 T1") for t in tabs), tabs)
        neg = next(t for t in tabs if t.startswith("neg"))
        flat = {bk.cell(neg, f"{c}{r}").value for c in "ABC" for r in range(1, 5) if bk.cell(neg, f"{c}{r}")}
        self.assertIn(-1234.0, flat)
        self.assertIn(1234.0, flat)
        self.assertIn(0.125, flat)
        self.assertIn(5.5, flat)
        self.assertIn("Revenue", flat)
        self.assertEqual(bk.value("Index", "A1"), "Sheet")
        self.assertEqual(sum(1 for r in range(2, 10) if bk.value("Index", f"A{r}")), len(tabs))
        notes = bk.comments[neg]
        self.assertTrue(any("p.1" in n and "bbox" in n for n in notes.values()))

    def test_single_doc_names_and_grid_id(self):
        bk = xlsx.read(grid_export.export_tables_xlsx(self.s, self.t))
        self.assertEqual(bk.order, ["Index", "p1 T1"])
        self.assertEqual(bk.value("p1 T1", "B2"), 100.0)
        self.assertEqual(bk.value("p1 T1", "A1"), "Item")
        g2 = self.s.create_grid("G2", [self.t, self.n], [{"id": "x", "text": "What?"}])
        bk2 = xlsx.read(grid_export.export_tables_xlsx(self.s, g2))
        self.assertGreaterEqual(len(bk2.order), 3)

    def test_negative_format_shows_brackets(self):
        data = grid_export.export_tables_xlsx(self.s, [self.n])
        st = zipfile.ZipFile(io.BytesIO(data)).read("xl/styles.xml").decode()
        self.assertIn("#,##0_);(#,##0)", st)

    def test_csv(self):
        with tempfile.TemporaryDirectory() as d:
            files = grid_export.export_tables_csv(self.s, self.t, d)
            self.assertEqual(len(files), 1)
            with open(files[0], encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], ["Item", "Q1", "Q2", "Q3"])
            self.assertEqual(rows[1], ["Revenue", "100", "200", "300"])

    @unittest.skipUnless(shutil.which("soffice"), "soffice not installed")
    def test_tables_open_in_libreoffice(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.xlsx"
            grid_export.export_tables_xlsx(self.s, [self.t, self.n], p)
            subprocess.run(["soffice", "--headless", "--convert-to", "csv", "--outdir", d, str(p)], check=True,
                           capture_output=True, timeout=120)
            self.assertTrue((Path(d) / "t.csv").exists())


if __name__ == "__main__":
    unittest.main()
