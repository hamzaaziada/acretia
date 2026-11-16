"""Core archetypes that prove the path: cover, section_divider, chart_takeaways."""
from __future__ import annotations

from om.deck.archetypes import BuildContext, register
from om.deck.archetypes import base
from om.deck.model import Element, Para, Run
from om.deck.theme import SIZES, grid_w, grid_x
from om import house

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


@register("cover", visual_type="cover", schema={
    "type": "object", "additionalProperties": False,
    "properties": {"client": {"type": "string"}, "date": {"type": "string"}}})
def build_cover(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    meta: dict = {}
    title = slide.get("title") or ctx.deck_title
    w = grid_w(10)
    paras, size = base.fitted([Para([Run(title, b=True)], space_after=0)], w, 2.0, size=SIZES["cover"], floor=32,
                              role="cover", block_id="cover", meta=meta)
    els = [base.text_el(ctx, "cover", None, grid_x(0), 2.3, w, 2.0, paras, size, font="major", valign="b")]
    line = " | ".join(x for x in (b.get("client"), b.get("date") or slide.get("as_of")) if x)
    if line:
        els.append(base.text_el(ctx, "cover", "sub", grid_x(0), 4.5, w, 0.5, [Para([Run(line)], space_after=0)],
                                SIZES["body"], color="muted"))
    return base.solved(slide, ctx, "cover", "cover", els + base.frame(slide, ctx, mode="cover"), meta)


@register("section_divider", visual_type="divider", schema={
    "type": "object", "additionalProperties": False, "properties": {"number": {"type": ["string", "integer"]}}})
def build_divider(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    meta: dict = {}
    w = grid_w(10)
    paras, size = base.fitted([Para([Run(slide.get("title", ""), b=True)], space_after=0)], w, 1.6,
                              size=SIZES["divider"], floor=32, role="divider", block_id="divider", meta=meta)
    els = []
    top = 2.9
    if b.get("number") not in (None, ""):
        els.append(base.text_el(ctx, "divider", "num", grid_x(0), 2.2, w, 0.7,
                                [Para([Run(f"{int(b['number']):02d}" if str(b["number"]).isdigit() else str(b["number"]),
                                           b=True, color="accent")], space_after=0)],
                                SIZES["divider"], font="major", valign="b"))
    els.append(base.text_el(ctx, "divider", None, grid_x(0), top, w, 1.6, paras, size, font="major"))
    return base.solved(slide, ctx, "section_divider", "divider", els + base.frame(slide, ctx, mode="divider"), meta)


@register("chart_takeaways", data=True, visual_type="chart", schema={
    "type": "object", "required": ["chart", "takeaways"], "additionalProperties": False,
    "properties": {"chart": _CHART_SCHEMA,
                   "takeaways": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                   "subtitle": {"type": "string"}, "measure": {"type": "string"}, "binding": {"type": "object"}}})
def build_chart_takeaways(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    for key in ("chart", "takeaways"):
        if key not in b:
            raise ValueError(f"chart_takeaways: blocks.{key} is required")
    if len(b["takeaways"]) != 3:
        raise ValueError("chart_takeaways: exactly 3 takeaways required")
    meta: dict = {}
    els = base.frame(slide, ctx, meta=meta)
    x, y, w, h = base.content_box(ctx, base.has_subtitle(slide))
    chart = {"number_format": "0.0", "labels": True, "gridlines": False, "legend": False, **b["chart"]}
    cw = grid_w(8)
    els.append(Element(base.eid(ctx, "chart"), "chart", "chart", grid_x(0), y, cw, h, chart=chart,
                       binding=b.get("binding")))
    tx, tw, gap = grid_x(8), grid_w(4), ctx.gap
    th = round((h - 2 * gap) / 3, 2)
    for i, text in enumerate(b["takeaways"]):
        paras = [Para([Run(f"{i + 1}  ", b=True, color="accent")] + base.figure_runs(text), space_after=0)]
        paras, size = base.fitted(paras, tw - 0.4, th - 0.4, size=SIZES["body"], floor=12, role="callout",
                                  block_id=f"takeaway {i + 1}", inset=0.2, meta=meta)
        els.append(base.text_el(ctx, "callout", i + 1, tx, y + i * (th + gap), tw, th, paras, size,
                                valign="m", inset=0.2, fill="panel", kind="rect"))
    return base.solved(slide, ctx, "chart_takeaways", chart["type"], els, meta)
