"""Stable model API for the product app (S4.8): pure functions over workbook bytes plus small JSON-friendly dicts.

Everything a model view needs: build a model, list and edit its inputs, ask it questions, audit it tab by tab, explain a
cell down to the filing, export it behind the delivery gate, and roll it forward to the newest filing.

State is an optional on-disk store keyed by ``model_id`` (``ACRETIA_MODELS_DIR``, default ``storage/models/``). Versions are
immutable and written once; each records its parent. No global state, no model call, no network unless the default ``fetch``
is used.  Contract and examples: ``docs/interfaces.md`` ("Models (S4)").
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import re
import time
import warnings as _warnings
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypedDict

from . import comps as _comps
from . import delivery
from . import formula as fx
from . import lbo as _lbo
from . import manifest as mf
from . import market as _market
from . import merger as _merger
from . import model3 as _model3
from . import modelcheck, recalc, rollforward, validate_xlsx, wbedit, wbgraph, xlsx
from . import statements as stm

V = 1
KINDS = ("three_statement", "dcf", "lbo", "merger", "comps")
EXPORT_FORMATS = ("xlsx", "xlsx_values", "manifest_json")
LOGO_ANCHOR = "B2"                                   # where Sheet.image places the logo on the first sheet
_NO_INPUT_SHEETS = {"Filings", "Checks"}
_ACCN = re.compile(r"\d{10}-\d{2}-\d{6}")
_MODEL_ID = re.compile(r"^m_[0-9a-f]{20}$")
BLUE = "0000FF"


# --------------------------------------------------------------------------- errors
class ModelApiError(Exception):
    """Base of every typed error. ``code`` is a stable string; ``detail`` is JSON-friendly or None."""
    code = "error"

    def __init__(self, message: str, *, detail: Any = None):
        super().__init__(message)
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "detail": self.detail}


class UnsupportedCompany(ModelApiError):
    code = "unsupported_company"


class NoMarketPrice(ModelApiError):
    code = "no_market_price"


class NotAnInput(ModelApiError):
    code = "not_an_input"


class NotFound(ModelApiError):
    code = "not_found"


class InvalidRequest(ModelApiError):
    code = "invalid_request"


class Blocked(ModelApiError, delivery.DeliveryBlocked):
    """The delivery gate refused: ``.report`` is the om.delivery.gate report, ``.detail`` the same dict."""
    code = "blocked"

    def __init__(self, report: dict):
        delivery.DeliveryBlocked.__init__(self, report)
        self.detail = report


class ModelResult(TypedDict, total=False):
    v: int
    model_id: str
    version: int
    parent: dict | None
    kind: str
    tickers: list
    created_at: str
    bytes_sha256: str
    bytes: int
    outputs: list
    checks: dict
    grade: dict
    validate: dict
    engines: dict
    timings: dict
    warnings: list
    markets: dict
    assumptions: dict
    edit: dict
    update: dict


# --------------------------------------------------------------------------- small helpers
def _clean(x):
    """JSON-safe copy: NaN/inf -> None, tuples -> lists, dates -> ISO strings, keys -> str."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if hasattr(x, "isoformat"):
        return x.isoformat()
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    if hasattr(x, "code"):                       # om.formula.Err
        return str(x.code)
    return str(x)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _close(a, b, tol: float = 1e-6) -> bool:
    if _num(a) and _num(b):
        return abs(a - b) <= tol * max(1.0, abs(a), abs(b))
    return a == b or (a in (None, "") and b in (None, ""))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Clock:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.steps: dict = {}

    def step(self, name: str, fn):
        t = time.perf_counter()
        try:
            return fn()
        finally:
            self.steps[name] = round(self.steps.get(name, 0.0) + time.perf_counter() - t, 4)

    def done(self) -> dict:
        return {**self.steps, "total": round(time.perf_counter() - self.t0, 4)}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------- store
def models_dir() -> Path:
    return Path(os.environ.get("ACRETIA_MODELS_DIR") or "storage/models")


