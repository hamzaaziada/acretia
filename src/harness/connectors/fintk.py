"""Ratios over our statements dict (S2.5).

FinanceToolkit (MIT, ledger: adopt) was used for IDEAS ONLY. Its data layer expects an FMP API key (or Yahoo) and
we hold no keys and never call FMP, so the ratio definitions below are implemented over the statements produced by
`financial_statements()` (edgartools / om.statements, SEC XBRL). FinanceToolkit is not installed or imported.

Input: {"years": [...], "data": {line_key: [value per year, $m]}} (a dict from sec.statements_to_dict) or an
om.statements.Statements object. Missing inputs give None, never a guess. Pure functions, no I/O."""
from __future__ import annotations

DEFAULT_TAX = 0.21   # statutory fallback when pretax income is non-positive


def _as_dict(st) -> dict:
    if isinstance(st, dict):
        return st
    from .sec import statements_to_dict
    return statements_to_dict(st)


def _col(d: dict, key: str, n: int) -> list:
    v = d["data"].get(key)
    return list(v) if v is not None else [None] * n


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _add(*xs):
    vals = [x for x in xs if x is not None]
    return sum(vals) if vals else None


def _growth(xs):
    return [None] + [(_div(xs[i] - xs[i - 1], abs(xs[i - 1])) if xs[i] is not None and xs[i - 1] not in (None, 0) else None)
                     for i in range(1, len(xs))]


def _avg(xs):
    return [xs[0]] + [(_div(_add(xs[i], xs[i - 1]), 2) if xs[i] is not None and xs[i - 1] is not None else None)
                      for i in range(1, len(xs))]


def ratios(st) -> dict:
    """-> {"years": [...], "metrics": {name: [per-year float|None]}}"""
    d = _as_dict(st)
    n = len(d["years"])
    g = lambda k: _col(d, k, n)  # noqa: E731
    rev, cogs, ebit, da = g("revenue"), g("cogs"), g("ebit"), g("da")
    ni, pretax, tax = g("net_income"), g("pretax"), g("tax")
    ie, cash, sti = g("interest_expense"), g("cash"), g("sti")
    debt_c, debt_n = g("debt_current"), g("debt_noncurrent")
    eq, assets = g("equity_total"), g("assets")
    ca, cl, gp, eps = g("current_assets"), g("current_liabilities"), g("gross_profit"), g("eps_diluted")
    gp = [x if x is not None else (None if r is None or c is None else r - c) for x, r, c in zip(gp, rev, cogs)]
    ebitda = [None if e is None else e + (x or 0) if x is not None else None for e, x in zip(ebit, da)]
    debt = [_add(a, b) for a, b in zip(debt_c, debt_n)]
    liquid = [_add(a, b) for a, b in zip(cash, sti)]
    net_debt = [None if dd is None or lq is None else dd - lq for dd, lq in zip(debt, liquid)]
    taxrate = []
    for t, p in zip(tax, pretax):
        r = _div(t, p) if p is not None and p > 0 else None
        taxrate.append(min(max(r, 0.0), 0.5) if r is not None else DEFAULT_TAX)
    nopat = [None if e is None else e * (1 - r) for e, r in zip(ebit, taxrate)]
    invested = [None if e is None or dd is None or lq is None else e + dd - lq for e, dd, lq in zip(eq, debt, liquid)]
    m = {
        "revenue_growth": _growth(rev), "ebit_growth": _growth(ebit), "net_income_growth": _growth(ni),
        "eps_growth": _growth(eps), "ebitda_growth": _growth(ebitda),
        "gross_margin": [_div(a, b) for a, b in zip(gp, rev)],
        "ebit_margin": [_div(a, b) for a, b in zip(ebit, rev)],
        "ebitda": ebitda,
        "ebitda_margin": [_div(a, b) for a, b in zip(ebitda, rev)],
        "net_margin": [_div(a, b) for a, b in zip(ni, rev)],
        "tax_rate": taxrate, "nopat": nopat, "invested_capital": invested, "total_debt": debt, "net_debt": net_debt,
        "roic": [_div(a, b) for a, b in zip(nopat, _avg(invested))],
        "roe": [_div(a, b) for a, b in zip(ni, _avg(eq))],
        "roa": [_div(a, b) for a, b in zip(ni, _avg(assets))],
        "debt_to_equity": [_div(a, b) for a, b in zip(debt, eq)],
        "net_debt_to_ebitda": [_div(a, b) if b is not None and b > 0 else None for a, b in zip(net_debt, ebitda)],
        "interest_coverage": [_div(a, abs(b)) if b else None for a, b in zip(ebit, ie)],
        "current_ratio": [_div(a, b) for a, b in zip(ca, cl)],
    }
    return {"years": list(d["years"]), "metrics": m}


def ev_ebitda_inputs(st, price: float, diluted_shares_m: float | None = None, year_index: int = -1) -> dict:
    """EV/EBITDA building blocks for one year. `price` is supplied by the caller (no market data fetched here).
    diluted_shares_m defaults to the statement's diluted share count ($m units: millions of shares)."""
    d = _as_dict(st)
    r = ratios(d)["metrics"]
    i = year_index
    shares = diluted_shares_m if diluted_shares_m is not None else _col(d, "diluted_shares", len(d["years"]))[i]
    mcap = None if shares is None or price is None else price * shares
    nd, ebitda = r["net_debt"][i], r["ebitda"][i]
    ev = None if mcap is None or nd is None else mcap + nd
    return {"year": d["years"][i], "price": price, "diluted_shares_m": shares, "market_cap_m": mcap, "net_debt_m": nd,
            "enterprise_value_m": ev, "ebitda_m": ebitda,
            "ev_ebitda": _div(ev, ebitda) if ebitda is not None and ebitda > 0 else None}
