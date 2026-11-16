"""Merger (accretion / dilution) model, written by code from two companies' SEC filings.

Sheets:
  Cover          deal summary, accretion / dilution by year, master check, contents
  Assumptions    market prices, offer premium, consideration mix, financing rates, tax, synergies and phasing,
                 integration costs, fees, intangible write-up, projection drivers, sensitivity steps (all blue inputs)
  Purchase price offer price, equity purchase price, net debt assumed, enterprise value paid, implied multiples
  Sources & Uses stock issued, cash used, new debt, fees; new shares issued
  PPA            purchase price allocation: write-ups, deferred tax liability, goodwill
  Pro forma      standalone projections, deal adjustments (pre- and after-tax), pro forma EPS, accretion / dilution
  Breakeven      pre-tax synergies needed to break even each year; the maximum year-1 EPS-neutral premium (closed form)
  Sensitivity    live closed-form grids (premium x % stock; synergies x premium); no data tables
  Checks         sources = uses, mix = 100%, goodwill >= 0, breakeven reproduces zero accretion, master check
  Filings        both companies' historicals as filed, blue, sourced and linked

Rules: no typed number inside a formula (structural constants only), one formula per row across the forecast
years, the LLM never types a number here. Accretion is on a reported basis (integration costs included, fees
financed and capitalised, no circularity).
"""
from __future__ import annotations

from . import statements as stm
from .model3 import _avg, _clamp, _sd
from .xlsx import BLUE, GREEN, GREY, NAVY, Workbook, col_letter, quote_sheet, ref

F = 3                       # forecast years
C0 = 3                      # first value column (C)
BASE = C0                   # last actual year column on Pro forma
Y = [C0 + 1 + i for i in range(F)]
FIRST = 8
LT_GROWTH = 0.03


# --------------------------------------------------------------------------- defaults
def _need(s: stm.Statements, who: str) -> None:
    if len(s.years) < 1:
        raise ValueError(f"{who} ({s.ticker}): no fiscal years in the statements")
    last = len(s.years) - 1
    for k in ("revenue", "net_income", "diluted_shares"):
        if s.get(k, last) is None:
            raise ValueError(f"{who} ({s.ticker}): the latest filing doesn't tag {s.label(k)}")
    if not s.get("diluted_shares", last) or s.get("diluted_shares", last) <= 0:
        raise ValueError(f"{who} ({s.ticker}): diluted shares must be positive")


def _proj_defaults(s: stm.Statements) -> tuple[list, list]:
    H = len(s.years)
    rev = [s.get("revenue", i) for i in range(H)]
    ni = s.get("net_income", H - 1)
    growth = [_sd(rev[i], rev[i - 1]) - 1 if i and _sd(rev[i], rev[i - 1]) else None for i in range(H)]
    g0 = _clamp(_avg(growth), -0.10, 0.25, 0.05)
    gs = [g0 + (LT_GROWTH - g0) * t / F for t in range(F)]
    margin = _clamp(_sd(ni, rev[-1]), -0.5, 0.6, 0.1)
    return gs, [margin] * F


def defaults(acq: stm.Statements, tgt: stm.Statements, acq_market: dict, tgt_market: dict) -> dict:
    """Driver defaults from history and the market inputs. Everything here is overridable via `assumptions`."""
    la, lt = len(acq.years) - 1, len(tgt.years) - 1
    ag, am = _proj_defaults(acq)
    tg, tm = _proj_defaults(tgt)
    pretax = [acq.get("pretax", i) for i in range(la + 1)]
    tax = [acq.get("tax", i) for i in range(la + 1)]
    tax_rate = _clamp(_avg([_sd(tax[i], pretax[i]) for i in range(la + 1) if (pretax[i] or 0) > 0]), 0.0, 0.35, 0.21)
    premium, pct_stock, fee_pct = 0.30, 0.50, 0.01
    equity = float(tgt_market["price"]) * (1 + premium) * (tgt.get("diluted_shares", lt) or 0)
    cash_cons = (1 - pct_stock) * equity + fee_pct * equity
    acq_cash = (acq.get("cash", la) or 0) + (acq.get("sti", la) or 0)
    cash_used = round(max(0.0, min(0.5 * acq_cash, cash_cons)), 1)
    syn = round(0.02 * (tgt.get("revenue", lt) or 0), 1)
    return {
        "acq_growth": ag, "acq_margin": am, "tgt_growth": tg, "tgt_margin": tm,
        "premium": premium, "pct_stock": pct_stock, "pct_cash": 1 - pct_stock, "fee_pct": fee_pct,
        "rate_debt": 0.06, "rate_cash": 0.03, "cash_used": cash_used, "tax": tax_rate,
        "syn_runrate": syn, "syn_phase": [0.25, 0.75, 1.0], "integ": [round(0.5 * syn, 1), round(0.25 * syn, 1), 0.0],
        "wu_pct": 0.30, "life": 10.0,
        "prem_step": 0.05, "stock_step": 0.25, "syn_step": max(round(syn / 2, 1), 1.0),
        "tol": 0.01, "tol_pct": 0.0001, "tol_eps": 0.0001,
    }


# --------------------------------------------------------------------------- builder
class _M:
    def __init__(self, acq, tgt, acq_market, tgt_market, d):
        self.acq, self.tgt = acq, tgt
        self.am, self.tm = acq_market, tgt_market
        self.d = d
        self.wb = Workbook(iterate=False)
        self.rows: dict[str, dict[str, int]] = {}
        self.ha, self.ht = len(acq.years), len(tgt.years)
        self.fil: dict[str, dict[str, int]] = {"A": {}, "T": {}}

    # -- addresses
    def x(self, sheet: str, key: str, col: int = C0, absolute: bool = True) -> str:
        return f"{quote_sheet(sheet)}!{ref(self.rows[sheet][key], col, absolute, absolute)}"

    def loc(self, sheet: str, key: str, col: int = C0) -> str:
        return ref(self.rows[sheet][key], col)

    def filing(self, co: str, key: str) -> str:
        n = self.ha if co == "A" else self.ht
        return f"Filings!{ref(self.fil[co][key], C0 + n - 1, True, True)}"

    def fy(self, k: int) -> str:
        return f"FY{self.acq.years[-1].year + 1 + k}E"


def _layout(sh, title: str, sub: str, m: _M, header: str = "$ in millions", years: bool = True, cols: int = 6) -> None:
    sh.set("A2", title, kind="title")
    sh.set("A3", sub, kind="note")
    sh.set((5, 1), header, kind="header")
    sh.set((5, 2), "", kind="header")
    for c in range(C0, cols + 1):
        sh.set((5, c), "", kind="header")
    if years:
        sh.set((5, BASE), f"FY{m.acq.years[-1].year}A", kind="header", align="right")
        for k, c in enumerate(Y):
            sh.set((5, c), m.fy(k), kind="header", align="right")
        sh.set((6, 1), "Fiscal year (acquirer)", kind="note")
    sh.width("A", 46)
    sh.width("B", 8)
    for c in range(C0, cols + 1):
        sh.width(c, 12.5)
    sh.freeze = (6, 2)


