"""Chart archetypes (S3.3b): native, data-bound charts with a so-what panel, direct labels and no legends.

Every archetype returns a house frame (title, rule, subtitle with the measure in bold, source and as-of line, footer),
one native chart (or a row of them) on the 12-column grid and a side panel (badge, stat callouts, colour key,
takeaway). Code owns the numbers (sorting, shares, bridge deltas, medians, badges, axis scales and the overlay
positions that depend on them); the renderer owns label contrast. A block may carry a ModelManifest `binding`
(on the block or on a series) which becomes the chart element's `binding` so S3.9 sync can re-bind it.
"""
from __future__ import annotations

import math
import statistics

from om import house
from om.deck.archetypes import BuildContext, register
from om.deck.archetypes import base, core
from om.deck.model import Element, Para, Run
from om.deck.render import MINUS, fmt_number
from om.deck.theme import SIZES, grid_w, grid_x

G = house.GRID
BODY = SIZES["body"]
KEY_ROW_H = 0.36
BADGE_H = 0.55
STAT_H, STAT_LABEL_H = 0.7, 0.55
_PART_TOKENS = ["secondary", "muted", "mute_bar", "light"]


# ---------------------------------------------------------------- schema helpers
def _schema(props: dict, required: list[str]) -> dict:
    common = {"subtitle": {"type": "string", "minLength": 1}, "takeaway": {"type": "string", "minLength": 1},
              "binding": {"type": ["string", "object"]}}
    return {"type": "object", "additionalProperties": False, "required": ["subtitle", "takeaway", *required],
            "properties": {**common, **props}}


_NUM = {"type": "number"}
_NF = {"type": "string"}
_STAT = {"type": "object", "additionalProperties": False, "required": ["value", "label"],
         "properties": {"value": {"type": "string", "maxLength": 9}, "label": {"type": "string", "maxLength": 70}}}
_BIND = {"binding": {"type": "string"}}


def _strs(lo: int, hi: int, maxlen: int = 40) -> dict:
    return {"type": "array", "minItems": lo, "maxItems": hi, "items": {"type": "string", "maxLength": maxlen}}


# ---------------------------------------------------------------- shared building blocks
def _begin(slide: dict, ctx: BuildContext, aid: str, *required: str):
    b = slide.get("blocks") or {}
    core.need(b, aid, "subtitle", "takeaway", *required)
    if not slide.get("source") or not slide.get("as_of"):
        raise ValueError(f"{aid}: data slides need source and as_of")
    meta: dict = {}
    els = base.frame(slide, ctx, meta=meta)
    if meta.get("fit_errors"):
        raise core.FitFailure(meta["fit_errors"][0])
    _, y, _, h = base.content_box(ctx, True)
    return b, meta, els, y, h


def _binding(b: dict, *series_lists) -> dict | None:
    cand = b.get("binding")
    for lst in series_lists:
        for s in lst or []:
            if cand is None and isinstance(s, dict) and s.get("binding"):
                cand = s["binding"]
    if cand is None:
        return None
    return {"manifest_id": cand if isinstance(cand, str) else cand.get("manifest_id"), "kind": "chart"}


def _chart_el(ctx: BuildContext, suffix, x: float, y: float, w: float, h: float, spec: dict,
              binding: dict | None) -> Element:
    spec = {"gridlines": False, "legend": False, **spec}
    return Element(base.eid(ctx, "chart", suffix), "chart", "chart", round(x, 2), round(y, 2), round(w, 2),
                   round(h, 2), chart=spec, binding=binding)


def _fmt(v: float, nf: str, signed: bool = False) -> str:
    body = fmt_number(abs(v), nf)
    if signed:
        return ("+" if v >= 0 else MINUS) + body
    return (MINUS if v < 0 else "") + body


def _takeaway_runs(text: str) -> list[Run]:
    t = text if base._LEAD.match(text) else f"So what: {text}"
    return base.figure_runs(t)


def _panel(ctx: BuildContext, meta: dict, x_col: int, span: int, y: float, h: float, takeaway: str, *,
           badge: str | None = None, stats: list[dict] | None = None, key: list[tuple[str, str]] | None = None
           ) -> list[Element]:
    """Side panel: badge, stat callouts, colour key (swatch + label), then the takeaway box filling the rest."""
    x, w, gap = grid_x(x_col), grid_w(span), ctx.gap
    els: list[Element] = []
    cy = y
    if badge:
        els.append(core.tx(ctx, meta, "badge", None, x, cy, w, BADGE_H,
                           [Para([Run(badge, b=True, color="background")], align="c", space_after=0)], BODY,
                           valign="m", fill="accent", inset=0.08))
        cy += BADGE_H + gap
    for i, st in enumerate(stats or []):
        els.append(core.tx(ctx, meta, "stat", i + 1, x, cy, w, STAT_H,
                           [Para([Run(st["value"], b=True, color="accent")], space_after=0)], SIZES["stat"],
                           font="major", valign="b"))
        els.append(core.tx(ctx, meta, "stat_label", i + 1, x, cy + STAT_H, w, STAT_LABEL_H,
                           [core.para(st["label"])], BODY))
        cy += STAT_H + STAT_LABEL_H + (gap if i + 1 < len(stats or []) else 0)
    if stats:
        cy += gap
    for i, (label, token) in enumerate(key or []):
        els.append(core.tx(ctx, meta, "key", i + 1, x, cy, w, KEY_ROW_H,
                           [Para(base.figure_runs(label), level=1, space_after=0)], BODY, valign="m"))
        els.append(core.rect(ctx, "decor", f"key{i + 1}", x, cy + (KEY_ROW_H - 0.18) / 2, 0.18, 0.18, token))
        cy += KEY_ROW_H
    if key:
        cy += gap
    rem = round(y + h - cy, 2)
    if rem < 1.1:
        raise core.FitFailure(f"side panel leaves {rem} in for the takeaway; cut a stat or key row")
    els.append(core.tx(ctx, meta, "callout", "takeaway", x, cy, w, rem, [Para(_takeaway_runs(takeaway), space_after=0)],
                       BODY, valign="m", inset=0.2, fill="panel"))
    return els


