"""Banker-grade Excel export of the document grid and of auto-extracted PDF tables (S5.5b, parity-spec 10, 14, 20).

Uses only the house writer (om.xlsx) and the public GridStore calls (view, formatted_view, export_rows, cells, questions,
group_by_source, tables, document_name, runs). Nothing here talks to a model or the network.

  export_grid_xlsx(store, grid_id, path=None, *, logo_png=None, title=None, include_unverified=False) -> bytes
      Sheets "Matrix" (typed values, one Excel NOTE per answered cell: p.<page>: "<exact quote>" [<engine>, <conf>]),
      "Sources" (one row per answered cell: page, exact quote, bbox, span hash, engine, confidence, cost) and "Run log".
      not_found -> "Not found" (grey); unverified / error -> "Needs review" (amber, the raw answer is never exported unless
      include_unverified=True, then it is prefixed UNVERIFIED); skipped-by-condition -> "Skipped (condition)".
  export_tables_xlsx(store, doc_ids_or_grid_id, path=None) -> bytes     one sheet per extracted table plus an "Index" sheet
  export_tables_csv(store, doc_id, out_dir) -> list[str]                one CSV per extracted table
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from om import xlsx

MATRIX, SOURCES, RUNLOG = "Matrix", "Sources", "Run log"
HEADER_ROW = 5                       # rows 1-4: logo / title / as-of line
GREY, AMBER_FILL, AMBER_FONT, BAND = "7F7F7F", "FFF2CC", "9C5700", "F7F9FB"
QUOTE_MAX = 250
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_STAMP = {"currency": '$#,##0.00_);($#,##0.00)', "number": '#,##0.##_);(#,##0.##)', "percent": "0.0%", "date": "yyyy-mm-dd"}
_ANSWERED = ("ok", "extracted")


def _clean(s) -> str:
    return _ILLEGAL.sub("", "" if s is None else str(s))


def _conf(c) -> str:
    return "n/a" if c is None else f"{float(c):.2f}"


def _trunc(q: str, n: int = QUOTE_MAX) -> str:
    return q if len(q) <= n else q[: n - 1].rstrip() + "…"


def _note(c: dict) -> str:
    return f"p.{c['page']}: “{_trunc(_clean(c['exact_quote']))}” [{c['engine']}, {_conf(c['confidence'])}]"


def _stamp(iso) -> str:
    try:
        t = datetime.fromisoformat(str(iso))
    except ValueError:
        t = datetime.now(timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _serial(d) -> float | None:
    try:
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            d = date.fromisoformat(str(d)[:10])
        return float((d - date(1899, 12, 30)).days)
    except ValueError:
        return None


def _num(x):
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _typed_cell(qtype: str, typed, answer: str):
    """(value, number format or None) for an answered cell. Falls back to text whenever the typed value is not usable."""
    if qtype in ("currency", "number", "percent"):
        n = _num(typed)
        if n is not None:
            if qtype == "percent":
                return n / 100.0, _STAMP["percent"]       # the grid stores 12.5 for 12.5 %
            if qtype == "number" and n == int(n) and abs(n) < 1e15:
                return n, '#,##0_);(#,##0)'
            return n, _STAMP[qtype]
    elif qtype == "date":
        s = _serial(typed)
        if s is not None and isinstance(typed, str):
            return s, _STAMP["date"]
    elif qtype == "boolean":
        if isinstance(typed, bool):
            return ("Yes" if typed else "No"), None
    return _clean(answer), None


def _width(q: dict) -> float:
    return {"text": 46, "list": 46, "boolean": 12, "date": 14}.get(q["type"], 17)


def _add_autofilter(data: bytes, sheet_no: int, rng: str, sheet_name: str) -> bytes:
    """om.xlsx has no autofilter yet: add <autoFilter> to the sheet part and the hidden _FilterDatabase name."""
    a, b = rng.split(":")
    absr = ":".join("$" + re.sub(r"(\d+)", r"$\1", p) for p in (a, b))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            raw = zi.read(info.filename)
            if info.filename == f"xl/worksheets/sheet{sheet_no}.xml":
                raw = raw.decode("utf-8").replace("</sheetData>", f'</sheetData><autoFilter ref="{rng}"/>', 1).encode("utf-8")
            elif info.filename == "xl/workbook.xml":
                s = raw.decode("utf-8")
                dn = (f'<definedName name="_xlnm._FilterDatabase" localSheetId="{sheet_no - 1}" hidden="1">'
                      f"{xlsx.quote_sheet(sheet_name)}!{absr}</definedName>")
                s = s.replace("<definedNames>", "<definedNames>" + dn, 1) if "<definedNames>" in s else \
                    s.replace("</sheets>", "</sheets><definedNames>" + dn + "</definedNames>", 1)
                raw = s.encode("utf-8")
            zi_new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi_new.compress_type = zipfile.ZIP_DEFLATED
            zi_new.external_attr = info.external_attr
            zi_new.create_system = info.create_system
            zo.writestr(zi_new, raw)
    return out.getvalue()


def _finish(data: bytes, path) -> bytes:
    if path:
        Path(path).write_bytes(data)
    return data


# =========================================================================== grid workbook
def export_grid_xlsx(store, grid_id, path=None, *, logo_png: bytes | None = None, title: str | None = None,
                     include_unverified: bool = False) -> bytes:
    v = store.formatted_view(grid_id)
    gid, gname = v["grid_id"], v["name"]
    qs = v["questions"]
    rules = {r["id"]: r["style"] for r in v.get("format_rules", [])}
    raw_by = {(c["doc_id"], c["question_id"]): c for c in store.cells(gid)}
    typed_rows = {r["doc_id"]: r for r in store.export_rows(gid)}
    runs = store.runs(gid)

    wb = xlsx.Workbook()
    ws = wb.sheet(MATRIX, tab="0B2A4A")
    first_q = 3
    last_col = first_q + len(qs) - 1 if qs else 2
    ws.width(1, 36)
    ws.width(2, 24)
    for i, q in enumerate(qs):
        ws.width(first_q + i, _width(q))

    name_col = 1
    if logo_png:
        ws.image(logo_png, ("A1", "A3"), name="Logo", max_height_px=54)
        name_col = 2
    stamp = _stamp(runs[-1].get("finished_at") if runs else None)
    run_id = runs[-1]["run_id"] if runs else "no run yet"
    ws.set((1, name_col), _clean(title or gname), kind="title")
    ws.set((2, name_col), f"As of {stamp}  |  Run {run_id}  |  {len(v['rows'])} documents x {len(qs)} questions", kind="note")
    ws.set((3, name_col), "Every figure carries a cell note with its page and exact quote; see the Sources sheet.", kind="note")

    for col, label in ((1, "Document"), (2, "Document Source")):
        ws.set((HEADER_ROW, col), label, kind="header", wrap=True)
    for i, q in enumerate(qs):
        tip = q["text"] + (f"\n\nInstructions: {q['instructions']}" if q["instructions"] else "")
        ws.set((HEADER_ROW, first_q + i), _clean(q["label"] or q["id"]), kind="header", wrap=True, comment=_clean(tip),
               align="right" if q["type"] in ("currency", "number", "percent", "date") else None)

    sources = []
    answered = 0
    r = HEADER_ROW
    for row_i, row in enumerate(v["rows"]):
        r += 1
        band = BAND if row_i % 2 else None
        ws.set((r, 1), _clean(row["name"]), bold=True, fill=band, wrap=True)
        ws.set((r, 2), _clean(row["source_folder"]), fill=band, wrap=True, color=GREY)
        for i, q in enumerate(qs):
            col = first_q + i
            c = row["cells"].get(q["id"])
            style_ids = (c or {}).get("styles") or []
            fill, color, bold = band, None, False
            for sid in style_ids:
                st = rules.get(sid, {})
                fill = st["fill"].lstrip("#").upper() if st.get("fill") else fill
                color = st["font"].lstrip("#").upper() if st.get("font") else color
                bold = bold or bool(st.get("bold"))
            where = (r, col)
            status = c["status"] if c else "pending"
            if status in _ANSWERED:
                answered += 1
                typed = typed_rows[row["doc_id"]].get(q["id"])
                val, fmt = _typed_cell(q["type"], typed, c["answer"])
                numeric = not isinstance(val, str)
                ws.set(where, val, kind="hist" if numeric else "text", fmt=fmt, fill=fill, color=color,
                       bold=bold, wrap=not numeric, comment=_note(c), align="right" if numeric else None,
                       indent=0 if numeric else 1)
                bb = c["bbox_norm"] or (None,) * 4
                sources.append((row["name"], q["label"] or q["id"], c["page"], _clean(c["exact_quote"]), *bb,
                                c["sha256_span_hash"], c["engine"], c["confidence"], c["cost_usd"], ref_pending(where)))
            elif status == "not_found":
                ws.set(where, "Not found", kind="note", fill=fill, color=color or GREY, bold=bold)
            elif status in ("unverified", "error"):
                raw = _clean((raw_by.get((row["doc_id"], q["id"])) or {}).get("raw_answer"))
                if include_unverified and status == "unverified" and raw:
                    ws.set(where, f"UNVERIFIED: {raw}", fill=AMBER_FILL, color=AMBER_FONT, italic=True, wrap=True,
                           comment="UNVERIFIED: the quote could not be located in the source document. Do not rely on this figure.")
                else:
                    ws.set(where, "Needs review", fill=AMBER_FILL, color=AMBER_FONT, bold=True)
            elif status == "skipped":
                ws.set(where, "Skipped (condition)", kind="note", fill=fill, color=color or GREY, bold=bold)
            else:
                ws.set(where, "Pending", kind="note", fill=fill, color=GREY)
    last_row = max(r, HEADER_ROW)
    ws.freeze = (HEADER_ROW, 1)
    ws.print_setup(title_rows=HEADER_ROW, title_cols="A", footer=(f"Source: Acretia grid {gname}", "", ""),
                   landscape=True, fit_width=1, fit_height=0)

    src = wb.sheet(SOURCES, tab="2E6DA4")
    heads = ["Document", "Question", "Page", "Exact quote", "bbox x0", "bbox y0", "bbox x1", "bbox y1", "Span hash",
             "Engine", "Confidence", "Cost (USD)", "Matrix cell"]
    for col, w in zip(range(1, 14), (30, 26, 7, 70, 9, 9, 9, 9, 26, 14, 11, 11, 12)):
        src.width(col, w)
    for col, h in enumerate(heads, 1):
        src.set((1, col), h, kind="header", wrap=True)
    for k, s in enumerate(sources, 2):
        doc, q, page, quote, x0, y0, x1, y1, h, eng, conf, cost, cellref = s
        src.set((k, 1), _clean(doc), wrap=True)
        src.set((k, 2), _clean(q), wrap=True)
        src.set((k, 3), page, kind="hist", fmt="int", align="center")
        src.set((k, 4), quote, wrap=True, indent=1)
        for j, b in enumerate((x0, y0, x1, y1)):
            src.set((k, 5 + j), b, kind="hist", fmt="0.0000") if b is not None else src.set((k, 5 + j), "")
        src.set((k, 9), h, color=GREY)
        src.set((k, 10), eng)
        src.set((k, 11), conf, kind="hist", fmt="0.00") if conf is not None else src.set((k, 11), "n/a", color=GREY)
        src.set((k, 12), cost, kind="hist", fmt='$#,##0.0000')
        src.set((k, 13), cellref, link=f"{MATRIX}!{cellref}", color=xlsx.BLUE, underline=True)
    src.freeze = (1, 0)
    src.print_setup(title_rows=1, footer=(f"Source: Acretia grid {gname}", "", ""))

    log = wb.sheet(RUNLOG, tab="7F7F7F")
    heads = ["Run", "Engine", "Started", "Finished", "Cells touched", "Skipped", "Elapsed (s)", "First cell (s)",
             "Tokens in", "Tokens out", "Est. cost (USD)", "Actual cost (USD)"]
    for col, (h, w) in enumerate(zip(heads, (18, 14, 22, 22, 12, 9, 11, 12, 11, 11, 15, 16)), 1):
        log.set((1, col), h, kind="header", wrap=True)
        log.width(col, w)
    for k, rn in enumerate(runs, 2):
        vals = [rn["run_id"], rn["engine"], rn["started_at"], rn["finished_at"], rn["touched"], rn["skipped"],
                rn["elapsed_s"], rn["first_cell_s"], rn["tokens_in"], rn["tokens_out"], rn["est_cost_usd"], rn["actual_cost_usd"]]
        fmts = [None, None, None, None, "int", "int", "num2", "num2", "num0", "num0", '$#,##0.0000', '$#,##0.0000']
        for col, (val, f) in enumerate(zip(vals, fmts), 1):
            if val is None:
                log.set((k, col), "", )
            elif f:
                log.set((k, col), val, kind="hist", fmt=f)
            else:
                log.set((k, col), _clean(val))
    if not runs:
        log.set((2, 1), "No runs recorded for this grid.", kind="note")
    log.freeze = (1, 0)
    log.print_setup(title_rows=1, footer=(f"Source: Acretia grid {gname}", "", ""))

    data = wb.to_bytes()
    data = _add_autofilter(data, 1, f"A{HEADER_ROW}:{xlsx.col_letter(last_col)}{last_row}", MATRIX)
    return _finish(data, path)


def ref_pending(where: tuple) -> str:
    return xlsx.ref(*where)


# =========================================================================== tables
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def parse_number(text) -> tuple[float, str] | None:
    """(value, number format) when the WHOLE cell is a number: 1,234 / (1,234) / -5 / $1,234.50 / 12.5% / ($3.2). None otherwise."""
    t = _clean(text).strip().replace("−", "-").replace("–", "-").replace("\xa0", " ")
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t.startswith("-"):
        neg, t = True, t[1:].strip()
    dollar = t.startswith("$")
    if dollar:
        t = t[1:].strip()
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    if t.startswith("-"):                                   # $-5
        neg, t = True, t[1:].strip()
    if not _NUM.fullmatch(t):
        return None
    v = float(t.replace(",", ""))
    dec = len(t.split(".")[1]) if "." in t else 0
    if neg:
        v = -v
    zeros = "0" * dec
    body = f"#,##0.{zeros}" if dec else "#,##0"
    if pct:
        return v / 100.0, f"0.{zeros}%" if dec else "0%"
    if dollar:
        return v, f"$#,##0.{zeros}_);($#,##0.{zeros})" if dec else "$#,##0_);($#,##0)"
    if "," not in t and dec == 0 and 1900 <= abs(v) <= 2100 and not neg:
        return v, "0"                                       # a year, not an amount: no thousands separator
    return v, f"{body}_);({body})"


def _safe_sheet(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name).strip("' ")[:31] or "Table"
    n, cand = 1, base
    while cand.lower() in used:
        n += 1
        suf = f" ({n})"
        cand = base[: 31 - len(suf)] + suf
    used.add(cand.lower())
    return cand


def _resolve_docs(store, spec) -> list[str]:
    if isinstance(spec, str):
        try:
            return [r["doc_id"] for r in store.view(spec)["rows"]]
        except KeyError:
            return [spec]
    return list(dict.fromkeys(spec))


def export_tables_xlsx(store, doc_ids_or_grid_id, path=None) -> bytes:
    docs = _resolve_docs(store, doc_ids_or_grid_id)
    wb = xlsx.Workbook()
    idx = wb.sheet("Index", tab="0B2A4A")
    used = {"index"}
    multi = len(docs) > 1
    entries = []
    for d in docs:
        dname = store.document_name(d)
        per_page: dict[int, int] = {}
        for t in store.tables(d):
            per_page[t["page"]] = per_page.get(t["page"], 0) + 1
            nm = f"p{t['page']} T{per_page[t['page']]}"
            if multi:
                nm = f"{re.sub(chr(46) + 'pdf$', '', dname, flags=re.I)[:14]} {nm}"
            sh_name = _safe_sheet(nm, used)
            sh = wb.sheet(sh_name)
            rows = t["rows"]
            ncols = max((len(r) for r in rows), default=0)
            widths = [8] * ncols
            numeric_first = any(parse_number(c) for c in (rows[0] if rows else []))
            for i, row in enumerate(rows, 1):
                for j, cell in enumerate(row, 1):
                    txt = _clean(cell)
                    widths[j - 1] = min(60, max(widths[j - 1], len(txt) + 2))
                    parsed = parse_number(txt)
                    head = i == 1 and not numeric_first
                    if parsed:
                        sh.set((i, j), parsed[0], kind="hist", fmt=parsed[1], align="right")
                    else:
                        sh.set((i, j), txt, bold=head, bottom=head, wrap=len(txt) > 60)
            for j, w in enumerate(widths, 1):
                sh.width(j, w)
            bb = ", ".join(f"{x:.4f}" for x in t["bbox_norm"])
            note = f"{dname}, p.{t['page']}, table bbox (normalised) [{bb}], source {t['source']}, span {t['sha256_span_hash']}"
            if rows and rows[0]:
                sh.cells[(1, 1)].comment = note
            else:
                sh.set((1, 1), "", comment=note)
            sh.print_setup(footer=(f"Source: {dname} p.{t['page']}", "", ""), landscape=True)
            entries.append((sh_name, dname, t["page"], len(rows), ncols, t["source"], t["sha256_span_hash"]))
    heads = ["Sheet", "Document", "Page", "Rows", "Columns", "Extractor", "Span hash"]
    for col, (h, w) in enumerate(zip(heads, (22, 34, 7, 8, 9, 12, 40)), 1):
        idx.set((1, col), h, kind="header")
        idx.width(col, w)
    for k, (sn, dn, pg, nr, nc, src, h) in enumerate(entries, 2):
        idx.set((k, 1), sn, link=f"{xlsx.quote_sheet(sn)}!A1", color=xlsx.BLUE, underline=True)
        idx.set((k, 2), _clean(dn))
        idx.set((k, 3), pg, kind="hist", fmt="int")
        idx.set((k, 4), nr, kind="hist", fmt="int")
        idx.set((k, 5), nc, kind="hist", fmt="int")
        idx.set((k, 6), src)
        idx.set((k, 7), h, color=GREY)
    if not entries:
        idx.set((2, 1), "No tables were extracted from these documents.", kind="note")
    idx.freeze = (1, 0)
    return _finish(wb.to_bytes(), path)


def export_tables_csv(store, doc_id, out_dir) -> list[str]:
    import csv
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w.-]+", "_", re.sub(r"\.pdf$", "", store.document_name(doc_id), flags=re.I)).strip("_") or "doc"
    files, per_page = [], {}
    for t in store.tables(doc_id):
        per_page[t["page"]] = per_page.get(t["page"], 0) + 1
        p = out / f"{stem}_p{t['page']}_T{per_page[t['page']]}.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(t["rows"])
        files.append(str(p))
    return files
