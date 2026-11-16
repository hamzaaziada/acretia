# IFRS as endorsed in the Kingdom of Saudi Arabia (SOCPA)

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: unverified.*

**Issuer:** SOCPA (Saudi Organization for Chartered and Professional Accountants)  
**Jurisdictions:** Saudi Arabia

## Summary
IFRS as endorsed by SOCPA for publicly accountable entities, with SOCPA's own requirements for matters IFRS does not cover, zakat being the example. Zakat (2.5 percent on the zakat base, charged on the Saudi and GCC owners' share) sits outside IAS 12, while income tax at 20 percent applies to the non-Saudi share. Zakat is therefore its own line and profit is commonly quoted before zakat and income tax. Statements are in SAR, often bilingual, mostly by function, with current/non-current ordering.

## Relationship to full IFRS
Full IFRS except the zakat and tax carve-out; IFRS for SMEs for small entities.

## Effective dates and caveats
- IFRS as endorsed by SOCPA: listed entities from 1 January 2017; other establishments for periods after 1 January 2018, early application possible from 2017 (Arab News, CMA)
- SOCPA amended its zakat accounting standard to align with IFRS, applying to fiscal years beginning on or after 1 January 2017 (EY tax alert)
- Cost model required for listed companies' PPE and investment property until fiscal years starting 2022; fair value or revaluation allowed after (IFRS profile)
- UNVERIFIED: whether and from when zakat moved from retained earnings to profit or loss

## Presentation
- **Profit or loss layout:** By function is typical; profit before zakat and income tax is a standard subtotal.
- **Balance sheet order:** Current/non-current split; zakat payable appears as a liability.
- **OCI:** As IFRS, including defined benefit remeasurements of end-of-service obligations.

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
- Interest paid: Usually financing or operating, per policy.
- Interest received: Operating or investing.
- Dividends paid: Financing.
- Dividends received: Operating or investing.

## Measurement bases
- As IFRS
- Zakat measured on the zakat base under ZATCA rules, not as temporary-difference tax
- End-of-service benefits as defined benefit plan under IAS 19 with actuarial valuation

## Key disclosures an analyst reads
- Zakat and income tax charge split between Saudi/GCC and foreign shareholders
- Zakat assessment status with ZATCA
- End-of-service benefit actuarial assumptions
- IFRS 16 lease disclosures, often large for retailers

## Difference entries involving this framework
- `diff-leases-ifrs16-asc842` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-leases-net-debt` (leases): recipe `lease_adjusted_net_debt`
- `diff-revenue-ifrs15-asc606-eas48` (revenue): recipe `revenue_principal_agent_net`
- `diff-inventory-lifo` (inventory): recipe `lifo_to_fifo`
- `diff-revaluation` (revaluation): recipe `revaluation_reverse`
- `diff-associates-jvs` (associates_jvs): recipe `associates_share_strip`
- `diff-fx-translation` (fx_translation): recipe `fx_translate_period_end_average`
- `diff-fx-devaluation-ias21` (fx_devaluation): recipe `devaluation_fx_loss_normalise`
- `diff-zakat-vs-income-tax` (zakat_tax): recipe `zakat_as_tax`
- `diff-eosb-ksa` (end_of_service): recipe `eosb_as_debt_like`
- `diff-government-grants` (government_grants): recipe `gov_grant_gross_up`
- `diff-socpa-ifrs-adoption` (framework_adoption): recipe `eas_to_ifrs_map`
- `diff-zakat-base-components` (zakat_tax): recipe `zakat_as_tax`
- `diff-eosb-ksa-actuarial-vs-nominal` (end_of_service): recipe `eosb_as_debt_like`

**Verified facts**
- Listed companies on IFRS from 1 January 2017; others for periods after 1 January 2018: <https://www.arabnews.com/corporate-and-sponsored-content/kpmg-to-make-private-sector-ready-for-upcoming-ifrs-1137586>
- Zakat outside IAS 12; Saudi/GCC portion zakat, non-Saudi portion IAS 12 income tax: <https://www.ifrs.org/content/dam/ifrs/meetings/2026/march/asaf/ap10-socpa-presentation-zakat.pdf>
- Revaluation and fair value models allowed from fiscal years starting 2022: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>

**Unverified facts**
- Profit or loss versus retained earnings treatment of zakat and its start date

## Sources
- IFRS jurisdiction profile: Saudi Arabia, Endorsement, zakat, revaluation timing: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>
- SOCPA presentation to IFRS ASAF, Zakat and IAS 12: <https://www.ifrs.org/content/dam/ifrs/meetings/2026/march/asaf/ap10-socpa-presentation-zakat.pdf>
- EY Tax Alert 2016-2063, Amended SOCPA zakat standard: <https://taxnews.ey.com/news/2016-2063>
