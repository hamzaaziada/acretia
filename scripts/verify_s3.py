#!/usr/bin/env python3
"""S3 gate: deck engine v2 (spec, ghost deck, archetypes, native charts, fit, validator, RTL, theme cloner, model sync,
vision-critic loop, creative visual layer, hygiene, north-star metrics, parity items).

Written from docs/s3/gate-spec.md (sections A-L) without reading the implementers' tests. Offline: sockets are disabled
for the whole run, ACRETIA_LLM_MODE=replay, ACRETIA_DATA is a temp dir. Every check prints
`PASS|FAIL|SKIP <id> <one-line evidence>`; exit 0 only if no FAIL.

    python3 scripts/verify_s3.py [--only A,C3,K] [--json out.json]

SKIP is used only when LibreOffice/poppler are absent. A missing corpus (evals/decks/...) or a missing in-flight module is a
FAIL, never a SKIP. Fixtures with planted defects are built inside this script; implementer self-reports are not trusted.
"""
from __future__ import annotations

import argparse
import ast
import copy
import csv
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import math
import os
import posixpath
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# ------------------------------------------------------------ hermetic environment
_SCRUB = re.compile(r"(_API_KEY|_AUTH_TOKEN|_BASE_URL)$|^(OM_PROVIDER_|OM_FALLBACK_|OM_MODEL_|OM_STAGE_|MESHPOOL_|"
                    r"ANTHROPIC_|OPENAI_|GEMINI_|DEEPSEEK_|ACRETIA_LLM_)|^GOOGLE_API_KEY$")
for _k in [k for k in os.environ if _SCRUB.search(k)]:
    del os.environ[_k]
os.environ["ACRETIA_LLM_MODE"] = "replay"
TMP = Path(tempfile.mkdtemp(prefix="verify_s3_"))
os.environ["ACRETIA_DATA"] = str(TMP / "data")
OUT = TMP / "decks"
OUT.mkdir(parents=True, exist_ok=True)

# import heavy stdlib network modules BEFORE the socket patch so their socket subclasses bind to the real class
import http.client  # noqa: E402,F401
import ssl  # noqa: E402,F401
import urllib.request  # noqa: E402,F401
from lxml import etree  # noqa: E402

for _m in ("om.deck.spec", "om.deck.ghost", "om.deck.engine", "om.deck.render", "om.deck.validate", "om.deck.metrics",
           "om.deck.fit", "om.deck.rtl", "om.deck.critic", "om.deck.sync", "om.deck.house_clone", "om.deck.provenance",
           "om.deck.slop", "om.deck.archetypes", "om.deck.theme", "om.deck.model", "om.deck.visuals.probe",
           "om.deck.visuals.log", "om.deck.visuals.variety", "om.deck.visuals.library", "src.harness.adapter",
           "om.contracts"):
    try:
        importlib.import_module(_m)
    except Exception:  # noqa: BLE001 - reported by the checks that need the module
        pass

_REAL_SOCKET = socket.socket
ATT = {"n": 0, "first": ""}


class _NoSocket(_REAL_SOCKET):
    def __init__(self, *a, **k):
        ATT["n"] += 1
        ATT["first"] = ATT["first"] or "".join(traceback.format_stack(limit=4)[:-1])[-300:]
        raise OSError("gate: network disabled")


def _no_conn(*a, **k):
    ATT["n"] += 1
    ATT["first"] = ATT["first"] or "create_connection/getaddrinfo"
    raise OSError("gate: network disabled")


socket.socket, socket.create_connection, socket.getaddrinfo = _NoSocket, _no_conn, _no_conn

# ------------------------------------------------------------ check framework
REG: list = []


class Fail(Exception):
    pass


class Skip(Exception):
    pass


def check(cid):
    def deco(fn):
        REG.append((cid, fn))
        return fn
    return deco


def need(cond, msg):
    if not cond:
        raise Fail(msg)


