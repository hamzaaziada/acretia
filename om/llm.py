"""Model-agnostic LLM layer with per-stage routing.

Every LLM call in the app goes through `Router.complete_json(stage, ...)`. Which model serves which
stage is configuration, so stages can be tuned independently later (a cheap fast model for bulk
extraction, a stronger one for agentic modelling, …):

  .env (or environment):
    OM_MODEL_DEFAULT=deepseek:deepseek-chat          # fallback for every stage
    OM_MODEL_MATRIX=anthropic:claude-opus-5-5        # per-stage override (MATRIX, SHEETS_AGENT, RERANK, …)
    DEEPSEEK_API_KEY=…  ANTHROPIC_API_KEY=…  OPENAI_API_KEY=…  OPENROUTER_API_KEY=…

  Providers
    anthropic    Claude (SDK-shaped client if injected; else the harness adapter -> Anthropic OpenAI-compatible endpoint)
    deepseek     https://api.deepseek.com            (OpenAI-compatible; JSON mode; automatic prefix caching)
    openai       https://api.openai.com/v1           (JSON-schema structured outputs)
    openrouter   https://openrouter.ai/api/v1        (hundreds of models behind one key)
    groq, together, fireworks, mistral               (OpenAI-compatible)
    ollama       http://localhost:11434/v1           (local models, no key)
    custom       any OpenAI-compatible server: OM_PROVIDER_<NAME>_BASE_URL / _API_KEY_ENV

With no model configured for a stage the caller falls back to its non-LLM path (e.g. the Matrix's
extractive engine). Outputs are validated against the JSON schema on every provider; one repair
retry is made with the validation error. Grounding (quote verification) happens downstream and is
model-independent.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace as _replace
from urllib.parse import urlparse

from . import pii, replay

PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY", "json": "json_object", "default": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "json": "json_schema", "default": "gpt-4.1-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "json": "json_object", "default": "deepseek/deepseek-chat"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "json": "json_object", "default": "llama-3.3-70b-versatile"},
    "together": {"base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY", "json": "json_object", "default": "deepseek-ai/DeepSeek-V3"},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1", "key_env": "FIREWORKS_API_KEY", "json": "json_object", "default": "accounts/fireworks/models/deepseek-v3"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY", "json": "json_object", "default": "gemini-flash-latest"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY", "json": "json_object", "default": "mistral-large-latest"},
    # MeshPool gateway (D-004): the default provider. Its key is bound to MESHPOOL_HOST and never sent anywhere else.
    "meshpool": {"base_url": "https://llm.meshpool.ai/v1", "key_env": "MESHPOOL_API_KEY", "json": "json_object", "default": "auto"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None, "json": "json_object", "default": "qwen2.5:14b"},
}
ANTHROPIC_DEFAULT = "claude-opus-5-5"
MESHPOOL_HOST = "llm.meshpool.ai"
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
KEY_BOUND_HOSTS = {"meshpool": MESHPOOL_HOST, "anthropic": "api.anthropic.com"}     # provider name -> the only host its key may ever reach
AUTO_ORDER = ("meshpool", "anthropic", "deepseek", "openai", "gemini", "openrouter", "together", "groq", "fireworks", "mistral")
VISION = ("anthropic", "openai", "gemini", "openrouter")      # providers whose default models read images


class LLMError(Exception):
    pass


class InvalidJSON(LLMError):
    """The model's reply wasn't parseable JSON (truncated or malformed); worth one retry."""


class LLMRefusal(LLMError):
    pass


class TransportError(LLMError):
    """Network/HTTP failure. `status` is the HTTP status when there was one (None for timeouts / unreachable)."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class SchemaInvalid(LLMError):
    """Reply parsed as JSON but did not match the schema even after the repair retry."""


