# IFRS standards the analyst reads

*Generated from `om/intl/standards/ifrs_standards.yaml`. Own words, no copied standard text.*

## IAS 1: Presentation of financial statements
Sets the complete set of statements (financial position, profit or loss and OCI, changes in equity, cash flows, notes), going-concern and accrual basis, current versus non-current classification, and the minimum face line items. Expenses may be analysed by nature or by function; function reporters must also disclose depreciation and staff costs by nature. Until IFRS 18 applies (annual periods from 1 January 2027) no operating profit subtotal is defined, so each company builds its own and the figure is not comparable.

- **Scope:** General-purpose financial statements: the full set of statements, fair presentation, going concern, accruals, materiality and offsetting.
- **Recognition:** No recognition rules; sets classification as current or non-current by the right to defer settlement for at least twelve months after the reporting date.
- **Initial measurement:** Not applicable.
- **Subsequent measurement:** Not applicable.
- **Presentation:** Minimum face line items, expenses by nature or function, current and non-current split, OCI by recyclable and non-recyclable items, comparatives, until IFRS 18 replaces the presentation rules from 2027.
- **Key disclosures:** Accounting policies (material only), judgements, sources of estimation uncertainty, capital management, puttable instruments, dividends.
- **Key judgements:** Going concern, classification of debt with covenants, aggregation, and whether a liability is current when covenants fall due within twelve months.
- **Recent amendments:** Classification of liabilities as current or non-current and non-current liabilities with covenants (2020 and 2022, effective 2024); material accounting policy information (2021); IFRS 18 replaces IAS 1 presentation from 2027.
- **Analyst effect:** Covenant-driven reclassification moves debt into current liabilities and distorts working capital and liquidity ratios; no standard operating profit exists before IFRS 18.

**Analyst impact:** Computed operating profit must be rebuilt consistently; check which items sit above and below the subtotal the company shows.

**Recipe:** `by_nature_ebit`

*Basis: standard-reference; confidence: unverified*

- IAS 1, paras 54-55 (balance sheet), 82 (profit or loss), 99-105 (expense analysis): <https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/>

## IFRS 18: Presentation and disclosure in financial statements
Replaces IAS 1 presentation rules for annual periods beginning on or after 1 January 2027. It splits the income statement into operating, investing and financing categories, forces subtotals for operating profit and profit before financing and income taxes, and requires disclosure of management-defined performance measures with a reconciliation. Comparatives are restated, so the first IFRS 18 year gives a clean operating profit definition for IFRS reporters. Items such as foreign exchange differences are classified by the line they relate to.

- **Scope:** Presentation and disclosure in general-purpose financial statements; replaces IAS 1 presentation rules for annual periods from 1 January 2027 (retrospective).
- **Recognition:** No recognition changes; reclassifies items into operating, investing, financing, income tax and discontinued operations categories.
- **Initial measurement:** No measurement requirements.
- **Subsequent measurement:** No measurement requirements.
- **Presentation:** Mandatory subtotals: operating profit and profit before financing and income taxes; aggregation and disaggregation principles; function reporters disclose operating expenses by nature.
- **Key disclosures:** Management-defined performance measures in one note with reconciliation, unusual items, and by-nature breakdown for function presenters.
- **Key judgements:** Main business activities (for entities with investing or financing as a main business), classification of FX and derivative items, and what counts as a management-defined measure.
- **Recent amendments:** Issued April 2024; IFRS 19 for subsidiaries without public accountability issued 2024 for 2027; cash flow statement starts from operating profit under IAS 7 amendments.
- **Analyst effect:** Operating profit finally comparable across IFRS reporters; EBITDA and adjusted measures must be reconciled; expect restated comparatives and a one-off definitional break in 2027.

**Analyst impact:** Expect restated operating profit and EBIT definitions from 2027; keep both bases during the transition.

**Recipe:** `by_nature_ebit`

*Basis: standard-reference; confidence: unverified*

- IFRS 18, Categories, subtotals and MPM disclosure: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/>

## IFRS 15: Revenue from contracts with customers
Revenue follows a five-step model for contracts with customers: identify the contract, identify the separate performance obligations, determine the transaction price (including variable consideration and financing), allocate it by relative stand-alone selling price, and recognise revenue when or as control passes (over time if a defined test is met, otherwise at a point in time). Principal versus agent decides gross versus net revenue. Contract assets, contract liabilities (advance billings) and receivables appear on the balance sheet, and incremental costs of obtaining a contract may be capitalised and amortised.

- **Scope:** Revenue from contracts with customers, except leases, insurance, financial instruments and some non-monetary exchanges.
- **Recognition:** Five-step model: identify the contract, identify separate performance obligations, determine the transaction price, allocate by stand-alone selling price, recognise revenue when or as control passes (over time if the customer simultaneously benefits, the asset is enhanced under customer control, or there is no alternative use plus a right to payment; otherwise at a point in time).
- **Initial measurement:** Transaction price net of variable consideration (expected value or most likely amount) only to the extent it is highly probable that a significant reversal will not occur (the constraint); adjust for significant financing and non-cash consideration.
- **Subsequent measurement:** Revisit estimates of variable consideration each period; progress measured by input or output methods; contract costs amortised.
- **Presentation:** Contract assets, contract liabilities and receivables; revenue separately from other income.
- **Key disclosures:** Disaggregation, contract balances and movements, remaining performance obligations, significant judgements, assets from costs to obtain or fulfil.
- **Key judgements:** The variable-consideration constraint, principal versus agent, licence timing (right to use versus access), distinct goods bundled with services, and percentage-of-completion progress measures.
- **Recent amendments:** No major amendments in 2019-2026; clarifications of 2016 are embedded; IFRS 18 only changes presentation.
- **Analyst effect:** Revenue timing and gross versus net presentation move margins; contract liabilities are a leading indicator of future revenue and a source of operating cash.

**Analyst impact:** Check principal-agent judgement, percentage-of-completion revenue and contract liabilities for developers; backlog comes from the remaining performance obligation note.

**Recipe:** `revenue_principal_agent_net`

*Basis: standard-reference; confidence: unverified*

- IFRS 15, paras 9, 31-38, B34-B38, 110-129: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/>

## IFRS 16: Leases
A lessee recognises a right-of-use asset and a lease liability for almost every lease at commencement, the liability being the present value of unpaid payments at the rate implicit in the lease or the incremental borrowing rate. Afterwards it depreciates the right-of-use asset and accrues interest on the lease liability, so the single rent expense of the old model is replaced by depreciation plus interest, which raises EBITDA and moves the principal part of payments to financing cash flow. Short-term leases (up to twelve months) and low-value assets may stay as a straight expense. Lessors keep the finance versus operating classification.

- **Scope:** All leases except some rights under other standards (mineral rights, biological assets, service concessions, licences of intellectual property granted by a lessor).
- **Recognition:** Lessee recognises a right-of-use asset and a lease liability at commencement for all leases except short-term (12 months or less) and low-value asset exemptions; lessors classify as finance or operating leases.
- **Initial measurement:** Liability at the present value of unpaid lease payments using the implicit rate or the incremental borrowing rate; asset equals the liability plus initial direct costs, prepayments and restoration costs.
- **Subsequent measurement:** Depreciate the asset and accrue interest on the liability; remeasure on reassessment or modification (term, index-linked payments, purchase option); lessor finance leases as net investment.
- **Presentation:** Right-of-use assets and lease liabilities separately or in notes; depreciation in operating costs, interest in finance costs; principal repayments in financing cash flow.
- **Key disclosures:** Right-of-use movement by class, maturity analysis, total cash outflow, expense on short-term, low-value and variable payments, sale and leaseback gains.
- **Key judgements:** Lease term including extension options, whether a contract contains a lease, discount rate, separating lease and non-lease components, and variable payments.
- **Recent amendments:** COVID-19 rent concession relief (2020-2021); sale and leaseback with variable payments (2022, effective 2024) requires lessee measurement without recognising gains on retained rights.
- **Analyst effect:** EBITDA rises as rent leaves operating costs, operating cash flow rises and financing outflows rise; net debt may include lease liabilities; convert to a pre-16 basis to compare with US GAAP operating-lease reporters.

**Analyst impact:** Compare EBITDA with pre-16 or US GAAP peers; include lease liabilities in net debt only when EBITDA is also on the post-16 basis.

**Recipe:** `ifrs16_to_pre16_ebitda`

*Basis: standard-reference; confidence: unverified*

- IFRS 16, paras 22-38 (lessee), 47-60 (presentation and disclosure): <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

## IFRS 9: Financial instruments
Financial assets are classified by the business model and the contractual cash flow test into amortised cost, fair value through OCI or fair value through profit or loss. Impairment uses expected credit losses (ECL) in three stages: stage 1 books twelve-month expected losses, stage 2 (significant increase in credit risk since initial recognition) and stage 3 (credit-impaired) book lifetime losses, and interest income moves to net carrying amount in stage 3. Estimates must reflect reasonable and supportable forward-looking information, such as macroeconomic scenarios weighted by probability, not only past loss rates; receivables without a financing element can use a simple provision matrix. Hedge accounting aligns with risk management.

- **Scope:** Recognition, classification, impairment and derecognition of financial assets and liabilities, and hedge accounting; excludes items covered by IFRS 10-11, IFRS 16, IFRS 2 and IFRS 17.
- **Recognition:** Recognise when the entity becomes party to the contract; derecognise assets when cash flow rights expire or risks and rewards transfer; liabilities when extinguished.
- **Initial measurement:** Fair value plus transaction costs (not for items at FVTPL); trade receivables without a significant financing component at transaction price.
- **Subsequent measurement:** Assets by business model and cash flow test: amortised cost, FVOCI or FVTPL; ECL impairment in three stages (12-month loss in stage 1, lifetime when credit risk rose significantly or credit-impaired) using forward-looking information; liabilities mainly at amortised cost.
- **Presentation:** Impairment losses shown separately in profit or loss; interest revenue on effective-interest basis; hedge results in the line they hedge or OCI reserves for cash flow hedges.
- **Key disclosures:** Through IFRS 7: ECL movement, credit risk, fair value levels, hedging relationships.
- **Key judgements:** Business model assessment, SPPI test, significant increase in credit risk, macroeconomic scenario weights, and hedge accounting (fair value, cash flow and net investment models; economic relationship, credit risk dominance and hedge ratio replace the old 80-125 percent test).
- **Recent amendments:** 2019-2020 interest rate benchmark reform relief (phases 1 and 2); 2024 amendments on settlement of liabilities through electronic payment systems and on SPPI and contingent features, effective 2026.
- **Analyst effect:** Credit cost is booked earlier, so provisions lead write-offs; hedge accounting shifts FX and rate effects between OCI and profit; fair value option and FVTPL items add volatility to earnings and EPS.

