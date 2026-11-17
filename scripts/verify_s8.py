#!/usr/bin/env python3
"""S8 gate: international annual-report reading (docs/s8/gate-spec.md, assertions G0-G12).

Written from the Boss's gate spec by a worker who has not seen the implementers' tests. Expected values are derived
here (hand arithmetic, the fixture manifest's ground truth, our own adversarial tables), never from the code under test.

    python3 scripts/verify_s8.py [--only G4,G6] [--json] [--clean-machine]

* One function per assertion, each returning (status, detail) with status PASS / FAIL / SKIP.
* A module or file that is not built yet is a FAIL ("not built yet: <module>"), never a crash and never a PASS.
* Sockets are blocked for the whole run (monkeypatched to raise); no model call is made. tesseract, pdftoppm and
  pdftotext run as subprocesses.
* Exit 0 only when nothing FAILs and no assertion of the never-skippable set (G0-G7, G9, G10) is skipped.
* A full run writes docs/s8/gate-report.md (a partial --only run does not).
"""
from __future__ import annotations

import argparse
import ast
import copy
import csv
import difflib
import hashlib
import importlib
import io
import json
import os
import random
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SPEC = os.path.join(ROOT, "docs", "s8", "gate-spec.md")
REPORT = os.path.join(ROOT, "docs", "s8", "gate-report.md")
FIXDIR = os.path.join(ROOT, "tests", "fixtures", "intl")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
ANCHORS = ["SWDY", "EAST", "TMGH", "2280", "4190", "2010", "EMAAR", "ADNOCDIST", "ALDAR"]
NEVER_SKIP_GROUPS = {"G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G9", "G10"}


# ------------------------------------------------------------------------------------------------ framework
class NotBuilt(Exception):
    pass


class Skip(Exception):
    pass


GATES: dict = {}


def gate(gid, title=""):
    def deco(fn):
        GATES[gid] = dict(fn=fn, name=fn.__name__, title=title or (fn.__doc__ or "").strip().split("\n")[0])
        return fn
    return deco


def need(modname):
    try:
        return importlib.import_module(modname)
    except ModuleNotFoundError as e:
        if e.name and (modname == e.name or modname.startswith(e.name + ".")):
            raise NotBuilt(f"not built yet: {modname}")
        raise


def need_attr(modname, attr):
    m = need(modname)
    if not hasattr(m, attr):
        raise NotBuilt(f"not built yet: {modname}.{attr}")
    return getattr(m, attr)


