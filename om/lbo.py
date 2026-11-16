"""Leveraged-buyout model (take-private of the company in the statements), written by code.

Sheets:
  Cover            title, key returns, master check, contents
  Assumptions      every blue input: entry pricing (premium or multiple switch), fees, minimum cash, tranche table,
                   operating drivers per projection year, exit, circularity switch, sensitivity steps
  Sources & Uses   purchase equity, refinanced net debt, fees; tranches by x EBITDA and the sponsor-equity plug
  Operations       historicals (linked from Filings) and five projection years down to levered free cash flow
  Debt             revolver, term loan B (amortisation and cash sweep), senior notes (bullet), PIK notes;
                   interest on average balances behind Circ; credit statistics
  Returns          exit value, MoM, IRR (closed form plus an IRR() cross-check), returns attribution
  Sensitivity      live closed-form grids (no data tables)
  Checks           every check reads OK or ERROR; master check
  Filings          historicals as filed, blue, with a source comment and filing link

Rules: $m throughout (per share in $); no typed number inside a formula beyond the structural constants; every
projection row uses one formula across all years; the LLM never types a number here.
"""
from __future__ import annotations

from datetime import date

from . import statements as stm
from .xlsx import BLUE, GREEN, GREY, NAVY, Workbook, col_letter, quote_sheet, ref

F = 5                       # projection years
FIRST = 8                   # first data row
C0 = 3                      # first period column (C)
X2 = '0.00"x"_);(0.00"x")'
PCT2 = '0.00%_);(0.00%)'


class UnsupportedCompany(ValueError):
    pass


# --------------------------------------------------------------------------- grid helper
class _G:
    """Deferred-render sheet: rows are assigned when lines are declared, so formulas can reference rows declared later."""

    def __init__(self, m: "_M", name: str, tab: str | None, title: str, sub: str, headers=None, hdr2=None, a_width: float = 46):
        self.m, self.name = m, name
        self.sh = m.wb.sheet(name, tab=tab)
        self.rows: dict[str, int] = {}
        self.specs: list = []
        self.r = FIRST
        self.title, self.sub = title, sub
        self.headers, self.hdr2, self.a_width = headers, hdr2, a_width
        self.ncols = len(headers) if headers else 1

    # declaration
    def section(self, title: str) -> None:
        self.specs.append(("section", self.r, title))
        self.r += 1

    def gap(self, n: int = 1) -> None:
        self.r += n

    def line(self, key: str, label: str, fn=None, span: tuple[int, int] | None = None, *, fmt: str = "num0", bold: bool = False,
             top: bool = False, indent: int = 0, unit: str = "", italic: bool = False, kind: str | None = None, extra: dict | None = None,
             name: str | None = None, comment: str | None = None, validate: list | None = None) -> None:
        """fn(i) -> value for column C0+i, i within span (inclusive). `extra`: {column offset: (value, fmt)} for side cells."""
        self.rows[key] = self.r
        self.specs.append(("line", self.r, key, label, fn, span, fmt, bold, top, indent, unit, italic, kind, extra or {}, name, comment, validate))
        self.r += 1

    def one(self, key: str, label: str, value, **kw) -> None:
        """A single value in column C."""
        self.line(key, label, (lambda i, v=value: v), (0, 0), **kw)

    # references
    def at(self, key: str, i: int, abs_col: bool = False, abs_row: bool = False) -> str:
        a = ref(self.rows[key], C0 + i, abs_col=abs_col, abs_row=abs_row)
        return a if self.m.ctx == self.name else f"{quote_sheet(self.name)}!{a}"

    def c(self, key: str) -> str:
        """Absolute reference to the single value in column C."""
        a = ref(self.rows[key], C0, abs_col=True, abs_row=True)
        return a if self.m.ctx == self.name else f"{quote_sheet(self.name)}!{a}"

    def rng(self, key: str, i0: int, i1: int) -> str:
        a = f"{ref(self.rows[key], C0 + i0, abs_col=True, abs_row=True)}:{ref(self.rows[key], C0 + i1, abs_col=True, abs_row=True)}"
        return a if self.m.ctx == self.name else f"{quote_sheet(self.name)}!{a}"

    def render(self) -> None:
        m, sh = self.m, self.sh
        m.ctx = self.name
        sh.set("A2", self.title, kind="title")
        sh.set("A3", self.sub, kind="note")
        sh.set((5, 1), f"{m.s.currency} in millions", kind="header")
        sh.set((5, 2), "", kind="header")
        sh.set((6, 1), self.hdr2[0] if self.hdr2 else "", kind="note")
        sh.width("A", self.a_width)
        sh.width("B", 8)
        for i, h in enumerate(self.headers or []):
            sh.set((5, C0 + i), h, kind="header", align="right")
            if self.hdr2:
                sh.set((6, C0 + i), self.hdr2[1][i], kind="note", align="right")
            sh.width(C0 + i, 12.5)
        sh.freeze = (6, 2)
        for spec in self.specs:
            if spec[0] == "section":
                _, r, title = spec
                sh.set((r, 1), title, bold=True, color=NAVY, bottom=True)
                for c in range(2, C0 + self.ncols):
                    sh.set((r, c), "", bottom=True)
                continue
            _, r, key, label, fn, span, fmt, bold, top, indent, unit, italic, kind, extra, name, comment, validate = spec
            sh.set((r, 1), label, bold=bold, indent=indent, italic=italic, top=top, color=GREY if italic else None)
            if unit:
                sh.set((r, 2), unit, kind="note", top=top)
            elif top:
                sh.set((r, 2), "", top=top)
            if fn and span:
                for i in range(span[0], span[1] + 1):
                    v = fn(i)
                    if v is None:
                        if top:
                            sh.set((r, C0 + i), "", top=True)
                        continue
                    sh.set((r, C0 + i), v, fmt=fmt, bold=bold, top=top, italic=italic, kind=kind,
                           comment=comment if (i == span[0] and comment) else None)
            for off, (v, f2) in extra.items():
                v = v() if callable(v) else v
                sh.set((r, C0 + off), v, fmt=f2, kind="calc" if isinstance(v, str) else kind)
            if name:
                self.m.wb.define(name, self.name, ref(r, C0))
            if validate:
                sh.validate_list(ref(r, C0), validate)


class _M:
    def __init__(self, s: stm.Statements):
        self.s = s
        self.H = len(s.years)
        self.K = self.H - 1                 # index of the LTM (closing) period
        self.wb = Workbook(iterate=True)
        self.ctx = ""

    def label(self, p: int) -> str:
        if p < self.H:
            return f"FY{self.s.years[p].year}A"
        return f"FY{self.s.years[-1].year + p - self.H + 1}E"

    def end(self, p: int) -> str:
        if p < self.H:
            return self.s.years[p].isoformat()
        e = self.s.years[-1]
        try:
            return e.replace(year=e.year + p - self.H + 1).isoformat()
        except ValueError:
            return date(e.year + p - self.H + 1, e.month, 28).isoformat()


