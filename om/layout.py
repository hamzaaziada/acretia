"""Slide layout JSON -> native PowerPoint. The contract between the vision model ('rebuild this image as a
slide') and the .pptx writer. Every element is editable in PowerPoint: text boxes, shapes, connectors,
native tables and native charts. Illustrations and icons can be cropped from the approved image.

Canvas: 13.333 x 7.5 inches, origin top-left. Colours are hex ('#0B1F3A'). Sizes in points.
"""
from __future__ import annotations

import io
import re
import struct
import zlib

from .pptx import Deck, Slide, emu, para, run

CANVAS_W, CANVAS_H = 13.333, 7.5

_RUN = {"type": "object", "required": ["text"], "properties": {
    "text": {"type": "string"}, "size": {"type": "number"}, "bold": {"type": "boolean"}, "italic": {"type": "boolean"},
    "color": {"type": "string"}, "underline": {"type": "boolean"}, "font": {"type": "string"}}}
_PARA = {"type": "object", "required": ["runs"], "properties": {
    "runs": {"type": "array", "items": _RUN}, "align": {"type": "string", "enum": ["l", "ctr", "r", "just"]},
    "bullet": {"type": "boolean"}, "level": {"type": "integer"}, "space_after": {"type": "number"}, "line_spacing": {"type": "number"}}}
_BOX = {"x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"}}

SCHEMA = {
    "type": "object", "required": ["elements"],
    "properties": {
        "background": {"type": "string"},
        "font": {"type": "string"},
        "elements": {"type": "array", "items": {"type": "object", "required": ["type"], "properties": {
            "type": {"type": "string", "enum": ["text", "shape", "line", "table", "chart", "image_crop", "icon", "component"]},
            "name": {"type": "string"}, "size": {"type": "number"}, "badge": {"type": "string"},
            "label": {"type": "string"}, "title": {"type": "string"}, "measure": {"type": "string"}, "unit": {"type": "string"},
            "note": {"type": "string"}, "source": {"type": "string"}, "deck": {"type": "string"}, "page": {"type": ["string", "integer"]},
            "value": {"type": "string"}, "context": {"type": "string"}, "text": {"type": "string"}, "heading": {"type": "string"},
            "positive": {"type": "boolean"}, "cols": {"type": "integer"}, "number": {"type": ["string", "integer"]},
            "steps": {"type": "array", "items": {"type": "object"}}, "items": {"type": "array", "items": {"type": "object"}},
            "target": {"type": "array", "items": {"type": "number"}}, "min": {"type": "number"}, "max": {"type": "number"},
            "before_label": {"type": "string"}, "after_label": {"type": "string"}, "highlight_column": {"type": "integer"},
            **_BOX,
            "paragraphs": {"type": "array", "items": _PARA},
            "valign": {"type": "string", "enum": ["t", "ctr", "b"]}, "inset": {"type": "number"},
            "shape": {"type": "string"}, "fill": {"type": "string"}, "line": {"type": "string"}, "line_width": {"type": "number"},
            "dash": {"type": "string"}, "rotation": {"type": "number"}, "corner": {"type": "number"}, "shadow": {"type": "boolean"},
            "x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
            "color": {"type": "string"}, "width": {"type": "number"}, "arrow_end": {"type": "boolean"}, "arrow_start": {"type": "boolean"},
            "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            "col_widths": {"type": "array", "items": {"type": "number"}}, "header_fill": {"type": "string"},
            "font_size": {"type": "number"}, "row_height": {"type": "number"}, "numeric_columns": {"type": "array", "items": {"type": "integer"}},
            "bold_rows": {"type": "array", "items": {"type": "integer"}}, "shade_rows": {"type": "array", "items": {"type": "integer"}},
            "kind": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "series": {"type": "array", "items": {"type": "object", "required": ["name", "values"], "properties": {
                "name": {"type": "string"}, "values": {"type": "array", "items": {"type": ["number", "null"]}}, "color": {"type": "string"}}}},
            "point_colors": {"type": "array", "items": {"type": ["string", "null"]}},
            "number_format": {"type": "string"}, "labels": {"type": "boolean"}, "legend": {"type": "boolean"},
            "axis": {"type": "boolean"}, "axis_min": {"type": "number"}, "axis_max": {"type": "number"}, "gap": {"type": "integer"},
            "crop": {"type": "array", "items": {"type": "number"}}, "gridlines": {"type": "boolean"},
        }}},
    },
}

