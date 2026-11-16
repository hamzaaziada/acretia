"""Trading comparables workbook, written by code from SEC companyfacts: every multiple is a live formula.

Sheets (one column per company on Inputs / Calendarisation / Equity value; target first, then the peers):
  Inputs           blue, sourced: price (market), basic shares, options + weighted-average strike, RSUs, convertibles,
                   debt, preferred, minority interest, cash and short-term investments, FY / prior FY / YTD / prior YTD
                   for revenue, EBIT, D&A, net income and diluted EPS; LTM is a formula (FY + YTD - prior YTD).
                   Global assumptions (NM caps, calendar month, quartile points, tolerance) are named inputs.
  Calendarisation  CY = w_latest * FY_latest + w_prior * FY_prior with w_prior = MOD(FYE month - CY month, 12) / 12
  Equity value     treasury stock method diluted shares, equity value, EV bridge (each line visible)
  Comps            EV/Revenue, EV/EBITDA, EV/EBIT, P/E on LTM and CY with NM rules; peer-only summary statistics
  Valuation        implied target share price from the peer 25th-75th percentile multiples; football-field table
  Checks           diluted >= basic, EV bridge recomputes, LTM identity, weights, no error values, master check
  Filings          the filings every typed historical number comes from, with links

Rules: nothing typed inside a formula except structural constants; the LLM never types a number here.
"""
from __future__ import annotations

from datetime import date, timedelta

from .facts import ANNUAL_FORMS, Company, Fact
from .xlsx import BLUE, GREY, NAVY, Workbook, col_letter, quote_sheet, ref

C0 = 3                                    # first company column (C)
M = 1e6

METRICS = (("rev", "revenue", "Revenue", "num1"), ("ebit", "ebit", "EBIT (operating income)", "num1"),
           ("da", "d_and_a", "Depreciation & amortisation", "num1"), ("ni", "net_income", "Net income", "num1"),
           ("eps", "eps_diluted", "Diluted EPS", "usd2"))

OPT_NUM = ("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber")
OPT_PX = ("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice")
RSU_CONCEPTS = (("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"),
                ("us-gaap", "ShareBasedCompensationArrangementByShareBasedPaymentAwardNonOptionEquityInstrumentsOutstandingNumber"))
CONV_CONCEPT = ("us-gaap", "IncrementalCommonSharesAttributableToConversionOfDebtSecurities")


def _url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/" if accn else ""


def _d(s):
    return date.fromisoformat(s) if s else None


# --------------------------------------------------------------------------- extraction from companyfacts
class _Rec:
    """One typed number: value, the facts it came from (or a note why it is zero/absent)."""
    __slots__ = ("val", "facts", "note")

    def __init__(self, val: float, facts=None, note: str = ""):
        self.val, self.facts, self.note = float(val), list(facts or []), note

    def comment(self) -> str:
        if not self.facts:
            return self.note
        lines = [f"{f.taxonomy}:{f.concept} = {f.val:,.4f} {f.unit}, {(f.start.isoformat() + ' to ') if f.start else ''}{f.end}, "
                 f"{f.form} filed {f.filed}, accn {f.accn}" for f in self.facts]
        return "\n".join(lines + ([self.note] if self.note else []))


def _raw_fact(co: Company, tc: tuple[str, str], unit: str) -> Fact | None:
    """Latest reported value of a concept the Company metric chains do not cover (annual forms preferred)."""
    rows = co.raw.get(tc[0], {}).get(tc[1], {}).get("units", {}).get(unit, [])
    best, key = None, None
    for r in rows:
        filed = _d(r.get("filed"))
        if co.as_of and filed and filed > co.as_of:
            continue
        k = (r.get("form") in ANNUAL_FORMS, _d(r["end"]), filed or date.min)
        if key is None or k > key:
            key = k
            best = Fact(float(r["val"]), _d(r["end"]), _d(r.get("start")), filed or date.min, r.get("form", ""), r.get("accn", ""),
                        tc[1], tc[0], unit)
    return best


def _scaled(v: float, shares_or_money: bool = True) -> float:
    return v / M if shares_or_money else v


