"""Document parser: layout blocks + exact page/bbox + completeness guard.

Layout backends (``ACRETIA_PARSER`` or ``backend=``): ``docling`` (optional,
imported lazily, converter cached per process), ``pdfdoc`` (always available),
``marker`` / ``mineru`` (isolated HTTP services, see ``om.parse_services``).
Every backend ALSO loads ``om.pdfdoc`` word geometry, so ``locate`` works the
same whatever produced the layout blocks.

Completeness guard: per page, the token recall of the raw text layer
(``pdftotext -layout``) in the backend's block text must reach the threshold
(default 0.97, env ``ACRETIA_COMPLETENESS_MIN``). Below it, lines whose
tokens the backend dropped are added as ``kind="recovered"`` blocks and a
warning records the drop; ``completeness_before_recovery`` keeps the evidence.
"""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

from om import pdfdoc
from om.pdfdoc import norm_bbox, span_hash

COMPLETENESS_MIN = 0.97
KINDS = {"heading", "text", "table", "list", "caption", "footnote", "header", "footer", "recovered", "other"}
BACKENDS = ("docling", "pdfdoc", "marker", "mineru")


@dataclass
class Block:
    kind: str
    text: str
    page: int
    bbox_norm: tuple
    sha256_span_hash: str
    source: str


@dataclass
class Locator:
    page: int
    bbox_norm: tuple
    sha256_span_hash: str
    text: str
    rects: list = field(default_factory=list)


@dataclass
class ParsedPage:
    number: int
    width: float
    height: float
    blocks: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    raw_text: str = ""
    completeness: float = 1.0
    completeness_before_recovery: float = 1.0
    threshold: float = COMPLETENESS_MIN


@dataclass
class ParsedDoc:
    doc_id: str
    backend: str
    pages: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def page(self, n):
        for p in self.pages:
            if p.number == n:
                return p
        raise KeyError(f"no page {n}")

    def text(self):
        return "\f".join("\n".join(b.text for b in p.blocks) for p in self.pages)

    def incomplete_pages(self):
        """Pages still below the completeness threshold after recovery: [(page, completeness)]."""
        return [(p.number, p.completeness) for p in self.pages if p.completeness < p.threshold]

    def to_dict(self):
        def blk(b):
            return {"kind": b.kind, "text": b.text, "page": b.page, "bbox_norm": list(b.bbox_norm),
                    "sha256_span_hash": b.sha256_span_hash, "source": b.source}

        def word(w):
            return {"text": w.text, "page": w.page, "bbox_norm": list(w.bbox_norm),
                    "sha256_span_hash": w.sha256_span_hash, "font_size": w.font_size, "ocr": w.ocr}

        def line(l):
            return {"text": l.text, "page": l.page, "bbox_norm": list(l.bbox_norm),
                    "sha256_span_hash": l.sha256_span_hash, "words": [word(w) for w in l.words]}
        return {"doc_id": self.doc_id, "backend": self.backend, "warnings": list(self.warnings),
                "pages": [{"number": p.number, "width": p.width, "height": p.height,
                           "blocks": [blk(b) for b in p.blocks], "lines": [line(l) for l in p.lines],
                           "raw_text": p.raw_text, "completeness": p.completeness,
                           "completeness_before_recovery": p.completeness_before_recovery,
                           "threshold": p.threshold}
                          for p in self.pages]}

    @classmethod
    def from_dict(cls, d):
        def word(w):
            return pdfdoc.Word(w["text"], w["page"], tuple(w["bbox_norm"]), w["sha256_span_hash"],
                               w.get("font_size"), bool(w.get("ocr")))

        def line(l):
            return pdfdoc.Line(l["text"], l["page"], tuple(l["bbox_norm"]), l["sha256_span_hash"],
                               [word(w) for w in l["words"]])
        pages = [ParsedPage(p["number"], p["width"], p["height"],
                            [Block(b["kind"], b["text"], b["page"], tuple(b["bbox_norm"]),
                                   b["sha256_span_hash"], b["source"]) for b in p["blocks"]],
                            [line(l) for l in p["lines"]], p["raw_text"], p["completeness"],
                            p["completeness_before_recovery"], p.get("threshold", COMPLETENESS_MIN))
                 for p in d["pages"]]
        return cls(d["doc_id"], d["backend"], pages, list(d.get("warnings", [])))


