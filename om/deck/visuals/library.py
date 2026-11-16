"""Visual-language library: styles, prompt templates, SVG-designer rules, learned weights and art-direction choice."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

PRIOR_SCORE, PRIOR_WEIGHT = 7.0, 3
RETIRE_RUNS, RETIRE_BELOW = 5, 6.0
KINDS = ("illustration", "hero", "diagram", "icon_system")
ASPECTS = {"16:9": (1600, 900), "1:1": (900, 900), "3:2": (1200, 800), "4:3": (1200, 900)}
NEG = "no text, no letters, no logos, flat vector look, no gradients, no shadows, no 3D, no stock-photo clichés"
PALETTE_USE = "accent colour sparingly (at most 15% of painted area, one focal element); greys and secondary blue carry the rest"


@dataclass(frozen=True)
class Style:
    id: str
    description: str
    prompt: str
    svg_rules: str
    kinds: tuple[str, ...]
    aspects: tuple[str, ...] = ("16:9", "3:2", "1:1")
    palette_use: str = PALETTE_USE
    extra: dict = field(default_factory=dict, hash=False, compare=False)


def _s(id, description, look, svg, kinds, aspects=("16:9", "3:2", "1:1")) -> Style:
    prompt = (f"{look} Subject / concept: {{concept}}. Composition: {{composition}}. Palette (hex, flat fills only): {{palette}}; "
              f"{PALETTE_USE}. Aspect {{aspect}}. {NEG}.")
    return Style(id, description, prompt, svg + " Flat fills only, no <text>, no gradients/filters, palette colours only.", kinds, aspects)


STYLES: dict[str, Style] = {s.id: s for s in (
    _s("editorial_illustration", "Flat editorial illustration: big overlapping shapes, confident negative space.",
       "Flat editorial illustration in the style of a business magazine, abstract large overlapping geometric forms.",
       "Compose 4-7 large overlapping organic and geometric shapes with generous white space.", ("illustration", "hero")),
    _s("isometric_system", "Isometric blocks and stacks showing a system.",
       "Clean isometric illustration of stacked blocks and platforms showing a system, orthographic 30 degree view.",
       "Draw isometric cubes in a grid with varied stack heights; top/left/right faces in three tones.", ("illustration", "diagram", "hero")),
    _s("line_art_schematic", "Line-art flow schematic with nodes and elbow connectors.",
       "Precise line-art schematic of nodes connected by orthogonal lines with arrowheads, light panel fills.",
       "Draw rounded-rectangle nodes in columns joined by elbow connectors with arrowheads; thin consistent strokes.", ("diagram", "illustration"),
       ("16:9", "3:2")),
    _s("data_art", "Data art: dot fields, flow ribbons, radial bars generated from a seed.",
       "Abstract data-art composition: dot fields, flowing ribbons or radial bars, no axes, no labels.",
       "Draw a dot field with varying radii, or layered flow ribbons, or radial bars around a centre.", ("hero", "illustration")),
    _s("duotone_hero", "Duotone abstract hero made of overlapping flat shapes in two tones.",
       "Duotone photo-style hero rendered as flat abstract overlapping shapes in two tones plus one small accent.",
       "Overlap circles, arches and rectangles using two tones and one small accent element.", ("hero", "illustration"), ("16:9", "3:2")),
    _s("annotated_map", "Abstract annotated map: regions, pins and a route (no real geography).",
       "Abstract map-like tiling of regions with pins and a dashed route; invented geography, no place names.",
       "Tile an inset rectangle with irregular regions in three light tones, add pins and a dashed route.", ("diagram", "illustration", "hero")),
    _s("iconographic_system", "Geometric icon system: a consistent glyph set on tiles.",
       "A consistent set of geometric icons on square tiles: rings, bars, triangles, diamonds, plus signs.",
       "Draw a 3x2 or 4x2 grid of tiles each with a geometric glyph built from circles, rects, triangles.", ("icon_system", "diagram"), ("16:9", "3:2")),
    _s("bold_typographic", "Bold typographic forms: numerals built as shapes, never words.",
       "Bold graphic composition of huge segmented numeral shapes used as pure forms, no readable words.",
       "Build large seven-segment style numerals from rectangles (lit and ghost segments); no text elements.", ("hero", "illustration")),
)}


def palette_for(theme=None) -> dict[str, str]:
    """Flat palette (token -> hex) from a theme (dict / object with .colors) or the house palette."""
    from ... import house
    pal = dict(house.PALETTE)
    src = theme if isinstance(theme, dict) else (getattr(theme, "colors", None) or getattr(theme, "palette", None) or {}) if theme else {}
    for k, v in (src.items() if isinstance(src, dict) else ()):
        if isinstance(v, str) and v.startswith("#") and len(v) == 7:
            pal[k] = v.upper()
    return pal


def _read(log_path):
    from . import log
    try:
        return log.read(log_path)
    except OSError:
        return []


def weights(log_path=None) -> dict[str, dict]:
    """Per style: Bayesian mean of logged scores (prior 7.0, weight 3), run count, retired flag."""
    from . import log
    sums: dict[str, list[float]] = {}
    for row in _read(log_path):
        v = log.entry_score(row)
        if v is not None and row.get("style"):
            sums.setdefault(row["style"], []).append(v)
    out = {}
    for sid in STYLES:
        xs = sums.get(sid, [])
        n = len(xs)
        raw = sum(xs) / n if n else None
        out[sid] = {"score": (PRIOR_SCORE * PRIOR_WEIGHT + sum(xs)) / (PRIOR_WEIGHT + n), "runs": n, "mean": raw,
                    "retired": n >= RETIRE_RUNS and raw is not None and raw < RETIRE_BELOW}
    return out


def _wanted_kinds(deck_spec) -> set[str]:
    get = (lambda o, k: o.get(k) if isinstance(o, dict) else getattr(o, k, None))
    kinds = set(get(deck_spec, "visual_kinds") or [])
    for s in get(deck_spec, "slides") or []:
        for k in ("visual_kind", "kind"):
            v = get(s, k)
            if v:
                kinds.add(v)
        v = get(s, "visual")
        if v and get(v, "kind"):
            kinds.add(get(v, "kind"))
    return {k for k in kinds if k in KINDS}


def choose_art_direction(deck_spec, *, rng: random.Random | None = None, log_path=None) -> str:
    """Pick the deck's visual language: explicit `art_direction` wins; otherwise weighted-random over non-retired styles."""
    rng = rng or random.Random()
    explicit = deck_spec.get("art_direction") if isinstance(deck_spec, dict) else getattr(deck_spec, "art_direction", None)
    if explicit and explicit != "auto" and explicit in STYLES:
        return explicit
    w = weights(log_path)
    live = [s for s in STYLES if not w[s]["retired"]] or list(STYLES)
    want = _wanted_kinds(deck_spec)
    suited = [s for s in live if not want or want & set(STYLES[s].kinds)] or live
    return rng.choices(suited, weights=[max(w[s]["score"], 0.1) ** 2 for s in suited], k=1)[0]
