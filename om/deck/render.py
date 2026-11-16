"""python-pptx renderer: SolvedSlides + Theme -> .pptx bytes (native text, tables, charts; no effects)."""
from __future__ import annotations

import io
import json
import re
import zipfile

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (XL_AXIS_CROSSES, XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE,
                             XL_TICK_MARK)
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
from om.deck.theme import SCHEME_SLOTS, Theme

EMU = 914400
BINDINGS_RELTYPE = "http://acretia.ai/rel/bindings"
BINDINGS_PART = "/acretia/bindings.json"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_ENUM = {
    "dk1": MSO_THEME_COLOR.TEXT_1, "lt1": MSO_THEME_COLOR.BACKGROUND_1, "dk2": MSO_THEME_COLOR.TEXT_2,
    "lt2": MSO_THEME_COLOR.BACKGROUND_2, "accent1": MSO_THEME_COLOR.ACCENT_1, "accent2": MSO_THEME_COLOR.ACCENT_2,
    "accent3": MSO_THEME_COLOR.ACCENT_3, "accent4": MSO_THEME_COLOR.ACCENT_4, "accent5": MSO_THEME_COLOR.ACCENT_5,
    "accent6": MSO_THEME_COLOR.ACCENT_6,
}
_XML_SLOT = {"dk1": "tx1", "lt1": "bg1", "dk2": "tx2", "lt2": "bg2"}
_SLOT_ORDER = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_SERIES_SEQ = ["accent", "series2", "series3", "light", "secondary", "muted"]
_ALIGN = {"l": "l", "r": "r", "c": "ctr"}
_ANCHOR = {"t": "t", "m": "ctr", "c": "ctr", "b": "b"}


class RenderError(ValueError):
    pass


def _emu(v: float) -> Emu:
    return Emu(int(round(v * EMU)))


class _Ctx:
    def __init__(self, theme: Theme):
        self.theme = theme

    def hex(self, token: str) -> str:
        try:
            return self.theme.colors[token].lstrip("#")
        except KeyError:
            raise RenderError(f"unknown colour token {token!r}") from None

    def color(self, cf, token: str) -> None:
        slot = SCHEME_SLOTS.get(token)
        if slot:
            cf.theme_color = _ENUM[slot]
        else:
            cf.rgb = RGBColor.from_string(self.hex(token).upper())

    def clr_xml(self, token: str) -> str:
        slot = SCHEME_SLOTS.get(token)
        if slot:
            return f'<a:schemeClr xmlns:a="{_NS_A}" val="{_XML_SLOT.get(slot, slot)}"/>'
        return f'<a:srgbClr xmlns:a="{_NS_A}" val="{self.hex(token).upper()}"/>'


# ---------------------------------------------------------------- theme part

def _patch_theme(prs, theme: Theme) -> None:
    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    ns = {"a": _NS_A}
    cs = root.find(".//a:clrScheme", ns)
    for ch in list(cs):
        cs.remove(ch)
    cs.set("name", theme.name)
    inv = {v: k for k, v in SCHEME_SLOTS.items()}

    def add(tag: str, token: str) -> None:
        el = etree.SubElement(cs, f"{{{_NS_A}}}{tag}")
        etree.SubElement(el, f"{{{_NS_A}}}srgbClr").set("val", theme.colors[token].lstrip("#").upper())

    for slot in _SLOT_ORDER:
        add(slot, inv[slot])
    add("hlink", "accent")
    add("folHlink", "muted")
    fs = root.find(".//a:fontScheme", ns)
    fs.set("name", theme.name)
    for tag, role in (("majorFont", "major"), ("minorFont", "minor")):
        f = fs.find(f"a:{tag}", ns)
        for ch in list(f):
            f.remove(ch)
        etree.SubElement(f, f"{{{_NS_A}}}latin").set("typeface", theme.fonts[role])
        etree.SubElement(f, f"{{{_NS_A}}}ea").set("typeface", "")
        etree.SubElement(f, f"{{{_NS_A}}}cs").set("typeface", theme.fonts.get(f"{role}_cs", theme.fonts[role]))
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _open(template: str | None):
    if template is None:
        prs = Presentation()
        prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
        return prs
    with open(template, "rb") as fh:
        data = fh.read()
    if template.lower().endswith(".potx"):
        src = zipfile.ZipFile(io.BytesIO(data))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                blob = src.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    blob = blob.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
                dst.writestr(item, blob)
        data = out.getvalue()
    prs = Presentation(io.BytesIO(data))
    lst = prs.slides._sldIdLst
    for sld in list(lst):
        prs.part.drop_rel(sld.rId)
        lst.remove(sld)
    return prs


