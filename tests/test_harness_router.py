"""S2.3 router, profiles and tool registry. Hermetic: fake classifier, no network."""
import csv
import os
import tempfile
import unittest
from unittest import mock

from src.harness import router as R


class FakeClassifier:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    def chat(self, messages, json_schema=None, job_id=None):
        self.calls.append((messages, json_schema, job_id))
        if self.exc:
            raise self.exc
        return self.reply


CASES = [
    ("Roll forward this model to FY2026", ["m.xlsx"], "modeling", "excel"),
    ("roll-forward the three-statement model", [], "modeling", "excel"),
    ("Build a DCF with sensitivity tables", [], "modeling", "excel"),
    ("Answer the diligence questions from the data room", ["vdr.zip"], "extraction", "grid"),
    ("Answer these diligence questions", ["cim.pdf", "leases.pdf", "msa.pdf"], "extraction", "grid"),
    ("Extract the change of control clauses from each contract", ["a.pdf", "b.pdf"], "extraction", "grid"),
    ("Make a pitchbook for the sell-side process", [], "reasoning", "deck"),
    ("Turn this into slides for the board", [], "reasoning", "deck"),
    ("Critique this slide layout, anything overlapping?", ["slide3.png"], "vision_critic", "general"),
    ("review the rendered page", ["shot.jpg"], "vision_critic", "general"),
    ("Role-play a skeptical buyer and give buyer feedback", [], "persona", "general"),
    ("Pretend you are the CFO and push back on the plan", [], "persona", "general"),
    ("Research the market size and competitor landscape for HVAC services", [], "reasoning", "research"),
    ("Pull trading comps and precedent transactions", [], "reasoning", "research"),
    ("Explain why margins fell and recommend actions", [], "reasoning", "general"),
    ("Update the cap table for the Series B", ["cap.xlsx"], "modeling", "excel"),
]


class RoutingTests(unittest.TestCase):
    def test_table(self):
        for req, files, tt, eng in CASES:
            with self.subTest(req=req):
                clf = FakeClassifier(exc=AssertionError("must not be called"))
                r = R.route(req, files=files, classifier=clf)
                self.assertEqual((r.task_type, r.engines[0]), (tt, eng), r.reason)
                self.assertGreaterEqual(r.confidence, R.THRESHOLD)
                self.assertFalse(r.used_model_call)
                self.assertEqual(set(r.models), set(R.ROLES))

    def test_ambiguous_calls_classifier_once(self):
        clf = FakeClassifier(reply={"task_type": "modeling", "engines": ["excel"], "confidence": 0.9})
        r = R.route("please help with this", classifier=clf)
        self.assertEqual(len(clf.calls), 1)
        self.assertIsNotNone(clf.calls[0][1])           # json schema passed
        self.assertTrue(r.used_model_call)
        self.assertEqual((r.task_type, r.engines), ("modeling", ["excel"]))

    def test_classifier_failure_falls_back(self):
        for clf in (FakeClassifier(exc=RuntimeError("down")), FakeClassifier(reply="not json"),
                    FakeClassifier(reply={"task_type": "bogus", "engines": []})):
            r = R.route("hmm", classifier=clf)
            self.assertEqual((r.task_type, r.engines), ("reasoning", ["general"]))
            self.assertTrue(r.used_model_call)
            self.assertEqual(len(clf.calls), 1)

    def test_no_classifier_ambiguous_is_low_confidence_default(self):
        r = R.route("hmm")
        self.assertEqual((r.task_type, r.engines, r.used_model_call), ("reasoning", ["general"], False))
        self.assertLess(r.confidence, R.THRESHOLD)

    def test_task_type_override(self):
        r = R.route("anything", task_type="extraction")
        self.assertEqual((r.task_type, r.engines, r.confidence), ("extraction", ["grid"], 1.0))
        with self.assertRaises(ValueError):
            R.route("x", task_type="nope")

    def test_vision_requires_vision_profile(self):
        r = R.route("critique this layout", files=["a.png"], profile="deepseek")
        self.assertEqual(r.task_type, "vision_critic")
        self.assertTrue(R.load_profiles()[r.profile]["supports_vision"])
        self.assertIn("lacks vision", r.reason)
        r2 = R.route("critique this layout", files=["a.png"], profile="gemini")
        self.assertEqual(r2.profile, "gemini")

    def test_deck_chain_after_model(self):
        r = R.route("Roll forward the DCF model and build a pitchbook deck from it", files=["m.xlsx"])
        self.assertEqual(r.engines, ["excel", "deck"])

    def test_log_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "routing.csv")
            R.route("Build a DCF", log_path=p)
            R.route("Make slides", log_path=p)
            with open(p, newline="") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1][4], "modeling")


