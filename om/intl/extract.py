"""Annual-report extraction: PDF (native, scanned, Arabic, English or bilingual) -> `ExtractedStatements` (S8.3b).

Pipeline: native text layer (om.pdfdoc) or tesseract (om.intl.ocr) -> table reconstruction (om.intl.tables) ->
label mapping (om.intl.labels) -> number parsing (om.intl.numparse) -> sign convention, units, totals, derived EBIT
-> `Figure`s with page, bbox, confidence and span hash. No model call anywhere; the same bytes give the same numbers.

Decisions (also in DECISIONS.md D-S8-xx by the Boss):
* Sign: for keys whose `om.statements.LINES` sign is -1 and for the `x.` cost keys, a bracketed printed value is
  stored positive (`reasons += ["sign:deduction"]`); an unbracketed one in a statement that brackets its expenses is a
  credit and stored negative (`sign:credit`). Everything else keeps the printed sign. A loss label (`sign_hint -1`)
  printed without a bracket is stored negative (`sign:loss-label`).
* A label match below 0.7 confidence leaves the key `None` (reason `unmapped_label`); the figure is still extracted.
* A by-nature P&L without an operating-profit line gets a derived `ebit` Figure (`adjust.by_nature_ebit`).
* Numeric cells below 0.95 OCR confidence are re-read with `ocr.reocr_number`; a disagreement sets `status="review"`.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, timedelta

from .. import pdfdoc
from .. import statements as stm
from . import adjust, labels, numparse, tables
from .types import ExtractedStatements, Figure

COST_X = {"x.zakat", "x.rou_depreciation", "x.lease_interest", "x.employee_costs", "x.raw_materials", "x.depreciation",
          "x.amortisation", "x.other_opex", "x.selling_expenses", "x.admin_expenses"}
PER_SHARE = {"eps_diluted", "x.eps_basic"}
NOTE_KEYS = {"x.rou_depreciation", "x.lease_interest", "x.rou_assets", "x.lease_liabilities_current",
             "x.lease_liabilities_noncurrent"}
MIN_LABEL_CONF = 0.7
REOCR_BELOW = 0.95
OCR_FULL_DPI = 300
BIG_DOC_PAGES = 8


class ExtractError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ io helpers
def _read(pdf) -> bytes:
    if isinstance(pdf, (bytes, bytearray)):
        return bytes(pdf)
    with open(pdf, "rb") as fh:
        return fh.read()


def _page_png(path: str, n: int, dpi: int = OCR_FULL_DPI) -> bytes | None:
    with tempfile.TemporaryDirectory(prefix="acretia_pg_") as td:
        pre = os.path.join(td, "p")
        try:
            subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-f", str(n), "-l", str(n), "-singlefile", path, pre],
                           check=True, capture_output=True, timeout=120)
            with open(pre + ".png", "rb") as fh:
                return fh.read()
        except (OSError, subprocess.SubprocessError):
            return None


# ------------------------------------------------------------------------------------------------ keys and signs
def _lines_sign(key):
    ent = stm.LINES.get(key)
    return ent[2] if ent else 1


def _is_expense_key(key):
    return key in COST_X or (key in stm.LINES and _lines_sign(key) == -1)


# Arabic phrasings the label dictionary (S8.2) misses or scores as ambiguous. Used only when the matcher returns
# nothing or < MIN_LABEL_CONF; keyed by labels.normalise_ar(text). To move into om/intl/data/labels/ar.yaml (blocker
# reported to the Boss: not our file).
_AR_SUPPLEMENT = {labels.normalise_ar(k): v for k, v in {
    "العملاء والمدينون الآخرون": "ar", "العملاء والمدينون الاخرون": "ar", "العملاء والمدينون": "ar",
    "الموردون والدائنون الآخرون": "ap", "الموردون والدائنون": "ap", "الموردون وأوراق الدفع": "ap",
    "مصروفات البيع والمصروفات العمومية والإدارية": "sga", "مصروفات البيع والعمومية والإدارية": "sga",
    "متحصلات من القروض بالصافي": "x.borrowings_proceeds",
}.items()}


def _supplement(text):
    return _AR_SUPPLEMENT.get(labels.normalise_ar(text or "")) if text else None


def _match(text, stmt):
    if not text or not text.strip():
        return None
    try:
        return labels.match(text, statement=stmt if stmt in ("IS", "BS", "CF", "OCI", "EQ") else None)
    except Exception:
        return None


_FUZZ_CACHE = {}
FUZZY_MIN = 0.86
FUZZY_MARGIN = 0.04


def _fuzzy(text, lang, stmt):
    """Character-level repair of an OCR-garbled label against the dictionary (same statement preferred)."""
    import difflib
    if not text or not text.strip():
        return None
    n = labels.normalise_ar(text) if lang == "ar" else labels.normalise_label(text)
    if len(n) < 5:
        return None
    if lang not in _FUZZ_CACHE:
        _FUZZ_CACHE[lang] = labels.entries(lang=lang)
    ents = [e for e in _FUZZ_CACHE[lang] if not stmt or e.statement == stmt] or _FUZZ_CACHE[lang]
    sm = difflib.SequenceMatcher(None)
    sm.set_seq2(n)
    best = {}
    for e in ents:
        sm.set_seq1(e.norm)
        if sm.real_quick_ratio() < FUZZY_MIN - 0.1 or sm.quick_ratio() < FUZZY_MIN - 0.1:
            continue
        r = sm.ratio()
        if r > best.get(e.key, (0, None))[0]:
            best[e.key] = (r, e)
    if not best or max(r for r, _ in best.values()) < FUZZY_MIN:
        return _contain(n, lang, ents)
    ranked = sorted(best.values(), key=lambda t: -t[0])
    top = ranked[0]
    if top[0] < FUZZY_MIN or (len(ranked) > 1 and top[0] - ranked[1][0] < FUZZY_MARGIN):
        return None
    e = top[1]
    return labels.LabelMatch(e.key, round(top[0] * 0.9, 3), e.sign_hint, lang, e.is_total, e.statement, "ocr-fuzzy", n)


def _tok_sim(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _contain(n, lang, ents):
    """OCR dropped words: every remaining query word is (fuzzily) a word of the dictionary label that covers at
    least half of that label's words, and exactly one key does so best."""
    q = [t for t in n.split() if len(t) >= 3]
    if not q:
        return None
    best = {}
    for e in ents:
        et = e.norm.split()
        if len(et) < len(q) or len(et) > len(q) + 3:
            continue
        used, ok = set(), True
        for t in q:
            hit = next((i for i, x in enumerate(et) if i not in used and _tok_sim(t, x) >= 0.82), None)
            if hit is None:
                ok = False
                break
            used.add(hit)
        if ok:
            cov = len(q) / len(et)
            if cov >= 0.5 and cov > best.get(e.key, (0, None))[0]:
                best[e.key] = (cov, e)
    if not best:
        return None
    ranked = sorted(best.values(), key=lambda t: -t[0])
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.1:
        return None
    e = ranked[0][1]
    return labels.LabelMatch(e.key, round(0.72 + 0.1 * ranked[0][0], 3), e.sign_hint, lang, e.is_total, e.statement,
                             "ocr-fuzzy", n)


