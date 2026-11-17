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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit

from om.contracts import Citation, ContractError, sha256_hex
from src.harness.evidence import canonical_bytes
from src.harness.research.api import SourcedFigure
from src.harness.router import ToolError, ToolRegistry

TICKER_RE = re.compile(r"[A-Za-z0-9.\-]{1,12}")
CONCEPT_RE = re.compile(r"(?:[A-Za-z][A-Za-z0-9-]*:)?[A-Za-z][A-Za-z0-9_]*")
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
PERIODS = ("annual", "quarterly")
QUARTER_DAYS = (80, 100)      # a discrete fiscal quarter
YTD9_DAYS = (255, 290)        # nine months year to date (Q1-Q3), as filed on the Q3 10-Q
MINUS = "\u2212"
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


# ------------------------------------------------------------------------------------------------ quarterly (10-Q)
def _check_period(period) -> str:
    if period not in PERIODS:
        raise ToolError(f"period must be one of {PERIODS}, got {period!r}")
    return period


def _clean_row(r, as_of):
    """(row, end, start) for a usable numeric fact row, else None."""
    if not isinstance(r, dict):
        return None
    val, end = r.get("val"), _valid_date(r.get("end"))
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or not end:
        return None
    start = _valid_date(r.get("start")) if r.get("start") is not None else None
    if r.get("start") is not None and not start:
        return None
    if as_of and (end > as_of or str(r.get("filed", "")) > as_of):
        return None
    return r, end, start


def _newer(a, b) -> bool:
    return (str(a.get("filed", "")), str(a.get("accn", ""))) > (str(b.get("filed", "")), str(b.get("accn", "")))


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _quarter_series(rows: list, as_of: str | None):
    """One concept/unit -> ([entry], [fiscal-year ends whose Q4 cannot be derived]).

    entry = {"end", "start", "row", "derived": None | {"fy", "ytd", "value"}}. Q1-Q3 come from 10-Q rows (~90-day
    durations, or balance-sheet instants). A fiscal Q4 flow is derived as FY minus 9M YTD, and only when both the 10-K
    year and the 10-Q nine-month figure are tagged; a Q4 balance-sheet instant is the 10-K year-end value itself."""
    disc, ytd = {}, {}
    for r in rows or []:
        c = _clean_row(r, as_of)
        if not c or not str(r.get("form", "")).startswith("10-Q"):
            continue
        _, end, start = c
        if start is None or QUARTER_DAYS[0] <= _days(start, end) <= QUARTER_DAYS[1]:
            bucket, key = disc, end
        elif YTD9_DAYS[0] <= _days(start, end) <= YTD9_DAYS[1]:
            bucket, key = ytd, (end, start)
        else:
            continue
        if key not in bucket or _newer(r, bucket[key]):
            bucket[key] = r
    entries = {e: {"end": e, "start": r.get("start"), "row": r, "derived": None} for e, r in disc.items()}
    underivable = []
    for fy in _annual_rows(rows, as_of):
        end, start = fy["end"], fy.get("start")
        if end in entries:
            continue
        if start is None:                                       # balance-sheet instant: Q4 = year end, tagged directly
            entries[end] = {"end": end, "start": None, "row": fy, "derived": None}
            continue
        cands = [r for (yend, ystart), r in ytd.items()
                 if abs(_days(ystart, start)) <= 7 and QUARTER_DAYS[0] <= _days(yend, end) <= QUARTER_DAYS[1]]
        if not cands:
            underivable.append(end)
            continue
        y = max(cands, key=lambda r: (str(r.get("filed", "")), str(r.get("accn", ""))))
        value = round(fy["val"] - y["val"], 6)
        q4_start = (date.fromisoformat(y["end"]) + timedelta(days=1)).isoformat()
        entries[end] = {"end": end, "start": q4_start, "row": fy, "derived": {"fy": fy, "ytd": y, "value": value}}
    return [entries[k] for k in sorted(entries)], underivable


