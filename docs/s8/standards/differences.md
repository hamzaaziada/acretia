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
- **Summary:** EAS 49 (lease contracts, issued in 2019 as part of the update that added standards based on IFRS 9, 15 and 16) mirrors IFRS 16 for lessees: the lessee recognises a right-of-use asset and a lease liability at commencement, then depreciates the asset and accrues interest on the liability, as under IFRS 16. Before it, Egyptian companies used the older leasing rules where operating lease rentals were an expense and only finance leases appeared on the balance sheet. Expect a transition-year step in EBITDA, lease liabilities and retained earnings in the first EAS 49 year. The effective date and transition options were adjusted by later decisions and are not confirmed here.
- **Analyst impact:** Before adoption treat operating lease commitments as debt-like using the disclosed future rentals; after adoption use the lease liability line directly and compare EBITDA on a pre-16 basis. Check the adoption year for a step.
- **Adjustment recipe:** `capitalise_operating_leases`
- **Citations:**
  - EAS 49 Lease Contracts, Decisions made in 2019 (list), implementation guide listed: <https://fra.gov.eg/en/?p=13760728>
  - IFRS 16, paras C1-C19 (transition): <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

**Verified facts**
- EAS 49 Lease Contracts was issued in 2019: <https://fra.gov.eg/en/?p=13760728>
- The 2019 EAS update added standards based on IFRS 9, 15 and 16: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Unverified facts**
- EAS 49 effective date, transition method and paragraph numbers

### `diff-leases-indas116`
- **Frameworks:** IndAS, IFRS
- **Confidence:** verified
- **Summary:** Ind AS 116 is close to IFRS 16: lessees put nearly all leases on the balance sheet, depreciate the right-of-use asset and accrue interest on the lease liability, and it applies to annual periods beginning on or after 1 April 2019. Carve-outs and differences are small. Ind AS 116 does not allow the fair value model for a right-of-use asset that meets the investment property definition, and it always classes the interest part of lease payments in financing cash flows. The old Ind AS 17 exemption from straight-lining lessor income for inflation-linked rent was dropped, matching IFRS 16.
- **Analyst impact:** Treat Indian EBITDA as post-16, as for IFRS; convert to pre-16 by deducting lease payments, and remember lease interest is outside operating cash flow. Fiscal years end 31 March, so calendarise before comparing with December reporters.
- **Adjustment recipe:** `ifrs16_to_pre16_ebitda`
- **Citations:**
  - Ind AS 116, Effective date and differences from IFRS 16: <https://alumni.in.kpmg.com/downloads/Publications/Accounting_Publications/firstnotes-leases-standard-ind-as-116-notified-mca.pdf>
  - IFRS 16, paras 22-38, 47-60: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

**Verified facts**
- Effective 1 April 2019; no fair value model for investment-property ROU; lease interest always financing; inflation exemption for lessors removed: <https://alumni.in.kpmg.com/downloads/Publications/Accounting_Publications/firstnotes-leases-standard-ind-as-116-notified-mca.pdf>

### `diff-eas49-ebitda-effect`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** Moving to EAS 49, the lessee records a right-of-use asset and a lease liability, depreciates the asset and accrues interest on the liability. Rent that was an operating expense becomes depreciation and interest, so EBITDA and EBIT rise (EBIT by the interest element only), operating cash flow rises and financing outflows include lease principal. Debt and total assets increase by the lease liability and asset.
- **Analyst impact:** For Egyptian retailers, real estate and logistics firms, build a pre-EAS 49 EBITDA by deducting lease payments (principal and interest), and add lease liabilities to net debt only when EBITDA is on the post-adoption basis.
- **Adjustment recipe:** `ifrs16_to_pre16_ebitda`
- **Citations:**
  - EAS 49 Lease Contracts, Lessee model (same as IFRS 16 paras 22-38): <https://fra.gov.eg/en/?p=13760728>
  - IFRS 16, paras 22-38: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/>

**Unverified facts**
- EAS 49 effective date and transition method by company

## revenue

### `diff-revenue-ifrs15-asc606-eas48`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IFRS 15 and ASC 606 share the five-step model for revenue from contracts with customers (identify the contract, the performance obligations, the transaction price, allocate it, recognise as control passes), so most revenue is recognised alike. Remaining gaps: the collectability test wording, treatment of some licences, impairment reversal on contract costs, and interim disclosure. EAS 48 (Revenue from Contracts with Customers, which replaced the older Egyptian revenue standard) and Ind AS 115 follow IFRS 15 and apply the same five-step model to contracts with customers. Under older Egyptian and UK-style rules, revenue recognition followed risk-and-reward and percentage-of-completion methods.
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
- **Summary:** IFRS, EAS, FRS 102 and Ind AS ban last-in first-out. US GAAP permits it, and US companies using LIFO in rising prices show lower profit and inventory than FIFO peers. LIFO users disclose a LIFO reserve, the cumulative gap to FIFO.
- **Analyst impact:** Convert LIFO inventory to FIFO by adding the LIFO reserve and adjust cost of sales by the change in reserve before comparing margins or working capital with IFRS peers.
- **Adjustment recipe:** `lifo_to_fifo`
- **Citations:**
  - IAS 2, paras 23-27: <https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/>
  - ASC 330, 330-10-30 (inventory pricing methods): <https://asc.fasb.org/>

## development_costs

