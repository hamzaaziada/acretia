"""S2.1 model adapter: fake transports only, never the network."""
import ast
import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om import llm, replay  # noqa: E402
from om.llm import InvalidJSON, LLMError, LLMRefusal, SchemaInvalid, TransportError  # noqa: E402
from src.harness import adapter as adp  # noqa: E402
from src.harness.adapter import Adapter, image_part, parse_sse  # noqa: E402
from src.harness.ledger import BudgetExceeded, Ledger, SpendGuard, cost_usd  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "adapter"
KEY = "sk-test-key-0123456789"
SCHEMA = {"type": "object", "required": ["answer", "n"], "properties": {"answer": {"type": "string"}, "n": {"type": "integer"}}}
EMAIL = "jane.doe@example.com"
REPLAY_MESSAGES = [{"role": "system", "content": "You are terse."},
                   {"role": "user", "content": f"Summarise the note from {EMAIL} about revenue."}]


def reply(content, prompt=10, completion=5, finish="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


class FakeTransport:
    """Pops queued replies (dict) or exceptions; records every call."""

    def __init__(self, *queue):
        self.queue, self.calls = list(queue), []

    def __call__(self, url, body, headers, stream=False):
        self.calls.append({"url": url, "body": body, "headers": headers, "stream": stream})
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def sse(*deltas, usage=None):
    out = [": keepalive\n", "\n"]
    for d in deltas:
        out += ["data: " + json.dumps({"choices": [{"delta": {"content": d}}]}) + "\n", "\n"]
    if usage:
        out += ["data: " + json.dumps({"choices": [], "usage": usage}) + "\n"]
    out.append("data: [DONE]\n")
    return out


def make(*queue, **kw):
    t = FakeTransport(*queue)
    kw.setdefault("mode", "live")
    kw.setdefault("sleep", lambda s: None)
    return Adapter("https://llm.meshpool.ai/v1", KEY, "m", transport=t, **kw), t


class ChatTests(unittest.TestCase):
    def test_plain_chat_returns_text_usage_cost(self):
        a, t = make(reply("hello", 100, 20))
        r = a.chat([{"role": "user", "content": "hi"}], max_tokens=50, job_id="j1")
        self.assertEqual((r.text, r.replayed, r.model, r.fallbacks), ("hello", False, "m", []))
        self.assertEqual(r.usage["input_tokens"], 100)
        self.assertGreater(r.cost_usd, 0)
        c = t.calls[0]
        self.assertEqual(c["url"], "https://llm.meshpool.ai/v1/chat/completions")
        self.assertEqual(c["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual((c["body"]["model"], c["body"]["max_tokens"], c["body"]["temperature"]), ("m", 50, 0))

    def test_json_schema_is_validated_and_sent(self):
        a, t = make(reply('{"answer": "a", "n": 3}'))
        r = a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
        self.assertEqual(r.data, {"answer": "a", "n": 3})
        body = t.calls[0]["body"]
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIn('"required"', body["messages"][0]["content"])         # schema restated for JSON-mode-only servers

    def test_json_repair_retry_then_success(self):
        a, t = make(reply("not json at all"), reply('{"answer": "b", "n": 1}'))
        r = a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
        self.assertEqual(r.data["answer"], "b")
        self.assertEqual(len(t.calls), 2)
        repair = t.calls[1]["body"]["messages"]
        self.assertEqual([m["role"] for m in repair[-2:]], ["assistant", "user"])
        self.assertIn("rejected", repair[-1]["content"])

    def test_schema_violation_repaired_once_then_raises(self):
        a, t = make(reply('{"answer": "x"}'), reply('{"answer": 5, "n": 1}'))
        with self.assertRaises(SchemaInvalid):
            a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
        self.assertEqual(len(t.calls), 2)                                     # exactly one repair, no more

    def test_unparseable_after_repair_raises_invalid_json(self):
        a, _ = make(reply("nope"), reply("still nope"))
        with self.assertRaises(InvalidJSON):
            a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)

    def test_content_filter_is_a_refusal_not_a_fallthrough(self):
        b, tb = make(reply("x"))
        a, _ = make(reply("", finish="content_filter"), fallbacks=[b])
        with self.assertRaises(LLMRefusal):
            a.chat([{"role": "user", "content": "q"}])
        self.assertEqual(tb.calls, [])

    def test_vision_payload_shape(self):
        a, t = make(reply("a chart"))
        png = b"\x89PNG\r\n\x1a\nfakebytes"
        a.chat([{"role": "user", "content": [{"type": "text", "text": "what is this?"}, image_part(png, "image/png")]}])
        parts = t.calls[0]["body"]["messages"][0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "what is this?"})
        self.assertEqual(parts[1]["type"], "image_url")
        url = parts[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        import base64
        self.assertEqual(base64.b64decode(url.split(",", 1)[1]), png)

    def test_from_env(self):
        env = {"ACRETIA_LLM_BASE_URL": "https://llm.meshpool.ai/v1", "ACRETIA_LLM_API_KEY": KEY, "ACRETIA_LLM_MODEL": "claude-x"}
        with mock.patch.dict(os.environ, env):
            a = Adapter.from_env()
        self.assertEqual((a.base_url, a.model, a.key_host), ("https://llm.meshpool.ai/v1", "claude-x", "llm.meshpool.ai"))
        with mock.patch.dict(os.environ, {}, clear=True):
            d = Adapter.from_env()
        self.assertEqual((d.base_url, d.api_key, d.model), (adp.DEFAULT_BASE_URL, None, "auto"))


class StreamTests(unittest.TestCase):
    def test_parse_sse_ignores_comments_and_stops_at_done(self):
        evs = list(parse_sse(sse("a", "b") + ["data: {\"x\": 1}\n"]))
        self.assertEqual(len(evs), 2)

    def test_stream_yields_deltas_and_sets_result(self):
        a, t = make(sse("Hel", "lo ", "world", usage={"prompt_tokens": 7, "completion_tokens": 3}),
                    ledger=Ledger())
        s = a.chat([{"role": "user", "content": "hi"}], stream=True, job_id="j")
        self.assertEqual(list(s), ["Hel", "lo ", "world"])
        self.assertEqual(s.result.text, "Hello world")
        self.assertEqual(s.result.usage["output_tokens"], 3)
        self.assertTrue(t.calls[0]["stream"])
        self.assertTrue(t.calls[0]["body"]["stream"])
        self.assertEqual(a.ledger.total("j")["output_tokens"], 3)

    def test_stream_unmasks_placeholder_split_across_chunks(self):
        a, _ = make(sse("Mail [EMA", "IL_1] now"))
        s = a.chat([{"role": "user", "content": f"write to {EMAIL}"}], stream=True)
        self.assertEqual(s.text(), f"Mail {EMAIL} now")

    def test_stream_falls_back_before_first_chunk(self):
        b, _ = make(sse("ok"))
        a, _ = make(TransportError("boom", 503), fallbacks=[b], max_retries=0)
        s = a.chat([{"role": "user", "content": "hi"}], stream=True)
        self.assertEqual(s.text(), "ok")
        self.assertEqual(s.result.fallbacks[0]["kind"], "TransportError")

    def test_stream_with_schema_is_rejected(self):
        a, _ = make()
        with self.assertRaises(ValueError):
            a.chat([{"role": "user", "content": "x"}], stream=True, json_schema=SCHEMA)


class RetryFallbackTests(unittest.TestCase):
    def test_retry_503_then_success_with_backoff(self):
        sleeps = []
        a, t = make(TransportError("unavailable", 503), TransportError("rate", 429), reply("ok"), sleep=sleeps.append)
        self.assertEqual(a.chat([{"role": "user", "content": "q"}]).text, "ok")
        self.assertEqual(len(t.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertGreater(sleeps[1], sleeps[0])                              # exponential

    def test_timeout_is_retried(self):
        a, t = make(TimeoutError("slow"), reply("ok"))
        self.assertEqual(a.chat([{"role": "user", "content": "q"}]).text, "ok")

    def test_client_error_is_not_retried(self):
        a, t = make(TransportError("bad request", 400), reply("never"))
        with self.assertRaises(TransportError):
            a.chat([{"role": "user", "content": "q"}])
        self.assertEqual(len(t.calls), 1)

    def test_retries_exhausted_raises(self):
        a, t = make(*[TransportError("down", 503)] * 3, max_retries=2)
        with self.assertRaises(TransportError):
            a.chat([{"role": "user", "content": "q"}])
        self.assertEqual(len(t.calls), 3)

    def test_fallback_to_second_adapter(self):
        b, tb = make(reply('{"answer": "from b", "n": 2}'))
        a, ta = make(TransportError("down", 503), TransportError("down", 503), fallbacks=[b], max_retries=1)
        r = a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
        self.assertEqual(r.data["answer"], "from b")
        self.assertEqual(len(ta.calls), 2)
        self.assertEqual([e["kind"] for e in r.fallbacks], ["TransportError"])

    def test_fallback_on_invalid_json_from_first(self):
        b, _ = make(reply('{"answer": "ok", "n": 1}'))
        a, _ = make(reply("bad"), reply("worse"), fallbacks=[b])
        r = a.chat([{"role": "user", "content": "q"}], json_schema=SCHEMA)
        self.assertEqual(r.data["n"], 1)
        self.assertEqual(r.fallbacks[0]["kind"], "InvalidJSON")

    def test_last_error_propagates_when_chain_exhausted(self):
        b, _ = make(TransportError("b down", 500), max_retries=0)
        a, _ = make(TransportError("a down", 500), fallbacks=[b], max_retries=0)
        with self.assertRaises(TransportError) as cm:
            a.chat([{"role": "user", "content": "q"}])
        self.assertIn("b down", str(cm.exception))


class KeyHostTests(unittest.TestCase):
    def test_lookalike_and_odd_endpoints_refused(self):
        bad = ["https://llm.meshpool.ai.evil.com/v1", "https://llm.meshpool.ai@evil.com/v1", "https://xllm.meshpool.ai/v1",
               "https://meshpool.ai/v1", "https://llm.meshpool.ai./v1", "http://llm.meshpool.ai/v1",
               "https://llm.meshpool.ai:8443/v1", "https://user:pw@llm.meshpool.ai/v1", "https://api.openai.com/v1"]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(LLMError):
                Adapter(url, KEY, "m", key_host="llm.meshpool.ai", transport=lambda *a, **k: self.fail("sent"))

    def test_good_host_accepted_and_case_insensitive(self):
        Adapter("https://LLM.meshpool.ai/v1", KEY, "m", key_host="llm.meshpool.ai", transport=lambda *a, **k: {})

    def test_key_host_defaults_to_base_url_host(self):
        a = Adapter("https://api.openai.com/v1", KEY, "m", transport=lambda *a, **k: {})
        self.assertEqual(a.key_host, "api.openai.com")
        with self.assertRaises(LLMError):
            Adapter("http://api.openai.com/v1", KEY, "m", transport=lambda *a, **k: {})

    def test_key_with_unknown_host_and_no_key_host_is_refused(self):
        for url in ("https://gateway.example.com/v1", "https://evil.example/v1", "https://llm.meshpool.ai.evil.com/v1"):
            with self.subTest(url=url), self.assertRaises(LLMError) as cm:
                Adapter(url, KEY, "m", transport=lambda *a, **k: self.fail("sent"))
            self.assertIn("key_host", str(cm.exception))
            self.assertNotIn(KEY, str(cm.exception))
        a = Adapter("https://gateway.example.com/v1", KEY, "m", key_host="gateway.example.com", transport=lambda *a, **k: {})
        self.assertEqual(a.key_host, "gateway.example.com")
        Adapter("https://gateway.example.com/v1", None, "m")                    # no key: no binding needed

    def test_from_env_key_host_from_preset_or_env(self):
        env = {"ACRETIA_LLM_BASE_URL": "https://api.anthropic.com/v1", "ACRETIA_LLM_API_KEY": KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(Adapter.from_env().key_host, "api.anthropic.com")
        env = {"ACRETIA_LLM_BASE_URL": "https://gateway.example.com/v1", "ACRETIA_LLM_API_KEY": KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(LLMError):
                Adapter.from_env()
        with mock.patch.dict(os.environ, {**env, "ACRETIA_LLM_KEY_HOST": "gateway.example.com"}, clear=True):
            self.assertEqual(Adapter.from_env().key_host, "gateway.example.com")
        for h in ("llm.meshpool.ai", "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com"):
            self.assertIn(h, adp.KNOWN_KEY_HOSTS)

    def test_base_url_mutated_after_construction_is_refused_before_sending(self):
        a, t = make(reply("x"))
        a.base_url = "https://evil.com/v1"
        with self.assertRaises(LLMError):
            a.chat([{"role": "user", "content": "q"}])
        self.assertEqual(t.calls, [])

    def test_redirect_off_host_refused_and_guard_installed(self):
        used = []

        def spy(*handlers):
            used.extend(handlers)
            raise urllib.error.URLError("stop")
        import urllib.error
        with mock.patch.object(urllib.request, "build_opener", spy), self.assertRaises(urllib.error.URLError):
            adp.urllib_transport("https://llm.meshpool.ai/v1/chat/completions", {}, {}, bound_host="llm.meshpool.ai", has_key=True)
        h = next(h for h in used if isinstance(h, llm._SameHostRedirect))
        self.assertEqual((h.host, h.has_key), ("llm.meshpool.ai", True))
        req = urllib.request.Request("https://llm.meshpool.ai/v1/chat/completions", data=b"{}")
        for dest in ("https://evil.com/x", "https://llm.meshpool.ai.evil.com/v1", "http://llm.meshpool.ai/v1"):
            with self.subTest(dest=dest), self.assertRaises(LLMError):
                h.redirect_request(req, None, 307, "Temporary Redirect", {}, dest)

    def test_key_not_in_body_or_error_text(self):
        a, t = make(TransportError("HTTP 401", 401))
        with self.assertRaises(TransportError) as cm:
            a.chat([{"role": "user", "content": "q"}])
        self.assertNotIn(KEY, json.dumps(t.calls[0]["body"]))
        self.assertNotIn(KEY, str(cm.exception))

    def test_ollama_localhost_without_key_ok_and_sends_no_auth(self):
        t = FakeTransport(reply("hi"))
        a = Adapter("http://localhost:11434/v1", None, "qwen2.5:14b", transport=t, mode="live")
        a.chat([{"role": "user", "content": "q"}])
        self.assertNotIn("Authorization", t.calls[0]["headers"])
        Adapter("http://127.0.0.1:11434/v1", None, "m", transport=t)

    def test_remote_http_refused_with_or_without_key(self):
        for key in (None, KEY):
            with self.subTest(key=key), self.assertRaises(LLMError):
                Adapter("http://example.com/v1", key, "m", transport=lambda *a, **k: self.fail("sent"))

    def test_localhost_http_with_key_refused(self):
        with self.assertRaises(LLMError):
            Adapter("http://localhost:11434/v1", KEY, "m", transport=lambda *a, **k: self.fail("sent"))


class PiiTests(unittest.TestCase):
    def test_pii_never_reaches_transport_and_is_restored_in_result(self):
        a, t = make(reply("Contact [EMAIL_1] about it."), masker_names=["Jane Doe"])
        msgs = [{"role": "system", "content": f"Owner {EMAIL}"},
                {"role": "user", "content": [{"type": "text", "text": f"Jane Doe wrote from {EMAIL}, call +1 415-555-0132"}]}]
        r = a.chat(msgs, job_id="j")
        sent = json.dumps(t.calls[0]["body"])
        for secret in (EMAIL, "Jane Doe", "415-555-0132"):
            self.assertNotIn(secret, sent)
        self.assertIn("[EMAIL_1]", sent)
        self.assertEqual(r.text, f"Contact {EMAIL} about it.")
        self.assertEqual(msgs[0]["content"], f"Owner {EMAIL}")                # caller's messages untouched

    def test_json_data_is_unmasked(self):
        a, _ = make(reply('{"answer": "[EMAIL_1]", "n": 1}'))
        r = a.chat([{"role": "user", "content": f"who? {EMAIL}"}], json_schema=SCHEMA)
        self.assertEqual(r.data["answer"], EMAIL)

    def test_same_job_keeps_placeholders_stable(self):
        a, t = make(reply("a"), reply("b"))
        a.chat([{"role": "user", "content": f"x {EMAIL}"}], job_id="J")
        a.chat([{"role": "user", "content": f"y other@example.org and {EMAIL}"}], job_id="J")
        self.assertIn("[EMAIL_1]", json.dumps(t.calls[1]["body"]))
        self.assertIn("[EMAIL_2]", json.dumps(t.calls[1]["body"]))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _env(self, d):
        return mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": str(d)})

    def test_committed_fixture_replays_with_zero_sockets(self):
        boom = AssertionError("network touched in replay mode")
        a = Adapter("https://llm.meshpool.ai/v1", KEY, "fixture-model", mode="replay",
                    transport=lambda *x, **k: self.fail("transport used in replay"))
        with self._env(FIXTURES), \
                mock.patch.object(socket.socket, "connect", side_effect=boom), \
                mock.patch.object(socket, "create_connection", side_effect=boom), \
                mock.patch.object(socket, "getaddrinfo", side_effect=boom), \
                mock.patch.object(urllib.request, "urlopen", side_effect=boom), \
                mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=boom):
            r = a.chat(REPLAY_MESSAGES, json_schema=SCHEMA)
        self.assertTrue(r.replayed)
        self.assertEqual(r.cost_usd, 0.0)
        self.assertEqual(r.data, {"answer": f"Note from {EMAIL}", "n": 7})        # PII restored from the masked fixture

    def test_committed_fixtures_contain_no_pii(self):
        files = list(FIXTURES.glob("*.json"))
        self.assertTrue(files)
        for f in files:
            self.assertNotIn("example.com", f.read_text())

    def test_replay_miss_raises_before_any_socket(self):
        boom = AssertionError("network touched")
        a = Adapter("https://llm.meshpool.ai/v1", KEY, "m", mode="replay")        # no transport: would use urllib
        with self._env(self.tmp.name), \
                mock.patch.object(socket.socket, "connect", side_effect=boom) as sc, \
                mock.patch.object(socket, "getaddrinfo", side_effect=boom) as ga, \
                mock.patch.object(urllib.request, "build_opener", side_effect=boom) as bo:
            with self.assertRaises(replay.ReplayMiss) as cm:
                a.chat([{"role": "user", "content": "never recorded"}])
            with self.assertRaises(replay.ReplayMiss):
                list(a.chat([{"role": "user", "content": "never recorded"}], stream=True))
        self.assertEqual(len(cm.exception.key), 64)
        for m in (sc, ga, bo):
            m.assert_not_called()

    def test_record_writes_masked_fixture_then_replays(self):
        rec, t = make(reply('{"answer": "[EMAIL_1]", "n": 7}'), mode="record")
        with self._env(self.tmp.name):
            live = rec.chat(REPLAY_MESSAGES, json_schema=SCHEMA)
            files = list(Path(self.tmp.name).glob("*.json"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertNotIn(EMAIL, text)
            self.assertIn("[EMAIL_1]", text)
            self.assertNotIn(EMAIL, json.dumps(t.calls[0]["body"]))
            rep = Adapter("https://llm.meshpool.ai/v1", KEY, "m", mode="replay")
            r = rep.chat(REPLAY_MESSAGES, json_schema=SCHEMA)
        self.assertEqual(r.data, live.data)
        self.assertEqual(r.data["answer"], EMAIL)
        self.assertTrue(r.replayed and not live.replayed)

    def test_invalid_reply_is_not_recorded(self):
        rec, _ = make(reply("bad"), reply("bad again"), mode="record")
        with self._env(self.tmp.name), self.assertRaises(InvalidJSON):
            rec.chat(REPLAY_MESSAGES, json_schema=SCHEMA)
        self.assertEqual(list(Path(self.tmp.name).glob("*.json")), [])

    def test_stream_record_and_replay(self):
        rec, _ = make(sse("Hi [EMAIL_", "1]"), mode="record")
        with self._env(self.tmp.name):
            self.assertEqual(rec.chat(REPLAY_MESSAGES, stream=True).text(), f"Hi {EMAIL}")
            rep = Adapter("https://llm.meshpool.ai/v1", KEY, "m", mode="replay")
            s = rep.chat(REPLAY_MESSAGES, stream=True)
            self.assertEqual(s.text(), f"Hi {EMAIL}")
            self.assertTrue(s.result.replayed)

    def test_env_mode_default_is_respected(self):
        a = Adapter("https://llm.meshpool.ai/v1", KEY, "m")
        with self._env(self.tmp.name), mock.patch.dict(os.environ, {"ACRETIA_LLM_MODE": "replay"}):
            with self.assertRaises(replay.ReplayMiss):
                a.chat([{"role": "user", "content": "x"}])


class LedgerTests(unittest.TestCase):
    def test_totals_per_job_and_overall(self):
        led = Ledger()
        a, _ = make(reply("a", 1000, 100), reply("b", 500, 50), reply("c", 200, 20), ledger=led, mask=False)
        a.chat([{"role": "user", "content": "1"}], job_id="J1")
        a.chat([{"role": "user", "content": "2"}], job_id="J1")
        a.chat([{"role": "user", "content": "3"}], job_id="J2")
        j1, j2, tot = led.total("J1"), led.total("J2"), led.total()
        self.assertEqual((j1["calls"], j1["input_tokens"], j1["output_tokens"]), (2, 1500, 150))
        self.assertEqual((j2["calls"], j2["input_tokens"]), (1, 200))
        self.assertEqual(tot["calls"], 3)
        self.assertAlmostEqual(tot["cost_usd"], j1["cost_usd"] + j2["cost_usd"])
        self.assertAlmostEqual(j2["cost_usd"], cost_usd("m", 200, 20))

    def test_jsonl_is_append_only_and_reloaded(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "ledger.jsonl"
            led = Ledger(p)
            led.record("J", "gpt-4.1-mini", 1000, 100)
            led.record("J", "gpt-4.1-mini", 10, 1)
            rows = [json.loads(x) for x in p.read_text().splitlines()]
            self.assertEqual([r["input_tokens"] for r in rows], [1000, 10])
            again = Ledger(p)
            self.assertEqual(again.total("J")["calls"], 2)
            again.record("K", "m", 1, 1)
            self.assertEqual(len(p.read_text().splitlines()), 3)

    def test_price_table_longest_match_and_cache_discount(self):
        self.assertAlmostEqual(cost_usd("gpt-4.1-mini-2025", 1_000_000, 0), 0.40)
        self.assertAlmostEqual(cost_usd("gpt-4.1", 1_000_000, 0), 2.0)
        self.assertAlmostEqual(cost_usd("claude-sonnet-5-5", 0, 1_000_000), 10.0)      # verified 2026-11-16
        self.assertAlmostEqual(cost_usd("claude-sonnet-4-5", 0, 1_000_000), 15.0)
        self.assertAlmostEqual(cost_usd("gpt-4.1", 1_000_000, 0, 1_000_000), 0.2)
        self.assertEqual(cost_usd("ollama:qwen", 10**6, 10**6, local=True), 0.0)
        self.assertGreater(cost_usd("ollama:qwen", 10**6, 10**6), 0.0)      # remote host: never free (F15)

    def test_spend_guard_blocks_before_the_call(self):
        led = Ledger(guard=SpendGuard(limit_usd=0.01))
        a, t = make(reply("x"), ledger=led)
        # worst case: 4096 output tokens of an unknown (expensive-default) model dwarfs $0.01
        with self.assertRaises(BudgetExceeded):
            a.chat([{"role": "user", "content": "q"}], max_tokens=4096, job_id="J")
        self.assertEqual(t.calls, [])
        self.assertEqual(led.total()["calls"], 0)

    def test_spend_guard_counts_spend_so_far_and_job_limit(self):
        guard = SpendGuard(limit_usd=1.0, job_limit_usd=0.10)
        led = Ledger(guard=guard)
        a, t = make(reply("x", 100, 100), reply("y"), ledger=led)
        a.model = "gpt-4.1-mini"
        a.chat([{"role": "user", "content": "q"}], max_tokens=1000, job_id="A")      # worst case ~$0.0016, fine
        led.record("A", "gpt-4.1-mini", 0, 60_000)                                    # job A has now spent ~$0.096
        with self.assertRaises(BudgetExceeded) as cm:
            a.chat([{"role": "user", "content": "q"}], max_tokens=4000, job_id="A")
        self.assertIn("job", str(cm.exception))
        self.assertEqual(len(t.calls), 1)
        a.chat([{"role": "user", "content": "q"}], max_tokens=1000, job_id="B")      # other jobs are unaffected
        self.assertEqual(len(t.calls), 2)

    def test_guard_checked_for_repair_and_stream(self):
        led = Ledger(guard=SpendGuard(limit_usd=0.005))
        a, t = make(sse("hi"), ledger=led)
        a.model = "gpt-4.1-mini"
        with self.assertRaises(BudgetExceeded):
            a.chat([{"role": "user", "content": "q"}], max_tokens=100_000, stream=True).text()
        self.assertEqual(t.calls, [])


class Om_llmDelegationTests(unittest.TestCase):
    """om/llm.py providers go through the adapter and keep their behaviour."""

    def test_openai_compat_provider_uses_adapter_request(self):
        seen = []
        p = llm.OpenAICompatProvider("meshpool", "m", "https://llm.meshpool.ai/v1", KEY,
                                     transport=lambda url, body, headers: seen.append((url, headers)) or reply('{"answer":"a","n":1}'))
        with mock.patch.object(adp.Adapter, "request", autospec=True, side_effect=adp.Adapter.request) as req:
            res = p.complete_json("s", [llm.Part("q")], SCHEMA)
        self.assertEqual(res.data["n"], 1)
        req.assert_called_once()
        self.assertEqual(seen[0][1]["Authorization"], f"Bearer {KEY}")

    def test_anthropic_without_sdk_client_routes_through_adapter_to_anthropic_host(self):
        seen = []
        tr = lambda url, body, headers: seen.append((url, headers)) or reply('{"answer":"a","n":1}')    # noqa: E731
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": KEY}):
            p = llm.make_provider("anthropic:claude-x", transport=tr)
        res = p.complete_json("s", [llm.Part("q")], SCHEMA)
        self.assertEqual(res.model, "anthropic:claude-x")
        self.assertEqual(seen[0][0], "https://api.anthropic.com/v1/chat/completions")
        self.assertEqual(seen[0][1]["Authorization"], f"Bearer {KEY}")

    def test_anthropic_needs_a_key_not_an_sdk(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(LLMError):
            llm.make_provider("anthropic")


class NoProviderSdkTests(unittest.TestCase):
    BANNED = ("anthropic", "openai", "google.generativeai", "google.genai", "mistralai", "cohere", "litellm")

    def test_no_module_imports_a_provider_sdk(self):
        allowed = ROOT / "src" / "harness" / "adapter.py"
        offenders = []
        for base in ("om", "src"):
            for path in (ROOT / base).rglob("*.py"):
                if path == allowed:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
                    elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__" and node.args \
                            and isinstance(node.args[0], ast.Constant):
                        names = [str(node.args[0].value)]
                    elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module" and node.args \
                            and isinstance(node.args[0], ast.Constant):
                        names = [str(node.args[0].value)]
                    for n in names:
                        if any(n == b or n.startswith(b + ".") for b in self.BANNED):
                            offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {n}")
        self.assertEqual(offenders, [])

    def test_adapter_itself_imports_no_sdk(self):
        tree = ast.parse((ROOT / "src" / "harness" / "adapter.py").read_text())
        mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse({m.split(".")[0] for m in mods} & {"anthropic", "openai", "mistralai", "cohere", "litellm"})

class HeaderEncodingTests(unittest.TestCase):
    def test_bad_key_is_a_clear_error_without_the_value(self):
        for bad in ("k\u2014ey", "abc\r\nX-Evil: 1"):
            a = Adapter("https://llm.meshpool.ai/v1", bad, "m", max_retries=0)
            with mock.patch.object(socket, "socket", side_effect=AssertionError("socket opened")):
                with self.assertRaises(LLMError) as cm:
                    a.request({"messages": []})
            self.assertIn("Authorization", str(cm.exception))
            self.assertNotIn(bad, str(cm.exception))
            self.assertNotIn("Evil", str(cm.exception))

    def test_urllib_transport_rejects_bad_header(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("socket opened")):
            with self.assertRaises(LLMError) as cm:
                adp.urllib_transport("https://llm.meshpool.ai/v1/x", {}, {"X-Test": "a\r\nb"})
        self.assertIn("X-Test", str(cm.exception))


# ====================================================================================== FP-S2b
import textwrap  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from src.harness.adapter import StreamInterrupted  # noqa: E402

MSG = [{"role": "user", "content": "q"}]


class AtomicSpendTests(unittest.TestCase):
    def test_threads_never_exceed_limit_and_blocked_never_reach_transport(self):
        led = Ledger(guard=SpendGuard(0.05))
        live, peak, calls = [0], [0], [0]
        lock = threading.Lock()

        def transport(url, body, headers):
            with lock:
                calls[0] += 1
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.15)
            with lock:
                live[0] -= 1
            return reply("x", 10, 5)
        a = Adapter("https://llm.meshpool.ai/v1", KEY, "claude-sonnet-x", transport=transport, mode="live", ledger=led, mask=False)
        outcomes = []

        def worker():
            try:
                a.chat(MSG, max_tokens=2000, job_id="J")
                outcomes.append("ok")
            except BudgetExceeded:
                outcomes.append("blocked")
        ts = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(outcomes.count("ok"), calls[0])            # a blocked call never touched the transport
        self.assertGreaterEqual(outcomes.count("blocked"), 1)
        self.assertEqual(peak[0], 1)                                # worst case $0.03 each: one in flight at a time
        self.assertLessEqual(led.total()["cost_usd"] + led.inflight_usd(), 0.05)
        self.assertEqual(led.inflight_usd(), 0.0)

    def test_four_processes_share_one_budget(self):
        with tempfile.TemporaryDirectory() as d:
            ledger, log = Path(d) / "l.jsonl", Path(d) / "sends.log"
            code = textwrap.dedent(f"""
                import sys, time, os
                sys.path.insert(0, {str(ROOT)!r})
                from src.harness.adapter import Adapter
                from src.harness.ledger import Ledger, SpendGuard, BudgetExceeded
                def tr(url, body, headers):
                    t0 = time.time(); time.sleep(0.2)
                    open({str(log)!r}, "a").write(f"{{t0}} {{time.time()}}\\n")
                    return {{"choices": [{{"message": {{"content": "x"}}, "finish_reason": "stop"}}], "usage": {{"prompt_tokens": 5, "completion_tokens": 2}}}}
                led = Ledger({str(ledger)!r}, guard=SpendGuard(0.05))
                a = Adapter("https://llm.meshpool.ai/v1", "{KEY}", "claude-sonnet-x", transport=tr, mode="live", ledger=led, mask=False)
                for _ in range(3):
                    try: a.chat([{{"role": "user", "content": "q"}}], max_tokens=2000, job_id="J")
                    except BudgetExceeded: pass
            """)
            ps = [subprocess.Popen([sys.executable, "-c", code]) for _ in range(4)]
            self.assertTrue(all(p.wait(60) == 0 for p in ps))
            spans = [tuple(map(float, l.split())) for l in log.read_text().splitlines()]
            peak = max(sum(1 for (a, b) in spans if a <= t0 < b) for (t0, _) in spans) if spans else 0
            self.assertEqual(peak, 1)                               # worst-case $0.03: never two sends in flight
            led = Ledger(ledger, guard=SpendGuard(0.05))
            self.assertEqual(led.total()["calls"], len(spans))
            self.assertLessEqual(led.total()["cost_usd"], 0.05)
            self.assertEqual(led.inflight_usd(), 0.0)
            self.assertEqual(len(ledger.read_text().splitlines()), len(spans))      # JSONL audit trail kept

    def test_retries_reserve_each_attempt_and_failures_release(self):
        led = Ledger(guard=SpendGuard(1.0))
        a, t = make(TransportError("x", 503), reply("ok", 10, 5), ledger=led, mask=False)
        a.model = "claude-sonnet-x"
        a.chat(MSG, max_tokens=100)
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(led.total()["calls"], 1)                   # the failed attempt cost nothing and holds nothing
        self.assertEqual(led.inflight_usd(), 0.0)

    def test_retry_blocked_by_budget_is_not_sent(self):
        led = Ledger(guard=SpendGuard(0.05))
        hold = led.reserve("other", "claude-sonnet-x", 0.04)         # someone else's in-flight call
        a, t = make(TransportError("x", 503), reply("ok"), ledger=led, mask=False)
        a.model = "claude-sonnet-x"
        with self.assertRaises(BudgetExceeded):
            a.chat(MSG, max_tokens=2000)
        self.assertEqual(t.calls, [])
        led.release(hold)

    def test_settle_and_release_are_idempotent_and_settle_unknown_bills_worst_case(self):
        led = Ledger(guard=SpendGuard(1.0))
        r = led.reserve("J", "gpt-4.1", 0.5)
        row = led.settle(r, None)
        self.assertAlmostEqual(row["cost_usd"], 0.5, places=4)
        self.assertEqual(led.settle(r, None), {})
        led.release(r)
        self.assertAlmostEqual(led.total()["cost_usd"], 0.5, places=4)
        r2 = led.reserve("J", "gpt-4.1", 0.3)
        led.release(r2)
        led.release(r2)
        self.assertEqual(led.inflight_usd(), 0.0)

    def test_repair_retry_reserves_again(self):
        led = Ledger(guard=SpendGuard(0.0045))
        a, t = make(reply("not json", 10, 2000), reply('{"answer":"a","n":1}'), ledger=led, mask=False)
        a.model = "gpt-4.1-mini"
        with self.assertRaises(BudgetExceeded):
            a.chat(MSG, json_schema=SCHEMA, max_tokens=2500, job_id="J")      # first fits ($0.004), the repair's reserve does not
        self.assertEqual(len(t.calls), 1)


class StreamBillingTests(unittest.TestCase):
    def test_abandoned_stream_bills_received_tokens_not_zero(self):
        led = Ledger(guard=SpendGuard(10.0))
        a, _ = make(sse("Hello ", "there ", "friend"), ledger=led, mask=False)
        s = a.chat(MSG, stream=True, max_tokens=1000, job_id="J")
        it = iter(s)
        next(it)
        s.close()
        tot = led.total("J")
        self.assertEqual(tot["calls"], 1)
        self.assertGreater(tot["cost_usd"], 0)
        self.assertEqual(led.inflight_usd(), 0.0)

    def test_stream_dropped_before_any_text_bills_worst_case(self):
        led = Ledger(guard=SpendGuard(10.0))
        a, _ = make([TransportError("reset")] and iter(()), ledger=led, mask=False)   # empty stream, no usage
        a.model = "gpt-4.1"
        s = a.chat(MSG, stream=True, max_tokens=1000, job_id="J")
        with self.assertRaises(StreamInterrupted):          # an empty stream without [DONE] is incomplete, not "empty text"
            s.text()
        self.assertGreater(led.total("J")["cost_usd"], 0)

    def test_unknown_usage_aborted_stream_is_worst_case(self):
        led = Ledger(guard=SpendGuard(10.0))

        def lines():
            raise TransportError("conn reset")
            yield
        a, _ = make(lines(), ledger=led, mask=False)
        a.model = "gpt-4.1"
        with self.assertRaises(TransportError):
            a.chat(MSG, stream=True, max_tokens=1000, job_id="J").text()
        worst = cost_usd("gpt-4.1", a._estimate_input_tokens(MSG), 1000)
        self.assertGreaterEqual(led.total("J")["cost_usd"], worst - 1e-9)
        self.assertAlmostEqual(led.total("J")["cost_usd"], worst, places=4)

    def test_mid_stream_failure_before_output_falls_back(self):
        def broken():
            raise TransportError("reset", 503)
            yield
        good, _ = make(sse("fine"), mask=False)
        a, _ = make(broken(), fallbacks=[good], mask=False)
        self.assertEqual(a.chat(MSG, stream=True).text(), "fine")

    def test_mid_stream_failure_after_output_raises_typed_with_partial(self):
        led = Ledger()

        def broken():
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "par"}}]}) + "\n"
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "tial"}}]}) + "\n"
            raise TransportError("reset", 503)
        good, gt = make(sse("other"), mask=False)
        a, _ = make(broken(), fallbacks=[good], ledger=led, mask=False)
        got = []
        with self.assertRaises(StreamInterrupted) as cm:
            for d in a.chat(MSG, stream=True, job_id="J"):
                got.append(d)
        self.assertEqual(cm.exception.partial_text, "".join(got))
        self.assertEqual(cm.exception.partial_text, "partial")
        self.assertTrue(cm.exception.retryable)
        self.assertGreater(cm.exception.usage["output_tokens"], 0)
        self.assertEqual(gt.calls, [])                              # never silently continued elsewhere
        self.assertGreater(led.total("J")["cost_usd"], 0)


