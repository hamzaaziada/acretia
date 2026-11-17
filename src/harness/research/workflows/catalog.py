"""The S6.1 workflow catalog: definitions, search by description (BM25), "/" composition, routing."""
from __future__ import annotations

import math
import re

from .base import Step, Workflow, WorkflowError
from . import steps as S

_STATEMENTS = dict(id="statements", kind="tool", tool="sec_statements", foreach="request.tickers",
                   args_template={"ticker": "{{item}}", "years": "{{request.options.years|5}}"})
_Q_STATEMENTS = dict(id="quarterly_statements", kind="tool", tool="sec_statements", foreach="request.tickers",
                     args_template={"ticker": "{{item}}", "years": 2, "period": "quarterly"})
_REVIEW = dict(id="review", kind="review_gate")
_TITLES = dict(id="titles", kind="llm_text", tool="action_titles", optional=True)
_VERIFY = dict(id="verify", kind="verify")
_SCHEMA = {"type": "object", "properties": {"tickers": {"type": "array"}, "doc_ids": {"type": "array"},
                                              "options": {"type": "object"}}}


def _wf(id_, title, description, keywords, steps, *, requires=(), prepare=None):
    return Workflow(id=id_, title=title, description=description, inputs_schema=_SCHEMA,
                    steps=tuple(Step(**s) for s in steps), keywords=tuple(keywords), requires=tuple(requires),
                    prepare=prepare)


def _build() -> dict:
    wfs = [
        _wf("company_profile", "Company profile one-pager",
            "One-page company profile: business description, headline KPIs, five-year financials and margin ratios "
            "from SEC filings, every figure sourced.",
            ("profile", "one-pager", "tear sheet", "company overview", "financials", "kpi"),
            [_REVIEW, _STATEMENTS,
             dict(id="company_page", kind="tool", tool="web_facts", optional=True, when="request.options.company_url",
                  args_template={"url": "{{request.options.company_url}}"}),
             dict(id="assemble_company_profile", kind="assemble", tool="company_profile", depends_on=("statements",)),
             _TITLES, _VERIFY], requires=("tickers",)),
        _wf("earnings_recap", "Earnings recap",
            "Earnings recap: latest quarter against the prior quarter and the year-ago quarter for revenue, margins and "
            "diluted EPS where tagged (derived Q4 labelled), plus management guidance only when it is sourced.",
            ("earnings", "recap", "results", "quarter", "eps", "margin", "guidance"),
            [_REVIEW, _Q_STATEMENTS,
             dict(id="eps", kind="tool", tool="sec_facts", optional=True,
                  args_template={"ticker": "{{request.tickers[0]}}", "concepts": [S.EPS_CONCEPT], "periods": 8,
                                 "period": "quarterly"}),
             dict(id="guidance", kind="tool", tool="web_facts", optional=True, when="request.options.guidance_url",
                  args_template={"url": "{{request.options.guidance_url}}"}),
             dict(id="assemble_earnings_recap", kind="assemble", tool="earnings_recap",
                  depends_on=("quarterly_statements",)),
             _TITLES, _VERIFY], requires=("tickers",)),
        _wf("buyer_list", "Buyer list",
            "Strategic and financial buyer list ranked by a deterministic score on sourced cash capacity, leverage "
            "headroom and operating margin; candidates come only from the inputs or the grid, never invented.",
            ("buyers", "acquirers", "strategic", "financial sponsors", "private equity", "m&a", "ranking", "sell-side"),
            [_REVIEW,
             dict(id="candidate_statements", kind="tool", tool="sec_statements", foreach="plan.candidate_tickers",
                  when="plan.candidate_tickers", optional=True,
                  args_template={"ticker": "{{item}}", "years": 2}),
             dict(id="grid", kind="tool", tool="grid_query", optional=True, when="request.options.grid_sql",
                  args_template={"sql": "{{request.options.grid_sql}}"}),
             dict(id="assemble_buyer_list", kind="assemble", tool="buyer_list"),
             _TITLES, _VERIFY], prepare=S.prepare_buyer_list),
        _wf("qa", "Sourced question answering",
            "Answer a question about a company with targeted tool calls; the answer is sourced figures with citations.",
            ("question", "answer", "ask", "lookup", "how much", "what was"),
            [_REVIEW, _STATEMENTS,
             dict(id="qa_eps", kind="tool", tool="sec_facts", optional=True, when="plan.concepts",
                  args_template={"ticker": "{{request.tickers[0]}}", "concepts": "{{plan.concepts}}", "periods": 3}),
             dict(id="assemble_qa", kind="assemble", tool="qa", depends_on=("statements",)),
             _TITLES, _VERIFY], requires=("tickers",), prepare=S.prepare_qa),
        _wf("tick_and_tie", "Tick and tie",
            "Tick and tie a document against a model or sourced figures page by page: every number gets its location, "
            "matched source and status ok, mismatch or unsourced.",
            ("tick", "tie", "tick and tie", "tie out", "cross-check", "document", "audit", "reconcile", "pages"),
            [_REVIEW, _STATEMENTS,
             dict(id="model_cells", kind="tool", tool="xlsx_evaluate", optional=True, when="request.options.model",
                  args_template={"path": "{{request.options.model.path}}", "cells": "{{request.options.model.cells}}"}),
             dict(id="assemble_tick_and_tie", kind="assemble", tool="tick_and_tie"),
             _TITLES, _VERIFY], requires=("doc_ids",)),
    ]
    return {w.id: w for w in wfs}


CATALOG: dict = _build()


def get(workflow_id: str) -> Workflow:
    try:
        return CATALOG[workflow_id]
    except KeyError:
        raise WorkflowError(f"unknown workflow {workflow_id!r}; known: {sorted(CATALOG)}") from None


