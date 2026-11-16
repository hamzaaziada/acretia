"""LBO builder: conventions acceptance (grade, checks, LibreOffice), independent recomputation of the returns from the
workbook's own cached values, tranche mechanics, attribution, sensitivity and circularity. Hermetic: synthetic company."""
import shutil
import unittest

from om import bench, lbo, modelcheck
from om import statements as stm
from om.xlsx import read
from tests.test_model3 import synthetic_companyfacts

MARKET = {"price": 25.0, "as_of": "2024-12-31", "source": "test fixture"}
COLS = "CDEFGH"                         # Debt / Checks: close, then years 1-5


class LboBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = stm.build(synthetic_companyfacts(), "TEST")
        cls.wb, cls.meta = lbo.build_workbook(cls.s, market=MARKET)
        cls.x = cls.wb.to_bytes()
        cls.b = read(cls.x)
        cls.R = cls.meta["rows"]

    def v(self, sheet, key, col="C", b=None):
        return (b or self.b).value(sheet, f"{col}{self.R[sheet][key]}")

    def out(self, id_):
        o = next(o for o in self.meta["outputs"] if o["id"] == id_)
        return self.b.value(o["sheet"], o["ref"])


class AcceptanceTests(LboBase):
    def test_grade_production_ready(self):
        g = modelcheck.grade(self.x)
        self.assertTrue(g["production_ready"], [r for r in g["graders"] if r["passed"] is False])
        self.assertGreaterEqual(g["score"], 95)

    def test_master_check_ok_and_converged(self):
        self.assertTrue(self.meta["converged"])
        self.assertEqual(self.v("Checks", "master"), "OK")
        for k, row in self.R["Checks"].items():
            if k.startswith("c_"):
                for c in COLS:
                    val = self.b.value("Checks", f"{c}{row}")
                    self.assertIn(val, (None, "OK"), f"{k} {c}")

    def test_sheets_and_outputs(self):
        self.assertEqual(self.b.order, ["Cover", "Assumptions", "Sources & Uses", "Operations", "Debt", "Returns", "Sensitivity", "Checks", "Filings"])
        ids = {o["id"] for o in self.meta["outputs"]}
        for want in ("lbo.irr", "lbo.mom", "lbo.entry_ev", "lbo.exit_ev", "lbo.sponsor_equity", "lbo.total_leverage_entry",
                     "lbo.attr_ebitda_growth", "lbo.attr_multiple", "lbo.attr_deleveraging"):
            self.assertIn(want, ids)
        for o in self.meta["outputs"]:
            self.assertIsInstance(self.b.value(o["sheet"], o["ref"]), float, o["id"])
        for k in ("sweep", "pik", "exit"):
            sheet, cell = self.meta["plants"][k].split("!")
            self.assertTrue(self.b.cell(sheet, cell).formula, k)

    def test_libreoffice_agrees_at_circ_zero(self):
        if not (shutil.which("soffice") or shutil.which("libreoffice")):
            self.skipTest("LibreOffice (soffice) not installed")
        x0 = lbo.build(self.s, market=MARKET, circ=0)[0]
        res = bench.agree(x0)
        if res is None:
            self.skipTest("LibreOffice recalculation unavailable")
        self.assertEqual(res["mismatches"], 0, res["examples"])
        self.assertGreater(res["formula_cells"], 300)

    def test_market_input_carries_its_source(self):
        a = self.R["Assumptions"]["price"]
        self.assertEqual(self.b.value("Assumptions", f"C{a}"), 25.0)
        self.assertIn("test fixture", self.b.comments["Assumptions"][(a, 3)])
        self.assertEqual(self.b.cell("Assumptions", f"C{a}").color, "0000FF")


