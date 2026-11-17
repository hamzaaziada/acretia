"""Template fit (S4.9, parity items 42 and 46): deliver SEC-sourced numbers in a banker's own file structure.

  profile(ref_xlsx)                         infer a reference workbook's structure: sheets in order, header row and period
                                            columns, label column, line items (indent, bold, total, formula vs input,
                                            number format), fonts, fills, widths, freeze panes, units declaration
  mapping(profile, source_meta=None)        map each reference line item to one of our canonical keys (om.statements.LINES
                                            plus a few derived keys) with a deterministic synonym table, token
                                            normalisation and a similarity fallback with a confidence score
  generate(ref_xlsx, statements, ...)       a new workbook with the reference's sheets, order, labels, periods, formats,
                                            widths, freeze panes and colour code; historical cells are blue sourced
                                            inputs (comment: concept, period, accession; link: the filing); reference
                                            formulas are kept (same addresses, because the layout is reproduced)
  structure_diff(ref_xlsx, out_xlsx)        independent structural comparison, score 0..1

Rules the generator follows
  * Never a guessed number. A reference row with no canonical match stays in the output, empty, with the comment
    "not in source filings", and is listed in report["unmapped"]. Same for a period the filings do not cover.
  * Reference cells are copied cell for cell (text, styles, number formats). Only the numbers on mapped line-item rows
    are replaced. Reference formulas are kept at the same addresses; a formula that cannot be carried over (external
    link, unknown sheet) becomes SUM(mapped children above) and is flagged. A formula that would evaluate to an error
    because its inputs are not in the filings is cleared and flagged, never wrapped to hide the error.
  * Sign convention follows the reference: an expense row that the reference subtracts (`=C6-C7`) keeps the sign as
    filed (positive); one it adds, or whose reference values are negative, is shown as an outflow (negated).
  * Units: a reference declaring thousands gets x1000, billions /1000 (statements are in $m). Shares and EPS are not scaled.
  * Input colour: the reference's own input colour when it is blue-ish, otherwise standard blue (model checks need blue).
  * Fonts: om.xlsx writes Arial only; the reference font family is recorded in the profile but not reproduced.
  * Projection columns (E/F/P suffix): empty unless model_bytes is given. With a model, a `Model` sheet is added holding
    the model workbook's cached values for the mapped lines (blue, comment names the source cell), and projection cells
    are green links `=Model!X` (negated where the reference shows an outflow). Cross-workbook links would break when
    files move, and copying the model's formula network would drag its whole sheet graph; pasted values with a
    traceable comment are the simplest robust choice. Refresh by regenerating.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from . import formula as fx
from . import statements as stm
from . import xlsx as X

NS = X.NS
RNS = X.RNS
PNS = X.PNS

NOT_IN_FILINGS = "not in source filings"

BUILTIN_FMT = {0: None, 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 14: "mm-dd-yy", 15: "d-mmm-yy",
               16: "d-mmm", 17: "mmm-yy", 22: "m/d/yy h:mm", 37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)",
               39: "#,##0.00_);(#,##0.00)", 40: "#,##0.00_);[Red](#,##0.00)", 49: "@"}


# =========================================================================== raw XML (styles, widths, panes)
@dataclass
class _Parsed:
    book: X.Book
    xfs: list                       # per xf index: dict(fmt, color, bold, italic, size, underline, fill, top, bottom, indent, align, wrap, font)
    sheets: dict                    # name -> {"cells": {rc: xf}, "widths": {col: w}, "freeze": (rows, cols) | None}
    order: list


def _rgb(el) -> str | None:
    if el is None:
        return None
    v = el.get("rgb")
    return v[-6:].upper() if v else None


def _parse(data: bytes) -> _Parsed:
    book = X.read(data)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    xfs: list[dict] = []
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        codes = {int(n.get("numFmtId")): n.get("formatCode") for n in st.iter(f"{NS}numFmt")}
        fonts = []
        fe = st.find(f"{NS}fonts")
        for f in (fe.findall(f"{NS}font") if fe is not None else []):
            def on(tag):
                e = f.find(f"{NS}{tag}")
                return e is not None and e.get("val") not in ("0", "false")
            sz, nm = f.find(f"{NS}sz"), f.find(f"{NS}name")
            fonts.append({"color": _rgb(f.find(f"{NS}color")), "bold": on("b"), "italic": on("i"), "underline": f.find(f"{NS}u") is not None,
                          "size": float(sz.get("val")) if sz is not None else 10.0, "font": nm.get("val") if nm is not None else None})
        fills = []
        fle = st.find(f"{NS}fills")
        for f in (fle.findall(f"{NS}fill") if fle is not None else []):
            pf = f.find(f"{NS}patternFill")
            fills.append(_rgb(pf.find(f"{NS}fgColor")) if pf is not None and pf.get("patternType") == "solid" else None)
        borders = []
        be = st.find(f"{NS}borders")
        for b in (be.findall(f"{NS}border") if be is not None else []):
            t, bt = b.find(f"{NS}top"), b.find(f"{NS}bottom")
            borders.append((t is not None and t.get("style") is not None, bt is not None and bt.get("style") is not None))
        xe = st.find(f"{NS}cellXfs")
        for xf in (xe.findall(f"{NS}xf") if xe is not None else []):
            fid, flid, bid = int(xf.get("fontId") or 0), int(xf.get("fillId") or 0), int(xf.get("borderId") or 0)
            nid = int(xf.get("numFmtId") or 0)
            al = xf.find(f"{NS}alignment")
            fo = fonts[fid] if fid < len(fonts) else {"color": None, "bold": False, "italic": False, "underline": False, "size": 10.0, "font": None}
            top, bot = borders[bid] if bid < len(borders) else (False, False)
            xfs.append({**fo, "fmt": codes.get(nid, BUILTIN_FMT.get(nid)), "fill": fills[flid] if flid < len(fills) else None,
                        "top": top, "bottom": bot, "indent": int(al.get("indent") or 0) if al is not None else 0,
                        "align": al.get("horizontal") if al is not None else None,
                        "wrap": al is not None and al.get("wrapText") in ("1", "true")})
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wrels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PNS}Relationship"):
            wrels[r.get("Id")] = "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    sheets = {}
    for i, sh in enumerate(wb.iter(f"{NS}sheet")):
        part = wrels.get(sh.get(f"{RNS}id")) or f"xl/worksheets/sheet{i + 1}.xml"
        if part not in names:
            continue
        root = ET.fromstring(z.read(part))
        cells = {}
        for c in root.iter(f"{NS}c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r") or "")
            if m:
                cells[(int(m.group(2)), X.col_index(m.group(1)))] = int(c.get("s") or 0)
        widths = {}
        for col in root.iter(f"{NS}col"):
            if col.get("width") and col.get("customWidth") in ("1", "true"):
                for ci in range(int(col.get("min")), min(int(col.get("max")), int(col.get("min")) + 200) + 1):
                    widths[ci] = round(float(col.get("width")), 3)
        pane = root.find(f"{NS}sheetViews/{NS}sheetView/{NS}pane")
        freeze = None
        if pane is not None and pane.get("state") in ("frozen", "frozenSplit"):
            freeze = (int(float(pane.get("ySplit") or 0)), int(float(pane.get("xSplit") or 0)))
        sheets[sh.get("name")] = {"cells": cells, "widths": widths, "freeze": freeze}
    return _Parsed(book, xfs, sheets, list(book.order))


def _xf(P: _Parsed, name: str, rc: tuple) -> dict:
    i = P.sheets.get(name, {}).get("cells", {}).get(rc)
    if i is None or i >= len(P.xfs):
        return {"fmt": None, "color": None, "bold": False, "italic": False, "size": 10.0, "underline": False, "fill": None,
                "top": False, "bottom": False, "indent": 0, "align": None, "wrap": False, "font": None}
    return P.xfs[i]


# =========================================================================== periods
_P_PREFIXED = re.compile(r"^(?:FY|CY|FYE|F)\s*['’]?\s*((?:19|20)\d{2}|\d{2})\s*([AEFPB]|ACT|ACTUAL|EST|ESTIMATE|FORECAST|PROJ|BUDGET)?$", re.I)
_P_PLAIN = re.compile(r"^((?:19|20)\d{2})\s*([AEFPB]|ACT|ACTUAL|EST|ESTIMATE|FORECAST|PROJ|BUDGET)?$", re.I)
_P_MONTH = re.compile(r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-\s']\s*((?:19|20)?\d{2})\s*([AEFPB])?$", re.I)
_P_DATE = re.compile(r"^((?:19|20)\d{2})[-/]\d{1,2}[-/]\d{1,2}$|^\d{1,2}[-/]\d{1,2}[-/]((?:19|20)\d{2})$")
_PROJ = {"E", "F", "P", "B", "EST", "ESTIMATE", "FORECAST", "PROJ", "BUDGET"}


def _year2(y: str) -> int:
    n = int(y)
    return n if n >= 100 else (2000 + n if n < 70 else 1900 + n)


def _is_date_fmt(code: str | None) -> bool:
    return bool(code) and bool(re.search(r"[ymd]", re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.', "", code.lower())))


def parse_period(v, fmt: str | None = None) -> dict | None:
    """-> {"year", "projection", "label"} or None when the value is not a period header."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        if _is_date_fmt(fmt) and 20000 < v < 80000:
            y = (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(v))).year
            return {"year": y, "projection": False, "label": str(v)}
        if float(v).is_integer() and 1990 <= v <= 2100 and not _is_date_fmt(fmt):
            return {"year": int(v), "projection": False, "label": str(int(v))}
        return None
    s = str(v).strip()
    if not s:
        return None
    for rx in (_P_PREFIXED, _P_PLAIN, _P_MONTH):
        m = rx.match(s)
        if m:
            suf = (m.group(2) or "").upper() if m.lastindex and m.lastindex >= 2 else ""
            return {"year": _year2(m.group(1)), "projection": suf in _PROJ, "label": s}
    m = _P_DATE.match(s)
    if m:
        return {"year": int(m.group(1) or m.group(2)), "projection": False, "label": s}
    return None


