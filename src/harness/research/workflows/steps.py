"""Deterministic assemblers and text steps for the S6.1 workflows.

Rules (PLAN S6.2, D-S6-04): every number on a slide comes from a figure the verifier can re-check. Slides are built only
from figures that pass ``verify_figure`` now (``usable``); anything else stays in ``ctx.figures`` so ``verify_result``
reports it in ``rejected``. Titles never contain numbers other than years. SlideSpec carries the archetype payload in
``data["archetype_blocks"]`` (see docs/interfaces-s6/workflows.md).
"""
from __future__ import annotations

import math
import re
from statistics import median

from om.contracts import ContractError, action_title_lint, sha256_hex
from src.harness.evidence import canonical_bytes
from src.harness.research.verify import verify_figure

from .base import ASSEMBLERS, assembler, text_step

HEADLINE = (("Revenue", "revenue"), ("Gross profit", "gross_profit"), ("Operating income", "ebit"),
            ("Net income", "net_income"), ("Total assets", "assets"), ("Cash and equivalents", "cash"),
            ("Cash from operations", "cfo"), ("Capital expenditure (payments, as reported)", "capex"))
RATIOS = (("Gross margin", "Gross profit", "Revenue"), ("Operating margin", "Operating income", "Revenue"),
          ("Net margin", "Net income", "Revenue"))
EPS_CONCEPT = "us-gaap:EarningsPerShareDiluted"
_SCALES = (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3))


# ------------------------------------------------------------------------------------------------ formatting
def sig(v: float, tol: float = 0.003, maxdp: int = 4) -> str:
    """Smallest number of decimals whose rounding stays within ``tol`` of v (so the printed value still verifies)."""
    a = abs(v)
    for dp in range(maxdp + 1):
        s = f"{a:,.{dp}f}"
        if a == 0 or abs(float(s.replace(",", "")) - a) <= tol * a:
            return s
    return f"{a:,.{maxdp}f}"


def fmt(fig: dict, signed: bool = False) -> str:
    v, u = float(fig["value"]), (fig.get("units") or "").lower()
    sign = "-" if v < 0 else ("+" if signed else "")
    if "%" in u or "percent" in u:
        return f"{sign}{sig(v)}%"
    if "bps" in u:
        return f"{sign}{sig(v, maxdp=1)} bps"
    if "million" in u:
        return f"{sign}${sig(v)}m"
    if "billion" in u:
        return f"{sign}${sig(v)}bn"
    if "thousand" in u:
        return f"{sign}${sig(v)}k"
    if "shares" in u:
        return f"{sign}${sig(v, maxdp=3)}"
    if u in ("usd", "eur", "gbp"):
        a = abs(v)
        if a >= 1e9:
            return f"{sign}${sig(v / 1e9)}bn"
        if a >= 1e6:
            return f"{sign}${sig(v / 1e6)}m"
        return f"{sign}${sig(v)}"
    if u.endswith("x") or "multiple" in u:
        return f"{sign}{sig(v)}x"
    return f"{sign}{sig(v)}"


def fy(end: str) -> str:
    return f"FY{str(end)[:4]}"


def _fp(end: str) -> str:
    return f"FY ending {end}"


# ------------------------------------------------------------------------------------------------ figure helpers
def usable(ctx, fig: dict) -> bool:
    cache = ctx.__dict__.setdefault("_usable", {})
    k = sha256_hex(canonical_bytes(fig))
    if k not in cache:
        try:
            cache[k] = verify_figure(fig, ctx.resolver, figures=ctx.figures).ok
        except Exception:       # noqa: BLE001
            cache[k] = False
    return cache[k]


def add_figure(ctx, fig: dict, *, ingest: bool = True) -> dict:
    """Candidate figure for verification. ``ingest`` registers its quote as a source snapshot: only for figures this
    code computed from verified inputs, never for caller-supplied figures or document numbers."""
    if ingest:
        ctx._ingest({"figures": [fig], "data": {}})
    else:
        ctx.figures.append(fig)
    return fig


def derived(ctx, label, value, units, end, quote_expr, inputs, tag, period=None):
    """A figure computed from verified inputs; the quote spells out the arithmetic."""
    if not all(usable(ctx, i) for i in inputs) or not math.isfinite(value):
        return None
    v = float(f"{value:.6g}")
    disp = f"{v:g}{'%' if units == '%' else ' bps' if units == 'bps' else ''}"
    quote = f"{label} = {quote_expr} = {disp}"
    base = inputs[0]["citation"]
    cit = {"doc_id": base["doc_id"], "sha256_span_hash": sha256_hex(canonical_bytes(
        {"derived": tag, "label": label, "end": end, "inputs": [i["citation"]["sha256_span_hash"] for i in inputs]})),
        "quote": quote, "as_of": end, "url": base.get("url") or base.get("source_url")}
    if not cit["url"]:
        return None
    fig = {"label": label, "value": v, "units": units, "period": period or _fp(end), "citation": cit, "v": 1}
    add_figure(ctx, fig)
    return fig if usable(ctx, fig) else None


def _pct(num, den):
    return 100.0 * num["value"] / den["value"]


_DER_LABEL = re.compile(r"^(?P<base>.+?) derived: FY")
_FY_IN = re.compile(r"FY ending (\d{4}-\d{2}-\d{2})")
_YTD_IN = re.compile(r"9M ending (\d{4}-\d{2}-\d{2})")


def _qper(end: str) -> str:
    return f"quarter ending {end}"


def _make_q4(ctx, idx, tk, f):
    """Replace a tool-derived Q4 figure (FY - 9M; its label carries braces and dates) by a figure with a clean label
    that says it is derived and cites both verified inputs (fiscal year, nine months). -> (fig, inputs, base, name,
    end) or None."""
    m = _DER_LABEL.match(f["label"])
    if not m:
        return None
    base, lab = m.group("base"), f["label"]
    fe, ye = _FY_IN.search(lab), _YTD_IN.search(lab)
    fy_f = idx.get((base, f"FY ending {fe.group(1)}")) if fe else None
    y_f = idx.get((f"{base} 9M YTD", f"9M ending {ye.group(1)}")) if ye else None
    if not (fy_f and y_f) or abs(fy_f["value"] - y_f["value"] - f["value"]) > 1e-6:
        return None
    name = base[len(tk) + 1:]
    end = f["period"][len("quarter ending "):]
    d = derived(ctx, f"{base} fourth quarter, derived from fiscal year less nine months", f["value"], f["units"], end,
                f"{name} fiscal year - {name} nine months = {fy_f['value']:g} - {y_f['value']:g}",
                [fy_f, y_f], "q4", period=f["period"])
    return (d, (fy_f, y_f), base, name, end) if d else None