class _Rows:
    """Row allocator for one sheet: section / line, remembers each key's row."""

    def __init__(self, m: _M, name: str):
        self.m, self.name, self.r = m, name, FIRST
        m.rows[name] = {}

    def key(self, k: str) -> int:
        r = self.r
        self.m.rows[self.name][k] = r
        self.r += 1
        return r

    def section(self, sh, title: str, cols: int = 6) -> None:
        sh.set((self.r, 1), title, bold=True, color=NAVY, bottom=True)
        for c in range(2, cols + 1):
            sh.set((self.r, c), "", bottom=True)
        self.r += 1

    def gap(self, n: int = 1) -> None:
        self.r += n


def _filings(m: _M, sh) -> None:
    sh.set("A2", "Figures as filed with the SEC", kind="title")
    sh.set("A3", "Blue = as reported (XBRL), $m. Hover for the concept, period and accession; click to open the filing.", kind="note")
    sh.width("A", 46)
    sh.width("B", 8)
    sh.freeze = (6, 2)
    sh.set((5, 1), "Line", kind="header")
    sh.set((5, 2), "", kind="header")
    r = FIRST - 2
    for co, s, who in (("A", m.acq, "Acquirer"), ("T", m.tgt, "Target")):
        n = len(s.years)
        sh.set((r, 1), f"{who}: {s.name} ({s.ticker})", bold=True, color=NAVY, bottom=True)
        for c in range(2, C0 + max(m.ha, m.ht)):
            sh.set((r, c), "", bottom=True)
        r += 1
        sh.set((r, 1), "Fiscal year ending", kind="note")
        for p in range(n):
            sh.set((r, C0 + p), s.years[p].isoformat(), kind="note", align="right")
            sh.width(C0 + p, 12.5)
        r += 1
        for k, (stmt, kind, sign, label, chain) in stm.LINES.items():
            fmt = "usd2" if k == "eps_diluted" else ("num1" if k == "diluted_shares" else "num0")
            sh.set((r, 1), f"{stmt} · {label}")
            m.fil[co][k] = r
            for p in range(n):
                it = s.data[k][p]
                if it.value is None:
                    continue
                sh.set((r, C0 + p), float(it.value), kind="hist", fmt=fmt, comment=it.source() or None,
                       link=s.filings[p]["url"] or None)
            r += 1
        sh.set((r, 1), "Source filing", kind="note")
        for p in range(n):
            f = s.filings[p]
            sh.set((r, C0 + p), f"{f['form']} {f['accn']}", kind="note", align="right", link=f["url"] or None)
        r += 2
    m.rows["Filings"] = {f"{co}.{k}": v for co in ("A", "T") for k, v in m.fil[co].items()}


def _assumptions(m: _M, sh) -> None:
    d = m.d
    _layout(sh, "Assumptions", "Blue cells are inputs. Per-year inputs sit under the forecast years; everything else is in column C.", m)
    R = _Rows(m, "Assumptions")

    def scalar(key, label, v, fmt="pct", unit="", comment=None, text=False):
        r = R.key(key)
        sh.set((r, 1), label, indent=1)
        if unit:
            sh.set((r, 2), unit, kind="note")
        sh.set((r, C0), v if text else float(v), kind="input", fmt=None if text else fmt, comment=comment)

    def peryear(key, label, vals, fmt="pct", unit=""):
        r = R.key(key)
        sh.set((r, 1), label, indent=1)
        if unit:
            sh.set((r, 2), unit, kind="note")
        for k, c in enumerate(Y):
            sh.set((r, c), float(vals[k]), kind="input", fmt=fmt)

    R.section(sh, "Market data (caller supplied; never invented)")
    for pre, who, mk in (("acq", "Acquirer", m.am), ("tgt", "Target", m.tm)):
        scalar(f"{pre}_price", f"{who} share price", mk["price"], "usd2", "$", comment=f"Source: {mk.get('source', '')}; as of {mk.get('as_of', '')}")
        scalar(f"{pre}_asof", f"{who} price as of", str(mk.get("as_of", "")), text=True)
        scalar(f"{pre}_source", f"{who} price source", str(mk.get("source", "")), text=True)
    R.gap()
    R.section(sh, "Offer and consideration")
    scalar("premium", "Offer premium to current target price", d["premium"])
    scalar("pct_stock", "Consideration paid in acquirer stock", d["pct_stock"])
    scalar("pct_cash", "Consideration paid in cash", d["pct_cash"])
    scalar("fee_pct", "Transaction fees (% of equity purchase price)", d["fee_pct"])
    scalar("cash_used", "Acquirer balance-sheet cash used", d["cash_used"], "num1", "$m")
    R.gap()
    R.section(sh, "Financing and tax")
    scalar("rate_debt", "Interest rate on new acquisition debt", d["rate_debt"])
    scalar("rate_cash", "Interest income rate forgone on cash used", d["rate_cash"])
    scalar("tax", "Tax rate on deal adjustments", d["tax"])
    R.gap()
    R.section(sh, "Synergies and integration (per forecast year)")
    scalar("syn_rr", "Pre-tax synergies at run-rate", d["syn_runrate"], "num1", "$m")
    peryear("syn_phase", "Synergy phasing (% of run-rate realised)", d["syn_phase"])
    peryear("integ", "Integration costs (pre-tax)", d["integ"], "num1", "$m")
    R.gap()
    R.section(sh, "Purchase price allocation")
    scalar("wu_pct", "Intangible write-up (% of excess purchase price)", d["wu_pct"])
    scalar("life", "Useful life of written-up intangibles", d["life"], "num1", "years")
    R.gap()
    R.section(sh, "Standalone projection drivers (per forecast year)")
    peryear("acq_growth", "Acquirer revenue growth", d["acq_growth"])
    peryear("acq_margin", "Acquirer net margin", d["acq_margin"])
    peryear("tgt_growth", "Target revenue growth", d["tgt_growth"])
    peryear("tgt_margin", "Target net margin", d["tgt_margin"])
    R.gap()
    R.section(sh, "Sensitivity steps")
    scalar("prem_step", "Offer premium step", d["prem_step"])
    scalar("stock_step", "% stock step", d["stock_step"])
    scalar("syn_step", "Run-rate synergies step", d["syn_step"], "num1", "$m")
    sh.set((R.r + 1, 1), "Projections are simple and per company: revenue growth and net margin off the last actual year. "
           "Fiscal years are not calendarised.", kind="note")


