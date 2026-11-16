import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.harness.admin import AdminError, PermissionDenied, agents, audit_log, mcp_tools, sources, spend
from src.harness.ledger import BudgetExceeded, Ledger

ROOT = Path(__file__).resolve().parent.parent
OWNER = {"user_id": "u1", "role": "owner"}
ADMIN = {"user_id": "u2", "role": "admin"}
MEMBER = {"user_id": "u3", "role": "member"}
VIEWER = {"user_id": "u4", "role": "viewer"}

ECHO_SERVER = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from src.harness.router import ToolRegistry
from src.harness.mcp.server import MCPServer
reg = ToolRegistry()
reg.register("echo", lambda text: {{"echo": text}}, {{"type": "object", "properties": {{"text": {{"type": "string"}}}}, "required": ["text"]}}, description="echo")
reg.register("secret", lambda: {{"x": 1}}, {{"type": "object", "properties": {{}}}}, description="hidden")
MCPServer("echo", reg).serve_stdio()
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "a.sqlite")


class RolesAndAudit(Base):
    def test_member_and_viewer_cannot_mutate(self):
        for who in (MEMBER, VIEWER):
            with self.assertRaises(PermissionDenied):
                agents.set_enabled("o1", "ag", False, who, db=self.db)
            with self.assertRaises(PermissionDenied):
                spend.set_limit("o1", "org", None, 5, "total", who, db=self.db)
            with self.assertRaises(PermissionDenied):
                sources.register_source("o1", "web", "env:X", who, db=self.db)
            with self.assertRaises(PermissionDenied):
                mcp_tools.register_mcp_server("o1", "s", [sys.executable, "x.py"], {}, "*", who, db=self.db)
        self.assertEqual(audit_log("o1", db=self.db), [])

    def test_audit_rows_and_append_only(self):
        agents.set_enabled("o1", "ag", False, ADMIN, db=self.db)
        agents.set_enabled("o1", "ag", True, OWNER, db=self.db)
        rows = audit_log("o1", db=self.db)
        self.assertEqual([r["action"] for r in rows], ["agent.set_enabled"] * 2)
        self.assertEqual(rows[0]["before"], {"enabled": True})
        self.assertEqual(rows[0]["after"], {"enabled": False})
        self.assertEqual((rows[0]["actor_id"], rows[0]["actor_role"]), ("u2", "admin"))
        self.assertGreater(rows[0]["at"], 0)
        from om import storage
        c = storage.connect(self.db)
        with self.assertRaises(Exception):
            c.execute("DELETE FROM admin_audit")
        with self.assertRaises(Exception):
            c.execute("UPDATE admin_audit SET action='x'")
        c.close()
        spend.set_limit("o1", "org", None, 5, "total", ADMIN, db=self.db)
        spend.set_limit("o1", "org", None, 7, "total", ADMIN, db=self.db)
        r = audit_log("o1", action="spend.set_limit", db=self.db)
        self.assertEqual((r[1]["before"], r[1]["after"]), ({"limit_usd": 5.0}, {"limit_usd": 7.0}))


class Agents(Base):
    def test_default_toggle_list_filter_isolation(self):
        self.assertTrue(agents.is_enabled("o1", "ag", db=self.db))
        agents.set_enabled("o1", "ag", False, ADMIN, db=self.db)
        self.assertFalse(agents.is_enabled("o1", "ag", db=self.db))
        self.assertTrue(agents.is_enabled("o2", "ag", db=self.db))
        self.assertEqual(agents.list_agents("o2", db=self.db), [])
        listed = agents.list_agents("o1", known=["b"], db=self.db)
        self.assertEqual([(x["agent_id"], x["enabled"]) for x in listed], [("ag", False), ("b", True)])
        cat = [{"id": "ag"}, {"id": "b"}]
        self.assertEqual(agents.filter_enabled("o1", cat, db=self.db), [{"id": "b"}])
        self.assertEqual(len(agents.filter_enabled("o2", cat, db=self.db)), 2)


