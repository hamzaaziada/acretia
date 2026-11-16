"""Deck viewer API (SPEC §4 decks; PLAN P-J4, S7.3; parity items 34-41).

A deck is a `pptx` deliverable of a deal (om.deals.DealStore history = versions). This module reads the package at zip level:
slide titles and source lines come from the shapes the engine names `sN.<role>`, validator badges from `om.deck.validate`,
PNG previews from LibreOffice + pdftoppm (cached by sha256; 503 with a hint when they are missing).

Revision rounds edit IN PLACE: only the commented slides' parts (slide xml, or the chart part for a chart-type switch) are
rewritten; every other zip entry is copied byte for byte, so untouched slides stay byte-identical (parity items 35, 38). A comment
the deterministic patch path cannot read is handed to the job runner as a `deck_edit` job when `om.api.jobs` exists.

Tables owned: deck_comments, deck_accepts.
"""
from __future__ import annotations

import difflib
import hashlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath

from om.api import db as _db
from om.api.http import ApiError, Response, Route
from om.deals import DealError, DealStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS deck_comments(
  id TEXT PRIMARY KEY, org_id TEXT NOT NULL, deal_id TEXT NOT NULL, deck_name TEXT NOT NULL, version INTEGER NOT NULL,
  slide INTEGER NOT NULL, x REAL NOT NULL, y REAL NOT NULL, body TEXT NOT NULL, author_id TEXT, status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL, applied_in_version INTEGER, job_id TEXT);
CREATE INDEX IF NOT EXISTS deck_comments_deck ON deck_comments(org_id, deal_id, deck_name, version);
CREATE TABLE IF NOT EXISTS deck_accepts(
  org_id TEXT NOT NULL, deal_id TEXT NOT NULL, deck_name TEXT NOT NULL, slide_key TEXT NOT NULL, accepted_by TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY(org_id, deal_id, deck_name, slide_key));
"""

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main", "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
REL_CHART = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"
ROLE_TITLE = re.compile(r"\.(title|cover|divider|headline)$")
ROLE_SOURCE = re.compile(r"\.(source|sources)$")
ROLE_PAGE = re.compile(r"\.page_number$")
_RENDER_LOCKS: dict = {}
_RENDER_LOCKS_G = threading.Lock()
_VALIDATE_CACHE: dict = {}
MAX_COMMENT = 2000


# --------------------------------------------------------------------------- helpers
def _nf() -> ApiError:
    return ApiError(404, "not_found", "No such resource.")


def _bad(msg: str, hint: str, code: str = "bad_request", status: int = 400) -> ApiError:
    return ApiError(status, code, msg, hint)


def _body(ctx) -> dict:
    return ctx.json if isinstance(ctx.json, dict) else {}


def _lxml():
    try:
        from lxml import etree
        return etree
    except ImportError:
        raise ApiError(503, "deck_deps_missing", "The deck reader needs lxml.", "Install the deck dependencies: pip install python-pptx lxml.") from None


def _store(ctx) -> DealStore:
    return DealStore(ctx.conn, ctx.blobs, ctx.org_id)


def _deck(ctx, version=None):
    """(store, deal_id, name, history, version, bytes) with tenant-scoped 404s."""
    deal_id, name = ctx.params["deal_id"], ctx.params["name"]
    store = _store(ctx)
    try:
        hist = store.history(deal_id, name)
    except DealError:
        raise _nf() from None
    hist = [h for h in hist if h["kind"] == "pptx"]
    if not hist:
        raise _nf()
    if version is None:
        version = hist[-1]["version"]
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise _bad("The version must be a whole number.", "Pick a version from the list.") from None
    if not any(h["version"] == version for h in hist):
        raise _nf()
    return store, deal_id, name, hist, version, store.get_version(deal_id, name, version)


# --------------------------------------------------------------------------- package reading
def read_zip(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: (i, z.read(i.filename)) for i in z.infolist()}


def _resolve(base: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return str(PurePosixPath(os.path.normpath(str(PurePosixPath(base).parent / target))))


def _rels_of(parts: dict, part: str) -> list[dict]:
    rp = str(PurePosixPath(part).parent / "_rels" / (PurePosixPath(part).name + ".rels"))
    if rp not in parts:
        return []
    etree = _lxml()
    root = etree.fromstring(parts[rp][1])
    return [{"id": r.get("Id"), "type": r.get("Type"), "target": _resolve(part, r.get("Target")), "mode": r.get("TargetMode")}
            for r in root.findall(f"{{{REL_NS}}}Relationship")]


def slide_parts(parts: dict) -> list[str]:
    """Slide part names in presentation order."""
    etree = _lxml()
    pres = etree.fromstring(parts["ppt/presentation.xml"][1])
    rid_to = {r["id"]: r["target"] for r in _rels_of(parts, "ppt/presentation.xml")}
    out = []
    for sid in pres.findall(".//p:sldIdLst/p:sldId", NS):
        rid = sid.get(f"{{{NS['r']}}}id")
        if rid in rid_to:
            out.append(rid_to[rid])
    return out


def _shape_texts(root) -> list[dict]:
    out = []
    for sp in root.iter(f"{{{NS['p']}}}sp"):
        nv = sp.find("p:nvSpPr/p:cNvPr", NS)
        paras = []
        for p in sp.findall(".//a:p", NS):
            t = "".join(x.text or "" for x in p.findall(".//a:t", NS)).strip()
            if t:
                paras.append(t)
        out.append({"name": (nv.get("name") if nv is not None else "") or "", "paras": paras, "el": sp})
    return out


def slide_fingerprint(parts: dict, part: str) -> str:
    """sha256 over the slide xml, its rels and the chart/media parts it owns: what 'this slide is unchanged' means."""
    h = hashlib.sha256()
    h.update(parts[part][1])
    rp = str(PurePosixPath(part).parent / "_rels" / (PurePosixPath(part).name + ".rels"))
    if rp in parts:
        h.update(parts[rp][1])
    for r in _rels_of(parts, part):
        if r["mode"] == "External" or "slideLayout" in r["type"] or "notesSlide" in r["type"]:
            continue
        for t in (r["target"], str(PurePosixPath(r["target"]).parent / "_rels" / (PurePosixPath(r["target"]).name + ".rels"))):
            if t in parts:
                h.update(parts[t][1])
    return h.hexdigest()


def read_slides(data: bytes) -> list[dict]:
    etree = _lxml()
    parts = read_zip(data)
    out = []
    for n, part in enumerate(slide_parts(parts), 1):
        root = etree.fromstring(parts[part][1])
        shapes = _shape_texts(root)
        title = next((s["paras"][0] for s in shapes if ROLE_TITLE.search(s["name"]) and s["paras"]), "")
        if not title:
            title = next((s["paras"][0] for s in shapes if s["paras"] and not ROLE_PAGE.search(s["name"])), "")
        sources = [" ".join(s["paras"]) for s in shapes if ROLE_SOURCE.search(s["name"]) and s["paras"]]
        outline = [p for s in shapes if not re.search(r"\.(footer|page_number)$", s["name"]) for p in s["paras"]]
        out.append({"n": n, "part": part, "title": title, "sources": sources, "outline": outline[:14],
                    "texts": [p for s in shapes for p in s["paras"]], "key": slide_fingerprint(parts, part)})
    return out


def patch_zip(data: bytes, replacements: dict) -> bytes:
    """Rewrite a pptx: parts in `replacements` change, every other entry is copied byte for byte (same order, same metadata)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            blob = replacements.get(info.filename, None)
            if blob is None:
                blob = zin.read(info.filename)
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type, zi.external_attr, zi.create_system = info.compress_type, info.external_attr, info.create_system
            zout.writestr(zi, blob)
    return buf.getvalue()


