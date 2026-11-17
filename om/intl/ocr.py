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
import re
import tempfile
from PIL import ImageStat
from dataclasses import dataclass

from om.pdfdoc import PdfDoc, Page, Word, PdfError, span_hash, norm_bbox, _line, _group_lines
from om.intl.numparse import normalise_digits

TIMEOUT = 120
DIGITS_WL = "0123456789,.()-٠١٢٣٤٥٦٧٨٩٬٫"


class OcrError(Exception):
    pass


@dataclass
class OcrWord(Word):
    conf: float = 0.0          # 0..1
    dbox: tuple | None = None  # normalised box in the deskewed image (internal)


def available():
    return bool(shutil.which("tesseract"))


def _run(args, timeout=TIMEOUT):
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, shell=False,
                              env=dict(os.environ, OMP_THREAD_LIMIT="1"))
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
    """Projection-profile skew search (degrees, positive = counter-clockwise content tilt). Pillow only."""
    from PIL import Image, ImageOps
    w, h = gray.size
    f = 800.0 / max(w, h)
    small = gray.resize((max(1, int(w * f)), max(1, int(h * f)))) if f < 1 else gray
    ink = ImageOps.invert(small)
    st = ImageStat.Stat(ink)
    thr = st.mean[0] + st.stddev[0]
    im = ink.point(lambda p: 255 if p > thr else 0)
    best, ang = -1.0, 0.0
    n = int(limit / step)
    for k in range(-n, n + 1):
        t = k * step
        rot = im.rotate(t, resample=Image.BILINEAR, fillcolor=0)
        rows = list(rot.resize((1, rot.size[1]), Image.BOX).tobytes())
        mean = sum(rows) / len(rows)
        s = sum((r - mean) ** 2 for r in rows)
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
_LANGS_CACHE = {}


def installed_langs():
    """Language codes tesseract can load (cached per TESSDATA_PREFIX)."""
    key = os.environ.get("TESSDATA_PREFIX", "")
    if key not in _LANGS_CACHE:
        r = _run(["tesseract", "--list-langs"], timeout=30)
        out = (r.stdout + r.stderr).decode("utf-8", "replace").splitlines()
        _LANGS_CACHE[key] = {ln.strip() for ln in out[1:] if ln.strip() and not ln.startswith("Error")}
    return _LANGS_CACHE[key]


def check_langs(langs):
    """Raise OcrError when a requested tesseract language is missing (instead of Latin garbage)."""
    have = installed_langs()
    for lg in langs.split("+"):
        if lg and lg not in have:
            raise OcrError(f"tesseract language data '{lg}' not installed")


def _tesseract_tsv(img, langs, psm, extra=None):
    check_langs(langs)
    with tempfile.TemporaryDirectory(prefix="acretia_tess_") as td:
        src = os.path.join(td, "in.png")
        img.save(src, "PNG")
        cmd = ["tesseract", src, "-", "-l", langs, "--psm", str(psm), "--dpi", "300"] + (extra or []) + ["tsv"]
        # timeout scales with the page size (megapixels); OMP_THREAD_LIMIT=1 is set in _run
        r = _run(cmd, timeout=max(TIMEOUT, int(60 + 12 * img.size[0] * img.size[1] / 1e6)))
    if r.returncode != 0:
        raise OcrError("tesseract failed: " + r.stderr.decode("utf-8", "replace")[-200:])
    return r.stdout.decode("utf-8", "replace").splitlines()


_BIDI = dict.fromkeys([0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
                       0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF])


def _clean(t):
    return t.translate(_BIDI).strip()


