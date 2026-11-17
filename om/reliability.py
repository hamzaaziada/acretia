"""Reliability corpus run (D-032 north-star): 100+ companies, US XBRL 10-K filers plus IFRS 20-F filers, through the
whole Excel pipeline, with a per-step wall clock and failures reported by cause.

Per company (`run_one`): fetch -> Statements -> `statements.audit` -> model3 (circ=1 and circ=0) -> `modelcheck.grade`
-> `validate_xlsx.validate` -> `recalc.compare` (circ=0: om + LibreOffice + formulon) -> earnings update (Statements as of
one fiscal year earlier -> model -> `rollforward.roll_forward` -> grade) timed end to end.

Outcome is `pass`, `unsupported` (model3 does not cover the company; not a failure) or `fail` with a cause bucket:
fetch | mapping/missing concept | IFRS concept gap | tie-out | grader:<id> | validate:<id> | engine divergence | exception:<type>.
`audit_flags` keeps every audit warning, so a historical figure that does not tie is flagged, never silent.

    python3 -m om.reliability run [--n 120] [--force] [--workers 4] [--out data/out/s4/reliability]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import model3, modelcheck, recalc, rollforward, validate_xlsx
from . import statements as stm

OUT_DIR = Path("data/out/s4/reliability")
RAW_DIR = Path("data/raw/sec")
SEC_RPS = 4.0                      # SEC fair access allows 10 req/s; we use 4
UA_DEFAULT = "Acretia hamza@meshpool.ai"
TARGET_PASS = 0.97
TARGET_UPDATE_SECONDS = 300.0

# --------------------------------------------------------------------------- universe
# US 10-K filers, a spread across GICS sectors (no banks / insurers).
US_TICKERS = [
    # information technology
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "CSCO", "AMD", "INTC", "QCOM", "TXN", "IBM", "NOW", "INTU",
    "AMAT", "MU", "ADI", "PANW", "SNPS",
    # communication services
    "GOOGL", "META", "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS", "EA",
    # consumer discretionary
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX", "BKNG", "F", "GM", "MAR", "ORLY", "LULU",
    # consumer staples
    "WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ", "CL", "KMB", "GIS", "MO", "KR", "STZ",
    # health care
    "JNJ", "UNH", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "AMGN", "BMY", "GILD", "ISRG", "MDT", "CVS", "VRTX",
    # industrials
    "CAT", "DE", "HON", "UPS", "BA", "LMT", "RTX", "GE", "UNP", "MMM", "FDX", "WM", "ETN", "EMR", "CSX",
    # energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "PSX", "MPC",
    # materials
    "LIN", "SHW", "APD", "FCX", "NEM", "DOW", "NUE",
    # utilities
    "NEE", "DUK", "SO", "D", "AEP",
    # real estate (operating REITs)
    "PLD", "AMT", "EQIX", "SPG",
]
# Foreign private issuers filing IFRS (ifrs-full) XBRL on Form 20-F.
IFRS_TICKERS = [
    "SAP", "ASML", "NVO", "TM", "SHEL", "UL", "BHP", "AZN", "SONY", "TSM", "INFY", "ABEV", "BTI", "DEO", "RIO",
    "NVS", "SNY", "GSK", "BP", "PHG", "ERIC", "NOK", "SE", "STLA", "TTE",
]
# Banks and insurers: model3 does not model them yet. Recorded as out of scope, never as failures.
OUT_OF_SCOPE = {
    "JPM": "bank", "BAC": "bank", "WFC": "bank", "C": "bank", "GS": "broker-dealer", "MS": "broker-dealer",
    "USB": "bank", "PNC": "bank", "SCHW": "broker-dealer", "BLK": "asset manager",
    "BRK-B": "insurer", "MET": "insurer", "PRU": "insurer", "AIG": "insurer", "CB": "insurer", "PGR": "insurer",
    "V": "payments (financial format)", "MA": "payments (financial format)",
    "HSBC": "bank", "LYG": "bank", "MUFG": "bank",
}


def universe(n: int = 120) -> list[str]:
    """Deterministic list of up to `n` tickers: the IFRS filers are spread evenly among the US ones, in proportion, so
    any `n` keeps both populations. `n` larger than the pool returns the whole pool."""
    us, ifrs = list(US_TICKERS), list(IFRS_TICKERS)
    total = len(us) + len(ifrs)
    n = min(max(n, 0), total)
    n_ifrs = min(len(ifrs), max(1, round(n * len(ifrs) / total))) if n else 0
    n_us = n - n_ifrs
    if n_us > len(us):
        n_us, n_ifrs = len(us), min(len(ifrs), n - len(us))
    pick_us, pick_ifrs = us[:n_us], ifrs[:n_ifrs]
    out: list[str] = []
    i = j = 0
    step = max(1, len(pick_us) // max(1, len(pick_ifrs))) if pick_ifrs else len(pick_us) + 1
    while i < len(pick_us) or j < len(pick_ifrs):
        for _ in range(step):
            if i < len(pick_us):
                out.append(pick_us[i])
                i += 1
        if j < len(pick_ifrs):
            out.append(pick_ifrs[j])
            j += 1
    return out


# --------------------------------------------------------------------------- data access
_CLIENT = None
_CLIENT_LOCK = threading.Lock()
_TICKER_MAP: dict | None = None


def _client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from .sec import SecClient
            ua = os.environ.get("SEC_USER_AGENT") or UA_DEFAULT
            _CLIENT = SecClient(ua, RAW_DIR, max_rps=SEC_RPS)
        return _CLIENT


def fetch(ticker: str) -> dict:
    """Companyfacts JSON for a ticker (disk-cached under data/raw/). Raises FileNotFoundError when unknown."""
    global _TICKER_MAP
    c = _client()
    with _CLIENT_LOCK:
        if _TICKER_MAP is None:
            _TICKER_MAP = {}
            for r in c.tickers():
                _TICKER_MAP.setdefault(str(r["ticker"]).upper(), int(r["cik"]))
    t = ticker.upper()
    cik = _TICKER_MAP.get(t) or _TICKER_MAP.get(t.replace("-", ".")) or _TICKER_MAP.get(t.replace(".", "-"))
    if cik is None:
        raise FileNotFoundError(f"{ticker}: not in the SEC ticker map")
    return c.companyfacts(cik)


def is_ifrs(cf: dict, ticker: str = "") -> bool:
    facts = (cf or {}).get("facts") or {}
    ifrs, us = len(facts.get("ifrs-full", {})), len(facts.get("us-gaap", {}))
    if ifrs or us:
        return ifrs > us
    return ticker.upper() in IFRS_TICKERS


# --------------------------------------------------------------------------- classification
_NOT_TAGGED = re.compile(r"^FY\d+: (.+) is not tagged$")
_DOESNT_TAG = re.compile(r"doesn't tag (.+?); can't build")
_TIE_MARKERS = ("≠", "exceed", "FX/other")


def missing_concepts(flags: list[str]) -> list[str]:
    """Line items the audit says are untagged, de-duplicated (these are the concept gaps)."""
    out: list[str] = []
    for f in flags:
        m = _NOT_TAGGED.match(f)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def tie_flags(flags: list[str]) -> list[str]:
    return [f for f in flags if any(t in f for t in _TIE_MARKERS)]


def classify(rec: dict) -> tuple[str, str, str]:
    """(outcome, cause, detail) from a run_one record. Pure: the tests drive it with hand-built records."""
    err = rec.get("error")
    if rec.get("unsupported"):
        return "unsupported", "unsupported", rec["unsupported"]
    flags = rec.get("audit_flags", [])
    missing = rec.get("missing_concepts") or missing_concepts(flags)
    ifrs = bool(rec.get("ifrs"))
    if err:
        step, typ, msg = err.get("step", ""), err.get("type", "Exception"), err.get("message", "")
        if step == "fetch":
            return "fail", "fetch", f"{typ}: {msg}"
        if typ == "NoAnnualData":
            return "fail", ("IFRS concept gap" if ifrs else "mapping/missing concept"), msg
        if step in ("statements", "model") and missing:
            return "fail", ("IFRS concept gap" if ifrs else "mapping/missing concept"), "untagged: " + ", ".join(missing)
        if step in ("statements", "model") and tie_flags(flags):
            return "fail", "tie-out", "; ".join(tie_flags(flags)[:3])
        return "fail", f"exception:{typ}", f"{step}: {msg}"
    bad = rec.get("grade", {}).get("failed_critical", [])
    if bad:
        return "fail", f"grader:{bad[0]}", ", ".join(bad)
    val = rec.get("validate")
    if val and val.get("passed") is False:
        vbad = val.get("failed") or ["unknown"]
        return "fail", f"validate:{vbad[0]}", ", ".join(vbad)
    rc = rec.get("recalc", {})
    if rc and rc.get("agree") is False:
        return "fail", "engine divergence", f"{rc.get('divergences', 0)} divergent cells, e.g. {', '.join(rc.get('examples', [])[:3])}"
    up = rec.get("update", {})
    if up and up.get("error"):
        return "fail", f"exception:{up['error'].get('type', 'Exception')}", f"update: {up['error'].get('message', '')}"
    if up and up.get("seconds") is not None and up["seconds"] > TARGET_UPDATE_SECONDS:
        return "fail", "update too slow", f"{up['seconds']:.0f}s > {TARGET_UPDATE_SECONDS:.0f}s"
    return "pass", "", ""


# --------------------------------------------------------------------------- one company
class _Step:
    def __init__(self, timings: dict, name: str):
        self.timings, self.name = timings, name

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *a):
        self.timings[self.name] = round(time.perf_counter() - self.t0, 3)
        return False


def _err(step: str, e: BaseException) -> dict:
    return {"step": step, "type": type(e).__name__, "message": str(e)[:300]}


def _failed_graders(g: dict) -> list[str]:
    return [x["id"] for x in g.get("graders", []) if x.get("critical") and x.get("passed") is False]


def run_one(ticker: str, *, facts: dict | None = None, years: int = 5, engines=None) -> dict:
    """Run the pipeline for one ticker; never raises. `facts` bypasses the fetch (tests, replays)."""
    rec: dict = {"ticker": ticker, "ifrs": ticker.upper() in IFRS_TICKERS, "audit_flags": [], "timings": {},
                 "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    tm = rec["timings"]
    t_all = time.perf_counter()
    try:
        with _Step(tm, "fetch"):
            cf = facts if facts is not None else fetch(ticker)
        rec["ifrs"] = is_ifrs(cf, ticker)
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = _err("fetch", e)
        return _finish(rec, t_all)
    try:
        with _Step(tm, "statements"):
            s = stm.build(cf, ticker, years=years)
        with _Step(tm, "audit"):
            rec["audit_flags"] = stm.audit(s)
        rec["years"] = [y.isoformat() for y in s.years]
        rec["currency"] = s.currency
        rec["name"] = s.name
        rec["flagged"] = bool(rec["audit_flags"])
        rec["untagged_latest"] = [k for k in s.data if s.years and s.data[k][-1].value is None]      # internal keys with no value in the latest FY
        rec["missing_concepts"] = missing_concepts(rec["audit_flags"])
        rec["tie_flags"] = tie_flags(rec["audit_flags"])
        if not s.years:
            rec["error"] = {"step": "statements", "type": "NoAnnualData",
                            "message": "no fiscal year has both a revenue/net-income figure and a balance sheet"}
            return _finish(rec, t_all)
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = _err("statements", e)
        return _finish(rec, t_all)
    try:
        with _Step(tm, "model"):
            data1, meta1 = model3.build(s, circ=1)
        with _Step(tm, "model_circ0"):
            data0, _ = model3.build(s, circ=0)
        rec["converged"] = bool(meta1.get("converged"))
        rec["model_seconds"] = round(tm["model"] + tm["model_circ0"], 3)
    except model3.UnsupportedCompany as e:
        msg = str(e) or "UnsupportedCompany"
        m = _DOESNT_TAG.search(msg)
        if m:                                               # a concept gap, not an out-of-scope company: a failure
            rec["missing_concepts"] = sorted(set(rec.get("missing_concepts", [])) | {x.strip() for x in m.group(1).split(",")})
            rec["error"] = _err("model", e)
        else:
            rec["unsupported"] = msg
        return _finish(rec, t_all)
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = _err("model", e)
        return _finish(rec, t_all)
    try:
        with _Step(tm, "grade"):
            g = modelcheck.grade(data1)
        rec["grade"] = {"score": g.get("score"), "production_ready": g.get("production_ready"), "failed_critical": _failed_graders(g)}
        with _Step(tm, "validate"):
            v = validate_xlsx.validate(data1, require_sources=True)
        rules: dict = {}
        for f in v.get("findings", []):
            k = f"{f.get('id', '')}:{f.get('severity', '')}"
            rules[k] = rules.get(k, 0) + 1
        rec["validate"] = {"passed": v.get("passed"), "rules": rules,
                           "failed": sorted({f.get("id", "") for f in v.get("findings", []) if f.get("severity") == "critical"})}
        with _Step(tm, "recalc"):
            c = recalc.compare(data0, engines=engines)
        eng = c.get("engines", {})
        rec["recalc"] = {"agree": c.get("agree"), "divergences": len(c.get("divergences", [])), "compared_cells": c.get("compared_cells", 0),
                         "engines": [n for n, i in eng.items() if i.get("available")],
                         "unavailable": {n: i.get("reason", "") for n, i in eng.items() if not i.get("available")},
                         "examples": [d["cell"] for d in c.get("divergences", [])[:5]]}
    except Exception as e:                                  # noqa: BLE001
        rec["error"] = _err("checks", e)
        return _finish(rec, t_all)
    rec["update"] = _update(cf, ticker, s, years)
    return _finish(rec, t_all)


def _update(cf: dict, ticker: str, s: stm.Statements, years: int) -> dict:
    """Earnings-update drill: as of the day the latest fiscal year closed (before its 10-K), rebuild the model, then roll
    forward onto the current statements. Wall clock covers rebuild, roll-forward and the grade of the output."""
    up: dict = {"steps": {}}
    t0 = time.perf_counter()
    try:
        prior = s.years[-1]
        t = time.perf_counter()
        old_s = stm.build(cf, ticker, years=years, as_of=prior)
        up["steps"]["old_statements"] = round(time.perf_counter() - t, 3)
        if not old_s.years or old_s.years[-1] >= s.years[-1]:
            up["skipped"] = "no earlier filing in the facts to roll forward from"
            up["seconds"] = None
            return up
        t = time.perf_counter()
        old_x, old_meta = model3.build(old_s)
        up["steps"]["old_model"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        new_x, _ = rollforward.roll_forward(old_x, s, old_meta=old_meta)
        up["steps"]["roll_forward"] = round(time.perf_counter() - t, 3)
        t = time.perf_counter()
        g = modelcheck.grade(new_x)
        up["steps"]["grade"] = round(time.perf_counter() - t, 3)
        up["production_ready"] = bool(g.get("production_ready"))
        up["failed_critical"] = _failed_graders(g)
        up["from"], up["to"] = old_s.years[-1].isoformat(), s.years[-1].isoformat()
    except model3.UnsupportedCompany as e:
        up["skipped"] = f"unsupported: {e}"
    except Exception as e:                                  # noqa: BLE001
        up["error"] = {"type": type(e).__name__, "message": str(e)[:300]}
    up["seconds"] = None if up.get("skipped") else round(time.perf_counter() - t0, 3)
    return up


def _finish(rec: dict, t_all: float) -> dict:
    rec["timings"]["total"] = round(time.perf_counter() - t_all, 3)
    rec["outcome"], rec["cause"], rec["detail"] = classify(rec)
    return rec


# --------------------------------------------------------------------------- corpus
def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 3)


def summarize(results: dict) -> dict:
    recs = list(results.values())
    sup = [r for r in recs if r["outcome"] != "unsupported"]
    passed = [r for r in recs if r["outcome"] == "pass"]
    fails = [r for r in recs if r["outcome"] == "fail"]
    causes: dict[str, list[str]] = {}
    for r in fails:
        causes.setdefault(r["cause"], []).append(r["ticker"])
    split = {}
    for label, flag in (("US", False), ("IFRS", True)):
        sub = [r for r in recs if bool(r.get("ifrs")) == flag]
        ss = [r for r in sub if r["outcome"] != "unsupported"]
        npass = sum(1 for r in sub if r["outcome"] == "pass")
        split[label] = {"attempted": len(sub), "supported": len(ss), "unsupported": len(sub) - len(ss), "passed": npass,
                        "critical_pass_rate": (npass / len(ss)) if ss else None}
    builds = [r["model_seconds"] for r in recs if r.get("model_seconds") is not None]
    updates = [r["update"]["seconds"] for r in recs if r.get("update", {}).get("seconds") is not None]
    rules: dict[str, list[str]] = {}
    for r in recs:
        for k in r.get("validate", {}).get("rules", {}):
            rules.setdefault(k, []).append(r["ticker"])
    ifrs_fail = [r for r in fails if r.get("ifrs")]
    gap: dict[str, list[str]] = {}
    for r in ifrs_fail:
        for m in r.get("missing_concepts", []):
            gap.setdefault(m, []).append(r["ticker"])
    explained = [r["ticker"] for r in ifrs_fail if r.get("missing_concepts")]
    return {
        "attempted": len(recs), "supported": len(sup), "unsupported": len(recs) - len(sup), "passed": len(passed), "failed": len(fails),
        "critical_pass_rate": (len(passed) / len(sup)) if sup else None,
        "pass_rate_all_attempted": (len(passed) / len(recs)) if recs else None,
        "target_pass": TARGET_PASS,
        "causes": {k: sorted(v) for k, v in sorted(causes.items(), key=lambda kv: -len(kv[1]))},
        "split": split,
        "build_seconds": {"p50": _pct(builds, .5), "p95": _pct(builds, .95), "n": len(builds)},
        "update_seconds": {"p50": _pct(updates, .5), "p95": _pct(updates, .95), "n": len(updates), "target": TARGET_UPDATE_SECONDS,
                           "over_target": sorted(r["ticker"] for r in recs if (r.get("update", {}).get("seconds") or 0) > TARGET_UPDATE_SECONDS)},
        "validator_rules": {k: sorted(v) for k, v in sorted(rules.items(), key=lambda kv: -len(kv[1]))},
        "flagged_companies": sum(1 for r in recs if r.get("audit_flags")),
        "ifrs_gap": {"failed": len(ifrs_fail), "explained_by_missing_concepts": len(explained),
                     "share_explained": (len(explained) / len(ifrs_fail)) if ifrs_fail else None,
                     "concepts": {k: sorted(set(v)) for k, v in sorted(gap.items(), key=lambda kv: -len(set(kv[1])))}},
    }


def report(results: dict, out_of_scope: dict | None = None) -> str:
    S = summarize(results)
    pct = lambda x: "n/a" if x is None else f"{x:.1%}"
    sec = lambda x: "n/a" if x is None else f"{x:.1f}s"
    L = ["# Reliability run (D-032)", "",
         f"- Attempted **{S['attempted']}** companies: {S['passed']} pass, {S['failed']} fail, {S['unsupported']} unsupported (not counted as failures).",
         f"- **Critical-pass rate over supported companies: {pct(S['critical_pass_rate'])}** (target {TARGET_PASS:.0%}).",
         f"- Pass rate over all attempted: {pct(S['pass_rate_all_attempted'])}.",
         f"- Companies with at least one audit flag (figure flagged, not silent): {S['flagged_companies']}.",
         "", "## US vs IFRS", "", "| Population | Attempted | Supported | Unsupported | Pass | Critical-pass rate |", "|---|---|---|---|---|---|"]
    for k, v in S["split"].items():
        L.append(f"| {k} | {v['attempted']} | {v['supported']} | {v['unsupported']} | {v['passed']} | {pct(v['critical_pass_rate'])} |")
    L += ["", "## Timing (wall clock, workers share one machine)", "", "| Metric | p50 | p95 | n |", "|---|---|---|---|",
          f"| Model build (circ=1 + circ=0) | {sec(S['build_seconds']['p50'])} | {sec(S['build_seconds']['p95'])} | {S['build_seconds']['n']} |",
          f"| Earnings update (rebuild + roll-forward + grade), target < {TARGET_UPDATE_SECONDS:.0f}s | {sec(S['update_seconds']['p50'])} | {sec(S['update_seconds']['p95'])} | {S['update_seconds']['n']} |"]
    if S["update_seconds"]["over_target"]:
        L.append(f"\nOver the update target: {', '.join(S['update_seconds']['over_target'])}")
    L += ["", "## Failures by cause", ""]
    if not S["causes"]:
        L.append("None.")
    for cause, ts in S["causes"].items():
        ex = next((results[t]["detail"] for t in ts if results[t].get("detail")), "")
        L.append(f"- **{cause}** ({len(ts)}): {', '.join(ts)}" + (f" . e.g. {ex}" if ex else ""))
    L += ["", "## Validator rules fired (rule:severity, companies)", ""]
    for k, ts in S["validator_rules"].items():
        L.append(f"- {k} ({len(ts)}): {', '.join(ts[:12])}{' ...' if len(ts) > 12 else ''}")
    if not S["validator_rules"]:
        L.append("None.")
    g = S["ifrs_gap"]
    L += ["", "## IFRS concept gaps", ""]
    if not g["failed"]:
        L.append("No IFRS failures.")
    else:
        L.append(f"{g['failed']} IFRS failures; {g['explained_by_missing_concepts']} ({pct(g['share_explained'])}) have untagged line items the audit names.")
        for c, ts in g["concepts"].items():
            L.append(f"- {c}: {', '.join(ts)}")
    uns = [r for r in results.values() if r["outcome"] == "unsupported"]
    if uns or out_of_scope:
        L += ["", "## Out of scope / unsupported (not failures)", ""]
        for r in sorted(uns, key=lambda r: r["ticker"]):
            L.append(f"- {r['ticker']}: {r['detail']}")
        for t, why in sorted((out_of_scope or {}).items()):
            L.append(f"- {t}: out of scope ({why})")
    return "\n".join(L) + "\n"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def run(tickers: list[str], out_dir: str | Path = OUT_DIR, workers: int = 4, force: bool = False, runner=None, log=None) -> dict:
    """Run the corpus, resumable: tickers already in results.json are skipped unless force. Writes results.json and
    report.md (rewritten after every ticker so an interrupted run loses nothing). Returns {ticker: record}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rpath = out / "results.json"
    results: dict = {} if force else _load(rpath)
    todo = [t for t in dict.fromkeys(tickers) if t not in results]
    runner = runner or run_one
    lock = threading.Lock()

    def save():
        tmp = rpath.with_suffix(".tmp")
        tmp.write_text(json.dumps(results, indent=1, sort_keys=True, default=str))
        tmp.replace(rpath)
        (out / "report.md").write_text(report(results, OUT_OF_SCOPE))

    def job(t):
        rec = runner(t)
        with lock:
            results[t] = rec
            save()
            if log:
                log(f"{t}: {rec['outcome']} {rec.get('cause', '')} total={rec.get('timings', {}).get('total')}s")

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            list(ex.map(job, todo))
    else:
        save()
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="om.reliability")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, default=120)
    r.add_argument("--force", action="store_true")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--out", default=str(OUT_DIR))
    a = ap.parse_args(argv)
    os.environ.setdefault("SEC_USER_AGENT", UA_DEFAULT)
    res = run(universe(a.n), a.out, workers=a.workers, force=a.force, log=lambda m: print(m, flush=True))
    S = summarize(res)
    print(f"critical-pass {S['critical_pass_rate']} over {S['supported']} supported ({S['attempted']} attempted); report: {a.out}/report.md")
    return 0 if (S["critical_pass_rate"] or 0) >= TARGET_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