# =========================================================================== profile
_UNIT_RX = [(re.compile(r"in\s+thousands|\$\s?000s?|\b000s\b|\bthousands?\b|\(\$?k\)|\$k\b|\busd\s?k\b", re.I), 1000.0, "thousands"),
            (re.compile(r"in\s+billions|\bbillions?\b|\$\s?bn\b|\busd\s?bn\b|\$b\b", re.I), 0.001, "billions"),
            (re.compile(r"in\s+millions|\bmillions?\b|\$\s?mm?\b|\busd\s?mm?\b|\b(?:eur|gbp|usd|€|£|\$)\s?m\b|\bmm\b", re.I), 1.0, "millions")]
_STMT_HINT = [("CF", re.compile(r"cash\s*flow|\bcf\b|cashflow|cash flows", re.I)),
              ("BS", re.compile(r"balance|\bbs\b|financial position|assets|liabilit", re.I)),
              ("IS", re.compile(r"income|\bis\b|p\s*&\s*l|profit|operations|earnings|statement of op", re.I))]
RATIO_WORDS = re.compile(r"%|margin|growth|yoy|y/y|ratio|per cent|percent|multiple|\bx\b|turnover days|days", re.I)


def _statement_hint(text: str) -> str | None:
    for st, rx in _STMT_HINT:
        if rx.search(text or ""):
            return st
    return None


def _blueish(c: str | None) -> bool:
    if not c or len(c) != 6:
        return False
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return b > 100 and b > r + 40 and b > g + 20