# ------------------------------------------------------------------ helpers
def _read(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    try:
        with open(path_or_bytes, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise pdfdoc.PdfError(f"cannot read file: {e}")


def _threshold(threshold):
    if threshold is not None:
        return float(threshold)
    try:
        return float(os.environ.get("ACRETIA_COMPLETENESS_MIN", COMPLETENESS_MIN))
    except ValueError:
        return COMPLETENESS_MIN


_ARABIC = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]")
_AR_STRIP = re.compile("[\u0640\u064b-\u065f\u0670\u06d6-\u06ed]")  # tatweel + harakat/quranic marks


_RUN = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]+|[^\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]+")


def _clean(t):
    t = unicodedata.normalize("NFKC", t)
    if _ARABIC.search(t):
        t = _AR_STRIP.sub("", t)
    return "".join(c for c in t.casefold() if unicodedata.category(c)[0] not in "PSC")


def _norm_token(t):
    """Canonical token. Arabic-script tokens compare direction-agnostically (visual vs logical order)."""
    t = _clean(t)
    if t and _ARABIC.search(t):
        t = "".join(sorted(t))
    return t


def _tokens(text, bidi=None):
    """Normalised tokens. Bidi text mixes scripts inside one whitespace token (``2300000درهم``,
    ``Marchالتاريخ``) depending on extractor, so Arabic-bearing tokens are split into script runs."""
    text = text or ""
    if bidi is None:
        bidi = bool(_ARABIC.search(text))
    out = []
    for x in text.split():
        c = _clean(x)
        if not c:
            continue
        if bidi:   # RTL page: digit runs come out reversed too in visual-order extractors
            out += ["".join(sorted(run)) for run in _RUN.findall(c)]
        else:
            out.append(c)
    return out


def completeness(parsed_text, raw_text):
    """Multiset token recall of ``raw_text`` tokens found in ``parsed_text``."""
    bidi = bool(_ARABIC.search(raw_text or "") or _ARABIC.search(parsed_text or ""))
    raw = Counter(_tokens(raw_text, bidi))
    n = sum(raw.values())
    if n == 0:
        return 1.0
    got = Counter(_tokens(parsed_text, bidi))
    return sum(min(c, got[t]) for t, c in raw.items()) / n


def raw_page_texts(path_or_bytes):
    """Per-page text layer via ``pdftotext -layout`` (subprocess); falls back to pdfdoc lines."""
    data = _read(path_or_bytes)
    if shutil.which("pdftotext"):
        with tempfile.TemporaryDirectory(prefix="acretia_raw_") as td:
            p = os.path.join(td, "in.pdf")
            with open(p, "wb") as fh:
                fh.write(data)
            try:
                r = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, timeout=120)
                if r.returncode == 0:
                    pages = r.stdout.decode("utf-8", "replace").split("\f")
                    if pages and not pages[-1].strip():
                        pages.pop()
                    return pages
            except (subprocess.TimeoutExpired, OSError):
                pass
    doc = pdfdoc.load(data, ocr=False)
    return ["\n".join(l.text for l in p.lines) for p in doc.pages]


def _block(kind, text, page, bbox, source):
    bbox = tuple(float(v) for v in bbox)
    return Block(kind if kind in KINDS else "other", text, page, bbox, span_hash(page, text, bbox), source)


# ------------------------------------------------- RTL: visual -> logical order
# pdfplumber hands back Arabic/Hebrew lines in *visual* order (words by ascending x, characters of RTL
# words reversed). Rebuild reading order from the word geometry with a minimal inverse-bidi (no new
# dependency): RTL base direction -> runs reversed, LTR runs (Latin, digits, codes) keep their order.
_RTL_CH = re.compile("[֐-׿؀-ۿݐ-ݿࢠ-ࣿיִ-﷿ﹰ-﻿]")


def _cls(ch):
    if _RTL_CH.match(ch):
        return "R"
    return "L" if ch.isalnum() else "N"


def _units(text, chars=None):
    """Glyph units: a lam-alef ligature glyph (2 chars, one glyph) and combining marks stay together."""
    raw = list(chars) if chars and "".join(chars) == text else list(text)
    out = []
    for u in raw:
        if out and unicodedata.category(u[0]) == "Mn":
            out[-1] += u
        else:
            out.append(u)
    return out


