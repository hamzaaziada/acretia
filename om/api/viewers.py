"""Viewer endpoints (SPEC §4): citation preview, PDF inspector data, the Excel model view (live recompute, audit overlay,
explain, tab audit, ask).  Stdlib only; every query is scoped to ``ctx.org_id``; a deal or deliverable of another org
answers 404 exactly like a missing one.

Engines: ``om.wbedit.edit`` (splice + recalculation through ``om.formula``), ``om.wbgraph`` (graph / explain / ask),
``om.xlsx.read``.  ``om.modelapi`` (S4.8) is used for nothing here because it is not on main yet; the three calls above
are the contract it wraps.

No table is created here: ``documents``, ``document_pages`` and ``citations`` belong to the documents module.
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import OrderedDict

from .http import ApiError, Route

SCHEMA = ""  # no tables of our own (see module docstring)

MAX_CHANGES = 200
INPUT_SHEETS = ("Assumptions",)          # sheets whose blue constants form the assumptions panel (plus DCF inputs)
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_BUILTIN_FMT = {0: "General", 1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%", 11: "0.00E+00",
                14: "yyyy-mm-dd", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 37: "#,##0_);(#,##0)", 38: "#,##0_);[Red](#,##0)",
                39: "#,##0.00_);(#,##0.00)", 40: "#,##0.00_);[Red](#,##0.00)", 49: "@"}


# --------------------------------------------------------------------------- helpers
def _store(ctx):
    try:
        from .state import STATE  # type: ignore
        return STATE.deal_store(ctx.conn, ctx.org_id)
    except ImportError:
        from ..deals import DealStore
        return DealStore(ctx.conn, ctx.blobs, ctx.org_id)


def _not_found(what: str, hint: str | None = None) -> ApiError:
    return ApiError(404, "not_found", f"No such {what}.", hint)


def _load(ctx, deal_id: str, name: str, version=None) -> tuple[bytes, int, int]:
    """(bytes, version served, latest version) of an xlsx deliverable; 404 for unknown / other-org deal or name."""
    from ..deals import DealError
    st = _store(ctx)
    try:
        hist = st.history(deal_id, name)
    except DealError:
        raise _not_found("deal", "Check the deal id, or switch to the organization that owns it.") from None
    if not hist:
        raise _not_found("model", f"This deal has no deliverable called {name!r}. Open the Models tab to see what exists.")
    latest = hist[-1]["version"]
    v = latest
    if version not in (None, ""):
        try:
            v = int(version)
        except (TypeError, ValueError):
            raise ApiError(400, "bad_version", "version must be a whole number.", f"Latest is v{latest}.") from None
    row = next((h for h in hist if h["version"] == v), None)
    if row is None:
        raise _not_found("version", f"Versions of {name!r}: 1 to {latest}.")
    if row["kind"] != "xlsx":
        raise ApiError(415, "not_a_workbook", f"{name!r} is a {row['kind']} deliverable, not an Excel model.",
                       "Open it from the Library to download it.")
    try:
        data = st.get_version(deal_id, name, v)
    except Exception:
        raise _not_found("model file") from None
    return data, v, latest


def _num(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return int(v) if v.is_integer() and abs(v) < 1e15 else v
    return v


# --------------------------------------------------------------------------- workbook view (cached per content hash)
_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 8


def _styles(z: zipfile.ZipFile) -> list[str]:
    """Number-format code per cellXfs index."""
    if "xl/styles.xml" not in z.namelist():
        return []
    st = ET.fromstring(z.read("xl/styles.xml"))
    custom = {int(n.get("numFmtId")): n.get("formatCode") or "General" for n in st.iter(f"{_NS}numFmt")}
    xe = st.find(f"{_NS}cellXfs")
    out = []
    for xf in (xe.findall(f"{_NS}xf") if xe is not None else []):
        i = int(xf.get("numFmtId") or 0)
        out.append(custom.get(i) or _BUILTIN_FMT.get(i, "General"))
    return out


def _sheet_layout(data: bytes) -> dict:
    """{sheet: {"fmt": {(r,c): code}, "freeze": (rows, cols), "widths": {col: chars}, "indent": ...}} from the raw XML."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    xf_fmt = _styles(z)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{_PNS}Relationship"):
            rels[r.get("Id")] = "xl/" + r.get("Target").lstrip("/").removeprefix("xl/")
    out = {}
    for i, sh in enumerate(wb.iter(f"{_NS}sheet")):
        part = rels.get(sh.get(f"{_RNS}id")) or f"xl/worksheets/sheet{i + 1}.xml"
        if part not in names:
            continue
        root = ET.fromstring(z.read(part))
        fmt, widths, freeze = {}, {}, (0, 0)
        pane = root.find(f".//{_NS}pane")
        if pane is not None and pane.get("state") in ("frozen", "frozenSplit"):
            freeze = (int(float(pane.get("ySplit") or 0)), int(float(pane.get("xSplit") or 0)))
        for col in root.iter(f"{_NS}col"):
            try:
                lo, hi, w = int(col.get("min")), int(col.get("max")), float(col.get("width"))
            except (TypeError, ValueError):
                continue
            for c in range(lo, min(hi, lo + 200) + 1):
                widths[c] = w
        for c in root.iter(f"{_NS}c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r") or "")
            s = int(c.get("s") or 0)
            if m and s < len(xf_fmt) and xf_fmt[s] != "General":
                from ..xlsx import col_index
                fmt[(int(m.group(2)), col_index(m.group(1)))] = xf_fmt[s]
        out[sh.get("name")] = {"fmt": fmt, "freeze": freeze, "widths": widths}
    return out


