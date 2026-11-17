"""Deterministic claim check: a slide's title must be backed by the slide's own evidence (R2-d).

Provenance proves every figure traces to sourced data; this proves the slide does not contradict itself.

  claim_basis      major  title figure carries a basis ("x forward revenue", "25% IRR") but the body shows that value, or
                          only multiples/percentages, on another basis ("x EBITDA")
  claim_unsupported major title figure (with a unit) appears nowhere in the body, chart or table of the same slide
  claim_direction  major  title verb says grow/rise/expand (or fall/decline) but the message series moves the other way
  mixed_units      major  one table column / list mixes $m with $bn, or % with x
  repeated_label   minor  the same lead-in label ("Output:") opens three or more items on one slide

English and Arabic (basis words, direction verbs, Arabic-Indic digits, x/percent signs). Zero LLM, zero network."""
from __future__ import annotations

import re

from om.deck import provenance as P

SKIP_ROLES = P.SKIP_ROLES | {"title", "footer", "page_number", "source", "footer_rule", "title_rule"}
_EXTRA = str.maketrans({"×": "x", "٪": "%", "٫": ".", "٬": ","})

# basis vocabulary per unit class: canonical basis -> patterns (English word boundary; Arabic substring)
_BASES = {
    "x": {
        "revenue": r"\b(?:revenues?|sales|arr|turnover|top[- ]line)\b|إيراد|ايراد|مبيعات",
        "ebitda": r"\bebitda\b|الأرباح قبل الفوائد",
        "ebit": r"\bebit\b",
        "earnings": r"\b(?:earnings|eps|p/e|pe|net income|profit)\b|صافي الدخل|صافي الربح",
        "fcf": r"\b(?:fcf|free cash flow)\b|التدفق النقدي الحر",
        "moic": r"\b(?:moic|money multiple)\b",
    },
    "pct": {
        "irr": r"\birr\b|معدل العائد الداخلي",
        "margin": r"\bmargins?\b|هامش",
        "growth": r"\b(?:growth|cagr|yoy)\b|نمو",
        "yield": r"\byields?\b|عائد(?! داخلي)",
    },
}
_UP = (r"\b(?:grow|grows|grew|growing|rise|rises|rose|rising|expand|expands|expanded|expanding|climb|climbs|climbed|"
       r"increase|increases|increased|surge|surges|surged)\b|ينمو|تنمو|نمت|نما|ارتفع|يرتفع|ترتفع|ارتفاع|يتوسع|توسع|زيادة")
_DOWN = (r"\b(?:fall|falls|fell|falling|decline|declines|declined|declining|drop|drops|dropped|shrink|shrinks|shrank|"
         r"contract|contracts|contracted|decrease|decreases|decreased|slip|slips|slipped|erode|erodes|eroded)\b|"
         r"ينخفض|تنخفض|انخفض|انخفاض|تراجع|يتراجع|تراجعت|هبوط|انكماش")
_LABEL = re.compile(r"^\s*([A-Za-z؀-ۿ][\w؀-ۿ /&-]{1,22}?)\s*:\s+\S")
_MONEY_M = {"m", "mm", "million"}
_MONEY_B = {"bn", "billion", "tn", "trillion"}
_DIR_CHARTS = {"line", "column", "area", "combo", "stacked_column"}


def _f(sev, rule, slide, shape, msg) -> dict:
    return {"severity": sev, "rule": rule, "slide": slide, "shape_id": None, "shape_name": shape, "message": msg}


def _clean(text: str) -> str:
    return P._norm(str(text)).translate(_EXTRA)


def _cls(m) -> str | None:
    unit, cur = m.group("unit"), m.group("cur")
    if unit == "%":
        return "pct"
    if unit == "x":
        return "x"
    if unit in ("bps", "pp", "pts"):
        return "bps"
    if cur or unit in P.UNITS:
        return "money"
    return None


def _bases(text: str, cls: str | None) -> set[str]:
    low = text.lower()
    return {b for b, pat in _BASES.get(cls or "", {}).items() if re.search(pat, low)}