class Series:
    """Per-ticker view over statement figures and the ratios derived from them. Annual statements are keyed by
    ``FY ending <date>``; quarterly ones (``period="quarterly"``) by ``quarter ending <date>``, with a Q4 derived as
    FY minus 9M indexed under the plain line name (``is_derived`` tells them apart)."""

    def __init__(self, ctx, tk, res):
        data = res.get("data") or {}
        st = data.get("statements") or {}
        self.tk, self.ends = tk, [str(y) for y in st.get("years", [])]
        self.quarterly = st.get("period") == "quarterly"
        self.comp = data.get("comparisons") or {}
        self.derived_q, self.q4_inputs = set(), {}
        self.idx = {}
        for f in res.get("figures", []):
            self.idx[(f["label"], f["period"])] = f
        self.ctx = ctx
        if self.quarterly:
            self._q4_figures(res)
        for end in self.ends:
            for name, n, d in RATIOS:
                a, b = self.get(n, end), self.get(d, end)
                if a and b and b["value"] > 0 and usable(ctx, a) and usable(ctx, b):
                    derived(ctx, f"{tk} {name}", _pct(a, b), "%", end,
                            f"{a['label']} / {b['label']} = {a['value']:g} / {b['value']:g}",
                            [a, b], name, period=self.per(end))
        if not self.quarterly:
            for prev, cur in zip(self.ends, self.ends[1:]):
                a, b = self.get("Revenue", prev), self.get("Revenue", cur)
                if a and a["value"] > 0 and b:
                    derived(ctx, f"{tk} Revenue growth", 100.0 * (b["value"] / a["value"] - 1.0), "%", cur,
                            f"{b['label']} / {a['label']} - 1 = {b['value']:g} / {a['value']:g} - 1", [a, b], "growth")
        for f in list(ctx.figures):          # derived figures were appended to ctx.figures: index them too
            self.idx.setdefault((f["label"], f["period"]), f)

    def per(self, end):
        return _qper(end) if self.quarterly else _fp(end)

    def get(self, name, end):
        f = self.idx.get((f"{self.tk} {name}", self.per(end)))
        return f if f and usable(self.ctx, f) else None

    def is_derived(self, name, end) -> bool:
        """True for a Q4 line derived as FY minus 9M (quarterly statements only)."""
        return (f"{self.tk} {name}", self.per(end)) in self.derived_q

    def inputs(self, name, end) -> list:
        """The two cited inputs (FY, 9M YTD) of a derived Q4 line; empty for a directly tagged figure."""
        return list(self.q4_inputs.get((name, end), ()))

    def _q4_figures(self, res):
        for f in res.get("figures", []):
            r = _make_q4(self.ctx, self.idx, self.tk, f)
            if r:
                d, ins, base, name, end = r
                self.idx[(base, f["period"])] = d
                self.derived_q.add((base, f["period"]))
                self.q4_inputs[(name, end)] = ins

    def series(self, name):
        return [(e, self.get(name, e)) for e in self.ends if self.get(name, e)]

    def latest(self, name):
        s = self.series(name)
        return s[-1] if s else (None, None)


def statements(ctx, step="statements") -> list:
    out = ctx.outputs.get(step)
    items = out if isinstance(out, list) else ([out] if out else [])
    res = []
    for r in items:
        if isinstance(r, dict) and (r.get("data") or {}).get("statements", {}).get("years"):
            tk = (r["data"].get("ticker") or r["data"]["statements"].get("ticker") or "").upper()
            res.append(Series(ctx, tk, r))
    return res


def _cites(figs, n=4):
    out, seen = [], set()
    for f in figs:
        c = f["citation"]
        if c["sha256_span_hash"] not in seen:
            seen.add(c["sha256_span_hash"])
            out.append(c)
    return out[:n]


def _slide(ctx, wf, sid, archetype, layout, title, figs, *, data=None, blocks=None, bullets=None, facts=(),
           cites=4):
    figs = [f for f in figs if f]
    as_of = max((f["citation"]["as_of"] for f in figs), default=None)
    s = {"id": sid, "layout": layout, "title": title, "action_title": title, "bullets": bullets or [],
         "sources": _cites(figs, cites), "citations": _cites(figs, cites), "data": data or {}, "blocks": blocks or []}
    if archetype:
        s["archetype"] = archetype
    if as_of:
        s["as_of"] = as_of
    ctx.slides.append(s)
    ctx.slide_meta[sid] = {"template": title, "facts": list(facts)}
    return s


def _dir(a, b):
    if a is None or b is None:
        return None
    return "up" if b > a * 1.0005 else "down" if b < a * 0.9995 else "flat"


def _claim(tk, y, rev_dir, ebit):
    base = {"up": "increased revenue", "down": "reported lower revenue", "flat": "reported flat revenue",
            None: "reported results"}[rev_dir]
    tail = "" if ebit is None else (" while operating income stayed positive" if ebit > 0
                                    else " while operating income turned negative")
    return f"{tk} {base}{tail} in {fy(y)}"


def _excel(ctx, s: Series, model_type="three_statement"):
    inputs = {}
    for end in s.ends:
        for name, key in HEADLINE:
            f = s.get(name, end)
            if f:
                inputs[f"{key}_{end[:4]}"] = f
    if inputs:
        ctx.excel.append({"v": 1, "model_type": model_type, "ticker": s.tk, "inputs": inputs})


def _kpi_slide(ctx, wf, s, names, sid, tail_title=None, ctxtext="as reported"):
    y_figs = []
    for name in names:
        e, f = s.latest(name)
        if f:
            y_figs.append((name, e, f))
    if not y_figs:
        return None
    end = max(e for _, e, _ in y_figs)
    y_figs = [x for x in y_figs if x[1] == end]
    figs = [f for _, _, f in y_figs]
    rev_e, rev = s.latest("Revenue")
    prev = s.get("Revenue", s.ends[s.ends.index(rev_e) - 1]) if rev and s.ends.index(rev_e) > 0 else None
    _, ebit = s.latest("Operating income")
    title = tail_title or _claim(s.tk, end, _dir(prev["value"] if prev else None, rev["value"] if rev else None),
                                 ebit["value"] if ebit else None)
    if 3 <= len(figs) <= 5:
        kpis = [{"label": f["label"], "value": fmt(f), "context": f"{fy(end)}, {ctxtext}"} for f in figs]
        return _slide(ctx, wf, sid, "kpi_row", "table", title, figs,
                      data={"archetype_blocks": {"kpis": kpis, "highlight": 0,
                                                 "subtitle": "Latest fiscal year, USD millions"}},
                      facts=[f["label"] for f in figs])
    rows = [{"label": f["label"], "value": fmt(f), "period": fy(end)} for f in figs]
    return _slide(ctx, wf, sid, None, "table", title, figs,
                  blocks=[{"type": "table", "columns": ["Metric", "Value", "Period"], "rows": rows}],
                  facts=[f["label"] for f in figs])


