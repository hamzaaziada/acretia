"""OCR service: tesseract as an isolated subprocess (never pytesseract / tesserocr).

* ``ocr_page_image(png_bytes, langs="ara+eng", psm=6, page=1) -> list[OcrWord]``
* ``ocr_pdf(path, pages=None, dpi=300, langs="ara+eng") -> om.pdfdoc.PdfDoc``
  (words carry ``ocr=True`` and ``conf``; ``doc.word_conf`` maps span hash -> conf)
* ``reocr_number(png_bytes, bbox_norm, text, conf) -> (text, conf, agreed)``:
  crop a numeric cell, re-read it with a digit whitelist at psm 7.

All bboxes are normalised to the ORIGINAL page image (top-left origin, [0,1]),
also when deskew rotated the image before recognition.
"""
import hashlib
import io
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from om.pdfdoc import PdfDoc, Page, Word, PdfError, span_hash, norm_bbox, _line
from om.intl.numparse import normalise_digits

TIMEOUT = 120
DIGITS_WL = "0123456789,.()-٠١٢٣٤٥٦٧٨٩٬٫"


class OcrError(Exception):
    pass


@dataclass
class OcrWord(Word):
    conf: float = 0.0          # 0..1


def available():
    return bool(shutil.which("tesseract"))


def _run(args, timeout=TIMEOUT):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        raise OcrError(f"{args[0]} timed out after {timeout}s")
    except OSError as e:
        raise OcrError(f"cannot run {args[0]}: {e}")