def _grid_box(ctx: BuildContext, center_x: float, span: int, lo_col: int, hi_col: int, anchor: float | None = None
              ) -> tuple[float, float]:
    """(x, w) of a `span`-column box on the grid whose centre is nearest `center_x` and that covers `anchor`."""
    best = None
    for c in range(lo_col, hi_col - span + 2):
        x, w = grid_x(c), grid_w(span)
        if anchor is not None and not (x + 0.15 <= anchor <= x + w - 0.15):
            continue
        d = abs(x + w / 2 - center_x)
        if best is None or d < best[0]:
            best = (d, x, w)
    if best is None:
        c = max(lo_col, min(hi_col - span + 1, 0))
        return grid_x(c), grid_w(span)
    return best[1], best[2]


class _Plot:
    """Chart box plus its manual inner plot layout and axis scale, to place overlays exactly."""

    def __init__(self, x: float, y: float, w: float, h: float, layout: list[float], lo: float, hi: float):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.lx, self.ly, self.lw, self.lh = layout
        self.lo, self.hi = lo, hi

    def fx(self, f: float) -> float:
        return self.x + self.w * (self.lx + self.lw * f)

    def fy(self, f: float) -> float:
        return self.y + self.h * (self.ly + self.lh * f)

    def val_x(self, v: float) -> float:
        return self.fx((v - self.lo) / (self.hi - self.lo))

    def val_y(self, v: float) -> float:
        return self.fy(1 - (v - self.lo) / (self.hi - self.lo))


def _finish(slide: dict, ctx: BuildContext, aid: str, vtype: str, els: list[Element], meta: dict):
    return base.solved(slide, ctx, aid, vtype, els, meta)


def _headroom(vals, frac: float = 0.18) -> float:
    return max(v for v in vals if v is not None) * (1 + frac)


# ---------------------------------------------------------------- 1. ranked_bar
@register("ranked_bar", data=True, visual_type="bar", schema=_schema({
    "items": {"type": "array", "minItems": 3, "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "value"],
        "properties": {"label": {"type": "string", "maxLength": 34}, "value": _NUM, "key": {"type": "boolean"}}}},
    "number_format": _NF, "stat": _STAT, "series_name": {"type": "string"}}, ["items", "stat"]))
def build_ranked_bar(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "ranked_bar", "items", "stat")
    items = sorted(b["items"], key=lambda i: -i["value"])
    keys = [i for i, it in enumerate(items) if it.get("key")] or [0]
    nf = b.get("number_format", "0.0")
    lo = min(0.0, min(i["value"] for i in items))
    spec = {"type": "bar", "categories": [i["label"] for i in items], "number_format": nf, "labels": True,
            "highlight": keys, "axis_min": lo, "axis_max": _headroom([i["value"] for i in items]),
            "series": [{"name": b.get("series_name", "Value"), "values": [i["value"] for i in items]}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, [b])))
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], stats=[b["stat"]])
    return _finish(slide, ctx, "ranked_bar", "bar", els, meta)


# ---------------------------------------------------------------- 2. waterfall
@register("waterfall", data=True, visual_type="waterfall", schema=_schema({
    "steps": {"type": "array", "minItems": 4, "maxItems": 10, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "value"],
        "properties": {"label": {"type": "string", "maxLength": 22}, "value": _NUM, "total": {"type": "boolean"}}}},
    "number_format": _NF, "prefix": {"type": "string", "maxLength": 3}, "suffix": {"type": "string", "maxLength": 4},
    "series_name": {"type": "string"}}, ["steps"]))
def build_waterfall(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "waterfall", "steps")
    steps = b["steps"]
    n = len(steps)
    totals = [i for i, s in enumerate(steps) if s.get("total")] or [0, n - 1]
    if 0 not in totals or n - 1 not in totals:
        raise ValueError("waterfall: the first and last step must be totals")
    run = 0.0
    for i, s in enumerate(steps):
        if i in totals:
            if i and abs(run - s["value"]) > 1e-6 * max(1.0, abs(s["value"])):
                raise ValueError(f"waterfall does not foot at {s['label']!r}: steps sum to {run:g}, total is {s['value']:g}")
            run = s["value"]
        else:
            run += s["value"]
    nf = b.get("number_format", "0")
    first, last = steps[0]["value"], steps[-1]["value"]
    delta = last - first
    pre, suf = b.get("prefix", ""), b.get("suffix", "")
    pct = f" ({_fmt(delta / first * 100, '0.0', True)}%)" if first else ""
    badge = f"{'+' if delta >= 0 else MINUS}{pre}{fmt_number(abs(delta), nf)}{suf}{pct}"
    base.declare(meta, abs(delta), "blocks.steps[0].value", "blocks.steps[-1].value")
    if first:
        base.declare(meta, abs(delta / first * 100), "blocks.steps[0].value", "blocks.steps[-1].value")
    spec = {"type": "waterfall", "categories": [s["label"] for s in steps], "totals": totals, "number_format": nf,
            "labels": True, "labels_above": True, "axis_min": 0,
            "series": [{"name": b.get("series_name", "Value"), "values": [s["value"] for s in steps]}]}
    peak, run = 0.0, 0.0
    for i, s in enumerate(steps):
        run = s["value"] if i in totals else run + s["value"]
        peak = max(peak, run, s["value"] if i in totals else 0)
    spec["axis_max"] = round(peak * 1.2, 6)
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, [b])))
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], badge=badge)
    return _finish(slide, ctx, "waterfall", "waterfall", els, meta)


