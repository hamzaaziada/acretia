"""S6.1b research tools: hermetic (fake SEC/web objects, sockets patched to raise, no LLM)."""
import copy
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from om import statements as stm
from om.contracts import Citation
from om.storage import AnalyticsDB, ensure_grid_schema
from om.xlsx import Workbook
from src.harness.connectors.sec import statements_to_dict
from src.harness.connectors.web import PageFacts
from src.harness.evidence import EvidenceBundle, verify
from src.harness.research import tools as T
from src.harness.research.api import SourcedFigure
from src.harness.router import ToolError

FIX = Path(__file__).parent / "fixtures" / "research" / "tools"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class FakeSec:
    def __init__(self, cf=None):
        self.cf = cf or load("companyfacts_testco.json")
        self.calls = 0

    def company_facts(self, ticker):
        self.calls += 1
        return copy.deepcopy(self.cf)

    def filings(self, ticker, form="10-K", n=5):
        return [{"form": form, "filed": "2025-02-15", "accession": "0000000001-25-000001", "source": "fake",
                 "url": "https://www.sec.gov/Archives/edgar/data/1234/000000000125000001/x.htm"},
                {"form": form, "filed": "2024-02-15", "accession": "0000000001-24-000001", "source": "fake",
                 "url": "https://www.sec.gov/Archives/edgar/data/1234/000000000124000001/x.htm"}][:n]

    def financial_statements(self, ticker, years=5):
        return statements_to_dict(stm.build(self.cf, ticker.upper(), years=years), source="fake")


class FakeWeb:
    def __init__(self, name="web_page.json"):
        self.d = load(name)

    def page_facts(self, url):
        return PageFacts(**self.d), [("https://example.com/a", "A")]


def _no_net(*a, **k):
    raise AssertionError("network access attempted")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            p = mock.patch(target, _no_net)
            p.start()
            self.addCleanup(p.stop)

    def bundle(self):
        b = EvidenceBundle(self.root / "ev.jsonl")
        self.addCleanup(b.close)
        return b