def _scan(text: str, ctx: str = "", *, window: int = 34) -> list[dict]:
    """Figures in `text`: {cls, cands, unit, text, basis}. Basis comes from the words around the figure (up to the
    neighbouring figure) plus `ctx` (a table header or row label)."""
    text = _clean(text)
    text = P.CITE.sub(" ", text)
    text = P._DATES.sub(" ", text)
    ms = list(P._TOK.finditer(text))
    out = []
    for i, m in enumerate(ms):
        num, unit, cur = m.group("num").rstrip(","), m.group("unit"), m.group("cur")
        after = text[m.end():m.end() + 2]
        if not unit and (after[:1].isalpha() or re.match(r"-[A-Za-z]", after)):
            continue
        cls = _cls(m)
        if cls is None and not cur and "," not in num and "." not in num and 1900 <= int(float(num)) <= 2100:
            continue                                                  # a year
        raw = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        lo = ms[i - 1].end() if i else 0
        hi = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        around = text[max(lo, m.start() - window):m.start()] + " " + text[m.end():min(hi, m.end() + window)]
        out.append({"cls": cls, "cands": P._cands(raw, dec, unit, bool(cur)), "unit": unit, "text": m.group(0).strip(),
                    "basis": _bases(around + " " + ctx, cls), "val": raw})
    return out


def _el_figures(el) -> list[dict]:
    out: list[dict] = []
    if getattr(el, "text", None):
        for t in P.element_texts(el):
            out += _scan(t)
    tb = getattr(el, "table", None)
    if tb:
        cols = [P._cell(c) for c in tb.get("columns", [])]
        for row in tb.get("rows", []):
            label = P._cell(row[0]) if row else ""
            for j, c in enumerate(row):
                out += _scan(P._cell(c), ctx=(cols[j] if j < len(cols) else "") + " " + label)
    ch = getattr(el, "chart", None)
    if ch:
        for se in ch.get("series", []):
            nm = str(se.get("name", ""))
            for v in se.get("values", []):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append({"cls": None, "cands": [(abs(float(v)), 0.0)], "unit": None, "text": str(v),
                                "basis": set(), "val": float(v), "series": nm})
    return out


def _compat(tok_basis: set, title_basis: set) -> bool:
    return not tok_basis or not title_basis or bool(tok_basis & title_basis)


def _matches(t: dict, b: dict) -> bool:
    return P._match({"cands": t["cands"]}, b["cands"])


# ------------------------------------------------------------------- (a)
def _title_text(sl) -> str:
    return " ".join(" ".join(P.element_texts(el)) for el in sl.elements if el.role == "title")