**Analyst impact:** Bad-debt charges may be lumpier and earlier; for Egypt the equivalent is EAS 47 once adopted.

**Recipe:** `eas_to_ifrs_map`

*Basis: standard-reference; confidence: unverified*

- IFRS 9, paras 4.1.1-4.1.5, 5.5.1-5.5.20: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/>

## IFRS 3: Business combinations
Acquisitions use the acquisition method: identifiable assets and liabilities at fair value, goodwill as the residual, acquisition costs expensed, contingent consideration at fair value with later changes in profit or loss. Non-controlling interest may be measured at fair value (full goodwill) or at its share of net assets. Pooling of interests is not allowed for acquisitions, and combinations under common control are outside the scope (practice varies, commonly book value or predecessor accounting; Ind AS 103 mandates pooling for them).

- **Scope:** Transactions in which an acquirer obtains control of a business; excludes common-control combinations, asset acquisitions and joint ventures formation.
- **Recognition:** Apply the acquisition method: identify the acquirer, the acquisition date, recognise identifiable assets and liabilities (including contingent liabilities that are present obligations) and goodwill.
- **Initial measurement:** Identifiable net assets at fair value (with exceptions such as deferred tax, employee benefits, leases); consideration at fair value including contingent consideration; non-controlling interest at fair value or share of net assets; acquisition costs expensed.
- **Subsequent measurement:** Goodwill is not amortised and is tested annually under IAS 36; contingent consideration classified as a liability is remeasured through profit or loss; measurement period of up to twelve months for provisional values.
- **Presentation:** Goodwill and acquired intangibles on the balance sheet; acquisition costs and remeasurements in profit or loss; cash paid net of cash acquired in investing.
- **Key disclosures:** Consideration, assets and liabilities acquired, goodwill drivers and tax deductibility, acquired receivables, revenue and profit since acquisition and pro forma.
- **Key judgements:** Business versus asset acquisition (concentration test), identifying intangibles, fair value of contingent consideration and earn-outs, and bargain purchase gains.
- **Recent amendments:** 2018 amendments on the definition of a business and optional concentration test; 2020 reference to the Conceptual Framework.
- **Analyst effect:** Purchase-price amortisation lowers EBIT and earnings but not EBITDA; goodwill inflates equity and invites later impairment; earn-out remeasurements distort profit.

**Analyst impact:** Acquired intangibles amortisation is non-cash and often excluded from adjusted earnings; check goodwill share of equity.

*Basis: standard-reference; confidence: unverified*

- IFRS 3, paras 4-5, 18-19, 32, 53: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-3-business-combinations/>

## IFRS 10: Consolidated financial statements
Control, not ownership percentage, decides consolidation: power over relevant activities, exposure to variable returns and the link between them. Subsidiaries are consolidated line by line with non-controlling interests shown within equity. Investment entities are an exception.

- **Scope:** Consolidated financial statements of a parent and subsidiaries; investment entities are exempt from consolidating most investees.
- **Recognition:** Consolidate every entity that is controlled: power over relevant activities, exposure to variable returns, and ability to use power to affect them.
- **Initial measurement:** Subsidiary assets and liabilities combined line by line with intragroup items eliminated; non-controlling interests shown separately.
- **Subsequent measurement:** Uniform accounting policies and reporting dates (within three months); transactions with non-controlling interests are equity transactions; loss of control triggers derecognition and gain or loss.
- **Presentation:** Profit and equity attributed to owners and to non-controlling interests.
- **Key disclosures:** Through IFRS 12: judgements on control, restrictions, material non-controlling interests, structured entities.
- **Key judgements:** De facto control with less than half of votes, potential voting rights, principal versus agent for funds, and structured entities.
- **Recent amendments:** 2014 and 2015 amendments on investment entities and sale of assets to an associate; effective-date deferral for the sale or contribution amendment remains open.
- **Analyst effect:** EBITDA and debt include 100 percent of subsidiaries; subtract non-controlling interests (and their share of net debt) when valuing the parent.

**Analyst impact:** Use profit attributable to owners for per-share work; remember EBITDA covers 100 percent of consolidated subsidiaries.

*Basis: standard-reference; confidence: unverified*

- IFRS 10, paras 5-18, B2-B85: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-10-consolidated-financial-statements/>

## IFRS 11: Joint arrangements
A joint venture (rights to net assets) is equity accounted. A joint operation (rights to assets and obligations for liabilities) is accounted line by line for the investor's share. Proportionate consolidation of joint ventures is not allowed.

- **Scope:** Arrangements controlled jointly under a contract.
- **Recognition:** Classify as a joint operation (investor has rights to assets and obligations) or a joint venture (rights to net assets) by structure, legal form, contract terms and other facts.
- **Initial measurement:** Joint operation: recognise own share of assets, liabilities, revenue and expenses; joint venture: equity method at cost.
- **Subsequent measurement:** Joint venture follows IAS 28 equity accounting; joint operation share kept line by line.
- **Presentation:** Share of profit of joint ventures in one line; joint operation shares inside normal lines.
- **Key disclosures:** Through IFRS 12: nature and risks of joint arrangements, summarised financial information.
- **Key judgements:** Structure and legal form classification, separate vehicles, and acquisition of an interest in a joint operation that is a business.
- **Recent amendments:** 2014 amendment on acquiring an interest in a joint operation; open deferral of the IFRS 10/IAS 28 sale amendment.
- **Analyst effect:** Proportionate share of joint operation EBITDA and debt is in the numbers; joint venture debt and EBITDA are off the group figures and need a manual proportionate adjustment.

**Analyst impact:** Equity-accounted joint venture debt is off balance sheet; look in IFRS 12 notes for proportionate leverage.

**Recipe:** `associates_share_strip`

*Basis: standard-reference; confidence: unverified*

- IFRS 11, paras 14-18, 20-24: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-11-joint-arrangements/>

## IFRS 12: Disclosure of interests in other entities
Requires a single note on subsidiaries with material non-controlling interests, associates and joint ventures (with summarised financials) and unconsolidated structured entities. This is the place to find the numbers that the equity method hides.

- **Scope:** Interests in subsidiaries, joint arrangements, associates and unconsolidated structured entities.
- **Recognition:** Disclosure standard with no recognition rules.
- **Initial measurement:** Not applicable.
- **Subsequent measurement:** Not applicable.
- **Presentation:** Dedicated note with summarised financial information per material associate and joint venture.
- **Key disclosures:** Significant judgements, restrictions on assets and cash, risks from structured entities, summarised financials, dividends received.
- **Key judgements:** Materiality of investees, what is a structured entity, and degree of detail given.
- **Recent amendments:** Investment entity consequential changes (2012-2014); IFRS 18 aligns profit measures.
- **Analyst effect:** Supplies the numbers needed for proportionate net debt and EBITDA and for non-controlling interest values.

**Analyst impact:** Build proportionate net debt and EBITDA for material equity-accounted investees from this note.

**Recipe:** `associates_share_strip`

*Basis: standard-reference; confidence: unverified*

- IFRS 12, paras 10-24, B10-B16: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-12-disclosure-of-interests-in-other-entities/>

## IAS 2: Inventories
Inventory is carried at the lower of cost and net realisable value. Cost formulas are first-in first-out (FIFO) or weighted average only, so last-in first-out (LIFO) is prohibited, in contrast to US GAAP, which permits LIFO. Write-downs are reversed when the cause disappears, limited to the original write-down.

- **Scope:** Inventories except financial instruments, biological assets and work in progress under construction contracts (IFRS 15).
- **Recognition:** Recognise as expense when sold; write-downs when net realisable value is below cost.
- **Initial measurement:** Cost: purchase price, conversion costs including fixed production overheads on normal capacity, and other costs bringing inventory to location and condition.
- **Subsequent measurement:** Lower of cost and net realisable value; FIFO or weighted average (LIFO prohibited); reversal of write-downs when NRV recovers.
- **Presentation:** Inventory as current asset; cost of inventories sold in cost of sales or by nature.
- **Key disclosures:** Policies, carrying amount by class, write-downs and reversals, amounts pledged.
- **Key judgements:** Net realisable value estimates, capacity assumptions for overhead absorption, and commodity inventories at fair value less costs to sell for brokers.
- **Recent amendments:** No amendments in 2019-2026.
- **Analyst effect:** Cost of sales and margins depend on the formula; no LIFO reserve under IFRS, so convert US LIFO peers to FIFO.

**Analyst impact:** No LIFO reserve exists for IFRS reporters; for US peers use the LIFO reserve to restate to FIFO.

**Recipe:** `lifo_to_fifo`

*Basis: standard-reference; confidence: unverified*

- IAS 2, paras 9, 25, 33-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/>

## IAS 7: Statement of cash flows
Cash flows are classed as operating, investing and financing. Operating activities may be shown directly or by the indirect reconciliation from profit. Interest and dividends paid or received may be placed in operating, investing or financing as a consistent policy, which breaks comparability with US GAAP.

- **Scope:** Statement of cash flows for all entities.
- **Recognition:** Classify cash flows into operating, investing and financing.
- **Initial measurement:** Cash and cash equivalents: short-term highly liquid investments with insignificant risk of changes in value.
- **Subsequent measurement:** Not applicable.
- **Presentation:** Operating flows by the direct or indirect method; interest and dividends classified consistently by policy; taxes in operating unless identified with investing or financing.
- **Key disclosures:** Components of cash, non-cash transactions, changes in liabilities from financing, restrictions on cash, supplier finance arrangements effects.
- **Key judgements:** Classification of interest, dividends and lease payments, cash equivalents boundary, and where supplier finance outflows belong.
- **Recent amendments:** Supplier finance arrangements disclosures (2023, effective 2024); IFRS 18 changes the starting line to operating profit and removes interest and dividend choices from 2027.
- **Analyst effect:** Interest placement changes operating cash flow and free cash flow; supplier finance can inflate operating cash flow while hiding debt.

**Analyst impact:** Normalise interest paid and dividends before comparing operating cash flow; under IFRS 16 the principal part of rent moves to financing.

**Recipe:** `ifrs16_to_pre16_ebitda`

*Basis: standard-reference; confidence: unverified*

- IAS 7, paras 18-20, 31-34, 44A: <https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/>

## IAS 12: Income taxes
Income tax follows the balance-sheet liability method: current tax is what is payable for the period, and deferred tax is recognised on temporary differences between carrying amounts and tax bases, measured at tax rates enacted or substantively enacted by the reporting date. A deferred tax asset (including for tax losses) is recognised only to the extent that future taxable profit is probable. Deferred tax is not discounted. Taxes on income only are in scope; zakat in Saudi Arabia is handled outside IAS 12. A tax rate reconciliation must be disclosed.

