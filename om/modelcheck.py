"""Grade any Excel model against the bar independent reviewers use (WSP, ICAEW, Vals, Ankura).

grade(xlsx_bytes) -> {"score", "production_ready", "graders": [...]}. Works on any workbook, not only ours:

  calculates     no #REF!/#DIV/0!/#VALUE! etc. (formulas without saved results are calculated here)
  checks         a Checks tab exists and every check reads OK
  balances       total assets = total liabilities + equity in every column (found by row labels)
  constants      no numbers typed inside formulas ("=C5*1.05"); structural constants allowed
  consistency    no formula that breaks the pattern of its neighbours across a row, and no typed number
                 sitting where the row's formula should be (Excel's "inconsistent formula", plus plugs)
  colours        typed numbers blue, formulas not blue (links to other sheets green is reported, not required)
  circularity    circular references only with iterative calculation on and a 1/0 breaker; converges
  sources        typed historical numbers carry a comment or link saying where they came from

A model is production-ready only if every critical grader passes.
"""
from __future__ import annotations

import re

from . import formula as fx
from .xlsx import CROSS_SHEET, literals, read, ref, relative

ALLOWED_CONSTANTS = {0.0, 1.0, 0.5, 2.0, 100.0, 365.0, 360.0, 12.0, 4.0, 52.0, 1000.0, 1e6}
BLUES = {"0000FF", "0070C0", "0000CC", "1F4E79", "2F5597", "3333FF", "0000EE"}
CHECK_FAIL = re.compile(r"^\s*(error|fail(ed)?|false|not ok|mismatch|x|✗)\b", re.I)
INPUT_SHEET = re.compile(r"assum|input|driver|scenario|case|dcf|valuation|lbo|returns|cover|check", re.I)
NON_NEGATIVE = re.compile(r"^(cash|accounts receivable|receivables|inventor|accounts payable|payables|pp&e|property|goodwill|intangible|revolver|term debt|total debt|long-term debt|short-term debt)", re.I)
CRITICAL = ("calculates", "checks", "balances", "signs", "constants", "consistency", "circularity")


def _cells(book):
    for name in book.order:
        for rc, c in book.sheets[name].items():
            yield name, rc, c


def _result(gid, title, passed, score, detail, cells=None, critical=None):
    return {"id": gid, "title": title, "passed": passed, "score": round(score, 3), "detail": detail,
            "cells": list(cells or []), "n_cells": len(cells or []), "critical": gid in CRITICAL if critical is None else critical}


def _where(sheet, rc):
    return f"{sheet}!{ref(*rc)}"


