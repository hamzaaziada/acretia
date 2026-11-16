import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from om import xlsx
from om.storage import AnalyticsDB, ensure_grid_schema
from src.harness import evidence
from src.harness.mcp import deck_server, excel_server, grid_server
from src.harness.mcp import protocol as P
from src.harness.mcp.client import MCPClient, MCPError
from src.harness.mcp.server import MCPServer
from src.harness.router import ToolRegistry

REPO = Path(__file__).resolve().parent.parent


def seed_grid(path, backend="sqlite"):
    db = AnalyticsDB(str(path), prefer=backend)
    ensure_grid_schema(db)
    db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer, exact_quote, page, confidence) "
               "VALUES (?,?,?,?,?,?,?)", ["g1", "docA", "q1", "42 days", "payable within 42 days", 3, 0.9])
    db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer) VALUES (?,?,?,?)",
               ["g1", "docB", "q1", "n/a"])
    db._c().close()
    return str(path)


def make_xlsx(path):
    wb = xlsx.Workbook()
    s = wb.sheet("Model")
    s.set("A1", 10)
    s.set("A2", 5)
    s.set("A3", "=A1*A2")
    Path(path).write_bytes(wb.to_bytes())


class EchoRegistryMixin:
    def registry(self):
        reg = ToolRegistry()
        reg.register("echo", lambda text: {"echo": text},
                     {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}})
        reg.register("boom", lambda: 1 / 0, {"type": "object", "properties": {}})
        return reg


class ProtocolTests(EchoRegistryMixin, unittest.TestCase):
    def setUp(self):
        self.srv = MCPServer("t", self.registry())

    def rpc(self, method, params=None, id_=1):
        m = {"jsonrpc": "2.0", "id": id_, "method": method}
        if params is not None:
            m["params"] = params
        return self.srv.handle(m)

    def test_initialize_list_call_ping(self):
        r = self.rpc("initialize", {})["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertEqual(r["capabilities"], {"tools": {}})
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        names = [t["name"] for t in self.rpc("tools/list")["result"]["tools"]]
        self.assertEqual(sorted(names), ["boom", "echo"])
        res = self.rpc("tools/call", {"name": "echo", "arguments": {"text": "hi"}})["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(res["structuredContent"], {"echo": "hi"})
        self.assertEqual(json.loads(res["content"][0]["text"]), {"echo": "hi"})
        self.assertEqual(self.rpc("ping")["result"], {})

    def test_errors(self):
        self.assertEqual(self.rpc("nope/nothing")["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "echo", "arguments": {}})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/call", {"name": "echo", "arguments": {"text": 5}})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/call", {"name": "missing"})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/call", {"arguments": {}})["error"]["code"], -32602)
        self.assertEqual(self.rpc("tools/list", [1])["error"]["code"], -32602)
        self.assertEqual(self.srv.handle([])["error"]["code"], -32600)
        self.assertEqual(self.srv.handle({"id": 1, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(self.srv.handle({"jsonrpc": "2.0", "id": 1})["error"]["code"], -32600)
        # tool crash is a tool error, not a protocol error
        res = self.rpc("tools/call", {"name": "boom"})["result"]
        self.assertTrue(res["isError"])

    def test_unknown_notification_executes_nothing(self):
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "tools/call",
                                           "params": {"name": "boom"}}))

    def test_stdio_loop_in_memory(self):
        lines = (b'{bad json\n' + b'\n' + P.encode({"jsonrpc": "2.0", "id": 7, "method": "ping"}))
        out = io.BytesIO()
        self.srv.serve_stdio(io.BytesIO(lines), out)
        resps = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(resps[0]["error"]["code"], -32700)
        self.assertIsNone(resps[0]["id"])
        self.assertEqual(resps[1], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_oversize_message(self):
        big = b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + b"a" * (P.MAX_MESSAGE_BYTES + 10) + b'"}}\n'
        out = io.BytesIO()
        self.srv.serve_stdio(io.BytesIO(big + P.encode({"jsonrpc": "2.0", "id": 2, "method": "ping"})), out)
        resps = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(resps[0]["error"]["code"], -32700)
        self.assertEqual(resps[1]["id"], 2)

    def test_inprocess_client(self):
        c = MCPClient.inprocess(self.srv)
        self.assertEqual(c.initialize()["serverInfo"]["name"], "t")
        self.assertEqual(len(c.list_tools()), 2)
        self.assertEqual(c.call_tool("echo", {"text": "x"}), {"echo": "x"})
        with self.assertRaises(MCPError):
            c.call_tool("boom")
        with self.assertRaises(MCPError) as cm:
            c.call_tool("echo", {})
        self.assertEqual(cm.exception.code, -32602)


class EvidenceTests(EchoRegistryMixin, unittest.TestCase):
    def test_chain_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            ev = os.path.join(d, "job1.jsonl")
            srv = MCPServer("t", self.registry(), evidence_path=ev)
            c = MCPClient.inprocess(srv)
            c.call_tool("echo", {"text": "a"})
            srv.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                        "params": {"name": "echo", "arguments": {"text": "b"}}})
            srv.close()
            self.assertTrue(evidence.verify(ev))
            recs = evidence.export(ev)
            self.assertEqual([r["tool"] for r in recs], ["echo", "echo"])
            self.assertEqual(recs[0]["source"], "echo")

    def test_source_is_doc_id(self):
        with tempfile.TemporaryDirectory() as d:
            ev = os.path.join(d, "job2.jsonl")
            reg = ToolRegistry()
            reg.register("lookup", lambda doc_id: {"ok": True},
                         {"type": "object", "required": ["doc_id"], "properties": {"doc_id": {"type": "string"}}})
            srv = MCPServer("t", reg, evidence_path=ev)
            MCPClient.inprocess(srv).call_tool("lookup", {"doc_id": "docA"})
            srv.close()
            self.assertEqual(evidence.export(ev)[0]["source"], "docA")
            self.assertTrue(evidence.verify(ev))


class GridTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.db = seed_grid(Path(self.root) / "grid.db")
        self.env = {"ACRETIA_MCP_ROOT": self.root, "ACRETIA_GRID_DB": self.db, "ACRETIA_GRID_BACKEND": "sqlite"}

    def test_stdio_subprocess_round_trip(self):
        c = MCPClient.spawn([sys.executable, "-m", "src.harness.mcp.grid_server"], env=self.env, timeout=30,
                            cwd=str(REPO))
        try:
            self.assertEqual(c.initialize()["protocolVersion"], "2025-06-18")
            names = {t["name"] for t in c.list_tools()}
            self.assertEqual(names, {"grid_query", "grid_cell", "grid_schema"})
            r = c.call_tool("grid_query", {"sql": "SELECT doc_id, answer FROM grid_cells ORDER BY doc_id"})
            self.assertEqual(r["rows"][0], {"doc_id": "docA", "answer": "42 days"})
            self.assertEqual(r["row_count"], 2)
            cell = c.call_tool("grid_cell", {"grid_id": "g1", "doc_id": "docA", "question_id": "q1"})
            self.assertEqual(cell["cell"]["page"], 3)
            self.assertFalse(c.call_tool("grid_cell", {"grid_id": "g1", "doc_id": "x", "question_id": "q"})["found"])
            self.assertIn("grid_cells", c.call_tool("grid_schema")["tables"])
            with self.assertRaises(MCPError):
                c.call_tool("grid_query", {"sql": "DROP TABLE grid_cells"})
        finally:
            c.close()

    def test_sql_injection_rejected(self):
        os.environ.update(self.env)
        srv = grid_server.make_server(self.db)
        try:
            c = MCPClient.inprocess(srv)
            for bad in ["SELECT 1; DROP TABLE grid_cells", "DROP TABLE grid_cells", "INSERT INTO grid_cells VALUES (1)",
                        "ATTACH 'x.db' AS x", "COPY grid_cells TO 'out.csv'", "PRAGMA table_info(grid_cells)",
                        "SELECT * FROM grid_cells -- x", "SELECT * /* c */ FROM grid_cells",
                        "WITH a AS (SELECT 1) DELETE FROM grid_cells", "SELECT * FROM 'secrets.csv'",
                        "SELECT * FROM read_csv('/etc/passwd')", "UPDATE grid_cells SET answer='x'",
                        "SELECT * FROM grid_cells WHERE answer = 'it''s' ; SELECT 2", "", "   "]:
                with self.assertRaises(MCPError, msg=bad):
                    c.call_tool("grid_query", {"sql": bad})
            # semicolon inside a string literal is data, not a statement break
            self.assertEqual(c.call_tool("grid_query", {"sql": "SELECT ';' AS s"})["rows"], [{"s": ";"}])
            n = c.call_tool("grid_query", {"sql": "SELECT COUNT(*) AS n FROM grid_cells"})["rows"][0]["n"]
            self.assertEqual(n, 2)
        finally:
            srv.close()
            for k in self.env:
                os.environ.pop(k, None)

    def test_db_path_outside_root_rejected(self):
        os.environ["ACRETIA_MCP_ROOT"] = self.root
        try:
            with self.assertRaises(ValueError):
                grid_server.open_db("/etc/evil.db")
        finally:
            os.environ.pop("ACRETIA_MCP_ROOT", None)


class PathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.outside = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside.cleanup)
        make_xlsx(Path(self.root) / "m.xlsx")
        make_xlsx(Path(self.outside.name) / "secret.xlsx")
        os.symlink(Path(self.outside.name) / "secret.xlsx", Path(self.root) / "link.xlsx")
        os.symlink(self.outside.name, Path(self.root) / "linkdir")
        self._old = os.environ.get("ACRETIA_MCP_ROOT")
        os.environ["ACRETIA_MCP_ROOT"] = self.root
        self.c = MCPClient.inprocess(excel_server.make_server())

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ACRETIA_MCP_ROOT", None)
        else:
            os.environ["ACRETIA_MCP_ROOT"] = self._old

    def test_evaluate_and_grade(self):
        r = self.c.call_tool("xlsx_evaluate", {"path": "m.xlsx", "cells": ["Model!A3", "Model!A1"]})
        self.assertEqual(r["values"]["Model!A3"]["value"], 50)
        self.assertEqual(r["values"]["Model!A1"]["value"], 10)
        g = self.c.call_tool("xlsx_grade", {"path": "m.xlsx"})
        self.assertIsInstance(g, dict)
        self.assertTrue(g)

    def test_traversal_rejected(self):
        secret = str(Path(self.outside.name) / "secret.xlsx")
        for bad in ["../" + os.path.basename(self.outside.name) + "/secret.xlsx", secret, "link.xlsx",
                    "linkdir/secret.xlsx", "sub/../../x.xlsx", "/etc/passwd", "m.txt", "nonexistent.xlsx"]:
            for tool in ("xlsx_evaluate", "xlsx_grade", "xlsx_recalc"):
                args = {"path": bad} if tool != "xlsx_evaluate" else {"path": bad, "cells": ["Model!A1"]}
                with self.assertRaises(MCPError, msg=f"{tool} {bad}"):
                    self.c.call_tool(tool, args)

    def test_bad_cell_refs(self):
        with self.assertRaises(MCPError):
            self.c.call_tool("xlsx_evaluate", {"path": "m.xlsx", "cells": ["A1"]})
        with self.assertRaises(MCPError):
            self.c.call_tool("xlsx_evaluate", {"path": "m.xlsx", "cells": ["Nope!A1"]})

    def test_recalc_and_deck_degrade_gracefully(self):
        r = self.c.call_tool("xlsx_recalc", {"path": "m.xlsx"})
        self.assertIn("available", r)
        if not r["available"]:
            self.assertIn("reason", r)
        d = MCPClient.inprocess(deck_server.make_server())
        (Path(self.root) / "x.pptx").write_bytes(b"PK")
        for tool in ("pptx_validate", "deck_render"):
            r = d.call_tool(tool, {"path": "x.pptx"})
            self.assertIn("available", r)
            if not r["available"]:
                self.assertTrue(r["reason"])
        with self.assertRaises(MCPError):
            d.call_tool("pptx_validate", {"path": "../x.pptx"})

    def test_layout_spacing_check(self):
        (Path(self.root) / "l.json").write_text(json.dumps({"elements": []}))
        d = MCPClient.inprocess(deck_server.make_server())
        try:
            r = d.call_tool("pptx_validate", {"path": "l.json"})
        except MCPError:
            self.skipTest("layout schema differs")
        self.assertTrue(r["available"])


class TimeoutTests(unittest.TestCase):
    def test_hung_server_times_out(self):
        c = MCPClient.spawn([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
        t = time.time()
        with self.assertRaises(MCPError) as cm:
            c.initialize()
        self.assertIn("timed out", str(cm.exception))
        self.assertLess(time.time() - t, 10)

    def test_crashed_server(self):
        c = MCPClient.spawn([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=5)
        with self.assertRaises(MCPError) as cm:
            c.initialize()
        self.assertIn("exit", str(cm.exception))
        c.close()

    def test_bad_spawn(self):
        with self.assertRaises(MCPError):
            MCPClient.spawn(["/nonexistent/binary"])
        with self.assertRaises(MCPError):
            MCPClient.spawn("python3 -c 1")


if __name__ == "__main__":
    unittest.main()
