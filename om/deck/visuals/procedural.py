"""Offline procedural generator: per-style parametric art, drawn once as primitives, rendered to PNG (3x supersampled) and SVG.

Flat theme colours only, no gradients, no text glyphs. rng = random.Random(seed); seed None = non-deterministic.
"""
from __future__ import annotations

import io
import math
import random

from .library import ASPECTS, palette_for

SS = 3  # supersampling factor


class Canvas:
    """Primitive recorder: rect / poly / ellipse / line items in pixel units, rendered to PNG and SVG from the same list."""

    def __init__(self, w: int, h: int, bg: str):
        self.w, self.h, self.bg, self.items = w, h, bg, []

    def rect(self, x, y, w, h, c): self.items.append(("poly", [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], c))
    def poly(self, pts, c): self.items.append(("poly", [tuple(p) for p in pts], c))
    def ellipse(self, cx, cy, rx, ry, c): self.items.append(("ell", (cx, cy, rx, ry), c))
    def line(self, pts, width, c, closed=False):
        self.items.append(("line", ([tuple(p) for p in pts] + ([pts[0]] if closed else []), width), c))

    def recolor(self, old: str, new: str):
        self.items = [(k, g, new if c == old else c) for k, g, c in self.items]

    def png(self) -> bytes:
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (self.w * SS, self.h * SS), self.bg)
        d = ImageDraw.Draw(im)
        for kind, g, c in self.items:
            if kind == "poly":
                d.polygon([(x * SS, y * SS) for x, y in g], fill=c)
            elif kind == "ell":
                cx, cy, rx, ry = g
                d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=c)
            else:
                pts, width = g
                d.line([(x * SS, y * SS) for x, y in pts], fill=c, width=max(1, round(width * SS)), joint="curve")
                for x, y in (pts[0], pts[-1]):   # round caps
                    r = width * SS / 2
                    d.ellipse([x * SS - r, y * SS - r, x * SS + r, y * SS + r], fill=c)
        out = io.BytesIO()
        im.resize((self.w, self.h), Image.LANCZOS).save(out, "PNG")
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


# --------------------------------------------------------------------------- per-style generators: (canvas, rng, pal)
def _tones(p):  # greys/secondary tones; accent kept apart
    return [p["secondary"], p["series2"], p["light"], p["mute_bar"], p["panel"], p["muted"]]


def editorial_illustration(c: Canvas, r: random.Random, p):
    W, H, t = c.w, c.h, _tones(p)
    c.rect(r.uniform(.05, .2) * W, r.uniform(.08, .2) * H, r.uniform(.3, .45) * W, r.uniform(.6, .75) * H, p["panel"])
    for _ in range(r.randint(4, 6)):
        col, k = r.choice(t[:4]), r.random()
        cx, cy, s = r.uniform(.15, .85) * W, r.uniform(.2, .8) * H, r.uniform(.1, .22) * H
        if k < .4:
            c.ellipse(cx, cy, s * r.uniform(.8, 1.4), s, col)
        elif k < .7:
            c.rect(cx - s, cy - s * 1.2, s * 2, s * 2.4, col)
        else:   # arch
            c.rect(cx - s, cy, s * 2, s * 1.4, col)
            c.ellipse(cx, cy, s, s, col)
    c.ellipse(r.uniform(.2, .8) * W, r.uniform(.2, .45) * H, H * .06, H * .06, p["accent"])


def isometric_system(c: Canvas, r: random.Random, p):
    W, H = c.w, c.h
    n = r.randint(3, 5)
    s = min(W / (1.732 * (n + 1)), H / (n + 3.2))
    dx, dy, u = .866 * s, .5 * s, s * .55
    ox, oy = W / 2, H * .5 - n * dy * .6 - u
    sets = [(p["light"], p["mute_bar"], p["secondary"]), (p["panel"], p["muted"], p["secondary"]), (p["series2"], p["secondary"], p["text"])]
    hot = (r.randrange(n), r.randrange(n))
    for gi, gj in sorted(((i, j) for i in range(n) for j in range(n)), key=lambda q: q[0] + q[1]):
        k = r.randint(1, 3)
        top, left, right = (p["accent"], p["secondary"], p["text"]) if (gi, gj) == hot else r.choice(sets)
        x, y = ox + (gi - gj) * dx, oy + (gi + gj) * dy + 2 * dy
        hgt = k * u
        c.poly([(x - dx, y + dy - hgt + hgt), (x, y + 2 * dy), (x, y + 2 * dy - hgt), (x - dx, y + dy - hgt)], left)
        c.poly([(x + dx, y + dy), (x, y + 2 * dy), (x, y + 2 * dy - hgt), (x + dx, y + dy - hgt)], right)
        c.poly([(x, y - hgt), (x + dx, y + dy - hgt), (x, y + 2 * dy - hgt), (x - dx, y + dy - hgt)], top)