_PURE_LINK = re.compile(r"^=\s*[+-]?\s*(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!\$?[A-Z]{1,3}\$?\d+\s*$")
_XSHEET = re.compile(r"(?:'(?:[^']|'')+'|[A-Za-z_][\w.]*)!\$?[A-Z]{1,3}\$?\d+")
_ERR = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!"}
_WHITE = {"FFFFFF"}


def _classify(cell) -> str:
    f = cell.formula
    if f:
        return "link" if _PURE_LINK.match(f) else "calc"
    v = cell.value
    if isinstance(v, bool):
        return "label"
    if isinstance(v, (int, float)):
        return "input"
    if isinstance(v, str) and v:
        if (cell.color or "").upper() in _WHITE:
            return "header"
        return "label"
    return "label"


def _section_of(book, sheet: str, r: int) -> str | None:
    grid = book.sheets.get(sheet, {})
    for rr in range(r - 1, 0, -1):
        c = grid.get((rr, 1))
        if c is not None and isinstance(c.value, str) and c.value and not c.formula and c.bold:
            others = [k for k in grid if k[0] == rr and k[1] >= 3 and grid[k].value not in (None, "")]
            if not others:
                return c.value
    return None


def _bundle(data: bytes) -> dict:
    """Parsed workbook shared by every endpoint: book, graph, layout, per-cell class/format."""
    from .. import wbgraph, xlsx
    import hashlib
    key = hashlib.sha256(data).hexdigest()
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    book = xlsx.read(data)
    g = wbgraph.graph(data)
    b = {"key": key, "book": book, "graph": g, "layout": _sheet_layout(data)}
    _CACHE[key] = b
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return b


def _fmt_of(b: dict, sheet: str, rc: tuple) -> str | None:
    return (b["layout"].get(sheet) or {}).get("fmt", {}).get(rc)


def _citation_tokens(ctx, deal_id: str) -> dict:
    """cell_locator -> citation token for this deal's documents, plus xbrl-backed citations (no document)."""
    try:
        rows = ctx.conn.execute(
            "SELECT c.token, c.cell_locator, c.xbrl_concept FROM citations c "
            "LEFT JOIN documents d ON d.id=c.doc_id AND d.org_id=c.org_id "
            "WHERE c.org_id=? AND c.cell_locator IS NOT NULL AND c.cell_locator<>'' AND (d.deal_id=? OR c.doc_id IS NULL OR c.doc_id='') "
            "ORDER BY c.rowid", (ctx.org_id, deal_id)).fetchall()
    except sqlite3.Error:
        return {}
    out = {}
    for r in rows:
        out.setdefault(r["cell_locator"], {"token": r["token"], "xbrl": r["xbrl_concept"]})
    return out