class Spend(Base):
    def kw(self):
        return {"db": self.db}

    def test_order_deal_team_org(self):
        spend.set_limit("o1", "deal", "d1", 1, "total", ADMIN, **self.kw())
        spend.set_limit("o1", "team", "t1", 5, "total", ADMIN, **self.kw())
        spend.set_limit("o1", "org", None, 10, "monthly", ADMIN, **self.kw())
        g = spend.guard_for("o1", "t1", "d1", db=self.db)
        with self.assertRaises(BudgetExceeded) as cm:
            g.check(0, 0, 2.0)
        self.assertEqual((cm.exception.scope, cm.exception.scope_id), ("deal", "d1"))
        # team hit when the deal has room
        spend.set_limit("o1", "deal", "d1", 100, "total", ADMIN, **self.kw())
        with self.assertRaises(BudgetExceeded) as cm:
            g.check(0, 0, 6.0)
        self.assertEqual(cm.exception.scope, "team")
        spend.set_limit("o1", "team", "t1", 100, "total", ADMIN, **self.kw())
        with self.assertRaises(BudgetExceeded) as cm:
            g.check(0, 0, 11.0)
        self.assertEqual((cm.exception.scope, cm.exception.period), ("org", "monthly"))
        g.check(0, 0, 9.0)

    def test_usage_blocks_and_precheck_before_call(self):
        spend.set_limit("o1", "team", "t1", 1.0, "total", OWNER, **self.kw())
        spend.record("o1", "t1", "d1", "j", 0.9, db=self.db)
        led = spend.OrgLedger("o1", "t1", "d1", db=self.db)
        calls = []
        with self.assertRaises(BudgetExceeded):
            led.precheck("j", "claude-opus-4", 10_000, 4_000)   # worst case far above $0.10
        self.assertEqual(calls, [])
        self.assertEqual(spend.usage("o1", "team", "t1", "total", db=self.db), 0.9)
        led.record("j", "claude-opus-4", 1000, 100)
        self.assertGreater(spend.usage("o1", "team", "t1", "total", db=self.db), 0.9)
        self.assertEqual(spend.usage("o1", "deal", "d1", "total", db=self.db), spend.usage("o1", "team", "t1", "total", db=self.db))
        self.assertIsInstance(led, Ledger)

    def test_monthly_vs_total_and_isolation(self):
        old = time.time() - 70 * 86400
        spend.record("o1", "t1", None, "j", 9.0, at=old, db=self.db)
        spend.record("o2", "t1", None, "j", 4.0, db=self.db)
        spend.record("o1", "t1", None, "j", 1.0, db=self.db)
        self.assertEqual(spend.usage("o1", "team", "t1", "monthly", db=self.db), 1.0)
        self.assertEqual(spend.usage("o1", "team", "t1", "total", db=self.db), 10.0)
        self.assertEqual(spend.usage("o1", "org", None, "total", db=self.db), 10.0)
        spend.set_limit("o1", "team", "t1", 1.5, "monthly", ADMIN, db=self.db)
        spend.guard_for("o1", "t1", db=self.db).check(0, 0, 0.5)
        with self.assertRaises(BudgetExceeded):
            spend.guard_for("o1", "t1", db=self.db).check(0, 0, 0.6)
        # org o2 has no limit and is unaffected; limits of o1 never apply to o2
        spend.guard_for("o2", "t1", db=self.db).check(0, 0, 1000)
        self.assertEqual(spend.get_limits("o2", db=self.db), [])

    def test_validation(self):
        for bad in (dict(scope="x", scope_id="a", limit_usd=1, period="total"),
                    dict(scope="team", scope_id="a", limit_usd=-1, period="total"),
                    dict(scope="team", scope_id="a", limit_usd=1, period="weekly"),
                    dict(scope="team", scope_id=None, limit_usd=1, period="total")):
            with self.assertRaises(AdminError):
                spend.set_limit("o1", actor=ADMIN, db=self.db, **bad)

    def test_concurrent_record_is_atomic(self):
        errs = []

        def work():
            try:
                for _ in range(25):
                    spend.record("o1", "t1", "d1", "j", 0.01, db=self.db)
            except Exception as e:  # pragma: no cover
                errs.append(e)
        ts = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertAlmostEqual(spend.usage("o1", "org", None, "total", db=self.db), 2.0, places=6)


