"""P1.3: task routing, MeshPool key binding, fallback chain, PII masking, record/replay, per-job meter. Fully offline."""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import llm, pii, replay  # noqa: E402
from om.llm import InvalidJSON, LLMError, LLMRefusal, Meter, Part, Result, Router, TransportError  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}, "n": {"type": "integer"}},
          "required": ["answer", "n"]}
# Replay fixtures (committed). Regenerate with ACRETIA_LLM_MODE=record and the same prompts + a fake provider.
SYS = "You extract facts."
EXTRACT_PARTS = [Part("Contact: jane.doe@acme.com, +1 415 555 0132. Revenue FY2024 was $12.3bn (1,234.5m).")]
REASON_PARTS = [Part("Explain the margin trend. CIK 0000320193, period 2024-03-31.")]


class FakeProvider:
    def __init__(self, name="fake", model="m", replies=None, usage=None):
        self.name, self.model = name, model
        self.replies = list(replies or [])
        self.calls = []
        self.usage = usage or {"input_tokens": 1000, "output_tokens": 100}

    def complete_json(self, system, parts, schema, repair_note=None, **kw):
        self.calls.append({"system": system, "text": "\n".join(p.text for p in parts), "repair": repair_note, "kw": kw})
        r = self.replies.pop(0) if self.replies else {"answer": "ok", "n": 1}
        if isinstance(r, BaseException):
            raise r
        return Result(r, dict(self.usage), f"{self.name}:{self.model}")


def router(**kw):
    kw.setdefault("mode", "live")
    return Router(**kw)


class TaskRoutingTests(unittest.TestCase):
    def test_task_types_map_onto_existing_stages(self):
        self.assertEqual(llm.TASK_TYPES, ("extraction", "modeling", "reasoning", "vision_critic"))
        for t in llm.TASK_TYPES:
            self.assertIn(llm.TASK_STAGES[t], llm.STAGES)

    def test_complete_task_and_for_task(self):
        ext, mod = FakeProvider("ext"), FakeProvider("mod")
        r = router(overrides={"extraction": ext, "sheets_agent": mod})
        r.complete_task("extraction", "s", [Part("q")], SCHEMA)
        r.for_task("modeling").complete_json("s", [Part("q")], SCHEMA)         # task -> stage sheets_agent
        self.assertEqual((len(ext.calls), len(mod.calls)), (1, 1))
        with self.assertRaises(LLMError):
            r.for_task("nope")

    def test_stage_calls_unchanged_and_task_env_override(self):
        p = FakeProvider()
        r = router(overrides={"matrix": p})
        r.complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(len(p.calls), 1)
        self.assertEqual(r.for_task("extraction").provider(), p)               # extraction -> matrix stage override
        with mock.patch.dict(os.environ, {"OM_MODEL_REASONING": "ollama:qwen2.5:14b"}, clear=False):
            self.assertEqual(Router().describe("ask", "reasoning"), "ollama:qwen2.5:14b")