def _sheet_profile(P: _Parsed, name: str) -> dict:
    grid = P.book.sheets[name]
    raw = P.sheets[name]
    maxr = max((r for r, _ in grid), default=0)

    def fmt_of(rc):
        return _xf(P, name, rc)["fmt"]

    # header row: first row (within 25) with >= 2 period-looking cells, preferring the row with most
    header, best = None, 0
    for r in range(1, min(maxr, 25) + 1):
        pcs = [(c, parse_period(cell.value, fmt_of((r, c)))) for (rr, c), cell in grid.items()
               if rr == r and not cell.formula and cell.value not in (None, "")]
        pcs = [(c, p) for c, p in pcs if p]
        if len(pcs) >= 2 and len(pcs) > best:
            header, best = r, len(pcs)
            if len(pcs) >= 3:
                break
    periods = []
    if header:
        for (rr, c), cell in sorted(grid.items(), key=lambda t: t[0][1]):
            if rr == header and not cell.formula:
                p = parse_period(cell.value, fmt_of((rr, c)))
                if p:
                    periods.append({"col": c, "label": cell.value if isinstance(cell.value, str) else p["label"], **{k: p[k] for k in ("year", "projection")}})
    pcols = {p["col"] for p in periods}
    first_p = min(pcols) if pcols else 3
    # label column: text-rich column left of the first period column
    counts: dict[int, int] = {}
    for (r, c), cell in grid.items():
        if header and r <= header or c >= first_p:
            continue
        if isinstance(cell.value, str) and cell.value.strip() and not cell.formula:
            counts[c] = counts.get(c, 0) + 1
    label_col = max(counts, key=lambda c: (counts[c], -c)) if counts else 1
    # units declaration: any text up to the header row (or first 8 rows) mentioning a scale
    units = {"text": None, "scale": 1.0, "label": None}
    for (r, c), cell in sorted(grid.items()):
        if r > (header or 8) + 0 or not isinstance(cell.value, str):
            continue
        for rx, scale, nm in _UNIT_RX:
            if rx.search(cell.value):
                units = {"text": cell.value, "scale": scale, "label": nm}
                break
        if units["text"]:
            break
    # line items
    items, section = [], None
    sheet_hint = _statement_hint(name)
    for r in range(((header or 0) + 1), maxr + 1):
        lc = grid.get((r, label_col))
        label = lc.value.strip() if lc is not None and isinstance(lc.value, str) and lc.value.strip() else None
        if not label or lc.formula:
            continue
        pv = [grid.get((r, c)) for c in sorted(pcols)]
        pv = [x for x in pv if x is not None and (x.formula or x.value not in (None, ""))]
        st = _xf(P, name, (r, label_col))
        has_formula = any(x.formula for x in pv)
        first_num = next((fmt_of((r, c)) for c in sorted(pcols) if (r, c) in grid and (grid[(r, c)].formula or grid[(r, c)].value not in (None, ""))), None) \
            or next((fmt_of((r, c)) for c in sorted(pcols) if (r, c) in raw["cells"]), None)
        is_section = not pv and (st["bold"] or st["fill"] is not None or label.isupper() or st["bottom"])
        item = {"row": r, "label": label, "indent": st["indent"], "bold": st["bold"], "total": st["top"] or bool(has_formula and st["bold"]),
                "section": bool(is_section), "formula": bool(has_formula), "has_values": bool(pv), "fmt": first_num,
                "ratio": bool(RATIO_WORDS.search(label)) or bool(first_num and "%" in first_num),
                "section_name": section, "statement_hint": _statement_hint(section or "") or sheet_hint}
        if is_section:
            section = label
            item["statement_hint"] = _statement_hint(label) or sheet_hint
        items.append(item)
    # colour code: font colours of numeric inputs / formulas / cross-sheet links in the period area
    cc: dict[str, dict] = {"input": {}, "formula": {}, "link": {}}
    for (r, c), cell in grid.items():
        if c not in pcols or header is None or r <= header:
            continue
        col = _xf(P, name, (r, c))["color"]
        if cell.formula:
            cc["link" if X.CROSS_SHEET.search(cell.formula) else "formula"][col] = cc["link" if X.CROSS_SHEET.search(cell.formula) else "formula"].get(col, 0) + 1
        elif isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
            cc["input"][col] = cc["input"].get(col, 0) + 1
    hxf = _xf(P, name, (header, min(pcols))) if header and pcols else None
    fonts = {}
    for (r, c), _cell in list(grid.items())[:400]:
        f = _xf(P, name, (r, c))["font"]
        if f:
            fonts[f] = fonts.get(f, 0) + 1
    return {"name": name, "header_row": header, "periods": periods, "label_col": label_col, "units": units, "items": items,
            "freeze": raw["freeze"], "widths": dict(raw["widths"]), "statement_hint": sheet_hint,
            "header_style": {k: hxf[k] for k in ("color", "bold", "fill", "fmt", "align", "size")} if hxf else None,
            "fonts": sorted(fonts, key=lambda f: -fonts[f]), "colours": {k: max(v, key=v.get) if v else None for k, v in cc.items()}}


def profile(ref_xlsx: bytes) -> dict:
    """Infer the reference workbook's structure. Pure parse: no network, no model."""
    P = _parse(ref_xlsx)
    sheets = [_sheet_profile(P, n) for n in P.order if n in P.sheets]
    inp = [s["colours"]["input"] for s in sheets if s["colours"]["input"]]
    return {"order": [s["name"] for s in sheets], "sheets": sheets,
            "colour_code": {"input": inp[0] if inp else None,
                            "formula": next((s["colours"]["formula"] for s in sheets if s["colours"]["formula"]), None),
                            "link": next((s["colours"]["link"] for s in sheets if s["colours"]["link"]), None)}}


