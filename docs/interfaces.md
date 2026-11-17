# Interfaces

## Research agent jobs

Status: **stable (S6.0)**. Code: `src/harness/research/{api,jobs}.py`. The agent behind it is a placeholder until S6.1;
the interface below does not change when it lands. Output is only SlideSpecs, Excel input payloads and sourced figures,
never free prose (PLAN S6.2).

### Python signatures

```python
from src.harness.research.api import (ResearchRequest, ResearchResult, SourcedFigure, ExcelInputPayload,
                                      ResearchEvent, run_research, partition_figures)
from src.harness.research import jobs

run_research(request, *, adapter=None, tools=None, evidence_dir="storage/evidence", job_id=None,
             on_event=None, cancel=None) -> ResearchResult          # synchronous, in-process

jobs.submit(request, *, org_id=None) -> job_id                      # org comes from request.org_id
jobs.status(job_id, *, org_id="local") -> om.contracts.Job
jobs.result(job_id, *, org_id="local") -> ResearchResult | None     # None until finished
jobs.cancel(job_id, *, org_id="local") -> bool                      # False if already finished
jobs.events(job_id, after_seq=0, *, org_id="local", limit=500) -> list[dict]
jobs.worker_loop(stop_event, adapter=None, *, tools=None, evidence_dir=None, lease=300.0, poll=0.2)
jobs.JobNotFound                                                    # KeyError subclass
```

Storage: `SQLiteKV` queue `research` in `ACRETIA_JOBS_DB` (default `storage/jobs.sqlite`); evidence chains in
`ACRETIA_EVIDENCE_DIR` (default `storage/evidence/<job_id>.jsonl`, verify with `src.harness.evidence.verify`).
`run_research` never raises for agent failures (they return `status: "failed"` with `error`); it raises
`ContractError` only for an invalid request or job id. Run one `worker_loop` thread/process per backend.

### JSON shapes (every payload carries `"v": 1`)

Request (only `question` is required):

```json
{"v": 1, "question": "What drove Apple's FY24 gross margin?", "tickers": ["AAPL"], "doc_ids": [], "room_id": null,
 "as_of": "2025-09-27", "outputs": ["slide_specs", "excel_inputs", "grid_answers"], "budget_usd": 2.0,
 "max_steps": 12, "org_id": "local", "user_id": null}
```

`budget_usd > 0`, `max_steps` 1..50, `outputs` a non-empty subset of the three kinds, `as_of` a real YYYY-MM-DD.

Result:

```json
{"v": 1, "job_id": "res_3f2a9c1d0b7e4a55", "status": "succeeded", "evidence_head": "<64 hex>",
 "slide_specs": [{"id": "s1", "layout": "...", "...": "SlideSpec as in om/contracts.py"}],
 "excel_inputs": [{"v": 1, "model_type": "dcf", "ticker": "AAPL", "inputs": {"revenue": "<SourcedFigure>"}}],
 "figures": [{"v": 1, "label": "Revenue", "value": 391035.0, "units": "USD_m", "period": "FY2024",
              "citation": {"doc_id": "doc1", "sha256_span_hash": "<64 hex>", "url": "https://www.sec.gov/...",
                           "page": null, "as_of": "2025-09-27"}}],
 "rejected": [{"figure": {"label": "TAM"}, "reason": "SourcedFigure.citation.as_of: required: ..."}],
 "cost_usd": 0.0, "tokens": 0, "error": null,
 "steps": [{"name": "plan", "status": "succeeded", "detail": ""},
           {"name": "note", "status": "succeeded", "detail": "agent not yet implemented (S6.1)"}]}
```

Invariants enforced by `ResearchResult.validate()`: no prose keys (`summary`, `answer`, `text`, `report`, `markdown`,
...) anywhere at the top level; every figure has `citation.as_of` and either a `url` or `doc_id` with a `page`; a
figure that fails this belongs in `rejected` (use `partition_figures`), never in `figures`.

Event (`type` is one of `step_started`, `step_finished`, `figure`, `rejected`, `cost`, `done`, `error`):

```json
{"v": 1, "seq": 3, "type": "step_finished", "job_id": "res_3f2a9c1d0b7e4a55",
 "ts": "2026-11-16T09:30:00.123456Z", "data": {"name": "plan", "status": "succeeded"}}
```

`seq` is 1-based and gapless per job (assigned by `jobs.events`; absent on in-process `on_event` callbacks). The last
event of a finished job is `done` with `data.status`; failures emit `error` (`data.message`) before `done`.

### Status lifecycle

`queued -> running -> succeeded | failed | cancelled`. `jobs.status()` returns the `om.contracts.Job` row
(`attempts`, `tokens`, `cost_usd`, `steps`, `error`). A crashed worker leaves the queue item leased; after the lease
expires it is re-delivered and re-run under the same `job_id` (evidence chain continues, the result is written once,
a duplicate delivery of a finished job is acked without re-running). After 3 attempts the job is marked `failed`.

### Cancellation

`jobs.cancel()` sets a persisted flag; the run checks it between steps and returns `status: "cancelled"` with the
steps completed so far. A queued job is cancelled as soon as a worker picks it up. In-process callers pass a
`threading.Event` as `cancel=`.

### Org scoping

Every row is keyed by `org_id` (from `ResearchRequest.org_id`, so the backend must set it from the authenticated
session, never from client input). Another org's `job_id` behaves exactly like an unknown one: `JobNotFound` from
`status/result/events/cancel`. Map it to HTTP 404.

### Recommended HTTP surface (for the product-app session; not implemented here)

