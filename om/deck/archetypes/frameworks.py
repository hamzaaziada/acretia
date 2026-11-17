"""Table and framework archetypes (S3.3c): comparison, comps, sensitivity, 2x2, market map, tombstones,
harvey balls, risk heatmap, deal structure, timeline and scorecard.

Tables use the renderer's native table. Marks the renderer has no shape for are built from native parts:
harvey balls are native pie charts, dots/diamonds/triangles are glyph text boxes, outlines are unfilled rects and
connectors are straight orthogonal lines. Marks and annotations carry the `decor` role (data marks, exempt from
the column grid by contract); everything else sits on the 12-column grid.
"""
from __future__ import annotations

import math
import re
import statistics

from om.deck.archetypes import BuildContext, register
from om.deck.archetypes import base
from om.deck.metrics import measure, text_width
from om.deck.model import Element, Para, Run
from om.deck.theme import grid_w, grid_x

STRIP_H = 0.8
LABEL_H = 0.3
_NUM_RE = re.compile(r"^[\s+\-−($€£]*\d[\d,]*(?:\.\d+)?\s?(?:%|x|bn|mm|m|k|pp|bps)?\)?$")


# ---------------------------------------------------------------- shared helpers
def _S(props: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": {
        "subtitle": {"type": "string"}, "takeaway": {"type": "string"}, "bindings": {"type": "object"},
        "bindings_format": {"type": ["string", "object"]}, **props}}


def _strs(lo: int, hi: int) -> dict:
    return {"type": "array", "items": {"type": "string"}, "minItems": lo, "maxItems": hi}


def _setup(slide: dict, ctx: BuildContext, key: str, need_takeaway: bool = False):
    b = slide.get("blocks") or {}
    if not base.has_subtitle(slide):
        raise ValueError(f"{key}: blocks.subtitle (measure and unit) is required")
    if need_takeaway and not b.get("takeaway"):
        raise ValueError(f"{key}: blocks.takeaway (the so-what) is required")
    meta: dict = {}
    els = base.frame(slide, ctx, meta=meta)
    x, y, w, h = base.content_box(ctx, True)
    return b, meta, els, (x, y, w, h)


def _txt(ctx, meta, role, suffix, x, y, w, h, content, *, size=12, floor=12, align="l", valign="m", fill=None,
         line=None, inset=0.0, color="text", bold=False, bid=None) -> Element:
    paras = content if content and isinstance(content[0], Para) else [Para(content, align=align, space_after=0)]
    if isinstance(content, str):
        paras = [Para([Run(content, b=bold)], align=align, space_after=0)]
    paras, sz = base.fitted(paras, w, h, size=size, floor=floor, role=role, block_id=bid or f"{role} {suffix}",
                            inset=inset, meta=meta)
    return base.text_el(ctx, role, suffix, x, y, w, h, paras, sz, color=color, valign=valign, inset=inset, fill=fill,
                        line=line, kind="rect" if (fill or line) else "text")


def _strip(ctx, meta, els, b, box) -> float:
    """Takeaway strip at the bottom when blocks.takeaway is set. Returns the body height above it."""
    x, y, w, h = box
    if not b.get("takeaway"):
        return h
    els.append(_txt(ctx, meta, "callout", None, grid_x(0), round(y + h - STRIP_H, 2), grid_w(12), STRIP_H,
                    base.figure_runs(b["takeaway"]), size=14, floor=12, fill="panel", inset=0.15, bid="takeaway"))
    return round(h - STRIP_H - ctx.gap, 2)


def _finish(slide, ctx, archetype, visual_type, els, meta):
    if meta.get("fit_errors"):
        raise ValueError(f"{archetype}: " + "; ".join(meta["fit_errors"]))
    return base.solved(slide, ctx, archetype, visual_type, els, meta)


def _is_num(s) -> bool:
    return bool(_NUM_RE.match(str(s))) or str(s).strip() in ("n.a.", "n.m.", "")


def _aligns(columns, rows) -> list[str]:
    out = ["l"]
    for c in range(1, len(columns)):
        vals = [str(r[c]) for r in rows if c < len(r) and str(r[c]).strip()]
        out.append("r" if vals and all(_is_num(v) for v in vals) else "l")
    return out


def _col_widths(spec: dict, total: float) -> list[float]:
    try:
        from om.deck import render
        return render._col_widths(spec, total)
    except (ImportError, AttributeError):
        n = len(spec["columns"])
        ws = []
        for c in range(n):
            longest = max([len(str(spec["columns"][c]))] + [len(str(r[c])) for r in spec["rows"] if c < len(r)])
            ws.append(min(max(longest, 6), 28) * (1.5 if c == 0 else 1.0))
        return [total * v / sum(ws) for v in ws]


def _table(ctx, meta, els, name, x, y, w, avail, columns, rows, *, aligns=None, bold_rows=(), highlight=None,
           sizes=(14, 12), max_row=0.5, bindings=None, bindings_format=None) -> dict:
    """Add the native table; pick the largest size that fits; return geometry for overlays."""
    spec_rows = [[str(c) for c in r] for r in rows]
    cws = _col_widths({"columns": columns, "rows": spec_rows}, w)
    nr = len(spec_rows) + 1
    chosen, need = None, 0.0
    for size in sizes:
        need = 0.0
        for r in [columns] + spec_rows:
            for c, t in enumerate(r):
                m = measure(str(t), size, cws[c] - 0.16, bold=True, rtl=ctx.rtl)
                need = max(need, m.height_in + 0.1)
        if need * nr <= avail + 1e-6:
            chosen = size
            break
    if chosen is None:
        meta.setdefault("fit_errors", []).append(
            f"table {name} needs {need * nr:.2f} in for {nr} rows, {avail:.2f} in available; cut rows or columns")
        chosen = sizes[-1]
    row_h = round(max(min(avail / nr, max_row), need), 3)
    spec = {"columns": list(columns), "rows": spec_rows, "size": chosen,
            "col_align": aligns or _aligns(columns, spec_rows), "bold_rows": list(bold_rows)}
    if highlight is not None:
        spec["highlight_col"] = highlight
    binding = ({"kind": "table", "bindings": dict(bindings), "header_rows": 1,
                **({"format": bindings_format} if bindings_format else {})} if bindings else None)
    els.append(Element(base.eid(ctx, name), "table", name, round(x, 2), round(y, 2), round(w, 2),
                       round(row_h * nr, 3), table=spec, binding=binding))
    xs = [x]
    for cw in cws:
        xs.append(xs[-1] + cw)
    return {"xs": xs, "cws": cws, "row_h": row_h, "y": y, "x": x, "w": w, "h": row_h * nr, "size": chosen, "nr": nr}


