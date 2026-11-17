"""Core archetypes (cover, section_divider, chart_takeaways) and the shared building blocks of the text archetypes.

Geometry comes only from the 12-column grid. Shared helpers (`tx`, `rect`, `hline`, `vline`, `art`, `row_cols`, ...)
are used by `text.py`; text that cannot fit raises `FitFailure` so the content step can cut or split.
"""
from __future__ import annotations

from om import house
from om.deck.archetypes import BuildContext, register
from om.deck.archetypes import base
from om.deck.model import Element, Para, Run
from om.deck.theme import CANVAS_H, CANVAS_W, MARGIN_X, SIZES, grid_w, grid_x

G = house.GRID

_CHART_TYPES = ["bar", "column", "stacked_bar", "stacked_column", "line", "area", "scatter", "pie", "doughnut",
                "waterfall", "football_field", "combo"]
_CHART_SCHEMA = {
    "type": "object", "required": ["type", "categories", "series"],
    "properties": {
        "type": {"enum": _CHART_TYPES},
        "categories": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "series": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["name", "values"],
            "properties": {"name": {"type": "string"},
                           "values": {"type": "array", "items": {"type": ["number", "null"]}}}}},
        "number_format": {"type": "string"}, "labels": {"type": "boolean"}, "legend": {"type": "boolean"},
        "axis_title": {"type": "string"}, "highlight": {"type": "array", "items": {"type": "integer"}},
        "totals": {"type": "array", "items": {"type": "integer"}},
    },
}

_FLOORS = {44: 32, 40: 32, 32: 24, 24: 20}


# ---------------------------------------------------------------- shared building blocks
class FitFailure(ValueError):
    """Text does not fit its box at the size floor; the content step must cut or split."""


def tx(ctx: BuildContext, meta: dict, role: str, suffix, x: float, y: float, w: float, h: float, paras: list[Para],
       size: float, *, floor: float | None = None, font: str = "minor", color: str = "text", valign: str = "t",
       inset: float = 0.0, fill: str | None = None, line: tuple[str, float] | None = None) -> Element:
    """Fitted text element; a filled one becomes a `rect` that carries its own text."""
    fl = floor if floor is not None else _FLOORS.get(int(size), 12 if size >= 14 else size)
    block = f"{role} {suffix}" if suffix not in (None, "") else role
    local: dict = {}
    paras, sz = base.fitted(paras, w, h, size=size, floor=fl, role=role, block_id=block, inset=inset, meta=local)
    if local.get("fit_errors"):
        raise FitFailure(local["fit_errors"][0])
    if "fit" in local:
        meta["fit"] = local["fit"]
    return base.text_el(ctx, role, suffix, x, y, w, h, paras, sz, font=font, color=color, valign=valign, inset=inset,
                        fill=fill, line=line, kind="rect" if fill else "text")


def para(text: str, *, b: bool = False, color: str | None = None, align: str = "l", after: float = 0,
         figures: bool = True, bullet: bool = False) -> Para:
    runs = base.figure_runs(text, color=color) if figures and not b else [Run(text, b, color)]
    return Para(runs, align=align, space_after=after, bullet=bullet)


def rect(ctx: BuildContext, role: str, suffix, x: float, y: float, w: float, h: float, fill: str,
         line: tuple[str, float] | None = None) -> Element:
    return Element(base.eid(ctx, role, suffix), "rect", role, round(x, 2), round(y, 2), round(w, 2), round(h, 2),
                   fill=fill, line=line)


def hline(ctx: BuildContext, role: str, suffix, x: float, y: float, w: float, token: str = "mute_bar",
          width: float = house.RULE_PT) -> Element:
    return Element(base.eid(ctx, role, suffix), "line", role, round(x, 2), round(y, 2), round(w, 2), 0.0,
                   line=(token, width))


def vline(ctx: BuildContext, role: str, suffix, x: float, y: float, h: float, token: str = "mute_bar",
          width: float = house.RULE_PT) -> Element:
    return Element(base.eid(ctx, role, suffix), "line", role, round(x, 2), round(y, 2), 0.0, round(h, 2),
                   line=(token, width))