def _unit_of(fmt: str | None, label: str) -> str:
    f = fmt or ""
    if "%" in f:
        return "%"
    if '"x"' in f or f.endswith("x"):
        return "x"
    if "$" in f:
        return "USD"
    if re.search(r"\b(days|years)\b", label, re.I):
        return "days" if "days" in label.lower() else "years"
    return ""


def _checks(b: dict) -> list[dict]:
    """One entry per row of the Checks sheet that carries OK/ERROR results; the master check comes last."""
    from ..xlsx import col_letter
    book = b["book"]
    grid = book.sheets.get("Checks")
    if not grid:
        return []
    from ..wbgraph import key_of
    rows: dict = {}
    for (r, c), cell in grid.items():
        if c >= 3 and cell.value in ("OK", "ERROR"):
            rows.setdefault(r, []).append((c, cell.value))
    out, master = [], None
    for r in sorted(rows):
        lab = grid.get((r, 1))
        name = str(lab.value) if lab is not None and lab.value else f"Row {r}"
        cs = sorted(rows[r])
        bad = [c for c, v in cs if v != "OK"]
        entry = {"name": name, "ref": key_of("Checks", r, (bad or [c for c, _ in cs])[0]),
                 "status": "fail" if bad else "pass", "value": "ERROR" if bad else "OK", "periods": len(cs),
                 "failing": [f"Checks!{col_letter(c)}{r}" for c in bad]}
        if name.strip().upper() == "MASTER CHECK":
            master = entry
            continue
        out.append(entry)
    if master:
        out.append(master)
    return out


def _view(ctx, deal_id: str, name: str, data: bytes, version: int, latest: int) -> dict:
    from ..wbgraph import label_of
    from ..xlsx import col_letter
    b = _bundle(data)
    book = b["book"]
    cites = _citation_tokens(ctx, deal_id)
    sheets, cells = [], {}
    for sh in book.order:
        grid = book.sheets[sh]
        lay = b["layout"].get(sh, {})
        rmax = max((r for r, _ in grid), default=0)
        cmax = max((c for _, c in grid), default=0)
        fr, fc = lay.get("freeze", (0, 0))
        widths = {col_letter(c): w for c, w in (lay.get("widths") or {}).items() if c <= cmax + 1}
        sheets.append({"name": sh, "rows": rmax, "cols": cmax, "freeze": {"rows": fr, "cols": fc}, "widths": widths})
        for (r, c), cell in grid.items():
            if cell.formula is None and (cell.value is None or cell.value == ""):
                continue
            key = f"{sh}!{col_letter(c)}{r}"
            d: dict = {"v": _num(cell.value), "cls": _classify(cell)}
            if cell.formula:
                d["f"] = cell.formula
            fm = _fmt_of(b, sh, (r, c))
            if fm:
                d["fmt"] = fm
            if cell.bold:
                d["b"] = 1
            if cell.is_error or (isinstance(cell.value, str) and cell.value in _ERR):
                d["err"] = 1
            note = book.comments.get(sh, {}).get((r, c))
            if note:
                d["note"] = note
            url = book.links.get(sh, {}).get((r, c))
            if url and url.startswith("http"):
                d["url"] = url
            ct = cites.get(key)
            if ct and not cell.formula:
                d["citation_token"] = ct["token"]
                if ct.get("xbrl"):
                    d["xbrl_concept"] = ct["xbrl"]
            cells[key] = d
    assumptions = []
    for sh in book.order:
        if sh not in INPUT_SHEETS and sh != "DCF":
            continue
        for (r, c), cell in sorted(book.sheets[sh].items()):
            if cell.formula is not None or not isinstance(cell.value, (int, float)) or isinstance(cell.value, bool):
                continue
            if (cell.color or "").upper() != "0000FF" or c < 3:
                continue
            key = f"{sh}!{col_letter(c)}{r}"
            lab = label_of(book, key)
            base = (cell_label := (book.sheets[sh].get((r, 1)))) and cell_label.value or ""
            fm = _fmt_of(b, sh, (r, c))
            assumptions.append({"ref": key, "label": lab or key, "row_label": str(base), "sheet": sh, "section": _section_of(book, sh, r),
                                "value": _num(cell.value), "fmt": fm, "unit": _unit_of(fm, str(base))})
    out = {"deal_id": deal_id, "name": name, "version": version, "latest": latest, "editable": ctx.role in ("member", "owner"),
           "sheets": sheets, "cells": cells, "assumptions": assumptions, "checks": _checks(b),
           "outputs": _outputs(b)}
    man = _manifest(ctx, deal_id, name)
    if man is not None:
        out["manifest"] = man
    return out


