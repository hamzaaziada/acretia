"""Deterministic visual scoring (0-10): palette, accent restraint, whitespace, complexity, text-free, distinctness; optional VLM."""
from __future__ import annotations

import io

from .library import palette_for

WEIGHTS = {"palette": .25, "accent": .15, "whitespace": .15, "complexity": .15, "text_free": .15, "distinct": .15}


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _d(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** .5


def _open(png: bytes, width: int):
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    h = max(1, round(im.height * width / im.width))
    return im.resize((width, h), Image.BOX)


def _px(im) -> list:
    return list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())


def _background(im, hint: str | None = None):
    """The theme background if it covers >= 2% of the image, else the dominant colour."""
    if hint:
        h, px = _hex(hint), _px(im)
        if sum(_d(q, h) < 24 for q in px) >= .02 * len(px):
            return h
    return max(im.getcolors(im.width * im.height), key=lambda t: t[0])[1]


def color_shares(png: bytes, pal: dict) -> dict:
    """painted = share of pixels away from the dominant (background) colour; accent / in_palette = shares of painted."""
    im = _open(png, 160)
    px, bg = _px(im), _background(im, pal.get("background"))
    painted = [q for q in px if _d(q, bg) > 24]
    if not painted:
        return {"painted": 0.0, "accent": 0.0, "in_palette": 0.0}
    cols = [_hex(v) for v in pal.values() if isinstance(v, str) and v.startswith("#") and len(v) == 7]
    acc = _hex(pal["accent"])
    return {"painted": len(painted) / len(px),
            "accent": sum(_d(q, acc) < 40 for q in painted) / len(painted),
            "in_palette": sum(min(_d(q, c) for c in cols) < 70 for q in painted) / len(painted)}


def phash(png: bytes) -> int:
    """256-bit difference hash (17x16 greyscale)."""
    im = _open(png, 17).convert("L").resize((17, 16))
    px, bits = _px(im), 0
    for y in range(16):
        for x in range(16):
            bits = (bits << 1) | (px[y * 17 + x] > px[y * 17 + x + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _edge_density(png: bytes) -> float:
    from PIL import ImageFilter
    g = _open(png, 200).convert("L").filter(ImageFilter.FIND_EDGES)
    px = _px(g)
    return sum(v > 40 for v in px) / len(px)


def _texty_rows(png: bytes, bg_hint: str | None = None) -> float:
    """Share of rows with glyph-row texture: very many short painted/unpainted runs (typical of lines of text)."""
    im = _open(png, 320)
    bg, w = _background(im, bg_hint), im.width
    px = _px(im)
    bad = 0
    for y in range(im.height):
        row = [_d(q, bg) > 60 for q in px[y * w:(y + 1) * w]]
        tr = sum(row[i] != row[i + 1] for i in range(w - 1))
        if tr >= 36:
            bad += 1
    return bad / im.height


def score(candidate, theme=None, others=()) -> dict:
    png = candidate.png if hasattr(candidate, "png") else candidate
    pal = palette_for(theme)
    sh = color_shares(png, pal)
    p = sh["painted"]
    s = {"palette": 10 * min(1, sh["in_palette"] / .9) if p else 0.0,
         "accent": 10.0 if sh["accent"] <= .15 else max(0.0, 10 - (sh["accent"] - .15) * 50),
         "whitespace": 0.0 if p <= 0 else 10.0 if .25 <= p <= .7 else max(0.0, 10 - (.25 - p) * 40) if p < .25 else max(0.0, 10 - (p - .7) * 30)}
    e = _edge_density(png) if p else 0.0
    s["complexity"] = 10 * min(1, e / .02) if e < .02 else 10.0 if e <= .25 else max(0.0, 10 - (e - .25) * 40)
    s["text_free"] = max(0.0, 10 - 25 * _texty_rows(png, pal.get('background'))) if p else 0.0
    hs = [phash(o.png if hasattr(o, "png") else o) for o in others]
    h = phash(png)
    s["distinct"] = 10.0 if not hs else 10 * min(1, min(hamming(h, x) for x in hs) / 48)
    s = {k: round(v, 2) for k, v in s.items()}
    s["overall"] = round(sum(s[k] * w for k, w in WEIGHTS.items()), 2)
    return s


VLM_SYSTEM = ("You are a senior presentation art director. Rate this slide visual 0-10: polished, flat, on-palette, no text or logos, "
              "no clichés, supports the concept. Return JSON {\"score\": number, \"issues\": [string]}.")


def vlm_score(candidate, router, concept: str = "") -> float | None:
    """Optional critic score via task type `vision_critic`; any failure -> None."""
    try:
        from ...llm import Part
        parts = [Part(f"Concept: {concept or 'abstract business visual'}", image=candidate.png)]
        schema = {"type": "object", "required": ["score"], "properties": {"score": {"type": "number"}}}
        res = router.complete_task("vision_critic", VLM_SYSTEM, parts, schema)
        v = float(res.data["score"])
        return max(0.0, min(10.0, v))
    except Exception:
        return None


def choose(cands, theme=None, router=None, concept: str = ""):
    """-> (best candidate, {candidate id: score dict}); the VLM score, when present, is blended 50/50 into `final`."""
    scores = {}
    for i, c in enumerate(cands):
        sc = score(c, theme, others=[o for j, o in enumerate(cands) if j != i])
        v = vlm_score(c, router, concept) if router is not None else None
        if v is not None:
            sc["vlm"] = v
        sc["final"] = round((sc["overall"] + v) / 2, 2) if v is not None else sc["overall"]
        scores[c.id] = sc
    best = max(cands, key=lambda c: scores[c.id]["final"])
    return best, scores
