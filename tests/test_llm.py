"""Model-agnostic LLM layer: OpenAI-compatible adapter (DeepSeek etc.), routing, schema repair."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import llm  # noqa: E402
from om.docs import DocRef, passages  # noqa: E402
from om.matrix import Column, MatrixStore  # noqa: E402
from om.search import Index  # noqa: E402

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}, "n": {"type": "integer"}},
          "required": ["answer", "n"], "additionalProperties": False}


def deepseek_reply(content, cache_hit=0):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 40, "prompt_cache_hit_tokens": cache_hit}}


class OpenAICompatTests(unittest.TestCase):
    def test_deepseek_json_mode_schema_in_prompt_and_usage(self):
        seen = []

        def transport(url, body, headers):
            seen.append((url, body, headers))
            return deepseek_reply('{"answer": "ok", "n": 3}', cache_hit=800)
        p = llm.OpenAICompatProvider("deepseek", "deepseek-chat", "https://api.deepseek.com", "sk-test", "json_object", transport)
        res = llm.Router({"matrix": p}).complete_json("matrix", "You are precise.", [llm.Part("DOC", cache=True), llm.Part("Q")], SCHEMA)
        url, body, headers = seen[0]
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn('"required": ["answer", "n"]', body["messages"][0]["content"])     # schema restated for JSON mode
        self.assertTrue(body["messages"][1]["content"].startswith("DOC"))                 # stable prefix first (prefix caching)
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(headers["Authorization"], "Bearer sk-test")
        self.assertEqual(res.data, {"answer": "ok", "n": 3})
        self.assertEqual(res.usage["cache_read_input_tokens"], 800)
        self.assertEqual(res.model, "deepseek:deepseek-chat")

    def test_repair_retry_on_schema_violation(self):
        replies = iter(['```json\n{"answer": "ok"}\n```', '{"answer": "ok", "n": 1}'])
        calls = []

        def transport(url, body, headers):
            calls.append(body)
            return deepseek_reply(next(replies))
        p = llm.OpenAICompatProvider("deepseek", "deepseek-chat", "https://x", "k", "json_object", transport)
        res = llm.Router({"s": p}).complete_json("s", "sys", [llm.Part("doc")], SCHEMA)
        self.assertTrue(res.repaired)
        self.assertEqual(res.data["n"], 1)
        self.assertIn("missing required key 'n'", calls[1]["messages"][1]["content"])

    def test_openai_uses_json_schema_format(self):
        bodies = []
        p = llm.OpenAICompatProvider("openai", "gpt-4.1-mini", "https://api.openai.com/v1", "k", "json_schema",
                                     lambda u, b, h: bodies.append(b) or deepseek_reply('{"answer":"a","n":2}'))
        p.complete_json("s", [llm.Part("d")], SCHEMA)
        self.assertEqual(bodies[0]["response_format"]["type"], "json_schema")
        self.assertEqual(bodies[0]["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_content_filter_is_a_refusal(self):
        p = llm.OpenAICompatProvider("x", "m", "https://x", None, "json_object",
                                     lambda u, b, h: {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]})
        with self.assertRaises(llm.LLMRefusal):
            p.complete_json("s", [llm.Part("d")], SCHEMA)


class RoutingTests(unittest.TestCase):
    def test_per_stage_routing_and_default(self):
        env = {"OM_MODEL_DEFAULT": "deepseek:deepseek-chat", "OM_MODEL_SHEETS_AGENT": "anthropic:claude-opus-5-5",
               "DEEPSEEK_API_KEY": "k"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(llm.configured_spec("matrix"), "deepseek:deepseek-chat")
            self.assertEqual(llm.configured_spec("sheets_agent"), "anthropic:claude-opus-5-5")
            self.assertEqual(llm.Router().describe("matrix"), "deepseek:deepseek-chat")

    def test_auto_detects_first_key_and_none_without_keys(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k"}, clear=True):
            self.assertEqual(llm.configured_spec("matrix"), "deepseek")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(llm.configured_spec("matrix"))
            self.assertFalse(llm.Router().available("matrix"))

    def test_missing_key_and_custom_provider(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(llm.LLMError):
                llm.make_provider("deepseek")
        env = {"OM_PROVIDER_MYVLLM_BASE_URL": "http://gpu-box:8000/v1"}
        with mock.patch.dict(os.environ, env, clear=True):
            p = llm.make_provider("myvllm:Qwen/Qwen2.5-72B-Instruct")
            self.assertEqual((p.base_url, p.model, p.key), ("http://gpu-box:8000/v1", "Qwen/Qwen2.5-72B-Instruct", None))
        self.assertEqual(llm.make_provider("ollama").base_url, "http://localhost:11434/v1")

    def test_validator(self):
        self.assertIsNone(llm.validate({"answer": "a", "n": 1}, SCHEMA))
        self.assertIn("expected integer", llm.validate({"answer": "a", "n": "1"}, SCHEMA))
        self.assertIn("expected integer", llm.validate({"answer": "a", "n": True}, SCHEMA))


class MatrixOnDeepSeekTests(unittest.TestCase):
    def test_matrix_runs_on_openai_compatible_provider_with_grounding(self):
        tmp = tempfile.TemporaryDirectory()
        idx = Index(Path(tmp.name) / "s.db")
        ps, n = passages("<p>Item 7. MD&A</p><p>Revenue was $50.0 million in 2026, up 12%.</p>", 120, 20)
        idx.add(DocRef(1, "AAA", "AAA Inc.", "10-K", "2026-11-01", None, "a", "d.htm", "u", "10-K", None), ps, n)
        store = MatrixStore(idx)
        mid = store.create("t", [1], [Column("Revenue", "What was revenue?", "currency")])

        def transport(url, body, headers):
            pid = int(re.search(r"\[P(\d+)\]", body["messages"][1]["content"]).group(1))
            return deepseek_reply(json.dumps({"answers": [{"column": "Revenue", "answer": "$50.0 million", "value": 50.0,
                                                           "unit": "$ millions", "not_found": False, "confidence": "high",
                                                           "citations": [{"passage_id": pid, "quote": "Revenue was $50.0 million in 2026"}]}]}))
        router = llm.Router({"matrix": llm.OpenAICompatProvider("deepseek", "deepseek-chat", "https://api.deepseek.com", "k",
                                                                 "json_object", transport)})
        stats = store.run(mid, router)
        self.assertEqual(stats["engine"], "deepseek:deepseek-chat")
        cell = store.cells(mid)[1]["Revenue"]
        self.assertEqual(cell["status"], "ok")
        self.assertEqual(cell["model"], "deepseek:deepseek-chat")
        self.assertTrue(cell["citations"][0]["verified"])
        tmp.cleanup()


class ValidateTypeListTests(unittest.TestCase):
    def test_type_lists(self):
        from om.llm import validate
        sch = {"type": "object", "properties": {"v": {"type": ["number", "null"]}, "p": {"type": ["string", "integer"]}}}
        self.assertIsNone(validate({"v": None, "p": 3}, sch))
        self.assertIsNone(validate({"v": 2.5, "p": "x"}, sch))
        self.assertIsNotNone(validate({"v": "a"}, sch))
        from om import layout
        self.assertIsNone(validate({"elements": [{"type": "chart", "series": [{"name": "s", "values": [1, None]}], "page": 2}]}, layout.SCHEMA))


if __name__ == "__main__":
    unittest.main()
