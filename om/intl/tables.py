"""Table reconstruction from positioned words (S8.3b).

Input: the words of one `om.pdfdoc.Page` (native text layer or `om.intl.ocr` OCR). Output: a `Table` of rows with
label text (English and Arabic kept apart), numeric cells assigned to value columns, a note-reference column,
period dates per column, and the printed unit.

The steps (all deterministic, no model):
  1. words -> display-correct words (native Arabic comes out of pdfplumber as visual-order presentation forms; they
     are reversed and NFKC-normalised into logical order),
  2. rows by y (OCR pages are de-skewed first: the slope is fitted from tesseract's own line grouping),
  3. statement title -> "IS" | "BS" | "CF" | "OCI" | "EQ" | "NOTE",
  4. numeric columns by x-alignment (right edge) of number tokens; a narrow column of small integers at an extreme
     is the note-reference column,
  5. period dates per column from the header words, falling back to the title date and the page direction,
  6. unit line via `numparse.detect_unit`.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from statistics import median

from . import labels, numparse

_AR_RE = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_AR_LETTER = re.compile("[ء-يٱ-ۓﭐ-﷿ﹰ-﻿]")
_PRES = re.compile("[ﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile("[A-Za-z]")
_BRACKET_SWAP = str.maketrans("()[]{}<>", ")(][}{><")
_DIGITISH = re.compile(r"[\d٠-٩۰-۹]")

COL_TOL = 0.02          # right-edge clustering tolerance (fraction of page width)


def fix_word_text(text: str, visual: bool = False) -> str:
    """Native Arabic from pdfplumber is visual-order (presentation forms and isolated plain letters): reverse the word,
    then NFKC (ligatures expand in logical order). `visual` is a page-level fact: any presentation form on the page
    means every Arabic word on it is visual-order. Everything else is returned untouched."""
    if not (_PRES.search(text) or (visual and _AR_LETTER.search(text))):
        return text
    parts = re.split(r"([0-9\u0660-\u0669]+)", text)
    if len(parts) > 1:
        out = []
        for p in parts[::-1]:
            out.append(p if _DIGITISH.fullmatch(p[:1] or "x") else unicodedata.normalize("NFKC", p[::-1]).translate(_BRACKET_SWAP))
        return "".join(out)
    return unicodedata.normalize("NFKC", text[::-1]).translate(_BRACKET_SWAP)


@dataclass
class TWord:
    text: str
    bbox: tuple
    conf: float | None
    ocr: bool
    raw: str                      # text as the PDF/OCR gave it (hash input)
    cy: float = 0.0               # de-skewed vertical centre

    @property
    def xc(self):
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def is_ar(self):
        return bool(_AR_LETTER.search(self.text))


@dataclass
class Row:
    idx: int
    cy: float
    words: list

    @property
    def y0(self):
        return min(w.bbox[1] for w in self.words)

    @property
    def y1(self):
        return max(w.bbox[3] for w in self.words)

    def text(self, rtl=False):
        ws = sorted(self.words, key=lambda w: w.bbox[0], reverse=rtl)
        return " ".join(w.text for w in ws)


@dataclass
class Cell:
    raw: str
    bbox: tuple
    conf: float | None
    parsed: object
    col: int
    ocr: bool = False
    page_word_raws: list = field(default_factory=list)


@dataclass
class TRow:
    index: int
    cy: float
    label_en: str
    label_ar: str
    label_bbox: tuple | None
    label_conf: float | None
    cells: dict
    note: str | None = None
    page: int = 0

    @property
    def label(self):
        if self.label_en and self.label_ar:
            return f"{self.label_en} | {self.label_ar}"
        return self.label_en or self.label_ar


@dataclass
class Table:
    statement: str
    page: int
    rows: list
    periods: list                  # date per value column (None when unknown)
    col_x: list                    # (x0, x1) per value column
    unit: tuple                    # (currency|None, scale|None)
    rtl: bool
    lang: str                      # en | ar | bi
    warnings: list = field(default_factory=list)
    restated: set = field(default_factory=set)      # column indices
    title: str = ""
    score: int = 0
    ocr: bool = False
    note_x: tuple | None = None


# ----------------------------------------------------------------------------------------------- words and rows
def prepare_words(page) -> list:
    out = []
    conf_map = getattr(page, "_word_conf", None) or {}
    visual = (not getattr(page, "ocr", False)) and any(_PRES.search(w.text or "") for w in page.words)
    for w in page.words:
        t = fix_word_text((w.text or "").strip(), visual and not getattr(w, "ocr", False))
        if not t:
            continue
        if getattr(w, "ocr", False) and _DIGITISH.search(t) and (t.startswith(")") or t.endswith("(")) \
                and not _AR_LETTER.search(t):
            t = t.translate(_BRACKET_SWAP)          # bidi-mirrored brackets from OCR: ')1,234(' -> '(1,234)'
        c = getattr(w, "conf", None)
        if c is None and w.sha256_span_hash in conf_map:
            c = conf_map[w.sha256_span_hash]
        out.append(TWord(t, tuple(w.bbox_norm), c if getattr(w, "ocr", False) or c is not None else None,
                         bool(getattr(w, "ocr", False)), w.text))
    return out


def estimate_slope(page, words) -> float:
    """Slope (dy/dx in normalised units) of text lines on an OCR page, from tesseract's own line grouping."""
    slopes = []
    for ln in getattr(page, "lines", []):
        ws = [w for w in ln.words if (w.bbox_norm[2] - w.bbox_norm[0]) > 0]
        if len(ws) < 4:
            continue
        xs = [(w.bbox_norm[0] + w.bbox_norm[2]) / 2 for w in ws]
        ys = [(w.bbox_norm[1] + w.bbox_norm[3]) / 2 for w in ws]
        if max(xs) - min(xs) < 0.3:
            continue
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den > 0:
            slopes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)
    if len(slopes) < 3:
        return 0.0
    s = median(slopes)
    return s if abs(s) < 0.05 else 0.0


