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
(per-slide revision, annotations, versions, rollback). CLI: `python3 acretia.py slides build spec.yaml
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

## Document grid (S5, session D)

Status: **stable (v1)**, including `MatrixChat` (S5.5c). Code: `om/grid.py` (store, engines, run stream), `om/grid_chat.py`
(Matrix Chat), `om/grid_export.py` (Excel/CSV), `om/docparse.py` (parse + Locator), `om/vdr_risk.py` (data-room risk
scan). CLI: `python3 acretia.py grid ...`. Engine version string `ENGINE_VERSION` is currently `grid-3`; it is folded into
every cell hash, so an engine upgrade reruns cells on the next run and nothing else.

Rule for the UI: **traceable or not shown.** A cell shows an answer only when its status is `ok` or `extracted`, and then
it always carries a page, a box and a quote the store located itself (an engine only proposes). Never render
`raw_answer` or a `suggestion`.

### Python signatures

```python
from om.grid import GridStore, BudgetExceeded
from om.grid_chat import MatrixChat
from om.grid_export import export_grid_xlsx, export_tables_xlsx, export_tables_csv
from om.vdr_risk import scan_documents, scan_room

store = GridStore(path=":memory:", backend="auto", parser_backend=None)   # "auto" = DuckDB if importable, else SQLite

# rows (documents)
store.add_document(path_or_bytes, name=None, source_path=None) -> doc_id           # parse once, cached by sha256
store.add_documents(items, workers=4, progress=None) -> {"files": [...], "ok", "failed", "duplicates", "alerts"}
#   items: paths or (name_or_source_path, bytes); progress(done, total, file_status) is called on the calling thread
#   file: {"name", "source_path", "status": "ok"|"duplicate"|"failed", "doc_id", "pages", "completeness_min",
#          "warnings", "error", "seconds"}; one bad file never aborts the batch; alerts are display strings
store.ingest_log() -> list[dict]                     # persisted per-file statuses from add_documents (not add_document)
store.create_grid(name, doc_ids, questions) -> grid_id          # name unique; grid_id also accepted by name everywhere
store.add_rows(grid, doc_ids)                         # idempotent
store.grid_names() -> [{"grid_id","name","created_at"}]; store.doc_ids(grid); store.document_name(doc_id)

# columns ("questions"): {"id", "text", "type", "instructions"?, "label"?, "condition"?, "engine"?}
#   type in text|number|percent|currency|date|boolean|list ; id has no whitespace
store.add_questions(grid, questions); store.questions(grid) -> list[dict]
store.update_question(grid, qid, text=None, type=None, instructions=None, condition=...)   # changes the hash: reruns
store.rename_question(grid, qid, label)               # label only, nothing reruns
store.reorder_questions(grid, [qid, ...])             # every id exactly once
store.dependents(grid, qid); store.delete_question(grid, qid, cascade=False) -> deleted ids   # ValueError if dependents
store.set_question_engine(grid, qid, "extractive" | "llm" | "llm:<model>" | <register_engine name>)   # per-column swap
store.register_engine(name, engine)
store.set_variable(grid, name, value); store.variables(grid)    # "{{var:name}}" in text / instructions
store.workflow_graph(grid) -> {"nodes","edges","order"}         # edges kind: variable | column | condition

# cost, run, results
store.estimate(grid, engine="extractive", questions=None, docs=None) -> estimate dict
store.run_stream(grid, engine="extractive", workers=8, max_cost_usd=None, questions=None, docs=None)  # generator
store.run(grid, ..., progress=None) -> done dict + "estimate"   # drains run_stream
store.runs(grid) -> [{"run_id","engine","started_at","finished_at","touched","skipped","est_cost_usd","actual_cost_usd",
                      "elapsed_s","first_cell_s","tokens_in","tokens_out","cells"}]