### `diff-development-costs`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS
- **Confidence:** verified
- **Summary:** IFRS requires capitalising development costs once defined criteria are met. US GAAP generally expenses research and development as incurred, with exceptions for certain software costs. FRS 102 lets entities choose to capitalise or expense. Capitalised development appears in intangible assets, with amortisation later.
- **Analyst impact:** Capitalising raises current EBIT and operating cash flow and shifts spending to investing. For comparability, expense the capitalised amount and reverse the related amortisation.
- **Adjustment recipe:** `dev_cost_expense`
- **Citations:**
  - IAS 38, paras 54-57: <https://www.ifrs.org/issued-standards/list-of-standards/ias-38-intangible-assets/>
  - ASC 730, 730-10-25: <https://asc.fasb.org/>
  - FRS 102, Section 18, paras 18.14-18.15: <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>

## revaluation

### `diff-revaluation`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS, SOCPA-IFRS, UAE-IFRS
- **Confidence:** verified
- **Summary:** IFRS allows revaluing whole classes of PPE (and intangibles with active markets) to fair value, with the increase held in a revaluation surplus in OCI. US GAAP prohibits upward revaluation. Ind AS allows revaluation of PPE but not the fair value model for investment property. Egypt did not permit revaluation of PPE, intangibles or investment property until January 2023. Saudi Arabia kept the cost model for listed companies until fiscal years starting 2022 and allows fair value or revaluation after that.
- **Analyst impact:** Revalued assets lift equity and the depreciation base; reverse the surplus and the extra depreciation for return-on-capital comparisons across jurisdictions, and treat Egypt and Saudi periods before the change as cost-based.
- **Adjustment recipe:** `revaluation_reverse`
- **Citations:**
  - IAS 16, paras 31-42: <https://www.ifrs.org/issued-standards/list-of-standards/ias-16-property-plant-and-equipment/>
  - IAS 40, paras 33-55: <https://www.ifrs.org/issued-standards/list-of-standards/ias-40-investment-property/>
  - Ind AS 40, Cost model only for investment property: <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>
  - IFRS jurisdiction profile: Egypt, Revaluation not permitted under EAS until January 2023: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
  - IFRS jurisdiction profile: Saudi Arabia, Cost model for fiscal years before 2022; fair value or revaluation after: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>

## impairment_reversal

### `diff-impairment-reversal`
- **Frameworks:** IFRS, USGAAP, FRS102, IndAS, EAS
- **Confidence:** verified
- **Summary:** IFRS lets a company reverse an earlier impairment of PPE, intangibles other than goodwill and investments when the reasons fade, up to the depreciated cost that would have existed. Goodwill impairment is never reversed. US GAAP prohibits reversing an impairment of assets held and used; written-down cost becomes the new basis.
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

### `diff-eas17-separate-fs`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** In separate financial statements IAS 27 lets a parent carry subsidiaries, associates and joint ventures at cost, at fair value under IFRS 9, or using the equity method. The IFRS Foundation profile for Egypt (January 2024) says the equity method was not an alternative under EAS in separate statements. Prime Ministerial Decree 636 of 2024 replaced EAS 17 (separate financial statements); secondary summaries say the new text adds the equity method as an option, which has not been confirmed. Egyptian holding companies therefore often show investments at cost in the separate set and only the consolidated set carries equity-accounted results.
- **Analyst impact:** Use consolidated statements for valuation; in the separate set, investment income is dividends, not share of profit. Check which method was used before comparing parent-only profit or equity across years or with IFRS peers.
- **Adjustment recipe:** `associates_share_strip`
- **Citations:**
  - EAS 17 Separate financial statements, Substituted by PM Decree 636 of 2024: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>
  - IFRS jurisdiction profile: Egypt, Separate financial statements and the equity method: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
  - IAS 27, para 10 (cost, IFRS 9 or equity method): <https://www.ifrs.org/issued-standards/list-of-standards/ias-27-separate-financial-statements/>

**Verified facts**
- Equity method not an alternative in separate FS under EAS (profile, Jan 2024): <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
- Decree 636/2024 substituted EAS 17: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>

**Unverified facts**
- Whether the 2024 EAS 17 adds an equity-method option
- Effective date of the 2024 EAS 17

## hyperinflation

### `diff-hyperinflation-ias29`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS
- **Confidence:** verified
- **Summary:** IAS 29 requires restating a hyperinflationary entity's statements by a price index and reporting a net monetary gain or loss. US GAAP does not restate; it requires the remeasurement of the foreign subsidiary using the parent's currency as functional currency when cumulative three-year inflation is about 100 percent. Argentina and Turkey are on the current lists of economies where IAS 29 applies. Egypt is not treated as hyperinflationary at the end of 2025 but sits on a watchlist with Angola, Myanmar, Nigeria and Syria.
- **Analyst impact:** Restate or at least flag results in hyperinflationary economies (Argentina, Turkey and others on the current list); use constant-currency and avoid mixing indexed and unindexed periods. For Egypt keep the status under review rather than assuming IAS 29.
- **Adjustment recipe:** `ias29_restate`
- **Citations:**
  - IAS 29, paras 3-8, 11-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-29-financial-reporting-in-hyperinflationary-economies/>
  - ASC 830, 830-10-45-11: <https://asc.fasb.org/>
  - BDO IFRB 2026/07, Year-end hyperinflationary economies update (Egypt on watchlist): <https://www.bdo.global/en-gb/insights/ifrs-and-corporate-reporting/2026/ifrb-2026-07-year-end-hyperinflationary-economies-update>

