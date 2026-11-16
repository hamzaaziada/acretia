"""VDR gap and risk detector (S5.3). Deterministic, no LLM.

scan_room / scan_documents -> {"findings", "summary", "coverage"}. Detectors: missing financial periods, missing standard
document categories, conflicting figures (via om.consistency) and sentence-level clause risks (change of control, covenants,
MFN, exclusivity). Every clause quote is an exact substring of its page text; PDF findings carry a located bbox + span hash,
or bbox None and locate_failed=True (a box is never invented)."""
from __future__ import annotations

import bisect
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


# --------------------------------------------------------------------------- periods
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MON_RE = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?[\s_-]+((?:19|20)\d{2})\b", re.I)
_ISO_MON = re.compile(r"\b((?:19|20)\d{2})[-_/](0[1-9]|1[0-2])\b(?![-_/]\d)")


def period_of(text: str):
    """-> (kind, key) with kind annual|quarter|month; key FY2023 | (2024, 3) | (2024, 3) or None."""
    m = _MON_RE.search(text)
    if m:
        return "month", (int(m.group(2)), _MONTHS.index(m.group(1)[:3].lower()) + 1)
    m = _ISO_MON.search(text)
    if m:
        return "month", (int(m.group(1)), int(m.group(2)))
    for _s, _e, p, proj in cs.find_periods(text):
        if proj:
            continue
        q = re.fullmatch(r"Q([1-4]) ((?:19|20)\d{2})", p)
        if q:
            return "quarter", (int(q.group(2)), int(q.group(1)))
        if re.fullmatch(r"FY(?:19|20)\d{2}", p):
            return "annual", int(p[2:])
    return None


def _fmt_q(k):
    return f"Q{k[1]} {k[0]}"


def _fmt_m(k):
    return f"{k[0]}-{k[1]:02d}"


def _idx_q(k):
    return k[0] * 4 + k[1] - 1


def _idx_m(k):
    return k[0] * 12 + k[1] - 1


def _coverage(docs, cats):
    cov = {"annual": {}, "quarter": {}, "month": {}}
    audited_years = set()
    for d in docs:
        c = cats[d["doc_id"]]
        if not c & {"audited_financials", "management_accounts"}:
            continue
        base = Path(str(d["name"])).name
        p = period_of(base) or period_of(_first_text(d)[:300])
        if not p:
            continue
        kind, key = p
        cov[kind].setdefault(key, []).append(d)
        if kind == "annual" and "audited_financials" in c:
            audited_years.add(key)
    return cov, audited_years


