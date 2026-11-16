# Differences and analyst adjustment recipes

*Generated from `om/intl/standards/differences.yaml`.*

## leases

### `diff-leases-ifrs16-asc842`
- **Frameworks:** IFRS, USGAAP, SOCPA-IFRS, UAE-IFRS, IndAS
- **Confidence:** verified
- **Summary:** IFRS 16 puts nearly every lease on the balance sheet and splits cost into depreciation and interest, so lease expense leaves operating costs. US GAAP ASC 842 also records a liability and asset for operating leases, but keeps one straight-line lease cost inside operating expenses; only finance leases are split. The same lease therefore gives higher EBITDA under IFRS than under US GAAP.
- **Analyst impact:** EBITDA, operating cash flow and net debt are not comparable between IFRS and US GAAP retailers, airlines and restaurants. Move IFRS companies to a pre-IFRS 16 basis (deduct lease payments from EBITDA) or move US companies to a post-16 basis.
- **Adjustment recipe:** `ifrs16_to_pre16_ebitda`
- **Citations:**
  - IFRS 16, paras 22-26, 47-49: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>
  - ASC 842, Subtopic 842-20 (lessee), 842-20-25: <https://asc.fasb.org/>

### `diff-leases-net-debt`
- **Frameworks:** IFRS, USGAAP, SOCPA-IFRS, UAE-IFRS, EAS
- **Confidence:** verified
- **Summary:** Lease liabilities are debt-like but are reported in different places. IFRS companies show them with borrowings or in their own line; US companies split operating and finance lease liabilities. Whether to add them to net debt depends on whether EBITDA in the same ratio is before or after rent.
- **Analyst impact:** Keep numerator and denominator consistent: post-16 EBITDA with lease-inclusive net debt, or pre-16 EBITDA with lease-exclusive net debt. Mixed bases overstate or understate leverage.
- **Adjustment recipe:** `lease_adjusted_net_debt`
- **Citations:**
  - IFRS 16, paras 47(b), 53(g), 58: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>
  - ASC 842, 842-20-45 (balance sheet presentation): <https://asc.fasb.org/>

### `diff-leases-eas49`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** EAS 49 mirrors IFRS 16 for lessees. Before it took effect, Egyptian companies used the older leasing rules where operating lease rentals were an expense and only finance leases appeared on the balance sheet. Some Egyptian reports will show a transition in the first year of EAS 49 with a modified retrospective effect on retained earnings.
- **Analyst impact:** Before adoption treat operating lease commitments as debt-like using the disclosed future rentals; after adoption use the lease liability line directly. Check the adoption year for a step in EBITDA.
- **Adjustment recipe:** `capitalise_operating_leases`
- **Citations:**
  - EAS 49 Leases, Scope, lessee model and transition (UNVERIFIED paragraph numbers): <https://fra.gov.eg/>
  - IFRS 16, paras C1-C19 (transition): <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

## revenue

### `diff-revenue-ifrs15-asc606-eas48`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IFRS 15 and ASC 606 share the five-step model, so most revenue is recognised alike. Remaining gaps: the collectability test wording, treatment of some licences, impairment reversal on contract costs, and interim disclosure. EAS 48 and Ind AS 115 follow IFRS 15. Under older Egyptian and UK-style rules, revenue recognition followed risk-and-reward and percentage-of-completion methods.
- **Analyst impact:** Revenue growth across the transition year can step; check the transition method and whether comparatives were restated. For gross versus net, rely on the principal-agent note.
- **Adjustment recipe:** `revenue_principal_agent_net`
- **Citations:**
  - IFRS 15, paras 9, 31, B34-B38: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/>
  - ASC 606, Topic 606-10-25, 606-10-55-36 to 55-40: <https://asc.fasb.org/>
  - EAS 48, Revenue from contracts with customers (UNVERIFIED paragraph numbers): <https://fra.gov.eg/>

### `diff-revenue-principal-agent`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS
- **Confidence:** verified
- **Summary:** A company that controls goods or services before transfer reports revenue gross; an agent reports only its fee. Distributors, platforms and travel businesses differ in judgement, so identical business models can show revenue at very different levels while gross profit stays similar.
- **Analyst impact:** Compare margin on a net-revenue or gross-profit basis when peers differ in principal-agent conclusions.
- **Adjustment recipe:** `revenue_principal_agent_net`
- **Citations:**
  - IFRS 15, paras B34-B38: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/>

## inventory

