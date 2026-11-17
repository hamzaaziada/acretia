"""S4.1: om.validate_xlsx. Offline: the synthetic model3 workbook, a clean mini model, one negative fixture per check id."""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from om import model3, statements, validate_xlsx as vx  # noqa: E402
from om.formula import calculate_workbook  # noqa: E402
from om.xlsx import Workbook  # noqa: E402
from tests.test_model3 import synthetic_companyfacts  # noqa: E402


def mini(*, iterate=False, mutate=None) -> bytes:
    """Clean hand-built model: Inputs -> Model (with a live sensitivity grid) -> Checks. mutate(wb) edits before writing."""
    wb = Workbook(iterate=iterate)
    inp = wb.sheet("Inputs")
    inp.set("A2", "Inputs", kind="title")
    inp.set("A5", "USD in millions", kind="header")
    for r, (label, v, fmt) in enumerate((("Growth", 0.05, "pct"), ("Base revenue", 100.0, "num0"), ("Cost ratio", 0.6, "pct"),
                                         ("Growth step", 0.01, "pct"), ("Revenue step", 10.0, "num0"), ("Circ", 0, "int")), 7):
        inp.set((r, 1), label)
        inp.set((r, 3), v, kind="input", fmt=fmt)
    wb.define("Circ", "Inputs", "C12")
    m = wb.sheet("Model")
    m.set("A2", "Model", kind="title")
    m.set("A5", "USD in millions", kind="header")
    m.set("A7", "Revenue")
    m.set("C7", "=Inputs!$C$8", fmt="num0")
    for c in "DEF":
        m.set(f"{c}7", f"={chr(ord(c) - 1)}7*(1+Inputs!$C$7)", fmt="num0")
    m.set("A8", "Cost")
    for c in "CDEF":
        m.set(f"{c}8", f"={c}7*Inputs!$C$9", fmt="num0")
    m.set("A9", "Profit")
    for c in "CDEF":
        m.set(f"{c}9", f"={c}7-{c}8", fmt="num0")
    m.set("A11", "Sensitivity: profit (revenue down, growth across)", bold=True)
    for j, c in enumerate("DEF"):
        off = j - 1
        m.set(f"{c}12", f"=Inputs!$C$7{'+' if off >= 0 else '-'}{abs(off)}*Inputs!$C$10" if off else "=Inputs!$C$7", fmt="pct")
    for i, r in enumerate((13, 14, 15)):
        off = i - 1
        m.set(f"C{r}", f"=Inputs!$C$8{'+' if off >= 0 else '-'}{abs(off)}*Inputs!$C$11" if off else "=Inputs!$C$8", fmt="num0")
        for c in "DEF":
            m.set(f"{c}{r}", f"=$C{r}*(1+{c}$12)*(1-Inputs!$C$9)", fmt="num0")
    ck = wb.sheet("Checks")
    ck.set("A2", "Checks", kind="title")
    ck.set("A5", "USD in millions", kind="header")
    ck.set("A7", "Profit is revenue less cost")
    for c in "CDEF":
        ck.set(f"{c}7", f'=IF(ABS(Model!{c}9-(Model!{c}7-Model!{c}8))<0.5,"OK","ERROR")')
    ck.set("A8", "All checks")
    ck.set("C8", '=IF(COUNTIF(C7:F7,"ERROR")=0,"OK","ERROR")')
    if mutate:
        mutate(wb)
    calculate_workbook(wb)
    return wb.to_bytes()


def patch(data: bytes, fn, part="xl/worksheets/sheet2.xml") -> bytes:
    """Rewrite one XML part of the xlsx with fn(text) -> text (sheet2 is Model)."""
    src, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            b = src.read(n)
            z.writestr(n, fn(b.decode("utf-8")).encode("utf-8") if n == part else b)
    return out.getvalue()


def crit(res) -> set:
    return {f["id"] for f in res["findings"] if f["severity"] == "critical"}


def warn(res) -> set:
    return {f["id"] for f in res["findings"] if f["severity"] == "warning"}


