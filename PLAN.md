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

## North star: the product (read this first)

Acretia ships as a **production-level product that does what Rogo's Felix does, and beats it**. The engines (stages S1–S6, S8) exist to serve this product, and it is judged by what a banker experiences:

1. They open the app (or email it) and ask in plain language: "spread trading comps for ElSewedy vs GCC cable peers and add a football field".
2. An agent plans the work, shows its steps and cost live, and pulls filings, the VDR and the firm's own files.
3. It returns **finished deliverables** within minutes: Excel in the firm's conventions, slides in the firm's template, an IC memo. Every number links to the highlighted source.
4. The banker comments ("make slide 4 a waterfall", "use 9% WACC") and the agent edits in place, with versions and undo.
5. When new earnings land, the model and deck roll forward by themselves and the user is told.

### User journeys = product acceptance tests (P-J1 … P-J8)

Each journey is scripted as an end-to-end browser test (Playwright, Apache-2.0, ledger row) running against the real app. The Haiku personas also judge it from screenshots and outputs.

| Journey | The user does | They get (acceptance) |
|---|---|---|
| P-J1 Ask | Types a request in the command bar (or sends it by email) | A live plan with steps, sources, cost and time; deliverables delivered to the deal's library; p50 under 5 min for comps or a profile deck |
| P-J2 Deal workspace | Creates a deal, drops a VDR zip (50+ PDFs, some scanned or Arabic) | Documents indexed with progress; diligence matrix with cost estimate; gaps and risks flagged; every cell clickable to its bbox |
| P-J3 Model | "3-statement + DCF for X" (US XBRL or an annual-report PDF) | A graded, tied Excel model; assumptions editable in the UI with live recompute; download; audit view (blue/black/green, three-engine check) |
| P-J4 Deck | "Pitch book / IC memo from this model and grid" | Ghost-deck approval, then rendered slides in the firm template with validator badges; comment-to-edit annotator; versions and diffs; model→deck sync |
| P-J5 Earnings update | A new filing arrives (or the user triggers it) | Model rolled forward, deck refreshed, diff shown, notification sent |
| P-J6 Trust | Clicks any number in a slide, Excel cell, memo or grid | Split-pane PDF with the exact span highlighted, plus page, as-of date and source link |
| P-J7 Firm setup | An admin uploads templates and sample decks, defines Adjusted EBITDA and Net Debt, adds users and roles, connects SharePoint/Drive/VDR | House style cloned and applied everywhere; definitions used in every model; RBAC enforced |
| P-J8 Agent library | Picks a pre-built agent (comps, DCF, LBO, merger, CIM summary, teaser, buyer list, earnings recap, IC memo) or saves their own prompt chain | Repeatable runs, shareable within the org, run history |

### North-star metrics: claims we must be able to defend (goal: Hebbia/Rogo parity)

We claim what Rogo and Hebbia claim, time saved, reliability and usefulness, **only when measured**.

1. **Time-saved benchmark (TSB).** For each catalogue task:
   - **Catalogue tasks:**
     - trading comps
     - precedents
     - 3-statement from 10-K or annual report
     - DCF
     - LBO
     - merger model
     - CIM / VDR first-pass review (per 50 docs)
     - company profile / one-pager
     - pitchbook section
     - teaser
     - IC memo
     - earnings model update
     - earnings recap
     - buyer list
   - **Measure** `T_h`, the human baseline: sourced ranges in `docs/time-saved-baselines.md`, later validated with timed analysts.
   - **Measure** `T_a` = wall-clock to deliverable + review-and-fix time to client-ready.
   - **Client-ready** means: every deterministic gate passes, the personas score ≥ 8.5, and the remaining edits are logged.
   - **Review-and-fix time:** first estimated from the persona's "edits needed" list × a published minutes-per-edit table, then replaced by real reviewer timings from a pilot of 3–5 analysts.
   - **Report** `1 − T_a/T_h` per task (median, IQR, n ≥ 10 companies or briefs) in `eval/tsb/report.md`.
   - **Claim** a figure only when it is human-validated and at or above the published competitor claim for that task (sources in the baselines doc).
2. **Reliability SLOs**, on scripted runs of every journey across ≥ 100 varied companies and briefs (US, IFRS, MENA):
   - task success ≥ 97%;
   - **zero silent wrong numbers**: every figure is either tied to a source or flagged;
   - identical inputs give identical numbers (the data layer is deterministic);
   - 100% of failed jobs resume cleanly;
   - p95 latency and cost per deliverable published.
3. **Usefulness.** The whole catalogue runs end to end from the command bar and the agent library. The PE-principal persona says "would pay $10K+/seat" on each deliverable type.

