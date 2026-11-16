"""Candidate generation: image model if the probe says so, else the SVG designer via the router, else procedural."""
from __future__ import annotations

import random
from dataclasses import dataclass

from . import procedural
from .library import ASPECTS, STYLES, palette_for

HINTS = ("off-centre focal point with a large empty margin", "symmetric, centred, calm", "diagonal movement from lower left to upper right",
         "dense cluster on one side, open space on the other", "layered depth with overlapping forms", "grid-aligned repetition with one outlier",
         "tall vertical rhythm", "wide horizontal band composition")

SVG_SYSTEM = ("You are a senior illustrator. Draw ONE finished flat vector illustration as a single SVG. Flat solid fills from the given "
              "palette only; no <text> elements, no gradients, no filters, no shadows, no images, no scripts. "
              'Return JSON: {"svg": "<svg ...>...</svg>"}.')


@dataclass
class Candidate:
    id: str
    style: str
    kind: str
    png: bytes
    svg: str | None
    source: str          # image_model | svg_designer | procedural
    prompt: str
    seed: int | None


def _prompt(style, concept, theme, hint, aspect) -> str:
    pal = palette_for(theme)
    hexes = ", ".join(pal[k] for k in ("text", "secondary", "series2", "light", "mute_bar", "panel", "accent", "background"))
    return STYLES[style].prompt.format(concept=concept, palette=hexes, composition=hint, aspect=aspect)


def _valid_svg(svg: str) -> bool:
    low = svg.lower()
    return "<text" not in low and "gradient" not in low and "<image" not in low and "<filter" not in low


def _image_model(prompt, image_status, aspect):
    client = image_status.get("client")
    if client is None:
        from ... import images
        client = images.make_image_provider(None)
    return client.generate(prompt, aspect=aspect if aspect in ("16:9", "4:3", "1:1") else "16:9")


def _svg_designer(prompt, router, size):
    from ... import images
    from ...llm import Part
    w, h = size
    res = router.complete_json("storyboard", SVG_SYSTEM, [Part(f'viewBox="0 0 {w} {h}". {prompt}')],
                               {"type": "object", "required": ["svg"], "properties": {"svg": {"type": "string"}}})
    svg = images.sanitize_svg(res.data.get("svg") or "")
    if not _valid_svg(svg):
        return None, None
    png = images.render_svg(svg)
    return (png, svg) if png else (None, None)


def candidates(concept: str, style: str, n: int = 3, *, kind: str = "illustration", theme=None, router=None,
               image_status: dict | None = None, seed: int | None = None, aspect: str = "16:9") -> list[Candidate]:
    if style not in STYLES:
        raise ValueError(f"unknown style {style!r}")
    base = random.SystemRandom().randrange(2 ** 31) if seed is None else seed
    hints = random.Random(base).sample(HINTS, min(n, len(HINTS)))
    size = ASPECTS.get(aspect, ASPECTS["16:9"])
    out: list[Candidate] = []

    def add(i, png, svg, source, prompt, s):
        out.append(Candidate(f"{style}-{source[:3]}-{base}-{i}", style, kind, png, svg, source, prompt, s))

    for i in range(n):
        s = base + i * 7919
        prompt = _prompt(style, concept, theme, hints[i % len(hints)], aspect) + f" Variation {i + 1} of {n}."
        if image_status and image_status.get("available"):
            try:
                add(i, _image_model(prompt, image_status, aspect), None, "image_model", prompt, s)
                continue
            except Exception:
                pass
        if router is not None:
            try:
                png, svg = _svg_designer(prompt + " " + STYLES[style].svg_rules, router, size)
                if png:
                    add(i, png, svg, "svg_designer", prompt, s)
                    continue
            except Exception:   # ReplayMiss, LLMError, ImageError, anything the adapter raises: fall through
                pass
        png, svg, s = procedural.render(style, seed=s, aspect=aspect, theme=theme)
        add(i, png, svg, "procedural", prompt, s)
    return out