class TestModel3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = statements.build(synthetic_companyfacts(), "TEST")
        cls.data, _ = model3.build(s)
        cls.res = vx.validate(cls.data)

    def test_findings_recorded(self):
        # Our own reference model must pass every check (no findings at all on the synthetic workbook). If a new check
        # ever flags it, keep the exact ids here and report the blocker (model3 is outside the S4.1 row).
        self.assertEqual(self.res["findings"], [])
        self.assertTrue(self.res["passed"])

    def test_stats(self):
        st = self.res["stats"]
        self.assertEqual(st["hardcoded_calc_cells"], 0)
        self.assertEqual(st["sensitivity_blocks"], 2)       # perpetuity growth + exit multiple grids on DCF
        self.assertGreater(st["circular_cells"], 0)         # default circ=1: interest loop behind the Circ breaker
        self.assertTrue(self.res["modelcheck"]["production_ready"])

    def test_circ_forbid_flags_loop(self):
        res = vx.validate(self.data, circ_policy="forbid")
        self.assertEqual(crit(res), {"circularity"})
        self.assertFalse(res["passed"])


class TestClean(unittest.TestCase):
    def test_clean_passes(self):
        res = vx.validate(mini())
        self.assertEqual(res["findings"], [])
        self.assertTrue(res["passed"])
        self.assertEqual(res["stats"]["sensitivity_blocks"], 1)
        self.assertEqual(res["stats"]["hardcoded_calc_cells"], 0)

    def test_bad_policy(self):
        with self.assertRaises(ValueError):
            vx.validate(mini(), circ_policy="nope")