def fallthrough_ok(e: BaseException) -> bool:
    """True when the next provider in a fallback chain may be tried: transport errors, 429/5xx, timeouts."""
    if isinstance(e, (InvalidJSON, SchemaInvalid)):
        return True
    if isinstance(e, TransportError):
        return e.status is None or e.status == 429 or e.status >= 500
    if isinstance(e, LLMError):
        return False
    if isinstance(e, (TimeoutError, ConnectionError, urllib.error.URLError, OSError)):
        return True
    code = getattr(e, "status_code", None)
    if isinstance(code, int):
        return code == 429 or code >= 500
    return any(w in type(e).__name__ for w in ("Timeout", "Connection"))


@dataclass
class Part:
    text: str
    cache: bool = False          # stable prefix: cache it where the provider supports explicit caching
    image: bytes | None = None   # optional image (vision models only): the text is its caption
    media_type: str = "image/png"


@dataclass
class Result:
    data: dict
    usage: dict = field(default_factory=dict)
    model: str = ""
    repaired: bool = False
    fallbacks: list = field(default_factory=list)   # events (refusal / transport / invalid_json) from providers tried earlier


# --------------------------------------------------------------------------- schema validation (subset)
def validate(data, schema, path="$") -> str | None:
    """Small JSON-schema validator for the subset we emit (type, properties, required, items, enum, anyOf)."""
    if "anyOf" in schema:
        errs = [validate(data, s, path) for s in schema["anyOf"]]
        return None if any(e is None for e in errs) else f"{path}: matches none of anyOf ({errs[0]})"
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}
    if isinstance(t, list):                     # "type": ["number", "null"]
        ok = [x for x in t if isinstance(data, types.get(x, object)) and not (x in ("integer", "number") and isinstance(data, bool))]
        if not ok:
            return f"{path}: expected one of {t}, got {type(data).__name__}"
        t = ok[0]
    elif t and not isinstance(data, types.get(t, object)) or (t in ("integer", "number") and isinstance(data, bool)):
        return f"{path}: expected {t}, got {type(data).__name__}"
    if "enum" in schema and data not in schema["enum"]:
        return f"{path}: {data!r} not in {schema['enum']}"
    if t == "object":
        for k in schema.get("required", []):
            if k not in data:
                return f"{path}: missing required key {k!r}"
        for k, sub in schema.get("properties", {}).items():
            if k in data:
                e = validate(data[k], sub, f"{path}.{k}")
                if e:
                    return e
    if t == "array" and "items" in schema:
        for i, item in enumerate(data):
            e = validate(item, schema["items"], f"{path}[{i}]")
            if e:
                return e
    return None


def _extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