class SecTools(Base):
    def test_sec_facts_cites_every_figure(self):
        r = T.sec_facts("TEST", ["us-gaap:Revenues"], 5, sec=FakeSec()).to_dict()
        self.assertEqual([f["period"] for f in r["figures"]], ["FY ending 2023-12-31", "FY ending 2024-12-31"])
        f = r["figures"][1]
        self.assertAlmostEqual(f["value"], 1100.0 * 1e6, delta=1)          # verbatim, full USD, no scaling
        self.assertEqual(f["units"], "USD")
        c = f["citation"]
        self.assertEqual(c["doc_id"], "0000000001-25-000001")
        self.assertEqual(c["xbrl_concept"], "us-gaap:Revenues")
        self.assertEqual(c["as_of"], "2024-12-31")
        self.assertTrue(c["url"].startswith("https://www.sec.gov/Archives/edgar/data/1234/"))
        self.assertEqual(len(c["sha256_span_hash"]), 64)
        SourcedFigure.from_dict(f)                                           # contract-valid
        self.assertEqual(r["data"]["missing"], [])

    def test_missing_concept_gives_no_figure_not_zero(self):
        r = T.sec_facts("TEST", ["us-gaap:Revenues", "us-gaap:NoSuchConcept"], 5, sec=FakeSec()).to_dict()
        self.assertTrue(all(f["label"].endswith("Revenues") for f in r["figures"]))
        self.assertEqual([m["item"] for m in r["data"]["missing"]], ["us-gaap:NoSuchConcept"])
        self.assertNotIn(0.0, [f["value"] for f in r["figures"]])

    def test_as_of_and_periods_window(self):
        r = T.sec_facts("TEST", ["Revenues"], 1, sec=FakeSec()).to_dict()
        self.assertEqual(len(r["figures"]), 1)
        r = T.sec_facts("TEST", ["Revenues"], 5, sec=FakeSec(), as_of="2023-12-31").to_dict()
        self.assertEqual(r["figures"], [])                                   # FY2023 was filed 2024-02-15, after as_of
        r = T.sec_facts("TEST", ["Revenues"], 5, sec=FakeSec(), as_of="2024-03-01").to_dict()
        self.assertEqual([f["citation"]["as_of"] for f in r["figures"]], ["2023-12-31"])

    def test_sec_statements_headline_figures_and_total_debt(self):
        r = T.sec_statements("TEST", 2, sec=FakeSec()).to_dict()
        labels = {f["label"] for f in r["figures"]}
        for want in ("Revenue", "Gross profit", "Operating income", "Net income", "Total assets", "Cash and equivalents",
                     "Cash from operations"):
            self.assertIn(f"TEST {want}", labels)
        self.assertIn("TEST derived: total_debt = debt_current + debt_noncurrent", labels)
        rev = [f for f in r["figures"] if f["label"] == "TEST Revenue"]
        self.assertEqual(rev[-1]["units"], "USD millions")
        self.assertAlmostEqual(rev[-1]["value"], 1100.0, places=3)
        self.assertEqual(len(r["data"]["derivations"][0]["inputs"]), 2)
        self.assertEqual(len(r["data"]["statements"]["years"]), 2)

    def test_sec_filings_lists_without_figures(self):
        r = T.sec_filings("TEST", "10-K", 2, sec=FakeSec()).to_dict()
        self.assertEqual(len(r["data"]["filings"]), 2)
        self.assertEqual(r["figures"], [])
        r = T.sec_filings("TEST", "10-K", 2, sec=FakeSec(), as_of="2024-06-01").to_dict()
        self.assertEqual(len(r["data"]["filings"]), 1)

    def test_derived_ratio_cites_its_inputs(self):
        r = T.ratios("TEST", 3, sec=FakeSec()).to_dict()
        gm = [f for f in r["figures"] if "gross_margin" in f["label"]]
        self.assertTrue(gm)
        self.assertTrue(gm[0]["label"].startswith("TEST derived: gross_margin = gross_profit / revenue"))
        self.assertAlmostEqual(gm[0]["value"], 0.45, places=6)
        der = [d for d in r["data"]["derivations"] if d["figure"] == gm[0]["label"] and d["period"] == gm[0]["period"]][0]
        self.assertEqual(len(der["inputs"]), 2)
        input_hashes = {c["sha256_span_hash"] for c in der["inputs"]}
        self.assertTrue(input_hashes <= {c["sha256_span_hash"] for c in r["citations"]})
        self.assertIn("gross_profit", der["inputs"][0]["quote"] + der["inputs"][1]["quote"])
        self.assertIn(gm[0]["citation"]["sha256_span_hash"], {c["sha256_span_hash"] for c in r["citations"]})
        growth = [f for f in r["figures"] if "revenue_growth" in f["label"]]
        self.assertEqual(len(growth), 1)                                      # 2 years in fixture: only 2024 has a prior
        self.assertAlmostEqual(growth[0]["value"], 0.1, places=6)

    def test_ratio_with_missing_input_is_dropped(self):
        cf = load("companyfacts_testco.json")
        del cf["facts"]["us-gaap"]["GrossProfit"]
        r = T.ratios("TEST", 3, sec=FakeSec(cf)).to_dict()
        self.assertFalse([f for f in r["figures"] if "gross_margin" in f["label"]])
        self.assertTrue([m for m in r["data"]["missing"] if m["item"].startswith("gross_margin")])
        self.assertTrue([f for f in r["figures"] if "net_margin" in f["label"]])


