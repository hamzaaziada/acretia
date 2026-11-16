"""OM-Bench (models): build, grade and stress-test our Excel engine the way independent reviewers test AI tools.

Tasks
  model     build the integrated three-statement + DCF model for each company from its SEC filings, then grade
            it with om.modelcheck (calculates, checks, balances, signs, constants, consistency, colours,
            circularity, sources). Also records build time and solver convergence.
  audit     plant ten realistic modelling errors (one per copy) in a clean model and measure how many the
            graders catch, and at which cell. A clean copy must pass (no false alarms).
  agree     optional: recalculate with LibreOffice (circularity off) and compare every formula cell with our
            own evaluator, so the numbers we save in the file are proven to match a real spreadsheet engine.

Results go to data/out/bench/<date>/report.md and results.json.
"""
from __future__ import annotations

import copy
import json
import re
import time
from datetime import date
from pathlib import Path

from . import model3, modelcheck
from . import statements as stm
from .formula import calculate_workbook
from .xlsx import quote_sheet, read, ref


def _cell(meta, sheet, key, p):
    return meta["rows"][sheet][key], model3.C0 + p


PLANTS = [
    ("constants", "Typed number inside a forecast formula (revenue × 1.02)", ("constants",)),
    ("plug", "Typed plug overwrites a balance-sheet formula", ("consistency",)),
    ("pattern", "Formula points at the wrong year (D&A row)", ("consistency",)),
    ("ref", "#REF! in the WACC", ("calculates",)),
    ("sign", "Sign error: payables forecast negative", ("signs",)),
    ("equity", "Equity typed over, balance sheet no longer balances", ("balances",)),
    ("colour", "Typed number formatted as a formula (black)", ("colours",)),
    ("unsourced", "Historical figure with its source removed", ("sources",)),
    ("breaker", "Circularity breaker removed (interest always on average balances)", ("circularity",)),
    ("iterate", "Iterative calculation switched off in a circular model", ("circularity",)),
]


def plant(wb, meta, kind: str):
    """Return (workbook copy with one error planted, the cell it sits in or None)."""
    w = copy.deepcopy(wb)
    H = len(meta["years"])
    IS, BS, CF, DT = w["IS"], w["BS"], w["CF"], w["Debt"]
    at = lambda sheet, key, p: _cell(meta, sheet, key, p)
    where = None
    if kind == "constants":
        rc = at("IS", "rev", H + 1)
        IS.cells[rc].value += "*1.02"
        where = ("IS", rc)
    elif kind == "plug":
        rc = at("BS", "oca", H + 2)
        IS_val = BS.cells[rc].cached or 0.0
        BS.set(rc, round(float(IS_val), 0), kind="hist", fmt="num0")
        where = ("BS", rc)
    elif kind == "pattern":
        rc = at("CF", "da", H + 1)
        r_sc = meta["rows"]["Schedules"]["da"]
        CF.cells[rc].value = f"=Schedules!{ref(r_sc, model3.C0 + H)}"
        where = ("CF", rc)
    elif kind == "ref":
        dcf = w["DCF"]
        dcf.cells[(30, 3)].value = "=#REF!*(1-$C$29)+$C$28*$C$29"
        where = ("DCF", (30, 3))
    elif kind == "sign":
        for p in range(H, H + model3.F):
            rc = at("BS", "ap", p)
            BS.cells[rc].value = BS.cells[rc].value.replace("=-", "=", 1)
        where = ("BS", at("BS", "ap", H))
    elif kind == "equity":
        rc = at("BS", "se", H + 3)
        BS.set(rc, round(float(BS.cells[rc].cached or 0) + 5000.0, 0), kind="hist", fmt="num0")
        where = ("BS", rc)
    elif kind == "colour":
        rc = at("IS", "rd", H + 2)
        IS.set(rc, round(float(IS.cells[rc].cached or 0), 0), kind="calc", fmt="num0")
        where = ("IS", rc)
    elif kind == "unsourced":
        rc = at("Filings", "revenue", 0)
        cell = w["Filings"].cells[rc]
        cell.comment = cell.link = None
        where = ("Filings", rc)
    elif kind == "breaker":
        for sh in (DT,):
            for cell in sh.cells.values():
                if isinstance(cell.value, str):
                    cell.value = re.sub(r"IF\(Circ=1,AVERAGE\(([^()]*(?:\([^()]*\))?[^()]*),([^()]*(?:\([^()]*\))?[^()]*)\),[^()]*(?:\([^()]*\))?[^()]*\)",
                                        r"AVERAGE(\1,\2)", cell.value)
    elif kind == "iterate":
        w.iterate = False
    calculate_workbook(w, iterate=True)
    return w, where


def audit(wb, meta) -> dict:
    rows = []
    clean = modelcheck.grade(wb.to_bytes())
    for kind, title, expect in PLANTS:
        w, where = plant(wb, meta, kind)
        g = modelcheck.grade(w.to_bytes())
        failed = {r["id"]: r for r in g["graders"] if not r["passed"]}
        hit = [e for e in expect if e in failed]
        located = None
        if hit and where:
            a = f"{where[0]}!{ref(*where[1])}"
            located = any(c.startswith(a + " ") or c == a or c.startswith(f"{quote_sheet(where[0])}!{ref(*where[1])}")
                          for r in failed.values() for c in r["cells"])
        rows.append({"kind": kind, "error": title, "expected": list(expect), "caught": bool(hit), "located": located,
                     "graders_failed": sorted(failed), "production_ready": g["production_ready"]})
    caught = sum(r["caught"] for r in rows)
    return {"clean_passes": clean["production_ready"] and all(r["passed"] for r in clean["graders"]), "clean_score": clean["score"],
            "planted": len(rows), "caught": caught, "located": sum(1 for r in rows if r["located"]), "rows": rows}