# ------------------------------------------------------------------------------------------------ company_profile
def _business_bullets(ctx):
    res = ctx.outputs.get("company_page")
    if not res:
        return None, []
    page = (res.get("data") or {}).get("page") or {}
    text = " ".join(str(page.get(k) or "") for k in ("title", "snippet"))
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", str(page.get("snippet") or "")) if x.strip()]
    keep = [x.rstrip(".") for x in sents if not re.search(r"\d", x)][:3]
    figs = res.get("figures") or []
    cit = {"doc_id": f"web:{sha256_hex(text.encode())[:16]}", "sha256_span_hash": sha256_hex(text.encode()),
           "quote": str(page.get("snippet") or "")[:500], "url": page.get("url") or res.get("source"),
           "as_of": (figs[0]["citation"]["as_of"] if figs else (page.get("published") or "")[:10] or None)}
    return (cit if cit["url"] and cit["as_of"] else None), keep


@assembler("company_profile")
def asm_company_profile(ctx):
    n = 0
    for s in statements(ctx):
        tk = s.tk
        k = tk.lower()
        _kpi_slide(ctx, "company_profile", s, [h[0] for h in HEADLINE[:3]] + ["Net income", "Cash from operations"],
                   f"company_profile_{k}_kpis")
        ends = [e for e in s.ends if s.get("Revenue", e)]
        if len(ends) >= 3:
            periods = ends[-5:]
            rows = []
            for name, fmt_ in (("Revenue", "usd_m"), ("Operating income", "usd_m"), ("Net income", "usd_m"),
                               ("Gross margin", "pct"), ("Operating margin", "pct"), ("Net margin", "pct")):
                fs = [s.get(name, e) for e in periods]
                if all(fs):
                    rows.append((name, fmt_, fs))
            if len(rows) >= 3:
                kp = [{"name": f"{fs[0]['label']} ({'$m' if f_ == 'usd_m' else '%'})", "format": f_,
                       "values": [f["value"] for f in fs]} for _, f_, fs in rows]
                allf = [f for _, _, fs in rows for f in fs]
                om_ = s.series("Operating margin")
                d = "stayed flat" if len(om_) < 2 else ("expanded" if om_[-1][1]["value"] > om_[0][1]["value"] + 0.05
                                                         else "narrowed" if om_[-1][1]["value"] < om_[0][1]["value"] - 0.05
                                                         else "stayed flat")
                t = f"{tk} margins {d} across the reported years" if om_ else f"{tk} reported its financial history"
                _slide(ctx, "company_profile", f"company_profile_{k}_financials", "scorecard", "table", t, allf,
                       data={"archetype_blocks": {"subtitle": "Annual financials and ratios, USD millions",
                                                  "periods": [fy(e) for e in periods], "kpis": kp,
                                                  "takeaway": f"{tk} financials are as reported in SEC filings"}},
                       facts=[r[0] for r in rows])
        if not any(x["id"] == f"company_profile_{k}_financials" for x in ctx.slides) and ends:
            trs, allf = [], []
            for name in ("Revenue", "Gross profit", "Operating income", "Net income", "Gross margin",
                         "Operating margin", "Net margin"):
                fs = [s.get(name, e) for e in ends[-5:]]
                if all(fs):
                    trs.append({"metric": name, "cells": [{"label": f["label"], "value": fmt(f), "period": fy(e)}
                                                         for e, f in zip(ends[-5:], fs)]})
                    allf += fs
            if trs:
                _slide(ctx, "company_profile", f"company_profile_{k}_financials", None, "table",
                       f"{tk} reported its financial history", allf,
                       blocks=[{"type": "table", "columns": ["Metric"] + [fy(e) for e in ends[-5:]], "rows": trs}])
        rv = s.series("Revenue")
        if rv:
            figs = [f for _, f in rv][-5:]
            e, last = rv[-1]
            tk3 = [f"{last['label']} was {fmt(last)} in {fy(e)}"]
            for nm in ("Revenue growth", "Gross margin", "Operating margin", "Net margin"):
                ee, f = s.latest(nm)
                if f and len(tk3) < 3:
                    tk3.append(f"{f['label']} was {fmt(f)} in {fy(ee)}")
                    figs.append(f)
            while len(tk3) < 3:
                tk3.append("All figures are as reported in SEC filings, in USD millions")
            tk3 = tk3[:3]
            up = len(rv) > 1 and rv[-1][1]["value"] > rv[0][1]["value"]
            t = f"{tk} revenue {'increased' if up else 'decreased'} over the reported years"
            _slide(ctx, "company_profile", f"company_profile_{k}_revenue", "chart_takeaways", "chart", t, figs,
                   data={"archetype_blocks": {"subtitle": "Revenue by fiscal year, USD millions",
                                              "chart": {"type": "column", "categories": [fy(e) for e, _ in rv][-5:],
                                                        "series": [{"name": f"{rv[0][1]['label']} ($m)",
                                                                    "values": [f["value"] for _, f in rv][-5:]}]},
                                              "takeaways": tk3}},
                   facts=[last["label"]])
        _excel(ctx, s)
        n += 1
    cit, bullets = _business_bullets(ctx)
    if cit and bullets:
        tk = (ctx.request.get("tickers") or ["The company"])[0].upper()
        sl = _slide(ctx, "company_profile", f"company_profile_{tk.lower()}_business", None, "bullets",
                    f"{tk} published this description of its business", [], bullets=bullets)
        sl["sources"], sl["citations"], sl["as_of"] = [cit], [cit], cit["as_of"]
    return {"tickers": n}