class WebTools(Base):
    def test_number_with_units_becomes_figure_with_snippet_quote(self):
        r = T.web_facts("https://example.com/news/q4", web=FakeWeb()).to_dict()
        vals = {(f["value"], f["units"]) for f in r["figures"]}
        self.assertEqual(vals, {(1.2, "USD billion"), (12.0, "%")})            # "3,400 employees" has no unit: no figure
        c = r["figures"][0]["citation"]
        self.assertEqual(c["as_of"], "2025-02-01")
        self.assertEqual(c["url"], "https://example.com/news/q4")
        self.assertEqual(c["quote"], load("web_page.json")["snippet"])

    def test_no_units_no_figures(self):
        r = T.web_facts("https://example.com/about", web=FakeWeb("web_page_nonum.json")).to_dict()
        self.assertEqual(r["figures"], [])
        self.assertEqual(r["data"]["page"]["title"], "About")

    def test_parse_amount(self):
        self.assertEqual(T.parse_amount("$1,234.5 million"), (1234.5, "USD million"))
        self.assertEqual(T.parse_amount("(12.5%)"), (-12.5, "%"))
        self.assertEqual(T.parse_amount("1,000"), (1000.0, "number"))
        self.assertIsNone(T.parse_amount("about 5 million"))
        self.assertIsNone(T.parse_amount("n/a"))


class GridTools(Base):
    def make_db(self, rows):
        path = self.root / "grid.sqlite"
        db = AnalyticsDB(str(path), prefer="sqlite")
        ensure_grid_schema(db)
        for r in rows:
            db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer, exact_quote, page, bbox_x0, bbox_y0,"
                       " bbox_x1, bbox_y1, confidence, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", r)
        db.close()
        return str(path)

    ROWS = [("g1", "d1", "q_rev", "$1,250.5 million", "Revenue was $1,250.5 million", 7, 0.1, 0.2, 0.6, 0.25, 0.9,
             "2025-03-01T00:00:00Z"),
            ("g1", "d1", "q_name", "Acme Corp", "The Company, Acme Corp", 1, 0.1, 0.1, 0.5, 0.15, 0.9, "2025-03-01T00:00:00Z")]

    def test_grid_cell_numeric_has_page_and_bbox(self):
        with mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)}):
            r = T.grid_cell("g1", "d1", "q_rev", grid_db=self.make_db(self.ROWS)).to_dict()
        f = r["figures"][0]
        self.assertEqual((f["value"], f["units"]), (1250.5, "USD million"))
        c = f["citation"]
        self.assertEqual(c["page"], 7)
        self.assertEqual(c["bbox_norm"], [0.1, 0.2, 0.6, 0.25])
        self.assertEqual(c["quote"], "Revenue was $1,250.5 million")
        self.assertEqual(c["doc_id"], "d1")
        self.assertEqual(c["as_of"], "2025-03-01")

    def test_grid_cell_text_answer_no_figure_and_missing_cell(self):
        with mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)}):
            db = self.make_db(self.ROWS)
            r = T.grid_cell("g1", "d1", "q_name", grid_db=db).to_dict()
            self.assertEqual(r["figures"], [])
            self.assertTrue(r["data"]["missing"])
            r = T.grid_cell("g1", "d1", "nope", grid_db=db).to_dict()
            self.assertFalse(r["data"]["found"])

    def test_grid_query_figures_and_guard(self):
        with mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)}):
            db = self.make_db(self.ROWS)
            r = T.grid_query("SELECT * FROM grid_cells WHERE grid_id = ?", ["g1"], grid_db=db).to_dict()
            self.assertEqual(r["data"]["row_count"], 2)
            self.assertEqual(len(r["figures"]), 1)
            for bad in ("DROP TABLE grid_cells", "SELECT 1; SELECT 2", "DELETE FROM grid_cells"):
                with self.assertRaises(ToolError):
                    T.grid_query(bad, grid_db=db)

    def test_grid_query_engine_hardening(self):
        from src.harness.mcp import grid_server
        from src.harness.mcp.server import ToolFailure
        secret = self.root / "o.csv"
        secret.write_text("c\nOUTSIDE_SECRET\n")
        with mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)}):
            db = self.make_db(self.ROWS)
            for bad in (f"select * from (select 1) t, '{secret}'", f"select * from read_ndjson_auto('{secret}')",
                        "select * from (select 1) t, query('sel'||'ect 1')", f"select * from glob('{self.root}/*')",
                        f"ATTACH '{self.root}/x.db' AS x", f"COPY grid_cells TO '{self.root}/out.csv'"):
                with self.assertRaises(ToolError) as cm:
                    T.grid_query(bad, grid_db=db)
                self.assertNotIn("OUTSIDE_SECRET", str(cm.exception))
            # engine alone (guard bypassed), via the shared helper the tool uses
            for backend in ("sqlite",):
                adb = AnalyticsDB(db, prefer=backend)
                with self.assertRaises(ToolFailure):
                    grid_server.run_select(adb, f"select * from (select 1) t, '{secret}'", check=False)
                with self.assertRaises(ToolFailure):
                    grid_server.run_select(adb, "DELETE FROM grid_cells", check=False)
            r = T.grid_query("WITH x AS (SELECT doc_id FROM grid_cells) SELECT COUNT(*) AS n FROM x", grid_db=db).to_dict()
            self.assertEqual(r["data"]["rows"], [{"n": 2}])
            with self.assertRaises(ToolError) as cm:
                T.grid_query("with recursive r(n) as (select 1 union all select n+1 from r) select count(*) from r",
                             grid_db=db)
            self.assertIn("timeout", str(cm.exception))
        self.assertFalse((self.root / "out.csv").exists())

    def test_grid_db_path_confined(self):
        outside = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.addCleanup(os.unlink, outside.name)
        with mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)}):
            with self.assertRaises(ToolError):
                T.grid_cell("g", "d", "q", grid_db=outside.name)