class Sources(Base):
    def test_register_validate_and_dashboard(self):
        with self.assertRaises(AdminError):
            sources.register_source("o1", "nope", "env:K", ADMIN, db=self.db)
        with self.assertRaises(AdminError):
            sources.register_source("o1", "web", "sk-live-abc123", ADMIN, db=self.db)
        sid = sources.register_source("o1", "web", "secret://vault/web", ADMIN, db=self.db)
        other = sources.register_source("o1", "sec", "env:SEC", ADMIN, db=self.db)
        never = sources.register_source("o1", "web", "env:W2", ADMIN, db=self.db)
        now = 1_800_000_000.0
        sources.record_sync("o1", sid, "ok", 10, 0, at=now - 3600, db=self.db)
        sources.record_sync("o1", sid, "partial", 5, 2, at=now - 600, db=self.db)
        sources.record_sync("o1", other, "error", 0, 3, at=now - 25 * 3600, db=self.db)
        d = {r["source_id"]: r for r in sources.dashboard("o1", now=now, db=self.db)}
        self.assertFalse(d[sid]["stale"])
        self.assertEqual((d[sid]["status"], d[sid]["last_items"], d[sid]["total_items"], d[sid]["total_errors"]), ("partial", 5, 15, 2))
        self.assertTrue(d[other]["stale"])
        self.assertTrue(d[never]["stale"])
        self.assertEqual(d[never]["status"], "never_synced")
        self.assertEqual(d[sid]["config_ref"], "secret://vault/web")

    def test_isolation(self):
        sid = sources.register_source("o1", "web", "env:K", ADMIN, db=self.db)
        self.assertEqual(sources.dashboard("o2", db=self.db), [])
        with self.assertRaises(AdminError):
            sources.record_sync("o2", sid, "ok", 1, 0, db=self.db)
        self.assertEqual(len(audit_log("o1", db=self.db)), 1)
        self.assertEqual(audit_log("o2", db=self.db), [])


