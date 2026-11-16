# Agent lock

One row per active claim. Claim a packet before you touch its files, commit the claim, and remove the row when the gate passes. If a claim is older than 6 hours and its branch has no new commits, treat it as abandoned and say so in the log.

| Packet | Agent / session | Branch | Claimed (UTC) | Files |
|---|---|---|---|---|
| — | — | — | — | — |

## Log
- 2026-11-16: created; no active claims.