def _blank_layout(prs):
    return min(prs.slide_layouts, key=lambda l: len(l.placeholders))


# ---------------------------------------------------------------- text

def _has_arabic(spec: TextSpec) -> bool:
    return any(_ARABIC.search(r.t) for p in spec.paras for r in p.runs)


def _fill_text(tf, spec: TextSpec, cx: _Ctx, rtl: bool, *, align_override: dict | None = None) -> None:
    body = tf._txBody.find(qn("a:bodyPr"))
    for ch in list(body):
        body.remove(ch)
    ins = str(int(round(spec.inset * EMU)))
    body.set("wrap", "square")
    for k in ("lIns", "tIns", "rIns", "bIns"):
        body.set(k, ins)
    body.set("anchor", _ANCHOR.get(spec.valign, "t"))
    use_cs = rtl or _has_arabic(spec)
    face = "+mj" if spec.font == "major" else "+mn"
    for i, para in enumerate(spec.paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        align = para.align
        if rtl and align != "c":
            align = "r"
        pPr.set("algn", _ALIGN.get(align, "l"))
        if rtl:
            pPr.set("rtl", "1")
        indent = 0.25
        if para.bullet:
            pPr.set("marL", str(int(round((para.level + 1) * indent * EMU))))
            pPr.set("indent", str(-int(round(indent * EMU))))
        elif para.level:
            pPr.set("marL", str(int(round(para.level * indent * EMU))))
        p.space_after = Pt(para.space_after)
        if para.bullet:
            bf = etree.SubElement(pPr, qn("a:buFont"))
            bf.set("typeface", "Arial")
            etree.SubElement(pPr, qn("a:buChar")).set("char", "•")
        else:
            etree.SubElement(pPr, qn("a:buNone"))
        for run in para.runs:
            r = p.add_run()
            r.text = run.t
            f = r.font
            f.size = Pt(spec.size)
            f.bold = bool(run.b)
            cx.color(f.color, run.color or spec.color)
            f.name = f"{face}-lt"
            arabic = _ARABIC.search(run.t) is not None
            if use_cs or arabic:
                etree.SubElement(r._r.get_or_add_rPr(), qn("a:cs")).set("typeface", f"{face}-cs")
            if arabic:
                r._r.get_or_add_rPr().set("lang", "ar-SA")


def _strip_style(shape) -> None:
    el = shape._element
    st = el.find(qn("p:style"))
    if st is not None:
        el.remove(st)


def _set_fill_line(shape, el: Element, cx: _Ctx) -> None:
    if el.fill:
        shape.fill.solid()
        cx.color(shape.fill.fore_color, el.fill)
    else:
        shape.fill.background()
    if el.line:
        cx.color(shape.line.color, el.line[0])
        shape.line.width = Pt(el.line[1])
    else:
        shape.line.fill.background()


def _add_box(slide, el: Element, cx: _Ctx, rtl: bool) -> None:
    box = (_emu(el.x), _emu(el.y), _emu(el.w), _emu(el.h))
    if el.kind == "text":
        shp = slide.shapes.add_textbox(*box)
    else:
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *box)
    _strip_style(shp)
    shp.name = el.id
    _set_fill_line(shp, el, cx)
    if el.text:
        _fill_text(shp.text_frame, el.text, cx, rtl)


def _add_line(slide, el: Element, cx: _Ctx) -> None:
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, _emu(el.x), _emu(el.y), _emu(el.x + el.w), _emu(el.y + el.h))
    _strip_style(c)
    c.name = el.id
    token, width = el.line or ("text", 0.75)
    cx.color(c.line.color, token)
    c.line.width = Pt(width)


def _add_image(slide, el: Element) -> None:
    img = el.image or {}
    pic = slide.shapes.add_picture(io.BytesIO(img["png"]), _emu(el.x), _emu(el.y), _emu(el.w), _emu(el.h))
    pic.name = el.id
    pic._element.nvPicPr.cNvPr.set("descr", img.get("alt", ""))


# ---------------------------------------------------------------- tables

def _col_widths(spec: dict, total: float) -> list[float]:
    n = len(spec["columns"])
    weights = []
    for c in range(n):
        longest = max([len(str(spec["columns"][c]))] + [len(str(r[c])) for r in spec["rows"] if c < len(r)])
        weights.append(min(max(longest, 6), 28) * (1.5 if c == 0 else 1.0))
    s = sum(weights)
    return [total * w / s for w in weights]


