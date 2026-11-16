"""Excel engine: workbook writer/reader, formula evaluator, statements from XBRL, the integrated model, the grader
and the planted-error audit. Hermetic: a synthetic company, no network, no LibreOffice needed."""
import unittest

from om import bench, model3, modelcheck
from om import formula as fx
from om import statements as stm
from om.xlsx import Workbook, literals, read, relative, shift


def _fact(val, end, start=None, form="10-K", filed=None, accn="0000000001-25-000001"):
    d = {"val": val, "end": end, "form": form, "accn": accn, "filed": filed or f"{int(end[:4]) + 1}-02-15"}
    if start:
        d["start"] = start
    return d


def synthetic_companyfacts(years=(2022, 2023, 2024)) -> dict:
    """A small, internally consistent company: statements tie exactly, like a real 10-K."""
    g = {}

    def put(concept, rows, unit="USD"):
        g.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).extend(rows)

    cash_prev = 50.0
    for i, y in enumerate(years):
        s, e = f"{y}-01-01", f"{y}-12-31"
        M = 1e6
        rev = 1000.0 * (1.1 ** i)
        cogs, rd, sga = 0.55 * rev, 0.08 * rev, 0.12 * rev
        ebit = rev - cogs - rd - sga
        ie, ii = 20.0, 5.0
        pretax = ebit - ie + ii
        tax = 0.21 * pretax
        ni = pretax - tax
        da, sbc, capex, div, bb = 0.05 * rev, 0.02 * rev, 0.06 * rev, 0.2 * ni, 0.3 * ni
        cfo = ni + da + sbc - 10.0
        cfi = -capex - 5.0
        cff = -div - bb + 15.0
        chg = cfo + cfi + cff
        cash = cash_prev + chg
        ar, inv, ap = 0.1 * rev, 0.08 * rev, 0.07 * rev
        ca = cash + ar + inv + 30.0
        ppe = 400.0 + 20 * i
        gw = 100.0
        assets = ca + ppe + gw + 60.0
        debt_c, debt_nc = 25.0, 300.0
        cl = ap + debt_c + 40.0
        liab = cl + debt_nc + 50.0
        eq = assets - liab
        for c, v in (("Revenues", rev), ("CostOfRevenue", cogs), ("GrossProfit", rev - cogs), ("ResearchAndDevelopmentExpense", rd),
                     ("SellingGeneralAndAdministrativeExpense", sga), ("OperatingIncomeLoss", ebit), ("InterestExpense", ie),
                     ("InvestmentIncomeInterest", ii),
                     ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", pretax),
                     ("IncomeTaxExpenseBenefit", tax), ("NetIncomeLoss", ni), ("DepreciationDepletionAndAmortization", da),
                     ("ShareBasedCompensation", sbc), ("NetCashProvidedByUsedInOperatingActivities", cfo),
                     ("PaymentsToAcquirePropertyPlantAndEquipment", capex), ("NetCashProvidedByUsedInInvestingActivities", cfi),
                     ("PaymentsOfDividends", div), ("PaymentsForRepurchaseOfCommonStock", bb),
                     ("NetCashProvidedByUsedInFinancingActivities", cff), ("CashAndCashEquivalentsPeriodIncreaseDecrease", chg)):
            put(c, [_fact(v * M, e, s)])
        put("WeightedAverageNumberOfDilutedSharesOutstanding", [_fact(100e6 - i * 1e6, e, s)], unit="shares")
        put("EarningsPerShareDiluted", [_fact(round(ni * M / (100e6 - i * 1e6), 2), e, s)], unit="USD/shares")
        for c, v in (("CashAndCashEquivalentsAtCarryingValue", cash), ("AccountsReceivableNetCurrent", ar), ("InventoryNet", inv),
                     ("AssetsCurrent", ca), ("PropertyPlantAndEquipmentNet", ppe), ("Goodwill", gw), ("Assets", assets),
                     ("AccountsPayableCurrent", ap), ("LongTermDebtCurrent", debt_c), ("LiabilitiesCurrent", cl),
                     ("LongTermDebtNoncurrent", debt_nc), ("Liabilities", liab), ("StockholdersEquity", eq),
                     ("LiabilitiesAndStockholdersEquity", assets)):
            put(c, [_fact(v * M, e)])
        cash_prev = cash
    return {"cik": 1234, "entityName": "Testco Inc.", "facts": {"us-gaap": g}}


