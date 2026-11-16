"""A dependency-free .xlsx writer and reader built for banker-grade models.

Writer
  • Multiple sheets, real styles: banking colour code (blue hard-coded inputs and historicals, black formulas,
    green links to other sheets), number formats with negatives in brackets and dashes for zero, bold totals
    with a top border, header fills, indents, column widths, frozen panes, gridlines off.
  • Cell comments (with the VML Excel needs to show them) and hyperlinks, so every sourced number says which
    filing, concept and period it came from and opens the filing.
  • Defined names, list validation (scenario switches), conditional formatting (green OK / red ERROR) and the
    iterative-calculation flag for models with an interest circularity.
Formulas are written without cached values and the file asks Excel to calculate fully on load; use
om.consistency.recalc (LibreOffice) to get calculated values without Excel.

Reader
  read(data) -> Book: every cell's formula, value and font colour, plus defined names and the iterate flag.
  Used by om.modelcheck to grade any workbook, ours or anyone else's.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

# --------------------------------------------------------------------------- conventions
BLUE, BLACK, GREEN, RED, GREY, WHITE = "0000FF", "000000", "008000", "C00000", "7F7F7F", "FFFFFF"
NAVY, HEADER_FILL, INPUT_FILL, SUBTLE_FILL = "0B2A4A", "0B2A4A", "FFF2CC", "F2F2F2"
FONT = "Arial"

FORMATS = {
    "num0": '#,##0_);(#,##0);"–"_)',
    "num1": '#,##0.0_);(#,##0.0);"–"_)',
    "num2": '#,##0.00_);(#,##0.00);"–"_)',
    "pct": '0.0%_);(0.0%);"–"_)',
    "x": '0.0"x"_);(0.0"x")',
    "days": '0.0_);(0.0)',
    "usd2": '$#,##0.00_);($#,##0.00)',
    "int": "0",
    "date": "yyyy-mm-dd",
    "text": "@",
}
CROSS_SHEET = re.compile(r"(?:'[^']+'|[A-Za-z_][\w.]*)!\$?[A-Z]{1,3}\$?\d+")


def col_letter(c: int) -> str:
    out = ""
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def split_ref(ref: str) -> tuple[int, int]:
    m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", ref)
    if not m:
        raise ValueError(f"bad cell reference {ref!r}")
    return int(m.group(2)), col_index(m.group(1))


def ref(r: int, c: int, abs_col: bool = False, abs_row: bool = False) -> str:
    return f"{'$' if abs_col else ''}{col_letter(c)}{'$' if abs_row else ''}{r}"


def quote_sheet(name: str) -> str:
    return f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name


# --------------------------------------------------------------------------- styles
@dataclass(frozen=True)
class Style:
    color: str = BLACK
    bold: bool = False
    italic: bool = False
    size: float = 10
    fmt: str | None = None
    fill: str | None = None
    top: bool = False            # thin top border (totals)
    bottom: bool = False         # thin bottom border (headers)
    indent: int = 0
    align: str | None = None     # left / center / right
    underline: bool = False
    wrap: bool = False


class _StyleBook:
    def __init__(self):
        self.fonts: list[tuple] = []
        self.fills: list[str | None] = []
        self.borders: list[tuple] = [(False, False)]
        self.numfmts: dict[str, int] = {}
        self.xfs: list[tuple] = []
        self.index: dict[Style, int] = {}
        self.dxfs: list[tuple[str, str]] = []
        self.get(Style())                                  # xf 0 = default

    def _idx(self, lst, item):
        if item not in lst:
            lst.append(item)
        return lst.index(item)

    def get(self, s: Style) -> int:
        if s in self.index:
            return self.index[s]
        font = self._idx(self.fonts, (s.color, s.bold, s.italic, s.size, s.underline))
        fill = self._idx(self.fills, s.fill) + 2 if s.fill else 0      # 0 none, 1 gray125 are reserved
        border = self._idx(self.borders, (s.top, s.bottom))
        code = FORMATS.get(s.fmt, s.fmt) if s.fmt else None
        fmt = 0
        if code:
            if code not in self.numfmts:
                self.numfmts[code] = 164 + len(self.numfmts)
            fmt = self.numfmts[code]
        self.xfs.append((fmt, font, fill, border, s.indent, s.align, s.wrap))
        self.index[s] = len(self.xfs) - 1
        return self.index[s]

    def dxf(self, font: str, fill: str) -> int:
        return self._idx(self.dxfs, (font, fill))

    def xml(self) -> str:
        fills = [f for f in self.fills]
        nf = "".join(f'<numFmt numFmtId="{i}" formatCode="{escape(c, {chr(34): "&quot;"})}"/>' for c, i in self.numfmts.items())
        fonts = "".join(
            f'<font>{"<b/>" if b else ""}{"<i/>" if it else ""}{"<u/>" if u else ""}<sz val="{sz:g}"/><color rgb="FF{col}"/><name val="{FONT}"/><family val="2"/></font>'
            for col, b, it, sz, u in self.fonts)
        fill_xml = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' + "".join(
            f'<fill><patternFill patternType="solid"><fgColor rgb="FF{f}"/><bgColor indexed="64"/></patternFill></fill>' for f in fills)
        side = '<{0} style="thin"><color rgb="FF000000"/></{0}>'
        borders = "".join(f'<border><left/><right/>{side.format("top") if t else "<top/>"}{side.format("bottom") if b else "<bottom/>"}<diagonal/></border>'
                          for t, b in self.borders)
        xfs = []
        for fmt, font, fill, border, indent, align, wrap in self.xfs:
            attrs = f'numFmtId="{fmt}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
            attrs += (' applyNumberFormat="1"' if fmt else "") + ' applyFont="1"' + (' applyFill="1"' if fill else "") + (' applyBorder="1"' if border else "")
            al = ""
            if indent or align or wrap:
                attrs += ' applyAlignment="1"'
                al = "<alignment" + (f' horizontal="{align}"' if align else (' horizontal="left"' if indent else "")) + (f' indent="{indent}"' if indent else "") + (' wrapText="1"' if wrap else "") + "/>"
            xfs.append(f"<xf {attrs}>{al}</xf>" if al else f"<xf {attrs}/>")
        dxfs = "".join(f'<dxf><font><b/><color rgb="FF{f}"/></font><fill><patternFill><bgColor rgb="FF{b}"/></patternFill></fill></dxf>' for f, b in self.dxfs)
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<numFmts count="{len(self.numfmts)}">{nf}</numFmts>'
                f'<fonts count="{len(self.fonts)}">{fonts}</fonts>'
                f'<fills count="{len(fills) + 2}">{fill_xml}</fills>'
                f'<borders count="{len(self.borders)}">{borders}</borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
                '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                f'<dxfs count="{len(self.dxfs)}">{dxfs}</dxfs>'
                '</styleSheet>')


# --------------------------------------------------------------------------- sheets
@dataclass
class Cell:
    value: object
    style: Style
    comment: str | None = None
    link: str | None = None           # http(s) URL or internal "Sheet!A1"
    cached: object = None             # calculated result of a formula (om.formula), written as the cell's value


@dataclass
class Sheet:
    name: str
    book: "Workbook"
    cells: dict = field(default_factory=dict)
    widths: dict = field(default_factory=dict)
    freeze: tuple[int, int] | None = None      # (rows above, columns left)
    validations: list = field(default_factory=list)
    cond: list = field(default_factory=list)
    tab: str | None = None
    zoom: int = 85

    def set(self, where: str | tuple, value, *, kind: str | None = None, fmt: str | None = None, bold: bool = False,
            italic: bool = False, indent: int = 0, top: bool = False, bottom: bool = False, fill: str | None = None,
            align: str | None = None, color: str | None = None, size: float = 10, comment: str | None = None,
            link: str | None = None, wrap: bool = False, underline: bool = False) -> str:
        """kind: input (blue, hard-coded), hist (blue, sourced historical), calc (black formula), link (green,
        another sheet), text, header, title, check. Inferred from the value when not given."""
        r, c = split_ref(where) if isinstance(where, str) else where
        if kind is None:
            if isinstance(value, str) and value.startswith("="):
                kind = "link" if CROSS_SHEET.search(value) else "calc"
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                kind = "input"
            else:
                kind = "text"
        col = color or {"input": BLUE, "hist": BLUE, "calc": BLACK, "link": GREEN, "text": BLACK, "header": WHITE,
                        "title": NAVY, "note": GREY, "check": BLACK}.get(kind, BLACK)
        if kind == "input" and fill is None:
            fill = INPUT_FILL
        if kind == "header":
            fill, bold = fill or HEADER_FILL, True
        if kind == "title":
            bold, size = True, max(size, 14)
        if kind == "note":
            italic = True
        st = Style(color=col, bold=bold, italic=italic, size=size, fmt=fmt, fill=fill, top=top, bottom=bottom,
                   indent=indent, align=align, underline=underline, wrap=wrap)
        self.cells[(r, c)] = Cell(value, st, comment, link)
        return ref(r, c)

    def width(self, col: str | int, w: float) -> None:
        self.widths[col_index(col) if isinstance(col, str) else col] = w

    def validate_list(self, where: str, options: list) -> None:
        self.validations.append((where, ",".join(str(o) for o in options)))

    def ok_error(self, rng: str) -> None:
        """Green fill for "OK", red for anything starting with "ERROR"."""
        self.cond.append((rng, self.book._styles.dxf("006100", "C6EFCE"), self.book._styles.dxf("9C0006", "FFC7CE")))

    # ------------------------------------------------------------------ xml
    def _xml(self, idx: int, rels: list) -> tuple[str, str | None, str | None]:
        sb = self.book._styles
        rows: dict[int, list] = {}
        for (r, c), cell in self.cells.items():
            rows.setdefault(r, []).append((c, cell))
        out_rows, comments, links = [], [], []
        for r in sorted(rows):
            xs = []
            for c, cell in sorted(rows[r], key=lambda t: t[0]):
                a = ref(r, c)
                s = sb.get(cell.style)
                v = cell.value
                if isinstance(v, str) and v.startswith("="):
                    cv = cell.cached
                    f = f"<f>{escape(v[1:])}</f>"
                    if cv is None:
                        xs.append(f'<c r="{a}" s="{s}">{f}</c>')
                    elif isinstance(cv, bool):
                        xs.append(f'<c r="{a}" s="{s}" t="b">{f}<v>{int(cv)}</v></c>')
                    elif isinstance(cv, (int, float)):
                        xs.append(f'<c r="{a}" s="{s}">{f}<v>{repr(float(cv))}</v></c>')
                    elif type(cv).__name__ == "Err":
                        xs.append(f'<c r="{a}" s="{s}" t="e">{f}<v>{escape(cv.code)}</v></c>')
                    else:
                        xs.append(f'<c r="{a}" s="{s}" t="str">{f}<v>{escape(str(cv))}</v></c>')
                elif isinstance(v, bool):
                    xs.append(f'<c r="{a}" s="{s}" t="b"><v>{int(v)}</v></c>')
                elif isinstance(v, (int, float)):
                    xs.append(f'<c r="{a}" s="{s}"><v>{repr(float(v)) if isinstance(v, float) else v}</v></c>')
                elif v is None or v == "":
                    xs.append(f'<c r="{a}" s="{s}"/>')
                else:
                    xs.append(f'<c r="{a}" s="{s}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
                if cell.comment:
                    comments.append((r, c, cell.comment))
                if cell.link:
                    links.append((a, cell.link))
            out_rows.append(f'<row r="{r}">{"".join(xs)}</row>')
        pane = ""
        if self.freeze:
            fr, fc = self.freeze
            tl = ref(fr + 1, fc + 1)
            active = "bottomRight" if fr and fc else ("bottomLeft" if fr else "topRight")
            pane = (f'<pane{f" xSplit={chr(34)}{fc}{chr(34)}" if fc else ""}{f" ySplit={chr(34)}{fr}{chr(34)}" if fr else ""} '
                    f'topLeftCell="{tl}" activePane="{active}" state="frozen"/>')
        views = (f'<sheetViews><sheetView showGridLines="0" zoomScale="{self.zoom}" zoomScaleNormal="{self.zoom}"{" tabSelected=" + chr(34) + "1" + chr(34) if idx == 1 else ""} '
                 f'workbookViewId="0">{pane}</sheetView></sheetViews>')
        cols = ""
        if self.widths:
            cols = "<cols>" + "".join(f'<col min="{c}" max="{c}" width="{w}" customWidth="1"/>' for c, w in sorted(self.widths.items())) + "</cols>"
        cond = ""
        for i, (rng, ok, bad) in enumerate(self.cond):
            first = rng.split(":")[0].replace("$", "")
            cond += (f'<conditionalFormatting sqref="{rng}"><cfRule type="cellIs" dxfId="{ok}" priority="{2 * i + 1}" operator="equal"><formula>"OK"</formula></cfRule>'
                     f'<cfRule type="beginsWith" dxfId="{bad}" priority="{2 * i + 2}" operator="beginsWith" text="ERROR"><formula>LEFT({first},5)="ERROR"</formula></cfRule></conditionalFormatting>')
        dv = ""
        if self.validations:
            dv = f'<dataValidations count="{len(self.validations)}">' + "".join(
                f'<dataValidation type="list" allowBlank="1" showInputMessage="1" showErrorMessage="1" sqref="{w}"><formula1>"{escape(o)}"</formula1></dataValidation>'
                for w, o in self.validations) + "</dataValidations>"
        hl = ""
        if links:
            parts = []
            for a, target in links:
                if re.match(r"https?://", target):
                    rid = f"rId{len(rels) + 1}"
                    rels.append((rid, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", target, True))
                    parts.append(f'<hyperlink ref="{a}" r:id="{rid}"/>')
                else:
                    parts.append(f'<hyperlink ref="{a}" location="{escape(target)}" display="{escape(target)}"/>')
            hl = "<hyperlinks>" + "".join(parts) + "</hyperlinks>"
        legacy, comments_xml, vml = "", None, None
        if comments:
            rid_c, rid_v = f"rId{len(rels) + 1}", f"rId{len(rels) + 2}"
            rels.append((rid_c, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments", f"../comments{idx}.xml", False))
            rels.append((rid_v, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing", f"../drawings/vmlDrawing{idx}.vml", False))
            legacy = f'<legacyDrawing r:id="{rid_v}"/>'
            comments_xml, vml = _comments(comments, idx)
        tab = f'<sheetPr>{f"<tabColor rgb={chr(34)}FF{self.tab}{chr(34)}/>" if self.tab else ""}<pageSetUpPr fitToPage="1"/></sheetPr>'
        xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
               f'{tab}{views}<sheetFormatPr defaultRowHeight="13.2"/>{cols}<sheetData>{"".join(out_rows)}</sheetData>'
               f'{cond}{dv}{hl}<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
               '<pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
               f'{legacy}</worksheet>')
        return xml, comments_xml, vml


def _comments(items: list, idx: int) -> tuple[str, str]:
    body = "".join(f'<comment ref="{ref(r, c)}" authorId="0"><text><r><rPr><sz val="9"/><rFont val="Tahoma"/></rPr>'
                   f'<t xml:space="preserve">{escape(t)}</t></r></text></comment>' for r, c, t in items)
    cxml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><authors><author>open-multiples</author></authors>'
            f'<commentList>{body}</commentList></comments>')
    shapes = []
    for k, (r, c, _) in enumerate(items):
        shapes.append(
            f'<v:shape id="_x0000_s{1024 * idx + k + 1}" type="#_x0000_t202" style="position:absolute;margin-left:80pt;margin-top:2pt;'
            f'width:220pt;height:70pt;z-index:{k + 1};visibility:hidden" fillcolor="#ffffe1" o:insetmode="auto">'
            '<v:fill color2="#ffffe1"/><v:shadow on="t" color="black" obscured="t"/><v:path o:connecttype="none"/>'
            '<v:textbox style="mso-direction-alt:auto"><div style="text-align:left"></div></v:textbox>'
            f'<x:ClientData ObjectType="Note"><x:MoveWithCells/><x:SizeWithCells/><x:Anchor>{c}, 15, {max(r - 2, 0)}, 2, {c + 4}, 15, {r + 4}, 4</x:Anchor>'
            f'<x:AutoFill>False</x:AutoFill><x:Row>{r - 1}</x:Row><x:Column>{c - 1}</x:Column></x:ClientData></v:shape>')
    vml = ('<xml xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">'
           f'<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="{idx}"/></o:shapelayout>'
           '<v:shapetype id="_x0000_t202" coordsize="21600,21600" o:spt="202" path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/>'
           '<v:path gradientshapeok="t" o:connecttype="rect"/></v:shapetype>' + "".join(shapes) + "</xml>")
    return cxml, vml


class Workbook:
    def __init__(self, iterate: bool = False):
        self.sheets: list[Sheet] = []
        self.names: dict[str, str] = {}
        self.iterate = iterate
        self._styles = _StyleBook()

    def sheet(self, name: str, tab: str | None = None) -> Sheet:
        if len(name) > 31 or re.search(r"[\[\]:*?/\\]", name):
            raise ValueError(f"invalid sheet name {name!r}")
        s = Sheet(name, self, tab=tab)
        self.sheets.append(s)
        return s

    def __getitem__(self, name: str) -> Sheet:
        return next(s for s in self.sheets if s.name == name)

    def define(self, name: str, sheet: str, cell: str) -> None:
        r, c = split_ref(cell)
        self.names[name] = f"{quote_sheet(sheet)}!{ref(r, c, True, True)}"

    def to_bytes(self) -> bytes:
        files: dict[str, str] = {}
        overrides, sheet_entries, wb_rels = [], [], []
        any_vml = False
        for i, sh in enumerate(self.sheets, 1):
            rels: list = []
            xml, cxml, vml = sh._xml(i, rels)
            files[f"xl/worksheets/sheet{i}.xml"] = xml
            overrides.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            if cxml:
                files[f"xl/comments{i}.xml"] = cxml
                files[f"xl/drawings/vmlDrawing{i}.vml"] = vml
                overrides.append(f'<Override PartName="/xl/comments{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/>')
                any_vml = True
            if rels:
                files[f"xl/worksheets/_rels/sheet{i}.xml.rels"] = (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + "".join(f'<Relationship Id="{rid}" Type="{t}" Target="{escape(tg)}"{" TargetMode=" + chr(34) + "External" + chr(34) if ext else ""}/>'
                              for rid, t, tg, ext in rels) + "</Relationships>")
            sheet_entries.append(f'<sheet name="{escape(sh.name)}" sheetId="{i}" r:id="rId{i}"/>')
            wb_rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        n = len(self.sheets)
        wb_rels.append(f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        names = ""
        if self.names:
            names = "<definedNames>" + "".join(f'<definedName name="{escape(k)}">{escape(v)}</definedName>' for k, v in self.names.items()) + "</definedNames>"
        calc = '<calcPr calcId="191029" fullCalcOnLoad="1"' + (' iterate="1" iterateCount="100" iterateDelta="0.001"' if self.iterate else "") + "/>"
        files["xl/workbook.xml"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                    f'<bookViews><workbookView activeTab="0"/></bookViews><sheets>{"".join(sheet_entries)}</sheets>{names}{calc}</workbook>')
        files["xl/_rels/workbook.xml.rels"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                                               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(wb_rels) + "</Relationships>")
        files["xl/styles.xml"] = self._styles.xml()
        files["_rels/.rels"] = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        files["[Content_Types].xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            + ('<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>' if any_vml else "")
            + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(overrides) + "</Types>")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for k in ["[Content_Types].xml", "_rels/.rels"] + [k for k in files if k not in ("[Content_Types].xml", "_rels/.rels")]:
                z.writestr(k, files[k])
        return buf.getvalue()


# --------------------------------------------------------------------------- formula references
_STR = re.compile(r'"[^"]*"')
_REF = re.compile(r"(?<![A-Za-z_\d$.])(\$?)([A-Z]{1,3})(\$?)(\d{1,7})(?![\d(A-Za-z_])")


def _outside_strings(formula: str, fn) -> str:
    out, last = [], 0
    for m in _STR.finditer(formula):
        out.append(fn(formula[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(fn(formula[last:]))
    return "".join(out)


def shift(formula: str, dr: int, dc: int) -> str:
    """Move a formula's relative references by (dr rows, dc columns), as copying a cell does."""
    def mv(part: str) -> str:
        def one(m):
            cabs, cl, rabs, rw = m.groups()
            c = col_index(cl) if cabs else col_index(cl) + dc
            r = int(rw) if rabs else int(rw) + dr
            return f"{cabs}{col_letter(max(c, 1))}{rabs}{max(r, 1)}"
        return _REF.sub(one, part)
    return _outside_strings(formula, mv)