def grade(data: bytes, *, recalc_fallback: bool = True) -> dict:
    book = read(data)
    graders = []

    # ------------------------------------------------------------ calculate (use saved values; else our engine)
    formulas = [(s, rc, c) for s, rc, c in _cells(book) if c.formula]
    missing = sum(1 for _, _, c in formulas if c.value is None)
    eng = fx.from_book(book)
    eng.calculate(iterate=True)
    values = {}
    if missing > len(formulas) * 0.2:
        values = {k: v for k, v in eng.values.items()}
        source = "calculated here (the file has no saved results)"
        if eng.unsupported and recalc_fallback:
            from .consistency import recalc
            fresh = recalc(data)
            if fresh:
                lo = read(fresh)
                values = {(sh, r, c): cell.value for sh, g in lo.sheets.items() for (r, c), cell in g.items() if cell.formula}
                for (sh, r, c), cell in [((sh, r, c), cell) for sh, g in lo.sheets.items() for (r, c), cell in g.items()]:
                    if cell.is_error:
                        values[(sh, r, c)] = fx.Err(str(cell.value))
                source = f"recalculated with LibreOffice (functions our engine doesn't evaluate yet: {', '.join(sorted(eng.unsupported))})"
            else:
                source = (f"calculated here; cells using {', '.join(sorted(eng.unsupported))} could not be evaluated "
                          "(install LibreOffice or save the file in Excel to grade them)")
    else:
        source = "saved results in the file"
    val = lambda s, rc, c: values.get((s, rc[0], rc[1]), c.value) if values else c.value
    errs = [f"{k[0]}!{ref(k[1], k[2])} invalid formula {str(eng.raw[k])[:50]!r}" for k in eng.invalid]
    blame_us = bool(eng.unsupported) and source.startswith("calculated here;")
    skipped = 0
    for s, rc, c in formulas:
        if (s, rc[0], rc[1]) in eng.invalid:
            continue
        v = val(s, rc, c)
        if blame_us and v == fx.NAME:
            skipped += 1
            continue
        if isinstance(v, fx.Err) or c.is_error or (isinstance(v, str) and re.match(r"^#(REF!|DIV/0!|VALUE!|NAME\?|NUM!|N/A|NULL!)$", v)):
            errs.append(f"{_where(s, rc)} {v}")
    graders.append(_result("calculates", "Calculates without errors", False if errs else (None if skipped else True),
                           1.0 if not errs else max(0.0, 1 - len(errs) / max(len(formulas), 1) * 20),
                           f"{len(formulas):,} formulas; {len(errs)} error cells ({len(eng.invalid)} not valid Excel)"
                           + (f"; {skipped} cells not evaluated" if skipped else "") + f" — {source}", errs))

    # ------------------------------------------------------------ checks tab
    check_sheets = [n for n in book.order if re.search(r"check", n, re.I)]
    fails, n_checks = [], 0
    for n in check_sheets:
        for rc, c in book.sheets[n].items():
            v = val(n, rc, c)
            if rc[1] == 1:
                continue
            if isinstance(v, str) and v.strip().upper() == "OK" or v is True:
                n_checks += 1
            elif (isinstance(v, str) and CHECK_FAIL.match(v)) or v is False or isinstance(v, fx.Err):
                n_checks += 1
                fails.append(f"{_where(n, rc)} {v}")
    if not check_sheets:
        graders.append(_result("checks", "Checks tab, all checks pass", False, 0.0, "no Checks tab: integrity is not tested inside the model"))
    else:
        graders.append(_result("checks", "Checks tab, all checks pass", n_checks > 0 and not fails, 1 - len(fails) / max(n_checks, 1) if n_checks else 0.0,
                               (f"{n_checks} check results on {', '.join(check_sheets)}; {len(fails)} failing" if n_checks else
                                f"{', '.join(check_sheets)} has no OK / ERROR results, so nothing is actually checked"), fails))

    # ------------------------------------------------------------ balance sheet balances
    def row_of(sheet, pattern):
        for rc, c in book.sheets[sheet].items():
            if rc[1] <= 2 and isinstance(c.value, str) and re.fullmatch(pattern, c.value.strip(), re.I):
                return rc[0]
        return None
    bal_rows, unbalanced, cols_checked = [], [], 0
    for n in book.order:
        ta = row_of(n, r"total assets")
        tle = row_of(n, r"total liabilities (and|&) (shareholders'? |stockholders'? )?equity")
        if ta and tle:
            bal_rows.append(n)
            grid = book.sheets[n]
            for col in sorted({rc[1] for rc in grid if rc[1] > 2}):
                a, b = grid.get((ta, col)), grid.get((tle, col))
                if not a or not b:
                    continue
                va, vb = val(n, (ta, col), a), val(n, (tle, col), b)
                if isinstance(va, float) and isinstance(vb, float):
                    cols_checked += 1
                    if abs(va - vb) > max(0.5, 1e-6 * abs(va)):
                        unbalanced.append(f"{n}!{ref(ta, col)}: assets {va:,.1f} vs L&E {vb:,.1f}")
    if not bal_rows:
        graders.append(_result("balances", "Balance sheet balances every period", None, 1.0,
                               "not applicable: no balance sheet in this model (rows 'Total assets' and 'Total liabilities & equity')"))
    else:
        graders.append(_result("balances", "Balance sheet balances every period", cols_checked > 0 and not unbalanced, 1 - len(unbalanced) / max(cols_checked, 1),
                               f"{cols_checked} periods checked on {', '.join(bal_rows)}; {len(unbalanced)} out of balance", unbalanced))

    # ------------------------------------------------------------ signs: balance-sheet lines that can't be negative
    negs, n_sign = [], 0
    for n in bal_rows:
        grid = book.sheets[n]
        for (r, col), c in grid.items():
            if col > 2:
                continue
            if isinstance(c.value, str) and NON_NEGATIVE.match(c.value.strip()):
                for (r2, c2), cell in grid.items():
                    if r2 == r and c2 > 2:
                        v = val(n, (r2, c2), cell)
                        if isinstance(v, float):
                            n_sign += 1
                            if v < -0.5:
                                negs.append(f"{n}!{ref(r2, c2)} {c.value.strip()} = {v:,.1f}")
    if bal_rows:
        graders.append(_result("signs", "Balance-sheet lines have sensible signs", not negs, 1 - len(negs) / max(n_sign, 1),
                               f"{n_sign} values checked (cash, receivables, inventory, payables, PP&E, goodwill, debt); {len(negs)} negative", negs))

    # ------------------------------------------------------------ constants inside formulas
    hard = []
    for s, rc, c in formulas:
        lits = [x for x in literals(c.formula) if x not in ALLOWED_CONSTANTS]
        if lits:
            hard.append(f"{_where(s, rc)} {c.formula[:60]}")
    graders.append(_result("constants", "No numbers typed inside formulas", not hard, 1 - len(hard) / max(len(formulas), 1),
                           f"{len(hard)} of {len(formulas):,} formulas contain a typed number other than 0, 1, 0.5, 365 and similar", hard))

    # ------------------------------------------------------------ row consistency + plugs
    broken, plugs = [], []
    for n in book.order:
        grid = book.sheets[n]
        for (r, col), c in grid.items():
            left, right = grid.get((r, col - 1)), grid.get((r, col + 1))
            if not (left and right and left.formula and right.formula):
                continue
            rl, rr = relative(left.formula, r, col - 1), relative(right.formula, r, col + 1)
            if rl != rr:
                continue
            l2, r2 = grid.get((r, col - 2)), grid.get((r, col + 2))
            run = (l2 and l2.formula and relative(l2.formula, r, col - 2) == rl) or (r2 and r2.formula and relative(r2.formula, r, col + 2) == rr)
            if not run:
                continue                       # alternating column types (value, change, value, change): not a pattern
            if c.formula:
                if relative(c.formula, r, col) != rl:
                    broken.append(f"{_where(n, (r, col))} {c.formula[:50]} (neighbours: {left.formula[:40]})")
            elif isinstance(c.value, float):
                plugs.append(f"{_where(n, (r, col))} typed {c.value:,.2f} between formulas {left.formula[:40]}")
    bad = broken + plugs
    graders.append(_result("consistency", "Formulas consistent across each row; no typed plugs", not bad, 1 - len(bad) / max(len(formulas), 1) * 10,
                           f"{len(broken)} formulas break their row's pattern; {len(plugs)} typed numbers replace a formula", bad))

    # ------------------------------------------------------------ colours
    wrong_inputs, blue_formulas, links_not_green, n_inputs, n_links = [], [], [], 0, 0
    for s, rc, c in _cells(book):
        if c.formula:
            if c.color in BLUES:
                blue_formulas.append(_where(s, rc))
            if CROSS_SHEET.search(c.formula):
                n_links += 1
                if c.color not in ("008000", "00B050", "006100", "00B000"):
                    links_not_green.append(_where(s, rc))
        elif isinstance(c.value, float):
            n_inputs += 1
            if c.color not in BLUES:
                wrong_inputs.append(_where(s, rc))
    total = n_inputs + len(formulas)
    misses = len(wrong_inputs) + len(blue_formulas)
    graders.append(_result("colours", "Colour code: typed numbers blue, formulas black", misses == 0, 1 - misses / max(total, 1),
                           f"{len(wrong_inputs)} of {n_inputs:,} typed numbers not blue; {len(blue_formulas)} formulas coloured as inputs; "
                           f"{len(links_not_green)} of {n_links:,} links to other sheets not green (reported only)",
                           wrong_inputs + blue_formulas, critical=False))

    # ------------------------------------------------------------ circularity
    cyc = _cycles(eng)
    if not cyc:
        graders.append(_result("circularity", "Circularity handled", True, 1.0, "no circular references"))
    else:
        cyc_formulas = [eng.raw[k] for k in cyc if isinstance(eng.raw.get(k), str)]
        breaker = any(re.search(r"IF\(\s*[A-Za-z_][\w.]*\s*=\s*1", f or "") for f in cyc_formulas) or \
            any(re.search(r"IF\(", f or "") and re.search(r"(?i)circ", f or "") for f in cyc_formulas)
        ok = book.iterate and breaker and eng.converged
        graders.append(_result("circularity", "Circularity handled", ok, 1.0 if ok else 0.3 if book.iterate else 0.0,
                               f"{len(cyc)} cells in circular loops; iterative calculation {'on' if book.iterate else 'OFF'}; "
                               f"1/0 breaker {'found' if breaker else 'not found'}; {'converges' if eng.converged else 'does not converge'} "
                               f"({eng.iterations} iterations)", [f"{k[0]}!{ref(k[1], k[2])}" for k in sorted(cyc)]))

    # ------------------------------------------------------------ sources on typed historical numbers
    typed = [(s, rc) for s, rc, c in _cells(book) if not c.formula and isinstance(c.value, float) and not INPUT_SHEET.search(s)]
    sourced = [x for x in typed if x[1] in book.comments.get(x[0], {}) or x[1] in book.links.get(x[0], {})]
    unsourced = [_where(s, rc) for s, rc in typed if (s, rc) not in set(sourced)]
    share = len(sourced) / len(typed) if typed else 1.0
    graders.append(_result("sources", "Typed historical numbers carry their source", not unsourced, share,
                           f"{len(sourced)} of {len(typed)} typed numbers outside input sheets have a source comment or link", unsourced, critical=False))

    crit_ok = all(g["passed"] is not False for g in graders if g["critical"])
    weights = {"calculates": 3, "checks": 2, "balances": 3, "signs": 2, "constants": 2, "consistency": 2, "colours": 1, "circularity": 2, "sources": 2}
    scored = [g for g in graders if g["passed"] is not None]
    score = sum(weights[g["id"]] * g["score"] for g in scored) / sum(weights[g["id"]] for g in scored)
    return {"score": round(100 * score, 1), "production_ready": crit_ok, "graders": graders,
            "stats": {"sheets": book.order, "formulas": len(formulas), "typed_numbers": n_inputs}}


def _cycles(eng: fx.Engine) -> set:
    """Cells that sit in a circular loop (strongly connected components larger than one cell, or self-loops)."""
    graph = {k: [d for d in fx.deps(a, eng.names, set()) if d in eng.ast] for k, a in eng.ast.items()}
    index, low, on, stack, out, counter = {}, {}, set(), [], set(), [0]
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(graph[root]))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on.add(root)
        while work:
            node, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(graph[nxt])))
                elif nxt in on:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in graph[node]:
                    out.update(comp)
    return out


def report_md(name: str, g: dict) -> str:
    lines = [f"### {name}: {g['score']}/100 — {'production-ready' if g['production_ready'] else 'NOT production-ready'}", "",
             "| Grader | Result | Detail |", "|---|---|---|"]
    for r in g["graders"]:
        res = "n/a" if r["passed"] is None else ("PASS" if r["passed"] else "FAIL") + f" ({r['score']:.0%})"
        lines.append(f"| {r['title']}{' (critical)' if r['critical'] else ''} | {res} | {r['detail']} |")
    return "\n".join(lines)
