# Teardown: libraz/formulon (Excel formula engine, second engine for S4.2)

repo: https://github.com/libraz/formulon
commit: 636e32f1158f973b549b7cc6a309959716a444e5
licence: Apache-2.0 (`LICENSE`; `NOTICE` says "Copyright 2026 libraz" and that test fixtures derive from IronCalc, which is MIT/Apache-2.0 dual licensed, so the NOTICE must travel with any redistribution)
ran: yes (pip `formulon` 0.18.0 in a venv; recalculated our real `AAPL three-statement model.xlsx` and compared every formula cell against `om.formula` and LibreOffice headless; the repo clone is at 0.18.0 per `packages/python/pyproject.toml`)

## Read this first: two projects are called formulon

- [OBSERVATION] The npm package named `formulon` (repo `leifg/formulon`, commit 3f1151abd5b71bf832289d76fd630535ed58cade, MIT) is a parser for Salesforce formulas, not Excel. Run with `npm i formulon@6.25.6`: `SUM(1,2,3)`, `NPV(0.1,1,2,3)`, `AVERAGE`, `CHOOSE`, `IFERROR`, `COUNTIF`, `SUMPRODUCT` and `POWER` all return `Unknown function ... NoFunctionError`, `A1+B1` returns an `ArgumentError` (no cell references), and `1/0` returns `null` instead of `#DIV/0!`. Only operators, `IF`, `AND`, `MAX`, `MIN`, `ABS`, `ROUND` work. `README.md` line 12 says "Parser for Salesforce Formulas".
- [OBSERVATION] Even on the subset it can express, it is fragile for Excel text: of 922 formulas in our AAPL model that use only operators/IF/MAX/MIN/ABS/AND/OR/ROUND and same-book references (references replaced by LibreOffice values), it agreed with LibreOffice on 905 and disagreed on 0; the other 17 were parser errors after I rewrote unary `-(` as `(-1)*(` (10 remaining syntax errors, 7 `^` argument-type errors; before the rewrite 189 of 922 failed because `-(a)` is a syntax error). Only 922 of 1,155 cells were even expressible.
- [INFERENCE] The ledger row (`libraz/formulon`, 636e32f..., Apache-2.0) names the correct project. Use `libraz/formulon` (PyPI `formulon`, npm `@libraz/formulon`); never `npm i formulon`.

## What libraz/formulon is

- [OBSERVATION] README: a C++17 Excel recalculation engine shipped as WebAssembly (`@libraz/formulon`), a Python package and native CLI binaries (darwin-arm64, linux-x64, linux-arm64); "526 Excel function names, 511 implemented locally"; reads and writes `.xlsx` and `.xlsb`; 28 locale profiles; results compared against goldens captured from Mac Excel 365; known differences are listed in `tests/divergence.yaml` (52 entries counted by `grep -c "^- \|^  - id"`; header documents `skip-oracle` and tolerance modes).
- [OBSERVATION] The installed wheel is 5.0 MB (`du -sh .../site-packages/formulon`), no compiler needed, `pip install formulon` took seconds. `formulon.eval_formula("=SUM(1,2,3)").to_python()` returned `6.0`; `=NPV(0.1,1,2,3)` returned `4.815927873779113`; `=CHOOSE(2,10,20,30)` returned `20.0`; `=IFERROR(1/0,0)` returned `0.0`; `=SUMPRODUCT({1,2},{3,4})` returned `11.0`; `=1/0` returned an error-kind `Value` (error_code 1).
- [OBSERVATION] API used: `formulon.Workbook.load(bytes)`, `.sheet_count()`, `.sheet_name(i)`, `.recalc()`, `.get_value(sheet, row, col)` (0-based) returning a `Value` with `.to_python()`, `.set_number(sheet,row,col,v)`, `.set_iterative(enabled,max_iter,max_change)`, `.save()` (`site-packages/formulon/workbook.py:4554,4698,4972,5082,5093,5137`).

## Test: three engines on our real model

Input: `data/out/AAPL three-statement model.xlsx` written by `om` (10 sheets, 1,155 formula cells: IF 124, SUM 89, ABS 60, NPV 50, MAX 20, AVERAGE 15, CHOOSE 11, AND 6, COUNTIF 2, SUMPRODUCT 1, ISERROR 1; iterative calc on, named cells `Scenario`, `Circ`, `Tol*`).

