"""Slides: every generated part is well-formed XML, decks have the expected pages, and the analyst rules hold
(all-NM multiple columns dropped, banks kept out of the EBITDA-margin chart, divergent methods flagged)."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import decks  # noqa: E402
from om.pptx import attr  # noqa: E402
from om.search import Index  # noqa: E402

ROWS = {
    "AAA": {"ticker": "AAA", "name": "ALPHA HOLDINGS INC", "revenue_ltm": 1200.0, "revenue_growth_ltm_yoy": 12.0,
            "margin_gross_ltm": 55.0, "margin_ebitda_ltm": 30.0, "rule_of_40_ltm_hist": 42.0, "revenue_fy": 1100.0,
            "revenue_fy_minus1": 1000.0, "ebitda_ltm": 360.0, "ebitda_fy": 330.0, "ebitda_fy_minus1": 290.0},
    "BBB": {"ticker": "BBB", "name": "BETA CORP", "revenue_ltm": 800.0, "revenue_growth_ltm_yoy": 25.0,
            "margin_gross_ltm": 70.0, "margin_ebitda_ltm": 20.0, "rule_of_40_ltm_hist": 45.0},
    "BNK": {"ticker": "BNK", "name": "GAMMA BANCORP", "revenue_ltm": 900.0, "revenue_growth_ltm_yoy": 5.0,
            "is_financial_format": True},
}


class FakeData:
    def comps_row(self, t):
        if t.upper() not in ROWS:
            raise KeyError(t)
        return dict(ROWS[t.upper()]), {}


class FakeRounds:
    def stats(self, **f):
        return {"rounds": 2, "total_sold": 3.5e8, "median_sold": 1.75e8, "quarters_loaded": [{"quarter": "2026Q3"}, {"quarter": "2026Q2"}],
                "by_quarter": [{"quarter": "2026-Q2", "sold": 1e8, "rounds": 1}, {"quarter": "2026-Q3", "sold": 2.5e8, "rounds": 1}],
                "by_industry": [{"industry": "Biotechnology", "sold": 3.5e8}]}

    def search(self, **f):
        return {"results": [{"company": "Delta Bio Inc", "industry": "Biotechnology", "city": "Boston", "state": "MA", "country": "US",
                             "first_sale_date": "2026-08-01", "amount_sold": 2.5e8, "investors": 9}]}


def parts(deck):
    z = zipfile.ZipFile(io.BytesIO(deck.save()))
    for n in z.namelist():
        if n.endswith((".xml", ".rels")):
            ET.fromstring(z.read(n))          # raises on malformed XML
    return z


def slide_text(z):
    return " ".join(z.read(n).decode() for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))


def dcf_values(gap=True):
    v = {"B4": "TEST", "A2": "TEST CO INC — unlevered free cash flow", "J14": 0.09, "J17": 0.03, "J18": 12.0,
         "C42": 50.0, "D42": 160.0 if gap else 55.0, "D47": 0.07, "C46": 5.0}
    for r in range(52, 57):
        for i, c in enumerate("CDEFG"):
            v[f"{c}{r}"] = 50.0 + i - (r - 54)
            v[f"{c}{r + 13}"] = (160.0 if gap else 55.0) + i - (r - 54)
    for i, c in enumerate("CDEFG"):
        v[f"{c}51"], v[f"B{52 + i}"] = 0.02 + i * 0.005, 0.08 + i * 0.005
    return v


class DeckTests(unittest.TestCase):
    def test_attr_escapes_quotes(self):
        self.assertEqual(attr('"$"#,##0'), "&quot;$&quot;#,##0")
        self.assertEqual(attr("a<b&c"), "a&lt;b&amp;c")

    def test_display_name(self):
        self.assertEqual(decks.display_name("MICROSOFT CORP"), "Microsoft Corp.")
        self.assertEqual(decks.display_name("BANK OF THE WEST"), "Bank of the West")
        self.assertEqual(decks.display_name(None), "")

    def test_comps_deck(self):
        deck, stem = decks.build("comps", {"tickers": "AAA, BBB BNK ZZZ"}, data_service=FakeData(), brand="Test Partners")
        z = parts(deck)
        text = slide_text(z)
        self.assertEqual(stem, "Comps AAA BBB BNK ZZZ")
        self.assertIn("Alpha Holdings Inc.", text)
        self.assertIn("Test Partners", text)
        self.assertIn("not found", text)               # unknown ticker is shown, not silently dropped
        self.assertNotIn("EV / EBITDA", text.split("Growth and profitability")[0])  # all-NM multiple columns dropped
        charts = [n for n in z.namelist() if n.startswith("ppt/charts/chart")]
        self.assertTrue(charts)
        growth_chart = z.read(charts[0]).decode()
        self.assertNotIn("BNK", growth_chart)          # bank excluded from EBITDA-margin chart

    def test_tearsheet_without_filings(self):
        idx = Index(Path(tempfile.mkdtemp()) / "s.db")
        deck, stem = decks.build("tearsheet", {"ticker": "aaa"}, data_service=FakeData(), index=idx)
        parts(deck)
        self.assertEqual(stem, "AAA profile")

    def test_dcf_payload_and_divergence(self):
        p = decks.dcf_payload({}, dcf_values(gap=True))
        self.assertEqual(p["ticker"], "TEST")
        self.assertEqual([m["low"] for m in p["methods"]], [50.0, 160.0])     # inner 3x3 of each sensitivity table
        self.assertTrue(decks._divergence_note(p["methods"], p["checks"]).startswith("Methods do not overlap"))
        deck, _ = decks.build("dcf", {"values": dcf_values(gap=True)})
        self.assertIn("Methods do not overlap", slide_text(parts(deck)))
        close = decks.dcf_payload({}, dcf_values(gap=False))
        self.assertEqual(decks._divergence_note(close["methods"], close["checks"]), "")

    def test_rounds_deck_filters_whitelisted(self):
        deck, _ = decks.build("rounds", {"filters": {"industry": "Biotechnology", "min_sold": "1000000", "evil": "x"}},
                              rounds=FakeRounds())
        self.assertIn("Delta Bio", slide_text(parts(deck)))

    def test_answer_deck_with_and_without_model(self):
        res = {"answer": "Supply is concentrated in Asia [1].", "verified": 1,
               "citations": [{"n": 1, "source_id": "D1", "quote": "suppliers in Asia", "verified": True}],
               "sources": [{"id": "D1", "kind": "document", "company": "Alpha", "form": "10-K", "filed": "2026-01-01"}]}
        text = slide_text(parts(decks.build("answer", {"question": "Q?", "result": res})[0]))
        self.assertIn("Appendix", text)
        text = slide_text(parts(decks.build("answer", {"question": "Q?", "result": {"sources": res["sources"]}})[0]))
        self.assertIn("Sources found", text)

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            decks.build("nope", {})


if __name__ == "__main__":
    unittest.main()