### `diff-inventory-lifo`
- **Frameworks:** IFRS, USGAAP, EAS, FRS102, IndAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IFRS, EAS, FRS 102 and Ind AS ban last-in first-out. US GAAP allows it, and US companies using LIFO in rising prices show lower profit and inventory than FIFO peers. LIFO users disclose a LIFO reserve, the cumulative gap to FIFO.
- **Analyst impact:** Convert LIFO inventory to FIFO by adding the LIFO reserve and adjust cost of sales by the change in reserve before comparing margins or working capital with IFRS peers.
- **Adjustment recipe:** `lifo_to_fifo`
- **Citations:**
  - IAS 2, paras 23-27: <https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/>
  - ASC 330, 330-10-30 (inventory pricing methods): <https://asc.fasb.org/>

## development_costs

### `diff-development-costs`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS
- **Confidence:** verified
- **Summary:** IFRS requires capitalising development costs once defined criteria are met. US GAAP expenses research and development as incurred, with exceptions for certain software costs. FRS 102 lets entities choose to capitalise or expense. Capitalised development appears in intangible assets, with amortisation later.
- **Analyst impact:** Capitalising raises current EBIT and operating cash flow and shifts spending to investing. For comparability, expense the capitalised amount and reverse the related amortisation.
- **Adjustment recipe:** `dev_cost_expense`
- **Citations:**
  - IAS 38, paras 54-57: <https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/>
  - ASC 730, 730-10-25: <https://asc.fasb.org/>
  - FRS 102, Section 18, paras 18.14-18.15: <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>

## revaluation

### `diff-revaluation`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IFRS allows revaluing whole classes of PPE (and intangibles with active markets) to fair value, with the increase held in a revaluation surplus in OCI. US GAAP prohibits upward revaluation. Ind AS allows revaluation of PPE but not fair value for investment property. Egypt removed the option in its 2015 reissue (UNVERIFIED).
- **Analyst impact:** Revalued assets lift equity and depreciation base; reverse the surplus and extra depreciation for return-on-capital comparisons across jurisdictions.
- **Adjustment recipe:** `revaluation_reverse`
- **Citations:**
  - IAS 16, paras 31-42: <https://www.ifrs.org/issued-standards/list-of-standards/ias-16-property-plant-and-equipment/>
  - IAS 40, paras 33-55: <https://www.ifrs.org/issued-standards/list-of-standards/ias-40-investment-property/>
  - Ind AS 40, Cost model only for investment property: <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>

## impairment_reversal

### `diff-impairment-reversal`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS
- **Confidence:** verified
- **Summary:** IFRS lets a company reverse an earlier impairment of PPE, intangibles other than goodwill and investments when the reasons fade, up to the depreciated cost that would have existed. Goodwill impairment is never reversed. US GAAP forbids reversing an impairment of assets held for use.
- **Analyst impact:** Reversals inflate IFRS earnings in recoveries (commodities, shipping). Remove reversals from normalised profit before comparing with US peers.
- **Adjustment recipe:** `impairment_reversal_strip`
- **Citations:**
  - IAS 36, paras 109-125: <https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/>
  - ASC 360, 360-10-35-20 (restoration prohibited): <https://asc.fasb.org/>

## borrowing_costs

### `diff-borrowing-costs`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS
- **Confidence:** verified
- **Summary:** IFRS requires capitalising borrowing costs on qualifying assets, and deducts investment income on funds borrowed specifically. US GAAP also capitalises interest but does not net investment income and uses the weighted average accumulated expenditure method. FRS 102 permits either capitalising or expensing.
- **Analyst impact:** Capitalised interest hides financing cost inside capex. Add it back to interest expense for interest cover and EBIT-to-interest ratios.
- **Adjustment recipe:** `capitalised_interest_expense`
- **Citations:**
  - IAS 23, paras 8-18: <https://www.ifrs.org/issued-standards/list-of-standards/ias-23-borrowing-costs/>
  - ASC 835-20, 835-20-30: <https://asc.fasb.org/>

## associates_jvs

### `diff-associates-jvs`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS, SOCPA-IFRS, UAE-IFRS, FRS102
- **Confidence:** verified
- **Summary:** Both frameworks use the equity method for associates and joint ventures. IFRS requires uniform accounting policies with the investor, forbids proportionate consolidation of joint ventures and treats joint operations line by line. US GAAP allows proportionate consolidation in some industries and the fair value option. The share of results sits in one P&L line, often before tax.
- **Analyst impact:** EBITDA should exclude equity-accounted profit; add the equity investment (or market value) to the EV bridge and consider proportionate debt.
- **Adjustment recipe:** `associates_share_strip`
- **Citations:**
  - IAS 28, paras 10, 35: <https://www.ifrs.org/issued-standards/list-of-standards/ias-28-investments-in-associates-and-joint-ventures/>
  - IFRS 11, paras 14-24: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-11-joint-arrangements/>
  - ASC 323, 323-10-25: <https://asc.fasb.org/>

