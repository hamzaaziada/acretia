"""S6.1 workflow model and sequential executor (D-033).

A ``Workflow`` is a declarative, deterministic step graph. ``RunContext`` owns everything a step needs (tools, evidence,
events, cancel flag, timing, resolver) and exposes ``run_step(step)`` and ``finish()``; ``execute`` is the minimal
sequential loop. A harness-lab runtime (``src.harness.agent.run_workflow``) may replace the loop; it must drive the same
context (see docs/interfaces-s6/workflows.md). No agent loop, planner or recovery lives here.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import importlib.util
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from om.contracts import ContractError, JobStep, SlideSpec, sha256_hex
from om.llm import validate as _schema_validate
from src.harness.evidence import EvidenceBundle, canonical_bytes, head_hash
from src.harness.research.api import (OUTPUT_KINDS, ExcelInputPayload, ResearchResult, SourcedFigure,
                                      partition_figures)
from src.harness.research.verify import SourceResolver, verify_result

STEP_KINDS = ("tool", "verify", "assemble", "review_gate", "llm_text")
_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,47}")
MAX_FOREACH = 25

ASSEMBLERS: dict[str, Callable] = {}
TEXT_STEPS: dict[str, Callable] = {}


def assembler(name):
    def deco(fn):
        ASSEMBLERS[name] = fn
        return fn
    return deco


def text_step(name):
    def deco(fn):
        TEXT_STEPS[name] = fn
        return fn
    return deco


class WorkflowError(Exception):
    pass


class TemplateError(WorkflowError):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------------------------------------ model
@dataclass(frozen=True)
class Step:
    id: str
    kind: str
    tool: str | None = None
    args_template: dict = field(default_factory=dict)
    depends_on: tuple = ()
    optional: bool = False
    timeout_s: float = 60.0
    foreach: str | None = None      # expression -> list; the tool runs once per item (``{{item}}``), output is a list
    when: str | None = None         # expression; the step is skipped when it is falsy

    def __post_init__(self):
        if not _ID_RE.fullmatch(self.id):
            raise WorkflowError(f"step id {self.id!r} must match {_ID_RE.pattern}")
        if self.kind not in STEP_KINDS:
            raise WorkflowError(f"step {self.id}: kind {self.kind!r} not in {STEP_KINDS}")
        if self.kind in ("tool", "assemble", "llm_text") and not self.tool:
            raise WorkflowError(f"step {self.id}: kind {self.kind} needs `tool`")
        if not (isinstance(self.timeout_s, (int, float)) and self.timeout_s > 0):
            raise WorkflowError(f"step {self.id}: timeout_s must be > 0")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "tool": self.tool, "args_template": self.args_template,
                "depends_on": list(self.depends_on), "optional": self.optional, "timeout_s": self.timeout_s,
                "foreach": self.foreach, "when": self.when}


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    description: str
    inputs_schema: dict
    steps: tuple
    outputs: tuple = ("slide_specs", "excel_inputs", "figures")
    keywords: tuple = ()
    prepare: Callable | None = None         # request dict -> {"..."} deterministic plan, visible as ``plan.*``

    def __post_init__(self):
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        self.validate()

    def validate(self):
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids):
            raise WorkflowError(f"{self.id}: duplicate step ids")
        seen = set()
        for s in self.steps:
            for d in s.depends_on:
                if d not in seen:
                    raise WorkflowError(f"{self.id}: step {s.id} depends on {d!r}, which is not an earlier step")
            seen.add(s.id)
        if not self.steps or self.steps[-1].kind != "verify" or sum(s.kind == "verify" for s in self.steps) != 1:
            raise WorkflowError(f"{self.id}: exactly one verify step, and it must be last")
        bad = [o for o in self.outputs if o not in OUTPUT_KINDS and o != "figures"]
        if bad:
            raise WorkflowError(f"{self.id}: unknown outputs {bad}")

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "description": self.description,
                "inputs_schema": self.inputs_schema, "steps": [s.to_dict() for s in self.steps],
                "outputs": list(self.outputs)}

    def content_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.to_dict()))


# ------------------------------------------------------------------------------------------------ templates
_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
_REF = re.compile(r"\{\{\s*(.+?)\s*\}\}")
_MISSING = object()


def lookup(expr: str, scope: dict):
    """``request.tickers[0]``, ``steps.statements.data.x``, ``request.options.years|5`` (default after ``|``)."""
    expr, _, default = expr.partition("|")
    expr = expr.strip()
    cur: Any = scope
    pos = 0
    ok = bool(expr)
    while ok and pos < len(expr):
        if expr[pos] == ".":
            pos += 1
        m = _TOKEN.match(expr, pos)
        if not m:
            raise TemplateError(f"bad reference {expr!r}")
        pos = m.end()
        key, idx = m.group(1), m.group(2)
        try:
            cur = cur[int(idx)] if idx is not None else cur[key]
        except (KeyError, IndexError, TypeError):
            cur = _MISSING
            break
    if cur is _MISSING:
        if default.strip():
            try:
                return json.loads(default)
            except ValueError:
                return default.strip()
        raise TemplateError(f"reference {expr!r} does not resolve")
    return cur


def resolve(value, scope: dict):
    if isinstance(value, str):
        m = _REF.fullmatch(value.strip())
        if m:
            return lookup(m.group(1), scope)
        return _REF.sub(lambda mm: str(lookup(mm.group(1), scope)), value)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [resolve(v, scope) for v in value]
    return value


def truthy(expr: str, scope: dict) -> bool:
    try:
        v = lookup(expr, scope)
    except TemplateError:
        return False
    return bool(v)


# ------------------------------------------------------------------------------------------------ resolver
class LayeredResolver(SourceResolver):
    """Independent base resolver (documents, XBRL) first, then what the run's own tool calls captured."""

    def __init__(self, base: SourceResolver | None = None, pages: dict | None = None):
        super().__init__()
        self.base = base
        for doc, pg in (pages or {}).items():
            for p, text in pg.items():
                self.add_page(doc, int(p), text)

    def _first(self, name, own, *a, **k):
        v = getattr(self.base, name)(*a, **k) if self.base is not None else None
        return v if v is not None else own(*a, **k)

    def xbrl_value(self, *a, **k):
        return self._first("xbrl_value", super().xbrl_value, *a, **k)

    def page_text(self, *a, **k):
        return self._first("page_text", super().page_text, *a, **k)

    def url_text(self, *a, **k):
        return self._first("url_text", super().url_text, *a, **k)

    def cell_value(self, *a, **k):
        return self._first("cell_value", super().cell_value, *a, **k)

    def pages(self, doc_id) -> dict:
        out = {}
        for src in (getattr(self.base, "_pages", None) or {}, self._pages):
            for (d, p), t in src.items():
                if d == doc_id:
                    out.setdefault(p, t)
        return dict(sorted(out.items()))