def _quarter_comparisons(ends: list) -> dict:
    """Latest quarter, the prior quarter and the same quarter a year earlier (None when not in the data)."""
    ends = sorted(ends)
    if not ends:
        return {"latest": None, "prior_quarter": None, "year_ago": None}
    latest = ends[-1]
    prior = next((e for e in reversed(ends[:-1]) if QUARTER_DAYS[0] <= _days(e, latest) <= QUARTER_DAYS[1] + 10), None)
    yago = next((e for e in ends[:-1] if 350 <= _days(e, latest) <= 380), None)
    return {"latest": latest, "prior_quarter": prior, "year_ago": yago}


def _derived_label(base: str, fy_end: str, ytd_end: str) -> str:
    return (f"{base} derived: FY {MINUS} 9M = {{{base}|FY ending {fy_end}}} - "
            f"{{{base} 9M YTD|9M ending {ytd_end}}}")


def _sec_facts_quarterly(tk, concepts, periods, cf, as_of) -> ToolResult:
    cik = cf.get("cik")
    if cik is None:
        raise ToolError("company facts carry no CIK; cannot cite")
    fallback_doc, facts_url = _cik_urls(cik)
    figures, cits, missing, rows_out, derivations = [], [], [], [], []

    def xbrl_fig(label, tax, name, unit, r, period):
        end, accn, start = r["end"], r.get("accn") or "", r.get("start")
        quote = (f"{tax}:{name} = {r['val']} {unit}, {start + ' to ' if start else ''}{end}, "
                 f"{r.get('form', '')} filed {r.get('filed', '')}" + (f", accn {accn}" if accn else ""))
        cit = _cit(doc_id=accn or fallback_doc, sha256_span_hash=_hash(
            {"cik": cik, "concept": f"{tax}:{name}", "unit": unit, "val": r["val"], "start": start, "end": end,
             "accn": accn, "form": r.get("form"), "filed": r.get("filed")}),
            quote=quote, url=_filing_url(cik, accn) if accn else facts_url, as_of=end, xbrl_concept=f"{tax}:{name}")
        fig, why = _figure(label, r["val"], unit, period, cit)
        return fig, cit, why

    for concept in concepts:
        tax, name = _split_concept(concept)
        node = ((cf.get("facts") or {}).get(tax) or {}).get(name)
        if not node:
            missing.append({"item": f"{tax}:{name}", "reason": "concept not in company facts"})
            continue
        got = False
        for unit in sorted(node.get("units") or {}):
            entries, bad = _quarter_series(node["units"][unit], as_of)
            window = entries[-periods:]
            floor = window[0]["end"] if window else None
            for e in bad:
                if floor is None or e >= floor:
                    missing.append({"item": f"{tax}:{name}@{e}", "reason": "Q4 not derivable: FY minus 9M needs both "
                                                                           "the 10-K and the 10-Q nine-month value tagged"})
            for en in window:
                end, d = en["end"], en["derived"]
                base = f"{tk} {name}"
                if d is None:
                    fig, cit, why = xbrl_fig(base, tax, name, unit, en["row"], f"quarter ending {end}")
                    if fig is None:
                        missing.append({"item": f"{tax}:{name}@{end}", "reason": why})
                        continue
                    figures.append(fig)
                    cits.append(cit)
                    rows_out.append({"concept": f"{tax}:{name}", "unit": unit, "end": end, "val": en["row"]["val"],
                                     "accn": en["row"].get("accn") or "", "derived": False})
                    got = True
                    continue
                fy, y = d["fy"], d["ytd"]
                fy_fig, fy_cit, w1 = xbrl_fig(base, tax, name, unit, fy, f"FY ending {fy['end']}")
                y_fig, y_cit, w2 = xbrl_fig(f"{base} 9M YTD", tax, name, unit, y, f"9M ending {y['end']}")
                if fy_fig is None or y_fig is None:
                    missing.append({"item": f"{tax}:{name}@{end}", "reason": w1 or w2})
                    continue
                accn = fy.get("accn") or ""
                quote = (f"derived: FY {MINUS} 9M: {tax}:{name} FY ending {fy['end']} = {fy['val']} {unit} less 9M ending "
                         f"{y['end']} = {y['val']} {unit} gives {d['value']} {unit}, quarter ending {end}")
                cit = _cit(doc_id=accn or fallback_doc, sha256_span_hash=_hash(
                    {"derived": "fy-9m", "concept": f"{tax}:{name}", "unit": unit, "end": end,
                     "inputs": [fy_cit.sha256_span_hash, y_cit.sha256_span_hash]}),
                    quote=quote, url=_filing_url(cik, accn) if accn else facts_url, as_of=end)
                fig, why = _figure(_derived_label(base, fy["end"], y["end"]), d["value"], unit, f"quarter ending {end}", cit)
                if fig is None:
                    missing.append({"item": f"{tax}:{name}@{end}", "reason": why})
                    continue
                figures.extend([fy_fig, y_fig, fig])
                cits.extend([cit, fy_cit, y_cit])
                derivations.append({"figure": fig.label, "period": fig.period, "formula": f"FY {MINUS} 9M",
                                    "inputs": [fy_cit.to_dict(), y_cit.to_dict()]})
                rows_out.append({"concept": f"{tax}:{name}", "unit": unit, "end": end, "val": d["value"],
                                 "accn": accn, "derived": True})
                got = True
        if not got:
            missing.append({"item": f"{tax}:{name}", "reason": "no quarterly value in the requested window"})
    ends = sorted({r["end"] for r in rows_out})
    return ToolResult({"ticker": tk, "cik": cik, "period": "quarterly", "rows": rows_out, "derivations": derivations,
                       "comparisons": _quarter_comparisons(ends), "missing": missing},
                      figures, _dedupe(cits), facts_url)


