"""Scorer for the S6.3 research evals.

Our bar: a correct number WITHOUT a verified citation scores as wrong. Numbers match within 1% relative (exact for
counts) after unit normalisation. Gold answers that are long free text cannot be scored deterministically and are
reported as ``unscorable`` (excluded from the accuracy denominator, never silently counted as right).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path

REL_TOL = 0.01
SCORECARD_COLUMNS = ["stage", "eval", "n", "score", "notes"]
_SCALE = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
_UNIT_FIGURE = {"usd": ("money", 1.0), "usd_k": ("money", 1e3), "usd_m": ("money", 1e6), "usd_mm": ("money", 1e6),
                "usd_bn": ("money", 1e9), "usd_b": ("money", 1e9), "pct": ("frac", 0.01), "percent": ("frac", 0.01),
                "%": ("frac", 0.01), "bps": ("frac", 1e-4), "bp": ("frac", 1e-4), "count": ("count", 1.0),
                "shares": ("count", 1.0), "x": ("plain", 1.0), "ratio": ("plain", 1.0)}
_NUM = re.compile(r"(?<![A-Za-z0-9.])(?P<open>\()?(?P<cur>[$€£])?\s?(?P<sign>[-−–])?(?P<cur2>[$€£])?"
                  r"(?P<num>\d[\d,]*(?:\.\d+)?|\.\d+)\s?"
                  r"(?P<unit>%|bps|bp|basis points|billion|bn|million|mm|thousand|[bmkx])?(?![A-Za-z0-9])")


def parse_numbers(text: str) -> list:
    """All numeric tokens in ``text`` as dicts(value, kind, currency, scaled). Year-like bare numbers are skipped."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group("num")
        unit = (m.group("unit") or "").lower()
        cur = bool(m.group("cur") or m.group("cur2"))
        if not unit and not cur and re.fullmatch(r"(19|20)\d\d", raw):
            continue
        v = float(raw.replace(",", ""))
        if m.group("sign") or m.group("open"):
            v = -v
        kind, scaled = "plain", False
        if unit == "%":
            kind, v = "frac", v / 100
        elif unit in ("bps", "bp", "basis points"):
            kind, v = "frac", v / 1e4
        elif unit in _SCALE:
            kind, v, scaled = "money" if (cur or unit in ("billion", "million", "thousand", "bn", "mm")) else "plain", \
                v * _SCALE[unit], True
        elif cur:
            kind = "money"
        elif unit == "x":
            kind = "plain"
        elif "." not in raw and "," not in raw:
            kind = "count"
        out.append({"value": v, "kind": kind, "currency": cur, "scaled": scaled})
    return out


_CCY = r"(?:usd|eur|gbp|egp|sar|aed|us\$|\$|€|£)"
_SCALE_WORDS = {"thousand": 1e3, "thousands": 1e3, "k": 1e3, "'000": 1e3, "000s": 1e3, "000": 1e3,
                "million": 1e6, "millions": 1e6, "mm": 1e6, "mn": 1e6, "m": 1e6,
                "billion": 1e9, "billions": 1e9, "bn": 1e9, "b": 1e9}


def _unit_parts(units) -> tuple:
    """Canonical (kind, multiplier) for a units string; case-insensitive. Unknown strings give ("plain", 1.0)."""
    u = str(units or "").strip().lower().replace("’", "'").replace("_", " ").replace("-", " ")
    u = re.sub(r"\s+", " ", u)
    if u in _UNIT_FIGURE:
        return _UNIT_FIGURE[u]
    if u in ("%", "pct", "percent", "percentage", "percentage points", "pp"):
        return "frac", 0.01
    if u in ("bps", "bp", "basis points", "basis point"):
        return "frac", 1e-4
    if u in ("ratio", "x", "times", "multiple", "turns"):
        return "plain", 1.0
    if u in ("count", "shares", "units", "number", "employees"):
        return "count", 1.0
    m = re.fullmatch(rf"({_CCY})?\s*(?:in |\()?\s*('?000s?|[a-z]+)?\)?\s*(?:/|per )?\s*(share|shares|sh|unit)?", u)
    if m and (m.group(1) or m.group(3)) and (m.group(2) is None or m.group(2) in _SCALE_WORDS or m.group(2) == "000s"):
        if m.group(3):                               # "USD/share" is a per-share amount, never scaled
            return "money", 1.0
        return "money", _SCALE_WORDS.get(m.group(2), 1.0) if m.group(2) else 1.0
    m = re.fullmatch(r"(?:in )?('?000s?|thousands?|millions?|billions?|mm|mn|bn|k)(?: of)?\s*(?:" + _CCY + r")?", u)
    if m and (m.group(1) in _SCALE_WORDS):
        return "money", _SCALE_WORDS[m.group(1)]
    return "plain", 1.0


