"""The one model adapter (PLAN S2.1, D-020): an OpenAI-compatible `/chat/completions` client on plain urllib.

Works with anything that speaks that dialect: MeshPool (default), Claude via Anthropic's compatible endpoint, GPT,
Gemini's compatible endpoint, vLLM, Ollama. Provides chat + vision (`data:` image parts), SSE streaming, JSON-schema
validated output with one repair retry, retries with backoff, a fallback chain of further Adapters, reversible PII
masking of every outbound text part, record/replay by masked-prompt hash (zero network in replay), a per-job
token/cost ledger with a pre-call spend guard, and an API key bound to its host.

This is the only module allowed to talk to a model provider; no provider SDK is imported anywhere (AST-tested).
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import urlparse

from om import llm as _llm
from om import pii, replay
from om.llm import InvalidJSON, LLMError, LLMRefusal, SchemaInvalid, TransportError, validate

from .ledger import BudgetExceeded, Ledger, cost_usd  # noqa: F401  (re-exported)

DEFAULT_BASE_URL = "https://llm.meshpool.ai/v1"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
USER_AGENT = "Acretia/0.1"
IMAGE_TOKENS = 3000            # flat worst-case input estimate per image part


@dataclass
class AdapterResult:
    text: str
    data: object = None                 # parsed JSON when json_schema was given
    usage: dict = field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    replayed: bool = False
    fallbacks: list = field(default_factory=list)   # events from adapters tried earlier in the chain


def image_part(image: bytes, media_type: str = "image/png") -> dict:
    """OpenAI vision content part carrying the image inline as a base64 data URL."""
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(image).decode()}"}}


# --------------------------------------------------------------------------- default HTTP transport
def urllib_transport(url: str, body: dict, headers: dict, *, timeout: float = 60, bound_host: str | None = None,
                     has_key: bool = False, stream: bool = False):
    """POST JSON. Returns the parsed reply, or (stream=True) an iterator of decoded SSE lines. A redirect to another
    host is refused while a key is attached. HTTP/network errors become TransportError (status set for HTTP)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    opener = urllib.request.build_opener(_llm._SameHostRedirect(bound_host or (urlparse(url).hostname or ""), has_key))
    try:
        r = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise TransportError(f"HTTP {e.code} from {urlparse(url).hostname}: {e.read()[:300]!r}", e.code)
    except LLMError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise TransportError(f"unreachable {urlparse(url).hostname}: {e}")
    if not stream:
        with r:
            return json.loads(r.read())

    def lines():
        with r:
            for raw in r:
                yield raw.decode("utf-8", "replace")
    return lines()


def _retryable(e: BaseException) -> bool:
    if isinstance(e, TransportError):
        return e.status is None or e.status == 429 or e.status >= 500
    return isinstance(e, (TimeoutError, ConnectionError, urllib.error.URLError)) and not isinstance(e, urllib.error.HTTPError)


def parse_sse(lines):
    """Yield the JSON event of each `data:` line of a server-sent-events stream; stops at `data: [DONE]`."""
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def _held_back(buf: str) -> int:
    """Index from which `buf` might end in a half-received placeholder like '[EMAIL_' (kept until it completes)."""
    i = buf.rfind("[")
    return i if i >= 0 and "]" not in buf[i:] and len(buf) - i < 24 else len(buf)


class ChatStream:
    """Iterate to receive unmasked text deltas; `.result` (an AdapterResult) is set once the stream is exhausted."""

    def __init__(self, gen):
        self._gen, self.result = gen, None

    def __iter__(self):
        res = yield from self._gen
        self.result = res

    def text(self) -> str:
        return "".join(self)


