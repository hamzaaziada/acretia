# How far we are from Rogo, Model ML, Shortcut and Fiscal.ai, and how to close the gap

*Written 2026-11-16. Competitor facts come from public sources only: product pages, changelogs, launch posts, and independent tests by Wall Street Prep, Ankura, Vals and ICAEW. Content licensing (broker research, expert transcripts, CapIQ-style feeds) is out of scope, as asked.*

## Bottom line

You're right: we are not close. On breadth of finished work we're at roughly 15–20% of Rogo or Model ML.

- **Excel is the biggest gap.** Today we have:
  - one-sheet templates;
  - a 5-year DCF on % of revenue;
  - a paper LBO;
  - an `.xlsx` export with no formatting, no number formats and no input/formula colours, where every sourced value is frozen as a hardcode.

  Shortcut ships an 8-tab LBO with tranches, a cash sweep and a Checks tab. Rogo bought two companies (Subset and Offset) just to build and roll forward models.
- **Slides are second.** Our graders haven't signed off a single slide yet. We can't build into a firm's own template. We can't edit a slide in place. Two slides cost about 270k tokens.

The opening is that **every competitor's numbers are weakest where ours are strongest**. Independent tests found:

- **Wall Street Prep** (Apple 3-statement model):
  - The best tool, Shortcut, scored 5.9/10, below a weak human analyst at 6.4.
  - Every tool scored 0 on circularity.
  - Shortcut's historicals had invented line items that still summed to the right totals.
- **Ankura:** no tool produced a production-ready model.
- **Model ML:** the one public figure is about 50% of workbooks fully correct.
- **Vals:** the most common failure is formulas pointing at the right cells with wrong inputs.

Their models type numbers. Ours can't: every historical in open-multiples is a filing fact, picked by code and carrying its accession number.

**The strategy:**
- **Let code build the numbers and the model.** The LLM only chooses assumptions and writes words.
- **Check every output before anyone sees it.** This is a deterministic suite: the balance sheet balances every period, cash ties, no hardcodes in calculation rows, and formulas are consistent across each row.
- **Publish our measured accuracy.** None of them do.

That is a "better than Rogo" claim we can defend. "We also make decks" is not.

## Scorecard

5 = best in class today, 0 = absent.

### Excel and models

| Capability | Best in class | Us today | Score |
|---|---|---|---|
| Model types | DCF, LBO, merger, 3-statement, operating model, comps, precedents (Rogo, Model ML, Shortcut) | Comps, precedents, a 1-sheet 5-year DCF, a paper LBO | 1 |
| Model depth | **Shortcut LBO:** 8 tabs, revolver/TLA/TLB/PIK, 5-step sweep, returns attribution, Checks tab. **3-statement:** schedules + Checks tab | No schedules, no integrated statements, no checks | 0.5 |
| Output file | Multi-tab; IB formatting (blue inputs, black formulas, green links); number formats; source in cell comments with the PDF page highlighted (Shortcut v0.6) | `sheets.to_xlsx`: one sheet, no styles or formats; `OM()` values written as bare hardcodes with no source comment | 0.5 |
| Circularity, integration | Nobody does it well (all scored 0 at WSP) | None | 0 |
| Work on the user's own model | Roll forward a new quarter; retrofit source links (Daloopa); explain and fix errors (Subset); audit mode, formula tracer, preview and rollback (Shortcut) | Read-only: `check_workbook` finds error cells and broken checks | 1 |
| Sheet agent | Planner, cell editor, verifier and formatter agents; Plan Mode; checkpoints | Browser agent with validation and 2 repair rounds; ~30 functions; one sheet | 1.5 |

### Slides

| Capability | Best in class | Us today | Score |
|---|---|---|---|
| Deck types | Valuation book (comps, precedents, DCF, LBO, football field), CIM, teaser, management presentation, company and strip profiles (Rogo, Model ML) | Deck Studio (free-form) + 5 fixed decks (comps, tear sheet, valuation, rounds, answer) | 1.5 |
| Firm template | Learns from a firm's prior decks (charts, tables, logos); output "in exact prior formats" (Model ML) | Our own house master only | 0.5 |
| Visual quality | "85% of the way there" (a Baird user on Rogo) | Our own partner and MD graders: no slide passed; best drafts 5–7/10 | 1.5 |
| Numbers tied to the model | PowerPoint plug-in pulls live numbers from the model and regenerates exhibits when it changes (Model ML) | Deck numbers come from the data service, not linked to a workbook | 1 |
| Editing | Comment on the slide → edit in place, batched and versioned (Rogo Slides Annotator) | "Redo this slide" regenerates the whole slide | 1 |
| Speed and cost | Minutes | ~130k tokens and many minutes per slide | 1 |
| Deck QA | AutoCheck: maths, tie-out, facts, formatting, logic (Model ML) | Consistency checker + spacing checks + panel grading | **3.5** |

