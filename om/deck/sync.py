"""Deck <-> ModelManifest sync (S3.9). Zero LLM, zero network.

A deck's ``/acretia/bindings.json`` maps element id -> binding. ``resync`` rewrites only the bound shapes (chart
caches + embedded workbook, table cells, KPI/value runs) at ZIP level: every other package part is copied through
byte-for-byte, and on a changed slide part only the bound shape's XML differs.

Binding shapes (``om.deck.model.Element.binding``):
  chart : {"manifest_id": id, "kind": "chart", "format"?, "units"?, "series_index"?}   value: list | list[list]
  table : {"kind": "table", "bindings": {"r,c": id}, "format"?: str | {"r,c": str}, "units"?, "header_rows"?: 1}
          "r" counts data rows (the TableSpec ``rows`` index), "c" the column.
  value : {"manifest_id": id, "kind": "value", "format"?, "units"?, "run"?: int}
"""
from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from om.contracts import ModelManifest
from om.deck.render import read_bindings

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": _A, "p": _P, "c": _C, "r": _R}


class SyncError(ValueError):
    pass


def bindings(pptx_bytes: bytes) -> dict:
    return read_bindings(pptx_bytes)


# ---------------------------------------------------------------- formatting

_FMT = re.compile(r"^(?P<pre>[^#0,]*)(?P<num>[#,0]*(?:\.0+)?)(?P<suf>.*)$")


def format_value(v, fmt: str | None) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, str):
        return v
    if not fmt:
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0").rstrip(".")
    m = _FMT.match(fmt)
    if not m or not m.group("num"):
        raise SyncError(f"unsupported number format {fmt!r}")
    pre, num, suf = m.group("pre"), m.group("num"), m.group("suf")
    x = float(v) * (100 if "%" in suf else 1)
    dec = len(num.split(".")[1]) if "." in num else 0
    body = f"{abs(x):{',' if ',' in num else ''}.{dec}f}"
    if float(body.replace(",", "")) == 0:
        return f"{pre}{body}{suf}"
    return f"{'-' if x < 0 else ''}{pre}{body}{suf}"


# ---------------------------------------------------------------- package helpers

