"""S4.7c: the LBO, merger and comps workbooks carry a banker-grade Cover dashboard and the house finish.
Reads the bytes with openpyxl (independent of om.xlsx) and the raw chart XML. Hermetic: synthetic companies, no network."""
import re
import shutil
import unittest
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

import openpyxl

from om import bench, comps, lbo, merger, modelcheck, recalc, validate_xlsx
from om import statements as stm
from tests.test_comps import fixture as comps_fixture
from tests.test_lbo import MARKET as LBO_MARKET
from tests.test_merger import ACQ_MKT, TGT_MKT, scaled
from tests.test_model3 import synthetic_companyfacts

NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart", "r": "http://schemas.openxmlformats.org/package/2006/relationships",
      "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NAMED = {"Input", "Calculation", "Link", "Header", "Total"}


def build_lbo():
    return lbo.build(stm.build(synthetic_companyfacts(), "TEST"), market=LBO_MARKET)


def build_merger(assumptions=None):
    cf = synthetic_companyfacts()
    return merger.build(stm.build(cf, "ACQ"), stm.build(scaled(cf, 0.3), "TGT"), acq_market=ACQ_MKT, tgt_market=TGT_MKT, assumptions=assumptions)


def build_comps():
    tgt, peers, markets = comps_fixture()
    return comps.build(tgt, peers, markets=markets, as_of="2025-03-03")


