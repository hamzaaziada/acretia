"""Ask: plan → parallel tools → cited answer → verification; and the no-model path."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from om import ask  # noqa: E402
from om import llm  # noqa: E402
from om.docs import DocRef, passages  # noqa: E402
from om.search import Index  # noqa: E402

DOC = """<html><body><p>Item 1A. Risk Factors</p>
<p>New tariffs on imports from China may increase the Company's costs and reduce gross margins.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Total net sales were $478,834 million in 2026, up 15% from 2025.</p></body></html>"""


class FakeData:
    def comps_row(self, ticker):
        return ({"name": "Apple Inc.", "cik": 320193, "revenue_ltm": 478834.0, "margin_ebitda_ltm": 35.8, "ltm_end": "2026-09-26"},
                {"revenue_ltm_lcu": {"facts": [{"accn": "0000320193-26-000026"}]}})


class ScriptedProvider:
    """Plays the model: a plan, then (optionally) no more calls, then an answer citing what it was given."""

    def __init__(self, answer_fn):
        self.answer_fn, self.calls, self.model = answer_fn, [], "scripted"

    def complete_json(self, system, parts, schema, **kw):
        self.calls.append((system, [p.text for p in parts]))
        if "tool_calls" in schema["properties"]:
            first = sum(1 for s, _ in self.calls if "Plan the lookups" in s) == 1
            calls = [{"tool": "search_documents", "args": {"query": "tariff*"}},
                     {"tool": "company_financials", "args": {"ticker": "AAPL"}}] if first else []
            return llm.Result({"tool_calls": calls, "reason": "need risk factors and financials"}, {}, "scripted")
        return llm.Result(self.answer_fn("\n".join(p.text for p in parts) if False else parts[0].text), {"input_tokens": 100}, "scripted")


class AskTests(unittest.TestCase):
    def setUp(self):
        self.idx = Index(Path(tempfile.mkdtemp()) / "s.db")
        ps, n = passages(DOC, target=120, minimum=20)
        self.idx.add(DocRef(320193, "AAPL", "Apple Inc.", "10-K", "2026-11-03", None, "a", "d.htm", "https://sec/aapl", "10-K", None), ps, n)
        self.tools = ask.Tools(self.idx, FakeData(), None, None)

    def test_full_loop_with_verification(self):
        def answer(sources_text):
            d_id = "D1" if "[D1]" in sources_text else "D2"
            return {"answer_markdown": "Tariffs raise costs and pressure margins [1]. LTM revenue was $478.8bn [2]. Margins are 99% [3].",
                    "citations": [{"n": 1, "source_id": d_id, "quote": "New tariffs on imports from China may increase the Company's costs"},
                                  {"n": 2, "source_id": "F1", "quote": "revenue_ltm: 478834"},
                                  {"n": 3, "source_id": "F1", "quote": "margin: 99"}],
                    "follow_ups": ["How large are China sales?"]}
        prov = ScriptedProvider(answer)
        router = llm.Router({"ask": prov})
        steps = []
        out = ask.run(router, self.tools, "How do tariffs affect Apple?", progress=steps.append)
        self.assertEqual(len(out["tool_calls"]), 2)
        kinds = {s["kind"] for s in out["sources"]}
        self.assertEqual(kinds, {"document", "financials"})
        ver = {c["n"]: c["verified"] for c in out["citations"]}
        self.assertEqual(ver, {1: True, 2: True, 3: False})          # fabricated figure is flagged
        self.assertEqual((out["verified"], out["unverified"]), (2, 1))
        self.assertTrue(any("parallel" in s for s in steps))
        self.assertTrue(any("Writing the answer" in s for s in steps))
        self.assertIn("[F1]", prov.calls[-1][1][0])                   # sources passed to the answer step

    def test_room_scope_is_enforced(self):
        seen = []
        orig = self.tools.search_documents
        self.tools.search_documents = lambda **kw: (seen.append(kw), orig(**kw))[1]
        prov = ScriptedProvider(lambda t: {"answer_markdown": "x", "citations": [], "follow_ups": []})
        ask.run(llm.Router({"ask": prov}), self.tools, "q", scope={"room": 7})
        self.assertEqual(seen[0]["room"], 7)

    def test_without_model(self):
        out = ask.run_without_model(self.tools, "What does AAPL say about tariffs?", known_tickers={"AAPL"})
        self.assertTrue(out["no_model"])
        kinds = [s["kind"] for s in out["sources"]]
        self.assertIn("document", kinds)
        self.assertIn("financials", kinds)

    def test_sources_dedupe_and_ids(self):
        s = ask.Sources()
        d = {"kind": "document", "chunk_id": 5, "company": "A", "form": "10-K", "filed": "x", "section": "", "text": "t"}
        s.add([d, d, {"kind": "round", "company": "B", "first_sale_date": "2026-01-01"}])
        self.assertEqual(list(s.items), ["D1", "R1"])


if __name__ == "__main__":
    unittest.main()
