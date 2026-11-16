"""Measure an SVG slide draft so its spacing can be checked exactly, not by eye.

Reads rects, lines, circles and text (with simple translate() groups and tspans), estimates text extents
from font size and character count, and returns a layout-like structure in inches (120 SVG units = 1 in)
that om.spacing.check() understands. Findings are reported in SVG units too, so the designer gets numbers
it can act on.
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

U = 120.0                      # SVG units per inch
PX_TO_PT = 0.6                 # 1 px at 120/in = 0.6 pt


def _num(v, d=0.0) -> float:
    try:
        return float(re.sub(r"[a-z%]+$", "", str(v).strip()))
    except (TypeError, ValueError):
        return d


def _style(el) -> dict:
    out = {k: v for k, v in el.attrib.items()}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _translate(tr: str | None) -> tuple[float, float]:
    m = re.search(r"translate\(\s*(-?[\d.]+)[ ,]*(-?[\d.]*)\s*\)", tr or "")
    return (float(m.group(1)), float(m.group(2) or 0)) if m else (0.0, 0.0)


def boxes(svg: str) -> dict:
    """SVG -> {"elements": [...]} in inches, the shape om.spacing.check() expects."""
    root = ET.fromstring(re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", svg, count=0))
    els = []

    def walk(node, ox, oy, inherited):
        tx, ty = _translate(node.get("transform"))
        ox, oy = ox + tx, oy + ty
        st = {**inherited, **{k: v for k, v in _style(node).items() if k in ("font-size", "font-weight", "text-anchor", "fill")}}
        tag = node.tag.split("}")[-1]
        a = _style(node)
        if tag == "rect":
            x, y, w, h = ox + _num(a.get("x")), oy + _num(a.get("y")), _num(a.get("width")), _num(a.get("height"))
            fill = a.get("fill", "#000")
            if w >= 1580 and h >= 880:
                pass                                                   # page background
            elif fill not in ("none", "transparent", "#fff", "#ffffff", "#FFFFFF", "white") and w > 2 and h > 2:
                els.append({"type": "shape", "shape": "rect", "x": x / U, "y": y / U, "w": w / U, "h": h / U, "fill": fill,
                            "svg": (x, y, w, h)})
            elif w > 2 and h <= 3:
                els.append({"type": "line", "x1": x / U, "y1": y / U, "x2": (x + w) / U, "y2": y / U})
        elif tag == "line":
            x1, y1, x2, y2 = (ox + _num(a.get("x1")), oy + _num(a.get("y1")), ox + _num(a.get("x2")), oy + _num(a.get("y2")))
            els.append({"type": "line", "x1": x1 / U, "y1": y1 / U, "x2": x2 / U, "y2": y2 / U})
        elif tag == "text":
            lines = []
            base_x, base_y = ox + _num(a.get("x")), oy + _num(a.get("y"))
            size = _num(st.get("font-size", a.get("font-size", 16)), 16)
            spans = [c for c in node if c.tag.split("}")[-1] == "tspan"]
            if (node.text or "").strip():
                lines.append((base_x, base_y, node.text.strip(), size))
            for sp in spans:
                ss = _style(sp)
                sx = ox + _num(ss.get("x"), base_x - ox) if ss.get("x") else (lines[-1][0] if lines else base_x)
                sy = oy + _num(ss.get("y")) if ss.get("y") else (lines[-1][1] + _num(ss.get("dy"), 0) if lines else base_y + _num(ss.get("dy"), 0))
                txt = "".join(sp.itertext()).strip()
                if txt:
                    lines.append((sx, sy, txt, _num(ss.get("font-size"), size)))
            if lines:
                anchor = st.get("text-anchor", a.get("text-anchor", "start"))
                xs, x2s, tops, bots = [], [], [], []
                for lx, ly, txt, sz in lines:
                    w = len(txt) * sz * 0.52
                    left = lx - (w / 2 if anchor == "middle" else w if anchor == "end" else 0)
                    xs.append(left), x2s.append(left + w), tops.append(ly - sz * 0.8), bots.append(ly + sz * 0.25)
                x, y = min(xs), min(tops)
                els.append({"type": "text", "x": x / U, "y": y / U, "w": (max(x2s) - x) / U, "h": (max(bots) - y) / U,
                            "paragraphs": [{"runs": [{"text": t, "size": round(sz * PX_TO_PT, 1),
                                                      "bold": str(st.get("font-weight", "")) in ("bold", "700", "600")}]} for _, _, t, sz in lines],
                            "inset": 0, "svg": (x, y, max(x2s) - x, max(bots) - y)})
        for child in node:
            if child.tag.split("}")[-1] not in ("defs", "style", "title", "desc", "tspan"):
                walk(child, ox, oy, st)

    walk(root, 0.0, 0.0, {})
    return {"elements": els}


def check(svg: str) -> list[str]:
    """Spacing findings for an SVG draft, with inches converted back to SVG units for the designer."""
    from .spacing import check as spacing_check
    try:
        lay = boxes(svg)
    except ET.ParseError as e:
        return [f"the SVG doesn't parse ({e}); return well-formed SVG"]
    out = []
    for f in spacing_check(lay):
        f = re.sub(r"box (-?[\d.]+),(-?[\d.]+) ([\d.]+)x([\d.]+) in",
                   lambda m: f"box x {float(m.group(1)) * U:.0f}, y {float(m.group(2)) * U:.0f}, {float(m.group(3)) * U:.0f} x {float(m.group(4)) * U:.0f} units", f)
        f = re.sub(r"(-?\d+\.\d+) in", lambda m: f"{float(m.group(1)) * U:.0f} units", f)
        out.append(f)
    return out
