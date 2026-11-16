# eval/research: S6.3 research evals (Vals Finance Agent, FinanceBench, BankerToolBench)

Built and run offline (D-021). Live runs happen on the user's machine with `ACRETIA_LLM_*` env keys; a replay run never
fakes a live result.

```bash
python3 -m eval.research.datasets fetch            # explicit network step -> data/evals/<name>/, writes manifest.json
python3 -m eval.research.run --suite all --mode replay --limit 5      # offline; items with no fixture = not run
python3 -m eval.research.run --suite vals --mode live --limit 50      # user's machine only
python3 -m eval.research.run --suite all --data-root eval/research/fixtures --mode replay   # smoke run, no scorecard write
```

## Datasets (downloaded, never vendored; `data/` is gitignored; `manifest.json` has url + sha256 + fetched_at)

| name | source (pinned) | licence | notes |
|---|---|---|---|
| vals_v1 | github.com/vals-ai/finance-agent @72239d1 `data/public.csv` | MIT (repo); check vals.ai terms for questions | 50 public questions |
| vals_v2 | github.com/vals-ai/finance-agent-v2 @3ef5e4a `data/public.csv` | MIT (repo) | 27 public of 926; no gold Answer column, gold = rubric criteria |
| financebench | HF PatronusAI/financebench @e04404e | CC-BY-NC-4.0 | 150 open-source items; local scoring only |
| btb | HF handshake-ai-research/bankertoolbench @6407cdc `tasks.jsonl` | CC-BY-4.0 (tag `noai`); code Apache-2.0 | 100 tasks; deliverable rubrics, no short gold answer |

## Scoring (`score.py`)

Numbers: 1% relative (exact for counts) after unit normalisation (`$`, %, bps, million/billion, `USD_m` figures). A
correct number without a verified citation (doc_id + 64-hex span hash + url or page) scores as wrong. Evidence: a
citation page or quote overlapping gold evidence (FinanceBench). Long free-text gold and BTB rubrics are `unscorable`
here (need an LLM judge / deliverable grader, live) and are excluded from the accuracy denominator, never counted right.

## `scorecard.csv`

Columns `suite,metric,value,n,mode,ran_live,date,notes`. `update_scorecard()` upserts only `research/*` rows keyed by
(suite, metric) and keeps every other row. A replay row never overwrites a live row. Replay rows have a blank value and
the note `not run live (D-021)`.

## Time-saved hook: `data/evals/out/tsb_research.jsonl`

One JSON object per item (docs/time-saved-baselines.md §3 asks for instrumented `T_a` from job telemetry and a separate
review-and-rework estimate; it fixes no byte format, so this is the format `eval/tsb/` should ingest):

```json
{"v": 1, "task": "research_qa", "suite": "research/vals-v1", "item_id": "vals_v1-001", "category": "Beat or Miss",
 "mode": "live", "ran_live": "yes", "status": "succeeded",
 "T_a": {"wall_clock_s": 41.2, "cost_usd": 0.31, "tokens": 18211}, "review_and_fix_min": null, "ts": "2026-11-16T10:00:00Z"}
```

`review_and_fix_min` is left null: the TSB harness fills it from persona edit lists x minutes-per-edit.