def ids() -> list:
    return list(CATALOG)


# ------------------------------------------------------------------------------------------------ search (item 32)
_STOP = frozenset("a an and the of to for in on with from by is are was be it its this that as at or".split())
_TOK = re.compile(r"[a-z0-9&]+")


def _tokens(text: str) -> list:
    return [t for t in _TOK.findall(text.lower()) if t not in _STOP]


def _is_enabled(org_id, agent_id) -> bool:
    try:
        from src.harness.admin.agents import is_enabled
    except ImportError:
        return True
    return bool(is_enabled(org_id, agent_id))


def search(query: str, org_id: str = "local", *, limit: int = 10) -> list:
    """BM25 over title + description + keywords; deterministic (ties by id). Admin-disabled agents are filtered out."""
    docs = {i: _tokens(f"{w.title} {w.description} {' '.join(w.keywords)}") for i, w in CATALOG.items()}
    n, avg = len(docs), sum(len(d) for d in docs.values()) / max(len(docs), 1)
    q = _tokens(query)
    out = []
    for i, d in docs.items():
        sc = 0.0
        for t in set(q):
            f = d.count(t)
            if not f:
                continue
            df = sum(1 for x in docs.values() if t in x)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            sc += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * len(d) / avg))
        if sc > 0:
            out.append((round(sc, 9), i))
    out.sort(key=lambda x: (-x[0], x[1]))
    res = []
    for sc, i in out:
        if _is_enabled(org_id, i):
            w = CATALOG[i]
            res.append({"id": i, "title": w.title, "description": w.description, "score": sc})
        if len(res) >= limit:
            break
    return res


# ------------------------------------------------------------------------------------------------ "/" composition (item 30)
_TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,11}")


def parse_command(text: str) -> dict:
    """``"/company_profile /earnings_recap AAPL MSFT"`` -> workflows, tickers, remaining text."""
    toks = text.strip().split()
    wfs = []
    while toks and toks[0].startswith("/"):
        name = toks.pop(0)[1:]
        if name not in CATALOG:
            raise WorkflowError(f"unknown workflow {name!r}; known: {sorted(CATALOG)}")
        if name not in wfs:
            wfs.append(name)
    if not wfs:
        raise WorkflowError("no /workflow in command")
    tickers = [t for t in toks if _TICKER.fullmatch(t)]
    return {"workflows": wfs, "tickers": list(dict.fromkeys(tickers)), "rest": " ".join(toks)}


def compose(parts, *, id: str | None = None) -> Workflow:
    """One workflow with the union of steps (same step id means the same definition, run once) and merged outputs."""
    wfs = [get(p) if isinstance(p, str) else p for p in parts]
    if not wfs:
        raise WorkflowError("compose needs at least one workflow")
    if len(wfs) == 1:
        return wfs[0]
    seen: dict = {}
    for w in wfs:
        for s in w.steps:
            if s.id in seen and seen[s.id].to_dict() != s.to_dict():
                raise WorkflowError(f"step id {s.id!r} differs between composed workflows")
            seen.setdefault(s.id, s)
    order = {"review_gate": 0, "tool": 1, "assemble": 2, "llm_text": 3, "verify": 4}
    steps = sorted(seen.values(), key=lambda s: order[s.kind])        # stable: keeps first-appearance order inside a kind
    asm = tuple(s.id for s in steps if s.kind == "assemble")
    fixed = []
    for s in steps:
        dep = tuple(dict.fromkeys(d for d in s.depends_on if d in seen))
        if s.kind == "verify":
            dep = tuple(x.id for x in steps if x.kind != "verify")
        elif s.kind == "llm_text":
            dep = asm
        fixed.append(Step(**{**s.to_dict(), "depends_on": dep}))
    prep = [w.prepare for w in wfs if w.prepare]

    def prepare(req):
        out = {}
        for p in prep:
            out.update(p(req))
        return out
    schema = wfs[0].inputs_schema
    return Workflow(id=id or "+".join(w.id for w in wfs), title=" + ".join(w.title for w in wfs),
                    description=" ".join(w.description for w in wfs), inputs_schema=schema, steps=tuple(fixed),
                    outputs=tuple(dict.fromkeys(o for w in wfs for o in w.outputs)),
                    keywords=tuple(dict.fromkeys(k for w in wfs for k in w.keywords)),
                    requires=tuple(dict.fromkeys(r for w in wfs for r in w.requires)),
                    prepare=prepare if prep else None)


# ------------------------------------------------------------------------------------------------ routing
_ROUTES = ((re.compile(r"tick[- ]?and[- ]?tie|tie[- ]?out", re.I), "tick_and_tie"),
           (re.compile(r"buyer list|potential (buyers|acquirers)|list of buyers", re.I), "buyer_list"),
           (re.compile(r"earnings recap|recap of (the )?earnings|earnings summary", re.I), "earnings_recap"),
           (re.compile(r"company profile|one[- ]?pager|tear ?sheet", re.I), "company_profile"))


def route(request):
    """-> (Workflow | None, request). Explicit ``request.workflow`` wins, then a leading "/" command in the question,
    then a strong phrase in the question. Anything else returns None (the S6.0 placeholder keeps running)."""
    import dataclasses
    spec = request.workflow
    q = (request.question or "").strip()
    text = spec if spec else (q if q.startswith("/") else None)
    if text:
        text = text.strip()
        if not text.startswith("/"):
            text = " ".join("/" + p for p in re.split(r"[,\s+]+", text) if p)
        cmd = parse_command(text)
        if cmd["tickers"] and not request.tickers and not spec:
            request = dataclasses.replace(request, tickers=cmd["tickers"])
        return compose(cmd["workflows"]), request
    for rx, wid in _ROUTES:
        if rx.search(q):
            return CATALOG[wid], request
    return None, request
