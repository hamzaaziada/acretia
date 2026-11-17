"""Deterministic workbook validator (S4.1): the checks a model reviewer runs before opening the file.

validate(xlsx_bytes) -> {"passed", "findings", "stats", "modelcheck"}. `passed` is False iff any finding is critical.
Finding ids are stable: modelcheck.<grader>, units, sensitivity.table, sensitivity.live, links.green, hardcode.calc,
hardcode.typed, hardcode.isolated, consistency.columns, consistency.rows, sources.missing (require_sources=True only),
circularity, noise.merged, noise.volatile, noise.gridlines, errors.

No LLM and no network. Builds on om.modelcheck (grading), om.xlsx (reading) and om.formula (cycles / convergence);
reads the raw sheet XML for what om.xlsx does not expose (formula types, merged cells, gridlines, number formats).
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from . import formula as fx
from . import modelcheck as mc
from .xlsx import CROSS_SHEET, col_index, col_letter, read, ref, relative

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CAP = 50
GREENS = ("008000", "00B050", "006100", "00B000")
SCALE_NAMES = {1e3: "thousands", 1e6: "millions", 1e9: "billions"}
VOLATILE = re.compile(r"\b(OFFSET|INDIRECT|NOW|TODAY|RANDBETWEEN|RAND)\s*\(", re.I)
CONVERSION = re.compile(r"[*/]\s*\(?\s*(1000|1e3|1000000|1e6|1000000000|1e9)\b", re.I)
CONV_NAME = re.compile(r"conv|unit|scale|fx|thousand|million|billion", re.I)
SHEET_REF = re.compile(r"(?:'([^']+)'|([A-Za-z_][\w.]*))!")
CELL_REF = re.compile(r"(?:(?:'[^']+'|[A-Za-z_][\w.]*)!)?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")
STRINGS = re.compile(r'"[^"]*"')
SENS_LABEL = re.compile(r"sensitivit", re.I)
SCALE_PATTERNS = (
    (1e9, re.compile(r"\bbillions?\b|\$\s?bn\b|(?-i:\b[A-Z]{3}\s?bn\b)|\bin\s+bn\b|\$\s?b\b", re.I)),
    (1e6, re.compile(r"\bmillions?\b|\$\s?mm?n?\b|(?-i:\b[A-Z]{3}\s?mm?\b)|\bin\s+mm?n?\b|\bmn\b", re.I)),
    (1e3, re.compile(r"\bthousands?\b|\$\s?k\b|\$\s?000s?\b|'000s?\b|\bin\s+000s?\b|(?-i:\b[A-Z]{3}\s?k\b)", re.I)),
)
ROW_UNIT = re.compile(r"\(\s*[^()]*\)|^\s*\$|^\s*[A-Z]{3}\b", re.I)


# --------------------------------------------------------------------------- raw sheet XML
def _raw(data: bytes) -> dict:
    """{sheet: {"cells": {rc: {"f": text|None, "t": f-type|None, "s": style idx}}, "merges": [(r1,c1,r2,c2)],
    "gridlines": bool}} plus "_fmt": {style idx: format code}."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    codes: dict[int, str] = {}
    xf_fmt: list[int] = []
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        for nf in st.iter(f"{NS}numFmt"):
            codes[int(nf.get("numFmtId"))] = nf.get("formatCode") or ""
        xe = st.find(f"{NS}cellXfs")
        for xf in (xe.findall(f"{NS}xf") if xe is not None else []):
            xf_fmt.append(int(xf.get("numFmtId") or 0))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    wrels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{PNS}Relationship"):
            wrels[r.get("Id")] = "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    out: dict = {"_fmt": {i: codes.get(f, "") for i, f in enumerate(xf_fmt)}}
    for i, sh in enumerate(wb.iter(f"{NS}sheet")):
        part = wrels.get(sh.get(f"{RNS}id")) or f"xl/worksheets/sheet{i + 1}.xml"
        if part not in names:
            continue
        root = ET.fromstring(z.read(part))
        cells = {}
        for c in root.iter(f"{NS}c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r") or "")
            if not m:
                continue
            f = c.find(f"{NS}f")
            cells[(int(m.group(2)), col_index(m.group(1)))] = {
                "f": f.text if f is not None else None, "t": f.get("t") if f is not None else None,
                "s": int(c.get("s") or 0), "has_f": f is not None}
        merges = []
        for mcell in root.iter(f"{NS}mergeCell"):
            m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", mcell.get("ref") or "")
            if m:
                merges.append((int(m.group(2)), col_index(m.group(1)), int(m.group(4)), col_index(m.group(3))))
        sv = root.find(f"{NS}sheetViews/{NS}sheetView")
        grid = sv is None or sv.get("showGridLines") not in ("0", "false")
        out[sh.get("name")] = {"cells": cells, "merges": merges, "gridlines": grid}
    return out