def agree(x: bytes) -> dict | None:
    """Compare our saved results with LibreOffice's recalculation (circularity must be off)."""
    from .consistency import recalc
    lo_bytes = recalc(x)
    if not lo_bytes:
        return None
    ours, lo = read(x), read(lo_bytes)
    n = bad = 0
    diffs = []
    for sh, grid in ours.sheets.items():
        for rc, c in grid.items():
            if not c.formula:
                continue
            n += 1
            other = lo.sheets.get(sh, {}).get(rc)
            a, b = c.value, other.value if other else None
            if isinstance(a, float) and isinstance(b, float):
                same = abs(a - b) <= 1e-6 * max(1.0, abs(a))
            else:
                same = (a if a not in (None, "") else "") == (b if b not in (None, "") else "") or (a in (None, "", 0.0) and b in (None, "", 0.0))
            if not same:
                bad += 1
                diffs.append(f"{sh}!{ref(*rc)} ours {a!r} LibreOffice {b!r}")
    return {"formula_cells": n, "mismatches": bad, "examples": diffs[:5]}


def run(companies: list[tuple[str, dict]], out_dir: Path, *, with_libreoffice: bool = False, audit_ticker: str | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"date": date.today().isoformat(), "models": [], "audit": None}
    built = {}
    for ticker, cf in companies:
        t0 = time.time()
        try:
            s = stm.build(cf, ticker)
            wb, meta = model3.build_workbook(s)
        except model3.UnsupportedCompany as e:
            results["models"].append({"ticker": ticker, "supported": False, "reason": str(e)})
            continue
        x = wb.to_bytes()
        secs = time.time() - t0
        (out_dir / f"{ticker} three-statement model.xlsx").write_bytes(x)
        g = modelcheck.grade(x)
        row = {"ticker": ticker, "name": s.name, "supported": True, "years": meta["years"], "seconds": round(secs, 2),
               "converged": meta["converged"], "iterations": meta["iterations"], "score": g["score"],
               "production_ready": g["production_ready"], "graders": {r["id"]: {"passed": r["passed"], "detail": r["detail"]} for r in g["graders"]},
               "mapping_warnings": meta["warnings"]}
        if with_libreoffice:
            w0, _ = model3.build_workbook(s, circ=0)
            row["libreoffice"] = agree(w0.to_bytes())
        results["models"].append(row)
        built[ticker] = (wb, meta)
    pick = audit_ticker if audit_ticker in built else next(iter(built), None)
    if pick:
        results["audit"] = {"ticker": pick, **audit(*built[pick])}
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    (out_dir / "report.md").write_text(report(results))
    return results


def report(res: dict) -> str:
    L = [f"# OM-Bench — Excel models ({res['date']})", "",
         "Each model is built from SEC filings by code, calculated by our evaluator, and graded by `om.modelcheck`.", "",
         "| Company | Years | Score | Production-ready | Failing graders | Solver | Build | LibreOffice agreement |",
         "|---|---|---|---|---|---|---|---|"]
    for m in res["models"]:
        if not m["supported"]:
            L.append(f"| {m['ticker']} | — | — | not supported | {m['reason']} | | | |")
            continue
        fails = ", ".join(k for k, v in m["graders"].items() if not v["passed"]) or "none"
        lo = m.get("libreoffice")
        lo_txt = "not run" if lo is None else f"{lo['formula_cells'] - lo['mismatches']:,}/{lo['formula_cells']:,} cells match"
        L.append(f"| {m['ticker']} | FY{m['years'][0][:4]}–FY{m['years'][-1][:4]} | {m['score']} | {'yes' if m['production_ready'] else 'NO'} | {fails} | "
                 f"{'converged' if m['converged'] else 'NOT converged'} in {m['iterations']} | {m['seconds']}s | {lo_txt} |")
    a = res.get("audit")
    if a:
        L += ["", f"## Audit: ten planted errors in the {a['ticker']} model", "",
              f"Clean model passes every grader: **{'yes' if a['clean_passes'] else 'NO'}**. "
              f"Caught **{a['caught']}/{a['planted']}**; pointed at the exact cell for {a['located']} of the cell-level errors.", "",
              "| Planted error | Expected grader | Caught | Exact cell | Graders that failed |", "|---|---|---|---|---|"]
        for r in a["rows"]:
            L.append(f"| {r['error']} | {', '.join(r['expected'])} | {'yes' if r['caught'] else 'NO'} | "
                     f"{'—' if r['located'] is None else ('yes' if r['located'] else 'no')} | {', '.join(r['graders_failed']) or 'none'} |")
    warn = [(m["ticker"], w) for m in res["models"] if m.get("supported") for w in m.get("mapping_warnings", [])]
    if warn:
        L += ["", "## Mapping notes from the filings", ""] + [f"- {t}: {w}" for t, w in warn]
    return "\n".join(L) + "\n"