def normalise_figure(value, units) -> dict:
    kind, mult = _unit_parts(units)
    return {"value": float(value) * mult, "kind": kind}


def numbers_match(gold: dict, fig: dict, rel_tol: float = REL_TOL) -> bool:
    g, f = gold["value"], fig["value"]
    exact = gold["kind"] == "count" and not gold["currency"]
    cands = [g]
    if gold["kind"] in ("money", "plain", "count") and not gold["scaled"] and (gold["currency"] or fig["kind"] == "money"):
        cands += [g * 1e3, g * 1e6, g * 1e9]        # "$1577" answered as USD_m: question states the unit
    for c in cands:
        if exact and c == g:
            if f == g:
                return True
        elif abs(f - c) <= rel_tol * max(abs(c), 1e-12):
            return True
        elif c == 0 and f == 0:
            return True
    return False


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def citation_verified(fig: dict) -> bool:
    c = fig.get("citation") or {}
    has_hash = bool(re.fullmatch(r"[0-9a-f]{64}", c.get("sha256_span_hash") or ""))
    return bool(c.get("doc_id")) and has_hash and (bool(c.get("url") or c.get("source_url")) or c.get("page") is not None)


def evidence_overlap(figures: list, gold_evidence: list):
    """None when the item has no gold evidence; else True when any citation hits a gold page (same doc if both known)
    or its quote overlaps a gold quote (substring either way, or token Jaccard >= 0.5)."""
    if not gold_evidence:
        return None
    for f in figures:
        c = f.get("citation") or {}
        cq = _norm_text(c.get("quote", ""))
        for g in gold_evidence:
            gd, cd = _norm_text(g.get("doc", "")), _norm_text(c.get("doc_id", ""))
            doc_ok = not gd or not cd or gd in cd or cd in gd
            if doc_ok and g.get("page") is not None and c.get("page") == g["page"]:
                return True
            gq = _norm_text(g.get("quote", ""))
            if cq and gq and doc_ok:
                if cq in gq or gq in cq:
                    return True
                a, b = set(cq.split()), set(gq.split())
                if a and b and len(a & b) / len(a | b) >= 0.5:
                    return True
    return False


def score_item(item, result: dict | None) -> dict:
    """``item``: EvalItem; ``result``: ResearchResult.to_dict() or None when the item was not run.
    Returns {scorable, correct, numeric_ok, cited, evidence_ok, reason}."""
    gold = (item.gold_answer or "").strip()
    out = {"scorable": True, "correct": False, "numeric_ok": False, "cited": False, "evidence_ok": None, "reason": ""}
    if item.meta.get("needs_deliverable_grader") or not gold:
        return {**out, "scorable": False, "reason": "rubric grading needs deliverable grader (live)"}
    gnums = parse_numbers(gold)
    mode = "numeric" if gnums and len(gold) <= 200 else "text" if not gnums and len(gold) <= 80 else None
    if mode is None:
        return {**out, "scorable": False, "reason": "free-text gold needs LLM judge (live)"}
    if result is None or result.get("status") not in ("succeeded",):
        out["reason"] = "not run" if result is None else f"status {result.get('status')}"
        return out
    figures = list(result.get("figures") or [])
    if mode == "numeric":
        nf = [(f, normalise_figure(f["value"], f.get("units"))) for f in figures]
        hits = []
        for g in gnums:
            hit = next(((f, n) for f, n in nf if numbers_match(g, n)), None)
            hits.append(hit)
        out["numeric_ok"] = all(hits)
        matched = [h[0] for h in hits if h]
        out["cited"] = out["numeric_ok"] and all(citation_verified(f) for f in matched)
        used = matched or figures
    else:
        blob = _norm_text(" ".join(f"{f.get('label', '')} {f.get('period', '')}" for f in figures))
        g = _norm_text(gold)
        out["numeric_ok"] = bool(g) and (g == blob or g in blob)
        matched = figures
        out["cited"] = out["numeric_ok"] and any(citation_verified(f) for f in figures)
        used = figures
    out["evidence_ok"] = evidence_overlap(used, item.gold_evidence)
    out["correct"] = out["numeric_ok"] and out["cited"]
    out["reason"] = ("ok" if out["correct"] else "correct value but no verified citation (scored wrong)"
                     if out["numeric_ok"] else "no matching figure")
    return out


