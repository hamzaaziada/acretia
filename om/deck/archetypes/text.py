"""Text and structure archetypes: exec_summary, agenda, kpi_row, stat_hero, quote, recommendation, takeaway_box,
two_column_compare, numbered_insights, process_flow, gantt, issue_tree, visual_text, appendix_divider.

All geometry sits on the 12-column grid. Shapes the renderer has only as rectangles and straight lines are built from
those: steps are squares, milestones are small squares, connectors are horizontal and vertical segments. Free-floating
timeline parts (month labels, bars, markers) carry the role `decor`, which the validator exempts from the grid.
"""
from __future__ import annotations

import re

from om.deck.archetypes import BuildContext, register
from om.deck.archetypes import base
from om.deck.archetypes.core import (FitFailure, area, art, cols, hline, need, para, rect, row_cols, short_footer,
                                     tx, vline)
from om.deck.model import Element, Para, Run
from om.deck.theme import CANVAS_H, CANVAS_W, MARGIN_X, SIZES, grid_w, grid_x

BODY, LABEL, TITLE, STAT = SIZES["body"], SIZES["label"], SIZES["title"], SIZES["stat"]
_OPT = {"subtitle": {"type": "string"}, "measure": {"type": "string"}}
_STR = {"type": "string"}


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": {**props, **_OPT}}


def _arr(item: dict, lo: int, hi: int) -> dict:
    return {"type": "array", "items": item, "minItems": lo, "maxItems": hi}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": props}


def _begin(slide: dict, ctx: BuildContext, aid: str, *keys: str):
    b = slide.get("blocks") or {}
    need(b, aid, *keys)
    meta: dict = {}
    els = base.frame(slide, ctx, meta=meta)
    y, h = area(slide, ctx)
    return b, meta, els, y, h


def _t(text: str, *, b: bool = False, color: str | None = None, align: str = "l", after: float = 0) -> Para:
    return para(text, b=b, color=color, align=align, after=after)


def _lead(lead: str, text: str, color: str | None = None) -> Para:
    """Bold lead-in label, key figures in the rest bold, the explanation regular."""
    return Para([Run(lead.rstrip(":") + ":", True, color), *base.figure_runs(" " + text, color=color)], space_after=0)


def _bullets(items: list[str]) -> list[Para]:
    return [Para(base.figure_runs(t), bullet=True, space_after=4) for t in items]


# ---------------------------------------------------------------- exec_summary
@register("exec_summary", data=True, visual_type="text", schema=_schema({
    "insights": _arr(_obj({"lead": _STR, "text": _STR, "figure": _STR}, ["lead", "text"]), 3, 5),
    "so_what": _obj({"heading": _STR, "text": _STR}, ["text"])}, ["insights"]))
def build_exec_summary(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "exec_summary", "insights")
    ins = b["insights"]
    n = len(ins)
    rh = round(h / n, 2)
    so = b.get("so_what")
    fig = any(i.get("figure") for i in ins)
    t_end = (6 if fig else 8) if so else (8 if fig else 11)
    tx0, tw = cols(1, t_end)
    right = grid_x(9) - 0.2 if so else grid_x(12)
    for i, it in enumerate(ins):
        ry = round(y + i * rh, 2)
        if i:
            els.append(hline(ctx, "rule", i, grid_x(0), ry, round(right - grid_x(0), 2)))
        els.append(tx(ctx, meta, "number", i + 1, grid_x(0), ry, grid_w(1), rh,
                      [Para([Run(str(i + 1), True, "accent")], space_after=0)], TITLE, font="major", valign="m"))
        els.append(tx(ctx, meta, "body", i + 1, tx0, ry, tw, rh, [_lead(it["lead"], it["text"])], BODY, valign="m",
                      inset=0.05))
        if fig and it.get("figure"):
            fx, fw = (cols(7, 8) if so else cols(9, 11))
            els.append(tx(ctx, meta, "kpi", i + 1, fx, ry, fw, rh, [Para([Run(it["figure"], True)], space_after=0)],
                          TITLE, font="major", valign="m"))
    if so:
        px, pw = cols(9, 11)
        paras = [Para([Run(so.get("heading", "So what"), True, "accent")], space_after=6),
                 Para(base.figure_runs(so["text"]), space_after=0)]
        els.append(tx(ctx, meta, "callout", "so_what", px, y, pw, h, paras, BODY, inset=0.2, fill="panel"))
    return base.solved(slide, ctx, "exec_summary", "text", els, meta)


# ---------------------------------------------------------------- agenda
@register("agenda", visual_type="text", schema=_schema({
    "items": _arr(_obj({"title": _STR, "detail": _STR, "time": _STR}, ["title"]), 3, 7),
    "current": {"type": "integer", "minimum": 0}}, ["items"]))
