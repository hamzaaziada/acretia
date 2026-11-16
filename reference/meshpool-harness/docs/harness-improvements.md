# Meshpool Harness v1: why it underperforms, and what to change

Scope: v1 code-engine runs on DeepSeek V4.1 Flash through the Meshpool gateway (SWE-bench Verified, Terminal-Bench
2.0). Every claim cites a file and line in this repository, or a measurement in `eval/results/`. Nothing here is
implemented yet. Each change goes behind a flag so it can be ablated.

Price constants used in every estimate are the ones the loop itself uses (`meshpool_harness/core/loop.py:118-119`).
Per million tokens: uncached input $0.15, cached input $0.003, output $0.60, all times the measured gateway factor.

## 1. Cache hit rate (target: at least 85%)

### How a request is assembled

| Order | Content | Where it comes from | Stable across calls in one task? |
|---|---|---|---|
| 1 | Tool schemas (8 core tools, fixed order) | `core/tools.py:24-54`, `core/loop.py:44` | Yes |
| 2 | System prompt plus sorted skill index | `engines/code/engine.py:17-39`, `core/loop.py:40-46` | Yes (identical across all tasks) |
| 3 | Task message: task text plus harness_note, how_to_run_tests, terminal_mode, repo_hints, issue examples, existing_test_style, lessons | `engines/code/engine.py:59-132` | Yes (built once, before the first call) |
| 4 | History: assistant turns (content and tool calls), tool results, guard notes as user messages | `core/loop.py:124-200` | Append-only |
| 5 | Request body: model, max_tokens, temperature, tools, tool_choice; `prompt_cache_key` and `user` only if `MH_CACHE_KEY=1` | `eval/ledger.py:239-248`, `core/wire.py:84-91` | Yes |
| 6 | Headers: Authorization, `X-Harness-*` attribution only; no session headers | `eval/ledger.py:253-260`, `core/wire.py:95-98` | Yes |

The prompt itself is byte-stable and append-only. There are no timestamps or random IDs in it: a search for nonce,
uuid and strftime finds none on the request path. Tool order is fixed, and history is never rewritten in v1.

### Every source of cache churn found

| # | Source | Evidence | Effect in v1 |
|---|---|---|---|
| 1 | **No conversation affinity.** No `prompt_cache_key`, `user` or session header is sent by default, so the gateway can send consecutive calls of one conversation to different upstream backends, each with a cold cache. | `eval/ledger.py:245` (opt-in, off in v1); `eval/ledger.py:255-260` (no session headers). A captured Codex request sends `prompt_cache_key` = session id, plus `session-id`, `thread-id` and `x-client-request-id` headers carrying the same id. | **Suspected, not confirmed.** Final A/B on 7 dev tasks, same code, run side by side: 86% cached with the key, 91% without. No benefit shown. Both arms are far above the 56–60% the same v1 code got in earlier runs, so the gateway's cache behavior changes over time (GATEWAY_ISSUES.md #1). |
| 2 | **History rewritten on HTTP 400.** On the first 400, the client cleans every message, which rewrites earlier content. | `core/client.py:45-50` | Rare path. Breaks the prefix once when it fires. |
| 3 | **Compaction rewrites old tool results.** | `core/loop.py:49-56`, `102-105` | **Never fired in v1:** the largest prompt in 4,071 v1 calls was 68K tokens, below the 600K-character (~150K-token) trigger. |
| 4 | **Escalation starts a new conversation.** | `engines/code/engine.py:157-165` | The system prompt and task text are shared, so the first call of attempt 2 is partly cached. Small: 3 of 40 test tasks escalated. |
| 5 | **First call of each task** | Inherent | 1 call in ~30 is cold apart from the shared system and tool prefix (about 1.5K tokens). |

### Effect on cost

For v1 on Verified (399K prompt tokens and 6.5K output tokens per task), list cost per task works out to:

| Cache rate | List cost per task | Change |
|---|---|---|
| 57% | $0.0303 | baseline |
| 85% | $0.0139 | −54% |
| 90% | $0.0110 | −64% |

