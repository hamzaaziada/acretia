"""M&A deal multiples from SEC merger filings (proxies, S-4s, tender-offer 14D-9s).

Pipeline
  1. discover():  EDGAR full-text search for filings whose text mentions a precedent-transactions analysis.
  2. extract():   find each "Selected (Precedent) Transactions Analysis" section, the banker who ran it,
                  the table(s) that follow, and the reference range the banker picked.
  3. rows -> observations: one row per (filing, analysis, deal, multiple). Deals listed without a
     per-deal multiple are still kept (identity only), so they can be matched to other filings.
  4. consolidate(): group observations of the same deal across filings; median per multiple type.

Everything is a fact from an SEC filing; every observation carries the accession number, URL,
advisor and the raw cell text it was read from.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .htmltables import Doc, Table, clean_row, parse

EFTS = "https://efts.sec.gov/LATEST/search-index?q={q}&forms={forms}&dateRange=custom&startdt={s}&enddt={e}&from={frm}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{fn}"
FORMS = ["DEFM14A", "PREM14A", "DEFM14C", "PREM14C", "S-4", "S-4/A", "F-4", "SC 14D9", "SC TO-T", "425"]
QUERIES = ['"selected precedent transactions"', '"selected transactions analysis"',
           '"precedent transactions analysis"', '"selected comparable transactions"']

SECTION_RE = re.compile(
    r"(?i)(selected\s+(?:precedent|comparable|m\s*&\s*a)?\s*transactions?\s+analysis"
    r"|precedent\s+transactions?\s+analysis|selected\s+(?:precedent|comparable)\s+(?:m&a\s+)?transactions)")
STOP_RE = re.compile(
    r"(?im)^[ \t]*(discounted\s+cash\s+flow|selected\s+(?:public\s+)?(?:trading\s+)?compan(?:y|ies)\s+analysis"
    r"|premiums?\s+paid\s+analysis|other\s+(?:information|factors)|miscellaneous|sum[- ]of[- ]the[- ]parts"
    r"|leveraged\s+buyout\s+analysis|analyst\s+price\s+targets|52-week)")
ADVISOR_RE = re.compile(r"(?:^|[.;]\s+|\n)\s*([A-Z][\w&.,'\- ]{1,60}?)\s+(?:reviewed|analyzed|performed|compared|identified|selected|calculated)\b")
RANGE_RE = re.compile(r"(?i)(?:selected|applied|derived)[^.]{0,120}?range of ([^.]{0,90}?)of\s+(\d+(?:\.\d+)?)x\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)x")

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SUMMARY = re.compile(r"(?i)^(median|mean|average|high|low|maximum|minimum|25th|75th|overall)")
TARGET_H = re.compile(r"(?i)\btarget|\bacquired|\bcompany\b|\bseller")
ACQ_H = re.compile(r"(?i)acquir|buyer|purchaser|bidder|sponsor")
DATE_H = re.compile(r"(?i)date|announced|announcement|month|year|closed")
MULT_H = re.compile(r"(?i)\b(ev|tev|ttv|transaction|enterprise|aggregate|implied|equity|price)\b|/|multiple|revenue|sales|ebitda|ebit\b|earnings|p/e|x\b")


@dataclass
class Observation:
    announced: str | None
    target: str
    acquirer: str | None
    kind: str | None            # multiple | amount (amounts are $ millions as printed)
    metric: str | None          # revenue | ebitda | ebit | gross_profit | earnings | book | tangible_book | core_deposit_premium | deal_value
    period: str | None          # ltm | ntm | cy<yyyy> | fy1 | unspecified
    numerator: str | None       # ev | equity
    value: float | None
    nm: bool
    raw_header: str
    raw_cell: str
    advisor: str | None
    filing_company: str
    filing_cik: int
    form: str
    filed: str
    accession: str
    url: str
    table_index: int
    confidence: float


@dataclass
class Analysis:
    accession: str
    url: str
    filing_company: str
    form: str
    filed: str
    advisor: str | None
    n_deals: int
    n_multiples: int
    summary: dict = field(default_factory=dict)
    reference_range: dict | None = None
    table_index: int | None = None


# --------------------------------------------------------------------------- discovery
def discover(sec, start: date, end: date, forms=FORMS, queries=QUERIES, max_hits: int | None = None) -> list[dict]:
    """EDGAR full-text search, sliced by month (the API caps a query at 10,000 hits, 100 per page)."""
    seen, out = set(), []
    cur = start
    while cur <= end:
        nxt = min(end, (cur.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
        for q in queries:
            frm = 0
            while True:
                url = EFTS.format(q=_qs(q), forms=",".join(f.replace(" ", "%20") for f in forms),
                                  s=cur.isoformat(), e=nxt.isoformat(), frm=frm)
                j = sec.get_json(url, f"efts/{_slug(q)}_{cur:%Y%m}_{frm}", max_age=6 * 3600)
                hits = j.get("hits", {}).get("hits", [])
                for h in hits:
                    s = h["_source"]
                    adsh, fn = h["_id"].split(":", 1)
                    if (adsh, fn) in seen:
                        continue
                    seen.add((adsh, fn))
                    cik = int((s.get("ciks") or ["0"])[0])
                    out.append({"accession": adsh, "file": fn, "cik": cik, "form": s.get("form"),
                                "file_type": s.get("file_type"), "filed": s.get("file_date"),
                                "company": re.sub(r"\s*\(.*$", "", (s.get("display_names") or [""])[0]).strip(),
                                "url": ARCHIVE.format(cik=cik, adsh=adsh.replace("-", ""), fn=fn)})
                    if max_hits and len(out) >= max_hits:
                        return out
                total = j.get("hits", {}).get("total", {}).get("value", 0)
                frm += 100
                if frm >= min(total, 10000) or not hits:
                    break
        cur = nxt + timedelta(days=1)
    return out


def _qs(q: str) -> str:
    from urllib.parse import quote
    return quote(q)


def _slug(q: str) -> str:
    return re.sub(r"\W+", "_", q).strip("_")[:40]


# --------------------------------------------------------------------------- extraction
def extract(html_text: str, meta: dict) -> tuple[list[Observation], list[Analysis]]:
    doc = parse(html_text)
    obs: list[Observation] = []
    analyses: list[Analysis] = []
    used_tables: set[int] = set()
    for m in SECTION_RE.finditer(doc.text):
        start = m.start()
        # only treat it as a section heading if it starts a line (avoid in-sentence mentions)
        line_start = doc.text.rfind("\n", 0, start) + 1
        if doc.text[line_start:start].strip():
            continue
        after = doc.text[m.end():m.end() + 6].lstrip(" \t")
        if after[:1] not in ("\n", ".", ":", "—", "–", "-"):
            continue  # a sentence that merely starts with these words, not a heading
        stop = STOP_RE.search(doc.text, m.end() + 200)
        end = min(stop.start() if stop else len(doc.text), m.end() + 40000)
        section = doc.text[m.end():end]
        advisor = _advisor(section)
        rr = _reference_range(section)
        for t in doc.tables:
            if t.index in used_tables or not (m.end() <= t.offset <= end):
                continue
            parsed = _parse_table(t)
            if not parsed:
                continue
            used_tables.add(t.index)
            rows, summary, n_mult = parsed
            for r in rows:
                obs.extend(_to_obs(r, advisor, meta, t.index))
            analyses.append(Analysis(meta["accession"], meta["url"], meta["company"], meta["form"], meta["filed"],
                                     advisor, len(rows), n_mult, summary, rr, t.index))
    return obs, analyses


def _advisor(section: str) -> str | None:
    head = section[:1500]
    m = ADVISOR_RE.search(head)
    if not m:
        return None
    name = m.group(1).strip(" ,.")
    if len(name.split()) > 6 or name.lower().startswith(("the ", "in ", "for ", "using ", "based ", "although")):
        return None
    return name


def _reference_range(section: str) -> dict | None:
    m = RANGE_RE.search(section)
    if not m:
        return None
    label = re.sub(r"\s+", " ", m.group(1)).strip()
    metric, period, num = classify_header(label)
    return {"label": label, "low": float(m.group(2)), "high": float(m.group(3)),
            "metric": metric, "period": period, "numerator": num}


def _parse_table(t: Table):
    rows = [clean_row(r) for r in t.rows]
    rows = [r for r in rows if r]
    if len(rows) < 3:
        return None
    # header: first row (within the first 4) that has a target-ish column
    hidx = None
    for i, r in enumerate(rows[:4]):
        joined = " | ".join(r)
        if TARGET_H.search(joined) and (ACQ_H.search(joined) or DATE_H.search(joined)):
            hidx = i
            break
    if hidx is None:
        return None
    header = rows[hidx]
    # two-row headers: a following row of short period labels (LTM / NTM / 2026E) refines multiple columns
    sub = rows[hidx + 1] if hidx + 1 < len(rows) else []
    if sub and all(len(c) <= 12 for c in sub) and not any(_is_number(c) for c in sub) \
            and any(re.search(r"(?i)ltm|ntm|cy|fy|20\d\d|forward|trailing", c) for c in sub):
        hidx += 1
        header = _merge_header(header, sub)
    roles = []
    for h in header:
        if TARGET_H.search(h) and not MULT_H.search(h.replace("Company", "")) or re.fullmatch(r"(?i)target(\s+company)?", h):
            roles.append("target")
        elif ACQ_H.search(h):
            roles.append("acquirer")
        elif DATE_H.search(h) and not re.search(r"(?i)ebitda|revenue|sales", h):
            roles.append("date")
        elif MULT_H.search(h):
            roles.append("multiple")
        else:
            roles.append("other")
    if "target" not in roles:
        # "Acquiror / Target" in one column
        for i, h in enumerate(header):
            if re.search(r"(?i)target", h):
                roles[i] = "target"
        if "target" not in roles:
            return None
    out_rows, summary, n_mult = [], {}, 0
    for r in rows[hidx + 1:]:
        if SUMMARY.match(r[0]):
            vals = [_mult(c) for c in r[1:]]
            vals = [v for v in vals if v[0] is not None]
            mh = [h for h, ro in zip(header, roles) if ro == "multiple"]
            for h, v in zip(mh[-len(vals):] if vals else [], vals):
                summary.setdefault(r[0].lower(), {})[h] = v[0]
            continue
        rec = _align(r, header, roles)
        if not rec or not rec.get("target"):
            continue
        n_mult += sum(1 for _, (v, _nm, _raw) in rec["multiples"] if v is not None)
        out_rows.append(rec)
    if not out_rows:
        return None
    return out_rows, summary, n_mult


def _merge_header(top: list[str], sub: list[str]) -> list[str]:
    # spread the sub-labels over the trailing multiple columns of the top header
    mult_idx = [i for i, h in enumerate(top) if MULT_H.search(h)]
    if not mult_idx:
        return top + sub
    base = top[:mult_idx[0]]
    groups = top[mult_idx[0]:]
    per = max(1, len(sub) // max(1, len(groups)))
    merged = []
    for gi, g in enumerate(groups):
        for s in sub[gi * per:(gi + 1) * per]:
            merged.append(f"{g} {s}")
    return base + (merged or groups)


def _align(r: list[str], header: list[str], roles: list[str]) -> dict | None:
    rec = {"multiples": []}
    if len(r) == len(header):
        pairs = list(zip(header, roles, r))
    else:
        # identity columns from the left, multiple columns from the right
        id_cols = [(h, ro) for h, ro in zip(header, roles) if ro != "multiple"]
        m_cols = [(h, ro) for h, ro in zip(header, roles) if ro == "multiple"]
        n_id = len(id_cols)
        if len(r) < n_id:
            return None
        pairs = [(h, ro, v) for (h, ro), v in zip(id_cols, r[:n_id])]
        rest = r[n_id:]
        pairs += [(h, ro, v) for (h, ro), v in zip(m_cols[-len(rest):] if rest else [], rest)]
    for h, ro, v in pairs:
        if ro == "multiple":
            rec["multiples"].append((h, _mult(v)))
        elif ro in ("target", "acquirer", "date"):
            rec[ro] = v
    if rec.get("target") and "/" in rec["target"] and "acquirer" not in rec:
        a, _, b = rec["target"].partition("/")
        rec["acquirer"], rec["target"] = a.strip(), b.strip()
    return rec


def _is_number(s: str) -> bool:
    return bool(re.fullmatch(r"[\$€£(]*-?[\d,]+(\.\d+)?[x%)]*", s.strip()))


def _mult(cell: str):
    raw = cell
    c = cell.strip().replace(",", "").lstrip("$€£ ")
    if re.fullmatch(r"(?i)n\.?m\.?|nm|n/?a|—|–|-|\*|n\.?a\.?|not\s+(meaningful|available)", c):
        return (None, True, raw)
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\s*[x×%]?\)?[*†(\w)]*", c)
    if not m:
        return (None, False, raw)
    v = float(m.group(1))
    if c.startswith("(") and c.endswith(")"):
        v = -v
    return (v, False, raw)


RATIO_H = re.compile(r"(?i)/|\bto\b|multiple|\bx\b|premium|p/e|\bpe\b")


def column_kind(header: str, cell: str) -> str:
    """multiple (a ratio) or amount (a $ figure such as deal value or target revenue)."""
    c = cell.strip()
    if re.search(r"\d\s*[x×]\)?\s*$", c):
        return "multiple"
    if c.startswith(("$", "€", "£")) or not RATIO_H.search(header):
        return "amount"
    return "multiple"


def classify_header(h: str, kind: str = "multiple"):
    s = h.lower()
    metric = ("core_deposit_premium" if "core deposit" in s
              else "tangible_book" if re.search(r"tangible book|\btbv\b|tbvps", s)
              else "ebitda" if "ebitda" in s else "ebit" if re.search(r"\bebit\b", s)
              else "gross_profit" if "gross profit" in s
              else "revenue" if re.search(r"revenue|sales", s)
              else "earnings" if re.search(r"earnings|p/e|\bpe\b|net income|\beps\b", s)
              else "book" if "book" in s else None)
    if kind == "amount":
        if metric is None and re.search(r"price|value|consideration|size", s):
            metric = "deal_value"
        elif metric:
            metric = f"target_{metric}"
    period = ("ltm" if re.search(r"\bltm\b|last twelve|trailing|\bttm\b", s)
              else "ntm" if re.search(r"\bntm\b|next twelve|forward|\bfwd\b", s)
              else f"cy{m.group(1)}" if (m := re.search(r"\b(?:cy)?(20\d\d)[ef]?\b", s))
              else "fy1" if re.search(r"fy\s*\+?\s*1|fy1", s)
              else "unspecified" if metric else None)
    if kind == "amount":
        return metric, period, None
    numerator = ("equity" if re.search(r"equity value|offer value|price|deal value|p/e|\bpe\b", s)
                 or metric in ("tangible_book", "book", "earnings")
                 else "ev" if re.search(r"\b(ev|tev|enterprise|transaction value|aggregate value|implied value|firm value)\b", s)
                 else "ev" if metric in ("revenue", "ebitda", "ebit", "gross_profit") else None)
    return metric, period, numerator


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(?i)([a-z]{3})[a-z]*\.?\s+\d{1,2},?\s+(\d{4})", s)          # December 31, 2021
    if m and m.group(1).lower() in MONTHS:
        return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.match(r"(\d{1,2})/\d{1,2}/(\d{2,4})$", s)                           # 12/31/2021
    if m:
        y = int(m.group(2))
        return f"{y + 2000 if y < 100 else y:04d}-{int(m.group(1)):02d}"
    m = re.match(r"(?i)([a-z]{3})[a-z]*\.?[\s\-/]*'?(\d{4}|\d{2})\b", s)       # November 2025, Mar-21
    if m and m.group(1).lower() in MONTHS:
        y = int(m.group(2))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.match(r"(\d{1,2})/(\d{1,2}/)?(\d{2,4})", s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return f"{y:04d}-{int(m.group(1)):02d}"
    m = re.search(r"(19|20)\d\d", s)
    return m.group(0) if m else None


def _to_obs(rec: dict, advisor, meta, tidx) -> list[Observation]:
    base = dict(announced=parse_date(rec.get("date")), target=_clean_name(rec["target"]),
                acquirer=_clean_name(rec.get("acquirer")), advisor=advisor,
                filing_company=meta["company"], filing_cik=meta["cik"], form=meta["form"],
                filed=meta["filed"], accession=meta["accession"], url=meta["url"], table_index=tidx)
    out = []
    for h, (v, nm, raw) in rec["multiples"]:
        kind = column_kind(h, raw)
        metric, period, num = classify_header(h, kind)
        conf = 0.9 if (metric and period not in (None, "unspecified")) else 0.7 if metric else 0.3
        if kind == "multiple" and v is not None and not (0 < v <= 250):
            nm, v = True, None  # same non-meaningful rule as public comps
        out.append(Observation(kind=kind, metric=metric, period=period, numerator=num, value=v, nm=nm,
                               raw_header=h, raw_cell=raw, confidence=conf, **base))
    if not out:  # deal listed without a per-deal multiple
        out.append(Observation(kind=None, metric=None, period=None, numerator=None, value=None, nm=False,
                               raw_header="", raw_cell="", confidence=0.5, **base))
    return out


def _clean_name(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s*\(\d+\)\s*$|[*†‡]+$", "", s).strip(" ,")
    return s or None


# --------------------------------------------------------------------------- consolidation
_SUFFIX = re.compile(r"(?i)[,.]?\s+(inc|corp|corporation|co|company|ltd|limited|plc|llc|lp|l\.p|n\.v|s\.a|ag|se|holdings?|group)\.?$")


def name_key(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower().replace("&", "and")
    for _ in range(3):
        s = _SUFFIX.sub("", s).strip()
    return re.sub(r"[^a-z0-9]+", "", s)


def consolidate(obs: list[Observation]) -> list[dict]:
    """One row per deal (target + acquirer + announce month within 2 months)."""
    groups: dict[tuple, list[Observation]] = {}
    index: dict[tuple, list[tuple]] = {}
    for o in obs:
        k = (name_key(o.target), name_key(o.acquirer))
        ym = o.announced or ""
        match = None
        for existing in index.get(k, []):
            if _months_apart(existing[2], ym) <= 2:
                match = existing
                break
        if match is None:
            match = (k[0], k[1], ym)
            index.setdefault(k, []).append(match)
        groups.setdefault(match, []).append(o)
    deals = []
    for (tk, ak, ym), os_ in groups.items():
        row = {"target": _mode([o.target for o in os_]), "acquirer": _mode([o.acquirer for o in os_ if o.acquirer]),
               "announced": _mode([o.announced for o in os_ if o.announced]),
               "n_filings": len({o.accession for o in os_}),
               "advisors": "; ".join(sorted({o.advisor for o in os_ if o.advisor})),
               "sources": " ".join(sorted({o.url for o in os_}))}
        by_type: dict[str, list[float]] = {}
        for o in os_:
            if o.value is None or not o.metric:
                continue
            if o.kind == "multiple" and 0 < o.value <= 250:
                by_type.setdefault(f"{o.numerator or 'ev'}_{o.metric}_{o.period or 'unspecified'}", []).append(o.value)
            elif o.kind == "amount" and o.value > 0:
                by_type.setdefault(f"{o.metric}_musd_as_printed", []).append(o.value)
        for k, vals in sorted(by_type.items()):
            row[k] = statistics.median(vals)
            row[f"{k}_n"] = len(vals)
            if len(vals) > 1 and max(vals) > 0 and (max(vals) - min(vals)) / max(vals) > 0.10:
                row[f"{k}_disagreement"] = True
        deals.append(row)
    deals.sort(key=lambda r: r.get("announced") or "", reverse=True)
    return deals


def _months_apart(a: str, b: str) -> int:
    if not a or not b or len(a) < 7 or len(b) < 7:
        return 0 if a[:4] == b[:4] else 99
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return abs((ya - yb) * 12 + ma - mb)


def _mode(xs):
    xs = [x for x in xs if x]
    return max(set(xs), key=xs.count) if xs else None


def as_dict(o) -> dict:
    return asdict(o)
