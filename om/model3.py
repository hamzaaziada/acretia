"""Integrated three-statement model + DCF, written by code from SEC filings.

Sheets (period columns line up on every sheet):
  Cover        company, units, sources, master check, key outputs, colour legend, contents
  Assumptions  scenario switch (Base / Upside / Downside), circularity switch, every forecast driver as a blue
               input, with the historical value of the same ratio beside it
  IS / BS / CF historical columns link to Filings; forecast columns are formulas only
  Schedules    PP&E roll-forward (capex, D&A on beginning PP&E) and working-capital days
  Debt         term debt, revolver that draws to hold minimum cash, interest on average balances
               (circularity on a 1/0 breaker; the workbook enables iterative calculation)
  DCF          unlevered FCF from the model, WACC (CAPM), both terminal-value methods, cross-checks,
               sensitivity tables
  Checks       balance sheet balances every period, cash ties, debt and revolver non-negative, minimum cash,
               historical EPS and gross profit tie to the filing; one master check
  Filings      every historical number as reported, blue, with a comment naming the XBRL concept, period, form,
               filing date and accession, and a link to the filing

Rules: no hard-coded number inside a formula (structural constants only: 0, 1, 0.5 for mid-year, 365 days);
every forecast row uses the same formula across all forecast years; the LLM never types a number here.
"""
from __future__ import annotations

from datetime import date

from . import statements as stm
from .xlsx import BLUE, GREEN, GREY, NAVY, Workbook, col_letter, quote_sheet, ref

F = 5                       # forecast years
FIRST = 8                   # first data row on statement sheets
C0 = 3                      # first period column (C)
LT_GROWTH = 0.03


class _Grid:
    def __init__(self, m: "_Model", name: str, tab: str | None, title: str, sub: str):
        self.m, self.name = m, name
        self.sh = m.wb.sheet(name, tab=tab)
        self.rows: dict[str, int] = {}
        self.specs: list = []
        self.r = FIRST
        self.title, self.sub = title, sub

    def section(self, title: str) -> None:
        self.specs.append(("section", self.r, title))
        self.r += 1

    def gap(self, n: int = 1) -> None:
        self.r += n

    def line(self, key: str, label: str, hist=None, fcst=None, *, fmt: str = "num0", bold: bool = False, top: bool = False,
             indent: int = 0, unit: str = "", italic: bool = False, kind: str | None = None) -> None:
        self.rows[key] = self.r
        self.specs.append(("line", self.r, key, label, hist, fcst, fmt, bold, top, indent, unit, italic, kind))
        self.r += 1

    def at(self, key: str, p: int, absolute_col: bool = False) -> str:
        a = ref(self.rows[key], C0 + p, abs_col=absolute_col)
        return a if self.m.ctx == self.name else f"{quote_sheet(self.name)}!{a}"

    def rng(self, key: str, p0: int, p1: int) -> str:
        a = f"{ref(self.rows[key], C0 + p0)}:{ref(self.rows[key], C0 + p1)}"
        return a if self.m.ctx == self.name else f"{quote_sheet(self.name)}!{a}"

    def render(self) -> None:
        m, sh = self.m, self.sh
        m.ctx = self.name
        sh.set("A2", self.title, kind="title")
        sh.set("A3", self.sub, kind="note")
        sh.set((5, 1), f"{m.s.currency} in millions", kind="header")
        sh.set((5, 2), "", kind="header")
        for p in range(m.H + F):
            sh.set((5, C0 + p), m.period_label(p), kind="header", align="right")
            sh.set((6, C0 + p), m.period_end(p), kind="note", align="right")
        sh.set((6, 1), "Fiscal year ending", kind="note")
        sh.width("A", 44)
        sh.width("B", 7)
        for p in range(m.H + F):
            sh.width(C0 + p, 11.5)
        sh.freeze = (6, 2)
        for spec in self.specs:
            if spec[0] == "section":
                _, r, title = spec
                sh.set((r, 1), title, bold=True, color=NAVY, bottom=True)
                for c in range(2, C0 + m.H + F):
                    sh.set((r, c), "", bottom=True)
                continue
            _, r, key, label, hist, fcst, fmt, bold, top, indent, unit, italic, kind = spec
            sh.set((r, 1), label, bold=bold, indent=indent, italic=italic, top=top, color=GREY if italic else None)
            if unit:
                sh.set((r, 2), unit, kind="note", top=top)
            elif top:
                sh.set((r, 2), "", top=top)
            for p in range(m.H + F):
                fn = hist if p < m.H else fcst
                v = fn(p) if callable(fn) else None
                if v is None:
                    if top:
                        sh.set((r, C0 + p), "", top=True)
                    continue
                k = kind
                if k is None and isinstance(v, (int, float)) and self.name != "Assumptions":
                    k = "hist"              # placeholder zeros on statement sheets: blue (hard-coded) but no input fill
                sh.set((r, C0 + p), v, fmt=fmt, bold=bold, top=top, italic=italic, kind=k)


class _Model:
    def __init__(self, s: stm.Statements):
        self.s = s
        self.H = len(s.years)
        self.wb = Workbook(iterate=True)
        self.ctx = ""

    # ------------------------------------------------------------ periods
    def period_label(self, p: int) -> str:
        if p < self.H:
            return f"FY{self.s.years[p].year}A"
        return f"FY{self.s.years[-1].year + p - self.H + 1}E"

    def period_end(self, p: int) -> str:
        if p < self.H:
            return self.s.years[p].isoformat()
        e = self.s.years[-1]
        try:
            return e.replace(year=e.year + p - self.H + 1).isoformat()
        except ValueError:
            return date(e.year + p - self.H + 1, e.month, 28).isoformat()

    def hist(self, p: int) -> bool:
        return p < self.H