# =========================================================================== mapping
# canonical key -> synonym phrases (normalised below). Keys: om.statements.LINES plus derived ebitda, total_debt.
SYNONYMS: dict[str, list[str]] = {
    "revenue": ["revenue", "revenues", "net sales", "sales", "total sales", "net revenue", "net revenues", "total revenue",
                "total revenues", "turnover", "net turnover", "total net sales", "top line", "total net revenue", "sales revenue"],
    "cogs": ["cost of sales", "cost of goods sold", "cogs", "cost of revenue", "cost of revenues", "cost of goods sold and services",
             "direct costs", "cost of products sold", "cost of sales and services", "total cost of sales", "cost of goods"],
    "gross_profit": ["gross profit", "gross income", "gross result", "gross profit reported", "gross margin amount"],
    "rd": ["research and development", "r and d", "r and d expense", "research development", "research and development expense",
           "product development", "technology and development", "research and development costs"],
    "sga": ["sga", "sg and a", "selling general and administrative", "selling general administrative", "selling general and administrative expense",
            "selling general administrative expense", "sg and a expense", "general and administrative", "selling and administrative expense",
            "sales general and administrative"],
    "ebit": ["operating income", "operating profit", "ebit", "income from operations", "operating earnings", "profit from operations",
             "operating profit ebit", "operating income loss", "earnings before interest and tax", "operating result"],
    "interest_expense": ["interest expense", "finance costs", "finance cost", "interest and debt expense", "financial expense", "interest expense net",
                         "interest paid expense"],
    "interest_income": ["interest income", "finance income", "investment income", "interest and other income", "financial income"],
    "pretax": ["pre tax income", "pretax income", "profit before tax", "income before taxes", "income before tax", "ebt", "pbt",
               "income before income taxes", "earnings before tax", "earnings before taxes", "profit before taxation", "pre tax profit"],
    "tax": ["income tax", "income taxes", "tax expense", "provision for income taxes", "taxes", "income tax expense", "taxation", "tax charge",
            "provision for taxes"],
    "net_income": ["net income", "net profit", "net earnings", "profit for the year", "profit after tax", "pat", "net income to common",
                   "net income attributable to common", "profit for the period", "net income loss", "earnings", "net profit after tax"],
    "diluted_shares": ["diluted shares", "diluted weighted average shares", "weighted average diluted shares", "shares outstanding diluted",
                       "diluted shares outstanding", "weighted average shares diluted", "diluted share count", "shares diluted"],
    "eps_diluted": ["diluted eps", "eps diluted", "earnings per share diluted", "eps", "diluted earnings per share", "earnings per share"],
    "cash": ["cash and cash equivalents", "cash", "cash and equivalents", "cash and bank balances", "cash and short term deposits"],
    "sti": ["short term investments", "marketable securities", "short term investment", "current investments", "investments short term"],
    "ar": ["accounts receivable", "trade receivables", "receivables", "debtors", "trade and other receivables", "accounts receivable net",
           "trade debtors", "net receivables"],
    "inventory": ["inventory", "inventories", "stock", "stocks", "inventory net"],
    "current_assets": ["total current assets", "current assets", "total current asset"],
    "ppe": ["ppe net", "ppe", "property plant and equipment", "fixed assets", "net fixed assets", "tangible assets", "pp and e net",
            "property plant equipment net", "pp and e", "property and equipment net"],
    "goodwill": ["goodwill"],
    "intangibles": ["intangible assets", "other intangibles", "intangibles", "intangible assets net", "intangible assets excluding goodwill"],
    "assets": ["total assets"],
    "ap": ["accounts payable", "trade payables", "creditors", "trade and other payables", "payables", "trade creditors", "accounts payable trade"],
    "debt_current": ["short term debt", "current portion of long term debt", "current debt", "short term borrowings", "current borrowings",
                     "current portion of debt", "debt current"],
    "current_liabilities": ["total current liabilities", "current liabilities"],
    "debt_noncurrent": ["long term debt", "long term borrowings", "non current debt", "term debt", "non current borrowings", "long term debt net",
                        "borrowings non current"],
    "liabilities": ["total liabilities"],
    "equity_parent": ["shareholders equity", "stockholders equity", "total shareholders equity", "total stockholders equity", "equity",
                      "shareholders funds", "equity attributable to shareholders", "equity attributable to owners", "shareowners equity"],
    "liabilities_equity": ["total liabilities and equity", "total liabilities and shareholders equity", "total liabilities and stockholders equity",
                           "total equity and liabilities", "total liabilities equity", "total liabilities and shareholders funds"],
    "equity_total": ["total equity", "total equity including nci", "total equity incl nci", "total equity including minority interest"],
    "cf_net_income": ["net income incl nci", "net income including noncontrolling interest", "net income including nci"],
    "da": ["depreciation and amortization", "d and a", "depreciation amortization", "depreciation and amortisation", "depreciation",
           "depreciation amortisation", "da", "depreciation depletion and amortization", "amortization and depreciation"],
    "sbc": ["stock based compensation", "share based compensation", "sbc", "stock compensation", "share based payments", "stock based comp"],
    "cfo": ["cash from operations", "cash flow from operating activities", "net cash from operating activities", "operating cash flow", "cfo",
            "cash flows from operating activities", "net cash provided by operating activities", "cash from operating activities",
            "net cash generated from operating activities"],
    "capex": ["capex", "capital expenditure", "capital expenditures", "purchases of ppe", "purchase of property plant and equipment",
              "additions to ppe", "purchases of property plant and equipment", "purchase of ppe", "capital spending", "investment in ppe"],
    "acquisitions": ["acquisitions", "acquisitions net of cash acquired", "acquisition of businesses", "business acquisitions", "acquisitions net of cash"],
    "cfi": ["cash from investing", "cash flow from investing activities", "net cash from investing activities", "cash from investing activities",
            "cash flows from investing activities", "net cash used in investing activities", "cfi"],
    "dividends": ["dividends paid", "dividends", "dividend payments", "cash dividends paid", "payment of dividends"],
    "buybacks": ["share repurchases", "repurchase of common stock", "stock buyback", "share buybacks", "buybacks", "purchase of treasury shares",
                 "repurchases of common stock", "share repurchase"],
    "cff": ["cash from financing", "cash flow from financing activities", "net cash from financing activities", "cash from financing activities",
            "cash flows from financing activities", "net cash used in financing activities", "cff"],
    "net_change_cash": ["net change in cash", "net increase decrease in cash", "net change in cash and cash equivalents", "change in cash",
                        "net increase in cash", "net cash flow", "net increase decrease in cash and cash equivalents"],
    "ebitda": ["ebitda", "adjusted ebitda", "ebitda reported"],
    "total_debt": ["total debt", "gross debt", "total borrowings", "debt total"],
}
DERIVED = {"ebitda": ("IS", "EBITDA", ("ebit", "da")), "total_debt": ("BS", "Total debt", ("debt_current", "debt_noncurrent"))}
_NOTE = re.compile(r"^(source|sources|note|notes|memo)\b|:\s*$", re.I)
_STOP = {"of", "the", "and", "for", "in", "on", "to", "a", "an", "less", "plus", "total_"}


def _canon_stmt(key: str) -> str:
    return stm.LINES[key][0] if key in stm.LINES else DERIVED[key][0]


def _norm(s: str) -> list[str]:
    s = (s or "").lower().replace("&", " and ").replace("’", "").replace("'", "")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9% ]", " ", s)
    s = re.sub(r"\b(?:less|plus|note\s*\d+)\b", " ", s)
    toks = []
    for t in s.split():
        if t in _STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        toks.append(t)
    return toks


def _build_index(extra: dict | None = None):
    exact: dict[str, list[str]] = {}
    sets: dict[frozenset, list[str]] = {}
    phrases: list[tuple[str, str]] = []
    table = {k: list(v) for k, v in SYNONYMS.items()}
    for k in stm.LINES:
        table.setdefault(k, []).append(stm.LINES[k][3])
    for k, (_st, label, _c) in DERIVED.items():
        table.setdefault(k, []).append(label)
    for phrase, key in (extra or {}).items():
        table.setdefault(key, []).append(phrase)
    for key, ps in table.items():
        for p in ps:
            toks = _norm(p)
            if not toks:
                continue
            j = " ".join(toks)
            exact.setdefault(j, [])
            if key not in exact[j]:
                exact[j].append(key)
            sets.setdefault(frozenset(toks), [])
            if key not in sets[frozenset(toks)]:
                sets[frozenset(toks)].append(key)
            phrases.append((j, key))
    return exact, sets, phrases


def _pick(keys: list[str], hint: str | None) -> str:
    if hint:
        for k in keys:
            if _canon_stmt(k) == hint:
                return k
    return keys[0]