def _xml_bytes(root) -> bytes:
    return _lxml().tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


# --------------------------------------------------------------------------- deterministic edits
_TITLE_RES = [
    re.compile(r"^\s*(?:new\s+)?(?:slide\s+)?(?:title|retitle|headline)\s*[:=]\s*[\"“']?(?P<t>.+?)[\"”']?\s*$", re.I | re.S),
    re.compile(r"\b(?:change|set|make|rename|retitle|replace|update)\b[^\"“']{0,30}\b(?:title|headline)\b[^\"“']{0,12}\b(?:to|as|with)\b\s*[:\-]?\s*[\"“']?(?P<t>[^\"”']{3,}?)[\"”']?\s*\.?\s*$", re.I | re.S),
]
_REPLACE_RE = re.compile(r"\b(?:replace|change|correct|fix)\s+[\"“'](?P<a>[^\"”']+)[\"”']\s+(?:with|to|by|->)\s+[\"“'](?P<b>[^\"”']+)[\"”']", re.I)
_CHART_RE = re.compile(r"\b(?:change|switch|make|convert|turn|use|show)\b.{0,50}?\b(line|bar|column)\b(?:\s*(?:chart|graph))?", re.I | re.S)


def parse_comment(body: str) -> list[dict]:
    """Comment text -> deterministic ops: title edit, literal text replace, chart-type switch. [] when it needs a model."""
    ops = []
    m = _REPLACE_RE.search(body)
    if m:
        ops.append({"op": "replace", "a": m.group("a"), "b": m.group("b")})
    for rx in _TITLE_RES:
        m = rx.search(body)
        if m and not ops:
            t = m.group("t").strip().strip("\"“”'")
            if t:
                ops.append({"op": "title", "text": t})
                break
    m = _CHART_RE.search(body)
    if m and re.search(r"chart|graph|line|bar|column", body, re.I) and not ops:
        ops.append({"op": "chart", "kind": m.group(1).lower()})
    return ops


