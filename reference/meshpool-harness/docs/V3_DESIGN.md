# Meshpool Harness v3: design

v3 is one tested bundle, switched on with `MH_PRESET=v3`. Each part has its own flag, so any part can be turned off
and measured separately. Every part comes from either our own run evidence or a published result from a top
open-source harness. Sources are listed at the end.

## 1. What we are fixing (from v2 head-to-heads on DeepSeek V4.1 Flash)

| Gap | Evidence |
|---|---|
| **Solves only tie the best agent** | Verified 17/19 (tied with plain DeepSeek); Terminal-Bench 9–10/20 (plain DeepSeek 10, Codex 9); MiniWoB++ 34/34 (tied) |
| **Inconsistent runs** | Our two Terminal-Bench runs solved 12 different tasks between them, but only 9–10 each; 5 of 20 tasks flipped |
| **Early wrong finishes** | polyglot-rust-c finished in 4 min, openssl-selfsigned-cert in 2 min, both wrong; plain DeepSeek kept going and solved them |
| **Turn budget runs out** | 91% of turns issue one tool call; median 44 of 60 turns used; 6 of 26 runs hit the cap inside trial-and-error loops (for example raman-fitting re-ran nearly the same fitting script more than 50 times) |
| **Computer-use speed** | 17 s per solved task against Claude Code's 14 s |

## 2. What we keep (v2's leads)

These must not regress:
- **The minimal loop and short prompt.** Forced checks lost in our tests and in Refact's.
- **Streaming,** which cut the average model wait per call from 24.5 s to 7.5 s.
- **Fewest tokens** of every agent tested.
- **Clean finishes:** every run ends on its own inside the cap.
- **The shared browser tool:** batch actions, label targets, typed roles, date fix.
- **Retries** for 5xx, 429 and the gateway's random 400.

## 3. The v3 parts

| # | Part (flag) | What it does | Source | Gap it targets |
|---|---|---|---|---|
| 1 | **Required todo list** (`MH_TODO`) | The model lists the task's concrete requirements (files, paths, formats, outputs, behaviours) with a `todo` tool and ticks them off. `finish` is refused while items are open (at most twice, so it can never deadlock). | ForgeCode: 38% → 66% on Terminal-Bench 2 after enforcing it, their largest reported gain | Early wrong finishes |
| 2 | **Environment snapshot** (`MH_ENV_SNAPSHOT`) | Before the first call: working directory, file listing, tool versions, disk and memory. Added to the task. | Meta-Harness and Factory Droid: saves 2–5 exploration turns | Turn budget |
| 3 | **Loop detection** (`MH_DOOM`) | 3 identical tool calls in a row, or a 2–3 call pattern repeated 3 times, produces one reminder to change tool, arguments or approach | ForgeCode doom-loop hook | Trial-and-error loops |
| 4 | **Loop breaker** (`MH_STALL`) | 12 turns with no file change and no new passing command produces one nudge | Our transcripts | Trial-and-error loops |
| 5 | **Turn-budget note** (`MH_TURN_NOTE`) | 15 turns before the cap: make the deliverable exist now | Our transcripts (capped runs end with nothing delivered) | Turn budget |
| 6 | ~~Evidence-driven second attempt~~ (removed from the preset after the dev split; see below) (`MH_EVIDENCE_RETRY`) | Repository tasks only. If attempt 1's log has no check that failed before the first edit and passes after the last, a second attempt uses only the unused turns and must reproduce first. Kept only with that proof; otherwise attempt 1 is restored exactly. | Agentless, Aider, OpenHands: extra samples only when not plausible; Aider got about 90% of its gain from 2 attempts | Inconsistent runs, wrong fixes |
| 7 | **Browser prefetch and same-turn finish** (`MH_BROWSER_PREFETCH`, `MH_BROWSER_FINISH_SAME_TURN`) | The first page view goes into the prompt. The model may finish in the same turn as a final action; a finish after a failed action in that turn is refused. | Our MiniWoB++ runs: 4.9 → 4.0 calls per task | Computer-use speed |

**Built but left off by default:**

| Part | Why it is off |
|---|---|
| One-call finish reviewer (`MH_REVIEW`) | Refact found self-critique did not help |
| Light end-state check (`MH_ENDSTATE_CHECK`) | Lost on our dev split |
| Verify-before-finish rule (`MH_GUARDS` + `finish_check`) | Lost on our dev split |
| Two attempts on every task (`MH_ENSEMBLE=2`) | About doubles cost per task |
| Evidence-driven second attempt (`MH_EVIDENCE_RETRY`) | Dev split: it fired on pytest-7490 and django-14771, where attempt 1 was already right. Both second attempts lacked the before/after proof and were discarded. On pytest it used 4× attempt 1's tokens. The trigger is too weak: correct fixes rarely re-run the exact failing command. |

## 4. Next candidates (not built yet, ranked)

1. **Pick between attempts with existing tests.** When the second attempt runs, run the repository's existing
   tests that passed before the patch, and drop the candidate that breaks them. Agentless: 77 → 81 fixes for about
   $0.01 per issue.
2. **A standalone reproduction test as the chooser.** Agentless: 81 → 96 fixes, its largest single component.
3. **Several commands per turn.** A bash variant that takes a list of commands, each with its own timeout
   (Terminus 2 / KIRA), aimed at our 91% single-call turns.
4. **Varying reasoning effort by phase.** High for planning and verification, low for execution (ForgeCode). This
   needs a provider setting for DeepSeek's thinking mode.
5. **Collapsing old command outputs.** SWE-agent gained 3 points from showing only the last 5 outputs in full.
   It costs cache hits, so test it against cost.

## 5. How v3 is judged

1. **Dev split first.** Compare against the v2 + streaming baseline on the same 11 dev tasks; keep v3 only under the
   pre-registered rule.
2. **Then one head-to-head** on the frozen test tasks, with v3, Codex CLI, Claude Code and plain DeepSeek all
   running at the same time.
3. **Report:** solves, billed and equal-cache cost per solved task, time per solved task, clean finishes and cache
   hit rate.
4. **Sample size:** a single run moves about ±2 tasks out of 20, so a solve-rate claim needs repeated runs or a
   larger task set.

## Sources

**SWE-bench harnesses:**
- Agentless: github.com/OpenAutoCoder/Agentless; arxiv.org/html/2407.01489v2, Tables 3–4.
- Trae Agent: se-research.bytedance.com/blogs/trae-on-swe-bench-verified-71; arxiv.org/html/2507.23370v1.
- Aider: aider.chat/2024/05/22/swe-bench-lite.html.
- OpenHands critic: openhands.dev/blog/20260305-learning-to-verify-ai-generated-code.
- SWE-agent: arxiv.org/html/2405.15793v3.
- Refact: refact.ai/blog/2025/open-source-sota-on-swe-bench-verified-refact-ai/.

**Terminal-Bench harnesses:**
- ForgeCode: forgecode.dev/blog/benchmarks-dont-matter/ and /blog/gpt-5-4-agent-improvements/; code in
  github.com/antinomyhq/forge (pending_todos.rs, doom_loop.rs).
- Terminus-KIRA: github.com/krafton-ai/KIRA.
- Meta-Harness: github.com/stanford-iris-lab/meta-harness-tbench2-artifact (_gather_env_snapshot).
- Factory Droid: factory.ai/news/terminal-bench.
- Harbor and Terminus 2: github.com/laude-institute/harbor.

Some of these pages were read from search snippets or cloned code, because direct fetches were blocked. Treat their
numbers as what the authors report.
