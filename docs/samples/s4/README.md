# S4 sample workbooks

Built from SEC companyfacts through `om.modelapi.build_model` (market prices: public-float proxy via `om.market.resolve`, cited in each workbook).
Rendered with LibreOffice headless (workbook print setup applies) and `pdftoppm -r 110`; at most 12 pages per model, Cover first.
Regenerate: `python3 scripts/render_samples_s4.py`.

## aapl_three_statement_dcf

- Tickers: AAPL (dcf)
- As-of filing: AAPL 10-K, FYE 2026-09-26, filed 2026-11-03, accession 0000320193-26-000026
- modelcheck score: 100.0 (production ready: True)
- validate pass: True (critical 0)
- Three engines agree: True (1218 cells compared)
- Build seconds: 5.7 (includes SEC fetch and all checks); workbook 61,343 bytes; 12 PDF pages
- Workbook: [aapl_three_statement_dcf.xlsx](aapl_three_statement_dcf.xlsx)

| PNG | First lines on the page |
|---|---|
| [aapl_three_statement_dcf/page-01.png](png/aapl_three_statement_dcf/page-01.png) | Strictly private & confidential / Apple Inc. (AAPL) / Integrated three-statement model and DCF, built from SEC filings |
| [aapl_three_statement_dcf/page-02.png](png/aapl_three_statement_dcf/page-02.png) | EBITDA to unlevered free cash flow, FY2027E DCF value per share (sensitivity range) / Strictly private & confidential / 200,000 |
| [aapl_three_statement_dcf/page-03.png](png/aapl_three_statement_dcf/page-03.png) | Strictly private & confidential / Assumptions and scenarios / Blue cells are inputs. Grey columns show the same ratio in the actuals for reference. |
| [aapl_three_statement_dcf/page-04.png](png/aapl_three_statement_dcf/page-04.png) | Strictly private & confidential / Apple Inc. — income statement / fiscal years 2022–2026 actual, 2027–2031 forecast |
| [aapl_three_statement_dcf/page-05.png](png/aapl_three_statement_dcf/page-05.png) | Strictly private & confidential / Apple Inc. — balance sheet / fiscal years 2022–2026 actual, 2027–2031 forecast |
| [aapl_three_statement_dcf/page-06.png](png/aapl_three_statement_dcf/page-06.png) | Strictly private & confidential / Apple Inc. — cash flow statement / fiscal years 2022–2026 actual, 2027–2031 forecast |
| [aapl_three_statement_dcf/page-07.png](png/aapl_three_statement_dcf/page-07.png) | Strictly private & confidential / Supporting schedules / PP&E roll-forward and working capital |
| [aapl_three_statement_dcf/page-08.png](png/aapl_three_statement_dcf/page-08.png) | Strictly private & confidential / Debt, revolver and interest / Revolver draws to keep minimum cash; interest on average balances when the circularity switch is |
| [aapl_three_statement_dcf/page-09.png](png/aapl_three_statement_dcf/page-09.png) | Strictly private & confidential / Apple Inc. — discounted cash flow / Unlevered free cash flow from the integrated model; mid-year convention switchable; both t |
| [aapl_three_statement_dcf/page-10.png](png/aapl_three_statement_dcf/page-10.png) | Strictly private & confidential / USD in millions FY2022A FY2023A FY2024A FY2025A FY2026A FY2027E FY2028E FY2029E FY2030E FY2031E / Implied exit EV / EBITDA 11. |
| [aapl_three_statement_dcf/page-11.png](png/aapl_three_statement_dcf/page-11.png) | Strictly private & confidential / Model checks / Every check must read OK; the master check feeds the cover |
| [aapl_three_statement_dcf/page-12.png](png/aapl_three_statement_dcf/page-12.png) | Strictly private & confidential / Apple Inc. — figures as filed with the SEC / Blue = as reported (XBRL), $m. Hover for the concept, period and accession; click |

## ko_three_statement_dcf