- **Scope:** Taxes on profits, including withholding taxes on distributions; excludes non-income taxes and (in Saudi Arabia) zakat.
- **Recognition:** Recognise current tax payable and deferred tax on temporary differences using the balance-sheet liability method; recognise deferred tax assets only to the extent that taxable profit is probable; initial recognition exemption has narrowed.
- **Initial measurement:** Use rates enacted or substantively enacted at the reporting date; deferred tax is not discounted.
- **Subsequent measurement:** Reassess recoverability of deferred tax assets each period; tax on items in OCI or equity goes there.
- **Presentation:** Tax expense line, deferred tax as non-current, offsetting only where a legal right exists; no discounting.
- **Key disclosures:** Tax rate reconciliation, deferred tax by temporary difference, unrecognised losses and credits, uncertain positions via IFRIC 23, Pillar Two current tax.
- **Key judgements:** Recoverability of deferred tax assets, uncertain tax positions, outside basis differences on subsidiaries, and tax on leases and decommissioning.
- **Recent amendments:** Deferred tax on leases and decommissioning obligations (2021, effective 2023); International Tax Reform Pillar Two model rules temporary exception and disclosures (2023, immediate effect); IFRIC 23 (2019).
- **Analyst effect:** Effective tax rate swings from one-off deferred tax items or tax losses; normalise to a statutory rate and add Pillar Two top-up tax for large groups.

**Analyst impact:** Use the reconciliation to separate recurring from one-off rates; zakat requires a separate treatment.

**Recipe:** `zakat_as_tax`

*Basis: standard-reference; confidence: unverified*

- IAS 12, paras 5, 12, 15, 24, 79-88: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

## IAS 16: Property, plant and equipment
Property, plant and equipment is initially recognised at cost and then carried under one of two models for each class: the cost model (cost less accumulated depreciation and impairment) or the revaluation model (fair value at the revaluation date less later depreciation, with regular updates). Revaluation gains go to OCI and a revaluation surplus, and losses reduce the surplus first and then hit profit. Components with different lives are depreciated separately, and depreciation rises on the revalued amount.

- **Scope:** Property, plant and equipment held for use that are expected to be used for more than one period; excludes investment property, biological assets and assets held for sale.
- **Recognition:** Recognise when future economic benefits are probable and cost is reliably measurable; spare parts and major inspections as components.
- **Initial measurement:** Cost: purchase price, directly attributable costs and estimated restoration costs; borrowing costs of qualifying assets capitalised; proceeds from testing before use now go to profit or loss.
- **Subsequent measurement:** Cost model or revaluation model by class; depreciation over useful life by component with annual review of residual value, life and method; impairment under IAS 36.
- **Presentation:** Separate class lines; depreciation by function or nature; revaluation surplus in OCI.
- **Key disclosures:** Reconciliation of carrying amounts, methods and lives, revalued amounts and surplus, commitments, assets pledged.
- **Key judgements:** Useful lives and residual values, component identification, revaluation valuer inputs, and when assets are available for use.
- **Recent amendments:** Proceeds before intended use (2020, effective 2022); IFRS 18 only presentation.
- **Analyst effect:** Depreciation policy drives EBIT and capital intensity; the revaluation model inflates equity and depreciation base, reverse it for return on capital.

**Analyst impact:** Revaluation inflates assets and equity without cash; reverse the surplus to compare return on assets.

**Recipe:** `revaluation_reverse`

*Basis: standard-reference; confidence: unverified*

- IAS 16, paras 30-31, 39-40, 73: <https://www.ifrs.org/issued-standards/list-of-standards/ias-16-property-plant-and-equipment/>

## IAS 19: Employee benefits
Short-term benefits are expensed as service is rendered. Defined contribution plans expense the payment. Defined benefit plans, including most statutory end-of-service or gratuity schemes, are measured with the projected unit credit method: an actuary projects benefits using salary growth, attrition and mortality and discounts them at high-quality bond yields. Current service cost and net interest go to profit or loss; remeasurements (actuarial gains and losses) go to OCI and are not recycled to profit.

- **Scope:** All employee benefits: short-term, post-employment (defined contribution and defined benefit), other long-term and termination benefits.
- **Recognition:** Expense short-term benefits as service is rendered; recognise the net defined benefit liability or asset for defined benefit plans, with the asset limited by the asset ceiling.
- **Initial measurement:** Projected unit credit method for the obligation, discounted at high-quality corporate bond yields (or government bonds where no deep market); plan assets at fair value.
- **Subsequent measurement:** Current service cost and net interest in profit or loss; remeasurements (actuarial gains and losses, return on assets, change in ceiling) in OCI and not recycled; settlement and curtailment gains in profit or loss.
- **Presentation:** Net liability or asset on the balance sheet; service cost in operating expenses, interest in finance items.
- **Key disclosures:** Actuarial assumptions and sensitivity, reconciliation of obligation and plan assets, asset allocation, funding, expected contributions.
- **Key judgements:** Discount rate, salary growth, mortality and attrition, asset ceiling and minimum funding (IFRIC 14), classification of plans as defined contribution or benefit, and statutory end-of-service schemes.
- **Recent amendments:** Plan amendment, curtailment or settlement: use updated assumptions for the rest of the period (2018, effective 2019).
- **Analyst effect:** Treat net deficits as debt-like (after tax); discount-rate changes move OCI and equity, not earnings; end-of-service schemes are debt-like even when unfunded.

**Analyst impact:** Treat the end-of-service obligation as debt-like when material; check for cash payout versus accrual in the cash flow.

**Recipe:** `eosb_as_debt_like`

*Basis: standard-reference; confidence: unverified*

- IAS 19, paras 57, 67-69, 120, 135-144: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>

## IAS 20: Government grants and government assistance
Grants are recognised when there is reasonable assurance of compliance and receipt. Income grants are matched to the cost they compensate, either as other income or as a reduction of that cost. Asset grants are shown as deferred income or deducted from the asset's carrying amount. Below-market government loans carry a grant element.

- **Scope:** Government grants and other government assistance, except tax benefits through the tax system.
- **Recognition:** Recognise when there is reasonable assurance that conditions will be met and the grant will be received; match to related costs.
- **Initial measurement:** Fair value of the asset or amount received; below-market government loans carry a grant element measured as the difference from market rate under IFRS 9.
- **Subsequent measurement:** Income grants in profit or loss over the periods costs are recognised; asset grants as deferred income or deducted from the asset; repayment accounted as a change in estimate.
- **Presentation:** Separate other income or reduction of the related expense; deferred income as a liability.
- **Key disclosures:** Policy, nature and extent of grants, unfulfilled conditions and contingencies.
- **Key judgements:** Reasonable assurance, whether a benefit is a grant or revenue, and gross versus net presentation.
- **Recent amendments:** No amendments in 2019-2026; new US GAAP disclosure rules (ASU 2021-10) differ.
- **Analyst effect:** Netting grants against costs raises margins and lowers capex; gross up and exclude grants that may end.

**Analyst impact:** Separate grant income from operating performance; gross up when cost deduction hides true capex or margin.

**Recipe:** `gov_grant_gross_up`

*Basis: standard-reference; confidence: unverified*

- IAS 20, paras 7, 12, 24, 10A: <https://www.ifrs.org/issued-standards/list-of-standards/ias-20-accounting-for-government-grants-and-disclosure-of-government-assistance/>

## IAS 21: Effects of changes in foreign exchange rates
Each entity picks a functional currency. Foreign currency transactions are recorded at the transaction date rate; monetary items are retranslated at the closing rate with differences in profit or loss. Non-monetary items at historical cost stay at the original rate. Translating a foreign operation into a presentation currency uses the closing rate for assets and liabilities, transaction or average rates for income and expenses, with differences in OCI.

- **Scope:** Foreign currency transactions, foreign operations and presentation currency; excludes derivatives and hedge accounting under IFRS 9.
- **Recognition:** Translate transactions into the functional currency at the date of transaction; monetary items at the closing rate at each reporting date.
- **Initial measurement:** Functional currency is the currency of the primary economic environment (sales prices, costs, financing, retention of receipts); initial foreign items at the transaction-date rate (IFRIC 22 for advance consideration).
- **Subsequent measurement:** Monetary items retranslated at closing rate with differences in profit or loss; non-monetary items at historical cost keep their rate; foreign operations translated at closing rate for balance sheet and transaction or average rate for income with differences in OCI, recycled on disposal.
- **Presentation:** Exchange differences disclosed; translation reserve in equity.
- **Key disclosures:** Net exchange differences in profit or loss, functional currency changes, translation reserve movement.
- **Key judgements:** Functional currency indicators, hyperinflation interaction, net investment designation and lack of exchangeability.
- **Recent amendments:** Lack of exchangeability (2023, effective 2025): estimate a spot rate when a currency cannot be exchanged and disclose the effect; IFRIC 22 (2016).
- **Analyst effect:** Devaluation flows through finance costs or other expense and can swamp EBIT; strip FX out of EBITDA and recurring profit, and translate peers on the same rate basis.

**Analyst impact:** After a devaluation, foreign currency debt generates large losses; strip these to compare operating performance.

**Recipe:** `devaluation_fx_loss_normalise`

*Basis: standard-reference; confidence: unverified*

- IAS 21, paras 21-23, 28, 39, 52: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>

## IAS 23: Borrowing costs
Borrowing costs directly attributable to the acquisition, construction or production of a qualifying asset, meaning one that takes a substantial period of time to get ready for its intended use or sale, are capitalised into the asset's cost until it is ready. Costs on specific borrowings are capitalised net of investment income earned on them; general borrowings use a weighted capitalisation rate. The old option to expense is gone. Capitalisation pauses during extended suspension of active development.

- **Scope:** Borrowing costs for qualifying assets; exempts assets measured at fair value and inventories produced in large quantities repetitively.
- **Recognition:** Capitalise borrowing costs directly attributable to acquisition, construction or production of a qualifying asset that takes a substantial period to get ready; expense the rest.
- **Initial measurement:** Specific borrowings: actual cost less investment income earned; general borrowings: weighted average capitalisation rate on expenditure.
- **Subsequent measurement:** Part of asset cost, depreciated; capitalisation suspended during extended interruption and ceases when substantially ready.
- **Presentation:** Interest in finance costs reduced by the capitalised part; cash interest paid classification under IAS 7.
- **Key disclosures:** Amount capitalised and the capitalisation rate.
- **Key judgements:** Whether an asset is qualifying, start and end dates, and treatment of general funds used for development.
- **Recent amendments:** Borrowings that remain outstanding after the related asset is ready are general borrowings (2019 annual improvements).
- **Analyst effect:** Interest cover and EBIT look better because interest is in capex; add capitalised interest back to interest expense.

**Analyst impact:** Interest expense is understated and capex overstated versus an expense-all view; matters most for developers and utilities.

**Recipe:** `capitalised_interest_expense`

*Basis: standard-reference; confidence: unverified*

