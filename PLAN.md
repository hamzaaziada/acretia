# Acretia — master build plan

The goal is institutional parity with Rogo (Felix, Subset, Offset), Model ML, Shortcut and Daloopa Scout, and then to beat them. Third-party data licensing is excluded: no CapIQ, FactSet or PitchBook feeds. The work covers:

- ingestion and extraction
- depth of financial analysis
- Excel modelling accuracy
- slide and deck fidelity
- reliability of autonomous workflows

This file is the plan. [`PROGRESS.md`](PROGRESS.md) records what is verified, [`DECISIONS.md`](DECISIONS.md) records the choices made, and [`AGENT_LOCK.md`](AGENT_LOCK.md) records who owns what. The operating rules for any agent working here are in [`CLAUDE.md`](CLAUDE.md).

---

## 0. Operating protocol (summary; full text in CLAUDE.md)

**Step 0, before any work**

1. Run `git status` and `git log -n 15 --oneline`.
2. Read `PROGRESS.md` and `DECISIONS.md`.
3. Run `python3 -m unittest discover -s tests -q`.
4. Read `AGENT_LOCK.md`. Claim only unowned packets, write your claim, and commit it before you start.
5. Never redo a packet that `PROGRESS.md` marks ✅ verified.

**Roles**

- **Boss (Opus):**
  - claims milestones and writes Task Packets;
  - writes and runs the independent gate scripts (`scripts/verify_m<N>.py`) and the security review;
  - issues Fix Packets;
  - keeps to under 10% of tokens.
- **Executor (Sonnet subagent):**
  - executes one packet autonomously;
  - reads only targeted line ranges;
  - writes code and unit tests, and runs deterministic checks;
  - self-repairs up to 3 loops;
  - returns the compact Completion Receipt.

**Gates**

- Deterministic checks (formula and AST evaluation, LibreOffice recalculation, schema round-trips, bounding-box geometry) always run before any LLM or vision call.
- A milestone is ✅ only when its `scripts/verify_m<N>.py` exits 0 **and** the full test suite is green.

**Two runtimes**

- **Native offline:**
  - Python 3.10+ standard library only
  - SQLite in WAL mode
  - blobs in `storage/blobs/`
  - LLM replay fixtures
  - our own AST Excel evaluator
- **Docker Compose:**
  - the app
  - headless LibreOffice
  - optional Postgres, Redis, MinIO and DuckDB services behind adapters

Every feature must pass in both runtimes. The offline mode is what CI runs.

**Phone notifications**

- After M5 passes (Feature Review Ready): notify, then carry on into M6.
- After M6 passes (Security Review Passed): notify again.
- Use the Claude Code `PushNotification` tool. It reaches the phone when Remote Control is connected.
- There is no WhatsApp or OpenClaw hook in this environment (see D-007).

---

## 1. Where we start (resume point, 2026-11-16)

Already built and verified in this repo; don't redo:

| Area | What exists | Where |
|---|---|---|
| Data from filings | XBRL fundamentals: LTM, FY, EV bridge, provenance per field | `om/facts.py`, `om/metrics.py`, `om/concepts.py` |
| Full statements | IS / BS / CF for up to 5 fiscal years, source on every number | `om/statements.py` |
| Excel writer/reader | Styled multi-sheet xlsx, comments, links, names, validation, conditional formats, cached values | `om/xlsx.py` |
| Formula engine | Excel-grammar evaluator with iterative circularity; matches LibreOffice on 6,958/6,958 cells | `om/formula.py` |
| 3-statement + DCF | 10-sheet integrated model, scenarios, revolver, circularity breaker, Checks tab | `om/model3.py` |
| Model QA gate | Grades any workbook: errors, checks, balance, signs, constants, consistency, colours, circularity, sources | `om/modelcheck.py` |
| Model benchmark | Builds 6 companies, audit of 10 planted errors (10/10 caught), LibreOffice agreement | `om/bench.py`, `open_multiples.py bench` |
| Consistency checker | Deck vs sources vs workbook, SEC tie-out, room checks | `om/consistency.py` |
| Deck Studio | Storyboard, prompts, SVG designer, slides engine, partner + MD graders, redo | `om/studio.py`, `om/layout.py`, `om/pptx.py`, `om/spacing.py`, `om/grading.py` |
| Research | Full-text search, Matrix (doc × question grid with verified quotes), Ask, data rooms, connectors | `om/search.py`, `om/matrix.py`, `om/ask.py`, `om/rooms.py`, `om/connectors.py` |
| M&A precedents | Fairness-opinion tables from proxies | `om/ma.py` |
| LLM router | Multi-provider, per-stage models, vision, JSON validation, Keychain keys bound to host | `om/llm.py`, `om/keystore.py`, `om/settings.py` |
| Web app | Local server with Host/Origin guard, security headers | `om/web.py`, `om/static/*` |