def build_agenda(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "agenda", "items")
    items, cur = b["items"], b.get("current")
    n = len(items)
    if cur is not None and not 0 <= cur < n:
        raise ValueError("agenda: blocks.current is outside the items")
    rh = round(min(0.8, h / n), 2)
    for i, it in enumerate(items):
        ry = round(y + i * rh, 2)
        on = cur == i
        c_main = "accent" if on else ("muted" if cur is not None else "text")
        c_side = "text" if on else ("muted" if cur is not None else "text")
        if on:
            els.append(rect(ctx, "panel", i + 1, grid_x(0), ry, grid_x(12) - grid_x(0), rh, "panel"))
        else:
            els.append(hline(ctx, "rule", i + 1, grid_x(0), round(ry + rh, 2), round(grid_x(12) - grid_x(0), 2)))
        els.append(tx(ctx, meta, "number", i + 1, grid_x(0), ry, grid_w(1), rh,
                      [Para([Run(f"{i + 1:02d}", True, c_main)], align="c", space_after=0)], TITLE, font="major",
                      valign="m"))
        x1, w1 = cols(1, 5)
        els.append(tx(ctx, meta, "body", i + 1, x1, ry, w1, rh, [Para([Run(it["title"], True, c_main)], space_after=0)],
                      BODY, valign="m", inset=0.05))
        if it.get("detail"):
            x2, w2 = cols(6, 9)
            els.append(tx(ctx, meta, "label", i + 1, x2, ry, w2, rh, [Para([Run(it["detail"], False, c_side)],
                          space_after=0)], LABEL, valign="m", inset=0.05))
        if it.get("time"):
            for k, num in enumerate(re.findall(r"\d+(?:\.\d+)?", it["time"])):
                base.declare(meta, float(num), f"blocks.items[{i}].time[{k}]")
            x3, w3 = cols(10, 11)
            els.append(tx(ctx, meta, "label", f"t{i + 1}", x3, ry, w3, rh, [Para([Run(it["time"], True, c_side)],
                          align="r", space_after=0)], LABEL, valign="m", inset=0.05))
    return base.solved(slide, ctx, "agenda", "text", els, meta)


# ---------------------------------------------------------------- kpi_row
_CHANGE = {"up": ("secondary", "background"), "down": ("negative", "background"), "flat": ("mute_bar", "text")}


@register("kpi_row", data=True, visual_type="stat", schema=_schema({
    "kpis": _arr(_obj({"label": _STR, "value": _STR, "context": _STR,
                       "change": _obj({"text": _STR, "direction": {"enum": ["up", "down", "flat"]}}, ["text"])},
                      ["label", "value"]), 3, 5),
    "highlight": {"type": "integer", "minimum": 0}, "so_what": _STR}, ["kpis"]))
def build_kpi_row(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "kpi_row", "kpis")
    kp, hi = b["kpis"], b.get("highlight")
    n = len(kp)
    ch = min(3.4, h - ctx.gap - 0.7) if b.get("so_what") else min(3.4, h)
    ins = 0.2 if n < 5 else 0.12
    for i, (k, (cx, cw)) in enumerate(zip(kp, row_cols(n))):
        els.append(rect(ctx, "panel", i + 1, cx, y, cw, ch, "panel"))
        els.append(tx(ctx, meta, "label", i + 1, cx, y, cw, 0.7, [_t(k["label"], b=True)], BODY, valign="m", inset=ins))
        els.append(tx(ctx, meta, "kpi", i + 1, cx, round(y + 0.7, 2), cw, 1.2,
                      [Para([Run(k["value"], True, "accent" if hi == i else None)], space_after=0)], STAT, floor=STAT,
                      font="major", valign="m", inset=ins))
        chg = k.get("change")
        if chg:
            fill, col = _CHANGE[chg.get("direction", "flat")]
            bw = round(min(1.7, cw - 2 * ins), 2)
            els.append(tx(ctx, meta, "decor", f"badge{i + 1}", round(cx + ins, 2), round(y + 1.95, 2), bw, 0.38,
                          [Para([Run(chg["text"], True, col)], align="c", space_after=0)], BODY, floor=BODY,
                          valign="m", inset=0.04, fill=fill))
        if k.get("context"):
            els.append(tx(ctx, meta, "body", i + 1, cx, round(y + 2.4, 2), cw, round(ch - 2.4, 2),
                          [_t(k["context"])], BODY, inset=ins))
    if b.get("so_what"):
        sy = round(y + ch + ctx.gap, 2)
        els.append(tx(ctx, meta, "callout", "so_what", grid_x(0), sy, grid_x(12) - grid_x(0), round(y + h - sy, 2),
                      [Para(base.figure_runs(b["so_what"]), space_after=0)], BODY, valign="m", inset=0.2,
                      fill="key_message"))
    return base.solved(slide, ctx, "kpi_row", "stat", els, meta)


# ---------------------------------------------------------------- stat_hero
@register("stat_hero", data=True, visual_type="stat", schema=_schema({
    "stats": _arr(_obj({"value": _STR, "label": _STR, "context": _STR}, ["value", "label"]), 1, 2),
    "so_what": _STR}, ["stats"]))