_Q_FLOW = ("revenue", "gross_profit", "ebit", "net_income", "cfo", "capex")
_Q_STOCK = (("assets", "total_assets"), ("cash", "cash"))


def _usd_unit(node: dict):
    units = [u for u in sorted(node.get("units") or {}) if "/" not in u and re.fullmatch(r"[A-Z]{3}", u)]
    return ("USD" if "USD" in units else units[0]) if units else None


def _sec_statements_quarterly(tk, quarters, cf, as_of) -> ToolResult:
    from om.concepts import DURATION, INSTANT
    cik = cf.get("cik")
    if cik is None:
        raise ToolError("company facts carry no CIK; cannot cite")
    fallback_doc, facts_url = _cik_urls(cik)
    chains = {k: DURATION[k] for k in _Q_FLOW}
    chains.update({k: INSTANT[c] for k, c in _Q_STOCK})
    per_key, bad_by_key, currency = {}, {}, "USD"
    for key, chain in chains.items():
        by_end, bad = {}, set()
        for tax, name in chain:                                  # first concept with a value for that quarter wins
            node = ((cf.get("facts") or {}).get(tax) or {}).get(name)
            unit = _usd_unit(node) if node else None
            if not unit:
                continue
            ents, b = _quarter_series(node["units"][unit], as_of)
            for en in ents:
                by_end.setdefault(en["end"], dict(en, concept=f"{tax}:{name}", unit=unit))
            bad.update(b)
            currency = unit
        per_key[key], bad_by_key[key] = by_end, bad
    ends = sorted({e for d in per_key.values() for e in d})[-quarters:]
    labels = dict(HEADLINE)
    data = {k: [] for k in chains}
    filings, qmeta = [], []
    figures, cits, missing, derivations = [], [], [], []

    def cit_for(key, r, concept, end, value, extra):
        accn = r.get("accn") or ""
        return _cit(doc_id=accn or fallback_doc, sha256_span_hash=_hash(
            {"ticker": tk, "line": key, "end": end, "val": value, "accn": accn, "extra": extra, "q": True}),
            quote=extra.get("quote") if isinstance(extra, dict) and extra.get("quote") else
            f"{key} = {value} {currency} millions, quarter ending {end}",
            url=_filing_url(cik, accn) if accn else facts_url, as_of=end)

    for end in ends:
        meta = {"end": end, "derived": []}
        accn0 = None
        for key in chains:
            en = per_key[key].get(end)
            if en is None:
                data[key].append(None)
                if end in bad_by_key[key]:
                    missing.append({"item": f"{key}@{end}", "reason": "Q4 not derivable: FY minus 9M needs both tagged"})
                else:
                    missing.append({"item": f"{key}@{end}", "reason": "line not tagged in the filings"})
                continue
            accn0 = accn0 or en["row"].get("accn")
            d, label = en["derived"], f"{tk} {labels[key]}"
            if d is None:
                v = round(en["row"]["val"] / 1e6, 6)
                cit = cit_for(key, en["row"], en["concept"], end, v, None)
                fig, why = _figure(label, v, f"{currency} millions", f"quarter ending {end}", cit)
                if fig is None:
                    data[key].append(None)
                    missing.append({"item": f"{key}@{end}", "reason": why})
                    continue
                figures.append(fig)
                cits.append(cit)
                data[key].append(v)
                continue
            fy, y = d["fy"], d["ytd"]
            fy_v, y_v = round(fy["val"] / 1e6, 6), round(y["val"] / 1e6, 6)
            v = round(d["value"] / 1e6, 6)
            fy_cit = cit_for(key, fy, en["concept"], fy["end"], fy_v,
                             {"quote": f"{key} = {fy_v} {currency} millions, FY ending {fy['end']}"})
            y_cit = cit_for(key, y, en["concept"], y["end"], y_v,
                            {"quote": f"{key} = {y_v} {currency} millions, 9M ending {y['end']}"})
            fy_fig, w1 = _figure(label, fy_v, f"{currency} millions", f"FY ending {fy['end']}", fy_cit)
            y_fig, w2 = _figure(f"{label} 9M YTD", y_v, f"{currency} millions", f"9M ending {y['end']}", y_cit)
            quote = (f"derived: FY {MINUS} 9M: {key} FY ending {fy['end']} = {fy_v} less 9M ending {y['end']} = {y_v} "
                     f"gives {v} {currency} millions, quarter ending {end}")
            cit = cit_for(key, fy, en["concept"], end, v, {"quote": quote, "inputs": [fy_cit.sha256_span_hash,
                                                                                      y_cit.sha256_span_hash]})
            fig, w3 = (None, w1 or w2) if fy_fig is None or y_fig is None else _figure(
                _derived_label(label, fy["end"], y["end"]), v, f"{currency} millions", f"quarter ending {end}", cit)
            if fig is None:
                data[key].append(None)
                missing.append({"item": f"{key}@{end}", "reason": w3})
                continue
            figures.extend([fy_fig, y_fig, fig])
            cits.extend([cit, fy_cit, y_cit])
            data[key].append(v)
            meta["derived"].append(key)
            derivations.append({"figure": fig.label, "period": fig.period, "formula": f"FY {MINUS} 9M",
                                "inputs": [fy_cit.to_dict(), y_cit.to_dict()]})
        filings.append({"accn": accn0, "url": _filing_url(cik, accn0) if accn0 else facts_url})
        qmeta.append(meta)
    st = {"cik": cik, "currency": currency, "years": ends, "period": "quarterly", "data": data, "filings": filings}
    return ToolResult({"ticker": tk, "period": "quarterly", "statements": st, "quarters": qmeta,
                       "comparisons": _quarter_comparisons(ends), "derivations": derivations, "missing": missing},
                      figures, _dedupe(cits), facts_url)