# ---------------------------------------------------------------- 3 + 4. stacked_bar / stacked_column
_PARTS = {"type": "array", "minItems": 2, "maxItems": 5, "items": {
    "type": "object", "additionalProperties": False, "required": ["name", "values"],
    "properties": {"name": {"type": "string", "maxLength": 28}, "values": {"type": "array", "items": _NUM},
                   "key": {"type": "boolean"}, **_BIND}}}


def _stacked(slide: dict, ctx: BuildContext, aid: str, ctype: str):
    b, meta, els, y, h = _begin(slide, ctx, aid, "categories", "parts")
    cats, parts = b["categories"], b["parts"]
    for p in parts:
        if len(p["values"]) != len(cats):
            raise ValueError(f"{aid}: part {p['name']!r} has {len(p['values'])} values for {len(cats)} categories")
    percent = b.get("mode", "percent") == "percent"
    totals = [sum(p["values"][i] for p in parts) for i in range(len(cats))]
    keyed = [i for i, p in enumerate(parts) if p.get("key")] or [0]
    tokens, rest = {}, iter(_PART_TOKENS)
    for i in range(len(parts)):
        tokens[i] = "accent" if i in keyed[:1] else next(rest)
    series = []
    for i, p in enumerate(parts):
        vals = [round(v / t * 100, 1) if percent and t else v for v, t in zip(p["values"], totals)]
        series.append({"name": p["name"], "values": vals, "color": tokens[i]})
    nf = b.get("number_format") or ('0"%"' if percent else "0")
    spec = {"type": ctype, "categories": cats, "number_format": nf, "labels": True, "series": series,
            "axis_min": 0, "axis_max": 100 if percent else round(max(totals) * 1.05, 6)}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, parts, [b])))
    key = [(p["name"], tokens[i]) for i, p in enumerate(parts)]
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], key=key)
    return _finish(slide, ctx, aid, ctype, els, meta)


@register("stacked_bar", data=True, visual_type="stacked_bar", schema=_schema({
    "categories": _strs(2, 8), "parts": _PARTS, "mode": {"enum": ["percent", "absolute"]}, "number_format": _NF},
    ["categories", "parts"]))
def build_stacked_bar(slide: dict, ctx: BuildContext):
    return _stacked(slide, ctx, "stacked_bar", "stacked_bar")


@register("stacked_column", data=True, visual_type="stacked_column", schema=_schema({
    "categories": _strs(3, 8), "parts": _PARTS, "mode": {"enum": ["percent", "absolute"]}, "number_format": _NF},
    ["categories", "parts"]))
def build_stacked_column(slide: dict, ctx: BuildContext):
    return _stacked(slide, ctx, "stacked_column", "stacked_column")


# ---------------------------------------------------------------- 5. annotated_line
@register("annotated_line", data=True, visual_type="line", schema=_schema({
    "categories": _strs(4, 16, 14),
    "series": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "values"],
        "properties": {"name": {"type": "string", "maxLength": 26}, "values": {"type": "array", "items": _NUM},
                       **_BIND}}},
    "annotation": {"type": "object", "additionalProperties": False, "required": ["at", "text"],
                   "properties": {"at": {"type": "integer", "minimum": 0}, "text": {"type": "string", "maxLength": 60}}},
    "number_format": _NF, "change_unit": {"type": "string", "maxLength": 4}},
    ["categories", "series", "annotation"]))
def build_annotated_line(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "annotated_line", "categories", "series", "annotation")
    cats, series, ann = b["categories"], b["series"], b["annotation"]
    n = len(cats)
    for s in series:
        if len(s["values"]) != n:
            raise ValueError(f"annotated_line: series {s['name']!r} has {len(s['values'])} values for {n} categories")
    if not 0 <= ann["at"] < n:
        raise ValueError("annotated_line: annotation.at is outside the categories")
    nf = b.get("number_format", "0.0")
    main = series[0]["values"]
    allv = [v for s in series for v in s["values"]]
    lo, hi = min(allv), max(allv)
    rng = (hi - lo) or abs(hi) * 0.1 or 1.0
    amin, amax = lo - 0.1 * rng, hi + 0.5 * rng
    unit = b.get("change_unit", "%")
    base.declare(meta, abs(main[-1] - main[0]), "blocks.series[0].values[0]", "blocks.series[0].values[-1]")
    if main[0]:
        base.declare(meta, abs((main[-1] / main[0] - 1) * 100), "blocks.series[0].values[0]",
                     "blocks.series[0].values[-1]")
    if unit == "%":
        badge = f"{_fmt((main[-1] / main[0] - 1) * 100, '0.0', True)}% vs {cats[0]}" if main[0] else ""
    else:
        badge = f"{_fmt(main[-1] - main[0], nf, True)} {unit} vs {cats[0]}"
    cw = grid_w(9)
    layout = [0.02, 0.05, 0.72, 0.80]
    spec = {"type": "line", "categories": cats, "number_format": nf, "labels": False, "value_axis": False,
            "axis_min": round(amin, 6), "axis_max": round(amax, 6), "plot_layout": layout,
            "series": [{"name": s["name"], "values": s["values"],
                        "color": "accent" if i == 0 else "muted"} for i, s in enumerate(series)]}
    els.append(_chart_el(ctx, None, grid_x(0), y, cw, h, spec, _binding(b, series, [b])))
    plot = _Plot(grid_x(0), y, cw, h, layout, amin, amax)
    px = plot.fx((ann["at"] + 0.5) / n)
    py = plot.val_y(main[ann["at"]])
    bx, bw = _grid_box(ctx, px, 3, 0, 5, anchor=px)
    box_h = 0.62
    by = y + 0.05
    els.append(core.tx(ctx, meta, "callout", "annotation", bx, by, bw, box_h, [core.para(ann["text"])], BODY,
                       valign="m", inset=0.12, fill="panel"))
    els.append(core.vline(ctx, "leader", "annotation", px, by + box_h, max(py - 0.1 - (by + box_h), 0.1), "muted"))
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], badge=badge)
    return _finish(slide, ctx, "annotated_line", "line", els, meta)