def cluster_rows(words, slope=0.0) -> list:
    if not words:
        return []
    hs = [w.bbox[3] - w.bbox[1] for w in words]
    tol = 0.6 * median(hs)
    for w in words:
        w.cy = (w.bbox[1] + w.bbox[3]) / 2 - slope * (w.xc - 0.5)
    # numbers have the most reliable vertical extent: anchor rows on them, then attach the rest
    rows = []
    for w in sorted(words, key=lambda w: w.cy):
        if rows and abs(w.cy - rows[-1][0]) <= tol:
            r = rows[-1]
            r[1].append(w)
            r[0] = sum(x.cy for x in r[1]) / len(r[1])
        else:
            rows.append([w.cy, [w]])
    return [Row(i, r[0], sorted(r[1], key=lambda w: w.bbox[0])) for i, r in enumerate(rows)]


# ----------------------------------------------------------------------------------------------- titles
_STMT_PATTERNS = [
    ("EQ", re.compile(r"changes in (?:shareholders |stockholders |owners )?equity|changes in (?:the )?owners|"
                      r"التغيرات في حقوق|التغير في حقوق|قايمه التغير في حقوق|حقوق الملكيه")),
    ("CF", re.compile(r"cash ?flows?|التدفقات النقديه|التدفق النقدي")),
    ("BS", re.compile(r"financial position|balance sheet|financial condition|المركز المالي|الميزانيه")),
    ("IS", re.compile(r"profit or loss|profit and loss|income statement|statements? of (?:income|operations|earnings)|"
                      r"results of operations|الارباح او الخسائر|الارباح والخسائر|قايمه الدخل(?! الشامل)|نتايج الاعمال|"
                      r"قايمه الارباح|statement of profit")),
    ("OCI", re.compile(r"comprehensive income|الدخل الشامل")),
]
_NOTE_TITLE = re.compile(r"\bnote\s*\d+|ايضاح\s*\d+|ايضاح رقم")
_CONT = re.compile(r"continued|cont\.|\(تابع\)|تابع|تتمه")