def _purchase(m: _M, sh) -> None:
    _layout(sh, "Purchase price", "Offer price, equity purchase price, net debt assumed and the multiples paid.", m, years=False, cols=4)
    R = _Rows(m, "Purchase price")
    A = lambda k: m.x("Assumptions", k)
    rows = [
        ("tgt_price", "Target current share price", "$", "usd2", f"={A('tgt_price')}"),
        ("premium", "Offer premium", "%", "pct", f"={A('premium')}"),
        ("offer", "Offer price per share", "$", "usd2", None),
        ("tgt_sh", "Target diluted shares", "m", "num1", f"={m.filing('T', 'diluted_shares')}"),
        ("equity", "Equity purchase price", "$m", "num0", None),
        ("debt", "Plus: target debt assumed", "$m", "num0", f"={m.filing('T', 'debt_current')}+{m.filing('T', 'debt_noncurrent')}"),
        ("cash", "Less: target cash and short-term investments", "$m", "num0", f"=-({m.filing('T', 'cash')}+{m.filing('T', 'sti')})"),
        ("ev", "Enterprise value paid", "$m", "num0", None),
        ("ebitda", "Target EBITDA (last actual: operating income + D&A)", "$m", "num0", f"={m.filing('T', 'ebit')}+{m.filing('T', 'da')}"),
        ("ni", "Target net income (last actual)", "$m", "num0", f"={m.filing('T', 'net_income')}"),
        ("rev", "Target revenue (last actual)", "$m", "num0", f"={m.filing('T', 'revenue')}"),
        ("ev_ebitda", "Implied EV / EBITDA", "x", "x", None),
        ("ev_rev", "Implied EV / revenue", "x", "x", None),
        ("pe_paid", "Implied P/E paid (equity price / net income)", "x", "x", None),
        ("tgt_pe", "Target P/E at current price", "x", "x", None),
        ("acq_pe", "Acquirer P/E at current price", "x", "x", None),
    ]
    for key, label, unit, fmt, f in rows:
        r = R.key(key)
        sh.set((r, 1), label, bold=key in ("offer", "equity", "ev"), top=key in ("equity", "ev"))
        sh.set((r, 2), unit, kind="note")
        if key == "offer":
            f = f"={m.loc('Purchase price', 'tgt_price')}*(1+{m.loc('Purchase price', 'premium')})"
        elif key == "equity":
            f = f"={m.loc('Purchase price', 'offer')}*{m.loc('Purchase price', 'tgt_sh')}"
        elif key == "ev":
            f = f"=SUM({m.loc('Purchase price', 'equity')}:{m.loc('Purchase price', 'cash')})"
        elif key == "ev_ebitda":
            f = f"=IF({m.loc('Purchase price', 'ebitda')}>0,{m.loc('Purchase price', 'ev')}/{m.loc('Purchase price', 'ebitda')},0)"
        elif key == "ev_rev":
            f = f"=IF({m.loc('Purchase price', 'rev')}>0,{m.loc('Purchase price', 'ev')}/{m.loc('Purchase price', 'rev')},0)"
        elif key == "pe_paid":
            f = f"=IF({m.loc('Purchase price', 'ni')}>0,{m.loc('Purchase price', 'equity')}/{m.loc('Purchase price', 'ni')},0)"
        elif key == "tgt_pe":
            f = (f"=IF({m.loc('Purchase price', 'ni')}>0,{m.loc('Purchase price', 'tgt_price')}*{m.loc('Purchase price', 'tgt_sh')}"
                 f"/{m.loc('Purchase price', 'ni')},0)")
        elif key == "acq_pe":
            f = (f"=IF({m.filing('A', 'net_income')}>0,{A('acq_price')}*{m.filing('A', 'diluted_shares')}/{m.filing('A', 'net_income')},0)")
        sh.set((r, C0), f, fmt=fmt, bold=key in ("offer", "equity", "ev"), top=key in ("equity", "ev"))
    sh.set((R.r + 1, 1), "Net debt is from the latest actual balance sheet. Offer premium and prices are inputs on Assumptions.", kind="note")


def _sources_uses(m: _M, sh) -> None:
    _layout(sh, "Sources & Uses", "How the equity purchase price and fees are funded; shares issued to target holders.", m, years=False, cols=4)
    R = _Rows(m, "Sources & Uses")
    A = lambda k: m.x("Assumptions", k)
    P = lambda k: m.x("Purchase price", k)
    n = "Sources & Uses"
    L = lambda k: m.loc(n, k)

    def line(key, label, f, fmt="num0", unit="$m", bold=False, top=False):
        r = R.key(key)
        sh.set((r, 1), label, bold=bold, top=top, indent=0 if bold else 1)
        sh.set((r, 2), unit, kind="note", top=top)
        sh.set((r, C0), f, fmt=fmt, bold=bold, top=top)

    R.section(sh, "Uses", 4)
    line("u_equity", "Equity purchase price", f"={P('equity')}")
    line("u_fees", "Transaction fees", f"={A('fee_pct')}*{m.loc(n, 'u_equity')}")
    line("u_total", "Total uses", f"=SUM({L('u_equity')}:{L('u_fees')})", bold=True, top=True)
    R.gap()
    R.section(sh, "Sources", 4)
    line("s_stock", "Acquirer stock issued to target holders", f"={A('pct_stock')}*{L('u_equity')}")
    line("s_cash", "Acquirer balance-sheet cash", f"={A('cash_used')}")
    line("cash_cons", "Memo: cash consideration to target holders", f"={A('pct_cash')}*{L('u_equity')}")
    line("s_debt", "New acquisition debt (cash consideration + fees - cash used)", f"={L('cash_cons')}+{L('u_fees')}-{L('s_cash')}")
    line("s_total", "Total sources", f"={L('s_stock')}+{L('s_cash')}+{L('s_debt')}", bold=True, top=True)
    R.gap()
    R.section(sh, "Shares", 4)
    line("new_sh", "New acquirer shares issued", f"={L('s_stock')}/{A('acq_price')}", "num1", "m", bold=True)
    line("exch", "Exchange ratio (acquirer shares per target share, stock portion)", f"={L('new_sh')}/{P('tgt_sh')}", "num2" if False else "num2", "x")
    line("own", "Target holders' pro forma ownership", f"={L('new_sh')}/({m.filing('A', 'diluted_shares')}+{L('new_sh')})", "pct", "%")
    line("nd", "Memo: target net debt assumed (stays outstanding)", f"={P('debt')}+{P('cash')}")


def _ppa(m: _M, sh) -> None:
    _layout(sh, "Purchase price allocation", "Target book equity, intangible write-ups, deferred tax and goodwill. Existing goodwill is eliminated.", m,
            years=False, cols=4)
    R = _Rows(m, "PPA")
    A = lambda k: m.x("Assumptions", k)
    L = lambda k: m.loc("PPA", k)

    def line(key, label, f, fmt="num0", unit="$m", bold=False, top=False):
        r = R.key(key)
        sh.set((r, 1), label, bold=bold, top=top, indent=0 if bold else 1)
        sh.set((r, 2), unit, kind="note", top=top)
        sh.set((r, C0), f, fmt=fmt, bold=bold, top=top)

    line("price", "Equity purchase price", f"={m.x('Purchase price', 'equity')}", bold=True)
    line("book", "Target book equity", f"={m.filing('T', 'equity_parent')}")
    line("old_gw", "Less: existing goodwill (eliminated)", f"=-{m.filing('T', 'goodwill')}")
    line("tb", "Adjusted tangible book value", f"={L('book')}+{L('old_gw')}", top=True)
    line("excess", "Excess purchase price over adjusted book value", f"={L('price')}-{L('tb')}")
    line("wu", "Intangible write-up", f"={A('wu_pct')}*MAX(0,{L('excess')})")
    line("dtl", "Deferred tax liability on the write-up", f"={L('wu')}*{A('tax')}")
    line("net_id", "Net identifiable assets acquired (adjusted book + write-up - DTL)", f"={L('tb')}+{L('wu')}-{L('dtl')}", top=True)
    line("goodwill", "Goodwill created", f"={L('price')}-{L('net_id')}", bold=True, top=True)
    line("amort", "Annual amortisation of the write-up (pre-tax)", f"={L('wu')}/{A('life')}")
    line("gw_pct", "Goodwill as % of purchase price", f"=IF({L('price')}>0,{L('goodwill')}/{L('price')},0)", "pct", "%")