class TestNegatives(unittest.TestCase):
    def check(self, data, expect: set, **kw):
        res = vx.validate(data, **kw)
        self.assertEqual(crit(res), expect, [f for f in res["findings"] if f["severity"] == "critical"])
        self.assertEqual(res["passed"], not expect)
        return res

    def test_modelcheck_constants(self):
        def mut(wb):
            wb["Model"].set("F8", "=F7*0.6", fmt="num0")
        res = self.check(mini(mutate=mut), {"modelcheck.constants"})
        f = next(x for x in res["findings"] if x["id"] == "modelcheck.constants")
        self.assertEqual((f["sheet"], f["cell"]), ("Model", "F8"))

    def test_modelcheck_checks_failing(self):
        def mut(wb):
            for c in "CDEF":
                wb["Checks"].set(f"{c}7", f'=IF(Model!{c}9>1000,"OK","ERROR")')
        self.check(mini(mutate=mut), {"modelcheck.checks"})

    def test_units_mixed_sheet(self):
        def mut(wb):
            wb["Model"].set("A6", "$ in thousands")
        self.check(mini(mutate=mut), {"units"})

    def test_units_cross_sheet_without_conversion(self):
        def mut(wb):
            wb["Inputs"].set("A5", "USD in thousands", kind="header")
        res = self.check(mini(mutate=mut), {"units"})
        self.assertTrue(all(f["cell"] for f in res["findings"] if f["id"] == "units"))

    def test_units_cross_sheet_with_conversion_ok(self):
        def mut(wb):
            wb["Inputs"].set("A5", "USD in thousands", kind="header")
            wb["Model"].set("C7", "=Inputs!$C$8/1000", fmt="num0")
            for r in (13, 14, 15):
                wb["Model"].set(f"C{r}", wb["Model"].cells[(r, 3)].value + "/1000", fmt="num0")
            for c in "DEF":
                wb["Model"].set(f"{c}12", wb["Model"].cells[(12, ord(c) - 64)].value, fmt="pct", color="008000")
            for c in "CDEF":
                wb["Model"].set(f"{c}8", f"={c}7*Inputs!$C$9", fmt="num0")
        res = vx.validate(mini(mutate=mut))
        self.assertEqual([f for f in res["findings"] if f["id"] == "units" and f["cell"] == "C7"], [])
        # sensitivity cells still link thousands into millions without a conversion, so units stays critical elsewhere
        self.assertIn("units", crit(res))

    def test_units_expected(self):
        self.check(mini(), set(), units="millions")
        self.check(mini(), {"units"}, units="thousands")

    def test_units_format_warning(self):
        def mut(wb):
            wb["Model"].set("C9", "=C7-C8", fmt='#,##0,')
        res = vx.validate(mini(mutate=mut))
        self.assertTrue(res["passed"])
        self.assertIn("units", warn(res))

    def test_sensitivity_array_formula(self):
        data = patch(mini(), lambda x: x.replace("<f>C7-C8</f>", '<f t="array" ref="C9">C7-C8</f>'))
        self.check(data, {"sensitivity.table"})

    def test_sensitivity_data_table(self):
        data = patch(mini(), lambda x: x.replace("<f>C7-C8</f>", '<f t="dataTable" ref="C9" dt2D="1" r1="C7" r2="C8"></f>'))
        self.assertIn("sensitivity.table", crit(vx.validate(data)))

    def test_sensitivity_table_function(self):
        def mut(wb):
            wb["Model"].set("C9", "=TABLE(C7,C8)", fmt="num0")
        self.assertIn("sensitivity.table", crit(vx.validate(mini(mutate=mut))))

    def test_sensitivity_live_typed_cell(self):
        def mut(wb):
            wb["Model"].set("E14", 123.0, kind="input")
        res = self.check(mini(mutate=mut), {"sensitivity.live"})
        f = next(x for x in res["findings"] if x["id"] == "sensitivity.live")
        self.assertEqual((f["sheet"], f["cell"]), ("Model", "E14"))

    def test_sensitivity_live_not_model(self):
        def mut(wb):
            wb["Model"].set("E14", "=$C14*(1+E$12)", fmt="num0")
        res = self.check(mini(mutate=mut), {"sensitivity.live"})
        self.assertIn("model cell", next(x for x in res["findings"] if x["id"] == "sensitivity.live")["message"])

    def test_sensitivity_live_not_header(self):
        def mut(wb):
            wb["Model"].set("E14", "=Inputs!$C$8*(1-Inputs!$C$9)", fmt="num0")
        res = self.check(mini(mutate=mut), {"sensitivity.live"})
        self.assertIn("header", next(x for x in res["findings"] if x["id"] == "sensitivity.live")["message"])

    def test_links_green(self):
        def mut(wb):
            wb["Model"].set("D7", "=C7*(1+Inputs!$C$7)", fmt="num0", color="000000")
        res = self.check(mini(mutate=mut), {"links.green"})
        self.assertEqual(res["findings"][0]["cell"], "D7")
        self.check(mini(mutate=mut), set(), require_green_links=False)

    def test_hardcode_calc(self):
        def mut(wb):
            wb["Model"].set("E8", 77.0, kind="input")
        res = self.check(mini(mutate=mut), {"hardcode.calc", "modelcheck.consistency"})  # a typed plug is flagged by both
        self.assertEqual(res["stats"]["hardcoded_calc_cells"], 1)

    def test_hardcode_calc_sourced_hist_allowed(self):
        def mut(wb):
            wb["Model"].set("C8", 60.0, kind="hist", comment="10-K FY2024, us-gaap:CostOfRevenue")
        res = vx.validate(mini(mutate=mut))
        self.assertEqual(res["stats"]["hardcoded_calc_cells"], 0)

    def test_circularity_without_breaker(self):
        def mut(wb):
            wb["Model"].set("C7", "=D7", fmt="num0")           # C7 <-> D7 loop, no switch
        for it in (True, False):
            res = vx.validate(mini(iterate=it, mutate=mut))
            self.assertIn("circularity", crit(res))

    def test_circularity_with_breaker_ok(self):
        def mut(wb):
            wb["Model"].set("C8", "=IF(Circ=1,C9*Inputs!$C$9,C7*Inputs!$C$9)", fmt="num0")
            wb["Model"].set("C9", "=C7-C8", fmt="num0")
        data = mini(iterate=True, mutate=mut)
        res = vx.validate(data)
        self.assertNotIn("circularity", crit(res))
        self.assertGreater(res["stats"]["circular_cells"], 0)
        self.assertIn("circularity", crit(vx.validate(data, circ_policy="forbid")))

    def test_merged(self):
        data = patch(mini(), lambda x: x.replace("</sheetData>", '</sheetData><mergeCells count="1"><mergeCell ref="C9:D9"/></mergeCells>'))
        res = self.check(data, {"noise.merged"})
        self.assertEqual(res["findings"][0]["sheet"], "Model")

    def test_merged_over_text_ok(self):
        data = patch(mini(), lambda x: x.replace("</sheetData>", '</sheetData><mergeCells count="1"><mergeCell ref="A2:B2"/></mergeCells>'))
        self.check(data, set())

    def test_volatile_is_warning(self):
        def mut(wb):
            wb["Model"].set("C9", "=C7-C8+0*RAND()", fmt="num0")
        res = vx.validate(mini(mutate=mut))
        self.assertIn("noise.volatile", warn(res))
        self.assertNotIn("noise.volatile", crit(res))

    def test_gridlines_is_warning(self):
        data = patch(mini(), lambda x: x.replace('showGridLines="0"', 'showGridLines="1"'))
        res = vx.validate(data)
        self.assertEqual(warn(res), {"noise.gridlines"})
        self.assertTrue(res["passed"])

    def test_errors(self):
        def fix(x):
            return re.sub(r'<c r="C9"( s="\d+")>\s*<f>C7-C8</f>.*?</c>', r'<c r="C9"\1 t="e"><f>C7-C8</f><v>#DIV/0!</v></c>', x, count=1)
        res = vx.validate(patch(mini(), fix))
        self.assertEqual(crit(res), {"errors", "modelcheck.calculates"})   # modelcheck reports the same cell too
        f = next(x for x in res["findings"] if x["id"] == "errors")
        self.assertEqual((f["sheet"], f["cell"]), ("Model", "C9"))