class ProfileTests(unittest.TestCase):
    def test_all_profiles_complete(self):
        ps = R.load_profiles()
        self.assertEqual(set(ps), {"claude", "openai", "gemini", "deepseek", "glm", "kimi", "local"})
        for n, p in ps.items():
            for k in ("family", "match", "context_window", "supports_vision", "supports_json_schema", "recommended",
                      "prompt_quirks", "max_output_tokens", "price_per_mtok"):
                self.assertIn(k, p, f"{n}.{k}")
            self.assertEqual(set(p["price_per_mtok"]), {"input", "output"})
            self.assertEqual(set(R.models_for(p, "modeling")), set(R.ROLES))
            self.assertTrue(all(R.models_for(p, "modeling").values()))

    def test_matching(self):
        want = {"claude-sonnet-5-5": "claude", "claude-3-5-haiku-20241022": "claude", "gpt-4.1": "openai",
                "o3-mini": "openai", "gemini-2.5-pro": "gemini", "deepseek-chat": "deepseek", "glm-4.6": "glm",
                "kimi-k2": "kimi", "qwen2.5:7b": "local", "llama3.1:8b": "local", "ollama/mistral": "local",
                "deepseek-r1:7b": "local"}
        with mock.patch.dict(os.environ):
            os.environ.pop("ACRETIA_PROFILE", None)
            for mid, fam in want.items():
                with self.subTest(mid=mid):
                    self.assertEqual(R.profile_for_model(mid)["family"], fam)
            self.assertIsNone(R.profile_for_model("totally-unknown-xyz"))

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"ACRETIA_PROFILE": "glm"}):
            self.assertEqual(R.profile_for_model("claude-sonnet-5-5")["family"], "glm")
            self.assertEqual(R.route("Build a DCF").profile, "glm")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = R.ToolRegistry()
        self.reg.register("add", lambda a, b: a + b, {"type": "object", "required": ["a", "b"], "properties": {
            "a": {"type": "integer"}, "b": {"type": "integer"}}, "additionalProperties": False},
            ["modeling"], "Add two ints")
        self.reg.register("echo", lambda text: text, {"type": "object", "required": ["text"],
                                                       "properties": {"text": {"type": "string"}}})

    def test_call_ok(self):
        self.assertEqual(self.reg.call("add", {"a": 1, "b": 2}), 3)

    def test_rejects_bad_args_and_unknown(self):
        for args in ({"a": 1}, {"a": "x", "b": 2}, {"a": 1, "b": 2, "c": 3}):
            with self.assertRaises(R.ToolError):
                self.reg.call("add", args)
        with self.assertRaises(R.ToolError):
            self.reg.call("nope", {})

    def test_list_descriptors_and_filter(self):
        names = {t["name"] for t in self.reg.list()}
        self.assertEqual(names, {"add", "echo"})
        self.assertEqual([t["name"] for t in self.reg.list("modeling")], ["add", "echo"])
        self.assertEqual([t["name"] for t in self.reg.list("persona")], ["echo"])
        d = self.reg.list("modeling")[0]
        self.assertEqual(set(d), {"name", "description", "inputSchema"})

    def test_duplicate_and_bad_task_type(self):
        with self.assertRaises(R.ToolError):
            self.reg.register("add", len, {})
        with self.assertRaises(R.ToolError):
            self.reg.register("x", len, {}, ["bogus"])


if __name__ == "__main__":
    unittest.main()