# ------------------------------------------------------------------------------------------------ earnings_recap
@assembler("earnings_recap")
def asm_earnings_recap(ctx):
    eps_res = ctx.outputs.get("eps")
    eps_all = (eps_res or {}).get("figures") or []
    qs = statements(ctx, "quarterly_statements")
    if qs:
        for s in qs:
            _recap_quarterly(ctx, s, eps_all)
        _recap_guidance(ctx)
        return {}
    eps_figs = [f for f in eps_all if f["label"].endswith("EarningsPerShareDiluted")]
    for s in statements(ctx):
        tk, k = s.tk, s.tk.lower()
        if len(s.ends) < 2:
            ctx.notes.append(f"{tk}: fewer than two fiscal years; no comparison")
            continue
        cur, prior = s.ends[-1], s.ends[-2]
        for f in eps_figs:
            if f["label"].startswith(tk + " ") and usable(ctx, f):
                s.idx[(f["label"], f["period"])] = f
        eps_by_end = {f["citation"]["as_of"]: f for f in eps_figs if f["label"].startswith(tk + " ") and usable(ctx, f)}
        names = ("Revenue", "Gross profit", "Operating income", "Net income")
        kpi_names = [n for n in names if s.get(n, cur)]
        figs = [s.get(n, cur) for n in kpi_names]
        if eps_by_end.get(cur):
            figs.append(eps_by_end[cur])
        figs = figs[:5]
        _, nd = s.latest("Net income")
        rev, rev_p = s.get("Revenue", cur), s.get("Revenue", prior)
        if 3 <= len(figs):
            kp = [{"label": f["label"], "value": fmt(f), "context": f"{fy(cur)}, as reported"} for f in figs]
            _slide(ctx, "earnings_recap", f"earnings_recap_{k}_kpis", "kpi_row", "table",
                   _claim(tk, cur, _dir(rev_p["value"] if rev_p else None, rev["value"] if rev else None),
                          s.get("Operating income", cur)["value"] if s.get("Operating income", cur) else None),
                   figs, data={"archetype_blocks": {"kpis": kp, "highlight": 0,
                                                    "subtitle": "Latest fiscal year, USD millions"}})
        rows, used = [], []
        for n in kpi_names:
            a, b = s.get(n, cur), s.get(n, prior)
            if not (a and b):
                continue
            row = {"label": a["label"], "latest": {"label": a["label"], "value": fmt(a)},
                   "prior": {"label": b["label"], "value": fmt(b)}}
            used += [a, b]
            if b["value"] > 0 and a["value"] > 0:
                ch = derived(ctx, f"{a['label']} change vs prior year", 100 * (a["value"] / b["value"] - 1), "%", cur,
                             f"{a['label']} / {b['label']} - 1 = {a['value']:g} / {b['value']:g} - 1", [a, b], "chg")
                if ch:
                    row["change"] = {"label": ch["label"], "value": fmt(ch, signed=True)}
                    used.append(ch)
            rows.append(row)
        for n in ("Gross margin", "Operating margin"):
            a, b = s.get(n, cur), s.get(n, prior)
            if a and b:
                ch = derived(ctx, f"{a['label']} change vs prior year", (a["value"] - b["value"]) * 100, "bps", cur,
                             f"({a['label']} - {b['label']}) x 100 = ({a['value']:g} - {b['value']:g}) x 100",
                             [a, b], "bps")
                row = {"label": a["label"], "latest": {"label": a["label"], "value": fmt(a)},
                       "prior": {"label": b["label"], "value": fmt(b)}}
                used += [a, b]
                if ch:
                    row["change"] = {"label": ch["label"], "value": fmt(ch, signed=True)}
                    used.append(ch)
                rows.append(row)
        if eps_by_end.get(cur) and eps_by_end.get(prior):
            a, b = eps_by_end[cur], eps_by_end[prior]
            rows.append({"label": a["label"], "latest": {"label": a["label"], "value": fmt(a)},
                         "prior": {"label": b["label"], "value": fmt(b)}})
            used += [a, b]
        if rows:
            ni, nip = s.get("Net income", cur), s.get("Net income", prior)
            d = _dir(nip["value"], ni["value"]) if ni and nip else None
            t = {"up": f"{tk} net income increased versus the prior year",
                 "down": f"{tk} net income decreased versus the prior year",
                 "flat": f"{tk} net income was unchanged versus the prior year"}.get(
                d, f"{tk} reported its latest results against the prior year")
            _slide(ctx, "earnings_recap", f"earnings_recap_{k}_compare", None, "table", t, used,
                   blocks=[{"type": "table", "columns": ["Metric", "Latest", "Prior", "Change"], "rows": rows,
                            "periods": {"latest": fy(cur), "prior": fy(prior)}}],
                   facts=[r["label"] for r in rows])
        _excel(ctx, s)
    _recap_guidance(ctx)
    return {}


def _recap_guidance(ctx):
    g = ctx.outputs.get("guidance")
    if g and g.get("figures"):
        gf = [f for f in g["figures"] if usable(ctx, f)]
        if gf:
            rows = [{"label": f["label"], "value": fmt(f), "source": f["citation"].get("url") or ""} for f in gf[:8]]
            _slide(ctx, "earnings_recap", "earnings_recap_guidance", None, "table",
                   "Management guidance was published with the latest results", gf[:8],
                   blocks=[{"type": "table", "columns": ["Item", "Value", "Source"], "rows": rows}])
    else:
        ctx.notes.append("no sourced guidance: slide omitted")


# ------------------------------------------------------------------------------------------------ quarterly recap
_Q_LINES = ("Revenue", "Gross profit", "Operating income", "Net income")
_Q_MARGINS = (("Gross margin", "Gross profit"), ("Operating margin", "Operating income"))
_NA = "not available"
_WHICH = (("latest", "latest quarter"), ("prior", "prior quarter"), ("year_ago", "year-ago quarter"))
_EPS_RX = re.compile(r"^(?P<base>.+?EarningsPerShareDiluted)(?: derived: FY.*)?$")


def _q_eps(ctx, s, eps_all):
    """Diluted EPS per quarter end from the quarterly ``sec_facts`` output: {end: (figure, derived?)}, verified only.
    A Q4 EPS derived as FY less 9M is re-issued with a clean label and both inputs cited."""
    pool = {(f["label"], f["period"]): f for f in eps_all}
    want = f"{s.tk} EarningsPerShareDiluted"
    out, inputs = {}, {}
    for f in eps_all:
        if not f["period"].startswith("quarter ending"):
            continue
        end, fig, der = f["period"][len("quarter ending "):], f, False
        m = _DER_LABEL.match(f["label"])
        if m:
            r = _make_q4(ctx, pool, s.tk, f) if m.group("base") == want else None
            if not r:
                continue
            fig, ins, _, _, _ = r
            der = True
            inputs[end] = ins
        elif f["label"] != want:
            continue
        if usable(ctx, fig):
            out[end] = (fig, der)
    return out, inputs