def map_label(label: str, hint: str | None = None, *, extra: dict | None = None) -> dict | None:
    """-> {"key", "confidence", "method"} or None. Ratio rows ('% margin', 'growth') never map."""
    if RATIO_WORDS.search(label or ""):
        return None
    exact, sets, phrases = _build_index(extra)
    toks = _norm(label)
    if not toks:
        return None
    j = " ".join(toks)
    if j in exact:
        return {"key": _pick(exact[j], hint), "confidence": 1.0, "method": "synonym"}
    fs = frozenset(toks)
    if fs in sets:
        return {"key": _pick(sets[fs], hint), "confidence": 0.95, "method": "tokens"}
    best, bk = 0.0, None
    for p, key in phrases:
        pt = set(p.split())
        jac = len(pt & fs) / len(pt | fs)
        score = max(difflib.SequenceMatcher(None, j, p).ratio(), jac * 0.95)
        if hint and _canon_stmt(key) == hint:
            score += 0.02
        if score > best:
            best, bk = score, key
    if bk and best >= 0.8:
        return {"key": bk, "confidence": round(min(best, 0.94), 3), "method": "fuzzy"}
    return None


def mapping(profile: dict, source_meta: dict | None = None) -> dict:
    """Map every reference line item to a canonical key.

    source_meta (optional): {"synonyms": {phrase: key}, "available": [keys with data]}; default: every LINES key.
    Returns {"rows": {sheet: {row: {"key", "confidence", "method", "label"}}}, "unmapped": [...], "low_confidence": [...]}."""
    meta = source_meta or {}
    extra = meta.get("synonyms")
    available = set(meta["available"]) if meta.get("available") is not None else None
    rows: dict[str, dict] = {}
    unmapped, low = [], []
    for sh in profile["sheets"]:
        rows[sh["name"]] = {}
        for it in sh["items"]:
            if it["section"]:
                continue
            if _NOTE.match(it["label"]):
                continue
            if it["ratio"]:
                if not it["formula"]:                              # a margin/growth formula row is carried over, not mapped
                    unmapped.append({"sheet": sh["name"], "row": it["row"], "label": it["label"], "reason": "ratio row (not a filed line)"})
                continue
            m = map_label(it["label"], it["statement_hint"], extra=extra)
            if m and available is not None and m["key"] not in available:
                m = None
            if not m:
                if it["formula"]:
                    continue                                       # an unmapped subtotal keeps the reference formula
                unmapped.append({"sheet": sh["name"], "row": it["row"], "label": it["label"], "reason": "no canonical line matches"})
                continue
            rows[sh["name"]][it["row"]] = {**m, "label": it["label"]}
            if m["confidence"] < 0.9:
                low.append({"sheet": sh["name"], "row": it["row"], "label": it["label"], "key": m["key"], "confidence": m["confidence"]})
    return {"rows": rows, "unmapped": unmapped, "low_confidence": low}


# =========================================================================== values from statements
def _value(st: stm.Statements, key: str, i: int):
    """-> (value $m / shares m / per-share, sources text) for fiscal year index i, or (None, '')."""
    if key in stm.LINES:
        it = st.data[key][i]
        return it.value, it.source()
    if key in DERIVED:
        parts = [_value(st, k, i) for k in DERIVED[key][2]]
        if key == "total_debt":
            vals = [p[0] for p in parts if p[0] is not None]
            if not vals:
                return None, ""
            v = sum(vals)
        else:                                                      # ebitda = ebit + d&a
            if any(p[0] is None for p in parts):
                return None, ""
            v = sum(p[0] for p in parts)
        names = " + ".join(f"{k}" for k in DERIVED[key][2])
        return v, f"Derived: {key} = {names}\n" + "\n".join(p[1] for p in parts if p[1])
    return None, ""


# =========================================================================== formula helpers
_REF = re.compile(r"(?:(?:'([^']+)'|([A-Za-z_][\w.]*))!)?(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\w(])")


def _operator_before(formula: str, row: int) -> str | None:
    """'+' or '-' when `formula` uses a same-sheet cell of `row` as a direct additive term (paren depth 0, not in a product,
    quotient or function), else None."""
    f = formula[1:] if formula.startswith("=") else formula
    depth, i, prev = 0, 0, None
    while i < len(f):
        ch = f[i]
        if ch == '"':
            j = f.find('"', i + 1)
            i = (j if j > 0 else len(f)) + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch in "+-*/^" and depth == 0:
            prev = ch
        elif (ch.isalpha() or ch in "$'") and (i == 0 or not (f[i - 1].isalnum() or f[i - 1] in "._!")):
            m = _REF.match(f, i)
            if m:
                nxt = f[m.end()] if m.end() < len(f) else ""
                if depth == 0 and not m.group(1) and not m.group(2) and int(m.group(6)) == row and prev not in ("*", "/", "^") \
                        and nxt not in ("*", "/", "^", ":"):
                    return prev or "+"
                i = m.end()
                continue
        i += 1
    return None


def _children_above(r: int, rows_ok: set[int]) -> tuple[int, int] | None:
    top, rr = None, r - 1
    while rr in rows_ok:
        top, rr = rr, rr - 1
    return (top, r - 1) if top else None


# =========================================================================== generate
def _model_lines(model_bytes: bytes, model_meta: dict | None):
    """-> (book, {canonical key: (sheet, row)}, {year: col}) for the supplied model3 workbook."""
    mb = X.read(model_bytes)
    tbl = {  # model3 row key -> canonical key, per sheet
        "IS": {"rev": "revenue", "cogs": "cogs", "gp": "gross_profit", "rd": "rd", "sga": "sga", "ebit": "ebit", "int_exp": "interest_expense",
               "int_inc": "interest_income", "pretax": "pretax", "tax": "tax", "ni": "net_income", "shares": "diluted_shares",
               "eps": "eps_diluted", "ebitda": "ebitda"},
        "BS": {"cash": "cash", "sti": "sti", "ar": "ar", "inv": "inventory", "tca": "current_assets", "ppe": "ppe", "gw": "goodwill",
               "intang": "intangibles", "ta": "assets", "ap": "ap", "tl": "liabilities", "se": "equity_parent", "tle": "liabilities_equity",
               "te": "equity_total"},
        "CF": {"ni": "cf_net_income", "da": "da", "sbc": "sbc", "cfo": "cfo", "capex": "capex", "acq": "acquisitions", "cfi": "cfi",
               "div": "dividends", "bb": "buybacks", "cff": "cff"}}
    lines: dict[str, tuple] = {}
    meta_rows = (model_meta or {}).get("rows") or {}
    for sh, mp in tbl.items():
        if sh not in mb.sheets:
            continue
        if sh in meta_rows:
            for mk, ck in mp.items():
                if mk in meta_rows[sh]:
                    lines.setdefault(ck, (sh, meta_rows[sh][mk]))
        else:                                                       # no meta: match column A labels with our own mapper
            for (r, c), cell in mb.sheets[sh].items():
                if c == 1 and isinstance(cell.value, str):
                    m = map_label(cell.value, sh)
                    if m and _canon_stmt(m["key"]) == sh and m["confidence"] >= 0.95:
                        lines.setdefault(m["key"], (sh, r))
    years: dict[int, int] = {}
    hdr = mb.sheets.get("IS", {})
    for (r, c), cell in hdr.items():
        if r == 5 and c >= 3:
            p = parse_period(cell.value)
            if p:
                years[p["year"]] = c
    return mb, lines, years


