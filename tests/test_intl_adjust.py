"""S8.6a: analyst adjustment recipes, hand-computed numbers."""
import unittest

from om.intl.adjust import RECIPES

IDS = ["ifrs16_to_pre16_ebitda", "lease_adjusted_net_debt", "capitalise_operating_leases", "zakat_as_tax", "by_nature_ebit",
       "ias29_restate", "fx_translate_period_end_average", "devaluation_fx_loss_normalise", "eosb_as_debt_like",
       "dev_cost_expense", "revaluation_reverse", "impairment_reversal_strip", "capitalised_interest_expense", "lifo_to_fifo",
       "gov_grant_gross_up", "associates_share_strip", "revenue_principal_agent_net", "eas_to_ifrs_map"]


class TestRecipes(unittest.TestCase):
    def test_contract_ids_all_present(self):
        self.assertEqual(set(IDS), set(RECIPES))

    def test_by_nature_ebit(self):
        v = {"revenue": 1000.0, "x.raw_materials": 400.0, "x.employee_costs": 200.0, "x.depreciation": 50.0,
             "x.amortisation": 10.0, "x.other_opex": 90.0, "x.changes_in_inventories": 20.0, "x.other_income": 30.0}
        r = RECIPES["by_nature_ebit"](v)
        self.assertEqual(r["adjusted"]["ebit"], 1000 - 750 + 20 + 30)
        self.assertEqual(r["adjusted"]["ebitda"], 360.0)
        self.assertIn("computed_by_nature", r["flags"])
        self.assertEqual(r["adjusted"]["basis_flags"], {"ebit": "computed_by_nature"})
        r2 = RECIPES["by_nature_ebit"](v, other_income_operating=False)
        self.assertEqual(r2["adjusted"]["ebit"], 270.0)
        self.assertIsNone(RECIPES["by_nature_ebit"]({})["adjusted"]["ebit"])

    def test_ifrs16_pre16(self):
        v = {"ebitda": 500.0, "ebit": 300.0, "x.rou_depreciation": 80.0, "x.lease_interest": 20.0}
        r = RECIPES["ifrs16_to_pre16_ebitda"](v)
        self.assertEqual(r["adjusted"]["ebitda_pre16"], 400.0)
        self.assertEqual(r["adjusted"]["ebit_pre16"], 280.0)   # 300 - (100 - 80)
        self.assertIn("ifrs16_pre16_proxy", r["flags"])
        r = RECIPES["ifrs16_to_pre16_ebitda"](v, lease_payments=95.0)
        self.assertEqual(r["adjusted"]["ebitda_pre16"], 405.0)
        self.assertIn("ifrs16_pre16_lease_payments", r["flags"])
        self.assertIsNone(RECIPES["ifrs16_to_pre16_ebitda"]({"ebitda": 1.0})["adjusted"]["ebitda_pre16"])

    def test_ebitda_from_ebit_plus_da(self):
        v = {"ebit": 300.0, "da": 200.0, "x.rou_depreciation": 80.0, "x.lease_interest": 20.0}
        self.assertEqual(RECIPES["ifrs16_to_pre16_ebitda"](v)["adjusted"]["ebitda_pre16"], 400.0)

    def test_lease_adjusted_net_debt_toggle(self):
        v = {"debt_current": 100.0, "debt_noncurrent": 200.0, "cash": 150.0, "sti": 10.0,
             "x.lease_liabilities_current": 40.0, "x.lease_liabilities_noncurrent": 60.0}
        on = RECIPES["lease_adjusted_net_debt"](v, include_leases=True)
        off = RECIPES["lease_adjusted_net_debt"](v, include_leases=False)
        self.assertEqual(on["adjusted"]["net_debt"], 300 - 150 + 100)
        self.assertEqual(off["adjusted"]["net_debt"], 150.0)
        self.assertEqual(on["adjusted"]["net_debt_ex_leases"], 150.0)
        self.assertIn("leases_included", on["flags"])
        self.assertIn("leases_excluded", off["flags"])
        self.assertEqual(RECIPES["lease_adjusted_net_debt"](v, include_sti=True)["adjusted"]["net_debt"], 240.0)

    def test_capitalise_operating_leases(self):
        v = {"ebitda": 500.0, "ebit": 300.0, "debt_current": 0.0, "debt_noncurrent": 200.0, "cash": 50.0}
        r = RECIPES["capitalise_operating_leases"](v, operating_lease_liability=400.0, operating_lease_cost=90.0, discount_rate=0.05)
        a = r["adjusted"]
        self.assertEqual(a["lease_interest"], 20.0)
        self.assertEqual(a["lease_depreciation"], 70.0)
        self.assertEqual(a["ebitda"], 590.0)
        self.assertEqual(a["ebit"], 320.0)
        self.assertEqual(a["net_debt"], 200 + 400 - 50)

    def test_zakat_as_tax(self):
        v = {"pretax": 1000.0, "tax": 150.0, "x.zakat": 25.0}
        r = RECIPES["zakat_as_tax"](v)
        self.assertAlmostEqual(r["adjusted"]["effective_rate_incl_zakat"], 0.175)
        self.assertAlmostEqual(r["adjusted"]["effective_rate_ex_zakat"], 0.15)
        self.assertEqual(r["adjusted"]["total_tax_and_zakat"], 175.0)
        self.assertIn("zakat_in_tax_rate", r["flags"])
        r = RECIPES["zakat_as_tax"](v, zakat_included_in_tax=True)
        self.assertAlmostEqual(r["adjusted"]["effective_rate_incl_zakat"], 0.15)
        self.assertAlmostEqual(r["adjusted"]["effective_rate_ex_zakat"], 0.125)
        self.assertIsNone(RECIPES["zakat_as_tax"]({"pretax": -5.0, "tax": 1.0})["adjusted"]["effective_rate_incl_zakat"])

    def test_ias29(self):
        v = {"ppe": 100.0, "cash": 50.0, "revenue": 200.0, "eps_diluted": 1.0}
        r = RECIPES["ias29_restate"](v, cpi_from=100.0, cpi_to=125.0)
        self.assertEqual(r["adjusted"]["ppe"], 125.0)
        self.assertEqual(r["adjusted"]["revenue"], 250.0)
        self.assertEqual(r["adjusted"]["cash"], 50.0)   # monetary
        self.assertEqual(r["adjusted"]["eps_diluted"], 1.0)
        self.assertIn("ias29_restated", r["flags"])
        r = RECIPES["ias29_restate"](v, cpi_from=100.0, cpi_to=125.0, restate_keys=["ppe"])
        self.assertEqual(r["adjusted"]["revenue"], 200.0)
        self.assertIn("missing:cpi", RECIPES["ias29_restate"](v)["flags"])

    def test_fx_translate_recipe(self):
        v = {"cash": 320.0, "revenue": 250.0, "eps_diluted": 2.5, "diluted_shares": 100.0}
        a = RECIPES["fx_translate_period_end_average"](v, rate_end=32.0, rate_avg=25.0)["adjusted"]
        self.assertEqual((a["cash"], a["revenue"], a["eps_diluted"], a["diluted_shares"]), (10.0, 10.0, 0.1, 100.0))

    def test_devaluation_fx_loss(self):
        v = {"ebit": 300.0, "pretax": 250.0, "net_income": 200.0, "x.fx_gain_loss": -80.0}
        a = RECIPES["devaluation_fx_loss_normalise"](v)["adjusted"]
        self.assertEqual(a["ebit"], 380.0)
        self.assertEqual(a["recurring_pretax"], 330.0)
        self.assertEqual(a["recurring_net_income"], 280.0)
        a = RECIPES["devaluation_fx_loss_normalise"](v, fx_in_ebit=False, tax_rate=0.25)["adjusted"]
        self.assertEqual(a["ebit"], 300.0)
        self.assertEqual(a["recurring_net_income"], 260.0)

    def test_eosb(self):
        v = {"x.eosb": 40.0, "debt_current": 10.0, "debt_noncurrent": 90.0, "cash": 60.0}
        a = RECIPES["eosb_as_debt_like"](v)["adjusted"]
        self.assertEqual(a["net_debt_incl_eosb"], 40 + 40)
        self.assertEqual(RECIPES["eosb_as_debt_like"](v, tax_rate=0.25)["adjusted"]["eosb_debt_like"], 30.0)

    def test_dev_cost_expense(self):
        v = {"ebit": 300.0, "ebitda": 400.0, "capex": 120.0, "x.capitalised_dev": 30.0}
        a = RECIPES["dev_cost_expense"](v, dev_amortisation=10.0)["adjusted"]
        self.assertEqual((a["ebit"], a["ebitda"], a["capex"]), (280.0, 370.0, 90.0))

    def test_revaluation_and_impairment(self):
        v = {"ebit": 300.0, "pretax": 280.0, "net_income": 200.0}
        a = RECIPES["revaluation_reverse"](v, revaluation_gain=50.0, tax_rate=0.2)["adjusted"]
        self.assertEqual((a["ebit"], a["pretax"], a["net_income"]), (250.0, 230.0, 160.0))
        a = RECIPES["impairment_reversal_strip"](v, impairment_reversal=10.0)["adjusted"]
        self.assertEqual((a["ebit"], a["pretax"], a["net_income"]), (290.0, 270.0, 190.0))
        self.assertIn("missing:revaluation_gain", RECIPES["revaluation_reverse"](v)["flags"])

    def test_capitalised_interest(self):
        v = {"interest_expense": 40.0, "pretax": 200.0, "capex": 150.0}
        a = RECIPES["capitalised_interest_expense"](v, capitalised_interest=12.0)["adjusted"]
        self.assertEqual((a["interest_expense"], a["pretax"], a["capex"]), (52.0, 188.0, 138.0))

    def test_lifo_to_fifo(self):
        v = {"inventory": 500.0, "cogs": 800.0, "ebit": 200.0, "pretax": 180.0, "net_income": 140.0}
        a = RECIPES["lifo_to_fifo"](v, lifo_reserve=60.0, prior_lifo_reserve=40.0, tax_rate=0.25)["adjusted"]
        self.assertEqual((a["inventory"], a["cogs"], a["ebit"], a["pretax"], a["net_income"]), (560.0, 780.0, 220.0, 200.0, 155.0))

    def test_gov_grants(self):
        v = {"cogs": 700.0, "ebit": 200.0, "x.gov_grants": 15.0}
        a = RECIPES["gov_grant_gross_up"](v)["adjusted"]
        self.assertEqual((a["cogs"], a["ebit"], a["ebit_ex_grants"], a["x.gov_grants_income"]), (715.0, 200.0, 185.0, 15.0))

    def test_associates(self):
        v = {"ebit": 300.0, "net_income": 200.0, "x.share_of_associates": 25.0}
        self.assertEqual(RECIPES["associates_share_strip"](v)["adjusted"]["net_income_ex_associates"], 175.0)
        self.assertEqual(RECIPES["associates_share_strip"](v, in_ebit=True)["adjusted"]["ebit"], 275.0)
        self.assertEqual(RECIPES["associates_share_strip"](v)["adjusted"]["ebit"], 300.0)

    def test_principal_agent(self):
        v = {"revenue": 1000.0, "cogs": 800.0, "ebit": 100.0}
        a = RECIPES["revenue_principal_agent_net"](v, agent_amount=400.0)["adjusted"]
        self.assertEqual((a["revenue"], a["cogs"], a["ebit"]), (600.0, 400.0, 100.0))
        self.assertAlmostEqual(a["ebit_margin"], 100 / 600)

    def test_eas_to_ifrs(self):
        v = {"ppe": 1000.0, "equity_parent": 800.0, "assets": 2000.0, "liabilities": 1200.0}
        r = RECIPES["eas_to_ifrs_map"](v, fx_loss_capitalised=60.0, rou_asset=100.0, lease_liability=110.0, adjustments={"ar": -5.0})
        a = r["adjusted"]
        self.assertEqual((a["ppe"], a["equity_parent"], a["assets"], a["liabilities"], a["ar"]), (940.0, 740.0, 2100.0, 1310.0, -5.0))
        self.assertIn("eas_fx_capitalisation_reversed", r["flags"])

    def test_every_recipe_contract_shape_and_no_mutation(self):
        rich = {"revenue": 1000.0, "cogs": 800.0, "ebit": 200.0, "ebitda": 300.0, "pretax": 180.0, "tax": 30.0, "net_income": 150.0,
                "cash": 100.0, "debt_current": 20.0, "debt_noncurrent": 80.0, "inventory": 50.0, "capex": 40.0,
                "interest_expense": 10.0, "ppe": 500.0, "x.zakat": 5.0, "x.eosb": 7.0, "x.fx_gain_loss": -3.0}
        params = {"ias29_restate": dict(cpi_from=1.0, cpi_to=1.1), "fx_translate_period_end_average": dict(rate_end=2.0, rate_avg=2.0),
                  "lifo_to_fifo": dict(lifo_reserve=5.0), "revaluation_reverse": dict(revaluation_gain=1.0),
                  "impairment_reversal_strip": dict(impairment_reversal=1.0), "capitalised_interest_expense": dict(capitalised_interest=1.0),
                  "revenue_principal_agent_net": dict(agent_amount=10.0)}
        for rid, fn in RECIPES.items():
            snap = dict(rich)
            r = fn(rich, **params.get(rid, {}))
            self.assertEqual(rich, snap, rid)
            self.assertEqual(set(r), {"adjusted", "flags", "explain"}, rid)
            self.assertIsInstance(r["adjusted"], dict)
            self.assertIsInstance(r["flags"], list)
            self.assertTrue(r["explain"] and isinstance(r["explain"], str), rid)
            fn({})  # empty input must not raise


if __name__ == "__main__":
    unittest.main()
