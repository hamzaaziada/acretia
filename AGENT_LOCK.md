# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S1.2 deck teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/deck-*.md, docs/teardowns/briefs/* |
| S1.3 excel/grid/research teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/excel-*.md, docs/teardowns/grid-*.md, docs/teardowns/research-*.md |
| S2.1 adapter | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/adapter.py, src/harness/ledger.py, om/llm.py, tests/test_adapter.py, tests/fixtures/adapter/* |
| S2.4 MCP | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/mcp/*, tests/test_mcp.py |
| S2.5 connectors | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/connectors/*, tests/test_connectors_harness.py, tests/fixtures/connectors/* |
| S5.1 parser (session D) | worker | main | 2026-11-16 | om/docparse.py, om/parse_services.py, tests/test_docparse.py, tests/fixtures/docparse/*, docs/s5/parser-*.md |
| S5.2 DuckDB grid (session D) | worker | main | 2026-11-16 | om/grid.py, tests/test_grid.py, tests/fixtures/grid/*, open_multiples.py (grid subcommand only) |
| S5.3 VDR gap/risk (session D) | worker | main | 2026-11-16 | om/vdr_risk.py, tests/test_vdr_risk.py, tests/fixtures/vdr/* |
| S5.4 evals (session D) | worker | main | 2026-11-16 | evals/tenk/*, evals/odl_bench/*, scripts/build_tenk_corpus.py, scripts/eval_s5.py, tests/test_s5_evals.py, scorecard.csv (S5 rows only) |
| S5 gate (session D) | Boss | main | 2026-11-16 | scripts/verify_s5.py, docs/s5/* |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |
| S4.1 validate_xlsx | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/validate_xlsx.py, scripts/validate_xlsx.py, tests/test_validate_xlsx.py |
| S4.2 three-engine recalc | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/recalc.py, tests/test_recalc.py |
| S4.3a LBO | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/lbo.py, tests/test_lbo.py |
| S4.3b merger | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/merger.py, tests/test_merger.py |
| S4.3c comps | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/comps.py, tests/test_comps.py |
| S4.4 graph/ask/edit/roll-forward | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/wbgraph.py, om/wbedit.py, om/rollforward.py, tests/test_wbgraph.py, tests/test_wbedit.py, tests/test_rollforward.py |
| S4.5 manifest + delivery gate | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/manifest.py, om/delivery.py, tests/test_manifest.py |
| S4.7a writer polish (styles, charts, print, outline) | worker (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/xlsx.py, tests/test_xlsx_polish.py |
| S4.6 bench + S4 gate | Boss (session C) | claude/busy-knuth-i3ewp5 | 2026-11-16 | om/bench.py, scripts/verify_s4.py, tests/test_bench.py, docs/s4/* |

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