def relative(formula: str, row: int, col: int) -> str:
    """R1C1-style form: identical for formulas that are copies of each other across a row or column."""
    def rel(part: str) -> str:
        def one(m):
            cabs, cl, rabs, rw = m.groups()
            c = f"C{col_index(cl)}" if cabs else f"C[{col_index(cl) - col}]"
            r = f"R{rw}" if rabs else f"R[{int(rw) - row}]"
            return r + c
        return _REF.sub(one, part)
    return _outside_strings(formula, rel)


def literals(formula: str) -> list[float]:
    """Numeric constants written inside a formula (excluding cell references and function names)."""
    def strip_refs(part: str) -> str:
        part = re.sub(r"(?:'[^']+'|[A-Za-z_][\w.]*)!", "", part)
        part = _REF.sub(" ", part)
        return re.sub(r"[A-Za-z_][A-Za-z0-9_.]*", " ", part)
    body = _outside_strings(formula.lstrip("="), lambda p: strip_refs(p))
    body = _STR.sub(" ", body)
    return [float(x) for x in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", body)]


# --------------------------------------------------------------------------- reader
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


@dataclass
class RCell:
    formula: str | None
    value: object
    color: str | None          # font RGB ("0000FF"), None if theme/default
    bold: bool = False
    is_error: bool = False


@dataclass
class Book:
    sheets: dict               # name -> {(row, col): RCell}
    order: list
    names: dict
    iterate: bool
    comments: dict = field(default_factory=dict)   # name -> {(row, col): text}
    links: dict = field(default_factory=dict)      # name -> {(row, col): target}

    def cell(self, sheet: str, where: str) -> RCell | None:
        return self.sheets.get(sheet, {}).get(split_ref(where))

    def value(self, sheet: str, where: str):
        c = self.cell(sheet, where)
        return c.value if c else None


def read(data: bytes) -> Book:
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    xf_font: list[tuple[str | None, bool]] = []
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        fonts = []
        fe = st.find(f"{NS}fonts")
        for f in (fe.findall(f"{NS}font") if fe is not None else []):
            c = f.find(f"{NS}color")
            rgb = c.get("rgb")[-6:].upper() if c is not None and c.get("rgb") else None
            fonts.append((rgb, f.find(f"{NS}b") is not None and f.find(f"{NS}b").get("val") not in ("0", "false")))
        xe = st.find(f"{NS}cellXfs")
        for xf in (xe.findall(f"{NS}xf") if xe is not None else []):
            fid = int(xf.get("fontId") or 0)
            xf_font.append(fonts[fid] if fid < len(fonts) else (None, False))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wrels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PNS}Relationship"):
            wrels[r.get("Id")] = "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    dn = {d.get("name"): d.text for d in wb.iter(f"{NS}definedName")}
    calc = wb.find(f"{NS}calcPr")
    iterate = calc is not None and calc.get("iterate") in ("1", "true")
    sheets, order, comments, links = {}, [], {}, {}
    for i, sh in enumerate(wb.iter(f"{NS}sheet")):
        part = wrels.get(sh.get(f"{RNS}id")) or f"xl/worksheets/sheet{i + 1}.xml"
        if part not in names:
            continue
        grid, masters = {}, {}
        for c in ET.fromstring(z.read(part)).iter(f"{NS}c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r") or "")
            if not m:
                continue
            rc = (int(m.group(2)), col_index(m.group(1)))
            f, v, t = c.find(f"{NS}f"), c.find(f"{NS}v"), c.get("t")
            s = int(c.get("s") or 0)
            color, bold = xf_font[s] if s < len(xf_font) else (None, False)
            val, err = None, False
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{NS}t"))
            elif t == "e":
                val, err = (v.text if v is not None else "#VALUE!"), True
            elif t == "b" and v is not None:
                val = v.text == "1"
            elif t == "str" and v is not None:
                val = v.text or ""
            elif v is not None and v.text is not None:
                try:
                    val = float(v.text)
                except ValueError:
                    val = v.text
            formula = None
            if f is not None:
                if f.get("t") == "shared" and f.get("si") is not None:
                    si = f.get("si")
                    if f.text:
                        masters[si] = (rc, f.text)
                        formula = "=" + f.text
                    elif si in masters:
                        (r0, c0), text = masters[si]
                        formula = "=" + shift(text, rc[0] - r0, rc[1] - c0)
                elif f.text:
                    formula = "=" + f.text
            grid[rc] = RCell(formula, val, color, bold, err)
        sheets[sh.get("name")] = grid
        order.append(sh.get("name"))
        # comments and hyperlinks hang off the sheet's relationships
        rels_part = part.rsplit("/", 1)[0] + "/_rels/" + part.rsplit("/", 1)[1] + ".rels"
        rels = {}
        if rels_part in names:
            for r in ET.fromstring(z.read(rels_part)).iter(f"{PNS}Relationship"):
                rels[r.get("Id")] = (r.get("Type", ""), r.get("Target", ""))
        cm, lk = {}, {}
        for rid, (typ, target) in rels.items():
            if typ.endswith("/comments"):
                cpart = "xl/" + target.replace("../", "") if target.startswith("../") else part.rsplit("/", 1)[0] + "/" + target
                cpart = cpart if cpart in names else "xl/" + target.lstrip("/").removeprefix("xl/")
                if cpart in names:
                    for cmt in ET.fromstring(z.read(cpart)).iter(f"{NS}comment"):
                        try:
                            cm[split_ref(cmt.get("ref"))] = "".join(t.text or "" for t in cmt.iter(f"{NS}t"))
                        except ValueError:
                            pass
        root = ET.fromstring(z.read(part))
        for h in root.iter(f"{NS}hyperlink"):
            try:
                rc = split_ref(h.get("ref").split(":")[0])
            except ValueError:
                continue
            rid = h.get(f"{RNS}id")
            lk[rc] = rels.get(rid, ("", ""))[1] if rid else (h.get("location") or "")
        comments[sh.get("name")] = cm
        links[sh.get("name")] = lk
    return Book(sheets, order, dn, iterate, comments, links)