def _outputs(b: dict) -> list[dict]:
    """Headline numbers the rail keeps in view: DCF value per share plus the last forecast year's revenue, EBITDA, FCF."""
    from ..wbgraph import key_of, label_of
    book = b["book"]
    outs = []
    dcf = book.sheets.get("DCF", {})
    for (r, c), cell in sorted(dcf.items()):
        if c == 1 and isinstance(cell.value, str) and cell.value.strip().lower() in ("implied value per share", "implied share price"):
            outs.append({"ref": key_of("DCF", r, 3), "label": cell.value})
            break
    for sh, labels in (("IS", ("revenue", "ebitda", "net income")), ("CF", ("free cash flow",))):
        grid = book.sheets.get(sh, {})
        cmax = max((c for _, c in grid), default=0)
        for (r, c), cell in sorted(grid.items()):
            if c == 1 and isinstance(cell.value, str) and cell.value.strip().lower() in labels and (r, cmax) in grid:
                outs.append({"ref": key_of(sh, r, cmax), "label": label_of(book, key_of(sh, r, cmax)) or cell.value})
    return outs


def _manifest(ctx, deal_id: str, name: str):
    """A ``<name>.manifest.json`` deliverable next to the model, when the agent run wrote one."""
    try:
        st = _store(ctx)
        h = st.history(deal_id, name + ".manifest.json")
        if h:
            return json.loads(st.get_version(deal_id, name + ".manifest.json", h[-1]["version"]).decode("utf-8"))
    except Exception:
        return None
    return None


# --------------------------------------------------------------------------- model routes
def model_get(ctx):
    data, v, latest = _load(ctx, ctx.params["deal_id"], ctx.params["name"], ctx.query.get("version"))
    return _view(ctx, ctx.params["deal_id"], ctx.params["name"], data, v, latest)


def _clean_changes(raw, book) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise ApiError(422, "no_changes", "changes must be an object like {\"Assumptions!F20\": 0.08}.",
                       "Edit an assumption first, then recompute.")
    if len(raw) > MAX_CHANGES:
        raise ApiError(422, "too_many_changes", f"At most {MAX_CHANGES} cells per recompute.")
    out = {}
    for k, val in raw.items():
        if not isinstance(k, str) or "!" not in k:
            raise ApiError(422, "bad_ref", f"{k!r} is not a cell reference.", "Use Sheet!A1, for example Assumptions!F20.")
        sh = k.rsplit("!", 1)[0].strip("'")
        if sh not in book.sheets:
            raise ApiError(422, "unknown_sheet", f"The workbook has no sheet {sh!r}.", "Sheets: " + ", ".join(book.order))
        if isinstance(val, str) and not val.startswith("="):
            s = val.strip().replace(",", "")
            try:
                val = float(s[:-1]) / 100 if s.endswith("%") else float(s)
            except ValueError:
                pass
        if isinstance(val, bool) or not (val is None or isinstance(val, (int, float, str))):
            raise ApiError(422, "bad_value", f"{k}: values must be numbers, text or =formulas.")
        out[k] = val
    return out