class XlsxTools(Base):
    def make_book(self, name="m.xlsx"):
        wb = Workbook()
        sh = wb.sheet("Model")
        sh.set("B2", 100.0)
        sh.set("C2", 0.05)
        sh.set("D2", "=B2*(1+C2)")
        sh.set("E2", "text")
        (self.root / name).write_bytes(wb.to_bytes())

    def test_evaluate_cites_cell_locator(self):
        self.make_book()
        r = T.xlsx_evaluate("m.xlsx", ["Model!D2", "Model!E2"], excel_root=self.root, as_of="2025-01-01").to_dict()
        self.assertEqual(len(r["figures"]), 1)
        f = r["figures"][0]
        self.assertAlmostEqual(f["value"], 105.0)
        self.assertEqual(f["citation"]["cell_locator"], "Model!D2")
        self.assertEqual(f["citation"]["as_of"], "2025-01-01")
        self.assertEqual(r["data"]["values"]["Model!D2"]["formula"], "=B2*(1+C2)")
        self.assertEqual(r["data"]["missing"][0]["item"], "Model!E2")

    def test_path_confined_to_excel_root(self):
        self.make_book()
        for p in ("../m.xlsx", "/etc/passwd", "nope.xlsx", "m.txt"):
            with self.assertRaises(ToolError):
                T.xlsx_evaluate(p, ["Model!B2"], excel_root=self.root)
        with self.assertRaises(ToolError):
            T.xlsx_evaluate("m.xlsx", ["Model!B2"], excel_root=None)
        with self.assertRaises(ToolError):
            T.xlsx_evaluate("m.xlsx", ["bad ref"], excel_root=self.root)


