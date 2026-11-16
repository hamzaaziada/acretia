"""Workbook dependency graph, cell explanations and deterministic Ask mode (S4.4).

``graph(data)`` reads an .xlsx and returns a validated ``WorkbookGraph`` (om.contracts): one node per non-empty cell
(formula + cached value), edges = each formula's direct precedents (ranges stay ranges, defined names are resolved to
the cells they point at).  ``ask`` answers questions about a workbook by matching row labels and period headers; it
never guesses: a question it cannot resolve says so and lists the nearest labels.  No model is called anywhere.
"""
from __future__ import annotations

import difflib
import re

from . import formula as fx
from .contracts import GraphNode, WorkbookGraph
from .xlsx import Book, col_letter, quote_sheet, read, ref, split_ref

_CELL_RE = re.compile(r"^(?:'((?:[^']|'')+)'|([^'!]+))!\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?$")
_PERIOD_RE = re.compile(r"^\s*(?:FY\s?|CY\s?)?((?:19|20)\d\d)\s*[AEae]?\s*$")
_NAME_TARGET = re.compile(r"^(?:'[^']+'|[^'!:\s]+)!\$?[A-Z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Z]{1,3}\$?[1-9][0-9]*)?$")
_MAX_RANGE = 200_000


# --------------------------------------------------------------------------- keys
def split_key(key: str) -> tuple[str, int, int, int, int]:
    """'Sheet!A1' or 'Sheet!A1:B9' -> (sheet, r1, c1, r2, c2)."""
    m = _CELL_RE.match(key.strip())
    if not m:
        raise ValueError(f"bad cell reference {key!r}")
    sheet = (m.group(1) or m.group(2) or "").replace("''", "'")
    r1, c1 = split_ref(f"{m.group(3)}{m.group(4)}")
    if m.group(5):
        r2, c2 = split_ref(f"{m.group(5)}{m.group(6)}")
        return sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)
    return sheet, r1, c1, r1, c1


def key_of(sheet: str, r: int, c: int) -> str:
    return f"{quote_sheet(sheet)}!{ref(r, c)}"


def norm_key(cell: str) -> str:
    sheet, r, c, _, _ = split_key(cell)
    return key_of(sheet, r, c)


def _range_key(sheet: str, r1: int, c1: int, r2: int, c2: int) -> str:
    return key_of(sheet, r1, c1) if (r1, c1) == (r2, c2) else f"{key_of(sheet, r1, c1)}:{ref(r2, c2)}"


# --------------------------------------------------------------------------- graph
def _walk(node, names: dict, out: list, seen_names: frozenset = frozenset()) -> None:
    k = node[0]
    if k == "cell":
        out.append(_range_key(node[1], node[2], node[3], node[2], node[3]))
    elif k == "range":
        out.append(_range_key(node[1], node[2], node[3], node[4], node[5]))
    elif k == "name":
        if node[1] in names and node[1] not in seen_names:
            _walk(names[node[1]], names, out, seen_names | {node[1]})
    elif k == "bin":
        _walk(node[2], names, out, seen_names)
        _walk(node[3], names, out, seen_names)
    elif k == "neg":
        _walk(node[1], names, out, seen_names)
    elif k == "fn":
        for a in node[2]:
            _walk(a, names, out, seen_names)


def _scalar(v):
    if isinstance(v, fx.Err):
        return v.code
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    return v


def graph(data: bytes) -> WorkbookGraph:
    book = read(data)
    eng = fx.from_book(book)
    nodes, edges = {}, {}
    for sheet in book.order:
        if "'" in sheet:
            continue                                   # sheet names with quotes can't be NODE_REF keys
        for (r, c), cell in sorted(book.sheets[sheet].items()):
            if cell.formula is None and (cell.value is None or cell.value == ""):
                continue
            key = key_of(sheet, r, c)
            nodes[key] = GraphNode(formula=cell.formula, value=_scalar(cell.value))
            ast = eng.ast.get((sheet, r, c))
            if ast is not None:
                found: list = []
                _walk(ast, eng.names, found)
                found = list(dict.fromkeys(found))
                if found:
                    edges[key] = found
    names = {n: t for n, t in book.names.items()
             if t and not n.startswith("_xlnm") and _NAME_TARGET.match(t)}
    return WorkbookGraph(nodes=nodes, edges=edges, names=names).validate()