def resolve_label(en, ar, stmt, fuzzy=False):
    """-> (key, confidence, sign_hint, is_total, reasons)."""
    me, ma = _match(en, stmt), _match(ar, stmt)
    if fuzzy:
        if (me is None or me.confidence < MIN_LABEL_CONF) and (ma is None or ma.confidence < MIN_LABEL_CONF):
            fm = _fuzzy(ar, "ar", stmt) if ar else None
            fe = _fuzzy(en, "en", stmt) if en and not fm else None
            if fm:
                ma = fm
            elif fe:
                me = fe
    sup = _supplement(ar)
    if sup and (ma is None or ma.confidence < MIN_LABEL_CONF or ma.key != sup) and (me is None or me.confidence < MIN_LABEL_CONF):
        ma = labels.LabelMatch(sup, 0.9, 1, "ar", False, stmt or "", "supplement", "")
    reasons = []
    ms = [m for m in (me, ma) if m is not None]
    if not ms:
        return None, 0.0, 1, False, ["unmapped_label"]
    best = max(ms, key=lambda m: m.confidence)
    if len(ms) == 2 and me.key != ma.key and min(me.confidence, ma.confidence) >= MIN_LABEL_CONF:
        reasons.append(f"label-conflict:{me.key}/{ma.key}")
        conf = best.confidence * 0.7
    else:
        conf = best.confidence
        if len(ms) == 2 and me.key == ma.key:
            conf = min(1.0, conf + 0.0)
    key = best.key
    if conf < MIN_LABEL_CONF or key is None:
        return None, conf, best.sign_hint, best.is_total, ["unmapped_label"]
    if stmt == "IS" and key == "da":
        key = "x.depreciation"
    if best.method == "ocr-fuzzy":
        reasons.append("label-fuzzy")
    return key, conf, best.sign_hint, best.is_total, reasons