| Route | Maps to | Response |
|---|---|---|
| `POST /v1/research/jobs` | `jobs.submit(ResearchRequest.from_dict({**body, "org_id": session.org, "user_id": session.user}))` | `202 {"v": 1, "job_id": "..."}` |
| `GET /v1/research/jobs/{id}` | `jobs.status` plus `jobs.result` | `{"v": 1, "job": Job, "result": ResearchResult or null}` |
| `GET /v1/research/jobs/{id}/events?after=n` | `jobs.events(id, n)` | JSON list for polling, or the same items as SSE (`id: <seq>`, `data: <event json>`; resume with `Last-Event-ID`); close the stream after a `done` event |
| `POST /v1/research/jobs/{id}/cancel` | `jobs.cancel` | `{"v": 1, "cancelled": bool}` |

`ContractError` on submit -> 422 with the message (it starts with the offending field path). `JobNotFound` -> 404.

### Stability promise

Additive changes only: new optional fields, new event `data` keys, new event types (clients must ignore unknown
types), new outputs kinds. Existing field names, meanings and the status lifecycle do not change within `"v": 1`. A
breaking change bumps `v`; this build rejects any payload with another `v`.

## Annual-report reading (S8, session E)

One stable call turns an annual-report PDF into tied, cited statements plus a review queue. The PDF may be native or
scanned, and in Arabic, English or both. The implementation lands with S8.3b; this signature is the contract now.

```python
from om.intl.pipeline import read_report, ReportResult

res: ReportResult = read_report(
    pdf,                      # path or bytes; native or scanned; Arabic, English or bilingual
    *, company=None,          # optional name/ticker hint
    hints=None,               # optional {"currency": "EGP", "unit_scale": 1e3, "fiscal_year_end_month": 6, "standard": "EAS",
                              #           "pages": {"IS": 7, "BS": 6, "CF": 9}}
    prior=None,               # optional ReportResult or PDF of the previous year's report (comparatives tie)
    strict=True,              # strict: statements is None unless every hard tie passes
)
res.statements      # om.intl.types.IntlStatements | None (subclass of om.statements.Statements; om.model3.build accepts it)
res.extracted       # om.intl.types.ExtractedStatements (every printed figure, released or not)
res.tie_report      # om.intl.tieout.TieReport (passed, ties[name, period, lhs, rhs, diff, passed, figures])
res.review          # list[om.intl.review.ReviewItem]: figure, reasons, page, bbox_norm, crop_png (highlighted)
res.blocked         # bool: True when strict release was refused (statements is None, review explains why)
res.telemetry       # {"wall_seconds", "steps": [{"name", "started_at", "finished_at", "seconds", "tokens", "cost_usd", "engine"}],
                    #  "pages", "scanned", "language", "flags", "review_minutes"}  (docs/product/SPEC.md "Telemetry")
res.to_json()       # {"v": 1, ...} with the review crops as file paths or base64
```

Guarantees:
- Every figure carries page, bbox_norm in [0, 1] and confidence in [0, 1].
- A figure that fails a tie, or falls below the confidence threshold without corroboration, is in `review` and never
  in `statements`.
- The data layer is deterministic: the same bytes give the same numbers.
- No model call is made, so `tokens` and `cost_usd` are 0.

Stability: fields are only added within `"v": 1`.

## Deck engine (S3, session B)

One stable call for the product app: **brief → ghost deck → (approval) → deck + validation report**.

```python
from om.deck.engine import deck_from_brief, build
from src.harness.adapter import Adapter

res = deck_from_brief(brief,                    # str, or dict {"brief", "client", "lang", optional "ghost", "spec"}
                      adapter=Adapter.from_env(),  # None or replay-miss -> needs brief["ghost"] + brief["spec"]
                      lang="en",                # "ar" -> RTL deck
                      approve=None,             # None: return the ghost for UI approval, no deck
                                                # True or callable(GhostDeck) -> bool: build after approval
                      out="deck.pptx", seed=None, template=None, critic=True)
# -> {"ghost": GhostDeck dict, "pptx": path | None, "report": BuildReport dict}
```

Two-step flow for the UI (S7.3 workbench): call once with `approve=None` and show `res["ghost"]` (action titles,
sections, lint findings). When the user approves (optionally after editing titles), call again with the edited
ghost in `brief["ghost"]` and `approve=True`.

`build(spec, *, out, adapter=None, ghost=None, require_ghost_approval=False, seed=None, template=None,
profile=None, manifest=None, values=None, critic=True, n_candidates=3, job_id=None, strict=True) -> BuildReport`
builds from a DeckSpec v2 (YAML/JSON, `om/deck/spec.py`).

BuildReport (`.to_dict()`): `ok`, `path`, `slides`, `critical`, `major`, `findings` (each `{severity, rule, slide,
shape_id, shape_name, message}`: shape ids let the UI badge the exact shape), `art_direction`, `image_probe`,
`visuals` (per slide candidates, scores, kept id), `critic` ("not run live" offline), `timings` (per step ms),
`total_seconds`, `tokens`, `cost_usd`, `numbers_digest` (same brief + data → same digest; visuals may vary),
`job` (om.contracts.Job dict).

Related: `scripts/validate_pptx.py deck.pptx --json` (validator alone), `om.deck.sync.resync(pptx, manifest,
values)` (refresh bound charts/tables/KPIs from the model, no LLM), `om.deck.revise` / `om.deck.versions`
(per-slide revision, annotations, versions, rollback). CLI: `python3 open_multiples.py slides build spec.yaml
--out deck.pptx [--json]`. Stability: the call signature and the report keys above are stable from S3; new keys
may be added, none removed without a decision entry.