class PiiOutboundTests(unittest.TestCase):
    def _sent(self, messages, **kw):
        a, t = make(reply("ok"), **kw)
        a.chat(messages)
        return json.dumps(t.calls[0]["body"], ensure_ascii=False)

    def test_every_string_field_is_masked(self):
        card, iban = "4111 1111 1111 1111", "DE89 3704 0044 0532 0130 00"
        msgs = [
            {"role": "user", "content": [{"type": "input_text", "text": f"mail {EMAIL}"},
                                         {"type": "tool_result", "content": [{"type": "text", "text": f"card {card}"}]}]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "lookup", "arguments": json.dumps({"iban": iban, "who": "x"})}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "bob.smith@corp.example.com", "content": f"result for {EMAIL}"},
        ]
        sent = self._sent(msgs)
        for raw in (EMAIL, card, iban, "bob.smith@corp.example.com"):
            self.assertNotIn(raw, sent)
        self.assertIn("c1", sent)
        self.assertIn("lookup", sent)

    def test_tool_call_arguments_are_unmasked_in_the_reply(self):
        j = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c", "type": "function", "function": {
            "name": "send", "arguments": '{"to": "[EMAIL_1]"}'}}]}, "finish_reason": "tool_calls"}], "usage": {}}
        a, _ = make(j)
        r = a.chat([{"role": "user", "content": f"write to {EMAIL}"}])
        self.assertEqual(json.loads(r.tool_calls[0]["function"]["arguments"]), {"to": EMAIL})

    def test_confusable_and_spaced_pii_masked_before_send(self):
        cases = ["jane.doe\uff20example.com", "4111\u00a01111\u00a01111\u00a01111", "4111\u20091111\u20091111\u20091111",
                 "de89 3704 0044 0532 0130 00", "gb82west12345698765432"]
        for c in cases:
            with self.subTest(c=c):
                sent = self._sent([{"role": "user", "content": f"see {c} thanks"}])
                self.assertNotIn(c, sent)
                self.assertNotIn(c.replace("\u00a0", "\\u00a0"), sent)


class RecordPiiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)

    def _fixtures_text(self):
        return "".join(f.read_text() for f in Path(self.tmp.name).glob("*.json"))

    def test_record_masks_pii_in_the_reply_and_never_writes_it(self):
        a, _ = make(reply("contact ceo@bigcorp.com or 4111 1111 1111 1111"), mode="record")
        r = a.chat([{"role": "user", "content": "who?"}], job_id="J")
        self.assertIn("ceo@bigcorp.com", r.text)                     # the live caller still gets the answer
        saved = self._fixtures_text()
        self.assertTrue(saved)
        self.assertNotIn("bigcorp", saved)
        self.assertNotIn("4111", saved)
        self.assertIn("[EMAIL_", saved)

    def test_record_refuses_when_masking_is_off(self):
        a, _ = make(reply("mail ceo@bigcorp.com"), mode="record", mask=False)
        with self.assertRaises(replay.FixturePII):
            a.chat([{"role": "user", "content": "who?"}])
        self.assertEqual(self._fixtures_text(), "")

    def test_replay_save_itself_refuses_raw_pii(self):
        with self.assertRaises(replay.FixturePII):
            replay.save("k" * 64, "t", {"text": "x@y.example.org"}, {}, "m")


class KeyEchoTests(unittest.TestCase):
    def test_error_body_echoing_the_key_is_redacted_everywhere(self):
        import http.server

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = f'{{"error": "bad key {KEY} (Authorization: Bearer {KEY})"}}'.encode()
                self.send_response(401)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        with self.assertRaises(TransportError) as cm:
            adp.urllib_transport(f"http://127.0.0.1:{srv.server_port}/chat/completions", {}, {"Authorization": f"Bearer {KEY}"})
        self.assertNotIn(KEY, str(cm.exception))
        self.assertNotIn(KEY, repr(cm.exception))
        self.assertEqual(cm.exception.status, 401)

    def test_custom_transport_errors_are_scrubbed_and_not_chained(self):
        for exc in (TransportError(f"HTTP 401: echo {KEY}", 401), ConnectionError(f"reset, header Authorization: Bearer {KEY}"),
                    ValueError(f"weird {KEY}")):
            with self.subTest(exc=type(exc).__name__):
                a, _ = make(exc, max_retries=0, mask=False)
                with self.assertRaises(Exception) as cm:
                    a.chat(MSG)
                e = cm.exception
                self.assertNotIn(KEY, str(e))
                self.assertNotIn(KEY, repr(e))
                self.assertIsNone(e.__context__)
                self.assertNotIn(KEY, "".join(__import__("traceback").format_exception(e)))

    def test_redact_patterns(self):
        t = adp.redact("Authorization: Bearer abcdef123456 and bearer zzzzzzzz9 and key sk-live-999999", "sk-live-999999")
        for bad in ("abcdef123456", "zzzzzzzz9", "sk-live-999999"):
            self.assertNotIn(bad, t)

    def test_fallback_event_does_not_leak_key(self):
        b, _ = make(reply("ok"), mask=False)
        a, _ = make(TransportError(f"HTTP 503 {KEY}", 503), fallbacks=[b], max_retries=0, mask=False)
        r = a.chat(MSG)
        self.assertNotIn(KEY, json.dumps(r.fallbacks))


