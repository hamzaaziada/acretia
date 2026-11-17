"""OM-Bench (models): build, grade and stress-test our Excel engine the way independent reviewers test AI tools.

Tasks
  model     build the integrated three-statement + DCF model for each company from its SEC filings, then grade
            it with om.modelcheck (calculates, checks, balances, signs, constants, consistency, colours,
            circularity, sources). Also records build time and solver convergence.
  audit     plant ten realistic modelling errors (one per copy) in a clean model and measure how many the
            graders catch, and at which cell. A clean copy must pass (no false alarms).
  agree     optional: recalculate with LibreOffice (circularity off) and compare every formula cell with our
            own evaluator, so the numbers we save in the file are proven to match a real spreadsheet engine.
  s4        OM-Bench 10 (S4.6): three-statement models for ten public companies plus LBO, merger and comps workbooks,
            each graded, validated (with require_sources) and compared across engines, with build seconds and formula
            counts; and audit_all(): the ten three-statement plants plus nine LBO / merger / comps plants.

Results go to data/out/bench/<date>/report.md and results.json.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from datetime import date
from pathlib import Path

from . import model3, modelcheck, validate_xlsx
from . import statements as stm
from .formula import calculate_workbook
from .xlsx import col_index, quote_sheet, read, ref


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


# =========================================================================== S4.6: planted errors in LBO, merger and comps
NEW_PLANTS = [
    ("lbo", "lbo_sweep", "LBO: cash sweep formula overtyped with a number"),
    ("lbo", "lbo_pik", "LBO: PIK accrual turned into cash-pay (balance stops growing, cash interest absorbs it)"),
    ("lbo", "lbo_exit", "LBO: exit enterprise value typed over"),
    ("merger", "mrg_shares", "Merger: pro forma share count typed over"),
    ("merger", "mrg_goodwill", "Merger: goodwill replaced by a plug"),
    ("merger", "mrg_synergy_tax", "Merger: synergies not tax-effected in one year"),
    ("comps", "cmp_tsm", "Comps: diluted shares use basic shares in one column (no treasury stock method)"),
    ("comps", "cmp_bridge", "Comps: EV bridge drops cash in one column"),
    ("comps", "cmp_nm", "Comps: NM rule removed in one cell"),
]
_LOC = re.compile(r"^'?([^'!]+?)'?!\$?([A-Z]{1,3})\$?(\d+)")


def _split(loc: str) -> tuple[str, tuple[int, int]]:
    m = _LOC.match(loc)
    return m.group(1), (int(m.group(3)), col_index(m.group(2)))


def _type_over(sheet, rc, *, kind="calc", digits=1):
    """An analyst overtypes a formula with its current value (black = calculation style, blue = disguised as an input)."""
    cell = sheet.cells[rc]
    fmt = cell.style.fmt
    sheet.set(rc, round(float(cell.cached or 0.0), digits), kind=kind, fmt=fmt)


def _formula_of(sheet, rc, new: str):
    sheet.cells[rc].value = new
    sheet.cells[rc].cached = None


def plant_new(wb, meta, kind: str):
    """(workbook copy with one LBO / merger / comps error planted, (sheet, (row, col)) of the planted cell)."""
    w = copy.deepcopy(wb)
    pl = meta["plants"]
    rows = meta["rows"]
    if kind == "lbo_sweep":
        sh, rc = _split(pl["sweep"])
        _type_over(w[sh], rc)
    elif kind == "lbo_pik":
        sh, rc = _split(pl["pik"])
        d = w[sh]
        opening = ref(rows["Debt"]["pik_open"], rc[1])
        _formula_of(d, rc, f"={opening}*PikRate*0")
        op = w["Operations"]
        r_cash = rows["Operations"]["int_cash"]
        for (r, c), cell in op.cells.items():
            if r == rows["Operations"]["int_pik"] and isinstance(cell.value, str) and f"Debt!{ref(*rc)}" in cell.value.replace("$", ""):
                _formula_of(op, (r_cash, c), op.cells[(r_cash, c)].value + f"+Debt!{opening}*PikRate")
                break
    elif kind == "lbo_exit":
        sh, rc = _split(pl["exit"])
        _type_over(w[sh], rc)
    elif kind == "mrg_shares":
        sh, rc = _split(pl["shares"])
        _type_over(w[sh], rc)
    elif kind == "mrg_goodwill":
        sh, rc = _split(pl["goodwill"])
        _type_over(w[sh], rc, kind="hist", digits=0)
    elif kind == "mrg_synergy_tax":
        sh, rc0 = _split(pl["synergy_tax"])
        rc = (rc0[0], rc0[1] + 1)                              # the second projection year (the first column of a row may differ legitimately)
        _formula_of(w[sh], rc, f"={ref(rows['Pro forma']['syn'], rc[1])}")
    elif kind == "cmp_tsm":
        sh, rc0 = _split(pl["tsm"])
        rc = (rows["Equity value"]["dil"], rc0[1])
        _formula_of(w[sh], rc, f"={ref(rows['Equity value']['basic'], rc[1])}")
    elif kind == "cmp_bridge":
        sh, rc0 = _split(pl["bridge"])
        E = rows["Equity value"]
        rc = (E["bridge"], rc0[1])
        c = rc[1]
        _formula_of(w[sh], rc, f"={ref(E['debt'], c)}+{ref(E['pref'], c)}+{ref(E['mi'], c)}-{ref(E['sti'], c)}")
    elif kind == "cmp_nm":
        sh, rc = _split(pl["nm"])
        m = re.search(r'"NM",([^",()]+)\)\)$', w[sh].cells[rc].value)
        _formula_of(w[sh], rc, "=" + m.group(1))
    else:
        raise ValueError(kind)
    calculate_workbook(w, iterate=True)
    return w, (sh, rc)


def _flags(v: dict) -> tuple[set, set]:
    """(failing grader ids, {(sheet, cell)} named by any finding or failing grader) from a validate() result."""
    graders = {g["id"] for g in v["modelcheck"]["graders"] if g["passed"] is False}
    cells = {(f["sheet"], f["cell"].replace("$", "")) for f in v["findings"] if f["sheet"] and f["cell"]}
    for g in v["modelcheck"]["graders"]:
        if g["passed"] is False:
            for item in g["cells"]:
                m = _LOC.match(item)
                if m:
                    cells.add((m.group(1), f"{m.group(2)}{m.group(3)}"))
    return graders, cells


def audit_new(wb, meta, model: str) -> dict:
    """Plant this model's errors one at a time. A plant counts as caught when it adds a failing grader or a critical finding that
    the clean workbook does not have, and as located when some finding names the planted cell."""
    clean = validate_xlsx.validate(wb.to_bytes(), require_sources=True)
    base_g, base_c = _flags(clean)
    base_f = {(f["id"], f["sheet"], f["cell"]) for f in clean["findings"]}
    rows = []
    for m, kind, title in NEW_PLANTS:
        if m != model:
            continue
        w, (sh, rc) = plant_new(wb, meta, kind)
        v = validate_xlsx.validate(w.to_bytes(), require_sources=True)
        gs, cs = _flags(v)
        new_crit = sorted({f["id"] for f in v["findings"] if f["severity"] == "critical" and (f["id"], f["sheet"], f["cell"]) not in base_f})
        new_g = sorted(gs - base_g)
        at = ref(*rc)
        rows.append({"kind": kind, "model": model, "error": title, "cell": f"{sh}!{at}", "caught": bool(new_crit or new_g),
                     "located": (sh, at) in (cs - base_c), "findings": new_crit, "graders_failed": new_g,
                     "production_ready": v["modelcheck"]["production_ready"]})
    return {"clean_passes": clean["passed"] and not clean["findings"], "clean_findings": len(clean["findings"]),
            "clean_ids": sorted({f["id"] for f in clean["findings"]}), "rows": rows}


def synthetic_builds() -> dict:
    """Offline builds on the synthetic fixtures: {"model3": (wb, meta), "lbo": ..., "merger": ..., "comps": ...}."""
    from . import comps, lbo, merger
    from tests.test_comps import fixture
    from tests.test_model3 import synthetic_companyfacts
    mk = {"price": 25.0, "as_of": "2024-12-31", "source": "synthetic test fixture"}
    s = stm.build(synthetic_companyfacts(), "TEST")
    s2 = stm.build(synthetic_companyfacts(), "TWO")
    tgt, peers, markets = fixture()
    return {"model3": model3.build_workbook(s), "lbo": lbo.build_workbook(s, market=mk),
            "merger": merger.build_workbook(s, s2, acq_market=mk, tgt_market=mk),
            "comps": comps.build_workbook(tgt, peers, markets=markets, as_of="2025-03-03")}


def audit_all(builds: dict | None = None) -> dict:
    """Every planted-error audit: ten three-statement plants plus nine LBO / merger / comps plants.
    Returns {"models": [{"model", "planted", "caught", "located", "clean_passes", "rows"}], "totals": {...}, "ok": bool}."""
    builds = builds or synthetic_builds()
    models = []
    a = audit(*builds["model3"])
    models.append({"model": "model3", "planted": a["planted"], "caught": a["caught"], "located": a["located"],
                   "locatable": sum(1 for r in a["rows"] if r["located"] is not None),
                   "clean_passes": a["clean_passes"], "clean_ids": [], "rows": a["rows"]})
    for name in ("lbo", "merger", "comps"):
        r = audit_new(*builds[name], name)
        models.append({"model": name, "planted": len(r["rows"]), "caught": sum(x["caught"] for x in r["rows"]),
                       "located": sum(1 for x in r["rows"] if x["located"]), "locatable": len(r["rows"]), "clean_passes": r["clean_passes"],
                       "clean_ids": r["clean_ids"], "rows": r["rows"]})
    new = [m for m in models if m["model"] != "model3"]
    planted_new, caught_new = sum(m["planted"] for m in new), sum(m["caught"] for m in new)
    located_new = sum(m["located"] for m in new)
    base = models[0]
    tot = {"three_statement": f"{base['caught']}/{base['planted']}", "new": f"{caught_new}/{planted_new}",
           "planted": base["planted"] + planted_new, "caught": base["caught"] + caught_new,
           "located": base["located"] + located_new, "new_planted": planted_new, "new_caught": caught_new, "new_located": located_new,
           "locatable": base["locatable"] + planted_new,
           "located_pct": round(100.0 * (base["located"] + located_new) / max(base["locatable"] + planted_new, 1), 1),
           "new_located_pct": round(100.0 * located_new / max(planted_new, 1), 1),
           "clean_pass": all(m["clean_passes"] for m in models)}
    tot["ok"] = (base["caught"] == base["planted"] == 10 and planted_new >= 9 and caught_new == planted_new
                 and tot["new_located_pct"] >= 90.0 and tot["located_pct"] >= 90.0)
    return {"models": models, "totals": tot, "ok": tot["ok"]}


# =========================================================================== S4.6: OM-Bench 10
DEFAULT_10 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "KO", "PG", "HD", "CAT"]
SUBSTITUTES = ["JNJ", "PEP", "CSCO", "ORCL"]
LBO_TICKERS = ["KO", "HD", "CAT"]
MERGER_PAIRS = [("PG", "KO"), ("HD", "CAT")]
COMPS_SET = ("KO", ["PEP", "PG", "MDLZ", "CL"])
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "out" / "s4" / "bench"
OFFLINE_MARKET = {"price": 25.0, "as_of": "2024-12-31", "source": "synthetic test fixture (offline bench)"}


def _live_loader():
    """ticker -> companyfacts through the cached SEC client (SEC_USER_AGENT must be set; data/raw is never committed)."""
    from .sec import SecClient
    ua = os.environ.get("SEC_USER_AGENT", "")
    if not ua:
        raise RuntimeError("set SEC_USER_AGENT to run the live bench (or use --offline)")
    sec = SecClient(ua, ROOT / "data" / "raw" / "sec")
    by = {str(r["ticker"]).upper(): int(r["cik"]) for r in sec.tickers()}

    def load(t: str):
        cik = by.get(t.upper())
        return sec.companyfacts(cik) if cik else None
    return load


def _offline_loader():
    from tests.test_model3 import synthetic_companyfacts

    def load(t: str):
        return synthetic_companyfacts()
    return load


def _evaluate(label: str, kind: str, data: bytes, circ0: bytes | None, secs: float, out_dir: Path, *, libreoffice: bool, extra=None) -> dict:
    from . import recalc
    g = modelcheck.grade(data)
    v = validate_xlsx.validate(data, require_sources=True)
    c = recalc.compare(circ0 or data, engines=None if libreoffice else ("cached", "om"))
    avail = [n for n, i in c["engines"].items() if i["available"]]
    (out_dir / f"{label}.xlsx").write_bytes(data)
    row = {"label": label, "kind": kind, "supported": True, "seconds": round(secs, 2), "formulas": v["stats"]["formulas"], "score": g["score"],
           "production_ready": g["production_ready"], "graders_failed": [r["id"] for r in g["graders"] if r["passed"] is False],
           "validate_passed": v["passed"], "validate_critical": v["stats"]["critical"], "validate_warnings": v["stats"]["warnings"],
           "validate_ids": sorted({f["id"] for f in v["findings"] if f["severity"] == "critical"}),
           "agree": c["agree"], "compared_cells": c["compared_cells"], "divergences": len(c["divergences"]),
           "divergence_examples": [d["cell"] for d in c["divergences"][:5]],
           "engines": avail, "engines_unavailable": {n: i["reason"] for n, i in c["engines"].items() if not i["available"]},
           "three_engine": c["agree"] and len([e for e in avail if e != "cached"]) >= 2 and c["compared_cells"] > 0}
    row.update(extra or {})
    return row


def run_s4(tickers=DEFAULT_10, out_dir: Path | str = DEFAULT_OUT, *, libreoffice: bool = True, offline: bool = False, loader=None,
           deals: bool = True) -> dict:
    """OM-Bench 10: model3 for each ticker, LBO for KO/HD/CAT, mergers PG+KO and HD+CAT, comps KO vs PEP/PG/MDLZ/CL; each graded,
    validated (require_sources) and compared across engines (circularity off), with build seconds and formula counts."""
    from . import comps, lbo, market, merger
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    load = loader or (_offline_loader() if offline else _live_loader())
    cache: dict = {}
    notes: list[str] = []

    def cf(t):
        if t not in cache:
            try:
                cache[t] = load(t)
            except Exception as e:  # noqa: BLE001  (network / parse failures are recorded, not fatal)
                cache[t] = None
                notes.append(f"{t}: companyfacts unavailable ({type(e).__name__}: {e})")
        return cache[t]

    def stmts(t):
        c = cf(t)
        return stm.build(c, t) if c else None

    def mkt(t):
        return dict(OFFLINE_MARKET) if offline else market.resolve(t, cf(t))

    res = {"date": date.today().isoformat(), "offline": offline, "libreoffice": libreoffice, "universe": list(tickers), "substitutions": [],
           "notes": notes, "models": [], "audit": None}
    subs = [t for t in SUBSTITUTES if t not in tickers]
    builds: dict = {}
    for t in list(tickers):
        cur, tried = t, []
        while cur is not None:
            t0 = time.time()
            try:
                s = stmts(cur)
                if s is None:
                    raise model3.UnsupportedCompany("no SEC data for this ticker")
                wb, meta = model3.build_workbook(s)
                data = wb.to_bytes()
                secs = time.time() - t0
                w0, _ = model3.build_workbook(s, circ=0)
                break
            except model3.UnsupportedCompany as e:
                tried.append(f"{cur}: {e}")
                nxt = subs.pop(0) if subs else None
                if nxt:
                    res["substitutions"].append({"from": cur, "to": nxt, "reason": str(e)})
                cur = nxt
        if cur is None:
            res["models"].append({"label": f"{t} three-statement model", "kind": "model3", "supported": False, "reason": "; ".join(tried)})
            continue
        res["models"].append(_evaluate(f"{cur} three-statement model", "model3", data, w0.to_bytes(), secs, out_dir, libreoffice=libreoffice,
                                       extra={"ticker": cur, "years": meta["years"], "converged": meta["converged"]}))
        builds.setdefault("model3", (wb, meta))
    if deals:
        def deal(label, kind, fn, extra=None):
            t0 = time.time()
            try:
                wb, meta, circ0 = fn()
                data = wb.to_bytes()
                secs = time.time() - t0
            except Exception as e:  # noqa: BLE001
                res["models"].append({"label": label, "kind": kind, "supported": False, "reason": f"{type(e).__name__}: {e}"})
                return
            res["models"].append(_evaluate(label, kind, data, circ0, secs, out_dir, libreoffice=libreoffice,
                                           extra={"converged": meta.get("converged"), **(extra or {})}))
            builds.setdefault(kind, (wb, meta))

        for t in LBO_TICKERS:
            def f(t=t):
                s, m = stmts(t), mkt(t)
                if s is None or m is None:
                    raise RuntimeError("no statements or market data")
                wb, meta = lbo.build_workbook(s, market=m)
                return wb, meta, lbo.build_workbook(s, market=m, circ=0)[0].to_bytes()
            deal(f"{t} LBO", "lbo", f, {"ticker": t})
        for a, b in MERGER_PAIRS:
            def f(a=a, b=b):
                sa, sb, ma, mb = stmts(a), stmts(b), mkt(a), mkt(b)
                if None in (sa, sb, ma, mb):
                    raise RuntimeError("no statements or market data")
                wb, meta = merger.build_workbook(sa, sb, acq_market=ma, tgt_market=mb)
                return wb, meta, None
            deal(f"{a}+{b} merger", "merger", f, {"ticker": f"{a}+{b}"})

        def f():
            tg, peers = COMPS_SET
            mk = {t: mkt(t) for t in [tg, *peers]}
            if any(cf(t) is None or mk[t] is None for t in mk):
                raise RuntimeError("no companyfacts or market data for the comps set")
            wb, meta = comps.build_workbook((tg, cf(tg)), [(p, cf(p)) for p in peers], markets=mk)
            return wb, meta, None
        deal(f"{COMPS_SET[0]} trading comps", "comps", f, {"ticker": COMPS_SET[0]})
    if all(k in builds for k in ("model3", "lbo", "merger", "comps")):
        res["audit"] = audit_all(builds)
    else:
        res["audit"] = audit_all(synthetic_builds())
        res["audit"]["source"] = "synthetic fixtures (a live build was missing)"
    (out_dir / "results.json").write_text(json.dumps(res, indent=2, default=str))
    (out_dir / "report.md").write_text(report_s4(res))
    return res


def report_s4(res: dict) -> str:
    L = [f"# OM-Bench 10: Excel engine ({res['date']}{', offline synthetic fixtures' if res.get('offline') else ''})", "",
         "Every workbook is built by code, graded by `om.modelcheck`, validated by `om.validate_xlsx` (with `require_sources`) and "
         "recalculated by the other engines with circularity off. Seconds are build wall-clock.", ""]
    if res["substitutions"]:
        L += ["Substitutions: " + "; ".join(f"{s['from']} -> {s['to']} ({s['reason']})" for s in res["substitutions"]), ""]
    L += ["| Workbook | Score | Critical pass | Validate | Three-engine agree | Cells compared | Formulas | Seconds |", "|---|---|---|---|---|---|---|---|"]
    for m in res["models"]:
        if not m.get("supported", True):
            L.append(f"| {m['label']} | n/a | n/a | n/a | n/a | | | not built: {m['reason']} |")
            continue
        L.append(f"| {m['label']} | {m['score']} | {'yes' if m['production_ready'] else 'NO'} | "
                 f"{'pass' if m['validate_passed'] else 'FAIL ' + ','.join(m['validate_ids'])} | "
                 f"{'yes' if m['three_engine'] else ('NO' if not m['agree'] else 'partial: ' + '+'.join(m['engines']))} | "
                 f"{m['compared_cells']:,} | {m['formulas']:,} | {m['seconds']} |")
    a = res.get("audit")
    if a:
        t = a["totals"]
        L += ["", "## Planted-error audit", "",
              f"Three-statement {t['three_statement']}; LBO / merger / comps {t['new']}; located {t['located']}/{t['locatable']} cell-level plants ({t['located_pct']}%). "
              f"Clean models raise no findings: **{'yes' if t['clean_pass'] else 'NO'}**.", "",
              "| Model | Planted error | Cell | Caught | Located | Findings / graders |", "|---|---|---|---|---|---|"]
        for m in a["models"]:
            for r in m["rows"]:
                hits = ", ".join(r.get("findings", []) + r.get("graders_failed", [])) if "findings" in r else ", ".join(r.get("graders_failed", []))
                L.append(f"| {m['model']} | {r['error']} | {r.get('cell', '')} | {'yes' if r['caught'] else 'NO'} | "
                         f"{'n/a' if r['located'] is None else ('yes' if r['located'] else 'no')} | {hits} |")
    for n in res.get("notes", []):
        L.append(f"\n- {n}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m om.bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s4 = sub.add_parser("s4", help="OM-Bench 10 plus the planted-error audit")
    s4.add_argument("--offline", action="store_true", help="synthetic fixtures, no network")
    s4.add_argument("--out", default=str(DEFAULT_OUT))
    s4.add_argument("--no-libreoffice", action="store_true")
    s4.add_argument("tickers", nargs="*")
    a = ap.parse_args(argv)
    res = run_s4(a.tickers or DEFAULT_10, a.out, libreoffice=not a.no_libreoffice, offline=a.offline)
    print(report_s4(res))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