**Verified facts**
- Egypt not hyperinflationary at 31 Dec 2025; on watchlist with Angola, Myanmar, Nigeria, Syria; Argentina and Turkey on the IAS 29 list: <https://www.bdo.global/en-gb/insights/ifrs-and-corporate-reporting/2026/ifrb-2026-07-year-end-hyperinflationary-economies-update>

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
- **Summary:** When a currency is devalued, monetary items in foreign currency (debt, payables, cash) are retranslated at the new closing rate and the full difference hits profit or loss under IAS 21. Importers with USD debt show big losses, exporters with USD cash show gains. Egypt had devaluations in 2016 and 2022 (recognised in the IFRS Foundation jurisdiction profile). On 6 March 2024 the central bank moved to a flexible, market-determined exchange rate and raised rates by 600 basis points: the official rate, held near 30.9 per USD for more than a year, jumped to about 50 (an intraday record of about 50.6) within a day. Revenue in local currency also steps up as prices are reset, so a single year mixes a one-off translation loss with a changed operating base. In reporting, USD monetary items carried at about 30.9 at the 2023 year end are retranslated at the new rate in the first 2024 quarter, so the loss lands in Q1 2024 results (EAS 13, replaced by PM Decree 636 of 2024, takes it to profit or loss), unless an entity still applies a deferral allowed by the earlier special treatment.
- **Analyst impact:** Strip devaluation FX losses out of recurring EBITDA and earnings. Take the FX gain or loss line (and any FX embedded in finance costs or cost of sales) out of operating profit, tax-effect it, and show adjusted net income beside reported. Where an entity capitalised or deferred FX loss under EAS 13 special treatment, add the deferred charge back so the period carries its economic cost. Treat the March 2024 retranslation as a one-off in the first quarter of 2024 and do not extrapolate it or the later EGP-denominated revenue step; compare 2023 and 2024 on a USD or constant-rate basis. Then check the unhedged USD debt still outstanding, since the next devaluation repeats the effect.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - IAS 21, paras 23, 28: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>
  - IFRS jurisdiction profile: Egypt, Foreign currency translation differences: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
  - Central Bank of Egypt, Official exchange rate history: <https://www.cbe.org.eg/en/economic-research/statistics/exchange-rates>
  - Kuwait Times (Reuters report), 6 March 2024 float: <https://kuwaittimes.com/article/11794/business/egypt-pound-loses-over-third-of-value-as-bank-signals-float>

**Verified facts**
- Egypt applied special translation treatment after the 2016 and 2022 devaluations: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
- 6 March 2024: CBE moved to market-determined rate; official rate about 30.9 per USD for over a year before, record low about 50.6: <https://kuwaittimes.com/article/11794/business/egypt-pound-loses-over-third-of-value-as-bank-signals-float>
- 6 March 2024: policy rates raised 600 basis points; pound about 52 at its weakest official level that afternoon: <https://thenationalnews.com/business/economy/2024/03/06/egypt-imf-currency-egyptian-pound-record-low>

**Unverified facts**
- The January 2023 devaluation step
- Post-float rate path after 6 March 2024 (about 47 to 50 range in later trading)
- How the 2024 EAS 13 treats FX differences in detail

### `diff-fx-eas13-special-treatment`
- **Frameworks:** EAS
- **Confidence:** unverified
- **Summary:** Egypt added special accounting treatments for devaluations to EAS 13: an appendix tied to the 2016 liberalisation and later appendices B (Prime Ministerial Decision 1568 of 2022) and C (Prime Ministerial Decision 4706 of 2022), alongside FRA Decision 843 of 2022 as amended by Decision 1378 of 2022. In general they let an entity put part of the loss on foreign currency items into the cost of related assets or defer it, instead of taking it all to profit; the IFRS Foundation profile notes this was a one-time application extended to the end of 2023 and affects depreciation of remeasured assets. A Prime Ministerial decree of 2024 (No. 636) then replaced EAS 13 itself.
- **Analyst impact:** Reported earnings under special treatment can be flattered by deferral. Add the deferred balance back as a charge, remove capitalised FX loss from asset cost and the extra depreciation, and compare to IFRS peers on a normalised basis.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - EAS 13, Appendices A, B, C (special treatment): <https://fra.gov.eg/en/?p=13760728>
  - PM Decree 636 of 2024, Article 1 (replacement of EAS 13, 17, 34): <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>

**Verified facts**
- Decision 843/2022 (amended by 1378/2022), Appendix B PM Decision 1568/2022 and Appendix C PM Decision 4706/2022 exist as listed by FRA: <https://fra.gov.eg/en/?p=13760728>
- PM Decree 636/2024 substituted EAS 13, EAS 17 and EAS 34: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>
- One-time application extended to end of 2023; affects depreciation of remeasured assets: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Unverified facts**
- Exact scope and amortisation periods of each appendix
- Effective dates of the 2023 and 2024 rounds

