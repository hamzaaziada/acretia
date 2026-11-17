#!/usr/bin/env python3
"""Stage 4 gate (Excel engine): implements docs/s4/GATE_SPEC.md assertions A1-J29.

Independence: facts are recomputed with openpyxl (cached values and formulas), raw zipfile + ElementTree, and the gate's own
arithmetic.  Builder `meta` is used only to locate sheets and cells.  No LLM or model call anywhere; seeds are fixed.

    python3 scripts/verify_s4.py [--offline] [--only A,B,...] [--no-suite]

Output: one line per assertion `PASS|FAIL|SKIP <id> <reason>`, a summary, and data/out/s4/gate.json.
Exit 0 only if no assertion FAILs (and, outside --offline, none is SKIPped).
A module or function that is missing at run time prints `FAIL missing <module.func>`; nothing is silently skipped.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import importlib
import io
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xesc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SEC_USER_AGENT", "Acretia hamza@meshpool.ai")   # approved for the SEC User-Agent only
random.seed(20261116)

OUT = ROOT / "data" / "out" / "s4"
RAW = ROOT / "data" / "raw"
BENCH10 = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "KO", "PG", "HD", "CAT"]
SUBSTITUTES = ["JNJ", "PEP", "CSCO", "ORCL"]
LBO_TARGETS = ["KO", "HD", "CAT"]
MERGER_PAIRS = [("PG", "KO"), ("HD", "CAT")]
COMPS_TARGET, COMPS_PEERS = "KO", ["PEP", "PG", "MDLZ", "CL"]
SB_COMMIT = "49b73a94775fb489063f60ca1865e3a650079a79"          # docs/ledger: license-and-repo-ledger.csv
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
GREEN, BLUE = "008000", "0000FF"

RESULTS: list[dict] = []
DETAILS: dict = {}
ARGS = None
T0 = time.time()


# ======================================================================================== plumbing
class Missing(Exception):
    pass


def need(modname: str, *attrs):
    try:
        m = importlib.import_module(modname)
    except Exception as e:   # noqa: BLE001
        raise Missing(f"{modname} ({type(e).__name__}: {str(e)[:80]})")
    for a in attrs:
        if not hasattr(m, a):
            raise Missing(f"{modname}.{a}")
    return m


def emit(id_: str, status: str, reason: str, secs: float = 0.0) -> None:
    reason = " ".join(str(reason).split())
    RESULTS.append({"id": id_, "status": status, "reason": reason, "seconds": round(secs, 2)})
    print(f"{status} {id_} {reason[:600]}", flush=True)


def run(id_: str, fn):
    t = time.time()
    try:
        r = fn()
        if isinstance(r, tuple):
            ok, reason = r
        else:
            ok, reason = bool(r), ""
        status = ok if ok in ("PASS", "FAIL", "SKIP") else ("PASS" if ok else "FAIL")
    except Missing as e:
        status, reason = "FAIL", f"missing {e}"
    except Exception as e:   # noqa: BLE001
        tb = traceback.extract_tb(e.__traceback__)
        where = f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"
        status, reason = "FAIL", f"exception {type(e).__name__}: {str(e)[:200]} @ {where}"
    emit(id_, status, reason, time.time() - t)


def wanted(section: str) -> bool:
    return ARGS.only is None or section in ARGS.only


def lo_available() -> bool:
    return bool(shutil.which("soffice") or shutil.which("libreoffice"))


def tolerant(a, b, rel=1e-9, ab=1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) or math.isnan(b):
            return False
        return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))
    return a == b


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ======================================================================================== OOXML / openpyxl helpers
def col_letter(c: int) -> str:
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 26 + ord(ch) - 64
    return n


def split_ref(ref: str):
    m = re.fullmatch(r"\$?([A-Z]{1,3})\$?(\d+)", ref)
    return int(m.group(2)), col_index(m.group(1))


def openpyxl_pair(data: bytes):
    import openpyxl
    wf = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    wv = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    return wf, wv


def label_row(ws, label: str, col: int = 1, start: int = 1, exact: bool = True):
    lab = label.strip().lower()
    for r in range(start, ws.max_row + 1):
        v = ws.cell(r, col).value
        if isinstance(v, str):
            t = v.strip().lower()
            if (t == lab) if exact else t.startswith(lab):
                return r
    return None


def name_target(wf, name: str):
    """Defined-name -> (sheet, 'C9')"""
    dn = wf.defined_names.get(name)
    if dn is None:
        return None
    m = re.match(r"'?([^'!]+)'?!\$?([A-Z]+)\$?(\d+)$", dn.attr_text)
    return (m.group(1), f"{m.group(2)}{m.group(3)}") if m else None


def name_value(wf, wv, name: str):
    t = name_target(wf, name)
    return wv[t[0]][t[1]].value if t else None


def period_columns(ws, rows=(5, 6)) -> dict:
    out = {}
    for r in rows:
        for c in range(3, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and re.fullmatch(r"FY\d{4}[AE]", v.strip()):
                out[v.strip()] = c
    return out


class Z:
    """Raw OOXML package: names, text parts, sheet-name -> part path."""

    def __init__(self, data: bytes):
        self.data = data
        self.z = zipfile.ZipFile(io.BytesIO(data))
        self.names = self.z.namelist()

    def read(self, n: str) -> bytes:
        return self.z.read(n)

    def text(self, n: str) -> str:
        return self.z.read(n).decode("utf-8")

    def sheets(self) -> list[tuple[str, str]]:
        wbx = ET.fromstring(self.read("xl/workbook.xml"))
        rels = ET.fromstring(self.read("xl/_rels/workbook.xml.rels"))
        rmap = {r.get("Id"): r.get("Target") for r in rels}
        out = []
        for s in wbx.find("m:sheets", NS):
            rid = s.get(f"{{{NS['r']}}}id")
            t = rmap[rid]
            t = t.lstrip("/")
            path = t if t.startswith("xl/") else "xl/" + t
            out.append((s.get("name"), path))
        return out

    def sheet_path(self, name: str) -> str:
        for n, p in self.sheets():
            if n == name:
                return p
        raise KeyError(name)


def rewrite_zip(data: bytes, changes: dict) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zin.namelist():
            zo.writestr(n, changes.get(n, zin.read(n)))
    return out.getvalue()


def _cell_re(ref: str):
    return re.compile(r'<c r="' + ref + r'"(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</c>)', re.S)


def patch_cell(data: bytes, sheet: str, ref: str, *, number=None, formula=None, cached=None, text=None, error=None, style=None) -> bytes:
    """Raw-XML rewrite of one <c>. Keeps the cell's style unless `style` is given. `cached` = <v> for a formula."""
    z = Z(data)
    path = z.sheet_path(sheet)
    x = z.text(path)
    m = _cell_re(ref).search(x)
    if not m:
        raise KeyError(f"{sheet}!{ref} not present in sheet XML")
    attrs = m.group("attrs")
    s = re.search(r'\ss="(\d+)"', attrs)
    s_attr = f' s="{style if style is not None else s.group(1)}"' if (style is not None or s) else ""
    if error is not None:
        new = f'<c r="{ref}"{s_attr} t="e">' + (f"<f>{xesc(formula)}</f>" if formula else "") + f"<v>{error}</v></c>"
    elif formula is not None:
        t_attr = ""
        v = ""
        if cached is not None:
            if isinstance(cached, str):
                t_attr = ' t="str"'
                v = f"<v>{xesc(cached)}</v>"
            else:
                v = f"<v>{cached!r}</v>"
        new = f'<c r="{ref}"{s_attr}{t_attr}><f>{xesc(formula)}</f>{v}</c>'
    elif text is not None:
        new = f'<c r="{ref}"{s_attr} t="inlineStr"><is><t xml:space="preserve">{xesc(text)}</t></is></c>'
    else:
        new = f'<c r="{ref}"{s_attr}><v>{number!r}</v></c>'
    return rewrite_zip(data, {path: (x[:m.start()] + new + x[m.end():]).encode("utf-8")})


def cell_xml(data: bytes, sheet: str, ref: str) -> str:
    z = Z(data)
    m = _cell_re(ref).search(z.text(z.sheet_path(sheet)))
    return m.group(0) if m else ""


def cached_number(data: bytes, sheet: str, ref: str):
    import openpyxl
    wv = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    return wv[sheet][ref].value


# ---- precedent graph, built here from openpyxl formulas (independent of om.wbgraph / om.formula)
_REF_RE = re.compile(r"(?:(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?(\$?[A-Z]{1,3}\$?\d+)(?::(\$?[A-Z]{1,3}\$?\d+))?(?![A-Za-z0-9_(])")


def precedents_of(wf, sheet: str, formula: str, names: dict, maxcells=4000):
    f = re.sub(r'"[^"]*"', '""', formula)
    out = set()
    for m in re.finditer(r"(?<![A-Za-z0-9_.!'$])" + _REF_RE.pattern, f):
        sh = (m.group(1) or "").replace("''", "'") or m.group(2) or sheet
        a, b = m.group(3), m.group(4) or m.group(3)
        if sh not in wf.sheetnames:
            continue
        (r1, c1), (r2, c2) = split_ref(a), split_ref(b)
        r1, r2, c1, c2 = min(r1, r2), max(r1, r2), min(c1, c2), max(c1, c2)
        if (r2 - r1 + 1) * (c2 - c1 + 1) > maxcells:
            continue
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((sh, r, c))
    for tok in re.findall(r"(?<![A-Za-z0-9_.!'$])([A-Za-z_][A-Za-z0-9_.]*)(?![A-Za-z0-9_.(!])", f):
        if tok in names:
            sh, ref = names[tok]
            out.add((sh, *split_ref(ref)))
    return out


def tainted_by_sheet(wf, source_sheet: str) -> set:
    """All cells that (transitively) depend on any cell of `source_sheet`."""
    names = {}
    for n in wf.defined_names:
        t = name_target(wf, n)
        if t:
            names[n] = t
    rev: dict = {}
    for ws in wf.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    for p in precedents_of(wf, ws.title, c.value, names):
                        rev.setdefault(p, []).append((ws.title, c.row, c.column))
    seen = set()
    stack = [k for k in rev if k[0] == source_sheet]
    while stack:
        k = stack.pop()
        for d in rev.get(k, ()):
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


def mentions(strings, sheet: str, ref: str) -> bool:
    """Does any reported location string name `sheet!ref` (directly or inside a range)? Sheet names may be quoted or not."""
    r0, c0 = split_ref(ref)
    pat = re.compile(r"(?:^|[^A-Za-z0-9_])'?" + re.escape(sheet) + r"'?!\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?")
    for s in strings:
        for m in pat.finditer(str(s)):
            c1, r1 = col_index(m.group(1)), int(m.group(2))
            c2, r2 = (col_index(m.group(3)), int(m.group(4))) if m.group(3) else (c1, r1)
            if min(r1, r2) <= r0 <= max(r1, r2) and min(c1, c2) <= c0 <= max(c1, c2):
                return True
    return False


# ======================================================================================== fixtures
def _fact(val, end, start=None, form="10-K", filed=None, accn="0000000001-25-000001"):
    d = {"val": val, "end": end, "form": form, "accn": accn, "filed": filed or f"{int(end[:4]) + 1}-02-15"}
    if start:
        d["start"] = start
    return d


def syn_cf(scale: float = 1.0, years=(2020, 2021, 2022, 2023, 2024), *, name="Synco", cik=1234, shares=None, price=None,
           options=None, negative=False) -> dict:
    """Offline fixture: tests/test_model3.py::synthetic_companyfacts, scaled; optional share data for comps."""
    from tests.test_model3 import synthetic_companyfacts
    cf = synthetic_companyfacts(years)
    for concept, body in cf["facts"]["us-gaap"].items():
        for unit, rows in body["units"].items():
            for r in rows:
                if unit == "USD":
                    r["val"] = r["val"] * scale
                    if negative and concept in ("OperatingIncomeLoss", "NetIncomeLoss", "GrossProfit"):
                        r["val"] = -abs(r["val"]) if concept != "GrossProfit" else r["val"]
                elif unit == "USD/shares":
                    r["val"] = r["val"] * scale          # EPS follows net income; diluted share counts are not scaled
                    if negative and concept == "EarningsPerShareDiluted":
                        r["val"] = -abs(r["val"])
    cf["entityName"] = name
    cf["cik"] = cik
    if shares:
        last = f"{years[-1]}-12-31"
        dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_fact(shares, f"{years[-1] + 1}-02-01")]}}}
        if price:
            dei["EntityPublicFloat"] = {"units": {"USD": [_fact(shares * price * 0.9, f"{years[-1]}-06-30")]}}
        cf["facts"]["dei"] = dei
        if options:
            n, k = options
            cf["facts"]["us-gaap"]["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"] = {
                "units": {"shares": [_fact(n, last)]}}
            cf["facts"]["us-gaap"]["ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"] = {
                "units": {"USD/shares": [_fact(k, last)]}}
            cf["facts"]["us-gaap"]["ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"] = {
                "units": {"shares": [_fact(n * 0.5, last)]}}
    return cf


SYN_SCALES = [0.5, 0.8, 1.0, 1.3, 1.7, 2.0, 3.0, 5.0, 8.0, 13.0]


class WBX:
    def __init__(self, kind, label, data, meta, circ0=None, note=""):
        self.kind, self.label, self.data, self.meta, self.circ0, self.note = kind, label, data, meta, circ0, note


