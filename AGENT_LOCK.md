# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S5.4a 10-K corpus (session D) | worker | main | 2026-11-16 | evals/tenk/*, scripts/build_tenk_corpus.py, tests/test_s5_evals.py |
| S5.fix1 docparse clean-machine (session D) | worker | main | 2026-11-17 | om/docparse.py, tests/test_docparse.py, requirements.txt (pdf lines only) |
| S5.5a grid parity engine (session D) | worker | main | 2026-11-17 | om/grid.py, tests/test_grid.py, tests/test_grid_parity.py, tests/fixtures/grid/* |
| S5 gate (session D) | gate-writer worker | main | 2026-11-17 | scripts/verify_s5.py |
| S5 docs (session D) | Boss | main | 2026-11-16 | docs/s5/* |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |
| FP-S3-a renderer native shapes/connectors + chart plot layout | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/render.py, om/deck/model.py, tests/test_deck_render.py |
| FP-S3-b archetype keys, sourced examples, derived provenance, citation markers, positive token | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/archetypes/*.py, om/deck/provenance.py, om/deck/theme.py, tests/test_deck_arch_*.py, tests/test_deck_engine.py |
| S3.12 revisions: per-slide edit, annotations, versions, rollback | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/revise.py, om/deck/versions.py, tests/test_deck_revise.py |
| S3 gate script (independent writer) | session B gate worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | scripts/verify_s3.py |
| S3 gate + docs | session B Boss | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | docs/s3/*, docs/deck-engine.md, PROGRESS.md (S3 row only) |
| S8.1 standards KB (session E) | worker | main | 2026-11-16 | om/intl/standards/**, docs/s8/standards/**, scripts/gen_standards_docs.py, tests/test_intl_standards.py |
| S8.2 concepts + bilingual labels (session E) | worker | main | 2026-11-16 | om/intl/concepts.py, om/intl/labels.py, om/intl/data/labels/**, tests/test_intl_concepts.py, tests/test_intl_labels.py |
| S8.3a numbers + OCR service + synthetic fixtures (session E) | worker | main | 2026-11-16 | om/intl/numparse.py, om/intl/ocr.py, scripts/make_intl_fixtures.py, tests/fixtures/intl/**, tests/test_intl_numparse.py, tests/test_intl_ocr.py, license-and-repo-ledger.csv (S8 rows only) |
| S8.4 types + tie-out + review queue (session E) | worker | main | 2026-11-16 | om/intl/types.py, om/intl/tieout.py, om/intl/review.py, tests/test_intl_tieout.py |
| S8.6a FX, calendarisation, adjustments (session E) | worker | main | 2026-11-16 | om/intl/fx.py, om/intl/calendar.py, om/intl/adjust.py, tests/test_intl_fx.py, tests/test_intl_adjust.py, docs/s8-requests-for-s4.md |
| S8.0/S8.7-corpus anchors + eval sourcing (session E) | worker | main | 2026-11-16 | evals/intl/corpus/**, evals/intl/anchors/*/sources.json, scripts/fetch_intl_corpus.py, data/raw/intl/** (never committed) |
| S8.0 anchor notes + QA (session E, wave 2) | worker | main | 2026-11-16 | om/intl/companies/**, evals/intl/anchors/*/{figures,release_recon,qa}.jsonl |
| S8.5 intl connectors (session E, wave 2; new files only, base.py untouched) | worker | main | 2026-11-16 | src/harness/connectors/intl_*.py, om/intl/sources/**, om/intl/ixbrl.py, docs/s8/source-terms.md, tests/test_intl_connectors.py, tests/fixtures/intl_connectors/** |
| S8.7c standards QA eval (session E) | worker | main | 2026-11-16 | evals/intl/standards_qa/**, scripts/eval_intl_qa.py, tests/test_eval_intl_qa.py, scorecard.csv (S8 rows only) |
| S8 gate + docs (session E) | Boss + gate worker | main | 2026-11-16 | scripts/verify_s8.py, tests/test_verify_s8_smoke.py, docs/s8/*.md, om/intl/__init__.py, PROGRESS.md (S8 row only) |
| SF.0 product spec + gate spec (session F) | Boss | main | 2026-11-16 | docs/product/**, docs/product-requests.md, PROGRESS.md (Product row only), DECISIONS.md (D-SF-* only) |
| SF.1 API backend (session F) | session F workers | main | 2026-11-16 | om/api/**, tests/test_api_*.py, tests/fixtures/api/** |
| SF.2 frontend app (session F) | session F workers | main | 2026-11-16 | frontend/** |
| SF.3 e2e journeys + product gate (session F) | session F gate worker | main | 2026-11-16 | e2e/**, scripts/verify_product.py |
| SF.4 TSB + reliability harness (session F, D-032) | session F workers | main | 2026-11-16 | eval/tsb/**, eval/reliability/** |
| S6.1b research tools | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/research/tools.py, tests/test_research_tools.py, tests/fixtures/research/tools/* |
| S6.2 figure verifier | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/research/verify.py, tests/test_research_verify.py |
| S6.3 research evals | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | eval/research/**, tests/test_research_evals.py |
| S4.7c dashboards for LBO/merger/comps | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/lbo.py, om/merger.py, om/comps.py, tests/test_polish_models.py |
| S4.6a OM-Bench 10 + planted audit | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/bench.py, om/validate_xlsx.py, tests/test_bench.py, tests/test_validate_xlsx.py |
| S4.6c reliability-100 + timing | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/reliability.py, tests/test_reliability.py |
| S4 gate script | gate worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | scripts/verify_s4.py |
| S4.8 model API for product app | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/modelapi.py, tests/test_modelapi.py, docs/interfaces.md (Models section only) |
| S4.9 reference-structure generation + firm templates | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/templatefit.py, tests/test_templatefit.py |
| FP-S1a S1 gate strictness | gate-writer (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | scripts/verify_s1.py |
| FP-S1b ledger + notices | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | license-and-repo-ledger.csv, docs/ledger-notes.md, THIRD_PARTY_NOTICES.md, requirements.txt (anthropic line only) |
| FP-S1c buyer-research rubric thresholds | worker (session A) | claude/dreamy-ramanujan-k8p2xt | 2026-11-17 | docs/buyer-research.md |
| S4.fix2 formula engine coverage (SpreadsheetBench) | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-17 | om/formula.py, tests/test_formula_ext2.py |

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
