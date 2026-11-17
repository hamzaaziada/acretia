"""Deck builders: data → polished, editable PowerPoint (native tables & charts, sourced footnotes).

  comps_deck(tickers)          trading comparables: table with median/mean, growth vs margin chart, scale chart,
                               data-driven takeaways, methodology
  tear_sheet(ticker)           company profile: KPI tiles, 3-period financial summary, revenue/EBITDA chart,
                               risk factors quoted from the latest 10-K (with section reference)
  valuation_deck(payload)      football field (ranges by method), DCF assumptions & outputs, sensitivity grid
  rounds_deck(filters)         private-market update from Form D: KPIs, capital by quarter, top rounds, industries
  answer_deck(ask_result)      an Ask answer as slides: answer bullets with citation markers + sources appendix
Every number on a slide traces to a filing / Form D / model cell; takeaways are computed, not generated.
"""
from __future__ import annotations

import re
import statistics
import time

from .pptx import MARGIN, W, Deck, emu, para, run

CONTENT_TOP = emu(1.5)
FULL_W = W - 2 * MARGIN


# --------------------------------------------------------------------------- formatting
def money_m(v, dec=0):
    """$ millions -> '478,834'"""
    return "n/a" if v is None else f"{v:,.{dec}f}"


def big_money(v_usd):
    if v_usd is None:
        return "n/a"
    a = abs(v_usd)
    return f"${v_usd / 1e12:,.2f}tn" if a >= 1e12 else f"${v_usd / 1e9:,.1f}bn" if a >= 1e9 else f"${v_usd / 1e6:,.1f}m" if a >= 1e6 else f"${v_usd:,.0f}"


def pct(v, dec=1):
    return "n/a" if v is None else f"{v:.{dec}f}%"


def mult(v):
    return "NM" if v is None else f"{v:.1f}x"


LEGAL = {"CORP": "Corp.", "CORPORATION": "Corporation", "INC": "Inc.", "INC.": "Inc.", "CO": "Co.", "CO.": "Co.", "LTD": "Ltd.",
         "PLC": "plc", "LLC": "LLC", "LP": "LP", "NV": "N.V.", "SA": "S.A.", "AG": "AG", "SE": "SE", "&": "&", "HOLDINGS": "Holdings"}


BRANDS = {b.upper(): b for b in ["NVIDIA", "JPMorgan", "ASML", "AMD", "IBM", "SAP", "TSMC", "HSBC", "UBS", "KKR", "AT&T", "eBay",
                                    "PayPal", "ServiceNow", "BlackRock", "FedEx", "UPS", "NetApp", "AbbVie", "GlaxoSmithKline", "HP",
                                    "Booking", "DoorDash", "CrowdStrike", "MongoDB", "HubSpot", "DocuSign", "QUALCOMM", "Arista", "ARM",
                                    "BNY", "SoFi", "AppLovin", "GoDaddy", "McDonald's", "McKesson", "ConocoPhillips", "ExxonMobil"]}


def display_name(name: str | None) -> str:
    """'MICROSOFT CORP' -> 'Microsoft Corp.'; 'NVIDIA CORP' -> 'NVIDIA Corp.'; mixed-case names are kept as filed."""
    if not name:
        return ""
    if not name.isupper():
        return name
    words = []
    for i, w in enumerate(name.split()):
        u = w.upper().strip(",")
        if i and u in {"OF", "AND", "THE", "FOR", "DE"}:
            words.append(w.lower())
            continue
        words.append(BRANDS.get(u) or LEGAL.get(u) or (w if (len(w) <= 3 and w.isalpha() and u not in {"THE", "AND", "OF"}) else w.capitalize()))
    return " ".join(words)


def _num(vals):
    return [v for v in vals if isinstance(v, (int, float))]


def kpi_tiles(slide, tiles: list[tuple[str, str]], y: int, h: float = 1.0):
    n = len(tiles)
    gap = emu(0.18)
    w = int((FULL_W - gap * (n - 1)) / n)
    for i, (label, value) in enumerate(tiles):
        x = MARGIN + i * (w + gap)
        slide.rect(x, y, w, emu(h), fill="band")
        slide.rect(x, y, emu(0.06), emu(h), fill="blue")
        slide.text(x + emu(0.2), y + emu(0.1), w - emu(0.3), emu(h - 0.2),
                   [para(run(label, 10, False, "slate"), space_after=2), para(run(value, 22, True, "navy"))], anchor="ctr")