def _ser(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _rels_path(part: str) -> str:
    d, _, f = part.rpartition("/")
    return f"{d}/_rels/{f}.rels"


def _resolve(part: str, target: str) -> str:
    parts = part.rpartition("/")[0].split("/")
    for seg in target.split("/"):
        if seg == "..":
            parts.pop()
        elif seg not in ("", "."):
            parts.append(seg)
    return "/".join(parts)


def _rel_target(files: dict, part: str, rid: str) -> str:
    rels = etree.fromstring(files[_rels_path(part)])
    for r in rels.findall(f"{{{_RELS}}}Relationship"):
        if r.get("Id") == rid:
            return _resolve(part, r.get("Target"))
    raise SyncError(f"{part}: relationship {rid} not found")


def _find_shapes(files: dict, parsed: dict) -> dict[str, tuple[str, etree._Element]]:
    out: dict[str, tuple[str, etree._Element]] = {}
    for name in sorted(files):
        if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
            root = parsed.setdefault(name, etree.fromstring(files[name]))
            for c in root.iter(f"{{{_P}}}cNvPr"):
                shape = c.getparent().getparent()
                if etree.QName(shape).localname in ("sp", "graphicFrame", "pic", "cxnSp"):
                    out[c.get("name")] = (name, shape)
    return out


def _as_list(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


# ---------------------------------------------------------------- per-kind updaters

def _runs(shape_or_tc) -> list:
    return list(shape_or_tc.iter(f"{{{_A}}}r"))


def _set_run_text(run, text: str) -> str:
    t = run.find(f"{{{_A}}}t")
    old = t.text or ""
    t.text = text
    return old


def _update_value(el_id, shape, b, val) -> tuple[str, str] | None:
    runs = _runs(shape)
    if not runs:
        raise SyncError(f"element {el_id!r} (manifest id {b.get('manifest_id')!r}): no text run to update")
    idx = b.get("run")
    if idx is None:
        idx = next((i for i, r in enumerate(runs) if re.search(r"\d", r.findtext(f"{{{_A}}}t") or "")), 0)
    new = format_value(val, b.get("format"))
    run = runs[idx]
    if (run.findtext(f"{{{_A}}}t") or "") == new:
        return None
    return _set_run_text(run, new), new


def _update_cell(el_id, shape, rc: str, mid: str, fmt, val, header_rows: int):
    try:
        r, c = (int(x) for x in rc.split(","))
    except ValueError:
        raise SyncError(f"element {el_id!r}: bad table binding key {rc!r} (manifest id {mid!r})") from None
    rows = shape.findall(f".//{{{_A}}}tr")
    try:
        tc = rows[r + header_rows].findall(f"{{{_A}}}tc")[c]
    except IndexError:
        raise SyncError(f"element {el_id!r}: table has no cell {rc!r} (manifest id {mid!r})") from None
    para = tc.find(f".//{{{_A}}}p")
    runs = para.findall(f"{{{_A}}}r") if para is not None else []
    if not runs:
        raise SyncError(f"element {el_id!r}: cell {rc!r} has no run (manifest id {mid!r})")
    new = format_value(val, fmt)
    old = "".join(r.findtext(f"{{{_A}}}t") or "" for r in runs)
    if old == new:
        return None
    _set_run_text(runs[0], new)
    for extra in runs[1:]:
        para.remove(extra)
    return old, new


def _chart_part(files, slide_part, shape, el_id) -> str:
    ch = shape.find(f".//{{{_C}}}chart")
    if ch is None:
        raise SyncError(f"element {el_id!r}: bound as chart but is not a chart")
    return _rel_target(files, slide_part, ch.get(f"{{{_R}}}id"))


def _num_vals(ser) -> list:
    out = {}
    for pt in ser.findall(f"c:val/c:numRef/c:numCache/c:pt", NS):
        out[int(pt.get("idx"))] = float(pt.findtext("c:v", namespaces=NS))
    n = int(ser.find("c:val/c:numRef/c:numCache/c:ptCount", NS).get("val"))
    return [out.get(i) for i in range(n)]


def _write_cache(ser, values: list) -> None:
    cache = ser.find("c:val/c:numRef/c:numCache", NS)
    for pt in cache.findall(f"{{{_C}}}pt"):
        cache.remove(pt)
    cache.find(f"{{{_C}}}ptCount").set("val", str(len(values)))
    for i, v in enumerate(values):
        if v is None:
            continue
        pt = etree.SubElement(cache, f"{{{_C}}}pt")
        pt.set("idx", str(i))
        etree.SubElement(pt, f"{{{_C}}}v").text = repr(float(v))


def _update_workbook(blob: bytes, ser, values: list) -> bytes:
    import openpyxl
    f = ser.findtext("c:val/c:numRef/c:f", namespaces=NS) or ""
    m = re.fullmatch(r"'?([^'!]+)'?!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", f)
    if not m:
        raise SyncError(f"chart series formula {f!r} is not a simple range")
    sheet, col, r0 = m.group(1), m.group(2), int(m.group(3))
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb[sheet]
    for i, v in enumerate(values):
        ws[f"{col}{r0 + i}"] = None if v is None else float(v)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _update_chart(files, parsed, changed_blobs, slide_part, shape, el_id, b, val):
    cpart = _chart_part(files, slide_part, shape, el_id)
    root = parsed.setdefault(cpart, etree.fromstring(files[cpart]))
    sers = root.findall(".//c:ser", NS)
    nested = bool(val) and isinstance(val[0], (list, tuple))
    lists = [list(x) for x in val] if nested else [list(_as_list(val))]
    start = int(b.get("series_index", 0))
    if start + len(lists) > len(sers):
        raise SyncError(f"element {el_id!r} (manifest id {b.get('manifest_id')!r}): "
                        f"{len(lists)} series supplied from index {start}, chart has {len(sers)}")
    olds, news = [], []
    for k, new in enumerate(lists):
        ser = sers[start + k]
        old = _num_vals(ser)
        if len(new) != len(old):
            raise SyncError(f"element {el_id!r} (manifest id {b.get('manifest_id')!r}): "
                            f"{len(new)} points supplied, chart series has {len(old)}")
        new = [None if x is None else float(x) for x in new]
        if new == old:
            continue
        _write_cache(ser, new)
        olds.append(old)
        news.append(new)
        # embedded workbook
        try:
            crel = _rels_path(cpart)
            rels = etree.fromstring(files[crel])
            tgt = next((_resolve(cpart, r.get("Target")) for r in rels.findall(f"{{{_RELS}}}Relationship")
                        if r.get("Type", "").endswith("/package")), None)
        except KeyError:
            tgt = None
        if tgt and tgt in files:
            changed_blobs[tgt] = _update_workbook(changed_blobs.get(tgt, files[tgt]), ser, new)
    if not news:
        return None
    return (olds[0], news[0]) if len(news) == 1 else (olds, news)


# ---------------------------------------------------------------- resync

def resync(pptx_bytes: bytes, manifest: ModelManifest, values: dict) -> tuple[bytes, dict]:
    outs = {o.id: o for o in manifest.outputs}
    binds = read_bindings(pptx_bytes)
    zin = zipfile.ZipFile(io.BytesIO(pptx_bytes))
    files = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    parsed: dict[str, etree._Element] = {}
    blobs: dict[str, bytes] = {}
    shapes = _find_shapes(files, parsed)
    report = {"changed": [], "missing": [], "unchanged": []}

    def check(el_id: str, mid: str, b: dict) -> None:
        if mid not in outs:
            raise SyncError(f"element {el_id!r}: manifest id {mid!r} is not in the manifest")
        bu = b.get("units")
        if bu is not None and bu != outs[mid].units:
            raise SyncError(f"element {el_id!r}: units mismatch for {mid!r}: binding {bu!r} vs manifest {outs[mid].units!r}")

    def supplied(mid: str):
        return mid in values and values[mid] is not None

    for el_id in sorted(binds):
        b = binds[el_id]
        kind = b.get("kind", "value")
        if el_id not in shapes:
            raise SyncError(f"element {el_id!r} (manifest id {b.get('manifest_id')!r}): shape not found in deck")
        part, shape = shapes[el_id]
        if kind == "table":
            cells = b.get("bindings") or {}
            hr = int(b.get("header_rows", 1))
            for rc in sorted(cells, key=lambda k: tuple(int(x) for x in k.split(","))):
                mid = cells[rc]
                check(el_id, mid, b)
                if not supplied(mid):
                    report["missing"].append({"element": el_id, "manifest_id": mid, "cell": rc})
                    continue
                fmt = b.get("format")
                fmt = fmt.get(rc) if isinstance(fmt, dict) else fmt
                res = _update_cell(el_id, shape, rc, mid, fmt, values[mid], hr)
                (report["changed"] if res else report["unchanged"]).append(
                    {"element": el_id, "manifest_id": mid, "cell": rc, **({"old": res[0], "new": res[1]} if res else {})})
            continue
        mid = b.get("manifest_id")
        if not mid:
            raise SyncError(f"element {el_id!r}: binding has no manifest_id")
        check(el_id, mid, b)
        if not supplied(mid):
            report["missing"].append({"element": el_id, "manifest_id": mid})
            continue
        if kind == "chart":
            res = _update_chart(files, parsed, blobs, part, shape, el_id, b, values[mid])
        elif kind == "value":
            res = _update_value(el_id, shape, b, values[mid])
        else:
            raise SyncError(f"element {el_id!r}: unknown binding kind {kind!r}")
        (report["changed"] if res else report["unchanged"]).append(
            {"element": el_id, "manifest_id": mid, **({"old": res[0], "new": res[1]} if res else {})})

    if not report["changed"]:
        return pptx_bytes, report
    # only parts that actually changed are re-serialised; everything else is copied verbatim
    new_parts = {n: blobs[n] for n in blobs}
    for name, root in parsed.items():
        if name.startswith("ppt/slides/") or name.startswith("ppt/charts/"):
            if name in _dirty_parts(report, shapes, files, parsed, binds):
                new_parts[name] = _ser(root)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, new_parts.get(info.filename, files[info.filename]))
    return out.getvalue(), report


def _dirty_parts(report, shapes, files, parsed, binds) -> set[str]:
    dirty: set[str] = set()
    for ch in report["changed"]:
        el_id = ch["element"]
        part, shape = shapes[el_id]
        dirty.add(part)
        if binds[el_id].get("kind") == "chart":
            dirty.add(_chart_part(files, part, shape, el_id))
    return dirty