def aggregate(scored: list) -> dict:
    """scored: list of (score dict, record dict). Returns n / n_run / n_scorable / accuracy / evidence_rate."""
    n = len(scored)
    run = [s for s, r in scored if r.get("status") != "not_run"]
    scorable = [s for s, r in scored if s["scorable"] and r.get("status") != "not_run"]
    ev = [s for s in scorable if s["evidence_ok"] is not None]
    return {"n": n, "n_run": len(run), "n_scorable": len(scorable),
            "n_unscorable": sum(1 for s, _ in scored if not s["scorable"]),
            "accuracy": (sum(s["correct"] for s in scorable) / len(scorable)) if scorable else None,
            "numeric_only_accuracy": (sum(s["numeric_ok"] for s in scorable) / len(scorable)) if scorable else None,
            "evidence_rate": (sum(bool(s["evidence_ok"]) for s in ev) / len(ev)) if ev else None, "n_evidence": len(ev)}


def _notes_live(notes: str) -> bool:
    return "ran_live=yes" in (notes or "")


def update_scorecard(path, rows: list) -> None:
    """Upsert ``rows`` (dicts with stage, eval, n, score, notes) into the 5-column scorecard (D-S6-01), keyed by
    (stage, eval). Only evals starting with "research/" may be written (ValueError otherwise). Foreign rows are
    kept byte-identical; no columns are ever added. A replay row never overwrites a live row (ran_live in notes)."""
    path = Path(path)
    for r in rows:
        if not str(r.get("eval", "")).startswith("research/"):
            raise ValueError(f"update_scorecard only writes research/ rows, got eval {r.get('eval')!r}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = text.splitlines(keepends=True)
    header = ",".join(SCORECARD_COLUMNS) + "\n"
    recs, prev = [], 0                     # (raw_text, parsed_row)
    if text.strip():
        rd = csv.reader(io.StringIO(text))
        cols = next(rd)
        if cols != SCORECARD_COLUMNS:
            raise ValueError(f"scorecard header {cols} != {SCORECARD_COLUMNS} (D-S6-01)")
        header, prev = lines[0], rd.line_num
        for row in rd:
            recs.append(["".join(lines[prev:rd.line_num]), dict(zip(SCORECARD_COLUMNS, row))])
            prev = rd.line_num
    for new in rows:
        key = (new.get("stage", "S6"), new["eval"])
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerow([new.get(c, "") for c in SCORECARD_COLUMNS])
        raw = out.getvalue()
        i = next((i for i, (_, r) in enumerate(recs) if (r["stage"], r["eval"]) == key), None)
        if i is None:
            recs.append([raw, dict(zip(SCORECARD_COLUMNS, [new.get(c, "") for c in SCORECARD_COLUMNS]))])
        elif not (_notes_live(recs[i][1]["notes"]) and not _notes_live(new.get("notes", ""))):
            recs[i] = [raw, recs[i][1] | {c: new.get(c, "") for c in SCORECARD_COLUMNS}]
    body = "".join(r[0] if r[0].endswith("\n") else r[0] + "\n" for r in recs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body, encoding="utf-8")


def scorecard_rows(suite: str, agg: dict, *, mode: str, today: str | None = None, note: str = "") -> list:
    live = mode == "live" and agg["n_run"] > 0
    d = today or date.today().isoformat()
    tail = "; ".join(x for x in (note, "" if live else "not run live (D-021)") if x)
    meta = f"mode={mode}; ran_live={'yes' if live else 'no'}; date={d}; "

    def val(x):
        return "" if x is None or not live else f"{x:.4f}"
    unsc = f"; {agg['n_unscorable']} unscorable excluded" if agg["n_unscorable"] else ""
    mk = lambda metric, v, n, t: {"stage": "S6", "eval": f"research/{suite}/{metric}", "n": n, "score": v,  # noqa: E731
                                  "notes": meta + t}
    return [mk("strict_accuracy", val(agg["accuracy"]), agg["n_scorable"], tail + unsc),
            mk("evidence_rate", val(agg["evidence_rate"]), agg["n_evidence"], tail),
            mk("items_run", str(agg["n_run"]) if live else "", agg["n"], tail)]
