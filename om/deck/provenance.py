"""Number provenance: every figure printed on a slide must trace to sourced spec data, a bound manifest value or a chart series.

A number is traceable when, after normalising formats ($1.1bn == 1,100 m == 1100; 38% == 0.38; rounding to the printed
precision), it equals a number that appears in the slide's own *data* blocks (numeric leaves, tables, KPI values, chart
series). Prose fields (takeaways, bullets, subtitles, titles, notes) are never a source: a model-written sentence cannot
vouch for its own figures. Data blocks only count when the slide carries a `source` or `as_of`; manifest values and the
`values` mapping always count. Untraceable numbers are critical findings, rule `unsourced_number`, naming the shape id.

Wave 3 (D-S3-11): a prose number also traces when it appears in a sourced data block of ANY slide of the deck (an
executive summary cites later slides), and when an archetype declares it as computed: `SolvedSlide.meta["derived"] =
[{"value": v, "from": [json paths]}]` (medians, totals, CAGR, implied values). Numbers with no data anywhere stay critical.
Citations (#19): `[n]` markers in rendered text must resolve to the slide's `sources` list (or its single `source` as
[1]); a dangling marker is a critical `citation` finding. Markers are never counted as numbers.

Zero LLM, zero network."""
from __future__ import annotations

import re

PROSE_KEYS = frozenset({
    "takeaways", "bullets", "text", "body", "subtitle", "measure", "title", "headline", "summary", "callout", "callouts",
    "notes", "caption", "description", "message", "points", "narrative", "commentary", "lead", "so_what", "bottom_line",
    "quote", "statement", "paragraph", "paragraphs", "rationale", "takeaway", "verdict", "note", "badge",
    "tagline", "label_note"})
SKIP_ROLES = frozenset({"footer", "page_number", "source", "footer_rule", "title_rule", "decor", "divider", "visual"})
UNITS = {"bn": 1e9, "billion": 1e9, "mm": 1e6, "m": 1e6, "million": 1e6, "tn": 1e12, "trillion": 1e12, "k": 1e3,
         "thousand": 1e3}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DATES = re.compile(rf"\d{{4}}-\d{{2}}(?:-\d{{2}})?|\d{{1,2}}\s{_MONTH}\.?,?\s\d{{4}}|{_MONTH}\.?\s\d{{1,2}},?\s\d{{4}}", re.I)
_STEP = re.compile(r"(?:step|phase|stage|option|tier|slide|scenario|case|wave|pillar|priority|page)\s*$", re.I)
_TOK = re.compile(
    r"(?<![\w.])(?P<cur>[$€£])?\s?(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s?(?P<unit>%|bps(?!\w)|pp(?!\w)|pts(?!\w)|x(?!\w)|(?:billion|million|trillion|thousand|bn|mm|tn|m|k)(?!\w)))?")
_ORDINAL = re.compile(r"^\d{1,2}[.)]?$")
EPS = 1e-9


def _norm(text: str) -> str:
    return text.translate(_DIGITS)


def _cands(raw: float, dec: int, unit: str | None, cur: bool) -> list[tuple[float, float]]:
    tol = 0.5 * 10 ** -dec
    if unit == "%":
        return [(raw, tol), (raw / 100, tol / 100)]
    if unit in UNITS:
        m = UNITS[unit]
        return [(raw, tol), (raw * m, tol * m), (raw * m / 1e6, tol * m / 1e6)]
    return [(raw, tol)]


CITE = re.compile(r"\[(\d{1,2})\]")


def tokens(text: str, *, strict_skip: bool = True) -> list[dict]:
    """Numeric tokens in `text`: {"text", "cands": [(value, tolerance)]}. Years, dates, ordinals, citation markers and
    code-like ids are skipped."""
    text = CITE.sub(" ", _norm(text))
    text = _DATES.sub(" ", text)
    out = []
    for m in _TOK.finditer(text):
        num, unit, cur = m.group("num"), m.group("unit"), m.group("cur")
        after = text[m.end():m.end() + 2]
        if not unit and (after[:1].isalpha() or re.match(r"-[A-Za-z]", after)):
            continue                                   # 3rd, 10-K, 3-statement
        if strict_skip:
            if not unit and not cur and "," not in num and "." not in num and 1900 <= int(num) <= 2100:
                continue                               # plain year
            if not unit and not cur and re.fullmatch(r"\d", num) and _STEP.search(text[:m.start()]):
                continue                               # "Step 3"
        raw = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        out.append({"text": m.group(0).strip(), "cands": _cands(raw, dec, unit, bool(cur))})
    return out


def _match(tok: dict, pool: list[tuple[float, float]]) -> bool:
    for tv, tt in tok["cands"]:
        for sv, st in pool:
            if abs(tv - sv) <= tt + st + EPS * max(1.0, abs(tv), abs(sv)):
                return True
    return False


