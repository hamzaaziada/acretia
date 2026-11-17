"""S8.2 IFRS concept mapping."""
import unittest

from om.concepts import I
from om.intl import concepts as C
from om.intl import labels as L
from om.statements import LINES

# LINES chains that S8.2 deliberately maps to a more specific key
KNOWN_RESPLIT = {"ProfitLoss": "cf_net_income", "SellingExpense": "x.selling_expenses",
                 "AdministrativeExpense": "x.admin_expenses", "DepreciationExpense": "da"}


class TestConcepts(unittest.TestCase):
    def test_every_lines_ifrs_concept_resolves(self):
        n = 0
        for key, (_st, _k, _s, _l, chain) in LINES.items():
            flat = [c for part in chain for c in part] if chain and isinstance(chain[0], list) else chain
            for tax, name in flat:
                if tax != I:
                    continue
                got = C.concept_to_key(f"ifrs-full:{name}")
                want = KNOWN_RESPLIT.get(name, key)
                self.assertEqual(got, want, (key, name))
                n += 1
        self.assertGreater(n, 40)

    def test_qname_forms(self):
        for q in ["ifrs-full:Revenue", "ifrs-full_Revenue", "{https://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full}Revenue",
                  "{http://xbrl.ifrs.org/taxonomy/2021-03-24/ifrs-full}Revenue", "ifrs_full:Revenue", "Revenue"]:
            self.assertEqual(C.concept_to_key(q), "revenue", q)

    def test_named_concepts(self):
        want = {
            "Revenue": "revenue", "CostOfSales": "cogs", "GrossProfit": "gross_profit",
            "ProfitLossFromOperatingActivities": "ebit", "ProfitLossBeforeTax": "pretax",
            "IncomeTaxExpenseContinuingOperations": "tax", "ProfitLoss": "cf_net_income",
            "ProfitLossAttributableToOwnersOfParent": "net_income",
            "ProfitLossAttributableToNoncontrollingInterests": "x.nci_profit", "DistributionCosts": "x.selling_expenses",
            "AdministrativeExpense": "x.admin_expenses", "OtherIncome": "x.other_income", "FinanceCosts": "interest_expense",
            "FinanceIncome": "interest_income",
            "ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod": "x.share_of_associates",
            "EmployeeBenefitsExpense": "x.employee_costs", "RawMaterialsAndConsumablesUsed": "x.raw_materials",
            "DepreciationAndAmortisationExpense": "da", "RightofuseAssets": "x.rou_assets",
            "InvestmentProperty": "x.investment_property", "NoncurrentAssets": "x.noncurrent_assets",
            "NoncurrentLiabilities": "x.noncurrent_liabilities", "IssuedCapital": "x.share_capital",
            "RetainedEarnings": "x.retained_earnings", "NoncontrollingInterests": "x.nci_equity",
            "CashFlowsFromUsedInOperatingActivities": "cfo",
            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "capex",
            "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities": "x.lease_payments",
            "EffectOfExchangeRateChangesOnCashAndCashEquivalents": "x.fx_effect_cash",
            "OtherComprehensiveIncome": "x.oci_total", "ComprehensiveIncome": "x.total_comprehensive_income",
            "BasicEarningsLossPerShare": "x.eps_basic", "DilutedEarningsLossPerShare": "eps_diluted",
            "CurrentLeaseLiabilities": "x.lease_liabilities_current", "NoncurrentLeaseLiabilities": "x.lease_liabilities_noncurrent",
            "Assets": "assets", "CurrentAssets": "current_assets", "Liabilities": "liabilities", "Equity": "equity_total",
        }
        for name, key in want.items():
            self.assertEqual(C.concept_to_key(f"ifrs-full:{name}"), key, name)

    def test_unknown(self):
        self.assertIsNone(C.concept_to_key("ifrs-full:NoSuchElement"))
        self.assertIsNone(C.concept_to_key(""))
        self.assertIsNone(C.concept_to_key("us-gaap:Revenues"))

    def test_extension_fallback_via_label(self):
        self.assertEqual(C.concept_to_key("egx:NetSalesAndServices", label="Net sales"), "revenue")
        self.assertEqual(C.concept_to_key("{http://example.com/tax}ZakatCharge", label="Zakat expense"), "x.zakat")
        self.assertEqual(C.concept_to_key("tadawul:X", label="Total non-current assets"), "x.noncurrent_assets")
        self.assertIsNone(C.concept_to_key("egx:Foo", label="Weather forecast"))
        self.assertIsNone(C.concept_to_key("egx:Foo"))
        # ifrs-full concept not in the table is not guessed from a label unless one is given
        self.assertEqual(C.concept_to_key("ifrs-full:SomeNewElement", label="Net sales"), "revenue")

    def test_key_to_concepts(self):
        self.assertEqual(C.key_to_concepts("revenue")[0], "ifrs-full:Revenue")
        self.assertIn("ifrs-full:ProfitLossBeforeTax", C.key_to_concepts("pretax"))
        self.assertEqual(C.key_to_concepts("nope"), [])
        for q in C.key_to_concepts("cfo"):
            self.assertEqual(C.concept_to_key(q), "cfo")

    def test_roundtrip_and_known_keys(self):
        valid = set(LINES) | set(L.EXTRA_KEYS)
        for concept, key in C.IFRS_TO_KEY.items():
            self.assertIn(key, valid, concept)
            self.assertIn(f"ifrs-full:{concept}", C.key_to_concepts(key))

    def test_every_extra_key_has_a_concept_or_is_documented(self):
        # keys with no ifrs-full line item of their own are allowed to be label-only
        label_only = {"x.zakat_none"}
        for key in L.EXTRA_KEYS:
            if key in label_only:
                continue
            self.assertTrue(C.key_to_concepts(key), key)


if __name__ == "__main__":
    unittest.main()