# --------------------------------------------------------------------------- helpers
def _scales(text: str) -> set:
    return {s for s, rx in SCALE_PATTERNS if rx.search(text)}


def _fmt_scale(code: str) -> float | None:
    """Display scale a number format implies: trailing commas after a digit placeholder, or a "m"/"bn"/"k" suffix."""
    if not code:
        return None
    suffix = re.search(r'"\s*(bn|b|m|mm|mn|k)\s*"', code, re.I)
    bare = STRINGS.sub("", code)
    commas = re.search(r"[0#?](,+)(?![0#?,])", bare)
    n = len(commas.group(1)) if commas else 0
    if n:
        return {1: 1e3, 2: 1e6, 3: 1e9}.get(n)
    if suffix:
        return {"bn": 1e9, "b": 1e9, "m": 1e6, "mm": 1e6, "mn": 1e6, "k": 1e3}[suffix.group(1).lower()]
    return None


def _refs(formula: str, default_sheet: str, names: dict) -> list[tuple[str, tuple[int, int, int, int]]]:
    """[(sheet, (r1, c1, r2, c2))] for every cell/range reference in the formula (strings stripped)."""
    body = STRINGS.sub('""', formula)
    out = []
    for m in re.finditer(r"(?:(?:'([^']+)'|([A-Za-z_][\w.]*))!)?\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?(?![\w(])", body):
        if m.start() and re.match(r"[\w.]", body[m.start() - 1]):
            continue
        sheet = m.group(1) or m.group(2) or default_sheet
        c1, r1 = col_index(m.group(3)), int(m.group(4))
        c2, r2 = (col_index(m.group(5)), int(m.group(6))) if m.group(5) else (c1, r1)
        out.append((sheet, (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))))
    return out


SHAPE_REF = re.compile(r"(?<![\w.$])\$?[A-Z]{1,3}\$?\d+(?![\w(])")


def _shape(formula: str) -> str:
    """The formula with every cell reference replaced by #: equal for cells that do the same thing on different rows/columns."""
    return SHAPE_REF.sub("#", formula)


def _tokens(shape: str) -> set:
    return set(re.findall(r"[A-Za-z_][\w.]*!?", STRINGS.sub('""', shape)))


def _similarity(a: str, b: str) -> float:
    """Share of the smaller formula's tokens found in the other (1.0 when one formula is the other with a piece added or removed)."""
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(min(len(ta), len(tb)), 1)


def _uses_name(formula: str, names: dict) -> bool:
    body = STRINGS.sub('""', formula)
    return any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w(!])", body) for n in names if not n.startswith("_xlnm"))


def _numeric(cell) -> bool:
    return cell is not None and (bool(cell.formula) or (isinstance(cell.value, float)))


def _where(sheet: str, rc: tuple) -> str:
    return f"{sheet}!{ref(*rc)}"


class _Findings:
    def __init__(self):
        self.items: list[dict] = []
        self.counts: dict[str, int] = {}
        self.truncated: dict[str, int] = {}

    def add(self, fid: str, severity: str, sheet, cell, message: str) -> None:
        n = self.counts[fid] = self.counts.get(fid, 0) + 1
        if n > CAP:
            self.truncated[fid] = n
            return
        self.items.append({"id": fid, "severity": severity, "sheet": sheet, "cell": cell, "message": message})


