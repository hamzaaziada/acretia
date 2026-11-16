"""PDF layer with coordinates: words, lines, rulings, each carrying page, a
normalised bbox and a deterministic span hash.

Coordinates: ``bbox_norm = (x0, y0, x1, y1)`` with a top-left origin, each
value clamped to [0, 1] with x0 <= x1 and y0 <= y1.

Span hash: ``sha256(f"{page}|{text}|{x0:.4f},{y0:.4f},{x1:.4f},{y1:.4f}")``
(UTF-8, hex digest: exactly 64 lowercase hex characters), computed on the
clamped bbox.

Backends (env ``ACRETIA_PDF_BACKEND=auto|pdfplumber|poppler``): pdfplumber
(optional, gives font sizes, rects and rulings), else poppler
``pdftotext -bbox-layout`` (no rulings). Pages without a text layer are OCRed
with ``pdftoppm`` + ``tesseract`` when available; OCR words are flagged.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

try:  # optional, see requirements-extras.txt
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

MAX_PAGES = 2000
MAX_BYTES = 200 * 1024 * 1024
TIMEOUT = 120


class PdfError(Exception):
    """Not a PDF, encrypted, corrupt, or over the configured limits."""


def span_hash(page, text, bbox):
    s = f"{page}|{text}|" + ",".join(f"{v:.4f}" for v in bbox)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def norm_bbox(x0, y0, x1, y1, w, h):
    """Normalise a top-left-origin point bbox into [0,1] with ordered corners."""
    def c(v, d):
        v = v / d if d else 0.0
        return min(1.0, max(0.0, v))
    a, b, cc, d = c(x0, w), c(y0, h), c(x1, w), c(y1, h)
    return (min(a, cc), min(b, d), max(a, cc), max(b, d))


@dataclass
class Span:
    text: str
    page: int
    bbox_norm: tuple
    sha256_span_hash: str


@dataclass
class Word(Span):
    font_size: float | None = None
    ocr: bool = False


@dataclass
class Line(Span):
    words: list = field(default_factory=list)


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    chars_present: bool = False
    ocr: bool = False
    rects: list = field(default_factory=list)     # bbox_norm tuples
    rulings: list = field(default_factory=list)   # bbox_norm tuples (thin lines)


@dataclass
class PdfDoc:
    doc_id: str
    pages: list
    backend: str = ""
    warnings: list = field(default_factory=list)

    def text(self):
        return "\f".join("\n".join(l.text for l in p.lines) for p in self.pages)

    def to_citations(self):
        from om.contracts import Citation
        return [Citation(doc_id=self.doc_id, sha256_span_hash=l.sha256_span_hash, page=p.number,
                         bbox_norm=tuple(l.bbox_norm), quote=l.text)
                for p in self.pages for l in p.lines]


def _word(text, page, box, size=None, ocr=False):
    return Word(text, page, box, span_hash(page, text, box), size, ocr)


def _line(words, page, key=None):
    text = " ".join(w.text for w in words)
    box = (min(w.bbox_norm[0] for w in words), min(w.bbox_norm[1] for w in words),
           max(w.bbox_norm[2] for w in words), max(w.bbox_norm[3] for w in words))
    return Line(text, page, box, span_hash(page, text, box), list(words))


def _group_lines(words, page):
    """Group words into visual lines by vertical-centre containment."""
    lines, cur, top, bot = [], [], 0.0, 0.0
    for w in sorted(words, key=lambda w: (w.bbox_norm[1], w.bbox_norm[0])):
        cy = (w.bbox_norm[1] + w.bbox_norm[3]) / 2
        if cur and top <= cy <= bot:
            cur.append(w)
            top, bot = min(top, w.bbox_norm[1]), max(bot, w.bbox_norm[3])
        else:
            if cur:
                lines.append(cur)
            cur, top, bot = [w], w.bbox_norm[1], w.bbox_norm[3]
    if cur:
        lines.append(cur)
    return [_line(sorted(ws, key=lambda w: w.bbox_norm[0]), page) for ws in lines]


def _run(args, timeout=TIMEOUT):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        raise PdfError(f"{args[0]} timed out after {timeout}s")
    except OSError as e:
        raise PdfError(f"cannot run {args[0]}: {e}")


def _validate(data, max_bytes):
    if len(data) > max_bytes:
        raise PdfError(f"file too large ({len(data)} bytes > {max_bytes})")
    if b"%PDF-" not in data[:1024]:
        raise PdfError("not a PDF (missing %PDF- header)")
    if re.search(rb"/Encrypt\s*[<\d]", data):
        raise PdfError("encrypted PDF not supported")


# ---------------------------------------------------------------- pdfplumber
def _load_plumber(path, max_pages):
    import io
    pages = []
    try:
        with open(path, "rb") as fh:
            pdf = pdfplumber.open(io.BytesIO(fh.read()))
        try:
            if len(pdf.pages) > max_pages:
                raise PdfError(f"too many pages ({len(pdf.pages)} > {max_pages})")
            for i, pp in enumerate(pdf.pages, 1):
                W, H = float(pp.width), float(pp.height)
                words = []
                for w in pp.extract_words(extra_attrs=["size"]):
                    box = norm_bbox(w["x0"], w["top"], w["x1"], w["bottom"], W, H)
                    words.append(_word(w["text"], i, box, round(float(w["size"]), 2)))
                rects, rulings = [], []
                for r in pp.rects:
                    box = norm_bbox(r["x0"], r["top"], r["x1"], r["bottom"], W, H)
                    (rulings if min(r["width"], r["height"]) < 1.5 else rects).append(box)
                for l in pp.lines:
                    rulings.append(norm_bbox(l["x0"], l["top"], l["x1"], l["bottom"], W, H))
                pg = Page(i, W, H, words, _group_lines(words, i), chars_present=len(pp.chars) > 0,
                          rects=rects, rulings=rulings)
                pages.append(pg)
                pp.flush_cache()
        finally:
            pdf.close()
    except PdfError:
        raise
    except Exception as e:
        raise PdfError(f"pdfplumber failed: {type(e).__name__}: {e}")
    return pages


# ------------------------------------------------------------------- poppler
def _tag(e):
    return e.tag.rsplit("}", 1)[-1]


def _load_poppler(path, max_pages):
    if not shutil.which("pdftotext"):
        raise PdfError("poppler pdftotext not installed")
    with tempfile.TemporaryDirectory(prefix="acretia_pdf_") as td:
        out = os.path.join(td, "o.html")
        r = _run(["pdftotext", "-bbox-layout", "-l", str(max_pages + 1), path, out])
        if r.returncode != 0 or not os.path.exists(out):
            raise PdfError("pdftotext failed: " + r.stderr.decode("utf-8", "replace").strip()[:200])
        try:
            root = ET.parse(out).getroot()
        except ET.ParseError as e:
            raise PdfError(f"cannot parse pdftotext output: {e}")
    pages = []
    for el in root.iter():
        if _tag(el) != "page":
            continue
        i = len(pages) + 1
        if i > max_pages:
            raise PdfError(f"too many pages (> {max_pages})")
        W, H = float(el.get("width")), float(el.get("height"))
        words, lines = [], []
        for ln in el.iter():
            if _tag(ln) != "line":
                continue
            lw = []
            for w in ln:
                if _tag(w) != "word" or not (w.text or "").strip():
                    continue
                box = norm_bbox(float(w.get("xMin")), float(w.get("yMin")),
                                float(w.get("xMax")), float(w.get("yMax")), W, H)
                lw.append(_word(w.text.strip(), i, box))
            if lw:
                words += lw
                lines.append(_line(lw, i))
        pages.append(Page(i, W, H, words, lines, chars_present=bool(words)))
    return pages


# ----------------------------------------------------------------------- OCR
def _png_size(b):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        raise PdfError("unexpected raster format")
    return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")


def _ocr_page(path, page):
    """OCR one page in place. Returns a warning string or None."""
    if not (shutil.which("tesseract") and shutil.which("pdftoppm")):
        return f"page {page.number}: no text layer and OCR tools (tesseract, pdftoppm) unavailable"
    with tempfile.TemporaryDirectory(prefix="acretia_ocr_") as td:
        prefix = os.path.join(td, "p")
        n = str(page.number)
        r = _run(["pdftoppm", "-r", "200", "-gray", "-png", "-f", n, "-l", n, "-singlefile", path, prefix])
        png = prefix + ".png"
        if r.returncode != 0 or not os.path.exists(png):
            return f"page {page.number}: rasterisation failed"
        with open(png, "rb") as fh:
            pw, ph = _png_size(fh.read(32))
        r = _run(["tesseract", png, "-", "tsv"])
        if r.returncode != 0:
            return f"page {page.number}: tesseract failed"
    groups = {}
    rows = r.stdout.decode("utf-8", "replace").splitlines()
    for row in rows[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        text = c[11].strip()
        try:
            conf = float(c[10])
            l, t, w, h = (int(c[6]), int(c[7]), int(c[8]), int(c[9]))
        except ValueError:
            continue
        if not text or conf < 0:
            continue
        box = norm_bbox(l, t, l + w, t + h, pw, ph)
        groups.setdefault(tuple(c[2:5]), []).append(_word(text, page.number, box, ocr=True))
    page.words = [w for ws in groups.values() for w in ws]
    page.lines = [_line(sorted(ws, key=lambda w: w.bbox_norm[0]), page.number) for ws in groups.values()]
    page.lines.sort(key=lambda l: (l.bbox_norm[1], l.bbox_norm[0]))
    page.ocr = bool(page.words)
    return None if page.words else f"page {page.number}: OCR found no text"


# ---------------------------------------------------------------------- load
def load(path_or_bytes, ocr="auto", max_pages=MAX_PAGES, max_bytes=MAX_BYTES):
    """Parse a PDF into a PdfDoc. Raises PdfError on bad/encrypted/corrupt input."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        try:
            if os.path.getsize(path_or_bytes) > max_bytes:
                raise PdfError(f"file too large (> {max_bytes} bytes)")
            with open(path_or_bytes, "rb") as fh:
                data = fh.read()
        except OSError as e:
            raise PdfError(f"cannot read file: {e}")
    _validate(data, max_bytes)
    choice = os.environ.get("ACRETIA_PDF_BACKEND", "auto").strip().lower() or "auto"
    if choice not in ("auto", "pdfplumber", "poppler"):
        raise PdfError(f"bad ACRETIA_PDF_BACKEND {choice!r}")
    if choice == "pdfplumber" and pdfplumber is None:
        raise PdfError("pdfplumber backend requested but not installed")
    order = {"auto": ["pdfplumber", "poppler"], "pdfplumber": ["pdfplumber"], "poppler": ["poppler"]}[choice]
    doc = PdfDoc(doc_id=hashlib.sha256(data).hexdigest(), pages=[])
    with tempfile.TemporaryDirectory(prefix="acretia_pdfsrc_") as td:
        path = os.path.join(td, "in.pdf")
        with open(path, "wb") as fh:
            fh.write(data)
        errs = []
        for name in order:
            if name == "pdfplumber" and pdfplumber is None:
                continue
            try:
                doc.pages = (_load_plumber if name == "pdfplumber" else _load_poppler)(path, max_pages)
                doc.backend = name
                break
            except PdfError as e:
                if "too many pages" in str(e):
                    raise
                errs.append(f"{name}: {e}")
        else:
            raise PdfError("cannot read PDF (" + "; ".join(errs) + ")")
        if not doc.pages:
            raise PdfError("PDF has no pages")
        if ocr:
            for p in doc.pages:
                if not p.words and not p.chars_present:
                    w = _ocr_page(path, p)
                    if w:
                        doc.warnings.append(w)
    return doc
