"""The one model adapter (PLAN S2.1, D-020): an OpenAI-compatible `/chat/completions` client on plain urllib.

Works with anything that speaks that dialect: MeshPool (default), Claude via Anthropic's compatible endpoint, GPT,
Gemini's compatible endpoint, vLLM, Ollama. Provides chat + vision (`data:` image parts), SSE streaming, JSON-schema
validated output with one repair retry, retries with backoff, a fallback chain of further Adapters, reversible PII
masking of every outbound text part, record/replay by masked-prompt hash (zero network in replay), a per-job
token/cost ledger with an atomic reserve -> settle spend guard (every network send, retries and stream starts
included), and an API key bound to its host (explicit `key_host` or a known provider preset, never derived from an
arbitrary base_url).

Streaming contract: if a stream fails before any text reached the consumer, the next adapter in the chain is tried.
If it fails after text was yielded, `StreamInterrupted` is raised carrying the partial text and the usage billed so
far; the job runner decides whether to retry the whole call (the partial text is NOT a complete answer).

This is the only module allowed to talk to a model provider; no provider SDK is imported anywhere (AST-tested).
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
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
# Provider name -> the only host its key may reach. A key whose endpoint is not one of these needs an explicit key_host.
KEY_HOST_PRESETS = {"meshpool": "llm.meshpool.ai", "anthropic": "api.anthropic.com", "openai": "api.openai.com",
                    "gemini": "generativelanguage.googleapis.com",
                    **{n: (urlparse(p["base_url"]).hostname or "") for n, p in _llm.PRESETS.items()
                       if p.get("key_env") and n not in ("meshpool", "openai", "gemini")}}
KNOWN_KEY_HOSTS = frozenset(KEY_HOST_PRESETS.values())
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
USER_AGENT = "Acretia/0.1"
IMAGE_TOKENS = 3000            # flat worst-case input estimate per image part


class StreamInterrupted(LLMError):
    """A stream failed AFTER text had been yielded. `partial_text` is what the consumer already received (unmasked),
    `usage` what was billed for it. Never silently continued on another adapter: the job runner retries the whole call."""
    retryable = True

    def __init__(self, message: str, partial_text: str = "", usage: dict | None = None, model: str = ""):
        super().__init__(message)
        self.partial_text, self.usage, self.model = partial_text, usage or {}, model


_BEARER = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=:-]{4,}")
_AUTH_HDR = re.compile(r"(?i)((?:proxy-)?authorization|x-api-key|api-key)(['\"]?\s*[:=]\s*['\"]?)(?:(?:bearer|basic|token)\s+)?[^\s,'\"}\\]+")


def redact(text, *secrets) -> str:
    """Remove every secret value (plain and repr-escaped), `Bearer ...` tokens and Authorization header values."""
    t = str(text)
    for sec in secrets:
        if sec and len(sec) >= 4:
            for form in {sec, repr(sec)[1:-1], json.dumps(sec)[1:-1]}:
                t = t.replace(form, "[REDACTED]")
    t = _AUTH_HDR.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", t)
    return _BEARER.sub(lambda m: m.group(1) + " [REDACTED]", t)


def _key_of(headers: dict) -> str:
    v = headers.get("Authorization", "") or ""
    return v.split(None, 1)[1] if v.lower().startswith("bearer ") and len(v.split(None, 1)) == 2 else v


@dataclass
class AdapterResult:
    text: str
    data: object = None                 # parsed JSON when json_schema was given
    usage: dict = field(default_factory=dict)
    model: str = ""
    cost_usd: float = 0.0
    replayed: bool = False
    fallbacks: list = field(default_factory=list)   # events from adapters tried earlier in the chain
    tool_calls: list = field(default_factory=list)  # OpenAI-style tool_calls with arguments unmasked


def image_part(image: bytes, media_type: str = "image/png") -> dict:
    """OpenAI vision content part carrying the image inline as a base64 data URL."""
    return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64.b64encode(image).decode()}"}}


# --------------------------------------------------------------------------- default HTTP transport
def urllib_transport(url: str, body: dict, headers: dict, *, timeout: float = 60, bound_host: str | None = None,
                     has_key: bool = False, stream: bool = False):
    """POST JSON. Returns the parsed reply, or (stream=True) an iterator of decoded SSE lines. A redirect to another
    host is refused while a key is attached. HTTP/network errors become TransportError (status set for HTTP)."""
    for hk, hv in headers.items():
        _llm.check_header_value(hk, hv)
    secret = _key_of(headers)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    opener = urllib.request.build_opener(_llm._SameHostRedirect(bound_host or (urlparse(url).hostname or ""), has_key))
    try:
        r = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_txt = redact(e.read(20000).decode("utf-8", "replace"), secret)      # redact BEFORE truncating
        raise TransportError(f"HTTP {e.code} from {urlparse(url).hostname}: {body_txt[:300]!r}", e.code) from None
    except LLMError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise TransportError(f"unreachable {urlparse(url).hostname}: {redact(e, secret)}") from None
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

    def close(self) -> None:
        """Abandon the stream: bills the tokens received so far (or the worst case if none), never $0."""
        self._gen.close()


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
        self.key_host = (key_host or "").lower() or None
        if self.api_key and not self.key_host:
            host = (urlparse(self.base_url).hostname or "").lower()
            if host in KNOWN_KEY_HOSTS or (host and host == (os.environ.get("OM_PROVIDER_CUSTOM_KEY_HOST") or "").strip().lower()):
                self.key_host = host
            else:
                raise LLMError(f"an API key was given for {host or self.base_url!r}, which is not a known provider host and "
                               f"has no key_host: pass key_host=... (or set ACRETIA_LLM_KEY_HOST) naming the one host the "
                               f"key may be sent to; known hosts: {', '.join(sorted(KNOWN_KEY_HOSTS))}")
        self._maskers: dict[str, pii.Masker] = {}
        self._lock = threading.Lock()
        self._check_endpoint()

    @classmethod
    def from_env(cls, prefix: str = "ACRETIA_LLM_", **kw) -> "Adapter":
        env = lambda k: (os.environ.get(prefix + k) or "").strip() or None      # noqa: E731
        base, key = env("BASE_URL") or DEFAULT_BASE_URL, env("API_KEY")
        if key and "key_host" not in kw:
            kw["key_host"] = env("KEY_HOST") or {h: h for h in KNOWN_KEY_HOSTS}.get((urlparse(base).hostname or "").lower())
        return cls(base, key, env("MODEL") or "auto", **kw)

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
        return self._request(body, stream=stream, retries=retries)[0]

    def _request(self, body: dict, *, stream: bool = False, retries: int | None = None, reserve=None):
        """As `request`, but `reserve()` (if given) is called before EVERY network attempt (first try, each retry);
        a failed attempt releases its reservation. Returns (reply, reservation); the caller settles or releases."""
        self._check_endpoint()            # base_url is mutable: re-checked on every call
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if stream:
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            _llm.check_header_value("Authorization", f"Bearer {self.api_key}", "api key")
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempts = (self.max_retries if retries is None else retries) + 1
        for n in range(attempts):
            res = reserve() if reserve is not None else None        # BudgetExceeded here: nothing is sent
            err = None
            try:
                if self.transport is not None:
                    out = self.transport(url, body, headers, stream=True) if stream else self.transport(url, body, headers)
                else:
                    out = urllib_transport(url, body, headers, timeout=self.timeout, bound_host=self.key_host,
                                           has_key=bool(self.api_key), stream=stream)
                return out, res
            except BaseException as e:      # noqa: BLE001 - classified below
                if res is not None:
                    self.ledger.release(res)
                err = e
                retry = isinstance(e, Exception) and _retryable(e) and n < attempts - 1
                if not retry:
                    clean = self._clean_error(e)
                    if clean is e:
                        raise
            # raised outside the except block: a sanitised error carries no __context__ holding the raw message
            if not retry:
                raise clean
            self._sleep(min(self.backoff * 2 ** n, 30))
        raise TransportError("retries exhausted")

    def _clean_error(self, e: BaseException) -> BaseException:
        """`e` itself when it holds no secret; else a same-kind error with the key and Authorization data redacted."""
        if not isinstance(e, Exception) or not self.api_key:
            return e
        msg = str(e)
        red = redact(msg, self.api_key)
        if red == msg and self.api_key not in repr(e.args):
            return e
        if isinstance(e, TransportError):
            return TransportError(red, e.status)
        if isinstance(e, LLMError):
            return type(e)(red) if type(e).__init__ is Exception.__init__ else LLMError(red)
        return TransportError(red) if _retryable(e) else LLMError(red)

    # ----------------------------------------------------------------- masking
    def _masker(self, job_id: str | None) -> pii.Masker:
        if job_id is None:
            return pii.Masker(self.masker_names)
        with self._lock:
            return self._maskers.setdefault(job_id, pii.Masker(self.masker_names))

    def _mask_messages(self, messages: list[dict], masker: pii.Masker | None) -> list[dict]:
        """Mask EVERY outbound string field: str / list content parts (text, input_text, tool_result ...), tool
        messages, tool_calls[].function.arguments, name fields. Structural keys and data: URLs are kept."""
        return [{**m} if masker is None else masker.mask_obj(m) for m in messages]

    def _unmask_tool_calls(self, calls, masker) -> list:
        out = []
        for c in calls or []:
            c = json.loads(json.dumps(c))
            fn = c.get("function") or {}
            args = fn.get("arguments")
            if masker is not None and isinstance(args, str):
                try:
                    fn["arguments"] = json.dumps(pii.unmask_obj(json.loads(args), masker.mapping), ensure_ascii=False)
                except ValueError:
                    fn["arguments"] = masker.unmask(args)
            elif masker is not None and isinstance(args, dict):
                fn["arguments"] = pii.unmask_obj(args, masker.mapping)
            if masker is not None and isinstance(fn.get("name"), str):
                fn["name"] = masker.unmask(fn["name"])
            out.append(c)
        return out

    @staticmethod
    def _estimate_input_tokens(messages: list[dict]) -> int:
        n = 0

        def walk(o):
            nonlocal n
            if isinstance(o, dict):
                if o.get("type") == "image_url":
                    n += IMAGE_TOKENS
                    return
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, str):
                n += len(o) // 3 + 1
        for m in messages:
            n += 4
            walk(m)
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
            extra = {k: v for k, v in m.items() if k not in ("role", "content")}
            if extra:                       # tool_calls / name / tool_call_id change the request, so they change the key
                parts.append(SimpleNamespace(text=f"{m['role']}:meta:" + json.dumps(extra, sort_keys=True), image=None))
        task = f"adapter:{self.model}"
        return replay.request_key(task, "", parts, schema or {}), task

    # ----------------------------------------------------------------- spend: reserve -> settle
    def _reserver(self, masked_msgs: list[dict], max_tokens: int, job_id):
        """A callable that reserves the worst case of ONE network send, or None without a ledger."""
        if self.ledger is None:
            return None
        worst = self.ledger.worst_case(self.model, self._estimate_input_tokens(masked_msgs), max_tokens) \
            if hasattr(self.ledger, "worst_case") else None
        if worst is None:
            from .ledger import cost_usd as _c
            worst = _c(self.model, self._estimate_input_tokens(masked_msgs), max_tokens)
        return lambda: self.ledger.reserve(job_id, self.model, worst)

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

    def _settle(self, res, usage: dict, masked: list[dict], text: str, note: str = "") -> float:
        i = usage.get("input_tokens")
        o = usage.get("output_tokens")
        i = self._estimate_input_tokens(masked) if i is None else i
        o = len(text) // 3 if o is None else o
        cached = usage.get("cache_read_input_tokens") or 0
        if res is not None:
            return self.ledger.settle(res, {"input_tokens": i, "output_tokens": o, "cached_tokens": cached}, note)["cost_usd"]
        return cost_usd(self.model, i, o, cached)

    def _fixture_text(self, text: str, masker) -> str:
        """The reply as it may be written to a fixture: scanned for PII; found PII is masked (the mapping stays in the
        job's masker) or, with masking off, the save is refused. Never raw PII on disk."""
        if not replay.find_pii(text):
            return text
        if masker is None:
            raise replay.FixturePII("the reply contains PII and masking is off (mask=False): refusing to record a fixture")
        return masker.mask(text)[0]

    def _chat_one(self, masked, masker, schema, temperature, max_tokens, job_id) -> AdapterResult:
        mode = replay.mode(self.mode)
        key = task = None
        if mode != "live":
            key, task = self._key(masked, schema)
        if mode == "replay":                                   # zero network: a miss raises before any socket exists
            doc = replay.load(key, task)
            text = (doc.get("data") or {}).get("text", "")
            return self._finish(text, masker, schema, doc.get("usage") or {}, doc.get("model") or self.model, 0.0, True)
        body = self._body(masked, schema, temperature, max_tokens)
        j, res = self._request(body, reserve=self._reserver(masked, max_tokens, job_id))
        text, usage, cost, calls = self._read(j, masked, res)
        if schema is not None:
            err = self._schema_error(text, masker, schema)
            if err:                                            # one repair retry with the error, then fall through
                repair = body["messages"] + [{"role": "assistant", "content": text}, {"role": "user", "content":
                         f"Your previous reply was rejected: {err}. Reply again with ONLY a JSON object that conforms to the schema."}]
                j, res = self._request({**body, "messages": repair}, reserve=self._reserver(repair, max_tokens, job_id))
                text, u2, c2, calls = self._read(j, masked, res)
                usage = {k: (usage.get(k) or 0) + (u2.get(k) or 0) for k in usage}
                cost += c2
        out = self._finish(text, masker, schema, usage, self.model, cost, False)
        out.tool_calls = self._unmask_tool_calls(calls, masker)
        if mode == "record":                                   # only valid replies are recorded, scanned for PII first
            replay.save(key, task, {"text": self._fixture_text(text, masker)}, usage, self.model)
        return out

    def _read(self, j: dict, masked, res):
        """Parse a reply and settle its reservation (a content-filtered reply was still billed)."""
        choice = (j.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        usage = self._usage(j)
        cost = self._settle(res, usage, masked, text)
        if choice.get("finish_reason") == "content_filter":
            raise LLMRefusal("content filter")
        return text, usage, cost, msg.get("tool_calls") or []

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
                raise InvalidJSON(f"invalid JSON from {model}: {e}; reply ends ...{redact(text[-120:], self.api_key)!r}")
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
            state: dict = {}
            gen = ad._stream_one(use_masked, use_masker, temperature, max_tokens, job_id, state)
            yielded: list[str] = []
            try:
                while True:
                    try:
                        delta = next(gen)
                    except StopIteration as stop:
                        stop.value.fallbacks = events
                        return stop.value
                    yielded.append(delta)
                    yield delta
            except GeneratorExit:
                gen.close()                       # abandoned by the consumer: the inner finally bills what arrived
                raise
            except BaseException as e:      # noqa: BLE001
                if yielded and isinstance(e, Exception):
                    raise StreamInterrupted(
                        f"stream from {ad.model} failed after {len(''.join(yielded))} chars were delivered "
                        f"({type(e).__name__}: {redact(e, ad.api_key)[:160]}); retry the whole call",
                        "".join(yielded), state.get("usage"), ad.model) from None
                if yielded or not isinstance(e, Exception) or not _llm.fallthrough_ok(e) or idx == len(chain) - 1:
                    raise
                events.append({"kind": type(e).__name__, "model": ad.model, "error": str(e)[:200]})

    def _stream_one(self, masked, masker, temperature, max_tokens, job_id, state: dict | None = None):
        state = state if state is not None else {}
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
        lines, res = self._request(self._body(masked, None, temperature, max_tokens, stream=True), stream=True,
                                   reserve=self._reserver(masked, max_tokens, job_id))
        raw_all, pending, usage, settled = [], "", {}, False
        try:
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
            cost = self._settle(res, usage, masked, masked_text)
            settled = True
            state["usage"] = usage
            if mode == "record":
                replay.save(key, task, {"text": self._fixture_text(masked_text, masker)}, usage, self.model)
            return AdapterResult(masker.unmask(masked_text) if masker else masked_text, None, usage, self.model, cost, False)
        finally:
            if not settled:      # aborted, abandoned or failed mid-stream: bill the tokens received, else the worst case
                got = "".join(raw_all)
                if usage.get("output_tokens") is not None or usage.get("input_tokens") is not None:
                    billed = usage
                elif got:
                    billed = {"input_tokens": self._estimate_input_tokens(masked), "output_tokens": max(1, len(got) // 3)}
                else:
                    billed = None
                state["usage"] = billed or {}
                if res is not None:
                    self.ledger.settle(res, None if billed is None else
                                       {"input_tokens": billed.get("input_tokens"), "output_tokens": billed.get("output_tokens"),
                                        "cached_tokens": billed.get("cache_read_input_tokens") or 0}, "stream aborted")
            close = getattr(lines, "close", None)
            if close:
                with contextlib.suppress(Exception):
                    close()
