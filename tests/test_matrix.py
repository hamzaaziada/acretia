"""Offline tests for the Matrix (router + Claude adapter over a fake SDK). Run: python3 -m unittest discover -s tests -v"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.docs import DocRef, passages  # noqa: E402
from om.llm import AnthropicProvider, Router  # noqa: E402
from om.matrix import Column, MatrixStore, build_prompt, key_terms  # noqa: E402
from om.search import Index  # noqa: E402

DOC = """<html><body><p>Item 1A. Risk Factors</p>
<p>We depend on a single supplier in Taiwan for advanced chips, and any disruption would hurt revenue.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Total net revenue was $391,035 million in fiscal 2026, an increase of 7% year over year.</p>
</body></html>"""


class FakeClient(Router):
    """A Router whose "matrix" stage is the real Claude adapter over a fake SDK (records requests)."""

    def __init__(self, script):
        self.script, self.requests = script, []
        sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=self.create)))
        super().__init__({"matrix": AnthropicProvider("claude-opus-5-5", client=sdk)})

    def create(self, **kw):
        self.requests.append(kw)
        out = self.script(kw)
        if out == "REFUSE":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=None)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=800, cache_creation_input_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(out))])


def pid_for(req, needle):
    """Passage id of the passage containing `needle`, as Claude would cite it."""
    import re
    text = req["messages"][0]["content"][0]["text"]
    for m in re.finditer(r"\[P(\d+)\] \([^)]*\)\n([^\[]+)", text):
        if needle in m.group(2):
            return int(m.group(1))
    return -1


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.idx = Index(Path(self.tmp.name) / "s.db")
        ps, n = passages(DOC, target=120, minimum=20)
        ref = DocRef(1, "AAA", "AAA Inc.", "10-K", "2026-11-01", None, "0000000001-26-000001", "d.htm",
                     "https://sec.example/aaa", "10-K", None)
        self.idx.add(ref, ps, n)
        self.store = MatrixStore(self.idx)
        self.cols = [Column("Revenue", "What was total net revenue in the fiscal year?", "currency"),
                     Column("Key supplier risk", "What supplier concentration risk is disclosed?")]
        self.mid = self.store.create("t", [1], self.cols)

    def tearDown(self):
        self.tmp.cleanup()

    def good(self, req):
        return {"answers": [
            {"column": "Revenue", "answer": "$391,035 million in fiscal 2026 (+7%).", "value": 391035, "unit": "$ millions",
             "not_found": False, "confidence": "high",
             "citations": [{"passage_id": pid_for(req, "Total net revenue"), "quote": "Total net revenue was $391,035 million in fiscal 2026"}]},
            {"column": "Key supplier risk", "answer": "Single chip supplier in Taiwan.", "value": None, "unit": None,
             "not_found": False, "confidence": "high",
             "citations": [{"passage_id": pid_for(req, "single supplier"), "quote": "a single supplier in Spain"}]},  # wrong quote
        ]}

    def test_request_shape_caching_schema_fallbacks(self):
        fc = FakeClient(self.good)
        self.store.run(self.mid, fc)
        r = fc.requests[0]
        self.assertEqual(r["model"], "claude-opus-5-5")
        self.assertEqual(r["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", r["betas"])
        self.assertEqual(r["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(r["messages"][0]["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("Total net revenue", r["messages"][0]["content"][0]["text"])
        enum = r["output_config"]["format"]["schema"]["properties"]["answers"]["items"]["properties"]["column"]["enum"]
        self.assertEqual(enum, ["Revenue", "Key supplier risk"])

    def test_grounding_marks_fabricated_quote_unverified(self):
        stats = self.store.run(self.mid, FakeClient(self.good))
        cells = self.store.cells(self.mid)[1]
        self.assertEqual(cells["Revenue"]["status"], "ok")
        self.assertTrue(cells["Revenue"]["citations"][0]["verified"])
        self.assertEqual(cells["Revenue"]["citations"][0]["section"], "Item 7. Management's Discussion and Analysis")
        self.assertEqual(cells["Key supplier risk"]["status"], "unverified")
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["unverified"], 1)

    def test_refusal_and_incremental_runs(self):
        self.store.run(self.mid, FakeClient(lambda r: "REFUSE"))
        self.assertEqual({c["status"] for c in self.store.cells(self.mid)[1].values()}, {"refused"})
        fc = FakeClient(self.good)
        self.store.run(self.mid, fc)                        # refused cells are retried
        self.assertEqual(len(fc.requests), 1)
        fc2 = FakeClient(self.good)
        self.store.run(self.mid, fc2)                       # nothing missing -> no calls
        self.assertEqual(len(fc2.requests), 0)
        self.store.add_column(self.mid, Column("Growth", "Revenue growth rate?", "percent"))

        def growth(req):
            return {"answers": [{"column": "Growth", "answer": "7%", "value": 7, "unit": "%", "not_found": False,
                                 "confidence": "high", "citations": [{"passage_id": pid_for(req, "increase of 7%"),
                                                                      "quote": "an increase of 7% year over year"}]}]}
        fc3 = FakeClient(growth)
        self.store.run(self.mid, fc3)                       # only the new column is asked
        self.assertEqual(len(fc3.requests), 1)
        self.assertIn('"Growth"', fc3.requests[0]["messages"][0]["content"][1]["text"])
        self.assertNotIn('"Revenue"', fc3.requests[0]["messages"][0]["content"][1]["text"])
        self.assertEqual(self.store.cells(self.mid)[1]["Growth"]["value"], 7)

    def test_sdk_error_marks_row_and_continues(self):
        def boom(req):
            raise RuntimeError("rate limited")
        stats = self.store.run(self.mid, FakeClient(boom))
        self.assertEqual(stats["error"], 2)

    def test_export_csv(self):
        self.store.run(self.mid, FakeClient(self.good))
        out = Path(self.tmp.name) / "m.csv"
        self.store.export_csv(self.mid, out)
        with open(out) as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][:5], ["company", "ticker", "form", "filed", "url"])
        self.assertIn("UNVERIFIED", rows[1][-1])

    def test_key_terms(self):
        self.assertEqual(key_terms("What supplier concentration risk is disclosed?"), ["supplier", "concentration", "risk"])

    def test_extractive_engine_without_api_key(self):
        stats = self.store.run(self.mid, None)   # client=None -> extractive
        self.assertEqual(stats["engine"], "extractive")
        cells = self.store.cells(self.mid)[1]
        rev = cells["Revenue"]
        self.assertEqual(rev["status"], "extracted")
        self.assertIn("391,035", rev["answer"])
        self.assertEqual(rev["value"], 391035.0)
        self.assertTrue(rev["citations"][0]["verified"])
        self.assertIn("single supplier", cells["Key supplier risk"]["answer"])
        # a Claude run later upgrades extracted cells
        fc = FakeClient(self.good)
        self.store.run(self.mid, fc)
        self.assertEqual(len(fc.requests), 1)
        self.assertEqual(self.store.cells(self.mid)[1]["Revenue"]["status"], "ok")
        system, parts, schema = build_prompt({"company": "X", "ticker": "X", "form": "10-K", "filed": "2026", "url": "u"},
                                             [{"chunk_id": 5, "section": None, "text": "hello"}], self.cols)
        self.assertIn("[P5]", parts[0].text)
        self.assertTrue(parts[0].cache)


if __name__ == "__main__":
    unittest.main()