## hyperinflation

### `diff-hyperinflation-ias29`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS
- **Confidence:** unverified
- **Summary:** IAS 29 requires restating a hyperinflationary entity's statements by a price index and reporting a net monetary gain or loss. US GAAP does not restate; it requires the remeasurement of the foreign subsidiary using the parent's currency as functional currency when cumulative three-year inflation is about 100 percent. Egypt's inflation was high in 2023-2024 but the country was not on the commonly published IAS 29 country list at the time of writing (UNVERIFIED).
- **Analyst impact:** Restate or at least flag results in hyperinflationary economies (Argentina, Turkey, Lebanon, Ethiopia); use constant-currency and avoid mixing indexed and unindexed periods.
- **Adjustment recipe:** `ias29_restate`
- **Citations:**
  - IAS 29, paras 3-8, 11-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-29-financial-reporting-in-hyperinflationary-economies/>
  - ASC 830, 830-10-45-11: <https://asc.fasb.org/>

## fx_translation

### `diff-fx-translation`
- **Frameworks:** IFRS, USGAAP, EAS, FRS102, IndAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** Under IAS 21 and ASC 830, a foreign operation is translated into the reporting currency with the closing rate for the balance sheet and average (or transaction date) rates for the income statement, and the difference goes to OCI as a translation reserve. Using the wrong rate mix distorts margins and ratios.
- **Analyst impact:** Compare companies on the same translation basis. Use period-end rates for balances and period average for flows; keep a constant-currency view for growth.
- **Adjustment recipe:** `fx_translate_period_end_average`
- **Citations:**
  - IAS 21, paras 38-47: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>
  - ASC 830, 830-30-45: <https://asc.fasb.org/>

## fx_devaluation

### `diff-fx-devaluation-ias21`
- **Frameworks:** IFRS, EAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** unverified
- **Summary:** When a currency is devalued, monetary items in foreign currency (debt, payables, cash) are retranslated at the new closing rate and the full difference hits profit or loss under IAS 21. Importers with USD debt show big losses, exporters with USD cash show gains. Egypt floated the pound in November 2016, and had further steps in 2022, early 2023 and March 2024.
- **Analyst impact:** Normalise FX gains and losses out of operating performance, and check the unhedged USD debt that remains. Pre- and post-devaluation periods have different revenue levels in EGP because of repricing.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - IAS 21, paras 23, 28: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>
  - Central Bank of Egypt, Official exchange rate history: <https://www.cbe.org.eg/en/economic-research/statistics/exchange-rates>

### `diff-fx-eas13-special-treatment`
- **Frameworks:** EAS
- **Confidence:** unverified
- **Summary:** Egypt has issued special accounting treatments in annexes to EAS 13 after devaluations. In general these let an entity recognise part of the loss on foreign currency items either in the cost of related assets or as a deferred item amortised over a period instead of full immediate recognition in profit. They apply to specified items and dates and carry disclosure duties. Exact scope, decree numbers and amortisation periods differ by round (2016, 2022, 2023, 2024).
- **Analyst impact:** Reported earnings in EAS reports can be flattered by deferred FX loss. Add the deferred balance back as a charge, reduce asset cost by capitalised FX loss, and compare to IFRS peers.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - EAS 13, Effects of changes in foreign exchange rates, special treatment annexes (UNVERIFIED decree numbers): <https://fra.gov.eg/>

## zakat_tax

### `diff-zakat-vs-income-tax`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** unverified
- **Summary:** In Saudi Arabia zakat is levied on Saudi and GCC owners' share of a company, based largely on a zakat base of equity and long-term funding less certain assets (rate 2.5 percent), while income tax at 20 percent applies to the foreign owners' share. SOCPA's endorsement keeps zakat outside IAS 12, so it is a separate line, not an income tax expense, and there is no deferred tax on zakat. Profit is quoted before zakat and income tax.
- **Analyst impact:** Compare KSA companies with others on a pre-zakat basis, or treat zakat as a tax by adding it to tax expense. Effective tax rates are not comparable, and net income to owners is after zakat.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - ZATCA zakat rules, Implementing regulations on zakat and income tax: <https://zatca.gov.sa/en/Pages/default.aspx>
  - SOCPA IFRS endorsement, Zakat and tax carve-out from IAS 12/IFRIC 21: <https://socpa.org.sa/>

