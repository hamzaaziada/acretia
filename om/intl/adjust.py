"""Analyst adjustment recipes for international statements (S8.6a).

Every recipe is `fn(values, **params) -> {"adjusted": dict, "flags": list[str], "explain": str}` and is registered in
`RECIPES` under the id the standards KB uses. `values` is keyed like om.statements.LINES plus the `x.` keys
(reporting-currency millions). Expenses stored as positive numbers where LINES has sign -1 (cogs, sga, tax, capex);
`x.` operating costs are positive costs; `x.fx_gain_loss`, `x.other_income`, `x.share_of_associates` are signed
P&L effects (positive = gain). `x.changes_in_inventories` is a signed P&L effect (increase in stock = positive).
A recipe never mutates its input and never invents a number: a missing input gives None plus a `missing:` flag.
"""
from __future__ import annotations

from ..statements import LINES
from .fx import kind_of

OPEX_BY_NATURE = ("x.raw_materials", "x.employee_costs", "x.depreciation", "x.amortisation", "x.other_opex",
                  "x.selling_expenses", "x.admin_expenses")


def _v(values, key, default=None):
    x = values.get(key)
    return default if x is None else x


def _need(values, keys, flags):
    miss = [k for k in keys if values.get(k) is None]
    flags.extend(f"missing:{k}" for k in miss)
    return not miss


def _out(adjusted, flags, explain):
    return {"adjusted": adjusted, "flags": flags, "explain": explain}


def _ebitda(values, flags=None):
    if values.get("ebitda") is not None:
        return values["ebitda"]
    ebit = values.get("ebit")
    da = values.get("da")
    if da is None and (values.get("x.depreciation") is not None or values.get("x.amortisation") is not None):
        da = _v(values, "x.depreciation", 0.0) + _v(values, "x.amortisation", 0.0)
    if ebit is None or da is None:
        if flags is not None:
            flags.append("missing:ebitda")
        return None
    return ebit + da


def by_nature_ebit(values, other_income_operating=True, include_inventory_change=True):
    """EBIT = revenue - sum of operating expenses by nature (+ other operating income)."""
    flags = ["computed_by_nature"]
    if values.get("revenue") is None:
        return _out({"ebit": None}, flags + ["missing:revenue"], "No revenue, so by-nature EBIT cannot be computed.")
    parts = [k for k in OPEX_BY_NATURE if values.get(k) is not None]
    if not parts:
        flags.append("no_opex_components")
    ebit = values["revenue"] - sum(values[k] for k in parts)
    used = list(parts)
    if include_inventory_change and values.get("x.changes_in_inventories") is not None:
        ebit += values["x.changes_in_inventories"]
        used.append("x.changes_in_inventories")
    if other_income_operating and values.get("x.other_income") is not None:
        ebit += values["x.other_income"]
        used.append("x.other_income")
    dep = _v(values, "x.depreciation", 0.0) + _v(values, "x.amortisation", 0.0)
    return _out({"ebit": ebit, "ebitda": ebit + dep, "components": used, "basis_flags": {"ebit": "computed_by_nature"}},
                flags, "The report shows costs by nature, so EBIT is revenue less each operating cost line"
                       + (" plus other operating income" if other_income_operating and "x.other_income" in used else "") + ".")


def ifrs16_to_pre16_ebitda(values, lease_payments=None):
    """Pre-IFRS 16 view: lease cost sits in EBITDA again. Proxy = right-of-use depreciation + lease interest."""
    flags: list[str] = []
    e = _ebitda(values, flags)
    if lease_payments is not None:
        cost, flags = lease_payments, flags + ["ifrs16_pre16_lease_payments"]
    else:
        if not _need(values, ["x.rou_depreciation", "x.lease_interest"], flags) or e is None:
            return _out({"ebitda_pre16": None}, flags, "Lease cost inputs are missing, so no pre-IFRS 16 EBITDA is shown.")
        cost, flags = values["x.rou_depreciation"] + values["x.lease_interest"], flags + ["ifrs16_pre16_proxy"]
    if e is None:
        return _out({"ebitda_pre16": None}, flags, "No EBITDA to adjust.")
    adj = {"ebitda_pre16": e - cost, "lease_cost": cost}
    if values.get("ebit") is not None and values.get("x.rou_depreciation") is not None:
        adj["ebit_pre16"] = values["ebit"] - (cost - values["x.rou_depreciation"])
    return _out(adj, flags, "Lease cost goes back into operating cost: EBITDA less right-of-use depreciation and lease interest "
                            "(or less actual lease payments when given).")


