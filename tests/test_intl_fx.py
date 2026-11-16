"""S8.6a: IntlFX, translation and calendarisation. Offline; rates from committed fixtures."""
import csv
import os
import tempfile
import unittest
from datetime import date

from om.intl import calendar as cal
from om.intl.fx import IntlFX, fy_start, translate
from om.statements import Item, Statements


def _fixture_csv():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "fx.csv")
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "ccy", "end", "avg", "source"])
        for m in range(1, 13):
            w.writerow([f"2023-{m:02d}", "EGP", 32 if m == 12 else 30, 25, "fixture"])
        w.writerow(["2022-12", "EGP", 30, 25, "fixture"])
    return p


def _stm(currency="EGP", years=(date(2023, 12, 31),)):
    data = {"cash": [Item(320.0)], "revenue": [Item(250.0)], "eps_diluted": [Item(2.5)], "diluted_shares": [Item(100.0)],
            "x.eosb": [Item(64.0)], "x.employee_costs": [Item(50.0)], "ebit": [Item(None)]}
    return Statements("T", "T", 0, currency, list(years), data, [{}], [])


class TestFX(unittest.TestCase):
    def setUp(self):
        self.fx = IntlFX(_fixture_csv())
        self.real = IntlFX()  # committed IMF IFS file

    def test_rate_month_end_and_prior(self):
        self.assertEqual(self.real.rate("EGP", date(2024, 3, 31)), 47.16)
        self.assertEqual(self.real.rate("EGP", date(2024, 3, 15)), 30.8414)  # prior month end (Feb)
        self.assertIsNone(self.real.rate("EGP", date(2010, 1, 31)))

    def test_pegs(self):
        self.assertEqual(self.fx.rate("SAR", date(2023, 6, 30)), 3.75)
        self.assertAlmostEqual(self.fx.average("AED", date(2023, 1, 1), date(2023, 12, 31)), 3.6725)
        self.assertEqual(self.fx.rate("USD", date(2023, 6, 30)), 1.0)

    def test_average_day_weighted(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "f.csv")
        with open(p, "w") as fh:
            fh.write("month,ccy,end,avg,source\n2023-01,EGP,1,10,x\n2023-02,EGP,1,20,x\n")
        fx = IntlFX(p)
        self.assertAlmostEqual(fx.average("EGP", date(2023, 1, 1), date(2023, 2, 28)), (31 * 10 + 28 * 20) / 59)
        self.assertIsNone(fx.average("EGP", date(2023, 1, 1), date(2023, 3, 31)))  # March missing

    def test_devaluation_events(self):
        def months(a, b):
            return [f["date"] for f in self.real.devaluation_flags("EGP", a, b)]
        self.assertIn(date(2016, 11, 30), months(date(2016, 1, 1), date(2016, 12, 31)))
        self.assertIn(date(2022, 3, 31), months(date(2022, 1, 1), date(2022, 6, 30)))
        late = months(date(2022, 7, 1), date(2023, 6, 30))
        self.assertIn(date(2022, 10, 31), late)
        self.assertIn(date(2023, 1, 31), late)
        f = self.real.devaluation_flags("EGP", date(2024, 1, 1), date(2024, 6, 30))
        self.assertEqual([x["date"] for x in f], [date(2024, 3, 31)])
        self.assertAlmostEqual(f[0]["pct_move"], 47.16 / 30.8414 - 1)
        self.assertEqual(f[0]["flag"], "devaluation")

    def test_no_flag_for_calm_period_or_peg(self):
        self.assertEqual(self.real.devaluation_flags("EGP", date(2019, 1, 1), date(2019, 12, 31)), [])
        self.assertEqual(self.real.devaluation_flags("SAR", date(2015, 1, 1), date(2024, 12, 31)), [])

    def test_fy_start(self):
        self.assertEqual(fy_start(date(2024, 6, 30)), date(2023, 7, 1))
        self.assertEqual(fy_start(date(2023, 12, 31)), date(2023, 1, 1))

    def test_translate_bs_end_flows_average(self):
        t = translate(_stm(), "USD", self.fx)
        self.assertAlmostEqual(t.data["cash"][0].value, 320 / 32)      # period-end 32
        self.assertAlmostEqual(t.data["x.eosb"][0].value, 64 / 32)     # x. stock at end rate
        self.assertAlmostEqual(t.data["revenue"][0].value, 250 / 25)   # average 25
        self.assertAlmostEqual(t.data["x.employee_costs"][0].value, 2.0)
        self.assertAlmostEqual(t.data["eps_diluted"][0].value, 0.1)    # EPS at the average
        self.assertEqual(t.data["diluted_shares"][0].value, 100.0)     # share count unchanged
        self.assertIsNone(t.data["ebit"][0].value)
        self.assertEqual(t.currency, "USD")
        self.assertEqual(_stm().data["cash"][0].value, 320.0)          # original untouched

    def test_translate_to_peg_currency(self):
        t = translate(_stm(), "SAR", self.fx)
        self.assertAlmostEqual(t.data["cash"][0].value, 320 / 32 * 3.75)

    def test_translate_flags_devaluation_for_spanning_period(self):
        s = _stm(years=(date(2024, 6, 30),))
        t = translate(s, "USD", self.real)
        self.assertTrue(any(f["flag"] == "devaluation" and f["date"] == date(2024, 3, 31) for f in t.fx_flags))
        self.assertTrue(any("devaluation" in w for w in t.warnings))
        s2 = _stm(years=(date(2019, 12, 31),))
        self.assertFalse(translate(s2, "USD", self.real).fx_flags)

    def test_translate_missing_rate_leaves_none(self):
        t = translate(_stm(years=(date(2008, 12, 31),)), "USD", self.real)
        self.assertIsNone(t.data["cash"][0].value)
        self.assertTrue(any(f["flag"] == "fx_rate_missing" for f in t.fx_flags))