**Ownership:**
- the product session builds the TSB/reliability harness (`eval/tsb/`, job telemetry);
- live measurement runs on the user's Mac with the Keychain key (D-021);
- the independent reviewer re-checks the numbers before any claim.

**Production bar:**
- multi-tenant auth with roles; audit log of every action and agent step;
- streamed progress; cost shown per task; resumable jobs; notifications;
- fast, dense, institutional UI with keyboard shortcuts; accessible (WCAG AA); English/Arabic UI with RTL;
- no dead ends: every error says what to do next.

---

## 0. Ground rules (binding on every packet)

1. **Licence ledger first.** Before adopting, vendoring or borrowing from any repo, inspect its `LICENSE` at a **pinned commit** and add a row to [`license-and-repo-ledger.csv`](license-and-repo-ledger.csv): `repo, commit_hash, license, decision (adopt | borrow_ideas | isolated_service | skip), reason`.
   - MIT, Apache-2.0, BSD and MPL-2.0 may be vendored, forked or used.
   - GPL and AGPL code (Marker, MinerU, and possibly OpenBB modules) may run **only** as an isolated Docker service over HTTP and is never imported into the core.
   - Source-available or proprietary code (such as `anthropics/skills`) is used for ideas only, with zero copied code or text.
2. **One model adapter.** Every LLM and VLM call goes through `src/harness/adapter.py`: OpenAI-compatible chat plus vision, configured with `base_url`, `api_key` and `model_name`, and working with Claude, GPT, Gemini, vLLM, Ollama and the MeshPool gateway (`llm.meshpool.ai`).
   - No provider SDK may be called anywhere else; CI greps for this.
   - The existing `om/llm.py` Router becomes a thin caller of the adapter.
3. **Generative creativity, deterministic polish.** Models choose the story, the visual concept and the art direction, and they generate the artwork. This is deliberately non-deterministic, so quality can be measured and improved run over run (see S3.11).
   - Deterministic code owns everything a buyer checks: layout geometry and the grid, font metrics, contrast, overflow, formulas, numbers and charts.
   - Models never produce coordinates, fonts, colours, formulas or historical numbers. Data charts are always native and bound to the model, never images.
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
| S3.11 | **Creative visual layer: varied, generated, never rubber-stamped.**<br>• **Art direction per deck:** chosen from a growing library of visual languages: editorial illustration, isometric systems, line-art schematics, data-art, duotone photo-style heroes, annotated maps, iconographic systems, bold typographic slides.<br>• **Several candidates per non-data visual (default 3), generated non-deterministically.** Use the image model when its endpoint answers; probe at startup and on every run, and use it whenever it works. Otherwise use the SVG designer (`om/images.py` SvgImages) through the adapter. The VLM critic and the validators score the candidates and the best one is kept.<br>• **Variety rules, enforced deterministically:**<br>  – no two consecutive slides share an archetype and visual type;<br>  – at least 5 distinct visual types per 10 slides;<br>  – a layout-signature similarity detector flags any deck that looks templated.<br>• **Learning loop:** log the critic, persona and validator scores for each style and prompt; prefer winners and retire losers, so the visual library improves with every run. Visuals must still pass `validate_pptx.py` and the persona gates: ultra-polished, not decorative noise |
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
| S4.7 | **Excel visual polish at banker grade:**<br>• a cover/dashboard sheet with native Excel charts (bridge, football field, revenue/EBITDA trend) bound to model cells;<br>• consistent named cell styles;<br>• print setup (fit to width, repeat titles, headers and footers with source);<br>• column grouping for historicals and projections;<br>• zero visual noise (no merged cells in calculation areas, gridlines off, aligned decimals).<br>The IB persona grades polish as a blocking criterion |
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
| S6.3 | **Evals:** Vals Finance Agent v1 public set (50 questions) and v2 where public, the FinanceBench subset, and BankerToolBench tasks where public (ICLR 2026; 502-banker rubric; frontier models scored 0% client-ready), all scored with evidence. Also the Wall Street Prep Apple 3-statement task (same prompt) through S4 |
| Gate | `scripts/verify_s6.py` (0 unsourced figures, eval pass rates recorded), then **persona gate** |

### Stage 7 — The product app (session F) + security review, Docker and CI (session A)

The product app (P-J1–P-J8 above) is built by session F, starting now: the shell first, then each engine plugged in as it lands on main. S7.4–S7.5 (security, Docker, CI) stay with session A. S7.1–S7.3 below are part of the product app.