class McpTools(Base):
    def setUp(self):
        super().setUp()
        self.script = os.path.join(self.tmp.name, "echo_server.py")
        Path(self.script).write_text(ECHO_SERVER)
        self.cmd = [sys.executable, self.script]

    def reg(self, org="o1", name="echo", allow=("echo",), **kw):
        return mcp_tools.register_mcp_server(org, name, kw.pop("command", self.cmd), kw.pop("env_refs", {}), list(allow) if allow != "*" else "*",
                                             kw.pop("actor", ADMIN), db=self.db, **kw)

    def test_refusals(self):
        with self.assertRaises(AdminError):
            self.reg(command=f"{sys.executable} {self.script}")
        with self.assertRaises(AdminError):
            self.reg(command=["bash", "-c", "id"])
        with self.assertRaises(AdminError):
            self.reg(command=["/tmp/python", "x.py"])
        with self.assertRaises(AdminError):
            self.reg(command="http://example.com/mcp")
        with self.assertRaises(AdminError):
            self.reg(command="https://127.0.0.1/mcp")
        with self.assertRaises(AdminError):
            self.reg(command="https://10.0.0.5/mcp")
        with self.assertRaises(AdminError):
            self.reg(name="bad.name")
        with self.assertRaises(AdminError):
            self.reg(env_refs={"TOKEN": "sk-rawvalue"})
        mcp_tools.set_executable_allowlist("o1", ["node"], ADMIN, db=self.db)
        with self.assertRaises(AdminError):
            self.reg()                       # python no longer allowed for this org
        self.reg(org="o2")                   # other org unaffected
        with self.assertRaises(AdminError):
            mcp_tools.set_executable_allowlist("o1", ["bash"], ADMIN, db=self.db)

    def test_public_url_registers(self):
        r = self.reg(command="https://mcp.example.com/sse", allow=("ping",), resolver=lambda h, p: ["93.184.216.34"])
        self.assertEqual(r["transport"], "url")
        tools = mcp_tools.tools_for_user("o1", MEMBER, db=self.db)
        self.assertEqual([t["name"] for t in tools], ["org.echo.ping"])

    def test_prefix_allow_untrusted_evidence_and_disable(self):
        self.reg()
        tools = mcp_tools.tools_for_user("o1", MEMBER, db=self.db)
        self.assertEqual([t["name"] for t in tools], ["org.echo.echo"])        # `secret` filtered by allow_tools
        self.assertTrue(all(t["untrusted"] for t in tools))
        self.assertEqual(mcp_tools.tools_for_user("o2", MEMBER, db=self.db), [])
        with self.assertRaises(PermissionDenied):
            mcp_tools.tools_for_user("o1", {"user_id": "x", "role": "member", "org_id": "o2"}, db=self.db)
        ev = os.path.join(self.tmp.name, "ev", "job.jsonl")
        out = mcp_tools.call_tool("o1", MEMBER, "org.echo.echo", {"text": "hi"}, evidence_path=ev, db=self.db)
        self.assertEqual(out["result"], {"echo": "hi"})
        self.assertTrue(out["untrusted"])
        recs = [json.loads(l) for l in Path(ev).read_text().splitlines()]
        self.assertEqual((len(recs), recs[0]["tool"], recs[0]["source"]), (1, "org.echo.echo", "org.echo.echo"))
        with self.assertRaises(AdminError):
            mcp_tools.call_tool("o1", MEMBER, "org.echo.secret", {}, evidence_path=ev, db=self.db)
        with self.assertRaises(AdminError):
            mcp_tools.call_tool("o2", MEMBER, "org.echo.echo", {"text": "x"}, evidence_path=ev, db=self.db)
        with self.assertRaises(PermissionDenied):
            mcp_tools.set_server_enabled("o1", "echo", False, MEMBER, db=self.db)
        mcp_tools.set_server_enabled("o1", "echo", False, ADMIN, db=self.db)
        self.assertEqual(mcp_tools.tools_for_user("o1", MEMBER, db=self.db), [])
        self.assertEqual(
            [r["action"] for r in audit_log("o1", db=self.db)], ["mcp.register", "mcp.set_enabled"])

    def test_wildcard_and_env_refs_and_bad_server(self):
        os.environ["ACRETIA_TEST_TOKEN"] = "tok"
        self.addCleanup(os.environ.pop, "ACRETIA_TEST_TOKEN", None)
        self.reg(allow="*", env_refs={"TOKEN": "env:ACRETIA_TEST_TOKEN"})
        self.reg(name="broken", command=[sys.executable, os.path.join(self.tmp.name, "missing.py")], allow="*")
        tools, errors = mcp_tools.tools_report("o1", MEMBER, timeout=5, db=self.db)
        self.assertEqual(sorted(t["name"] for t in tools), ["org.echo.echo", "org.echo.secret"])
        self.assertEqual([e["server"] for e in errors], ["broken"])
        stored = [s for s in mcp_tools.list_servers("o1", db=self.db) if s["name"] == "echo"][0]
        self.assertEqual(stored["env_refs"], {"TOKEN": "env:ACRETIA_TEST_TOKEN"})
        self.assertNotIn("tok", json.dumps(stored))


if __name__ == "__main__":
    unittest.main()