# ----------------------------------------------------------- preprocessing
def _otsu(hist, total):
    sum_all = sum(i * h for i, h in enumerate(hist))
    wb = sb = 0
    best, thr = -1.0, 128
    for i, h in enumerate(hist):
        wb += h
        if not wb:
            continue
        wf = total - wb
        if not wf:
            break
        sb += i * h
        mb, mf = sb / wb, (sum_all - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > best:
            best, thr = v, i
    return thr


def estimate_skew(gray, limit=3.0, step=0.25):
    """Projection-profile skew search (degrees, positive = counter-clockwise content tilt)."""
    import numpy as np
    from PIL import Image
    w, h = gray.size
    f = 800.0 / max(w, h)
    small = gray.resize((max(1, int(w * f)), max(1, int(h * f)))) if f < 1 else gray
    a = 255 - np.asarray(small, dtype=np.float32)
    thr = float(a.mean() + a.std())
    im = Image.fromarray(((a > thr) * 255).astype("uint8"))
    best, ang = -1.0, 0.0
    n = int(limit / step)
    for k in range(-n, n + 1):
        t = k * step
        rot = np.asarray(im.rotate(t, resample=Image.BILINEAR, fillcolor=0), dtype=np.float32)
        s = float(np.var(rot.sum(axis=1)))
        if s > best:
            best, ang = s, t
    return ang


def preprocess(png_bytes, deskew=True, binarise=False):
    """Return (PIL gray image, angle_deg applied). Grayscale, autocontrast, optional deskew/threshold."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(png_bytes)).convert("L")
    im = ImageOps.autocontrast(im, cutoff=1)
    ang = 0.0
    if deskew:
        ang = estimate_skew(im)
        if abs(ang) >= 0.25:
            im = im.rotate(ang, resample=Image.BICUBIC, expand=False, fillcolor=255)
        else:
            ang = 0.0
    if binarise:
        thr = _otsu(im.histogram(), im.size[0] * im.size[1])
        im = im.point(lambda p: 255 if p > thr else 0)
    return im, ang


def _unrotate_box(box, ang, w, h):
    """Map a pixel box from the deskewed image back to the original image."""
    if not ang:
        return box
    x0, y0, x1, y1 = box
    cx, cy = w / 2.0, h / 2.0
    # PIL rotate(a) turns the image counter-clockwise by a; undo with a clockwise turn
    t = math.radians(ang)
    pts = []
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        dx, dy = x - cx, cy - y
        # content was rotated CCW by ang; rotate point CW to recover
        rx = dx * math.cos(t) + dy * math.sin(t)
        ry = -dx * math.sin(t) + dy * math.cos(t)
        pts.append((cx + rx, cy - ry))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------------- core
def _tesseract_tsv(img, langs, psm, extra=None):
    with tempfile.TemporaryDirectory(prefix="acretia_tess_") as td:
        src = os.path.join(td, "in.png")
        img.save(src, "PNG")
        cmd = ["tesseract", src, "-", "-l", langs, "--psm", str(psm), "--dpi", "300"] + (extra or []) + ["tsv"]
        r = _run(cmd)
    if r.returncode != 0:
        raise OcrError("tesseract failed: " + r.stderr.decode("utf-8", "replace")[-200:])
    return r.stdout.decode("utf-8", "replace").splitlines()


def _parse_tsv(rows, w, h, ang, page):
    words, groups = [], {}
    for row in rows[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        text = c[11].strip()
        try:
            conf = float(c[10])
            l, t, ww, hh = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        except ValueError:
            continue
        if not text or conf < 0:
            continue
        x0, y0, x1, y1 = _unrotate_box((l, t, l + ww, t + hh), ang, w, h)
        box = norm_bbox(x0, y0, x1, y1, w, h)
        ow = OcrWord(text, page, box, span_hash(page, text, box), None, True, min(1.0, max(0.0, conf / 100.0)))
        words.append(ow)
        groups.setdefault(tuple(c[2:5]), []).append(ow)
    return words, groups


def ocr_page_image(png_bytes, langs="ara+eng", psm=6, page=1, deskew=True, binarise=False):
    """OCR one page raster. Returns OcrWord list; bboxes refer to the input image."""
    words, _ = _ocr_image(png_bytes, langs, psm, page, deskew, binarise)
    return words


def _ocr_image(png_bytes, langs, psm, page, deskew=True, binarise=False):
    if not available():
        raise OcrError("tesseract not installed")
    from PIL import Image
    w, h = Image.open(io.BytesIO(png_bytes)).size
    img, ang = preprocess(png_bytes, deskew=deskew, binarise=binarise)
    rows = _tesseract_tsv(img, langs, psm)
    return _parse_tsv(rows, w, h, ang, page)


def ocr_pdf(path, pages=None, dpi=300, langs="ara+eng", psm=6):
    """Rasterise a PDF with pdftoppm and OCR it into a PdfDoc (Words flagged ocr=True, with .conf)."""
    if not (available() and shutil.which("pdftoppm")):
        raise OcrError("tesseract and pdftoppm are required")
    with open(path, "rb") as fh:
        data = fh.read()
    doc = PdfDoc(doc_id=hashlib.sha256(data).hexdigest(), pages=[], backend="tesseract")
    doc.word_conf = {}
    info = _run(["pdfinfo", path])
    npages = 1
    for ln in info.stdout.decode("utf-8", "replace").splitlines():
        if ln.startswith("Pages:"):
            npages = int(ln.split()[1])
    want = sorted(set(pages)) if pages else range(1, npages + 1)
    with tempfile.TemporaryDirectory(prefix="acretia_ocrpdf_") as td:
        for n in want:
            prefix = os.path.join(td, f"p{n}")
            r = _run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-f", str(n), "-l", str(n), "-singlefile", path, prefix])
            png = prefix + ".png"
            if r.returncode != 0 or not os.path.exists(png):
                doc.warnings.append(f"page {n}: rasterisation failed")
                continue
            with open(png, "rb") as fh:
                pb = fh.read()
            from PIL import Image
            pw, ph = Image.open(io.BytesIO(pb)).size
            words, groups = _ocr_image(pb, langs, psm, n)
            page = Page(n, pw * 72.0 / dpi, ph * 72.0 / dpi, words=words, ocr=bool(words))
            page.lines = [_line(sorted(ws, key=lambda w: w.bbox_norm[0]), n) for ws in groups.values()]
            page.lines.sort(key=lambda l: (l.bbox_norm[1], l.bbox_norm[0]))
            for w in words:
                doc.word_conf[w.sha256_span_hash] = w.conf
            doc.pages.append(page)
            if not words:
                doc.warnings.append(f"page {n}: OCR found no text")
    if not doc.pages:
        raise PdfError("no pages could be OCRed")
    return doc


# -------------------------------------------------- numeric cell re-OCR
def reocr_number(png_bytes, bbox_norm, text, conf, langs="ara+eng", pad=0.004, scale=3):
    """Re-read one numeric cell with a digits whitelist (psm 7).

    Returns ``(text, conf, agreed)``. When the second reading has the same digits as
    the first, the higher-confidence reading is kept and ``agreed`` is True. When they
    disagree the original text is returned with the lower confidence halved and
    ``agreed`` False, so the caller routes the figure to review.
    """
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(png_bytes)).convert("L")
    w, h = im.size
    x0, y0, x1, y1 = bbox_norm
    box = (max(0, int((x0 - pad) * w)), max(0, int((y0 - pad / 2) * h)),
           min(w, int((x1 + pad) * w) + 1), min(h, int((y1 + pad / 2) * h) + 1))
    crop = im.crop(box)
    crop = crop.resize((crop.size[0] * scale, crop.size[1] * scale), Image.LANCZOS)
    crop = ImageOps.expand(ImageOps.autocontrast(crop, cutoff=1), border=24, fill=255)
    rows = _tesseract_tsv(crop, langs, 7, extra=["-c", "tessedit_char_whitelist=" + DIGITS_WL])
    parts = []
    for row in rows[1:]:
        c = row.split("\t")
        if len(c) >= 12 and c[0] == "5" and c[11].strip():
            try:
                parts.append((c[11].strip(), float(c[10]) / 100.0))
            except ValueError:
                pass
    if not parts:
        return text, conf, False
    t2 = "".join(p[0] for p in parts)
    c2 = min(1.0, max(0.0, min(p[1] for p in parts)))
    d1 = "".join(ch for ch in normalise_digits(text) if ch.isdigit())
    d2 = "".join(ch for ch in normalise_digits(t2) if ch.isdigit())
    if d1 and d1 == d2:
        return (t2, c2, True) if c2 > conf else (text, conf, True)
    return text, min(conf, c2) * 0.5, False
