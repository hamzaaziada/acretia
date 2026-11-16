"""S6.1b research tools: the research agent's only way to get data.

``build_registry(...)`` returns a plain ``src.harness.router.ToolRegistry`` (no agent loop here; any runtime may call it).
Every tool returns ``ToolResult.to_dict()`` and, when an ``EvidenceBundle`` is given, appends exactly one evidence record
per successful call.

Rules every tool follows (PLAN S6.2):
* A figure's value is copied verbatim from the source record. Scale is never applied silently: it is written into
  ``units`` ("USD millions", "USD million", "%"). A missing value yields NO figure and a ``data["missing"]`` entry,
  never 0.
* Every figure is built through ``SourcedFigure.from_dict``, so it has a citation, an as-of date and a url or page.
  A candidate that fails the contract is dropped and reported in ``data["missing"]``.
* Deterministic: the same inputs give identical dicts (no clock reads except ``fetched_at`` handed back by the crawler).
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from om.contracts import Citation, ContractError, sha256_hex
from src.harness.evidence import canonical_bytes
from src.harness.research.api import SourcedFigure
from src.harness.router import ToolError, ToolRegistry

TICKER_RE = re.compile(r"[A-Za-z0-9.\-]{1,12}")
CONCEPT_RE = re.compile(r"(?:[A-Za-z][A-Za-z0-9-]*:)?[A-Za-z][A-Za-z0-9_]*")
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
MAX_ROWS = 200
MAX_CELLS = 500
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass
class ToolResult:
    data: dict
    figures: list = field(default_factory=list)       # list[SourcedFigure]
    citations: list = field(default_factory=list)     # list[om.contracts.Citation]
    source: str = ""

    def to_dict(self) -> dict:
        return {"data": self.data, "figures": [f.to_dict() for f in self.figures],
                "citations": [c.to_dict() for c in self.citations], "source": self.source}


# ------------------------------------------------------------------------------------------------ helpers
def _hash(obj) -> str:
    return sha256_hex(canonical_bytes(obj))


def _valid_date(s) -> str | None:
    if isinstance(s, str) and _DATE_RE.fullmatch(s):
        try:
            date.fromisoformat(s)
            return s
        except ValueError:
            return None
    return None


def _cit(**kw) -> Citation:
    return Citation.from_dict({k: v for k, v in kw.items() if v is not None})


def _figure(label, value, units, period, citation: Citation):
    """-> (SourcedFigure | None, reason). Never raises; the contract decides what counts as sourced."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None, "value is not a finite number"
    try:
        return SourcedFigure.from_dict({"label": label, "value": value, "units": units, "period": period,
                                        "citation": citation.to_dict()}), ""
    except ContractError as e:
        return None, str(e)


def _dedupe(cits: list) -> list:
    seen, out = set(), []
    for c in cits:
        if c.sha256_span_hash not in seen:
            seen.add(c.sha256_span_hash)
            out.append(c)
    return out


def _check_ticker(ticker) -> str:
    if not isinstance(ticker, str) or not TICKER_RE.fullmatch(ticker):
        raise ToolError(f"invalid ticker {ticker!r}")
    return ticker.upper()


def _check_int(name, v, lo, hi) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ToolError(f"{name} must be an integer in [{lo}, {hi}]")
    return v


