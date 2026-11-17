"""VDR gap and risk detector (S5.3). Deterministic, no LLM.

scan_room / scan_documents -> {"findings", "summary", "coverage"}. Detectors: missing financial periods, missing standard
document categories, conflicting figures (via om.consistency) and sentence-level clause risks (change of control, covenants,
MFN, exclusivity). Every clause quote is an exact substring of its page text; PDF findings carry a located bbox + span hash,
or bbox None and locate_failed=True (a box is never invented)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from om import consistency as cs

TYPES = ("missing_period", "missing_document", "conflicting_figure", "change_of_control", "covenant", "mfn", "exclusivity")
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


# --------------------------------------------------------------------------- checklist
def _cat(cid, label, severity, name, first_page=None):
    return {"id": cid, "label": label, "severity": severity, "name": name, "first_page": first_page or name}


DEFAULT_CHECKLIST = [
    _cat("audited_financials", "Audited financial statements", "high",
         r"audited|annual (?:report|accounts|financial)|financial statements|\b10-?k\b|statutory accounts",
         r"independent auditor|report of independent|audited consolidated|audited financial|consolidated financial statements"),
    _cat("management_accounts", "Management accounts", "medium",
         r"management accounts|management financials?|monthly (?:accounts|financials|reporting|pack)|quarterly (?:accounts|financials|reporting)|\bmgmt\b",
         r"management accounts|unaudited management"),
    _cat("budget_forecast", "Budget / forecast", "medium", r"budget|forecast|business plan|projections|financial model",
         r"budget for|forecast for|business plan"),
    _cat("cap_table", "Capitalisation table", "high",
         r"cap(?:italization|italisation)?[ _-]*table|share register|shareholder|stock ledger|ownership (?:table|schedule)|equity ledger",
         r"capitalization table|capitalisation table|cap table|fully diluted"),
    _cat("debt_agreements", "Debt / credit agreements", "high",
         r"credit agreement|loan agreement|facility agreement|indenture|note purchase|term loan|revolv|promissory|debt|borrowing",
         r"credit agreement|loan agreement|facility agreement|indenture|note purchase agreement"),
    _cat("customer_contracts", "Material customer contracts", "medium",
         r"customer (?:contract|agreement)|master services|\bmsa\b|sales agreement|distribution agreement|reseller|customer",
         r"customer agreement|master services agreement|sales agreement"),
    _cat("supplier_contracts", "Material supplier contracts", "medium",
         r"supplier|supply agreement|vendor|procurement|purchase agreement", r"supplier agreement|supply agreement|vendor agreement"),
    _cat("leases", "Leases", "medium", r"\blease|rental agreement|premises", r"lease agreement|landlord|tenant"),
    _cat("employment", "Employment / key-person agreements", "medium",
         r"employment|key[- ]person|executive|officer|offer letter|consulting agreement", r"employment agreement|key person"),
    _cat("ip_schedule", "IP schedule", "medium", r"intellectual property|\bip\b schedule|patent|trademark|\bip\b register",
         r"intellectual property|patent|trademark"),
    _cat("litigation", "Litigation", "medium", r"litigation|legal proceedings|lawsuit|disputes?|claims? (?:schedule|register)",
         r"litigation|legal proceedings|lawsuit"),
    _cat("tax_returns", "Tax returns", "medium", r"tax return|tax filing|\btax\b", r"tax return"),
    _cat("insurance", "Insurance", "medium", r"insurance|certificate of insurance|insurance polic", r"insurance polic|certificate of insurance"),
    _cat("corporate_docs", "Corporate / organisational documents", "medium",
         r"articles of|certificate of incorporation|by-?laws|memorandum|org(?:anisation|anization)? chart|corporate (?:structure|docs|records)|minutes|good standing",
         r"certificate of incorporation|articles of association|bylaws"),
]


def _classify(doc, checklist) -> set[str]:
    name = doc.get("name", "")
    first = _first_text(doc)[:700]
    out = set()
    for c in checklist:
        if re.search(c["name"], name, re.I) or re.search(c["first_page"], first, re.I):
            out.add(c["id"])
    return out


def _first_text(doc) -> str:
    for p in doc.get("pages") or []:
        if p:
            return p
    return ""


# --------------------------------------------------------------------------- entities
_ENT_SUFFIX = re.compile(r"\b(?:inc|incorporated|corp|corporation|co|company|companies|ltd|limited|plc|llc|lp|holdings?|group|gmbh|ag|sa|nv|bv)\b\.?", re.I)
_ENT_SKIP_LINE = re.compile(r"registrant|commission|pursuant|file number|exact name|section|independent auditor|auditor|report of|signed|page \d", re.I)
_ENT_STOP = {"the", "and", "inc", "corp", "corporation", "company", "companies", "group", "holdings", "holding", "limited", "ltd", "international",
             "global", "united", "american", "national", "first", "financial", "statements", "audited", "annual", "report", "management",
             "accounts", "consolidated", "project", "confidential", "information", "memorandum", "agreement", "draft", "final", "page", "form",
             "table", "contents", "pdf"}
_DOC_WORDS = _ENT_STOP | {"fy", "10k", "10-k", "10q", "q1", "q2", "q3", "q4", "budget", "forecast", "excerpt", "cim", "scanned", "arabic"}


def _entity_info(doc):
    """-> (tokens, display). Tokens are distinctive words of the document's own company name, read from the title area."""
    head = _first_text(doc)[:1800]
    for ln in head.split("\n")[:30]:
        ln = ln.strip()
        if not ln or _ENT_SKIP_LINE.search(ln):
            continue
        m = _ENT_SUFFIX.search(ln)
        if not m:
            continue
        words = re.findall(r"[^\W\d_][\w'’&\-]*", ln[:m.start()])
        if not words or len(words) > 6:
            continue
        toks = {w.lower().strip("'’-&") for w in words}
        toks = {t for t in toks if len(t) >= 3 and t not in _ENT_STOP}
        if toks:
            return frozenset(toks), " ".join(w[:1].upper() + w[1:].lower() for w in re.sub(r"^the\s+", "", " ".join(words), flags=re.I).split())
    pm = re.search(r"\bProject\s+([A-Z][a-z]{3,})", head)
    if pm:
        return frozenset({pm.group(1).lower()}), pm.group(1)
    base = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", Path(str(doc.get("name", ""))).name)
    toks = {w.lower() for w in re.findall(r"\b[A-Z]{2,6}\b", base)} - _DOC_WORDS     # a ticker in the file name: "AAPL 10-K.pdf"
    return frozenset(toks), " ".join(sorted(toks)).upper()


