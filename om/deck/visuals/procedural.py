"""Offline procedural generator: per-style parametric art, drawn once as primitives, rendered to PNG (3x supersampled) and SVG.

Flat theme colours only, no gradients, no text glyphs. rng = random.Random(seed); seed None = non-deterministic.

Composition rules (library.RULES) are enforced in code, not hoped for:
  * every mark sits inside a safe margin (6 % of the shorter side): over-wide drawings are scaled to fit;
  * visual weight is balanced: if the painted centroid leaves the middle band the drawing is mirrored / shifted;
  * accent <= 12 % of painted pixels (recoloured to secondary otherwise);
  * generators keep >= 25 % negative space, no mark below 0.8 % of the canvas width, one or two stroke widths per style;
  * each style has 3-5 sub-compositions picked by ``seed % n`` so neighbouring seeds differ in structure, not just colour.
"""
from __future__ import annotations

import io
import math
import random

from .library import ASPECTS, RULES, palette_for

SS = 3  # supersampling factor


class Canvas:
    """Primitive recorder: rect / poly / ellipse / line items in pixel units, rendered to PNG and SVG from the same list."""

    def __init__(self, w: int, h: int, bg: str, variant: int = 0):
        self.w, self.h, self.bg, self.items, self.variant = w, h, bg, [], variant
        m = RULES["safe_margin"] * min(w, h)
        self.x0, self.y0, self.x1, self.y1 = m, m, w - m, h - m      # internal safe box
        self.bw, self.bh = self.x1 - self.x0, self.y1 - self.y0
        self.lw = max(3.0, min(w, h) * .0075)                         # the style's one stroke width

    def rect(self, x, y, w, h, c): self.items.append(("poly", [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], c))
    def poly(self, pts, c): self.items.append(("poly", [tuple(p) for p in pts], c))
    def ellipse(self, cx, cy, rx, ry, c): self.items.append(("ell", (cx, cy, rx, ry), c))
    def line(self, pts, width, c, closed=False):
        self.items.append(("line", ([tuple(p) for p in pts] + ([pts[0]] if closed else []), width), c))

    def recolor(self, old: str, new: str):
        self.items = [(k, g, new if c == old else c) for k, g, c in self.items]

    # -- geometry helpers -------------------------------------------------------------------------------------------
    def bbox(self):
        xs, ys = [], []
        for kind, g, _ in self.items:
            if kind == "poly":
                xs += [q[0] for q in g]; ys += [q[1] for q in g]
            elif kind == "ell":
                xs += [g[0] - g[2], g[0] + g[2]]; ys += [g[1] - g[3], g[1] + g[3]]
            else:
                hw = g[1] / 2
                xs += [q[0] - hw for q in g[0]] + [q[0] + hw for q in g[0]]
                ys += [q[1] - hw for q in g[0]] + [q[1] + hw for q in g[0]]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)

    def affine(self, sx, sy, tx, ty):
        """x' = sx*x + tx, y' = sy*y + ty over every primitive (stroke widths are left alone)."""
        f = lambda q: (q[0] * sx + tx, q[1] * sy + ty)
        out = []
        for kind, g, c in self.items:
            if kind == "poly":
                g = [f(q) for q in g]
            elif kind == "ell":
                g = (g[0] * sx + tx, g[1] * sy + ty, g[2] * abs(sx), g[3] * abs(sy))
            else:
                g = ([f(q) for q in g[0]], g[1])
            out.append((kind, g, c))
        self.items = out

    def raster(self, ss: int = SS):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (self.w * ss, self.h * ss), self.bg)
        d = ImageDraw.Draw(im)
        for kind, g, c in self.items:
            if kind == "poly":
                d.polygon([(x * ss, y * ss) for x, y in g], fill=c)
            elif kind == "ell":
                cx, cy, rx, ry = g
                d.ellipse([(cx - rx) * ss, (cy - ry) * ss, (cx + rx) * ss, (cy + ry) * ss], fill=c)
            else:
                pts, width = g
                d.line([(x * ss, y * ss) for x, y in pts], fill=c, width=max(1, round(width * ss)), joint="curve")
                for x, y in (pts[0], pts[-1]):   # round caps
                    r = width * ss / 2
                    d.ellipse([x * ss - r, y * ss - r, x * ss + r, y * ss + r], fill=c)
        return im

    def png(self) -> bytes:
        from PIL import Image
        out = io.BytesIO()
        self.raster(SS).resize((self.w, self.h), Image.LANCZOS).save(out, "PNG")
        return out.getvalue()

    def svg(self) -> str:
        f = lambda v: f"{v:.1f}"
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">',
                 f'<rect width="{self.w}" height="{self.h}" fill="{self.bg}"/>']
        for kind, g, c in self.items:
            if kind == "poly":
                parts.append(f'<polygon points="{" ".join(f"{f(x)},{f(y)}" for x, y in g)}" fill="{c}"/>')
            elif kind == "ell":
                cx, cy, rx, ry = g
                parts.append(f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{f(rx)}" ry="{f(ry)}" fill="{c}"/>')
            else:
                pts, width = g
                parts.append(f'<polyline points="{" ".join(f"{f(x)},{f(y)}" for x, y in pts)}" fill="none" stroke="{c}" '
                             f'stroke-width="{f(width)}" stroke-linecap="round" stroke-linejoin="round"/>')
        return "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- shared drawing helpers
def _circle(cx, cy, r, n=48):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _half(cx, cy, rx, ry, up=True, n=48):
    """Half-ellipse polygon resting on the horizontal line y = cy (up = above the line)."""
    sg = -1 if up else 1
    return [(cx + rx * math.cos(math.pi * i / n), cy + sg * ry * math.sin(math.pi * i / n)) for i in range(n + 1)]


def _arrow(c: Canvas, pts, col, lw=None):
    """Orthogonal connector ending in a filled arrowhead whose tip is the last point."""
    lw = lw or c.lw
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    L = math.hypot(x1 - x0, y1 - y0) or 1
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    al = lw * 3.4
    base = (x1 - ux * al, y1 - uy * al)
    c.line(list(pts[:-1]) + [base], lw, col)
    c.poly([(x1, y1), (base[0] - uy * al * .5, base[1] + ux * al * .5), (base[0] + uy * al * .5, base[1] - ux * al * .5)], col)


def _ground(c: Canvas, p, gy, band=.07):
    c.rect(c.x0, gy, c.bw, c.bh * band, p["panel"])
    c.line([(c.x0 + c.lw, gy), (c.x1 - c.lw, gy)], c.lw, p["text"])


# --------------------------------------------------------------------------- editorial_illustration
def _ed_skyline(c, r, p):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .86
    n = r.randint(6, 8)
    ws = [r.uniform(.8, 1.25) for _ in range(n)]
    total, gap = bw * r.uniform(.62, .74), bw * .01
    unit = (total - gap * (n - 1)) / sum(ws)
    sx = x0 + (bw - total) * r.uniform(.2, .8)
    focal = r.randrange(1, n - 1)
    xs, x = [], sx
    for w in ws:
        xs.append((x, w * unit)); x += w * unit + gap
    fx, fw = xs[focal]
    c.ellipse(fx + fw / 2 + r.uniform(-.1, .1) * bw, gy - bh * .45, bh * r.uniform(.3, .36), bh * .33, p["light"])
    tones = [p["secondary"], p["mute_bar"]]
    prev = None
    for i, (bx, bwid) in enumerate(xs):
        if i == focal:
            continue
        h = bh * r.uniform(.28, .56)
        col = r.choice([t for t in tones if t != prev]); prev = col
        c.rect(bx, gy - h, bwid, h, col)
        if r.random() < .6:                                   # setback crown
            c.rect(bx + bwid * .2, gy - h - bh * .06, bwid * .6, bh * .06, col)
        if col == p["secondary"] and bwid > 80:               # window rhythm: vertical slits
            k = max(1, int(bwid // 56))
            for s in range(k):
                sx2 = bx + bwid * (s + .5) / k - 9
                c.rect(sx2, gy - h + bh * .05, 18, min(h * .55, bh * .16), p["light"])
    h = bh * .74
    c.rect(fx, gy - h, fw, h, p["accent"])
    c.rect(fx + fw * .22, gy - h - bh * .05, fw * .56, bh * .05, p["accent"])
    c.line([(fx + fw / 2, gy - h - bh * .05), (fx + fw / 2, gy - h - bh * .11)], c.lw, p["accent"])
    _ground(c, p, gy)


def _ed_factory(c, r, p):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .86
    fx, fw, fh = x0 + bw * r.uniform(.03, .08), bw * .4, bh * .3
    for k, (cx, ch) in enumerate(((.1, .42), (.2, .3))):     # chimneys sit behind the hall
        c.rect(fx + fw * cx, gy - fh - bh * ch, bw * .036, fh + bh * ch, p["text"])
    c.rect(fx, gy - fh, fw, fh, p["secondary"])
    teeth, th = 4, bh * .12
    tw = fw / teeth
    for i in range(teeth):
        c.poly([(fx + i * tw, gy - fh), (fx + i * tw, gy - fh - th), (fx + (i + 1) * tw, gy - fh)], p["secondary"])
        c.rect(fx + i * tw + tw * .2, gy - fh * .78, tw * .6, fh * .34, p["light"])
    c.rect(fx + fw * .44, gy - fh * .3, fw * .12, fh * .3, p["text"])
    yx = fx + fw + bw * r.uniform(.07, .09)                   # container yard
    cw, chh, gp = bw * .09, bh * .1, bw * .006
    heights = r.choice(((3, 2, 1), (2, 3, 1), (1, 3, 2)))
    tones = [p["light"], p["mute_bar"], p["secondary"]]
    for col in range(3):
        for row in range(heights[col]):
            c.rect(yx + col * (cw + gp), gy - (row + 1) * chh + gp / 2, cw, chh - gp, tones[(col + row) % 3])
    ya, yb = yx - cw * .25, yx + 3 * cw + 2 * gp + cw * .25   # gantry crane
    top = gy - bh * .62
    c.line([(ya, gy), (ya, top)], c.lw * 1.5, p["text"])
    c.line([(yb, gy), (yb, top)], c.lw * 1.5, p["text"])
    c.line([(ya - cw * .3, top), (yb + cw * .3, top)], c.lw * 1.5, p["text"])
    hx = yx + cw * r.uniform(.2, 1.9)
    c.rect(hx - 16, top - 7, 32, 24, p["text"])
    c.line([(hx, top), (hx, gy - bh * .42)], c.lw, p["text"])
    c.rect(hx - cw / 2, gy - bh * .42, cw, chh, p["accent"])
    _ground(c, p, gy)


def _ed_energy(c, r, p):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .86
    lead_x = x0 + bw * r.uniform(.42, .62)
    c.ellipse(lead_x + bw * r.choice((-.1, .1)), gy - bh * .5, bh * .33, bh * .33, p["light"])
    f1, f2, ph = r.uniform(1.0, 1.6), r.uniform(1.2, 2), r.uniform(0, 6.28)

    def hill(base, amp, f, col, phase):
        pts = [(x0 + bw * i / 60, base - amp * (math.sin(f * 2 * math.pi * i / 60 + phase) * .5 + .5)) for i in range(61)]
        c.poly(pts + [(x1b, gy + bh * .07), (x0, gy + bh * .07)], col)
        return lambda x: base - amp * (math.sin(f * 2 * math.pi * (x - x0) / bw + phase) * .5 + .5)

    x1b = x0 + bw
    back = hill(gy - bh * .05, bh * .08, f1, p["mute_bar"], ph)
    front = hill(gy + bh * .0, bh * .045, f2, p["panel"], ph + 2)
    c.line([(x0 + c.lw, gy + bh * .07), (x1b - c.lw, gy + bh * .07)], c.lw, p["text"])
    spots = [(lead_x, 1.0, True), (lead_x - bw * r.uniform(.22, .3), .62, False), (lead_x + bw * r.uniform(.2, .28), .45, False)]
    for x, s, lead in sorted(spots, key=lambda q: q[1]):
        by = back(x) + 4
        hy = by - bh * .68 * s
        t1, t2 = bw * .0075 * (.6 + .4 * s), bw * .0045 * (.6 + .4 * s)
        col = p["accent"] if lead else p["secondary"]
        c.poly([(x - t1, by), (x + t1, by), (x + t2, hy), (x - t2, hy)], p["text"])
        a0, L, wd = r.uniform(0, 2 * math.pi), bh * .3 * s, bh * .034 * s
        for k in range(3):
            a = a0 + k * 2 * math.pi / 3
            d, n = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
            c.poly([(x, hy), (x + d[0] * L * .28 + n[0] * wd, hy + d[1] * L * .28 + n[1] * wd), (x + d[0] * L, hy + d[1] * L),
                    (x + d[0] * L * .28 - n[0] * wd, hy + d[1] * L * .28 - n[1] * wd)], col)
        c.ellipse(x, hy, bh * .018 * (.6 + .4 * s) + 4, bh * .018 * (.6 + .4 * s) + 4, p["text"])


def _ed_coins(c, r, p):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .86
    n = r.randint(4, 6)
    sw, ch = bw * .092, bh * .085
    gap = sw * r.uniform(.55, .8)
    total = n * sw + (n - 1) * gap
    sx = x0 + (bw - total) * r.uniform(.3, .7) + sw / 2
    ry = sw * .17
    c.ellipse(sx + (n - 1) * (sw + gap) * r.uniform(.6, .9), gy - bh * .36, bh * .42, bh * .42, p["panel"])
    for i in range(n):
        cx, k = sx + i * (sw + gap), i + 2
        hot = i == n - 1
        for j in range(k):
            yb = gy - j * ch
            col = p["accent"] if hot else (p["secondary"] if j % 2 == 0 else p["light"])
            c.ellipse(cx, yb, sw / 2, ry, col)
            c.rect(cx - sw / 2, yb - ch, sw, ch, col)
            c.ellipse(cx, yb - ch, sw / 2, ry, col)
        c.ellipse(cx, gy - k * ch, sw / 2, ry, p["panel"] if not hot else p["key_message"])
    _ground(c, p, gy + ry, .05)


_ED = (_ed_skyline, _ed_factory, _ed_energy, _ed_coins)


def editorial_illustration(c: Canvas, r: random.Random, p):
    _ED[c.variant % len(_ED)](c, r, p)


# --------------------------------------------------------------------------- isometric_system
def isometric_system(c: Canvas, r: random.Random, p):
    W, H = c.bw, c.bh
    v = c.variant % 3
    n = r.randint(3, 5)
    s = min(W / (1.732 * (n + 1)), H / (n + 3.2))
    dx, dy, u = .866 * s, .5 * s, s * .55
    ox, oy = c.x0 + W / 2, c.y0 + H * .5 - n * dy * .6 - u
    sets = [(p["light"], p["mute_bar"], p["secondary"]), (p["panel"], p["muted"], p["secondary"]), (p["series2"], p["secondary"], p["text"])]
    cells = [(i, j) for i in range(n) for j in range(n)]

    def height(i, j):
        if v == 0:
            return r.randint(1, 3)
        if v == 1:                                           # rising stair along the diagonal
            return 1 + min(3, (i + j) * 3 // (2 * n - 2 + 1))
        d = abs(i - (n - 1) / 2) + abs(j - (n - 1) / 2)       # central tower, low shoulders
        return max(1, 4 - int(d * 1.6))
    hs = {q: height(*q) for q in cells}
    hot = max(cells, key=lambda q: (hs[q], r.random()))
    for gi, gj in sorted(cells, key=lambda q: q[0] + q[1]):
        k = hs[(gi, gj)]
        top, left, right = (p["accent"], p["secondary"], p["text"]) if (gi, gj) == hot else sets[(gi * 2 + gj + v) % 3] if v else r.choice(sets)
        x, y = ox + (gi - gj) * dx, oy + (gi + gj) * dy + 2 * dy
        hgt = k * u
        c.poly([(x - dx, y + dy), (x, y + 2 * dy), (x, y + 2 * dy - hgt), (x - dx, y + dy - hgt)], left)
        c.poly([(x + dx, y + dy), (x, y + 2 * dy), (x, y + 2 * dy - hgt), (x + dx, y + dy - hgt)], right)
        c.poly([(x, y - hgt), (x + dx, y + dy - hgt), (x, y + 2 * dy - hgt), (x - dx, y + dy - hgt)], top)


# --------------------------------------------------------------------------- line_art_schematic
def _glyph_line(c: Canvas, kind: int, x: float, y: float, g: float, col, soft, lw):
    """Small geometric glyph, stroked with the style's single stroke width."""
    if kind == 0:
        c.line(_circle(x, y, g), lw, col, closed=True); c.ellipse(x, y, g * .34, g * .34, soft)
    elif kind == 1:
        c.line([(x - g, y), (x + g, y)], lw, col); c.line([(x, y - g), (x, y + g)], lw, col)
    elif kind == 2:
        c.line([(x - g, y + g * .8), (x, y - g), (x + g, y + g * .8)], lw, col, closed=True)
    elif kind == 3:
        for i, hh in enumerate((.9, 1.6, 1.2)):
            c.rect(x - g + i * g * .78, y + g * .9 - hh * g, g * .5, hh * g, col if i == 1 else soft)
    elif kind == 4:
        c.line([(x, y - g), (x + g, y), (x, y + g), (x - g, y)], lw, col, closed=True); c.ellipse(x, y, g * .3, g * .3, soft)
    else:
        c.line([(x - g, y - g), (x + g * .35, y - g), (x + g * .35, y + g * .35), (x - g, y + g * .35)], lw, col, closed=True)
        c.rect(x - g * .3, y - g * .3, g * 1.3, g * 1.3, soft)


def _node(c: Canvas, p, x, y, s, kind, hot=False):
    c.rect(x - s / 2, y - s / 2, s, s, p["accent"] if hot else p["panel"])
    c.line([(x - s / 2, y - s / 2), (x + s / 2, y - s / 2), (x + s / 2, y + s / 2), (x - s / 2, y + s / 2)], c.lw,
           p["text"] if not hot else p["accent"], closed=True)
    _glyph_line(c, kind, x, y, s * .22, p["background"] if hot else p["secondary"], p["key_message"] if hot else p["light"], c.lw)


def _sch_pipeline(c, r, p):
    cols = r.randint(3, 4)
    ns = min(c.bh * .2, c.bw / (cols * 2.3))
    counts = [r.choice((1, 2, 3)) for _ in range(cols)]
    counts[r.randrange(cols)] = 3
    pitch = ns * 1.85
    xs = [c.x0 + ns / 2 + i * (c.bw - ns) / (cols - 1) for i in range(cols)]
    cy = c.y0 + c.bh / 2
    pos = [[(xs[i], cy + (j - (counts[i] - 1) / 2) * pitch) for j in range(counts[i])] for i in range(cols)]
    hot = (r.randrange(cols), 0)
    hot = (hot[0], r.randrange(counts[hot[0]]))
    for i in range(cols - 1):
        edges = {(r.randrange(counts[i]), j2) for j2 in range(counts[i + 1])}
        edges |= {(j, r.randrange(counts[i + 1])) for j in range(counts[i]) if not any(e[0] == j for e in edges)}
        for a, b in sorted(edges):
            (xa, ya), (xb, yb) = pos[i][a], pos[i + 1][b]
            mx = (xa + xb) / 2
            pts = [(xa + ns / 2, ya), (mx, ya), (mx, yb), (xb - ns / 2, yb)] if ya != yb else [(xa + ns / 2, ya), (xb - ns / 2, yb)]
            _arrow(c, pts, p["secondary"])
    kinds = r.sample(range(6), 6)
    for i in range(cols):
        for j, (x, y) in enumerate(pos[i]):
            _node(c, p, x, y, ns, kinds[(i + j) % 6], (i, j) == hot)


def _sch_hub(c, r, p):
    ns = min(c.bh * .19, c.bw / 7.5)
    hs = ns * 1.4
    xc, yc = c.x0 + c.bw / 2, c.y0 + c.bh / 2
    xl, xr = c.x0 + ns / 2, c.x1 - ns / 2
    d = c.bh * .28
    sats = [(xl, yc - d), (xl, yc + d), (xr, yc - d), (xr, yc + d)]
    if r.random() < .5:
        sats += [(xl, yc), (xr, yc)][:r.randint(0, 2)]
    kinds = r.sample(range(6), 6)
    for i, (x, y) in enumerate(sats):
        left = x < xc
        mx = (x + xc) / 2 + (ns - hs) / 4 * 0
        sgn = -1 if left else 1
        pts = [(xc + sgn * hs / 2, yc), (mx, yc), (mx, y), (x - sgn * ns / 2, y)] if y != yc else [(xc + sgn * hs / 2, yc), (x - sgn * ns / 2, y)]
        _arrow(c, pts, p["secondary"])
    if r.random() < .7:
        for sy in (-1, 1):
            _arrow(c, [(xc, yc + sy * hs / 2), (xc, yc + sy * (c.bh / 2 - ns / 2) - sy * ns / 2)], p["secondary"])
            _node(c, p, xc, yc + sy * (c.bh / 2 - ns / 2), ns, kinds[(sy + 3) % 6])
    for i, (x, y) in enumerate(sats):
        _node(c, p, x, y, ns, kinds[i % 6])
    _node(c, p, xc, yc, hs, kinds[5], True)


def _sch_tree(c, r, p):
    ns = min(c.bh * .19, c.bw / 8)
    ys = [c.y0 + ns / 2, c.y0 + c.bh / 2, c.y1 - ns / 2]
    split = r.choice(((2, 1, 2), (1, 2, 2), (2, 2, 1), (1, 1, 2)))
    leaves = sum(split)
    lx = [c.x0 + ns / 2 + i * (c.bw - ns) / (leaves - 1) for i in range(leaves)]
    mids, k = [], 0
    for cnt in split:
        grp = lx[k:k + cnt]; k += cnt
        mids.append(sum(grp) / cnt)
    xr = sum(mids) / len(mids)
    kinds = r.sample(range(6), 6)
    by1, by2 = (ys[0] + ys[1]) / 2, (ys[1] + ys[2]) / 2
    for mx in mids:
        _arrow(c, [(xr, ys[0] + ns / 2), (xr, by1), (mx, by1), (mx, ys[1] - ns / 2)], p["secondary"])
    k = 0
    for mx, cnt in zip(mids, split):
        for q in lx[k:k + cnt]:
            _arrow(c, [(mx, ys[1] + ns / 2), (mx, by2), (q, by2), (q, ys[2] - ns / 2)], p["secondary"])
        k += cnt
    _node(c, p, xr, ys[0], ns * 1.25, kinds[0], True)
    for i, mx in enumerate(mids):
        _node(c, p, mx, ys[1], ns, kinds[1 + i % 5])
    for i, q in enumerate(lx):
        _node(c, p, q, ys[2], ns, kinds[(i + 2) % 6])


def _sch_loop(c, r, p):
    ns = min(c.bh * .2, c.bw / 7)
    xs = [c.x0 + ns / 2, c.x0 + c.bw / 2, c.x1 - ns / 2]
    yt, yb, ym = c.y0 + ns / 2, c.y1 - ns / 2, c.y0 + c.bh / 2
    A, B, C = [(x, yt) for x in xs], [(x, yb) for x in xs], (xs[1], ym)
    h = ns / 2
    for a, b in ((A[0], A[1]), (A[1], A[2])):
        _arrow(c, [(a[0] + h, a[1]), (b[0] - h, b[1])], p["secondary"])
    _arrow(c, [(A[2][0], yt + h), (B[2][0], yb - h)], p["secondary"])
    for a, b in ((B[2], B[1]), (B[1], B[0])):
        _arrow(c, [(a[0] - h, a[1]), (b[0] + h, b[1])], p["secondary"])
    _arrow(c, [(B[0][0], yb - h), (A[0][0], yt + h)], p["secondary"])
    _arrow(c, [(xs[1], yt + h), (xs[1], ym - ns * .65)], p["secondary"])
    _arrow(c, [(xs[1], ym + ns * .65), (xs[1], yb - h)], p["secondary"])
    kinds = r.sample(range(6), 6)
    for i, q in enumerate(A + B[::-1]):
        _node(c, p, q[0], q[1], ns, kinds[i % 6])
    _node(c, p, C[0], C[1], ns * 1.3, kinds[r.randrange(6)], True)


_SCH = (_sch_pipeline, _sch_hub, _sch_tree, _sch_loop)


def line_art_schematic(c: Canvas, r: random.Random, p):
    _SCH[c.variant % len(_SCH)](c, r, p)


# --------------------------------------------------------------------------- data_art
def data_art(c: Canvas, r: random.Random, p):
    W, H, v = c.bw, c.bh, c.variant % 3
    cols = [p["secondary"], p["series2"], p["light"], p["mute_bar"]]
    if v == 0:
        nx = r.randint(10, 13)
        ny = max(5, round(nx * H / W))
        cell, ph, fr = min(W / nx, H / ny), r.uniform(0, 6.28), r.uniform(.6, 1.4)
        ox, oy = c.x0 + (W - cell * nx) / 2, c.y0 + (H - cell * ny) / 2
        hot = (r.randrange(nx), r.randrange(ny))
        for i in range(nx):
            for j in range(ny):
                k = (math.sin(i * fr * .5 + ph) + math.cos(j * fr * .7 - ph) + 2) / 4
                rad = cell * (.14 + .34 * k)
                c.ellipse(ox + (i + .5) * cell, oy + (j + .5) * cell, rad, rad, p["accent"] if (i, j) == hot else cols[min(3, int(k * 4))])
    elif v == 1:
        nb = r.randint(4, 5)
        pitch = H * .78 / nb
        for b in range(nb):
            amp, fq, ph, th = r.uniform(.04, .09) * H, r.uniform(1.2, 3) / W * 6.28, r.uniform(0, 6.28), pitch * r.uniform(.3, .46)
            top = [(x, c.y0 + H * .12 + b * pitch + amp * math.sin(fq * (x - c.x0) + ph)) for x in range(int(c.x0), int(c.x1) + 1, max(4, int(W) // 80))]
            c.poly(top + [(x, y + th) for x, y in reversed(top)], p["accent"] if b == nb - 2 else cols[b % 4])
    else:
        cx, cy, n = c.x0 + W / 2, c.y0 + H / 2, r.randint(36, 56)
        r0, rm = H * .14, H * .46
        hot = r.randrange(n)
        sp = r.uniform(.2, .35)
        for i in range(n):
            a0, a1 = i / n * 6.2832, (i + .62) / n * 6.2832
            ln = r0 + (rm - r0) * (.25 + .75 * abs(math.sin(i * sp + 1)))
            c.poly([(cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)), (cx + ln * math.cos(a0), cy + ln * math.sin(a0)),
                    (cx + ln * math.cos(a1), cy + ln * math.sin(a1)), (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1))],
                   p["accent"] if i == hot else cols[i % 3])


# --------------------------------------------------------------------------- duotone_hero
def _tones(r, p):
    return r.choice(((p["secondary"], p["light"]), (p["text"], p["mute_bar"]), (p["secondary"], p["mute_bar"])))


def _dt_ridges(c, r, p, a, b):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    hy = y0 + bh * .55
    c.ellipse(x0 + bw * r.uniform(.3, .7), hy - bh * .12, bh * .13, bh * .13, p["accent"])
    for k, (base, amp, n, col) in enumerate(((.66, .4, 3, b), (.8, .3, 4, a), (.96, .17, 6, b))):
        pts = []
        for i in range(2 * n + 1):
            y = y0 + bh * base - bh * amp * (r.uniform(.6, 1) if i % 2 else r.uniform(0, .2))
            pts.append((x0 + bw * i / (2 * n), y))
        c.poly(pts + [(c.x1, c.y1), (x0, c.y1)], col)
        if k:
            c.line(pts, c.lw * 1.4, p["background"])


def _dt_colonnade(c, r, p, a, b):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .64
    n = r.randint(9, 13)
    cw = bw / (n * 1.35)
    gap = (bw * .92 - n * cw) / (n - 1)
    sx = x0 + bw * .04
    mode = r.choice(("wave", "stairs", "peak"))
    f = {"wave": lambda i: .5 + .5 * math.sin(i * .9 + r.uniform(0, 1)), "stairs": lambda i: i / (n - 1),
         "peak": lambda i: 1 - abs(2 * i / (n - 1) - 1)}[mode]
    hs = [bh * (.16 + .34 * f(i)) for i in range(n)]
    tall = max(range(n), key=lambda i: hs[i])
    for i, h in enumerate(hs):
        x, col = sx + i * (cw + gap), (a, b)[i % 2]
        c.rect(x, gy - h, cw, h, col)
        if i % 2 == 0:
            c.ellipse(x + cw / 2, gy - h, cw / 2, cw / 2, col)
        if i == tall:
            c.rect(x, gy - h - cw * .5, cw, cw * .5 + h * .14, p["accent"])
            c.ellipse(x + cw / 2, gy - h - cw * .5, cw / 2, cw / 2, p["accent"]) if i % 2 == 0 else None
        c.rect(x, gy + c.lw * 1.5, cw, h * .5, b if i % 2 else p["panel"])
    c.line([(x0 + c.lw, gy), (c.x1 - c.lw, gy)], c.lw, p["text"])


def _dt_arches(c, r, p, a, b):
    x0, y0, bw, bh = c.x0, c.y0, c.bw, c.bh
    gy = y0 + bh * .66
    R0 = min(bh * .56, bw * .32)
    cx = x0 + bw * r.uniform(.4, .6)
    nr = r.randint(4, 5)
    for k in range(nr):
        R = R0 * (1 - k * .8 / nr)
        col = p["accent"] if k == nr - 1 else (a, b)[k % 2]
        c.poly(_half(cx, gy, R, R, True), col)
    for k in range(nr):
        R = R0 * (1 - k * .8 / nr)
        c.poly(_half(cx, gy + c.lw * 1.5, R, R * .42, False), p["light"] if k == nr - 1 else (a, b)[k % 2])
    c.line([(x0 + c.lw, gy), (c.x1 - c.lw, gy)], c.lw, p["text"])


_DT = (_dt_ridges, _dt_colonnade, _dt_arches)


def duotone_hero(c: Canvas, r: random.Random, p):
    a, b = _tones(r, p)
    _DT[c.variant % len(_DT)](c, r, p, a, b)


# --------------------------------------------------------------------------- annotated_map
def annotated_map(c: Canvas, r: random.Random, p):
    v = c.variant % 3
    nx, ny = r.randint(7, 9), r.randint(4, 5)
    gw, gh = c.bw / nx, c.bh / ny
    V = [[(c.x0 + i * gw + (0 if i in (0, nx) else r.uniform(-.25, .25) * gw), c.y0 + j * gh + (0 if j in (0, ny) else r.uniform(-.25, .25) * gh))
          for j in range(ny + 1)] for i in range(nx + 1)]
    cx0, cy0 = r.uniform(.35, .65) * nx, r.uniform(.4, .6) * ny

    def land(i, j):
        u, w = (i + .5 - cx0) / (nx / 2), (j + .5 - cy0) / (ny / 2)
        if v == 0:                                           # one continent
            return u * u + w * w < .72 + r.uniform(-.12, .12)
        if v == 1:                                           # archipelago: a few separate islands
            return any(((i + .5 - ix) ** 2 / 2.4 + (j + .5 - iy) ** 2 / 1.4) < 1 for ix, iy in isl)
        return abs(w - .55 * math.sin(u * 2.2 + cx0)) < .42   # river corridor
    isl = [(r.uniform(1.2, nx - 1.2), r.uniform(.8, ny - .8)) for _ in range(4)]
    tones = [p["panel"], p["light"], p["mute_bar"]]
    tiles = []
    for i in range(nx):
        for j in range(ny):
            if land(i, j):
                q = [V[i][j], V[i + 1][j], V[i + 1][j + 1], V[i][j + 1]]
                c.poly(q, r.choice(tones))
                c.line(q, c.lw * .6, p["background"], closed=True)
                tiles.append(((V[i][j][0] + V[i + 1][j + 1][0]) / 2, (V[i][j][1] + V[i + 1][j + 1][1]) / 2))
    if len(tiles) < 4:
        tiles = [(c.x0 + c.bw * u, c.y0 + c.bh * w) for u, w in ((.3, .4), (.5, .6), (.7, .4), (.5, .3))]
    pins = sorted(r.sample(tiles, min(len(tiles), r.randint(3, 4))))
    for a, b in zip(pins, pins[1:]):                          # dashed route, dash 26 / gap 18
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        t = 0.0
        while t < L:
            e = min(L, t + 26)
            c.line([(a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L), (a[0] + (b[0] - a[0]) * e / L, a[1] + (b[1] - a[1]) * e / L)], c.lw, p["text"])
            t += 44
    for i, (x, y) in enumerate(pins):
        s = c.bh * .04
        col = p["accent"] if i == 0 else p["secondary"]
        c.poly([(x - s * .8, y - s * 1.4), (x + s * .8, y - s * 1.4), (x, y + s * .6)], col)
        c.ellipse(x, y - s * 2, s, s, col)
        c.ellipse(x, y - s * 2, s * .42, s * .42, p["background"])


# --------------------------------------------------------------------------- iconographic_system
def _glyph(c: Canvas, k: int, x: float, y: float, s: float, p, hot: bool):
    main, soft = (p["accent"] if hot else p["secondary"]), p["light"]
    if k == 0:
        c.ellipse(x, y, s, s, main); c.ellipse(x, y, s * .62, s * .62, soft); c.ellipse(x, y, s * .28, s * .28, main)
    elif k == 1:
        c.rect(x - s, y - s * .22, s * 2, s * .44, main); c.rect(x - s * .22, y - s, s * .44, s * 2, main)
    elif k == 2:
        c.poly([(x - s, y + s * .8), (x, y - s), (x + s, y + s * .8)], main); c.poly([(x - s * .45, y + s * .5), (x, y - s * .2), (x + s * .45, y + s * .5)], soft)
    elif k == 3:
        for i, hh in enumerate((.6, 1.0, .8)):
            c.rect(x - s + i * s * .72, y + s - hh * s * 2, s * .5, hh * s * 2, main if i == 1 else soft)
    elif k == 4:
        c.poly([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], main); c.poly([(x, y - s * .45), (x + s * .45, y), (x, y + s * .45), (x - s * .45, y)], soft)
    else:
        c.ellipse(x, y, s, s, soft); c.poly([(x, y), (x, y - s), (x + s, y - s), (x + s, y + s), (x, y + s)], main)


def iconographic_system(c: Canvas, r: random.Random, p):
    cols, rows = ((3, 2), (4, 2), (5, 1))[c.variant % 3]
    gap = min(c.bw, c.bh) * .045
    ts = min((c.bw - gap * (cols - 1)) / cols, (c.bh - gap * (rows - 1)) / rows)
    ox, oy = c.x0 + (c.bw - (ts * cols + gap * (cols - 1))) / 2, c.y0 + (c.bh - (ts * rows + gap * (rows - 1))) / 2
    kinds, hot = r.sample(range(6), 6), r.randrange(cols * rows)
    for n in range(cols * rows):
        x, y = ox + (n % cols) * (ts + gap), oy + (n // cols) * (ts + gap)
        c.rect(x, y, ts, ts, p["panel"])
        c.ellipse(x + ts / 2, y + ts / 2, ts * .36, ts * .36, p["background"])
        _glyph(c, kinds[n % 6], x + ts / 2, y + ts / 2, ts * .2, p, n == hot)


# --------------------------------------------------------------------------- bold_typographic
_SEG = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg"}


def bold_typographic(c: Canvas, r: random.Random, p):
    v = c.variant % 3
    nd = (2, 3, 2)[v]
    dh = c.bh * (.66 if v != 2 else .72)
    dw = min(dh * .56, c.bw * .86 / nd / 1.15)
    t = c.bh * .1
    gap = dw * (.2 if v != 2 else .5)
    tw = dw * nd + gap * (nd - 1)
    x0 = c.x0 + (c.bw - tw) / 2
    y0 = c.y0 + c.bh * .04
    hot = (r.randrange(nd), r.choice("abcdefg"))
    digits = [r.randrange(10) for _ in range(nd)]
    for i in range(nd):
        x = x0 + i * (dw + gap)
        seg = {"a": (x, y0, dw, t), "d": (x, y0 + dh - t, dw, t), "g": (x, y0 + dh / 2 - t / 2, dw, t),
               "f": (x, y0, t, dh / 2), "b": (x + dw - t, y0, t, dh / 2), "e": (x, y0 + dh / 2, t, dh / 2), "c": (x + dw - t, y0 + dh / 2, t, dh / 2)}
        for lit in (False, True):                              # ghosts first so lit segments keep clean corners
            for k, box in seg.items():
                if (k in _SEG[digits[i]]) == lit:
                    c.rect(*box, p["accent"] if (i, k) == hot and lit else p["secondary"] if lit else p["panel"])
    nb = r.randint(5, 7)                                       # plinth: equal blocks spanning the digits
    bg_ = tw * .018
    bwid = (tw - bg_ * (nb - 1)) / nb
    for i in range(nb):
        c.rect(x0 + i * (bwid + bg_), y0 + dh + c.bh * .06, bwid, c.bh * .05, (p["mute_bar"], p["light"], p["secondary"])[(i + v) % 3])


GENERATORS = {f.__name__: f for f in (editorial_illustration, isometric_system, line_art_schematic, data_art, duotone_hero,
                                      annotated_map, iconographic_system, bold_typographic)}


# --------------------------------------------------------------------------- composition enforcement
def _fit_to_safe_box(c: Canvas, passes: int = 3):
    for _ in range(passes):
        if not _fit_once(c):
            break


def _fit_once(c: Canvas) -> bool:
    x0, y0, x1, y1 = c.bbox()
    if x1 <= x0 or y1 <= y0:
        return False
    s = min(c.bw / (x1 - x0), c.bh / (y1 - y0))
    s = min(s, 1.0) if s < 1 or max((x1 - x0) / c.bw, (y1 - y0) / c.bh) > .82 else min(s * .92, 1.5)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ncx = min(max(cx, c.x0 + (x1 - x0) * s / 2), c.x1 - (x1 - x0) * s / 2)
    ncy = min(max(cy, c.y0 + (y1 - y0) * s / 2), c.y1 - (y1 - y0) * s / 2)
    if abs(s - 1) > .005 or abs(ncx - cx) > .01 or abs(ncy - cy) > .01:
        c.affine(s, s, ncx - s * cx, ncy - s * cy)
        return s < 1
    return False


def _centroid(c: Canvas):
    import numpy as np
    im = np.asarray(c.raster(1)).astype(int)
    bg = np.array([int(c.bg[i:i + 2], 16) for i in (1, 3, 5)])
    m = np.abs(im - bg).sum(2) > 24
    ys, xs = np.nonzero(m)
    return (xs.mean() / c.w, ys.mean() / c.h) if len(xs) else (.5, .5)


def _balance(c: Canvas):
    """Pull the painted centroid into the middle band: mirror if that helps, then shift within the safe box."""
    lo, hi = .5 - RULES["centroid_band"] / 2, .5 + RULES["centroid_band"] / 2
    cx, cy = _centroid(c)
    if abs(cx - .5) > .06:
        c.affine(-1, 1, c.w, 0)
        nx, ny = _centroid(c)
        if abs(nx - .5) > abs(cx - .5):
            c.affine(-1, 1, c.w, 0)
        else:
            cx, cy = nx, ny
    if lo + .05 <= cx <= hi - .05 and lo + .05 <= cy <= hi - .05:
        return
    x0, y0, x1, y1 = c.bbox()
    dx = min(max((.5 - cx) * c.w, c.x0 - x0), c.x1 - x1) if abs(cx - .5) > .08 else 0
    dy = min(max((.5 - cy) * c.h, c.y0 - y0), c.y1 - y1) if abs(cy - .5) > .08 else 0
    if dx or dy:
        c.affine(1, 1, dx, dy)


def build(style: str, *, seed: int, aspect: str = "16:9", theme=None) -> Canvas:
    """The recorded, rule-enforced drawing for a style and seed (render() rasterises this)."""
    if style not in GENERATORS:
        raise ValueError(f"unknown style {style!r}")
    p = palette_for(theme)
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    c = Canvas(w, h, p["background"], variant=seed)
    GENERATORS[style](c, random.Random(seed), p)
    _fit_to_safe_box(c)
    _balance(c)
    return c


def render(style: str, *, seed: int | None = None, aspect: str = "16:9", theme=None) -> tuple[bytes, str, int]:
    """-> (png bytes, svg string, seed used). Accent is capped at 12% of painted pixels (recolours to secondary if over)."""
    from . import score
    if style not in GENERATORS:
        raise ValueError(f"unknown style {style!r}")
    seed = random.SystemRandom().randrange(2 ** 31) if seed is None else seed
    p = palette_for(theme)
    c = build(style, seed=seed, aspect=aspect, theme=theme)
    png = c.png()
    if score.color_shares(png, p)["accent"] > RULES["max_accent"]:
        c.recolor(p["accent"], p["secondary"])
        png = c.png()
    return png, c.svg(), seed