# ---------------------------------------------------------------- source pool
def _walk(node, pool: list, prose: bool = False) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, (int, float)):
        pool.append((abs(float(node)), 0.0))
    elif isinstance(node, str):
        if not prose:
            for t in tokens(node, strict_skip=False):
                pool.extend(t["cands"])
    elif isinstance(node, dict):
        for k, v in node.items():
            _walk(v, pool, prose or (isinstance(k, str) and k.lower() in PROSE_KEYS))
    elif isinstance(node, (list, tuple)):
        for v in node:
            _walk(v, pool, prose)


def slide_pool(slide: dict, extra: list) -> list[tuple[float, float]]:
    pool = list(extra)
    if slide.get("source") or slide.get("sources") or slide.get("as_of"):
        _walk(slide.get("blocks") or {}, pool)
    return pool


def _bound_pool(manifest, values) -> list[tuple[float, float]]:
    pool: list = []
    m = manifest.to_dict() if hasattr(manifest, "to_dict") else manifest
    for src in (m, values):
        if src is not None:
            _walk(src, pool)
    return pool


# ---------------------------------------------------------------- rendered text
def _cell(c) -> str:
    if isinstance(c, dict):
        return str(c.get("t", c.get("text", "")))
    return "" if c is None else str(c)


def element_texts(el) -> list[str]:
    """Text strings of an element that a reader sees, one per paragraph / table cell."""
    out: list[str] = []
    if getattr(el, "text", None):
        for p in el.text.paras:
            runs = list(p.runs)
            if runs and _ORDINAL.match(runs[0].t.strip()):
                runs = runs[1:]                        # leading list ordinal "1  "
            out.append("".join(r.t for r in runs))
    tb = getattr(el, "table", None)
    if tb:
        out += [_cell(c) for c in tb.get("columns", [])]
        for row in tb.get("rows", []):
            out += [_cell(c) for c in row]
    return out


def _derived_pool(sl) -> list[tuple[float, float]]:
    """Archetype-declared computed values of one solved slide, as (value, tolerance) pairs."""
    pool: list = []
    for d in (getattr(sl, "meta", None) or {}).get("derived") or []:
        v = d.get("value") if isinstance(d, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            pool.append((abs(float(v)), 0.0))
    return pool


def source_list(slide: dict) -> list[str]:
    """The slide's citation list: `sources` (list of strings) when present, else its single `source` as [1]."""
    src = slide.get("sources")
    if isinstance(src, (list, tuple)) and src:
        return [str(x) for x in src]
    return [str(slide["source"])] if slide.get("source") else []


def check(spec: dict, slides, *, manifest=None, values=None) -> list[dict]:
    """Findings (validator format) for every rendered number that cannot be traced to sourced data, and every `[n]`
    citation marker without a matching source."""
    bound = _bound_pool(manifest, values)
    spec_slides = list((spec or {}).get("slides") or [])
    slides = list(slides)
    deck_pool = list(bound)                            # sourced data blocks of every slide + declared derived values
    for s in slides:
        i = getattr(s, "index", 0) - 1
        sp = spec_slides[i] if 0 <= i < len(spec_slides) else {}
        if sp.get("source") or sp.get("sources") or sp.get("as_of"):
            _walk(sp.get("blocks") or {}, deck_pool)
        deck_pool += _derived_pool(s)                  # declared by archetype code, not by model-written prose
    out: list[dict] = []
    for s in slides:
        i = getattr(s, "index", 0) - 1
        sp = spec_slides[i] if 0 <= i < len(spec_slides) else {}
        n_src = len(source_list(sp))
        for el in s.elements:
            if el.role in SKIP_ROLES:
                continue
            bad, marks = [], []
            for text in element_texts(el):
                bad += [t["text"] for t in tokens(text) if not _match(t, deck_pool)]
                marks += [int(n) for n in CITE.findall(text) if not 1 <= int(n) <= n_src]
            if bad:
                out.append({"severity": "critical", "rule": "unsourced_number", "slide": s.index, "shape_id": None,
                            "shape_name": el.id,
                            "message": f"{el.id}: number(s) {', '.join(dict.fromkeys(bad))} not traceable to sourced "
                                       f"spec data, a bound manifest value or a chart series"})
            if marks:
                out.append({"severity": "critical", "rule": "citation", "slide": s.index, "shape_id": None,
                            "shape_name": el.id,
                            "message": f"{el.id}: citation marker(s) {', '.join(f'[{n}]' for n in dict.fromkeys(marks))} "
                                       f"have no matching entry in the slide's sources ({n_src} listed)"})
    return out
