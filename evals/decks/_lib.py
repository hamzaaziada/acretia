"""Authoring helpers shared by the corpus and the reliability generator.

`S(...)` describes one slide; `make_brief(...)` turns a list of slides into
`{brief, ghost, spec}`: a banker's request, an approved ghost deck (storyline) and a DeckSpec v2.
All figures in the corpus are synthetic and the source lines say so (D-S3-11: every prose number
must exist in a sourced data block of the same deck)."""
from __future__ import annotations

import re

STRUCTURAL = {"cover", "section_divider", "appendix_divider", "agenda", "quote"}
NO_SOURCE = {"cover", "section_divider", "appendix_divider", "agenda", "quote"}
APPROVED_AT = "2026-11-17T00:00:00+00:00"


def S(arch: str, title: str, blocks: dict | None = None, *, src=None, sec: str = "", visual=None, why: str = "",
      cite: bool = True) -> dict:
    """One slide. `src` is a source name or a tuple of source names (-> `sources`, `[1]` marker on the takeaway)."""
    return {"arch": arch, "title": title, "blocks": blocks or {}, "src": src, "sec": sec, "visual": visual,
            "why": why, "cite": cite}


def _cite(blocks: dict, n: int) -> dict:
    b = dict(blocks)
    for k in ("takeaway", "so_what"):
        v = b.get(k)
        if isinstance(v, str) and v and not re.search(r"\[\d\]", v):
            b[k] = v.rstrip(". ") + " [1]"
            break
    return b


def make_brief(slug: str, deck_title: str, request: str, slides: list[dict], *, lang: str = "en", client: str = "",
               as_of: str = "2026-10-31", art: str = "auto", src: str = "Illustrative data room (synthetic)") -> dict:
    from om.deck import ghost as G
    out, sec, ghost_slides = [], "", []
    sections: list[str] = []
    for i, s in enumerate(slides, 1):
        arch = s["arch"]
        sec = s["sec"] or sec or "Storyline"
        if sec not in sections:
            sections.append(sec)
        sl = {"id": f"s{i}", "archetype": arch, "title": s["title"]}
        blocks = s["blocks"]
        if arch not in NO_SOURCE:
            srcs = s["src"]
            if isinstance(srcs, (tuple, list)):
                sl["source"] = "; ".join(srcs)
                sl["sources"] = list(srcs)
                if s["cite"]:
                    blocks = _cite(blocks, len(srcs))
            else:
                sl["source"] = srcs or src
            sl["as_of"] = as_of
        sl["blocks"] = blocks
        if s["visual"]:
            sl["visual"] = {"concept": s["visual"][0], "kind": s["visual"][1]}
        sl["notes"] = s["why"] or f"Evidence slide {i}: {s['title'][:60]}"
        out.append(sl)
        hint = {"appendix_divider": "appendix"}.get(arch, arch)
        ghost_slides.append(G.GhostSlide(id=sl["id"], title=s["title"], section=sec, archetype_hint=hint,
                                         purpose=sl["notes"]))
    g = G.GhostDeck(deck_id=slug, brief=request, lang=lang, slides=ghost_slides, sections=sections)
    g.lint = G.lint(g)
    G.approve(g, "eval-corpus")
    g.approved_at = APPROVED_AT
    spec = {"deck_id": slug, "title": deck_title, "lang": lang, "client": client, "as_of": as_of,
            "art_direction": art, "theme": "house", "slides": out}
    return {"brief": request, "ghost": g.to_dict(), "spec": spec}