store.view(grid) -> {"grid_id","name","questions","rows":[{"doc_id","name","source_path","source_folder","cells":{qid: cell}}],
                     "pending_cells"}            # raw_answer is removed; a missing cell = pending
store.cells(grid) -> list[cell]; store.formatted_view(grid)    # view + styles
store.export_rows(grid) -> typed dicts; store.export_csv(grid, path)

# formatting, transfer, source folders, tables
store.set_format_rules(grid, rules) -> normalised rules; store.format_rules(grid)
store.filter_docs(grid, when) -> [doc_id]; store.transfer(grid, when, name, copy_questions=True, copy_cells=False) -> new grid_id
store.group_by_source(grid) -> {folder: [doc_id]}               # "" = no folder
store.tables(doc_id) -> [{"page","bbox_norm","rows","source","sha256_span_hash"}]
export_grid_xlsx(store, grid, path=None, *, logo_png=None, title=None, include_unverified=False) -> bytes   # "Matrix", "Sources", "Run log"
export_tables_xlsx(store, doc_ids_or_grid_id, path=None) -> bytes; export_tables_csv(store, doc_id, out_dir) -> [paths]

# Matrix Chat (S5.5c, stable v1)
chat = MatrixChat(store, grid_id, adapter=None, model=None)      # adapter None: exact templated answers, no model call
chat.ask(question, *, stream=False, max_rows=60) -> final dict   # stream=True: generator of events
```

### JSON shapes (grid payloads are plain dicts; every HTTP body should carry `"v": 1`)

Estimate (first stream event, and `store.estimate`):

```json
{"pending_cells": 4, "est_input_tokens": 0, "est_output_tokens": 0, "est_cost_usd": 0.0, "model": "extractive",
 "engine": "extractive", "skipped_cells": 0, "engine_calls": 4}
```

Cell (`cells`, `view` rows, `cell` events):

```json
{"doc_id": "<sha256>", "question_id": "revenue", "answer": "$391,035 million", "value": 391035.0, "unit": "USD_m",
 "status": "extracted", "exact_quote": "Net sales 391,035 Total net sales 391,035", "page": 1,
 "bbox_norm": [0.1176, 0.1880, 0.7067, 0.1993], "rects": [[0.1176, 0.1880, 0.7067, 0.1993]],
 "sha256_span_hash": "<64 hex>", "confidence": 0.9, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0,
 "engine": "extractive", "content_hash": "<64 hex>", "run_id": "run_ab12cd34ef56", "updated_at": "<iso>",
 "flags": [], "extra_citations": [{"page": 2, "bbox_norm": [0, 0, 0, 0], "sha256_span_hash": "<64 hex>", "quote": "..."}]}
