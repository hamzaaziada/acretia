# Acretia — master build plan (v2: architectural pivot, 2026-11-16)

Acretia is a model-agnostic, institutional-grade finance research and deliverables stack. It is built to compete with Hebbia Matrix, Rogo and AlphaSense, and to match Model ML, Shortcut and Daloopa on deliverables. It has five parts:

- vetted open-source components, each entered in a licence ledger
- one Harness and VDR/data router (MCP)
- one OpenAI-compatible model adapter
- deterministic engines for decks, Excel, document grids and research
- a production-grade UI
- adversarial buyer-persona gates

v1 of this plan (M1–M7) is superseded. Its packets are mapped to v2 stages below; nothing verified is redone. [`PROGRESS.md`](PROGRESS.md) is the source of truth for status, [`DECISIONS.md`](DECISIONS.md) for choices, and [`AGENT_LOCK.md`](AGENT_LOCK.md) for file-level claims. The operating rules are in [`CLAUDE.md`](CLAUDE.md).

---

## 0. Ground rules (binding on every packet)

1. **Licence ledger first.** Before adopting, vendoring or borrowing from any repo, inspect its `LICENSE` at a **pinned commit** and add a row to [`license-and-repo-ledger.csv`](license-and-repo-ledger.csv): `repo, commit_hash, license, decision (adopt | borrow_ideas | isolated_service | skip), reason`.
   - MIT, Apache-2.0, BSD and MPL-2.0 may be vendored, forked or used.
   - GPL and AGPL code (Marker, MinerU, and possibly OpenBB modules) may run **only** as an isolated Docker service over HTTP and is never imported into the core.
   - Source-available or proprietary code (such as `anthropics/skills`) is used for ideas only, with zero copied code or text.
2. **One model adapter.** Every LLM and VLM call goes through `src/harness/adapter.py`: OpenAI-compatible chat plus vision, configured with `base_url`, `api_key` and `model_name`, and working with Claude, GPT, Gemini, vLLM, Ollama and the MeshPool gateway (`llm.meshpool.ai`).
   - No provider SDK may be called anywhere else; CI greps for this.
   - The existing `om/llm.py` Router becomes a thin caller of the adapter.
3. **Deterministic code owns layout, font metrics, formulas and validators.** Models only fill structured YAML/JSON specs: archetype ids, action titles, blocks, sources and as-of dates. They never produce coordinates, fonts, colours, formulas or historical numbers.
4. **Evidence bundle.** Every router and tool call appends to an immutable, hash-chained JSONL evidence bundle per job: tool, args hash, source URL or doc id, page, bbox, timestamp and output hash.
5. **Teardown notes** live in `docs/teardowns/<repo>.md`. Each candidate is tested on real sample inputs, and every finding is labelled `[OBSERVATION]`, `[INFERENCE]` or `[UNKNOWN]`.
6. **Deterministic gates before LLM or VLM gates**, always.
7. **Buyer-persona gates.** After Workstreams 1–4 (and the final integration), three Haiku personas grade the milestone's deliverables. Any score below **8.5/10** blocks sign-off and generates targeted Fix Packets (see §6).

## 1. Existing assets to extend (don't rebuild)