def _logical_word(text, chars=None):
    """Visual-order word text -> logical order (words without RTL letters are returned unchanged)."""
    if not _RTL_CH.search(text):
        return text
    us = _units(text, chars)
    cl = [_cls(u[0]) for u in us]
    for i, c in enumerate(cl):          # neutrals (. , - / % :) between LTR units belong to the LTR run
        if c == "N":
            a = next((cl[j] for j in range(i - 1, -1, -1) if cl[j] != "N"), None)
            b = next((cl[j] for j in range(i + 1, len(cl)) if cl[j] != "N"), None)
            cl[i] = "L" if a == "L" and b == "L" else "R"
    runs = []
    for u, c in zip(us, cl):
        if runs and runs[-1][0] == c:
            runs[-1][1].append(u)
        else:
            runs.append([c, [u]])
    return "".join("".join(r[::-1] if c == "R" else r) for c, r in reversed(runs))


def _logical_line(line, wchars=None, page_rtl=True):
    """Rebuild one visual line in reading order; lines without RTL letters are returned untouched."""
    words = line.words
    if not any(_RTL_CH.search(w.text) for w in words):
        return line
    cls = ["R" if _RTL_CH.search(w.text) else ("L" if any(c.isalnum() for c in w.text) else "N") for w in words]
    strong = [c for c in cls if c != "N"]    # edges agree -> that direction; else the page's dominant one
    base = strong[0] if strong[0] == strong[-1] else ("R" if page_rtl else "L")
    for i, c in enumerate(cls):
        if c == "N":
            a = next((cls[j] for j in range(i - 1, -1, -1) if cls[j] != "N"), None)
            b = next((cls[j] for j in range(i + 1, len(cls)) if cls[j] != "N"), None)
            cls[i] = "L" if a == "L" and b == "L" else base
    runs = []
    for w, c in zip(words, cls):
        if runs and runs[-1][0] == c:
            runs[-1][1].append(w)
        else:
            runs.append([c, [w]])
    if base == "R":
        runs.reverse()
    new = []
    for c, ws in runs:
        for w in (ws[::-1] if c == "R" else ws):
            t = _logical_word(w.text, (wchars or {}).get(id(w)))
            new.append(pdfdoc.Word(t, w.page, w.bbox_norm, span_hash(w.page, t, w.bbox_norm), w.font_size, w.ocr))
    text = " ".join(w.text for w in new)
    return pdfdoc.Line(text, line.page, line.bbox_norm, span_hash(line.page, text, line.bbox_norm), new)


def _plumber_chars(data, page_nos):
    """{page_no: [(x0, x1, top, bottom, text)]} (normalised) for ligature-aware reversal."""
    out = {}
    if pdfdoc.pdfplumber is None:
        return out
    import io
    try:
        with pdfdoc.pdfplumber.open(io.BytesIO(data)) as pdf:
            for n in page_nos:
                pp = pdf.pages[n - 1]
                W, H = float(pp.width), float(pp.height)
                out[n] = []
                for c in pp.chars:
                    b = norm_bbox(c["x0"], c["top"], c["x1"], c["bottom"], W, H)
                    out[n].append((b[0], b[2], b[1], b[3], c["text"]))
                pp.flush_cache()
    except Exception:
        return {}
    return out


def _word_chars(words, chars):
    """id(word) -> its glyph texts (a ligature stays one entry), only where they re-assemble to the word text."""
    out = {}
    for w in words:
        if not _RTL_CH.search(w.text):
            continue
        x0, y0, x1, y1 = w.bbox_norm
        cs = [(i, c) for i, c in enumerate(chars)
              if x0 - 1e-4 <= (c[0] + c[1]) / 2 <= x1 + 1e-4 and y0 - 1e-4 <= (c[2] + c[3]) / 2 <= y1 + 1e-4
              and c[4].strip()]
        cs.sort(key=lambda t: (t[1][0], t[0]))
        if "".join(c[4] for _i, c in cs) == w.text:
            out[id(w)] = [c[4] for _i, c in cs]
    return out