### `diff-eas-fx-relief-comparatives`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** After the special FX treatment appendices expired at the end of 2023 and EAS 13 was replaced in 2024, comparatives are not like for like: 2022 and 2023 figures may carry capitalised or deferred FX losses (with extra depreciation or amortisation later) while 2024 figures recognise movements in profit or loss under the aligned text. The FX relief is a one-time application, so a company that used it reports lower expenses in the relief years and higher charges in later years.
- **Analyst impact:** Restate comparatives to a single basis: reverse the deferred FX balance and its amortisation, add back FX capitalised into asset cost and the extra depreciation, and show EBITDA and net income before and after relief so that 2022 to 2024 trends are comparable.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - IFRS jurisdiction profile: Egypt, FX translation differences treatment: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
  - PM Decree 636 of 2024, Article 1 (EAS 13 replaced): <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>

**Verified facts**
- One-time FX relief application extended to end of 2023; affects depreciation of remeasured assets: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Unverified facts**
- Detail of which items each appendix covered and exact amortisation periods

## zakat_tax

### `diff-zakat-vs-income-tax`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** verified
- **Summary:** In Saudi Arabia zakat is a 2.5 percent charge on the zakat base (broadly net worth as computed for zakat) and falls on the Saudi and GCC owners' share, while income tax at 20 percent of adjusted profit applies to the share held by non-Saudi, non-GCC owners. Mixed-ownership companies bear both in proportion. SOCPA's position is that zakat sits outside IAS 12, so it is accounted for under its own endorsed requirements and IAS 8 rather than as an IAS 12 income tax, and there is no deferred tax on zakat. A live IFRS 18 debate concerns whether zakat is presented together with income tax or in operating results.
- **Analyst impact:** Compare KSA companies on a pre-zakat and pre-tax basis, or treat zakat as a tax by adding it to tax expense. Effective tax rates are not comparable across ownership structures, and net income to owners is after zakat. Do not leave zakat in operating costs.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - PwC Tax Summaries Saudi Arabia, Zakat 2.5 percent, income tax 20 percent, ownership split: <https://taxsummaries.pwc.com/saudi-arabia/corporate/taxes-on-corporate-income>
  - SOCPA presentation to IFRS ASAF, Zakat outside IAS 12; two taxation systems by ownership: <https://www.ifrs.org/content/dam/ifrs/meetings/2026/march/asaf/ap10-socpa-presentation-zakat.pdf>
  - IFRS jurisdiction profile: Saudi Arabia, Zakat covered by separately endorsed SOCPA requirements: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>

**Verified facts**
- Zakat 2.5 percent on zakat base; income tax 20 percent on non-Saudi/non-GCC share: <https://taxsummaries.pwc.com/saudi-arabia/corporate/taxes-on-corporate-income>
- Zakat applies to Saudi/GCC portion, IAS 12-type tax to non-Saudi portion; no IFRS specific to zakat: <https://www.ifrs.org/content/dam/ifrs/meetings/2026/march/asaf/ap10-socpa-presentation-zakat.pdf>

### `diff-uae-corporate-tax`
- **Frameworks:** UAE-IFRS, IFRS
- **Confidence:** verified
- **Summary:** The UAE corporate tax charges 9 percent on taxable income above AED 375,000 (nothing below it) from the first financial year starting on or after 1 June 2023, so IAS 12 current and deferred tax appear for UAE groups from their 2024 reports. Qualifying free zone income may be taxed at 0 percent. Earlier years show almost no income tax, so effective tax rates are not comparable across the change.
- **Analyst impact:** Compare after-tax profit on a normalised tax rate; use pre-tax profit when mixing periods and expect a one-off deferred tax effect in the transition year.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - UAE Ministry of Finance, Corporate tax rate, threshold (Cabinet Decision 116 of 2022) and effective date: <https://mof.gov.ae/en/news/ministry-of-finance-confirms-applicable-taxable-income-threshold-for-corporate-tax-abu-dhabi-uae/>
  - IAS 12, paras 47-52: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

**Verified facts**
- 9 percent above AED 375,000, from first financial year starting on or after 1 June 2023: <https://mof.gov.ae/en/news/ministry-of-finance-confirms-applicable-taxable-income-threshold-for-corporate-tax-abu-dhabi-uae/>

### `diff-uae-dmtt-pillar-two`
- **Frameworks:** UAE-IFRS, IFRS
- **Confidence:** verified
- **Summary:** For multinational groups with consolidated revenue of EUR 750 million or more in at least two of the last four years, the UAE applies a Domestic Minimum Top-up Tax (Cabinet Decision 142 of 2024) for fiscal years starting on or after 1 January 2025. It tops UAE profit up to a 15 percent minimum effective rate, so the 9 percent headline rate is not the final rate for large groups.
- **Analyst impact:** Model large UAE-based groups at up to 15 percent after tax from 2025 rather than 9 percent, and treat top-up tax as a recurring tax line, not a one-off.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - Cabinet Decision 142 of 2024 (UAE DMTT), Scope, rate and effective date: <https://www.ey.com/en_gl/technical/tax-alerts/uae-issues-domestic-minimum-top-up-tax-legislation>

**Verified facts**
- 15 percent minimum, EUR 750m revenue in two of four years, fiscal years beginning on or after 1 Jan 2025, Cabinet Decision 142 of 2024: <https://www.ey.com/en_gl/technical/tax-alerts/uae-issues-domestic-minimum-top-up-tax-legislation>