---

## 2. Milestones

Each milestone is a set of Task Packets (P-ids). Each packet lists its files, contract invariants and exact check commands. Status is tracked in `PROGRESS.md`.

### M1 — Core contracts, two-runtime storage, LLM router, deal memory

| Packet | Scope | Files | Done when |
|---|---|---|---|
| P1.1 | **Contracts** as stdlib dataclasses with `to_dict`/`from_dict`/`validate` and JSON round-trip: `Citation`, `WorkbookGraph`, `ModelSpec`, `ModelManifest`, `SlideSpec`, `SolvedSlideLayout`, `SlideRepairPatch`, `DeckSpec`, `GridSpec`, `GridCell`, `DealMemory`, `Job`, `ValidationReport` | `om/contracts.py`, `tests/test_contracts.py` | Every contract round-trips; invalid input raises with a field path; `Citation.bbox_norm` within [0, 1]; `sha256_span_hash` is 64 hex characters |
| P1.2 | **Storage adapters:** `BlobStore` (local `storage/blobs/`, S3/MinIO via presigned SigV4 using stdlib hmac); `KV/queue` (SQLite, Redis optional); `DB` (SQLite WAL; Postgres DSN accepted for the relational tables that don't use FTS5) | `om/storage.py`, `tests/test_storage.py` | Offline tests pass; the S3 signer matches AWS test vectors |
| P1.3 | **LLM router hardening:** task-type routing (`extraction`, `modeling`, `reasoning`, `vision_critic`) over the existing stages; MeshPool gateway (`https://llm.meshpool.ai/v1`) as the default provider; fallback chain; **PII masking** (emails, phones, IBANs, card numbers, national IDs, person names on request) before every call, with reversible placeholders; **replay fixtures** (record/replay keyed by a prompt hash) for offline CI; per-job token and cost meter | `om/llm.py`, `om/pii.py`, `om/replay.py`, `tests/test_llm_router.py`, `tests/fixtures/llm/*` | Replay mode makes zero network calls; masking round-trips; meter sums per job; the key never leaves its bound host |
| P1.4 | **DealMemory:** a deal/mandate workspace holding firm accounting definitions (Adjusted EBITDA, Net Debt), formatting preferences and a versioned deliverable history with inspectable diffs and undo | `om/deals.py`, `tests/test_deal_memory.py` | Version diff of workbook cells and deck text; undo restores the bytes exactly |
| Gate | `scripts/verify_m1.py` | | Schema round-trips, replay + PII checks, DealMemory diffs, adversarial inputs |

### M2 — Messy PDF, footnote and chart ingestion; bulk VDR grid

| Packet | Scope | Files | Done when |
|---|---|---|---|
| P2.1 | **PDF layer with coordinates.** Optional pdfplumber/pypdfium2; native fallback = `pdftotext -bbox-layout` (poppler). Every word, line and table cell carries `page`, `bbox_norm` and `sha256_span_hash`. OCR fallback (tesseract) when no text layer, flagged | `om/pdfdoc.py`, `tests/test_pdfdoc.py` | 100% of spans have bounds within [0, 1] and a 64-hex hash |
| P2.2 | **Table-structure parser:** ruling lines plus whitespace columns; multi-row headers normalised (merged periods "Three months ended…"); accounting negatives; units ("in millions"); footnote markers linked to footnote text | `om/pdftables.py` | 10-K statement tables parse to period × line-item grids that tie to XBRL within rounding |
| P2.3 | **Chart data extraction:** vector charts (axis labels + bar geometry), with a vision fallback flagged as estimated | `om/pdfcharts.py` | Synthetic bar/line charts recover values within 2% |
| P2.4 | **Concurrent ingestion** of 50+ PDFs (thread pool, content-hash dedupe, resumable) into rooms | `om/rooms.py`, `om/extract.py` | 60 files ingested; a re-run is a no-op |
| P2.5 | **Document Grid** (DuckDB when installed, SQLite otherwise): `GridSpec`/`GridCell` keyed by a content hash; passage-level citations; reuses Matrix | `om/grid.py` | 100-cell 10-K grid: every cell has a citation with page and bbox |
| P2.6 | **VDR gap and risk detector:** missing periods, figures that conflict across documents (reuses `consistency`), covenant / change-of-control / MFN / exclusivity clauses | `om/vdr.py` | A planted-issue room is fully detected; a clean room returns zero high findings |
| Gate | `scripts/verify_m2.py` | | Synthetic messy-PDF corpus plus a 100-cell 10-K grid; bbox bounds, hashes, tie-outs; an opendataloader-bench-style table-recovery score |

### M3 — Institutional Excel engine: build, comprehend, edit, roll forward, audit

| Packet | Scope | Files | Done when |
|---|---|---|---|
| P3.1 | **WorkbookGraph:** parse any xlsx into a cell DAG (precedents/dependents, named ranges, cross-sheet); Ask Mode (read-only Q&A: "why is FCF negative in FY27" gives a trace with drivers); `explain(cell)` | `om/workbook_graph.py` | Traces match a hand-built fixture; handles shared formulas, names, 3D refs |
| P3.2 | **Targeted edits:** an edit plan applied to a copy; downstream recalc; diff; refuse an edit that breaks the checks; preserve styles exactly (round-trip untouched XML parts byte-for-byte) | `om/workbook_edit.py` | Editing one input changes only its dependents; other sheets are byte-identical |
| P3.3 | **Earnings roll-forward:** given a model and a new 10-K/10-Q (XBRL or PDF), map actuals to the Inputs/Filings column, insert a period column, extend the formulas, preserve formatting; Daloopa-style retrofit (match hardcodes to facts, add a link, flag mismatches) | `om/rollforward.py` | 10 public models rolled forward; 10/10 tie; 0 hardcoded calculation cells |
| P3.4 | **Statement depth:** quarterly history; NOL schedule in tax; treasury-stock diluted shares (from option/RSU footnotes); calendarisation to December year-ends; segment revenue build from XBRL dimensions (instance documents) | `om/statements.py`, `om/model3.py`, `om/segments.py` | Tests on fixtures; models still grade 100 |
| P3.5 | **LBO:** sources & uses, multi-tranche debt (revolver, TLA, TLB, senior notes, PIK), mandatory amortisation, cash sweep waterfall, interest circularity breaker, sponsor IRR/MoM (formula-only, no IRR() dependency at the core — closed form plus an XIRR cross-check), returns attribution, entry × exit sensitivity | `om/lbo.py` | Grader 100; independent openpyxl + LibreOffice recalculation agrees |
| P3.6 | **Merger model:** offer price and premium, cash/stock mix, new debt, goodwill and simple purchase-price allocation, synergies with phase-in, accretion/dilution by year, breakeven synergies, contribution analysis | `om/merger.py` | Grader 100; hand-checked fixture |
| P3.7 | **Comps:** trading comps with LTM/NTM calendarisation, treasury-stock dilution, EV-to-equity bridge, NM rules, quartile stats; precedents from `om/ma.py`; football field from all methods | `om/comps.py` (extends `templates.comps`) | Grader 100; values tie to `metrics.py` |
| P3.8 | **ModelManifest export:** every output (KPI, table, chart series) gets an id → sheet/cell/range, units and citation chain | `om/manifest.py` | Manifest validates; every id resolves |
| P3.9 | **Hard QA gate at delivery:** `deliver()` refuses any workbook that fails modelcheck critical graders, has any hardcode in a calculation cell, any error, BS ≠ L+E, or cash not tying (tolerance 1e-6), or where LibreOffice and our evaluator disagree | `om/delivery.py` | Planted-error audit 10/10 plus new plants for LBO/merger |
| Gate | `scripts/verify_m3.py` | | Builds and rolls forward 10 public-company models; inspects every cell via openpyxl (independent reader) + our evaluator + LibreOffice; 10/10 tie-outs; 0 hardcoded calc cells |

### M4 — Consulting-grade deck engine and model-to-deck live sync

| Packet | Scope | Files | Done when |
|---|---|---|---|
| P4.1 | **Firm template and style cloner:** read `.potx`/`.pptx` masters and layouts plus 2–3 sample decks; extract theme colours, fonts, placeholder geometry, table styles, chart palettes, footer/disclaimer rules, tombstone layouts → `HouseProfile` (feeds `om/house.py`) | `om/stylecloner.py` | Round-trip: a deck built from the profile matches the sample's masters; the style diff is empty |
| P4.2 | **Build into the client's own master:** write slides into their layouts and placeholders (keep their master XML) | `om/pptx.py` | Opens in PowerPoint/LibreOffice; layout names preserved |
| P4.3 | **ModelManifest binding:** charts, KPI callouts and comps tables bind to manifest ids; `sync(deck, model)` updates the numbers with no LLM | `om/decksync.py` | Mutate an input → re-sync → every bound number changes; no other bytes change |
| P4.4 | **Archetype library (36):** waterfall, football field, stacked/clustered bar, combo, scatter, comps table, tombstones, timeline, 2×2, process, KPI grid, … as native charts and shapes; correct OpenXML element order | `om/layout.py`, `om/archetypes.py` | Each archetype renders cleanly through LibreOffice; schema-valid |
| P4.5 | **Two-stage visual QA:** a 22-rule deterministic validator (overflow, overlap, margins, WCAG 4.5:1 contrast, min type, density, alignment, title rule, footer rule, page numbers, no eyebrows) **first**, then LibreOffice → PNG → vision critic → `SlideRepairPatch` (max 3) | `om/spacing.py`, `om/deckqa.py` | 0 critical defects across 20 generated decks |
| P4.6 | **Action titles** (Pyramid Principle) and a source footnote on every number-bearing slide | `om/studio.py` | Rubric pass on the 20-deck set |
| Gate | `scripts/verify_m4.py` | | 20 decks generated; manifest mutation → deterministic sync; renders; 0 critical layout, contrast or overflow defects |

### M5 — Autonomous deal workflows ("Felix" mode) and benchmark harness

| Packet | Scope | Files | Done when |
|---|---|---|---|
| P5.1 | **Job runner:** resumable background jobs with steps, retries, per-step cost and latency telemetry, cancellation; SQLite-backed (Redis optional) | `om/jobs.py` | Kill and resume mid-run finishes the job; telemetry is recorded |
| P5.2 | **Pipelines:** CIM + VDR → extract & normalise → spread comps / build 3-statement + LBO → pitchbook / IC memo → hard QA gate → deliver; every step uses gates | `om/pipelines.py` | End-to-end on a synthetic CIM + VDR fixture, offline with replay |
| P5.3 | **IC memo / Word output** (docx writer, stdlib) bound to the manifest | `om/docx.py`, `om/memo.py` | Numbers tie to the model |
| P5.4 | **Eval harness:** `eval/scorecard.csv`: 20 deck briefs, 10 models, a finance-QA subset (FinanceBench-style, local fixtures), 100-cell 10-K grid, table-recovery bench | `eval/`, `om/evals.py` | `EVAL_REPORT.md` generated with pass rates and tokens per deliverable |
| Gate | `scripts/verify_m5.py` | | Full scorecard in offline mode (and in compose mode when Docker is available); 100% of deterministic gates pass |
| Notify | PushNotification: "Feature review ready: <summary of EVAL_REPORT.md>" | | |

### M6 — Security review and hardening (mandatory before sign-off)

| Packet | Scope | Done when |
|---|---|---|
| P6.1 | **Auth and tenancy:** orgs, users, roles (owner/member/viewer); scrypt password hashes; sessions (HttpOnly, SameSite=Strict); every store scoped by `org_id`; local single-user mode only when bound to localhost | Cross-org reads and writes are impossible in tests across SQLite, the blob store and the KV |
| P6.2 | **Untrusted files:** path traversal, ZipSlip, zip bombs (ratio and size caps), XXE (no DTDs or entities), SSRF (connector URLs: allow-list, no private IPs, no redirects to private), LibreOffice run with an isolated profile and timeout | Adversarial fixtures are all rejected |
| P6.3 | **Formula injection:** neutralise `=CMD|`, `=WEBSERVICE`, `=HYPERLINK`, DDE and leading `= + - @` in untrusted text written to cells or CSV | Fixtures neutralised |
| P6.4 | **LLM and secret hygiene:** PII masking enforced on every call; no secrets in the repo or logs (scanner in CI); prompt-injection isolation (untrusted documents fenced as data, tool calls validated) | Scanner clean; injection fixtures can't trigger tools |
| P6.5 | **Deploy hardening:** Dockerfile (non-root, read-only rootfs plus writable volumes), compose, TLS through Caddy, rate limits, security headers, CSP | Container scan passes; headers present |
| Gate | `scripts/verify_security.py` → `SECURITY_REPORT.md` | 0 Critical / High findings |
| Notify | PushNotification: "Security review passed: 0 critical/high. Repo ready for your review." | |

### M7 — Ready to deploy

| Packet | Scope |
|---|---|
| P7.1 | `Dockerfile` (Python 3.12-slim + LibreOffice + poppler + tesseract), `docker-compose.yml` (app, caddy, optional postgres/redis/minio profiles), `.env.example` without secrets, `DEPLOY.md` |
| P7.2 | GitHub Actions CI: offline suite + all verify scripts + secret scan + LibreOffice agreement job |
| P7.3 | `README.md` rewrite: what it does, how to run locally and with Docker, how keys are stored, the benchmark |

---

## 3. Gate script contract (every `scripts/verify_m<N>.py`)

- Written by the Boss, independent of the executor's tests. It uses different code paths where possible, such as openpyxl to read workbooks and LibreOffice to recalculate.
- Exercises real inputs plus adversarial cases. Prints a compact table. Exits non-zero on any failure.
- Never calls a live LLM: replay fixtures only.
- Run in CI.

## 4. Receipt format (executor → boss)

```
### Receipt: [Packet ID]
- **Files Changed:** `path` (created/modified)
- **Checks Run:** `<exact command>` -> `<X passed, 0 failed>`
- **Key Decisions:** <1 line or "None">
- **Ready for Gate:** YES / NO (blocker)
```
