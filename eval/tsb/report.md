# Time-saved benchmark (TSB), first replay report

Generated 2026-11-17 09:22 UTC by `eval/tsb/run.py` in **replay** mode (tasks=comps,precedents,three_statement,dcf,lbo,merger,vdr_review,profile,pitchbook_section,teaser,ic_memo,earnings_update,earnings_recap,buyer_list; n cap=all runnable); harness wall time 23s. All rows: `status = estimate`. **Human-validated rows: 0.** Nothing in this file may be quoted as a measured customer result.

## How to read this

- `T_a` = job wall time (instrumented from the job telemetry) + review-and-fix minutes. Review-and-fix = sum over persona "edits needed" x `eval/tsb/edit_minutes.csv`. **In replay the edit lists are canned placeholders** (`tests/fixtures/eval/persona_edits/`), hand-calibrated to the catalogue's own `review_minutes_estimate`; they are not persona output. So the replay figure is the product's own review estimate restated, not independent evidence. Every minutes-per-edit value is `[INFERENCE]` (no published table was found).
- Wall time in replay excludes model latency: engines run on fixtures and prose steps are canned replies. Live runs will be slower for the three prose tasks.
- `T_h` comes from `docs/time-saved-baselines.md` section 2 via `eval/tsb/baselines.py`: low/mid/high = the sourced range's ends and geometric mean. Savings = `1 - T_a/T_h`. With a low `T_h` the saving shrinks, so `low` is the conservative column.
- **Speed, error rate and client-ready rate are separate columns and are never blended.** Error rate = share of runs that failed, failed a deterministic gate or left an unsourced/unflagged number. Client-ready = deterministic gates pass AND no blocking edit AND no silent number; the persona component (>= 8.5) was **not run**, so passing rows read `unknown`, not `yes`.
- `n` counts runs. Offline data is one real company (AAPL) plus labelled synthetic fixtures, so `n_companies` is at most 4 and **no task reaches the n >= 10 independent briefs the claim rule needs**. Briefs that need live data or a live model are listed as skipped, not simulated.

## Per-task results (estimate)

| Task | n runs | n cos | skipped (needs live) | T_h (min, low/mid/high) | median T_a (min) | wall / review (min) | saved low | saved mid (IQR) | saved high | error rate | client-ready yes/unknown/no |
|---|---|---|---|---|---|---|---|---|---|---|---|
| comps | 8 | 4 | 4 | 120/120/120 | 20.0 | 0.00 / 20 | 83% | 83% (83% to 83%) | 83% | 0% | 0/8/0 |
| precedents | 8 | 0 | 4 | - | **blocked: The S4 precedents engine hasn't landed yet (S4 precedents stage); this step cannot run until it does. The other steps in this run are unaffected.** | - | - | - | - | - | - |
| three_statement | 8 | 4 | 4 | 120/147/180 | 15.0 | 0.01 / 15 | 88% | 90% (90% to 90%) | 92% | 75% | 0/2/6 |
| dcf | 8 | 4 | 4 | 90/90/90 | 15.0 | 0.01 / 15 | 83% | 83% (83% to 83%) | 83% | 75% | 0/2/6 |
| lbo | 8 | 4 | 4 | 480/588/720 | 30.0 | 0.00 / 30 | 94% | 95% (95% to 95%) | 96% | 0% | 0/8/0 |
| merger | 8 | 4 | 4 | 30/42/60 | 30.0 | 0.00 / 30 | 0% | 29% (29% to 29%) | 50% | 0% | 0/8/0 |
| vdr_review | 4 | 4 | 6 | 1200/1470/1800 | 90.0 | 0.00 / 90 | 92% | 94% (94% to 94%) | 95% | 0% | 0/4/0 |
| profile | 8 | 4 | 4 | baseline: own timing study needed | 25.0 | 0.00 / 25 | n/a | n/a | n/a | 0% | 0/8/0 |
| pitchbook_section | 8 | 4 | 4 | baseline: own timing study needed | 35.0 | 0.00 / 35 | n/a | n/a | n/a | 0% | 0/8/0 |
| teaser | 8 | 4 | 4 | baseline: own timing study needed | 25.0 | 0.00 / 25 | n/a | n/a | n/a | 0% | 0/8/0 |
| ic_memo | 2 | 1 | 8 | 240/465/900 | 60.0 | 0.00 / 60 | 75% | 87% (87% to 87%) | 93% | 0% | 0/0/2 |
| earnings_update | 8 | 4 | 4 | 15/42/120 | 10.0 | 0.01 / 10 | 33% | 76% (76% to 76%) | 92% | 75% | 0/2/6 |
| earnings_recap | 2 | 1 | 8 | baseline: own timing study needed | 20.0 | 0.00 / 20 | n/a | n/a | n/a | 0% | 0/0/2 |
| buyer_list | 2 | 1 | 8 | baseline: own timing study needed | 40.0 | 0.00 / 40 | n/a | n/a | n/a | 0% | 0/0/2 |