# --------------------------------------------------------------------------- sensitivity blocks
def _sens_blocks(book) -> list[dict]:
    """Each block: {sheet, label_rc, header_row, header_col, cols (c1..c2 grid columns), rows (grid rows)}."""
    blocks = []
    for sheet in book.order:
        g = book.sheets[sheet]
        for (r0, c0), c in sorted(g.items()):
            if c0 > 2 or not isinstance(c.value, str) or not SENS_LABEL.search(c.value) or c.formula:
                continue
            found = None
            for hr in range(r0 + 1, r0 + 4):
                cols = sorted(cc for (rr, cc), x in g.items() if rr == hr and cc > c0 and _numeric(x))
                run = []
                for cc in cols:
                    if run and cc != run[-1] + 1:
                        if len(run) >= 3:
                            break
                        run = []
                    run.append(cc)
                if len(run) >= 3:
                    found = (hr, run)
                    break
            if not found:
                continue
            hr, run = found
            c1, c2 = run[0], run[-1]
            below = g.get((hr + 1, c1 - 1))
            hc, gc1 = (c1 - 1, c1) if _numeric(below) and c1 - 1 > c0 - 1 and c1 - 1 >= 1 else (c1, c1 + 1)
            rows = []
            r = hr + 1
            while _numeric(g.get((r, hc))) and any((r, cc) in g for cc in range(gc1, c2 + 1)):
                rows.append(r)
                r += 1
            if rows:
                blocks.append({"sheet": sheet, "label": (r0, c0), "hr": hr, "hc": hc, "cols": list(range(gc1, c2 + 1)), "rows": rows})
    return blocks


# --------------------------------------------------------------------------- the validator
# --------------------------------------------------------------------------- consistency.rowset
PERIOD_LABEL = re.compile(r"^\s*(?:FY|CY|F|H|Q[1-4]\s*)?'?\d{2,4}\s*([A-Za-z]{0,3})\s*$")
TOTAL_LABEL = re.compile(r"\b(total|subtotal|check|checks|sum)\b", re.I)
_ROWTOK = re.compile(r"((?:'[^']+'|[A-Za-z_][\w.]*)!)?R(\[-?\d+\]|\d+)C")


def _period_kinds(g: dict) -> dict:
    """{column: 'A' (historical) | 'E' (projection)} from the first period-label header row in rows 1-12 of a sheet."""
    best: dict = {}
    for r in range(1, 13):
        cols = {}
        for (rr, cc), c in g.items():
            if rr == r and cc >= 3 and isinstance(c.value, str) and not c.formula:
                m = PERIOD_LABEL.match(c.value)
                if m:
                    cols[cc] = "A" if m.group(1).upper() in ("A", "ACT") else "E"
        if len(cols) >= 2 and len(cols) > len(best):
            best = cols
    return best


def _rowset(rel: str) -> frozenset:
    return frozenset((m.group(1) or "", m.group(2)) for m in _ROWTOK.finditer(rel))


def _rowset_findings(book, F, flagged: set, grid_cells: set, hdr_rows: set, blocks: list) -> None:
    """consistency.rowset: in a row of period columns, one formula that differs from the pattern of its row-mates.
    Majority rule when one exists; with two cells or no majority the row is flagged when the cells reference different sets of
    rows/sheets. Exempt: totals/checks rows, cells across the historical/projection boundary, the first projection column when
    it opens from the last historical column, and sensitivity grids."""
    for s in book.order:
        g = book.sheets[s]
        kinds = _period_kinds(g)
        if len(kinds) < 2:
            continue
        sens_rows = {r for b in blocks if b["sheet"] == s for r in range(min(b["hr"], *b["rows"]), max(b["rows"]) + 1)}
        rows: dict[int, dict] = {}
        for (r, cc), c in g.items():
            if c.formula and cc in kinds:
                rows.setdefault(r, {})[cc] = c
        for r, cells in sorted(rows.items()):
            label = " ".join(str(g[(r, k)].value) for k in (1, 2) if (r, k) in g and isinstance(g[(r, k)].value, str))
            if TOTAL_LABEL.search(label) or (s, r) in hdr_rows or r in sens_rows:
                continue
            run: list[int] = []
            runs = []
            for k in sorted(cells):
                if run and (k != run[-1] + 1 or kinds[k] != kinds[run[-1]]):
                    runs.append(run)
                    run = []
                run.append(k)
            runs.append(run)
            for run in runs:
                forms = {k: relative(cells[k].formula, r, k) for k in run}
                if len(run) > 1 and kinds[run[0]] == "E" and kinds.get(run[0] - 1) == "A" and re.search(r"C\[-1\]", forms[run[0]]) \
                        and forms[run[0]] != forms[run[1]] and all(forms[k] == forms[run[1]] for k in run[2:]):
                    run = run[1:]              # opening balance: the first projection column opens from the last historical column
                if len(run) < 2:
                    continue
                forms = {k: forms[k] for k in run}
                if not any(re.search(r"C\[(?:0|-1)\]", f) for f in forms.values()):
                    continue                    # not a time series: scenario columns / fixed-point valuation cells
                sets = {k: _rowset(forms[k]) for k in run}
                counts: dict = {}
                for f in forms.values():
                    counts[f] = counts.get(f, 0) + 1
                top = max(counts, key=counts.get)
                odd = None
                if counts[top] >= 2 and counts[top] == len(run) - 1:
                    odd = next(k for k in run if forms[k] != top)
                else:
                    scount: dict = {}
                    for v in sets.values():
                        scount[v] = scount.get(v, 0) + 1
                    stop = max(scount, key=scount.get)
                    if len(scount) > 1 and (scount[stop] >= 2 or len(run) == 2):
                        odd = next((k for k in reversed(run) if sets[k] != stop), None)
                    if odd is not None and len(scount) > 2:
                        odd = None
                if odd is None or (s, (r, odd)) in flagged or (s, r, odd) in grid_cells:
                    continue
                flagged.add((s, (r, odd)))
                F.add("consistency.rowset", "critical", s, ref(r, odd),
                      f"formula differs from its {len(run) - 1} row-mate{'s' if len(run) > 2 else ''} in a period row "
                      f"(references rows {sorted(x[1] for x in sets[odd])} vs {sorted(x[1] for x in sets[next(k for k in run if k != odd)])}): "
                      f"{cells[odd].formula[:50]}")


