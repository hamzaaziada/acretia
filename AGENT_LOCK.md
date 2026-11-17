# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S5.4a 10-K corpus (session D) | worker | main | 2026-11-16 | evals/tenk/*, scripts/build_tenk_corpus.py, tests/test_s5_evals.py |
| S5.4b evals + VDR50 (session D) | worker | main | 2026-11-17 | evals/vdr50/*, evals/odl_bench/*, evals/out/*, scripts/build_vdr50.py, scripts/eval_s5.py, tests/test_s5_eval_runner.py, scorecard.csv (S5 rows only) |
| S5.5c Matrix Chat (session D) | worker | main | 2026-11-17 | om/grid_chat.py, tests/test_grid_chat.py, tests/fixtures/grid_chat/* |
| S5.6 grid interfaces doc (session D) | worker | main | 2026-11-17 | docs/interfaces.md ("Document grid (S5)" section only) |
| S5.F1 completeness recovery (session D) | worker | main | 2026-11-17 | om/docparse.py, tests/test_docparse.py |
| S5.F2 extractive precision (session D) | worker | main | 2026-11-17 | om/grid.py, tests/test_grid.py, tests/test_grid_parity.py, tests/test_grid_extractive.py |
| S5 docs (session D) | Boss | main | 2026-11-16 | docs/s5/* |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |
| S3 gate script (independent writer) | session B gate worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | scripts/verify_s3.py |
| S3.10 corpus, reliability run, eval, scorecard, samples | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-17 | evals/decks/**, om/deck/eval.py, scripts/eval_s3.py, scorecard.csv (S3 rows only), docs/samples/s3/**, tests/test_deck_eval.py |
| FP-S3-c takeaway provenance, engine returns solved slides, revise without spy | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-17 | om/deck/archetypes/*.py, om/deck/provenance.py, om/deck/engine.py, om/deck/revise.py, tests/test_deck_arch_*.py, tests/test_deck_engine.py, tests/test_deck_revise.py |
| FP-S3-d procedural art polish + SVG designer quality | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-17 | om/deck/visuals/procedural.py, om/deck/visuals/library.py, tests/test_deck_visuals.py |
| S3 gate + docs | session B Boss | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | docs/s3/*, docs/deck-engine.md, PROGRESS.md (S3 row only) |
| S8.1 standards KB (session E) | worker | main | 2026-11-16 | om/intl/standards/**, docs/s8/standards/**, scripts/gen_standards_docs.py, tests/test_intl_standards.py |
| S8.3a numbers + OCR service + synthetic fixtures (session E) | worker | main | 2026-11-16 | om/intl/numparse.py, om/intl/ocr.py, scripts/make_intl_fixtures.py, tests/fixtures/intl/**, tests/test_intl_numparse.py, tests/test_intl_ocr.py, license-and-repo-ledger.csv (S8 rows only) |
| S8.3b extraction pipeline + read_report + intl-model CLI (session E) | worker | main | 2026-11-16 | om/intl/extract.py, om/intl/tables.py, om/intl/pipeline.py, open_multiples.py (intl-model subcommand only), tests/test_intl_extract.py, tests/test_intl_pipeline.py, evals/intl/review_minutes.csv, evals/intl/telemetry.jsonl |
| S8.0/S8.7-corpus anchors + eval sourcing (session E) | worker | main | 2026-11-16 | evals/intl/corpus/**, evals/intl/anchors/*/sources.json, scripts/fetch_intl_corpus.py, data/raw/intl/** (never committed) |
| S8.0 anchor notes + QA (session E, wave 2) | worker | main | 2026-11-16 | om/intl/companies/**, evals/intl/anchors/*/{figures,release_recon,qa}.jsonl |
| S8.5 intl connectors (session E, wave 2; new files only, base.py untouched) | worker | main | 2026-11-16 | src/harness/connectors/intl_*.py (S2.5 base fixed on main; S8.5 dispatched 2026-11-17), om/intl/sources/**, om/intl/ixbrl.py, docs/s8/source-terms.md, tests/test_intl_connectors.py, tests/fixtures/intl_connectors/** |
| S8.7c standards QA eval (session E) | worker | main | 2026-11-16 | evals/intl/standards_qa/**, scripts/eval_intl_qa.py, tests/test_eval_intl_qa.py, scorecard.csv (S8 rows only) |
| S8 gate + docs (session E) | Boss + gate worker | main | 2026-11-16 | scripts/verify_s8.py, tests/test_verify_s8_smoke.py, docs/s8/*.md, om/intl/__init__.py, PROGRESS.md (S8 row only) |
| SF.0 product spec + gate spec (session F) | Boss | main | 2026-11-16 | docs/product/**, docs/product-requests.md, PROGRESS.md (Product row only), DECISIONS.md (D-SF-* only) |
| SF.1 API backend (session F) | session F workers | main | 2026-11-16 | om/api/**, tests/test_api_*.py, tests/fixtures/api/** |
| SF.2 frontend app (session F) | session F workers | main | 2026-11-16 | frontend/** |
| SF.3 e2e journeys + product gate (session F) | session F gate worker | main | 2026-11-16 | e2e/**, scripts/verify_product.py |
| SF.4 TSB + reliability harness (session F, D-032) | session F workers | main | 2026-11-16 | eval/tsb/**, eval/reliability/** |
| S6.2 figure verifier | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/research/verify.py, tests/test_research_verify.py |
| FP-S1c buyer-research rubric thresholds | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | docs/buyer-research.md |
| S4.fix2 formula engine coverage (SpreadsheetBench) | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/formula.py, tests/test_formula_ext2.py |
| FP-S2b adapter/ledger/PII/router | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | src/harness/adapter.py, src/harness/ledger.py, src/harness/router.py, src/harness/profiles/*, om/pii.py, om/replay.py, tests/test_adapter.py, tests/test_harness_router.py, tests/test_llm_router.py |
| S6.1c awaiting_review + quarterly data | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | om/contracts.py (Job.status enum only), src/harness/research/jobs.py, src/harness/research/workflows/review.py, src/harness/research/tools.py, tests/test_research_api.py, tests/test_research_tools.py, tests/test_research_workflows.py |
| FP-S4-A data fidelity (statements/concepts/facts) | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/statements.py, om/concepts.py, om/facts.py, tests/test_statements_fix.py |
| FP-S4-B model3 valuation + robustness | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/model3.py, tests/test_model3_fix.py, license-and-repo-ledger.csv (one row) |
| FP-S4-C print/polish + manifest | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/polish.py, om/xlsx.py, om/manifest.py, tests/test_polish_fix.py |
| FP-S4-D LBO + merger | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/lbo.py, om/merger.py, tests/test_lbo_merger_fix.py |
| FP-S4-E comps + market | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/comps.py, om/market.py, tests/test_comps_fix.py |
| FP-S4-F validator 3-column rows | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/validate_xlsx.py, tests/test_validate_fix.py |

## Log
- 2026-11-16: created; no active claims.
- 2026-11-16: M1 claimed by cloud Boss session.
- 2026-11-16: M1 gate passed; lock released. M2 claimed.
- 2026-11-16: Plan v2 adopted (d7dfb1a). M2 claim converted: in-flight P2.1/P2.4 re-labelled S5.1-pre/S2.5-pre. S1.1–S1.4 claimed.
- 2026-11-16: S1.1, S1.4 and the pre-stage rows done and released. S2.1, S2.2, S2.3, S2.6, S2.7 claimed (S1.2/S1.3 still running; they share no files).
- 2026-11-16: S2.6, S2.7 done (pending S2 gate). S2.4, S2.5 claimed.
- 2026-11-16: Session C claimed S4.1–S4.7 (Excel engine); disjoint from S1/S2 rows.
- 2026-11-16: S2.2, S2.3 done (pending S2 gate); rows released.
- 2026-11-16: Session D claimed S5.1–S5.4 and the S5 gate.
- 2026-11-16: session B claimed S3 wave 1 (core, fit/RTL, spec/ghost, validator, visuals) and the S3 gate.
- 2026-11-16: S2.1 adapter landed on main (e988e01); row released.
- 2026-11-16: Reviewer findings verified (env-dependent live path in Router chains; OCR test recursion; psycopg/pypdf ledger gap). FP-R1..R3 claimed.
- 2026-11-16: S2.4, S2.5 done (pending S2 gate); rows released. S6.0 interface claimed early for session F's command bar.
- 2026-11-16: S1.2 deck teardowns and FP-R2 ledger rows done; rows released.
- 2026-11-16: session E claimed S8.1–S8.7 and the S8 gate. S8.5 writes only new `src/harness/connectors/intl_*.py` files (inside the S2.5 glob); it waits for S2.5's base.py on main and never edits S2.5 files.
- 2026-11-16: session A restored session C/F rows that de1725b dropped by mistake, and removed the stale S4.1/S4.5/S4.7a rows it had re-added.
- 2026-11-16: session B: S3 wave 1 merged (core, fit/RTL, spec/ghost, validator, visuals); wave 2 claimed (archetypes a/b/c, critic, cloner+sync).
- 2026-11-16: Session F claimed eval/tsb/ and eval/reliability/ (D-032 measurement harness).
- 2026-11-16: session A: FP-R1, FP-R3, S6.0 landed on main (f8bc923); FP-R4 and S2 connector gate section claimed.
- 2026-11-16: session A: S6.1a, S6.1b, S6.2, S6.3 claimed.
- 2026-11-16: S4.2, S4.3a/b/c, S4.4, S4.7b merged and released. Session C wave 2 claimed: S4.7c, S4.6a/b/c, S4.fix1, S4 gate script.
- 2026-11-16: session B: S3.8, S3.9 merged and released; S3.fix-env claimed (reviewer: deck deps/fonts on clean machines).
- 2026-11-16: session A: S6.1a released (agent loop belongs to harness lab S9, D-033); S7.5a CI claimed early (reviewer: main red on clean machine).
- 2026-11-16: session E: S8.4, S8.6a, S8.1 landed; S8.7c and the S8 gate writer dispatched.
- 2026-11-17: S5.1, S5.2, S5.3 verified on main and released. Claimed S5.fix1, S5.5a; S5.4a resumed; S5 gate writer dispatched (session D).
- 2026-11-16: session A: S1.3, FP-R4, S2 connector gate done; S1-fin claimed.
- 2026-11-16: session A: S7.5a CI on main (a6c1b2b); S1 grader findings → FP-S1a/b/c claimed.
- 2026-11-16: session B: S3.3a/b/c, S3.int, S3.fix-env merged and released; wave 3 claimed (FP-S3-a, FP-S3-b, S3.12, S3 gate script).
- 2026-11-17: S4.fix1, S4.6b merged and released; S4.fix2 claimed.
- 2026-11-16: session A: FP-S1a/b, S6.1b, S6.3 done; S6.1 workflows, S6.4, S6.5a, S6.5b claimed (parity items 24-33, 58-63).
- 2026-11-16: session A: S2 specialist review FAIL (1C/7H); FP-S2a-d claimed.
- 2026-11-17: S5.fix1 and S5.5a verified on main and released; S5.4b and S5.5b claimed (session D).
- 2026-11-16: session A: FP-CI1 claimed (main CI runs all cancelled by cancel-in-progress).
- 2026-11-16: session E: S8.2, S8.3a, S8.4, S8.6a landed (S8.4/S8.6a/S8.2 rows released; S8.3a row kept for the Eastern-digit fix). S8.3b claimed.
- 2026-11-16: session A: FP-CI1 landed.
- 2026-11-17: S5.5b verified on main and released; S5.5c, S5.6 claimed (session D).
- 2026-11-17: session B: FP-S3-a, FP-S3-b, S3.12 merged and released; claimed S3.10 corpus, FP-S3-c, FP-S3-d.
- 2026-11-17: S4.7c, S4.6a, S4.8, S4.9 merged and released; S4.10 samples claimed.
- 2026-11-17: S5 gate script landed; Fix Packets S5.F1, S5.F2 claimed (session D).
- 2026-11-16: session A: FP-S2d done; FP-CI2 claimed (CI forced replay mode broke 12 fake-provider tests).
- 2026-11-16: session A: FP-CI2 landed (8619648).
- 2026-11-16: session A: FP-S2a done (pending S2 re-review).
- 2026-11-16: session A: FP-S2c done (pending S2 re-review).
- 2026-11-16: session A: S6.1, S6.4, S6.5a, S6.5b done; S6.1c claimed.
- 2026-11-17: S4.6c, S4 gate, S4.10 merged and released. Fix Packets FP-S4-A..F claimed (IB VP review 6.2/10, gate FAILs, reliability 52%).