- IAS 23, paras 8-14, 26: <https://www.ifrs.org/issued-standards/list-of-standards/ias-23-borrowing-costs/>

## IAS 24: Related party disclosures
Entities disclose related party relationships, transactions, balances and commitments, including the parent and ultimate controlling party. Key management personnel, meaning those with authority over planning, directing and controlling the entity, have their compensation disclosed in total and by category (short-term, post-employment, other long-term, termination, share-based). Government-related entities receive a partial exemption but must still describe individually significant transactions.

- **Scope:** Related party relationships, transactions, balances and commitments; key management compensation.
- **Recognition:** Disclosure only.
- **Initial measurement:** Not applicable.
- **Subsequent measurement:** Not applicable.
- **Presentation:** Notes: parent and ultimate controlling party, key management personnel compensation by category (short-term, post-employment, other long-term, termination, share-based), transaction amounts and balances with terms and guarantees.
- **Key disclosures:** Names of related parties, nature of relationships, outstanding balances, terms, provisions for doubtful debts, commitments, government-related entity exemptions.
- **Key judgements:** Who is a related party (family, joint ventures, post-employment plans), what qualifies as key management, and arm's-length statements.
- **Recent amendments:** No amendments in 2019-2026.
- **Analyst effect:** Large dealings with controlling shareholders or government-related entities affect revenue quality and governance; key management pay shows alignment.

**Analyst impact:** Large related-party revenue or loans with controlling shareholders raise governance risk; common for family groups in the GCC and Egypt.

**Recipe:** `associates_share_strip`

*Basis: standard-reference; confidence: unverified*

- IAS 24, paras 9-18, 25-26: <https://www.ifrs.org/issued-standards/list-of-standards/ias-24-related-party-disclosures/>

## IAS 28: Investments in associates and joint ventures
Significant influence (usually 20 percent or more of votes) triggers the equity method: the investment starts at cost and is moved by the investor's share of profit, OCI and dividends. The share of results sits in one line, often below operating profit. Impairment testing follows IAS 36 and gains from transactions are eliminated.

- **Scope:** Investments in associates (significant influence) and joint ventures.
- **Recognition:** Equity method from the date significant influence arises (usually 20 percent or more of votes).
- **Initial measurement:** Cost, with goodwill included in the carrying amount and not tested separately; excess of share of net fair values recognised in profit.
- **Subsequent measurement:** Add the share of profit or loss and OCI, deduct dividends; stop at zero unless there are obligations; tested under IAS 36 for impairment; use uniform policies.
- **Presentation:** Share of results in one line, investment in one balance-sheet line.
- **Key disclosures:** Through IFRS 12: summarised financials, unrecognised losses, restrictions.
- **Key judgements:** Significant influence with less than 20 percent, long-term interests that form part of the net investment, and the profit on transactions with the investee.
- **Recent amendments:** Long-term interests in associates (2017, effective 2019); open deferral of the sale or contribution amendment.
- **Analyst effect:** Exclude share of associates from EBITDA, add the investment at value to enterprise value, and note that profit is not cash until dividends.

**Analyst impact:** Associate profit has no cash effect until dividends; exclude it from EBITDA and add investment value to enterprise value bridge.

**Recipe:** `associates_share_strip`

*Basis: standard-reference; confidence: unverified*

- IAS 28, paras 3, 10, 22, 40-43: <https://www.ifrs.org/issued-standards/list-of-standards/ias-28-investments-in-associates-and-joint-ventures/>

## IAS 29: Financial reporting in hyperinflationary economies
When the functional currency is hyperinflationary (a cumulative three-year rate near or above 100 percent together with qualitative signs) statements are restated into the measuring unit at the reporting date using a general price index. Non-monetary items are indexed, monetary items are left, and the net monetary gain or loss goes to profit or loss. Comparatives are restated.

- **Scope:** Entities whose functional currency is that of a hyperinflationary economy, assessed with indicators including a cumulative three-year inflation rate near or above 100 percent.
- **Recognition:** Restate non-monetary items and equity by a general price index; recognise the net monetary gain or loss in profit.
- **Initial measurement:** Statements expressed in the measuring unit at the reporting date, with comparatives restated.
- **Subsequent measurement:** Revalue each period by the index change; income statement restated from transaction dates; no restatement of monetary items.
- **Presentation:** Gain or loss on net monetary position in profit or loss; restated comparatives; translation of a hyperinflationary operation uses the closing rate for all amounts.
- **Key disclosures:** Fact of restatement, index and level, monetary position gain or loss.
- **Key judgements:** When an economy becomes or ceases to be hyperinflationary and the choice of index.
- **Recent amendments:** IFRIC agenda decision on assessing hyperinflation (2022) and annual lists of affected economies; check each year-end list.
- **Analyst effect:** Restated earnings and equity are not comparable to other markets; use constant-currency and compare operating cash flow.

**Analyst impact:** Reported EBIT and equity are inflated or deflated by indexing; restate peers on the same basis before comparing.

**Recipe:** `ias29_restate`

*Basis: standard-reference; confidence: unverified*

- IAS 29, paras 3, 8, 11-28, 34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-29-financial-reporting-in-hyperinflationary-economies/>

## IAS 33: Earnings per share
Basic earnings per share divides profit attributable to ordinary equity holders by the weighted average number of ordinary shares outstanding. Diluted EPS adjusts both numerator and denominator for dilutive potential ordinary shares such as options, warrants, convertibles and contingently issuable shares, using the treasury share method for options. Potential shares that would increase EPS (antidilutive ones) are ignored. Bonus issues and splits restate prior periods; EPS is shown on continuing and total profit.

- **Scope:** Earnings per share for entities with publicly traded ordinary shares.
- **Recognition:** Disclosure of basic and diluted EPS on continuing operations and total.
- **Initial measurement:** Basic: profit to ordinary holders (after preference dividends) over weighted average shares; Diluted: add dilutive potential ordinary shares.
- **Subsequent measurement:** Restate for bonus issues, splits and share consolidations; options use the treasury stock method; convertibles use the if-converted method; antidilutive potential shares are excluded.
- **Presentation:** EPS on the face of the statement of profit or loss.
- **Key disclosures:** Numerators and denominators, instruments that could dilute, antidilutive instruments.
- **Key judgements:** Contingently issuable shares, ranking of potential shares, and the control number (profit from continuing operations).
- **Recent amendments:** No amendments in 2019-2026; IFRS 18 consequential edits from 2027.
- **Analyst effect:** Use diluted weighted average shares for market cap work and normalised EPS; watch buybacks and treasury shares.

**Analyst impact:** Use diluted weighted average shares in market-cap work; watch treasury shares and employee plans.

*Basis: standard-reference; confidence: unverified*

- IAS 33, paras 10, 19-26, 31, 64: <https://www.ifrs.org/issued-standards/list-of-standards/ias-33-earnings-per-share/>

## IAS 36: Impairment of assets
An asset is impaired when its carrying amount exceeds its recoverable amount, which is the higher of fair value less costs of disposal (FVLCD) and value in use (VIU, the present value of expected cash flows). Testing is done for cash-generating units (CGUs) when assets do not generate independent inflows. Goodwill and indefinite-life or not-yet-available intangibles are tested at least annually; other assets when an indicator exists. Impairment of assets other than goodwill can be reversed if estimates improve, up to the carrying amount that would have existed without the impairment; goodwill impairment is never reversed. US GAAP differs: no reversal for assets held and used.

- **Scope:** Impairment of PPE, intangibles, goodwill, right-of-use assets and investments in subsidiaries, associates and joint ventures; excludes inventories, deferred tax, financial instruments and others.
- **Recognition:** Test when an indicator exists; test goodwill, indefinite-life and not-yet-available intangibles annually; recognise a loss when carrying amount exceeds recoverable amount.
- **Initial measurement:** Recoverable amount is the higher of fair value less costs of disposal and value in use (present value of cash flows from continuing use with pre-tax discount rate).
- **Subsequent measurement:** Impairment first reduces goodwill allocated to the cash-generating unit, then other assets pro rata; reversals allowed for assets other than goodwill, capped at depreciated cost; no reversal of goodwill.
- **Presentation:** Impairment in profit or loss (or against revaluation surplus); reversal in profit.
- **Key disclosures:** Key assumptions (growth, discount rate), headroom, sensitivity, goodwill allocation, impairment by segment.
- **Key judgements:** CGU identification, cash flow forecasts, terminal growth, discount rate, and allocation of corporate assets and goodwill.
- **Recent amendments:** Recoverable amount disclosures for non-financial assets (2013); consequential changes for IFRS 18 only.
- **Analyst effect:** Impairments are non-cash but signal weak returns; reversals inflate IFRS earnings versus US GAAP, where reversals are prohibited for held-and-used assets.

**Analyst impact:** Reversals create profit with no cash; strip them from recurring earnings. Thin headroom is an early warning for goodwill.

**Recipe:** `impairment_reversal_strip`

*Basis: standard-reference; confidence: unverified*

- IAS 36, paras 6, 59, 117-123, 124: <https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/>

## IAS 37: Provisions, contingent liabilities and contingent assets
A provision is recognised when there is a present legal or constructive obligation from a past event, an outflow of resources is probable (more likely than not) and a reliable estimate can be made (all three together; a present obligation means legal or constructive from a past event), measured at the best estimate and discounted when material. Contingent liabilities, meaning possible obligations or probable ones that cannot be measured reliably, are only disclosed and not booked. Contingent assets are not recognised until virtually certain. Restructuring and onerous contract rules limit when charges can be taken.

- **Scope:** Provisions, contingent liabilities and contingent assets, except those covered by other standards (revenue contracts, income tax, leases, employee benefits).
- **Recognition:** Recognise a provision when there is a present obligation (legal or constructive) from a past event, an outflow of resources is probable and a reliable estimate can be made; contingent liabilities are disclosed only; contingent assets recognised only when virtually certain.
- **Initial measurement:** Best estimate of the expenditure required to settle, discounted when the time value of money is material, with risks reflected in cash flows or the rate.
- **Subsequent measurement:** Review each period; unwind discount as finance cost; use provisions only for the purpose for which they were set up.
- **Presentation:** Provisions as current or non-current liabilities; charge in operating costs or other expense.
- **Key disclosures:** Movement by class, timing and uncertainty, major assumptions, contingent liabilities with estimates, and reimbursement assets.
- **Key judgements:** Probability of outflow, constructive obligations (restructuring), onerous contracts (unavoidable costs), litigation outcomes and decommissioning cost estimates.
- **Recent amendments:** Onerous contracts: cost of fulfilling a contract (2020, effective 2022); climate-related commitments illustrated in IFRIC discussions.
- **Analyst effect:** Large provision movements swing earnings; treat litigation, decommissioning and warranty provisions with expected cash outflows as debt-like and read contingent liability notes.