def generate(ref_xlsx: bytes, statements: stm.Statements, *, model_meta: dict | None = None,
             model_bytes: bytes | None = None) -> tuple[bytes, dict]:
    P = _parse(ref_xlsx)
    prof = profile(ref_xlsx)
    mp = mapping(prof)
    year_idx = {d.year: i for i, d in enumerate(statements.years)}
    wb = X.Workbook()
    report: dict = {"formulas": [], "flags": [], "unmapped": list(mp["unmapped"]), "low_confidence": list(mp["low_confidence"]),
                    "mapped": [], "filled": 0, "empty_periods": [], "signs": [], "notes": [], "ties": [], "cleared": []}
    colour = prof["colour_code"]["input"]
    if colour and not _blueish(colour):
        report["notes"].append(f"reference input colour {colour} is not blue; standard blue used so model checks can read the colour code")
        colour = None
    colour = colour or X.BLUE
    mb = mlines = myears = None
    model_rows: dict[str, int] = {}
    if model_bytes:
        mb, mlines, myears = _model_lines(model_bytes, model_meta)
    sheet_names = set(P.order)
    model_name = "Model" if "Model" not in sheet_names else "Model_link"

    placed: dict[tuple, str] = {}           # (sheet, r, c) -> kind of the cell we wrote (for the report)
    for sp in prof["sheets"]:
        name = sp["name"]
        sh = wb.sheet(name)
        grid, raw = P.book.sheets[name], P.sheets[name]
        sh.freeze = raw["freeze"]
        for c, w in raw["widths"].items():
            sh.width(c, w)
        pcol = {p["col"]: p for p in sp["periods"]}
        items = {it["row"]: it for it in sp["items"]}
        rmap = mp["rows"][name]
        scale = sp["units"]["scale"]
        # which item rows will hold data (children for SUM fallbacks)
        data_rows = {r for r in rmap if not items[r]["formula"]}

        def style_kw(rc, xf=None):
            xf = xf or _xf(P, name, rc)
            return dict(fmt=xf["fmt"], bold=xf["bold"], italic=xf["italic"], size=xf["size"] or 10, fill=xf["fill"], top=xf["top"],
                        bottom=xf["bottom"], indent=xf["indent"], align=xf["align"], underline=xf["underline"], wrap=xf["wrap"])

        def sign_for(r: int, key: str) -> bool:
            """True when the generated value is negated (shown as an outflow)."""
            if key not in stm.LINES or stm.LINES[key][2] != -1:
                return False
            ops = []
            for it in sp["items"]:
                if it["formula"]:
                    for c in sorted(pcol):
                        cell = grid.get((it["row"], c))
                        if cell is not None and cell.formula:
                            op = _operator_before(cell.formula, r)
                            if op:
                                ops.append(op)
                            break
            if ops:
                return ops[0] == "+"
            for c in sorted(pcol):
                cell = grid.get((r, c))
                if cell is not None and isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool) and cell.value != 0:
                    return cell.value < 0
            return False

        neg = {r: sign_for(r, m["key"]) for r, m in rmap.items()}
        for r, m in rmap.items():
            report["mapped"].append({"sheet": name, "row": r, "label": m["label"], "key": m["key"], "confidence": m["confidence"]})
            report["signs"].append({"sheet": name, "row": r, "key": m["key"], "convention": "outflow (negated)" if neg[r] else "as filed"})
        unmapped_rows = {u["row"] for u in mp["unmapped"] if u["sheet"] == name}

        coords = set(grid) | set(raw["cells"])
        for (r, c) in sorted(coords):
            cell = grid.get((r, c))
            xf = _xf(P, name, (r, c))
            kw = style_kw((r, c), xf)
            val = cell.value if cell is not None else None
            formula = cell.formula if cell is not None else None
            item = items.get(r)
            in_period = c in pcol and sp["header_row"] and r > sp["header_row"] and item is not None and not item["section"]
            font_color = xf["color"]
            # ---------------- line-item period cells
            if in_period and r in rmap and not item["formula"]:
                p = pcol[c]
                key, flip = rmap[r]["key"], neg[r]
                money = key not in ("diluted_shares", "eps_diluted")
                f_ = scale if money else 1.0
                if p["projection"]:
                    if mlines and key in mlines and p["year"] in myears:
                        msheet, mrow = mlines[key]
                        mr = model_rows.setdefault(key, len(model_rows) + 4)
                        mflip = False
                        if key in stm.LINES and stm.LINES[key][2] == -1:       # model shows expenses as outflows
                            mflip = not flip
                        f = f"={'-' if mflip else ''}{X.quote_sheet(model_name)}!{X.ref(mr, 2 + list(sorted(myears)).index(p['year']) + 1)}"
                        sh.set((r, c), f, **{**kw, "color": X.GREEN, "fill": kw["fill"] if kw["fill"] != X.INPUT_FILL else None})
                        placed[(name, r, c)] = "link"
                    else:
                        sh.set((r, c), None, **kw, color=font_color)
                        report["empty_periods"].append({"sheet": name, "row": r, "col": X.col_letter(c), "reason": "projection column: no model supplied"
                                                        if not mlines else "line not in the model"})
                    continue
                i = year_idx.get(p["year"])
                v, src = (None, "")
                if i is not None:
                    v, src = _value(statements, key, i)
                if v is None:
                    sh.set((r, c), None, **kw, color=font_color,
                           comment=None if i is not None else None)
                    report["empty_periods"].append({"sheet": name, "row": r, "col": X.col_letter(c),
                                                    "reason": f"FY{p['year']} not in the filings" if i is None else f"{key}: no filed value for FY{p['year']}"})
                    continue
                out = v * f_ * (-1 if flip else 1)
                note = f"FY{p['year']} · {rmap[r]['label']} ← {key}" + (" (shown as outflow: sign flipped)" if flip else "") + \
                       (f" (×{scale:g} for {sp['units']['label']})" if f_ != 1.0 else "")
                url = statements.filings[i]["url"] if i < len(statements.filings) else None
                sh.set((r, c), out, kind="hist", **{**kw, "fill": kw["fill"] if kw["fill"] != X.INPUT_FILL else None}, color=colour,
                       comment=note + "\n" + src, link=url)
                report["filled"] += 1
                placed[(name, r, c)] = "hist"
                continue
            # ---------------- unmapped / ratio input rows: kept empty and flagged
            if in_period and not item["formula"] and (r in unmapped_rows or r not in rmap):
                sh.set((r, c), None, **kw, color=font_color)
                continue
            # ---------------- formulas
            if formula:
                f, status = _carry(formula, name, sheet_names)
                is_proj = c in pcol and pcol[c]["projection"]
                if is_proj and not mlines:
                    sh.set((r, c), None, **kw, color=font_color)
                    report["empty_periods"].append({"sheet": name, "row": r, "col": X.col_letter(c), "reason": "projection column: no model supplied"})
                    continue
                if f is None:
                    rows_ok = data_rows | {rr for rr in items if items[rr]["formula"] is False and rr in rmap}
                    rng = _children_above(r, rows_ok)
                    if rng:
                        col = X.col_letter(c)
                        f = f"=SUM({col}{rng[0]}:{col}{rng[1]})"
                        report["formulas"].append({"sheet": name, "cell": X.ref(r, c), "reference": formula, "output": f, "status": f"fallback SUM of mapped children ({status})"})
                        report["flags"].append(f"{name}!{X.ref(r, c)}: formula could not be carried over ({status}); SUM of mapped children used")
                    else:
                        sh.set((r, c), None, **kw, color=font_color)
                        report["flags"].append(f"{name}!{X.ref(r, c)}: formula could not be carried over ({status}); no mapped children, left empty")
                        continue
                else:
                    report["formulas"].append({"sheet": name, "cell": X.ref(r, c), "reference": formula, "output": f, "status": "carried over (layout reproduced, same addresses)"})
                sh.set((r, c), f, **{**kw, "fill": kw["fill"] if kw["fill"] != X.INPUT_FILL else None})
                placed[(name, r, c)] = "formula"
                continue
            # ---------------- everything else: copy as-is
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                is_input = c not in pcol
                sh.set((r, c), val, kind="hist" if is_input else "text", **kw, color=font_color if font_color else None)
            elif val is None or val == "":
                sh.set((r, c), None, **kw, color=font_color)
            else:
                lab = (r in items and c == sp["label_col"])
                cm = NOT_IN_FILINGS if lab and r in unmapped_rows and not items[r]["formula"] else None
                sh.set((r, c), str(val), kind="text", **kw, color=font_color, comment=cm)
        # flag unmapped rows (label comment already set) in the report counts

    # ---------------- Model sheet (projection links)
    if mlines and model_rows:
        ms = wb.sheet(model_name)
        ms.set("A1", "Model forecast values pasted from the supplied model workbook (cached results; regenerate to refresh)", kind="title")
        ms.set((3, 1), "Line", kind="header")
        ms.set((3, 2), "Key", kind="header")
        ys = sorted(myears)
        for j, y in enumerate(ys):
            ms.set((3, 3 + j), f"FY{y}", kind="header", align="right")
            ms.width(3 + j, 12)
        ms.width("A", 40)
        for key, rr in model_rows.items():
            msheet, mrow = mlines[key]
            ms.set((rr, 1), stm.LINES[key][3] if key in stm.LINES else DERIVED[key][1])
            ms.set((rr, 2), key)
            for j, y in enumerate(ys):
                cv = mb.sheets[msheet].get((mrow, myears[y]))
                if cv is not None and isinstance(cv.value, (int, float)) and not isinstance(cv.value, bool):
                    ms.set((rr, 3 + j), cv.value, kind="hist", fmt="num1" if key in ("diluted_shares",) else "num0",
                           comment=f"Cached value of {msheet}!{X.ref(mrow, myears[y])} in the supplied model workbook")
        ms.freeze = (3, 2)
        report["notes"].append(f"projection columns link to the {model_name} sheet, which holds the model's cached values")

    # ---------------- calculate; clear formulas that error because their inputs are not in the filings
    cleared: list[str] = []
    for _ in range(4):
        fx.calculate_workbook(wb)
        bad = []
        for s in wb.sheets:
            for (r, c), cell in s.cells.items():
                if isinstance(cell.value, str) and cell.value.startswith("=") and (isinstance(cell.cached, fx.Err)
                                                                               or (isinstance(cell.cached, str) and cell.cached.startswith("#"))):
                    bad.append((s, r, c))
        if not bad:
            break
        for s, r, c in bad:
            old = s.cells[(r, c)]
            s.set((r, c), None, fmt=old.style.fmt, bold=old.style.bold, italic=old.style.italic, size=old.style.size, fill=old.style.fill,
                  top=old.style.top, bottom=old.style.bottom, indent=old.style.indent, align=old.style.align, color=old.style.color)
            cleared.append(f"{s.name}!{X.ref(r, c)}")
            report["flags"].append(f"{s.name}!{X.ref(r, c)}: formula would error because its inputs are not in the filings; left empty")
    report["cleared"] = cleared
    # ---------------- ties: formula rows whose canonical key has a filed value
    for sp in prof["sheets"]:
        s = wb[sp["name"]]
        scale = sp["units"]["scale"]
        for it in sp["items"]:
            if not it["formula"] or it["section"]:
                continue
            m = map_label(it["label"], it["statement_hint"])
            if not m:
                continue
            for p in sp["periods"]:
                i = year_idx.get(p["year"])
                cell = s.cells.get((it["row"], p["col"]))
                if i is None or p["projection"] or cell is None or not isinstance(cell.value, str) or not cell.value.startswith("="):
                    continue
                v, _src = _value(statements, m["key"], i)
                if v is None or not isinstance(cell.cached, (int, float)):
                    continue
                money = m["key"] not in ("diluted_shares", "eps_diluted")
                want = v * (scale if money else 1.0)
                got = cell.cached
                ok = abs(abs(got) - abs(want)) <= max(1e-6, 1e-6 * abs(want))
                report["ties"].append({"sheet": sp["name"], "cell": X.ref(it["row"], p["col"]), "key": m["key"], "computed": got, "filed": want, "ties": ok})
    _checks_sheet(wb, report, year_idx, statements, prof)
    data = wb.to_bytes()
    diff = structure_diff(ref_xlsx, data)
    report["structure"] = {"score": diff["score"], "sheets_matched": diff["facts"]["sheets"]["matched"], "rows_matched": diff["facts"]["labels"]["matched"],
                           "periods_matched": diff["facts"]["periods"]["matched"], "of": {k: v["total"] for k, v in diff["facts"].items()}}
    report["score"] = diff["score"]
    report["unmapped_count"] = len(report["unmapped"])
    return data, report


