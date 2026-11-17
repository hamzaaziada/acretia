"""House frame and shared helpers for archetypes: title, rules, subtitle, source, footer, figure emphasis, fit, RTL."""
from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING

from om import house
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
from om.deck.theme import CANVAS_W, MARGIN_X, SIZES, grid_x, grid_w

if TYPE_CHECKING:
    from om.deck.archetypes import BuildContext

G = house.GRID
FULL_W = round(CANVAS_W - 2 * MARGIN_X, 2)

_NUM = r"\d[\d,]*(?:\.\d+)?"
_FIGURE = re.compile(
    rf"[+\-−]?[$€£]\s?{_NUM}(?:\s?(?:bn|mm|m|k|billion|million|trillion|thousand)\b)?"
    rf"|[+\-−]?{_NUM}\s?%"
    rf"|[+\-−]?{_NUM}\s?(?:bps?|pp|pts)\b"
    rf"|{_NUM}x\b"
    rf"|{_NUM}\s?(?:bn|mm|billion|million|trillion|years?|months?|days?|quarters?)\b"
)
_LEAD = re.compile(r"^([^:\n]{1,40}:)(\s|$)")


def figure_runs(text: str, *, color: str | None = None) -> list[Run]:
    """Bold the lead-in label and key figures; leave the rest regular."""
    spans: list[tuple[str, bool]] = []
    rest = text
    m = _LEAD.match(text)
    if m:
        spans.append((m.group(1), True))
        rest = text[len(m.group(1)):]
    pos = 0
    for f in _FIGURE.finditer(rest):
        if f.start() > pos:
            spans.append((rest[pos:f.start()], False))
        spans.append((f.group(0), True))
        pos = f.end()
    if pos < len(rest):
        spans.append((rest[pos:], False))
    merged: list[list] = []
    for t, b in spans:
        if merged and merged[-1][1] == b:
            merged[-1][0] += t
        else:
            merged.append([t, b])
    return [Run(t, b, color) for t, b in merged if t]