- Tickers: KO (dcf)
- As-of filing: KO 10-K, FYE 2025-12-31, filed 2026-02-20, accession 0001628280-26-010047
- modelcheck score: 100.0 (production ready: True)
- validate pass: True (critical 0)
- Three engines agree: True (1219 cells compared)
- Build seconds: 2.0 (includes SEC fetch and all checks); workbook 61,093 bytes; 12 PDF pages
- Workbook: [ko_three_statement_dcf.xlsx](ko_three_statement_dcf.xlsx)

| PNG | First lines on the page |
|---|---|
| [ko_three_statement_dcf/page-01.png](png/ko_three_statement_dcf/page-01.png) | Strictly private & confidential / COCA COLA CO (KO) / Integrated three-statement model and DCF, built from SEC filings |
| [ko_three_statement_dcf/page-02.png](png/ko_three_statement_dcf/page-02.png) | EBITDA to unlevered free cash flow, FY2026E DCF value per share (sensitivity range) / 16,000 / Strictly private & confidential |
| [ko_three_statement_dcf/page-03.png](png/ko_three_statement_dcf/page-03.png) | Strictly private & confidential / Assumptions and scenarios / Blue cells are inputs. Grey columns show the same ratio in the actuals for reference. |
| [ko_three_statement_dcf/page-04.png](png/ko_three_statement_dcf/page-04.png) | Strictly private & confidential / COCA COLA CO — income statement / fiscal years 2021–2025 actual, 2026–2030 forecast |
| [ko_three_statement_dcf/page-05.png](png/ko_three_statement_dcf/page-05.png) | Strictly private & confidential / COCA COLA CO — balance sheet / fiscal years 2021–2025 actual, 2026–2030 forecast |
| [ko_three_statement_dcf/page-06.png](png/ko_three_statement_dcf/page-06.png) | Strictly private & confidential / COCA COLA CO — cash flow statement / fiscal years 2021–2025 actual, 2026–2030 forecast |
| [ko_three_statement_dcf/page-07.png](png/ko_three_statement_dcf/page-07.png) | Strictly private & confidential / Supporting schedules / PP&E roll-forward and working capital |
| [ko_three_statement_dcf/page-08.png](png/ko_three_statement_dcf/page-08.png) | Strictly private & confidential / Debt, revolver and interest / Revolver draws to keep minimum cash; interest on average balances when the circularity switch is |
| [ko_three_statement_dcf/page-09.png](png/ko_three_statement_dcf/page-09.png) | Strictly private & confidential / COCA COLA CO — discounted cash flow / Unlevered free cash flow from the integrated model; mid-year convention switchable; both |
| [ko_three_statement_dcf/page-10.png](png/ko_three_statement_dcf/page-10.png) | Strictly private & confidential / USD in millions FY2021A FY2022A FY2023A FY2024A FY2025A FY2026E FY2027E FY2028E FY2029E FY2030E / Implied exit EV / EBITDA 10. |
| [ko_three_statement_dcf/page-11.png](png/ko_three_statement_dcf/page-11.png) | Strictly private & confidential / Model checks / Every check must read OK; the master check feeds the cover |
| [ko_three_statement_dcf/page-12.png](png/ko_three_statement_dcf/page-12.png) | Strictly private & confidential / COCA COLA CO — figures as filed with the SEC / Blue = as reported (XBRL), $m. Hover for the concept, period and accession; cli |

## hd_lbo

- Tickers: HD (lbo)
- As-of filing: HD 10-K, FYE 2026-02-01, filed 2026-03-18, accession 0001628280-26-019436
- modelcheck score: 100.0 (production ready: True)
- validate pass: True (critical 0)
- Three engines agree: True (672 cells compared)
- Build seconds: 2.2 (includes SEC fetch and all checks); workbook 52,794 bytes; 13 PDF pages
- Workbook: [hd_lbo.xlsx](hd_lbo.xlsx)

