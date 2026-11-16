# S4 gate spec (`scripts/verify_s4.py`)

Written by the Boss (D-027). The gate script is written by a Sonnet worker who has not seen the implementers' tests. It reads workbooks with **openpyxl** (independent reader) wherever a fact can be checked that way, and with `zipfile` + ElementTree for raw OOXML. It never calls an LLM. Exit 0 only if every assertion passes; print one line per assertion (`PASS`/`FAIL`/`SKIP <reason>`), then a summary, and write `data/out/s4/gate.json` (not committed).

Flags: `--offline` (synthetic fixtures only, for CI), default (synthetic + SEC). SEC data is fetched through `om.sec`/the existing cache under `data/raw/` with `SEC_USER_AGENT="Acretia hamza@meshpool.ai"`; if SEC is unreachable, the SEC assertions report `SKIP` and the gate exits non-zero unless `--offline`.

## Universe

- **OM-Bench 10:** AAPL, MSFT, NVDA, GOOGL, AMZN, META, KO, PG, HD, CAT (non-financial; substitute with the next of JNJ, PEP, CSCO, ORCL if one is unsupported, and print the substitution).
- **LBO:** 3 targets from the 10 (e.g. KO, HD, CAT). Market from `om.market.resolve`.
- **Merger:** 2 pairs, acquirer first: PG + KO, HD + CAT. The gate tests mechanics, not deal sense.
- **Comps:** target KO with peers PEP, PG, MDLZ, CL (fallback to any 4 of the 10).
- Offline mode: the synthetic company from `tests/test_model3.py::synthetic_companyfacts` and scaled variants.

## Assertions

### A. Tie-out and grading (all workbooks above)
1. `om.modelcheck.grade` → `production_ready` and every critical grader passes; score ≥ 95. **10/10** three-statement models.
2. Balance sheet balances in every period (recomputed by the gate from openpyxl cached values: Total assets vs Total liabilities & equity rows found by label, tolerance 0.5).
3. Cash ties: CF ending cash = BS cash every period (recomputed by the gate).
4. Checks sheet: every check cell's cached value is `"OK"`; the master check is `"OK"`.

### B. Validator (`om.validate_xlsx.validate`)
5. `passed` on every workbook; `stats["hardcoded_calc_cells"] == 0` summed over all workbooks.
6. Gate's own independent scan (openpyxl, `data_only=False`): no formula contains `TABLE(`; no array/dataTable formulas (raw XML `t="array"`/`t="dataTable"`); no merged range intersects a formula cell; no `OFFSET|INDIRECT|NOW\(|TODAY\(|RAND`; every cross-sheet formula cell has a green font.
7. Adversarial: for each of these mutations applied to a clean synthetic model3 workbook (via raw XML or `om.xlsx`), `validate` must fail with the expected finding id: hard-coded number replacing a projection formula (`hardcode.calc` or `modelcheck.consistency`); `{=TABLE(...)}`/`t="dataTable"` in a sensitivity cell (`sensitivity.table`); a sensitivity grid cell turned into a typed number (`sensitivity.live`); a cross-sheet link recoloured black (`links.green`); a sheet header switched to "in billions" while linked from a millions sheet (`units`); a circular reference without the breaker (`circularity`); a merged range over formulas (`noise.merged`).

### C. Three engines (`om.recalc.compare`)
8. On every workbook built with circularity off: `agree` is True; LibreOffice available (else FAIL unless `--offline`, where SKIP with reason); formulon status reported (available or the reason it is not); `compared_cells` > 0; 0 divergences.
9. Adversarial: corrupt one cached value in a copy → `compare` reports exactly that cell.
10. Circular build (circ=1): cycle cells are listed under `excluded` and om.formula converges (`meta["converged"]`).

### D. New models' mechanics (gate recomputes from openpyxl cached values, independent of the builders)
11. LBO: IRR = MoM^(1/years) − 1 within 1e-6 and equals the `IRR()` cross-check row; sources = uses; PIK balance(t) = PIK balance(t−1) × (1 + PIK rate) when no PIK repayment; TLB never negative and the sweep never exceeds excess cash; returns attribution components sum to the equity gain within 0.01; sensitivity grid centre cell equals the base IRR.
12. Merger: pro forma EPS(y1) = (acq NI + tgt NI + after-tax synergies − after-tax new interest − after-tax forgone interest − after-tax amortisation) ÷ (acq shares + new shares), within 0.005; accretion % consistent; goodwill = price − (book equity + write-ups − DTL) ≥ 0; plugging breakeven synergies gives |accretion| < 0.01%; sensitivity centre = base accretion.
13. Comps: TSM diluted shares recomputed (ITM options × (1 − strike/price) + RSUs + basic); EV = equity value + debt + preferred + NCI − cash; any peer with denominator ≤ 0 shows "NM" and is excluded from quartiles; quartiles equal `statistics.quantiles(method="inclusive")` of the non-NM peers.