Tasks with `baseline: own timing study needed` have no credible published human time (baselines doc section 2); no saving is computed for them.

## Competitor claims beside each task (labels as in the baselines doc)

Not directly comparable: different tasks, no audited method, mostly [vendor]. We claim nothing against them until a human-validated figure exists.

| Task | Who | Claim | Type | Method |
|---|---|---|---|---|
| three_statement | Daloopa | Model build: 2 days–1 week+ by hand vs 45–60 min; 50–70% saved | vendor | step estimates |
| three_statement | Wall Street Prep | Apple 3-statement model, scored /10: Shortcut 5.9, Claude 5.5, Copilot 4.4, ChatGPT 2.5, vs analysts 9.4 / 7.9 / 6.4; tools took 15–60 min, analysts 1–3 hrs; every tool s | independent | one task, first attempt |
| three_statement | Ankura | 5 tools built "structurally complete" models in 7–10 min; none production-ready | independent | single pass |
| three_statement | BankerToolBench (ICLR 2026) | 502 bankers rated 0% of a frontier model's outputs client-ready; the best model fails about half the rubric criteria; human time up to 21 hrs per task | independent | 502 bankers, 100+ criteria |
| dcf | Shortcut | Preferred over first-year McKinsey/Goldman analysts in 89.1% of 247 blind pairwise comparisons; humans had time caps (DCF 90 min, M&A 90, LBO 50) | vendor | blind grading, n=247 |
| lbo | Shortcut | Preferred over first-year McKinsey/Goldman analysts in 89.1% of 247 blind pairwise comparisons; humans had time caps (DCF 90 min, M&A 90, LBO 50) | vendor | blind grading, n=247 |
| merger | Shortcut | Preferred over first-year McKinsey/Goldman analysts in 89.1% of 247 blind pairwise comparisons; humans had time caps (DCF 90 min, M&A 90, LBO 50) | vendor | blind grading, n=247 |
| vdr_review | Rogo / Harbor View | 1–2 weeks saved per CIM | vendor | none |
| vdr_review | AlphaSense | Diligence information gathering 50–75% faster; a 6-hr task in 1 hr | customer | none |
| vdr_review | Brightwave | 3–5 associate hrs → under 30 min; data rooms to memos "in hours" | vendor | none |
| profile | Rogo / Baird | Top-10 power users save 5+ hrs/day; output is "85% of the way there" | vendor/customer | power-user subset, self-report |
| pitchbook_section | Rogo / Baird | Top-10 power users save 5+ hrs/day; output is "85% of the way there" | vendor/customer | power-user subset, self-report |
| teaser | Rogo / Harbor View | 1–2 weeks saved per CIM | vendor | none |
| ic_memo | Brightwave | 3–5 associate hrs → under 30 min; data rooms to memos "in hours" | vendor | none |
| earnings_update | Daloopa | 2 hrs saved per ticker per earnings update (elsewhere 15–45 min per model: inconsistent); >99% accuracy | vendor | none |
| earnings_recap | Daloopa | 2 hrs saved per ticker per earnings update (elsewhere 15–45 min per model: inconsistent); >99% accuracy | vendor | none |