```

(`bbox_norm`/`rects` are tuples in Python, arrays in JSON. `value` is the typed value for the column type.)

### Statuses: what the UI shows

| status | meaning | show |
|---|---|---|
| `ok` | engine answer (LLM) whose quote was located | answer + citation (page, highlight) |
| `extracted` | deterministic extractive answer, quote located | answer + citation; the UI may mark it "extracted" |
| `not_found` | the document does not answer, or the evidence was too weak | grey "Not found in document". If flag `low_evidence` is set, the cell may carry a `suggestion` in the engine output; it is **not** stored as an answer, never display it as one |
| `unverified` | the engine gave an answer whose quote could not be located (flags `unverified:quote_not_located` / `unverified:no_quote`) | amber "Needs review"; the answer text is empty in every read, **never show the raw answer** (exports show "Needs review" too) |
| `error` | the engine raised; flag `error:<Type>: ...` | red retry badge; the cell is retried by the next run |
| `skipped` | run condition not met; flag `condition_not_met:<qid> <op> <value>` | grey "Skipped (condition)"; counts as filled |
| (no cell) | pending | spinner / empty |

Flags: `page_corrected:<old>` (the engine's page was wrong, the quote exists on exactly one other page; the cell is still
verified, show a small info badge), `condition_not_met:...`, `low_evidence`, `unverified:...`, `error:...`. Unknown flags
must be ignored. Filled statuses are `ok`, `extracted`, `not_found`, `skipped`; `unverified` and `error` rerun.

### Columns, variables, conditions, follow-ups

- Variables: `set_variable(g, "topic", "...")`, then `{{var:topic}}` in a column's text or instructions. An undefined
  variable raises `ValueError` at estimate/run time. Editing a value reruns only the columns that use it.
- Follow-up column: `{{col:qid}}` inserts the same row's upstream answer and quote; changes cascade only downstream.
  Columns run in topological waves; cycles and unknown refs raise `ValueError` (at create/add/update).
- Run condition: question key `"condition": {"column": qid, "op": OP, "value": v}` against the same row's upstream cell.
  `OP` is one of `eq ne contains not_contains gt gte lt lte exists not_found is_true is_false` (the last four take no `value`).
  Not met: status `skipped`, empty answer.
- `workflow_graph`: nodes `{"id","label","type":"column"|"variable"}` (variables have id `var:<name>`), edges
  `{"from","to","kind"}`, `order` = a valid run order.

### Cost estimate, budget, run stream

`estimate()` is free and exact about what would compute (unchanged cells are not counted). `run_stream(...,
max_cost_usd=x)` yields the estimate first and then raises `BudgetExceeded` (nothing was run) if it is above `x`; map it to
HTTP 402 with the estimate. Events, in order:

```json
{"type": "estimate", "pending_cells": 4, "est_cost_usd": 0.0, "...": "as above"}
{"type": "cell", "cell": {"...": "cell dict without raw_answer; already written to the DB"}}
{"type": "skipped", "reason": "unchanged", "count": 6}
{"type": "done", "run_id": "run_...", "engine": "extractive", "touched": [["<doc_id>", "revenue"]], "skipped": 6,
 "stats": {"extracted": 3, "not_found": 1}, "elapsed_s": 0.1, "first_cell_s": 0.01,
 "actual_cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0, "estimate": {"...": "..."}}
```

`cell` events arrive in completion order (not row order): place each by `(doc_id, question_id)`. `skipped` is emitted only
when count > 0. `first_cell_s` (also in `runs()`) is the first-cell latency telemetry (parity item 1: under 10 s).
Cancellation: close the generator (stop iterating); cells already yielded are saved, the rest stay pending, no `done`
event or `runs()` row is written for a closed stream.

Incremental semantics: a cell's `content_hash` = sha256(doc_id, resolved question text, type, instructions, engine id,
`ENGINE_VERSION`, plus a digest of its upstream cells and condition). A cell recomputes only when it is missing, its hash
changed, or its status is `unverified`/`error`. Not rerun: rename, reorder, adding a row or a column (only the new
cells compute), a rerun with nothing changed. Rerun: a text/type/instructions edit of that column, a variable edit (users
only), an upstream cell change (downstream only), a per-column engine swap (that column only). `questions=[qid,...]` and
`docs=[doc_id,...]` restrict a run (and an estimate) to those columns / rows (bulk run); ids not in the grid raise `KeyError`.

### Cell -> citation -> highlight

A citation is `(doc_id, page, bbox_norm, rects, sha256_span_hash, exact_quote)`. `page` is 1-based. `bbox_norm` is
`[x0, y0, x1, y1]` normalised to `[0, 1]` against the page, **origin top-left, y grows downward** (not the PDF
bottom-left origin). `rects` is one such box per text line of the quote (use it for the highlight, so wrapped quotes do not
paint the whole block; fall back to `bbox_norm` when empty). `sha256_span_hash` fingerprints the located span (the same
span always hashes the same); use it as the stable citation id and to detect a changed document.

To render: show page `page` of the PDF (any renderer, e.g. pdf.js or a server PNG at a known `width_px x height_px`) and
draw each rect at `left = x0 * width_px`, `top = y0 * height_px`, `width = (x1 - x0) * width_px`, `height = (y1 - y0) *
height_px`; scroll it into view (parity items 15-16). `exact_quote` goes in the hover preview (item 15). Extra evidence is
in `extra_citations` (same fields with `bbox_norm`, no `rects`). Only `ok`/`extracted` cells have a citation. Documents
with unreliable text layers: `docparse.parse(...).incomplete_pages()` lists pages below the completeness guard, and
`add_documents` reports them in `alerts` / `completeness_min`.

### Conditional formatting

`set_format_rules(grid, rules)` replaces the rule list (invalid rules raise `ValueError`). Rule:
`{"id": "weak", "apply_to": "row" | qid, "style": {"fill": "#RRGGBB", "font": "#RRGGBB", "bold": true}, "when": WHEN}`.
`WHEN` = `{"all": [WHEN, ...]}` | `{"any": [WHEN, ...]}` | a condition `{"column": qid, "op": OP, "value": v}` or
`{"field": "status" | "confidence" | "source_folder", "op": OP, "value": v[, "column": qid]}` (status/confidence need a
`column` when the rule applies to a row). `formatted_view()` returns `view()` plus `format_rules`, per row `styles`
(row rule ids), `cell_styles` {qid: ids} and per cell `styles`; the UI looks the ids up in `format_rules[*].style`.

### Transfer, source folders, tables, exports

- `filter_docs(g, when)` + `transfer(g, when, name, copy_questions, copy_cells)` -> new grid with the matching rows
  (same `WHEN` language; copies variables and format rules; recomputed incrementally unless `copy_cells`).
- `source_path` on `add_document(s)` gives each row `source_folder`; `group_by_source` -> `{folder: [doc_id]}` for the
  Document Source column and folder grouping.
- `tables(doc_id)` -> auto-extracted tables (`rows` = list of string lists, `source` "docling" | "pdfdoc"); export with
  `export_tables_xlsx` / `export_tables_csv`. `export_grid_xlsx` writes typed values with a cell note per answered cell
  (page and exact quote), a Sources sheet and a Run log; `not_found`, `unverified`/`error` and `skipped` cells export as
  "Not found", "Needs review", "Skipped (condition)". `export_rows` gives `<qid>`, `<qid>__page`, `__quote`, `__status`,
  `__confidence` per column (value and quote are None unless the cell is shown).

### Matrix Chat

`MatrixChat(store, grid_id, adapter=None, model=None).ask(question, stream=False, max_rows=60)`. It plans
deterministically first (count, list, filter, top-k, sum, average, min, max, median over typed values; folders), retrieves
cells with BM25, then answers: templated without an adapter, or one streamed adapter call. Row citations like `[R12]`
must be in the retrieved context, numbers must come from cited rows or the structured result (otherwise the sentence is
replaced by "[Removed: not supported by the grid]"); only `ok`/`extracted` cells are citable. Events with `stream=True`:

```json
{"type": "plan", "operation": "list", "...": "plan fields", "rows_in_scope": 2, "elapsed_s": 0.0}
{"type": "delta", "text": "1 documents: acme.pdf ($391,035 million) [R1]. "}
{"type": "final", "answer": "...", "citations": [{"row_id": "R1", "doc_id": "...", "doc_name": "acme.pdf",
   "question_id": "revenue", "page": 1, "bbox_norm": [0.1, 0.2, 0.7, 0.3], "sha256_span_hash": "<64 hex>", "quote": "..."}],
 "operation": "list", "plan": {}, "rows_considered": 2, "flags": [], "first_token_s": 0.0, "elapsed_s": 0.0,
 "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
```

`ask(stream=False)` returns the `final` dict without `type`. Flags to surface: `uncited_sentence`, `no_valid_citations`,
`unsupported_number:...`, `invented_row_id:...`, `llm_error:<Type>` (fell back to the exact templated answer). Citations
open the same way as grid cells.

### VDR risk report

`scan_documents(docs, *, expected_periods=None, checklist=DEFAULT_CHECKLIST, locate=None)` and `scan_room(index, rooms,
room_id, ...)` return:

```json
{"findings": [{"id": "<hash>", "type": "change_of_control", "severity": "high", "title": "...", "detail": "...",
               "doc_id": "c1", "doc_name": "contract.pdf", "page": 1, "quote": "<exact substring of the page>",
               "bbox_norm": [0.1, 0.1, 0.9, 0.12], "sha256_span_hash": "<64 hex>", "related": [], "locate_failed": false}],
 "summary": {"by_type": {"missing_period": 0, "...": 0}, "by_severity": {"high": 1}, "documents": 1},
 "coverage": {"periods": {}, "checklist": {"<id>": {"label": "...", "documents": ["..."]}}}}
```

`type` in `missing_period | missing_document | conflicting_figure | change_of_control | covenant | mfn | exclusivity`;
severity `critical | high | medium | low | info`. `docs` items: `{"doc_id","name","pages":[text],"page_items":[(page,text)],
"pdf": path|None}`. Findings on PDFs carry page, `bbox_norm` and `sha256_span_hash` (same coordinate system as grid cells);
`bbox_norm` is `None` with `locate_failed: true` when the span cannot be located (a box is never invented), and
missing-document/period findings have no page. **Callers must omit `locate`** to get the default `om.docparse` locator;
passing `locate=lambda *a: None` (as `om/api/grid.py` currently does) drops every bounding box.

### Runnable examples

Both snippets were run against synthetic PDFs built with `om.pdfwrite.PDFWriter` and `parser_backend="pdfdoc"`
(`make_pdf(company, sales, staff)` below is the three-line helper they share).

```python
from om.pdfwrite import PDFWriter

def make_pdf(company="ACME", sales="391,035", staff="164,000"):
    w = PDFWriter()
    w.page()
    w.text(72, 740, f"{company} Corp Form 10-K", 8)
    w.text(72, 700, "Consolidated Statements of Operations", 14, "Helvetica-Bold")
    w.text(72, 670, "(in millions)       2024      2023", 9)
    w.text(72, 650, "Net sales", 9);       w.text(300, 650, sales, 9);   w.text(400, 650, "383,285", 9)
    w.text(72, 636, "Total net sales", 9); w.text(300, 636, sales, 9);   w.text(400, 636, "383,285", 9)
    w.page()
    w.text(72, 700, f"As of September 28, 2024, the Company had approximately {staff} full-time equivalent employees.", 10)
    w.text(72, 680, "The auditor, Ernst & Young LLP, issued an unqualified opinion on the financial statements.", 10)
    return w.to_bytes()
```

1. Ingest, estimate, budget, stream, incremental rerun, citation:

```python
# Snippet 1: build a grid, estimate, stream a run, render a citation
from om.grid import GridStore, BudgetExceeded

store = GridStore(":memory:", parser_backend="pdfdoc")        # ":memory:" -> use "data/grid.duckdb" in the app
ingest = store.add_documents([("acme/10k.pdf", make_pdf()), ("beta/10k.pdf", make_pdf("BETA", "210,000", "12,500"))],
                             progress=lambda n, total, st: print(f"ingest {n}/{total} {st['name']} {st['status']}"))
doc_ids = [f["doc_id"] for f in ingest["files"] if f["doc_id"]]
gid = store.create_grid("Q3 review", doc_ids, [
    {"id": "revenue", "text": "What were total net sales?", "type": "currency", "label": "Revenue"},
    {"id": "staff", "text": "How many full-time equivalent employees did the company have?", "type": "number"},
])
est = store.estimate(gid)
print("estimate", est["pending_cells"], est["est_cost_usd"])
try:
    for ev in store.run_stream(gid, max_cost_usd=1.00):         # BudgetExceeded is raised right after the estimate event
        if ev["type"] == "cell":
            c = ev["cell"]
            print("cell", c["question_id"], c["status"], repr(c["answer"]), "page", c["page"])
        elif ev["type"] == "done":
            print("done first_cell_s", ev["first_cell_s"], "stats", ev["stats"])
except BudgetExceeded as e:
    print("refused", e)
# Second run: nothing recomputes
done = store.run(gid)
print("rerun touched", len(done["touched"]), "skipped", done["skipped"])
cell = store.cells(gid)[0]
print({k: cell[k] for k in ("status", "page", "bbox_norm", "rects", "sha256_span_hash", "exact_quote")})
print(len(store.runs(gid)), "runs logged")
```

2. Columns, variables, follow-ups, conditions, rules, transfer, exports:

```python
# Snippet 2: columns, variables, follow-ups, conditions, rules, transfer, exports, tables
import os, tempfile
from om.grid import GridStore
from om.grid_export import export_grid_xlsx, export_tables_xlsx, export_tables_csv

store = GridStore(os.path.join(tempfile.mkdtemp(), "grid.sqlite"), backend="sqlite", parser_backend="pdfdoc")
a = store.add_document(make_pdf(), name="acme.pdf", source_path="Financials/acme.pdf")
b = store.add_document(make_pdf("BETA", "210,000", "12,500"), name="beta.pdf", source_path="Legal/beta.pdf")
gid = store.create_grid("Review", [a], [{"id": "rev", "text": "What were total net sales?", "type": "currency"}])
store.add_rows(gid, [b])                                           # add a row (idempotent)
store.set_variable(gid, "topic", "full-time equivalent employees")
store.add_questions(gid, [
    {"id": "staff", "text": "How many {{var:topic}} did the company have?", "type": "number"},
    {"id": "audit", "text": "Who is the auditor? Revenue was {{col:rev}}", "condition": {"column": "rev", "op": "exists"}},
])
store.rename_question(gid, "rev", "Revenue (USDm)")                # label only, nothing reruns
store.reorder_questions(gid, ["staff", "rev", "audit"])
store.set_question_engine(gid, "audit", "extractive")              # "llm" / "llm:<model>" / register_engine() name
print(store.workflow_graph(gid)["order"])
print(store.run(gid)["stats"])
store.set_variable(gid, "topic", "employees")                      # reruns ONLY the columns that use {{var:topic}}
print(store.run(gid)["touched"])
store.set_format_rules(gid, [{"id": "weak", "apply_to": "row", "style": {"fill": "#FFF2CC"},
                              "when": {"any": [{"field": "confidence", "column": "rev", "op": "lt", "value": 0.5},
                                               {"field": "status", "column": "rev", "op": "ne", "value": "extracted"}]}}])
fv = store.formatted_view(gid)
print(fv["rows"][0]["styles"], fv["rows"][0]["cells"]["rev"]["styles"])
print(store.group_by_source(gid))
legal = store.transfer(gid, {"field": "source_folder", "op": "eq", "value": "Legal"}, "Legal only", copy_cells=True)
print(store.doc_ids(legal) == [b])
out = tempfile.mkdtemp()
xl = export_grid_xlsx(store, gid, os.path.join(out, "grid.xlsx"))
print(len(xl) > 1000, export_tables_csv(store, a, out), len(export_tables_xlsx(store, gid)) > 0)
print(store.export_rows(gid)[0]["rev__page"], len(store.ingest_log()))   # 0: only add_documents logs
```

3. Highlight rectangles, Matrix Chat, VDR scan:

```python
# Snippet 3: citation -> highlight rects, VDR risk scan, Matrix Chat (no adapter = templated, no model call)
import os, tempfile
from om.grid import GridStore
from om.grid_chat import MatrixChat
from om.vdr_risk import scan_documents
from om.docparse import parse

store = GridStore(":memory:", parser_backend="pdfdoc")
d1 = store.add_document(make_pdf(), name="acme.pdf")
d2 = store.add_document(make_pdf("BETA", "210,000", "12,500"), name="beta.pdf")
gid = store.create_grid("Chat", [d1, d2], [{"id": "revenue", "text": "What were total net sales?", "type": "currency", "label": "Revenue"}])
store.run(gid)

def highlight(cell, page_w_px, page_h_px):
    """normalised [0,1], origin TOP-LEFT, y down -> CSS pixels on the rendered page image."""
    if cell["status"] not in ("ok", "extracted"):
        return []                                   # never highlight (or show) anything else
    return [{"left": x0 * page_w_px, "top": y0 * page_h_px, "width": (x1 - x0) * page_w_px, "height": (y1 - y0) * page_h_px}
            for x0, y0, x1, y1 in (cell["rects"] or [cell["bbox_norm"]])]
print(highlight(store.cells(gid)[0], 612, 792)[0])

chat = MatrixChat(store, gid)
final = chat.ask("Which documents have revenue above 300000?")
print(final["operation"], "|", final["answer"], "|", [c["doc_name"] for c in final["citations"]])
print([ev["type"] for ev in chat.ask("What is the average revenue?", stream=True)])

tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "contract.pdf")
from om.pdfwrite import PDFWriter
w = PDFWriter(); w.page()
w.text(72, 700, "This agreement may be terminated upon a change of control of the Company without notice.", 10)
open(path, "wb").write(w.to_bytes())
pages = [p.raw_text for p in parse(path, backend="pdfdoc").pages]
rep = scan_documents([{"doc_id": "c1", "name": "contract.pdf", "pages": pages, "page_items": list(enumerate(pages, 1)), "pdf": path}])
print(rep["summary"]["by_type"]["change_of_control"], [(f["type"], f["page"], f["bbox_norm"] is not None) for f in rep["findings"] if f["type"] == "change_of_control"])
```

### Parity map (docs/parity-spec.md)

| Item | Served by |
|---|---|
| 1 cited answers stream, first cells < 10 s | `add_questions` + `run_stream` (`cell` events, `first_cell_s`) |
| 2 two-step creation wizard | `add_documents` (step 1), `create_grid` / `add_questions` (step 2); the splitting of one question into columns is a UI/LLM step, no engine call |
| 3 run condition skips rows visibly | question `condition`; status `skipped` + flag `condition_not_met` |
| 4 variable edit reruns dependents | `set_variable` + `run` |
| 5 Column Manager | `rename_question`, `reorder_questions`, `update_question`, `set_question_engine`, `delete_question`, bulk `run(questions=, docs=)` |
| 6 Workflow View | `workflow_graph` |
| 7 conditional formatting AND/OR | `set_format_rules`, `formatted_view` |
| 8 transfer filtered documents | `filter_docs`, `transfer` (to a new Matrix; "to a Chat" = `MatrixChat` on the new grid) |
| 9 Document Source column | `add_document(s)(source_path=)`, `source_folder`, `group_by_source` |
| 10 Excel export, logo | `export_grid_xlsx(logo_png=)` |
| 11 Matrix Chat over 1,000+ rows | `MatrixChat.ask` (first-token telemetry `first_token_s`) |
| 12 500-row grid at 60 fps | client-side (virtualised table over `view`); no engine call |
| 13 100-file upload with status | `add_documents(progress=)`, `ingest_log`, `alerts` |
| 14 PDF tables exportable | `tables`, `export_tables_xlsx`, `export_tables_csv` |
| 15 hover preview < 0.5 s | cell `exact_quote` + page/rects in the `view` payload (no extra call) |
| 16 click opens scrolled highlight | `page` + `rects` (coordinate rules above) |
| 17 trace a figure in < 2 min | cell citation + `export_grid_xlsx` Sources sheet and cell notes |

### Concurrency, storage, scoping

- One `GridStore` per thread/process. The DB connection never leaves the thread that created it; parsing and engines run in
  worker threads inside `add_documents` / `run_stream`, but every DB write happens on the calling thread. Consume
  `run_stream` on the thread that owns the store (a web server runs it in a dedicated worker or per-request store).
- DuckDB file when `duckdb` is importable (`GridStore("data/grid.duckdb")`), else a SQLite file at the same path
  (`backend="sqlite"` forces it). Both use the same SQL; do not open one file with both backends. Two processes must not
  write one file.
- Parsed documents are cached in the same file (`documents.parsed_json`, plus `pages` and `lines`), keyed by the sha256
  of the bytes, and in memory per store; the same file is never reparsed. PDF bytes themselves are not stored: keep the
  original (the highlight needs it) under your own file store keyed by `doc_id`.
- There is no org scoping inside `GridStore`: the product app must keep one store file per org (for example
  `storage/<org_id>/grid.duckdb`) and check access before calling it.
- No model call happens unless a column uses `"llm"` / `"llm:<model>"` (through `src/harness/adapter.py`) or
  `MatrixChat` has an adapter. Documents are data, never instructions.

### Recommended HTTP surface (for the product-app session; not implemented here)

| Route | Call |
|---|---|
| `POST /v1/grids` `{name, doc_ids, questions}` | `create_grid` |
| `GET /v1/grids`, `GET /v1/grids/{id}` | `grid_names`, `formatted_view` (+ `variables`, `workflow_graph`) |
| `POST /v1/docs` (multipart, many files) | `add_documents`, returns the batch dict; progress over SSE or polling `ingest_log` |
| `POST /v1/grids/{id}/rows` | `add_rows` |
| `POST /v1/grids/{id}/columns`; `PATCH`/`DELETE .../columns/{qid}` | `add_questions`; `update_question` / `rename_question` / `set_question_engine`; `delete_question` |
| `POST /v1/grids/{id}/columns/order` | `reorder_questions` |
| `PUT /v1/grids/{id}/variables/{name}` | `set_variable` |
| `PUT /v1/grids/{id}/format-rules` | `set_format_rules` |
| `POST /v1/grids/{id}/estimate` `{questions?, docs?, engine?}` | `estimate` |
| `POST /v1/grids/{id}/run` `{questions?, docs?, engine?, max_cost_usd?}` | `run_stream` as SSE: `event: estimate\|cell\|skipped\|done`, `data:` the event JSON; `BudgetExceeded` -> 402 with the estimate; client disconnect closes the generator |
| `GET /v1/grids/{id}/runs` | `runs` |
| `POST /v1/grids/{id}/transfer` `{when, name, copy_cells?}` | `transfer` |
| `POST /v1/grids/{id}/chat` `{question, stream?}` | `MatrixChat.ask`, SSE `plan\|delta\|final` |
| `GET /v1/grids/{id}/export.xlsx` | `export_grid_xlsx` |
| `GET /v1/docs/{doc_id}/tables.xlsx`, `.../tables/csv` | `export_tables_xlsx`, `export_tables_csv` |
| `GET /v1/docs/{doc_id}/pdf` | the original bytes (your file store) |
| `POST /v1/rooms/{id}/risk` | `scan_room` (omit `locate`) |

`ValueError` / `KeyError` from these calls -> 422 / 404 with the message.

### Stability promise

Within `"v": 1` fields are only added, never renamed or removed: cell fields, event fields, statuses, flags, the
`WHEN`/rule language, `run_stream` event order, `MatrixChat` events and the VDR finding fields. Clients must ignore unknown
fields, flags, statuses and event types. A breaking change bumps `v`. `ENGINE_VERSION` changes are not breaking: they only
trigger recomputation.
