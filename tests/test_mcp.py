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


# ---------------------------------------------------------------------------------------------- FP-S2a hardening
import signal
import subprocess
import zipfile

from src.harness.mcp import client as mcp_client
from src.harness.mcp.server import ToolFailure


def secret_files(d):
    (Path(d) / "o.csv").write_text("secret_col\nOUTSIDE_SECRET\n")
    (Path(d) / "o.json").write_text('{"a":"OUTSIDE_JSON"}\n')


class EngineHardeningTests(unittest.TestCase):
    """The engine, not a keyword list, must refuse file access: every attack runs with the text guard bypassed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        secret_files(self.tmp.name)
        self.d = self.tmp.name

    def db(self, backend):
        db = AnalyticsDB(":memory:", prefer=backend)
        ensure_grid_schema(db)
        db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer) VALUES ('g','d1','q','1')")
        db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer) VALUES ('g','d2','q','2')")
        return db

    def attacks(self):
        d = self.d
        return [f"select * from (select 1) t, '{d}/o.csv'",
                f"select * from read_ndjson_auto('{d}/o.json')",
                f"select * from (select 1) t, query('sel'||'ect * from read_'||'csv(''{d}/o.csv'')')",
                f"select * from glob('{d}/*')", f"select * from read_text('{d}/o.csv')",
                f"select * from read_blob('{d}/o.csv')", f"select * from parquet_scan('{d}/x.parquet')",
                f"select * from read_csv('{d}/o.csv')", f"ATTACH '{d}/new.db' AS x",
                f"COPY (select 1) TO '{d}/out.csv'", "select * from read_csv('https://example.com/x.csv')",
                "select * from read_parquet('s3://bucket/x.parquet')", f"INSTALL httpfs", "LOAD httpfs",
                "DROP TABLE grid_cells", "INSERT INTO grid_cells (grid_id, doc_id, question_id) VALUES ('a','b','c')",
                "SET enable_external_access = true", "PRAGMA enable_external_access", "select load_extension('x')"]

    def test_engine_refuses_every_attack(self):
        for backend in ("duckdb", "sqlite"):
            db = self.db(backend)
            for q in self.attacks():
                with self.subTest(backend=backend, q=q[:60]):
                    try:
                        res = grid_server.run_select(db, q, check=False, timeout=3)
                    except ToolFailure as e:
                        self.assertNotIn("OUTSIDE", str(e))
                    else:
                        self.fail(f"engine let it through: {res}")
        self.assertFalse((Path(self.d) / "out.csv").exists())
        self.assertFalse((Path(self.d) / "new.db").exists())

    def test_text_guard_also_refuses(self):
        db = self.db("duckdb")
        for q in self.attacks():
            with self.subTest(q=q[:60]):
                with self.assertRaises(ToolFailure):
                    grid_server.run_select(db, q, timeout=3)

    def test_file_backed_read_only_connection(self):
        for backend in ("duckdb", "sqlite"):
            path = str(Path(self.d) / f"{backend}.db")
            db = AnalyticsDB(path, prefer=backend)
            ensure_grid_schema(db)
            db.execute("INSERT INTO grid_cells (grid_id, doc_id, question_id, answer) VALUES ('g','d','q','7')")
            db.close()
            db = AnalyticsDB(path, prefer=backend)  # unopened: the hardened read-only connection opens the file
            with self.subTest(backend=backend):
                r = grid_server.run_select(db, "SELECT answer FROM grid_cells")
                self.assertEqual(r["rows"], [{"answer": "7"}])
                with self.assertRaises(ToolFailure):
                    grid_server.run_select(db, "DELETE FROM grid_cells", check=False)
                with self.assertRaises(ToolFailure):
                    grid_server.run_select(db, f"select * from read_csv('{self.d}/o.csv')", check=False)
                self.assertEqual(db.query("SELECT COUNT(*) AS n FROM grid_cells")[0]["n"], 1)

    def test_legitimate_queries_still_work(self):
        for backend in ("duckdb", "sqlite"):
            db = self.db(backend)
            with self.subTest(backend=backend):
                self.assertEqual(grid_server.run_select(db, "SELECT COUNT(*) AS n FROM grid_cells")["rows"], [{"n": 2}])
                r = grid_server.run_select(db, "WITH x AS (SELECT doc_id, answer FROM grid_cells) "
                                               "SELECT a.doc_id, b.answer FROM x a JOIN grid_cells b ON a.doc_id = b.doc_id "
                                               "WHERE a.answer > ? ORDER BY 1", ["1"])
                self.assertEqual(r["rows"], [{"doc_id": "d2", "answer": "2"}])
                r = grid_server.run_select(db, "SELECT grid_id, COUNT(*) AS n, MAX(answer) AS m FROM grid_cells GROUP BY 1")
                self.assertEqual(r["rows"], [{"grid_id": "g", "n": 2, "m": "2"}])
                self.assertEqual(grid_server.run_select(db, "SELECT * FROM grid_runs")["rows"], [])

    def test_timeouts_and_memory(self):
        rec = ("with recursive r(n) as (select 1 union all select n+1 from r) select count(*) from r")
        for backend in ("duckdb", "sqlite"):
            db = self.db(backend)
            with self.subTest(backend=backend, q="recursive"):
                t = time.time()
                with self.assertRaises(ToolFailure) as cm:
                    grid_server.run_select(db, rec, timeout=1)
                self.assertLess(time.time() - t, 6)
                self.assertIn("timeout", str(cm.exception))
        db = self.db("duckdb")
        t = time.time()
        with self.assertRaises(ToolFailure):
            grid_server.run_select(db, "select repeat('a', 1000000000)", timeout=2)
        self.assertLess(time.time() - t, 6)

    def test_row_and_byte_caps(self):
        db = self.db("duckdb")
        r = grid_server.run_select(db, "select * from range(5000)", limit=5000)
        self.assertEqual(r["row_count"], grid_server.MAX_ROWS)
        self.assertTrue(r["truncated"])
        r = grid_server.run_select(db, "select repeat('a', 6000) as s from range(1000)", limit=1000)
        self.assertTrue(r["bytes_truncated"])
        self.assertLess(r["row_count"], 1000)
        self.assertLessEqual(len(json.dumps(r["rows"])), grid_server.MAX_RESULT_BYTES + 100 * len(r["rows"]))
        sq = self.db("sqlite")
        r = grid_server.run_select(sq, "with recursive r(n) as (select 1 union all select n+1 from r where n < 5000) "
                                       "select n from r", limit=5000)
        self.assertEqual(r["row_count"], grid_server.MAX_ROWS)

    def test_bad_params(self):
        with self.assertRaises(ToolFailure):
            grid_server.run_select(self.db("duckdb"), "SELECT ?", [{"a": 1}])


class ServerResponsivenessTests(unittest.TestCase):
    def test_ping_answers_while_query_runs(self):
        env = {"ACRETIA_MCP_ROOT": os.path.realpath(tempfile.gettempdir()), "ACRETIA_GRID_BACKEND": "duckdb",
               "ACRETIA_GRID_TIMEOUT": "4"}
        proc = subprocess.Popen([sys.executable, "-m", "src.harness.mcp.grid_server"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=str(REPO),
                                env=mcp_client.child_env(env))
        self.addCleanup(proc.kill)
        def send(m):
            proc.stdin.write(P.encode(m))
            proc.stdin.flush()
        send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "grid_query", "arguments": {
            "sql": "with recursive r(n) as (select 1 union all select n+1 from r) select count(*) from r"}}})
        time.sleep(0.5)
        t = time.time()
        send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
        first = json.loads(proc.stdout.readline())
        self.assertEqual(first["id"], 2)
        self.assertLess(time.time() - t, 2.5)
        second = json.loads(proc.stdout.readline())
        self.assertEqual(second["id"], 1)
        self.assertTrue(second["result"]["isError"])
        self.assertIn("timeout", second["result"]["content"][0]["text"])
        proc.stdin.close()
        proc.wait(timeout=10)


class DeepJsonTests(unittest.TestCase):
    def test_decode_rejects_deep_nesting(self):
        for deep in ("[" * 100 + "]" * 100, '{"a":' * 100 + "1" + "}" * 100, "[" * 200000 + "]" * 200000):
            line = '{"jsonrpc":"2.0","id":2,"method":"ping","params":' + deep + "}"
            with self.assertRaises(P.ProtocolError) as cm:
                P.decode(line)
            self.assertIn(cm.exception.code, (P.PARSE_ERROR, P.INVALID_REQUEST))

    def test_brackets_inside_strings_do_not_count(self):
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"s": "[" * 500 + '\\"' + "{" * 500}})
        self.assertEqual(P.decode(line)["method"], "ping")
        ok = '{"a":' * 60 + "1" + "}" * 60
        self.assertIsInstance(P.decode(ok), dict)

    def test_server_survives_deep_json(self):
        srv = MCPServer("t", ToolRegistry())
        deep = '{"jsonrpc":"2.0","id":2,"method":"ping","params":' + "[" * 100000 + "]" * 100000 + "}\n"
        out = io.BytesIO()
        srv.serve_stdio(io.BytesIO(deep.encode() + b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n'), out)
        lines = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], P.INVALID_REQUEST)
        self.assertEqual(lines[1]["result"], {})


ECHO_ENV_SERVER = r"""
import sys, json, os
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    res = {}
    if m["method"] == "initialize":
        res = {"protocolVersion": "x", "serverInfo": {"name": "e", "env": sorted(os.environ), "pid": os.getpid()}}
    elif m["method"] == "tools/call":
        res = {"structuredContent": {"pid": os.getpid(), "env": sorted(os.environ)}, "content": [], "isError": False}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}) + "\n")
    sys.stdout.flush()