| Asset | Where | Use in v2 |
|---|---|---|
| Excel writer/reader, formula evaluator, 3-statement + DCF builder, model grader, model bench (10/10 audit, LibreOffice 6,958/6,958) | `om/xlsx.py`, `om/formula.py`, `om/model3.py`, `om/modelcheck.py`, `om/bench.py` | Core of Workstream 2. `validate_xlsx.py` wraps `om.modelcheck` and adds units, live-sensitivity and Formulon checks |
| Statements and fundamentals from XBRL with provenance | `om/statements.py`, `om/facts.py`, `om/metrics.py` | Data source behind the router, alongside edgartools |
| Deck Studio, layout JSON contract, components, spacing rules, icon library, partner + MD graders | `om/studio.py`, `om/layout.py`, `om/pptx.py`, `om/spacing.py`, `om/grading.py`, `om/icons.py`, `om/house.py` | Workstream 1 extends these. `validate_pptx.py` grows out of `om/spacing.py` |
| Consistency checker (deck vs sources vs workbook, SEC tie-out) | `om/consistency.py` | Shared validator across workstreams |
| Matrix (doc × question, verified quotes), Ask, search, data rooms, connectors | `om/matrix.py`, `om/ask.py`, `om/search.py`, `om/rooms.py`, `om/connectors.py` | Workstream 3 moves the Matrix onto DuckDB with page and bbox |
| Meshpool Harness (user's own, MIT): router rules, model profiles, spend ledger and guard, agent loop, slides engine (python-pptx archetypes, textfit, QA), sheets QA | `reference/meshpool-harness/` | Source for `src/harness/` (router, profiles, ledger) and for deck textfit/QA ideas. See `reference/meshpool-harness/BUILD_SPEC.md` |
| v1 M1 (gated 19/19): contracts, storage adapters, PII masking, LLM replay, DealMemory, router hardening | `om/contracts.py`, `om/storage.py`, `om/pii.py`, `om/replay.py`, `om/deals.py`, `om/llm.py`, `scripts/verify_m1.py` | Stage 2 extends these. Do not re-create them under `src/harness/`; the adapter wraps them |

## 2. Execution order (stages run in sequence; packets inside a stage run in parallel)

Packets in the same stage that don't share files run **concurrently** as parallel Sonnet workers. `AGENT_LOCK.md` is the file-level mutex (see `CLAUDE.md`). Each stage ends with its deterministic gate, then the persona gate where one is marked.

### Stage 1 — Licence ledger, repo teardowns, buyer research

| Packet | Scope | Output |
|---|---|---|
| S1.1 | Ledger for every repo named in this plan. Pin a commit, read the LICENSE, decide. Verify the uncertain ones: docling (MIT?), OpenBB (Aug-2026 licence per module), crawl4ai (Apache-2.0 + attribution), edgartools (MIT), FinanceToolkit (MIT), `anthropics/financial-services` (Apache-2.0?), formulon, Marker (GPL), MinerU (AGPL), presenton, PPTAgent, AutoPresent, SlideCoder, clean-slides, Mck-ppt-design-skill, mbb-ppt-generator, mckinsey-pptx, pptx-mcp-server, swak/pptx-mcp, ginlix-ai pptx skill, python-pptx, PptxGenJS, gpt-researcher, dexter, FinRobot, unstructured, Apache Tika, fonttools, Pillow, arabic-reshaper, python-bidi, duckdb, opendataloader-bench, SpreadsheetBench, FinanceBench, Vals Finance Agent | `license-and-repo-ledger.csv` |
| S1.2 | Deck-engine teardowns: run each candidate on the same 3 sample briefs where it can run; record archetype coverage, layout method, validator rules and output quality | `docs/teardowns/deck-*.md` |
| S1.3 | Excel, grid and research teardowns: `anthropics/financial-services` recipes, formulon, docling vs Marker vs MinerU on 3 messy 10-K/CIM PDFs (bbox fidelity, completeness vs raw page text), gpt-researcher, dexter, FinRobot, edgartools MCP, FinanceToolkit MCP | `docs/teardowns/*.md` |
| S1.4 | Buyer research: real IB, PE and MBB rejection criteria (formatting standards, Excel conventions, IC memo expectations, partner/EM review checklists, WSO/Reddit complaints), all with sources | `docs/buyer-research.md` → personas in §6 |
| Gate | `scripts/verify_s1.py`: every adopted or vendored dependency has a ledger row with a 40-hex commit and a licence; there is no GPL/AGPL import in `src/` or `om/`; every teardown has labelled findings | |

### Stage 2 — Harness and MCP data/VDR router + model-agnostic adapter

v1 M1 is done (see §1): extend `om/contracts.py`, `om/pii.py`, `om/replay.py`, `om/storage.py` and `om/deals.py` rather than duplicating them.

| Packet | Scope | Files |
|---|---|---|
| S2.1 | **Adapter:** OpenAI-compatible chat and vision; retries and fallback chain; streaming; JSON-schema-validated outputs; PII masking (reversible placeholders); replay fixtures (record/replay by prompt hash, zero network in CI); per-job token and cost ledger (port `reference/meshpool-harness/eval/ledger.py`); spend guard; the key is bound to its host | `src/harness/adapter.py`, `src/harness/ledger.py`, `om/llm.py` (reuses `om/pii.py`, `om/replay.py`) |
| S2.2 | **Contracts:** Citation (doc_id, page, bbox_norm, cell_locator, xbrl_concept, sha256_span_hash, url, as_of), EvidenceRecord, WorkbookGraph, ModelSpec, ModelManifest, SlideSpec, GhostDeck, SolvedSlideLayout, SlideRepairPatch, DeckSpec, GridSpec/GridCell, DealMemory, Job, ValidationReport | `om/contracts.py` (extend: EvidenceRecord, GhostDeck, Citation.url/as_of) |
| S2.3 | **Router:** rule-first routing (port `meshpool_harness/router`); task types `extraction`, `modeling`, `reasoning`, `vision_critic`, `persona`; model profiles (claude, openai, gemini, deepseek, glm, kimi, local vLLM/Ollama); tool registry over MCP | `src/harness/router.py`, `src/harness/profiles/` |
| S2.4 | **MCP servers and clients:** an MCP client in the harness, plus MCP servers for the engines: Document Grid (DuckDB), Headless Excel daemon (LibreOffice persistent + `om.formula`), Deck Engine | `src/harness/mcp/` |
| S2.5 | **Connectors:** local, S3 and MinIO data rooms; nested `.zip`/`.msg`/`.eml` unpacking (unstructured or Tika as an isolated service; ZipSlip/bomb-safe); Google Drive and SharePoint (existing `om/connectors.py`); edgartools (MIT) as the primary SEC source next to `om/statements.py`; FinanceToolkit wired to edgartools (not FMP); crawl4ai for IR pages and press releases (robots.txt honoured, rate-limited) | `src/harness/connectors/` |
| S2.6 | **Evidence bundle** (hash-chained JSONL per job) and **DealMemory** (firm accounting definitions, formatting preferences, versioned deliverables with diffs and undo) | `src/harness/evidence.py`, `om/deals.py` (extend) |
| S2.7 | **Storage:** add DuckDB to the existing `om/storage.py` adapters (SQLite WAL, blob store local/S3/MinIO, SQLite/Redis queue) | `om/storage.py` |
| Gate | `scripts/verify_s2.py`: schema round-trips; replay with zero sockets opened (monkeypatched socket); PII round-trip; no provider SDK imports outside the adapter (AST scan); a tamper-evident evidence chain; an MCP tool list and calls over stdio; ZipSlip/XXE fixtures rejected | |

### Stage 3 — Workstream 1: deck engine (priority 1) + deck eval

| Packet | Scope |
|---|---|
| S3.1 | **Ghost deck first:** the storyline as action titles only (Pyramid Principle, ≤15 words, ≤2 lines, numbers included). A horizontal-logic check (title sequence reads as an argument; deterministic lints plus one LLM check), then user approval in the UI before rendering |
| S3.2 | **Spec format:** YAML/JSON SlideSpec with archetype id, action title, structured blocks, source and as-of date. No coordinates, fonts or colours from the model; schema-rejected if present |
| S3.3 | **35+ archetypes:** exec summary, agenda tracker, chart + 3 takeaways, ranked bar, waterfall / EBITDA bridge, stacked bar, annotated line, 2×2, football field, comparison table, Gantt/timeline, process flow, issue tree, market map, KPI row, quote, section divider, comps table, tombstones, … Native charts in python-pptx (MIT) as the primary renderer, with PptxGenJS (MIT) as a scratch fallback only if the ledger and a teardown justify it. Extends `om/layout.py` components and the Meshpool Harness archetypes |
| S3.4 | **Constraint layout engine:** real glyph metrics via fonttools and Pillow. Fit order: reflow → tighten spacing → shrink to the floor (≥10pt body, ≥14pt tables per typography budget) → structured error back to the content step ("body block 2 is 38 words over; cut or split") |
| S3.5 | **Arabic and RTL:** arabic-reshaper + python-bidi for measurement; full mirroring of layouts; OpenXML `rtl="1"` and `algn="r"`; Arabic-capable theme fonts |
| S3.6 | **Anti-slop rules:** 12-column grid (0.02 in snap), ≤4 type sizes, theme-only fonts and colours, 1 accent + greys, ≥15% whitespace. None of: gradients, shadows, 3D, stock icons, rounded card grids, banned filler words (delve, leverage, unlock, game-changer, seamless, robust, "in today's fast-paced", …), em dashes, emojis, exclamation marks |
| S3.7 | **`validate_pptx.py`** (deterministic): measured overflow, overlaps, out of bounds, grid alignment, WCAG 4.5:1 contrast, font floors, type-size count, banned phrases, punctuation rules, XML validity, the user's house rules (title rule, footer rule with page numbers, no eyebrows). Returns shape ids |
| S3.8 | **Vision critic loop:** LibreOffice → PNG → VLM critic through the adapter, naming shape ids → SlideRepairPatch, max 3 loops. Runs only after the validator passes |
| S3.9 | **Firm template cloner and model-to-deck sync:** `.potx`/`.pptx` masters plus 2–3 sample decks → house profile; build into the client's layouts; charts, KPIs and tables bound to ModelManifest ids; re-sync with no LLM |
| S3.10 | **Deck eval:** 20 real finance briefs, 3 of them in Arabic, × 2 frontier models + 1 open-weight model through the adapter; benchmark against Presenton, PPTAgent (PPTEval rubric) and SlidesBench. Results go to `scorecard.csv` |
| Gate | `scripts/verify_s3.py` (all 20 decks: 0 critical validator defects; sync mutation test; Arabic RTL checks), then **persona gate** (EM + PE + Analyst ≥ 8.5) |

### Stage 4 — Workstream 2: Excel engine

| Packet | Scope |
|---|---|
| S4.1 | **`validate_xlsx.py`:** wraps `om.modelcheck` and adds unit consistency (a $m vs $bn mix), live sensitivity tables (no `{=TABLE}`; every grid cell a formula), green cross-sheet links (required, not just reported) and circular-reference policy |
| S4.2 | **Dual recalculation:** persistent LibreOffice headless daemon (MPL-2.0) after every write; formulon (Apache-2.0, if the ledger confirms) as a second engine; plus `om.formula`. Any divergence is flagged with cells |
| S4.3 | **Recipes:** comps, DCF, LBO, 3-statement, merger, following `anthropics/financial-services` (Apache-2.0, verify) structure where it adds; data from edgartools + FinanceToolkit + `om.statements`. Existing `om/model3.py` stays the 3-statement core; new: `om/lbo.py`, `om/merger.py`, `om/comps.py` (TSM, calendarisation, NTM where estimates exist) |
| S4.4 | **WorkbookGraph, Ask mode, targeted edits, earnings roll-forward** (v1 P3.1–P3.3) |
| S4.5 | **ModelManifest export and the hard delivery gate** (v1 P3.8–P3.9) |
| S4.6 | **SpreadsheetBench eval** (public subset, licence permitting) + the existing OM-Bench (10 public companies, planted-error audit) |
| Gate | `scripts/verify_s4.py` (10/10 models tie, 0 hardcoded calc cells, three-engine agreement, audit ≥ 10/10), then **persona gate** |

### Stage 5 — Workstream 3: document matrix grid (Hebbia-style)

| Packet | Scope |
|---|---|
| S5.1 | **Parser:** docling (verify MIT) by default, keeping pages and exact bboxes; a completeness check against raw page text (pdftotext) so dropped layouts are detected; Marker and MinerU as optional isolated services only |
| S5.2 | **DuckDB Matrix:** rows are documents, columns are diligence questions, cells are `{answer, exact_quote, page, bbox, confidence, cost}`; parallel cell execution; pre-run cost estimate; incremental reruns (new rows or columns only); migrate `om/matrix.py` |
| S5.3 | **VDR gap and risk detector:** missing periods, conflicting figures (via `om.consistency`), change-of-control, covenants, MFN, exclusivity |
| S5.4 | **Evals:** opendataloader-bench (table and structure recovery) + 10-K QA (100 cells with gold answers, quotes and pages) |
| Gate | `scripts/verify_s5.py` (bbox_norm within [0, 1] for 100% of cells, quote found on the cited page, completeness ≥ threshold, incremental rerun touches only new cells), then **persona gate** |

### Stage 6 — Workstream 4: research agent

| Packet | Scope |
|---|---|
| S6.1 | **Research agent:** gpt-researcher (Apache-2.0) as the base, dexter (MIT) task planning with self-reflection and a source-logged scratchpad, FinRobot report structures; all tools through the harness router (edgartools, FinanceToolkit, crawl4ai, Matrix, Excel daemon) |
| S6.2 | **Outputs:** only SlideSpecs and Excel input payloads, never free prose. Any figure without a verifiable source and as-of date is rejected |
| S6.3 | **Evals:** Vals Finance Agent (50 public questions) + FinanceBench subset, scored with evidence |
| Gate | `scripts/verify_s6.py` (0 unsourced figures, eval pass rates recorded), then **persona gate** |

### Stage 7 — Production UI, security review, Docker and CI

| Packet | Scope |
|---|---|
| S7.1 | **Split-pane document and citation inspector:** click any Matrix cell, slide source line or Excel input to jump to the highlighted bbox on the PDF page (pdf.js, Apache-2.0, vendored and pinned in the ledger) |
| S7.2 | **Interactive Matrix grid:** add rows and columns, live cost estimate, streamed cell results |
| S7.3 | **Deck and model workbench:** approve or edit the ghost deck, slide previews with `validate_pptx` badges, Excel audit view (blue/black/green, three-engine check status) |
| S7.4 | **Security review** (v1 M6): tenancy/RBAC, ZipSlip/XXE/SSRF/zip bombs, formula injection, LibreOffice isolation, PII on every LLM call, secret scan, prompt-injection isolation for VDR documents → `SECURITY_REPORT.md` with 0 Critical/High |
| S7.5 | **Docker and CI** (v1 M7): Dockerfile (non-root, LibreOffice, poppler, tesseract), compose (app, Caddy, optional postgres/redis/minio, isolated GPL services), GitHub Actions (offline suite, all verify scripts, ledger check, secret scan), `DEPLOY.md`, README |
| Gate | `scripts/verify_s7.py` + `scripts/verify_security.py`, then the final **persona gate** on an end-to-end deal run (CIM + VDR → Matrix → model → deck → memo) |

## 3. Acceptance audit (before concluding)

Mark every acceptance criterion in §2 as `MET`, `PARTLY MET` or `NOT MET` in `ACCEPTANCE.md`. Include the evidence (command and result), `scorecard.csv`, and a list of open questions.

## 4. Notifications

- When the S3–S6 gates have passed and the S7 UI is integrated: "feature review ready" plus a summary of `scorecard.csv`.
- When the security review is clean: a second notification.
- Both use the Claude Code PushNotification tool (D-007, D-021). If a notification can't be delivered, record that in `PROGRESS.md`.

## 5. Receipt format (worker → boss)

```
### Receipt: [Packet ID]
- **Files Changed:** `path` (created/modified)
- **Checks Run:** `<exact command>` -> `<X passed, 0 failed>`
- **Key Decisions:** <1 line or "None">
- **Ready for Gate:** YES / NO (blocker)
```

## 6. Buyer personas (Haiku gates)

Refine from `docs/buyer-research.md` in S1.4. Each persona returns per-criterion scores, an overall score out of 10, blocking issues (with shape, cell or document locators) and "would pay $10K+/seat? yes/no + why". Below 8.5 means blocked: the Boss turns the blocking issues into Fix Packets.

- **Goldman / Morgan Stanley IB analyst:**
  - Excel linking and formula conventions (blue/black/green, no hardcodes, consistent rows, checks tab)
  - model navigability and speed (named ranges, layout, freeze panes, print setup)
  - zero-error tolerance (any #REF!, an unbalanced BS or untied cash = fail)
- **McKinsey / Bain engagement manager:**
  - storyline logic of the action titles (pyramid, horizontal flow)
  - one message per slide
  - grid discipline and whitespace
  - chart clarity (right chart for the message, labelled, sourced)
  - anti-slop polish
  - house rules (title rule, footer rule with page number, no eyebrows)
- **PE principal / investment committee:**
  - every figure traceable to a highlighted bbox
  - VDR completeness (gaps flagged)
  - risk coverage
  - IC-memo structure
  - would they pay $10K+/seat for this exact deliverable?