GUIDE = """Layout JSON (all positions in inches on a 13.333 x 7.5 canvas, origin top-left; colours hex; font sizes in pt):
Top level: {"background": hex, "font": "Calibri|Arial|Georgia|Cambria|Garamond|Aptos|…" (deck typeface), "elements": [...]}
- {"type":"text", x,y,w,h, paragraphs:[{runs:[{text,size,bold,italic,color,font}], align:"l|ctr|r", bullet, level,
   line_spacing (percent, e.g. 110), space_after (pt)}], valign:"t|ctr|b"}
- {"type":"shape", shape:"rect|roundRect|ellipse|chevron|homePlate|rightArrow|downArrow|triangle|diamond|hexagon|pentagon|wedgeRectCallout|donut|leftBrace|rightBrace",
   x,y,w,h, fill, line, line_width, dash:"dash|dot", corner:0-0.5 (roundRect), shadow, rotation, paragraphs (text inside), valign}
- {"type":"line", x1,y1,x2,y2, color, width(pt), arrow_end, arrow_start, dash}
- {"type":"table", x,y,w, rows:[[header...],[...]], col_widths:[relative], header_fill, font_size, row_height(in),
   numeric_columns:[col idx right-aligned], bold_rows:[row idx], shade_rows:[row idx]}
- {"type":"chart", x,y,w,h, kind:"col|bar|stacked_col|stacked_bar|line|pie|doughnut|waterfall", categories:[...],
   series:[{name, values:[...], color}], point_colors:[per-category hex], number_format:'#,##0.0' or '0%' or '"$"#,##0.0"B"',
   labels, legend, axis, axis_min, axis_max, gap, gridlines}
   waterfall: one series of signed deltas; categories whose name starts with "=" are totals (e.g. "=Closing cash") drawn from zero.
- {"type":"image_crop", x,y,w,h, crop:[x0,y0,x1,y1] as fractions of the source image} — only for photos/illustrations/icons
   that can't be drawn natively; never for text, tables or charts.
Draw in z-order (backgrounds first). Use native tables and charts for data; never draw a chart out of rectangles.
Text inside cards uses inset 0.2 (the default)."""


def guide() -> str:
    """Full contract for the slides engine: primitives, components, icon names, house style."""
    from . import house
    from .icons import catalogue
    return GUIDE + "\n\n" + COMPONENT_GUIDE + "\nIcon names: " + catalogue() + "\n\n" + house.STYLE_GUIDE


FONTS = {"calibri": "Calibri", "arial": "Arial", "helvetica": "Arial", "georgia": "Georgia", "cambria": "Cambria",
         "garamond": "Garamond", "times": "Times New Roman", "times new roman": "Times New Roman", "aptos": "Aptos",
         "segoe ui": "Segoe UI", "verdana": "Verdana", "tahoma": "Tahoma", "trebuchet ms": "Trebuchet MS", "palatino": "Palatino Linotype",
         "serif": "Georgia", "sans-serif": "Calibri", "sans": "Calibri"}
_FONT = {"value": None}


def _font(name: str | None) -> str | None:
    if not name:
        return _FONT["value"]
    return FONTS.get(name.strip().lower(), name.strip()[:40])


def _p(paragraphs, default_size=12) -> list[str]:
    out = []
    for pg in paragraphs or []:
        runs = [run(r.get("text", ""), r.get("size") or default_size, bool(r.get("bold")), r.get("color") or "111827",
                    bool(r.get("italic")), font=_font(r.get("font")), underline=bool(r.get("underline"))) for r in pg.get("runs") or []]
        ls = pg.get("line_spacing")
        if ls is not None:
            ls = float(ls)
            ls = ls * 100 if ls <= 4 else ls          # 1.1 means 110%; 110 means 110%
            ls = max(80.0, min(ls, 250.0))           # never let lines collapse onto each other
        out.append(para(runs or [run("", default_size)], pg.get("align") or "l", bool(pg.get("bullet")), int(pg.get("level") or 0),
                        space_after=pg.get("space_after", 4), line=ls))
    return out


def _clamp(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = lo
    return max(lo, min(hi, v))


def _box(e):
    x = _clamp(e.get("x"), -0.5, CANVAS_W)
    y = _clamp(e.get("y"), -0.5, CANVAS_H)
    w = _clamp(e.get("w"), 0.01, CANVAS_W + 1)
    h = _clamp(e.get("h"), 0.01, CANVAS_H + 1)
    return emu(x), emu(y), emu(w), emu(h)


def crop_png(img: bytes, crop: list[float]) -> bytes | None:
    """Crop a PNG (8-bit RGB/RGBA, non-interlaced) by fractional box; stdlib only. None if unsupported."""
    try:
        w, h, rows, bpp = _decode_png(img)
    except Exception:
        return None
    x0, y0, x1, y1 = [max(0.0, min(1.0, float(c))) for c in (crop + [0, 0, 1, 1])[:4]]
    a, b, c, d = int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)
    out = [r[a * bpp:c * bpp] for r in rows[b:d]]
    return _encode_png(c - a, d - b, out, bpp)


def _decode_png(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w = 8, b"", None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", chunk)
            assert depth == 8 and ctype in (2, 6) and inter == 0
            bpp = 3 if ctype == 2 else 4
        elif typ == b"IDAT":
            idat += chunk
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            left = line[x - bpp] if x >= bpp else 0
            up = prev[x]
            ul = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + left) & 255
            elif f == 2:
                line[x] = (line[x] + up) & 255
            elif f == 3:
                line[x] = (line[x] + ((left + up) >> 1)) & 255
            elif f == 4:
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                line[x] = (line[x] + (left if pa <= pb and pa <= pc else up if pb <= pc else ul)) & 255
        rows.append(bytes(line))
        prev = line
    return w, h, rows, bpp


def _encode_png(w: int, h: int, rows: list[bytes], bpp: int) -> bytes:
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + r for r in rows)
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2 if bpp == 3 else 6, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))