def _chg(ctx, s, name, a, b, end, tag, margin):
    """Change of the latest figure against a comparison figure, computed in code from verified inputs."""
    if margin:
        return derived(ctx, f"{s.tk} {name} change vs {tag}", (a["value"] - b["value"]) * 100, "bps", end,
                       f"({name} latest - {name} {tag}) x 100 = ({a['value']:g} - {b['value']:g}) x 100",
                       [a, b], "bps", period=_qper(end))
    if a["value"] > 0 and b["value"] > 0:
        return derived(ctx, f"{s.tk} {name} change vs {tag}", 100 * (a["value"] / b["value"] - 1), "%", end,
                       f"{name} latest / {name} {tag} - 1 = {a['value']:g} / {b['value']:g} - 1",
                       [a, b], "chg", period=_qper(end))
    return None


def _recap_quarterly(ctx, s, eps_all):
    tk, k = s.tk, s.tk.lower()
    comp = s.comp or {}
    ends = {w: comp.get({"prior": "prior_quarter"}.get(w, w)) for w, _ in _WHICH}
    cur = ends["latest"]
    if not cur:
        ctx.notes.append(f"{tk}: no quarters in the data; no comparison")
        return
    eps, eps_inputs = _q_eps(ctx, s, eps_all)
    notes, used, rows, derived_cells = [], [], [], []
    names = [(n, False) for n in _Q_LINES] + [(n, True) for n, _ in _Q_MARGINS]
    comp_of = dict(_Q_MARGINS)

    def support(name, end, margin):
        base = [comp_of[name], "Revenue"] if margin else [name]
        out = []
        for b in base:
            out += s.inputs(b, end)
        return out

    def is_der(name, end, margin):
        return any(s.is_derived(b, end) for b in ([comp_of[name], "Revenue"] if margin else [name]))

    def row_for(name, get, margin, eps_row=False):
        figs = {w: (get(ends[w]) if ends[w] else None) for w, _ in _WHICH}
        if not any(figs.values()):
            notes.append(f"{name}: not available for any compared quarter, row omitted")
            return
        row = {"label": name}
        for w, human in _WHICH:
            f = figs[w]
            if f:
                row[w] = {"label": f["label"], "value": fmt(f)}
                used.append(f)
                if eps_row:
                    der = eps[ends[w]][1]
                    used.extend(eps_inputs.get(ends[w], ()))
                else:
                    der = is_der(name, ends[w], margin)
                    used.extend(support(name, ends[w], margin))
                if der:
                    derived_cells.append(f"{name}, {human}")
            else:
                row[w] = _NA
                notes.append(f"{name}: {human} {_NA} "
                             + ("(comparison quarter not found in the filings)" if not ends[w]
                                else "(not tagged or not verifiable)"))
        for key, w, tag in (("change_prior", "prior", "prior quarter"), ("change_year_ago", "year_ago", "year-ago quarter")):
            b = figs[w]
            ch = _chg(ctx, s, name, figs["latest"], b, cur, tag, margin) if b and figs["latest"] else None
            if ch:
                row[key] = {"label": ch["label"], "value": fmt(ch, signed=True)}
                used.append(ch)
            else:
                row[key] = _NA
        rows.append(row)

    for name, margin in names:
        row_for(name, (lambda e, n=name: s.get(n, e)), margin)
    if eps:
        row_for("Diluted EPS", lambda e: (eps.get(e) or (None,))[0], False, eps_row=True)
    else:
        notes.append("Diluted EPS: not tagged for the quarters in the data")
    if not rows:
        ctx.notes.append(f"{tk}: no verified quarterly lines; no recap")
        return
    cols = ["Metric", "Latest quarter", "Prior quarter", "Year-ago quarter", "Change vs prior quarter",
            "Change vs year-ago quarter"]
    bullets = list(dict.fromkeys(notes))
    if derived_cells:
        bullets.append("Derived fourth-quarter figures (fiscal year minus nine months, both inputs cited): "
                       + "; ".join(dict.fromkeys(derived_cells)))
    # KPI slide: latest quarter
    kfigs = [r for r in (s.get(n, cur) for n in _Q_LINES) if r]
    if eps.get(cur):
        kfigs.append(eps[cur][0])
    kfigs = kfigs[:5]
    rev, rev_p = s.get("Revenue", cur), (s.get("Revenue", ends["prior"]) if ends["prior"] else None)
    if len(kfigs) >= 3:
        kp = [{"label": f["label"], "value": fmt(f), "context": "latest quarter, as reported"} for f in kfigs]
        d = _dir(rev_p["value"] if rev_p else None, rev["value"] if rev else None)
        t = {"up": f"{tk} revenue increased versus the prior quarter",
             "down": f"{tk} revenue decreased versus the prior quarter",
             "flat": f"{tk} revenue was unchanged versus the prior quarter"}.get(d, f"{tk} reported its latest quarter")
        sup = [x for f in kfigs for x in (s.inputs(n, cur) for n in _Q_LINES if s.get(n, cur) is f) for x in x]
        _slide(ctx, "earnings_recap", f"earnings_recap_{k}_kpis", "kpi_row", "table", t, kfigs + sup,
               data={"archetype_blocks": {"kpis": kp, "highlight": 0, "subtitle": "Latest quarter, USD millions"}},
               cites=12)
    ni, nip = s.get("Net income", cur), (s.get("Net income", ends["prior"]) if ends["prior"] else None)
    d = _dir(nip["value"], ni["value"]) if ni and nip else None
    t = {"up": f"{tk} net income increased versus the prior quarter and the year-ago quarter",
         "down": f"{tk} net income decreased versus the prior quarter",
         "flat": f"{tk} net income was unchanged versus the prior quarter"}.get(
        d, f"{tk} reported its latest quarter against the prior quarter and the year-ago quarter")
    if d == "up":
        ya = s.get("Net income", ends["year_ago"]) if ends["year_ago"] else None
        if not (ya and ni["value"] > ya["value"]):
            t = f"{tk} net income increased versus the prior quarter"
    _slide(ctx, "earnings_recap", f"earnings_recap_{k}_compare", None, "table", t, used,
           blocks=[{"type": "table", "columns": cols, "rows": rows,
                    "periods": {w: _qper(e) for w, e in ends.items() if e}}],
           bullets=bullets, facts=[r["label"] for r in rows], cites=40)