def _to_logical(pdf, data):
    """Convert pdfplumber's visual-order RTL lines to logical order, in place (poppler words are logical)."""
    if pdf.backend != "pdfplumber":
        return pdf
    pages = [p for p in pdf.pages if any(_RTL_CH.search(w.text) for w in p.words)]
    if not pages:
        return pdf
    chars = _plumber_chars(data, [p.number for p in pages])
    for p in pages:
        wc = _word_chars(p.words, chars.get(p.number, []))
        n_r = sum(1 for w in p.words if _RTL_CH.search(w.text))
        n_s = sum(1 for w in p.words if any(c.isalnum() for c in w.text))
        lines = [_logical_line(l, wc, 2 * n_r >= n_s) for l in p.lines]
        rep = {}
        for old, new in zip(p.lines, lines):
            if new is old:
                continue
            pool = {}
            for w in new.words:
                pool.setdefault(w.bbox_norm, []).append(w)
            for w in old.words:
                rep[id(w)] = pool[w.bbox_norm].pop(0)
        p.words = [rep.get(id(w), w) for w in p.words]
        p.lines = lines
    return pdf


# --------------------------------------------------------- pdfdoc backend
def _segments(line, gap=0.03):
    """Column segments of a line; each segment keeps the line's own (reading) word order."""
    ws = line.words
    if all(ws[i].bbox_norm[0] <= ws[i + 1].bbox_norm[0] for i in range(len(ws) - 1)):
        order = ws
    else:                                # logical (RTL) lines run right-to-left: split on x, emit in line order
        order = sorted(ws, key=lambda w: w.bbox_norm[0])
    segs, cur = [], []
    for w in order:
        if cur and w.bbox_norm[0] - cur[-1].bbox_norm[2] > gap:
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    if order is not ws:
        pos = {id(w): i for i, w in enumerate(ws)}
        segs = [sorted(sg, key=lambda w: pos[id(w)]) for sg in segs]
    return segs


def _pdfdoc_blocks(pg):
    """Group lines into paragraph blocks (same column, small vertical gap)."""
    have_sizes = any(w.font_size for w in pg.words)
    lines = pg.lines
    if not have_sizes:
        # poppler backend: no font sizes, and its flow-based lines split table cells apart.
        # Rebuild visual lines from words and use glyph box height as the size proxy.
        lines = pdfdoc._group_lines(pg.words, pg.number) or pg.lines

    def size(w):
        return w.font_size or (w.bbox_norm[3] - w.bbox_norm[1])
    sizes = sorted(size(w) for w in pg.words if size(w))
    med = sizes[len(sizes) // 2] if sizes else None
    groups, cur = [], []
    for l in lines:
        if cur:
            p = cur[-1]
            h = max(p.bbox_norm[3] - p.bbox_norm[1], 1e-6)
            if (0 <= l.bbox_norm[1] - p.bbox_norm[3] < 0.8 * h and abs(l.bbox_norm[0] - p.bbox_norm[0]) < 0.03
                    and len(_segments(l)) == len(_segments(p))):
                cur.append(l)
                continue
            groups.append(cur)
        cur = [l]
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        text = "\n".join(l.text for l in g)
        box = (min(l.bbox_norm[0] for l in g), min(l.bbox_norm[1] for l in g),
               max(l.bbox_norm[2] for l in g), max(l.bbox_norm[3] for l in g))
        if box[3] < 0.07:
            kind = "header"
        elif box[1] > 0.93:
            kind = "footer"
        elif all(len(_segments(l)) >= 3 for l in g):
            kind = "table"
        elif med and len(g) == 1 and any(size(w) > med * 1.15 for w in g[0].words):
            kind = "heading"
        elif re.match(r"\s*([-*•]|\d+[.)])\s", g[0].text):
            kind = "list"
        else:
            kind = "text"
        out.append(_block(kind, text, pg.number, box, "pdfdoc"))
    return out


# ---------------------------------------------------------- docling backend
_DL_KIND = {"title": "heading", "section_header": "heading", "text": "text", "paragraph": "text",
            "list_item": "list", "table": "table", "caption": "caption", "footnote": "footnote",
            "page_header": "header", "page_footer": "footer", "formula": "text", "code": "text"}
_CONVERTERS = {}
_LOCK = threading.Lock()


def docling_available():
    try:
        return importlib.util.find_spec("docling") is not None
    except (ImportError, ValueError):
        return False


def _converter(ocr):
    with _LOCK:
        if ocr not in _CONVERTERS:
            from docling.document_converter import DocumentConverter
            if ocr:
                _CONVERTERS[ocr] = DocumentConverter()
            else:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.document_converter import PdfFormatOption
                _CONVERTERS[ocr] = DocumentConverter(format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=PdfPipelineOptions(do_ocr=False))})
        return _CONVERTERS[ocr]