def build_stat_hero(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "stat_hero", "stats")
    stats, so = b["stats"], b.get("so_what")
    n = len(stats)
    band = 1.1 if so else 0.0
    pic = art(ctx, slide, grid_x(7), y, grid_w(5), round(h - (band + ctx.gap if band else 0), 2))
    side = pic is not None or so is not None
    if pic:
        els.append(pic)
        if so:
            els.append(tx(ctx, meta, "callout", "so_what", grid_x(7), round(y + h - band, 2), grid_w(5), band,
                          [Para(base.figure_runs(so), space_after=0)], BODY, valign="m", inset=0.2, fill="key_message"))
    elif so:
        els.append(tx(ctx, meta, "callout", "so_what", grid_x(7), y, grid_w(5), h,
                      [Para([Run("So what", True, "accent")], space_after=6), Para(base.figure_runs(so))],
                      BODY, inset=0.25, fill="panel"))
    top, avail = y, h
    spans = [(grid_x(0), grid_w(7))] * n if side else row_cols(n)
    bh = round((avail - (n - 1) * ctx.gap) / n, 2) if side else avail
    for i, (s, (sx, sw)) in enumerate(zip(stats, spans)):
        sy = round(top + (i * (bh + ctx.gap) if side else 0), 2)
        if side and i:
            els.append(hline(ctx, "rule", i, sx, round(sy - ctx.gap / 2, 2), sw))
        els.append(tx(ctx, meta, "kpi", i + 1, sx, sy, sw, 1.0,
                      [Para([Run(s["value"], True, "accent" if i == 0 else None)], space_after=0)], STAT, floor=STAT,
                      font="major", valign="m"))
        els.append(tx(ctx, meta, "label", i + 1, sx, round(sy + 1.0, 2), sw, 0.45, [_t(s["label"], b=True)], BODY,
                      valign="m"))
        if s.get("context"):
            els.append(tx(ctx, meta, "body", i + 1, sx, round(sy + 1.5, 2), sw, round(max(bh - 1.5, 0.5), 2),
                          [_t(s["context"])], BODY))
    return base.solved(slide, ctx, "stat_hero", "stat", els, meta)


# ---------------------------------------------------------------- quote
@register("quote", visual_type="text", schema=_schema({
    "quote": _STR, "attribution": _STR, "role": _STR}, ["quote", "attribution"]))
def build_quote(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "quote", "quote", "attribution")
    qx, qw = cols(1, 10)
    els.append(hline(ctx, "rule", None, qx, round(y + 0.2, 2), grid_w(1), "accent", 3.0))
    els.append(tx(ctx, meta, "quote", None, qx, round(y + 0.5, 2), qw, round(h - 0.5 - 1.1, 2),
                  [Para([Run(b["quote"])], space_after=0)], 32, font="major"))
    paras = [Para([Run(b["attribution"], True)], space_after=2)]
    if b.get("role"):
        paras.append(Para([Run(b["role"], False, "muted")], space_after=0))
    els.append(tx(ctx, meta, "body", "attribution", qx, round(y + h - 0.9, 2), qw, 0.9, paras, BODY, valign="b"))
    return base.solved(slide, ctx, "quote", "text", els, meta)


# ---------------------------------------------------------------- recommendation
@register("recommendation", visual_type="columns", schema=_schema({
    "phases": _arr(_obj({"label": _STR, "window": _STR, "actions": _arr(_STR, 2, 4), "owner": _STR, "date": _STR},
                        ["label", "actions", "owner", "date"]), 3, 3),
    "owner_label": _STR, "date_label": _STR}, ["phases"]))
def build_recommendation(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "recommendation", "phases")
    if len(b["phases"]) != 3:
        raise ValueError("recommendation: exactly 3 phases (now, next, later) required")
    hh, oh = 0.6, 0.95
    bh = round(h - hh - oh, 2)
    for i, (p, (cx, cw)) in enumerate(zip(b["phases"], row_cols(3))):
        head = p["label"] + (f": {p['window']}" if p.get("window") else "")
        els.append(tx(ctx, meta, "label", i + 1, cx, y, cw, hh, [Para([Run(head, True, "background")], space_after=0)],
                      BODY, valign="m", inset=0.2, fill="accent" if i == 0 else "secondary"))
        els.append(tx(ctx, meta, "body", i + 1, cx, round(y + hh, 2), cw, bh, _bullets(p["actions"]), BODY,
                      inset=0.2, fill="panel"))
        oy = round(y + hh + bh, 2)
        els.append(tx(ctx, meta, "callout", f"owner{i + 1}", cx, oy, cw, oh,
                      [_lead(b.get("owner_label", "Owner"), p["owner"]), _lead(b.get("date_label", "Date"), p["date"])],
                      BODY, valign="m", inset=0.2, fill="panel"))
        els.append(hline(ctx, "rule", i + 1, cx, oy, cw))
    return base.solved(slide, ctx, "recommendation", "columns", els, meta)


# ---------------------------------------------------------------- takeaway_box
@register("takeaway_box", visual_type="text", schema=_schema({
    "decision": _STR, "rationale": _arr(_STR, 2, 4), "risks": _arr(_STR, 1, 3),
    "rationale_heading": _STR, "risks_heading": _STR}, ["decision", "rationale", "risks"]))
def build_takeaway_box(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "takeaway_box", "decision", "rationale", "risks")
    full = grid_x(12) - grid_x(0)
    dh = 1.3
    els.append(tx(ctx, meta, "callout", "decision", grid_x(0), y, full, dh,
                  [Para([Run(b["decision"], True, "background")], space_after=0)], TITLE, font="major", valign="m",
                  inset=0.25, fill="accent"))
    by = round(y + dh + ctx.gap, 2)
    bh = round(y + h - by, 2)
    for i, (key, head, dflt) in enumerate((("rationale", "rationale_heading", "Rationale"),
                                           ("risks", "risks_heading", "Risks and mitigations"))):
        cx, cw = cols(6 * i, 6 * i + 5)
        paras = [Para([Run(b.get(head, dflt), True)], space_after=6)] + _bullets(b[key])
        els.append(tx(ctx, meta, "body", key, cx, by, cw, bh, paras, BODY, inset=0.2, fill="panel"))
    return base.solved(slide, ctx, "takeaway_box", "text", els, meta)


