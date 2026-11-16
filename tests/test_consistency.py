"""Inconsistency checker. Two halves: it must catch planted errors, and it must stay quiet on legitimate differences
(rounding at different precision, scenarios, different periods, '% of revenue', increments, footnotes)."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import consistency as cs  # noqa: E402
from om.pptx import Deck, emu  # noqa: E402
from om.rooms import Rooms  # noqa: E402
from om.search import Index  # noqa: E402
from tests.fixtures_office import docx, pptx, xlsx  # noqa: E402


def facts(text, ents=None):
    return [(f.metric, round(f.value, 6), f.period) for f in cs.text_facts(text, ents, source="t", where="t", carry=False)[0]]


def deck_bytes(slides):
    """slides: list of {'texts': [...], 'table': rows | None}"""
    d = Deck("t")
    for s in slides:
        sl = d.content(s.get("title", "Title"), "", "Source: test.")
        y = emu(1.5)
        for t in s.get("texts", []):
            sl.text(emu(0.5), y, emu(9), emu(0.6), [cs_para(t)])
            y += emu(0.7)
        if s.get("table"):
            sl.table(emu(0.5), y, emu(11), s["table"], [3] + [1.5] * (len(s["table"][0]) - 1), set(range(1, len(s["table"][0]))))
    return d.save()


def cs_para(t):
    from om.pptx import para, run
    return para(run(t, 12))


class ParsingTests(unittest.TestCase):
    def test_numbers_units_and_scales(self):
        n = {x.raw: (x.value * x.scale, x.kind) for x in cs.parse_numbers("$84.2 million, 31%, 12.0x, $1.2bn, (1,234), €5m")}
        self.assertEqual(n["$84.2 million"], (84.2e6, "money"))
        self.assertEqual(n["31%"], (31.0, "pct"))
        self.assertEqual(n["12.0x"], (12.0, "mult"))
        self.assertEqual(n["$1.2bn"], (1.2e9, "money"))
        self.assertEqual(n["(1,234)"], (-1234.0, None))
        self.assertEqual([x.raw for x in cs.parse_numbers("$9.38B1 of cash")], ["$9.38B"])   # footnote marker dropped

    def test_periods(self):
        self.assertEqual(cs.canon_period("FY2026E")[0], "FY2026")
        self.assertTrue(cs.canon_period("FY2026E")[1])
        self.assertEqual(cs.canon_period("Revenue LTM ($m)")[0], "LTM")
        self.assertEqual(cs.canon_period("Q3 FY25")[0], "Q3 2025")
        self.assertEqual(cs.canon_period("at 30 August 2026")[0], "2026-08-30")
        self.assertEqual(cs.canon_period("expires on March 31, 2027")[0], "2027-03-31")   # a date, not FY2027

    def test_metric_labels_must_be_exact(self):
        self.assertEqual(cs.canon_metric("Revenue LTM ($m)"), "revenue")
        self.assertEqual(cs.canon_metric("EBITDA margin"), "ebitda_margin")
        self.assertIsNone(cs.canon_metric("Long-term debt"))
        self.assertIsNone(cs.canon_metric("Debt and leases"))
        self.assertIsNone(cs.canon_metric("Revenue / EBITDA"))

    def test_prose_facts(self):
        f = facts("FY2025 revenue was $84.2 million, up 31% year over year. Adjusted EBITDA was $18.5 million, a margin of 22%.")
        self.assertIn(("revenue", 84.2e6, "FY2025"), f)
        self.assertIn(("revenue_growth", 31.0, "FY2025"), f)
        self.assertIn(("adj_ebitda_margin", 22.0, None), f)

    def test_prose_guards(self):
        self.assertEqual(facts("The top 10 customers represent 41% of revenue."), [])
        self.assertEqual(facts("Management expects cold-chain to add $6 million ARR in 2026."), [])
        self.assertEqual(facts("The $4.0B buyback leaves $15.5B of cash."), [])
        self.assertEqual(facts("Three months of FY26 operating cash flow is $3.96B."), [])
        self.assertEqual(facts("The agreement expires on March 31, 2027."), [])
        self.assertEqual(facts("Capex grew 14.2% a year over three years."), [])            # a CAGR, not a period figure
        self.assertIn(("capex_growth", 14.2, "FY2026"), facts("Capex grew 14.2% in FY2026."))

    def test_comparison_inherits_metric(self):
        e = cs.Entities()
        e.add("NVIDIA Corp.", "NVDA")
        f = facts("NVIDIA Corp. is the fastest grower at 83.4% LTM vs. a peer median of 17.9%.", e)
        self.assertEqual(f, [("revenue_growth", 83.4, "LTM"), ("revenue_growth", 17.9, "LTM")])


class DeckTests(unittest.TestCase):
    def test_cross_slide_conflict_and_arithmetic(self):
        data = deck_bytes([
            {"texts": ["Fiscal 2026 free cash flow was $9.39B ($15.82B operating less $6.43B capex)."]},
            {"texts": ["$15.82B of FY26 operating cash flow less $6.43B capex left $9.38B of free cash flow."]},
        ])
        r = cs.check_deck(data, tie=False)
        kinds = {(i["type"], i["severity"]) for i in r["issues"]}
        self.assertIn(("conflict", "medium"), kinds)                  # $9.39B vs $9.38B: one rounding step
        self.assertIn(("arithmetic", "medium"), kinds)                # 15.82 − 6.43 = 9.39, not 9.38
        self.assertTrue(any("$9.39B vs $9.38B" in i["title"] for i in r["issues"]))

    def test_precision_and_scenarios_stay_quiet(self):
        data = deck_bytes([
            {"texts": ["FY2025 revenue was $84.2 million.", "The $4.0B buyback leaves $15.5B of cash."]},
            {"texts": ["FY2025 revenue was $84.23 million.", "The $3.0B buyback leaves $16.5B of cash."]},
        ])
        self.assertEqual(cs.check_deck(data, tie=False)["issues"], [])

    def test_table_median_and_takeaway(self):
        table = [["Company", "Ticker", "Revenue growth"], ["Alpha Inc.", "AAA", "15.1%"], ["Beta Corp.", "BBB", "17.9%"],
                 ["Gamma Corp.", "GGG", "83.4%"], ["Delta Co.", "DDD", "13.2%"], ["Median", "", "17.9%"]]
        data = deck_bytes([{"table": table}, {"texts": ["Gamma Corp. is the fastest grower at 83.4% LTM vs. a peer median of 17.9%."]}])
        r = cs.check_deck(data, tie=False)
        agg = [i for i in r["issues"] if i["type"] == "aggregate"]
        self.assertEqual(len(agg), 1)                                  # median of 15.1, 17.9, 83.4, 13.2 is 16.5
        self.assertIn("16.5", agg[0]["title"])

    def test_bridge_and_notes(self):
        d = Deck("t")
        s = d.content("Bridge", "", "Source: test.")
        s.chart(emu(0.5), emu(1.5), emu(8), emu(4), ["Opening cash", "Free cash flow", "Dividends", "Closing cash"],
                [("Cash bridge ($B)", [20.2, 9.4, -3.6, 27.0])])
        r = cs.check_deck(d.save(), tie=False)
        self.assertTrue(any(i["type"] == "bridge" for i in r["issues"]))   # 20.2 + 9.4 − 3.6 = 26.0, not 27.0

    def test_tie_out(self):
        class DS:
            def comps_row(self, t):
                return ({"revenue_ltm": 1000.0, "revenue_fy": 950.0, "margin_gross_ltm": 40.0, "cik": 1, "ltm_end": "2026-06-30",
                         "last_fy_end": "2025-12-31"}, {})
        table = [["Company", "Ticker", "Revenue LTM ($m)", "Gross margin"], ["Alpha Inc.", "AAA", "1,000", "45.0%"]]
        r = cs.check_deck(deck_bytes([{"table": table}]), data_service=DS(), tie=True)
        self.assertEqual(r["tie_out"]["checked"], 2)
        self.assertEqual(r["tie_out"]["matched"], 1)
        self.assertTrue(any(i["type"] == "source" and "Gross margin" in i["title"] for i in r["issues"]))


class RoomTests(unittest.TestCase):
    def room(self, cim, model, mgmt):
        d = Path(tempfile.mkdtemp())
        idx = Index(d / "s.db")
        rm = Rooms(idx, d)
        rid = rm.create("r")
        rm.add_file(rid, "CIM.docx", docx([["Financial Summary", cim]]))
        rm.add_file(rid, "Model.xlsx", xlsx(model))
        rm.add_file(rid, "Mgmt.pptx", pptx([["Plan", mgmt]]))
        return cs.check_room(idx, rm, rid)

    MODEL = {"P&L": [["Metric", "FY2024", "FY2025", "FY2026E"], ["Revenue ($m)", 64.3, 84.2, 107.5],
                     ["Adjusted EBITDA ($m)", 11.9, 18.5, 26.9]], "KPIs": [["Customers", 412]]}

    def test_consistent_room_is_quiet(self):
        r = self.room("FY2025 revenue was $84.2 million, up 31% year over year. Adjusted EBITDA was $18.5 million, a margin of 22%. "
                      "The top 10 customers represent 41% of revenue.", self.MODEL, "Target revenue of $107.5 million in FY2026")
        self.assertEqual(r["issues"], [])
        self.assertGreaterEqual(r["facts"], 8)

    def test_planted_errors_are_caught(self):
        r = self.room("FY2025 revenue was $84.2 million, up 31% year over year. Adjusted EBITDA was $19.5 million, a margin of 22%. "
                      "We serve 415 customers.", self.MODEL, "Target revenue of $110.0 million in FY2026")
        titles = " | ".join(i["title"] for i in r["issues"])
        self.assertIn("Revenue (FY2026)", titles)
        self.assertIn("Adjusted EBITDA (FY2025)", titles)
        self.assertIn("Customers", titles)
        self.assertTrue(any(i["type"] == "math" for i in r["issues"]))      # 19.5 / 84.2 = 23.2%, not 22%

    def test_model_review_downgrades(self):
        class Router:
            def available(self, stage):
                return True

            def complete_json(self, stage, system, parts, schema, **kw):
                from om.llm import Result
                if "facts" in schema["properties"]:
                    return Result({"facts": []})
                return Result({"same_measure": False, "explanation": "One is gross, one is net."})
        d = Path(tempfile.mkdtemp())
        idx = Index(d / "s.db")
        rm = Rooms(idx, d)
        rid = rm.create("r")
        rm.add_file(rid, "A.docx", docx([["FY2025 revenue was $84.2 million."]]))
        rm.add_file(rid, "B.docx", docx([["FY2025 revenue was $90.0 million."]]))
        r = cs.check_room(idx, rm, rid, router=Router())
        conflict = [i for i in r["issues"] if i["type"] == "conflict"][0]
        self.assertEqual(conflict["severity"], "low")
        self.assertIn("gross", conflict["review"])


class WorkbookTests(unittest.TestCase):
    def test_errors_checks_and_cross_sheet(self):
        data = xlsx({"Model": [["Costco, $m"], ["Line item", "2027E", "2028E"], ["Revenue", 321339, 340619], ["Free cash flow", 10274, 10955]],
                     "Outputs": [["Outputs, $m"], ["Line item", "2027E", "2028E"], ["Revenue", 321339, 340000]],
                     "Checks": [["Check", "Difference", "Status"], ["Closing cash ties", 15330, "ERROR"], ["Grid centre", 0, "OK"]]})
        z = zipfile.ZipFile(io.BytesIO(data))
        files = {n: z.read(n) for n in z.namelist()}
        sheet = next(n for n in files if n.endswith("sheet1.xml"))
        files[sheet] = files[sheet].replace(b"</sheetData>", b'<row r="9"><c r="B9" t="e"><v>#N/A</v></c></row></sheetData>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as out:
            for n, b in files.items():
                out.writestr(n, b)
        r = cs.check_workbook(buf.getvalue(), allow_recalc=False)
        types = {i["type"] for i in r["issues"]}
        self.assertIn("error_cells", types)
        self.assertIn("checks", types)
        self.assertTrue(any(i["type"] == "conflict" and "Revenue (FY2028)" in i["title"] for i in r["issues"]))


if __name__ == "__main__":
    unittest.main()