def _expand(g: WorkbookGraph, target: str) -> list[str]:
    """A precedent entry as node keys that exist (a range becomes the cells in it)."""
    if ":" not in target:
        return [target] if target in g.nodes else []
    sheet, r1, c1, r2, c2 = split_key(target)
    if (r2 - r1 + 1) * (c2 - c1 + 1) <= _MAX_RANGE:
        keys = (key_of(sheet, r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1))
        return [k for k in keys if k in g.nodes]
    out = []
    for k in g.nodes:
        s, r, c, _, _ = split_key(k)
        if s == sheet and r1 <= r <= r2 and c1 <= c <= c2:
            out.append(k)
    return out


def direct_precedents(g: WorkbookGraph, cell: str) -> list[str]:
    """Edges as stored (ranges kept as ranges)."""
    return list(g.edges.get(norm_key(cell), []))


def precedents(g: WorkbookGraph, cell: str, depth: int | None = None) -> list[str]:
    """Every cell that feeds ``cell`` (breadth first, nearest first); ranges expand to the cells in them."""
    start = norm_key(cell)
    seen, order, frontier, d = {start}, [], [start], 0
    while frontier and (depth is None or d < depth):
        d += 1
        nxt = []
        for k in frontier:
            for t in g.edges.get(k, []):
                for p in _expand(g, t):
                    if p not in seen:
                        seen.add(p)
                        order.append(p)
                        nxt.append(p)
        frontier = nxt
    return order


def _reverse(g: WorkbookGraph) -> dict:
    rev: dict = {}
    for src, targets in g.edges.items():
        for t in targets:
            for p in _expand(g, t):
                rev.setdefault(p, []).append(src)
    return rev


def dependents(g: WorkbookGraph, cell: str, depth: int | None = None) -> list[str]:
    """Every cell that uses ``cell`` (breadth first, nearest first)."""
    start = norm_key(cell)
    rev = _reverse(g)
    seen, order, frontier, d = {start}, [], [start], 0
    while frontier and (depth is None or d < depth):
        d += 1
        nxt = []
        for k in frontier:
            for p in rev.get(k, []):
                if p not in seen:
                    seen.add(p)
                    order.append(p)
                    nxt.append(p)
        frontier = nxt
    return order


def inputs_of(g: WorkbookGraph, cell: str) -> list[str]:
    """Leaf inputs behind ``cell``: typed numbers (no formula) it transitively depends on."""
    out = []
    for p in precedents(g, cell):
        n = g.nodes[p]
        if n.formula is None and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            out.append(p)
    return out


# --------------------------------------------------------------------------- labels
def _text(book: Book, sheet: str, r: int, c: int) -> str | None:
    cell = book.sheets.get(sheet, {}).get((r, c))
    if cell and cell.formula is None and isinstance(cell.value, str) and cell.value.strip():
        return cell.value.strip()
    return None


def _label_col(book: Book, sheet: str, r: int) -> int | None:
    for c in (1, 2):
        if _text(book, sheet, r, c):
            return c
    return None


def row_label(book: Book, sheet: str, r: int) -> str | None:
    c = _label_col(book, sheet, r)
    return _text(book, sheet, r, c) if c else None


def _period_of_text(v) -> int | None:
    if isinstance(v, str):
        m = _PERIOD_RE.match(v)
        if m:
            return int(m.group(1))
    return None


def period_header(book: Book, sheet: str, r: int, c: int) -> str | None:
    """Period header for a cell: row 5 (or 6) of its column, else the nearest FY-style header above it."""
    for hr in (5, 6):
        t = _text(book, sheet, hr, c)
        if t and (_period_of_text(t) or re.match(r"^(FY|CY|Q\d)", t, re.I)):
            return t
    for hr in range(r - 1, 0, -1):
        t = _text(book, sheet, hr, c)
        if t and _period_of_text(t) and re.search(r"[A-Za-z]", t):
            return t
    return None


def label_of(book: Book, cell: str) -> str:
    """'Revenue (FY2026E)': the row label from column A/B plus the period header from rows 5-6."""
    sheet, r, c, _, _ = split_key(cell)
    base = row_label(book, sheet, r) or ""
    ph = period_header(book, sheet, r, c) if c > 2 else None
    if base and ph:
        return f"{base} ({ph})"
    return base or ph or ""