def cover_chart_parts(x: bytes) -> list[str]:
    """Chart part names drawn on the first sheet in tab order (raw OOXML walk)."""
    z = zipfile.ZipFile(BytesIO(x))
    wbx = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    first = wbx.find("m:sheets", NS)[0]
    target = rels[first.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")].lstrip("/")
    sheet_path = target if target.startswith("xl/") else "xl/" + target
    srels = sheet_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
    drawings = [r.get("Target") for r in ET.fromstring(z.read(srels)) if r.get("Type", "").endswith("/drawing")]
    out = []
    for d in drawings:
        dpath = "xl/" + d.replace("../", "")
        drels = dpath.replace("drawings/", "drawings/_rels/") + ".rels"
        out += ["xl/" + r.get("Target").replace("../", "") for r in ET.fromstring(z.read(drels)) if r.get("Type", "").endswith("/chart")]
    return out


def val_refs(x: bytes) -> list[str]:
    z = zipfile.ZipFile(BytesIO(x))
    refs = []
    for part in cover_chart_parts(x):
        root = ET.fromstring(z.read(part))
        refs += [f.text for f in root.findall(".//c:val/c:numRef/c:f", NS)]
    return refs


def cells_in(ref: str):
    m = re.match(r"^'?(.+?)'?!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$", ref)
    sheet, c1, r1, c2, r2 = m.groups()
    c2, r2 = c2 or c1, r2 or r1
    return sheet, f"{c1}{r1}:{c2}{r2}"


class Common:
    """Shared assertions; subclasses set build(), and the sheets whose columns must carry outline levels."""
    OUTLINE_SHEETS: tuple = ()

    @classmethod
    def setUpClass(cls):
        cls.x, cls.meta = cls.make()
        cls.f = openpyxl.load_workbook(BytesIO(cls.x))
        cls.v = openpyxl.load_workbook(BytesIO(cls.x), data_only=True)

    def test_cover_first_with_three_charts(self):
        self.assertEqual(self.f.sheetnames[0], "Cover")
        parts = cover_chart_parts(self.x)
        self.assertGreaterEqual(len(parts), 3)
        self.assertGreaterEqual(len(self.meta["charts"]), 3)
        self.assertEqual(len(parts), len(self.meta["charts"]))

    def test_every_chart_value_series_is_formula_cells(self):
        refs = val_refs(self.x)
        self.assertGreaterEqual(len(refs), 5)
        for r in refs:
            sheet, rng = cells_in(r)
            for row in self.f[sheet][rng]:
                for c in row:
                    self.assertTrue(isinstance(c.value, str) and c.value.startswith("="), f"{r}: {c.coordinate} is {c.value!r}, not a formula")

    def test_named_styles_present_and_used(self):
        names = {s.name for s in self.f._named_styles}
        self.assertTrue(NAMED <= names, NAMED - names)
        used = {c.style for ws in self.f for row in ws.iter_rows() for c in row if c.value is not None}
        self.assertTrue(NAMED <= used, NAMED - used)

    def test_print_setup_on_every_sheet(self):
        for ws in self.f:
            footer = " ".join(filter(None, (ws.oddFooter.left.text, ws.oddFooter.center.text, ws.oddFooter.right.text)))
            self.assertIn("Page &P of &N", footer, ws.title)
            self.assertTrue(ws.print_title_rows, ws.title)
            self.assertTrue(ws.page_setup.orientation == "landscape" and ws.sheet_properties.pageSetUpPr.fitToPage, ws.title)
            self.assertEqual(ws.page_setup.fitToWidth, 1, ws.title)

    def test_outline_levels_on_period_sheets(self):
        for name in self.OUTLINE_SHEETS:
            ws = self.f[name]
            self.assertTrue(any((d.outlineLevel or 0) >= 1 for d in ws.column_dimensions.values()), name)

    def test_gridlines_off_and_no_merged_cells(self):
        for ws in self.f:
            self.assertFalse(ws.sheet_view.showGridLines, ws.title)
            self.assertEqual(list(ws.merged_cells.ranges), [], ws.title)

    def test_numeric_cells_are_formatted(self):
        for ws in self.v:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                        self.assertNotEqual(c.number_format, "General", f"{ws.title}!{c.coordinate}")

    def test_house_gates(self):
        g = modelcheck.grade(self.x)
        self.assertTrue(g["production_ready"], [r for r in g["graders"] if r["passed"] is False])
        self.assertEqual(g["score"], 100)
        rep = validate_xlsx.validate(self.x)
        self.assertTrue(rep["passed"], rep["findings"])
        self.assertEqual(len(rep["findings"]), 0)
        self.assertTrue(self.meta["converged"])

    def test_libreoffice_recalculation_agrees(self):
        if not (shutil.which("soffice") or shutil.which("libreoffice")):
            self.skipTest("LibreOffice (soffice) not installed")
        x = self.make_circ_off()
        res = bench.agree(x)
        if res is None:
            self.skipTest("LibreOffice recalculation unavailable")
        self.assertEqual(res["mismatches"], 0, res["examples"])
        cmp = recalc.compare(x)
        self.assertTrue(cmp["agree"], cmp.get("divergences", cmp)[:5] if isinstance(cmp.get("divergences"), list) else cmp)

    @classmethod
    def make_circ_off(cls):
        return cls.x

    def row_values(self, sheet, row, cols):
        return [self.v[sheet][f"{c}{row}"].value for c in cols]


class LboDashboard(Common, unittest.TestCase):
    OUTLINE_SHEETS = ("Operations", "Debt", "Assumptions")

    @classmethod
    def make(cls):
        return build_lbo()

    @classmethod
    def make_circ_off(cls):
        return lbo.build(stm.build(synthetic_companyfacts(), "TEST"), market=LBO_MARKET, circ=0)[0]

    def test_master_ok_and_dashboard_checks(self):
        R = self.meta["rows"]["Checks"]
        self.assertEqual(self.v["Checks"][f"C{R['master']}"].value, "OK")
        for k in ("c_bridge", "c_debtchart", "c_ff"):
            self.assertEqual(self.v["Checks"][f"C{R[k]}"].value, "OK", k)
        self.assertEqual(self.v["Cover"]["C10"].value, "OK")

    def test_returns_bridge_ties_to_returns_sheet(self):
        b0 = lbo.COV["bridge"]
        vals = [self.v["Cover"][f"C{b0 + 1 + i}"].value for i in range(lbo.BRIDGE_STEPS)]
        self.assertAlmostEqual(sum(vals[:-1]), vals[-1], places=6)
        R = self.meta["rows"]["Returns"]
        self.assertAlmostEqual(vals[0], self.v["Returns"][f"C{R['eq_in']}"].value, places=6)
        self.assertAlmostEqual(vals[-1], self.v["Returns"][f"C{R['eq_out']}"].value, places=6)
        for key, got in zip(("a_ebitda", "a_mult", "a_delev", "a_fees"), vals[1:-1]):
            self.assertAlmostEqual(got, self.v["Returns"][f"C{R[key]}"].value, places=6)

    def test_irr_football_field_contains_base(self):
        R = self.meta["rows"]["Returns"]
        base = self.v["Returns"][f"C{R['irr']}"].value
        f0 = lbo.COV["ff"]
        for i in range(1, lbo.FF_ROWS + 1):
            lo, hi, spread = self.row_values("Cover", f0 + i, "CDE")
            self.assertLessEqual(lo, base + 1e-9, i)
            self.assertGreaterEqual(hi, base - 1e-9, i)
            self.assertAlmostEqual(hi - lo, spread, places=9)
        self.assertAlmostEqual(self.v["Cover"][f"C{f0 + lbo.FF_ROWS + 1}"].value, base, places=9)

    def test_debt_chart_stacks_to_total_debt(self):
        t0 = lbo.COV["trend"]
        DR = self.meta["rows"]["Debt"]
        for col in "CDEFGH":
            parts = sum(self.v["Cover"][f"{col}{t0 + k}"].value for k in (4, 5, 6, 7))
            self.assertAlmostEqual(parts, self.v["Debt"][f"{col}{DR['debt']}"].value, places=6)

    def test_chart_kinds(self):
        kinds = [c["kind"] for c in self.meta["charts"]]
        self.assertIn("stacked_column", kinds)
        self.assertIn("stacked_bar", kinds)
        self.assertGreaterEqual(kinds.count("stacked_column"), 2)         # tranche chart and the waterfall


class MergerDashboard(Common, unittest.TestCase):
    OUTLINE_SHEETS = ("Pro forma", "Breakeven")

    @classmethod
    def make(cls):
        return build_merger()

    def test_master_ok_and_dashboard_checks(self):
        R = self.meta["rows"]["Checks"]
        self.assertEqual(self.v["Checks"][f"C{R['master']}"].value, "OK")
        for r in range(R["first"], R["last"] + 1):
            self.assertEqual(self.v["Checks"][f"C{r}"].value, "OK", self.v["Checks"][f"A{r}"].value)
        self.assertEqual(self.v["Cover"][f"C{self.meta['rows']['Cover']['master']}"].value, "OK")

    def test_purchase_price_bridge_ties(self):
        b0 = merger.COV["bridge"]
        vals = [self.v["Cover"][f"C{b0 + 1 + i}"].value for i in range(merger.BRIDGE_STEPS)]
        self.assertAlmostEqual(sum(vals[:-1]), vals[-1], places=6)
        PR = self.meta["rows"]["Purchase price"]
        self.assertAlmostEqual(vals[-1], self.v["Purchase price"][f"C{PR['ev']}"].value, places=6)
        self.assertAlmostEqual(vals[0], self.v["Purchase price"][f"C{PR['equity']}"].value, places=6)

    def test_accretion_table_matches_pro_forma(self):
        a0 = merger.COV["adt"]
        PF = self.meta["rows"]["Pro forma"]
        for k, col in enumerate("DEF"):
            cov_col = "CDE"[k]
            self.assertAlmostEqual(self.v["Cover"][f"{cov_col}{a0 + 4}"].value, self.v["Pro forma"][f"{col}{PF['acc_p']}"].value, places=9)
            self.assertAlmostEqual(self.v["Cover"][f"{cov_col}{a0 + 2}"].value, self.v["Pro forma"][f"{col}{PF['pf_eps']}"].value, places=9)
            self.assertAlmostEqual(self.v["Cover"][f"{cov_col}{a0 + 1}"].value, self.v["Pro forma"][f"{col}{PF['sa_eps']}"].value, places=9)

    def test_all_stock_deal_reads_master_ok_with_defaults(self):
        for ass in ({"pct_stock": 1.0}, {"pct_stock": 1.0, "pct_cash": 0.0}, {"pct_cash": 0.0}):
            x, meta = build_merger(ass)
            v = openpyxl.load_workbook(BytesIO(x), data_only=True)
            R = meta["rows"]["Checks"]
            bad = [v["Checks"][f"A{r}"].value for r in range(R["first"], R["last"] + 1) if v["Checks"][f"C{r}"].value != "OK"]
            self.assertEqual(bad, [], ass)
            self.assertEqual(v["Checks"][f"C{R['master']}"].value, "OK", ass)
            SU = meta["rows"]["Sources & Uses"]
            self.assertGreaterEqual(v["Sources & Uses"][f"C{SU['s_debt']}"].value, 0)
            self.assertLessEqual(v["Sources & Uses"][f"C{SU['s_cash']}"].value,
                                 v["Sources & Uses"][f"C{SU['cash_cons']}"].value + v["Sources & Uses"][f"C{SU['u_fees']}"].value + 1e-9)

    def test_default_cash_used_is_capped_at_cash_need(self):
        x, meta = build_merger({"pct_stock": 1.0})
        self.assertEqual(meta["defaults"]["pct_cash"], 0.0)
        v = openpyxl.load_workbook(BytesIO(x), data_only=True)
        SU = meta["rows"]["Sources & Uses"]
        self.assertLessEqual(meta["defaults"]["cash_used"], v["Sources & Uses"][f"C{SU['u_fees']}"].value)
        # an explicit user value is respected, not re-capped
        _, meta2 = build_merger({"pct_stock": 1.0, "cash_used": 5.0})
        self.assertEqual(meta2["defaults"]["cash_used"], 5.0)


class CompsDashboard(Common, unittest.TestCase):
    OUTLINE_SHEETS = ("Inputs", "Calendarisation", "Equity value")

    @classmethod
    def make(cls):
        return build_comps()

    def test_master_ok(self):
        R = self.meta["rows"]["Checks"]
        self.assertEqual(self.v["Checks"][f"C{R['master']}"].value, "OK")
        for k in ("c_cov", "c_ffpx"):
            self.assertEqual(self.v["Checks"][f"C{R[k]}"].value, "OK", k)
        self.assertEqual(self.v["Cover"]["C10"].value, "OK")

    def test_football_field_chart_is_bound_to_the_valuation_table(self):
        ff = self.meta["football_field"]
        refs = [r for r in val_refs(self.x) if r.startswith("Valuation!")]
        self.assertEqual(len(refs), 2)                                    # Low (invisible) and Spread
        sheet, rng = cells_in(refs[0])
        lo_col = ff["columns"]["low"]
        self.assertTrue(rng.startswith(f"{lo_col}{ff['first_row']}:") and rng.endswith(str(ff["marker_row"])))
        V = self.v["Valuation"]
        for r in range(ff["first_row"], ff["marker_row"] + 1):
            lo, hi, spread = V[f"B{r}"].value, V[f"C{r}"].value, V[f"D{r}"].value
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                self.assertAlmostEqual(lo + spread, hi, places=9)
        price = V[f"E{ff['marker_row']}"].value
        self.assertLessEqual(V[f"B{ff['marker_row']}"].value, price)
        self.assertGreaterEqual(V[f"C{ff['marker_row']}"].value, price)

    def test_peer_multiple_chart_data_is_blank_safe(self):
        t0 = comps.COV["peers"]
        n = 1 + len(self.meta["peers"])
        rows = {self.v["Cover"][f"B{t0 + 1 + i}"].value: self.v["Cover"][f"C{t0 + 1 + i}"].value for i in range(n)}
        for name, val in rows.items():
            self.assertIsInstance(val, (int, float), name)               # never "NM" text in a chart series
        self.assertEqual(rows["PDD"], 0)                                 # negative-EBITDA peer is NM on Comps, so zero here
        comps_ws = self.v["Comps"]
        med = self.v["Cover"][f"C{t0 + n + 1}"].value
        R = self.meta["rows"]["Comps"]
        ebitda_col = next(c for c in "FGHIJKLMNOPQ" if comps_ws[f"{c}5"].value == "EV / EBITDA LTM")
        self.assertAlmostEqual(med, comps_ws[f"{ebitda_col}{R['median']}"].value, places=9)

    def test_cover_has_a_horizontal_bar_chart(self):
        z = zipfile.ZipFile(BytesIO(self.x))
        dirs = [ET.fromstring(z.read(p)).find(".//c:barChart/c:barDir", NS).get("val") for p in cover_chart_parts(self.x)]
        self.assertGreaterEqual(dirs.count("bar"), 2)                    # football field and the peer EV / EBITDA ranking


if __name__ == "__main__":
    unittest.main()
