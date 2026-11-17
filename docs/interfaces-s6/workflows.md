# Research workflows (S6.1)

Status: **stable shape, S6.1**. Code: `src/harness/research/workflows/{base,review,steps,catalog}.py`. Decision D-033: the
agent runtime (loop, planning, context, recovery) belongs to the harness-lab session (S9, `src/harness/agent/`). This
package ships **declarative step graphs** plus a minimal sequential executor. It contains no agent loop.

## Model

```python
Step(id, kind, tool=None, args_template={}, depends_on=(), optional=False, timeout_s=60.0, foreach=None, when=None)
Workflow(id, title, description, inputs_schema, steps, outputs, keywords=(), requires=(), prepare=None)
```

* `kind` is one of `tool` (call a registry tool), `review_gate` (pre-run source review), `assemble` (build slides, Excel
  inputs and candidate figures from earlier outputs; registered in `base.ASSEMBLERS`), `llm_text` (action-title wording,
  registered in `base.TEXT_STEPS`) and `verify` (`verify_result`; exactly one, always last).
* `args_template` values may contain `{{request.tickers[0]}}`, `{{request.options.years|5}}` (default after `|`),
  `{{steps.<id>.data.x}}`, `{{plan.x}}` (output of `Workflow.prepare(request)`, a pure function) and `{{item}}` inside a
  `foreach` step. A whole-string reference keeps its type; an embedded one is stringified. Unresolvable references raise
  `TemplateError` (the step fails, or is skipped if `optional`).
* `foreach` runs the tool once per list item (max 25); the output is a list. `when` skips the step when the expression
  is empty. `depends_on` must name earlier steps; a failed dependency fails the step.
* A step id means one definition across the catalog (tested), so `compose()` can run shared steps once.

## Contract a runtime must satisfy

`src.harness.agent.run_workflow(workflow, context) -> ResearchResult` is used automatically when
`importlib.util.find_spec("src.harness.agent")` finds a module exposing it; otherwise `base.execute` runs. The runtime
receives a `RunContext` and must:

1. call `context.begin()`, then `context.run_step(step, n, total)` for steps in a dependency-respecting order (it may
   reorder independent steps, retry, or skip optional ones; it must not skip `review_gate` or `verify`);
2. stop when `context.status != "running"` and return `context.finish()` exactly once (it validates the result and
   closes the evidence chain);
3. never write figures, slides or evidence directly, and never call a model except through `context.adapter`.

`run_step` does the per-step work: `step_started`/`step_finished` events with `progress` `"n/N"` and `wall_clock_s`,
cancel check before each step, one evidence record per tool call (plus one per review, assemble, llm_text and verify
step), `max_steps` accounting and per-step timeout. `ResearchResult.timings` maps step id to `wall_clock_s` for the TSB
harness (docs/time-saved-baselines.md section 3); it is absent from the wire form while empty and excluded from
`output_digest()`, which hashes status, slides, Excel inputs, figures and rejected (identical inputs give an identical
digest).

## Verification rules

* Every figure and every slide goes through `verify_result` in the final `verify` step. Unverified figures land in
  `rejected`; a slide or Excel payload holding an unverified number is rejected whole. On `failed` or `cancelled` no
  figure or slide is returned (nothing unverified is shown).
* Assemblers build slides only from figures that pass `verify_figure` first (`steps.usable`), so one bad figure removes
  its own number, not the slide. Titles contain no number except years (D-S6-04); with an adapter, a reworded title is
  accepted only if it passes `action_title_lint` and has no number other than a year. The adapter receives metric labels
  only, never document text.
* The run's resolver (`LayeredResolver`) uses an injected independent `SourceResolver` first (`run_research(resolver=)`,
  documents/XBRL), then what the run's own tool calls captured: XBRL rows from `sec_facts`, source quotes per URL,
  cell values. Caller-supplied figures and document numbers are never self-snapshotted.
* Ratios and changes are computed in code from verified statement figures, with the arithmetic written in the citation
  quote. The `ratios` tool is not used: its unitless quotes cannot be re-checked next to `sec_statements` quotes
  through one resolver (the "USD millions" declaration in the statements quotes rescales them). Finding for the verifier
  owner: a per-figure snapshot would remove the clash.

## Workflows (`catalog.CATALOG`)