def bullets(items: list[str], size: float = 12) -> list[str]:
    return [para(run(t, size), bullet=True, space_after=6) for t in items]


# --------------------------------------------------------------------------- comps
def comps_deck(data_service, tickers: list[str], brand: str = "Research", title: str | None = None) -> Deck:
    rows = []
    for t in tickers:
        try:
            r, _ = data_service.comps_row(t)
            rows.append(r)
        except Exception as e:  # unknown ticker: keep going, note it
            rows.append({"ticker": t.upper(), "name": f"{t.upper()} (not found: {e})"})
    deck = Deck(title or "Trading comparables", brand)
    deck.cover(title or "Trading Comparables Analysis", " · ".join(r.get("ticker") or "" for r in rows), None)

    head = ["Company", "Ticker", "Revenue LTM ($m)", "Revenue growth", "Gross margin", "EBITDA margin", "Rule of 40",
            "EV / Revenue", "EV / EBITDA", "P / E"]
    body = []
    for r in rows:
        body.append([display_name(r.get("name", "")), r.get("ticker", ""), money_m(r.get("revenue_ltm")), pct(r.get("revenue_growth_ltm_yoy")),
                     pct(r.get("margin_gross_ltm")), pct(r.get("margin_ebitda_ltm")), pct(r.get("rule_of_40_ltm_hist"), 0),
                     mult(r.get("ev_revenue_ltm")), mult(r.get("ev_ebitda_ltm")), mult(r.get("price_earnings_ltm"))])
    keys = ["revenue_ltm", "revenue_growth_ltm_yoy", "margin_gross_ltm", "margin_ebitda_ltm", "rule_of_40_ltm_hist",
            "ev_revenue_ltm", "ev_ebitda_ltm", "price_earnings_ltm"]
    fmts = [money_m, pct, pct, pct, lambda v: pct(v, 0), mult, mult, mult]
    stats_rows = []
    for label, fn in (("Median", statistics.median), ("Mean", statistics.mean)):
        line = [label, ""]
        for k, f in zip(keys, fmts):
            vals = _num(r.get(k) for r in rows)
            line.append(f(fn(vals)) if vals else "n/a")
        stats_rows.append(line)
    table = [head] + body + stats_rows
    widths = [3.2, 0.9, 1.6, 1.3, 1.2, 1.3, 1.1, 1.2, 1.2, 1.0]
    drop = [c for c in (7, 8, 9) if all(row[c] in ("NM", "n/a") for row in table[1:])]
    if drop:
        table = [[v for c, v in enumerate(row) if c not in drop] for row in table]
        widths = [w_ for c, w_ in enumerate(widths) if c not in drop]
    note = (" Valuation multiples omitted: they require a licensed share price (set PRICES_CSV)." if drop else
            " Multiples: NM = negative, above 250x or unavailable.")
    s = deck.content("Trading comparables", "LTM operating metrics" + ("" if drop else " and valuation multiples"),
                     "Source: company 10-K / 10-Q filings (SEC EDGAR XBRL). LTM = latest fiscal year + current YTD − prior YTD. "
                     "EBITDA = reported EBIT + D&A; not meaningful for banks and insurers (n/a)." + note)
    n = len(table)
    th = s.table(MARGIN, CONTENT_TOP, FULL_W, table, widths, set(range(2, len(widths))),
                 {n - 2, n - 1}, row_h=0.36 if n <= 12 else 0.28, font=11 if n <= 12 else 9, shade_rows={n - 2, n - 1})
    # 6. peer summary strip under the table
    ops = [r for r in rows if r.get("revenue_ltm")]
    if ops and CONTENT_TOP + th + emu(1.6) < emu(6.6):
        med = lambda k: statistics.median(_num(r.get(k) for r in ops) or [0])  # noqa: E731
        kpi_tiles(s, [("Peers", str(len(rows))), ("Median revenue LTM", big_money(med("revenue_ltm") * 1e6)),
                      ("Median revenue growth", pct(med("revenue_growth_ltm_yoy"))),
                      ("Median EBITDA margin", pct(statistics.median(_num(r.get("margin_ebitda_ltm") for r in ops if not r.get("is_financial_format")) or [0])))],
                  CONTENT_TOP + th + emu(0.45), h=0.95)

    valid = [r for r in rows if r.get("revenue_ltm") and not r.get("is_financial_format")]
    fin = [display_name(r.get("name")) for r in rows if r.get("is_financial_format")]
    if valid:
        s2 = deck.content("Growth and profitability", "LTM revenue growth vs. EBITDA margin (%)",
                          "Source: SEC filings via XBRL." + (f" Excludes financial-format companies (EBITDA not meaningful): {', '.join(fin)}." if fin else ""))
        s2.chart(MARGIN, CONTENT_TOP, emu(8.2), emu(4.9), [r["ticker"] for r in valid],
                 [("Revenue growth (%)", [round(r.get("revenue_growth_ltm_yoy") or 0, 1) for r in valid]),
                  ("EBITDA margin (%)", [round(r.get("margin_ebitda_ltm") or 0, 1) for r in valid])], number_format="0.0")
        g = max(valid, key=lambda r: r.get("revenue_growth_ltm_yoy") or -1e9)
        m = max(valid, key=lambda r: r.get("margin_ebitda_ltm") or -1e9)
        big = max(valid, key=lambda r: r.get("revenue_ltm") or 0)
        med_g = statistics.median(_num(r.get("revenue_growth_ltm_yoy") for r in valid) or [0])
        med_m = statistics.median(_num(r.get("margin_ebitda_ltm") for r in valid) or [0])
        for r_ in valid:
            r_["name"] = display_name(r_.get("name"))
        takeaways = [f"{g['name']} is the fastest grower at {pct(g.get('revenue_growth_ltm_yoy'))} LTM vs. a peer median of {pct(med_g)}.",
                     f"{m['name']} has the highest EBITDA margin ({pct(m.get('margin_ebitda_ltm'))}); peer median {pct(med_m)}.",
                     f"{big['name']} is the largest by revenue ({big_money((big.get('revenue_ltm') or 0) * 1e6)} LTM)."]
        r40 = [r for r in valid if (r.get("rule_of_40_ltm_hist") or 0) >= 40]
        if r40:
            takeaways.append(f"{len(r40)} of {len(valid)} peers clear the Rule of 40 (growth + EBITDA margin).")
        s2.text(emu(9.0), CONTENT_TOP, W - MARGIN - emu(9.0), emu(4.9),
                [para(run("Key takeaways", 14, True, "navy"), space_after=10)] + bullets(takeaways, 12))

        s3 = deck.content("Scale", "LTM revenue and EBITDA ($ in millions)", "Source: SEC filings via XBRL.")
        s3.chart(MARGIN, CONTENT_TOP, FULL_W, emu(4.9), [r["ticker"] for r in valid],
                 [("Revenue", [round(r.get("revenue_ltm") or 0) for r in valid]), ("EBITDA", [round(r.get("ebitda_ltm") or 0) for r in valid])])
    _methodology(deck)
    return deck