# ------------------------------------------------------------------------------------------------ buyer_list
def prepare_buyer_list(request: dict) -> dict:
    cands, seen = [], set()
    for c in (request.get("options") or {}).get("candidates") or []:
        if not isinstance(c, dict) or not str(c.get("name", "")).strip():
            continue
        name = str(c["name"]).strip()
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        t = str(c.get("type", "strategic")).lower()
        cands.append({"name": name, "type": t if t in ("strategic", "financial") else "strategic",
                      "ticker": (str(c["ticker"]).upper() if c.get("ticker") else None),
                      "metrics": [m for m in c.get("metrics") or [] if isinstance(m, dict)], "source": "input"})
    return {"candidates": cands[:25], "candidate_tickers": list(dict.fromkeys(c["ticker"] for c in cands if c["ticker"]))[:25]}


def _usd_m(f):
    u, v = (f.get("units") or "").lower(), float(f["value"])
    for word, sc in _SCALES:
        if word in u:
            return v * sc / 1e6
    return v / 1e6 if u in ("usd", "") else v


def _score(cap, margin, headroom, deal):
    c = min(1.0, cap / deal) if deal else min(1.0, cap / 50000.0)
    m = max(0.0, min(1.0, (margin or 0.0) / 30.0))
    h = 0.5 if headroom is None else max(0.0, min(1.0, headroom))
    return round(0.5 * c + 0.3 * h + 0.2 * m, 6)


@assembler("buyer_list")
def asm_buyer_list(ctx):
    cands = [dict(c) for c in ctx.plan.get("candidates", [])]
    by_tk = {}
    for r in ctx.outputs.get("candidate_statements") or []:
        if isinstance(r, dict) and (r.get("data") or {}).get("statements", {}).get("years"):
            by_tk[(r["data"].get("ticker") or "").upper()] = Series(ctx, (r["data"].get("ticker") or "").upper(), r)
    g = ctx.outputs.get("grid")
    if g:
        for row in ((g.get("data") or {}).get("rows") or []):
            if isinstance(row, dict) and str(row.get("name") or row.get("company") or "").strip():
                nm = str(row.get("name") or row.get("company")).strip()
                if nm.casefold() not in {c["name"].casefold() for c in cands}:
                    t = str(row.get("type", "strategic")).lower()
                    cands.append({"name": nm, "type": t if t in ("strategic", "financial") else "strategic",
                                  "ticker": None, "metrics": [], "source": "grid"})
        ctx.figures.extend(g.get("figures") or [])
    deal = None
    try:
        deal = float(ctx.options.get("deal_size_usd_m")) or None
    except (TypeError, ValueError):
        pass
    rows = []
    for c in cands:
        cap = marg = None
        capfig = margfig = None
        head = None
        s = by_tk.get(c["ticker"] or "")
        figs = []
        if s:
            e, capfig = s.latest("Cash and equivalents")
            e2, margfig = s.latest("Operating margin")
            _, ebit = s.latest("Operating income")
            _, debt = (None, s.idx.get((f"{s.tk} derived: total_debt = debt_current + debt_noncurrent", _fp(e))))
            if debt and usable(ctx, debt):
                figs.append(debt)
        for m in c["metrics"]:
            add_figure(ctx, m, ingest=False)
            if usable(ctx, m) and re.search(r"cash|dry powder|aum|capacity", str(m.get("label", "")), re.I) \
                    and capfig is None:
                capfig = m
        if capfig:
            cap = _usd_m(capfig)
        if margfig:
            marg = margfig["value"]
        if s and capfig and debt and cap is not None and ebit and ebit["value"] > 0:
            head = 1.0 - max(_usd_m(debt) - cap, 0.0) / (6.0 * ebit["value"])
        score = _score(cap, marg, head, deal) if cap is not None else None
        why = []
        if capfig is None:
            why.append("no sourced capacity metric")
        elif deal and cap >= deal:
            why.append("cash covers the stated deal size")
        else:
            why.append("sourced cash capacity")
        if margfig and margfig["value"] >= 15:
            why.append("healthy operating margin")
        rows.append({"cand": c, "score": score, "cap": capfig, "marg": margfig, "why": "; ".join(why),
                     "figs": [f for f in (capfig, margfig) if f]})
    out = {}
    for typ, title in (("strategic", "Ranked strategic buyers show where cash and margins support a deal"),
                       ("financial", "Ranked financial buyers show where capacity supports a deal")):
        grp = [r for r in rows if r["cand"]["type"] == typ]
        grp.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0), r["cand"]["name"].casefold()))
        out[typ] = [r["cand"]["name"] for r in grp]
        for part, i in enumerate(range(0, len(grp), 8), 1):
            chunk = grp[i:i + 8]
            trs, figs = [], []
            for j, r in enumerate(chunk, i + 1):
                tr = {"rank": j if r["score"] is not None else None, "name": r["cand"]["name"], "type": typ,
                      "status": "ranked" if r["score"] is not None else "unscored", "rationale": r["why"],
                      "source": r["cand"]["source"]}
                tr["capacity"] = {"label": r["cap"]["label"], "value": fmt(r["cap"])} if r["cap"] else None
                tr["operating_margin"] = {"label": r["marg"]["label"], "value": fmt(r["marg"])} if r["marg"] else None
                trs.append(tr)
                figs += r["figs"]
            _slide(ctx, "buyer_list", f"buyer_list_{typ}_{part}", None, "table", title, figs,
                   blocks=[{"type": "table", "columns": ["Rank", "Buyer", "Capacity", "Operating margin", "Rationale"],
                            "rows": trs}])
    return {"ranking": out}


# ------------------------------------------------------------------------------------------------ qa
_WANT = (("revenue", r"revenue|sales|top.?line", "Revenue"), ("gross", r"gross (profit|margin)", "Gross profit"),
         ("gross_m", r"gross margin", "Gross margin"), ("ebit", r"operating (income|profit)|ebit", "Operating income"),
         ("op_m", r"operating margin|ebit margin", "Operating margin"),
         ("ni", r"net income|net profit|earnings|profit", "Net income"), ("net_m", r"net margin", "Net margin"),
         ("growth", r"growth|grew|growing", "Revenue growth"), ("cash", r"\bcash\b(?! flow)", "Cash and equivalents"),
         ("assets", r"total assets|assets", "Total assets"), ("cfo", r"cash flow|operating cash", "Cash from operations"),
         ("capex", r"capex|capital expenditure", "Capital expenditure (payments, as reported)"),
         ("eps", r"\beps\b|per share", "EarningsPerShareDiluted"))


