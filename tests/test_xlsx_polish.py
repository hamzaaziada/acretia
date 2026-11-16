"""S4.7a: banker-grade polish features of the xlsx writer (named styles, charts, print setup, outline groups)."""
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

from om import xlsx

WS_ORDER = ["sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData", "sheetCalcPr", "sheetProtection",
            "protectedRanges", "scenarios", "autoFilter", "sortState", "dataConsolidate", "customSheetViews", "mergeCells",
            "phoneticPr", "conditionalFormatting", "dataValidations", "hyperlinks", "printOptions", "pageMargins",
            "pageSetup", "headerFooter", "rowBreaks", "colBreaks", "customProperties", "cellWatches", "ignoredErrors",
            "smartTags", "drawing", "legacyDrawing"]
STYLES_ORDER = ["numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs", "cellStyles", "dxfs"]


def local(tag):
    return tag.split("}")[-1]


def build():
    wb = xlsx.Workbook()
    sh = wb.sheet("Model", tab="0B2A4A")
    sh.set("A2", "Title", kind="title")
    sh.set("A3", "note", kind="note")
    for j, h in enumerate(["FY22", "FY23", "FY24"]):
        sh.set((5, 3 + j), h, kind="header")
    sh.set("A6", "Revenue", kind="text")
    sh.set("A7", "Cost", kind="text")
    for j, (rv, cs) in enumerate([(100.0, 60.0), (120.0, 70.0), (150.0, 80.0)]):
        sh.set((6, 3 + j), rv, kind="hist", fmt="num0")
        sh.set((7, 3 + j), cs, kind="input", fmt="num0")
    sh.set("C8", "=C6-C7", kind="calc", fmt="num0")
    sh.cells[(8, 3)].cached = 40.0
    sh.set("A9", "Total", kind="total")
    sh.set("C9", "=Other!A1", fmt="num0")
    sh.cells[(9, 3)].cached = 5.0
    sh.set("A10", "OK", kind="check")
    sh.width("A", 30)
    sh.group_cols("D", "E", level=1)
    sh.group_rows(6, 7, level=1)
    sh.print_setup(area="A1:E40", title_rows="5:5", title_cols="A:A", header="Acme & Co",
                   footer="Source: SEC filings & company reports")
    sh.chart("column", title="Revenue", series=[
        {"name": "Revenue", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$6:$E$6", "color": None},
        {"name": "Model!$A$7", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$7:$E$7", "invisible": True}],
        anchor=("B12", "H28"), y_format="num0", data_labels=True)
    sh.chart("bar", title="Floating", series=[
        {"name": "Cost", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$7:$E$7", "color": "7F7F7F"}], anchor=("B30", "H45"))
    sh.chart("line", title="Line", series=[
        {"name": "Revenue", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$6:$E$6"}], anchor=("J12", "P28"))
    sh.chart("stacked_column", title="Stack", series=[
        {"name": "A", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$6:$E$6"},
        {"name": "B", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$7:$E$7"}], anchor=("J30", "P45"), legend=False)
    sh.chart("stacked_bar", title="StackH", series=[
        {"name": "A", "cats": "'Model'!$C$5:$E$5", "vals": "'Model'!$C$6:$E$6"}], anchor=("R12", "X28"))
    o = wb.sheet("Other")
    o.set("A1", 5.0)
    return wb


class Polish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb = build()
        cls.data = cls.wb.to_bytes()
        cls.z = zipfile.ZipFile(io.BytesIO(cls.data))

    def test_all_parts_parse(self):
        for n in self.z.namelist():
            if n.endswith((".xml", ".rels", ".vml")):
                ET.fromstring(self.z.read(n))
        for part in ("xl/charts/chart1.xml", "xl/charts/chart5.xml", "xl/drawings/drawing1.xml", "xl/drawings/_rels/drawing1.xml.rels"):
            self.assertIn(part, self.z.namelist())
        ct = self.z.read("[Content_Types].xml").decode()
        self.assertIn("drawingml.chart+xml", ct)
        self.assertIn("drawing+xml", ct)

    def test_worksheet_child_order(self):
        for n in ("xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"):
            kids = [local(c.tag) for c in ET.fromstring(self.z.read(n))]
            idx = [WS_ORDER.index(k) for k in kids]
            self.assertEqual(idx, sorted(idx), kids)
        kids = [local(c.tag) for c in ET.fromstring(self.z.read("xl/worksheets/sheet1.xml"))]
        for k in ("dimension", "printOptions", "pageSetup", "headerFooter", "drawing"):
            self.assertIn(k, kids)

    def test_styles_order_and_named(self):
        st = ET.fromstring(self.z.read("xl/styles.xml"))
        kids = [local(c.tag) for c in st]
        self.assertEqual(kids, [k for k in STYLES_ORDER if k in kids])
        names = [c.get("name") for c in st.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}cellStyle")]
        self.assertEqual(names, ["Normal", "Input", "Historical", "Calculation", "Link", "Header", "Title", "Note", "Total", "Check"])
        self.assertEqual(set(xlsx.STYLE_NAMES.values()) - set(names), set())
        self.assertEqual(xlsx.STYLE_NAMES["hist"], "Historical")

    def test_workbook_defined_names_order(self):
        wbx = ET.fromstring(self.z.read("xl/workbook.xml"))
        kids = [local(c.tag) for c in wbx]
        self.assertLess(kids.index("sheets"), kids.index("definedNames"))
        self.assertLess(kids.index("definedNames"), kids.index("calcPr"))
        txt = self.z.read("xl/workbook.xml").decode()
        self.assertIn('name="_xlnm.Print_Area" localSheetId="0">Model!$A$1:$E$40', txt)
        self.assertIn("_xlnm.Print_Titles", txt)

    def test_header_footer_escaping(self):
        xml = self.z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn("Acme &amp;&amp; Co", xml)
        self.assertIn("Source: SEC filings &amp;&amp; company reports", xml)
        self.assertIn("&amp;RPage &amp;P of &amp;N", xml)

    def test_outline(self):
        xml = self.z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('outlineLevelCol="1"', xml)
        self.assertIn('outlineLevelRow="1"', xml)
        self.assertIn('<outlinePr summaryBelow="0" summaryRight="1"/>', xml)
        self.assertRegex(xml, r'<col min="4" max="4" width="[\d.]+" outlineLevel="1"/>')

    def test_openpyxl(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        wb = openpyxl.load_workbook(io.BytesIO(self.data))
        ws = wb["Model"]
        self.assertTrue({"Input", "Historical", "Calculation", "Link", "Header", "Title", "Note", "Total", "Check"} <= set(wb.named_styles))
        self.assertEqual(len(ws._charts), 5)
        self.assertEqual(ws.print_title_rows, "$5:$5")
        self.assertEqual(ws.print_title_cols, "$A:$A")
        self.assertEqual(ws.column_dimensions["D"].outlineLevel, 1)
        self.assertEqual(ws.row_dimensions[6].outlineLevel, 1)
        self.assertIn("Acme && Co", ws.oddHeader.center.text)
        self.assertIn("SEC filings && company", ws.oddFooter.left.text)
        self.assertIn("Page", ws.oddFooter.right.text)
        self.assertEqual(wb["Model"]["A9"].style, "Total")

    def test_read_roundtrip(self):
        b = xlsx.read(self.data)
        self.assertEqual(b.value("Model", "C6"), 100.0)
        self.assertEqual(b.cell("Model", "C6").color[-6:], "0000FF")
        self.assertEqual(b.cell("Model", "C8").formula.lstrip("="), "C6-C7")

    def test_chart_cache(self):
        c1 = self.z.read("xl/charts/chart1.xml").decode()
        self.assertIn("<c:numCache>", c1)
        self.assertIn("<c:strCache>", c1)
        self.assertIn('<c:legendEntry><c:idx val="1"/><c:delete val="1"/>', c1)
        self.assertIn("Arial", c1)
        self.assertNotIn("view3D", c1)

    def test_no_feature_sheet_unchanged(self):
        wb = xlsx.Workbook()
        s = wb.sheet("S")
        s.set("A1", 1.5)
        s.set("A2", "=A1*2", kind="calc")
        s.width("A", 12)
        z = zipfile.ZipFile(io.BytesIO(wb.to_bytes()))
        xml = z.read("xl/worksheets/sheet1.xml").decode()
        # intended diff vs. the pre-S4.7a writer: only the <dimension> element was added
        self.assertEqual(re.sub(r'<dimension ref="[^"]+"/>', "", xml).count("dimension"), 0)
        stripped = re.sub(r'<dimension ref="[^"]+"/>', "", xml)
        self.assertIn('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><sheetViews>', stripped)
        self.assertIn('<sheetFormatPr defaultRowHeight="13.2"/><cols><col min="1" max="1" width="12" customWidth="1"/></cols><sheetData>', stripped)
        self.assertIn('<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/><pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>', stripped)
        for bad in ("printOptions", "headerFooter", "<drawing", "outline"):
            self.assertNotIn(bad, stripped)
        self.assertNotIn("definedNames", z.read("xl/workbook.xml").decode())
        self.assertFalse([n for n in z.namelist() if "chart" in n or n.startswith("xl/drawings/drawing")])
        self.assertIn('<dimension ref="A1:A2"/>', xml)

    @unittest.skipUnless(shutil.which("soffice"), "soffice not installed")
    def test_libreoffice(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.xlsx")
            with open(src, "wb") as fh:
                fh.write(self.data)
            prof = "-env:UserInstallation=file://" + os.path.join(d, "profile")
            for fmt, out in (("pdf", "in.pdf"), ("xlsx:Calc MS Excel 2007 XML", "out/in.xlsx")):
                outdir = os.path.join(d, os.path.dirname(out) or "")
                os.makedirs(outdir, exist_ok=True)
                r = subprocess.run(["soffice", prof, "--headless", "--convert-to", fmt, "--outdir", outdir, src],
                                   capture_output=True, text=True, timeout=180)
                self.assertTrue(os.path.exists(os.path.join(d, out)), r.stdout + r.stderr)
            z = zipfile.ZipFile(os.path.join(d, "out", "in.xlsx"))
            self.assertTrue([n for n in z.namelist() if n.startswith("xl/charts/chart") and n.endswith(".xml")])


if __name__ == "__main__":
    unittest.main()
