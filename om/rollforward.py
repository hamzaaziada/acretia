"""Earnings roll-forward for om.model3 workbooks (S4.4).

A company reports a new fiscal year.  ``roll_forward(old_xlsx, new_statements)`` reads the user's current Assumptions from
the old workbook (by row label, so the blue cells they edited survive), rebuilds the model on the new statements so the
newly reported year becomes an actual (blue, sourced) column and the forecast window moves one year, carries the user's
assumptions over by fiscal year, extends the last value to the new final year, and writes a ``Roll-forward`` sheet that
sets the actuals against the prior forecast.  Deterministic: no model is called.
"""
from __future__ import annotations

from . import formula as fx
from . import model3
from .statements import Statements
from .wbgraph import _is_actual, _periods, row_label
from .xlsx import col_letter, quote_sheet, read, ref

SCENARIO_KEYS = ("growth", "gm")            # carried as (base, upside, downside) triples
VARIANCE = (("Revenue", "IS", "rev", "num0"), ("EBITDA", "IS", "ebitda", "num0"), ("Net income", "IS", "ni", "num0"),
            ("Diluted EPS", "IS", "eps", "usd2"), ("Free cash flow", "CF", "fcf", "num0"))
SHEET_NAME = "Roll-forward"


def _align(old_book, sheet: str, ref_wb, ref_rows: dict) -> dict:
    """Map each model row key to its row in the old workbook by walking the row labels in order (labels such as
    'Base' repeat, so the order disambiguates them)."""
    grid = ref_wb[sheet].cells
    labels = {k: (grid[(r, 1)].value if (r, 1) in grid else None) for k, r in ref_rows.items()}
    old_rows = sorted({r for r, _ in old_book.sheets.get(sheet, {})})
    out, cursor = {}, 0
    for k, r in sorted(ref_rows.items(), key=lambda kv: kv[1]):
        want = labels.get(k)
        if not isinstance(want, str):
            continue
        for i in range(cursor, len(old_rows)):
            if row_label(old_book, sheet, old_rows[i]) == want.strip():
                out[k] = old_rows[i]
                cursor = i + 1
                break
    return out


def _num(book, sheet: str, r: int, c: int):
    cell = book.sheets.get(sheet, {}).get((r, c))
    v = cell.value if cell else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pct(actual, prior):
    return None if prior in (None, 0) or actual is None else actual / prior - 1