def _decor(ctx, suffix, x, y, w, h, **kw) -> Element:
    return Element(base.eid(ctx, "decor", suffix), kw.pop("kind", "rect"), "decor", round(x, 2), round(y, 2),
                   round(w, 2), round(h, 2), **kw)


def _glyph(ctx, meta, suffix, glyph, cx, cy, size=14, color="accent", box=0.3, bold=False):
    paras = [Para([Run(glyph, b=bold, color=color)], align="c", space_after=0)]
    paras, sz = base.fitted(paras, box, box, size=size, floor=size, role="decor", block_id=f"mark {suffix}", meta=meta)
    return base.text_el(ctx, "decor", suffix, cx - box / 2, cy - box / 2, box, box, paras, sz, valign="m")


def _fmt_money(v, digits=1) -> str:
    return "n.a." if v is None else f"${v:,.{digits}f}bn"


def _fmt_x(v) -> str:
    return "n.a." if v is None else f"{v:.1f}x"


def _fmt_pct(v) -> str:
    return "n.a." if v is None else f"{v:.1f}%"


def _axes(ctx, meta, els, mc0, mspan, my, mh, xname, yname, xlevels, ylevels):
    """Axis names and end labels around a matrix that spans columns mc0..mc0+mspan-1 at y my, height mh."""
    mx, mw = grid_x(mc0), grid_w(mspan)
    els.append(_txt(ctx, meta, "label", "yname", mx, round(my - LABEL_H, 2), mw, LABEL_H,
                    [Run("↑ " + yname, b=True)], bid="y axis"))
    els.append(_txt(ctx, meta, "label", "yhigh", grid_x(0), my, grid_w(1), LABEL_H, [Run(ylevels[1])], align="r",
                    valign="t", bid="y high"))
    els.append(_txt(ctx, meta, "label", "ylow", grid_x(0), round(my + mh - LABEL_H, 2), grid_w(1), LABEL_H,
                    [Run(ylevels[0])], align="r", valign="b", bid="y low"))
    by = round(my + mh + 0.05, 2)
    els.append(_txt(ctx, meta, "label", "xlow", mx, by, grid_w(1), LABEL_H, [Run(xlevels[0])], bid="x low"))
    els.append(_txt(ctx, meta, "label", "xname", grid_x(mc0 + 1), by, grid_w(mspan - 2), LABEL_H,
                    [Run(xname + " →", b=True)], align="c", bid="x axis"))
    els.append(_txt(ctx, meta, "label", "xhigh", grid_x(mc0 + mspan - 1), by, grid_w(1), LABEL_H,
                    [Run(xlevels[1])], align="r", bid="x high"))


# ---------------------------------------------------------------- comparison_table
@register("comparison_table", data=True, visual_type="table", schema=_S({
    "options": _strs(2, 5),
    "rows": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
        "type": "object", "additionalProperties": False, "required": ["criterion", "values"],
        "properties": {"criterion": {"type": "string"}, "values": {"type": "array", "items": {"type": ["string", "number"]}}}}},
    "verdict": _strs(2, 5), "highlight": {"type": "integer", "minimum": 0},
    "criterion_header": {"type": "string"}, "verdict_label": {"type": "string"},
}, ["subtitle", "options", "rows", "verdict", "highlight", "takeaway"]))
def build_comparison_table(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "comparison_table", True)
    n = len(b["options"])
    if not 0 <= b["highlight"] < n or len(b["verdict"]) != n or any(len(r["values"]) != n for r in b["rows"]):
        raise ValueError("comparison_table: highlight, verdict and every row need one value per option")
    body = _strip(ctx, meta, els, b, box)
    rows = [[r["criterion"], *r["values"]] for r in b["rows"]] + [[b.get("verdict_label", "Verdict"), *b["verdict"]]]
    cols = [b.get("criterion_header", "Criterion"), *b["options"]]
    g = _table(ctx, meta, els, "table", box[0], box[1], box[2], body, cols, rows, bold_rows=[len(rows) - 1],
               highlight=b["highlight"] + 1, bindings=b.get("bindings"), bindings_format=b.get("bindings_format"))
    hx, hw = g["xs"][b["highlight"] + 1], g["cws"][b["highlight"] + 1]
    els.append(Element(base.eid(ctx, "rule", "highlight"), "line", "rule", round(hx, 2), round(g["y"] + g["h"], 2),
                       round(hw, 2), 0.0, line=("accent", 2.25)))
    return _finish(slide, ctx, "comparison_table", "table", els, meta)


# ---------------------------------------------------------------- comps_table
COMPS_COLUMNS = ["Company", "EV ($bn)", "EV/EBITDA NTM", "P/E NTM", "Revenue growth", "EBITDA margin"]
_COMPS_KEYS = ["ev", "ev_ebitda", "pe", "growth", "margin"]


def comps_stats(rows: list[dict]) -> dict:
    """Median and mean per numeric column, ignoring missing values."""
    out = {"median": {}, "mean": {}}
    for k in _COMPS_KEYS:
        vals = [r[k] for r in rows if r.get(k) is not None]
        out["median"][k] = statistics.median(vals) if vals else None
        out["mean"][k] = statistics.fmean(vals) if vals else None
    return out


def _comps_row(label: str, r: dict) -> list[str]:
    return [label, _fmt_money(r.get("ev")), _fmt_x(r.get("ev_ebitda")), _fmt_x(r.get("pe")),
            _fmt_pct(r.get("growth")), _fmt_pct(r.get("margin"))]


_NUM_OPT = {"type": ["number", "null"]}
_COMP_STATS = {"type": "object", "additionalProperties": False,
               "properties": {k: _NUM_OPT for k in _COMPS_KEYS}}