Billed cost per solved task on the 14 tasks we share with Codex would move from $0.113 to about $0.041–0.052. Codex
is at $0.033 there. Closing the rest of the gap needs solves (section 2), not tokens: we already send fewer tokens
than Codex (399K vs 579K per task).

## 2. Solve-rate gap vs plain DeepSeek

### Scaffolding we add on top of a bare tool loop

| Component | Where | Flag today | What v1 logs show (40 test tasks, `wt/final4/failures.csv`) |
|---|---|---|---|
| Method-heavy system prompt (5-step method, rules) | `engines/code/engine.py:17-39` | none | — |
| Test-command discovery appended to the task | `engine.py:65-72` | `MH_TESTCMD` | — |
| Terminal-mode note | `engine.py:73-78` | `MH_MODE` | — |
| Repo hints (identifier locations) | `engine.py:79-85`, `engines/code/locate.py` | `MH_CODE_HINTS` | — |
| Issue examples run before the start | `engine.py:95-99`, `gates.py:60-79` | `MH_ISSUE_REPRO` | — |
| Nearest existing test shown | `engine.py:100-103`, `gates.py:177` | `MH_NEAREST_TEST` | — |
| Lessons from past tasks | `engine.py:130-132`, `memory.py:65-69` | `MH_MEMORY` | — |
| Scope gate at finish | `engine.py:111-115`, `gates.py:203` | `MH_SCOPE_GATE` | — |
| Related-sites gate at finish | `engine.py:116-120`, `gates.py:238` | `MH_RELATED_SITES` | — |
| Regression gate at finish (up to 2 rejections) | `engine.py:121-125`, `gates.py:114-145` | `MH_REGRESSION_GATE` | — |
| Escalation: reset and second attempt at temperature 0.6 | `engine.py:147-177` | `MH_ESCALATE`, `MH_ESC_TURNS` | 3 tasks escalated, 0 solved, median 55 min each |
| Exploration lock after 25 turns without an edit | `core/loop.py:15`, `170-175` | `MH_MODE=light` only | 2 Terminal-Bench tasks |
| Progress nudges at 12 and 20 turns without an edit; "5 turns left" | `core/guards.py:45-59` | `MH_MODE=light` only | **12 of 20 Terminal-Bench tasks** (4 solved): counts file edits, so it misfires when the work is done by shell commands |
| Repeat-search reminder | `guards.py:61-74` | none | 4 tasks |
| Repeat-failure warning at 3, abort at 5 | `guards.py:76-93` | none | — |
| Error-not-quoted nag | `guards.py:95-107` | none | 6 tasks |
| Finish needs a passing check after the last edit, cited in evidence | `guards.py:110-124` | `require_check` argument | 9 tasks |
| Test-tampering block (any change to a tracked test file) | `guards.py:125-136`, `162-173` | none | **10 of 20 Verified tasks** (9 still solved): adding a test to an existing test file is normal, and each block costs revert-and-recheck turns |
| Deliverables check | `guards.py:139-160` | none | — |
| Python syntax check on edit; read-before-edit; stale-edit check | `core/tools.py:222-276` | none | 1 stale edit |
| Tool output cap (8,000 characters, head and tail) | `tools.py:13-14`, `128-136` | none | — |
| Temperature 0.0 | `engine.py:51` | none | — |
| Benchmark-shaped triggers: gates and repro fire only when the task text has `<issue>` tags or `docker exec -w … bash -lc` | `engine.py:55`, `82`, `94` | `MH_CONTAINER_NATIVE` | Normal users get a different harness than the one benchmarked (see Q6) |

### Ablation design

1. **Flags.** Add a flag to every row that lacks one: the test-tampering mode, progress nudges, exploration lock,
   error-not-quoted, repeat-search, finish-evidence check, edit lint, output cap and temperature. Add
   `MH_PROFILE=bare`, which turns every optional component off at once. Bare means the same tools, a one-paragraph
   system prompt, and no guards except the safety ones: writes stay inside the workdir, and existing tests cannot be
   deleted.
2. **Two endpoints.** Run full v1 and bare on the dev split. Then run leave-one-out: full minus each component, and
   bare plus each component. Components that interact are tested together as a group, then separately if the group
   matters.