def roll_forward(old_xlsx: bytes, new_statements: Statements, *, old_meta: dict | None = None) -> tuple[bytes, dict]:
    old = read(old_xlsx)
    if "Assumptions" not in old.sheets or "IS" not in old.sheets:
        raise ValueError("not an om.model3 workbook: it needs Assumptions and IS sheets")
    s = new_statements
    ref_wb, ref_meta = model3.build_workbook(s)               # layout and default drivers for the new statements
    F, H = ref_meta["forecast_years"], len(s.years)
    new_last = s.years[-1].year
    new_years = [new_last + 1 + j for j in range(F)]

    per = _periods(old, "Assumptions")
    if not per:
        raise ValueError("Assumptions has no FY period header row; cannot map columns by fiscal year")
    actual_years = [y for y, c in per.items() if _is_actual(old, "Assumptions", c, y)]
    old_last = max(actual_years) if actual_years else min(per) - 1
    if new_last <= old_last:
        raise ValueError(f"new statements end in FY{new_last}, not after the workbook's last actual FY{old_last}; nothing to roll forward")

    # ------------------------------------------------ the user's current assumptions, by row label and fiscal year
    arows_ref = ref_meta["rows"]["Assumptions"]
    arows = ({k: int(v) for k, v in old_meta["rows"]["Assumptions"].items()} if old_meta and old_meta.get("rows", {}).get("Assumptions")
             else _align(old, "Assumptions", ref_wb, arows_ref))
    warnings = [f"Assumptions row {k!r} not found in the old workbook; the default for the new statements is used"
                for k in arows_ref if k not in arows and k not in ("scenario_note", "circ_note") and
                (k in ref_meta["defaults"] or k[:-2] in SCENARIO_KEYS)]
    defaults = ref_meta["defaults"]
    carried, extended, dropped, assumptions = [], [], [], {}

    def series(key: str, default: list) -> list:
        row = arows.get(key)
        vals, last = [], None
        for j, y in enumerate(new_years):
            v = _num(old, "Assumptions", row, per[y]) if row and y in per else None
            if v is not None:
                carried.append({"key": key, "label": row_label(old, "Assumptions", row), "year": y, "value": v,
                                "from": f"Assumptions!{ref(row, per[y])}", "to_column": col_letter(3 + H + j)})
                last = v
            elif last is not None:
                extended.append({"key": key, "year": y, "value": last, "note": f"no prior value for FY{y}E; FY{y - 1}E value extended"})
            else:
                last = default[j]
                v = None
            vals.append(v if v is not None else last)
        return vals

    for key, dflt in defaults.items():
        if key in SCENARIO_KEYS:
            assumptions[key] = tuple(series(f"{key}_{sfx}", list(dflt[i])) for i, sfx in enumerate("bud"))
        else:
            assumptions[key] = series(key, list(dflt))
    input_keys = [f"{k}_{x}" for k in defaults if k in SCENARIO_KEYS for x in "bud"] + [k for k in defaults if k not in SCENARIO_KEYS]
    for key in input_keys:
        row = arows.get(key)
        for y, c in sorted(per.items()):
            v = _num(old, "Assumptions", row, c) if row and old_last < y <= new_last else None
            if v is not None:
                dropped.append({"key": key, "label": row_label(old, "Assumptions", row), "year": y, "value": v,
                                "from": f"Assumptions!{ref(row, c)}",
                                "reason": f"FY{y} is now an actual: the assumption is replaced by the reported figure"})
    sc = _num(old, "Assumptions", arows.get("scenario_note", 9), 3)
    cc = _num(old, "Assumptions", arows.get("circ_note", 10), 3)
    scenario = int(sc) if sc in (1.0, 2.0, 3.0) else 1
    circ = int(cc) if cc in (0.0, 1.0) else 1

    # ------------------------------------------------ rebuild on the new statements
    wb, meta = model3.build_workbook(s, assumptions=assumptions, circ=circ, scenario=scenario)
    rows = meta["rows"]
    act_col = 3 + H - 1                                            # the newly reported year
    irows = {sh: (old_meta["rows"][sh] if old_meta and old_meta.get("rows", {}).get(sh) else _align(old, sh, ref_wb, rows[sh]))
             for sh in ("IS", "CF")}

    # ------------------------------------------------ variance table: actual vs the prior forecast
    prior_per = {sh: _periods(old, sh) for sh in ("IS", "CF")}
    variance, sheet_rows = [], []
    sh = wb.sheet(SHEET_NAME, tab="7F7F7F")
    sh.set("A2", f"Roll-forward: FY{new_last} actual against the prior forecast", kind="title")
    sh.set("A3", "Prior forecast values are blue inputs taken from the previous workbook (hover for the source cell); actuals link to the statements.", kind="note")
    for c, h in enumerate(("Metric", "", "Prior forecast", "Actual", "Variance", "% variance", "Prior workbook cell"), 1):
        sh.set((5, c), h, kind="header", align="right" if c in (3, 4, 5, 6) else None)
    sh.set((6, 1), "Fiscal year", kind="note")
    sh.set((6, 3), f"FY{new_last}E", kind="note", align="right")
    sh.set((6, 4), f"FY{new_last}A", kind="note", align="right")
    sh.width("A", 30)
    sh.width("B", 7)
    for c in range(3, 7):
        sh.width(c, 14)
    sh.width("G", 26)
    sh.freeze = (6, 2)
    r = 7
    for label, sheet, key, fmt in VARIANCE:
        orow, ocol = irows[sheet].get(key), prior_per[sheet].get(new_last)
        prior = _num(old, sheet, orow, ocol) if orow and ocol else None
        new_row = rows[sheet][key]
        actual_ref = f"{quote_sheet(sheet)}!{ref(new_row, act_col)}"
        if prior is None:
            sh.set((r, 1), label)
            sh.set((r, 7), f"no FY{new_last} forecast in the prior workbook", kind="note")
            r += 1
            continue
        src = f"{sheet}!{ref(orow, ocol)}"
        sh.set((r, 1), label, bold=label in ("Revenue", "Net income"))
        sh.set((r, 3), prior, kind="input", fmt=fmt,
               comment=f"Prior forecast for FY{new_last}E ({label}) from the previous workbook: {src}.")
        sh.set((r, 4), f"={actual_ref}", fmt=fmt)
        sh.set((r, 5), f"=D{r}-C{r}", fmt=fmt)
        sh.set((r, 6), f"=IF(C{r}=0,0,D{r}/C{r}-1)", fmt="pct")
        sh.set((r, 7), src, kind="note")
        sheet_rows.append((label, sheet, key, r, prior, src, actual_ref))
        r += 1
    order = [x.name for x in wb.sheets]
    wb.sheets.sort(key=lambda x: order.index(x.name) if x.name != SHEET_NAME else order.index("Filings") - 0.5)
    eng = fx.calculate_workbook(wb)
    for label, sheet, key, rr, prior, src, actual_ref in sheet_rows:
        actual = eng.values.get((sheet, rows[sheet][key], act_col))
        variance.append({"metric": label, "prior_cell": src, "prior_forecast": prior,
                         "actual_cell": actual_ref, "actual": actual, "diff": None if actual is None else actual - prior,
                         "pct_diff": _pct(actual, prior), "cell": f"{quote_sheet(SHEET_NAME)}!C{rr}"})
    meta["converged"], meta["iterations"] = eng.converged, eng.iterations
    report = {
        "new_actual": {"year": new_last, "label": f"FY{new_last}A", "column": col_letter(act_col), "filing": s.filings[-1]},
        "previous_last_actual": old_last,
        "forecast_years": new_years,
        "variance": variance,
        "assumptions_carried": carried,
        "assumptions_extended": extended,
        "assumptions_dropped": dropped,
        "scenario": scenario, "circ": circ,
        "warnings": warnings,
        "meta": meta,
    }
    return wb.to_bytes(), report