def _entity_clusters(docs):
    """doc_id -> cluster key (display name). Documents sharing a distinctive company-name word are one entity.
    Unnamed documents join the sole named entity of the room, or each other when no entity is named; with several named entities
    they stay alone (a figure in an unnamed document is never compared with an arbitrary company)."""
    info = {d["doc_id"]: _entity_info(d) for d in docs}
    parent = {k: k for k in info}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    named = [k for k, (t, _) in info.items() if t]
    for i, a in enumerate(named):
        for b in named[i + 1:]:
            if info[a][0] & info[b][0]:
                parent[find(a)] = find(b)
    roots = sorted({find(k) for k in named}, key=str)
    out = {}
    for k in named:
        out[k] = f"ent:{find(k)}"
    disp = {f"ent:{r}": info[r][1] for r in roots}
    for k, (t, _) in info.items():
        if t:
            continue
        out[k] = f"ent:{roots[0]}" if len(roots) == 1 else ("ent:" if not roots else f"solo:{k}")
    return out, disp


# --------------------------------------------------------------------------- periods
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MON_RE = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?[\s_-]+((?:19|20)\d{2})\b", re.I)
_ISO_MON = re.compile(r"\b((?:19|20)\d{2})[-_/](0[1-9]|1[0-2])\b(?![-_/]\d)")
_YEAR_ENDED = re.compile(r"(?:fiscal\s+)?(?:year|period)\s+(?:ended|ending)\s+(?:on\s+)?(?:\d{1,2}\s+)?(?:[A-Za-z]{3,9}\.?\s*)(?:\d{1,2},?\s*)?((?:19|20)\d{2})\b", re.I)
MIN_YEAR = 1990


def _year_ok(y: int) -> bool:
    import datetime
    return MIN_YEAR <= y <= datetime.date.today().year + 5


def period_of(text: str):
    """-> (kind, key) with kind annual|quarter|month; key FY2023 -> 2023 | (2024, 3). Years outside 1990..now+5 are ignored."""
    m = _MON_RE.search(text)
    if m and _year_ok(int(m.group(2))):
        return "month", (int(m.group(2)), _MONTHS.index(m.group(1)[:3].lower()) + 1)
    m = _ISO_MON.search(text)
    if m and _year_ok(int(m.group(1))):
        return "month", (int(m.group(1)), int(m.group(2)))
    for _s, _e, p, proj in cs.find_periods(text):
        if proj:
            continue
        q = re.fullmatch(r"Q([1-4]) ((?:19|20)\d{2})", p)
        if q and _year_ok(int(q.group(2))):
            return "quarter", (int(q.group(2)), int(q.group(1)))
        if re.fullmatch(r"FY(?:19|20)\d{2}", p) and _year_ok(int(p[2:])):
            return "annual", int(p[2:])
    return None


def _annual_of(text: str):
    ym = _YEAR_ENDED.search(text)
    if ym and _year_ok(int(ym.group(1))):
        return int(ym.group(1))
    for _s, _e, p, proj in cs.find_periods(text):
        if not proj and re.fullmatch(r"FY(?:19|20)\d{2}", p) and _year_ok(int(p[2:])):
            return int(p[2:])
    return None


def _title_area(doc) -> str:
    return _first_text(doc)[:420]


def _doc_period(d, c):
    """Coverage of one financial document from its file name and title/header area only (never narrative body text)."""
    base = Path(str(d["name"])).name
    head = _title_area(d)
    if "management_accounts" in c:
        p = period_of(base) or period_of(head)
        if p:
            return p
    if "audited_financials" in c:
        y = _annual_of(base) or _annual_of(head)
        if y:
            return "annual", y
    return None


def _coverage(docs, cats):
    """-> ({series: {kind: {key: [doc]}}}, {series: audited years}). A series is one entity's documents: a gap needs a missing period
    inside one company's contiguous run, never across unrelated filers."""
    fin = [d for d in docs if cats[d["doc_id"]] & {"audited_financials", "management_accounts"}]
    clusters, _disp = _entity_clusters(fin)
    cov, audited = {}, {}
    for d in fin:
        p = _doc_period(d, cats[d["doc_id"]])
        if not p:
            continue
        kind, key = p
        ser = clusters[d["doc_id"]]
        cov.setdefault(ser, {"annual": {}, "quarter": {}, "month": {}})[kind].setdefault(key, []).append(d)
        if kind == "annual" and "audited_financials" in cats[d["doc_id"]]:
            audited.setdefault(ser, set()).add(key)
    return cov, audited


def _fmt_q(k):
    return f"Q{k[1]} {k[0]}"


def _fmt_m(k):
    return f"{k[0]}-{k[1]:02d}"


def _idx_q(k):
    return k[0] * 4 + k[1] - 1


def _idx_m(k):
    return k[0] * 12 + k[1] - 1