3. **Paired design.** Use the same tasks, seeds and order for every arm. Record solves, prompt, cached and output
   tokens, model calls, wall time, and the clean-finish flag.
4. **Decision rule** (pre-registered). Keep a component only if one of these holds:
   - its leave-one-out removal loses solves (McNemar p < 0.10 on the dev split);
   - it cuts cost or time per solved task by more than 10% with no solves lost.

   Otherwise remove it or default it to off.
5. **Dev split only.** Ablations run on a dev split disjoint from the test split. The test split is touched once, at
   the end (see Evaluation protocol).

## 3. Speed (median 15 min on Verified, vs 7 for Codex and 11 for Claude Code)

The call count is similar to Codex: 29 turns median for us (v1 rows) against 27.6 Codex calls per task. So the time
goes into each call or each tool, not into more calls. v1 does not record where the time goes:
- tool seconds are kept only in memory (`tools.py:321-322`);
- the call ledger has no latency column (`eval/ledger.py:195-230`);
- the full transcript is written only when the run ends (`core/loop.py:59-76`).

Candidates, from the code:

| Where | Evidence | Cost per task |
|---|---|---|
| Regression gate | `gates.py:114-131`: runs the related tests twice (stashed baseline, then the change), each up to 600 s, at every gated finish, up to 2 rejections (`engine.py:121-125`) | Up to 4 test runs of up to 10 min each; not measured |
| Issue-example repro before the first call | `gates.py:60-79`: each snippet up to 90 s | Up to a few minutes before turn 1 |
| Test-command discovery | `engines/code/testcmd.py:12-24`: probes up to 60 s | Up to 1 min before turn 1 |
| Escalation | `engine.py:147-177` | 3 of 40 tasks, median 55 min, 0 solved |
| Guard-induced extra turns | `guards.py:125-136` (10 Verified tasks), `guards.py:51-56` (12 Terminal-Bench tasks) | About 2–4 turns each, roughly 1–2 min at ~28 s per turn |
| Tool calls run one at a time within a turn | `core/loop.py:144` | Small for reads; larger when the model issues several test commands |
| Non-streaming requests, 600 s timeout | `eval/ledger.py:236`, `253-266` | Streaming does not shorten a call, but a stalled call is only detected at 600 s |

## 4. Token efficiency

We already send the fewest tokens of the coding agents: Verified 399K per task against Codex 579K and Claude Code
932K; Terminal-Bench 445K against Codex 583K and Junie 888K. With the cache fixed, carried tokens cost $0.003 per
million, so trimming is worth less than caching and must not cost solves.

| Source | Evidence | Note |
|---|---|---|
| Tool results kept verbatim for the whole task | `core/loop.py:195`; compaction only above 600K characters (`loop.py:22`, `102`) | Each 2K-token result is re-sent on every later call |
| Up to 8,000 characters per result (grep up to 400 matching lines, glob up to 2,000 paths) | `tools.py:13-14`, `200-210`, `218-220` | Lower the grep and glob caps, and print the match count |
| Re-reading an unchanged file returns the full text again | `tools.py:159-178` (the hash in `seen` is computed but not used for reads) | Return "unchanged since your last read" when the hash matches (append-only safe) |
| Task-message extras on every task | `engine.py:65-132` | Sent once, cached afterwards; their value is a solve question (section 2) |

## 5. Developer experience (from the code only)

There is no issue tracker in this checkout (no git remote), so no issues are cited.

