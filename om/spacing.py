"""Automatic spacing and type check on slide layouts (layout JSON, inches on 13.333 x 7.5).

Every finding is a major issue for the graders, so a slide with one can't be signed off. Rules come from
house.py: margins / safe area, minimum type sizes, overlaps, gaps of 0.3 or 0.5 in (one per slide), aligned
edges, equal cards, card padding; and across a deck, the same title and footer position on every page.
"""
from __future__ import annotations

import itertools

from . import house

W, H = house.CANVAS
SAFE = house.GRID["safe"]
FOOTER_TOP = 6.9                  # footer band: page number, deck name
NOTE_TOP = house.GRID["content_bottom"]
TOL_ALIGN = 0.03                  # edges within this are "aligned"
NEAR_ALIGN = 0.15                 # ...beyond it but within this they look like a mistake
TOL_GAP = 0.06
MAX_BLOCK_WORDS = 25
MAX_SLIDE_WORDS = 110


def _box(e) -> tuple[float, float, float, float] | None:
    t = e.get("type")
    if t == "line":
        x1, y1, x2, y2 = (float(e.get(k) or 0) for k in ("x1", "y1", "x2", "y2"))
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    if t == "table":
        rows = len(e.get("rows") or [])
        h = float(e.get("h") or rows * float(e.get("row_height") or 0.32))
        return float(e.get("x") or 0), float(e.get("y") or 0), float(e.get("w") or 0), h
    if t == "component":
        return None                                   # expanded before checking
    if all(k in e for k in ("x", "y", "w")):
        return float(e["x"]), float(e["y"]), float(e["w"]), float(e.get("h") or e.get("size") or 0)
    if t == "icon" and all(k in e for k in ("x", "y")):
        s = float(e.get("size") or 0.5)
        return float(e["x"]), float(e["y"]), s, s
    return None


def _label(e, i) -> str:
    for pg in e.get("paragraphs") or []:
        txt = " ".join(r.get("text", "") for r in pg.get("runs") or []).strip()
        if txt:
            return f"“{txt[:32]}{'…' if len(txt) > 32 else ''}”"
    if e.get("type") == "chart":
        return f"{e.get('kind', 'chart')} chart"
    if e.get("type") == "icon":
        return f"icon {e.get('name', '')}"
    return f"{e.get('shape') or e.get('type')} #{i}"


def _is_background(e, b) -> bool:
    x, y, w, h = b
    return e.get("type") == "shape" and not e.get("paragraphs") and (w * h >= 0.4 * W * H or w >= 0.9 * W or h >= 0.9 * H)


def _is_footer(e, b) -> bool:
    return b[1] >= FOOTER_TOP - 0.05 and b[3] <= 0.6


def _sizes(e) -> list[float]:
    return [float(r.get("size") or 12) for pg in e.get("paragraphs") or [] for r in pg.get("runs") or [] if (r.get("text") or "").strip()]