class Adapter:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None, model_name: str = "auto", *,
                 key_host: str | None = None, timeout: float = 60, transport=None, mode: str | None = None,
                 masker_names=(), ledger: Ledger | None = None, max_retries: int = 2, fallbacks=(),
                 json_mode: str = "json_schema", sleep=time.sleep, backoff: float = 0.5, mask: bool = True):
        """transport(url, body, headers) -> parsed reply dict; with stream=True -> iterable of SSE lines."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        self.model = model_name
        self.timeout, self.transport, self.mode = timeout, transport, mode
        self.masker_names, self.ledger, self.max_retries = tuple(masker_names), ledger, max_retries
        self.fallbacks = list(fallbacks)
        self.json_mode, self._sleep, self.backoff, self.mask = json_mode, sleep, backoff, mask
        self.key_host = (key_host or (urlparse(self.base_url).hostname or "") if self.api_key else key_host or "").lower() or None
        self._maskers: dict[str, pii.Masker] = {}
        self._lock = threading.Lock()
        self._check_endpoint()

    @classmethod
    def from_env(cls, prefix: str = "ACRETIA_LLM_", **kw) -> "Adapter":
        env = lambda k: (os.environ.get(prefix + k) or "").strip() or None      # noqa: E731
        return cls(env("BASE_URL") or DEFAULT_BASE_URL, env("API_KEY"), env("MODEL") or "auto", **kw)

    # ----------------------------------------------------------------- endpoint / key binding
    def _check_endpoint(self) -> None:
        u = urlparse(self.base_url)
        host = (u.hostname or "").lower()
        if u.scheme not in ("http", "https") or not host:
            raise LLMError(f"bad base_url {self.base_url!r}")
        if self.api_key:
            # exact host, https, port 443, no userinfo (also refuses plain http to localhost: no key over http)
            _llm.key_host_guard(self.base_url, self.key_host)
        elif u.scheme == "http" and host not in LOCAL_HOSTS:
            raise LLMError("plain http is only allowed for localhost / 127.0.0.1 (use https://)")
        elif u.username or u.password:
            raise LLMError("credentials in the URL are not allowed")

    # ----------------------------------------------------------------- low-level request (also used by om/llm.py)
    def request(self, body: dict, *, stream: bool = False, retries: int | None = None):
        """Send one chat-completions body with the key guard at call time and retry/backoff; returns the reply dict
        (or the SSE line iterator). No masking, replay or ledger here."""
        self._check_endpoint()            # base_url is mutable: re-checked on every call
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if stream:
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempts = (self.max_retries if retries is None else retries) + 1
        for n in range(attempts):
            try:
                if self.transport is not None:
                    return self.transport(url, body, headers, stream=True) if stream else self.transport(url, body, headers)
                return urllib_transport(url, body, headers, timeout=self.timeout, bound_host=self.key_host,
                                        has_key=bool(self.api_key), stream=stream)
            except BaseException as e:      # noqa: BLE001 - classified below
                if not isinstance(e, Exception) or not _retryable(e) or n == attempts - 1:
                    raise
                self._sleep(min(self.backoff * 2 ** n, 30))
        raise TransportError("retries exhausted")

    # ----------------------------------------------------------------- masking
    def _masker(self, job_id: str | None) -> pii.Masker:
        if job_id is None:
            return pii.Masker(self.masker_names)
        with self._lock:
            return self._maskers.setdefault(job_id, pii.Masker(self.masker_names))

    def _mask_messages(self, messages: list[dict], masker: pii.Masker | None) -> list[dict]:
        out = []
        for m in messages:
            c = m.get("content")
            if masker is None:
                out.append({**m})
            elif isinstance(c, str):
                out.append({**m, "content": masker.mask(c)[0]})
            elif isinstance(c, list):
                out.append({**m, "content": [({**p, "text": masker.mask(p.get("text", ""))[0]} if p.get("type") == "text" else p)
                                             for p in c]})
            else:
                out.append({**m})
        return out

    @staticmethod
    def _estimate_input_tokens(messages: list[dict]) -> int:
        n = 0
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                n += len(c) // 3 + 4
            elif isinstance(c, list):
                for p in c:
                    n += IMAGE_TOKENS if p.get("type") == "image_url" else len(p.get("text", "")) // 3 + 4
        return n

    # ----------------------------------------------------------------- replay key
    def _key(self, messages: list[dict], schema: dict | None) -> tuple[str, str]:
        parts = []
        for m in messages:
            c = m.get("content")
            for p in ([{"type": "text", "text": c}] if isinstance(c, str) else c or []):
                if p.get("type") == "image_url":
                    parts.append(SimpleNamespace(text=f"{m['role']}:", image=p["image_url"]["url"].encode()))
                else:
                    parts.append(SimpleNamespace(text=f"{m['role']}:{p.get('text', '')}", image=None))
        task = f"adapter:{self.model}"
        return replay.request_key(task, "", parts, schema or {}), task

    # ----------------------------------------------------------------- chat
    def chat(self, messages: list[dict], *, json_schema: dict | None = None, temperature: float = 0,
             max_tokens: int = 4096, job_id: str | None = None, stream: bool = False):
        """messages: OpenAI-style [{"role","content"}], content a string or a list of parts (text / image_url).
        Returns an AdapterResult, or with stream=True a ChatStream yielding text deltas."""
        if stream and json_schema is not None:
            raise ValueError("json_schema is not supported together with stream=True")
        masker = self._masker(job_id) if self.mask else None
        masked = self._mask_messages(messages, masker)
        if stream:
            return ChatStream(self._stream(messages, masked, masker, temperature, max_tokens, job_id))
        events: list = []
        for ad in [self, *self.fallbacks]:
            try:
                res = (ad._chat_one(masked, masker, json_schema, temperature, max_tokens, job_id) if ad is self
                       else ad.chat(messages, json_schema=json_schema, temperature=temperature, max_tokens=max_tokens, job_id=job_id))
                res.fallbacks = events + res.fallbacks
                return res
            except BaseException as e:      # noqa: BLE001
                if not isinstance(e, Exception) or not _llm.fallthrough_ok(e) or ad is ([self, *self.fallbacks][-1]):
                    raise
                events.append({"kind": type(e).__name__, "model": ad.model, "error": str(e)[:200]})
        raise LLMError("no adapter in the chain")        # unreachable

    def _body(self, masked: list[dict], schema: dict | None, temperature: float, max_tokens: int, stream: bool = False) -> dict:
        msgs = masked
        body: dict = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
        if schema is not None:
            note = "Return ONLY a JSON object that conforms to this JSON schema:\n" + json.dumps(schema)
            if msgs and msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
                msgs = [{**msgs[0], "content": msgs[0]["content"] + "\n\n" + note}, *msgs[1:]]
            else:
                msgs = [{"role": "system", "content": note}, *msgs]
            body["messages"] = msgs
            if self.json_mode == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": False}}
            elif self.json_mode == "json_object":
                body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _usage(j: dict) -> dict:
        u = j.get("usage") or {}
        return {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                "cache_read_input_tokens": u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens")}

    def _account(self, job_id, usage: dict, masked: list[dict], text: str) -> float:
        i = usage.get("input_tokens")
        o = usage.get("output_tokens")
        i = self._estimate_input_tokens(masked) if i is None else i
        o = len(text) // 3 if o is None else o
        cached = usage.get("cache_read_input_tokens") or 0
        if self.ledger is not None:
            return self.ledger.record(job_id, self.model, i, o, cached)["cost_usd"]
        return cost_usd(self.model, i, o, cached)

    def _chat_one(self, masked, masker, schema, temperature, max_tokens, job_id) -> AdapterResult:
        mode = replay.mode(self.mode)
        key = task = None
        if mode != "live":
            key, task = self._key(masked, schema)
        if mode == "replay":                                   # zero network: a miss raises before any socket exists
            doc = replay.load(key, task)
            text = (doc.get("data") or {}).get("text", "")
            return self._finish(text, masker, schema, doc.get("usage") or {}, doc.get("model") or self.model, 0.0, True)
        if self.ledger is not None:
            self.ledger.precheck(job_id, self.model, self._estimate_input_tokens(masked), max_tokens)
        body = self._body(masked, schema, temperature, max_tokens)
        j = self.request(body)
        text, usage, cost = self._read(j, masked, job_id)
        if schema is not None:
            err = self._schema_error(text, masker, schema)
            if err:                                            # one repair retry with the error, then fall through
                repair = body["messages"] + [{"role": "assistant", "content": text}, {"role": "user", "content":
                         f"Your previous reply was rejected: {err}. Reply again with ONLY a JSON object that conforms to the schema."}]
                if self.ledger is not None:
                    self.ledger.precheck(job_id, self.model, self._estimate_input_tokens(repair), max_tokens)
                j = self.request({**body, "messages": repair})
                text, u2, c2 = self._read(j, masked, job_id)
                usage = {k: (usage.get(k) or 0) + (u2.get(k) or 0) for k in usage}
                cost += c2
        res = self._finish(text, masker, schema, usage, self.model, cost, False)
        if mode == "record":                                   # only valid replies are recorded; masked text: no PII
            replay.save(key, task, {"text": text}, usage, self.model)
        return res

    def _read(self, j: dict, masked, job_id):
        choice = (j.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise LLMRefusal("content filter")
        text = (choice.get("message") or {}).get("content") or ""
        usage = self._usage(j)
        return text, usage, self._account(job_id, usage, masked, text)

    @staticmethod
    def _parse(text: str, masker):
        data = _llm._extract_json(text)
        return pii.unmask_obj(data, masker.mapping) if masker else data

    def _schema_error(self, text: str, masker, schema) -> str | None:
        try:
            data = self._parse(text, masker)
        except (json.JSONDecodeError, IndexError) as e:
            return f"not valid JSON ({e})"
        return validate(data, schema)

    def _finish(self, text, masker, schema, usage, model, cost, replayed) -> AdapterResult:
        data = None
        if schema is not None:
            try:
                data = self._parse(text, masker)
            except (json.JSONDecodeError, IndexError) as e:
                raise InvalidJSON(f"invalid JSON from {model}: {e}; reply ends ...{text[-120:]!r}")
            err = validate(data, schema)
            if err:
                raise SchemaInvalid(f"{model}: {err}")
        return AdapterResult(masker.unmask(text) if masker else text, data, usage, model, cost, replayed)

    # ----------------------------------------------------------------- streaming
    def _stream(self, original, masked, masker, temperature, max_tokens, job_id):
        chain = [self, *self.fallbacks]
        events: list = []
        for idx, ad in enumerate(chain):
            use_masked, use_masker = (masked, masker) if ad is self else (None, None)
            if ad is not self:
                use_masker = ad._masker(job_id) if ad.mask else None
                use_masked = ad._mask_messages(original, use_masker)
            gen = ad._stream_one(use_masked, use_masker, temperature, max_tokens, job_id)
            started = False
            try:
                while True:
                    try:
                        delta = next(gen)
                    except StopIteration as stop:
                        stop.value.fallbacks = events
                        return stop.value
                    started = True
                    yield delta
            except BaseException as e:      # noqa: BLE001
                if started or not isinstance(e, Exception) or not _llm.fallthrough_ok(e) or idx == len(chain) - 1:
                    raise
                events.append({"kind": type(e).__name__, "model": ad.model, "error": str(e)[:200]})

    def _stream_one(self, masked, masker, temperature, max_tokens, job_id):
        mode = replay.mode(self.mode)
        key = task = None
        if mode != "live":
            key, task = self._key(masked, {"stream": True})
        if mode == "replay":
            doc = replay.load(key, task)
            text = masker.unmask((doc.get("data") or {}).get("text", "")) if masker else (doc.get("data") or {}).get("text", "")
            if text:
                yield text
            return AdapterResult(text, None, doc.get("usage") or {}, doc.get("model") or self.model, 0.0, True)
        if self.ledger is not None:
            self.ledger.precheck(job_id, self.model, self._estimate_input_tokens(masked), max_tokens)
        lines = self.request(self._body(masked, None, temperature, max_tokens, stream=True), stream=True)
        raw_all, pending, usage = [], "", {}
        for ev in parse_sse(lines):
            if ev.get("usage"):
                usage = self._usage(ev)
            choice = (ev.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "content_filter":
                raise LLMRefusal("content filter")
            delta = (choice.get("delta") or {}).get("content") or ""
            if not delta:
                continue
            raw_all.append(delta)
            pending += delta
            cut = _held_back(pending)
            if cut:
                chunk, pending = pending[:cut], pending[cut:]
                yield masker.unmask(chunk) if masker else chunk
        if pending:
            yield masker.unmask(pending) if masker else pending
        masked_text = "".join(raw_all)
        cost = self._account(job_id, usage, masked, masked_text)
        if mode == "record":
            replay.save(key, task, {"text": masked_text}, usage, self.model)
        return AdapterResult(masker.unmask(masked_text) if masker else masked_text, None, usage, self.model, cost, False)