def _apply(data: bytes, changes: dict) -> tuple[bytes, dict, float]:
    from .. import wbedit
    t0 = time.perf_counter()
    try:
        new, rep = wbedit.edit(data, changes, recalc=True)
    except wbedit.EditRefused as e:
        raise ApiError(422, "edit_refused", str(e), "This cell cannot be edited here; change an input it depends on.") from None
    except (KeyError, ValueError, TypeError) as e:
        raise ApiError(422, "invalid_edit", str(e).strip("'\""), "Check the cell reference and the value.") from None
    return new, rep, (time.perf_counter() - t0) * 1000


def model_recompute(ctx):
    ctx.require("viewer")
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    body = ctx.json if isinstance(ctx.json, dict) else {}
    data, v, latest = _load(ctx, deal_id, name, body.get("version"))
    b = _bundle(data)
    changes = _clean_changes(body.get("changes"), b["book"])
    new, rep, ms = _apply(data, changes)
    nb = _bundle(new)
    changed = {}
    for c in rep["changed"]:
        changed[c["cell"]] = {"v_old": _num(c["old_value"]), "v_new": _num(c["new_value"])}
    for d in rep["dependents_updated"]:
        changed[d["cell"]] = {"v_old": _num(d["old"]), "v_new": _num(d["new"])}
    return {"changed": changed, "checks": _checks(nb), "ms": round(ms, 1), "version": v, "latest": latest,
            "outputs": [{"ref": o["ref"], "value": _num(_cell_value(nb["book"], o["ref"]))} for o in _outputs(nb)]}


def _cell_value(book, ref: str):
    sh, a1 = ref.rsplit("!", 1)
    c = book.cell(sh, a1)
    return c.value if c else None


def model_save(ctx):
    ctx.require("member")
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    body = ctx.json if isinstance(ctx.json, dict) else {}
    data, v, latest = _load(ctx, deal_id, name, body.get("version"))
    if v != latest:
        raise ApiError(409, "stale_version", f"You are editing v{v} but v{latest} exists.",
                       "Reload the model, re-apply your changes and save again, so nobody's work is overwritten.")
    changes = _clean_changes(body.get("changes"), _bundle(data)["book"])
    new, rep, ms = _apply(data, changes)
    note = str(body.get("note") or "").strip()[:500] or "Edited in the model view: " + ", ".join(list(changes)[:4])
    from ..deals import DealError
    try:
        meta = _store(ctx).save_deliverable(deal_id, name, new, "xlsx", note)
    except DealError as e:
        raise ApiError(422, "save_failed", str(e)) from None
    ctx.audit("model.save", f"{deal_id}/{name}", {"version": meta["version"], "cells": sorted(changes)[:20]})
    return {"version": meta["version"], "name": name, "size": meta["size"], "note": note, "created_at": meta["created_at"],
            "cells_changed": len(rep["changed"]), "dependents_updated": len(rep["dependents_updated"]), "ms": round(ms, 1)}


def _validate_ref(b: dict, ref: str) -> str:
    from .. import wbgraph
    if not ref or "!" not in ref:
        raise ApiError(400, "bad_ref", "ref must look like Sheet!A1.", "Click a cell first.")
    try:
        key = wbgraph.norm_key(ref)
        sh = wbgraph.split_key(key)[0]
    except Exception:
        raise ApiError(400, "bad_ref", f"{ref!r} is not a cell reference.", "Use Sheet!A1.") from None
    if sh not in b["book"].sheets:
        raise ApiError(404, "not_found", f"No sheet {sh!r}.")
    return key


