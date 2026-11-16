# S4 Excel engine: conventions every packet follows

These are binding for every S4 worker. Read this file once, then only the targeted slices your packet names.

## Builders (LBO, merger, comps, and anything else that writes a model)

- Write with `om.xlsx.Workbook` / `Sheet.set(...)`. Never write xlsx XML by hand in a builder.
- Every number and formula is written by code (D-005). The LLM never types a number.
- Colour code via `kind=`: `input` (blue, yellow fill: assumptions), `hist` (blue: figures as filed, with a source comment and filing link), `calc` (black formula on the same sheet), `link` (green: formula referencing another sheet; `Sheet.set` infers this). Do not override colours on numbers.
- No typed number inside a formula except the structural constants in `om.modelcheck.ALLOWED_CONSTANTS` (0, 1, 0.5, 2, 4, 12, 52, 100, 360, 365, 1000, 1e6). Every rate, multiple, fee or tolerance is an input cell (preferably a defined name via `wb.define`).
- One formula per row across all projection columns (relative pattern identical; `om.modelcheck` "consistency" grader enforces it). Historical columns may differ from projection columns.
- No `{=TABLE()}` data tables, no array formulas, no merged cells in calculation areas, no volatile functions (`OFFSET`, `INDIRECT`, `NOW`, `TODAY`, `RAND`).
- Sensitivity tables are **live formula grids**: every grid cell is a closed-form formula that references the model's cells and the row/column header inputs. The headers are inputs (blue) or formulas off a base input plus a step input.
- Use only functions `om.formula` evaluates: ABS AND AVERAGE CHOOSE COLUMNS COUNT COUNTA COUNTIF EXP IF IFERROR INDEX INT IRR ISBLANK ISERROR ISNUMBER ISTEXT LEFT LEN LN MATCH MAX MEDIAN MIN MOD NOT NPV OR PERCENTILE(.INC) POWER QUARTILE(.INC) ROUND ROUNDDOWN ROUNDUP ROWS SIGN SQRT STDEV(.S) SUM SUMIF SUMPRODUCT TEXT. If you need another, stop and report it as a blocker in your Receipt (om/formula.py belongs to the S4.2 row).
- Circularity (interest on average balances, cash sweep): only behind a 1/0 switch input named `Circ` (`=IF(Circ=1, average-balance formula, opening-balance formula)`), with `Workbook(iterate=True)`. With `circ=0` the workbook must have **no** circular reference (LibreOffice comparison, D-006).
- A `Checks` sheet: every check cell evaluates to the text `"OK"` or `"ERROR"` (formula), column C onward; a master check `=IF(AND(COUNTIF(rng,"ERROR")=0, ...),"OK","ERROR")`; `sh.ok_error(rng)` for conditional colouring. Tolerances are named input cells.
- Sheet layout like `om/model3.py`: title in A2 (`kind="title"`), subtitle A3 (`kind="note"`), header row 5 (`kind="header"`), period-end row 6, labels in column A (width ~44), units in B, periods from column C, `freeze=(6, 2)`.
- After building, calculate with `om.formula.calculate_workbook(wb)` so the file carries cached values; `meta["converged"]` must be True.
- Return `build_workbook(...) -> (wb, meta)` and `build(...) -> (bytes, meta)`. `meta` holds at least: `"model"`, `"rows"` (sheet -> {key: row}), `"outputs"` (list of `{"id", "sheet", "ref", "units", "label"}` for the headline numbers a deck would cite), `"converged"`, `"iterations"`, `"warnings"`.
- Inputs come from `om.statements.Statements` (`om.statements.build(companyfacts, ticker)`), already provenance-tagged (`s.data[key][p].source()`, `s.filings[p]["url"]`). Tests use `tests/test_model3.py::synthetic_companyfacts` (import it) — never network.
- Market data (share price, as-of) is a caller-supplied dict `market={"price": float, "as_of": "YYYY-MM-DD", "source": str}` written as a blue input with its source as a cell comment (D-S4-01). Never invent a price.

## Acceptance every builder must meet (its unit tests assert these)

1. `om.modelcheck.grade(bytes)["production_ready"] is True` and every critical grader passes, score ≥ 95.
2. `om.validate_xlsx` (when it lands) passes; until then: zero formula cells containing literals outside the allowed set, and all cross-sheet formulas green.
3. With `circ=0`: `om.bench.agree(bytes)` (LibreOffice recalculation) reports 0 mismatches. Skip with a reason if `soffice` is missing.
4. Checks sheet master check reads `OK`.

## Workers

- Write **only** the files in your `AGENT_LOCK.md` row. Need another file? Return a blocker.
- Read targeted slices only (`grep -n`, then 50–120 line reads).
- Run your own tests with `python3 -m unittest tests.test_<name> -q`, then the full suite `python3 -m unittest discover -s tests -q` once at the end.
- At most 3 self-repair loops. Return only the Receipt (PLAN.md §5).
- Don't commit or push; the Boss merges.