@register("comps_table", data=True, visual_type="table", schema=_S({
    "rows": {"type": "array", "minItems": 3, "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["company"],
        "properties": {"company": {"type": "string"}, **{k: _NUM_OPT for k in _COMPS_KEYS}}}},
    "compute_stats": {"type": "boolean"}, "median": _COMP_STATS, "mean": _COMP_STATS, "dense": {"type": "boolean"},
}, ["subtitle", "rows", "takeaway"]))
def build_comps_table(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "comps_table", True)
    stats = comps_stats(b["rows"]) if b.get("compute_stats") else {"median": b.get("median"), "mean": b.get("mean")}
    if not stats["median"] or not stats["mean"]:
        raise ValueError("comps_table: give median and mean, or set compute_stats true")
    body = _strip(ctx, meta, els, b, box)
    for kind in ("median", "mean"):       # computed or supplied statistics are archetype output: declare them
        for k in _COMPS_KEYS:
            v = (stats[kind] or {}).get(k)
            if v is not None:
                base.declare(meta, v, *[f"blocks.rows[{i}].{k}" for i in range(len(b["rows"]))])
    rows = [_comps_row(r["company"], r) for r in b["rows"]]
    rows += [_comps_row("Median", stats["median"]), _comps_row("Mean", stats["mean"])]
    sizes = (14, 12, 10) if (b.get("dense") or ctx.dense) else (14, 12)
    _table(ctx, meta, els, "table", box[0], box[1], box[2], body, COMPS_COLUMNS, rows,
           aligns=["l"] + ["r"] * 5, bold_rows=[len(rows) - 2, len(rows) - 1], highlight=2, sizes=sizes,
           max_row=0.42, bindings=b.get("bindings"), bindings_format=b.get("bindings_format"))
    return _finish(slide, ctx, "comps_table", "table", els, meta)


# ---------------------------------------------------------------- sensitivity_table
@register("sensitivity_table", data=True, visual_type="table", schema=_S({
    "row_label": {"type": "string"}, "col_label": {"type": "string"},
    "row_values": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 7},
    "col_values": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 7},
    "values": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
    "base": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 2, "maxItems": 2},
    "axis_format": {"type": "string"}, "value_format": {"type": "string"},
}, ["subtitle", "row_label", "col_label", "row_values", "col_values", "values", "base", "takeaway"]))
def build_sensitivity_table(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "sensitivity_table", True)
    rv, cv, vals = b["row_values"], b["col_values"], b["values"]
    bi, bj = b["base"]
    if len(vals) != len(rv) or any(len(r) != len(cv) for r in vals) or not (bi < len(rv) and bj < len(cv)):
        raise ValueError("sensitivity_table: values must be rows x cols and base must index a cell")
    af, vf = b.get("axis_format", "{:.1f}%"), b.get("value_format", "${:,.2f}")
    body = _strip(ctx, meta, els, b, box)
    top = box[1] + LABEL_H
    cols = [b["row_label"]] + [af.format(v) for v in cv]
    rows = [[af.format(rv[i])] + [vf.format(v) for v in vals[i]] for i in range(len(rv))]
    g = _table(ctx, meta, els, "table", box[0], top, box[2], body - LABEL_H, cols, rows,
               aligns=["l"] + ["r"] * len(cv), sizes=(14, 12), max_row=0.5, bindings=b.get("bindings"), bindings_format=b.get("bindings_format"))
    x0, x1 = g["xs"][1], g["xs"][-1]
    els.append(_txt(ctx, meta, "decor", "collabel", x0, box[1], x1 - x0, LABEL_H, [Run(b["col_label"] + " →", b=True)],
                    align="c", bid="column axis"))
    rh = g["row_h"]
    els.append(_decor(ctx, "base", g["xs"][bj + 1], top + (bi + 1) * rh, g["cws"][bj + 1], rh, line=("accent", 2.25)))
    return _finish(slide, ctx, "sensitivity_table", "table", els, meta)


# ---------------------------------------------------------------- matrix_2x2
_AXIS = {"type": "object", "additionalProperties": False, "required": ["label"], "properties": {
    "label": {"type": "string"}, "low": {"type": "string"}, "high": {"type": "string"}}}


@register("matrix_2x2", visual_type="matrix", schema=_S({
    "x_axis": _AXIS, "y_axis": _AXIS, "quadrants": _strs(4, 4), "target": {"type": "integer", "minimum": 0, "maximum": 3},
    "items": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "xv", "yv"],
        "properties": {"label": {"type": "string"}, "xv": {"type": "number", "minimum": 0, "maximum": 1},
                       "yv": {"type": "number", "minimum": 0, "maximum": 1}, "highlight": {"type": "boolean"}}}},
}, ["subtitle", "x_axis", "y_axis", "quadrants", "target", "items", "takeaway"]))
def build_matrix_2x2(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "matrix_2x2", True)
    x, y, w, h = box
    my, mh = y + LABEL_H, h - 2 * LABEL_H - 0.05
    mx, mw = grid_x(1), grid_w(8)
    qw, qh = grid_w(4), round((mh - 0.2) / 2, 2)
    xa, ya = b["x_axis"], b["y_axis"]
    _axes(ctx, meta, els, 1, 8, my, mh, xa["label"], ya["label"], (xa.get("low", "Low"), xa.get("high", "High")),
          (ya.get("low", "Low"), ya.get("high", "High")))
    # quadrant order: top-left, top-right, bottom-left, bottom-right
    pos = [(grid_x(1), my), (grid_x(5), my), (grid_x(1), my + qh + 0.2), (grid_x(5), my + qh + 0.2)]
    for i, (qx, qy) in enumerate(pos):
        els.append(_txt(ctx, meta, "quadrant", i + 1, qx, qy, qw, qh, [Run(b["quadrants"][i], b=True)], valign="t",
                        fill="panel" if i == b["target"] else None, line=("mute_bar", 0.75), inset=0.1,
                        bid=f"quadrant {i + 1}"))
    placed: list[tuple[float, float, float, float]] = []
    for i, it in enumerate(b["items"]):
        label = it["label"]
        bw = round(text_width(label, 12, bold=bool(it.get("highlight"))) + 0.45, 2)
        px = mx + it["xv"] * (qw * 2 + 0.2)
        py = my + (1 - it["yv"]) * (qh * 2 + 0.2)
        qy = my if it["yv"] >= 0.5 else my + qh + 0.2
        py = min(max(py, qy + 0.42), qy + qh - 0.2)
        right = px + bw > mx + 2 * qw + 0.2 - 0.05
        bx = px - bw + 0.3 if right else px - 0.15
        by = py - 0.14
        for _ in range(6):
            if any(bx < ox + ow and bx + bw > ox and by < oy + oh and by + 0.28 > oy for ox, oy, ow, oh in placed):
                by += 0.3
        by = min(by, qy + qh - 0.3)
        placed.append((bx, by, bw, 0.28))
        hi = bool(it.get("highlight"))
        dot = Run("●", color="accent" if hi else "secondary")
        lab = Run(label, b=hi)
        runs = [lab, Run(" "), dot] if right else [dot, Run(" "), lab]
        els.append(_txt(ctx, meta, "decor", f"item{i + 1}", bx, by, bw, 0.28, runs, align="r" if right else "l",
                        bid=f"item {i + 1}"))
    tx = grid_x(9)
    els.append(_txt(ctx, meta, "callout", None, tx, my, grid_w(3), round(mh, 2), base.figure_runs(b["takeaway"]),
                    size=14, floor=12, fill="panel", inset=0.2, valign="m", bid="takeaway"))
    return _finish(slide, ctx, "matrix_2x2", "matrix", els, meta)


