# Indian Accounting Standards (Ind AS)

*Generated from `om/intl/standards/frameworks.yaml`. Authored by Acretia in its own words. Confidence: verified.*

**Issuer:** Ministry of Corporate Affairs on advice of the National Financial Reporting Authority; ICAI drafts  
**Jurisdictions:** India

## Summary
Converged with IFRS but not identical. Notified under the Companies (Indian Accounting Standards) Rules 2015 and mandatory in phases: from 1 April 2016 for listed companies and unlisted companies with net worth of INR 500 crore or more, and from 1 April 2017 for all other listed companies and unlisted companies with net worth of INR 250 crore up to 500 crore (SME-exchange companies and those below INR 250 crore stay on the older standards). Differences are called carve-outs: investment property uses cost only, business combinations under common control use pooling of interests, and a few presentation and measurement options differ. Reporting is in INR, with a fiscal year ending 31 March.

## Relationship to full IFRS
Substantially converged with carve-outs (investment property, common-control combinations, some financial instrument and employee benefit details).

## Effective dates and caveats
- Phased adoption: net worth of INR 500 crore or more from fiscal 2016-17; INR 250 crore and all listed companies from fiscal 2017-18
- Ind AS 116 leases: annual periods beginning on or after 1 April 2019

## Presentation
- **Profit or loss layout:** Schedule III of the Companies Act prescribes a by-nature statement of profit and loss.
- **Balance sheet order:** Schedule III prescribed current/non-current format.
- **OCI:** Separate OCI section in the same statement as profit or loss.

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
- Method: Indirect usual; direct allowed.
- Interest paid: Financing for non-finance entities.
- Interest received: Investing.
- Dividends paid: Financing.
- Dividends received: Investing.

## Measurement bases
- Cost for investment property (fair value model not permitted)
- Pooling at carrying amounts for common-control business combinations
- Fair value or amortised cost for financial instruments as IFRS 9

## Key disclosures an analyst reads
- Schedule III line items and note layout
- Operating segments for listed companies
- Related parties and CSR spending

## Difference entries involving this framework
- `diff-leases-ifrs16-asc842` (leases): recipe `ifrs16_to_pre16_ebitda`
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
- `diff-ind-as-carveouts` (presentation): recipe `by_nature_ebit`
- `diff-leases-indas116` (leases): recipe `ifrs16_to_pre16_ebitda`
- `diff-indas-applicability` (presentation): recipe `eas_to_ifrs_map`

## Sources
- Ind AS, Ind AS 1, 40, 103 (Appendix C), 116: <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>
- Companies (Indian Accounting Standards) Rules 2015, Rule 4 applicability phases: <https://taxguru.in/company-law/applicability-indian-accounting-standard-ind.html>
- Ind AS 116, Differences from IFRS 16: <https://alumni.in.kpmg.com/downloads/Publications/Accounting_Publications/firstnotes-leases-standard-ind-as-116-notified-mca.pdf>
