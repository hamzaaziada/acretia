# Product requests (session F → engine sessions)

Interface changes the product app needs. Each names the target session. The owner edits its own files; session F never does.

| # | To | Request | Why | Status |
|---|---|---|---|---|
| PR-1 | Session A (S2.2 contracts) | Add optional telemetry fields to `JobStep` in `om/contracts.py`: `started_at` (utc_timestamp), `finished_at`, `seconds` (number ≥ 0), `tokens` (int ≥ 0), `cost_usd` (number ≥ 0), `engine` (string). Add `wall_seconds` and `source` (`app|email|schedule|api`) to `Job`. All optional, so existing round-trips still pass. | D-032 job telemetry: per-step time/tokens/cost in the Job contract and the UI. Until it lands, `om/api/jobs.py` keeps these in its own `steps_json`. | open |
| PR-2 | Session B (S3) | Declare `fonttools`, `arabic-reshaper`, `python-bidi` (and Pillow) in `requirements-extras.txt` / `pyproject.toml`. On a fresh cloud container 13 `test_deck_fit`/`test_deck_rtl` tests fail with `ModuleNotFoundError: fontTools` until they are pip-installed by hand. | Keeps the full suite green on a fresh container, which every session runs before pushing. | open |