def _set_title(root, text: str) -> bool:
    for s in _shape_texts(root):
        if ROLE_TITLE.search(s["name"]) and s["paras"]:
            sp = s["el"]
            paras = sp.findall(".//a:p", NS)
            first = next((p for p in paras if p.findall(".//a:t", NS)), None)
            if first is None:
                return False
            runs = first.findall("a:r", NS)
            runs[0].find("a:t", NS).text = text
            for r in runs[1:]:
                first.remove(r)
            for p in paras:
                if p is not first and "".join(x.text or "" for x in p.findall(".//a:t", NS)).strip():
                    p.getparent().remove(p)
            return True
    return False


def _replace_text(root, a: str, b: str) -> int:
    n = 0
    for t in root.iter(f"{{{NS['a']}}}t"):
        if t.text and a in t.text:
            t.text = t.text.replace(a, b)
            n += 1
    return n


def _convert_chart(xml: bytes, kind: str) -> bytes | None:
    """Switch a bar/column/line chart part to another of those kinds; None when nothing to do or not switchable."""
    etree = _lxml()
    root = etree.fromstring(xml)
    C = NS["c"]
    q = lambda t: f"{{{C}}}{t}"  # noqa: E731
    plot = root.find(".//c:plotArea", NS)
    if plot is None:
        return None
    bar, line = plot.find("c:barChart", NS), plot.find("c:lineChart", NS)
    cur = None
    if bar is not None:
        cur = "bar" if (bar.find("c:barDir", NS) is not None and bar.find("c:barDir", NS).get("val") == "bar") else "column"
    elif line is not None:
        cur = "line"
    if cur is None or cur == kind:
        return None

    def axes(cat_pos, val_pos):
        for tag, pos in (("catAx", cat_pos), ("valAx", val_pos)):
            ax = plot.find(f"c:{tag}", NS)
            if ax is not None and ax.find("c:axPos", NS) is not None:
                ax.find("c:axPos", NS).set("val", pos)

    if kind in ("bar", "column") and bar is not None:
        bar.find("c:barDir", NS).set("val", "bar" if kind == "bar" else "col")
        axes("l" if kind == "bar" else "b", "b" if kind == "bar" else "l")
        return _xml_bytes(root)
    if kind in ("bar", "column") and line is not None:
        new = etree.Element(q("barChart"))
        etree.SubElement(new, q("barDir")).set("val", "bar" if kind == "bar" else "col")
        etree.SubElement(new, q("grouping")).set("val", "clustered")
        for ser in line.findall("c:ser", NS):
            for t in ("marker", "smooth"):
                for el in ser.findall(f"c:{t}", NS):
                    ser.remove(el)
            sp = ser.find("c:spPr", NS)
            if sp is not None:
                ln = sp.find("a:ln", NS)
                fill = ln.find("a:solidFill", NS) if ln is not None else None
                if fill is not None and sp.find("a:solidFill", NS) is None:
                    sp.insert(0, fill)
                if ln is not None:
                    sp.remove(ln)
                    etree.SubElement(sp, f"{{{NS['a']}}}ln").append(etree.Element(f"{{{NS['a']}}}noFill"))
            inv = etree.Element(q("invertIfNegative"))
            inv.set("val", "0")
            anchor = sp if sp is not None else ser.find("c:tx", NS)
            (anchor.addnext(inv) if anchor is not None else ser.insert(2, inv))
            new.append(ser)
        etree.SubElement(new, q("gapWidth")).set("val", "60")
        for ax in line.findall("c:axId", NS):
            new.append(ax)
        plot.replace(line, new)
        axes("l" if kind == "bar" else "b", "b" if kind == "bar" else "l")
        return _xml_bytes(root)
    if kind == "line" and bar is not None:
        new = etree.Element(q("lineChart"))
        etree.SubElement(new, q("grouping")).set("val", "standard")
        etree.SubElement(new, q("varyColors")).set("val", "0")
        for ser in bar.findall("c:ser", NS):
            for t in ("invertIfNegative", "shape"):
                for el in ser.findall(f"c:{t}", NS):
                    ser.remove(el)
            sp = ser.find("c:spPr", NS)
            if sp is not None:
                fill = sp.find("a:solidFill", NS)
                ln = sp.find("a:ln", NS)
                if ln is not None:
                    sp.remove(ln)
                ln = etree.SubElement(sp, f"{{{NS['a']}}}ln")
                ln.set("w", "31750")
                ln.set("cap", "rnd")
                if fill is not None:
                    sp.remove(fill)
                    ln.append(fill)
                if sp.find("a:noFill", NS) is None:
                    sp.insert(0, etree.Element(f"{{{NS['a']}}}noFill"))
            mk = etree.Element(q("marker"))
            etree.SubElement(mk, q("symbol")).set("val", "circle")
            etree.SubElement(mk, q("size")).set("val", "6")
            anchor = sp if sp is not None else ser.find("c:tx", NS)
            (anchor.addnext(mk) if anchor is not None else ser.insert(2, mk))
            ext = ser.find("c:extLst", NS)
            sm = etree.Element(q("smooth"))
            sm.set("val", "0")
            (ext.addprevious(sm) if ext is not None else ser.append(sm))
            new.append(ser)
        etree.SubElement(new, q("marker")).set("val", "1")
        for ax in bar.findall("c:axId", NS):
            new.append(ax)
        plot.replace(bar, new)
        axes("b", "l")
        return _xml_bytes(root)
    return None


