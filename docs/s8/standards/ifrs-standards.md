# IFRS standards the analyst reads

*Generated from `om/intl/standards/ifrs_standards.yaml`. Own words, no copied standard text.*

## IAS 1: Presentation of financial statements
Sets the complete set of statements (financial position, profit or loss and OCI, changes in equity, cash flows, notes), going-concern and accrual basis, current versus non-current classification, and the minimum face line items. Expenses may be analysed by nature or by function; function reporters must also disclose depreciation and staff costs by nature. Until IFRS 18 applies (annual periods from 1 January 2027) no operating profit subtotal is defined, so each company builds its own and the figure is not comparable.

**Disclosures:** Accounting policies; judgements and estimation uncertainty; capital management; depreciation and employee cost by nature when by function

**Analyst impact:** Computed operating profit must be rebuilt consistently; check which items sit above and below the subtotal the company shows.

**Recipe:** `by_nature_ebit`

- IAS 1, paras 54-55 (balance sheet), 82 (profit or loss), 99-105 (expense analysis): <https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/>

## IFRS 18: Presentation and disclosure in financial statements
Replaces IAS 1 presentation rules for annual periods beginning on or after 1 January 2027. It splits the income statement into operating, investing and financing categories, forces subtotals for operating profit and profit before financing and income taxes, and requires disclosure of management-defined performance measures with a reconciliation. Comparatives are restated, so the first IFRS 18 year gives a clean operating profit definition for IFRS reporters. Items such as foreign exchange differences are classified by the line they relate to.

**Disclosures:** Management-defined performance measures with reconciliation; expenses by nature note for function reporters

**Analyst impact:** Expect restated operating profit and EBIT definitions from 2027; keep both bases during the transition.

**Recipe:** `by_nature_ebit`

- IFRS 18, Categories, subtotals and MPM disclosure: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/>

## IFRS 15: Revenue from contracts with customers
A five-step model: identify the contract, identify distinct promises, set the transaction price, allocate it by relative stand-alone price, and recognise revenue as each promise is satisfied (over time or at a point in time). Principal versus agent decides gross versus net revenue. Contract assets and liabilities appear on the balance sheet; costs to obtain contracts may be capitalised.

**Disclosures:** Disaggregation of revenue; contract balances; remaining performance obligations; significant judgements on timing and variable consideration

**Analyst impact:** Check principal-agent judgement, percentage-of-completion revenue and contract liabilities for developers; backlog comes from the remaining performance obligation note.

**Recipe:** `revenue_principal_agent_net`

- IFRS 15, paras 9, 31-38, B34-B38, 110-129: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/>

## IFRS 16: Leases
Lessees record a right-of-use asset and a lease liability for almost all leases, then charge depreciation and interest instead of rent. EBITDA rises and operating cash flow rises while financing outflows include principal. Short-term and low-value leases may stay off balance sheet as expense. Lessors keep finance versus operating classification.

**Disclosures:** Right-of-use asset movement; maturity analysis of lease liabilities; total cash outflow; expense for short-term and variable leases

**Analyst impact:** Compare EBITDA with pre-16 or US GAAP peers; include lease liabilities in net debt only when EBITDA is also on the post-16 basis.

**Recipe:** `ifrs16_to_pre16_ebitda`

- IFRS 16, paras 22-38 (lessee), 47-60 (presentation and disclosure): <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

## IFRS 9: Financial instruments
Classification follows the business model and cash flow test into amortised cost, fair value through OCI or fair value through profit or loss. Impairment uses expected credit losses in three stages, so provisions are booked earlier than under the old incurred-loss model. Hedge accounting aligns with risk management.

**Disclosures:** Loss allowance reconciliation by stage; credit risk exposure; fair value hierarchy; hedge effects

**Analyst impact:** Bad-debt charges may be lumpier and earlier; for Egypt the equivalent is EAS 47 once adopted.

**Recipe:** `eas_to_ifrs_map`

- IFRS 9, paras 4.1.1-4.1.5, 5.5.1-5.5.20: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/>

## IFRS 3: Business combinations
Acquisitions use the acquisition method: identifiable assets and liabilities at fair value, goodwill as the residual, acquisition costs expensed, contingent consideration at fair value with later changes in profit or loss. Non-controlling interest may be measured at fair value (full goodwill) or at its share of net assets.