def mod(name):
    """Import a module or fail with 'module missing'."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and (name == e.name or name.startswith(e.name + ".")):
            raise Fail(f"module missing: {name}") from None
        raise Fail(f"module {name} cannot be imported: {type(e).__name__}: {e}") from None
    except Exception as e:  # noqa: BLE001
        raise Fail(f"module {name} cannot be imported: {type(e).__name__}: {e}") from None


def has_lo():
    return bool(shutil.which("soffice") or shutil.which("libreoffice")) and bool(shutil.which("pdftoppm"))


# ------------------------------------------------------------ package parsing helpers
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PN = "http://schemas.openxmlformats.org/presentationml/2006/main"
CN = "http://schemas.openxmlformats.org/drawingml/2006/chart"
RN = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"a": A, "p": PN, "c": CN, "r": RN}
EMU = 914400.0
CANVAS_W = 13.333
MARGIN = 0.7
ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
NAME_RE = re.compile(r"^s(\d+)\.([a-z_]+)(?:\.(.+))?$")


class P:
    """A parsed .pptx package (read-only view)."""

    def __init__(self, data: bytes):
        self.data = data
        self.z = zipfile.ZipFile(io.BytesIO(data))
        self.names = self.z.namelist()
        self._x: dict = {}
        self.parts = {n: self.z.read(n) for n in self.names}

    def xml(self, name):
        if name not in self._x:
            self._x[name] = etree.fromstring(self.parts[name])
        return self._x[name]

    def rels(self, part):
        rp = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if rp not in self.parts:
            return {}
        out = {}
        for r in etree.fromstring(self.parts[rp]):
            if r.get("TargetMode") == "External":
                continue
            t = r.get("Target", "")
            tgt = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), t))
            out[r.get("Id")] = (r.get("Type", ""), tgt)
        return out

    def slides(self):
        pres = self.xml("ppt/presentation.xml")
        rel = self.rels("ppt/presentation.xml")
        return [rel[s.get(f"{{{RN}}}id")][1] for s in pres.findall("p:sldIdLst/p:sldId", NS)]

    def slide_size(self):
        sz = self.xml("ppt/presentation.xml").find("p:sldSz", NS)
        return int(sz.get("cx")) / EMU, int(sz.get("cy")) / EMU

    def theme_root(self):
        names = sorted(n for n in self.names if re.match(r"ppt/theme/theme\d+\.xml$", n))
        return self.xml(names[0]) if names else None


def shapes_of(root):
    tree = root.find("p:cSld/p:spTree", NS)
    out = []
    for ch in tree:
        tag = etree.QName(ch).localname
        if tag not in ("sp", "pic", "graphicFrame", "cxnSp", "grpSp"):
            continue
        nv = ch.find(".//p:cNvPr", NS)
        xf = ch.find("p:xfrm", NS) if tag == "graphicFrame" else (
            ch.find("p:grpSpPr/a:xfrm", NS) if tag == "grpSp" else ch.find("p:spPr/a:xfrm", NS))
        x = y = w = h = 0.0
        if xf is not None and xf.find("a:off", NS) is not None:
            o, e = xf.find("a:off", NS), xf.find("a:ext", NS)
            x, y, w, h = int(o.get("x")) / EMU, int(o.get("y")) / EMU, int(e.get("cx")) / EMU, int(e.get("cy")) / EMU
        m = NAME_RE.match(nv.get("name", ""))
        out.append({"name": nv.get("name", ""), "id": int(nv.get("id", "0")), "tag": tag, "x": x, "y": y, "w": w, "h": h,
                    "el": ch, "role": m.group(2) if m else None, "n": int(m.group(1)) if m else None})
    return out


def paras_of(el):
    """[(pPr element or None, text)] for every paragraph of a shape / table cell."""
    out = []
    for p in el.iter(f"{{{A}}}p"):
        out.append((p.find("a:pPr", NS), "".join(t.text or "" for t in p.iter(f"{{{A}}}t"))))
    return out


def text_of(el):
    return "\n".join(t for _, t in paras_of(el))


def chart_series(root):
    out = []
    for ser in root.iter(f"{{{CN}}}ser"):
        d = {"name": "".join(ser.xpath("c:tx//c:v/text()", namespaces=NS))}
        for tag in ("val", "yVal", "xVal"):
            cache = ser.find(f"c:{tag}/c:numRef/c:numCache", NS)
            if cache is None:
                continue
            n = int(cache.find("c:ptCount", NS).get("val"))
            vals = {int(pt.get("idx")): float(pt.findtext("c:v", namespaces=NS)) for pt in cache.findall("c:pt", NS)}
            d[tag] = [vals.get(i) for i in range(n)]
        out.append(d)
    return out


def slide_chart_parts(p: P, slide_part, root=None):
    """{shape name: chart part} for the graphicFrames of a slide."""
    root = root if root is not None else p.xml(slide_part)
    rels = p.rels(slide_part)
    out = {}
    for s in shapes_of(root):
        if s["tag"] == "graphicFrame":
            ch = s["el"].find(".//c:chart", NS)
            if ch is not None:
                out[s["name"]] = rels[ch.get(f"{{{RN}}}id")][1]
    return out


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def series_eq(a, b):
    if a is None or b is None or len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if (x is None) != (y is None):
            return False
        if x is not None and not close(float(x), float(y)):
            return False
    return True


# ------------------------------------------------------------ build helpers
class Deck:
    def __init__(self, name, spec, rep: dict, wall: float, path, data: bytes | None):
        self.name, self.spec, self.r, self.wall, self.path, self.data = name, spec, rep, wall, path, data
        self._p = None
        self.lang = spec.get("lang", "en")

    @property
    def p(self) -> P:
        if self._p is None:
            self._p = P(self.data)
        return self._p


def crit_nonprov(findings):
    return [f for f in findings if f.get("severity") == "critical" and f.get("rule") != "unsourced_number"]


def build_deck(name, spec, *, seed=7, save=True, **kw) -> Deck:
    E = mod("om.deck.engine")
    out = str(OUT / f"{name}.pptx") if save else None
    t = time.perf_counter()
    rep = E.build(spec, out=out, seed=seed, **kw)
    wall = time.perf_counter() - t
    data = rep.data if rep.data is not None else (Path(out).read_bytes() if out and Path(out).exists() else None)
    return Deck(name, spec, rep.to_dict(), wall, out, data)


def slide_with_id(arch_id, i, ex=None):
    A_ = mod("om.deck.archetypes")
    s = copy.deepcopy(ex if ex is not None else A_.REGISTRY[arch_id].example)
    s["id"], s["archetype"] = f"s{i}", arch_id
    return s


def deck_spec(slides, *, deck_id="gate-deck", title="Gate deck", lang="en", as_of="2026-09-30", **extra):
    return {"deck_id": deck_id, "title": title, "lang": lang, "client": "Gate", "as_of": as_of, "art_direction": "auto",
            "theme": "house", "slides": slides, **extra}


_VALID_EX = None


def valid_examples():
    """[(archetype id, slide dict with id)] for registered examples that pass spec.validate on their own."""
    global _VALID_EX
    if _VALID_EX is None:
        A_, S = mod("om.deck.archetypes"), mod("om.deck.spec")
        out = []
        for i, (aid, a) in enumerate(A_.REGISTRY.items(), 1):
            if a.example is None:
                continue
            s = slide_with_id(aid, i)
            if not S.validate(deck_spec([s])):
                out.append((aid, s))
        _VALID_EX = out
    return _VALID_EX


def english_spec(n=None):
    sl = []
    for i, (aid, s) in enumerate(valid_examples(), 1):
        s = copy.deepcopy(s)
        s["id"] = f"s{i}"
        if aid == "visual_text" and not s.get("visual"):
            s["visual"] = {"concept": "digital onboarding journey for SMEs", "kind": "illustration"}
        sl.append(s)
    return deck_spec(sl[:n] if n else sl, deck_id="gate-en")


AR_PHRASES = ["نمو الإيرادات", "هامش الربح التشغيلي", "التدفق النقدي الحر", "حصة السوق", "تكلفة التمويل", "العائد على حقوق الملكية",
              "قاعدة العملاء", "الرافعة المالية", "خفض التكاليف", "الطلب المحلي", "محفظة القروض", "جودة الأصول", "الودائع الجارية",
              "الاستثمار الرأسمالي", "كفاءة التشغيل"]
AR_TITLES = ["ارتفعت الإيرادات 8% بدعم التسعير وتحسن المزيج", "يتداول المصرف عند أدنى مضاعف بين نظرائه بنسبة 10.6x",
             "يحقق الخيار الثاني أعلى قيمة بأقل مخاطر تنفيذ", "تحسنت وحدة الاقتصاد على كل المقاييس في عام 2026",
             "ينمو الربح التشغيلي 32 مليون دولار مع أثر التسعير", "نناقش اليوم العرض والتمويل والجدول الزمني",
             "تعتمد الحصة على الأفراد أكثر من أي نظير", "يتجاوز العائد المتوقع حد 18% بهامش مريح"]
_KEEP = {"id", "archetype", "direction", "key", "kind", "type", "number_format", "prefix", "suffix", "mode", "binding",
         "manifest_id", "format", "color", "unit", "units", "as_of", "lang", "status", "level", "style", "align"}


def arabize(node, key=None, ctr=None):
    ctr = ctr if ctr is not None else [0]
    if isinstance(node, dict):
        return {k: arabize(v, k, ctr) for k, v in node.items()}
    if isinstance(node, list):
        return [arabize(v, key, ctr) for v in node]
    if isinstance(node, str) and key not in _KEEP and not re.search(r"\d", node) and len(node) > 2:
        ctr[0] += 1
        return AR_PHRASES[ctr[0] % len(AR_PHRASES)]
    return node


def arabic_spec():
    S = mod("om.deck.spec")
    picks = ["cover", "exec_summary", "ranked_bar", "comparison_table", "kpi_row", "waterfall", "agenda", "stacked_bar"]
    sl, ctr = [], [0]
    for aid in picks:
        ex = dict(next((s for a, s in valid_examples() if a == aid), {}) or {})
        if not ex:
            continue
        ex = arabize(ex, None, ctr)
        ex["title"] = AR_TITLES[len(sl) % len(AR_TITLES)]
        ex["id"] = f"s{len(sl) + 1}"
        sl.append(ex)
        if S.validate(deck_spec(sl, lang="ar", deck_id="gate-ar", title="عرض الاختبار")):
            sl.pop()
    return deck_spec(sl, lang="ar", deck_id="gate-ar", title="عرض الاختبار")


_CACHE: dict = {}


def cached(key, fn):
    if key not in _CACHE:
        try:
            _CACHE[key] = ("ok", fn())
        except BaseException as e:  # noqa: BLE001
            _CACHE[key] = ("err", e)
    kind, v = _CACHE[key]
    if kind == "err":
        raise v
    return v


def fallback_en():
    return cached("fb_en", lambda: build_deck("fallback_en", english_spec()))


def fallback_ar():
    return cached("fb_ar", lambda: build_deck("fallback_ar", arabic_spec()))


# ------------------------------------------------------------ corpus
BRIEFS = ROOT / "evals/decks/briefs"
RELI = ROOT / "evals/decks/reliability"
EDITS = ROOT / "evals/decks/edits"


def _load_one(path: Path):
    S = mod("om.deck.spec")
    raw = S.load(path)
    ghost = raw.get("ghost")
    spec = raw
    if isinstance(raw.get("spec"), dict) and "slides" not in raw:
        spec = raw["spec"]
        ghost = ghost or raw.get("ghost")
    spec = {k: v for k, v in spec.items() if k != "ghost"}
    return {"name": path.stem, "file": path, "raw": raw, "spec": spec, "ghost": ghost}


def briefs():
    def go():
        if not BRIEFS.is_dir():
            raise Fail("corpus missing: evals/decks/briefs/ does not exist")
        files = sorted(p for p in BRIEFS.iterdir() if p.suffix.lower() in (".json", ".yaml", ".yml"))
        if not files:
            raise Fail("corpus missing: evals/decks/briefs/ has no brief files")
        return [_load_one(f) for f in files]
    return cached("briefs", go)


def corpus():
    """The 20 corpus decks, each built once through the engine entry point."""
    def go():
        E = mod("om.deck.engine")
        decks = []
        for b in briefs():
            name = b["name"]
            t = time.perf_counter()
            try:
                if b["ghost"]:
                    out = str(OUT / f"{name}.pptx")
                    res = E.deck_from_brief({"brief": b["raw"].get("brief", "") if isinstance(b["raw"].get("brief", ""), str) else "",
                                             "ghost": b["ghost"], "spec": b["spec"]}, adapter=None, approve=True, out=out, seed=7)
                    rep = res["report"]
                    path = res["pptx"]
                    data = Path(path).read_bytes() if path and Path(path).exists() else None
                    d = Deck(name, b["spec"], rep, time.perf_counter() - t, path, data)
                else:
                    d = build_deck(name, b["spec"])
            except Exception as e:  # noqa: BLE001
                d = Deck(name, b["spec"], {"ok": False, "error": f"{type(e).__name__}: {e}", "findings": [], "critical": 0,
                                           "major": 0, "visuals": [], "timings": {}, "job": {}}, time.perf_counter() - t, None, None)
            decks.append(d)
        return decks
    return cached("corpus", go)


def decks_or_fallback():
    """(decks, note). Corpus decks when present, else fallback decks built by this script."""
    try:
        cs = [d for d in corpus() if d.data]
        if cs:
            return cs, f"{len(cs)} corpus decks"
    except Fail:
        pass
    return [fallback_en(), fallback_ar()], "corpus absent: ran on 2 fallback decks built by the gate"


def need_data(d):
    need(d.data, f"{d.name}: no .pptx produced ({d.r.get('error')})")


# ============================================================================================ A. Deck set
@check("A1")
def a1():
    bs = briefs()
    need(len(bs) == 20, f"expected exactly 20 briefs, found {len(bs)}")
    S = mod("om.deck.spec")
    ar = [b for b in bs if b["spec"].get("lang") == "ar"]
    need(len(ar) >= 3, f"need >= 3 Arabic briefs, found {len(ar)}")
    bad = []
    for b in bs:
        errs = S.validate(b["spec"])
        if errs:
            bad.append(f"{b['name']}: {errs[0]}")
    need(not bad, f"{len(bad)} briefs fail spec.validate: " + "; ".join(bad[:3]))
    return f"20 briefs, {len(ar)} Arabic, all validate with 0 errors"


@check("A2")
def a2():
    ds = corpus()
    need(len(ds) == 20, f"expected 20 decks, found {len(ds)}")
    bad = [f"{d.name}: {d.r.get('error') or 'no file'}" for d in ds if not d.data or d.r.get("error")]
    need(not bad, f"{len(bad)} decks did not build: " + "; ".join(bad[:3]))
    for d in ds:
        zipfile.ZipFile(io.BytesIO(d.data)).testzip()
    ts = [d.r.get("total_seconds", d.wall) for d in ds]
    return f"20 built offline via engine; build s: min {min(ts):.1f} median {statistics.median(ts):.1f} max {max(ts):.1f}"


@check("A3")
def a3():
    V = mod("om.deck.validate")
    ds = corpus()
    crit, majors, bad = 0, [], []
    for d in ds:
        need_data(d)
        rep = V.validate(d.data)
        c = rep.critical
        m = sum(1 for f in rep.findings if f["severity"] == "major")
        crit += c
        majors.append(m)
        if c:
            bad.append(f"{d.name}: {[(f['rule'], f['slide']) for f in rep.findings if f['severity'] == 'critical'][:2]}")
        if m > 2:
            bad.append(f"{d.name}: {m} major")
    need(not bad, f"{crit} critical total; " + "; ".join(bad[:4]))
    return f"0 critical in 20 decks; majors per deck {majors}"


@check("A4")
def a4():
    if not (shutil.which("soffice") or shutil.which("libreoffice")) or not shutil.which("pdfinfo"):
        raise Skip("LibreOffice or poppler (pdfinfo) not installed")
    ds = corpus()
    for d in ds:
        need_data(d)
    od = TMP / "pdf"
    od.mkdir(exist_ok=True)
    paths = [d.path for d in ds]
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    t = time.perf_counter()
    r = subprocess.run([soffice, f"-env:UserInstallation=file://{TMP}/lo_a4", "--headless", "--convert-to", "pdf", "--outdir", str(od), *paths],
                       capture_output=True, timeout=1200, env={**os.environ, "HOME": str(TMP)})
    bad = []
    for d in ds:
        pdf = od / (Path(d.path).stem + ".pdf")
        n = len(d.p.slides())
        if not pdf.exists():
            bad.append(f"{d.name}: no pdf")
            continue
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", info)
        pages = int(m.group(1)) if m else -1
        if pages != n:
            bad.append(f"{d.name}: {pages} pages vs {n} slides")
    need(not bad, "; ".join(bad[:4]) + f" (soffice rc {r.returncode})")
    return f"20 decks -> pdf, page count == slide count ({time.perf_counter() - t:.0f}s)"


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⭐⭕⬛⬜⌀-⏿️‍]")
_LEV = re.compile(r"\b(?:to|we|will|can|could|would|should|may|might|must|you|they|and|or|that|which|how)\s+leverag(?:e|es|ed|ing)\b"
                  r"|\bleveraging\b(?!\s+(?:ratio|multiple))", re.I)
MY_BANNED = ["delve", "game-changer", "game changer", "seamless", "robust", "synergy", "synergies", "cutting-edge", "best-in-class",
             "holistic", "paradigm", "revolutionize", "empower", "journey", "unlock", "in today's fast-paced", "dive into",
             "at the end of the day", "world-class", "evolving landscape"]


def deck_text_items(p: P):
    """[(slide no, where, text)] for text frames, table cells and chart titles. Notes are excluded."""
    items = []
    for i, sp in enumerate(p.slides(), 1):
        root = p.xml(sp)
        for s in shapes_of(root):
            if s["tag"] in ("sp", "graphicFrame", "grpSp"):
                for ppr, t in paras_of(s["el"]):
                    if t.strip():
                        items.append((i, s["name"], t))
        for _, cpart in slide_chart_parts(p, sp, root).items():
            croot = p.xml(cpart)
            for ttl in croot.findall("c:chart/c:title", NS):
                t = "".join(x.text or "" for x in ttl.iter(f"{{{A}}}t"))
                if t.strip():
                    items.append((i, "chart title", t))
    return items


def slop_violations(items):
    try:
        banned = list(mod("om.deck.slop").BANNED)
    except Fail:
        banned = []
    pool = sorted({b.lower() for b in banned + MY_BANNED})
    rx = [(b, re.compile(r"(?<!\w)" + re.escape(b) + r"(?!\w)", re.I)) for b in pool]
    out = {"banned": [], "emdash": [], "emoji": [], "bang": []}
    for i, w, t in items:
        for b, r in rx:
            if r.search(t):
                out["banned"].append((i, w, b))
        if _LEV.search(t):
            out["banned"].append((i, w, "leverage (verb)"))
        if "—" in t:
            out["emdash"].append((i, w))
        if _EMOJI.search(t):
            out["emoji"].append((i, w))
        if "!" in t or "！" in t:
            out["bang"].append((i, w))
    return out


@check("A5")
def a5():
    ds = corpus()
    tot = {"banned": 0, "emdash": 0, "emoji": 0, "bang": 0}
    ex = []
    n = 0
    for d in ds:
        need_data(d)
        items = deck_text_items(d.p)
        n += len(items)
        v = slop_violations(items)
        for k in tot:
            tot[k] += len(v[k])
            if v[k]:
                ex.append(f"{d.name}:{k}:{v[k][0]}")
    need(not any(tot.values()), f"slop in corpus {tot}; e.g. {ex[:3]}")
    return f"{n} text items in 20 decks: 0 banned phrases, 0 em dashes, 0 emojis, 0 exclamation marks"


def house_frame_problems(p: P):
    """Violations of the house frame on every content slide of a package."""
    bad = []
    sw, _ = p.slide_size()
    full = sw - 2 * MARGIN
    n_content = 0
    for i, sp in enumerate(p.slides(), 1):
        sh = shapes_of(p.xml(sp))
        roles = {s["role"] for s in sh if s["role"]}
        if "cover" in roles or "divider" in roles:
            continue
        title = next((s for s in sh if s["role"] == "title"), None)
        if title is None:
            bad.append(f"s{i}: no title shape")
            continue
        n_content += 1
        rules = [s for s in sh if s["role"] == "title_rule"]
        okr = any(r["w"] >= 0.9 * full and r["h"] < 0.02 and r["x"] >= MARGIN - 0.06 and r["x"] + r["w"] <= sw - MARGIN + 0.06
                  and title["y"] + title["h"] - 0.06 <= r["y"] <= title["y"] + title["h"] + 0.3 for r in rules)
        if not okr:
            bad.append(f"s{i}: title_rule missing or not margin-to-margin under the title")
        if not any(s["role"] == "footer_rule" for s in sh):
            bad.append(f"s{i}: footer_rule missing")
        pn = [s for s in sh if s["role"] == "page_number"]
        if not any(text_of(s["el"]).strip() == str(i) for s in pn):
            bad.append(f"s{i}: page_number text != {i}")
        for s in sh:
            if s is title or s["tag"] != "sp" or s["role"] in ("title", "title_rule", "footer_rule"):
                continue
            if text_of(s["el"]).strip() and s["y"] + s["h"] <= title["y"] + 0.01:
                bad.append(f"s{i}: text shape {s['name']} above the title (eyebrow)")
    return bad, n_content


@check("A6")
def a6():
    ds = corpus()
    allbad, nc = [], 0
    for d in ds:
        need_data(d)
        b, n = house_frame_problems(d.p)
        nc += n
        allbad += [f"{d.name} {x}" for x in b]
    need(not allbad, f"{len(allbad)} house-frame violations: " + "; ".join(allbad[:4]))
    return f"{nc} content slides in 20 decks: title rule, footer rule, page number, no eyebrow"


def source_problems(d: Deck):
    A_ = mod("om.deck.archetypes")
    bad, n = [], 0
    sps = d.p.slides()
    spec_slides = d.spec["slides"]
    if len(sps) != len(spec_slides):
        return [f"{d.name}: {len(sps)} slides rendered vs {len(spec_slides)} in the spec"], 0
    for i, (sp, ss) in enumerate(zip(sps, spec_slides), 1):
        arch = A_.REGISTRY.get(ss["archetype"])
        if not arch or not arch.data:
            continue
        n += 1
        src = [s for s in shapes_of(d.p.xml(sp)) if s["role"] == "source"]
        txt = " ".join(text_of(s["el"]) for s in src)
        if "source" not in txt.lower():
            bad.append(f"{d.name} s{i}({ss['archetype']}): no 'Source' line")
        elif not re.search(r"as of\s+\S*\d", txt, re.I):
            bad.append(f"{d.name} s{i}({ss['archetype']}): no as-of date in '{txt[:50]}'")
    return bad, n


@check("A7")
def a7():
    ds = corpus()
    allbad, n = [], 0
    for d in ds:
        need_data(d)
        b, c = source_problems(d)
        allbad += b
        n += c
    need(not allbad, f"{len(allbad)} data slides without source/as-of: " + "; ".join(allbad[:3]))
    return f"{n} data slides all carry a Source line and an as-of date"


# ============================================================================================ B. Spec and ghost
def _base_spec(blocks):
    return {"deck_id": "d", "title": "T", "lang": "en", "slides": [{"id": "s1", "archetype": "comparison_table", "title": "A 1", "blocks": blocks}]}


@check("B1")
def b1():
    S = mod("om.deck.spec")
    cases = [("top-level x", {**_base_spec({}), "x": 1}, "$.x"),
             ("nested font_size", _base_spec({"items": [{}, {}, {"font_size": 12}]}), "$.slides[0].blocks.items[2].font_size"),
             ("fill", _base_spec({"fill": "accent"}), "$.slides[0].blocks.fill"),
             ("hex in table cell", _base_spec({"rows": [["a", "b", "c"], ["d", "e", "#1A2B3C"]]}), "$.slides[0].blocks.rows[1][2]"),
             ("rgb()", _base_spec({"note": "rgb(1,2,3)"}), "$.slides[0].blocks.note")]
    for label, spec, path in cases:
        errs = S.validate(spec, skeleton=True)
        got = [e.path for e in errs]
        need(path in got, f"{label}: expected an error at {path}, got {got}")
    clean = S.validate(_base_spec({"note": "ok"}), skeleton=True)
    need(not clean, f"a clean spec was rejected: {clean[:2]}")
    return "5 forbidden-key / colour cases rejected with the exact JSON path; clean spec accepted"


@check("B2")
def b2():
    S = mod("om.deck.spec")
    spec = {"deck_id": "d", "title": "T", "lang": "en", "slides": [{"id": "s1", "archetype": "watefall", "title": "A 1", "blocks": {}}]}
    errs = S.validate(spec)
    e = next((e for e in errs if e.path == "$.slides[0].archetype"), None)
    need(e is not None, f"no error at $.slides[0].archetype: {errs}")
    need("waterfall" in e.message, f"no close match named in: {e.message}")
    spec["slides"][0]["archetype"] = "zzqq_nothing"
    e2 = next((e for e in S.validate(spec) if e.path == "$.slides[0].archetype"), None)
    need(e2 is not None and "unknown" in e2.message.lower(), "wholly unknown id not rejected as unknown")
    return f"'watefall' -> {e.message[:70]}"


def clean_ghost():
    G = mod("om.deck.ghost")
    t = [("Project Atlas carve-out", "cover"), ("Atlas adds $412m of value if we close by Q2 2027", "exec_summary"),
         ("The payments unit earns a 21.4% EBITDA margin, 4 points above peers", "ranked_bar"),
         ("Two customers carry 38% of revenue and both renew in 2027", "chart_takeaways"),
         ("Cost savings of $85m land within 24 months of close", "waterfall"),
         ("Net debt of 3.1x EBITDA falls to 2.2x by month 24", "stacked_bar"),
         ("A $1.62bn bid clears the 18% hurdle with 0.4x headroom", "football_field"),
         ("Approve exclusivity by 30 November and price both renewals in", "recommendation")]
    return G.GhostDeck("clean", "brief", "en", [G.GhostSlide(f"s{i + 1}", a, "Main", h) for i, (a, h) in enumerate(t)], ["Main"])


@check("B3")
def b3():
    G = mod("om.deck.ghost")
    long_title = " ".join(["Retail", "revenue", "grew", "8%", "while", "the", "corporate", "franchise", "treasury", "and", "markets", "desk",
                           "all", "lost", "share", "in", "a", "weaker", "rate", "cycle", "2026"])
    rows = [("Project Atlas", "cover"), ("Atlas adds $412m of value if we close by Q2 2027", "exec_summary"), (long_title, "bullets"),
            ("Overview", "bullets"), ("Net debt falls to 2.2x EBITDA within 24 months", "ranked_bar"),
            ("Net debt falls to 2.2x EBITDA within 24 months", "ranked_bar"),
            ("Retail revenue grows faster than corporate revenue", "chart_takeaways"),
            ("Margins expand 190 bps on cost savings.", "waterfall"), ("Margins expand 190 bps — savings drive most of it", "waterfall")]
    g = G.GhostDeck("planted", "b", "en", [G.GhostSlide(f"s{i + 1}", t, "S", h) for i, (t, h) in enumerate(rows)], ["S"])
    fs = G.lint(g)

    def has(rule, slide, sub=None):
        return any(f["rule"] == rule and f["slide"] == slide and (sub is None or sub in f["message"].lower()) for f in fs)
    exp = [("title_length", 2, None), ("generic_title", 3, None), ("duplicate_title", 5, None), ("title_number", 6, None),
           ("punctuation", 7, "full stop"), ("punctuation", 8, "dash")]
    miss = [e for e in exp if not has(*e)]
    need(not miss, f"ghost lint missed planted defects {miss}; got {[(f['rule'], f['slide']) for f in fs]}")
    fp = [(f["rule"], f["slide"]) for f in fs if f["slide"] in (0, 1, 4)]
    need(not fp, f"false positives on clean slides: {fp}")
    cl = G.lint(clean_ghost())
    need(cl == [], f"a clean 8-slide ghost deck got findings: {[(f['rule'], f['slide'], f['message'][:50]) for f in cl][:3]}")
    return "6 planted defects flagged on the right slides; clean 8-slide ghost deck has 0 findings"


@check("B4")
def b4():
    G, E = mod("om.deck.ghost"), mod("om.deck.engine")
    sl = [slide_with_id("cover", 1), slide_with_id("ranked_bar", 2)]
    spec = deck_spec(sl, deck_id="b4")
    g = clean_ghost()
    try:
        G.to_spec_skeleton(g)
        raise Fail("to_spec_skeleton accepted an unapproved ghost deck")
    except G.GhostNotApproved:
        pass
    try:
        G.require_approved(g)
        raise Fail("require_approved accepted an unapproved ghost deck")
    except G.GhostNotApproved:
        pass
    out1 = OUT / "b4_refused.pptx"
    rep = E.build(spec, ghost=g, require_ghost_approval=True, out=str(out1), seed=1)
    need(not rep.ok and any(f["rule"] == "ghost_not_approved" for f in rep.findings), "engine did not refuse the unapproved ghost deck")
    need(not out1.exists() and rep.data is None, "engine wrote a deck for an unapproved ghost deck")
    res = E.deck_from_brief({"brief": "x", "ghost": g.to_dict(), "spec": spec}, adapter=None, approve=None, out=str(OUT / "b4_dfb.pptx"))
    need(res["pptx"] is None, "deck_from_brief built a deck without approval")
    G.approve(g, "gate")
    out2 = OUT / "b4_ok.pptx"
    rep2 = E.build(spec, ghost=g, require_ghost_approval=True, out=str(out2), seed=1)
    need(rep2.error == "" and out2.exists(), f"approved ghost deck did not render: {rep2.error}")
    return "GhostNotApproved raised, engine refused (no file written), rendered after approve()"


# ============================================================================================ C. Archetypes and charts
REQ_ARCH = ["exec_summary", "agenda", "chart_takeaways", "ranked_bar", "waterfall", "stacked_bar", "annotated_line", "matrix_2x2",
            "football_field", "comparison_table", "gantt", "process_flow", "issue_tree", "market_map", "kpi_row", "quote",
            "section_divider", "comps_table", "tombstones"]


@check("C1")
def c1():
    R = mod("om.deck.archetypes").REGISTRY
    need(len(R) >= 35, f"only {len(R)} archetypes registered, need >= 35")
    miss = [a for a in REQ_ARCH if a not in R]
    need(not miss, f"required archetypes missing: {miss}")
    noex = [a for a, x in R.items() if x.example is None]
    need(not noex, f"archetypes without a registered example: {noex}")
    return f"{len(R)} archetypes, all {len(REQ_ARCH)} required ids present, every one ships an example"


@check("C2")
def c2():
    A_ = mod("om.deck.archetypes")
    bad, unsrc, secs = [], 0, []
    for i, (aid, a) in enumerate(A_.REGISTRY.items(), 1):
        s = slide_with_id(aid, 1, a.example)
        d = build_deck(f"c2_{aid}", deck_spec([s], deck_id=f"c2-{aid}"), save=False)
        cr = crit_nonprov(d.r["findings"])
        unsrc += sum(1 for f in d.r["findings"] if f["rule"] == "unsourced_number")
        secs.append(d.wall)
        if d.r["error"] or cr or not d.data:
            bad.append(f"{aid}: {d.r['error'][:80] or (cr[0]['rule'] + ' ' + cr[0]['message'][:60])}")
    need(not bad, f"{len(bad)}/{len(A_.REGISTRY)} archetypes fail to build/validate from their own example: " + " | ".join(bad[:5]))
    sl = [slide_with_id(aid, i, a.example) for i, (aid, a) in enumerate(A_.REGISTRY.items(), 1)]
    d = build_deck("c2_combined", deck_spec(sl, deck_id="c2-combined"))
    cr = crit_nonprov(d.r["findings"])
    need(not d.r["error"] and d.data, f"combined deck failed: {d.r['error'][:150]}")
    need(not cr, f"combined deck has {len(cr)} critical validator findings: {[(f['rule'], f['slide']) for f in cr][:4]}")
    return (f"{len(A_.REGISTRY)} archetypes build + validate alone and in one {len(sl)}-slide deck, 0 critical "
            f"(unsourced_number findings, covered by K2: {unsrc} alone)")


def solved_for(aid):
    A_, T = mod("om.deck.archetypes"), mod("om.deck.theme")
    a = A_.REGISTRY[aid]
    s = slide_with_id(aid, 1, a.example)
    return a.build(s, A_.BuildContext(T.Theme.house(), 1, 1, "Gate deck")), s


def waterfall_foots(sers, spec_vals, totals):
    """Reconstruct from the chart XML caches: Increase/Decrease/Total series."""
    by = {x["name"].lower(): x.get("val") for x in sers}
    up, dn, tot = by.get("increase"), by.get("decrease"), by.get("total")
    need(up is not None and dn is not None and tot is not None, f"waterfall caches missing Increase/Decrease/Total (have {list(by)})")
    n = len(spec_vals)
    run = None
    for i in range(n):
        if tot[i] is not None:
            need(close(tot[i], spec_vals[i]), f"total at {i}: cache {tot[i]} != spec {spec_vals[i]}")
            if run is not None:
                need(close(run, tot[i]), f"waterfall does not foot at {i}: running {run} vs total {tot[i]}")
            run = tot[i]
        else:
            d = (up[i] or 0.0) - (dn[i] or 0.0)
            need(close(d, spec_vals[i]), f"delta at {i}: cache {d} != spec {spec_vals[i]}")
            need(run is not None, "waterfall starts with a delta")
            run += d
    return n


@check("C3")
def c3():
    R, Rn = mod("om.deck.archetypes").REGISTRY, mod("om.deck.render")
    T = mod("om.deck.theme")
    n_arch = n_chart = 0
    problems = []
    for aid in R:
        solved, slide = solved_for(aid)
        charts = [e for e in solved.elements if e.chart]
        if not charts:
            continue
        n_arch += 1
        try:
            data = Rn.render([solved], T.Theme.house(), title="Gate")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{aid}: render {type(e).__name__}: {str(e)[:80]}")
            continue
        p = P(data)
        sp = p.slides()[0]
        sh = {s["name"]: s for s in shapes_of(p.xml(sp))}
        parts = slide_chart_parts(p, sp)
        for e in charts:
            n_chart += 1
            s = sh.get(e.id)
            if s is None or s["tag"] != "graphicFrame" or e.id not in parts:
                problems.append(f"{aid}/{e.id}: chart is not a native graphicFrame chart part (tag {s and s['tag']})")
                continue
            if any(x["tag"] == "pic" and x["name"] == e.id for x in sh.values()):
                problems.append(f"{aid}/{e.id}: chart drawn as a picture")
                continue
            sers = chart_series(p.xml(parts[e.id]))
            cs = e.chart
            typ = cs["type"]
            try:
                if typ == "waterfall":
                    vals = [float(v or 0) for v in cs["series"][0]["values"]]
                    waterfall_foots(sers, vals, cs.get("totals"))
                    tots = set(cs.get("totals", [0, len(vals) - 1]))
                    need(close(sum(v for i, v in enumerate(vals) if i not in tots), vals[-1] - vals[0]), "waterfall spec does not foot: start + deltas != end")
                elif typ == "football_field":
                    lo, hi = cs["series"][0]["values"], cs["series"][1]["values"]
                    need(len(sers) >= 2 and series_eq(sers[0].get("val"), lo), "football low cache != spec low values")
                    need(series_eq(sers[1].get("val"), [b - a for a, b in zip(lo, hi)]), "football range cache != high - low")
                else:
                    for sv in cs["series"]:
                        ok = any(series_eq(x.get(k), sv["values"]) for x in sers for k in ("val", "yVal"))
                        need(ok, f"series {sv.get('name')!r}: spec values not found in the chart cache")
                        if typ == "scatter" and sv.get("x"):
                            need(any(series_eq(x.get("xVal"), sv["x"]) for x in sers), f"scatter series {sv.get('name')!r}: x values not cached")
            except Fail as f:
                problems.append(f"{aid}/{e.id}: {f}")
        if aid == "chart_takeaways":   # also against the raw spec the author wrote, not the archetype's output
            raw = slide["blocks"]["chart"]["series"][0]["values"]
            sers = chart_series(p.xml(next(iter(parts.values()))))
            try:
                waterfall_foots(sers, [float(v) for v in raw], None)
            except Fail as f:
                problems.append(f"chart_takeaways raw spec: {f}")
    need(n_arch >= 8, f"only {n_arch} chart archetypes found, expected >= 8")
    need(not problems, f"{len(problems)} chart problems: " + " | ".join(problems[:4]))
    return f"{n_arch} chart archetypes / {n_chart} charts are native, caches == spec values (tol 1e-9), waterfalls foot"


@check("C4")
def c4():
    R = mod("om.deck.archetypes").REGISTRY
    vt = sorted({a.visual_type for a in R.values()})
    need(len(vt) >= 12, f"only {len(vt)} distinct visual types: {vt}")
    return f"{len(vt)} distinct visual types"


# ============================================================================================ D. Fit engine
@check("D1")
def d1():
    from PIL import ImageFont
    M = mod("om.deck.metrics")
    texts = ["Revenue grows 8% on pricing and mix", "EBITDA margin expands 190 bps", "Net debt to EBITDA falls to 2.2x",
             "The quick brown fox jumps over the lazy dog", "Approve exclusivity by 30 November", "Trading comparables, NTM multiples",
             "Regional revenue and margin by division", "Working capital neutral across the perimeter", "1,240 1,652 85 412 21.4%", "Customer concentration risk"]
    path = M.font_path("minor", False)
    need(path and Path(path).exists(), f"no measurement font found ({path})")
    f = ImageFont.truetype(path, 1000)
    worst = 0.0
    for t in texts:
        px = f.getlength(t)
        for pt in (10, 14, 24):
            ref = px / 1000 * pt / 72
            got = M.text_width(t, pt)
            err = abs(got - ref) / ref
            worst = max(worst, err)
            need(err <= 0.02, f"text_width off by {err:.1%} for {t[:30]!r} at {pt} pt (got {got:.3f} in, Pillow {ref:.3f} in)")
    return f"10 strings x 3 sizes within 2% of Pillow getlength (worst {worst:.2%}) using {Path(path).name}"


def _paras(text):
    Mo = mod("om.deck.model")
    return [Mo.Para([Mo.Run(text)], space_after=0)]


@check("D2")
def d2():
    F = mod("om.deck.fit")
    base = "Revenue grew on price and mix while volumes held steady across the perimeter this year "
    w, h = 4.0, 1.0
    k = 1
    while F.fit_text(_paras(base * k), w, h, size=10, floor=10, role="body", block_id="body.2").ok:
        k += 1
        need(k < 200, "fit never overflowed")
    fit_k = max(k - 1, 1)
    r = F.fit_text(_paras(base * (3 * fit_k)), w, h, size=14, floor=10, role="body", block_id="body.2")
    need(not r.ok and r.error is not None, "a block 3x too long for its box did not return a FitError")
    need(re.match(r"^\w+ block \d+ is \d+ words over; cut or split$", r.error.message), f"bad FitError message: {r.error.message!r}")
    need(r.error.words_over > 0, "FitError.words_over is 0")
    need(r.size >= 10, f"fitted size {r.size} fell below the floor 10")
    r2 = F.fit_text(_paras(base * max(fit_k // 2, 2)), w, h, size=14, floor=10, role="body", block_id="body.1")
    need(r2.size >= 10, f"shrink went below the floor: {r2.size}")
    return f"3x overflow -> {r.error.message!r}; size stayed >= floor ({r.size})"


@check("D3")
def d3():
    F, Mt, Mo = mod("om.deck.fit"), mod("om.deck.metrics"), mod("om.deck.model")
    w, n = 6.0, 5
    paras = [Mo.Para([Mo.Run(f"Line {i} of the block")], space_after=6) for i in range(n)]
    h_tight = Mt.para_height(paras, w, 14, line_spacing=1.0, space_after_pt=0.0)
    h_loose = Mt.para_height(paras, w, 14)
    need(h_tight < h_loose - 0.05, "fixture invalid: spacing does not change the height")
    h = h_tight + (h_loose - h_tight) * 0.3
    r = F.fit_text(paras, w, h, size=14, floor=10, role="body", block_id="body.1")
    need(r.ok, "block that fits after tightening was rejected")
    stages = [s.split(":")[0] for s in r.steps]
    need("tighten" in stages and "shrink" not in stages, f"steps {r.steps}: expected tighten and no shrink")
    need(r.size == 14, f"font shrank to {r.size} although tightening was enough")
    note = "" if "reflow" in stages else " (steps omit a leading 'reflow' entry; contract lists reflow first)"
    return f"steps {r.steps}, size stays 14{note}"


# ============================================================================================ E. Validator
def _pp():
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu, Inches, Pt
    return Presentation, RGBColor, MSO_CONNECTOR, MSO_SHAPE, Emu, Inches, Pt


def frame_slide(prs, n, *, rule=True, pagenum="n", eyebrow=False):
    """A clean house-framed slide built with python-pptx directly (not the renderer). Returns {name: shape}."""
    _, RGB, CON, SHP, Emu, In, Pt = _pp()
    lay = min(prs.slide_layouts, key=lambda l: len(l.placeholders))
    sl = prs.slides.add_slide(lay)
    for ph in list(sl.placeholders):
        ph._element.getparent().remove(ph._element)
    W = prs.slide_width
    full = W - 2 * In(0.7)
    S = {}

    def tb(name, x, y, w, h, text, size, bold=False):
        s = sl.shapes.add_textbox(x, y, w, h)
        s.name = name
        s.text_frame.word_wrap = True
        r = s.text_frame.paragraphs[0].add_run()
        r.text = text
        r.font.size = Pt(size)
        r.font.bold = bold
        S[name.split(".", 1)[1]] = s
        return s
    tb(f"s{n}.title", In(0.7), In(0.5), full, In(0.95), "Revenue grows 8% on pricing and mix", 24, True)
    if rule:
        c = sl.shapes.add_connector(CON.STRAIGHT, In(0.7), In(1.55), In(0.7) + full, In(1.55))
        c.name = f"s{n}.title_rule"
        S["title_rule"] = c
    c = sl.shapes.add_connector(CON.STRAIGHT, In(0.7), In(6.95), In(0.7) + full, In(6.95))
    c.name = f"s{n}.footer_rule"
    tb(f"s{n}.footer", In(0.7), In(7.02), In(8), In(0.3), "Gate deck", 10)
    if pagenum:
        tb(f"s{n}.page_number", W - In(0.7) - In(1.0), In(7.02), In(1.0), In(0.3), str(n) if pagenum == "n" else pagenum, 10)
    if eyebrow:
        tb(f"s{n}.label", In(0.7), In(0.18), In(3.0), In(0.3), "Market update", 10)
    return sl, S


def add_body(sl, S, n, text, *, size=14, color=None, h=0.8, name="body", y=2.15, x=0.7, w=None):
    _, RGB, CON, SHP, Emu, In, Pt = _pp()
    W = sl.part.package.presentation_part.presentation.slide_width
    s = sl.shapes.add_textbox(In(x), In(y), In(w) if w else W - 2 * In(0.7), In(h))
    s.name = f"s{n}.{name}"
    s.text_frame.word_wrap = True
    r = s.text_frame.paragraphs[0].add_run()
    r.text = text
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = RGB.from_string(color)
    S[name] = s
    return s


def add_panel(sl, S, n, x=0.7, y=3.5, w=3.0, h=1.5):
    _, RGB, CON, SHP, Emu, In, Pt = _pp()
    s = sl.shapes.add_shape(SHP.RECTANGLE, In(x), In(y), In(w), In(h))
    s.name = f"s{n}.panel"
    S["panel"] = s
    return s


def planted_deck():
    """(pptx bytes, expectations, clean-slide numbers). One planted defect per slide."""
    Presentation, RGB, CON, SHP, Emu, In, Pt = _pp()
    from lxml import etree as et
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    exp = []     # (slide, rule, {shape ids accepted} | None)
    n = 0

    def nxt(**kw):
        nonlocal n
        n += 1
        return n, *frame_slide(prs, n, **kw)
    n1, sl, S = nxt()
    add_body(sl, S, n1, "Pricing and mix drove the increase.")
    clean = [n1]
    n_, sl, S = nxt()
    add_body(sl, S, n_, "Pricing and mix drove the increase in net sales across every region we cover. " * 6, h=0.35)
    exp.append((n_, "overflow", {S["body"].shape_id}))
    n_, sl, S = nxt()
    a = add_body(sl, S, n_, "First block of text for the slide.", name="body.1", h=1.0)
    b = add_body(sl, S, n_, "Second block of text for the slide.", name="body.2", h=1.0, y=2.6)
    exp.append((n_, "overlap", {a.shape_id, b.shape_id}))
    n_, sl, S = nxt()
    add_body(sl, S, n_, "Pricing and mix drove the increase.", color="C7CCD4")
    exp.append((n_, "contrast", {S["body"].shape_id}))
    n_, sl, S = nxt()
    add_body(sl, S, n_, "Pricing and mix drove the increase.", size=8)
    exp.append((n_, "font_floor", {S["body"].shape_id}))
    n_, sl, S = nxt()
    add_body(sl, S, n_, "Revenue rose — margins held.")
    exp.append((n_, "punctuation", {S["body"].shape_id}))
    n_, sl, S = nxt()
    add_body(sl, S, n_, "We will leverage the platform across regions.")
    exp.append((n_, "banned_phrase", {S["body"].shape_id}))
    n_, sl, S = nxt(rule=False)
    add_body(sl, S, n_, "Pricing and mix drove the increase.")
    exp.append((n_, "house_title_rule", {S["title"].shape_id}))
    n_, sl, S = nxt(pagenum=None)
    add_body(sl, S, n_, "Pricing and mix drove the increase.")
    exp.append((n_, "house_footer", None))
    n_, sl, S = nxt(pagenum="99")
    add_body(sl, S, n_, "Pricing and mix drove the increase.")
    exp.append((n_, "house_footer", {S["page_number"].shape_id}))
    n_, sl, S = nxt(eyebrow=True)
    add_body(sl, S, n_, "Pricing and mix drove the increase.")
    exp.append((n_, "house_eyebrow", {S["label"].shape_id}))
    n_, sl, S = nxt()
    pn = add_panel(sl, S, n_)
    pn.fill.gradient()
    exp.append((n_, "slop_effects", {pn.shape_id}))
    n_, sl, S = nxt()
    pn = add_panel(sl, S, n_)
    pn.fill.solid()
    pn.fill.fore_color.rgb = RGB.from_string("0B1F33")
    sp = pn._element.spPr
    eff = et.SubElement(sp, f"{{{A}}}effectLst")
    et.SubElement(eff, f"{{{A}}}outerShdw", blurRad="50800", dist="38100", dir="2700000")
    exp.append((n_, "slop_effects", {pn.shape_id}))
    n_, sl, S = nxt()
    pn = add_panel(sl, S, n_)
    pn.fill.solid()
    pn.fill.fore_color.rgb = RGB.from_string("FF00FF")
    exp.append((n_, "theme_color", {pn.shape_id}))
    n_, sl, S = nxt()
    s = add_body(sl, S, n_, "Twelve point text.", size=12, h=1.5)
    for sz, t in ((14, "Fourteen point text."), (18, "Eighteen point text.")):
        pr = s.text_frame.add_paragraph()
        r = pr.add_run()
        r.text = t
        r.font.size = Pt(sz)
    exp.append((n_, "type_sizes", None))
    n_, sl, S = nxt()
    pn = add_panel(sl, S, n_, x=12.0, y=3.5, w=2.5, h=1.5)
    pn.fill.solid()
    pn.fill.fore_color.rgb = RGB.from_string("F2F3F5")
    exp.append((n_, "bounds", {pn.shape_id}))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), exp, clean


def clean_deck_bytes():
    Presentation, RGB, CON, SHP, Emu, In, Pt = _pp()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    for n in (1, 2):
        sl, S = frame_slide(prs, n)
        add_body(sl, S, n, "Pricing and mix drove the increase.")
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


@check("E1")
def e1():
    V = mod("om.deck.validate")
    data, exp, clean = planted_deck()
    rep = V.validate(data)
    fs = rep.findings
    miss = []
    for slide, rule, ids in exp:
        hit = [f for f in fs if f["slide"] == slide and f["rule"] == rule]
        if not hit:
            miss.append(f"s{slide} {rule}: not detected (got {[f['rule'] for f in fs if f['slide'] == slide]})")
        elif ids is not None and not any(f["shape_id"] in ids for f in hit):
            miss.append(f"s{slide} {rule}: wrong shape {[(f['shape_id'], f['shape_name']) for f in hit]} expected one of {sorted(ids)}")
    need(not miss, f"{len(miss)}/{len(exp)} planted defects mishandled: " + " | ".join(miss[:4]))
    cf = [f for f in fs if f["slide"] in clean]
    need(not cf, f"clean house-framed slide has findings: {[(f['rule'], f['message'][:50]) for f in cf]}")
    return f"{len(exp)} planted defects detected with the right rule and shape id; clean slide yields 0 findings"


@check("E2")
def e2():
    data, _, _ = planted_deck()
    bad, ok = TMP / "e2_defects.pptx", TMP / "e2_clean.pptx"
    bad.write_bytes(data)
    ok.write_bytes(clean_deck_bytes())
    script = str(ROOT / "scripts/validate_pptx.py")
    r1 = subprocess.run([sys.executable, script, str(bad)], capture_output=True, text=True, cwd=ROOT)
    r0 = subprocess.run([sys.executable, script, str(ok)], capture_output=True, text=True, cwd=ROOT)
    need(r1.returncode == 1, f"defect deck exit code {r1.returncode}, expected 1")
    need(r0.returncode == 0, f"clean deck exit code {r0.returncode}, expected 0: {r0.stdout[-200:]}")
    j1 = subprocess.run([sys.executable, script, str(bad), "--json"], capture_output=True, text=True, cwd=ROOT)
    j0 = subprocess.run([sys.executable, script, str(ok), "--json"], capture_output=True, text=True, cwd=ROOT)
    d1_, d0 = json.loads(j1.stdout), json.loads(j0.stdout)
    need(j1.returncode == 1 and d1_["ok"] is False and d1_["critical"] > 0 and d1_["findings"], "--json on the defect deck")
    need(j0.returncode == 0 and d0["ok"] is True and d0["critical"] == 0, "--json on the clean deck")
    return f"exit 1 on defect deck ({d1_['critical']} critical), 0 on clean deck, --json parses"


# ============================================================================================ F. Arabic / RTL
def arabic_decks():
    cs = []
    try:
        cs = [d for d in corpus() if d.lang == "ar" and d.data]
    except Fail:
        pass
    return cs + [fallback_ar()]


def rtl_problems(d: Deck):
    p = d.p
    bad, n_par, n_tbl, n_ch = [], 0, 0, 0
    for i, sp in enumerate(p.slides(), 1):
        root = p.xml(sp)
        for s in shapes_of(root):
            for ppr, t in paras_of(s["el"]):
                if not ARABIC.search(t):
                    continue
                n_par += 1
                algn = ppr.get("algn") if ppr is not None else None
                if ppr is None or ppr.get("rtl") != "1":
                    bad.append(f"{d.name} s{i} {s['name']}: Arabic paragraph without rtl=1")
                elif algn not in ("r", "ctr"):
                    bad.append(f"{d.name} s{i} {s['name']}: Arabic paragraph algn={algn!r}, not right/centre")
            if s["role"] == "title" and ARABIC.search(text_of(s["el"])):
                want = CANVAS_W - MARGIN - s["w"]
                if abs(s["x"] - want) > 0.02:
                    bad.append(f"{d.name} s{i} title x={s['x']:.2f}, mirrored LTR position is {want:.2f}")
            if s["tag"] == "graphicFrame" and s["el"].find(".//a:tbl", NS) is not None:
                n_tbl += 1
                tp = s["el"].find(".//a:tbl/a:tblPr", NS)
                if tp is None or tp.get("rtl") != "1":
                    bad.append(f"{d.name} s{i} {s['name']}: table without rtl=1")
        for nm, cp in slide_chart_parts(p, sp, root).items():
            c = p.xml(cp)
            bc = c.find(".//c:barChart", NS)
            if bc is None:
                continue
            n_ch += 1
            horizontal = bc.find("c:barDir", NS).get("val") == "bar"
            cat = c.find(".//c:catAx/c:scaling/c:orientation", NS)
            val = c.find(".//c:valAx/c:scaling/c:orientation", NS)
            if cat is None or cat.get("val") != "maxMin":
                bad.append(f"{d.name} s{i} {nm}: category axis not reversed (maxMin)")
            if horizontal and (val is None or val.get("val") != "maxMin"):
                bad.append(f"{d.name} s{i} {nm}: horizontal bar value axis not mirrored for RTL")
    return bad, n_par, n_tbl, n_ch


@check("F1")
def f1():
    ds = arabic_decks()
    allbad, tp, tt, tc = [], 0, 0, 0
    for d in ds:
        need_data(d)
        b, a, t, c = rtl_problems(d)
        allbad += b
        tp, tt, tc = tp + a, tt + t, tc + c
    need(tp > 0, "no Arabic paragraphs found in the Arabic decks")
    need(not allbad, f"{len(allbad)} RTL problems: " + " | ".join(allbad[:4]))
    return f"{len(ds)} Arabic decks: {tp} Arabic paragraphs rtl+right, titles mirrored, {tt} tables rtl, {tc} bar/column charts reversed"


@check("F2")
def f2():
    rx = re.compile("[ﭐ-﷿ﹰ-﻿]")
    ds = arabic_decks()
    n = 0
    for d in ds:
        need_data(d)
        for name, blob in d.p.parts.items():
            if name.endswith(".xml") and name.startswith(("ppt/slides/", "ppt/charts/", "ppt/notesSlides/")):
                n += 1
                m = rx.search(blob.decode("utf-8", "ignore"))
                need(not m, f"{d.name} {name}: presentation-form code point U+{ord(m.group(0)):04X}" if m else "")
    return f"{n} slide/chart XML parts of {len(ds)} Arabic decks: no presentation-form code points"


@check("F3")
def f3():
    ds = list(arabic_decks()) + [fallback_en()]
    for d in ds:
        need_data(d)
        th = d.p.theme_root()
        need(th is not None, f"{d.name}: no theme part")
        for tag in ("majorFont", "minorFont"):
            cs = th.find(f".//a:fontScheme/a:{tag}/a:cs", NS)
            need(cs is not None and cs.get("typeface"), f"{d.name}: theme {tag} has no cs font")
    return f"{len(ds)} decks: theme major and minor fonts both define a cs typeface"


# ============================================================================================ G. Theme, cloner, sync
EFFECT_TAGS = ("gradFill", "outerShdw", "sp3d", "scene3d")


def font_problems(d: Deck):
    p = d.p
    th = p.theme_root()
    names = set()
    for tag in ("majorFont", "minorFont"):
        for k in ("latin", "cs", "ea"):
            e = th.find(f".//a:fontScheme/a:{tag}/a:{k}", NS)
            if e is not None and e.get("typeface"):
                names.add(e.get("typeface"))
    bad, n = [], 0
    for name, blob in p.parts.items():
        if name.endswith(".xml") and name.startswith(("ppt/slides/slide", "ppt/charts/chart")):
            root = p.xml(name)
            for tag in ("latin", "cs", "ea", "sym"):
                for e in root.iter(f"{{{A}}}{tag}"):
                    tf = e.get("typeface")
                    n += 1
                    if tf and not tf.startswith(("+mj-", "+mn-")) and tf not in names:
                        bad.append(f"{d.name} {name}: {tf!r}")
    return bad, n


@check("G1")
def g1():
    ds, note = decks_or_fallback()
    fb, n = [], 0
    eff = []
    for d in ds:
        b, c = font_problems(d)
        fb += b
        n += c
        for name, blob in d.p.parts.items():
            if name.endswith(".xml") and not name.startswith("ppt/theme/"):
                txt = blob.decode("utf-8", "ignore")
                for t in EFFECT_TAGS:
                    if f"<a:{t}" in txt or f"<{t}" in txt:
                        eff.append(f"{d.name} {name}: {t}")
    need(not fb, f"{len(fb)} runs with non-theme fonts: {fb[:3]}")
    need(not eff, f"{len(eff)} banned effects in slides/charts/layouts/masters: {eff[:3]}")
    theme_fmt = sorted({t for d in ds[:1] for nme, blob in d.p.parts.items() if nme.startswith("ppt/theme/")
                        for t in EFFECT_TAGS if f"<a:{t}" in blob.decode("utf-8", "ignore")})
    extra = f"; theme fmtScheme still defines {theme_fmt} (unreferenced by any shape)" if theme_fmt else ""
    return f"{note}: {n} font refs are theme fonts; no {', '.join(EFFECT_TAGS)} in slides, charts, layouts or masters{extra}"


CLIENT = {"dk1": "1A1A2E", "lt1": "FFFFFF", "dk2": "7A1F3D", "lt2": "F4EDE4", "accent1": "C8102E", "accent2": "0F6E8C",
          "accent3": "5A6B7B", "accent4": "E8B4B8", "accent5": "2E7D32", "accent6": "B71C1C", "hlink": "0F6E8C", "folHlink": "5A6B7B"}


def make_potx(path: Path):
    Presentation, RGB, CON, SHP, Emu, In, Pt = _pp()
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    cs = root.find(".//a:clrScheme", NS)
    for ch in list(cs):
        cs.remove(ch)
    cs.set("name", "ClientCo")
    for slot, hexv in CLIENT.items():
        e = etree.SubElement(cs, f"{{{A}}}{slot}")
        etree.SubElement(e, f"{{{A}}}srgbClr").set("val", hexv)
    fs = root.find(".//a:fontScheme", NS)
    fs.set("name", "ClientCo")
    for tag, lat, csf in (("majorFont", "Georgia", "Times New Roman"), ("minorFont", "Verdana", "Tahoma")):
        f = fs.find(f"a:{tag}", NS)
        for ch in list(f):
            f.remove(ch)
        etree.SubElement(f, f"{{{A}}}latin").set("typeface", lat)
        etree.SubElement(f, f"{{{A}}}ea").set("typeface", "")
        etree.SubElement(f, f"{{{A}}}cs").set("typeface", csf)
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    lay = next(l for l in prs.slide_layouts if l.name == "Title and Content")
    for ph in lay.placeholders:
        t = str(ph.placeholder_format.type)
        if "TITLE" in t:
            ph.left, ph.top, ph.width, ph.height = In(1.0), In(0.9), In(11.3), In(1.1)
        elif "BODY" in t or "OBJECT" in t:
            ph.left, ph.top, ph.width, ph.height = In(1.0), In(2.4), In(11.3), In(3.9)
    buf = io.BytesIO()
    prs.save(buf)
    zin = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            blob = zin.read(it.filename)
            if it.filename == "[Content_Types].xml":
                blob = blob.replace(b"presentationml.presentation.main+xml", b"presentationml.template.main+xml")
            zout.writestr(it, blob)


def client_fixture():
    def go():
        HC = mod("om.deck.house_clone")
        pot = TMP / "client.potx"
        make_potx(pot)
        prof = HC.clone(str(pot))
        E = mod("om.deck.engine")
        sl = [slide_with_id(a, i + 1, s) for i, (a, s) in enumerate(valid_examples()[:10])]
        spec = deck_spec(sl, deck_id="client-10")
        t = time.perf_counter()
        rep = E.build(spec, out=str(OUT / "client10.pptx"), seed=3, profile=prof, template=str(pot))
        wall = time.perf_counter() - t
        return pot, prof, spec, rep, wall
    return cached("client", go)


@check("G2")
def g2():
    pot, prof, spec, rep, wall = client_fixture()
    th = prof.theme
    need(th.fonts["major"] == "Georgia" and th.fonts["minor"] == "Verdana", f"profile fonts {th.fonts}")
    need(th.fonts.get("major_cs") == "Times New Roman" and th.fonts.get("minor_cs") == "Tahoma", f"profile cs fonts {th.fonts}")
    for tok, slot in (("text", "dk1"), ("secondary", "dk2"), ("panel", "lt2"), ("accent", "accent1"), ("series2", "accent2")):
        need(th.colors[tok].upper() == "#" + CLIENT[slot], f"profile colour {tok} = {th.colors[tok]}, client {slot} = #{CLIENT[slot]}")
    g = prof.grid
    need(abs(g["title_y"] - 0.9) < 0.02 and abs(g["margin_x"] - 1.0) < 0.02 and abs(g["title_h"] - 1.1) < 0.02,
         f"profile grid did not take the client's title placeholder (title_y {g['title_y']}, margin_x {g['margin_x']}, title_h {g['title_h']})")
    need(rep.error == "" and rep.data, f"deck from client profile failed: {rep.error}")
    need(not crit_nonprov(rep.findings), f"deck built with the client profile has criticals: {[(f['rule'], f['slide']) for f in crit_nonprov(rep.findings)][:3]}")
    p = P(rep.data)
    thx = p.theme_root()
    need(thx.find(".//a:fontScheme/a:majorFont/a:latin", NS).get("typeface") == "Georgia", "built deck theme major font is not the client's Georgia")
    need(thx.find(".//a:fontScheme/a:minorFont/a:latin", NS).get("typeface") == "Verdana", "built deck theme minor font is not Verdana")
    need(thx.find(".//a:clrScheme/a:accent1/a:srgbClr", NS).get("val").upper() == CLIENT["accent1"], "built deck accent1 is not the client's")
    need(thx.find(".//a:clrScheme/a:dk2/a:srgbClr", NS).get("val").upper() == CLIENT["dk2"], "built deck dk2 is not the client's")
    d = Deck("client10", spec, rep.to_dict(), wall, str(OUT / "client10.pptx"), rep.data)
    fb, n = font_problems(d)
    need(not fb, f"non-theme fonts in client-branded deck: {fb[:3]}")
    V = mod("om.deck.validate")
    vr = V.validate(rep.data, theme=th)
    need(vr.critical == 0, f"validator finds {vr.critical} critical in the client-branded deck: {[(f['rule'], f['slide']) for f in vr.findings if f['severity'] == 'critical'][:3]}")
    return f"potx cloned (Georgia/Verdana, accent {th.colors['accent']}, title_y {g['title_y']}); branded deck uses them, 0 critical"


@check("L1")
def l1():
    pot, prof, spec, rep, wall = client_fixture()
    need(len(spec["slides"]) == 10, "fixture is not 10 slides")
    need(rep.error == "" and rep.slides == 10, f"branded 10-slide deck did not build: {rep.error} ({rep.slides} slides)")
    need(wall < 180, f"branded deck took {wall:.1f}s, limit 180s")
    return f"branded 10-slide deck built offline in {wall:.1f}s (limit 180s)"


def sync_fixture(bound_id="m-rev"):
    Mo, Rn, T = mod("om.deck.model"), mod("om.deck.render"), mod("om.deck.theme")
    from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
    ch = lambda vals: {"type": "column", "categories": ["FY24", "FY25", "FY26"], "series": [{"name": "Revenue", "values": vals}],
                       "number_format": "0", "labels": True}
    tbl = lambda r: {"columns": ["Metric", "FY26"], "rows": r, "col_align": ["l", "r"], "size": 14}
    kpi = lambda i, t, b: Element(f"s1.kpi.{i}", "text", "kpi", 6.7 + (i - 1) * 3.0, 3.8, 2.8, 1.0,
                                  text=TextSpec([Para([Run(t, True)])], 40, "major"), binding=b)
    s1 = SolvedSlide(1, "gate", [
        Element("s1.chart", "chart", "chart", 0.7, 1.0, 5.6, 2.6, chart=ch([100.0, 120.0, 150.0]),
                binding={"manifest_id": bound_id, "kind": "chart"}),
        Element("s1.chart.2", "chart", "chart", 6.7, 1.0, 5.9, 2.6, chart=ch([1.0, 2.0, 3.0])),
        Element("s1.table", "table", "table", 0.7, 3.8, 5.6, 1.6, table=tbl([["EBITDA", "$25"], ["Margin", "16.7%"]]),
                binding={"kind": "table", "bindings": {"0,1": "m-ebitda", "1,1": "m-margin"}, "header_rows": 1,
                         "format": {"0,1": "$#,##0", "1,1": "0.0%"}}),
        kpi(1, "12.5%", {"manifest_id": "m-kpi", "kind": "value", "format": "0.0%"}),
        kpi(2, "7.0x", None),
        Element("s1.table.2", "table", "table", 0.7, 5.6, 5.6, 1.2, table=tbl([["Cash", "$9"]])),
    ])
    s2 = SolvedSlide(2, "gate", [
        Element("s2.chart", "chart", "chart", 0.7, 1.0, 5.6, 2.6, chart=ch([5.0, 6.0, 7.0])),
        Element("s2.table", "table", "table", 6.7, 1.0, 5.6, 1.6, table=tbl([["Debt", "$44"]])),
        Element("s2.kpi.1", "text", "kpi", 0.7, 4.0, 3.0, 1.0, text=TextSpec([Para([Run("3.1x", True)])], 40, "major")),
    ])
    data = Rn.render([s1, s2], T.Theme.house(), title="sync")
    manifest = mod("om.contracts").ModelManifest.from_dict({"workbook_sha256": "a" * 64, "outputs": [
        {"id": i, "sheet": "Model", "ref": r, "units": u} for i, r, u in (
            ("m-rev", "B2:B4", "USD m"), ("m-ebitda", "C2", "USD m"), ("m-margin", "C3", "ratio"), ("m-kpi", "C4", "ratio"),
            ("m-unbound", "Z9", "x"))]})
    return data, manifest


def c14n(el):
    return etree.tostring(el, method="c14n")


@check("G3")
def g3():
    SY = mod("om.deck.sync")
    data, mf = sync_fixture()
    base = {"m-rev": [100.0, 120.0, 150.0], "m-ebitda": 25, "m-margin": 0.167, "m-kpi": 0.125, "m-unbound": 7.0}
    new = dict(base, **{"m-rev": [100.0, 120.0, 165.0], "m-ebitda": 31, "m-margin": 0.184, "m-kpi": 0.131})
    out, rep = SY.resync(data, mf, new)
    a, b = P(data), P(out)
    need(set(a.names) == set(b.names), f"part set changed: {sorted(set(a.names) ^ set(b.names))[:4]}")
    changed = sorted(n for n in a.names if a.parts[n] != b.parts[n])
    s1 = a.slides()[0]
    chart_part = slide_chart_parts(a, s1)["s1.chart"]
    crel = a.rels(chart_part)
    wb = [t for _, (ty, t) in crel.items() if ty.endswith("/package")]
    allowed = {s1, chart_part, *wb}
    stray = [n for n in changed if n not in allowed]
    need(not stray, f"parts changed that no bound shape owns: {stray}")
    need(s1 in changed and chart_part in changed, f"expected the bound slide and chart part to change, changed={changed}")
    # inside the changed slide part: only the bound shapes differ
    ra, rb = a.xml(s1), b.xml(s1)
    sa, sb = {s["name"]: s for s in shapes_of(ra)}, {s["name"]: s for s in shapes_of(rb)}
    diff = sorted(n for n in sa if c14n(sa[n]["el"]) != c14n(sb[n]["el"]))
    need(set(diff) <= {"s1.chart", "s1.table", "s1.kpi.1"} and {"s1.table", "s1.kpi.1"} <= set(diff), f"shapes whose XML changed: {diff}")
    ra2, rb2 = copy.deepcopy(ra), copy.deepcopy(rb)
    for r in (ra2, rb2):
        tree = r.find("p:cSld/p:spTree", NS)
        for ch in list(tree):
            nv = ch.find(".//p:cNvPr", NS)
            if nv is not None and nv.get("name") in diff:
                tree.remove(ch)
    need(c14n(ra2) == c14n(rb2), "slide XML outside the bound shapes changed")
    # new values present
    cs = chart_series(b.xml(chart_part))[0]["val"]
    need(series_eq(cs, [100.0, 120.0, 165.0]), f"chart cache after sync {cs}")
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(b.parts[wb[0]])).active
    nums = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float))]
    need(165 in nums and 150 not in nums, f"embedded chart workbook not refreshed: {nums}")
    tcell = {s["name"]: text_of(s["el"]) for s in shapes_of(rb)}
    need("$31" in tcell["s1.table"] and "18.4%" in tcell["s1.table"], f"table cells after sync: {tcell['s1.table']!r}")
    need("13.1%" in tcell["s1.kpi.1"], f"KPI after sync: {tcell['s1.kpi.1']!r}")
    need("$25" not in tcell["s1.table"], "old table value still present")
    # unbound mutation changes nothing
    out2, rep2 = SY.resync(data, mf, dict(base, **{"m-unbound": 999.0}))
    pb = P(out2)
    need(all(a.parts[n] == pb.parts[n] for n in a.names) and set(a.names) == set(pb.names), "mutating an unbound value changed the deck")
    # missing manifest id
    bad, _ = sync_fixture(bound_id="m-ghost")
    try:
        SY.resync(bad, mf, dict(base, **{"m-ghost": [1.0, 2.0, 3.0]}))
        raise Fail("a binding to a missing manifest id did not raise")
    except Fail:
        raise
    except Exception as e:  # noqa: BLE001
        need("m-ghost" in str(e) and "manifest" in str(e).lower(), f"unclear error for missing manifest id: {type(e).__name__}: {e}")
        err = f"{type(e).__name__}: {str(e)[:70]}"
    return f"only {len(changed)} parts changed ({', '.join(Path(n).name for n in changed)}), bound shapes {diff}; unbound mutation = no change; missing id -> {err}"


@check("L5")
def l5():
    SY, E = mod("om.deck.sync"), mod("om.deck.engine")
    sl = [slide_with_id("ranked_bar", 1), slide_with_id("kpi_row", 2)]
    mid = "m-peer-ev-ebitda"
    mf = mod("om.contracts").ModelManifest.from_dict({"workbook_sha256": "b" * 64, "outputs": [
        {"id": mid, "sheet": "Comps", "ref": "B2:B8", "units": "x"}]})
    rep = E.build(deck_spec(sl, deck_id="l5"), manifest=mf, out=str(OUT / "l5.pptx"), seed=2)
    need(rep.error == "" and rep.data, f"template deck failed: {rep.error}")
    p = P(rep.data)
    binds = json.loads(p.parts["acretia/bindings.json"]) if "acretia/bindings.json" in p.parts else {}
    need(any(b.get("manifest_id") == mid or mid in json.dumps(b) for b in binds.values()), f"no binding to {mid} written by the engine: {binds}")
    sp = p.slides()[0]
    part = slide_chart_parts(p, sp)["s1.chart"]
    old = chart_series(p.xml(part))[0]["val"]
    new = [round(v * 1.1, 3) for v in old]
    out, r = SY.resync(rep.data, mf, {mid: new})
    q = P(out)
    got = chart_series(q.xml(part))[0]["val"]
    need(series_eq(got, new), f"chart not refreshed from the model values: {got} vs {new}")
    other = [n for n in p.names if p.parts[n] != q.parts[n] and n != part and not n.startswith("ppt/embeddings/")]
    need(not other, f"unrelated parts changed on resync: {other}")
    return f"engine-built template slide re-synced: {len(new)} chart points refreshed with no LLM, only the chart part and its workbook changed"


# ============================================================================================ H. Critic loop
class FakeVLM:
    """Fake vision model: names a real shape id from the prompt. mode='live' so the engine/critic treat it as a live adapter."""
    mode = "live"

    def __init__(self, behaviour):
        self.behaviour, self.calls, self.per_slide = behaviour, 0, {}

    def chat(self, messages, *, json_schema=None, job_id=None, **kw):
        self.calls += 1
        text = messages[1]["content"][0]["text"]
        idx = int(re.search(r"Slide (\d+) \(archetype", text).group(1))
        ids = re.findall(r"^- (\S+) \[(\w+)\]", text, re.M)
        n = self.per_slide[idx] = self.per_slide.get(idx, 0) + 1
        tgt = next((i for r in ("body", "callout", "label") for i, ro in ids if ro == r), ids[0][0] if ids else "s1.title")
        if self.behaviour == "once" and n >= 2:
            data = {"ok": True, "score": 9, "issues": [], "patch": None}
        else:
            colour = "secondary" if n % 2 else "text"
            data = {"ok": False, "score": 5, "issues": [{"shape": tgt, "problem": "low emphasis", "severity": "minor"}],
                    "patch": {"slide_index": idx, "reason": "gate", "ops": [{"op": "set_style", "target": tgt, "args": {"color": colour}}]}}
        return SimpleNamespace(data=data, usage={}, cost_usd=0.0, text="")


def critic_slides(k=2):
    out = []
    A_, T, V, Rn = mod("om.deck.archetypes"), mod("om.deck.theme"), mod("om.deck.validate"), mod("om.deck.render")
    th = T.Theme.house()
    for aid, s in valid_examples():
        if aid not in ("exec_summary", "takeaway_box", "numbered_insights", "recommendation", "visual_text"):
            continue
        sl = A_.REGISTRY[aid].build(slide_with_id(aid, len(out) + 1, s), A_.BuildContext(th, len(out) + 1, k, "Gate deck"))
        out.append(sl)
        if len(out) == k:
            break
    need(len(out) == k, "could not build slides for the critic fixture")
    need(V.validate(Rn.render(out, th, title="t")).critical == 0, "critic fixture slides are not validator-clean")
    return out, th


@check("H1")
def h1():
    if not has_lo():
        raise Skip("LibreOffice/pdftoppm not installed: the critic cannot rasterize")
    C, V, Rn = mod("om.deck.critic"), mod("om.deck.validate"), mod("om.deck.render")
    slides, th = critic_slides(2)
    calls = {"n": 0}

    def counting(data, theme=None):
        calls["n"] += 1
        return V.validate(data, theme=theme)
    f1_ = FakeVLM("once")
    t = time.perf_counter()
    new, rep = C.loop(slides, th, adapter=f1_, title="t", validate=counting)
    need(rep["loops"] == 2 and rep["critic"] == "critic: ok", f"patch-then-ok run: loops={rep['loops']} status={rep['critic']}")
    need(rep["patches_applied"], f"no patch was applied: refused={rep['patches_refused']} dropped={rep['dropped']}")
    ids = {e.id for s in slides for e in s.elements}
    need(all(o["target"] in ids for ap in rep["patches_applied"] for o in ap["ops"]), "applied patch targets an id that is not on the slide")
    need(calls["n"] >= 2, f"validator ran {calls['n']}x; expected a re-validation after the patch")
    tgt = rep["patches_applied"][0]["ops"][0]["target"]
    before = next(e for s in slides for e in s.elements if e.id == tgt)
    after = next(e for s in new for e in s.elements if e.id == tgt)
    need(after.text.color == "secondary" and before.text.color != "secondary", f"patch not visible in the slide ({before.text.color} -> {after.text.color})")
    f2_ = FakeVLM("always")
    new2, rep2 = C.loop(slides, th, adapter=f2_, title="t")
    need(rep2["loops"] == 3 and f2_.calls == 3 * len(slides), f"always-complaining critic: loops={rep2['loops']} calls={f2_.calls}, expected 3 loops / {3 * len(slides)} calls")
    need("max loops" in rep2["critic"], f"status {rep2['critic']!r}")
    return f"patch applied + re-validated ({calls['n']} validations), stops ok at 2 loops; always-complain stops at exactly 3 loops ({time.perf_counter() - t:.0f}s)"


@check("H2")
def h2():
    C, V, Rn = mod("om.deck.critic"), mod("om.deck.validate"), mod("om.deck.render")
    slides, th = critic_slides(2)
    s = copy.deepcopy(slides[0])
    body = next(e for e in s.elements if e.role in ("body", "callout", "label"))
    body.x = 14.5          # planted: shape outside the slide -> validator critical
    pre = V.validate(Rn.render([s, slides[1]], th, title="t"))
    need(pre.critical > 0, "fixture invalid: the validator did not see the planted critical")
    fake = FakeVLM("always")
    _, rep = C.loop([s, slides[1]], th, adapter=fake, title="t")
    need(fake.calls == 0, f"critic was called {fake.calls}x although the validator reported a critical finding")
    need(rep["critic"].startswith("critic: skipped"), f"critic status {rep['critic']!r}")
    return f"validator critical ({pre.findings[0]['rule']}) -> critic not called ({rep['critic']})"


@check("H3")
def h3():
    E = mod("om.deck.engine")
    n0 = ATT["n"]
    sl = [slide_with_id("cover", 1), slide_with_id("quote", 2), slide_with_id("section_divider", 3)]
    d = build_deck("h3", deck_spec(sl, deck_id="h3"), adapter=None)
    need(d.r["ok"] or not d.r["error"], f"build failed: {d.r['error']}")
    need("not run live" in d.r["critic"], f"critic recorded {d.r['critic']!r}, expected 'critic: not run live'")
    from src.harness.adapter import Adapter
    ad = Adapter(mode="replay", api_key="gate-key")
    d2 = build_deck("h3b", deck_spec(sl, deck_id="h3b"), adapter=ad)
    need(not d2.r["error"] and "not run live" in d2.r["critic"], f"replay-mode adapter: error={d2.r['error']!r} critic={d2.r['critic']!r}")
    need(ATT["n"] == n0, f"{ATT['n'] - n0} socket attempts during replay builds")
    return "replay builds (no adapter, and an Adapter in replay mode) finish with 'critic: not run live', 0 sockets opened"


# ============================================================================================ I. Creative visual layer
def visual_spec():
    sl = [slide_with_id("cover", 1), slide_with_id("visual_text", 2), slide_with_id("ranked_bar", 3), slide_with_id("section_divider", 4),
          slide_with_id("quote", 5), slide_with_id("waterfall", 6), slide_with_id("kpi_row", 7)]
    sl[0]["visual"] = {"concept": "carve-out of a payments unit", "kind": "hero"}
    sl[1]["visual"] = {"concept": "digital onboarding for SMEs", "kind": "illustration"}
    sl[3]["visual"] = {"concept": "valuation and returns", "kind": "illustration"}
    sl[4]["visual"] = {"concept": "customer voice", "kind": "illustration"}
    return deck_spec(sl, deck_id="gate-visual")


@check("I1")
def i1():
    Pr = mod("om.deck.visuals.probe")
    from src.harness.adapter import Adapter
    n0 = ATT["n"]
    st = Pr.image_endpoint(offline=True, force=True)
    need(st["available"] is False and st["reason"], f"offline probe: {st}")
    st2 = Pr.image_endpoint(adapter=Adapter(mode="replay", api_key="gate-key"), force=True)
    need(st2["available"] is False and "replay" in st2["reason"].lower(), f"replay probe: {st2}")
    d = build_deck("i1", visual_spec())
    ip = d.r["image_probe"]
    need(ip and ip.get("available") is False and ip.get("reason"), f"build report image_probe: {ip}")
    need("image_probe" in d.r["timings"], "the probe step did not run on this build")
    d2 = build_deck("i1b", visual_spec(), adapter=Adapter(mode="replay", api_key="gate-key"))
    need(d2.r["image_probe"].get("available") is False, "replay build did not record the unavailable probe")
    need(ATT["n"] == n0, f"{ATT['n'] - n0} sockets opened by the probe/builds")
    return f"probe unavailable offline ({ip['reason'][:40]!r}), recorded in the build report, 0 sockets"


def visual_problems(d: Deck):
    bad, n = [], 0
    media = {hashlib.sha256(b).hexdigest() for nme, b in d.p.parts.items() if nme.startswith("ppt/media/")}
    for v in d.r.get("visuals", []):
        n += 1
        cands = v.get("candidates", [])
        ids = [c["id"] for c in cands]
        if len(cands) < 3:
            bad.append(f"{d.name} slide {v.get('slide')}: {len(cands)} candidates")
        if v["kept"]["id"] not in ids:
            bad.append(f"{d.name} slide {v.get('slide')}: kept id not among candidates")
        if not all(isinstance(c.get("scores"), dict) and c["scores"] for c in cands):
            bad.append(f"{d.name} slide {v.get('slide')}: candidate scores missing")
        if v["kept"].get("png_sha256") and media and v["kept"]["png_sha256"] not in media:
            # the kept image may legitimately not be placed by the archetype; only flag when the slide has a picture
            sp = d.p.slides()[v["slide"] - 1] if v.get("slide") else None
            if sp and any(s["tag"] == "pic" for s in shapes_of(d.p.xml(sp))):
                bad.append(f"{d.name} slide {v.get('slide')}: kept PNG hash is not the picture on the slide")
    return bad, n


@check("I2")
def i2():
    ds, note = decks_or_fallback()
    ds = list(ds)
    if note.startswith("corpus absent"):
        ds.append(cached("vis_deck", lambda: build_deck("visual", visual_spec())))
    bad, n = [], 0
    for d in ds:
        need_data(d)
        b, c = visual_problems(d)
        bad += b
        n += c
    need(n > 0, f"{note}: no non-data visuals recorded in any build report")
    need(not bad, f"{len(bad)} visual-selection problems: " + "; ".join(bad[:3]))
    return f"{note}: {n} visuals, each chosen from >= 3 scored candidates, kept id listed"


@check("I3")
def i3():
    A_ = mod("om.deck.archetypes")
    ds = corpus()
    var, arts, consec = [], set(), []
    for d in ds:
        need_data(d)
        var += [f"{d.name}:{f['rule']}" for f in d.r["findings"] if f["rule"] in ("variety", "templated")]
        if d.r.get("art_direction"):
            arts.add(d.r["art_direction"])
        sl = d.spec["slides"]
        for a, b in zip(sl, sl[1:]):
            if a["archetype"] == b["archetype"] and A_.REGISTRY[a["archetype"]].visual_type == A_.REGISTRY[b["archetype"]].visual_type:
                consec.append(f"{d.name}:{a['id']}->{b['id']}")
    need(not var, f"{len(var)} variety/templated findings: {var[:3]}")
    need(len(arts) >= 6, f"only {len(arts)} distinct art directions across the corpus: {sorted(arts)}")
    need(not consec, f"consecutive slides share archetype + visual type: {consec[:3]}")
    return f"0 variety/templated findings, {len(arts)} art directions, no consecutive repeats in 20 decks"


@check("I4")
def i4():
    sl = [slide_with_id("kpi_row", i + 1) for i in range(10)]
    for i, s in enumerate(sl):
        s["title"] = f"Unit economics improved on measure number {i + 1} in FY26"
    d = build_deck("i4_rubber", deck_spec(sl, deck_id="i4"))
    t = [f for f in d.r["findings"] if f["rule"] == "templated"]
    need(t, f"a 10-slide rubber-stamp deck (same archetype and layout) was not flagged 'templated'; rules seen {sorted({f['rule'] for f in d.r['findings']})}")
    return f"rubber-stamp deck flagged: {t[0]['message'][:80]}"


@check("I5")
def i5():
    L = mod("om.deck.visuals.log")
    p = L.default_path()
    need(str(p).startswith(str(TMP)), f"style log path {p} is outside the temp ACRETIA_DATA")
    before = len(L.read())
    d = build_deck("i5", visual_spec(), seed=5)
    rows = [r for r in L.read()[before:] if r.get("deck_id") == d.spec["deck_id"]]
    n_vis = len(d.r["visuals"])
    need(n_vis > 0, "no visuals were produced")
    need(len(rows) == n_vis, f"{len(rows)} style-log rows for {n_vis} kept visuals")
    kept = {v["kept"]["id"] for v in d.r["visuals"]}
    need({r["candidate_id"] for r in rows} == kept, "style-log candidate ids differ from the kept visuals")
    need(all(isinstance(r.get("scores"), dict) and r["scores"] for r in rows), "style-log rows without scores")
    need(len(L.read()) == before + n_vis, "style log grew by a different amount than the kept visuals")
    return f"{n_vis} kept visuals -> {len(rows)} rows appended to {p.name} with scores"


@check("I6")
def i6():
    a = build_deck("i6_a", visual_spec(), seed=11)
    b = build_deck("i6_b", visual_spec(), seed=12)
    for d in (a, b):
        need(not d.r["error"] and d.data, f"{d.name}: {d.r['error']}")
    ha = {v["id"]: v["kept"]["png_sha256"] for v in a.r["visuals"]}
    hb = {v["id"]: v["kept"]["png_sha256"] for v in b.r["visuals"]}
    need(ha and set(ha) == set(hb), "visual slide sets differ")
    same = [k for k in ha if ha[k] == hb[k]]
    need(not same, f"visuals identical across seeds for slides {same}")
    need(a.r["numbers_digest"] == b.r["numbers_digest"], "numbers_digest differs between seeds")
    ca = {n: a.p.parts[n] for n in a.p.names if n.startswith("ppt/charts/chart")}
    cb = {n: b.p.parts[n] for n in b.p.names if n.startswith("ppt/charts/chart")}
    need(ca and ca == cb, "chart XML differs between seeds")
    return f"{len(ha)} visuals differ across seeds; numbers_digest and {len(ca)} chart parts identical"


# ============================================================================================ J. Hygiene
SDK = {"openai", "anthropic", "mistralai", "cohere", "litellm", "groq", "boto3", "together"}
NETLIB = {"requests", "httpx", "aiohttp", "urllib3", "http.client", "urllib.request"}


@check("J1")
def j1():
    bad = []
    n = 0
    for f in sorted((ROOT / "om/deck").rglob("*.py")):
        n += 1
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for nm in names:
                if nm.split(".")[0] in SDK or nm.startswith(("google.generativeai", "google.genai")) or nm in NETLIB:
                    bad.append(f"{f.relative_to(ROOT)}:{node.lineno} imports {nm}")
    need(not bad, f"provider SDK / raw network imports under om/deck: {bad[:4]}")
    crit = (ROOT / "om/deck/critic.py").read_text()
    need("src.harness.adapter" in crit, "critic.py does not go through src/harness/adapter.py")
    return f"{n} files under om/deck: no provider SDK or raw HTTP imports; critic uses the adapter"


@check("J2")
def j2():
    p = ROOT / "scorecard.csv"
    need(p.exists(), "scorecard.csv missing")
    rows = [r for r in csv.DictReader(p.open(encoding="utf-8")) if (r.get("stage") or "").strip() == "S3"]
    need(rows, "scorecard.csv has no S3 rows (corpus/eval packet not landed)")
    bs = briefs()
    names = [b["name"] for b in bs] + [b["spec"].get("deck_id", "") for b in bs]
    per = {}
    models = {}
    bad = []
    for r in rows:
        blob = " ".join(str(v) for v in r.values()).lower()
        bn = next((b["name"] for b in bs if b["name"].lower() in blob or str(b["spec"].get("deck_id", "")).lower() in blob), None)
        m = re.search(r"model[=:]\s*([\w.\-:/]+)", blob)
        model = m.group(1) if m else (r.get("eval", "").split(":")[-1] if ":" in r.get("eval", "") else "?")
        if bn is None:
            bad.append(f"row for no brief: {r.get('eval')}")
            continue
        key = (bn, model)
        per[key] = per.get(key, 0) + 1
        models.setdefault(bn, set()).add(model)
        notes = (r.get("notes") or "").lower()
        score = (r.get("score") or "").strip()
        if "not run live" in blob:
            if re.search(r"\d", score):
                bad.append(f"{bn}/{model}: numeric score {score!r} in a 'not run live' row")
            if re.search(r"score\s*[=:]\s*\d", notes):
                bad.append(f"{bn}/{model}: numeric score in notes of a 'not run live' row")
        for kw in ("critical", "major", "variety", "build"):
            if kw not in notes:
                bad.append(f"{bn}/{model}: offline metric '{kw}' missing from notes")
                break
    dup = [k for k, v in per.items() if v > 1]
    need(not dup, f"duplicate (brief, model) rows: {dup[:3]}")
    missing = [b["name"] for b in bs if b["name"] not in models]
    need(not missing, f"briefs without an S3 scorecard row: {missing[:4]}")
    need(not bad, f"{len(bad)} scorecard problems: " + "; ".join(bad[:3]))
    return f"{len(rows)} S3 rows cover 20 briefs; 'not run live' rows carry no score; offline metrics filled"


@check("J3")
def j3():
    pk = importlib.import_module("om.deck")
    import pkgutil
    bad, n = [], 0
    for m in pkgutil.walk_packages(pk.__path__, "om.deck."):
        n += 1
        try:
            importlib.import_module(m.name)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{m.name}: {type(e).__name__}: {str(e)[:60]}")
    need(not bad, f"{len(bad)} modules fail to import: {bad[:3]}")
    return f"{n} om.deck modules import cleanly"


# ============================================================================================ K. North-star metrics
def reliability_specs():
    def go():
        if not RELI.is_dir():
            raise Fail("corpus missing: evals/decks/reliability/ does not exist")
        gen = RELI / "generate.py"
        specs = []
        if gen.exists():
            sys.path.insert(0, str(RELI))
            try:
                sp = importlib.util.spec_from_file_location("reliability_generate", gen)
                m = importlib.util.module_from_spec(sp)
                sp.loader.exec_module(m)
                specs = list(m.specs(n=100))
            finally:
                sys.path.remove(str(RELI))
        else:
            S = mod("om.deck.spec")
            files = sorted(p for p in RELI.iterdir() if p.suffix.lower() in (".json", ".yaml", ".yml"))
            specs = [{k: v for k, v in S.load(f).items() if k != "ghost"} for f in files]
        if len(specs) < 100:
            raise Fail(f"corpus missing: reliability generator/specs yield {len(specs)} < 100 specs")
        return specs
    return cached("reli_specs", go)


def reliability_run():
    def go():
        E = mod("om.deck.engine")
        res = []
        for i, sp in enumerate(reliability_specs()):
            sp = {k: v for k, v in sp.items() if k != "ghost"}
            t = time.perf_counter()
            try:
                rep = E.build(sp, out=None, seed=1000 + i)
                r = rep.to_dict()
            except Exception as e:  # noqa: BLE001
                r = {"error": f"{type(e).__name__}: {e}", "findings": [], "job": {}, "timings": {}, "total_seconds": 0.0, "slides": 0}
            wall = time.perf_counter() - t
            res.append({"i": i, "spec": sp, "r": r, "wall": wall, "n": len(sp.get("slides", [])), "lang": sp.get("lang", "en")})
        return res
    return cached("reli_run", go)


@check("K1")
def k1():
    specs = reliability_specs()
    text = [json.dumps(s, ensure_ascii=False).lower() for s in specs]
    cats = {"US GAAP": ("us gaap", "u.s. gaap"), "IFRS": ("ifrs",),
            "MENA": ("saudi", "uae", "egypt", "riyadh", "dubai", "cairo", "abu dhabi", "kuwait", "qatar", "tadawul", "egx", "adx", "dfm", "mena", "oman", "bahrain", "jordan", "morocco"),
            "pitchbook": ("pitchbook", "pitch book"), "IC deck": ("investment committee", "ic deck", " ic "), "earnings recap": ("earnings",),
            "market entry": ("market entry", "market-entry"), "carve-out": ("carve-out", "carve out", "carveout")}
    cnt = {k: sum(any(t in s for t in toks) for s in text) for k, toks in cats.items()}
    miss = [k for k, v in cnt.items() if v == 0]
    ar = sum(1 for s in specs if s.get("lang") == "ar")
    need(len(specs) >= 100, f"{len(specs)} specs")
    need(ar >= 3, f"only {ar} Arabic specs")
    need(not miss, f"reliability specs lack variety: no spec mentions {miss}")
    res = reliability_run()
    good = [x for x in res if not x["r"].get("error") and not crit_nonprov(x["r"]["findings"])]
    rate = len(good) / len(res)
    bad = [f"#{x['i']}: {x['r'].get('error') or crit_nonprov(x['r']['findings'])[0]['message']}"[:90] for x in res if x not in good]
    need(rate >= 0.97, f"success rate {rate:.1%} < 97%: {bad[:3]}")
    return f"{len(res)} specs built offline, success {rate:.1%} (>= 97%), {ar} Arabic; coverage {cnt}"


@check("K2")
def k2():
    ds = corpus()
    n = 0
    bad = []
    for d in ds:
        u = [f for f in d.r.get("findings", []) if f["rule"] == "unsourced_number"]
        n += len(u)
        if u:
            bad.append(f"{d.name}: {u[0]['shape_name']}")
    res = reliability_run()
    for x in res:
        u = [f for f in x["r"].get("findings", []) if f["rule"] == "unsourced_number"]
        n += len(u)
        if u:
            bad.append(f"reliability #{x['i']}: {u[0]['shape_name']}")
    need(n == 0, f"{n} unsourced_number findings in {len(bad)} decks: {bad[:4]}")
    return f"0 unsourced_number findings across 20 corpus decks and {len(res)} reliability decks"


@check("K3")
def k3():
    bs = briefs()
    withv = [b for b in bs if any(s.get("visual", {}).get("kind", "none") not in ("none", None) and s.get("visual", {}).get("concept") for s in b["spec"]["slides"])]
    pick = (withv + [b for b in bs if b not in withv])[:5]
    need(len(pick) == 5, "fewer than 5 corpus briefs to sample")
    n_vis = 0
    for b in pick:
        x = build_deck(f"k3a_{b['name']}", b["spec"], seed=21, save=False)
        y = build_deck(f"k3b_{b['name']}", b["spec"], seed=22, save=False)
        need(x.r["numbers_digest"] and x.r["numbers_digest"] == y.r["numbers_digest"], f"{b['name']}: numbers_digest differs between seeds")
        ha = sorted(v["kept"]["png_sha256"] for v in x.r["visuals"])
        hb = sorted(v["kept"]["png_sha256"] for v in y.r["visuals"])
        if ha:
            n_vis += len(ha)
            need(ha != hb, f"{b['name']}: kept visuals identical across seeds")
    need(n_vis > 0, "none of the 5 sampled briefs has a generated visual, so visual variation cannot be shown")
    return f"5 sampled briefs: identical numbers_digest across seeds, kept visuals ({n_vis}) differ"


@check("K4")
def k4():
    res = reliability_run()
    ten = [x for x in res if x["n"] == 10] or res
    ts = sorted(x["r"].get("total_seconds") or x["wall"] for x in ten)
    p50, p90 = statistics.median(ts), ts[min(len(ts) - 1, math.ceil(0.9 * len(ts)) - 1)]
    need(p50 < 300, f"p50 {p50:.1f}s >= 300s")
    bad = []
    pool = [(f"rel#{x['i']}", x["r"]) for x in res] + [(d.name, d.r) for d in corpus()]
    for nm, r in pool:
        job = r.get("job") or {}
        steps = job.get("steps") or []
        if not steps or not all("ms" in (s.get("detail") or "") for s in steps):
            bad.append(f"{nm}: job steps lack timings")
        elif "tokens" not in job or "cost_usd" not in job:
            bad.append(f"{nm}: job lacks tokens/cost_usd")
        elif job["cost_usd"] != 0 or job["tokens"] != 0:
            bad.append(f"{nm}: offline job reports tokens={job['tokens']} cost={job['cost_usd']}")
        elif not r.get("timings") or "cost_usd" not in r or "tokens" not in r:
            bad.append(f"{nm}: report lacks timings/tokens/cost_usd")
    need(not bad, f"{len(bad)} reports without per-step timing/tokens/cost: {bad[:3]}")
    return f"p50 {p50:.1f}s p90 {p90:.1f}s over {len(ten)} decks (limit 300s); {len(pool)} jobs carry per-step ms, tokens, cost_usd=0"


def _refs(node, slide=None, out=None):
    out = out if out is not None else []
    if isinstance(node, dict):
        sl = node.get("slide", slide)
        if isinstance(sl, str) and sl.isdigit():
            sl = int(sl)
        sid = node.get("shape_id", node.get("shape"))
        if sid is not None and not isinstance(sid, (dict, list)):
            out.append((sl, sid))
        for k, v in node.items():
            ks = None
            if isinstance(k, str):
                m = re.fullmatch(r"(?:slide[ _-]?)?(\d+)", k, re.I)
                ks = int(m.group(1)) if m else None
            _refs(v, ks if ks is not None else sl, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, slide, out)
    return out


@check("K5")
def k5():
    need(EDITS.is_dir(), "corpus missing: evals/decks/edits/ does not exist")
    ds = corpus()
    bad, total = [], 0
    for d in ds:
        need_data(d)
        did = d.spec.get("deck_id", d.name)
        f = EDITS / f"{did}.json"
        if not f.exists():
            f = EDITS / f"{d.name}.json"
        if not f.exists():
            bad.append(f"{did}: no edits file")
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            bad.append(f"{did}: invalid JSON ({e})")
            continue
        refs = _refs(doc)
        total += len(refs)
        valid = {}
        for i, sp in enumerate(d.p.slides(), 1):
            sh = shapes_of(d.p.xml(sp))
            valid[i] = {str(s["id"]) for s in sh} | {s["name"] for s in sh}
        for sl, sid in refs:
            if sl not in valid or str(sid) not in valid[sl]:
                bad.append(f"{did}: slide {sl} has no shape {sid!r}")
        if not doc:
            bad.append(f"{did}: empty edits file")
    need(not bad, f"{len(bad)} edits-file problems: " + "; ".join(bad[:4]))
    return f"20 edits files present, {total} shape references all valid for their slide"


# ============================================================================================ L. Parity items
def _find_bytes(res):
    if isinstance(res, (bytes, bytearray)):
        return bytes(res)
    if isinstance(res, str) and res.lower().endswith((".pptx", ".potx")) and Path(res).exists():
        return Path(res).read_bytes()
    if isinstance(res, (tuple, list)):
        for x in res:
            b = _find_bytes(x)
            if b:
                return b
    if isinstance(res, dict):
        for k in ("pptx", "data", "bytes", "deck", "path", "out"):
            if k in res:
                b = _find_bytes(res[k])
                if b:
                    return b
    for k in ("data", "pptx", "bytes", "path"):
        if hasattr(res, k):
            b = _find_bytes(getattr(res, k))
            if b:
                return b
    return None


def flex_call(fn, **avail):
    """Call fn with the keyword arguments its signature names; Fail with the signature when one cannot be bound."""
    sig = inspect.signature(fn)
    kw, missing = {}, []
    for n, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if n in avail:
            kw[n] = avail[n]
        elif p.default is p.empty:
            missing.append(n)
    if missing:
        raise Fail(f"API mismatch: cannot bind {missing} of {fn.__module__}.{fn.__name__}{sig}; gate script needs updating")
    return fn(**kw)


def pick_fn(m, patterns):
    for pat in patterns:
        for n in dir(m):
            if not n.startswith("_") and re.fullmatch(pat, n) and callable(getattr(m, n)):
                return getattr(m, n)
    raise Fail(f"API missing: no function matching {patterns} in {m.__name__} (has {[n for n in dir(m) if not n.startswith('_')][:12]})")


def own_parts(p: P, slide_part):
    """Parts owned by a slide: its xml, rels, notes, charts, embedded workbooks, media."""
    own = {slide_part, posixpath.join(posixpath.dirname(slide_part), "_rels", posixpath.basename(slide_part) + ".rels")}
    stack = [slide_part]
    while stack:
        part = stack.pop()
        for _, (ty, tgt) in p.rels(part).items():
            if tgt in own or not tgt.startswith("ppt/"):
                continue
            if any(k in ty for k in ("/slideLayout", "/slideMaster", "/theme")):
                continue
            own.add(tgt)
            rp = posixpath.join(posixpath.dirname(tgt), "_rels", posixpath.basename(tgt) + ".rels")
            if rp in p.parts:
                own.add(rp)
            stack.append(tgt)
    return own


def revise_base():
    sl = [slide_with_id(a, i + 1, s) for i, (a, s) in enumerate([x for x in valid_examples() if x[0] in (
        "cover", "ranked_bar", "waterfall", "comparison_table", "exec_summary", "stacked_bar")])]
    spec = deck_spec(sl, deck_id="l2-base")
    d = build_deck("l2_base", spec, seed=4)
    need(d.data and not d.r["error"], f"base deck for revision failed: {d.r['error']}")
    return d, sl


def _other_slides_identical(a: P, b: P, k_idx):
    sa, sb = a.slides(), b.slides()
    need(len(sa) == len(sb), f"slide count changed {len(sa)} -> {len(sb)}")
    need(a.parts["ppt/presentation.xml"] is not None, "")
    own_k = own_parts(a, sa[k_idx])
    bad = []
    for i, part in enumerate(sa):
        if i == k_idx:
            continue
        for n in own_parts(a, part) - own_k:
            if n not in b.parts:
                # parts may be renumbered by the saver: compare by position through rels instead
                bad.append(f"{n}: missing after revision")
            elif a.parts[n] != b.parts[n]:
                bad.append(f"{n}: bytes changed")
    return bad


@check("L2")
def l2():
    R = mod("om.deck.revise")
    d, sl = revise_base()
    k = 2
    new_slide = copy.deepcopy(d.spec["slides"][k])
    new_slide["title"] = "EBITDA grows $32m as price and savings outweigh cost inflation, revised"
    out, info = R.revise_slide(d.data, d.spec, d.spec["slides"][k]["id"], new_slide)
    a, b = d.p, P(out)
    bad = _other_slides_identical(a, b, k)
    need(not bad, f"{len(bad)} parts of other slides changed: {bad[:4]}")
    tb = "\n".join(text_of(s["el"]) for s in shapes_of(b.xml(b.slides()[k])))
    need("revised" in tb, "the revised slide does not carry the spec change")
    need(a.parts[a.slides()[k]] != b.parts[b.slides()[k]], "revised slide part is unchanged")
    for i in range(len(a.slides())):
        if i != k:
            need(a.parts[a.slides()[i]] == b.parts[b.slides()[i]], f"slide {i + 1} part differs")
    return f"revise_slide: slide {k + 1} re-rendered; every other slide part, rels, media and chart part byte-identical"


@check("L3")
def l3():
    R, V = mod("om.deck.revise"), mod("om.deck.versions")
    d, sl = revise_base()
    k, sh = None, []
    for i, sp in enumerate(d.p.slides()):
        sh = [s for s in shapes_of(d.p.xml(sp)) if s["role"] == "body" and len(text_of(s["el"]).split()) >= 6]
        if sh:
            k = i
            break
    need(sh, "no annotatable body shape in the base deck")
    ann = [{"slide": k + 1, "shape": sh[0]["name"], "comment": "Shorten this to 4 words"},
           {"slide": 99, "shape": "s99.body", "comment": "anything"}]
    out, rep = R.annotate(d.data, d.spec, ann)
    st = [a["status"] for a in rep["annotations"]]
    need(st[0] == "applied" and st[1] == "rejected", f"annotation statuses {st}")
    need(rep["slides_changed"] == [k + 1], f"slides_changed {rep['slides_changed']}")
    bad = _other_slides_identical(d.p, P(out), k)
    need(not bad, f"bulk annotation changed unannotated slides: {bad[:3]}")
    need(out != d.data, "annotated deck is unchanged")
    did = "gate-l3"
    n1 = V.save(did, d.data, d.spec, note="base")
    n2 = V.save(did, out, rep["spec"], note="round 1", annotations=ann)
    lst = V.list(did)
    need([r["version"] for r in lst] == [n1, n2], f"version list {[r['version'] for r in lst]}")
    need(lst[1]["annotations"] and lst[1]["annotations"][0]["comment"] == ann[0]["comment"], "round not saved with its annotations")
    return "bulk annotation round applied in place (1 applied, 1 rejected), saved as version 2 with its annotations"


@check("L4")
def l4():
    R, V = mod("om.deck.revise"), mod("om.deck.versions")
    d, sl = revise_base()
    k = 1
    new_slide = copy.deepcopy(d.spec["slides"][k])
    new_slide["title"] = "Acme trades at the lowest EV/EBITDA multiple in its peer set, revised"
    out, info = R.revise_slide(d.data, d.spec, d.spec["slides"][k]["id"], new_slide)
    did = "gate-l4"
    n1 = V.save(did, d.data, d.spec)
    n2 = V.save(did, out, info["spec"], note="edit")
    cmp_ = V.compare(did, n1, n2)
    need(cmp_["changed_slides"] == [k + 1], f"compare changed_slides {cmp_['changed_slides']}")
    need(cmp_["changed_shapes"].get(k + 1), f"compare lists no changed shapes: {cmp_['changed_shapes']}")
    rb = V.rollback(did, n1)
    need(hashlib.sha256(rb).hexdigest() == hashlib.sha256(d.data).hexdigest() and rb == d.data, "rollback bytes differ from version 1")
    need(V.get(did, n1) == d.data, "stored version 1 bytes differ")
    return f"compare lists slide {k + 1} + shapes {cmp_['changed_shapes'][k + 1][:2]}; rollback restores exact bytes of v{n1}"


@check("L6")
def l6():
    ds, note = decks_or_fallback()
    n_tbl, bad = 0, []
    for d in ds:
        need_data(d)
        for i, sp in enumerate(d.p.slides(), 1):
            for s in shapes_of(d.p.xml(sp)):
                is_tbl = s["tag"] == "graphicFrame" and s["el"].find(".//a:tbl", NS) is not None
                n_tbl += is_tbl
                if s["role"] == "table" and not is_tbl:
                    bad.append(f"{d.name} s{i} {s['name']}: role table but tag {s['tag']}")
                if s["tag"] == "pic" and s["role"] not in ("visual", "cover", "divider", "decor", None):
                    bad.append(f"{d.name} s{i} {s['name']}: picture with role {s['role']}")
                if s["tag"] == "pic" and re.search(r"table", s["el"].find(".//p:cNvPr", NS).get("descr", "") + s["name"], re.I):
                    bad.append(f"{d.name} s{i} {s['name']}: picture of a table")
    need(n_tbl > 0, f"{note}: no native tables found at all")
    need(not bad, f"{len(bad)} table problems: {bad[:3]}")
    return f"{note}: {n_tbl} tables, all native a:tbl graphicFrames, no pictures of tables"


@check("L7")
def l7():
    spec = {}
    try:
        ds = [d for d in corpus() if d.data]
        note = f"{len(ds)} corpus decks"
    except Fail:
        s = slide_with_id("ranked_bar", 1)
        s["sources"] = ["FactSet consensus, 31 October 2026", "Company filings, FY25 annual reports"]
        s["source"] = "FactSet consensus; company filings"
        s["blocks"]["takeaway"] = "Acme trades 2.3x below the peer median [1], on filings that reconcile [2]"
        ds = [build_deck("l7", deck_spec([s], deck_id="l7"))]
        note = "corpus absent: 1 gate-built deck with a two-source slide"
        need(ds[0].data, f"gate-built citation deck failed: {ds[0].r['error'][:120]}")
    n_cited, bad = 0, []
    A_ = mod("om.deck.archetypes")
    for d in ds:
        for i, (sp, ss) in enumerate(zip(d.p.slides(), d.spec["slides"]), 1):
            srcs = ss.get("sources") or []
            if not srcs and not (A_.REGISTRY.get(ss["archetype"]) and A_.REGISTRY[ss["archetype"]].data):
                continue
            sh = shapes_of(d.p.xml(sp))
            src_txt = " ".join(text_of(s["el"]) for s in sh if s["role"] == "source")
            listed = {int(x) for x in re.findall(r"\[(\d+)\]", src_txt)}
            body_txt = " ".join(text_of(s["el"]) for s in sh if s["role"] not in ("source", "footer", "page_number"))
            marks = {int(x) for x in re.findall(r"\[(\d+)\]", body_txt)}
            if srcs:
                n_cited += 1
                if listed != set(range(1, len(srcs) + 1)):
                    bad.append(f"{d.name} s{i}: source line lists {sorted(listed)}, spec has {len(srcs)} sources")
                if not marks:
                    bad.append(f"{d.name} s{i}: no inline [n] marker in text/cells")
            unresolved = marks - listed
            if unresolved:
                bad.append(f"{d.name} s{i}: markers {sorted(unresolved)} not in the source line")
    need(n_cited > 0, f"{note}: no data slide with multiple sources to check")
    need(not bad, f"{len(bad)} citation problems: {bad[:3]}")
    return f"{note}: {n_cited} cited data slides, every [n] marker resolves to a source in the footer line"


# ============================================================================================ J4 (last): no network
@check("J4")
def j4():
    need(ATT["n"] == 0, f"{ATT['n']} socket attempts during the run; first: {ATT['first'][-200:]}")
    return "0 socket attempts across the whole gate run"


# ============================================================================================ runner
def selected(cid, only):
    if not only:
        return True
    return any(cid == t or (len(t) == 1 and cid.startswith(t)) for t in only)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="", help="comma list of groups or ids, e.g. A,C3,K")
    ap.add_argument("--json", default="", help="write machine-readable results to this path")
    a = ap.parse_args(argv)
    only = [t.strip().upper() for t in a.only.split(",") if t.strip()]
    results = []
    t_all = time.perf_counter()
    print(f"verify_s3: offline gate, ACRETIA_LLM_MODE=replay, temp data {TMP}")
    for cid, fn in REG:
        if not selected(cid, only):
            continue
        t0 = time.perf_counter()
        try:
            ev = fn() or ""
            st = "PASS"
        except Skip as e:
            st, ev = "SKIP", str(e)
        except Fail as e:
            st, ev = "FAIL", str(e)
        except Exception as e:  # noqa: BLE001
            st, ev = "FAIL", f"{type(e).__name__}: {e}"
            if os.environ.get("VERIFY_DEBUG"):
                traceback.print_exc()
        dt = time.perf_counter() - t0
        ev = " ".join(str(ev).split())[:400]
        print(f"{st} {cid} {ev} [{dt:.1f}s]", flush=True)
        results.append({"id": cid, "status": st, "evidence": ev, "seconds": round(dt, 2)})
    n = {s: sum(1 for r in results if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    print(f"SUMMARY: {n['PASS']} PASS, {n['FAIL']} FAIL, {n['SKIP']} SKIP in {time.perf_counter() - t_all:.0f}s")
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": n, "results": results}, indent=2), encoding="utf-8")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
