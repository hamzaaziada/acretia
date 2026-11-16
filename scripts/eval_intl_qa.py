#!/usr/bin/env python3
"""S8.7c standards Q&A eval. Deterministic: KB.answer on each question, scored against a key-point rubric.

Pass = >= 75% of key points match AND >= 1 citation matches must_cite AND every citation has a URL.
No model calls (live_model=no). Writes results.jsonl and the S8 standards_qa row of scorecard.csv.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QDIR = ROOT / "evals" / "intl" / "standards_qa"
SCORECARD = ROOT / "scorecard.csv"
HEADER = ["stage", "eval", "n", "score", "notes"]
THRESHOLD_POINTS = 0.75
_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي", "ـ": ""})
_AR_DIAC = re.compile("[ً-ٰٟ]")
_EAST = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def norm(text) -> str:
    t = _AR_DIAC.sub("", str(text)).translate(_AR_MAP).translate(_EAST).lower()
    t = re.sub(r"\b(?:percent|per cent|pct)\b", "%", t)
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    return re.sub(r"\s+", " ", t).strip()


def point_matches(point: str, text: str) -> bool:
    """Regex (case-insensitive) searched in the Arabic-normalised text, also with hyphens/slashes read as spaces."""
    n = norm(text)
    variants = (n, re.sub(r"[-_/]", " ", n))
    try:
        rx = re.compile(norm(point), re.I)
    except re.error:
        rx = re.compile(re.escape(norm(point)), re.I)
    return any(rx.search(v) for v in variants)


def cite_matches(must_cite, citations) -> bool:
    for c in citations:
        hay = norm(f"{c.get('standard', '')} {c.get('ref', '')}")
        if any(norm(m) in hay for m in must_cite):
            return True
    return False


def score_answer(question: dict, text: str, citations: list) -> dict:
    kps = question["key_points"]
    matched = [p for p in kps if point_matches(p, text)]
    frac = len(matched) / len(kps) if kps else 0.0
    cite_ok = cite_matches(question["must_cite"], citations)
    url_ok = bool(citations) and all(str(c.get("url", "")).strip() for c in citations)
    return {"id": question["id"], "pass": frac >= THRESHOLD_POINTS and cite_ok and url_ok,
            "points_fraction": round(frac, 3), "matched_points": matched, "missed_points": [p for p in kps if p not in matched],
            "cite_ok": cite_ok, "url_ok": url_ok}


def load_questions(path: Path = QDIR / "questions.jsonl") -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run(kb=None, qfile: str = "questions.jsonl") -> list:
    if kb is None:
        sys.path.insert(0, str(ROOT))
        from om.intl.standards import load
        kb = load()
    out = []
    for q in load_questions(QDIR / qfile):
        a = kb.answer(q["question"])
        cits = [{"standard": c.get("standard"), "ref": c.get("ref"), "url": c.get("url")} for c in a.citations]
        r = score_answer(q, a.text, a.citations)
        r.update({"citations": cits, "entries": [e.get("id") for e in a.entries], "answer": a.text[:600]})
        out.append(r)
    return out


def write_scorecard(n: int, score: float, path: Path = SCORECARD, eval_name: str = "standards_qa") -> None:
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    header = rows[0] if rows else HEADER
    body = [r for r in rows[1:] if not (len(r) > 1 and r[0] == "S8" and r[1] == eval_name)]
    new = {"stage": "S8", "eval": eval_name, "n": str(n), "score": f"{score:.3f}",
           "notes": "live_model=no; deterministic retrieval; key-point rubric >=75%, cite match, url on every citation"}
    body.append([new.get(h, "") for h in header])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body)


def main() -> int:
    heldout = "--set" in sys.argv and sys.argv[sys.argv.index("--set") + 1:][:1] == ["heldout"]
    res = run(qfile="heldout.jsonl" if heldout else "questions.jsonl")
    with (QDIR / ("heldout_results.jsonl" if heldout else "results.jsonl")).open("w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(res)
    score = sum(r["pass"] for r in res) / n
    write_scorecard(n, score, eval_name="standards_qa_heldout" if heldout else "standards_qa")
    print(f"{'standards_qa_heldout' if heldout else 'standards_qa'}: {sum(r['pass'] for r in res)}/{n} = {score:.3f}")
    for r in res:
        if not r["pass"]:
            print(f"FAIL {r['id']} points={r['points_fraction']} cite={r['cite_ok']} url={r['url_ok']} missed={r['missed_points']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
