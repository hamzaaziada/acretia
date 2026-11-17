# Teardown: anthropics/financial-services (Excel recipes)

repo: https://github.com/anthropics/financial-services
commit: 3e32c2287dcb637c184c01cc0ad82d6af7e9bb0f
licence: Apache-2.0 (top-level `LICENSE` is the unmodified Apache-2.0 text; nested `LICENSE`/`LICENSE.txt` in `skill-creator` and `partner-built/spglobal/**` are also Apache-2.0 text)
ran: partial (the repo is prompt/skill text plus one validator script; ran `validate_dcf.py` on our real AAPL workbook, read the comps, DCF, LBO, 3-statement, merger, audit and xlsx-author skills; nothing here builds a workbook, so there is no builder to run)

Scope read: `plugins/vertical-plugins/financial-analysis/skills/{comps-analysis,dcf-model,lbo-model,3-statement-model,audit-xls,xlsx-author}/SKILL.md` and `plugins/vertical-plugins/investment-banking/skills/merger-model/SKILL.md`. Test input: `data/out/AAPL three-statement model.xlsx` (written by `python3 open_multiples.py model AAPL`; 10 sheets, 1,155 formula cells), copied to the scratchpad before use.

## What it is

- [OBSERVATION] The repo is Claude plugin/skill content, not a library. `find . -name "*.xlsx"` returns nothing and `find . -name recalc.py` returns nothing; the only workbook-touching code is `dcf-model/scripts/validate_dcf.py` (also copied under `agent-plugins/*`). The skills tell the model to write openpyxl or Office JS itself. (`dcf-model/SKILL.md:800-843` says to run `recalc.py` "from the xlsx skill", but that file is not in this repo.)
- [OBSERVATION] `lbo-model/SKILL.md:8-19` says to copy `examples/LBO_Model.xlsx` as the template and "never build from scratch". That file does not exist in the repo at this commit, so the LBO skill can only be followed as prose.
- [INFERENCE] Because the skills say "ask the user for a template first" (`lbo-model/SKILL.md:12-14`) and "user preferences and uploaded templates always override" (`comps-analysis/SKILL.md:119-124`), the recipes are guidance for an interactive Office session, not a deterministic generator. They suit Acretia only as a checklist; Acretia's builders (D-005, code writes models) must encode the rules themselves.

## Structure conventions worth matching (each cited)

- [OBSERVATION] Colours: blue = hardcoded input, black = formula, green = cross-sheet link (`dcf-model/SKILL.md:852-856`, `xlsx-author/SKILL.md` "Conventions"). Fills: only blues and greys, `#1F4E79` section header, `#D9E1F2` sub-header, `#BDD7EE` output rows (`dcf-model/SKILL.md:856-866`).
- [OBSERVATION] Formulas over hardcodes: every projection, discount factor and sensitivity cell must be a live formula, "never a value computed in Python and written as a number" (`dcf-model/SKILL.md:44-48`). This is already Acretia's D-005 rule.
- [OBSERVATION] Sensitivity tables: odd dimensions (5x5 or 7x7), centre cell equals the base case, centre highlighted `#BDD7EE`, every cell a full-recalculation formula, no Excel Data Table feature (`dcf-model/SKILL.md:59-66`, `525-545`; `lbo-model/SKILL.md:152-160`). This matches S4.1's "no `{=TABLE}`; every grid cell a formula".
- [OBSERVATION] Source comments on every hardcode: format `Source: [System/Document], [Date], [Reference], [URL]`, added as each input is created (`dcf-model/SKILL.md:67-70,905-907`, `comps-analysis/SKILL.md:355-373`). Our AAPL workbook has 344 blue numeric constants but cell comments only on the `Filings` sheet (182 comments, 187 hyperlinks); the model sheets have none (read with `om.xlsx.read`, `Book.comments`).
- [OBSERVATION] Comps layout: header block rows 1-3, operating stats block, valuation block, a statistics block of Max / 75th / Median / 25th / Min using `QUARTILE`, stats only on comparable ratios and not on size metrics, a "5-10 rule" for metric count, and an explicit data-source priority (MCP/institutional first, never web search) (`comps-analysis/SKILL.md:24-36,108-119,199-224,337`).
- [OBSERVATION] 3-statement: an explicit sign-convention table (D&A positive, capex negative, debt repayments negative; `3-statement-model/SKILL.md:316-326`), a master check that aggregates section checks to one "ALL CHECKS PASS" cell (`:395-400`), and an interest-circularity breaker toggle (`:328-332`).
- [OBSERVATION] LBO: break circularity by computing interest on the beginning balance (`lbo-model/SKILL.md:136-139`), cash sweeps respect tranche priority and balances cannot go negative (`:141-145`), IRR/MOIC sign rules (`:146-150`).
- [OBSERVATION] Merger model: Sources & Uses table and accretion/dilution inputs (acquirer EPS, consideration mix, new debt, synergies phase-in, fees) (`merger-model/SKILL.md:44`, Step 1 inputs list).
- [OBSERVATION] `audit-xls/SKILL.md` Step 2 has a nine-row formula-check table (errors, hardcodes inside formulas, inconsistent neighbours, off-by-one ranges, pasted-over formulas, circular refs, broken links, unit/scale mismatches, hidden rows) and Step 3 model-integrity checks (BS balances, RE roll-forward). These are the rules `om.modelcheck` plus S4.1 should cover.
- [OBSERVATION] Checkpointed workflow: show the user inputs, then revenue, then FCF, then WACC, then equity bridge, before the next section (`dcf-model/SKILL.md:50-57`, `lbo-model/SKILL.md:44`). Not applicable to an autonomous builder.

