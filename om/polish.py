"""S4.7b: banker-grade polish layer shared by every workbook builder (three-statement, LBO, merger, comps).

  finish(wb, model_name=, source=, period_sheets=)   print setup, outline groups, freeze panes, number-format defaults
  waterfall(sh, ...)                                 formula-driven bridge table + stacked-column waterfall chart
  football_field(sh, ...)                            formula-driven low/high table + floating-bar football field
  trend(sh, ...)                                     column / line chart over cells that already exist
  section(sh, row, title, ...)                       a tidy "Chart data" section heading

Everything a helper writes is a formula (black on the same sheet, green when it links to another sheet) with a number
format; no typed numbers, no merged cells. Chart series are bound to those cells, never to typed data.
"""
from __future__ import annotations

import dataclasses

from .xlsx import NAVY, Sheet, Workbook, col_index, col_letter, quote_sheet, ref

CONFIDENTIAL = "Strictly private & confidential"
C_TOTAL, C_UP, C_DOWN = "0B2A4A", "2E6DA4", "C00000"
C_RANGE = "2E6DA4"


def _col(c) -> int:
    return col_index(c) if isinstance(c, str) else int(c)


def _rng(sh: Sheet, c: int, r1: int, r2: int | None = None) -> str:
    r2 = r1 if r2 is None else r2
    return f"{quote_sheet(sh.name)}!{ref(r1, c, True, True)}:{ref(r2, c, True, True)}"


def _cell(sh: Sheet, r: int, c: int) -> str:
    return f"{quote_sheet(sh.name)}!{ref(r, c, True, True)}"


def _fm(f: str) -> str:
    return f if f.startswith("=") else "=" + f


# --------------------------------------------------------------------------- finish
def _default_fmt(cell) -> str | None:
    v = cell.cached if (isinstance(cell.value, str) and cell.value.startswith("=")) else cell.value
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, int) and 1900 <= v <= 2100 and not (isinstance(cell.value, str)):
        return "int"
    if float(v) != int(v) and abs(v) < 100:
        return "num2"
    return "num0"


def _extent(sh: Sheet) -> tuple[int, int]:
    rows = [r for r, _ in sh.cells] or [1]
    cols = [c for _, c in sh.cells] or [1]
    from .xlsx import split_ref
    for ch in sh.charts:
        r2, c2 = split_ref(ch["anchor"][1])
        rows.append(r2)
        cols.append(c2)
    return max(rows), max(cols)


def finish(wb: Workbook, *, model_name: str, source: str, period_sheets: dict[str, dict] | None = None) -> None:
    """Apply the house finish to every sheet.

    period_sheets maps a sheet name to {"hist": (first_col, last_col), "proj": (first_col, last_col)} (letters or 1-based
    indices); those column blocks get outline level 1 (visible, collapsible) and the sheet gets freeze panes (6, 2) when it
    has none. Print setup on every sheet: landscape, fit 1 page wide, print titles (rows 5:6 and columns A:B on frozen
    period sheets, rows 2:3 elsewhere), print area covering cells and charts, header = confidential marking, footer =
    (source, model name, "Page &P of &N"); the writer appends the page counter on the right, so the R slot is left empty.
    Every numeric cell without a number format gets one (num0 / num2 / int); text and explicit formats are left alone."""
    period_sheets = period_sheets or {}
    for sh in wb.sheets:
        spec = period_sheets.get(sh.name)
        if spec:
            for key in ("hist", "proj"):
                if spec.get(key):
                    sh.group_cols(_col(spec[key][0]), _col(spec[key][1]), level=1, hidden=False)
            if sh.freeze is None:
                sh.freeze = (6, 2)
        for cell in sh.cells.values():
            if cell.style.fmt is None:
                f = _default_fmt(cell)
                if f:
                    cell.style = dataclasses.replace(cell.style, fmt=f)
            st = cell.style
            if st.top and st.bold and st.named in ("Normal", "Calculation") and cell.value not in (None, ""):
                cell.style = dataclasses.replace(st, named="Total")      # total rows: bold with a top rule
        last_r, last_c = _extent(sh)
        if sh.freeze and sh.freeze[0] >= 5:
            fr, fc = sh.freeze
            rows, cols = f"5:{max(fr, 6)}", f"A:{col_letter(max(fc, 1))}"
        else:
            rows, cols = ("2:3" if (2, 1) in sh.cells or (2, 2) in sh.cells else "1:1"), None
        sh.print_setup(area=f"A1:{col_letter(last_c)}{last_r}", title_rows=rows, title_cols=cols,
                       header=("", "", CONFIDENTIAL), footer=(source, model_name, ""), landscape=True, fit_width=1, fit_height=0)