**Analyst impact:** Big provision movements affect earnings quality; treat litigation and decommissioning provisions as debt-like if cash will go out.

**Recipe:** `eosb_as_debt_like`

*Basis: standard-reference; confidence: unverified*

- IAS 37, paras 14, 36, 45, 72, 86: <https://www.ifrs.org/issued-standards/list-of-standards/ias-37-provisions-contingent-liabilities-and-contingent-assets/>

## IAS 38: Intangible assets
Intangible assets are recognised at cost if identifiable, controlled and expected to give future benefit. Research expenditure is always expensed. Development expenditure is capitalised only when technical feasibility, intention and ability to complete and use or sell, probable future economic benefits, adequate resources and reliable measurement are all demonstrated; otherwise it is expensed. Internally generated brands, customer lists and goodwill are not capitalised. Finite-life intangibles are amortised; indefinite-life ones are tested annually. US GAAP generally expenses development costs.

- **Scope:** Intangible assets that are not within another standard; includes software, licences, brands and development costs.
- **Recognition:** Recognise when identifiable, controlled, probable benefits and reliable cost; research expensed; development capitalised when technical feasibility, intention, ability to use or sell, probable benefits, resources and reliable measurement are shown; internally generated brands, goodwill and customer lists are not recognised.
- **Initial measurement:** Cost; separately acquired at purchase price, business-combination intangibles at fair value.
- **Subsequent measurement:** Cost or revaluation model (active market only); finite lives amortised, indefinite lives tested annually; impairment under IAS 36.
- **Presentation:** Intangibles separate from goodwill; amortisation in operating costs.
- **Key disclosures:** Useful lives, amortisation, reconciliations, research and development expensed, assets with indefinite lives.
- **Key judgements:** Feasibility and probable benefit for development, software as intangible versus part of hardware (IAS 16), cloud computing arrangements (service contracts versus assets, per IFRIC agenda decisions), and useful lives.
- **Recent amendments:** IFRIC cloud computing configuration and customisation costs (2021); IASB project on intangible assets pending.
- **Analyst effect:** Capitalised development lifts EBIT and operating cash flow and shifts spending to investing; expense it to compare with US GAAP peers.

**Analyst impact:** Capitalising lifts operating profit and cash flow from operations, and depresses investing cash flow; compare to expensing peers.

**Recipe:** `dev_cost_expense`

*Basis: standard-reference; confidence: unverified*

- IAS 38, paras 54, 57, 74-75, 107: <https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/>

## IAS 40: Investment property
Investment property is property held to earn rentals or for capital appreciation, not for own use or sale in the ordinary course. After initial measurement at cost, the entity chooses for all its investment property either the cost model (depreciated, with fair value disclosed) or the fair value model, where changes in fair value go to profit or loss each period and no depreciation is taken. Indian Ind AS allows the cost model only.

- **Scope:** Property held to earn rentals or for capital appreciation, including property under construction for that use; excludes owner-occupied and inventory property.
- **Recognition:** Recognise when probable benefits and reliable cost; transfers to or from investment property require a change in use supported by evidence (the change-in-use trigger).
- **Initial measurement:** Cost, including transaction costs.
- **Subsequent measurement:** Choose cost model (with fair value disclosed) or fair value model for all investment property; fair value changes in profit or loss and no depreciation.
- **Presentation:** Fair value gains in profit or loss (often outside operating profit); rental income in revenue or other income.
- **Key disclosures:** Method, valuation inputs and valuer, reconciliation, rental income and direct operating expenses, restrictions and commitments.
- **Key judgements:** Classification of mixed-use property, change in use, valuation yields and rents, and property under construction at fair value when reliably measurable.
- **Recent amendments:** Transfers of investment property (2016, clarified evidence of change in use); IFRS 16 sub-leases interaction.
- **Analyst effect:** Fair value gains are unrealised; strip them from earnings and use adjusted EBITDA from rental income; Ind AS permits cost only.

**Analyst impact:** Fair value gains are unrealised; strip them from earnings when comparing real estate groups.

**Recipe:** `revaluation_reverse`

*Basis: standard-reference; confidence: unverified*

- IAS 40, paras 30-33, 75-79: <https://www.ifrs.org/issued-standards/list-of-standards/ias-40-investment-property/>

## IFRS 8: Operating segments
Listed entities report operating segments using the management approach: segments are the components the chief operating decision maker (CODM) reviews to allocate resources and assess performance, with the profit measure used internally and reconciliations to group totals. A segment is reportable if it passes any 10 percent quantitative threshold (revenue including intersegment, absolute profit or loss, or assets); reportable segments must cover at least 75 percent of external revenue, otherwise more segments are added. Entity-wide disclosures cover products, geography and major customers over 10 percent of revenue.

- **Scope:** Entities with publicly traded securities (or filing to list); disclosure of operating segments, products, geography and major customers.
- **Recognition:** Not a recognition standard: segments follow the management approach, as the chief operating decision maker reviews them.
- **Initial measurement:** Segment profit and assets reported on the measure used internally, not necessarily IFRS.
- **Subsequent measurement:** Not applicable; reconcile totals to group revenue, profit, assets and liabilities.
- **Presentation:** A note: segment revenue (external and intersegment), profit measure, assets if reported internally, reconciliations.
- **Key disclosures:** Factors identifying segments, measurement basis, reconciliations, revenue by product and country, customers above 10 percent of revenue.
- **Key judgements:** Identifying the CODM and aggregation of segments, applying the 10 percent thresholds and 75 percent external revenue test, and allocations of central costs.
- **Recent amendments:** No major amendment in 2019-2026; IFRS 18 from 2027 aligns operating profit measures and changes how segment profit reconciles.
- **Analyst effect:** Segment EBITDA may differ from group EBIT; use the reconciliation, watch unallocated costs and intersegment eliminations, and rebuild like-for-like margins.

**Analyst impact:** Segment profit measures can differ from group EBIT; tie segment totals to the income statement and note unallocated items.

*Basis: standard-reference; confidence: unverified*

- IFRS 8, paras 5, 11-13, 23, 28, 32-34: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-8-operating-segments/>

## IFRS 1: First-time adoption of IFRS
The first financial statements that state explicit and unreserved IFRS compliance, plus interim reports inside that year. Prepare an opening IFRS statement of financial position at the transition date by applying the standards in force at the first reporting date retrospectively, then adjust everything recognised under old GAAP.

- **Scope:** The first financial statements that state explicit and unreserved IFRS compliance, plus interim reports inside that year.
- **Recognition:** Prepare an opening IFRS statement of financial position at the transition date by applying the standards in force at the first reporting date retrospectively, then adjust everything recognised under old GAAP.
- **Initial measurement:** Opening balances use IFRS carrying amounts; optional exemptions allow deemed cost (fair value or revalued amount) for PPE, investment property and intangibles.
- **Subsequent measurement:** After transition the entity follows each IFRS normally; the differences are reconciled once through equity.
- **Presentation:** At least one year of comparatives and an opening position; reconciliations of equity and total comprehensive income from previous GAAP.
- **Key disclosures:** Reconciliations from previous GAAP to IFRS for equity at the transition date and the last old-GAAP year end, and the profit or loss for that year; exemptions used.
- **Key judgements:** Which optional exemptions to take (business combinations before transition, deemed cost, cumulative translation reserve reset to zero, leases) and whether mandatory exceptions such as estimates apply.
- **Recent amendments:** Amendments for subsidiaries that become first-time adopters later and for hyperinflation exit (2010); annual improvements on hedge accounting at transition (2022). IFRS 18 consequential edits from 2027.
- **Analyst effect:** Transition year equity, margins and leverage jump with no operating cause (leases on balance sheet, deemed cost, reserve reset); do not trend across the transition without the reconciliation.

**Analyst impact:** Transition year equity, margins and leverage jump with no operating cause (leases on balance sheet, deemed cost, reserve reset); do not trend across the transition without the reconciliation.

*Basis: standard-reference; confidence: unverified*

- IFRS 1, paras 6-8, 13-19, 21-24: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-1-first-time-adoption-of-international-financial-reporting-standards/>

## IFRS 2: Share-based payment
Transactions paid for in shares, options or cash linked to share price, including employee schemes and goods or services from others. Expense over the vesting period as services are received, credited to equity for equity-settled awards or to a liability for cash-settled ones.

- **Scope:** Transactions paid for in shares, options or cash linked to share price, including employee schemes and goods or services from others.
- **Recognition:** Expense over the vesting period as services are received, credited to equity for equity-settled awards or to a liability for cash-settled ones.
- **Initial measurement:** Equity-settled awards at grant-date fair value of the instruments (option pricing model), not revalued; cash-settled at the fair value of the liability.
- **Subsequent measurement:** Equity-settled: true up the number expected to vest for service and non-market conditions only; cash-settled: remeasure to fair value each period through profit or loss.
- **Presentation:** Employee cost within staff expense (function or nature); credit to a share-based payment reserve or a liability.
- **Key disclosures:** Nature of plans, number and weighted exercise prices of options, valuation inputs, and the total expense.
- **Key judgements:** Model inputs (volatility, expected term), vesting and market conditions, modification and cancellation accounting, and cash-settled versus equity-settled classification (net settlement features).
- **Recent amendments:** 2016 amendments on cash-settled awards with vesting conditions, net-settled withholding tax and modifications from cash to equity settlement.
- **Analyst effect:** A non-cash charge inside EBIT; adjusted EBITDA often adds it back but dilution through diluted EPS and cash-settled liabilities (debt-like) still cost holders value.

**Analyst impact:** A non-cash charge inside EBIT; adjusted EBITDA often adds it back but dilution through diluted EPS and cash-settled liabilities (debt-like) still cost holders value.

*Basis: standard-reference; confidence: unverified*

- IFRS 2, paras 7-8, 10-13, 19-21, 30: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-2-share-based-payment/>

## IFRS 4: Insurance contracts (superseded)
Insurance contracts under the interim standard; replaced by IFRS 17 for periods from 2023 (with a temporary deferral for some insurers until IFRS 9 alignment). Permitted continuing local GAAP practices for insurance liabilities with a liability adequacy test.

- **Scope:** Insurance contracts under the interim standard; replaced by IFRS 17 for periods from 2023 (with a temporary deferral for some insurers until IFRS 9 alignment).
- **Recognition:** Permitted continuing local GAAP practices for insurance liabilities with a liability adequacy test.
- **Initial measurement:** Insurer's previous GAAP basis.
- **Subsequent measurement:** Previous GAAP with limited improvements; shadow accounting allowed.
- **Presentation:** Insurance liabilities as presented under local rules.
- **Key disclosures:** Amounts and risks from insurance contracts, sensitivity and concentration.
- **Key judgements:** Classifying insurance versus investment contracts and the temporary exemption from IFRS 9.
- **Recent amendments:** Deferral of IFRS 9 for insurers (2016) ended with IFRS 17 adoption in 2023.
- **Analyst effect:** Historical insurer comparability is poor; treat pre-2023 figures as a different basis from IFRS 17.