class MeshPoolTests(unittest.TestCase):
    KEY = "mp-test-key-not-real"

    def test_meshpool_is_default_when_only_its_key_is_set(self):
        env = {k: "" for k in ("OM_MODEL_DEFAULT", "OM_MODEL_MATRIX", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")}
        with mock.patch.dict(os.environ, {**env, "MESHPOOL_API_KEY": self.KEY}):
            self.assertEqual(llm.configured_spec("matrix"), "meshpool")
            p = llm.make_provider("meshpool:some-model")
            self.assertEqual((p.base_url, p.model), ("https://llm.meshpool.ai/v1", "some-model"))
            self.assertEqual(llm.make_provider("meshpool").model, "auto")

    def test_key_is_sent_only_to_meshpool_host(self):
        seen = []
        with mock.patch.dict(os.environ, {"MESHPOOL_API_KEY": self.KEY}):
            p = llm.make_provider("meshpool:m", transport=lambda url, body, headers: seen.append((url, headers)) or
                                  {"choices": [{"message": {"content": '{"answer":"a","n":1}'}, "finish_reason": "stop"}]})
        p.complete_json("s", [Part("q")], SCHEMA)
        self.assertEqual(seen[0][0], "https://llm.meshpool.ai/v1/chat/completions")
        self.assertEqual(seen[0][1]["Authorization"], f"Bearer {self.KEY}")

    def test_key_refused_for_other_and_lookalike_hosts(self):
        bad = ["https://api.openai.com/v1", "https://llm.meshpool.ai.evil.com/v1", "https://evil.com/llm.meshpool.ai",
               "https://llm.meshpool.ai@evil.com/v1", "https://xllm.meshpool.ai/v1", "https://meshpool.ai/v1",
               "https://llm.meshpool.ai./v1", "http://llm.meshpool.ai/v1", "https://llm.meshpool.ai:8443/v1",
               "https://user:pw@llm.meshpool.ai/v1", "https://LLM.MESHPOOL.AI.evil.com/v1"]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(LLMError):
                    llm.key_host_guard(url, llm.MESHPOOL_HOST)
                with self.assertRaises(LLMError):
                    llm.OpenAICompatProvider("meshpool", "m", url, self.KEY, transport=lambda *a: {})
        llm.key_host_guard("https://llm.meshpool.ai/v1", llm.MESHPOOL_HOST)     # the one allowed host
        llm.key_host_guard("https://LLM.meshpool.ai/v1", llm.MESHPOOL_HOST)

    def test_env_base_url_override_cannot_redirect_the_key(self):
        with mock.patch.dict(os.environ, {"MESHPOOL_API_KEY": self.KEY, "OM_PROVIDER_MESHPOOL_BASE_URL": "https://llm.meshpool.ai.evil.com/v1"}):
            with self.assertRaises(LLMError):
                llm.make_provider("meshpool")

    def test_base_url_mutated_after_construction_is_refused_at_call_time(self):
        p = llm.OpenAICompatProvider("meshpool", "m", "https://llm.meshpool.ai/v1", self.KEY, transport=lambda *a: self.fail("sent"))
        p.base_url = "https://evil.com/v1"
        with self.assertRaises(LLMError):
            p.complete_json("s", [Part("q")], SCHEMA)

    def test_redirect_to_another_host_is_refused(self):
        h = llm._SameHostRedirect(llm.MESHPOOL_HOST, True)
        req = urllib.request.Request("https://llm.meshpool.ai/v1/chat/completions", data=b"{}", headers={"Authorization": "Bearer x"})
        for dest in ("https://evil.com/steal", "https://llm.meshpool.ai.evil.com/v1", "http://llm.meshpool.ai/v1"):
            with self.subTest(dest=dest), self.assertRaises(LLMError):
                h.redirect_request(req, None, 307, "Temporary Redirect", {}, dest)
        get = urllib.request.Request("https://llm.meshpool.ai/v1/models")
        self.assertIsNotNone(h.redirect_request(get, None, 302, "Found", {}, "https://llm.meshpool.ai/v2/models"))   # same host passes the guard

    def test_default_post_uses_the_redirect_guard(self):
        p = llm.OpenAICompatProvider("meshpool", "m", "https://llm.meshpool.ai/v1", self.KEY)
        used = []
        real = urllib.request.build_opener

        def spy(*handlers):
            used.extend(handlers)
            raise urllib.error.URLError("stop")
        with mock.patch.object(urllib.request, "build_opener", spy), self.assertRaises(urllib.error.URLError):
            p._post("https://llm.meshpool.ai/v1/chat/completions", {}, {})
        self.assertTrue(any(isinstance(h, llm._SameHostRedirect) and h.host == "llm.meshpool.ai" and h.has_key for h in used))
        self.assertTrue(callable(real))


class FallbackTests(unittest.TestCase):
    def test_transport_5xx_and_timeout_fall_through(self):
        a = FakeProvider("a", replies=[TransportError("a HTTP 503", 503)])
        b = FakeProvider("b", replies=[TimeoutError("slow")])
        c = FakeProvider("c", replies=[{"answer": "from c", "n": 3}])
        r = router(overrides={"matrix": a}, chains={"matrix": [b, c]})
        res = r.complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(res.data["answer"], "from c")
        self.assertEqual([e["kind"] for e in res.fallbacks], ["transport", "transport"])
        self.assertEqual((len(a.calls), len(b.calls), len(c.calls)), (1, 1, 1))

    def test_client_error_4xx_does_not_fall_through(self):
        a = FakeProvider("a", replies=[TransportError("a HTTP 401", 401)])
        b = FakeProvider("b")
        with self.assertRaises(TransportError):
            router(overrides={"matrix": a}, chains={"matrix": [b]}).complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(b.calls, [])

    def test_invalid_json_retries_once_then_falls_through(self):
        a = FakeProvider("a", replies=[InvalidJSON("bad"), InvalidJSON("bad again")])
        b = FakeProvider("b", replies=[{"answer": "b", "n": 2}])
        res = router(overrides={"matrix": a}, chains={"matrix": [b]}).complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(len(a.calls), 2)                       # one retry, with a repair note
        self.assertIn("not valid JSON", a.calls[1]["repair"])
        self.assertEqual(res.data["answer"], "b")
        self.assertEqual(res.fallbacks[0]["kind"], "invalid_json")

    def test_invalid_json_then_repaired_stays_on_same_provider(self):
        a = FakeProvider("a", replies=[InvalidJSON("bad"), {"answer": "fixed", "n": 1}])
        b = FakeProvider("b")
        res = router(overrides={"matrix": a}, chains={"matrix": [b]}).complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertTrue(res.repaired)
        self.assertEqual(b.calls, [])

    def test_refusal_is_recorded_and_not_silently_skipped(self):
        a = FakeProvider("a", replies=[LLMRefusal("no")])
        b = FakeProvider("b")
        r = router(overrides={"matrix": a}, chains={"matrix": [b]})
        with self.assertRaises(LLMRefusal):
            r.complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(b.calls, [])
        self.assertEqual([e["kind"] for e in r.events], ["refusal"])
        r2 = router(overrides={"matrix": FakeProvider("a", replies=[LLMRefusal("no")])}, chains={"matrix": [FakeProvider("b")]},
                    fallthrough_on_refusal=True)               # explicit opt-in still records it
        res = r2.complete_json("matrix", "s", [Part("q")], SCHEMA)
        self.assertEqual(res.fallbacks[0]["kind"], "refusal")

    def test_all_fail_raises_last_error_and_chain_from_env(self):
        r = router(overrides={"matrix": FakeProvider("a", replies=[TransportError("x", 500)])},
                   chains={"matrix": [FakeProvider("b", replies=[TransportError("y", 502)])]})
        with self.assertRaisesRegex(TransportError, "y"):
            r.complete_json("matrix", "s", [Part("q")], SCHEMA)
        env = {"OM_MODEL_DEFAULT": "ollama:q", "OM_FALLBACK_DEFAULT": "ollama:other, ollama:q"}
        with mock.patch.dict(os.environ, env):
            names = [p.model for p in Router().providers("matrix")]
        self.assertEqual(names, ["q", "other"])                 # deduplicated, ordered


class PiiTests(unittest.TestCase):
    def test_masks_and_round_trips(self):
        m = pii.Masker(["Jane Doe"])
        text = ("Email jane.doe@acme.com, phone +44 20 7946 0958 or (415) 555-0132, IBAN DE89 3704 0044 0532 0130 00, "
                "card 4111 1111 1111 1111, SSN 123-45-6789, NINO AB 12 34 56 C, owner Jane Doe.")
        masked, mapping = m.mask(text)
        for secret in ("jane.doe@acme.com", "7946", "555-0132", "DE89", "4111", "123-45-6789", "AB 12 34 56 C", "Jane Doe"):
            self.assertNotIn(secret, masked)
        for kind in ("EMAIL", "PHONE", "IBAN", "CARD", "SSN", "NINO", "PERSON"):
            self.assertIn(f"[{kind}_1]", masked)
        self.assertEqual(m.unmask(masked, mapping), text)

    def test_same_value_same_placeholder_within_a_job(self):
        m = pii.Masker()
        a, _ = m.mask("a@x.com then b@x.com")
        b, _ = m.mask("again a@x.com and 415-555-0132 and (415) 555 0132")
        self.assertEqual(a, "[EMAIL_1] then [EMAIL_2]")
        self.assertTrue(b.startswith("again [EMAIL_1] and [PHONE_1] and [PHONE_1]"))

    def test_checksums_gate_iban_and_card(self):
        self.assertTrue(pii.iban_ok("GB82 WEST 1234 5698 7654 32"))
        self.assertFalse(pii.iban_ok("GB82 WEST 1234 5698 7654 33"))
        self.assertTrue(pii.luhn_ok("4111111111111111"))
        self.assertFalse(pii.luhn_ok("4111111111111112"))
        masked, _ = pii.Masker().mask("bad GB82 WEST 1234 5698 7654 33 and 4111 1111 1111 1112")
        self.assertIn("GB82 WEST 1234 5698 7654 33", masked)
        self.assertIn("4111 1111 1111 1112", masked)

    def test_ordinary_financial_text_untouched(self):
        text = ("Revenue 1,234.5m in FY2024 ($12.3bn), margin 12.5%, EBITDA 1,234,567,890,123, as of 2024-03-31 / 31/03/2024, "
                "CIK 0000320193, accession 0000320193-24-000123, Q3'24, 10-K, EV/EBITDA 14.2x, shares 15,115,823,000, "
                "range 2019-2024, ticker AAPL, NASDAQ:AAPL, 3-2-1 ratio, +12.5% yoy, tel-free 1.5.")
        self.assertEqual(pii.Masker().mask(text)[0], text)

    def test_unmask_ignores_unknown_placeholders_and_walks_json(self):
        obj = {"a": "[EMAIL_1] wrote", "b": ["[PHONE_9]", 3, None], "c": {"d": "x [EMAIL_1]"}}
        out = pii.unmask_obj(obj, {"[EMAIL_1]": "a@b.co"})
        self.assertEqual(out, {"a": "a@b.co wrote", "b": ["[PHONE_9]", 3, None], "c": {"d": "x a@b.co"}})

    def test_router_masks_outbound_and_unmasks_result(self):
        p = FakeProvider(replies=[{"answer": "Reach [EMAIL_1] at [PHONE_1]", "n": 1}])
        r = router(overrides={"matrix": p})
        res = r.complete_json("matrix", "Owner jane.doe@acme.com", [Part("call +1 415 555 0132"), Part("x", cache=True)], SCHEMA)
        sent = p.calls[0]["system"] + p.calls[0]["text"]
        self.assertNotIn("jane.doe@acme.com", sent)
        self.assertNotIn("555 0132", sent)
        self.assertIn("[EMAIL_1]", sent)
        self.assertEqual(res.data["answer"], "Reach jane.doe@acme.com at +1 415 555 0132")

    def test_job_keeps_placeholders_stable_and_names_are_supplied(self):
        p = FakeProvider()
        r = router(overrides={"matrix": p})
        r.complete_json("matrix", "s", [Part("a@x.com")], SCHEMA, job_id="j1")
        r.complete_json("matrix", "s", [Part("b@x.com and a@x.com and Bob Smith")], SCHEMA, job_id="j1", pii_names=["Bob Smith"])
        self.assertIn("[EMAIL_2] and [EMAIL_1] and [PERSON_1]", p.calls[1]["text"])
        r.complete_json("matrix", "s", [Part("a@x.com")], SCHEMA, mask=False)
        self.assertIn("a@x.com", p.calls[2]["text"])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ACRETIA_LLM_MODE": "replay", "ACRETIA_LLM_FIXTURES": str(FIXTURES)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_committed_fixtures_replay_with_unmasked_output(self):
        r = Router()                                            # mode from env = replay; no providers, no keys
        res = r.complete_task("extraction", SYS, EXTRACT_PARTS, SCHEMA)
        self.assertEqual(res.data, {"answer": "Contact jane.doe@acme.com on +1 415 555 0132; FY2024 revenue $12.3bn.", "n": 1})
        res2 = r.complete_json("ask", SYS, REASON_PARTS, SCHEMA)
        self.assertEqual(res2.data["n"], 2)
        self.assertEqual(r.meter.totals()["replayed_calls"], 2)
        self.assertEqual(r.meter.totals()["cost_usd"], 0.0)

    def test_fixtures_contain_no_pii(self):
        files = list(FIXTURES.glob("*.json"))
        self.assertGreaterEqual(len(files), 2)
        blob = "".join(f.read_text() for f in files)
        for secret in ("jane.doe@acme.com", "555 0132", "415"):
            self.assertNotIn(secret, blob)
        for f in files:
            self.assertEqual(json.loads(f.read_text())["key"], f.stem)

    def test_miss_raises_and_makes_zero_network_calls(self):
        boom = AssertionError("network used in replay mode")
        provider = FakeProvider()
        provider.complete_json = mock.Mock(side_effect=boom)
        with mock.patch.object(urllib.request, "urlopen", side_effect=boom) as uo, \
                mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=boom) as op, \
                mock.patch.object(socket.socket, "connect", side_effect=boom) as sc, \
                mock.patch.object(socket, "create_connection", side_effect=boom) as cc, \
                mock.patch.object(socket, "getaddrinfo", side_effect=boom) as ga, \
                mock.patch.dict(os.environ, {"MESHPOOL_API_KEY": "k", "OM_MODEL_DEFAULT": "meshpool"}):
            for r in (Router(), Router(overrides={"matrix": provider}, chains={"matrix": ["meshpool"]})):
                with self.assertRaises(replay.ReplayMiss) as cm:
                    r.complete_json("matrix", SYS, [Part("an unrecorded prompt")], SCHEMA)
                self.assertEqual(len(cm.exception.key), 64)
            for m in (uo, op, sc, cc, ga, provider.complete_json):
                m.assert_not_called()

    def test_key_is_provider_agnostic_masked_and_sensitive_to_inputs(self):
        k = replay.request_key("extraction", "s", [Part("a")], SCHEMA)
        self.assertEqual(k, replay.request_key("extraction", "s", [Part("a", cache=True)], SCHEMA))   # cache flag is not part of it
        for other in (replay.request_key("reasoning", "s", [Part("a")], SCHEMA), replay.request_key("extraction", "t", [Part("a")], SCHEMA),
                      replay.request_key("extraction", "s", [Part("b")], SCHEMA), replay.request_key("extraction", "s", [Part("a")], {})):
            self.assertNotEqual(k, other)
        # two different emails mask to the same prompt -> same fixture, so fixtures never depend on the PII value
        m1, _ = pii.Masker().mask("hi a@x.com")
        m2, _ = pii.Masker().mask("hi zzz@y.org")
        self.assertEqual(replay.request_key("t", "s", [Part(m1)], SCHEMA), replay.request_key("t", "s", [Part(m2)], SCHEMA))

    def test_record_then_replay_round_trip(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": d}):
            p = FakeProvider(replies=[{"answer": "mail [EMAIL_1]", "n": 7}])
            rec = Router(overrides={"matrix": p}, mode="record")
            a = rec.complete_json("matrix", "s", [Part("write to bob@corp.com")], SCHEMA)
            self.assertEqual(a.data["answer"], "mail bob@corp.com")
            files = list(Path(d).glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertNotIn("bob@corp.com", files[0].read_text())
            b = Router(mode="replay").complete_json("matrix", "s", [Part("write to bob@corp.com")], SCHEMA)
            self.assertEqual(b.data, a.data)
            self.assertEqual(len(p.calls), 1)

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            replay.mode("bogus")


class MeterTests(unittest.TestCase):
    def test_sums_per_job_with_price_table_and_default(self):
        m = Meter(prices={"cheap": (1.0, 2.0), "cheap-plus": (10.0, 20.0)}, default=(5.0, 5.0))
        self.assertEqual(m.price("x:cheap-plus-1"), (10.0, 20.0))        # longest match wins
        m.record("j1", "x:cheap", {"input_tokens": 1_000_000, "output_tokens": 500_000})
        m.record("j1", "x:unknown", {"input_tokens": 200_000, "output_tokens": 0, "cache_read_input_tokens": 50})
        m.record("j2", "x:cheap", {"input_tokens": 10, "output_tokens": None})
        t = m.totals("j1")
        self.assertEqual((t["input_tokens"], t["output_tokens"], t["calls"], t["cache_read_tokens"]), (1_200_000, 500_000, 2, 50))
        self.assertAlmostEqual(t["cost_usd"], 1.0 + 1.0 + 1.0)
        self.assertEqual(m.totals("j2")["input_tokens"], 10)
        self.assertEqual(m.totals("nope")["calls"], 0)

    def test_thread_safe(self):
        m = Meter()
        ts = [threading.Thread(target=lambda: [m.record("j", "claude-sonnet-x", {"input_tokens": 1, "output_tokens": 1}) for _ in range(500)])
              for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(m.totals("j")["calls"], 4000)
        self.assertEqual(m.totals("j")["input_tokens"], 4000)

    def test_router_meters_by_job_id(self):
        p = FakeProvider("deepseek", "deepseek-chat", usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000})
        r = router(overrides={"matrix": p, "ask": p})
        r.complete_json("matrix", "s", [Part("q")], SCHEMA, job_id="A")
        r.complete_task("reasoning", "s", [Part("q")], SCHEMA, job_id="A")
        r.complete_json("matrix", "s", [Part("q")], SCHEMA, job_id="B")
        self.assertEqual(r.meter.totals("A")["calls"], 2)
        self.assertAlmostEqual(r.meter.totals("A")["cost_usd"], 2 * (0.27 + 1.10))
        self.assertAlmostEqual(r.meter.totals("B")["cost_usd"], 0.27 + 1.10)
        self.assertNotIn("job_id", p.calls[0]["kw"])                     # router-only kwargs never reach providers

class HermeticTests(unittest.TestCase):
    """An explicit chain / override is exact: env provider keys must never add a real provider or open a socket."""
    ENV = {"MESHPOOL_API_KEY": "k\u2014ey", "ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y", "OM_MODEL_ASK": "meshpool:auto"}

    def _no_net(self):
        return mock.patch.object(socket, "socket", side_effect=AssertionError("socket opened"))

    def test_explicit_chain_is_exclusive(self):
        a, b = FakeProvider("a", replies=[TransportError("boom")]), FakeProvider("b")
        with mock.patch.dict(os.environ, self.ENV), self._no_net():
            r = router(chains={"ask": [a, b]})
            self.assertEqual(r.providers("ask"), [a, b])
            res = r.complete_json("ask", SYS, EXTRACT_PARTS, SCHEMA)
        self.assertEqual(res.data["answer"], "ok")
        self.assertEqual(len(b.calls), 1)

    def test_override_is_exclusive(self):
        a = FakeProvider("a")
        with mock.patch.dict(os.environ, self.ENV), self._no_net():
            r = router(overrides={"ask": a})
            self.assertEqual(r.providers("ask"), [a])
            r.complete_json("ask", SYS, EXTRACT_PARTS, SCHEMA)
        self.assertEqual(len(a.calls), 1)

    def test_env_primary_kept_without_explicit_chain(self):
        with mock.patch.dict(os.environ, {"MESHPOOL_API_KEY": "key", "OM_MODEL_ASK": "meshpool:auto"}):
            ps = router().providers("ask")
        self.assertEqual([p.name for p in ps], ["meshpool"])

    def test_bad_key_clear_error_without_value(self):
        for bad in ("k\u2014ey", "abc\r\nX-Evil: 1", "tok\nen"):
            with mock.patch.dict(os.environ, {"MESHPOOL_API_KEY": bad}):
                with self.assertRaises(LLMError) as cm:
                    llm.make_provider("meshpool:auto")
            self.assertIn("MESHPOOL_API_KEY", str(cm.exception))
            self.assertNotIn(bad, str(cm.exception))
            self.assertNotIn("Evil", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
