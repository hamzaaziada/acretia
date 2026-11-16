"""Targeted workbook edits that leave everything else byte-identical (S4.4).

``edit(data, {"Sheet!C5": 0.07, "Sheet!D5": "=C5*2"})`` changes the named cells and, with ``recalc=True``, refreshes the cached
``<v>`` of every cell that depends on them (across sheets) using om.formula.  The file is spliced as raw text, never
re-serialised: parts that are not affected keep the same decompressed bytes in the same order; inside an affected sheet only
the target ``<c>`` elements and the ``<v>`` of dependents whose value changed are rewritten.  Edits inside merged ranges or
array formulas are refused.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape, unescape

from . import formula as fx
from .xlsx import col_letter, read, ref, shift, split_ref

_WB = "xl/workbook.xml"
_RELS = "xl/_rels/workbook.xml.rels"
_CT = "[Content_Types].xml"
_CHAIN = "xl/calcChain.xml"
_UNESC = {"&quot;": '"', "&apos;": "'"}
_CHANGED_TOL = 1e-12


class EditRefused(ValueError):
    """The edit would touch a merged range or an array formula (or is otherwise unsafe)."""


# --------------------------------------------------------------------------- helpers
def _parse_target(key: str) -> tuple[str, int, int]:
    if "!" not in key:
        raise ValueError(f"cell must be 'Sheet!A1', got {key!r}")
    sh, a1 = key.rsplit("!", 1)
    if sh.startswith("'") and sh.endswith("'"):
        sh = sh[1:-1].replace("''", "'")
    r, c = split_ref(a1)
    return sh, r, c


def _in_range(rng: str, r: int, c: int) -> bool:
    try:
        a, _, b = rng.partition(":")
        r1, c1 = split_ref(a)
        r2, c2 = split_ref(b or a)
    except ValueError:
        return False
    return min(r1, r2) <= r <= max(r1, r2) and min(c1, c2) <= c <= max(c1, c2)


def _sheet_parts(files: dict) -> dict:
    wb = files[_WB].decode("utf-8")
    rels = {}
    if _RELS in files:
        for m in re.finditer(r"<Relationship\b[^>]*>", files[_RELS].decode("utf-8")):
            tag = m.group(0)
            i, t = re.search(r'\bId="([^"]*)"', tag), re.search(r'\bTarget="([^"]*)"', tag)
            if i and t:
                tgt = t.group(1)
                rels[i.group(1)] = tgt.lstrip("/") if tgt.startswith("/") else "xl/" + tgt
    out = {}
    for i, m in enumerate(re.finditer(r"<sheet\b[^>]*>", wb), 1):
        tag = m.group(0)
        name = unescape(re.search(r'\bname="([^"]*)"', tag).group(1), _UNESC)
        rid = re.search(r'\br:id="([^"]*)"', tag)
        part = rels.get(rid.group(1)) if rid else None
        out[name] = part or f"xl/worksheets/sheet{i}.xml"
    return out


def _cell_re(a1: str) -> re.Pattern:
    return re.compile(r'<c\b[^>]*?\br="' + a1 + r'"[^>]*?(?:/>|>.*?</c>)', re.S)


def _fmt_num(v) -> str:
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    return repr(float(v))


def _cached_xml(v) -> tuple[str | None, str]:
    """(t attribute or None, <v> inner text) for a calculated value."""
    if isinstance(v, bool):
        return "b", str(int(v))
    if isinstance(v, (int, float)):
        return None, _fmt_num(v)
    if isinstance(v, fx.Err):
        return "e", escape(v.code)
    return "str", escape("" if v is None else str(v))


def _attrs(open_tag: str) -> list:
    return re.findall(r'([\w:.-]+)="([^"]*)"', open_tag)


def _open_tag(a1: str, old_open: str | None, t: str | None) -> str:
    """Opening <c ...> tag keeping every attribute of the old cell (style etc.) except t."""
    attrs = [(k, v) for k, v in (_attrs(old_open) if old_open else []) if k not in ("r", "t")]
    parts = [f'r="{a1}"'] + [f'{k}="{v}"' for k, v in attrs if k == "s"]
    parts += [f'{k}="{v}"' for k, v in attrs if k != "s"]
    if t:
        parts.append(f't="{t}"')
    return "<c " + " ".join(parts) + ">"


def _new_cell(a1: str, old_open: str | None, value, cached) -> str:
    """Serialise the replacement <c>. ``cached`` is the calculated result for a formula (or None)."""
    if isinstance(value, str) and value.startswith("="):
        t, vtxt = _cached_xml(cached) if cached is not None else (None, "")
        body = f"<f>{escape(value[1:])}</f>" + (f"<v>{vtxt}</v>" if cached is not None else "")
        return _open_tag(a1, old_open, t) + body + "</c>"
    if isinstance(value, bool):
        return _open_tag(a1, old_open, "b") + f"<v>{int(value)}</v></c>"
    if isinstance(value, (int, float)):
        return _open_tag(a1, old_open, None) + f"<v>{_fmt_num(value)}</v></c>"
    if value is None or value == "":
        o = _open_tag(a1, old_open, None)
        return o[:-1] + "/>"
    return _open_tag(a1, old_open, "inlineStr") + f'<is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def _split_cell(xml: str) -> tuple[str, str | None, str]:
    """(opening tag, body or None for a self-closed cell, original xml)."""
    m = re.match(r"<c\b[^>]*?(/?)>", xml, re.S)
    open_tag = m.group(0)
    if m.group(1):
        return open_tag, None, xml
    return open_tag, xml[m.end():-len("</c>")], xml


def _f_info(body: str | None) -> dict | None:
    if not body:
        return None
    m = re.search(r"<f\b([^>]*?)(?:/>|>(.*?)</f>)", body, re.S)
    if not m:
        return None
    at = dict(_attrs("<f " + m.group(1) + ">"))
    return {"attrs": at, "text": unescape(m.group(2), _UNESC) if m.group(2) is not None else None, "xml": m.group(0)}


def _insert_cell(sheet_xml: str, r: int, c: int, cell_xml: str) -> str:
    row_m = re.search(r'<row\b[^>]*?\br="' + str(r) + r'"[^>]*?(?:/>|>.*?</row>)', sheet_xml, re.S)
    if row_m:
        row = row_m.group(0)
        if row.endswith("/>") and not row.endswith("</row>"):
            new = row[:-2] + ">" + cell_xml + "</row>"
        else:
            inner_start = re.match(r"<row\b[^>]*>", row).end()
            inner = row[inner_start:-len("</row>")]
            pos = len(inner)
            for m in re.finditer(r'<c\b[^>]*?\br="([A-Z]+)\d+"', inner):
                if split_ref(m.group(1) + "1")[1] > c:
                    pos = m.start()
                    break
            new = row[:inner_start] + inner[:pos] + cell_xml + inner[pos:] + "</row>"
        return sheet_xml[:row_m.start()] + new + sheet_xml[row_m.end():]
    new_row = f'<row r="{r}">{cell_xml}</row>'
    pos = None
    for m in re.finditer(r'<row\b[^>]*?\br="(\d+)"', sheet_xml):
        if int(m.group(1)) > r:
            pos = m.start()
            break
    if pos is None:
        if "<sheetData/>" in sheet_xml:
            return sheet_xml.replace("<sheetData/>", f"<sheetData>{new_row}</sheetData>", 1)
        pos = sheet_xml.index("</sheetData>")
    return sheet_xml[:pos] + new_row + sheet_xml[pos:]


def _guards(sheet_xml: str, r: int, c: int, a1: str, sheet: str) -> None:
    for m in re.finditer(r'<mergeCell\b[^>]*\bref="([^"]+)"', sheet_xml):
        if _in_range(m.group(1), r, c):
            raise EditRefused(f"{sheet}!{a1} is inside merged range {m.group(1)}")
    for m in re.finditer(r"<f\b([^>]*?)(?:/>|>)", sheet_xml):
        at = dict(_attrs("<f " + m.group(1) + ">"))
        if at.get("t") == "array" and at.get("ref") and _in_range(at["ref"], r, c):
            raise EditRefused(f"{sheet}!{a1} is part of an array formula {at['ref']}")


def _unshare_group(sheet_xml: str, si: str, skip_a1: str) -> tuple[str, list]:
    """Expand a shared-formula group into explicit per-cell formulas (needed when its master cell is overwritten)."""
    master = None
    members = []
    for m in re.finditer(r'<c\b[^>]*?\br="([A-Z]+\d+)"[^>]*?(?:/>|>.*?</c>)', sheet_xml, re.S):
        fi = _f_info(_split_cell(m.group(0))[1])
        if fi and fi["attrs"].get("t") == "shared" and fi["attrs"].get("si") == si:
            members.append((m, fi))
            if fi["text"]:
                master = (m.group(1), fi["text"])
    if not master:
        return sheet_xml, []
    r0, c0 = split_ref(master[0])
    out, done = sheet_xml, []
    for m, fi in reversed(members):
        a1 = re.search(r'\br="([A-Z]+\d+)"', m.group(0)).group(1)
        if a1 == skip_a1:
            continue
        r, c = split_ref(a1)
        text = master[1] if (r, c) == (r0, c0) else shift("=" + master[1], r - r0, c - c0)[1:]
        new_xml = m.group(0).replace(fi["xml"], f"<f>{escape(text)}</f>", 1)
        out = out[:m.start()] + new_xml + out[m.end():]
        done.append(a1)
    return out, sorted(done)


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= _CHANGED_TOL * max(1.0, abs(a), abs(b))
    return a == b


def _set_cached(cell_xml: str, value) -> str:
    """Replace only the cached <v> (and the t attribute if the result's type changed) of a formula cell."""
    open_tag, body, _ = _split_cell(cell_xml)
    t, vtxt = _cached_xml(value)
    old_t = dict(_attrs(open_tag)).get("t")
    if (old_t or "n") == (t or "n"):
        new_open = open_tag
    else:
        new_open = re.sub(r'\s+t="[^"]*"', "", open_tag, count=1)
        if t:
            new_open = new_open[:-1] + f' t="{t}">'
    body = body or ""
    if re.search(r"<v\b[^>]*?(?:/>|>.*?</v>)", body, re.S):
        body = re.sub(r"<v\b[^>]*?(?:/>|>.*?</v>)", lambda _m: f"<v>{vtxt}</v>", body, count=1, flags=re.S)
    else:
        fm = re.search(r"<f\b[^>]*?(?:/>|>.*?</f>)", body, re.S)
        at = fm.end() if fm else len(body)
        body = body[:at] + f"<v>{vtxt}</v>" + body[at:]
    return new_open + body + "</c>"


# --------------------------------------------------------------------------- edit
def edit(data: bytes, changes: dict, *, recalc: bool = True) -> tuple[bytes, dict]:
    """Apply ``changes`` ({"Sheet!C5": number | text | "=formula"}); return (new bytes, report)."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    infos = zin.infolist()
    files = {i.filename: zin.read(i.filename) for i in infos}
    parts = _sheet_parts(files)
    book = read(data)

    targets = {}
    for key, val in changes.items():
        sh, r, c = _parse_target(key)
        if sh not in parts:
            raise KeyError(f"no sheet {sh!r} in the workbook")
        if isinstance(val, str) and val.startswith("="):
            try:
                fx.parse(val, sh)
            except fx.XLError as e:
                raise ValueError(f"{key}: not a valid formula ({e})") from e
        elif not (val is None or isinstance(val, (str, int, float, bool))):
            raise TypeError(f"{key}: unsupported value {val!r}")
        targets[(sh, r, c)] = val

    # ------------------------------------------------ recalculation (before any splicing, so errors leave nothing half-done)
    new_values: dict = {}
    dependents_changed: dict = {}
    old_cells = {}
    if recalc:
        base = {}
        for name, grid in book.sheets.items():
            for (r, c), cell in grid.items():
                base[(name, r, c)] = cell.formula if cell.formula else cell.value
        old_cells = dict(base)
        eng_old = fx.Engine(base, {k: v for k, v in book.names.items() if v})
        eng_old.calculate(iterate=book.iterate)
        merged = dict(base)
        for k, v in targets.items():
            if v is None or v == "":
                merged.pop(k, None)
            else:
                merged[k] = v
        eng_new = fx.Engine(merged, {k: v for k, v in book.names.items() if v})
        eng_new.calculate(iterate=book.iterate)
        # closure of cells downstream of the edits
        rev: dict = {}
        for k, a in eng_new.ast.items():
            for d in fx.deps(a, eng_new.names, set()):
                rev.setdefault(d, set()).add(k)
        closure, stack = set(), list(targets)
        while stack:
            k = stack.pop()
            for n in rev.get(k, ()):
                if n not in closure:
                    closure.add(n)
                    stack.append(n)
        for k in closure | {k for k in targets if isinstance(targets[k], str) and targets[k].startswith("=")}:
            if k in eng_new.ast:
                nv, ov = eng_new.values.get(k), eng_old.values.get(k)
                if k in targets or not _same(nv, ov):
                    new_values[k] = nv
        dependents_changed = {k: (eng_old.values.get(k), v) for k, v in new_values.items() if k not in targets}

    # ------------------------------------------------ splice sheet XML
    by_sheet: dict = {}
    for (sh, r, c), v in targets.items():
        by_sheet.setdefault(sh, {})[(r, c)] = v
    dep_by_sheet: dict = {}
    for (sh, r, c) in dependents_changed:
        dep_by_sheet.setdefault(sh, []).append((r, c))
    touched, unshared, report_changes = [], [], []
    for sh in dict.fromkeys(list(by_sheet) + list(dep_by_sheet)):
        part = parts[sh]
        xml = files[part].decode("utf-8")
        orig = xml
        for (r, c), val in sorted(by_sheet.get(sh, {}).items()):
            a1 = ref(r, c)
            _guards(xml, r, c, a1, sh)
            m = _cell_re(a1).search(xml)
            old_open, old_f = None, None
            if m:
                old_open, body, _ = _split_cell(m.group(0))
                old_f = _f_info(body)
                if old_f and old_f["attrs"].get("t") == "shared" and old_f["text"]:
                    xml, done = _unshare_group(xml, old_f["attrs"].get("si"), a1)
                    unshared += [f"{sh}!{x}" for x in done] + [f"{sh}!{a1}"]
                    m = _cell_re(a1).search(xml)
                elif old_f and old_f["attrs"].get("t") == "shared":
                    unshared.append(f"{sh}!{a1}")
            cached = new_values.get((sh, r, c)) if recalc else None
            cell_xml = _new_cell(a1, old_open, val, cached)
            xml = xml[:m.start()] + cell_xml + xml[m.end():] if m else _insert_cell(xml, r, c, cell_xml)
            old = book.cell(sh, a1)
            report_changes.append({"cell": f"{sh}!{a1}", "old": (old.formula or old.value) if old else None, "new": val,
                                   "old_value": old.value if old else None,
                                   "new_value": new_values.get((sh, r, c), val) if recalc else None})
        for (r, c) in sorted(dep_by_sheet.get(sh, [])):
            a1 = ref(r, c)
            m = _cell_re(a1).search(xml)
            if m:
                xml = xml[:m.start()] + _set_cached(m.group(0), new_values[(sh, r, c)]) + xml[m.end():]
        if xml != orig:
            files[part] = xml.encode("utf-8")
            touched.append(part)

    # ------------------------------------------------ calcChain
    chain = _CHAIN in files
    if chain:
        del files[_CHAIN]
        ct = files[_CT].decode("utf-8")
        ct2 = re.sub(r'<Override\b[^>]*\bPartName="/xl/calcChain\.xml"[^>]*/>', "", ct)
        if ct2 != ct:
            files[_CT] = ct2.encode("utf-8")
            touched.append(_CT)
        rl = files[_RELS].decode("utf-8")
        rl2 = re.sub(r'<Relationship\b[^>]*(?:/calcChain"|Target="calcChain\.xml")[^>]*/>', "", rl)
        if rl2 != rl:
            files[_RELS] = rl2.encode("utf-8")
            touched.append(_RELS)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            if info.filename not in files:
                continue
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, files[info.filename])

    report = {
        "changed": report_changes,
        "dependents_updated": [{"cell": f"{sh}!{ref(r, c)}", "old": ov, "new": nv} for (sh, r, c), (ov, nv) in sorted(dependents_changed.items())],
        "parts_touched": sorted(set(touched)),
        "calc_chain_removed": chain,
        "unshared": sorted(set(unshared)),
        "recalc": recalc,
    }
    return out.getvalue(), report
