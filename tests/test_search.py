"""Offline tests for passage splitting and the search index. Run: python3 -m unittest discover -s tests -v"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.docs import DocRef, passages  # noqa: E402
from om.search import Index  # noqa: E402

TENK = """<html><body>
<div><ix:header><div>hidden xbrl junk dei:EntityRegistrantName</div></ix:header></div>
<p>Table of Contents</p>
<p>Item 1A. Risk Factors .......... 12</p>
<p>Item 1A. Risk Factors</p>
<p>We face intense competition and pricing pressures in our markets, which could reduce margins.</p>
<p>Tariffs on components imported from China may increase our costs and disrupt our supply chain.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Revenue grew 12% driven by services. Gross margin expanded despite higher memory prices.</p>
</body></html>"""


def ref(ticker, form, filed, n):
    return DocRef(cik=n, ticker=ticker, company=f"{ticker} Inc.", form=form, filed=filed, report_date=None,
                  accession=f"000000000{n}-26-000001", file="doc.htm", url=f"https://sec.example/{ticker}/{n}",
                  title=form, items=None)


class PassageTests(unittest.TestCase):
    def test_sections_toc_and_xbrl_header(self):
        ps, _ = passages(TENK, target=120, minimum=40)
        text = " ".join(p.text for p in ps)
        self.assertNotIn("hidden xbrl junk", text)
        self.assertNotIn("Table of Contents", text)
        secs = {p.section for p in ps}
        self.assertIn("Item 1A. Risk Factors", secs)
        self.assertTrue(any(s and s.startswith("Item 7") for s in secs))
        risk = [p for p in ps if p.section == "Item 1A. Risk Factors"]
        self.assertTrue(any("pricing pressures" in p.text for p in risk))


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.idx = Index(Path(self.tmp.name) / "s.db")
        ps, n = passages(TENK, target=120, minimum=40)
        self.idx.add(ref("AAA", "10-K", "2025-02-01", 1), ps, n)
        ps2, n2 = passages("<p>Item 2.02 Results of Operations</p><p>Quarterly revenue rose on strong pricing; no tariff impact.</p>", 120, 20)
        self.idx.add(ref("BBB", "8-K", "2026-05-01", 2), ps2, n2)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stemming_and_phrase(self):
        r = self.idx.search("pricing pressure")
        self.assertEqual(r["total_documents"], 1)
        self.assertIn("<mark>", r["results"][0]["passages"][0]["snippet"])
        self.assertEqual(self.idx.search('"supply chain"')["total_documents"], 1)

    def test_filters_and_section(self):
        self.assertEqual(self.idx.search("tariff*", {"tickers": ["BBB"]})["total_documents"], 1)
        self.assertEqual(self.idx.search("tariff*", {"forms": ["10-K"], "section": "Risk"})["total_documents"], 1)
        self.assertEqual(self.idx.search("tariff*", {"date_from": "2026-01-01"})["results"][0]["ticker"], "BBB")

    def test_bad_syntax_falls_back(self):
        r = self.idx.search('margins (unbalanced "quote')
        self.assertIn("AND", r["fts"])

    def test_trend_and_facets(self):
        t = self.idx.trend("tariff*")
        self.assertEqual([x["quarter"] for x in t], ["2025-Q1", "2026-Q2"])
        f = self.idx.facets("tariff*")
        self.assertEqual({x["key"] for x in f["company"]}, {"AAA", "BBB"})

    def test_saved_search_alerts_only_new_documents(self):
        self.idx.save("tariffs", "tariff*")
        self.assertEqual(self.idx.alerts()[0]["new_documents"], 0)   # nothing new since saving
        time.sleep(0.01)
        ps, n = passages("<p>New tariffs announced on imported steel will raise input costs materially.</p>", 120, 20)
        self.idx.add(ref("CCC", "8-K", "2026-11-01", 3), ps, n)
        a = self.idx.alerts()[0]
        self.assertEqual(a["new_documents"], 1)
        self.assertEqual(a["results"][0]["ticker"], "CCC")
        self.assertEqual(self.idx.alerts()[0]["new_documents"], 0)   # marked as seen

    def test_passage_context(self):
        r = self.idx.search("memory prices")
        p = self.idx.passage(r["results"][0]["passages"][0]["chunk_id"], context=1)
        self.assertEqual(p["document"]["ticker"], "AAA")
        self.assertGreaterEqual(len(p["passages"]), 1)


if __name__ == "__main__":
    unittest.main()