def apply_ops(data: bytes, ops_by_slide: dict) -> tuple[bytes, dict]:
    """Apply {slide n: [op]} to a pptx. Returns (new bytes, {slide n: [ops that took effect]}). Other parts stay byte-identical."""
    etree = _lxml()
    parts = read_zip(data)
    order = slide_parts(parts)
    repl: dict = {}
    done: dict = {}
    for n, ops in ops_by_slide.items():
        if not 1 <= n <= len(order):
            continue
        part = order[n - 1]
        root = etree.fromstring(parts[part][1])
        touched = False
        for op in ops:
            ok = False
            if op["op"] == "title":
                ok = _set_title(root, op["text"])
                touched = touched or ok
            elif op["op"] == "replace":
                ok = _replace_text(root, op["a"], op["b"]) > 0
                touched = touched or ok
            elif op["op"] == "chart":
                for r in _rels_of(parts, part):
                    if r["type"] == REL_CHART and r["target"] in parts:
                        new = _convert_chart(repl.get(r["target"], parts[r["target"]][1]), op["kind"])
                        if new is not None:
                            repl[r["target"]] = new
                            ok = True
            if ok:
                done.setdefault(n, []).append(op)
        if touched:
            repl[part] = _xml_bytes(root)
    return (patch_zip(data, repl) if repl else data), done


def reorder_zip(data: bytes, order: list[int]) -> bytes:
    """Reorder slides by 1-based `order` (a permutation). Slide parts only change where a page number has to follow its slide."""
    etree = _lxml()
    parts = read_zip(data)
    n = len(slide_parts(parts))
    if sorted(order) != list(range(1, n + 1)):
        raise _bad(f"The new order must list each of the {n} slides exactly once.", "Send a permutation such as [2,1,3].")
    pres = etree.fromstring(parts["ppt/presentation.xml"][1])
    lst = pres.find(".//p:sldIdLst", NS)
    ids = list(lst)
    for el in ids:
        lst.remove(el)
    for k in order:
        lst.append(ids[k - 1])
    repl = {"ppt/presentation.xml": _xml_bytes(pres)}
    old_parts = slide_parts(parts)
    for new_pos, k in enumerate(order, 1):
        if new_pos == k:
            continue
        part = old_parts[k - 1]
        root = etree.fromstring(parts[part][1])
        changed = False
        for s in _shape_texts(root):
            if ROLE_PAGE.search(s["name"]) and s["paras"] and s["paras"][0].isdigit():
                for t in s["el"].iter(f"{{{NS['a']}}}t"):
                    if t.text and t.text.strip().isdigit():
                        t.text = str(new_pos)
                        changed = True
                        break
        if changed:
            repl[part] = _xml_bytes(root)
    return patch_zip(data, repl)


# --------------------------------------------------------------------------- validator badges
def _validate(data: bytes) -> list[dict]:
    key = hashlib.sha256(data).hexdigest()
    if key in _VALIDATE_CACHE:
        return _VALIDATE_CACHE[key]
    try:
        from om.deck import validate
        findings = validate.validate(data).findings
    except Exception as e:  # missing deps: say so rather than showing a green badge
        findings = [{"severity": "major", "rule": "validator_unavailable", "slide": 0, "shape_id": None, "shape_name": None,
                     "message": f"The validator could not run ({type(e).__name__}); install python-pptx and Pillow."}]
    if len(_VALIDATE_CACHE) > 64:
        _VALIDATE_CACHE.clear()
    _VALIDATE_CACHE[key] = findings
    return findings


def _status(findings: list[dict]) -> str:
    sev = {f["severity"] for f in findings}
    return "fail" if "critical" in sev else "warn" if "major" in sev else "pass"


# --------------------------------------------------------------------------- rendering
def renderer_available() -> bool:
    return bool(shutil.which("soffice") or shutil.which("libreoffice")) and bool(shutil.which("pdftoppm"))