class PriceTests(unittest.TestCase):
    def test_verified_prices_and_default_is_most_expensive(self):
        self.assertEqual(adp.Ledger and __import__("src.harness.ledger", fromlist=["x"]).price_for("gpt-5-pro"), (15.0, 120.0))
        from src.harness.ledger import price_for, DEFAULT_PRICE, PRICES
        self.assertEqual(price_for("gemini-2.5-pro"), (2.5, 15.0))
        self.assertEqual(price_for("gpt-5-pro-2026"), (15.0, 120.0))
        self.assertEqual(price_for("claude-opus-4.1"), (15.0, 75.0))
        self.assertEqual(price_for("totally-unknown-model"), DEFAULT_PRICE)
        self.assertEqual(DEFAULT_PRICE, (max(p[0] for p in PRICES.values()), max(p[1] for p in PRICES.values())))

    def test_profile_prices_match_ledger_and_are_sourced(self):
        from src.harness.ledger import price_for
        for f in (ROOT / "src" / "harness" / "profiles").glob("*.json"):
            d = json.loads(f.read_text())
            self.assertIn("price_verified", d)
            self.assertIn("price_date", d)
            if d["price_verified"] and d["family"] != "local":
                self.assertTrue(d["price_source"], f.name)
            for m, p in d["prices_per_mtok_by_model"].items():
                if d["family"] != "local":
                    self.assertEqual(tuple(p.values()), price_for(m), f"{f.name}:{m}")