def render(slide: Slide, layout: dict, source_image: bytes | None = None) -> list[str]:
    """Draw a layout onto a slide. Returns warnings (skipped or repaired elements)."""
    warn = []
    layout = expand(layout)
    _FONT["value"] = _font(layout.get("font")) if layout.get("font") else None
    if layout.get("background"):
        slide.background = layout["background"]
    for k, e in enumerate(layout.get("elements") or [], start=1):
        t = e.get("type")
        try:
            if t == "text":
                x, y, w, h = _box(e)
                slide.text(x, y, w, h, _p(e.get("paragraphs")), anchor=e.get("valign") or "t", inset=e.get("inset", 0.02),
                           fill=e.get("fill"))
            elif t == "shape":
                x, y, w, h = _box(e)
                slide.shape(x, y, w, h, e.get("shape") or "rect", e.get("fill"), e.get("line"), e.get("line_width") or 0.75,
                            _p(e.get("paragraphs")) or None, e.get("valign") or "ctr", e.get("inset", 0.2), e.get("rotation") or 0,
                            e.get("dash"), adj=e.get("corner"), shadow=bool(e.get("shadow")))
            elif t == "line":
                slide.connector(emu(_clamp(e.get("x1"), 0, CANVAS_W)), emu(_clamp(e.get("y1"), 0, CANVAS_H)),
                                emu(_clamp(e.get("x2"), 0, CANVAS_W)), emu(_clamp(e.get("y2"), 0, CANVAS_H)),
                                e.get("color") or "9CA3AF", e.get("width") or 1, bool(e.get("arrow_end")), bool(e.get("arrow_start")), e.get("dash"))
            elif t == "table":
                rows = [[str(c) for c in r] for r in e.get("rows") or [] if r]
                if len(rows) < 1:
                    continue
                n = max(len(r) for r in rows)
                rows = [r + [""] * (n - len(r)) for r in rows]
                x, y, w, _ = _box({**e, "h": 1})
                cw = e.get("col_widths") if e.get("col_widths") and len(e["col_widths"]) == n else None
                slide.table(x, y, w, rows, cw, set(e.get("numeric_columns") or []), set(e.get("bold_rows") or []),
                            row_h=e.get("row_height") or 0.32, font=e.get("font_size") or 10.5, header_fill=e.get("header_fill") or "0B1F3A",
                            shade_rows=set(e.get("shade_rows") or []))
            elif t == "chart":
                _chart(slide, e)
            elif t == "icon":
                from .icons import ICONS, find
                name = e.get("name") or ""
                if name not in ICONS:
                    alt = find(name, 1)
                    if not alt:
                        warn.append(f"element {k}: unknown icon {name!r}")
                        continue
                    warn.append(f"element {k}: icon {name!r} not in the library; used {alt[0]!r}")
                    name = alt[0]
                s_ = emu(_clamp(e.get("size") or 0.5, 0.15, 3))
                slide.icon(emu(_clamp(e.get("x"), 0, CANVAS_W)), emu(_clamp(e.get("y"), 0, CANVAS_H)), s_, name,
                           e.get("color") or ("#FFFFFF" if e.get("badge") else "#0B1F33"), e.get("badge"))
            elif t == "image_crop":
                if not source_image:
                    warn.append(f"element {k}: image_crop without a source image")
                    continue
                img = crop_png(source_image, e.get("crop") or [0, 0, 1, 1])
                if img is None:
                    warn.append(f"element {k}: source image is not a plain PNG; crop skipped")
                    continue
                x, y, w, h = _box(e)
                slide.picture(x, y, w, h, img, "Illustration")
            else:
                warn.append(f"element {k}: unknown type {t!r}")
        except Exception as ex:  # one bad element must not sink the slide
            warn.append(f"element {k} ({t}): {ex}")
    return warn


def _chart(slide: Slide, e: dict):
    x, y, w, h = _box(e)
    cats = [str(c) for c in e.get("categories") or []]
    series = [(s.get("name") or "", [None if v is None else float(v) for v in (s.get("values") or [])][:len(cats)]) for s in e.get("series") or []]
    colors = [(s.get("color") or "").lstrip("#").upper() or None for s in e.get("series") or []]
    palette = [c for c in colors if c] or None
    kind = e.get("kind") or "col"
    common = dict(number_format=e.get("number_format") or "#,##0", labels=e.get("labels", True), legend=e.get("legend", len(series) > 1),
                  gap=e.get("gap") or 60, axis_min=e.get("axis_min"), axis_max=e.get("axis_max"), value_axis=bool(e.get("axis")),
                  point_colors=e.get("point_colors"), gridlines=e.get("gridlines", False), font=_FONT["value"])
    if kind == "waterfall":
        vals = series[0][1] if series else []
        base, bars, pc, run_total = [], [], [], 0.0
        for c, v in zip(cats, vals):
            v = v or 0.0
            if c.startswith("="):
                base.append(0.0)
                bars.append(v)
                run_total = v
                pc.append("0B1F3A")
            else:
                lo = run_total if v >= 0 else run_total + v
                base.append(lo)
                bars.append(abs(v))
                run_total += v
                pc.append("15803D" if v >= 0 else "B91C1C")
        slide.chart(x, y, w, h, [c.lstrip("=") for c in cats], [("base", base), (series[0][0] if series else "Value", bars)], kind="col",
                    stacked=True, hidden_first=True, colors=palette, **{**common, "legend": False,
                                                                        "point_colors": e.get("point_colors") or pc}, label_color="FFFFFF")
        return
    stacked = kind.startswith("stacked")
    k = {"stacked_col": "col", "stacked_bar": "bar"}.get(kind, kind)
    slide.chart(x, y, w, h, cats, series, kind=k, stacked=stacked, colors=palette, **common)


