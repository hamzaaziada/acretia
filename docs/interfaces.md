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

## Models (S4)

**Status: implemented (S4.8).** One stable module, `om/modelapi.py`, is the only thing the product app needs to build, edit,
question, audit and export a financial model. Every call is a pure function over workbook bytes and small JSON-friendly
dicts; the only state is an on-disk store keyed by `model_id`. No model (LLM) call is made, and nothing touches the network
unless the default `fetch` is used. Session F wires the model view on top of it.

```python
from om import modelapi
from om.modelapi import ModelResult, ModelApiError, DeliveryBlocked   # DeliveryBlocked is om.delivery.DeliveryBlocked

modelapi.build_model(kind, tickers, *, assumptions=None, quotes=None, fetch=None) -> ModelResult
    # kind: "three_statement" | "dcf" | "lbo" | "merger" | "comps"
    # tickers: one ticker; merger = [acquirer, target]; comps = [target, *peers] (at least one peer)
    # assumptions: the builder's own overrides (om.model3 / om.lbo / om.merger defaults keys); comps also takes
    #              "as_of" and "calendar_month"
    # quotes: an om.prices.Quote, {ticker: Quote} or CsvPrices (same as om.market.resolve); without one, the
    #         public-float proxy from the filings is used when it exists
    # fetch: callable ticker -> SEC companyfacts dict. Default: om.sec with SEC_USER_AGENT (cached under data/raw/sec)
modelapi.get_model(model_id, version=None) -> ModelResult          # latest version when None
modelapi.get_bytes(model_id, version=None) -> bytes                # the .xlsx
modelapi.list_versions(model_id) -> [{"version", "parent_version", "bytes_sha256", "created_at"}]
modelapi.list_inputs(model_id, version=None) -> [{"cell", "sheet", "label", "period", "value", "fmt", "source"}]
modelapi.set_inputs(model_id, changes: dict[str, number], *, version=None) -> ModelResult
modelapi.ask(model_id, question, *, version=None) -> {"answer", "cells", "values", "reconciled", "unreconciled", "method"}
modelapi.audit(model_id, version=None) -> {"tabs": [...], "findings": [...]}
modelapi.explain(model_id, cell, *, version=None) -> dict
modelapi.export(model_id, *, fmt="xlsx", logo_png=None, version=None) -> bytes   # fmt: "xlsx" | "xlsx_values" | "manifest_json"
modelapi.export_with_report(...same...) -> (bytes, {"warnings": [...], "gate": {...}, "sha256"})
modelapi.update_earnings(model_id, *, fetch=None) -> ModelResult
```

`"dcf"` is the three-statement workbook (it contains the DCF sheet) with the outputs led by the DCF ids
(`m3.dcf.value_per_share`, `m3.dcf.enterprise_value`, `m3.dcf.equity_value`, `m3.dcf.tv_pct_ev`).

### ModelResult

```json
{
  "v": 1,
  "model_id": "m_8d68ab77605ec281775d",
  "version": 2,
  "parent": {"version": 1, "bytes_sha256": "<hex>"},        // null for version 1
  "kind": "dcf",
  "tickers": ["ACME"],
  "created_at": "2026-11-16T09:30:00Z",
  "bytes_sha256": "<hex>", "bytes": 52720,
  "outputs": [
    {"id": "m3.dcf.value_per_share", "label": "Implied value per share", "sheet": "DCF", "ref": "C48", "units": "USD/share",
     "value": 35.33,
     "citations": [{"doc_id": "0000320193-24-000123", "sha256_span_hash": "<hex>", "quote": "us-gaap:Revenues = ...",
                    "source_url": "https://www.sec.gov/Archives/edgar/data/...", "sheet": "Filings", "cell": "D9"}]}
  ],
  "checks": {"master": "OK", "ok": true,
             "items": [{"label": "Balance sheet balances", "cell": "Checks!C9", "value": "OK", "ok": true, "cells": 9}]},
  "grade": {"score": 100.0, "production_ready": true, "critical_failed": [], "formulas": 1017, "typed_numbers": 300},
  "validate": {"passed": true, "critical": 0, "warnings": 2, "formulas": 1017, "circular_cells": 14, "first_findings": []},
  "engines": {"agree": true, "compared_cells": 1017, "divergences": 0,
              "engines": {"om": {"available": true, "cells": 1017, "seconds": 0.8, "reason": ""}}},
  "timings": {"fetch": 0.01, "build": 1.9, "grade": 0.7, "validate": 0.5, "recalc": 1.4, "manifest": 0.3, "total": 4.9},
  "warnings": [],
  "markets": {"ACME": {"price": 50.0, "as_of": "2025-01-03", "source": "quote ...", "basis": "quote"}},   // lbo, merger, comps
  "assumptions": {},
  "edit":   {"changes": [{"cell", "label", "period", "before", "after"}],
             "changed_outputs": [{"id", "label", "before", "after"}], "dependents_updated": 412, "parts_touched": ["xl/worksheets/sheet3.xml"]},
  "update": {"rolled": true, "new_actual": {...}, "previous_last_actual": 2023, "forecast_years": [2025, 2026, 2027],
             "variance": [{"metric", "prior_forecast", "actual", "diff", "pct_diff", ...}], "changed_outputs": [...], "timings": {...}}
}
```

