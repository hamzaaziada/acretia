# IFRS in the UAE and wider GCC (UAE, Qatar, Kuwait, Bahrain, Oman)

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: unverified.*

**Issuer:** Local securities regulators and commercial company laws; IASB standards used unmodified  
**Jurisdictions:** UAE, Qatar, Kuwait, Bahrain, Oman

## Summary
Listed and most regulated entities in the UAE apply full IFRS as issued by the IASB with no local carve-outs. Federal corporate tax (9 percent above a threshold) began for financial years starting on or after 1 June 2023, so earlier years show no income tax for most UAE entities and later years need deferred tax. Gratuity under the labour law is a defined benefit item.

## Relationship to full IFRS
Full IFRS, unmodified. GCC states differ on local tax and labour law, not on the standards.

## Effective dates and caveats
- UAE federal corporate tax: financial years starting on or after 1 June 2023 (UNVERIFIED: confirm decree text)

## Presentation
- **Profit or loss layout:** By function typical; real estate developers often show revenue and direct costs.
- **Balance sheet order:** Current/non-current; some developers present a liquidity ordering.
- **OCI:** As IFRS.

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
- Method: Indirect.
- Interest paid: Operating or financing, per policy.
- Interest received: Operating or investing.
- Dividends paid: Financing.
- Dividends received: Operating or investing.

## Measurement bases
- As IFRS; investment property commonly at fair value
- Revaluation model used by some for property

## Key disclosures an analyst reads
- Corporate tax status and deferred tax opening balances
- Employee end-of-service provisions
- Contract liabilities and escrow balances for developers
- Related party balances with government-linked shareholders

## Difference entries involving this framework
- `diff-leases-ifrs16-asc842` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-leases-net-debt` (leases): recipe `lease_adjusted_net_debt`
- `diff-revenue-ifrs15-asc606-eas48` (revenue): recipe `revenue_principal_agent_net`
- `diff-inventory-lifo` (inventory): recipe `lifo_to_fifo`
- `diff-revaluation` (revaluation): recipe `revaluation_reverse`
- `diff-associates-jvs` (associates_jvs): recipe `associates_share_strip`
- `diff-fx-translation` (fx_translation): recipe `fx_translate_period_end_average`
- `diff-fx-devaluation-ias21` (fx_devaluation): recipe `devaluation_fx_loss_normalise`
- `diff-eosb-gcc-egypt` (end_of_service): recipe `eosb_as_debt_like`
- `diff-government-grants` (government_grants): recipe `gov_grant_gross_up`
- `diff-uae-corporate-tax` (zakat_tax): recipe `zakat_as_tax`

## Sources
- IFRS adoption by jurisdiction, UAE profile: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/>