def _norm_title(text: str) -> str:
    t = text.lower() + " " + labels.normalise_ar(text)
    return re.sub(r"\s+", " ", t)


def detect_statement(rows, limit=9) -> tuple:
    """(code, title_row_index, continued) for the first title-like row in the page head, else (None, -1, False)."""
    for r in rows[:limit]:
        if _has_value_numbers(r):
            continue
        txt = " ".join([r.text(False), r.text(True)])
        t = _norm_title(txt)
        for code, rx in _STMT_PATTERNS:
            if rx.search(t):
                if code == "OCI" and re.search(r"profit or loss|income statement|الارباح او الخسائر", t):
                    code = "IS"
                return code, r.idx, bool(_CONT.search(t))
        if _NOTE_TITLE.search(t) and re.search(r"lease|ايجار", t):
            return "NOTE", r.idx, False
    return None, -1, False


_BODY = {
    "CF": [r"operating activities|الانشطه التشغيليه|التشغيل", r"investing activities|الانشطه الاستثماريه|الاستثمار",
           r"financing activities|الانشطه التمويليه|التمويل", r"cash and cash equivalents|النقديه وما في حكمها|النقديه"],
    "BS": [r"current assets|الاصول المتداوله|الموجودات المتداوله", r"current liabilities|الالتزامات المتداوله|المطلوبات المتداوله",
           r"total assets|اجمالي الاصول|اجمالي الموجودات", r"equity|حقوق الملكيه"],
    "IS": [r"revenue|sales|الايرادات|المبيعات", r"gross profit|مجمل الربح", r"net profit|net income|profit for the (?:year|period)|صافي الربح|ربح السنه",
           r"operating profit|ربح التشغيل|income tax|ضريبه الدخل"],
}


def detect_by_body(rows) -> str | None:
    """Statement type from the body labels when the title line is missing (OCR may drop it). Needs a table-like page
    (>= 6 value rows) and >= 3 distinct label families; CF is checked first (it also mentions equivalents/activities)."""
    if sum(1 for r in rows if _has_value_numbers(r)) < 6:
        return None
    texts = [(" ".join([r.text(False), r.text(True)])).lower() + " " + labels.normalise_ar(r.text(True)) for r in rows]
    best = None
    for code in ("CF", "BS", "IS"):
        hits = sum(1 for rx in _BODY[code] if any(re.search(rx, t) for t in texts))
        if hits >= 3 and (best is None or hits > best[1]):
            best = (code, hits)
    return best[0] if best else None


# ----------------------------------------------------------------------------------------------- numbers
def _num_kind(text):
    return numparse.parse_number(text)


def _is_numeric_word(w) -> bool:
    p = numparse.parse_number(w.text)
    return p.kind == "number" and bool(_DIGITISH.search(w.text))


def merge_fragments(words) -> list:
    """OCR splits '(1,234)' into '(' '1,234' ')' sometimes: glue bracket/dash fragments to the adjacent number."""
    out, i = [], 0
    ws = sorted(words, key=lambda w: w.bbox[0])
    while i < len(ws):
        w = ws[i]
        if i + 1 < len(ws):
            n = ws[i + 1]
            gap = n.bbox[0] - w.bbox[2]
            same_row = abs(n.cy - w.cy) < (w.bbox[3] - w.bbox[1]) * 0.8
            if same_row and -0.004 < gap < 0.012 and w.ocr and n.ocr:
                a, b = w.text, n.text
                glue = (a in ("(", "-", "—", "–") and _DIGITISH.search(b)) or (b in (")", "-") and _DIGITISH.search(a)) \
                    or (re.fullmatch(r"[\d,.]+", a) and re.fullmatch(r"[\d,.]+", b) and a.endswith((",", ".")) )
                if glue:
                    bb = (min(w.bbox[0], n.bbox[0]), min(w.bbox[1], n.bbox[1]), max(w.bbox[2], n.bbox[2]), max(w.bbox[3], n.bbox[3]))
                    cs = [c for c in (w.conf, n.conf) if c is not None]
                    m = TWord(a + b, bb, min(cs) if cs else None, True, a + b, (w.cy + n.cy) / 2)
                    ws[i + 1] = m
                    i += 1
                    continue
        out.append(w)
        i += 1
    return out


