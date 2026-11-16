"""S6.0 stable research-agent contracts and entry point.

``run_research`` is the one function the product app calls (directly or via ``jobs.py``). Until S6.1 lands it
runs a deterministic placeholder planner: no model call without an injected adapter, a verifiable evidence
chain, well-formed empty output. Output is only SlideSpecs, Excel input payloads and sourced figures; free prose
is rejected by the contract (PLAN S6.2). Additive changes only; every payload carries ``"v": 1``.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar

from om.contracts import (STATUS, Citation, Contract, ContractError, JobStep, SlideSpec, _err, enum, integer,
                          iso_date, json_value, listing, mapping, nested, number, optional, string, utc_timestamp)
from src.harness.evidence import EvidenceBundle, head_hash

API_VERSION = 1
OUTPUT_KINDS = ("slide_specs", "excel_inputs", "grid_answers")
EVENT_TYPES = ("step_started", "step_finished", "figure", "rejected", "cost", "done", "error")
JOB_ID_RE = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
PROSE_KEYS = frozenset({"answer", "summary", "text", "prose", "report", "markdown", "narrative", "commentary",
                        "memo", "essay", "content", "analysis"})
_HASH = string(pattern=r"[0-9a-f]{64}")
_ID = string(pattern=JOB_ID_RE)
_V = enum(API_VERSION) if False else (lambda x, p: x if (x == API_VERSION and not isinstance(x, bool))
                                      else _err(p, f"unsupported version {x!r}; this build speaks v={API_VERSION}"))


def _reject_prose(d, path):
    if isinstance(d, dict):
        for k in d:
            if k in PROSE_KEYS:
                _err(f"{path}.{k}", "free prose deliverables are not allowed; use slide_specs, excel_inputs or "
                                    "sourced figures")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dicts_of(cls):
    def v(x, p):
        if not isinstance(x, (list, tuple)):
            _err(p, f"expected list, got {type(x).__name__}")
        return [cls._parse(e, f"{p}[{i}]").to_dict() for i, e in enumerate(x)]
    return v


@dataclass
class ResearchRequest(Contract):
    question: str
    tickers: list = field(default_factory=list)
    doc_ids: list = field(default_factory=list)
    room_id: str | None = None
    as_of: str | None = None
    outputs: list = field(default_factory=lambda: list(OUTPUT_KINDS))
    budget_usd: float = 2.0
    max_steps: int = 12
    org_id: str = "local"
    user_id: str | None = None
    v: int = API_VERSION
    SCHEMA: ClassVar = {
        "question": string(), "tickers": listing(string(pattern=r"[A-Za-z0-9.\-]{1,12}"), unique=True),
        "doc_ids": listing(string(pattern=r"\S+"), unique=True), "room_id": optional(string(pattern=r"\S+")),
        "as_of": optional(iso_date), "outputs": listing(enum(*OUTPUT_KINDS), min_len=1, unique=True),
        "budget_usd": lambda x, p: number()(x, p) if number()(x, p) > 0 else _err(p, "must be > 0"),
        "max_steps": integer(1, 50), "org_id": string(pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"),
        "user_id": optional(string(pattern=r"\S+")), "v": _V}

    @classmethod
    def _parse(cls, d, path):
        _reject_prose(d, path)
        return super()._parse(d, path)


@dataclass
class SourcedFigure(Contract):
    label: str
    value: float
    units: str
    period: str
    citation: Citation
    v: int = API_VERSION
    SCHEMA: ClassVar = {"label": string(), "value": number(), "units": string(), "period": string(),
                        "citation": nested(Citation), "v": _V}

    def _check(self, path):
        c = self.citation
        if not c.as_of:
            _err(f"{path}.citation.as_of", "required: every figure needs an as-of date")
        if not (c.url or c.source_url) and c.page is None:
            _err(f"{path}.citation", "needs a url, or doc_id with a page")


@dataclass
class ExcelInputPayload(Contract):
    model_type: str
    ticker: str
    inputs: dict = field(default_factory=dict)
    v: int = API_VERSION
    SCHEMA: ClassVar = {"model_type": string(), "ticker": string(pattern=r"[A-Za-z0-9.\-]{1,12}"),
                        "inputs": mapping(string(), nested(SourcedFigure)), "v": _V}


@dataclass
class RejectedFigure(Contract):
    figure: dict
    reason: str
    SCHEMA: ClassVar = {"figure": mapping(string(), json_value), "reason": string()}


@dataclass
class ResearchResult(Contract):
    job_id: str
    status: str
    evidence_head: str
    slide_specs: list = field(default_factory=list)
    excel_inputs: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    cost_usd: float = 0.0
    tokens: int = 0
    steps: list = field(default_factory=list)
    error: str | None = None
    v: int = API_VERSION
    SCHEMA: ClassVar = {
        "job_id": _ID, "status": enum(*STATUS), "evidence_head": _HASH, "slide_specs": _dicts_of(SlideSpec),
        "excel_inputs": listing(nested(ExcelInputPayload)), "figures": listing(nested(SourcedFigure)),
        "rejected": listing(nested(RejectedFigure)), "cost_usd": number(0), "tokens": integer(0),
        "steps": listing(nested(JobStep)), "error": optional(string(0)), "v": _V}

    @classmethod
    def _parse(cls, d, path):
        _reject_prose(d, path)
        return super()._parse(d, path)


@dataclass
class ResearchEvent(Contract):
    type: str
    job_id: str
    ts: str
    data: dict = field(default_factory=dict)
    seq: int | None = None          # assigned by jobs.events(); absent for in-process callbacks
    v: int = API_VERSION
    SCHEMA: ClassVar = {"type": enum(*EVENT_TYPES), "job_id": _ID, "ts": utc_timestamp,
                        "data": mapping(string(), json_value), "seq": optional(integer(1)), "v": _V}


def partition_figures(candidates) -> tuple[list, list]:
    """Split raw figure dicts into (valid SourcedFigure list, rejected [{figure, reason}]). Anything without a
    verifiable source and as-of date lands in ``rejected``; nothing is silently dropped."""
    ok, bad = [], []
    for c in candidates or []:
        try:
            ok.append(SourcedFigure.from_dict(c))
        except (ContractError, TypeError, AttributeError) as e:
            fig = c if isinstance(c, dict) else {"raw": repr(c)}
            try:
                fig = json.loads(json.dumps(fig, default=repr))
            except (TypeError, ValueError):
                fig = {"raw": repr(c)}
            bad.append({"figure": fig, "reason": str(e)})
    return ok, bad


_PLAN_SCHEMA = {"type": "object", "properties": {"tool": {"type": "string"}, "args": {"type": "object"}},
                "required": ["tool"]}


def run_research(request: ResearchRequest, *, adapter=None, tools=None, evidence_dir="storage/evidence",
                 job_id: str | None = None, on_event: Callable[[dict], None] | None = None,
                 cancel: threading.Event | None = None) -> ResearchResult:
    """STABLE entry point. Never raises for agent-level failures: they come back as status "failed" with ``error``.
    Raises ContractError only for an invalid request/job_id."""
    if isinstance(request, dict):
        request = ResearchRequest.from_dict(request)
    request.validate()
    if job_id is None:
        job_id = "res_" + re.sub(r"\W", "", _now())[:20]
    string(pattern=JOB_ID_RE)(job_id, "job_id")
    steps: list[JobStep] = []
    cost, tokens = 0.0, 0
    state = {"status": "succeeded", "error": None}

    def emit(type_, data=None):
        if on_event is not None:
            try:
                on_event({"v": API_VERSION, "type": type_, "job_id": job_id, "ts": _now(), "data": data or {}})
            except Exception:
                pass    # a broken listener must not kill the run

    def cancelled() -> bool:
        return cancel is not None and cancel.is_set()

    bundle = EvidenceBundle(Path(evidence_dir) / f"{job_id}.jsonl")

    def step(name, fn):
        """Run one step: events, JobStep row, cancellation checked before it starts."""
        if cancelled():
            state["status"] = "cancelled"
            return False
        if len(steps) >= request.max_steps:
            state["status"], state["error"] = "failed", f"max_steps ({request.max_steps}) exceeded"
            return False
        emit("step_started", {"name": name})
        try:
            detail = fn() or ""
        except Exception as e:      # agent-level failure -> failed result, not a raised exception
            steps.append(JobStep(name, "failed", str(e)[:500]))
            emit("step_finished", {"name": name, "status": "failed"})
            state["status"], state["error"] = "failed", f"{type(e).__name__}: {e}"[:500]
            return False
        steps.append(JobStep(name, "succeeded", detail))
        emit("step_finished", {"name": name, "status": "succeeded"})
        return True

    def plan():
        bundle.append("plan", request.to_dict(), source="planner:placeholder",
                      output={"planner": "placeholder", "outputs": request.outputs})
        return "deterministic placeholder plan"

    def probe():
        nonlocal cost, tokens
        res = adapter.chat([{"role": "user", "content": "Pick one tool to call for: " + request.question}],
                           json_schema=_PLAN_SCHEMA, job_id=job_id)
        cost += float(res.cost_usd or 0)
        tokens += int((res.usage or {}).get("total_tokens", 0) or 0)
        emit("cost", {"cost_usd": cost, "tokens": tokens})
        if cost > request.budget_usd:
            raise RuntimeError(f"budget exceeded: {cost:.4f} > {request.budget_usd}")
        choice = res.data if isinstance(res.data, dict) else {}
        name = choice.get("tool")
        if tools is not None and name:
            out = tools.call(name, choice.get("args") or {})
            bundle.append(f"tool:{name}", choice.get("args") or {}, source=f"tool:{name}", output=out)
            return f"called {name} once"
        return "adapter replied; no tool call"

    def note():
        return "agent not yet implemented (S6.1)"

    try:
        for name, fn, enabled in (("plan", plan, True), ("plumbing_probe", probe, adapter is not None),
                                  ("note", note, True)):
            if enabled and not step(name, fn):
                break
        if cancelled() and state["status"] == "succeeded":
            state["status"] = "cancelled"
        if state["status"] == "cancelled":
            emit("done", {"status": "cancelled"})
        elif state["status"] == "failed":
            emit("error", {"message": state["error"]})
            emit("done", {"status": "failed"})
        figures, rejected = partition_figures([])
        for r in rejected:
            emit("rejected", r)
        for f in figures:
            emit("figure", f.to_dict())
        if state["status"] == "succeeded":
            emit("done", {"status": "succeeded"})
        result = ResearchResult(job_id=job_id, status=state["status"], evidence_head=head_hash(bundle.path),
                                figures=figures, rejected=rejected, cost_usd=cost, tokens=tokens, steps=steps,
                                error=state["error"])
        return result.validate()
    finally:
        bundle.close()
