"""Dependency-free .pptx writer with a banker-grade design system.

Produces real PowerPoint files: native text, native tables and native charts (bar / column / stacked /
floating football-field), so everything stays editable in PowerPoint, Keynote and Google Slides.

Design system
  16:9 · Calibri · navy title band rule · consistent margins (0.5") · 8pt sourced footnote + page number
  on every content slide · tables with navy header row, hairline row rules, right-aligned numbers,
  bold summary rows · charts with muted gridlines and data labels.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

EMU = 914400                     # per inch
W, H = 12192000, 6858000         # 13.333" x 7.5"
MARGIN = int(0.5 * EMU)
FONT = "Calibri"

THEME = {
    "navy": "0B1F3A", "blue": "1F5FBF", "teal": "0F8B8D", "gold": "B8892B", "slate": "475569",
    "ink": "111827", "muted": "6B7280", "rule": "D1D5DB", "band": "F3F4F6", "white": "FFFFFF", "red": "B91C1C",
}
SERIES = ["1F5FBF", "0F8B8D", "B8892B", "475569", "7C3AED", "0B1F3A"]

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def attr(s: str) -> str:
    """Escape for use inside an XML attribute (number formats like "$"#,##0 contain quotes)."""
    return escape(str(s), {'"': "&quot;"})


def emu(inches: float) -> int:
    return int(round(inches * EMU))


# --------------------------------------------------------------------------- text helpers
def run(text: str, size: float = 12, bold: bool = False, color: str = "ink", italic: bool = False, font: str | None = None,
        underline: bool = False) -> str:
    col = _hex(color)
    f = attr(font or FONT)
    u = ' u="sng"' if underline else ""
    return (f'<a:r><a:rPr lang="en-US" sz="{int(size * 100)}" b="{int(bold)}" i="{int(italic)}"{u} dirty="0">'
            f'<a:solidFill><a:srgbClr val="{col}"/></a:solidFill><a:latin typeface="{f}"/><a:cs typeface="{f}"/></a:rPr>'
            f'<a:t>{escape(str(text))}</a:t></a:r>')


def _hex(color) -> str:
    if isinstance(color, (list, tuple)):
        color = color[0] if color else None
    if not isinstance(color, str):
        color = None
    c = THEME.get(color or "ink", color or "111827")
    c = c.lstrip("#").upper()[:6] if c else "111827"
    return c if len(c) == 6 and all(ch in "0123456789ABCDEF" for ch in c) else "111827"


PRESET_SHAPES = {"rect", "roundRect", "ellipse", "triangle", "rtTriangle", "diamond", "pentagon", "homePlate", "chevron", "hexagon",
                 "octagon", "plus", "rightArrow", "leftArrow", "upArrow", "downArrow", "leftRightArrow", "flowChartProcess",
                 "flowChartDecision", "parallelogram", "trapezoid", "wedgeRectCallout", "wedgeRoundRectCallout", "snip1Rect",
                 "round2SameRect", "donut", "blockArc", "star5", "line", "bracketPair", "leftBrace", "rightBrace"}


def para(runs: str | list, align: str = "l", bullet: bool = False, level: int = 0, space_after: float = 4,
         line: float | None = None) -> str:
    runs = "".join(runs) if isinstance(runs, list) else runs
    ind = ""
    bu = '<a:buNone/>'
    if bullet:
        mar = emu(0.22 + 0.25 * level)
        ind = f' marL="{mar}" indent="{-emu(0.18)}"'
        bu = f'<a:buClr><a:srgbClr val="{THEME["blue"]}"/></a:buClr><a:buFont typeface="Arial"/><a:buChar char="{"•" if level == 0 else "–"}"/>'
    ln = f'<a:lnSpc><a:spcPct val="{int(line * 1000)}"/></a:lnSpc>' if line else ""
    return (f'<a:p><a:pPr algn="{align}"{ind}>{ln}<a:spcAft><a:spcPts val="{int(space_after * 100)}"/></a:spcAft>{bu}</a:pPr>'
            f'{runs}</a:p>')


@dataclass
class Slide:
    shapes: list[str] = field(default_factory=list)
    charts: list[str] = field(default_factory=list)      # chart part XML, referenced in order
    media: list[tuple[str, bytes]] = field(default_factory=list)   # (ext, bytes), referenced as rIdImg<n>
    background: str | None = None
    _id: int = 2

    def nid(self) -> int:
        self._id += 1
        return self._id

    # ------------------------------------------------------------------ primitives
    def rect(self, x, y, w, h, fill: str | None = None, line: str | None = None, line_w: float = 0.75):
        f = f'<a:solidFill><a:srgbClr val="{THEME.get(fill, fill)}"/></a:solidFill>' if fill else "<a:noFill/>"
        ln = (f'<a:ln w="{int(line_w * 12700)}"><a:solidFill><a:srgbClr val="{THEME.get(line, line)}"/></a:solidFill></a:ln>'
              if line else "<a:ln><a:noFill/></a:ln>")
        i = self.nid()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Rect {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{f}{ln}</p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>')

    def shape(self, x, y, w, h, prst: str = "rect", fill: str | None = None, line: str | None = None, line_w: float = 0.75,
              paragraphs: list[str] | None = None, anchor: str = "ctr", inset: float = 0.08, rot: float = 0, dash: str | None = None,
              flip_h: bool = False, flip_v: bool = False, adj: float | None = None, shadow: bool = False):
        """Any preset geometry (rounded box, circle, chevron, arrow, callout…), optionally with text inside."""
        prst = prst if prst in PRESET_SHAPES else "rect"
        f = f'<a:solidFill><a:srgbClr val="{_hex(fill)}"/></a:solidFill>' if fill else "<a:noFill/>"
        dsh = f'<a:prstDash val="{dash}"/>' if dash in ("dash", "sysDash", "dot", "lgDash", "sysDot") else ""
        ln = (f'<a:ln w="{int(line_w * 12700)}"><a:solidFill><a:srgbClr val="{_hex(line)}"/></a:solidFill>{dsh}</a:ln>'
              if line else "<a:ln><a:noFill/></a:ln>")
        av = f'<a:avLst><a:gd name="adj" fmla="val {int(adj * 100000)}"/></a:avLst>' if adj is not None else "<a:avLst/>"
        eff = ('<a:effectLst><a:outerShdw blurRad="50800" dist="19050" dir="5400000" algn="t" rotWithShape="0">'
               '<a:srgbClr val="000000"><a:alpha val="18000"/></a:srgbClr></a:outerShdw></a:effectLst>') if shadow else ""
        xf = (f' rot="{int(rot * 60000)}"' if rot else "") + (' flipH="1"' if flip_h else "") + (' flipV="1"' if flip_v else "")
        ins = emu(inset)
        i = self.nid()
        body = "".join(paragraphs) if paragraphs else '<a:p><a:endParaRPr lang="en-US"/></a:p>'
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Shape {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm{xf}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{prst}">{av}</a:prstGeom>{f}{ln}{eff}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="{ins}" tIns="{ins}" rIns="{ins}" bIns="{ins}" anchor="{anchor}"/><a:lstStyle/>{body}</p:txBody></p:sp>')

    def icon(self, x, y, size, name: str, color: str = "FFFFFF", badge: str | None = None, stroke: float | None = None):
        """A library icon as native vector geometry; with badge, drawn white-on-colour inside a filled circle."""
        from .icons import custgeom
        if badge:
            self.shape(x, y, size, size, "ellipse", fill=badge)
            pad = int(size * 0.22)
            x, y, size = x + pad, y + pad, size - 2 * pad
        sw = stroke if stroke is not None else max(0.75, 2 / 24 * size / EMU * 72)        # 2-unit stroke on the 24 grid
        col = _hex(color)
        i = self.nid()
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Icon {attr(name)} {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{size}" cy="{size}"/></a:xfrm>{custgeom(name)}'
            f'<a:solidFill><a:srgbClr val="{col}"/></a:solidFill>'
            f'<a:ln w="{int(sw * 12700)}" cap="rnd"><a:solidFill><a:srgbClr val="{col}"/></a:solidFill><a:round/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></p:txBody></p:sp>')

    def connector(self, x1, y1, x2, y2, color: str = "rule", weight: float = 1.0, head: bool = False, tail: bool = False,
                  dash: str | None = None):
        """A straight line between two points (EMU), with optional arrowheads."""
        x, y, w, h = min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
        flip = (' flipH="1"' if x2 < x1 else "") + (' flipV="1"' if y2 < y1 else "")
        dsh = f'<a:prstDash val="{dash}"/>' if dash in ("dash", "sysDash", "dot", "lgDash", "sysDot") else ""
        hd = '<a:tailEnd type="triangle" w="med" len="med"/>' if head else ""
        tl = '<a:headEnd type="triangle" w="med" len="med"/>' if tail else ""
        i = self.nid()
        self.shapes.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Connector {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{flip}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="{int(weight * 12700)}"><a:solidFill><a:srgbClr val="{_hex(color)}"/></a:solidFill>{dsh}{tl}{hd}</a:ln></p:spPr></p:cxnSp>')

    def picture(self, x, y, w, h, data: bytes, name: str = "Picture"):
        ext = "jpeg" if data[:3] == b"\xff\xd8\xff" else "png"
        self.media.append((ext, data))
        rid = f"rIdImg{len(self.media)}"
        i = self.nid()
        self.shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="{attr(name)} {i}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')

    def text(self, x, y, w, h, paragraphs: list[str], anchor: str = "t", inset: float = 0.0, fill: str | None = None,
             autofit: bool = False):
        i = self.nid()
        ins = emu(inset)
        f = f'<a:solidFill><a:srgbClr val="{_hex(fill)}"/></a:solidFill>' if fill else "<a:noFill/>"
        fit = "<a:normAutofit/>" if autofit else ""
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Text {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{f}</p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="{ins}" tIns="{ins}" rIns="{ins}" bIns="{ins}" anchor="{anchor}">{fit}</a:bodyPr><a:lstStyle/>'
            f'{"".join(paragraphs) or "<a:p/>"}</p:txBody></p:sp>')

    def line(self, x, y, w, color="rule", weight: float = 0.75):
        i = self.nid()
        self.shapes.append(
            f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Line {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="0"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="{int(weight * 12700)}"><a:solidFill><a:srgbClr val="{THEME.get(color, color)}"/></a:solidFill></a:ln></p:spPr></p:cxnSp>')

    # ------------------------------------------------------------------ table
    def table(self, x, y, w, rows: list[list], col_widths: list[float] | None = None, num_cols: set[int] | None = None,
              bold_rows: set[int] | None = None, row_h: float = 0.32, font: float = 10.5, header_fill: str = "navy",
              shade_rows: set[int] | None = None):
        """rows[0] is the header. Numbers should be pre-formatted strings. num_cols are right-aligned."""
        ncols = len(rows[0])
        col_widths = col_widths or [1] * ncols
        tot = sum(col_widths)
        widths = [int(w * c / tot) for c in col_widths]
        num_cols = num_cols or set()
        bold_rows = bold_rows or set()
        shade_rows = shade_rows or set()

        def cell(txt, r, c):
            hdr = r == 0
            align = "r" if (c in num_cols and not hdr) or (hdr and c in num_cols) else "l"
            color = "white" if hdr else "ink"
            b = hdr or r in bold_rows
            fill = (f'<a:solidFill><a:srgbClr val="{_hex(header_fill)}"/></a:solidFill>' if hdr else
                    f'<a:solidFill><a:srgbClr val="{THEME["band"]}"/></a:solidFill>' if r in shade_rows else "<a:noFill/>")
            top_rule = THEME["navy"] if r in bold_rows and r > 1 else THEME["rule"]
            top_w = 12700 if r in bold_rows and r > 1 else 6350

            def ln(tag, col, wdt):
                return f'<a:{tag} w="{wdt}"><a:solidFill><a:srgbClr val="{col}"/></a:solidFill></a:{tag}>'
            borders = (f'<a:lnL w="0"><a:noFill/></a:lnL><a:lnR w="0"><a:noFill/></a:lnR>'
                       + (ln("lnT", top_rule, top_w) if not hdr else '<a:lnT w="0"><a:noFill/></a:lnT>')
                       + ln("lnB", THEME["rule"], 6350))
            return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>{para(run(txt, font, b, color), align, space_after=0)}</a:txBody>'
                    f'<a:tcPr marL="{emu(0.06)}" marR="{emu(0.06)}" marT="{emu(0.03)}" marB="{emu(0.03)}" anchor="ctr">'
                    f'{borders}{fill}</a:tcPr></a:tc>')
        trs = "".join(f'<a:tr h="{emu(row_h)}">' + "".join(cell("" if v is None else v, r, c) for c, v in enumerate(row)) + "</a:tr>"
                      for r, row in enumerate(rows))
        grid = "".join(f'<a:gridCol w="{cw}"/>' for cw in widths)
        i = self.nid()
        h = emu(row_h) * len(rows)
        self.shapes.append(
            f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Table {i}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></p:xfrm>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
            f'<a:tbl><a:tblPr firstRow="1" bandRow="0"/><a:tblGrid>{grid}</a:tblGrid>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
        return h

    # ------------------------------------------------------------------ chart
    def chart(self, x, y, w, h, categories: list[str], series: list[tuple[str, list[float | None]]], kind: str = "col",
              stacked: bool = False, number_format: str = "#,##0", labels: bool = True, legend: bool = True,
              hidden_first: bool = False, gap: int = 60, colors: list[str] | None = None, axis_title: str | None = None,
              axis_min: float | None = None, axis_max: float | None = None, value_axis: bool = False,
              point_colors: list[str | None] | None = None, label_color: str | None = None, gridlines: bool = True,
              font: str | None = None):
        """kind: col (vertical) | bar (horizontal) | line | pie | doughnut. hidden_first + stacked = floating bars
        (football field, waterfall). point_colors colour individual points of the first visible series."""
        idx = len(self.charts) + 1
        rid = f"rIdChart{idx}"
        cfont = attr(font or FONT)
        colors = colors or SERIES

        def lit_str(vals):
            return f'<c:strLit><c:ptCount val="{len(vals)}"/>' + "".join(f'<c:pt idx="{i}"><c:v>{escape(str(v))}</c:v></c:pt>' for i, v in enumerate(vals)) + "</c:strLit>"

        def lit_num(vals):
            pts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(vals) if v is not None)
            return f'<c:numLit><c:formatCode>{escape(number_format)}</c:formatCode><c:ptCount val="{len(vals)}"/>{pts}</c:numLit>'
        sers = []
        for si, (name, vals) in enumerate(series):
            invisible = hidden_first and si == 0
            fill = '<a:noFill/>' if invisible else f'<a:solidFill><a:srgbClr val="{colors[(si - (1 if hidden_first else 0)) % len(colors)]}"/></a:solidFill>'
            dl = ""
            if labels and not invisible:
                dl = (f'<c:dLbls><c:numFmt formatCode="{attr(number_format)}" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
                      f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900" b="0"><a:solidFill><a:srgbClr val="{_hex(label_color) if label_color else (THEME["ink"] if not stacked else THEME["white"])}"/></a:solidFill>'
                      f'<a:latin typeface="{cfont}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>'
                      f'<c:dLblPos val="{"ctr" if stacked else "outEnd"}"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/>'
                      f'<c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>')
            first_visible = si == (1 if hidden_first else 0)
            dpts = ""
            if point_colors and (first_visible or kind in ("pie", "doughnut")):
                dpts = "".join(f'<c:dPt><c:idx val="{pi}"/><c:invertIfNegative val="0"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="{_hex(pc)}"/></a:solidFill></c:spPr></c:dPt>'
                               for pi, pc in enumerate(point_colors) if pc)
            col_hex = colors[(si - (1 if hidden_first else 0)) % len(colors)]
            if kind == "line":
                sers.append(f'<c:ser><c:idx val="{si}"/><c:order val="{si}"/><c:tx><c:v>{escape(name)}</c:v></c:tx>'
                            f'<c:spPr><a:ln w="28575" cap="rnd"><a:solidFill><a:srgbClr val="{col_hex}"/></a:solidFill><a:round/></a:ln></c:spPr>'
                            f'<c:marker><c:symbol val="circle"/><c:size val="5"/><c:spPr><a:solidFill><a:srgbClr val="{col_hex}"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:marker>'
                            f'{dl.replace("outEnd", "t")}<c:cat>{lit_str(categories)}</c:cat><c:val>{lit_num(vals)}</c:val><c:smooth val="0"/></c:ser>')
            elif kind in ("pie", "doughnut"):
                if not point_colors:
                    dpts = "".join(f'<c:dPt><c:idx val="{pi}"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="{colors[pi % len(colors)]}"/></a:solidFill>'
                                   f'<a:ln w="12700"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln></c:spPr></c:dPt>' for pi in range(len(categories)))
                sers.append(f'<c:ser><c:idx val="{si}"/><c:order val="{si}"/><c:tx><c:v>{escape(name)}</c:v></c:tx>{dpts}'
                            f'{dl.replace("<c:dLblPos val=\"outEnd\"/>", "").replace("<c:dLblPos val=\"ctr\"/>", "")}'
                            f'<c:cat>{lit_str(categories)}</c:cat><c:val>{lit_num(vals)}</c:val></c:ser>')
            else:
                sers.append(f'<c:ser><c:idx val="{si}"/><c:order val="{si}"/><c:tx><c:v>{escape(name)}</c:v></c:tx>'
                            f'<c:spPr>{fill}<a:ln><a:noFill/></a:ln></c:spPr><c:invertIfNegative val="0"/>{dpts}{dl}'
                            f'<c:cat>{lit_str(categories)}</c:cat><c:val>{lit_num(vals)}</c:val></c:ser>')
        grouping = "stacked" if stacked else "clustered"
        overlap = '<c:overlap val="100"/>' if stacked else '<c:overlap val="-10"/>'

        def txpr(sz=900, color="muted"):
            return (f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{sz}"><a:solidFill><a:srgbClr val="{THEME[color]}"/></a:solidFill>'
                    f'<a:latin typeface="{cfont}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>')
        cat_pos, val_pos = ("l", "b") if kind == "bar" else ("b", "l")
        if kind == "line":
            plot_open, plot_close = f'<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>', '<c:marker val="1"/><c:axId val="111"/><c:axId val="222"/></c:lineChart>'
        elif kind in ("pie", "doughnut"):
            tag = "doughnutChart" if kind == "doughnut" else "pieChart"
            plot_open = f'<c:{tag}><c:varyColors val="1"/>'
            plot_close = ('<c:firstSliceAng val="0"/><c:holeSize val="55"/>' if kind == "doughnut" else '<c:firstSliceAng val="0"/>') + f'</c:{tag}>'
        else:
            plot_open = f'<c:barChart><c:barDir val="{kind}"/><c:grouping val="{grouping}"/><c:varyColors val="0"/>'
            plot_close = f'<c:gapWidth val="{gap}"/>{overlap}<c:axId val="111"/><c:axId val="222"/></c:barChart>'
        axes_open, axes_close = ("<!--", "-->") if kind in ("pie", "doughnut") else ("", "")
        ttl = ""
        if axis_title:
            ttl = (f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="900" b="0"/></a:pPr>'
                   f'<a:r><a:rPr lang="en-US" sz="900" b="0"><a:solidFill><a:srgbClr val="{THEME["muted"]}"/></a:solidFill></a:rPr><a:t>{escape(axis_title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>')
        show_legend = legend and (len(series) - (1 if hidden_first else 0)) > 1
        leg = (f'<c:legend><c:legendPos val="t"/>' + ('<c:legendEntry><c:idx val="0"/><c:delete val="1"/></c:legendEntry>' if hidden_first else "")
               + f'<c:overlay val="0"/>{txpr(900, "slate")}</c:legend>') if show_legend else ""
        xml = (f'{XML}<c:chartSpace xmlns:c="{NS_C}" xmlns:a="{NS_A}" xmlns:r="{NS_R}"><c:roundedCorners val="0"/>'
               f'<c:chart><c:autoTitleDeleted val="1"/><c:plotArea><c:layout/>'
               f'{plot_open}{"".join(sers)}{plot_close}'
               f'{axes_open}<c:catAx><c:axId val="111"/><c:scaling><c:orientation val="{"maxMin" if kind == "bar" else "minMax"}"/></c:scaling><c:delete val="0"/>'
               f'<c:axPos val="{cat_pos}"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
               f'<c:tickLblPos val="low"/><c:spPr><a:ln w="9525"><a:solidFill><a:srgbClr val="{THEME["rule"]}"/></a:solidFill></a:ln></c:spPr>{txpr(1000, "ink")}'
               f'<c:crossAx val="222"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
               f'<c:valAx><c:axId val="222"/><c:scaling><c:orientation val="minMax"/>'
               + (f'<c:max val="{axis_max}"/>' if axis_max is not None else "") + (f'<c:min val="{axis_min}"/>' if axis_min is not None else "")
               + f'</c:scaling><c:delete val="{0 if (value_axis or not labels) else 1}"/>'
               f'<c:axPos val="{val_pos}"/>' + ('<c:majorGridlines><c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>' if gridlines else '') +
               f'{ttl}<c:numFmt formatCode="{attr(number_format)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
               f'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>{txpr()}<c:crossAx val="111"/><c:crosses val="{"max" if kind == "bar" else "autoZero"}"/><c:crossBetween val="between"/></c:valAx>{axes_close}'
               f'<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr></c:plotArea>{leg}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
               f'<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
               f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr><a:latin typeface="{cfont}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr></c:chartSpace>')
        self.charts.append(xml)
        i = self.nid()
        self.shapes.append(
            f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{i}" name="Chart {i}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></p:xfrm><a:graphic><a:graphicData uri="{NS_C}">'
            f'<c:chart xmlns:c="{NS_C}" r:id="{rid}"/></a:graphicData></a:graphic></p:graphicFrame>')


# --------------------------------------------------------------------------- deck
class Deck:
    def __init__(self, title: str, brand: str = "Research", confidential: bool = True):
        self.title, self.brand, self.confidential = title, brand, confidential
        self.slides: list[Slide] = []

    # ------------------------------------------------------------------ slide templates
    def cover(self, title: str, subtitle: str = "", date: str | None = None) -> Slide:
        s = Slide()
        s.rect(0, 0, W, H, fill="navy")
        s.rect(0, H - emu(0.12), W, emu(0.12), fill="blue")
        s.rect(MARGIN, emu(2.55), emu(0.9), emu(0.06), fill="gold")
        s.text(MARGIN, emu(2.75), W - 2 * MARGIN, emu(1.4), [para(run(title, 36, True, "white"), line=95)], anchor="t")
        if subtitle:
            s.text(MARGIN, emu(4.15), W - 2 * MARGIN, emu(0.9), [para(run(subtitle, 16, False, "D6DEEA"))])
        s.text(MARGIN, H - emu(0.9), emu(6), emu(0.4),
               [para([run(self.brand, 11, True, "white"), run(f"   ·   {date or time.strftime('%B %Y')}", 11, False, "AFC0D6")])])
        if self.confidential:
            s.text(W - MARGIN - emu(4), H - emu(0.9), emu(4), emu(0.4), [para(run("Strictly confidential", 10, False, "AFC0D6"), "r")])
        self.slides.append(s)
        return s

    def content(self, title: str, subtitle: str = "", source: str = "") -> Slide:
        s = Slide()
        s.text(MARGIN, emu(0.32), W - 2 * MARGIN, emu(0.55), [para(run(title, 24, True, "navy"))], anchor="b")
        if subtitle:
            s.text(MARGIN, emu(0.88), W - 2 * MARGIN, emu(0.35), [para(run(subtitle, 12, False, "slate"))])
        s.rect(MARGIN, emu(1.28), W - 2 * MARGIN, emu(0.025), fill="navy")
        n = len(self.slides) + 1
        s.line(MARGIN, H - emu(0.55), W - 2 * MARGIN, "rule", 0.5)
        if source:
            s.text(MARGIN, H - emu(0.52), W - 2 * MARGIN - emu(1.6), emu(0.42), [para(run(source, 8, False, "muted"), line=90)])
        s.text(W - MARGIN - emu(1.5), H - emu(0.52), emu(1.5), emu(0.3),
               [para([run(self.brand + "   ", 8, True, "slate"), run(str(n), 8, False, "muted")], "r")])
        self.slides.append(s)
        return s

    def blank(self, background: str | None = None) -> Slide:
        s = Slide(background=background)
        self.slides.append(s)
        return s

    def section(self, title: str) -> Slide:
        s = Slide()
        s.rect(0, 0, emu(0.35), H, fill="blue")
        s.text(emu(1.0), emu(2.9), W - emu(2), emu(1.2), [para(run(title, 30, True, "navy"))], anchor="ctr")
        self.slides.append(s)
        return s

    # ------------------------------------------------------------------ package
    def save(self) -> bytes:
        files: dict[str, str] = {}
        n = len(self.slides)
        chart_no = media_no = 0
        binaries: dict[str, bytes] = {}
        slide_ct, chart_ct = [], []
        for i, s in enumerate(self.slides, 1):
            rels = [f'<Relationship Id="rId1" Type="{REL}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>']
            for j, cx in enumerate(s.charts, 1):
                chart_no += 1
                files[f"ppt/charts/chart{chart_no}.xml"] = cx
                chart_ct.append(chart_no)
                rels.append(f'<Relationship Id="rIdChart{j}" Type="{REL}/chart" Target="../charts/chart{chart_no}.xml"/>')
            for j, (ext, data) in enumerate(s.media, 1):
                media_no += 1
                binaries[f"ppt/media/image{media_no}.{ext}"] = data
                rels.append(f'<Relationship Id="rIdImg{j}" Type="{REL}/image" Target="../media/image{media_no}.{ext}"/>')
            bg = (f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{_hex(s.background)}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                  if s.background else "")
            files[f"ppt/slides/slide{i}.xml"] = (
                f'{XML}<p:sld xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"><p:cSld>{bg}<p:spTree>'
                f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                f'{"".join(s.shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')
            files[f"ppt/slides/_rels/slide{i}.xml.rels"] = (
                f'{XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
            slide_ct.append(i)
        files["[Content_Types].xml"] = (
            f'{XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/><Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>'
            '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>'
            '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            + "".join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in slide_ct)
            + "".join(f'<Override PartName="/ppt/charts/chart{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>' for i in chart_ct)
            + "</Types>")
        files["_rels/.rels"] = (
            f'{XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="ppt/presentation.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            f'<Relationship Id="rId3" Type="{REL}/extended-properties" Target="docProps/app.xml"/></Relationships>')
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        files["docProps/core.xml"] = (
            f'{XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(self.title)}</dc:title><dc:creator>{escape(self.brand)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
        files["docProps/app.xml"] = (
            f'{XML}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Acretia</Application>'
            f'<Slides>{n}</Slides></Properties>')
        files["ppt/presentation.xml"] = (
            f'{XML}<p:presentation xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}" saveSubsetFonts="1">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:sldIdLst>' + "".join(f'<p:sldId id="{255 + i}" r:id="rId{10 + i}"/>' for i in slide_ct) + '</p:sldIdLst>'
            f'<p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        files["ppt/_rels/presentation.xml.rels"] = (
            f'{XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}/theme" Target="theme/theme1.xml"/>'
            f'<Relationship Id="rId3" Type="{REL}/presProps" Target="presProps.xml"/>'
            f'<Relationship Id="rId4" Type="{REL}/viewProps" Target="viewProps.xml"/>'
            f'<Relationship Id="rId5" Type="{REL}/tableStyles" Target="tableStyles.xml"/>'
            + "".join(f'<Relationship Id="rId{10 + i}" Type="{REL}/slide" Target="slides/slide{i}.xml"/>' for i in slide_ct)
            + "</Relationships>")
        files["ppt/presProps.xml"] = f'{XML}<p:presentationPr xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"/>'
        files["ppt/viewProps.xml"] = (f'{XML}<p:viewPr xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}">'
                                      '<p:normalViewPr><p:restoredLeft sz="15620"/><p:restoredTop sz="94660"/></p:normalViewPr>'
                                      '<p:gridSpacing cx="76200" cy="76200"/></p:viewPr>')
        files["ppt/tableStyles.xml"] = f'{XML}<a:tblStyleLst xmlns:a="{NS_A}" def="{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}"/>'
        files["ppt/slideMasters/slideMaster1.xml"] = (
            f'{XML}<p:sldMaster xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>'
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            '<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="2400"/></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr><a:defRPr sz="1400"/></a:lvl1pPr></p:bodyStyle>'
            '<p:otherStyle><a:lvl1pPr><a:defRPr sz="1200"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>')
        files["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = (
            f'{XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            f'<Relationship Id="rId2" Type="{REL}/theme" Target="../theme/theme1.xml"/></Relationships>')
        files["ppt/slideLayouts/slideLayout1.xml"] = (
            f'{XML}<p:sldLayout xmlns:a="{NS_A}" xmlns:r="{NS_R}" xmlns:p="{NS_P}" type="blank" preserve="1"><p:cSld name="Blank">'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        files["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = (
            f'{XML}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>')
        files["ppt/theme/theme1.xml"] = _theme()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
            for name, content in files.items():
                z.writestr(name, content)
            for name, data in binaries.items():
                z.writestr(name, data)
        return buf.getvalue()


def _theme() -> str:
    c = THEME
    clr = (f'<a:dk1><a:srgbClr val="{c["ink"]}"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
           f'<a:dk2><a:srgbClr val="{c["navy"]}"/></a:dk2><a:lt2><a:srgbClr val="{c["band"]}"/></a:lt2>'
           + "".join(f'<a:accent{i}><a:srgbClr val="{v}"/></a:accent{i}>' for i, v in enumerate(SERIES, 1))
           + f'<a:hlink><a:srgbClr val="{c["blue"]}"/></a:hlink><a:folHlink><a:srgbClr val="{c["slate"]}"/></a:folHlink>')
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    ln = '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>'
    return (f'{XML}<a:theme xmlns:a="{NS_A}" name="Acretia"><a:themeElements><a:clrScheme name="Acretia">{clr}</a:clrScheme>'
            f'<a:fontScheme name="Acretia"><a:majorFont><a:latin typeface="{FONT}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
            f'<a:minorFont><a:latin typeface="{FONT}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
            f'<a:fmtScheme name="Acretia"><a:fillStyleLst>{fill * 3}</a:fillStyleLst><a:lnStyleLst>{ln * 3}</a:lnStyleLst>'
            '<a:effectStyleLst>' + '<a:effectStyle><a:effectLst/></a:effectStyle>' * 3 + '</a:effectStyleLst>'
            f'<a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