class TestCalendar(unittest.TestCase):
    def test_june_to_december(self):
        r = cal.calendarise({date(2023, 6, 30): 100.0, date(2024, 6, 30): 200.0})
        self.assertEqual(r, {date(2023, 12, 31): 6 / 12 * 100 + 6 / 12 * 200})
        w = cal.weights(6)
        self.assertEqual((w["fy_before_target"], w["fy_after_target"]), (0.5, 0.5))

    def test_june_three_years(self):
        r = cal.calendarise({date(2022, 6, 30): 80.0, date(2023, 6, 30): 100.0, date(2024, 6, 30): 200.0})
        self.assertEqual(r[date(2022, 12, 31)], 90.0)
        self.assertEqual(r[date(2023, 12, 31)], 150.0)

    def test_march_to_december(self):
        r = cal.calendarise({date(2023, 3, 31): 100.0, date(2024, 3, 31): 200.0})
        self.assertEqual(r, {date(2023, 12, 31): 3 / 12 * 100 + 9 / 12 * 200})
        w = cal.weights(3)
        self.assertEqual((w["fy_before_target"], w["fy_after_target"]), (0.25, 0.75))

    def test_december_unchanged_and_other_target(self):
        self.assertEqual(cal.calendarise({date(2023, 12, 31): 5.0}), {date(2023, 12, 31): 5.0})
        r = cal.calendarise({date(2023, 12, 31): 100.0, date(2024, 12, 31): 200.0}, target_month=6)
        self.assertEqual(r, {date(2024, 6, 30): 150.0})

    def test_stock_nearest_no_weighting(self):
        r = cal.calendarise({date(2023, 6, 30): 100.0, date(2024, 6, 30): 200.0}, kind="stock")
        self.assertEqual(r[date(2023, 12, 31)], 100.0)  # tie: earlier period end
        r = cal.calendarise({date(2023, 3, 31): 100.0, date(2024, 3, 31): 200.0}, kind="stock")
        self.assertEqual(r[date(2023, 12, 31)], 200.0)  # Mar 2024 is 3 months away, Mar 2023 is 9

    def test_gap_and_mixed_month_rejected(self):
        self.assertEqual(cal.calendarise({date(2023, 6, 30): 1.0, date(2025, 6, 30): 2.0}), {})
        with self.assertRaises(ValueError):
            cal.calendarise({date(2023, 6, 30): 1.0, date(2024, 3, 31): 2.0})


if __name__ == "__main__":
    unittest.main()