def _pro_forma(m: _M, sh) -> None:
    _layout(sh, "Pro forma earnings and accretion / dilution",
            "Standalone projections, deal adjustments and the pro forma EPS bridge. Reported basis: integration costs included.", m)
    n = "Pro forma"
    layout = [
        ("S", f"Acquirer standalone: {m.acq.name}"), "a_g", "a_rev", "a_m", "a_ni", "a_sh", "a_eps", ("G",),
        ("S", f"Target standalone: {m.tgt.name}"), "t_g", "t_rev", "t_m", "t_ni", ("G",),
        ("S", "Deal adjustments, pre-tax"), "syn", "integ", "newint", "forgone", "amort", "pre_total", ("G",),
        ("S", "Deal adjustments, after tax"), "at_syn", "at_integ", "at_newint", "at_forgone", "at_amort", "at_total", ("G",),
        ("S", "Pro forma combined"), "pf_ni", "pf_new", "pf_sh", "pf_eps", "sa_eps", "acc_d", "acc_p", "verdict",
    ]
    rows = m.rows[n] = {}
    r = FIRST
    for item in layout:
        if isinstance(item, str):
            rows[item] = r
        r += 1
    A = lambda k, c: f"Assumptions!{ref(m.rows['Assumptions'][k], c)}"
    As = lambda k: m.x("Assumptions", k)
    L = lambda k, c: ref(rows[k], c)
    tax = As("tax")

    def line(key, label, base=None, fc=None, fmt="num0", unit="$m", bold=False, top=False, italic=False):
        r = rows[key]
        sh.set((r, 1), label, bold=bold, top=top, italic=italic, indent=0 if bold or top else 1)
        sh.set((r, 2), unit, kind="note", top=top)
        if base is not None:
            sh.set((r, BASE), base, fmt=fmt, bold=bold, top=top, italic=italic)
        elif top:
            sh.set((r, BASE), "", top=True)
        if fc is not None:
            for c in Y:
                sh.set((r, c), fc(c), fmt=fmt, bold=bold, top=top, italic=italic)

    r = FIRST
    for item in layout:
        if isinstance(item, tuple) and item[0] == "S":
            sh.set((r, 1), item[1], bold=True, color=NAVY, bottom=True)
            for c in range(2, 7):
                sh.set((r, c), "", bottom=True)
        r += 1
    for co, pre, who in (("A", "a", "acq"), ("T", "t", "tgt")):
        line(f"{pre}_g", "Revenue growth", None, lambda c, who=who: f"={A(who + '_growth', c)}", "pct", "%", italic=True)
        line(f"{pre}_rev", "Revenue", f"={m.filing(co, 'revenue')}", lambda c, pre=pre: f"={L(pre + '_rev', c - 1)}*(1+{L(pre + '_g', c)})")
        line(f"{pre}_m", "Net margin", f"={L(pre + '_ni', BASE)}/{L(pre + '_rev', BASE)}", lambda c, who=who: f"={A(who + '_margin', c)}", "pct", "%", italic=True)
        line(f"{pre}_ni", "Net income", f"={m.filing(co, 'net_income')}", lambda c, pre=pre: f"={L(pre + '_rev', c)}*{L(pre + '_m', c)}", bold=True)
    line("a_sh", "Diluted shares (held flat)", f"={m.filing('A', 'diluted_shares')}", lambda c: f"={L('a_sh', c - 1)}", "num1", "m")
    line("a_eps", "Standalone diluted EPS", f"={L('a_ni', BASE)}/{L('a_sh', BASE)}", lambda c: f"={L('a_ni', c)}/{L('a_sh', c)}", "usd2", "$", bold=True)
    line("syn", "Synergies (run-rate x phasing)", None, lambda c: f"={As('syn_rr')}*{A('syn_phase', c)}")
    line("integ", "Integration costs", None, lambda c: f"=-{A('integ', c)}")
    line("newint", "Interest on new acquisition debt", None, lambda c: f"=-{m.x('Sources & Uses', 's_debt')}*{As('rate_debt')}")
    line("forgone", "Interest income forgone on cash used", None, lambda c: f"=-{As('cash_used')}*{As('rate_cash')}")
    line("amort", "Amortisation of intangible write-up", None, lambda c: f"=-{m.x('PPA', 'amort')}")
    line("pre_total", "Total pre-tax adjustments", None, lambda c: f"=SUM({L('syn', c)}:{L('amort', c)})", top=True, bold=True)
    for k, lab in (("syn", "Synergies"), ("integ", "Integration costs"), ("newint", "Interest on new acquisition debt"),
                   ("forgone", "Interest income forgone on cash used"), ("amort", "Amortisation of intangible write-up")):
        line("at_" + k, lab, None, lambda c, k=k: f"={L(k, c)}*(1-{tax})")
    line("at_total", "Total after-tax adjustments", None, lambda c: f"=SUM({L('at_syn', c)}:{L('at_amort', c)})", top=True, bold=True)
    line("pf_ni", "Pro forma net income", None, lambda c: f"={L('a_ni', c)}+{L('t_ni', c)}+{L('at_total', c)}", bold=True)
    line("pf_new", "New shares issued", None, lambda c: f"={m.x('Sources & Uses', 'new_sh')}", "num1", "m")
    line("pf_sh", "Pro forma diluted shares", None, lambda c: f"={L('a_sh', c)}+{L('pf_new', c)}", "num1", "m", bold=True)
    line("pf_eps", "Pro forma diluted EPS", None, lambda c: f"={L('pf_ni', c)}/{L('pf_sh', c)}", "usd2", "$", bold=True, top=True)
    line("sa_eps", "Standalone acquirer EPS", None, lambda c: f"={L('a_eps', c)}", "usd2", "$")
    line("acc_d", "Accretion / (dilution), $ per share", None, lambda c: f"={L('pf_eps', c)}-{L('sa_eps', c)}", "usd2", "$")
    line("acc_p", "Accretion / (dilution), %", None, lambda c: f"=IF({L('sa_eps', c)}>0,{L('acc_d', c)}/{L('sa_eps', c)},0)", "pct", "%", bold=True)
    line("verdict", "Result", None, lambda c: f'=IF({L("acc_p", c)}>0,"Accretive",IF({L("acc_p", c)}<0,"Dilutive","Neutral"))', None, "")