def _checks_sheet(wb, report: dict, year_idx: dict, st: stm.Statements, prof: dict) -> None:
    """Appended `Checks` sheet (the reference structure is untouched): every carried subtotal that has a filed counterpart is
    compared to the filed value (blue, sourced) within a named tolerance; a master check sums them up."""
    cs = wb.sheet("Checks" if "Checks" not in [s.name for s in wb.sheets] else "Checks_fit", tab="C00000")
    cs.set("A1", "Template fit checks", kind="title")
    cs.set("A2", "Each subtotal the template computes is compared with the figure as filed (absolute values, so sign conventions do not matter).", kind="note")
    cs.set("A3", "Tolerance (absolute)", bold=True)
    cs.set("B3", 0.001, kind="input", fmt="num2")
    wb.define("Tol", cs.name, "B3")
    cs.set("A4", "Master check", bold=True)
    cs.set("A5", "Check", kind="header")
    cs.set("B5", "As filed", kind="header", align="right")
    cs.set("C5", "Result", kind="header", align="right")
    r = 6
    for t in report["ties"]:
        sheet, cell = t["sheet"], t["cell"]
        cs.set((r, 1), f"{sheet}!{cell}: {t['key']} computed vs filed")
        cs.set((r, 2), t["filed"], kind="hist", fmt="num2", comment=f"As filed: {t['key']} (statements, scaled to the template's units)")
        cs.set((r, 3), f'=IF(ABS(ABS({X.quote_sheet(sheet)}!{cell})-ABS(B{r}))<=Tol,"OK","ERROR")', align="right")
        r += 1
    cs.set((4, 3), f'=IF(COUNTIF(C6:C{max(r - 1, 6)},"ERROR")=0,"OK","ERROR")' if r > 6 else '=IF(COUNTIF(C5:C5,"ERROR")=0,"OK","ERROR")',
           bold=True, align="right")
    cs.width("A", 52)
    cs.width("B", 14)
    cs.width("C", 12)
    cs.ok_error(f"C4:C{max(r - 1, 6)}")
    cs.freeze = (5, 1)
    fx.calculate_workbook(wb)
    bad = [t for t in report["ties"] if not t["ties"]]
    if bad:
        report["flags"].append(f"{len(bad)} subtotal(s) do not tie to the filed figure (the template's rows do not sum to the filed total)")


