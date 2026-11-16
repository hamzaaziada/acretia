"""S6.3 research eval runner.

    python3 -m eval.research.run --suite vals|financebench|btb|all --mode replay|live --limit N [--out DIR]

Calls the stable ``src.harness.research.api.run_research``. Replay mode builds an adapter that never opens a socket;
an item with no replay fixture is recorded as ``not_run`` (never faked). Live mode uses ``Adapter.from_env()`` and is
meant for the user's machine (D-021). Outputs go to ``data/evals/out/`` (untracked): per-item records, summary.json and
tsb_research.jsonl; ``scorecard.csv`` rows are written via ``score.update_scorecard`` (research/ rows only).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from eval.research import datasets
from eval.research.score import aggregate, score_item, scorecard_rows, update_scorecard

REPO = datasets.REPO
OUT_DEFAULT = REPO / "data" / "evals" / "out"
SCORECARD = REPO / "scorecard.csv"
TSB_VERSION = 1


def _suites(suite: str) -> dict:
    if suite == "all":
        return {"vals-v1": "vals_v1", "vals-v2": "vals_v2", "financebench": "financebench", "btb": "btb"}
    if suite == "vals":
        return {"vals-v1": "vals_v1", "vals-v2": "vals_v2"}
    if suite in ("financebench", "btb"):
        return {suite: suite}
    raise SystemExit(f"unknown suite {suite!r}")


def build_request(item):
    from src.harness.research.api import ResearchRequest
    q = item.question
    if item.dataset == "financebench" and item.meta.get("doc_name"):
        q = f"[{item.meta.get('company', '')} / {item.meta['doc_name']}] {q}"
    return ResearchRequest(question=q, tickers=list(item.tickers))


def run_item(item, adapter, *, runner=None, evidence_dir):
    """Returns the per-item record. Never raises for agent failures."""
    from src.harness.research.api import run_research
    runner = runner or run_research
    t0 = time.perf_counter()
    rec = {"id": item.id, "dataset": item.dataset, "category": item.category, "status": "not_run", "note": "",
           "figures": [], "citations": [], "verified": 0, "rejected": 0, "wall_clock_s": 0.0, "cost_usd": 0.0, "tokens": 0}
    result = None
    try:
        res = runner(build_request(item), adapter=adapter, evidence_dir=str(evidence_dir))
        result = res.to_dict() if hasattr(res, "to_dict") else dict(res)
    except Exception as e:   # contract errors etc.
        rec["status"], rec["note"] = ("not_run", f"not run (no fixture): {e}") if type(e).__name__ == "ReplayMiss" \
            else ("failed", f"{type(e).__name__}: {e}"[:300])
    rec["wall_clock_s"] = round(time.perf_counter() - t0, 4)
    if result is not None:
        err = result.get("error") or ""
        if "ReplayMiss" in err:
            rec["status"], rec["note"] = "not_run", "not run (no fixture)"
            result = None
        else:
            rec["status"] = result.get("status", "failed")
            rec["note"] = err[:300]
            figs = result.get("figures") or []
            rec["figures"] = [{"label": f.get("label"), "value": f.get("value"), "units": f.get("units"),
                               "period": f.get("period")} for f in figs]
            rec["citations"] = [{k: (f.get("citation") or {}).get(k) for k in ("doc_id", "page", "url", "quote", "as_of")}
                                for f in figs]
            rec["verified"], rec["rejected"] = len(figs), len(result.get("rejected") or [])
            rec["cost_usd"], rec["tokens"] = float(result.get("cost_usd") or 0), int(result.get("tokens") or 0)
    return rec, result


def make_adapter(mode: str):
    from src.harness.adapter import Adapter
    return Adapter.from_env(mode="replay") if mode == "replay" else Adapter.from_env()


def tsb_record(rec: dict, suite: str, mode: str, ran_live: bool, ts: str) -> dict:
    return {"v": TSB_VERSION, "task": "research_qa", "suite": f"research/{suite}", "item_id": rec["id"],
            "category": rec["category"], "mode": mode, "ran_live": "yes" if ran_live else "no", "status": rec["status"],
            "T_a": {"wall_clock_s": rec["wall_clock_s"], "cost_usd": rec["cost_usd"], "tokens": rec["tokens"]},
            "review_and_fix_min": None, "ts": ts}


def run(suite="all", mode="replay", limit=None, out=None, *, data_root=None, adapter=None, runner=None,
        scorecard_path=SCORECARD, update_card=True, now=None) -> dict:
    out = Path(out) if out else OUT_DEFAULT
    out.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    ts, today = now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%d")
    if adapter is None:
        adapter = make_adapter(mode)
    summary = {"v": 1, "mode": mode, "date": today, "suites": {}}
    all_rows, tsb_lines = [], []
    with tempfile.TemporaryDirectory(prefix="evals-evidence-") as ev_dir:
        for sname, dname in _suites(suite).items():
            try:
                items = datasets.load(dname, data_root)
            except datasets.DatasetUnavailable as e:
                agg = aggregate([])
                summary["suites"][sname] = {"status": "dataset_unavailable", "reason": str(e), **agg}
                all_rows += scorecard_rows(sname, agg, mode=mode, today=today, note="dataset unavailable (not fetched)")
                continue
            if limit:
                items = items[:limit]
            scored, records = [], []
            for it in items:
                rec, result = run_item(it, adapter, runner=runner, evidence_dir=ev_dir)
                sc = score_item(it, result)
                rec["score"] = sc
                scored.append((sc, rec))
                records.append(rec)
                tsb_lines.append(tsb_record(rec, sname, mode, mode == "live" and rec["status"] != "not_run", ts))
            agg = aggregate(scored)
            note = "BTB rubric scoring needs a deliverable grader; no client-ready rate" if dname == "btb" else ""
            summary["suites"][sname] = {"status": "ok", **agg, "items": records}
            all_rows += scorecard_rows(sname, agg, mode=mode, today=today, note=note)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    with (out / "tsb_research.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, sort_keys=True) + "\n" for r in tsb_lines)
    if update_card:
        update_scorecard(scorecard_path, all_rows)
    summary["scorecard_rows"] = all_rows
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eval.research.run")
    ap.add_argument("--suite", default="all", choices=["vals", "financebench", "btb", "all"])
    ap.add_argument("--mode", default="replay", choices=["replay", "live"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--data-root", help="datasets root (default data/evals; use eval/research/fixtures for a smoke run)")
    ap.add_argument("--no-scorecard", action="store_true")
    a = ap.parse_args(argv)
    use_fixtures = bool(a.data_root) and Path(a.data_root).resolve() == datasets.FIXTURES.resolve()
    s = run(a.suite, a.mode, a.limit, a.out, data_root=a.data_root, update_card=not (a.no_scorecard or use_fixtures))
    for name, d in s["suites"].items():
        print(f"{name}: {d['status']} n={d['n']} run={d['n_run']} accuracy={d['accuracy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