### Analysis depth and data

Content licensing is ignored here; this is only what we can compute.

| Capability | Best in class | Us today | Score |
|---|---|---|---|
| History | 20+ annual and 40+ quarterly periods (Fiscal.ai) | LTM, FY and FY−1 only (the XBRL has the full history; we discard it) | 1 |
| Statements | Full as-reported and standardised statements | ~20 standardised concepts; no full income statement, balance sheet or cash flow | 1 |
| Segments and KPIs | 2,300 companies, 12+ years (Fiscal.ai); segments for 5,500 tickers (Daloopa) | None | 0 |
| Adjusted / non-GAAP | Adjusted EBITDA, EPS and FCF matching the Street | Unadjusted only | 0 |
| Calendarisation, diluted shares | Standard practice | Neither: basic shares only, no calendarisation | 0 |
| Prices | Live | **Test prices of $100: every multiple in `public_comps.csv` is meaningless** | 0 |
| Foreign filers | Quarterly data | 20-F LTM is the last fiscal year (ASML "LTM" = FY2025) | 1 |
| Precedent transactions | From CapIQ or PitchBook | 172 deals parsed from proxy fairness-opinion tables, each with its source | **2.5** (unique) |
| Cited Q&A, document grid | Hebbia Matrix; Rogo deep-link citations | Ask + Matrix with quote-level citation verification | **3** |

### Accuracy

| Capability | Best in class | Us today | Score |
|---|---|---|---|
| Field provenance | Every cell links to the filing (Daloopa, Rogo) | Every field has a concept + accession (`provenance.jsonl`), but nothing clickable in Excel | 3.5 |
| Measured accuracy | Vendor claims of "99%" with no published method | Never measured | 0 |
| Model correctness checks | Shortcut Checks tab (BS and cash only, year 1) | None for models | 0 |

## Where everyone is weak (our opening)

1. **Historicals checked line by line, not only by subtotal.** WSP caught Shortcut inventing line items that still summed to the right totals. We can check every line against XBRL.
2. **Full integration with interest circularity.** That means:
   - interest on average debt and cash balances;
   - a revolver;
   - a 1/0 circularity breaker;
   - shares modelled properly.

   Every tool scored 0 on this.
3. **Formula consistency across each row.** ICAEW: AI "is notorious for changing formulas as it goes across a forecast." This is easy to lint with R1C1 comparison.
4. **Measured whole-workbook correctness.** The best public number is about 50%.
5. **Calendarisation and non-GAAP bridges.** No competitor documents how they do either.

## Roadmap

Each phase ends in something a banker can open, with a done-test.

### Phase 0: Measure first (OM-Bench)

We can't close a gap we don't measure. Grading is deterministic wherever possible.

1. **Data gold set.** 30 companies × 25 line items × 3 periods, checked by hand against the filing tables. This includes the hard cases: restatements, 52/53-week years, 20-F filers, banks.
   - **Metric:** exact match at display precision.
   - **Target:** ≥ 99.5%, published.
2. **Model tasks (12), mirroring the WSP and Vals tests:**
   - Apple 3-statement (3 historical + 4 forecast years)
   - LBO with tranches
   - DCF on the 3-statement
   - merger accretion/dilution
   - comps with calendarisation
   - **roll an existing model forward with a new 10-Q**
   - **audit a model with 10 planted errors**
3. **Model graders:**
   - opens and recalculates in LibreOffice with no error cells
   - BS balances every period; cash ties
   - no constants inside calculation formulas
   - R1C1 formulas consistent across each row
   - colour conventions followed
   - circularity breaker works
   - values match a reference model within tolerance
4. **Deck tasks (10):** comps page, football field, company profile, situation overview, CIM executive summary, teaser, board update.
   - **Graded by:** the partner + MD panel, the spacing checks, and a tie-out of every number to the workbook.
5. **Side-by-side.** Run the same tasks on Shortcut's free tier and Fiscal.ai's free plan. You do the sign-ups; I don't create accounts.