class ReturnsTests(LboBase):
    def test_irr_and_mom_recomputed_independently(self):
        eq_in = self.v("Sources & Uses", "s_eq")
        eq_out = self.v("Returns", "eq_out")
        n = int(self.v("Returns", "n"))
        mom = eq_out / eq_in
        self.assertAlmostEqual(self.out("lbo.mom"), mom, places=9)
        self.assertAlmostEqual(self.out("lbo.irr"), mom ** (1 / n) - 1, places=9)
        # equity in = uses - debt, from the workbook's own cells
        uses = sum(self.v("Sources & Uses", k) for k in ("u_eq", "u_nd", "u_txn", "u_fin", "u_cash"))
        debt = sum(self.v("Sources & Uses", k) for k in ("s_rev", "s_tlb", "s_sn", "s_pik"))
        self.assertAlmostEqual(eq_in, uses - debt, places=6)
        # exit equity = multiple x exit EBITDA less net debt (incl. PIK)
        ebitda = self.b.value("Operations", f"{'CDEFGHIJ'[len(self.s.years) - 1 + n]}{self.R['Operations']['ebitda']}")
        mult = self.b.value("Assumptions", f"C{self.R['Assumptions']['exit_mult']}")
        nd = self.b.value("Debt", f"{COLS[n]}{self.R['Debt']['net_debt']}")
        self.assertAlmostEqual(eq_out, mult * ebitda - nd, places=6)

    def test_irr_cross_check_row_agrees(self):
        self.assertAlmostEqual(self.v("Returns", "irr_x"), self.v("Returns", "irr"), places=6)
        flows = [self.v("Returns", "cf", c) for c in COLS]
        self.assertAlmostEqual(flows[0], -self.v("Sources & Uses", "s_eq"), places=6)
        self.assertEqual(flows[1:-1], [0.0] * (len(flows) - 2))
        self.assertAlmostEqual(flows[-1], self.v("Returns", "eq_out"), places=6)

    def test_attribution_sums_to_equity_gain(self):
        parts = [self.v("Returns", k) for k in ("a_ebitda", "a_mult", "a_delev", "a_fees")]
        gain = self.v("Returns", "eq_out") - self.v("Sources & Uses", "s_eq")
        self.assertAlmostEqual(sum(parts), gain, places=6)
        self.assertAlmostEqual(self.v("Returns", "gain"), gain, places=6)
        self.assertLess(parts[3], 0)                       # fees are leakage
        self.assertGreater(parts[0], 0)                    # the synthetic company grows EBITDA
        self.assertAlmostEqual(self.v("Returns", "a_diff"), 0.0, places=6)

    def test_entry_pricing_switch(self):
        s = self.s
        wb, meta = lbo.build_workbook(s, market=MARKET, assumptions={"entry_mode": 2, "entry_mult": 9.0})
        b = read(wb.to_bytes())
        R = meta["rows"]
        ev, ltm = b.value("Sources & Uses", f"C{R['Sources & Uses']['ev']}"), b.value("Sources & Uses", f"C{R['Sources & Uses']['ltm']}")
        self.assertAlmostEqual(ev / ltm, 9.0, places=6)
        self.assertEqual(b.value("Checks", f"C{R['Checks']['master']}"), "OK")


class DebtTests(LboBase):
    def d(self, key, t):
        return self.b.value("Debt", f"{COLS[t]}{self.R['Debt'][key]}")

    def test_pik_principal_grows_by_the_pik_rate(self):
        rate = self.b.value("Assumptions", f"E{self.R['Assumptions']['t_pik']}")
        self.assertAlmostEqual(rate, 0.12)
        for t in range(1, 6):
            self.assertAlmostEqual(self.d("pik_end", t), self.d("pik_end", t - 1) * (1 + rate), places=6)
        self.assertGreater(self.d("pik_end", 5), self.d("pik_end", 0))
        # PIK is non-cash: it is in debt and taxable income, but not in the cash interest line
        for t in range(1, 6):
            cash_int = self.d("int_rev", t) + self.d("int_tlb", t) + self.d("int_sn", t)
            self.assertAlmostEqual(self.d("int_total", t), cash_int, places=6)

    def test_sweep_pays_tlb_only_from_excess_cash(self):
        sweep_pct = self.b.value("Assumptions", f"G{self.R['Assumptions']['t_tlb']}")
        minc = self.b.value("Assumptions", f"C{self.R['Assumptions']['min_cash']}")
        for t in range(1, 6):
            pre = self.d("cash", t - 1) + self.d("lfcf", t) - self.d("tlb_mand", t)
            excess = max(pre - minc + self.d("rev_chg", t), 0.0)
            self.assertAlmostEqual(self.d("tlb_sweep", t), min(self.d("tlb_open", t) - self.d("tlb_mand", t), sweep_pct * excess), places=6)
            self.assertAlmostEqual(self.d("tlb_end", t), self.d("tlb_open", t) - self.d("tlb_mand", t) - self.d("tlb_sweep", t), places=6)
            self.assertGreaterEqual(self.d("cash", t), minc - 1e-6)
            self.assertGreaterEqual(self.d("tlb_end", t), -1e-9)
        self.assertGreater(sum(self.d("tlb_sweep", t) for t in range(1, 6)), 0)
        # notes are a bullet: untouched
        self.assertAlmostEqual(self.d("sn_end", 5), self.d("sn_end", 0), places=6)

    def test_no_sweep_when_sweep_percent_zero_and_revolver_covers_shortfall(self):
        wb, meta = lbo.build_workbook(self.s, market=MARKET, assumptions={"tlb_sweep": 0.0})
        b = read(wb.to_bytes())
        R = meta["rows"]["Debt"]
        for c in COLS[1:]:
            self.assertAlmostEqual(b.value("Debt", f"{c}{R['tlb_sweep']}"), 0.0, places=9)
        self.assertGreater(b.value("Debt", f"H{R['cash']}"), b.value("Debt", f"C{R['cash']}"))      # cash builds instead
        # a punishing case: no cash flow, revolver must draw to hold minimum cash
        wb2, meta2 = lbo.build_workbook(self.s, market=MARKET, assumptions={"margin": [0.05] * 5, "tlb_sweep": 1.0})
        b2 = read(wb2.to_bytes())
        R2 = meta2["rows"]["Debt"]
        self.assertGreater(max(b2.value("Debt", f"{c}{R2['rev_end']}") for c in COLS[1:]), 0.0)
        self.assertEqual(b2.value("Checks", f"C{meta2['rows']['Checks']['master']}"), "OK")

    def test_credit_statistics(self):
        lev0 = self.d("lev", 0)
        self.assertAlmostEqual(lev0, 5.0, places=6)         # 3.0x + 1.5x + 0.5x at default sizing
        self.assertAlmostEqual(self.out("lbo.total_leverage_entry"), lev0, places=9)
        self.assertGreater(self.d("cov", 1), 1.0)