# ---------------------------------------------------------------- 6. combo_margin
@register("combo_margin", data=True, visual_type="combo", schema=_schema({
    "categories": _strs(3, 10, 14),
    "bars": {"type": "object", "additionalProperties": False, "required": ["name", "values"],
             "properties": {"name": {"type": "string", "maxLength": 28}, "values": {"type": "array", "items": _NUM},
                            **_BIND}},
    "line": {"type": "object", "additionalProperties": False, "required": ["name", "values"],
             "properties": {"name": {"type": "string", "maxLength": 28}, "values": {"type": "array", "items": _NUM},
                            **_BIND}},
    "number_format": _NF, "line_format": _NF}, ["categories", "bars", "line"]))
def build_combo_margin(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "combo_margin", "categories", "bars", "line")
    cats, bars, line = b["categories"], b["bars"], b["line"]
    if len(bars["values"]) != len(cats) or len(line["values"]) != len(cats):
        raise ValueError("combo_margin: bars and line need one value per category")
    nf, lf = b.get("number_format", "0"), b.get("line_format", "0.0%")
    lo, hi = min(line["values"]), max(line["values"])
    s = (hi - lo) / 0.22 if hi > lo else (abs(hi) * 0.2 or 0.01)
    a2min = lo - 0.68 * s
    spec = {"type": "combo", "categories": cats, "number_format": nf, "labels": True, "secondary": True,
            "axis_min": 0, "axis_max": round(max(bars["values"]) / 0.56, 6),
            "axis2_min": round(a2min, 8), "axis2_max": round(a2min + s, 8),
            "series": [{"name": bars["name"], "values": bars["values"], "color": "mute_bar"},
                       {"name": line["name"], "values": line["values"], "color": "accent", "number_format": lf}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, [bars, line], [b])))
    pp = (line["values"][-1] - line["values"][0]) * (100 if "%" in lf else 1)
    badge = f"{_fmt(pp, '0.0', True)} pp vs {cats[0]}"
    base.declare(meta, abs(pp), "blocks.line.values[0]", "blocks.line.values[-1]")
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], badge=badge,
                  key=[(bars["name"], "mute_bar"), (line["name"], "accent")])
    return _finish(slide, ctx, "combo_margin", "combo", els, meta)


# ---------------------------------------------------------------- 7. scatter_quadrant
@register("scatter_quadrant", data=True, visual_type="scatter", schema=_schema({
    "points": {"type": "array", "minItems": 5, "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "xv", "yv"],
        "properties": {"label": {"type": "string", "maxLength": 22}, "xv": _NUM, "yv": _NUM,
                       "subject": {"type": "boolean"}}}},
    "x_title": {"type": "string", "maxLength": 40}, "y_title": {"type": "string", "maxLength": 40},
    "x_format": _NF, "y_format": _NF, "stat": _STAT, "binding": {"type": ["string", "object"]}},
    ["points", "x_title", "y_title", "stat"]))
def build_scatter_quadrant(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "scatter_quadrant", "points", "x_title", "y_title", "stat")
    pts = b["points"]
    xs, ys = [p["xv"] for p in pts], [p["yv"] for p in pts]
    mx, my = statistics.median(xs), statistics.median(ys)

    def pad(lo: float, hi: float) -> tuple[float, float]:
        r = (hi - lo) or abs(hi) * 0.2 or 1.0
        return round(lo - 0.18 * r, 6), round(hi + 0.18 * r, 6)
    x0, x1 = pad(min(xs), max(xs))
    y0, y1 = pad(min(ys), max(ys))
    subj = [i for i, p in enumerate(pts) if p.get("subject")]
    xf, yf = b.get("x_format", "0%"), b.get("y_format", "0%")
    spec = {"type": "scatter", "categories": [p["label"] for p in pts], "number_format": yf, "labels": True,
            "value_axis": True, "x_format": xf, "axis_format": yf, "x_title": b["x_title"], "axis_title": b["y_title"],
            "x_min": x0, "x_max": x1, "axis_min": y0, "axis_max": y1,
            "series": [{"name": "Peers", "values": ys, "x": xs, "color": "muted", "point_labels": True,
                        "point_colors": {i: "accent" for i in subj}, "bold_points": subj},
                       {"name": "Median y", "values": [my, my], "x": [x0, x1], "ref": True},
                       {"name": "Median x", "values": [y0, y1], "x": [mx, mx], "ref": True}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, [b])))
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], stats=[b["stat"]])
    return _finish(slide, ctx, "scatter_quadrant", "scatter", els, meta)


