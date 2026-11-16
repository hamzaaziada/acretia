"""Offline tests for the M&A precedent-transactions parser. Run: python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import ma  # noqa: E402

META = {"accession": "0000000000-26-000001", "url": "https://example/doc.htm", "company": "TargetCo",
        "cik": 1, "form": "DEFM14A", "filed": "2026-10-01"}

DOC = """
<html><body>
<p><b>Selected Precedent Transactions Analysis</b></p>
<p>Bank One reviewed certain information relating to the following selected transactions.</p>
<table>
<tr><td></td><td>Date Announced</td><td></td><td>Target</td><td></td><td>Acquiror</td><td>EV/LTM<br>Revenue</td><td>EV/NTM EBITDA</td></tr>
<tr><td></td><td>November 2025</td><td></td><td>Alpha Corp.</td><td></td><td>Beta Inc.</td><td>6.3</td><td>x</td><td>NM</td></tr>
<tr><td></td><td>Mar-21</td><td></td><td>Gamma, Inc.</td><td></td><td>Delta Holdings plc</td><td>$</td><td>9.7x</td><td>21.4x</td></tr>
<tr><td>Median</td><td>8.0x</td><td>21.4x</td></tr>
</table>
<p>Bank One selected a reference range of EV/LTM Revenue multiples of 5.0x to 9.0x derived from the selected transactions.</p>
<p><b>Discounted Cash Flow Analysis</b></p>
<table><tr><td>Target</td><td>Acquiror</td><td>EV/Revenue</td></tr><tr><td>Should</td><td>Not</td><td>1.0x</td></tr></table>
</body></html>
"""


class MaParserTests(unittest.TestCase):
    def setUp(self):
        self.obs, self.an = ma.extract(DOC, META)

    def test_finds_one_analysis_and_stops_at_next_section(self):
        self.assertEqual(len(self.an), 1)
        self.assertEqual(self.an[0].advisor, "Bank One")
        self.assertEqual(self.an[0].n_deals, 2)

    def test_reference_range(self):
        rr = self.an[0].reference_range
        self.assertEqual((rr["low"], rr["high"], rr["metric"], rr["period"]), (5.0, 9.0, "revenue", "ltm"))

    def test_values_and_glued_cells(self):
        alpha = [o for o in self.obs if o.target == "Alpha Corp."]
        rev = [o for o in alpha if o.metric == "revenue"][0]
        self.assertEqual((rev.value, rev.period, rev.numerator, rev.announced), (6.3, "ltm", "ev", "2025-11"))
        ebitda = [o for o in alpha if o.metric == "ebitda"][0]
        self.assertTrue(ebitda.nm)
        self.assertIsNone(ebitda.value)

    def test_short_date_and_summary(self):
        gamma = [o for o in self.obs if o.target == "Gamma, Inc."]
        self.assertEqual(gamma[0].announced, "2021-03")
        self.assertEqual(self.an[0].summary["median"]["EV/NTM EBITDA"], 21.4)

    def test_consolidate_merges_same_deal_across_filings(self):
        other = dict(META, accession="0000000000-26-000002", url="https://example/other.htm")
        obs2, _ = ma.extract(DOC.replace("6.3", "6.5"), other)
        deals = ma.consolidate(self.obs + obs2)
        alpha = [d for d in deals if d["target"] == "Alpha Corp."][0]
        self.assertEqual(alpha["n_filings"], 2)
        self.assertAlmostEqual(alpha["ev_revenue_ltm"], 6.4)

    def test_dates_with_day(self):
        self.assertEqual(ma.parse_date("December 31, 2021"), "2021-12")
        self.assertEqual(ma.parse_date("12/31/2021"), "2021-12")
        self.assertEqual(ma.parse_date("Mar-21"), "2021-03")
        self.assertEqual(ma.parse_date("2019"), "2019")

    def test_amount_vs_multiple_columns(self):
        self.assertEqual(ma.column_kind("Acquisition Price", "$165.0"), "amount")
        self.assertEqual(ma.column_kind("Target Revenues", "$23.0"), "amount")
        self.assertEqual(ma.column_kind("Price to Revenues", "7.2"), "multiple")
        self.assertEqual(ma.classify_header("Acquisition Price", "amount"), ("deal_value", "unspecified", None))
        self.assertEqual(ma.classify_header("Price / Tangible Book Value"), ("tangible_book", "unspecified", "equity"))
        self.assertEqual(ma.classify_header("Core Deposit Premium"), ("core_deposit_premium", "unspecified", None))

    def test_classify_header(self):
        self.assertEqual(ma.classify_header("TEV / CY2026E EBITDA"), ("ebitda", "cy2026", "ev"))
        self.assertEqual(ma.classify_header("Transaction Value / LTM Sales"), ("revenue", "ltm", "ev"))


if __name__ == "__main__":
    unittest.main()