# --------------------------------------------------------------------------- layout helpers
def section(sh: Sheet, row: int, title: str, first_col: int = 2, last_col: int = 8) -> None:
    """A navy section heading with a bottom rule across first_col..last_col."""
    sh.set((row, first_col), title, bold=True, color=NAVY, bottom=True)
    for c in range(first_col + 1, last_col + 1):
        sh.set((row, c), "", bottom=True)


def _head(sh: Sheet, r: int, c: int, labels: list[str]) -> None:
    for i, t in enumerate(labels):
        sh.set((r, c + i), t, bold=True, bottom=True, align="left" if i == 0 else "right")


# --------------------------------------------------------------------------- waterfall
def waterfall(sh: Sheet, *, top_left: tuple[int, int], steps: list[tuple[str, str]], title: str, anchor: tuple,
              y_format: str = "num0", legend: bool = False) -> dict:
    """Bridge table + stacked-column waterfall. steps = [(label, formula)]; the first and last steps are totals, the
    ones between are signed deltas (their formulas carry the sign). Table columns from top_left (row, col):
      label | value | running | base (invisible) | up | down | total
    Rows start one below the header. Returns {"header_row","first_row","last_row","value_col","cols"} so callers can
    write tie-out checks (sum of first..last-1 values must equal the last value)."""
    r0, c0 = top_left
    n = len(steps)
    if n < 3:
        raise ValueError("a waterfall needs at least a start, one step and an end")
    _head(sh, r0, c0, ["", "Value", "Running", "Base", "Increase", "Decrease", "Total"])
    cols = dict(label=c0, value=c0 + 1, run=c0 + 2, base=c0 + 3, up=c0 + 4, down=c0 + 5, total=c0 + 6)
    A = lambda k, r: ref(r, cols[k])
    for i, (label, f) in enumerate(steps):
        r = r0 + 1 + i
        first, last = i == 0, i == n - 1
        sh.set((r, c0), label, bold=first or last, top=last, indent=0 if (first or last) else 1)
        sh.set((r, cols["value"]), _fm(f), fmt=y_format, bold=first or last, top=last)
        sh.set((r, cols["run"]), f"={A('value', r)}" if first or last else f"={A('run', r - 1)}+{A('value', r)}", fmt=y_format, top=last)
        if first or last:
            sh.set((r, cols["base"]), f"=MIN({A('value', r)},0)", fmt=y_format, top=last)
            sh.set((r, cols["up"]), "=0", fmt=y_format, top=last)
            sh.set((r, cols["down"]), "=0", fmt=y_format, top=last)
            sh.set((r, cols["total"]), f"=MAX({A('value', r)},0)", fmt=y_format, top=last, bold=True)
        else:
            sh.set((r, cols["base"]), f"=MAX(MIN({A('run', r - 1)},{A('run', r)}),0)", fmt=y_format)
            sh.set((r, cols["up"]), f"=MAX({A('value', r)},0)", fmt=y_format)
            sh.set((r, cols["down"]), f"=MAX(-{A('value', r)},0)", fmt=y_format)
            sh.set((r, cols["total"]), "=0", fmt=y_format)
    first_r, last_r = r0 + 1, r0 + n
    cats = _rng(sh, cols["label"], first_r, last_r)
    series = [
        {"name": "Base", "cats": cats, "vals": _rng(sh, cols["base"], first_r, last_r), "invisible": True},
        {"name": "Total", "cats": cats, "vals": _rng(sh, cols["total"], first_r, last_r), "color": C_TOTAL},
        {"name": "Increase", "cats": cats, "vals": _rng(sh, cols["up"], first_r, last_r), "color": C_UP},
        {"name": "Decrease", "cats": cats, "vals": _rng(sh, cols["down"], first_r, last_r), "color": C_DOWN},
    ]
    sh.chart("stacked_column", title=title, series=series, anchor=anchor, y_format=y_format, legend=legend, data_labels=False,
             gap_width=50, overlap=100)
    return dict(header_row=r0, first_row=first_r, last_row=last_r, value_col=cols["value"], cols=cols)


