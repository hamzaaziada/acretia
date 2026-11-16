"""Metrics engine: one row of public-comps fields per company, plus field-level provenance.

Money fields are in millions. Each money field exists in reporting currency (suffix _lcu) and USD.
Multiples are computed in reporting currency, so they are FX-neutral.
Non-meaningful rule: multiple is null (and listed in `nm_fields`) if denominator <= 0 or result > 250.
Forward (NTM / FY+1 / calendar-year estimate) fields are not produced yet: they need the estimates layer.
"""
from __future__ import annotations

from datetime import date, timedelta

from .concepts import FINANCIAL_SIC
from .facts import Company, Value
from .fx import FX
from .prices import Quote

NM_CAP = 250.0
M = 1e6


def _add(*vals: Value, basis: str) -> Value:
    if any(v.val is None for v in vals):
        return Value(None, "missing")
    return Value(sum(v.val for v in vals), basis, [s for v in vals for s in v.sources], vals[0].end)


def _first(*vals: Value) -> Value:
    for v in vals:
        if v.val is not None:
            return v
    return Value(None, "missing")


def _ratio(num, den, pct=False):
    if num is None or den is None or den <= 0:
        return None
    return num / den * (100 if pct else 1)


def _growth(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def is_financial(sic: int | None) -> bool:
    return bool(sic) and any(lo <= sic <= hi for lo, hi in FINANCIAL_SIC)


def compute(cf: dict, sub: dict | None, quote: Quote | None, fx: FX | None,
            as_of: date | None = None) -> tuple[dict, dict]:
    c = Company(cf, as_of=as_of)
    sub = sub or {}
    prov: dict[str, dict] = {}
    row: dict = {}
    nm: list[str] = []

    sic = int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None
    fin = is_financial(sic)
    forms = {f for f in (sub.get("filings", {}).get("recent", {}).get("form") or [])}
    foreign = bool(forms & {"20-F", "40-F"}) and "10-K" not in forms
    row.update({
        "cik": c.cik, "name": c.name or sub.get("name"),
        "ticker": (sub.get("tickers") or [None])[0], "exchange": (sub.get("exchanges") or [None])[0],
        "sic": sic, "sic_description": sub.get("sicDescription"),
        "fiscal_year_end_mmdd": sub.get("fiscalYearEnd"), "state_of_incorporation": sub.get("stateOfIncorporation"),
        "reporting_currency": c.ccy, "is_financial_format": fin, "foreign_filer": foreign,
        "as_of": (as_of or date.today()).isoformat(),
    })

    def put(name: str, v: Value, scale: float = M):
        row[name] = None if v.val is None else v.val / scale
        if v.val is not None:
            prov[name] = v.prov()

    # ---------------------------------------------------------------- flows
    ltm_end = c.latest_end()
    row["ltm_end"] = ltm_end.isoformat() if ltm_end else None
    fy_rev = c.fy("revenue")
    row["last_fy_end"] = fy_rev.end.isoformat() if fy_rev.end else None

    def flow(metric: str) -> dict[str, Value]:
        return {"ltm": c.ltm(metric), "fy": c.fy(metric), "fy_minus1": c.fy(metric, -1),
                "ltm_prior": c.ltm_prior_year(metric)}

    rev, cogs, gp_t, ebit, ni = flow("revenue"), flow("cost_of_revenue"), flow("gross_profit"), flow("ebit"), flow("net_income")
    da = flow("d_and_a")
    dep, amo = flow("depreciation"), flow("amortization")
    cfo, capex = flow("cfo"), flow("capex")
    sm, ga, sga, rd, opex = flow("sm"), flow("ga"), flow("sga"), flow("rd"), flow("opex")

    out: dict[str, dict[str, Value]] = {"revenue": rev, "ebit": ebit, "net_income": ni, "cfo": cfo, "capex": capex}
    out["gross_profit"] = {p: _first(gp_t[p], _add(rev[p], Value(-cogs[p].val if cogs[p].val is not None else None,
                                                                    cogs[p].basis, cogs[p].sources, cogs[p].end),
                                                   basis="revenue-cost_of_revenue")) for p in rev}
    out["d_and_a"] = {p: _first(da[p], _add(dep[p], amo[p], basis="depreciation+amortization")) for p in rev}
    out["ebitda"] = {p: _add(ebit[p], out["d_and_a"][p], basis="ebit+d_and_a") for p in rev}
    out["fcf"] = {p: (_add(cfo[p], Value(-capex[p].val, capex[p].basis, capex[p].sources, capex[p].end), basis="cfo-capex")
                      if capex[p].val is not None else Value(None, "missing")) for p in rev}

    usd_avg = {}
    for p in ("ltm", "fy", "fy_minus1"):
        v = rev[p]
        if c.ccy != "USD" and fx and v.end:
            usd_avg[p] = fx.avg_per_usd(c.ccy, v.end - timedelta(days=364), v.end)
        else:
            usd_avg[p] = 1.0

    for metric in ("revenue", "gross_profit", "ebitda", "ebit", "net_income", "fcf", "cfo", "capex", "d_and_a"):
        for p in ("ltm", "fy", "fy_minus1"):
            if metric in ("cfo", "capex", "d_and_a") and p == "fy_minus1":
                continue
            v = out[metric][p]
            put(f"{metric}_{p}_lcu", v)
            rate = usd_avg.get(p)
            row[f"{metric}_{p}"] = None if v.val is None or not rate else v.val / rate / M

    # growth
    for metric in ("revenue", "ebitda", "ebit", "gross_profit", "net_income", "fcf"):
        if metric == "ebitda":
            prior_ltm = _add(ebit["ltm_prior"], out["d_and_a"]["ltm_prior"], basis="ebit+d_and_a")
        elif metric == "gross_profit":
            prior_ltm = gp_t["ltm_prior"]
        elif metric == "fcf":
            prior_ltm = Value(None)
        else:
            prior_ltm = out[metric]["ltm_prior"] if metric in out else Value(None)
        row[f"{metric}_growth_ltm_yoy"] = _growth(out[metric]["ltm"].val, prior_ltm.val)
        row[f"{metric}_growth_fy"] = _growth(out[metric]["fy"].val, out[metric]["fy_minus1"].val)
        if prior_ltm.val is not None:
            prov[f"{metric}_ltm_prior_year_lcu"] = prior_ltm.prov()

    # margins and expense ratios
    for p in ("ltm", "fy"):
        r = rev[p].val
        for metric, key in (("gross_profit", "gross"), ("ebitda", "ebitda"), ("ebit", "ebit"),
                            ("net_income", "net"), ("fcf", "fcf")):
            row[f"margin_{key}_{p}"] = _ratio(out[metric][p].val, r, pct=True) if r and r > 0 else None
        sga_v = sga[p].val
        row[f"expenses_revenue_pct_sm_{p}"] = _ratio(sm[p].val, r, True)
        row[f"expenses_revenue_pct_ga_{p}"] = _ratio(ga[p].val, r, True)
        row[f"expenses_revenue_pct_sga_{p}"] = _ratio(sga_v if sga_v is not None else
                                                      (sm[p].val + ga[p].val if sm[p].val is not None and ga[p].val is not None else None), r, True)
        row[f"expenses_revenue_pct_rd_{p}"] = _ratio(rd[p].val, r, True)
        opex_v = opex[p].val
        if opex_v is None and out["gross_profit"][p].val is not None and ebit[p].val is not None:
            opex_v = out["gross_profit"][p].val - ebit[p].val
        row[f"expenses_revenue_pct_opex_{p}"] = _ratio(opex_v, r, True)

    g = row.get("revenue_growth_ltm_yoy")
    m_ = row.get("margin_ebitda_ltm")
    row["rule_of_40_ltm_hist"] = g + m_ if g is not None and m_ is not None else None
    row["rule_of_x_ltm_hist"] = 2.5 * g + m_ if g is not None and m_ is not None else None
    eps = c.fy("eps_diluted")
    row["eps_diluted_fy"] = eps.val
    if eps.val is not None:
        prov["eps_diluted_fy"] = eps.prov()

    # ---------------------------------------------------------------- balance sheet / EV bridge
    bs = c.balance_date()
    row["balance_sheet_date"] = bs.isoformat() if bs else None
    inst = {k: c.instant(k, bs) for k in ("cash", "st_investments", "lt_debt_total", "lt_debt_noncurrent",
                                          "lt_debt_current", "st_borrowings", "commercial_paper", "finance_lease",
                                          "operating_lease", "preferred", "temp_equity", "minority_interest",
                                          "total_equity", "total_assets", "total_liabilities")}

    def z(v: Value) -> float:
        return v.val or 0.0

    lt = inst["lt_debt_total"] if inst["lt_debt_total"].val is not None else \
        _add(Value(z(inst["lt_debt_noncurrent"]), "lt_noncurrent", inst["lt_debt_noncurrent"].sources),
             Value(z(inst["lt_debt_current"]), "lt_current", inst["lt_debt_current"].sources), basis="noncurrent+current")
    debt_parts = [lt, inst["st_borrowings"], inst["commercial_paper"], inst["finance_lease"]]
    debt = Value(sum(z(v) for v in debt_parts), "lt_debt+st_borrowings+commercial_paper+finance_lease",
                 [s for v in debt_parts for s in v.sources], bs)
    cash = Value(z(inst["cash"]) + z(inst["st_investments"]), "cash+st_investments",
                 inst["cash"].sources + inst["st_investments"].sources, bs)
    pref = Value(z(inst["preferred"]) + z(inst["temp_equity"]), "preferred+temporary_equity",
                 inst["preferred"].sources + inst["temp_equity"].sources, bs)
    mi = Value(z(inst["minority_interest"]), "minority_interest", inst["minority_interest"].sources, bs)
    for name, v in (("ev_bridge_total_debt", debt), ("ev_bridge_cash", cash), ("ev_bridge_preferred_and_hybrid", pref),
                    ("ev_bridge_minority_interest", mi), ("lease_liabilities", inst["operating_lease"]),
                    ("total_equity", inst["total_equity"]), ("total_assets", inst["total_assets"])):
        put(f"{name}_lcu", v)
    a, l_, e = inst["total_assets"].val, inst["total_liabilities"].val, inst["total_equity"].val
    row["check_balance_sheet"] = None if None in (a, l_, e) or not a else abs(a - (l_ + e + z(mi) + z(inst["temp_equity"]))) / a < 0.005

    # ---------------------------------------------------------------- shares
    cover = c.instant("shares_out_cover")
    bs_sh = c.instant("shares_out_bs", bs) if bs else Value(None)
    dil = c.facts("diluted_shares")
    dil_latest = dil[max(dil, key=lambda k: k[1])] if dil else None
    if cover.val:
        shares, basis = cover, "cover_page"
    elif bs_sh.val:
        shares, basis = bs_sh, "balance_sheet"
    elif dil_latest:
        shares, basis = Value(dil_latest.val, "diluted_weighted_avg", [dil_latest], dil_latest.end), "diluted_weighted_avg"
    else:
        shares, basis = Value(None), None
    row["shares_out"] = shares.val
    row["shares_basis"] = basis
    row["shares_date"] = shares.end.isoformat() if shares.end else None
    if shares.val:
        prov["shares_out"] = shares.prov()
    ref = bs_sh.val or (dil_latest.val if dil_latest else None)
    row["check_shares"] = None if not (shares.val and ref) else 0.5 <= shares.val / ref <= 2.0

    # ---------------------------------------------------------------- market & multiples
    mc_lcu = None
    if quote and shares.val:
        to_lcu = 1.0
        if quote.currency != c.ccy:
            if not fx:
                to_lcu = None
            else:
                a_ = fx.per_usd(c.ccy, quote.on)
                b_ = fx.per_usd(quote.currency, quote.on)
                to_lcu = a_ / b_ if a_ and b_ else None
        if to_lcu:
            mc_lcu = quote.close / quote.ordinary_per_unit * shares.val * to_lcu
        row.update({"price": quote.close, "price_currency": quote.currency, "price_date": quote.on.isoformat(),
                    "price_source": quote.source,
                    "adr_ratio_unverified": foreign and quote.ordinary_per_unit == 1.0})
    ev_lcu = None
    if mc_lcu is not None:
        ev_lcu = mc_lcu if fin else mc_lcu + debt.val + pref.val + mi.val - cash.val
        row["market_cap_lcu"] = mc_lcu / M
        row["enterprise_value_lcu"] = ev_lcu / M
        row["ev_incl_leases_lcu"] = (ev_lcu + z(inst["operating_lease"])) / M
        rate = fx.per_usd(c.ccy, quote.on) if (fx and c.ccy != "USD") else 1.0
        row["market_cap"] = mc_lcu / rate / M if rate else None
        row["enterprise_value"] = ev_lcu / rate / M if rate else None
        prov["enterprise_value_lcu"] = {"basis": "market_cap" if fin else
                                        "market_cap+total_debt+preferred_and_hybrid+minority_interest-cash",
                                        "price": {"close": quote.close, "date": quote.on.isoformat(), "source": quote.source},
                                        "balance_sheet_date": row["balance_sheet_date"]}

    def multiple(name: str, num, den):
        if num is None or den is None:
            row[name] = None
            return
        if den <= 0 or num / den > NM_CAP or num / den < 0:
            row[name] = None
            nm.append(name)
            return
        row[name] = num / den

    for p in ("ltm", "fy"):
        multiple(f"ev_revenue_{p}", ev_lcu, out["revenue"][p].val)
        multiple(f"ev_gross_profit_{p}", ev_lcu, out["gross_profit"][p].val)
        multiple(f"ev_ebitda_{p}", None if fin else ev_lcu, out["ebitda"][p].val)
        multiple(f"ev_ebit_{p}", None if fin else ev_lcu, out["ebit"][p].val)
        multiple(f"ev_fcf_{p}", None if fin else ev_lcu, out["fcf"][p].val)
        multiple(f"price_earnings_{p}", mc_lcu, out["net_income"][p].val)
    multiple("price_to_book", mc_lcu, inst["total_equity"].val)
    multiple("price_to_sales", mc_lcu, out["revenue"]["ltm"].val)
    multiple("price_to_free_cash_flow", mc_lcu, out["fcf"]["ltm"].val)
    multiple("price_to_cash_flow", mc_lcu, out["cfo"]["ltm"].val)
    rg = row.get("revenue_growth_ltm_yoy")
    multiple("ev_revenue_growth_adj_ltm_yoy", row.get("ev_revenue_ltm"), rg if rg and rg > 0 else None)
    eg = row.get("ebitda_growth_ltm_yoy")
    multiple("ev_ebitda_growth_adj_ltm_yoy", row.get("ev_ebitda_ltm"), eg if eg and eg > 0 else None)
    row["nm_fields"] = ",".join(nm)
    if fx and c.ccy != "USD":
        row["fx_source"] = fx.source
    return row, prov