def _collect(ticker: str, cf: dict, as_of: date | None) -> dict:
    co = Company(cf, as_of=as_of)
    rec: dict = {"ticker": ticker, "name": cf.get("entityName") or ticker, "cik": co.cik, "ccy": co.ccy, "warnings": []}
    w = rec["warnings"]
    if co.ccy != "USD":
        w.append(f"{ticker}: reports in {co.ccy}; the price is assumed to be in the same currency (no FX applied)")

    # ---- income statement components: FY, prior FY, YTD, prior YTD (LTM = FY + YTD - prior YTD)
    fy_end = None
    for key, metric, label, _fmt in METRICS:
        per_share = key == "eps"
        s = 1.0 if per_share else M
        ltm = co.ltm(metric)
        if ltm.val is None or not ltm.sources:
            for part in ("fy", "py", "ytd", "pytd"):
                rec[f"{key}_{part}"] = _Rec(0.0, note=f"{label}: not tagged in XBRL; set to 0")
            if key in ("rev", "ebit", "ni"):
                w.append(f"{ticker}: {label} not found in the filings")
            continue
        fy_f = ltm.sources[0]
        rest = ltm.sources[1:]
        cur = [f for f in rest if f.start and f.start > fy_f.end - timedelta(days=5)]
        prior = [f for f in rest if f not in cur]
        pfy = co.fy(metric, -1, anchor=fy_f.end)
        rec[f"{key}_fy"] = _Rec(fy_f.val / s, [fy_f])
        rec[f"{key}_py"] = _Rec(pfy.val / s, pfy.sources) if pfy.val is not None else _Rec(0.0, note=f"{label}: prior fiscal year not available; set to 0")
        rec[f"{key}_ytd"] = _Rec(sum(f.val for f in cur) / s, cur, note="" if cur else "No year-to-date period after the fiscal year end: LTM = FY")
        rec[f"{key}_pytd"] = _Rec(sum(f.val for f in prior) / s, prior, note="" if prior else "No prior-year YTD: LTM = FY")
        if key == "rev":
            fy_end = fy_f.end
        if ltm.basis == "fy_only":
            w.append(f"{ticker}: {label} LTM falls back to the fiscal year (no matching interim periods)")
    if fy_end is None:
        fy_end = max((r.facts[0].end for k, r in rec.items() if k.endswith("_fy") and r.facts), default=None)
    rec["fy_end"] = fy_end
    rec["fye_month"] = _Rec(float(fy_end.month) if fy_end else 12.0,
                            rec["rev_fy"].facts if fy_end and rec["rev_fy"].facts else [],
                            note="" if fy_end else "Fiscal year end unknown: assumed December")
    if rec["da_fy"].val == 0 and not rec["da_fy"].facts:
        w.append(f"{ticker}: D&A not tagged, so EBITDA equals EBIT")

    # ---- balance sheet at the latest balance-sheet date
    bd = co.balance_date()
    rec["bs_date"] = bd

    def inst(metric: str, label: str) -> _Rec:
        v = co.instant(metric, at=bd) if bd else co.instant(metric)
        if v.val is None:
            return _Rec(0.0, note=f"{label}: not tagged at the balance-sheet date; set to 0")
        return _Rec(v.val / M, v.sources)

    for key, metric, label in (("lt_nc", "lt_debt_noncurrent", "Long-term debt, non-current"), ("lt_c", "lt_debt_current", "Long-term debt, current"),
                               ("st_b", "st_borrowings", "Short-term borrowings"), ("cp", "commercial_paper", "Commercial paper"),
                               ("fl", "finance_lease", "Finance lease liabilities"), ("pref", "preferred", "Preferred stock"),
                               ("mi", "minority_interest", "Minority (non-controlling) interest"),
                               ("cash", "cash", "Cash and equivalents"), ("sti", "st_investments", "Short-term investments")):
        rec[key] = inst(metric, label)
    if not any(rec[k].facts for k in ("lt_nc", "lt_c", "st_b", "cp")):
        tot = co.instant("lt_debt_total", at=bd) if bd else co.instant("lt_debt_total")
        if tot.val is not None:
            rec["lt_nc"] = _Rec(tot.val / M, tot.sources, note="Total long-term debt (no current / non-current split tagged)")

    # ---- share count and dilutive securities
    sh = co.instant("shares_out_cover")
    if sh.val is None:
        sh = co.instant("shares_out_bs")
    if sh.val is None:
        rec["basic"] = _Rec(0.0, note="Basic shares outstanding: not tagged; set to 0")
        w.append(f"{ticker}: no shares-outstanding fact (dei or balance sheet)")
    else:
        rec["basic"] = _Rec(sh.val / M, sh.sources)
    n = _raw_fact(co, OPT_NUM, "shares")
    px = _raw_fact(co, OPT_PX, f"{co.ccy}/shares")
    rec["opt"] = _Rec(n.val / M, [n]) if n else _Rec(0.0, note="Options outstanding: not tagged in XBRL; set to 0")
    rec["strike"] = _Rec(px.val, [px]) if px and n else _Rec(0.0, note="Weighted-average exercise price: not tagged; set to 0")
    rsu = None
    for tc in RSU_CONCEPTS:
        rsu = _raw_fact(co, tc, "shares")
        if rsu:
            break
    rec["rsu"] = _Rec(rsu.val / M, [rsu]) if rsu else _Rec(0.0, note="RSUs / unvested units: not tagged in XBRL; set to 0")
    cv = _raw_fact(co, CONV_CONCEPT, "shares")
    rec["conv"] = _Rec(cv.val / M, [cv], note="Dilutive shares from convertibles (if-converted, as reported)") if cv else \
        _Rec(0.0, note="Convertible securities: no if-converted shares tagged; set to 0")
    return rec


# --------------------------------------------------------------------------- workbook
class _Row:
    """Registry of rows by key on a sheet, written down the page."""

    def __init__(self, sh, start: int):
        self.sh, self.r, self.rows = sh, start, {}

    def section(self, title: str, ncols: int) -> None:
        self.sh.set((self.r, 1), title, bold=True, color=NAVY, bottom=True)
        for c in range(2, C0 + ncols):
            self.sh.set((self.r, c), "", bottom=True)
        self.r += 1

    def gap(self) -> None:
        self.r += 1

    def line(self, key: str, label: str, unit: str = "", *, bold: bool = False, indent: int = 1, top: bool = False) -> int:
        self.rows[key] = self.r
        self.sh.set((self.r, 1), label, bold=bold, indent=indent, top=top)
        self.sh.set((self.r, 2), unit, kind="note", top=top)
        self.r += 1
        return self.r - 1


def _head(sh, title: str, sub: str, tickers: list[str], names: list[str] | None, first: str, widths: tuple = (46, 9, 14)) -> None:
    sh.set("A2", title, kind="title")
    sh.set("A3", sub, kind="note")
    sh.set((5, 1), first, kind="header")
    sh.set((5, 2), "Unit", kind="header")
    for i, t in enumerate(tickers):
        sh.set((5, C0 + i), t, kind="header", align="right")
        sh.set((6, C0 + i), (names[i] if names else ""), kind="note", align="right")
        sh.width(C0 + i, widths[2])
    sh.set((6, 1), "Company", kind="note")
    sh.width("A", widths[0])
    sh.width("B", widths[1])
    sh.freeze = (6, 2)


