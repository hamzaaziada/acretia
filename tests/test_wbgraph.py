"""S4.4: workbook graph, explain and Ask mode (deterministic, offline)."""
import unittest

from om import model3, statements as stm, xlsx
from om import wbgraph as wg
from om.contracts import WorkbookGraph
from tests.test_model3 import synthetic_companyfacts


class WbGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stm.build(synthetic_companyfacts((2022, 2023, 2024)), "TST")
        cls.data, cls.meta = model3.build(cls.s)
        cls.rows = cls.meta["rows"]
        cls.g = wg.graph(cls.data)
        cls.book = xlsx.read(cls.data)

    def cell(self, sheet, key, col="G"):          # G = FY2026E with three actual years
        return f"{sheet}!{col}{self.rows[sheet][key]}"

    # ------------------------------------------------------------ contract
    def test_contract_round_trip_and_shape(self):
        d = self.g.to_dict()
        again = WorkbookGraph.from_dict(d)
        self.assertEqual(again.to_dict(), d)
        self.assertGreater(len(self.g.nodes), 1000)
        n = self.g.nodes[self.cell("IS", "rev")]
        self.assertTrue(n.formula.startswith("=") and isinstance(n.value, float))
        self.assertIn("Scenario", self.g.names)
        # defined names are resolved to the cells they point at: EBITDA-driving growth goes through the CHOOSE on Assumptions
        self.assertIn("Assumptions!C9", self.g.edges[self.cell("Assumptions", "growth")])

    def test_ranges_stay_ranges(self):
        ranged = [(k, e) for k, es in self.g.edges.items() for e in es if ":" in e]
        self.assertTrue(ranged)
        for k, e in ranged[:20]:
            self.assertRegex(e, r"!\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+$")

    # ------------------------------------------------------------ traversal
    def test_precedents_and_dependents(self):
        ebitda, rev = self.cell("IS", "ebitda"), self.cell("IS", "rev")
        self.assertIn(rev, wg.precedents(self.g, ebitda))
        self.assertNotIn(rev, wg.precedents(self.g, ebitda, depth=1))          # EBITDA = EBIT + D&A; revenue is two steps away
        self.assertIn(self.cell("IS", "ebit"), wg.precedents(self.g, ebitda, depth=1))
        self.assertIn(ebitda, wg.dependents(self.g, rev))
        self.assertIn(self.cell("IS", "gp"), wg.dependents(self.g, rev, depth=1))
        self.assertNotIn(ebitda, wg.dependents(self.g, rev, depth=1))
        self.assertEqual(wg.precedents(self.g, "'IS'!$G$" + str(self.rows["IS"]["rev"]), depth=1),
                         wg.precedents(self.g, rev, depth=1))                  # reference spellings normalise

    def test_inputs_of_are_typed_numbers(self):
        leaves = wg.inputs_of(self.g, self.cell("IS", "rev"))
        self.assertTrue(leaves)
        for k in leaves:
            n = self.g.nodes[k]
            self.assertIsNone(n.formula)
            self.assertIsInstance(n.value, float)
        self.assertIn(self.cell("Assumptions", "growth_b"), leaves)
        self.assertIn(self.cell("Filings", "revenue", col="E"), leaves)         # the last actual year anchors the forecast

    def test_label_of(self):
        self.assertEqual(wg.label_of(self.book, self.cell("IS", "rev")), "Revenue (FY2026E)")
        self.assertEqual(wg.label_of(self.book, self.cell("IS", "rev", col="D")), "Revenue (FY2023A)")

    def test_explain_cites_sources(self):
        ex = wg.explain(self.data, self.cell("IS", "rev", col="D"))
        self.assertEqual(ex["label"], "Revenue (FY2023A)")
        self.assertEqual(ex["precedents"][0]["cell"], self.cell("Filings", "revenue", col="D"))
        self.assertTrue(ex["inputs"])
        self.assertIn("us-gaap:Revenues", ex["inputs"][0]["source"])
        deep = wg.explain(self.data, self.cell("IS", "ebitda"))
        self.assertTrue(deep["precedents"] and deep["precedents"][0]["precedents"])  # depth 2
        with self.assertRaises(KeyError):
            wg.explain(self.data, "IS!ZZ999")

    # ------------------------------------------------------------ ask mode
    def ask(self, q):
        return wg.ask(self.data, q)

    def test_ask_revenue_by_year(self):
        for q in ("what is FY2026 revenue", "Sales in 2026E?", "turnover FY2026"):
            r = self.ask(q)
            self.assertEqual(r["cells"], [self.cell("IS", "rev")], q)
            self.assertAlmostEqual(r["values"][0], self.book.value("IS", self.cell("IS", "rev").split("!")[1]))
            self.assertIn(self.cell("IS", "rev"), r["answer"])
        self.assertEqual(self.ask("revenue 2023")["cells"], [self.cell("IS", "rev", col="D")])

    def test_ask_margins_and_eps(self):
        r = self.ask("EBITDA margin in 2025")
        self.assertEqual(r["cells"], [self.cell("IS", "ebitda_m", col="F")])
        self.assertAlmostEqual(r["values"][0], self.book.value("IS", self.cell("IS", "ebitda_m", col="F").split("!")[1]))
        self.assertEqual(self.ask("gross margin 2024")["cells"], [self.cell("IS", "gm", col="E")])
        self.assertEqual(self.ask("what is diluted EPS for 2026")["cells"], [self.cell("IS", "eps")])
        self.assertEqual(self.ask("net profit in FY2023")["cells"], [self.cell("IS", "ni", col="D")])

    def test_ask_no_period_returns_every_year(self):
        r = self.ask("what is EBITDA")
        self.assertEqual(len(r["cells"]), 8)
        self.assertEqual(r["cells"][0], self.cell("IS", "ebitda", col="C"))

    def test_ask_what_drives_fcf(self):
        r = self.ask("what drives free cash flow")
        self.assertIn("CF!", r["cells"][0])
        self.assertIn(self.cell("CF", "cfo", col="F"), r["cells"])
        self.assertIn(self.cell("CF", "capex", col="F"), r["cells"])
        self.assertIn("fed by", r["answer"])

    def test_ask_where_does_net_income_come_from(self):
        r = self.ask("where does 2023 net income come from")
        self.assertEqual(r["cells"][0], self.cell("IS", "ni", col="D"))
        self.assertIn(self.cell("IS", "pretax", col="D"), r["cells"])
        self.assertIn("us-gaap:", r["answer"])                                 # ends at the filed XBRL figure

    def test_ask_wacc_inputs(self):
        r = self.ask("which cells feed the WACC")
        self.assertTrue(r["cells"][0].startswith("DCF!"))
        labels = " ".join(r["answer"].split())
        self.assertIn("Cost of equity", labels)
        self.assertGreater(len(r["cells"]), 2)

    def test_ask_refuses_the_unanswerable(self):
        r = self.ask("what is the airspeed velocity of an unladen swallow")
        self.assertEqual((r["cells"], r["values"]), ([], []))
        self.assertIn("won't guess", r["answer"])
        self.assertTrue(r["method"].startswith("unresolved"))
        r = self.ask("revenue in 2031")                                        # label exists, period does not
        self.assertEqual(r["cells"], [])
        self.assertIn("Nearest labels", r["answer"])


if __name__ == "__main__":
    unittest.main()