# --------------------------------------------------------------------------- providers
class AnthropicProvider:
    """Claude. With an injected SDK-shaped `client` (tests, or a caller who already holds one) the Messages API is used
    through it (structured outputs, prompt caching, refusal fallback). Without one, calls go through the harness
    adapter to Anthropic's OpenAI-compatible endpoint: no provider SDK is imported anywhere in this module (D-020)."""

    def __init__(self, model: str, client=None, transport=None, api_key: str | None = None):
        self.model = model
        self.client = client
        self._compat = None
        if client is None:
            key = api_key or _env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN")
            if not key:
                raise LLMError("Claude needs ANTHROPIC_API_KEY (Settings)")
            self._compat = OpenAICompatProvider("anthropic", model, ANTHROPIC_BASE_URL, key, "json_object", transport,
                                                key_host=KEY_BOUND_HOSTS["anthropic"])

    def complete_json(self, system: str, parts: list[Part], schema: dict, max_tokens: int = 16000,
                      effort: str = "medium", repair_note: str | None = None) -> Result:
        if self._compat is not None:
            return self._compat.complete_json(system, parts, schema, max_tokens, effort, repair_note)
        import base64
        content = []
        for p in parts:
            if p.image is not None:
                content.append({"type": "image", "source": {"type": "base64", "media_type": p.media_type,
                                                            "data": base64.b64encode(p.image).decode()}})
            if p.text:
                content.append({"type": "text", "text": p.text, **({"cache_control": {"type": "ephemeral"}} if p.cache else {})})
        if repair_note:
            content.append({"type": "text", "text": repair_note})
        resp = self.client.beta.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}])
        u = getattr(resp, "usage", None)
        usage = {k: getattr(u, k, None) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens")} if u else {}
        if resp.stop_reason == "refusal":
            raise LLMRefusal("refused")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise LLMError(f"no text in response (stop_reason={resp.stop_reason})")
        return Result(json.loads(text), usage, f"anthropic:{self.model}")


class OpenAICompatProvider:
    """Any OpenAI-compatible /chat/completions endpoint (DeepSeek, OpenAI, OpenRouter, Groq, local…)."""

    def __init__(self, name: str, model: str, base_url: str, api_key: str | None, json_mode: str = "json_object",
                 transport=None, timeout: int = 300, key_host: str | None = None):
        self.name, self.model, self.base_url, self.key, self.json_mode = name, model, base_url.rstrip("/"), api_key, json_mode
        self.key_host = (key_host or KEY_BOUND_HOSTS.get(name) or "").lower() or None
        if self.key and self.key_host:
            key_host_guard(self.base_url, self.key_host)
        self._injected = transport
        self.transport = transport or self._post
        self.timeout = timeout

    def _adapter(self):
        """The harness adapter that performs the HTTP call (key-host binding, redirect guard, retry/backoff)."""
        from src.harness.adapter import Adapter
        return Adapter(self.base_url, self.key, self.model, key_host=self.key_host, timeout=self.timeout, mode="live",
                       transport=self._injected, max_retries=0 if self._injected else 3, backoff=2.0, mask=False)

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        from src.harness.adapter import urllib_transport
        try:
            return urllib_transport(url, body, headers, timeout=self.timeout,
                                    bound_host=self.key_host or (urlparse(url).hostname or ""), has_key=bool(self.key))
        except TransportError as e:
            raise TransportError(f"{self.name} {e}", e.status)

    def complete_json(self, system: str, parts: list[Part], schema: dict, max_tokens: int = 8000,
                      effort: str = "medium", repair_note: str | None = None) -> Result:
        # Stable content first and identical across calls -> providers with automatic prefix caching
        # (DeepSeek, OpenAI) reuse it. The schema is restated in the prompt for providers with only JSON mode.
        sys_msg = system + "\n\nReturn ONLY a JSON object that conforms to this JSON schema:\n" + json.dumps(schema)
        user = "\n\n".join(p.text for p in parts) + (f"\n\n{repair_note}" if repair_note else "")
        if any(p.image is not None for p in parts):
            import base64
            user = []
            for p in parts:
                if p.image is not None:
                    user.append({"type": "image_url", "image_url": {
                        "url": f"data:{p.media_type};base64,{base64.b64encode(p.image).decode()}"}})
                if p.text:
                    user.append({"type": "text", "text": p.text})
            if repair_note:
                user.append({"type": "text", "text": repair_note})
        body = {"model": self.model, "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}],
                "max_tokens": max_tokens, "temperature": 0}
        if self.json_mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": False}}
        elif self.json_mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        if self.key and self.key_host:
            key_host_guard(self.base_url, self.key_host)       # re-checked at call time: base_url is mutable
        j = self._adapter().request(body)
        choice = (j.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "content_filter":
            raise LLMRefusal("content filter")
        text = (choice.get("message") or {}).get("content") or ""
        u = j.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                 "cache_read_input_tokens": u.get("prompt_cache_hit_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens")}
        try:
            data = _extract_json(text)
        except json.JSONDecodeError as e:
            cut = " (reply was cut off at the token limit)" if choice.get("finish_reason") == "length" else ""
            raise InvalidJSON(f"invalid JSON from {self.name}{cut}: {e}; reply ends …{text[-120:]!r}")
        return Result(data, usage, f"{self.name}:{self.model}")


# --------------------------------------------------------------------------- routing
def _env(k: str) -> str | None:
    v = os.environ.get(k)
    return v.strip() if v and v.strip() else None


def key_host_guard(base_url: str, bound: str | None = None) -> None:
    """A key is only sent to the host it was entered for. `bound` is the exact host (e.g. MeshPool's); without it the
    custom-endpoint binding from OM_PROVIDER_CUSTOM_KEY_HOST applies (see settings.save). Exact hostname match only:
    lookalikes (llm.meshpool.ai.evil.com, llm.meshpool.ai@evil.com, trailing dot) and non-https/odd ports are refused."""
    explicit = bool(bound)
    bound = (bound or _env("OM_PROVIDER_CUSTOM_KEY_HOST") or "").lower()
    u = urlparse(base_url)
    host = (u.hostname or "").lower()
    if bound and host != bound:
        raise LLMError(f"the saved key was entered for {bound}, not {host}; enter it again in Settings to use this endpoint")
    if explicit and (u.scheme != "https" or u.username or u.password or (u.port not in (None, 443))):
        raise LLMError(f"the key for {bound} may only be sent to https://{bound}")
    if u.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise LLMError("refusing to send the key over plain http to a remote host; use https://")


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect to another host while a key is attached (urllib would resend the Authorization header)."""

    def __init__(self, host: str, has_key: bool):
        self.host, self.has_key = (host or "").lower(), has_key

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if self.has_key:
            u = urlparse(newurl)
            if (u.hostname or "").lower() != self.host or u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise LLMError(f"refusing redirect to {u.hostname}: the API key is bound to {self.host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_provider(spec: str, transport=None, anthropic_client=None):
    """spec: 'provider:model' (model optional), e.g. 'deepseek:deepseek-chat', 'anthropic', 'ollama:qwen2.5:14b'."""
    name, _, model = spec.partition(":")
    name = name.strip().lower()
    if name == "anthropic":
        return AnthropicProvider(model or ANTHROPIC_DEFAULT, client=anthropic_client, transport=transport)
    preset = dict(PRESETS.get(name, {}))
    up = name.upper()
    if _env(f"OM_PROVIDER_{up}_BASE_URL"):
        preset["base_url"] = _env(f"OM_PROVIDER_{up}_BASE_URL")
        preset["key_env"] = _env(f"OM_PROVIDER_{up}_API_KEY_ENV") or preset.get("key_env")
        preset.setdefault("json", _env(f"OM_PROVIDER_{up}_JSON") or "json_object")
    if not preset.get("base_url"):
        raise LLMError(f"unknown provider {name!r}; known: anthropic, {', '.join(PRESETS)} (or set OM_PROVIDER_{up}_BASE_URL)")
    key = _env(preset["key_env"]) if preset.get("key_env") else None
    if preset.get("key_env") and not key:
        raise LLMError(f"{name} needs {preset['key_env']} (Settings)")
    if name == "custom" and key:
        key_host_guard(preset["base_url"])
    if name in KEY_BOUND_HOSTS and key:
        key_host_guard(preset["base_url"], KEY_BOUND_HOSTS[name])
    return OpenAICompatProvider(name, model or preset["default"], preset["base_url"], key, preset.get("json", "json_object"), transport,
                                key_host=KEY_BOUND_HOSTS.get(name))


VISION_STAGES = {"slide_review", "slide_build"}


def configured_spec(stage: str) -> str | None:
    """Model spec for a stage: OM_MODEL_<STAGE> > OM_MODEL_DEFAULT > first provider with a key set.
    Vision stages: OM_MODEL_<STAGE> > OM_MODEL_VISION > the default if it can read images > first vision provider with a key."""
    if stage in VISION_STAGES:
        spec = _env(f"OM_MODEL_{stage.upper()}") or _env("OM_MODEL_VISION")
        if spec:
            return spec
        d = _env("OM_MODEL_DEFAULT")
        if d and d.split(":", 1)[0].lower() in VISION:
            return d
        order = [n for n in AUTO_ORDER if n in VISION]
    else:
        spec = _env(f"OM_MODEL_{stage.upper()}") or _env("OM_MODEL_DEFAULT")
        if spec:
            return spec
        order = AUTO_ORDER
    for name in order:
        env = "ANTHROPIC_API_KEY" if name == "anthropic" else PRESETS[name]["key_env"]
        if _env(env) or (name == "anthropic" and _env("ANTHROPIC_AUTH_TOKEN")):
            return name
    return None


# --------------------------------------------------------------------------- task types
TASK_TYPES = ("extraction", "modeling", "reasoning", "vision_critic")
TASK_STAGES = {"extraction": "matrix", "modeling": "sheets_agent", "reasoning": "ask", "vision_critic": "slide_review"}


# --------------------------------------------------------------------------- token and cost meter
# USD per million tokens (input, output); matched by longest substring of the model id. Approximate list prices:
# edit or pass `prices=` to Meter. Unknown models use DEFAULT_PRICE (deliberately on the expensive side).
PRICES = {"claude-opus": (15.0, 75.0), "claude-sonnet": (3.0, 15.0), "claude-haiku": (1.0, 5.0),
          "deepseek": (0.27, 1.10), "gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gemini-flash": (0.30, 2.50),
          "llama": (0.60, 0.60), "mistral-large": (2.0, 6.0), "ollama:": (0.0, 0.0)}
DEFAULT_PRICE = (3.0, 15.0)


class Meter:
    """Thread-safe per-job token and cost accounting."""

    def __init__(self, prices: dict | None = None, default: tuple[float, float] = DEFAULT_PRICE):
        self.prices = dict(PRICES if prices is None else prices)
        self.default = default
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def price(self, model: str) -> tuple[float, float]:
        m = (model or "").lower()
        hits = [k for k in self.prices if k.lower() in m]
        return self.prices[max(hits, key=len)] if hits else self.default

    def record(self, job_id: str | None, model: str, usage: dict | None, replayed: bool = False) -> float:
        u = usage or {}
        tin, tout, tcache = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0), int(u.get("cache_read_input_tokens") or 0)
        pin, pout = self.price(model)
        cost = 0.0 if replayed else (tin * pin + tout * pout) / 1e6
        with self._lock:
            j = self._jobs.setdefault(job_id or "_", {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                                                       "cost_usd": 0.0, "calls": 0, "replayed_calls": 0, "by_model": {}})
            j["input_tokens"] += tin
            j["output_tokens"] += tout
            j["cache_read_tokens"] += tcache
            j["cost_usd"] += cost
            j["calls"] += 1
            j["replayed_calls"] += int(replayed)
            bm = j["by_model"].setdefault(model or "?", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0})
            bm["input_tokens"] += tin
            bm["output_tokens"] += tout
            bm["cost_usd"] += cost
            bm["calls"] += 1
        return cost

    def totals(self, job_id: str | None = None) -> dict:
        with self._lock:
            j = self._jobs.get(job_id or "_")
            if not j:
                return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cost_usd": 0.0, "calls": 0,
                        "replayed_calls": 0, "by_model": {}}
            return json.loads(json.dumps(j))

    def jobs(self) -> dict[str, dict]:
        with self._lock:
            return json.loads(json.dumps(self._jobs))

    def reset(self, job_id: str | None = None) -> None:
        with self._lock:
            self._jobs.pop(job_id or "_", None)


# --------------------------------------------------------------------------- router
def _first_json_note(e) -> str:
    return (f"Your previous reply was not valid JSON ({str(e)[:160]}). Reply again with ONLY one complete JSON object; "
            "keep each text field short so it fits.")


class TaskRouter:
    """A Router bound to one task type: `Router.for_task("extraction").complete_json(system, parts, schema)`."""

    def __init__(self, router: "Router", task_type: str):
        self.router, self.task_type, self.stage = router, task_type, TASK_STAGES[task_type]

    def provider(self):
        return self.router.provider(self.stage, self.task_type)

    def available(self) -> bool:
        return self.router.available(self.stage, self.task_type)

    def describe(self) -> str:
        return self.router.describe(self.stage, self.task_type)

    def complete_json(self, system: str, parts: list[Part], schema: dict, **kw) -> Result:
        return self.router.complete_task(self.task_type, system, parts, schema, **kw)


class Router:
    """Resolves providers per stage / task type and runs schema-validated JSON completions.

    Per call: mask PII -> (replay/record by masked-request hash) -> provider chain (primary then fallbacks; one repair
    retry per provider) -> unmask the returned strings -> meter. `mode` (default ACRETIA_LLM_MODE, else live) is
    replay-only when 'replay': no provider is even constructed, so no network call can happen."""

    def __init__(self, overrides: dict[str, object] | None = None, chains: dict[str, list] | None = None, mode: str | None = None,
                 mask: bool = True, meter: Meter | None = None, person_names: list[str] | tuple[str, ...] = (),
                 fallthrough_on_refusal: bool = False):
        self.overrides = overrides or {}   # stage or task type -> provider instance (tests / programmatic use)
        self.chains = chains or {}         # stage or task type -> ordered fallback specs/provider instances
        self.mode, self.mask, self.person_names = mode, mask, tuple(person_names)
        self.fallthrough_on_refusal = fallthrough_on_refusal
        self.meter = meter if meter is not None else Meter()
        self.events: list[dict] = []
        self._cache: dict[str, object] = {}
        self._maskers: dict[str, pii.Masker] = {}
        self._lock = threading.Lock()

    # -- resolution
    @staticmethod
    def _name(stage: str, task: str | None) -> str:
        return task or stage

    def provider(self, stage: str, task: str | None = None):
        name = self._name(stage, task)
        for k in (name, stage):
            if k in self.overrides:
                return self.overrides[k]
        if name not in self._cache:
            spec = (_env(f"OM_MODEL_{task.upper()}") if task else None) or configured_spec(stage)
            self._cache[name] = make_provider(spec) if spec else None
        return self._cache[name]

    def for_task(self, task_type: str) -> TaskRouter:
        if task_type not in TASK_STAGES:
            raise LLMError(f"unknown task type {task_type!r}; known: {', '.join(TASK_TYPES)}")
        return TaskRouter(self, task_type)

    def available(self, stage: str, task: str | None = None) -> bool:
        try:
            return self.provider(stage, task) is not None
        except LLMError:
            return False

    def describe(self, stage: str, task: str | None = None) -> str:
        try:
            p = self.provider(stage, task)
        except LLMError as e:
            return f"misconfigured: {e}"
        if p is None:
            return "none (non-LLM fallback)"
        return f"{getattr(p, 'name', 'anthropic')}:{p.model}"

    def _event(self, kind: str, label: str, provider, err) -> dict:
        ev = {"kind": kind, "task": label, "provider": f"{getattr(provider, 'name', 'anthropic')}:{getattr(provider, 'model', '?')}",
              "error": f"{type(err).__name__}: {str(err)[:200]}"}
        with self._lock:
            self.events.append(ev)
        return ev

    def providers(self, stage: str, task: str | None = None) -> list:
        """Primary provider followed by the fallback chain (config: chains=, OM_FALLBACK_<NAME>, OM_FALLBACK_DEFAULT)."""
        name = self._name(stage, task)
        entries = self.chains.get(name) or self.chains.get(stage)
        if entries is None:
            raw = _env(f"OM_FALLBACK_{name.upper()}") or _env(f"OM_FALLBACK_{stage.upper()}") or _env("OM_FALLBACK_DEFAULT") or ""
            entries = [x.strip() for x in raw.split(",") if x.strip()]
        out = []
        try:
            primary = self.provider(stage, task)
        except LLMError as e:
            if not entries:
                raise
            primary = None
            self._event("misconfigured", name, None, e)
        if primary is not None:
            out.append(primary)
        for ent in entries:
            try:
                p = make_provider(ent) if isinstance(ent, str) else ent
            except LLMError as e:
                self._event("misconfigured", name, None, e)
                continue
            if not any(p is q or (getattr(p, "name", 0), getattr(p, "model", 0)) == (getattr(q, "name", 1), getattr(q, "model", 1)) for q in out):
                out.append(p)
        return out

    # -- one provider: one repair retry for bad JSON, one for schema mismatch
    def _one(self, p, system, parts, schema, kw) -> Result:
        try:
            res = p.complete_json(system, parts, schema, **kw)
        except InvalidJSON as e:
            kw2 = dict(kw)
            kw2["max_tokens"] = max(int(kw.get("max_tokens") or 8000), 16000)
            res = p.complete_json(system, parts, schema, repair_note=_first_json_note(e), **kw2)
            res.repaired = True
        err = validate(res.data, schema)
        if err:
            note = (f"Your previous reply did not match the required JSON schema ({err}). "
                    "Reply again with ONLY the corrected JSON object.")
            res = p.complete_json(system, parts, schema, repair_note=note, **kw)
            res.repaired = True
            err = validate(res.data, schema)
            if err:
                raise SchemaInvalid(f"schema validation failed after repair: {err}")
        return res

    def _chain(self, providers, system, parts, schema, kw, label) -> Result:
        if not providers:
            raise LLMError(f"no model configured for {label!r}")
        trail, last = [], None
        for p in providers:
            try:
                res = self._one(p, system, parts, schema, kw)
                res.fallbacks = trail
                return res
            except LLMRefusal as e:
                trail.append(self._event("refusal", label, p, e))       # recorded, never silent
                last = e
                if not self.fallthrough_on_refusal:
                    raise
            except Exception as e:
                if not fallthrough_ok(e):
                    raise
                kind = "invalid_json" if isinstance(e, (InvalidJSON, SchemaInvalid)) else "transport"
                trail.append(self._event(kind, label, p, e))
                last = e
        raise last

    def _masker(self, job_id: str | None, names) -> pii.Masker:
        allnames = tuple(self.person_names) + tuple(names or ())
        if job_id is None:
            return pii.Masker(allnames)
        with self._lock:
            m = self._maskers.get(job_id)
            if m is None:
                m = self._maskers[job_id] = pii.Masker(allnames)
            else:
                m.names = sorted(set(m.names) | {n for n in allnames if n}, key=len, reverse=True)
            return m

    def end_job(self, job_id: str) -> None:
        """Forget a job's placeholder table (the meter keeps its totals)."""
        with self._lock:
            self._maskers.pop(job_id, None)

    # -- public API
    def complete_json(self, stage: str, system: str, parts: list[Part], schema: dict, **kw) -> Result:
        return self._complete(stage, None, system, parts, schema, kw)

    def complete_task(self, task_type: str, system: str, parts: list[Part], schema: dict, **kw) -> Result:
        if task_type not in TASK_STAGES:
            raise LLMError(f"unknown task type {task_type!r}; known: {', '.join(TASK_TYPES)}")
        return self._complete(TASK_STAGES[task_type], task_type, system, parts, schema, kw)

    def _complete(self, stage, task, system, parts, schema, kw) -> Result:
        kw = dict(kw)
        job_id = kw.pop("job_id", None)
        names = kw.pop("pii_names", None)
        do_mask = kw.pop("mask", self.mask)
        label = self._name(stage, task)
        mode = replay.mode(self.mode)
        mapping: dict[str, str] = {}
        if do_mask:
            masker = self._masker(job_id, names)
            system = masker.mask(system)[0]
            parts = [_replace(p, text=masker.mask(p.text)[0]) for p in parts]
            mapping = dict(masker.mapping)
        key = replay.request_key(label, system, parts, schema) if mode != "live" else ""
        if mode == "replay":
            rec = replay.load(key, label)              # raises ReplayMiss before any provider is even built
            res = Result(rec["data"], rec.get("usage") or {}, rec.get("model", ""))
            self.meter.record(job_id, res.model, res.usage, replayed=True)
        else:
            res = self._chain(self.providers(stage, task), system, parts, schema, kw, label)
            self.meter.record(job_id, res.model, res.usage)
            if mode == "record":
                replay.save(key, label, res.data, res.usage, res.model)
        if mapping:
            res.data = pii.unmask_obj(res.data, mapping)
        return res


STAGES = {"ask": "Ask research assistant", "matrix": "Matrix cell answers", "sheets_agent": "Sheets agent",
          "storyboard": "Deck Studio: storyboard and slide prompts", "slide_review": "Deck Studio: partner/MD review of slide images (vision)",
          "slide_build": "Deck Studio: rebuild an approved image as an editable slide (vision)",
          "check": "Consistency checks (optional: extra extraction and review)", "rerank": "Search re-ranking (planned)"}