def _sensitivity_consts(m: _M, sh) -> dict:
    """Constants block linking the model's drivers; every grid cell is a closed form on these and the headers."""
    n = "Sensitivity"
    R = m.rows[n] = {}
    As = lambda k: m.x("Assumptions", k)
    PF = lambda k, c=Y[0]: m.x("Pro forma", k, c)
    items = [
        ("nia", "Acquirer standalone net income, year 1", f"={PF('a_ni')}", "num1"),
        ("nit", "Target standalone net income, year 1", f"={PF('t_ni')}", "num1"),
        ("epsa", "Acquirer standalone EPS, year 1", f"={PF('a_eps')}", "usd2"),
        ("na", "Acquirer diluted shares (m)", f"={PF('a_sh')}", "num1"),
        ("pa", "Acquirer share price", f"={As('acq_price')}", "usd2"),
        ("p0n", "Target unaffected equity value ($m)", f"={m.x('Purchase price', 'tgt_price')}*{m.x('Purchase price', 'tgt_sh')}", "num0"),
        ("ph1", "Synergy phasing, year 1", f"=Assumptions!{ref(m.rows['Assumptions']['syn_phase'], Y[0], True, True)}", "pct"),
        ("integ1", "Integration costs, year 1 ($m)", f"=Assumptions!{ref(m.rows['Assumptions']['integ'], Y[0], True, True)}", "num1"),
        ("t", "Tax rate", f"={As('tax')}", "pct"),
        ("rd", "Interest rate on new debt", f"={As('rate_debt')}", "pct"),
        ("rc", "Interest rate forgone on cash", f"={As('rate_cash')}", "pct"),
        ("cash", "Acquirer cash used ($m)", f"={As('cash_used')}", "num1"),
        ("f", "Transaction fees (% of equity price)", f"={As('fee_pct')}", "pct"),
        ("w", "Intangible write-up (% of excess)", f"={As('wu_pct')}", "pct"),
        ("life", "Write-up useful life (years)", f"={As('life')}", "num1"),
        ("tb", "Adjusted tangible book value ($m)", f"={m.x('PPA', 'tb')}", "num0"),
        ("prem0", "Base offer premium", f"={As('premium')}", "pct"),
        ("stock0", "Base % stock", f"={As('pct_stock')}", "pct"),
        ("syn0", "Base run-rate synergies ($m)", f"={As('syn_rr')}", "num1"),
        ("dprem", "Premium step", f"={As('prem_step')}", "pct"),
        ("dstock", "% stock step", f"={As('stock_step')}", "pct"),
        ("dsyn", "Synergies step ($m)", f"={As('syn_step')}", "num1"),
    ]
    sh.set((FIRST, 1), "Model drivers (linked)", bold=True, color=NAVY, bottom=True)
    for c in range(2, 9):
        sh.set((FIRST, c), "", bottom=True)
    for i, (k, label, f, fmt) in enumerate(items):
        r = FIRST + 1 + i
        R[k] = r
        sh.set((r, 1), label, indent=1)
        sh.set((r, C0), f, fmt=fmt)
    return R


def _sensitivity(m: _M, sh) -> None:
    n = "Sensitivity"
    sh.set("A2", "Sensitivity: year-1 accretion / (dilution)", kind="title")
    sh.set("A3", "Live closed-form grids on the model's drivers and the row / column headers. The centre cell equals the base case.", kind="note")
    sh.set((5, 1), "", kind="header")
    for c in range(2, 9):
        sh.set((5, c), "", kind="header")
    sh.width("A", 46)
    sh.width("B", 14)
    for c in range(3, 9):
        sh.width(c, 12.5)
    sh.freeze = (6, 2)
    K = _sensitivity_consts(m, sh)
    k = lambda key: f"$C${K[key]}"
    start = FIRST + len(K) + 3
    cols = [4, 5, 6, 7, 8]

    def hdr(r, c, base, step, off, lo_hi=False):
        if off == 0:
            f = f"={k(base)}"
        else:
            f = f"={k(base)}{'+' if off > 0 else '-'}{abs(off)}*{k(step)}"
        if lo_hi:
            f = "=MIN(1,MAX(0," + f[1:] + "))"
        return f

    # ---- grid 1: premium (rows) x % stock (columns)
    r1 = start
    sh.set((r1, 1), "Year-1 accretion / (dilution) %: offer premium (down) x % stock (across)", bold=True, color=NAVY, bottom=True)
    for c in range(2, 9):
        sh.set((r1, c), "", bottom=True)
    hr = r1 + 1
    sh.set((hr, 1), "Offer premium down; % stock across", kind="note")
    sh.set((hr, 2), "Equity price $m", bold=True, align="right")
    for j, c in enumerate(cols):
        sh.set((hr, c), hdr(hr, c, "stock0", "dstock", j - 2, True), fmt="pct", bold=True, align="right")
    m.rows[n]["g1_head"] = hr
    for i in range(5):
        r = hr + 1 + i
        off = i - 2
        sh.set((r, 3), hdr(r, 3, "prem0", "dprem", off), fmt="pct", bold=True)
        sh.set((r, 2), f"={k('p0n')}*(1+$C{r})", fmt="num0")
        for c in cols:
            s = f"{col_letter(c)}${hr}"
            kk = f"$B{r}"
            pf = (f"({k('nia')}+{k('nit')}+({k('syn0')}*{k('ph1')}-{k('integ1')})*(1-{k('t')})"
                  f"-(1-{k('t')})*({k('rd')}*({kk}*(1+{k('f')}-{s})-{k('cash')})+{k('rc')}*{k('cash')}+{k('w')}*MAX({kk}-{k('tb')},0)/{k('life')}))")
            sh.set((r, c), f"=({pf}/({k('na')}+{s}*{kk}/{k('pa')}))/{k('epsa')}-1", fmt="pct")
    m.rows[n]["g1_centre"] = hr + 3
    m.rows[n]["g1_centre_col"] = cols[2]
    # ---- grid 2: synergies (rows) x premium (columns)
    r2 = hr + 8
    sh.set((r2, 1), "Year-1 accretion / (dilution) %: run-rate synergies (down) x offer premium (across)", bold=True, color=NAVY, bottom=True)
    for c in range(2, 9):
        sh.set((r2, c), "", bottom=True)
    h2 = r2 + 1
    sh.set((h2, 1), "Run-rate synergies down; offer premium across", kind="note")
    for j, c in enumerate(cols):
        sh.set((h2, c), hdr(h2, c, "prem0", "dprem", j - 2), fmt="pct", bold=True, align="right")
    e2 = h2 + 1
    sh.set((e2, 1), "Equity purchase price at that premium ($m)", kind="note")
    for c in cols:
        sh.set((e2, c), f"={k('p0n')}*(1+{col_letter(c)}${h2})", fmt="num0", italic=True)
    for i in range(5):
        r = e2 + 1 + i
        off = i - 2
        f = hdr(r, 3, "syn0", "dsyn", off)
        sh.set((r, 3), "=MAX(0," + f[1:] + ")" if off else f, fmt="num1", bold=True)
        for c in cols:
            kk = f"{col_letter(c)}${e2}"
            pf = (f"({k('nia')}+{k('nit')}+($C{r}*{k('ph1')}-{k('integ1')})*(1-{k('t')})"
                  f"-(1-{k('t')})*({k('rd')}*({kk}*(1+{k('f')}-{k('stock0')})-{k('cash')})+{k('rc')}*{k('cash')}"
                  f"+{k('w')}*MAX({kk}-{k('tb')},0)/{k('life')}))")
            sh.set((r, c), f"=({pf}/({k('na')}+{k('stock0')}*{kk}/{k('pa')}))/{k('epsa')}-1", fmt="pct")
    m.rows[n]["g2_head"] = h2
    m.rows[n]["g2_centre"] = e2 + 3
    m.rows[n]["g2_centre_col"] = cols[2]
    sh.set((e2 + 8, 1), "Grids assume the write-up excess is positive and hold cash used fixed; the debt line absorbs the rest of the cash consideration.", kind="note")