def cols(a: int, b: int) -> tuple[float, float]:
    """(x, w) of the column span a..b inclusive."""
    return grid_x(a), grid_w(b - a + 1)


def row_cols(n: int) -> list[tuple[float, float]]:
    """Equal column spans for n blocks in a row; five blocks use two columns each, centred."""
    if n == 5:
        return [(grid_x(1 + 2 * i), grid_w(2)) for i in range(5)]
    span = 12 // n
    if span * n != 12:
        raise ValueError(f"cannot split 12 columns into {n} equal blocks")
    return [(grid_x(span * i), grid_w(span)) for i in range(n)]


def area(slide: dict, ctx: BuildContext) -> tuple[float, float]:
    """(y, h) of the content area under the title (and subtitle when there is one)."""
    _, y, _, h = base.content_box(ctx, base.has_subtitle(slide))
    return y, h


def need(b: dict, aid: str, *keys: str) -> None:
    for k in keys:
        if k not in b:
            raise ValueError(f"{aid}: blocks.{k} is required")


def art(ctx: BuildContext, slide: dict, x: float, y: float, w: float, h: float, role: str = "visual") -> Element | None:
    """Image element from `ctx.visual` ({png, alt, style}); None when there is no visual. Alt text is always set."""
    v = ctx.visual
    if not v or not v.get("png"):
        return None
    alt = v.get("alt") or f"Illustration for {slide.get('title') or ctx.deck_title}"
    return Element(base.eid(ctx, role), "image", role, round(x, 2), round(y, 2), round(w, 2), round(h, 2),
                   image={"png": v["png"], "alt": alt, "style": v.get("style", ""),
                          "candidate_id": v.get("candidate_id", "")})


def short_footer(ctx: BuildContext, span: int, page_number: bool) -> list[Element]:
    """Footer limited to the first `span` columns, for slides whose right side is a full-bleed visual."""
    note = SIZES["note"]
    text_span = span - 1 if page_number else span
    els = [hline(ctx, "footer_rule", None, MARGIN_X, G["footer_rule_y"], grid_w(span), "text"),
           base.text_el(ctx, "footer", None, grid_x(0), G["footer_y"], grid_w(text_span), 0.3,
                        [Para([Run(ctx.deck_title)], space_after=0)], note, color="muted")]
    if page_number:
        els.append(base.text_el(ctx, "page_number", None, grid_x(span - 1), G["footer_y"], grid_w(1), 0.3,
                                [Para([Run(str(ctx.index))], align="r", space_after=0)], note, color="muted"))
    return els


# ---------------------------------------------------------------- cover
@register("cover", visual_type="cover", schema={
    "type": "object", "additionalProperties": False,
    "properties": {"client": {"type": "string"}, "date": {"type": "string"}}})