**Analyst impact:** Historical insurer comparability is poor; treat pre-2023 figures as a different basis from IFRS 17.

*Basis: standard-reference; confidence: unverified*

- IFRS 4, Replaced by IFRS 17 from 1 January 2023: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-4-insurance-contracts/>

## IFRS 5: Non-current assets held for sale and discontinued operations
Non-current assets and disposal groups whose carrying amount will be recovered mainly through sale, and components that are discontinued. Classify as held for sale when the asset is available for immediate sale in present condition, management is committed and the sale is highly probable and expected within a year.

- **Scope:** Non-current assets and disposal groups whose carrying amount will be recovered mainly through sale, and components that are discontinued.
- **Recognition:** Classify as held for sale when the asset is available for immediate sale in present condition, management is committed and the sale is highly probable and expected within a year.
- **Initial measurement:** Lower of carrying amount and fair value less costs to sell; impairment loss if lower.
- **Subsequent measurement:** No depreciation or amortisation while held for sale; gains from later increases recognised only up to prior losses.
- **Presentation:** Assets and liabilities shown separately as current; results of a discontinued operation as one post-tax line with comparatives re-presented.
- **Key disclosures:** Description, facts and circumstances, gain or loss, segment, and cash flows of discontinued operations.
- **Key judgements:** Whether the highly probable and one-year criteria are met (and delays outside control), what qualifies as a major line of business, and fair value less costs to sell.
- **Recent amendments:** Clarifications on plans to sell a controlling interest (2014) and IFRS 18 consequential presentation changes from 2027.
- **Analyst effect:** Moves earnings and EBITDA of discontinued parts below continuing profit, stops depreciation, and splits net debt and cash flow; use continuing figures for run-rate and the held-for-sale balance in the EV bridge.

**Analyst impact:** Moves earnings and EBITDA of discontinued parts below continuing profit, stops depreciation, and splits net debt and cash flow; use continuing figures for run-rate and the held-for-sale balance in the EV bridge.

*Basis: standard-reference; confidence: unverified*

- IFRS 5, paras 6-8, 15, 25, 30-33, 33A: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-5-non-current-assets-held-for-sale-and-discontinued-operations/>

## IFRS 6: Exploration for and evaluation of mineral resources
Costs incurred in searching for mineral, oil and gas resources before technical feasibility is shown. Entities may continue prior policies for exploration and evaluation assets (capitalise or expense) while choosing a consistent policy.

- **Scope:** Costs incurred in searching for mineral, oil and gas resources before technical feasibility is shown.
- **Recognition:** Entities may continue prior policies for exploration and evaluation assets (capitalise or expense) while choosing a consistent policy.
- **Initial measurement:** Cost, with a policy on which expenditures are capitalised as exploration and evaluation assets.
- **Subsequent measurement:** Cost or revaluation; tested for impairment when facts suggest carrying amount may exceed recoverable amount, using a relaxed CGU rule.
- **Presentation:** Classified as tangible or intangible; reclassified out of the exploration category when feasibility is shown.
- **Key disclosures:** Policies, amounts of assets, liabilities, income, expense and cash flows from exploration.
- **Key judgements:** Policy choice between successful efforts and full cost, and impairment indicators such as expired licences.
- **Recent amendments:** None of significance since 2019; IFRS 18 only affects presentation.
- **Analyst effect:** Full-cost capitalisation lifts EBIT and operating cash flow versus expensing; compare miners and oil companies on one policy.

**Analyst impact:** Full-cost capitalisation lifts EBIT and operating cash flow versus expensing; compare miners and oil companies on one policy.

*Basis: standard-reference; confidence: unverified*

- IFRS 6, paras 6-9, 15-18, 20: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-6-exploration-for-and-evaluation-of-mineral-resources/>

## IFRS 7: Financial instruments disclosures
Disclosure of the significance of financial instruments and the nature and extent of credit, liquidity and market risks. A disclosure standard; recognition and measurement sit in IFRS 9 and IAS 32.

- **Scope:** Disclosure of the significance of financial instruments and the nature and extent of credit, liquidity and market risks.
- **Recognition:** A disclosure standard; recognition and measurement sit in IFRS 9 and IAS 32.
- **Initial measurement:** Not applicable (disclosure).
- **Subsequent measurement:** Fair value hierarchy information for items at fair value.
- **Presentation:** Classification tables by category, offsetting information, and risk sections in the notes.
- **Key disclosures:** Carrying amounts by IFRS 9 category, ECL allowance reconciliation, credit risk exposure, liquidity maturity tables, market risk sensitivity, hedging effects, supplier finance arrangements.
- **Key judgements:** Level 3 inputs, how credit risk concentrations and significant increases in credit risk are described, and what counts as a supplier finance arrangement.
- **Recent amendments:** Supplier finance arrangements disclosures with IAS 7 (2023, effective 2024); 2024 amendments on classification and measurement of financial instruments (effective 2026) add disclosures for contingent features and equity instruments at FVOCI.
- **Analyst effect:** Use the maturity table for debt schedules, the supplier finance note to adjust working capital and net debt, and the ECL reconciliation for credit-cost forecasts.

**Analyst impact:** Use the maturity table for debt schedules, the supplier finance note to adjust working capital and net debt, and the ECL reconciliation for credit-cost forecasts.

*Basis: standard-reference; confidence: unverified*

- IFRS 7, paras 7-8, 31-42, 44F-44H: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-7-financial-instruments-disclosures/>

## IFRS 13: Fair value measurement
How to measure fair value when another IFRS requires or permits it, with exceptions (share-based payments, leases, net realisable value). A measurement framework only.

- **Scope:** How to measure fair value when another IFRS requires or permits it, with exceptions (share-based payments, leases, net realisable value).
- **Recognition:** A measurement framework only.
- **Initial measurement:** Exit price in an orderly transaction between market participants at the measurement date, in the principal or most advantageous market, using the highest and best use for non-financial assets.
- **Subsequent measurement:** Valuation techniques (market, income, cost) maximising observable inputs: level 1 quoted prices, level 2 observable, level 3 unobservable.
- **Presentation:** Applied in the lines that carry fair value.
- **Key disclosures:** Hierarchy levels, valuation techniques and inputs for level 2 and 3, reconciliations of level 3 movements, sensitivity of recurring level 3 measurements.
- **Key judgements:** Level classification, unobservable inputs such as discount rates and yields, blockage factors, and unit of account.
- **Recent amendments:** No substantial amendment in 2019-2026; the 2024 IFRS 9 and IFRS 7 amendments add fair value related disclosures for equity instruments.
- **Analyst effect:** Level 3 gains (investment property, financial assets) are subjective; haircut them in comparable earnings and cap rates for property groups.

**Analyst impact:** Level 3 gains (investment property, financial assets) are subjective; haircut them in comparable earnings and cap rates for property groups.

*Basis: standard-reference; confidence: unverified*

- IFRS 13, paras 9, 22-27, 61-66, 72-90, 93: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-13-fair-value-measurement/>

## IFRS 14: Regulatory deferral accounts
Optional interim standard for first-time adopters that kept regulatory deferral balances under previous GAAP; superseded in practice while the IASB completes its rate-regulated activities project. Continue previous GAAP recognition of regulatory deferral account balances.

- **Scope:** Optional interim standard for first-time adopters that kept regulatory deferral balances under previous GAAP; superseded in practice while the IASB completes its rate-regulated activities project.
- **Recognition:** Continue previous GAAP recognition of regulatory deferral account balances.
- **Initial measurement:** Previous GAAP basis.
- **Subsequent measurement:** Previous GAAP basis, with impairment per previous practice.
- **Presentation:** Separate line items for regulatory deferral balances and movements, outside revenue.
- **Key disclosures:** Nature of rate regulation, risks, amounts and reconciliations.
- **Key judgements:** Whether the entity is eligible (first-time adopter with rate-regulated activities) and which balances to carry.
- **Recent amendments:** New rate-regulated activities standard still pending at the IASB; only IFRS 18 consequential changes.
- **Analyst effect:** Regulatory balances act like deferred revenue or receivables; adjust leverage and earnings for utilities that use or do not use the option.

**Analyst impact:** Regulatory balances act like deferred revenue or receivables; adjust leverage and earnings for utilities that use or do not use the option.

*Basis: standard-reference; confidence: unverified*

- IFRS 14, paras 5-6, 11-13, 20-26: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-14-regulatory-deferral-accounts/>

## IFRS 17: Insurance contracts
Insurance contracts issued, reinsurance held and investment contracts with discretionary participation features. Group contracts by portfolio, profitability and annual cohort; recognise from the start of coverage, with onerous contracts losses immediately.

- **Scope:** Insurance contracts issued, reinsurance held and investment contracts with discretionary participation features.
- **Recognition:** Group contracts by portfolio, profitability and annual cohort; recognise from the start of coverage, with onerous contracts losses immediately.
- **Initial measurement:** General model: fulfilment cash flows (probability-weighted cash flows, discounting, risk adjustment) plus the contractual service margin that defers unearned profit; premium allocation approach for short contracts; variable fee approach for participating contracts.
- **Subsequent measurement:** The contractual service margin is released over coverage; insurance finance income or expense through profit or loss or OCI by policy choice; remeasure estimates each period.
- **Presentation:** Insurance revenue, insurance service expense, and insurance finance income or expense; groups of contracts in assets or liabilities.
- **Key disclosures:** Reconciliations of liabilities, contractual service margin, discount rates, confidence level for risk adjustment, transition approach, sensitivity.
- **Key judgements:** Discount rate curves, risk adjustment, coverage units, boundary of contracts, grouping and the OCI option.
- **Recent amendments:** 2020 amendments (effective 2023) and a 2021 comparative-information option for the IFRS 9 overlap.
- **Analyst effect:** Revenue is no longer gross premium; value insurers on contractual service margin and combined ratio from insurance service result, and watch investment result versus finance expense.

**Analyst impact:** Revenue is no longer gross premium; value insurers on contractual service margin and combined ratio from insurance service result, and watch investment result versus finance expense.

*Basis: standard-reference; confidence: unverified*

- IFRS 17, paras 32-52, 53-59, 99-105, B96-B119: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-17-insurance-contracts/>

## IAS 8: Accounting policies, changes in accounting estimates and errors
Selecting and changing accounting policies, accounting for changes in estimates and correcting prior period errors. A policy change is applied retrospectively unless impracticable; an estimate change is prospective; material prior-period errors are restated.

