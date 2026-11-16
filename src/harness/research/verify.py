"""S6.2 figure verifier: no figure leaves the research agent unless it is independently re-checked against its source.

Pure function library (no agent loop, no network). Everything the verifier needs from the outside world comes
through an injectable :class:`SourceResolver` that only reads evidence payloads / local caches.

A figure passes only when exactly one of these holds (strictest banking standard, nothing is ever "fixed"):

* ``xbrl``      the resolver's XBRL value equals ``value`` after the declared scale, within ``rel_tol``;
* ``page_text`` / ``quote``  the cited quote occurs (whitespace-normalised) on the cited page (or url snapshot)
  AND contains a number equal to the figure after scale, with a compatible unit kind (%, bps, x, currency);
* ``cell``      the cited cell equals the figure;
* ``derived``   the label declares ``... = {Input A} / {Input B}`` over other cited figures, each of which itself
  verifies, and recomputation matches.

Common gates run first: as-of present, a real date, not in the future; period year consistent with the as-of year;
units and scale unambiguous. Every failure carries a precise reason.

Conventions
-----------
* ``fig.value`` is in the declared units. ``USD m`` -> x1e6, ``bn`` -> x1e9, ``%`` -> value/100, ``bps`` -> value/1e4,
  ``x`` -> value. The normalised number is what gets compared.
* XBRL lookup: ``resolver.xbrl_value(citation.doc_id, citation.xbrl_concept, period_end, fig.units)`` where
  ``period_end`` is the figure period when it is an ISO date, otherwise the raw period string (``"FY2024"``) for the
  resolver to interpret. Resolver values are in base units (full dollars).
* ``extract_numbers`` returns ``(value, hint)``: magnitude words (k/m/bn/tn, thousand/million/billion) are applied;
  ``%`` and ``bps`` are NOT (``"45%"`` -> ``(45.0, "%")``); the hint is ``"USD"``/``"EUR"``/``"GBP"``/``"JPY"``/
  ``"CHF"``/``"%"``/``"bps"``/``"x"``/``""``. Parenthesised numbers are negative.
* Slides: a number must match a verified figure by value AND the figure's label must occur in the number's context
  (its own string, enclosing ``label``/``name``/``metric``/... keys, sibling label cells, the slide title). Exempt:
  ISO dates, years 1900-2100, and plain integers 0-20 with no unit (enumerations such as "3 drivers").
"""
from __future__ import annotations

import ast
import dataclasses
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.harness.research.api import ResearchResult, SourcedFigure

METHODS = ("xbrl", "quote", "page_text", "cell", "derived", "none")
DEFAULT_REL_TOL = 0.005


@dataclass
class Verdict:
    ok: bool
    reason: str
    method: str


