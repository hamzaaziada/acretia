# Reliability report, first replay run

Generated 2026-11-17 04:38 UTC by `eval/reliability/run.py` in **replay** mode; harness wall time 123s. Ran 126 briefs (`--n 130`).

Everything below is from fixtures: one real company (AAPL), three labelled synthetic companies (DEMOA, DEMOB, DEMOT) and two seeded synthetic deals. It tests the product's plumbing and number discipline on offline data. It says **nothing** yet about live-data reliability, MENA/IFRS filings or live model drafting; those briefs are in the corpus and are skipped here (listed at the end).

## Headline versus SLO targets (PLAN North-star metrics 2)

| SLO | Target | Measured (replay) | Verdict |
|---|---|---|---|
| Task success (done + expected deliverable) | >= 97% | 100.0% (118/118 supported briefs run); incl. engine-blocked: 96.7% | MET |
| Silent wrong numbers | 0 | **0** of 24241 numbers checked (15655 sourced, 8586 flagged) | MET |
| Determinism (two runs, identical numbers) | 100% | 100.0% (118/118) | MET |
| Failed jobs resume cleanly | 100% | 100.0% (118/118) | MET |
| p95 latency (job wall seconds, replay) | published | p50 0.22 s, p95 0.65 s, max 0.86 s | published; no live-model latency included |
| Cost per deliverable | published | **not a live measurement.** Replay books the recorded token usage of the canned fixtures at ledger rates: $0.0487 over 118 deliverables = $0.0004 each on average; the 7 prose runs (5600 replayed tokens) account for all of it (about $0.0070 per prose deliverable); engine-only deliverables cost $0.00 | not measured |

Briefs run: 126 of 142 in the corpus (16 need live data/model and are skipped). Supported briefs run: 118; engine blocked: 4; Arabic-only probes (planner has no Arabic rules): 4.

## What each check does

- **Success:** job reaches `done` and produces a deliverable of the catalogue's output kind. Briefs blocked by a missing engine (`precedents`) and Arabic-only probes are excluded from the main denominator and reported on their own line, never as a pass.
- **Silent wrong numbers:** workbook hard-coded numbers (cell comment or link = sourced; blue input-cell convention = flagged assumption; a constant in an actual-period time-series column or on a filings sheet without a comment/link, or a non-blue constant = silent), deck figures (a slide with figures needs a `Source:` line naming the filing or date, or an explicit flag), memo figures (a source line or the canned-text flag), VDR findings (doc id + page), citation tokens (must resolve in the citation store) and, for DCF override briefs, the requested WACC / terminal growth must be in the built workbook. It does **not** re-derive numbers from the filings; it checks that each has a tie or a flag.
- **Determinism:** every brief is run twice in fresh jobs. xlsx compared cell by cell (formula and value), pptx slide text, docx text, json values.
- **Resume:** a one-shot exception is injected into the last engine step before `deliver` (monkeypatched step function; the job service has no built-in hook). The job is resumed; earlier steps must not re-run and the result must equal the clean run.

## By task

| task_id | briefs | done | success | blocked/unsupported | silent numbers | deterministic | resume ok | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| buyer_list | 2 | 2 | 2/2 | 0 | 0 | 2/2 | 2/2 | 0.03 | 0.03 |
| comps | 12 | 11 | 11/11 | 1 | 0 | 11/11 | 11/11 | 0.10 | 0.17 |
| dcf | 30 | 29 | 29/29 | 1 | 0 | 29/29 | 29/29 | 0.51 | 0.69 |
| earnings_recap | 2 | 2 | 2/2 | 0 | 0 | 2/2 | 2/2 | 0.03 | 0.03 |
| earnings_update | 8 | 8 | 8/8 | 0 | 0 | 8/8 | 8/8 | 0.61 | 0.84 |
| ic_memo | 3 | 3 | 3/3 | 0 | 0 | 3/3 | 3/3 | 0.03 | 0.05 |
| lbo | 10 | 10 | 10/10 | 0 | 0 | 10/10 | 10/10 | 0.23 | 0.40 |
| merger | 9 | 9 | 9/9 | 0 | 0 | 9/9 | 9/9 | 0.15 | 0.18 |
| pitchbook_section | 8 | 8 | 8/8 | 0 | 0 | 8/8 | 8/8 | 0.16 | 0.24 |
| precedents | 4 | 0 | 0/0 | 4 | 0 | 0/0 | 0/0 | n/a | n/a |
| profile | 11 | 10 | 10/10 | 1 | 0 | 10/10 | 10/10 | 0.19 | 0.34 |
| teaser | 10 | 10 | 10/10 | 0 | 0 | 10/10 | 10/10 | 0.13 | 0.19 |
| three_statement | 10 | 10 | 10/10 | 0 | 0 | 10/10 | 10/10 | 0.29 | 0.45 |
| vdr_review | 7 | 6 | 6/6 | 1 | 0 | 6/6 | 6/6 | 0.03 | 0.04 |

## By perturbation