**Disclosures:** Consideration; fair value of acquired assets; goodwill drivers; pro forma revenue and profit

**Analyst impact:** Acquired intangibles amortisation is non-cash and often excluded from adjusted earnings; check goodwill share of equity.

- IFRS 3, paras 4-5, 18-19, 32, 53: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-3-business-combinations/>

## IFRS 10: Consolidated financial statements
Control, not ownership percentage, decides consolidation: power over relevant activities, exposure to variable returns and the link between them. Subsidiaries are consolidated line by line with non-controlling interests shown within equity. Investment entities are an exception.

**Disclosures:** Significant judgements on control; non-controlling interests with material share; restrictions on group assets

**Analyst impact:** Use profit attributable to owners for per-share work; remember EBITDA covers 100 percent of consolidated subsidiaries.

- IFRS 10, paras 5-18, B2-B85: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-10-consolidated-financial-statements/>

## IFRS 11: Joint arrangements
A joint venture (rights to net assets) is equity accounted. A joint operation (rights to assets and obligations for liabilities) is accounted line by line for the investor's share. Proportionate consolidation of joint ventures is not allowed.

**Disclosures:** Nature and extent of interests; summarised financial information of material joint ventures

**Analyst impact:** Equity-accounted joint venture debt is off balance sheet; look in IFRS 12 notes for proportionate leverage.

- IFRS 11, paras 14-18, 20-24: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-11-joint-arrangements/>

## IFRS 12: Disclosure of interests in other entities
Requires a single note on subsidiaries with material non-controlling interests, associates and joint ventures (with summarised financials) and unconsolidated structured entities. This is the place to find the numbers that the equity method hides.

**Disclosures:** Summarised financial information for material associates and joint ventures; dividends received; risks of structured entities

**Analyst impact:** Build proportionate net debt and EBITDA for material equity-accounted investees from this note.

**Recipe:** `associates_share_strip`

- IFRS 12, paras 10-24, B10-B16: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-12-disclosure-of-interests-in-other-entities/>

## IAS 2: Inventories
Inventory is carried at the lower of cost and net realisable value. Cost formulas are first-in first-out or weighted average only, so last-in first-out is prohibited. Write-downs are reversed when the cause disappears, limited to the original write-down.

**Disclosures:** Carrying amount by class; write-downs and reversals; cost of inventories recognised as expense

**Analyst impact:** No LIFO reserve exists for IFRS reporters; for US peers use the LIFO reserve to restate to FIFO.

**Recipe:** `lifo_to_fifo`

- IAS 2, paras 9, 25, 33-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/>

## IAS 7: Statement of cash flows
Cash flows are classed as operating, investing and financing. Operating activities may be shown directly or by the indirect reconciliation from profit. Interest and dividends paid or received may be placed in operating, investing or financing as a consistent policy, which breaks comparability with US GAAP.

**Disclosures:** Components of cash and equivalents; non-cash transactions; changes in liabilities from financing activities; restricted cash

**Analyst impact:** Normalise interest paid and dividends before comparing operating cash flow; under IFRS 16 the principal part of rent moves to financing.

**Recipe:** `ifrs16_to_pre16_ebitda`

- IAS 7, paras 18-20, 31-34, 44A: <https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/>

## IAS 12: Income taxes
Current tax is what is due for the period. Deferred tax arises from temporary differences between carrying amounts and tax bases, with assets recognised only when future taxable profit is probable. Taxes on income only are in scope; zakat in Saudi Arabia is carved out by SOCPA endorsement. A tax rate reconciliation must be disclosed.

**Disclosures:** Tax rate reconciliation; deferred tax by source; unrecognised deferred tax; tax losses

**Analyst impact:** Use the reconciliation to separate recurring from one-off rates; zakat requires a separate treatment.

**Recipe:** `zakat_as_tax`

- IAS 12, paras 5, 12, 15, 24, 79-88: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

## IAS 16: Property, plant and equipment
Items are recognised at cost and depreciated over useful life by component. A company may instead choose the revaluation model for a whole class: fair value is updated regularly, gains go to OCI and a revaluation surplus, and losses reduce the surplus first. Depreciation then rises on the revalued amount.

**Disclosures:** Reconciliation of carrying amounts; depreciation methods and lives; revaluation date and surplus; commitments

**Analyst impact:** Revaluation inflates assets and equity without cash; reverse the surplus to compare return on assets.

**Recipe:** `revaluation_reverse`

