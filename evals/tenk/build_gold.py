#!/usr/bin/env python3
"""Generate evals/tenk/gold.jsonl from the human label spec below.

Each label = (line regex, number of lines, normalised gold answer, unit/note). The quote is
taken verbatim from the trimmed PDF as om.pdfdoc extracts it (the geometry the grid uses), so it
is locatable by construction; the value was read from the page by the labeller. q01-q05 and q10
are then cross-checked against SEC XBRL company facts (data/raw/tenk/CIK*.facts.json).
Usage: python3 evals/tenk/build_gold.py
"""
import json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from om import pdfdoc  # noqa: E402

OUT = ROOT / "evals" / "tenk"
RAW = ROOT / "data" / "raw" / "tenk"
M, EPS, CNT, D, T = "usd_millions", "usd_per_share", "count", "date", "text"
Q = json.loads((OUT / "questions.json").read_text())["questions"]

def L(rx, n, val, unit, note=None): return dict(rx=rx, n=n, val=val, unit=unit, note=note)
SPEC = {
 "AAPL": {"q01": L(r"^Total net sales 478,834", 1, 478834, M), "q02": L(r"^Net income \$ 132,175", 1, 132175, M),
   "q03": L(r"^Diluted \$ 8\.98", 1, 8.98, EPS), "q04": L(r"^Total assets \$ 404,548", 1, 404548, M),
   "q05": L(r"^Cash and cash equivalents \$ 36,305", 1, 36305, M), "q06": L(r"approximately 167,000 full-time", 1, 167000, CNT, "full-time equivalent employees"),
   "q07": L(r"^For the fiscal year ended September 26, 2026", 1, "2026-09-26", D), "q08": L(r"^/s/ Ernst & Young LLP", 2, "Ernst & Young LLP", T),
   "q09": L(r"^California 94-2404110", 3, "California", T), "q10": L(r"^Term debt 68,208", 1, 68208, M)},
 "MSFT": {"q01": L(r"^Total revenue 331,839", 1, 331839, M), "q02": L(r"^Net income \$ 133,749", 1, 133749, M),
   "q03": L(r"^Diluted \$ 17\.95", 1, 17.95, EPS), "q04": L(r"^Total assets \$ 758,376", 1, 758376, M),
   "q05": L(r"^Cash and cash equivalents \$ 20,935", 1, 20935, M), "q06": L(r"we employed approximately 223,000 people", 2, 223000, CNT, "full-time"),
   "q07": L(r"^For the Fiscal Year Ended June 30, 2026", 1, "2026-06-30", D), "q08": L(r"Deloitte & Touche LLP has", 2, "Deloitte & Touche LLP", T),
   "q09": L(r"^WASHINGTON 91-1144442", 2, "Washington", T), "q10": L(r"^Long-term debt 31,067", 1, 31067, M)},
 "KO": {"q01": L(r"^Net Operating Revenues \$ 47,941", 1, 47941, M), "q02": L(r"^Net Income Attributable to Shareowners of The Coca-Cola$", 3, 13107, M, "attributable to shareowners of The Coca-Cola Company"),
   "q03": L(r"^\$ 3\.04 \$ 2\.46", 2, 3.04, EPS), "q04": L(r"^Total Assets \$ 104,816", 1, 104816, M),
   "q05": L(r"^Cash and cash equivalents \$ 10,270", 1, 10270, M), "q06": L(r"had approximately 65,900 and 69,700 employees", 1, 65900, CNT),
   "q07": L(r"^For the fiscal year ended December 31, 2025", 1, "2025-12-31", D), "q08": L(r"^/s/ Ernst & Young LLP", 2, "Ernst & Young LLP", T),
   "q09": L(r"^Delaware 58-0628465", 3, "Delaware", T), "q10": L(r"^Long-term debt 42,119", 1, 42119, M)},
 "JNJ": {"q01": L(r"^Sales to customers \$94,193", 1, 94193, M), "q02": L(r"^Net earnings \$26,804", 1, 26804, M),
   "q03": L(r"^Total net earnings per share - diluted \$11\.03", 1, 11.03, EPS), "q04": L(r"^Total assets \$199,210", 1, 199210, M),
   "q05": L(r"^Cash and cash equivalents \(Notes 1 and 2\) \$19,709", 1, 19709, M), "q06": L(r"approximately 138,200 employees worldwide", 1, 138200, CNT),
   "q07": L(r"^For the fiscal year ended December 28, 2025", 1, "2025-12-28", D), "q08": L(r"^/s/ PricewaterhouseCoopers LLP", 2, "PricewaterhouseCoopers LLP", T),
   "q09": L(r"^New Jersey 22-1024240", 2, "New Jersey", T), "q10": L(r"^Long-term debt \(Note 7\) 39,438", 1, 39438, M)},
 "PG": {"q01": L(r"^NET SALES \$ 87,032", 1, 87032, M), "q02": L(r"^Net earnings attributable to Procter & Gamble 16,046", 1, 16046, M, "attributable to Procter & Gamble"),
   "q03": L(r"^Diluted net earnings per common share 6\.62", 1, 6.62, EPS), "q04": L(r"^TOTAL ASSETS \$ 126,521", 1, 126521, M),
   "q05": L(r"^Cash and cash equivalents \$ 9,942", 1, 9942, M), "q06": L(r"had approximately 104,000 employees", 1, 104000, CNT),
   "q07": L(r"^For the Fiscal Year Ended June 30, 2026", 1, "2026-06-30", D), "q08": L(r"^/s/ Deloitte & Touche LLP", 2, "Deloitte & Touche LLP", T),
   "q09": L(r"^State of Incorporation: Ohio", 1, "Ohio", T), "q10": L(r"^LONG-TERM DEBT 22,842", 1, 22842, M)},
 "WMT": {"q01": L(r"^Total revenues 713,163", 1, 713163, M, "total revenues (net sales 706,413 plus membership and other income)"), "q02": L(r"^Consolidated net income attributable to Walmart \$ 21,893", 1, 21893, M, "attributable to Walmart"),
   "q03": L(r"^Diluted net income per common share attributable to Walmart 2\.73", 1, 2.73, EPS), "q04": L(r"^Total assets \$ 284,668", 1, 284668, M),
   "q05": L(r"^Cash and cash equivalents \$ 10,727", 1, 10727, M), "q06": L(r"approximately 2\.1 million associates around", 2, 2100000, CNT, "approximately 2.1 million associates"),
   "q07": L(r"^For the fiscal year ended January 31, 2026, or", 1, "2026-01-31", D), "q08": L(r"^/s/ Ernst & Young LLP", 2, "Ernst & Young LLP", T),
   "q09": L(r"^Delaware$", 4, "Delaware", T), "q10": L(r"^Long-term debt 34,624", 1, 34624, M)},
 "COST": {"q01": L(r"^Total revenue 303,154", 1, 303154, M), "q02": L(r"^NET INCOME \$ 9,226", 1, 9226, M),
   "q03": L(r"^Diluted \$ 20\.76", 1, 20.76, EPS), "q04": L(r"^TOTAL ASSETS \$ 89,045", 1, 89045, M),
   "q05": L(r"^Cash and cash equivalents \$ 20,207", 1, 20207, M), "q06": L(r"we employed 355,000 employees worldwide", 1, 355000, CNT),
   "q07": L(r"^For the fiscal year ended August 30, 2026", 1, "2026-08-30", D), "q08": L(r"^/s/ KPMG LLP", 2, "KPMG LLP", T),
   "q09": L(r"^Washington 91-1223280", 3, "Washington", T), "q10": L(r"^Long-term debt, excluding current portion 3,914", 1, 3914, M)},
 "HD": {"q01": L(r"^Net sales \$ 164,683", 1, 164683, M), "q02": L(r"^Net earnings \$ 14,156", 1, 14156, M),
   "q03": L(r"^Diluted earnings per share \$ 14\.23", 1, 14.23, EPS), "q04": L(r"^Total assets \$ 105,095", 1, 105095, M),
   "q05": L(r"^Cash and cash equivalents \$ 1,389", 1, 1389, M), "q06": L(r"we employed approximately 472,400 associates", 1, 472400, CNT),
   "q07": L(r"^For the fiscal year ended February 1, 2026", 1, "2026-02-01", D), "q08": L(r"^/s/ KPMG LLP", 2, "KPMG LLP", T),
   "q09": L(r"^Delaware 95-3261426", 2, "Delaware", T), "q10": L(r"^Long-term debt, excluding current installments 46,341", 1, 46341, M)},
 "MCD": {"q01": L(r"^Total revenues 26,885 25,920", 1, 26885, M), "q02": L(r"^Net income \$ 8,563 \$ 8,223", 1, 8563, M),
   "q03": L(r"^Earnings per common share.diluted \$ 11\.95", 1, 11.95, EPS), "q04": L(r"^Total assets \$ 59,515", 1, 59515, M),
   "q05": L(r"^Cash and equivalents \$ 774", 1, 774, M), "q06": L(r"^Over 150,000 people are employed", 1, 150000, CNT, "stated as 'Over 150,000' (Company and company-operated restaurants; excludes franchisee staff)"),
   "q07": L(r"^For the fiscal year ended December 31, 2025", 1, "2025-12-31", D), "q08": L(r"^/s/ Ernst & Young LLP", 2, "Ernst & Young LLP", T),
   "q09": L(r"^Delaware 36-2361282", 2, "Delaware", T), "q10": L(r"^Long-term debt 39,973", 1, 39973, M)},
 "LOW": {"q01": L(r"^Net sales \$ 86,286", 1, 86286, M), "q02": L(r"^Net earnings \$ 6,654", 1, 6654, M),
   "q03": L(r"Diluted earnings per common share decreased 3\.1%", 2, 11.85, EPS), "q04": L(r"^Total assets \$ 54,144", 1, 54144, M),
   "q05": L(r"^Cash and cash equivalents \$ 982", 1, 982, M), "q06": L(r"Lowe.s employed approximately 167,000 full-time associates", 1, 167000, CNT, "full-time associates only; 109,000 part-time also stated"),
   "q07": L(r"^For the fiscal year ended January 30, 2026", 1, "2026-01-30", D), "q08": L(r"^/s/ Deloitte & Touche LLP", 2, "Deloitte & Touche LLP", T),
   "q09": L(r"^North Carolina 56-0578072", 2, "North Carolina", T), "q10": L(r"^Long-term debt, excluding current maturities 37,490", 1, 37490, M)},
}
XBRL = {"q01": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
        "q02": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
        "q03": ["EarningsPerShareDiluted"], "q04": ["Assets"],
        "q05": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
        "q10": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtExcludingCurrentMaturities"]}

def norm(s): return re.sub(r"\s+", " ", s).strip()

def xbrl_check(cik, accession, fye, q, val):
    facts = json.loads((RAW / f"CIK{cik:010d}.facts.json").read_text())["facts"].get("us-gaap", {})
    seen = []
    for c in XBRL[q]:
        for unit, rows in facts.get(c, {}).get("units", {}).items():
            for r in rows:
                if r.get("end") != fye or r.get("accn") != accession:
                    continue
                if q in ("q01", "q02", "q03") and r.get("start") and (date.fromisoformat(fye) - date.fromisoformat(r["start"])).days < 300:
                    continue
                v = r["val"] if q == "q03" else r["val"] / 1e6
                seen.append((c, v))
                if abs(v - val) < (0.0051 if q == "q03" else 0.51):
                    return {"concept": f"us-gaap:{c}", "value": v, "match": True}
    return {"concept": None, "value": None, "match": False, "seen": seen}

def main():
    man = json.loads((OUT / "manifest.json").read_text())
    rows, bad = [], 0
    for f in man["filings"]:
        t = f["ticker"]; doc = pdfdoc.load(str(OUT / f["pdf"]))
        omap = {m["page"]: m["orig_page"] for m in f["page_map"]}
        for q in Q:
            s = SPEC[t][q["id"]]; rx = re.compile(s["rx"], re.I); hit = None
            for p in doc.pages:
                for i, l in enumerate(p.lines):
                    if rx.search(l.text):
                        hit = (p.number, norm(" ".join(x.text for x in p.lines[i:i + s["n"]]))); break
                if hit: break
            if not hit:
                print("NO MATCH", t, q["id"], s["rx"]); bad += 1; continue
            page, quote = hit
            assert 3 <= len(quote.split()) <= 40, (t, q["id"], quote)
            xc = xbrl_check(f["cik"], f["accession"], f["fiscal_year_end"], q["id"], s["val"]) if q["id"] in XBRL else None
            if xc and not xc["match"]: print("XBRL MISMATCH", t, q["id"], s["val"], xc.get("seen")[:6]); bad += 1
            row = {"cell_id": f"{t}-{q['id']}", "ticker": t, "pdf": f["pdf"], "question_id": q["id"], "question": q["question"], "type": q["type"],
                   "gold_answer": s["val"], "unit": s["unit"], "gold_quote": quote, "gold_page": page, "orig_page": omap[page], "xbrl_check": xc}
            if s["note"]: row["answer_note"] = s["note"]
            rows.append(row)
    (OUT / "gold.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(len(rows), "cells written;", bad, "problems")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
