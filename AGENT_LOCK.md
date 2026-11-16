# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S1.2 deck teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/deck-*.md, docs/teardowns/briefs/* |
| S1.3 excel/grid/research teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/excel-*.md, docs/teardowns/grid-*.md, docs/teardowns/research-*.md |
| S2.1 adapter | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/adapter.py, src/harness/ledger.py, om/llm.py, tests/test_adapter.py, tests/fixtures/adapter/* |
| S2.2 contracts | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | om/contracts.py, tests/test_contracts.py |
| S2.3 router | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/router.py, src/harness/profiles/*, tests/test_harness_router.py |
| S2.6 evidence | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | src/harness/evidence.py, tests/test_evidence.py |
| S2.7 duckdb storage | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | om/storage.py, tests/test_storage.py |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |

## Log
- 2026-11-16: created; no active claims.
- 2026-11-16: M1 claimed by cloud Boss session.
- 2026-11-16: M1 gate passed; lock released. M2 claimed.
- 2026-11-16: Plan v2 adopted (d7dfb1a). M2 claim converted: in-flight P2.1/P2.4 re-labelled S5.1-pre/S2.5-pre. S1.1–S1.4 claimed.
- 2026-11-16: S1.1, S1.4 and the pre-stage rows done and released. S2.1, S2.2, S2.3, S2.6, S2.7 claimed (S1.2/S1.3 still running; they share no files).