class TestS46Rules(unittest.TestCase):
    """S4.6a: typed numbers disguised as calculations, edge-cell pattern breaks, and require_sources (parity item 20)."""

    @staticmethod
    def calc_sheet(wb):
        c = wb.sheet("Calc")
        c.set("A2", "Calc", kind="title")
        c.set("A5", "USD in millions", kind="header")
        for r in (7, 8, 9, 10):
            c.set(f"C{r}", "=Inputs!$C$8", fmt="num0")
            c.set(f"D{r}", f"=$C{r}*(1+Inputs!$C$7)", fmt="num0")
        return c

    def test_typed_black_number_in_a_one_cell_row(self):
        def mut(wb):
            wb["Model"].set("C20", 123.0, kind="calc", fmt="num0")
        res = vx.validate(mini(mutate=mut))
        self.assertEqual(crit(res), {"hardcode.typed"})
        self.assertEqual([f["cell"] for f in res["findings"] if f["id"] == "hardcode.typed"], ["C20"])

    def test_typed_black_number_on_an_input_named_sheet(self):
        def mut(wb):
            wb["Inputs"].set("C20", 5.0, kind="calc")
        self.assertIn("hardcode.typed", crit(vx.validate(mini(mutate=mut))))

    def test_blue_input_on_input_sheet_is_fine(self):
        def mut(wb):
            wb["Inputs"].set("C20", 5.0, kind="input", fmt="num0")
        self.assertEqual(vx.validate(mini(mutate=mut))["findings"], [])

    def test_isolated_blue_plug_between_formulas(self):
        def mut(wb):
            c = self.calc_sheet(wb)
            c.set("C8", 42.0, kind="hist", fmt="num0")
            del c.cells[(8, 4)]
        res = vx.validate(mini(mutate=mut))
        self.assertIn(("hardcode.isolated", "C8"), {(f["id"], f["cell"]) for f in res["findings"]})
        self.assertFalse(res["passed"])

    def test_sourced_typed_number_between_formulas_is_allowed(self):
        def mut(wb):
            c = self.calc_sheet(wb)
            c.set("C8", 42.0, kind="hist", fmt="num0", comment="10-K FY24 p.51")
        self.assertNotIn("hardcode.isolated", {f["id"] for f in vx.validate(mini(mutate=mut))["findings"]})

    def test_last_column_pattern_break(self):
        # modelcheck's consistency grader needs a neighbour on both sides: an edge cell escapes it
        def mut(wb):
            wb["Model"].set("F8", "=F7", fmt="num0")
        res = vx.validate(mini(mutate=mut))
        self.assertIn(("consistency.columns", "F8"), {(f["id"], f["cell"]) for f in res["findings"]})
        self.assertNotIn("modelcheck.consistency", {f["id"] for f in res["findings"]})
        self.assertFalse(res["passed"])

    def test_first_column_may_differ(self):
        self.assertEqual(vx.validate(mini())["findings"], [])        # Model row 7: C is the base-year link, D..F roll forward

    def test_stacked_row_pattern_break(self):
        def mut(wb):
            c = self.calc_sheet(wb)
            c.set("D8", "=$C8*Inputs!$C$7", fmt="num0")
        res = vx.validate(mini(mutate=mut))
        self.assertIn(("consistency.rows", "D8"), {(f["id"], f["cell"]) for f in res["findings"]})

    def test_total_under_its_parts_is_not_flagged(self):
        def mut(wb):
            c = self.calc_sheet(wb)
            c.set("D11", "=SUM(D7:D10)", fmt="num0")
        self.assertEqual(vx.validate(mini(mutate=mut))["findings"], [])

    def test_require_sources(self):
        def mut(wb):
            wb["Model"].set("C20", 7.0, kind="hist", fmt="num0")
        data = mini(mutate=mut)
        self.assertEqual(vx.validate(data)["findings"], [])
        res = vx.validate(data, require_sources=True)
        self.assertEqual(crit(res), {"sources.missing"})
        self.assertEqual([f["cell"] for f in res["findings"]], ["C20"])
        self.assertFalse(res["passed"])

    def test_require_sources_accepts_comment_or_link(self):
        def mut(wb):
            wb["Model"].set("C20", 7.0, kind="hist", fmt="num0", comment="10-K FY24")
            wb["Model"].set("C21", 8.0, kind="hist", fmt="num0", link="https://www.sec.gov/Archives/edgar/data/1/x.htm")
        self.assertEqual(vx.validate(mini(mutate=mut), require_sources=True)["findings"], [])

    def test_require_sources_skips_input_sheets(self):
        self.assertEqual(vx.validate(mini(), require_sources=True)["findings"], [])

    def test_model3_passes_with_require_sources(self):
        s = statements.build(synthetic_companyfacts(), "TEST")
        data, _ = model3.build(s)
        self.assertEqual(vx.validate(data, require_sources=True)["findings"], [])