def lease_adjusted_net_debt(values, include_leases=True, include_sti=False):
    """Net debt = borrowings (+ lease liabilities when include_leases) - cash (- short-term investments if asked)."""
    flags: list[str] = []
    debt = _v(values, "debt_current", 0.0) + _v(values, "debt_noncurrent", 0.0)
    leases = _v(values, "x.lease_liabilities_current", 0.0) + _v(values, "x.lease_liabilities_noncurrent", 0.0)
    if not _need(values, ["cash"], flags):
        return _out({"net_debt": None}, flags, "No cash figure, so net debt is not computed.")
    cash = values["cash"] + (_v(values, "sti", 0.0) if include_sti else 0.0)
    ex = debt - cash
    flags.append("leases_included" if include_leases else "leases_excluded")
    return _out({"net_debt": ex + (leases if include_leases else 0.0), "net_debt_ex_leases": ex, "lease_liabilities": leases},
                flags, "Net debt is borrowings less cash, with lease liabilities added only when the toggle is on.")


def capitalise_operating_leases(values, operating_lease_liability=None, operating_lease_cost=None, discount_rate=0.05):
    """US GAAP (ASC 842) operating leases restated as IFRS 16-like: cost splits into depreciation + interest."""
    flags = ["asc842_to_ifrs16_view"]
    liab = operating_lease_liability if operating_lease_liability is not None else values.get("operating_lease_liability")
    cost = operating_lease_cost if operating_lease_cost is not None else values.get("operating_lease_cost")
    if liab is None or cost is None:
        return _out({}, flags + ["missing:operating_lease_inputs"], "Operating lease liability and cost are needed.")
    interest = liab * discount_rate
    adj = {"lease_interest": interest, "lease_depreciation": cost - interest, "lease_debt_added": liab}
    e = _ebitda(values)
    if e is not None:
        adj["ebitda"] = e + cost
    if values.get("ebit") is not None:
        adj["ebit"] = values["ebit"] + interest
    if values.get("cash") is not None:
        adj["net_debt"] = _v(values, "debt_current", 0.0) + _v(values, "debt_noncurrent", 0.0) + liab - values["cash"]
    return _out(adj, flags, "The single operating lease cost is split into interest on the liability and depreciation, "
                            "and the liability joins debt, which is how IFRS 16 reports it.")


def zakat_as_tax(values, zakat_included_in_tax=False):
    """Effective rate with zakat treated as a tax-like charge, shown separately."""
    flags = ["zakat_in_tax_rate"]
    if not _need(values, ["pretax", "tax"], flags):
        return _out({}, flags, "Pre-tax profit and tax are needed.")
    zakat = _v(values, "x.zakat", 0.0)
    total = values["tax"] if zakat_included_in_tax else values["tax"] + zakat
    pt = values["pretax"]
    adj = {"zakat": zakat, "total_tax_and_zakat": total}
    if pt > 0:
        adj["effective_rate_incl_zakat"] = total / pt
        adj["effective_rate_ex_zakat"] = (values["tax"] - (zakat if zakat_included_in_tax else 0.0)) / pt
    else:
        adj["effective_rate_incl_zakat"] = adj["effective_rate_ex_zakat"] = None
        flags.append("pretax_not_positive")
    return _out(adj, flags, "Zakat is a levy on profit or net assets, so it is shown on its own line and counted with income "
                            "tax in the effective rate.")


