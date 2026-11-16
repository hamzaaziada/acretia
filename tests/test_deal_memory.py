import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from om import xlsx
from om.contracts import DealMemory
from om.deals import DealError, DealStore
from om.pptx import Deck, para, run
from om.storage import LocalBlobStore
from src.harness.evidence import EvidenceBundle


def book(rev, formula="=B1*2"):
    wb = xlsx.Workbook()
    s = wb.sheet("Model")
    s.set("A1", "Revenue")
    s.set("B1", rev)
    s.set("B2", formula)
    s.set("B3", 7)
    return wb.to_bytes()


def deck(text):
    d = Deck("T")
    s = d.blank()
    s.text(0, 0, 100000, 100000, [para(run("Fixed title")), para(run(text))])
    s2 = d.blank()
    s2.text(0, 0, 100000, 100000, [para(run("Same"))])
    return d.save()


class DealMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.blobs = LocalBlobStore(os.path.join(self.tmp.name, "blobs"))
        self.s = DealStore(os.path.join(self.tmp.name, "d.sqlite"), self.blobs)
        self.deal = self.s.create_deal("Project Atlas")
        self.id = self.deal.deal_id

    def test_definitions_round_trip(self):
        self.s.set_definition(self.id, "Adjusted EBITDA", "EBITDA before SBC and one-offs")
        m = self.s.set_formatting(self.id, units="USD m", negative_style="(1.0)", decimals=1, fiscal_year_end="12-31")
        self.assertEqual(DealMemory.from_json(m.to_json()), m)
        self.assertEqual(self.s.get(self.id).definitions["Adjusted EBITDA"], "EBITDA before SBC and one-offs")
        self.assertEqual(self.s.get(self.id).formatting["units"], "USD m")
        self.assertEqual([v.version for v in m.versions], [1, 2, 3])
        self.assertEqual([d.deal_id for d in self.s.list()], [self.id])

    def test_diff_definitions(self):
        self.s.set_definition(self.id, "Net Debt", "Debt less cash")
        self.s.set_definition(self.id, "Net Debt", "Debt less cash and ST investments")
        d = self.s.diff_definitions(self.id, 2, 3)
        self.assertEqual(d["definitions"]["changed"]["Net Debt"]["new"], "Debt less cash and ST investments")
        self.assertEqual(self.s.diff_definitions(self.id, 1, 2)["definitions"]["added"], {"Net Debt": "Debt less cash"})
        with self.assertRaises(DealError):
            self.s.diff_definitions(self.id, 1, 99)

    def test_xlsx_diff_exactly_two_cells(self):
        self.s.save_deliverable(self.id, "model.xlsx", book(100), "xlsx")
        self.s.save_deliverable(self.id, "model.xlsx", book(110, "=B1*3"), "xlsx")
        d = self.s.diff(self.id, "model.xlsx", 1, 2)
        self.assertEqual(len(d["changes"]), 2, d)
        by = {c["ref"]: c for c in d["changes"]}
        self.assertEqual((by["B1"]["old"], by["B1"]["new"]), (100.0, 110.0))
        self.assertEqual((by["B2"]["old"], by["B2"]["new"]), ("=B1*2", "=B1*3"))
        self.assertEqual(by["B1"]["sheet"], "Model")
        self.assertFalse(d["identical"])

    def test_pptx_diff(self):
        self.s.save_deliverable(self.id, "deck.pptx", deck("EBITDA 10"), "pptx")
        self.s.save_deliverable(self.id, "deck.pptx", deck("EBITDA 12"), "pptx")
        d = self.s.diff(self.id, "deck.pptx", 1, 2)
        self.assertEqual(d["changes"], [{"slide": 1, "removed": ["EBITDA 10"], "added": ["EBITDA 12"]}])

    def test_text_diff(self):
        self.s.save_deliverable(self.id, "a.json", b'{"a": 1}\n', "json")
        self.s.save_deliverable(self.id, "a.json", b'{"a": 2}\n', "json")
        u = self.s.diff(self.id, "a.json", 1, 2)["changes"][0]["unified"]
        self.assertIn('-{"a": 1}', u)
        self.assertIn('+{"a": 2}', u)

    def test_undo_restores_exact_bytes_and_keeps_history(self):
        v1, v2 = book(100), book(110)
        self.s.save_deliverable(self.id, "m.xlsx", v1, "xlsx")
        self.s.save_deliverable(self.id, "m.xlsx", v2, "xlsx")
        r = self.s.undo(self.id, "m.xlsx")
        self.assertEqual(r["version"], 3)
        got = self.s.get_version(self.id, "m.xlsx", 3)
        self.assertEqual(got, v1)
        self.assertEqual(hashlib.sha256(got).hexdigest(), hashlib.sha256(v1).hexdigest())
        self.assertEqual(self.s.get_version(self.id, "m.xlsx", 2), v2)
        self.assertEqual([h["version"] for h in self.s.history(self.id, "m.xlsx")], [1, 2, 3])
        r2 = self.s.restore(self.id, "m.xlsx", 2)
        self.assertEqual((r2["version"], r2["sha256"]), (4, hashlib.sha256(v2).hexdigest()))
        self.assertEqual(self.s.diff(self.id, "m.xlsx", 1, 3)["identical"], True)

    def test_history_monotonic_per_deliverable(self):
        for i in range(3):
            self.s.save_deliverable(self.id, "a.json", b"%d" % i, "json", note=f"n{i}")
        self.s.save_deliverable(self.id, "b.json", b"x", "json")
        self.assertEqual([h["version"] for h in self.s.history(self.id, "a.json")], [1, 2, 3])
        self.assertEqual([h["version"] for h in self.s.history(self.id, "b.json")], [1])
        self.assertEqual(self.s.deliverables(self.id), ["a.json", "b.json"])
        self.assertEqual(self.s.history(self.id, "none"), [])

    def test_adversarial(self):
        with self.assertRaises(DealError):
            self.s.get("deal-nope")
        with self.assertRaises(DealError):
            self.s.save_deliverable("deal-nope", "x", b"1", "json")
        with self.assertRaises(DealError):
            self.s.history("deal-nope", "x")
        self.s.save_deliverable(self.id, "a.json", b"1", "json")
        for v in (0, -1, 2, 99, True, "1", None):
            with self.assertRaises(DealError, msg=repr(v)):
                self.s.get_version(self.id, "a.json", v)
        with self.assertRaises(DealError):
            self.s.undo(self.id, "a.json")
        with self.assertRaises(DealError):
            self.s.undo(self.id, "missing")
        with self.assertRaises(DealError):
            self.s.save_deliverable(self.id, "a.json", b"1", "exe")
        with self.assertRaises(DealError):
            self.s.save_deliverable(self.id, "a.json", "text", "json")
        with self.assertRaises(DealError):
            self.s.set_definition(self.id, " ", "x")

    def test_corrupt_zip_as_xlsx_and_pptx(self):
        self.s.save_deliverable(self.id, "c.xlsx", b"not a zip", "xlsx")
        self.s.save_deliverable(self.id, "c.xlsx", book(1), "xlsx")
        with self.assertRaises(DealError) as cm:
            self.s.diff(self.id, "c.xlsx", 1, 2)
        self.assertIn("unreadable", str(cm.exception))
        self.s.save_deliverable(self.id, "c.pptx", b"junk", "pptx")
        self.s.save_deliverable(self.id, "c.pptx", b"junk2", "pptx")
        with self.assertRaises(DealError):
            self.s.diff(self.id, "c.pptx", 1, 2)

    def test_org_scoping(self):
        self.s.save_deliverable(self.id, "a.json", b"1", "json")
        other = self.s.for_org("acme")
        self.assertEqual(other.list(), [])
        with self.assertRaises(DealError):
            other.get(self.id)
        with self.assertRaises(DealError):
            other.history(self.id, "a.json")
        with self.assertRaises(DealError):
            other.get_version(self.id, "a.json", 1)
        with self.assertRaises(DealError):
            other.save_deliverable(self.id, "a.json", b"2", "json")
        self.assertEqual(len(self.s.history(self.id, "a.json")), 1)
        d2 = other.create_deal("Own")
        self.assertEqual([d.deal_id for d in other.list()], [d2.deal_id])
        self.assertEqual([d.deal_id for d in self.s.list()], [self.id])