class TestCLI(unittest.TestCase):
    def run_cli(self, data, *args):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "m.xlsx")
            with open(p, "wb") as fh:
                fh.write(data)
            return subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "validate_xlsx.py"), p, *args], capture_output=True, text=True)

    def test_exit_0_clean(self):
        r = self.run_cli(mini())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)

    def test_exit_1_failed_and_json(self):
        def mut(wb):
            wb["Model"].set("F8", "=F7*0.6", fmt="num0")
        data = mini(mutate=mut)
        r = self.run_cli(data, "--json")
        self.assertEqual(r.returncode, 1)
        out = json.loads(r.stdout)
        self.assertFalse(out["passed"])
        self.assertIn("modelcheck.constants", {f["id"] for f in out["findings"]})
        self.assertIn("FAILED", self.run_cli(data).stdout)

    def test_flags(self):
        def mut(wb):
            wb["Model"].set("D7", "=C7*(1+Inputs!$C$7)", fmt="num0", color="000000")
        data = mini(mutate=mut)
        self.assertEqual(self.run_cli(data).returncode, 1)
        self.assertEqual(self.run_cli(data, "--no-green").returncode, 0)
        s = statements.build(synthetic_companyfacts(), "TEST")
        m3, _ = model3.build(s)
        self.assertEqual(self.run_cli(m3, "--circ", "forbid").returncode, 1)

    def test_unreadable(self):
        self.assertEqual(self.run_cli(b"not a zip").returncode, 2)


if __name__ == "__main__":
    unittest.main()