def model_explain(ctx):
    from .. import wbgraph
    data, v, _ = _load(ctx, ctx.params["deal_id"], ctx.params["name"], ctx.query.get("version"))
    b = _bundle(data)
    key = _validate_ref(b, ctx.query.get("ref", ""))
    book, g = b["book"], b["graph"]
    if key not in g.nodes:
        return {"cell": key, "label": wbgraph.label_of(book, key), "formula": None, "value": None, "empty": True,
                "precedents": [], "dependents": [], "inputs": []}
    ex = wbgraph.explain(data, key, _graph=g, _book=book)
    deps = []
    for d in wbgraph.dependents(g, key, depth=1)[:60]:
        n = g.nodes.get(d)
        deps.append({"cell": d, "label": wbgraph.label_of(book, d), "formula": n.formula if n else None, "value": _num(n.value) if n else None})
    ex["dependents"] = deps
    ex["n_dependents"] = len(wbgraph.dependents(g, key))
    ex["value"] = _num(ex.get("value"))
    ct = _citation_tokens(ctx, ctx.params["deal_id"]).get(key)
    if ct and not ex.get("formula"):
        ex["citation_token"] = ct["token"]
    ex["note"] = book.comments.get(wbgraph.split_key(key)[0], {}).get(wbgraph.split_key(key)[1:3])
    return ex


def model_audit(ctx):
    """Tab audit (parity 44): per sheet, cross-sheet links, hard-codes sitting in calculation rows, and errors."""
    from .. import wbgraph
    from ..xlsx import col_letter
    data, v, _ = _load(ctx, ctx.params["deal_id"], ctx.params["name"], ctx.query.get("version"))
    b = _bundle(data)
    book = b["book"]
    cites = _citation_tokens(ctx, ctx.params["deal_id"])
    sheets, totals = [], {"links": 0, "hardcodes": 0, "errors": 0}
    for sh in book.order:
        grid = book.sheets[sh]
        row_has_formula: dict = {}
        for (r, c), cell in grid.items():
            if cell.formula:
                row_has_formula[r] = row_has_formula.get(r, 0) + 1
        links, hard, errs, counts = [], [], [], {"input": 0, "calc": 0, "link": 0}
        for (r, c), cell in sorted(grid.items()):
            key = f"{sh}!{col_letter(c)}{r}"
            cls = _classify(cell)
            if cls in counts:
                counts[cls] += 1
            if cell.is_error or (isinstance(cell.value, str) and cell.value in _ERR):
                errs.append({"ref": key, "value": cell.value, "label": wbgraph.label_of(book, key)})
            if cell.formula:
                targets = []
                for m in _XSHEET.finditer(cell.formula):
                    t = m.group(0)
                    tsh = t.rsplit("!", 1)[0].strip("'").replace("''", "'")
                    if tsh != sh:
                        targets.append(t.replace("$", ""))
                if targets:
                    links.append({"ref": key, "to": list(dict.fromkeys(targets))[:4], "formula": cell.formula[:120],
                                  "label": wbgraph.label_of(book, key)})
            elif (cls == "input" and sh not in INPUT_SHEETS and sh not in ("Filings",) and c >= 3
                  and row_has_formula.get(r, 0) >= 2 and key not in cites and not book.comments.get(sh, {}).get((r, c))):
                hard.append({"ref": key, "value": _num(cell.value), "label": wbgraph.label_of(book, key)})
        totals["links"] += len(links)
        totals["hardcodes"] += len(hard)
        totals["errors"] += len(errs)
        sheets.append({"sheet": sh, "counts": counts, "n_links": len(links), "links": links[:150], "hardcodes": hard[:150],
                       "n_hardcodes": len(hard), "errors": errs[:150], "n_errors": len(errs),
                       "status": "fail" if errs else ("warn" if hard else "pass")})
    return {"version": v, "sheets": sheets, "totals": totals}