- **Scope:** Selecting and changing accounting policies, accounting for changes in estimates and correcting prior period errors.
- **Recognition:** A policy change is applied retrospectively unless impracticable; an estimate change is prospective; material prior-period errors are restated.
- **Initial measurement:** Apply IFRS; when silent, develop policies from similar standards and the Conceptual Framework.
- **Subsequent measurement:** Comparatives and opening equity restated for policy changes and errors.
- **Presentation:** Third balance sheet where restatement is material; effect of restatement per line item.
- **Key disclosures:** Nature and amount of policy changes, estimate changes with material effects, and prior period error corrections.
- **Key judgements:** Distinguishing a change in estimate from a change in policy, materiality of errors, and the hierarchy when no IFRS applies.
- **Recent amendments:** Definition of accounting estimates (2021, effective 2023); Conceptual Framework references (2018).
- **Analyst effect:** Restated comparatives break trends; read the restatement note before using prior-year figures, and treat repeated restatements as an audit quality flag.

**Analyst impact:** Restated comparatives break trends; read the restatement note before using prior-year figures, and treat repeated restatements as an audit quality flag.

*Basis: standard-reference; confidence: unverified*

- IAS 8, paras 10-12, 14-19, 32-40, 41-49: <https://www.ifrs.org/issued-standards/list-of-standards/ias-8-accounting-policies-changes-in-accounting-estimates-and-errors/>

## IAS 10: Events after the reporting period
Events between the reporting date and the date financial statements are authorised for issue. Adjusting events (evidence of conditions existing at the reporting date) are recognised; non-adjusting events are disclosed only; dividends declared after year end are not liabilities.

- **Scope:** Events between the reporting date and the date financial statements are authorised for issue.
- **Recognition:** Adjusting events (evidence of conditions existing at the reporting date) are recognised; non-adjusting events are disclosed only; dividends declared after year end are not liabilities.
- **Initial measurement:** Adjusting events change recognised amounts.
- **Subsequent measurement:** Not applicable.
- **Presentation:** Date of authorisation disclosed; going concern deterioration after year end can change the basis of preparation.
- **Key disclosures:** Nature and estimated financial effect of material non-adjusting events such as acquisitions, major FX moves and dividends proposed.
- **Key judgements:** Whether an event provides evidence of conditions at the reporting date, for example customer insolvency or a post-year-end devaluation (non-adjusting).
- **Recent amendments:** No amendments in 2019-2026.
- **Analyst effect:** A post-year-end devaluation or large acquisition is not in the balance sheet; read the events note and pro forma the debt and earnings.

**Analyst impact:** A post-year-end devaluation or large acquisition is not in the balance sheet; read the events note and pro forma the debt and earnings.

*Basis: standard-reference; confidence: unverified*

- IAS 10, paras 3, 8-11, 14-16, 21: <https://www.ifrs.org/issued-standards/list-of-standards/ias-10-events-after-the-reporting-period/>

## IAS 27: Separate financial statements
Statements presented by a parent or investor in addition to consolidated statements, or where consolidation is not required. Account for investments in subsidiaries, joint ventures and associates at cost, as financial instruments under IFRS 9, or using the equity method.

- **Scope:** Statements presented by a parent or investor in addition to consolidated statements, or where consolidation is not required.
- **Recognition:** Account for investments in subsidiaries, joint ventures and associates at cost, as financial instruments under IFRS 9, or using the equity method.
- **Initial measurement:** Cost or fair value under the chosen policy, applied to each category.
- **Subsequent measurement:** Cost less impairment, fair value, or equity method; dividends recognised in profit or loss when the right to receive arises.
- **Presentation:** Separate statements clearly labelled, with dividend income as the main investment income.
- **Key disclosures:** Reasons for separate statements, list of significant investments and the method used.
- **Key judgements:** Which of the three methods to use (the equity method option was added in 2014) and impairment of the carrying amount.
- **Recent amendments:** Equity method in separate statements (2014, effective 2016); local standards such as Egypt's EAS 17 were revised in 2024.
- **Analyst effect:** Parent-only profit is mostly dividends and says little about group earnings; value from consolidated figures.

**Analyst impact:** Parent-only profit is mostly dividends and says little about group earnings; value from consolidated figures.

**Recipe:** `associates_share_strip`

*Basis: standard-reference; confidence: unverified*

- IAS 27, paras 10-12, 16-17: <https://www.ifrs.org/issued-standards/list-of-standards/ias-27-separate-financial-statements/>

## IAS 32: Financial instruments presentation
Presentation of financial instruments as liabilities or equity, treasury shares, compound instruments and offsetting. Classify an instrument as a liability when the issuer has a contractual obligation to deliver cash or another financial asset (or settle in a variable number of its own shares); otherwise equity.

- **Scope:** Presentation of financial instruments as liabilities or equity, treasury shares, compound instruments and offsetting.
- **Recognition:** Classify an instrument as a liability when the issuer has a contractual obligation to deliver cash or another financial asset (or settle in a variable number of its own shares); otherwise equity.
- **Initial measurement:** Compound instruments split into liability (fair value of equivalent debt) and equity (residual).
- **Subsequent measurement:** Liability component at amortised cost; equity not remeasured; treasury shares deducted from equity.
- **Presentation:** Offset only with a legally enforceable right and intention to settle net; interest and dividends follow the classification.
- **Key disclosures:** Through IFRS 7: terms, offsetting, and puttable instruments.
- **Key judgements:** Puttable and perpetual instruments, convertibles with foreign currency features and derivative settlement choices, and the fixed-for-fixed test.
- **Recent amendments:** Classification of liabilities as current or non-current (IAS 1) interacts; 2024 IFRS 9 and 7 amendments; the IASB project on financial instruments with characteristics of equity is pending.
- **Analyst effect:** Hybrid and preferred instruments shift between debt and equity and so alter leverage and EPS; check perpetual notes and put options on non-controlling interests.

**Analyst impact:** Hybrid and preferred instruments shift between debt and equity and so alter leverage and EPS; check perpetual notes and put options on non-controlling interests.

*Basis: standard-reference; confidence: unverified*

- IAS 32, paras 11, 16-18, 25-27, 33, 42: <https://www.ifrs.org/issued-standards/list-of-standards/ias-32-financial-instruments-presentation/>

## IAS 34: Interim financial reporting
Condensed interim reports when required or chosen. Same policies as annual statements applied to year-to-date, with each interim period treated as a discrete part of the year.

- **Scope:** Condensed interim reports when required or chosen.
- **Recognition:** Same policies as annual statements applied to year-to-date, with each interim period treated as a discrete part of the year.
- **Initial measurement:** Same recognition and measurement; costs incurred unevenly are not deferred; tax uses the estimated average annual effective rate.
- **Subsequent measurement:** Estimate changes and restatements handled prospectively or as annual rules.
- **Presentation:** Condensed statements with major headings and subtotals, selected explanatory notes, comparative periods (prior year-to-date and last year end balance sheet).
- **Key disclosures:** Significant events, changes in policies, seasonality, segment and fair value information, contingent liabilities, and dividends.
- **Key judgements:** Seasonality and estimating annual tax rate, and impairment testing at interim dates.
- **Recent amendments:** Disclosure of information elsewhere in the interim report (2018); IFRS 18 aligns presentation.
- **Analyst effect:** Quarterly data is condensed and unaudited; seasonal businesses need trailing twelve-month figures, and tax rates smooth through the year.

**Analyst impact:** Quarterly data is condensed and unaudited; seasonal businesses need trailing twelve-month figures, and tax rates smooth through the year.

*Basis: standard-reference; confidence: unverified*

- IAS 34, paras 5-8, 16A, 28-30, 43: <https://www.ifrs.org/issued-standards/list-of-standards/ias-34-interim-financial-reporting/>

## IAS 41: Agriculture
Biological assets and agricultural produce at the point of harvest; bearer plants moved to IAS 16. Recognise a biological asset when controlled, probable benefits and reliable measurement.

- **Scope:** Biological assets and agricultural produce at the point of harvest; bearer plants moved to IAS 16.
- **Recognition:** Recognise a biological asset when controlled, probable benefits and reliable measurement.
- **Initial measurement:** Fair value less costs to sell; produce at fair value at harvest becomes inventory under IAS 2.
- **Subsequent measurement:** Remeasure biological assets to fair value less costs to sell each period with changes in profit or loss; cost used only when fair value is clearly unreliable.
- **Presentation:** Biological assets separately; fair value changes disclosed separately in the income statement.
- **Key disclosures:** Reconciliation of carrying amount, description of groups, valuation methods and assumptions, restrictions and commitments.
- **Key judgements:** Level 3 valuation inputs, discount rates, and the split between bearer plants and the fruit.
- **Recent amendments:** Bearer plants moved to IAS 16 (2014, effective 2016); removal of tax cash flows from fair value (2020 annual improvements).
- **Analyst effect:** Earnings include unrealised fair value gains on herds and crops; strip them to find cash-based profit in agriculture and dairy.

**Analyst impact:** Earnings include unrealised fair value gains on herds and crops; strip them to find cash-based profit in agriculture and dairy.

*Basis: standard-reference; confidence: unverified*

- IAS 41, paras 10-12, 26, 30, 43-46: <https://www.ifrs.org/issued-standards/list-of-standards/ias-41-agriculture/>

## IFRIC 1: Changes in existing decommissioning, restoration and similar liabilities
Changes in the measurement of decommissioning, restoration or similar liabilities recognised under IAS 37 and included in asset cost. Adjust the related asset when the estimate of outflows, timing or the discount rate changes.

- **Scope:** Changes in the measurement of decommissioning, restoration or similar liabilities recognised under IAS 37 and included in asset cost.
- **Recognition:** Adjust the related asset when the estimate of outflows, timing or the discount rate changes.
- **Initial measurement:** Liability at the present value of expected costs; asset cost includes the same amount.
- **Subsequent measurement:** Change adds to or reduces asset cost (cost model) or revaluation surplus and profit (revaluation model); the asset cannot go below zero, with any excess to profit.
- **Presentation:** Unwinding of discount as finance cost.
- **Key disclosures:** Provision movement and assumptions under IAS 37.
- **Key judgements:** Discount rate selection and timing of abandonment.
- **Recent amendments:** None in 2019-2026.
- **Analyst effect:** A lower discount rate raises liabilities and asset values together; treat decommissioning provisions as debt-like for extractives and utilities.

**Analyst impact:** A lower discount rate raises liabilities and asset values together; treat decommissioning provisions as debt-like for extractives and utilities.

**Recipe:** `eosb_as_debt_like`

*Basis: standard-reference; confidence: unverified*

- IFRIC 1, paras 4-8: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-1-changes-in-existing-decommissioning-restoration-and-similar-liabilities/>

## IFRIC 12: Service concession arrangements
Operators that build, operate and maintain public infrastructure for a grantor with control over services and the residual interest. Operator does not recognise the infrastructure as PPE; it recognises a financial asset, an intangible asset, or both.