def _cell_borders(tc, cx: _Ctx, bottom: bool) -> None:
    tcPr = tc.get_or_add_tcPr()
    for ch in list(tcPr):
        tcPr.remove(ch)
    for tag in ("lnL", "lnR", "lnT"):
        tcPr.append(parse_xml(f'<a:{tag} xmlns:a="{_NS_A}" w="0"><a:noFill/></a:{tag}>'))
    if bottom:
        tcPr.append(parse_xml(
            f'<a:lnB xmlns:a="{_NS_A}" w="6350" cap="flat" cmpd="sng"><a:solidFill>{cx.clr_xml("mute_bar")}</a:solidFill>'
            f'<a:prstDash val="solid"/></a:lnB>'))
    else:
        tcPr.append(parse_xml(f'<a:lnB xmlns:a="{_NS_A}" w="0"><a:noFill/></a:lnB>'))


def _add_table(slide, el: Element, cx: _Ctx, rtl: bool) -> None:
    spec = el.table or {}
    cols, rows = spec["columns"], spec["rows"]
    nr, nc = len(rows) + 1, len(cols)
    gf = slide.shapes.add_table(nr, nc, _emu(el.x), _emu(el.y), _emu(el.w), _emu(el.h))
    gf.name = el.id
    tbl = gf.table
    tbl.first_row = False
    tbl.horz_banding = False
    tblPr = tbl._tbl.tblPr
    for ch in tblPr.findall(qn("a:tableStyleId")):
        tblPr.remove(ch)
    for a in ("firstRow", "bandRow", "firstCol", "lastRow", "lastCol", "bandCol"):
        tblPr.set(a, "0")
    if rtl:
        tblPr.set("rtl", "1")
    for c, w in enumerate(_col_widths(spec, el.w)):
        tbl.columns[c].width = _emu(w)
    for r in range(nr):
        tbl.rows[r].height = _emu(el.h / nr)
    size = float(spec.get("size", 14))
    aligns = spec.get("col_align") or ["l"] + ["r"] * (nc - 1)
    bold_rows = set(spec.get("bold_rows", []))
    hi = spec.get("highlight_col")
    for r in range(nr):
        for c in range(nc):
            cell = tbl.cell(r, c)
            header = r == 0
            text = str(cols[c] if header else (rows[r - 1][c] if c < len(rows[r - 1]) else ""))
            a = aligns[c] if c < len(aligns) else "l"
            if rtl:
                a = {"l": "r", "r": "l"}.get(a, a)
            color = "background" if header else ("accent" if hi == c else "text")
            bold = header or (r - 1) in bold_rows or hi == c
            ts = TextSpec([Para([Run(text, b=bold, color=color)], align=a, space_after=0)], size, valign="m", inset=0.0)
            _fill_text(cell.text_frame, ts, cx, rtl)
            if rtl:  # rtl swapped alignment above; _fill_text forces r, restore requested one
                for p in cell.text_frame.paragraphs:
                    p._p.get_or_add_pPr().set("algn", _ALIGN[a])
            cell.vertical_anchor = 3  # MSO_ANCHOR.MIDDLE
            cell.margin_left = cell.margin_right = _emu(0.08)
            cell.margin_top = cell.margin_bottom = _emu(0.04)
            _cell_borders(cell._tc, cx, bottom=not header)
            tcPr = cell._tc.get_or_add_tcPr()
            if header:
                tcPr.append(parse_xml(f'<a:solidFill xmlns:a="{_NS_A}">{cx.clr_xml("text")}</a:solidFill>'))
            else:
                tcPr.append(parse_xml(f'<a:noFill xmlns:a="{_NS_A}"/>'))
            tcPr.set("anchor", "ctr")


# ---------------------------------------------------------------- charts

_TYPES = {
    "bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "stacked_bar": XL_CHART_TYPE.BAR_STACKED, "stacked_column": XL_CHART_TYPE.COLUMN_STACKED,
    "line": XL_CHART_TYPE.LINE, "area": XL_CHART_TYPE.AREA, "scatter": XL_CHART_TYPE.XY_SCATTER,
    "pie": XL_CHART_TYPE.PIE, "doughnut": XL_CHART_TYPE.DOUGHNUT, "waterfall": XL_CHART_TYPE.COLUMN_STACKED,
    "football_field": XL_CHART_TYPE.BAR_STACKED, "combo": XL_CHART_TYPE.COLUMN_CLUSTERED,
}
_HORIZONTAL = {"bar", "stacked_bar", "football_field"}
_STACKED = {"stacked_bar", "stacked_column", "waterfall", "football_field"}
MINUS = "−"
GAP_WIDTH = 60
MIN_LABEL_CONTRAST = 4.5


