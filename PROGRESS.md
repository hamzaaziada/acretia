# Progress

**Plan v2 (pivot, 2026-11-16) is active: see PLAN.md.** The v1 milestone table below is kept for history; v1 packets map into v2 stages.

| v2 stage | Status | Evidence |
|---|---|---|
| S1 Ledger, teardowns, buyer research | 🟡 | Deterministic gate `scripts/verify_s1.py` 13/13 (exact ledger mapping, import coverage, copyleft isolation, NOTICE coverage, labelled teardowns). Specialist review PASS WITH FIXES 7.5/10, all High fixed. Teardowns: 15 deck engines + Excel/grid/research on real inputs. Buyer research: 56 sources, self-consistent rubric (102-anchor computed self-test). Persona gate NOT met: round 8 IB 7.4, MBB 6.6, PE 6.3 (D-S1-04) |
| S2 Harness, router, adapter | 🟡 | S2.4b Excel MCP daemon wiring done: `xlsx_recalc` calls `om.recalc.compare` (was a dead branch), plus `xlsx_engine_status`/`xlsx_engine_restart`; gate `scripts/verify_s2_4b.py` 22/23 passed, 1 skipped (uno bridge not importable on this Mac, D-S2-02). | Deterministic gate `scripts/verify_s2.py` 32/32 and `verify_m1` 20/20 (hermetic). Adapter, router/profiles, MCP stdio servers, connectors, evidence chain, DuckDB storage on main. Specialist review round 1 FAIL 5/10 (1 Critical, 7 High) → FP-S2a–d fixed; re-review in progress. Persona gate n/a (infrastructure) |
| S3 Deck engine + eval | 🟡 | Deck Studio, spacing, graders exist |
| S4 Excel engine | 🟡 | 3-statement + DCF, grader, bench verified |
| S5 Document matrix grid | 🟡 | Session D building S5.1–S5.4 (claimed 2026-11-16). Existing: Matrix with verified quotes (no bbox/DuckDB) |
| S6 Research agent | 🟡 | Built: job interface (S6.0), sourced tools (S6.1b), figure verifier (S6.2), eval harness Vals/FinanceBench/BankerToolBench in replay (S6.3), workflows incl. tick-and-tie and source review (S6.1), schedules/email (S6.4), admin + SCIM/ACL (S6.5). Gate script, specialist review and personas pending; live evals need an endpoint (D-021) |
| S7 UI, security, Docker/CI | ⬜ | |
| Product (Felix parity, session F) | 🟡 | Works end to end in replay mode (ask → plan → source review → steps → deliverable → model/deck viewer), verified in Chromium against the real server; screenshots in docs/samples/product/. **Graders:** UI/UX lead review 1 = **6.4/10, BLOCK** (docs/product/uiux-review-1.md: citation paths end without a highlight, Documents tab raw keys, Matrix persistence, deck canvas, raw ids, viewer role); fix packets FP-A/FP-B/SF.7 in flight. Gate verify_product.py and Haiku personas not yet passed. Reliability (replay, fixtures): success 100% of supported briefs, 0 silent wrong numbers of 24,241, determinism 100%, resume 100% (eval/reliability/report.md); time-saved figures are estimates, not claims (eval/tsb/report.md). No ✅ until all three graders pass (D-033) |
| S8 International accounting + OCR financials | 🟡 | Session E building S8.1–S8.7 (claimed 2026-11-16) |

## v1 (superseded)

Status: ✅ verified (gate passed) · 🟡 partial · ⬜ not started. Update this file only after a gate passes.

| Milestone | Status | Evidence |
|---|---|---|
| Baseline (pre-plan) | ✅ | 144 tests pass (`python3 -m unittest discover -s tests -q`). The Excel engine bench is green: six companies at 100/100, 6,958/6,958 cells agree with LibreOffice, and the audit catches 10/10 planted errors (`data/out/bench/2026-11-16/report.md`, not committed) |
| M1 Contracts, storage, LLM router, DealMemory | ✅ | `scripts/verify_m1.py` 20/20, hermetic (re-verified on main after reviewer fix f8bc923, with provider keys present in env): 13 contracts round-trip with field-path errors and fuzz; SigV4 matches both AWS vectors; SQLite queue exactly-once across 16 threads; PII never reaches the provider or fixtures; replay works with sockets disabled; MeshPool key refused on 8 lookalike hosts; DealMemory 2-cell xlsx diff, pptx diff, byte-exact undo, org isolation. Suite 222/222 |
| M2 PDF / VDR ingestion and grid | 🟡 | Text extraction, rooms, connectors, Matrix and the consistency checker exist. Still to build: bbox citations, a table parser, charts, a DuckDB grid and the VDR risk detector |
| M3 Excel engine | 🟡 | P3.4 is partial (5-year annual history; no quarters, NOLs, TSM or segments). Done (✅ verified, see the baseline row): 3-statement + DCF, the writer/reader, the evaluator, the QA grader and the bench. Still to build: WorkbookGraph, edits, roll-forward, LBO, merger, comps, the manifest and the delivery gate |
| M4 Deck engine | 🟡 | Deck Studio, layout components, spacing rules, the icon library and partner/MD graders exist. Still to build: the style cloner, client masters, manifest sync, 36 archetypes and the WCAG/vision QA loop |
| M5 Felix workflows and evals | ⬜ | |
| M6 Security review | ⬜ | Existing pieces: Keychain keys, a Host/Origin guard, SVG sanitising, the key-to-host binding |
| M7 Deploy | ⬜ | |

## Log

- 2026-11-16: Repository initialised. The plan, decisions and lock files were written. Next: M1 P1.1 contracts.
- 2026-11-16: M1 gate passed (19/19), suite 222 green. Next: M2.
- 2026-11-16: Architectural pivot to plan v2. Meshpool Harness reference code added. M1 work (gated) maps into S2. Next: S1.
- 2026-11-16: session A: reviewer findings (router live path, OCR test recursion, psycopg/pypdf ledger rows) fixed in f8bc923; verify_m1 20/20 hermetic.
- 2026-11-17: session A: S1 deterministic + specialist graders pass; persona gate not met after 8 rounds (D-S1-04). S2 fixes for specialist findings landed; re-review running. S6 packets built; S6 gate next.
- 2026-11-17: session G: S2.4b done and gated (22/23, 1 skipped). Excel MCP server now recalculates through `om.recalc.compare`; engine status and daemon restart exposed. LibreOffice stays a subprocess (D-S2-03).