MONETARY = {"cash", "sti", "ar", "ap", "debt_current", "debt_noncurrent", "x.lease_liabilities_current",
            "x.lease_liabilities_noncurrent", "x.eosb", "diluted_shares", "eps_diluted", "x.eps_basic",
            "current_assets", "current_liabilities"}


def ias29_restate(values, cpi_from=None, cpi_to=None, restate_keys=None):
    """IAS 29 hyperinflation: scale non-monetary figures by the index ratio cpi_to / cpi_from."""
    flags = ["ias29_restated"]
    if not cpi_from or not cpi_to or cpi_from <= 0:
        return _out(dict(values), flags + ["missing:cpi"], "Both price index values are needed.")
    f = cpi_to / cpi_from
    keys = restate_keys if restate_keys is not None else [k for k in values if k not in MONETARY]
    adj = {k: (v * f if k in keys and v is not None else v) for k, v in values.items()}
    flags.append("monetary_items_not_restated")
    return _out(adj, flags, f"Non-monetary figures are multiplied by the price index ratio {f:.4f}; monetary items already sit "
                            "in year-end money and are left alone.")


def fx_translate_period_end_average(values, rate_end=None, rate_avg=None):
    """Translate with rates as reporting-currency units per 1 target unit: stocks / rate_end, flows / rate_avg."""
    flags = ["fx_translated"]
    if not rate_end or not rate_avg:
        return _out(dict(values), flags + ["missing:rate"], "Both a period-end and an average rate are needed.")
    adj = {}
    for k, v in values.items():
        kind = kind_of(k)
        if v is None or kind is None:
            adj[k] = v
        elif kind == "u":
            adj[k] = v
        else:
            adj[k] = v / (rate_end if kind == "i" else rate_avg)
    return _out(adj, flags, "Balance-sheet lines use the period-end rate and income and cash-flow lines the period average; "
                            "share counts are unchanged and EPS follows the average.")


def devaluation_fx_loss_normalise(values, fx_in_ebit=True, tax_rate=0.0):
    """Take the FX gain or loss out of EBIT and recurring earnings (it is a devaluation effect, not operations)."""
    flags = ["devaluation_fx_item_excluded"]
    if values.get("x.fx_gain_loss") is None:
        return _out({}, flags + ["missing:x.fx_gain_loss"], "No FX gain or loss line to normalise.")
    fx = values["x.fx_gain_loss"]
    adj = {"fx_gain_loss_below_ebit": fx}
    if values.get("ebit") is not None:
        adj["ebit"] = values["ebit"] - fx if fx_in_ebit else values["ebit"]
    if values.get("net_income") is not None:
        adj["recurring_net_income"] = values["net_income"] - fx * (1 - tax_rate)
    if values.get("pretax") is not None:
        adj["recurring_pretax"] = values["pretax"] - fx
    return _out(adj, flags, "A devaluation shows up as a large FX gain or loss; it is moved below EBIT and removed from "
                            "recurring earnings.")


def eosb_as_debt_like(values, tax_rate=0.0, net_debt=None):
    """End-of-service benefit liability treated as debt-like (net of tax shield if tax_rate is given)."""
    flags = ["eosb_debt_like"]
    if values.get("x.eosb") is None:
        return _out({}, flags + ["missing:x.eosb"], "No end-of-service liability reported.")
    add = values["x.eosb"] * (1 - tax_rate)
    nd = net_debt
    if nd is None and values.get("cash") is not None:
        nd = _v(values, "debt_current", 0.0) + _v(values, "debt_noncurrent", 0.0) - values["cash"]
    adj = {"eosb_debt_like": add}
    if nd is not None:
        adj["net_debt_incl_eosb"] = nd + add
    return _out(adj, flags, "Staff end-of-service benefits are owed to employees like debt, so they are added to net debt.")