def render_pngs(data: bytes, cache_root: Path) -> list[Path]:
    """Slide PNGs (80 dpi) for a deck, cached by sha256. Raises ApiError 503 when LibreOffice/poppler are missing."""
    key = hashlib.sha256(data).hexdigest()
    out_dir = Path(cache_root) / "slides" / key
    done = out_dir / "done"
    if done.exists():
        return sorted(out_dir.glob("s-*.png"), key=lambda p: int(re.search(r"(\d+)\.png$", p.name).group(1)))
    if not renderer_available():
        raise ApiError(503, "renderer_unavailable", "Slide previews need LibreOffice and poppler on the server.",
                       "Install them: apt-get install -y libreoffice-impress poppler-utils. The text outline is shown meanwhile.")
    with _RENDER_LOCKS_G:
        lock = _RENDER_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if done.exists():
            return render_pngs(data, cache_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        with tempfile.TemporaryDirectory(prefix="acr-lo-") as tmp:
            src = Path(tmp) / "deck.pptx"
            src.write_bytes(data)
            try:
                subprocess.run([soffice, "--headless", f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", "pdf",
                                "--outdir", tmp, str(src)], check=True, capture_output=True, timeout=180)
                subprocess.run(["pdftoppm", "-png", "-r", "80", str(Path(tmp) / "deck.pdf"), str(out_dir / "s")],
                               check=True, capture_output=True, timeout=120)
            except (subprocess.SubprocessError, OSError) as e:
                raise ApiError(503, "render_failed", "The slide preview could not be rendered.",
                               f"Download the deck instead, or retry in a minute ({type(e).__name__}).") from None
        for p in out_dir.glob("s-*.png"):
            m = re.search(r"s-0*(\d+)\.png$", p.name)
            if m and p.name != f"s-{int(m.group(1))}.png":
                p.rename(out_dir / f"s-{int(m.group(1))}.png")
        done.write_text("ok")
    return render_pngs(data, cache_root)


# --------------------------------------------------------------------------- jobs and approvals (optional modules)
def _submit_job(ctx, kind: str, deal_id: str, prompt: str, inputs: dict) -> str:
    try:
        from om.api import jobs  # type: ignore
        submit = getattr(getattr(jobs, "SERVICE", None), "submit")
    except (ImportError, AttributeError):
        raise ApiError(503, "jobs_unavailable", "The edit needs the model, and the job runner is not available here.",
                       "Rephrase as 'title: New title', 'replace \"old\" with \"new\"' or 'change chart to line', or try again later.") from None
    avail = {"org_id": ctx.org_id, "deal_id": deal_id, "user_id": (ctx.user or {}).get("id"), "prompt": prompt, "agent_id": kind,
             "kind": kind, "inputs": inputs, "source": "app", "conn": ctx.conn}
    sig = inspect.signature(submit)
    kw = avail if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()) else {k: v for k, v in avail.items() if k in sig.parameters}
    res = submit(**kw)
    if isinstance(res, dict):
        return str(res.get("id") or res.get("job_id") or "")
    return str(getattr(res, "id", None) or res)


def _approval(ctx, deal_id: str, name: str):
    """The pending ghost-deck approval for this deck, when the job tables exist."""
    try:
        for j in ctx.conn.execute("SELECT id FROM jobs WHERE org_id=? AND deal_id=? AND status='awaiting_approval' ORDER BY started_at DESC",
                                  (ctx.org_id, deal_id)).fetchall():
            ev = ctx.conn.execute("SELECT data_json FROM job_events WHERE job_id=? AND type='approval' ORDER BY seq DESC LIMIT 1", (j["id"],)).fetchone()
            data = json.loads(ev["data_json"]) if ev else None
            if data and data.get("kind") == "ghost_deck":
                p = data.get("payload") or {}
                if p.get("deck_name") in (None, name):
                    return {"job_id": j["id"], "step_id": data.get("step_id"), "kind": "ghost_deck", "payload": p}
    except Exception:
        return None
    return None


def _citation_for_source(ctx, deal_id: str, text: str):
    """A citation token when a source line names one of the deal's documents; None otherwise."""
    try:
        from om.api import grid as _g
        words = [w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in ("source", "sources", "company", "filings", "asof", "from")]
        if not words:
            return None
        best, best_n = None, 0
        for d in ctx.conn.execute("SELECT id, name FROM documents WHERE org_id=? AND deal_id=?", (ctx.org_id, deal_id)):
            n = sum(1 for w in words if w in d["name"].lower())
            if n > best_n:
                best, best_n = d, n
        if best is None:
            return None
        return {"token": _g._mint(ctx.conn, ctx.org_id, best["id"], 1, None, text), "doc_id": best["id"], "page": 1}
    except Exception:
        return None


# --------------------------------------------------------------------------- state: accepts and comments
def _accepted(ctx, deal_id, name) -> set:
    return {r["slide_key"] for r in ctx.conn.execute("SELECT slide_key FROM deck_accepts WHERE org_id=? AND deal_id=? AND deck_name=?",
                                                     (ctx.org_id, deal_id, name))}


def _comment_out(r) -> dict:
    return {"id": r["id"], "slide": r["slide"], "x": r["x"], "y": r["y"], "body": r["body"], "author_id": r["author_id"],
            "status": r["status"], "created_at": r["created_at"], "version": r["version"],
            "applied_in_version": r["applied_in_version"], "job_id": r["job_id"]}


def _comments(ctx, deal_id, name, version) -> list[dict]:
    return [_comment_out(r) for r in ctx.conn.execute(
        "SELECT * FROM deck_comments WHERE org_id=? AND deal_id=? AND deck_name=? AND version=? ORDER BY created_at, id",
        (ctx.org_id, deal_id, name, version))]


