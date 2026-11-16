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
- **Summary:** EAS 49 (lease contracts, issued in 2019 as part of the update that added standards based on IFRS 9, 15 and 16) mirrors IFRS 16 for lessees. Before it, Egyptian companies used the older leasing rules where operating lease rentals were an expense and only finance leases appeared on the balance sheet. Expect a transition-year step in EBITDA, lease liabilities and retained earnings in the first EAS 49 year. The effective date and transition options were adjusted by later decisions and are not confirmed here.
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
- **Summary:** When a currency is devalued, monetary items in foreign currency (debt, payables, cash) are retranslated at the new closing rate and the full difference hits profit or loss under IAS 21. Importers with USD debt show big losses, exporters with USD cash show gains. Egypt had devaluations in 2016 and 2022 (recognised in the IFRS Foundation jurisdiction profile) and further steps in 2023 and March 2024 (not confirmed here). Revenue in local currency also steps up as prices are reset, so a single year mixes a one-off translation loss with a changed operating base.
- **Analyst impact:** Strip devaluation FX losses out of recurring EBITDA and earnings. Take the FX gain or loss line (and any FX embedded in finance costs or cost of sales) out of operating profit, tax-effect it, and show adjusted net income beside reported. Where an entity capitalised or deferred FX loss under EAS 13 special treatment, add the deferred charge back so the period carries its economic cost. Then check the unhedged USD debt still outstanding, since the next devaluation repeats the effect.
- **Adjustment recipe:** `devaluation_fx_loss_normalise`
- **Citations:**
  - IAS 21, paras 23, 28: <https://www.ifrs.org/issued-standards/list-of-standards/ias-21-the-effects-of-changes-in-foreign-exchange-rates/>
  - IFRS jurisdiction profile: Egypt, Foreign currency translation differences: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>
  - Central Bank of Egypt, Official exchange rate history: <https://www.cbe.org.eg/en/economic-research/statistics/exchange-rates>

**Verified facts**
- Egypt applied special translation treatment after the 2016 and 2022 devaluations: <https://www.ifrs.org/use-around-the-world/use-of-ifrs-standards-by-jurisdiction/view-jurisdiction/egypt/>

**Unverified facts**
- Devaluation steps in 2023 and March 2024

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

## zakat_tax

### `diff-zakat-vs-income-tax`
- **Frameworks:** SOCPA-IFRS, IFRS
- **Confidence:** verified
- **Summary:** In Saudi Arabia zakat is a 2.5 percent charge on the zakat base (broadly net worth as computed for zakat) and falls on the Saudi and GCC owners' share, while income tax at 20 percent of adjusted profit applies to the share held by non-Saudi, non-GCC owners. Mixed-ownership companies bear both in proportion. SOCPA's position is that zakat sits outside IAS 12, so it is accounted for under its own endorsed requirements and IAS 8 rather than as an IAS 12 income tax, and there is no deferred tax on zakat. A live IFRS 18 debate concerns whether zakat is presented together with income tax or in operating results.
- **Analyst impact:** Compare KSA companies on a pre-zakat and pre-tax basis, or treat zakat as a tax by adding it to tax expense (recipe zakat_as_tax). Effective tax rates are not comparable across ownership structures, and net income to owners is after zakat. Do not leave zakat in operating costs.
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
- **Summary:** The newer Egyptian standards copy IFRS: EAS 47 corresponds to IFRS 9 financial instruments, EAS 48 to IFRS 15 revenue, EAS 49 to IFRS 16 leases. All three were issued in 2019 (the FRA lists them under its 2019 decisions); an appendix to EAS 47 was added in 2023 (Prime Ministerial Decision 4575 of 2023). Differences come from effective dates, transition options and special treatments granted by Egyptian regulation. Early and late adopters make years non-comparable inside the same market.
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
