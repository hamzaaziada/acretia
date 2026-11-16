"""S4.9 template fit: a firm's reference workbook structure delivered with our SEC-sourced numbers. Hermetic."""
import unittest

from om import modelcheck, statements as stm, templatefit as tf, validate_xlsx
from om.xlsx import Workbook, read
from tests.test_model3 import synthetic_companyfacts


def _statements():
    return stm.build(synthetic_companyfacts(), "TEST")


def _row(sh, r, label, vals=None, f=None, fmt="num0", bold=False, indent=0, top=False, italic=False):
    sh.set(f"A{r}", label, bold=bold, indent=indent, top=top, italic=italic)
    for c, v in zip(["C", "D", "E"], vals or [None] * 3):
        if f:
            sh.set(f"{c}{r}", f.replace("#", c), fmt=fmt, bold=bold, top=top, italic=italic)
        elif v is not None:
            sh.set(f"{c}{r}", v, kind="hist", fmt=fmt, bold=bold)


def firm_template() -> bytes:
    """IS / BS / CF with the firm's own labels, FY22A..FY24E periods, subtotal formulas and a margin row."""
    wb = Workbook()
    for name, title in (("IS", "Income statement"), ("BS", "Balance sheet"), ("CF", "Cash flow")):
        sh = wb.sheet(name)
        sh.set("A1", f"Project Falcon · {title}", kind="title")
        sh.set("A3", "USD in millions", kind="note")
        sh.set("A5", "", kind="header")
        sh.set("B5", "", kind="header")
        for c, lab in zip("CDE", ["FY22A", "FY23A", "FY24E"]):
            sh.set(f"{c}5", lab, kind="header", align="right")
            sh.width(c, 12)
        sh.width("A", 40)
        sh.freeze = (5, 1)
    s = wb["IS"]
    _row(s, 6, "Net sales", [111.0, 222.0, 333.0], bold=True)
    _row(s, 7, "Cost of sales", [1.0, 2.0, 3.0], indent=1)
    _row(s, 8, "Gross profit", f="=#6-#7", bold=True, top=True)
    _row(s, 9, "SG&A", [1.0, 1.0, 1.0], indent=1)
    _row(s, 10, "R&D", [1.0, 1.0, 1.0], indent=1)
    _row(s, 11, "Restructuring charges", [5.0, 5.0, 5.0], indent=1)          # not in filings: must stay empty
    _row(s, 12, "Operating profit", f="=#8-#9-#10-#11", bold=True, top=True)
    _row(s, 13, "% margin", f="=#12/#6", fmt="pct", italic=True, indent=1)
    _row(s, 14, "Interest expense", [1.0, 1.0, 1.0], indent=1)
    _row(s, 15, "Net income", [1.0, 1.0, 1.0], bold=True)
    b = wb["BS"]
    _row(b, 6, "Cash and equivalents", [1.0, 1.0, 1.0])
    _row(b, 7, "Trade receivables", [1.0, 1.0, 1.0])
    _row(b, 8, "Inventories", [1.0, 1.0, 1.0])
    _row(b, 9, "Total assets", [1.0, 1.0, 1.0], bold=True, top=True)
    _row(b, 10, "Trade payables", [1.0, 1.0, 1.0])
    _row(b, 11, "Total liabilities", [1.0, 1.0, 1.0], bold=True, top=True)
    c = wb["CF"]
    _row(c, 6, "Cash flow from operating activities", [1.0, 1.0, 1.0], bold=True)
    _row(c, 7, "Purchases of PP&E", [1.0, 1.0, 1.0])
    _row(c, 8, "D&A", [1.0, 1.0, 1.0])
    return wb.to_bytes()