### `diff-egypt-income-tax`
- **Frameworks:** EAS, IFRS
- **Confidence:** verified
- **Summary:** Egyptian companies pay corporate income tax at a standard 22.5 percent of net taxable profit. Oil exploration companies face about 40.55 percent, and the Suez Canal Authority, the Egyptian Petroleum Authority and the central bank 40 percent. Deferred tax follows the IAS 12 balance-sheet approach under the Egyptian deferred tax standard. Tax assessments can stay open for several years.
- **Analyst impact:** Check the tax rate reconciliation and open assessments; treat disputed tax as debt-like, and normalise the rate for sector regimes.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - PwC Tax Summaries Egypt, Taxes on corporate income: <https://taxsummaries.pwc.com/egypt/corporate/taxes-on-corporate-income>
  - IAS 12, paras 79-88: <https://www.ifrs.org/issued-standards/list-of-standards/ias-12-income-taxes/>

**Verified facts**
- Standard rate 22.5 percent; oil exploration 40.55 percent; SCA, EGPC and CBE 40 percent: <https://taxsummaries.pwc.com/egypt/corporate/taxes-on-corporate-income>

### `diff-zakat-base-components`
- **Frameworks:** SOCPA-IFRS
- **Confidence:** verified
- **Summary:** Zakat is 2.5 percent of the zakat base for a Hijri year (prorated by days when the fiscal year differs). A company with legal accounts adds property rights and their equivalents (equity, reserves and provisions treated as equity), partners' loans and allocations, the gap between adjusted and book net profit, and liabilities that are effectively long-term funding (non-current debt, end-of-service and leave provisions, deferred tax liability, lease liabilities, negative derivatives). It deducts net fixed assets, intangibles, qualifying investments, materials not for sale, statutory deposits and deferred tax assets, with caps that tie the liabilities added to the assets deducted. A minimum base applies: the base cannot fall below adjusted net profit, and if the result is negative with no adjusted profit there is no zakat base.
- **Analyst impact:** Zakat is driven by balance sheet items, not just profit, so asset-light and highly capitalised companies pay different effective rates; forecast zakat from equity plus long-term funding less fixed assets and investments, with adjusted profit as a floor, and treat it as a tax-like charge below operating profit.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - ZATCA Implementing Regulations for Zakat Collection (1445H, Ministerial Decision 1007, amended by 1248), Articles 15, 23, 26, 27, 29: <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>

**Verified facts**
- Zakat 2.5 percent of the base for the Hijri year, prorated by days (Article 15): <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>
- Added items: property rights, partners' loans, profit difference; liabilities incl. non-current debt, end-of-service and leave provisions, deferred tax liability, lease obligations, negative derivatives (Articles 23, 29): <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>
- Deductions: net fixed assets, intangibles, qualifying investments, non-sale materials, statutory deposits, deferred tax assets (Article 26); minimum base by adjusted net profit (Article 27): <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>

### `diff-uae-ct-year-ends`
- **Frameworks:** UAE-IFRS
- **Confidence:** unverified
- **Summary:** UAE corporate tax applies from the first financial year starting on or after 1 June 2023, so the first taxable period depends on the year end. A calendar-year company starts on 1 January 2024 (no tax in 2023). A company with a 31 May or 30 June year end starts on the first financial year beginning on or after 1 June 2023: 1 June 2023 to 31 May 2024 in one case and 1 July 2023 to 30 June 2024 in the other. The federal authority accepts a first period of six to eighteen months, the 375,000 threshold is not pro-rated, and returns are due nine months after period end.
- **Analyst impact:** Normalise effective tax rates by year end: non-calendar companies show tax a half-year earlier than calendar ones; use pre-tax profit when comparing the transition year and add a one-off deferred tax effect.
- **Adjustment recipe:** `zakat_as_tax`
- **Citations:**
  - UAE Ministry of Finance, Effective date of the corporate tax regime: <https://mof.gov.ae/en/news/ministry-of-finance-confirms-applicable-taxable-income-threshold-for-corporate-tax-abu-dhabi-uae/>
  - UAE Corporate Tax FAQs, Tax period and first period: <https://mof.gov.ae/?p=19308>

**Verified facts**
- Corporate Tax effective for financial years starting on or after 1 June 2023: <https://mof.gov.ae/en/news/ministry-of-finance-confirms-applicable-taxable-income-threshold-for-corporate-tax-abu-dhabi-uae/>

**Unverified facts**
- Worked examples for 31 May and 30 June year ends are inferences from the rule, not read in an official example
- First-period length range and nine-month filing window from secondary sources

## end_of_service

### `diff-eosb-gcc-egypt`
- **Frameworks:** UAE-IFRS, EAS, IFRS
- **Confidence:** unverified
- **Summary:** The UAE labour law obliges private employers to pay a gratuity on leaving, in the order of 21 days of basic pay per year for the first five years and 30 days per year afterwards, capped at about two years of pay (secondary sources only). IAS 19 treats these as defined benefit plans, so companies should have actuarial valuations with remeasurements in OCI. Egyptian private employers lean on social insurance, with contractual schemes treated case by case.
- **Analyst impact:** The end-of-service provision is debt-like but rarely in reported net debt. Add it to adjusted debt when material, and watch the discount rate and cash payout in the cash flow.
- **Adjustment recipe:** `eosb_as_debt_like`
- **Citations:**
  - IAS 19, paras 57-62, 67-69: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>
  - UAE labour law, End-of-service gratuity: <https://u.ae/en/information-and-services/jobs/end-of-service-benefits-gratuity>

