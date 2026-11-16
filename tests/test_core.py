"""Offline unit tests: period logic, point-in-time gating, EV bridge and n/m rules.
Run: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.facts import Company  # noqa: E402
from om.metrics import compute  # noqa: E402
from om.prices import Quote  # noqa: E402


def f(val, start, end, filed, form="10-Q", accn="a"):
    return {"val": val, "start": start, "end": end, "filed": filed, "form": form, "accn": accn}


def inst(val, end, filed, form="10-Q"):
    return {"val": val, "end": end, "filed": filed, "form": form, "accn": "b"}


def cf(**concepts):
    us = {}
    for name, (unit, rows) in concepts.items():
        us[name] = {"units": {unit: rows}}
    return {"cik": 1, "entityName": "TestCo", "facts": {"us-gaap": us}}


REV = [
    f(1000, "2024-01-01", "2024-12-31", "2025-02-20", "10-K"),
    f(1200, "2025-01-01", "2025-12-31", "2026-02-20", "10-K"),
    f(600, "2025-01-01", "2025-06-30", "2025-08-01"),     # prior H1 YTD
    f(700, "2026-01-01", "2026-06-30", "2026-08-01"),     # current H1 YTD
]


class PeriodTests(unittest.TestCase):
    def test_ltm_from_fy_plus_ytd(self):
        c = Company(cf(Revenues=("USD", REV)))
        v = c.ltm("revenue")
        self.assertEqual(v.val, 1200 + 700 - 600)
        self.assertEqual(v.basis, "fy+ytd-ytd_prior")

    def test_ltm_equals_fy_after_annual_report(self):
        c = Company(cf(Revenues=("USD", REV[:2])))
        self.assertEqual(c.ltm("revenue").val, 1200)

    def test_point_in_time_hides_later_filings(self):
        c = Company(cf(Revenues=("USD", REV)), as_of=date(2026, 3, 1))
        self.assertEqual(c.ltm("revenue").val, 1200)      # H1-2026 10-Q not yet filed
        c2 = Company(cf(Revenues=("USD", REV)), as_of=date(2025, 9, 1))
        self.assertEqual(c2.fy("revenue").val, 1000)       # FY2025 10-K filed 2026-02-20, not visible yet
        v2 = c2.ltm("revenue")                              # H1-2024 YTD missing -> falls back to FY, says so
        self.assertEqual((v2.val, v2.basis), (1000, "fy_only"))

    def test_restatement_latest_vs_first(self):
        rows = REV[:2] + [f(1250, "2025-01-01", "2025-12-31", "2026-05-01", "10-K/A")]
        c = Company(cf(Revenues=("USD", rows)))
        self.assertEqual(c.fy("revenue").val, 1250)
        self.assertEqual(c.facts("revenue", "first")[(date(2025, 1, 1), date(2025, 12, 31))].val, 1200)

    def test_quarter_sum_when_no_ytd_tag(self):
        rows = [f(1200, "2025-01-01", "2025-12-31", "2026-02-20", "10-K"),
                f(250, "2025-01-01", "2025-03-31", "2025-05-01"), f(260, "2025-04-01", "2025-06-30", "2025-08-01"),
                f(300, "2026-01-01", "2026-03-31", "2026-05-01"), f(320, "2026-04-01", "2026-06-30", "2026-08-01")]
        v = Company(cf(Revenues=("USD", rows))).ltm("revenue")
        self.assertEqual(v.val, 1200 + 620 - 510)
        self.assertIn("quarter_sum", v.basis)

    def test_single_tag_preferred_over_mixing(self):
        rows_a = [f(1200, "2025-01-01", "2025-12-31", "2026-02-20", "10-K")]
        rows_b = [f(1190, "2025-01-01", "2025-12-31", "2026-02-20", "10-K"),
                  f(600, "2025-01-01", "2025-06-30", "2025-08-01"), f(700, "2026-01-01", "2026-06-30", "2026-08-01")]
        data = cf(Revenues=("USD", rows_a), RevenuesNetOfInterestExpense=("USD", rows_b))
        v = Company(data).ltm("revenue")
        self.assertEqual(v.val, 1190 + 100)  # all three periods from the same tag


class MetricTests(unittest.TestCase):
    def base(self, ebit_val=300):
        return cf(
            Revenues=("USD", REV[:2]),
            OperatingIncomeLoss=("USD", [f(ebit_val, "2025-01-01", "2025-12-31", "2026-02-20", "10-K")]),
            DepreciationDepletionAndAmortization=("USD", [f(50, "2025-01-01", "2025-12-31", "2026-02-20", "10-K")]),
            NetIncomeLoss=("USD", [f(200, "2025-01-01", "2025-12-31", "2026-02-20", "10-K")]),
            Assets=("USD", [inst(5000, "2025-12-31", "2026-02-20", "10-K")]),
            Liabilities=("USD", [inst(3000, "2025-12-31", "2026-02-20", "10-K")]),
            StockholdersEquity=("USD", [inst(2000, "2025-12-31", "2026-02-20", "10-K")]),
            LongTermDebt=("USD", [inst(800, "2025-12-31", "2026-02-20", "10-K")]),
            CashAndCashEquivalentsAtCarryingValue=("USD", [inst(300, "2025-12-31", "2026-02-20", "10-K")]),
            CommonStockSharesOutstanding=("shares", [inst(100, "2025-12-31", "2026-02-20", "10-K")]),
        )

    def test_ev_bridge_and_multiples(self):
        row, prov = compute(self.base(), {"sic": "7372"}, Quote("T", 20.0, "USD", date(2026, 3, 1), "test"), None)
        self.assertAlmostEqual(row["market_cap_lcu"] * 1e6, 2000)
        self.assertAlmostEqual(row["enterprise_value_lcu"] * 1e6, 2000 + 800 - 300)
        self.assertAlmostEqual(row["ev_ebitda_ltm"], 2500 / 350)
        self.assertAlmostEqual(row["revenue_growth_fy"], 20.0)
        self.assertTrue(row["check_balance_sheet"])
        self.assertIn("ebitda_ltm_lcu", prov)

    def test_nm_rule_negative_and_above_250(self):
        row, _ = compute(self.base(ebit_val=-100), {"sic": "7372"}, Quote("T", 20.0, "USD", date(2026, 3, 1), "test"), None)
        self.assertIsNone(row["ev_ebit_ltm"])
        self.assertIn("ev_ebit_ltm", row["nm_fields"])
        row2, _ = compute(self.base(ebit_val=1), {"sic": "7372"}, Quote("T", 20.0, "USD", date(2026, 3, 1), "test"), None)
        self.assertIsNone(row2["ev_ebit_ltm"])  # 2500 / 1 > 250x

    def test_financial_format_ev_equals_market_cap(self):
        row, _ = compute(self.base(), {"sic": "6021"}, Quote("T", 20.0, "USD", date(2026, 3, 1), "test"), None)
        self.assertAlmostEqual(row["enterprise_value_lcu"], row["market_cap_lcu"])
        self.assertIsNone(row["ev_ebitda_ltm"])


if __name__ == "__main__":
    unittest.main()