def _call_with_timeout(fn, timeout):
    box: dict = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as e:      # noqa: BLE001 - re-raised in the caller
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"step exceeded timeout_s={timeout}")
    if "e" in box:
        raise box["e"]
    return box["v"]


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=repr)


def output_digest(result) -> str:
    """Hash of everything a user can see (slides, Excel inputs, figures, rejected). Excludes timings and evidence."""
    d = result.to_dict() if hasattr(result, "to_dict") else result
    keep = {k: d.get(k) for k in ("status", "slide_specs", "excel_inputs", "figures", "rejected")}
    return hashlib.sha256(_canon(keep).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ run context
class RunContext:
    def __init__(self, workflow: Workflow, request, *, job_id: str, evidence_dir="storage/evidence", tools=None,
                 adapter=None, emit=None, cancel=None, resolver=None, review=None, clock=time.perf_counter,
                 bundle: EvidenceBundle | None = None):
        self.workflow = workflow
        self.req_obj = request
        self.request = request.to_dict()
        self.request.setdefault("options", {})
        self.options = self.request["options"]
        self.job_id = job_id
        self.tools = tools
        self.adapter = adapter
        self._emit = emit
        self.cancel = cancel
        self.review = review
        self.clock = clock
        self.bundle = bundle or EvidenceBundle(Path(evidence_dir) / f"{job_id}.jsonl")
        self.resolver = LayeredResolver(resolver, self.options.get("pages") or {})
        self.outputs: dict = {}
        self.figures: list = []          # candidate figure dicts (unverified until the verify step)
        self.slides: list = []
        self.excel: list = []
        self.slide_meta: dict = {}
        self.rejected: list = []
        self.timings: dict = {}
        self.steps: list = []
        self.notes: list = []
        self.cost = 0.0
        self.tokens = 0
        self.status = "running"
        self.error: str | None = None
        self.verified: ResearchResult | None = None
        self.executed = 0
        self.plan = workflow.prepare(self.request) if workflow.prepare else {}
        self._ok: set = set()
        self._snap: dict = {}
        self.finished = False

    # -- plumbing
    def emit(self, type_, data=None):
        if self._emit is not None:
            try:
                self._emit({"v": 1, "type": type_, "job_id": self.job_id, "ts": _now(), "data": data or {}})
            except Exception:
                pass

    def cancelled(self) -> bool:
        return self.cancel is not None and self.cancel.is_set()

    def scope(self, item=_MISSING) -> dict:
        s = {"request": self.request, "steps": self.outputs, "plan": self.plan}
        if item is not _MISSING:
            s["item"] = item
        return s

    def get_tools(self):
        if self.tools is None:
            from src.harness.research.tools import build_registry
            self.tools = build_registry(as_of=self.request.get("as_of"))
        return self.tools

    def evidence(self, tool, args, source, output):
        self.bundle.append(tool, args, source=source, output=output)

    # -- stepping
    def begin(self):
        string = self.workflow.inputs_schema
        data = {"question": self.request.get("question"), "tickers": self.request.get("tickers", []),
                "doc_ids": self.request.get("doc_ids", []), "options": self.options}
        err = _schema_validate(data, string) if string else None
        if err:
            self.status, self.error = "failed", f"invalid inputs for {self.workflow.id}: {err}"
        return self

    def run_step(self, step: Step, n: int | None = None, total: int | None = None) -> str:
        n = n or len(self.steps) + 1
        total = total or len(self.workflow.steps)
        prog = f"{n}/{total}"
        if self.status != "running":
            return "skipped"
        if self.cancelled():
            self.status = "cancelled"
            return "cancelled"
        if self.executed >= self.request["max_steps"]:
            self.status, self.error = "failed", f"max_steps ({self.request['max_steps']}) exceeded"
            return "failed"
        self.executed += 1
        name = step.id
        self.emit("step_started", {"name": name, "kind": step.kind, "progress": prog, "n": n, "of": total})
        t0 = self.clock()
        outcome, detail = "succeeded", ""
        try:
            for d in step.depends_on:
                if d not in self._ok:
                    raise WorkflowError(f"dependency {d!r} did not succeed")
            if step.when and not truthy(step.when, self.scope()):
                detail = f"skipped: {step.when} is empty"
            else:
                detail = getattr(self, f"_do_{step.kind}")(step) or ""
            self._ok.add(step.id)
        except Cancelled:
            self.status, outcome, detail = "cancelled", "cancelled", "cancelled"
        except Exception as e:      # noqa: BLE001 - step failures are data, not crashes
            msg = f"{type(e).__name__}: {e}"[:500]
            if step.optional:
                outcome, detail = "failed", f"optional step failed: {msg}"
                self._ok.add(step.id)
                self.outputs.setdefault(step.id, None)
            else:
                outcome, detail = "failed", msg
                self.status, self.error = "failed", f"step {step.id}: {msg}"
        wall = round(max(self.clock() - t0, 0.0), 6)
        self.timings[step.id] = wall
        self.steps.append(JobStep(step.id, outcome, detail[:500]))
        self.emit("step_finished", {"name": name, "status": outcome, "progress": prog, "n": n, "of": total,
                                    "wall_clock_s": wall})
        return outcome

    def _do_tool(self, step: Step):
        tools = self.get_tools()
        if step.foreach:
            items = lookup(step.foreach, self.scope())
            if not isinstance(items, list):
                raise WorkflowError(f"foreach {step.foreach!r} is not a list")
            res = []
            for it in items[:MAX_FOREACH]:
                if self.cancelled():
                    raise Cancelled()
                res.append(self._one_tool(step, tools, self.scope(it)))
            self.outputs[step.id] = res
            return f"{len(res)} call(s) to {step.tool}"
        self.outputs[step.id] = self._one_tool(step, tools, self.scope())
        return f"called {step.tool}"

    def _one_tool(self, step, tools, scope):
        args = resolve(step.args_template, scope)
        res = _call_with_timeout(lambda: tools.call(step.tool, args), step.timeout_s)
        if not isinstance(res, dict):
            raise WorkflowError(f"tool {step.tool} returned {type(res).__name__}, expected dict")
        self.evidence(step.tool, args, str(res.get("source") or f"tool:{step.tool}"), res)
        self._ingest(res)
        return res

    def _ingest(self, res: dict):
        """Index what a tool call captured so the verifier can re-check it, and collect its candidate figures."""
        data = res.get("data") or {}
        rows = {(r.get("concept"), r.get("end"), r.get("unit")): r for r in data.get("rows") or [] if isinstance(r, dict)}
        for f in res.get("figures") or []:
            self.figures.append(f)
            c = f.get("citation") or {}
            if c.get("xbrl_concept"):
                row = rows.get((c["xbrl_concept"], c.get("as_of"), f.get("units")))
                if row is not None:
                    self.resolver.add_xbrl(c["doc_id"], c["xbrl_concept"], f["period"], row["val"])
            elif c.get("cell_locator"):
                self.resolver.add_cell(c["doc_id"], c["cell_locator"], f["value"])
            elif c.get("quote") and c.get("page") is not None:
                self._snap.setdefault(("p", c["doc_id"], c["page"]), []).append(c["quote"])
            elif c.get("quote") and c.get("url"):
                self._snap.setdefault(("u", c["url"]), []).append(c["quote"])
        for k, quotes in self._snap.items():
            text = "\n".join(dict.fromkeys(quotes))
            if k[0] == "p":
                if self.resolver.base is None or self.resolver.base.page_text(k[1], k[2]) is None:
                    self.resolver.add_page(k[1], k[2], text)
            else:
                self.resolver.add_url(k[1], text)

    def _do_review_gate(self, step: Step):
        if not self.options.get("source_review", True):
            return "source review disabled"
        from .review import await_review, plan_sources
        sources = plan_sources(self)
        self.emit("source_review", {"workflow": self.workflow.id, "status": "awaiting_review", "sources": sources})
        decision = await_review(self, sources)
        self.evidence("review_gate", {"workflow": self.workflow.id}, f"workflow:{self.workflow.id}",
                      {"decision": decision, "sources_sha256": sha256_hex(canonical_bytes(sources))})
        if decision == "cancelled":
            raise Cancelled()
        if decision != "approved":
            self.status, self.error = "cancelled", f"source review {decision}"
            raise Cancelled()
        return f"approved ({len(sources)} source(s))"

    def _do_assemble(self, step: Step):
        fn = ASSEMBLERS.get(step.tool)
        if fn is None:
            raise WorkflowError(f"unknown assembler {step.tool!r}")
        out = fn(self) or {}
        self.evidence(f"assemble:{step.tool}", {}, f"workflow:{self.workflow.id}",
                      {"slides": len(self.slides), "excel": len(self.excel), "figures": len(self.figures), **out})
        return f"{len(self.slides)} slide(s), {len(self.excel)} excel input(s)"

    def _do_llm_text(self, step: Step):
        fn = TEXT_STEPS.get(step.tool)
        if fn is None:
            raise WorkflowError(f"unknown text step {step.tool!r}")
        info = fn(self) or {}
        self.evidence(f"llm_text:{step.tool}", {}, f"workflow:{self.workflow.id}", info)
        return info.get("detail", "")

    def _do_verify(self, step: Step):
        figs, rej = partition_figures(_dedupe(self.figures))
        slides = []
        for s in self.slides:
            try:
                slides.append(SlideSpec.from_dict(s).to_dict())
            except ContractError as e:
                rej.append({"figure": {"kind": "slide_spec", "id": str(s.get("id", "")), "spec": s}, "reason": str(e)})
        excel = []
        for p in self.excel:
            try:
                excel.append(ExcelInputPayload.from_dict(p))
            except ContractError as e:
                rej.append({"figure": {"kind": "excel_input", "id": str(p.get("model_type", "")), "payload": p},
                            "reason": str(e)})
        head = head_hash(self.bundle.path)
        cand = ResearchResult(job_id=self.job_id, status="succeeded", evidence_head=head, slide_specs=slides,
                              excel_inputs=excel, figures=figs, rejected=rej)
        self.verified = verify_result(cand, self.resolver)
        for r in self.verified.rejected:
            self.emit("rejected", r)
        for f in self.verified.figures:
            self.emit("figure", f.to_dict())
        self.evidence("verify", {}, f"workflow:{self.workflow.id}",
                      {"figures_ok": len(self.verified.figures), "rejected": len(self.verified.rejected),
                       "slides_ok": len(self.verified.slide_specs), "digest": output_digest(self.verified)})
        return (f"{len(self.verified.figures)} verified, {len(self.verified.rejected)} rejected, "
                f"{len(self.verified.slide_specs)} slide(s) kept")

    # -- result
    def finish(self) -> ResearchResult:
        if self.finished:
            raise WorkflowError("finish() called twice")
        self.finished = True
        if self.status == "running":
            self.status = "succeeded"
        try:
            if self.status == "cancelled":
                self.emit("done", {"status": "cancelled"})
            elif self.status == "failed":
                self.emit("error", {"message": self.error})
                self.emit("done", {"status": "failed"})
            else:
                self.emit("done", {"status": "succeeded"})
            head = head_hash(self.bundle.path)
            kw: dict = {}
            if self.status == "succeeded" and self.verified is not None:
                v = self.verified
                outs = self.request.get("outputs") or list(OUTPUT_KINDS)
                kw = {"slide_specs": v.slide_specs if "slide_specs" in outs else [],
                      "excel_inputs": v.excel_inputs if "excel_inputs" in outs else [],
                      "figures": v.figures, "rejected": v.rejected}
            res = ResearchResult(job_id=self.job_id, status=self.status, evidence_head=head, cost_usd=self.cost,
                                 tokens=self.tokens, steps=self.steps, error=self.error, timings=dict(self.timings),
                                 **kw)
            return res.validate()
        finally:
            self.bundle.close()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dedupe(figs: list) -> list:
    seen, out = set(), []
    for f in figs:
        k = _canon(f)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


# ------------------------------------------------------------------------------------------------ execution
def agent_runtime() -> Callable | None:
    """The harness-lab runtime (S9) if it exists and exposes ``run_workflow(workflow, context)``."""
    try:
        if importlib.util.find_spec("src.harness.agent") is None:
            return None
        mod = importlib.import_module("src.harness.agent")
    except Exception:       # noqa: BLE001
        return None
    fn = getattr(mod, "run_workflow", None)
    return fn if callable(fn) else None


def execute(workflow: Workflow, ctx: RunContext) -> ResearchResult:
    """Minimal sequential executor: declared order, cancel flag checked between steps."""
    ctx.begin()
    total = len(workflow.steps)
    for i, step in enumerate(workflow.steps, 1):
        if ctx.status != "running":
            break
        ctx.run_step(step, i, total)
    return ctx.finish()


def run_workflow(workflow: Workflow, ctx: RunContext, *, use_runtime: bool = True) -> ResearchResult:
    rt = agent_runtime() if use_runtime else None
    if rt is not None:
        return rt(workflow, ctx)
    return execute(workflow, ctx)