**Unverified facts**
- UAE gratuity tiers, cap and decree-law article numbers (no official source read)
- Egypt end-of-service position

### `diff-eosb-ksa`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** verified
- **Summary:** Under the Saudi Labour Law an employer pays an end-of-service award on termination: half a month of the last wage for each of the first five years and a full month for each later year, with part years pro-rated. When the worker resigns the award is reduced: nothing under two years, one third from two to under five years, two thirds from five to under ten, in full after ten. Saudi reports treat the obligation as a defined benefit plan under IAS 19, valued actuarially, with remeasurements in OCI.
- **Analyst impact:** Treat the end-of-service provision as debt-like when material and add it to adjusted net debt; note it grows with headcount and wage inflation and is paid out in cash on exits, so check the movement note for payouts versus current service cost.
- **Adjustment recipe:** `eosb_as_debt_like`
- **Citations:**
  - Saudi Labour Law (HRSD guidance), End-of-service award calculation: <https://www.hrsd.gov.sa/en/knowledge-centre/articles/317-0>
  - IAS 19, paras 57-62, 67-69, 120: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>

**Verified facts**
- Award of half a month per year for the first five years, a month per year after; resignation scaling: <https://www.hrsd.gov.sa/en/knowledge-centre/articles/317-0>

### `diff-eosb-ksa-actuarial-vs-nominal`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** unverified
- **Summary:** The Saudi end-of-service award is a statutory amount based on final wage and years of service (a nominal, accrual-style figure: what would be paid if everyone left at the reporting date). IAS 19 treats it as a defined benefit plan and requires the projected unit credit method: project future salary, attrition and retirement, discount at high-quality bond yields, and put remeasurements in OCI. Smaller reporters sometimes book the nominal amount; listed companies are expected to use an actuarial valuation, and the zakat base adds the provision as a long-term liability.
- **Analyst impact:** The actuarial liability is usually lower than the nominal amount because of attrition and discounting; check which method is used before comparing, and treat the provision as debt-like with the nominal amount as the upper bound.
- **Adjustment recipe:** `eosb_as_debt_like`
- **Citations:**
  - IAS 19, paras 67-69 (projected unit credit), 120: <https://www.ifrs.org/issued-standards/list-of-standards/ias-19-employee-benefits/>
  - ZATCA Implementing Regulations for Zakat Collection, Article 29(1)(b): <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>

**Verified facts**
- Provisions for end-of-service benefits are added to the zakat base as stable debt to non-owners (Article 29): <https://zatca.gov.sa/en/RulesRegulations/Documents/ZAKAT%20COLLECTION.pdf>

**Unverified facts**
- How widespread nominal-method accounting is among listed Saudi companies

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
- **Summary:** IFRS lets entities place interest and dividends received or paid in different sections; US GAAP fixes them (interest received and paid and dividends received in operating, dividends paid in financing). Ind AS 116 always puts the interest part of lease payments in financing, and Ind AS usually shows interest paid in financing for non-finance entities.
- **Analyst impact:** Align cash flow from operations by moving interest to a single section before comparing free cash flow.
- **Adjustment recipe:** `ifrs16_to_pre16_ebitda`
- **Citations:**
  - IAS 7, paras 31-34: <https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/>
  - ASC 230, 230-10-45-16 to 45-17: <https://asc.fasb.org/>
  - Ind AS 116, Lease interest classified in financing: <https://alumni.in.kpmg.com/downloads/Publications/Accounting_Publications/firstnotes-leases-standard-ind-as-116-notified-mca.pdf>

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
- **Summary:** FRS 102 permits policy choices that IFRS removes: expensing or capitalising development, expensing or capitalising borrowing costs, and amortising goodwill over its useful life (a maximum of ten years when the life cannot be estimated reliably) where IFRS tests goodwill for impairment each year and never amortises it. Until 2026 operating leases of lessees stayed off balance sheet. After the 2024 amendments (periods from 1 January 2026), revenue and leases follow an IFRS 15 and IFRS 16 like approach.
- **Analyst impact:** Compare UK private company accounts with IFRS peers after adding back goodwill amortisation and pre-2026 lease commitments, and decide a common development and borrowing cost policy.
- **Adjustment recipe:** `capitalise_operating_leases`
- **Citations:**
  - FRS 102, Sections 18, 19 (goodwill amortisation), 20, 23: <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>
  - IAS 36, para 90 (annual goodwill test): <https://www.ifrs.org/issued-standards/list-of-standards/ias-36-impairment-of-assets/>

### `diff-indas-applicability`
- **Frameworks:** IndAS, IFRS
- **Confidence:** verified
- **Summary:** Ind AS is mandatory in phases under the Companies (Indian Accounting Standards) Rules. From the year starting 1 April 2016, listed companies and unlisted companies with net worth of INR 500 crore or more must apply it, together with their parents, subsidiaries, associates and joint ventures. From 1 April 2017 it extends to all listed companies and unlisted companies with net worth of INR 250 crore up to 500 crore. Companies on SME exchanges and those under INR 250 crore stay on the older Accounting Standards. Net worth is measured on standalone statements, and once Ind AS applies it continues even if net worth falls. Banks, insurers and NBFCs follow later dates.
- **Analyst impact:** Check which accounting regime an Indian company uses before comparing: pre-2016 or smaller companies are not on Ind AS, so leases, financial instruments and business combinations differ from IFRS peers.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - Companies (Indian Accounting Standards) Rules 2015, Rule 4 (roadmap), as summarised: <https://taxguru.in/company-law/applicability-indian-accounting-standard-ind.html>
  - Ind AS, MCA accounting standards page: <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>