def _parse_tsv(rows, w, h, ang, page):
    words, groups = [], {}
    for row in rows[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        text = _clean(c[11])
        try:
            conf = float(c[10])
            l, t, ww, hh = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        except ValueError:
            continue
        if not text or conf < 0:
            continue
        x0, y0, x1, y1 = _unrotate_box((l, t, l + ww, t + hh), ang, w, h)
        box = norm_bbox(x0, y0, x1, y1, w, h)
        ow = OcrWord(text, page, box, span_hash(page, text, box), None, True, min(1.0, max(0.0, conf / 100.0)),
                     norm_bbox(l, t, l + ww, t + hh, w, h))
        words.append(ow)
        groups.setdefault(tuple(c[2:5]), []).append(ow)
    return words, groups


# ------------------------------------------------ Eastern-digit glyph classifier
# Tesseract's Arabic model reads Eastern Arabic digits (٠-٩) as Latin lookalikes (Y, E, A, V ...).
# For numeric columns we therefore segment connected components and match them against templates
# rendered from system fonts (nearest template, with a confidence margin).
_E_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_E_GLYPHS = _E_DIGITS + "٬٫()-"
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
_BM_W, _BM_H = 16, 20
_TEMPLATES = None


def _comp_bitmap(mask_rows, x0, y0, x1, y1):
    """Fixed-size grey bitmap (list of ints) of a binary component mask."""
    from PIL import Image
    w, h = x1 - x0 + 1, y1 - y0 + 1
    buf = bytearray(w * h)
    for yy in range(h):
        row = mask_rows[yy + y0]
        for xx in range(w):
            if row[xx + x0]:
                buf[yy * w + xx] = 255
    im = Image.frombytes("L", (w, h), bytes(buf)).resize((_BM_W, _BM_H), Image.BILINEAR)
    return list(im.tobytes())


def _templates():
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    from PIL import Image, ImageDraw, ImageFont
    out = []
    for path in _FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, 120)
        except OSError:
            continue
        glyphs = {}
        for ch in _E_GLYPHS:
            im = Image.new("L", (260, 260), 0)
            ImageDraw.Draw(im).text((60, 40), ch, fill=255, font=font)
            bb = im.point(lambda p: 255 if p > 110 else 0).getbbox()
            if not bb:
                continue
            w, h = im.size
            rows = [im.crop((0, y, w, y + 1)).point(lambda p: 1 if p > 110 else 0).tobytes() for y in range(h)]
            glyphs[ch] = (bb, _comp_bitmap(rows, bb[0], bb[1], bb[2] - 1, bb[3] - 1))
        tall = [glyphs[c][0] for c in "١٢٣٤٦٧٨٩" if c in glyphs]
        if len(tall) < 6:
            continue
        hs = sorted(b[3] - b[1] for b in tall)
        ts = sorted(b[1] for b in tall)
        H, T = hs[len(hs) // 2], ts[len(ts) // 2]
        for ch, (bb, bm) in glyphs.items():
            wv, hv = bb[2] - bb[0], bb[3] - bb[1]
            out.append((ch, (wv / H, hv / H, (bb[1] - T) / H, (bb[3] - T) / H), bm))
    _TEMPLATES = out
    return out


def _components(rows, w, h):
    """8-connected components of a binary row list. Returns list of (x0,y0,x1,y1,label) and label map rows."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    labels = []
    nxt = 1
    prev_runs = []
    for y in range(h):
        row = rows[y]
        runs, x = [], 0
        while x < w:
            if row[x]:
                s = x
                while x < w and row[x]:
                    x += 1
                runs.append([s, x - 1, 0])
            else:
                x += 1
        for r_ in runs:
            lab = 0
            for pr in prev_runs:
                if pr[1] >= r_[0] - 1 and pr[0] <= r_[1] + 1:
                    if lab == 0:
                        lab = find(pr[2])
                    else:
                        parent[find(pr[2])] = lab if False else find(lab)
                        parent[find(pr[2])] = find(lab)
            if lab == 0:
                lab = nxt
                parent[lab] = lab
                nxt += 1
            r_[2] = lab
        labels.append(runs)
        prev_runs = runs
    boxes = {}
    for y, runs in enumerate(labels):
        for s, e, lab in runs:
            l = find(lab)
            b = boxes.get(l)
            if b is None:
                boxes[l] = [s, y, e, y]
            else:
                b[0], b[1], b[2], b[3] = min(b[0], s), min(b[1], y), max(b[2], e), max(b[3], y)
    # masks per component (only for those later classified): build lazily via runs
    comp_runs = {}
    for y, runs in enumerate(labels):
        for s, e, lab in runs:
            comp_runs.setdefault(find(lab), []).append((y, s, e))
    return boxes, comp_runs


def _split_wide(mask, a, b, c, d, H):
    """Split a component that is wider than one digit (touching glyphs) at column-ink minima."""
    w = c - a + 1
    if w <= 1.25 * H or (d - b + 1) < 0.5 * H:
        return [(a, b, c, d)]
    k = max(2, int(round(w / (0.78 * H))))
    cols = [sum(mask[y][x] for y in range(b, d + 1)) for x in range(a, c + 1)]
    cuts, piece = [], w / k
    for i in range(1, k):
        ctr = int(round(i * piece))
        lo, hi = max(1, ctr - int(0.3 * piece)), min(w - 2, ctr + int(0.3 * piece))
        cut = min(range(lo, hi + 1), key=lambda x: (cols[x], abs(x - ctr)))
        cuts.append(cut)
    out, start = [], 0
    for cut in cuts + [w]:
        xs = range(start, cut)
        ys = [y for y in range(b, d + 1) if any(mask[y][a + x] for x in xs)]
        if ys:
            out.append((a + start, ys[0], a + cut - 1, ys[-1]))
        start = cut
    return out or [(a, b, c, d)]


def _classify(feat, bm, templates):
    """Nearest template -> (char, distance, second distance)."""
    best, second = (None, 9.9), 9.9
    seen = {}
    for ch, tf, tbm in templates:
        small = feat[1] < 0.45 or tf[1] < 0.45
        df = ((feat[0] - tf[0]) ** 2 + (feat[1] - tf[1]) ** 2 + (feat[2] - tf[2]) ** 2 + (feat[3] - tf[3]) ** 2)
        if small:
            d = df * 2.0
        else:
            db = sum(abs(a - b) for a, b in zip(bm, tbm)) / (255.0 * len(bm))
            d = db + df * 0.6
        if d < seen.get(ch, 9.9):
            seen[ch] = d
    ranked = sorted(seen.items(), key=lambda kv: kv[1])
    if not ranked:
        return None, 9.9, 9.9
    best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 9.9
    return best[0], best[1], second


def read_eastern_digits(gray, box, h_ref=None):
    """Read one or more Eastern-digit tokens inside ``box`` (pixel box) of a deskewed gray image.

    Returns a list of ``(text, conf, (x0, y0, x1, y1))`` tokens (pixel boxes), left to right.
    Tokens with any component below the confidence margin get a low confidence.
    """
    templates = _templates()
    if not templates:
        return []
    from PIL import Image
    x0, y0, x1, y1 = [int(v) for v in box]
    crop = gray.crop((x0, y0, x1, y1))
    w, h = crop.size
    if w < 4 or h < 4:
        return []
    thr = _otsu(crop.histogram(), w * h)
    data = crop.tobytes()
    rows = [bytes(1 if data[y * w + x] < thr else 0 for x in range(w)) for y in range(h)]
    boxes, comp_runs = _components(rows, w, h)
    comps = []
    for lab, (a, b, c, d) in boxes.items():
        cw, ch_ = c - a + 1, d - b + 1
        if cw < 2 and ch_ < 2:
            continue                                   # speck
        comps.append((a, b, c, d, lab))
    if not comps:
        return []
    maxh = max(c[3] - c[1] + 1 for c in comps)
    ref = [c for c in comps if (c[3] - c[1] + 1) >= 0.6 * maxh and (c[2] - c[0] + 1) <= 1.3 * maxh]
    if not ref or (h_ref and maxh < 0.35 * h_ref):
        # no digit-height component: a lone dash (nil cell) is the only thing worth reading
        if h_ref and len(comps) == 1:
            a, b, c, d, lab = comps[0]
            if (c - a + 1) >= 0.3 * h_ref and (d - b + 1) <= 0.2 * h_ref and (c - a + 1) <= 1.2 * h_ref:
                return [("-", 0.8, (x0 + a, y0 + b, x0 + c + 1, y0 + d + 1))]
        return []
    hs = sorted(c[3] - c[1] + 1 for c in ref)
    ts = sorted(c[1] for c in ref)
    H = hs[len(hs) // 2]
    T = ts[len(ts) // 2]
    comps = [c for c in comps if not ((c[2] - c[0] + 1) > 2.5 * H and (c[3] - c[1] + 1) < 0.2 * H)]  # rules
    comps.sort(key=lambda c: c[0])
    # speckle filter: tiny things that are not plausible dots
    comps = [c for c in comps if (c[3] - c[1] + 1) >= 0.08 * H or (c[2] - c[0] + 1) >= 0.25 * H]
    tokens, cur = [], []
    for c in comps:
        if cur and c[0] - max(k[2] for k in cur) > 0.85 * H:
            tokens.append(cur)
            cur = []
        cur.append(c)
    if cur:
        tokens.append(cur)
    out = []
    for tok in tokens:
        text, confs = "", []
        for (a, b, c, d, lab) in tok:
            mask = [bytearray(w) for _ in range(h)]
            for (yy, s_, e_) in comp_runs[lab]:
                for xx in range(s_, e_ + 1):
                    mask[yy][xx] = 1
            for (pa, pb, pc, pd) in _split_wide(mask, a, b, c, d, H):
                cw, chh = pc - pa + 1, pd - pb + 1
                feat = (cw / H, chh / H, (pb - T) / H, (pd + 1 - T) / H)
                bm = _comp_bitmap(mask, pa, pb, pc, pd)
                ch, d1, d2 = _classify(feat, bm, templates)
                if ch is None:
                    text, confs = text + "?", confs + [0.0]
                    continue
                margin = (d2 - d1) / (d2 + 1e-6) if d2 < 9 else 1.0
                cf = max(0.0, min(0.99, 0.5 * (1 - d1 / 0.30) + 0.5 * min(1.0, margin * 2))) if d1 < 0.30 else 0.0
                text += ch
                confs.append(cf)
        bx = (x0 + min(t[0] for t in tok), y0 + min(t[1] for t in tok),
              x0 + max(t[2] for t in tok) + 1, y0 + max(t[3] for t in tok) + 1)
        out.append((text, min(confs) if confs else 0.0, bx))
    return out


_NUMLIKE = re.compile(r"^[0-9\u0660-\u0669A-Za-z(){}\[\]\\|!/:;.,'\u2019\-\u066b\u066c\u2013\u2014\u201c\u201d\"~`^]+$")
_AR_LETTER = re.compile(r"[\u0621-\u064a]")


def _digits_of(t):
    return "".join(ch for ch in normalise_digits(t) if ch.isdigit())


def _eastern_pass(img, words, ang, w, h, page, force=False):
    """Replace tesseract's reading of numeric columns by glyph-classifier tokens when the page
    uses Eastern Arabic digits. Returns the new word list, or None when nothing was changed."""
    numeric = [x for x in words if x.dbox and _NUMLIKE.match(x.text) and not _AR_LETTER.search(x.text)
               and (any(ch.isdigit() for ch in x.text) or len(x.text) >= 3)]
    if len(numeric) < 4:
        return None
    heights = sorted((x.dbox[3] - x.dbox[1]) * h for x in numeric)
    h0 = heights[len(heights) // 2]

    def pbox(x):
        return (x.dbox[0] * w - 6, x.dbox[1] * h - 4, x.dbox[2] * w + 6, x.dbox[3] * h + 4)
    if not force:
        sample = sorted(numeric, key=lambda x: -(x.dbox[2] - x.dbox[0]))[:10]
        hits = 0
        for x in sample:
            toks = read_eastern_digits(img, pbox(x))
            if toks and toks[0][1] >= 0.3 and _digits_of(toks[0][0]) != _digits_of(x.text):
                hits += 1
        if hits < 3 or hits < 0.4 * len(sample):
            return None
    # numeric column spans (deskewed pixel x ranges)
    spans = []
    for x in sorted(numeric, key=lambda x: x.dbox[0]):
        a, b = x.dbox[0] * w - 8, x.dbox[2] * w + 8
        if spans and a <= spans[-1][1] + 0.6 * h0:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    y_lo = max(0, int(min(x.dbox[1] for x in numeric) * h - 1.5 * h0))
    y_hi = min(h, int(max(x.dbox[3] for x in numeric) * h + 2.5 * h0))
    new = []
    for a, b in spans:
        a, b = max(0, int(a)), min(w, int(b))
        col = img.crop((a, y_lo, b, y_hi))
        cw, ch_ = col.size
        thr = _otsu(col.histogram(), cw * ch_)
        ink = list(col.point(lambda p: 255 if p < thr else 0).resize((1, ch_), Image_BOX()).tobytes())
        bands, y = [], 0
        gap = max(2, int(0.3 * h0))
        while y < ch_:
            if ink[y] > 1:
                s0 = y
                last = y
                while y < ch_ and (ink[y] > 1 or y - last <= gap):
                    if ink[y] > 1:
                        last = y
                    y += 1
                bands.append((s0, last + 1))
            else:
                y += 1
        for s0, e0 in bands:
            if e0 - s0 < 2:
                continue
            for text, cf, bx in read_eastern_digits(img, (a, y_lo + s0 - 2, b, y_lo + e0 + 2), h_ref=0.85 * h0):
                if cf < 0.25 or "?" in text or not any(c in _E_DIGITS or c == "-" for c in text):
                    continue
                if (bx[3] - bx[1]) < 0.45 * h0 and text != "-":
                    continue
                new.append((text, cf, bx))
    # digits outside the numeric columns (period headers, notes in running text): word by word
    def inside(x, boxes):
        return any(bx[0] <= (x.dbox[0] + x.dbox[2]) / 2 * w <= bx[2] and bx[1] <= (x.dbox[1] + x.dbox[3]) / 2 * h <= bx[3]
                   for _, _, bx in boxes)
    for x in words:
        if not x.dbox or inside(x, new) or _AR_LETTER.search(x.text) or not _NUMLIKE.match(x.text):
            continue
        if x.text.isalpha() and len(x.text) > 3:
            continue                                   # plain Latin word
        for text, cf, bx in read_eastern_digits(img, pbox(x), h_ref=0.85 * h0):
            if cf >= 0.35 and "?" not in text and sum(c in _E_DIGITS for c in text) >= 2 and (bx[3] - bx[1]) >= 0.45 * h0:
                new.append((text, cf, bx))
    if not new:
        return None
    out = [x for x in words if not (x.dbox and any(
        bx[0] <= (x.dbox[0] + x.dbox[2]) / 2 * w <= bx[2] and bx[1] <= (x.dbox[1] + x.dbox[3]) / 2 * h <= bx[3]
        for _, _, bx in new))]
    for text, cf, bx in new:
        ubox = _unrotate_box(bx, ang, w, h)
        box = norm_bbox(*ubox, w, h)
        out.append(OcrWord(text, page, box, span_hash(page, text, box), None, True, cf,
                           norm_bbox(*bx, w, h)))
    return out


def Image_BOX():
    from PIL import Image
    return Image.BOX


def ocr_page_image(png_bytes, langs="ara+eng", psm=6, page=1, deskew=True, binarise=False, sparse=True,
                   digits="auto"):
    """OCR one page raster. Returns OcrWord list; bboxes refer to the input image.

    ``digits``: ``"auto"`` detects Eastern Arabic digits (٠-٩) on Arabic pages and reads numeric
    columns with the glyph classifier (tesseract misreads them); ``"eastern"`` forces it,
    ``"western"`` disables it.

    With ``sparse`` a second sparse-text pass (psm 11) recovers numeric tokens that the
    block pass dropped (table rows are sometimes merged or skipped at psm 6).
    """
    words, _ = _ocr_image(png_bytes, langs, psm, page, deskew, binarise, sparse, digits)
    return words


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _ocr_image(png_bytes, langs, psm, page, deskew=True, binarise=False, sparse=True, digits="auto"):
    if not available():
        raise OcrError("tesseract not installed")
    from PIL import Image
    w, h = Image.open(io.BytesIO(png_bytes)).size
    img, ang = preprocess(png_bytes, deskew=deskew, binarise=binarise)
    words, groups = _parse_tsv(_tesseract_tsv(img, langs, psm), w, h, ang, page)
    if sparse and psm != 11:
        extra, _ = _parse_tsv(_tesseract_tsv(img, langs, 11), w, h, ang, page)
        added = [e for e in extra if any(ch.isdigit() for ch in e.text)
                 and not any(_iou(e.bbox_norm, x.bbox_norm) > 0.2 for x in words)]
        if added:
            words = words + added
            groups = {("g", i): ws for i, ws in enumerate(
                [l.words for l in _group_lines(words, page)])}
    if digits != "western" and "ara" in langs:
        new = _eastern_pass(img, words, ang, w, h, page, force=(digits == "eastern"))
        if new is not None:
            words = new
            groups = {("g", i): ws for i, ws in enumerate(
                [l.words for l in _group_lines(words, page)])}
    return words, groups


def ocr_pdf(path, pages=None, dpi=300, langs="ara+eng", psm=6, digits="auto"):
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
            attempts = [dpi] if dpi <= 200 else [dpi, 200]
            words = groups = None
            for k, use_dpi in enumerate(attempts):
                prefix = os.path.join(td, f"p{n}_{use_dpi}")
                r = _run(["pdftoppm", "-r", str(use_dpi), "-gray", "-png", "-f", str(n), "-l", str(n),
                          "-singlefile", path, prefix])
                png = prefix + ".png"
                if r.returncode != 0 or not os.path.exists(png):
                    doc.warnings.append(f"page {n}: rasterisation failed")
                    break
                with open(png, "rb") as fh:
                    pb = fh.read()
                from PIL import Image
                pw, ph = Image.open(io.BytesIO(pb)).size
                try:
                    words, groups = _ocr_image(pb, langs, psm, n, digits=digits)
                    break
                except OcrError as e:
                    if "timed out" in str(e) and k + 1 < len(attempts):
                        doc.warnings.append(f"page {n}: {e}; retrying at {attempts[k + 1]} dpi")
                        continue
                    raise
            if words is None:
                continue
            page = Page(n, pw * 72.0 / use_dpi, ph * 72.0 / use_dpi, words=words, ocr=bool(words))
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
def _reread(png_bytes, bbox_norm, langs, whitelist, psm=7, pad=0.004, scale=3):
    """Crop one cell and read it with tesseract (whitelist, psm). Returns (text, conf 0..1)."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(png_bytes)).convert("L")
    w, h = im.size
    x0, y0, x1, y1 = bbox_norm
    box = (max(0, int((x0 - pad) * w)), max(0, int((y0 - pad / 2) * h)),
           min(w, int((x1 + pad) * w) + 1), min(h, int((y1 + pad / 2) * h) + 1))
    crop = im.crop(box)
    crop = crop.resize((crop.size[0] * scale, crop.size[1] * scale), Image.LANCZOS)
    crop = ImageOps.expand(ImageOps.autocontrast(crop, cutoff=1), border=24, fill=255)
    extra = ["-c", "tessedit_char_whitelist=" + whitelist] if whitelist else []
    rows = _tesseract_tsv(crop, langs, psm, extra=extra)
    parts = []
    for row in rows[1:]:
        c = row.split("\t")
        if len(c) >= 12 and c[0] == "5" and _clean(c[11]):
            try:
                parts.append((_clean(c[11]), float(c[10]) / 100.0))
            except ValueError:
                pass
    if not parts:
        return "", 0.0
    return "".join(p[0] for p in parts), min(1.0, max(0.0, min(p[1] for p in parts)))


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
