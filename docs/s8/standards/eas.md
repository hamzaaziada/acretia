# Egyptian Accounting Standards

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: unverified.*

**Issuer:** Ministry of Investment and the Financial Regulatory Authority (FRA) process; standards issued by ministerial or prime ministerial decree  
**Jurisdictions:** Egypt

## Summary
A national set modelled on IFRS with a time lag. The 2015 reissue brought most standards close to older IAS text; newer standards for financial instruments (EAS 47), revenue (EAS 48) and leases (EAS 49) track IFRS 9, 15 and 16. Listed Egyptian groups report under EAS in local currency (EGP), usually by function with a current/non-current balance sheet. Special accounting treatments for foreign exchange (EAS 13 annexes) have been issued after the major devaluations and can defer or capitalise FX differences.

## Relationship to full IFRS
Not full IFRS. Lag in standards, some choices removed or added, and temporary special treatments that have no IFRS counterpart (FX relief annexes).

## Effective dates and caveats
- EAS issued July 2015, amended 2019 and 2023 (IFRS Foundation profile)
- EAS 47 financial instruments, EAS 48 revenue, EAS 49 lease contracts: issued 2019 (FRA decisions list). UNVERIFIED: effective dates and postponements
- EAS 13 special FX treatment: appendices tied to the 2016 and 2022 devaluations (FRA Decision 843/2022, amended 1378/2022; PM Decisions 1568/2022 and 4706/2022). EAS 13, 17 and 34 were substituted by PM Decree 636/2024

## Presentation
- **Profit or loss layout:** Mostly by function (revenue, cost of sales, gross profit, administrative and selling expenses); by nature occurs.
- **Balance sheet order:** Current/non-current split. Statements are often bilingual (Arabic and English) with Arabic as legal text.
- **OCI:** Presented as a separate statement of comprehensive income; fewer items than IFRS in practice (translation, hedges, some revaluation).

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
- Method: Indirect is the norm; direct allowed.
- Interest paid: Operating or financing, disclosed.
- Interest received: Operating or investing.
- Dividends paid: Financing.
- Dividends received: Operating or investing.

## Measurement bases
- Historical cost; the revaluation model for PPE, intangibles and investment property was not permitted until January 2023 and is allowed since
- Amortised cost with ECL under EAS 47 for entities that adopted it; older incurred-loss rules before
- Foreign currency monetary items at closing rate with EAS 13 special treatment where elected

## Key disclosures an analyst reads
- Foreign currency exposure and any special FX treatment elected
- Related parties and board remuneration
- Segment note for listed entities
- Lease commitments and right-of-use movement after EAS 49

## Difference entries involving this framework
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
- `diff-fx-eas13-special-treatment` (fx_devaluation): recipe `devaluation_fx_loss_normalise`
- `diff-eosb-gcc-egypt` (end_of_service): recipe `eosb_as_debt_like`
- `diff-government-grants` (government_grants): recipe `gov_grant_gross_up`
- `diff-presentation-by-nature-function` (presentation): recipe `by_nature_ebit`
- `diff-cash-flow-classification` (presentation): recipe `ifrs16_to_pre16_ebitda`
- `diff-eas-ifrs-new-standards` (eas_ifrs_mapping): recipe `eas_to_ifrs_map`
- `diff-eas-ifrs-legacy-map` (eas_ifrs_mapping): recipe `eas_to_ifrs_map`
- `diff-egypt-income-tax` (zakat_tax): recipe `zakat_as_tax`
- `diff-ecl-ifrs9-eas47-cecl` (credit_losses): recipe `eas_to_ifrs_map`
- `diff-eas17-separate-fs` (associates_jvs): recipe `associates_share_strip`

**Verified facts**
- EAS issued 2015, amended 2019 and 2023; EAS not full IFRS; revaluation barred until January 2023: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
- EAS 47, 48, 49 issued in 2019; EAS 13 appendix decisions 843/1378/1568/4706 of 2022: <https://fra.gov.eg/en/?p=13760728>
- PM Decree 636/2024 substituted EAS 13, 17 and 34: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>

**Unverified facts**
- Effective dates of EAS 47/48/49
- Scope of each EAS 13 appendix

## Sources
- Egyptian Accounting Standards, FRA decisions list (2019, 2022, 2023, 2024): <https://fra.gov.eg/en/?p=13760728>
- IFRS jurisdiction profile: Egypt, EAS versus IFRS differences: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
- PM Decree 636 of 2024, Article 1: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>