**Verified facts**
- Phase thresholds INR 500 crore (FY2016-17) and 250 crore (FY2017-18), SME exemption, standalone net worth: <https://taxguru.in/company-law/applicability-indian-accounting-standard-ind.html>

## eas_ifrs_mapping

### `diff-eas-ifrs-new-standards`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** The newer Egyptian standards copy IFRS: EAS 47 corresponds to IFRS 9 financial instruments, EAS 48 (revenue from contracts with customers, five-step model) to IFRS 15, and EAS 49 (lessee right-of-use asset and lease liability) to IFRS 16 leases. All three were issued in 2019 (the FRA lists them under its 2019 decisions); an appendix to EAS 47 was added in 2023 (Prime Ministerial Decision 4575 of 2023). Differences come from effective dates, transition options and special treatments granted by Egyptian regulation. Early and late adopters make years non-comparable inside the same market.
- **Analyst impact:** Map EAS lines to the matching IFRS concepts and flag the adoption year and transition method; do not blend pre- and post-adoption years without restatement.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - EAS 47, 48, 49, FRA decisions list (2019, 2023): <https://fra.gov.eg/en/?p=13760728>
  - IFRS jurisdiction profile: Egypt, EAS issued 2015, amended 2019 and 2023: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Verified facts**
- EAS 47, 48 and 49 issued in 2019; EAS 47 appendix C added 2023: <https://fra.gov.eg/en/?p=13760728>
- 2019 update added standards based on IFRS 9, 15 and 16: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Unverified facts**
- Effective dates and postponement decisions for EAS 47/48/49
- Issuing decision number (reported as Minister of Investment Decision 69 of 2019 in secondary sources only)

### `diff-eas-ifrs-legacy-map`
- **Frameworks:** EAS, IFRS
- **Confidence:** unverified
- **Summary:** Older Egyptian standards line up with IAS. Confirmed by the titles in the 2024 FRA decree: EAS 1 presentation (IAS 1), EAS 5 accounting policies, estimates and errors (IAS 8), EAS 13 foreign exchange effects (IAS 21), EAS 17 separate financial statements (IAS 27), EAS 23 intangible assets (IAS 38), EAS 24 deferred tax (IAS 12), EAS 34 real estate investment (IAS 40). Other pairings, believed but not checked: EAS 2 with IAS 2 inventories, EAS 4 with IAS 7 cash flows, EAS 10 with IAS 16 PPE, EAS 22 with IAS 33 earnings per share, EAS 31 with IAS 36 impairment, EAS 38 with IAS 19 employee benefits.
- **Analyst impact:** Use as a first-pass concept map when reading Egyptian notes; confirm each unchecked pairing in the current standards text and flag where Egyptian options differ.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - PM Decree 636 of 2024, Article 1 and Explanation 2 references: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>
  - Egyptian Accounting Standards, FRA standards index: <https://fra.gov.eg/en/?p=13760728>

**Verified facts**
- Titles of EAS 1, 5, 13, 17, 23, 24, 34, 47, 48 as named in Decree 636/2024: <https://fra.gov.eg/wp-content/uploads/2024/07/Decree-no-636_.pdf>

**Unverified facts**
- EAS 2, 4, 10, 22, 31, 38 numbering

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

## framework_adoption

### `diff-socpa-ifrs-adoption`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** unverified
- **Summary:** Saudi Arabia moved to IFRS as endorsed by SOCPA in stages. Listed entities applied it from 1 January 2017, the date set by the SOCPA decision and followed by the capital market regulator, which asked listed companies to report their transition progress. Other establishments follow for periods after 1 January 2018, with early application possible from 2017; non-publicly-accountable entities use the SMEs framework rather than full IFRS. Banks and insurers already reported under IFRS earlier. During the first years the cost model was kept for PPE and intangibles, so Saudi figures before and after transition are not on the same footing.
- **Analyst impact:** Do not compare Saudi statements across the 2016 to 2017 boundary without the transition reconciliation (retained earnings and equity restated); check which framework an unlisted Saudi counterparty used.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - SOCPA IFRS endorsement, Adoption timeline for listed and other entities: <https://www.arabnews.com/corporate-and-sponsored-content/kpmg-to-make-private-sector-ready-for-upcoming-ifrs-1137586>
  - Saudi Capital Market Authority, Listed company IFRS transition disclosures: <https://cma.gov.sa/en/MediaCenter/PR/Pages/Standards.aspx>
  - IFRS jurisdiction profile: Saudi Arabia, Adoption and revaluation timing: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>

**Verified facts**
- Listed companies applied IFRS from 1 January 2017; other establishments for periods after 1 January 2018 (early application from 2017): <https://www.arabnews.com/corporate-and-sponsored-content/kpmg-to-make-private-sector-ready-for-upcoming-ifrs-1137586>
- Capital market regulator required listed companies to disclose IFRS transition progress; adoption from early 2017 per the SOCPA decision: <https://cma.gov.sa/en/MediaCenter/PR/Pages/Standards.aspx>
- IFRS required for publicly accountable entities; cost model until fiscal years starting 2022: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/saudi-arabia/>