def dev_cost_expense(values, dev_amortisation=0.0):
    """Expense capitalised development spend instead of capitalising it."""
    flags = ["dev_cost_expensed"]
    cap = values.get("x.capitalised_dev")
    if cap is None:
        return _out({}, flags + ["missing:x.capitalised_dev"], "No capitalised development cost reported.")
    adj = {}
    if values.get("ebit") is not None:
        adj["ebit"] = values["ebit"] - cap + dev_amortisation
    e = _ebitda(values)
    if e is not None:
        adj["ebitda"] = e - cap
    if values.get("capex") is not None:
        adj["capex"] = values["capex"] - cap
    return _out(adj, flags, "Capitalised development spend is charged to the period, lowering EBITDA and capex by the same amount.")


def _strip(values, amount_key, amount, tax_rate, flag, text):
    flags = [flag]
    if amount is None:
        return _out({}, flags + [f"missing:{amount_key}"], f"No {amount_key} given.")
    adj = {}
    for k in ("ebit", "pretax"):
        if values.get(k) is not None:
            adj[k] = values[k] - amount
    if values.get("net_income") is not None:
        adj["net_income"] = values["net_income"] - amount * (1 - tax_rate)
    return _out(adj, flags, text)


def revaluation_reverse(values, revaluation_gain=None, tax_rate=0.0):
    """Remove fair-value revaluation gains (e.g. investment property) from profit."""
    g = revaluation_gain if revaluation_gain is not None else values.get("revaluation_gain")
    return _strip(values, "revaluation_gain", g, tax_rate, "revaluation_reversed",
                  "Unrealised revaluation gains are non-cash and non-recurring, so they come out of profit.")


def impairment_reversal_strip(values, impairment_reversal=None, tax_rate=0.0):
    """Remove impairment reversals (IAS 36 allows them, US GAAP does not) from profit."""
    g = impairment_reversal if impairment_reversal is not None else values.get("impairment_reversal")
    return _strip(values, "impairment_reversal", g, tax_rate, "impairment_reversal_stripped",
                  "Impairment reversals are one-off gains, so they come out of profit.")


def capitalised_interest_expense(values, capitalised_interest=None):
    """Treat interest capitalised into assets as an expense of the period."""
    flags = ["capitalised_interest_expensed"]
    ci = capitalised_interest if capitalised_interest is not None else values.get("capitalised_interest")
    if ci is None:
        return _out({}, flags + ["missing:capitalised_interest"], "No capitalised interest given.")
    adj = {}
    if values.get("interest_expense") is not None:
        adj["interest_expense"] = values["interest_expense"] + ci
    if values.get("pretax") is not None:
        adj["pretax"] = values["pretax"] - ci
    if values.get("capex") is not None:
        adj["capex"] = values["capex"] - ci
    return _out(adj, flags, "Interest capitalised into assets is added to interest expense and taken out of capex.")


def lifo_to_fifo(values, lifo_reserve=None, prior_lifo_reserve=0.0, tax_rate=0.0):
    """Add the LIFO reserve to inventory and restate cost of sales by the change in the reserve."""
    flags = ["lifo_to_fifo"]
    if lifo_reserve is None:
        return _out({}, flags + ["missing:lifo_reserve"], "The LIFO reserve is needed.")
    d = lifo_reserve - prior_lifo_reserve
    adj = {"lifo_reserve_change": d}
    if values.get("inventory") is not None:
        adj["inventory"] = values["inventory"] + lifo_reserve
    if values.get("cogs") is not None:
        adj["cogs"] = values["cogs"] - d
    for k in ("ebit", "pretax"):
        if values.get(k) is not None:
            adj[k] = values[k] + d
    if values.get("net_income") is not None:
        adj["net_income"] = values["net_income"] + d * (1 - tax_rate)
    return _out(adj, flags, "FIFO inventory is LIFO inventory plus the reserve, and cost of sales falls by the reserve's increase.")