# ---------------------------------------------------------------- two_column_compare
_SIDE = _obj({"heading": _STR, "metric": _STR, "points": _arr(_STR, 2, 5)}, ["heading", "points"])


@register("two_column_compare", visual_type="compare", schema=_schema({
    "a": _SIDE, "b": _SIDE, "verdict": _STR, "verdict_label": _STR, "emphasis": {"enum": ["a", "b"]}},
    ["a", "b", "verdict"]))
def build_two_column_compare(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "two_column_compare", "a", "b", "verdict")
    vh, hh = 0.9, 0.6
    bh = round(h - hh - vh - ctx.gap, 2)
    for i, key in enumerate(("a", "b")):
        side = b[key]
        cx, cw = cols(6 * i, 6 * i + 5)
        fill = "accent" if b.get("emphasis") == key else "secondary"
        els.append(tx(ctx, meta, "label", key, cx, y, cw, hh, [Para([Run(side["heading"], True, "background")],
                      space_after=0)], BODY, valign="m", inset=0.2, fill=fill))
        by = round(y + hh, 2)
        els.append(rect(ctx, "panel", key, cx, by, cw, bh, "panel"))
        py, ph = by, bh
        if side.get("metric"):
            els.append(tx(ctx, meta, "kpi", key, cx, by, cw, 0.8, [Para([Run(side["metric"], True)], space_after=0)],
                          TITLE, font="major", valign="m", inset=0.2))
            py, ph = round(by + 0.8, 2), round(bh - 0.8, 2)
        els.append(tx(ctx, meta, "body", key, cx, py, cw, ph, _bullets(side["points"]), BODY, inset=0.2))
    els.append(tx(ctx, meta, "callout", "verdict", grid_x(0), round(y + h - vh, 2), grid_x(12) - grid_x(0), vh,
                  [_lead(b.get("verdict_label", "Verdict"), b["verdict"])], BODY, valign="m", inset=0.2,
                  fill="key_message"))
    return base.solved(slide, ctx, "two_column_compare", "compare", els, meta)


# ---------------------------------------------------------------- numbered_insights
@register("numbered_insights", visual_type="cards", schema=_schema({
    "insights": _arr(_obj({"title": _STR, "text": _STR, "figure": _STR}, ["title", "text"]), 2, 4),
    "layout": {"enum": ["grid", "row"]}}, ["insights"]))
def build_numbered_insights(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "numbered_insights", "insights")
    ins = b["insights"]
    n = len(ins)
    grid = n == 4 and b.get("layout", "grid") == "grid"
    if grid:
        ch = round((h - ctx.gap) / 2, 2)
        spots = [(cols(6 * c, 6 * c + 5), round(y + r * (ch + ctx.gap), 2)) for r in range(2) for c in range(2)]
    else:
        ch = min(h, 3.4)
        spots = [(c, y) for c in row_cols(n)]
    for i, (it, ((cx, cw), cy)) in enumerate(zip(ins, spots)):
        els.append(rect(ctx, "panel", i + 1, cx, cy, cw, ch, "panel"))
        fig = it.get("figure")
        by, bh_ = round(cy + 0.8, 2), round(ch - 0.8, 2)
        if fig and grid:              # number on the left two columns, headline figure on the right four
            c0 = 6 * (i % 2)
            nx, nw = cols(c0, c0 + 1)
            fx, fw = cols(c0 + 2, c0 + 5)
            els.append(tx(ctx, meta, "kpi", i + 1, fx, cy, fw, 0.8, [Para([Run(fig, True)], align="r",
                          space_after=0)], TITLE, font="major", valign="m", inset=0.2))
        else:
            nx, nw = cx, cw
            if fig:                   # row layout: the figure gets its own band under the number
                els.append(tx(ctx, meta, "kpi", i + 1, cx, by, cw, 0.9, [Para([Run(fig, True)], space_after=0)],
                              TITLE, font="major", valign="m", inset=0.2))
                by, bh_ = round(by + 0.9, 2), round(bh_ - 0.9, 2)
        els.append(tx(ctx, meta, "number", i + 1, nx, cy, nw, 0.8, [Para([Run(f"{i + 1:02d}", True, "accent")],
                      space_after=0)], TITLE, font="major", valign="m", inset=0.2))
        paras = [Para([Run(it["title"], True)], space_after=4), Para(base.figure_runs(it["text"]), space_after=0)]
        els.append(tx(ctx, meta, "body", i + 1, cx, by, cw, bh_, paras, BODY, inset=0.2))
    return base.solved(slide, ctx, "numbered_insights", "cards", els, meta)


# ---------------------------------------------------------------- process_flow
@register("process_flow", visual_type="flow", schema=_schema({
    "steps": _arr(_obj({"name": _STR, "output": _STR}, ["name", "output"]), 4, 6),
    "highlight": {"type": "integer", "minimum": 0}, "output_label": _STR}, ["steps"]))
