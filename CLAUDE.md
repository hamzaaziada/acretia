# Working in this repo (Acretia)

Read [PLAN.md](PLAN.md) for the milestones. [PROGRESS.md](PROGRESS.md) is the source of truth for what is done.

## Start of every session

1. Run `git status` and `git log -n 15 --oneline`. Read `PROGRESS.md`, `DECISIONS.md` and `AGENT_LOCK.md`.
2. Run `python3 -m unittest discover -s tests -q`. It must be green before you start.
3. Claim the next unowned packet in `AGENT_LOCK.md`, then commit.

## Rules

- **Autonomous.** Don't stop to ask about implementation details. Resolve them from contracts, tests or the strictest banking standard, and log the choice in `DECISIONS.md`.
  - This does not override safety. Never put secrets in the repo, never push to a remote other than `origin`, and never send data to hosts other than those named in `DECISIONS.md`.
- **Read minimally.** Use `grep -n` and 50–120-line slices. Run tests with `-q`.
- **Deterministic gates before any LLM or vision call.** In order: formulas via `om.formula`, workbooks via `om.modelcheck`, LibreOffice recalculation via `om.consistency.recalc`, layout via `om.spacing`.
- **Standard-library core** (see D-001). Optional packages go behind `try: import` with a graceful fallback, and are listed in `requirements-extras.txt`.
- **No live LLM in tests.** Use replay fixtures in `tests/fixtures/llm/`.
- **Models are written by code** (D-005). Never let an LLM type a historical number or a formula into a workbook.
- **Commit at the end of each verified packet.** Message format: `M<N> P<N.x>: <what>`. Push to `origin`.

## Commands

```bash
python3 -m unittest discover -s tests -q          # full suite (offline)
python3 open_multiples.py model AAPL              # integrated 3-statement + DCF, graded
python3 open_multiples.py grade path/to/model.xlsx
python3 open_multiples.py bench AAPL MSFT --libreoffice
python3 scripts/verify_m<N>.py                    # milestone gates
python3 open_multiples.py serve --port 8791       # local web app
```

## Data

- SEC data is cached under `data/raw/` (not committed). Tests must use synthetic fixtures, such as `tests/test_model3.py::synthetic_companyfacts`, never the network.
- `SEC_USER_AGENT` comes from the environment.