def _check_title(sl) -> list[dict]:
    title = _title_text(sl)
    tfigs = [t for t in _scan(title) if t["cls"]]
    if not tfigs:
        return []
    for t in tfigs:                      # "6.8x to 9.1x forward revenue": the range shares one basis
        if not t["basis"]:
            shared = {frozenset(o["basis"]) for o in tfigs if o["cls"] == t["cls"] and o["basis"]}
            if len(shared) == 1:
                t["basis"] = set(next(iter(shared)))
    body: list[dict] = []
    for el in sl.elements:
        if el.role not in SKIP_ROLES:
            body += _el_figures(el)
    for d in (getattr(sl, "meta", None) or {}).get("derived") or []:
        v = d.get("value") if isinstance(d, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            body.append({"cls": None, "cands": [(abs(float(v)), 0.0)], "unit": None, "text": str(v), "basis": set(), "val": v})
    out, seen = [], set()
    for t in tfigs:
        key = (t["cls"], t["text"])
        if key in seen:
            continue
        seen.add(key)
        same_cls = [b for b in body if b["cls"] == t["cls"]]
        eligible = [b for b in body if b["cls"] in (t["cls"], None)]
        hit = [b for b in eligible if _matches(t, b)]
        tb = t["basis"]
        words = "/".join(sorted(tb))
        if tb and same_cls and not any(_compat(b["basis"], tb) for b in same_cls):
            have = "/".join(sorted({x for b in same_cls for x in b["basis"]}))
            out.append(_f("major", "claim_basis", sl.index, "title",
                          f"title says {t['text']} on a {words} basis but the body shows {t['cls']} figures only on "
                          f"{have or 'another'} basis"))
        elif not hit and not (t["cls"] == "pct" and t["val"] in (0.0, 100.0)):
            out.append(_f("major", "claim_unsupported", sl.index, "title",
                          f"title figure {t['text']} appears nowhere in the slide's body, chart or table"))
        elif tb and not any(_compat(b["basis"], tb) for b in hit):
            have = "/".join(sorted({x for b in hit for x in b["basis"]}))
            out.append(_f("major", "claim_basis", sl.index, "title",
                          f"title says {t['text']} on a {words} basis but the matching body figure is on {have} basis"))
    return out


# ------------------------------------------------------------------- (b)
def _sig(fig: dict) -> tuple[str | None, str | None]:
    u = fig["unit"]
    suffix = "m" if u in _MONEY_M else "bn" if u in _MONEY_B else None
    return fig["cls"], suffix


def _mixed(figs: list[dict]) -> str | None:
    cls = {f["cls"] for f in figs if f["cls"] in ("pct", "x", "money")}
    if {"pct", "x"} <= cls:
        return "% and x"
    suf = {_sig(f)[1] for f in figs if f["cls"] == "money"} - {None}
    if suf == {"m", "bn"}:
        return "$m and $bn"
    return None


def _check_mixed(sl) -> list[dict]:
    out = []
    for el in sl.elements:
        if el.role in SKIP_ROLES:
            continue
        tb = getattr(el, "table", None)
        if tb:
            rows = tb.get("rows", [])
            ncols = max((len(r) for r in rows), default=0)
            cols = {}
            for j in range(1, ncols):
                figs = []
                for r in rows:
                    fs = _scan(P._cell(r[j])) if j < len(r) else []
                    figs.append(fs[0] if len(fs) == 1 and len(re.sub(r"[^\w]", "", P._cell(r[j]))) <= 12 else None)
                cols[j] = figs
            # a metric-per-row matrix (scorecard: one unit per row, periods across) repeats the same unit pattern in
            # several columns and is legitimately mixed down each of them; a stray mixed column is unique
            pat = {j: tuple(f["cls"] if f else None for f in figs) for j, figs in cols.items()}
            for j, figs in cols.items():
                real = [f for f in figs if f]
                m = _mixed(real) if len(real) >= 2 and len(cols) >= 2 else None
                if m and sum(p == pat[j] for p in pat.values()) == 1:
                    hdr = P._cell(tb["columns"][j]) if j < len(tb.get("columns", [])) else str(j)
                    out.append(_f("major", "mixed_units", sl.index, el.id, f"column '{hdr}' mixes {m}"))
        elif getattr(el, "text", None) and len(el.text.paras) >= 3:
            figs = []
            for t in P.element_texts(el):
                fs = _scan(t)
                if fs and re.match(r"^\s*[+\-$€£]?\s?\d", _clean(t)):
                    figs.append(fs[0])
            m = _mixed(figs) if len(figs) >= 3 else None
            if m:
                out.append(_f("major", "mixed_units", sl.index, el.id, f"list mixes {m}"))
    kp = [f for el in sl.elements if el.role == "kpi" for f in _el_figures(el)[:1]]
    if len(kp) >= 2 and "$m and $bn" == _mixed(kp):
        out.append(_f("major", "mixed_units", sl.index, "kpi", "KPI values mix $m and $bn"))
    return out


# ------------------------------------------------------------------- (c)
def _check_labels(sl) -> list[dict]:
    seen: dict[str, int] = {}
    for el in sl.elements:
        if el.role in SKIP_ROLES:
            continue
        for t in P.element_texts(el):
            m = _LABEL.match(t)
            if m:
                k = m.group(1).strip().lower()
                seen[k] = seen.get(k, 0) + 1
    return [_f("minor", "repeated_label", sl.index, None, f"label '{k}:' opens {n} items; drop it or vary it")
            for k, n in seen.items() if n >= 3]


# ------------------------------------------------------------------- (d)
def _check_direction(sl) -> list[dict]:
    title = _clean(_title_text(sl)).lower()
    up, down = bool(re.search(_UP, title)), bool(re.search(_DOWN, title))
    if up == down:
        return []
    for el in sl.elements:
        ch = getattr(el, "chart", None)
        if not ch or ch.get("type") not in _DIR_CHARTS or not ch.get("series"):
            continue
        vals = [v for v in ch["series"][0].get("values", []) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(vals) < 2 or vals[0] == vals[-1]:
            return []
        first, last = vals[0], vals[-1]
        if (up and last < first) or (down and last > first):
            return [_f("major", "claim_direction", sl.index, "title",
                       f"title says {'rising' if up else 'falling'} but the series goes {first:g} to {last:g}")]
        return []
    return []


def check(spec, slides) -> list[dict]:
    """Findings (validator format) for every rendered slide whose title contradicts or outruns its own evidence."""
    out: list[dict] = []
    for sl in slides:
        out += _check_title(sl)
        out += _check_mixed(sl)
        out += _check_labels(sl)
        out += _check_direction(sl)
    return out