# --------------------------------------------------------------------------------------------- resolver
class SourceResolver:
    """Injectable source access. The default reads only registered/in-memory data and evidence payloads; it never
    touches the network. Subclass (or use the ``add_*`` registrars) to supply data."""

    def __init__(self, *, xbrl=None, pages=None, urls=None, cells=None):
        self._xbrl = dict(xbrl or {})     # (ticker_or_cik, concept, period_end) -> float
        self._pages = dict(pages or {})   # (doc_id, page) -> str
        self._urls = dict(urls or {})     # url -> str
        self._cells = dict(cells or {})   # (path_or_doc, locator) -> float

    def add_xbrl(self, ticker_or_cik, concept, period_end, value):
        self._xbrl[(str(ticker_or_cik), concept, str(period_end))] = float(value)
        return self

    def add_page(self, doc_id, page, text):
        self._pages[(doc_id, int(page))] = text
        return self

    def add_url(self, url, text):
        self._urls[url] = text
        return self

    def add_cell(self, path_or_doc, locator, value):
        self._cells[(path_or_doc, locator)] = float(value)
        return self

    def ingest_evidence(self, bundle, records=None):
        """Index tool outputs stored in an ``EvidenceBundle`` payload store. Recognised output shapes (dicts):
        ``{"doc_id","page","text"}``, ``{"url","text"}``, ``{"ticker"|"cik","concept","period_end","value"}``,
        ``{"doc"|"path","locator","value"}``. Unknown shapes are ignored. Returns the number of entries indexed."""
        import json
        n = 0
        for rec in (records if records is not None else bundle.export()):
            try:
                out = json.loads(bundle.load_payload(rec["output_sha256"]))
            except Exception:
                continue
            for o in (out if isinstance(out, list) else [out]):
                if not isinstance(o, dict):
                    continue
                if "doc_id" in o and "page" in o and isinstance(o.get("text"), str):
                    self.add_page(o["doc_id"], o["page"], o["text"]); n += 1
                elif "url" in o and isinstance(o.get("text"), str):
                    self.add_url(o["url"], o["text"]); n += 1
                elif "concept" in o and "period_end" in o and isinstance(o.get("value"), (int, float)):
                    self.add_xbrl(o.get("ticker") or o.get("cik"), o["concept"], o["period_end"], o["value"]); n += 1
                elif "locator" in o and isinstance(o.get("value"), (int, float)):
                    self.add_cell(o.get("doc") or o.get("path"), o["locator"], o["value"]); n += 1
        return n

    def xbrl_value(self, ticker_or_cik, concept, period_end, unit=None) -> float | None:
        return self._xbrl.get((str(ticker_or_cik), concept, str(period_end)))

    def page_text(self, doc_id, page) -> str | None:
        return self._pages.get((doc_id, page))

    def url_text(self, url) -> str | None:
        return self._urls.get(url)

    def cell_value(self, path_or_doc, cell_locator) -> float | None:
        return self._cells.get((path_or_doc, cell_locator))


# --------------------------------------------------------------------------------------------- numbers
_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGITS.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})
_TRANS = dict(_DIGITS)
_TRANS.update({0x066B: ".", 0x066C: ","})
_TRANS.update({c: "-" for c in (0x2212, 0x2012, 0x2013, 0x2014, 0xFE63, 0xFF0D, 0x2010, 0x2011)})
_THIN = "    "
_SCALE_WORD = {"k": 1e3, "thousand": 1e3, "thousands": 1e3, "000": 1e3, "000s": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6,
               "mln": 1e6, "million": 1e6, "millions": 1e6, "b": 1e9, "bn": 1e9, "bln": 1e9, "billion": 1e9,
               "billions": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12, "trillions": 1e12}
_CUR = {"$": "USD", "us$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "¥": "JPY",
        "jpy": "JPY", "chf": "CHF"}

_NUM_RE = re.compile(r"""
    (?P<open>\()?\s*
    (?P<sign>[-+])?\s*
    (?P<cur>US\$|[$€£¥]|\b(?:USD|EUR|GBP|JPY|CHF)\b)?\s*
    (?P<sign2>-)?\s*
    (?P<num>\d{1,3}(?:\.\d{3})+,\d{1,2}(?!\d)|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    (?:\s*(?P<close1>\)))?
    (?:(?P<suf1>%|bps|bp|bn|mn|mm|mln|bln|tn|[kmbtx×])(?![A-Za-z])
      |\s+(?P<suf2>percent|per\s?cent|basis\s+points?|bps|billion|million|thousand|trillion|bn|mn|mm|%)(?![A-Za-z]))?
    (?:\s*(?P<close2>\)))?
    """, re.X | re.I)


def _normalise_text(text: str) -> str:
    text = re.sub(r"(?<=\d)[" + _THIN + r"](?=\d{3}(?!\d))", ",", text)
    text = text.translate(_TRANS)
    return unicodedata.normalize("NFKC", text)