def build_process_flow(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "process_flow", "steps")
    steps, hi = b["steps"], b.get("highlight")
    if not 4 <= len(steps) <= 6:
        raise ValueError("process_flow: 4 to 6 steps required")
    spans = row_cols(len(steps))
    hy, oy = round(y + 0.75, 2), round(y + 1.65, 2)
    for i, (s, (cx, cw)) in enumerate(zip(steps, spans)):
        els.append(tx(ctx, meta, "number", i + 1, cx, y, cw, 0.75,
                      [Para([Run(f"{i + 1:02d}", True, "accent" if hi == i else "secondary")], space_after=0)],
                      TITLE, font="major", valign="m"))
        els.append(tx(ctx, meta, "label", i + 1, cx, hy, cw, 0.9, [Para([Run(s["name"], True, "background")],
                      space_after=0)], BODY, valign="m", inset=0.12, fill="accent" if hi == i else "secondary"))
        els.append(tx(ctx, meta, "body", i + 1, cx, oy, cw, round(min(2.4, y + h - oy), 2),
                      [_lead(b.get("output_label", "Output"), s["output"])], BODY, inset=0.12, fill="panel"))
        if i:
            px, pw = spans[i - 1]
            els.append(hline(ctx, "connector", i, round(px + pw, 2), round(hy + 0.45, 2), round(cx - px - pw, 2),
                             "text", 1.5))
    return base.solved(slide, ctx, "process_flow", "flow", els, meta)


# ---------------------------------------------------------------- gantt
_MS = _obj({"month": {"type": "number"}, "label": _STR}, ["month", "label"])
_BAR = _obj({"start": {"type": "number"}, "end": {"type": "number"}, "label": _STR, "highlight": {"type": "boolean"}},
            ["start", "end"])


def gantt_geometry(n_months: int) -> tuple[float, float]:
    """(x of the timeline, width of one month column); bars land on these columns."""
    x0 = grid_x(3)
    return x0, round((grid_x(12) - x0) / n_months, 4)


@register("gantt", visual_type="timeline", schema=_schema({
    "months": _arr(_STR, 6, 12),
    "workstreams": _arr(_obj({"name": _STR, "bars": _arr(_BAR, 1, 3), "milestones": _arr(_MS, 0, 3)},
                             ["name", "bars"]), 3, 6),
    "today": {"type": "number"}, "today_label": _STR}, ["months", "workstreams"]))
def build_gantt(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "gantt", "months", "workstreams")
    months, ws = b["months"], b["workstreams"]
    m, n = len(months), len(ws)
    x0, mw = gantt_geometry(m)
    xr = round(x0 + mw * m, 2)
    for i, name in enumerate(months):
        els.append(tx(ctx, meta, "decor", f"m{i}", round(x0 + i * mw, 2), y, round(mw, 2), 0.3,
                      [Para([Run(name, True, "muted")], align="c", space_after=0)], LABEL, valign="m"))
    top = round(y + 0.62, 2)
    els.append(hline(ctx, "rule", "head", grid_x(0), top, round(xr - grid_x(0), 2), "text"))
    rh = round((y + h - top) / n, 2)
    bar_h, ms = round(min(0.3, rh * 0.4), 2), 0.18
    for i, w in enumerate(ws):
        ry = round(top + i * rh, 2)
        els.append(tx(ctx, meta, "label", i + 1, grid_x(0), ry, grid_w(3), rh, [Para([Run(w["name"], True)],
                      space_after=0)], BODY, valign="m", inset=0.05))
        els.append(hline(ctx, "rule", i + 1, grid_x(0), round(ry + rh, 2), round(xr - grid_x(0), 2)))
        for k, bar in enumerate(w["bars"]):
            if not (0 <= bar["start"] <= bar["end"] < m):
                raise ValueError(f"gantt: bar {bar} is outside the {m} months")
            bx, bw = round(x0 + bar["start"] * mw, 2), round((bar["end"] + 1 - bar["start"]) * mw, 2)
            lab = bar.get("label") if bar.get("label") and bw >= 1.2 else None
            hl = bar.get("highlight")
            els.append(tx(ctx, meta, "decor", f"bar{i + 1}_{k + 1}", bx, round(ry + rh * 0.12, 2), bw, bar_h,
                          [Para([Run(lab or "", True, "background" if hl else "text")], align="c", space_after=0)],
                          LABEL, valign="m", inset=0.04, fill="accent" if hl else "mute_bar")
                       if lab else rect(ctx, "decor", f"bar{i + 1}_{k + 1}", bx, round(ry + rh * 0.12, 2), bw, bar_h,
                                        "accent" if hl else "mute_bar"))
        for k, mi in enumerate(w.get("milestones", [])):
            mx = round(x0 + mi["month"] * mw - ms / 2, 2)
            my = round(ry + rh * 0.58, 2)
            els.append(rect(ctx, "decor", f"ms{i + 1}_{k + 1}", mx, my, ms, ms, "secondary"))
            left = mx + ms + 0.06 + 1.5 > xr
            lx = round(mx - 0.06 - 1.5, 2) if left else round(mx + ms + 0.06, 2)
            els.append(tx(ctx, meta, "decor", f"mt{i + 1}_{k + 1}", lx, round(my - 0.03, 2), 1.5, 0.24,
                          [Para([Run(mi["label"])], align="r" if left else "l", space_after=0)], LABEL, valign="m"))
    if b.get("today") is not None:
        tdx = round(x0 + b["today"] * mw, 2)
        els.append(vline(ctx, "decor", "today", tdx, round(y + 0.3, 2), round(y + h - y - 0.3, 2), "accent", 1.5))
        els.append(tx(ctx, meta, "decor", "today_label", round(tdx - 0.5, 2), round(y + 0.3, 2), 1.0, 0.3,
                      [Para([Run(b.get("today_label", "Today"), True, "accent")], align="c", space_after=0)], LABEL,
                      valign="m"))
    return base.solved(slide, ctx, "gantt", "timeline", els, meta)