def model_ask(ctx):
    from .. import wbgraph
    from ..xlsx import split_ref
    data, v, _ = _load(ctx, ctx.params["deal_id"], ctx.params["name"], (ctx.json or {}).get("version") if isinstance(ctx.json, dict) else None)
    q = str((ctx.json or {}).get("question") or "").strip() if isinstance(ctx.json, dict) else ""
    if not q:
        raise ApiError(422, "no_question", "Type a question about the model.", "For example: What is FY2026E revenue?")
    if len(q) > 600:
        raise ApiError(422, "question_too_long", "Keep the question under 600 characters.")
    b = _bundle(data)
    res = wbgraph.ask(data, q, _book=b["book"], _graph=b["graph"])
    cells = []
    for ref in res.get("cells", []):
        sh, a1 = ref.rsplit("!", 1)
        c = b["book"].cell(sh, a1)
        cells.append({"ref": ref, "label": wbgraph.label_of(b["book"], ref), "value": _num(c.value) if c else None,
                      "fmt": _fmt_of(b, sh, split_ref(a1))})
    # the answer must reconcile to the workbook: the values quoted come from the same cached cells
    res["cells_detail"] = cells
    res["reconciled"] = all(abs((d["value"] or 0) - (x or 0)) < 1e-9 if isinstance(x, (int, float)) and isinstance(d["value"], (int, float)) else d["value"] == x
                            for d, x in zip(cells, res.get("values", [])))
    res["version"] = v
    return res


# --------------------------------------------------------------------------- citations / documents
def _json_list(txt):
    try:
        v = json.loads(txt) if isinstance(txt, str) and txt else txt
    except (TypeError, ValueError):
        return None
    if isinstance(v, dict):
        v = [v.get(k) for k in ("x0", "y0", "x1", "y1")]
    if isinstance(v, (list, tuple)) and len(v) == 4 and all(isinstance(x, (int, float)) for x in v):
        return [max(0.0, min(1.0, float(x))) for x in v]
    return None


def _cit_row(ctx, token: str):
    try:
        return ctx.conn.execute(
            "SELECT c.token, c.doc_id, c.page, c.bbox_json, c.quote, c.url, c.as_of, c.xbrl_concept, c.cell_locator, c.doc_name, c.kind, "
            "d.deal_id AS deal_id, d.name AS d_name FROM citations c LEFT JOIN documents d ON d.id=c.doc_id AND d.org_id=c.org_id "
            "WHERE c.org_id=? AND c.token=?", (ctx.org_id, token)).fetchone()
    except sqlite3.Error:
        return None


def _context(ctx, doc_id, page, quote: str, width: int = 170) -> tuple[str, str]:
    if not doc_id or not page or not quote:
        return "", ""
    try:
        r = ctx.conn.execute("SELECT text FROM document_pages WHERE org_id=? AND doc_id=? AND page=?", (ctx.org_id, doc_id, page)).fetchone()
    except sqlite3.Error:
        return "", ""
    if r is None or not r["text"]:
        return "", ""
    text = re.sub(r"\s+", " ", r["text"])
    q = re.sub(r"\s+", " ", quote).strip()
    i = text.lower().find(q.lower()) if q else -1
    if i < 0 and len(q) > 40:
        q2 = q[:40]
        i = text.lower().find(q2.lower())
        q = q2 if i >= 0 else q
    if i < 0:
        return "", ""
    before = text[max(0, i - width):i]
    after = text[i + len(q):i + len(q) + width]
    if len(text[:i]) > width and " " in before:
        before = "…" + before.split(" ", 1)[1]
    if len(text[i + len(q):]) > width and " " in after:
        after = after.rsplit(" ", 1)[0] + "…"
    return before.lstrip(), after.rstrip()


def _cit_dict(row) -> dict:
    return {"token": row["token"], "doc_id": row["doc_id"] or None, "deal_id": row["deal_id"], "page": row["page"],
            "bbox_norm": _json_list(row["bbox_json"]), "quote": row["quote"] or "", "url": row["url"], "as_of": row["as_of"],
            "xbrl_concept": row["xbrl_concept"], "cell_locator": row["cell_locator"], "kind": row["kind"],
            "doc_name": row["doc_name"] or row["d_name"] or ""}


def citation_preview(ctx):
    row = _cit_row(ctx, ctx.params["token"])
    if row is None:
        raise _not_found("citation", "The source may have been removed, or it belongs to another organization.")
    d = _cit_dict(row)
    before, after = _context(ctx, d["doc_id"], d["page"], d["quote"])
    d["context_before"], d["context_after"] = before, after
    return d