- IAS 16, paras 30-31, 39-40, 73: <https://www.ifrs.org/issued-standards/list-of-standards/ias-16-property-plant-and-equipment/>

## IAS 19: Employee benefits
Short-term benefits are expensed as service is rendered. Post-employment defined contribution plans expense the payment; defined benefit plans, including most statutory end-of-service or gratuity schemes, require an actuarial valuation with a discount rate, salary growth and attrition. Service cost goes to profit or loss; remeasurements go to OCI and never recycle.

**Disclosures:** Actuarial assumptions and sensitivity; obligation movement; expected cash flow timing

**Analyst impact:** Treat the end-of-service obligation as debt-like when material; check for cash payout versus accrual in the cash flow.

**Recipe:** `eosb_as_debt_like`

- IAS 19, paras 57, 67-69, 120, 135-144: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>

## IAS 20: Government grants and government assistance
Grants are recognised when there is reasonable assurance of compliance and receipt. Income grants are matched to the cost they compensate, either as other income or as a reduction of that cost. Asset grants are shown as deferred income or deducted from the asset's carrying amount. Below-market government loans carry a grant element.

**Disclosures:** Accounting policy; nature and extent of grants; unfulfilled conditions

**Analyst impact:** Separate grant income from operating performance; gross up when cost deduction hides true capex or margin.

**Recipe:** `gov_grant_gross_up`

- IAS 20, paras 7, 12, 24, 10A: <https://www.ifrs.org/issued-standards/list-of-standards/ias-20-accounting-for-government-grants-and-disclosure-of-government-assistance/>

## IAS 21: Effects of changes in foreign exchange rates
Each entity picks a functional currency. Foreign currency transactions are recorded at the transaction date rate; monetary items are retranslated at the closing rate with differences in profit or loss. Non-monetary items at historical cost stay at the original rate. Translating a foreign operation into a presentation currency uses the closing rate for assets and liabilities, transaction or average rates for income and expenses, with differences in OCI.

**Disclosures:** Net exchange differences in profit or loss; functional currency changes; translation reserve movement

**Analyst impact:** After a devaluation, foreign currency debt generates large losses; strip these to compare operating performance.

**Recipe:** `devaluation_fx_loss_normalise`

- IAS 21, paras 21-23, 28, 39, 52: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>

## IAS 23: Borrowing costs
Interest and related costs directly attributable to acquiring or building a qualifying asset must be added to its cost until the asset is ready. The old option to expense is gone. Income earned from temporarily investing specific borrowings is deducted from capitalised cost.

**Disclosures:** Amount capitalised; capitalisation rate

**Analyst impact:** Interest expense is understated and capex overstated versus an expense-all view; matters most for developers and utilities.

**Recipe:** `capitalised_interest_expense`

- IAS 23, paras 8-14, 26: <https://www.ifrs.org/issued-standards/list-of-standards/ias-23-borrowing-costs/>

## IAS 24: Related party disclosures
Discloses relationships, transactions, balances and commitments with related parties, including key management compensation by category. Government-related entities get a partial exemption but must still describe significant transactions.

**Disclosures:** Parent and ultimate controlling party; key management compensation; balances and terms; guarantees

**Analyst impact:** Large related-party revenue or loans with controlling shareholders raise governance risk; common for family groups in the GCC and Egypt.

- IAS 24, paras 9-18, 25-26: <https://www.ifrs.org/issued-standards/list-of-standards/ias-24-related-party-disclosures/>

## IAS 28: Investments in associates and joint ventures
Significant influence (usually 20 percent or more of votes) triggers the equity method: the investment starts at cost and is moved by the investor's share of profit, OCI and dividends. The share of results sits in one line, often below operating profit. Impairment testing follows IAS 36 and gains from transactions are eliminated.

**Disclosures:** Summarised financials; dividends; unrecognised losses (through IFRS 12)

**Analyst impact:** Associate profit has no cash effect until dividends; exclude it from EBITDA and add investment value to enterprise value bridge.

**Recipe:** `associates_share_strip`

- IAS 28, paras 3, 10, 22, 40-43: <https://www.ifrs.org/issued-standards/list-of-standards/ias-28-investments-in-associates-and-joint-ventures/>