| Packet | Scope |
|---|---|
| S7.1 | **Split-pane document and citation inspector:** click any Matrix cell, slide source line or Excel input to jump to the highlighted bbox on the PDF page (pdf.js, Apache-2.0, vendored and pinned in the ledger) |
| S7.2 | **Interactive Matrix grid:** add rows and columns, live cost estimate, streamed cell results |
| S7.3 | **Deck and model workbench:** approve or edit the ghost deck, slide previews with `validate_pptx` badges, Excel audit view (blue/black/green, three-engine check status) |
| S7.4 | **Security review** (v1 M6): tenancy/RBAC, ZipSlip/XXE/SSRF/zip bombs, formula injection, LibreOffice isolation, PII on every LLM call, secret scan, prompt-injection isolation for VDR documents → `SECURITY_REPORT.md` with 0 Critical/High |
| S7.5 | **Docker and CI** (v1 M7): Dockerfile (non-root, LibreOffice, poppler, tesseract), compose (app, Caddy, optional postgres/redis/minio, isolated GPL services), GitHub Actions (offline suite, all verify scripts, ledger check, secret scan), `DEPLOY.md`, README |
| Gate | `scripts/verify_s7.py` + `scripts/verify_security.py`, then the final **persona gate** on an end-to-end deal run (CIM + VDR → Matrix → model → deck → memo) |

### Stage 8 — International accounting and unstructured financials (non-US, MENA-first)

Acretia must be as fluent outside the US as inside it: IFRS, Egyptian Accounting Standards (EAS), Saudi IFRS as endorsed by SOCPA, UAE/GCC IFRS, UK FRS 102, Indian Ind AS and others, as well as US GAAP. It must also turn messy, often scanned, often Arabic annual reports into the same tied, sourced statements that SEC XBRL gives us today.

| Packet | Scope |
|---|---|
| S8.0 | **Order and anchor companies (user direction).** IFRS first: full depth on IFRS presentation, measurement and disclosures. Then the local variants: Egyptian EAS, SOCPA-endorsed IFRS (KSA), UAE IFRS. The engine must *understand what these companies' statements actually look like*. Anchor set, non-financial and listed:<br>• **Egypt (EGX):** Elsewedy Electric (SWDY), Eastern Company (EAST), Talaat Moustafa Group (TMGH)<br>• **Saudi Arabia (Tadawul):** Almarai (2280), Jarir Marketing (4190), SABIC (2010)<br>• **UAE (DFM/ADX):** Emaar Properties (EMAAR), ADNOC Distribution (ADNOCDIST), Aldar Properties (ALDAR)<br>For each: the latest two annual audited financial statements **and** the latest quarterly earnings releases or investor presentations. Use them to (a) extract full IS/BS/CF with citations; (b) check that the earnings-release figures tie to the statements and explain every difference (adjusted vs reported, segment vs group, restatements); (c) write a per-company "how to read these statements" note: framework, layout quirks, non-standard line items, zakat or tax, IFRS 16, FX/devaluation, related parties, units, fiscal year; (d) answer 10 analyst questions per company with cited answers. Store facts, notes and links; commit source PDFs only where the publisher's terms allow, otherwise record URL + sha256 |
| S8.1 | **Accounting-standards knowledge base** (`om/intl/standards/`, YAML + docs; written in our own words, sources cited, no copied standard text). For each framework: statement layouts (function vs nature P&L, current/non-current ordering, OCI), required line items, and the key differences from US GAAP and IFRS: leases (IFRS 16 vs ASC 842 vs EAS 49), revenue, inventory (no LIFO under IFRS), development-cost capitalisation, revaluation model, impairment reversals, borrowing costs, associates/JVs, IAS 29 hyperinflation, IAS 21 FX translation and devaluation effects (critical for Egypt), zakat vs income tax (KSA), employee end-of-service benefits, government grants, plus EAS-specific items and the EAS ↔ IFRS mapping (e.g. EAS 47/48/49). Each difference carries an **analyst adjustment recipe** (how to make companies comparable: IFRS 16 EBITDA vs pre-16, lease-adjusted net debt, zakat treatment) |
| S8.2 | **Concept mapping:** IFRS (`ifrs-full`), ESEF and local taxonomies, plus PDF line-item labels in English and Arabic, mapped to the canonical `om.statements` lines with confidence. A bilingual label dictionary (e.g. "صافي الربح" → net income, "إيرادات النشاط" → revenue, "تكلفة المبيعات" → cost of revenue) |
| S8.3 | **OCR and unstructured extraction pipeline:**<br>• scanned and native PDFs; Arabic and English;<br>• OCR engines per the licence ledger (tesseract `ara+eng` as an isolated service; PaddleOCR/EasyOCR if the ledger allows) with per-word confidence and bboxes;<br>• Eastern Arabic digits (٠–٩) and Persian digits normalised; Arabic thousands and decimal separators (٬ ٫); RTL table reconstruction; brackets and minus negatives; units ("بالألف جنيه", "EGP '000", "SAR million"); multi-column bilingual reports;<br>• fiscal years ending other than in December;<br>• output: `Statements` objects with a Citation per figure (page, bbox, OCR confidence), so `om/model3.py` and the S4 models work unchanged |
| S8.4 | **Tie-out and confidence gate for extracted statements:**<br>• subtotals add up, BS balances, CF ties to the change in cash, IS/CF net income agree, prior-year comparatives match the previous report;<br>• low OCR confidence or a failed tie routes the figure to a review queue with the highlighted bbox, never silently into a model |
| S8.5 | **Sources (public, licence- and ToS-respecting):**<br>• EGX company disclosures and annual reports (public PDFs; robots.txt and rate limits honoured, facts and links stored, never re-hosted);<br>• Saudi Exchange (Tadawul) XBRL/financial statements;<br>• ESEF filings via filings.xbrl.org (EU/UK IFRS: XBRL plus the report);<br>• UK Companies House;<br>• SEC 20-F/40-F (IFRS), already in `om/statements.py`;<br>• user uploads and VDRs.<br>Connector files go under `src/harness/connectors/intl_*.py` |
| S8.6 | **Model and comps support:**<br>• IFRS by-nature P&L (no reported operating income → computed EBIT with a flagged basis);<br>• IFRS 16 toggles;<br>• zakat;<br>• EGP/SAR/AED with FX at period-end vs average and devaluation flags (`om/fx.py`);<br>• calendarisation of non-December years.<br>Coordinate with S4 (which owns `om/model3.py`, `om/comps.py`): S8 supplies Statements + flags; S4 adapts the builders. Lock-coordinated |
| S8.7 | **Evals:**<br>• (a) **automatic gold:** ESEF and SEC 20-F filers have both XBRL and a PDF/HTML report. Extract from the PDF and compare against the XBRL values, figure by figure, for 20 IFRS companies across ≥ 5 countries;<br>• (b) **MENA set:** the 9 S8.0 anchor companies first, then 10 EGX + 5 Tadawul non-bank companies (≥ 5 reports scanned or Arabic-only): tie-out pass rate, earnings-release-to-statements reconciliation, figure accuracy on a hand-verified subset (≥ 300 figures, anchors included), and OCR character accuracy on Arabic numerals;<br>• (c) **standards QA:** 50 questions on IFRS/EAS/US GAAP differences with cited answers.<br>Results go to `scorecard.csv` |
| Gate | `scripts/verify_s8.py` (≥ 99% figure accuracy on the XBRL-gold set; ≥ 98% on the hand-verified MENA subset; 100% of figures carry page + bbox + confidence; failed ties never reach a model), then the **persona gate** with a fourth persona: **MENA PE/IB associate** (Cairo/Riyadh), who grades EAS/IFRS handling, Arabic reports, EGP devaluation and zakat treatment |