| Friction | Evidence |
|---|---|
| The usage log path defaults to a machine-specific path (`/home/user/guard/usage.csv`) | `core/wire.py:64` |
| A missing or wrong key surfaces as a raw `RuntimeError: meshpool HTTP 401: {...}`, with no hint about which variable to set | `core/wire.py:112-113`, `eval/ledger.py:290-291` |
| The client silently switches between the eval ledger (budget and usage accounting) and a bare transport with no cost reporting, depending on what is importable | `core/client.py:15-20` |
| The CLI error lists the valid engines without `browser`, although `browser` is accepted | `meshpool_harness/cli.py:36-38` |
| 35 `MH_*` environment flags, with no config file and no listing in `--help` | `grep -o "MH_[A-Z_]*"` over `meshpool_harness/`, `engines/`, `eval/ledger.py` |
| No session resume: history lives in memory, the transcript is written only at the end, and each CLI run gets a random id | `core/loop.py:59-76`, `cli.py:40` |
| Guard events are appended to `failures.csv` in the install directory: it grows without bound and fails on read-only installs | `core/guards.py:12`, `18-26` |
| The strongest code features (repro, regression gate, nearest test) switch on only for benchmark-shaped prompts | `engines/code/engine.py:55`, `82`, `94` |

## 6. Features, ranked by value to the Meshpool roadmap (not built)

| Rank | Feature | Fit | Effort | Why this rank |
|---|---|---|---|---|
| 1 | Cost-aware model routing hook | High: the cheapest-capable-model story is Meshpool's business. A router already exists (`meshpool_harness/router/router.py:16`, `29-46`), but it picks one default model and classifies only the engine. | S–M: a per-call hook (role, turn, recent failures, spend so far) that returns a model id, plus per-model price tables (eval already has them) | Direct effect on cost per solved task, and it is the gateway's product hook |
| 2 | Agent Client Protocol (ACP) support for Zed, JetBrains and T3 Code | High for adoption: it puts the harness inside editors without per-editor work | M–L: a JSON-RPC stdio server mapping session, prompt, tool calls, permissions and streaming onto the loop. It needs session resume (section 5) and streaming. | Large reach, but no effect on the benchmark metrics and depends on resume |
| 3 | Office deck mode (native .pptx) | Medium: off the coding roadmap | S: a deck engine already exists and writes .pptx with python-pptx (`engines/slides/renderer.py`, `requirements.txt:4`). What remains is exposing it as a mode and documenting it. | Mostly built; low marginal value |

## 7. Computer use: MiniWoB++ with all three agents (mw4, measured)

Same 34 tasks, seed, browser tool (including `batch`), model and gateway, run on 2026-11-10:

| Agent | Solved | $ per solved, billed | $ per solved, equal cache | Tokens per task | Cache hit | Median time | Time per solved |
|---|---|---|---|---|---|---|---|
| Meshpool Harness | 32/34 | $0.0029 | $0.0023 | 23,217 | 82% | 42 s | 98 s |
| Plain DeepSeek | 33/34 | $0.0034 | $0.0022 | 25,241 | 77% | 40 s | 70 s |
| Claude Code | 33/34 | $0.0076 | $0.0047 | 81,334 | 80% | 11 s | 25 s |

Every agent missed enter-date. Only we missed click-widget.

**Cause of the click-widget miss (from the transcript):** the snapshot names every `<input>` and every `<textarea>`
as `textbox` (`engines/browser/ctl.py:45`). So "Click on a text widget" was ambiguous on the first,
graded episode, and the model clicked a button.

| ID | Change (flag) | Evidence | Metric | Expected impact | Effort | Risk |
|---|---|---|---|---|---|---|
| B1 | Name fields by their real type: `textarea`, `input[text]`, `input[email]`, ... (`MH_BROWSER_TYPED_ROLES`) | `engines/browser/ctl.py:45`; mw4 click-widget transcript | Computer-use solves (all agents share the tool) | Fixes this miss class; +1 task on mw4 if nothing else changes | S | Low |
| B2 | Our browser engine is slower per solved task than plain DeepSeek (98 s vs 70 s) and Claude Code (25 s). Measure per-step time (S1 applies to the browser engine too) before choosing a fix. | Table above | Time | Unknown until measured | S | None |

## Change table

The effort and risk ratings in this table are judgment calls, not measurements.