def _cik_urls(cik) -> tuple[str, str]:
    """(doc_id fallback, companyfacts url)."""
    return (f"companyfacts:{cik}", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")


def _filing_url(cik, accn) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{str(accn).replace('-', '')}/"


def _sec(sec):
    if sec is not None:
        return sec
    from src.harness.connectors.sec import SecAdapter    # needs SEC_USER_AGENT; never touched when `sec=` is injected
    return SecAdapter()


def _clip_statements(st: dict, as_of: str | None) -> dict:
    """Drop fiscal years ending after ``as_of`` (all per-year lists are index-aligned with ``years``)."""
    if not as_of:
        return st
    keep = [i for i, y in enumerate(st.get("years", [])) if str(y) <= as_of]
    out = dict(st)
    out["years"] = [st["years"][i] for i in keep]
    out["data"] = {k: [v[i] for i in keep if i < len(v)] for k, v in st.get("data", {}).items()}
    if isinstance(st.get("filings"), list):
        out["filings"] = [st["filings"][i] for i in keep if i < len(st["filings"])]
    return out


# ------------------------------------------------------------------------------------------------ numbers with units
_SCALE = {"trillion": "trillion", "billion": "billion", "million": "million", "thousand": "thousand", "bn": "billion",
          "mm": "million", "m": "million", "k": "thousand", "%": "%", "percent": "%"}
_CUR = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CURP = r"(?P<cur>US\$|USD|EUR|GBP|[$€£])"
_AMOUNT = re.compile(rf"^(?P<open>\()?\s*(?P<neg>-)?\s*{_CURP}?\s*(?P<neg2>-)?\s*{_NUM}\s*"
                     r"(?P<scale>trillion|billion|million|thousand|bn|mm|m|k|%|percent)?\s*(?P<close>\))?$", re.I)
_SCAN = re.compile(rf"{_CURP}?\s?{_NUM}\s?(?P<scale>trillion|billion|million|thousand|bn|%|percent)?(?![A-Za-z0-9])", re.I)


def _units(cur, scale) -> str:
    c = _CUR.get((cur or "").lower(), "")
    s = _SCALE.get((scale or "").lower(), "")
    return " ".join(x for x in (c, s) if x) or "number"


def parse_amount(text) -> tuple[float, str] | None:
    """Whole-string amount -> (value verbatim, units) or None. '(1,234.5) million' -> (-1234.5, 'million')."""
    if not isinstance(text, str):
        return None
    m = _AMOUNT.match(text.strip())
    if not m or bool(m.group("open")) != bool(m.group("close")):
        return None
    v = float(m.group("num").replace(",", ""))
    if m.group("open") or m.group("neg") or m.group("neg2"):
        v = -v
    return v, _units(m.group("cur"), m.group("scale"))


def scan_amounts(text: str) -> list:
    """Numbers that carry an explicit currency symbol, scale word or percent sign inside free text."""
    out = []
    for m in _SCAN.finditer(text or ""):
        if not (m.group("cur") or m.group("scale")):
            continue
        out.append((float(m.group("num").replace(",", "")), _units(m.group("cur"), m.group("scale")), m.start(), m.group(0)))
    return out


# ------------------------------------------------------------------------------------------------ SEC XBRL facts
def _annual_rows(rows: list, as_of: str | None) -> list:
    best: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        val, end = r.get("val"), _valid_date(r.get("end"))
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not end:
            continue
        if not str(r.get("form", "")).startswith(ANNUAL_FORMS):
            continue
        start = _valid_date(r.get("start"))
        if r.get("start") is not None:
            if not start or not 350 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 380:
                continue
        if as_of and (end > as_of or str(r.get("filed", "")) > as_of):
            continue
        key = (end, start is None)
        if key not in best or (str(r.get("filed", "")), str(r.get("accn", ""))) > (str(best[key].get("filed", "")),
                                                                                  str(best[key].get("accn", ""))):
            best[key] = r
    return [best[k] for k in sorted(best)]


def _split_concept(concept: str) -> tuple[str, str]:
    if ":" in concept:
        tax, name = concept.split(":", 1)
        return tax, name
    return "us-gaap", concept


def sec_facts(ticker: str, concepts: list, periods: int = 5, *, sec=None, as_of=None) -> ToolResult:
    tk = _check_ticker(ticker)
    periods = _check_int("periods", periods, 1, 20)
    if not isinstance(concepts, list) or not concepts or not all(isinstance(c, str) and CONCEPT_RE.fullmatch(c)
                                                                 for c in concepts):
        raise ToolError("concepts must be a non-empty list of XBRL concept names like 'us-gaap:Revenues'")
    cf = _sec(sec).company_facts(tk)
    cik = cf.get("cik")
    if cik is None:
        raise ToolError("company facts carry no CIK; cannot cite")
    fallback_doc, facts_url = _cik_urls(cik)
    figures, cits, missing, rows_out = [], [], [], []
    for concept in concepts:
        tax, name = _split_concept(concept)
        node = ((cf.get("facts") or {}).get(tax) or {}).get(name)
        if not node:
            missing.append({"item": f"{tax}:{name}", "reason": "concept not in company facts"})
            continue
        got = False
        for unit in sorted((node.get("units") or {})):
            for r in _annual_rows(node["units"][unit], as_of)[-periods:]:
                end, accn = r["end"], r.get("accn") or ""
                start = r.get("start")
                quote = (f"{tax}:{name} = {r['val']} {unit}, {start + ' to ' if start else ''}{end}, "
                         f"{r.get('form', '')} filed {r.get('filed', '')}" + (f", accn {accn}" if accn else ""))
                cit = _cit(doc_id=accn or fallback_doc, sha256_span_hash=_hash(
                    {"cik": cik, "concept": f"{tax}:{name}", "unit": unit, "val": r["val"], "start": start, "end": end,
                     "accn": accn, "form": r.get("form"), "filed": r.get("filed")}),
                    quote=quote, url=_filing_url(cik, accn) if accn else facts_url, as_of=end,
                    xbrl_concept=f"{tax}:{name}")
                fig, why = _figure(f"{tk} {name}", r["val"], unit, f"FY ending {end}", cit)
                if fig is None:
                    missing.append({"item": f"{tax}:{name}@{end}", "reason": why})
                    continue
                figures.append(fig)
                cits.append(cit)
                rows_out.append({"concept": f"{tax}:{name}", "unit": unit, "end": end, "val": r["val"], "accn": accn})
                got = True
        if not got:
            missing.append({"item": f"{tax}:{name}", "reason": "no annual value in the requested window"})
    return ToolResult({"ticker": tk, "cik": cik, "rows": rows_out, "missing": missing}, figures, _dedupe(cits), facts_url)


# ------------------------------------------------------------------------------------------------ statements
HEADLINE = (("revenue", "Revenue"), ("gross_profit", "Gross profit"), ("ebit", "Operating income"),
            ("net_income", "Net income"), ("assets", "Total assets"), ("cash", "Cash and equivalents"),
            ("cfo", "Cash from operations"), ("capex", "Capital expenditure (payments, as reported)"))


def _stmt_cell(st: dict, key: str, i: int):
    v = (st.get("data") or {}).get(key)
    if v is None or i >= len(v):
        return None
    x = v[i]
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _stmt_citation(st: dict, ticker: str, key: str, i: int, value, *, quote: str | None = None, extra=None) -> Citation:
    end = str(st["years"][i])
    fl = st.get("filings") or []
    f = fl[i] if i < len(fl) and isinstance(fl[i], dict) else {}
    accn = f.get("accn") or ""
    cik = st.get("cik")
    fallback_doc, facts_url = _cik_urls(cik) if cik is not None else (None, None)
    cur = st.get("currency") or "USD"
    url = f.get("url") or (_filing_url(cik, accn) if cik is not None and accn else facts_url)
    doc_id = accn or fallback_doc
    if not doc_id or not url:
        raise ContractError(f"statement {key} FY{end}: no filing or CIK to cite")
    return _cit(doc_id=doc_id, sha256_span_hash=_hash({"ticker": ticker, "line": key, "end": end, "val": value,
                                                       "accn": accn, "extra": extra}),
                quote=quote or f"{key} = {value} {cur} millions, FY ending {end}", url=url, as_of=end)


def _statement_figure(st, tk, key, label, i):
    v = _stmt_cell(st, key, i)
    end = str(st["years"][i])
    if v is None:
        return None, None, {"item": f"{key}@{end}", "reason": "line not tagged in the filing"}
    try:
        cit = _stmt_citation(st, tk, key, i, v)
    except ContractError as e:
        return None, None, {"item": f"{key}@{end}", "reason": str(e)}
    fig, why = _figure(f"{tk} {label}", v, f"{st.get('currency') or 'USD'} millions", f"FY ending {end}", cit)
    if fig is None:
        return None, None, {"item": f"{key}@{end}", "reason": why}
    return fig, cit, None


def sec_statements(ticker: str, years: int = 5, *, sec=None, as_of=None) -> ToolResult:
    tk = _check_ticker(ticker)
    years = _check_int("years", years, 1, 15)
    st = _clip_statements(_sec(sec).financial_statements(tk, years), as_of)
    figures, cits, missing, derivations = [], [], [], []
    for i in range(len(st.get("years", []))):
        for key, label in HEADLINE:
            fig, cit, miss = _statement_figure(st, tk, key, label, i)
            if miss:
                missing.append(miss)
            else:
                figures.append(fig)
                cits.append(cit)
        dc, dn = _stmt_cell(st, "debt_current", i), _stmt_cell(st, "debt_noncurrent", i)
        end = str(st["years"][i])
        if dc is None or dn is None:
            missing.append({"item": f"total_debt@{end}", "reason": "debt_current or debt_noncurrent not tagged"})
            continue
        ins = [_stmt_citation(st, tk, k, i, v) for k, v in (("debt_current", dc), ("debt_noncurrent", dn))]
        total = dc + dn
        cit = _stmt_citation(st, tk, "total_debt", i, total, extra=[c.sha256_span_hash for c in ins],
                             quote=f"derived: total_debt = debt_current + debt_noncurrent = {dc} + {dn} = {total} "
                                   f"{st.get('currency') or 'USD'} millions, FY ending {end}")
        fig, why = _figure(f"{tk} derived: total_debt = debt_current + debt_noncurrent", total,
                           f"{st.get('currency') or 'USD'} millions", f"FY ending {end}", cit)
        if fig is None:
            missing.append({"item": f"total_debt@{end}", "reason": why})
            continue
        figures.append(fig)
        cits.extend([cit] + ins)
        derivations.append({"figure": fig.label, "period": fig.period, "inputs": [c.to_dict() for c in ins]})
    cik = st.get("cik")
    src = _cik_urls(cik)[1] if cik is not None else f"statements:{tk}"
    return ToolResult({"ticker": tk, "statements": st, "derivations": derivations, "missing": missing},
                      figures, _dedupe(cits), src)


# ------------------------------------------------------------------------------------------------ filings
def sec_filings(ticker: str, form: str = "10-K", n: int = 3, *, sec=None, as_of=None) -> ToolResult:
    tk = _check_ticker(ticker)
    n = _check_int("n", n, 1, 25)
    if not isinstance(form, str) or not re.fullmatch(r"[A-Za-z0-9\-/]{1,12}", form):
        raise ToolError(f"invalid form {form!r}")
    rows = list(_sec(sec).filings(tk, form, n))
    if as_of:
        rows = [r for r in rows if str(r.get("filed", "")) <= as_of]
    rows = [{k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v)) for k, v in r.items()} for r in rows]
    return ToolResult({"ticker": tk, "form": form, "filings": rows, "missing": []}, [], [],
                      f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={tk}&type={form}")


# ------------------------------------------------------------------------------------------------ ratios (derived)
# metric -> (formula, inputs [(statement key, year offset)], equity handled separately)
RATIOS = {
    "revenue_growth": ("(revenue - revenue_prior) / abs(revenue_prior)", [("revenue", 0), ("revenue", -1)]),
    "gross_margin": ("gross_profit / revenue", [("gross_profit", 0), ("revenue", 0)]),
    "ebit_margin": ("ebit / revenue", [("ebit", 0), ("revenue", 0)]),
    "net_margin": ("net_income / revenue", [("net_income", 0), ("revenue", 0)]),
    "current_ratio": ("current_assets / current_liabilities", [("current_assets", 0), ("current_liabilities", 0)]),
    "debt_to_equity": ("(debt_current + debt_noncurrent) / equity",
                       [("debt_current", 0), ("debt_noncurrent", 0), ("equity", 0)]),
}


def ratios(ticker: str, years: int = 3, *, sec=None, as_of=None) -> ToolResult:
    from src.harness.connectors import fintk
    tk = _check_ticker(ticker)
    years = _check_int("years", years, 1, 15)
    st = _clip_statements(_sec(sec).financial_statements(tk, years), as_of)
    metrics = fintk.ratios(st) if st.get("years") else {"years": [], "metrics": {}}
    figures, cits, missing, derivations = [], [], [], []
    for i in range(len(st.get("years", []))):
        end = str(st["years"][i])
        for name, (formula, inputs) in RATIOS.items():
            value = (metrics["metrics"].get(name) or [None] * (i + 1))[i]
            if name == "revenue_growth" and i == 0:
                continue                                     # no prior year inside the window: not a gap, not computable
            picked, why = [], ""
            for key, off in inputs:
                k = key
                if key == "equity":
                    k = "equity_total" if _stmt_cell(st, "equity_total", i) is not None else "equity_parent"
                v = _stmt_cell(st, k, i + off)
                if v is None:
                    why = f"input {k} not tagged for FY ending {st['years'][i + off]}"
                    break
                picked.append((k, i + off, v))
            if why or value is None or not math.isfinite(value):
                missing.append({"item": f"{name}@{end}", "reason": why or "not computable from reported inputs"})
                continue
            ins = [_stmt_citation(st, tk, k, j, v) for k, j, v in picked]
            lbl = f"derived: {name} = {formula}"
            used = ", ".join(f"{k}[{st['years'][j]}]={v}" for k, j, v in picked)
            cit = _stmt_citation(st, tk, name, i, value, extra={"formula": formula, "inputs": [c.sha256_span_hash for c in ins]},
                                 quote=f"derived: {name} = {formula}; {used}; = {value}")
            fig, why2 = _figure(f"{tk} {lbl}", value, "ratio", f"FY ending {end}", cit)
            if fig is None:
                missing.append({"item": f"{name}@{end}", "reason": why2})
                continue
            figures.append(fig)
            cits.extend([cit] + ins)
            derivations.append({"figure": fig.label, "period": fig.period, "formula": formula,
                                "inputs": [c.to_dict() for c in ins]})
    cik = st.get("cik")
    src = _cik_urls(cik)[1] if cik is not None else f"statements:{tk}"
    return ToolResult({"ticker": tk, "years": st.get("years", []), "metrics": metrics["metrics"],
                       "derivations": derivations, "missing": missing}, figures, _dedupe(cits), src)


# ------------------------------------------------------------------------------------------------ web
def web_facts(url: str, *, web=None, as_of=None) -> ToolResult:
    if not isinstance(url, str) or not re.fullmatch(r"https?://\S+", url):
        raise ToolError("url must be an http(s) URL")
    if web is None:
        from src.harness.connectors.web import Crawler   # SSRF / robots / rate limits live in the Crawler
        web = Crawler()
    facts, links = web.page_facts(url)
    d = facts.as_dict() if hasattr(facts, "as_dict") else dict(facts)
    d["links"] = [list(x) if isinstance(x, (tuple, list)) else x for x in (links or [])][:25]
    snippet = d.get("snippet") or ""
    when = _valid_date(d.get("published")) or _valid_date(str(d.get("fetched_at", ""))[:10]) or _valid_date(as_of)
    figures, cits, missing, seen = [], [], [], set()
    for value, units, pos, token in scan_amounts(snippet):
        words = snippet[:pos].split()[-6:]
        label = " ".join(words) or d.get("title") or "web figure"
        if (value, units, label) in seen:
            continue
        seen.add((value, units, label))
        if not when:
            missing.append({"item": token, "reason": "no published or fetch date"})
            continue
        cit = _cit(doc_id=f"web:{d.get('sha256') or _hash(url)}", sha256_span_hash=sha256_hex(snippet), quote=snippet,
                   url=d.get("url") or url, as_of=when)
        fig, why = _figure(label, value, units, f"as of {when}", cit)
        if fig is None:
            missing.append({"item": token, "reason": why})
            continue
        figures.append(fig)
        cits.append(cit)
    return ToolResult({"page": d, "missing": missing}, figures, _dedupe(cits), d.get("url") or url)


# ------------------------------------------------------------------------------------------------ grid
def _open_grid(grid_db):
    if grid_db is None:
        raise ToolError("no grid database configured")
    if hasattr(grid_db, "query"):
        return grid_db, False
    from om.storage import AnalyticsDB
    from src.harness.mcp.paths import PathError, resolve_in_root
    try:
        p = resolve_in_root(str(grid_db), must_exist=True)
    except PathError as e:
        raise ToolError(str(e)) from None
    db = AnalyticsDB(str(p), prefer=os.environ.get("ACRETIA_GRID_BACKEND", "duckdb"))
    return db, True


def _cell_figure(row: dict, default_as_of):
    need = ("doc_id", "question_id", "answer", "exact_quote", "page", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1")
    if not all(k in row for k in need):
        return None, None, "row lacks citation columns"
    ref = f"{row['doc_id']}/{row['question_id']}"
    parsed = parse_amount(row["answer"])
    if parsed is None:
        return None, None, "answer is not a number with units"
    when = _valid_date(str(row.get("updated_at") or "")[:10]) or _valid_date(default_as_of)
    if not when:
        return None, None, "no as-of date for the cell"
    quote = row["exact_quote"]
    if not isinstance(quote, str) or not quote.strip() or not isinstance(row["page"], int) or isinstance(row["page"], bool):
        return None, None, "cell has no exact quote or page"
    bbox = [row[k] for k in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1")]
    try:
        cit = _cit(doc_id=str(row["doc_id"]), sha256_span_hash=sha256_hex(quote), page=row["page"], bbox_norm=bbox,
                   quote=quote, as_of=when)
    except ContractError as e:
        return None, None, str(e)
    fig, why = _figure(str(row["question_id"]), parsed[0], parsed[1], f"as of {when}", cit)
    return fig, cit, why or ref


def grid_query(sql: str, params=None, *, grid_db=None, as_of=None) -> ToolResult:
    from src.harness.mcp.grid_server import run_select
    from src.harness.mcp.server import ToolFailure
    if params is not None and not isinstance(params, list):
        raise ToolError("params must be a list")
    db, own = _open_grid(grid_db)
    try:
        try:
            res = run_select(db, sql, params, MAX_ROWS)   # shared hardened engine: no external access, timeout, caps
        except ToolFailure as e:
            raise ToolError(str(e)) from None
    finally:
        if own:
            db.close()
    truncated = res["truncated"]
    rows = res["rows"]
    figures, cits, missing = [], [], []
    for row in rows:
        if "exact_quote" not in row:
            continue
        fig, cit, why = _cell_figure(row, as_of)
        if fig is None:
            missing.append({"item": f"{row.get('doc_id')}/{row.get('question_id')}", "reason": why})
        else:
            figures.append(fig)
            cits.append(cit)
    return ToolResult({"rows": rows, "row_count": len(rows), "truncated": truncated, "missing": missing},
                      figures, _dedupe(cits), "grid:query")


def grid_cell(grid_id: str, doc_id: str, question_id: str, *, grid_db=None, as_of=None) -> ToolResult:
    for k, v in (("grid_id", grid_id), ("doc_id", doc_id), ("question_id", question_id)):
        if not isinstance(v, str) or not v:
            raise ToolError(f"{k} must be a non-empty string")
    db, own = _open_grid(grid_db)
    try:
        rows = db.query("SELECT * FROM grid_cells WHERE grid_id = ? AND doc_id = ? AND question_id = ?",
                        [grid_id, doc_id, question_id])
    finally:
        if own:
            db.close()
    src = f"grid:{grid_id}/{doc_id}/{question_id}"
    if not rows:
        return ToolResult({"found": False, "cell": None, "missing": [{"item": src, "reason": "no such grid cell"}]},
                          [], [], src)
    fig, cit, why = _cell_figure(rows[0], as_of)
    missing = [] if fig is not None else [{"item": src, "reason": why}]
    return ToolResult({"found": True, "cell": rows[0], "missing": missing},
                      [fig] if fig else [], [cit] if cit else [], src)


# ------------------------------------------------------------------------------------------------ xlsx
_CELL_RE = re.compile(r"(?:'((?:[^']|'')+)'|([^'!]+))!(\$?[A-Z]{1,3}\$?\d+)")


def _xlsx_path(path, excel_root) -> Path:
    if excel_root is None:
        raise ToolError("no excel_root configured")
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ToolError("path must be a non-empty string")
    base = Path(os.path.realpath(excel_root))
    cand = Path(path)
    real = Path(os.path.realpath(cand if cand.is_absolute() else base / cand))
    try:
        real.relative_to(base)
    except ValueError:
        raise ToolError(f"path escapes the allowed root: {path!r}") from None
    if real.suffix.lower() not in (".xlsx", ".xlsm") or not real.is_file():
        raise ToolError(f"no such workbook: {path!r}")
    return real


def xlsx_evaluate(path: str, cells: list, *, excel_root=None, as_of=None) -> ToolResult:
    from om import formula as fx
    from om import xlsx
    if not isinstance(cells, list) or not cells or len(cells) > MAX_CELLS or not all(isinstance(c, str) for c in cells):
        raise ToolError(f"cells must be a list of 1..{MAX_CELLS} strings like 'Sheet1!B4'")
    real = _xlsx_path(path, excel_root)
    raw_bytes = real.read_bytes()
    rel = real.relative_to(Path(os.path.realpath(excel_root))).as_posix()
    book = xlsx.read(raw_bytes)
    eng = fx.from_book(book)
    eng.calculate(iterate=True)
    when = _valid_date(as_of) or datetime.fromtimestamp(real.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
    file_hash = sha256_hex(raw_bytes)
    values, figures, cits, missing = {}, [], [], []
    for ref in cells:
        m = _CELL_RE.fullmatch(ref)
        if not m:
            raise ToolError(f"bad cell reference {ref!r}; use Sheet!A1")
        sheet = (m.group(1) or "").replace("''", "'") or m.group(2)
        if sheet not in book.sheets:
            raise ToolError(f"no such sheet {sheet!r}")
        r, c = xlsx.split_ref(m.group(3))
        cell = book.sheets[sheet].get((r, c))
        val = eng.values.get((sheet, r, c), cell.value if cell else None)
        formula = cell.formula if cell else None
        values[ref] = {"value": val if val is None or isinstance(val, (bool, int, float, str)) else str(val),
                       "formula": formula}
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            missing.append({"item": ref, "reason": "cell is empty or not numeric"})
            continue
        local = m.group(3).replace("$", "")
        loc = f"'{sheet.replace(chr(39), chr(39) * 2)}'!{local}" if re.search(r"[^A-Za-z0-9_.]", sheet) else f"{sheet}!{local}"
        quote = f"{loc} = {val}" + (f" ({formula})" if formula else "")
        try:
            cit = _cit(doc_id=f"xlsx:{rel}", sha256_span_hash=_hash({"file": file_hash, "cell": loc, "val": val,
                                                                    "formula": formula}),
                       quote=quote, source_url=f"file:///{rel}", cell_locator=loc, as_of=when)
        except ContractError as e:
            missing.append({"item": ref, "reason": str(e)})
            continue
        fig, why = _figure(loc, val, "number", f"workbook {rel}", cit)
        if fig is None:
            missing.append({"item": ref, "reason": why})
            continue
        figures.append(fig)
        cits.append(cit)
    return ToolResult({"path": rel, "values": values, "unsupported_functions": sorted(map(str, eng.unsupported))[:50],
                       "missing": missing}, figures, _dedupe(cits), f"xlsx:{rel}")


# ------------------------------------------------------------------------------------------------ registry
def _obj(required, **props) -> dict:
    return {"type": "object", "required": list(required), "additionalProperties": False, "properties": props}


def build_registry(*, evidence=None, sec=None, web=None, grid_db=None, excel_root=None, as_of=None) -> ToolRegistry:
    """The research agent's tool surface. ``evidence`` (an EvidenceBundle) gets one record per successful call."""
    if as_of is not None and not _valid_date(as_of):
        raise ToolError(f"as_of must be YYYY-MM-DD, got {as_of!r}")
    reg = ToolRegistry()

    def wrap(name, fn):
        def run(**kw):
            res = fn(**kw).to_dict()
            if evidence is not None:
                page = bbox = None
                if len(res["figures"]) == 1:
                    c = res["figures"][0]["citation"]
                    page, bbox = c.get("page"), c.get("bbox_norm")
                evidence.append(name, kw, source=res["source"], page=page, bbox_norm=bbox, output=res)
            return res
        run.__doc__ = fn.__doc__
        return run

    tickers = {"type": "string"}
    tools = [
        ("sec_facts", lambda ticker, concepts, periods=5: sec_facts(ticker, concepts, periods, sec=sec, as_of=as_of),
         _obj(["ticker", "concepts"], ticker=tickers, concepts={"type": "array", "items": {"type": "string"}},
              periods={"type": "integer"}),
         "Annual XBRL values (us-gaap:Revenues, ...) from SEC company facts, one cited figure per fiscal year."),
        ("sec_statements", lambda ticker, years=5: sec_statements(ticker, years, sec=sec, as_of=as_of),
         _obj(["ticker"], ticker=tickers, years={"type": "integer"}),
         "Annual 3-statement data in USD millions plus cited headline figures."),
        ("sec_filings", lambda ticker, form="10-K", n=3: sec_filings(ticker, form, n, sec=sec, as_of=as_of),
         _obj(["ticker"], ticker=tickers, form={"type": "string"}, n={"type": "integer"}),
         "Recent SEC filings (form, filing date, accession, url)."),
        ("ratios", lambda ticker, years=3: ratios(ticker, years, sec=sec, as_of=as_of),
         _obj(["ticker"], ticker=tickers, years={"type": "integer"}),
         "Derived ratios; each figure cites every input line it is computed from."),
        ("web_facts", lambda url: web_facts(url, web=web, as_of=as_of),
         _obj(["url"], url={"type": "string"}),
         "Title, date and snippet of a public web page; figures only for numbers with explicit units."),
        ("grid_query", lambda sql, params=None: grid_query(sql, params, grid_db=grid_db, as_of=as_of),
         _obj(["sql"], sql={"type": "string"}, params={"type": "array"}),
         "Read-only single SELECT over the document grid; numeric answers become cited figures."),
        ("grid_cell", lambda grid_id, doc_id, question_id: grid_cell(grid_id, doc_id, question_id, grid_db=grid_db,
                                                                      as_of=as_of),
         _obj(["grid_id", "doc_id", "question_id"], grid_id={"type": "string"}, doc_id={"type": "string"},
              question_id={"type": "string"}),
         "One document-grid cell with its page, bbox and exact quote."),
        ("xlsx_evaluate", lambda path, cells: xlsx_evaluate(path, cells, excel_root=excel_root, as_of=as_of),
         _obj(["path", "cells"], path={"type": "string"}, cells={"type": "array", "items": {"type": "string"}}),
         "Recalculate a workbook inside excel_root and read cells like 'Sheet1!B4'; figures cite the cell."),
    ]
    for name, fn, schema, desc in tools:
        reg.register(name, wrap(name, fn), schema, task_types=["reasoning", "extraction"], description=desc)
    return reg