# --------------------------------------------------------------------------- tear sheet
BOILER = re.compile(r"(?i)^(statements in this|this section|the following|in addition|forward-looking|you should|investors should|"
                    r"the company's (business|operations), (reputation|financial)|risks? (and|or) uncertaint)")
SPECIFIC = re.compile(r"(?i)\b(tariffs?|china|taiwan|india|vietnam|semiconductor|memory|storage|supply|component|customer|"
                      r"currency|interest rate|regulat\w*|antitrust|litigation|cyber\w*|data|privacy|AI|energy|power|labor|"
                      r"inventory|manufactur\w*|concentration|single source|outsourc\w*|export|sanction\w*|war|conflict)\b")
GENERIC = re.compile(r"(?i)\b(material(ly)? adverse(ly)?|no assurance|there can be|may not be able|could be harmed|any or all)\b")
RISK_HINT = re.compile(r"(?i)\b(could|may|might|risk|adversely|depend|uncertain|competition|tariff|regulat|supply|concentrat)\w*")


def tear_sheet(data_service, index, ticker: str, brand: str = "Research") -> Deck:
    r, prov = data_service.comps_row(ticker)
    name, t = display_name(r.get("name")) or ticker.upper(), ticker.upper()
    deck = Deck(f"{name} — company profile", brand)
    deck.cover(f"{name}", f"Company profile · {t} · {r.get('sic_description') or ''}".strip(" ·"), None)

    s = deck.content(f"{name} at a glance", f"LTM to {r.get('ltm_end')} · reporting currency {r.get('reporting_currency')} · $ in millions",
                     "Source: company 10-K / 10-Q filings (SEC EDGAR XBRL).")
    kpi_tiles(s, [("Revenue LTM", big_money((r.get("revenue_ltm") or 0) * 1e6)), ("Revenue growth YoY", pct(r.get("revenue_growth_ltm_yoy"))),
                  ("EBITDA margin", pct(r.get("margin_ebitda_ltm"))), ("Free cash flow LTM", big_money((r.get("fcf_ltm") or 0) * 1e6))], CONTENT_TOP)
    lines = [("Revenue", "revenue"), ("Gross profit", "gross_profit"), ("EBITDA", "ebitda"), ("EBIT", "ebit"),
             ("Net income", "net_income"), ("Free cash flow", "fcf")]
    fy = (r.get("last_fy_end") or "")[:4]
    head = ["$ in millions", f"FY{int(fy) - 1}" if fy.isdigit() else "FY-1", f"FY{fy}" if fy else "FY",
            f"LTM {r.get('ltm_end') or ''}".strip()]
    table = [head]
    for label, k in lines:
        table.append([label, money_m(r.get(f"{k}_fy_minus1")), money_m(r.get(f"{k}_fy")), money_m(r.get(f"{k}_ltm"))])
    table.append(["EBITDA margin", "", pct(r.get("margin_ebitda_fy")), pct(r.get("margin_ebitda_ltm"))])
    table.append(["Revenue growth", "", pct(r.get("revenue_growth_fy")), pct(r.get("revenue_growth_ltm_yoy"))])
    s.table(MARGIN, CONTENT_TOP + emu(1.3), emu(6.4), table, [2.2, 1.3, 1.3, 1.6], {1, 2, 3}, {1, 3}, row_h=0.33, font=10.5)
    periods = ["FY-1", "FY", "LTM"]
    s.chart(MARGIN + emu(6.8), CONTENT_TOP + emu(1.2), FULL_W - emu(6.8), emu(3.6), periods,
            [("Revenue", [r.get("revenue_fy_minus1"), r.get("revenue_fy"), r.get("revenue_ltm")]),
             ("EBITDA", [r.get("ebitda_fy_minus1"), r.get("ebitda_fy"), r.get("ebitda_ltm")])])

    risks = _risk_quotes(index, t)
    if risks:
        s2 = deck.content("Key risks disclosed", f"Selected statements from {name}'s latest annual report (Item 1A. Risk Factors)",
                          f"Source: {name} Form 10-K, filed {risks[0]['filed']} (SEC EDGAR). Quotations are verbatim excerpts.")
        paras = []
        for q in risks[:6]:
            paras.append(para([run("“", 12, True, "blue"), run(q["text"], 12), run("”", 12, True, "blue")], bullet=True, space_after=10))
        s2.text(MARGIN, CONTENT_TOP, FULL_W, emu(5.0), paras)
    _methodology(deck)
    return deck


