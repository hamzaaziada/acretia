# Progress

**Plan v2 (pivot, 2026-11-16) is active: see PLAN.md.** The v1 milestone table below is kept for history; v1 packets map into v2 stages.

| v2 stage | Status | Evidence |
|---|---|---|
| S1 Ledger, teardowns, buyer research | ⬜ | ledger started (1 row) |
| S2 Harness, router, adapter | 🟡 | v1 M1 ✅ (contracts, storage, PII, replay, DealMemory, router hardening; verify_m1 20/20). Adapter, router/profiles, MCP, connectors, evidence chain and DuckDB storage landed on main (e988e01, f8bc923); `scripts/verify_s2.py` 16/16 so far, connector section and graders pending |
| S3 Deck engine + eval | 🟡 | Deck Studio, spacing, graders exist |
| S4 Excel engine | 🟡 | 3-statement + DCF, grader, bench verified |
| S5 Document matrix grid | 🟡 | Session D building S5.1–S5.4 (claimed 2026-11-16). Existing: Matrix with verified quotes (no bbox/DuckDB) |
| S6 Research agent | 🟡 | Ask with verified citations exists |
| S7 UI, security, Docker/CI | ⬜ | |
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
