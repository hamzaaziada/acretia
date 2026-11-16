"""Model templates built to investment-banking modelling conventions.

Conventions applied (common practice across bulge-bracket and elite-boutique banks; these are original
layouts, not copies of any firm's proprietary templates):
  • Colour code: hard-coded inputs blue, formulas black, links to data (filings / matrix) green.
  • No hard-coded numbers inside formulas; every assumption lives in a labelled input cell.
  • Assumptions, calculations and outputs in separate blocks; units stated on every block ("$m").
  • Historical (LTM) column next to projections; growth and margin rows under each line item.
  • DCF: WACC built bottom-up (CAPM), mid-year convention switch, both terminal-value methods
    (perpetuity growth and exit multiple) with cross-checks (implied exit multiple / implied growth),
    TV as % of EV, sensitivity tables (WACC × g, WACC × exit multiple).
  • Comps / precedents: max, 75th percentile, mean, median, 25th percentile, min; non-meaningful
    multiples (negative or > 250x) shown as NM and excluded; implied valuation of a target at the
    interquartile range; sourced footnotes.
"""
from __future__ import annotations

import csv
from pathlib import Path


def col(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


class Builder:
    def __init__(self):
        self.cells: dict[str, object] = {}
        self.formats: dict[str, str] = {}
        self.bold: dict[str, int] = {}

    def set(self, ref: str, value, fmt: str | None = None, bold: bool = False):
        self.cells[ref] = value
        if fmt:
            self.formats[ref] = fmt
        if bold:
            self.bold[ref] = 1
        return ref

    def meta(self, **kw) -> dict:
        return {"formats": self.formats, "bold": self.bold, **kw}


STATS = (("Max", "MAX({r})"), ("75th percentile", "QUARTILE({r},3)"), ("Mean", "AVERAGE({r})"),
         ("Median", "MEDIAN({r})"), ("25th percentile", "QUARTILE({r},1)"), ("Min", "MIN({r})"))


# --------------------------------------------------------------------------- trading comps
COMPS_COLS = [  # (field, header, format)
    ("market_cap", "Market cap", "num0"), ("enterprise_value", "Enterprise value", "num0"),
    ("revenue_ltm", "Revenue LTM", "num0"), ("ebitda_ltm", "EBITDA LTM", "num0"),
    ("revenue_growth_ltm_yoy", "Revenue growth", "pct100"), ("margin_gross_ltm", "Gross margin", "pct100"),
    ("margin_ebitda_ltm", "EBITDA margin", "pct100"), ("rule_of_40_ltm_hist", "Rule of 40", "num1"),
    ("ev_revenue_ltm", "EV / Revenue", "x"), ("ev_ebitda_ltm", "EV / EBITDA", "x"), ("price_earnings_ltm", "P / E", "x"),
]


def comps(tickers: list[str], target: str | None = None) -> tuple[dict, dict]:
    b = Builder()
    b.set("A1", "Trading Comparables Analysis", bold=True)
    b.set("A2", "($ in millions, except multiples; LTM = last twelve months)")
    b.set("A4", "Company", bold=True)
    b.set("B4", "Ticker", bold=True)
    b.set("A3", "field key →")
    for j, (key, head, fmt) in enumerate(COMPS_COLS):
        c = col(j + 2)
        b.set(f"{c}3", key)
        b.set(f"{c}4", head, bold=True)
    first = 5
    for i, t in enumerate(tickers):
        r = first + i
        b.set(f"A{r}", f"=OMNAME($B{r})")
        b.set(f"B{r}", t.upper())
        for j, (key, head, fmt) in enumerate(COMPS_COLS):
            c = col(j + 2)
            f = f"=OM($B{r},{c}$3)" if fmt != "pct100" else f"=OM($B{r},{c}$3)/100"
            b.set(f"{c}{r}", f, "pct" if fmt == "pct100" else fmt)
    last = first + max(len(tickers), 1) - 1
    sr = last + 2
    for k, (label, expr) in enumerate(STATS):
        r = sr + k
        b.set(f"A{r}", label, bold=label in ("Mean", "Median"))
        for j, (key, head, fmt) in enumerate(COMPS_COLS):
            if j < 4:
                continue  # size metrics: stats on multiples and operating metrics only
            c = col(j + 2)
            b.set(f"{c}{r}", f'=IFERROR({expr.format(r=f"{c}{first}:{c}{last}")},"NM")', "pct" if fmt == "pct100" else fmt,
                  bold=label in ("Mean", "Median"))
    # implied valuation of a target at the comps' interquartile range
    ir = sr + len(STATS) + 2
    ev_rev, ev_ebitda = col(2 + 8), col(2 + 9)
    p75, med, p25 = sr + 1, sr + 3, sr + 4
    b.set(f"A{ir}", "Implied valuation of target", bold=True)
    b.set(f"A{ir + 1}", "Target ticker")
    b.set(f"B{ir + 1}", (target or (tickers[0] if tickers else "")).upper())
    b.set(f"C{ir + 2}", "25th pct", bold=True)
    b.set(f"D{ir + 2}", "Median", bold=True)
    b.set(f"E{ir + 2}", "75th pct", bold=True)
    for k, (label, fld, mcol) in enumerate((("EV / Revenue LTM", "revenue_ltm", ev_rev), ("EV / EBITDA LTM", "ebitda_ltm", ev_ebitda))):
        r = ir + 3 + 2 * k
        b.set(f"A{r}", f"Target {fld.replace('_ltm', '').replace('_', ' ')} LTM")
        b.set(f"B{r}", f'=OM($B${ir + 1},"{fld}")', "num0")
        b.set(f"A{r + 1}", f"Implied EV at {label}")
        for cc, sr_ in (("C", p25), ("D", med), ("E", p75)):
            b.set(f"{cc}{r + 1}", f'=IFERROR($B{r}*{mcol}{sr_},"NM")', "num0")
    fn = ir + 8
    b.set(f"A{fn}", "Notes", bold=True)
    b.set(f"A{fn + 1}", "Source: company 10-K / 10-Q filings (SEC EDGAR XBRL) via =OM(); click any green cell for the filing.")
    b.set(f"A{fn + 2}", "LTM = latest fiscal year + current year-to-date − prior year-to-date. EBITDA = reported EBIT + D&A (unadjusted).")
    b.set(f"A{fn + 3}", "Market cap / EV / multiples require a licensed share price (PRICES_CSV); otherwise shown as #NOPRICE.")
    b.set(f"A{fn + 4}", "NM = not meaningful (negative or above 250x); excluded from statistics.")
    return b.cells, b.meta(template="comps", tickers=[t.upper() for t in tickers], widths={"A": 230, "B": 70})


# --------------------------------------------------------------------------- precedent transactions
def precedents(deals_csv: Path, query: str = "", limit: int = 40) -> tuple[dict, dict]:
    rows = []
    if deals_csv.exists():
        with open(deals_csv, newline="") as fh:
            for r in csv.DictReader(fh):
                m = {k: r.get(k) for k in ("ev_revenue_ltm", "ev_revenue_ntm", "ev_revenue_unspecified", "ev_ebitda_ltm",
                                           "ev_ebitda_ntm", "ev_ebitda_unspecified") if r.get(k)}
                if not m:
                    continue
                text = f"{r['target']} {r['acquirer']} {r['advisors']}".lower()
                if query and not all(w in text for w in query.lower().split()):
                    continue
                rows.append((r, m))
    rows.sort(key=lambda x: x[0]["announced"] or "", reverse=True)
    rows = rows[:limit]
    b = Builder()
    b.set("A1", "Precedent Transactions Analysis", bold=True)
    b.set("A2", "($ in millions, except multiples) — multiples as presented in fairness-opinion analyses")
    heads = [("Announced", None), ("Target", None), ("Acquirer", None), ("EV / LTM Revenue", "x"), ("EV / NTM Revenue", "x"),
             ("EV / LTM EBITDA", "x"), ("Deal value", "num0"), ("Financial advisor(s)", None), ("Source", None)]
    for j, (h, _) in enumerate(heads):
        b.set(f"{col(j)}4", h, bold=True)
    first = 5
    for i, (r, m) in enumerate(rows):
        n = first + i
        vals = [r["announced"], r["target"], r["acquirer"], m.get("ev_revenue_ltm") or m.get("ev_revenue_unspecified"),
                m.get("ev_revenue_ntm"), m.get("ev_ebitda_ltm") or m.get("ev_ebitda_unspecified"),
                r.get("deal_value_musd_as_printed"), r["advisors"], r["sources"].split(" ")[0]]
        for j, v in enumerate(vals):
            if v not in (None, ""):
                b.set(f"{col(j)}{n}", v, heads[j][1])
    last = first + max(len(rows), 1) - 1
    sr = last + 2
    for k, (label, expr) in enumerate(STATS):
        r = sr + k
        b.set(f"A{r}", label, bold=label in ("Mean", "Median"))
        for j in (3, 4, 5):
            c = col(j)
            b.set(f"{c}{r}", f'=IFERROR({expr.format(r=f"{c}{first}:{c}{last}")},"NM")', "x", bold=label in ("Mean", "Median"))
    ir = sr + len(STATS) + 2
    b.set(f"A{ir}", "Implied valuation of target", bold=True)
    b.set(f"A{ir + 1}", "Target LTM revenue")
    b.set(f"B{ir + 1}", 100, "num0")
    b.set(f"A{ir + 2}", "Target LTM EBITDA")
    b.set(f"B{ir + 2}", 20, "num0")
    b.set(f"C{ir + 3}", "25th pct", bold=True)
    b.set(f"D{ir + 3}", "Median", bold=True)
    b.set(f"E{ir + 3}", "75th pct", bold=True)
    for k, (label, inp, mc) in enumerate((("EV / LTM Revenue", ir + 1, "D"), ("EV / LTM EBITDA", ir + 2, "F"))):
        r = ir + 4 + k
        b.set(f"A{r}", f"Implied EV at {label}")
        for cc, s in (("C", sr + 4), ("D", sr + 3), ("E", sr + 1)):
            b.set(f"{cc}{r}", f'=IFERROR($B${inp}*{mc}{s},"NM")', "num0")
    fn = ir + 7
    b.set(f"A{fn}", "Notes", bold=True)
    b.set(f"A{fn + 1}", "Source: selected precedent transactions tables in SEC merger proxies / S-4s (EDGAR); see Source column.")
    b.set(f"A{fn + 2}", "Multiples are as reported by each financial advisor and not re-computed; periods may differ by advisor.")
    b.set(f"A{fn + 3}", "Blue cells are inputs: replace the target's LTM revenue and EBITDA.")
    return b.cells, b.meta(template="precedents", rows=len(rows), widths={"A": 200, "B": 220, "C": 200, "H": 180, "I": 120})


# --------------------------------------------------------------------------- DCF
def dcf(ticker: str) -> tuple[dict, dict]:
    t = ticker.upper()
    b = Builder()
    S = b.set
    S("A1", "Discounted Cash Flow Analysis", bold=True)
    S("A2", "=OMNAME(B4)&\" — unlevered free cash flow, $ in millions except per-share data\"")
    S("A4", "Ticker", bold=True)
    S("B4", t)

    # ---- assumptions
    S("A6", "Key assumptions", bold=True)
    S("C6", "Year 1", bold=True); S("D6", "Year 2", bold=True); S("E6", "Year 3", bold=True); S("F6", "Year 4", bold=True); S("G6", "Year 5", bold=True)
    S("A7", "Revenue growth")
    for c, v in zip("CDEFG", (0.10, 0.09, 0.08, 0.07, 0.06)):
        S(f"{c}7", v, "pct")
    S("A8", "EBITDA margin")
    S("C8", "=C21", "pct")
    for p, c in zip("CDEF", "DEFG"):
        S(f"{c}8", f"={p}8", "pct")
    S("A9", "D&A % of revenue");      S("C9", "=C22/C18", "pct")
    S("A10", "Capex % of revenue");   S("C10", "=C25/C18", "pct")
    S("A11", "Δ NWC % of Δ revenue"); S("C11", 0.05, "pct")
    S("A12", "Cash tax rate");        S("C12", 0.21, "pct")
    S("A13", "Mid-year convention (1 = on)"); S("C13", 1)

    # ---- WACC (CAPM)
    S("I6", "WACC", bold=True)
    S("I7", "Risk-free rate");             S("J7", 0.0425, "pct")
    S("I8", "Equity risk premium");        S("J8", 0.055, "pct")
    S("I9", "Levered beta");               S("J9", 1.10, "num2")
    S("I10", "Cost of equity");            S("J10", "=J7+J9*J8", "pct")
    S("I11", "Pre-tax cost of debt");      S("J11", 0.055, "pct")
    S("I12", "After-tax cost of debt");    S("J12", "=J11*(1-C12)", "pct")
    S("I13", "Target debt / total capital"); S("J13", 0.10, "pct")
    S("I14", "WACC", bold=True);           S("J14", "=J10*(1-J13)+J12*J13", "pct", bold=True)
    S("I16", "Terminal value", bold=True)
    S("I17", "Perpetuity growth rate");    S("J17", 0.03, "pct")
    S("I18", "Exit EV / EBITDA multiple"); S("J18", 12.0, "x")

    # ---- projections (C = LTM actual, D..H = years 1-5)
    S("A16", "Free cash flow build", bold=True)
    S("C16", "LTM", bold=True)
    for i, c in enumerate("DEFGH"):
        S(f"{c}16", f"Year {i + 1}", bold=True)
    S("A17", "Year index"); S("C17", 0)
    for i, c in enumerate("DEFGH"):
        S(f"{c}17", i + 1)
    S("A18", "Revenue", bold=True);      S("C18", '=OM($B$4,"revenue_ltm")', "num0", bold=True)
    S("A19", "  % growth")
    S("A20", "EBITDA", bold=True);       S("C20", '=OM($B$4,"ebitda_ltm")', "num0", bold=True)
    S("A21", "  % margin");              S("C21", "=C20/C18", "pct")
    S("A22", "(–) D&A");                 S("C22", '=OM($B$4,"d_and_a_ltm")', "num0")
    S("A23", "EBIT");                    S("C23", "=C20-C22", "num0")
    S("A24", "(–) Taxes on EBIT")
    S("A25", "(–) Capex");               S("C25", '=OM($B$4,"capex_ltm")', "num0")
    S("A26", "(–) Increase in NWC")
    S("A27", "Unlevered free cash flow", bold=True)
    S("A28", "Discount period")
    S("A29", "Discount factor")
    S("A30", "PV of free cash flow", bold=True)
    assumption = dict(zip("DEFGH", "CDEFG"))
    for p, c in zip("CDEFG", "DEFGH"):
        a = assumption[c]
        S(f"{c}18", f"={p}18*(1+{a}$7)", "num0", bold=True)
        S(f"{c}19", f"={c}18/{p}18-1", "pct")
        S(f"{c}20", f"={c}18*{a}$8", "num0", bold=True)
        S(f"{c}21", f"={c}20/{c}18", "pct")
        S(f"{c}22", f"={c}18*$C$9", "num0")
        S(f"{c}23", f"={c}20-{c}22", "num0")
        S(f"{c}24", f"=-{c}23*$C$12", "num0")
        S(f"{c}25", f"={c}18*$C$10", "num0")
        S(f"{c}26", f"=({c}18-{p}18)*$C$11", "num0")
        S(f"{c}27", f"={c}23+{c}24+{c}22-{c}25-{c}26", "num0", bold=True)
        S(f"{c}28", f"={c}17-0.5*$C$13", "num2")
        S(f"{c}29", f"=1/(1+$J$14)^{c}28", "num2")
        S(f"{c}30", f"={c}27*{c}29", "num0", bold=True)

    # ---- valuation: both terminal-value methods side by side
    S("A32", "Valuation", bold=True); S("C32", "Perpetuity growth", bold=True); S("D32", "Exit multiple", bold=True)
    S("A33", "Sum of PV of free cash flows"); S("C33", "=SUM(D30:H30)", "num0"); S("D33", "=C33", "num0")
    S("A34", "Terminal value (Year 5)");      S("C34", "=H27*(1+J17)/(J14-J17)", "num0"); S("D34", "=H20*J18", "num0")
    S("A35", "PV of terminal value");         S("C35", "=C34/(1+J14)^H17", "num0"); S("D35", "=D34/(1+J14)^H17", "num0")
    S("A36", "Enterprise value", bold=True);  S("C36", "=C33+C35", "num0", bold=True); S("D36", "=D33+D35", "num0", bold=True)
    S("A37", "(–) Debt");                     S("C37", '=OM($B$4,"ev_bridge_total_debt_lcu")', "num0"); S("D37", "=C37", "num0")
    S("A38", "(+) Cash & investments");       S("C38", '=OM($B$4,"ev_bridge_cash_lcu")', "num0"); S("D38", "=C38", "num0")
    S("A39", "(–) Minority interest & preferred"); S("C39", '=OM($B$4,"ev_bridge_minority_interest_lcu")+OM($B$4,"ev_bridge_preferred_and_hybrid_lcu")', "num0"); S("D39", "=C39", "num0")
    S("A40", "Equity value", bold=True);      S("C40", "=C36-C37+C38-C39", "num0", bold=True); S("D40", "=D36-D37+D38-D39", "num0", bold=True)
    S("A41", "Shares outstanding (m)");       S("C41", '=OM($B$4,"shares_out")/1000000', "num0"); S("D41", "=C41", "num0")
    S("A42", "Implied value per share", bold=True); S("C42", "=C40/C41", "num2", bold=True); S("D42", "=D40/D41", "num2", bold=True)
    S("A44", "Cross-checks", bold=True)
    S("A45", "TV as % of enterprise value");  S("C45", "=C35/C36", "pct"); S("D45", "=D35/D36", "pct")
    S("A46", "Implied exit EV / EBITDA (from g)"); S("C46", "=C34/H20", "x")
    S("A47", "Implied perpetuity growth (from multiple)"); S("D47", "=(D34*J14-H27)/(D34+H27)", "pct")
    S("A48", "Implied EV / LTM EBITDA");      S("C48", "=C36/C20", "x"); S("D48", "=D36/C20", "x")

    # ---- sensitivity tables (closed-form, so they recalc live without data tables)
    def price_g(w, g):
        return (f"=(NPV({w},$D$27:$H$27)*(1+{w})^(0.5*$C$13)+$H$27*(1+{g})/({w}-{g})/(1+{w})^$H$17"
                f"-$C$37+$C$38-$C$39)/$C$41")

    def price_m(w, m):
        return f"=(NPV({w},$D$27:$H$27)*(1+{w})^(0.5*$C$13)+$H$20*{m}/(1+{w})^$H$17-$C$37+$C$38-$C$39)/$C$41"

    S("A50", "Sensitivity — implied value per share (perpetuity growth)", bold=True)
    S("B51", "WACC ↓ / g →")
    S("A63", "Sensitivity — implied value per share (exit multiple)", bold=True)
    S("B64", "WACC ↓ / multiple →")
    # sensitivity axes: centred on the base case, stepping by input cells (no hard-codes in formulas)
    S("I20", "Sensitivity step — WACC");     S("J20", 0.005, "pct")
    S("I21", "Sensitivity step — growth");   S("J21", 0.005, "pct")
    S("I22", "Sensitivity step — multiple"); S("J22", 1.0, "x")
    for row, base, step, fmt in ((51, "$J$17", "$J$21", "pct"), (64, "$J$18", "$J$22", "x")):
        S(f"E{row}", f"={base}", fmt, bold=True)
        S(f"D{row}", f"=E{row}-{step}", fmt, bold=True); S(f"C{row}", f"=D{row}-{step}", fmt, bold=True)
        S(f"F{row}", f"=E{row}+{step}", fmt, bold=True); S(f"G{row}", f"=F{row}+{step}", fmt, bold=True)
    for top in (52, 65):
        S(f"B{top + 2}", "=$J$14", "pct", bold=True)
        S(f"B{top + 1}", f"=B{top + 2}-$J$20", "pct", bold=True); S(f"B{top}", f"=B{top + 1}-$J$20", "pct", bold=True)
        S(f"B{top + 3}", f"=B{top + 2}+$J$20", "pct", bold=True); S(f"B{top + 4}", f"=B{top + 3}+$J$20", "pct", bold=True)
    for i in range(5):
        r1, r2 = 52 + i, 65 + i
        for c in "CDEFG":
            S(f"{c}{r1}", price_g(f"$B{r1}", f"{c}$51"), "num2")
            S(f"{c}{r2}", price_m(f"$B{r2}", f"{c}$64"), "num2")

    S("A72", "Notes", bold=True)
    S("A73", "Base year (LTM) from SEC filings via =OM() — green cells; click for the source filing.")
    S("A74", "Blue cells are assumptions. Beta, risk-free rate and ERP are placeholders: replace with your data provider's.")
    S("A75", "Mid-year convention discounts each year's cash flow at t − 0.5; terminal value is discounted at the end of Year 5.")
    S("A76", "Shares are basic shares from the latest 10-K/10-Q cover page; use diluted (treasury-stock method) for a final view.")
    S("A77", "If the two methods diverge, check the implied growth / multiple cross-checks; normalise terminal-year capex toward D&A.")
    return b.cells, b.meta(template="dcf", widths={"A": 250, "B": 120, "I": 200})


# --------------------------------------------------------------------------- LBO (quick returns model)
def lbo(ticker: str) -> tuple[dict, dict]:
    t = ticker.upper()
    b = Builder()
    S = b.set
    S("A1", "LBO Returns Analysis (paper LBO)", bold=True)
    S("A2", "=OMNAME(B4)&\" — $ in millions\"")
    S("A4", "Ticker", bold=True); S("B4", t)
    S("A6", "Transaction assumptions", bold=True)
    S("A7", "LTM EBITDA");               S("B7", '=OM($B$4,"ebitda_ltm")', "num0")
    S("A8", "Entry EV / EBITDA");        S("B8", 10.0, "x")
    S("A9", "Entry enterprise value");   S("B9", "=B7*B8", "num0")
    S("A10", "Leverage (Debt / EBITDA)"); S("B10", 5.0, "x")
    S("A11", "Debt raised");             S("B11", "=B7*B10", "num0")
    S("A12", "Fees & expenses (% EV)");  S("B12", 0.02, "pct")
    S("A13", "Sponsor equity");          S("B13", "=B9*(1+B12)-B11", "num0", bold=True)
    S("A14", "Interest rate on debt");   S("B14", 0.085, "pct")
    S("A15", "Exit EV / EBITDA");        S("B15", "=B8", "x")
    S("A16", "Cash tax rate");           S("B16", 0.25, "pct")
    S("A17", "Holding period (years)");  S("B17", 5)
    S("A18", "Operating model", bold=True)
    S("B18", "Year 0", bold=True)
    for i, c in enumerate("CDEFG"):
        S(f"{c}18", f"Year {i + 1}", bold=True)
    S("A19", "Revenue growth")
    for c, v in zip("CDEFG", (0.08, 0.08, 0.07, 0.06, 0.05)):
        S(f"{c}19", v, "pct")
    S("A20", "Revenue");      S("B20", '=OM($B$4,"revenue_ltm")', "num0")
    S("A21", "EBITDA margin"); S("B21", "=B7/B20", "pct")
    S("A22", "EBITDA");       S("B22", "=B7", "num0")
    S("A23", "(–) D&A % rev"); S("B23", '=OM($B$4,"d_and_a_ltm")/B20', "pct")
    S("A24", "(–) Capex % rev"); S("B24", '=OM($B$4,"capex_ltm")/B20', "pct")
    S("A25", "(–) Interest")
    S("A26", "(–) Taxes")
    S("A27", "(–) Capex")
    S("A28", "Free cash flow to debt paydown", bold=True)
    S("A29", "Ending debt", bold=True); S("B29", "=B11", "num0")
    for p, c in zip("BCDEF", "CDEFG"):
        S(f"{c}20", f"={p}20*(1+{c}19)", "num0")
        S(f"{c}21", f"={p}21", "pct")
        S(f"{c}22", f"={c}20*{c}21", "num0")
        S(f"{c}25", f"={p}29*$B$14", "num0")
        S(f"{c}26", f"=MAX(0,({c}22-{c}20*$B$23-{c}25)*$B$16)", "num0")
        S(f"{c}27", f"={c}20*$B$24", "num0")
        S(f"{c}28", f"={c}22-{c}25-{c}26-{c}27", "num0", bold=True)
        S(f"{c}29", f"=MAX(0,{p}29-{c}28)", "num0", bold=True)
    S("A31", "Exit & returns (Year 5)", bold=True)
    S("A32", "Exit enterprise value");   S("B32", "=G22*B15", "num0")
    S("A33", "(–) Net debt at exit");    S("B33", "=G29", "num0")
    S("A34", "Exit equity value");       S("B34", "=B32-B33", "num0", bold=True)
    S("A35", "MOIC");                    S("B35", "=B34/B13", "x", bold=True)
    S("A36", "IRR");                     S("B36", "=B35^(1/B17)-1", "pct", bold=True)
    S("A38", "Notes", bold=True)
    S("A39", "Paper LBO: no minimum cash, single tranche, all free cash flow sweeps debt; interest on opening balance.")
    S("A40", "Blue cells are assumptions; green cells come from SEC filings via =OM().")
    S("A41", "Exit is modelled at the end of Year 5 (column G); change the holding period only together with the exit column.")
    return b.cells, b.meta(template="lbo", widths={"A": 230})


TEMPLATES = {"comps": "Trading comps", "precedents": "Precedent transactions", "dcf": "DCF", "lbo": "LBO (paper)"}