HEADING = re.compile(r"^([A-Z][A-Za-z,&/\- ]{3,90}?)\s(?=(?:The Company|The company|We|Our)\b)")


def _risk_quotes(index, ticker: str, k: int = 6) -> list[dict]:
    doc = index.db.execute("SELECT doc_id, filed FROM documents WHERE ticker=? AND form IN ('10-K','20-F') ORDER BY filed DESC LIMIT 1",
                           (ticker,)).fetchone()
    if not doc:
        return []
    chunks = index.db.execute("SELECT text, section FROM chunks WHERE doc_id=? AND section LIKE '%1A%' ORDER BY ord", (doc["doc_id"],)).fetchall()
    out, seen = [], set()
    for oi, c in enumerate(chunks):
        for sent in re.split(r"(?<=[.])\s+(?=[A-Z])", c["text"]):
            # drop a run-in sub-heading glued to the sentence ("Legal and Regulatory Risks The Company is…")
            sent = sent.strip()
            m = HEADING.match(sent)
            if m and sum(w[:1].isupper() for w in m.group(1).split()) >= 2:
                sent = sent[m.end():]
            if not (90 <= len(sent) <= 260) or len(RISK_HINT.findall(sent)) < 2 or BOILER.match(sent):
                continue
            key = sent[:60]
            if key in seen:
                continue
            seen.add(key)
            # specificity: concrete nouns (tariffs, China, semiconductors…), numbers and proper nouns beat generic wording
            score = (len(SPECIFIC.findall(sent)) * 2 + len(re.findall(r"\d", sent)) * 0.3
                     + len(re.findall(r"(?<!^)(?<![.] )\b[A-Z][a-z]{2,}", sent)) * 0.5 - len(GENERIC.findall(sent)))
            out.append({"text": sent, "section": c["section"], "filed": doc["filed"], "score": score, "ord": oi})
    best = sorted(out, key=lambda x: -x["score"])[:k]
    return sorted(best, key=lambda x: x["ord"])