def _merge_wrapped(trs, stmt):
    """Join wrapped labels: a label-only line beside a number row. Returns the merged list (rows without cells that
    were absorbed are dropped)."""
    ys = [r.cy for r in trs if r.cells]
    pitch = sorted(b - a for a, b in zip(ys, ys[1:]) if b > a)
    pitch = pitch[len(pitch) // 2] if pitch else 0.02
    out = list(trs)

    def conf_of(en, ar):
        k, c, *_ = resolve_label(en, ar, stmt)
        return (c if k else 0.0)

    i = 0
    drop = set()
    while i < len(out):
        r = out[i]
        if r.cells or not (r.label_en or r.label_ar) or id(r) in drop:
            i += 1
            continue
        prev = next((p for p in reversed(out[:i]) if id(p) not in drop), None)
        nxt = out[i + 1] if i + 1 < len(out) else None
        alone = conf_of(r.label_en, r.label_ar)
        done = False
        if prev is not None and prev.cells and r.cy - prev.cy <= 1.7 * pitch and alone < 0.9:
            c0 = conf_of(prev.label_en, prev.label_ar)
            en, ar = (prev.label_en + " " + r.label_en).strip(), (prev.label_ar + " " + r.label_ar).strip()
            if conf_of(en, ar) > max(c0, alone) + 1e-9 and (c0 < 0.9 or conf_of(en, ar) > c0):
                prev.label_en, prev.label_ar = en, ar
                prev.label_bbox = _union(prev.label_bbox, r.label_bbox)
                drop.add(id(r))
                done = True
        if not done and nxt is not None and nxt.cells and nxt.cy - r.cy <= 1.7 * pitch and alone < 0.9:
            c1 = conf_of(nxt.label_en, nxt.label_ar)
            en, ar = (r.label_en + " " + nxt.label_en).strip(), (r.label_ar + " " + nxt.label_ar).strip()
            if conf_of(en, ar) > max(c1, alone) + 1e-9 and c1 < 0.9:
                nxt.label_en, nxt.label_ar = en, ar
                nxt.label_bbox = _union(nxt.label_bbox, r.label_bbox)
                drop.add(id(r))
        i += 1
    return [r for r in out if id(r) not in drop]


def _union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _clamp_bbox(bb):
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in bb)
    if x1 <= x0:
        x0, x1 = max(0.0, x0 - 5e-5), min(1.0, x1 + 5e-5)
        if x1 <= x0:
            x0, x1 = 0.0, 1e-4
    if y1 <= y0:
        y0, y1 = max(0.0, y0 - 5e-5), min(1.0, y1 + 5e-5)
        if y1 <= y0:
            y0, y1 = 0.0, 1e-4
    return (x0, y0, x1, y1)


def _parse_certainty(raw):
    s = numparse.normalise_digits(raw)
    return 1.0 if re.fullmatch(r"[\(\-–—]?\s*[\d,.\s']+\s*[\)\-–—]?|[-–—]+", s.strip()) and s.count("(") == s.count(")") else 0.85


def _period_start(end: date, stmt):
    if stmt in ("BS", None):
        return None
    try:
        return date(end.year - 1, end.month, end.day) + timedelta(days=1)
    except ValueError:
        return end - timedelta(days=364)