def _extract_full(text):
    """-> list[(value, hint, magnitude_applied)]; the shared core of :func:`extract_numbers`."""
    if not isinstance(text, str):
        return []
    t = _normalise_text(text)
    out = []
    for m in _NUM_RE.finditer(t):
        first = m.start()
        while first < len(t) and t[first].isspace():
            first += 1
        prev = t[first - 1] if first > 0 else " "
        has_lead = any(m.group(g) for g in ("open", "sign", "cur", "sign2"))
        if not has_lead and (prev.isalnum() or prev in "_."):
            continue                      # glued to a word / decimal tail: "Q3", "FY24", "v1.2"
        suf = re.sub(r"\s+", "", (m.group("suf1") or m.group("suf2") or "").lower())
        nxt = t[m.end("num")] if m.end("num") < len(t) else " "
        if not suf and nxt.isalpha():
            continue                      # "5th", "3Q"
        num = m.group("num")
        s = num.replace(".", "").replace(",", ".") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", num) \
            else num.replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        neg = bool(m.group("sign2")) or (m.group("sign") == "-" and not (prev.isalnum() or prev == ")"))
        if m.group("open") and (m.group("close1") or m.group("close2")) and not m.group("sign"):
            neg = True
        if neg:
            v = -v
        hint, mag = _CUR.get((m.group("cur") or "").lower(), ""), False
        if suf in ("%", "percent"):
            hint = "%"
        elif suf in ("bps", "bp") or suf.startswith("basispoint"):
            hint = "bps"
        elif suf in ("x", "\u00d7"):
            hint = "x"
        elif suf in _SCALE_WORD:
            v, mag = v * _SCALE_WORD[suf], True
        out.append((v, hint, mag))
    return out


def extract_numbers(text) -> list[tuple[float, str]]:
    """All numbers in ``text`` as ``(value_in_base_units, unit_hint)``. See module docstring for conventions."""
    return [(v, h) for v, h, _ in _extract_full(text)]


# --------------------------------------------------------------------------------------------- units / scale
def _parse_units(units: str):
    """-> (kind, scale, error). kind in abs|pct|bps|x."""
    low = (units or "").lower()
    kind = "abs"
    if "%" in low or re.search(r"percent|pct", low):
        kind = "pct"
    elif re.search(r"\bbps\b|\bbp\b|basis", low):
        kind = "bps"
    elif re.search(r"(?<![a-z])x(?![a-z])|\btimes\b|\bmultiple\b", low):
        kind = "x"
    toks = re.findall(r"[a-z]+|\d+s?", low)
    scales = {_SCALE_WORD[t] for t in toks if t in _SCALE_WORD and kind == "abs"}
    if kind != "abs" and any(t in _SCALE_WORD for t in toks if t not in ("x", "b", "t", "m", "k", "bp", "bps")):
        return kind, 1.0, f"unit/scale ambiguity: units {units!r} mix a ratio unit with a magnitude word"
    if len(scales) > 1:
        return kind, 1.0, f"unit/scale ambiguity: units {units!r} declare more than one magnitude"
    return kind, (next(iter(scales)) if scales else 1.0), None


_DECL = ((re.compile(r"in\s+thousands|thousands\s+of|\$\s?000'?s|\(\s?000'?s?\s?\)|in\s+000'?s|usd\s+thousands|'000"), 1e3),
         (re.compile(r"in\s+millions|millions\s+of|usd\s+millions|\$\s?in\s+millions"), 1e6),
         (re.compile(r"in\s+billions|billions\s+of|usd\s+billions"), 1e9))


def _declared_scales(text: str) -> set:
    low = _normalise_text(text).lower()
    return {sc for rx, sc in _DECL if rx.search(low)}


def _norm_value(value: float, kind: str, scale: float) -> float:
    if kind == "pct":
        return value / 100.0
    if kind == "bps":
        return value / 10000.0
    if kind == "x":
        return value
    return value * scale