# ---------------------------------------------------------------- market_map
@register("market_map", visual_type="map", schema=_S({
    "segments": {"type": "array", "minItems": 2, "maxItems": 6, "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "players"], "properties": {
            "name": {"type": "string"},
            "players": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
                "type": "object", "additionalProperties": False, "required": ["name"],
                "properties": {"name": {"type": "string"}, "client": {"type": "boolean"}}}}}}},
}, ["subtitle", "segments"]))
def build_market_map(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "market_map")
    segs = b["segments"]
    span = {2: 6, 3: 4, 4: 3, 6: 2}.get(len(segs))
    if span is None:
        raise ValueError("market_map: 2, 3, 4 or 6 segments fit the grid")
    body = _strip(ctx, meta, els, b, box)
    x, y, w, h = box
    m = max(len(s["players"]) for s in segs)
    cy = y + 0.55
    gap = 0.1
    ch = round(min(0.5, (body - 0.55 - (m - 1) * gap) / m), 2)
    if ch < 0.32:
        raise ValueError("market_map: too many players for the height")
    for i, s in enumerate(segs):
        sx, sw = grid_x(i * span), grid_w(span)
        els.append(_txt(ctx, meta, "label", f"seg{i + 1}", sx, y, sw, 0.45, [Run(s["name"], b=True)], size=14,
                        valign="m", bid=f"segment {i + 1}"))
        els.append(Element(base.eid(ctx, "rule", f"seg{i + 1}"), "line", "rule", sx, round(y + 0.5, 2), sw, 0.0,
                           line=("text", 0.75)))
        for j, p in enumerate(s["players"]):
            cl = bool(p.get("client"))
            els.append(_txt(ctx, meta, "chip", f"{i + 1}_{j + 1}", sx, round(cy + j * (ch + gap), 2), sw, ch,
                            [Run(p["name"], b=cl, color="background" if cl else None)], align="c",
                            fill="accent" if cl else "panel", inset=0.05, bid=f"chip {i + 1}.{j + 1}"))
    return _finish(slide, ctx, "market_map", "map", els, meta)


# ---------------------------------------------------------------- tombstones
@register("tombstones", data=True, visual_type="grid", schema=_S({
    "deals": {"type": "array", "minItems": 3, "maxItems": 9, "items": {
        "type": "object", "additionalProperties": False, "required": ["acquirer", "target", "date", "ev", "multiple"],
        "properties": {"acquirer": {"type": "string"}, "target": {"type": "string"}, "date": {"type": "string"},
                       "ev": {"type": "number"}, "multiple": {"type": "number"}, "highlight": {"type": "boolean"}}}},
}, ["subtitle", "deals", "takeaway"]))
def build_tombstones(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "tombstones", True)
    body = _strip(ctx, meta, els, b, box)
    deals = b["deals"]
    rows = math.ceil(len(deals) / 3)
    for k in ("multiple", "ev"):          # statistics a takeaway may quote (median, mean, range) are computed from the deals
        vals = sorted(float(d[k]) for d in deals)
        mid = len(vals) // 2
        med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        src = [f"blocks.deals[{i}].{k}" for i in range(len(deals))]
        for v in (med, sum(vals) / len(vals), vals[0], vals[-1]):
            base.declare(meta, round(v, 1), *src)
    ph = round(min(1.3, (body - (rows - 1) * ctx.gap) / rows), 2)
    for i, d in enumerate(deals):
        r, c = divmod(i, 3)
        paras = [Para([Run(f"{d['acquirer']} / {d['target']}", b=True)], space_after=0),
                 Para(base.figure_runs(f"EV ${d['ev']:,.1f}bn, {d['multiple']:.1f}x EBITDA, {d['date']}"),
                      space_after=0)]
        els.append(_txt(ctx, meta, "tombstone", i + 1, grid_x(c * 4), round(box[1] + r * (ph + ctx.gap), 2),
                        grid_w(4), ph, paras, size=14, floor=12, valign="m", inset=0.15,
                        fill="key_message" if d.get("highlight") else "panel", bid=f"deal {i + 1}"))
    return _finish(slide, ctx, "tombstones", "grid", els, meta)


# ---------------------------------------------------------------- harvey_table
def harvey_chart(v: float, hi: bool = False) -> dict:
    """Native pie spec for a harvey ball filled to fraction v (0, 0.25, 0.5, 0.75, 1)."""
    v = float(v)
    return {"type": "pie", "categories": ["Met", "Gap"], "labels": False, "legend": False,
            "series": [{"name": "Coverage", "values": [v, round(1 - v, 4)],
                        "point_colors": {"0": "accent" if hi else "text", "1": "mute_bar"}}]}