def _carry(formula: str, sheet: str, sheets: set) -> tuple[str | None, str]:
    """A reference formula carried to the output. The layout is reproduced cell for cell, so the address translation is the
    identity; this checks that every reference lands on something that exists in the output."""
    if re.search(r"\[\d+\]", formula) or "#REF!" in formula:
        return None, "external workbook link or broken reference"
    f = re.sub(r'"[^"]*"', '""', formula)
    for m in re.finditer(r"(?:'([^']+)'|([A-Za-z_][\w.]*))!", f):
        if (m.group(1) or m.group(2)) not in sheets:
            return None, f"sheet {m.group(1) or m.group(2)!r} is not in the reference workbook"
    return formula, "ok"


# =========================================================================== structure_diff
def _facts(P: _Parsed, prof: dict) -> dict:
    out = {"sheets": prof["order"], "labels": {}, "periods": {}, "formats": {}, "freeze": {}, "widths": {}}
    for sp in prof["sheets"]:
        n = sp["name"]
        grid = P.book.sheets[n]
        lc = sp["label_col"]
        out["labels"][n] = [(r, str(grid[(r, lc)].value).strip()) for r in sorted({r for (r, c) in grid if c == lc})
                            if grid[(r, lc)].value not in (None, "") and not grid[(r, lc)].formula]
        out["periods"][n] = [(sp["header_row"], p["col"], str(grid[(sp["header_row"], p["col"])].value).strip()) for p in sp["periods"]]
        out["formats"][n] = {(it["row"], p["col"]): _xf(P, n, (it["row"], p["col"]))["fmt"] for it in sp["items"]
                             if not it["section"] for p in sp["periods"]}
        out["freeze"][n] = sp["freeze"]
        out["widths"][n] = {c: round(w, 1) for c, w in sp["widths"].items()}
    return out


def structure_diff(ref_xlsx: bytes, out_xlsx: bytes) -> dict:
    """Independent structural comparison of a generated workbook against its reference.

    facts: sheet names and order, labels and order (row by row), period headers, number formats of the period cells on line-item
    rows, freeze panes, column widths. Each fact scores matched/total; score is their mean (1.0 = identical structure)."""
    A, B = _parse(ref_xlsx), _parse(out_xlsx)
    fa, fb = _facts(A, profile(ref_xlsx)), _facts(B, profile(out_xlsx))
    facts: dict[str, dict] = {}
    n = max(len(fa["sheets"]), len(fb["sheets"]), 1)
    facts["sheets"] = {"matched": sum(1 for x, y in zip(fa["sheets"], fb["sheets"]) if x == y), "total": len(fa["sheets"]) if fa["sheets"] else n,
                       "extra_in_output": [s for s in fb["sheets"] if s not in fa["sheets"]]}

    def tally(key):
        m = t = 0
        for s in fa["sheets"]:
            a, b = fa[key].get(s), fb[key].get(s)
            if isinstance(a, dict):
                b = b or {}
                for k, v in a.items():
                    t += 1
                    m += 1 if b.get(k) == v else 0
            elif isinstance(a, list):
                b = b or []
                bs = set(b)
                for x in a:
                    t += 1
                    m += 1 if x in bs else 0
            else:
                t += 1
                m += 1 if a == b else 0
        return {"matched": m, "total": t}
    for k in ("labels", "periods", "formats", "freeze", "widths"):
        facts[k] = tally(k)
    scores = [f["matched"] / f["total"] for f in facts.values() if f["total"]]
    # an output with extra sheets before/among the reference sheets is not identical in order
    order_ok = fb["sheets"][:len(fa["sheets"])] == fa["sheets"]
    score = (sum(scores) / len(scores) if scores else 0.0) * (1.0 if order_ok else 0.9)
    return {"score": round(score, 6), "facts": facts, "order_ok": order_ok}