### Phase 1: A real Excel engine (biggest gap; all deterministic)

1. **`om/xlsx.py`: a real workbook writer.**
   - Multiple sheets, styles, number formats, widths, freeze panes.
   - Blue inputs, black formulas, green links.
   - Defined names; a scenario switch with data validation; the iterative-calculation flag.
   - **Every sourced number gets a cell comment and hyperlink to the filing** (concept, accession, period).
2. **Financial statements from XBRL.**
   - Full as-reported income statement, balance sheet and cash flow; 5–10 years plus quarters.
   - Standardised mapping, where every "other" line reconciles to the reported total.
   - A line-level check against the filing, so errors can't hide under subtotals.
3. **3-statement model generator.**
   - Schedules: revenue build, PP&E and D&A, NWC, debt with a revolver, interest on average balances with a circularity breaker, tax, and equity/shares (treasury-stock diluted).
   - Base / up / down switch.
   - A Checks tab that every tab rolls up into, checked in every period.
   - **Code writes every formula; the LLM proposes assumptions only.**
4. **Rebuild the other models on that base:**
   - **DCF:** on the 3-statement.
   - **Full LBO:** sources & uses, tranches, sweep, returns attribution, IRR grid.
   - **Merger model:** accretion/dilution, simple purchase-price allocation.
5. **Workbook lint, run on every output.** Extends `consistency.check_workbook`. A model fails if the lint fails.

**Done when** the Apple 3-statement task passes every Phase 0 model grader.

### Phase 2: Work on the user's own models

1. Read an existing workbook as a formula graph: precedents and dependents.
2. **Retrofit:** match hardcoded historicals to XBRL facts, add source links, flag cells that don't match.
3. **Roll forward:** add the new quarter while keeping the user's formulas and formatting.
4. **Audit mode:** the Phase 0 lint, plus an "explain this number" trace, plus a proposed fix shown as a preview diff with rollback.
5. Later: an Office.js add-in so all of this runs inside Excel.

### Phase 3: Analysis depth

Everything here is computed, not licensed.

1. Full annual and quarterly history.
2. Calendarisation to December year-ends.
3. Treasury-stock diluted shares from the equity-compensation footnotes.
4. **Non-GAAP:** parse the reconciliation tables in earnings-release EX-99s (we already ingest them). This gives adjusted EBITDA and EPS, each with a bridge back to GAAP.
5. **Segments** from the XBRL dimensional data in each filing's instance document. `companyfacts` drops dimensions, so we read the instance documents directly.
6. **20-F interim figures** from 6-K exhibit tables.
7. **A price feed.** This is the one data dependency we can't skip; without it every multiple is fake. Your licensed EOD CSV works today. A paid API is the next step.

### Phase 4: Decks a banker would send

1. **Firm template ingestion.**
   - Read the client's `.pptx`/`.potx`: masters, layouts, theme colours, fonts, placeholder positions.
   - Generate a per-firm house profile, then build into their layouts.
2. **An exhibit library driven by the workbook,** not by LLM-typed numbers:
   - comps table
   - football field (ranges from comps, precedents, DCF and LBO)
   - share price chart
   - precedents table
   - sources & uses
   - returns grid

   Every figure links back to a workbook cell, and re-running the model refreshes the deck.
3. **Deck types:**
   - valuation book
   - company and strip profiles (the thing WSO users say Rogo does well)
   - teaser
   - CIM executive summary
4. **Comment-to-edit:** structured edits to the layout JSON in place, with versions, instead of regenerating the slide.
5. **Speed.** Data exhibits skip the SVG/image step and go straight to native layout. The image path is kept for concept slides only.
   - **Target:** a 10-slide valuation book in under 5 minutes and under 100k tokens.

### Phase 5: Enterprise (later; you said no login for now)

SSO, audit log, single-tenant or customer-cloud deployment, SOC 2. Rogo and Model ML both have these, and banks require them.

## What not to chase

- **Licensed content:** expert transcripts, broker research, CapIQ.
- **Forward-deployed banker armies:** Rogo built over 2,450 custom agents in one week.
- **Email-triggered agents:** wait until the outputs are worth delegating.

## Sources