## IAS 29: Financial reporting in hyperinflationary economies
When the functional currency is hyperinflationary (a cumulative three-year rate near or above 100 percent together with qualitative signs) statements are restated into the measuring unit at the reporting date using a general price index. Non-monetary items are indexed, monetary items are left, and the net monetary gain or loss goes to profit or loss. Comparatives are restated.

**Disclosures:** Fact of restatement; price index and level; net monetary position gain or loss

**Analyst impact:** Reported EBIT and equity are inflated or deflated by indexing; restate peers on the same basis before comparing.

**Recipe:** `ias29_restate`

- IAS 29, paras 3, 8, 11-28, 34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-29-financial-reporting-in-hyperinflationary-economies/>

## IAS 33: Earnings per share
Basic EPS divides profit attributable to ordinary holders by the weighted average ordinary shares. Diluted EPS adds the effect of options, convertibles and contingent shares. Bonus issues and share splits restate prior periods.

**Disclosures:** Numerators and denominators; anti-dilutive instruments excluded

**Analyst impact:** Use diluted weighted average shares in market-cap work; watch treasury shares and employee plans.

- IAS 33, paras 10, 19-26, 31, 64: <https://www.ifrs.org/issued-standards/list-of-standards/ias-33-earnings-per-share/>

## IAS 36: Impairment of assets
Assets are written down when carrying amount exceeds the higher of fair value less costs of disposal and value in use. Goodwill and indefinite-life intangibles are tested every year. Impairment (other than goodwill) is reversed if the estimates improve, up to the amount that would have been recognised without impairment.

**Disclosures:** Discount rate; growth rate; headroom; sensitivity of key assumptions; impairment by segment

**Analyst impact:** Reversals create profit with no cash; strip them from recurring earnings. Thin headroom is an early warning for goodwill.

**Recipe:** `impairment_reversal_strip`

- IAS 36, paras 6, 59, 117-123, 124: <https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/>

## IAS 37: Provisions, contingent liabilities and contingent assets
A provision is booked for a present obligation from a past event where an outflow is probable and the amount can be estimated, at the best estimate (discounted if material). Possible obligations are only disclosed. Restructuring and onerous contract rules limit when the charge can be taken.

**Disclosures:** Movement by class; timing and uncertainty; contingent liabilities with estimates

**Analyst impact:** Big provision movements affect earnings quality; treat litigation and decommissioning provisions as debt-like if cash will go out.

**Recipe:** `eosb_as_debt_like`

- IAS 37, paras 14, 36, 45, 72, 86: <https://www.ifrs.org/issued-standards/list-of-standards/ias-37-provisions-contingent-liabilities-and-contingent-assets/>

## IAS 38: Intangible assets
Research cost is expensed. Development cost is capitalised once technical feasibility, intent, ability to use or sell, probable future benefit, resources and reliable measurement are shown. Internally generated brands and customer lists are not capitalised. Finite-life intangibles are amortised; the revaluation model needs an active market.

**Disclosures:** Amortisation; impairment; total research and development expensed; capitalised development movement

**Analyst impact:** Capitalising lifts operating profit and cash flow from operations, and depresses investing cash flow; compare to expensing peers.

**Recipe:** `dev_cost_expense`

- IAS 38, paras 54, 57, 74-75, 107: <https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/>

## IAS 40: Investment property
Property held to earn rent or for capital growth is separate from owner-occupied property. The entity chooses cost or fair value for all investment property. Under fair value, changes go to profit or loss each period and no depreciation is taken. Indian Ind AS allows cost only.

**Disclosures:** Valuation method and inputs; valuer independence; rental income and direct costs; reconciliation of carrying amount

**Analyst impact:** Fair value gains are unrealised; strip them from earnings when comparing real estate groups.

**Recipe:** `revaluation_reverse`

- IAS 40, paras 30-33, 75-79: <https://www.ifrs.org/issued-standards/list-of-standards/ias-40-investment-property/>

## IFRS 8: Operating segments
Listed entities report segments on the same basis management uses internally, with the chief operating decision maker's profit measure, plus a reconciliation to group totals. Entity-wide disclosures cover products, geography and major customers.

**Disclosures:** Segment revenue; profit measure; assets and liabilities if reported to the decision maker; reconciliations; geographic revenue; major customer share

**Analyst impact:** Segment profit measures can differ from group EBIT; tie segment totals to the income statement and note unallocated items.

- IFRS 8, paras 5, 11-13, 23, 28, 32-34: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-8-operating-segments/>