def _cluster_1d(vals, tol):
    vals = sorted(vals)
    groups, cur = [], [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] <= tol:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    groups.append(cur)
    return groups


# ----------------------------------------------------------------------------------------------- headers
_HEAD_WORDS = re.compile(r"^(?:note|notes|particulars|description|ايضاح|ايضاحات|البيان|بيان|ملاحظات|رقم الايضاح)$")
_RESTATED = re.compile(r"restated|re-?presented|معدله|معدل|معاد")


def _header_like(row) -> bool:
    txt = row.text(False) + " " + row.text(True)
    if numparse.parse_period_header(txt) is not None:
        return True
    cur, sc = numparse.detect_unit(txt)
    if cur or sc:
        return True
    for w in row.words:
        n = labels.normalise_ar(w.text) if w.is_ar else w.text.lower().strip(".:")
        n2 = re.sub(r"\d+$", "", n)
        if _HEAD_WORDS.match(n) or _HEAD_WORDS.match(n2):
            return True
    return False


def _has_value_numbers(row) -> bool:
    return any(_is_numeric_word(w) and (("," in w.text) or ("." in w.text) or len(re.sub(r"\D", "", w.text)) >= 5
                                         or "(" in w.text) for w in row.words)


def _add_year(d: date, k: int) -> date:
    y = d.year + k
    day = min(d.day, calendar.monthrange(y, d.month)[1])
    if d.day == calendar.monthrange(d.year, d.month)[1]:
        day = calendar.monthrange(y, d.month)[1]
    return date(y, d.month, day)