- **Rogo:** [platform/agents](https://rogo.com/platform/agents), [Jul 2026 IB post](https://rogo.com/blog/ai-for-investment-banking), [May 2026 update](https://rogo.com/blog/may-product-update), [Subset](https://rogo.com/news/rogo-acquires-subset), [Baird case](https://rogo.com/customers/baird-investment-banking), [data evaluations](https://rogo.com/blog/data-evaluations), [Vantaige review](https://vantaige.io/blog/rogo-ai-review-felix-investment-banking-2026)
- **Model ML:** [Operator](https://modelml.com/articles/operator-the-ai-agent-for-investment-banking-workflows), [plug-ins](https://modelml.com/articles/model-ml-plug-ins-for-word-excel-powerpoint-and-teams), [AI Modules](https://www.modelml.com/articles/introducing-ai-modules-by-model-ml), [GAII](https://www.gaiiinstitute.com/companies/model-ml/)
- **Shortcut:** [3-statement](https://shortcut.ai/blog/posts/three-statement-model), [LBO](https://shortcut.ai/blog/posts/lbo-model), [v0.6](https://shortcut.ai/blog/posts/v0-6-release), [SpreadsheetBench](https://shortcut.ai/blog/posts/spreadsheetbench), [changelog](https://mog.shortcut.ai/changelog)
- **Independent tests:** [WSP ranking](https://wallstreetprep.com/knowledge/ranking-the-best-ai-tools-for-financial-modeling-2026), [Ankura](https://ankura.com/insights/putting-ai-to-the-test-how-5-tools-performed-across-3-financial-models), [Vals EMB v1.1](https://www.vals.ai/benchmarks/emb-v1-1), [ICAEW](https://www.icaew.com/insights/viewpoints-on-the-news/2026/jun-2026/how-to-identify-ai-errors-in-financial-models)
- **Fiscal.ai:** [docs](https://docs.fiscal.ai/), [MCP skills](https://docs.fiscal.ai/docs/guides/mcp-skills)
- **Daloopa:** [model updates](https://daloopa.com/blog/product-updates/automate-financial-model-updates), [data quality](https://daloopa.com/blog/product-updates/financial-data-quality-llm-workflows-mcp)

## Progress, 2026-11-16: Excel engine (Phase 1 core) and model benchmark

**Built**
- `om/xlsx.py`: a styled multi-sheet writer and reader.
- `om/statements.py`: full statements from XBRL.
- `om/model3.py`: the integrated 3-statement model, plus DCF.
- `om/formula.py`: a formula evaluator with Excel-style iteration.
- `om/modelcheck.py`: a grader for any workbook.
- `om/bench.py`: the benchmark runner.
- **CLI:** `model`, `grade` and `bench`.
- **Web:** a "3-statement model (.xlsx)" button on Sheets; Check now grades uploaded models.

**What a model contains**
- Ten sheets: Cover, Assumptions, IS, BS, CF, Schedules, Debt, DCF, Checks, Filings.
- Scenario switch: Base, Upside, Downside.
- Revolver, and interest on average balances behind a 1/0 circularity breaker.
- Every historical figure in blue, with the XBRL concept, period and accession in a comment, and a link to the filing.

**Measured (`python3 open_multiples.py bench … --libreoffice`)**
- **Models:** AAPL, MSFT, COST, NVDA, ASML (IFRS 20-F) and AI (loss-maker) all grade 100/100 and production-ready.
  - The balance sheet balances every period, in every scenario, with the circularity on or off.
  - Historical EPS, gross profit, total assets and operating cash flow tie to the filing.
- **Agreement:** our saved values match a LibreOffice recalculation on 6,958 of 6,958 formula cells.
- **Audit:** 10 of 10 planted modelling errors caught; all 8 cell-level ones located to the exact cell; no false alarms on the clean model.
- **Banks:** JPM is refused clearly. Banks need a different model.

**AI-built models from earlier runs, graded by the same tool**
- **Cleopatra integrated DCF:** 58.7.
  - Two invalid formulas, one an unfilled `{rev_row}` placeholder.
  - #DIV/0! errors.
  - 168 formulas with typed numbers.
- **CLHO test model:** 62.8. 88 labels written as formulas, and a Checks tab that checks nothing.
- **Cleopatra valuation:** 67.1. A self-referencing WACC with iterative calculation off.

**Still missing in Phase 1**
- Full LBO (tranches, cash sweep, returns attribution) and the merger model.
- Quarterly history.
- Treasury-stock diluted shares.
- A segment-level revenue build.
- Forecast defaults are mechanical, taken from each company's history. There are no consensus estimates.
- **Not yet tested in desktop Excel:** only LibreOffice so far. Comment boxes and the iterative-calculation flag need a check in Excel itself.
