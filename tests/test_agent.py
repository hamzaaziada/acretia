"""Sheets agent: prompt building, plan validation, model-agnostic run (fake DeepSeek-style provider)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import agent as ag  # noqa: E402
from om import llm  # noqa: E402

FIELDS = ["revenue_ltm", "ebitda_ltm", "ev_revenue_ltm", "price_earnings_ltm", "name"]


class ValidationTests(unittest.TestCase):
    def test_check_formula(self):
        self.assertIsNone(ag.check_formula('=IFERROR(MEDIAN(L5:L7),"NM")'))
        self.assertIsNone(ag.check_formula('=OM($B5,"revenue_ltm")/1000', set(FIELDS)))
        self.assertEqual(ag.check_formula("=SUM(A1:A3"), "unbalanced parentheses")
        self.assertEqual(ag.check_formula('="abc'), "unbalanced quotes")
        self.assertEqual(ag.check_formula("=XLOOKUP(A1,B:B,C:C)"), "unknown function XLOOKUP")
        self.assertEqual(ag.check_formula("=AA999+1"), "reference AA999 outside the grid")
        self.assertEqual(ag.check_formula('=OM("AAPL","revenue_ttm")', set(FIELDS)), "unknown OM field revenue_ttm")
        self.assertIsNone(ag.check_formula('="SUM(" & A1'))     # function-looking text inside strings is ignored

    def test_validate_plan(self):
        plan = {"operations": [
            {"op": "set", "cell": "M4", "value": "EV / Sales", "format": "", "bold": True},
            {"op": "set", "cell": "$M$5", "value": '=OM($B5,"ev_revenue_ltm")', "format": "x", "bold": False},
            {"op": "set", "cell": "ZZ1", "value": "1", "format": "", "bold": False},
            {"op": "set", "cell": "M6", "value": "=FOO(1)", "format": "", "bold": False},
            {"op": "clear", "cell": "A30:C31", "value": "", "format": "", "bold": False},
            {"op": "set", "cell": "M7", "value": "3", "format": "weird", "bold": False}]}
        ok, problems = ag.validate_plan(plan, set(FIELDS))
        self.assertEqual([o["cell"] for o in ok], ["M4", "M5", "A30:C31", "M7"])
        self.assertEqual(ok[3]["format"], "")
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("FOO" in p for p in problems))

    def test_prompt_has_stable_cacheable_prefix_and_errors(self):
        cells = {"A1": "Comps", "B5": "AAPL", "C5": '=OM($B5,"revenue_ltm")'}
        system, parts, schema = ag.build_prompt("add P/E", cells, {"C5": 478834.0}, "C5",
                                                [{"name": "falcon", "documents": ["CIM.docx"], "columns": ["Revenue"]}],
                                                FIELDS, errors=["C9 = =FOO() → #NAME?"])
        self.assertTrue(parts[0].cache)
        self.assertIn("revenue_ltm", parts[0].text)
        self.assertIn('"falcon"', parts[0].text)
        self.assertNotIn("C5:", parts[0].text)                     # sheet state is not in the cached prefix
        self.assertIn('C5: =OM($B5,"revenue_ltm") → 478834', parts[1].text)
        self.assertIn("first empty row 7", parts[1].text)
        self.assertIn("#NAME?", parts[2].text)
        self.assertIn("Never", system)
        self.assertEqual(schema["required"], ["message", "operations"])

    def test_snapshot_orders_by_row_then_column(self):
        s = ag.snapshot({"B2": "x", "A10": "y", "C1": "z", "A2": "w"}, {})
        self.assertEqual([l.split(":")[0] for l in s.splitlines()], ["C1", "A2", "B2", "A10"])


class RunTests(unittest.TestCase):
    def test_run_through_openai_compatible_provider(self):
        reply = {"message": "Added EV/Sales in M4:M6 with a median in M8.",
                 "operations": [{"op": "set", "cell": "M4", "value": "EV / Sales", "format": "", "bold": True},
                                {"op": "set", "cell": "M5", "value": '=OM($B5,"ev_revenue_ltm")', "format": "x", "bold": False},
                                {"op": "set", "cell": "M8", "value": '=IFERROR(MEDIAN(M5:M6),"NM")', "format": "x", "bold": True}]}
        seen = []

        def transport(url, body, headers):
            seen.append(body)
            return {"choices": [{"message": {"content": json.dumps(reply)}, "finish_reason": "stop"}], "usage": {}}
        router = llm.Router({"sheets_agent": llm.OpenAICompatProvider("deepseek", "deepseek-chat", "https://api.deepseek.com",
                                                                      "k", "json_object", transport)})
        out = ag.run(router, "add EV/Sales", {"B5": "AAPL"}, {}, "M4", [], FIELDS)
        self.assertEqual(len(out["operations"]), 3)
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["model"], "deepseek:deepseek-chat")
        self.assertIn('"operations"', seen[0]["messages"][0]["content"])      # schema restated for JSON-mode models


if __name__ == "__main__":
    unittest.main()