**Unverified facts**
- Which framework applies to each class of non-listed entity from 2018 (IFRS for SMEs reported by secondary sources)

### `diff-uae-ifrs-requirement`
- **Frameworks:** UAE-IFRS, IFRS
- **Confidence:** unverified
- **Summary:** The UAE has never had a local GAAP: its commercial companies legislation requires international accounting standards, which in practice means IFRS as issued by the IASB (Federal Decree-Law 32 of 2021 replaced the 2015 companies law, which carried the same requirement). Listed companies trade on the Dubai Financial Market or the Abu Dhabi Securities Exchange; ADX listing rules require IFRS and DFM permits it with most issuers using it. The securities regulator, formerly the Securities and Commodities Authority (SCA), was reconstituted as the Capital Market Authority (CMA) under Federal Decree-Laws 32 and 33 of 2025, effective 1 January 2026. New IFRS standards apply from their own effective dates because there is no endorsement step.
- **Analyst impact:** UAE listed statements are full IFRS with no carve-outs, so use IFRS recipes unchanged; some financial institutions may use AAOIFI, so check the basis of preparation note. Refer to the regulator by its current name when sourcing disclosures after 2025.
- **Adjustment recipe:** `eas_to_ifrs_map`
- **Citations:**
  - IFRS jurisdiction profile: UAE, Companies law, DFM, ADX, DFSA: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/united-arab-emirates/>
  - Federal Decree-Laws 32 and 33 of 2025, Capital Market Authority (formerly SCA): <https://www.regulationtomorrow.com/2026/01/uae-sca-renamed-cma-and-other-landmark-legislations/>

**Verified facts**
- Companies law requires international standards (IFRS in practice); ADX listing rules require IFRS; DFM permits IFRS and most issuers use it: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction.html/united-arab-emirates/>
- Federal Decree-Laws 32 and 33 of 2025 establish the Capital Market Authority, effective 1 January 2026: <https://www.regulationtomorrow.com/2026/01/uae-sca-renamed-cma-and-other-landmark-legislations/>

**Unverified facts**
- Article of Federal Decree-Law 32 of 2021 that sets the IFRS requirement
- That the CMA directly supervises DFM and ADX disclosures (only commentary read)

## business_combinations

### `diff-business-combinations`
- **Frameworks:** IFRS, USGAAP, IndAS, FRS102, EAS
- **Confidence:** verified
- **Summary:** IFRS 3 and ASC 805 both require the acquisition method for business combinations: identify the acquirer, measure assets and liabilities at fair value, recognise goodwill, expense deal costs; pooling of interests is not allowed for acquisitions. Transactions under common control are outside the scope of IFRS 3, so practice varies (book value or predecessor accounting, sometimes with restatement of comparatives); US GAAP uses carrying amounts for common-control transfers. Ind AS 103 Appendix C prescribes pooling of interests at carrying values for common-control combinations, so no goodwill arises. FRS 102 uses acquisition accounting for acquisitions but still allows merger accounting for qualifying group reconstructions.
- **Analyst impact:** After a group reorganisation, expect no fair value step-up or goodwill under pooling or merger accounting and restated comparatives; for acquisitions compare on the acquisition method and add back purchase-price amortisation. Use pro forma figures to compare organic growth.
- **Adjustment recipe:** `associates_share_strip`
- **Citations:**
  - IFRS 3, paras 2(c) (common control scope exclusion), 4-5, 32: <https://www.ifrs.org/issued-standards/list-of-standards/ifrs-3-business-combinations/>
  - ASC 805, 805-10, 805-50 (common control): <https://asc.fasb.org/>
  - Ind AS 103, Appendix C (common control, pooling of interests): <https://www.mca.gov.in/content/mca/global/en/acts-rules/ebooks/accounting-standards.html>
  - FRS 102, Section 19 (acquisitions and group reconstructions): <https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/uk-and-ireland-standards/frs-102/>

## provisions

### `diff-provisions-ias37-asc450`
- **Frameworks:** IFRS, USGAAP, EAS, IndAS, FRS102
- **Confidence:** verified
- **Summary:** Under IAS 37 a provision needs a present obligation, legal or constructive, arising from a past event, a probable outflow of economic benefits (more likely than not), and a reliable estimate; it is measured at the best estimate and discounted when the effect is material. Possible obligations or ones that cannot be measured are contingent liabilities, disclosed but not booked. US GAAP (ASC 450) accrues a loss contingency when a loss is probable (a higher likelihood bar than IFRS) and reasonably estimable, uses the low end of a range when no point is better, and generally does not discount. Egyptian, Indian and UK standards follow the IAS 37 approach.
- **Analyst impact:** IFRS reporters book some litigation and restructuring liabilities earlier and at a higher point in a range than US reporters; treat litigation, decommissioning and warranty provisions with expected cash outflows as debt-like and read the contingent liability note for unbooked exposure.
- **Adjustment recipe:** `eosb_as_debt_like`
- **Citations:**
  - IAS 37, paras 14, 36, 45, 86: <https://www.ifrs.org/issued-standards/list-of-standards/ias-37-provisions-contingent-liabilities-and-contingent-assets/>
  - ASC 450, 450-20-25 (loss contingencies): <https://asc.fasb.org/>