- [OBSERVATION] Baseline: `om.formula` recalculation equals the cached values in the file for all 1,155 cells (0 diffs, 0.07 s). LibreOffice headless via `om.consistency.recalc` took 1.33 s. `om.formula` vs LibreOffice: 11 cells differ, all of the form `=G16` pointing at an empty cell: `om.formula` returns `None`, LibreOffice returns `0.0` (`BS!H16:L16`, `Debt!H18`, `Debt!C20:D20`). Excel also shows 0 for a reference to a blank cell, so this is a small `om.formula` divergence worth fixing in S4.2.
- [OBSERVATION] formulon on the unmodified file: `Workbook.load` 1.22 s (includes WASM start-up), `recalc()` 0.006 s; 1,155 of 1,155 formula cells agree with LibreOffice values (blank-versus-zero treated as equal), 0 errors.
- [OBSERVATION] Because a baseline agreement can just echo cached values, I perturbed the inputs. With the circularity switch off (`Assumptions!C10 = 0`) and three assumption cells changed (`Assumptions!H14=0.12`, `I15=0.15`, `L14=0.02`), 389 formula cells moved and `om.formula`, formulon and LibreOffice agreed on all 1,155 cells (0 diffs each). The LibreOffice leg required writing the edited file with openpyxl and recalculating via `om.consistency.recalc`.
- [OBSERVATION] With the circularity switch on (the model's default) and the same edits, `om.formula` and formulon still agree with each other (0 diffs above a 1e-3 relative tolerance; largest difference seen about 3e-8 absolute on `IS!H25`: 138344.8666756224 vs 138344.8666755921), but both differ from LibreOffice on 155 cells. LibreOffice returns `0.0` or small negatives for `IS!H25:L25` (net income) and `Checks!C23`/`Cover!C11` become `ERROR`. The same 155 diffs appear with no edits at all after an openpyxl round trip (file saved without cached values), so the cause is LibreOffice's cold-start iteration, not the perturbation.
- [INFERENCE] The baseline "LibreOffice 1,155 of 1,155" on the file as written is probably LibreOffice keeping cached values rather than iterating: the circular model fails to converge in LibreOffice as soon as cached values are absent. That makes a persistent LibreOffice daemon a weak check for circular models unless it is given warm values or the circ switch, while `om.formula` and formulon converge to the same fixed point.
- [OBSERVATION] Trap in the harness: openpyxl round-tripping drops cached values and rewrites `calcPr`; I set `iterate=True`, 100 iterations, 0.001 delta before recalculating, and the 155 diffs persisted, so the iterate flag alone does not fix it.

## Fit with S4.2

- [INFERENCE] formulon is a credible independent second engine for `validate_xlsx.py`: it is pip-installable, 5 MB, loads our real file, honours `iterate`, and matched `om.formula` to better than 1e-3 relative on every cell (about 3e-8 absolute at worst). It covers every function our current model uses.
- [INFERENCE] The three-engine rule in the S4 gate ("three-engine agreement") should run with the circular switch both on and off, and treat LibreOffice disagreement on circular cells as a known engine limit, not a model error, unless `om.formula` and formulon also disagree.
- [UNKNOWN] Behaviour on `{=TABLE}` data tables, `XIRR`/`XNPV`, `OFFSET`/`INDIRECT`, and LBO-style circular sweeps (not in the AAPL model). `tests/divergence.yaml` lists known gaps but I did not map them to our planned `om/lbo.py` and `om/merger.py` function set.
- [UNKNOWN] The ja-JP-centred oracle (header of `tests/divergence.yaml` says "Mac Excel 365 (ja-JP)"): how far results for en-US are verified; the default profile for new workbooks is `win-365-en_US` per the README but fidelity against real Excel was not testable here.

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt (isolated, optional second recalculation engine), pinned to a released wheel and with `NOTICE` kept. It is Apache-2.0, small and installable with pip, and it agreed with `om.formula` on every cell in both the baseline and perturbed runs. Keep `om.formula` as the primary engine and LibreOffice as the Excel-compatible third check, but do not rely on LibreOffice alone for circular models. Avoid the unrelated Salesforce `formulon` npm package.