# ---------------------------------------------------------------------------------------------------- FP-S2e2
from src.harness.ledger import LedgerError, price_for  # noqa: E402
from om import pii as _pii  # noqa: E402

_MSGS = [{"role": "user", "content": "hello"}]


def _sse_events(deltas, finish=None, done=True, usage=None):
    out = ["data: " + json.dumps({"choices": [{"delta": {"content": d}}]}) + "\n" for d in deltas]
    if finish:
        out.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": finish}]}) + "\n")
    if usage:
        out.append("data: " + json.dumps({"choices": [], "usage": usage}) + "\n")
    if done:
        out.append("data: [DONE]\n")
    return out


class TruncationTests(unittest.TestCase):
    def test_stream_without_done_is_interrupted_not_complete(self):
        a, _ = make(_sse_events(["half an ans"], done=False), mask=False)
        with self.assertRaises(StreamInterrupted) as cm:
            a.chat(_MSGS, stream=True).text()
        self.assertTrue(cm.exception.retryable)
        self.assertEqual(cm.exception.partial_text, "half an ans")

    def test_stream_finish_length_and_content_filter_are_interrupted(self):
        for fin in ("length", "content_filter"):
            a, _ = make(_sse_events(["abc"], finish=fin), mask=False)
            with self.assertRaises((StreamInterrupted, LLMRefusal)):
                a.chat(_MSGS, stream=True).text()

    def test_complete_stream_still_ok(self):
        a, _ = make(_sse_events(["ab", "c"], finish="stop"), mask=False)
        self.assertEqual(a.chat(_MSGS, stream=True).text(), "abc")

    def test_truncated_stream_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": d}):
            a, _ = make(_sse_events(["half"], done=False), mode="record", mask=False)
            with self.assertRaises(StreamInterrupted):
                a.chat(_MSGS, stream=True).text()
            self.assertEqual(list(Path(d).rglob("*.json")), [])

    def test_stream_truncation_is_still_billed(self):
        led = Ledger(guard=SpendGuard(10.0))
        a, _ = make(_sse_events(["half"], done=False), ledger=led, mask=False)
        with self.assertRaises(StreamInterrupted):
            a.chat(_MSGS, stream=True, job_id="J").text()
        self.assertEqual(led.total("J")["calls"], 1)
        self.assertEqual(led.inflight_usd(), 0.0)

    def test_plain_nonstream_length_raises_with_partial_text(self):
        a, _ = make(reply("partial reply", finish="length"), mask=False)
        with self.assertRaises(StreamInterrupted) as cm:
            a.chat(_MSGS)
        self.assertTrue(cm.exception.retryable)
        self.assertEqual(cm.exception.partial_text, "partial reply")

    def test_schema_length_repairs_once_with_higher_max_tokens(self):
        a, t = make(reply('{"answer": "x', finish="length"), reply('{"answer": "ok", "n": 1}'), mask=False)
        r = a.chat(_MSGS, json_schema=SCHEMA, max_tokens=100)
        self.assertEqual(r.data, {"answer": "ok", "n": 1})
        self.assertEqual(len(t.calls), 2)
        self.assertGreater(t.calls[1]["body"]["max_tokens"], t.calls[0]["body"]["max_tokens"])

    def test_schema_length_twice_falls_through_to_next_adapter(self):
        fb, ft = make(reply('{"answer": "fb", "n": 2}'), mask=False)
        a, t = make(reply('{"a":', finish="length"), reply('{"a":', finish="length"), fallbacks=[fb], mask=False)
        r = a.chat(_MSGS, json_schema=SCHEMA)
        self.assertEqual(r.data, {"answer": "fb", "n": 2})
        self.assertEqual(len(t.calls), 2)
        self.assertEqual(len(ft.calls), 1)

    def test_truncated_reply_never_recorded(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": d}):
            a, _ = make(reply("cut", finish="length"), mode="record", mask=False)
            with self.assertRaises(StreamInterrupted):
                a.chat(_MSGS)
            a2, _ = make(reply('{"a":', finish="length"), reply('{"a":', finish="length"), mode="record", mask=False)
            with self.assertRaises(InvalidJSON):
                a2.chat(_MSGS, json_schema=SCHEMA)
            self.assertEqual(list(Path(d).rglob("*.json")), [])


class UntrustedUsageTests(unittest.TestCase):
    def test_negative_provider_usage_never_lowers_totals(self):
        led = Ledger(guard=SpendGuard(10.0))
        a, _ = make(reply("a", prompt=-10**9, completion=-10**9), reply("b", prompt=-10**9, completion=-10**9),
                    ledger=led, mask=False)
        seen = [led.total()["cost_usd"]]
        for _ in range(2):
            a.chat(_MSGS, job_id="J")
            seen.append(led.total()["cost_usd"])
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(min(seen), 0.0)
        self.assertGreater(seen[-1], 0.0)                 # at least the input estimate was billed
        tot = led.total("J")
        self.assertGreaterEqual(tot["input_tokens"], 0)
        self.assertGreaterEqual(tot["output_tokens"], 0)

    def test_absurd_and_nan_usage_bills_worst_case(self):
        led = Ledger(guard=SpendGuard(1000.0))
        for bad in (10**12, float("nan"), "lots"):
            res = led.reserve("J", "gpt-4.1", 0.5, est_input_tokens=7)
            row = led.settle(res, {"input_tokens": bad, "output_tokens": 5})
            self.assertGreaterEqual(row["cost_usd"], 0.5 - 1e-6)
            self.assertIn("rejected", row["note"])

    def test_settle_bills_at_least_the_input_estimate(self):
        led = Ledger()
        res = led.reserve("J", "gpt-4.1", 1.0, est_input_tokens=1000)
        row = led.settle(res, {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(row["input_tokens"], 1000)

    def test_precheck_negative_max_tokens_is_not_negative(self):
        led = Ledger(guard=SpendGuard(10.0))
        self.assertGreaterEqual(led.precheck("J", "gpt-4.1", 10, -10**9), 0.0)

    def test_record_rejects_negative_and_nan_cost(self):
        led = Ledger(prices={"x": (-1.0, -1.0)})
        with self.assertRaises(LedgerError):
            led.record("J", "x", 10, 10)
        self.assertEqual(led.total()["calls"], 0)
        led2 = Ledger(prices={"x": (float("nan"), 1.0)})
        with self.assertRaises(LedgerError):
            led2.record("J", "x", 10, 10)
        self.assertEqual(led2.total()["calls"], 0)
        with self.assertRaises(LedgerError):
            Ledger().record("J", "gpt-4.1", 10**9, 1)

    def test_record_clamps_negative_tokens(self):
        led = Ledger()
        row = led.record("J", "gpt-4.1", -5, -5, -5)
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["cost_usd"]), (0, 0, 0.0))

    def test_file_backed_negative_usage_monotonic(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "l.jsonl", guard=SpendGuard(10.0))
            last = 0.0
            for _ in range(3):
                res = led.reserve("J", "gpt-4.1", 0.01, est_input_tokens=5)
                led.settle(res, {"input_tokens": -10**9, "output_tokens": -10**9})
                cur = led.total()["cost_usd"]
                self.assertGreaterEqual(cur, last)
                last = cur


class LocalPriceTests(unittest.TestCase):
    def test_local_model_free_only_on_local_host(self):
        self.assertEqual(price_for("my-local-model", local=True), (0.0, 0.0))
        from src.harness.ledger import DEFAULT_PRICE
        self.assertEqual(price_for("my-local-model"), DEFAULT_PRICE)
        self.assertEqual(price_for("local-llm"), DEFAULT_PRICE)

    def test_adapter_is_local(self):
        self.assertTrue(Adapter("http://localhost:11434/v1", None, "m").is_local)
        self.assertTrue(Adapter("http://127.0.0.1:11434/v1", None, "m").is_local)
        self.assertTrue(Adapter("http://[::1]:11434/v1", None, "m").is_local)
        self.assertFalse(Adapter("https://llm.meshpool.ai/v1", KEY, "m").is_local)
        self.assertTrue(Adapter("https://gpu.internal/v1", None, "m", local_hosts=["gpu.internal"]).is_local)
        self.assertFalse(Adapter("https://gpu.internal/v1", None, "m").is_local)

    def test_remote_host_with_local_model_id_is_billed_at_default_price(self):
        led = Ledger()
        a, _ = make(reply("x", prompt=1000, completion=1000), ledger=led, mask=False)
        a.model = "my-local-model"
        a.chat(_MSGS, job_id="J")
        self.assertGreater(led.total("J")["cost_usd"], 0.0)

    def test_local_host_local_model_is_free(self):
        led = Ledger()
        t = FakeTransport(reply("x", prompt=1000, completion=1000))
        a = Adapter("http://localhost:11434/v1", None, "ollama:qwen", transport=t, mode="live", ledger=led, mask=False)
        a.chat(_MSGS, job_id="J")
        self.assertEqual(led.total("J")["cost_usd"], 0.0)
        self.assertEqual(led.total("J")["calls"], 1)

    def test_configured_local_host_is_free(self):
        led = Ledger()
        t = FakeTransport(reply("x", prompt=1000, completion=1000))
        a = Adapter("https://gpu.internal/v1", None, "my-local-model", transport=t, mode="live", ledger=led, mask=False,
                    local_hosts=["gpu.internal"])
        a.chat(_MSGS, job_id="J")
        self.assertEqual(led.total("J")["cost_usd"], 0.0)


class ZeroWidthPiiTests(unittest.TestCase):
    def _check(self, text, secret_fragments):
        m = _pii.Masker()
        out, _ = m.mask(text)
        for frag in secret_fragments:
            self.assertNotIn(frag, out)
        for ch in "\u200b\u200c\u200d\u2060\ufeff":
            self.assertNotIn(ch, out)
        self.assertEqual(m.unmask(out), text)             # round trip restores the original, zero-width chars included
        return out

    def test_email_split_by_zwsp(self):
        out = self._check("mail b\u200bob@corp.com now", ["ob@corp.com", "corp.com"])
        self.assertEqual(out, "mail [EMAIL_1] now")
        out = self._check("x bo\u200b\u200bb@co\u200brp.com. y", ["bob", "corp.com"])
        self.assertIn("[EMAIL_1]", out)

    def test_card_split_by_word_joiner(self):
        out = self._check("card 4111\u20601111 1111\u20601111 end", ["4111", "1111"])
        self.assertEqual(out, "card [CARD_1] end")

    def test_phone_with_bom(self):
        out = self._check("call (415)\ufeff555-0132 or +1\u200b 415 555 0132 now", ["555-0132", "0132"])
        self.assertIn("[PHONE_1]", out)

    def test_same_email_with_and_without_zero_width_shares_placeholder(self):
        m = _pii.Masker()
        out, _ = m.mask("bob@corp.com and b\u200bob@corp.com")
        self.assertEqual(out, "[EMAIL_1] and [EMAIL_1]")

    def test_adapter_outbound_has_no_fragment(self):
        a, t = make(reply("ok"))
        a.chat([{"role": "user", "content": "write to b\u200bob@corp.com"}])
        sent = json.dumps(t.calls[0]["body"], ensure_ascii=False)
        self.assertNotIn("corp.com", sent)
        self.assertNotIn("\u200b", sent)


if __name__ == "__main__":
    unittest.main()