# --------------------------------------------------------------------------- valuation (from a Sheets model)
def valuation_deck(payload: dict, brand: str = "Research") -> Deck:
    """payload: {company, ticker, unit: '$ per share', methods: [{name, low, high, note}], assumptions: [[label, value]],
                 outputs: [[label, value]], sensitivity: {title, row_label, col_label, rows: [...], cols: [...], grid: [[...]]}}"""
    company = display_name(payload.get("company")) or payload.get("ticker") or "Company"
    deck = Deck(f"{company} — valuation", brand)
    deck.cover(f"{company} — Preliminary Valuation", "Discussion materials · draft for internal review", None)
    methods = [m for m in payload.get("methods", []) if m.get("low") is not None and m.get("high") is not None]
    if methods:
        lo = min(m["low"] for m in methods)
        hi = max(m["high"] for m in methods)
        span = max(hi - lo, abs(hi) * 0.1, 1)
        axis_min = max(0, round((lo - span * 0.35) / 5) * 5)
        dec = 0 if hi >= 100 else 2   # one precision for the whole page
        cats = [f"{m['name']}  ({_v(m['low'], dec)} – {_v(m['high'], dec)})" for m in methods]
        s = deck.content("Valuation summary", f"Implied value per share ({payload.get('unit', '$')}) by methodology",
                         "Source: valuation model (Sheets). " + payload.get("range_note", "Ranges from the model's sensitivity analysis.") + " " +
                         " ".join(m.get("note", "") for m in methods if m.get("note")))
        callout = _divergence_note(methods, payload.get("checks") or {})
        s.chart(MARGIN, CONTENT_TOP, FULL_W, emu(4.3 if callout else 4.9), cats,
                [("Low", [m["low"] for m in methods]), ("Range", [round(m["high"] - m["low"], 2) for m in methods])],
                kind="bar", stacked=True, hidden_first=True, labels=False, value_axis=True, number_format='"$"#,##0',
                gap=55, axis_min=axis_min)
        if callout:
            s.rect(MARGIN, CONTENT_TOP + emu(4.4), FULL_W, emu(0.55), "F3F5F8")
            s.rect(MARGIN, CONTENT_TOP + emu(4.4), emu(0.06), emu(0.55), "B8892B")
            s.text(MARGIN + emu(0.2), CONTENT_TOP + emu(4.43), FULL_W - emu(0.3), emu(0.5), [para(run(callout, 11))])
    if payload.get("assumptions") or payload.get("outputs"):
        s2 = deck.content("Discounted cash flow — key assumptions and outputs", "$ in millions, except per-share data",
                          "Source: valuation model (Sheets). Base year from SEC filings; assumptions are the deal team's.")
        if payload.get("assumptions"):
            s2.text(MARGIN, CONTENT_TOP, emu(5.9), emu(0.4), [para(run("Assumptions", 13, True, "navy"))])
            s2.table(MARGIN, CONTENT_TOP + emu(0.45), emu(5.9), [["Assumption", "Value"]] + payload["assumptions"], [3, 1.4], {1}, row_h=0.3, font=10.5)
        if payload.get("outputs"):
            x = MARGIN + emu(6.4)
            s2.text(x, CONTENT_TOP, FULL_W - emu(6.4), emu(0.4), [para(run("Outputs", 13, True, "navy"))])
            outs = payload["outputs"]
            s2.table(x, CONTENT_TOP + emu(0.45), FULL_W - emu(6.4), [["", "Perpetuity growth", "Exit multiple"]] + outs, [2.6, 1.4, 1.4],
                     {1, 2}, {len(outs)}, row_h=0.3, font=10.5)
    sens = payload.get("sensitivity")
    if sens and sens.get("grid"):
        s3 = deck.content(sens.get("title", "Sensitivity analysis"), "Implied value per share",
                          "Source: valuation model (Sheets). Shaded row = base-case WACC; centre column = base-case assumption.")
        head = [f"{sens.get('row_label', '')} ↓  /  {sens.get('col_label', '')} →"] + [str(c) for c in sens["cols"]]
        grid = [[str(rlab)] + [_v(v, 2) for v in row] for rlab, row in zip(sens["rows"], sens["grid"])]
        mid = len(grid) // 2 + 1
        s3.table(MARGIN + emu(1.5), CONTENT_TOP + emu(0.3), FULL_W - emu(3.0), [head] + grid, [2.2] + [1] * len(sens["cols"]),
                 set(range(1, len(head))), {mid}, row_h=0.42, font=11, shade_rows={mid})
    _methodology(deck)
    return deck