# --------------------------------------------------------------------------- routes
def get_deck(ctx):
    store, deal_id, name, hist, version, data = _deck(ctx, ctx.query.get("version"))
    slides = read_slides(data)
    findings = _validate(data)
    accepted = _accepted(ctx, deal_id, name)
    base = f"/api/v1/decks/{deal_id}/{name}/v/{version}/slides"
    out = []
    for s in slides:
        fs = [f for f in findings if f["slide"] == s["n"]]
        out.append({"n": s["n"], "title": s["title"], "png_url": f"{base}/{s['n']}.png", "outline": s["outline"],
                    "sources": [{"text": t, "citation_token": (_citation_for_source(ctx, deal_id, t) or {}).get("token")} for t in s["sources"]],
                    "badges": [{"rule": f["rule"], "severity": f["severity"], "message": f["message"], "shape": f.get("shape_name")} for f in fs],
                    "status": _status(fs), "accepted": s["key"] in accepted, "key": s["key"][:16]})
    deck_level = [f for f in findings if f["slide"] == 0]
    return {"deal_id": deal_id, "name": name, "version": version,
            "versions": [{"version": h["version"], "created_at": h["created_at"], "note": h["note"], "size": h["size"]} for h in hist],
            "slides": out,
            "validator": {"passed": not any(f["severity"] == "critical" for f in findings), "status": _status(findings),
                          "counts": {k: sum(1 for f in findings if f["severity"] == k) for k in ("critical", "major", "minor")},
                          "findings": [{"rule": f["rule"], "severity": f["severity"], "message": f["message"], "slide": f["slide"]} for f in deck_level]},
            "comments": _comments(ctx, deal_id, name, version), "renderer": {"available": renderer_available()},
            "approval": _approval(ctx, deal_id, name),
            "download_url": f"/api/v1/deals/{deal_id}/deliverables/{name}/versions/{version}/download"}


def slide_png(ctx):
    store, deal_id, name, hist, version, data = _deck(ctx, ctx.params["version"])
    n = ctx.params["n"]
    n = int(n[:-4] if n.endswith(".png") else n) if re.fullmatch(r"\d+(\.png)?", n) else 0
    if not 1 <= n <= len(slide_parts(read_zip(data))):
        raise _nf()
    cache = Path(ctx.data_dir or tempfile.gettempdir()) / "cache"
    pngs = render_pngs(data, cache)
    if n > len(pngs):
        raise _nf()
    return Response(200, pngs[n - 1].read_bytes(), "image/png", {"Cache-Control": "private, max-age=31536000, immutable"})


def post_comment(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx, _body(ctx).get("version"))
    b = _body(ctx)
    slides = read_slides(data)
    try:
        slide, x, y = int(b.get("slide")), float(b.get("x", 0.5)), float(b.get("y", 0.5))
    except (TypeError, ValueError):
        raise _bad("A comment needs a slide number and an x,y position.", "Click on the slide to drop a pin.") from None
    text = str(b.get("body") or "").strip()
    if not 1 <= slide <= len(slides):
        raise _bad(f"This deck has {len(slides)} slides.", "Pick a slide that exists.")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise _bad("The pin position must be inside the slide.", "x and y are fractions between 0 and 1.")
    if not text or len(text) > MAX_COMMENT:
        raise _bad("Write what should change (up to 2,000 characters).", "For example: 'Change the title to \"Revenue up 12%\"'.")
    if version != hist[-1]["version"]:
        raise _bad("Comments go on the latest version.", f"Switch to version {hist[-1]['version']} or roll back first.", "not_latest", 409)
    if slides[slide - 1]["key"] in _accepted(ctx, deal_id, name):
        raise _bad("This slide is accepted and locked.", "Unlock it (remove the acceptance) before asking for changes.", "slide_locked", 409)
    cid = _db.new_id("cmt")
    ctx.conn.execute("INSERT INTO deck_comments(id, org_id, deal_id, deck_name, version, slide, x, y, body, author_id, status, created_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?, 'open', ?)",
                     (cid, ctx.org_id, deal_id, name, version, slide, x, y, text, (ctx.user or {}).get("id"), _db.now()))
    ctx.audit("deck.comment", f"{deal_id}/{name}", {"slide": slide, "version": version})
    return 201, _comment_out(ctx.conn.execute("SELECT * FROM deck_comments WHERE id=?", (cid,)).fetchone())


def delete_comment(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx)
    n = ctx.conn.execute("DELETE FROM deck_comments WHERE id=? AND org_id=? AND deal_id=? AND deck_name=? AND status='open'",
                         (ctx.params["comment_id"], ctx.org_id, deal_id, name)).rowcount
    if not n:
        raise _nf()
    return {"deleted": ctx.params["comment_id"]}