def build_deck(layouts: list[dict], sources: list[bytes | None] | None = None, title: str = "Deck", brand: str = "Research") -> tuple[bytes, list[str]]:
    d = Deck(title, brand)
    warnings = []
    for i, lay in enumerate(layouts):
        s = d.blank()
        warnings += [f"slide {i + 1}: {w}" for w in render(s, lay or {}, (sources or [None] * len(layouts))[i])]
    return d.save(), warnings


def texts(layout: dict) -> str:
    """All visible text of a layout (for checking numbers against the storyboard)."""
    out = []
    for e in expand(layout).get("elements") or []:
        for pg in e.get("paragraphs") or []:
            out.append(" ".join(r.get("text", "") for r in pg.get("runs") or []))
        for r in e.get("rows") or []:
            out.append(" | ".join(str(c) for c in r))
        if e.get("type") == "chart":
            out.append(" ".join(e.get("categories") or []))
    return "\n".join(out)


def render_png(pptx_bytes: bytes, dpi: int = 80) -> list[bytes]:
    """Render slides to PNG with LibreOffice (+ pdftoppm). [] if the tools aren't installed."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    exe = shutil.which("soffice") or ("/Applications/LibreOffice.app/Contents/MacOS/soffice"
                                       if Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists() else None)
    ppm = shutil.which("pdftoppm")
    if not exe or not ppm:
        return []
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "deck.pptx"
        src.write_bytes(pptx_bytes)
        try:
            subprocess.run([exe, "--headless", "--norestore", f"-env:UserInstallation=file://{d}/profile", "--convert-to", "pdf",
                            "--outdir", d, str(src)], capture_output=True, timeout=180)
            pdf = Path(d) / "deck.pdf"
            if not pdf.exists():
                return []
            subprocess.run([ppm, "-r", str(dpi), "-png", str(pdf), str(Path(d) / "s")], capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired):
            return []
        files = sorted(Path(d).glob("s-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        return [f.read_bytes() for f in files]


# --------------------------------------------------------------------------- components: consulting devices, built from primitives
def _t(x, y, w, h, runs, align="l", valign="t", **kw):
    return {"type": "text", "x": x, "y": y, "w": w, "h": h, "valign": valign,
            "paragraphs": [{"runs": runs if isinstance(runs, list) else [runs], "align": align, **kw}]}


def _r(text, size, bold=False, color=None, font=None):
    from . import house
    return {"text": text, "size": size, "bold": bold, "color": color or house.PALETTE["text"], **({"font": font} if font else {})}


CHART_COMPONENTS = {"bridge", "dot_plot"}


def expand(layout: dict) -> dict:
    """Replace {"type": "component", "kind": …} elements with primitives laid out on the house grid."""
    out = []
    for e in layout.get("elements") or []:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "component":
            kind = e.get("kind") if isinstance(e.get("kind"), str) else None
            fn = COMPONENTS.get(kind) if kind else None
            try:
                parts = fn(e) if fn else [{"type": "bogus-component", "kind": str(e.get("kind"))}]
                if kind in CHART_COMPONENTS:
                    for part in parts:
                        part["_chart"] = kind          # chart internals: chart rules, not card and body-text rules
                out += parts
            except Exception as ex:  # a malformed component must not sink the slide
                out.append({"type": "bogus-component", "kind": f"{kind}: {ex}"})
        elif e.get("type") == "table" and e.get("highlight_column") is not None:
            out += [e] + _highlight_column(e)
        else:
            out.append(e)
    return {**layout, "elements": out}


def _highlight_column(e):
    from . import house
    rows = e.get("rows") or []
    n = max((len(r) for r in rows), default=0)
    k = int(e["highlight_column"])
    if not 0 <= k < n:
        return []
    cw = e.get("col_widths") if e.get("col_widths") and len(e["col_widths"]) == n else [1] * n
    x0 = float(e["x"]) + float(e["w"]) * sum(cw[:k]) / sum(cw)
    w = float(e["w"]) * cw[k] / sum(cw)
    h = len(rows) * float(e.get("row_height") or 0.32)
    return [{"type": "shape", "shape": "rect", "x": x0, "y": float(e["y"]), "w": w, "h": h, "line": house.PALETTE["accent"], "line_width": 2}]


def c_exhibit_frame(e):
    """The house frame: title (no eyebrow), rule under it, subtitle, note/source, footer rule, deck name and page number."""
    from . import house
    G, P, T = house.GRID, house.PALETTE, house.TYPE
    W = house.CANVAS[0] - 2 * G["margin_x"]
    x = G["margin_x"]
    out = []
    if e.get("title"):
        out.append(_t(x, G["title_y"], W, G["title_h"], _r(e["title"], T["title"], True), valign="b", line_spacing=95))
    out.append({"type": "line", "x1": x, "y1": G["title_rule_y"], "x2": x + W, "y2": G["title_rule_y"], "color": P["text"],
                "width": house.RULE_PT, "role": "title_rule"})
    if e.get("measure") or e.get("unit"):
        runs = [_r(e.get("measure", ""), 14, True)] + ([_r(", " + e["unit"], 14)] if e.get("unit") else [])
        out.append(_t(x, G["subtitle_y"], W, 0.32, runs))
    note = " ".join(t for t in (e.get("note"), ("Source: " + e["source"]) if e.get("source") else None) if t)
    if note:
        out.append(_t(x, G["note_y"], W, 0.45, _r(note, T["note"], color=P["muted"])))
    out.append({"type": "line", "x1": x, "y1": G["footer_rule_y"], "x2": x + W, "y2": G["footer_rule_y"], "color": P["mute_bar"],
                "width": house.RULE_PT, "role": "footer_rule"})
    out.append(_t(x, G["footer_y"], W * 0.75, 0.3, _r(e.get("deck", ""), T["note"], color=P["muted"])))
    out.append(_t(x + W * 0.75, G["footer_y"], W * 0.25, 0.3, _r(str(e.get("page", "")), T["note"], color=P["muted"]), align="r"))
    return out


def c_stat_callout(e):
    from . import house
    P = house.PALETTE
    x, y, w = float(e["x"]), float(e["y"]), float(e.get("w") or 3)
    big = 44 if w >= 2.5 else 36
    out = [_t(x, y, w, 0.8, _r(e.get("value", ""), big, True, e.get("color") or P["accent"], house.FONTS["heading"]), valign="b")]
    if e.get("label"):
        out.append(_t(x, y + 0.85, w, 0.36, _r(e["label"], 14, True)))
    if e.get("context"):
        out.append(_t(x, y + 1.22, w, 0.62, _r(e["context"], 14, color=P["muted"])))
    return out


def c_change_badge(e):
    from . import house
    P = house.PALETTE
    s = float(e.get("size") or 0.62)
    fill = e.get("color") or (P["positive"] if e.get("positive", True) else P["negative"])
    return [{"type": "shape", "shape": "ellipse", "x": float(e["x"]), "y": float(e["y"]), "w": s, "h": s, "fill": fill, "inset": 0.02,
             "paragraphs": [{"runs": [_r(e.get("text", ""), 12, True, "#FFFFFF")], "align": "ctr"}], "valign": "ctr"}]


def c_takeaway_box(e):
    from . import house
    P = house.PALETTE
    paras = []
    if e.get("heading"):
        paras.append({"runs": [_r(e["heading"], 16, True)], "space_after": 4})
    if e.get("text"):
        paras.append({"runs": [_r(e["text"], 14)]})
    return [{"type": "shape", "shape": "rect", "x": float(e["x"]), "y": float(e["y"]), "w": float(e["w"]), "h": float(e.get("h") or 1.2),
             "fill": e.get("fill") or P["key_message"], "inset": house.CARD_PADDING, "valign": "ctr", "paragraphs": paras}]


def c_process_flow(e):
    from . import house
    P = house.PALETTE
    steps = e.get("steps") or []
    n = max(1, len(steps))
    x, y, w = float(e["x"]), float(e["y"]), float(e["w"])
    h = float(e.get("h") or 3.6)
    gap = float(e.get("gap") or 0.3)
    sw = (w - gap * (n - 1)) / n
    icon_s, chev_h = 0.6, 0.7
    has_icons = any(s.get("icon") for s in steps)
    cy = y + (icon_s + 0.3 if has_icons else 0)
    out = []
    for k, s in enumerate(steps):
        sx = x + k * (sw + gap)
        if s.get("icon"):
            out.append({"type": "icon", "name": s["icon"], "x": sx + sw / 2 - icon_s / 2, "y": y, "size": icon_s, "badge": P["accent"], "color": "#FFFFFF"})
        out.append({"type": "shape", "shape": "homePlate" if k == 0 else "chevron", "x": sx, "y": cy, "w": sw, "h": chev_h,
                    "fill": P["secondary"], "inset": 0.1, "valign": "ctr",
                    "paragraphs": [{"runs": [_r(f"{k + 1}  ", 14, True, "#FFFFFF"), _r(s.get("title", ""), 14, True, "#FFFFFF")], "align": "ctr"}]})
        if s.get("text"):
            out.append({"type": "shape", "shape": "rect", "x": sx, "y": cy + chev_h + gap, "w": sw, "h": max(0.8, y + h - (cy + chev_h + gap)),
                        "fill": P["panel"], "inset": house.CARD_PADDING, "valign": "t", "paragraphs": [{"runs": [_r(s["text"], 14)]}]})
    return out


def c_icon_grid(e):
    from . import house
    P = house.PALETTE
    items = e.get("items") or []
    cols = int(e.get("cols") or min(3, max(1, len(items))))
    rows = -(-len(items) // cols) if items else 1
    x, y, w, h = float(e["x"]), float(e["y"]), float(e["w"]), float(e.get("h") or 3.8)
    gap = float(e.get("gap") or 0.3)
    cw, ch = (w - gap * (cols - 1)) / cols, (h - gap * (rows - 1)) / rows
    pad, ic = house.CARD_PADDING, 0.55
    out = []
    for k, it in enumerate(items):
        cx, cy = x + (k % cols) * (cw + gap), y + (k // cols) * (ch + gap)
        out.append({"type": "shape", "shape": "rect", "x": cx, "y": cy, "w": cw, "h": ch, "fill": P["panel"]})
        tx = cx + pad
        if it.get("icon"):
            out.append({"type": "icon", "name": it["icon"], "x": cx + pad, "y": cy + pad, "size": ic, "badge": P["accent"], "color": "#FFFFFF"})
            tx = cx + pad + ic + 0.2
        out.append(_t(tx, cy + pad, cx + cw - pad - tx, 0.55, _r(it.get("title", ""), 16, True), valign="ctr"))
        if it.get("text"):
            out.append(_t(cx + pad, cy + pad + ic + 0.15, cw - 2 * pad, ch - 2 * pad - ic - 0.15, _r(it["text"], 14)))
    return out


def c_callout_card(e):
    from . import house
    P = house.PALETTE
    x, y, w, h = float(e["x"]), float(e["y"]), float(e.get("w") or 2.6), float(e.get("h") or 1.0)
    paras = [{"runs": [_r(e.get("title", ""), 14, True, "#FFFFFF")], "space_after": 2}]
    if e.get("text"):
        paras.append({"runs": [_r(e["text"], 14, False, "#FFFFFF")]})
    out = [{"type": "shape", "shape": "rect", "x": x, "y": y, "w": w, "h": h, "fill": e.get("fill") or P["accent"], "inset": house.CARD_PADDING,
            "valign": "ctr", "paragraphs": paras}]
    if e.get("target"):
        tx, ty = float(e["target"][0]), float(e["target"][1])
        sx = min(max(tx, x), x + w)
        sy = y + h if ty > y + h else y if ty < y else ty
        if y <= ty <= y + h:
            sx = x + w if tx > x + w else x
        out.append({"type": "line", "x1": sx, "y1": sy, "x2": tx, "y2": ty, "color": P["accent"], "width": 1})
        out.append({"type": "shape", "shape": "ellipse", "x": tx - 0.07, "y": ty - 0.07, "w": 0.14, "h": 0.14, "fill": P["accent"]})
    return out


def c_numbered_heading(e):
    from . import house
    P = house.PALETTE
    x, y, w = float(e["x"]), float(e["y"]), float(e.get("w") or 8)
    return [_t(x, y, 1.0, 0.4, _r(str(e.get("number", "")), 16, True, P["accent"])),
            {"type": "line", "x1": x, "y1": y + 0.45, "x2": x + 0.4, "y2": y + 0.45, "color": P["accent"], "width": 2},
            _t(x, y + 0.6, w, 1.0, _r(e.get("title", ""), 32, True, None, house.FONTS["heading"]))]


def c_dot_plot(e):
    from . import house
    P = house.PALETTE
    rows = e.get("rows") or []
    x, y, w, h = float(e["x"]), float(e["y"]), float(e["w"]), float(e.get("h") or 3.5)
    lo = float(e.get("min", min([min(r.get("before", 0), r.get("after", 0)) for r in rows] or [0])))
    hi = float(e.get("max", max([max(r.get("before", 0), r.get("after", 0)) for r in rows] or [1])))
    span = (hi - lo) or 1
    lw = w * 0.32
    px, pw = x + lw + 0.3, w - lw - 0.3 - 0.7
    rh = h / max(1, len(rows) + 1)
    unit = e.get("unit", "")
    out = [_t(px - 0.4, y, 1.6, 0.35, _r(e.get("before_label", "Before"), 12, True, P["muted"])),
           _t(px + pw - 1.2, y, 1.6, 0.35, _r(e.get("after_label", "After"), 12, True, P["accent"]), align="r")]
    for k, r in enumerate(rows):
        ry = y + rh * (k + 1)
        b, a = float(r.get("before", 0)), float(r.get("after", 0))
        bx, ax = px + pw * (b - lo) / span, px + pw * (a - lo) / span
        out.append(_t(x, ry - 0.2, lw, 0.4, _r(r.get("label", ""), 14), valign="ctr"))
        out.append({"type": "line", "x1": px, "y1": ry, "x2": px + pw, "y2": ry, "color": "#E5E7EB", "width": 1})
        out.append({"type": "line", "x1": bx, "y1": ry, "x2": ax, "y2": ry, "color": P["muted"], "width": 1.5, "arrow_end": True})
        out.append({"type": "shape", "shape": "ellipse", "x": bx - 0.09, "y": ry - 0.09, "w": 0.18, "h": 0.18, "fill": P["mute_bar"]})
        out.append({"type": "shape", "shape": "ellipse", "x": ax - 0.11, "y": ry - 0.11, "w": 0.22, "h": 0.22, "fill": P["accent"]})
        out.append(_t(px + pw + 0.1, ry - 0.2, 0.9, 0.4, _r(f"{a:g}{unit}", 12, True, P["accent"]), valign="ctr"))
    return out


COMPONENTS = {"exhibit_frame": c_exhibit_frame, "stat_callout": c_stat_callout, "change_badge": c_change_badge,
              "takeaway_box": c_takeaway_box, "process_flow": c_process_flow, "icon_grid": c_icon_grid,
              "callout_card": c_callout_card, "numbered_heading": c_numbered_heading, "dot_plot": c_dot_plot}

COMPONENT_GUIDE = """Components (preferred: they follow the house grid, type scale and spacing automatically). Use
{"type":"component","kind":…} with:
- exhibit_frame: title (the takeaway sentence), measure, unit, note, source, deck, page — use on every content slide. It draws the
  house frame: title top-left (no eyebrow), a rule under the title, a footer rule, deck name left and page number right.