def _split_concept(concept: str) -> tuple[str, str]:
    if ":" in concept:
        tax, name = concept.split(":", 1)
        return tax, name
    return "us-gaap", concept


def sec_facts(ticker: str, concepts: list, periods: int = 5, *, sec=None, as_of=None, period: str = "annual") -> ToolResult:
    """``period="quarterly"``: 10-Q quarters (~90 days); Q4 is derived as FY minus 9M only when both are tagged."""
    tk = _check_ticker(ticker)
    period = _check_period(period)
    periods = _check_int("periods", periods, 1, 40 if period == "quarterly" else 20)
    if not isinstance(concepts, list) or not concepts or not all(isinstance(c, str) and CONCEPT_RE.fullmatch(c)
                                                                 for c in concepts):
        raise ToolError("concepts must be a non-empty list of XBRL concept names like 'us-gaap:Revenues'")
    cf = _sec(sec).company_facts(tk)
    if period == "quarterly":
        return _sec_facts_quarterly(tk, concepts, periods, cf, as_of)
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


def sec_statements(ticker: str, years: int = 5, *, sec=None, as_of=None, period: str = "annual") -> ToolResult:
    """``period="quarterly"``: headline lines per quarter from 10-Q facts (``years`` = years of quarters, 4 per year);
    ``data["comparisons"]`` names the latest quarter, the prior quarter and the same quarter a year earlier."""
    tk = _check_ticker(ticker)
    period = _check_period(period)
    years = _check_int("years", years, 1, 15)
    if period == "quarterly":
        return _sec_statements_quarterly(tk, years * 4, _sec(sec).company_facts(tk), as_of)
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