### E. Planted-error audit (`om.bench.audit` extended)
14. Existing 10 three-statement plants caught and located: **10/10**.
15. New plants, each caught by `modelcheck` or `validate_xlsx` and located to the planted cell: LBO sweep formula hard-coded, PIK accrual broken (cash-pay instead of accrue), exit EV typed over; merger new-share count typed over, goodwill plug, synergies not tax-effected; comps TSM using basic shares, EV bridge dropping cash, NM rule removed. Required: caught = planted (≥ 9 new), located ≥ 90%.

### F. Working on existing workbooks
16. `om.wbgraph.graph` validates as a `WorkbookGraph`; revenue → EBITDA → FCF dependency path exists on a model3 workbook.
17. `om.wbgraph.ask`: 5 fixed questions answered with the correct cells; 1 unanswerable question returns no number.
18. `om.wbedit.edit`: change one Assumptions input on a model3 workbook and on an openpyxl-authored workbook with shared strings → every untouched zip part byte-identical (decompressed), the edited sheet differs only inside the target `<c>` elements and changed `<v>` values, and dependents' cached values equal a full `om.formula` recalculation of the edited file.
19. `om.rollforward.roll_forward`: for 2 SEC companies, old = statements built `as_of` one fiscal year earlier, new = current; the new year is an actual (blue, with a source comment and filing link), a user-edited assumption survives, the variance sheet exists, and the result passes A1–A4 and B5.

### G. Manifest and delivery
20. `om.delivery.deliver` writes xlsx + manifest + report for every clean workbook; the manifest validates against `om.contracts.ModelManifest`, its sha256 matches the delivered file, every output cell exists in openpyxl with a numeric cached value, and every historical-derived output has ≥ 1 citation with a URL.
21. Adversarial: a workbook with a planted `#DIV/0!` and one with a failing check each raise `DeliveryBlocked` and leave no files behind.

### H. Polish (S4.7), checked with openpyxl + raw XML on every delivered workbook
22. A `Cover`/dashboard sheet first in the tab order with ≥ 3 native charts (`xl/charts/chart*.xml`), every series **value** reference (`c:val`) resolving to formula cells in this workbook (not typed chart data); category references may be text labels or formulas; three-statement models carry revenue/EBITDA trend + an EBITDA/FCF bridge (waterfall) + a valuation football field; LBO carries a returns-attribution bridge; comps a football field.
23. Named styles present (`Input`, `Calculation`, `Link`, `Header`, `Total` at least) and used by cells.
24. Every sheet: gridlines off, frozen panes on calculation sheets, print setup (fit to 1 page wide, landscape, print titles for the header rows/label columns, footer with source and `Page &P of &N`).
25. Historical and projection columns grouped with outline levels on the statement sheets.
26. No merged cells in calculation areas; every number cell has a number format (no "General" on numbers); fonts limited to the house font.

### I. Bench and SpreadsheetBench (S4.6)
27. OM-Bench report written (`data/out/s4/bench.md`) with the 10 companies, scores, three-engine status, audit table.
28. SpreadsheetBench verified-400 (CC BY-SA 4.0; data fetched to `data/raw/spreadsheetbench/` at pinned commit 49b73a94, never committed): engine-fidelity eval — for every golden answer workbook, recompute formula cells with `om.formula` and compare with the values Excel saved; report the share of workbooks and of formula cells reproduced, plus the top missing functions. Gate threshold: ≥ 95% of formula cells reproduced on workbooks whose functions are all supported, and the coverage numbers recorded in `scorecard.csv` rows `S4.6`. The LLM-solving harness runs in replay mode only (D-021) and is recorded as "not run live".

### J. Suite
29. `python3 -m unittest discover -s tests -q` is green (the gate runs it as a subprocess and parses the result).