def _dl_bbox(bb, page_w, page_h):
    """Docling BoundingBox (points; BOTTOMLEFT or TOPLEFT origin) -> top-left normalised."""
    origin = str(getattr(bb.coord_origin, "name", bb.coord_origin)).upper()
    l, r = bb.l, bb.r
    if "BOTTOM" in origin:
        t, b = page_h - bb.t, page_h - bb.b
    else:
        t, b = bb.t, bb.b
    return norm_bbox(l, t, r, b, page_w, page_h)


def _dl_text(item):
    text = getattr(item, "text", "") or ""
    if not text and hasattr(item, "data") and getattr(item.data, "table_cells", None):
        text = " ".join(c.text for c in item.data.table_cells if getattr(c, "text", ""))
    return text


def _docling_blocks(dl_doc, sizes=None):
    """Convert a DoclingDocument-like object to ``{page_no: [Block]}``."""
    try:
        from docling_core.types.doc.document import ContentLayer
        layers = set(ContentLayer)
    except Exception:
        layers = None
    kw = {"included_content_layers": layers} if layers else {}
    out = {}
    for item, _lvl in dl_doc.iterate_items(**kw):
        label = str(getattr(getattr(item, "label", ""), "value", getattr(item, "label", ""))).lower()
        kind = _DL_KIND.get(label, "other")
        if label == "picture":
            continue
        text = _dl_text(item)
        for pv in getattr(item, "prov", None) or []:
            if not text.strip():
                break
            pgobj = dl_doc.pages.get(pv.page_no) if hasattr(dl_doc.pages, "get") else dl_doc.pages[pv.page_no]
            w, h = pgobj.size.width, pgobj.size.height
            out.setdefault(pv.page_no, []).append(
                _block(kind, text, pv.page_no, _dl_bbox(pv.bbox, w, h), "docling"))
    return out


def _docling_run(data, ocr):
    with tempfile.TemporaryDirectory(prefix="acretia_dl_") as td:
        p = os.path.join(td, "in.pdf")
        with open(p, "wb") as fh:
            fh.write(data)
        return _converter(ocr).convert(p).document


# --------------------------------------------------------------- recovery
def _recover(page_blocks, lines, page_no, source):
    have = Counter(_tokens(" ".join(b.text for b in page_blocks)))
    rec = []
    for l in lines:
        toks = _tokens(l.text)
        if not toks:
            continue
        need = Counter(toks)
        if all(have[t] >= c for t, c in need.items()):
            have.subtract(need)
            continue
        for t, c in need.items():
            have[t] = max(0, have[t] - c)
        rec.append(Block("recovered", l.text, page_no, tuple(l.bbox_norm), l.sha256_span_hash, source))
    return rec


def _poppler_words(data, page_no):
    """Word geometry for one page from poppler (``pdftotext -bbox-layout``, subprocess only)."""
    if not shutil.which("pdftotext"):
        return []
    with tempfile.TemporaryDirectory(prefix="acretia_bbox_") as td:
        p, out = os.path.join(td, "in.pdf"), os.path.join(td, "o.html")
        with open(p, "wb") as fh:
            fh.write(data)
        try:
            r = subprocess.run(["pdftotext", "-bbox-layout", "-f", str(page_no), "-l", str(page_no), p, out],
                               capture_output=True, timeout=120)
            if r.returncode != 0 or not os.path.exists(out):
                return []
            root = ET.parse(out).getroot()
        except (subprocess.TimeoutExpired, OSError, ET.ParseError):
            return []
    words = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "page":
            continue
        W, H = float(el.get("width")), float(el.get("height"))
        for w in el.iter():
            if w.tag.rsplit("}", 1)[-1] == "word" and (w.text or "").strip():
                box = norm_bbox(float(w.get("xMin")), float(w.get("yMin")),
                                float(w.get("xMax")), float(w.get("yMax")), W, H)
                words.append(pdfdoc._word(w.text.strip(), page_no, box))
        break
    return words