def _breakeven(m: _M, sh) -> None:
    n = "Breakeven"
    _layout(sh, "Breakeven analysis", "Pre-tax synergies that make each year EPS-neutral, and the highest year-1 premium that is EPS-neutral (closed form).", m)
    R = _Rows(m, n)
    PF = lambda key, c: f"'Pro forma'!{ref(m.rows['Pro forma'][key], c)}"
    L = lambda key, c: ref(m.rows[n][key], c)
    As = lambda k: m.x("Assumptions", k)

    def line(key, label, fc, fmt="num1", unit="$m", bold=False, top=False):
        r = R.key(key)
        sh.set((r, 1), label, bold=bold, top=top, indent=0 if bold else 1)
        sh.set((r, 2), unit, kind="note", top=top)
        for c in Y:
            sh.set((r, c), fc(c), fmt=fmt, bold=bold, top=top)

    R.section(sh, "Pre-tax synergies needed to break even (closed form)")
    line("pf_ni", "Pro forma net income", lambda c: f"={PF('pf_ni', c)}")
    line("at_syn", "Less: after-tax synergies in the model", lambda c: f"={PF('at_syn', c)}")
    line("ex_syn", "Pro forma net income before synergies", lambda c: f"={L('pf_ni', c)}-{L('at_syn', c)}", top=True)
    line("sa_eps", "Standalone acquirer EPS", lambda c: f"={PF('sa_eps', c)}", "usd2", "$")
    line("pf_sh", "Pro forma diluted shares", lambda c: f"={PF('pf_sh', c)}", "num1", "m")
    line("req", "Net income needed for EPS-neutral", lambda c: f"={L('sa_eps', c)}*{L('pf_sh', c)}")
    line("be_at", "After-tax synergies needed", lambda c: f"={L('req', c)}-{L('ex_syn', c)}", top=True)
    line("be_pre", "Pre-tax synergies needed to break even (negative = cushion)", lambda c: f"={L('be_at', c)}/(1-{As('tax')})", bold=True)
    line("syn", "Pre-tax synergies in the model", lambda c: f"={PF('syn', c)}")
    line("cushion", "Synergies above / (below) breakeven", lambda c: f"={L('syn', c)}-{L('be_pre', c)}")
    line("acc_be", "Accretion at breakeven synergies (must be zero)",
         lambda c: f"=(({L('ex_syn', c)}+{L('be_pre', c)}*(1-{As('tax')}))/{L('pf_sh', c)})/{L('sa_eps', c)}-1", "pct", "%")
    R.gap()
    R.section(sh, "Maximum offer premium for year-1 EPS-neutral (closed form)")
    S = lambda key: f"Sensitivity!{ref(m.rows['Sensitivity'][key], C0, True, True)}"
    T = S("t")

    def sc(key, label, f, fmt="num1", unit="$m", bold=False):
        r = R.key(key)
        sh.set((r, 1), label, indent=0 if bold else 1, bold=bold)
        sh.set((r, 2), unit, kind="note")
        sh.set((r, C0), f, fmt=fmt, bold=bold)

    c0 = lambda key: ref(m.rows[n][key], C0)
    sc("const", "Year-1 net income before the equity-price terms",
       f"={S('nia')}+{S('nit')}+({S('syn0')}*{S('ph1')}-{S('integ1')})*(1-{T})+(1-{T})*({S('rd')}*{S('cash')}-{S('rc')}*{S('cash')}+{S('w')}*{S('tb')}/{S('life')})")
    sc("slope", "Net income lost per $ of equity price (after tax)",
       f"=(1-{T})*({S('rd')}*(1+{S('f')}-{S('stock0')})+{S('w')}/{S('life')})", "num2" if False else "pct", "")
    sc("k_star", "Maximum equity purchase price for EPS-neutral",
       f"=({c0('const')}-{S('nia')})/({c0('slope')}+{S('epsa')}*{S('stock0')}/{S('pa')})", "num0", "$m", True)
    sc("prem_star", "Maximum offer premium for year-1 EPS-neutral", f"={c0('k_star')}/{S('p0n')}-1", "pct", "%", True)
    sc("offer_star", "Offer price per share at that premium", f"={m.x('Purchase price', 'tgt_price')}*(1+{c0('prem_star')})", "usd2", "$")
    kk = c0("k_star")
    pf = (f"({S('nia')}+{S('nit')}+({S('syn0')}*{S('ph1')}-{S('integ1')})*(1-{T})"
          f"-(1-{T})*({S('rd')}*({kk}*(1+{S('f')}-{S('stock0')})-{S('cash')})+{S('rc')}*{S('cash')}+{S('w')}*MAX({kk}-{S('tb')},0)/{S('life')}))")
    sc("acc_star", "Year-1 accretion at that premium (must be zero)",
       f"=({pf}/({S('na')}+{S('stock0')}*{kk}/{S('pa')}))/{S('epsa')}-1", "pct", "%")
    sh.set((R.r + 1, 1), "Valid while the write-up excess is positive and new debt is not negative.", kind="note")