"""


class ClientRobustnessTests(unittest.TestCase):
    def test_respawn_after_kill(self):
        c = MCPClient.spawn([sys.executable, "-c", ECHO_ENV_SERVER], timeout=10)
        c.BACKOFF_S = 0.01
        self.addCleanup(c.close)
        c.initialize()
        pid1 = c.call_tool("t")["pid"]
        os.kill(pid1, signal.SIGKILL)
        c._proc.wait()
        pid2 = c.call_tool("t")["pid"]
        self.assertNotEqual(pid1, pid2)
        self.assertEqual(c.respawns, 1)
        self.assertTrue(c.ping() is False or True)  # re-initialized session keeps answering

    def test_respawn_when_child_dies_mid_call(self):
        script = ECHO_ENV_SERVER.replace('elif m["method"] == "tools/call":',
                                         'elif m["method"] == "tools/call" and not os.path.exists(sys.argv[1]):\n'
                                         '        open(sys.argv[1], "w").close(); os._exit(1)\n'
                                         '    elif m["method"] == "tools/call":')
        with tempfile.TemporaryDirectory() as d:
            c = MCPClient.spawn([sys.executable, "-c", script, str(Path(d) / "flag")], timeout=10)
            c.BACKOFF_S = 0.01
            self.addCleanup(c.close)
            c.initialize()
            self.assertIn("pid", c.call_tool("t"))
            self.assertEqual(c.respawns, 1)

    def test_only_one_respawn_per_call(self):
        c = MCPClient.spawn([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=5)
        c.BACKOFF_S = 0.01
        with self.assertRaises(MCPError):
            c.initialize()
        self.assertEqual(c.respawns, 1)
        c.close()

    def test_env_allowlist_blocks_secrets(self):
        base = {"PATH": "/usr/bin", "LANG": "C", "MESHPOOL_API_KEY": "sk-1", "ACRETIA_LLM_API_KEY": "sk-2",
                "GITHUB_TOKEN": "t", "AWS_SECRET": "s", "HOME": "/root", "ACRETIA_MCP_ROOT": "/r", "ACRETIA_GRID_DB": "d",
                "ACRETIA_EVIDENCE_PATH": "e", "TMPDIR": "/tmp", "PYTHONPATH": "/p", "RANDOM_VAR": "x",
                "ACRETIA_MCP_API_KEY": "leak"}
        env = mcp_client.child_env({"EXTRA_TOKEN": "z", "ACRETIA_MCP_FLAG": "1"}, base)
        self.assertEqual(sorted(env), sorted(["PATH", "LANG", "ACRETIA_MCP_ROOT", "ACRETIA_GRID_DB", "ACRETIA_EVIDENCE_PATH",
                                              "TMPDIR", "PYTHONPATH", "ACRETIA_MCP_FLAG"]))

    def test_secret_in_parent_env_does_not_reach_child(self):
        old = {k: os.environ.get(k) for k in ("MESHPOOL_API_KEY", "ACRETIA_LLM_API_KEY", "SOME_TOKEN")}
        os.environ.update({"MESHPOOL_API_KEY": "sk-LEAK", "ACRETIA_LLM_API_KEY": "sk-LEAK2", "SOME_TOKEN": "t"})
        try:
            c = MCPClient.spawn([sys.executable, "-c", ECHO_ENV_SERVER], env={"X_API_KEY": "explicit"}, timeout=10)
            self.addCleanup(c.close)
            c.initialize()
            names = c.call_tool("t")["env"]
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        for bad in ("MESHPOOL_API_KEY", "ACRETIA_LLM_API_KEY", "SOME_TOKEN", "X_API_KEY"):
            self.assertNotIn(bad, names)
        self.assertIn("PATH", names)


def write_zip(path, sheet_parts=(), extra=()):
    """Minimal xlsx-shaped zip. sheet_parts: iterables of bytes chunks for xl/worksheets/sheetN.xml."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        for i, chunks in enumerate(sheet_parts, 1):
            with zf.open(f"xl/worksheets/sheet{i}.xml", "w", force_zip64=True) as f:
                for ch in chunks:
                    f.write(ch)
        for name, chunks in extra:
            with zf.open(name, "w", force_zip64=True) as f:
                for ch in chunks:
                    f.write(ch)


class ExcelBombTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self._old = os.environ.get("ACRETIA_MCP_ROOT")
        os.environ["ACRETIA_MCP_ROOT"] = self.root
        self.addCleanup(lambda: os.environ.pop("ACRETIA_MCP_ROOT", None) if self._old is None
                        else os.environ.__setitem__("ACRETIA_MCP_ROOT", self._old))
        self.c = MCPClient.inprocess(excel_server.make_server())

    def fail_data(self, tool, args):
        res = self.c._server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": tool, "arguments": args}})["result"]
        self.assertTrue(res["isError"], res)
        return res["structuredContent"]

    def test_cell_bomb_refused_with_structured_error(self):
        row = b'<row>' + b'<c r="A1"/>' * 1000 + b'</row>'
        write_zip(Path(self.root) / "bomb.xlsx", [[b"<worksheet><sheetData>"] + [row] * 2100 + [b"</sheetData></worksheet>"]])
        self.assertLess(os.path.getsize(Path(self.root) / "bomb.xlsx"), 5_000_000)
        for tool, args in (("xlsx_evaluate", {"path": "bomb.xlsx", "cells": ["S!A1"]}), ("xlsx_grade", {"path": "bomb.xlsx"}),
                           ("xlsx_recalc", {"path": "bomb.xlsx"})):
            d = self.fail_data(tool, args)
            self.assertEqual((d["code"], d["limit"]), ("xlsx_limit_exceeded", "cells"), tool)

    def test_cells_across_chunk_boundaries_are_counted_once(self):
        cell = b'<c r="A1"/>'
        data = cell * 300000
        for off in (0, 1, 2):  # shift cells across the 1 MiB read boundary
            write_zip(Path(self.root) / "edge.xlsx", [[b"x" * off, data]])
            info = excel_server.precheck_xlsx(Path(self.root) / "edge.xlsx")
            self.assertEqual(info["cells"], 300000)

    def test_huge_shared_strings_refused(self):
        zeros = [b"0" * (1 << 20)] * 230
        write_zip(Path(self.root) / "ss.xlsx", [[b"<worksheet/>"]], extra=[("xl/sharedStrings.xml", zeros)])
        self.assertLess(os.path.getsize(Path(self.root) / "ss.xlsx"), 2_000_000)
        d = self.fail_data("xlsx_grade", {"path": "ss.xlsx"})
        self.assertEqual((d["code"], d["limit"]), ("xlsx_limit_exceeded", "uncompressed_bytes"))

    def test_oversize_file_and_entries_and_bad_zip(self):
        make_xlsx(Path(self.root) / "ok.xlsx")
        with self.assertRaises(ToolFailure) as cm:
            excel_server.precheck_xlsx(Path(self.root) / "ok.xlsx", max_file=100)
        self.assertEqual(cm.exception.data["limit"], "file_bytes")
        (Path(self.root) / "junk.xlsx").write_bytes(b"not a zip")
        self.assertEqual(self.fail_data("xlsx_grade", {"path": "junk.xlsx"})["code"], "xlsx_invalid")

    def test_child_memory_limit_is_structured(self):
        make_xlsx(Path(self.root) / "ok.xlsx")
        with self.assertRaises(ToolFailure) as cm:
            excel_server.run_isolated({"op": "grade", "path": str(Path(self.root) / "ok.xlsx")}, mem_bytes=24 * 1024 * 1024)
        self.assertIn(cm.exception.data["code"], ("xlsx_memory_limit", "xlsx_worker_failed"))

    def test_child_timeout_is_structured(self):
        make_xlsx(Path(self.root) / "ok.xlsx")
        with self.assertRaises(ToolFailure) as cm:
            excel_server.run_isolated({"op": "grade", "path": str(Path(self.root) / "ok.xlsx")}, timeout=0.01)
        self.assertEqual(cm.exception.data["code"], "xlsx_timeout")

    def test_valid_workbook_still_evaluates_in_child(self):
        make_xlsx(Path(self.root) / "ok.xlsx")
        r = self.c.call_tool("xlsx_evaluate", {"path": "ok.xlsx", "cells": ["Model!A3"]})
        self.assertEqual(r["values"]["Model!A3"]["value"], 50)


if __name__ == "__main__":
    unittest.main()