def build_workbook(target: tuple[str, dict], peers: list[tuple[str, dict]], *, markets: dict[str, dict],
                   as_of: str | None = None, calendar_month: int = 12):
    """Trading comps as an om.xlsx.Workbook (calculated) plus metadata. Inputs are (ticker, companyfacts)."""
    from .formula import calculate_workbook
    if not 1 <= int(calendar_month) <= 12:
        raise ValueError("calendar_month must be 1..12")
    asof_d = _d(as_of)
    warnings: list[str] = []
    recs: list[dict] = []
    for i, (t, cf) in enumerate([target] + list(peers)):
        t = t.upper()
        mk = (markets or {}).get(t) or (markets or {}).get(t.lower())
        role = "target" if i == 0 else "peer"
        if not mk or not mk.get("price") or float(mk["price"]) <= 0:
            if i == 0:
                raise ValueError(f"no market price for the target {t}: supply markets[{t!r}] (never invented)")
            warnings.append(f"peer {t} dropped: no market price supplied")
            continue
        r = _collect(t, cf, asof_d)
        if not r["rev_fy"].facts:
            if i == 0:
                raise ValueError(f"target {t}: no revenue found in the filings")
            warnings.append(f"peer {t} dropped: no revenue found in the filings")
            continue
        r["market"], r["role"] = mk, role
        warnings += r["warnings"]
        recs.append(r)
    if len(recs) < 2:
        raise ValueError("need the target and at least one peer with a price and revenue")
    n = len(recs)
    npeer = n - 1
    tickers = [r["ticker"] for r in recs]
    names = [r["name"] for r in recs]
    tcol = C0                              # target column
    lastc = C0 + n - 1
    CL = lambda i: col_letter(C0 + i)

    wb = Workbook()
    shI = wb.sheet("Inputs", tab=BLUE)
    shC = wb.sheet("Calendarisation")
    shE = wb.sheet("Equity value")
    shP = wb.sheet("Comps", tab=NAVY)
    shV = wb.sheet("Valuation", tab=NAVY)
    shK = wb.sheet("Checks")
    shF = wb.sheet("Filings", tab=GREY)
    rows: dict = {}

    # ================================================================ Inputs
    sub = f"Blue = typed. Companyfacts are as filed with the SEC; hover for the concept, period and accession, click to open the filing. $ and shares in millions."
    _head(shI, f"{recs[0]['name']} — trading comparables: inputs", sub, tickers, names, "Millions except per share")
    I = _Row(shI, 8)
    rows["Inputs"] = I.rows

    def typed(key, label, unit, getter, fmt, kind="hist"):
        r = I.line(key, label, unit)
        for i, rc in enumerate(recs):
            x = getter(rc)
            cell = shI.set((r, C0 + i), x.val, fmt=fmt, kind=kind)
            c = shI.cells[(r, C0 + i)]
            c.comment = x.comment() or None
            if x.facts:
                c.link = _url(rc["cik"], x.facts[0].accn) or None
        return r

    I.section("Assumptions (global, named inputs)", n)
    glob = (("NMCapEVRev", "NM cap: EV / Revenue above this is not meaningful", "x", 25.0, "x"),
            ("NMCapEVEBITDA", "NM cap: EV / EBITDA above this is not meaningful", "x", 100.0, "x"),
            ("NMCapEVEBIT", "NM cap: EV / EBIT above this is not meaningful", "x", 100.0, "x"),
            ("NMCapPE", "NM cap: P / E above this is not meaningful", "x", 100.0, "x"),
            ("CalMonth", "Calendar year-end month for calendarisation (12 = December)", "month", float(calendar_month), "int"),
            ("QLow", "Low quartile for implied valuation (1 = 25th percentile)", "quartile", 1.0, "int"),
            ("QHigh", "High quartile for implied valuation (3 = 75th percentile)", "quartile", 3.0, "int"),
            ("Tol", "Check tolerance ($m, shares m, or x)", "abs", 0.0001, "num2"))
    for nm, label, unit, v, fmt in glob:
        r = I.line(nm.lower(), label, unit)
        shI.set((r, C0), v, fmt=fmt, kind="input")
        wb.define(nm, "Inputs", ref(r, C0))
    I.gap()

    I.section("Market data (caller-supplied; never invented)", n)
    r = I.line("price", "Share price", "$")
    for i, rc in enumerate(recs):
        mk = rc["market"]
        shI.set((r, C0 + i), float(mk["price"]), fmt="usd2", kind="input", comment=f"{mk.get('source', '')} (basis: {mk.get('basis', 'quote')})")
    r = I.line("price_asof", "Price as of", "date")
    for i, rc in enumerate(recs):
        shI.set((r, C0 + i), str(rc["market"].get("as_of", "")), kind="text", align="right")
    r = I.line("price_basis", "Price basis", "")
    for i, rc in enumerate(recs):
        shI.set((r, C0 + i), str(rc["market"].get("basis", "quote")), kind="text", align="right")
    I.gap()

    I.section("Share count and dilutive securities", n)
    typed("basic", "Basic shares outstanding (latest cover / balance sheet)", "m", lambda rc: rc["basic"], "num1")
    typed("opt", "Options outstanding", "m", lambda rc: rc["opt"], "num2")
    typed("strike", "Options: weighted-average exercise price", "$", lambda rc: rc["strike"], "usd2")
    typed("rsu", "RSUs / unvested units", "m", lambda rc: rc["rsu"], "num2")
    typed("conv", "Convertible securities (if-converted shares)", "m", lambda rc: rc["conv"], "num2")
    I.gap()

    I.section("Balance sheet (latest)", n)
    for key, label in (("lt_nc", "Long-term debt, non-current"), ("lt_c", "Long-term debt, current"), ("st_b", "Short-term borrowings"),
                       ("cp", "Commercial paper"), ("fl", "Finance lease liabilities"), ("pref", "Preferred stock"),
                       ("mi", "Minority (non-controlling) interest"), ("cash", "Cash and equivalents"), ("sti", "Short-term investments")):
        typed(key, label, "$m", lambda rc, key=key: rc[key], "num1")
    r = I.line("bs_date", "Balance-sheet date", "date")
    for i, rc in enumerate(recs):
        shI.set((r, C0 + i), rc["bs_date"].isoformat() if rc["bs_date"] else "", kind="text", align="right")
    I.gap()

    I.section("Fiscal calendar", n)
    typed("fye", "Fiscal year-end month (1-12)", "month", lambda rc: rc["fye_month"], "int")
    r = I.line("fye_date", "Latest fiscal year end", "date")
    for i, rc in enumerate(recs):
        shI.set((r, C0 + i), rc["fy_end"].isoformat() if rc["fy_end"] else "", kind="text", align="right")
    I.gap()

    I.section("Income statement components (LTM = FY + YTD - prior YTD)", n)
    for key, _m, label, fmt in METRICS:
        unit = "$" if key == "eps" else "$m"
        typed(f"{key}_fy", f"{label}: latest fiscal year", unit, lambda rc, key=key: rc[f"{key}_fy"], fmt)
        typed(f"{key}_py", f"{label}: prior fiscal year", unit, lambda rc, key=key: rc[f"{key}_py"], fmt)
        typed(f"{key}_ytd", f"{label}: current year to date", unit, lambda rc, key=key: rc[f"{key}_ytd"], fmt)
        typed(f"{key}_pytd", f"{label}: prior-year year to date", unit, lambda rc, key=key: rc[f"{key}_pytd"], fmt)
        rr = I.line(f"{key}_ltm", f"{label}: LTM", unit, bold=True, top=True)
        for i in range(n):
            c = CL(i)
            shI.set((rr, C0 + i), f"={c}{I.rows[key + '_fy']}+{c}{I.rows[key + '_ytd']}-{c}{I.rows[key + '_pytd']}", fmt=fmt, bold=True, top=True)
        I.gap()

    # ================================================================ Calendarisation
    _head(shC, "Calendarisation to a common year end",
          "CY = w_latest x FY_latest + w_prior x FY_prior; w_prior = MOD(FYE month - CY month, 12) / 12, the share of the calendar year that falls in the prior fiscal year.",
          tickers, names, "Millions except per share")
    K = _Row(shC, 8)
    rows["Calendarisation"] = K.rows
    IN = lambda key, i: f"Inputs!{CL(i)}{I.rows[key]}"
    K.section("Weights", n)
    K.line("fye", "Fiscal year-end month", "month")
    K.line("lag", "Months the fiscal year end lags the calendar year end", "months")
    K.line("wp", "Weight on the prior fiscal year", "%")
    K.line("wl", "Weight on the latest fiscal year", "%")
    for i in range(n):
        c = CL(i)
        shC.set((K.rows["fye"], C0 + i), f"={IN('fye', i)}", fmt="int")
        shC.set((K.rows["lag"], C0 + i), f"=MOD({c}{K.rows['fye']}-CalMonth,12)", fmt="int")
        shC.set((K.rows["wp"], C0 + i), f"={c}{K.rows['lag']}/12", fmt="pct")
        shC.set((K.rows["wl"], C0 + i), f"=1-{c}{K.rows['wp']}", fmt="pct")
    K.gap()
    K.section("Fiscal-year and LTM figures (links to Inputs)", n)
    for key, _m, label, fmt in METRICS:
        unit = "$" if key == "eps" else "$m"
        for part, lab in (("fy", "latest fiscal year"), ("py", "prior fiscal year"), ("ltm", "LTM")):
            r = K.line(f"{key}_{part}", f"{label}: {lab}", unit)
            for i in range(n):
                shC.set((r, C0 + i), f"={IN(key + '_' + part, i)}", fmt=fmt)
    for part, lab in (("fy", "latest fiscal year"), ("py", "prior fiscal year"), ("ltm", "LTM")):
        r = K.line(f"ebitda_{part}", f"EBITDA (EBIT + D&A): {lab}", "$m", bold=True)
        for i in range(n):
            c = CL(i)
            shC.set((r, C0 + i), f"={c}{K.rows['ebit_' + part]}+{c}{K.rows['da_' + part]}", fmt="num1", bold=True)
    K.gap()
    K.section("Calendarised figures", n)
    for key, label, fmt in (("rev", "Revenue", "num1"), ("ebitda", "EBITDA", "num1"), ("ebit", "EBIT", "num1"), ("ni", "Net income", "num1"),
                            ("eps", "Diluted EPS", "usd2")):
        r = K.line(f"{key}_cy", f"{label}: calendar year", "$" if key == "eps" else "$m", bold=True)
        for i in range(n):
            c = CL(i)
            shC.set((r, C0 + i), f"={c}{K.rows['wl']}*{c}{K.rows[key + '_fy']}+{c}{K.rows['wp']}*{c}{K.rows[key + '_py']}", fmt=fmt, bold=True)

    # ================================================================ Equity value (TSM + EV bridge)
    _head(shE, "Equity value and enterprise value",
          "Diluted shares by the treasury stock method: in-the-money options add options - options x strike / price shares; out-of-the-money options add none.",
          tickers, names, "Millions except per share")
    E = _Row(shE, 8)
    rows["Equity value"] = E.rows
    E.section("Diluted shares (treasury stock method)", n)
    for key, label, unit, src in (("price", "Share price", "$", "price"), ("basic", "Basic shares outstanding", "m", "basic"),
                                  ("opt", "Options outstanding", "m", "opt"), ("strike", "Options: weighted-average exercise price", "$", "strike"),
                                  ("rsu", "RSUs / unvested units", "m", "rsu"), ("conv", "Convertible securities (if-converted)", "m", "conv")):
        r = E.line(key, label, unit)
        for i in range(n):
            shE.set((r, C0 + i), f"={IN(src, i)}", fmt="usd2" if unit == "$" else "num2")
    r = E.line("itm", "Net new shares from in-the-money options (TSM)", "m")
    for i in range(n):
        c = CL(i)
        p, o, k = (f"{c}{E.rows[x]}" for x in ("price", "opt", "strike"))
        shE.set((r, C0 + i), f"=IF({p}>{k},{o}-{o}*{k}/{p},0)", fmt="num2")
    r = E.line("exopt", "Shares excluding options (basic + RSUs + convertibles)", "m")
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"={c}{E.rows['basic']}+{c}{E.rows['rsu']}+{c}{E.rows['conv']}", fmt="num2")
    r = E.line("dil", "Diluted shares outstanding", "m", bold=True, top=True)
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"={c}{E.rows['exopt']}+{c}{E.rows['itm']}", fmt="num2", bold=True, top=True)
    E.gap()
    E.section("Enterprise value bridge", n)
    r = E.line("eqv", "Equity value (price x diluted shares)", "$m", bold=True)
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"={c}{E.rows['price']}*{c}{E.rows['dil']}", fmt="num1", bold=True)
    for key, label in (("lt_nc", "Long-term debt, non-current"), ("lt_c", "Long-term debt, current"), ("st_b", "Short-term borrowings"),
                       ("cp", "Commercial paper"), ("fl", "Finance lease liabilities")):
        r = E.line(key, f"+ {label}", "$m")
        for i in range(n):
            shE.set((r, C0 + i), f"={IN(key, i)}", fmt="num1")
    r = E.line("debt", "Total debt", "$m", bold=True, top=True)
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"=SUM({c}{E.rows['lt_nc']}:{c}{E.rows['fl']})", fmt="num1", bold=True, top=True)
    for key, label in (("pref", "+ Preferred stock"), ("mi", "+ Minority interest")):
        r = E.line(key, label, "$m")
        for i in range(n):
            shE.set((r, C0 + i), f"={IN(key, i)}", fmt="num1")
    for key, label in (("cash", "- Cash and equivalents"), ("sti", "- Short-term investments")):
        r = E.line(key, label, "$m")
        for i in range(n):
            shE.set((r, C0 + i), f"={IN(key, i)}", fmt="num1")
    r = E.line("bridge", "Net bridge: debt + preferred + minority interest - cash and investments", "$m", top=True)
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"={c}{E.rows['debt']}+{c}{E.rows['pref']}+{c}{E.rows['mi']}-{c}{E.rows['cash']}-{c}{E.rows['sti']}", fmt="num1", top=True)
    r = E.line("ev", "Enterprise value", "$m", bold=True, top=True)
    for i in range(n):
        c = CL(i)
        shE.set((r, C0 + i), f"={c}{E.rows['eqv']}+{c}{E.rows['bridge']}", fmt="num1", bold=True, top=True)

    # ================================================================ Comps
    mult = (("rev", "EV / Revenue", "ev", "rev", "NMCapEVRev"), ("ebitda", "EV / EBITDA", "ev", "ebitda", "NMCapEVEBITDA"),
            ("ebit", "EV / EBIT", "ev", "ebit", "NMCapEVEBIT"), ("pe", "P / E", "px", "eps", "NMCapPE"))
    mcols = []                                  # (key, period, label, column)
    col = 6
    for key, label, kind, met, cap in mult:
        for period in ("ltm", "cy"):
            mcols.append((key, period, f"{label} {period.upper()}", col, kind, met, cap))
            col += 1
    shP.set("A2", f"{recs[0]['name']} — trading comparables", kind="title")
    shP.set("A3", f"Multiples are formulas on Equity value and Calendarisation. NM = denominator <= 0 or multiple above its cap (Inputs). "
                  f"Statistics use the {npeer} peer{'s' if npeer != 1 else ''} only (target excluded) and ignore NM.", kind="note")
    for c, t in ((1, "Company"), (2, "Ticker"), (3, "Price ($)"), (4, "Equity value ($m)"), (5, "Enterprise value ($m)")):
        shP.set((5, c), t, kind="header", align="left" if c < 3 else "right")
    for key, period, label, c, *_ in mcols:
        shP.set((5, c), label, kind="header", align="right")
    shP.width("A", 34)
    shP.width("B", 9)
    for c in range(3, col):
        shP.width(c, 13)
    shP.freeze = (5, 2)
    P: dict = {}
    shP.set((6, 1), "Target", bold=True, color=NAVY)
    comp_row = {}

    def comps_row(r: int, i: int) -> None:
        c = CL(i)
        rc = recs[i]
        shP.set((r, 1), f"{rc['name']}", bold=(i == 0))
        shP.set((r, 2), rc["ticker"], kind="text", bold=(i == 0))
        shP.set((r, 3), f"={quote_sheet('Equity value')}!{c}{E.rows['price']}", fmt="usd2", bold=(i == 0))
        shP.set((r, 4), f"={quote_sheet('Equity value')}!{c}{E.rows['eqv']}", fmt="num0", bold=(i == 0))
        shP.set((r, 5), f"={quote_sheet('Equity value')}!{c}{E.rows['ev']}", fmt="num0", bold=(i == 0))
        for key, period, label, mc, kind, met, cap in mcols:
            den = f"Calendarisation!{c}{K.rows[met + '_' + period]}"
            num = f"$E{r}" if kind == "ev" else f"$C{r}"
            shP.set((r, mc), f'=IF(OR({den}<=0,{num}<=0),"NM",IF({num}/{den}>{cap},"NM",{num}/{den}))', fmt="x", bold=(i == 0), align="right")

    comps_row(7, 0)
    comp_row[0] = 7
    shP.set((9, 1), "Peers", bold=True, color=NAVY)
    for j in range(1, n):
        comps_row(9 + j, j)
        comp_row[j] = 9 + j
    p0, p1 = 10, 9 + npeer
    sr = p1 + 2
    shP.set((sr - 1, 1), f"Peer statistics (n = {npeer}, target excluded)", bold=True, color=NAVY, bottom=True)
    for c in range(2, col):
        shP.set((sr - 1, c), "", bottom=True)
    stats = (("max", "Maximum", "MAX({r})"), ("q3", "75th percentile", "QUARTILE({r},QHigh)"), ("mean", "Mean", "AVERAGE({r})"),
             ("median", "Median", "MEDIAN({r})"), ("q1", "25th percentile", "QUARTILE({r},QLow)"), ("min", "Minimum", "MIN({r})"))
    for k, (key, label, fn) in enumerate(stats):
        r = sr + k
        P[key] = r
        shP.set((r, 1), label, bold=(key == "median"), indent=1)
        for _k, _p, _l, mc, *_ in mcols:
            rng = f"{col_letter(mc)}{p0}:{col_letter(mc)}{p1}"
            shP.set((r, mc), f'=IF(COUNT({rng})=0,"NM",{fn.format(r=rng)})', fmt="x", bold=(key == "median"), align="right")
    r = sr + len(stats)
    P["n"] = r
    shP.set((r, 1), "Peers with a meaningful multiple", indent=1, top=True)
    for c in range(2, 6):
        shP.set((r, c), "", top=True)
    for _k, _p, _l, mc, *_ in mcols:
        rng = f"{col_letter(mc)}{p0}:{col_letter(mc)}{p1}"
        shP.set((r, mc), f"=COUNT({rng})", fmt="int", top=True, align="right")
    rows["Comps"] = {**P, "target": 7, "peer_first": p0, "peer_last": p1}
    mcol = {(k, p): c for k, p, _l, c, *_ in mcols}

    # ================================================================ Valuation
    shV.set("A2", f"{recs[0]['name']} — implied valuation from peer multiples", kind="title")
    shV.set("A3", "Peer 25th-75th percentile multiple x the target's metric. EV methods go back to a price through the net bridge and the "
                  "treasury stock method solved in closed form: P = (equity + N x K) / (shares ex-options + N) when that exceeds the strike K, else equity / shares ex-options.", kind="note")
    shV.width("A", 40)
    for c in range(2, 12):
        shV.width(c, 14)
    V = _Row(shV, 5)
    rows["Valuation"] = V.rows
    V.section("Target share data (links)", 4)
    tE = lambda key: f"={quote_sheet('Equity value')}!{CL(0)}{E.rows[key]}"
    for key, label, unit, src, fmt in (("bridge", "Net bridge (debt + preferred + MI - cash)", "$m", "bridge", "num1"),
                                       ("opt", "Options outstanding (N)", "m", "opt", "num2"), ("strike", "Options exercise price (K)", "$", "strike", "usd2"),
                                       ("exopt", "Shares excluding options", "m", "exopt", "num2"), ("price", "Current share price", "$", "price", "usd2")):
        r = V.line(key, label, unit)
        shV.set((r, 3), tE(src), fmt=fmt)
    V.gap()
    br, nn, kk, ss = (f"$C${V.rows[x]}" for x in ("bridge", "opt", "strike", "exopt"))
    hdr = V.r
    for c, t in enumerate(("Method", "Unit", "Low multiple", "High multiple", "Target metric", "EV low", "EV high", "Equity low", "Equity high",
                           "Price low", "Price high"), start=1):
        shV.set((hdr, c), t, kind="header", align="left" if c <= 2 else "right")
    V.r += 1
    methods = []
    first_m = V.r
    for key, period, label, mc, kind, met, cap in mcols:
        r = V.r
        V.r += 1
        methods.append((r, key, period, label))
        shV.set((r, 1), label, indent=1)
        shV.set((r, 2), "x", kind="note")
        shV.set((r, 3), f"=Comps!{col_letter(mc)}{P['q1']}", fmt="x", align="right")
        shV.set((r, 4), f"=Comps!{col_letter(mc)}{P['q3']}", fmt="x", align="right")
        shV.set((r, 5), f"=Calendarisation!{CL(0)}{K.rows[met + '_' + period]}", fmt="usd2" if met == "eps" else "num1", align="right")
        if kind == "ev":
            for c, m in ((6, "C"), (7, "D")):
                shV.set((r, c), f'=IF(ISNUMBER({m}{r}),IF(E{r}>0,{m}{r}*E{r},"NM"),"NM")', fmt="num0", align="right")
            for c, s in ((8, "F"), (9, "G")):
                shV.set((r, c), f'=IF(ISNUMBER({s}{r}),{s}{r}-{br},"NM")', fmt="num0", align="right")
            for c, s in ((10, "H"), (11, "I")):
                e = f"{s}{r}"
                shV.set((r, c), f'=IF(ISNUMBER({e}),IF({e}>0,IF(({e}+{nn}*{kk})/({ss}+{nn})>{kk},({e}+{nn}*{kk})/({ss}+{nn}),{e}/{ss}),"NM"),"NM")',
                        fmt="usd2", align="right")
        else:
            for c in (6, 7, 8, 9):
                shV.set((r, c), "n/a", kind="note", align="right")
            for c, m in ((10, "C"), (11, "D")):
                shV.set((r, c), f'=IF(ISNUMBER({m}{r}),IF(E{r}>0,{m}{r}*E{r},"NM"),"NM")', fmt="usd2", align="right")
    last_m = V.r - 1
    V.gap()
    # football field
    V.section("Football field (chart source: bind a stacked bar to Low and Spread)", 9)
    ff_head = V.r
    for c, t in enumerate(("Method", "Low", "High", "Spread (High - Low)", "Current price"), start=1):
        shV.set((ff_head, c), t, kind="header", align="left" if c == 1 else "right")
    V.r += 1
    ff0 = V.r
    for r, key, period, label in methods:
        fr = V.r
        V.r += 1
        shV.set((fr, 1), f"=A{r}")
        shV.set((fr, 2), f"=J{r}", fmt="usd2", align="right")
        shV.set((fr, 3), f"=K{r}", fmt="usd2", align="right")
        shV.set((fr, 4), f'=IF(ISNUMBER(B{fr}),IF(ISNUMBER(C{fr}),C{fr}-B{fr},"NM"),"NM")', fmt="usd2", align="right")
        shV.set((fr, 5), f"=$C${V.rows['price']}", fmt="usd2", align="right")
    ff1 = V.r - 1
    V.gap()
    ref_r = V.r
    V.rows["ref_low"], V.rows["ref_high"] = ref_r, ref_r + 1
    shV.set((ref_r, 1), "Implied price, low (median of the method lows)", bold=True)
    shV.set((ref_r, 3), f'=IF(COUNT(B{ff0}:B{ff1})=0,"NM",MEDIAN(B{ff0}:B{ff1}))', fmt="usd2", bold=True, align="right")
    shV.set((ref_r + 1, 1), "Implied price, high (median of the method highs)", bold=True)
    shV.set((ref_r + 1, 3), f'=IF(COUNT(C{ff0}:C{ff1})=0,"NM",MEDIAN(C{ff0}:C{ff1}))', fmt="usd2", bold=True, align="right")
    V.r += 2
    rows["Valuation"].update({"method_first": first_m, "method_last": last_m, "ff_header": ff_head, "ff_first": ff0, "ff_last": ff1})

    # ================================================================ Checks
    shK.set("A2", "Checks", kind="title")
    shK.set("A3", "Every cell reads OK or ERROR. Tolerance Tol is a named input on Inputs.", kind="note")
    shK.set((5, 1), "Check", kind="header")
    shK.set((5, 2), "", kind="header")
    for i, t in enumerate(tickers):
        shK.set((5, C0 + i), t, kind="header", align="right")
        shK.width(C0 + i, 14)
    shK.width("A", 62)
    shK.width("B", 4)
    shK.freeze = (5, 2)
    master_r = 7
    shK.set((master_r - 1, 1), "Master check", bold=True, color=NAVY, bottom=True)
    Kc = _Row(shK, 9)
    rows["Checks"] = Kc.rows
    qs = quote_sheet
    per_company = (
        ("c_dil", "Diluted shares >= basic shares",
         lambda c: f'=IF({qs("Equity value")}!{c}{E.rows["dil"]}>={qs("Equity value")}!{c}{E.rows["basic"]}-Tol,"OK","ERROR")'),
        ("c_ev", "EV bridge recomputes from Inputs (independent TSM form)",
         lambda c: (f'=IF(ABS({qs("Equity value")}!{c}{E.rows["ev"]}-(Inputs!{c}{I.rows["price"]}*(Inputs!{c}{I.rows["basic"]}+Inputs!{c}{I.rows["rsu"]}'
                    f'+Inputs!{c}{I.rows["conv"]}+Inputs!{c}{I.rows["opt"]}*MAX(0,1-Inputs!{c}{I.rows["strike"]}/Inputs!{c}{I.rows["price"]}))'
                    f'+SUM(Inputs!{c}{I.rows["lt_nc"]}:{c}{I.rows["fl"]})+Inputs!{c}{I.rows["pref"]}+Inputs!{c}{I.rows["mi"]}'
                    f'-Inputs!{c}{I.rows["cash"]}-Inputs!{c}{I.rows["sti"]}))<=Tol,"OK","ERROR")')),
        ("c_ltm", "LTM = FY + YTD - prior YTD for revenue, EBIT, D&A, net income, EPS",
         lambda c: "=IF(AND(" + ",".join(
             f"ABS(Inputs!{c}{I.rows[k + '_ltm']}-(Inputs!{c}{I.rows[k + '_fy']}+Inputs!{c}{I.rows[k + '_ytd']}-Inputs!{c}{I.rows[k + '_pytd']}))<=Tol"
             for k in ("rev", "ebit", "da", "ni", "eps")) + '),"OK","ERROR")'),
        ("c_w", "Calendarisation weights sum to 100%",
         lambda c: f'=IF(ABS(Calendarisation!{c}{K.rows["wp"]}+Calendarisation!{c}{K.rows["wl"]}-1)<=Tol,"OK","ERROR")'),
        ("c_err", "No error values in this company's calculations",
         lambda c: (f'=IF(SUMPRODUCT(--ISERROR(Calendarisation!{c}{K.rows["fye"]}:{c}{K.r - 1}))'
                    f'+SUMPRODUCT(--ISERROR({qs("Equity value")}!{c}{E.rows["price"]}:{c}{E.r - 1}))=0,"OK","ERROR")')),
    )
    for key, label, fn in per_company:
        r = Kc.line(key, label, "")
        for i in range(n):
            shK.set((r, C0 + i), fn(CL(i)), kind="check", align="right")
    singles = (
        ("c_comps", "No error values on Comps",
         f'=IF(SUMPRODUCT(--ISERROR(Comps!C7:{col_letter(col - 1)}{P["n"]}))=0,"OK","ERROR")'),
        ("c_val", "No error values on Valuation",
         f'=IF(SUMPRODUCT(--ISERROR(Valuation!C{first_m}:K{ff1}))=0,"OK","ERROR")'),
        ("c_ff", "Football field: no negative spread (high >= low)", f'=IF(MIN(Valuation!D{ff0}:D{ff1})>=0,"OK","ERROR")'),
        ("c_peers", "Peer statistics exclude the target (peer range starts below the target row)", f'=IF(Comps!A{p0 - 1}="Peers","OK","ERROR")'),
    )
    for key, label, f in singles:
        r = Kc.line(key, label, "")
        shK.set((r, C0), f, kind="check", align="right")
    first_row, last_row = Kc.rows["c_dil"], Kc.r - 1
    rng = f"C{first_row}:{col_letter(lastc)}{last_row}"
    shK.set((master_r, C0), f'=IF(AND(COUNTIF({rng},"ERROR")=0,SUMPRODUCT(--ISERROR({rng}))=0,COUNTIF({rng},"OK")>0),"OK","ERROR")', bold=True, kind="check")
    shK.ok_error(rng)
    shK.ok_error(f"C{master_r}")
    rows["Checks"]["master"] = master_r

    # ================================================================ Filings
    shF.set("A2", "Source filings", kind="title")
    shF.set("A3", "Every typed historical number on Inputs comes from one of these filings (hover over the cell for concept and period).", kind="note")
    for c, t in enumerate(("Ticker", "Form", "Accession", "Filed", "Latest period end", "Link"), start=1):
        shF.set((5, c), t, kind="header")
    shF.width("A", 10)
    shF.width("B", 10)
    shF.width("C", 24)
    shF.width("D", 12)
    shF.width("E", 16)
    shF.width("F", 70)
    fr = 6
    for rc in recs:
        seen: dict = {}
        for k, v in rc.items():
            if isinstance(v, _Rec):
                for f in v.facts:
                    cur = seen.get(f.accn)
                    if cur is None or f.end > cur.end:
                        seen[f.accn] = f
        for accn, f in sorted(seen.items(), key=lambda kv: kv[1].filed):
            url = _url(rc["cik"], accn)
            shF.set((fr, 1), rc["ticker"], kind="text")
            shF.set((fr, 2), f.form, kind="text")
            shF.set((fr, 3), accn, kind="text")
            shF.set((fr, 4), f.filed.isoformat(), kind="text")
            shF.set((fr, 5), f.end.isoformat(), kind="text")
            shF.set((fr, 6), url, kind="text", link=url or None)
            fr += 1
    shF.freeze = (5, 0)

    # sheet order
    order = ["Inputs", "Calendarisation", "Equity value", "Comps", "Valuation", "Checks", "Filings"]
    wb.sheets.sort(key=lambda s: order.index(s.name))
    eng = calculate_workbook(wb)

    # ================================================================ meta
    def vals(sheet: str, r: int, c: int):
        return eng.values.get((sheet, r, c))

    plant_i = next((i for i in range(1, n) if recs[i]["opt"].val > 0 and recs[i]["market"]["price"] > recs[i]["strike"].val), 1)
    ev_r, itm_r = E.rows["ev"], E.rows["itm"]
    outputs = [
        {"id": "comps.median_ev_ebitda_ltm", "sheet": "Comps", "ref": f"{col_letter(mcol[('ebitda', 'ltm')])}{P['median']}", "units": "x",
         "label": "Peer median EV / EBITDA (LTM)"},
        {"id": "comps.median_pe_ltm", "sheet": "Comps", "ref": f"{col_letter(mcol[('pe', 'ltm')])}{P['median']}", "units": "x",
         "label": "Peer median P / E (LTM)"},
        {"id": "comps.implied_price_low", "sheet": "Valuation", "ref": f"C{V.rows['ref_low']}", "units": "USD/share",
         "label": "Implied share price, low (median of method lows)"},
        {"id": "comps.implied_price_high", "sheet": "Valuation", "ref": f"C{V.rows['ref_high']}", "units": "USD/share",
         "label": "Implied share price, high (median of method highs)"},
        {"id": "comps.target_ev", "sheet": "Equity value", "ref": f"{CL(0)}{ev_r}", "units": "USD m", "label": "Target enterprise value"},
        {"id": "comps.target_diluted_shares", "sheet": "Equity value", "ref": f"{CL(0)}{E.rows['dil']}", "units": "m shares",
         "label": "Target diluted shares (treasury stock method)"},
    ]
    meta = {"model": "comps", "rows": rows, "outputs": outputs, "converged": eng.converged, "iterations": eng.iterations,
            "warnings": warnings, "target": tickers[0], "peers": tickers[1:], "as_of": as_of, "calendar_month": int(calendar_month),
            "columns": {t: CL(i) for i, t in enumerate(tickers)},
            "football_field": {"sheet": "Valuation", "ref": f"A{ff_head}:E{ff1}", "header_row": ff_head, "first_row": ff0, "last_row": ff1,
                               "columns": {"method": "A", "low": "B", "high": "C", "spread": "D", "current": "E"}},
            "plants": {"tsm": f"Equity value!{CL(plant_i)}{itm_r}", "bridge": f"Equity value!{CL(plant_i)}{ev_r}",
                       "nm": f"Comps!{col_letter(mcol[('pe', 'ltm')])}{comp_row[plant_i]}"}}
    return wb, meta


def build(target: tuple[str, dict], peers: list[tuple[str, dict]], *, markets: dict[str, dict], as_of: str | None = None,
          calendar_month: int = 12) -> tuple[bytes, dict]:
    wb, meta = build_workbook(target, peers, markets=markets, as_of=as_of, calendar_month=calendar_month)
    return wb.to_bytes(), meta