`edit` is present only on versions made by `set_inputs`, `update` only on versions made by `update_earnings`. `timings` are
seconds per step (D-032); `total` is wall time of the call that made the version. `checks.ok` is the master check plus every
check line; read `checks.master` for the single cell the workbook shows.

### Other shapes

```json
// list_inputs: blue input cells, by row label and period. Reported (filing) figures and the Checks sheet are not inputs.
{"cell": "Assumptions!E27", "sheet": "Assumptions", "label": "Tax rate (% of pre-tax income)", "period": "FY2024E",
 "value": 0.21, "fmt": "0.0%_);(0.0%);\"–\"_)", "source": null}

// ask: reconciled is true only when every cited value equals the workbook's cached value AND an independent om.formula
// recalculation of that cell (parity 43). No cell found: cells == [], reconciled == false.
{"answer": "Revenue FY2025E = 1,309.83 (IS!F9). ...", "cells": ["IS!F9"], "values": [1309.83], "reconciled": true,
 "unreconciled": [], "method": "..."}

// audit (parity 44): one entry per tab, in workbook order
{"tabs": [{"sheet": "IS", "formulas": 153, "inputs": 0,
           "links_in":  [{"sheet": "CF", "count": 12}], "links_out": [{"sheet": "Assumptions", "count": 40}],
           "errors": ["IS!G9"], "hardcodes": ["IS!H12"], "unsourced": [],
           "checks": {"ok": 0, "error": 0}}],
 "findings": [{"id": "errors", "severity": "critical", "sheet": "IS", "cell": "G9", "message": "..."}]}   // om.validate_xlsx findings

// explain (parity 20): om.wbgraph.explain plus the leaves that have no source
{"cell": "IS!E9", "label": "Revenue (FY2023A)", "formula": "=Filings!E9", "value": 1.1e9,
 "precedents": [...], "inputs": [{"cell": "Filings!E9", "value": 1100.0, "source": "us-gaap:Revenues = ...", "link": "https://www.sec.gov/..."}],
 "unsourced_leaves": []}
```

### Errors

All are `ModelApiError` subclasses with a stable string `code`, a message that starts with the cause, and `detail`
(JSON-friendly or `None`); `e.to_dict()` is `{"code", "message", "detail"}`.

| code | class | raised when |
|---|---|---|
| `unsupported_company` | `UnsupportedCompany` | bank/insurer or unclassified balance sheet, fewer than two fiscal years, a required line is not tagged, unknown ticker, `fetch` found nothing |
| `no_market_price` | `NoMarketPrice` | `lbo`, `merger` or `comps` needs a price and neither `quotes` nor the filings supply one (`detail.ticker`) |
| `not_an_input` | `NotAnInput` | `set_inputs` touched a formula, a reported figure, an empty cell or another non-blue cell; `detail` is `[{"cell", "reason"}]`; nothing is changed |
| `blocked` | `Blocked` (also an `om.delivery.DeliveryBlocked`) | `export` and the delivery gate failed; `.report` / `detail` is the gate report (`steps[name, passed, detail]`) |
| `not_found` | `NotFound` | unknown `model_id`, version or cell |
| `invalid_request` | `InvalidRequest` | bad kind, tickers, question, number, cell reference or export format; `update_earnings` on a non-three-statement model |

### Storage layout

`ACRETIA_MODELS_DIR` (default `storage/models/`, not committed):

```
<dir>/m_<20 hex>/v1/model.xlsx       # the workbook of that version
<dir>/m_<20 hex>/v1/record.json      # the ModelResult above, exactly as returned
<dir>/m_<20 hex>/v1/private.json     # builder metadata, build inputs and cumulative input edits (not part of the contract)
<dir>/m_<20 hex>/v2/...              # one directory per version; a version records its parent
<dir>/_sources/<sha256>.json.gz      # the companyfacts each model was built from (content-addressed)
```

`model_id` is `m_` plus 20 hex characters of the sha256 of the build key (kind, tickers, assumptions, markets and the sha256
of each filings payload), so building the same thing twice returns the same model and version 1 without recomputing.
Files are written once and never changed; `record.json` is written last, so a version is visible only when complete.
Editing never overwrites: `set_inputs` and `update_earnings` add the next version number with `parent` pointing at the
version they started from (`version=` on `set_inputs` branches from an older one).