@register("harvey_table", data=True, visual_type="table", schema=_S({
    "peers": _strs(2, 6), "header_key": {"type": "string"}, "highlight": {"type": "integer", "minimum": 0},
    "capabilities": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "values"], "properties": {
            "name": {"type": "string"},
            "values": {"type": "array", "items": {"enum": [0, 0.25, 0.5, 0.75, 1]}}}}},
}, ["subtitle", "peers", "capabilities", "takeaway"]))
def build_harvey_table(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "harvey_table", True)
    n = len(b["peers"])
    if any(len(c["values"]) != n for c in b["capabilities"]):
        raise ValueError("harvey_table: every capability needs one value per peer")
    hi = b.get("highlight")
    body = _strip(ctx, meta, els, b, box)
    cols = [b.get("header_key", "Capability, full ball = fully met"), *b["peers"]]
    rows = [[c["name"]] + [""] * n for c in b["capabilities"]]
    g = _table(ctx, meta, els, "table", box[0], box[1], box[2], body, cols, rows, aligns=["l"] + ["c"] * n,
               highlight=None if hi is None else hi + 1, max_row=0.5)
    d = round(min(g["row_h"] - 0.08, 0.4), 2)
    for r, cap in enumerate(b["capabilities"]):
        for c, v in enumerate(cap["values"]):
            cx = g["xs"][c + 1] + g["cws"][c + 1] / 2
            cy = g["y"] + (r + 1.5) * g["row_h"]
            els.append(_decor(ctx, f"ball{r + 1}_{c + 1}", cx - d / 2, cy - d / 2, d, d, kind="chart",
                              chart=harvey_chart(v, hi == c)))
    return _finish(slide, ctx, "harvey_table", "table", els, meta)


# ---------------------------------------------------------------- risk_heatmap
_HEAT = ["panel", "key_message", "light", "series2"]


def _heat_token(score: int) -> str:
    return _HEAT[0 if score <= 4 else 1 if score <= 9 else 2 if score <= 14 else 3]


@register("risk_heatmap", data=True, visual_type="heatmap", schema=_S({
    "risks": {"type": "array", "minItems": 3, "maxItems": 8, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "likelihood", "impact"],
        "properties": {"label": {"type": "string"}, "likelihood": {"type": "integer", "minimum": 1, "maximum": 5},
                       "impact": {"type": "integer", "minimum": 1, "maximum": 5}}}},
    "likelihood_label": {"type": "string"}, "impact_label": {"type": "string"},
}, ["subtitle", "risks", "takeaway"]))
def build_risk_heatmap(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "risk_heatmap", True)
    body = _strip(ctx, meta, els, b, box)
    x, y, w, h = box
    my = y + LABEL_H
    mh = round(body - 2 * LABEL_H - 0.05, 2)
    _axes(ctx, meta, els, 1, 6, my, mh, b.get("likelihood_label", "Likelihood"), b.get("impact_label", "Impact"),
          ("Low", "High"), ("Low", "High"))
    mx, mw = grid_x(1), grid_w(6)
    g = 0.06
    cw, ch = (mw - 4 * g) / 5, (mh - 4 * g) / 5
    for imp in range(5, 0, -1):
        for lk in range(1, 6):
            els.append(_decor(ctx, f"cell{imp}_{lk}", mx + (lk - 1) * (cw + g), my + (5 - imp) * (ch + g), cw, ch,
                              fill=_heat_token(imp * lk)))
    slots: dict[tuple[int, int], int] = {}
    lines = []
    for i, r in enumerate(b["risks"]):
        key = (r["likelihood"], r["impact"])
        k = slots[key] = slots.get(key, -1) + 1
        if k > 2:
            raise ValueError("risk_heatmap: at most 3 risks per cell")
        d = min(0.3, ch - 0.08)
        cx0 = mx + (r["likelihood"] - 1) * (cw + g) + (cw - (3 * d + 0.12)) / 2 + k * (d + 0.06)
        cy0 = my + (5 - r["impact"]) * (ch + g) + (ch - d) / 2
        els.append(_txt(ctx, meta, "decor", f"dot{i + 1}", cx0, cy0, d, d, [Run(str(i + 1), b=True, color="background")],
                        align="c", fill="text", bid=f"risk {i + 1}"))
        lines.append(Para([Run(f"{i + 1}  ", b=True, color="accent")] + base.figure_runs(r["label"]), space_after=4))
    els.append(_txt(ctx, meta, "body", None, grid_x(7), my, grid_w(5), mh, lines, size=14, floor=12, valign="t",
                    bid="risk list"))
    return _finish(slide, ctx, "risk_heatmap", "heatmap", els, meta)


# ---------------------------------------------------------------- deal_structure
_AUTO = {1: [(4, 4)], 2: [(1, 4), (7, 4)], 3: [(1, 2), (5, 2), (9, 2)], 4: [(0, 2), (3, 2), (6, 2), (9, 2)]}