def _period_findings(docs, cats, expected):
    series, audited = _coverage(docs, cats)
    out = []

    def doc_ref(d):
        return {"doc_id": d["doc_id"], "doc_name": d["name"]}

    def add(kind, label, sev, neighbours, why):
        rel = [dict(doc_ref(d), period=lab) for d, lab in neighbours]
        out.append({"type": "missing_period", "severity": sev, "title": f"Missing {label}", "detail": why, "doc_id": None, "doc_name": None,
                    "page": None, "quote": "", "bbox_norm": None, "sha256_span_hash": None, "related": rel, "_key": (kind, label)})

    allm = {"annual": {}, "quarter": {}, "month": {}}
    for ser, cov in series.items():
        for kind in cov:
            for k, v in cov[kind].items():
                allm[kind].setdefault(k, []).extend(v)

    def covered_in(cov):
        months_have, quarters_have = set(cov["month"]), set(cov["quarter"])

        def q_covered(q):
            return q in quarters_have or all((q[0], (q[1] - 1) * 3 + i) in months_have for i in (1, 2, 3))

        def m_covered(m):
            return m in months_have or ((m[0], (m[1] - 1) // 3 + 1) in quarters_have)
        return q_covered, m_covered

    for ser in sorted(series, key=str):
        cov = series[ser]
        q_covered, m_covered = covered_in(cov)

        def nb(kind, keys, fmt, cov=cov):
            return [(cov[kind][k][0], fmt(k)) for k in keys if k in cov[kind]]
        ys = sorted(cov["annual"])
        for y in range(ys[0], ys[-1]) if ys else []:
            if y not in cov["annual"]:
                if all(q_covered((y, i)) for i in (1, 2, 3, 4)):
                    continue
                sev = "high" if audited.get(ser) else "medium"
                add("annual", f"FY{y}", sev, nb("annual", [y - 1, y + 1], lambda k: f"FY{k}"),
                    f"Financial statements cover FY{ys[0]} to FY{ys[-1]} but nothing was found for FY{y}.")
        qs = sorted(cov["quarter"], key=_idx_q)
        if qs:
            for i in range(_idx_q(qs[0]), _idx_q(qs[-1])):
                q = (i // 4, i % 4 + 1)
                if not q_covered(q):
                    add("quarter", _fmt_q(q), "medium", nb("quarter", [(q[0] if q[1] > 1 else q[0] - 1, q[1] - 1 or 4)], _fmt_q)
                        + nb("quarter", [(q[0] if q[1] < 4 else q[0] + 1, q[1] % 4 + 1)], _fmt_q),
                        f"Management accounts cover {_fmt_q(qs[0])} to {_fmt_q(qs[-1])} but nothing was found for {_fmt_q(q)}.")
        ms = sorted(cov["month"], key=_idx_m)
        if ms:
            for i in range(_idx_m(ms[0]), _idx_m(ms[-1])):
                m = (i // 12, i % 12 + 1)
                if not m_covered(m):
                    add("month", _fmt_m(m), "medium", [], f"Monthly accounts cover {_fmt_m(ms[0])} to {_fmt_m(ms[-1])} but nothing was found for {_fmt_m(m)}.")
    have = {f["_key"] for f in out}
    q_all, m_all = covered_in(allm)
    for e in expected or []:
        p = period_of(str(e))
        if not p:
            continue
        kind, key = p
        if kind == "annual":
            ok = key in allm["annual"] or all(q_all((key, i)) for i in (1, 2, 3, 4))
            lab, sev = f"FY{key}", "high"
        elif kind == "quarter":
            ok, lab, sev = q_all(key), _fmt_q(key), "medium"
        else:
            ok, lab, sev = m_all(key), _fmt_m(key), "medium"
        if not ok and (kind, lab) not in have:
            have.add((kind, lab))
            add(kind, lab, sev, [], f"{lab} was expected in the data room but no matching financial statements or management accounts were found.")
    for f in out:
        f.pop("_key")
    cover = {"annual": [f"FY{k}" for k in sorted(allm["annual"])], "quarterly": [_fmt_q(k) for k in sorted(allm["quarter"], key=_idx_q)],
             "monthly": [_fmt_m(k) for k in sorted(allm["month"], key=_idx_m)]}
    return out, cover


# --------------------------------------------------------------------------- clause detectors
_SPLIT = re.compile(r"(?<=[.!?;؟؛])\s+(?=[A-Z(\"“؀-ۿ])")
_NEG = re.compile(r"\b(?:no|not|nothing|neither|nor|without|never|absence of|free of|n't)\b", re.I)
_DEF = re.compile(r"^[\"“'(]*(?:change\s+(?:of|in)\s+control|[A-Z][\w ]{2,50}ratio|[A-Z][\w ]{2,50}coverage)[\"”']*\s*(?:\w+\s+)?(?:means|shall mean|has the meaning|is defined|refers to)\b", re.I)
_TERMINAL = re.compile(r"[.!?;:؟؛][\"”')\]]*$")
_NUMBERED = re.compile(r"^\s*(?:\(?\d+(?:\.\d+)*[.)]?|\(?[a-z]\)|[•\-–*])\s")
_ROWISH_END = re.compile(r"[\d%)]\s*$")


def _break_between(l1: str, l2: str) -> bool:
    """True when a line break ends a sentence. PDF lines wrap mid-sentence, so a break only counts at terminal punctuation, a numbered
    clause, a short heading or a table row."""
    a, b = l1.strip(), l2.strip()
    if not a or not b:
        return True
    if _TERMINAL.search(a) or _NUMBERED.match(b):
        return True
    starts_cap = b[:1].isupper() or b[:1].isdigit()
    if starts_cap and (len(a.split()) <= 5 or _ROWISH_END.search(a)):
        return True
    return False


def sentences(text: str):
    """Yield (start, end, sentence) with offsets into ``text``; sentences may span wrapped lines (the quote keeps the line breaks)."""
    segs, cur_s, prev, off = [], 0, None, 0
    for line in text.split("\n"):
        if prev is not None and _break_between(prev[1], line):
            segs.append((cur_s, prev[2]))
            cur_s = off
        prev = (off, line, off + len(line))
        off += len(line) + 1
    if prev is not None:
        segs.append((cur_s, prev[2]))
    for a, z in segs:
        pos = a
        chunk = text[a:z]
        spans = []
        for m in _SPLIT.finditer(chunk):
            spans.append((pos, a + m.start()))
            pos = a + m.end()
        spans.append((pos, z))
        for s, e in spans:
            seg = text[s:e]
            lead = len(seg) - len(seg.lstrip())
            t = seg.strip()
            if t:
                yield s + lead, s + lead + len(t), t


def _negated(sent: str, start: int, modal_ok: bool = False) -> bool:
    pre = sent[max(0, start - 80):start]
    if modal_ok:       # "shall not permit the ratio to exceed" is operative, not a negation
        pre = re.sub(r"\b(?:shall|will|may|must|agrees?|covenants?|undertakes?)\s+not\b", " ", pre, flags=re.I)
    pre = re.split(r"[,;:]", pre)[-1]
    return bool(_NEG.search(pre))


_COC = re.compile(r"change\s+(?:of|in)\s+control|change\s+of\s+ownership", re.I)
_COC_OP = re.compile(r"terminat|accelerat|consent|event of default|prepay|mandatory|put right|void|right to|may require|shall require|"
                     r"permitted to|entitle|waive|notify|notice|triggers?|constitutes?|shall be deemed", re.I)
_ASSIGN = re.compile(r"(?:assign\w*|transfer\w*)[^.;]{0,100}?(?:by\s+(?:way\s+of\s+)?merger|operation\s+of\s+law|merger|consolidation)", re.I)


def _coc(sent):
    if _DEF.match(sent):
        return None
    for m in _COC.finditer(sent):
        if not _negated(sent, m.start()) and not re.search(r"\b(?:does not|do not|did not|has no|have no|contains? no)\b[^.]{0,40}(?:contain|include|provide|have)", sent[:m.start()], re.I):
            if _COC_OP.search(sent):
                return {"severity": "high", "title": "Change-of-control provision",
                        "detail": "Change of control triggers consent, termination or acceleration rights; confirm the transaction does not trip it."}
    m = _ASSIGN.search(sent)
    if m and re.search(r"consent|prohibit|not (?:be )?(?:assign|transfer)|void|terminat", sent, re.I) and not _negated(sent, m.start()):
        return {"severity": "high", "title": "Assignment by merger / operation of law requires consent",
                "detail": "Assignment through merger or operation of law is restricted or needs counterparty consent."}
    return None


_RATIO = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x\b|×|:\s*1(?:\.0+)?\b|to\s+1(?:\.0+)?\b)", re.I)
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:million|billion|m\b|mm\b|bn\b)?", re.I)
_OPV = re.compile(r"shall not|not exceed|to exceed|no (?:greater|higher|more) than|at least|not be less|not to be less|minimum|maximum|maintain|not permit|shall not permit|exceed", re.I)
_MAINT = [
    ("leverage", re.compile(r"leverage ratio|(?:total |net |senior |secured )?(?:debt|indebtedness)\s+(?:to|/)\s+(?:consolidated\s+)?(?:adjusted\s+)?EBITDA|net debt\s*/\s*EBITDA", re.I)),
    ("interest coverage", re.compile(r"interest coverage|fixed charge coverage|debt service coverage|EBITDA\s+to\s+interest", re.I)),
    ("minimum liquidity / EBITDA", re.compile(r"minimum\s+(?:consolidated\s+)?(?:liquidity|EBITDA|net worth|cash)|liquidity of at least|(?:liquidity|EBITDA) (?:of )?(?:not less than|at least)", re.I)),
    ("capex limit", re.compile(r"capital expenditures?[^.;]{0,60}(?:shall not|not to|to) exceed|capex[^.;]{0,40}(?:not exceed|limit)", re.I)),
]
_NEGCOV = re.compile(r"(?:shall not|will not|may not|agrees not to|not (?:create|incur|permit|suffer|declare|pay|make|assume))[^.;]{0,140}?"
                     r"(indebtedness|additional (?:debt|indebtedness)|incur\w*\s+(?:any\s+)?debt|\bliens?\b|dividends?|distributions?|restricted payments?)", re.I)


def _covenant(sent):
    if _DEF.match(sent):
        return None
    for label, rx in _MAINT:
        m = rx.search(sent)
        if m and not _negated(sent, m.start(), True) and (_OPV.search(sent) or _RATIO.search(sent)) and not re.search(r"\bmeans\b", sent[:m.start()], re.I):
            thr = _RATIO.search(sent) if label in ("leverage", "interest coverage") else (_MONEY.search(sent) or _RATIO.search(sent))
            if label == "capex limit":
                thr = _MONEY.search(sent)
            if thr is None:
                thr = _RATIO.search(sent) or _MONEY.search(sent)
            if thr is not None and thr.re is _RATIO:
                val = f"{float(thr.group(1)):g}x"
            else:
                val = re.sub(r"\s+", " ", thr.group(0)).strip() if thr else None
            d = f"Financial maintenance covenant ({label})."
            if val:
                d += f" Threshold: {val}."
            return {"severity": "high", "title": f"Financial maintenance covenant: {label}", "detail": d, "threshold": val}
    m = _NEGCOV.search(sent)
    if m and not _negated(sent, m.start(), True):
        what = m.group(1).lower()
        kind = "liens" if "lien" in what else "dividends / distributions" if re.search(r"dividend|distribution|restricted", what) else "additional indebtedness"
        return {"severity": "medium", "title": f"Negative covenant: restriction on {kind}", "detail": f"Negative covenant restricting {kind}."}
    return None


_MFN = re.compile(r"most[- ]favou?red[- ](?:nation|customer|pricing|terms|licensee|buyer|clause)|\bMFN\b|no less favou?rable than|price parity|"
                  r"(?:pricing|prices?|rates?|terms)[^.;]{0,80}(?:no (?:higher|greater) than|equal to or better than|lowest)[^.;]{0,60}(?:any other|other customers?|any third)", re.I)


def _mfn(sent):
    if _DEF.match(sent):
        return None
    m = _MFN.search(sent)
    if m and not _negated(sent, m.start()):
        sev = "high" if re.search(r"refund|rebate|true-?up|retroactiv|audit|credit", sent, re.I) else "medium"
        return {"severity": sev, "title": "Most-favoured-nation / price-parity clause",
                "detail": "Pricing is tied to the best terms given to other customers; later discounts may reprice this contract."}
    return None


_DEALERS = r"(?:supplier|vendor|distributor|reseller|manufacturer|customer|client|licensee|licensor|dealer|agent|provider|contractor|source|buyer|purchaser|party|parties)"
_TRADE_VERB = (r"(?:suppl\w+|provid\w+|sell\w*|sold|offer\w*|market\w*|distribut\w+|licen[sc]\w+|purchas\w+|buy\w*|procur\w+|sourc\w+|obtain\w*|"
               r"appoint\w*|engag\w+|retain\w*|contract\w*|deal\w*|trad\w+|negotiat\w+|solicit\w*|sublicen[sc]\w+|resell\w*)")
_EXCL = [
    (re.compile(r"(?<!non-)(?<!non )(?<!non)\b(?:exclusive(?:ly)?\s+(?:supplier|distributor|distribution|territory|licen[sc]e|licen[sc]ee|dealer|reseller|provider|rights?|basis|agent|"
                r"manufacturer|purchaser|vendor|relationship|customer|client|buyer|channel|partner)|"
                r"(?:sole|only)\s+(?:and\s+exclusive\s+)?(?:supplier|distributor|source|provider|vendor|customer|reseller|licensee)\b|"
                r"(?:sole\s+and\s+)(?<!non-)exclusive|purchase[^.;]{0,60}exclusively from|exclusive(?:ly)? (?:from|to) |"
                r"exclusivity\s+(?:discussions?|negotiations?|period|undertaking|agreement|arrangement|provisions?|obligations?|rights?|clause)|"
                r"(?:grants?|granted|granting|giving|gives?|given|agrees? to|enter(?:s|ed)? into)\s+(?:[\w-]+\s+){0,3}?exclusivity)", re.I), "high", "Exclusivity"),
    (re.compile(r"non-?compet\w*|shall not compete|agrees? not to compete|covenant not to compete", re.I), "high", "Non-compete"),
    (re.compile(r"non-?solicit\w*|shall not (?:directly or indirectly )?(?:solicit|hire)", re.I), "medium", "Non-solicit"),
    # operative prohibitions: "shall not supply any competing customer", "will not appoint any other distributor"
    (re.compile(r"\b(?:shall|will|may|must|agrees?\s+to|undertakes?\s+to|covenants?\s+to)\s+not\s+(?!be\b|been\b|have\b|become\b|unreasonably\b)(?:\w+\s+){0,3}?" + _TRADE_VERB +
                r"\b[^.;]{0,140}?\b(?:any\s+other\b|any\s+third[- ]part\w+|any\s+competing\b|any\s+competitors?\b|competitors?\b|competing\b|"
                r"other\s+" + _DEALERS + r"s?\b|any\s+person\s+other\s+than)", re.I), "high", "Exclusivity (restriction on dealing with others)"),
    (re.compile(r"\b(?:shall|will|may|must)\s+not\b[^.;]{0,100}\b(?:from|with)\s+any\s+(?:source|supplier|vendor|distributor|person|party)\s+other\s+than\b", re.I),
     "high", "Exclusivity (restriction on dealing with others)"),
    (re.compile(r"(?:shall|will|may) not[^.;]{0,120}\bwith any other\b", re.I), "medium", "Restriction on dealing with others"),
]
_EXCL_DECOY = re.compile(r"\bnon-?exclusive\b|\b(?:nothing|no\s+provision|no\s+term)\b[^.;]{0,140}\b(?:exclusiv\w*|prevent\w*|restrict\w*|prohibit\w*|limit\w*|oblig\w*)|"
                         r"\b(?:free|entitled|permitted|at liberty)\s+to\b|\bremains?\s+free\b|\b(?:is|are|be)\s+not\s+(?:an?\s+)?exclusive\b|"
                         r"\bno\s+exclusiv\w+|\bwithout\s+exclusiv\w+|\bnot\s+(?:grant|create|confer|give|imply|intended to (?:grant|create))\w*\s+(?:\w+\s+){0,6}exclusiv", re.I)


def _excl(sent):
    if _DEF.match(sent):
        return None
    if _EXCL_DECOY.search(sent):
        return None
    for rx, sev, label in _EXCL:
        for m in rx.finditer(sent):
            self_neg = bool(re.match(r"(?:shall|will|may|must|covenant|agrees?|undertakes?) (?:not|to not)|covenant not|agrees? not", m.group(0), re.I)) or "not" in m.group(0)[:20].lower()
            if not self_neg and _negated(sent, m.start()):
                continue
            return {"severity": sev, "title": f"{label} clause", "detail": f"{label}: restricts who the parties may deal with."}
    return None


# --------------------------------------------------------------------------- Arabic clauses
_AR_RE = re.compile(r"[؀-ۿ]")
_AR_STRIP = re.compile(r"[ً-ٰٟـ‎‏‪-‮]")


def _ar(s: str) -> str:
    """Normalised Arabic for matching only (quotes always keep the original text): NFKC, no diacritics/tatweel, alef and yeh variants folded."""
    s = _AR_STRIP.sub("", unicodedata.normalize("NFKC", s))
    return re.sub(r"[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه")


def _has_ar(s: str) -> bool:
    return len(_AR_RE.findall(s)) >= 6


_AR_NEG = re.compile(r"(?:غير|ليس|ليست|لا\s+يوجد|لا\s+توجد|لا\s+يتضمن|لا\s+يمنح|لا\s+ينش\w*|لا\s+يترتب|لا\s+يعني|لا\s+يشمل|دون|بدون|باستثناء|عدم)[^.،؛]{0,40}$")
_AR_DEF = re.compile(r"^[\"“«(]?\s*(?:تغيير\s+السيطره|السيطره|نسبه[\w ]{2,30})\s*[\"”»)]?\s*(?:يعني|تعني|يقصد|يقصد\s+ب|هو|هي|يشير)\b")


def _ar_negated(n: str, start: int) -> bool:
    return bool(_AR_NEG.search(n[max(0, start - 45):start]))


_AR_EXCL = re.compile(r"حصري\w*")
_AR_EXCL_PROHIB = re.compile(r"(?:لا\s+يجوز|لن\s+(?:يقوم|يحق|يسمح)|لا\s+يحق|يحظر|يمتنع|لا\s+يتعاقد|لا\s+يعين|لا\s+يبيع|لا\s+يشتري|لا\s+يورد)"
                             r"[^.؛]{0,120}?(?:شراء|توريد|بيع|تعيين|التعاقد|التعامل|توزيع|تزويد|الحصول|استيراد|تسويق)[^.؛]{0,120}?"
                             r"(?:من|الي|لدي|الي\s+اي|لاي|مع)?\s*(?:اي|لاي)\s+(?:مورد|موزع|وكيل|جهه|طرف|مصدر|مصنع|منافس|بايع|مشتر)\w*\s*(?:اخر|ثالث|اخرين|منافس)")
_AR_COC = re.compile(r"(?:تغيير|تغير|تحول|انتقال)\s+(?:في\s+)?(?:السيطره|الملكيه|ملكيه|الرقابه|الاداره)|الاستحواذ\s+علي\s+(?:الشركه|الطرف|المورد|المشتري|المستاجر|المؤجر)|"
                    r"(?:الاندماج|الاستحواذ)\s+(?:مع|علي)")
_AR_COC_OP = re.compile(r"موافق|انهاء|انهاء|فسخ|تسريع|استحقاق|يحق|اخطار|اشعار|اعتراض|يجوز\s+(?:ل|للطرف)|ما\s+لم")
_AR_MFN = re.compile(r"(?:الدوله|المعامله|الشروط)\s+الاكثر\s+(?:رعايه|تفضيلا)|الاكثر\s+رعايه|لا\s+(?:تقل|يقل)\s+(?:\w+\s+){0,2}(?:افضليه|مواتاه|ملاءمه)\s+عن|"
                     r"افضل\s+(?:الشروط|الاسعار|سعر|شروط)\s+(?:الممنوحه|المقدمه|المعروضه|التي)|اقل\s+سعر\s+(?:ممنوح|مقدم|معروض)")
_AR_COV = re.compile(r"(?:تعهدات\s+ماليه|التعهدات\s+الماليه|نسبه\s+(?:الدين|الديون|المديونيه)\s+(?:الي|الى|/|علي)\s+(?:الارباح|الايبيتدا|EBITDA|الدخل)|"
                     r"نسبه\s+تغطيه\s+(?:الفوائد|خدمه\s+الدين)|الحد\s+الادني\s+(?:ل)?(?:لسيوله|السيوله|صافي\s+الثروه))", re.I)
_AR_COV_OP = re.compile(r"يجب|لا\s+(?:تزيد|تتجاوز|تقل|يزيد|يتجاوز|يقل)|الحد\s+الاقصي|الحد\s+الادني|الحفاظ|التزام|تتعهد|يتعهد")


def _ar_clause(kind, sent):
    n = _ar(sent)
    if _AR_DEF.match(n):
        return None
    if kind == "exclusivity":
        if re.search(r"غير\s+حصري|ليس\s+حصري", n) and not _AR_EXCL_PROHIB.search(n):
            return None
        for m in _AR_EXCL.finditer(n):
            if _ar_negated(n, m.start()):
                continue
            return {"severity": "high", "title": "Exclusivity clause", "detail": "Exclusivity: restricts who the parties may deal with."}
        m = _AR_EXCL_PROHIB.search(n)
        if m and not _ar_negated(n, m.start()):
            return {"severity": "high", "title": "Exclusivity (restriction on dealing with others) clause",
                    "detail": "Exclusivity (restriction on dealing with others): restricts who the parties may deal with."}
    elif kind == "change_of_control":
        m = _AR_COC.search(n)
        if m and _AR_COC_OP.search(n) and not _ar_negated(n, m.start()) and not re.search(r"لا\s+(?:يوجد|توجد|يتضمن)", n[:m.start()]):
            return {"severity": "high", "title": "Change-of-control provision",
                    "detail": "Change of control triggers consent, termination or acceleration rights; confirm the transaction does not trip it."}
    elif kind == "mfn":
        m = _AR_MFN.search(n)
        if m and not _ar_negated(n, m.start()):
            return {"severity": "medium", "title": "Most-favoured-nation / price-parity clause",
                    "detail": "Pricing is tied to the best terms given to other customers; later discounts may reprice this contract."}
    elif kind == "covenant":
        m = _AR_COV.search(n)
        if m and _AR_COV_OP.search(n) and not _ar_negated(n, m.start()):
            thr = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|×|مره|مرات|الي\s*1)", n)
            val = f"{float(thr.group(1)):g}x" if thr else None
            d = "Financial maintenance covenant." + (f" Threshold: {val}." if val else "")
            return {"severity": "high", "title": "Financial maintenance covenant", "detail": d, "threshold": val}
    return None


def _with_ar(kind, fn):
    def run(sent):
        hit = fn(sent)
        if hit is None and _has_ar(sent):
            return _ar_clause(kind, sent)
        return hit
    return run


CLAUSES = (("change_of_control", _with_ar("change_of_control", _coc)), ("covenant", _with_ar("covenant", _covenant)),
           ("mfn", _with_ar("mfn", _mfn)), ("exclusivity", _with_ar("exclusivity", _excl)))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().lower()


# --------------------------------------------------------------------------- locating
class _DocLocator:
    """Default locator: om.docparse words (logical-order Arabic, OCR for scanned pages) -> bbox + span hash of the exact quote."""

    def __init__(self):
        self._cache = {}

    def __call__(self, doc, page, quote):
        src = doc.get("pdf")
        if src is None or not quote or page is None:
            return None
        key = doc["doc_id"]
        if key not in self._cache:
            try:
                from om import docparse
                self._cache[key] = docparse.parse(src, backend="pdfdoc")
            except Exception:
                self._cache[key] = None
        parsed = self._cache[key]
        if parsed is None:
            return None
        from om import docparse
        try:
            loc = docparse.locate(parsed, page, quote)
        except Exception:
            return None
        if loc is None:
            return None
        return {"bbox_norm": tuple(loc.bbox_norm), "sha256_span_hash": loc.sha256_span_hash}


def _valid_loc(loc) -> bool:
    try:
        b = loc["bbox_norm"]
        h = loc["sha256_span_hash"]
        return (len(b) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in b) and b[0] <= b[2] and b[1] <= b[3]
                and isinstance(h, str) and bool(re.fullmatch(r"[0-9a-f]{64}", h)))
    except Exception:
        return False


