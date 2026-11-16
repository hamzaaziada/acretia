"""Model-agnostic LLM layer with per-stage routing.

Every LLM call in the app goes through `Router.complete_json(stage, ...)`. Which model serves which
stage is configuration, so stages can be tuned independently later (a cheap fast model for bulk
extraction, a stronger one for agentic modelling, …):

  .env (or environment):
    OM_MODEL_DEFAULT=deepseek:deepseek-chat          # fallback for every stage
    OM_MODEL_MATRIX=anthropic:claude-opus-5-5        # per-stage override (MATRIX, SHEETS_AGENT, RERANK, …)
    DEEPSEEK_API_KEY=…  ANTHROPIC_API_KEY=…  OPENAI_API_KEY=…  OPENROUTER_API_KEY=…

  Providers
    anthropic    Claude via the official `anthropic` SDK (structured outputs, prompt caching, refusal fallback)
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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY", "json": "json_object", "default": "deepseek-chat"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "json": "json_schema", "default": "gpt-4.1-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "json": "json_object", "default": "deepseek/deepseek-chat"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "json": "json_object", "default": "llama-3.3-70b-versatile"},
    "together": {"base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY", "json": "json_object", "default": "deepseek-ai/DeepSeek-V3"},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1", "key_env": "FIREWORKS_API_KEY", "json": "json_object", "default": "accounts/fireworks/models/deepseek-v3"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY", "json": "json_object", "default": "gemini-flash-latest"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY", "json": "json_object", "default": "mistral-large-latest"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None, "json": "json_object", "default": "qwen2.5:14b"},
}
ANTHROPIC_DEFAULT = "claude-opus-5-5"
AUTO_ORDER = ("anthropic", "deepseek", "openai", "gemini", "openrouter", "together", "groq", "fireworks", "mistral")
VISION = ("anthropic", "openai", "gemini", "openrouter")      # providers whose default models read images


class LLMError(Exception):
    pass


class InvalidJSON(LLMError):
    """The model's reply wasn't parseable JSON (truncated or malformed); worth one retry."""


class LLMRefusal(LLMError):
    pass


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
    """Claude via the official SDK. Structured outputs guarantee schema-valid JSON; the document
    prefix is cached; server-side refusal fallback is on."""

    def __init__(self, model: str, client=None):
        self.model = model
        if client is None:
            try:
                import anthropic
            except ImportError:
                raise LLMError("pip install anthropic (requirements.txt) to use Claude")
            client = anthropic.Anthropic()
        self.client = client

    def complete_json(self, system: str, parts: list[Part], schema: dict, max_tokens: int = 16000,
                      effort: str = "medium", repair_note: str | None = None) -> Result:
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
                 transport=None, timeout: int = 300):
        self.name, self.model, self.base_url, self.key, self.json_mode = name, model, base_url.rstrip("/"), api_key, json_mode
        self.transport = transport or self._post
        self.timeout = timeout

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise LLMError(f"{self.name} HTTP {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise LLMError(f"{self.name} unreachable: {e}")
        raise LLMError("retries exhausted")

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
        headers = {"Content-Type": "application/json", "User-Agent": "OpenMultiples/0.1"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        j = self.transport(f"{self.base_url}/chat/completions", body, headers)
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


def key_host_guard(base_url: str) -> None:
    """A custom-endpoint key is only sent to the host it was entered for (see settings.save)."""
    from urllib.parse import urlparse
    bound = (_env("OM_PROVIDER_CUSTOM_KEY_HOST") or "").lower()
    host = (urlparse(base_url).hostname or "").lower()
    if bound and host != bound:
        raise LLMError(f"the saved key was entered for {bound}, not {host}; enter it again in Settings to use this endpoint")
    if urlparse(base_url).scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise LLMError("refusing to send the key over plain http to a remote host; use https://")


def make_provider(spec: str, transport=None, anthropic_client=None):
    """spec: 'provider:model' (model optional), e.g. 'deepseek:deepseek-chat', 'anthropic', 'ollama:qwen2.5:14b'."""
    name, _, model = spec.partition(":")
    name = name.strip().lower()
    if name == "anthropic":
        return AnthropicProvider(model or ANTHROPIC_DEFAULT, client=anthropic_client)
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
    return OpenAICompatProvider(name, model or preset["default"], preset["base_url"], key, preset.get("json", "json_object"), transport)


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
            if name == "anthropic":
                try:
                    import anthropic  # noqa: F401
                except ImportError:
                    continue
            return name
    return None


class Router:
    """Resolves a provider per stage and runs schema-validated JSON completions with one repair retry."""

    def __init__(self, overrides: dict[str, object] | None = None):
        self.overrides = overrides or {}   # stage -> provider instance (tests / programmatic use)
        self._cache: dict[str, object] = {}

    def provider(self, stage: str):
        if stage in self.overrides:
            return self.overrides[stage]
        if stage not in self._cache:
            spec = configured_spec(stage)
            self._cache[stage] = make_provider(spec) if spec else None
        return self._cache[stage]

    def available(self, stage: str) -> bool:
        try:
            return self.provider(stage) is not None
        except LLMError:
            return False

    def describe(self, stage: str) -> str:
        try:
            p = self.provider(stage)
        except LLMError as e:
            return f"misconfigured: {e}"
        if p is None:
            return "none (non-LLM fallback)"
        return f"{getattr(p, 'name', 'anthropic')}:{p.model}"

    def complete_json(self, stage: str, system: str, parts: list[Part], schema: dict, **kw) -> Result:
        p = self.provider(stage)
        if p is None:
            raise LLMError(f"no model configured for stage {stage!r}")
        try:
            res = p.complete_json(system, parts, schema, **kw)
        except InvalidJSON as e:
            note = (f"Your previous reply was not valid JSON ({str(e)[:160]}). Reply again with ONLY one complete JSON object; "
                    "keep each text field short so it fits.")
            kw2 = dict(kw)
            kw2["max_tokens"] = max(int(kw.get("max_tokens") or 8000), 16000)
            res = p.complete_json(system, parts, schema, repair_note=note, **kw2)
            res.repaired = True
        err = validate(res.data, schema)
        if err:
            note = (f"Your previous reply did not match the required JSON schema ({err}). "
                    "Reply again with ONLY the corrected JSON object.")
            res = p.complete_json(system, parts, schema, repair_note=note, **kw)
            res.repaired = True
            err = validate(res.data, schema)
            if err:
                raise LLMError(f"schema validation failed after repair: {err}")
        return res


STAGES = {"ask": "Ask research assistant", "matrix": "Matrix cell answers", "sheets_agent": "Sheets agent",
          "storyboard": "Deck Studio: storyboard and slide prompts", "slide_review": "Deck Studio: partner/MD review of slide images (vision)",
          "slide_build": "Deck Studio: rebuild an approved image as an editable slide (vision)",
          "check": "Consistency checks (optional: extra extraction and review)", "rerank": "Search re-ranking (planned)"}