def _period_findings(docs, cats, expected):
    cov, audited_years = _coverage(docs, cats)
    out = []

    def doc_ref(d):
        return {"doc_id": d["doc_id"], "doc_name": d["name"]}

    def add(kind, label, sev, neighbours, why):
        rel = [dict(doc_ref(d), period=lab) for d, lab in neighbours]
        out.append({"type": "missing_period", "severity": sev, "title": f"Missing {label}", "detail": why, "doc_id": None, "doc_name": None,
                    "page": None, "quote": "", "bbox_norm": None, "sha256_span_hash": None, "related": rel, "_key": (kind, label)})

    months_have = set(cov["month"])
    quarters_have = set(cov["quarter"])

    def q_covered(q):
        return q in quarters_have or all((q[0], (q[1] - 1) * 3 + i) in months_have for i in (1, 2, 3))

    def m_covered(m):
        return m in months_have or ((m[0], (m[1] - 1) // 3 + 1) in quarters_have)

    def nb(kind, keys, fmt):
        return [(cov[kind][k][0], fmt(k)) for k in keys if k in cov[kind]]

    ys = sorted(cov["annual"])
    for y in range(ys[0], ys[-1]) if ys else []:
        if y not in cov["annual"] and (y not in range(0)):
            if all(q_covered((y, i)) for i in (1, 2, 3, 4)):
                continue
            sev = "high" if audited_years else "medium"
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
    for e in expected or []:
        p = period_of(str(e))
        if not p:
            continue
        kind, key = p
        if kind == "annual":
            ok = key in cov["annual"] or all(q_covered((key, i)) for i in (1, 2, 3, 4))
            lab, sev = f"FY{key}", "high"
        elif kind == "quarter":
            ok, lab, sev = q_covered(key), _fmt_q(key), "medium"
        else:
            ok, lab, sev = m_covered(key), _fmt_m(key), "medium"
        if not ok and (kind, lab) not in have:
            have.add((kind, lab))
            add(kind, lab, sev, [], f"{lab} was expected in the data room but no matching financial statements or management accounts were found.")
    for f in out:
        f.pop("_key")
    cover = {"annual": [f"FY{k}" for k in sorted(cov["annual"])], "quarterly": [_fmt_q(k) for k in sorted(cov["quarter"], key=_idx_q)],
             "monthly": [_fmt_m(k) for k in sorted(cov["month"], key=_idx_m)]}
    return out, cover


# --------------------------------------------------------------------------- clause detectors
_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"“])|\n+")
_NEG = re.compile(r"\b(?:no|not|nothing|neither|nor|without|never|absence of|free of|n't)\b", re.I)
_DEF = re.compile(r"^[\"“'(]*(?:change\s+(?:of|in)\s+control|[A-Z][\w ]{2,50}ratio|[A-Z][\w ]{2,50}coverage)[\"”']*\s*(?:\w+\s+)?(?:means|shall mean|has the meaning|is defined|refers to)\b", re.I)


def sentences(text: str):
    pos, spans = 0, []
    for m in _SPLIT.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
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


_EXCL = [
    (re.compile(r"(?<!non-)(?<!non )(?<!non)exclusive(?:ly)?\s+(?:supplier|distributor|distribution|territory|licen[sc]e|licen[sc]ee|dealer|reseller|provider|rights?|basis|agent|manufacturer|purchaser|vendor|relationship)|"
                r"(?:sole\s+and\s+)(?<!non-)exclusive|purchase[^.;]{0,60}exclusively from|exclusive(?:ly)? (?:from|to) ", re.I), "high", "Exclusivity"),
    (re.compile(r"non-?compet\w*|shall not compete|agrees? not to compete|covenant not to compete", re.I), "high", "Non-compete"),
    (re.compile(r"non-?solicit\w*|shall not (?:directly or indirectly )?(?:solicit|hire)", re.I), "medium", "Non-solicit"),
    (re.compile(r"(?:shall|will|may) not[^.;]{0,120}\bwith any other\b", re.I), "medium", "Restriction on dealing with others"),
]


def _excl(sent):
    if _DEF.match(sent):
        return None
    for rx, sev, label in _EXCL:
        for m in rx.finditer(sent):
            self_neg = bool(re.match(r"(?:shall|will|may) not|covenant not|agrees? not", m.group(0), re.I))
            if not self_neg and _negated(sent, m.start()):
                continue
            return {"severity": sev, "title": f"{label} clause", "detail": f"{label}: restricts who the parties may deal with."}
    return None


CLAUSES = (("change_of_control", _coc), ("covenant", _covenant), ("mfn", _mfn), ("exclusivity", _excl))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().lower()


# --------------------------------------------------------------------------- locating
class _PdfLocator:
    def __init__(self):
        self._cache = {}

    def __call__(self, doc, page, quote):
        src = doc.get("pdf")
        if src is None or not quote or page is None:
            return None
        from om import pdfdoc
        key = doc["doc_id"]
        if key not in self._cache:
            try:
                self._cache[key] = pdfdoc.load(src, ocr="never") if _accepts_ocr() else pdfdoc.load(src)
            except Exception:
                self._cache[key] = None
        pd = self._cache[key]
        if pd is None:
            return None
        pg = next((p for p in pd.pages if p.number == page), None)
        if pg is None:
            return None
        words = [w for l in pg.lines for w in l.words] or list(pg.words)
        stream, starts, pos = [], [], 0
        for w in words:
            t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", w.text))
            starts.append(pos)
            stream.append(t)
            pos += len(t)
        s = "".join(stream)
        q = re.sub(r"\s+", "", unicodedata.normalize("NFKC", quote))
        i = s.find(q)
        if i < 0 or not q:
            return None
        a = bisect.bisect_right(starts, i) - 1
        b = bisect.bisect_right(starts, i + len(q) - 1) - 1
        ws = words[a:b + 1]
        box = (min(w.bbox_norm[0] for w in ws), min(w.bbox_norm[1] for w in ws), max(w.bbox_norm[2] for w in ws), max(w.bbox_norm[3] for w in ws))
        return {"bbox_norm": tuple(box), "sha256_span_hash": pdfdoc.span_hash(page, quote, box)}


def _accepts_ocr() -> bool:
    import inspect
    from om import pdfdoc
    return "ocr" in inspect.signature(pdfdoc.load).parameters


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
    locator = locate or _PdfLocator()
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


def _conflict_findings(docs, ptext, by_id, finish, facts=None):
    if facts is None:
        facts = []
        for d in docs:
            carry = None
            for page, text in _page_items(d):
                fs, carry = cs.text_facts(text, None, source=d["name"], where=f"{d['name']} · p.{page}", page=page, doc_id=d["doc_id"], carry_period=carry)
                facts += fs
    out = []
    for issue in cs.find_conflicts(facts, None, scope="room"):
        items = []
        for g in issue["groups"]:
            for it in g[:1]:
                items.append(it)
        items = [it for it in items if it.get("doc_id") in by_id] or items
        if len(items) < 2:
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
    from om.consistency import room_facts
    facts = room_facts(index, rooms, room_id)
    return scan_documents(docs, expected_periods=expected_periods, checklist=checklist, locate=locate, _facts=facts)