def _recover_poppler(blocks, raw, data, page_no):
    """Add poppler words whose tokens are missing from the parsed text -> (blocks, lines)."""
    btxt = " ".join(b.text for b in blocks)
    bidi = bool(_ARABIC.search(raw) or _ARABIC.search(btxt))
    missing = Counter(_tokens(raw, bidi))
    missing.subtract(Counter(_tokens(btxt, bidi)))
    missing = +missing
    if not missing:
        return [], []
    picked = []
    for w in _poppler_words(data, page_no):
        ts = _tokens(w.text, bidi)
        if ts and all(missing[t] > 0 for t in ts):
            for t in ts:
                missing[t] -= 1
            picked.append(w)
    lines = pdfdoc._group_lines(picked, page_no)
    recs = [_block("recovered", l.text, page_no, l.bbox_norm, "pdftotext") for l in lines]
    return recs, lines


# -------------------------------------------------------------------- parse
def _resolve_backend(backend):
    b = (backend or os.environ.get("ACRETIA_PARSER") or "auto").strip().lower()
    if b == "auto":
        return "docling" if docling_available() else "pdfdoc"
    if b not in BACKENDS:
        raise ValueError(f"unknown parser backend {b!r}")
    return b


def parse(path_or_bytes, backend=None, *, ocr="auto", threshold=None):
    data = _read(path_or_bytes)
    thr = _threshold(threshold)
    want_ocr = ocr not in (False, None, "off", "never", "none")
    name = _resolve_backend(backend)
    pdf = _to_logical(pdfdoc.load(data, ocr=want_ocr), data)
    raws = raw_page_texts(data)
    doc = ParsedDoc(pdf.doc_id, name, [], list(pdf.warnings))
    by_page = None
    if name == "docling":
        try:
            by_page = _docling_blocks(_docling_run(data, want_ocr))
        except Exception as e:  # never crash the grid
            doc.warnings.append(f"docling failed ({type(e).__name__}: {str(e)[:120]}); fell back to pdfdoc")
            doc.backend = name = "pdfdoc"
    elif name in ("marker", "mineru"):
        from om import parse_services
        try:
            svc = parse_services.ServiceParser.from_env(name)
            by_page = {}
            for sp in svc.parse_pages(data):
                by_page[sp["number"]] = [
                    _block(b["kind"], b["text"], sp["number"],
                           norm_bbox(*b["bbox"], sp["width"], sp["height"]), name) for b in sp["blocks"]]
        except parse_services.ServiceError as e:
            doc.warnings.append(f"{name} unavailable ({e}); fell back to pdfdoc")
            doc.backend = name = "pdfdoc"
            by_page = None
    for pg in pdf.pages:
        blocks = list(by_page.get(pg.number, [])) if by_page is not None else _pdfdoc_blocks(pg)
        raw = raws[pg.number - 1] if pg.number - 1 < len(raws) else ""
        if not raw.strip():
            raw = "\n".join(l.text for l in pg.lines)
        before = completeness(" ".join(b.text for b in blocks), raw)
        after = before
        if before < thr:
            rec = _recover(blocks, pg.lines, pg.number, name)
            blocks += rec
            after = completeness(" ".join(b.text for b in blocks), raw)
            n_pop = 0
            lines = list(pg.lines)
            if after < thr:
                prec, plines = _recover_poppler(blocks, raw, data, pg.number)
                if prec:
                    blocks += prec
                    lines = sorted(lines + plines, key=lambda l: (l.bbox_norm[1], l.bbox_norm[0]))
                    n_pop = len(prec)
                    after = completeness(" ".join(b.text for b in blocks), raw)
            doc.warnings.append(f"page {pg.number}: {name} dropped {round((1 - before) * 100, 1)}% of raw "
                                f"tokens; recovered {len(rec)} lines from the text layer"
                                + (f" and {n_pop} lines from poppler word geometry" if n_pop else ""))
            if after < thr:
                doc.warnings.append(f"page {pg.number}: INCOMPLETE after recovery "
                                    f"(completeness {after:.3f} < {thr}); text may be unreadable or scanned")
        else:
            lines = pg.lines
        doc.pages.append(ParsedPage(pg.number, pg.width, pg.height, blocks, lines, raw, after, before, thr))
    return doc