def prepare_qa(request: dict) -> dict:
    q = str(request.get("question") or "").lower()
    want = [lab for _, rx, lab in _WANT if re.search(rx, q)]
    m = re.search(r"(?:last|past|prior)\s+(\d{1,2})\s+(?:fiscal )?years?|(\d{1,2})[- ]year", q)
    n = int(next(g for g in m.groups() if g)) if m else 3
    return {"want": want, "periods": max(1, min(n, 10)),
            "concepts": [EPS_CONCEPT] if "EarningsPerShareDiluted" in want else []}


@assembler("qa")
def asm_qa(ctx):
    want = ctx.plan.get("want") or ["Revenue", "Operating income", "Net income"]
    n = ctx.plan.get("periods", 3)
    eps = (ctx.outputs.get("qa_eps") or {}).get("figures") or []
    picked, base = [], list(ctx.figures)
    for s in statements(ctx):
        for w in want:
            if w == "EarningsPerShareDiluted":
                continue
            for e, f in s.series(w)[-n:]:
                picked.append(f)
    for f in eps:
        if usable(ctx, f):
            picked.append(f)
    dedup = {sha256_hex(canonical_bytes(f)): f for f in picked}
    picked = list(dedup.values())
    ctx.figures[:] = picked
    if not picked:
        ctx.notes.append("no sourced figure answers the question")
        return {}
    tk = (ctx.request.get("tickers") or ["The company"])[0].upper()
    latest = max(f["citation"]["as_of"] for f in picked)
    cur = [f for f in picked if f["citation"]["as_of"] == latest]
    if 3 <= len(cur) <= 5:
        kp = [{"label": f["label"], "value": fmt(f), "context": f"{fy(latest)}, sourced"} for f in cur]
        _slide(ctx, "qa", "qa_answer", "kpi_row", "table", f"{tk} figures answer the question with sourced values", cur,
               data={"archetype_blocks": {"kpis": kp, "highlight": 0, "subtitle": "Latest value per metric"}})
    labels = sorted({f["label"] for f in picked})
    rows = []
    for lab in labels:
        for f in sorted((x for x in picked if x["label"] == lab), key=lambda x: x["citation"]["as_of"]):
            rows.append({"label": lab, "value": fmt(f), "period": fy(f["citation"]["as_of"])})
    _slide(ctx, "qa", "qa_detail", None, "table", f"{tk} figures answer the question with sourced values", picked,
           blocks=[{"type": "table", "columns": ["Metric", "Value", "Period"], "rows": rows}]) if not (
        3 <= len(cur) <= 5) else None
    return {"answered": len(picked)}


# ------------------------------------------------------------------------------------------------ tick_and_tie
_NUM = re.compile(r"(?<![\w.,])(?P<neg>[-(])?\s?(?P<cur>US\$|USD|[$€£])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                  r"(?:\s?(?P<suf>%|percent|bn|billion|million|mm|mn|thousand|k|x)(?![A-Za-z]))?(?P<close>\))?(?![\w-])", re.I)
_SKIP_TEXT = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:FY|Q[1-4]|H[12]|CY)\s?'?\d{2,4}\b|\bpages?\s+\d+\b|\bnote\s+\d+\b", re.I)
_SUFSCALE = {"bn": 1e9, "billion": 1e9, "million": 1e6, "mm": 1e6, "mn": 1e6, "thousand": 1e3, "k": 1e3}
_DECL = ((re.compile(r"in\s+thousands|\$\s?000", re.I), 1e3, "thousands"),
         (re.compile(r"in\s+millions|usd\s+millions", re.I), 1e6, "millions"),
         (re.compile(r"in\s+billions", re.I), 1e9, "billions"))


def _declared(text):
    found = [(sc, w) for rx, sc, w in _DECL if rx.search(text)]
    return found[0] if len(found) == 1 else (1.0, "")


def scan_numbers(text: str, page_scale=(1.0, "")):
    """-> list of dicts {text, value, units, norm, kind, dp, index} for every checkable number in a line."""
    clean = _SKIP_TEXT.sub(lambda m: " " * len(m.group(0)), text)
    out = []
    for m in _NUM.finditer(clean):
        raw = m.group("num")
        v = float(raw.replace(",", ""))
        suf = (m.group("suf") or "").lower()
        cur = m.group("cur")
        has_unit = bool(suf or cur)
        if not has_unit and float(v).is_integer() and ("," not in raw) and (
                1900 <= v <= 2100 or 0 <= v <= 20):
            continue
        if bool(m.group("neg") == "(") != bool(m.group("close")) and m.group("neg") == "(":
            pass
        neg = m.group("neg") in ("-", "(")
        sv = -v if neg else v
        dp = len(raw.split(".")[1]) if "." in raw else 0
        if suf in ("%", "percent"):
            kind, units, norm = "pct", "%", sv
        elif suf == "x":
            kind, units, norm = "x", "x", sv
        else:
            kind = "abs"
            scale = _SUFSCALE.get(suf) or (page_scale[0] if not suf else 1.0)
            word = {1e3: "thousands", 1e6: "millions", 1e9: "billions"}.get(scale, "")
            cc = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "£": "GBP"}.get((cur or "").lower(), "")
            units = " ".join(x for x in (cc or ("USD" if word else ""), word) if x) or "number"
            norm = sv * scale
        out.append({"text": m.group(0).strip(), "value": sv, "units": units, "norm": norm, "kind": kind, "dp": dp,
                    "scale": (_SUFSCALE.get(suf) or (page_scale[0] if kind == "abs" and not suf else 1.0))})
    return out


def _fig_norm(f):
    u = (f.get("units") or "").lower()
    v = float(f["value"])
    if "%" in u or "percent" in u:
        return "pct", v
    if u.endswith("x"):
        return "x", v
    for word, sc in _SCALES:
        if word in u:
            return "abs", v * sc
    return "abs", v


def _core(label: str, tickers) -> list:
    lab = label.split("=")[0].split("(")[0].replace("derived:", " ").replace("_", " ").strip().casefold()
    toks = lab.split()
    if toks and toks[0].upper() in tickers:
        toks = toks[1:]
    return toks