@register("deal_structure", visual_type="diagram", schema=_S({
    "entities": {"type": "array", "minItems": 3, "maxItems": 9, "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "label", "tier"], "properties": {
            "id": {"type": "string"}, "label": {"type": "string"}, "sub": {"type": "string"},
            "tier": {"type": "integer", "minimum": 0, "maximum": 2}, "col": {"type": "integer", "minimum": 0, "maximum": 11},
            "span": {"type": "integer", "minimum": 1, "maximum": 12}, "highlight": {"type": "boolean"}}}},
    "links": {"type": "array", "minItems": 2, "items": {
        "type": "object", "additionalProperties": False, "required": ["from", "to", "label"],
        "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "label": {"type": "string"}}}},
}, ["subtitle", "entities", "links"]))
def build_deal_structure(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "deal_structure")
    body = _strip(ctx, meta, els, b, box)
    x, y, w, h = box
    tiers = sorted({e["tier"] for e in b["entities"]})
    bh = 0.8
    pitch = (body - bh) / max(len(tiers) - 1, 1) if len(tiers) > 1 else 0
    geo: dict[str, tuple[float, float, float, float]] = {}
    for t in tiers:
        ents = [e for e in b["entities"] if e["tier"] == t]
        if any("col" not in e for e in ents):
            if len(ents) not in _AUTO:
                raise ValueError("deal_structure: at most 4 entities per tier without explicit col and span")
            for e, (c, s) in zip(ents, _AUTO[len(ents)]):
                e.setdefault("col", c)
                e.setdefault("span", s)
        ty = round(y + tiers.index(t) * pitch, 2)
        for e in ents:
            if e["col"] + e["span"] > 12:
                raise ValueError(f"deal_structure: entity {e['id']} leaves the grid")
            hi = bool(e.get("highlight"))
            col = "background" if hi else None
            paras = [Para([Run(e["label"], b=True, color=col)], align="c", space_after=0)]
            if e.get("sub"):
                paras.append(Para([Run(e["sub"], color=col)], align="c", space_after=0))
            ex, ew = grid_x(e["col"]), grid_w(e["span"])
            els.append(_txt(ctx, meta, "entity", e["id"], ex, ty, ew, bh, paras, size=14, floor=12, valign="m",
                            fill="accent" if hi else "panel", inset=0.08, bid=f"entity {e['id']}"))
            geo[e["id"]] = (ex, ty, ew, bh)
    for k, ln in enumerate(b["links"]):
        try:
            px, py, pw, ph = geo[ln["from"]]
            cx, cy, cw, _ = geo[ln["to"]]
        except KeyError as ex:
            raise ValueError(f"deal_structure: link refers to unknown entity {ex}") from None
        a, z = px + pw / 2, cx + cw / 2
        y0, y2 = py + ph, cy
        ym = round(y0 + (y2 - y0) / 2, 2)
        segs = [(a, y0, 0.0, ym - y0)]
        if abs(a - z) > 0.01:
            segs.append((min(a, z), ym, abs(a - z), 0.0))
        segs.append((z, ym, 0.0, y2 - ym))
        for s, (sx, sy, sw, sh) in enumerate(segs):
            els.append(Element(base.eid(ctx, "connector", f"{k + 1}_{s + 1}"), "line", "connector", round(sx, 2),
                               round(sy, 2), round(sw, 2), round(sh, 2), line=("text", 1.0)))
        els.append(_txt(ctx, meta, "decor", f"pct{k + 1}", z + 0.08, ym + (y2 - ym) / 2 - 0.13, 0.9, 0.26,
                        [Run(ln["label"], b=True)], bid=f"link {k + 1}"))
    return _finish(slide, ctx, "deal_structure", "diagram", els, meta)


# ---------------------------------------------------------------- timeline_milestones
@register("timeline_milestones", visual_type="timeline", schema=_S({
    "milestones": {"type": "array", "minItems": 4, "maxItems": 8, "items": {
        "type": "object", "additionalProperties": False, "required": ["date", "label"],
        "properties": {"date": {"type": "string"}, "label": {"type": "string"}, "highlight": {"type": "boolean"}}}},
}, ["subtitle", "milestones"]))
def build_timeline(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "timeline_milestones")
    body = _strip(ctx, meta, els, b, box)
    x, y, w, h = box
    ms = b["milestones"]
    n = len(ms)
    ay = round(y + body / 2, 2)
    els.append(Element(base.eid(ctx, "axis"), "line", "axis", grid_x(0), ay, grid_w(12), 0.0, line=("text", 1.5)))
    sp = grid_w(12) / n
    lh = round(body / 2 - 0.35, 2)
    for i, m in enumerate(ms):
        cx = grid_x(0) + (i + 0.5) * sp
        hi = bool(m.get("highlight"))
        els.append(_glyph(ctx, meta, f"diamond{i + 1}", "◆", cx, ay, size=14, color="accent" if hi else "secondary"))
        bw = round(min(2 * sp - 0.2, 2.6, 2 * (cx - grid_x(0)), 2 * (grid_x(12) - cx)), 2)
        above = i % 2 == 0
        paras = [Para([Run(m["date"], b=True, color="accent" if hi else None)], align="c", space_after=0),
                 Para([Run(m["label"])], align="c", space_after=0)]
        els.append(_txt(ctx, meta, "decor", f"label{i + 1}", cx - bw / 2, ay - 0.35 - lh if above else ay + 0.35, bw, lh,
                        paras, valign="b" if above else "t", bid=f"milestone {i + 1}"))
    return _finish(slide, ctx, "timeline_milestones", "timeline", els, meta)


# ---------------------------------------------------------------- scorecard
_KPI_FMT = {"pct": lambda v: f"{v:.1f}%", "usd_m": lambda v: f"${v:,.0f}m", "x": lambda v: f"{v:.1f}x",
            "num": lambda v: f"{v:,.0f}"}


def kpi_change(values: list[float], fmt: str) -> tuple[str, int]:
    """Latest vs prior period: text ('+1.2 pp' for pct, '+4.2%' otherwise) and direction (-1, 0, 1)."""
    a, z = values[-2], values[-1]
    if fmt == "pct":
        d = z - a
        txt = f"{d:+.1f} pp"
    else:
        d = (z - a) / abs(a) if a else 0.0
        txt = f"{d * 100:+.1f}%"
    return txt.replace("-", "−"), (d > 0) - (d < 0)


@register("scorecard", data=True, visual_type="table", schema=_S({
    "periods": _strs(3, 6),
    "kpis": {"type": "array", "minItems": 3, "maxItems": 6, "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "values", "format"], "properties": {
            "name": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}},
            "format": {"enum": list(_KPI_FMT)}, "good_up": {"type": "boolean"}}}},
}, ["subtitle", "periods", "kpis", "takeaway"]))
def build_scorecard(slide: dict, ctx: BuildContext):
    b, meta, els, box = _setup(slide, ctx, "scorecard", True)
    n = len(b["periods"])
    if any(len(k["values"]) != n for k in b["kpis"]):
        raise ValueError("scorecard: every KPI needs one value per period")
    body = _strip(ctx, meta, els, b, box)
    rows, dirs = [], []
    for k in b["kpis"]:
        txt, d = kpi_change(k["values"], k["format"])
        dirs.append(d)
        a_, z_ = k["values"][-2], k["values"][-1]
        base.declare(meta, abs(z_ - a_) if k["format"] == "pct" else (abs((z_ - a_) / abs(a_)) * 100 if a_ else 0.0),
                     f"blocks.kpis[{len(rows)}].values[-2]", f"blocks.kpis[{len(rows)}].values[-1]")
        rows.append([k["name"]] + [_KPI_FMT[k["format"]](v) for v in k["values"]] + [txt])
    g = _table(ctx, meta, els, "table", box[0], box[1], box[2], body, ["KPI", *b["periods"], "Change"], rows,
               aligns=["l"] + ["r"] * (n + 1), highlight=n, max_row=0.5, bindings=b.get("bindings"), bindings_format=b.get("bindings_format"))
    bx = 0.42
    for r, (k, d) in enumerate(zip(b["kpis"], dirs)):
        if d == 0:
            continue
        good = (d > 0) == k.get("good_up", True)
        cx = g["xs"][n + 1] + 0.1 + bx / 2
        cy = g["y"] + (r + 1.5) * g["row_h"]
        els.append(_glyph(ctx, meta, f"change{r + 1}", "▲" if d > 0 else "▼", cx, cy, size=24,
                          color="positive" if good else "negative", box=bx))
    return _finish(slide, ctx, "scorecard", "table", els, meta)