def _doc_row(ctx, doc_id: str):
    try:
        r = ctx.conn.execute("SELECT * FROM documents WHERE org_id=? AND id=?", (ctx.org_id, doc_id)).fetchone()
    except sqlite3.Error:
        r = None
    if r is None:
        raise _not_found("document", "It may have been deleted, or it belongs to another organization.")
    return r


def _doc_citations(ctx, doc_id: str) -> list[dict]:
    try:
        rows = ctx.conn.execute(
            "SELECT c.token, c.doc_id, c.page, c.bbox_json, c.quote, c.url, c.as_of, c.xbrl_concept, c.cell_locator, c.doc_name, c.kind, "
            "d.deal_id AS deal_id, d.name AS d_name FROM citations c LEFT JOIN documents d ON d.id=c.doc_id AND d.org_id=c.org_id "
            "WHERE c.org_id=? AND c.doc_id=? ORDER BY c.page, c.rowid LIMIT 500", (ctx.org_id, doc_id)).fetchall()
    except sqlite3.Error:
        return []
    return [_cit_dict(r) for r in rows]


def doc_inspect(ctx):
    doc_id = ctx.params["doc_id"]
    d = _doc_row(ctx, doc_id)
    keys = d.keys()
    cites = _doc_citations(ctx, doc_id)
    cur = None
    tok = ctx.query.get("cite")
    if tok:
        cur = next((c for c in cites if c["token"] == tok), None)
        if cur is None:
            row = _cit_row(ctx, tok)
            if row is not None:
                cur = _cit_dict(row)
    if cur is not None:
        cur["context_before"], cur["context_after"] = _context(ctx, doc_id, cur["page"], cur["quote"])
    doc = {"id": d["id"], "name": d["name"], "deal_id": d["deal_id"], "pages": d["pages"], "kind": d["kind"] if "kind" in keys else None,
           "lang": d["lang"] if "lang" in keys else None, "status": d["status"] if "status" in keys else None}
    return {"doc": doc, "citation": cur, "citations": cites, "file_url": f"/api/v1/documents/{doc_id}/file"}


def doc_search(ctx):
    doc_id = ctx.params["doc_id"]
    _doc_row(ctx, doc_id)
    q = (ctx.query.get("q") or "").strip()
    if len(q) < 2:
        return {"q": q, "hits": [], "total": 0}
    try:
        rows = ctx.conn.execute("SELECT page, text FROM document_pages WHERE org_id=? AND doc_id=? ORDER BY page", (ctx.org_id, doc_id)).fetchall()
    except sqlite3.Error:
        rows = []
    hits, total, ql = [], 0, q.lower()
    for r in rows:
        text = re.sub(r"\s+", " ", r["text"] or "")
        low, start, n = text.lower(), 0, 0
        while True:
            i = low.find(ql, start)
            if i < 0:
                break
            n += 1
            if n == 1:
                hits.append({"page": r["page"], "snippet": text[max(0, i - 60):i + len(q) + 80], "at": i - max(0, i - 60)})
            start = i + len(ql)
        total += n
        if len(hits) >= 200:
            break
    return {"q": q, "hits": hits, "total": total}


ROUTES = [
    Route("GET", "/api/v1/citations/{token}/preview", citation_preview, role="viewer"),
    Route("GET", "/api/v1/documents/{doc_id}/inspect", doc_inspect, role="viewer"),
    Route("GET", "/api/v1/documents/{doc_id}/search", doc_search, role="viewer"),
    Route("GET", "/api/v1/models/{deal_id}/{name}", model_get, role="viewer"),
    Route("POST", "/api/v1/models/{deal_id}/{name}/recompute", model_recompute, role="viewer"),
    Route("POST", "/api/v1/models/{deal_id}/{name}/save", model_save, role="member"),
    Route("GET", "/api/v1/models/{deal_id}/{name}/explain", model_explain, role="viewer"),
    Route("GET", "/api/v1/models/{deal_id}/{name}/audit", model_audit, role="viewer"),
    Route("POST", "/api/v1/models/{deal_id}/{name}/ask", model_ask, role="viewer"),
]
