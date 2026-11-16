"""Review queue for figures the tie-out or confidence gate held back (S8.4).

`queue(ex, report, pdf=...)` lists every figure with status "review" with its reasons, page, bbox and, when the
PDF is given (path or bytes), a PNG crop of the figure's row with the number highlighted. The crop comes from
`pdftoppm -r 150` (poppler, subprocess only) and Pillow.

`to_jsonl(items, crop_dir=None)`: one JSON object per line. With `crop_dir`, each crop is written to
`<crop_dir>/<doc12>_p<page>_<n>.png` and the line carries `crop_path`; without it the line carries `crop_png_b64`
(base64). Lines without a crop carry neither key.
"""
from __future__ import annotations

import base64
import glob
import io
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

from .types import ExtractedStatements, Figure

DPI = 150
PAD_Y = 0.012          # vertical padding around the bbox, fraction of the page height
PAD_X = 0.02           # horizontal padding when not using the full row width


@dataclass
class ReviewItem:
    figure: Figure
    reasons: list
    page: int
    bbox_norm: tuple
    crop_png: bytes | None = None


def _render_page(pdf, page: int) -> "Image.Image | None":
    from PIL import Image
    with tempfile.TemporaryDirectory() as d:
        path = pdf
        if isinstance(pdf, (bytes, bytearray)):
            path = os.path.join(d, "in.pdf")
            with open(path, "wb") as fh:
                fh.write(pdf)
        out = os.path.join(d, "pg")
        try:
            subprocess.run(["pdftoppm", "-r", str(DPI), "-f", str(page), "-l", str(page), "-png", str(path), out],
                           check=True, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        files = sorted(glob.glob(out + "*.png"))
        if not files:
            return None
        with Image.open(files[0]) as im:
            return im.convert("RGB")


def crop(pdf, page: int, bbox_norm, *, full_row: bool = True) -> bytes | None:
    """PNG bytes of the figure's row on `page`, the bbox outlined in red; None if the page can't be rendered."""
    from PIL import ImageDraw
    im = _render_page(pdf, page)
    if im is None:
        return None
    w, h = im.size
    x0, y0, x1, y1 = (float(v) for v in bbox_norm)
    box = (x0 * w, y0 * h, x1 * w, y1 * h)
    d = ImageDraw.Draw(im)
    for k in range(3):
        d.rectangle((box[0] - 2 - k, box[1] - 2 - k, box[2] + 2 + k, box[3] + 2 + k), outline=(220, 30, 30))
    cx0, cx1 = (0, w) if full_row else (max(0, (x0 - PAD_X) * w), min(w, (x1 + PAD_X) * w))
    region = (int(cx0), int(max(0, (y0 - PAD_Y) * h)), int(cx1), int(min(h, (y1 + PAD_Y) * h)) + 1)
    out = io.BytesIO()
    im.crop(region).save(out, format="PNG")
    return out.getvalue()


def queue(ex: ExtractedStatements, report=None, *, pdf=None, full_row: bool = True) -> list[ReviewItem]:
    items = []
    for f in ex.figures:
        if f.status != "review":
            continue
        png = None
        if pdf is not None:
            try:
                png = crop(pdf, f.page, f.bbox_norm, full_row=full_row)
            except Exception:
                png = None
        items.append(ReviewItem(f, list(f.reasons), f.page, tuple(f.bbox_norm), png))
    items.sort(key=lambda it: (it.page, it.bbox_norm[1], it.bbox_norm[0]))
    return items


def to_jsonl(items: list[ReviewItem], crop_dir: str | None = None) -> str:
    lines = []
    for n, it in enumerate(items):
        f = it.figure
        rec = {"key": f.key, "label": f.label, "raw": f.raw, "value": f.value, "period_end": f.period_end.isoformat(),
               "statement": f.statement, "page": it.page, "bbox_norm": list(it.bbox_norm), "confidence": f.confidence,
               "reasons": it.reasons, "doc_id": f.doc_id, "sha256_span_hash": f.sha256_span_hash}
        if it.crop_png:
            if crop_dir:
                os.makedirs(crop_dir, exist_ok=True)
                path = os.path.join(crop_dir, f"{f.doc_id[:12]}_p{it.page}_{n}.png")
                with open(path, "wb") as fh:
                    fh.write(it.crop_png)
                rec["crop_path"] = path
            else:
                rec["crop_png_b64"] = base64.b64encode(it.crop_png).decode("ascii")
        lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")