# --------------------------------------------------------------------------- defaults from history
def _sd(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _avg(xs, n=3):
    xs = [x for x in xs if x is not None][-n:]
    return sum(xs) / len(xs) if xs else None


def _clamp(v, lo, hi, default):
    if v is None:
        return default
    return max(lo, min(hi, v))


def defaults(s: stm.Statements) -> dict:
    H = len(s.years)
    g = lambda k, i: s.get(k, i)
    rev = [g("revenue", i) for i in range(H)]
    cogs = [g("cogs", i) if g("cogs", i) is not None else (rev[i] - g("gross_profit", i) if g("gross_profit", i) is not None else 0) for i in range(H)]
    growth = [_sd(rev[i], rev[i - 1]) - 1 if i and _sd(rev[i], rev[i - 1]) else None for i in range(H)]
    y1 = _clamp(_avg(growth), -0.15, 0.40, 0.05)
    base_g = [y1 + (LT_GROWTH - y1) * t / (F - 1) for t in range(F)]
    gm = _clamp(_avg([1 - _sd(cogs[i], rev[i]) for i in range(H) if rev[i]]), -1, 1, 0.4)
    ebit = [g("ebit", i) for i in range(H)]
    other = [(ebit[i] - (rev[i] - cogs[i]) + (g("rd", i) or 0) + (g("sga", i) or 0)) if ebit[i] is not None else None for i in range(H)]
    pretax, tax = [g("pretax", i) for i in range(H)], [g("tax", i) for i in range(H)]
    ni = [g("net_income", i) for i in range(H)]
    tr = _clamp(_avg([_sd(tax[i], pretax[i]) for i in range(H) if (pretax[i] or 0) > 0]), 0, 0.35, 0.21)
    nci_ratio = _sd((ni[-1] - pretax[-1] + tax[-1]) if None not in (ni[-1], pretax[-1], tax[-1]) else None, pretax[-1])
    nci = 0.0 if nci_ratio is None or abs(nci_ratio) < 0.005 else _clamp(nci_ratio, -0.1, 0.1, 0.0)
    ppe = [g("ppe", i) for i in range(H)]
    da = [g("da", i) for i in range(H)]
    da_pct = _clamp(_sd(da[-1], ppe[-2]) if H > 1 else _sd(da[-1], ppe[-1]), 0.02, 0.6, 0.15)
    capex = _clamp(_avg([_sd(g("capex", i), rev[i]) for i in range(H)]), 0, 0.5, 0.04)
    last = H - 1
    dso = _clamp(_sd((g("ar", last) or 0) * 365, rev[last]), 0, 365, 30)
    dio = _clamp(_sd((g("inventory", last) or 0) * 365, cogs[last]), 0, 365, 0) if cogs[last] else 0
    dpo = _clamp(_sd((g("ap", last) or 0) * 365, cogs[last]), 0, 365, 30) if cogs[last] else _clamp(_sd((g("ap", last) or 0) * 365, rev[last]), 0, 365, 30)
    ca, cl = g("current_assets", last), g("current_liabilities", last)
    oca = _sd(ca - sum(g(k, last) or 0 for k in ("cash", "sti", "ar", "inventory")), rev[last]) if ca is not None else 0
    ocl = _sd(cl - (g("ap", last) or 0) - (g("debt_current", last) or 0), rev[last]) if cl is not None else 0
    sbc = _clamp(_sd(g("sbc", last), rev[last]), 0, 0.5, 0)
    payout = _clamp(_avg([_sd(g("dividends", i), ni[i]) for i in range(H) if (ni[i] or 0) > 0]), 0, 1.5, 0)
    buyback = _clamp(_avg([_sd(g("buybacks", i) or 0, ni[i]) for i in range(H) if (ni[i] or 0) > 0]), 0, 2, 0)
    sh = [g("diluted_shares", i) for i in range(H)]
    n = min(3, H - 1)
    share_chg = _clamp((sh[-1] / sh[-1 - n]) ** (1 / n) - 1 if n and sh[-1] and sh[-1 - n] else None, -0.05, 0.05, 0)
    debt = [(g("debt_current", i) or 0) + (g("debt_noncurrent", i) or 0) for i in range(H)]
    ie = [g("interest_expense", i) for i in range(H)]
    rate_d = None
    for i in range(H - 1, 0, -1):
        if ie[i] and debt[i] + debt[i - 1] > 0:
            rate_d = ie[i] / ((debt[i] + debt[i - 1]) / 2)
            break
    rate_d = _clamp(rate_d, 0.02, 0.12, 0.05)
    ii = [g("interest_income", i) for i in range(H)]
    cash_inv = [(g("cash", i) or 0) + (g("sti", i) or 0) for i in range(H)]
    rate_c = None
    for i in range(H - 1, 0, -1):
        if ii[i] and cash_inv[i] + cash_inv[i - 1] > 0:
            rate_c = ii[i] / ((cash_inv[i] + cash_inv[i - 1]) / 2)
            break
    rate_c = _clamp(rate_c, 0, 0.06, 0.03)
    min_cash = _clamp(_sd(g("cash", last), rev[last]), 0.01, 0.05, 0.02)
    return {
        "growth": (base_g, [x + 0.02 for x in base_g], [x - 0.03 for x in base_g]),
        "gm": ([gm] * F, [gm + 0.01] * F, [gm - 0.015] * F),
        "rd": [_clamp(_sd(g("rd", last), rev[last]), 0, 1, 0)] * F,
        "sga": [_clamp(_sd(g("sga", last), rev[last]), 0, 1, 0)] * F,
        "other": [_clamp(_avg([-_sd(o, r) for o, r in zip(other, rev) if o is not None and r]), -0.5, 0.5, 0)] * F,
        "nonop": [0.0] * F, "tax": [tr] * F, "nci": [nci] * F, "da": [da_pct] * F, "capex": [capex] * F,
        "dso": [dso] * F, "dio": [dio] * F, "dpo": [dpo] * F, "oca": [_clamp(oca, -0.5, 1, 0)] * F, "ocl": [_clamp(ocl, -0.5, 1, 0)] * F,
        "sbc": [sbc] * F, "payout": [payout] * F, "buyback": [buyback] * F, "shares": [share_chg] * F,
        "repay": [0.0] * F, "issue": [0.0] * F, "rate_debt": [rate_d] * F, "rate_rev": [rate_d + 0.01] * F,
        "rate_cash": [rate_c] * F, "min_cash": [min_cash] * F,
    }


# --------------------------------------------------------------------------- builder
class UnsupportedCompany(ValueError):
    pass


def build(s: stm.Statements, *, assumptions: dict | None = None, circ: int = 1, scenario: int = 1) -> tuple[bytes, dict]:
    wb, meta = build_workbook(s, assumptions=assumptions, circ=circ, scenario=scenario)
    return wb.to_bytes(), meta


def build_workbook(s: stm.Statements, *, assumptions: dict | None = None, circ: int = 1, scenario: int = 1):
    """The model as an om.xlsx.Workbook (calculated), plus metadata: row map, defaults, warnings."""
    if s.financial_format:
        raise UnsupportedCompany(f"{s.ticker} reports a bank/insurer balance sheet; the three-statement model needs a classified balance sheet.")
    if len(s.years) < 2:
        raise UnsupportedCompany(f"{s.ticker}: need at least two fiscal years of filings.")
    last = len(s.years) - 1
    missing = [s.label(k) for k in ("revenue", "ebit", "pretax", "net_income", "assets", "current_assets", "current_liabilities", "cfo", "cfi", "cff")
               if s.get(k, last) is None]
    if s.get("current_assets", last) is None and s.get("current_liabilities", last) is None:
        raise UnsupportedCompany(f"{s.ticker} files an unclassified balance sheet (typical of banks, insurers and brokers); "
                                 "those need a balance-sheet-driven model (deposits, loans, capital ratios), which isn't built yet.")
    if missing:
        raise UnsupportedCompany(f"{s.ticker}: the latest filing doesn't tag {', '.join(missing)}; can't build a tied model.")
    d = defaults(s)
    if assumptions:
        d.update(assumptions)
    m = _Model(s)
    H, wb = m.H, m.wb
    P = range(H + F)
    years = f"fiscal years {s.years[0].year}–{s.years[-1].year} actual, {s.years[-1].year + 1}–{s.years[-1].year + F} forecast"
    cover = wb.sheet("Cover", tab=NAVY)
    A = _Grid(m, "Assumptions", BLUE, "Assumptions and scenarios", "Blue cells are inputs. Grey columns show the same ratio in the actuals for reference.")
    IS = _Grid(m, "IS", None, f"{s.name} — income statement", years)
    BS = _Grid(m, "BS", None, f"{s.name} — balance sheet", years)
    CF = _Grid(m, "CF", None, f"{s.name} — cash flow statement", years)
    SC = _Grid(m, "Schedules", None, "Supporting schedules", "PP&E roll-forward and working capital")
    DT = _Grid(m, "Debt", None, "Debt, revolver and interest", "Revolver draws to keep minimum cash; interest on average balances when the circularity switch is on")
    DCF = wb.sheet("DCF", tab=GREEN)
    CK = _Grid(m, "Checks", "C00000", "Model checks", "Every check must read OK; the master check feeds the cover")
    FL = _Grid(m, "Filings", GREY, f"{s.name} — figures as filed with the SEC", "Blue = as reported (XBRL), $m. Hover for the concept, period and accession; click to open the filing.")

    h = lambda p: p < H
    prev = lambda p: p - 1

    # ------------------------------------------------------------ Filings (all hard-coded historicals live here)
    FL.section("As reported")
    for k, (stmt, kind, sign, label, chain) in stm.LINES.items():
        fmt = "usd2" if k == "eps_diluted" else ("num1" if k == "diluted_shares" else "num0")

        def hv(p, k=k):
            if p >= H:
                return None
            it = s.data[k][p]
            if it.value is None:
                return None
            return it.value

        FL.line(k, f"{stmt} · {label}", hv, None, fmt=fmt, kind="hist")
    FL.gap()
    FL.line("liab_total", "BS · Total liabilities (reported, or L&E less equity)", lambda p: (
        f"={FL.at('liabilities', p)}" if s.get("liabilities", p) is not None else
        f"={FL.at('liabilities_equity', p)}-{FL.at('equity_total' if s.get('equity_total', p) is not None else 'equity_parent', p)}") if p < H else None,
        None, fmt="num0")
    FL.line("filing", "Source filing", lambda p: s.filings[p]["form"] + " " + s.filings[p]["accn"] if p < H else None, None, fmt="text", kind="text")

    # ------------------------------------------------------------ Assumptions
    A.section("Switches")
    A.line("scenario_note", "Scenario: 1 = Base, 2 = Upside, 3 = Downside", None, None)
    A.line("circ_note", "Interest on average balances (circularity): 1 = on, 0 = off", None, None)
    A.gap()

    def inputs(key, label, vals, fmt="pct", hist_ratio=None, unit=""):
        A.line(key, label, (lambda p: hist_ratio(p)) if hist_ratio else None,
               lambda p, vals=vals: float(vals[p - H]), fmt=fmt, unit=unit, indent=1)

    def scen(key, label, triple, hist_ratio, fmt="pct"):
        A.line(key, label, hist_ratio, lambda p: f"=CHOOSE(Scenario,{A.at(key + '_b', p)},{A.at(key + '_u', p)},{A.at(key + '_d', p)})", fmt=fmt, bold=True)
        for suffix, name, vals in zip("bud", ("Base", "Upside", "Downside"), triple):
            A.line(f"{key}_{suffix}", name, None, lambda p, vals=vals: float(vals[p - H]), fmt=fmt, indent=2)

    A.section("Revenue and margins (scenario-driven)")
    scen("growth", "Revenue growth", d["growth"], lambda p: f"={IS.at('rev', p)}/{IS.at('rev', p - 1)}-1" if p else None)
    scen("gm", "Gross margin", d["gm"], lambda p: f"={IS.at('gp', p)}/{IS.at('rev', p)}")
    A.section("Operating costs (% of revenue)")
    inputs("rd", "R&D", d["rd"], hist_ratio=lambda p: f"=-{IS.at('rd', p)}/{IS.at('rev', p)}")
    inputs("sga", "SG&A", d["sga"], hist_ratio=lambda p: f"=-{IS.at('sga', p)}/{IS.at('rev', p)}")
    inputs("other", "Other operating expense", d["other"], hist_ratio=lambda p: f"=-{IS.at('other_op', p)}/{IS.at('rev', p)}")
    A.section("Below operating income")
    inputs("nonop", "Other non-operating income (% of revenue)", d["nonop"], hist_ratio=lambda p: f"={IS.at('nonop', p)}/{IS.at('rev', p)}")
    inputs("tax", "Tax rate (% of pre-tax income)", d["tax"], hist_ratio=lambda p: f"=IF({IS.at('pretax', p)}=0,0,-{IS.at('tax', p)}/{IS.at('pretax', p)})")
    inputs("nci", "Minority interest & other (% of pre-tax income)", d["nci"], hist_ratio=lambda p: f"=IF({IS.at('pretax', p)}=0,0,{IS.at('nci', p)}/{IS.at('pretax', p)})")
    inputs("shares", "Change in diluted share count", d["shares"], hist_ratio=lambda p: f"={IS.at('shares', p)}/{IS.at('shares', p - 1)}-1" if p else None)
    A.section("Capital and working capital")
    inputs("capex", "Capex (% of revenue)", d["capex"], hist_ratio=lambda p: f"=-{CF.at('capex', p)}/{IS.at('rev', p)}")
    inputs("da", "D&A (% of beginning PP&E)", d["da"], hist_ratio=lambda p: f"={CF.at('da', p)}/{BS.at('ppe', p - 1)}" if p else None)
    inputs("dso", "Receivable days (DSO)", d["dso"], fmt="days", unit="days", hist_ratio=lambda p: f"={BS.at('ar', p)}/{IS.at('rev', p)}*365")
    inputs("dio", "Inventory days (DIO)", d["dio"], fmt="days", unit="days", hist_ratio=lambda p: f"=IF({IS.at('cogs', p)}=0,0,-{BS.at('inv', p)}/{IS.at('cogs', p)}*365)")
    inputs("dpo", "Payable days (DPO)", d["dpo"], fmt="days", unit="days", hist_ratio=lambda p: f"=IF({IS.at('cogs', p)}=0,0,-{BS.at('ap', p)}/{IS.at('cogs', p)}*365)")
    inputs("oca", "Other current assets (% of revenue)", d["oca"], hist_ratio=lambda p: f"={BS.at('oca', p)}/{IS.at('rev', p)}")
    inputs("ocl", "Other current liabilities (% of revenue)", d["ocl"], hist_ratio=lambda p: f"={BS.at('ocl', p)}/{IS.at('rev', p)}")
    inputs("sbc", "Stock-based compensation (% of revenue)", d["sbc"], hist_ratio=lambda p: f"={CF.at('sbc', p)}/{IS.at('rev', p)}")
    A.section("Shareholder returns (% of net income)")
    inputs("payout", "Dividends", d["payout"], hist_ratio=lambda p: f"=IF({IS.at('ni', p)}<=0,0,-{CF.at('div', p)}/{IS.at('ni', p)})")
    inputs("buyback", "Share repurchases", d["buyback"], hist_ratio=lambda p: f"=IF({IS.at('ni', p)}<=0,0,-{CF.at('bb', p)}/{IS.at('ni', p)})")
    A.section("Financing")
    inputs("repay", "Term debt repaid (% of opening balance)", d["repay"])
    inputs("issue", "New term debt issued ($m)", d["issue"], fmt="num0")
    inputs("rate_debt", "Interest rate on term debt", d["rate_debt"])
    inputs("rate_rev", "Interest rate on revolver", d["rate_rev"])
    inputs("rate_cash", "Interest earned on cash & investments", d["rate_cash"])
    inputs("min_cash", "Minimum cash (% of revenue)", d["min_cash"])

    # ------------------------------------------------------------ Income statement
    fl = lambda k, sign=1: (lambda p: (f"={'-' if sign < 0 else ''}{FL.at(k, p)}" if s.get(k, p) is not None else None) if p < H else None)
    IS.section("Income statement")
    IS.line("rev", "Revenue", fl("revenue"), lambda p: f"={IS.at('rev', p - 1)}*(1+{A.at('growth', p)})", bold=True)
    IS.line("rev_g", "% growth", lambda p: f"={IS.at('rev', p)}/{IS.at('rev', p - 1)}-1" if p else None,
            lambda p: f"={IS.at('rev', p)}/{IS.at('rev', p - 1)}-1", fmt="pct", italic=True, indent=1)
    IS.line("cogs", "Cost of revenue", lambda p: (f"=-{FL.at('cogs', p)}" if s.get("cogs", p) is not None else
                                                 (f"=-({FL.at('revenue', p)}-{FL.at('gross_profit', p)})" if s.get("gross_profit", p) is not None else None)),
            lambda p: f"=-{IS.at('rev', p)}*(1-{A.at('gm', p)})")
    IS.line("gp", "Gross profit", lambda p: f"={IS.at('rev', p)}+{IS.at('cogs', p)}", lambda p: f"={IS.at('rev', p)}+{IS.at('cogs', p)}", bold=True, top=True)
    IS.line("gm", "% margin", lambda p: f"={IS.at('gp', p)}/{IS.at('rev', p)}", lambda p: f"={IS.at('gp', p)}/{IS.at('rev', p)}", fmt="pct", italic=True, indent=1)
    IS.line("rd", "Research & development", fl("rd", -1), lambda p: f"=-{IS.at('rev', p)}*{A.at('rd', p)}", indent=1)
    IS.line("sga", "Selling, general & administrative", fl("sga", -1), lambda p: f"=-{IS.at('rev', p)}*{A.at('sga', p)}", indent=1)
    IS.line("other_op", "Other operating income / (expense)", lambda p: f"={FL.at('ebit', p)}-{IS.at('gp', p)}-{IS.at('rd', p)}-{IS.at('sga', p)}",
            lambda p: f"=-{IS.at('rev', p)}*{A.at('other', p)}", indent=1)
    IS.line("ebit", "Operating income (EBIT)", lambda p: f"={IS.at('gp', p)}+{IS.at('rd', p)}+{IS.at('sga', p)}+{IS.at('other_op', p)}",
            lambda p: f"={IS.at('gp', p)}+{IS.at('rd', p)}+{IS.at('sga', p)}+{IS.at('other_op', p)}", bold=True, top=True)
    IS.line("ebit_m", "% margin", lambda p: f"={IS.at('ebit', p)}/{IS.at('rev', p)}", lambda p: f"={IS.at('ebit', p)}/{IS.at('rev', p)}", fmt="pct", italic=True, indent=1)
    IS.line("int_exp", "Interest expense", fl("interest_expense", -1), lambda p: f"=-{DT.at('int_total', p)}", indent=1)
    IS.line("int_inc", "Interest income", fl("interest_income"), lambda p: f"={DT.at('int_cash', p)}", indent=1)
    IS.line("nonop", "Other non-operating income / (expense)",
            lambda p: f"={FL.at('pretax', p)}-{IS.at('ebit', p)}-{IS.at('int_exp', p)}-{IS.at('int_inc', p)}",
            lambda p: f"={IS.at('rev', p)}*{A.at('nonop', p)}", indent=1)
    IS.line("pretax", "Pre-tax income", lambda p: f"=SUM({IS.at('ebit', p)},{IS.at('int_exp', p)}:{IS.at('nonop', p)})",
            lambda p: f"=SUM({IS.at('ebit', p)},{IS.at('int_exp', p)}:{IS.at('nonop', p)})", bold=True, top=True)
    IS.line("tax", "Income tax", fl("tax", -1), lambda p: f"=-{IS.at('pretax', p)}*{A.at('tax', p)}", indent=1)
    IS.line("nci", "Minority interest & other", lambda p: f"={FL.at('net_income', p)}-{IS.at('pretax', p)}-{IS.at('tax', p)}",
            lambda p: f"={IS.at('pretax', p)}*{A.at('nci', p)}", indent=1)
    IS.line("ni", "Net income to common shareholders", lambda p: f"={IS.at('pretax', p)}+{IS.at('tax', p)}+{IS.at('nci', p)}",
            lambda p: f"={IS.at('pretax', p)}+{IS.at('tax', p)}+{IS.at('nci', p)}", bold=True, top=True)
    IS.gap()
    IS.line("shares", "Diluted weighted shares (m)", fl("diluted_shares"), lambda p: f"={IS.at('shares', p - 1)}*(1+{A.at('shares', p)})", fmt="num1")
    IS.line("eps", "Diluted EPS", lambda p: f"={IS.at('ni', p)}/{IS.at('shares', p)}", lambda p: f"={IS.at('ni', p)}/{IS.at('shares', p)}", fmt="usd2", bold=True)
    IS.gap()
    IS.section("Memo")
    IS.line("da", "Depreciation & amortization", lambda p: f"={CF.at('da', p)}", lambda p: f"={CF.at('da', p)}")
    IS.line("ebitda", "EBITDA", lambda p: f"={IS.at('ebit', p)}+{IS.at('da', p)}", lambda p: f"={IS.at('ebit', p)}+{IS.at('da', p)}", bold=True)
    IS.line("ebitda_m", "% margin", lambda p: f"={IS.at('ebitda', p)}/{IS.at('rev', p)}", lambda p: f"={IS.at('ebitda', p)}/{IS.at('rev', p)}", fmt="pct", italic=True, indent=1)

    # ------------------------------------------------------------ Balance sheet
    same = lambda g, k: (lambda p: f"={g.at(k, p - 1)}")
    BS.section("Assets")
    BS.line("cash", "Cash & equivalents", fl("cash"), lambda p: f"={CF.at('end_cash', p)}", indent=1)
    BS.line("sti", "Short-term investments", fl("sti"), same(BS, "sti"), indent=1)
    BS.line("ar", "Accounts receivable", fl("ar"), lambda p: f"={IS.at('rev', p)}*{A.at('dso', p)}/365", indent=1)
    BS.line("inv", "Inventory", fl("inventory"), lambda p: f"=-{IS.at('cogs', p)}*{A.at('dio', p)}/365", indent=1)
    BS.line("oca", "Other current assets", lambda p: f"={FL.at('current_assets', p)}-SUM({BS.at('cash', p)}:{BS.at('inv', p)})",
            lambda p: f"={IS.at('rev', p)}*{A.at('oca', p)}", indent=1)
    BS.line("tca", "Total current assets", lambda p: f"=SUM({BS.at('cash', p)}:{BS.at('oca', p)})", lambda p: f"=SUM({BS.at('cash', p)}:{BS.at('oca', p)})", bold=True, top=True)
    BS.line("ppe", "PP&E, net", fl("ppe"), lambda p: f"={SC.at('ppe_end', p)}", indent=1)
    BS.line("gw", "Goodwill", fl("goodwill"), same(BS, "gw"), indent=1)
    BS.line("intang", "Intangible assets", fl("intangibles"), same(BS, "intang"), indent=1)
    BS.line("onca", "Other non-current assets", lambda p: f"={FL.at('assets', p)}-{BS.at('tca', p)}-SUM({BS.at('ppe', p)}:{BS.at('intang', p)})",
            same(BS, "onca"), indent=1)
    BS.line("ta", "Total assets", lambda p: f"={BS.at('tca', p)}+SUM({BS.at('ppe', p)}:{BS.at('onca', p)})",
            lambda p: f"={BS.at('tca', p)}+SUM({BS.at('ppe', p)}:{BS.at('onca', p)})", bold=True, top=True)
    BS.gap()
    BS.section("Liabilities and equity")
    BS.line("ap", "Accounts payable", fl("ap"), lambda p: f"=-{IS.at('cogs', p)}*{A.at('dpo', p)}/365", indent=1)
    BS.line("ocl", "Other current liabilities", lambda p: f"={FL.at('current_liabilities', p)}-{BS.at('ap', p)}-{FL.at('debt_current', p)}",
            lambda p: f"={IS.at('rev', p)}*{A.at('ocl', p)}", indent=1)
    BS.line("debt", "Term debt (short- and long-term)", lambda p: f"={FL.at('debt_current', p)}+{FL.at('debt_noncurrent', p)}",
            lambda p: f"={DT.at('debt_end', p)}", indent=1)
    BS.line("rev_bal", "Revolver", None, lambda p: f"={DT.at('rev_end', p)}", indent=1)
    BS.line("oncl", "Other non-current liabilities", lambda p: f"={FL.at('liab_total', p)}-{FL.at('current_liabilities', p)}-{FL.at('debt_noncurrent', p)}",
            same(BS, "oncl"), indent=1)
    BS.line("tl", "Total liabilities", lambda p: f"=SUM({BS.at('ap', p)}:{BS.at('oncl', p)})", lambda p: f"=SUM({BS.at('ap', p)}:{BS.at('oncl', p)})", bold=True, top=True)
    BS.line("se", "Shareholders' equity", fl("equity_parent"),
            lambda p: f"={BS.at('se', p - 1)}+{IS.at('ni', p)}+{CF.at('sbc', p)}+{CF.at('div', p)}+{CF.at('bb', p)}", indent=1)
    BS.line("oeq", "Minority interest & other equity", lambda p: f"={FL.at('liabilities_equity', p)}-{FL.at('liab_total', p)}-{BS.at('se', p)}",
            lambda p: f"={BS.at('oeq', p - 1)}-{IS.at('nci', p)}", indent=1)
    BS.line("te", "Total equity", lambda p: f"={BS.at('se', p)}+{BS.at('oeq', p)}", lambda p: f"={BS.at('se', p)}+{BS.at('oeq', p)}", bold=True, top=True)
    BS.line("tle", "Total liabilities & equity", lambda p: f"={BS.at('tl', p)}+{BS.at('te', p)}", lambda p: f"={BS.at('tl', p)}+{BS.at('te', p)}", bold=True, top=True)
    BS.gap()
    BS.line("bal", "Balance check (assets − liabilities & equity)", lambda p: f"={BS.at('ta', p)}-{BS.at('tle', p)}",
            lambda p: f"={BS.at('ta', p)}-{BS.at('tle', p)}", italic=True, fmt="num1")

    # ------------------------------------------------------------ Cash flow
    CF.section("Operating activities")
    CF.line("ni", "Net income (incl. minority interest)", fl("cf_net_income"), lambda p: f"={IS.at('pretax', p)}+{IS.at('tax', p)}", indent=1)
    CF.line("da", "Depreciation & amortization", fl("da"), lambda p: f"={SC.at('da', p)}", indent=1)
    CF.line("sbc", "Stock-based compensation", fl("sbc"), lambda p: f"={IS.at('rev', p)}*{A.at('sbc', p)}", indent=1)
    CF.line("nwc", "Working capital & other",
            lambda p: f"={FL.at('cfo', p)}-{CF.at('ni', p)}-{CF.at('da', p)}-{CF.at('sbc', p)}",
            lambda p: (f"=-({BS.at('ar', p)}-{BS.at('ar', p - 1)})-({BS.at('inv', p)}-{BS.at('inv', p - 1)})-({BS.at('oca', p)}-{BS.at('oca', p - 1)})"
                       f"+({BS.at('ap', p)}-{BS.at('ap', p - 1)})+({BS.at('ocl', p)}-{BS.at('ocl', p - 1)})"), indent=1)
    CF.line("cfo", "Cash from operations", lambda p: f"=SUM({CF.at('ni', p)}:{CF.at('nwc', p)})", lambda p: f"=SUM({CF.at('ni', p)}:{CF.at('nwc', p)})", bold=True, top=True)
    CF.section("Investing activities")
    CF.line("capex", "Capital expenditure", fl("capex", -1), lambda p: f"=-{SC.at('capex', p)}", indent=1)
    CF.line("acq", "Acquisitions", fl("acquisitions", -1), None, indent=1)
    CF.line("oinv", "Other investing", lambda p: f"={FL.at('cfi', p)}-{CF.at('capex', p)}-{CF.at('acq', p)}",
            lambda p: f"=-({BS.at('sti', p)}-{BS.at('sti', p - 1)})-({BS.at('onca', p)}-{BS.at('onca', p - 1)})", indent=1)
    CF.line("cfi", "Cash from investing", lambda p: f"=SUM({CF.at('capex', p)}:{CF.at('oinv', p)})", lambda p: f"=SUM({CF.at('capex', p)}:{CF.at('oinv', p)})", bold=True, top=True)
    CF.section("Financing activities")
    CF.line("debt", "Term debt issued / (repaid)", None, lambda p: f"={DT.at('debt_end', p)}-{DT.at('debt_beg', p)}", indent=1)
    CF.line("div", "Dividends", fl("dividends", -1), lambda p: f"=-MAX(0,{IS.at('ni', p)})*{A.at('payout', p)}", indent=1)
    CF.line("bb", "Share repurchases", fl("buybacks", -1), lambda p: f"=-MAX(0,{IS.at('ni', p)})*{A.at('buyback', p)}", indent=1)
    CF.line("ofin", "Other financing", lambda p: f"={FL.at('cff', p)}-{CF.at('debt', p)}-{CF.at('div', p)}-{CF.at('bb', p)}",
            lambda p: f"=({BS.at('oncl', p)}-{BS.at('oncl', p - 1)})", indent=1)
    CF.line("revolver", "Revolver draw / (repayment)", None, lambda p: f"={DT.at('rev_draw', p)}", indent=1)
    CF.line("cff", "Cash from financing", lambda p: f"=SUM({CF.at('debt', p)}:{CF.at('revolver', p)})", lambda p: f"=SUM({CF.at('debt', p)}:{CF.at('revolver', p)})", bold=True, top=True)
    CF.gap()
    CF.line("fx", "FX & other", lambda p: f"={FL.at('net_change_cash', p)}-{CF.at('cfo', p)}-{CF.at('cfi', p)}-{CF.at('cff', p)}", None, indent=1)
    CF.line("chg", "Net change in cash", lambda p: f"={CF.at('cfo', p)}+{CF.at('cfi', p)}+{CF.at('cff', p)}+{CF.at('fx', p)}",
            lambda p: f"={CF.at('cfo', p)}+{CF.at('cfi', p)}+{CF.at('cff', p)}+{CF.at('fx', p)}", bold=True, top=True)
    CF.line("beg_cash", "Beginning cash", None, lambda p: f"={BS.at('cash', p - 1)}", indent=1)
    CF.line("end_cash", "Ending cash", None, lambda p: f"={CF.at('beg_cash', p)}+{CF.at('chg', p)}", bold=True)
    CF.gap()
    CF.section("Memo")
    CF.line("fcf", "Free cash flow (CFO + capex)", lambda p: f"={CF.at('cfo', p)}+{CF.at('capex', p)}", lambda p: f"={CF.at('cfo', p)}+{CF.at('capex', p)}", bold=True)

    # ------------------------------------------------------------ Schedules
    SC.section("PP&E roll-forward")
    SC.line("ppe_beg", "Beginning PP&E", lambda p: f"={BS.at('ppe', p - 1)}" if p else None, lambda p: f"={SC.at('ppe_end', p - 1)}", indent=1)
    SC.line("capex", "(+) Capex", lambda p: f"=-{CF.at('capex', p)}", lambda p: f"={IS.at('rev', p)}*{A.at('capex', p)}", indent=1)
    SC.line("da", "(−) Depreciation & amortization", lambda p: f"={CF.at('da', p)}", lambda p: f"={SC.at('ppe_beg', p)}*{A.at('da', p)}", indent=1)
    SC.line("ppe_other", "Other (disposals, leases, FX, acquisitions)", lambda p: f"={SC.at('ppe_end', p)}-{SC.at('ppe_beg', p)}-{SC.at('capex', p)}+{SC.at('da', p)}" if p else None,
            None, indent=1)
    SC.line("ppe_end", "Ending PP&E", lambda p: f"={BS.at('ppe', p)}", lambda p: f"={SC.at('ppe_beg', p)}+{SC.at('capex', p)}-{SC.at('da', p)}+{SC.at('ppe_other', p)}", bold=True, top=True)
    SC.gap()
    SC.section("Working capital")
    SC.line("nwc", "Net working capital (excl. cash and debt)",
            lambda p: f"={BS.at('ar', p)}+{BS.at('inv', p)}+{BS.at('oca', p)}-{BS.at('ap', p)}-{BS.at('ocl', p)}",
            lambda p: f"={BS.at('ar', p)}+{BS.at('inv', p)}+{BS.at('oca', p)}-{BS.at('ap', p)}-{BS.at('ocl', p)}", bold=True)
    SC.line("nwc_pct", "% of revenue", lambda p: f"={SC.at('nwc', p)}/{IS.at('rev', p)}", lambda p: f"={SC.at('nwc', p)}/{IS.at('rev', p)}", fmt="pct", italic=True, indent=1)
    SC.line("dso", "Receivable days", lambda p: f"={BS.at('ar', p)}/{IS.at('rev', p)}*365", lambda p: f"={BS.at('ar', p)}/{IS.at('rev', p)}*365", fmt="days", indent=1)
    SC.line("dpo", "Payable days", lambda p: f"=IF({IS.at('cogs', p)}=0,0,-{BS.at('ap', p)}/{IS.at('cogs', p)}*365)",
            lambda p: f"=IF({IS.at('cogs', p)}=0,0,-{BS.at('ap', p)}/{IS.at('cogs', p)}*365)", fmt="days", indent=1)

    # ------------------------------------------------------------ Debt
    avg = lambda a, b: f"IF(Circ=1,AVERAGE({a},{b}),{a})"
    DT.section("Term debt")
    DT.line("debt_beg", "Beginning balance", None, lambda p: f"={BS.at('debt', p - 1)}", indent=1)
    DT.line("debt_repay", "(−) Repayment", None, lambda p: f"=-{DT.at('debt_beg', p)}*{A.at('repay', p)}", indent=1)
    DT.line("debt_issue", "(+) New issuance", None, lambda p: f"={A.at('issue', p)}", indent=1)
    DT.line("debt_end", "Ending balance", lambda p: f"={BS.at('debt', p)}", lambda p: f"=SUM({DT.at('debt_beg', p)}:{DT.at('debt_issue', p)})", bold=True, top=True)
    DT.line("int_debt", "Interest expense", None, lambda p: f"={A.at('rate_debt', p)}*{avg(DT.at('debt_beg', p), DT.at('debt_end', p))}", indent=1)
    DT.gap()
    DT.section("Revolver")
    DT.line("min_cash", "Minimum cash", None, lambda p: f"={IS.at('rev', p)}*{A.at('min_cash', p)}", indent=1)
    DT.line("cash_pre", "Cash before revolver",
            None, lambda p: (f"={BS.at('cash', p - 1)}+{CF.at('cfo', p)}+{CF.at('cfi', p)}+{CF.at('debt', p)}+{CF.at('div', p)}"
                             f"+{CF.at('bb', p)}+{CF.at('ofin', p)}+{CF.at('fx', p)}"), indent=1)
    DT.line("rev_beg", "Beginning balance", None, lambda p: f"={BS.at('rev_bal', p - 1)}", indent=1)
    DT.line("rev_draw", "Draw / (repayment)", None, lambda p: f"=MAX(-{DT.at('rev_beg', p)},{DT.at('min_cash', p)}-{DT.at('cash_pre', p)})", indent=1)
    DT.line("rev_end", "Ending balance", lambda p: f"={BS.at('rev_bal', p)}", lambda p: f"={DT.at('rev_beg', p)}+{DT.at('rev_draw', p)}", bold=True, top=True)
    DT.line("int_rev", "Interest expense", None, lambda p: f"={A.at('rate_rev', p)}*{avg(DT.at('rev_beg', p), DT.at('rev_end', p))}", indent=1)
    DT.gap()
    DT.section("Interest summary")
    DT.line("int_total", "Total interest expense", None, lambda p: f"={DT.at('int_debt', p)}+{DT.at('int_rev', p)}", bold=True)
    DT.line("int_cash", "Interest income on cash & investments", None,
            lambda p: f"={A.at('rate_cash', p)}*" + avg("(" + BS.at("cash", p - 1) + "+" + BS.at("sti", p - 1) + ")",
                                                          "(" + BS.at("cash", p) + "+" + BS.at("sti", p) + ")"), bold=True)
    DT.line("lev", "Total debt / EBITDA", lambda p: f"=({BS.at('debt', p)}+{BS.at('rev_bal', p)})/{IS.at('ebitda', p)}",
            lambda p: f"=({BS.at('debt', p)}+{BS.at('rev_bal', p)})/{IS.at('ebitda', p)}", fmt="x", italic=True)

    # ------------------------------------------------------------ Checks
    ok = lambda cond: f'=IF({cond},"OK","ERROR")'
    CK.section("Every period")
    CK.line("c_bal", "Balance sheet balances", lambda p: ok(f"ABS({BS.at('bal', p)})<Tol"), lambda p: ok(f"ABS({BS.at('bal', p)})<Tol"), fmt="text")
    CK.line("c_is", "Income statement adds to net income", lambda p: ok(f"ABS({IS.at('ni', p)}-{IS.at('pretax', p)}-{IS.at('tax', p)}-{IS.at('nci', p)})<Tol"),
            lambda p: ok(f"ABS({IS.at('ni', p)}-{IS.at('pretax', p)}-{IS.at('tax', p)}-{IS.at('nci', p)})<Tol"), fmt="text")
    CK.section("Forecast integrity")
    CK.line("c_cash", "Cash flow ending cash = balance sheet cash", None, lambda p: ok(f"ABS({CF.at('end_cash', p)}-{BS.at('cash', p)})<Tol"), fmt="text")
    CK.line("c_ni", "Cash-flow net income = income statement (before minority interest)", None,
            lambda p: ok(f"ABS({CF.at('ni', p)}-{IS.at('ni', p)}+{IS.at('nci', p)})<Tol"), fmt="text")
    CK.line("c_debt", "Term debt and revolver are not negative", None, lambda p: ok(f"AND({DT.at('debt_end', p)}>=-Tol,{DT.at('rev_end', p)}>=-Tol)"), fmt="text")
    CK.line("c_min", "Cash at or above the minimum", None, lambda p: ok(f"{BS.at('cash', p)}>={DT.at('min_cash', p)}-Tol"), fmt="text")
    CK.line("c_ppe", "PP&E roll-forward ties", None, lambda p: ok(f"ABS({SC.at('ppe_end', p)}-{BS.at('ppe', p)})<Tol"), fmt="text")
    CK.section("Ties to the filing (actuals)")
    CK.line("c_eps", "Diluted EPS = reported (within 2% or half a cent)", lambda p: (
        ok(f"ABS({IS.at('eps', p)}-{FL.at('eps_diluted', p)})<=MAX(TolEPS*ABS({FL.at('eps_diluted', p)}),TolCents)") if s.get("eps_diluted", p) else None),
        None, fmt="text")
    CK.line("c_gp", "Gross profit = reported", lambda p: (ok(f"ABS({IS.at('gp', p)}-{FL.at('gross_profit', p)})<Tol") if s.get("gross_profit", p) is not None and s.get("cogs", p) is not None else None),
            None, fmt="text")
    CK.line("c_ta", "Total assets = reported", lambda p: ok(f"ABS({BS.at('ta', p)}-{FL.at('assets', p)})<Tol"), None, fmt="text")
    CK.line("c_cfo", "Cash from operations = reported", lambda p: ok(f"ABS({CF.at('cfo', p)}-{FL.at('cfo', p)})<Tol"), None, fmt="text")
    CK.gap()
    CK.line("master", "MASTER CHECK", None, None, bold=True, fmt="text")

    for g in (FL, A, IS, BS, CF, SC, DT, CK):
        g.render()

    # switches (named) and input styling on the Assumptions sheet
    a = A.sh
    a.set((A.rows["scenario_note"], C0), scenario, fmt="int")
    a.validate_list(ref(A.rows["scenario_note"], C0), [1, 2, 3])
    a.set((A.rows["circ_note"], C0), circ, fmt="int")
    a.validate_list(ref(A.rows["circ_note"], C0), [0, 1])
    wb.define("Scenario", "Assumptions", ref(A.rows["scenario_note"], C0))
    wb.define("Circ", "Assumptions", ref(A.rows["circ_note"], C0))
    # Filings: comments + links on every reported number
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
    # master check
    ck = CK.sh
    first, lastc = col_letter(C0), col_letter(C0 + H + F - 1)
    top, bot = CK.rows["c_bal"], CK.rows["c_cfo"]
    m.ctx = "Checks"
    tr = CK.rows["master"] + 2
    ck.set((tr, 1), "Tolerances", bold=True, color=NAVY, bottom=True)
    for i, (nm, label, v, fmt) in enumerate((("Tol", "Rounding tolerance ($m)", 0.5, "num2"), ("TolEPS", "EPS tolerance (% of reported)", 0.02, "pct"),
                                             ("TolCents", "EPS tolerance (reported to the cent)", 0.005, "num2"))):
        ck.set((tr + 1 + i, 1), label, indent=1)
        ck.set((tr + 1 + i, C0), v, fmt=fmt)
        wb.define(nm, "Checks", ref(tr + 1 + i, C0))
    rng = f"{first}{top}:{lastc}{bot}"
    ck.set((CK.rows["master"], C0), f'=IF(AND(COUNTIF({rng},"ERROR")=0,SUMPRODUCT(--ISERROR({rng}))=0,COUNTIF({rng},"OK")>0),"OK","ERROR")', bold=True)
    ck.ok_error(f"{first}{top}:{lastc}{bot}")
    ck.ok_error(f"{first}{CK.rows['master']}")
    m.ctx = ""

    _dcf(m, DCF, IS, BS, CF, A)
    _cover(m, cover, IS, CF, CK)
    # sheet order: Cover first, Filings last
    order = ["Cover", "Assumptions", "IS", "BS", "CF", "Schedules", "Debt", "DCF", "Checks", "Filings"]
    wb.sheets.sort(key=lambda sh: order.index(sh.name))
    from .formula import calculate_workbook
    eng = calculate_workbook(wb)
    meta = {"converged": eng.converged, "iterations": eng.iterations, "ticker": s.ticker, "name": s.name, "years": [y.isoformat() for y in s.years], "forecast_years": F,
            "warnings": s.warnings, "defaults": d, "rows": {g.name: g.rows for g in (IS, BS, CF, SC, DT, CK, A, FL)}}
    return wb, meta


# --------------------------------------------------------------------------- DCF
def _dcf(m: _Model, sh, IS: _Grid, BS: _Grid, CF: _Grid, A: _Grid) -> None:
    H = m.H
    m.ctx = "DCF"
    s = m.s
    sh.set("A2", f"{s.name} — discounted cash flow", kind="title")
    sh.set("A3", "Unlevered free cash flow from the integrated model; mid-year convention switchable; both terminal-value methods", kind="note")
    sh.width("A", 44)
    sh.width("B", 7)
    for p in range(H + F):
        sh.width(C0 + p, 11.5)
    sh.freeze = (6, 2)
    sh.set((5, 1), f"{s.currency} in millions", kind="header")
    sh.set((5, 2), "", kind="header")
    for p in range(H + F):
        sh.set((5, C0 + p), m.period_label(p), kind="header", align="right")
    fc = range(H, H + F)
    L = lambda r: {"ebit": 8, "tax": 9, "nopat": 10, "da": 11, "capex": 12, "nwc": 13, "ufcf": 14, "idx": 16, "per": 17, "df": 18, "pv": 19}[r]
    c = lambda p: C0 + p
    a = lambda r, p: ref(L(r), c(p))
    rows = [("ebit", "EBIT", lambda p: f"={IS.at('ebit', p)}"),
            ("tax", "(−) Taxes on EBIT", lambda p: f"=-{a('ebit', p)}*{A.at('tax', p)}"),
            ("nopat", "NOPAT", lambda p: f"={a('ebit', p)}+{a('tax', p)}"),
            ("da", "(+) Depreciation & amortization", lambda p: f"={CF.at('da', p)}"),
            ("capex", "(−) Capex", lambda p: f"={CF.at('capex', p)}"),
            ("nwc", "(−) Increase in working capital", lambda p: f"={CF.at('nwc', p)}"),
            ("ufcf", "Unlevered free cash flow", lambda p: f"={a('nopat', p)}+{a('da', p)}+{a('capex', p)}+{a('nwc', p)}")]
    for key, label, fn in rows:
        bold = key in ("nopat", "ufcf")
        sh.set((L(key), 1), label, bold=bold, top=key == "ufcf", indent=0 if bold else 1)
        for p in fc:
            sh.set((L(key), c(p)), fn(p), fmt="num0", bold=bold, top=key == "ufcf")
    I = {"rf": 23, "erp": 24, "beta": 25, "ke": 26, "kd": 27, "kd_at": 28, "wd": 29, "wacc": 30, "g": 32, "mult": 33, "mid": 34,
         "price": 35}
    v = lambda k: f"$C${I[k]}"
    sh.set((L("idx"), 1), "Year", indent=1)
    sh.set((L("per"), 1), "Discount period", indent=1)
    sh.set((L("df"), 1), "Discount factor", indent=1)
    sh.set((L("pv"), 1), "Present value of FCF", bold=True)
    for p in fc:
        prev = ref(L("idx"), c(p - 1))
        sh.set((L("idx"), c(p)), 1 if p == H else f"={prev}+1", fmt="int", kind="calc" if p > H else "input")
        sh.set((L("per"), c(p)), f"={a('idx', p)}-0.5*{v('mid')}", fmt="num2")
        sh.set((L("df"), c(p)), f"=1/(1+{v('wacc')})^{a('per', p)}", fmt="num2")
        sh.set((L("pv"), c(p)), f"={a('ufcf', p)}*{a('df', p)}", fmt="num0", bold=True)

    sh.set((22, 1), "Discount rate (CAPM)", bold=True, color=NAVY, bottom=True)
    sh.set((I["rf"], 1), "Risk-free rate", indent=1); sh.set((I["rf"], 3), 0.0425, fmt="pct")
    sh.set((I["erp"], 1), "Equity risk premium", indent=1); sh.set((I["erp"], 3), 0.055, fmt="pct")
    sh.set((I["beta"], 1), "Levered beta", indent=1); sh.set((I["beta"], 3), 1.1, fmt="num2")
    sh.set((I["ke"], 1), "Cost of equity", indent=1); sh.set((I["ke"], 3), f"={v('rf')}+{v('beta')}*{v('erp')}", fmt="pct")
    sh.set((I["kd"], 1), "Pre-tax cost of debt", indent=1); sh.set((I["kd"], 3), f"={A.at('rate_debt', H)}", fmt="pct")
    sh.set((I["kd_at"], 1), "After-tax cost of debt", indent=1); sh.set((I["kd_at"], 3), f"={v('kd')}*(1-{A.at('tax', H)})", fmt="pct")
    sh.set((I["wd"], 1), "Debt / total capital (target)", indent=1); sh.set((I["wd"], 3), 0.10, fmt="pct")
    sh.set((I["wacc"], 1), "WACC", bold=True, top=True); sh.set((I["wacc"], 3), f"={v('ke')}*(1-{v('wd')})+{v('kd_at')}*{v('wd')}", fmt="pct", bold=True, top=True)
    sh.set((31, 1), "Terminal value and other inputs", bold=True, color=NAVY, bottom=True)
    sh.set((I["g"], 1), "Perpetuity growth rate", indent=1); sh.set((I["g"], 3), LT_GROWTH, fmt="pct")
    sh.set((I["mult"], 1), "Exit EV / EBITDA multiple", indent=1); sh.set((I["mult"], 3), 12.0, fmt="x")
    sh.set((I["mid"], 1), "Mid-year convention (1 = on)", indent=1); sh.set((I["mid"], 3), 1, fmt="int")
    sh.set((I["price"], 1), "Current share price (enter)", indent=1); sh.set((I["price"], 3), 0, fmt="usd2")

    last_f, last_h = H + F - 1, H - 1
    ufcf = f"{ref(L('ufcf'), c(H))}:{ref(L('ufcf'), c(last_f))}"
    N = ref(L("idx"), c(last_f))
    V = {"sum": 39, "tv": 40, "pvtv": 41, "ev": 42, "debt": 43, "cash": 44, "oeq": 45, "eq": 46, "sh": 47, "ps": 48, "up": 49,
         "tvpct": 51, "impl_mult": 52, "impl_g": 53, "ev_ebitda": 54}
    sh.set((37, 1), "Valuation", bold=True, color=NAVY, bottom=True)
    sh.set((37, 3), "Perpetuity", bold=True, align="right", bottom=True)
    sh.set((37, 4), "Exit multiple", bold=True, align="right", bottom=True)
    labels = {"sum": "Sum of PV of free cash flow", "tv": "Terminal value", "pvtv": "PV of terminal value", "ev": "Enterprise value",
              "debt": "(−) Debt incl. revolver (latest actual)", "cash": "(+) Cash & short-term investments", "oeq": "(−) Minority interest & other equity",
              "eq": "Equity value", "sh": "Diluted shares (m, latest actual)", "ps": "Implied value per share", "up": "Upside / (downside) to current price",
              "tvpct": "Terminal value as % of EV", "impl_mult": "Implied exit EV / EBITDA", "impl_g": "Implied perpetuity growth", "ev_ebitda": "Implied EV / latest EBITDA"}
    for k, r in V.items():
        sh.set((r, 1), labels[k], bold=k in ("ev", "eq", "ps"), top=k in ("ev", "eq"), indent=0 if k in ("ev", "eq", "ps") else 1)
    sh.set((50, 1), "Cross-checks", bold=True, color=NAVY, bottom=True)
    ebitda_last = IS.at("ebitda", last_f)
    for col, method in ((3, "g"), (4, "m")):
        X = lambda k: ref(V[k], col)
        sh.set((V["sum"], col), f"=SUM({ref(L('pv'), c(H))}:{ref(L('pv'), c(last_f))})", fmt="num0")
        sh.set((V["tv"], col), f"={ref(L('ufcf'), c(last_f))}*(1+{v('g')})/({v('wacc')}-{v('g')})" if method == "g" else f"={ebitda_last}*{v('mult')}", fmt="num0")
        sh.set((V["pvtv"], col), f"={X('tv')}/(1+{v('wacc')})^{N}", fmt="num0")
        sh.set((V["ev"], col), f"={X('sum')}+{X('pvtv')}", fmt="num0", bold=True, top=True)
        sh.set((V["debt"], col), f"=-({BS.at('debt', last_h)}+{BS.at('rev_bal', last_h)})", fmt="num0")
        sh.set((V["cash"], col), f"={BS.at('cash', last_h)}+{BS.at('sti', last_h)}", fmt="num0")
        sh.set((V["oeq"], col), f"=-{BS.at('oeq', last_h)}", fmt="num0")
        sh.set((V["eq"], col), f"=SUM({X('ev')}:{X('oeq')})", fmt="num0", bold=True, top=True)
        sh.set((V["sh"], col), f"={IS.at('shares', last_h)}", fmt="num1")
        sh.set((V["ps"], col), f"={X('eq')}/{X('sh')}", fmt="usd2", bold=True)
        sh.set((V["up"], col), f"=IF({v('price')}>0,{X('ps')}/{v('price')}-1,0)", fmt="pct")
        sh.set((V["tvpct"], col), f"={X('pvtv')}/{X('ev')}", fmt="pct")
        sh.set((V["ev_ebitda"], col), f"={X('ev')}/{IS.at('ebitda', last_h)}", fmt="x")
    sh.set((V["impl_mult"], 3), f"={ref(V['tv'], 3)}/{ebitda_last}", fmt="x")
    sh.set((V["impl_g"], 4), f"=({ref(V['tv'], 4)}*{v('wacc')}-{ref(L('ufcf'), c(last_f))})/({ref(V['tv'], 4)}+{ref(L('ufcf'), c(last_f))})", fmt="pct")
    # sensitivities: closed form, live
    sh.set((56, 1), "Sensitivity — value per share, perpetuity growth (WACC down, growth across)", bold=True, color=NAVY, bottom=True)
    sh.set((66, 1), "Sensitivity — value per share, exit multiple (WACC down, multiple across)", bold=True, color=NAVY, bottom=True)
    sh.set((76, 1), "Sensitivity steps", bold=True, color=NAVY, bottom=True)
    sh.set((77, 1), "WACC step", indent=1); sh.set((77, 3), 0.005, fmt="pct")
    sh.set((78, 1), "Growth step", indent=1); sh.set((78, 3), 0.005, fmt="pct")
    sh.set((79, 1), "Multiple step", indent=1); sh.set((79, 3), 1.0, fmt="x")
    bridge = f"+{ref(V['debt'], 3, True, True)}+{ref(V['cash'], 3, True, True)}+{ref(V['oeq'], 3, True, True)}"
    shares = ref(V["sh"], 3, True, True)
    U = f"{ref(L('ufcf'), c(H), True, True)}:{ref(L('ufcf'), c(last_f), True, True)}"
    lastu, NN, mid, el = ref(L("ufcf"), c(last_f), True, True), ref(L("idx"), c(last_f), True, True), "$C$34", ebitda_last.replace("IS!", "IS!$")
    for top, base, step, fmt, kind in ((57, "$C$32", "$C$78", "pct", "g"), (67, "$C$33", "$C$79", "x", "m")):
        cols = [4, 5, 6, 7, 8]
        for j, cc in enumerate(cols):
            off = j - 2
            sh.set((top, cc), f"={base}{'+' if off >= 0 else '-'}{abs(off)}*{step}" if off else f"={base}", fmt=fmt, bold=True, align="right")
        for i in range(5):
            r = top + 1 + i
            off = i - 2
            sh.set((r, 3), f"=$C$30{'+' if off >= 0 else '-'}{abs(off)}*$C$77" if off else "=$C$30", fmt="pct", bold=True)
            for cc in cols:
                w, x = f"$C{r}", f"{col_letter(cc)}${top}"
                pv = f"NPV({w},{U})*(1+{w})^(0.5*{mid})"
                tv = f"{lastu}*(1+{x})/({w}-{x})" if kind == "g" else f"{el}*{x}"
                sh.set((r, cc), f"=({pv}+{tv}/(1+{w})^{NN}{bridge})/{shares}", fmt="usd2")
    sh.set((82, 1), "Notes", bold=True)
    for i, t in enumerate([
        "Beta, risk-free rate and equity risk premium are placeholders: replace with your provider's data.",
        "Stock-based compensation is treated as a cash cost (not added back to unlevered FCF), the conservative convention.",
        "Net debt is from the latest actual balance sheet; long-term marketable securities and leases sit in other assets / liabilities and are not netted.",
        "Diluted shares are the latest weighted-average diluted count from the 10-K; use treasury-stock-method shares at today's price for a final view.",
        "Terminal value is discounted from the end of the final forecast year; mid-year convention applies to the forecast cash flows."]):
        sh.set((83 + i, 1), t, kind="note")
    m.ctx = ""


# --------------------------------------------------------------------------- cover
def _cover(m: _Model, sh, IS: _Grid, CF: _Grid, CK: _Grid) -> None:
    s, H = m.s, m.H
    m.ctx = "Cover"
    sh.width("A", 3)
    sh.width("B", 40)
    for cc in range(3, 3 + H + F):
        sh.width(cc, 11.5)
    sh.set("B2", f"{s.name} ({s.ticker})", kind="title", size=18)
    sh.set("B3", "Integrated three-statement model and DCF, built from SEC filings", kind="note")
    sh.set("B5", "Currency / units", bold=True); sh.set("C5", f"{s.currency} in millions, except per-share data")
    sh.set("B6", "Actuals", bold=True); sh.set("C6", f"FY{s.years[0].year}–FY{s.years[-1].year} ({len(s.years)} fiscal years, latest-filed values)")
    sh.set("B7", "Forecast", bold=True); sh.set("C7", f"FY{s.years[-1].year + 1}–FY{s.years[-1].year + F}")
    sh.set("B8", "SEC CIK", bold=True); sh.set("C8", str(s.cik))
    sh.set("B9", "Scenario", bold=True); sh.set("C9", '=CHOOSE(Scenario,"Base","Upside","Downside")')
    sh.set("B10", "Interest circularity", bold=True); sh.set("C10", '=IF(Circ=1,"On (iterative calculation)","Off (opening balances)")')
    sh.set("B11", "MASTER CHECK", bold=True); sh.set("C11", f"={CK.at('master', 0)}", bold=True)
    sh.ok_error("C11")
    sh.set("B13", "Summary", bold=True, color=NAVY, bottom=True)
    for p in range(H + F):
        sh.set((13, 3 + p), m.period_label(p), bold=True, align="right", bottom=True)
    rows = [("Revenue", IS, "rev", "num0"), ("% growth", IS, "rev_g", "pct"), ("EBITDA", IS, "ebitda", "num0"), ("% margin", IS, "ebitda_m", "pct"),
            ("Net income", IS, "ni", "num0"), ("Diluted EPS", IS, "eps", "usd2"), ("Free cash flow", CF, "fcf", "num0")]
    for i, (label, g, k, fmt) in enumerate(rows):
        sh.set((14 + i, 2), label, indent=1 if label.startswith("%") else 0, italic=label.startswith("%"))
        for p in range(H + F):
            if k == "rev_g" and p == 0:
                continue
            sh.set((14 + i, 3 + p), f"={g.at(k, p)}", fmt=fmt)
    sh.set("B23", "Colour code", bold=True, color=NAVY, bottom=True)
    sh.set("B24", "Hard-coded input or figure as filed", color=BLUE)
    sh.set("B25", "Formula on this sheet")
    sh.set("B26", "Link to another sheet", color=GREEN)
    sh.set("B28", "Contents", bold=True, color=NAVY, bottom=True)
    for i, (name, what) in enumerate([("Assumptions", "scenario and circularity switches, every forecast driver"), ("IS", "income statement"),
                                      ("BS", "balance sheet"), ("CF", "cash flow statement"), ("Schedules", "PP&E roll-forward, working capital"),
                                      ("Debt", "term debt, revolver, interest"), ("DCF", "valuation and sensitivities"),
                                      ("Checks", "integrity checks and the master check"), ("Filings", "every historical figure as filed, with its source")]):
        sh.set((29 + i, 2), name, link=f"'{name}'!A1", color=BLUE, underline=True)
        sh.set((29 + i, 3), what, kind="note")
    sh.set("B39", "Sources", bold=True, color=NAVY, bottom=True)
    for i, f in enumerate(s.filings):
        sh.set((40 + i, 2), f"FY{f['end'][:4]}: {f['form']} filed {f['filed']}, accession {f['accn']}", link=f["url"] or None,
               color=BLUE if f["url"] else None, underline=bool(f["url"]))
    if s.warnings:
        r0 = 41 + len(s.filings)
        sh.set((r0, 2), "Mapping notes", bold=True, color=NAVY, bottom=True)
        for i, w in enumerate(s.warnings[:12]):
            sh.set((r0 + 1 + i, 2), w, kind="note")
    m.ctx = ""