# --------------------------------------------------------------------------- defaults
def _sd(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _clamp(v, lo, hi, default):
    return default if v is None else max(lo, min(hi, v))


def _avg(xs, n=3):
    xs = [x for x in xs if x is not None][-n:]
    return sum(xs) / len(xs) if xs else None


def defaults(s: stm.Statements, market: dict | None = None) -> dict:
    """Assumptions derived from the filings (and the market price, for the exit multiple) so the base case is sensible."""
    H = len(s.years)
    g = lambda k, i: s.get(k, i)
    last = H - 1
    rev = [g("revenue", i) for i in range(H)]
    da = [g("da", i) or 0.0 for i in range(H)]
    ebitda = [(g("ebit", i) or 0.0) + da[i] for i in range(H)]
    growth = [_sd(rev[i], rev[i - 1]) - 1 if i and _sd(rev[i], rev[i - 1]) else None for i in range(H)]
    y1 = _clamp(_avg(growth), -0.10, 0.25, 0.05)
    lt = 0.03
    gr = [y1 + (lt - y1) * t / (F - 1) for t in range(F)]
    margin = _clamp(_sd(ebitda[last], rev[last]), 0.03, 0.70, 0.20)
    da_pct = _clamp(_sd(da[last], rev[last]), 0.0, 0.30, 0.04)
    capex = _clamp(_avg([_sd(g("capex", i), rev[i]) for i in range(H)]), 0.0, 0.30, 0.04)
    nwc_bal = (g("ar", last) or 0) + (g("inventory", last) or 0) - (g("ap", last) or 0)
    nwc = _clamp(_sd(nwc_bal, rev[last]), 0.0, 0.40, 0.10)
    tax = _clamp(_avg([_sd(g("tax", i), g("pretax", i)) for i in range(H) if (g("pretax", i) or 0) > 0]), 0.15, 0.30, 0.25)
    min_cash = round(_clamp(_sd(g("cash", last), rev[last]), 0.01, 0.05, 0.02) * rev[last], 1)
    d = {
        "entry_mode": 1, "premium": 0.25, "entry_mult": 10.0, "txn_fee": 0.02, "fin_fee": 0.025, "min_cash": min_cash,
        "rev_x": 0.0, "rev_rate": 0.075,
        "tlb_x": 3.0, "tlb_rate": 0.085, "tlb_amort": 0.01, "tlb_sweep": 1.0,
        "sn_x": 1.5, "sn_rate": 0.105,
        "pik_x": 0.5, "pik_rate": 0.12,
        "max_lev": 6.5,
        "growth": gr, "margin": [margin] * F, "da": [da_pct] * F, "capex": [capex] * F, "nwc": [nwc] * F, "tax": [tax] * F,
        "exit_mult": 8.0, "exit_year": 5, "circ": 1,
        "entry_step": 0.5, "exit_step": 0.5, "margin_step": 0.01,
    }
    if market and market.get("price") and g("diluted_shares", last) and ebitda[last] > 0:
        debt = (g("debt_current", last) or 0) + (g("debt_noncurrent", last) or 0)
        net_debt = debt - (g("cash", last) or 0) - (g("sti", last) or 0)
        ev = float(market["price"]) * (1 + d["premium"]) * g("diluted_shares", last) + net_debt
        d["entry_mult"] = round(ev / ebitda[last], 1)
        d["exit_mult"] = d["entry_mult"]
    return d


# --------------------------------------------------------------------------- builder
def build(s: stm.Statements, *, market: dict, assumptions: dict | None = None, circ: int = 1) -> tuple[bytes, dict]:
    wb, meta = build_workbook(s, market=market, assumptions=assumptions, circ=circ)
    return wb.to_bytes(), meta


def build_workbook(s: stm.Statements, *, market: dict, assumptions: dict | None = None, circ: int = 1):
    """The LBO as a calculated om.xlsx.Workbook plus metadata (row map, outputs, plant locators)."""
    if s.financial_format:
        raise UnsupportedCompany(f"{s.ticker} reports a bank/insurer balance sheet; an operating-company LBO needs a classified one.")
    if len(s.years) < 2:
        raise UnsupportedCompany(f"{s.ticker}: need at least two fiscal years of filings.")
    last = len(s.years) - 1
    missing = [s.label(k) for k in ("revenue", "ebit", "da", "diluted_shares") if s.get(k, last) is None]
    if missing:
        raise UnsupportedCompany(f"{s.ticker}: the latest filing doesn't tag {', '.join(missing)}; can't size an LBO.")
    if not market or not market.get("price") or not market.get("as_of"):
        raise ValueError("market must carry price, as_of and source (never invented)")
    d = defaults(s, market)
    if assumptions:
        d.update(assumptions)
    d["circ"] = circ
    d["_src"] = f"{market.get('source', '')}, as of {market['as_of']}"
    m = _M(s)
    H, K, wb = m.H, m.K, m.wb
    NP = H + F
    yrs = f"fiscal years {s.years[0].year}–{s.years[-1].year} actual, {s.years[-1].year + 1}–{s.years[-1].year + F} projected"
    labels_all = [m.label(p) for p in range(NP)]
    ends_all = [m.end(p) for p in range(NP)]
    compact = ["Close (LTM)"] + [f"Year {t}" for t in range(1, F + 1)]
    compact2 = [m.label(K)] + [m.label(K + t) for t in range(1, F + 1)]
    P = lambda t: K + t                     # period index of year t (0 = LTM)
    U = f"{s.currency} in millions"

    cover = wb.sheet("Cover", tab=NAVY)
    A = _G(m, "Assumptions", BLUE, "Assumptions", "Blue cells are inputs. Grey columns show the same ratio in the actuals for reference.", a_width=52)
    SU = _G(m, "Sources & Uses", None, f"{s.name} — sources and uses at close", "Sponsor equity is the plug: total uses less the debt raised", ["Amount", "% of total", "x LTM EBITDA"])
    OP = _G(m, "Operations", None, f"{s.name} — operating build", yrs, labels_all, ("Fiscal year ending", ends_all))
    DB = _G(m, "Debt", None, "Debt schedule and credit statistics",
            "Revolver draws to hold minimum cash and is repaid first; term loan B amortises and sweeps excess cash; PIK accrues to principal",
            compact, ("Fiscal year ending", compact2))
    RT = _G(m, "Returns", None, "Sponsor returns", "Exit value, money multiple and IRR (closed form with an IRR() cross-check), and where the gain comes from",
            ["Value", "", "", "", "", ""])
    SE = wb.sheet("Sensitivity", tab=GREEN)
    CK = _G(m, "Checks", "C00000", "Model checks", "Every check must read OK; the master check feeds the cover", compact, ("Period", compact2))
    FL = _G(m, "Filings", GREY, f"{s.name} — figures as filed with the SEC",
            "Blue = as reported (XBRL), $m. Hover for the concept, period and accession; click to open the filing.", labels_all[:H], ("Fiscal year ending", ends_all[:H]))

    # ------------------------------------------------------------ Filings
    FL.section("As reported")
    for k, (stmt, kind, sign, label, chain) in stm.LINES.items():
        fmt = "usd2" if k == "eps_diluted" else ("num1" if k == "diluted_shares" else "num0")

        def hv(i, k=k):
            if i >= H:
                return None
            v = s.data[k][i].value
            return v

        FL.line(k, f"{stmt} · {label}", hv, (0, H - 1), fmt=fmt, kind="hist")
    FL.gap()
    FL.line("filing", "Source filing", lambda i: s.filings[i]["form"] + " " + s.filings[i]["accn"], (0, H - 1), fmt="text", kind="text")

    fl = lambda key, p: FL.at(key, p)
    FLc = lambda key: FL.at(key, last)      # latest filed year

    # ------------------------------------------------------------ Assumptions
    A.section("Switches")
    A.one("circ", "Circularity: 1 = interest on average balances, 0 = opening balances", float(d["circ"]), fmt="int", name="Circ", validate=[0, 1])
    A.one("entry_mode", "Entry pricing: 1 = premium to current price, 2 = EV / LTM EBITDA multiple", float(d["entry_mode"]), fmt="int", name="EntryMode", validate=[1, 2])
    A.gap()
    A.section("Market data (caller-supplied, never invented)")
    A.one("price", "Current share price", float(market["price"]), fmt="usd2", unit="$", name="Price", kind="input",
          comment=f"{market.get('source', 'market data')}, as of {market['as_of']}")
    A.one("as_of", "Price as of", str(market["as_of"]), fmt="text", kind="text")
    A.one("src", "Price source", str(market.get("source", "")), fmt="text", kind="text")
    A.gap()
    A.section("Entry")
    A.one("premium", "Offer premium to current price (used when entry pricing = 1)", float(d["premium"]), fmt="pct", name="Premium", kind="input")
    A.one("entry_mult", "Entry EV / LTM EBITDA (used when entry pricing = 2)", float(d["entry_mult"]), fmt="x", name="EntryMult", kind="input")
    A.one("txn_fee", "Transaction fees (% of enterprise value)", float(d["txn_fee"]), fmt="pct", name="TxnFee", kind="input")
    A.one("fin_fee", "Financing fees (% of debt raised)", float(d["fin_fee"]), fmt="pct", name="FinFee", kind="input")
    A.one("min_cash", "Minimum cash", float(d["min_cash"]), fmt="num1", unit="$m", name="MinCash", kind="input")
    A.one("max_lev", "Maximum total leverage at close (check)", float(d["max_lev"]), fmt="x", name="MaxLev", kind="input")
    A.gap()
    A.section("Financing tranches")
    A.line("tr_head", "Tranche", lambda i: ("x LTM EBITDA", "Cash rate", "PIK rate", "Amortisation", "Cash sweep")[i], (0, 4), fmt="text", bold=True, kind="text")
    A.line("t_rev", "Revolver (drawn at close; draws to hold minimum cash, repaid first)",
           lambda i: (d["rev_x"], d["rev_rate"])[i] if i < 2 else None, (0, 1), indent=1, kind="input",
           extra={}, fmt="pct")
    A.line("t_tlb", "Term loan B (mandatory amortisation, cash sweep)",
           lambda i: (d["tlb_x"], d["tlb_rate"], None, d["tlb_amort"], d["tlb_sweep"])[i], (0, 4), indent=1, kind="input", fmt="pct")
    A.line("t_sn", "Senior notes (bullet, cash interest)", lambda i: (d["sn_x"], d["sn_rate"])[i] if i < 2 else None, (0, 1), indent=1, kind="input", fmt="pct")
    A.line("t_pik", "PIK notes (interest accrues to principal)", lambda i: (d["pik_x"], None, d["pik_rate"])[i] if i != 1 else None, (0, 2),
           indent=1, kind="input", fmt="pct")
    A.gap()
    A.section("Exit")
    A.one("exit_mult", "Exit EV / EBITDA", float(d["exit_mult"]), fmt="x", name="ExitMult", kind="input")
    A.one("exit_year", "Exit year (1 to 5)", float(d["exit_year"]), fmt="int", name="ExitYear", kind="input", validate=[1, 2, 3, 4, 5])
    A.gap()
    A.section("Sensitivity steps")
    A.one("entry_step", "Entry multiple step", float(d["entry_step"]), fmt="x", name="EntryStep", kind="input")
    A.one("exit_step", "Exit multiple step", float(d["exit_step"]), fmt="x", name="ExitStep", kind="input")
    A.one("margin_step", "Exit EBITDA margin step", float(d["margin_step"]), fmt="pct", name="MarginStep", kind="input")
    A.gap()
    A.section("Operating drivers by projection year")
    A.line("hdr", "", lambda p: labels_all[p], (0, NP - 1), fmt="text", bold=True, kind="text")

    def drv(key, label, vals, hist=None, fmt="pct"):
        A.line(key, label, lambda p: float(vals[p - H]) if p >= H else (hist(p) if hist else None), (0, NP - 1), fmt=fmt, indent=1,
               kind=None)

    ratio = lambda num, den: (lambda p: f"={num(p)}/{den(p)}")
    drv("growth", "Revenue growth", d["growth"], lambda p: f"={OP.at('growth', p)}" if p else None)
    drv("margin", "EBITDA margin", d["margin"], lambda p: f"={OP.at('margin', p)}")
    drv("da", "D&A (% of revenue)", d["da"], lambda p: f"={OP.at('da', p)}/{OP.at('rev', p)}")
    drv("capex", "Capex (% of revenue)", d["capex"], lambda p: f"={OP.at('capex', p)}/{OP.at('rev', p)}")
    drv("nwc", "Net working capital (% of change in revenue)", d["nwc"])
    drv("tax", "Tax rate", d["tax"], lambda p: f"=IFERROR({fl('tax', p)}/{fl('pretax', p)},0)" if s.get("pretax", p) and s.get("tax", p) is not None else None)

    # ------------------------------------------------------------ Operations
    pj = (H, NP - 1)
    OP.section("Income and cash flow")
    OP.line("rev", "Revenue", lambda p: f"={fl('revenue', p)}" if p < H else f"={OP.at('rev', p - 1)}*(1+{A.at('growth', p)})", (0, NP - 1), bold=True)
    OP.line("growth", "% growth", lambda p: f"={OP.at('rev', p)}/{OP.at('rev', p - 1)}-1" if p else None, (0, NP - 1), fmt="pct", italic=True, indent=1)
    OP.line("ebitda", "EBITDA", lambda p: f"={fl('ebit', p)}+{fl('da', p)}" if p < H else f"={OP.at('rev', p)}*{A.at('margin', p)}", (0, NP - 1), bold=True)
    OP.line("margin", "% margin", lambda p: f"={OP.at('ebitda', p)}/{OP.at('rev', p)}", (0, NP - 1), fmt="pct", italic=True, indent=1)
    OP.line("da", "(−) Depreciation & amortisation", lambda p: f"={fl('da', p)}" if p < H else f"={OP.at('rev', p)}*{A.at('da', p)}", (0, NP - 1), indent=1)
    OP.line("ebit", "EBIT", lambda p: f"={OP.at('ebitda', p)}-{OP.at('da', p)}", (0, NP - 1), bold=True, top=True)
    OP.gap()
    OP.line("capex", "Capex", lambda p: f"={fl('capex', p)}" if p < H else f"={OP.at('rev', p)}*{A.at('capex', p)}", (0, NP - 1), indent=1)
    OP.line("dnwc", "Increase in net working capital", lambda p: f"=({OP.at('rev', p)}-{OP.at('rev', p - 1)})*{A.at('nwc', p)}", pj, indent=1)
    OP.line("int_cash", "Cash interest", lambda p: f"={DB.at('int_total', p - K)}", pj, indent=1)
    OP.line("int_pik", "PIK interest (non-cash)", lambda p: f"={DB.at('pik_acc', p - K)}", pj, indent=1)
    OP.line("pretax", "Taxable income (EBIT less all interest)", lambda p: f"={OP.at('ebit', p)}-{OP.at('int_cash', p)}-{OP.at('int_pik', p)}", pj, top=True)
    OP.line("tax", "Cash taxes (on EBIT less interest, floored at zero)", lambda p: f"=MAX({OP.at('pretax', p)},0)*{A.at('tax', p)}", pj, indent=1)
    OP.line("lfcf", "Levered free cash flow (before debt repayment)",
            lambda p: f"={OP.at('ebitda', p)}-{OP.at('tax', p)}-{OP.at('capex', p)}-{OP.at('dnwc', p)}-{OP.at('int_cash', p)}", pj, bold=True, top=True)
    OP.line("conv", "% of EBITDA", lambda p: f"={OP.at('lfcf', p)}/{OP.at('ebitda', p)}", pj, fmt="pct", italic=True, indent=1)

    # ------------------------------------------------------------ Sources & Uses
    m.ctx = SU.name
    cI = lambda key: SU.c(key)
    ltm = OP.at("ebitda", K)
    SU.section("Entry pricing")
    SU.one("ltm", "LTM EBITDA", f"={ltm}", unit="$m")
    SU.one("shares", "Diluted shares (latest filing)", f"={FLc('diluted_shares')}", fmt="num1", unit="m")
    SU.one("debt_old", "Existing debt", f"={FLc('debt_current')}+{FLc('debt_noncurrent')}", unit="$m")
    SU.one("cash_old", "Existing cash and short-term investments", f"={FLc('cash')}+{FLc('sti')}", unit="$m")
    SU.one("net_debt", "Existing net debt (refinanced)", f"={cI('debt_old')}-{cI('cash_old')}", unit="$m", bold=True)
    SU.one("price", "Current share price", "=Price", fmt="usd2", unit="$")
    SU.one("offer", "Offer price per share", f"=IF(EntryMode=1,Price*(1+Premium),(EntryMult*{cI('ltm')}-{cI('net_debt')})/{cI('shares')})", fmt="usd2", unit="$", bold=True)
    SU.one("prem_impl", "Implied premium to current price", f"={cI('offer')}/{cI('price')}-1", fmt="pct", italic=True)
    SU.one("eq_price", "Equity purchase price", f"={cI('offer')}*{cI('shares')}", unit="$m")
    SU.one("ev", "Entry enterprise value", f"={cI('eq_price')}+{cI('net_debt')}", unit="$m", bold=True, top=True)
    SU.one("mult", "Implied EV / LTM EBITDA", f"={cI('ev')}/{cI('ltm')}", fmt="x", italic=True)
    SU.gap()
    SU.section("Uses")
    SU.gap(0)
    tot_u, tot_s = "tot_u", "tot_s"
    pct = lambda key, tot: {1: (lambda: f"={SU.c(key)}/{SU.c(tot)}", "pct")}
    xe = lambda key: {2: (lambda: f"={SU.c(key)}/{SU.c('ltm')}", "x")}
    SU.line("u_eq", "Equity purchase price", lambda i: f"={cI('eq_price')}", (0, 0), indent=1, extra={**pct("u_eq", tot_u), **xe("u_eq")})
    SU.line("u_nd", "Refinance existing net debt", lambda i: f"={cI('net_debt')}", (0, 0), indent=1, extra={**pct("u_nd", tot_u), **xe("u_nd")})
    SU.line("u_txn", "Transaction fees", lambda i: f"=TxnFee*{cI('ev')}", (0, 0), indent=1, extra={**pct("u_txn", tot_u), **xe("u_txn")})
    SU.line("u_fin", "Financing fees", lambda i: f"=FinFee*{cI('s_debt')}", (0, 0), indent=1, extra={**pct("u_fin", tot_u), **xe("u_fin")})
    SU.line("u_cash", "Minimum cash to balance sheet", lambda i: "=MinCash", (0, 0), indent=1, extra={**pct("u_cash", tot_u), **xe("u_cash")})
    SU.line(tot_u, "Total uses", lambda i: f"=SUM({ref(SU.rows['u_eq'], C0)}:{ref(SU.rows['u_cash'], C0)})", (0, 0), bold=True, top=True,
            extra={**pct(tot_u, tot_u), **xe(tot_u)})
    SU.gap()
    SU.section("Sources")
    SU.line("s_rev", "Revolver drawn at close", lambda i: f"=RevX*{cI('ltm')}", (0, 0), indent=1, extra={**pct("s_rev", tot_s), **xe("s_rev")})
    SU.line("s_tlb", "Term loan B", lambda i: f"=TlbX*{cI('ltm')}", (0, 0), indent=1, extra={**pct("s_tlb", tot_s), **xe("s_tlb")})
    SU.line("s_sn", "Senior notes", lambda i: f"=SnX*{cI('ltm')}", (0, 0), indent=1, extra={**pct("s_sn", tot_s), **xe("s_sn")})
    SU.line("s_pik", "PIK notes", lambda i: f"=PikX*{cI('ltm')}", (0, 0), indent=1, extra={**pct("s_pik", tot_s), **xe("s_pik")})
    SU.line("s_debt", "Total debt raised", lambda i: f"=SUM({ref(SU.rows['s_rev'], C0)}:{ref(SU.rows['s_pik'], C0)})", (0, 0), bold=True, top=True,
            extra={**pct("s_debt", tot_s), **xe("s_debt")})
    SU.line("s_eq", "Sponsor equity (plug)", lambda i: f"={cI(tot_u)}-{cI('s_debt')}", (0, 0), bold=True, extra={**pct("s_eq", tot_s), **xe("s_eq")})
    SU.line(tot_s, "Total sources", lambda i: f"={cI('s_debt')}+{cI('s_eq')}", (0, 0), bold=True, top=True, extra={**pct(tot_s, tot_s), **xe(tot_s)})
    SU.gap()
    SU.one("fees", "Total fees and leakage", f"={cI('u_txn')}+{cI('u_fin')}", unit="$m")
    SU.one("eq_pct", "Sponsor equity as % of total capitalisation", f"={cI('s_eq')}/{cI(tot_s)}", fmt="pct", italic=True)

    # ------------------------------------------------------------ Debt
    m.ctx = DB.name
    cI_su = lambda key: SU.c(key)
    db = lambda key, t: DB.at(key, t)
    T = (1, F)
    CL = (0, F)

    DB.section("Credit statistics basis")
    DB.line("ebitda", "EBITDA", lambda t: f"={OP.at('ebitda', P(t))}", CL, bold=True)
    DB.gap()
    DB.section("Cash waterfall")
    DB.line("cash_open", "Opening cash", lambda t: f"={db('cash', t - 1)}", T, indent=1)
    DB.line("lfcf", "Levered free cash flow", lambda t: f"={OP.at('lfcf', P(t))}", T, indent=1)
    DB.line("mand_neg", "(−) Mandatory amortisation, term loan B", lambda t: f"=-{db('tlb_mand', t)}", T, indent=1)
    DB.line("pre", "Cash before revolver and sweep", lambda t: f"={db('cash_open', t)}+{db('lfcf', t)}+{db('mand_neg', t)}", T, top=True)
    DB.line("excess", "Excess over minimum cash (negative = shortfall)", lambda t: f"={db('pre', t)}-MinCash", T, indent=1)
    DB.line("rev_chg", "Revolver draw / (repayment)", lambda t: f"=MAX(-{db('rev_open', t)},-{db('excess', t)})", T, indent=1)
    DB.line("sweep_av", "Excess cash available to sweep", lambda t: f"=MAX({db('excess', t)}+{db('rev_chg', t)},0)", T, indent=1)
    DB.line("sweep_neg", "(−) Term loan B cash sweep", lambda t: f"=-{db('tlb_sweep', t)}", T, indent=1)
    DB.line("cash", "Closing cash", lambda t: f"={cI_su('u_cash')}" if t == 0 else f"={db('pre', t)}+{db('rev_chg', t)}+{db('sweep_neg', t)}", CL, bold=True, top=True)
    DB.gap()
    DB.section("Revolver")
    DB.line("rev_open", "Opening balance", lambda t: f"={db('rev_end', t - 1)}", T, indent=1)
    DB.line("rev_chg2", "Draw / (repayment)", lambda t: f"={db('rev_chg', t)}", T, indent=1)
    DB.line("rev_end", "Closing balance", lambda t: f"={cI_su('s_rev')}" if t == 0 else f"={db('rev_open', t)}+{db('rev_chg2', t)}", CL, bold=True, top=True)
    DB.gap()
    DB.section("Term loan B")
    DB.line("tlb_open", "Opening balance", lambda t: f"={db('tlb_end', t - 1)}", T, indent=1)
    DB.line("tlb_mand", "Mandatory amortisation (% of original)",
            lambda t: f"=MIN({db('tlb_open', t)},TlbAmort*{DB.at('tlb_end', 0, abs_col=True)})", T, indent=1)
    DB.line("tlb_sweep", "Cash sweep (% of excess cash, never above the balance)",
            lambda t: f"=MIN({db('tlb_open', t)}-{db('tlb_mand', t)},TlbSweep*{db('sweep_av', t)})", T, indent=1)
    DB.line("tlb_end", "Closing balance", lambda t: f"={cI_su('s_tlb')}" if t == 0 else f"={db('tlb_open', t)}-{db('tlb_mand', t)}-{db('tlb_sweep', t)}", CL, bold=True, top=True)
    DB.gap()
    DB.section("Senior notes (bullet)")
    DB.line("sn_open", "Opening balance", lambda t: f"={db('sn_end', t - 1)}", T, indent=1)
    DB.line("sn_end", "Closing balance", lambda t: f"={cI_su('s_sn')}" if t == 0 else f"={db('sn_open', t)}", CL, bold=True, top=True)
    DB.gap()
    DB.section("PIK notes")
    DB.line("pik_open", "Opening balance", lambda t: f"={db('pik_end', t - 1)}", T, indent=1)
    DB.line("pik_acc", "PIK interest accrued to principal", lambda t: f"={db('pik_open', t)}*PikRate", T, indent=1)
    DB.line("pik_end", "Closing balance", lambda t: f"={cI_su('s_pik')}" if t == 0 else f"={db('pik_open', t)}+{db('pik_acc', t)}", CL, bold=True, top=True)
    DB.gap()
    DB.section("Cash interest (average balances when Circ = 1, opening balances when 0)")
    DB.line("int_rev", "Revolver", lambda t: f"=IF(Circ=1,AVERAGE({db('rev_open', t)},{db('rev_end', t)}),{db('rev_open', t)})*RevRate", T, indent=1)
    DB.line("int_tlb", "Term loan B", lambda t: f"=IF(Circ=1,AVERAGE({db('tlb_open', t)},{db('tlb_end', t)}),{db('tlb_open', t)})*TlbRate", T, indent=1)
    DB.line("int_sn", "Senior notes", lambda t: f"={db('sn_open', t)}*SnRate", T, indent=1)
    DB.line("int_total", "Total cash interest", lambda t: f"=SUM({ref(DB.rows['int_rev'], C0 + t)}:{ref(DB.rows['int_sn'], C0 + t)})", T, bold=True, top=True)
    DB.gap()
    DB.section("Credit statistics")
    DB.line("debt", "Total debt (incl. accrued PIK)", lambda t: f"={db('rev_end', t)}+{db('tlb_end', t)}+{db('sn_end', t)}+{db('pik_end', t)}", CL, bold=True)
    DB.line("net_debt", "Net debt", lambda t: f"={db('debt', t)}-{db('cash', t)}", CL)
    DB.line("lev", "Total debt / EBITDA", lambda t: f"={db('debt', t)}/{db('ebitda', t)}", CL, fmt="x", italic=True)
    DB.line("nlev", "Net debt / EBITDA", lambda t: f"={db('net_debt', t)}/{db('ebitda', t)}", CL, fmt="x", italic=True)
    DB.line("cov", "EBITDA / cash interest", lambda t: f"=IFERROR({db('ebitda', t)}/{db('int_total', t)},0)", T, fmt="x", italic=True)
    DB.line("cov2", "(EBITDA − capex) / cash interest", lambda t: f"=IFERROR(({db('ebitda', t)}-{OP.at('capex', P(t))})/{db('int_total', t)},0)", T, fmt="x", italic=True)

    # ------------------------------------------------------------ Returns
    m.ctx = RT.name
    ry = lambda key: RT.c(key)
    RT.section("Exit")
    RT.one("n", "Holding period (years)", "=ExitYear", fmt="int", unit="years")
    RT.one("ebitda_in", "Entry LTM EBITDA", f"={cI_su('ltm')}", unit="$m")
    RT.one("ebitda_out", "Exit-year EBITDA", f"=INDEX({OP.rng('ebitda', H, NP - 1)},ExitYear)", unit="$m")
    RT.one("mult_in", "Entry EV / EBITDA", f"={cI_su('mult')}", fmt="x")
    RT.one("mult_out", "Exit EV / EBITDA", "=ExitMult", fmt="x")
    RT.one("ev_in", "Entry enterprise value", f"={cI_su('ev')}", unit="$m")
    RT.one("ev_out", "Exit enterprise value", f"={ry('mult_out')}*{ry('ebitda_out')}", unit="$m", bold=True, top=True)
    RT.one("debt_out", "(−) Total debt at exit (incl. accrued PIK)", f"=INDEX({DB.rng('debt', 1, F)},ExitYear)", unit="$m", indent=1)
    RT.one("cash_out", "(+) Cash at exit", f"=INDEX({DB.rng('cash', 1, F)},ExitYear)", unit="$m", indent=1)
    RT.one("nd_out", "Net debt at exit", f"={ry('debt_out')}-{ry('cash_out')}", unit="$m", indent=1)
    RT.one("pik_out", "of which accrued PIK notes", f"=INDEX({DB.rng('pik_end', 1, F)},ExitYear)", unit="$m", italic=True, indent=2)
    RT.one("eq_out", "Sponsor equity value at exit", f"={ry('ev_out')}-{ry('nd_out')}", unit="$m", bold=True, top=True)
    RT.one("eq_in", "Sponsor equity invested", f"={cI_su('s_eq')}", unit="$m", bold=True)
    RT.gap()
    RT.section("Returns")
    RT.one("mom", "Money multiple (MoM)", f"={ry('eq_out')}/{ry('eq_in')}", fmt=X2, bold=True)
    RT.one("irr", "IRR (closed form: MoM ^ (1 / years) − 1)", f"=IF({ry('mom')}>0,POWER({ry('mom')},1/{ry('n')})-1,-1)", fmt="pct", bold=True)
    RT.gap()
    RT.section("IRR cross-check (sponsor cash flows: entry and exit only)")
    RT.line("yr", "Year", lambda i: "=0" if i == 0 else f"={ref(RT.rows['yr'], C0 + i - 1)}+1", (0, F), fmt="int")
    RT.line("cf", "Sponsor cash flow", lambda i: f"=IF({ref(RT.rows['yr'], C0 + i)}=0,-{ry('eq_in')},IF({ref(RT.rows['yr'], C0 + i)}=ExitYear,{ry('eq_out')},0))", (0, F))
    RT.one("irr_x", "IRR() over the cash-flow strip", f"=IF({ry('eq_out')}>0,IFERROR(IRR({ref(RT.rows['cf'], C0)}:{ref(RT.rows['cf'], C0 + F)}),-1),-1)", fmt="pct")
    RT.one("irr_d", "Difference vs closed form", f"={ry('irr_x')}-{ry('irr')}", fmt=PCT2, italic=True)
    RT.gap()
    RT.section("Returns attribution (sums exactly to the sponsor equity gain)")
    RT.one("gain", "Sponsor equity gain", f"={ry('eq_out')}-{ry('eq_in')}", unit="$m", bold=True)
    RT.line("a_ebitda", "EBITDA growth (at the entry multiple)", lambda i: f"=({ry('ebitda_out')}-{ry('ebitda_in')})*{ry('mult_in')}", (0, 0), indent=1, unit="$m",
            extra={1: (f"=C{RT.r}/{ry('gain')}", "pct")})
    RT.line("a_mult", "Multiple expansion / (contraction) (on exit EBITDA)", lambda i: f"=({ry('mult_out')}-{ry('mult_in')})*{ry('ebitda_out')}", (0, 0), indent=1, unit="$m",
            extra={1: (f"=C{RT.r}/{ry('gain')}", "pct")})
    RT.line("a_delev", "Debt paydown and cash generation (net debt reduction)", lambda i: f"={cI_su('net_debt_close')}-{ry('nd_out')}", (0, 0), indent=1, unit="$m",
            extra={1: (f"=C{RT.r}/{ry('gain')}", "pct")})
    RT.line("a_fees", "Fees and leakage", lambda i: f"=-{cI_su('fees')}", (0, 0), indent=1, unit="$m", extra={1: (f"=C{RT.r}/{ry('gain')}", "pct")})
    RT.line("a_sum", "Total attributed", lambda i: f"=SUM({ref(RT.rows['a_ebitda'], C0)}:{ref(RT.rows['a_fees'], C0)})", (0, 0), bold=True, top=True, unit="$m",
            extra={1: (f"=C{RT.r}/{ry('gain')}", "pct")})
    RT.one("a_diff", "Difference to equity gain", f"={ry('a_sum')}-{ry('gain')}", fmt="num2", italic=True)

    # Sources & Uses carries the closing net debt (after the transaction) for the attribution
    m.ctx = SU.name
    SU.gap()
    SU.one("net_debt_close", "Net debt at close (new debt less minimum cash)", f"={cI('s_debt')}-{cI('u_cash')}", unit="$m")

    # ------------------------------------------------------------ Checks
    m.ctx = CK.name
    ok = lambda cond: f'=IF({cond},"OK","ERROR")'
    ckc = lambda key: CK.c(key)
    CK.section("Transaction")
    CK.one("c_su", "Sources equal uses", ok(f"ABS({cI_su(tot_s)}-{cI_su(tot_u)})<Tol"), fmt="text")
    CK.one("c_eq", "Sponsor equity is positive", ok(f"{cI_su('s_eq')}>0"), fmt="text")
    CK.one("c_lev", "Total leverage at close within the maximum", ok(f"{DB.at('lev', 0)}<=MaxLev+Tol"), fmt="text")
    CK.one("c_ev", "Entry EV ties to the pricing method",
           ok(f"IF(EntryMode=2,ABS({cI_su('ev')}-EntryMult*{cI_su('ltm')})<Tol,ABS({cI_su('ev')}-{cI_su('eq_price')}-{cI_su('net_debt')})<Tol)"), fmt="text")
    CK.section("Every projection year")
    CK.line("c_rev", "Revolver balance is not negative", lambda t: ok(f"{DB.at('rev_end', t)}>=-Tol"), T, fmt="text")
    CK.line("c_tlb", "Term loan B balance is not negative", lambda t: ok(f"{DB.at('tlb_end', t)}>=-Tol"), T, fmt="text")
    CK.line("c_pik", "PIK balance is not negative", lambda t: ok(f"{DB.at('pik_end', t)}>=-Tol"), T, fmt="text")
    CK.line("c_cash", "Cash at or above the minimum", lambda t: ok(f"{DB.at('cash', t)}>=MinCash-Tol"), T, fmt="text")
    CK.line("c_pikroll", "PIK accrues at the PIK rate", lambda t: ok(f"ABS({DB.at('pik_end', t)}-{DB.at('pik_open', t)}*(1+PikRate))<Tol"), T, fmt="text")
    CK.line("c_roll", "Cash roll: closing = opening + levered FCF − debt repaid + revolver draw",
            lambda t: ok(f"ABS({DB.at('cash', t)}-{DB.at('cash', t - 1)}-{OP.at('lfcf', P(t))}+{DB.at('tlb_mand', t)}+{DB.at('tlb_sweep', t)}-{DB.at('rev_chg', t)})<Tol"), T, fmt="text")
    CK.section("Returns")
    CK.one("c_irr", "Closed-form IRR agrees with IRR() on the cash-flow strip", ok(f"ABS({RT.c('irr_d')})<TolIRR"), fmt="text")
    CK.one("c_attr", "Attribution sums to the sponsor equity gain", ok(f"ABS({RT.c('a_diff')})<Tol"), fmt="text")
    CK.one("c_eq_out", "Exit equity = exit EV less net debt", ok(f"ABS({RT.c('eq_out')}-{RT.c('ev_out')}+{RT.c('nd_out')})<Tol"), fmt="text")
    CK.gap()
    CK.line("master", "MASTER CHECK", None, None, bold=True, fmt="text")

    # ------------------------------------------------------------ render
    for g in (FL, A, SU, OP, DB, RT, CK):
        g.render()
    m.ctx = "Assumptions"
    # table headers on the tranche block are text; fix colours on the header row
    a = A.sh
    for i in range(5):
        c = a.cells.get((A.rows["tr_head"], C0 + i))
        if c:
            a.set((A.rows["tr_head"], C0 + i), c.value, kind="text", bold=True, align="right")
    for i in range(NP):
        a.set((A.rows["hdr"], C0 + i), labels_all[i], kind="text", bold=True, align="right")
    for key, spec in (("t_rev", (("RevX", "x"), ("RevRate", "pct"))), ("t_tlb", (("TlbX", "x"), ("TlbRate", "pct"), None, ("TlbAmort", "pct"), ("TlbSweep", "pct"))),
                      ("t_sn", (("SnX", "x"), ("SnRate", "pct"))), ("t_pik", (("PikX", "x"), None, ("PikRate", "pct")))):
        for i, sp in enumerate(spec):
            if sp is None:
                continue
            cell = a.cells[(A.rows[key], C0 + i)]
            a.set((A.rows[key], C0 + i), cell.value, fmt=sp[1], kind="input")
            wb.define(sp[0], "Assumptions", ref(A.rows[key], C0 + i))
    a.width("A", 62)

    # Filings: comments and links
    for k in stm.LINES:
        r = FL.rows[k]
        for p in range(H):
            it = s.data[k][p]
            if it.value is not None:
                cell = FL.sh.cells[(r, C0 + p)]
                cell.comment, cell.link = it.source(), s.filings[p]["url"] or None
    for p in range(H):
        cell = FL.sh.cells.get((FL.rows["filing"], C0 + p))
        if cell and s.filings[p]["url"]:
            cell.link = s.filings[p]["url"]

    # Checks: tolerances and master
    ck = CK.sh
    top, bot = CK.rows["c_su"], CK.rows["c_eq_out"]
    first, lastc = col_letter(C0), col_letter(C0 + F)
    tr0 = CK.rows["master"] + 2
    ck.set((tr0, 1), "Tolerances", bold=True, color=NAVY, bottom=True)
    for i, (nm, label, v, fmt) in enumerate((("Tol", "Rounding tolerance ($m)", 0.01, "num2"), ("TolIRR", "IRR cross-check tolerance", 0.0001, PCT2))):
        ck.set((tr0 + 1 + i, 1), label, indent=1)
        ck.set((tr0 + 1 + i, C0), v, fmt=fmt)
        wb.define(nm, "Checks", ref(tr0 + 1 + i, C0))
    rng = f"{first}{top}:{lastc}{bot}"
    ck.set((CK.rows["master"], C0), f'=IF(AND(COUNTIF({rng},"ERROR")=0,SUMPRODUCT(--ISERROR({rng}))=0,COUNTIF({rng},"OK")>0),"OK","ERROR")', bold=True)
    ck.ok_error(rng)
    ck.ok_error(f"{first}{CK.rows['master']}")

    centres = _sensitivity(m, SE, A, SU, OP, DB, RT)
    _cover(m, cover, SU, RT, CK, DB, d)
    order = ["Cover", "Assumptions", "Sources & Uses", "Operations", "Debt", "Returns", "Sensitivity", "Checks", "Filings"]
    wb.sheets.sort(key=lambda sh: order.index(sh.name))
    from .formula import calculate_workbook
    eng = calculate_workbook(wb)

    rrow = lambda key: RT.rows[key]
    out = lambda id_, g, key, units, label: {"id": id_, "sheet": g.name, "ref": ref(g.rows[key], C0), "units": units, "label": label}
    meta = {
        "model": "lbo", "ticker": s.ticker, "name": s.name, "converged": eng.converged, "iterations": eng.iterations, "warnings": s.warnings,
        "centres": centres, "years": [y.isoformat() for y in s.years], "projection_years": F, "defaults": d, "market": dict(market),
        "rows": {g.name: g.rows for g in (A, SU, OP, DB, RT, CK, FL)},
        "outputs": [
            out("lbo.irr", RT, "irr", "%", "Sponsor IRR"),
            out("lbo.mom", RT, "mom", "x", "Money multiple (MoM)"),
            out("lbo.entry_ev", SU, "ev", "USD m", "Entry enterprise value"),
            out("lbo.exit_ev", RT, "ev_out", "USD m", "Exit enterprise value"),
            out("lbo.sponsor_equity", SU, "s_eq", "USD m", "Sponsor equity invested"),
            {"id": "lbo.total_leverage_entry", "sheet": "Debt", "ref": ref(DB.rows["lev"], C0), "units": "x", "label": "Total debt / EBITDA at close"},
            out("lbo.attr_ebitda_growth", RT, "a_ebitda", "USD m", "Value created by EBITDA growth"),
            out("lbo.attr_multiple", RT, "a_mult", "USD m", "Value created by multiple expansion"),
            out("lbo.attr_deleveraging", RT, "a_delev", "USD m", "Value created by debt paydown and cash generation"),
        ],
        "plants": {"sweep": f"Debt!{ref(DB.rows['tlb_sweep'], C0 + 3)}", "pik": f"Debt!{ref(DB.rows['pik_acc'], C0 + 2)}",
                   "exit": f"Returns!{ref(RT.rows['ev_out'], C0)}"},
    }
    return wb, meta


# --------------------------------------------------------------------------- sensitivity
def _sensitivity(m: _M, sh, A: _G, SU: _G, OP: _G, DB: _G, RT: _G) -> None:
    s, H = m.s, m.H
    m.ctx = "Sensitivity"
    sh.set("A2", f"{s.name} — returns sensitivity", kind="title")
    sh.set("A3", "Live closed-form grids: entry multiple moves purchase price and fees, debt stays sized on EBITDA; exit cases hold the base debt paydown", kind="note")
    sh.set((5, 1), f"{s.currency} in millions", kind="header")
    for c in range(2, 9):
        sh.set((5, c), "", kind="header")
    sh.width("A", 50)
    sh.width("B", 8)
    for c in range(3, 9):
        sh.width(c, 12.5)
    sh.freeze = (6, 2)
    base = [
        ("ltm", "LTM EBITDA", f"={SU.c('ltm')}", "num1"),
        ("txn", "Transaction fee (% of EV)", "=TxnFee", "pct"),
        ("fin", "Financing fees", f"={SU.c('u_fin')}", "num1"),
        ("cash", "Minimum cash", "=MinCash", "num1"),
        ("debt", "Debt raised", f"={SU.c('s_debt')}", "num1"),
        ("e_in", "Sponsor equity invested (base)", f"={RT.c('eq_in')}", "num1"),
        ("m_in", "Entry EV / EBITDA (base)", f"={RT.c('mult_in')}", "x"),
        ("m_out", "Exit EV / EBITDA (base)", "=ExitMult", "x"),
        ("x_ebitda", "Exit-year EBITDA", f"={RT.c('ebitda_out')}", "num1"),
        ("x_rev", "Exit-year revenue", f"=INDEX({OP.rng('rev', H, H + F - 1)},ExitYear)", "num1"),
        ("x_mg", "Exit-year EBITDA margin (base)", None, "pct"),
        ("x_nd", "Net debt at exit (base)", f"={RT.c('nd_out')}", "num1"),
        ("n", "Holding period (years)", "=ExitYear", "int"),
    ]
    sh.set((7, 1), "Base values (linked)", bold=True, color=NAVY, bottom=True)
    for c in range(2, 9):
        sh.set((7, c), "", bottom=True)
    B = {}
    for i, (k, label, f, fmt) in enumerate(base):
        r = 8 + i
        B[k] = f"$C${r}"
        sh.set((r, 1), label, indent=1)
        sh.set((r, 3), f if f else f"={B['x_ebitda']}/{B['x_rev']}", fmt=fmt)
    r0 = 8 + len(base) + 1

    def grid(r, title, row_label, col_label, rows_hdr, cols_hdr, cell, fmt, hfmt_r, hfmt_c):
        sh.set((r, 1), title, bold=True, color=NAVY, bottom=True)
        for c in range(2, 9):
            sh.set((r, c), "", bottom=True)
        sh.set((r + 1, 1), f"Rows: {row_label}; columns: {col_label}", kind="note")
        for j, f in enumerate(cols_hdr):
            sh.set((r + 1, 4 + j), f, fmt=hfmt_c, bold=True, align="right", bottom=True)
        for i, f in enumerate(rows_hdr):
            rr = r + 2 + i
            sh.set((rr, 3), f, fmt=hfmt_r, bold=True)
            for j in range(5):
                cc = col_letter(4 + j)
                sh.set((rr, 4 + j), cell(f"$C{rr}", f"{cc}${r + 1}"), fmt=fmt, bold=(i == 2 and j == 2), fill="E8EEF7" if (i == 2 and j == 2) else None)
        return r + 8

    ladder = lambda b, st: [f"={b}-2*{st}", f"={b}-{st}", f"={b}", f"={b}+{st}", f"={b}+2*{st}"]
    e_in = lambda x: f"({x}*{B['ltm']}*(1+{B['txn']})+{B['fin']}+{B['cash']}-{B['debt']})"
    e_out = lambda y: f"({y}*{B['x_ebitda']}-{B['x_nd']})"
    irr = lambda mom: f"IF({mom}>0,POWER({mom},1/{B['n']})-1,-1)"
    r = grid(r0, "IRR: entry multiple against exit multiple", "entry EV / LTM EBITDA", "exit EV / EBITDA",
             ladder(B["m_in"], "EntryStep"), ladder(B["m_out"], "ExitStep"),
             lambda x, y: "=" + irr(f"{e_out(y)}/{e_in(x)}"), "pct", "x", "x")
    r = grid(r, "Money multiple: entry multiple against exit multiple", "entry EV / LTM EBITDA", "exit EV / EBITDA",
             ladder(B["m_in"], "EntryStep"), ladder(B["m_out"], "ExitStep"),
             lambda x, y: f"={e_out(y)}/{e_in(x)}", X2, "x", "x")
    e_out2 = lambda y, mg: f"({y}*{B['x_rev']}*{mg}-{B['x_nd']})"
    grid(r, "IRR: exit multiple against exit-year EBITDA margin (debt paydown held at base)", "exit EV / EBITDA", "exit-year EBITDA margin",
         ladder(B["m_out"], "ExitStep"), ladder(B["x_mg"], "MarginStep"),
         lambda y, mg: "=" + irr(f"{e_out2(y, mg)}/{B['e_in']}"), "pct", "x", "pct")
    m.ctx = ""
    # remember where the centre cells sit, for tests and the bench
    return {"irr": f"F{r0 + 4}", "mom": f"F{r0 + 12}", "margin_irr": f"F{r0 + 20}"}


# --------------------------------------------------------------------------- cover
def _cover(m: _M, sh, SU: _G, RT: _G, CK: _G, DB: _G, d: dict) -> None:
    s = m.s
    m.ctx = "Cover"
    sh.width("A", 3)
    sh.width("B", 44)
    sh.width("C", 18)
    sh.width("D", 40)
    sh.set("B2", f"{s.name} ({s.ticker}) — take-private LBO", kind="title", size=18)
    sh.set("B3", "Leveraged buyout model built from SEC filings; every number is written by code", kind="note")
    sh.set("B5", "Units", bold=True)
    sh.set("C5", f"{s.currency} in millions, except per-share data")
    sh.set("B6", "Actuals", bold=True)
    sh.set("C6", f"FY{s.years[0].year}–FY{s.years[-1].year} ({len(s.years)} fiscal years)")
    sh.set("B7", "Projection", bold=True)
    sh.set("C7", f"FY{s.years[-1].year + 1}–FY{s.years[-1].year + F}")
    sh.set("B8", "Entry pricing", bold=True)
    sh.set("C8", '=IF(EntryMode=1,"Premium to current price","EV / LTM EBITDA multiple")')
    sh.set("B9", "Interest circularity", bold=True)
    sh.set("C9", '=IF(Circ=1,"On (average balances, iterative)","Off (opening balances)")')
    sh.set("B10", "MASTER CHECK", bold=True)
    sh.set("C10", f"={CK.at('master', 0)}", bold=True)
    sh.ok_error("C10")
    sh.set("B12", "Key returns", bold=True, color=NAVY, bottom=True)
    sh.set("C12", "", bottom=True)
    rows = [("Sponsor IRR", RT.c("irr"), "pct"), ("Money multiple (MoM)", RT.c("mom"), X2),
            ("Entry enterprise value", SU.c("ev"), "num0"), ("Entry EV / LTM EBITDA", SU.c("mult"), "x"),
            ("Offer price per share ($)", SU.c("offer"), "usd2"), ("Sponsor equity invested", SU.c("s_eq"), "num0"),
            ("Total debt / EBITDA at close", DB.at("lev", 0), "x"), ("Exit enterprise value", RT.c("ev_out"), "num0"),
            ("Sponsor equity value at exit", RT.c("eq_out"), "num0")]
    for i, (label, f, fmt) in enumerate(rows):
        sh.set((13 + i, 2), label)
        sh.set((13 + i, 3), f"={f}", fmt=fmt, bold=i < 2)
    r = 13 + len(rows) + 1
    sh.set((r, 2), "Colour code", bold=True, color=NAVY, bottom=True)
    sh.set((r + 1, 2), "Hard-coded input or figure as filed", color=BLUE)
    sh.set((r + 2, 2), "Formula on this sheet")
    sh.set((r + 3, 2), "Link to another sheet", color=GREEN)
    r += 5
    sh.set((r, 2), "Contents", bold=True, color=NAVY, bottom=True)
    for i, (name, what) in enumerate([("Assumptions", "every input: pricing, fees, tranches, drivers, exit, switches"),
                                      ("Sources & Uses", "purchase price, fees, tranches and the sponsor equity plug"),
                                      ("Operations", "historicals and the five-year operating build to levered FCF"),
                                      ("Debt", "revolver, term loan B with sweep, senior notes, PIK; credit statistics"),
                                      ("Returns", "exit value, MoM, IRR and returns attribution"),
                                      ("Sensitivity", "live IRR and MoM grids"),
                                      ("Checks", "integrity checks and the master check"),
                                      ("Filings", "every historical figure as filed, with its source")]):
        sh.set((r + 1 + i, 2), name, link=f"'{name}'!A1", color=BLUE, underline=True)
        sh.set((r + 1 + i, 3), what, kind="note")
    r += 11
    sh.set((r, 2), "Sources", bold=True, color=NAVY, bottom=True)
    sh.set((r + 1, 2), f"Share price: {d['_src']}", kind="note")
    for i, f in enumerate(s.filings):
        sh.set((r + 2 + i, 2), f"FY{f['end'][:4]}: {f['form']} filed {f['filed']}, accession {f['accn']}", link=f["url"] or None,
               color=BLUE if f["url"] else None, underline=bool(f["url"]))
    m.ctx = ""