| id | needs | output |
|---|---|---|
| `company_profile` | `tickers` | `kpi_row`, `scorecard` (or a table when under 3 years), `chart_takeaways`, optional business bullets (`options.company_url`, sentences without digits), `three_statement` ExcelInputPayload |
| `earnings_recap` | `tickers` | `kpi_row`, latest-vs-prior table incl. margins in bps and diluted EPS when tagged, guidance table only when `options.guidance_url` yields sourced figures |
| `buyer_list` | `options.candidates` | ranked tables per strategic and financial group; candidates only from the input list or `options.grid_sql` rows; unscored buyers listed last |
| `qa` | `tickers`, `question` | sourced figures chosen by question keywords (`plan.want`), `kpi_row` or table |
| `tick_and_tie` | `doc_ids` and a source | per page: number, location (`index`), matched source, status `ok`, `mismatch` or `unsourced` |

Slide shape: SlideSpec with `archetype` (ids from `om.deck.archetypes.REGISTRY`) and the archetype payload in
`data["archetype_blocks"]` (the contract's `blocks` is a typed list, so a deck-side adapter maps `data` to the DeckSpec
`blocks`); generic tables are `blocks=[{"type": "table", "columns": [...], "rows": [...]}]` where every numeric cell is
`{"label": <figure label>, "value": <display string>}`. Display strings keep enough decimals to verify within 0.5%.

Buyer score (deterministic, documented): `0.5*capacity + 0.3*leverage headroom + 0.2*operating margin`, capacity =
`min(1, cash / options.deal_size_usd_m)` (50,000 USD m when no size is given), margin scaled to 30%, headroom
`1 - max(debt - cash, 0) / (6 * operating income)` (0.5 when unavailable), ties by name. Capacity comes from a sourced
cash, dry-powder, AUM or capacity figure; scores are not printed, rank is.

`tick_and_tie` inputs: page text from `options.pages` (`{doc_id: {"1": text}}`) or an injected resolver with pages;
the model/figures from `options.figures` (SourcedFigure dicts), `options.model` (`{"path", "cells"}` via
`xlsx_evaluate`) or statement figures for `tickers`. Needs `request.as_of` or `options.doc_as_of` (else the latest
source as-of). A number matches a figure when the figure's label words all appear in the same sentence and the values
agree within the larger of 0.5% and half the last printed digit (page-declared scale "in millions" is applied).
Years, dates, page and note references and unitless integers 0-20 are not checked.

## Source review (item 24)

First step of every workflow. Emits `source_review` (`status: awaiting_review`, `sources`: tools with resolved args,
`doc_id`s, URLs) and waits for `review=callable(sources)->bool` or `workflows.approve(job_id, evidence_dir=None)` /
`reject(job_id)`; passing `evidence_dir` also writes `<evidence_dir>/<job_id>.review` so another process can approve.
`request.options.source_review=false` skips it; `options.review_timeout_s` bounds the wait (default 86400). Cancel wins
at any time; rejection or timeout ends `cancelled`. **Blocker for the Boss:** `jobs.status()` keeps `running` while the
gate waits, because `awaiting_review` is not in `om.contracts.STATUS` and `jobs.py` is out of scope. To close item 24 in
jobs mode: add `awaiting_review` to `STATUS`, have `jobs._process` set it on the `source_review` event and back to
`running` after, and expose `approve(job_id)` calling `workflows.approve(job_id, evidence_dir=ev_dir)`. The worker and
the approver then need the same evidence dir.

## "/" runs, routing, catalog

* `parse_command("/company_profile /earnings_recap AAPL")` -> workflows, tickers; `compose([...])` unions steps (shared ids
  run once; order review, tools, assemblers, titles, verify) and merges outputs.
* `run_research` picks the workflow from `request.workflow` (id, `"a,b"` or `"/a /b"`), a leading `/` command in
  `question` (tickers in the command are used when the request has none), or a strong phrase ("company profile",
  "one-pager", "earnings recap", "buyer list", "tick and tie"). Anything else keeps the S6.0 placeholder, so existing
  callers are unchanged. `qa` is explicit only (`workflow="qa"` or `/qa`). `ResearchRequest` gains optional `workflow`
  and `options` (omitted from `to_dict()` while unset); `ResearchResult` gains `timings`; `EVENT_TYPES` gains
  `source_review`; `run_research` gains `resolver=` and `review=`. `v` stays 1.
* `catalog.search(query, org_id, limit=10)`: BM25 over title, description and keywords (ties by id), filtered by
  `src.harness.admin.agents.is_enabled(org_id, workflow_id)`; if that module is not importable every workflow counts
  as enabled. `run_request` also refuses a disabled workflow (`status: failed`, error names the org).

## Known limits

* The tool surface is annual XBRL: "prior" and "prior-year" in `earnings_recap` are the same fiscal year; quarterly
  comparison needs a quarterly tool.
* Statement periods are labelled `FY<year of period end>`.
* `grid_answers` has no field in `ResearchResult`, so no workflow emits it.
* `buyer_list` metrics for non-listed buyers must be caller-supplied SourcedFigures that the resolver can verify.