def _do_locate(fn, doc, page, quote):
    try:
        loc = fn(doc, page, quote)
    except Exception:
        return None
    return loc if loc and _valid_loc(loc) else None


# --------------------------------------------------------------------------- scanning
def _fid(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _page_items(doc):
    """[(page_no|None, text)] from doc['pages'] (list of str, 1-based) or doc['page_items']."""
    if doc.get("page_items") is not None:
        return list(doc["page_items"])
    return [(i + 1, t or "") for i, t in enumerate(doc.get("pages") or [])]


def _anchor(text: str, quote: str, raw: str = "") -> str | None:
    if quote and quote in text:
        return quote
    for s, e, sent in sentences(text):
        if (quote and _norm(quote) and _norm(quote) in _norm(sent)) or (raw and raw in sent):
            return sent
    return None


def scan_documents(docs, *, expected_periods=None, checklist=DEFAULT_CHECKLIST, locate=None, _facts=None) -> dict:
    docs = [dict(d) for d in docs]
    locator = locate or _DocLocator()
    by_id = {d["doc_id"]: d for d in docs}
    ptext = {(d["doc_id"], p): t for d in docs for p, t in _page_items(d)}
    cats = {d["doc_id"]: _classify(d, checklist) for d in docs}
    findings: list[dict] = []

    def finish(f, doc):
        f = dict(f)
        f.setdefault("related", [])
        f["bbox_norm"], f["sha256_span_hash"] = None, None
        if doc is not None and doc.get("pdf") is not None and f["page"] is not None and f["quote"]:
            loc = _do_locate(locator, doc, f["page"], f["quote"])
            if loc:
                f["bbox_norm"], f["sha256_span_hash"] = tuple(loc["bbox_norm"]), loc["sha256_span_hash"]
            else:
                f["locate_failed"] = True
        for r in f["related"]:
            rd = by_id.get(r.get("doc_id"))
            if rd is not None and rd.get("pdf") is not None and r.get("page") is not None and r.get("quote"):
                loc = _do_locate(locator, rd, r["page"], r["quote"])
                r["bbox_norm"], r["sha256_span_hash"] = (tuple(loc["bbox_norm"]), loc["sha256_span_hash"]) if loc else (None, None)
        f["id"] = _fid(f["type"], f.get("doc_id"), f.get("page"), f.get("quote"), f["title"])
        return f

    # 1. periods + 2. checklist
    pf, period_cov = _period_findings(docs, cats, expected_periods)
    for f in pf:
        findings.append(finish(f, None))
    present = {c["id"]: [d["name"] for d in docs if c["id"] in cats[d["doc_id"]]] for c in checklist}
    for c in checklist:
        if not present[c["id"]]:
            findings.append(finish({"type": "missing_document", "severity": c["severity"], "title": f"Missing: {c['label']}",
                                    "detail": f"No document in the data room looks like '{c['label']}'.", "doc_id": None, "doc_name": None,
                                    "page": None, "quote": "", "related": []}, None))

    # 4. clause risks
    for d in docs:
        seen = set()
        for page, text in _page_items(d):
            for s, e, sent in sentences(text):
                for typ, fn in CLAUSES:
                    hit = fn(sent)
                    if not hit:
                        continue
                    key = (typ, _norm(sent))
                    if key in seen:
                        continue
                    seen.add(key)
                    f = {"type": typ, "severity": hit["severity"], "title": hit["title"], "detail": hit["detail"], "doc_id": d["doc_id"],
                         "doc_name": d["name"], "page": page, "quote": text[s:e], "related": []}
                    if hit.get("threshold"):
                        f["threshold"] = hit["threshold"]
                    findings.append(finish(f, d))

    # 3. conflicts
    findings += _conflict_findings(docs, ptext, by_id, finish, _facts)

    findings.sort(key=lambda f: (TYPES.index(f["type"]), SEV_RANK[f["severity"]], str(f.get("doc_name") or ""), f.get("page") or 0, f["quote"], f["title"]))
    return _report(findings, docs, {"periods": period_cov, "checklist": {c["id"]: {"label": c["label"], "documents": present[c["id"]]} for c in checklist}})


def _report(findings, docs, coverage):
    bt, bs = {t: 0 for t in TYPES}, {}
    for f in findings:
        bt[f["type"]] += 1
        bs[f["severity"]] = bs.get(f["severity"], 0) + 1
    return {"findings": findings, "summary": {"by_type": bt, "by_severity": {k: bs[k] for k in sorted(bs, key=SEV_RANK.get)}, "documents": len(docs)},
            "coverage": coverage}


# --------------------------------------------------------------------------- figure conflicts
# Only statement lines (label = exactly one canonical total metric, columns named by period headers) and explicit metric sentences
# ("Total revenue for FY2024 was USD 52.9 million") become facts. Narrative mentions, components, FX effects, segments and
# comparatives never do, and figures are only paired across documents of the same entity.
_FACT_METRICS = {m for m, k in cs.KIND.items() if k in ("money", "pct") and m not in cs.POINT_IN_TIME and not m.endswith("_growth")
                 and m not in ("ev", "equity_value", "eps", "wacc") and not m.startswith("~")}
_BAD_BASIS = re.compile(r"segment|division|region|geograph|currenc|foreign|exchange|\bfx\b|impact|effect|attributable|per\s+share|organic|constant|excluding|"
                        r"\bexcl\b|of\s+which|including|incl\.|acquisition|pro[- ]?forma|increas|decreas|declin|growth|grew|\brose\b|\bfell\b|compared|"
                        r"versus|\bvs\b|\bfrom\b|\bup\b|\bdown\b|lower|higher|offset|benefit|favorabl|favourabl|related to|due to|contribut|portion|"
                        r"\bby\s+\$|target|budget|forecast|guidance|outlook|expect|project|estimate|plan|\bmonths?\b|\bquarters?\b|\bq[1-4]\b|\bh[12]\b", re.I)
_UNIT_SCALES = [(re.compile(r"in\s+thousands|\(\s*000'?s?\s*\)|'000|\$\s?000|\bthousands?\b|\bk\b\)", re.I), 1e3),
                (re.compile(r"in\s+millions|\(\s*(?:us)?\$?\s?m(?:m|n)?\s*\)|\bmillions?\b|\$\s?m\b", re.I), 1e6),
                (re.compile(r"in\s+billions|\(\s*(?:us)?\$?\s?bn?\s*\)|\bbillions?\b|\$\s?bn\b", re.I), 1e9),
                (re.compile(r"\b(?:usd|eur|gbp|aed|sar|cad|aud|chf|jpy)\b|us\$|[$€£]", re.I), 1.0)]
_STMT_ROW = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z ,&/'()\-]*?[A-Za-z)])\s+(?P<nums>(?:\(?[-−]?[$€£]?\s?\d[\d,]*(?:\.\d+)?\s?%?\)?[ \t]*){1,8})\s*$")


def _unit_scale(text: str):
    for rx, sc in _UNIT_SCALES:
        if rx.search(text):
            return sc
    return None


def _fy_labels(s: str):
    out = []
    for ym in _YEAR_ENDED.finditer(s):
        if _year_ok(int(ym.group(1))):
            out.append((ym.start(), ym.end(), f"FY{ym.group(1)}"))
    taken = [(a, b) for a, b, _ in out]
    for a, b, p, proj in cs.find_periods(s):
        if proj or any(a < tb and ta < b for ta, tb in taken):
            continue
        if re.fullmatch(r"(?:FY|)(?:19|20)\d{2}|FY(?:19|20)\d{2}|Q[1-4] (?:19|20)\d{2}|H[12] (?:19|20)\d{2}", p) and _year_ok(int(re.search(r"(?:19|20)\d{2}", p).group(0))):
            out.append((a, b, p if not p.isdigit() else f"FY{p}"))
    return sorted(out)


def _fact_ok(f) -> bool:
    if f.kind == "pct":
        lim = (0.0, 100.0) if f.metric.endswith("_margin") else (-1000.0, 1000.0)
        return lim[0] <= f.value <= lim[1]
    return f.kind == "money"


def _doc_facts(d):
    out = []
    for page, text in _page_items(d):
        lines = text.split("\n")
        # statement lines under a period header
        for i, ln in enumerate(lines):
            m = _STMT_ROW.match(ln)
            if not m:
                continue
            metric = cs.canon_metric(m.group("label"))
            if metric not in _FACT_METRICS:
                continue
            nums = cs.parse_numbers(m.group("nums"), accounting=True)
            if not nums:
                continue
            hdr = None
            for j in range(i - 1, max(-1, i - 9), -1):
                cand = lines[j]
                labs = _fy_labels(cand)
                if labs:
                    rest = re.sub(r"[()$€£,/|-]", " ", cand)
                    for a, b, _ in reversed(labs):
                        rest = rest[:a] + " " + rest[b:]
                    if len(re.findall(r"[A-Za-z]{3,}", rest)) <= 4 and not cs.PROJECTION.search(cand) and not cs.SCENARIO_COL.search(cand):
                        hdr = (j, labs)
                    break
                if _STMT_ROW.match(cand) and j < i - 1:
                    pass
            if hdr is None:
                continue
            j, labs = hdr
            pers = [p for _a, _b, p in labs]
            if len(pers) != len(nums) or len(set(pers)) != len(pers):
                continue
            scale = _unit_scale(" ".join(lines[max(0, j - 3):j + 1]) + " " + " ".join(lines[:3]))
            for n, per in zip(nums, pers):
                if KIND_OF(metric) == "pct" and n.kind != "pct":
                    continue
                f = cs.make_fact(n, metric, kind_hint=None, scale_hint=scale, entity=None, period=per, projection=False, source=d["name"],
                                 where=f"{d['name']} · p.{page}", quote=ln.strip(), origin="table", page=page, doc_id=d["doc_id"])
                if f and _fact_ok(f):
                    out.append(f)
        # explicit metric sentences
        for s, e, sent in sentences(text):
            if len(sent) > 300 or not re.search(r"\d", sent) or _BAD_BASIS.search(re.sub(_YEAR_ENDED, " ", sent)):
                continue
            labs = _fy_labels(sent)
            pers = {p for _a, _b, p in labs}
            if len(pers) != 1 or cs.PROJECTION.search(sent):
                continue
            per = next(iter(pers))
            S2 = sent
            for a, b, p in reversed(labs):
                S2 = S2[:a] + p + S2[a:b][len(S2[a:b].rstrip()):] + S2[b:]
            nums = cs.parse_numbers(S2, accounting=False)
            for a, b, metric in cs.metric_mentions(S2):
                if metric not in _FACT_METRICS:
                    continue
                nxt = next((n for n in nums if n.start >= b and not re.fullmatch(r"(?:19|20)\d{2}", n.raw) and n.raw.strip() != per[2:]), None)
                if nxt is None or not cs.BEFORE_LINK.match(cs._strip_periods(S2[b:nxt.start])):
                    continue
                if any(a2 <= nxt.start < b2 for a2, b2, _ in [(x[0], x[1], 0) for x in cs.find_periods(S2)] if re.fullmatch(r"(?:FY)?(?:19|20)\d{2}", S2[a2:b2], re.I)):
                    continue
                if KIND_OF(metric) == "pct" and nxt.kind != "pct":
                    continue
                f = cs.make_fact(nxt, metric, kind_hint=None, scale_hint=None, entity=None, period=per, projection=False, source=d["name"],
                                 where=f"{d['name']} · p.{page}", quote=text[s:e], origin="text", page=page, doc_id=d["doc_id"])
                if f and _fact_ok(f):
                    out.append(f)
    return out


def KIND_OF(metric):
    return cs.KIND.get(metric)


def _conflict_findings(docs, ptext, by_id, finish, facts=None):
    raw = []
    for d in docs:
        raw += _doc_facts(d)
    if not raw:
        return []
    clusters, disp = _entity_clusters([by_id[i] for i in {f.doc_id for f in raw}])
    for f in raw:
        key = clusters[f.doc_id]
        f.entity = disp.get(key, "") if not key.startswith("solo:") else key
    out = []
    for issue in cs.find_conflicts(raw, None, scope="room"):
        items, used = [], set()
        for g in issue["groups"]:
            pick = next((it for it in g if it.get("doc_id") not in used), g[0])
            used.add(pick.get("doc_id"))
            items.append(pick)
        if len({it.get("doc_id") for it in items}) < 2:
            continue

        def ref(it):
            did, pg = it.get("doc_id"), it.get("page")
            q = it.get("quote") or ""
            text = ptext.get((did, pg))
            if text is not None:
                q = _anchor(text, q, str(it.get("value") or "")) or ""
            return {"doc_id": did, "doc_name": by_id[did]["name"] if did in by_id else it.get("source"), "page": pg, "quote": q,
                    "value": it.get("value"), "period": it.get("period")}
        refs = [ref(i) for i in items]
        p = refs[0]
        out.append(finish({"type": "conflicting_figure", "severity": issue["severity"], "title": issue["title"], "detail": issue.get("detail", ""),
                           "doc_id": p["doc_id"], "doc_name": p["doc_name"], "page": p["page"], "quote": p["quote"], "related": refs[1:],
                           "metric": issue.get("metric"), "period": issue.get("period")}, by_id.get(p["doc_id"])))
    return out


def scan_room(index, rooms, room_id, *, expected_periods=None, checklist=DEFAULT_CHECKLIST, locate=None) -> dict:
    docs = []
    for d in rooms.documents(room_id):
        grouped: dict = {}
        order = []
        for c in index.db.execute("SELECT text, section FROM chunks WHERE doc_id=? ORDER BY ord", (d["doc_id"],)):
            m = re.search(r"p\.(\d+)", c["section"] or "")
            pg = int(m.group(1)) if m else None
            if pg not in grouped:
                grouped[pg] = []
                order.append(pg)
            grouped[pg].append(c["text"])
        items = [(p, "\n".join(grouped[p])) for p in sorted((p for p in order if p is not None))]
        if None in grouped:
            items.append((None, "\n".join(grouped[None])))
        fp = rooms.file_path(d["doc_id"])
        docs.append({"doc_id": d["doc_id"], "name": d["path"], "pages": [t for _, t in items], "page_items": items,
                     "pdf": str(fp) if fp is not None and Path(d["path"]).suffix.lower() == ".pdf" else None})
    return scan_documents(docs, expected_periods=expected_periods, checklist=checklist, locate=locate)