class WriterReaderTests(unittest.TestCase):
    def test_round_trip_styles_comments_links_names(self):
        wb = Workbook(iterate=True)
        sh = wb.sheet("Model")
        sh.set("B2", 100.0, kind="hist", comment="us-gaap:Revenues", link="https://www.sec.gov/")
        sh.set("C2", 0.05, fmt="pct")
        sh.set("D2", "=B2*(1+C2)", fmt="num0")
        sh.set("E2", "=Other!A1")
        wb.sheet("Other").set("A1", 7.0)
        wb.define("Growth", "Model", "C2")
        fx.calculate_workbook(wb)
        b = read(wb.to_bytes())
        self.assertTrue(b.iterate)
        self.assertEqual(b.cell("Model", "B2").color, "0000FF")          # typed number blue
        self.assertEqual(b.cell("Model", "D2").color, "000000")          # formula black
        self.assertEqual(b.cell("Model", "E2").color, "008000")          # link to another sheet green
        self.assertAlmostEqual(b.value("Model", "D2"), 105.0)            # cached value written
        self.assertEqual(b.comments["Model"][(2, 2)], "us-gaap:Revenues")
        self.assertEqual(b.links["Model"][(2, 2)], "https://www.sec.gov/")
        self.assertEqual(b.names["Growth"], "Model!$C$2")

    def test_reference_helpers(self):
        self.assertEqual(shift("=C5*(1+D$7)+$B$2", 0, 1), "=D5*(1+E$7)+$B$2")
        self.assertEqual(relative("=D5*(1+E$7)", 5, 5), relative("=C5*(1+D$7)", 5, 4))
        self.assertEqual(literals('=IF(Scenario=1,C5*1.05,C5)+"x2"'), [1.0, 1.05])