def _write_once(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(blob)
    try:
        os.link(tmp, path)                                   # fails if it exists: stored files are never overwritten
    finally:
        tmp.unlink(missing_ok=True)


def _jbytes(obj) -> bytes:
    return json.dumps(_clean(obj), sort_keys=True, indent=1, allow_nan=False).encode("utf-8")


def _check_id(model_id: str) -> Path:
    if not isinstance(model_id, str) or not _MODEL_ID.match(model_id):
        raise NotFound(f"no model {model_id!r}")
    return models_dir() / model_id


def _versions(d: Path) -> list[int]:
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        m = re.match(r"^v(\d+)$", p.name)
        if m and (p / "record.json").exists():
            out.append(int(m.group(1)))
    return sorted(out)


def _load(model_id: str, version: int | None = None) -> tuple[dict, bytes, dict]:
    d = _check_id(model_id)
    vs = _versions(d)
    if not vs:
        raise NotFound(f"no model {model_id!r}")
    v = vs[-1] if version is None else version
    if v not in vs:
        raise NotFound(f"model {model_id} has no version {version!r} (versions: {vs})")
    p = d / f"v{v}"
    return (json.loads((p / "record.json").read_bytes()), (p / "model.xlsx").read_bytes(),
            json.loads((p / "private.json").read_bytes()))


def _commit(model_id: str | None, rec: dict, data: bytes, private: dict, parent: tuple[str, int] | None) -> dict:
    """Write a new immutable version. ``parent`` is (model_id, version) or None for a first version.
    A first version's id is the sha256 of its build key (kind, tickers, assumptions, markets, filings sha256s)."""
    sha = _sha(data)
    mid = model_id or _key_id(private.get("build") or {"bytes": sha})
    d = models_dir() / mid
    d.mkdir(parents=True, exist_ok=True)
    n = (_versions(d) or [0])[-1]
    while True:
        n += 1
        try:
            (d / f"v{n}").mkdir()
            break
        except FileExistsError:
            continue
    if parent is not None:
        prec = json.loads((d / f"v{parent[1]}" / "record.json").read_bytes())
        rec["parent"] = {"version": parent[1], "bytes_sha256": prec["bytes_sha256"]}
    else:
        rec["parent"] = None
    rec.update({"v": V, "model_id": mid, "version": n, "bytes_sha256": sha, "bytes": len(data), "created_at": _now()})
    p = d / f"v{n}"
    _write_once(p / "model.xlsx", data)
    _write_once(p / "private.json", _jbytes(private))
    _write_once(p / "record.json", _jbytes(rec))              # last: a version without record.json is not visible yet
    return json.loads((p / "record.json").read_bytes())


def _key_id(build: dict) -> str:
    return "m_" + _sha(json.dumps(_clean(build), sort_keys=True, separators=(",", ":")).encode("utf-8"))[:20]


def _put_source(cf: dict) -> str:
    raw = json.dumps(cf, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sha = _sha(raw)
    p = models_dir() / "_sources" / f"{sha}.json.gz"
    if not p.exists():
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
            g.write(raw)
        try:
            _write_once(p, buf.getvalue())
        except FileExistsError:
            pass
    return sha


def _get_source(sha: str) -> dict:
    return json.loads(gzip.decompress((models_dir() / "_sources" / f"{sha}.json.gz").read_bytes()))


# --------------------------------------------------------------------------- fetch
def default_fetch(ticker: str) -> dict:
    """SEC companyfacts through om.sec (cached under data/raw/sec); needs SEC_USER_AGENT for live requests."""
    from .sec import SecClient
    sec = SecClient(os.environ.get("SEC_USER_AGENT", ""), Path(os.environ.get("ACRETIA_DATA_DIR") or "data") / "raw" / "sec")
    t = ticker.upper()
    cik = int(t) if t.isdigit() else next((int(r["cik"]) for r in sec.tickers() if str(r.get("ticker", "")).upper() == t), None)
    if cik is None:
        raise UnsupportedCompany(f"unknown ticker {ticker}")
    return sec.companyfacts(cik)


def _fetch_all(tickers: list[str], fetch, clock: _Clock) -> dict:
    fetch = fetch or default_fetch
    out = {}
    for t in tickers:
        try:
            out[t] = clock.step("fetch", lambda t=t: fetch(t))
        except ModelApiError:
            raise
        except (FileNotFoundError, KeyError, LookupError) as e:
            raise UnsupportedCompany(f"no filings found for {t} ({type(e).__name__}: {e})") from e
        if not isinstance(out[t], dict) or "facts" not in out[t]:
            raise UnsupportedCompany(f"{t}: the filings payload has no 'facts'")
    return out


# --------------------------------------------------------------------------- building
def _wrap_build(fn):
    try:
        return fn()
    except (_model3.UnsupportedCompany, _lbo.UnsupportedCompany) as e:
        raise UnsupportedCompany(str(e)) from e
    except ValueError as e:
        msg = str(e)
        if re.search(r"share price|market price|market must carry", msg):
            raise NoMarketPrice(msg) from e
        if re.search(r"diluted shares|doesn't tag|no revenue|no fiscal years|need the target|at least two", msg):
            raise UnsupportedCompany(msg) from e
        raise InvalidRequest(msg) from e
    except (KeyError, TypeError) as e:
        raise InvalidRequest(f"{type(e).__name__}: {e}") from e


def _build_workbook(kind: str, tickers: list[str], cfs: dict, markets: dict, assumptions: dict | None):
    a = dict(assumptions or {})
    t0 = tickers[0]
    if kind in ("three_statement", "dcf"):
        s = stm.build(cfs[t0], t0)
        return _model3.build_workbook(s, assumptions=a or None)
    if kind == "lbo":
        return _lbo.build_workbook(stm.build(cfs[t0], t0), market=markets[t0], assumptions=a or None)
    if kind == "merger":
        t1 = tickers[1]
        return _merger.build_workbook(stm.build(cfs[t0], t0), stm.build(cfs[t1], t1), acq_market=markets[t0], tgt_market=markets[t1],
                                      assumptions=a or None)
    as_of, cm = a.pop("as_of", None), a.pop("calendar_month", 12)
    return _comps.build_workbook((t0, cfs[t0]), [(t, cfs[t]) for t in tickers[1:]], markets=markets, as_of=as_of, calendar_month=cm)


def _dcf_outputs(book, meta: dict) -> list[dict]:
    want = (("m3.dcf.value_per_share", "implied value per share", "USD/share"), ("m3.dcf.enterprise_value", "enterprise value", "USD m"),
            ("m3.dcf.equity_value", "equity value", "USD m"), ("m3.dcf.tv_pct_ev", "terminal value as % of ev", "%"))
    found = {}
    for (r, c), cell in sorted(book.sheets.get("DCF", {}).items()):
        if c == 1 and isinstance(cell.value, str):
            low = cell.value.strip().lower()
            for oid, label, units in want:
                if low == label and oid not in found:
                    found[oid] = {"id": oid, "sheet": "DCF", "ref": f"C{r}", "units": units, "historical": False, "label": cell.value.strip()}
    head = [found[o[0]] for o in want if o[0] in found]
    return head + [o for o in mf.default_outputs(book, meta) if o["id"] not in found]


def _resolve_markets(kind: str, tickers: list[str], cfs: dict, quotes) -> dict:
    need = {"lbo": tickers[:1], "merger": tickers[:2], "comps": tickers[:1]}.get(kind, [])
    optional = tickers[1:] if kind == "comps" else []
    out = {}
    for t in need + optional:
        m = _market.resolve(t, cfs[t], quotes)
        if m is None and t in need:
            raise NoMarketPrice(f"no market price for {t}: pass quotes={{'{t}': om.prices.Quote(...)}}; the filings carry no public float",
                                detail={"ticker": t})
        if m is not None:
            out[t] = m
    return out


def _checks(book, meta: dict) -> dict:
    grid = book.sheets.get("Checks")
    if grid is None:
        return {"master": None, "ok": False, "items": [], "error": "no Checks sheet"}
    items, master = [], None
    mrow = ((meta.get("rows") or {}).get("Checks") or {}).get("master")
    for r in sorted({r for r, _ in grid}):
        vals = [(c, x.value) for (rr, c), x in sorted(grid.items()) if rr == r and c >= 3 and x.value in ("OK", "ERROR")]
        if not vals:
            continue
        lab = wbgraph.row_label(book, "Checks", r)
        if r == mrow or (mrow is None and lab and "master" in lab.lower()):
            master = vals[0][1]
        elif lab:
            bad = [c for c, v in vals if v != "OK"]
            items.append({"label": lab, "cell": wbgraph.key_of("Checks", r, vals[0][0]), "value": "ERROR" if bad else "OK",
                          "ok": not bad, "cells": len(vals)})
    return {"master": master, "ok": master == "OK" and all(i["ok"] for i in items), "items": items}


def _outputs(data: bytes, meta: dict) -> list[dict]:
    man, values = mf.export_with_values(data, meta)
    book = xlsx.read(data)
    labels = {o["id"]: o.get("label") for o in (meta.get("outputs") or [])}
    out = []
    for mo in man.to_dict()["outputs"]:
        lab = labels.get(mo["id"])
        if not lab:
            try:
                lab = wbgraph.label_of(book, f"{xlsx.quote_sheet(mo['sheet'])}!{mo['ref']}") or None
            except Exception:                                     # noqa: BLE001
                lab = None
        out.append({**mo, "label": lab, "value": values.get(mo["id"])})
    return _clean(out)


def _analyze(data: bytes, meta: dict, clock: _Clock) -> dict:
    g = clock.step("grade", lambda: modelcheck.grade(data))
    v = clock.step("validate", lambda: validate_xlsx.validate(data))
    e = clock.step("recalc", lambda: recalc.compare(data))
    outs = clock.step("manifest", lambda: _outputs(data, meta))
    book = xlsx.read(data)
    failed = [x.get("id") or x.get("title") for x in g.get("graders", []) if x.get("critical") and x.get("passed") is False]
    stats = v.get("stats", {})
    return {
        "outputs": outs,
        "checks": _checks(book, meta),
        "grade": {"score": g.get("score"), "production_ready": bool(g.get("production_ready")), "critical_failed": failed,
                  "formulas": (g.get("stats") or {}).get("formulas"), "typed_numbers": (g.get("stats") or {}).get("typed_numbers")},
        "validate": {"passed": bool(v.get("passed")), "critical": stats.get("critical", 0), "warnings": stats.get("warnings", 0),
                     "formulas": stats.get("formulas"), "circular_cells": stats.get("circular_cells"),
                     "first_findings": v.get("findings", [])[:5]},
        "engines": {"agree": bool(e.get("agree")), "compared_cells": e.get("compared_cells", 0), "divergences": len(e.get("divergences") or []),
                    "engines": {n: {k: i.get(k) for k in ("available", "cells", "seconds", "reason")} for n, i in (e.get("engines") or {}).items()}},
    }


def _public(rec: dict) -> ModelResult:
    return rec  # type: ignore[return-value]


def build_model(kind: str, tickers: list[str], *, assumptions: dict | None = None, quotes=None, fetch: Callable | None = None) -> ModelResult:
    """Build and store version 1 of a model. ``fetch(ticker) -> companyfacts``; ``quotes`` as for om.market.resolve."""
    if kind not in KINDS:
        raise InvalidRequest(f"unknown kind {kind!r}; expected one of {KINDS}")
    tickers = [str(t).upper() for t in (tickers or [])]
    need = {"merger": 2, "comps": 2}.get(kind, 1)
    if len(tickers) < need or len(set(tickers)) != len(tickers):
        raise InvalidRequest(f"{kind} needs {'at least ' if kind == 'comps' else ''}{need} distinct ticker(s), got {tickers}")
    if kind != "comps":
        tickers = tickers[: (2 if kind == "merger" else 1)]
    if assumptions is not None and not isinstance(assumptions, dict):
        raise InvalidRequest("assumptions must be a dict")
    clock = _Clock()
    cfs = _fetch_all(tickers, fetch, clock)
    markets = _resolve_markets(kind, tickers, cfs, quotes)
    build = {"kind": kind, "tickers": tickers, "assumptions": _clean(assumptions or {}), "markets": markets,
             "sources": {t: _put_source(cf) for t, cf in cfs.items()}}
    d = models_dir() / _key_id(build)
    if _versions(d):                                          # same inputs already built: idempotent, nothing recomputed
        return _public(_load(d.name, _versions(d)[0])[0])
    wb, meta = clock.step("build", lambda: _wrap_build(lambda: _build_workbook(kind, tickers, cfs, markets, assumptions)))
    data = wb.to_bytes()
    if kind == "dcf":
        meta = dict(meta)
        meta["outputs"] = _dcf_outputs(xlsx.read(data), meta)
    meta = _clean(meta)
    a = _analyze(data, meta, clock)
    rec = {"kind": kind, "tickers": tickers, **a, "warnings": list(meta.get("warnings") or []), "markets": markets,
           "assumptions": _clean(assumptions or {})}
    rec["timings"] = clock.done()
    return _public(_commit(None, rec, data, {"meta": meta, "build": build, "overrides": {}}, None))


def get_model(model_id: str, version: int | None = None) -> ModelResult:
    return _public(_load(model_id, version)[0])


def get_bytes(model_id: str, version: int | None = None) -> bytes:
    return _load(model_id, version)[1]


def list_versions(model_id: str) -> list[dict]:
    """[{"version", "parent_version", "bytes_sha256", "created_at"}] oldest first."""
    d = _check_id(model_id)
    vs = _versions(d)
    if not vs:
        raise NotFound(f"no model {model_id!r}")
    out = []
    for v in vs:
        r = json.loads((d / f"v{v}" / "record.json").read_bytes())
        out.append({"version": v, "parent_version": (r.get("parent") or {}).get("version"), "bytes_sha256": r["bytes_sha256"],
                    "created_at": r["created_at"]})
    return out


# --------------------------------------------------------------------------- inputs
def _reported(book, sheet: str, rc: tuple) -> bool:
    link = book.links.get(sheet, {}).get(rc) or ""
    return link.startswith("http") or bool(_ACCN.search(book.comments.get(sheet, {}).get(rc) or ""))


def _input_cells(book) -> dict:
    """{key: (sheet, r, c)} for blue-font numeric constants that are not reported (filing) figures."""
    out = {}
    for sheet in book.order:
        if sheet in _NO_INPUT_SHEETS or "'" in sheet:
            continue
        for (r, c), cell in sorted(book.sheets[sheet].items()):
            if (cell.formula is None and cell.color == BLUE and _num(cell.value) and not _reported(book, sheet, (r, c))):
                out[wbgraph.key_of(sheet, r, c)] = (sheet, r, c)
    return out


def _formats(data: bytes) -> tuple[dict, dict]:
    try:
        raw = validate_xlsx._raw(data)
        return raw, raw.get("_fmt", {})
    except Exception:                                             # noqa: BLE001
        return {}, {}


def list_inputs(model_id: str, version: int | None = None) -> list[dict]:
    """Blue input cells: [{"cell","sheet","label","period","value","fmt","source"}] in sheet and row order."""
    _, data, _ = _load(model_id, version)
    book = xlsx.read(data)
    raw, fmts = _formats(data)
    out = []
    for key, (sheet, r, c) in _input_cells(book).items():
        cell = book.sheets[sheet][(r, c)]
        s = (raw.get(sheet, {}).get("cells", {}).get((r, c)) or {}).get("s")
        src = book.comments.get(sheet, {}).get((r, c)) or book.links.get(sheet, {}).get((r, c))
        out.append({"cell": key, "sheet": sheet, "label": wbgraph.row_label(book, sheet, r) or "",
                    "period": wbgraph.period_header(book, sheet, r, c) if c > 2 else None,
                    "value": cell.value, "fmt": fmts.get(s) if s is not None else None, "source": src})
    return out


def set_inputs(model_id: str, changes: dict, *, version: int | None = None) -> ModelResult:
    """Edit blue input cells with recompute (om.wbedit), re-grade, store a new version whose parent is the one edited."""
    if not isinstance(changes, dict) or not changes:
        raise InvalidRequest("changes must be a non-empty {cell: number} dict")
    rec, data, private = _load(model_id, version)
    book = xlsx.read(data)
    inputs = _input_cells(book)
    norm, bad = {}, []
    for k, v in changes.items():
        try:
            key = wbgraph.norm_key(str(k).replace("$", ""))
        except ValueError:
            raise InvalidRequest(f"bad cell reference {k!r}; use 'Sheet!C5'") from None
        if not _num(v):
            raise InvalidRequest(f"{k}: a number is required, got {v!r}")
        if key not in inputs:
            sheet, r, c, _, _ = wbgraph.split_key(key)
            cell = book.sheets.get(sheet, {}).get((r, c))
            why = ("no such sheet" if sheet not in book.sheets else "empty cell" if cell is None else
                   "a formula" if cell.formula else "a reported (filing) figure" if _reported(book, sheet, (r, c)) else
                   "not a blue input cell")
            bad.append({"cell": key, "reason": why})
        norm[key] = float(v)
    if bad:
        raise NotAnInput("only blue input cells may be edited; refused: " + "; ".join(f"{b['cell']} ({b['reason']})" for b in bad), detail=bad)
    clock = _Clock()
    old = {k: inputs[k] for k in norm}
    if all(_close(book.sheets[s][(r, c)].value, norm[k], 1e-12) for k, (s, r, c) in old.items()):
        return _public(rec)
    new, report = clock.step("edit", lambda: wbedit.edit(data, norm, recalc=True))
    meta = private["meta"]
    a = _analyze(new, meta, clock)
    before = {o["id"]: o["value"] for o in rec["outputs"]}
    changed = [{"id": o["id"], "label": o["label"], "before": before.get(o["id"]), "after": o["value"]}
               for o in a["outputs"] if not _close(before.get(o["id"]), o["value"], 1e-9)]
    bk = xlsx.read(new)
    cells = [{"cell": k, "label": wbgraph.row_label(book, s, r) or "", "period": wbgraph.period_header(book, s, r, c) if c > 2 else None,
              "before": book.sheets[s][(r, c)].value, "after": norm[k]} for k, (s, r, c) in old.items()]
    rec2 = {**{k: rec.get(k) for k in ("kind", "tickers", "markets", "assumptions")}, **a, "warnings": list(rec.get("warnings") or []),
            "edit": {"changes": cells, "changed_outputs": changed, "dependents_updated": len(report["dependents_updated"]),
                     "parts_touched": report["parts_touched"]}}
    rec2["timings"] = clock.done()
    del bk
    private2 = {**private, "overrides": {**private.get("overrides", {}), **norm}}
    return _public(_commit(model_id, rec2, new, private2, (model_id, rec["version"])))


# --------------------------------------------------------------------------- ask / explain / audit
def ask(model_id: str, question: str, *, version: int | None = None) -> dict:
    """Multi-tab Q&A. ``reconciled``: every cited value equals the workbook's cached value and, for formula cells, an
    independent om.formula recalculation (parity 43)."""
    if not isinstance(question, str) or not question.strip():
        raise InvalidRequest("question must be a non-empty string")
    _, data, _ = _load(model_id, version)
    book = xlsx.read(data)
    res = wbgraph.ask(data, question, _book=book)
    cells, values = list(res.get("cells") or []), list(res.get("values") or [])
    ok = bool(cells) and len(cells) == len(values) and all(":" not in c for c in cells)
    unreconciled = []
    if ok:
        fresh = recalc.om_values(data)
        for c, v in zip(cells, values):
            sheet, r, cc, _, _ = wbgraph.split_key(c)
            cell = book.sheets.get(sheet, {}).get((r, cc))
            good = cell is not None and _close(cell.value, v)
            if good and cell.formula:
                f = fresh.get((sheet, r, cc))
                good = _close(cell.value, f.code if hasattr(f, "code") else f)
            if not good:
                unreconciled.append(c)
    else:
        unreconciled = cells
    return {"answer": res.get("answer"), "cells": cells, "values": _clean(values), "reconciled": ok and not unreconciled,
            "unreconciled": unreconciled, "method": res.get("method")}


def explain(model_id: str, cell: str, *, version: int | None = None) -> dict:
    """Formula, value, labelled precedents (depth 2) and each hard-coded leaf with its source (parity 20)."""
    _, data, _ = _load(model_id, version)
    try:
        out = wbgraph.explain(data, cell)
    except KeyError as e:
        raise NotFound(str(e).strip("'\"")) from e
    except ValueError as e:
        raise InvalidRequest(str(e)) from e
    out["unsourced_leaves"] = [i["cell"] for i in out.get("inputs", []) if not i.get("source") and not i.get("link")]
    return _clean(out)


def _target_sheet(t: str) -> str | None:
    try:
        return wbgraph.split_key(t)[0]
    except ValueError:
        return None


def audit(model_id: str, version: int | None = None) -> dict:
    """Per-tab audit (parity 44): formulas, inputs, links in/out by tab, error cells, hard-codes, unsourced inputs, checks."""
    _, data, _ = _load(model_id, version)
    book = xlsx.read(data)
    g = wbgraph.graph(data)
    v = validate_xlsx.validate(data)
    out, link_out, link_in = {}, {s: Counter() for s in book.order}, {s: Counter() for s in book.order}
    for key, targets in g.edges.items():
        s = _target_sheet(key)
        for t in targets:
            ts = _target_sheet(t)
            if s and ts and s != ts:
                link_out.setdefault(s, Counter())[ts] += 1
                link_in.setdefault(ts, Counter())[s] += 1
    hard: dict = {}
    for f in v.get("findings", []):
        if str(f.get("id", "")).startswith("hardcode"):
            hard.setdefault(f.get("sheet"), []).append(f"{xlsx.quote_sheet(f['sheet'])}!{f['cell']}")
    tabs = []
    for sheet in book.order:
        grid = book.sheets[sheet]
        formulas = sum(1 for c in grid.values() if c.formula)
        blue = [(rc, c) for rc, c in sorted(grid.items()) if c.formula is None and c.color == BLUE and _num(c.value)]
        sourced_any = any(book.comments.get(sheet, {}).get(rc) or book.links.get(sheet, {}).get(rc) for rc, _ in blue)
        unsourced = [wbgraph.key_of(sheet, *rc) for rc, _ in blue
                     if sourced_any and not (book.comments.get(sheet, {}).get(rc) or book.links.get(sheet, {}).get(rc))]
        errors = [wbgraph.key_of(sheet, *rc) for rc, c in sorted(grid.items())
                  if c.is_error or (isinstance(c.value, str) and c.value.startswith("#") and c.value.rstrip("!?/0A").upper() in
                                    ("#DIV", "#REF", "#VALUE", "#NAME", "#N", "#NUM", "#NULL"))]
        marks = Counter(c.value for c in grid.values() if c.value in ("OK", "ERROR"))
        tabs.append({"sheet": sheet, "formulas": formulas, "inputs": len(blue),
                     "links_in": [{"sheet": s, "count": n} for s, n in sorted(link_in.get(sheet, {}).items())],
                     "links_out": [{"sheet": s, "count": n} for s, n in sorted(link_out.get(sheet, {}).items())],
                     "errors": errors, "hardcodes": sorted(hard.get(sheet, [])), "unsourced": unsourced,
                     "checks": {"ok": marks.get("OK", 0), "error": marks.get("ERROR", 0)}})
    return _clean({"tabs": tabs, "findings": v.get("findings", [])[:200]})


# --------------------------------------------------------------------------- export
def _values_only_fallback(data: bytes) -> bytes:
    """Drop every <f> element, keeping cached values; string results become inline strings so the file stays valid."""
    zin = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    f_re = re.compile(r"<f\b[^>]*?(?:/>|>.*?</f>)", re.S)
    c_re = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)

    def fix(m):
        attrs, body = m.group(1), m.group(2)
        if body is None or "<f" not in body:
            return m.group(0)
        body = f_re.sub("", body)
        if re.search(r'\bt="str"', attrs):
            v = re.search(r"<v>(.*?)</v>", body, re.S)
            attrs = re.sub(r'\bt="str"', 't="inlineStr"', attrs)
            body = f'<is><t xml:space="preserve">{v.group(1) if v else ""}</t></is>'
        return f"<c{attrs}>{body}</c>"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            blob = zin.read(info.filename)
            if info.filename == "xl/calcChain.xml":
                continue
            if re.match(r"xl/worksheets/[^/]+\.xml$", info.filename):
                blob = c_re.sub(fix, blob.decode("utf-8")).encode("utf-8")
            elif info.filename == "[Content_Types].xml":
                blob = re.sub(rb'<Override\b[^>]*calcChain[^>]*/>', b"", blob)
            elif info.filename == "xl/_rels/workbook.xml.rels":
                blob = re.sub(rb'<Relationship\b[^>]*calcChain[^>]*/>', b"", blob)
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zout.writestr(zi, blob)
    return out.getvalue()


def _with_logo(private: dict, logo: bytes) -> bytes:
    """Rebuild the version from its stored sources (plus any input edits) and place the logo; needs xlsx.Sheet.image."""
    b = private.get("build")
    if not b:
        raise RuntimeError("this version was not built from stored sources (rolled forward), so the logo cannot be placed")
    cfs = {t: _get_source(sha) for t, sha in b["sources"].items()}
    wb, _ = _build_workbook(b["kind"], b["tickers"], cfs, b["markets"], b["assumptions"])
    for key, val in (private.get("overrides") or {}).items():
        sheet, r, c, _, _ = wbgraph.split_key(key)
        next(s for s in wb.sheets if s.name == sheet).cells[(r, c)].value = val
    fx.calculate_workbook(wb)
    wb.sheets[0].image(logo, LOGO_ANCHOR)
    return wb.to_bytes()


def export_with_report(model_id: str, *, fmt: str = "xlsx", logo_png: bytes | None = None, version: int | None = None) -> tuple[bytes, dict]:
    """``export`` plus {"warnings": [...], "gate": om.delivery.gate report (no manifest body), "sha256"}."""
    if fmt not in EXPORT_FORMATS:
        raise InvalidRequest(f"unknown format {fmt!r}; expected one of {EXPORT_FORMATS}")
    rec, data, private = _load(model_id, version)
    gate = delivery.gate(data, private["meta"])
    if not gate["passed"]:
        raise Blocked({k: v for k, v in gate.items() if k not in ("manifest", "values")})
    notes: list = []
    if logo_png is not None and fmt != "manifest_json":
        if callable(getattr(xlsx.Sheet, "image", None)):
            try:
                data = _with_logo(private, logo_png)
            except Exception as e:                              # noqa: BLE001
                notes.append(f"logo ignored: {type(e).__name__}: {e}")
        else:
            notes.append("logo ignored: this build of om.xlsx has no Sheet.image")
    if fmt == "manifest_json":
        blob = mf.to_json(mf.export(data, private["meta"])).encode("utf-8")
    elif fmt == "xlsx_values":
        vo = getattr(xlsx, "values_only", None)
        blob = vo(data) if callable(vo) else _values_only_fallback(data)
    else:
        blob = data
    for n in notes:
        _warnings.warn(n, stacklevel=2)
    return blob, {"warnings": notes, "gate": {k: v for k, v in gate.items() if k not in ("manifest", "values")}, "sha256": _sha(blob)}


def export(model_id: str, *, fmt: str = "xlsx", logo_png: bytes | None = None, version: int | None = None) -> bytes:
    """Deliver bytes in ``fmt``; raises ``Blocked`` (a DeliveryBlocked) unless om.delivery.gate passes."""
    return export_with_report(model_id, fmt=fmt, logo_png=logo_png, version=version)[0]


# --------------------------------------------------------------------------- earnings update
def update_earnings(model_id: str, *, fetch: Callable | None = None) -> ModelResult:
    """Roll a three-statement model forward to the latest filing (om.rollforward); a new version, timing recorded.
    Already current: the latest version is returned unchanged with ``update.rolled == False``."""
    rec, data, private = _load(model_id)
    if rec["kind"] not in ("three_statement", "dcf"):
        raise InvalidRequest(f"update_earnings supports three_statement and dcf models, not {rec['kind']}")
    clock = _Clock()
    t = rec["tickers"][0]
    cf = _fetch_all([t], fetch, clock)[t]
    s = clock.step("statements", lambda: stm.build(cf, t))
    meta = private["meta"]
    last_old = int(str(meta["years"][-1])[:4]) if meta.get("years") else None
    if last_old is not None and s.years[-1].year <= last_old:
        return _public({**rec, "update": {"rolled": False, "reason": f"already current at FY{last_old}", "timings": clock.done()}})
    new, report = clock.step("roll_forward", lambda: _wrap_build(lambda: rollforward.roll_forward(data, s, old_meta=meta)))
    meta2 = _clean(report["meta"])
    if rec["kind"] == "dcf":
        meta2["outputs"] = _dcf_outputs(xlsx.read(new), meta2)
    a = _analyze(new, meta2, clock)
    before = {o["id"]: o["value"] for o in rec["outputs"]}
    changed = [{"id": o["id"], "label": o["label"], "before": before.get(o["id"]), "after": o["value"]}
               for o in a["outputs"] if o["id"] in before and not _close(before[o["id"]], o["value"], 1e-9)]
    upd = {"rolled": True, "new_actual": report["new_actual"], "previous_last_actual": report["previous_last_actual"],
           "forecast_years": report["forecast_years"], "variance": report["variance"], "changed_outputs": changed,
           "assumptions_carried": len(report.get("assumptions_carried") or []), "assumptions_dropped": len(report.get("assumptions_dropped") or [])}
    rec2 = {"kind": rec["kind"], "tickers": rec["tickers"], **a, "warnings": list(report.get("warnings") or []), "markets": rec.get("markets") or {},
            "assumptions": rec.get("assumptions") or {}, "update": upd}
    rec2["timings"] = clock.done()
    rec2["update"]["timings"] = rec2["timings"]
    private2 = {"meta": meta2, "build": None, "overrides": {}}
    return _public(_commit(model_id, rec2, new, private2, (model_id, rec["version"])))