def _ratio_expr(name, refs):
    """Verifiable ratio expression over ``{label|period}`` references (no function calls; see verify._eval_expr)."""
    r = [f"{{{lab}|{per}}}" for lab, per in refs]
    if name == "revenue_growth":
        return f"({r[0]} - {r[1]}) / {r[1]}"
    if name == "debt_to_equity":
        return f"({r[0]} + {r[1]}) / {r[2]}"
    return f"{r[0]} / {r[1]}"


def ratios(ticker: str, years: int = 3, *, sec=None, as_of=None) -> ToolResult:
    """Derived ratios. Each ratio figure is ``units="ratio"``, its label carries the arithmetic over ``{label|period}``
    references, and its input lines are returned as cited figures too, so ``verify_figure`` recomputes the ratio from
    verified inputs (no unit scale is read from the ratio's own quote)."""
    from src.harness.connectors import fintk
    tk = _check_ticker(ticker)
    years = _check_int("years", years, 1, 15)
    st = _clip_statements(_sec(sec).financial_statements(tk, years), as_of)
    metrics = fintk.ratios(st) if st.get("years") else {"years": [], "metrics": {}}
    cur = st.get("currency") or "USD"
    labels = dict(HEADLINE)
    figures, cits, missing, derivations, inputs_seen = [], [], [], [], {}
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
            if name == "revenue_growth" and picked[1][2] <= 0:
                missing.append({"item": f"{name}@{end}", "reason": "prior-year revenue is not positive"})
                continue
            ins = [_stmt_citation(st, tk, k, j, v) for k, j, v in picked]
            in_figs, refs = [], []
            for (k, j, v), c in zip(picked, ins):
                lab = f"{tk} {labels.get(k, k)}"
                per = f"FY ending {st['years'][j]}"
                f_in, w = _figure(lab, v, f"{cur} millions", per, c)
                if f_in is None:
                    why = w
                    break
                in_figs.append(f_in)
                refs.append((lab, per))
            if why:
                missing.append({"item": f"{name}@{end}", "reason": why})
                continue
            lbl = f"{tk} derived: {name} = {_ratio_expr(name, refs)}"
            cit = _stmt_citation(st, tk, name, i, value, extra={"formula": formula, "inputs": [c.sha256_span_hash for c in ins]},
                                 quote=f"derived: {name} = {formula} = {value:.6g}")
            fig, why2 = _figure(lbl, value, "ratio", f"FY ending {end}", cit)
            if fig is None:
                missing.append({"item": f"{name}@{end}", "reason": why2})
                continue
            for f_in in in_figs:                             # the pool the verifier recomputes from
                inputs_seen.setdefault((f_in.label, f_in.period), f_in)
            figures.append(fig)
            cits.extend([cit] + ins)
            derivations.append({"figure": fig.label, "period": fig.period, "formula": formula,
                                "inputs": [c.to_dict() for c in ins]})
    figures.extend(inputs_seen.values())
    cik = st.get("cik")
    src = _cik_urls(cik)[1] if cik is not None else f"statements:{tk}"
    return ToolResult({"ticker": tk, "years": st.get("years", []), "metrics": metrics["metrics"],
                       "derivations": derivations, "missing": missing}, figures, _dedupe(cits), src)


# ------------------------------------------------------------------------------------------------ web
# F-01 (prompt-injection exfiltration): a model that has read untrusted text must not be able to smuggle it out through a
# URL. Three deterministic layers, none of them an LLM: (1) the host must be approved, (2) the URL shape is bounded,
# (3) no 24+ character run copied from a document seen in this job may appear in the URL.
MAX_URL_TAIL = 128          # query string and fragment, each
MAX_URL_PATH = 256
MAX_ENCODED = 64            # total characters of base64-, hex- or percent-encoded runs
SHINGLE = 24
MAX_SHINGLES = 2_000_000
_ENC_RES = (re.compile(r"(?:%[0-9A-Fa-f]{2})+"), re.compile(r"[0-9A-Fa-f]{16,}"), re.compile(r"[A-Za-z0-9+/]{24,}={0,2}"))
_NON_ALNUM = re.compile(r"[\W_]+")