| PNG | First lines on the page |
|---|---|
| [hd_lbo/page-01.png](png/hd_lbo/page-01.png) | Strictly private & confidential / The Home Depot, Inc. (HD) — take-private LBO / Leveraged buyout model built from SEC filings; every number is written by code |
| [hd_lbo/page-02.png](png/hd_lbo/page-02.png) | Strictly private & confidential / Assumptions / Blue cells are inputs. Grey columns show the same ratio in the actuals for reference. |
| [hd_lbo/page-03.png](png/hd_lbo/page-03.png) | Strictly private & confidential / The Home Depot, Inc. — sources and uses at close / Sponsor equity is the plug: total uses less the debt raised |
| [hd_lbo/page-04.png](png/hd_lbo/page-04.png) | Strictly private & confidential / USD in millions Amount % of totalx LTM EBITDA / Net debt at close (new debt less minimum cash) $m 120,373 |
| [hd_lbo/page-05.png](png/hd_lbo/page-05.png) | Strictly private & confidential / The Home Depot, Inc. — operating build / fiscal years 2022–2026 actual, 2027–2031 projected |
| [hd_lbo/page-06.png](png/hd_lbo/page-06.png) | Strictly private & confidential / Debt schedule and credit statistics / Revolver draws to hold minimum cash and is repaid first; term loan B amortises and sweep |
| [hd_lbo/page-07.png](png/hd_lbo/page-07.png) | Strictly private & confidential / USD in millions Close (LTM) Year 1 Year 2 Year 3 Year 4 Year 5 / Fiscal year ending FY2026A FY2027E FY2028E FY2029E FY2030E FY |
| [hd_lbo/page-08.png](png/hd_lbo/page-08.png) | Strictly private & confidential / Sponsor returns / Exit value, money multiple and IRR (closed form with an IRR() cross-check), and where the gain comes from |
| [hd_lbo/page-09.png](png/hd_lbo/page-09.png) | Strictly private & confidential / The Home Depot, Inc. — returns sensitivity / Live closed-form grids: entry multiple moves purchase price and fees, debt stays  |
| [hd_lbo/page-10.png](png/hd_lbo/page-10.png) | Strictly private & confidential / USD in millions / 20.8x 0.2% 2.0% 3.6% 5.2% 6.7% |
| [hd_lbo/page-11.png](png/hd_lbo/page-11.png) | Strictly private & confidential / Model checks / Every check must read OK; the master check feeds the cover |
| [hd_lbo/page-12.png](png/hd_lbo/page-12.png) | Strictly private & confidential / The Home Depot, Inc. — figures as filed with the SEC / Blue = as reported (XBRL), $m. Hover for the concept, period and access |

## pg_ko_merger

- Tickers: PG, KO (merger)
- As-of filing: PG 10-K, FYE 2026-06-30, filed 2026-08-04, accession 0000080424-26-000103
- modelcheck score: 100.0 (production ready: True)
- validate pass: True (critical 0)
- Three engines agree: True (360 cells compared)
- Build seconds: 1.8 (includes SEC fetch and all checks); workbook 55,966 bytes; 15 PDF pages
- Workbook: [pg_ko_merger.xlsx](pg_ko_merger.xlsx)