# ---------------------------------------------------------------- 8. football_field
@register("football_field", data=True, visual_type="football_field", schema=_schema({
    "methods": {"type": "array", "minItems": 3, "maxItems": 7, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "low", "high"],
        "properties": {"label": {"type": "string", "maxLength": 28}, "low": _NUM, "high": _NUM,
                       "key": {"type": "boolean"}}}},
    "current_price": _NUM, "implied": _NUM, "number_format": _NF, "prefix": {"type": "string", "maxLength": 3}},
    ["methods", "current_price"]))
def build_football_field(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "football_field", "methods", "current_price")
    ms = b["methods"]
    for m in ms:
        if m["high"] < m["low"]:
            raise ValueError(f"football_field: {m['label']!r} has high below low")
    price = b["current_price"]
    pre, nf = b.get("prefix", ""), b.get("number_format", "0")
    implied = b.get("implied")
    if implied is None:
        implied = statistics.fmean((m["low"] + m["high"]) / 2 for m in ms)
    lo_v = min(min(m["low"] for m in ms), price)
    hi_v = max(max(m["high"] for m in ms), price)
    step = 10 ** math.floor(math.log10(max(hi_v - lo_v, 1e-9)))
    amin = math.floor(lo_v * 0.92 / step) * step
    amax = math.ceil(hi_v * 1.06 / step) * step
    cw = grid_w(9)
    lx = min(0.4, (max(len(m["label"]) for m in ms) * 0.09 + 0.3) / cw)
    layout = [round(lx, 4), 0.14, round(0.97 - lx, 4), 0.72]
    keyed = {i: "accent" for i, m in enumerate(ms) if m.get("key")} or {i: "accent" for i in range(len(ms))}
    colors = {i: keyed.get(i, "mute_bar") for i in range(len(ms))}
    spec = {"type": "football_field", "categories": [m["label"] for m in ms], "number_format": nf, "labels": True,
            "value_axis": False, "axis_min": amin, "axis_max": amax,
            "plot_layout": layout,
            "series": [{"name": "Low", "values": [m["low"] for m in ms]},
                       {"name": "High", "values": [m["high"] for m in ms], "point_colors": colors}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, cw, h, spec, _binding(b, [b])))
    plot = _Plot(grid_x(0), y, cw, h, layout, amin, amax)
    px = plot.val_x(price)
    ptop, pbot = plot.fy(0), plot.fy(1)
    lbl = f"Current {pre}{fmt_number(price, nf)}"
    bx, bw = _grid_box(ctx, px, 2, 0, 8, anchor=px)
    els.append(core.tx(ctx, meta, "callout", "price", bx, y, bw, 0.4, [core.para(lbl, b=False)], BODY, valign="m"))
    els.append(core.vline(ctx, "marker", "price", px, y + 0.4, round(pbot - (y + 0.4), 2), "text", 1.5))
    up = (implied / price - 1) * 100 if price else 0.0
    base.declare(meta, implied, *[f"blocks.methods[{i}].{k}" for i in range(len(ms)) for k in ("low", "high")])
    base.declare(meta, abs(up), "blocks.current_price", "blocks.methods")
    stat = {"value": f"{pre}{fmt_number(implied, nf)}",
            "label": f"Implied value per share, {_fmt(up, '0.0', True)}% vs current {pre}{fmt_number(price, nf)}"}
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], stats=[stat])
    return _finish(slide, ctx, "football_field", "football_field", els, meta)


# ---------------------------------------------------------------- 9. small_multiples
@register("small_multiples", data=True, visual_type="small_multiples", schema=_schema({
    "panels": {"type": "array", "minItems": 3, "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False, "required": ["title", "categories", "values"],
        "properties": {"title": {"type": "string", "maxLength": 24}, "categories": _strs(3, 6, 8),
                       "values": {"type": "array", "items": _NUM}, **_BIND}}},
    "number_format": _NF}, ["panels"]))
def build_small_multiples(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "small_multiples", "panels")
    panels = b["panels"]
    nf = b.get("number_format", "0")
    for p in panels:
        if len(p["values"]) != len(p["categories"]):
            raise ValueError(f"small_multiples: panel {p['title']!r} needs one value per category")
    amax = _headroom([v for p in panels for v in p["values"]], 0.2)
    amin = min(0.0, min(v for p in panels for v in p["values"]))
    span = 12 // len(panels)
    title_h, gap = 0.4, ctx.gap
    take_h = 0.8
    chart_h = round(h - title_h - take_h - gap, 2)
    for i, p in enumerate(panels):
        x, w = grid_x(i * span), grid_w(span)
        els.append(core.tx(ctx, meta, "label", i + 1, x, y, w, title_h, [Para([Run(p["title"], b=True)], space_after=0)],
                           BODY, valign="m"))
        spec = {"type": "column", "categories": p["categories"], "number_format": nf, "labels": True,
                "highlight": [len(p["values"]) - 1], "axis_min": amin, "axis_max": amax,
                "series": [{"name": p["title"], "values": p["values"]}]}
        els.append(_chart_el(ctx, i + 1, x, y + title_h, w, chart_h, spec, _binding({"binding": p.get("binding")}
                                                                                  if p.get("binding") else {})))
    els.append(core.tx(ctx, meta, "callout", "takeaway", grid_x(0), round(y + h - take_h, 2), grid_w(12), take_h,
                       [Para(_takeaway_runs(b["takeaway"]), space_after=0)], BODY, valign="m", inset=0.15, fill="panel"))
    return _finish(slide, ctx, "small_multiples", "small_multiples", els, meta)