def gov_grant_gross_up(values, netted_against="cogs"):
    """Show a government grant gross: cost line back to gross, grant as its own income line, EBIT unchanged."""
    flags = ["gov_grant_gross_up"]
    g = values.get("x.gov_grants")
    if g is None:
        return _out({}, flags + ["missing:x.gov_grants"], "No government grant reported.")
    adj = {"x.gov_grants_income": g}
    if values.get(netted_against) is not None:
        adj[netted_against] = values[netted_against] + g
    if values.get("ebit") is not None:
        adj["ebit"] = values["ebit"]
        adj["ebit_ex_grants"] = values["ebit"] - g
    return _out(adj, flags, "A grant netted against costs is shown gross, so costs are not understated and the grant can be excluded "
                            "from underlying EBIT.")


def associates_share_strip(values, in_ebit=False):
    """Remove the share of associates' profit from operating or net profit."""
    flags = ["associates_share_stripped"]
    s = values.get("x.share_of_associates")
    if s is None:
        return _out({}, flags + ["missing:x.share_of_associates"], "No share of associates' results reported.")
    adj = {"share_of_associates": s}
    if values.get("ebit") is not None:
        adj["ebit"] = values["ebit"] - s if in_ebit else values["ebit"]
    if values.get("net_income") is not None:
        adj["net_income_ex_associates"] = values["net_income"] - s
    return _out(adj, flags, "Associates' profit is not controlled operating profit, so it is removed before multiples are applied.")


def revenue_principal_agent_net(values, agent_amount=None):
    """Restate gross billings of an agent to the net commission: revenue and cost of sales both fall."""
    flags = ["principal_agent_net"]
    if agent_amount is None or values.get("revenue") is None:
        return _out({}, flags + ["missing:agent_amount"], "The gross amount billed as agent is needed.")
    rev = values["revenue"] - agent_amount
    adj = {"revenue": rev}
    if values.get("cogs") is not None:
        adj["cogs"] = values["cogs"] - agent_amount
    if values.get("ebit") is not None and rev:
        adj["ebit"] = values["ebit"]
        adj["ebit_margin"] = values["ebit"] / rev
    return _out(adj, flags, "Pass-through billings come out of revenue and cost of sales alike, so profit is unchanged and margins rise.")


def eas_to_ifrs_map(values, fx_loss_capitalised=0.0, rou_asset=0.0, lease_liability=0.0, adjustments=None):
    """Map Egyptian Accounting Standards figures to an IFRS view: undo capitalised FX losses, add leases, apply listed deltas."""
    flags = ["eas_to_ifrs_mapped"]
    adj = dict(values)
    if fx_loss_capitalised:
        for k in ("ppe", "equity_parent"):
            if adj.get(k) is not None:
                adj[k] = adj[k] - fx_loss_capitalised
        flags.append("eas_fx_capitalisation_reversed")
    if rou_asset or lease_liability:
        if adj.get("assets") is not None:
            adj["assets"] += rou_asset
        if adj.get("liabilities") is not None:
            adj["liabilities"] += lease_liability
        adj["x.rou_assets"], adj["x.lease_liabilities_noncurrent"] = rou_asset, lease_liability
        flags.append("eas_leases_added")
    for k, dlt in (adjustments or {}).items():
        adj[k] = (adj.get(k) or 0.0) + dlt
        flags.append(f"eas_adjusted:{k}")
    return _out(adj, flags, "EAS figures are moved towards IFRS by reversing capitalised FX losses, adding leases and any listed deltas.")


RECIPES = {f.__name__: f for f in (
    ifrs16_to_pre16_ebitda, lease_adjusted_net_debt, capitalise_operating_leases, zakat_as_tax, by_nature_ebit,
    ias29_restate, fx_translate_period_end_average, devaluation_fx_loss_normalise, eosb_as_debt_like, dev_cost_expense,
    revaluation_reverse, impairment_reversal_strip, capitalised_interest_expense, lifo_to_fifo, gov_grant_gross_up,
    associates_share_strip, revenue_principal_agent_net, eas_to_ifrs_map)}