def line_art_schematic(c: Canvas, r: random.Random, p):
    W, H = c.w, c.h
    cols, lw = r.randint(3, 4), max(2.0, H / 150)
    for i in range(cols):   # swimlane bands
        if i % 2 == 0:
            c.rect(W * i / cols, H * .08, W / cols, H * .84, p["panel"])
    nw, nh = W / (cols * 2.1), H / 8
    hot, pos = r.randrange(cols), []
    for i in range(cols):
        k = r.randint(1, 3)
        for j in range(k):
            x, y = W * (i + .5) / cols, H * .08 + (j + .5) * H * .84 / k
            c.rect(x - nw / 2, y - nh / 2, nw, nh, p["accent"] if (i == hot and j == 0) else p["background"])
            c.line([(x - nw / 2, y - nh / 2), (x + nw / 2, y - nh / 2), (x + nw / 2, y + nh / 2), (x - nw / 2, y + nh / 2)], lw, p["secondary"], closed=True)
            c.rect(x - nw * .3, y - nh * .08, nw * .6, nh * .16, p["mute_bar"])
            pos.append((i, x, y))
    for i in range(cols - 1):
        a, b = [q for q in pos if q[0] == i], [q for q in pos if q[0] == i + 1]
        for _, x, y in a:
            _, x2, y2 = r.choice(b)
            mx = (x + x2) / 2
            c.line([(x + nw / 2, y), (mx, y), (mx, y2), (x2 - nw / 2 - lw * 3, y2)], lw, p["text"])
            ax, ay = x2 - nw / 2, y2
            c.poly([(ax, ay), (ax - lw * 4, ay - lw * 2.2), (ax - lw * 4, ay + lw * 2.2)], p["text"])