def _periods(book: Book, sheet: str) -> dict:
    """year -> column for the sheet's period header row (row 5, else the first row with several FY headers)."""
    grid = book.sheets.get(sheet, {})
    rows = sorted({r for r, _ in grid})
    for hr in [5] + [x for x in rows if x != 5][:40]:
        found = {}
        for (r, c), cell in grid.items():
            if r == hr and c > 2 and cell.formula is None and isinstance(cell.value, str):
                y = _period_of_text(cell.value)
                if y and re.search(r"FY|[AE]\s*$", cell.value, re.I):
                    found.setdefault(y, c)
        if len(found) >= 2:
            return found
    return {}


def _is_actual(book: Book, sheet: str, c: int, year: int) -> bool | None:
    for (r, cc), cell in book.sheets.get(sheet, {}).items():
        if cc == c and isinstance(cell.value, str) and _period_of_text(cell.value) == year:
            return cell.value.strip().upper().endswith("A")
    return None


def explain(data: bytes, cell: str, *, _graph: WorkbookGraph | None = None, _book: Book | None = None) -> dict:
    """Formula, value, labelled precedent tree to depth 2, and the leaf inputs with their source comments / links."""
    book = _book or read(data)
    g = _graph or graph(data)
    key = norm_key(cell)
    if key not in g.nodes:
        raise KeyError(f"{key} is empty or not in the workbook")

    def info(k: str) -> dict:
        n = g.nodes[k]
        return {"cell": k, "label": label_of(book, k), "formula": n.formula, "value": n.value}

    def comment_of(k: str) -> tuple[str | None, str | None]:
        sh, r, c, _, _ = split_key(k)
        return book.comments.get(sh, {}).get((r, c)), book.links.get(sh, {}).get((r, c))

    def tree(k: str, depth: int) -> list:
        out = []
        if depth <= 0:
            return out
        for t in g.edges.get(k, []):
            if ":" in t:
                cells = _expand(g, t)
                out.append({"cell": t, "range": True, "n_cells": len(cells), "label": label_of(book, t.split(":")[0]),
                            "values": [g.nodes[x].value for x in cells][:12]})
                continue
            if t not in g.nodes:
                out.append({"cell": t, "label": label_of(book, t), "formula": None, "value": None, "empty": True, "precedents": []})
                continue
            d = info(t)
            d["precedents"] = tree(t, depth - 1)
            out.append(d)
        return out

    res = info(key)
    res["precedents"] = tree(key, 2)
    leaves = []
    for k in inputs_of(g, key):
        d = info(k)
        c, link = comment_of(k)
        d["source"] = c
        d["link"] = link
        leaves.append(d)
    res["inputs"] = leaves
    return res


# --------------------------------------------------------------------------- ask mode
_STOP = {"what", "whats", "is", "are", "the", "of", "in", "for", "a", "an", "to", "from", "does", "do", "did", "me", "show", "tell",
         "give", "how", "much", "many", "was", "will", "be", "by", "at", "on", "and", "our", "my", "its", "it", "this", "that",
         "which", "where", "come", "comes", "coming", "drive", "drives", "driven", "driving", "feed", "feeds", "feeding", "affect",
         "affects", "depend", "depends", "depending", "cells", "cell", "number", "value", "year", "fiscal", "forecast", "forecasted",
         "projected", "actual", "latest", "calculated", "computed", "derived", "built", "source", "who", "whats", "with", "has", "have",
         "any", "s", "per", "amount", "total"}
_PHRASES = [
    (r"\bd\s*&\s*a\b", "da"), (r"\bdepreciation\s*(?:and|&)?\s*amortization\b", "da"), (r"\bfree cash flows?\b", "fcf"),
    (r"\bcapital expenditures?\b", "capex"), (r"\bearnings per share\b", "eps"), (r"\bdiluted eps\b", "eps"),
    (r"\bnet (?:profit|earnings)\b", "net income"), (r"\bbottom line\b", "net income"), (r"\boperating (?:profit|income)\b", "ebit"),
    (r"\bcost of goods sold\b|\bcogs\b|\bcost of sales\b", "cost revenue"), (r"\bcost of revenue\b", "cost revenue"),
    (r"\bsg\s*&\s*a\b", "sga"), (r"\bselling,? general (?:and|&) administrative\b", "sga"), (r"\bresearch (?:and|&) development\b", "rd"),
    (r"\br\s*&\s*d\b", "rd"), (r"\bweighted average cost of capital\b|\bdiscount rate\b", "wacc"),
    (r"\bshare price\b|\bprice per share\b|\bvalue per share\b", "value share"), (r"\bpre-?tax\b", "pretax"),
    (r"\bturnover\b|\bsales\b|\btop line\b|\btopline\b", "revenue"), (r"\bmargins\b", "margin"), (r"\bpercent(?:age)?\b", ""),
    (r"\bbalance sheet\b", "bs"), (r"\bcash flow from operations\b|\boperating cash flow\b|\bcash from operations\b", "cfo"),
    (r"\bcash from operating activities\b", "cfo"), (r"\btax rate\b", "tax rate"), (r"\bearnings\b", "income"),
    (r"\bprofit\b", "income"), (r"\bshares\b", "share"), (r"\bgrowth rate\b", "growth"), (r"\bgrowing\b", "growth"),
]
_TRACE = re.compile(r"\b(drive|drives|driven|driving|driver|drivers|feed|feeds|feeding|fed|depend|depends|depending|come from|comes from|"
                    r"coming from|derived|derive|built from|made up|made of|calculated|computed|how is|how does|how do|affect|affects|"
                    r"behind|underlying|inputs? (?:to|of|for)|go into|goes into|flow into|flows into)\b", re.I)
