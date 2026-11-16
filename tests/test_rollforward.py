"""S4.4: earnings roll-forward of an om.model3 workbook."""
import unittest

from om import model3, modelcheck, rollforward, statements as stm, wbedit, xlsx
from tests.test_model3 import synthetic_companyfacts


class RollForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s_old = stm.build(synthetic_companyfacts((2022, 2023)), "TST")
        cls.s_new = stm.build(synthetic_companyfacts((2022, 2023, 2024)), "TST")
        cls.old, cls.old_meta = model3.build(cls.s_old)
        cls.rows = cls.old_meta["rows"]["Assumptions"]
        # the user edits tax for FY2025E and FY2026E (old columns F, G) and the FY2024E growth (column E, about to be an actual)
        cls.edited, _ = wbedit.edit(cls.old, {f"Assumptions!F{cls.rows['tax']}": 0.33, f"Assumptions!G{cls.rows['tax']}": 0.34,
                                              f"Assumptions!E{cls.rows['growth_b']}": 0.5})
        cls.new, cls.report = rollforward.roll_forward(cls.edited, cls.s_new)
        cls.book = xlsx.read(cls.new)
        cls.old_book = xlsx.read(cls.edited)
        cls.nrows = cls.report["meta"]["rows"]

    def test_new_year_is_an_actual_and_sourced(self):
        self.assertEqual(self.report["new_actual"]["label"], "FY2024A")
        self.assertEqual(self.report["new_actual"]["column"], "E")
        self.assertEqual(self.book.value("IS", "E5"), "FY2024A")
        self.assertEqual(self.book.value("IS", "F5"), "FY2025E")
        self.assertEqual(self.book.value("IS", "J5"), "FY2029E")
        rev = self.book.cell("IS", f"E{self.nrows['IS']['rev']}")
        self.assertEqual(rev.formula, f"=Filings!E{self.nrows['Filings']['revenue']}")        # actual column links to the filing
        filing = self.book.cell("Filings", f"E{self.nrows['Filings']['revenue']}")
        self.assertEqual(filing.color, "0000FF")
        self.assertIn("us-gaap:Revenues", self.book.comments["Filings"][(self.nrows["Filings"]["revenue"], 5)])
        self.assertAlmostEqual(filing.value, 1210.0)

    def test_users_assumptions_carry_over_by_fiscal_year(self):
        r = self.rows["tax"]
        # 2025E / 2026E sat in columns F, G of the old workbook and still sit in F, G (the window moved by a year but so did the actuals)
        self.assertAlmostEqual(self.book.value("Assumptions", f"F{r}"), 0.33)
        self.assertAlmostEqual(self.book.value("Assumptions", f"G{r}"), 0.34)
        # FY2027E and FY2028E were not edited: they keep the old workbook's value, not a fresh default
        self.assertAlmostEqual(self.book.value("Assumptions", f"H{r}"), self.old_book.value("Assumptions", f"H{r}"))
        self.assertAlmostEqual(self.book.value("Assumptions", f"I{r}"), self.old_book.value("Assumptions", f"I{r}"))
        # the new final year extends the last value
        self.assertAlmostEqual(self.book.value("Assumptions", f"J{r}"), self.old_book.value("Assumptions", f"I{r}"))
        keys = {(c["key"], c["year"]): c["value"] for c in self.report["assumptions_carried"]}
        self.assertAlmostEqual(keys[("tax", 2025)], 0.33)
        self.assertTrue(any(e["key"] == "tax" and e["year"] == 2029 for e in self.report["assumptions_extended"]))
        # the scenario growth rates carry over as well (base case for 2026E)
        g = self.rows["growth_b"]
        self.assertAlmostEqual(self.book.value("Assumptions", f"G{g}"), self.old_book.value("Assumptions", f"G{g}"))

    def test_dropped_assumptions_are_reported(self):
        dropped = {(d["key"], d["year"]): d for d in self.report["assumptions_dropped"]}
        self.assertIn(("growth_b", 2024), dropped)
        self.assertAlmostEqual(dropped[("growth_b", 2024)]["value"], 0.5)               # the user's edit to a year that is now actual
        self.assertIn("now an actual", dropped[("growth_b", 2024)]["reason"])
        self.assertTrue(all(d["year"] == 2024 for d in self.report["assumptions_dropped"]))
        self.assertIsNone(self.book.value("Assumptions", f"E{self.rows['growth_b']}"))             # actual column holds no scenario input

    def test_variance_table_matches_both_workbooks(self):
        v = {x["metric"]: x for x in self.report["variance"]}
        self.assertEqual(list(v), ["Revenue", "EBITDA", "Net income", "Diluted EPS", "Free cash flow"])
        n = self.nrows
        for metric, sheet, key in (("Revenue", "IS", "rev"), ("EBITDA", "IS", "ebitda"), ("Net income", "IS", "ni"),
                                   ("Diluted EPS", "IS", "eps"), ("Free cash flow", "CF", "fcf")):
            row_new = n[sheet][key]
            row_old = self.old_meta["rows"][sheet][key]
            prior = self.old_book.value(sheet, f"E{row_old}")                           # FY2024E in the old workbook
            actual = self.book.value(sheet, f"E{row_new}")                              # FY2024A in the new one
            x = v[metric]
            self.assertAlmostEqual(x["prior_forecast"], prior, places=6, msg=metric)
            self.assertAlmostEqual(x["actual"], actual, places=6, msg=metric)
            self.assertAlmostEqual(x["pct_diff"], actual / prior - 1, places=9, msg=metric)
            self.assertEqual(x["prior_cell"], f"{sheet}!E{row_old}")
            self.assertEqual(x["actual_cell"], f"{sheet}!E{row_new}")
        # EBITDA and net income actually moved: the synthetic actuals differ from the extrapolated forecast
        self.assertNotEqual(round(v["Net income"]["pct_diff"], 6), 0)

    def test_roll_forward_sheet(self):
        self.assertIn("Roll-forward", self.book.order)
        self.assertLess(self.book.order.index("Roll-forward"), self.book.order.index("Filings"))
        for i, x in enumerate(self.report["variance"]):
            r = 7 + i
            self.assertAlmostEqual(self.book.value("Roll-forward", f"C{r}"), x["prior_forecast"], places=6)
            self.assertAlmostEqual(self.book.value("Roll-forward", f"D{r}"), x["actual"], places=6)
            self.assertAlmostEqual(self.book.value("Roll-forward", f"F{r}"), x["pct_diff"], places=9)
            prior = self.book.cell("Roll-forward", f"C{r}")
            self.assertIsNone(prior.formula)
            self.assertEqual(prior.color, "0000FF")                                     # prior forecast: blue input
            self.assertIn(x["prior_cell"], self.book.comments["Roll-forward"][(r, 3)])  # comment names the prior workbook cell
            self.assertTrue(self.book.cell("Roll-forward", f"D{r}").formula.startswith("="))
            self.assertEqual(self.book.cell("Roll-forward", f"D{r}").color, "008000")   # link to another sheet: green

    def test_production_ready(self):
        g = modelcheck.grade(self.new)
        self.assertTrue(g["production_ready"], [x for x in g["graders"] if x["passed"] is False])
        self.assertGreaterEqual(g["score"], 95)
        self.assertTrue(self.report["meta"]["converged"])
        self.assertEqual(self.book.value("Checks", f"C{self.nrows['Checks']['master']}"), "OK")

    def test_scenario_switch_and_refusals(self):
        up, _ = wbedit.edit(self.old, {"Assumptions!C9": 2})
        _, rep = rollforward.roll_forward(up, self.s_new)
        self.assertEqual(rep["scenario"], 2)
        with self.assertRaises(ValueError):
            rollforward.roll_forward(self.new, self.s_new)                              # nothing new to roll in
        with self.assertRaises(ValueError):
            rollforward.roll_forward(xlsx.Workbook().to_bytes(), self.s_new)


if __name__ == "__main__":
    unittest.main()