def _ref(f):
    c = f["citation"]
    return " ".join(x for x in (f["label"], f["period"], c.get("xbrl_concept") or c.get("url") or
                                c.get("cell_locator") or c.get("doc_id")) if x)


def _sentences(page_text):
    out, pos = [], 0
    for line in page_text.split("\n"):
        for part in re.split(r"(?<=[.;])\s+(?=[A-Z])", line):
            if part.strip():
                out.append(part.strip())
    return out


@assembler("tick_and_tie")
def asm_tick_and_tie(ctx):
    tickers = {t.upper() for t in ctx.request.get("tickers") or []}
    sources = []
    for f in ctx.options.get("figures") or []:
        if isinstance(f, dict):
            add_figure(ctx, f, ingest=False)
            if usable(ctx, f):
                sources.append(f)
    mc = ctx.outputs.get("model_cells")
    for f in (mc or {}).get("figures", []) if mc else []:
        if usable(ctx, f):
            sources.append(f)
    for s in statements(ctx):
        for (lab, per), f in s.idx.items():
            if usable(ctx, f):
                sources.append(f)
    sources = list({sha256_hex(canonical_bytes(f)): f for f in sources}.values())
    if not sources:
        raise ValueError("tick_and_tie needs a model or figures: pass options.figures, options.model or tickers")
    as_of = ctx.request.get("as_of") or ctx.options.get("doc_as_of") or max(f["citation"]["as_of"] for f in sources)
    summary = {}
    for doc in ctx.request.get("doc_ids") or []:
        pages = ctx.resolver.pages(doc)
        if not pages:
            raise ValueError(f"no page text for document {doc!r}: provide options.pages or a resolver with pages")
        counts = {"ok": 0, "mismatch": 0, "unsourced": 0}
        for page, text in pages.items():
            pscale = _declared(text)
            rows, figs, k = [], [], 0
            for sent in _sentences(text):
                low = sent.casefold()
                cands = []
                for f in sources:
                    core = _core(f["label"], tickers)
                    if core and all(t in low for t in core):
                        cands.append((len(core), f))
                for num in scan_numbers(sent, pscale):
                    k += 1
                    kind_c = [(n, f) for n, f in cands if _fig_norm(f)[0] == num["kind"]]
                    best = max((n for n, _ in kind_c), default=0)
                    kind_c = [f for n, f in kind_c if n == best]
                    status, match = "unsourced", None
                    if kind_c:
                        status = "mismatch"
                        for f in kind_c:
                            _, fv = _fig_norm(f)
                            tol = max(0.5 * 10 ** (-num["dp"]) * num["scale"], 0.005 * abs(fv))
                            if abs(num["norm"] - fv) <= tol:
                                status, match = "ok", f
                                break
                        if match is None:
                            match = min(kind_c, key=lambda f: abs(_fig_norm(f)[1] - num["norm"]))
                    counts[status] += 1
                    cit = {"doc_id": doc, "page": page, "quote": sent,
                           "sha256_span_hash": sha256_hex(canonical_bytes([doc, page, sent, k])), "as_of": as_of}
                    dfig = {"label": f"{doc} p{page} n{k}", "value": abs(num["value"]) * (-1 if num["value"] < 0 else 1),
                            "units": num["units"], "period": as_of, "citation": cit, "v": 1}
                    add_figure(ctx, dfig, ingest=False)
                    dok = usable(ctx, dfig)
                    if not dok and status == "ok":
                        status = "unsourced"
                    row = {"index": k, "number": {"label": dfig["label"], "value": num["text"]} if dok else None,
                           "status": status, "source": _ref(match) if match else ""}
                    if match is not None and usable(ctx, match):
                        row["model"] = {"label": match["label"], "value": fmt(match)}
                        figs.append(match)
                    if dok:
                        figs.append(dfig)
                    row["page"] = page
                    rows.append(row)
            for part, i in enumerate(range(0, len(rows), 10), 1):
                chunk = rows[i:i + 10]
                bad = {r["status"] for r in chunk} - {"ok"}
                t = ("All numbers on this page were matched to the source" if not bad else
                     "Some numbers on this page do not tie to the source" if "mismatch" in bad else
                     "Some numbers on this page have no source to tie to")
                _slide(ctx, "tick_and_tie", f"tick_and_tie_{re.sub(r'[^a-z0-9]+', '_', doc.lower())}_p{page}_{part}",
                       None, "table", t, figs,
                       blocks=[{"type": "table", "columns": ["Number", "Source", "Status"], "rows": chunk}],
                       data={"tick_and_tie": {"id": doc, "page": page}})
        summary[doc] = counts
    ctx.outputs["tick_and_tie"] = summary
    return {"summary": summary}


# ------------------------------------------------------------------------------------------------ titles
_TITLE_SCHEMA = {"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}}


def _no_new_numbers(title: str) -> bool:
    return not re.search(r"\d", re.sub(r"(?<!\d)(19|20)\d{2}(?!\d)", "", title))


@text_step("action_titles")
def titles(ctx):
    """Template titles are already on every slide. With an adapter, ask it to reword; accept only a title that passes
    ``action_title_lint`` and contains no number except years. Facts sent are labels, never document text."""
    if ctx.adapter is None:
        return {"detail": "deterministic template titles", "reworded": 0}
    n = 0
    for s in ctx.slides:
        meta = ctx.slide_meta.get(s["id"]) or {}
        if ctx.cost > ctx.request.get("budget_usd", 2.0):
            break
        try:
            res = ctx.adapter.chat([{"role": "user", "content": (
                "Reword this slide action title as one sentence claim, no numbers except years, same meaning. "
                f"Title: {meta.get('template')}. Metrics: {', '.join(meta.get('facts', [])[:6])}")}],
                json_schema=_TITLE_SCHEMA, job_id=ctx.job_id)
            ctx.cost += float(getattr(res, "cost_usd", 0) or 0)
            ctx.tokens += int((getattr(res, "usage", None) or {}).get("total_tokens", 0) or 0)
            t = (res.data or {}).get("title", "") if isinstance(res.data, dict) else ""
            if isinstance(t, str) and _no_new_numbers(t):
                action_title_lint(t.strip(), "title")
                s["title"] = s["action_title"] = t.strip()
                n += 1
        except Exception:       # noqa: BLE001 - keep the template title
            continue
    return {"detail": f"{n} title(s) reworded by the adapter", "reworded": n}


def prepare_none(request: dict) -> dict:
    return {}


def prepare_tick(request: dict) -> dict:
    return {}