def _close(a: float, b: float, tol: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= tol * max(abs(a), abs(b))


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", _normalise_text(text)).strip()


# --------------------------------------------------------------------------------------------- common gates
def _as_fig(f) -> SourcedFigure:
    return f if isinstance(f, SourcedFigure) else SourcedFigure.from_dict(f)


def _today() -> date:
    return date.today()


_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _period_year(period: str):
    ys = {int(y) for y in _YEAR_RE.findall(period or "")}
    if not ys:
        m = re.search(r"FY\s?'?(\d{2})(?!\d)", period or "", re.I)
        if m:
            ys = {2000 + int(m.group(1))}
    if len(ys) != 1:
        return None, ("period spans several years" if ys else "period has no parseable year")
    return next(iter(ys)), None


def _common(fig: SourcedFigure):
    c = fig.citation
    if not c.as_of:
        return "missing as_of"
    try:
        asof = datetime.strptime(c.as_of, "%Y-%m-%d").date()
    except ValueError:
        return f"as_of {c.as_of!r} is not a real date"
    if asof > _today():
        return f"as_of {c.as_of} is in the future"
    if isinstance(fig.value, bool) or not isinstance(fig.value, (int, float)) or not math.isfinite(fig.value):
        return "value is not a finite number"
    py, err = _period_year(fig.period)
    if err:
        return f"period {fig.period!r}: {err}"
    if asof.year not in (py, py + 1):
        return (f"period mismatch: period {fig.period!r} (year {py}) vs citation as_of {c.as_of}; "
                f"as_of year must be {py} or {py + 1}")
    kind, scale, uerr = _parse_units(fig.units)
    if uerr:
        return uerr
    return None


# --------------------------------------------------------------------------------------------- methods
def _v_xbrl(fig, resolver, tol, kind, scale):
    c = fig.citation
    pe = fig.period if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fig.period or "") else fig.period
    got = resolver.xbrl_value(c.doc_id, c.xbrl_concept, pe, fig.units)
    if got is None:
        return Verdict(False, f"source unavailable: no XBRL value for {c.xbrl_concept} {pe} ({c.doc_id})", "xbrl")
    exp = _norm_value(fig.value, kind, scale)
    if _close(float(got), exp, tol):
        return Verdict(True, f"XBRL {c.xbrl_concept} = {got:g} matches {exp:g}", "xbrl")
    why = ""
    for s in (1e3, 1e6, 1e9):
        if kind == "abs" and _close(float(got), fig.value * s, tol):
            why = f"; scale ambiguity: XBRL equals value x{s:g}, units say x{scale:g}"
    return Verdict(False, f"XBRL value {got:g} != figure {exp:g} (value {fig.value:g}, units {fig.units!r}){why}", "xbrl")


def _quote_numbers(quote: str, context: str):
    """Numbers of the quote as (comparable value, hint, stated value) and whether the scale is ambiguous. A unitless
    number is multiplied by the quote's (else the page's) declared table scale; explicit magnitude words win."""
    cscales = _declared_scales(quote) or _declared_scales(context)
    ambiguous = len(cscales) > 1
    scale = next(iter(cscales)) if len(cscales) == 1 else 1.0
    res = []
    for v, hint, mag in _extract_full(quote):
        plain = hint in ("", "USD", "EUR", "GBP", "JPY", "CHF") and not mag
        res.append((v * scale if plain else v, hint, v))
    return res, ambiguous


def _hint_ok(kind: str, hint: str) -> bool:
    if kind == "pct":
        return hint == "%"
    if kind == "bps":
        return hint == "bps"
    if kind == "x":
        return hint == "x"
    return hint not in ("%", "bps", "x")


def _hint_norm(v: float, hint: str) -> float:
    return v / 100.0 if hint == "%" else v / 10000.0 if hint == "bps" else v


