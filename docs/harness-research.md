# Agent harness: state of the art and Acretia design (research, 2026-11-16)

Labels: **[E]** evidence (paper, benchmark, measured), **[V]** vendor description, **[I]** inference. Some sources were seen only through secondary summaries; those are marked. Re-verify anything before quoting it externally.

## Bottom line

1. **Hybrid beats either pure form.** The pipeline is a fixed, code-owned workflow, and agent loops are bounded inside individual steps.
   - Anthropic's "workflows vs agents" guidance supports this ([building effective agents](https://www.anthropic.com/engineering/building-effective-agents)).
   - Hebbia describes "deterministic agentic steps" ([case study](https://claude.com/blog/working-at-the-frontier-how-hebbia-builds-ai-for-financial-diligence-that-cant-miss-a-detail)) [V].
2. **Excel and deck failures are mostly about formula/code correctness and consistency across artifacts.** BankerToolBench: about 41% of failures were code or formula bugs [E, secondary: [summary](https://www.themoonlight.io/review/bankertoolbench-evaluating-ai-agents-in-end-to-end-investment-banking-workflows)]; 0% client-ready ([arXiv 2604.11304](https://arxiv.org/abs/2604.11304)). Verifiers must be deterministic and must run on the real workbook and deck.
3. **The harness matters about as much as the model.** On MBABench 2.0 the same model scored 15.8% in one harness and 7.9% in another; the top pass rate was 15.8% ([Snorkel](https://snorkel.ai/leaderboard/mbabench-2/)) [E].
4. **Routing has real but modest headroom.**
   - A coarse router adds about +4.5 points over the best single model; a best-of-10 oracle adds +13.2 ([Rogo BFB](https://rogo.com/news/introducing-the-big-finance-benchmark)) [V].
   - Cost spread on the same task is about 60× ($1.26 vs $0.02, [Model Broker](https://rogo.com/news/introducing-model-broker)) [V].
   - So: start cheap and escalate when a verifier fails.
5. **External feedback fixes errors; self-critique doesn't.**
   - Intrinsic self-correction gives little and can make results worse ([arXiv 2310.01798](https://arxiv.org/pdf/2310.01798)) [E].
   - Tool-interactive checking (CRITIC) gives about +7 points, and the gain disappears without the tools ([ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/fef126561bbf9d4467dbb8d27334b8fe-Abstract-Conference.html)) [E].

## How leading products describe their harnesses

- **Hebbia** [V]:
  - one answer per Matrix cell, for traceability;
  - meta-prompting across hundreds of documents;
  - moving to the Claude Agent SDK for "smaller, repeatable, checked steps";
  - head-to-head evaluation of every new model, tracking citation match separately from accuracy.
  - No primary source exists on Max internals.
- **Rogo** [V]:
  - Model Broker routes by quality, speed and cost, with failover ("70% of enterprise queries should use a lightweight model").
  - Pre-configured finance skills, so the model doesn't rediscover workflows.
  - Big Finance Bench: 928 questions, rubrics of about 17 weighted items tagged Retrieval / Definition / Calculation, and a "cost per correct answer" metric.
- **Shortcut** [V]: planner → data extraction → cell execution → formatting → verification; a cell-level audit log with undo. "90%+ accuracy" is unmeasured.
- **Daloopa** [V]: agents score about 90% on structured, source-linked data vs about 19–20% on web sources. **Data tools matter more than the agent loop.**
- **Coding and research agents** [V]:
  - **Claude Code:** a single-threaded loop; subagents run in isolated contexts and return summaries.
  - **Cursor:** tunes the harness per model.
  - **Manus:** cache-hit rate is the top production metric; stable prefixes; append-only context; restating the todo list at the end of context; keeping failed actions in context.
  - **gpt-researcher:** planner → per-question executors → publisher.
  - **dexter:** plan / act / validate / answer.

## Patterns and evidence

- **Workflow vs agent.**
  - Agents are inconsistent across repeated runs: τ-bench pass^8 is under 25% in retail ([arXiv 2406.12045](https://arxiv.org/abs/2406.12045)) [E].
  - Structure is cheap and competitive (Agentless) [E].
  - The planner's output should be a **typed DAG executed by code** [I].
- **Subagents.** Anthropic's multi-agent research system scored +90.2% over single-agent Opus, but at about 15× the tokens ([post](https://www.anthropic.com/engineering/multi-agent-research-system)) [E-internal]. Cognition warns that parallel writers make conflicting decisions ([post](https://cognition.com/blog/dont-build-multi-agents)) [V]. Reconciliation: **fan out for read-only, independent work; one writer per artifact** [I].
- **Verification.**
  - Use the ladder: schema → recalculation/lint → tie-outs → cross-artifact ID match → LLM critic. The critic judges only, and runs on a **different model family**.
  - LLM judges have position and verbosity bias ([arXiv 2306.05685](https://arxiv.org/pdf/2306.05685)) [E], so use order-swapping, rubrics and human calibration.
- **Tools** ([writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents); [code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)):
  - few high-impact tools;
  - namespacing;
  - concise/detailed response modes;
  - actionable errors;
  - output caps;
  - progressive disclosure (about 98.7% fewer tool-definition tokens).
  - **Caveat:** JSON-schema masking can suppress tool calls on open-weight models; two-pass (free reasoning, then formatting) restored them ([paper](https://huggingface.co/papers/2606.25605)) [E].
- **Context** ([context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)):
  - compaction, tool-result clearing, structured notes, just-in-time retrieval;
  - prompt caching (reads about 0.1×; verify current prices);
  - measure the cache-hit rate per gateway route;
  - **never summarise numbers.** Numbers live in the ledger, referenced by id.
- **Routing.** FrugalGPT and RouteLLM gains degrade when the task mix shifts [E]. A cascade triggered by verifier failure is more robust than predicting difficulty up front [I].
- **Budgets and checkpoints.** Resume from the failing step, and save the plan before context overflows [E-ish]. Keep durable state ourselves (a content-hashed step table), not in a framework [I].
- **Hallucinated numbers.** BankerToolBench recorded an agent inventing data after finding nothing [E, secondary]. Rule: **models never output numbers into deliverables; they output `{{ev:id}}` references and code renders them.** A bare number is a lint error [I].
- **Evals.**
  - Start with about 20 real tasks; effect sizes are large [E-ish].
  - Use rubric partial credit (Retrieval / Definition / Calculation).
  - Measure pass^k for reliability.
  - Use held-out splits when tuning prompts and tools.

## Finance-specific lessons

- **Spreadsheets:**
  - MBABench: performance falls sharply beyond a few chained calculations ([arXiv 2605.22664](https://arxiv.org/abs/2605.22664)) [E].
  - SpreadsheetBench 2: best model 34.9% overall, 12% on debugging [E, summary].
  - So build in layers: inputs, then calculation blocks, **recalculating and checking after each block**. Never have the model write a whole formula chain in one shot.
- **Decks:**
  - PPTAgent (edit from references) and AutoPresent/SlidesBench [E].
  - PPTEval is criticised as optimistic; PresentBench uses checklists [E].
  - So: render from a template, run deterministic layout lint, and check that every number references its source.
- **BankerToolBench:**
  - consistency across artifacts (Excel/PPT/Word) is a key obstacle;
  - static models didn't recalculate when an input changed, so a **scenario-switch test** belongs in every model gate.
- **Vals Finance Agent:** a small tool set (edgar_search, web_search, parse_html_page, retrieve_information, calculator, price_history); parse, then retrieve; a calculator tool, because models shouldn't do arithmetic.
- **Diligence:** one question × one document per cell, with a citation, then a synthesis step over the cells.

## Cheap-model strategies (evidence is thin; indirect)

- Decompose until each call is a single job that can be checked.
- Make failures cheap to detect: schema, recalculation, source match.
- Retry with targeted feedback: the cell, expected vs actual.
- Specialise prompts and tool formats per model.
- Two-pass formatting on open-weight models.
- Cascade up a tier on repeated failure.
- Keep cheap models on work whose output fits a spec (extraction, classification, slide-spec filling). Frontier models handle planning, ambiguous judgement and the final critic, until our own evals say otherwise.

## Proposed Acretia harness (adopted as Stage S9)

- **Components:**
  - Intake/Router: rules plus a cheap classifier → workflow;
  - Planner: a typed StepGraph DAG; fixed workflows only fill in parameters;
  - Executor: a bounded ReAct loop per step; one writer per artifact; pure-code steps call no model;
  - MCP tool registry: strict schemas, per-step allowlists, progressive disclosure;
  - Verifier ladder;
  - Evidence ledger: the only source of numbers;
  - Memory: step table, artifact store, notes;
  - Budget governor: tokens, dollars, time, calls, retries;
  - Checkpointer: content-hashed, resumes from the first step that didn't pass;
  - Model adapter + per-model profiles;
  - Traces.
- **Fixed workflow vs open agent:**
  - fixed: comps (fan out per company), DCF/LBO (template formulas, recalculation after each block), deck (spec → render → lint → number references), VDR matrix (cells + synthesis), earnings update;
  - open agent inside a workflow shell: the research memo.
- **Model tiers:**
  - T0 code (arithmetic, formulas, rendering, linting);
  - T1 cheap/open (extraction, classification, spec filling, routing);
  - T2 mid (drafting, retrieval);
  - T3 frontier (open planning, judgement, critic, escalations).
  - Escalate one tier after two failures with the same finding.
  - The critic runs on a different provider.
  - Fail over on errors and rate limits.
  - Re-baseline whenever a new model ships.
- **Context and cost:**
  - stable prefix; deterministic tool order; append-only context; cache markers; cache-hit logging;
  - large outputs stay in the sandbox;
  - restate the plan and findings at each step;
  - compaction keeps evidence ids.

## Harness eval plan

- **Suites:**
  - golden tasks: 20, then 40–60 across the six workflows;
  - public anchors: MBABench/SpreadsheetBench 2 subset, Vals Finance Agent, Big Finance Bench (harness on GitHub);
  - a **seeded-error suite** to measure verifier recall;
  - a held-out split.
- **Metrics:**
  - **silent-error rate (headline)**;
  - task success (deterministic checks plus rubric);
  - recovery rate (retry / escalate / fallback);
  - pass^5;
  - cost per correct deliverable;
  - tokens by tier; cache-hit rate; p50/p95 latency; tool calls; steps.
- **Ablations** (same golden set, ≥ 3 seeds each):
  1. verifiers off / deterministic only / deterministic + critic;
  2. fixed workflow vs open agent;
  3. planner on or off;
  4. fan-out vs sequential;
  5. caching and result-clearing on or off;
  6. model tier policy vs all-frontier vs all-cheap;
  7. single model vs router vs verifier cascade;
  8. constrained decoding vs two-pass on open-weight models;
  9. formulas from templates vs written by the model;
  10. generic retries vs structured feedback.
- **Gating:**
  - **block** a merge if silent errors rise by more than 0.5 pp (or by any amount on the seeded suite), success falls by more than 2 pts, pass^5 falls, or a number appears without a ledger reference;
  - **warn** if cost per correct rises by more than 15% or p95 latency by more than 25%;
  - head-to-head on every new model; a weekly drift run;
  - human review of ≥ 10% of golden runs per release.
  - Calibrate the thresholds after two weeks of baseline data.

## Build order

1. Evidence ledger + the numeric-reference lint.
2. Workbook verifier (recalculation, tie-outs, scenario switch), then the deck layout lint.
3. StepGraph executor with checkpoints and budgets.
4. Router + model profiles, with the eval harness from day one.
5. Fan-out for comps and VDR.
6. Open-agent shell for memos, last.

## Known gaps

- No primary sources on the internals of Hebbia Max, Rogo Felix, Model ML or Shortcut.
- The BankerToolBench 41/27% split is from a secondary source.
- MBABench numbers per chain length are not public.
- No direct retry-rate data for gpt-oss, GLM, Kimi or DeepSeek.
- Several leaderboard model names are unverified.
