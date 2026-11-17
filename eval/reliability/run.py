#!/usr/bin/env python3
"""Reliability runner (SPEC section 11, PLAN "North-star metrics" 2, D-032).

    python3 eval/reliability/run.py --replay --n 100          # offline; fixtures only
    python3 eval/reliability/run.py --replay --n 10 --out /tmp/rel

Each runnable brief in `corpus.json` runs as an in-process job (temp data dir, seeded demo org, approvals auto-approved), then:
  1. success: job done and a deliverable of the expected kind exists (blocked engines and replay-impossible briefs are reported apart);
  2. silent wrong numbers: every hard-coded workbook number, deck/memo figure and finding must carry a citation/xbrl concept or an explicit flag;
     citation tokens must resolve; DCF overrides must show up in the workbook;
  3. determinism: the brief runs a second time and every xlsx cell (formula and value), pptx text, docx text and json value must match;
  4. resume: a one-shot exception is injected into the last engine step before `deliver`, the job is resumed, finished steps must not re-run,
     and the result must equal the clean run;
  5. latency (wall seconds of the clean run) and cost per deliverable (replay: priced fixture usage, not a bill).
Writes report.md and results.csv.  No live model calls, no sockets.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.reliability import (INPUT_BLUE, Harness, audit_run, override_cells, deliverables_identical, fmt, gate_result, median, pct)  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = {"success": 0.97, "silent": 0, "determinism": 1.0, "resume": 1.0}
CSV_COLS = ["brief_id", "task_id", "perturbation", "ticker", "region", "data", "lang", "outcome", "success", "kinds", "wall_seconds", "elapsed_seconds",
            "tokens", "cost_usd", "numbers_checked", "numbers_sourced", "numbers_flagged", "silent_numbers", "override_ok", "gates_pass", "model_score",
            "deterministic", "determinism_diffs", "resume_tested", "resume_ok", "resume_detail", "notes"]


def load_corpus(path: Path = HERE / "corpus.json") -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["briefs"]


def pick(briefs: list[dict], n: int | None) -> list[dict]:
    """n briefs spread evenly over the runnable list (deterministic), so a reduced set still covers tasks and perturbations."""
    if not n or n >= len(briefs):
        return briefs
    idx = sorted({int(i * len(briefs) / n) for i in range(n)})
    return [briefs[i] for i in idx]


def _classify(b: dict, run) -> str:
    if run.done:
        return "done"
    if run.blocked:
        return "blocked"
    if b.get("expect") == "unsupported_by_rule_planner":
        return "unsupported"
    return "failed"


def _override_ok(b: dict, run) -> bool | None:
    exp = b.get("expect_facts")
    if not exp:
        return None
    facts = run.step_output("build_dcf").get("facts") or {}
    return all(abs(float(facts.get(k, -1)) - v) < 1e-9 for k, v in exp.items())


def test_resume(h: Harness, b: dict, clean) -> dict:
    """Inject a one-shot failure into the last engine step before `deliver`, resume, and compare with the clean run."""
    fns = [s["fn"] for s in clean.steps]
    if "deliver" in fns:
        fns = fns[:fns.index("deliver")]
    if not fns:
        return {"tested": False, "ok": None, "detail": "no steps to fail"}
    target = fns[-1]
    earlier = [f for f in fns[:-1] if f in h.engines.STEP_FNS]
    calls_inj, restore_inj = h.inject_failure(target)
    calls_cnt, restore_cnt = h.count_calls(earlier)
    try:
        failed = h.run(b["prompt"], deal=b.get("deal"))
        if failed.status != "failed":
            return {"tested": True, "ok": False, "detail": f"injected failure in '{target}' did not fail the job (status {failed.status})"}
        pre = dict(calls_cnt)
        resumed = h.resume(failed)
    except Exception as e:                                  # noqa: BLE001
        return {"tested": True, "ok": False, "detail": f"resume raised {type(e).__name__}: {e}"}
    finally:
        restore_cnt()
        restore_inj()
    if resumed.status != "done":
        return {"tested": True, "ok": False, "detail": f"resume ended {resumed.status}: {resumed.error}"}
    reran = [f for f in earlier if calls_cnt[f] != pre[f]]       # no earlier step may run again during the resume
    same, k, notes = deliverables_identical(clean, resumed)
    n_del = len(resumed.deliverables)
    ok = same and not reran and n_del == len(clean.deliverables)
    detail = f"failed at '{target}', resumed; " + ("identical to clean run" if same else f"DIFFERS from clean run ({'; '.join(notes)})")
    if reran:
        detail += f"; steps re-run after resume: {reran}"
    if n_del != len(clean.deliverables):
        detail += f"; deliverable events {n_del} vs {len(clean.deliverables)}"
    return {"tested": True, "ok": ok, "detail": detail}


def run_one(h: Harness, b: dict, do_resume: bool = True, do_determinism: bool = True) -> dict:
    row = {k: "" for k in CSV_COLS}
    row.update(brief_id=b["id"], task_id=b["task_id"], perturbation=b.get("perturbation", ""), ticker=b.get("ticker") or "", region=b.get("region", ""),
               data=b["data"], lang=b.get("lang", "en"))
    run = h.run(b["prompt"], deal=b.get("deal"))
    oc = _classify(b, run)
    row.update(outcome=oc, wall_seconds=round(run.wall_seconds, 4), elapsed_seconds=round(run.elapsed_seconds, 4), tokens=run.tokens, cost_usd=run.cost_usd)
    if oc != "done":
        row.update(success=False, notes=((run.hint or run.error or "")[:160]).replace("\n", " "), kinds="")
        row["_hint"] = run.hint or run.error or ""
        return row
    kinds = sorted({d["kind"] for d in run.deliverables})
    exp = b.get("expect_output")
    success = bool(run.deliverables) and (exp in kinds if exp else True)
    aud = audit_run(h, run)
    gates = gate_result(run)
    ov = _override_ok(b, run)
    silent = aud.silent + (1 if ov is False else 0)
    row.update(success=success, kinds="+".join(kinds), numbers_checked=aud.total, numbers_sourced=aud.sourced, numbers_flagged=aud.flagged,
               silent_numbers=silent, override_ok=ov if ov is not None else "", gates_pass=gates["pass"], model_score=gates["model_score"] or "")
    unstyled = 0
    oc_cells = override_cells(run)
    if oc_cells:
        from om import xlsx
        for d in run.deliverables:
            if d["kind"] == "xlsx":
                bk = xlsx.read(d["data"])
                for ref in oc_cells:
                    sh, cell = ref.split("!")
                    rc = xlsx.split_ref(cell)
                    c = bk.sheets.get(sh, {}).get(rc)
                    if c is not None and c.color != INPUT_BLUE:
                        unstyled += 1
    row["_override_unstyled"] = unstyled
    row["_override_cells"] = len(oc_cells)
    row["_audit_examples"] = aud.examples + (["DCF override was not applied to the workbook"] if ov is False else [])
    row["_gate_blocking"] = gates["blocking"]
    row["_cost"] = run.cost_usd
    row["_deliverables"] = len(run.deliverables)
    if do_determinism:
        r2 = h.run(b["prompt"], deal=b.get("deal"))
        if r2.done:
            same, k, notes = deliverables_identical(run, r2)
            row.update(deterministic=same, determinism_diffs=k)
            if not same:
                row["notes"] = "; ".join(notes)[:200]
        else:
            row.update(deterministic=False, determinism_diffs=-1, notes=f"second run ended {r2.status}")
    if do_resume:
        rs = test_resume(h, b, run)
        row.update(resume_tested=rs["tested"], resume_ok=rs["ok"] if rs["ok"] is not None else "", resume_detail=rs["detail"])
    return row


def summarise(rows: list[dict]) -> dict:
    ran = [r for r in rows if r["outcome"] in ("done", "failed")]
    done = [r for r in rows if r["outcome"] == "done"]
    ok = [r for r in done if r["success"] is True]
    blocked = [r for r in rows if r["outcome"] == "blocked"]
    unsup = [r for r in rows if r["outcome"] == "unsupported"]
    det = [r for r in done if r["deterministic"] != ""]
    res = [r for r in done if r["resume_tested"] is True]
    lat = [float(r["wall_seconds"]) for r in done]
    el = [float(r["elapsed_seconds"]) for r in done]
    s = {"n_briefs_run": len(rows), "n_supported_run": len(ran), "n_done": len(done), "n_success": len(ok), "n_blocked": len(blocked), "n_unsupported": len(unsup),
         "success_rate": (len(ok) / len(ran)) if ran else None,
         "success_rate_incl_blocked": (len(ok) / (len(ran) + len(blocked))) if (ran or blocked) else None,
         "silent": sum(int(r["silent_numbers"] or 0) for r in done),
         "numbers_checked": sum(int(r["numbers_checked"] or 0) for r in done), "numbers_sourced": sum(int(r["numbers_sourced"] or 0) for r in done),
         "numbers_flagged": sum(int(r["numbers_flagged"] or 0) for r in done),
         "n_det": len(det), "n_det_ok": sum(1 for r in det if r["deterministic"] is True),
         "n_resume": len(res), "n_resume_ok": sum(1 for r in res if r["resume_ok"] is True),
         "p50": median(lat), "p95": pct(lat, 95), "max": max(lat) if lat else None, "p50_elapsed": median(el), "p95_elapsed": pct(el, 95),
         "tokens": sum(int(r["tokens"] or 0) for r in done), "cost": sum(float(r["cost_usd"] or 0) for r in done),
         "n_deliverables": sum(r.get("_deliverables", 0) for r in done),
         "gate_fail": [r for r in done if r["gates_pass"] is False]}
    s["determinism"] = (s["n_det_ok"] / s["n_det"]) if s["n_det"] else None
    s["resume_rate"] = (s["n_resume_ok"] / s["n_resume"]) if s["n_resume"] else None
    return s


def table(rows: list[dict], key: str) -> list[str]:
    g = defaultdict(list)
    for r in rows:
        g[r[key] or "-"].append(r)
    L = [f"| {key} | briefs | done | success | blocked/unsupported | silent numbers | deterministic | resume ok | p50 s | p95 s |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(g):
        rs = g[k]
        d = [r for r in rs if r["outcome"] == "done"]
        lat = [float(r["wall_seconds"]) for r in d]
        det = [r for r in d if r["deterministic"] != ""]
        res = [r for r in d if r["resume_tested"] is True]
        L.append(f"| {k} | {len(rs)} | {len(d)} | {sum(1 for r in d if r['success'] is True)}/{len([r for r in rs if r['outcome'] in ('done', 'failed')])} | "
                 f"{sum(1 for r in rs if r['outcome'] in ('blocked', 'unsupported'))} | {sum(int(r['silent_numbers'] or 0) for r in d)} | "
                 f"{sum(1 for r in det if r['deterministic'] is True)}/{len(det)} | {sum(1 for r in res if r['resume_ok'] is True)}/{len(res)} | "
                 f"{fmt(median(lat), 2)} | {fmt(pct(lat, 95), 2)} |")
    return L


def write_report(path: Path, rows: list[dict], s: dict, corpus: list[dict], mode: str, started: str, total_s: float, partial_note: str):
    pc = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"      # noqa: E731
    skipped = [b for b in corpus if b["data"] == "needs_live"]
    L = ["# Reliability report, first replay run", "",
         f"Generated {started} by `eval/reliability/run.py` in **{mode}** mode; harness wall time {total_s:.0f}s. {partial_note}", "",
         "Everything below is from fixtures: one real company (AAPL), three labelled synthetic companies (DEMOA, DEMOB, DEMOT) and two seeded synthetic deals. "
         "It tests the product's plumbing and number discipline on offline data. It says **nothing** yet about live-data reliability, MENA/IFRS filings or live model "
         "drafting; those briefs are in the corpus and are skipped here (listed at the end).", "",
         "## Headline versus SLO targets (PLAN North-star metrics 2)", "",
         "| SLO | Target | Measured (replay) | Verdict |", "|---|---|---|---|"]
    sr = s["success_rate"]
    L.append(f"| Task success (done + expected deliverable) | >= 97% | {pc(sr)} ({s['n_success']}/{s['n_supported_run']} supported briefs run); incl. engine-blocked: {pc(s['success_rate_incl_blocked'])} | "
             f"{'MET' if sr is not None and sr >= TARGETS['success'] else 'NOT MET'} |")
    L.append(f"| Silent wrong numbers | 0 | **{s['silent']}** of {s['numbers_checked']} numbers checked ({s['numbers_sourced']} sourced, {s['numbers_flagged']} flagged) | {'MET' if s['silent'] == 0 else 'NOT MET'} |")
    L.append(f"| Determinism (two runs, identical numbers) | 100% | {pc(s['determinism'])} ({s['n_det_ok']}/{s['n_det']}) | {'MET' if s['determinism'] == 1.0 else 'NOT MET'} |")
    L.append(f"| Failed jobs resume cleanly | 100% | {pc(s['resume_rate'])} ({s['n_resume_ok']}/{s['n_resume']}) | {'MET' if s['resume_rate'] == 1.0 else 'NOT MET'} |")
    L.append(f"| p95 latency (job wall seconds, replay) | published | p50 {fmt(s['p50'], 2)} s, p95 {fmt(s['p95'], 2)} s, max {fmt(s['max'], 2)} s | published; no live-model latency included |")
    prose = [r for r in rows if r["outcome"] == "done" and float(r["cost_usd"] or 0) > 0]
    pd = sum(r.get("_deliverables", 0) for r in prose)
    L.append(f"| Cost per deliverable | published | **not a live measurement.** Replay books the recorded token usage of the canned fixtures at ledger rates: "
             f"${s['cost']:.4f} over {s['n_deliverables']} deliverables = ${s['cost'] / max(1, s['n_deliverables']):.4f} each on average; the {len(prose)} prose runs "
             f"({s['tokens']} replayed tokens) account for all of it (about ${sum(float(r['cost_usd']) for r in prose) / max(1, pd):.4f} per prose deliverable); engine-only deliverables cost $0.00 | not measured |")
    L += ["", f"Briefs run: {s['n_briefs_run']} of {len(corpus)} in the corpus ({len(skipped)} need live data/model and are skipped). Supported briefs run: {s['n_supported_run']}; "
          f"engine blocked: {s['n_blocked']}; Arabic-only probes (planner has no Arabic rules): {s['n_unsupported']}.", ""]
    L += ["## What each check does", "",
          "- **Success:** job reaches `done` and produces a deliverable of the catalogue's output kind. Briefs blocked by a missing engine (`precedents`) and Arabic-only probes are "
          "excluded from the main denominator and reported on their own line, never as a pass.",
          "- **Silent wrong numbers:** workbook hard-coded numbers (cell comment or link = sourced; blue input-cell convention = flagged assumption; a constant in an actual-period "
          "time-series column or on a filings sheet without a comment/link, or a non-blue constant = silent), deck figures (a slide with figures needs a `Source:` line naming the filing or date, or an "
          "explicit flag), memo figures (a source line or the canned-text flag), VDR findings (doc id + page), citation tokens (must resolve in the citation store) and, for DCF override briefs, "
          "the requested WACC / terminal growth must be in the built workbook. It does **not** re-derive numbers from the filings; it checks that each has a tie or a flag.",
          "- **Determinism:** every brief is run twice in fresh jobs. xlsx compared cell by cell (formula and value), pptx slide text, docx text, json values.",
          "- **Resume:** a one-shot exception is injected into the last engine step before `deliver` (monkeypatched step function; the job service has no built-in hook). The job is resumed; "
          "earlier steps must not re-run and the result must equal the clean run.", ""]
    L += ["## By task", ""] + table(rows, "task_id") + ["", "## By perturbation", ""] + table(rows, "perturbation") + ["", "## By data kind and region", ""] + table(rows, "data") + [""] + table(rows, "region") + [""]
    # failures and findings
    fails = [r for r in rows if r["outcome"] == "failed"]
    L += ["## Failures", ""]
    if not fails:
        L.append("None among supported briefs.")
    for r in fails:
        L.append(f"- `{r['brief_id']}` ({r['task_id']}, {r['perturbation']}): {r['notes']}")
    blk = Counter((r["task_id"], r["notes"][:140]) for r in rows if r["outcome"] == "blocked")
    L += ["", "## Blocked (engine has not landed)", ""]
    L += [f"- `{t}` x{n}: {h}" for (t, h), n in blk.items()] or ["None."]
    uns = [r for r in rows if r["outcome"] == "unsupported"]
    L += ["", "## Arabic prompt text", ""]
    am = [r for r in rows if r["perturbation"] == "arabic_mixed"]
    L += [f"- Arabic text with English task keywords: {sum(1 for r in am if r['outcome'] == 'done')}/{len(am)} planned and ran.",
          f"- Arabic-only prompts: {sum(1 for r in uns)} of {len([r for r in rows if r['perturbation'] == 'arabic_only'])} failed gracefully with a hint (rule-first planner has no Arabic rules; "
          "the adapter planner path needs a live or recorded model). This is a **product gap for MENA users**, not a harness issue."]
    for r in uns[:4]:
        L.append(f"  - `{r['brief_id']}`: hint = {r['notes']}")
    sil = [r for r in rows if r["outcome"] == "done" and int(r["silent_numbers"] or 0) > 0]
    L += ["", "## Silent numbers found", ""]
    if not sil:
        L.append("None. Every number checked carried a source or a flag.")
    for r in sil[:15]:
        L.append(f"- `{r['brief_id']}` ({r['task_id']}): {r['silent_numbers']} unflagged/unsourced; first: {r.get('_audit_examples', [''])[:2]}")
    nd = [r for r in rows if r["outcome"] == "done" and r["deterministic"] is False]
    L += ["", "## Determinism differences", ""]
    L += [f"- `{r['brief_id']}` ({r['task_id']}): {r['determinism_diffs']} differing items. {r['notes']}" for r in nd[:15]] or ["None. Every re-run matched cell for cell / text for text."]
    nr = [r for r in rows if r["outcome"] == "done" and r["resume_tested"] is True and r["resume_ok"] is not True]
    L += ["", "## Resume failures", ""]
    L += [f"- `{r['brief_id']}` ({r['task_id']}): {r['resume_detail']}" for r in nr[:15]] or ["None. Every injected failure resumed to a result identical to the clean run, without re-running finished steps."]
    uo = sum(r.get("_override_unstyled", 0) for r in rows if r["outcome"] == "done")
    n_ov = sum(1 for r in rows if r["outcome"] == "done" and r.get("_override_cells"))
    L += ["", "## Product observations from this run (not fixed here)", "",
          f"- **Override cells lose the input styling.** In {sum(1 for r in rows if r['outcome'] == 'done' and r.get('_override_unstyled'))} of {n_ov} runs that applied a WACC / growth override from the prompt, the overridden cell is a plain "
          f"constant that is not blue and has no comment, so the workbook alone does not show it is a user override. The job's step note does disclose it (\"Overrides applied: ...\"), "
          f"so the number is counted as flagged here, but a reader who only opens the xlsx sees an unmarked hard-code ({uo} cells)."]
    gf = s["gate_fail"]
    L += ["", "## Deterministic gate observations (not counted in success)", ""]
    if gf:
        by = Counter((r["task_id"], r["ticker"]) for r in gf)
        L.append(f"`om.modelcheck` did not mark {len(gf)} delivered workbook(s) production-ready. By (task, ticker): " + "; ".join(f"{t}/{k} x{n}" for (t, k), n in sorted(by.items())) + ".")
    else:
        L.append("All delivered workbooks and decks passed their deterministic gates.")
    L += ["", "## Corpus coverage and honesty", "",
          f"- Corpus: {len(corpus)} briefs; data kinds: " + ", ".join(f"{k} {v}" for k, v in Counter(b['data'] for b in corpus).items()) + ".",
          f"- Distinct companies offline: {len({b['ticker'] for b in corpus if b['ticker'] and b['data'] != 'needs_live'})} tickers (AAPL real; DEMOA/B/T synthetic) plus 2 synthetic deals. "
          "Runs of the same company under different phrasing are not independent samples.",
          "- US-GAAP only offline. IFRS and MENA companies (MSFT, NVDA, SWDY, SAP in the corpus) need live data and are skipped; the MENA coverage here is the synthetic Nile data room (EN+AR documents).",
          "- Prose deliverables (IC memo, recap, buyer list) are canned replay text for AAPL only and are flagged `REPLAY FIXTURE`; they pass the number check by that flag, not by being right.",
          "- Latency excludes model time. Cost is the priced replayed usage of canned fixtures, not a bill; live cost per deliverable has not been measured.", "", "### Skipped (need live)", ""]
    L += [f"- `{b['id']}` {b['task_id']} {b['ticker']} ({b['region']})" for b in skipped]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CSV_COLS})


def run_all(n: int | None = None, out_dir: Path = HERE, mode: str = "replay", write: bool = True, corpus_path: Path | None = None,
            progress=None, budget_s: float | None = None) -> dict:
    corpus = load_corpus(corpus_path or HERE / "corpus.json")
    runnable = [b for b in corpus if b["data"] != "needs_live" or mode == "live"]
    chosen = pick(runnable, n)
    t0 = time.perf_counter()
    rows = []
    stopped = ""
    with Harness(llm_mode=mode) as h:
        for i, b in enumerate(chosen, 1):
            if budget_s and time.perf_counter() - t0 > budget_s:
                stopped = f"Stopped after {i - 1} of {len(chosen)} briefs because the time budget ({budget_s:.0f}s) ran out."
                break
            rows.append(run_one(h, b))
            if progress:
                progress(i, len(chosen), rows[-1])
    s = summarise(rows)
    res = {"rows": rows, "summary": s, "corpus": corpus}
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        note = stopped or (f"Ran {len(rows)} briefs (`--n {n}`)." if n else f"Ran all {len(rows)} runnable briefs.")
        write_report(out_dir / "report.md", rows, s, corpus, mode, time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), time.perf_counter() - t0, note)
        write_csv(out_dir / "results.csv", rows)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--replay", action="store_true", help="fixtures only, no network (the only mode this runner supports)")
    ap.add_argument("--n", type=int, help="number of briefs to run (spread evenly over the corpus)")
    ap.add_argument("--out", help="output directory (default eval/reliability)")
    ap.add_argument("--budget-seconds", type=float, help="stop after this many seconds and say so in the report")
    a = ap.parse_args(argv)

    def prog(i, tot, r):
        if i % 10 == 0 or i == tot:
            print(f"[{i}/{tot}] {r['brief_id']} {r['task_id']} {r['outcome']}", flush=True)
    res = run_all(a.n, Path(a.out) if a.out else HERE, "replay", progress=prog, budget_s=a.budget_seconds)
    s = res["summary"]
    print(f"success {fmt(s['success_rate'], 4)}  silent {s['silent']}  determinism {fmt(s['determinism'], 4)}  resume {fmt(s['resume_rate'], 4)}  "
          f"p95 {fmt(s['p95'], 2)}s  blocked {s['n_blocked']}  unsupported {s['n_unsupported']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