### `diff-uae-corporate-tax`
- **Frameworks:** UAE-IFRS, IFRS
- **Confidence:** unverified
- **Summary:** The UAE introduced federal corporate tax at 9 percent on profit above a threshold for financial years starting on or after 1 June 2023, so IAS 12 current and deferred tax appear for many UAE groups from 2024 reports. Free zone companies may be taxed at 0 percent on qualifying income. Earlier years show almost no income tax, so effective tax rates are not comparable.
- **Analyst impact:** Compare after-tax profit on a normalised tax rate; adjust prior years or use pre-tax profit when mixing periods.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - UAE Corporate Tax Law, Federal Decree-Law on Corporate Tax (UNVERIFIED number): <https://mof.gov.ae/corporate-tax/>
  - IAS 12, paras 47-52: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

### `diff-egypt-income-tax`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** Egyptian companies pay corporate income tax at a standard rate (22.5 percent in recent years) under the income tax law, with special regimes for oil and some sectors. Under EAS 24 deferred tax follows the IAS 12 approach. Tax assessments can be open for several years.
- **Analyst impact:** Check the tax rate reconciliation and open assessments; treat disputed tax as debt-like.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - Egyptian Income Tax Law, Corporate tax rate and regimes (UNVERIFIED article): <https://www.incometax.gov.eg/>
  - IAS 12, paras 79-88: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

## end_of_service

### `diff-eosb-gcc-egypt`
- **Frameworks:** SOCPA-IFRS, UAE-IFRS, EAS, IFRS
- **Confidence:** unverified
- **Summary:** Saudi and UAE labour laws oblige an employer to pay a gratuity on leaving, scaled to salary and years of service (in Saudi Arabia roughly half a month per year for the first five years and a full month after; in the UAE about 21 days per year for the first five years and 30 days after, capped at two years of pay). IAS 19 treats these as defined benefit plans, so companies should have actuarial valuations. Egyptian private employers lean on social insurance, with contractual schemes treated case by case (UNVERIFIED).
- **Analyst impact:** The end-of-service provision is debt-like but rarely in reported net debt. Add it to adjusted debt when material, and watch the discount rate and cash payout in the cash flow.
- **Adjustment recipe:** `eosb_as_debt_like`
- **Citations:**
  - IAS 19, paras 57-62, 67-69: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>
  - Saudi Labour Law, End-of-service award articles (UNVERIFIED article numbers): <https://hrsd.gov.sa/en/knowledge-center/laws-and-regulations>
  - UAE labour law, End-of-service gratuity: <https://u.ae/en/information-and-services/jobs/end-of-service-benefits-gratuity>

## government_grants

### `diff-government-grants`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IAS 20 gives clear rules: recognise grants when conditions are reasonably assured, take them to income to match costs or deduct them from the asset. US GAAP has no general standard; practice often applies IAS 20 by analogy, with new disclosure rules for government assistance. FRS 102 permits a performance or accrual model. The line used (other income, a deduction from cost of sales or from capex) changes margins.
- **Analyst impact:** Gross up grants netted against costs to compare margins, and separate grants from recurring operating profit when subsidies may end.
- **Adjustment recipe:** `gov_grant_gross_up`
- **Citations:**
  - IAS 20, paras 7-12, 24-26: <https://www.ifrs.org/issued-standards/list-of-standards/ias-20-accounting-for-government-grants-and-disclosure-of-government-assistance/>
  - FRS 102, Section 24: <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>

## presentation

### `diff-presentation-by-nature-function`
- **Frameworks:** IFRS, IndAS, EAS, FRS102, USGAAP
- **Confidence:** verified
- **Summary:** IFRS and most local sets let a company choose expenses by function or by nature. Ind AS schedule III forces by nature. Companies using by nature show raw materials, staff cost and depreciation and often no operating profit line. IFRS 18 from 2027 will require an operating profit subtotal for everyone, while US GAAP income from operations is by function and the SEC requires some natural-expense detail.
- **Analyst impact:** Build EBIT as revenue less operating expenses by nature, with flagged basis, and separate other operating income and FX items consistently.
- **Adjustment recipe:** `by_nature_ebit`
- **Citations:**
  - IAS 1, paras 99-105: <https://www.ifrs.org/issued-standards/list-of-standards/ias-1-presentation-of-financial-statements/>
  - IFRS 18, Operating category and subtotals: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-18-presentation-and-disclosure-in-financial-statements/>