- **Scope:** Operators that build, operate and maintain public infrastructure for a grantor with control over services and the residual interest.
- **Recognition:** Operator does not recognise the infrastructure as PPE; it recognises a financial asset, an intangible asset, or both.
- **Initial measurement:** Construction revenue and cost under IFRS 15 at fair value of consideration received or receivable.
- **Subsequent measurement:** Financial asset at amortised cost with interest income; intangible asset amortised over the concession.
- **Presentation:** Construction revenue and costs in profit or loss; concession receivable or intangible in assets.
- **Key disclosures:** Terms of the concession, rights, obligations, and revenue and profit on construction.
- **Key judgements:** Whether the grantor controls the asset, split between the financial and intangible models, and construction margins.
- **Recent amendments:** None of significance in 2019-2026.
- **Analyst effect:** Construction margins can inflate revenue and operating cash flow in build years; cash flow to equity follows the receivable collection.

**Analyst impact:** Construction margins can inflate revenue and operating cash flow in build years; cash flow to equity follows the receivable collection.

*Basis: standard-reference; confidence: unverified*

- IFRIC 12, paras 11-19, 21-27: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-12-service-concession-arrangements/>

## IFRIC 14: IAS 19, the limit on a defined benefit asset, minimum funding requirements and their interaction
How much of a surplus can be recognised as an asset and whether a minimum funding commitment creates a liability. A surplus is recognised only to the extent of an available economic benefit through refunds or reduced future contributions (the asset ceiling); onerous minimum funding adds a liability.

- **Scope:** How much of a surplus can be recognised as an asset and whether a minimum funding commitment creates a liability.
- **Recognition:** A surplus is recognised only to the extent of an available economic benefit through refunds or reduced future contributions (the asset ceiling); onerous minimum funding adds a liability.
- **Initial measurement:** Present value of economic benefits available.
- **Subsequent measurement:** Remeasure each period; changes in the ceiling go to OCI.
- **Presentation:** Net asset or liability after ceiling.
- **Key disclosures:** Effect of the ceiling and minimum funding on the plan, per IAS 19.
- **Key judgements:** Control of a refund or the trustees' power, and the funding schedule.
- **Recent amendments:** 2018 IAS 19 amendment changes how settlements interact; no change in 2019-2026.
- **Analyst effect:** Pension surplus on the balance sheet may be inaccessible; deduct it from enterprise value adjustments.

**Analyst impact:** Pension surplus on the balance sheet may be inaccessible; deduct it from enterprise value adjustments.

**Recipe:** `eosb_as_debt_like`

*Basis: standard-reference; confidence: unverified*

- IFRIC 14, paras 7-11, 23-26: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-14-ias-19-the-limit-on-a-defined-benefit-asset-minimum-funding-requirements-and-their-interaction/>

## IFRIC 16: Hedges of a net investment in a foreign operation
Hedges of the foreign currency exposure on the net assets of a foreign operation. Hedge of the functional currency exposure only (not the presentation currency); derivatives or borrowings can be the instrument.

- **Scope:** Hedges of the foreign currency exposure on the net assets of a foreign operation.
- **Recognition:** Hedge of the functional currency exposure only (not the presentation currency); derivatives or borrowings can be the instrument.
- **Initial measurement:** Effective part of the hedging instrument in OCI with the translation reserve.
- **Subsequent measurement:** Recycle to profit or loss on disposal of the foreign operation; ineffectiveness in profit.
- **Presentation:** Foreign currency translation reserve and the hedge reserve in OCI.
- **Key disclosures:** Hedge documentation and effectiveness under IFRS 7 and 9.
- **Key judgements:** Which entity holds the instrument and the amount of the hedged net investment.
- **Recent amendments:** Replaced the IAS 39 references with IFRS 9 hedge accounting.
- **Analyst effect:** Offsets translation moves in OCI instead of earnings; net debt FX gains and losses are in OCI.

**Analyst impact:** Offsets translation moves in OCI instead of earnings; net debt FX gains and losses are in OCI.

**Recipe:** `fx_translate_period_end_average`

*Basis: standard-reference; confidence: unverified*

- IFRIC 16, paras 10-14, 16-17: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-16-hedges-of-a-net-investment-in-a-foreign-operation/>

## IFRIC 17: Distributions of non-cash assets to owners
Distributions of assets other than cash (and choice of cash or assets) to owners. Recognise a dividend liability when appropriately authorised and no longer at the entity's discretion.

- **Scope:** Distributions of assets other than cash (and choice of cash or assets) to owners.
- **Recognition:** Recognise a dividend liability when appropriately authorised and no longer at the entity's discretion.
- **Initial measurement:** Fair value of the assets to be distributed.
- **Subsequent measurement:** Remeasure the liability through equity until settlement; the difference between the dividend and the carrying amount of the assets goes to profit or loss.
- **Presentation:** Dividend through equity; gain on distribution in profit or loss.
- **Key disclosures:** Carrying amount of the dividend payable and change since.
- **Key judgements:** Date from which approval is no longer at the entity's discretion.
- **Recent amendments:** None in 2019-2026.
- **Analyst effect:** A spin-off or in-kind dividend leaves a fair value gain in profit or loss; exclude it from recurring earnings.

**Analyst impact:** A spin-off or in-kind dividend leaves a fair value gain in profit or loss; exclude it from recurring earnings.

*Basis: standard-reference; confidence: unverified*

- IFRIC 17, paras 10-16: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-17-distributions-of-non-cash-assets-to-owners/>

## IFRIC 19: Extinguishing financial liabilities with equity instruments
A debtor issues its own equity instruments to a creditor to settle a financial liability in full or in part. Equity instruments are consideration paid; the liability is derecognised when extinguished.

- **Scope:** A debtor issues its own equity instruments to a creditor to settle a financial liability in full or in part.
- **Recognition:** Equity instruments are consideration paid; the liability is derecognised when extinguished.
- **Initial measurement:** Equity instruments at fair value (or at the liability's fair value if the equity cannot be measured reliably).
- **Subsequent measurement:** Difference from the carrying amount of the liability goes to profit or loss.
- **Presentation:** Gain or loss separately disclosed.
- **Key disclosures:** Gain or loss on extinguishment.
- **Key judgements:** Fair value of the equity issued and whether the transaction is with a creditor acting as a shareholder.
- **Recent amendments:** None in 2019-2026.
- **Analyst effect:** Debt-for-equity swaps create a non-cash gain in profit; remove it and treat leverage as improved only by the equity issue.

**Analyst impact:** Debt-for-equity swaps create a non-cash gain in profit; remove it and treat leverage as improved only by the equity issue.

*Basis: standard-reference; confidence: unverified*

- IFRIC 19, paras 5-10: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-19-extinguishing-financial-liabilities-with-equity-instruments/>

## IFRIC 21: Levies
Outflows imposed by governments, other than income taxes, fines or IFRS 15 and IAS 12 items. Recognise a liability when the obligating event that triggers payment under the legislation occurs; no constructive obligation arises from economic compulsion.

- **Scope:** Outflows imposed by governments, other than income taxes, fines or IFRS 15 and IAS 12 items.
- **Recognition:** Recognise a liability when the obligating event that triggers payment under the legislation occurs; no constructive obligation arises from economic compulsion.
- **Initial measurement:** Amount of the levy as set by the legislation, recognised progressively if the event occurs over time.
- **Subsequent measurement:** No change; interim reports do not anticipate or defer the levy.
- **Presentation:** Operating expense, not income tax.
- **Key disclosures:** Under IAS 37 for the liability and contingency.
- **Key judgements:** Identifying the obligating event (threshold crossing or activity at a date).
- **Recent amendments:** None in 2019-2026.
- **Analyst effect:** Levies hit profit in a particular quarter; spread over the year for run-rate and treat bank and sector levies as costs, not tax.

**Analyst impact:** Levies hit profit in a particular quarter; spread over the year for run-rate and treat bank and sector levies as costs, not tax.

*Basis: standard-reference; confidence: unverified*

- IFRIC 21, paras 8-14: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-21-levies/>

## IFRIC 22: Foreign currency transactions and advance consideration
Foreign currency transactions where a non-monetary asset or liability (advance or deferred income) is recognised before the related asset, expense or income. The transaction date for the related item is the date the advance non-monetary item was recognised.

- **Scope:** Foreign currency transactions where a non-monetary asset or liability (advance or deferred income) is recognised before the related asset, expense or income.
- **Recognition:** The transaction date for the related item is the date the advance non-monetary item was recognised.
- **Initial measurement:** Use the exchange rate on the date of the advance payment or receipt, for each payment separately.
- **Subsequent measurement:** The non-monetary advance is not retranslated.
- **Presentation:** Related income or expense at the historical advance rate.
- **Key disclosures:** Under IAS 21.
- **Key judgements:** Whether the advance is non-refundable and non-monetary and the date of recognition.
- **Recent amendments:** Effective 2018; no later changes.
- **Analyst effect:** Revenue and cost can reflect historical rates after a devaluation, so margins lag the new exchange rate.

**Analyst impact:** Revenue and cost can reflect historical rates after a devaluation, so margins lag the new exchange rate.

**Recipe:** `fx_translate_period_end_average`

*Basis: standard-reference; confidence: unverified*

- IFRIC 22, paras 8-9: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-22-foreign-currency-transactions-and-advance-consideration/>

## IFRIC 23: Uncertainty over income tax treatments
Uncertain income tax treatments affecting taxable profit, tax bases, losses and credits under IAS 12. Assume the tax authority examines the position with full knowledge; if an authority is probable to accept the treatment, use it; otherwise reflect the uncertainty.

- **Scope:** Uncertain income tax treatments affecting taxable profit, tax bases, losses and credits under IAS 12.
- **Recognition:** Assume the tax authority examines the position with full knowledge; if an authority is probable to accept the treatment, use it; otherwise reflect the uncertainty.
- **Initial measurement:** Most likely amount or expected value, whichever better predicts the resolution.
- **Subsequent measurement:** Reassess when facts change, such as an audit or a ruling.
- **Presentation:** Current or deferred tax asset or liability; separate presentation where relevant.
- **Key disclosures:** Judgements and estimates under IAS 1 and tax contingencies under IAS 12 and IAS 37.
- **Key judgements:** Whether treatments are considered separately or together, the probability that an authority will accept the position, and measurement method.
- **Recent amendments:** Effective 2019 with a modified retrospective transition.
- **Analyst effect:** Tax liabilities from disputes are debt-like; watch settlements that change effective tax rates.

**Analyst impact:** Tax liabilities from disputes are debt-like; watch settlements that change effective tax rates.

**Recipe:** `zakat_as_tax`

*Basis: standard-reference; confidence: unverified*

- IFRIC 23, paras 8-13: <https://www.ifrs.org/issued-standards/list-of-standards/ifric-23-uncertainty-over-income-tax-treatments/>