class Ctx:
    """Builds every workbook the gate needs, once, tolerating per-company failures (they become FAIL lines, not aborts)."""

    def __init__(self, offline: bool):
        self.offline = offline
        self.sec_ok = False
        self.sec_error = ""
        self.cfs: dict = {}
        self.substitutions: list = []
        self.m3: list[WBX] = []
        self.lbo: list[WBX] = []
        self.merger: list[WBX] = []
        self.comps: list[WBX] = []
        self.build_errors: list[str] = []
        self.syn_m3 = None            # (wb, meta, bytes) clean synthetic three-statement model
        self.syn_lbo = self.syn_merger = self.syn_comps = None
        self.stmts: dict = {}
        self.markets: dict = {}

    # ---------------------------------------------------------------- SEC
    def sec_cf(self, t: str):
        if t in self.cfs:
            return self.cfs[t]
        sec = need("om.sec", "SecClient")
        if not hasattr(self, "_sec"):
            self._sec = sec.SecClient(os.environ["SEC_USER_AGENT"], RAW / "sec")
            self._tick = {r["ticker"].upper(): int(r["cik"]) for r in self._sec.tickers()}
        cf = self._sec.companyfacts(self._tick[t])
        self.cfs[t] = cf
        return cf

    def probe_sec(self):
        try:
            self.sec_cf("KO")
            self.sec_ok = True
        except Exception as e:   # noqa: BLE001
            self.sec_ok, self.sec_error = False, f"{type(e).__name__}: {str(e)[:100]}"

    # ---------------------------------------------------------------- builders
    def _stm(self, t, cf, as_of=None):
        stm = need("om.statements", "build")
        key = (t, as_of)
        if key not in self.stmts:
            self.stmts[key] = stm.build(cf, t, as_of=as_of) if as_of else stm.build(cf, t)
        return self.stmts[key]

    def build_m3(self, label, s) -> WBX:
        m3 = need("om.model3", "build_workbook")
        wb, meta = m3.build_workbook(s)
        wb0, meta0 = m3.build_workbook(s, circ=0)
        return WBX("m3", label, wb.to_bytes(), meta, circ0=wb0.to_bytes())

    def build_universe(self):
        use_sec = (not self.offline) and self.sec_ok
        if use_sec:
            tickers = list(BENCH10)
            pool = list(SUBSTITUTES)
            i = 0
            while i < len(tickers):
                t = tickers[i]
                try:
                    s = self._stm(t, self.sec_cf(t))
                    self.m3.append(self.build_m3(t, s))
                except Exception as e:   # noqa: BLE001
                    reason = f"{type(e).__name__}: {str(e)[:100]}"
                    if pool:
                        sub = pool.pop(0)
                        self.substitutions.append(f"{t} -> {sub} ({reason})")
                        print(f"NOTE substituting {t} with {sub}: {reason}", flush=True)
                        tickers[i] = sub
                        continue
                    self.build_errors.append(f"m3 {t}: {reason}")
                i += 1
        else:
            for i, sc in enumerate(SYN_SCALES):
                cf = syn_cf(sc, name=f"Synco {i + 1}", cik=2000 + i)
                t = f"SYN{i + 1}"
                try:
                    self.m3.append(self.build_m3(t, self._stm(t, cf)))
                except Exception as e:   # noqa: BLE001
                    self.build_errors.append(f"m3 {t}: {type(e).__name__}: {str(e)[:100]}")
        # clean synthetic base for adversarial sections (always)
        m3 = need("om.model3", "build_workbook")
        s = self._stm("SYN0", syn_cf(1.0, name="Synco 0", cik=1999))
        wb, meta = m3.build_workbook(s)
        self.syn_m3 = (wb, meta, wb.to_bytes())
        wb0, meta0 = m3.build_workbook(s, circ=0)
        self.syn_m3_circ0 = (wb0, meta0, wb0.to_bytes())

    def market_for(self, t, cf):
        mk = need("om.market", "resolve")
        return mk.resolve(t, cf)

    def build_lbo(self):
        lbo = need("om.lbo", "build_workbook")
        if (not self.offline) and self.sec_ok:
            pool = [t for t in BENCH10 if t not in LBO_TARGETS]
            targets = list(LBO_TARGETS)
            i = 0
            while i < len(targets):
                t = targets[i]
                try:
                    cf = self.sec_cf(t)
                    s = self._stm(t, cf)
                    mkt = self.market_for(t, cf)
                    if mkt is None:
                        raise ValueError("no market price (no float proxy)")
                    wb, meta = lbo.build_workbook(s, market=mkt)
                    wb0, _ = lbo.build_workbook(s, market=mkt, circ=0)
                    self.lbo.append(WBX("lbo", t, wb.to_bytes(), meta, circ0=wb0.to_bytes(), note=f"price {mkt.get('price'):.2f} ({mkt.get('basis', '')})"))
                except Exception as e:   # noqa: BLE001
                    self.build_errors.append(f"lbo {t}: {type(e).__name__}: {str(e)[:160]}")
                i += 1
        else:
            for i, sc in enumerate([0.8, 1.0, 2.0]):
                t = f"SYN{i + 1}"
                cf = syn_cf(sc, name=f"Synco {i + 1}", cik=2000 + i)
                s = self._stm(f"L{t}", cf)
                mkt = {"price": 30.0 * sc, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"}
                try:
                    wb, meta = lbo.build_workbook(s, market=mkt)
                    wb0, _ = lbo.build_workbook(s, market=mkt, circ=0)
                    self.lbo.append(WBX("lbo", t, wb.to_bytes(), meta, circ0=wb0.to_bytes()))
                except Exception as e:   # noqa: BLE001
                    self.build_errors.append(f"lbo {t}: {type(e).__name__}: {str(e)[:160]}")
        s = self._stm("LBASE", syn_cf(1.0, name="Synco 0", cik=1999))
        mkt = {"price": 30.0, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"}
        wb, meta = lbo.build_workbook(s, market=mkt)
        self.syn_lbo = (wb, meta, wb.to_bytes())

    def build_merger(self):
        mg = need("om.merger", "build_workbook")
        if (not self.offline) and self.sec_ok:
            for a, t in MERGER_PAIRS:
                try:
                    cfa, cft = self.sec_cf(a), self.sec_cf(t)
                    ma, mt = self.market_for(a, cfa), self.market_for(t, cft)
                    if ma is None or mt is None:
                        raise ValueError("no market price for one side")
                    wb, meta = mg.build_workbook(self._stm(a, cfa), self._stm(t, cft), acq_market=ma, tgt_market=mt)
                    self.merger.append(WBX("merger", f"{a}+{t}", wb.to_bytes(), meta))
                except Exception as e:   # noqa: BLE001
                    self.build_errors.append(f"merger {a}+{t}: {type(e).__name__}: {str(e)[:160]}")
        else:
            for i, (sa, st) in enumerate([(2.0, 1.0), (3.0, 1.3)]):
                a, t = f"A{i + 1}", f"T{i + 1}"
                ma = {"price": 30.0 * sa, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"}
                mt = {"price": 30.0 * st, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"}
                try:
                    wb, meta = mg.build_workbook(self._stm(a, syn_cf(sa, name=f"Acq {i + 1}", cik=3000 + i)),
                                                 self._stm(t, syn_cf(st, name=f"Tgt {i + 1}", cik=3100 + i)), acq_market=ma, tgt_market=mt)
                    self.merger.append(WBX("merger", f"{a}+{t}", wb.to_bytes(), meta))
                except Exception as e:   # noqa: BLE001
                    self.build_errors.append(f"merger {a}+{t}: {type(e).__name__}: {str(e)[:160]}")
        wb, meta = mg.build_workbook(self._stm("MA", syn_cf(2.0, name="Acq 0", cik=3200)), self._stm("MT", syn_cf(1.0, name="Tgt 0", cik=3201)),
                                     acq_market={"price": 60.0, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"},
                                     tgt_market={"price": 30.0, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"})
        self.syn_merger = (wb, meta, wb.to_bytes())

    def comps_syn(self):
        """Target + 4 peers, one of them loss-making so that EV/EBIT and P/E must read NM; options in/out of the money."""
        cp = need("om.comps", "build_workbook")
        spec = [("TGT", 1.0, 100e6, (4e6, 12.0), False, 30.0), ("PA", 0.8, 80e6, (3e6, 20.0), False, 25.0), ("PB", 1.5, 140e6, (5e6, 60.0), False, 40.0),
                ("PC", 2.0, 220e6, (0.0, 0.0), False, 22.0), ("PD", 1.2, 90e6, (2e6, 5.0), True, 18.0)]
        cfs, mk = {}, {}
        for i, (t, sc, sh, opt, neg, px) in enumerate(spec):
            cfs[t] = syn_cf(sc, name=f"Peer {t}", cik=4000 + i, shares=sh, price=px, options=opt if opt[0] else None, negative=neg)
            mk[t] = {"price": px, "as_of": "2024-12-31", "source": "gate offline fixture (synthetic, not a quote)"}
        wb, meta = cp.build_workbook(("TGT", cfs["TGT"]), [(t, cfs[t]) for t in ("PA", "PB", "PC", "PD")], markets=mk)
        return WBX("comps", "TGT+4 synthetic", wb.to_bytes(), meta), (wb, meta, wb.to_bytes())

    def build_comps(self):
        cp = need("om.comps", "build_workbook")
        w_syn, self.syn_comps = self.comps_syn()
        self.comps_nm = w_syn
        if (not self.offline) and self.sec_ok:
            try:
                names = [COMPS_TARGET] + COMPS_PEERS
                cfs = {t: self.sec_cf(t) for t in names}
                mk = {t: self.market_for(t, cfs[t]) for t in names}
                bad = [t for t, m in mk.items() if m is None]
                if bad:
                    raise ValueError(f"no market price for {bad}")
                wb, meta = cp.build_workbook((COMPS_TARGET, cfs[COMPS_TARGET]), [(t, cfs[t]) for t in COMPS_PEERS], markets=mk)
                self.comps.append(WBX("comps", f"{COMPS_TARGET} vs {','.join(COMPS_PEERS)}", wb.to_bytes(), meta))
            except Exception as e:   # noqa: BLE001
                self.build_errors.append(f"comps {COMPS_TARGET}: {type(e).__name__}: {str(e)[:160]}")
        else:
            self.comps.append(w_syn)

    def all_clean(self) -> list[WBX]:
        return self.m3 + self.lbo + self.merger + self.comps


# ======================================================================================== A. tie-out and grading
def checks_cells(wf, wv):
    ws, wsv = wf["Checks"], wv["Checks"]
    out, master = [], None
    for r in range(1, ws.max_row + 1):
        lab = ws.cell(r, 1).value
        for c in range(3, ws.max_column + 1):
            f = ws.cell(r, c).value
            v = wsv.cell(r, c).value
            if isinstance(f, str) and f.startswith("=") and isinstance(v, str) and v in ("OK", "ERROR"):
                out.append(((r, c), v))
        if isinstance(lab, str) and "master" in lab.strip().lower() and master is None:
            for rr in (r, r + 1):
                for c in range(3, ws.max_column + 1):
                    if isinstance(wsv.cell(rr, c).value, str) and wsv.cell(rr, c).value in ("OK", "ERROR"):
                        master = (rr, c, wsv.cell(rr, c).value)
                        break
                if master:
                    break
    return out, master


def A1(cx: Ctx):
    mc = need("om.modelcheck", "grade")
    bad, n = [], 0
    for w in cx.m3:
        n += 1
        g = mc.grade(w.data)
        crit_fail = [x.get("id") for x in g["graders"] if x.get("critical") and x.get("passed") is False]
        if not g["production_ready"] or crit_fail or g["score"] < 95:
            bad.append(f"{w.label}: score {g['score']} ready={g['production_ready']} critical_failed={crit_fail}")
    cx.errors_m3 = cx.build_errors
    if len(cx.m3) < 10:
        bad.append(f"only {len(cx.m3)}/10 three-statement models built; build errors: {cx.build_errors[:3]}")
    return (not bad, f"{n - len([b for b in bad if ':' in b and 'only' not in b])}/10 models production_ready, score>=95" if not bad else "; ".join(bad[:4]))


def A2(cx: Ctx):
    bad, periods = [], 0
    for w in cx.m3:
        wf, wv = openpyxl_pair(w.data)
        bs = wv["BS"]
        ra, rl = label_row(bs, "Total assets"), label_row(bs, "Total liabilities & equity")
        if ra is None or rl is None:
            bad.append(f"{w.label}: BS rows not found")
            continue
        for c in range(3, bs.max_column + 1):
            a, l = bs.cell(ra, c).value, bs.cell(rl, c).value
            if num(a) and num(l):
                periods += 1
                if abs(a - l) > 0.5:
                    bad.append(f"{w.label} BS col {col_letter(c)}: assets {a:.2f} vs L&E {l:.2f}")
    return (not bad and periods > 0, f"balanced in {periods} company-periods (tol 0.5)" if not bad else "; ".join(bad[:4]))


def A3(cx: Ctx):
    bad, n = [], 0
    for w in cx.m3:
        wf, wv = openpyxl_pair(w.data)
        bs, cf = wv["BS"], wv["CF"]
        rb, rc = label_row(bs, "Cash & equivalents"), label_row(cf, "Ending cash")
        if rb is None or rc is None:
            bad.append(f"{w.label}: cash rows not found")
            continue
        for c in range(3, cf.max_column + 1):
            e, b = cf.cell(rc, c).value, bs.cell(rb, c).value
            if num(e) and num(b):
                n += 1
                if abs(e - b) > 0.5:
                    bad.append(f"{w.label} col {col_letter(c)}: CF ending cash {e:.2f} vs BS cash {b:.2f}")
    return (not bad and n > 0, f"CF ending cash = BS cash in {n} company-periods" if not bad else "; ".join(bad[:4]))


def A4(cx: Ctx):
    bad, total = [], 0
    for w in cx.all_clean():
        wf, wv = openpyxl_pair(w.data)
        if "Checks" not in wf.sheetnames:
            bad.append(f"{w.kind}:{w.label}: no Checks sheet")
            continue
        cells, master = checks_cells(wf, wv)
        total += len(cells)
        notok = [f"{col_letter(c)}{r}" for (r, c), v in cells if v != "OK"]
        if not cells:
            bad.append(f"{w.kind}:{w.label}: no check cells")
        if notok:
            bad.append(f"{w.kind}:{w.label}: not OK {notok[:3]}")
        if master is None or master[2] != "OK":
            bad.append(f"{w.kind}:{w.label}: master check {master}")
    return (not bad and total > 0, f"{total} check cells all OK, masters OK over {len(cx.all_clean())} workbooks" if not bad else "; ".join(bad[:4]))


# ======================================================================================== B. validator
def B5(cx: Ctx):
    vx = need("om.validate_xlsx", "validate")
    bad, hard = [], 0
    for w in cx.all_clean():
        r = vx.validate(w.data)
        hard += int(r["stats"].get("hardcoded_calc_cells", 0))
        if not r["passed"]:
            crit = [f.get("id") for f in r["findings"] if f.get("severity", "critical") == "critical"][:4]
            bad.append(f"{w.kind}:{w.label} findings {crit or [f.get('id') for f in r['findings'][:3]]}")
    if hard != 0:
        bad.append(f"hardcoded_calc_cells total {hard} != 0")
    return (not bad, f"validate passed on {len(cx.all_clean())} workbooks, hardcoded_calc_cells total 0" if not bad else "; ".join(bad[:4]))


def B6_scan(w: WBX) -> list[str]:
    probs = []
    z = Z(w.data)
    wf, wv = openpyxl_pair(w.data)
    for name, path in z.sheets():
        x = z.text(path)
        if re.search(r't="array"|t="dataTable"', x):
            probs.append(f"{name}: array/dataTable formula in XML")
        for m in re.finditer(r"<mergeCell ref=\"([A-Z]+\d+):([A-Z]+\d+)\"", x):
            (r1, c1), (r2, c2) = split_ref(m.group(1)), split_ref(m.group(2))
            ws = wf[name]
            hit = [ws.cell(r, c).coordinate for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)
                   if isinstance(ws.cell(r, c).value, str) and ws.cell(r, c).value.startswith("=")]
            if hit:
                probs.append(f"{name}: merged {m.group(1)}:{m.group(2)} covers formula {hit[0]}")
    green_bad = 0
    for ws in wf.worksheets:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if not (isinstance(v, str) and v.startswith("=")):
                    continue
                body = re.sub(r'"[^"]*"', '""', v)
                if "TABLE(" in body.upper():
                    probs.append(f"{ws.title}!{c.coordinate}: TABLE(")
                if re.search(r"\b(OFFSET|INDIRECT|RAND|RANDBETWEEN)\s*\(|\bNOW\s*\(|\bTODAY\s*\(", body, re.I):
                    probs.append(f"{ws.title}!{c.coordinate}: volatile function")
                if re.search(r"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!\$?[A-Z]{1,3}\$?\d+", body):
                    col = c.font.color.rgb if (c.font and c.font.color and isinstance(c.font.color.rgb, str)) else None
                    if not (col and col[-6:].upper() == GREEN):
                        green_bad += 1
                        if green_bad <= 3:
                            probs.append(f"{ws.title}!{c.coordinate}: cross-sheet formula not green (font {col})")
    if green_bad > 3:
        probs.append(f"... {green_bad} cross-sheet formula cells not green in total")
    return probs


def B6(cx: Ctx):
    bad = []
    for w in cx.all_clean():
        p = B6_scan(w)
        if p:
            bad.append(f"{w.kind}:{w.label} {p[:2]}")
    return (not bad, f"{len(cx.all_clean())} workbooks: no TABLE/array/dataTable, no merged-over-formula, no volatile, cross-sheet green" if not bad else "; ".join(bad[:3]))



def strip_breaker(xml: str):
    """IF(Circ=1,<average-balance>,<opening-balance>) -> <average-balance> everywhere (balanced-paren parse, nesting allowed)."""
    key = "IF(Circ=1,"
    n = 0
    while key in xml:
        i = xml.index(key)
        depth, j, commas = 1, i + len(key), []
        while depth:
            ch = xml[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 1:
                commas.append(j)
            j += 1
        a_end = commas[0]
        xml = xml[:i] + xml[i + len(key):a_end] + xml[j:]
        n += 1
    return xml, n


def find_cell(wf, sheet, pred, start_row=1):
    ws = wf[sheet]
    for row in ws.iter_rows(min_row=start_row):
        for c in row:
            if pred(c):
                return c
    return None


def B7(cx: Ctx):
    vx = need("om.validate_xlsx", "validate")
    wb, meta, base = cx.syn_m3
    wf, wv = openpyxl_pair(base)
    clean = vx.validate(base)
    if not clean["passed"]:
        return False, f"clean synthetic model does not pass validate: {[f.get('id') for f in clean['findings'][:3]]}"
    H = len(meta["years"])
    rows = meta["rows"]
    outcomes, bad = [], []

    def expect(label, data, ids):
        r = vx.validate(data)
        got = {f.get("id") for f in r["findings"]}
        ok = (not r["passed"]) and bool(got & set(ids))
        outcomes.append(f"{label}:{'ok' if ok else 'MISSED'}")
        if not ok:
            bad.append(f"{label}: passed={r['passed']} expected one of {ids}, got {sorted(got)[:6]}")

    # 1 hard-coded number replacing a projection formula
    c = 3 + H + 1
    ref = f"{col_letter(c)}{rows['IS']['rev']}"
    expect("hardcode", patch_cell(base, "IS", ref, number=round(float(wv["IS"][ref].value), 2)), ["hardcode.calc", "modelcheck.consistency"])
    # 2 data table / TABLE() in a sensitivity cell, 3 typed number in a sensitivity cell
    ws = wf["DCF"]
    grid = None
    for r in range(1, ws.max_row + 1):
        if isinstance(ws.cell(r, 1).value, str) and "sensitiv" in ws.cell(r, 1).value.lower():
            for rr in range(r + 1, r + 12):
                for cc in range(3, 9):
                    v = ws.cell(rr, cc).value
                    if isinstance(v, str) and v.startswith("=") and "(" in v and rr > r + 2 and cc > 3:
                        grid = (rr, cc)
                        break
                if grid:
                    break
        if grid:
            break
    if grid is None:
        bad.append("could not locate a DCF sensitivity grid cell")
    else:
        gref = f"{col_letter(grid[1])}{grid[0]}"
        raw = patch_cell(base, "DCF", gref, formula="TABLE(C5,C6)", cached=1.0)
        z = Z(raw)
        p = z.sheet_path("DCF")
        x = z.text(p)
        x2 = x.replace(f'<c r="{gref}"', f'<c r="{gref}"', 1)
        x2 = re.sub(r'(<c r="' + gref + r'"[^>]*>)<f>[^<]*</f>', r'\1<f t="dataTable" ref="' + gref + '" dt2D="1" dtr="1" r1="C5" r2="C6"/>', x2, count=1)
        expect("dataTable", rewrite_zip(raw, {p: x2.encode()}), ["sensitivity.table"])
        expect("TABLE()", raw, ["sensitivity.table"])
        expect("sens-typed", patch_cell(base, "DCF", gref, number=round(float(wv["DCF"][gref].value or 1.0), 2)), ["sensitivity.live"])
    # 4 cross-sheet link recoloured black
    link = find_cell(wf, "IS", lambda c: isinstance(c.value, str) and c.value.startswith("=") and "!" in c.value and c.column > 3 + H)
    black = find_cell(wf, "IS", lambda c: isinstance(c.value, str) and c.value.startswith("=") and "!" not in c.value and c.column > 3 + H
                      and c.number_format == link.number_format)
    zx = Z(base)
    sx = zx.text(zx.sheet_path("IS"))
    st = re.search(r'<c r="' + black.coordinate + r'"[^>]*\ss="(\d+)"', sx).group(1)
    expect("link-black", patch_cell(base, "IS", link.coordinate, formula=link.value[1:], cached=wv["IS"][link.coordinate].value, style=int(st)), ["links.green"])
    # 5 sheet header switched to billions while linked from a millions sheet
    hdr = wf["BS"]["A5"].value
    expect("units", patch_cell(base, "BS", "A5", text=re.sub(r"millions", "billions", hdr, flags=re.I)), ["units"])
    # 6 circular reference without the breaker
    zd = Z(base)
    dp = zd.sheet_path("Debt")
    dx = zd.text(dp)
    dx2, n = strip_breaker(dx)
    if n == 0:
        bad.append("circularity: no IF(Circ=1,AVERAGE(..)) pattern found in Debt sheet XML")
    else:
        expect("no-breaker", rewrite_zip(base, {dp: dx2.encode()}), ["circularity", "modelcheck.circularity"])
    # 7 merged range over formulas
    zi = Z(base)
    ip = zi.sheet_path("IS")
    ix = zi.text(ip)
    anchor = re.search(r"<(conditionalFormatting|dataValidations|hyperlinks|printOptions|pageMargins|pageSetup|headerFooter|drawing|legacyDrawing)\b", ix[ix.index("</sheetData>"):])
    pos = ix.index("</sheetData>") + len("</sheetData>") + (anchor.start() if anchor else len(ix))
    if anchor is None:
        pos = ix.index("</worksheet>")
    else:
        pos = ix.index("</sheetData>") + anchor.start()
    mref = f"{col_letter(3 + H)}{rows['IS']['rev']}:{col_letter(4 + H)}{rows['IS']['rev']}"
    ix2 = ix[:pos] + f'<mergeCells count="1"><mergeCell ref="{mref}"/></mergeCells>' + ix[pos:]
    expect("merged", rewrite_zip(base, {ip: ix2.encode()}), ["noise.merged"])
    return (not bad, f"7 mutations all rejected with the expected finding id ({', '.join(outcomes)})" if not bad else "; ".join(bad[:5]))


# ======================================================================================== C. three engines
def C8(cx: Ctx):
    rc = need("om.recalc", "compare")
    if not lo_available():
        return ("SKIP", "LibreOffice (soffice) not installed") if cx.offline else (False, "LibreOffice not available (required outside --offline)")
    bad, tot, fm = [], 0, {}
    items = [(w, w.circ0 or w.data) for w in cx.all_clean()]
    for w, data in items:
        r = rc.compare(data)
        e = r.get("engines", {})
        lo = e.get("libreoffice", {})
        fm = e.get("formulon", {})
        tot += r.get("compared_cells", 0)
        if not lo.get("available"):
            bad.append(f"{w.kind}:{w.label} LibreOffice engine unavailable: {lo.get('reason')}")
        if not r.get("agree") or r.get("divergences"):
            bad.append(f"{w.kind}:{w.label} divergences {len(r.get('divergences', []))} first {(r.get('divergences') or [{}])[0].get('cell')}")
        if not r.get("compared_cells"):
            bad.append(f"{w.kind}:{w.label} compared_cells = 0")
    fstat = "available" if fm.get("available") else f"unavailable ({fm.get('reason', '')[:60]})"
    return (not bad, f"{len(items)} circ-off workbooks agree, {tot} cells compared, formulon {fstat}" if not bad else "; ".join(bad[:3]) + f" | formulon {fstat}")


def C9(cx: Ctx):
    rc = need("om.recalc", "compare")
    if not lo_available():
        return ("SKIP", "LibreOffice (soffice) not installed") if cx.offline else (False, "LibreOffice not available")
    wb, meta, base = cx.syn_m3_circ0
    ref = f"{col_letter(3 + len(meta['years']) + 1)}{meta['rows']['IS']['rev']}"
    v = cached_number(base, "IS", ref)
    bad = patch_cell(base, "IS", ref, formula=openpyxl_pair(base)[0]["IS"][ref].value[1:], cached=float(v) + 7.0)
    r = rc.compare(bad)
    d = r.get("divergences", [])
    ok = (not r.get("agree")) and len(d) == 1 and str(d[0].get("cell", "")).replace("'", "") == f"IS!{ref}"
    return (ok, f"corrupted IS!{ref} reported exactly (1 divergence)" if ok else f"agree={r.get('agree')} divergences={[x.get('cell') for x in d][:5]} expected only IS!{ref}")


def C10(cx: Ctx):
    rc = need("om.recalc", "compare")
    bad, notes = [], []
    cases = [("m3", cx.syn_m3[1], cx.syn_m3[2]), ("lbo", cx.syn_lbo[1], cx.syn_lbo[2])]
    for label, meta, data in cases:
        wf, _ = openpyxl_pair(data)
        has_breaker = any(isinstance(c.value, str) and "Circ=1" in c.value for ws in wf.worksheets for row in ws.iter_rows() for c in row)
        if not has_breaker:
            bad.append(f"{label}: no Circ=1 breaker formulas, so not a circular build")
        r = rc.compare(data)
        cyc = (r.get("excluded") or {}).get("cycles") or []
        if not cyc:
            bad.append(f"{label}: compare lists no excluded cycle cells")
        if meta.get("converged") is not True:
            bad.append(f"{label}: meta converged={meta.get('converged')}")
        if not r.get("agree"):
            bad.append(f"{label}: non-cycle cells disagree ({len(r.get('divergences', []))})")
        notes.append(f"{label}: {len(cyc)} cycle cells excluded, converged in {meta.get('iterations')} iterations")
    return (not bad, "; ".join(notes) if not bad else "; ".join(bad[:4]))


# ======================================================================================== D. mechanics
def irr_bisect(cfs):
    def npv(r):
        return sum(c / (1 + r) ** i for i, c in enumerate(cfs))
    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def rowvals(ws, r, c0, c1):
    return [ws.cell(r, c).value for c in range(c0, c1 + 1)]


def D11_one(w: WBX) -> list[str]:
    bad = []
    wf, wv = openpyxl_pair(w.data)
    R, meta = w.meta["rows"], w.meta
    n = int(meta.get("projection_years", 5))
    ret, su, dbt = wv["Returns"], wv["Sources & Uses"], wv["Debt"]
    g = lambda ws, k, c=3: ws.cell(R[ws.title][k], c).value
    mom, irr, years = g(ret, "mom"), g(ret, "irr"), g(ret, "n")
    eq_out, eq_in = g(ret, "eq_out"), g(ret, "eq_in")
    if not all(num(x) for x in (mom, irr, years, eq_out, eq_in)):
        return [f"returns cells not numeric: {mom, irr, years, eq_out, eq_in}"]
    if abs(eq_out / eq_in - mom) > 1e-9 * max(1, abs(mom)):
        bad.append(f"MoM {mom} != equity out/in {eq_out / eq_in}")
    if abs(mom ** (1 / years) - 1 - irr) > 1e-6:
        bad.append(f"IRR {irr} != MoM^(1/years)-1 {mom ** (1 / years) - 1}")
    x_irr = g(ret, "irr_x")
    strip = [v for v in rowvals(ret, R["Returns"]["cf"], 3, 3 + int(years))]
    my = irr_bisect([float(v) for v in strip if num(v)]) if all(num(v) for v in strip) else None
    if not num(x_irr) or abs(x_irr - irr) > 1e-6:
        bad.append(f"IRR() cross-check row {x_irr} vs closed form {irr}")
    if my is None or abs(my - irr) > 1e-6:
        bad.append(f"gate IRR over sponsor cash-flow strip {my} vs model IRR {irr}")
    ev_out, debt_out, cash_out = g(ret, "ev_out"), g(ret, "debt_out"), g(ret, "cash_out")
    if abs(ev_out - debt_out + cash_out - eq_out) > 0.01:
        bad.append(f"exit equity {eq_out} != EV - debt + cash {ev_out - debt_out + cash_out}")
    # sources = uses
    uses = [g(su, k) for k in ("u_eq", "u_nd", "u_txn", "u_fin", "u_cash")]
    srcs = [g(su, k) for k in ("s_rev", "s_tlb", "s_sn", "s_pik", "s_eq")]
    tu, ts = g(su, "tot_u"), g(su, "tot_s")
    if abs(sum(uses) - tu) > 0.01 or abs(sum(srcs) - ts) > 0.01 or abs(tu - ts) > 0.01:
        bad.append(f"S&U: sum uses {sum(uses):.3f} / total uses {tu:.3f} / sum sources {sum(srcs):.3f} / total sources {ts:.3f}")
    # PIK
    rate = name_value(wf, wv, "PikRate")
    po, pe = R["Debt"]["pik_open"], R["Debt"]["pik_end"]
    pk = rowvals(dbt, pe, 3, 3 + n)
    if not num(rate):
        bad.append("PikRate named input not found")
    else:
        for t in range(1, n + 1):
            if abs(pk[t] - pk[t - 1] * (1 + rate)) > 0.01:
                bad.append(f"PIK year {t}: {pk[t]:.3f} != prior {pk[t - 1]:.3f} x (1+{rate})")
                break
    # TLB / sweep
    tlb = rowvals(dbt, R["Debt"]["tlb_end"], 3, 3 + n)
    if any(num(v) and v < -1e-6 for v in tlb):
        bad.append(f"TLB balance negative: {min(v for v in tlb if num(v))}")
    sweep = rowvals(dbt, R["Debt"]["tlb_sweep"], 4, 3 + n)
    avail = rowvals(dbt, R["Debt"]["sweep_av"], 4, 3 + n)
    for t, (s_, a_) in enumerate(zip(sweep, avail), 1):
        if s_ is None or a_ is None or s_ > a_ + 1e-6 or s_ < -1e-6:
            bad.append(f"sweep year {t}: {s_} exceeds excess cash {a_} (or negative)")
            break
    # attribution
    comp = [g(ret, k) for k in ("a_ebitda", "a_mult", "a_delev", "a_fees")]
    if abs(sum(comp) - (eq_out - eq_in)) > 0.01:
        bad.append(f"attribution sums {sum(comp):.3f} vs equity gain {eq_out - eq_in:.3f}")
    # sensitivity centres
    se = wv["Sensitivity"]
    cen = meta.get("centres") or {}
    for key, base in (("irr", irr), ("mom", mom), ("margin_irr", irr)):
        if key in cen:
            v = se[cen[key]].value
            if not num(v) or abs(v - base) > 1e-6:
                bad.append(f"sensitivity centre {key} {cen[key]} = {v} vs base {base}")
            f = wf["Sensitivity"][cen[key]].value
            if not (isinstance(f, str) and f.startswith("=")):
                bad.append(f"sensitivity centre {key} is not a formula")
        else:
            bad.append(f"no centre located for {key}")
    return bad


def D11(cx: Ctx):
    bad = []
    for w in cx.lbo:
        bad += [f"{w.label}: {b}" for b in D11_one(w)]
    if not cx.lbo:
        bad.append(f"no LBO workbook built: {[e for e in cx.build_errors if e.startswith('lbo')][:2]}")
    return (not bad, f"{len(cx.lbo)} LBO workbooks: IRR/MoM/IRR(), S=U, PIK, TLB, sweep, attribution, sensitivity centre all recomputed" if not bad else "; ".join(bad[:4]))


def lookup_sheet_cols(wf, name):
    return wf[name]


def D12_one(w: WBX) -> list[str]:
    bad = []
    wf, wv = openpyxl_pair(w.data)
    R = w.meta["rows"]
    A, PF, SU, PP, PA = wv["Assumptions"], wv["Pro forma"], wv["Sources & Uses"], wv["Purchase price"], wv["PPA"]
    a, pf, su, ppa = R["Assumptions"], R["Pro forma"], R["Sources & Uses"], R["PPA"]
    t = A.cell(a["tax"], 3).value
    c = 4   # year 1 column
    phase1 = A.cell(a["syn_phase"], c).value
    rr = A.cell(a["syn_rr"], 3).value
    integ1 = A.cell(a["integ"], c).value
    debt_new = SU.cell(su["s_debt"], 3).value
    r_debt, r_cash = A.cell(a["rate_debt"], 3).value, A.cell(a["rate_cash"], 3).value
    cash_used = A.cell(a["cash_used"], 3).value
    acq_px = A.cell(a["acq_price"], 3).value
    stock = SU.cell(su["s_stock"], 3).value
    price, book, old_gw = PP.cell(R["PPA"]["price"], 3).value if False else PA.cell(ppa["price"], 3).value, PA.cell(ppa["book"], 3).value, PA.cell(ppa["old_gw"], 3).value
    wu_pct, life = A.cell(a["wu_pct"], 3).value, A.cell(a["life"], 3).value
    adj_tb = (book or 0.0) + (old_gw or 0.0)                       # old_gw is shown as a negative elimination
    wu = wu_pct * max(0.0, price - adj_tb)
    dtl = wu * t
    gw_expect = price - (adj_tb + wu - dtl)
    gw = PA.cell(ppa["goodwill"], 3).value
    if gw < -1e-6 or abs(gw - gw_expect) > 0.01:
        bad.append(f"goodwill {gw:.3f} vs recomputed price - (adj. book + write-up - DTL) = {gw_expect:.3f}")
    amort = -wu / life
    new_sh = stock / acq_px
    if abs(new_sh - SU.cell(su["new_sh"], 3).value) > 1e-6:
        bad.append(f"new shares {SU.cell(su['new_sh'], 3).value} vs stock/price {new_sh}")
    pre = {"syn": rr * phase1, "integ": -integ1, "newint": -debt_new * r_debt, "forgone": -cash_used * r_cash, "amort": amort}
    for k, v in pre.items():
        got = PF.cell(pf[k], c).value
        if abs(got - v) > 0.005:
            bad.append(f"pre-tax {k}: model {got:.4f} vs recomputed {v:.4f}")
    a_ni, t_ni, a_sh = PF.cell(pf["a_ni"], c).value, PF.cell(pf["t_ni"], c).value, PF.cell(pf["a_sh"], c).value
    pf_ni = a_ni + t_ni + sum(pre.values()) * (1 - t)
    eps = pf_ni / (a_sh + new_sh)
    m_eps = PF.cell(pf["pf_eps"], c).value
    if abs(eps - m_eps) > 0.005:
        bad.append(f"pro forma EPS year 1: model {m_eps:.4f} vs recomputed {eps:.4f}")
    sa = a_ni / a_sh
    acc = eps / sa - 1
    m_acc = PF.cell(pf["acc_p"], c).value
    if abs(acc - m_acc) > 1e-4:
        bad.append(f"accretion % model {m_acc:.5f} vs recomputed {acc:.5f}")
    if (m_eps > PF.cell(pf["sa_eps"], c).value) != (m_acc > 0):
        bad.append("accretion sign inconsistent with EPS comparison")
    # sensitivity centre
    se = wv["Sensitivity"]
    cr, cc = R["Sensitivity"]["g1_centre"], R["Sensitivity"]["g1_centre_col"]
    cr2, cc2 = R["Sensitivity"]["g2_centre"], R["Sensitivity"]["g2_centre_col"]
    for rr_, cc_ in ((cr, cc), (cr2, cc2)):
        v = se.cell(rr_, cc_).value
        if not num(v) or abs(v - m_acc) > 1e-6:
            bad.append(f"sensitivity centre {col_letter(cc_)}{rr_} = {v} vs base accretion {m_acc}")
        f = wf["Sensitivity"].cell(rr_, cc_).value
        if not (isinstance(f, str) and f.startswith("=")):
            bad.append(f"sensitivity centre {col_letter(cc_)}{rr_} is not a formula")
    # breakeven plug: set run-rate synergies to the breakeven requirement, recalc with an independent engine
    be = wv["Breakeven"].cell(R["Breakeven"]["be_pre"], c).value
    if not (num(phase1) and phase1 > 0 and num(be)):
        bad.append(f"cannot plug breakeven (phase1={phase1}, breakeven={be})")
    else:
        import openpyxl
        wb2 = openpyxl.load_workbook(io.BytesIO(w.data))
        wb2["Assumptions"].cell(a["syn_rr"], 3).value = be / phase1
        buf = io.BytesIO()
        wb2.save(buf)
        rc = need("om.recalc", "libreoffice_values", "om_values")
        key = ("Pro forma", pf["acc_p"], c)
        vals, engine = (rc.libreoffice_values(buf.getvalue())[0], "LibreOffice") if lo_available() else (None, "")
        if vals is None:
            vals, engine = rc.om_values(buf.getvalue()), "om.formula"
        got = vals.get(key)
        if not num(got) or abs(got) >= 1e-4:
            bad.append(f"after plugging breakeven synergies ({be:.3f} pre-tax y1) accretion is {got} ({engine}), expected |.|<0.01%")
    return bad


def D12(cx: Ctx):
    bad = []
    for w in cx.merger:
        try:
            bad += [f"{w.label}: {b}" for b in D12_one(w)]
        except Exception as e:   # noqa: BLE001
            tb = traceback.extract_tb(e.__traceback__)[-1]
            bad.append(f"{w.label}: cannot recompute, a located cell is empty/non-numeric ({type(e).__name__}: {e} @ verify_s4.py:{tb.lineno} `{tb.line}`)")
    if not cx.merger:
        bad.append(f"no merger workbook built: {[e for e in cx.build_errors if e.startswith('merger')][:2]}")
    return (not bad, f"{len(cx.merger)} merger workbooks: pro forma EPS, accretion, goodwill, breakeven plug, sensitivity centres recomputed (integration costs included in EPS)" if not bad else "; ".join(bad[:4]))


MULTS = {"EV / Revenue LTM": ("ev", "rev_ltm", "NMCapEVRev"), "EV / Revenue CY": ("ev", "rev_cy", "NMCapEVRev"),
         "EV / EBITDA LTM": ("ev", "ebitda_ltm", "NMCapEVEBITDA"), "EV / EBITDA CY": ("ev", "ebitda_cy", "NMCapEVEBITDA"),
         "EV / EBIT LTM": ("ev", "ebit_ltm", "NMCapEVEBIT"), "EV / EBIT CY": ("ev", "ebit_cy", "NMCapEVEBIT"),
         "P / E LTM": ("px", "eps_ltm", "NMCapPE"), "P / E CY": ("px", "eps_cy", "NMCapPE")}


def D13_one(w: WBX) -> tuple[list[str], dict]:
    bad = []
    wf, wv = openpyxl_pair(w.data)
    R, meta = w.meta["rows"], w.meta
    EV_, CAL, CP = wv["Equity value"], wv["Calendarisation"], wv["Comps"]
    ev, cal, cp = R["Equity value"], R["Calendarisation"], R["Comps"]
    cols = {t: col_index(l) for t, l in meta["columns"].items()}
    nm_seen = 0
    for t, c in cols.items():
        g = lambda k: EV_.cell(ev[k], c).value
        px, basic, opt, k_, rsu, conv = g("price"), g("basic"), g("opt"), g("strike"), g("rsu"), g("conv")
        dil = basic + rsu + conv + (opt * (1 - k_ / px) if px > k_ and opt else 0.0)
        if abs(dil - g("dil")) > 1e-6 * max(1, abs(dil)):
            bad.append(f"{t}: diluted shares {g('dil')} vs TSM {dil}")
        eqv = px * dil
        debt = sum(EV_.cell(ev[k], c).value or 0 for k in ("lt_nc", "lt_c", "st_b", "cp", "fl"))
        evx = eqv + debt + (g("pref") or 0) + (g("mi") or 0) - (g("cash") or 0) - (g("sti") or 0)
        if abs(evx - g("ev")) > 1e-6 * max(1, abs(evx)):
            bad.append(f"{t}: EV {g('ev')} vs equity + debt + pref + NCI - cash {evx}")
    # peer multiples, NM, quartiles
    caps = {n: name_value(wf, wv, n) for n in ("NMCapEVRev", "NMCapEVEBITDA", "NMCapEVEBIT", "NMCapPE")}
    hdr = {CP.cell(5, c).value: c for c in range(3, CP.max_column + 1) if isinstance(CP.cell(5, c).value, str)}
    peers = [t for t in meta["peers"]]
    # peer rows: those whose column B ticker is a peer
    prow = {CP.cell(r, 2).value: r for r in range(cp["peer_first"], cp["peer_first"] + len(peers) + 4) if CP.cell(r, 2).value in peers}
    if len(prow) != len(peers):
        bad.append(f"peer rows located {sorted(prow)} vs peers {peers}")
    for label, (num_k, den_k, cap_n) in MULTS.items():
        if label not in hdr:
            bad.append(f"Comps header {label!r} missing")
            continue
        c = hdr[label]
        valid = []
        for t, r in prow.items():
            tc = cols[t]
            numer = EV_.cell(ev["ev"], tc).value if num_k == "ev" else EV_.cell(ev["price"], tc).value
            den = CAL.cell(cal[den_k], tc).value
            got = CP.cell(r, c).value
            if den <= 0 or numer <= 0 or numer / den > caps[cap_n]:
                if got != "NM":
                    bad.append(f"{t} {label}: expected NM (den {den:.3f}, num {numer:.3f}) got {got!r}")
                else:
                    nm_seen += 1
            else:
                if not num(got) or abs(got - numer / den) > 1e-6 * max(1, numer / den):
                    bad.append(f"{t} {label}: {got!r} vs {numer / den:.4f}")
                else:
                    valid.append(numer / den)
        stats = {"max": max(valid) if valid else "NM", "min": min(valid) if valid else "NM", "mean": statistics.mean(valid) if valid else "NM",
                 "median": statistics.median(valid) if valid else "NM"}
        if len(valid) >= 2:
            q = statistics.quantiles(valid, n=4, method="inclusive")
            stats["q1"], stats["q3"] = q[0], q[2]
        elif len(valid) == 1:
            stats["q1"] = stats["q3"] = valid[0]
        else:
            stats["q1"] = stats["q3"] = "NM"
        for k, exp in stats.items():
            got = CP.cell(cp[k], c).value
            if exp == "NM":
                if got != "NM":
                    bad.append(f"{label} {k}: expected NM got {got!r}")
            elif not num(got) or abs(got - exp) > 1e-6 * max(1, abs(exp)):
                bad.append(f"{label} {k}: {got!r} vs statistics.quantiles/mean {exp:.5f} (n={len(valid)})")
        nn = CP.cell(cp["n"], c).value
        if nn != len(valid):
            bad.append(f"{label} peer count {nn} vs {len(valid)}")
    return bad, {"nm_cells": nm_seen}


def D13(cx: Ctx):
    bad, nm = [], 0
    ws = list(cx.comps) + ([cx.comps_nm] if cx.comps_nm is not None and cx.comps_nm not in cx.comps else [])
    for w in ws:
        b, info = D13_one(w)
        nm += info["nm_cells"]
        bad += [f"{w.label}: {x}" for x in b]
    if not cx.comps:
        bad.append(f"no comps workbook built: {[e for e in cx.build_errors if e.startswith('comps')][:2]}")
    if nm == 0:
        bad.append("no NM cell was exercised in any comps workbook")
    return (not bad, f"{len(ws)} comps workbooks: TSM, EV bridge, NM rule ({nm} NM cells), quartiles (statistics.quantiles inclusive) all match" if not bad else "; ".join(bad[:4]))


# ======================================================================================== E. planted-error audit
def grade_and_validate(data: bytes):
    mc = need("om.modelcheck", "grade")
    vx = need("om.validate_xlsx", "validate")
    g = mc.grade(data)
    v = vx.validate(data)
    locs, ids = [], []
    for r in g["graders"]:
        if r.get("passed") is False:
            ids.append(r.get("id"))
            locs += list(r.get("cells") or [])
    for f in v["findings"]:
        ids.append(f.get("id"))
        if f.get("sheet") and f.get("cell"):
            locs.append(f"{f['sheet']}!{f['cell']}")
        locs += [str(x) for x in (f.get("cells") or [])]
        if f.get("where"):
            locs.append(str(f["where"]))
        if f.get("detail"):
            locs.append(str(f["detail"]))
    caught = (not g["production_ready"]) or (not v["passed"]) or any(r.get("passed") is False for r in g["graders"])
    return caught, ids, locs, g, v


def E14(cx: Ctx):
    bn = need("om.bench", "audit", "plant", "PLANTS")
    wb, meta, data = cx.syn_m3
    a = bn.audit(wb, meta)
    bad = []
    structural = [r["kind"] for r in a["rows"] if r.get("located") is None]
    if not a.get("clean_passes"):
        bad.append("clean model fails the audit's own control")
    if a["planted"] < 10 or a["caught"] != a["planted"]:
        bad.append(f"audit reports planted {a['planted']} caught {a['caught']}")
    if a["located"] < a["planted"] - len(structural) or len(structural) > 2:
        bad.append(f"audit located {a['located']} of {a['planted'] - len(structural)} cell-level plants (structural, no cell: {structural})")
    # cross-check with my own reading: every planted copy differs from clean at the located cell, and the graders flag it there
    wf0, _ = openpyxl_pair(data)
    from om.xlsx import ref as xref
    checked = 0
    for kind, _title, expect in bn.PLANTS:
        w2, where = bn.plant(wb, meta, kind)
        d2 = w2.to_bytes()
        if where is None:
            wf2, _ = openpyxl_pair(d2)
            same = (wf2.calculation.iterate == wf0.calculation.iterate) and all(
                wf2["Debt"][c.coordinate].value == c.value for row in wf0["Debt"].iter_rows() for c in row)
            if same:
                bad.append(f"{kind}: planted copy is identical to clean (no structural change)")
            continue
        sheet, rc = where
        ref = xref(*rc)
        wf2, _ = openpyxl_pair(d2)
        c0, c2 = wf0[sheet][ref], wf2[sheet][ref]
        if (c0.value == c2.value and c0.font.color == c2.font.color and bool(c0.comment) == bool(c2.comment)
                and bool(c0.hyperlink) == bool(c2.hyperlink)):
            bad.append(f"{kind}: reported cell {sheet}!{ref} is identical in the clean build")
            continue
        caught, ids, locs, g, v = grade_and_validate(d2)
        if not (caught and mentions(locs, sheet, ref)):
            bad.append(f"{kind}: not caught/located at {sheet}!{ref} (flags {sorted(set(map(str, ids)))[:4]})")
        checked += 1
    return (not bad, f"{a['caught']}/{a['planted']} existing plants caught; {a['located']} cell-level plants located ({len(structural)} structural: {structural}); {checked} located cells verified real and different from the clean build" if not bad else "; ".join(bad[:4]))


def E15(cx: Ctx):
    bad, rows = [], []
    plants = []
    # ---- LBO
    wb, meta, data = cx.syn_lbo
    R = meta["rows"]
    wf, wv = openpyxl_pair(data)
    dcol = col_letter(6)   # year 3 (F) for the sweep; year 2 (E) for PIK
    ref = f"F{R['Debt']['tlb_sweep']}"
    plants.append(("lbo-sweep-hardcoded", "lbo", data, "Debt", ref, dict(number=round(float(wv["Debt"][ref].value), 1))))
    ref = f"E{R['Debt']['pik_acc']}"
    plants.append(("lbo-pik-cash-pay", "lbo", data, "Debt", ref, dict(formula=f"E{R['Debt']['pik_open']}*PikRate*0", cached=0.0)))
    ref = f"C{R['Returns']['ev_out']}"
    plants.append(("lbo-exit-ev-typed", "lbo", data, "Returns", ref, dict(number=round(float(wv["Returns"][ref].value), 1))))
    # ---- merger
    wb, meta, data = cx.syn_merger
    R = meta["rows"]
    wf, wv = openpyxl_pair(data)
    ref = f"E{R['Pro forma']['pf_new']}"
    plants.append(("merger-new-shares-typed", "merger", data, "Pro forma", ref, dict(number=round(float(wv["Pro forma"][ref].value), 1))))
    ref = f"C{R['PPA']['goodwill']}"
    plants.append(("merger-goodwill-plug", "merger", data, "PPA", ref, dict(number=round(float(wv["PPA"][ref].value), 0))))
    ref = f"D{R['Pro forma']['at_syn']}"
    plants.append(("merger-synergies-not-taxed", "merger", data, "Pro forma", ref, dict(formula=f"D{R['Pro forma']['syn']}", cached=float(wv["Pro forma"][f"D{R['Pro forma']['syn']}"].value))))
    # ---- comps
    wb, meta, data = cx.syn_comps
    R = meta["rows"]
    wf, wv = openpyxl_pair(data)
    ref = f"D{R['Equity value']['dil']}"
    plants.append(("comps-tsm-basic-shares", "comps", data, "Equity value", ref, dict(formula=f"D{R['Equity value']['basic']}", cached=float(wv["Equity value"][f"D{R['Equity value']['basic']}"].value))))
    ref = f"D{R['Equity value']['ev']}"
    ev = R["Equity value"]
    plants.append(("comps-ev-drops-cash", "comps", data, "Equity value", ref,
                   dict(formula=f"D{ev['eqv']}+D{ev['lt_nc']}+D{ev['lt_c']}+D{ev['st_b']}+D{ev['cp']}+D{ev['fl']}+D{ev['pref']}+D{ev['mi']}", cached=float(wv["Equity value"][ref].value) + 1.0)))
    # NM rule removed: peer PD (loss-making) EV/EBIT LTM without the NM guard
    pcol = meta["columns"]["PD"]
    prow = next(r for r in range(R["Comps"]["peer_first"], R["Comps"]["peer_first"] + 8) if wv["Comps"].cell(r, 2).value == "PD")
    hdr = {wv["Comps"].cell(5, c).value: c for c in range(3, wv["Comps"].max_column + 1)}
    mc_ = hdr["EV / EBIT LTM"]
    ref = f"{col_letter(mc_)}{prow}"
    plants.append(("comps-nm-rule-removed", "comps", data, "Comps", ref,
                   dict(formula=f"$E{prow}/Calendarisation!{pcol}{R['Calendarisation']['ebit_ltm']}", cached=-5.0)))
    caught_n = located_n = 0
    for name, kind, data, sheet, ref, kw in plants:
        clean_caught, ids0, locs0, g0, v0 = grade_and_validate(data)
        mutated = patch_cell(data, sheet, ref, **kw)
        wf0, _ = openpyxl_pair(data)
        wf1, _ = openpyxl_pair(mutated)
        if wf0[sheet][ref].value == wf1[sheet][ref].value:
            bad.append(f"{name}: mutation did not change {sheet}!{ref}")
            continue
        caught, ids, locs, g, v = grade_and_validate(mutated)
        # the clean base may already carry unrelated findings; only what the mutation adds counts
        new_ids = {str(i) for i in ids} - {str(i) for i in ids0}
        loc = mentions(locs, sheet, ref) and not mentions(locs0, sheet, ref)
        caught = bool(loc or new_ids or (caught and not clean_caught))
        caught_n += int(caught)
        located_n += int(loc)
        rows.append({"plant": name, "cell": f"{sheet}!{ref}", "caught": caught, "located": loc, "flags": sorted({str(i) for i in ids})})
        if not caught:
            bad.append(f"{name} NOT caught at {sheet}!{ref}")
        elif not loc:
            bad.append(f"{name} caught ({sorted({str(i) for i in ids})[:3]}) but not located at {sheet}!{ref}")
    DETAILS["E15"] = rows
    n = len(plants)
    ok = (not bad) and caught_n == n and n >= 9 and located_n / n >= 0.9
    return (ok, f"caught {caught_n}/{n}, located {located_n}/{n} (>=9 new plants, >=90% located)" if ok else
            f"caught {caught_n}/{n}, located {located_n}/{n}: " + "; ".join(bad[:5]))


# ======================================================================================== F. existing workbooks
def F16(cx: Ctx):
    wg = need("om.wbgraph", "graph")
    ct = need("om.contracts", "WorkbookGraph")
    wb, meta, data = cx.syn_m3
    g = wg.graph(data)
    d = g.to_dict() if hasattr(g, "to_dict") else g
    ct.WorkbookGraph.from_dict(copy.deepcopy(d)).validate()
    wf, wv = openpyxl_pair(data)
    H = len(meta["years"])
    c = col_letter(3 + H + 1)
    rev, ebitda = f"IS!{c}{meta['rows']['IS']['rev']}", f"IS!{c}{meta['rows']['IS']['ebitda']}"
    r_f = label_row(wf["DCF"], "Unlevered free cash flow")
    fcf = f"DCF!{c}{r_f}" if r_f else None
    edges = d["edges"]

    def expand(entry):
        m = re.fullmatch(r"(.+)!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)", entry)
        if not m:
            return [entry.replace("$", "")]
        sh = m.group(1)
        return [f"{sh}!{col_letter(cc)}{rr}" for rr in range(int(m.group(3)), int(m.group(5)) + 1) for cc in range(col_index(m.group(2)), col_index(m.group(4)) + 1)]

    def reaches(src, dst):
        seen, st = {src}, [src]
        while st:
            k = st.pop()
            if k == dst:
                return True
            for p in edges.get(k, ()):
                for q in expand(p):
                    if q not in seen:
                        seen.add(q)
                        st.append(q)
        return False
    def ancestors(src):
        seen, st = set(), [src]
        while st:
            k = st.pop()
            for p in edges.get(k, ()):
                for q in expand(p):
                    if q not in seen:
                        seen.add(q)
                        st.append(q)
        return seen
    cand = [f"DCF!{col_letter(cc)}{r_f}" for cc in range(3, wf["DCF"].max_column + 1)] if r_f else []
    direct = {q for p in edges.get(ebitda, ()) for q in expand(p)}
    fcf_anc = set().union(*[ancestors(x) for x in cand]) if cand else set()
    rev_to_ebitda = reaches(ebitda, rev)
    rev_to_fcf = any(x == rev or rev in ancestors(x) for x in cand)
    ebitda_drivers_feed_fcf = bool(direct & fcf_anc) or ebitda in fcf_anc
    ok = rev_to_ebitda and rev_to_fcf and ebitda_drivers_feed_fcf
    return (ok, f"WorkbookGraph validates ({len(d['nodes'])} nodes, {len(edges)} formula nodes); independent traversal: {rev} -> {ebitda}; revenue -> DCF FCF; EBITDA drivers ({sorted(direct & fcf_anc)[:2]}) feed FCF (the IS EBITDA row itself is not a precedent of the DCF FCF row)" if ok
            else f"missing path: rev->ebitda {rev_to_ebitda}, rev->fcf {rev_to_fcf}, ebitda drivers->fcf {ebitda_drivers_feed_fcf} (fcf row {r_f})")


def F17(cx: Ctx):
    wg = need("om.wbgraph", "ask")
    wb, meta, data = cx.syn_m3
    wf, wv = openpyxl_pair(data)
    per = period_columns(wv["IS"])
    R = meta["rows"]
    rbs = label_row(wv["BS"], "Total assets")
    rdcf = label_row(wv["DCF"], "Implied value per share")
    qs = [("What is revenue in FY2025E?", f"IS!{col_letter(per['FY2025E'])}{R['IS']['rev']}"),
          ("What is EBITDA in FY2026E?", f"IS!{col_letter(per['FY2026E'])}{R['IS']['ebitda']}"),
          ("What is net income in FY2024A?", f"IS!{col_letter(per['FY2024A'])}{R['IS']['ni']}"),
          ("What are total assets in FY2027E?", f"BS!{col_letter(per['FY2027E'])}{rbs}"),
          ("What is the implied value per share?", f"DCF!C{rdcf}")]
    bad = []
    for q, exp in qs:
        r = wg.ask(data, q)
        cells = [str(x).replace("$", "") for x in (r.get("cells") or [])]
        sh, ref = exp.split("!")
        truth = wv[sh][ref].value
        vals = r.get("values") or []
        if not cells or cells[0] != exp or not vals or not num(vals[0]) or not tolerant(vals[0], truth, 1e-9):
            bad.append(f"{q!r}: got cells {cells[:2]} values {vals[:1]} expected {exp} = {truth}")
    r = wg.ask(data, "What is the airspeed velocity of an unladen swallow?")
    if r.get("cells") or r.get("values"):
        bad.append(f"unanswerable question returned cells {r.get('cells')} values {r.get('values')}")
    return (not bad, "5/5 questions answered with the correct cell and value; 1 unanswerable question returned no number" if not bad else "; ".join(bad[:4]))


def _sheet_parts(z: Z):
    return {p for _, p in z.sheets()}


def compare_edit(before: bytes, after: bytes, targets: set, label: str) -> list[str]:
    bad = []
    za, zb = Z(before), Z(after)
    if za.names != zb.names:
        bad.append(f"{label}: zip entry list/order changed")
    sheet_parts = _sheet_parts(za)
    for n in za.names:
        if n not in zb.names:
            continue
        if n not in sheet_parts:
            if za.read(n) != zb.read(n):
                bad.append(f"{label}: untouched part {n} differs")
            continue
        if za.read(n) == zb.read(n):
            continue
        ra, rb = ET.fromstring(za.read(n)), ET.fromstring(zb.read(n))
        sda, sdb = ra.find("m:sheetData", NS), rb.find("m:sheetData", NS)
        ra.remove(sda)
        rb.remove(sdb)
        if ET.canonicalize(ET.tostring(ra, encoding="unicode")) != ET.canonicalize(ET.tostring(rb, encoding="unicode")):
            bad.append(f"{label}: {n} differs outside sheetData")
        ca = {c.get("r"): c for row in sda for c in row}
        cb = {c.get("r"): c for row in sdb for c in row}
        if set(ca) != set(cb) or [r.attrib for r in sda] != [r.attrib for r in sdb]:
            bad.append(f"{label}: {n} cell set / row attributes changed")
            continue
        for ref, a in ca.items():
            b = cb[ref]
            if ET.canonicalize(ET.tostring(a, encoding="unicode")) == ET.canonicalize(ET.tostring(b, encoding="unicode")):
                continue
            key = f"{n}!{ref}"
            if (n, ref) in targets:
                continue
            fa, fb = a.find("m:f", NS), b.find("m:f", NS)
            same_f = (fa is None and fb is None) or (fa is not None and fb is not None and fa.text == fb.text and fa.attrib == fb.attrib)
            if not same_f or a.attrib != b.attrib:
                bad.append(f"{label}: {key} changed beyond <v>")
                if len(bad) > 6:
                    return bad
    return bad


def om_recalc_check(data: bytes, label: str) -> list[str]:
    rc = need("om.recalc", "om_values")
    vals = rc.om_values(data)
    wf, wv = openpyxl_pair(data)
    bad, n = [], 0
    for ws in wf.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    exp = vals.get((ws.title, c.row, c.column))
                    got = wv[ws.title].cell(c.row, c.column).value
                    if got is None:
                        continue
                    n += 1
                    if not tolerant(got, exp, 1e-7, 1e-7):
                        bad.append(f"{label}: {ws.title}!{c.coordinate} cached {got!r} vs om.formula {exp!r}")
                        if len(bad) > 3:
                            return bad
    if n == 0:
        bad.append(f"{label}: no cached formula values to compare")
    return bad


def authored_workbook() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "Inputs"
    a["A1"], a["B1"] = "Growth", 0.05
    a["A2"], a["B2"] = "Base revenue", 100.0
    a["A3"], a["B3"] = "Margin", 0.2
    c = wb.create_sheet("Calc")
    c["A1"], c["B1"], c["C1"], c["D1"] = "Line", "Y1", "Y2", "Y3"
    c["A2"] = "Revenue"
    c["B2"] = "=Inputs!B2*(1+Inputs!B1)"
    c["C2"] = "=B2*(1+Inputs!$B$1)"
    c["D2"] = "=C2*(1+Inputs!$B$1)"
    c["A3"] = "Profit"
    for col in "BCD":
        c[f"{col}3"] = f"={col}2*Inputs!$B$3"
    c["A4"] = "Total profit"
    c["B4"] = "=SUM(B3:D3)"
    c["A5"] = "Label"
    c["B5"] = '=IF(B4>60,"high","low")'
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if lo_available():
        d = tempfile.mkdtemp()
        p = Path(d) / "in.xlsx"
        p.write_bytes(data)
        out = Path(d) / "out"
        subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(out), str(p)], capture_output=True, timeout=120)
        q = out / "in.xlsx"
        if q.exists():
            data = q.read_bytes()
        shutil.rmtree(d, ignore_errors=True)
    return data


def F18(cx: Ctx):
    we = need("om.wbedit", "edit")
    bad, notes = [], []
    wb, meta, data = cx.syn_m3_circ0
    ref = f"{col_letter(3 + len(meta['years']))}{label_row(openpyxl_pair(data)[0]['Assumptions'], 'R&D')}"
    new = we.edit(data, {f"Assumptions!{ref}": 0.09})
    new = new[0] if isinstance(new, tuple) else new
    zt = Z(data)
    targets = {(zt.sheet_path("Assumptions"), ref)}
    bad += compare_edit(data, new, targets, "model3")
    wf1, wv1 = openpyxl_pair(new)
    if wv1["Assumptions"][ref].value != 0.09:
        bad.append(f"model3: edited cell value {wv1['Assumptions'][ref].value}")
    wv0 = openpyxl_pair(data)[1]
    changed = sum(1 for ws in wv0.worksheets for row in ws.iter_rows() for c in row if num(c.value) and not tolerant(c.value, wv1[ws.title][c.coordinate].value, 1e-12, 1e-12))
    if changed < 3:
        bad.append(f"model3: only {changed} cells changed after editing an input, dependents not refreshed")
    bad += om_recalc_check(new, "model3 full-recalc")
    notes.append(f"model3 edit {ref}: {changed} cells changed")
    # openpyxl-authored workbook with shared strings
    auth = authored_workbook()
    zs = Z(auth)
    has_ss = "xl/sharedStrings.xml" in zs.names
    new2 = we.edit(auth, {"Inputs!B1": 0.07})
    new2 = new2[0] if isinstance(new2, tuple) else new2
    t2 = {(Z(auth).sheet_path("Inputs"), "B1")}
    bad += compare_edit(auth, new2, t2, "authored")
    if not has_ss:
        bad.append("authored workbook has no sharedStrings part (fixture assumption violated)")
    wv2 = openpyxl_pair(new2)[1]
    if wv2["Inputs"]["B1"].value != 0.07:
        bad.append("authored: edited value not 0.07")
    bad += om_recalc_check(new2, "authored full-recalc")
    notes.append(f"authored (sharedStrings={has_ss}, LibreOffice round trip={lo_available()})")
    return (not bad, "; ".join(notes) + ": untouched parts byte-identical, only target <c> / dependent <v> changed, dependents equal om.formula recalculation" if not bad else "; ".join(bad[:4]))


def F19(cx: Ctx):
    rf = need("om.rollforward", "roll_forward")
    stm = need("om.statements", "build")
    mc = need("om.modelcheck", "grade")
    vx = need("om.validate_xlsx", "validate")
    m3 = need("om.model3", "build_workbook")
    cases = []
    if (not cx.offline) and cx.sec_ok:
        for t in ("KO", "HD"):
            cf = cx.sec_cf(t)
            new = cx._stm(t, cf)
            asof = new.years[-1]
            old = stm.build(cf, t, as_of=asof)
            cases.append((t, old, new))
    else:
        for i, sc in enumerate((1.0, 2.0)):
            t = f"R{i + 1}"
            new = stm.build(syn_cf(sc, name=f"Roll {i + 1}", cik=5000 + i), t)
            old = stm.build(syn_cf(sc, years=(2020, 2021, 2022, 2023), name=f"Roll {i + 1}", cik=5000 + i), t)
            cases.append((t, old, new))
    bad, notes = [], []
    for t, old, new in cases:
        if not (old.years[-1] < new.years[-1]):
            bad.append(f"{t}: as_of did not yield an older workbook ({old.years[-1]} vs {new.years[-1]})")
            continue
        wb, meta = m3.build_workbook(old)
        xb = wb.to_bytes()
        wf, wv = openpyxl_pair(xb)
        H = len(old.years)
        r_rd = label_row(wf["Assumptions"], "R&D")
        per = period_columns(wf["Assumptions"])
        y = new.years[-1].year + 1
        oc = per[f"FY{y}E"]
        raw = patch_cell(xb, "Assumptions", f"{col_letter(oc)}{r_rd}", number=0.0777)
        out, info = rf.roll_forward(raw, new, old_meta=meta)
        nf, nv = openpyxl_pair(out)
        nper = period_columns(nf["Assumptions"])
        nrd = label_row(nf["Assumptions"], "R&D")
        got = nv["Assumptions"].cell(nrd, nper[f"FY{y}E"]).value
        if not (num(got) and abs(got - 0.0777) < 1e-12):
            bad.append(f"{t}: user-edited FY{y}E R&D assumption became {got!r}")
        fy = new.years[-1].year
        if f"FY{fy}A" not in nper:
            bad.append(f"{t}: FY{fy}A is not an actual column in the rolled workbook ({sorted(nper)[:12]})")
        else:
            # the actual lives on Filings: blue typed value with a source comment and a filing link
            fs = nf["Filings"]
            hc = None
            for r in range(1, 9):
                for c in range(3, fs.max_column + 1):
                    v = fs.cell(r, c).value
                    if (isinstance(v, str) and f"FY{fy}" in v) or (isinstance(v, str) and v.startswith(str(fy))):
                        hc = c
                        break
                if hc:
                    break
            rr = label_row(fs, "Revenue", exact=False) or 9
            cell = fs.cell(rr, hc) if hc else None
            col = cell.font.color.rgb if cell is not None and cell.font and cell.font.color and isinstance(cell.font.color.rgb, str) else None
            if cell is None or not num(cell.value) or not (col and col[-6:].upper() == BLUE) or not cell.comment or not (cell.hyperlink and str(cell.hyperlink.target or cell.hyperlink.location or "").startswith("http")):
                bad.append(f"{t}: new actual FY{fy} on Filings not blue-with-comment-and-link (cell {cell.coordinate if cell is not None else None}, colour {col}, comment {bool(cell and cell.comment)}, link {bool(cell and cell.hyperlink)})")
        names = [s for s in nf.sheetnames]
        if not any(("roll" in s.lower() or "variance" in s.lower()) for s in names):
            bad.append(f"{t}: no roll-forward / variance sheet in {names}")
        g = mc.grade(out)
        v = vx.validate(out)
        cells, master = checks_cells(nf, nv)
        if not g["production_ready"] or not v["passed"] or not cells or any(val != "OK" for _, val in cells) or not master or master[2] != "OK":
            bad.append(f"{t}: rolled workbook fails A1-A4/B5 (ready={g['production_ready']}, validate={v['passed']}, checks {[x for x in cells if x[1] != 'OK'][:2]}, master {master})")
        notes.append(f"{t} FY{fy - 1}->FY{fy}")
    return (not bad and len(cases) == 2, f"rolled {', '.join(notes)}: new actual blue+comment+link, edited assumption survived, variance sheet present, grade/validate/checks pass" if not bad else "; ".join(bad[:4]))


# ======================================================================================== G. manifest and delivery
def deliver_all(cx: Ctx):
    if hasattr(cx, "delivered"):
        return cx.delivered
    dv = need("om.delivery", "deliver", "DeliveryBlocked")
    cx.deliver_root = Path(tempfile.mkdtemp(prefix="s4_deliver_"))
    cx.delivered = []
    cx.deliver_errors = []
    for i, w in enumerate(cx.all_clean()):
        out = cx.deliver_root / f"{i:02d}_{w.kind}_{re.sub(r'[^A-Za-z0-9]+', '_', w.label)}"
        try:
            r = dv.deliver(w.data, w.meta, out, name=f"{w.kind}-{i}", circ0_data=w.circ0)
            cx.delivered.append((w, r))
        except Exception as e:   # noqa: BLE001
            cx.deliver_errors.append(f"{w.kind}:{w.label}: {type(e).__name__}: {str(e)[:200]}")
    return cx.delivered


def G20(cx: Ctx):
    ct = need("om.contracts", "ModelManifest")
    delivered = deliver_all(cx)
    bad = list(cx.deliver_errors)
    n_out = 0
    for w, r in delivered:
        px, pm, pr = Path(r["xlsx"]), Path(r["manifest"]), Path(r["report"])
        if not (px.exists() and pm.exists() and pr.exists()):
            bad.append(f"{w.kind}:{w.label}: delivered files missing")
            continue
        raw = pm.read_text()
        man = ct.ModelManifest.from_dict(json.loads(raw))
        man.validate()
        d = man.to_dict()
        if d["workbook_sha256"] != hashlib.sha256(px.read_bytes()).hexdigest():
            bad.append(f"{w.kind}:{w.label}: manifest sha256 does not match the delivered file")
        wf, wv = openpyxl_pair(px.read_bytes())
        taint = tainted_by_sheet(wf, "Filings")
        for o in d["outputs"]:
            n_out += 1
            first = o["ref"].replace("$", "").split(":")[0]
            try:
                v = wv[o["sheet"]][first].value
            except KeyError:
                v = None
            if not num(v):
                bad.append(f"{w.kind}:{w.label}: output {o['id']} {o['sheet']}!{o['ref']} cached value {v!r} is not numeric")
                continue
            key = (o["sheet"], *split_ref(first))
            if key in taint and not any(str(c.get("source_url") or c.get("url") or "").startswith("http") for c in o.get("citations", [])):
                bad.append(f"{w.kind}:{w.label}: historical-derived output {o['id']} has no citation with a URL")
        if not d["outputs"]:
            bad.append(f"{w.kind}:{w.label}: manifest has no outputs")
    expected = len(cx.all_clean())
    return (not bad and len(delivered) == expected, f"{len(delivered)}/{expected} workbooks delivered (xlsx+manifest+report); manifests validate, sha256 match, {n_out} output cells numeric, historical outputs cited with URLs" if not bad else "; ".join(bad[:4]))


def G21(cx: Ctx):
    dv = need("om.delivery", "deliver", "DeliveryBlocked")
    wb, meta, data = cx.syn_m3_circ0
    tmp = Path(tempfile.mkdtemp(prefix="s4_block_"))
    bad = []
    # control: clean circ-off model delivers
    try:
        dv.deliver(data, meta, tmp / "control", name="control")
    except Exception as e:   # noqa: BLE001
        return False, f"control (clean workbook) was blocked: {type(e).__name__}: {str(e)[:150]}"
    rows = meta["rows"]
    ref = f"{col_letter(3 + len(meta['years']) + 1)}{rows['IS']['rev']}"
    div0 = patch_cell(data, "IS", ref, formula="1/0", error="#DIV/0!")
    wfc, wvc = openpyxl_pair(data)
    r_master = label_row(wfc["Checks"], "MASTER CHECK")
    r_chk = label_row(wfc["Checks"], "Balance sheet balances")
    failing = patch_cell(data, "Checks", f"{col_letter(3 + len(meta['years']) + 1)}{r_chk}", formula='IF(1=1,"ERROR","OK")', cached="ERROR")
    failing = patch_cell(failing, "Checks", f"C{r_master}", formula='IF(1=1,"ERROR","OK")', cached="ERROR")
    for label, mut in (("#DIV/0!", div0), ("failing check", failing)):
        out = tmp / label.replace(" ", "_").replace("#", "").replace("/", "")
        try:
            dv.deliver(mut, meta, out, name="blocked", circ0_data=mut)
            bad.append(f"{label}: delivery was NOT blocked")
        except dv.DeliveryBlocked:
            leftovers = [str(p) for p in out.rglob("*") if p.is_file()] if out.exists() else []
            if leftovers:
                bad.append(f"{label}: blocked but left files {leftovers[:3]}")
        except Exception as e:   # noqa: BLE001
            bad.append(f"{label}: raised {type(e).__name__} instead of DeliveryBlocked: {str(e)[:100]}")
    shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, "planted #DIV/0! and failing check both raise DeliveryBlocked and leave no files (clean control delivers)" if not bad else "; ".join(bad))


# ======================================================================================== H. polish
def delivered_books(cx: Ctx):
    """Delivered bytes for every clean workbook; a workbook the delivery gate refused is still polish-checked from the builder's bytes."""
    if hasattr(cx, "_books"):
        return cx._books
    got = {id(w): Path(r["xlsx"]).read_bytes() for w, r in deliver_all(cx)}
    cx._books = [(w, got.get(id(w), w.data)) for w in cx.all_clean()]
    return cx._books


def chart_parts_for(z: Z, sheet_path: str) -> list[str]:
    rel = sheet_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
    if rel not in z.names:
        return []
    out = []
    for r in ET.fromstring(z.read(rel)):
        if r.get("Type", "").endswith("/drawing"):
            dp = "xl/" + r.get("Target").replace("../", "")
            drel = dp.replace("drawings/", "drawings/_rels/") + ".rels"
            if drel in z.names:
                for r2 in ET.fromstring(z.read(drel)):
                    if r2.get("Type", "").endswith("/chart"):
                        out.append("xl/" + r2.get("Target").replace("../", ""))
    return out


def chart_info(z: Z, part: str):
    x = ET.fromstring(z.read(part))
    kinds = []
    for el in x.iter():
        tag = el.tag.split("}")[1]
        if tag in ("barChart", "lineChart", "areaChart", "scatterChart", "pieChart"):
            bd = el.find("c:barDir", NS)
            gp = el.find("c:grouping", NS)
            kinds.append((tag, bd.get("val") if bd is not None else None, gp.get("val") if gp is not None else None))
    vals = [f.text for ser in x.iter(f"{{{NS['c']}}}ser") for v in ser.findall("c:val", NS) for f in v.iter(f"{{{NS['c']}}}f")]
    nser = len(list(x.iter(f"{{{NS['c']}}}ser")))
    nval = sum(1 for ser in x.iter(f"{{{NS['c']}}}ser") if ser.find("c:val", NS) is not None)
    return kinds, vals, nser, nval


def refs_all_formula(wf, ref: str) -> list[str]:
    m = re.fullmatch(r"(?:'((?:[^']|'')+)'|([^!]+))!\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", ref)
    if not m:
        return [f"unparseable ref {ref}"]
    sh = (m.group(1) or "").replace("''", "'") or m.group(2)
    if sh not in wf.sheetnames:
        return [f"{ref}: sheet missing"]
    c1, r1 = col_index(m.group(3)), int(m.group(4))
    c2, r2 = (col_index(m.group(5)), int(m.group(6))) if m.group(5) else (c1, r1)
    bad = []
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            v = wf[sh].cell(r, c).value
            if not (isinstance(v, str) and v.startswith("=")):
                bad.append(f"{sh}!{col_letter(c)}{r} typed {v!r}")
    return bad


CHART_NEEDS = {"m3": {"trend", "waterfall", "football"}, "lbo": {"waterfall"}, "comps": {"football"}, "merger": set()}


def H22(cx: Ctx):
    bad = []
    for w, data in delivered_books(cx):
        z = Z(data)
        sheets = z.sheets()
        first, fpath = sheets[0]
        if not re.search(r"cover|dashboard|summary", first, re.I):
            bad.append(f"{w.kind}:{w.label}: first tab is {first!r}, not a Cover/dashboard")
            continue
        parts = chart_parts_for(z, fpath)
        if len(parts) < 3:
            bad.append(f"{w.kind}:{w.label}: {len(parts)} native charts on {first} (need >=3)")
            continue
        wf, _ = openpyxl_pair(data)
        kinds = set()
        for p in parts:
            ks, vals, nser, nval = chart_info(z, p)
            if nser == 0 or nval != nser:
                bad.append(f"{w.kind}:{w.label}: {p} has series without c:val")
            for v in vals:
                nonf = refs_all_formula(wf, v)
                if nonf:
                    bad.append(f"{w.kind}:{w.label}: {p} val {v} not formula-bound ({nonf[0]})")
            for tag, bdir, grp in ks:
                if tag == "barChart" and grp == "stacked" and bdir == "col":
                    kinds.add("waterfall")
                if tag == "barChart" and bdir == "bar":
                    kinds.add("football")
                if tag == "lineChart" or (tag == "barChart" and grp in ("clustered", "standard")):
                    kinds.add("trend")
        miss = CHART_NEEDS.get(w.kind, set()) - kinds
        if miss:
            bad.append(f"{w.kind}:{w.label}: missing chart kinds {sorted(miss)} (have {sorted(kinds)})")
    return (not bad, f"{len(delivered_books(cx))} delivered workbooks: Cover first, >=3 formula-bound charts, required bridge/football/trend present" if not bad else "; ".join(bad[:5]))


def H23(cx: Ctx):
    bad = []
    need_names = ["Input", "Calculation", "Link", "Header", "Total"]
    for w, data in delivered_books(cx):
        z = Z(data)
        st = ET.fromstring(z.read("xl/styles.xml"))
        names = {i: c.get("name") for i, c in enumerate(st.find("m:cellStyles", NS))}
        xfid_to_name = {int(c.get("xfId")): c.get("name") for c in st.find("m:cellStyles", NS)}
        xfs = st.find("m:cellXfs", NS)
        used_xf = {}
        for _, p in z.sheets():
            for c in ET.fromstring(z.read(p)).iter(f"{{{NS['m']}}}c"):
                s = c.get("s")
                if s is not None:
                    xid = int(xfs[int(s)].get("xfId", "0"))
                    used_xf[xfid_to_name.get(xid, "?")] = used_xf.get(xfid_to_name.get(xid, "?"), 0) + 1
        present = set(xfid_to_name.values())
        miss = [n for n in need_names if n not in present]
        unused = [n for n in need_names if n in present and not used_xf.get(n)]
        if miss or unused:
            bad.append(f"{w.kind}:{w.label}: styles missing {miss}, unused {unused}")
    return (not bad, f"named styles {need_names} present and used on {len(delivered_books(cx))} workbooks" if not bad else "; ".join(bad[:5]))


def H24(cx: Ctx):
    bad = []
    for w, data in delivered_books(cx):
        z = Z(data)
        wbx = z.text("xl/workbook.xml")
        sheets = z.sheets()
        titles = {int(i): t for i, t in re.findall(r'<definedName name="_xlnm.Print_Titles" localSheetId="(\d+)">([^<]*)', wbx)}
        for idx, (name, p) in enumerate(sheets):
            x = z.text(p)
            miss = []
            if 'showGridLines="0"' not in x:
                miss.append("gridlines on")
            calc = idx != 0 and name.lower() != "checks"
            if calc and 'state="frozen"' not in x:
                miss.append("no frozen panes")
            ps = re.search(r"<pageSetup [^>]*>", x)
            if not ps or 'orientation="landscape"' not in ps.group(0) or 'fitToWidth="1"' not in ps.group(0):
                miss.append("page setup not landscape/fit-1-wide")
            if "fitToPage" not in x:
                miss.append("fitToPage off")
            if idx not in titles:
                miss.append("no print titles")
            ft = re.search(r"<oddFooter>([^<]*)", x)
            fts = ft.group(1) if ft else ""
            if "Page &amp;P of &amp;N" not in fts or "ource" not in fts:
                miss.append(f"footer lacks source / 'Page &P of &N' ({fts[:40]!r})")
            if miss:
                bad.append(f"{w.kind}:{w.label}:{name}: {', '.join(miss)}")
    return (not bad, f"all sheets of {len(delivered_books(cx))} workbooks: gridlines off, frozen panes, landscape fit-1-wide, print titles, source + page footer" if not bad else f"{len(bad)} sheet problems; " + "; ".join(bad[:5]))


STATEMENT_SHEETS = {"m3": ["IS", "BS", "CF"], "lbo": ["Operations", "Debt"], "merger": ["Pro forma"], "comps": []}


def H25(cx: Ctx):
    bad = []
    for w, data in delivered_books(cx):
        z = Z(data)
        wf, _ = openpyxl_pair(data)
        for sh in STATEMENT_SHEETS.get(w.kind, []):
            x = z.text(z.sheet_path(sh))
            cols = {}
            for m in re.finditer(r"<col [^>]*>", x):
                a = m.group(0)
                lv = re.search(r'outlineLevel="(\d+)"', a)
                if lv and int(lv.group(1)) >= 1:
                    lo, hi = int(re.search(r'min="(\d+)"', a).group(1)), int(re.search(r'max="(\d+)"', a).group(1))
                    for c in range(lo, hi + 1):
                        cols[c] = int(lv.group(1))
            ws = wf[sh]
            hist, proj = [], []
            for r in (5, 6):
                for c in range(3, ws.max_column + 1):
                    v = ws.cell(r, c).value
                    if isinstance(v, str) and re.fullmatch(r"FY\d{4}A", v.strip()):
                        hist.append(c)
                    if isinstance(v, str) and re.fullmatch(r"FY\d{4}E|Year \d+", v.strip()):
                        proj.append(c)
            if not cols:
                bad.append(f"{w.kind}:{w.label}:{sh}: no outlined columns")
            elif not proj or not any(c in cols for c in proj) or (len(set(hist)) >= 2 and not any(c in cols for c in hist)):
                bad.append(f"{w.kind}:{w.label}:{sh}: outline does not cover historical ({len(set(hist))}) and projection ({len(set(proj))}) columns")
    return (not bad, f"historical and projection columns grouped on statement sheets of {len(delivered_books(cx))} workbooks" if not bad else "; ".join(bad[:5]))


def H26(cx: Ctx):
    from om import house
    fonts_ok = set(house.FONTS.values()) if hasattr(house, "FONTS") else {"Arial"}
    bad = []
    for w, data in delivered_books(cx):
        z = Z(data)
        wf, wv = openpyxl_pair(data)
        for idx, (name, p) in enumerate(z.sheets()):
            x = z.text(p)
            for m in re.finditer(r'<mergeCell ref="([A-Z]+\d+):([A-Z]+\d+)"', x):
                if idx != 0:
                    bad.append(f"{w.kind}:{w.label}:{name}: merged range {m.group(1)}:{m.group(2)} in a calculation sheet")
                else:
                    (r1, c1), (r2, c2) = split_ref(m.group(1)), split_ref(m.group(2))
                    if any(isinstance(wf[name].cell(r, c).value, str) and str(wf[name].cell(r, c).value).startswith("=") for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)):
                        bad.append(f"{w.kind}:{w.label}:{name}: merged range over formulas")
        gen = []
        fonts = set()
        for ws in wf.worksheets:
            wsv = wv[ws.title]
            for row in ws.iter_rows():
                for c in row:
                    if c.value is None:
                        continue
                    if c.font and c.font.name:
                        fonts.add(c.font.name)
                    isnum = num(c.value) or (isinstance(c.value, str) and c.value.startswith("=") and num(wsv[c.coordinate].value))
                    if isnum and c.number_format == "General":
                        gen.append(f"{ws.title}!{c.coordinate}")
        if gen:
            bad.append(f"{w.kind}:{w.label}: {len(gen)} number cells with General format, e.g. {gen[:3]}")
        extra = fonts - fonts_ok
        if extra:
            bad.append(f"{w.kind}:{w.label}: fonts outside the house set {sorted(fonts_ok)}: {sorted(extra)}")
    return (not bad, f"no merged calc cells, no General-format numbers, fonts within {sorted(fonts_ok)} on {len(delivered_books(cx))} workbooks" if not bad else "; ".join(bad[:5]))


# ======================================================================================== I. bench and SpreadsheetBench
def I27(cx: Ctx):
    bn = need("om.bench", "run_s4", "report_s4", "audit_all")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="s4_bench_"))
    live = (not cx.offline) and cx.sec_ok
    res = bn.run_s4(out_dir=tmp, libreoffice=lo_available(), offline=not live)
    text = bn.report_s4(res)
    aud = bn.audit_all()
    t = aud["totals"]
    text += ("\n\n## Planted-error audit (gate cross-run)\n\n| Model | Planted | Caught | Located |\n|---|---|---|---|\n" +
             "\n".join(f"| {m['model']} | {m['planted']} | {m['caught']} | {m['located']} |" for m in aud["models"]) + "\n")
    (OUT / "bench.md").write_text(text)
    bad = []
    models = [m for m in res["models"] if m.get("supported", True)]
    m3 = [m for m in models if str(m.get("label", "")).split()[0] in set(BENCH10 + SUBSTITUTES) or str(m.get("label", "")).startswith("SYN")]
    if len(models) < 10:
        bad.append(f"{len(models)} supported workbooks in the bench (need the 10 companies)")
    for m in models:
        if not num(m.get("score")):
            bad.append(f"{m.get('label')}: no score")
        if str(m.get("label")) not in text:
            bad.append(f"{m.get('label')} missing from bench.md")
    low = text.lower()
    if "three-engine" not in low:
        bad.append("three-engine status column not in the report")
    if t["planted"] < 19 or t["caught"] != t["planted"] or t["located_pct"] < 90:
        bad.append(f"audit: planted {t['planted']} caught {t['caught']} located {t['located_pct']}%")
    shutil.rmtree(tmp, ignore_errors=True)
    return (not bad, f"bench.md written: {len(models)} workbooks scored, engine status present, audit {t['caught']}/{t['planted']} caught, {t['located_pct']}% located" if not bad else "; ".join(bad[:4]))


def sb_fetch() -> Path:
    dest = RAW / "spreadsheetbench"
    marker = dest / f".commit-{SB_COMMIT}"
    if marker.exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/RUCKBReasoning/SpreadsheetBench/{SB_COMMIT}/data/spreadsheetbench_verified_400.tar.gz"
    tgz = dest / "verified_400.tar.gz"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": os.environ["SEC_USER_AGENT"].split()[0] + " gate"}), timeout=180) as r:
        tgz.write_bytes(r.read())
    import tarfile
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            p = (dest / m.name).resolve()
            if not str(p).startswith(str(dest.resolve())):
                raise RuntimeError(f"unsafe path in archive: {m.name}")
        t.extractall(dest, filter="data") if sys.version_info >= (3, 12) else t.extractall(dest)
    marker.write_text(SB_COMMIT)
    return dest


def I28(cx: Ctx):
    try:
        need("om.sbench")           # the product module must exist; the fidelity numbers below are the gate's own
        sb_missing = ""
    except Missing as e:
        sb_missing = f"missing {e}"
    if cx.offline:
        return "SKIP", "network dataset (SpreadsheetBench verified-400 at pinned commit) unavailable in --offline mode"
    rc = need("om.recalc", "om_engine")
    import openpyxl
    from openpyxl.utils.datetime import to_excel
    try:
        root = sb_fetch()
    except Exception as e:   # noqa: BLE001
        return False, f"could not fetch SpreadsheetBench at {SB_COMMIT[:8]}: {type(e).__name__}: {str(e)[:120]}"
    files = sorted(p for p in root.rglob("*.xlsx") if re.search(r"golden|answer|solution", p.name, re.I))
    if not files:
        return False, f"no golden/answer workbooks found under {root}"
    n_wb = n_supported = n_ok_supported = cells_all = cells_ok = cells_sup = cells_sup_ok = 0
    missing: dict = {}
    t0 = time.time()
    for p in files:
        if time.time() - t0 > 900:
            break
        try:
            data = p.read_bytes()
            wf = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
            wv = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
            if sum(ws.max_row * ws.max_column for ws in wf.worksheets) > 400_000:
                continue
            eng = rc.om_engine(data)
        except Exception:   # noqa: BLE001
            continue
        n_wb += 1
        unsup = set(getattr(eng, "unsupported", set()))
        if any(isinstance(c.value, str) and re.search(r"\[\d+\]", c.value) for ws in wf.worksheets for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and c.value.startswith("=")):
            unsup.add("external-workbook references")      # the answer file links to workbooks that are not in the package
        for f in unsup:
            missing[f] = missing.get(f, 0) + 1
        ok_c = tot_c = 0
        for ws in wf.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        exp = wv[ws.title][c.coordinate].value
                        if exp is None:
                            continue
                        tot_c += 1
                        got = eng.values.get((ws.title, c.row, c.column))
                        if isinstance(exp, (datetime.datetime, datetime.date)):
                            exp = to_excel(exp)
                        elif isinstance(exp, datetime.time):
                            exp = (exp.hour * 3600 + exp.minute * 60 + exp.second) / 86400.0
                        if tolerant(got, exp, 1e-6, 1e-6) or (isinstance(exp, str) and str(got).strip() == exp.strip()):
                            ok_c += 1
        cells_all += tot_c
        cells_ok += ok_c
        if not unsup:
            n_supported += 1
            cells_sup += tot_c
            cells_sup_ok += ok_c
            n_ok_supported += int(ok_c == tot_c)
    share_sup = cells_sup_ok / cells_sup if cells_sup else 0.0
    top = sorted(missing.items(), key=lambda kv: -kv[1])[:10]
    DETAILS["I28"] = {"workbooks": n_wb, "supported_workbooks": n_supported, "supported_exact": n_ok_supported, "formula_cells": cells_all,
                      "formula_cells_reproduced": cells_ok, "supported_cells": cells_sup, "supported_cells_reproduced": cells_sup_ok, "top_missing": top,
                      "llm_solving": "not run live (replay only, D-021)"}
    # scorecard row S4.6 (the gate records coverage; scorecard.csv is not committed by the gate)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sbench_fidelity.json").write_text(json.dumps(DETAILS["I28"], indent=2))
    sc = [p for p in ROOT.glob("**/scorecard.csv") if "data" not in p.parts and ".claude" not in p.parts]
    sc_ok = any("S4.6" in p.read_text() for p in sc)
    ok = n_wb >= 100 and share_sup >= 0.95 and not sb_missing and sc_ok
    extra = ("; " + sb_missing if sb_missing else "") + ("" if sc_ok else "; scorecard.csv has no S4.6 rows")
    return (ok, f"{n_wb} golden workbooks ({n_supported} fully supported); {cells_ok}/{cells_all} formula cells reproduced overall; supported-only {share_sup:.1%} (>=95% required); top missing {top[:5]}; LLM solving: not run live" + extra)


# ======================================================================================== J. suite
def J29(cx: Ctx):
    if ARGS.no_suite:
        return "SKIP", "--no-suite given"
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    tail = (p.stderr or p.stdout).strip().splitlines()
    ran = next((l for l in tail if l.startswith("Ran ")), "")
    res = next((l for l in reversed(tail) if l.startswith(("OK", "FAILED"))), tail[-1] if tail else "")
    ok = p.returncode == 0 and res.startswith("OK")
    return (ok, f"{ran}; {res}" if ok else f"{ran}; {res}; " + " | ".join([l for l in tail if l.startswith(("FAIL:", "ERROR:"))][:5]))


# ======================================================================================== main
SECTIONS = [
    ("A", [("A1", A1), ("A2", A2), ("A3", A3), ("A4", A4)], ("m3",)),
    ("B", [("B5", B5), ("B6", B6), ("B7", B7)], ("m3", "lbo", "merger", "comps")),
    ("C", [("C8", C8), ("C9", C9), ("C10", C10)], ("m3", "lbo", "merger", "comps")),
    ("D", [("D11", D11), ("D12", D12), ("D13", D13)], ("lbo", "merger", "comps")),
    ("E", [("E14", E14), ("E15", E15)], ()),
    ("F", [("F16", F16), ("F17", F17), ("F18", F18), ("F19", F19)], ()),
    ("G", [("G20", G20), ("G21", G21)], ("m3", "lbo", "merger", "comps")),
    ("H", [("H22", H22), ("H23", H23), ("H24", H24), ("H25", H25), ("H26", H26)], ("m3", "lbo", "merger", "comps")),
    ("I", [("I27", I27), ("I28", I28)], ("m3",)),
    ("J", [("J29", J29)], ()),
]


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="synthetic fixtures only; no SEC / SpreadsheetBench network")
    ap.add_argument("--only", default=None, help="comma-separated sections, e.g. A,B,G")
    ap.add_argument("--no-suite", action="store_true", help="skip J29 (full unittest run)")
    ARGS = ap.parse_args()
    ARGS.only = set(x.strip().upper() for x in ARGS.only.split(",")) if ARGS.only else None
    mode = "offline" if ARGS.offline else "default"
    print(f"verify_s4: mode={mode} only={sorted(ARGS.only) if ARGS.only else 'all'} libreoffice={'yes' if lo_available() else 'no'}", flush=True)
    cx = Ctx(ARGS.offline)
    cx.comps_nm = None
    if not ARGS.offline:
        cx.probe_sec()
        if not cx.sec_ok:
            print(f"NOTE SEC unreachable ({cx.sec_error}); falling back to synthetic fixtures, SEC-dependent assertions SKIP", flush=True)
    need_kinds = set()
    for sec, items, kinds in SECTIONS:
        if wanted(sec):
            need_kinds |= set(kinds)
    synth_needed = any(wanted(s) for s in "BCDEFGHI")
    t = time.time()
    try:
        if synth_needed or wanted("A"):
            cx.build_universe()
    except Missing as e:
        cx.build_errors.append(f"m3 build: missing {e}")
        cx.syn_m3 = cx.syn_m3_circ0 = None
    except Exception as e:   # noqa: BLE001
        cx.build_errors.append(f"m3 build: {type(e).__name__}: {str(e)[:150]}")
    for kind, fn in (("lbo", cx.build_lbo), ("merger", cx.build_merger), ("comps", cx.build_comps)):
        if kind in need_kinds or any(wanted(s) for s in "EFHI"):
            try:
                fn()
            except Missing as e:
                cx.build_errors.append(f"{kind} build: missing {e}")
            except Exception as e:   # noqa: BLE001
                cx.build_errors.append(f"{kind} build: {type(e).__name__}: {str(e)[:150]}")
    print(f"NOTE built {len(cx.m3)} three-statement, {len(cx.lbo)} LBO, {len(cx.merger)} merger, {len(cx.comps)} comps workbooks in {time.time() - t:.0f}s; "
          f"substitutions: {cx.substitutions or 'none'}; build errors: {cx.build_errors or 'none'}", flush=True)
    if not hasattr(cx, "comps_nm"):
        cx.comps_nm = None
    sec_skip = (not ARGS.offline) and not cx.sec_ok
    for sec, items, kinds in SECTIONS:
        if not wanted(sec):
            continue
        for id_, fn in items:
            if sec_skip and id_ in ("F19", "I28"):
                emit(id_, "SKIP", f"SEC unreachable: {cx.sec_error}")
                continue
            if cx.syn_m3 is None and id_ not in ("J29",):
                emit(id_, "FAIL", f"missing prerequisite: three-statement fixture failed to build ({cx.build_errors[:1]})")
                continue
            run(id_, lambda fn=fn: fn(cx))
    # summary
    n = {s: sum(1 for r in RESULTS if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    print(f"SUMMARY pass={n['PASS']} fail={n['FAIL']} skip={n['SKIP']} total={len(RESULTS)} in {time.time() - T0:.0f}s", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gate.json").write_text(json.dumps({
        "gate": "verify_s4", "mode": mode, "date": date.today().isoformat(), "seconds": round(time.time() - T0, 1), "summary": n,
        "substitutions": cx.substitutions, "build_errors": cx.build_errors, "sec_reachable": cx.sec_ok,
        "results": RESULTS, "details": DETAILS}, indent=2, default=str))
    if hasattr(cx, "deliver_root"):
        shutil.rmtree(cx.deliver_root, ignore_errors=True)
    skips = [r for r in RESULTS if r["status"] == "SKIP" and not (r["id"] == "J29" and ARGS.no_suite)]
    bad = n["FAIL"] > 0 or (bool(skips) and not ARGS.offline)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