# ---------------------------------------------------------------- 10. paired_bars
@register("paired_bars", data=True, visual_type="column", schema=_schema({
    "categories": _strs(3, 7, 18), "before": {"type": "object", "additionalProperties": False,
                                               "required": ["name", "values"],
                                               "properties": {"name": {"type": "string", "maxLength": 20},
                                                              "values": {"type": "array", "items": _NUM}, **_BIND}},
    "after": {"type": "object", "additionalProperties": False, "required": ["name", "values"],
              "properties": {"name": {"type": "string", "maxLength": 20},
                             "values": {"type": "array", "items": _NUM}, **_BIND}},
    "number_format": _NF, "stat": _STAT}, ["categories", "before", "after"]))
def build_paired_bars(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "paired_bars", "categories", "before", "after")
    cats, bef, aft = b["categories"], b["before"], b["after"]
    if len(bef["values"]) != len(cats) or len(aft["values"]) != len(cats):
        raise ValueError("paired_bars: before and after need one value per category")
    nf = b.get("number_format", "0.0")
    spec = {"type": "column", "categories": cats, "number_format": nf, "labels": True, "axis_min": 0,
            "axis_max": _headroom(bef["values"] + aft["values"]),
            "series": [{"name": bef["name"], "values": bef["values"], "color": "muted"},
                       {"name": aft["name"], "values": aft["values"], "color": "accent"}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(9), h, spec, _binding(b, [bef, aft], [b])))
    els += _panel(ctx, meta, 9, 3, y, h, b["takeaway"], stats=[b["stat"]] if b.get("stat") else None,
                  key=[(bef["name"], "muted"), (aft["name"], "accent")])
    return _finish(slide, ctx, "paired_bars", "column", els, meta)


# ---------------------------------------------------------------- 11. doughnut_split
@register("doughnut_split", data=True, visual_type="doughnut", schema=_schema({
    "slices": {"type": "array", "minItems": 2, "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "value"],
        "properties": {"label": {"type": "string", "maxLength": 30}, "value": {"type": "number", "minimum": 0},
                       "key": {"type": "boolean"}}}},
    "centre": {"type": "string", "maxLength": 9}, "number_format": _NF}, ["slices", "centre"]))
def build_doughnut_split(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "doughnut_split", "slices", "centre")
    sl = b["slices"]
    total = sum(s["value"] for s in sl)
    if total <= 0:
        raise ValueError("doughnut_split: slices sum to zero")
    keyed = [i for i, s in enumerate(sl) if s.get("key")] or [0]
    tokens, rest = {}, iter(_PART_TOKENS)
    for i in range(len(sl)):
        tokens[i] = "accent" if i == keyed[0] else next(rest)
    cw = grid_w(6)
    diam = min(h * 0.94, cw)
    layout = [round((cw - diam) / 2 / cw, 4), round((h - diam) / 2 / h, 4), round(diam / cw, 4), round(diam / h, 4)]
    spec = {"type": "doughnut", "categories": [s["label"] for s in sl], "number_format": b.get("number_format", "0"),
            "labels": False, "plot_layout": layout, "hole": 62,
            "series": [{"name": "Share", "values": [s["value"] for s in sl], "point_colors": tokens}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, cw, h, spec, _binding(b, [b])))
    els.append(core.tx(ctx, meta, "stat", "centre", grid_x(2), round(y + h / 2 - 0.45, 2), grid_w(2), 0.9,
                       [Para([Run(b["centre"], b=True, color="accent")], align="c", space_after=0)], SIZES["stat"],
                       font="major", valign="m"))
    key = [(f"{s['label']}  {fmt_number(s['value'] / total * 100, '0')}%", tokens[i]) for i, s in enumerate(sl)]
    els += _panel(ctx, meta, 6, 6, y, h, b["takeaway"], key=key)
    return _finish(slide, ctx, "doughnut_split", "doughnut", els, meta)


# ---------------------------------------------------------------- 12. column_kpi
@register("column_kpi", data=True, visual_type="column", schema=_schema({
    "categories": _strs(3, 8, 14), "values": {"type": "array", "items": _NUM}, "number_format": _NF,
    "series_name": {"type": "string"}, "stats": {"type": "array", "minItems": 2, "maxItems": 2, "items": _STAT},
    "binding": {"type": ["string", "object"]}}, ["categories", "values", "stats"]))
def build_column_kpi(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "column_kpi", "categories", "values", "stats")
    cats, vals = b["categories"], b["values"]
    if len(vals) != len(cats):
        raise ValueError("column_kpi: one value per category")
    spec = {"type": "column", "categories": cats, "number_format": b.get("number_format", "0"), "labels": True,
            "highlight": [len(vals) - 1], "axis_min": 0, "axis_max": _headroom(vals),
            "series": [{"name": b.get("series_name", "Value"), "values": vals}]}
    els.append(_chart_el(ctx, None, grid_x(0), y, grid_w(8), h, spec, _binding(b, [b])))
    els += _panel(ctx, meta, 8, 4, y, h, b["takeaway"], stats=b["stats"])
    return _finish(slide, ctx, "column_kpi", "column", els, meta)