def _v_text(fig, text, method, where, tol, kind, scale):
    c = fig.citation
    quote = _ws(c.quote or "")
    if not quote:
        return Verdict(False, f"no quote cited for {where}", method)
    if quote not in _ws(text):
        return Verdict(False, f"quote not found in {where} (whitespace-normalised)", method)
    nums, ambiguous = _quote_numbers(c.quote, text)
    exp = _norm_value(fig.value, kind, scale)
    kind_miss = False
    for v, hint, raw in nums:
        if _close(_hint_norm(v, hint), exp, tol):
            if _hint_ok(kind, hint):
                if ambiguous and hint in ("", "USD", "EUR", "GBP", "JPY", "CHF"):
                    continue
                return Verdict(True, f"quote found in {where} and contains {raw:g} matching {exp:g}", method)
            kind_miss = True
    if ambiguous:
        return Verdict(False, f"unit/scale ambiguity: {where} declares several magnitudes (thousands/millions/"
                              "billions) and the quote does not say which applies", method)
    if kind_miss:
        return Verdict(False, f"unit mismatch: quote number equals {exp:g} but its unit kind is not "
                              f"{kind!r} (percentage vs basis points vs multiple vs amount)", method)
    for v, hint, raw in nums:
        if kind == "abs" and any(_close(raw, fig.value * s, tol) or _close(v, fig.value * s, tol)
                                 for s in (1e3, 1e6, 1e9)) or _close(raw, fig.value, tol):
            qs = _declared_scales(c.quote) or _declared_scales(text)
            return Verdict(False, f"unit/scale ambiguity: quote number {raw:g} matches only under a different scale "
                                  f"than units {fig.units!r} (source declares {sorted(qs) or 'none'})", method)
    return Verdict(False, f"no number in the quote equals the figure ({exp:g}) after scale", method)


def _v_cell(fig, resolver, tol, kind, scale):
    c = fig.citation
    loc = c.cell_locator or (f"{c.sheet}!{c.cell}" if c.sheet and c.cell else None)
    got = resolver.cell_value(c.doc_id, loc)
    if got is None:
        return Verdict(False, f"source unavailable: no cell value for {c.doc_id} {loc}", "cell")
    for cand in (fig.value, _norm_value(fig.value, kind, scale)):
        if _close(float(got), cand, tol):
            return Verdict(True, f"cell {loc} = {got:g}", "cell")
    return Verdict(False, f"cell {loc} = {got:g} != figure {fig.value:g}", "cell")


_REF = re.compile(r"\{([^{}|]+)(?:\|([^{}]+))?\}")


