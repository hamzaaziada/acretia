#!/usr/bin/env python3
"""Time-saved benchmark runner (SPEC section 11, PLAN "North-star metrics", D-032).

    python3 eval/tsb/run.py --replay                 # default; offline, fixtures only, zero sockets
    python3 eval/tsb/run.py --replay --tasks dcf,comps --n 3 --out /tmp/tsb
    python3 eval/tsb/run.py --live                   # refuses unless ACRETIA_LLM_MODE=live and ACRETIA_LLM_API_KEY are set

Each brief runs as a real job through `om.api.jobs` (temp data dir, seeded demo org, source_review=false, approval gates
auto-approved with the ghost deck as drafted).  Per brief: wall time, per-step telemetry, deterministic grades, persona "edits
needed" (replay: canned placeholders under tests/fixtures/eval/persona_edits/, clearly labelled; live: hook below), then
review_fix = sum(edits x minutes), T_a = wall + review_fix, T_h from baselines.load().

Every row is an `estimate`.  Nothing here is human-validated; that needs the paired-timing pilot (pilot.md).
Speed, error rate and client-ready rate are reported separately.  A task whose engine is missing reports `blocked`, never a number.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.reliability import (Harness, audit_run, circularity_check, fmt, gate_result, iqr, median)  # noqa: E402
from eval.tsb import baselines  # noqa: E402

HERE = Path(__file__).resolve().parent
PERSONA_DIR = REPO / "tests" / "fixtures" / "eval" / "persona_edits"
TASK_ORDER = ("comps", "precedents", "three_statement", "dcf", "lbo", "merger", "vdr_review", "profile", "pitchbook_section", "teaser",
              "ic_memo", "earnings_update", "earnings_recap", "buyer_list")
PERSONA_PASS = 8.5
# which competitor claims (matched on the `who` column of the baselines doc, section 1) sit beside which task
CLAIM_MAP = {
    "three_statement": ("Wall Street Prep", "Ankura", "Daloopa", "BankerToolBench"),
    "dcf": ("Shortcut",), "lbo": ("Shortcut", "BankerToolBench"), "merger": ("Shortcut", "BankerToolBench"),
    "comps": ("Daloopa", "Hebbia"), "precedents": ("Hebbia",),
    "vdr_review": ("Rogo / Harbor View", "AlphaSense", "Brightwave", "Hebbia"),
    "earnings_update": ("Daloopa",), "earnings_recap": ("Daloopa",), "ic_memo": ("Brightwave", "Rogo / Baird"),
    "profile": ("Rogo / Baird",), "pitchbook_section": ("Rogo / Baird",), "teaser": ("Rogo / Harbor View",), "buyer_list": ("Hebbia",),
}
GENERAL_CLAIMS = ("Rogo", "Hebbia", "BankerToolBench", "Vals Finance Agent v2")
CSV_COLS = ["brief_id", "task_id", "region", "ticker", "data", "outcome", "blocked_reason", "wall_min", "review_fix_min", "t_a_min", "t_h_low_min",
            "t_h_mid_min", "t_h_high_min", "saved_low", "saved_mid", "saved_high", "baseline", "gates_pass", "model_score", "silent_numbers",
            "client_ready", "blocking", "persona_score", "edits", "status"]


# --------------------------------------------------------------------------- inputs
def load_edit_minutes(path: Path = HERE / "edit_minutes.csv") -> dict[str, float]:
    with open(path, newline="", encoding="utf-8") as f:
        return {r["edit_class"]: float(r["minutes"]) for r in csv.DictReader(f)}


def load_briefs(path: Path = HERE / "briefs.json") -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["briefs"]


def persona_edits(task_id: str, live_hook=None, run=None) -> dict:
    """Persona "edits needed" for a task.  Replay: the canned placeholder fixture.  Live: `live_hook(run)` must return the same shape
    ({"persona_score": float|None, "edits": [{"edit_class", "count", "blocking", "note"}]}); the Haiku persona call is out of scope here."""
    if live_hook is not None:
        return live_hook(run)
    p = PERSONA_DIR / f"{task_id}.json"
    if not p.is_file():
        return {"label": "no persona edit list for this task", "persona_score": None, "edits": [], "missing": True}
    return json.loads(p.read_text(encoding="utf-8"))


def review_fix_minutes(edits: list[dict], minutes: dict[str, float]) -> float:
    tot = 0.0
    for e in edits:
        if e["edit_class"] not in minutes:
            raise KeyError(f"edit class {e['edit_class']!r} is not in edit_minutes.csv")
        tot += float(e.get("count", 1)) * minutes[e["edit_class"]]
    return tot


# --------------------------------------------------------------------------- one brief
def run_brief(h: Harness, b: dict, bl: dict, minutes: dict[str, float], live_hook=None) -> dict:
    row = {k: "" for k in CSV_COLS}
    row.update(brief_id=b["id"], task_id=b["task_id"], region=b.get("region", ""), ticker=b.get("ticker") or "", data=b["data"], status="estimate")
    task = b["task_id"]
    t0 = time.perf_counter()
    run = h.run(b["prompt"], deal=b.get("deal"))
    row["wall_min"] = round(run.wall_seconds / 60.0, 5)
    row["_elapsed_s"] = run.elapsed_seconds
    row["_steps"] = [{"id": s["id"], "fn": s.get("fn"), "engine": s.get("engine"), "status": s["status"], "seconds": s.get("seconds"),
                      "tokens": s.get("tokens"), "cost_usd": s.get("cost_usd")} for s in run.steps]
    row["_cost_usd"] = run.cost_usd
    if run.blocked:
        row.update(outcome="blocked", blocked_reason=(run.hint or run.error or "")[:200])
        return row
    if not run.done:
        row.update(outcome="failed", blocked_reason=(run.error or "")[:200])
        return row
    gates = gate_result(run)
    aud = audit_run(h, run)
    pe = persona_edits(task, live_hook, run)
    edits = pe.get("edits", [])
    rf = review_fix_minutes(edits, minutes)
    t_a = row["wall_min"] + rf
    blocking = list(gates["blocking"]) + [f"persona: {e['edit_class']} x{e.get('count', 1)}" for e in edits if e.get("blocking")]
    ps = pe.get("persona_score")
    det_ok = gates["pass"] and not blocking and aud.silent == 0
    if not det_ok:
        cr = "no"
    elif ps is None:
        cr = "unknown"
    else:
        cr = "yes" if ps >= PERSONA_PASS else "no"
    row.update(outcome="done", review_fix_min=round(rf, 2), t_a_min=round(t_a, 4), gates_pass=gates["pass"], model_score=gates["model_score"],
               silent_numbers=aud.silent, client_ready=cr, blocking="; ".join(blocking), persona_score=ps if ps is not None else "",
               edits=sum(int(e.get("count", 1)) for e in edits))
    tb = bl["tasks"].get(task)
    if not tb or "baseline" in tb:
        row["baseline"] = baselines.NO_BASELINE
    else:
        row["baseline"] = "estimate"
        for k in ("low", "mid", "high"):
            th = tb[f"t_h_{k}"]
            row[f"t_h_{k}_min"] = th
            row[f"saved_{k}"] = round(1 - t_a / th, 4)
    if b.get("fixed_wsp"):
        row["_wsp"] = {"circularity": circularity_check(run), "model_score": gates["model_score"], "wall_min": row["wall_min"], "gates": gates["gates"]}
    row["_persona_label"] = pe.get("label", "")
    return row


# --------------------------------------------------------------------------- aggregation
def aggregate(rows: list[dict], bl: dict, briefs: list[dict], tasks: tuple[str, ...]) -> list[dict]:
    out = []
    for t in tasks:
        tb = bl["tasks"].get(t, {})
        all_b = [b for b in briefs if b["task_id"] == t]
        mine = [r for r in rows if r["task_id"] == t and not r["brief_id"].startswith("wsp-")]
        done = [r for r in mine if r["outcome"] == "done"]
        blocked = [r for r in mine if r["outcome"] == "blocked"]
        failed = [r for r in mine if r["outcome"] == "failed"]
        a = {"task_id": t, "briefs_total": len(all_b), "skipped_needs_live": sum(1 for b in all_b if b["data"] == "needs_live"),
             "n_runs": len(mine), "n_done": len(done), "n_blocked": len(blocked), "n_failed": len(failed),
             "n_companies": len({r["ticker"] or r["brief_id"] for r in done}), "baseline_row": tb.get("row"), "confidence": tb.get("confidence"),
             "baseline": "own timing study needed" if (not tb or "baseline" in tb) else "estimate"}
        if blocked and not done:
            a["blocked_reason"] = blocked[0]["blocked_reason"]
        if done:
            ta = [float(r["t_a_min"]) for r in done]
            a["wall_min_median"] = median([float(r["wall_min"]) for r in done])
            a["review_fix_min_median"] = median([float(r["review_fix_min"]) for r in done])
            a["t_a_median"] = median(ta)
            a["t_a_q1"], a["t_a_q3"] = iqr(ta)
            if a["baseline"] == "estimate":
                a["t_h"] = (tb["t_h_low"], tb["t_h_mid"], tb["t_h_high"])
                for k in ("low", "mid", "high"):
                    v = [float(r[f"saved_{k}"]) for r in done]
                    a[f"saved_{k}_median"] = median(v)
                    if k == "mid":
                        a["saved_mid_q1"], a["saved_mid_q3"] = iqr(v)
            bad = [r for r in done if (r["gates_pass"] is False) or (r["silent_numbers"] or 0) > 0]
            a["error_rate"] = round((len(bad) + len(failed)) / max(1, len(done) + len(failed)), 4)
            a["client_ready_yes"] = sum(1 for r in done if r["client_ready"] == "yes")
            a["client_ready_unknown"] = sum(1 for r in done if r["client_ready"] == "unknown")
            a["client_ready_no"] = sum(1 for r in done if r["client_ready"] == "no")
        out.append(a)
    return out


# --------------------------------------------------------------------------- report
def pc(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def write_report(path: Path, agg: list[dict], rows: list[dict], bl: dict, mode: str, args_note: str, wsp: dict | None, started: str, total_s: float):
    claims = bl["competitor_claims"]
    L = []
    L += ["# Time-saved benchmark (TSB), first replay report", "",
          f"Generated {started} by `eval/tsb/run.py` in **{mode}** mode ({args_note}); harness wall time {total_s:.0f}s. All rows: `status = estimate`. "
          "**Human-validated rows: 0.** Nothing in this file may be quoted as a measured customer result.", "",
          "## How to read this", "",
          "- `T_a` = job wall time (instrumented from the job telemetry) + review-and-fix minutes. Review-and-fix = sum over persona \"edits needed\" x "
          "`eval/tsb/edit_minutes.csv`. **In replay the edit lists are canned placeholders** (`tests/fixtures/eval/persona_edits/`), hand-calibrated to the "
          "catalogue's own `review_minutes_estimate`; they are not persona output. So the replay figure is the product's own review estimate "
          "restated, not independent evidence. Every minutes-per-edit value is `[INFERENCE]` (no published table was found).",
          "- Wall time in replay excludes model latency: engines run on fixtures and prose steps are canned replies. Live runs will be slower for the three prose tasks.",
          "- `T_h` comes from `docs/time-saved-baselines.md` section 2 via `eval/tsb/baselines.py`: low/mid/high = the sourced range's ends and geometric mean. "
          "Savings = `1 - T_a/T_h`. With a low `T_h` the saving shrinks, so `low` is the conservative column.",
          "- **Speed, error rate and client-ready rate are separate columns and are never blended.** Error rate = share of runs that failed, failed a deterministic gate or left an "
          "unsourced/unflagged number. Client-ready = deterministic gates pass AND no blocking edit AND no silent number; the persona component (>= 8.5) was **not run**, so passing rows read "
          "`unknown`, not `yes`.",
          "- `n` counts runs. Offline data is one real company (AAPL) plus labelled synthetic fixtures, so `n_companies` is at most 4 and **no task reaches the n >= 10 independent briefs the claim rule needs**. "
          "Briefs that need live data or a live model are listed as skipped, not simulated.", ""]
    L += ["## Per-task results (estimate)", "",
          "| Task | n runs | n cos | skipped (needs live) | T_h (min, low/mid/high) | median T_a (min) | wall / review (min) | saved low | saved mid (IQR) | saved high | error rate | client-ready yes/unknown/no |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in agg:
        if a["n_done"] == 0:
            reason = a.get("blocked_reason") or "no runnable briefs offline"
            L.append(f"| {a['task_id']} | {a['n_runs']} | 0 | {a['skipped_needs_live']} | - | **blocked: {reason}** | - | - | - | - | - | - |")
            continue
        th = ("baseline: own timing study needed" if a["baseline"] != "estimate" else "/".join(f"{x:.0f}" for x in a["t_h"]))
        if a["baseline"] == "estimate":
            sv = (pc(a["saved_low_median"]), f"{pc(a['saved_mid_median'])} ({pc(a['saved_mid_q1'])} to {pc(a['saved_mid_q3'])})", pc(a["saved_high_median"]))
        else:
            sv = ("n/a", "n/a", "n/a")
        L.append(f"| {a['task_id']} | {a['n_done']} | {a['n_companies']} | {a['skipped_needs_live']} | {th} | {a['t_a_median']:.1f} | "
                 f"{a['wall_min_median']:.2f} / {a['review_fix_min_median']:.0f} | {sv[0]} | {sv[1]} | {sv[2]} | {pc(a['error_rate'])} | "
                 f"{a['client_ready_yes']}/{a['client_ready_unknown']}/{a['client_ready_no']} |")
    L += ["", "Tasks with `baseline: own timing study needed` have no credible published human time (baselines doc section 2); no saving is computed for them.", ""]
    L += ["## Competitor claims beside each task (labels as in the baselines doc)", "",
          "Not directly comparable: different tasks, no audited method, mostly [vendor]. We claim nothing against them until a human-validated figure exists.", "",
          "| Task | Who | Claim | Type | Method |", "|---|---|---|---|---|"]
    for a in agg:
        t = a["task_id"]
        for c in claims:
            if any(c["who"].startswith(w) for w in CLAIM_MAP.get(t, ())):
                L.append(f"| {t} | {c['who']} | {c['claim'][:170]} | {c['type']} | {c['method'][:50]} |")
    L += ["", "General headline claims (not task-specific):", ""]
    for c in claims:
        if any(c["who"].startswith(w) for w in GENERAL_CLAIMS):
            L.append(f"- **{c['who']}** [{c['type']}]: {c['claim'][:200]} ({c['method']})")
    L += [""]
    L += ["## Fixed row: WSP Apple 3-statement", ""]
    if wsp:
        circ = wsp["circularity"]
        L += ["Same task as the [independent] Wall Street Prep ranking (baselines doc section 1), run through our `three_statement` agent on the AAPL fixture. The prompt is a paraphrase "
              "(WSP's exact prompt was not available offline [UNKNOWN]); the AAPL data is a fixture, not a fresh 10-K pull.", "",
              "| Measure | Acretia (replay, fixture data) | Independent bar (WSP) |", "|---|---|---|",
              f"| Wall time | {wsp['wall_min'] * 60:.1f} s ({wsp['wall_min']:.3f} min); no model latency in replay | tools 15-60 min; analysts 1-3 hrs |",
              f"| Deterministic model grade (`om.modelcheck`) | {fmt(wsp['model_score'], 1)}/100 | tools 2.5-5.9 /10; analysts 6.4-9.4 /10 (human rubric, not the same scale) |",
              f"| Interest circularity modelled and converging | **{'PASS' if circ['pass'] else 'FAIL'}** (converged={circ['converged']}, iterations={circ['iterations']}, "
              f"iterative calc on={circ['iterative_calc_enabled']}, switch on={circ['switch_on']}) | every tool scored 0 |", "",
              "The model-check score and the WSP 0-10 rubric are different instruments; only the circularity pass/fail is a like-for-like observation, and even that is one run on a fixture. "
              "It is not a claim of beating WSP's analysts."]
    else:
        L += ["Not run in this invocation (`wsp-apple-3stmt` brief not selected)."]
    L += ["", "## Skipped and blocked (honest gaps)", ""]
    for a in agg:
        if a["n_done"] == 0:
            L.append(f"- **{a['task_id']}**: blocked or no runnable brief. {a.get('blocked_reason', '')}")
        elif a["n_blocked"] or a["n_failed"]:
            L.append(f"- {a['task_id']}: {a['n_blocked']} blocked, {a['n_failed']} failed of {a['n_runs']} runs.")
    skipped = sum(a["skipped_needs_live"] for a in agg)
    L += [f"- {skipped} briefs across all tasks need live SEC data, user documents or a live model (US, IFRS and MENA companies outside the four fixtures); they run only through the user's Mac (D-021).", ""]
    L += ["## Next steps to turn estimates into claims", "",
          "1. Run `--live` on the user's Mac with persona edit lists from real Haiku personas (replace the canned fixtures).",
          "2. Run the paired-timing pilot in `eval/tsb/pilot.md` with 3-5 analysts; replace `T_h` and the minutes-per-edit table with measured values.",
          "3. Only then label rows `human-validated`, and only quote a figure at or above the published competitor claim for that task.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_COLS})


# --------------------------------------------------------------------------- main
def run_all(tasks=None, n=None, out_dir: Path = HERE, mode: str = "replay", per_task_brief_ids: dict | None = None, write: bool = True,
            live_hook=None, only_ids: list[str] | None = None) -> dict:
    briefs = load_briefs()
    bl = baselines.load()
    minutes = load_edit_minutes()
    tasks = tuple(tasks or TASK_ORDER)
    rows: list[dict] = []
    t_start = time.perf_counter()
    with Harness(llm_mode=mode) as h:
        sel = []
        for t in tasks:
            bs = [b for b in briefs if b["task_id"] == t and not b.get("fixed_wsp")]
            runnable = [b for b in bs if (b["data"] != "needs_live" or mode == "live")]
            if n:
                runnable = runnable[:n]
            sel += runnable
        wsp_b = [b for b in briefs if b.get("fixed_wsp") and (tasks is None or b["task_id"] in tasks)]
        if only_ids:
            sel = [b for b in sel if b["id"] in only_ids]
        for b in wsp_b + sel:
            rows.append(run_brief(h, b, bl, minutes, live_hook))
    agg = aggregate(rows, bl, briefs, tasks)
    wsp = next((r["_wsp"] for r in rows if "_wsp" in r), None)
    result = {"rows": rows, "agg": agg, "wsp": wsp}
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        note = f"tasks={','.join(tasks)}; n cap={n or 'all runnable'}"
        write_report(out_dir / "report.md", agg, rows, bl, mode, note, wsp, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), time.perf_counter() - t_start)
        write_csv(out_dir / "results.csv", rows)
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--replay", action="store_true", help="default: fixtures only, no network")
    g.add_argument("--live", action="store_true", help="live model; refuses without ACRETIA_LLM_MODE=live and ACRETIA_LLM_API_KEY")
    ap.add_argument("--tasks", help="comma-separated task_ids (default: all 14)")
    ap.add_argument("--n", type=int, help="cap briefs per task")
    ap.add_argument("--out", help="output directory (default eval/tsb)")
    a = ap.parse_args(argv)
    mode = "live" if a.live else "replay"
    if mode == "live":
        if os.environ.get("ACRETIA_LLM_MODE") != "live" or not os.environ.get("ACRETIA_LLM_API_KEY"):
            print("refusing to run live: set ACRETIA_LLM_MODE=live and the adapter env (ACRETIA_LLM_API_KEY, optionally ACRETIA_LLM_BASE_URL / "
                  "ACRETIA_LLM_MODEL) on the machine that holds the key (D-021). Replay mode needs none of this.", file=sys.stderr)
            return 2
    tasks = [t.strip() for t in a.tasks.split(",")] if a.tasks else None
    if tasks:
        bad = [t for t in tasks if t not in TASK_ORDER]
        if bad:
            print(f"unknown task_id(s): {', '.join(bad)}; valid: {', '.join(TASK_ORDER)}", file=sys.stderr)
            return 2
    res = run_all(tasks, a.n, Path(a.out) if a.out else HERE, mode)
    for ag in res["agg"]:
        if ag["n_done"]:
            s = f"saved mid {pc(ag.get('saved_mid_median'))}" if ag["baseline"] == "estimate" else "baseline: own timing study needed"
            print(f"{ag['task_id']:<18} n={ag['n_done']:<3} T_a={ag['t_a_median']:.1f} min  {s}")
        else:
            print(f"{ag['task_id']:<18} blocked: {ag.get('blocked_reason', 'no runnable brief offline')}")
    print(f"wrote {Path(a.out) if a.out else HERE}/report.md and results.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
