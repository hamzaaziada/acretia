# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| S5.1-pre (ex-M2 P2.1, in flight) | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | om/pdfwrite.py, om/pdfdoc.py, tests/test_pdfdoc.py, requirements-extras.txt |
| S2.5-pre (ex-M2 P2.4, in flight) | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | om/rooms.py, om/extract.py, tests/test_ingest.py |
| S1.1 ledger | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | license-and-repo-ledger.csv, docs/ledger-notes.md |
| S1.2 deck teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/deck-*.md, docs/teardowns/briefs/* |
| S1.3 excel/grid/research teardowns | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/teardowns/excel-*.md, docs/teardowns/grid-*.md, docs/teardowns/research-*.md |
| S1.4 buyer research | worker | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | docs/buyer-research.md |
| S1 gate | Boss | claude/dreamy-ramanujan-k8p2xt | 2026-11-16 | scripts/verify_s1.py |

## Log
- 2026-11-16: created; no active claims.
- 2026-11-16: M1 claimed by cloud Boss session.
- 2026-11-16: M1 gate passed; lock released. M2 claimed.
- 2026-11-16: Plan v2 adopted (d7dfb1a). M2 claim converted: in-flight P2.1/P2.4 re-labelled S5.1-pre/S2.5-pre. S1.1–S1.4 claimed.