def _eval_expr(expr: str, env: dict):
    tree = ast.parse(expr, mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name) and n.id in env:
            return env[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if b == 0:
                raise ZeroDivisionError("division by zero")
            return a / b
        raise ValueError(f"unsupported expression element {type(n).__name__}")
    return ev(tree)


def _derived_parts(label: str):
    if "=" not in label:
        return None
    expr = label.split("=", 1)[1]
    return expr if _REF.search(expr) else None


def _v_derived(fig, expr, resolver, tol, kind, scale, pool, stack):
    if not pool:
        return Verdict(False, "derived figure but no input figures supplied", "derived")
    env, names = {}, {}
    pool = [_as_fig(p) for p in pool]

    def sub(m):
        name = f"v{len(names)}"
        names[name] = (m.group(1).strip(), (m.group(2) or "").strip())
        return name
    py_expr = _REF.sub(sub, expr)
    for name, (lab, per) in names.items():
        cands = [p for p in pool if p.label.strip().casefold() == lab.casefold() and p is not fig
                 and id(p) not in stack]
        if per:
            cands = [p for p in cands if p.period.strip().casefold() == per.casefold()]
        elif len(cands) > 1:
            same = [p for p in cands if p.period == fig.period]
            cands = same or cands
        if not cands:
            return Verdict(False, f"derived input {lab!r} not found among cited figures", "derived")
        if len({(p.value, p.units, p.period) for p in cands}) > 1:
            return Verdict(False, f"derived input {lab!r} is ambiguous ({len(cands)} figures)", "derived")
        inp = cands[0]
        vd = verify_figure(inp, resolver, rel_tol=tol, figures=pool, _stack=stack + (id(fig),))
        if not vd.ok:
            return Verdict(False, f"derived input {lab!r} unverified: {vd.reason}", "derived")
        ik, isc, _ = _parse_units(inp.units)
        env[name] = _norm_value(inp.value, ik, isc)
    try:
        got = _eval_expr(py_expr, env)
    except (ZeroDivisionError, ValueError, SyntaxError) as e:
        return Verdict(False, f"derived formula could not be evaluated: {e}", "derived")
    exp = _norm_value(fig.value, kind, scale)
    cands = [got] + ([got / 100.0] if kind == "pct" else [got / 10000.0] if kind == "bps" else [])
    if any(_close(g, exp, tol) for g in cands):
        return Verdict(True, f"recomputed {got:g} from {len(names)} verified inputs matches {exp:g}", "derived")
    return Verdict(False, f"recomputed {got:g} from inputs != figure {exp:g}", "derived")


# --------------------------------------------------------------------------------------------- public: figure
def verify_figure(fig, resolver, *, rel_tol=DEFAULT_REL_TOL, figures=None, _stack=()) -> Verdict:
    """Independently re-check one figure. ``figures`` is the pool of sibling figures for ``derived`` inputs."""
    try:
        fig = _as_fig(fig)
    except Exception as e:
        return Verdict(False, f"figure is not a valid SourcedFigure: {e}", "none")
    err = _common(fig)
    if err:
        return Verdict(False, err, "none")
    kind, scale, _ = _parse_units(fig.units)
    c = fig.citation
    expr = _derived_parts(fig.label)
    if expr is not None:
        return _v_derived(fig, expr, resolver, rel_tol, kind, scale, figures, _stack)
    if c.xbrl_concept:
        return _v_xbrl(fig, resolver, rel_tol, kind, scale)
    if c.cell_locator or (c.sheet and c.cell):
        return _v_cell(fig, resolver, rel_tol, kind, scale)
    if c.quote and c.page is not None:
        text = resolver.page_text(c.doc_id, c.page)
        if text is not None:
            return _v_text(fig, text, "page_text", f"{c.doc_id} page {c.page}", rel_tol, kind, scale)
        if not (c.url or c.source_url):
            return Verdict(False, f"source unavailable: no text for {c.doc_id} page {c.page}", "page_text")
    url = c.url or c.source_url
    if c.quote and url:
        text = resolver.url_text(url)
        if text is None:
            return Verdict(False, f"source unavailable: no stored snapshot for {url}", "quote")
        return _v_text(fig, text, "quote", f"snapshot of {url}", rel_tol, kind, scale)
    return Verdict(False, "no verifiable method: cite an XBRL concept, a cell, a quote on a page/url, or a derivation",
                   "none")


# --------------------------------------------------------------------------------------------- public: result
_LABEL_KEYS = ("label", "name", "metric", "title", "series", "kpi", "header", "caption", "heading", "key")
_SKIP_KEYS = frozenset({"type", "id", "layout", "archetype", "as_of", "citations", "sources", "citation", "source",
                        "page", "index", "order", "rank", "level", "row", "col", "x", "y", "w", "h"})
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _is_exempt(v: float, hint: str, text_has_unit: bool) -> bool:
    if hint:
        return False
    if float(v).is_integer() and 1900 <= abs(v) <= 2100 and not text_has_unit:
        return True
    return float(v).is_integer() and 0 <= v <= 20 and not text_has_unit


def _norm_candidates(v: float, hint: str, from_string: bool):
    """Comparable normalised values for a slide number."""
    if hint == "%":
        return [v / 100.0], "pct"
    if hint == "bps":
        return [v / 10000.0], "bps"
    if hint == "x":
        return [v], "x"
    return [v], "abs"


def _slide_numbers(node, ctx, out, path, slide_ctx):
    if isinstance(node, str):
        s = _ISO_DATE.sub(" ", node)
        for v, hint in extract_numbers(s):
            if _is_exempt(v, hint, False):
                continue
            out.append((path, v, hint, True, " ".join([s] + ctx + slide_ctx), s))
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        if math.isfinite(node) and not _is_exempt(float(node), "", False):
            out.append((path, float(node), "", False, " ".join(ctx + slide_ctx), str(node)))
    elif isinstance(node, dict):
        local = list(ctx)
        for k in _LABEL_KEYS:
            if isinstance(node.get(k), str):
                local.append(node[k])
        for k, e in node.items():
            if k in _SKIP_KEYS:
                continue
            _slide_numbers(e, local, out, f"{path}.{k}", slide_ctx)
    elif isinstance(node, (list, tuple)):
        local = list(ctx) + [e for e in node if isinstance(e, str) and not extract_numbers(e)]
        for i, e in enumerate(node):
            _slide_numbers(e, local, out, f"{path}[{i}]", slide_ctx)


def _matches_figure(v, hint, from_string, ctx_text, figs, tol):
    ctx = _ws(ctx_text).casefold()
    for f in figs:
        if f.label.strip().casefold() not in ctx:
            continue
        kind, scale, _ = _parse_units(f.units)
        exp = _norm_value(f.value, kind, scale)
        if hint:
            nv, k2 = _norm_candidates(v, hint, from_string)
            if k2 == kind and _close(nv[0], exp, tol):
                return True
            if k2 == "abs" and kind == "abs" and _close(v, exp, tol):
                return True
            continue
        # unitless: raw stated value, or fully scaled value
        if kind == "abs" and (_close(v, exp, tol) or _close(v, f.value, tol)):
            return True
        if kind in ("pct", "bps", "x") and (_close(v, f.value, tol) or _close(v, exp, tol)):
            return True
    return False


def _check_slide(slide: dict, figs, tol):
    ctx = [str(slide.get(k)) for k in ("title", "action_title") if isinstance(slide.get(k), str)]
    out: list = []
    for k in ("title", "action_title", "notes", "bullets", "blocks", "data"):
        if k in slide:
            _slide_numbers(slide[k], [], out, k, ctx)
    bad = []
    for path, v, hint, from_s, ctx_text, shown in out:
        if not _matches_figure(v, hint, from_s, ctx_text, figs, tol):
            bad.append(f"{path}: number {v:g}{hint and ' ' + hint} in {shown[:60]!r} matches no verified figure "
                       "(value + label)")
    return bad


def _to_dict(x):
    return x.to_dict() if hasattr(x, "to_dict") else x


def verify_result(result, resolver, *, rel_tol=DEFAULT_REL_TOL) -> ResearchResult:
    """Return a new result: unverifiable figures move to ``rejected`` (nothing is dropped silently); slides and Excel
    payloads containing numbers that are not verified figures are rejected whole."""
    pool = [_as_fig(f) for f in result.figures]
    ok_figs, rejected = [], list(result.rejected)
    for f in pool:
        v = verify_figure(f, resolver, rel_tol=rel_tol, figures=pool)
        if v.ok:
            ok_figs.append(f)
        else:
            rejected.append({"figure": f.to_dict(), "reason": f"[{v.method}] {v.reason}"})
    slides = []
    for s in result.slide_specs:
        sd = _to_dict(s)
        bad = _check_slide(sd, ok_figs, rel_tol)
        if bad:
            rejected.append({"figure": {"kind": "slide_spec", "id": sd.get("id", ""), "spec": sd},
                             "reason": "slide contains unverified numbers: " + "; ".join(bad[:5])})
        else:
            slides.append(s)
    excel = []
    for p in result.excel_inputs:
        pd_ = _to_dict(p)
        bad = []
        for key, fd in (pd_.get("inputs") or {}).items():
            v = verify_figure(fd, resolver, rel_tol=rel_tol, figures=pool)
            if not v.ok:
                bad.append(f"input {key!r}: [{v.method}] {v.reason}")
        if bad:
            rejected.append({"figure": {"kind": "excel_input", "id": f"{pd_.get('model_type')}:{pd_.get('ticker')}",
                                        "payload": pd_},
                             "reason": "payload contains unverified figures: " + "; ".join(bad[:5])})
        else:
            excel.append(p)
    new = dataclasses.replace(result, figures=ok_figs, rejected=rejected, slide_specs=slides, excel_inputs=excel)
    return new.validate()