# ---------------------------------------------------------------- issue_tree
@register("issue_tree", visual_type="tree", schema=_schema({
    "root": _STR,
    "branches": _arr(_obj({"name": _STR, "leaves": _arr({"type": "string", "maxLength": 70}, 2, 3)},
                          ["name", "leaves"]), 2, 3)}, ["root", "branches"]))
def build_issue_tree(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "issue_tree", "root", "branches")
    br = b["branches"]
    nl = sum(len(x["leaves"]) for x in br)
    ig, gg = 0.06, 0.25
    lh = round((h - (len(br) - 1) * gg - (nl - len(br)) * ig) / nl, 2)
    lh = min(lh, 0.62)
    groups, cy = [], y
    for bi, br_ in enumerate(br):
        k = len(br_["leaves"])
        gh = round(k * lh + (k - 1) * ig, 2)
        groups.append((cy, gh))
        cy = round(cy + gh + gg, 2)
    total = round(cy - gg - y, 2)
    y_off = round((h - total) / 2, 2)
    groups = [(round(g + y_off, 2), gh) for g, gh in groups]
    rx, rw = cols(0, 2)
    bx, bw = cols(4, 6)
    lx, lw = cols(8, 11)
    mid1, mid2 = round(grid_x(3) + grid_w(1) / 2, 2), round(grid_x(7) + grid_w(1) / 2, 2)
    root_h = 1.5
    root_cy = round(y + y_off + total / 2, 2)
    els.append(tx(ctx, meta, "label", "root", rx, round(root_cy - root_h / 2, 2), rw, root_h,
                  [Para([Run(b["root"], True, "background")], space_after=0)], BODY, valign="m", inset=0.15,
                  fill="accent"))
    centers = [round(g + gh / 2, 2) for g, gh in groups]
    els.append(hline(ctx, "connector", "r0", round(rx + rw, 2), root_cy, round(mid1 - rx - rw, 2)))
    els.append(vline(ctx, "connector", "v1", mid1, min(centers), round(max(centers) - min(centers), 2)))
    bh = 0.85
    for i, (bd, (g, gh), c) in enumerate(zip(br, groups, centers)):
        els.append(hline(ctx, "connector", f"b{i + 1}", mid1, c, round(bx - mid1, 2)))
        els.append(tx(ctx, meta, "label", i + 1, bx, round(c - bh / 2, 2), bw, bh,
                      [Para([Run(bd["name"], True, "background")], space_after=0)], BODY, valign="m", inset=0.12,
                      fill="secondary"))
        lc = [round(g + j * (lh + ig) + lh / 2, 2) for j in range(len(bd["leaves"]))]
        els.append(hline(ctx, "connector", f"l{i + 1}", round(bx + bw, 2), c, round(mid2 - bx - bw, 2)))
        els.append(vline(ctx, "connector", f"w{i + 1}", mid2, min(lc + [c]), round(max(lc + [c]) - min(lc + [c]), 2)))
        for j, (leaf, c2) in enumerate(zip(bd["leaves"], lc)):
            els.append(hline(ctx, "connector", f"e{i + 1}_{j + 1}", mid2, c2, round(lx - mid2, 2)))
            els.append(tx(ctx, meta, "body", f"{i + 1}_{j + 1}", lx, round(c2 - lh / 2, 2), lw, lh,
                          [Para(base.figure_runs(leaf), space_after=0)], LABEL, valign="m", inset=0.06, fill="panel"))
    return base.solved(slide, ctx, "issue_tree", "tree", els, meta)


# ---------------------------------------------------------------- visual_text
@register("visual_text", visual_type="illustration", schema=_schema({
    "heading": _STR, "points": _arr(_STR, 2, 5), "callout": _STR}, ["points"]))
def build_visual_text(slide: dict, ctx: BuildContext):
    b, meta, els, y, h = _begin(slide, ctx, "visual_text", "points")
    pic = art(ctx, slide, grid_x(6), y, grid_w(6), h)
    paras = ([Para([Run(b["heading"], True)], space_after=8)] if b.get("heading") else []) + _bullets(b["points"])
    if pic:
        els.append(pic)
        tw = grid_w(6)
    elif b.get("callout"):
        els.append(tx(ctx, meta, "callout", "panel", grid_x(6), y, grid_w(6), h,
                      [Para(base.figure_runs(b["callout"]), space_after=0)], TITLE, font="major", valign="m",
                      inset=0.3, fill="panel"))
        tw = grid_w(6)
    else:
        tw = grid_x(12) - grid_x(0)
    els.append(tx(ctx, meta, "body", None, grid_x(0), y, tw, h, paras, BODY))
    return base.solved(slide, ctx, "visual_text", "illustration", els, meta)


# ---------------------------------------------------------------- appendix_divider
@register("appendix_divider", visual_type="divider", schema={
    "type": "object", "additionalProperties": False, "properties": {"contents": _arr(_STR, 1, 8)}})
