"""Rule-first router, model profiles and tool registry (Stage 2, S2.3). Ported from meshpool_harness/router.

* ``route()`` decides task type + engine chain with deterministic keyword/file-type rules. Only when the rules'
  confidence is below ``THRESHOLD`` is ``classifier.chat(...)`` called (once); if that fails the result falls back
  to ``general/reasoning``. Every decision can be appended to a CSV log.
* Profiles are JSON files in ``src/harness/profiles/`` (not YAML: the core is stdlib-only, D-001, and JSON needs
  no loader). Env ``ACRETIA_PROFILE`` forces a profile by name.
* ``ToolRegistry`` is the tool surface MCP servers (S2.4) plug into; ``call`` validates args with ``om.llm.validate``.
The model adapter is never imported here: a classifier is any object with ``chat(messages, json_schema=, job_id=)``.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from om.llm import validate

TASK_TYPES = ("extraction", "modeling", "reasoning", "vision_critic", "persona")
ENGINES = ("deck", "excel", "grid", "research", "general")
ROLES = ("planner", "worker", "verifier", "critic")
THRESHOLD = 0.6
PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
DEFAULT_PROFILE = "claude"
VISION_FALLBACK_ORDER = ("claude", "openai", "gemini")
DEFAULT_ENGINE = {"extraction": "grid", "modeling": "excel", "reasoning": "general", "vision_critic": "general",
                  "persona": "general"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".ods"}
DOC_EXT = {".pdf", ".zip", ".docx", ".doc", ".msg", ".eml"}
DECK_EXT = {".pptx", ".ppt", ".key"}

# (task_type, engine, regex, weight); the regex runs on lower-cased text.
RULES = [
    ("modeling", "excel", r"\broll[- ]?forward\b", 3.0),
    ("modeling", "excel", r"\b(three|3)[- ]statement|\bdcf\b|\blbo\b|\bfinancial model|\bcap table|\bwaterfall model", 3.0),
    ("modeling", "excel", r"\b(spreadsheet|workbook|excel|xlsx|tab|sheet|formulas?)\b", 1.0),
    ("modeling", "excel", r"\b(model|forecast|projections?|sensitivity|scenario)\b", 1.0),
    ("extraction", "grid", r"\b(diligence questions?|dd questions?|due diligence|data ?room|vdr|question list)\b", 3.0),
    ("extraction", "grid", r"\b(extract|pull out|parse|abstract|summari[sz]e each|per[- ]document|cite|citations?)\b", 1.5),
    ("extraction", "grid", r"\b(contracts?|leases?|agreements?|filings?|10-?k|10-?q|cim|documents?)\b", 1.0),
    ("reasoning", "deck", r"\b(pitch ?book|pitch ?deck|slides?|slide ?deck|deck|presentation|powerpoint|pptx|board ?pack)\b", 3.0),
    ("reasoning", "research", r"\b(research|market size|tam|competitor landscape|industry overview|peer set|"
                              r"trading comps|precedent transactions?|look up|find out)\b", 2.0),
    ("vision_critic", "general", r"\b(critique|critic|visual review|design review|look(s)? (right|off)|layout|"
                                 r"screenshot|rendered|overlap|alignment|legib\w*)\b", 2.0),
    ("persona", "general", r"\b(persona|role[- ]?play|as (a|the) (cfo|ceo|buyer|investor|lp|banker|vp)|"
                           r"pretend (you are|to be)|simulate (a|the) (buyer|investor|customer)|buyer feedback)\b", 3.0),
    ("reasoning", "general", r"\b(explain|why|analy[sz]e|compare|recommend|memo|assess|evaluate|think through)\b", 1.0),
]
_COMPILED = [(t, e, re.compile(p), w) for t, e, p, w in RULES]
CLASSIFIER_SCHEMA = {"type": "object", "required": ["task_type", "engines"], "properties": {
    "task_type": {"type": "string", "enum": list(TASK_TYPES)},
    "engines": {"type": "array", "items": {"type": "string", "enum": list(ENGINES)}},
    "confidence": {"type": "number"}}}


@dataclass
class Route:
    task_type: str
    engines: list
    profile: str
    models: dict
    confidence: float
    reason: str
    used_model_call: bool = False


# ------------------------------------------------------------------------------------------------ profiles
def load_profiles(directory: str | Path | None = None) -> dict:
    out = {}
    for p in sorted(Path(directory or PROFILE_DIR).glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def profile_for_model(model_id: str, profiles: dict | None = None) -> dict | None:
    """Profile whose ``match`` regexes hit ``model_id``. ``ACRETIA_PROFILE`` (a profile name) overrides.
    Local (Ollama/vLLM/open-weight tag) patterns are tried first; None when nothing matches."""
    profiles = profiles or load_profiles()
    forced = os.environ.get("ACRETIA_PROFILE")
    if forced and forced in profiles:
        return profiles[forced]
    mid = (model_id or "").lower()
    order = ["local"] + [k for k in profiles if k != "local"]
    for name in order:
        for pat in (profiles.get(name) or {}).get("match", []):
            if re.search(pat, mid):
                return profiles[name]
    return None


def _resolve_profile(name: str | None, profiles: dict) -> tuple[str, str]:
    forced = name or os.environ.get("ACRETIA_PROFILE") or DEFAULT_PROFILE
    if forced in profiles:
        return forced, ""
    p = profile_for_model(forced, profiles)           # allow a model id in place of a profile name
    if p:
        return p["family"], ""
    return DEFAULT_PROFILE, f"unknown profile {forced!r}, using {DEFAULT_PROFILE}"


def models_for(profile: dict, task_type: str) -> dict:
    rec = profile.get("recommended", {})
    base = dict(rec.get("default", {}))
    base.update(rec.get(task_type, {}))
    return {r: base.get(r) for r in ROLES}


# ------------------------------------------------------------------------------------------------ rules
def _rules(request: str, files) -> tuple[dict, dict, list]:
    t = request.lower()
    sc = {k: 0.0 for k in TASK_TYPES}
    eng: dict = {k: {} for k in TASK_TYPES}
    why = []
    for tt, e, rx, w in _COMPILED:
        n = len(rx.findall(t))
        if n:
            add = w * min(n, 2)
            sc[tt] += add
            eng[tt][e] = eng[tt].get(e, 0.0) + add
            why.append(f"{tt}:{rx.pattern[:24]}")
    exts = [Path(f).suffix.lower() for f in files]
    names = " ".join(Path(f).name.lower() for f in files)
    if any(x in EXCEL_EXT for x in exts):
        sc["modeling"] += 1.0
        eng["modeling"]["excel"] = eng["modeling"].get("excel", 0.0) + 1.0
        why.append("file xlsx")
    n_docs = sum(1 for x in exts if x in DOC_EXT)
    if n_docs:
        w = 1.0 + (1.0 if n_docs > 2 or ".zip" in exts or re.search(r"vdr|data ?room|diligence", names) else 0.0)
        sc["extraction"] += w
        eng["extraction"]["grid"] = eng["extraction"].get("grid", 0.0) + w
        why.append("file pdf/zip")
    if any(x in DECK_EXT for x in exts):
        sc["reasoning"] += 1.0
        eng["reasoning"]["deck"] = eng["reasoning"].get("deck", 0.0) + 1.0
    if any(x in IMAGE_EXT for x in exts):
        w = 1.0 + (2.0 if re.search(r"\b(critique|review|check|look|render|screenshot|layout)", t) else 0.0)
        sc["vision_critic"] += w
        why.append("image file")
    if sc["vision_critic"] and re.search(r"\b(slides?|deck|pitch ?book)\b", t):
        eng["vision_critic"]["deck"] = eng["vision_critic"].get("deck", 0.0) + 1.0
    return sc, eng, why


def _best_engine(eng: dict, task_type: str) -> str:
    cand = eng.get(task_type) or {}
    return max(cand, key=cand.get) if cand else DEFAULT_ENGINE[task_type]


def decide(request: str, files=(), task_type: str | None = None) -> tuple[str, list, float, str]:
    sc, eng, why = _rules(request, list(files))
    if task_type:
        return task_type, [_best_engine(eng, task_type)], 1.0, f"task_type override={task_type}"
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    (top_t, s1), (_, s2) = ranked[0], ranked[1]
    if s1 <= 0:
        return "reasoning", ["general"], 0.2, "no rule matched"
    conf = min(0.97, 0.4 + 0.12 * min(s1, 4.0)) * (1 - 0.5 * (s2 / s1))
    engines = [_best_engine(eng, top_t)]
    # deliverable chain: a modeling/extraction request that also names a deck ends in the deck engine
    if top_t in ("modeling", "extraction") and eng["reasoning"].get("deck", 0) >= 3.0:
        engines.append("deck")
    return top_t, engines, round(conf, 2), f"scores { {k: round(v, 1) for k, v in sc.items() if v} }; " + ", ".join(why[:4])


def _parse_classifier(resp) -> dict:
    d = getattr(resp, "data", resp)
    if isinstance(d, str):
        d = json.loads(d[d.find("{"): d.rfind("}") + 1])
    if not isinstance(d, dict):
        raise ValueError("classifier returned no object")
    err = validate(d, CLASSIFIER_SCHEMA)
    if err:
        raise ValueError(err)
    return d


def _classify(request: str, files, classifier, job_id: str) -> tuple[str, list, float]:
    prompt = ("Classify this request. task_type: extraction (pull facts from documents into a grid), modeling "
              "(build/roll an Excel model), reasoning (analysis, research, decks), vision_critic (review images "
              "or layout), persona (role-play a buyer/investor). engines: any of deck, excel, grid, research, "
              "general. Reply JSON only.\nRequest: " + request +
              "\nFiles: " + (", ".join(Path(f).name for f in files) or "none"))
    d = _parse_classifier(classifier.chat([{"role": "user", "content": prompt}], json_schema=CLASSIFIER_SCHEMA,
                                          job_id=job_id))
    return d["task_type"], [e for e in d["engines"] if e in ENGINES] or ["general"], float(d.get("confidence", 0.7))


def _log(path, request, files, r: Route, job_id: str) -> None:
    p = Path(path)
    new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "job_id", "request", "files", "task_type", "engines", "profile", "confidence",
                        "used_model_call", "reason"])
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), job_id, request[:200],
                    ";".join(Path(x).name for x in files), r.task_type, "+".join(r.engines), r.profile,
                    r.confidence, r.used_model_call, r.reason[:200]])


def route(request: str, *, files=(), task_type: str | None = None, profile: str | None = None, classifier=None,
          log_path=None, job_id: str = "router", threshold: float = THRESHOLD) -> Route:
    files = list(files)
    if task_type is not None and task_type not in TASK_TYPES:
        raise ValueError(f"unknown task_type {task_type!r}")
    tt, engines, conf, why = decide(request, files, task_type)
    used = False
    if conf < threshold and classifier is not None:
        used = True
        try:
            tt2, eng2, conf2 = _classify(request, files, classifier, job_id)
            tt, engines, conf, why = tt2, eng2, conf2, f"classifier (rules said {tt}@{conf})"
        except Exception as e:                      # any classifier failure: safe default
            tt, engines, conf, why = "reasoning", ["general"], 0.3, f"classifier failed ({type(e).__name__}); fallback"
    profiles = load_profiles()
    pname, note = _resolve_profile(profile, profiles)
    if note:
        why += "; " + note
    if tt == "vision_critic" and not profiles[pname].get("supports_vision"):
        alt = next((n for n in VISION_FALLBACK_ORDER if profiles.get(n, {}).get("supports_vision")), None)
        if alt:
            why += f"; profile {pname} lacks vision, switched to {alt}"
            pname = alt
    r = Route(tt, engines, pname, models_for(profiles[pname], tt), conf, why, used)
    if log_path or os.environ.get("ACRETIA_ROUTING_LOG"):
        _log(log_path or os.environ["ACRETIA_ROUTING_LOG"], request, files, r, job_id)
    return r


# ------------------------------------------------------------------------------------------------ tools
class ToolError(Exception):
    pass


@dataclass
class _Tool:
    name: str
    fn: object
    schema: dict
    task_types: tuple
    description: str = ""


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, _Tool] = {}

    def register(self, name: str, fn, schema: dict, task_types=None, description: str = "") -> None:
        if not name or name in self._tools:
            raise ToolError(f"invalid or duplicate tool name {name!r}")
        tts = tuple(task_types) if task_types else TASK_TYPES
        bad = [t for t in tts if t not in TASK_TYPES]
        if bad:
            raise ToolError(f"unknown task types {bad}")
        self._tools[name] = _Tool(name, fn, schema, tts, description or (getattr(fn, "__doc__", "") or "").strip())

    def list(self, task_type: str | None = None) -> list[dict]:
        return [{"name": t.name, "description": t.description, "inputSchema": t.schema}
                for t in self._tools.values() if task_type is None or task_type in t.task_types]

    def call(self, name: str, args: dict | None = None):
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool {name!r}")
        args = {} if args is None else args
        err = validate(args, tool.schema)
        if not err and tool.schema.get("additionalProperties") is False:
            extra = set(args) - set(tool.schema.get("properties", {}))
            if extra:
                err = f"unexpected keys {sorted(extra)}"
        if err:
            raise ToolError(f"invalid arguments for {name}: {err}")
        return tool.fn(**args)
