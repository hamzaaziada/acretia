# Phase 2 build spec (planning layer; PROMPT.md stays the source of truth)

Written by the reviewing engineer so the builder executes a fixed design instead of inventing one.
Where this spec and PROMPT.md disagree, PROMPT.md wins. Build in the order of section 9.
Language: Python 3 (python-pptx, openpyxl, pandas and LibreOffice tooling are Python-native).

## 0. Corrections from phase 0 review (fix first)
- recon.md says `junie --version` / `--help` print nothing useful. False: both print normally when run
  through `~/.local/bin/junie` (version 26.11.3, build 3959.5). Re-run, fix the section, and record the command.
- pricing.json: keep the official numbers but add a `measured` block per model, calibrated from
  x-litellm-key-spend deltas over at least 5 real calls (cost = delta spend; fit input/output rates).
  Meshpool's billing is what we pay. If measured and official differ by >10%, ledger costs use measured.
- Budget baseline is the external guard's start value ($0.003942), see OPERATOR_NOTE.md.

## 1. Package layout
```
meshpool_harness/
  __init__.py
  cli.py              # `python -m meshpool_harness run|route|serve|eval`
  server.py           # OpenAI-compatible POST /v1/chat/completions wrapper over route+run (stdlib http.server)
  core/
    client.py         # ModelClient: wraps eval/ledger.Ledger; MockClient replays eval/fixtures/*.jsonl
    prefix.py         # build_prefix(engine, profile) -> byte-stable system+tools; sha256 logged per call
    tools.py          # 8 core tools + spawn + need_context + load_skill; JSON-schema validation
    loop.py           # agent loop: turns, caps, truncation, compaction, finish-with-evidence
    guards.py         # failure-catalog guards as code (section 6)
    planner.py        # task graph JSON (job packets) + validation
    orchestrator.py   # schedule jobs (parallel/deps), merge, verifier, budgets
    repomap.py        # move/reuse eval/repo_map.py
    artifacts.py      # run dir layout, truncated-output files
  router/
    rules.py          # deterministic rules
    router.py         # rules -> optional classify call -> Route JSON; logs routing.csv
  profiles.py         # load profiles/<family>.yaml, pick by model id, flag override
engines/
  base.py             # Engine interface
  code/ slides/ sheets/ data/ general/   # each: engine.py, skill.md, planner.md, checks.py, tools.py(optional)
profiles/ deepseek.yaml glm.yaml kimi-k3.yaml claude.yaml openai.yaml notes.md
tests/                # pytest, offline only (MockClient); must pass before any live run
```

## 2. Core contracts (keep these exact so pieces fit)
```python
@dataclass
class Route:            # router output
    engines: list[str]  # ordered chain, e.g. ["data","slides"]; single engine = 1 item
    profile: str        # family name, e.g. "deepseek"
    models: dict        # {"planner":..., "worker":..., "verifier":...}
    confidence: float
    reason: str
    used_model_call: bool

@dataclass
class TaskRequest:
    request: str
    files: list[str]    # absolute paths
    output_format: str | None
    workdir: str        # run directory; engines write outputs here
    task_id: str

@dataclass
class EngineResult:
    ok: bool
    artifacts: list[str]     # files produced
    answer: str              # final text
    evidence: list[dict]     # [{"check": str, "cmd": str, "passed": bool, "output_tail": str}]
    cost: float              # from ledger rows with this task_id
    turns: int
    subagents: int

class Engine:
    name: str
    def skill(self) -> str: ...                       # loaded lazily via load_skill
    def checks(self, req, result) -> list[dict]: ...   # deterministic verifier checks
    def run(self, req: TaskRequest, profile, client) -> EngineResult: ...
```
Chains: orchestrator runs engines in order; engine i+1 gets only engine i's `artifacts` + `answer` as files/inputs.

## 3. Tools (strict JSON schemas, additionalProperties false)
read_file(path, start, end) | grep(pattern, path, glob) | glob(pattern) | edit(path, old, new) — fails if `old`
not found exactly once | write_file(path, content, append=false) | bash(cmd, timeout_s<=600) — output capped,
head+tail kept, full output saved under run dir and path returned | run_tests(cmd) | finish(answer, evidence[])
plus spawn(job_packet) and need_context(paths, reason) for workers, load_skill(name).
Invalid call -> precise error string back to the model, counted in failures.csv as tool_format.