if __name__ == "__main__":
    unittest.main()


_WORKER = """
import sys, threading, json
sys.path.insert(0, sys.argv[1])
from om.deals import DealStore
from om.storage import LocalBlobStore
db, blobs, deal, tag = sys.argv[2:6]
st = DealStore(db, LocalBlobStore(blobs))
errs = []
def run(t):
    for i in range(20):
        try:
            st.save_deliverable(deal, "model.json", ("%s-%d-%d" % (tag, t, i)).encode(), "json")
        except Exception as e:
            errs.append(repr(e))
ts = [threading.Thread(target=run, args=(t,)) for t in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
print(json.dumps(errs))
"""


class DealConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbp = os.path.join(self.tmp.name, "d.sqlite")
        self.blobp = os.path.join(self.tmp.name, "blobs")
        self.s = DealStore(self.dbp, LocalBlobStore(self.blobp))
        self.id = self.s.create_deal("Concurrent").deal_id

    def test_120_concurrent_set_definition_keep_all_keys(self):
        errs = []

        def run(t):
            for i in range(10):
                try:
                    self.s.set_definition(self.id, f"k-{t}-{i}", "v")
                except Exception as e:  # pragma: no cover
                    errs.append(e)
        ts = [threading.Thread(target=run, args=(t,)) for t in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        m = self.s.get(self.id)
        self.assertEqual(len(m.definitions), 120)
        self.assertEqual(len(m.versions), 121)  # created + one snapshot per write

    def test_concurrent_set_formatting_keep_all_keys(self):
        def run(t):
            self.s.set_formatting(self.id, **{f"p{t}": t})
        ts = [threading.Thread(target=run, args=(t,)) for t in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.s.get(self.id).formatting), 20)

    def test_160_saves_across_8_threads_and_2_processes(self):
        root = str(Path(__file__).resolve().parent.parent)
        procs = [subprocess.Popen([sys.executable, "-c", _WORKER, root, self.dbp, self.blobp, self.id, f"p{k}"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for k in range(2)]
        outs = [p.communicate(timeout=300) for p in procs]
        for p, (o, e) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, e)
            self.assertEqual(json.loads(o.strip().splitlines()[-1]), [])
        h = self.s.history(self.id, "model.json")
        self.assertEqual([x["version"] for x in h], list(range(1, 161)))


class DealEvidenceAnchorTests(unittest.TestCase):
    KEY = b"deal-evidence-key"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ev = Path(self.tmp.name) / "evidence"
        self.s = DealStore(os.path.join(self.tmp.name, "d.sqlite"), LocalBlobStore(os.path.join(self.tmp.name, "b")))
        self.id = self.s.create_deal("Anchored").deal_id
        self.b = EvidenceBundle(self.ev / "job9.jsonl")
        self.addCleanup(self.b.close)
        for i in range(5):
            self.b.append("t", {"i": i}, source="s", output=i)
        self.anchor = self.b.seal(key=self.KEY)

    def test_anchor_stored_and_verified(self):
        r = self.s.save_deliverable(self.id, "m.json", b"{}", "json", evidence_anchor=self.anchor.as_dict())
        self.assertEqual(r["evidence_anchor"]["head_hash"], self.anchor.head_hash)
        self.assertEqual(self.s.history(self.id, "m.json")[0]["evidence_anchor"], self.anchor.as_dict())
        self.assertTrue(self.s.verify_deliverable_evidence(self.id, "m.json", 1, self.ev, key=self.KEY))

    def test_truncated_evidence_fails_and_missing_anchor_fails(self):
        self.s.save_deliverable(self.id, "m.json", b"{}", "json", evidence_anchor=self.anchor.as_dict())
        self.s.save_deliverable(self.id, "plain.json", b"{}", "json")
        p = self.ev / "job9.jsonl"
        p.write_text("".join(p.read_text().splitlines(keepends=True)[:2]))
        self.assertIn("truncated", self.s.verify_deliverable_evidence(self.id, "m.json", 1, self.ev, key=self.KEY).reason)
        self.assertIn("missing anchor", self.s.verify_deliverable_evidence(self.id, "plain.json", 1, self.ev).reason)

    def test_restore_keeps_anchor_and_bad_anchor_rejected(self):
        self.s.save_deliverable(self.id, "m.json", b"{}", "json", evidence_anchor=self.anchor)
        self.s.save_deliverable(self.id, "m.json", b"{1}", "json")
        v3 = self.s.restore(self.id, "m.json", 1)
        self.assertEqual(v3["evidence_anchor"], self.anchor.as_dict())
        with self.assertRaises(DealError):
            self.s.save_deliverable(self.id, "m.json", b"x", "json", evidence_anchor={"job_id": "x"})