| ID | Change (flag) | Evidence | Metric | Expected impact (how estimated) | Effort | Risk |
|---|---|---|---|---|---|---|
| C1 | Send a stable per-conversation `prompt_cache_key` and `user` by default (`MH_CACHE_KEY`, default on) | `eval/ledger.py:245-248`, `core/wire.py:88-91` | Cache, cost | **No effect shown.** Final A/B: 86% with the key vs 91% without (7 dev tasks each, side by side). Keep it only as a harmless default, because Codex sends it; it is not the lever. | S | Low: the field is ignored where unsupported |
| C2 | Session headers like Codex: `session-id`, `x-client-request-id` = conversation id (`MH_SESSION_HEADERS`) | `eval/ledger.py:255-260`; captured Codex request | Cache | Unknown. The sequential probe (`eval/cache_probe.py`, about 7 calls per style after the first) gave plain chat 7/7, cache key 6/7, session headers 4/6. That is no measurable gain, and too few calls to separate the styles, because quiet sequential calls already cache well. Test it under real concurrent load, as an A/B on top of C1. | S | Low |
| C3 | On an HTTP 400, clean only the newest message, so the prefix is not rewritten (`MH_CLEAN_LAST`) | `core/client.py:45-50` | Cache, reliability | Small (rare path) | S | Low |
| S1 | Record per-call latency and per-tool seconds in the run log (`MH_TIMING_LOG`) | `tools.py:321-322`, `eval/ledger.py:195-230` | Speed (measurement) | None by itself; it is required to attribute time | S | None |
| S2 | Regression gate: run the baseline once, in the background, at the start; one change-run per finish; cap at 180 s (`MH_GATE_FAST`) | `gates.py:114-131`, `engine.py:121-125` | Speed | Removes 1–3 test-suite runs per gated finish. The size is measured by S1 before claiming. | S–M | Medium: a slower but complete regression signal may catch more |
| S3 | Escalation off, or capped at 10 min (`MH_ESCALATE`, `MH_ESC_MAX_SECONDS`) | `engine.py:147-177`; 3 of 40 test tasks, 0 solved, median 55 min | Time per solved | −8% total wall time on Verified and Terminal-Bench (3 × ~25 min saved over 40 tasks). No solves lost on test evidence (n = 3; confirmed by ablation). | S | Low |
| Q1 | Test guard "additive" mode: allow new tests in existing test files, block only deleted or changed existing test lines (`MH_TEST_GUARD=additive`) | `guards.py:125-136`, `162-173`; fired on 10 of 20 Verified tasks | Time, solves | About 2–4 turns saved on half of Verified tasks: median −1 to −2 min. Solves ±0 expected (9 of 10 were solved anyway). | S | Low |
| Q2 | Progress guards count state-changing shell commands as progress, not only file edits (`MH_PROGRESS=state`) | `guards.py:50-56`, `core/loop.py:170-175`; fired on 12 of 20 Terminal-Bench tasks (4 solved) | Solves, time | Removes wrong "edit now" nudges on terminal tasks. Solve effect unknown; ablation decides. | S | Low |
| Q3 | Ablation flags for every component, plus `MH_PROFILE=bare` | Section 2 table | Solves, cost, time | Enables the measurement; no direct impact | M | None |
| Q4 | Temperature flag (`MH_TEMPERATURE`, default 0.0 unchanged) | `engine.py:51`, `164` | Solves | Unknown; tested in the ablation | S | Low |
| Q5 | Trim the system prompt to what ablation shows helps (`MH_SYSTEM=short`) | `engine.py:17-39` | Solves, tokens | Unknown; plain DeepSeek wins with a minimal prompt (12 vs 10 on 14 Verified tasks), which motivates the test | S | Medium |
| Q6 | Trigger repro, regression gate and nearest test by capability (a git repo plus a discovered test command), not by `<issue>` or `docker exec` text (`MH_GATES_BY_CAPABILITY`) | `engine.py:55`, `82`, `94` | Validity, solves in normal use | Benchmarked behavior then equals normal-use behavior. Required by the "no benchmark-specific hints" rule. | M | Medium: gates may fire on more tasks |
| T1 | Unchanged re-read returns a short note (`MH_DEDUP_READS`) | `tools.py:159-178`, `173` | Tokens | Unknown share; measure re-read frequency from transcripts first (`loop.py:69-73`) | S | Low |
| T2 | Lower the grep and glob caps to 4,000 characters, with match counts (`MH_SEARCH_CAP`) | `tools.py:13-14`, `200-220` | Tokens | Small after C1 (carried tokens are cheap when cached) | S | Low: the model may need a narrower search |
| D1 | Clear error for a missing key or base URL; a portable default usage-log path; correct engine list in the CLI error; `meshpool config` listing every flag | `wire.py:64`, `112-113`; `cli.py:36-38` | Developer experience | — | S | None |
| D2 | Session resume: write the transcript after every turn; `--resume <id>` reloads it (append-only, cache-safe) | `core/loop.py:59-76`, `cli.py:40` | Developer experience, reliability | Prerequisite for ACP | M | Low |

