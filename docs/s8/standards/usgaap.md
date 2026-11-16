# US generally accepted accounting principles (FASB ASC)

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: verified.*

**Issuer:** FASB, with SEC rules for registrants  
**Jurisdictions:** United States

## Summary
Rules-based, codified. Expenses may be by function (usual) with income from operations; the balance sheet follows a liquidity-loose current/non-current split. Operating leases remain a single straight-line cost in operating expenses under ASC 842, LIFO is allowed, development costs are generally expensed, and revaluation up is not allowed. Many analyst adjustments exist to make US companies comparable to IFRS peers.

## Relationship to full IFRS
Different framework with partial convergence on revenue (ASC 606 vs IFRS 15) and financial instrument credit losses (CECL differs from IFRS 9).

## Effective dates and caveats
- ASC 842 leases: public entities fiscal years after 15 Dec 2018
- ASC 606 revenue: public entities fiscal years after 15 Dec 2017

## Presentation
- **Profit or loss layout:** By function with income from operations (SEC rules require cost-by-nature breakdown only for some captions).
- **Balance sheet order:** Current/non-current (classified) by convention; not mandated for all entities.
- **OCI:** Separate statement or combined; accumulated OCI shown in equity.

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
- Method: Indirect usual; direct allowed with a reconciliation.
- Interest paid: Operating (not a choice).
- Interest received: Operating.
- Dividends paid: Financing.
- Dividends received: Operating.

## Measurement bases
- Historical cost; no upward revaluation of PPE or intangibles
- LIFO, FIFO or average cost for inventory
- Fair value option for some financial instruments
- Current expected credit loss model (CECL) for financial assets at amortised cost

## Key disclosures an analyst reads
- LIFO reserve
- Operating lease cost, weighted average discount rate and remaining term (ASC 842)
- Non-GAAP reconciliations required for SEC filers
- Segment expense disclosure

## Difference entries involving this framework
- `diff-leases-ifrs16-asc842` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-leases-net-debt` (leases): recipe `lease_adjusted_net_debt`
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
- `diff-government-grants` (government_grants): recipe `gov_grant_gross_up`
- `diff-presentation-by-nature-function` (presentation): recipe `by_nature_ebit`
- `diff-cash-flow-classification` (presentation): recipe `ifrs16_to_pre16_ebitda`
- `diff-ecl-ifrs9-eas47-cecl` (credit_losses): recipe `eas_to_ifrs_map`
- `diff-business-combinations` (business_combinations): recipe `associates_share_strip`
- `diff-provisions-ias37-asc450` (provisions): recipe `eosb_as_debt_like`

## Sources
- FASB ASC, Topics 205, 220, 230, 330, 606, 842: <https://asc.fasb.org/>