def build_cover(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    meta: dict = {}
    title = slide.get("title") or ctx.deck_title
    pic = art(ctx, slide, grid_x(7), 0.0, round(CANVAS_W - grid_x(7), 2), CANVAS_H)
    w = grid_w(6) if pic else grid_w(10)
    els: list[Element] = []
    if pic:
        els.append(pic)
    els.append(rect(ctx, "decor", "bar", grid_x(0), 2.0, 0.9, 0.08, "accent"))
    els.append(tx(ctx, meta, "cover", None, grid_x(0), 2.35, w, 2.3, [Para([Run(title, b=True)], space_after=0)],
                  SIZES["cover"], font="major"))
    line = " | ".join(x for x in (b.get("client"), b.get("date") or slide.get("as_of")) if x)
    if line:
        els.append(tx(ctx, meta, "cover", "sub", grid_x(0), 4.85, w, 0.5, [Para([Run(line)], space_after=0)],
                      SIZES["body"], color="muted"))
    els += short_footer(ctx, 6, False) if pic else base.frame(slide, ctx, mode="cover")
    return base.solved(slide, ctx, "cover", "cover", els, meta)


# ---------------------------------------------------------------- section divider
@register("section_divider", visual_type="divider", schema={
    "type": "object", "additionalProperties": False, "properties": {"number": {"type": ["string", "integer"]}}})
def build_divider(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    meta: dict = {}
    pic = art(ctx, slide, grid_x(7), 0.0, round(CANVAS_W - grid_x(7), 2), CANVAS_H)
    w = grid_w(6) if pic else grid_w(10)
    els: list[Element] = [pic] if pic else []
    if b.get("number") not in (None, ""):
        num = f"{int(b['number']):02d}" if str(b["number"]).isdigit() else str(b["number"])
        els.append(tx(ctx, meta, "divider", "num", grid_x(0), 2.2, w, 0.7,
                      [Para([Run(num, b=True, color="accent")], space_after=0)], SIZES["divider"], font="major",
                      valign="b"))
    els.append(tx(ctx, meta, "divider", None, grid_x(0), 2.9, w, 1.9,
                  [Para([Run(slide.get("title", ""), b=True)], space_after=0)], SIZES["divider"], font="major"))
    els += short_footer(ctx, 6, True) if pic else base.frame(slide, ctx, mode="divider")
    return base.solved(slide, ctx, "section_divider", "divider", els, meta)


# ---------------------------------------------------------------- chart + three takeaways
@register("chart_takeaways", data=True, visual_type="chart", schema={
    "type": "object", "required": ["chart", "takeaways"], "additionalProperties": False,
    "properties": {"chart": _CHART_SCHEMA,
                   "takeaways": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                   "subtitle": {"type": "string"}, "measure": {"type": "string"}, "binding": {"type": "object"}}})
def build_chart_takeaways(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    need(b, "chart_takeaways", "chart", "takeaways")
    if len(b["takeaways"]) != 3:
        raise ValueError("chart_takeaways: exactly 3 takeaways required")
    meta: dict = {}
    els = base.frame(slide, ctx, meta=meta)
    x, y, w, h = base.content_box(ctx, base.has_subtitle(slide))
    chart = {"number_format": "0.0", "labels": True, "gridlines": False, "legend": False, **b["chart"]}
    els.append(Element(base.eid(ctx, "chart"), "chart", "chart", grid_x(0), y, grid_w(8), h, chart=chart,
                       binding=b.get("binding")))
    tx0, tw, gap = grid_x(8), grid_w(4), ctx.gap
    bw = grid_w(1)
    th = round((h - 2 * gap) / 3, 2)
    for i, text in enumerate(b["takeaways"]):
        cy = round(y + i * (th + gap), 2)
        els.append(rect(ctx, "panel", i + 1, tx0, cy, tw, th, "panel"))
        els.append(tx(ctx, meta, "badge", i + 1, tx0, cy, bw, th, [Para([Run(str(i + 1), b=True, color="background")],
                      align="c", space_after=0)], SIZES["title"], font="major", valign="m", fill="accent"))
        els.append(tx(ctx, meta, "callout", i + 1, grid_x(9), cy, grid_w(3), th, [para(text)], SIZES["body"],
                      valign="m", inset=0.15))
    return base.solved(slide, ctx, "chart_takeaways", chart["type"], els, meta)


EXAMPLES = {
    "cover": {"title": "Project Atlas: carve-out of the payments unit", "as_of": "2026-11-16",
              "blocks": {"client": "Board of Directors, Acme Bank", "date": "16 November 2026"}},
    "section_divider": {"title": "Valuation and returns", "blocks": {"number": 3}},
    "chart_takeaways": {
        "title": "EBITDA is flat as price gains offset volume and cost drag", "source": "Company filings",
        "as_of": "2026-09-30",
        "blocks": {"subtitle": "EBITDA bridge, FY25 to FY26, $ million",
                   "chart": {"type": "waterfall", "categories": ["FY25", "Price", "Volume", "Cost", "FY26"],
                             "series": [{"name": "EBITDA", "values": [100, 12, -8, -4, 100]}]},
                   "takeaways": ["Price: +$12m from list increases", "Volume: -$8m, mostly Q3 destocking",
                                 "Cost: 4.0% inflation absorbed by savings"]}},
}