def summary_template() -> bytes:
    """A one-sheet summary: FY2022..FY2024 headers, thousands, a subtotal formula, one row the filings do not carry."""
    wb = Workbook()
    sh = wb.sheet("Summary")
    sh.set("A1", "Target summary", kind="title")
    sh.set("A2", "USD in thousands", kind="note")
    for c, lab in zip("BCD", ("FY2022", "FY2023", "FY2024")):
        sh.set(f"{c}4", lab, kind="header", align="right")
        sh.width(c, 13)
    sh.width("A", 36)
    sh.freeze = (4, 1)
    sh.set("A5", "Turnover", bold=True)
    sh.set("A6", "Total cost of sales")
    sh.set("A7", "Gross profit", bold=True, top=True)
    sh.set("A8", "Customer concentration")
    sh.set("A9", "Net profit", bold=True)
    for c in "BCD":
        sh.set(f"{c}5", 1.0, kind="hist", fmt="num0")
        sh.set(f"{c}6", 1.0, kind="hist", fmt="num0")
        sh.set(f"{c}7", f"={c}5-{c}6", fmt="num0", bold=True, top=True)
        sh.set(f"{c}8", 0.3, kind="hist", fmt="pct")
        sh.set(f"{c}9", 1.0, kind="hist", fmt="num0")
    return wb.to_bytes()


def _critical_failures(data: bytes):
    return [(x["id"], x["detail"]) for x in modelcheck.grade(data)["graders"] if x["critical"] and x["passed"] is False]


class TemplateFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.st = _statements()
        cls.ref = firm_template()
        cls.out, cls.rep = tf.generate(cls.ref, cls.st)
        cls.book = read(cls.out)

    def test_profile(self):
        p = tf.profile(self.ref)
        self.assertEqual(p["order"], ["IS", "BS", "CF"])
        sp = p["sheets"][0]
        self.assertEqual(sp["header_row"], 5)
        self.assertEqual([x["label"] for x in sp["periods"]], ["FY22A", "FY23A", "FY24E"])
        self.assertEqual([x["projection"] for x in sp["periods"]], [False, False, True])
        self.assertEqual(sp["label_col"], 1)
        self.assertEqual(sp["units"]["label"], "millions")
        self.assertEqual(sp["freeze"], (5, 1))
        it = {i["label"]: i for i in sp["items"]}
        self.assertTrue(it["Gross profit"]["formula"] and it["Gross profit"]["total"])
        self.assertEqual(it["Cost of sales"]["indent"], 1)
        self.assertTrue(it["Net sales"]["bold"])
        self.assertTrue(it["% margin"]["ratio"])
        self.assertEqual(p["colour_code"]["input"], "0000FF")

    def test_period_patterns(self):
        for s, y, proj in (("FY2021", 2021, False), ("2021A", 2021, False), ("2026E", 2026, True), ("FY24", 2024, False),
                           ("FY24E", 2024, True), ("Dec-23", 2023, False), (2025, 2025, False)):
            self.assertEqual((tf.parse_period(s)["year"], tf.parse_period(s)["projection"]), (y, proj), s)
        self.assertIsNone(tf.parse_period("Revenue"))
        self.assertIsNone(tf.parse_period(12))

    def test_mapping_synonyms(self):
        for label, key in (("Net sales", "revenue"), ("Turnover", "revenue"), ("Total revenues", "revenue"), ("Cost of sales", "cogs"),
                           ("SG&A", "sga"), ("Selling, general and administrative", "sga"), ("D&A", "da"), ("Capex", "capex"),
                           ("Purchases of PP&E", "capex"), ("Operating profit", "ebit"), ("Trade receivables", "ar"),
                           ("Profit before tax", "pretax")):
            self.assertEqual(tf.map_label(label)["key"], key, label)
        self.assertEqual(tf.map_label("Net income", "CF")["key"], "cf_net_income")
        self.assertEqual(tf.map_label("Net income", "IS")["key"], "net_income")
        self.assertIsNone(tf.map_label("% margin"))
        self.assertIsNone(tf.map_label("Restructuring charges"))
        m = tf.map_label("Selling and general admin expenses")   # similarity fallback with a confidence score
        self.assertTrue(m and m["key"] == "sga" and m["confidence"] < 1.0 and m["method"] == "fuzzy", m)

    def test_structure_matches(self):
        d = tf.structure_diff(self.ref, self.out)
        self.assertEqual(d["score"], 1.0, d)
        self.assertTrue(d["order_ok"])
        self.assertEqual(self.rep["score"], 1.0)
        self.assertEqual(self.book.order[:3], ["IS", "BS", "CF"])

    def test_structure_diff_detects_changes(self):
        other = Workbook()
        other.sheet("IS").set("A5", "x")
        self.assertLess(tf.structure_diff(self.ref, other.to_bytes())["score"], 1.0)

    def test_historicals_equal_statements_and_carry_sources(self):
        b, st = self.book, self.st
        for r, key in ((6, "revenue"), (7, "cogs"), (9, "sga"), (10, "rd"), (14, "interest_expense"), (15, "net_income")):
            for col, ci, i in (("C", 3, 0), ("D", 4, 1)):                 # FY22A, FY23A
                self.assertAlmostEqual(b.value("IS", f"{col}{r}"), st.get(key, i), places=6, msg=f"{key} {col}")
                self.assertIn("accn", b.comments["IS"][(r, ci)])
                self.assertTrue(b.links["IS"][(r, ci)].startswith("http"))
                self.assertEqual(b.cell("IS", f"{col}{r}").color, "0000FF")
        self.assertAlmostEqual(b.value("BS", "C9"), st.get("assets", 0), places=6)
        self.assertAlmostEqual(b.value("CF", "D7"), st.get("capex", 1), places=6)     # as filed (positive)
        self.assertAlmostEqual(b.value("CF", "C8"), st.get("da", 0), places=6)

    def test_projection_column_empty_without_model(self):
        for r in (6, 7, 8, 12, 13):
            self.assertIn(self.book.value("IS", f"E{r}"), (None, ""))
        self.assertTrue(any(e["col"] == "E" for e in self.rep["empty_periods"]))

    def test_subtotals_are_formulas_and_tie(self):
        b = self.book
        self.assertEqual(b.cell("IS", "C8").formula, "=C6-C7")
        self.assertEqual(b.cell("IS", "D12").formula, "=D8-D9-D10-D11")
        self.assertEqual(b.cell("IS", "C13").formula, "=C12/C6")
        self.assertAlmostEqual(b.value("IS", "C8"), b.value("IS", "C6") - b.value("IS", "C7"), places=6)
        self.assertAlmostEqual(b.value("IS", "C12"), self.st.get("ebit", 0), places=4)          # ties to reported operating income
        self.assertAlmostEqual(b.value("IS", "D13"), self.st.get("ebit", 1) / self.st.get("revenue", 1), places=6)
        ties = [t for t in self.rep["ties"] if t["key"] == "ebit"]
        self.assertTrue(ties and all(t["ties"] for t in ties), ties)

    def test_unmapped_rows_stay_empty_and_flagged(self):
        b = self.book
        for col in "CDE":
            self.assertIn(b.value("IS", f"{col}11"), (None, ""))
        self.assertEqual(b.value("IS", "A11"), "Restructuring charges")
        self.assertEqual(b.comments["IS"][(11, 1)], tf.NOT_IN_FILINGS)
        self.assertTrue(any(u["label"] == "Restructuring charges" and u["sheet"] == "IS" for u in self.rep["unmapped"]))

    def test_report(self):
        r = self.rep
        self.assertTrue(r["formulas"])
        self.assertTrue(any(m["key"] == "revenue" and m["confidence"] == 1.0 for m in r["mapped"]))
        self.assertGreater(r["filled"], 20)
        self.assertEqual(r["structure"]["score"], 1.0)

    def test_grades_and_validates(self):
        self.assertEqual(_critical_failures(self.out), [])
        v = validate_xlsx.validate(self.out)
        self.assertTrue(v["passed"], v["findings"])

    def test_one_sheet_summary_thousands(self):
        ref = summary_template()
        out, rep = tf.generate(ref, self.st)
        b = read(out)
        self.assertEqual(tf.structure_diff(ref, out)["score"], 1.0)
        # thousands declared: statements are $m, so x1000
        self.assertAlmostEqual(b.value("Summary", "B5"), self.st.get("revenue", 0) * 1000, places=4)
        self.assertAlmostEqual(b.value("Summary", "D6"), self.st.get("cogs", 2) * 1000, places=4)
        self.assertEqual(b.cell("Summary", "B7").formula, "=B5-B6")
        self.assertAlmostEqual(b.value("Summary", "B7"), (self.st.get("revenue", 0) - self.st.get("cogs", 0)) * 1000, places=4)
        self.assertAlmostEqual(b.value("Summary", "C9"), self.st.get("net_income", 1) * 1000, places=4)
        for col in "BCD":
            self.assertIn(b.value("Summary", f"{col}8"), (None, ""))
        self.assertEqual(b.comments["Summary"][(8, 1)], tf.NOT_IN_FILINGS)
        self.assertTrue(any(u["label"] == "Customer concentration" for u in rep["unmapped"]))
        self.assertEqual(_critical_failures(out), [])
        v = validate_xlsx.validate(out)
        self.assertTrue(v["passed"], v["findings"])

    def test_period_not_in_filings_left_empty(self):
        w = Workbook()
        sh = w.sheet("S")
        for c, lab in zip("BC", ("FY2021", "FY2024")):
            sh.set(f"{c}3", lab, kind="header")
        sh.set("A4", "Revenue")
        sh.set("B4", 9.0, kind="hist")
        sh.set("C4", 9.0, kind="hist")
        out, rep = tf.generate(w.to_bytes(), self.st)
        b = read(out)
        self.assertIn(b.value("S", "B4"), (None, ""))                      # never a guessed number
        self.assertAlmostEqual(b.value("S", "C4"), self.st.get("revenue", 2), places=6)
        self.assertTrue(any("not in the filings" in e["reason"] for e in rep["empty_periods"]))

    def test_untranslatable_formula_falls_back_to_sum(self):
        w = Workbook()
        sh = w.sheet("IS")
        sh.set("B3", "FY2023A", kind="header")
        sh.set("C3", "FY2024A", kind="header")
        sh.set("A4", "Net sales")
        sh.set("A5", "Cost of sales")
        sh.set("A6", "Gross profit")
        for c in "BC":
            sh.set(f"{c}4", 1.0, kind="hist")
            sh.set(f"{c}5", 1.0, kind="hist")
            sh.set(f"{c}6", f"=Other!{c}4-{c}5")
        out, rep = tf.generate(w.to_bytes(), self.st)
        b = read(out)
        self.assertEqual(b.cell("IS", "B6").formula, "=SUM(B4:B5)")
        self.assertTrue(any("fallback" in f["status"] for f in rep["formulas"]))
        self.assertTrue(rep["flags"])

    def test_sign_convention_follows_reference(self):
        w = Workbook()
        sh = w.sheet("IS")
        sh.set("B3", "FY2023A", kind="header")
        sh.set("C3", "FY2024A", kind="header")
        sh.set("A4", "Gross profit")
        sh.set("A5", "SG&A")
        sh.set("A6", "Operating profit")
        sh.set("C4", 5.0, kind="hist")
        sh.set("C5", -1.0, kind="hist")
        sh.set("C6", "=C4+C5", bold=True)
        # the reference ADDS expenses (shown negative), so the output must show them negative and still tie
        sh.set("B4", 5.0, kind="hist")
        sh.set("B5", -1.0, kind="hist")
        sh.set("B6", "=B4+B5", bold=True)
        out, rep = tf.generate(w.to_bytes(), self.st)
        b = read(out)
        self.assertAlmostEqual(b.value("IS", "B5"), -self.st.get("sga", 1), places=6)
        self.assertTrue(any(x["key"] == "sga" and "outflow" in x["convention"] for x in rep["signs"]))

    def test_model_projection_links(self):
        from om import model3
        data, meta = model3.build(self.st)
        out, rep = tf.generate(self.ref, self.st, model_meta=meta, model_bytes=data)
        b = read(out)
        self.assertEqual(b.order[:3], ["IS", "BS", "CF"])
        self.assertIn("Model", b.order)
        f = b.cell("IS", "E6").formula
        self.assertTrue(f and f.startswith("=Model!"), f)
        self.assertEqual(b.cell("IS", "E6").color, "008000")
        self.assertIsNotNone(b.value("IS", "E6"))
        self.assertEqual(tf.structure_diff(self.ref, out)["score"], 1.0)
        self.assertEqual(_critical_failures(out), [])


if __name__ == "__main__":
    unittest.main()