def _divergence_note(methods: list[dict], checks: dict) -> str:
    """Flag ranges that don't overlap: a banker reviewing the page would ask why before anything else."""
    if len(methods) < 2:
        return ""
    lo_hi, hi_lo = max(m["low"] for m in methods), min(m["high"] for m in methods)
    if hi_lo <= 0 or lo_hi / hi_lo < 1.25:
        return ""
    parts = ["Methods do not overlap."]
    g, mx = checks.get("implied_growth"), checks.get("implied_multiple")
    if g is not None:
        parts.append(f"The exit multiple implies {g * 100:.1f}% perpetual growth")
    if mx is not None:
        parts.append(("and" if g is not None else "The") + f" the growth method implies {mx:.1f}x EBITDA at exit.")
    elif g is not None:
        parts[-1] += "."
    parts.append("Review terminal-year capex, margin and the exit multiple before relying on either range.")
    return " ".join(parts)


def _v(v, dec: int | None = None):
    if v is None:
        return "n/a"
    dec = (2 if abs(v) < 100 else 0) if dec is None else dec
    return f"${v:,.{dec}f}"


# --------------------------------------------------------------------------- funding market (Form D)
def rounds_deck(rounds, filters: dict | None = None, brand: str = "Research") -> Deck:
    f = filters or {}
    st = rounds.stats(**f)
    top = rounds.search(**{**f, "sort": "amount", "limit": 12})["results"]
    loaded = [q["quarter"] for q in st["quarters_loaded"]]
    period = f"{loaded[-1]} – {loaded[0]}" if loaded else ""
    scope = f.get("industry") or "All industries"
    deck = Deck("Private funding market update", brand)
    deck.cover("Private Funding Market Update", f"{scope} · US Regulation D offerings · {period}", None)
    s = deck.content("Market overview", f"{scope} · operating-company rounds (funds, real estate and public-company PIPEs excluded)",
                     "Source: SEC Form D filings (DERA quarterly data sets). Amounts as reported by issuers; amendments merged into the original round.")
    kpi_tiles(s, [("Rounds", f"{st['rounds']:,}"), ("Capital raised", big_money(st["total_sold"])), ("Median round", big_money(st["median_sold"])),
                  ("Period", period or "n/a")], CONTENT_TOP)
    q = [x for x in st["by_quarter"] if not loaded or x["quarter"] >= loaded[-1].replace("Q", "-Q")]
    if q:
        s.chart(MARGIN, CONTENT_TOP + emu(1.25), emu(7.6), emu(3.7), [x["quarter"] for x in q],
                [("Capital raised ($bn)", [round(x["sold"] / 1e9, 1) for x in q])], number_format="0.0")
        s.text(MARGIN + emu(7.9), CONTENT_TOP + emu(1.3), FULL_W - emu(7.9), emu(3.6),
               [para(run("Capital raised by quarter of first sale ($bn)", 11, True, "navy"), space_after=8)] +
               bullets([f"{x['quarter']}: {big_money(x['sold'])} across {x['rounds']:,} rounds" for x in q][-4:], 11))
    s2 = deck.content("Largest rounds", f"{scope} · ranked by amount sold", "Source: SEC Form D filings. Form D does not report valuation.")
    rows = [["Company", "Industry", "Location", "First sale", "Amount sold", "Investors"]]
    for r in top:
        rows.append([r["company"][:42], r["industry"], f"{r['city']}, {r['state'] or r['country']}", r["first_sale_date"] or "",
                     big_money(r["amount_sold"]), str(r["investors"])])
    s2.table(MARGIN, CONTENT_TOP, FULL_W, rows, [3.2, 1.8, 1.9, 1.2, 1.2, 0.9], {4, 5}, row_h=0.33, font=10)
    if st["by_industry"]:
        s3 = deck.content("Capital by industry", "Top industries by capital raised ($bn)", "Source: SEC Form D filings (industry group as self-reported by issuers).")
        ind = st["by_industry"][:10]
        s3.chart(MARGIN, CONTENT_TOP, FULL_W, emu(4.9), [i["industry"] for i in ind], [("Capital raised ($bn)", [round(i["sold"] / 1e9, 1) for i in ind])],
                 kind="bar", number_format="0.0", gap=45)
    return deck