# ------------------------------------------------------------------- locate
_TRANS = str.maketrans({"\u200e": None, "\u200f": None, "\u202a": None, "\u202b": None, "\u202c": None,
                        "\u202d": None, "\u202e": None, "\u2066": None, "\u2067": None, "\u2068": None,
                        "\u2069": None, "\u061c": None, "\u0640": None,
                        "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"',
                        "”": '"', "„": '"', "‐": "-", "‑": "-", "‒": "-",
                        "–": "-", "—": "-", "―": "-", "−": "-", "­": ""})


def _nq(s):
    return unicodedata.normalize("NFKC", s).translate(_TRANS)


def _rows(page, columns):
    """Reading-order rows of words: plain lines, or column-aware segments."""
    if not columns:
        return [list(l.words) for l in page.lines]
    segs = [s for l in page.lines for s in _segments(l)]
    clusters = []
    for s in sorted(segs, key=lambda s: s[0].bbox_norm[0]):
        for c in clusters:
            if abs(c[0] - s[0].bbox_norm[0]) < 0.02:
                c[1].append(s)
                break
        else:
            clusters.append((s[0].bbox_norm[0], [s]))
    rows = []
    for _x, ss in sorted(clusters, key=lambda c: c[0]):
        rows += sorted(ss, key=lambda s: s[0].bbox_norm[1])
    return rows


def _stream(rows, mode):
    """Join rows into one string with a char->(row, word) map. mode: space|dehyph|keep."""
    chars, idx = [], []
    flat = [(ri, wi, w) for ri, r in enumerate(rows) for wi, w in enumerate(r)]
    k = 0
    while k < len(flat):
        ri, wi, w = flat[k]
        t = _nq(w.text)
        last = wi == len(rows[ri]) - 1
        nxt = flat[k + 1] if k + 1 < len(flat) else None
        if mode != "space" and last and t.endswith("-") and len(t) > 1 and nxt and nxt[0] != ri:
            t2 = _nq(nxt[2].text)
            head = t[:-1] if mode == "dehyph" else t
            for c in head:
                chars.append(c)
                idx.append((ri, wi))
            for c in t2:
                chars.append(c)
                idx.append((nxt[0], nxt[1]))
            k += 2
        else:
            for c in t:
                chars.append(c)
                idx.append((ri, wi))
            k += 1
        chars.append(" ")
        idx.append(None)
    return "".join(chars), idx


def locate(doc, page, quote):
    """Exact quote on ``page`` -> Locator from pdfdoc word geometry, else None."""
    q = " ".join(_nq(quote).split())
    if not q:
        return None
    pg = doc.page(page)
    for columns in (False, True):
        rows = _rows(pg, columns)
        for mode in ("space", "dehyph", "keep"):
            s, idx = _stream(rows, mode)
            start = 0
            while True:
                i = s.find(q, start)
                if i < 0:
                    break
                j = i + len(q)
                if (i == 0 or s[i - 1] == " ") and (j == len(s) or s[j] == " "):
                    return _make_locator(pg, rows, [x for x in idx[i:j] if x is not None])
                start = i + 1
    return None


def _make_locator(pg, rows, hits):
    seen, per_row = [], {}
    for ri, wi in hits:
        if (ri, wi) not in seen:
            seen.append((ri, wi))
            per_row.setdefault(ri, []).append(rows[ri][wi])

    def union(ws):
        return (min(w.bbox_norm[0] for w in ws), min(w.bbox_norm[1] for w in ws),
                max(w.bbox_norm[2] for w in ws), max(w.bbox_norm[3] for w in ws))
    words = [rows[ri][wi] for ri, wi in seen]
    text = " ".join(w.text for w in words)
    box = union(words)
    return Locator(pg.number, box, span_hash(pg.number, text, box), text,
                   [union(ws) for _ri, ws in sorted(per_row.items())])


def find_quote(doc, quote, pages=None):
    out = []
    for p in doc.pages:
        if pages is not None and p.number not in pages:
            continue
        loc = locate(doc, p.number, quote)
        if loc:
            out.append(loc)
    return out
