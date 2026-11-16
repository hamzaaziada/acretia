# Methodology

Every published number traces to a filing. `data/out/provenance*.jsonl` records the XBRL concept, filing accession number, form, filing date and period for every field.

## Sources

| Input | Source | Licence |
|---|---|---|
| Financial statements | SEC EDGAR XBRL `companyfacts` (us-gaap, ifrs-full, dei) | US government data |
| Company metadata, SIC | SEC `submissions` | US government data |
| FX | ECB euro reference rates (through Frankfurter, or directly from ECB) | Free reuse; cite "Source: ECB statistics" |
| Prices | Your licensed EOD feed (CSV) or Twelve Data business tier | Per your licence |

No data from multiples.vc or any other comps vendor is used.

## Periods

- Periods are chosen by their real start and end dates, never by the `fy`/`fp` labels.
- **FY** is a duration of 350–380 days. The fiscal year label is the calendar year in which it ends.
- **LTM** at quarter end E is FY_last + YTD(E) − YTD(E − 1 year).
  - All three periods come from one XBRL tag where possible. Tags are only mixed when no single tag covers all three periods, and the basis then says `mixed_tags`.
  - If no YTD fact is tagged, contiguous 3-month quarters are summed (basis `quarter_sum`).
  - If there is no usable interim data, LTM = FY (basis `fy_only`). This is common for 20-F filers.
- **Restatements:** `latest` uses the most recently filed value, which is the default. `first` uses the value as first reported.
- **Point in time (`--as-of`):** only facts filed on or before that date are used.

## Concepts

The chains in [`om/concepts.py`](om/concepts.py) are tried in order. The first tag with a value wins, and the tag used is recorded.

- **EBITDA:** reported EBIT plus D&A from the cash-flow statement. D&A falls back to depreciation + amortization. It is unadjusted. IFRS-16 filers' EBITDA is structurally higher.
- **FCF:** operating cash flow minus purchases of PP&E.
- **Gross profit:** the reported tag, else revenue minus cost of revenue.
- **Opex ratio:** the reported tag, else gross profit minus EBIT.

## EV bridge

All bridge items come from one balance-sheet date, the latest one filed.

- **Total debt:** long-term debt (including current portion; else noncurrent + current) + short-term borrowings + commercial paper + finance leases.
- **Cash:** cash and equivalents + short-term investments.
- **Preferred and hybrid:** preferred stock + temporary equity.
- **Minority interest.**
- **Operating leases** are excluded from EV. They are shown separately, and `ev_incl_leases` adds them back.

**EV = market cap + debt + preferred + minority interest − cash.**

Banks, insurers and brokers (SIC 6000–6399, 6700–6799) are treated as financial format: **EV = market cap**, and EBITDA, EBIT and FCF multiples are not computed.

## Shares and market cap

- Shares come from the dei cover page (`EntityCommonStockSharesOutstanding`). The fallback is the balance-sheet count, then diluted weighted-average shares. The basis is recorded in `shares_basis`.
- `check_shares` flags a cover-page count that falls outside 0.5–2× the balance-sheet or diluted count.
- **Market cap** = price ÷ `ordinary_per_unit` × shares.
- Foreign filers with an unverified ADR ratio are flagged `adr_ratio_unverified`.

## Multiples and derived fields

- Multiples are computed in reporting currency, so they are FX-neutral.
- **Non-meaningful rule:** a multiple is null, and listed in `nm_fields`, when its denominator is ≤ 0, or the result is negative or above 250×.
- **Growth** = (current / prior − 1) × 100, and is null when the prior value is ≤ 0.
- **Growth-adjusted multiple** = multiple ÷ growth (in percentage points), and is null when growth is ≤ 0.
- **Rule of 40 (historical)** = LTM revenue growth YoY + LTM EBITDA margin. **Rule of X (historical)** = 2.5 × growth + margin. Forward versions need the estimates layer.

## FX

- Flows are converted at the average daily rate over the 12 months to period end.
- Market values are converted at the rate on the price date.
- Pegs are fixed: SAR 3.75, AED 3.6725, QAR 3.64, BHD 0.376 and OMR 0.3845 per USD.
- Ratios are always computed before conversion.

## Not built yet

- Forward fields (NTM, FY+1, calendar years 2026–2029). These need the estimates layer: guidance, broker street estimates and model estimates, each labelled.
- Monthly history snapshots.
- M&A from merger proxies.
- Form D rounds.
- Taxonomy.
- EU/UK and MENA filings.