def _norm(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def check_url_shape(url: str) -> None:
    """Shape rules that always apply, allowlisted host or not. Raises ``ToolError``."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise ToolError("url not approved: malformed url")
    if not host:
        raise ToolError("url not approved: no host")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise ToolError(f"url not approved: userinfo is not allowed ({host})")
    if len(parts.query) > MAX_URL_TAIL or len(parts.fragment) > MAX_URL_TAIL:
        raise ToolError(f"url not approved: query or fragment too long ({host})")
    if len(parts.path) > MAX_URL_PATH:
        raise ToolError(f"url not approved: path too long ({host})")
    tail = "?".join(x for x in (parts.path, parts.query) if x) + "#" + parts.fragment
    if sum(len(m.group(0)) for rx in _ENC_RES for m in rx.finditer(tail)) > MAX_ENCODED:
        raise ToolError(f"url not approved: encoded payload in url ({host})")


def _approved_urls(sources) -> list:
    from .workflows.review import approved_urls
    return approved_urls(sources)


class WebGuard:
    """Per-registry state for ``web_facts``: approved hosts, exact approved URLs and the shingles of document text seen."""

    def __init__(self, allow=None, request_urls=None, approved_sources=None, evidence=None):
        self.enforce = allow is not None or request_urls is not None or approved_sources is not None
        self.hosts: set[str] = set()
        self.urls: set[str] = set()      # exact URLs a human or the request named
        self.patterns: list[str] = []    # "*.example.com" entries
        self.shingles: set[int] = set()
        self.evidence = evidence
        for e in allow or ():
            self._add_host(e)
        self._add_urls(request_urls or ())
        self._add_urls(_approved_urls(approved_sources or ()))

    def _add_host(self, entry):
        if not isinstance(entry, str) or not entry.strip():
            return
        e = entry.strip().lower()
        if e.startswith("*."):
            self.patterns.append(e[2:])
        else:
            h = _host_of(e) if "://" in e else e.rstrip(".")
            if h:
                self.hosts.add(h)

    def approve(self, urls) -> None:
        """Explicitly listed (request or human-approved) URLs: the exact URL and its host become fetchable."""
        self.enforce = True
        self._add_urls(urls)

    def _add_urls(self, urls) -> None:
        for u in urls:
            if isinstance(u, str) and re.fullmatch(r"https?://\S+", u):
                self.urls.add(u)
                h = _host_of(u)
                if h:
                    self.hosts.add(h)

    def approve_sources(self, sources) -> None:
        """The approved pre-run source-review plan (``review.plan_sources`` output)."""
        self.approve(_approved_urls(sources))

    def host_ok(self, host: str) -> bool:
        return host in self.hosts or any(host == p or host.endswith("." + p) for p in self.patterns)

    def note_text(self, text) -> None:
        """Remember text from an untrusted document so none of it can leave inside a URL."""
        if not isinstance(text, str) or len(self.shingles) >= MAX_SHINGLES:
            return
        n = _norm(text[:2_000_000])
        for i in range(max(0, len(n) - SHINGLE + 1)):
            self.shingles.add(hash(n[i:i + SHINGLE]))

    def note_output(self, obj, _depth=0) -> None:
        if _depth > 8:
            return
        if isinstance(obj, str):
            self.note_text(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                self.note_output(v, _depth + 1)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                self.note_output(v, _depth + 1)

    def copies_document_text(self, url: str) -> bool:
        if not self.shingles:
            return False
        parts = urlsplit(url)
        n = _norm(unquote_plus(" ".join((parts.path, parts.query, parts.fragment))))
        return any(hash(n[i:i + SHINGLE]) in self.shingles for i in range(max(0, len(n) - SHINGLE + 1)))

    def check(self, url: str) -> None:
        """Raise ``ToolError`` unless ``url`` may be fetched; every refusal is appended to the evidence log."""
        host = _host_of(url) if isinstance(url, str) else ""
        try:
            if not isinstance(url, str) or not re.fullmatch(r"https?://\S+", url):
                raise ToolError("url must be an http(s) URL")
            check_url_shape(url)
            if self.enforce and url not in self.urls and not self.host_ok(host):
                raise ToolError(f"url not approved: {host}")
            if url not in self.urls and self.copies_document_text(url):
                raise ToolError(f"url not approved: contains text copied from a document ({host})")
        except ToolError as e:
            if self.evidence is not None and isinstance(url, str):
                self.evidence.append("web_facts.refused", {"url": url[:512]}, source=f"refused:{host or 'unknown'}",
                                     output={"refused": True, "reason": str(e), "host": host})
            raise


def web_facts(url: str, *, web=None, as_of=None, guard: WebGuard | None = None) -> ToolResult:
    if guard is not None:
        guard.check(url)
    else:
        if not isinstance(url, str) or not re.fullmatch(r"https?://\S+", url):
            raise ToolError("url must be an http(s) URL")
        check_url_shape(url)
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
_UNTRUSTED_TEXT_TOOLS = frozenset({"grid_query", "grid_cell", "xlsx_evaluate", "web_facts"})


def _obj(required, **props) -> dict:
    return {"type": "object", "required": list(required), "additionalProperties": False, "properties": props}


def build_registry(*, evidence=None, sec=None, web=None, grid_db=None, excel_root=None, as_of=None,
                   web_allow=None, request_urls=None, approved_sources=None) -> ToolRegistry:
    """The research agent's tool surface. ``evidence`` (an EvidenceBundle) gets one record per successful call.

    ``web_facts`` (F-01): once any of ``web_allow`` (org IR-domain allowlist: hosts, URLs or ``*.host``),
    ``request_urls`` (URLs the request lists) or ``approved_sources`` (the approved source-review plan) is given, only
    those hosts may be fetched; anything else raises ``ToolError("url not approved: <host>")``. With none given the host
    check is off (legacy), so callers that run untrusted text through a model must pass them or call
    ``reg.web_guard.approve_sources(...)``. URL shape and document-text-copy checks always apply, and every refusal is
    logged to ``evidence``. ``reg.web_guard.note_text`` records extra untrusted text (emails, VDR text).
    """
    if as_of is not None and not _valid_date(as_of):
        raise ToolError(f"as_of must be YYYY-MM-DD, got {as_of!r}")
    reg = ToolRegistry()
    guard = WebGuard(web_allow, request_urls, approved_sources, evidence)
    reg.web_guard = guard

    def wrap(name, fn):
        def run(**kw):
            res = fn(**kw).to_dict()
            if name in _UNTRUSTED_TEXT_TOOLS:
                guard.note_output({"d": res["data"], "q": [c.get("quote") for c in res["citations"]]})
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
        ("sec_facts", lambda ticker, concepts, periods=5, period="annual": sec_facts(
             ticker, concepts, periods, sec=sec, as_of=as_of, period=period),
         _obj(["ticker", "concepts"], ticker=tickers, concepts={"type": "array", "items": {"type": "string"}},
              periods={"type": "integer"}, period={"type": "string", "enum": list(PERIODS)}),
         "XBRL values (us-gaap:Revenues, ...) from SEC company facts, one cited figure per fiscal year or, with "
         "period=quarterly, per quarter (Q4 derived as FY minus 9M only when both are tagged)."),
        ("sec_statements", lambda ticker, years=5, period="annual": sec_statements(ticker, years, sec=sec, as_of=as_of, period=period),
         _obj(["ticker"], ticker=tickers, years={"type": "integer"}, period={"type": "string", "enum": list(PERIODS)}),
         "3-statement data in USD millions plus cited headline figures; period=quarterly gives 10-Q quarters."),
        ("sec_filings", lambda ticker, form="10-K", n=3: sec_filings(ticker, form, n, sec=sec, as_of=as_of),
         _obj(["ticker"], ticker=tickers, form={"type": "string"}, n={"type": "integer"}),
         "Recent SEC filings (form, filing date, accession, url)."),
        ("ratios", lambda ticker, years=3: ratios(ticker, years, sec=sec, as_of=as_of),
         _obj(["ticker"], ticker=tickers, years={"type": "integer"}),
         "Derived ratios; each figure cites every input line it is computed from."),
        ("web_facts", lambda url: web_facts(url, web=web, as_of=as_of, guard=guard),
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