## 4. Prompt / cache layout
[byte-stable prefix: system text + tool schemas + skill index] then [task/job packet] then [history].
No timestamps, ids, file listings in the prefix. Log prefix sha256 per call; a test asserts two workers of the
same engine+profile get identical prefix bytes. Cache hit rate = 1 - (actual spend delta / cost at full input price),
per call, logged in ledger.

## 5. Engines — minimum viable behavior and their deterministic checks
- code: reproduce (failing test/script) -> edit -> run tests. Checks: tests run and exit 0; diff does not touch
  tests unless asked; lint if repo has config.
- slides: model emits JSON deck spec only (schema in engines/slides/spec_schema.json; 10 slide types).
  renderer.py (python-pptx) owns layout: 13.333x7.5in, 12-col grid, 0.5in margins, 2 fonts max, palette in
  theme.py, native charts/tables, text fit via PIL font metrics (shrink to min size, then split slide).
  qa.py: soffice -> pdf -> png; checks out-of-bounds, overlap, empty placeholders, fonts<=2, contrast, slide count.
  Vision review of PNGs max 2 rounds.
- sheets: openpyxl, Inputs / Calc / Outputs sheets, named ranges, formulas only in Calc/Outputs.
  qa.py: soffice headless recalc, scan for #REF!/#DIV/0!/#VALUE!/#NAME?/#N/A, circular refs, hardcoded numbers
  in Calc/Outputs.
- data: quant runs code in a subprocess and logs every printed number to numbers.jsonl; answer check fails on
  any number not in that log (tolerance for rounding). Qual: codebook json, excerpts with source ids, quote
  checker script (exact substring match after whitespace normalization).
- general: core tools only, finish with evidence.

## 6. Guards (code, not prompt text) — each with a unit test
finish_without_check, stale_edit, test_tampering, repeat_failure(3x same cmd+error -> force strategy change),
error_not_quoted (next turn after failure must contain the key error line), invented_symbol (run checker after
edit batch), untraceable_number, fabricated_quote, slide_overflow, excel_hardcode, excel_error, spec_mismatch.
Every trigger writes failures.csv: ts, model, profile, task_id, category, caught(bool).

## 7. Router
Rules first: file extension, output words (deck/slides/pptx; excel/xlsx/spreadsheet/model; csv/analyze/
interview/survey/themes; fix/test/bug/repo/traceback/function), repo presence (.git / pyproject / package.json
in workdir), mixed signals -> chain ordered data->sheets->slides. Confidence < 0.6 -> one classify call on
the cheapest model (max_tokens 60, JSON). Still < 0.5 -> general. CLI flags --engine/--model override.
Score on eval routing dev set after every change; write experiments.csv row.

## 8. Product surface (what users actually touch)
- `python -m meshpool_harness run "make a 10 slide deck on X" --files a.csv --out ./out` prints route, cost,
  artifacts, evidence summary; exit code 0 only if all checks passed.
- `python -m meshpool_harness route "..."` prints Route JSON with no engine run.
- `python -m meshpool_harness serve --port 8787` OpenAI-compatible; response content = answer + artifact paths.
- Clean errors (no tracebacks) for: missing files, unreadable files, empty request, budget exhausted,
  meshpool 5xx (retry 2x with backoff, then a clear message), unknown engine/model flags.
- readme.md with copy-paste quickstart for each engine.

## 9. Build order and done criteria (each must be proven by a command before the next)
1. core/client + MockClient + tests (`pytest -q tests/test_client.py`).
2. tools + guards + loop with MockClient (`pytest -q tests/test_loop.py tests/test_guards.py`).
3. code engine + deepseek profile; one live dev task end to end.
4. Junie comparison runner already exists from phase 1; run harness on 1 coding dev task, then the dev subset.
5. slides renderer + qa offline on a hand-written spec (`pytest -q tests/test_slides.py`), then 1 live dev task.
6. router rules + routing dev accuracy printed.
7. sheets, then data, same pattern (offline tests first, then 1 live task, then dev subset).
8. planner/subagents; measure on/off on dev.
9. CLI + server + error handling (`pytest -q tests/test_cli.py`).
Commit after each step with the proving command in the message. Update PROGRESS.md after each step.

## 10. Review loop
After phase 2 the reviewing engineer stress-tests the product (all entry points, mixed chains, bad inputs,
large decks, messy CSVs, real repos) and writes REVIEW_FINDINGS.md. The next build session fixes every
finding marked must-fix before any new scope, then re-runs the dev subsets.
