"""Evidence bundle: hash chain, tamper detection, concurrency, resume, payload store."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from om.contracts import ContractError, sha256_hex
from src.harness.evidence import (GENESIS_HASH, EvidenceBundle, _canon_str, _record_hash, export, head_hash,
                                  traced, verify)


def _rewrite(path, recs):
    Path(path).write_text("".join(_canon_str(r) + "\n" for r in recs), encoding="utf-8")


def _rechain(recs, job=None):
    """Recompute seq/prev/hash so only the *semantic* tamper remains."""
    prev = GENESIS_HASH
    for i, r in enumerate(recs):
        r["seq"], r["prev_hash"] = i, prev
        if job:
            r["job_id"] = job
        r["record_hash"] = _record_hash(r)
        prev = r["record_hash"]
    return recs


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "job1.jsonl"
        self.b = EvidenceBundle(self.path)
        self.addCleanup(self.b.close)
        for i in range(5):
            self.b.append("tool", {"i": i}, source=f"doc{i}", page=i, bbox_norm=[0, 0.1, 0.5, 1], output={"o": i})

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def recs(self):
        return [json.loads(x) for x in self.lines()]

    def put(self, lines):
        self.path.write_text("".join(x + "\n" for x in lines), encoding="utf-8")

    def test_valid_chain_and_fields(self):
        r = self.recs()
        self.assertEqual(verify(self.path).n_records, 5)
        self.assertTrue(verify(self.path).ok)
        self.assertEqual(r[0]["prev_hash"], GENESIS_HASH)
        self.assertEqual([x["seq"] for x in r], list(range(5)))
        self.assertEqual(r[1]["prev_hash"], r[0]["record_hash"])
        self.assertTrue(r[0]["timestamp"].endswith("Z"))
        self.assertEqual(r[0]["args_sha256"], sha256_hex('{"i":0}'))
        self.assertEqual(r[0]["job_id"], "job1")
        self.assertNotIn('"o":0', self.path.read_text())
        self.assertEqual(head_hash(self.path), r[-1]["record_hash"])
        self.assertEqual(len(export(self.path)), 5)

    def test_bytes_hashed_raw_and_unicode(self):
        rec = self.b.append("t", b"\xff\x00", source="s", output="é")
        self.assertEqual(rec["args_sha256"], sha256_hex(b"\xff\x00"))
        self.assertEqual(rec["output_sha256"], sha256_hex('"é"'))

    def test_edited_field(self):
        ls = self.lines()
        r = json.loads(ls[2])
        r["source"] = "forged"
        ls[2] = _canon_str(r)
        self.put(ls)
        res = verify(self.path)
        self.assertEqual((res.ok, res.first_bad_seq), (False, 2))

    def test_deleted_line(self):
        ls = self.lines()
        del ls[2]
        self.put(ls)
        self.assertEqual(verify(self.path).first_bad_seq, 2)

    def test_deleted_first_line(self):
        self.put(self.lines()[1:])
        self.assertEqual(verify(self.path).first_bad_seq, 0)

    def test_inserted_line(self):
        ls = self.lines()
        fake = json.loads(ls[1])
        fake["tool"] = "fake"
        fake["record_hash"] = _record_hash(fake)
        ls.insert(2, _canon_str(fake))
        self.put(ls)
        self.assertEqual(verify(self.path).first_bad_seq, 2)

    def test_reordered_lines(self):
        ls = self.lines()
        ls[2], ls[3] = ls[3], ls[2]
        self.put(ls)
        self.assertEqual(verify(self.path).first_bad_seq, 2)

    def test_truncated_last_line(self):
        data = self.path.read_bytes()
        self.path.write_bytes(data[:-20])
        res = verify(self.path)
        self.assertEqual((res.ok, res.first_bad_seq), (False, 4))
        b2 = EvidenceBundle(self.path)
        self.addCleanup(b2.close)
        with self.assertRaises(ContractError):
            b2.append("t", {}, source="s", output=1)

    def test_truncated_at_line_boundary_is_not_detectable_by_chain_but_head_changes(self):
        before = head_hash(self.path)
        self.put(self.lines()[:-1])
        self.assertTrue(verify(self.path).ok)
        self.assertNotEqual(head_hash(self.path), before)  # why callers anchor head_hash externally

    def test_duplicated_line(self):
        ls = self.lines()
        ls.insert(3, ls[2])
        self.put(ls)
        self.assertEqual(verify(self.path).first_bad_seq, 3)

    def test_wrong_job_id_edit(self):
        recs = _rechain(self.recs(), job="other")
        _rewrite(self.path, recs)
        res = verify(self.path)
        self.assertEqual(res.first_bad_seq, 0)
        self.assertIn("job_id", res.reason)

    def test_replaced_by_other_jobs_valid_chain(self):
        other = Path(self.tmp.name) / "job2.jsonl"
        with EvidenceBundle(other) as ob:
            for i in range(3):
                ob.append("t", {"i": i}, source="x", output=i)
        self.assertTrue(verify(other).ok)
        self.path.write_bytes(other.read_bytes())
        res = verify(self.path)
        self.assertFalse(res.ok)
        self.assertEqual(res.first_bad_seq, 0)
        self.assertIn("job_id", res.reason)

    def test_non_monotonic_timestamp_and_equal_allowed(self):
        recs = self.recs()
        recs[3]["timestamp"] = "2000-01-01T00:00:00.000000Z"
        _rewrite(self.path, _rechain(recs))
        res = verify(self.path)
        self.assertEqual(res.first_bad_seq, 3)
        self.assertIn("timestamp", res.reason)
        recs = self.recs()
        for r in recs:
            r["timestamp"] = "2030-01-01T00:00:00.000000Z"
        _rewrite(self.path, _rechain(recs))
        self.assertTrue(verify(self.path).ok)

    def test_bbox_outside_unit_range(self):
        recs = self.recs()
        recs[1]["bbox_norm"] = [0, 0, 1.01, 1]
        _rewrite(self.path, _rechain(recs))
        res = verify(self.path)
        self.assertEqual(res.first_bad_seq, 1)
        self.assertIn("bbox", res.reason)

    def test_append_rejects_bad_bbox(self):
        for bb in ([0, 0, 2, 1], [-0.1, 0, 1, 1], [0, 0, 1], "x"):
            with self.assertRaises(ContractError):
                self.b.append("t", {}, source="s", bbox_norm=bb, output=1)
        self.assertEqual(verify(self.path).n_records, 5)

    def test_concurrency_threads(self):
        p = Path(self.tmp.name) / "conc.jsonl"
        b = EvidenceBundle(p)
        self.addCleanup(b.close)

        def work(t):
            for i in range(50):
                b.append("t", {"t": t, "i": i}, source="s", output=i)
        ts = [threading.Thread(target=work, args=(t,)) for t in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        res = verify(p)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.n_records, 400)

    def test_two_handles_same_file(self):
        b2 = EvidenceBundle(self.path)
        self.addCleanup(b2.close)
        b2.append("t", {}, source="s", output=1)
        self.b.append("t", {}, source="s", output=2)
        res = verify(self.path)
        self.assertTrue(res.ok, res)
        self.assertEqual(res.n_records, 7)

    def test_reopen_resumes_chain(self):
        head = head_hash(self.path)
        self.b.close()
        b2 = EvidenceBundle(self.path)
        self.addCleanup(b2.close)
        rec = b2.append("t", {}, source="s", output=1)
        self.assertEqual((rec["seq"], rec["prev_hash"]), (5, head))
        self.assertTrue(verify(self.path).ok)

    def test_payload_round_trip(self):
        p = Path(self.tmp.name) / "pay.jsonl"
        b = EvidenceBundle(p, store_payloads=True)
        self.addCleanup(b.close)
        rec = b.append("t", {"a": 1}, source="s", output={"x": [1, 2]})
        self.assertEqual(json.loads(b.load_payload(rec["args_sha256"])), {"a": 1})
        self.assertEqual(json.loads(b.load_payload(rec["output_sha256"])), {"x": [1, 2]})
        self.assertEqual(sha256_hex(b.load_payload(rec["output_sha256"])), rec["output_sha256"])
        self.assertTrue(verify(p).ok)

    def test_traced(self):
        @traced(self.b, "add", source_fn=lambda res, a, b: {"source": f"calc:{res}", "page": 3})
        def add(a, b):
            return a + b

        @traced(self.b, "plain")
        def plain(x=1):
            return {"x": x}
        self.assertEqual(add(1, 2), 3)
        plain(x=5)
        r = self.recs()
        self.assertEqual((r[5]["tool"], r[5]["source"], r[5]["page"]), ("add", "calc:3", 3))
        self.assertEqual(r[5]["output_sha256"], sha256_hex("3"))
        self.assertEqual((r[6]["tool"], r[6]["source"]), ("plain", "plain"))
        self.assertTrue(verify(self.path).ok)

    def test_missing_and_empty(self):
        self.assertFalse(verify(Path(self.tmp.name) / "nope.jsonl").ok)
        e = Path(self.tmp.name) / "empty.jsonl"
        EvidenceBundle(e).close()
        self.assertEqual((verify(e).ok, verify(e).n_records, head_hash(e)), (True, 0, GENESIS_HASH))


if __name__ == "__main__":
    unittest.main()