def _checks(m: _M, sh) -> None:
    n = "Checks"
    sh.set("A2", "Model checks", kind="title")
    sh.set("A3", "Every check must read OK; the master check feeds the cover.", kind="note")
    sh.set((5, 1), "Check", kind="header")
    sh.set((5, 2), "", kind="header")
    sh.set((5, C0), "Result", kind="header", align="right")
    sh.width("A", 62)
    sh.width("B", 8)
    sh.width("C", 12)
    sh.freeze = (6, 2)
    R = m.rows[n] = {}
    tol_r = FIRST + 18
    tols = [("Tol", "tol", "Rounding tolerance ($m)", "num2"), ("TolPct", "tol_pct", "Percentage tolerance (mix sums to 100%)", "pct"),
            ("TolEPS", "tol_eps", "Accretion tolerance (fraction of standalone EPS)", "pct")]
    T = {}
    sh.set((tol_r, 1), "Tolerances", bold=True, color=NAVY, bottom=True)
    sh.set((tol_r, 2), "", bottom=True)
    sh.set((tol_r, C0), "", bottom=True)
    for i, (nm, key, label, fmt) in enumerate(tols):
        r = tol_r + 1 + i
        sh.set((r, 1), label, indent=1)
        sh.set((r, C0), float(m.d[key]), kind="input", fmt=fmt)
        m.wb.define(nm, n, f"C{r}")
        T[nm] = f"$C${r}"
    As = lambda k: m.x("Assumptions", k)
    SU = lambda k: m.x("Sources & Uses", k)
    PF = lambda key, c: f"'Pro forma'!{ref(m.rows['Pro forma'][key], c, True, True)}"
    BE = lambda key, c: f"Breakeven!{ref(m.rows['Breakeven'][key], c, True, True)}"
    S = m.rows["Sensitivity"]
    y1 = Y[0]
    checks = [
        ("Sources equal uses", f'=IF(ABS({SU("s_total")}-{SU("u_total")})<={T["Tol"]},"OK","ERROR")'),
        ("Consideration mix (stock + cash) sums to 100%", f'=IF(ABS({As("pct_stock")}+{As("pct_cash")}-1)<={T["TolPct"]},"OK","ERROR")'),
        ("Goodwill is not negative", f'=IF({m.x("PPA", "goodwill")}>=0,"OK","ERROR")'),
        ("New acquisition debt is not negative", f'=IF({SU("s_debt")}>=0,"OK","ERROR")'),
        ("Cash used does not exceed acquirer cash and short-term investments",
         f'=IF({As("cash_used")}<={m.filing("A", "cash")}+{m.filing("A", "sti")}+{T["Tol"]},"OK","ERROR")'),
        ("Prices, shares and useful life are positive",
         f'=IF(AND({As("acq_price")}>0,{As("tgt_price")}>0,{m.x("Purchase price", "tgt_sh")}>0,{PF("a_sh", y1)}>0,{As("life")}>0),"OK","ERROR")'),
        ("Standalone acquirer EPS is positive (accretion % is meaningful)", f'=IF({PF("a_eps", y1)}>0,"OK","ERROR")'),
        ("Breakeven synergies reproduce 0% accretion, year 1", f'=IF(ABS({BE("acc_be", Y[0])})<={T["TolEPS"]},"OK","ERROR")'),
        ("Breakeven synergies reproduce 0% accretion, year 2", f'=IF(ABS({BE("acc_be", Y[1])})<={T["TolEPS"]},"OK","ERROR")'),
        ("Breakeven synergies reproduce 0% accretion, year 3", f'=IF(ABS({BE("acc_be", Y[2])})<={T["TolEPS"]},"OK","ERROR")'),
        ("Maximum EPS-neutral premium reproduces 0% accretion",
         f'=IF(ABS(Breakeven!{ref(m.rows["Breakeven"]["acc_star"], C0, True, True)})<={T["TolEPS"]},"OK","ERROR")'),
        ("Sensitivity grid 1 centre equals the base case",
         f'=IF(ABS(Sensitivity!{ref(S["g1_centre"], S["g1_centre_col"], True, True)}-{PF("acc_p", y1)})<={T["TolEPS"]},"OK","ERROR")'),
        ("Sensitivity grid 2 centre equals the base case",
         f'=IF(ABS(Sensitivity!{ref(S["g2_centre"], S["g2_centre_col"], True, True)}-{PF("acc_p", y1)})<={T["TolEPS"]},"OK","ERROR")'),
    ]
    for i, (label, f) in enumerate(checks):
        r = FIRST + 2 + i
        sh.set((r, 1), label, indent=1)
        sh.set((r, C0), f, bold=False)
    top, bot = FIRST + 2, FIRST + 1 + len(checks)
    assert bot < tol_r - 1
    R["master"] = FIRST
    R["first"], R["last"] = top, bot
    rng = f"C{top}:C{bot}"
    sh.set((FIRST, 1), "MASTER CHECK", bold=True)
    sh.set((FIRST, C0), f'=IF(AND(COUNTIF({rng},"ERROR")=0,SUMPRODUCT(--ISERROR({rng}))=0,COUNTIF({rng},"OK")>0),"OK","ERROR")', bold=True)
    sh.ok_error(rng)
    sh.ok_error(f"C{FIRST}")


def _cover(m: _M, sh) -> None:
    n = "Cover"
    sh.width("A", 3)
    sh.width("B", 46)
    for c in range(3, 8):
        sh.width(c, 13)
    sh.set("B2", f"{m.acq.name} ({m.acq.ticker}) acquires {m.tgt.name} ({m.tgt.ticker})", kind="title", size=18)
    sh.set("B3", "Accretion / dilution merger model, built from SEC filings", kind="note")
    P = lambda k: m.x("Purchase price", k)
    SU = lambda k: m.x("Sources & Uses", k)
    As = lambda k: m.x("Assumptions", k)
    PF = lambda k, c: f"'Pro forma'!{ref(m.rows['Pro forma'][k], c)}"
    sh.set("B5", "Deal summary", bold=True, color=NAVY, bottom=True)
    sh.set("C5", "", bottom=True)
    rows = [
        ("Offer price per share ($)", f"={P('offer')}", "usd2"),
        ("Offer premium", f"={As('premium')}", "pct"),
        ("Equity purchase price ($m)", f"={P('equity')}", "num0"),
        ("Enterprise value paid ($m)", f"={P('ev')}", "num0"),
        ("Implied EV / EBITDA", f"={P('ev_ebitda')}", "x"),
        ("Implied P/E paid", f"={P('pe_paid')}", "x"),
        ("Consideration in stock", f"={As('pct_stock')}", "pct"),
        ("New acquirer shares issued (m)", f"={SU('new_sh')}", "num1"),
        ("New acquisition debt ($m)", f"={SU('s_debt')}", "num0"),
        ("Goodwill created ($m)", f"={m.x('PPA', 'goodwill')}", "num0"),
    ]
    for i, (lab, f, fmt) in enumerate(rows):
        sh.set((6 + i, 2), lab, indent=1)
        sh.set((6 + i, 3), f, fmt=fmt)
    r = 6 + len(rows) + 1
    sh.set((r, 2), "Accretion / dilution", bold=True, color=NAVY, bottom=True)
    for k, c in enumerate(Y):
        sh.set((r, 3 + k), m.fy(k), bold=True, align="right", bottom=True)
    for i, (lab, key, fmt) in enumerate((("Standalone acquirer EPS ($)", "sa_eps", "usd2"), ("Pro forma EPS ($)", "pf_eps", "usd2"),
                                         ("Accretion / (dilution), $ per share", "acc_d", "usd2"), ("Accretion / (dilution), %", "acc_p", "pct"),
                                         ("Pre-tax synergies to break even ($m)", None, "num1"))):
        sh.set((r + 1 + i, 2), lab, indent=1, bold=key == "acc_p")
        for k, c in enumerate(Y):
            f = f"={PF(key, c)}" if key else f"=Breakeven!{ref(m.rows['Breakeven']['be_pre'], c)}"
            sh.set((r + 1 + i, 3 + k), f, fmt=fmt, bold=key == "acc_p")
    r += 7
    m.rows[n] = {"master": r}
    sh.set((r, 2), "MASTER CHECK", bold=True)
    sh.set((r, 3), f"=Checks!{ref(m.rows['Checks']['master'], C0)}", bold=True)
    sh.ok_error(f"C{r}")
    r += 2
    sh.set((r, 2), "Colour code", bold=True, color=NAVY, bottom=True)
    sh.set((r + 1, 2), "Hard-coded input or figure as filed", color=BLUE)
    sh.set((r + 2, 2), "Formula on this sheet")
    sh.set((r + 3, 2), "Link to another sheet", color=GREEN)
    r += 5
    sh.set((r, 2), "Contents", bold=True, color=NAVY, bottom=True)
    for i, (name, what) in enumerate([("Assumptions", "every driver, price and rate as a blue input"), ("Purchase price", "offer, equity value, EV and multiples"),
                                      ("Sources & Uses", "funding and shares issued"), ("PPA", "write-ups, deferred tax and goodwill"),
                                      ("Pro forma", "EPS bridge and accretion / dilution"), ("Breakeven", "breakeven synergies and maximum premium"),
                                      ("Sensitivity", "live grids on premium, % stock and synergies"), ("Checks", "integrity checks and the master check"),
                                      ("Filings", "both companies' figures as filed, with sources")]):
        sh.set((r + 1 + i, 2), name, link=f"'{name}'!A1", color=BLUE, underline=True)
        sh.set((r + 1 + i, 3), what, kind="note")
    r += 12
    sh.set((r, 2), "Sources", bold=True, color=NAVY, bottom=True)
    i = 0
    for who, s in (("Acquirer", m.acq), ("Target", m.tgt)):
        for f in s.filings:
            sh.set((r + 1 + i, 2), f"{who} FY{f['end'][:4]}: {f['form']} filed {f['filed']}, accession {f['accn']}", link=f["url"] or None,
                   color=BLUE if f["url"] else None, underline=bool(f["url"]))
            i += 1
    r += i + 2
    sh.set((r, 2), "Market data", bold=True, color=NAVY, bottom=True)
    for j, (who, mk) in enumerate((("Acquirer", m.am), ("Target", m.tm))):
        sh.set((r + 1 + j, 2), f"{who} price ${float(mk['price']):,.2f} as of {mk.get('as_of', '')}: {mk.get('source', '')}", kind="note")