def declare(meta: dict, value, *paths: str) -> None:
    """Record a figure the archetype computed (median, total, CAGR, implied value) in `meta["derived"]` so provenance
    counts it as sourced: {"value": v, "from": [json paths of the inputs]} (D-S3-11)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        meta.setdefault("derived", []).append({"value": float(value), "from": list(paths)})


def eid(ctx: "BuildContext", role: str, suffix: str | int | None = None) -> str:
    return f"s{ctx.index}.{role}" + (f".{suffix}" if suffix not in (None, "") else "")


def text_el(ctx: "BuildContext", role: str, suffix, x: float, y: float, w: float, h: float, paras: list[Para],
            size: float, *, font: str = "minor", color: str = "text", valign: str = "t", inset: float = 0.0,
            fill: str | None = None, line: tuple[str, float] | None = None, kind: str = "text") -> Element:
    return Element(eid(ctx, role, suffix), kind, role, round(x, 2), round(y, 2), round(w, 2), round(h, 2),
                   text=TextSpec(paras, size, font, color, valign, inset), fill=fill, line=line)


def line_el(ctx: "BuildContext", role: str, y: float, token: str = "text", width: float = house.RULE_PT) -> Element:
    return Element(eid(ctx, role), "line", role, MARGIN_X, round(y, 2), FULL_W, 0.0, line=(token, width))


def fitted(paras: list[Para], w: float, h: float, *, size: float, floor: float, role: str, block_id: str,
           inset: float = 0.0, meta: dict | None = None) -> tuple[list[Para], float]:
    """Fit text through om.deck.fit.fit_text; without it keep the given size and record meta['fit']."""
    meta = meta if meta is not None else {}
    try:
        fit = importlib.import_module("om.deck.fit")
    except ImportError:
        meta["fit"] = "unavailable"
        return paras, size
    res = fit.fit_text(paras, w, h, size=size, floor=floor, role=role, block_id=block_id, inset=inset)
    if not res.ok:
        meta.setdefault("fit_errors", []).append(getattr(res.error, "message", str(res.error)))
    return res.paras, res.size


def content_box(ctx: "BuildContext", has_subtitle: bool = False) -> tuple[float, float, float, float]:
    top = G["content_top"] if has_subtitle else round(G["title_rule_y"] + 0.25, 2)
    return MARGIN_X, top, FULL_W, round(G["content_bottom"] - top, 2)


def subtitle_runs(text: str) -> list[Run]:
    head, sep, tail = text.partition(",")
    return [Run(head, True)] + ([Run(sep + tail)] if sep else [])


def _subtitle_text(slide: dict) -> str:
    b = slide.get("blocks") or {}
    return b.get("subtitle") or b.get("measure") or slide.get("measure") or ""


def has_subtitle(slide: dict) -> bool:
    return bool(_subtitle_text(slide))


def _source_text(slide: dict) -> str:
    """`Source: A; as of D`, or with a `sources` list `Source: [1] A; [2] B; as of D` (citations, #19)."""
    srcs, as_of = slide.get("sources"), slide.get("as_of")
    parts = []
    if isinstance(srcs, (list, tuple)) and srcs:
        parts.append("Source: " + "; ".join(f"[{i}] {str(t).rstrip('.')}" for i, t in enumerate(srcs, 1)))
    elif slide.get("source"):
        src = slide["source"]
        parts.append(src if src.lower().startswith("source") else f"Source: {src}")
    if as_of:
        parts.append(f"as of {as_of}")
    return "; ".join(parts)


def footer_elements(ctx: "BuildContext", *, page_number: bool = True) -> list[Element]:
    els = [line_el(ctx, "footer_rule", G["footer_rule_y"])]
    note = SIZES["note"]
    els.append(text_el(ctx, "footer", None, grid_x(0), G["footer_y"], grid_w(9), 0.3,
                       [Para([Run(ctx.deck_title)], space_after=0)], note, color="muted"))
    if page_number:
        els.append(text_el(ctx, "page_number", None, grid_x(11), G["footer_y"], grid_w(1), 0.3,
                           [Para([Run(str(ctx.index))], align="r", space_after=0)], note, color="muted"))
    return els


def frame(slide: dict, ctx: "BuildContext", *, mode: str = "content", meta: dict | None = None) -> list[Element]:
    """House frame. mode: content (full), divider (footer rule + page number), cover (footer rule only)."""
    if mode != "content":
        return footer_elements(ctx, page_number=mode != "cover")
    meta = meta if meta is not None else {}
    els: list[Element] = []
    paras = [Para([Run(slide.get("title", ""), b=True)], space_after=0)]
    paras, size = fitted(paras, FULL_W, G["title_h"], size=SIZES["title"], floor=20, role="title",
                         block_id="title", meta=meta)
    els.append(text_el(ctx, "title", None, MARGIN_X, G["title_y"], FULL_W, G["title_h"], paras, size, font="major"))
    els.append(line_el(ctx, "title_rule", G["title_rule_y"]))
    sub = _subtitle_text(slide)
    if sub:
        els.append(text_el(ctx, "subtitle", None, MARGIN_X, G["subtitle_y"], FULL_W, 0.35,
                           [Para(subtitle_runs(sub), space_after=0)], SIZES["body"]))
    src = _source_text(slide)
    if src:
        paras, size = fitted([Para([Run(src)], space_after=0)], FULL_W, 0.4, size=SIZES["note"], floor=SIZES["note"],
                             role="source", block_id="source", meta=meta)
        els.append(text_el(ctx, "source", None, MARGIN_X, G["note_y"], FULL_W, 0.4, paras, size, color="muted"))
    return els + footer_elements(ctx)


def solved(slide: dict, ctx: "BuildContext", archetype: str, visual_type: str, elements: list[Element],
           meta: dict | None = None) -> SolvedSlide:
    out = SolvedSlide(ctx.index, archetype, elements, rtl=False, notes=slide.get("notes", ""),
                      visual_type=visual_type, meta=meta or {})
    return mirror(out, ctx) if ctx.rtl else out


def mirror(slide: SolvedSlide, ctx: "BuildContext") -> SolvedSlide:
    """Mirror for RTL via om.deck.rtl.mirror; fall back to a plain x flip when the module is absent."""
    try:
        rtl = importlib.import_module("om.deck.rtl")
    except ImportError:
        rtl = None
    if rtl is not None:
        out = rtl.mirror(slide)
        out.rtl = True
        return out
    for el in slide.elements:
        el.x = round(CANVAS_W - el.x - el.w, 2)
        if el.text:
            for p in el.text.paras:
                p.align = {"l": "r", "r": "l"}.get(p.align, p.align)
    slide.rtl = True
    slide.meta["rtl_mirror"] = "fallback"
    return slide