class FormulaTests(unittest.TestCase):
    def calc(self, cells, names=None, iterate=True):
        e = fx.Engine(cells, names)
        e.calculate(iterate=iterate)
        return e

    def test_arithmetic_and_functions(self):
        e = self.calc({("S", 1, 1): 2.0, ("S", 1, 2): "=-A1^2", ("S", 1, 3): "=SUM(A1:B1)+MAX(1,5)*10%",
                       ("S", 1, 4): '=IF(A1>1,"big","small")&"!"', ("S", 1, 5): "=NPV(0.1,A1,A1)", ("S", 1, 6): "=1/0",
                       ("S", 1, 7): "=IFERROR(F1,9)", ("S", 1, 8): "=CHOOSE(2,10,20,30)", ("S", 1, 9): '=COUNTIF(D1:D1,"big!")',
                       ("S", 1, 10): "=MEDIAN(A1,B1,C1)", ("S", 1, 11): "=#REF!"})
        v = lambda c: e.values[("S", 1, c)]
        self.assertEqual(v(2), 4.0)                                        # Excel: unary minus binds before ^
        self.assertAlmostEqual(v(3), 2 + 4 + 0.5)
        self.assertEqual(v(4), "big!")
        self.assertAlmostEqual(v(5), 2 / 1.1 + 2 / 1.21)
        self.assertEqual(v(6), fx.DIV0)
        self.assertEqual(v(7), 9.0)
        self.assertEqual(v(8), 20.0)
        self.assertEqual(v(9), 1.0)
        self.assertAlmostEqual(v(10), 4.0)
        self.assertEqual(v(11), fx.REF)

    def test_circular_reference_converges_like_excel_iteration(self):
        # interest = 10% of average cash; cash = 100 + interest
        e = self.calc({("S", 1, 1): "=100+B1", ("S", 1, 2): "=0.1*AVERAGE(100,A1)"})
        self.assertTrue(e.converged)
        cash = e.values[("S", 1, 1)]
        self.assertAlmostEqual(cash, 100 + 0.1 * (100 + cash) / 2, places=6)

    def test_invalid_formula_is_the_models_fault(self):
        e = fx.Engine({("S", 1, 1): "=Owned hospital beds at year end", ("S", 1, 2): "=SUM(A:A)"})
        self.assertIn(("S", 1, 1), e.invalid)
        self.assertNotIn(("S", 1, 2), e.invalid)       # valid Excel we don't evaluate yet
        self.assertTrue(e.unsupported)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stm.build(synthetic_companyfacts(), "TEST")
        cls.wb, cls.meta = model3.build_workbook(cls.s)
        cls.x = cls.wb.to_bytes()
        cls.grade = modelcheck.grade(cls.x)

    def test_statements_extracted_with_sources(self):
        self.assertEqual(len(self.s.years), 3)
        self.assertAlmostEqual(self.s.get("revenue", 0), 1000.0)
        self.assertIn("us-gaap:Revenues", self.s.data["revenue"][0].source())
        self.assertEqual(self.s.warnings, [])

    def test_model_solves_and_grades_production_ready(self):
        self.assertTrue(self.meta["converged"])
        self.assertTrue(self.grade["production_ready"], [g for g in self.grade["graders"] if g["passed"] is False])
        self.assertEqual(self.grade["score"], 100.0)
        b = read(self.x)
        master = b.value("Checks", f"C{self.meta['rows']['Checks']['master']}")
        self.assertEqual(master, "OK")
        self.assertEqual(b.sheets and b.order[0], "Cover")

    def test_balance_sheet_balances_every_period_in_every_scenario(self):
        for scenario in (1, 2, 3):
            for circ in (0, 1):
                wb, meta = model3.build_workbook(self.s, scenario=scenario, circ=circ)
                b = read(wb.to_bytes())
                r = meta["rows"]["BS"]["bal"]
                for p in range(len(self.s.years) + model3.F):
                    self.assertAlmostEqual(b.sheets["BS"][(r, model3.C0 + p)].value, 0.0, places=3, msg=(scenario, circ, p))

    def test_historicals_tie_to_filing(self):
        b = read(self.x)
        rows = self.meta["rows"]["IS"]
        for p in range(3):
            self.assertAlmostEqual(b.sheets["IS"][(rows["rev"], model3.C0 + p)].value, self.s.get("revenue", p), places=6)
            self.assertAlmostEqual(b.sheets["IS"][(rows["ni"], model3.C0 + p)].value, self.s.get("net_income", p), places=6)

    def test_every_forecast_row_uses_one_formula(self):
        g = next(x for x in self.grade["graders"] if x["id"] == "consistency")
        self.assertTrue(g["passed"])
        g = next(x for x in self.grade["graders"] if x["id"] == "constants")
        self.assertTrue(g["passed"], g["cells"][:3])

    def test_audit_catches_every_planted_error_without_false_alarms(self):
        a = bench.audit(self.wb, self.meta)
        self.assertTrue(a["clean_passes"])
        missed = [r["error"] for r in a["rows"] if not r["caught"]]
        self.assertEqual(missed, [])

    def test_bank_balance_sheet_is_refused_clearly(self):
        cf = synthetic_companyfacts()
        for c in ("AssetsCurrent", "LiabilitiesCurrent"):
            cf["facts"]["us-gaap"].pop(c)
        with self.assertRaises(model3.UnsupportedCompany) as e:
            model3.build(stm.build(cf, "BANK"))
        self.assertIn("unclassified balance sheet", str(e.exception))


class GraderOnForeignModels(unittest.TestCase):
    def test_flags_hardcodes_plugs_and_missing_checks(self):
        wb = Workbook()
        sh = wb.sheet("Model")
        for c, v in zip("BCDEF", (100.0, "=B1*1.05", "=C1*1.05", 115.0, "=E1*1.05")):
            sh.set(f"{c}1", v)
        sh.set("D2", "=D1*1.05")
        g = modelcheck.grade(wb.to_bytes())
        by = {x["id"]: x for x in g["graders"]}
        self.assertFalse(g["production_ready"])
        self.assertFalse(by["checks"]["passed"])            # no Checks tab
        self.assertFalse(by["constants"]["passed"])         # 1.05 typed in formulas
        self.assertIsNone(by["balances"]["passed"])         # no balance sheet: not applicable


if __name__ == "__main__":
    unittest.main()