def fmt_number(v: float, number_format: str) -> str:
    """Format v like the Excel number format would: placeholders, thousands comma, percent, quoted literals."""
    m = re.search(r"[#0,]*0(?:\.0+)?", number_format)
    if not m:
        return f"{v:g}"
    pre, post = number_format[:m.start()], number_format[m.end():]
    pct = "%" in re.sub(r'"[^"]*"', "", pre + post)
    lit = lambda t: re.sub(r'"([^"]*)"', r"\1", t).replace("\\", "")
    dec = len(m.group(0).split(".")[1]) if "." in m.group(0) else 0
    body = f"{abs(v) * (100 if pct else 1):{',' if ',' in m.group(0) else ''}.{dec}f}"
    return ("-" if v < 0 else "") + lit(pre) + body + lit(post)


def _lin(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex6: str) -> float:
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two 6-digit hex colours."""
    la, lb = _lum(a.lstrip("#")), _lum(b.lstrip("#"))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def label_token(cx: "_Ctx", fill_token: str | None) -> str:
    """Text token with the best contrast against a fill: `background` on dark fills, `text` on light ones."""
    if not fill_token:
        return "text"
    f = cx.hex(fill_token)
    return "background" if contrast(cx.hex("background"), f) > contrast(cx.hex("text"), f) else "text"


def _signed(v: float, nf: str) -> str:
    body = fmt_number(abs(v), nf)
    return ("+" if v >= 0 else MINUS) + body


def _plan_waterfall(spec: dict) -> list[dict]:
    cats = spec["categories"]
    vals = [float(v or 0) for v in spec["series"][0]["values"]]
    totals = set(spec.get("totals", [0, len(vals) - 1]))
    nf = spec.get("number_format", "0.0")
    n = len(vals)
    base, up, down, tot = [None] * n, [None] * n, [None] * n, [None] * n
    tops, texts = [0.0] * n, [""] * n
    run = 0.0
    for i, v in enumerate(vals):
        if i in totals:
            if i != 0 and abs(run - v) > 1e-6 * max(1.0, abs(v)):
                raise RenderError(f"waterfall does not foot at {cats[i]!r}: steps sum to {run}, total is {v}")
            run = v
            tot[i] = v
            tops[i] = v
            texts[i] = fmt_number(v, nf)
        else:
            new = run + v
            if min(run, new) < -1e-9:
                raise RenderError("waterfall running total crosses zero; not supported")
            base[i] = min(run, new)
            (up if v >= 0 else down)[i] = abs(v)
            tops[i] = max(run, new)
            texts[i] = _signed(v, nf)
            run = new
    plan = [
        {"name": "Base", "values": base, "hidden": True},
        {"name": "Increase", "values": up, "color": "positive", "labels": True, "fmt": f'"+"{nf}'},
        {"name": "Decrease", "values": down, "color": "negative", "labels": True, "fmt": f'"{MINUS}"{nf}'},
        {"name": "Total", "values": tot, "color": "secondary", "labels": True},
    ]
    if spec.get("labels_above"):
        peak = max(tops) or 1.0
        axis_max = float(spec.get("axis_max") or peak * 1.2)
        pad = round(axis_max * 0.09, 6)
        for p in plan[1:]:
            p["labels"] = False
        plan.append({"name": "Label", "values": [pad] * n, "hidden": True, "labels": True, "custom": texts,
                     "label_pos": "inBase", "label_token": "text"})
    else:
        for p, key in zip(plan[1:], ("up", "down", "tot")):
            p["small_below"] = 0.07 * (float(spec.get("axis_max") or max(tops) * 1.05 or 1.0))
    return plan


def _plan_football(spec: dict) -> tuple[list[dict], list[str]]:
    if len(spec["series"]) < 2:
        raise RenderError("football_field needs two series: low and high")
    lo, hi = spec["series"][0]["values"], spec["series"][1]["values"]
    fmt = spec.get("number_format", "0.0")
    width = [None if a is None or b is None else b - a for a, b in zip(lo, hi)]
    texts = [f"{fmt_number(a, fmt)}\u2013{fmt_number(b, fmt)}" if a is not None and b is not None else ""
             for a, b in zip(lo, hi)]
    name = spec["series"][1].get("name", "Range")
    return [{"name": "Low", "values": list(lo), "hidden": True},
            {"name": name, "values": width, "color": spec["series"][1].get("color", "accent"), "custom": texts,
             "point_colors": spec["series"][1].get("point_colors")}], texts


def _plan(spec: dict) -> list[dict]:
    t = spec["type"]
    if t == "waterfall":
        return _plan_waterfall(spec)
    if t == "football_field":
        return _plan_football(spec)[0]
    return [dict(s, labels=True) for s in spec["series"]]


def _chart_data(spec: dict, plan: list[dict]):
    nf = spec.get("number_format", "General")
    if spec["type"] == "scatter":
        cd = XyChartData()
        for s in plan:
            ser = cd.add_series(s["name"], number_format=s.get("number_format", nf))
            xs = s.get("x")
            for i, y in enumerate(s["values"]):
                if xs is not None:
                    x = float(xs[i])
                else:
                    try:
                        x = float(spec["categories"][i])
                    except (ValueError, TypeError, IndexError):
                        x = float(i)
                if y is not None:
                    ser.add_data_point(x, y)
        return cd
    cd = CategoryChartData(number_format=nf)
    cd.categories = spec["categories"]
    for s in plan:
        cd.add_series(s["name"], s["values"], number_format=s.get("number_format"))
    return cd


def _make_combo(chart) -> None:
    plot = chart._chartSpace.find(f".//{{{_NS_C}}}barChart")
    sers = plot.findall(f"{{{_NS_C}}}ser")
    if len(sers) < 2:
        return
    last = sers[-1]
    plot.remove(last)
    for tag in ("invertIfNegative",):
        for e in last.findall(f"{{{_NS_C}}}{tag}"):
            last.remove(e)
    etree.SubElement(last, f"{{{_NS_C}}}smooth").set("val", "0")
    line = etree.Element(f"{{{_NS_C}}}lineChart")
    etree.SubElement(line, f"{{{_NS_C}}}grouping").set("val", "standard")
    etree.SubElement(line, f"{{{_NS_C}}}varyColors").set("val", "0")
    line.append(last)
    etree.SubElement(line, f"{{{_NS_C}}}marker").set("val", "1")
    for ax in plot.findall(f"{{{_NS_C}}}axId"):
        etree.SubElement(line, f"{{{_NS_C}}}axId").set("val", ax.get("val"))
    plot.addnext(line)


def _secondary_axes(chart, lo: float | None, hi: float | None) -> None:
    """Give the line of a combo chart its own hidden value axis (scaled by lo/hi) so it floats above the bars."""
    cs = chart._chartSpace
    line = cs.find(f".//{{{_NS_C}}}lineChart")
    last_ax = [e for e in cs.find(f".//{{{_NS_C}}}plotArea") if e.tag in (f"{{{_NS_C}}}valAx", f"{{{_NS_C}}}catAx")][-1]
    scale = '<c:orientation val="minMax"/>' + (f'<c:max val="{hi}"/>' if hi is not None else "") + \
        (f'<c:min val="{lo}"/>' if lo is not None else "")
    cat = parse_xml(
        f'<c:catAx xmlns:c="{_NS_C}"><c:axId val="50010"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
        '<c:delete val="1"/><c:axPos val="b"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
        '<c:tickLblPos val="nextTo"/><c:crossAx val="50020"/><c:crosses val="autoZero"/><c:auto val="1"/>'
        '<c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>')
    val = parse_xml(
        f'<c:valAx xmlns:c="{_NS_C}"><c:axId val="50020"/><c:scaling>{scale}</c:scaling><c:delete val="0"/>'
        '<c:axPos val="r"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/>'
        '<c:minorTickMark val="none"/><c:tickLblPos val="none"/><c:spPr><a:ln xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:noFill/></a:ln></c:spPr><c:crossAx val="50010"/><c:crosses val="max"/>'
        '<c:crossBetween val="between"/></c:valAx>')
    last_ax.addnext(cat)
    cat.addnext(val)
    for ax, new in zip(line.findall(f"{{{_NS_C}}}axId"), ("50010", "50020")):
        ax.set("val", new)


def _manual_layout(chart, box: list[float], rtl: bool) -> None:
    x, y, w, h = box
    if rtl:
        x = round(1 - x - w, 4)
    pa = chart._chartSpace.find(f".//{{{_NS_C}}}plotArea")
    for old in pa.findall(f"{{{_NS_C}}}layout"):
        pa.remove(old)
    pa.insert(0, parse_xml(
        f'<c:layout xmlns:c="{_NS_C}"><c:manualLayout><c:layoutTarget val="inner"/><c:xMode val="edge"/>'
        f'<c:yMode val="edge"/><c:x val="{x}"/><c:y val="{y}"/><c:w val="{w}"/><c:h val="{h}"/>'
        '</c:manualLayout></c:layout>'))


def _font(font, cx: _Ctx, size: float = 12, token: str = "text", bold: bool = False) -> None:
    font.size = Pt(size)
    font.bold = bold
    font.name = "+mn-lt"
    cx.color(font.color, token)


def _end_label(s, j: int, cx: _Ctx, nf: str, rtl: bool, token: str) -> None:
    """Direct label on point j: series name + value, so the chart needs no legend."""
    dlb = s.points[j].data_label
    dlb.position = XL_LABEL_POSITION.LEFT if rtl else XL_LABEL_POSITION.RIGHT
    _font(dlb.font, cx, 12, token, bold=True)
    d = dlb._get_or_add_dLbl()
    d.find(f"{{{_NS_C}}}showSerName").set("val", "1")
    d.find(f"{{{_NS_C}}}idx").addnext(parse_xml(f'<c:numFmt xmlns:c="{_NS_C}" formatCode="{_xml_attr(nf)}" sourceLinked="0"/>'))
    d.append(parse_xml(f'<c:separator xmlns:c="{_NS_C}">  </c:separator>'))


def _xml_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _custom_label(s, j: int, txt: str, cx: _Ctx, token: str, pos=None, bold: bool = False) -> None:
    dlb = s.points[j].data_label
    tf = dlb.text_frame
    tf.text = txt
    _font(tf.paragraphs[0].runs[0].font, cx, 12, token, bold=bold)
    if pos is not None:
        dlb.position = pos


def _add_chart(slide, el: Element, cx: _Ctx, rtl: bool) -> None:
    spec = el.chart or {}
    t = spec["type"]
    if t not in _TYPES:
        raise RenderError(f"unknown chart type {t!r}")
    plan = _plan(spec)
    gf = slide.shapes.add_chart(_TYPES[t], _emu(el.x), _emu(el.y), _emu(el.w), _emu(el.h), _chart_data(spec, plan))
    gf.name = el.id
    chart = gf.chart
    if t == "combo":
        _make_combo(chart)
    nf = spec.get("number_format", "0.0")
    chart.has_title = False
    chart.font.size = Pt(12)
    chart.font.name = "+mn-lt"
    cx.color(chart.font.color, "text")
    cs = chart._chartSpace
    ch_el = cs.find(f"{{{_NS_C}}}chart")
    rc = etree.Element(f"{{{_NS_C}}}roundedCorners")
    rc.set("val", "0")
    ch_el.addprevious(rc)
    sp = parse_xml(f'<c:spPr xmlns:c="{_NS_C}" xmlns:a="{_NS_A}"><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>')
    ch_el.addnext(sp)

    labels, pie = bool(spec.get("labels")), t in ("pie", "doughnut")
    highlight = spec.get("highlight")
    hidden = [i for i, s in enumerate(plan) if s.get("hidden")]
    legend = bool(spec.get("legend"))
    chart.has_legend = legend
    if legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        _font(chart.legend.font, cx)
        leg = chart.legend._element
        pos = leg.find(f"{{{_NS_C}}}legendPos")
        for i in reversed(hidden):
            le = parse_xml(f'<c:legendEntry xmlns:c="{_NS_C}"><c:idx val="{i}"/><c:delete val="1"/></c:legendEntry>')
            pos.addnext(le)

    end_labels = t == "line" and spec.get("end_labels", not legend)
    series_all = [s for plot in chart.plots for s in plot.series]
    for i, (s, ps) in enumerate(zip(series_all, plan)):
        color = ps.get("color") or (_SERIES_SEQ[i % len(_SERIES_SEQ)])
        if len(plan) == 1 and highlight and not ps.get("color"):
            color = "mute_bar"
        is_line = t == "line" or (t == "combo" and i == len(plan) - 1)
        is_ref = bool(ps.get("ref"))
        if ps.get("hidden"):
            s.format.fill.background()
            s.format.line.fill.background()
        elif is_ref:
            cx.color(s.format.line.color, ps.get("color", "mute_bar"))
            s.format.line.width = Pt(1.0)
            s.marker.style = XL_MARKER_STYLE.NONE
        elif is_line:
            cx.color(s.format.line.color, color)
            s.format.line.width = Pt(2.25)
            s.smooth = False
            s.marker.style = XL_MARKER_STYLE.NONE
            if t == "line":
                last = max((j for j, v in enumerate(ps["values"]) if v is not None), default=None)
                if last is not None:
                    pt = s.points[last]
                    pt.marker.style = XL_MARKER_STYLE.CIRCLE
                    pt.marker.size = 8
                    pt.marker.format.fill.solid()
                    cx.color(pt.marker.format.fill.fore_color, color)
                    pt.marker.format.line.fill.background()
        elif t != "scatter" and not pie:
            s.format.fill.solid()
            cx.color(s.format.fill.fore_color, color)
            s.format.line.fill.background()
        elif t == "scatter":
            s.format.line.fill.background()
            s.marker.style = XL_MARKER_STYLE.CIRCLE
            s.marker.size = int(ps.get("marker_size", 10))
            s.marker.format.fill.solid()
            cx.color(s.marker.format.fill.fore_color, color)
            s.marker.format.line.fill.background()
        pc = {int(k): v for k, v in (ps.get("point_colors") or {}).items()}
        if not ps.get("hidden") and not is_ref:
            if len(plan) == 1 and highlight and not pc:
                pc = {j: "accent" for j in highlight}
            if pie:
                pc = {**{j: _SERIES_SEQ[j % len(_SERIES_SEQ)] for j in range(len(spec["categories"]))}, **pc}
            if t == "scatter":
                for j, tok in pc.items():
                    pt = s.points[j]
                    pt.marker.style = XL_MARKER_STYLE.CIRCLE
                    pt.marker.size = int(ps.get("marker_size", 10))
                    pt.marker.format.fill.solid()
                    cx.color(pt.marker.format.fill.fore_color, tok)
                    pt.marker.format.line.fill.background()
                    pt.format.fill.solid()
                    cx.color(pt.format.fill.fore_color, tok)
            elif not is_line:
                for j, tok in pc.items():
                    pt = s.points[j]
                    pt.format.fill.solid()
                    cx.color(pt.format.fill.fore_color, tok)
                    pt.format.line.fill.background()
        fill_tok = None if ps.get("hidden") else color
        if t == "line" and not ps.get("hidden") and not is_ref and end_labels:
            last = max((j for j, v in enumerate(ps["values"]) if v is not None), default=None)
            if last is not None:
                dls = s.data_labels
                dls.show_value = False
                _end_label(s, last, cx, ps.get("number_format", nf), rtl, "text")
        elif t == "scatter" and ps.get("point_labels") and not is_ref:
            names = spec["categories"]
            for j, v in enumerate(ps["values"]):
                if v is not None and j < len(names) and names[j]:
                    tok = "text"
                    _custom_label(s, j, names[j], cx, tok, pos=XL_LABEL_POSITION.LEFT if rtl else XL_LABEL_POSITION.RIGHT,
                                  bold=j in (ps.get("bold_points") or []))
        elif labels and ps.get("labels", not ps.get("hidden")) and not is_ref:
            dl = s.data_labels
            dl.show_value = True
            lf = ps.get("fmt") or ps.get("number_format") or nf
            dl.number_format = lf
            dl.number_format_is_linked = False
            inside = t in _STACKED
            custom = ps.get("custom")
            tok = ps.get("label_token") or ("text" if (not inside or custom) else label_token(cx, fill_tok))
            if inside and not custom and ps.get("small_below"):
                small = [v for v in ps["values"] if v is not None and v < ps["small_below"]]
                if small:
                    tok = "text"
            _font(dl.font, cx, 12, tok)
            if ps.get("label_pos") == "inBase":
                dl.position = XL_LABEL_POSITION.INSIDE_BASE
            elif inside:
                dl.position = XL_LABEL_POSITION.CENTER
            elif t in ("bar", "column") or pie:
                dl.position = XL_LABEL_POSITION.OUTSIDE_END
            else:
                dl.position = XL_LABEL_POSITION.ABOVE
            if custom:
                for j, txt in enumerate(custom):
                    if txt:
                        ptok = ps.get("label_token") or (label_token(cx, pc.get(j) or fill_tok) if inside else "text")
                        _custom_label(s, j, txt, cx, ptok)
    if pie:
        if t == "doughnut":
            dn = cs.find(f".//{{{_NS_C}}}doughnutChart")
            hs = dn.find(f"{{{_NS_C}}}holeSize")
            if hs is None:
                hs = etree.SubElement(dn, f"{{{_NS_C}}}holeSize")
            hs.set("val", str(int(spec.get("hole", 62))))
        if spec.get("plot_layout"):
            _manual_layout(chart, spec["plot_layout"], rtl)
        return
    ca, va = chart.category_axis, chart.value_axis
    for ax in (ca, va):
        ax.has_major_gridlines = False
        ax.has_minor_gridlines = False
        ax.major_tick_mark = XL_TICK_MARK.NONE
        _font(ax.tick_labels.font, cx)
    cx.color(ca.format.line.color, "mute_bar")
    ca.format.line.width = Pt(0.5)
    va.format.line.fill.background()
    va.tick_labels.number_format = spec.get("axis_format", nf)
    va.tick_labels.number_format_is_linked = False
    show_va = bool(spec.get("value_axis", not labels))
    va.visible = show_va
    if spec.get("axis_min") is not None:
        va.minimum_scale = spec["axis_min"]
    if spec.get("axis_max") is not None:
        va.maximum_scale = spec["axis_max"]
    if t == "scatter":
        if spec.get("x_min") is not None:
            ca.minimum_scale = spec["x_min"]
        if spec.get("x_max") is not None:
            ca.maximum_scale = spec["x_max"]
        ca.visible = True
        ca.tick_labels.number_format = spec.get("x_format", nf)
        ca.tick_labels.number_format_is_linked = False
        for ax, key in ((ca, "x_title"), (va, "axis_title")):
            if spec.get(key):
                ax.has_title = True
                ax.axis_title.text_frame.text = spec[key]
                _font(ax.axis_title.text_frame.paragraphs[0].runs[0].font, cx)
        if spec.get("axis_title"):
            va.visible = True
    elif spec.get("axis_title"):
        va.has_title = True
        va.axis_title.text_frame.text = spec["axis_title"]
        _font(va.axis_title.text_frame.paragraphs[0].runs[0].font, cx)
        va.visible = True
    for plot in chart.plots:
        if hasattr(plot, "gap_width") and t not in ("line", "area", "scatter"):
            plot.gap_width = GAP_WIDTH
    if t in _HORIZONTAL:
        ca.reverse_order = True
        ca.crosses = XL_AXIS_CROSSES.MAXIMUM
        if rtl:
            va.reverse_order = True
    elif rtl:
        ca.reverse_order = True
    lp = spec.get("plot_layout")
    if lp is None and end_labels:
        lp = [0.03, 0.06, 0.74, 0.80]
    if lp:
        _manual_layout(chart, lp, rtl)
    if t == "combo" and spec.get("secondary"):
        _secondary_axes(chart, spec.get("axis2_min"), spec.get("axis2_max"))


# ---------------------------------------------------------------- deck

def _add_bindings(prs, bindings: dict) -> None:
    blob = json.dumps(bindings, indent=1, sort_keys=True).encode("utf-8")
    part = Part(PackURI(BINDINGS_PART), "application/json", prs.part.package, blob)
    prs.part.relate_to(part, BINDINGS_RELTYPE)


def read_bindings(pptx_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as z:
        return json.loads(z.read(BINDINGS_PART.lstrip("/")).decode("utf-8"))


def render(slides: list[SolvedSlide], theme: Theme, *, title: str, template: str | None = None) -> bytes:
    prs = _open(template)
    if template is None:
        _patch_theme(prs, theme)
    prs.core_properties.title = title
    layout = _blank_layout(prs)
    cx = _Ctx(theme)
    bindings: dict[str, dict] = {}
    seen: set[str] = set()
    for s in slides:
        sl = prs.slides.add_slide(layout)
        for ph in list(sl.placeholders):
            ph._element.getparent().remove(ph._element)
        sl.background.fill.solid()
        cx.color(sl.background.fill.fore_color, "background")
        for el in s.elements:
            if el.id in seen:
                raise RenderError(f"duplicate element id {el.id!r}")
            seen.add(el.id)
            if el.kind in ("text", "rect"):
                _add_box(sl, el, cx, s.rtl)
            elif el.kind == "line":
                _add_line(sl, el, cx)
            elif el.kind == "table":
                _add_table(sl, el, cx, s.rtl)
            elif el.kind == "chart":
                _add_chart(sl, el, cx, s.rtl)
            elif el.kind == "image":
                _add_image(sl, el)
            else:
                raise RenderError(f"unknown element kind {el.kind!r}")
            if el.binding:
                bindings[el.id] = el.binding
        if s.notes:
            sl.notes_slide.notes_text_frame.text = s.notes
    _add_bindings(prs, bindings)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