| perturbation | briefs | done | success | blocked/unsupported | silent numbers | deterministic | resume ok | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| arabic_mixed | 6 | 6 | 6/6 | 0 | 0 | 6/6 | 6/6 | 0.19 | 0.51 |
| arabic_only | 4 | 0 | 0/0 | 4 | 0 | 0/0 | 0/0 | n/a | n/a |
| base | 43 | 39 | 39/39 | 4 | 0 | 39/39 | 39/39 | 0.22 | 0.59 |
| deal_context | 16 | 16 | 16/16 | 0 | 0 | 16/16 | 16/16 | 0.15 | 0.45 |
| override | 18 | 18 | 18/18 | 0 | 0 | 18/18 | 18/18 | 0.56 | 0.70 |
| phrasing | 39 | 39 | 39/39 | 0 | 0 | 39/39 | 39/39 | 0.18 | 0.59 |

## By data kind and region

| data | briefs | done | success | blocked/unsupported | silent numbers | deterministic | resume ok | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| real | 41 | 37 | 37/37 | 4 | 0 | 37/37 | 37/37 | 0.21 | 0.74 |
| synthetic | 85 | 81 | 81/81 | 4 | 0 | 81/81 | 81/81 | 0.22 | 0.59 |

| region | briefs | done | success | blocked/unsupported | silent numbers | deterministic | resume ok | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| MENA | 4 | 3 | 3/3 | 1 | 0 | 3/3 | 3/3 | 0.03 | 0.05 |
| US | 122 | 115 | 115/115 | 7 | 0 | 115/115 | 115/115 | 0.22 | 0.65 |

## Failures

None among supported briefs.

## Blocked (engine has not landed)

- `precedents` x4: The S4 precedents engine hasn't landed yet (S4 precedents stage); this step cannot run until it does. The other steps in this run are unaffe

## Arabic prompt text

- Arabic text with English task keywords: 6/6 planned and ran.
- Arabic-only prompts: 4 of 4 failed gracefully with a hint (rule-first planner has no Arabic rules; the adapter planner path needs a live or recorded model). This is a **product gap for MENA users**, not a harness issue.
  - `rel-119`: hint = Try naming a task, e.g. 'DCF for Apple', or pick an agent from the library.
  - `rel-120`: hint = Try naming a task, e.g. 'DCF for Apple', or pick an agent from the library.
  - `rel-121`: hint = Try naming a task, e.g. 'DCF for Apple', or pick an agent from the library.
  - `rel-122`: hint = Try naming a task, e.g. 'DCF for Apple', or pick an agent from the library.

## Silent numbers found

None. Every number checked carried a source or a flag.

## Determinism differences

None. Every re-run matched cell for cell / text for text.

## Resume failures

None. Every injected failure resumed to a result identical to the clean run, without re-running finished steps.

## Product observations from this run (not fixed here)

- **Override cells lose the input styling.** In 19 of 18 DCF override runs the overridden WACC / growth cell is a plain constant that is not blue and has no comment, so the workbook alone does not show it is a user override. The job's step note does disclose it ("Overrides applied: ..."), so the number is counted as flagged here, but a reader who only opens the xlsx sees an unmarked hard-code (19 cells).

## Deterministic gate observations (not counted in success)

`om.modelcheck` did not mark 33 delivered workbook(s) production-ready. By (task, ticker): dcf/DEMOA x8; dcf/DEMOB x6; dcf/DEMOT x6; earnings_update/DEMOA x2; earnings_update/DEMOB x2; earnings_update/DEMOT x2; three_statement/DEMOA x3; three_statement/DEMOB x2; three_statement/DEMOT x2.

## Corpus coverage and honesty

- Corpus: 142 briefs; data kinds: real 41, synthetic 85, needs_live 16.
- Distinct companies offline: 4 tickers (AAPL real; DEMOA/B/T synthetic) plus 2 synthetic deals. Runs of the same company under different phrasing are not independent samples.
- US-GAAP only offline. IFRS and MENA companies (MSFT, NVDA, SWDY, SAP in the corpus) need live data and are skipped; the MENA coverage here is the synthetic Nile data room (EN+AR documents).
- Prose deliverables (IC memo, recap, buyer list) are canned replay text for AAPL only and are flagged `REPLAY FIXTURE`; they pass the number check by that flag, not by being right.
- Latency excludes model time. Cost is the priced replayed usage of canned fixtures, not a bill; live cost per deliverable has not been measured.

### Skipped (need live)

- `rel-127` dcf MSFT (US)
- `rel-128` dcf NVDA (US)
- `rel-129` dcf SWDY (MENA)
- `rel-130` dcf SAP (IFRS)
- `rel-131` comps MSFT (US)
- `rel-132` comps NVDA (US)
- `rel-133` comps SWDY (MENA)
- `rel-134` comps SAP (IFRS)
- `rel-135` three_statement MSFT (US)
- `rel-136` three_statement NVDA (US)
- `rel-137` three_statement SWDY (MENA)
- `rel-138` three_statement SAP (IFRS)
- `rel-139` lbo MSFT (US)
- `rel-140` lbo NVDA (US)
- `rel-141` lbo SWDY (MENA)
- `rel-142` lbo SAP (IFRS)