| PNG | First lines on the page |
|---|---|
| [pg_ko_merger/page-01.png](png/pg_ko_merger/page-01.png) | Strictly private & confidential / PROCTER & GAMBLE Co (PG) acquires COCA COLA CO (KO) / Accretion / dilution merger model, built from SEC filings; every number  |
| [pg_ko_merger/page-02.png](png/pg_ko_merger/page-02.png) | Strictly private & confidential / Assumptions / Blue cells are inputs. Per-year inputs sit under the forecast years; everything else is in column C. |
| [pg_ko_merger/page-03.png](png/pg_ko_merger/page-03.png) | Strictly private & confidential / $ in millions FY2026A FY2027E FY2028E FY2029E / Fiscal year (acquirer) |
| [pg_ko_merger/page-04.png](png/pg_ko_merger/page-04.png) | Strictly private & confidential / Purchase price / Offer price, equity purchase price, net debt assumed and the multiples paid. |
| [pg_ko_merger/page-05.png](png/pg_ko_merger/page-05.png) | Strictly private & confidential / Sources & Uses / How the equity purchase price and fees are funded; shares issued to target holders. |
| [pg_ko_merger/page-06.png](png/pg_ko_merger/page-06.png) | Strictly private & confidential / Purchase price allocation / Target book equity, intangible write-ups, deferred tax and goodwill. Existing goodwill is eliminat |
| [pg_ko_merger/page-07.png](png/pg_ko_merger/page-07.png) | Strictly private & confidential / Pro forma earnings and accretion / dilution / Standalone projections, deal adjustments and the pro forma EPS bridge. Reported  |
| [pg_ko_merger/page-08.png](png/pg_ko_merger/page-08.png) | Strictly private & confidential / $ in millions FY2026A FY2027E FY2028E FY2029E / Fiscal year (acquirer) |
| [pg_ko_merger/page-09.png](png/pg_ko_merger/page-09.png) | Strictly private & confidential / Breakeven analysis / Pre-tax synergies that make each year EPS-neutral, and the highest year-1 premium that is EPS-neutral (cl |
| [pg_ko_merger/page-10.png](png/pg_ko_merger/page-10.png) | Strictly private & confidential / Sensitivity: year-1 accretion / (dilution) / Live closed-form grids on the model's drivers and the row / column headers. The c |
| [pg_ko_merger/page-11.png](png/pg_ko_merger/page-11.png) | Strictly private & confidential / Year-1 accretion / (dilution) %: run-rate synergies (down) x offer premium (across) / Run-rate synergies down; offer premium a |
| [pg_ko_merger/page-12.png](png/pg_ko_merger/page-12.png) | Strictly private & confidential / Model checks / Every check must read OK; the master check feeds the cover. |

## ko_comps

- Tickers: KO, PEP, PG, MDLZ, CL (comps)
- As-of filing: KO 10-K, FYE 2025-12-31, filed 2026-02-20, accession 0001628280-26-010047
- modelcheck score: 100.0 (production ready: True)
- validate pass: True (critical 0)
- Three engines agree: True (564 cells compared)
- Build seconds: 3.7 (includes SEC fetch and all checks); workbook 47,127 bytes; 9 PDF pages
- Workbook: [ko_comps.xlsx](ko_comps.xlsx)

| PNG | First lines on the page |
|---|---|
| [ko_comps/page-01.png](png/ko_comps/page-01.png) | Strictly private & confidential / COCA COLA CO (KO) — trading comparables / Peer multiples, calendarised and treasury-stock-method diluted, built from SEC filin |
| [ko_comps/page-02.png](png/ko_comps/page-02.png) | Strictly private & confidential / COCA COLA CO — trading comparables: inputs / Blue = typed. Companyfacts are as filed with the SEC; hover for the concept, peri |
| [ko_comps/page-03.png](png/ko_comps/page-03.png) | Strictly private & confidential / Millions except per share Unit KO PEP PG MDLZ CL / Company COCA COLA CO PEPSICO INC R & GAMBLE Co nternational, Inc. LIVE COMP |
| [ko_comps/page-04.png](png/ko_comps/page-04.png) | Strictly private & confidential / Calendarisation to a common year end / CY = w_latest x FY_latest + w_prior x FY_prior; w_prior = MOD(FYE month - CY month, 12) |
| [ko_comps/page-05.png](png/ko_comps/page-05.png) | Strictly private & confidential / Equity value and enterprise value / Diluted shares by the treasury stock method: in-the-money options add options - options x  |
| [ko_comps/page-06.png](png/ko_comps/page-06.png) | Strictly private & confidential / COCA COLA CO — trading comparables / Multiples are formulas on Equity value and Calendarisation. NM = denominator <= 0 or mult |
| [ko_comps/page-07.png](png/ko_comps/page-07.png) | Strictly private & confidential / COCA COLA CO — implied valuation from peer multiples / Peer 25th-75th percentile multiple x the target's metric. EV methods go |
| [ko_comps/page-08.png](png/ko_comps/page-08.png) | Strictly private & confidential / Checks / Every cell reads OK or ERROR. Tolerance Tol is a named input on Inputs. |
| [ko_comps/page-09.png](png/ko_comps/page-09.png) | Strictly private & confidential / Source filings / Every typed historical number on Inputs comes from one of these filings (hover over the cell for concept and  |