# ------------------------------------------------------------------------------------------------ labels by re-OCR
def _reocr_label(png, tbl, tr, ocr):
    """Re-read an unmapped row's label region with tesseract (one line, psm 7). Returns (en, ar, mean_conf) or None."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(png)).convert("L")
    except Exception:
        return None
    w, h = im.size
    ys = [c.bbox for c in tr.cells.values()]
    y0 = min(b[1] for b in ys) - 0.006
    y1 = max(b[3] for b in ys) + 0.006
    if tbl.rtl:
        nx = tbl.note_x[1] if tbl.note_x else max(x[1] for x in tbl.col_x)
        x0, x1 = nx + 0.01, 0.985
    else:
        nx = tbl.note_x[0] if tbl.note_x else min(x[0] for x in tbl.col_x)
        x0, x1 = 0.02, nx - 0.01
    if tbl.lang == "bi":
        return None
    box = (int(max(0, x0) * w), int(max(0, y0) * h), int(min(1, x1) * w), int(min(1, y1) * h))
    if box[2] - box[0] < 20 or box[3] - box[1] < 8:
        return None
    crop = im.crop(box)
    crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    try:
        ws = ocr.ocr_page_image(buf.getvalue(), langs="ara+eng" if tbl.lang == "ar" else "eng", psm=7, deskew=False)
    except Exception:
        return None
    if not ws:
        return None
    ar = [x for x in ws if tables._AR_LETTER.search(x.text)]
    en = [x for x in ws if not tables._AR_LETTER.search(x.text) and tables._LATIN.search(x.text)]
    en_t = " ".join(x.text for x in sorted(en, key=lambda x: x.bbox_norm[0]))
    ar_t = " ".join(x.text for x in sorted(ar, key=lambda x: -x.bbox_norm[0]))
    cs = [x.conf for x in ws]
    return en_t, ar_t, sum(cs) / len(cs)


# ------------------------------------------------------------------------------------------------ main
def extract(pdf, *, company=None, hints=None) -> ExtractedStatements:
    """PDF (path or bytes) -> ExtractedStatements. Appends a telemetry record (see om.intl.pipeline.write_telemetry;
    ACRETIA_TELEMETRY_PATH overrides the path, "off" disables)."""
    from .pipeline import extract_with_telemetry
    return extract_with_telemetry(pdf, company=company, hints=hints)


def _extract(pdf, *, company=None, hints=None):
    """-> (ExtractedStatements, info) with step timings for telemetry."""
    from . import ocr as ocrmod
    hints = dict(hints or {})
    t_start = time.time()
    data = _read(pdf)
    doc_id = hashlib.sha256(data).hexdigest()
    info = {"parse_s": 0.0, "ocr_s": 0.0, "extract_s": 0.0, "pages": 0, "scanned": False, "engine": "pdfplumber",
            "page_text": {}}
    with tempfile.TemporaryDirectory(prefix="acretia_ext_") as td:
        path = os.path.join(td, "in.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
        t0 = time.time()
        doc = pdfdoc.load(path, ocr=False)
        pages = {p.number: p for p in doc.pages}
        info["pages"] = len(pages)
        info["engine"] = doc.backend or "pdfplumber"
        empty = [n for n, p in pages.items() if not p.words]
        info["parse_s"] += time.time() - t0
        wp = (hints.get("pages") or {})
        if empty:
            info["scanned"] = len(empty) >= max(1, len(pages) // 2)
            t0 = time.time()
            if not ocrmod.available():
                raise ExtractError("scanned pages need tesseract (not installed)")
            want = empty
            if len(empty) > BIG_DOC_PAGES and not wp:
                low = ocrmod.ocr_pdf(path, pages=empty, dpi=110)
                keep = set()
                for p in low.pages:
                    ws = tables.prepare_words(p)
                    rows = tables.cluster_rows(ws, tables.estimate_slope(p, ws))
                    code, _, _ = tables.detect_statement(rows)
                    if code:
                        keep |= {p.number - 1, p.number, p.number + 1}
                want = sorted(n for n in keep if n in empty) or empty[:BIG_DOC_PAGES]
            elif wp:
                want = sorted({int(v) + d for v in wp.values() for d in (-1, 0, 1)} & set(empty)) or empty
            full = ocrmod.ocr_pdf(path, pages=want, dpi=OCR_FULL_DPI)
            for p in full.pages:
                pages[p.number] = p
            info["engine"] = (info["engine"] + "+tesseract")
            info["ocr_s"] += time.time() - t0
        t0 = time.time()
        # ---------------------------------------------------------------- candidates
        cands = []
        page_rows = {}
        for n in sorted(pages):
            p = pages[n]
            if not p.words:
                continue
            ws = tables.prepare_words(p)
            if not ws:
                continue
            slope = tables.estimate_slope(p, ws) if ws[0].ocr else 0.0
            rows = tables.cluster_rows(ws, slope)
            page_rows[n] = rows
            code, ti, cont = tables.detect_statement(rows)
            if wp:
                code2 = next((c for c, v in wp.items() if int(v) == n), None)
                if code2:
                    code, ti = code2, max(ti, 0)
                elif code != "NOTE":
                    code = None
            if code in ("IS", "BS", "CF", "NOTE") or (code in ("OCI", "EQ") and False):
                cands.append((n, code, ti, cont, ws, rows, slope))
        tbls = []
        fb_date = None
        if hints.get("period_end"):
            pe = hints["period_end"]
            fb_date = pe if isinstance(pe, date) else date.fromisoformat(str(pe))
        for n, code, ti, cont, ws, rows, slope in cands:
            t = tables.build_table(pages[n], code, ti, ws, rows, slope, fallback_date=fb_date)
            if t is not None:
                t.rows = _merge_wrapped(t.rows, code)
                t.score = sum(1 for r in t.rows if r.cells and resolve_label(r.label_en, r.label_ar, code, fuzzy=t.ocr)[0])
                tbls.append(t)
        chosen = []
        for code in ("IS", "BS", "CF"):
            c = [t for t in tbls if t.statement == code and t.score >= 3]
            if not c:
                continue
            best = max(c, key=lambda t: (t.score, -t.page))
            chosen.append(best)
            for t in c:       # adjacent pages of the same statement (continued / split assets-liabilities)
                if t is not best and abs(t.page - best.page) == 1 and t.score >= 3:
                    chosen.append(t)
        chosen += [t for t in tbls if t.statement == "NOTE" and t.score >= 1]
        chosen.sort(key=lambda t: t.page)
        if not any(t.statement == "IS" for t in chosen) and not any(t.statement == "BS" for t in chosen):
            raise ExtractError("no financial statements found in the PDF (period headers unreadable? pass "
                               "hints={'period_end': 'YYYY-MM-DD'})")

        # ---------------------------------------------------------------- unit, currency, language
        cur, scale = hints.get("currency"), hints.get("unit_scale")
        for t in chosen:
            if t.statement == "NOTE":
                continue
            cur = cur or t.unit[0]
            scale = scale or t.unit[1]
        warnings = []
        if not scale:
            scale = 1.0
            warnings.append("unit not printed; assumed 1")
        if not cur:
            cur = "XXX"
            warnings.append("currency not detected")
        langs = [t.lang for t in chosen]
        lang = "bi" if langs.count("bi") * 2 >= len(langs) else ("ar" if langs.count("ar") > langs.count("en") else "en")
        pngs = {}

        def png_for(n):
            if n not in pngs:
                pngs[n] = _page_png(path, n)
            return pngs[n]

        figs: list[Figure] = []
        grid = {}                       # (table idx, row idx, col) -> figure index
        restated_dates = set()
        for ti_, t in enumerate(chosen):
            stmt = t.statement
            tscale = (t.unit[1] if t.unit[1] and not hints.get("unit_scale") else None) or scale
            # sign convention of this statement
            neg = pos = 0
            resolved = []
            for tr in t.rows:
                if not tr.cells:
                    resolved.append(None)
                    continue
                key, lconf, sh, is_tot, rs = resolve_label(tr.label_en, tr.label_ar, stmt, fuzzy=t.ocr)
                if key is None and t.ocr and shutil.which("tesseract") and (png := png_for(t.page)) is not None:
                    rr = _reocr_label(png, t, tr, ocrmod)
                    if rr:
                        k2, c2, sh2, tot2, rs2 = resolve_label(rr[0], rr[1], stmt, fuzzy=True)
                        if k2:
                            key, lconf, sh, is_tot, rs = k2, c2 * 0.9, sh2, tot2, rs2 + ["label-reocr"]
                            tr.label_en, tr.label_ar = rr[0], rr[1]
                resolved.append((key, lconf, sh, is_tot, rs))
                if key and _is_expense_key(key) and stmt == "IS":
                    for c in tr.cells.values():
                        if c.parsed.kind == "number" and c.parsed.value:
                            neg += c.parsed.value < 0
                            pos += c.parsed.value > 0
            if t.ocr:
                _infer_keys(t, resolved, tscale)
            bracketed = neg >= pos
            seen = set()
            for ri, tr in enumerate(t.rows):
                if not tr.cells or resolved[ri] is None:
                    continue
                key, lconf, sh, is_tot, rs = resolved[ri]
                if stmt == "NOTE" and key not in NOTE_KEYS:
                    continue
                lab_ocr = tr.label_conf
                for col, cell in sorted(tr.cells.items()):
                    per = t.periods[col]
                    if per is None:
                        continue
                    p = cell.parsed
                    reasons = list(rs)
                    ocr_conf = cell.conf if cell.ocr else None
                    raw, bb = cell.raw, cell.bbox
                    status = "ok"
                    if cell.ocr and ocr_conf is not None and ocr_conf < REOCR_BELOW and p.kind == "number" \
                            and (png := png_for(t.page)) is not None:
                        try:
                            t2, c2, agreed = ocrmod.reocr_number(png, bb, raw, ocr_conf)
                        except Exception:
                            t2, c2, agreed = raw, ocr_conf, True
                        if agreed:
                            p2 = numparse.parse_number(t2, context="cell")
                            if p2.kind == "number" and p2.value == p.value:
                                raw, ocr_conf = t2 if c2 > ocr_conf else raw, max(ocr_conf, c2)
                        else:
                            ocr_conf = c2
                            status = "review"
                            reasons.append("ocr-disagreement")
                    printed = p.value if p.kind == "number" else 0.0
                    is_ps = key in PER_SHARE
                    sc = 1.0 if is_ps else tscale
                    val = printed * (1.0 if is_ps else sc / 1e6)
                    if key and p.kind == "number":
                        if _is_expense_key(key):
                            if printed < 0:
                                val = -val
                                reasons.append("sign:deduction")
                            elif printed > 0 and stmt == "IS" and bracketed and key in stm.LINES and neg >= 2:
                                val = -val
                                reasons.append("sign:credit")
                        elif sh == -1 and printed > 0 and not str(raw).strip().startswith("("):
                            val = -val
                            reasons.append("sign:loss-label")
                        elif sh == -1 and printed < 0:
                            reasons.append("sign:loss-label")
                    if key and (key, per) in seen:
                        reasons.append(f"duplicate-key:{key}")
                        k_use = None
                    else:
                        k_use = key
                        if key:
                            seen.add((key, per))
                    if col in t.restated:
                        reasons.append("restated")
                        restated_dates.add(per)
                    lf = lconf if key else 1.0
                    if lab_ocr is not None and key:
                        lf *= min(1.0, lab_ocr / 0.8)
                    conf = (ocr_conf if ocr_conf is not None else 1.0) * _parse_certainty(raw) * lf
                    conf = max(0.0, min(1.0, conf))
                    bbn = _clamp_bbox(bb)
                    figs.append(Figure(
                        key=k_use, label=tr.label or "", value=val, raw=raw, scale=sc, period_end=per,
                        period_start=_period_start(per, stmt), statement=stmt, page=t.page, bbox_norm=bbn,
                        label_bbox=_clamp_bbox(tr.label_bbox) if tr.label_bbox else None, confidence=conf,
                        ocr_conf=ocr_conf, source="ocr" if cell.ocr else "native", doc_id=doc_id,
                        sha256_span_hash=pdfdoc.span_hash(t.page, raw, bbn), status=status, reasons=reasons, row=ri,
                        is_total=bool(is_tot)))
                    grid[(ti_, ri, col)] = len(figs) - 1
            if stmt == "BS":
                _components(figs, grid, ti_, t, tscale)
        # derived EBIT
        _derive_ebit(figs, doc_id, [t for t in chosen if t.statement == "IS"])
        periods = sorted({f.period_end for f in figs})
        cur_per = periods[-1] if periods else date.today()
        name = company or hints.get("company")
        if not name:
            first = next((t for t in chosen if t.statement != "NOTE"), None)
            if first is not None and page_rows.get(first.page):
                r0 = page_rows[first.page][0]
                en = " ".join(w.text for w in sorted(r0.words, key=lambda w: w.bbox[0]) if not w.is_ar and w.text != "|")
                ar = " ".join(w.text for w in sorted(r0.words, key=lambda w: -w.bbox[0]) if w.is_ar)
                name = en.strip() or ar.strip()
            name = name or "Company"
        text_all = " ".join(t.title for t in chosen)
        std = hints.get("standard") or _infer_standard(cur, figs, text_all)
        for d in sorted(restated_dates):
            warnings.append(f"restated:{d.isoformat()}")
        for t in chosen:
            warnings += [f"p.{t.page}: {w}" for w in t.warnings]
        ex = ExtractedStatements(doc_id=doc_id, company=name, currency=cur, unit_scale=float(scale), periods=periods,
                                 figures=figs, standard=std, language=lang,
                                 fiscal_year_end_month=hints.get("fiscal_year_end_month") or cur_per.month,
                                 source_url=hints.get("source_url"), warnings=warnings)
        info["extract_s"] += time.time() - t0
        info["tables"] = [(t.statement, t.page, t.lang, t.rtl) for t in chosen]
        info["company_hint"] = company
    return ex, info


def _infer_standard(cur, figs, text):
    keys = {f.key for f in figs}
    if "x.zakat" in keys:
        return "SOCPA-IFRS"
    if cur == "EGP":
        return "EAS"
    return "IFRS"


def _components(figs, grid, ti_, t, tscale):
    """BS totals -> `components` (indices of the rows a total sums), found per period column from the stored values."""
    for col, per in enumerate(t.periods):
        if per is None:
            continue
        pending = []          # (row, fig index, is_total)
        for ri, tr in enumerate(t.rows):
            fi = grid.get((ti_, ri, col))
            if fi is None:
                continue
            f = figs[fi]
            if f.value is None:
                continue
            tot = f.is_total
            if not tot and pending and f.key is None:
                pass
            if tot or _sum_match(figs, pending, f, tscale, minlen=2):
                chosen = _suffix(figs, pending, f, tscale)
                if chosen is None and tot:
                    chosen = _fallback(figs, pending)
                if chosen:
                    f.components = [p[1] for p in chosen]
                    f.is_total = True
                    pending = pending[:len(pending) - len(chosen)]
                    pending.append((ri, fi, True))
                    continue
                if tot:
                    pending.append((ri, fi, True))
                    continue
            pending.append((ri, fi, False))


_CANON = {
    "current_assets": ["cash", "sti", "ar", "inventory"],
    "x.noncurrent_assets": ["ppe", "x.rou_assets", "goodwill", "intangibles"],
    "current_liabilities": ["ap", "debt_current"],
    "x.noncurrent_liabilities": ["debt_noncurrent"],
    "equity_total": ["x.share_capital", "x.retained_earnings"],
}


def _cellv(tr, col, tscale):
    c = tr.cells.get(col)
    if c is None or c.parsed.kind not in ("number", "nil"):
        return None
    return (c.parsed.value if c.parsed.kind == "number" else 0.0) * tscale / 1e6


def _infer_keys(t, resolved, tscale):
    """Last resort for OCR-garbled labels: an unmapped row whose value the statement's own arithmetic pins down
    (pretax - tax = profit, a total less its other components, closing less change in cash). Deterministic; the
    result is a low-confidence mapping (`label-inferred`) that the tie-out then corroborates or refuses."""
    stmt = t.statement
    cols = [c for c, p in enumerate(t.periods) if p is not None]
    if not cols:
        return
    keyrow = {r[0]: i for i, r in enumerate(resolved) if r and r[0]}
    unm = [i for i, r in enumerate(resolved) if r is not None and r[0] is None and t.rows[i].cells]
    if stmt == "IS":     # a lone admin/selling line that, with other income, bridges gross profit to EBIT is SG&A
        cand = [i for i, r in enumerate(resolved) if r and r[0] in ("x.admin_expenses", "x.selling_expenses")]
        if len(cand) == 1 and "sga" not in keyrow and all(k in keyrow for k in ("gross_profit", "ebit")):
            i = cand[0]
            ok = all((lambda v, a, b: None not in (v, a, b) and abs(a - abs(v) + (_cellv(t.rows[keyrow["x.other_income"]], c, tscale)
                                                                                    if "x.other_income" in keyrow else 0.0) - b) <= 3 * 0.5 * tscale / 1e6 + 1e-9)(
                _cellv(t.rows[i], c, tscale), _cellv(t.rows[keyrow["gross_profit"]], c, tscale),
                _cellv(t.rows[keyrow["ebit"]], c, tscale)) for c in cols)
            if ok:
                resolved[i] = ("sga", 0.82, 1, False, ["label-inferred"])
                keyrow["sga"] = i

    def val(key, col):
        i = keyrow.get(key)
        return None if i is None else _cellv(t.rows[i], col, tscale)

    def mark(i, key):
        resolved[i] = (key, 0.82, 1, False, ["label-inferred"])
        keyrow[key] = i

    def holds(fn):
        outs = [fn(c) for c in cols]
        return all(o is not None and o for o in outs)

    tolf = lambda n: n * 0.5 * tscale / 1e6 + 1e-9
    for i in list(unm):
        tr = t.rows[i]
        if stmt == "CF":
            trio = [k for k in ("cfo", "cfi", "cff") if k not in keyrow]
            if len(trio) == 1 and "net_change_cash" in keyrow and len(unm) >= 1:
                k = trio[0]
                others = [o for o in ("cfo", "cfi", "cff") if o != k]
                if holds(lambda c: (lambda v, nc, *os: None if None in (v, nc, *os) else
                                    abs(nc - sum(os) - (val("x.fx_effect_cash", c) or 0.0) - v) <= tolf(5))(
                        _cellv(tr, c, tscale), val("net_change_cash", c), *[val(o, c) for o in others])):
                    mark(i, k)
                    continue
        if stmt == "BS":
            for k, whole, part in (("x.noncurrent_liabilities", "liabilities", "current_liabilities"),
                                   ("x.noncurrent_assets", "assets", "current_assets")):
                if k not in keyrow and whole in keyrow and part in keyrow and \
                        holds(lambda c: (lambda v, a, b: None if None in (v, a, b) else abs(a - b - v) <= tolf(3))(
                            _cellv(tr, c, tscale), val(whole, c), val(part, c))):
                    mark(i, k)
                    break
            if resolved[i][0] is not None:
                continue
        if stmt == "IS":
            if "tax" not in keyrow and all(k in keyrow for k in ("pretax", "net_income")):
                if holds(lambda c: (lambda v, a, b: None if None in (v, a, b) else
                                    abs(a - abs(v) - (val("x.zakat", c) or 0.0) - b) <= tolf(3))(_cellv(tr, c, tscale),
                                                                                              val("pretax", c), val("net_income", c))):
                    mark(i, "tax")
                    continue
            if "sga" not in keyrow and all(k in keyrow for k in ("gross_profit", "ebit")):
                if holds(lambda c: (lambda v, a, b: None if None in (v, a, b) else
                                    abs(a - abs(v) + (val("x.other_income", c) or 0.0) - b) <= tolf(3))(_cellv(tr, c, tscale),
                                                                                                    val("gross_profit", c), val("ebit", c))):
                    mark(i, "sga")
                    continue
        elif stmt == "CF":
            if "x.cash_beginning" not in keyrow and all(k in keyrow for k in ("x.cash_end", "net_change_cash")):
                if holds(lambda c: (lambda v, a, b: None if None in (v, a, b) else abs(a - b - v) <= tolf(3))(
                        _cellv(tr, c, tscale), val("x.cash_end", c), val("net_change_cash", c))):
                    mark(i, "x.cash_beginning")
                    continue
        elif stmt == "BS":
            # the run of rows before the nearest following total
            tot_i = next((j for j in range(i + 1, len(resolved)) if resolved[j] and resolved[j][0] in _CANON), None)
            if tot_i is None:
                continue
            tkey = resolved[tot_i][0]
            start = max([j for j in range(i) if resolved[j] and resolved[j][3]] or [-1]) + 1
            run = [j for j in range(start, tot_i) if t.rows[j].cells]
            others = [j for j in run if j != i]
            if any(resolved[j] is None or resolved[j][0] is None for j in others):
                continue
            canon = _CANON[tkey]
            have = {resolved[j][0] for j in others}
            before = [resolved[j][0] for j in run if j < i and resolved[j][0] in canon]
            after = [resolved[j][0] for j in run if j > i and resolved[j][0] in canon]
            lo = max((canon.index(k) for k in before), default=-1)
            hi = min((canon.index(k) for k in after), default=len(canon))
            cands = [k for k in canon[lo + 1:hi] if k not in have]
            if len(cands) != 1:
                continue
            if holds(lambda c: (lambda v, tt: None if v is None or tt is None else
                                abs(tt - sum(_cellv(t.rows[j], c, tscale) or 0.0 for j in others) - v) <= tolf(len(run) + 1))(
                    _cellv(tr, c, tscale), _cellv(t.rows[tot_i], c, tscale))):
                mark(i, cands[0])


def _tol(n, tscale):
    return n * 0.5 * tscale / 1e6 + 1e-9


def _suffix(figs, pending, f, tscale):
    for k in range(1, len(pending) + 1):
        sub = pending[-k:]
        if abs(sum(figs[p[1]].value for p in sub) - f.value) <= _tol(k + 1, tscale):
            return sub
    return None


def _sum_match(figs, pending, f, tscale, minlen=2):
    if abs(f.value) < 1e-12:
        return False
    for k in range(minlen, len(pending) + 1):
        if abs(sum(figs[p[1]].value for p in pending[-k:]) - f.value) <= _tol(k + 1, tscale):
            return True
    return False


def _fallback(figs, pending):
    if not pending:
        return None
    last_tot = pending[-1][2]
    run = []
    for p in reversed(pending):
        if p[2] != last_tot:
            break
        run.append(p)
    return list(reversed(run)) or None


def _derive_ebit(figs, doc_id, is_tables):
    by_per = {}
    for i, f in enumerate(figs):
        if f.statement == "IS" and f.key and f.value is not None:
            by_per.setdefault(f.period_end, {}).setdefault(f.key, i)
    for per, idx in sorted(by_per.items()):
        if "ebit" in idx or "revenue" not in idx or "cogs" in idx:
            continue
        vals = {k: figs[i].value for k, i in idx.items()}
        res = adjust.by_nature_ebit(vals)
        if res["adjusted"].get("ebit") is None or "no_opex_components" in res["flags"]:
            continue
        comp_keys = res["adjusted"]["components"] + ["revenue"]
        comps = [idx[k] for k in comp_keys if k in idx]
        bbs = [figs[i].bbox_norm for i in comps]
        bb = (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))
        page = figs[idx["revenue"]].page
        raw = f"{res['adjusted']['ebit']:.6f}"
        base = figs[idx["revenue"]]
        figs.append(Figure(
            key="ebit", label="Operating profit (computed by nature)", value=res["adjusted"]["ebit"], raw=raw,
            scale=1e6, period_end=per, period_start=base.period_start, statement="IS", page=page,
            bbox_norm=_clamp_bbox(bb), label_bbox=None, confidence=min(figs[i].confidence for i in comps), ocr_conf=None,
            source="derived", doc_id=doc_id, sha256_span_hash=pdfdoc.span_hash(page, raw, _clamp_bbox(bb)),
            status="review" if any(figs[i].status == "review" for i in comps) else "ok",
            reasons=["basis:computed_by_nature"], row=None, is_total=True, components=comps))
