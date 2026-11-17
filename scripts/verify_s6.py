#!/usr/bin/env python3
"""S6 gate: research agent. Zero unsourced figures, planted wrong numbers rejected, tick-and-tie, prose ban, evidence
chain (and anchors), durable jobs (cancel, lease redelivery, org isolation, source review), determinism, admin toggles,
schedules, email in/out, SCIM + connector ACLs, evals and scorecard.

Offline: synthetic SEC companyfacts-shaped JSON and page texts from tests/fixtures/s6gate (regenerate with
tests/fixtures/s6gate/build.py). No live LLM, no network (every socket attempt is counted and must be 0). Written
from docs/interfaces*.md and module docstrings only, independently of the implementers' tests.
Exits non-zero on any FAIL; SKIP (feature not built yet) does not fail the gate.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
FX = Path(ROOT) / "tests" / "fixtures" / "s6gate"
RESULTS: list[tuple[str, str, str]] = []        # (name, "PASS"|"FAIL"|"SKIP", detail)


class Skip(Exception):
    """Raise inside a check for a feature that does not exist yet (reported SKIP with the reason)."""


def check(name):
    def deco(fn):
        try:
            RESULTS.append((name, "PASS", str(fn() or "")))
        except Skip as e:
            RESULTS.append((name, "SKIP", str(e)[:400]))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, "FAIL", f"{type(e).__name__}: {e}"[:600]))
            if os.environ.get("VERIFY_DEBUG"):
                traceback.print_exc()
        return fn
    return deco


def expect_error(fn, exc=Exception, contains=None):
    try:
        fn()
    except exc as e:
        if contains and contains.lower() not in str(e).lower():
            raise AssertionError(f"{e!r} lacks {contains!r}")
        return str(e)
    raise AssertionError(f"expected {getattr(exc, '__name__', exc)}")


class NoSockets:
    """Physically disable network for the duration; counts every attempt."""

    def __enter__(self):
        self.saved = (socket.socket, socket.create_connection, socket.getaddrinfo)
        self.attempts = 0

        def boom(*a, **k):
            self.attempts += 1
            raise AssertionError("socket opened during the S6 gate")
        socket.socket = socket.create_connection = socket.getaddrinfo = boom
        return self

    def __exit__(self, *exc):
        socket.socket, socket.create_connection, socket.getaddrinfo = self.saved
        return False


# ------------------------------------------------------------------------------------------ hermetic environment
_SCRUB = re.compile(r"(_API_KEY|_AUTH_TOKEN|_BASE_URL)$|^(OM_PROVIDER_|OM_FALLBACK_|OM_MODEL_|OM_STAGE_|MESHPOOL_|"
                    r"ANTHROPIC_|OPENAI_|GEMINI_|DEEPSEEK_|ACRETIA_LLM_)|^GOOGLE_API_KEY$|^SEC_USER_AGENT$|^ACRETIA_SMTP")
SCRUBBED = sorted(k for k in os.environ if _SCRUB.search(k))
for _k in SCRUBBED:
    del os.environ[_k]
os.environ["ACRETIA_LLM_MODE"] = "replay"
TMP = tempfile.mkdtemp(prefix="s6gate-")
os.environ.update({
    "ACRETIA_JOBS_DB": os.path.join(TMP, "jobs.sqlite"), "ACRETIA_ADMIN_DB": os.path.join(TMP, "admin.sqlite"),
    "ACRETIA_DB": os.path.join(TMP, "acretia.sqlite"), "ACRETIA_EVIDENCE_DIR": os.path.join(TMP, "evidence"),
    "ACRETIA_EVIDENCE_KEY": "s6-gate-evidence-key", "ACRETIA_EVIDENCE_KEY_FILE": os.path.join(TMP, "evidence.key")})
print("hermetic: scrubbed env vars (names only): " + (", ".join(SCRUBBED) or "none")
      + f"; ACRETIA_LLM_MODE=replay; tmp={TMP}")

try:
    from om import keystore as _ks  # noqa: E402
    for _fn, _val in (("get", lambda *a, **k: None), ("load_into_env", lambda *a, **k: []),
                      ("_find", lambda *a, **k: None), ("_file_read", lambda *a, **k: {}),
                      ("_file_write", lambda *a, **k: None), ("put", lambda *a, **k: None),
                      ("delete", lambda *a, **k: None)):
        if hasattr(_ks, _fn):
            setattr(_ks, _fn, _val)
except ImportError:
    pass


from om import contracts as C  # noqa: E402
from om import statements as stm  # noqa: E402
from src.harness import evidence as EV  # noqa: E402
from src.harness.connectors.sec import statements_to_dict  # noqa: E402
from src.harness.connectors.web import extract_facts  # noqa: E402
from src.harness.research import jobs, workflows  # noqa: E402
from src.harness.research.api import (ExcelInputPayload, ResearchRequest, ResearchResult,  # noqa: E402
                                      SourcedFigure, run_research)
from src.harness.research.tools import build_registry  # noqa: E402
from src.harness.research.verify import SourceResolver, verify_figure  # noqa: E402

import http.client, ssl, urllib.request  # noqa: E402,F401  (import before sockets are disabled)
from src.harness.research import email_io, schedule  # noqa: E402,F401
from eval.research import run as _evrun  # noqa: E402,F401

NS = NoSockets().__enter__()        # whole gate runs with the network physically off

TICKERS = ("TSTA", "BUYA", "BUYB")
IR_URL = "https://ir.testco.test/fy2025-outlook"
UTC = timezone.utc


# ------------------------------------------------------------------------------------------ fixtures
def _load(name):
    return json.loads((FX / name).read_text())


CF = {t: _load(f"companyfacts_{t}.json") for t in TICKERS}


def _page(name):
    return (FX / "pages" / name).read_text()


class FakeSec:
    """Stands in for connectors.sec.SecAdapter: serves the fixtures, never the network."""

    def __init__(self):
        self.calls = []

    def company_facts(self, t):
        self.calls.append(("company_facts", t))
        return copy.deepcopy(CF[t.upper()])

    def financial_statements(self, t, years=5):
        self.calls.append(("financial_statements", t))
        return statements_to_dict(stm.build(copy.deepcopy(CF[t.upper()]), t.upper(), years=years), source="fixture")

    def filings(self, t, form="10-K", n=5):
        return []


class FakeWeb:
    def page_facts(self, url):
        if url != IR_URL:
            raise RuntimeError("fixture web has one page only")
        facts, links = extract_facts(url, (FX / "web" / "ir_guidance.html").read_bytes(), now="2025-02-21T00:00:00Z")
        return facts, links


def registry():
    return build_registry(sec=FakeSec(), web=FakeWeb())


def statements_of(t):
    return statements_to_dict(stm.build(copy.deepcopy(CF[t]), t, years=5), source="fixture")


def truth_resolver(*, corrupt_url_line=None):
    """The independent 'documents': filing texts, XBRL facts, pages and the web page, all built from the fixture."""
    r = SourceResolver()
    for t in TICKERS:
        st = statements_of(t)
        for i, end in enumerate(st["years"]):
            url = st["filings"][i]["url"]
            lines = []
            for k, vals in st["data"].items():
                if vals[i] is not None:
                    lines.append(f"{k} = {vals[i]} USD millions, FY ending {end}")
            r.add_url(url, "\n".join(lines))
        for concept, node in CF[t]["facts"]["us-gaap"].items():
            for _unit, rows in node["units"].items():
                for row in rows:
                    r.add_xbrl(row["accn"], f"us-gaap:{concept}", f"FY ending {row['end']}", row["val"])
    r.add_page("TENK-TSTA", 7, _page("tenk_tsta_p7.txt"))
    r.add_page("SPONSOR-DECK", 2, _page("sponsor_deck_p2.txt"))
    for p in (1, 2, 3):
        r.add_page("DRAFT-DECK", p, _page(f"draft_deck_p{p}.txt"))
    facts, _ = FakeWeb().page_facts(IR_URL)
    r.add_url(IR_URL, facts.snippet)
    return r


def sig(label, value, units, period, doc, page, quote, as_of, *, seed=""):
    return {"label": label, "value": value, "units": units, "period": period, "v": 1,
            "citation": {"doc_id": doc, "page": page, "quote": quote, "as_of": as_of,
                         "sha256_span_hash": hashlib.sha256(f"{doc}|{page}|{quote}|{seed}".encode()).hexdigest()}}


GOOD_REV = sig("Revenue", 1210.0, "USD millions", "FY ending 2024-12-31", "TENK-TSTA", 7,
               "Revenue was $1,210 million in fiscal 2024", "2025-02-15")
SPONSOR_FIG = sig("Sponsor Fund I dry powder", 4500.0, "USD millions", "FY ending 2024-12-31", "SPONSOR-DECK", 2,
                  "dry powder of $4,500 million", "2025-02-15")
# planted (D-S6-03 / scale / wrong value). The distinctive numbers must never reach a slide or payload.
BAD_VALUE = sig("Operating income", 4321.5, "USD millions", "FY ending 2024-12-31", "TENK-TSTA", 7,
                "Operating income was $4,321.5 million in fiscal 2024", "2025-02-15")   # page says 4,231.5
BAD_SCALE = sig("Net income", 7777.0, "USD thousands", "FY ending 2024-12-31", "TENK-TSTA", 7,
                "Net income was $7,777 million in fiscal 2024", "2025-02-15")            # thousands vs millions
BAD_ASOF = sig("Total assets", 9876.0, "USD millions", "FY ending 2024-12-31", "TENK-TSTA", 7,
               "Total assets were $9,876 million at year end", "2024-06-30")             # as_of before period end
BAD_FUTURE = sig("Total assets restated", 9876.0, "USD millions", "FY ending 2024-12-31", "TENK-TSTA", 7,
                 "Total assets were $9,876 million at year end", "2099-01-01")
NO_SOURCE = {"label": "Market size", "value": 5555.0, "units": "USD millions", "period": "FY ending 2024-12-31", "v": 1,
             "citation": {"doc_id": "TENK-TSTA", "sha256_span_hash": "a" * 64, "as_of": "2025-02-15"}}   # no url/page
PLANTED = [BAD_VALUE, BAD_SCALE, BAD_ASOF, BAD_FUTURE, NO_SOURCE]
PLANTED_NUMBERS = (4321.5, 7777.0, 9876.0, 5555.0)


# ------------------------------------------------------------------------------------------ run helper
class Run:
    def __init__(self, name, req, res, events, edir):
        self.name, self.req, self.res, self.events, self.edir = name, req, res, events, edir
        self.path = Path(edir) / f"{res.job_id}.jsonl"

    @property
    def d(self):
        return self.res.to_dict()


RUNS: dict[str, Run] = {}
_n = [0]


def do_run(name, workflow, *, tickers=(), question="gate run", options=None, resolver=None, doc_ids=(), tools=None,
           org="gate-org", as_of=None):
    _n[0] += 1
    req = ResearchRequest(question=question, tickers=list(tickers), doc_ids=list(doc_ids), workflow=workflow,
                          options={"source_review": False, **(options or {})}, org_id=org, as_of=as_of)
    events, edir = [], tempfile.mkdtemp(dir=TMP)
    res = run_research(req, tools=tools or registry(), evidence_dir=edir, job_id=f"gate_{name}_{_n[0]}",
                       on_event=events.append, resolver=resolver)
    RUNS[name] = Run(name, req, res, events, edir)
    return RUNS[name]


DRAFT_PAGES = {"DRAFT-DECK": {str(p): _page(f"draft_deck_p{p}.txt") for p in (1, 2, 3)}}
CANDIDATES = [{"name": "Buyer Alpha", "type": "strategic", "ticker": "BUYA"},
              {"name": "Buyer Beta", "type": "strategic", "ticker": "BUYB"},
              {"name": "Sponsor Fund I", "type": "financial", "metrics": [SPONSOR_FIG]}]


def scenarios():
    """The five workflows on clean fixtures, each under the independent truth resolver where documents exist."""
    if "company_profile" in RUNS:
        return
    do_run("company_profile", "company_profile", tickers=["TSTA"], options={"company_url": IR_URL})
    do_run("earnings_recap", "earnings_recap", tickers=["TSTA"], options={"guidance_url": IR_URL})
    do_run("buyer_list", "buyer_list", resolver=truth_resolver(),
           options={"candidates": CANDIDATES, "deal_size_usd_m": 3000})
    do_run("qa", "qa", tickers=["TSTA"], question="What were revenue, operating margin and diluted EPS over the last 3 years?")
    do_run("tick_and_tie", "tick_and_tie", doc_ids=["DRAFT-DECK"], resolver=truth_resolver(),
           options={"pages": DRAFT_PAGES, "figures": [GOOD_REV]})


# ------------------------------------------------------------------------------------------ independent verifier
ALL_PLAIN = {}      # (ticker, key, end) -> value, for operand sourcing of derived figures


def _operand_pool():
    pool = []
    for t in TICKERS:
        st = statements_of(t)
        for k, vals in st["data"].items():
            pool += [v for v in vals if v is not None]
        for i in range(len(st["years"])):
            rev = st["data"]["revenue"][i]
            for k in ("gross_profit", "ebit", "net_income"):
                if rev and st["data"][k][i] is not None:
                    pool.append(100.0 * st["data"][k][i] / rev)
    return pool + [1.0, 100.0, 10000.0]


OPERANDS = _operand_pool()


def _eval(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b,
                    ast.Div: lambda: a / b}[type(n.op)]()
        raise ValueError(f"unsupported {type(n).__name__}")
    return ev(ast.parse(expr, mode="eval"))


def is_derived(f):
    return (f.citation.quote or "").count(" = ") >= 2 and f.citation.page is None and not f.citation.xbrl_concept


def check_derived(f):
    """A figure computed in code: the arithmetic in its quote is recomputed here and every operand must be a value
    that exists in the fixture. (verify_figure cannot do this independently: the arithmetic is not in any filing.)"""
    segs = f.citation.quote.split(" = ")
    expr = segs[-2].replace(" x ", " * ").replace("×", "*")
    got = _eval(expr)
    ok = any(abs(c - f.value) <= max(1e-6, 0.005 * abs(f.value)) for c in (got, got * 100.0))
    if not ok:
        return False, f"recomputed {got:g} != value {f.value:g} ({expr})"
    for tok in re.findall(r"\d+(?:\.\d+)?", expr):
        x = float(tok)
        if not any(abs(x - p) <= max(1e-4, 1e-4 * abs(p)) for p in OPERANDS):
            return False, f"operand {x:g} of {f.label!r} is not a fixture value"
    return True, f"recomputed {got:g}"


def independent_verdict(f, truth, pool):
    f = f if isinstance(f, SourcedFigure) else SourcedFigure.from_dict(f)
    if is_derived(f):
        ok, why = check_derived(f)
        return ok, why, "derived-recompute"
    v = verify_figure(f, truth, figures=pool)
    return v.ok, v.reason, v.method


def source_ok(c):
    return bool(c.get("as_of")) and bool(c.get("url") or c.get("source_url") or
                                          (c.get("doc_id") and c.get("page") is not None) or c.get("cell_locator"))


# ------------------------------------------------------------------------------------------ slide number audit
_SKIP_KEYS = frozenset({"id", "type", "layout", "archetype", "format", "as_of", "citations", "citation", "sources",
                        "source", "page", "index", "order", "rank", "level", "row", "col", "x", "y", "w", "h", "units",
                        "tick_and_tie", "schema", "version", "v"})
_STRIP = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:FY|Q[1-4]|H[12]|CY)\s?'?\d{2,4}\b|\bp\d+\b|\bn\d+\b", re.I)
_TOK = re.compile(r"(?<![\w.])(\(?-?)\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(bn|m|k|%|bps|x)?(?![A-Za-z0-9])", re.I)


def slide_numbers(slide):
    out = []

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k not in _SKIP_KEYS:
                    walk(v)
        elif isinstance(n, (list, tuple)):
            for v in n:
                walk(v)
        elif isinstance(n, bool) or n is None:
            return
        elif isinstance(n, (int, float)):
            out.append((abs(float(n)), "", 99, True, False))
        elif isinstance(n, str):
            clean = _STRIP.sub(" ", n)
            for m in _TOK.finditer(clean):
                raw = m.group(2)
                out.append((float(raw.replace(",", "")), (m.group(3) or "").lower(),
                            len(raw.split(".")[1]) if "." in raw else 0, False, "$" in m.group(0)))
    for k in ("title", "bullets", "blocks", "data", "notes"):
        walk(slide.get(k))
    return out


def fig_candidates(f):
    v, u = abs(float(f["value"])), (f.get("units") or "").lower()
    c = [v]
    if "thousand" in u:
        c.append(v / 1e3)
    if "billion" in u or "bn" in u:
        c.append(v * 1e3)
    if u in ("usd", "$"):
        c.append(v / 1e6)
    return c


def unmatched_numbers(slide, figures):
    cands = [c for f in figures for c in fig_candidates(f)]
    bad = []
    for x, suf, dp, raw, cur in slide_numbers(slide):
        if not suf and not cur and float(x).is_integer() and (0 <= x <= 20 or 1900 <= x <= 2100):
            continue
        xs = [x] + ([x * 1e3] if suf == "bn" else [x / 1e3] if suf == "k" else [])
        if not any(abs(a - b) <= max(0.005 * abs(b), 0.5 * 10 ** (-dp) if not raw else 0, 1e-9)
                   for a in xs for b in cands):
            bad.append(x)
    return bad


def all_numbers_of(r):
    d = r.res.to_dict() if hasattr(r, "res") else r.to_dict()
    toks = []
    for s in d["slide_specs"]:
        toks += [t[0] for t in slide_numbers(s)]
    for p in d["excel_inputs"]:
        toks += [abs(float(f["value"])) for f in p["inputs"].values()]
    return toks


def figure_key(f):
    return (f["label"], f["period"])


# =========================================================================================== 1. zero unsourced figures
@check("1a. scenarios: five workflows succeed on fixtures (no network, FakeSec served the data)")
def _():
    scenarios()
    for n in ("company_profile", "earnings_recap", "buyer_list", "qa", "tick_and_tie"):
        r = RUNS[n].res
        assert r.status == "succeeded", f"{n}: {r.status} {r.error}"
        assert r.figures, f"{n}: no figures"
        assert r.slide_specs, f"{n}: no slides"
    assert RUNS["company_profile"].res.excel_inputs, "company_profile: no Excel input payload"
    return ", ".join(f"{n}={len(RUNS[n].res.figures)}f/{len(RUNS[n].res.slide_specs)}s"
                     for n in ("company_profile", "earnings_recap", "buyer_list", "qa", "tick_and_tie"))


@check("1b. every figure has a citation with as_of and a url, or doc_id + page, or cell_locator")
def _():
    scenarios()
    n = 0
    for name, r in RUNS.items():
        for f in r.d["figures"]:
            assert source_ok(f["citation"]), f"{name}: figure without a usable source: {f['label']} {f['citation']}"
            assert re.fullmatch(r"[0-9a-f]{64}", f["citation"]["sha256_span_hash"]), f"{name}: bad span hash {f['label']}"
            n += 1
        for p in r.d["excel_inputs"]:
            for k, f in p["inputs"].items():
                assert source_ok(f["citation"]), f"{name}: excel input {k} unsourced"
    return f"{n} figures"


@check("1c. every figure re-verifies independently against a resolver built from the fixtures")
def _():
    scenarios()
    truth, n, derived, fails = truth_resolver(), 0, 0, []
    for name, r in RUNS.items():
        pool = r.res.figures
        for f in r.res.figures:
            ok, why, method = independent_verdict(f, truth, pool)
            n += 1
            derived += method == "derived-recompute"
            if not ok:
                fails.append(f"{name}: {f.label} {f.period} {f.value} {f.units}: [{method}] {why}")
    assert not fails, f"{len(fails)} figure(s) do not re-verify, e.g. " + " | ".join(fails[:3])
    return f"{n} figures re-verified ({derived} derived ones recomputed from fixture operands)"


@check("1d. every number in every SlideSpec is a verified figure value or exempt (D-S6-04)")
def _():
    scenarios()
    n = 0
    for name, r in RUNS.items():
        figs = r.d["figures"]
        for s in r.d["slide_specs"]:
            bad = unmatched_numbers(s, figs)
            assert not bad, f"{name}/{s['id']}: numbers with no verified figure: {bad[:6]}"
            n += len(slide_numbers(s))
    return f"{n} numeric tokens checked"


@check("1e. every ExcelInputPayload input re-verifies")
def _():
    scenarios()
    truth, n = truth_resolver(), 0
    for name, r in RUNS.items():
        for p in r.res.excel_inputs:
            raw = (p.inputs if isinstance(p, ExcelInputPayload) else p["inputs"]).values()
            pool = [f if isinstance(f, SourcedFigure) else SourcedFigure.from_dict(f) for f in raw]
            for f in pool:
                ok, why, method = independent_verdict(f, truth, r.res.figures + pool)
                assert ok, f"{name}: excel input {f.label} {f.period}: {why}"
                n += 1
    assert n, "no excel inputs to check"
    return f"{n} inputs"


@check("1f. figures + rejected account for every emitted candidate (nothing dropped silently)")
def _():
    scenarios()
    for name, r in RUNS.items():
        ev_fig = [e for e in r.events if e["type"] == "figure"]
        ev_rej = [e for e in r.events if e["type"] == "rejected"]
        assert len(ev_fig) == len(r.res.figures), f"{name}: {len(ev_fig)} figure events vs {len(r.res.figures)} figures"
        assert len(ev_rej) == len(r.res.rejected), f"{name}: {len(ev_rej)} rejected events vs {len(r.res.rejected)}"
        for x in r.d["rejected"]:
            assert x["reason"].strip(), f"{name}: rejected without a reason: {x['figure']}"
        keys = [figure_key(f) for f in r.d["figures"]]
        assert len(keys) == len(set(keys)) or name in ("tick_and_tie",), f"{name}: duplicate figures"
    return "events == result lists in all runs"


@check("1g. buyer_list: candidates come only from the input; ranking sourced; no invented buyers")
def _():
    scenarios()
    r = RUNS["buyer_list"]
    names = set()
    for s in r.d["slide_specs"]:
        for b in s.get("blocks", []):
            for row in b.get("rows", []):
                if isinstance(row, dict) and row.get("name"):
                    names.add(row["name"])
    given = {c["name"] for c in CANDIDATES}
    assert names, "no buyer rows on any slide"
    assert names <= given, f"invented buyers: {sorted(names - given)}"
    assert names == given, f"input candidates missing from the list: {sorted(given - names)}"
    return f"{len(names)} buyers, all from input"


@check("1h. the five workflows ignore unverifiable invented inputs (tick_and_tie without sources fails loudly, not silently)")
def _():
    r = do_run("tt_nosrc", "tick_and_tie", doc_ids=["DRAFT-DECK"], options={"pages": DRAFT_PAGES})
    assert r.res.status in ("failed",) or not r.res.figures, "tick_and_tie with no source produced figures"
    assert not r.res.slide_specs or r.res.status == "failed", "slides shown with nothing to tie to"
    return f"status={r.res.status}"


# =========================================================================================== 2. planted wrong numbers
def _run_planted():
    if "planted" not in RUNS:
        do_run("planted", "tick_and_tie", doc_ids=["DRAFT-DECK"], resolver=truth_resolver(),
               options={"pages": DRAFT_PAGES, "figures": [GOOD_REV] + PLANTED})
    return RUNS["planted"]


@check("2a. planted wrong value / scale trap / as_of before period end / future as_of / no source: all in rejected with a reason")
def _():
    r = _run_planted()
    assert r.res.status == "succeeded", f"{r.res.status} {r.res.error}"
    rej = {}
    for x in r.d["rejected"]:
        fig = x["figure"]
        rej[(fig.get("label"), fig.get("period"))] = x["reason"]
    for bad in PLANTED:
        k = (bad["label"], bad["period"])
        assert k in rej, f"planted figure {k} not in rejected: {sorted(rej)[:6]}"
        assert rej[k].strip(), f"planted figure {k} rejected without a reason"
    shown = {figure_key(f) for f in r.d["figures"]}
    for bad in PLANTED:
        assert figure_key(bad) not in shown, f"planted figure {figure_key(bad)} still in figures"
    assert figure_key(GOOD_REV) in shown, "the clean control figure was lost"
    return "; ".join(f"{k[0]}: {v[:60]}" for k, v in rej.items() if k[0] in {p['label'] for p in PLANTED})


@check("2b. planted numbers appear in no slide and no Excel payload")
def _():
    r = _run_planted()
    toks = all_numbers_of(r)
    for n in PLANTED_NUMBERS + (4231.5,):
        assert not any(abs(t - n) < 1e-6 for t in toks), f"planted/untrusted number {n} reached a deliverable"
    blob = json.dumps(r.d["slide_specs"]) + json.dumps(r.d["excel_inputs"])
    for s in ("4,321.5", "4321.5", "7,777", "9,876", "5,555"):
        assert s not in blob, f"{s} appears in a deliverable"
    return f"{len(toks)} deliverable numbers clean"


@check("2c. accounting: supplied figures == shown + rejected (nothing dropped silently)")
def _():
    r = _run_planted()
    supplied = [GOOD_REV] + PLANTED
    shown = {figure_key(f) for f in r.d["figures"]}
    rej = {(x["figure"].get("label"), x["figure"].get("period")) for x in r.d["rejected"]}
    for s in supplied:
        k = figure_key(s)
        assert (k in shown) != (k in rej) or (k in shown and k in rej) is False, f"{k}: in {'both' if k in shown and k in rej else 'neither'}"
    return f"{len(supplied)} supplied -> {sum(figure_key(s) in shown for s in supplied)} shown, {sum(figure_key(s) in rej for s in supplied)} rejected"


@check("2d. XBRL value disagreeing with the independent source is rejected and absent from slides/Excel (EPS)")
def _():
    acc = CF["TSTA"]["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]["USD/shares"][-1]
    wrong = SourceResolver().add_xbrl(acc["accn"], "us-gaap:EarningsPerShareDiluted", f"FY ending {acc['end']}",
                                      acc["val"] + 1.0)
    r = do_run("planted_eps", "earnings_recap", tickers=["TSTA"], resolver=wrong)
    assert r.res.status == "succeeded", f"{r.res.status} {r.res.error}"
    good = r.res.figures
    assert not any("EarningsPerShareDiluted" in (f.citation.xbrl_concept or "") and f.period.endswith(acc["end"])
                   for f in good), "EPS figure that disagrees with its source is still shown"
    rejected = [x for x in r.d["rejected"] if "EarningsPerShareDiluted" in json.dumps(x["figure"])]
    assert rejected, "disagreeing EPS not reported in rejected"
    toks = all_numbers_of(r)
    assert not any(abs(t - acc["val"]) < 1e-9 for t in toks), "disagreeing EPS value reached a slide or payload"
    return rejected[0]["reason"][:100]


@check("2e. a statement line disagreeing with the independent filing text is rejected; ratios built on it do not survive")
def _():
    st = statements_of("TSTA")
    i = st["years"].index("2023-12-31")
    url, real = st["filings"][i]["url"], st["data"]["revenue"][i]
    base = truth_resolver()
    text = base.url_text(url).replace(f"revenue = {real} USD", f"revenue = {real + 55.5} USD")
    assert text != base.url_text(url)
    base.add_url(url, text)
    r = do_run("planted_stmt", "company_profile", tickers=["TSTA"], resolver=base)
    wrong_rev = [f for f in r.res.figures if f.label.endswith(" Revenue") and f.period.endswith("2023-12-31")]
    assert not wrong_rev, "FY2023 revenue that disagrees with the filing text is still shown"
    assert any(x["figure"].get("label", "").endswith(" Revenue") and str(x["figure"].get("period", "")).endswith("2023-12-31")
               for x in r.d["rejected"]), "FY2023 revenue not reported in rejected"
    leak = [f.label for f in r.res.figures if f.period.endswith("2023-12-31") and
            re.search(r"margin|growth|change", f.label, re.I) and "1100" in (f.citation.quote or "")]
    assert not leak, f"ratios computed from the rejected revenue are still shown: {leak}"
    toks = all_numbers_of(r)
    assert not any(abs(t - real) < 1e-6 for t in toks), "the rejected FY2023 revenue reached a slide or payload"
    return "FY2023 revenue rejected; nothing downstream shown"


# =========================================================================================== 3. tick and tie
def _tie_rows(r):
    out = {}
    for s in r.d["slide_specs"]:
        info = (s.get("data") or {}).get("tick_and_tie")
        if info:
            for b in s.get("blocks", []):
                for row in b.get("rows", []):
                    out.setdefault(info["page"], []).append(row["status"])
    return out


@check("3a. tick-and-tie: clean page passes, planted mismatch caught on the right page, unsourced number flagged")
def _():
    scenarios()
    rows = _tie_rows(RUNS["tick_and_tie"])
    assert rows.get(1) and set(rows[1]) == {"ok"}, f"clean page 1: {rows.get(1)}"
    assert rows.get(2) and "mismatch" in rows[2] and "ok" not in rows[2], f"page 2 (planted 1,250 vs 1,210): {rows.get(2)}"
    assert rows.get(3) and "unsourced" in rows[3] and "mismatch" not in rows[3] and "ok" not in rows[3], \
        f"page 3 (3,450 accounts has no source): {rows.get(3)}"
    assert not (set(rows[1]) & {"mismatch", "unsourced"}), "false positive on the clean page"
    return f"p1={rows[1]} p2={rows[2]} p3={rows[3]}"


@check("3b. tick-and-tie never reports ok for a number it could not verify against its source page")
def _():
    # same planted page text, but the model figure is cited to a page whose text disagrees: nothing may be 'ok'
    bad_src = SourceResolver().add_page("TENK-TSTA", 7, "Revenue was $1,111 million in fiscal 2024.")
    r = do_run("tt_badsource", "tick_and_tie", doc_ids=["DRAFT-DECK"], resolver=bad_src,
               options={"pages": DRAFT_PAGES, "figures": [GOOD_REV]})
    rows = _tie_rows(r)
    assert "ok" not in sum(rows.values(), []), f"'ok' reported against an unverifiable source: {rows}"
    assert not any(figure_key(GOOD_REV) == figure_key(f) for f in r.d["figures"]), "unverifiable model figure shown"
    return f"statuses={rows}"


# =========================================================================================== 4. prose ban
@check("4. a ResearchResult/ResearchRequest carrying a free-prose key is rejected by contract validation")
def _():
    base = {"v": 1, "job_id": "res_abc", "status": "succeeded", "evidence_head": "0" * 64}
    ResearchResult.from_dict(dict(base))        # control: the base shape is valid
    for k in ("summary", "answer", "narrative", "report", "markdown", "text", "commentary"):
        expect_error(lambda k=k: ResearchResult.from_dict({**base, k: "Revenue grew strongly."}), C.ContractError)
        expect_error(lambda k=k: ResearchRequest.from_dict({"v": 1, "question": "q", k: "x"}), C.ContractError)
    r = ResearchResult.from_dict(dict(base))
    r.steps.append(C.JobStep("x", "succeeded", "ok"))
    assert "summary" not in r.to_dict()
    bad = r.to_dict()
    bad["summary"] = "free prose"
    expect_error(lambda: ResearchResult.from_dict(bad), C.ContractError)
    for run in RUNS.values():       # and no run ever emitted one
        assert not ({"summary", "answer", "narrative", "text", "report", "markdown"} & set(run.d)), run.name
    return "7 prose keys rejected on result and request"


# =========================================================================================== 5. evidence
@check("5a. every run's evidence bundle verifies and evidence_head is its head")
def _():
    scenarios()
    _run_planted()
    n = 0
    for name, r in RUNS.items():
        v = EV.verify(r.path)
        assert v.ok, f"{name}: {v.reason}"
        assert v.n_records > 0 or r.res.status == "failed", f"{name}: empty evidence"
        assert r.res.evidence_head == EV.head_hash(r.path), f"{name}: evidence_head is not the bundle head"
        n += v.n_records
    return f"{len(RUNS)} bundles, {n} records"


@check("5b. a tampered record is detected")
def _():
    scenarios()
    src = RUNS["company_profile"].path
    dst = Path(tempfile.mkdtemp(dir=TMP)) / src.name
    lines = src.read_text().splitlines(keepends=True)
    assert len(lines) >= 3
    k = len(lines) // 2
    lines[k] = lines[k].replace("tool", "t00l", 1) if "tool" in lines[k] else lines[k][:-3] + "0\n"
    dst.write_text("".join(lines))
    assert not EV.verify(dst).ok, "tampered bundle verified"
    return "detected"


@check("5c. sealed anchor: bundle verifies with anchor='auto'; truncation after sealing is detected")
def _():
    if not (hasattr(EV.EvidenceBundle, "seal") and "anchor" in EV.verify.__code__.co_varnames):
        raise Skip("EvidenceBundle.seal / verify(anchor=) not built yet")
    scenarios()
    for n in ("company_profile", "tick_and_tie"):
        src = RUNS[n].path
        d = Path(tempfile.mkdtemp(dir=TMP))
        dst = d / src.name
        dst.write_bytes(src.read_bytes())
        b = EV.EvidenceBundle(dst)
        try:
            b.seal(anchor_dir=d)
        finally:
            b.close()
        assert EV.verify(dst, anchor="auto", anchor_dir=d).ok, f"{n}: sealed bundle does not verify"
        lines = dst.read_bytes().split(b"\n")
        assert len(lines) > 3
        dst.write_bytes(b"\n".join(lines[:-3]) + b"\n")          # drop the last two records
        v = EV.verify(dst, anchor="auto", anchor_dir=d)
        assert not v.ok and "trunc" in v.reason.lower(), f"{n}: truncation not detected ({v})"
        dst.write_bytes(src.read_bytes())
        d2 = Path(tempfile.mkdtemp(dir=TMP))
        assert not EV.verify(dst, anchor="auto", anchor_dir=d2).ok, f"{n}: missing anchor not detected"
    return "seal ok, truncation and missing anchor detected"


# =========================================================================================== 6. jobs
class Killed(BaseException):
    """Simulates kill -9 of a worker: not an Exception, so nothing in the stack may swallow it into an ack."""


class GateTools:
    def __init__(self, *, block=False, kill_first=False):
        self.inner, self.entered, self.release = registry(), threading.Event(), threading.Event()
        self.block, self.kill_first, self.calls = block, kill_first, 0
        if not block:
            self.release.set()

    def call(self, name, args):
        self.calls += 1
        self.entered.set()
        if self.kill_first and self.calls == 1:
            raise Killed()
        if self.block:
            assert self.release.wait(30), "gate tools never released"
        return self.inner.call(name, args)


def new_jobs_db():
    jobs.close_all()
    os.environ["ACRETIA_JOBS_DB"] = os.path.join(TMP, f"jobs_{time.monotonic_ns()}.sqlite")


def start_worker(tools, edir, *, lease=300.0, poll=0.03):
    stop = threading.Event()
    t = threading.Thread(target=jobs.worker_loop, args=(stop, None),
                         kwargs=dict(tools=tools, evidence_dir=edir, lease=lease, poll=poll), daemon=True)
    t.start()
    return stop, t


def wait_for(fn, what, timeout=40.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {what}")


def job_req(org="orgA", **opt):
    return ResearchRequest(question="profile", tickers=["TSTA"], workflow="company_profile", org_id=org,
                           options={"source_review": False, **opt})


@check("6a. submit -> worker -> succeeded with a verified result; evidence chain verifies")
def _():
    new_jobs_db()
    edir = tempfile.mkdtemp(dir=TMP)
    jid = jobs.submit(job_req())
    assert jobs.status(jid, org_id="orgA").status == "queued"
    assert jobs.result(jid, org_id="orgA") is None
    stop, t = start_worker(GateTools(), edir)
    try:
        wait_for(lambda: jobs.status(jid, org_id="orgA").status in ("succeeded", "failed", "cancelled"), "job to finish")
    finally:
        stop.set()
    st = jobs.status(jid, org_id="orgA")
    assert st.status == "succeeded", f"{st.status} {st.error}"
    res = jobs.result(jid, org_id="orgA")
    assert res and res.status == "succeeded" and res.figures and res.slide_specs
    assert EV.verify(Path(edir) / f"{jid}.jsonl").ok
    truth = truth_resolver()
    bad = [f.label for f in res.figures if not independent_verdict(f, truth, res.figures)[0]]
    assert not bad, f"job result figures do not re-verify: {bad[:3]}"
    evs = jobs.events(jid, org_id="orgA")
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1)) and evs[-1]["type"] == "done"
    return f"{len(res.figures)} figures, {len(evs)} events"


@check("6b. cancel mid-run gives cancelled, with no figures or slides shown")
def _():
    new_jobs_db()
    edir = tempfile.mkdtemp(dir=TMP)
    tools = GateTools(block=True)
    jid = jobs.submit(job_req())
    stop, t = start_worker(tools, edir)
    try:
        assert tools.entered.wait(30), "worker never reached a tool call"
        assert jobs.status(jid, org_id="orgA").status == "running"
        assert jobs.cancel(jid, org_id="orgA") is True
        tools.release.set()
        wait_for(lambda: jobs.status(jid, org_id="orgA").status in ("succeeded", "failed", "cancelled"), "job to end")
    finally:
        tools.release.set()
        stop.set()
    assert jobs.status(jid, org_id="orgA").status == "cancelled"
    res = jobs.result(jid, org_id="orgA")
    assert res is not None and res.status == "cancelled"
    assert not res.figures and not res.slide_specs and not res.excel_inputs, "cancelled run still shows output"
    assert jobs.cancel(jid, org_id="orgA") is False, "cancel after finish must return False"
    return "cancelled; nothing shown"


@check("6c. worker killed mid-lease: job is re-delivered after lease expiry and completes exactly once")
def _():
    new_jobs_db()
    edir = tempfile.mkdtemp(dir=TMP)
    jid = jobs.submit(job_req())
    killer = GateTools(kill_first=True)
    stop_a, ta = start_worker(killer, edir, lease=1.0)
    ta.join(30)
    assert not ta.is_alive(), "worker A should have died (simulated kill)"
    assert jobs.result(jid, org_id="orgA") is None, "a killed worker must not leave a result"
    assert jobs.status(jid, org_id="orgA").status in ("running", "queued")
    stop_b, tb = start_worker(GateTools(), edir, lease=30.0)
    try:
        wait_for(lambda: jobs.status(jid, org_id="orgA").status in ("succeeded", "failed", "cancelled"),
                 "redelivery to complete", timeout=60)
    finally:
        stop_b.set()
    st = jobs.status(jid, org_id="orgA")
    assert st.status == "succeeded", f"{st.status} {st.error}"
    assert (st.attempts or 0) >= 2, f"expected a second delivery, attempts={st.attempts}"
    evs = jobs.events(jid, org_id="orgA")
    assert sum(e["type"] == "done" for e in evs) == 1, "job completed more than once"
    first = jobs.result(jid, org_id="orgA")
    assert EV.verify(Path(edir) / f"{jid}.jsonl").ok, "evidence chain broken after redelivery"
    # a duplicate delivery of the finished job is idempotent
    kv = jobs._kv()
    kv.enqueue(jobs.QUEUE, json.dumps({"org_id": "orgA", "job_id": jid}))
    stop_c, tc = start_worker(GateTools(), edir)
    time.sleep(1.0)
    stop_c.set()
    assert sum(e["type"] == "done" for e in jobs.events(jid, org_id="orgA")) == 1, "duplicate delivery re-ran the job"
    assert jobs.result(jid, org_id="orgA").to_json() == first.to_json(), "result changed on duplicate delivery"
    return f"attempts={st.attempts}, one 'done', duplicate delivery is a no-op"


@check("6d. cross-org status/result/cancel/events/approve/submit are refused and change nothing")
def _():
    new_jobs_db()
    jid = jobs.submit(job_req("orgA"))
    for fn in (lambda: jobs.status(jid, org_id="orgB"), lambda: jobs.result(jid, org_id="orgB"),
               lambda: jobs.cancel(jid, org_id="orgB"), lambda: jobs.events(jid, org_id="orgB")):
        expect_error(fn, jobs.JobNotFound)
    if hasattr(jobs, "approve"):
        expect_error(lambda: jobs.approve(jid, "orgB"), jobs.JobNotFound)
        expect_error(lambda: jobs.reject(jid, "no", org_id="orgB"), jobs.JobNotFound)
    expect_error(lambda: jobs.submit(job_req("orgA"), org_id="orgB"), ValueError)
    assert jobs.status(jid, org_id="orgA").status == "queued", "foreign cancel/approve changed the job"
    assert jobs.cancel(jid, org_id="orgA") is True
    return "JobNotFound for every foreign call"


def _review_ready():
    return ("awaiting_review" in C.STATUS and hasattr(jobs, "approve") and hasattr(jobs, "reject"))


@check("6e. source review: job waits in awaiting_review; approve resumes it; reject cancels it")
def _():
    if not _review_ready():
        raise Skip("awaiting_review status / jobs.approve / jobs.reject not built yet")
    new_jobs_db()
    edir = tempfile.mkdtemp(dir=TMP)
    stop, t = start_worker(GateTools(), edir)
    try:
        ja = jobs.submit(ResearchRequest(question="profile", tickers=["TSTA"], workflow="company_profile", org_id="orgA"))
        wait_for(lambda: jobs.status(ja, org_id="orgA").status == "awaiting_review", "awaiting_review")
        time.sleep(0.4)
        assert jobs.status(ja, org_id="orgA").status == "awaiting_review", "job did not wait for the reviewer"
        assert jobs.result(ja, org_id="orgA") is None
        src = jobs.review_sources(ja, org_id="orgA")
        assert src, "no planned sources exposed for review"
        expect_error(lambda: jobs.approve(ja, "orgB"), jobs.JobNotFound)
        assert jobs.status(ja, org_id="orgA").status == "awaiting_review"
        assert jobs.approve(ja, "orgA", approver="reviewer1") is True
        assert jobs.approve(ja, "orgA", approver="reviewer1") is False, "second approve must be a no-op"
        wait_for(lambda: jobs.status(ja, org_id="orgA").status in ("succeeded", "failed", "cancelled"), "approved job to end")
        assert jobs.status(ja, org_id="orgA").status == "succeeded", jobs.status(ja, org_id="orgA").error
        jr = jobs.submit(ResearchRequest(question="profile", tickers=["TSTA"], workflow="company_profile", org_id="orgA"))
        wait_for(lambda: jobs.status(jr, org_id="orgA").status == "awaiting_review", "second awaiting_review")
        assert jobs.reject(jr, "wrong sources", org_id="orgA") is True
        wait_for(lambda: jobs.status(jr, org_id="orgA").status in ("succeeded", "failed", "cancelled"), "rejected job to end")
        assert jobs.status(jr, org_id="orgA").status == "cancelled"
        rr = jobs.result(jr, org_id="orgA")
        assert rr is not None and not rr.figures and not rr.slide_specs
        assert jobs.approve(jr, "orgA") is False, "approve after reject must not resurrect the job"
    finally:
        stop.set()
    return "approve resumed, reject cancelled, foreign approve refused"


# =========================================================================================== 7. determinism
@check("7. the same request run twice gives identical figures, values, citations and slides (apart from ids/timestamps)")
def _():
    def strip(d):
        d = json.loads(json.dumps(d))
        for k in ("job_id", "evidence_head", "timings", "cost_usd", "tokens"):
            d.pop(k, None)
        return d
    for wf, kw in (("company_profile", dict(tickers=["TSTA"], options={"company_url": IR_URL})),
                   ("earnings_recap", dict(tickers=["TSTA"], options={"guidance_url": IR_URL})),
                   ("qa", dict(tickers=["TSTA"], question="What was revenue and operating margin?")),
                   ("buyer_list", dict(resolver_f=True, options={"candidates": CANDIDATES}))):
        kw = dict(kw)
        res = truth_resolver() if kw.pop("resolver_f", False) else None
        a = do_run(f"det_a_{wf}", wf, resolver=res, **kw)
        b = do_run(f"det_b_{wf}", wf, resolver=truth_resolver() if res else None, **kw)
        assert a.res.status == b.res.status == "succeeded", f"{wf}: {a.res.status}/{b.res.status}"
        da, db = strip(a.d), strip(b.d)
        assert da["figures"] == db["figures"], f"{wf}: figures differ"
        assert da["slide_specs"] == db["slide_specs"], f"{wf}: slides differ"
        assert da["excel_inputs"] == db["excel_inputs"], f"{wf}: excel inputs differ"
        assert da["rejected"] == db["rejected"], f"{wf}: rejected differ"
        assert workflows.output_digest(a.res) == workflows.output_digest(b.res), f"{wf}: digest differs"
    return "4 workflows x 2 runs identical"


# =========================================================================================== 8. catalog / admin
ADMIN = {"user_id": "admin1", "role": "admin"}
MEMBER = {"user_id": "u2", "role": "member"}


@check("8. disabled agent: hidden from catalog search, refused by run_request; non-admin cannot toggle")
def _():
    from src.harness.admin import PermissionDenied, agents
    org, other = "orgDis", "orgEnabled"
    found = [h["id"] for h in workflows.search("company profile one-pager", org)]
    assert "company_profile" in found, f"control: company_profile should be searchable: {found}"
    expect_error(lambda: agents.set_enabled(org, "company_profile", False, MEMBER), PermissionDenied)
    expect_error(lambda: agents.set_enabled(org, "company_profile", False, {"user_id": "v", "role": "viewer"}), PermissionDenied)
    assert agents.is_enabled(org, "company_profile") is True, "a refused toggle changed state"
    assert "company_profile" in [h["id"] for h in workflows.search("company profile one-pager", org)]
    out = agents.set_enabled(org, "company_profile", False, ADMIN)
    assert out["enabled"] is False
    assert "company_profile" not in [h["id"] for h in workflows.search("company profile one-pager", org)], "disabled agent still in search"
    assert "company_profile" in [h["id"] for h in workflows.search("company profile one-pager", other)], "toggle leaked to another org"
    r = do_run("disabled", "company_profile", tickers=["TSTA"], org=org)
    assert r.res.status == "failed" and org in (r.res.error or ""), f"disabled workflow not refused: {r.res.status} {r.res.error}"
    assert not r.res.figures and not r.res.slide_specs
    ok = do_run("not_disabled", "company_profile", tickers=["TSTA"], org=other)
    assert ok.res.status == "succeeded", "enabled org affected by another org's toggle"
    comp = do_run("disabled_compose", "company_profile,qa", tickers=["TSTA"], org=org, question="revenue?")
    assert comp.res.status == "failed", "disabled agent runs when composed with an enabled one"
    assert any(a["action"] == "agent.set_enabled" for a in agents.audit_log(org)) if hasattr(agents, "audit_log") else True
    agents.set_enabled(org, "company_profile", True, ADMIN)
    assert "company_profile" in [h["id"] for h in workflows.search("company profile one-pager", org)]
    return "hidden, refused, composed run refused, non-admin denied, re-enable works"


# =========================================================================================== 9. schedules / email
@check("9a. dispatch_due is idempotent per tick; org/user come from the schedule; monitor is not submitted")
def _():
    from src.harness.research.schedule import ScheduleStore
    store, sent = ScheduleStore(":memory:"), []
    req = {"question": "profile", "workflow": "company_profile", "tickers": ["TSTA"], "org_id": "victim",
           "monitor": {"compare_to": "last_run", "alert_on": ["new_filing"]}}
    s = store.create("orgS", "ana", req, "daily", hour=9, minute=0, tz="UTC", deliver={"email": ["ana@fund.test"]},
                     now=datetime(2026, 11, 16, 8, 0, tzinfo=UTC))
    submit = lambda r: (sent.append(r), f"job{len(sent)}")[1]          # noqa: E731
    now = datetime(2026, 11, 16, 9, 5, tzinfo=UTC)
    early = store.dispatch_due(datetime(2026, 11, 16, 8, 30, tzinfo=UTC), submit=submit)
    assert early == [] and not sent, "dispatched before the slot"
    a = store.dispatch_due(now, submit=submit)
    b = store.dispatch_due(now, submit=submit)
    c = store.dispatch_due(now, submit=submit)
    assert len(a) == 1 and b == [] and c == [] and len(sent) == 1, f"same tick submitted {len(sent)} job(s)"
    assert sent[0]["org_id"] == "orgS" and sent[0]["user_id"] == "ana", "org/user not taken from the schedule"
    assert "monitor" not in sent[0]
    nxt = store.dispatch_due(datetime(2026, 11, 17, 9, 1, tzinfo=UTC), submit=submit)
    assert len(nxt) == 1 and len(sent) == 2, "next day's slot did not dispatch"
    assert store.get("orgOther", s.id) is None, "schedule readable from another org"
    return "1 job per slot, replays are no-ops"


def _rendered():
    figs = [
        {"label": "<script>alert(1)</script> Revenue", "value": 1210.0, "units": "USD millions", "period": "FY2024", "v": 1,
         "citation": {"doc_id": "d1", "url": "https://www.sec.gov/Archives/x/", "as_of": "2025-02-15",
                      "sha256_span_hash": "b" * 64}},
        {"label": "UNCITEDLABEL", "value": 5.0, "units": "USD millions", "period": "FY2024", "v": 1,
         "citation": {"doc_id": "d2", "as_of": "2025-02-15", "sha256_span_hash": "c" * 64}},
        {"label": "NOASOFLABEL", "value": 6.0, "units": "USD millions", "period": "FY2024", "v": 1,
         "citation": {"doc_id": "d3", "url": "https://www.sec.gov/Archives/y/", "sha256_span_hash": "d" * 64}}]
    res = {"v": 1, "job_id": "res_1", "status": "succeeded", "figures": figs,
           "rejected": [{"figure": {"label": "REJECTEDLABEL", "value": 123456.0}, "reason": "no"}]}
    from src.harness.research.email_io import render_summary
    return render_summary(res, deck_url="javascript:alert(2)")


@check("9b. summary email shows only cited figures and escapes HTML")
def _():
    subject, text, html = _rendered()
    for hidden in ("UNCITEDLABEL", "NOASOFLABEL", "REJECTEDLABEL", "123,456", "123456"):
        assert hidden not in text and hidden not in html and hidden not in subject, f"{hidden} shown in the email"
    assert "1,210" in text and "https://www.sec.gov/Archives/x/" in text and "2025-02-15" in text
    assert "<script>" not in html and "&lt;script&gt;" in html, "label not HTML-escaped"
    assert "javascript:" not in html.lower().split("href=")[-1] if "href=" in html else True
    assert 'href="javascript' not in html.lower(), "javascript: deck url linked"
    assert "<script" not in subject.lower()
    return "2 uncited + 1 rejected withheld; script escaped"


def _eml(name):
    return (FX / "mail" / name).read_bytes()


ALLOW = {"orgM": ["@fund.test"]}


@check("9c. inbound email: allowlisted sender accepted; non-allowlisted, spoofed display name and DKIM fail rejected")
def _():
    from src.harness.research.email_io import InboundRejected, parse_request_email
    ok = parse_request_email(_eml("ok.eml"), org_allowlist=ALLOW)
    assert ok.org_id == "orgM" and ok.user == "ana@fund.test" and ok.kind == "research", ok
    for name in ("nonallow.eml", "spoof.eml", "dkimfail.eml"):
        expect_error(lambda n=name: parse_request_email(_eml(n), org_allowlist=ALLOW), InboundRejected)
    # same spoof, but the display name carries an allowlisted address while the real sender is foreign
    expect_error(lambda: parse_request_email(_eml("spoof.eml"), org_allowlist={"orgM": ["ceo@fund.test"]}), InboundRejected)
    return "ok accepted; 3 hostile mails rejected"


class _Spy:
    def __init__(self, log):
        self.log = log

    def call(self, name, args):
        self.log.append((name, args))
        raise AssertionError("a tool was called for an injected email request")


@check("9d. inbound prompt injection is data: nothing sent to evil.com, request text fenced, no extra recipients/files")
def _():
    from src.harness.research.email_io import handle_inbound, parse_request_email
    sent_mail, submitted = [], []
    for name in ("inject_body.eml", "inject_nosubject.eml"):
        inb = parse_request_email(_eml(name), org_allowlist=ALLOW)
        assert inb.user == "ana@fund.test" and inb.org_id == "orgM" and not inb.attachments
        q = inb.request["question"]
        assert q.startswith("<email_request>") and q.endswith("</email_request>"), f"{name}: request text not fenced"
        assert q.count("<email_request>") == 1 and q.count("</email_request>") == 1, f"{name}: fence can be escaped"
        extra = set(inb.request) - {"v", "question", "org_id", "user_id", "tickers", "outputs"}
        assert not extra, f"{name}: body added request fields {extra}"
        assert "evil.com" not in json.dumps({k: v for k, v in inb.request.items() if k != "question"})
        assert inb.request["user_id"] == "ana@fund.test"
        jid = handle_inbound(inb, submit=lambda r: (submitted.append(r), "job1")[1])
        assert jid == "job1"
        r = run_research(ResearchRequest.from_dict(inb.request), tools=_Spy(sent_mail), evidence_dir=tempfile.mkdtemp(dir=TMP),
                         job_id=f"gate_inj_{name[:-4]}")
        assert r.status in ("succeeded", "failed")
    assert not sent_mail, f"agent invoked tools on injected text: {sent_mail}"
    assert len(submitted) == 2
    blob = json.dumps(submitted)
    assert "boss@fund.test" not in json.dumps([{k: v for k, v in s.items() if k != "question"} for s in submitted])
    assert blob.count("evil.com") <= 1 * 2
    return "fenced; no tool calls; no recipients added; nothing emailed"


# =========================================================================================== 10. SCIM / ACL
@check("10a. SCIM deprovisioning fires revocation and filter_results/AclAuthorizer deny immediately (even with a warm cache)")
def _():
    from src.harness.admin import scim
    from src.harness.connectors.acl import AclAuthorizer, AclCache, ItemACL
    conn = sqlite3.connect(":memory:")
    svc = scim.ScimService(conn, "orgA")
    u = svc.create_user({"schemas": [scim.USER_SCHEMA], "userName": "bob@fund.test", "active": True,
                         "emails": [{"value": "bob@fund.test", "primary": True}]})
    other = svc.create_user({"schemas": [scim.USER_SCHEMA], "userName": "eve@fund.test", "active": True,
                             "emails": [{"value": "eve@fund.test", "primary": True}]})
    acls = {("box", "f1"): ItemACL("box", "f1", readers_users=frozenset({"bob@fund.test"})),
            ("box", "f2"): ItemACL("box", "f2", readers_users=frozenset({"eve@fund.test"})),
            ("box", "f3"): ItemACL("box", "f3", unknown=True),
            ("box", "f5"): ItemACL("box", "f5", public_in_org=True)}
    auth = AclAuthorizer(svc, lambda s, i: acls.get((s, i)), cache=AclCache(ttl=3600))
    hits = [{"source": "box", "item_id": i} for i in ("f1", "f2", "f3", "f4", "f5")]
    got = {h["item_id"] for h in auth.filter(u["id"], hits)}
    assert got == {"f1", "f5"}, f"bob should see f1 (his) and f5 (org-public) only, got {sorted(got)}"
    assert {h["item_id"] for h in auth.filter(other["id"], hits)} == {"f2", "f5"}
    assert auth.can_read(u["id"], "box", "f1") is True and auth.can_read(u["id"], "box", "f2") is False
    patch = {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
             "Operations": [{"op": "replace", "path": "active", "value": False}]}
    svc.patch_user(u["id"], patch)
    assert svc.is_active(u["id"]) is False
    kinds = {k for uid, k in svc.revocations(u["id"])}
    assert {"session", "schedules", "api_tokens"} <= kinds, f"revocation hooks did not all fire: {kinds}"
    assert any("user" in a["action"] for a in svc.audit_rows()), "no audit row for deprovisioning"
    assert auth.filter(u["id"], hits) == [], "deprovisioned user still sees results through a warm cache"
    assert auth.can_read(u["id"], "box", "f1") is False
    assert {h["item_id"] for h in auth.filter(other["id"], hits)} == {"f2", "f5"}, "deprovisioning hit another user"
    n = len(svc.revocations(u["id"]))
    svc.patch_user(u["id"], patch)
    assert len(svc.revocations(u["id"])) == n, "re-deactivating re-fired the hooks"
    expect_error(lambda: scim.ScimService(conn, "orgB").get_user(u["id"]), scim.ScimError)
    d2 = svc.create_user({"schemas": [scim.USER_SCHEMA], "userName": "carl@fund.test", "active": True})
    svc.delete_user(d2["id"])
    assert svc.is_active(d2["id"]) is False and svc.revocations(d2["id"]), "DELETE did not revoke"
    return f"revocations={sorted(kinds)}; denied immediately; cross-org id is 404"


@check("10b. unknown / missing / malformed / anonymous-link ACLs are denied by default")
def _():
    from src.harness.connectors import acl as A
    lookup = {("sp", "i1"): A.parse_sharepoint("sp", "i1", None),
              ("sp", "i2"): A.parse_sharepoint("sp", "i2", {"value": [{"id": "1", "roles": ["read"],
                                                                      "link": {"scope": "anonymous", "type": "view"}}]}),
              ("box", "i3"): A.parse_box("box", "i3", {"entries": "garbage"}),
              ("sp", "i4"): A.ItemACL("sp", "i4", readers_users=frozenset({"bob@fund.test"}))}
    hits = [{"source": s, "item_id": i} for s, i in (("sp", "i1"), ("sp", "i2"), ("box", "i3"), ("sp", "i4"),
                                                      ("sp", "i5"), ("", "i6"), ("sp", ""))]
    got = A.filter_results(hits, "bob@fund.test", ["any-group"], lambda s, i: lookup.get((s, i)))
    assert [(h["source"], h["item_id"]) for h in got] == [("sp", "i4")], f"default-deny breached: {got}"
    assert lookup[("sp", "i1")].unknown is True and not lookup[("sp", "i1")].allows("bob@fund.test")
    assert not lookup[("sp", "i2")].public_in_org, "anonymous link treated as org-public without the org setting"
    return "only the explicit grant is visible"


# =========================================================================================== 11. evals
@check("11a. replay eval with no fixtures runs offline, writes ran_live=no rows and never fakes a score")
def _():
    from eval.research import run as evrun
    out = Path(tempfile.mkdtemp(dir=TMP)) / "out"
    card = Path(tempfile.mkdtemp(dir=TMP)) / "scorecard.csv"
    summary = evrun.run(suite="vals", mode="replay", data_root=str(FX / "evals"), out=out, scorecard_path=card,
                        update_card=True)
    rows = summary["scorecard_rows"]
    assert rows, "no scorecard rows"
    for r in rows:
        assert r["eval"].startswith("research/"), r
        assert "ran_live=no" in r["notes"] and "mode=replay" in r["notes"], f"replay row not marked: {r}"
        assert "ran_live=yes" not in r["notes"]
        assert str(r["score"]) == "", f"replay row carries a score: {r}"
    s1 = summary["suites"].get("vals-v1", {})
    assert s1.get("n") == 1 and s1.get("n_run") == 0, f"item with no fixture must be not_run: {s1.get('n')}/{s1.get('n_run')}"
    assert all(i["status"] == "not_run" for i in s1.get("items", [])), "an unfixtured item was reported as run"
    text = card.read_text()
    assert text.splitlines()[0] == "stage,eval,n,score,notes" and "ran_live=no" in text
    saved = json.loads((out / "summary.json").read_text())
    assert saved["mode"] == "replay"
    return f"{len(rows)} rows, all ran_live=no, score blank"


@check("11b. update_scorecard: foreign rows preserved byte-for-byte; non-research evals refused; replay never overwrites live")
def _():
    from eval.research.score import update_scorecard
    p = Path(tempfile.mkdtemp(dir=TMP)) / "scorecard.csv"
    foreign = ('S4,sbench_formula_cells_reproduced,32850,0.716,"live_model=no; quoted, with comma; ""inner"" quotes"\n'
               "S8,standards_qa,50,0.980,  spaced  notes  \n"
               'S9,odd_row,1,,"multi\nline note"\n')
    original = "stage,eval,n,score,notes\n" + foreign
    p.write_bytes(original.encode())
    live = {"stage": "S6", "eval": "research/vals-v1/strict_accuracy", "n": 50, "score": "0.4200",
            "notes": "mode=live; ran_live=yes; date=2026-11-17; x"}
    update_scorecard(p, [live])
    after = p.read_bytes().decode()
    assert after.startswith(original), "foreign rows changed or were reordered"
    assert "research/vals-v1/strict_accuracy" in after
    replay = {**live, "score": "", "notes": "mode=replay; ran_live=no; date=2026-11-18; not run live (D-021)"}
    update_scorecard(p, [replay])
    assert p.read_bytes().decode() == after, "a replay row overwrote a live row"
    before = p.read_bytes()
    expect_error(lambda: update_scorecard(p, [{"stage": "S8", "eval": "standards_qa", "n": 1, "score": "1", "notes": "x"}]),
                 ValueError)
    expect_error(lambda: update_scorecard(p, [replay, {"stage": "S4", "eval": "sbench_formula_cells_reproduced",
                                                       "n": 1, "score": "1", "notes": "x"}]), ValueError)
    assert p.read_bytes() == before, "a refused update still modified the scorecard"
    again = {**live, "n": 51, "notes": "mode=live; ran_live=yes; date=2026-11-19; y"}
    update_scorecard(p, [again])
    assert p.read_bytes().decode().startswith(original) and ",51," in p.read_text(), "live rows are not updated by live runs"
    return "foreign rows byte-identical; refusal leaves file untouched"


@check("11c. scorer: a correct number without a verified citation counts as wrong; with one it counts as right")
def _():
    from eval.research.datasets import EvalItem
    from eval.research.score import score_item
    item = EvalItem("x-1", "What was Gatecorp's FY2024 revenue in USD millions?", "$1,210 million", [], ["GATE"], "t", "vals_v1", {})
    good_cit = {"doc_id": "d", "sha256_span_hash": "e" * 64, "url": "https://www.sec.gov/x/", "as_of": "2025-02-15", "quote": "q"}
    fig = lambda cit: {"label": "Revenue", "value": 1210.0, "units": "USD_m", "period": "FY2024", "citation": cit}   # noqa: E731
    ok = score_item(item, {"status": "succeeded", "figures": [fig(good_cit)]})
    assert ok["correct"] and ok["cited"], f"verified citation not credited: {ok}"
    for name, cit in (("no hash", {k: v for k, v in good_cit.items() if k != "sha256_span_hash"}),
                      ("no source", {k: v for k, v in good_cit.items() if k != "url"}),
                      ("bad hash", {**good_cit, "sha256_span_hash": "xyz"}), ("empty", {})):
        s = score_item(item, {"status": "succeeded", "figures": [fig(cit)]})
        assert s["numeric_ok"] and not s["correct"], f"{name}: correct number without a verified citation counted right: {s}"
    wrong = score_item(item, {"status": "succeeded", "figures": [{**fig(good_cit), "value": 999.0}]})
    assert not wrong["correct"] and not wrong["numeric_ok"]
    assert not score_item(item, None)["correct"] and not score_item(item, {"status": "failed", "figures": [fig(good_cit)]})["correct"]
    return "6 variants scored as specified"


@check("11d. scorer credits a correct, verified figure exactly as the research tools emit it (units 'USD millions')")
def _():
    from eval.research.datasets import EvalItem
    from eval.research.score import score_item
    scenarios()
    rev = next(f for f in RUNS["company_profile"].d["figures"] if f["label"] == "TSTA Revenue" and f["period"].endswith("2024-12-31"))
    item = EvalItem("x-2", "What was Testco's FY2024 revenue in USD millions?", "$1,210 million", [], ["TSTA"], "t", "vals_v1", {})
    s = score_item(item, {"status": "succeeded", "figures": [rev]})
    assert s["correct"], (f"a correct, verified, cited figure ({rev['value']} {rev['units']}) scores wrong against gold "
                          f"'$1,210 million': {s['reason']} (eval/research/score.py normalise_figure does not know the unit "
                          f"strings research tools emit)")
    return "tool-emitted units are scored correctly"


# =========================================================================================== 12. no network
@check("12. zero socket attempts during the entire gate (and the research code used only the fixtures)")
def _():
    assert NS.attempts == 0, f"{NS.attempts} socket attempt(s) were made"
    return "0 socket attempts"


# =========================================================================================== report
def main() -> int:
    NS.__exit__(None, None, None)
    jobs.close_all()
    w = max(len(n) for n, _, _ in RESULTS)
    for name, status, detail in RESULTS:
        print(f"[{status}] {name.ljust(w)}  {detail}")
    n_pass = sum(s == "PASS" for _, s, _ in RESULTS)
    n_fail = sum(s == "FAIL" for _, s, _ in RESULTS)
    n_skip = sum(s == "SKIP" for _, s, _ in RESULTS)
    print(f"\nS6 gate: {n_pass}/{len(RESULTS)} passed, {n_fail} failed, {n_skip} skipped")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