## Evaluation protocol

**Task sets**
- At least 50 tasks per benchmark (SWE-bench Verified, Terminal-Bench 2.0), drawn at random with a recorded seed,
  disjoint from every task used during development, and frozen before any arm runs.
- Every agent runs the identical task list: Meshpool Harness, Codex CLI, Claude Code, Junie and plain DeepSeek.

**Runs**
- 3 runs per task per agent, on the same model, gateway, turn cap, time cap and grader.
- The order is interleaved by task, so gateway conditions hit all agents equally.
- Infrastructure failures (disk, registry, gateway 5xx and 429, refused keys) are rerun, never scored, and listed.

**Metrics** (per agent and benchmark)
- Solve rate with a 95% confidence interval, from a task-level bootstrap, because the 3 runs of a task are not
  independent.
- Cost per solved task, billed and at an equal cache rate (one shared rate for every agent).
- Cache hit rate, overall and excluding each task's first call.
- Median time per task, and total time per solved task.
- Finished-cleanly rate: the run ended on its own inside the cap.

**Comparisons**
- Paired on the same tasks: the difference in solve rate with a bootstrap confidence interval, and McNemar on the
  per-task majority outcome.
- With 50 tasks × 3 runs and about 20% discordant tasks, the 95% interval on a solve-rate difference is roughly
  ±10 points. Smaller differences are reported as "no difference shown".

**Validity rules**
- No benchmark-specific prompts, files or task hints. The harness config is the same one shipped for normal use, and
  is committed before the run.
- The benchmark runner and scoring are unchanged.
- Changes are chosen on the dev split only. The test split is run once per release candidate, and its numbers are not
  used to choose further changes.

**Cost of the protocol (rough):** 2 benchmarks × 50 tasks × 3 runs × 5 agents is 1,500 runs. At $0.04–0.10 billed per
run after C1, that is about $60–150.

## Top 3 to build first

The final cache A/B changed the first item. A request change on our side did not move the cache rate: the key arm got
86%, the control 91%. The same v1 code now caches at 86–91%, against 57% in the earlier runs, so the gateway's
behavior over time explains much of the measured cost gap. Fair cost comparisons therefore need every agent run
interleaved at the same hours, which the evaluation protocol already requires.

1. **E0: same-time re-measurement before any cache work.** Run v1 on the shared Verified and Terminal-Bench tasks,
   interleaved with Codex, Claude Code and plain DeepSeek. This shows how much of the cost gap remains when gateway
   conditions are equal. At tonight's cache rate, v1 cost $0.027–0.031 per solved task on dev, against Codex's $0.033
   on test (different tasks, so this is not yet a comparison). About $3 for 40 tasks.
2. **S1 + S3 + S2: time instrumentation, the escalation cap, and the faster regression gate.** Speed is now the
   clearest gap: 15 vs 7 min median on Verified, at a similar number of model calls. S1 makes the breakdown
   measurable. S3 removes a measured 55-minute path that solved nothing. S2 removes duplicate test-suite runs at
   finish.
3. **Q1 + Q2 + Q3: misfiring guards fixed, plus the ablation flags.** The two guards fire on half of all test tasks,
   for reasons that are wrong. The flag framework then lets the dev-split ablation decide which scaffolding to keep
   against the plain-DeepSeek baseline. This is the path to the solve-rate gap.

C1 (cache key) stays a one-line, low-risk default, but it is no longer ranked for impact.