### Runnable examples (offline, from the repo root)

```python
import os, tempfile
os.environ["ACRETIA_MODELS_DIR"] = tempfile.mkdtemp()
from datetime import date
from om import modelapi
from om.prices import Quote
from tests.test_model3 import synthetic_companyfacts

fetch = lambda ticker: synthetic_companyfacts(years=(2022, 2023))        # any callable ticker -> companyfacts

# build_model, get_model, get_bytes
m = modelapi.build_model("dcf", ["ACME"], fetch=fetch)
mid = m["model_id"]
print(m["checks"]["master"], m["outputs"][0]["id"], round(m["outputs"][0]["value"], 2))     # OK m3.dcf.value_per_share 35.33
lbo = modelapi.build_model("lbo", ["ACME"], fetch=fetch, quotes={"ACME": Quote("ACME", 50.0, "USD", date(2025, 1, 3), "demo")})
try:
    modelapi.build_model("lbo", ["ACME"], fetch=fetch)                   # no quote, no public float in these filings
except modelapi.NoMarketPrice as e:
    print(e.code)                                                        # no_market_price
assert modelapi.get_model(mid) == m and modelapi.get_bytes(mid)[:2] == b"PK"

# list_inputs, set_inputs (a new version; changed outputs come back with before/after)
tax = next(i for i in modelapi.list_inputs(mid) if i["label"].lower().startswith("tax") and i["period"])
m2 = modelapi.set_inputs(mid, {tax["cell"]: tax["value"] + 0.05})
print(m2["version"], m2["parent"]["version"], m2["edit"]["changed_outputs"][0]["id"])       # 2 1 m3.dcf.value_per_share
try:
    modelapi.set_inputs(mid, {"IS!G9": 1})                               # a formula
except modelapi.NotAnInput as e:
    print(e.code, e.detail)                                              # not_an_input [{'cell': 'IS!G9', 'reason': 'a formula'}]

# ask, audit, explain
a = modelapi.ask(mid, "What is revenue in FY2025?")
print(a["cells"], a["reconciled"])                                       # ['IS!F9'] True
print([(t["sheet"], t["formulas"], len(t["errors"])) for t in modelapi.audit(mid)["tabs"]][:3])
ex = modelapi.explain(mid, "IS!E9", version=1)
print(ex["formula"], ex["inputs"][0]["cell"], ex["inputs"][0]["source"][:30])          # =D9*(1+Assumptions!E13) Filings!D9 us-gaap:Revenues = 1,1

# export: refused with Blocked unless om.delivery.gate passes
xl = modelapi.export(mid, fmt="xlsx")
values_only = modelapi.export(mid, fmt="xlsx_values")
manifest = modelapi.export(mid, fmt="manifest_json")

# update_earnings: roll forward to the newest filing (a new version, timings recorded)
m3 = modelapi.update_earnings(mid, fetch=lambda t: synthetic_companyfacts(years=(2022, 2023, 2024)))
print(m3["version"], m3["update"]["rolled"], m3["update"]["new_actual"]["label"], round(m3["timings"]["roll_forward"], 1))
```

### Optional xlsx hooks

- `xlsx_values` uses `om.xlsx.values_only(bytes)` when it exists; otherwise a built-in fallback drops every formula and keeps
  the cached values (string results become inline strings; the calc chain is removed).
- `logo_png` uses `om.xlsx.Sheet.image(png, anchor)` when it exists: the version is rebuilt from its stored filings plus its
  input edits and the logo goes on the first sheet at `modelapi.LOGO_ANCHOR` (`"B2"`). If the hook is missing, the version
  cannot be rebuilt (rolled forward) or the hook fails, the logo is ignored: `export_with_report` lists it in `warnings` and
  `export` raises a `UserWarning`. The gate always runs on the stored version first.

### What is guaranteed stable

Within `"v": 1`: the function names and keyword arguments above; the error codes; the field names and meanings in
ModelResult, `list_inputs`, `ask`, `audit` and `explain`; the storage layout and the immutability of stored versions; that
`model_id` is a pure function of the build inputs; that `set_inputs` only ever edits blue input cells and never overwrites a
version; that `export` never returns bytes the delivery gate refused. Additive changes only: new optional fields, new output
ids, new error codes (clients must treat an unknown `code` as a failure) and new export formats. Output ids follow the
builders (`m3.*`, `lbo.*`, `merger.*`, `comps.*`); a new id may appear, an existing id keeps its meaning. `timings` keys,
`first_findings`, `method` and the wording of messages are informative, not contract.