# --------------------------------------------------------------------------- Ask answer
def answer_deck(question: str, result: dict, brand: str = "Research") -> Deck:
    deck = Deck("Research note", brand)
    deck.cover(question[:110], f"Research note · {time.strftime('%d %B %Y')}", None)
    text = result.get("answer") or ""
    cites = {c["n"]: c for c in result.get("citations", [])}
    blocks = [b.strip() for b in re.split(r"\n+", text) if b.strip()]
    pages = [blocks[i:i + 6] for i in range(0, len(blocks), 6)]
    for pi, page in enumerate(pages):
        s = deck.content("Summary" if pi == 0 else "Summary (continued)", question[:120],
                         f"Sources: see appendix. {result.get('verified', 0)} citations verified against source text.")
        paras = []
        for b in page:
            is_bullet = bool(re.match(r"^[-*•]\s+", b))
            b = re.sub(r"^[-*•]\s+|^#+\s*", "", b).replace("**", "")
            parts = re.split(r"(\[\d+\])", b)
            runs = [run(p, 8, True, "blue") if re.fullmatch(r"\[\d+\]", p) else run(p, 13) for p in parts if p]
            paras.append(para(runs, bullet=is_bullet, space_after=9))
        s.text(MARGIN, CONTENT_TOP, FULL_W, emu(5.0), paras)
    srcs = result.get("sources", [])
    if srcs and not cites:
        rows = [["Source", "Type", "Detail"]]
        for x in srcs[:24]:
            k = x.get("kind")
            rows.append([(f"{x.get('company', '')} {x.get('form', '')} {x.get('filed', '')}" if k == "document" else
                          f"{x.get('target', '')} / {x.get('acquirer', '')}" if k == "deal" else str(x.get("company") or x.get("id"))).strip(),
                         {"document": "Filing", "financials": "Financials", "round": "Form D", "deal": "Precedent"}.get(k, k or ""),
                         re.sub(r"\s+", " ", str(x.get("text") or x.get("snippet") or ""))[:120]])
        for ci in range(0, len(rows) - 1, 12):
            s = deck.content("Sources found", question[:120], "Matching sources; add an AI model in Settings for a written, cited answer.")
            s.table(MARGIN, CONTENT_TOP, FULL_W, [rows[0]] + rows[1 + ci:13 + ci], [3.2, 1.1, 6.1], set(), row_h=0.36, font=9)
    if srcs and cites:
        rows = [["#", "Source", "Detail", "Verified"]]
        for n, c in sorted(cites.items()):
            src = next((x for x in srcs if x.get("id") == c["source_id"]), {})
            label = (f"{src.get('company', '')} {src.get('form', '')} {src.get('filed', '')}" if src.get("kind") == "document" else
                     f"{src.get('company', '')} financials" if src.get("kind") == "financials" else
                     f"{src.get('company', '')} Form D" if src.get("kind") == "round" else
                     f"{src.get('target', '')} / {src.get('acquirer', '')}" if src.get("kind") == "deal" else c["source_id"])
            rows.append([f"[{n}]", label.strip(), (c.get("quote") or "")[:110], "yes" if c.get("verified") else "no"])
        for chunk_i in range(0, len(rows) - 1, 12):
            s = deck.content("Appendix — sources", "Citations and supporting quotations", "Quotes are verbatim from the cited source.")
            s.table(MARGIN, CONTENT_TOP, FULL_W, [rows[0]] + rows[1 + chunk_i:13 + chunk_i], [0.5, 3.0, 6.0, 0.9], set(), row_h=0.36, font=9)
    return deck


# --------------------------------------------------------------------------- shared
def _methodology(deck: Deck):
    s = deck.content("Methodology and sources", "", "Prepared with Acretia. For discussion purposes only; not investment advice.")
    s.text(MARGIN, CONTENT_TOP, FULL_W, emu(5.0), bullets([
        "Financials: company 10-K / 10-Q filings via SEC EDGAR XBRL company facts; each figure links to its filing in the source model.",
        "LTM = latest fiscal year + current year-to-date − prior year-to-date, using one consistent XBRL concept where possible.",
        "EBITDA = reported operating income (EBIT) + depreciation & amortization; unadjusted.",
        "Multiples: EV / metric and price / earnings; negative or above 250x shown as NM. Market data requires a licensed price feed.",
        "Private rounds: SEC Form D (Regulation D); precedent transactions: fairness-opinion tables in SEC merger proxies.",
    ], 12))