_SHEET_PENALTY = {"is": 0, "cf": 0, "bs": 0, "dcf": 1, "assumptions": 2, "schedules": 2, "debt": 2, "cover": 3, "filings": 4, "checks": 5}


def _canon(text: str) -> list[str]:
    s = text.lower().replace("’", "'")
    for pat, rep in _PHRASES:
        s = re.sub(pat, f" {rep} ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if t not in _STOP]


def _label_tokens(label: str, previous: str | None) -> list[str]:
    """Tokens of a row label; '% margin' / '% growth' rows borrow the row above ('EBITDA' + '% margin')."""
    if label.strip().startswith("%") and previous:
        label = f"{previous} {label}"
    toks = _canon(label)
    return toks


def _query_period(q: str) -> tuple[int | None, str]:
    """Year mentioned in the question (FY2026, 2026E, fy26 not supported) and the question with it removed."""
    m = re.search(r"\b(?:fy\s?|cy\s?)?((?:19|20)\d\d)\s*[ae]?\b", q, re.I)
    if not m:
        return None, q
    return int(m.group(1)), (q[:m.start()] + " " + q[m.end():])


def _index(book: Book) -> list[dict]:
    rows = []
    for sheet in book.order:
        grid = book.sheets[sheet]
        prev = None
        for r in sorted({rc[0] for rc in grid}):
            label = row_label(book, sheet, r)
            if not label:
                continue
            vals = {c: cell for (rr, c), cell in grid.items() if rr == r and c > 2 and (cell.formula or cell.value not in (None, ""))}
            toks = _label_tokens(label, prev)
            display = f"{prev} {label}" if label.strip().startswith("%") and prev else label
            if not label.strip().startswith("%"):
                prev = label
            if vals:
                rows.append({"sheet": sheet, "row": r, "label": label, "display": display, "tokens": toks, "cells": vals,
                             "penalty": _SHEET_PENALTY.get(sheet.lower(), 1)})
    return rows


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        if abs(v) < 5 and v != int(v):
            return f"{v:.4g}"
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) < 1e4 else f"{v:,.0f}"
    return str(v)


def _nearest(book: Book, q_tokens: list[str], index: list[dict], n: int = 5) -> list[str]:
    labels = list(dict.fromkeys(r["label"] for r in index))
    want = " ".join(q_tokens)
    scored = sorted(labels, key=lambda l: -(difflib.SequenceMatcher(None, want, " ".join(_canon(l))).ratio()
                                            + 0.5 * len(set(q_tokens) & set(_canon(l)))))
    return scored[:n]