General headline claims (not task-specific):

- **Rogo** [vendor]: Users save about 400 hrs/yr (about 10 hrs/week) (none stated)
- **Rogo / Baird** [vendor/customer]: Top-10 power users save 5+ hrs/day; output is "85% of the way there" (power-user subset, self-report)
- **Rogo / Harbor View** [vendor]: 1–2 weeks saved per CIM (none)
- **Hebbia** [vendor]: 5–10 hrs/week per user (Fortune 100 customer) (none)
- **Hebbia (OpenAI page)** [vendor]: Bankers 30–40 hrs per deal; PE 20–30 hrs per deal (none)
- **BankerToolBench (ICLR 2026)** [independent]: 502 bankers rated 0% of a frontier model's outputs client-ready; the best model fails about half the rubric criteria; human time up to 21 hrs per task (502 bankers, 100+ criteria)
- **Vals Finance Agent v2** [independent]: Best models about 58%; under strict scoring all below 46% (public leaderboard)

## Fixed row: WSP Apple 3-statement

Same task as the [independent] Wall Street Prep ranking (baselines doc section 1), run through our `three_statement` agent on the AAPL fixture. The prompt is a paraphrase (WSP's exact prompt was not available offline [UNKNOWN]); the AAPL data is a fixture, not a fresh 10-K pull.

| Measure | Acretia (replay, fixture data) | Independent bar (WSP) |
|---|---|---|
| Wall time | 0.4 s (0.007 min); no model latency in replay | tools 15-60 min; analysts 1-3 hrs |
| Deterministic model grade (`om.modelcheck`) | 100.0/100 | tools 2.5-5.9 /10; analysts 6.4-9.4 /10 (human rubric, not the same scale) |
| Interest circularity modelled and converging | **PASS** (converged=True, iterations=24, iterative calc on=True, switch on=True) | every tool scored 0 |

The model-check score and the WSP 0-10 rubric are different instruments; only the circularity pass/fail is a like-for-like observation, and even that is one run on a fixture. It is not a claim of beating WSP's analysts.

## Deterministic gate failures observed (counted in error rate, not hidden)

- `dcf` on synthetic fixtures x6: model check failed: checks
- `earnings_update` on synthetic fixtures x6: model check failed: checks
- `three_statement` on synthetic fixtures x6: model check failed: checks

Diagnosis (checked by opening the workbook): the failing `om.modelcheck` grader is `checks`; on the synthetic DEMO* fixtures the check "Diluted EPS = reported (within 2% or half a cent)" (Checks row 20) returns ERROR and the MASTER CHECK follows. AAPL passes 100/100. The cause is most likely the synthetic fixtures' reported EPS not matching their net income and share count [INFERENCE, not diagnosed further]. This is reported, not fixed, here.

## Skipped and blocked (honest gaps)

- **precedents**: blocked or no runnable brief. The S4 precedents engine hasn't landed yet (S4 precedents stage); this step cannot run until it does. The other steps in this run are unaffected.
- 70 briefs across all tasks need live SEC data, user documents or a live model (US, IFRS and MENA companies outside the four fixtures); they run only through the user's Mac (D-021).

## Next steps to turn estimates into claims

1. Run `--live` on the user's Mac with persona edit lists from real Haiku personas (replace the canned fixtures).
2. Run the paired-timing pilot in `eval/tsb/pilot.md` with 3-5 analysts; replace `T_h` and the minutes-per-edit table with measured values.
3. Only then label rows `human-validated`, and only quote a figure at or above the published competitor claim for that task.
