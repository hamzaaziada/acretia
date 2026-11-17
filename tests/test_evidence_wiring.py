"""FP-S2e3: evidence anchors are sealed by the research run and the MCP server, rollback and key custody are
enforced, and a torn tail is repaired on resume. Offline; the key lives in a temp dir outside the evidence dir."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from om import storage as st
from om.contracts import ContractError
from src.harness import evidence as ev
from src.harness.evidence import EvidenceBundle, verify
from src.harness.mcp.protocol import encode
from src.harness.mcp.server import MCPServer
from src.harness.research.api import ResearchRequest, ResearchResult, run_research
from src.harness.router import ToolRegistry

_ENV = ("ACRETIA_EVIDENCE_KEY", "ACRETIA_EVIDENCE_KEY_FILE", "ACRETIA_EVIDENCE_STATE_DIR")


class Base(unittest.TestCase):
    def setUp(self):
        old = {k: os.environ.get(k) for k in _ENV}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evdir = self.root / "evidence"
        self.keydir = self.root / "keys"
        os.environ.pop("ACRETIA_EVIDENCE_KEY", None)
        os.environ.pop("ACRETIA_EVIDENCE_STATE_DIR", None)
        os.environ["ACRETIA_EVIDENCE_KEY_FILE"] = str(self.keydir / "evidence.key")

    def run_job(self, job_id="res_wiring", cancel=None):
        return run_research(ResearchRequest(question="q"), evidence_dir=str(self.evdir), job_id=job_id, cancel=cancel)


class ResearchSealTests(Base):
    def test_run_seals_anchor_that_verifies_by_default(self):
        r = self.run_job()
        self.assertEqual(r.status, "succeeded")
        a = r.evidence_anchor
        self.assertEqual((a["job_id"], a["seq"], a["head_hash"]), ("res_wiring", 1, r.evidence_head))
        path = self.evdir / "res_wiring.jsonl"
        self.assertTrue(verify(path))                      # default is auto: an anchor log exists
        self.assertTrue(verify(path, "auto"))
        self.assertTrue(verify(path, a))
        self.assertEqual(ResearchResult.from_dict(r.to_dict()).evidence_anchor, a)   # additive field round-trips
        self.assertEqual(stat.S_IMODE((self.keydir / "evidence.key").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.keydir.stat().st_mode), 0o700)
        self.assertFalse(self.evdir.joinpath("evidence.key").exists())

    def test_truncating_afterwards_fails_verify(self):
        r = self.run_job()
        path = self.evdir / "res_wiring.jsonl"
        lines = path.read_text().splitlines(keepends=True)
        self.assertGreaterEqual(len(lines), 1)
        path.write_text("".join(lines[:-1]))
        self.assertTrue(verify(path, False))               # the chain alone cannot tell
        res = verify(path)
        self.assertFalse(res.ok)
        self.assertIn("truncated", res.reason)
        self.assertFalse(verify(path, r.evidence_anchor).ok)

    def test_rolling_back_to_earlier_anchor_head_fails(self):
        r1 = self.run_job()
        path = self.evdir / "res_wiring.jsonl"
        n1 = r1.evidence_anchor["n_records"]
        with EvidenceBundle(path) as b:
            b.append("more", {}, source="s", output=1)
            b.append("more", {}, source="s", output=2)
            a2 = b.seal()
        self.assertEqual(a2.seq, 2)
        self.assertTrue(verify(path))
        # (a) roll the bundle back to the first anchor's head; the second anchor is still in the log
        lines = path.read_text().splitlines(keepends=True)
        path.write_text("".join(lines[:n1]))
        res = verify(path)
        self.assertFalse(res.ok)
        self.assertIn("rollback", res.reason)
        # (b) also cut the anchor log back to the first entry: only the high-water mark (outside the data dir) knows
        log = self.evdir / "anchors.jsonl"
        log.write_text(log.read_text().splitlines(keepends=True)[0])
        res = verify(path)
        self.assertFalse(res.ok)
        self.assertIn("rollback", res.reason)
        self.assertTrue(verify(path, r1.evidence_anchor))  # the old anchor alone still matches: that is the attack

    def test_failed_and_cancelled_runs_are_sealed_too(self):
        import threading
        ev_ = threading.Event()
        ev_.set()
        r = self.run_job("res_cancelled", cancel=ev_)
        self.assertEqual(r.status, "cancelled")
        self.assertTrue(verify(self.evdir / "res_cancelled.jsonl", r.evidence_anchor))

        class Boom:
            def chat(self, *a, **k):
                raise RuntimeError("provider down")
        r = run_research(ResearchRequest(question="q"), adapter=Boom(), evidence_dir=str(self.evdir), job_id="res_failed")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.evidence_anchor["job_id"], "res_failed")
        self.assertTrue(verify(self.evdir / "res_failed.jsonl"))

    def test_resume_repairs_torn_tail_and_reports_recovery(self):
        self.run_job("res_resume")
        path = self.evdir / "res_resume.jsonl"
        with open(path, "ab") as fh:
            fh.write(b'{"job_id":"res_resume","seq":99,"to')       # crash mid-write
        self.assertFalse(verify(path, False).ok)
        r = self.run_job("res_resume")                             # same job_id: a resume
        self.assertEqual(r.status, "succeeded")
        self.assertEqual(len(r.evidence_recovery), 1)
        self.assertGreater(r.evidence_recovery[0]["discarded_bytes"], 0)
        self.assertTrue(list(self.evdir.glob("res_resume.jsonl.torn-*")))
        self.assertTrue(verify(path))
        self.assertIn("recovery", [json.loads(x)["tool"] for x in path.read_text().splitlines()])


class McpSealTests(Base):
    def registry(self):
        reg = ToolRegistry()
        reg.register("echo", lambda text="": {"text": text}, {"type": "object", "properties": {"text": {"type": "string"}}})
        return reg

    def call(self, srv, i):
        return srv.handle({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                           "params": {"name": "echo", "arguments": {"text": str(i)}}})

    def test_close_seals_the_bundle(self):
        path = self.evdir / "mcp_session.jsonl"
        srv = MCPServer("t", self.registry(), evidence_path=str(path))
        for i in range(3):
            self.call(srv, i)
        srv.close()
        self.assertIsNone(srv.seal_error)
        self.assertEqual(srv.anchor["n_records"], 3)
        self.assertTrue(verify(path))
        lines = path.read_text().splitlines(keepends=True)
        path.write_text("".join(lines[:2]))
        self.assertFalse(verify(path).ok)
        srv.close()                                                  # idempotent

    def test_stdio_shutdown_seals(self):
        import io
        path = self.evdir / "mcp_stdio.jsonl"
        srv = MCPServer("t", self.registry(), evidence_path=str(path))
        stdin = io.BytesIO(encode({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "echo", "arguments": {"text": "x"}}}))
        srv.serve_stdio(stdin, io.BytesIO())
        self.assertEqual(srv.anchor["n_records"], 1)
        self.assertTrue(verify(path))

    def test_evidence_seal_method_on_demand(self):
        path = self.evdir / "mcp_demand.jsonl"
        srv = MCPServer("t", self.registry(), evidence_path=str(path))
        self.call(srv, 1)
        r1 = srv.handle({"jsonrpc": "2.0", "id": 10, "method": "evidence/seal"})["result"]
        self.call(srv, 2)
        r2 = srv.handle({"jsonrpc": "2.0", "id": 11, "method": "evidence/seal"})["result"]
        self.assertEqual((r1["anchor"]["seq"], r1["anchor"]["n_records"]), (1, 1))
        self.assertEqual((r2["anchor"]["seq"], r2["anchor"]["n_records"]), (2, 2))
        self.assertEqual(r2["evidence_head"], r2["anchor"]["head_hash"])
        self.assertTrue(verify(path))
        srv.close()
        none = MCPServer("t", self.registry())
        self.assertIn("error", none.handle({"jsonrpc": "2.0", "id": 1, "method": "evidence/seal"}))


class KeyCustodyTests(Base):
    def make(self):
        path = self.evdir / "jobK.jsonl"
        b = EvidenceBundle(path)
        b.append("t", {}, source="s", output=1)
        self.addCleanup(b.close)
        return b

    def test_group_or_world_readable_key_file_is_refused(self):
        b = self.make()
        b.seal()
        kf = self.keydir / "evidence.key"
        for mode in (0o640, 0o604, 0o644, 0o660):
            os.chmod(kf, mode)
            with self.assertRaises(ContractError) as cm:
                b.seal()
            self.assertIn("group- or world", str(cm.exception))
            with self.assertRaises(ContractError):
                ev.check_custody(self.evdir)
            self.assertFalse(verify(self.evdir / "jobK.jsonl").ok)       # verify fails closed, never trusts it
        os.chmod(kf, 0o600)
        b.seal()
        self.assertTrue(verify(self.evdir / "jobK.jsonl"))

    def test_run_research_and_mcp_refuse_to_start_with_open_key(self):
        self.run_job("res_first")
        os.chmod(self.keydir / "evidence.key", 0o644)
        with self.assertRaises(ContractError):
            self.run_job("res_second")
        with self.assertRaises(ContractError):
            MCPServer("t", ToolRegistry(), evidence_path=str(self.evdir / "m.jsonl"))

    def test_key_file_inside_evidence_dir_is_refused(self):
        os.environ["ACRETIA_EVIDENCE_KEY_FILE"] = str(self.evdir / "keys" / "evidence.key")
        b = self.make()
        with self.assertRaises(ContractError) as cm:
            b.seal()
        self.assertIn("under the evidence data dir", str(cm.exception))
        self.assertFalse((self.evdir / "keys").exists())

    def test_env_key_needs_no_file(self):
        os.environ["ACRETIA_EVIDENCE_KEY"] = "from-a-secret-store"
        os.environ["ACRETIA_EVIDENCE_KEY_FILE"] = str(self.evdir / "keys" / "evidence.key")   # ignored
        b = self.make()
        a = b.seal()
        self.assertTrue(verify(b.path, a))
        self.assertFalse(self.keydir.exists())

    def test_default_key_path_is_not_under_the_evidence_default(self):
        self.assertEqual(ev.KEY_FILE_DEFAULT, "storage/keys/evidence.key")
        self.assertFalse(Path(ev.KEY_FILE_DEFAULT).resolve().is_relative_to(Path("storage/evidence").resolve()))


class SeqAndDefaultsTests(Base):
    def test_seq_is_monotonic_per_job_and_independent_across_jobs(self):
        a, b = EvidenceBundle(self.evdir / "jA.jsonl"), EvidenceBundle(self.evdir / "jB.jsonl")
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        a.append("t", {}, source="s", output=1)
        b.append("t", {}, source="s", output=1)
        self.assertEqual([a.seal().seq, b.seal().seq, a.seal().seq, a.seal().seq], [1, 1, 2, 3])

    def test_plain_verify_without_anchor_log_is_chain_only(self):
        path = self.root / "plain" / "jobP.jsonl"
        with EvidenceBundle(path) as b:
            b.append("t", {}, source="s", output=1)
        self.assertTrue(verify(path))

    def test_chain_only_needs_explicit_false_once_a_log_exists(self):
        b = EvidenceBundle(self.evdir / "jobC.jsonl")
        self.addCleanup(b.close)
        b.append("t", {}, source="s", output=1)
        b.append("t", {}, source="s", output=2)
        b.seal()
        os.environ["ACRETIA_EVIDENCE_KEY"] = "a-different-key"
        self.assertFalse(verify(b.path).ok)
        self.assertTrue(verify(b.path, False))

    def test_legacy_anchor_without_seq_still_verifies(self):
        key = b"legacy"
        b = EvidenceBundle(self.evdir / "jobL.jsonl")
        self.addCleanup(b.close)
        b.append("t", {}, source="s", output=1)
        head, ts = b.head_hash(), "2026-01-01T00:00:00.000000Z"
        legacy = {"job_id": "jobL", "n_records": 1, "head_hash": head, "sealed_at": ts,
                  "signature": ev._sign(key, "jobL", 1, head, ts)}
        self.assertTrue(verify(b.path, legacy, key=key))


class LeaseFenceTests(unittest.TestCase):
    def test_raw_int_ack_raises_type_error_and_does_not_delete(self):
        kv = st.SQLiteKV(":memory:")
        kv.enqueue("q", b"job")
        lease = kv.dequeue("q", lease=30)
        with self.assertRaises(TypeError):
            kv.ack(lease.id)
        with self.assertRaises(TypeError):
            kv.nack(lease.id)
        self.assertEqual(kv.qsize("q"), 1)
        self.assertTrue(kv.ack(lease))


if __name__ == "__main__":
    unittest.main()
