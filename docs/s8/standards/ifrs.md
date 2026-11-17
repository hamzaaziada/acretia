# IFRS Accounting Standards (full IFRS)

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: verified.*

**Issuer:** IASB (IFRS Foundation)  
**Jurisdictions:** International, EU (as endorsed), most of the world

## Summary
The global baseline. Companies choose the layout of the profit and loss statement (by function or by nature) and order the balance sheet by liquidity or by current/non-current split. IFRS 18 replaces IAS 1 presentation rules from annual periods beginning 1 January 2027 and adds operating, investing and financing categories with mandatory subtotals.

## Relationship to full IFRS
This is the reference framework; every other entry in the base is described by its gap to it.

## Effective dates and caveats
- IFRS 15: periods from 1 Jan 2018
- IFRS 9: periods from 1 Jan 2018
- IFRS 16: periods from 1 Jan 2019
- IFRS 18: periods from 1 Jan 2027 (replaces IAS 1 presentation; comparatives restated)

## Presentation
- **Profit or loss layout:** Choice between expenses by function (cost of sales) and by nature (materials, staff costs, depreciation); by-nature reporters usually show no gross profit and no operating profit line before IFRS 18.
- **Balance sheet order:** Current/non-current split is the default; a liquidity ordering is allowed when more relevant (typical for banks and some real estate firms).
- **OCI:** Items that may later move to profit or loss (cash flow hedges, foreign operation translation, debt instruments at fair value through OCI) are shown apart from items that will not (revaluation surplus, equity instruments at fair value through OCI, defined benefit remeasurements).

### Required line items
**IS**

- Revenue
- Finance costs
- Share of profit or loss of associates and joint ventures
- Tax expense
- Post-tax result of discontinued operations
- Profit or loss for the period
- Profit attributable to owners and to non-controlling interests

**BS**

- Property, plant and equipment
- Investment property
- Intangible assets
- Goodwill
- Investments accounted for using the equity method
- Other financial assets
- Inventories
- Trade and other receivables
- Cash and cash equivalents
- Assets held for sale
- Trade and other payables
- Provisions
- Financial liabilities (borrowings, lease liabilities)
- Current tax assets and liabilities
- Deferred tax assets and liabilities
- Non-controlling interests (within equity)
- Issued capital and reserves attributable to owners

**CF**

- Cash flows from operating activities
- Cash flows from investing activities
- Cash flows from financing activities
- Net change in cash and cash equivalents
- Effect of exchange rate changes on cash
- Cash and cash equivalents at start and end of period

### Cash flow choices
- Method: Direct or indirect for operating activities; indirect is dominant in practice.
- Interest paid: Operating or financing, chosen and applied consistently.
- Interest received: Operating or investing.
- Dividends paid: Operating or financing.
- Dividends received: Operating or investing.

## Measurement bases
- Historical cost (inventory at lower of cost and net realisable value, most PPE)
- Revaluation model allowed for PPE and intangibles with an active market
- Fair value for investment property (optional), derivatives and many financial assets
- Amortised cost with expected credit loss for loans and receivables
- Defined benefit obligations at actuarial present value

## Key disclosures an analyst reads
- Segment information on the chief operating decision maker view (IFRS 8, listed entities)
- Related party transactions and key management pay (IAS 24)
- Lease maturity analysis, right-of-use movement and lease cash outflow (IFRS 16)
- Revenue disaggregation, contract balances and remaining performance obligations (IFRS 15)
- Expected credit loss movement and credit risk concentration (IFRS 7 and IFRS 9)
- Tax rate reconciliation and unrecognised deferred tax (IAS 12)
- Impairment test assumptions for goodwill (IAS 36)
- Basic and diluted earnings per share (IAS 33)

## Difference entries involving this framework
- `diff-leases-ifrs16-asc842` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-leases-net-debt` (leases): recipe `lease_adjusted_net_debt`
- `diff-leases-eas49` (leases): recipe `capitalise_operating_leases`
- `diff-revenue-ifrs15-asc606-eas48` (revenue): recipe `revenue_principal_agent_net`
- `diff-revenue-principal-agent` (revenue): recipe `revenue_principal_agent_net`
- `diff-inventory-lifo` (inventory): recipe `lifo_to_fifo`
- `diff-development-costs` (development_costs): recipe `dev_cost_expense`
- `diff-revaluation` (revaluation): recipe `revaluation_reverse`
- `diff-impairment-reversal` (impairment_reversal): recipe `impairment_reversal_strip`
- `diff-borrowing-costs` (borrowing_costs): recipe `capitalised_interest_expense`
- `diff-associates-jvs` (associates_jvs): recipe `associates_share_strip`
- `diff-hyperinflation-ias29` (hyperinflation): recipe `ias29_restate`
- `diff-fx-translation` (fx_translation): recipe `fx_translate_period_end_average`
- `diff-fx-devaluation-ias21` (fx_devaluation): recipe `devaluation_fx_loss_normalise`
- `diff-zakat-vs-income-tax` (zakat_tax): recipe `zakat_as_tax`
- `diff-eosb-gcc-egypt` (end_of_service): recipe `eosb_as_debt_like`
- `diff-eosb-ksa` (end_of_service): recipe `eosb_as_debt_like`
- `diff-government-grants` (government_grants): recipe `gov_grant_gross_up`
- `diff-presentation-by-nature-function` (presentation): recipe `by_nature_ebit`
- `diff-cash-flow-classification` (presentation): recipe `ifrs16_to_pre16_ebitda`
- `diff-eas-ifrs-new-standards` (eas_ifrs_mapping): recipe `eas_to_ifrs_map`
- `diff-eas-ifrs-legacy-map` (eas_ifrs_mapping): recipe `eas_to_ifrs_map`
- `diff-uae-corporate-tax` (zakat_tax): recipe `zakat_as_tax`
- `diff-uae-dmtt-pillar-two` (zakat_tax): recipe `zakat_as_tax`
- `diff-egypt-income-tax` (zakat_tax): recipe `zakat_as_tax`
- `diff-ind-as-carveouts` (presentation): recipe `by_nature_ebit`
- `diff-frs102-vs-ifrs` (presentation): recipe `capitalise_operating_leases`
- `diff-ecl-ifrs9-eas47-cecl` (credit_losses): recipe `eas_to_ifrs_map`
- `diff-leases-indas116` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-indas-applicability` (presentation): recipe `eas_to_ifrs_map`
- `diff-eas17-separate-fs` (associates_jvs): recipe `associates_share_strip`
- `diff-socpa-ifrs-adoption` (framework_adoption): recipe `eas_to_ifrs_map`
- `diff-uae-ifrs-requirement` (framework_adoption): recipe `eas_to_ifrs_map`
- `diff-business-combinations` (business_combinations): recipe `associates_share_strip`
- `diff-provisions-ias37-asc450` (provisions): recipe `eosb_as_debt_like`
- `diff-eosb-ksa-actuarial-vs-nominal` (end_of_service): recipe `eosb_as_debt_like`
- `diff-eas-fx-relief-comparatives` (fx_devaluation): recipe `devaluation_fx_loss_normalise`
- `diff-eas49-ebitda-effect` (leases): recipe `ifrs16_to_pre16_ebitda`

## Sources
- IAS 1, paras 54, 82 (minimum line items): <https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/>
- IAS 7, paras 31-34 (interest and dividends): <https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/>
- IFRS 18, Presentation categories and mandatory subtotals: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/>