def apply_comments(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx)
    ids = _body(ctx).get("comment_ids")
    if not isinstance(ids, list) or not ids:
        raise _bad("Choose the comments to apply.", "Send comment_ids: the open comments on this version.")
    qs = ",".join("?" * len(ids))
    rows = ctx.conn.execute(f"SELECT * FROM deck_comments WHERE org_id=? AND deal_id=? AND deck_name=? AND id IN ({qs}) ORDER BY created_at, id",
                            (ctx.org_id, deal_id, name, *ids)).fetchall()
    if len(rows) != len(set(ids)):
        raise _nf()
    if any(r["status"] != "open" for r in rows):
        raise _bad("Some comments were already applied.", "Refresh the deck; only open comments can be applied.", "already_applied", 409)
    if any(r["version"] != version for r in rows):
        raise _bad("Those comments belong to an older version.", "Re-add them on the latest version.", "not_latest", 409)
    slides = read_slides(data)
    locked = _accepted(ctx, deal_id, name)
    for r in rows:
        if slides[r["slide"] - 1]["key"] in locked:
            raise _bad(f"Slide {r['slide']} is accepted and locked.", "Remove the acceptance first; accepted slides stay byte-identical.", "slide_locked", 409)
    ops_by_slide: dict = {}
    owner: dict = {}
    for r in rows:
        ops = parse_comment(r["body"])
        for op in ops:
            ops_by_slide.setdefault(r["slide"], []).append(op)
            owner.setdefault((r["slide"], json.dumps(op, sort_keys=True)), []).append(r["id"])
    new_data, done = apply_ops(data, ops_by_slide) if ops_by_slide else (data, {})
    applied_ids = {cid for (n, js), cids in owner.items() if any(json.dumps(o, sort_keys=True) == js for o in done.get(n, [])) for cid in cids}
    pending = [r for r in rows if r["id"] not in applied_ids]
    jobs_out = []
    for r in pending:
        s = slides[r["slide"] - 1]
        prompt = (f"Edit slide {r['slide']} (\"{s['title']}\") of {name}: {r['body']}  "
                  f"[pin at x={r['x']:.2f}, y={r['y']:.2f}] Change only this slide; keep every other slide untouched.")
        try:
            jid = _submit_job(ctx, "deck_edit", deal_id, prompt, {"deck": name, "version": version, "slide": r["slide"], "comment_id": r["id"],
                                                                  "x": r["x"], "y": r["y"]})
        except ApiError as e:
            if applied_ids:
                jobs_out.append({"comment_id": r["id"], "error": e.message, "hint": e.hint})
                continue
            raise ApiError(422, "needs_model", f"Comment on slide {r['slide']} needs the model editor.", e.hint) from None
        ctx.conn.execute("UPDATE deck_comments SET status='job', job_id=? WHERE id=?", (jid, r["id"]))
        jobs_out.append({"comment_id": r["id"], "job_id": jid, "slide": r["slide"]})
    new_version = None
    if applied_ids:
        slides_changed = sorted({n for n in done})
        note = f"Revision round: {len(applied_ids)} comment(s) applied to slide(s) " + ", ".join(map(str, slides_changed))
        saved = store.save_deliverable(deal_id, name, new_data, "pptx", note)
        new_version = saved["version"]
        qs2 = ",".join("?" * len(applied_ids))
        ctx.conn.execute(f"UPDATE deck_comments SET status='applied', applied_in_version=? WHERE id IN ({qs2})", (new_version, *applied_ids))
    ctx.audit("deck.apply", f"{deal_id}/{name}", {"applied": len(applied_ids), "jobs": len(jobs_out), "version": new_version})
    return 201 if new_version else 202, {"version": new_version, "applied": sorted(applied_ids), "slides_changed": sorted(done),
                                         "jobs": jobs_out, "from_version": version}


def accept_slide(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx, ctx.query.get("version"))
    n = int(ctx.params["n"]) if ctx.params["n"].isdigit() else 0
    slides = read_slides(data)
    if not 1 <= n <= len(slides):
        raise _nf()
    key = slides[n - 1]["key"]
    ctx.conn.execute("INSERT OR IGNORE INTO deck_accepts(org_id, deal_id, deck_name, slide_key, accepted_by, created_at) VALUES(?,?,?,?,?,?)",
                     (ctx.org_id, deal_id, name, key, (ctx.user or {}).get("id"), _db.now()))
    ctx.audit("deck.accept", f"{deal_id}/{name}", {"slide": n})
    return {"slide": n, "accepted": True}


def unaccept_slide(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx, ctx.query.get("version"))
    n = int(ctx.params["n"]) if ctx.params["n"].isdigit() else 0
    slides = read_slides(data)
    if not 1 <= n <= len(slides):
        raise _nf()
    ctx.conn.execute("DELETE FROM deck_accepts WHERE org_id=? AND deal_id=? AND deck_name=? AND slide_key=?",
                     (ctx.org_id, deal_id, name, slides[n - 1]["key"]))
    return {"slide": n, "accepted": False}


def regenerate_slide(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx)
    n = int(ctx.params["n"]) if ctx.params["n"].isdigit() else 0
    slides = read_slides(data)
    if not 1 <= n <= len(slides):
        raise _nf()
    if slides[n - 1]["key"] in _accepted(ctx, deal_id, name):
        raise _bad(f"Slide {n} is accepted and locked.", "Remove the acceptance first.", "slide_locked", 409)
    instr = str(_body(ctx).get("instruction") or "").strip()
    prompt = f"Regenerate slide {n} (\"{slides[n - 1]['title']}\") of {name}." + (f" {instr}" if instr else "") + " Change only this slide."
    jid = _submit_job(ctx, "deck_edit", deal_id, prompt, {"deck": name, "version": version, "slide": n, "regenerate": True})
    return 202, {"job_id": jid, "slide": n}


