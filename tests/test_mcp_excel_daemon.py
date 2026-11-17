"""Excel MCP server: recalculation wiring, engine status and daemon restart.

Hermetic. LibreOffice and formulon are optional: when they are missing the tools must still answer, report the
reason, and compare whatever engines are available. Nothing here needs the network.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from om import model3, recalc
from om import statements as stm
from src.harness.mcp import excel_server as es
from src.harness.mcp.server import ToolFailure
from tests.test_model3 import synthetic_companyfacts


def _model_bytes() -> bytes:
    data, _ = model3.build(stm.build(synthetic_companyfacts(), "TEST"), circ=0)
    return data


class ExcelServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _model_bytes()

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self._old = os.environ.get("ACRETIA_MCP_ROOT")
        os.environ["ACRETIA_MCP_ROOT"] = str(self.root)
        (self.root / "m.xlsx").write_bytes(self.data)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ACRETIA_MCP_ROOT", None)
        else:
            os.environ["ACRETIA_MCP_ROOT"] = self._old


class RecalcWiring(ExcelServerCase):
    def test_recalc_uses_compare_and_returns_a_report(self):
        r = es.xlsx_recalc("m.xlsx")
        self.assertTrue(r["available"], r)
        res = r["result"]
        # the shape om.recalc.compare produces, not a guessed entry point
        for key in ("agree", "engines", "divergences", "compared_cells"):
            self.assertIn(key, res)
        self.assertGreater(res["compared_cells"], 500)
        self.assertEqual(set(res["engines"]), set(recalc.DEFAULT_ENGINES))

    def test_recalc_never_claims_an_entry_point_that_does_not_exist(self):
        # the old implementation guessed recalc_file/recalc/recalculate/three_engine/check, none of which exist
        for name in ("recalc_file", "recalculate", "three_engine"):
            self.assertFalse(hasattr(recalc, name), f"om.recalc.{name} unexpectedly exists")

    def test_engine_subset_is_honoured(self):
        r = es.xlsx_recalc("m.xlsx", engines=["cached", "om"])
        self.assertTrue(r["available"], r)
        self.assertEqual(set(r["result"]["engines"]), {"cached", "om"})
        self.assertTrue(r["result"]["agree"], r["result"]["divergences"][:3])

    def test_unknown_engine_is_rejected(self):
        with self.assertRaises(ToolFailure) as cm:
            es.xlsx_recalc("m.xlsx", engines=["nope"])
        self.assertIn("nope", str(cm.exception))

    def test_planted_cached_divergence_is_reported_through_the_tool(self):
        from om.xlsx import col_letter
        wb, _ = model3.build_workbook(stm.build(synthetic_companyfacts(), "TEST"), circ=0)
        sheet = wb["IS"]
        (r, c), cell = next((rc, cl) for rc, cl in sorted(sheet.cells.items())
                            if isinstance(cl.value, str) and cl.value.startswith("=")
                            and isinstance(cl.cached, float) and abs(cl.cached) > 1)
        cell.cached = cell.cached + 12345.0
        (self.root / "bad.xlsx").write_bytes(wb.to_bytes())
        res = es.xlsx_recalc("bad.xlsx", engines=["cached", "om"])["result"]
        self.assertFalse(res["agree"])
        self.assertIn(f"IS!{col_letter(c)}{r}", [d["cell"] for d in res["divergences"]])

    def test_missing_file_is_a_tool_failure_not_a_crash(self):
        with self.assertRaises(ToolFailure):
            es.xlsx_recalc("nope.xlsx")


class EngineStatus(ExcelServerCase):
    def test_status_reports_every_engine_without_recalculating(self):
        r = es.xlsx_engine_status()
        self.assertTrue(r["available"], r)
        res = r["result"]
        self.assertEqual(set(res["engines"]), set(recalc.DEFAULT_ENGINES))
        self.assertIn("ready", res)
        for name, e in res["engines"].items():
            self.assertIn("available", e, name)
            self.assertIn("reason", e, name)
            if not e["available"]:
                self.assertTrue(e["reason"], f"{name} unavailable with no reason")

    def test_om_and_cached_are_always_available(self):
        res = es.xlsx_engine_status()["result"]["engines"]
        self.assertTrue(res["om"]["available"])
        self.assertTrue(res["cached"]["available"])

    def test_ready_needs_two_engines(self):
        res = es.xlsx_engine_status()["result"]
        n = sum(1 for e in res["engines"].values() if e["available"])
        self.assertEqual(res["ready"], n >= 2)

    def test_unavailable_engine_names_its_dependency(self):
        lo = es.xlsx_engine_status()["result"]["engines"]["libreoffice"]
        if not lo["available"]:
            self.assertTrue("uno" in lo["reason"] or "soffice" in lo["reason"], lo["reason"])

    def test_status_does_not_start_the_daemon(self):
        d = recalc.daemon()
        before = d.starts
        es.xlsx_engine_status()
        self.assertEqual(d.starts, before, "engine_status must not spawn soffice")


class DaemonRestart(ExcelServerCase):
    def test_restart_returns_a_status_and_keeps_the_tool_working(self):
        r = es.xlsx_engine_restart()
        self.assertTrue(r["available"], r)
        self.assertIn("engines", r["result"])
        self.assertTrue(es.xlsx_recalc("m.xlsx")["available"])

    def test_restart_is_safe_when_libreoffice_is_missing(self):
        d = recalc.daemon()
        if d.available():
            self.skipTest("LibreOffice is installed; the missing-dependency path is not exercised")
        r = es.xlsx_engine_restart()
        self.assertTrue(r["available"], r)
        self.assertFalse(r["result"]["engines"]["libreoffice"]["available"])

    def test_restart_actually_replaces_the_process_when_available(self):
        d = recalc.daemon()
        if not d.available():
            self.skipTest(f"LibreOffice/uno unavailable: {d.reason}")
        es.xlsx_recalc("m.xlsx")                      # bring the daemon up
        first = d.pid
        self.assertIsNotNone(first)
        es.xlsx_engine_restart()
        self.assertNotEqual(d.pid, first, "restart did not replace the soffice process")
        self.assertTrue(es.xlsx_recalc("m.xlsx")["result"]["agree"])


class Protocol(ExcelServerCase):
    def test_all_tools_are_registered_with_schemas(self):
        srv = es.make_server()
        tools = {t["name"]: t for t in srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
        for name in ("xlsx_evaluate", "xlsx_grade", "xlsx_recalc", "xlsx_engine_status", "xlsx_engine_restart"):
            self.assertIn(name, tools)
            self.assertIn("inputSchema", tools[name])
        self.assertEqual(tools["xlsx_engine_status"]["inputSchema"]["required"], [])
        self.assertIn("engines", tools["xlsx_recalc"]["inputSchema"]["properties"])

    def test_calls_go_through_the_protocol_layer(self):
        srv = es.make_server()
        r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "xlsx_engine_status", "arguments": {}}})
        self.assertNotIn("error", r, r)
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertIn("engines", payload["result"])

    def test_recalc_call_through_the_protocol_layer(self):
        srv = es.make_server()
        r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "xlsx_recalc", "arguments": {"path": "m.xlsx"}}})
        self.assertNotIn("error", r, r)
        payload = json.loads(r["result"]["content"][0]["text"])
        self.assertTrue(payload["available"], payload)
        self.assertGreater(payload["result"]["compared_cells"], 500)


if __name__ == "__main__":
    unittest.main()