## 2b. Parallel sessions (who builds what)

Several Claude Code cloud sessions build at once, one stage each. Every session follows `CLAUDE.md`.

| Session | Owns | Starts |
|---|---|---|
| A: "Acretia: autonomous build" (Boss) | S1 → S2 → S6 → S7.4–S7.5 (security, Docker/CI) | now |
| B: "Acretia: deck engine" | S3 (incl. S3.11 creative layer) | now: deterministic parts first; the VLM critic and image generation use `om/llm.py` until S2.1's adapter lands, then switch |
| C: "Acretia: Excel engine" | S4 | now |
| D: "Acretia: document grid" | S5 | now (builds on `om/pdfdoc.py` from S5.1-pre) |
| F: "Acretia: product app (Felix parity)" | North star P-J1–P-J8, S7.1–S7.3 | now: owns `frontend/`, `om/api/` (or the backend the session chooses per D-029), `e2e/`, `scripts/verify_product.py` |
| E: "Acretia: international & OCR" | S8 | now: owns `om/intl/`, `src/harness/connectors/intl_*.py`, its own tests and `verify_s8.py`; uses `om/pdfdoc.py` (S5) and the Statements contract; asks S4 through locks for builder changes |

How the sessions share the repo:
- Lock rows and the stage's PROGRESS row go to `main` immediately, as small rebased commits.
- Decisions use per-session ids: `D-S3-01`, and so on.
- Shared files (`requirements-extras.txt`, `pyproject.toml`, `om/llm.py`) get minimal, rebased edits.
- Each session runs the full suite before every push to `main`.

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
  - visual range and "wow": varied, purposeful visuals that look made for this deck, not a template; a rubber-stamp look fails
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