def reorder(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx)
    order = _body(ctx).get("order")
    if not isinstance(order, list) or not all(isinstance(i, int) for i in order):
        raise _bad("Send the new order as a list of slide numbers.", "For example {\"order\": [2, 1, 3]}.")
    if order == list(range(1, len(order) + 1)):
        return {"version": version, "changed": False}
    new = reorder_zip(data, order)
    saved = store.save_deliverable(deal_id, name, new, "pptx", "Reordered slides: " + ", ".join(map(str, order)))
    # a moved slide's page number is rewritten, which changes its fingerprint: an accepted slide stays accepted
    old_keys, new_keys = [s["key"] for s in read_slides(data)], [s["key"] for s in read_slides(new)]
    locked = _accepted(ctx, deal_id, name)
    for pos, k in enumerate(order):
        if old_keys[k - 1] in locked and new_keys[pos] != old_keys[k - 1]:
            ctx.conn.execute("INSERT OR IGNORE INTO deck_accepts(org_id, deal_id, deck_name, slide_key, accepted_by, created_at) VALUES(?,?,?,?,?,?)",
                             (ctx.org_id, deal_id, name, new_keys[pos], (ctx.user or {}).get("id"), _db.now()))
    ctx.audit("deck.reorder", f"{deal_id}/{name}", {"order": order})
    return 201, {"version": saved["version"], "changed": True}


def compare(ctx):
    store, deal_id, name, hist, latest, _ = _deck(ctx)
    try:
        b = int(ctx.query.get("b") or latest)
        a = int(ctx.query.get("a") or (hist[-2]["version"] if len(hist) > 1 else latest))
    except ValueError:
        raise _bad("Versions must be whole numbers.", "Pick two versions from the list.") from None
    vers = {h["version"] for h in hist}
    if a not in vers or b not in vers:
        raise _nf()
    sa, sb = read_slides(store.get_version(deal_id, name, a)), read_slides(store.get_version(deal_id, name, b))
    out, changed = [], []
    for i in range(max(len(sa), len(sb))):
        x = sa[i] if i < len(sa) else None
        y = sb[i] if i < len(sb) else None
        if x is None or y is None:
            status = "added" if x is None else "removed"
            diff = {"removed": (x or {}).get("texts", []), "added": (y or {}).get("texts", [])}
        elif x["key"] == y["key"]:
            status, diff = "unchanged", {"removed": [], "added": []}
        else:
            status = "changed"
            sm = difflib.SequenceMatcher(None, x["texts"], y["texts"])
            diff = {"removed": [], "added": []}
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                if tag != "equal":
                    diff["removed"] += x["texts"][i1:i2]
                    diff["added"] += y["texts"][j1:j2]
        if status != "unchanged":
            changed.append(i + 1)
        out.append({"n": i + 1, "status": status, "title_a": (x or {}).get("title"), "title_b": (y or {}).get("title"), "text_diff": diff})
    return {"a": a, "b": b, "slides": out, "changed": changed, "identical": not changed,
            "png_a": f"/api/v1/decks/{deal_id}/{name}/v/{a}/slides/", "png_b": f"/api/v1/decks/{deal_id}/{name}/v/{b}/slides/"}


def rollback(ctx):
    ctx.require("member")
    store, deal_id, name, hist, version, data = _deck(ctx)
    target = _body(ctx).get("version")
    if not any(h["version"] == target for h in hist):
        raise _bad("Pick one of the existing versions.", "Open the version list and choose the one to restore.")
    saved = store.restore(deal_id, name, target, note=f"Rollback to v{target}")
    ctx.audit("deck.rollback", f"{deal_id}/{name}", {"to": target})
    return 201, {"version": saved["version"], "restored": target}


ROUTES = [
    Route("GET", "/api/v1/decks/{deal_id}/{name}", get_deck, role="viewer"),
    Route("GET", "/api/v1/decks/{deal_id}/{name}/v/{version}/slides/{n}.png", slide_png, role="viewer"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/comments", post_comment, role="member"),
    Route("DELETE", "/api/v1/decks/{deal_id}/{name}/comments/{comment_id}", delete_comment, role="member"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/apply", apply_comments, role="member"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/slides/{n}/accept", accept_slide, role="member"),
    Route("DELETE", "/api/v1/decks/{deal_id}/{name}/slides/{n}/accept", unaccept_slide, role="member"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/slides/{n}/regenerate", regenerate_slide, role="member"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/reorder", reorder, role="member"),
    Route("GET", "/api/v1/decks/{deal_id}/{name}/compare", compare, role="viewer"),
    Route("POST", "/api/v1/decks/{deal_id}/{name}/rollback", rollback, role="member"),
]