def build_table(page, code=None, title_idx=None, words=None, rows=None, slope=None, fallback_date=None) -> Table | None:
    """Reconstruct the statement table of one page. Returns None when no numeric columns are found."""
    words = words if words is not None else prepare_words(page)
    if not words:
        return None
    is_ocr = any(w.ocr for w in words)
    if slope is None:
        slope = estimate_slope(page, words) if is_ocr else 0.0
    rows = rows if rows is not None else cluster_rows(words, slope)
    if code is None:
        code, title_idx, _ = detect_statement(rows)
    if code is None:
        return None
    t0 = max(title_idx, 0)
    # header zone: title row and following header-like rows
    header_end = t0
    for r in rows[t0 + 1:t0 + 14]:
        yearish = any(numparse.parse_number(w.text, context="header").kind == "year" for w in r.words) \
            and not _has_value_numbers(r)
        if _header_like(r) or yearish:
            header_end = r.idx
            continue
        if any(_is_numeric_word(w) for w in r.words):
            break              # first data row; label-only rows before the header row are left alone
    # a header-like row after a data row (garbled multi-line headers) is not allowed to extend past the first data row
    data_rows = [r for r in rows if r.idx > header_end]
    for r in data_rows:
        r.words = merge_fragments(r.words) if is_ocr else r.words

    cand = []
    for r in data_rows:
        for w in r.words:
            if _is_numeric_word(w):
                cand.append((r.idx, w))
    nrows_num = len({i for i, _ in cand})
    if nrows_num < 2:
        return None
    clusters = _cluster_1d([w.bbox[2] for _, w in cand], COL_TOL)
    cols = []
    for g in clusters:
        members = [(i, w) for i, w in cand if g[0] - 1e-9 <= w.bbox[2] <= g[-1] + 1e-9]
        if len(members) >= max(2, int(0.25 * nrows_num)):
            cols.append(members)
    if not cols:
        return None
    cols.sort(key=lambda m: median(w.bbox[2] for _, w in m))

    def is_note_cluster(members):
        toks = [w.text for _, w in members]
        small = [t for t in toks if re.fullmatch(r"[\d٠-٩۰-۹]{1,3}", t)]
        return len(small) >= 0.8 * len(toks) and median(len(t) for t in toks) <= 2 and \
            median(w.bbox[2] - w.bbox[0] for _, w in members) < 0.04

    note_idx = None
    if len(cols) >= 2:
        ends = [0, len(cols) - 1]
        cands = [e for e in ends if is_note_cluster(cols[e])]
        if cands:
            note_idx = cands[0] if len(cands) == 1 else min(
                cands, key=lambda e: median(w.bbox[2] - w.bbox[0] for _, w in cols[e]))
    value_cols = [c for k, c in enumerate(cols) if k != note_idx]
    if not value_cols:
        return None
    note_cluster = cols[note_idx] if note_idx is not None else None
    col_x = [(min(w.bbox[0] for _, w in c), median(w.bbox[2] for _, w in c)) for c in value_cols]
    col_x1 = [x[1] for x in col_x]
    note_x1 = median(w.bbox[2] for _, w in note_cluster) if note_cluster else None

    # label side / direction
    lab_words = [w for r in data_rows for w in r.words if not _is_numeric_word(w)]
    n_ar = sum(1 for w in lab_words if w.is_ar)
    n_lat = sum(1 for w in lab_words if _LATIN.search(w.text))
    val_c = sum(col_x1) / len(col_x1)
    ar_x = [w.xc for w in lab_words if w.is_ar]
    en_x = [w.xc for w in lab_words if _LATIN.search(w.text) and not w.is_ar]
    if n_ar and n_lat and min(n_ar, n_lat) >= 0.15 * (n_ar + n_lat):
        lang = "bi"
    elif n_ar > n_lat:
        lang = "ar"
    else:
        lang = "en"
    if lang == "ar":
        rtl = (sum(ar_x) / len(ar_x) > val_c) if ar_x else True
    elif lang == "bi":
        rtl = False
    else:
        rtl = False
    # ----- rows
    trows = []
    for r in data_rows:
        cells, lab, note = {}, [], None
        for w in r.words:
            placed = False
            p = numparse.parse_number(w.text, context="cell")
            if p.kind in ("number", "nil"):
                for k, (x0, x1) in enumerate(col_x):
                    if abs(w.bbox[2] - x1) <= COL_TOL * 1.5 or (p.kind == "nil" and x0 - COL_TOL <= w.xc <= x1 + COL_TOL):
                        if p.kind == "nil" and not (abs(w.bbox[2] - x1) <= COL_TOL * 1.5 or (x0 - COL_TOL <= w.xc <= x1 + COL_TOL)):
                            continue
                        if k in cells:      # two tokens in one cell (split number): keep the wider-numeric one
                            old = cells[k]
                            if len(w.text) > len(old.raw):
                                cells[k] = Cell(w.text, w.bbox, w.conf, p, k, w.ocr, [w.raw])
                        else:
                            cells[k] = Cell(w.text, w.bbox, w.conf, p, k, w.ocr, [w.raw])
                        placed = True
                        break
                if not placed and note_x1 is not None and p.kind == "number" and abs(w.bbox[2] - note_x1) <= COL_TOL \
                        and re.fullmatch(r"[\d٠-٩۰-۹]{1,3}", w.text):
                    note = w.text
                    placed = True
            if not placed:
                if is_ocr and lang == "ar" and not w.is_ar and _LATIN.search(w.text) and (w.conf or 0.0) < 0.8:
                    continue                      # garbled Arabic read as Latin noise
                lab.append(w)
        ar_ws = [w for w in lab if w.is_ar]
        en_ws = [w for w in lab if not w.is_ar]
        # neutral tokens (dash, digits) join the script group whose x-range contains them
        en_ws = [w for w in en_ws if _LATIN.search(w.text) or _neutral_in(w, en_ws, ar_ws, "en")]
        ar_extra = [w for w in lab if not w.is_ar and not _LATIN.search(w.text) and _neutral_in(w, en_ws, ar_ws, "ar")]
        ar_ws = ar_ws + [w for w in ar_extra if w not in ar_ws]
        en_ws = [w for w in en_ws if w not in ar_extra]
        en_txt = " ".join(w.text for w in sorted(en_ws, key=lambda w: w.bbox[0]))
        ar_txt = " ".join(w.text for w in sorted(ar_ws, key=lambda w: -w.bbox[0]))
        lw = en_ws + ar_ws
        lbb = None
        if lw:
            lbb = (min(w.bbox[0] for w in lw), min(w.bbox[1] for w in lw), max(w.bbox[2] for w in lw), max(w.bbox[3] for w in lw))
        confs = [w.conf for w in lw if w.conf is not None]
        trows.append(TRow(r.idx, r.cy, en_txt.strip(), ar_txt.strip(), lbb, sum(confs) / len(confs) if confs else None,
                          cells, note, page.number))
    # ----- units / header text
    hdr_rows = rows[t0:header_end + 1]
    htxt = " ".join(r.text(False) + " " + r.text(True) for r in rows[:header_end + 1])
    unit = numparse.detect_unit(htxt)
    if unit == (None, None):
        unit = numparse.detect_unit(" ".join(r.text(False) + " " + r.text(True) for r in rows))
    title = " ".join(r.text(False) for r in rows[:header_end + 1])
    # ----- periods per column
    periods, restated = [], set()
    for k, (x0, x1) in enumerate(col_x):
        ws = [w for r in rows[:header_end + 1] for w in r.words if x0 - 0.03 <= w.xc <= x1 + 0.03 and r.idx > t0]
        ws.sort(key=lambda w: (round(w.cy, 2), w.bbox[0]))
        d = numparse.parse_period_header(" ".join(w.text for w in ws))
        if d is None:
            d = numparse.parse_period_header(" ".join(w.text for w in reversed(ws)))
        periods.append(d)
        if _RESTATED.search(" ".join(labels.normalise_ar(w.text) if w.is_ar else w.text.lower() for w in ws)):
            restated.add(k)
    warnings = []
    title_date = None
    for r in rows[:header_end + 1]:
        title_date = numparse.parse_period_header(r.text(False) + " " + r.text(True))
        if title_date:
            break
    order = list(range(len(col_x)))
    cur_first = order if not rtl else order[::-1]        # columns from "current" to older
    if any(p is None for p in periods) or len({p for p in periods}) != len(periods):
        known = [p for p in periods if p]
        base = max(known) if known else (title_date or fallback_date)
        if base is not None:
            if known and len(set(known)) == len(known):
                # fill the gaps from the known neighbours by year steps in reading order
                pass
            periods = [None] * len(col_x)
            for n, k in enumerate(cur_first):
                periods[k] = _add_year(base, -n)
            warnings.append("period headers not readable; columns assigned from the title date and page direction")
    # Group/Company style duplicates: keep the first of each date in reading order
    seen = set()
    for k in cur_first:
        p = periods[k]
        if p in seen:
            warnings.append(f"duplicate period column {k} ignored")
            periods[k] = None
        elif p is not None:
            seen.add(p)
    if periods and all(p is None for p in periods):
        return None
    score = sum(1 for tr in trows if tr.cells)
    return Table(code, page.number, trows, periods, col_x, unit, rtl, lang, warnings, restated, title, score, is_ocr,
                 (min(w.bbox[0] for _, w in note_cluster), note_x1) if note_cluster else None)


def _neutral_in(w, en_ws, ar_ws, script) -> bool:
    """A dash or digit inside a label belongs to the script group whose x-extent it sits in (else the nearest)."""
    grp = en_ws if script == "en" else ar_ws
    other = ar_ws if script == "en" else en_ws
    if not grp:
        return script == "en" and not other
    lo, hi = min(g.bbox[0] for g in grp), max(g.bbox[2] for g in grp)
    if lo - 0.01 <= w.xc <= hi + 0.01:
        return True
    if not other:
        return script == "en"
    olo, ohi = min(g.bbox[0] for g in other), max(g.bbox[2] for g in other)
    d_g = min(abs(w.xc - lo), abs(w.xc - hi))
    d_o = min(abs(w.xc - olo), abs(w.xc - ohi))
    return d_g <= d_o
