"""S4.7b: polish layer (om.polish) and the three-statement dashboard. Offline; facts mirror gate assertions H22-H26."""
import io
import re
import unittest
import zipfile

import openpyxl
from openpyxl.utils import range_boundaries

from om import bench, model3, modelcheck, polish, validate_xlsx
from om import statements as stm
from om.xlsx import Workbook
from tests.test_model3 import synthetic_companyfacts

STATEMENTS = ("IS", "BS", "CF")
PERIOD_SHEETS = ("Assumptions", "IS", "BS", "CF", "Schedules", "Debt", "Checks", "Filings")
REQUIRED_STYLES = {"Input", "Calculation", "Link", "Header", "Total"}


def _levels(ws) -> dict:
    out = {}
    for d in ws.column_dimensions.values():
        for c in range(d.min or 0, (d.max or 0) + 1):
            out[c] = d.outline_level
    return out


class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stm.build(synthetic_companyfacts(), "TEST")
        cls.data, cls.meta = model3.build(cls.s, circ=1)
        cls.data0, cls.meta0 = model3.build(cls.s, circ=0)
        cls.f = openpyxl.load_workbook(io.BytesIO(cls.data))
        cls.v = openpyxl.load_workbook(io.BytesIO(cls.data), data_only=True)
        cls.z = zipfile.ZipFile(io.BytesIO(cls.data))
        cls.H = len(cls.s.years)

    # ---- H22: dashboard first, >= 3 native charts bound to formula cells
    def test_cover_first_with_charts(self):
        self.assertEqual(self.f.sheetnames[0], "Cover")
        self.assertGreaterEqual(len(self.f["Cover"]._charts), 3)
        self.assertEqual(len(self.meta["charts"]), len(self.f["Cover"]._charts))
        parts = [n for n in self.z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n)]
        self.assertGreaterEqual(len(parts), 3)

    def test_chart_series_resolve_to_formula_cells(self):
        n = 0
        for part in [p for p in self.z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", p)]:
            xml = self.z.read(part).decode()
            sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
            self.assertTrue(sers, part)
            for ser in sers:
                self.assertTrue(re.search(r"<c:numRef><c:f>[^<]+</c:f>", ser), "values must be a numRef")
                for f in re.findall(r"<c:f>([^<]+)</c:f>", ser):
                    m = re.match(r"^'?([^'!]+)'?!(\$?[A-Z]+\$?\d+(?::\$?[A-Z]+\$?\d+)?)$", f)
                    self.assertIsNotNone(m, f)
                    self.assertIn(m.group(1), self.f.sheetnames)
                    ws = self.f[m.group(1)]
                    c1, r1, c2, r2 = range_boundaries(m.group(2).replace("$", ""))
                    if not re.search(rf"<c:numRef><c:f>{re.escape(f)}</c:f>", ser):
                        continue                                     # category labels are text; values must be formulas
                    for r in range(r1, r2 + 1):
                        for c in range(c1, c2 + 1):
                            cell = ws.cell(r, c)
                            self.assertEqual(cell.data_type, "f", f"{f} -> {cell.coordinate} is typed data")
                    n += 1
        self.assertGreaterEqual(n, 10)

    def test_bridge_ties_to_fcf(self):
        c, d = self.v["Cover"], self.v["DCF"]
        H = self.H
        col = 3 + H                                  # first forecast column on DCF / IS
        top = model3.COV["bridge"] + 1
        steps = [c.cell(top + i, 3).value for i in range(model3.BRIDGE_STEPS)]
        self.assertAlmostEqual(sum(steps[:-1]), steps[-1], places=6)
        self.assertAlmostEqual(steps[-1], d.cell(14, col).value, places=6)
        self.assertAlmostEqual(steps[0], self.v["IS"].cell(self.meta["rows"]["IS"]["ebitda"], col).value, places=6)
        self.assertEqual(self.v["Checks"].cell(self.meta["rows"]["Checks"]["master"], 3).value, "OK")
        row = self.meta["rows"]["Checks"]["c_bridge"]
        self.assertEqual(self.v["Checks"].cell(row, col).value, "OK")
        # waterfall helper columns are consistent: base + up/down/total reproduce the running level
        for i in range(1, model3.BRIDGE_STEPS - 1):
            base, up, down = (c.cell(top + i, k).value for k in (5, 6, 7))
            run = c.cell(top + i, 4).value
            prev = c.cell(top + i - 1, 4).value
            self.assertAlmostEqual(base + up + down, max(prev, run), places=6)

    def test_football_field_brackets_base(self):
        c, d = self.v["Cover"], self.v["DCF"]
        r = model3.COV["ff"] + 1
        for k, dcol in ((0, 3), (1, 4)):
            low, high = c.cell(r + k, 3).value, c.cell(r + k, 4).value
            base = d.cell(model3.DCF_PS_ROW, dcol).value
            self.assertLessEqual(low, base + 1e-9)
            self.assertLessEqual(base, high + 1e-9)
            self.assertAlmostEqual(c.cell(r + k, 5).value, high - low, places=9)
        row = self.meta["rows"]["Checks"]["c_ff"]
        self.assertEqual(self.v["Checks"].cell(row, 3 + self.H).value, "OK")

    # ---- H23: named styles
    def test_named_styles_present_and_used(self):
        names = set(self.f.named_styles)
        self.assertTrue(REQUIRED_STYLES <= names, names)
        used = {c.style for ws in self.f for row in ws.iter_rows() for c in row if c.value is not None}
        self.assertTrue(REQUIRED_STYLES <= used, used)

    # ---- H24: gridlines, freeze, print setup on every sheet
    def test_print_and_view_setup_every_sheet(self):
        for ws in self.f:
            with self.subTest(sheet=ws.title):
                self.assertFalse(ws.sheet_view.showGridLines)
                self.assertTrue(ws.print_title_rows, "print title rows")
                self.assertTrue(ws.oddFooter.right.text and "Page &P of &N" in ws.oddFooter.right.text)
                self.assertTrue(ws.oddFooter.left.text and ws.oddFooter.center.text)
                self.assertIn("confidential", ws.oddHeader.right.text)
                self.assertEqual(ws.page_setup.orientation, "landscape")
                self.assertEqual(ws.page_setup.fitToWidth, 1)
        for name in PERIOD_SHEETS + ("DCF",):
            ws = self.f[name]
            self.assertEqual(ws.print_title_rows, "$5:$6")
            self.assertEqual(ws.print_title_cols, "$A:$B")
            self.assertIsNotNone(ws.freeze_panes)

    # ---- H25: outline levels on hist / proj columns
    def test_hist_and_proj_columns_grouped(self):
        H = self.H
        for name in PERIOD_SHEETS:
            lv = _levels(self.f[name])
            for c in range(3, 3 + H + model3.F):
                self.assertEqual(lv.get(c), 1, f"{name} column {c}")
            self.assertFalse(lv.get(1)) and self.assertFalse(lv.get(2))
        for name in STATEMENTS:
            for d in self.f[name].column_dimensions.values():
                self.assertFalse(d.hidden)

    # ---- H26: merges, number formats, fonts
    def test_no_merges_numbers_formatted_house_font(self):
        for ws in self.f:
            self.assertEqual(len(ws.merged_cells.ranges), 0, ws.title)
        for ws in self.f:
            wv = self.v[ws.title]
            for row in ws.iter_rows():
                for c in row:
                    if c.value is None:
                        continue
                    self.assertEqual(c.font.name, "Arial", f"{ws.title}!{c.coordinate}")
                    val = wv[c.coordinate].value
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        self.assertNotEqual(c.number_format, "General", f"{ws.title}!{c.coordinate} = {val}")

    # ---- engine acceptance
    def test_grade_validate_agree(self):
        g = modelcheck.grade(self.data)
        self.assertTrue(g["production_ready"])
        self.assertGreaterEqual(g["score"], 100.0 - 1e-9 if g["score"] >= 100 else 95)
        v = validate_xlsx.validate(self.data)
        self.assertTrue(v["passed"], v["findings"][:3])
        self.assertEqual(v["findings"], [])
        self.assertTrue(self.meta["converged"])

    def test_libreoffice_agrees_without_circularity(self):
        a = bench.agree(self.data0)
        if a is None:
            self.skipTest("soffice not available")
        self.assertEqual(a["mismatches"], 0, a.get("examples"))


class Helpers(unittest.TestCase):
    def _wb(self):
        wb = Workbook()
        sh = wb.sheet("Dash")
        mdl = wb.sheet("Model")
        for i, v in enumerate((100.0, -30.0, -20.0)):
            mdl.set((i + 1, 1), v, kind="hist")
        mdl.set("A4", 5.0, kind="hist")
        mdl.set("A5", 9.0, kind="hist")
        return wb, sh

    def test_waterfall_and_football_formulas_only(self):
        wb, sh = self._wb()
        w = polish.waterfall(sh, top_left=(10, 2), steps=[("Start", "=Model!A1"), ("Costs", "=Model!A2"), ("Tax", "=Model!A3"),
                                                          ("End", "=Model!A1+Model!A2+Model!A3")], title="Bridge", anchor=("B2", "F8"))
        f = polish.football_field(sh, top_left=(20, 2), rows=[("Range", "=Model!A4", "=Model!A5")], title="FF", anchor=("H2", "M8"),
                                  marker="=Model!A4")
        polish.trend(sh, title="T", cats="Dash!$C$10:$F$10", series=[("Dash!$B$11", "Dash!$C$11:$F$11")], anchor=("B30", "F40"))
        self.assertEqual((w["first_row"], w["last_row"]), (11, 14))
        self.assertEqual(f["marker_row"], 22)
        for (r, c), cell in sh.cells.items():
            if c >= 3 and r > 10 and r != 20:
                self.assertTrue(cell.value in ("", None) or (isinstance(cell.value, str) and cell.value.startswith("=")),
                                f"typed value at {r},{c}")
        self.assertEqual(len(sh.charts), 3)
        self.assertTrue(sh.charts[0]["series"][0]["invisible"] and sh.charts[1]["series"][0]["invisible"])
        with self.assertRaises(ValueError):
            polish.waterfall(sh, top_left=(40, 2), steps=[("a", "=1"), ("b", "=1")], title="x", anchor=("B2", "C3"))

    def test_finish_defaults_formats_and_groups(self):
        wb, sh = self._wb()
        sh.set("A1", 5.5)
        sh.set("A2", 2024)
        sh.set("A3", "=A1*A1")
        wb.sheet("IS").set("C5", "FY24")
        polish.finish(wb, model_name="Demo", source="Source: test", period_sheets={"IS": {"hist": ("C", "D"), "proj": (5, 6)}})
        self.assertEqual(sh.cells[(1, 1)].style.fmt, "num2")
        self.assertEqual(sh.cells[(2, 1)].style.fmt, "int")
        self.assertIsNotNone(wb["IS"].freeze)
        self.assertEqual(sorted(wb["IS"].col_groups), [3, 4, 5, 6])
        self.assertEqual(sh.print_cfg["footer"], ("Source: test", "Demo", ""))
        self.assertEqual(sh.print_cfg["fit_width"], 1)


if __name__ == "__main__":
    unittest.main()