# --------------------------------------------------------------------------- football field
def football_field(sh: Sheet, *, top_left: tuple[int, int], rows: list[tuple[str, str, str]], title: str, anchor: tuple,
                   x_format: str = "usd2", marker: str | None = None, marker_label: str = "Base value per share") -> dict:
    """Valuation ranges as floating bars. rows = [(label, low_formula, high_formula)]. Table columns from top_left:
      label | low | high | spread (= high - low, floored at zero); the chart stacks an invisible low series under the
    spread. marker (optional formula) is written as a labelled row under the table (the point value the bars bracket).
    Returns {"header_row","first_row","last_row","marker_row","cols"}."""
    r0, c0 = top_left
    _head(sh, r0, c0, ["", "Low", "High", "Spread"])
    cols = dict(label=c0, low=c0 + 1, high=c0 + 2, spread=c0 + 3)
    for i, (label, lo, hi) in enumerate(rows):
        r = r0 + 1 + i
        sh.set((r, c0), label, indent=1)
        sh.set((r, cols["low"]), _fm(lo), fmt=x_format)
        sh.set((r, cols["high"]), _fm(hi), fmt=x_format)
        sh.set((r, cols["spread"]), f"=MAX({ref(r, cols['high'])}-{ref(r, cols['low'])},0)", fmt=x_format)
    first_r, last_r = r0 + 1, r0 + len(rows)
    marker_row = None
    if marker:
        marker_row = last_r + 1
        sh.set((marker_row, c0), marker_label, bold=True, top=True)
        sh.set((marker_row, cols["low"]), _fm(marker), fmt=x_format, bold=True, top=True)
        for k in ("high", "spread"):
            sh.set((marker_row, cols[k]), "", top=True)
    cats = _rng(sh, cols["label"], first_r, last_r)
    series = [
        {"name": "Low", "cats": cats, "vals": _rng(sh, cols["low"], first_r, last_r), "invisible": True},
        {"name": "Range", "cats": cats, "vals": _rng(sh, cols["spread"], first_r, last_r), "color": C_RANGE},
    ]
    sh.chart("stacked_bar", title=title, series=series, anchor=anchor, y_format=x_format, legend=False, data_labels=False,
             gap_width=60, overlap=100)
    return dict(header_row=r0, first_row=first_r, last_row=last_r, marker_row=marker_row, cols=cols)


# --------------------------------------------------------------------------- trend
def trend(sh: Sheet, *, title: str, cats: str, series: list[tuple[str, str]], anchor: tuple, kind: str = "column",
          y_format: str = "num0", legend: bool = True, data_labels: bool = False, colors: list | None = None) -> None:
    """Column / line chart over cells that already hold formulas. cats = period-label range; series = [(name_text,
    values_range[, own_cats])], all absolute references like "'Cover'!$C$23:$J$23"."""
    if kind not in ("column", "line", "bar"):
        raise ValueError("trend charts are column, bar or line")
    sers = [{"name": s[0], "vals": s[1], "cats": s[2] if len(s) > 2 else cats} for s in series]
    sh.chart(kind, title=title, series=sers, anchor=anchor,
             y_format=y_format, legend=legend and len(series) > 1, data_labels=data_labels, colors=colors)