### `diff-cash-flow-classification`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS
- **Confidence:** verified
- **Summary:** IFRS lets entities place interest and dividends received or paid in different sections; US GAAP fixes them (interest received and paid and dividends received in operating, dividends paid in financing). Ind AS generally puts interest paid in financing for non-finance entities.
- **Analyst impact:** Align cash flow from operations by moving interest to a single section before comparing free cash flow.
- **Adjustment recipe:** `ifrs16_to_pre16_ebitda`
- **Citations:**
  - IAS 7, paras 31-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/>
  - ASC 230, 230-10-45-16 to 45-17: <https://asc.fasb.org/>

### `diff-ind-as-carveouts`
- **Frameworks:** IndAS, IFRS
- **Confidence:** verified
- **Summary:** Ind AS differs from IFRS in a few places: no fair value model for investment property (Ind AS 40), pooling at carrying values for common-control business combinations (Ind AS 103 Appendix C), a mandatory by-nature layout in Schedule III, and some financial instrument and employee benefit details. The reporting year ends 31 March.
- **Analyst impact:** Calendarise to a common year end; expect no goodwill on group reorganisations; handle by-nature profit.
- **Adjustment recipe:** `by_nature_ebit`
- **Citations:**
  - Ind AS 103, Appendix C (common control): <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>
  - Ind AS 40, Cost model: <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>

### `diff-frs102-vs-ifrs`
- **Frameworks:** FRS102, IFRS
- **Confidence:** verified
- **Summary:** FRS 102 permits policy choices that IFRS removes: expensing development, expensing borrowing costs, a cost option for investment property in some cases, and goodwill amortisation over a limited life. Until 2026 leases of lessees stayed off balance sheet if operating. After the 2024 amendments, revenue and leases follow an IFRS-like approach.
- **Analyst impact:** Compare UK private company accounts with IFRS peers after adding back goodwill amortisation and pre-2026 lease commitments.
- **Adjustment recipe:** `capitalise_operating_leases`
- **Citations:**
  - FRS 102, Sections 18, 19, 20, 23: <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>

## eas_ifrs_mapping

### `diff-eas-ifrs-new-standards`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** The newer Egyptian standards copy IFRS: EAS 47 corresponds to IFRS 9 financial instruments, EAS 48 to IFRS 15 revenue, EAS 49 to IFRS 16 leases. Differences come from effective dates, transition options and special treatments granted by Egyptian regulation. Early adopters and late adopters make years non-comparable inside the same market.
- **Analyst impact:** Map EAS lines to the matching IFRS concepts and flag the adoption year and transition method; do not blend pre- and post-adoption years without restatement.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - EAS 47, 48, 49, Corresponding IFRS 9, 15 and 16 (UNVERIFIED effective dates): <https://fra.gov.eg/>
  - IFRS 9, 15, 16, Standards pages: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/>

### `diff-eas-ifrs-legacy-map`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** Older Egyptian standards line up with IAS: EAS 1 with IAS 1 presentation, EAS 2 with IAS 2 inventories, EAS 4 with IAS 7 cash flows, EAS 10 with IAS 16 PPE, EAS 12 with IAS 23 borrowing costs, EAS 13 with IAS 21 foreign exchange, EAS 22 with IAS 33 earnings per share, EAS 24 with IAS 12 income taxes, EAS 31 with IAS 36 impairment, EAS 38 with IAS 19 employee benefits. Numbers in this list should be checked against the current FRA text before use in a client deliverable.
- **Analyst impact:** Use as a first-pass concept map when reading Egyptian notes; confirm each pairing in the current standards text and flag where Egyptian options differ.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - Egyptian Accounting Standards, Index (UNVERIFIED numbering): <https://fra.gov.eg/>

## credit_losses

### `diff-ecl-ifrs9-eas47-cecl`
- **Frameworks:** IFRS, EAS, USGAAP
- **Confidence:** verified
- **Summary:** IFRS 9 uses three stages of expected credit loss, with lifetime loss on significant credit deterioration. US CECL books lifetime loss at initial recognition for all assets at amortised cost. EAS 47 follows IFRS 9 where adopted; earlier Egyptian rules used incurred loss or regulator-set provisions for banks.
- **Analyst impact:** Compare provisioning on loans and receivables by looking at coverage ratios; do not read a first-year ECL step as underlying deterioration.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - IFRS 9, paras 5.5.1-5.5.5: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/>
  - ASC 326, 326-20: <https://asc.fasb.org/>