# --------------------------------------------------------------------------- Sheets DCF -> valuation payload
def dcf_payload(cells: dict, values: dict) -> dict:
    """Read the DCF template's live values (as computed in the browser) into a valuation_deck payload.
    Ranges use the inner 3x3 of each sensitivity table (base ± one step), the usual football-field convention."""
    v = lambda a: values.get(a) if isinstance(values.get(a), (int, float)) else None  # noqa: E731

    def rng(rows, cols):
        xs = [v(f"{c}{r}") for r in rows for c in cols]
        xs = [x for x in xs if x is not None and x > 0]
        return (round(min(xs), 2), round(max(xs), 2)) if xs else (None, None)
    pct_ = lambda a: pct(v(a) * 100) if v(a) is not None else "n/a"  # noqa: E731
    g_lo, g_hi = rng(range(53, 56), "DEF")
    m_lo, m_hi = rng(range(66, 69), "DEF")
    ticker = str(values.get("B4") or cells.get("B4", {}).get("v") or "").upper()
    title = str(values.get("A2") or "")
    company = title.split(" — ")[0] if " — " in title else ticker
    growth = [v(f"{c}7") for c in "CDEFG"]
    return {
        "company": company, "ticker": ticker, "unit": "$",
        "range_note": "Ranges = base case ± one sensitivity step in WACC and in terminal growth / exit multiple.",
        "methods": [
            {"name": "DCF — perpetuity growth", "low": g_lo, "high": g_hi},
            {"name": "DCF — exit multiple", "low": m_lo, "high": m_hi},
        ],
        "assumptions": [
            ["Revenue growth (Years 1–5)", " / ".join(f"{x * 100:.0f}%" for x in growth if x is not None) or "n/a"],
            ["EBITDA margin", pct_("C8")], ["Capex % of revenue", pct_("C10")], ["Cash tax rate", pct_("C12")],
            ["WACC", pct_("J14")], ["Perpetuity growth rate", pct_("J17")],
            ["Exit EV / EBITDA", mult(v("J18"))],
        ],
        "outputs": [
            ["Enterprise value ($m)", money_m(v("C36")), money_m(v("D36"))],
            ["Equity value ($m)", money_m(v("C40")), money_m(v("D40"))],
            ["TV as % of EV", pct_("C45"), pct_("D45")],
            ["Implied value per share", _v(v("C42"), 2), _v(v("D42"), 2)],
        ],
        "checks": {"implied_growth": v("D47"), "implied_multiple": v("C46")},
        "sensitivity": {
            "title": "Sensitivity — implied value per share (perpetuity growth)",
            "row_label": "WACC", "col_label": "Perpetuity growth",
            "rows": [pct_(f"B{r}") for r in range(52, 57)],
            "cols": [pct_(f"{c}51") for c in "CDEFG"],
            "grid": [[v(f"{c}{r}") for c in "CDEFG"] for r in range(52, 57)],
        },
    }


# --------------------------------------------------------------------------- one entry point for web + CLI
def build(kind: str, req: dict, *, data_service=None, index=None, rounds=None, brand: str = "Research") -> tuple[Deck, str]:
    """-> (deck, file-name stem). kind: comps | tearsheet | valuation | dcf | rounds | answer"""
    if kind == "comps":
        ts = [t.upper() for t in re.split(r"[\s,]+", req.get("tickers") if isinstance(req.get("tickers"), str)
                                           else " ".join(req.get("tickers") or [])) if t]
        if not ts:
            raise ValueError("comps deck needs at least one ticker")
        return comps_deck(data_service, ts, brand, req.get("title")), "Comps " + " ".join(ts[:5])
    if kind == "tearsheet":
        t = (req.get("ticker") or "").strip().upper()
        if not t:
            raise ValueError("tear sheet needs a ticker")
        return tear_sheet(data_service, index, t, brand), f"{t} profile"
    if kind == "dcf":
        payload = dcf_payload(req.get("cells") or {}, req.get("values") or {})
        return valuation_deck(payload, brand), f"{payload['ticker'] or 'DCF'} valuation"
    if kind == "valuation":
        return valuation_deck(req["payload"], brand), f"{req['payload'].get('ticker') or 'Valuation'} valuation"
    if kind == "rounds":
        raw = req.get("filters") or {}
        f = {k: raw[k] for k in ("q", "industry", "state", "date_from", "category") if raw.get(k)}
        if raw.get("min_sold"):
            f["min_sold"] = float(raw["min_sold"])
        if raw.get("equity_only") in (True, "1", 1):
            f["equity_only"] = True
        return rounds_deck(rounds, f, brand), "Funding market update"
    if kind == "answer":
        return answer_deck(req.get("question") or "Research question", req.get("result") or {}, brand), "Research note"
    raise ValueError(f"unknown deck kind: {kind}")