class RegistryTests(Base):
    def reg(self, **kw):
        self.make_grid()
        return T.build_registry(sec=FakeSec(), web=FakeWeb(), grid_db=self.grid, excel_root=self.root, **kw)

    def make_grid(self):
        self.grid = GridTools.make_db(self, GridTools.ROWS)
        p = mock.patch.dict(os.environ, {"ACRETIA_MCP_ROOT": str(self.root)})
        p.start()
        self.addCleanup(p.stop)
        wb = Workbook()
        wb.sheet("Model").set("B2", 7.0)
        (self.root / "m.xlsx").write_bytes(wb.to_bytes())

    CALLS = [("sec_facts", {"ticker": "TEST", "concepts": ["us-gaap:Revenues"]}),
             ("sec_statements", {"ticker": "TEST", "years": 2}),
             ("sec_filings", {"ticker": "TEST"}),
             ("ratios", {"ticker": "TEST"}),
             ("web_facts", {"url": "https://example.com/news/q4"}),
             ("grid_query", {"sql": "SELECT * FROM grid_cells"}),
             ("grid_cell", {"grid_id": "g1", "doc_id": "d1", "question_id": "q_rev"}),
             ("xlsx_evaluate", {"path": "m.xlsx", "cells": ["Model!B2"]})]

    def test_all_tools_registered_for_reasoning_and_extraction(self):
        reg = self.reg()
        for tt in ("reasoning", "extraction"):
            self.assertEqual({t["name"] for t in reg.list(tt)}, {n for n, _ in self.CALLS})

    def test_each_call_appends_one_verifiable_record(self):
        b = self.bundle()
        reg = self.reg(evidence=b)
        for i, (name, args) in enumerate(self.CALLS, 1):
            out = reg.call(name, args)
            self.assertEqual(set(out), {"data", "figures", "citations", "source"})
            json.dumps(out)
            self.assertEqual(len(b.export()), i, name)
        self.assertTrue(verify(b.path))
        recs = b.export()
        self.assertEqual([r["tool"] for r in recs], [n for n, _ in self.CALLS])
        cell = recs[6]
        self.assertEqual(cell["page"], 7)
        self.assertEqual(cell["bbox_norm"], [0.1, 0.2, 0.6, 0.25])

    def test_failed_call_records_nothing(self):
        b = self.bundle()
        reg = self.reg(evidence=b)
        for name, args in (("sec_facts", {"ticker": "!!bad", "concepts": ["Revenues"]}),
                           ("grid_query", {"sql": "DROP TABLE grid_cells"}),
                           ("xlsx_evaluate", {"path": "../x.xlsx", "cells": ["Model!B2"]})):
            with self.assertRaises(ToolError):
                reg.call(name, args)
        self.assertEqual(b.export(), [])

    def test_registry_rejects_bad_args(self):
        reg = self.reg()
        for name, args in (("sec_facts", {"ticker": "TEST"}),                              # missing required
                           ("sec_facts", {"ticker": 5, "concepts": ["Revenues"]}),        # wrong type
                           ("sec_facts", {"ticker": "TEST", "concepts": "Revenues"}),
                           ("sec_filings", {"ticker": "TEST", "bogus": 1}),               # extra key
                           ("web_facts", {}), ("nope", {})):
            with self.assertRaises(ToolError, msg=name):
                reg.call(name, args)
        for name, args in (("sec_facts", {"ticker": "TEST", "concepts": ["Revenues"], "periods": 0}),
                           ("sec_statements", {"ticker": "TEST", "years": 99}),
                           ("web_facts", {"url": "file:///etc/passwd"}),
                           ("sec_facts", {"ticker": "TEST", "concepts": []})):
            with self.assertRaises(ToolError, msg=name):
                reg.call(name, args)

    def test_deterministic(self):
        reg = self.reg()
        for name, args in self.CALLS:
            self.assertEqual(reg.call(name, args), reg.call(name, args), name)

    def test_every_figure_is_contract_valid_and_sourced(self):
        reg = self.reg()
        for name, args in self.CALLS:
            out = reg.call(name, args)
            for f in out["figures"]:
                SourcedFigure.from_dict(f)
                self.assertTrue(f["citation"]["as_of"])
            for c in out["citations"]:
                Citation.from_dict(c)

    def test_registry_as_of_validation(self):
        with self.assertRaises(ToolError):
            T.build_registry(as_of="yesterday")


if __name__ == "__main__":
    unittest.main()
