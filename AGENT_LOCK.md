# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| M1 P1.1–P1.4 | Boss session_01Pf4xaPdC2V1r93ja2cebXD | claude/dreamy-ramanujan-k8p2xt → main | 2026-11-16 | om/contracts.py, om/storage.py, om/llm.py, om/pii.py, om/replay.py, om/deals.py, tests/test_{contracts,storage,llm_router,deal_memory}.py |

## Log
- 2026-11-16: created; no active claims.
- 2026-11-16: M1 claimed by cloud Boss session.