def ask(data: bytes, question: str, *, _book: Book | None = None, _graph: WorkbookGraph | None = None) -> dict:
    """Deterministic question answering over a workbook: {"answer", "cells", "values", "method"}."""
    book = _book or read(data)
    q = question.strip()
    year, rest = _query_period(q)
    trace = bool(_TRACE.search(q))
    toks = _canon(rest)
    index = _index(book)
    if not toks:
        return {"answer": "I could not tell which line item you mean; name a row such as revenue, EBITDA margin or free cash flow.",
                "cells": [], "values": [], "method": "unresolved: no line item in the question"}
    wanted = set(toks)
    cands = []
    for row in index:
        have = set(row["tokens"])
        if not wanted <= have:
            continue
        if year is not None:
            per = _periods(book, row["sheet"])
            if year not in per or per[year] not in row["cells"]:
                continue
        cands.append((len(have - wanted) + row["penalty"], row["sheet"] != "Cover", row))
    cands.sort(key=lambda t: (t[0], book.order.index(t[2]["sheet"]), t[2]["row"]))
    if not cands:
        near = _nearest(book, toks, index)
        extra = f" (no column for {year} on a matching row)" if year is not None and any(wanted <= set(r["tokens"]) for r in index) else ""
        return {"answer": f"I can't find that in the workbook{extra}; I won't guess a number. Nearest labels: " + "; ".join(near) + ".",
                "cells": [], "values": [], "method": "unresolved: no row label matched " + " ".join(toks)}
    best = cands[0][2]
    sheet, r = best["sheet"], best["row"]
    per = _periods(book, sheet)
    inv = {c: y for y, c in per.items()}
    if year is not None:
        cols = [per[year]]
    else:
        cols = sorted(best["cells"])
    if trace:
        col = cols[0] if year is not None else _pick_forecast_col(book, sheet, best, inv)
        return _answer_trace(data, book, _graph, best, col)
    cells = [key_of(sheet, r, c) for c in cols]
    vals = [best["cells"][c].value for c in cols]
    parts = []
    for c, v in zip(cols, vals):
        ph = period_header(book, sheet, r, c) if len(best["cells"]) > 1 else None
        parts.append(f"{ph + ': ' if ph and len(cols) > 1 else ''}{_fmt(v)}")
    ph1 = period_header(book, sheet, r, cols[0]) if len(best["cells"]) > 1 else None
    head = f"{best['display']}{' ' + ph1 if ph1 and len(cols) == 1 else ''}"
    where = ", ".join(cells[:4]) + (" ..." if len(cells) > 4 else "")
    others = [f"{c[2]['sheet']}!row {c[2]['row']} ({c[2]['display']})" for c in cands[1:3]]
    ans = f"{head} = {'; '.join(parts)} ({where})."
    if others:
        ans += " Other matching rows: " + "; ".join(others) + "."
    return {"answer": ans, "cells": cells, "values": vals,
            "method": f"label match on {sheet} row {r} ({best['label']!r})" + (f", period column {col_letter(cols[0])} for {year}" if year is not None else ", all periods")}


def _pick_forecast_col(book: Book, sheet: str, row: dict, inv: dict) -> int:
    cols = sorted(row["cells"])
    for c in cols:
        if inv.get(c) is not None and _is_actual(book, sheet, c, inv[c]) is False:
            return c
    return cols[-1] if cols else 3


def _answer_trace(data, book, g, row, col) -> dict:
    g = g or graph(data)
    sheet, r = row["sheet"], row["row"]
    target = key_of(sheet, r, col)
    if target not in g.nodes:
        return {"answer": f"{row['label']} has no value at {target}.", "cells": [], "values": [], "method": "unresolved: empty target"}
    ex = explain(data, target, _graph=g, _book=book)
    if len(row["cells"]) == 1:
        ex["label"] = row["display"]
    n = g.nodes[target]
    if n.formula is None:
        return {"answer": f"{ex['label']} is a typed input ({_fmt(n.value)}) at {target}; nothing feeds it.",
                "cells": [target], "values": [n.value], "method": f"label match on {sheet} row {r}; no formula"}
    direct = [p for p in ex["precedents"]]
    lines = []
    cells, vals = [target], [n.value]
    for p in direct:
        if p.get("range"):
            lines.append(f"{p['cell']} ({p['n_cells']} cells)")
            cells.append(p["cell"])
            vals.append(p["values"])
        else:
            lines.append(f"{p['label'] or p['cell']} {p['cell']} = {_fmt(p['value'])}")
            cells.append(p["cell"])
            vals.append(p["value"])
    ans = f"{ex['label']} = {_fmt(n.value)} at {target}, formula {n.formula}. It is fed by: " + "; ".join(lines) + "."
    if ex["inputs"]:
        ans += " Ultimate inputs: " + "; ".join(
            f"{i['label'] or i['cell']} {i['cell']} = {_fmt(i['value'])}" + (f" [{i['source'][:60]}]" if i.get("source") else "")
            for i in ex["inputs"][:6]) + (" ..." if len(ex["inputs"]) > 6 else "") + "."
    return {"answer": ans, "cells": cells, "values": vals, "method": f"label match on {sheet} row {r}; direct precedents from the formula graph"}