## Test on our real workbook

- [OBSERVATION] `python3 dcf-model/scripts/validate_dcf.py "AAPL three-statement model.xlsx"` (run in a venv with openpyxl) returned `status: PASS`, 0 errors, 4 warnings: missing sheets named `WACC` and `Sensitivity`, "Could not locate terminal growth and WACC values", and "Could not validate WACC range: 'Workbook' object has no attribute 'get'". Info lines: "Total formulas: 1155", "No formula errors found", "Terminal value is 72.7% of EV".
- [OBSERVATION] The `'Workbook' object has no attribute 'get'` warning is a bug inside the validator (it treats an openpyxl Workbook like a dict); two of the four warnings are layout assumptions (separate `WACC`/`Sensitivity` tabs) that contradict the same repo's own text, which puts sensitivities at the bottom of the DCF sheet (`dcf-model/SKILL.md:798`).
- [OBSERVATION] Our workbook colour census (via `om.xlsx.read`): 344 blue numeric constants, 383 black formulas, 772 green formulas; the colour convention is applied, with green used for formulas that reference other sheets.
- [INFERENCE] The validator is too shallow to adopt: it checks sheet names, error literals and a terminal-value share. `om.modelcheck` plus S4.1 already does more; borrow the check list, not the script.

## Fit with Acretia S4.3

- [INFERENCE] Worth matching: odd-sized sensitivity grids with a highlighted centre cell, `QUARTILE` statistics rows on comps, the sign-convention table, a master check cell, beginning-balance interest as a circularity option, and comments on every blue input (extend beyond the `Filings` sheet).
- [INFERENCE] Not worth matching: Times New Roman 11/12 pt (a "suggested default" at `comps-analysis/SKILL.md:119-135`), the Office JS merged-cell workarounds, and the checkpoint prompts.
- [UNKNOWN] Whether the `examples/LBO_Model.xlsx` and `recalc.py` it references are distributed elsewhere under a licence that would let us use them; they are absent at this commit.
- [UNKNOWN] The licence of anything in the sibling `anthropics/skills` repo the xlsx skill comes from; PLAN section 0 already treats that repo as ideas-only.

## Adopt / borrow ideas / isolated service / skip for Acretia

Borrow ideas. Do not vendor: the content is prose with no runnable builder, and the one script is weaker than `om.modelcheck`. The Apache-2.0 licence would permit copying, but the value is in the checklists, which we reimplement in `om/comps.py`, `om/lbo.py`, `om/merger.py` and `validate_xlsx.py`, keeping a note of the commit in the ledger.