def validate(data: bytes, *, circ_policy: str = "breaker", require_green_links: bool = True, units: str | None = None,
             require_sources: bool = False) -> dict:
    if circ_policy not in ("breaker", "forbid"):
        raise ValueError("circ_policy must be 'breaker' or 'forbid'")
    book = read(data)
    raw = _raw(data)
    grade = mc.grade(data)
    F = _Findings()
    formulas = [(s, rc, c) for s in book.order for rc, c in book.sheets[s].items() if c.formula]

    # ---- modelcheck.<grader>: failing critical graders, one finding per located cell
    for g in grade["graders"]:
        if not g["critical"] or g["passed"] is not False:
            continue
        if not g["cells"]:
            F.add(f"modelcheck.{g['id']}", "critical", None, None, f"{g['title']}: {g['detail']}")
            continue
        for item in g["cells"]:
            m = re.match(r"^(.+?)!(\$?[A-Z]{1,3}\d+)", item)
            F.add(f"modelcheck.{g['id']}", "critical", m.group(1) if m else None, m.group(2) if m else None, f"{g['title']}: {item}")

    # ---- errors: cached error values
    for s in book.order:
        for rc, c in sorted(book.sheets[s].items()):
            if c.is_error:
                F.add("errors", "critical", s, ref(*rc), f"cached error value {c.value}")

    # ---- sensitivity.table: TABLE(), data tables and array formulas, from the raw XML
    for s in book.order:
        for rc, info in sorted(raw.get(s, {}).get("cells", {}).items()):
            kind = info["t"] if info["t"] in ("dataTable", "array") else None
            if kind or (info["f"] and re.search(r"\bTABLE\s*\(", info["f"], re.I)):
                what = {"dataTable": "data table", "array": "array formula"}.get(kind, "TABLE() formula")
                F.add("sensitivity.table", "critical", s, ref(*rc), f"{what}: sensitivities must be live closed-form formula grids")

    # ---- sensitivity.live
    blocks = _sens_blocks(book)
    grid_cells = set()
    for b in blocks:
        g = book.sheets[b["sheet"]]
        for r in b["rows"]:
            for cc in b["cols"]:
                grid_cells.add((b["sheet"], r, cc))
                cell = g.get((r, cc))
                if cell is None:
                    F.add("sensitivity.live", "critical", b["sheet"], ref(r, cc), "empty cell inside a sensitivity grid")
                    continue
                if not cell.formula:
                    F.add("sensitivity.live", "critical", b["sheet"], ref(r, cc), f"typed value {cell.value!r} inside a sensitivity grid: every cell must be a live formula")
                    continue
                hdr, model = False, False
                for sh, (r1, c1, r2, c2) in _refs(cell.formula, b["sheet"], book.names):
                    inside_hdr = sh == b["sheet"] and ((r1 == r2 == b["hr"] and c1 == c2 and b["cols"][0] <= c1 <= b["cols"][-1])
                                                       or (c1 == c2 == b["hc"] and r1 == r2 and r1 in b["rows"]))
                    if inside_hdr:
                        hdr = True
                    elif not (sh == b["sheet"] and r1 == r2 and c1 == c2 and (r1, c1) in {(rr, ccc) for rr in b["rows"] for ccc in b["cols"]}):
                        model = True
                if not model and _uses_name(cell.formula, book.names):
                    model = True
                if not (hdr and model):
                    why = ("does not reference a header cell" if not hdr else "") + (" and " if not hdr and not model else "") + \
                          ("does not reference a model cell" if not model else "")
                    F.add("sensitivity.live", "critical", b["sheet"], ref(r, cc), f"sensitivity grid cell {why}: {cell.formula[:60]}")

    # ---- links.green
    if require_green_links:
        for s, rc, c in formulas:
            if CROSS_SHEET.search(c.formula) and c.color not in GREENS:
                F.add("links.green", "critical", s, ref(*rc), f"link to another sheet is not green (font {c.color or 'default'}): {c.formula[:50]}")

    # ---- hardcode.calc
    hardcoded = 0
    flagged: set = set()
    for s in book.order:
        if mc.INPUT_SHEET.search(s):
            continue
        g = book.sheets[s]
        rows: dict[int, list] = {}
        for (r, cc), c in g.items():
            if cc > 2:
                rows.setdefault(r, []).append((cc, c))
        for r, cells in sorted(rows.items()):
            if not any(c.formula for _, c in cells):
                continue
            for cc, c in sorted(cells, key=lambda t: t[0]):
                if c.formula or not isinstance(c.value, float) or c.color == "FFFFFF" or (s, r, cc) in grid_cells:
                    continue
                sourced = c.color in mc.BLUES and ((r, cc) in book.comments.get(s, {}) or (r, cc) in book.links.get(s, {}))
                if sourced:
                    continue
                hardcoded += 1
                flagged.add((s, (r, cc)))
                F.add("hardcode.calc", "critical", s, ref(r, cc), f"typed number {c.value:g} in a calculation row that is otherwise formulas")

    # ---- hardcode.typed / hardcode.isolated: a typed number disguised as a calculation
    for s in book.order:
        g = book.sheets[s]
        input_sheet = bool(mc.INPUT_SHEET.search(s))
        for (r, cc), c in sorted(g.items()):
            if c.formula or not isinstance(c.value, float) or (s, (r, cc)) in flagged or (s, r, cc) in grid_cells:
                continue
            if c.color not in mc.BLUES and c.color != "FFFFFF":
                flagged.add((s, (r, cc)))
                F.add("hardcode.typed", "critical", s, ref(r, cc), f"typed number {c.value:g} in black (calculation) font: a hard-coded value where a formula belongs")
            elif not input_sheet and cc > 2 and (r, cc) not in book.comments.get(s, {}) and (r, cc) not in book.links.get(s, {}):
                above = next((g.get((rr, cc)) for rr in range(r - 1, max(r - 4, 0), -1) if g.get((rr, cc)) is not None), None)
                below = next((g.get((rr, cc)) for rr in range(r + 1, r + 4) if g.get((rr, cc)) is not None), None)
                if above is not None and below is not None and above.formula and below.formula:
                    flagged.add((s, (r, cc)))
                    F.add("hardcode.isolated", "critical", s, ref(r, cc),
                          f"typed number {c.value:g} with no source sits between formulas in its column: looks like a plug")

    hdr_rows = {(b["sheet"], b["hr"]) for b in blocks}
    already = {(f["sheet"], f["cell"]) for f in F.items}
    # ---- consistency.columns / consistency.rows: one cell breaks the formula pattern shared by the others in its line
    # (a row of per-company or per-year columns, or a column of stacked per-company rows). Edge cells are covered, which the
    # modelcheck consistency grader (needs a neighbour each side) cannot see. The first cell of a line may differ (opening balance).
    for s in book.order:
        g = book.sheets[s]
        for axis, fid in (("row", "consistency.columns"), ("col", "consistency.rows")):
            lines: dict[int, dict] = {}
            for (r, cc), c in g.items():
                if cc >= 3 and c.formula:
                    lines.setdefault(r if axis == "row" else cc, {})[cc if axis == "row" else r] = c
            for key, cells in sorted(lines.items()):
                run: list[int] = []
                runs = []
                for k in sorted(cells):
                    if run and k != run[-1] + 1:
                        runs.append(run)
                        run = []
                    run.append(k)
                runs.append(run)
                for run in runs:
                    if len(run) < (3 if axis == "row" else 4):
                        continue
                    pos = (lambda k: (key, k)) if axis == "row" else (lambda k: (k, key))
                    forms = {k: relative(cells[k].formula, *pos(k)) if axis == "row" else _shape(cells[k].formula) for k in run}
                    counts: dict[str, int] = {}
                    for f in forms.values():
                        counts[f] = counts.get(f, 0) + 1
                    top = max(counts, key=counts.get)
                    if counts[top] < max(2, len(run) - 1) or len(run) - counts[top] != 1:
                        continue
                    odd = next(k for k in run if forms[k] != top)
                    if (axis == "row" and odd == run[0]) or (s, pos(odd)) in flagged or (s, ref(*pos(odd))) in already or (s, *pos(odd)) in grid_cells or (s, pos(odd)[0]) in hdr_rows:
                        continue
                    if axis == "col" or len(run) < 4:
                        # a different line item (a total under its parts, a header row) is not a broken copy of the pattern: the odd
                        # formula must share names/functions and at least one cell reference with the others
                        mates = [relative(cells[k].formula, *pos(k)) for k in run if k != odd]
                        mine = set(re.findall(r"R\[?-?\d+\]?C\[?-?\d+\]?", relative(cells[odd].formula, *pos(odd))))
                        if _similarity(forms[odd], top) < 0.6 or not any(mine & set(re.findall(r"R\[?-?\d+\]?C\[?-?\d+\]?", m)) for m in mates):
                            continue
                    flagged.add((s, pos(odd)))
                    F.add(fid, "critical", s, ref(*pos(odd)),
                          f"formula breaks the pattern of the other {counts[top]} cells in its {'row' if axis == 'row' else 'column'}: "
                          f"{cells[odd].formula[:50]}")

    _rowset_findings(book, F, flagged, grid_cells, hdr_rows, blocks)

    # ---- sources.missing (parity item 20): every typed historical number outside input sheets must cite its source
    if require_sources:
        for s in book.order:
            if mc.INPUT_SHEET.search(s):
                continue
            for rc, c in sorted(book.sheets[s].items()):
                if c.formula or not isinstance(c.value, float) or rc in book.comments.get(s, {}) or rc in book.links.get(s, {}):
                    continue
                F.add("sources.missing", "critical", s, ref(*rc), f"typed number {c.value:g} has no source comment or filing link")

    # ---- circularity
    eng = fx.from_book(book)
    eng.calculate(iterate=True)
    cyc = mc._cycles(eng)
    breaker = None
    if cyc:
        first = sorted(cyc)[0]
        cf = [eng.raw[k] for k in cyc if isinstance(eng.raw.get(k), str)]
        breaker = any(re.search(r"IF\(", f, re.I) and re.search(r"(?<![\w.])circ\w*(?![\w(])", STRINGS.sub('""', f), re.I)
                      and any(n.lower().startswith("circ") for n in book.names) for f in cf)
        loc = (first[0], ref(first[1], first[2]))
        if circ_policy == "forbid":
            F.add("circularity", "critical", loc[0], loc[1], f"{len(cyc)} cells in circular references and the policy forbids any")
        else:
            problems = []
            if not book.iterate:
                problems.append("iterative calculation is off")
            if not breaker:
                problems.append("no 1/0 breaker (IF on a switch named like Circ) in the loop")
            if not eng.converged:
                problems.append(f"does not converge ({eng.iterations} iterations)")
            if problems:
                F.add("circularity", "critical", loc[0], loc[1], f"{len(cyc)} cells in circular references: " + "; ".join(problems))

    # ---- noise
    for s in book.order:
        info = raw.get(s, {})
        fcells = {rc for rc, c in book.sheets[s].items() if c.formula}
        for (r1, c1, r2, c2) in info.get("merges", []):
            hit = sorted(rc for rc in fcells if r1 <= rc[0] <= r2 and c1 <= rc[1] <= c2)
            if hit:
                F.add("noise.merged", "critical", s, f"{ref(r1, c1)}:{ref(r2, c2)}", f"merged cells overlap formula cell {ref(*hit[0])}")
        if info.get("gridlines", False):
            F.add("noise.gridlines", "warning", s, None, "gridlines are shown")
    for s, rc, c in formulas:
        m = VOLATILE.search(STRINGS.sub('""', c.formula))
        if m:
            F.add("noise.volatile", "warning", s, ref(*rc), f"volatile function {m.group(1).upper()}(): {c.formula[:50]}")

    # ---- units
    declared: dict[str, set] = {}
    for s in book.order:
        sc: set = set()
        for (r, cc), c in book.sheets[s].items():
            if isinstance(c.value, str) and not c.formula:
                if r <= 8:
                    sc |= _scales(c.value)
                elif cc <= 2 and not re.search(r"share|per\s", c.value, re.I) and (cc == 2 or re.search(r"\([^()]*\)\s*$", c.value)):
                    sc |= _scales(c.value)
        if sc:
            declared[s] = sc
    primary = {s: next(iter(v)) for s, v in declared.items() if len(v) == 1}
    for s, v in declared.items():
        if len(v) > 1:
            F.add("units", "critical", s, None, "sheet mixes declared scales: " + ", ".join(sorted(SCALE_NAMES[x] for x in v)))
    if units:
        want = next((k for k, n in SCALE_NAMES.items() if n.startswith(units.lower().rstrip("s")) or units.lower() in n), None)
        for s, v in declared.items():
            if want and v != {want}:
                F.add("units", "critical", s, None, f"sheet declares {', '.join(sorted(SCALE_NAMES[x] for x in v))}; expected {SCALE_NAMES[want]}")
    for s, rc, c in formulas:
        if s not in primary:
            continue
        body = STRINGS.sub('""', c.formula)
        targets = {m.group(1) or m.group(2) for m in SHEET_REF.finditer(body)} - {s}
        for t in sorted(targets):
            if t in primary and primary[t] != primary[s]:
                if not (CONVERSION.search(body) or any(CONV_NAME.search(n) and re.search(rf"(?<![\w.]){re.escape(n)}(?![\w(!])", body) for n in book.names)):
                    F.add("units", "critical", s, ref(*rc),
                          f"links {SCALE_NAMES[primary[t]]} sheet {t} into {SCALE_NAMES[primary[s]]} sheet without a x/÷ 1000 conversion: {c.formula[:50]}")
    fmts = raw.get("_fmt", {})
    for s in book.order:
        if s not in primary:
            continue
        for rc, info in sorted(raw.get(s, {}).get("cells", {}).items()):
            cell = book.sheets[s].get(rc)
            if cell is None or not (cell.formula or isinstance(cell.value, float)):
                continue
            fs = _fmt_scale(fmts.get(info["s"], ""))
            if fs and fs != primary[s]:
                F.add("units", "warning", s, ref(*rc), f"number format {fmts[info['s']]!r} implies {SCALE_NAMES[fs]} but the sheet declares {SCALE_NAMES[primary[s]]}")
                break

    findings = F.items
    passed = not any(f["severity"] == "critical" for f in findings)
    stats = {"sheets": book.order, "formulas": len(formulas), "typed_numbers": grade["stats"]["typed_numbers"],
             "hardcoded_calc_cells": hardcoded, "sensitivity_blocks": len(blocks), "circular_cells": len(cyc),
             "declared_units": {s: sorted(SCALE_NAMES[x] for x in v) for s, v in declared.items()},
             "finding_counts": F.counts, "truncated": F.truncated,
             "critical": sum(1 for f in findings if f["severity"] == "critical"),
             "warnings": sum(1 for f in findings if f["severity"] == "warning")}
    return {"passed": passed, "findings": findings, "stats": stats, "modelcheck": grade}


def report(result: dict) -> str:
    st = result["stats"]
    lines = [f"{'PASSED' if result['passed'] else 'FAILED'}: {st['critical']} critical, {st['warnings']} warnings; "
             f"{st['formulas']:,} formulas on {len(st['sheets'])} sheets; modelcheck score {result['modelcheck']['score']}/100; "
             f"hardcoded calc cells {st['hardcoded_calc_cells']}"]
    for f in result["findings"]:
        where = f"{f['sheet']}!{f['cell']}" if f["sheet"] and f["cell"] else (f["sheet"] or "workbook")
        lines.append(f"  [{f['severity'].upper():8}] {f['id']:22} {where}: {f['message']}")
    for fid, n in st["truncated"].items():
        lines.append(f"  ... {fid}: {n} total, first {CAP} shown")
    return "\n".join(lines)
