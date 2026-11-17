"""Human time baselines (T_h) parsed from docs/time-saved-baselines.md (SPEC section 11).

`load()` returns {"tasks": {task_id: row}, "competitor_claims": [...]}.  A row is either
{"t_h_low", "t_h_mid", "t_h_high" (minutes), "confidence", "source", "raw", "row", "status": "estimate"} or, for tasks
with no credible published figure, {"baseline": "own timing study needed", ...} with no number.  Numbers are never
invented; anything that cannot be parsed raises BaselineParseError.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "docs" / "time-saved-baselines.md"
NO_BASELINE = "own timing study needed"

# Explicit name table: the row label (lower-case prefix) in section 2 -> task_ids.
NAME_TABLE: dict[str, tuple[str, ...]] = {
    "3-statement": ("three_statement",),
    "dcf": ("dcf",),
    "lbo (full)": ("lbo",),
    "merger": ("merger",),
    "trading comps": ("comps",),
    "precedent transactions": ("precedents",),
    "data-room first-pass": ("vdr_review",),
    "earnings model update": ("earnings_update",),
    "ic memo": ("ic_memo",),
    "company profile": ("profile", "pitchbook_section", "teaser", "buyer_list", "earnings_recap"),
}
NO_FIGURE = "no credible figure"

_U = r"(min(?:ute)?s?|hrs?|hours?|weeks?|days?)"
_N = r"(\d+(?:\.\d+)?)"
_RANGE = re.compile(rf"{_N}\s*{_U}?\s*[–\-]\s*{_N}\s*{_U}")
_SINGLE = re.compile(rf"{_N}\s*{_U}")
_UNIT_MIN = {"min": 1.0, "hr": 60.0, "hour": 60.0, "week": 2400.0, "day": 480.0}   # a work week = 40 h, a work day = 8 h
CONF = ("very low", "low", "medium", "high", "none")


class BaselineParseError(ValueError):
    pass


def _unit(u: str) -> float:
    u = u.lower()
    for k, v in _UNIT_MIN.items():
        if u.startswith(k):
            return v
    raise BaselineParseError(f"unknown time unit {u!r}")


def parse_range(text: str) -> tuple[float, float]:
    """First range (or single figure) in a free-text cell, in minutes: '2-3 hrs' -> (120, 180)."""
    t = text.replace("–", "-").replace("—", "-").replace("~", "").replace("‑", "-")
    best = None
    for rx in (_RANGE, _SINGLE):
        m = rx.search(t)
        if m and (best is None or m.start() < best[0].start()):
            best = (m, rx)
    if best is None:
        raise BaselineParseError(f"no time range in {text!r}")
    m, rx = best
    if rx is _RANGE:
        a, ua, b, ub = m.group(1), m.group(2), m.group(3), m.group(4)
        lo, hi = float(a) * _unit(ua or ub), float(b) * _unit(ub)
    else:
        lo = hi = float(m.group(1)) * _unit(m.group(2))
    if lo <= 0 or hi < lo:
        raise BaselineParseError(f"implausible range {lo}-{hi} min parsed from {text!r}")
    return lo, hi


def _clean(s: str) -> str:
    return re.sub(r"\*\*|`", "", s).strip()


def _tables(md: str) -> dict[str, list[list[str]]]:
    """Section heading prefix ('1', '2') -> rows (header excluded) of the first pipe table under it."""
    out: dict[str, list[list[str]]] = {}
    sec = None
    rows: list[list[str]] = []
    for line in md.splitlines() + ["## end"]:
        m = re.match(r"##\s+(\d+)\.", line)
        if m or line.startswith("## "):
            if sec and rows and sec not in out:
                out[sec] = rows
            sec, rows = (m.group(1) if m else None), []
            continue
        if sec and line.lstrip().startswith("|"):
            cells = [_clean(c) for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            rows.append(cells)
    return {k: v[1:] for k, v in out.items() if len(v) > 1}


def _conf(cell: str) -> str:
    c = cell.strip().lower()
    for k in CONF:
        if c.startswith(k):
            return k
    raise BaselineParseError(f"unreadable confidence {cell!r}")


def _claims(rows: list[list[str]]) -> list[dict]:
    out = []
    for r in rows:
        if len(r) < 6:
            raise BaselineParseError(f"competitor claim row has {len(r)} cells, expected 6: {r!r}")
        types = re.findall(r"\[(vendor|customer|independent|anecdote)\]", r[3])
        out.append({"who": r[0], "claim": r[1], "metric": r[2], "type": "/".join(types) or "unlabelled",
                    "method": r[4], "source": r[5]})
    return out


def parse(md: str) -> dict:
    tabs = _tables(md)
    if "2" not in tabs:
        raise BaselineParseError("section 2 (human baselines) has no table")
    if "1" not in tabs:
        raise BaselineParseError("section 1 (competitor claims) has no table")
    tasks: dict[str, dict] = {}
    for r in tabs["2"]:
        if len(r) < 4:
            raise BaselineParseError(f"baseline row has {len(r)} cells, expected 4: {r!r}")
        name, rng, src, conf = r[:4]
        key = next((k for k in NAME_TABLE if name.lower().startswith(k) or k in name.lower().split(" (")[0]), None)
        if key is None:
            continue                                        # a row with no catalogue task (LBO paper, CIM, complex)
        if NO_FIGURE in rng.lower():
            row = {"baseline": NO_BASELINE, "confidence": "none", "source": "", "raw": rng, "row": name, "status": "estimate"}
        else:
            lo, hi = parse_range(rng)
            row = {"t_h_low": lo, "t_h_mid": round(math.sqrt(lo * hi), 1), "t_h_high": hi, "confidence": _conf(conf),
                   "source": src, "raw": rng, "row": name, "status": "estimate", "unit": "minutes"}
        for tid in NAME_TABLE[key]:
            tasks[tid] = dict(row)
    missing = sorted({t for ts in NAME_TABLE.values() for t in ts} - set(tasks))
    if missing:
        raise BaselineParseError(f"section 2 has no row for: {', '.join(missing)}")
    return {"tasks": tasks, "competitor_claims": _claims(tabs["1"])}


_CACHE: dict[str, dict] = {}


def load(path=None) -> dict:
    p = Path(path) if path else DEFAULT_PATH
    key = str(p.resolve())
    st = p.stat()
    sig = f"{st.st_mtime_ns}:{st.st_size}"
    hit = _CACHE.get(key)
    if hit and hit["sig"] == sig:
        return hit["data"]
    data = parse(p.read_text(encoding="utf-8"))
    _CACHE[key] = {"sig": sig, "data": data}
    return data


def time_saved(task_id: str, t_a_minutes: float, baselines: dict | None = None) -> dict:
    """The `time_saved` object attached to a delivered job (SPEC section 5). Always an estimate until a pilot validates it."""
    b = (baselines or load())["tasks"].get(task_id)
    if not b or "baseline" in b:
        return {"task_id": task_id, "baseline": NO_BASELINE, "t_a_minutes": round(t_a_minutes, 2), "basis": "estimate"}
    pct = {k: round(1 - t_a_minutes / b[f"t_h_{k}"], 4) for k in ("low", "mid", "high")}
    return {"task_id": task_id, "basis": "estimate",
            "t_h_minutes": {"low": b["t_h_low"], "mid": b["t_h_mid"], "high": b["t_h_high"], "source": b["source"],
                            "confidence": b["confidence"]},
            "t_a_minutes": round(t_a_minutes, 2), "pct": pct}