# ---------------------------------------------------------------- examples
EXAMPLES = {
    "comparison_table": {
        "title": "Option B delivers the highest value with the lowest execution risk",
        "source": "Management case; advisor analysis", "as_of": "2026-09-30",
        "sources": ["Management case, board pack Sep 2026", "Advisor analysis, option model v5"],
        "blocks": {
            "subtitle": "Strategic options, value and risk, $ billion",
            "options": ["Option A: sell", "Option B: merge", "Option C: hold"], "highlight": 1,
            "rows": [{"criterion": "Equity value", "values": ["$4.2bn", "$5.1bn", "$3.6bn"]},
                     {"criterion": "Net cost savings", "values": ["$0.0bn", "$0.4bn", "$0.1bn"]},
                     {"criterion": "Time to close", "values": ["6 months", "9 months [2]", "n.a."]},
                     {"criterion": "Execution risk", "values": ["Low", "Medium", "Low"]},
                     {"criterion": "Tax leakage", "values": ["$0.3bn", "$0.0bn", "$0.0bn"]}],
            "verdict": ["Lower value", "Recommended", "Value gap"],
            "takeaway": "Merge: $5.1bn of equity value, $0.9bn above a sale, with medium execution risk [1]."}},
    "comps_table": {
        "title": "Peers trade at a median 11.2x EBITDA, the benchmark for the target",
        "source": "FactSet consensus; company filings", "as_of": "2026-10-31",
        "sources": ["FactSet consensus, 31 Oct 2026", "Company filings, latest 10-K and 10-Q"],
        "blocks": {
            "subtitle": "Trading comparables, NTM multiples, EV in $ billion",
            "compute_stats": True, "dense": True,
            "rows": [{"company": "Northwind Systems", "ev": 18.4, "ev_ebitda": 14.2, "pe": 22.5, "growth": 9.1, "margin": 27.4},
                     {"company": "Contoso Group", "ev": 12.1, "ev_ebitda": 12.8, "pe": 19.9, "growth": 7.4, "margin": 24.8},
                     {"company": "Fabrikam Holdings", "ev": 9.6, "ev_ebitda": 11.5, "pe": 18.2, "growth": 6.2, "margin": 23.1},
                     {"company": "Adatum Partners", "ev": 7.3, "ev_ebitda": 10.9, "pe": 17.4, "growth": 5.8, "margin": 21.7},
                     {"company": "Litware Industries", "ev": 5.8, "ev_ebitda": 9.7, "pe": 15.9, "growth": 4.1, "margin": 19.5},
                     {"company": "Proseware Corp", "ev": 4.4, "ev_ebitda": 9.2, "pe": 14.6, "growth": 3.5, "margin": 18.2}],
            "takeaway": "Median EV/EBITDA is 11.2x [1]; applying it to the target implies upside to its current value."}},
    "sensitivity_table": {
        "title": "Value per share stays above $44 across the full WACC and growth range",
        "source": "Acretia DCF model", "as_of": "2026-09-30",
        "sources": ["Acretia DCF model v9, base case"],
        "blocks": {
            "subtitle": "Implied share price, WACC by terminal growth, $ per share",
            "row_label": "WACC", "col_label": "Terminal growth", "base": [2, 2],
            "row_values": [8.0, 8.5, 9.0, 9.5, 10.0], "col_values": [2.0, 2.5, 3.0, 3.5, 4.0],
            "values": [[58.10, 61.40, 65.30, 70.10, 76.20], [53.20, 55.90, 59.00, 62.80, 67.50],
                       [49.00, 51.20, 53.80, 56.90, 60.60], [45.40, 47.30, 49.50, 52.10, 55.20],
                       [42.30, 43.90, 45.80, 48.00, 50.60]],
            "takeaway": "Base case: $53.80 per share at 9.0% WACC and 3.0% terminal growth [1]."}},
    "matrix_2x2": {
        "title": "Two of six targets combine high attractiveness with a credible path to win",
        "blocks": {
            "subtitle": "Acquisition screen, market attractiveness by ability to win",
            "x_axis": {"label": "Ability to win"}, "y_axis": {"label": "Market attractiveness"}, "target": 1,
            "quadrants": ["Build selectively", "Pursue now", "Deprioritise", "Opportunistic"],
            "items": [{"label": "Helios", "xv": 0.82, "yv": 0.84, "highlight": True},
                      {"label": "Orbit", "xv": 0.68, "yv": 0.7},
                      {"label": "Vertex", "xv": 0.2, "yv": 0.78},
                      {"label": "Nimbus", "xv": 0.3, "yv": 0.2},
                      {"label": "Quanta", "xv": 0.78, "yv": 0.25},
                      {"label": "Zenith", "xv": 0.12, "yv": 0.42}],
            "takeaway": "Helios and Orbit clear both bars and form the shortlist for the next round of diligence."}},
    "market_map": {
        "title": "Our client is the only player present in all three payment segments",
        "blocks": {
            "subtitle": "Regional payments market, players by segment",
            "segments": [
                {"name": "Acquiring", "players": [{"name": "Meridian Pay", "client": True}, {"name": "Gulf Merchant"},
                                                  {"name": "Nile Acquire"}, {"name": "Atlas Card"}]},
                {"name": "Issuing", "players": [{"name": "Meridian Pay", "client": True}, {"name": "Crescent Bank"},
                                                {"name": "Delta Issuing"}]},
                {"name": "Wallets", "players": [{"name": "Meridian Pay", "client": True}, {"name": "Oasis Wallet"},
                                                {"name": "Falcon Pay"}, {"name": "Sahara Cash"}, {"name": "Palm Money"}]}]}},
    "tombstones": {
        "title": "Precedent deals cluster at 11x to 13x EBITDA for scaled regional platforms",
        "source": "Company announcements; Mergermarket", "as_of": "2026-10-31",
        "blocks": {
            "subtitle": "Precedent transactions, EV in $ billion, EV/EBITDA multiple",
            "deals": [{"acquirer": "Brookfield", "target": "Neoen", "date": "Mar 2025", "ev": 6.1, "multiple": 11.8},
                      {"acquirer": "Mubadala", "target": "Yellow Door", "date": "Jun 2025", "ev": 3.4, "multiple": 12.6},
                      {"acquirer": "ADQ", "target": "Aramex Logistics", "date": "Sep 2025", "ev": 2.2, "multiple": 10.9},
                      {"acquirer": "STC", "target": "Tamkeen Digital", "date": "Nov 2025", "ev": 1.9, "multiple": 13.1},
                      {"acquirer": "Our client", "target": "Delta Health", "date": "Feb 2026", "ev": 2.8, "multiple": 12.0,
                       "highlight": True},
                      {"acquirer": "PIF", "target": "Atlas Retail", "date": "Apr 2026", "ev": 4.7, "multiple": 11.4}],
            "takeaway": "Median 11.9x EBITDA; our client's Delta Health deal at 12.0x sits in line."}},
    "harvey_table": {
        "title": "Our client leads on four of six capabilities and trails only on distribution",
        "source": "Expert interviews; company materials", "as_of": "2026-09-30",
        "blocks": {
            "subtitle": "Capability coverage by player, harvey balls from none to full",
            "peers": ["Our client", "Peer A", "Peer B", "Peer C"], "highlight": 0,
            "capabilities": [{"name": "Product breadth", "values": [1, 0.75, 0.5, 0.5]},
                             {"name": "Technology platform", "values": [1, 0.5, 0.75, 0.25]},
                             {"name": "Regional coverage", "values": [0.75, 0.75, 0.5, 1]},
                             {"name": "Risk management", "values": [1, 0.75, 0.25, 0.5]},
                             {"name": "Distribution", "values": [0.5, 1, 0.75, 0.75]},
                             {"name": "Cost position", "values": [0.75, 0.5, 0.5, 0.25]}],
            "takeaway": "Distribution is the gap: 0.5 coverage against 1.0 for Peer A."}},
    "risk_heatmap": {
        "title": "Three risks sit in the high-impact corner and need mitigation before signing",
        "source": "Deal team risk workshop", "as_of": "2026-10-15",
        "blocks": {
            "subtitle": "Risk register, likelihood by impact, five-point scale",
            "risks": [{"label": "Regulatory approval delayed beyond 9 months", "likelihood": 4, "impact": 5},
                      {"label": "Customer churn above 8% after close", "likelihood": 3, "impact": 4},
                      {"label": "Key engineer attrition of 20%", "likelihood": 4, "impact": 3},
                      {"label": "Integration cost overrun of $40m", "likelihood": 3, "impact": 3},
                      {"label": "FX loss on EGP exposure", "likelihood": 2, "impact": 4},
                      {"label": "Financing terms widen by 75 bps", "likelihood": 2, "impact": 2}],
            "takeaway": "Regulatory delay is the largest exposure: likelihood 4 of 5 and impact 5 of 5."}},
    "deal_structure": {
        "title": "The deal runs through a Cayman holdco that owns 100% of the target",
        "source": "Draft term sheet v3", "as_of": "2026-10-31",
        "blocks": {
            "subtitle": "Post-closing structure, ownership percentages",
            "entities": [{"id": "sponsor", "label": "Sponsor fund", "sub": "Cayman LP", "tier": 0},
                         {"id": "co", "label": "Co-investor", "sub": "Sovereign fund", "tier": 0},
                         {"id": "holdco", "label": "Holdco", "sub": "Cayman Ltd", "tier": 1, "highlight": True},
                         {"id": "target", "label": "Target Co", "sub": "Egypt SAE", "tier": 2},
                         {"id": "sub", "label": "Operating sub", "sub": "KSA LLC", "tier": 2}],
            "links": [{"from": "sponsor", "to": "holdco", "label": "70%"}, {"from": "co", "to": "holdco", "label": "30%"},
                      {"from": "holdco", "to": "target", "label": "100%"}, {"from": "holdco", "to": "sub", "label": "100%"}]}},
    "timeline_milestones": {
        "title": "Signing in March keeps closing on track for the fourth quarter",
        "blocks": {
            "subtitle": "Transaction timeline, 2026 to 2027",
            "milestones": [{"date": "Jan 2026", "label": "Mandate signed"},
                           {"date": "Mar 2026", "label": "Signing", "highlight": True},
                           {"date": "Jun 2026", "label": "Regulatory filing"},
                           {"date": "Sep 2026", "label": "Shareholder vote"},
                           {"date": "Nov 2026", "label": "Closing", "highlight": True},
                           {"date": "Q1 2027", "label": "Integration milestone"}]}},
    "scorecard": {
        "title": "Margins improved while growth slowed in the latest quarter",
        "source": "Management accounts", "as_of": "2026-09-30",
        "sources": ["Management accounts, quarterly pack"],
        "blocks": {
            "subtitle": "KPI scorecard, last five quarters, latest quarter against prior",
            "periods": ["Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26"],
            "kpis": [{"name": "Revenue ($m)", "format": "usd_m", "values": [412, 430, 447, 466, 478]},
                     {"name": "EBITDA margin", "format": "pct", "values": [21.4, 21.9, 22.5, 23.1, 24.0]},
                     {"name": "Net debt / EBITDA", "format": "x", "values": [2.9, 2.8, 2.6, 2.5, 2.3], "good_up": False},
                     {"name": "Churn", "format": "pct", "values": [3.1, 3.0, 3.2, 3.3, 3.6], "good_up": False},
                     {"name": "Backlog ($m)", "format": "usd_m", "values": [980, 1010, 1040, 1070, 1055]}],
            "takeaway": "EBITDA margin rose 0.9 pp to 24.0%, but backlog slipped 1.4% and churn rose 0.3 pp."}},
}
