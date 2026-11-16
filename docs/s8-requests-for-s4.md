# S8 requests for session C (S4 owns `om/model3.py` and `om/comps.py`)

S8.6a supplies the helpers; S4 adapts the builders. Nothing here was edited by S8. Line numbers are from `main` on 2026-11-16 and will drift, so
re-grep before editing. Helpers: `om.intl.adjust.RECIPES`, `om.intl.fx.IntlFX/translate`, `om.intl.calendar.calendarise/weights`.
Statements arrive as `IntlStatements` (an `om.statements.Statements`), with extra keys under `x.` and a `basis_flags` dict.

## model3.py

1. **Currency label is not always "$".** Hard-coded `$` in the user-visible labels:
   - L256 `"... $ and shares in millions."`; L252 `"Blue = as reported (XBRL), $m. ..."`; L319 `"New term debt issued ($m)"`; L535 `"Rounding tolerance ($m)"`.
   - Request: derive `cur = s.currency` once and format these as f"{cur}m" (the cover at L698 and L69 already use `s.currency`).
   - Number formats named `usd2` (EPS on the cover, L706 area) should become a currency-neutral two-decimal format when `s.currency != "USD"`.
2. **By-nature EBIT basis shown on the cover.** L229-231 lists `ebit` as required; an IFRS by-nature P&L has no reported operating income, so
   `IntlStatements` will carry `ebit` computed by `adjust.by_nature_ebit` with `basis_flags["ebit"] == "computed_by_nature"`.
   - Request: add a cover row after L698 (`sh.set("B..", "EBIT basis", ...)`) reading `getattr(s, "basis_flags", {}).get("ebit", "reported")`.
   - The `other_op` plug at L338-339 (EBIT minus gross profit, R&D and SG&A) will then absorb by-nature costs; label it "Other operating items (by-nature costs)" when the flag is set.
3. **Zakat in the tax line and the effective rate.** L302 builds the historical tax-rate ratio from `IS.tax` / `IS.pretax`, and L161 averages the same ratio in `defaults()`.
   - Request: when `x.zakat` is present, add an IS line "Zakat" directly below "Income tax" (L350) and compute the effective rate in L302 and L161 as `(tax + zakat) / pretax`
     (see `adjust.zakat_as_tax`), with the label "Tax and zakat rate". Keep zakat out of the forecast tax-rate input unless the user keeps it on (flag `zakat_in_tax_rate`).
   - The NCI plug at L351 (`net_income - pretax - tax`) must also subtract zakat or it will absorb it.
   - The check at L485 (`c_is`) has to include the zakat line.
4. **Lease liabilities in net debt behind a toggle.** Net debt is built from `BS.debt + BS.rev_bal` at L478-479 (leverage), L641 (DCF "(−) Debt incl. revolver") and L628 (its label).
   - Request: add a named input `IncludeLeases` (0/1) on Assumptions next to `CalMonth`-style inputs (L277 in comps shows the pattern), and add
     `x.lease_liabilities_current + x.lease_liabilities_noncurrent` to the debt term in L478, L479 and L641 when it is 1 (default 0 to keep US results unchanged).
   - The EBITDA used with it must be pre- or post-IFRS 16 consistently: with leases in net debt use reported (post-IFRS 16) EBITDA; with the toggle off use `adjust.ifrs16_to_pre16_ebitda`.
     Add the pre-IFRS 16 EBITDA as an extra row after L361 (`ebitda`) and use it in the valuation (L634 `ebitda_last`, L649) when `IncludeLeases = 0`.
5. **Devaluation flags in checks.** `Checks` (CK, L251, rows L484-501) are formula checks only.
   - Request: when `s.fx_flags` (from `om.intl.fx.translate`) or `s.warnings` contain a `devaluation` flag, add an informational row "Devaluation in the period (see FX)"
     showing the flagged FY and the % move as text (not part of the master check), and list the flags on the cover under L698.
   - Note: for EGP, forecasts should not extrapolate the historical growth of a devalued year; use `adjust.devaluation_fx_loss_normalise` for the nonop assumption at L204 (`"nonop"`).
6. **Display currency.** If the user wants USD, call `om.intl.fx.translate(statements, "USD", IntlFX())` before `build` (BS at period end, flows at the fiscal-year average).
   The cover should say "translated from EGP at period-end/average rates (IMF IFS)" using `s.fx_flags`/`basis_flags["fx_translation"]`.
7. **Fiscal year labels.** `FY{year}` at L699-700 assumes a calendar-year-like label; for June year ends label "FY2024 (Jun)" using `s.years[i].month`.

## comps.py

1. **Currency mismatch only warns.** L86-87 warns `"reports in {ccy}; the price is assumed to be in the same currency (no FX applied)"`.
   - Request: when `co.ccy != "USD"` and a market price currency is supplied, convert with `IntlFX.rate(ccy, price_date)` (market values at the price-date rate, `om.fx` rule) or refuse with a clear error. Never silently mix currencies in peer statistics.
2. **Calendarisation hook.** The calendarisation sheet (L336-349, weights `MOD(FYE month - CY month, 12) / 12`, named input `CalMonth` at L277) already implements the same weights as `om.intl.calendar.weights(fy_end_month, target_month)`.
   - Request: no new maths; add a test that the sheet's weights equal `calendarise()` for June (6/12, 6/12) and March (3/12, 9/12), and let `_collect` (L84) accept an `IntlStatements` for non-SEC peers, passing `fye_month` from `ExtractedStatements.fiscal_year_end_month`.
   - Stocks (net debt, equity) must not be weighted: use the nearest period end (`calendarise(..., kind="stock")`).
3. **Unit labels.** L288 `"Share price", "$"`, L303 `"$"`, L312 `"$m"`, L327 and L359 `unit = "$" if key == "eps" else "$m"`: use the peer's currency (or the target's, after conversion) instead of `$`.
4. **Peer flags.** Carry `basis_flags` (computed by-nature EBIT, zakat, lease basis, devaluation) into the peer table as a flags column, so a computed-EBIT or pre-IFRS 16 multiple is never presented as comparable to a reported one without a label.