def text_height(e) -> float:
    """Rough height the text needs (in): glyphs ≈ 0.5 em wide, lines 1.2 em, plus paragraph spacing."""
    w_pt = max(float(e.get("w") or 0) * 72 - 2 * 72 * float(e.get("inset", 0.2 if e.get("type") == "shape" else 0.02)), 10)
    need = 0.0
    paras = e.get("paragraphs") or []
    for k, pg in enumerate(paras):
        runs = pg.get("runs") or []
        size = max([float(r.get("size") or 12) for r in runs] or [12])
        chars = sum(len(r.get("text", "")) for r in runs)
        lines = max(1, -(-chars * size * 0.5 // w_pt))
        need += lines * size * 1.2 + (float(pg.get("space_after", 4)) if k < len(paras) - 1 else 0)   # no trailing space
    return need / 72


def _blocks(elements):
    """Cards (filled shapes with some size), charts, tables and icon cards: the things gaps are measured between."""
    out = []
    for i, e in enumerate(elements, start=1):
        b = _box(e)
        if not b or _is_background(e, b) or _is_footer(e, b):
            continue
        t = e.get("type")
        if (t == "shape" and e.get("fill") and b[2] >= 0.6 and b[3] >= 0.45 and (e.get("shape") or "rect") in
                ("rect", "roundRect", "snip1Rect", "round2SameRect")) or t in ("chart", "table"):
            out.append((i, e, b))
    return out


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    return w * h if w > 0 and h > 0 else 0.0


def _inside(inner, outer, slack=0.02) -> bool:
    return (inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack and inner[0] + inner[2] <= outer[0] + outer[2] + slack
            and inner[1] + inner[3] <= outer[1] + outer[3] + slack)


def check(layout: dict) -> list[str]:
    from .layout import expand
    elements = expand(layout).get("elements") or []
    out = []
    # chart internals (bridge bars, dot-plot marks) obey chart rules: 11 pt labels minimum, checked as one block
    chart_parts = [e for e in elements if e.get("_chart")]
    for e in chart_parts:
        sz = _sizes(e)
        if sz and min(sz) < 11 - 0.01:
            out.append(f"chart label {_label(e, 0)} is {min(sz):g} pt; chart labels are 11 pt minimum")
    groups = {}
    for e in chart_parts:
        b = _box(e)
        if b:
            g = groups.setdefault(e["_chart"], [b[0], b[1], b[0] + b[2], b[1] + b[3]])
            g[0], g[1], g[2], g[3] = min(g[0], b[0]), min(g[1], b[1]), max(g[2], b[0] + b[2]), max(g[3], b[1] + b[3])
    elements = [e for e in elements if not e.get("_chart")] + [
        {"type": "chart", "kind": k, "x": g[0], "y": g[1], "w": g[2] - g[0], "h": g[3] - g[1]} for k, g in groups.items()]
    boxes = [(i, e, _box(e)) for i, e in enumerate(elements, start=1)]
    boxes = [(i, e, b) for i, e, b in boxes if b]
    # 1. canvas and safe area
    for i, e, b in boxes:
        x, y, w, h = b
        if _is_background(e, b):
            continue
        if x < -0.01 or y < -0.01 or x + w > W + 0.01 or y + h > H + 0.01:
            out.append(f"{_label(e, i)} runs off the slide (box {x:.2f},{y:.2f} {w:.2f}x{h:.2f} in)")
            continue
        if _is_footer(e, b):
            continue
        if x < SAFE - 0.01 or x + w > W - SAFE + 0.01 or y < SAFE - 0.2 - 0.01:
            out.append(f"{_label(e, i)} sits inside the {SAFE} in margin (left {x:.2f}, right {W - x - w:.2f}, top {y:.2f} in)")
    # 1b. no eyebrows: nothing small sitting above (or level with the top of) the title
    t = _title(elements)
    if t:
        tsz, tb = t
        for i, e, b in boxes:
            sz = _sizes(e)
            if e.get("type") in ("text", "shape") and sz and max(sz) < tsz - 4 and b[1] + b[3] <= tb[1] + 0.25 and b[1] < 1.5:
                out.append(f"{_label(e, i)} is an eyebrow label above the title; remove it (no eyebrows, as a rule)")
    # 2. type sizes
    for i, e, b in boxes:
        sz = _sizes(e)
        if not sz:
            continue
        small = min(sz)
        if small < house.MIN_ANY_PT - 0.01:
            out.append(f"{_label(e, i)} uses {small:g} pt; nothing goes below {house.MIN_ANY_PT} pt")
        elif house.GRID["content_top"] - 0.35 <= b[1] < NOTE_TOP - 0.05 and not (e.get("type") == "shape" and b[3] < 0.5):
            words = sum(len(r.get("text", "").split()) for pg in e.get("paragraphs") or [] for r in pg.get("runs") or [])
            if words <= 3:                              # a label (bar value, axis or step name): label minimum
                if small < 11 - 0.01:
                    out.append(f"{_label(e, i)} is a {small:g} pt label; labels are 11 pt minimum")
            elif small < house.MIN_BODY_PT - 0.01:
                out.append(f"{_label(e, i)} body text is {small:g} pt; body text is {house.MIN_BODY_PT} pt minimum")
    for i, e, b in boxes:
        if e.get("type") == "table" and float(e.get("font_size") or 10.5) < house.MIN_ANY_PT:
            out.append(f"table #{i} text is {e.get('font_size')} pt; nothing goes below {house.MIN_ANY_PT} pt")
    # 3. card padding
    for i, e, b in boxes:
        if (e.get("type") == "shape" and e.get("paragraphs") and e.get("fill") and b[2] >= 1.0 and b[3] >= 0.6
                and (e.get("shape") or "rect") in ("rect", "roundRect", "snip1Rect", "round2SameRect")
                and float(e.get("inset", house.CARD_PADDING)) < 0.15 - 1e-6):
            out.append(f"{_label(e, i)} has {float(e.get('inset')):.2f} in padding inside its card; use {house.CARD_PADDING} in")
    # 4. overlaps (text on text, or text half over a shape / chart / table)
    texts = [(i, e, b) for i, e, b in boxes if e.get("type") in ("text", "shape") and e.get("paragraphs")]
    solids = [(i, e, b) for i, e, b in boxes if e.get("type") in ("chart", "table", "icon", "image_crop")
              or (e.get("type") == "shape" and not _is_background(e, b))]
    for (i, e, a), (j, f, c) in itertools.combinations(texts, 2):
        ov = _overlap(a, c)
        if ov > 0.05 * min(a[2] * a[3], c[2] * c[3]) and not (_inside(a, c) or _inside(c, a)):
            out.append(f"{_label(e, i)} overlaps {_label(f, j)}")
    for i, e, a in texts:
        for j, f, c in solids:
            if i == j:
                continue
            ov = _overlap(a, c)
            if ov > 0.08 * min(a[2] * a[3], c[2] * c[3]) and not (_inside(a, c) or _inside(c, a)):
                out.append(f"{_label(e, i)} overlaps {_label(f, j)} without sitting inside it")
    # 4b. cards sized to their content: a mostly empty card means the card is too big or the content too small
    cards = [(i, e, b) for i, e, b in boxes if e.get("type") == "shape" and e.get("fill") and b[2] >= 1.0 and b[3] >= 0.9
             and (e.get("shape") or "rect") in ("rect", "roundRect") and not _is_background(e, b)]
    for i, e, cb in cards:
        bottoms = []
        if e.get("paragraphs") and (e.get("valign") or "ctr") == "t":
            bottoms.append(cb[1] + float(e.get("inset", 0.2)) + text_height(e))
        for j, f, fb in boxes:
            if j != i and _inside(fb, cb) and not (f.get("type") == "shape" and f is e):
                bottoms.append(fb[1] + (text_height(f) + 0.04 if f.get("paragraphs") and f.get("type") == "text" else fb[3]))
        if bottoms:
            empty = cb[1] + cb[3] - max(bottoms) - house.CARD_PADDING
            if empty > 0.8 and empty > 0.45 * cb[3]:
                out.append(f"{_label(e, i)} card is mostly empty ({empty:.1f} in of space below its content); size cards to their "
                           "content or give them more to say")
    # 4c. a half-empty content area means the visual is too small
    content = [b for i, e, b in boxes if not _is_background(e, b) and not _is_footer(e, b)
               and b[1] >= house.GRID["content_top"] - 0.4 and b[1] + b[3] <= NOTE_TOP + 0.2]
    if content:
        x0, y0 = min(b[0] for b in content), min(b[1] for b in content)
        x1, y1 = max(b[0] + b[2] for b in content), max(b[1] + b[3] for b in content)
        area_w = W - 2 * house.GRID["margin_x"]
        area_h = NOTE_TOP - house.GRID["content_top"]
        if (x1 - x0) < 0.6 * area_w or (y1 - y0) < 0.5 * area_h:
            out.append(f"the content uses {x1 - x0:.1f} x {y1 - y0:.1f} in of the {area_w:.1f} x {area_h:.1f} in content area; "
                       "enlarge the visual rather than leave the slide half empty")
    # 4d. density: a reader gets the point in five seconds
    words_total = 0
    for i, e, b in texts:
        if _is_footer(e, b) or b[1] >= NOTE_TOP - 0.05 or b[1] < house.GRID["subtitle_y"] - 0.05:
            continue
        words = sum(len(r.get("text", "").split()) for pg in e.get("paragraphs") or [] for r in pg.get("runs") or [])
        words_total += words
        if words > MAX_BLOCK_WORDS and max(_sizes(e) or [0]) < 20:
            out.append(f"{_label(e, i)} has {words} words; keep each block to {MAX_BLOCK_WORDS} or fewer")
    for i, e, b in boxes:
        if e.get("type") == "table":
            words_total += sum(len(str(c).split()) for r in e.get("rows") or [] for c in r)
    if words_total > MAX_SLIDE_WORDS:
        out.append(f"the content area carries {words_total} words; cut to about {MAX_SLIDE_WORDS} — split the slide or move detail to backup")
    # 5. gaps, alignment and equal cards between blocks
    bl = _blocks(elements)
    gaps = []
    for (i, e, a), (j, f, c) in itertools.combinations(bl, 2):
        if _overlap(a, c) > 0:
            continue
        v_shared = min(a[1] + a[3], c[1] + c[3]) - max(a[1], c[1])
        h_shared = min(a[0] + a[2], c[0] + c[2]) - max(a[0], c[0])
        if v_shared > 0.5 * min(a[3], c[3]):          # side by side
            left, right = (a, c) if a[0] < c[0] else (c, a)
            if not any(k not in (i, j) and _between_h(left, right, b) for k, _, b in bl):
                gaps.append((right[0] - left[0] - left[2], _label(e, i), _label(f, j)))
            dt = abs(a[1] - c[1])
            if TOL_ALIGN < dt < NEAR_ALIGN:
                out.append(f"{_label(e, i)} and {_label(f, j)} are side by side but their tops differ by {dt:.2f} in; align them")
            if abs(a[3] - c[3]) / max(a[3], c[3]) < 0.15 and abs(a[3] - c[3]) > TOL_ALIGN and e.get("type") == f.get("type") == "shape":
                out.append(f"{_label(e, i)} and {_label(f, j)} look like equal cards but differ in height by {abs(a[3] - c[3]):.2f} in")
        elif h_shared > 0.5 * min(a[2], c[2]):        # stacked
            top, bot = (a, c) if a[1] < c[1] else (c, a)
            if not any(k not in (i, j) and _between_v(top, bot, b) for k, _, b in bl):
                gaps.append((bot[1] - top[1] - top[3], _label(e, i), _label(f, j)))
            dl = abs(a[0] - c[0])
            if TOL_ALIGN < dl < NEAR_ALIGN:
                out.append(f"{_label(e, i)} and {_label(f, j)} are stacked but their left edges differ by {dl:.2f} in; align them")
            if abs(a[2] - c[2]) / max(a[2], c[2]) < 0.15 and abs(a[2] - c[2]) > TOL_ALIGN and e.get("type") == f.get("type") == "shape":
                out.append(f"{_label(e, i)} and {_label(f, j)} look like equal cards but differ in width by {abs(a[2] - c[2]):.2f} in")
    # 5b. crowding: text that sits right against a card, chart or table above or below it
    for i, e, a in texts:
        if _is_footer(e, a) or abs(a[1] - house.GRID["subtitle_y"]) < 0.06:
            continue                                   # the subtitle is the exhibit's caption: it sits on the exhibit
        for j, f, c in bl:
            if i == j or _inside(a, c) or _overlap(a, c) > 0:
                continue
            h_shared = min(a[0] + a[2], c[0] + c[2]) - max(a[0], c[0])
            if h_shared <= 0.3 * min(a[2], c[2]):
                continue
            gap = a[1] - (c[1] + c[3]) if a[1] >= c[1] + c[3] else c[1] - (a[1] + a[3])
            if -0.01 <= gap < 0.15:
                out.append(f"{_label(e, i)} sits {max(gap, 0):.2f} in from {_label(f, j)}; leave at least {house.GAPS[0]} in")
    # 5c. an empty band across the content area means the blocks are floating
    content_boxes = sorted((b for i, e, b in boxes if not _is_background(e, b) and not _is_footer(e, b)
                            and b[1] >= house.GRID["subtitle_y"] - 0.05 and b[1] < NOTE_TOP), key=lambda b: b[1])
    reach = None
    for b in content_boxes:
        if reach is not None and b[1] - reach > 0.9:
            out.append(f"an empty band of {b[1] - reach:.2f} in runs across the slide (y {reach:.2f} to {b[1]:.2f} in); "
                       "close it up or enlarge the content")
        reach = max(reach or 0, b[1] + b[3])
    used = set()
    for g, x, y in gaps:
        if g > 1.2:
            continue                                  # separate regions, not a gap between neighbours
        near = [s for s in house.GAPS if abs(g - s) <= TOL_GAP]
        if not near:
            out.append(f"gap of {g:.2f} in between {x} and {y}; gaps are {house.GAPS[0]} or {house.GAPS[1]} in")
        else:
            used.add(near[0])
    if len(used) > 1:
        out.append(f"this slide mixes {house.GAPS[0]} in and {house.GAPS[1]} in gaps; pick one")
    return out


def _between_h(left, right, b) -> bool:
    return left[0] + left[2] <= b[0] + 0.01 and b[0] + b[2] <= right[0] + 0.01 and _overlap((b[0], left[1], b[2], left[3]), b) > 0


def _between_v(top, bot, b) -> bool:
    return top[1] + top[3] <= b[1] + 0.01 and b[1] + b[3] <= bot[1] + 0.01 and _overlap((top[0], b[1], top[2], b[3]), b) > 0


def _title(elements):
    cands = []
    for e in elements:
        b = _box(e)
        sz = _sizes(e)
        if b and sz and e.get("type") == "text" and b[1] < 2.0:
            cands.append((max(sz), b))
    return max(cands, key=lambda c: c[0]) if cands else None


def _rules(elements) -> tuple[bool, bool, bool]:
    """(rule under the title, rule above the footer, page number in the footer)"""
    t = _title(elements)
    lines = [e for e in elements if e.get("type") == "line" and abs(float(e.get("y1") or 0) - float(e.get("y2") or 0)) < 0.01
             and abs(float(e.get("x2") or 0) - float(e.get("x1") or 0)) > 0.6 * (W - 2 * house.GRID["margin_x"])]
    under = bool(t) and any(t[1][1] + 0.0 < float(l["y1"]) < t[1][1] + t[1][3] + 0.45 for l in lines)
    foot = any(6.6 < float(l["y1"]) < 7.05 for l in lines)
    page = any(_box(e) and _box(e)[1] >= FOOTER_TOP - 0.05 and any(
        __import__("re").fullmatch(r"\s*\d{1,3}\s*", r.get("text", "")) for pg in e.get("paragraphs") or [] for r in pg.get("runs") or [])
        for e in elements)
    return under, foot, page


def deck_check(layouts: list[dict]) -> list[str]:
    """The same frame on every content page: title rule, footer rule with page number, title and footer positions."""
    from .layout import expand
    out = []
    for n, l in enumerate(layouts, start=1):
        if n == 1:
            continue
        under, foot, page = _rules(expand(l).get("elements") or [])
        if not under:
            out.append(f"slide {n}: no rule under the title")
        if not foot:
            out.append(f"slide {n}: no rule above the footer")
        if not page:
            out.append(f"slide {n}: no page number in the footer")
    content = [(n, expand(l).get("elements") or []) for n, l in enumerate(layouts, start=1) if n > 1]   # page 1 is the cover
    titles = [(n, _title(els)) for n, els in content]
    titles = [(n, t) for n, t in titles if t]
    if len(titles) >= 2:
        ref_n, (ref_sz, ref_b) = titles[0]
        for n, (sz, b) in titles[1:]:
            if abs(b[0] - ref_b[0]) > TOL_ALIGN or abs(b[1] - ref_b[1]) > 0.1:
                out.append(f"slide {n}: the title sits at ({b[0]:.2f}, {b[1]:.2f}) in, slide {ref_n} at ({ref_b[0]:.2f}, {ref_b[1]:.2f}); use one title position")
            if abs(sz - ref_sz) > 0.5:
                out.append(f"slide {n}: title is {sz:g} pt, slide {ref_n} is {ref_sz:g} pt; use one title size")
    feet = []
    for n, els in content:
        fb = [(_box(e)) for e in els if _box(e) and _is_footer(e, _box(e)) and _sizes(e)]
        if fb:
            feet.append((n, min(b[1] for b in fb)))
    if len(feet) >= 2:
        ref_n, ref_y = feet[0]
        for n, y in feet[1:]:
            if abs(y - ref_y) > 0.05:
                out.append(f"slide {n}: the footer sits at y {y:.2f} in, slide {ref_n} at {ref_y:.2f} in; use one footer position")
    return out