def need_file(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        raise NotBuilt(f"not built yet: {rel}")
    return p


def rel(p):
    return os.path.relpath(p, ROOT)


def jl(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError as e:
                    raise AssertionError(f"{rel(path)}:{n} is not valid JSON ({e})")
    return out


def jget(rec, *names, default=None):
    for n in names:
        if n in rec and rec[n] not in (None, ""):
            return rec[n]
    return default


def fail(msg):
    raise AssertionError(msg)


def short(items, n=6):
    items = list(items)
    s = "; ".join(str(i) for i in items[:n])
    return s + (f" (+{len(items) - n} more)" if len(items) > n else "")


def pyfiles(*globs_roots, exclude=()):
    out = []
    for r in globs_roots:
        base = os.path.join(ROOT, r)
        if os.path.isfile(base):
            out.append(base)
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
            for f in fn:
                if f.endswith(".py"):
                    p = os.path.join(dp, f)
                    if not any(x in p for x in exclude):
                        out.append(p)
    return sorted(out)


def intl_connector_files():
    base = os.path.join(ROOT, "src", "harness")
    out = []
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.startswith("intl_") and f.endswith(".py"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def s8_code_files():
    return sorted(set(pyfiles("om/intl") + intl_connector_files()))


def parse_py(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def imports_of(tree):
    """[(module dotted name, lineno)] for every import (relative imports omitted)."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.append((n.module, n.lineno))
            out += [(f"{n.module}.{a.name}", n.lineno) for a in n.names]
    return out


# ------------------------------------------------------------------------------------------------ fixtures
_MAN = {}


def manifest():
    if "m" not in _MAN:
        need_file(rel(MANIFEST))
        with open(MANIFEST, encoding="utf-8") as fh:
            _MAN["m"] = json.load(fh)
    return _MAN["m"]


def fixtures():
    return manifest()["fixtures"]


def fx_path(e):
    return os.path.join(FIXDIR, e["file"])


def native_fixtures():
    return [e for e in fixtures() if e["kind"] == "native"]


def find_fx(pred, what):
    for e in fixtures():
        if pred(e):
            return e
    raise AssertionError(f"no fixture in the manifest matches: {what}")


def tol_units(e, n=0.5):
    """n x the printed unit, in reporting-currency millions."""
    return n * float(e["unit_scale"]) / 1e6


_EX = {}


def extracted(e):
    if e["file"] not in _EX:
        ext = need_attr("om.intl.extract", "extract")
        _EX[e["file"]] = ext(fx_path(e), company=e.get("company"))
    return _EX[e["file"]]


def fresh(e):
    return copy.deepcopy(extracted(e))


def truth_by(e):
    d = {}
    for t in e["ground_truth"]:
        d.setdefault((t["key"], t["period_end"]), []).append(t)
    return d


def iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def figs_for(ex, key, period, statement=None):
    return [i for i, f in enumerate(ex.figures)
            if f.key == key and iso(f.period_end) == period and (statement is None or f.statement == statement)]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def pdfinfo_pages(path):
    r = run(["pdfinfo", path])
    m = re.search(r"Pages:\s+(\d+)", r.stdout)
    return int(m.group(1)) if m else None


_EAST = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٬٫", "01234567890123456789,.")


def digits_only(s):
    return re.sub(r"\D", "", str(s).translate(_EAST))


def canon_token(s):
    return re.sub(r"\s+", "", str(s).translate(_EAST))


PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_ok(x):
    if isinstance(x, str) and os.path.exists(x):
        with open(x, "rb") as fh:
            x = fh.read()
    return isinstance(x, (bytes, bytearray)) and bytes(x[:8]) == PNG_SIG and len(x) > 100


STATUS: dict = {}


# ================================================================================================ G0 anchors
def anchor_dir(t):
    base = os.path.join(ROOT, "evals", "intl", "anchors")
    if os.path.isdir(base):
        for d in os.listdir(base):
            if d.lower() == t.lower():
                return os.path.join(base, d)
    raise NotBuilt(f"not built yet: evals/intl/anchors/{t}/")


def _load_sources(t):
    p = os.path.join(anchor_dir(t), "sources.json")
    if not os.path.exists(p):
        raise NotBuilt(f"not built yet: {rel(p)}")
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    return d["sources"] if isinstance(d, dict) and "sources" in d else d


def _doc_kind(s):
    k = str(jget(s, "doc_type", "type", "kind", default="")).lower()
    if "annual" in k:
        return "annual"
    if any(w in k for w in ("release", "earnings", "presentation", "quarter", "interim", "results")):
        return "release"
    return "other"


def _per_anchor(check):
    bad, ok = [], 0
    for t in ANCHORS:
        try:
            check(t)
            ok += 1
        except NotBuilt as e:
            bad.append(f"{t}: {e}")
        except AssertionError as e:
            bad.append(f"{t}: {e}")
    if bad:
        fail(f"{len(bad)}/{len(ANCHORS)} anchors fail: " + short(bad, 9))
    return "PASS", f"{ok}/{len(ANCHORS)} anchors"


@gate("G0.1", "anchor sources.json")
def g0_1_sources():
    def chk(t):
        src = _load_sources(t)
        ann = [s for s in src if _doc_kind(s) == "annual"]
        rel_ = [s for s in src if _doc_kind(s) == "release"]
        if len(ann) < 2:
            fail(f"{len(ann)} annual statements (<2)")
        if len(rel_) < 1:
            fail("no quarterly earnings release / investor presentation")
        for s in ann + rel_:
            if not str(s.get("url", "")).startswith("http"):
                fail("missing url")
            if not re.fullmatch(r"[0-9a-f]{64}", str(s.get("sha256", ""))):
                fail(f"bad sha256 for {s.get('url')}")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(jget(s, "retrieved", "retrieved_at", "retrieval_date", default=""))):
                fail(f"missing retrieval date for {s.get('url')}")
            if "committed" not in s:
                fail("missing committed flag")
            if s["committed"] and not str(s.get("terms_url", "")).startswith("http"):
                fail("committed:true without terms URL")
    return _per_anchor(chk)


def _norm_stmt(s):
    s = str(s or "").upper()
    for k in ("IS", "BS", "CF"):
        if s == k:
            return k
    if s.startswith("INCOME") or s.startswith("P&L") or s.startswith("PROFIT"):
        return "IS"
    if s.startswith("BALANCE") or s.startswith("FINANCIAL POSITION"):
        return "BS"
    if s.startswith("CASH"):
        return "CF"
    return s


def _bbox_ok(b):
    return (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)
            and all(0 <= v <= 1 for v in b) and b[0] < b[2] and b[1] < b[3])


def _unit_scale(unit):
    u = str(unit or "").lower()
    return 1e6 if "million" in u or "مليون" in u else 1e3 if "thousand" in u or "'000" in u or "ألف" in u else 1.0


@gate("G0.2", "anchor figures.jsonl: full IS/BS/CF + ties")
def g0_2_figures():
    def chk(t):
        src = _load_sources(t)
        ann = [s for s in src if _doc_kind(s) == "annual"]
        p = os.path.join(anchor_dir(t), "figures.jsonl")
        if not os.path.exists(p):
            raise NotBuilt(f"not built yet: {rel(p)}")
        recs = jl(p)
        for s in ann[:2]:
            sha = s["sha256"]
            mine = [r for r in recs if str(jget(r, "doc_sha256", "doc_id", "sha256", "doc", default="")) and
                    (sha.startswith(str(jget(r, "doc_sha256", "doc_id", "sha256", "doc"))[:12]) or
                     str(jget(r, "doc_sha256", "doc_id", "sha256", "doc")).startswith(sha[:12]))]
            if not mine:
                fail(f"no figures for doc {sha[:12]} (need doc_sha256/doc_id on each record)")
            for st in ("IS", "BS", "CF"):
                n = sum(1 for r in mine if _norm_stmt(jget(r, "statement", "stmt")) == st)
                if n < 8:
                    fail(f"doc {sha[:12]}: only {n} {st} lines (every printed line is required)")
            for r in mine:
                if not isinstance(r.get("page"), int) or r["page"] < 1:
                    fail(f"record without page: {short([str(r)[:80]], 1)}")
                if not _bbox_ok(jget(r, "bbox_norm", "bbox")):
                    fail(f"bad bbox on {r.get('label') or r.get('key')} p.{r.get('page')}")
                c = r.get("confidence")
                if not isinstance(c, (int, float)) or not 0 <= c <= 1:
                    fail("confidence missing or outside [0,1]")
                if r.get("key") is None and not r.get("label"):
                    fail("unmapped line without its printed label")
            scale = _unit_scale(s.get("unit"))
            reviewed = any(str(r.get("status", "")) == "review" and r.get("reasons") for r in mine)
            by = {}
            for r in mine:
                v = r.get("value")
                if r.get("key") and isinstance(v, (int, float)):
                    by.setdefault(str(jget(r, "period_end", "period", default="")), {}).setdefault(
                        (_norm_stmt(jget(r, "statement", "stmt")), r["key"]), v)
            if not by:
                fail(f"doc {sha[:12]}: no numeric mapped figures")
            for per, d in by.items():
                tol = 3.0 * scale / 1e6
                flat = {k[1]: v for k, v in d.items()}
                problems = []
                a = flat.get("assets")
                le = flat.get("liabilities_equity")
                if le is None and flat.get("liabilities") is not None and flat.get("equity_total") is not None:
                    le = flat["liabilities"] + flat["equity_total"]
                if a is None or le is None:
                    problems.append("BS balance not evaluable")
                elif abs(a - le) > tol:
                    problems.append(f"BS does not balance ({a} vs {le})")
                cf = [flat.get(k) for k in ("cfo", "cfi", "cff")]
                if None in cf:
                    problems.append("CF sections missing")
                else:
                    end, beg = flat.get("x.cash_end"), flat.get("x.cash_beginning")
                    nc = flat.get("net_change_cash")
                    fx = flat.get("x.fx_effect_cash") or 0.0
                    target = nc if nc is not None else (end - beg if end is not None and beg is not None else None)
                    if target is None:
                        problems.append("CF change in cash not evaluable")
                    elif abs(sum(cf) + fx - target) > tol:
                        problems.append(f"CF does not tie to change in cash ({sum(cf) + fx} vs {target})")
                ni_is = d.get(("IS", "net_income"))
                ni_cf = d.get(("CF", "net_income"), d.get(("CF", "cf_net_income")))
                if ni_is is None or ni_cf is None:
                    problems.append("IS/CF net income not evaluable")
                elif abs(ni_is - ni_cf) > tol:
                    problems.append("IS and CF net income differ")
                if problems and not reviewed:
                    fail(f"doc {sha[:12]} {per}: {'; '.join(problems)} and no review item explains it")
    return _per_anchor(chk)


CATEGORIES = {"adjusted_vs_reported", "segment_vs_group", "restatement", "rounding", "period_mismatch", "definition"}


@gate("G0.3", "earnings-release reconciliation")
def g0_3_release_recon():
    def chk(t):
        p = os.path.join(anchor_dir(t), "release_recon.jsonl")
        if not os.path.exists(p):
            raise NotBuilt(f"not built yet: {rel(p)}")
        recs = jl(p)
        if not recs:
            fail("empty")
        text = " ".join(str(jget(r, "metric", "headline", "label", "key", default="")).lower() for r in recs)
        for need_, alts in (("revenue", ("revenue", "sales")), ("EBITDA or operating profit", ("ebitda", "operating profit", "ebit")),
                            ("net profit", ("net profit", "net income", "profit for"))):
            if not any(a in text for a in alts):
                fail(f"no reconciled {need_}")
        for r in recs:
            cites = [k for k, v in r.items() if "cit" in k.lower() and v]
            if len(cites) < 2:
                fail(f"{jget(r, 'metric', 'label', 'key')}: needs both a release and a statements citation")
            d = jget(r, "difference", "diff", "delta", default=None)
            if d is None:
                fail(f"{jget(r, 'metric', 'label', 'key')}: no difference recorded")
            if abs(float(d)) > 0:
                if r.get("category") not in CATEGORIES:
                    fail(f"{jget(r, 'metric', 'label', 'key')}: difference {d} without a valid category")
                ex = str(jget(r, "explanation", "reason", "note", default="")).strip()
                if len(ex.split()) < 4:
                    fail(f"{jget(r, 'metric', 'label', 'key')}: difference {d} without a one-sentence explanation")
    return _per_anchor(chk)


GUIDE_SECTIONS = [("framework", ["framework", "standards"]), ("layout quirks", ["layout", "quirk"]),
                  ("non-standard lines", ["non-standard", "nonstandard", "non standard"]), ("zakat or tax", ["zakat", "tax"]),
                  ("IFRS 16", ["ifrs 16", "lease"]), ("FX/devaluation", ["fx", "devaluation", "currency", "exchange"]),
                  ("related parties", ["related part"]), ("units", ["unit"]), ("fiscal year", ["fiscal", "financial year", "year end", "year-end"])]


@gate("G0.4", "how-to-read notes per company")
def g0_4_company_notes():
    def chk(t):
        p = os.path.join(ROOT, "om", "intl", "companies", f"{t}.md")
        if not os.path.exists(p):
            raise NotBuilt(f"not built yet: {rel(p)}")
        lines = open(p, encoding="utf-8").read().split("\n")
        heads = [(i, len(m.group(1)), m.group(2).lower()) for i, l in enumerate(lines) if (m := re.match(r"^(#+)\s+(.*)", l))]
        miss = []
        for name, kws in GUIDE_SECTIONS:
            found = False
            for j, (i, lvl, title) in enumerate(heads):
                if any(k in title for k in kws):
                    end = next((i2 for i2, l2, _ in heads[j + 1:] if l2 <= lvl), len(lines))
                    body = "\n".join(lines[i:end])
                    if re.search(r"\b(?:pp?\.|pages?)\s*\d+", body, re.I):
                        found = True
                        break
            if not found:
                miss.append(name)
        if miss:
            fail("sections missing or without a page citation: " + ", ".join(miss))
    return _per_anchor(chk)


NUM_RX = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _numbers_in(obj, acc):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        acc.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _numbers_in(v, acc)


@gate("G0.5", "analyst Q&A with citations")
def g0_5_qa():
    def chk(t):
        d = anchor_dir(t)
        p = os.path.join(d, "qa.jsonl")
        if not os.path.exists(p):
            raise NotBuilt(f"not built yet: {rel(p)}")
        qa = jl(p)
        if len(qa) != 10:
            fail(f"{len(qa)} questions (need 10)")
        known = []
        for fn in ("figures.jsonl", "release_recon.jsonl"):
            fp = os.path.join(d, fn)
            if os.path.exists(fp):
                for r in jl(fp):
                    _numbers_in(r, known)
        for q in qa:
            ans = str(q.get("answer", ""))
            if not ans.strip():
                fail(f"{q.get('id')}: empty answer")
            cites = q.get("citations") or q.get("citation") or []
            if isinstance(cites, dict):
                cites = [cites]
            if not cites:
                fail(f"{q.get('id')}: no citation")
            good = False
            for c in cites:
                c = c if isinstance(c, dict) else {"figure_id": c}
                if c.get("figure_id") or c.get("figure") or (jget(c, "doc_sha256", "sha256", "doc_id") and c.get("page") is not None
                                                           and jget(c, "bbox_norm", "bbox")):
                    good = True
            if not good:
                fail(f"{q.get('id')}: citation lacks doc sha256 + page + bbox (or a figure id)")
            for m in NUM_RX.finditer(re.sub(r"\b(?:p|pp|page|pages|Q|H|FY)\.?\s*\d+", " ", ans)):
                tok = m.group(0)
                v = float(tok.replace(",", ""))
                if 1900 <= v <= 2100 and "," not in tok and "." not in tok:
                    continue
                dec = len(tok.split(".")[1]) if "." in tok else 0
                eps = 0.5 * 10 ** -dec + 1e-9
                if not any(abs(v - k) <= eps or abs(v - k * 1e3) <= eps * 1e3 or abs(v - k / 1e3) <= eps / 1e3 for k in known):
                    fail(f"{q.get('id')}: number {tok} not found in figures.jsonl or the release")
    return _per_anchor(chk)


# ================================================================================================ G1 licences
STDLIB = set(sys.stdlib_module_names)
LOCAL_TOP = {"om", "src", "scripts", "tests", "harness", "connectors", "intl"}
LEDGER = os.path.join(ROOT, "license-and-repo-ledger.csv")
MOD_TO_LEDGER = {"yaml": ["pyyaml"], "PIL": ["pillow"], "cv2": ["opencv"], "bs4": ["beautifulsoup", "bs4"],
                 "dateutil": ["dateutil"], "lxml": ["lxml"], "numpy": ["numpy"], "fitz": ["pymupdf"],
                 "docling": ["docling"], "pypdf": ["pypdf"], "pdfplumber": ["pdfplumber"]}
GPL_PKGS = {"fitz", "pymupdf", "mupdf", "ghostscript", "pdfminer_gpl", "pyqt5", "pyqt6", "pyside2", "gnupg", "mysql"}
PROVIDER_SDKS = {"anthropic", "openai", "google.generativeai", "google.genai", "vertexai", "mistralai", "cohere", "litellm",
                 "groq", "ollama", "together", "replicate", "boto3", "bedrock", "langchain", "llama_index", "deepseek"}
OCR_WRAPPERS = {"pytesseract", "tesserocr"}
NET_MODULES = {"urllib.request", "http.client", "socket", "requests", "httpx", "urllib3", "aiohttp", "ftplib", "http.server"}


def ledger_rows():
    need_file(rel(LEDGER))
    with open(LEDGER, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _row_ok(r):
    return (re.fullmatch(r"[0-9a-f]{40}", (r.get("commit_hash") or "").strip().lower()) is not None
            and (r.get("license") or "").strip() and (r.get("decision") or "").strip())


def third_party_imports():
    mods = {}
    for p in s8_code_files():
        for name, ln in imports_of(parse_py(p)):
            top = name.split(".")[0]
            if top in STDLIB or top in LOCAL_TOP or top == "__future__":
                continue
            mods.setdefault(top, []).append(f"{rel(p)}:{ln}")
    return mods


@gate("G1.1", "ledger rows for every third-party tool")
def g1_1_ledger():
    rows = ledger_rows()
    need_ = {"tesseract": ["tesseract-ocr/tesseract"], "tessdata (ara/eng traineddata)": ["tessdata"]}
    bad = []
    for label, keys in need_.items():
        hit = [r for r in rows if any(k in r["repo"].lower() for k in keys)]
        if not hit:
            bad.append(f"no ledger row for {label}")
        elif not any(_row_ok(r) for r in hit):
            bad.append(f"{label}: row lacks 40-hex commit / licence / decision")
    for top, where in sorted(third_party_imports().items()):
        keys = [k.lower() for k in MOD_TO_LEDGER.get(top, [top.lower()])]
        hit = [r for r in rows if any(k in r["repo"].lower() for k in keys)]
        if not hit or not any(_row_ok(r) for r in hit):
            bad.append(f"import '{top}' ({where[0]}) has no complete ledger row")
    if bad:
        fail(short(bad, 8))
    return "PASS", "tesseract, traineddata and every third-party import have 40-hex ledger rows"


@gate("G1.2", "no GPL/AGPL, provider SDK or PyMuPDF imports")
def g1_2_forbidden_imports():
    files = s8_code_files()
    if not files:
        raise NotBuilt("not built yet: om/intl/")
    rows = ledger_rows()
    bad = []
    for p in files:
        for name, ln in imports_of(parse_py(p)):
            top = name.split(".")[0]
            low = name.lower()
            if top.lower() in GPL_PKGS or low in GPL_PKGS:
                bad.append(f"{rel(p)}:{ln} imports GPL/AGPL package {name}")
            if any(low == s or low.startswith(s + ".") for s in PROVIDER_SDKS):
                bad.append(f"{rel(p)}:{ln} imports provider SDK {name}")
    for top, where in third_party_imports().items():
        for r in rows:
            if any(k.lower() in r["repo"].lower() for k in MOD_TO_LEDGER.get(top, [top])):
                lic = r["license"].upper()
                if re.search(r"(?<!L)GPL", lic) and "LGPL" not in lic:
                    bad.append(f"{top} ({where[0]}): ledger licence {r['license']}")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(files)} files scanned (AST)"


@gate("G1.3", "tesseract only as a subprocess")
def g1_3_tesseract_subprocess():
    files = s8_code_files()
    if not files:
        raise NotBuilt("not built yet: om/intl/")
    bad = []
    for p in files:
        for name, ln in imports_of(parse_py(p)):
            if name.split(".")[0] in OCR_WRAPPERS:
                bad.append(f"{rel(p)}:{ln} imports {name}")
    ocr = os.path.join(ROOT, "om", "intl", "ocr.py")
    if not os.path.exists(ocr):
        raise NotBuilt("not built yet: om.intl.ocr")
    src = open(ocr, encoding="utf-8").read()
    if "subprocess" not in src or "tesseract" not in src:
        bad.append("om/intl/ocr.py does not call tesseract through subprocess")
    if re.search(r"shell\s*=\s*True", src):
        bad.append("om/intl/ocr.py uses shell=True")
    if bad:
        fail(short(bad))
    return "PASS", "no pytesseract/tesserocr; ocr.py shells out"


@gate("G1.4", "no network modules in om/intl outside sources/")
def g1_4_no_network_imports():
    files = [p for p in pyfiles("om/intl") if os.sep + os.path.join("intl", "sources") + os.sep not in p]
    if not files:
        raise NotBuilt("not built yet: om/intl/")
    bad = []
    for p in files:
        for name, ln in imports_of(parse_py(p)):
            if name in NET_MODULES or name.split(".")[0] in {"requests", "httpx", "urllib3", "aiohttp", "socket"}:
                bad.append(f"{rel(p)}:{ln} imports {name}")
    if bad:
        fail(short(bad))
    return "PASS", f"{len(files)} modules scanned"


# ================================================================================================ G2 standards KB
def _kb():
    return need_attr("om.intl.standards", "load")()


def _walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from _walk_strings(v)


@gate("G2.1", "7 frameworks load")
def g2_1_frameworks():
    kb = _kb()
    ids = {re.sub(r"[^a-z0-9]", "", str(k).lower()) for k in kb.frameworks}
    req = {"IFRS": ["ifrs"], "EAS": ["eas"], "SOCPA-IFRS": ["socpaifrs", "socpa"], "GCC/UAE IFRS": ["uaeifrs", "gccifrs", "gcc"],
           "UK FRS 102": ["frs102", "ukfrs102"], "Ind AS": ["indas"], "US GAAP": ["usgaap"]}
    miss = [n for n, alts in req.items() if not any(i == a or (a not in ("ifrs", "eas") and a in i) for i in ids for a in alts)]
    if miss or len(kb.frameworks) < 7:
        fail(f"missing {miss}; loaded {sorted(kb.frameworks)}")
    return "PASS", f"{len(kb.frameworks)} frameworks: {', '.join(sorted(kb.frameworks))}"


@gate("G2.2", "statement layout and required line items")
def g2_2_layout():
    kb = _kb()
    bad = []
    for k, f in kb.frameworks.items():
        pres = f.get("presentation") or {}
        for field in ("pnl_layout", "balance_sheet_order", "oci", "required_line_items"):
            if not pres.get(field):
                bad.append(f"{k}.presentation.{field}")
    if bad:
        fail("missing: " + short(bad, 10))
    return "PASS", f"{len(kb.frameworks)} frameworks with P&L layout, current/non-current order, OCI, required lines"


TOPIC_ALIASES = {
    "leases": ["leases", "lease"], "revenue": ["revenue"], "inventory (LIFO)": ["inventory", "inventories"],
    "development costs": ["development_costs", "development"], "revaluation": ["revaluation"],
    "impairment reversal": ["impairment_reversal", "impairment"], "borrowing costs": ["borrowing_costs", "borrowing"],
    "associates/JVs": ["associates_jvs", "associates"], "IAS 29": ["hyperinflation", "ias29"],
    "IAS 21 devaluation": ["fx_devaluation", "devaluation"], "zakat vs income tax": ["zakat_tax", "zakat"],
    "end-of-service benefits": ["end_of_service", "eosb"], "government grants": ["government_grants", "grants"],
    "EAS-IFRS mapping": ["eas_ifrs_mapping", "eas_mapping"]}


@gate("G2.3", "required topics present")
def g2_3_topics():
    kb = _kb()
    by_topic = {}
    for d in kb.differences:
        by_topic.setdefault(str(d.get("topic", "")).lower(), []).append(d)
    miss = [n for n, al in TOPIC_ALIASES.items() if not any(a in by_topic for a in al)]
    blob = json.dumps(kb.differences, ensure_ascii=False).lower()
    for token in ("asc 842", "eas 49", "ifrs 16", "eas 47", "eas 48"):
        if token not in blob:
            miss.append(f"text mentioning '{token}'")
    lifo = "lifo" in blob
    if not lifo:
        miss.append("LIFO")
    if miss:
        fail("missing: " + short(miss, 10))
    return "PASS", f"{len(kb.differences)} difference entries across {len(by_topic)} topics"


@gate("G2.4", "citations and adjustment recipes")
def g2_4_citations_recipes():
    kb = _kb()
    adjust = need("om.intl.adjust")
    recipes = getattr(adjust, "RECIPES", None)
    if not isinstance(recipes, dict):
        raise NotBuilt("not built yet: om.intl.adjust.RECIPES")
    bad = []
    for d in kb.differences:
        cits = d.get("citations") or []
        if not cits:
            bad.append(f"{d.get('id')}: no citation")
        for c in cits:
            if not (c.get("standard") and c.get("ref") and str(c.get("url", "")).startswith("http")):
                bad.append(f"{d.get('id')}: citation needs standard + section/paragraph + public URL")
                break
        rid = d.get("adjustment")
        if not rid:
            bad.append(f"{d.get('id')}: no adjustment recipe id")
        elif not callable(recipes.get(rid)):
            bad.append(f"{d.get('id')}: recipe '{rid}' does not resolve to a callable in om.intl.adjust")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(kb.differences)} entries cited; every recipe id resolves"


QUOTE_RX = re.compile(r'"([^"]+)"|\u201c([^\u201d]+)\u201d|\u00ab([^\u00bb]+)\u00bb')


@gate("G2.5", "no-copy guard")
def g2_5_no_copy():
    kb = _kb()
    bad = []
    pools = [("difference", d) for d in kb.differences] + [("framework", f) for f in kb.frameworks.values()] + \
            [("standard", s) for s in getattr(kb, "standards", [])]
    for kind, e in pools:
        if e.get("authored") != "acretia":
            bad.append(f"{kind} {e.get('id')}: authored != acretia")
        for s in _walk_strings(e):
            for m in QUOTE_RX.finditer(s):
                q = next(g for g in m.groups() if g)
                if len(q.split()) > 25:
                    bad.append(f"{kind} {e.get('id')}: quoted passage of {len(q.split())} words")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(pools)} entries: all authored by us, no quote over 25 words"


# ================================================================================================ G3 labels
REQUIRED_KEYS = [("revenue", "IS", "Revenue", "الإيرادات"), ("ebit", "IS", "Operating profit", "ربح التشغيل"),
                 ("pretax", "IS", "Profit before income tax", "الربح قبل ضريبة الدخل"),
                 ("net_income", "IS", "Net profit for the year", "صافي ربح السنة"),
                 ("assets", "BS", "Total assets", "إجمالي الأصول"),
                 ("current_assets", "BS", "Total current assets", "إجمالي الأصول المتداولة"),
                 ("current_liabilities", "BS", "Total current liabilities", "إجمالي الالتزامات المتداولة"),
                 ("cfo", "CF", "Net cash from operating activities", "صافي النقد الناتج من الأنشطة التشغيلية"),
                 ("cfi", "CF", "Net cash used in investing activities", "صافي النقد المستخدم في الأنشطة الاستثمارية"),
                 ("cff", "CF", "Net cash from financing activities", "صافي النقد الناتج من الأنشطة التمويلية"),
                 ("cogs", "IS", "Cost of sales", "تكلفة المبيعات"),
                 ("cash", "BS", "Cash and cash equivalents", "النقد وما في حكمه"),
                 ("equity_total", "BS", "Total equity", "إجمالي حقوق الملكية"),
                 ("liabilities", "BS", "Total liabilities", "إجمالي الالتزامات"),
                 ("capex", "CF", "Purchase of property, plant and equipment", "شراء ممتلكات وآلات ومعدات"),
                 ("da", "CF", "Depreciation and amortisation", "الإهلاك والاستنفاد")]


def _match(labels, label, statement=None):
    try:
        return labels.match(label, statement=statement)
    except TypeError:
        return labels.match(label)


@gate("G3.1", "bilingual labels + ifrs-full concepts per key")
def g3_1_label_coverage():
    labels = need("om.intl.labels")
    concepts = need("om.intl.concepts")
    stm = need("om.statements")
    bad = []
    for key, st, en, ar in REQUIRED_KEYS:
        if key not in stm.LINES:
            bad.append(f"{key}: not in om.statements.LINES")
            continue
        for lang, text in (("en", en), ("ar", ar)):
            m = _match(labels, text, st)
            if m is None or m.key != key:
                bad.append(f"{key}: {lang} label '{text}' -> {getattr(m, 'key', None)}")
        cs = concepts.key_to_concepts(key)
        if not cs or not any("ifrs-full" in str(c) for c in cs):
            bad.append(f"{key}: no ifrs-full concept")
    if bad:
        fail(short(bad, 10))
    return "PASS", f"{len(REQUIRED_KEYS)} keys: en + ar label resolves, ifrs-full concept present"


def ar_variants(s):
    """Our own spelling variants of an Arabic label (hamza/alef, taa marbuta, alef maqsura, diacritics, tatweel)."""
    out = {}
    alef = "اأإآ"
    for a in alef:
        out[f"alef->{a}"] = re.sub("[" + alef + "]", a, s)
    out["taa-marbuta->haa"] = s.replace("ة", "ه")
    out["yaa->maqsura"] = re.sub(r"ي\b", "ى", s)
    out["diacritics"] = re.sub(r"([\u0621-\u064a])", "\\1\u064e", s, count=40)
    out["shadda+kasra"] = s.replace("ل", "ل\u0651\u0650", 2)
    out["tatweel"] = re.sub(r"([\u0628-\u064a])", "\\1\u0640", s, count=3)
    out["mixed"] = re.sub("[" + alef + "]", "ا", s).replace("ة", "ه").replace("ي", "ى")
    return out


@gate("G3.2", "Arabic normalisation invariance")
def g3_2_arabic_invariance():
    labels = need("om.intl.labels")
    bad, n = [], 0
    for key, st, en, ar in REQUIRED_KEYS[:8]:
        base = _match(labels, ar, st)
        if base is None or base.key != key:
            bad.append(f"base '{ar}' -> {getattr(base, 'key', None)} (want {key})")
            continue
        for name, v in ar_variants(ar).items():
            n += 1
            m = _match(labels, v, st)
            if m is None or m.key != key or m.confidence < 0.5:
                bad.append(f"{key} variant {name}: {getattr(m, 'key', None)}")
    plain, east, persian = (f"{ar} {d}" for ar, d in
                            (("إجمالي الأصول المتداولة", "12"), ("إجمالي الأصول المتداولة", "١٢"), ("إجمالي الأصول المتداولة", "۱۲")))
    ks = []
    for lab in (plain, east, persian):
        m = _match(labels, lab, "BS")
        ks.append((getattr(m, "key", None)))
    if len(set(ks)) != 1:
        bad.append(f"digit variants map differently: {ks}")
    nl = getattr(labels, "normalise_label", None)
    if nl and len({nl(plain), nl(east), nl(persian)}) != 1:
        bad.append("normalise_label differs across Latin/Eastern/Persian digits")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{n} variants + digit forms map to the plain key"


@gate("G3.3", "adversarial labels")
def g3_3_adversarial_labels():
    labels = need("om.intl.labels")
    bad = []
    p, l = _match(labels, "صافي الربح", "IS"), _match(labels, "صافي الخسارة", "IS")
    if p is None or l is None:
        bad.append("net profit / net loss label unmapped")
    else:
        if p.key != l.key:
            bad.append(f"profit/loss keys differ: {p.key} vs {l.key}")
        if not (p.sign_hint and l.sign_hint and p.sign_hint == -l.sign_hint):
            bad.append(f"sign_hint not opposite: {p.sign_hint} vs {l.sign_hint}")
    m = _match(labels, "إجمالي الأصول المتداولة", "BS")
    if getattr(m, "key", None) != "current_assets":
        bad.append(f"إجمالي الأصول المتداولة -> {getattr(m, 'key', None)}")
    m = _match(labels, "Profit before zakat and income tax", "IS")
    if getattr(m, "key", None) != "pretax":
        bad.append(f"Profit before zakat and income tax -> {getattr(m, 'key', None)}")
    totals = {"assets", "current_assets", "liabilities", "current_liabilities", "equity_total", "revenue", "net_income"}
    comps = [("Cash and cash equivalents", "BS", "cash"), ("Trade receivables", "BS", "ar"), ("Property, plant and equipment", "BS", None),
             ("Retained earnings", "BS", None), ("Short-term borrowings", "BS", None), ("Gross profit", "IS", "gross_profit"),
             ("Trade and other payables", "BS", None), ("Depreciation expense", "IS", None), ("Interest income", "IS", None),
             ("النقد وما في حكمه", "BS", "cash"), ("الذمم المدينة التجارية", "BS", None), ("الأرباح المبقاة", "BS", None),
             ("ممتلكات وآلات ومعدات", "BS", None)]
    for lab, st, expect in comps:
        m = _match(labels, lab, st)
        if m is not None and m.confidence >= 0.5:
            if m.key in totals and m.key != expect:
                bad.append(f"component '{lab}' mapped to total '{m.key}'")
            if expect and m.key != expect:
                bad.append(f"'{lab}' -> {m.key} (want {expect})")
    for junk in ("xqzv blorp", "الجدول الزمني للاجتماعات", "Chairman's statement"):
        m = _match(labels, junk, None)
        if m is not None and m.confidence >= 0.5:
            bad.append(f"unknown label '{junk}' mapped to {m.key} at {m.confidence:.2f}")
    if bad:
        fail(short(bad, 8))
    return "PASS", "profit/loss sign, current vs total, zakat, component vs total, unknown labels"


# ================================================================================================ G4 parsing
NUM_CASES = [
    ("(1,234)", -1234), ("١٬٢٣٤٫٥", 1234.5), ("۱۲۳", 123), ("(١٢٣)", -123), ("123-", -123), ("1.234.567", 1234567),
    ("1,234,567", 1234567), ("-1,234", -1234), ("(0.5)", -0.5), ("1,234.56", 1234.56), ("٣٤٥", 345), ("(١٬٢٣٤)", -1234),
    ("\u22121,234", -1234), ("  1,234  ", 1234), ("0", 0), ("(2,345,678)", -2345678), ("٢٬٣٤٥٬٦٧٨", 2345678),
    ("1,234,567.89", 1234567.89), ("(١٢٫٥)", -12.5), ("١٢٫٥", 12.5), ("1 234 567", 1234567), ("(12.3)", -12.3),
    ("1,000", 1000), ("999", 999), ("(999)", -999), ("12,345-", -12345), ("\u200f(1,234)\u200f", -1234), ("٠٫٥", 0.5),
]
NIL_CASES = ["-", "\u2014", "\u2013", "nil", "Nil", "(-)", "- ", "\u2212"]
KIND_CASES = [("12.5%", None, "percent"), ("Note 12", None, "note_ref"), ("إيضاح ٥", None, "note_ref"), ("5(a)", None, "note_ref"),
              ("Revenue", None, "text"), ("", None, "text"), ("12", "note", "note_ref"), ("2024", "header", "year"),
              ("2023", "header", "year")]
UNIT_CASES = [("بالألف جنيه مصري", ("EGP", 1e3)), ("EGP '000", ("EGP", 1e3)), ("EGP thousands", ("EGP", 1e3)),
              ("SAR million", ("SAR", 1e6)), ("بالمليون ريال سعودي", ("SAR", 1e6)), ("AED'000", ("AED", 1e3)),
              ("US$ thousands", ("USD", 1e3)), ("ر.س", ("SAR", None)), ("ج.م", ("EGP", None)),
              ("All amounts in SAR millions", ("SAR", 1e6)), ("(Amounts in thousands of Egyptian Pounds)", ("EGP", 1e3)),
              ("SAR '000", ("SAR", 1e3)), ("USD millions", ("USD", 1e6)), ("بالآلاف ريال سعودي", ("SAR", 1e3))]
PERIOD_CASES = [("30 June 2024", date(2024, 6, 30)), ("31 March 2024", date(2024, 3, 31)), ("31 December 2024", date(2024, 12, 31)),
                ("٣٠ يونيو ٢٠٢٤", date(2024, 6, 30)), ("30 يونيو 2024", date(2024, 6, 30)), ("٣١ مارس ٢٠٢٥", date(2025, 3, 31)),
                ("٣١ ديسمبر ٢٠٢٣", date(2023, 12, 31)), ("As at 31/12/2024", date(2024, 12, 31)), ("June 30, 2024", date(2024, 6, 30)),
                ("For the year ended 30 June 2024", date(2024, 6, 30)), ("2024 ديسمبر 31", date(2024, 12, 31)),
                ("As at 31 March 2023", date(2023, 3, 31))]


@gate("G4.1", "number parsing table")
def g4_1_numbers():
    parse = need_attr("om.intl.numparse", "parse_number")
    bad = []
    for tok, exp in NUM_CASES:
        p = parse(tok)
        if not (p.kind == "number" and p.value is not None and abs(p.value - exp) < 1e-9):
            bad.append(f"{tok!r}: got {p.value}/{p.kind}, want {exp}")
    for tok, kw in (("1.234,5", {}), ("1.234,5", {"decimal": ","}), ("١٫٢٣٤٬٥", {"decimal": ","})):
        p = parse(tok, **kw)
        if kw.get("decimal") == "," and tok.startswith("١"):
            continue
        if p.value is None or abs(p.value - 1234.5) > 1e-9:
            bad.append(f"{tok!r} {kw}: got {p.value}, want 1234.5")
    for tok in NIL_CASES:
        p = parse(tok)
        if not (p.is_nil or p.kind == "nil"):
            bad.append(f"{tok!r}: not nil ({p.kind})")
    for tok, ctx, kind in KIND_CASES:
        p = parse(tok, context=ctx) if ctx else parse(tok)
        if kind == "year":
            if p.kind == "number" and p.value is not None:
                bad.append(f"{tok!r} in {ctx}: treated as a value")
        elif p.kind != kind or (kind != "percent" and p.value is not None and kind in ("note_ref", "text")):
            bad.append(f"{tok!r}: kind {p.kind}, want {kind}")
    if bad:
        fail(f"{len(bad)} failures: " + short(bad, 10))
    n = len(NUM_CASES) + 3 + len(NIL_CASES) + len(KIND_CASES)
    return "PASS", f"{n} number cases"


@gate("G4.2", "unit and currency detection")
def g4_2_units():
    det = need_attr("om.intl.numparse", "detect_unit")
    bad = []
    for text, exp in UNIT_CASES:
        got = tuple(det(text))
        if got != exp:
            bad.append(f"{text!r}: {got} want {exp}")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(UNIT_CASES)} unit cases"


@gate("G4.3", "fiscal year-end detection")
def g4_3_periods():
    ph = need_attr("om.intl.numparse", "parse_period_header")
    bad = []
    for text, exp in PERIOD_CASES:
        got = ph(text)
        if got != exp:
            bad.append(f"{text!r}: {got} want {exp}")
    for junk in ("Notes to the financial statements", "", "Total assets"):
        if ph(junk) is not None:
            bad.append(f"{junk!r} parsed as a period")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(PERIOD_CASES)} header cases (30 June, 31 March, 31 December; EN and AR)"


@gate("G4.4", "table has at least 40 cases")
def g4_4_table_size():
    n = len(NUM_CASES) + 3 + len(NIL_CASES) + len(KIND_CASES) + len(UNIT_CASES) + len(PERIOD_CASES)
    if n < 40:
        fail(f"only {n} cases")
    return "PASS", f"{n} cases in the table"


# ================================================================================================ G5 extraction
@gate("G5.0", "tesseract + ara/eng traineddata installed")
def g5_0_tesseract():
    r = run(["tesseract", "--list-langs"])
    if r.returncode != 0:
        fail("tesseract is not installed (install it, do not skip): " + (r.stderr or r.stdout)[:120])
    langs = set(r.stdout.split())
    miss = {"ara", "eng"} - langs
    if miss:
        fail(f"tesseract traineddata missing: {sorted(miss)}")
    return "PASS", "tesseract with ara+eng"


def _present(e, pred):
    return any(pred(t) for t in e["ground_truth"])


@gate("G5.1", "fixture set coverage")
def g5_1_fixture_coverage():
    fx = fixtures()
    scanned_ar = [e for e in fx if e["kind"] == "scanned" and e["language"] == "ar"]
    need_ = {
        "native EN": any(e["kind"] == "native" and e["language"] == "en" for e in fx),
        "native AR": any(e["kind"] == "native" and e["language"] == "ar" for e in fx),
        "scanned EN": any(e["kind"] == "scanned" and e["language"] == "en" for e in fx),
        "scanned AR": bool(scanned_ar),
        "bilingual": any(e["language"] == "bi" for e in fx),
        "non-December year end": any(int(e["fiscal_year_end_month"]) != 12 for e in fx),
        "EGP '000": any(e["currency"] == "EGP" and float(e["unit_scale"]) == 1e3 for e in fx),
        "SAR million": any(e["currency"] == "SAR" and float(e["unit_scale"]) == 1e6 for e in fx),
        "by-nature P&L": any(_present(e, lambda t: t["key"] in ("x.raw_materials", "x.employee_costs")) for e in fx),
        "IFRS 16 lines": any(_present(e, lambda t: t["key"] in ("x.rou_assets", "x.lease_liabilities_current", "x.rou_depreciation")) for e in fx),
        "zakat line": any(_present(e, lambda t: t["key"] == "x.zakat") for e in fx)}
    miss = [k for k, v in need_.items() if not v]
    bad = []
    for e in fx:
        if e["kind"] == "scanned":
            if not os.path.exists(fx_path(e)):
                bad.append(f"{e['file']} missing")
                continue
            txt = run(["pdftotext", "-layout", fx_path(e), "-"]).stdout
            if len(re.findall(r"\d", txt)) > 0:
                bad.append(f"{e['file']}: scanned fixture has a text layer")
            skew = e.get("skew")
            if skew and max(abs(x) for x in skew) > 1.5:
                bad.append(f"{e['file']}: skew above 1.5 degrees")
            if not e.get("derived_from"):
                bad.append(f"{e['file']}: scanned fixture not derived from a native twin")
    if miss or bad:
        fail(f"missing {miss}; {short(bad)}")
    return "PASS", f"{len(fx)} fixtures cover all 11 required kinds"


def _classify(e, ex):
    """Per ground-truth record: 'ok' (released, exact), 'review' (held back), 'wrong' (released wrong), 'missing'."""
    tol = tol_units(e)
    res, wrong_extra = [], []
    pool = list(ex.figures)
    for t in e["ground_truth"]:
        if t["key"].startswith("_"):
            continue
        cands = [f for f in pool if f.key == t["key"] and iso(f.period_end) == t["period_end"]]
        samepage = [f for f in cands if f.page == t["page"]]
        cands = samepage or cands
        near = [f for f in pool if f.page == t["page"] and f.value is not None and abs(f.value - t["value"]) <= tol
                and iso(f.period_end) == t["period_end"]]
        rel_ = [f for f in cands if f.status == "ok"]
        if rel_:
            wrongs = [f for f in rel_ if f.value is None or abs(f.value - t["value"]) > tol]
            rights = [f for f in rel_ if f.value is not None and abs(f.value - t["value"]) <= tol]
            if wrongs and not rights:
                res.append(("wrong", t, wrongs[0]))
            elif wrongs:
                res.append(("wrong", t, wrongs[0]))
            else:
                res.append(("ok", t, rights[0]))
        elif any(f.status == "review" for f in cands) or any(f.status == "review" for f in near):
            res.append(("review", t, None))
        elif near:
            res.append(("ok" if near[0].status == "ok" else "review", t, near[0]))
        else:
            res.append(("missing", t, None))
    return res


_CLASS = {}


def classified(e):
    if e["file"] not in _CLASS:
        _CLASS[e["file"]] = _classify(e, extracted(e))
    return _CLASS[e["file"]]


@gate("G5.2", "no wrong released figures")
def g5_2_no_wrong_released_figures():
    bad, total = [], 0
    for e in fixtures():
        for st, t, f in classified(e):
            total += 1
            if st == "wrong":
                bad.append(f"{e['file']} {t['key']}@{t['period_end']}: truth {t['value']} released {f.value}")
            elif st == "missing":
                bad.append(f"{e['file']} {t['key']}@{t['period_end']} p.{t['page']}: neither extracted nor in review")
    if bad:
        fail(f"{len(bad)} of {total} ground-truth figures: " + short(bad, 6))
    return "PASS", f"{total} ground-truth figures, 0 wrong released, 0 missing"


@gate("G5.3", "coverage")
def g5_3_coverage():
    agg = {"native": [0, 0], "scanned": [0, 0]}
    per = []
    for e in fixtures():
        cl = classified(e)
        ok = sum(1 for s, *_ in cl if s == "ok")
        agg[e["kind"]][0] += ok
        agg[e["kind"]][1] += len(cl)
        per.append(f"{e['file']}={ok}/{len(cl)}")
    bad = []
    for kind, need_ in (("native", 0.95), ("scanned", 0.85)):
        ok, n = agg[kind]
        if n == 0 or ok / n < need_:
            bad.append(f"{kind}: {ok}/{n} = {ok / n if n else 0:.3f} < {need_}")
    if bad:
        fail("; ".join(bad) + " | " + short(per, 8))
    return "PASS", f"native {agg['native'][0]}/{agg['native'][1]}, scanned {agg['scanned'][0]}/{agg['scanned'][1]}"


_BBOX = {}


def pdftotext_words(path):
    if path in _BBOX:
        return _BBOX[path]
    r = run(["pdftotext", "-bbox", path, "-"])
    pages = {}
    cur = None
    for line in r.stdout.splitlines():
        m = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', line)
        if m:
            cur = (float(m.group(1)), float(m.group(2)), [])
            pages[len(pages) + 1] = cur
            continue
        m = re.search(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', line)
        if m and cur:
            import html
            cur[2].append((html.unescape(m.group(5)), *(float(m.group(i)) for i in range(1, 5))))
    _BBOX[path] = pages
    return pages


def _text_in_bbox(path, page, bb):
    pg = pdftotext_words(path).get(page)
    if not pg:
        return None
    w, h, words = pg
    x0, y0, x1, y1 = bb[0] * w - 1.5, bb[1] * h - 1.5, bb[2] * w + 1.5, bb[3] * h + 1.5
    ins = [x for x in words if x0 <= (x[1] + x[3]) / 2 <= x1 and y0 <= (x[2] + x[4]) / 2 <= y1]
    ins.sort(key=lambda x: x[1])
    return ["".join(x[0] for x in ins), "".join(x[0] for x in reversed(ins))]


@gate("G5.4", "figure metadata + native bbox text")
def g5_4_metadata():
    bad, n, checked = [], 0, 0
    for e in fixtures():
        ex = extracted(e)
        pages = pdfinfo_pages(fx_path(e)) or 10 ** 6
        for f in ex.figures:
            n += 1
            tag = f"{e['file']} {f.key}@{iso(f.period_end)}"
            if not (isinstance(f.page, int) and 1 <= f.page <= pages):
                bad.append(f"{tag}: page {f.page} outside 1..{pages}")
            b = f.bbox_norm
            if not (b and len(b) == 4 and all(0 <= v <= 1 for v in b) and b[0] < b[2] and b[1] < b[3]):
                bad.append(f"{tag}: bad bbox_norm {b}")
            if not (isinstance(f.confidence, (int, float)) and 0 <= f.confidence <= 1):
                bad.append(f"{tag}: confidence {f.confidence}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(f.sha256_span_hash)):
                bad.append(f"{tag}: sha256_span_hash not 64-hex")
            if e["kind"] == "native" and f.raw and f.source != "derived" and b and len(b) == 4:
                texts = _text_in_bbox(fx_path(e), f.page, b)
                checked += 1
                want = canon_token(f.raw)
                if not texts or not any(canon_token(t) == want for t in texts):
                    bad.append(f"{tag}: text in bbox {texts[0] if texts else None!r} != raw {f.raw!r}")
    if bad:
        fail(f"{len(bad)} problems in {n} figures: " + short(bad, 6))
    return "PASS", f"{n} figures checked; {checked} native bbox texts equal the raw token"


@gate("G5.5", "Arabic numeral OCR character accuracy >= 99%")
def g5_5_arabic_ocr_accuracy():
    ocr_img = need_attr("om.intl.ocr", "ocr_page_image")
    tgt = [e for e in fixtures() if e["kind"] == "scanned" and e["language"] == "ar"]
    if not tgt:
        fail("no scanned Arabic fixture")
    matched = total = 0
    for e in tgt:
        by_page = {}
        for t in e["ground_truth"]:
            d = digits_only(t["raw"])
            if d:
                by_page.setdefault(t["page"], []).append(d)
        with tempfile.TemporaryDirectory() as td:
            r = run(["pdftoppm", "-r", "300", "-png", fx_path(e), os.path.join(td, "p")])
            if r.returncode != 0:
                fail("pdftoppm failed: " + r.stderr[:100])
            files = sorted(f for f in os.listdir(td) if f.endswith(".png"))
            for page, truths in by_page.items():
                f = next((x for x in files if re.search(r"-0*%d\.png$" % page, x)), None)
                if not f:
                    fail(f"page {page} not rendered")
                words = ocr_img(open(os.path.join(td, f), "rb").read(), langs="ara+eng")
                toks = [digits_only(getattr(w, "text", "")) for w in words]
                toks = [t for t in toks if t]
                for tr in truths:
                    total += len(tr)
                    best = 0
                    for tk in toks:
                        sm = difflib.SequenceMatcher(None, tr, tk, autojunk=False)
                        best = max(best, sum(b.size for b in sm.get_matching_blocks()))
                        if best == len(tr):
                            break
                    matched += best
    acc = matched / total if total else 0.0
    if acc < 0.99:
        fail(f"Arabic numeral character accuracy {acc:.4f} < 0.99 over {total} characters")
    return "PASS", f"character accuracy {acc:.4f} over {total} digits"


# ================================================================================================ G6 tie-out
def _pdf_of(e):
    return fx_path(e)


def _clean_native():
    return native_fixtures()


def _tie_mods():
    return need("om.intl.tieout"), need("om.intl.review")


@gate("G6.1", "clean fixtures tie out (incl. comparatives)")
def g6_1_clean_ties():
    tie, _ = _tie_mods()
    bad = []
    for e in _clean_native():
        ex = fresh(e)
        rep = tie.check(ex)
        if not rep.passed:
            bad.append(f"{e['file']}: " + short([f"{t.name}@{iso(t.period)} diff {t.diff}" for t in rep.failed if t.hard], 3))
    nile = [e for e in _clean_native() if e["company"] == "Nile Valley Foods S.A.E."]
    cur = next((e for e in nile if e["periods"][1] > e["periods"][0] and e["periods"][1].startswith("2024")), None)
    old = next((e for e in nile if e["periods"][1].startswith("2023")), None)
    if cur and old:
        rep = tie.check(fresh(cur), prior=fresh(old))
        if not rep.passed:
            bad.append("with prior year: " + short([t.name for t in rep.failed], 3))
        # adversarial: shift the comparative in the current report so it disagrees with the prior report
        ex = fresh(cur)
        per = old["periods"][1]
        u = float(cur["unit_scale"]) / 1e6
        hit = 0
        for k in ("assets", "liabilities_equity"):
            for i in figs_for(ex, k, per):
                ex.figures[i].value += 2 * u
                ex.figures[i].status, ex.figures[i].reasons, ex.figures[i].confidence = "ok", [], 0.99
                hit += 1
        if hit and not tie.check(ex, prior=fresh(old)).failed:
            bad.append("mismatching comparative (assets and liabilities_equity shifted together) was not caught")
    else:
        bad.append("manifest lacks the FY2023/FY2024 pair needed for the comparative tie")
    if bad:
        fail(short(bad, 6))
    return "PASS", f"{len(_clean_native())} clean fixtures tie; comparative mismatch detected"


def _transpose(v):
    s = f"{abs(v):.6f}".rstrip("0").rstrip(".")
    ds = [i for i, c in enumerate(s) if c.isdigit()]
    for a, b in zip(ds, ds[1:]):
        if s[a] != s[b] and b - a == 1 or (s[a] != s[b] and s[a:b + 1].count(".") == 1):
            t = list(s)
            t[a], t[b] = t[b], t[a]
            out = float("".join(t))
            return out if v >= 0 else -out
    return v * 10 + 1


MUTATIONS = [("assets", "transpose", None), ("liabilities_equity", "plus2", None), ("net_income", "flip", "IS"),
             ("cfo", "flip", None), ("cfi", "transpose", None), ("cff", "plus2", None), ("pretax", "flip", None),
             ("revenue", "transpose", None), ("cash", "drop", None), ("equity_total", "plus2", None),
             ("current_assets", "drop", None), ("x.cash_end", "transpose", None), ("net_change_cash", "plus2", None),
             ("tax", "plus2", None), ("net_income", "flip", "CF"), ("gross_profit", "transpose", None)]


def _apply(kind, v, u):
    return {"transpose": _transpose(v), "flip": -v, "plus2": v + 2 * u, "drop": 0.0}[kind]


def mutation_cases():
    """Yield (fixture, key, kind, statement, truth value, period) for each mutation applicable to each native fixture."""
    for e in _clean_native():
        per = e["periods"][1]
        tr = truth_by(e)
        for key, kind, st in MUTATIONS:
            recs = tr.get((key, per))
            if key == "net_income" and st == "CF" and not recs:
                recs = tr.get(("cf_net_income", per))
            if recs and abs(recs[0]["value"]) > 0:
                yield e, key, kind, st, recs[0]["value"], per


@gate("G6.2", "mutations fail the tie, reach review and block release")
def g6_2_mutations():
    tie, review = _tie_mods()
    bad, n, kinds = [], 0, set()
    first_for = set()
    for e, key, kind, st, truth, per in mutation_cases():
        ex = fresh(e)
        key_in_ex = "net_income" if key == "cf_net_income" else key
        idx = figs_for(ex, key_in_ex, per, st)
        if not idx and key == "net_income" and st == "CF":
            idx = figs_for(ex, "cf_net_income", per)
        if not idx:
            bad.append(f"{e['file']}: figure {key}@{per} not extracted, cannot mutate")
            continue
        u = float(e["unit_scale"]) / 1e6
        newv = _apply(kind, truth, u)
        if abs(newv - truth) <= 2 * tol_units(e):
            continue
        for i in idx:
            f = ex.figures[i]
            f.value, f.status, f.reasons, f.confidence = newv, "ok", [], 0.99
        n += 1
        kinds.add(kind)
        tag = f"{e['file']} {key}/{kind}"
        rep = tie.check(ex)
        failing = [t for t in rep.failed if t.hard]
        if rep.passed or not failing:
            bad.append(f"{tag}: tie did not fail")
            continue
        involved = set()
        for t in failing:
            if set(idx) & set(t.figures):
                involved |= set(t.figures)
        if not involved:
            bad.append(f"{tag}: failing ties do not involve the mutated figure")
            continue
        use_pdf = e["file"] not in first_for
        first_for.add(e["file"])
        items = review.queue(ex, rep, pdf=_pdf_of(e) if use_pdf else None)
        queued = {(it.figure.key, iso(it.figure.period_end), it.figure.raw) for it in items}
        if not any((ex.figures[i].key, iso(ex.figures[i].period_end), ex.figures[i].raw) in queued for i in idx):
            bad.append(f"{tag}: mutated figure not in the review queue")
        if len(involved) >= 2 and sum(1 for i in involved if (ex.figures[i].key, iso(ex.figures[i].period_end), ex.figures[i].raw) in queued) < 2:
            bad.append(f"{tag}: involved figures not all queued")
        for args in ((ex, rep), (ex,)):
            try:
                tie.release(*args, strict=True)
                bad.append(f"{tag}: release(strict=True) did not raise")
            except tie.ReleaseBlocked:
                pass
        if use_pdf:
            _CROP[e["file"]] = items
    if n < 10:
        bad.append(f"only {n} mutations could be applied (need >= 10)")
    for k in ("transpose", "flip"):
        if k not in kinds:
            bad.append(f"no '{k}' mutation applied")
    if bad:
        fail(f"{len(bad)} of {n} mutations: " + short(bad, 6))
    return "PASS", f"{n} mutations ({', '.join(sorted(kinds))}): tie fails, figures queued, release blocked"


_CROP = {}


@gate("G6.3", "low confidence without corroboration goes to review")
def g6_3_low_confidence():
    tie, review = _tie_mods()
    e = _clean_native()[0]
    ex = fresh(e)
    base = next((f for f in ex.figures if f.key and f.value is not None), None)
    if base is None:
        fail("no figure to clone")
    lone = copy.deepcopy(base)
    lone.key, lone.label, lone.raw, lone.confidence, lone.status, lone.reasons = "x.gov_grants", "Government grants (probe)", "7", 0.30, "ok", []
    lone.is_total, lone.components, lone.row = False, None, None
    ex.figures.append(lone)
    rep = tie.check(ex)
    if lone.status != "review" or not lone.reasons:
        fail(f"uncorroborated 0.30-confidence figure has status={lone.status!r} reasons={lone.reasons}")
    items = review.queue(ex, rep)
    hit = [it for it in items if it.figure is lone]
    if not hit or not hit[0].reasons:
        fail("uncorroborated low-confidence figure missing from the review queue or has no reasons")
    return "PASS", f"reasons: {hit[0].reasons}"


@gate("G6.4", "review items carry page, bbox and a PNG crop")
def g6_4_review_crops():
    if not _CROP:
        g6_2_mutations()
    bad, n = [], 0
    for fn, items in _CROP.items():
        if not items:
            bad.append(f"{fn}: empty queue")
        for it in items:
            n += 1
            if not (isinstance(it.page, int) and it.page >= 1):
                bad.append(f"{fn}: item without page")
            b = it.bbox_norm
            if not (b and len(b) == 4 and 0 <= min(b) and max(b) <= 1 and b[0] < b[2] and b[1] < b[3]):
                bad.append(f"{fn}: bad bbox {b}")
            if not png_ok(it.crop_png):
                bad.append(f"{fn}: crop_png is not a valid non-empty PNG")
    if n == 0:
        fail("no review items to check")
    if bad:
        fail(short(bad, 6))
    return "PASS", f"{n} review items, all with page, bbox and a PNG crop"


@gate("G6.5", "failed ties never reach a model")
def g6_5_release_only_path():
    tie, _ = _tie_mods()
    bad = []
    allowed = os.path.join("om", "intl", "tieout.py")
    scan = [p for p in pyfiles("om", "src", "scripts", "acretia.py") if not p.endswith("verify_s8.py")]
    for p in scan:
        try:
            tree = parse_py(p)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                nm = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if nm == "IntlStatements" and not p.endswith(allowed):
                    bad.append(f"{rel(p)}:{n.lineno} constructs IntlStatements outside om/intl/tieout.py")
                if nm == "Statements" and os.sep + os.path.join("om", "intl") + os.sep in p and not p.endswith(allowed):
                    bad.append(f"{rel(p)}:{n.lineno} constructs Statements inside om.intl outside tieout.py")
    if not any(p.endswith(allowed) for p in scan):
        raise NotBuilt("not built yet: om.intl.tieout")
    src = open(os.path.join(ROOT, allowed), encoding="utf-8").read()
    if "IntlStatements(" not in src:
        bad.append("om/intl/tieout.py never constructs IntlStatements")
    n = 0
    for e in _clean_native():
        s = tie.release(fresh(e), strict=True)
        n += 1
        rr = getattr(s, "release_report", None)
        if rr is None or not rr.passed:
            bad.append(f"{e['file']}: released object's release_report.passed is not True")
    if bad:
        fail(short(bad, 6))
    return "PASS", f"AST: IntlStatements( only in tieout.py; {n} released objects carry a passed release_report"


# ================================================================================================ G7 model support
def _redsea():
    return find_fx(lambda e: e["kind"] == "native" and e["currency"] == "SAR" and e["language"] == "en", "native SAR English")


def _nile():
    return find_fx(lambda e: e["kind"] == "native" and e["currency"] == "EGP" and e["periods"][1].startswith("2024"), "native EGP FY2024")


def _released(e):
    tie = need("om.intl.tieout")
    return tie.release(fresh(e), strict=True)


def _build_book(s):
    model3 = need("om.model3")
    xl = need("om.xlsx")
    data, meta = model3.build(s)
    return xl.read(data), meta, data


def _check_book(b, meta):
    bad = []
    ck = b.sheets.get("Checks", {})
    errs = [k for k, c in ck.items() if str(c.value) == "ERROR"]
    if errs:
        bad.append(f"{len(errs)} ERROR cells on Checks")
    row = meta["rows"]["Checks"].get("master") if "Checks" in meta.get("rows", {}) else None
    if row is not None and b.value("Checks", f"C{row}") != "OK":
        bad.append(f"master check = {b.value('Checks', f'C{row}')!r}")
    bal = meta.get("rows", {}).get("BS", {}).get("bal")
    if bal is not None:
        vals = [c.value for (r, _c), c in b.sheets["BS"].items() if r == bal and isinstance(c.value, (int, float))]
        if not vals or any(abs(v) > 1e-3 for v in vals):
            bad.append(f"balance row not zero: {vals[:5]}")
    return bad


@gate("G7.1", "model3.build runs unchanged; balance and cash checks are zero")
def g7_1_model_builds():
    e = _nile()
    s = _released(e)
    if s.currency != "EGP" or s.years[-1].month != 6:
        fail(f"released statements: {s.currency}, last year end {s.years[-1]}")
    b, meta, _ = _build_book(s)
    bad = _check_book(b, meta)
    if bad:
        fail(short(bad))
    return "PASS", f"EGP, June year end ({s.years[-1]}): master OK, BS balance row zero"


@gate("G7.2", "by-nature P&L computes EBIT")
def g7_2_by_nature():
    e = _redsea()
    per = e["periods"][1]
    tr = {t["key"]: t["value"] for t in e["ground_truth"] if t["period_end"] == per}
    # hand derivation: EBIT = profit before zakat/tax + finance costs - finance income (== revenue + other income - opex by nature)
    ebit = tr["pretax"] + tr["interest_expense"] - tr.get("interest_income", 0.0)
    alt = tr["revenue"] + tr.get("x.other_income", 0.0) - sum(tr.get(k, 0.0) for k in ("x.raw_materials", "x.employee_costs",
                                                                                         "x.depreciation", "x.other_opex"))
    if abs(ebit - alt) > 0.2:
        fail(f"fixture ground truth inconsistent: {ebit} vs {alt}")
    s = _released(e)
    i = s.years.index(date.fromisoformat(per))
    got = s.get("ebit", i)
    flag = getattr(s, "basis_flags", {}).get("ebit")
    bad = []
    if flag != "computed_by_nature":
        bad.append(f"basis_flags['ebit'] = {flag!r}")
    if got is None or abs(got - ebit) > 0.25 * float(e["unit_scale"]) / 1e6 + 0.1:
        bad.append(f"EBIT {got} != hand value {ebit:.3f}")
    if bad:
        fail("; ".join(bad))
    return "PASS", f"EBIT {got:.2f} = hand value {ebit:.2f}; flagged computed_by_nature"


@gate("G7.3", "IFRS 16 toggle")
def g7_3_ifrs16():
    adj = need("om.intl.adjust")
    R = adj.RECIPES
    bad = []
    # hand-made: EBITDA 140 (EBIT 100 + D&A 40); right-of-use depreciation 12; lease interest 3 -> pre-IFRS 16 EBITDA 140 - 15 = 125
    r = R["ifrs16_to_pre16_ebitda"]({"ebit": 100.0, "da": 40.0, "x.rou_depreciation": 12.0, "x.lease_interest": 3.0})
    if abs((r["adjusted"].get("ebitda_pre16") or -1) - 125.0) > 1e-9:
        bad.append(f"pre-16 EBITDA {r['adjusted'].get('ebitda_pre16')} != 125")
    nd = {"debt_current": 50.0, "debt_noncurrent": 150.0, "cash": 80.0, "x.lease_liabilities_current": 20.0,
          "x.lease_liabilities_noncurrent": 30.0}
    on = R["lease_adjusted_net_debt"](nd, include_leases=True)["adjusted"]["net_debt"]
    off = R["lease_adjusted_net_debt"](nd, include_leases=False)["adjusted"]["net_debt"]
    if abs(on - 170.0) > 1e-9 or abs(off - 120.0) > 1e-9:
        bad.append(f"net debt with leases {on} (want 170), without {off} (want 120)")
    e = find_fx(lambda e: _present(e, lambda t: t["key"] == "x.rou_depreciation"), "fixture with IFRS 16 lines")
    per = e["periods"][1]
    tr = {t["key"]: t["value"] for t in e["ground_truth"] if t["period_end"] == per}
    vals = {k: tr.get(k) for k in ("ebit", "da", "x.rou_depreciation", "x.lease_interest", "cash", "debt_current", "debt_noncurrent",
                                   "x.lease_liabilities_current", "x.lease_liabilities_noncurrent")}
    if vals["da"] is None:
        vals["da"] = tr.get("x.depreciation", 0.0) + tr.get("x.amortisation", 0.0)
    if None in (vals["ebit"], vals["x.rou_depreciation"], vals["x.lease_interest"]):
        bad.append(f"{e['file']} ground truth lacks ebit / ROU depreciation / lease interest")
    else:
        want = vals["ebit"] + vals["da"] - vals["x.rou_depreciation"] - vals["x.lease_interest"]
        got = R["ifrs16_to_pre16_ebitda"](vals)["adjusted"].get("ebitda_pre16")
        if got is None or abs(got - want) > 1e-6:
            bad.append(f"fixture pre-16 EBITDA {got} != {want}")
        leases = (vals["x.lease_liabilities_current"] or 0) + (vals["x.lease_liabilities_noncurrent"] or 0)
        ex_l = (vals["debt_current"] or 0) + (vals["debt_noncurrent"] or 0) - (vals["cash"] or 0)
        g_on = R["lease_adjusted_net_debt"](vals, include_leases=True)["adjusted"]["net_debt"]
        g_off = R["lease_adjusted_net_debt"](vals, include_leases=False)["adjusted"]["net_debt"]
        if abs(g_on - (ex_l + leases)) > 1e-6 or abs(g_off - ex_l) > 1e-6:
            bad.append(f"fixture net debt {g_on}/{g_off} != {ex_l + leases}/{ex_l}")
    if bad:
        fail(short(bad))
    return "PASS", "pre-IFRS 16 EBITDA and lease-adjusted net debt match hand values (synthetic + fixture)"


@gate("G7.4", "zakat as a tax-like, flagged charge")
def g7_4_zakat():
    adj = need("om.intl.adjust")
    r = adj.RECIPES["zakat_as_tax"]({"pretax": 100.0, "tax": 10.0, "x.zakat": 2.5})
    a = r["adjusted"]
    bad = []
    if a.get("zakat") != 2.5:
        bad.append(f"zakat not shown separately: {a.get('zakat')}")
    if abs((a.get("effective_rate_incl_zakat") or 0) - 0.125) > 1e-9:
        bad.append(f"effective rate with zakat {a.get('effective_rate_incl_zakat')} != 0.125")
    if abs((a.get("effective_rate_ex_zakat") or 0) - 0.10) > 1e-9:
        bad.append(f"effective rate ex zakat {a.get('effective_rate_ex_zakat')} != 0.10")
    if not r["flags"]:
        bad.append("no flag raised")
    r2 = adj.RECIPES["zakat_as_tax"]({"pretax": 100.0, "tax": 12.5, "x.zakat": 2.5}, zakat_included_in_tax=True)
    if abs((r2["adjusted"].get("effective_rate_incl_zakat") or 0) - 0.125) > 1e-9:
        bad.append("zakat double counted when already inside tax")
    if bad:
        fail(short(bad))
    return "PASS", "zakat separate, in effective rate (12.5% = (10+2.5)/100), flagged"


def _csv_rates():
    p = os.path.join(ROOT, "om", "intl", "data", "fx", "egp_usd_monthly.csv")
    if not os.path.exists(p):
        raise NotBuilt(f"not built yet: {rel(p)}")
    rows = {}
    with open(p, newline="") as fh:
        for r in csv.DictReader(l for l in fh if l.strip() and not l.startswith("#")):
            rows[r["month"]] = (float(r["end"]), float(r["avg"]))
    return p, rows


@gate("G7.5", "FX: end vs average rates and devaluation flags")
def g7_5_fx():
    fxm = need("om.intl.fx")
    path, rows = _csv_rates()
    fx = fxm.IntlFX(path)
    bad = []
    end = fx.rate("EGP", date(2024, 6, 30))
    if end is None or abs(end - rows["2024-06"][0]) > 1e-6:
        bad.append(f"period-end rate {end} != CSV {rows['2024-06'][0]}")
    days = {m: (date(2024, 6, 30) if m == "2024-06" else None) for m in rows}
    months = [(2023, m) for m in range(7, 13)] + [(2024, m) for m in range(1, 7)]
    import calendar as _c
    tot = sum(rows[f"{y}-{m:02d}"][1] * _c.monthrange(y, m)[1] for y, m in months)
    dd = sum(_c.monthrange(y, m)[1] for y, m in months)
    avg = fx.average("EGP", date(2023, 7, 1), date(2024, 6, 30))
    if avg is None or abs(avg - tot / dd) > 1e-6:
        bad.append(f"average rate {avg} != day-weighted {tot / dd:.6f}")
    for label, a, b, want in (("FY June 2024 (March 2024 devaluation)", date(2023, 7, 1), date(2024, 6, 30), (2024, 3)),
                              ("FY June 2017 (November 2016 float)", date(2016, 7, 1), date(2017, 6, 30), (2016, 11))):
        fl = fx.devaluation_flags("EGP", a, b)
        if not any((f["date"].year, f["date"].month) == want for f in fl):
            bad.append(f"{label}: no devaluation flag in {want}")
    if fx.devaluation_flags("EGP", date(2018, 7, 1), date(2019, 6, 30)):
        bad.append("flag raised for the calm FY June 2019")
    # translation: balance sheet at the period-end rate, flows at the period-average rate
    stm = need("om.statements")
    items = {k: [stm.Item(None, [])] for k in stm.LINES}
    items["cash"] = [stm.Item(1000.0, [])]
    items["revenue"] = [stm.Item(5000.0, [])]
    s = stm.Statements(ticker="T", name="T", cik=0, currency="EGP", years=[date(2024, 6, 30)], data=items,
                       filings=[{"form": "", "accn": "", "url": ""}], warnings=[])
    t = fxm.translate(s, "USD", fx)
    if t.get("cash", 0) is None or abs(t.get("cash", 0) - 1000.0 / end) > 1e-6:
        bad.append(f"cash translated {t.get('cash', 0)} != {1000.0 / end:.4f} (period-end rate)")
    if t.get("revenue", 0) is None or abs(t.get("revenue", 0) - 5000.0 / (tot / dd)) > 1e-6:
        bad.append(f"revenue translated {t.get('revenue', 0)} != {5000.0 / (tot / dd):.4f} (average rate)")
    if bad:
        fail(short(bad))
    return "PASS", f"end {end:.4f}, average {avg:.4f}; both devaluations flagged, calm year clean"


@gate("G7.6", "calendarisation")
def g7_6_calendarise():
    cal = need("om.intl.calendar")
    bad = []
    # June year end: calendar 2023 = 6/12 of FY(Jun-23) + 6/12 of FY(Jun-24)
    got = cal.calendarise({date(2023, 6, 30): 100.0, date(2024, 6, 30): 200.0}, 12).get(date(2023, 12, 31))
    if got is None or abs(got - 150.0) > 1e-9:
        bad.append(f"June year end: {got} != 150 (6/12*100 + 6/12*200)")
    # March year end: calendar 2023 = 3/12 of FY(Mar-23) + 9/12 of FY(Mar-24)
    got = cal.calendarise({date(2023, 3, 31): 120.0, date(2024, 3, 31): 240.0}, 12).get(date(2023, 12, 31))
    if got is None or abs(got - 210.0) > 1e-9:
        bad.append(f"March year end: {got} != 210 (3/12*120 + 9/12*240)")
    got = cal.calendarise({date(2023, 12, 31): 77.0, date(2024, 12, 31): 88.0}, 12).get(date(2023, 12, 31))
    if got != 77.0:
        bad.append(f"December year end changed the value: {got}")
    if bad:
        fail(short(bad))
    return "PASS", "June 6/12+6/12 = 150; March 3/12+9/12 = 210; December unchanged"


# ================================================================================================ G8 connectors
CONNECTOR_NAMES = {"egx": ["egx"], "tadawul": ["tadawul", "saudi"], "esef": ["esef", "xbrl"], "companies_house": ["companies_house", "companieshouse"],
                   "kvk": ["kvk"], "inpi": ["inpi", "rne"], "bronnoysund": ["bronn", "brreg"], "cro": ["cro", "ireland"], "gleif": ["gleif", "lei"]}
PAID_NAMES = {"pappers": ["pappers"], "north_data": ["north_data", "northdata"], "bigdata": ["bigdata"],
              "third_bridge": ["third_bridge", "thirdbridge"], "arbolus": ["arbolus"]}


def _load_connector_modules():
    files = intl_connector_files()
    if not files:
        raise NotBuilt("not built yet: src/harness/connectors/intl_*.py")
    base = need("src.harness.connectors.connectors.base") if os.path.isdir(os.path.join(ROOT, "src", "harness", "connectors", "connectors")) \
        else need("src.harness.connectors.base")
    loaded = {}
    for p in files:
        modname = os.path.relpath(p, ROOT)[:-3].replace(os.sep, ".")
        try:
            loaded[p] = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            loaded[p] = e
    return base, loaded, files


def _find_registered(base, loaded, aliases):
    names = [n for n in getattr(base, "_FACTORIES", {}) if any(a in n.lower() for a in aliases)]
    return names


def _instantiate(base, name):
    import inspect
    fac = base._FACTORIES[name]
    kw = {}
    try:
        sig = inspect.signature(fac)
        for pn, prm in sig.parameters.items():
            low = pn.lower()
            if any(k in low for k in ("fixture", "replay_dir", "cache_dir", "offline_dir")):
                d = os.path.join(FIXDIR, "connectors", name)
                kw[pn] = d if os.path.isdir(d) else os.path.join(FIXDIR, "connectors")
            elif any(k in low for k in ("replay", "offline")):
                kw[pn] = True
    except (TypeError, ValueError):
        pass
    return base.get(name, **kw)


@gate("G8.1", "EGX, Tadawul, ESEF, Companies House register and list/fetch offline")
def g8_1_register_list_fetch():
    base, loaded, files = _load_connector_modules()
    bad = []
    for key in ("egx", "tadawul", "esef", "companies_house"):
        names = _find_registered(base, loaded, CONNECTOR_NAMES[key])
        if not names:
            bad.append(f"{key}: not registered")
            continue
        try:
            c = _instantiate(base, names[0])
            items = list(c.list())
            if not items:
                bad.append(f"{key}: list() empty from fixtures")
                continue
            content, meta = c.fetch(items[0].id)
            if not isinstance(content, (bytes, bytearray)) or not content or "name" not in meta or "source" not in meta:
                bad.append(f"{key}: fetch() must return (bytes, meta with name+source)")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{key}: {type(e).__name__}: {str(e)[:100]}")
    if bad:
        fail(short(bad))
    return "PASS", "4 connectors register, list and fetch from fixtures"


class _FakeResp(io.BytesIO):
    status = 200
    headers = {}

    def __init__(self, body=b"{}", status=200):
        super().__init__(body)
        self.status = status
        self.code = status

    def getcode(self):
        return self.status

    def geturl(self):
        return "https://fake.invalid/"

    def info(self):
        return {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """Patches urllib.request.urlopen with a scripted server and time with a fake clock; records every request."""

    def __init__(self, robots="User-agent: *\nDisallow: /private/\n"):
        self.robots, self.calls, self.now = robots, [], 1000.0

    def __enter__(self):
        import urllib.request as ur
        self.ur, self.orig = ur, (ur.urlopen, time.sleep, time.monotonic, time.time)

        def urlopen(req, *a, **k):
            url = req if isinstance(req, str) else req.full_url
            hdrs = {} if isinstance(req, str) else {k.lower(): v for k, v in req.header_items()}
            self.calls.append((self.now, url, hdrs))
            if url.endswith("/robots.txt"):
                return _FakeResp(self.robots.encode())
            return _FakeResp(b'{"items": []}')

        def sleep(s):
            self.now += s

        ur.urlopen = urlopen
        time.sleep = sleep
        time.monotonic = lambda: self.now
        time.time = lambda: self.now
        return self

    def __exit__(self, *a):
        self.ur.urlopen, time.sleep, time.monotonic, time.time = self.orig


def _live_connector(base, key):
    names = _find_registered(base, {}, CONNECTOR_NAMES[key])
    if not names:
        raise AssertionError(f"{key}: not registered")
    import inspect
    fac = base._FACTORIES[names[0]]
    kw = {}
    for pn in inspect.signature(fac).parameters:
        low = pn.lower()
        if any(k in low for k in ("replay", "offline")):
            kw[pn] = False
        if "api_key" in low or low == "key":
            kw[pn] = None
    return base.get(names[0], **kw)


@gate("G8.2", "robots.txt honoured before any request")
def g8_2_robots():
    base, loaded, files = _load_connector_modules()
    c = _live_connector(base, "egx")
    with FakeNet() as net:
        refused = False
        try:
            c.fetch("https://www.egx.com.eg/private/secret.pdf")
        except Exception:  # noqa: BLE001
            refused = True
        content_calls = [u for _, u, _h in net.calls if not u.endswith("/robots.txt")]
        if content_calls:
            fail(f"disallowed path was requested: {content_calls[0]}")
        if not refused:
            fail("fetch of a disallowed path did not raise")
    return "PASS", "disallowed path refused; only robots.txt requested"


@gate("G8.3", "rate limit between requests to one host")
def g8_3_rate_limit():
    base, loaded, files = _load_connector_modules()
    c = _live_connector(base, "egx")
    with FakeNet() as net:
        for p in ("a", "b", "c"):
            try:
                c.fetch(f"https://www.egx.com.eg/public/{p}.pdf")
            except Exception:  # noqa: BLE001
                pass
        times = [t for t, u, _h in net.calls if not u.endswith("/robots.txt")]
    if len(times) < 3:
        fail(f"only {len(times)} requests reached the fake server")
    gaps = [b - a for a, b in zip(times, times[1:])]
    interval = getattr(c, "min_interval", None) or getattr(c, "interval", None) or 1.0
    if min(gaps) + 1e-9 < float(interval):
        fail(f"gaps {gaps} below the configured interval {interval}")
    return "PASS", f"gaps {gaps} >= {interval}s on the fake clock"


@gate("G8.4", "User-Agent, Companies House key from env only")
def g8_4_ua_and_keys():
    base, loaded, files = _load_connector_modules()
    c = _live_connector(base, "egx")
    with FakeNet() as net:
        try:
            c.fetch("https://www.egx.com.eg/public/x.pdf")
        except Exception:  # noqa: BLE001
            pass
        uas = [h.get("user-agent", "") for _, _u, h in net.calls]
    if not uas or not all("acretia" in u.lower() for u in uas):
        fail(f"User-Agent does not identify Acretia: {uas[:3]}")
    saved = {k: os.environ.pop(k) for k in list(os.environ) if "COMPANIES_HOUSE" in k.upper() or "COMPANIESHOUSE" in k.upper()}
    try:
        try:
            ch = _live_connector(base, "companies_house")
            with FakeNet():
                list(ch.list())
                ch.fetch("00000006")
            fail("Companies House answered without a key in the environment")
        except AssertionError:
            raise
        except Exception as e:  # noqa: BLE001
            if isinstance(e, (KeyError, AttributeError, TypeError)):
                fail(f"Companies House failed uncleanly without a key: {type(e).__name__}: {e}")
    finally:
        os.environ.update(saved)
    hits = _secret_hits(intl_connector_files())
    if hits:
        fail("key literal in connectors: " + short(hits))
    return "PASS", "Acretia User-Agent on every request; missing key errors cleanly; no literal key"


@gate("G8.5", "nothing written outside data/raw/")
def g8_5_no_stray_writes():
    base, loaded, files = _load_connector_modules()

    def snap():
        out = set()
        for dp, dn, fn in os.walk(ROOT):
            dn[:] = [d for d in dn if d not in (".git", "__pycache__", "node_modules", ".venv")]
            if os.path.join(ROOT, "data", "raw") in dp:
                continue
            for f in fn:
                out.add(os.path.join(dp, f))
        return out
    before = snap()
    for key in ("egx", "tadawul", "esef", "companies_house"):
        names = _find_registered(base, loaded, CONNECTOR_NAMES[key])
        if names:
            try:
                c = _instantiate(base, names[0])
                for it in list(c.list())[:1]:
                    c.fetch(it.id)
            except Exception:  # noqa: BLE001
                pass
    new = [p for p in snap() - before if not p.endswith(".pyc")]
    if new:
        fail("files written outside data/raw/: " + short(map(rel, new)))
    return "PASS", "list/fetch wrote no files outside data/raw/"


@gate("G8.6", "registry connectors with offline fixtures; GLEIF crosses registries")
def g8_6_more_connectors():
    base, loaded, files = _load_connector_modules()
    bad = []
    for key in ("companies_house", "kvk", "inpi", "bronnoysund", "cro", "gleif"):
        names = _find_registered(base, loaded, CONNECTOR_NAMES[key])
        if not names:
            bad.append(f"{key}: not registered")
            continue
        try:
            c = _instantiate(base, names[0])
            items = list(c.list())
            if not items:
                bad.append(f"{key}: no fixture items")
                continue
            content, meta = c.fetch(items[0].id)
            if key == "gleif":
                txt = content.decode("utf-8", "replace") if isinstance(content, (bytes, bytearray)) else str(content)
                regs = set(re.findall(r'"(?:registry|registration_authority|registrationAuthority|authority)[A-Za-z_]*"\s*:\s*"([^"]+)"', txt))
                if len(regs) < 2 and len(meta.get("registries", [])) < 2:
                    bad.append("gleif: fixture does not resolve one entity across >= 2 registries")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{key}: {type(e).__name__}: {str(e)[:80]}")
    pipe = os.path.join(ROOT, "om", "intl", "pipeline.py")
    if not os.path.exists(pipe):
        bad.append("German/Spanish accounts routing: not built yet: om.intl.pipeline")
    if bad:
        fail(short(bad, 8))
    return "PASS", "6 registry connectors with offline fixtures; GLEIF resolves across registries"


@gate("G8.7", "source terms table and personal-data minimisation")
def g8_7_terms_and_pii():
    p = need_file("docs/s8/source-terms.md")
    rows = [l for l in open(p, encoding="utf-8") if l.strip().startswith("|") and not re.match(r"^\s*\|[\s:|-]+\|\s*$", l)]
    rows = rows[1:]
    bad = []
    wanted = {"egx": "egx", "tadawul": "tadawul|saudi exchange", "esef": "esef|xbrl", "companies house": "companies house", "kvk": "kvk",
              "inpi": "inpi", "br\u00f8nn\u00f8ysund": "br.nn.ysund|brreg", "cro": "cro|ireland", "gleif": "gleif"}
    for k, rx in wanted.items():
        row = next((r for r in rows if re.search(rx, r, re.I)), None)
        if not row:
            bad.append(f"no row for {k}")
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 5 or not re.search(r"https?://", row) or not re.search(r"\d{4}-\d{2}-\d{2}", row) or any(not c for c in cells[:5]):
            bad.append(f"{k}: row needs terms URL, licence, date reviewed, rate limit, what is stored")
    pii = re.compile(r"date_of_birth|dateOfBirth|birth|address_line|postal_code|nationality|\baddress\b", re.I)
    for f in intl_connector_files():
        for n, line in enumerate(open(f, encoding="utf-8"), 1):
            if pii.search(line) and not re.search(r"drop|remov|strip|exclude|pop\(|forbid|redact|minimi|never|deny|not store|#", line, re.I):
                bad.append(f"{rel(f)}:{n} handles personal-data field without a drop/redact: {line.strip()[:60]}")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(rows)} source rows; no unredacted personal-data fields in connectors"


@gate("G8.8", "paid sources are NotConfigured stubs")
def g8_8_paid_stubs():
    base, loaded, files = _load_connector_modules()
    cls = None
    for p in s8_code_files():
        for n in ast.walk(parse_py(p)):
            if isinstance(n, ast.ClassDef) and n.name == "NotConfigured":
                cls = n.name
    if cls is None:
        raise NotBuilt("not built yet: class NotConfigured")
    bad = []
    for key, al in PAID_NAMES.items():
        names = _find_registered(base, loaded, al)
        if not names:
            mods = [p for p in files if any(a in os.path.basename(p).lower() for a in al)]
            if not mods:
                bad.append(f"{key}: no interface")
            continue
        try:
            c = base.get(names[0])
            try:
                list(c.list())
                bad.append(f"{key}: list() did not raise NotConfigured")
            except Exception as e:  # noqa: BLE001
                if type(e).__name__ != "NotConfigured":
                    bad.append(f"{key}: raised {type(e).__name__}, want NotConfigured")
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ != "NotConfigured":
                bad.append(f"{key}: {type(e).__name__}: {str(e)[:60]}")
    hits = _secret_hits(intl_connector_files())
    if hits:
        bad.append("credentials in connectors: " + short(hits, 2))
    if bad:
        fail(short(bad, 8))
    return "PASS", "Pappers, North Data, Bigdata.com, Third Bridge, Arbolus raise NotConfigured; no credentials"


# ================================================================================================ G9 evals
def _g0_ok():
    bad = [k for k, v in STATUS.items() if k.startswith("G0.") and v != "PASS"]
    if len([k for k in STATUS if k.startswith("G0.")]) < 5:
        bad.append("G0 not run in this invocation")
    return bad


def _recompute(recs):
    """accuracy of released figures, coverage, flag rate and silent-wrong count from per-figure records."""
    rel_n = wrong = total = reviewed = 0
    silent = []
    for r in recs:
        gold = jget(r, "gold", "gold_value", "truth", "expected")
        if gold is None:
            continue
        total += 1
        status = str(r.get("status", "")).lower()
        released = status in ("ok", "released") or r.get("released") is True
        if status == "review" or r.get("review") is True or r.get("released") is False:
            released = False
        val = jget(r, "value", "extracted", "got", "extracted_value")
        if released:
            rel_n += 1
            tol = r.get("tol")
            if tol is None:
                tol = 0.5 * float(r["scale"]) / 1e6 if r.get("scale") else max(0.0005, 1e-4 * abs(gold))
            if val is None or abs(float(val) - float(gold)) > float(tol):
                wrong += 1
                silent.append(r)
        else:
            reviewed += 1
    return dict(total=total, released=rel_n, wrong=wrong, review=reviewed,
                accuracy=(rel_n - wrong) / rel_n if rel_n else 0.0, coverage=(rel_n - wrong) / total if total else 0.0,
                flag_rate=reviewed / total if total else 0.0, silent=silent)


def _results(name):
    p = need_file(f"evals/intl/{name}/results.jsonl")
    return jl(p)


def _meta_ok(recs):
    bad = 0
    for r in recs:
        if not isinstance(r.get("page"), int) or not _bbox_ok(jget(r, "bbox_norm", "bbox")) or not isinstance(r.get("confidence"), (int, float)):
            bad += 1
    return bad


@gate("G9.1", "XBRL gold")
def g9_1_xbrl_gold():
    g0 = _g0_ok()
    if g0:
        fail("G0 anchors must pass first (D-030): " + short(g0))
    recs = _results("xbrl_gold")
    m = _recompute(recs)
    filers = {jget(r, "filer", "company", "ticker", "entity", "lei") for r in recs}
    countries = {jget(r, "country", "jurisdiction") for r in recs}
    filers.discard(None)
    countries.discard(None)
    bad = []
    if len(filers) < 20:
        bad.append(f"{len(filers)} filers < 20")
    if len(countries) < 5:
        bad.append(f"{len(countries)} countries < 5")
    if m["total"] < 300:
        bad.append(f"{m['total']} figures < 300")
    if m["accuracy"] < 0.99:
        bad.append(f"accuracy {m['accuracy']:.4f} < 0.99")
    if m["coverage"] < 0.90:
        bad.append(f"coverage {m['coverage']:.4f} < 0.90")
    mb = _meta_ok(recs)
    if mb:
        bad.append(f"{mb} records lack page/bbox/confidence")
    if bad:
        fail("; ".join(bad))
    return "PASS", f"{len(filers)} filers, {len(countries)} countries, {m['total']} figures, accuracy {m['accuracy']:.4f}, coverage {m['coverage']:.4f}"


@gate("G9.2", "MENA set")
def g9_2_mena():
    g0 = _g0_ok()
    if g0:
        fail("G0 anchors must pass first (D-030): " + short(g0))
    recs = _results("mena")
    m = _recompute(recs)
    cos = {}
    for r in recs:
        c = jget(r, "company", "filer", "ticker", "entity")
        if c:
            cos[c] = r
    docs = {}
    for r in recs:
        d = jget(r, "doc_sha256", "doc_id", "doc")
        if d:
            docs[d] = r
    bad = []
    egx = {c for c, r in cos.items() if "egx" in str(jget(r, "exchange", "market", default="")).lower()}
    tad = {c for c, r in cos.items() if "tadawul" in str(jget(r, "exchange", "market", default="")).lower() or "saudi" in str(jget(r, "exchange", "market", default="")).lower()}
    if len(egx) < 10:
        bad.append(f"{len(egx)} EGX companies < 10")
    if len(tad) < 5:
        bad.append(f"{len(tad)} Tadawul companies < 5")
    sc = sum(1 for r in docs.values() if r.get("scanned") is True or str(r.get("language", "")).lower() == "ar" or r.get("arabic_only") is True)
    if sc < 5:
        bad.append(f"{sc} scanned/Arabic-only reports < 5")
    hv = sum(1 for r in recs if r.get("hand_verified") is True)
    if hv < 300:
        bad.append(f"{hv} hand-verified figures < 300")
    if m["accuracy"] < 0.98:
        bad.append(f"accuracy {m['accuracy']:.4f} < 0.98")
    if m["coverage"] < 0.70:
        bad.append(f"coverage {m['coverage']:.4f} < 0.70")
    same = [1 for r in recs if jget(r, "verifier") is None or jget(r, "extractor") is None or r.get("verifier") == r.get("extractor")]
    if same:
        bad.append(f"{len(same)} records without verifier != extractor")
    tp = [r.get("tie_passed") for r in docs.values() if "tie_passed" in r]
    if not tp:
        bad.append("tie-out pass rate not derivable (no tie_passed per document)")
    if not any(("ocr" in str(k).lower() and "acc" in str(k).lower()) for r in recs for k in r) and not _scorecard_rows("ocr"):
        bad.append("Arabic numeral OCR character accuracy not reported")
    if bad:
        fail("; ".join(bad))
    return "PASS", (f"{len(egx)} EGX + {len(tad)} Tadawul, {sc} scanned/AR, {hv} hand-verified, accuracy {m['accuracy']:.4f}, "
                    f"coverage {m['coverage']:.4f}, tie pass {sum(1 for x in tp if x) / len(tp):.3f}")


@gate("G9.3", "standards QA")
def g9_3_standards_qa():
    qs = jl(need_file("evals/intl/standards_qa/questions.jsonl"))
    kb = _kb()
    if len(qs) != 50:
        fail(f"{len(qs)} questions (need 50)")
    good, bad = 0, []
    for q in qs:
        a = kb.answer(q["question"])
        text = re.sub(r"\s+", " ", (a.text or "")).lower()
        pts = [re.search(p, text, re.I) is not None for p in q.get("key_points", [])]
        stds = " ".join(str(c.get("standard", "")) for c in a.citations).lower()
        cites_ok = all(m.lower() in stds for m in q.get("must_cite", [])) and bool(a.citations) and bool(a.entries)
        urls_ok = all(str(c.get("url", "")).startswith("http") and c.get("ref") for c in a.citations)
        if pts and all(pts) and cites_ok and urls_ok:
            good += 1
        else:
            bad.append(q["id"])
    score = good / len(qs)
    if score < 0.90:
        fail(f"score {score:.3f} < 0.90 ({len(bad)} failing: {short(bad, 8)})")
    return "PASS", f"{good}/{len(qs)} = {score:.3f}"


def _scorecard_rows(token=None):
    p = os.path.join(ROOT, "scorecard.csv")
    if not os.path.exists(p):
        raise NotBuilt("not built yet: scorecard.csv")
    with open(p, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if str(r.get("stage", "")).upper().startswith("S8")]
    if token:
        rows = [r for r in rows if token in (r.get("eval", "") + " " + r.get("notes", "")).lower()]
    return rows


def _num(x):
    try:
        v = float(str(x).strip().rstrip("%"))
        return v / 100 if str(x).strip().endswith("%") else v
    except ValueError:
        return None


@gate("G9.4", "scorecard rows match recomputed numbers")
def g9_4_scorecard():
    rows = _scorecard_rows()
    if not rows:
        fail("no S8 rows in scorecard.csv")
    bad = []
    qs = jl(need_file("evals/intl/standards_qa/questions.jsonl"))
    kb = _kb()
    want = {}
    good = 0
    for q in qs:
        a = kb.answer(q["question"])
        text = a.text.lower()
        stds = " ".join(str(c.get("standard", "")) for c in a.citations).lower()
        if all(re.search(p, text, re.I) for p in q.get("key_points", [])) and all(m.lower() in stds for m in q.get("must_cite", [])):
            good += 1
    want["standards_qa"] = good / len(qs)
    for name in ("xbrl_gold", "mena"):
        try:
            m = _recompute(_results(name))
        except NotBuilt as e:
            bad.append(str(e))
            continue
        want[f"{name} accuracy"] = m["accuracy"]
        want[f"{name} coverage"] = m["coverage"]
        want[f"{name} flag"] = m["flag_rate"]
    for k, v in want.items():
        toks = k.split()
        hit = [r for r in rows if all(t in (r.get("eval", "") + " " + r.get("notes", "")).lower().replace("_", " ").replace("-", " ")
                                      or t.replace("_", " ") in (r.get("eval", "")).lower().replace("_", " ") for t in toks)]
        if not hit or not any(_num(r.get("score")) is not None and abs(_num(r["score"]) - v) <= 0.001 for r in hit):
            bad.append(f"scorecard has no row matching {k} = {v:.4f}")
    for r in rows:
        blob = (r.get("eval", "") + r.get("notes", "")).lower()
        if any(w in blob for w in ("judge", "llm", "model")) and "live_model=no" not in blob and "not run live" not in blob:
            bad.append(f"row {r.get('eval')} is model-dependent but does not say 'not run live'")
    if bad:
        fail(short(bad, 8))
    return "PASS", f"{len(rows)} S8 rows match the recomputed numbers (+-0.001)"


# ================================================================================================ G10 hygiene
SECRET_PATTERNS = [(r"AKIA[0-9A-Z]{16}", "AWS key"), (r"\bsk-[A-Za-z0-9_\-]{20,}", "secret key (sk-)"), (r"\bghp_[A-Za-z0-9]{30,}", "GitHub token"),
                   (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "Slack token"), (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY", "private key"),
                   (r"AIza[0-9A-Za-z\-_]{35}", "Google API key"), (r"Bearer\s+[A-Za-z0-9\-_\.]{24,}", "bearer token"),
                   (r"(?i)(?:api[_-]?key|token|secret|passw(?:or)?d|passwd)\s*[:=]\s*[\"'][A-Za-z0-9_\-/+=]{16,}[\"']", "credential literal")]
PLACEHOLDER = re.compile(r"example|xxxx|your[_-]|<[^>]+>|placeholder|dummy|changeme|fake|test", re.I)


def _secret_hits(paths):
    hits = []
    for p in paths:
        try:
            if os.path.getsize(p) > 5_000_000:
                continue
            txt = open(p, encoding="utf-8", errors="strict").read()
        except (UnicodeDecodeError, OSError):
            continue
        for rx, what in SECRET_PATTERNS:
            for m in re.finditer(rx, txt):
                if PLACEHOLDER.search(m.group(0)):
                    continue
                hits.append(f"{rel(p)}: {what}")
    return hits


def s8_text_files():
    out = list(s8_code_files())
    for sub in ("docs/s8", "evals/intl", "tests/fixtures/intl", "om/intl"):
        base = os.path.join(ROOT, sub)
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
            for f in fn:
                if f.lower().endswith((".py", ".md", ".json", ".jsonl", ".csv", ".yaml", ".yml", ".txt", ".toml")):
                    out.append(os.path.join(dp, f))
    for pat in ("scripts/verify_s8.py", "scripts/make_intl_fixtures.py", "scripts/fetch_intl_corpus.py"):
        if os.path.exists(os.path.join(ROOT, pat)):
            out.append(os.path.join(ROOT, pat))
    t = os.path.join(ROOT, "tests")
    out += [os.path.join(t, f) for f in os.listdir(t) if f.startswith("test_intl_") or f == "test_verify_s8_smoke.py"]
    return sorted(set(out))


@gate("G10.1", "fixtures are ours: manifest, sha256, regeneration")
def g10_1_fixture_hygiene():
    man = manifest()
    bad = []
    listed = {e["file"] for e in man["fixtures"]}
    for e in man["fixtures"]:
        if not str(e.get("generator", "")).startswith("scripts/"):
            bad.append(f"{e['file']}: generator is not ours ({e.get('generator')})")
        p = fx_path(e)
        if not os.path.exists(p):
            bad.append(f"{e['file']}: missing")
        elif hashlib.sha256(open(p, "rb").read()).hexdigest() != e["sha256"]:
            bad.append(f"{e['file']}: sha256 differs from the manifest")
        by = {}
        for t in e["ground_truth"]:
            by.setdefault(t["period_end"], {})[t["key"]] = t["value"]
        for per, v in by.items():
            if "assets" in v and "liabilities_equity" in v and abs(v["assets"] - v["liabilities_equity"]) > 1e-6:
                bad.append(f"{e['file']} {per}: ground-truth balance sheet does not balance")
            if "cfo" in v and "cfi" in v and "cff" in v and "net_change_cash" in v and abs(v["cfo"] + v["cfi"] + v["cff"] - v["net_change_cash"]) > 1e-6:
                bad.append(f"{e['file']} {per}: ground-truth cash flow does not sum")
    tracked = run(["git", "ls-files", "tests/fixtures/intl", "evals/intl"], cwd=ROOT).stdout.split("\n")
    emanifests = set()
    for t in tracked:
        if t.endswith("manifest.json") and t.startswith("evals/intl"):
            try:
                d = json.load(open(os.path.join(ROOT, t)))
                emanifests |= {os.path.basename(x["file"]) for x in d.get("fixtures", d.get("files", []))}
            except (ValueError, KeyError, TypeError):
                pass
    for t in tracked:
        if t.lower().endswith((".pdf", ".png")):
            b = os.path.basename(t)
            if b not in listed and b not in emanifests:
                bad.append(f"{t}: committed but not in any manifest (third-party report?)")
            if "/anchors/" in t:
                bad.append(f"{t}: anchor report committed (publisher terms)")
    r = run([sys.executable, os.path.join(ROOT, "scripts", "make_intl_fixtures.py"), "--check"], cwd=ROOT)
    if r.returncode != 0:
        bad.append("make_intl_fixtures.py --check failed: " + (r.stdout + r.stderr).strip()[-160:])
    if bad:
        fail(short(bad, 6))
    return "PASS", f"{len(listed)} fixtures: our generator, sha256 match, ground truth ties, --check reproduces"


@gate("G10.2", "secret scan")
def g10_2_secrets():
    files = s8_text_files()
    hits = _secret_hits(files)
    if hits:
        fail(f"{len(hits)} hits: " + short(hits, 6))
    return "PASS", f"{len(files)} S8 files scanned, no keys, tokens or passwords"


# ================================================================================================ G11 north star
def _tele():
    p = need_file("evals/intl/telemetry.jsonl")
    return jl(p)


STEPS = ("parse", "ocr", "extract", "tieout", "review")


def _step_seconds(r):
    st = r.get("steps")
    if isinstance(st, dict):
        return {k: (v.get("seconds") if isinstance(v, dict) else v) for k, v in st.items()}
    if isinstance(st, list):
        return {s.get("name"): s.get("seconds") for s in st}
    return {k: r.get(k) for k in STEPS if k in r}


@gate("G11.1", "telemetry per extraction, p95 wall time")
def g11_1_telemetry():
    ext = need_attr("om.intl.extract", "extract")
    p = os.path.join(ROOT, "evals", "intl", "telemetry.jsonl")
    before = len(jl(p)) if os.path.exists(p) else 0
    e = _clean_native()[0]
    ext(fx_path(e), company=e["company"])
    recs = _tele()
    if len(recs) <= before:
        fail("an extraction run wrote no record to evals/intl/telemetry.jsonl")
    sha = hashlib.sha256(open(fx_path(e), "rb").read()).hexdigest()
    if not any(r.get("doc_sha256") == sha for r in recs[before:]):
        fail("new telemetry record carries a different doc_sha256")
    bad = []
    for r in recs:
        for k in ("doc_sha256", "pages", "scanned", "language", "wall_seconds", "tokens", "cost_usd", "engine", "flags"):
            if k not in r:
                bad.append(f"record lacks {k}")
                break
        else:
            ss = _step_seconds(r)
            if any(ss.get(s) is None for s in STEPS):
                bad.append(f"record {str(r['doc_sha256'])[:8]} lacks step seconds {[s for s in STEPS if ss.get(s) is None]}")
            if r["tokens"] != 0 or r["cost_usd"] != 0:
                bad.append("tokens/cost not 0 although no model is called")
    walls = sorted(float(r["wall_seconds"]) for r in recs if "wall_seconds" in r)
    if not walls:
        fail("no wall_seconds")
    p95 = walls[min(len(walls) - 1, int(0.95 * len(walls)))]
    if p95 > 600:
        bad.append(f"p95 wall {p95:.1f}s > 600s")
    if bad:
        fail(short(bad, 5))
    return "PASS", f"{len(recs)} records; median wall {statistics.median(walls):.1f}s, p95 {p95:.1f}s"


@gate("G11.2", "reliability: three numbers per set, zero silent wrong")
def g11_2_reliability():
    bad, detail = [], []
    for name in ("xbrl_gold", "mena"):
        recs = _results(name)
        m = _recompute(recs)
        if m["silent"]:
            bad.append(f"{name}: {len(m['silent'])} silent wrong numbers (released, wrong, unflagged)")
        docs = {}
        for r in recs:
            d = jget(r, "doc_sha256", "doc_id", "doc")
            if d and "tie_passed" in r:
                docs[d] = bool(r["tie_passed"])
        if not docs:
            bad.append(f"{name}: tie-out pass rate not derivable (tie_passed per document)")
        else:
            detail.append(f"{name} tie {sum(docs.values()) / len(docs):.3f} acc {m['accuracy']:.4f} flag {m['flag_rate']:.4f}")
    rows = _scorecard_rows()
    for st in ("anchor", "mena", "xbrl"):
        blob = [r for r in rows if st in (r.get("eval", "")).lower()]
        for metric, toks in (("tie-out pass rate", ("tie",)), ("figure accuracy", ("acc",)), ("flag rate", ("flag",))):
            if not any(any(t in (r["eval"] + " " + r.get("notes", "")).lower() for t in toks) for r in blob):
                bad.append(f"scorecard.csv: no {st} {metric} row")
    if bad:
        fail(short(bad, 8))
    return "PASS", "; ".join(detail)


@gate("G11.3", "review minutes")
def g11_3_review_minutes():
    p = need_file("evals/intl/review_minutes.csv")
    rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
    cols = rows[0].keys() if rows else []
    reason_c = next((c for c in cols if "reason" in c.lower() or "class" in c.lower()), None)
    min_c = next((c for c in cols if "min" in c.lower()), None)
    if not reason_c or not min_c:
        fail(f"columns reason/minutes missing: {list(cols)}")
    table = {}
    bad = []
    for r in rows:
        table[r[reason_c].strip()] = float(r[min_c])
        src = " ".join(str(v) for k, v in r.items() if k not in (reason_c, min_c))
        if not (re.search(r"https?://|\[INFERENCE\]|\[OBSERVATION\]|\[UNKNOWN\]", src) or len(src.strip()) > 20):
            bad.append(f"{r[reason_c]}: no source or [INFERENCE]")
        if "[INFERENCE]" in src and len(src.split()) < 6:
            bad.append(f"{r[reason_c]}: [INFERENCE] without reasoning")
    for k in ("low_ocr_conf", "tie_fail", "unmapped_label", "comparative_mismatch", "unit_ambiguous"):
        if k not in table:
            bad.append(f"reason class {k} missing")
    n = 0
    for r in _tele():
        if "review_minutes" not in r:
            bad.append("telemetry record without review_minutes")
            break
        fl = r.get("flags")
        counts = fl if isinstance(fl, dict) else {}
        if isinstance(fl, list):
            for x in fl:
                counts[x] = counts.get(x, 0) + 1
        want = sum(c * table.get(k, 0.0) for k, c in counts.items() if isinstance(c, (int, float)))
        if abs(float(r["review_minutes"]) - want) > 0.01:
            bad.append(f"review_minutes {r['review_minutes']} != sum(flags x minutes) {want:.2f}")
            break
        n += 1
    if bad:
        fail(short(bad, 6))
    return "PASS", f"{len(table)} reason classes; {n} documents' review_minutes recomputed"


def _intl_model_cli(pdf, out):
    return run([sys.executable, os.path.join(ROOT, "acretia.py"), "intl-model", pdf, "--out", out], cwd=ROOT, timeout=900)


def _check_handoff(xlsx_path):
    xl = need("om.xlsx")
    b = xl.read(open(xlsx_path, "rb").read())
    bad = []
    ck = b.sheets.get("Checks", {})
    errs = [k for k, c in ck.items() if str(c.value) == "ERROR"]
    if not ck:
        bad.append("no Checks sheet")
    if errs:
        bad.append(f"{len(errs)} ERROR cells on Checks")
    master = next((c.value for (r, c_), c in ck.items() if str(c.value).upper() == "MASTER CHECK"), None)
    pos = next(((r, c_) for (r, c_), c in ck.items() if str(c.value).upper() == "MASTER CHECK"), None)
    if pos and b.sheets["Checks"].get((pos[0], pos[1] + 1)) is not None and b.sheets["Checks"][(pos[0], pos[1] + 1)].value != "OK":
        bad.append("master check not OK")
    fl = b.sheets.get("Filings", {})
    cm = b.comments.get("Filings", {})
    nums = [k for k, c in fl.items() if c.formula is None and isinstance(c.value, (int, float)) and c.color == "0000FF"]
    nocomment = [k for k in nums if not re.search(r"p\.\s*\d+", cm.get(k, "")) or "bbox" not in cm.get(k, "")]
    if not nums:
        bad.append("Filings sheet has no reported (blue) figures")
    elif nocomment:
        bad.append(f"{len(nocomment)}/{len(nums)} Filings figures lack a page+bbox comment")
    return bad, len(nums)


@gate("G11.4", "hand-off: tied three-statement workbook from a synthetic SAR report")
def g11_4_handoff_synthetic():
    e = _redsea()
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "m.xlsx")
        r = _intl_model_cli(fx_path(e), out)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout)[-200:]
            if "invalid choice" in msg or "unknown" in msg.lower() or "usage" in msg.lower():
                raise NotBuilt("not built yet: acretia.py intl-model")
            fail("intl-model failed: " + msg)
        bad, n = _check_handoff(out)
    if bad:
        fail(short(bad))
    return "PASS", f"intl-model produced a workbook: checks OK, {n} Filings figures with page+bbox comments"


@gate("G11.4L", "hand-off live: Almarai latest annual FS")
def g11_4l_handoff_live():
    src = _load_sources("2280")
    ann = sorted([s for s in src if _doc_kind(s) == "annual"], key=lambda s: s["period_end"], reverse=True)[0]
    cand = os.path.join(ROOT, "data", "raw", "intl", ann.get("local_path", ""))
    if not os.path.exists(cand) or hashlib.sha256(open(cand, "rb").read()).hexdigest() != ann["sha256"]:
        raise Skip(f"anchor PDF not cached under data/raw/intl/ ({ann.get('local_path')}); live part skipped")
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "m.xlsx")
        r = _intl_model_cli(cand, out)
        if r.returncode != 0:
            fail("intl-model failed on Almarai: " + (r.stderr or r.stdout)[-200:])
        bad, n = _check_handoff(out)
    if bad:
        fail(short(bad))
    return "PASS", f"Almarai workbook tied; {n} Filings figures cited"


# ================================================================================================ G12 parity
@gate("G12.1", "locate() p95 <= 2 s over 50 random figures")
def g12_1_locate():
    locate = need_attr("om.intl.pipeline", "locate")
    pool = []
    for e in fixtures():
        pool += [(e, f) for f in extracted(e).figures if f.key]
    if not pool:
        fail("no figures to locate")
    rnd = random.Random(8)
    sample = [rnd.choice(pool) for _ in range(50)]
    ar_scanned = [(e, f) for e, f in pool if e["kind"] == "scanned" and e["language"] == "ar"]
    if ar_scanned:
        sample[:10] = [rnd.choice(ar_scanned) for _ in range(10)]
    times, bad = [], []
    for e, f in sample:
        t0 = time.perf_counter()
        r = locate(f)
        times.append(time.perf_counter() - t0)
        if not (isinstance(r, dict) and all(k in r for k in ("doc_sha256", "page", "bbox_norm", "png"))):
            bad.append("locate() result lacks doc_sha256/page/bbox_norm/png")
            break
        if r["page"] != f.page or not png_ok(r["png"]) or str(r["doc_sha256"]) != str(f.doc_id):
            bad.append(f"locate() wrong for {f.key} p.{f.page}")
    times.sort()
    p95 = times[int(0.95 * len(times)) - 1]
    if p95 > 2.0:
        bad.append(f"p95 {p95:.2f}s > 2s")
    if bad:
        fail(short(bad))
    return "PASS", f"p95 {p95:.2f}s, max {times[-1]:.2f}s over {len(times)} figures"


@gate("G12.2", "every Filings cell of an intl model cites doc, page, bbox")
def g12_2_filings_comments():
    e = _nile()
    s = _released(e)
    b, meta, _ = _build_book(s)
    fl = b.sheets.get("Filings", {})
    cm = b.comments.get("Filings", {})
    nums = [k for k, c in fl.items() if c.formula is None and isinstance(c.value, (int, float)) and c.color == "0000FF"]
    if not nums:
        fail("no reported figures on the Filings sheet")
    bad = [k for k in nums if not (re.search(r"p\.\s*\d+", cm.get(k, "")) and "bbox" in cm.get(k, "") and s.filings and True)]
    if bad:
        fail(f"{len(bad)}/{len(nums)} cells without a page+bbox comment, e.g. {bad[:3]}")
    doc12 = s.filings[0]["accn"]
    if not any(doc12 in cm.get(k, "") for k in nums):
        fail("comments do not carry the document id")
    return "PASS", f"{len(nums)} Filings cells carry doc, page, bbox"


@gate("G12.3", "specialist trace test")
def g12_3_trace_test():
    p = need_file("docs/s8/specialist-review.md")
    txt = open(p, encoding="utf-8").read()
    bad = []
    m = re.search(r"median[^0-9\n]{0,60}(\d+(?:\.\d+)?)\s*(s\b|sec|seconds|min)", txt, re.I)
    if not m:
        bad.append("no 'median ... <time>' trace result recorded")
    else:
        v = float(m.group(1)) * (1 if m.group(2).lower().startswith("min") else 1 / 60)
        if v >= 2.0:
            bad.append(f"median trace time {v:.2f} min >= 2 min")
    for t in ANCHORS:
        d = os.path.join(ROOT, "docs", "samples", "s8", t)
        if not os.path.isdir(d) or not os.listdir(d):
            bad.append(f"docs/samples/s8/{t}/ missing or empty")
    sc = re.search(r"score[^0-9\n]{0,30}(\d+(?:\.\d+)?)", txt, re.I)
    if bad:
        fail(short(bad, 6))
    return "PASS", f"median trace time recorded and < 2 min; samples for {len(ANCHORS)} anchors" + (f"; score {sc.group(1)}" if sc else "")


CLEAN_MACHINE = {"run": False}


@gate("G12.4", "clean machine install")
def g12_4_clean_machine():
    need_file("requirements.txt")
    docs = ""
    for f in ("README.md", "docs/s8/install.md", "docs/s8/README.md"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            docs += open(p, encoding="utf-8").read().lower()
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().lower()
    bad = []
    if "tesseract" not in docs or "poppler" not in docs:
        bad.append("tesseract/poppler not documented as system packages")
    if "yaml" not in req:
        bad.append("requirements.txt lacks PyYAML")
    if bad:
        fail(short(bad))
    if not CLEAN_MACHINE["run"]:
        raise Skip("pip install needs network; pass --clean-machine in CI. Requirements and docs checks passed")
    with tempfile.TemporaryDirectory() as td:
        v = os.path.join(td, "venv")
        for cmd in ([sys.executable, "-m", "venv", v], [os.path.join(v, "bin", "pip"), "install", "-q", "-r", os.path.join(ROOT, "requirements.txt")]):
            r = run(cmd, cwd=ROOT)
            if r.returncode != 0:
                fail(f"{' '.join(cmd[:3])} failed: {r.stderr[-200:]}")
        py = os.path.join(v, "bin", "python")
        r = run([py, "-m", "unittest", "discover", "-s", "tests", "-p", "test_intl_*.py", "-q"], cwd=ROOT)
        if r.returncode != 0:
            fail("S8 tests failed in the clean venv: " + r.stderr[-200:])
        r = run([py, os.path.join(ROOT, "scripts", "verify_s8.py"), "--only", "G4"], cwd=ROOT)
        if r.returncode != 0:
            fail("verify_s8.py failed in the clean venv")
    return "PASS", "venv + pip install + S8 tests + verify_s8 pass"


# ================================================================================================ runner
def block_network():
    def refuse(*a, **k):
        raise OSError("network blocked by verify_s8.py (offline gate)")
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


def gid_key(g):
    m = re.match(r"G(\d+)\.(\d+)(\w*)", g)
    return (int(m.group(1)), int(m.group(2)), m.group(3))


def group_of(g):
    return g.split(".")[0]


def selected(only):
    if not only:
        return sorted(GATES, key=gid_key)
    toks = [t.strip().upper() for t in only.split(",") if t.strip()]
    out = [g for g in GATES if any(g.upper() == t or g.upper().startswith(t + ".") or (len(t) > 3 and g.upper().startswith(t)) for t in toks)]
    return sorted(out, key=gid_key)


def run_one(gid):
    g = GATES[gid]
    t0 = time.time()
    try:
        status, detail = g["fn"]()
    except NotBuilt as e:
        status, detail = "FAIL", str(e)
    except Skip as e:
        status, detail = "SKIP", str(e)
    except AssertionError as e:
        status, detail = "FAIL", str(e) or "assertion failed"
    except Exception as e:  # noqa: BLE001
        status, detail = "FAIL", f"crash: {type(e).__name__}: {str(e)[:240]}"
        if os.environ.get("VERIFY_DEBUG"):
            traceback.print_exc()
    return status, " ".join(str(detail).split())[:600], time.time() - t0


def write_report(results, counts):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    lines = ["# S8 gate report", "", f"Generated by `scripts/verify_s8.py` on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
             f"Result: **{counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['SKIP']} SKIP**.", "",
             "| id | assertion | status | detail |", "|---|---|---|---|"]
    for gid, st, det, sec in results:
        lines.append(f"| {gid} | {GATES[gid]['title']} | {st} | {det.replace('|', '/')} |")
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated assertion groups or ids, e.g. G4,G6 or G5.2 (partial runs write no report)")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    ap.add_argument("--clean-machine", action="store_true", help="run G12.4 for real (venv + pip install; needs network)")
    a = ap.parse_args(argv)
    block_network()
    CLEAN_MACHINE["run"] = a.clean_machine
    os.environ.setdefault("ACRETIA_LLM_MODE", "replay")
    for k in [k for k in os.environ if re.search(r"(_API_KEY|_AUTH_TOKEN)$", k)]:
        del os.environ[k]
    ids = selected(a.only)
    if a.only and not ids:
        print(f"no assertion matches --only {a.only}")
        return 2
    # G0 first so later assertions can rely on D-030
    ids = [i for i in ids if group_of(i) == "G0"] + [i for i in ids if group_of(i) != "G0"]
    results = []
    for gid in ids:
        st, det, sec = run_one(gid)
        STATUS[gid] = st
        results.append((gid, st, det, sec))
        if not a.json:
            print(f"{st:4}  {gid:6} {GATES[gid]['name']}  ({sec:.1f}s)  {det[:200]}")
    results.sort(key=lambda r: gid_key(r[0]))
    counts = {k: sum(1 for r in results if r[1] == k) for k in ("PASS", "FAIL", "SKIP")}
    bad_skip = [r[0] for r in results if r[1] == "SKIP" and group_of(r[0]) in NEVER_SKIP_GROUPS]
    if not a.only:
        write_report(results, counts)
    if a.json:
        print(json.dumps({"counts": counts, "results": [dict(id=g, name=GATES[g]["name"], status=s, detail=d, seconds=round(t, 2))
                                                         for g, s, d, t in results]}, ensure_ascii=False, indent=1))
    else:
        print(f"\nS8 gate: {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['SKIP']} SKIP"
              + (f"; never-skippable skipped: {bad_skip}" if bad_skip else ""))
    return 0 if counts["FAIL"] == 0 and not bad_skip else 1


if __name__ == "__main__":
    sys.exit(main())
