# IB VP specialist review, round 1 (2026-11-17)

Reviewer: Sonnet "IB VP" subagent (D-033 grader 2), xlsx skill, on `docs/samples/s4/` (commit 60ccc9f). **Overall 6.2/10: FAIL** (≥ 8.5 to pass).

Per workbook: AAPL 3-stmt+DCF 7.0 · KO 3-stmt+DCF 5.5 · HD LBO 5.5 · PG+KO merger 5.5 · KO comps 5.0.
Per criterion: formula integrity 8.5 · linking/colour 8.5 · statement integrity 8.0 · **valuation sanity 4.0** · sourcing 6.0 · navigability 8.5 · **print setup 6.0** · visual polish 7.0 · **client-readiness 4.5**.

## Blocking issues
1. **Accession mismatch (AAPL, KO, HD Filings!C9:G49, Filings source row, Cover sources).** A cell's comment, its hyperlink and the "Source filing" row cite different accessions: 86/182 AAPL cells, 65/183 KO, 65/190 HD. E.g. AAPL Filings!C9: the comment says 0000320193-24-000123, the link opens 25-000079, and row 52 says 25-000079. The VP expects one accession per cell, identical in note, link and source row, and pointing to a filing that actually contains that period.
2. **KO DCF.**
   - Levered beta is the 1.10 placeholder (KO is around 0.55). WACC is 9.6%, so value is $24.80 / $28.03 against roughly $70 market.
   - Net debt ignores equity-method investments.
   - IS!H21:L21 forecasts other non-operating income (equity income) at 0, so NI drops from 13,107 to 9,419.
   - CF!H21 cuts the dividend 21% because a payout ratio is applied to the depressed NI.
   - Expected: company-specific beta, equity investments in the bridge, forecast equity income, and a flag when value is >30% from market.
3. **AAPL DCF.**
   - Cost of debt 3.40% is below rf 4.25%.
   - Cash yield 6.0% produces 10bn of FY31 interest income.
   - Current share price is 0, so there is no upside and no market marker on the football field.
   - Expected: price input + marker, cash yield ≤ rf, cost of debt > rf.
4. **AAPL IS!E19:G20 / Filings!E15:G16.** Interest expense/income are blank FY24–26 (tag not found) while "other non-operating" absorbs them. BS intangibles are populated only FY25/26. Expected: populated history or an explicit "not tagged" flag.
5. **HD LBO.**
   - 77% sponsor equity, 4.2% IRR, 1.23x MoM, and nothing flags it. IRR is below the cost of every tranche.
   - No hurdle or feasibility flag.
   - No §163(j) interest-deductibility cap.
6. **Share prices.** Public-float proxies dated 2025-06..12 sit against balance sheets to 2026-10. The merger uses PG at 2025-12-31 vs KO at 2025-06-27. The comps cover says "Prices as of 2025-06-27" but the dates vary. Expected: one dated price per name, a common date or explicit date per name, and a visible PROXY flag on cover headline numbers.
7. **Comps stale facts.** PEP RSUs come from the FY2011 10-K and CL RSUs from FY2018, silently carried as latest.
8. **Comps method.**
   - No forward (NTM/CY+1) multiples.
   - "CY" for December filers = FY actuals.
   - NM caps of 100x are far too loose (MDLZ P/E 36x drives a $106.71 high).
   - EV/Revenue sits in the blended range ($23–38 for KO) and drags it down.
   - EV excludes long-term/equity investments.
9. **Merger.**
   - −56% dilution with no commentary.
   - No pro forma balance sheet, leverage or interest cover, no financing fees, no refinancing of target debt.
   - KO NI (13,593 FY27E, 27.3% margin incl. equity income) conflicts with the KO DCF workbook (9,419).
   - Breakeven max premium −36.2% has no "n/a".
10. **Print.**
    - AAPL/KO cover: waterfall and football-field charts split across the page break; "Charts" heading clipped.
    - Footer-left text overlaps the centre footer (HD, PG, comps).
    - HD p10: orphan sensitivity block, mid-table page break.
    - AAPL p9/10: DCF cross-checks split across pages. AAPL p12: "Source filing" row truncated.
    - Comps p6: clipped headers ("uity value ($m)", "/ Revenue LTM"). Comps p7: header overlap, subtitle off-page.
    - HD p3: header collision "% of totalx LTM EBITDA".
    - No manual page breaks anywhere.

## Non-blocking
- Forecast inputs are 15-digit blue numbers (e.g. 0.07835767476487716) with no rationale comment. Round them to display precision and add a comment on the derivation.
- Gordon TV is discounted at N while flows are mid-year; the standard is N−0.5.
- DCF!H13 label "(−) Increase in working capital" shows a positive 5,322. The label or sign is wrong.
- Comps Valuation!B32:C32 has hard-coded `*(1-0.5/100)` in formulas.
- WACC target D/(D+E) 10%; ERP/rf are placeholders in both DCFs.
- HD "FY2026A" is fiscal year ended 2026-02-01 (HD calls it fiscal 2025).
- Contents links use the input blue (colour clash).
- The Cover "Chart data" block prints on its own page.
- AAPL/KO football field has no market marker, axis title or data labels. The waterfall shows a zero "Other" bar.
- AAPL cover growth line is one point short.

## Edits-needed list (analyst minutes; feeds time-saved)
Around 12–14 analyst hours across the five files. The largest items:
- accession reconciliation: 210 min;
- merger pro forma credit sheet: 120 min;
- comps NTM: 90 min;
- print fixes: 90 min;
- KO equity income/dividend: 45 min;
- NM caps/adjustments: 45 min;
- 163(j): 40 min.