- stat_callout: x, y, w, value ("$9.4B"), label, context (one line)
- change_badge: x, y, text ("+22%"), positive (true/false)
- takeaway_box: x, y, w, h, heading, text — the so-what
- process_flow: x, y, w, h, steps:[{title, text, icon}], gap (0.3 or 0.5)
- icon_grid: x, y, w, h, cols, items:[{icon, title, text}], gap
- callout_card: x, y, w, h, title, text, target:[x, y] (draws a leader line and dot to the target)
- numbered_heading: x, y, number, title
- dot_plot: x, y, w, h, rows:[{label, before, after}], min, max, unit, before_label, after_label
Tables also accept "highlight_column": index.
Icons: {"type":"icon", name, x, y, size (in), color, badge (hex fill: draws the icon white inside a filled circle)}."""


# --------------------------------------------------------------------------- emphasis: bold the important parts
_FIGURE = re.compile(r"(?:US\$|\$|€|£)?\(?-?\d[\d,]*(?:\.\d+)?\)?\s?(?:%|x\b|×|bn\b|billion\b|m\b|mm\b|million\b|k\b|pp\b|bp\b|B\b|M\b)?"
                     r"(?:\s?(?:billion|million))?")
_LEAD = re.compile(r"^([A-Z][^:.;]{2,48}[:.;—–-])\s")


def emphasize(layout: dict, max_size: float = 18) -> dict:
    """Bold the key figures (money, %, multiples) and the lead-in label of each body paragraph. Titles, already-bold
    runs and large type are left alone; whole sentences are never bolded."""
    import copy
    out = copy.deepcopy(layout)

    def split(run):
        txt = run.get("text", "")
        if run.get("bold") or float(run.get("size") or 12) > max_size or not txt.strip():
            return [run]
        pieces, pos = [], 0
        spans = []
        lead = _LEAD.match(txt)
        if lead and len(lead.group(1)) < len(txt) * 0.6:
            spans.append((0, lead.end(1)))
        for m in _FIGURE.finditer(txt):
            frag = m.group(0).strip()
            if not frag or not re.search(r"\d", frag):
                continue
            if re.fullmatch(r"(19|20)\d{2}", frag) or (re.fullmatch(r"\d{1,2}", frag) and not re.search(r"[%x×$]", frag)):
                continue                                 # years and small counts stay regular
            if not re.search(r"[$€£%x×]|bn|billion|million|\bm\b|pp|bp|[BM]\b", frag) and "," not in frag and "." not in frag:
                continue
            s, e = m.start(), m.start() + len(m.group(0).rstrip())
            prev2, nxt = txt[max(0, s - 2):s], txt[e:e + 2]
            if (txt[s:s + 1] in "-−" and s > 0 and txt[s - 1].isdigit()) or (len(prev2) == 2 and prev2[1] in "-/" and prev2[0].isdigit()) \
                    or (len(nxt) == 2 and nxt[0] in "-/" and nxt[1].isdigit()):
                continue                                 # part of a date (2026-08-30) or a fraction (1/2)
            frag_core = txt[s:e].rstrip(",.;")
            e = s + len(frag_core)
            spans.append((s, e))
        if not spans:
            return [run]
        spans.sort()
        merged = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
            else:
                merged.append((s, e))
        bolded = sum(e - s for s, e in merged)
        if bolded > 0.5 * len(txt):
            return [run]                                 # emphasis on most of the line is no emphasis
        for s, e in merged:
            if s > pos:
                pieces.append({**run, "text": txt[pos:s]})
            pieces.append({**run, "text": txt[s:e], "bold": True})
            pos = e
        if pos < len(txt):
            pieces.append({**run, "text": txt[pos:]})
        return pieces

    def walk(paras):
        for pg in paras or []:
            for r in pg.get("runs") or []:
                if isinstance(r.get("text"), str):
                    r["text"] = re.sub(r"\b(Source|Sources|Note|Notes):\s*\1:", r"\1:", r["text"])   # "Source: Source:"
            pg["runs"] = [r2 for r in pg.get("runs") or [] for r2 in split(r)]

    for e in out.get("elements") or []:
        if not isinstance(e, dict):
            continue
        if e.get("type") in ("text", "shape"):
            walk(e.get("paragraphs"))
        elif e.get("type") == "component":
            for k in ("text", "context"):
                pass                                     # components already set their own weights
    return out


# --------------------------------------------------------------------------- bridge: a waterfall drawn from code, so overlays line up
def c_bridge(e):
    """Cash or value walk. steps: [{label, value, total?: bool}], reference: {label, value} (dashed line),
    highlight: step index, notes: [{step, text}], unit ("$m"), number_format ("{:,.0f}")."""
    from . import house
    P = house.PALETTE
    steps = [s for s in e.get("steps") or [] if isinstance(s, dict)]
    if not steps:
        return []
    x, y, w, h = float(e["x"]), float(e["y"]), float(e["w"]), float(e.get("h") or 3.8)
    fmt = (lambda v: f"{v:,.0f}") if not e.get("decimals") else (lambda v: f"{v:,.{int(e['decimals'])}f}")
    label_h, value_h = 0.55, 0.28
    ref = e.get("reference") or {}
    legend_h = 0.35 if ref.get("value") is not None else 0.0
    plot_top, plot_bot = y + legend_h + value_h, y + h - label_h
    # running levels
    levels, run_total = [], 0.0
    for s in steps:
        v = float(s.get("value") or 0)
        if s.get("total"):
            levels.append((0.0, v, True))
            run_total = v
        else:
            lo, hi = sorted((run_total, run_total + v))
            levels.append((lo, hi, False))
            run_total += v
    vals = [v for lo, hi, _ in levels for v in (lo, hi)] + ([float(ref["value"])] if ref.get("value") is not None else []) + [0.0]
    vmax, vmin = max(vals), min(vals)
    span = (vmax - vmin) or 1.0
    to_y = lambda v: plot_bot - (v - vmin) / span * (plot_bot - plot_top)  # noqa: E731
    n = len(steps)
    slot = w / n
    bw = slot * 0.62
    hl = e.get("highlight")
    out = []
    prev_edge = None
    for k, ((lo, hi, total), s) in enumerate(zip(levels, steps)):
        bx = x + k * slot + (slot - bw) / 2
        top, bot = to_y(hi), to_y(lo)
        v = float(s.get("value") or 0)
        fill = P["accent"] if k == hl else (P["text"] if total else (P["positive"] if v >= 0 else P["mute_bar"]))
        out.append({"type": "shape", "shape": "rect", "x": bx, "y": top, "w": bw, "h": max(bot - top, 0.02), "fill": fill})
        lab = ("+" if (v > 0 and not total) else "") + fmt(v) if not total else fmt(v)
        out.append(_t(bx - 0.15, top - value_h, bw + 0.3, value_h, _r(lab, 12, True, P["accent"] if k == hl else P["text"]), align="ctr", valign="b"))
        out.append(_t(x + k * slot + 0.02, plot_bot + 0.06, slot - 0.04, label_h - 0.06,
                      _r(str(s.get("label", "")), 11, False, P["muted"]), align="ctr", valign="t"))
        level_after = hi if (total or v >= 0) else lo
        if prev_edge is not None:
            px, py = prev_edge
            out.append({"type": "line", "x1": px, "y1": py, "x2": bx, "y2": py, "color": "#9CA3AF", "width": 0.75, "dash": "dot"})
        prev_edge = (bx + bw, to_y(level_after))
    out.append({"type": "line", "x1": x, "y1": plot_bot, "x2": x + w, "y2": plot_bot, "color": "#9CA3AF", "width": 0.75})
    if ref.get("value") is not None:
        ry = to_y(float(ref["value"]))
        out.append({"type": "line", "x1": x, "y1": ry, "x2": x + w, "y2": ry, "color": P["negative"], "width": 1.25, "dash": "dash"})
        # legend above the plot (a label on the line would always cross a bar)
        ly = y + 0.14
        out.append({"type": "line", "x1": x + w - 3.6, "y1": ly, "x2": x + w - 3.2, "y2": ly, "color": P["negative"], "width": 1.25, "dash": "dash"})
        lab = str(ref.get("label", "")).strip()
        val = fmt(float(ref["value"]))
        text = lab if val in lab else f"{lab}: {val}".strip(": ")
        out.append(_t(x + w - 3.1, y, 3.1, 0.28, _r(text, 12, True, P["negative"]), valign="ctr"))
    for note in e.get("notes") or []:
        try:
            k = int(note.get("step"))
        except (TypeError, ValueError):
            continue
        if 0 <= k < n:
            lo, hi, _ = levels[k]
            cx = x + k * slot + slot / 2
            top_k = to_y(hi)
            out.append(_t(cx - slot * 0.95, max(plot_top - 0.05, top_k - value_h - 0.42), slot * 1.9, 0.4,
                          _r(str(note.get("text", "")), 12, True, P["accent"]), align="ctr", valign="b"))
    return out


COMPONENTS["bridge"] = c_bridge
COMPONENT_GUIDE += """
- bridge: x, y, w, h, steps:[{label (short, 1-3 words), value, total (true for opening/closing balances)}], reference:{label, value}
  (dashed line, e.g. a cash buffer), highlight (step index), notes:[{step, text}] — USE THIS for every cash or value walk instead
  of a chart plus hand-placed overlays; it aligns bars, labels, connectors and the reference line exactly."""