def build_appendix_divider(slide: dict, ctx: BuildContext):
    b = slide.get("blocks") or {}
    meta: dict = {}
    pic = art(ctx, slide, grid_x(7), 0.0, round(CANVAS_W - grid_x(7), 2), CANVAS_H)
    w = grid_w(6) if pic else grid_w(10)
    els: list[Element] = [pic] if pic else []
    els.append(rect(ctx, "decor", "bar", grid_x(0), 1.9, 0.9, 0.08, "accent"))
    els.append(tx(ctx, meta, "divider", None, grid_x(0), 2.2, w, 1.5,
                  [Para([Run(slide.get("title", "Appendix"), True)], space_after=0)], SIZES["divider"], font="major"))
    if b.get("contents"):
        els.append(tx(ctx, meta, "divider", "contents", grid_x(0), 3.9, w, 2.6,
                      [Para([Run(c, False, "muted")], space_after=4) for c in b["contents"]], BODY))
    els += short_footer(ctx, 6, True) if pic else base.frame(slide, ctx, mode="divider")
    return base.solved(slide, ctx, "appendix_divider", "divider", els, meta)


# ---------------------------------------------------------------- examples (finance content)
EXAMPLES = {
    "exec_summary": {
        "title": "Atlas adds $412m of value if we close by Q2 2027", "source": "Deal team model v14",
        "sources": ["Deal team model v14, base case", "Seller management accounts, FY25"],
        "as_of": "2026-11-12",
        "blocks": {"subtitle": "Key findings, base case, $ million",
                   "insights": [
                       {"lead": "Value", "text": "Run-rate cost savings and revenue gains lift the standalone value [1]",
                        "figure": "+$412m"},
                       {"lead": "Returns", "text": "Base case IRR clears the hurdle rate with headroom to spare [1]",
                        "figure": "21.4%"},
                       {"lead": "Leverage", "text": "Net debt to EBITDA at close falls back inside covenant within two years [1]",
                        "figure": "3.1x"},
                       {"lead": "Risk", "text": "Two customers carry this share of revenue and both renew in 2027 [2]",
                        "figure": "38%"}],
                   "so_what": {"text": "Approve exclusivity now and price the two renewals into the final bid."}}},
    "agenda": {
        "title": "Today we decide on the bid, the financing and the timetable",
        "blocks": {"current": 1, "items": [
            {"title": "Situation and process", "detail": "Where we stand with the seller", "time": "10 min"},
            {"title": "Valuation and returns", "detail": "DCF, comps and sources of value", "time": "25 min"},
            {"title": "Financing and structure", "detail": "Debt package and covenants", "time": "15 min"},
            {"title": "Risks and diligence", "detail": "Customer concentration, carve-out costs", "time": "15 min"},
            {"title": "Decision and next steps", "detail": "Bid range and exclusivity", "time": "10 min"}]}},
    "kpi_row": {
        "title": "Unit economics improved on every measure in FY26", "source": "Management accounts",
        "sources": ["Management accounts, FY26 close", "Covenant schedule, facility agreement"],
        "as_of": "2026-09-30",
        "blocks": {"subtitle": "FY26 versus FY25, carve-out perimeter", "highlight": 1,
                   "kpis": [
                       {"label": "Revenue", "value": "$2.4bn", "context": "Price and mix lead [1]",
                        "change": {"text": "+8.2% YoY", "direction": "up"}},
                       {"label": "EBITDA margin", "value": "21.4%", "context": "Savings landed early",
                        "change": {"text": "+190 bps", "direction": "up"}},
                       {"label": "Net debt / EBITDA", "value": "3.1x", "context": "Covenant at 3.5x [2]",
                        "change": {"text": "+0.3x", "direction": "down"}},
                       {"label": "Cash conversion", "value": "82%", "context": "Working capital neutral",
                        "change": {"text": "flat", "direction": "flat"}}],
                   "so_what": "Margin is the story, with the gain in basis points the main lever; leverage is the watch item."}},
    "stat_hero": {
        "title": "Entering Saudi Arabia triples our addressable market", "source": "Market study, Bank research",
        "sources": ["Market study, SME lending model", "Bank research, regional lending outlook"],
        "as_of": "2026-10-31",
        "blocks": {"subtitle": "Addressable SME lending, 2026 to 2030, $ billion",
                   "stats": [{"value": "$14.8bn", "label": "SME lending pool by 2030",
                              "context": "CAGR of 11.6% from $8.6bn in 2026 [1]"},
                             {"value": "3.1x", "label": "Market size versus current footprint",
                              "context": "Egypt and UAE combined stand at $4.8bn [2]"}],
                   "so_what": "Enter in 2027 through a partnership licence, then build the branch network."}},
    "quote": {
        "title": "Customers back the platform but want faster onboarding",
        "blocks": {"quote": "We would double our volume with them tomorrow if onboarding took days, not months.",
                   "attribution": "Group Treasurer, tier-one corporate client",
                   "role": "Customer interview, October 2026"}},
    "recommendation": {
        "title": "Close the deal in three phases over nine months",
        "source": "Deal team plan v6", "as_of": "2026-11-12",
        "blocks": {"phases": [
            {"label": "Now", "window": "next 30 days", "owner": "Deal lead", "date": "15 Dec 2026",
             "actions": ["Sign exclusivity at $1.62bn EV", "Launch confirmatory diligence on two customers",
                         "Lock the $900m debt commitment"]},
            {"label": "Next", "window": "days 30 to 120", "owner": "CFO", "date": "28 Feb 2027",
             "actions": ["Finalise the SPA and the TSA scope", "Agree the $85m cost savings plan",
                         "File merger control in three markets"]},
            {"label": "Later", "window": "days 120 to 270", "owner": "COO", "date": "30 Aug 2027",
             "actions": ["Close and separate the IT estate", "Run the 100-day integration plan",
                         "Report first savings captured to the board"]}]}},
    "takeaway_box": {
        "title": "We recommend a $1.62bn bid with price protection on two renewals",
        "source": "Deal team model v14", "as_of": "2026-11-12",
        "blocks": {"decision": "Approve a bid of $1.62bn EV, with a 5% earn-out on the two renewals",
                   "rationale": ["Returns: base case IRR clears the hurdle rate with room to spare",
                                 "Savings: run-rate cost savings are mostly identified bottom-up",
                                 "Strategy: adds a meaningful share of the Gulf payments market"],
                   "risks": ["Concentration: 38% of revenue from two clients, mitigated by the earn-out",
                             "Separation: $120m one-off cost, capped in the SPA"]}},
    "two_column_compare": {
        "title": "Option B is worth more than Option A but needs more time",
        "source": "Deal team valuation", "as_of": "2026-11-12",
        "blocks": {"emphasis": "b",
                   "a": {"heading": "Option A: sell in 2027", "metric": "$1.45bn",
                         "points": ["Value: a lower multiple on the current run rate",
                                    "Timing: signing by Q2 2027", "Risk: low, one buyer at exclusivity"]},
                   "b": {"heading": "Option B: carve out and list", "metric": "$1.51bn",
                         "points": ["Value: a higher multiple after two years of margin gains",
                                    "Timing: listing in Q1 2028", "Risk: market window and separation cost"]},
                   "verdict": "Option A wins on risk-adjusted value; revisit Option B if bids fall below $1.4bn."}},
    "numbered_insights": {
        "title": "Four drivers explain the margin gain and three of them repeat",
        "source": "Management accounts", "as_of": "2026-09-30",
        "blocks": {"insights": [
            {"title": "Pricing", "text": "Gains from list increases, with churn held low", "figure": "+$38m"},
            {"title": "Procurement", "text": "Saved on the top suppliers by volume", "figure": "$22m"},
            {"title": "Mix", "text": "Cards and cash management now earn most of revenue", "figure": "61%"},
            {"title": "One-offs", "text": "Non-recurring recoveries will not repeat", "figure": "$9m"}]}},
    "process_flow": {
        "title": "Six steps take the carve-out from signing to day one",
        "source": "PMO plan v6", "as_of": "2026-11-12",
        "blocks": {"highlight": 2, "steps": [
            {"name": "Sign SPA", "output": "Signed SPA and TSA term sheet"},
            {"name": "Clear approvals", "output": "Merger control in 3 markets"},
            {"name": "Separate IT", "output": "Standalone core platform"},
            {"name": "Transfer staff", "output": "2,400 employees on new contracts"},
            {"name": "Fund the entity", "output": "$900m debt drawn"},
            {"name": "Go live", "output": "Day-one readiness sign-off"}]}},
    "gantt": {
        "title": "The programme closes in nine months with IT separation as the critical path",
        "source": "PMO plan v6", "as_of": "2026-11-12",
        "blocks": {"subtitle": "Workstreams by month, 2027", "today": 1.5,
                   "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
                   "workstreams": [
                       {"name": "Legal and SPA", "bars": [{"start": 0, "end": 2, "label": "Draft and sign"}],
                        "milestones": [{"month": 3, "label": "SPA signed"}]},
                       {"name": "Regulatory", "bars": [{"start": 2, "end": 6, "label": "Merger control"}],
                        "milestones": [{"month": 7, "label": "Approvals in"}]},
                       {"name": "IT separation", "bars": [{"start": 1, "end": 7, "label": "Platform split",
                                                          "highlight": True}],
                        "milestones": [{"month": 8, "label": "Cut-over"}]},
                       {"name": "People and TSA", "bars": [{"start": 3, "end": 8, "label": "Transfer"}],
                        "milestones": []},
                       {"name": "Financing", "bars": [{"start": 0, "end": 1}, {"start": 7, "end": 8}],
                        "milestones": [{"month": 8.9, "label": "Funds drawn"}]}]}},
    "issue_tree": {
        "title": "Entry works only if three questions all resolve in our favour",
        "source": "Market study; Acretia DCF model", "as_of": "2026-10-31",
        "blocks": {"root": "Should we enter the Saudi SME market in 2027?",
                   "branches": [
                       {"name": "Is the market attractive?", "leaves": ["Pool of $14.8bn by 2030",
                                                                        "Margins 220 bps above Egypt"]},
                       {"name": "Can we win?", "leaves": ["Licence via a local partner", "Product fit with SME needs",
                                                          "Pricing within 15% of incumbents"]},
                       {"name": "Does it pay back?", "leaves": ["Payback in 4.5 years", "Capital need of $160m"]}]}},
    "visual_text": {
        "title": "Digital onboarding cuts time to first transaction from weeks to days",
        "blocks": {"heading": "What changed in 2026",
                   "points": ["Time: first transaction within days of application",
                              "Cost: onboarding cost per client fell sharply",
                              "Volume: many more SMEs onboarded in the same team",
                              "Quality: KYC rejections fell"],
                   "callout": "Onboarding is no longer the bottleneck for growth"}},
    "appendix_divider": {"title": "Appendix",
                         "blocks": {"contents": ["A. Comparable companies", "B. Precedent transactions",
                                                 "C. DCF sensitivities", "D. Diligence findings"]}},
}