# --------------------------------------------------------------------------- public API
def build_workbook(acq: stm.Statements, tgt: stm.Statements, *, acq_market: dict, tgt_market: dict, assumptions: dict | None = None):
    """The merger model as an om.xlsx.Workbook (calculated), plus metadata (rows, outputs, plants, defaults)."""
    for who, s in (("Acquirer", acq), ("Target", tgt)):
        _need(s, who)
    for who, mk in (("acquirer", acq_market), ("target", tgt_market)):
        if not mk or not mk.get("price") or float(mk["price"]) <= 0:
            raise ValueError(f"a positive {who} share price is required in its market dict (never invented)")
    d = defaults(acq, tgt, acq_market, tgt_market)
    if assumptions:
        d.update(assumptions)
    m = _M(acq, tgt, acq_market, tgt_market, d)
    wb = m.wb
    cover = wb.sheet("Cover", tab=NAVY)
    A = wb.sheet("Assumptions", tab=BLUE)
    PP = wb.sheet("Purchase price", tab=None)
    SU = wb.sheet("Sources & Uses", tab=None)
    PPA = wb.sheet("PPA", tab=None)
    PF = wb.sheet("Pro forma", tab=None)
    BE = wb.sheet("Breakeven", tab=GREEN)
    SE = wb.sheet("Sensitivity", tab=GREEN)
    CK = wb.sheet("Checks", tab="C00000")
    FL = wb.sheet("Filings", tab=GREY)
    _filings(m, FL)
    _assumptions(m, A)
    _purchase(m, PP)
    _sources_uses(m, SU)
    _ppa(m, PPA)
    _pro_forma(m, PF)
    _sensitivity(m, SE)
    _breakeven(m, BE)
    _checks(m, CK)
    _cover(m, cover)
    order = ["Cover", "Assumptions", "Purchase price", "Sources & Uses", "PPA", "Pro forma", "Breakeven", "Sensitivity", "Checks", "Filings"]
    wb.sheets.sort(key=lambda sh: order.index(sh.name))
    from .formula import calculate_workbook
    eng = calculate_workbook(wb)

    pf, rows = m.rows["Pro forma"], m.rows
    cell = lambda sheet, key, c=C0: ref(rows[sheet][key], c)
    outputs = [
        {"id": "merger.accretion_y1_pct", "sheet": "Pro forma", "ref": cell("Pro forma", "acc_p", Y[0]), "units": "%", "label": f"EPS accretion / (dilution), {m.fy(0)}"},
        {"id": "merger.accretion_y2_pct", "sheet": "Pro forma", "ref": cell("Pro forma", "acc_p", Y[1]), "units": "%", "label": f"EPS accretion / (dilution), {m.fy(1)}"},
        {"id": "merger.pf_eps_y1", "sheet": "Pro forma", "ref": cell("Pro forma", "pf_eps", Y[0]), "units": "$", "label": f"Pro forma diluted EPS, {m.fy(0)}"},
        {"id": "merger.goodwill", "sheet": "PPA", "ref": cell("PPA", "goodwill"), "units": "$m", "label": "Goodwill created"},
        {"id": "merger.breakeven_synergies_y1", "sheet": "Breakeven", "ref": cell("Breakeven", "be_pre", Y[0]), "units": "$m",
         "label": f"Pre-tax synergies to break even, {m.fy(0)}"},
        {"id": "merger.offer_price", "sheet": "Purchase price", "ref": cell("Purchase price", "offer"), "units": "$", "label": "Offer price per share"},
        {"id": "merger.ev_paid", "sheet": "Purchase price", "ref": cell("Purchase price", "ev"), "units": "$m", "label": "Enterprise value paid"},
        {"id": "merger.new_shares", "sheet": "Sources & Uses", "ref": cell("Sources & Uses", "new_sh"), "units": "m", "label": "New acquirer shares issued"},
    ]
    plants = {"shares": f"Pro forma!{ref(pf['pf_sh'], Y[0])}", "goodwill": f"PPA!{cell('PPA', 'goodwill')}",
              "synergy_tax": f"Pro forma!{ref(pf['at_syn'], Y[0])}"}
    warnings = [f"acquirer: {w}" for w in acq.warnings] + [f"target: {w}" for w in tgt.warnings]
    if acq.years[-1].month != tgt.years[-1].month:
        warnings.append("fiscal year ends differ between acquirer and target; projections are not calendarised")
    meta = {"model": "merger", "converged": eng.converged, "iterations": eng.iterations, "acquirer": acq.ticker, "target": tgt.ticker,
            "rows": {k: dict(v) for k, v in rows.items()}, "outputs": outputs, "plants": plants, "warnings": warnings, "defaults": d,
            "forecast_years": F}
    return wb, meta


def build(acq: stm.Statements, tgt: stm.Statements, *, acq_market: dict, tgt_market: dict, assumptions: dict | None = None) -> tuple[bytes, dict]:
    wb, meta = build_workbook(acq, tgt, acq_market=acq_market, tgt_market=tgt_market, assumptions=assumptions)
    return wb.to_bytes(), meta