class SensitivityTests(LboBase):
    def test_centre_cells_equal_base_case(self):
        c = self.meta["centres"]
        self.assertAlmostEqual(self.b.value("Sensitivity", c["irr"]), self.out("lbo.irr"), places=9)
        self.assertAlmostEqual(self.b.value("Sensitivity", c["mom"]), self.out("lbo.mom"), places=9)
        self.assertAlmostEqual(self.b.value("Sensitivity", c["margin_irr"]), self.out("lbo.irr"), places=9)

    def test_grid_is_monotonic(self):
        c = self.meta["centres"]
        col, row = c["irr"][0], int(c["irr"][1:])
        # IRR rises with the exit multiple (columns) and falls with the entry multiple (rows)
        cols = [self.b.value("Sensitivity", f"{k}{row}") for k in "DEFGH"]
        rows = [self.b.value("Sensitivity", f"{col}{row + k}") for k in range(-2, 3)]
        self.assertEqual(cols, sorted(cols))
        self.assertEqual(rows, sorted(rows, reverse=True))

    def test_sensitivity_matches_a_full_rebuild(self):
        # moving the entry multiple one step is exactly a rebuild priced by multiple (debt is sized on EBITDA, so the closed form is exact)
        R = self.R["Assumptions"]
        base_mult = self.v("Sources & Uses", "mult")
        step = self.b.value("Assumptions", f"C{R['entry_step']}")
        c = self.meta["centres"]
        row = int(c["irr"][1:])
        grid_irr = self.b.value("Sensitivity", f"{c['irr'][0]}{row + 1}")
        wb, meta = lbo.build_workbook(self.s, market=MARKET, assumptions={"entry_mode": 2, "entry_mult": base_mult + step})
        b2 = read(wb.to_bytes())
        o = next(o for o in meta["outputs"] if o["id"] == "lbo.irr")
        self.assertAlmostEqual(b2.value(o["sheet"], o["ref"]), grid_irr, places=6)


class CircularityTests(LboBase):
    def test_circ_on_converges_and_differs_only_slightly(self):
        wb0, m0 = lbo.build_workbook(self.s, market=MARKET, circ=0)
        b0 = read(wb0.to_bytes())
        self.assertTrue(m0["converged"])
        self.assertTrue(self.meta["converged"])
        irr1, irr0 = self.out("lbo.irr"), b0.value("Returns", f"C{m0['rows']['Returns']['irr']}")
        self.assertNotEqual(irr1, irr0)
        self.assertLess(abs(irr1 - irr0), 0.01)
        self.assertEqual(b0.value("Checks", f"C{m0['rows']['Checks']['master']}"), "OK")

    def test_circ_zero_has_no_circular_dependency_in_the_values(self):
        # at Circ=0 interest uses opening balances: year-1 interest equals opening balance x rate exactly
        wb0, m0 = lbo.build_workbook(self.s, market=MARKET, circ=0)
        b0 = read(wb0.to_bytes())
        R = m0["rows"]["Debt"]
        rate = b0.value("Assumptions", f"D{m0['rows']['Assumptions']['t_tlb']}")
        for t, c in enumerate(COLS[1:], start=1):
            self.assertAlmostEqual(b0.value("Debt", f"{c}{R['int_tlb']}"), b0.value("Debt", f"{c}{R['tlb_open']}") * rate, places=9)

    def test_rejects_missing_market(self):
        with self.assertRaises(ValueError):
            lbo.build_workbook(self.s, market={})


if __name__ == "__main__":
    unittest.main()