def data_art(c: Canvas, r: random.Random, p):
    W, H, v = c.w, c.h, r.choice(("dots", "ribbons", "radial"))
    cols = [p["secondary"], p["series2"], p["light"], p["mute_bar"]]
    if v == "dots":
        nx = r.randint(10, 13)
        ny = max(5, round(nx * H / W))
        cell, ph, fr = min(W / nx, H / ny), r.uniform(0, 6.28), r.uniform(.6, 1.4)
        hot = (r.randrange(nx), r.randrange(ny))
        for i in range(nx):
            for j in range(ny):
                k = (math.sin(i * fr * .5 + ph) + math.cos(j * fr * .7 - ph) + 2) / 4
                rad = cell * (.12 + .38 * k)
                c.ellipse((i + .5) * W / nx, (j + .5) * H / ny, rad, rad,
                          p["accent"] if (i, j) == hot else cols[min(3, int(k * 4))])
    elif v == "ribbons":
        nb, base = r.randint(4, 6), H * .18
        for b in range(nb):
            amp, fq, ph, th = r.uniform(.05, .13) * H, r.uniform(1.2, 3) / W * 6.28, r.uniform(0, 6.28), r.uniform(.07, .14) * H
            top = [(x, base + b * H * .13 + amp * math.sin(fq * x + ph)) for x in range(0, W + 1, max(4, W // 80))]
            c.poly(top + [(x, y + th) for x, y in reversed(top)], p["accent"] if b == nb - 2 and r.random() < .6 else cols[b % 4])
    else:
        cx, cy, n = W / 2, H / 2, r.randint(36, 60)
        r0, rm = H * .12, H * .46
        hot = r.randrange(n)
        for i in range(n):
            a0, a1 = i / n * 6.2832, (i + .62) / n * 6.2832
            ln = r0 + (rm - r0) * (.25 + .75 * abs(math.sin(i * r.uniform(.2, .35) + 1)))
            c.poly([(cx + r0 * math.cos(a0), cy + r0 * math.sin(a0)), (cx + ln * math.cos(a0), cy + ln * math.sin(a0)),
                    (cx + ln * math.cos(a1), cy + ln * math.sin(a1)), (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1))],
                   p["accent"] if i == hot else cols[i % 3])


def duotone_hero(c: Canvas, r: random.Random, p):
    W, H = c.w, c.h
    a, b = r.choice(((p["secondary"], p["light"]), (p["text"], p["mute_bar"]), (p["secondary"], p["panel"])))
    c.rect(r.uniform(0, .2) * W, 0, r.uniform(.4, .6) * W, H, b)
    for _ in range(r.randint(3, 5)):
        col, s = r.choice((a, b)), r.uniform(.15, .38) * H
        x, y = r.uniform(.1, .9) * W, r.uniform(.15, .85) * H
        k = r.random()
        (c.ellipse(x, y, s, s, col) if k < .5 else c.rect(x - s, y - s, s * 2, s * 1.4, col) if k < .8 else
         c.poly([(x - s, y + s), (x, y - s), (x + s, y + s)], col))
    c.ellipse(r.uniform(.2, .8) * W, r.uniform(.25, .75) * H, H * .045, H * .045, p["accent"])


def annotated_map(c: Canvas, r: random.Random, p):
    W, H = c.w, c.h
    mx, my, nx, ny = W * .06, H * .08, r.randint(4, 6), r.randint(3, 4)
    gw, gh = (W - 2 * mx) / nx, (H - 2 * my) / ny
    V = [[(mx + i * gw + (0 if i in (0, nx) else r.uniform(-.3, .3) * gw), my + j * gh + (0 if j in (0, ny) else r.uniform(-.3, .3) * gh))
          for j in range(ny + 1)] for i in range(nx + 1)]
    tones = [p["panel"], p["light"], p["mute_bar"]]
    for i in range(nx):
        for j in range(ny):
            q = [V[i][j], V[i + 1][j], V[i + 1][j + 1], V[i][j + 1]]
            c.poly(q, r.choice(tones))
            c.line(q, 3, p["background"], closed=True)
    pins = [(r.uniform(.15, .85) * W, r.uniform(.2, .8) * H) for _ in range(r.randint(3, 5))]
    for a, b in zip(pins, pins[1:]):   # dashed route
        n = 10
        for k in range(0, n, 2):
            c.line([(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n),
                    (a[0] + (b[0] - a[0]) * (k + 1) / n, a[1] + (b[1] - a[1]) * (k + 1) / n)], 4, p["text"])
    for i, (x, y) in enumerate(pins):
        s = H * .035
        col = p["accent"] if i == 0 else p["secondary"]
        c.poly([(x - s * .8, y - s * 1.4), (x + s * .8, y - s * 1.4), (x, y + s * .6)], col)
        c.ellipse(x, y - s * 2, s, s, col)
        c.ellipse(x, y - s * 2, s * .4, s * .4, p["background"])


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
    W, H = c.w, c.h
    cols, rows = r.choice(((3, 2), (4, 2), (3, 2)))
    gap = min(W, H) * .04
    ts = min((W - gap * (cols + 1)) / cols, (H - gap * (rows + 1)) / rows)
    ox, oy = (W - (ts * cols + gap * (cols - 1))) / 2, (H - (ts * rows + gap * (rows - 1))) / 2
    kinds, hot = r.sample(range(6), 6), r.randrange(cols * rows)
    for n in range(cols * rows):
        x, y = ox + (n % cols) * (ts + gap), oy + (n // cols) * (ts + gap)
        c.rect(x, y, ts, ts, p["panel"])
        c.ellipse(x + ts / 2, y + ts / 2, ts * .36, ts * .36, p["background"])
        _glyph(c, kinds[n % 6], x + ts / 2, y + ts / 2, ts * .2, p, n == hot)


_SEG = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg"}


def bold_typographic(c: Canvas, r: random.Random, p):
    W, H = c.w, c.h
    nd = r.choice((2, 3))
    dh = H * .62
    dw, t = min(dh * .55, W * .9 / nd / 1.15), H * .09
    gap = dw * .18
    x0, y0 = (W - (dw * nd + gap * (nd - 1))) / 2, H * .12
    hot = (r.randrange(nd), r.choice("abcdefg"))
    for i in range(nd):
        x, d = x0 + i * (dw + gap), r.randrange(10)
        seg = {"a": (x, y0, dw, t), "d": (x, y0 + dh - t, dw, t), "g": (x, y0 + dh / 2 - t / 2, dw, t),
               "f": (x, y0, t, dh / 2), "b": (x + dw - t, y0, t, dh / 2), "e": (x, y0 + dh / 2, t, dh / 2), "c": (x + dw - t, y0 + dh / 2, t, dh / 2)}
        for k, box in seg.items():
            lit = k in _SEG[d]
            c.rect(*box, p["accent"] if (i, k) == hot and lit else p["secondary"] if lit else p["panel"])
    for i in range(r.randint(5, 9)):   # base rhythm bars
        bw = W * .8 / 9
        c.rect(W * .1 + i * bw, H * .84, bw * .7, H * .05, r.choice((p["mute_bar"], p["light"], p["secondary"])))


GENERATORS = {f.__name__: f for f in (editorial_illustration, isometric_system, line_art_schematic, data_art, duotone_hero,
                                      annotated_map, iconographic_system, bold_typographic)}


def render(style: str, *, seed: int | None = None, aspect: str = "16:9", theme=None) -> tuple[bytes, str, int]:
    """-> (png bytes, svg string, seed used). Accent is capped at 12% of painted pixels (recolours to secondary if over)."""
    from . import score
    if style not in GENERATORS:
        raise ValueError(f"unknown style {style!r}")
    seed = random.SystemRandom().randrange(2 ** 31) if seed is None else seed
    p = palette_for(theme)
    w, h = ASPECTS.get(aspect, ASPECTS["16:9"])
    c = Canvas(w, h, p["background"])
    GENERATORS[style](c, random.Random(seed), p)
    png = c.png()
    if score.color_shares(png, p)["accent"] > .12:
        c.recolor(p["accent"], p["secondary"])
        png = c.png()
    return png, c.svg(), seed