# ---------------------------------------------------------------- examples
_SRC = "Company filings; Acretia analysis"

EXAMPLES = {
    "ranked_bar": {
        "title": "Acme trades at the lowest EV/EBITDA multiple in its peer set",
        "source": "FactSet consensus", "as_of": "2026-10-31",
        "sources": ["FactSet consensus, NTM EV/EBITDA", "Company filings, net debt at 30 Sep 2026"],
        "blocks": {"subtitle": "EV/EBITDA, next twelve months, x", "number_format": '0.0"x"', "series_name": "EV/EBITDA",
                   "items": [{"label": "Northwind Bank", "value": 14.8}, {"label": "Helios Financial", "value": 13.9},
                             {"label": "Brightline Capital", "value": 13.4}, {"label": "Meridian Group", "value": 12.9},
                             {"label": "Corvus Holdings", "value": 12.1}, {"label": "Aster Partners", "value": 11.8},
                             {"label": "Acme", "value": 10.6, "key": True}],
                   "stat": {"value": "2.3x", "label": "discount to the peer median of 12.9x"},
                   "takeaway": "Closing half the gap to the 12.9x median would re-rate Acme from 10.6x EBITDA [1]",
                   "binding": "m-peer-ev-ebitda"}},
    "waterfall": {
        "title": "EBITDA grows $32m as price and savings outweigh cost inflation",
        "source": _SRC, "as_of": "2026-09-30",
        "sources": ["Company filings, FY25 and FY26 accounts", "Acretia analysis, bridge model v3"],
        "blocks": {"subtitle": "EBITDA bridge, FY25 to FY26, $ million", "number_format": "0", "prefix": "$", "suffix": "m",
                   "steps": [{"label": "FY25", "value": 412}, {"label": "Price", "value": 58},
                             {"label": "Volume", "value": -31}, {"label": "Mix", "value": 12},
                             {"label": "Inflation", "value": -44}, {"label": "FX", "value": -9},
                             {"label": "Savings", "value": 46}, {"label": "FY26", "value": 444}],
                   "takeaway": "Price (+$58m) and savings (+$46m) outweigh inflation (-$44m) and volume (-$31m) [2]",
                   "binding": {"manifest_id": "m-ebitda-bridge"}}},
    "stacked_bar": {
        "title": "Acme leans on retail more than any peer while corporate lags",
        "source": _SRC, "as_of": "2026-06-30",
        "sources": ["Company filings, segment notes FY25", "Peer annual reports FY25"],
        "blocks": {"subtitle": "Revenue mix by business line, FY25, % of total revenue", "mode": "percent",
                   "categories": ["Acme", "Northwind", "Helios", "Brightline"],
                   "parts": [{"name": "Retail", "values": [52, 45, 38, 30], "key": True},
                             {"name": "Corporate", "values": [28, 30, 34, 41]},
                             {"name": "Treasury and markets", "values": [12, 15, 19, 20]},
                             {"name": "Other", "values": [8, 10, 9, 9]}],
                   "takeaway": "Retail is 52% of Acme revenue against 30% at Brightline [2]"}},
    "stacked_column": {
        "title": "Current accounts now fund 42% of deposits, up from 31% four years ago",
        "source": _SRC, "as_of": "2026-09-30",
        "blocks": {"subtitle": "Deposit mix, FY22 to FY26, % of total deposits", "mode": "percent",
                   "categories": ["FY22", "FY23", "FY24", "FY25", "FY26"],
                   "parts": [{"name": "Current accounts", "values": [31, 33, 36, 39, 42], "key": True},
                             {"name": "Savings", "values": [38, 37, 35, 33, 31]},
                             {"name": "Term deposits", "values": [31, 30, 29, 28, 27]}],
                   "takeaway": "Cheaper funding lowers the cost of deposits as current accounts reach 42% of the mix"}},
    "annotated_line": {
        "title": "Net interest margin recovers to 3.42% after the floating book reprices",
        "source": _SRC, "as_of": "2026-09-30",
        "sources": ["Company filings, quarterly results", "Peer quarterly results, median of six banks"],
        "blocks": {"subtitle": "Net interest margin, quarterly, %", "number_format": "0.00", "change_unit": "pp",
                   "categories": ["Q1 FY25", "Q2 FY25", "Q3 FY25", "Q4 FY25", "Q1 FY26", "Q2 FY26", "Q3 FY26", "Q4 FY26"],
                   "series": [{"name": "Acme NIM", "values": [3.05, 3.02, 2.94, 2.88, 3.01, 3.17, 3.31, 3.42],
                               "binding": "m-nim"},
                              {"name": "Peer median", "values": [3.10, 3.08, 3.04, 3.02, 3.05, 3.10, 3.15, 3.20]}],
                   "annotation": {"at": 3, "text": "Floating book reprices from Q1 FY26"},
                   "takeaway": "Acme NIM of 3.42% now sits above the 3.20% peer median, from 3.05% against 3.10% two years ago [2]"}},
    "combo_margin": {
        "title": "Revenue grows 8% a year while EBITDA margin widens 4.2 points",
        "source": _SRC, "as_of": "2026-09-30",
        "sources": ["Company filings, FY22 to FY26 accounts"],
        "blocks": {"subtitle": "Revenue, $ million, and EBITDA margin, %", "number_format": "#,##0", "line_format": "0.0%",
                   "categories": ["FY22", "FY23", "FY24", "FY25", "FY26"],
                   "bars": {"name": "Revenue, $m", "values": [820, 905, 968, 1042, 1128], "binding": "m-revenue"},
                   "line": {"name": "EBITDA margin", "values": [0.184, 0.196, 0.201, 0.213, 0.226]},
                   "takeaway": "Operating leverage lifts EBITDA margin from 18.4% to 22.6% as revenue reaches $1,128m [1]"}},
    "scatter_quadrant": {
        "title": "Acme pairs peer-median growth with the highest margin in the set",
        "source": "FactSet consensus", "as_of": "2026-10-31",
        "blocks": {"subtitle": "Revenue growth versus EBITDA margin, FY26E", "x_title": "Revenue growth, FY25 to FY26E",
                   "y_title": "EBITDA margin, FY26E", "x_format": "0%", "y_format": "0%",
                   "points": [{"label": "Acme", "xv": 0.083, "yv": 0.226, "subject": True},
                              {"label": "Northwind", "xv": 0.121, "yv": 0.184}, {"label": "Helios", "xv": 0.064, "yv": 0.171},
                              {"label": "Brightline", "xv": 0.095, "yv": 0.152}, {"label": "Meridian", "xv": 0.048, "yv": 0.198},
                              {"label": "Corvus", "xv": 0.109, "yv": 0.139}, {"label": "Aster", "xv": 0.072, "yv": 0.163}],
                   "stat": {"value": "+5.5pp", "label": "EBITDA margin above the peer median of 17.1%"},
                   "takeaway": "Margin, not growth, explains why Acme earns a premium to peers"}},
    "football_field": {
        "title": "Every method values Acme above the current $142 share price",
        "source": "Company filings; broker research", "as_of": "2026-11-13",
        "sources": ["Acretia DCF model v9", "FactSet, trading and transaction comparables", "Broker research, Nov 2026"],
        "blocks": {"subtitle": "Equity value per share by method, $", "prefix": "$", "number_format": "0",
                   "current_price": 142.1,
                   "methods": [{"label": "DCF (WACC 8.5 to 10.5%)", "low": 148, "high": 186, "key": True},
                               {"label": "Trading comps", "low": 139, "high": 171},
                               {"label": "Precedent transactions", "low": 152, "high": 194},
                               {"label": "52-week range", "low": 118, "high": 156},
                               {"label": "Broker targets", "low": 145, "high": 175}],
                   "takeaway": "The DCF range sits entirely above the market, a 17% upside at the midpoint [1]"}},
    "small_multiples": {
        "title": "Operating margin improves in all four regions, led by the Gulf",
        "source": _SRC, "as_of": "2026-09-30",
        "blocks": {"subtitle": "Operating margin by region, FY23 to FY26, %", "number_format": "0",
                   "panels": [{"title": "Gulf", "categories": ["FY23", "FY24", "FY25", "FY26"], "values": [18, 21, 24, 27]},
                              {"title": "Levant", "categories": ["FY23", "FY24", "FY25", "FY26"], "values": [14, 15, 17, 18]},
                              {"title": "North Africa", "categories": ["FY23", "FY24", "FY25", "FY26"], "values": [12, 14, 15, 17]},
                              {"title": "Europe", "categories": ["FY23", "FY24", "FY25", "FY26"], "values": [16, 16, 18, 19]}],
                   "takeaway": "Gulf margin is up from 18% to 27% since FY23, the largest gain of any region"}},
    "paired_bars": {
        "title": "Cost-to-income improves in four of five divisions after the programme",
        "source": _SRC, "as_of": "2026-09-30",
        "blocks": {"subtitle": "Cost-to-income ratio by division, FY25 versus FY26, %", "number_format": "0.0",
                   "categories": ["Retail", "Corporate", "Treasury", "Wealth", "Insurance"],
                   "before": {"name": "FY25", "values": [61.2, 48.5, 39.4, 66.8, 71.3]},
                   "after": {"name": "FY26", "values": [57.4, 45.1, 38.9, 62.0, 72.1]},
                   "stat": {"value": "-3.6pp", "label": "average ratio change across the group"},
                   "takeaway": "Insurance is the only division that moved the wrong way, from 71.3% to 72.1%"}},
    "doughnut_split": {
        "title": "Corporate lending is almost half of the $18.4bn loan book",
        "source": _SRC, "as_of": "2026-09-30",
        "blocks": {"subtitle": "Loan book by segment, % of gross loans", "centre": "$18.4bn",
                   "slices": [{"label": "Corporate", "value": 46, "key": True}, {"label": "Retail", "value": 31},
                              {"label": "SME", "value": 15}, {"label": "Other", "value": 8}],
                   "takeaway": "Corporate is 46% of loans against 31% for retail, so credit cost drives earnings"}},
    "column_kpi": {
        "title": "Revenue compounds at 8.3% a year to $1.13bn",
        "source": _SRC, "as_of": "2026-09-30",
        "blocks": {"subtitle": "Revenue, FY22 to FY26, $ million", "number_format": "#,##0", "series_name": "Revenue",
                   "categories": ["FY22", "FY23", "FY24", "FY25", "FY26"], "values": [820, 905, 968, 1042, 1128],
                   "stats": [{"value": "$1.13bn", "label": "FY26 revenue, up $86m on FY25"},
                             {"value": "8.3%", "label": "revenue CAGR, FY22 to FY26"}],
                   "takeaway": "Growth has been steady, with no year below 6.5%"}},
}
