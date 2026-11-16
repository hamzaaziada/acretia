# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S1.3 excel/grid/research teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/excel-*.md, docs/teardowns/grid-*.md, docs/teardowns/research-*.md |
| S5.1 parser (session D) | worker | main | 2026-11-16 | om/docparse.py, om/parse_services.py, tests/test_docparse.py, tests/fixtures/docparse/*, docs/s5/parser-*.md |
| S5.2 DuckDB grid (session D) | worker | main | 2026-11-16 | om/grid.py, tests/test_grid.py, tests/fixtures/grid/*, open_multiples.py (grid subcommand only) |
| S5.3 VDR gap/risk (session D) | worker | main | 2026-11-16 | om/vdr_risk.py, tests/test_vdr_risk.py, tests/fixtures/vdr/* |
| S5.4 evals (session D) | worker | main | 2026-11-16 | evals/tenk/*, evals/odl_bench/*, scripts/build_tenk_corpus.py, scripts/eval_s5.py, tests/test_s5_evals.py, scorecard.csv (S5 rows only) |
| S5 gate (session D) | Boss | main | 2026-11-16 | scripts/verify_s5.py, docs/s5/* |
| FP-R1 router hermeticity + OCR test | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | om/llm.py, tests/test_llm_router.py, src/harness/adapter.py, tests/test_adapter.py, tests/test_pdfdoc.py |
| FP-R3 gate hardening (gate-writer) | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py, scripts/verify_m1.py, scripts/verify_s2.py |
| S6.0 research job interface | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/research/__init__.py, src/harness/research/api.py, src/harness/research/jobs.py, docs/interfaces.md (section 'Research agent jobs' only), tests/test_research_api.py |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |
| S4.1 validate_xlsx | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/validate_xlsx.py, scripts/validate_xlsx.py, tests/test_validate_xlsx.py |
| S4.2 three-engine recalc | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/recalc.py, om/formula.py, tests/test_recalc.py, tests/test_formula_ext.py |
| S4.3a LBO | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/lbo.py, tests/test_lbo.py |
| S4.3b merger | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/merger.py, tests/test_merger.py |
| S4.3c comps | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/comps.py, om/market.py, tests/test_comps.py |
| S4.4 graph/ask/edit/roll-forward | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/wbgraph.py, om/wbedit.py, om/rollforward.py, tests/test_wbgraph.py, tests/test_wbedit.py, tests/test_rollforward.py |
| S4.5 manifest + delivery gate | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/manifest.py, om/delivery.py, tests/test_manifest.py |
| S4.7a writer polish (styles, charts, print, outline) | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/xlsx.py, tests/test_xlsx_polish.py |
| S4.6 bench + S4 gate | Boss (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/bench.py, scripts/verify_s4.py, tests/test_bench.py, docs/s4/* |
| S3.core render+theme+model+archetype base | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/__init__.py, om/deck/model.py, om/deck/theme.py, om/deck/render.py, om/deck/archetypes/__init__.py, om/deck/archetypes/base.py, om/deck/archetypes/core.py, tests/test_deck_render.py |
| S3.4/S3.5 metrics, fit, RTL | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/metrics.py, om/deck/fit.py, om/deck/rtl.py, tests/test_deck_fit.py, tests/test_deck_rtl.py |
| S3.1/S3.2 ghost deck + spec | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/spec.py, om/deck/ghost.py, tests/test_deck_spec.py, tests/test_deck_ghost.py, tests/fixtures/llm/deck_* |
| S3.6/S3.7 slop + validate_pptx | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/slop.py, om/deck/validate.py, scripts/validate_pptx.py, tests/test_validate_pptx.py |
| S3.11 visual layer | session B worker | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | om/deck/visuals/**, tests/test_deck_visuals.py |
| S3 gate + docs | session B Boss | claude/upbeat-mccarthy-viqjuo | 2026-11-16 | scripts/verify_s3.py, docs/deck-engine.md, PROGRESS.md (S3 row only) |
| S8.1 standards KB (session E) | worker | main | 2026-11-16 | om/intl/standards/**, docs/s8/standards/**, tests/test_intl_standards.py |
| S8.2 concepts + bilingual labels (session E) | worker | main | 2026-11-16 | om/intl/concepts.py, om/intl/labels.py, om/intl/data/labels/**, tests/test_intl_concepts.py, tests/test_intl_labels.py |
| S8.3a numbers + OCR service + synthetic fixtures (session E) | worker | main | 2026-11-16 | om/intl/numparse.py, om/intl/ocr.py, scripts/make_intl_fixtures.py, tests/fixtures/intl/**, tests/test_intl_numparse.py, tests/test_intl_ocr.py, license-and-repo-ledger.csv (S8 rows only) |
| S8.4 types + tie-out + review queue (session E) | worker | main | 2026-11-16 | om/intl/types.py, om/intl/tieout.py, om/intl/review.py, tests/test_intl_tieout.py |
| S8.6a FX, calendarisation, adjustments (session E) | worker | main | 2026-11-16 | om/intl/fx.py, om/intl/calendar.py, om/intl/adjust.py, tests/test_intl_fx.py, tests/test_intl_adjust.py, docs/s8-requests-for-s4.md |
| S8.7-corpus eval sourcing (session E) | worker | main | 2026-11-16 | evals/intl/corpus/**, scripts/fetch_intl_corpus.py, data/raw/intl/** (never committed) |
| S8.5 intl connectors (session E, wave 2; new files only, base.py untouched) | worker | main | 2026-11-16 | src/harness/connectors/intl_*.py, om/intl/sources/**, tests/test_intl_connectors.py, tests/fixtures/intl_connectors/** |
| S8 gate + docs (session E) | Boss | main | 2026-11-16 | scripts/verify_s8.py, docs/s8/*.md, om/intl/__init__.py, PROGRESS.md (S8 row only) |

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
