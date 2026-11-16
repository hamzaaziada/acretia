"""Calendarisation: restate non-December fiscal years to a calendar year (or any target year-end month).

A fiscal year ending d months after the target year-end contributes (12-d)/12 of the calendar year; the fiscal year
before it contributes d/12. June to December: 6/12 FY(t) + 6/12 FY(t+1). March to December: 3/12 FY(t) + 9/12 FY(t+1).
Stocks (balance sheet) are not weighted: the nearest period end is used.
"""
from __future__ import annotations

import calendar
from datetime import date


def _idx(d: date) -> int:
    return d.year * 12 + d.month - 1


def _from_idx(i: int) -> date:
    y, m = divmod(i, 12)
    m += 1
    return date(y, m, calendar.monthrange(y, m)[1])


def weights(fy_end_month: int, target_month: int = 12) -> dict:
    """Weights for the fiscal years that overlap one calendar year, with an explanation."""
    d = (fy_end_month - target_month) % 12
    after, before = (12 - d) / 12, d / 12
    if d == 0:
        text = "The fiscal year already ends in the target month: no weighting."
    else:
        text = (f"Fiscal year ends in month {fy_end_month}, {d} months after the target year-end (month {target_month}): "
                f"calendar year = {d}/12 x the fiscal year ending before the target date + {12 - d}/12 x the one ending after it.")
    return {"months_after_target": d, "fy_before_target": before, "fy_after_target": after, "explain": text}


def calendarise(values_by_fy_end: dict, target_month: int = 12, kind: str = "flow") -> dict:
    """Map {fiscal year end: value} to {target year end: value}.

    kind="flow" (income statement, cash flow): day-less month weights as above; needs both neighbouring fiscal years.
    kind="stock" (balance sheet): the nearest period end (ties go to the earlier one), no weighting, within 6 months.
    """
    if kind not in ("flow", "stock"):
        raise ValueError("kind must be 'flow' or 'stock'")
    vals = {_idx(d): v for d, v in values_by_fy_end.items() if v is not None}
    out: dict[date, float] = {}
    if not vals:
        return out
    if kind == "stock":
        lo, hi = min(vals), max(vals)
        for t in range(lo - 6, hi + 7):
            if t % 12 != target_month - 1:
                continue
            best = min(((abs(f - t), f) for f in vals if abs(f - t) <= 6), default=None)
            if best:
                out[_from_idx(t)] = vals[best[1]]
        return dict(sorted(out.items()))
    fy_month = next(iter(vals)) % 12 + 1
    if any(f % 12 + 1 != fy_month for f in vals):
        raise ValueError("calendarise needs a constant fiscal year-end month")
    dd = (fy_month - target_month) % 12
    for f in sorted(vals):
        t = f - dd  # target year end whose "after" fiscal year ends at f
        if dd == 0:
            out[_from_idx(t)] = vals[f]
        elif (f - 12) in vals:
            out[_from_idx(t)] = (dd / 12) * vals[f - 12] + ((12 - dd) / 12) * vals[f]
    return dict(sorted(out.items()))
