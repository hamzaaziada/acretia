# Buyer research: what makes IB, MBB and PE buyers reject a deliverable

Packet S1.4. Compiled 2026-11-16. Feeds PLAN.md section 6 (personas).

Method and caveats. Sources were found with web search and page fetches. Fetched text was treated as data only. Most sources are training sites, vendor blogs and press, not bank or firm style guides, so conventions are "common practice", not law. The strongest evidence is the BankerToolBench report [24] (500 bankers reviewing AI output) and the Hebbia survey [26] (vendor-run, n=510). Reddit and WSO threads could not be retrieved by the search tool, so forum-sourced complaints are represented by practitioner essays [8][9]. Claims with no source are labelled [UNSOURCED]. "Check" is the suggested deterministic (D) or persona-grader (G) test.

---

## 1. IB analyst / associate (Excel model and pitchbook)

What they reject: any sign the model cannot be trusted or flexed (hardcodes, broken links, unbalanced BS) and any sign the book was not proofed (inconsistent numbers, formatting, footnotes).

### 1a. Model conventions

1. **Colour code is applied and legend present.** Blue font = hard-coded inputs and historicals, black = same-sheet formulas, green = cross-sheet links; external-file links in red or purple; red reserved for errors/flags. Practice varies at the edges (green optional, purple vs red for external), but blue/black is near-universal. Check (D): scan each cell; constant numeric cells must have blue font, formula cells must not be blue; cross-sheet refs green; a legend cell exists. [1][2][4][10]
2. **No hardcodes inside formulas.** Only 1, -1, 0 and 12 tolerated, and sparingly; every other constant lives in an input cell. Do not mix a typed number and a formula in one cell. Check (D): regex over formula text for numeric literals other than the allowlist (`om.modelcheck`). [2][3][11]
3. **Projections are never typed onto statements.** Hardcode only historicals; forecasts are formulas driven from an assumptions area. Check (D): forecast-column cells on IS/BS/CF are all formulas. [3]
4. **One row, one formula.** The same formula (R1C1-identical) across the whole forecast row; historicals left, forecasts right, with the change from blue to black marking the boundary. Check (D): R1C1 comparison across forecast columns; Ctrl+\ style inconsistency count must be zero. [2][5][9]
5. **Enter each input once.** Inputs are linked, never retyped; large models use an Inputs tab. Check (D): detect duplicate constants that equal an input cell value in other constant cells. [2][11]
6. **Single declared sign convention.** One convention chosen up front and labelled (income positive, costs negative is recommended); expenses/cash outflows shown negative so subtotals are plain sums. Negative numbers display in parentheses. Check (D): sign of each line vs declared convention; number format contains parentheses for negatives. [2][3][4]
7. **Units, currency and scale labelled on every sheet.** Sheet header carries company, purpose, scenario, scale and currency; dollars and shares in millions, one decimal; percentages one decimal; multiples with an "x". Check (D): header cells exist on each tab; number-format audit. [2][4]
8. **Checks exist, sit near calculations, and roll up to one master check.** Minimum: assets = liabilities + equity, sources = uses, quarters sum to years, depreciation does not exceed PP&E, debt paydown does not exceed balance. Prefer direct calculation with a check over plugs. Check (D): checks tab present, all zero, master flag linked on cover. [2][7]
9. **Balance sheet balances and cash ties to the CF statement in every period, before any circularity is added.** A BS that does not balance or an untied cash line is an immediate fail. Check (D): recompute with LibreOffice and assert abs(A-L-E) < 0.5 in all periods. [14][13]
10. **Circularity is switchable.** Interest circularity has a circuit-breaker toggle (0/1 or beginning vs average balance), iterative calc is enabled, and IFERROR is not used to mask loops. Check (D): find the toggle cell; flip it, recalc, and assert the model still balances. [2][3][12][13]
11. **Zero error values.** No #REF!, #DIV/0!, #N/A, #VALUE!, #NAME? anywhere, including hidden sheets. Check (D): scan recalculated values. [8][9]
12. **Navigability.** Statements for one company on one tab, drivers grouped at top, rows/columns grouped rather than hidden, no hidden sheets at hand-off, named ranges used sparingly for global constants (not hundreds). Freeze panes on headers and labels. Check (D): hidden-sheet count = 0; named-range count under a threshold; freeze pane set on each model tab. [3] Freeze panes as a rule is [UNSOURCED] (not covered in [3]); keep as house rule.
13. **Print setup.** Print area set on each presentable tab, fit to 1 page wide, page-break preview clean, no blank trailing pages. Check (D): print area and fitToWidth set. Banking-specific print standards are [UNSOURCED]; generic Excel guidance only [37].
14. **Model design follows FAST principles** (flexible, appropriate, structured, transparent; separate foundation/workings/presentation/control sheets). Check (G): sheet-type separation. [6]
15. **Changing an input flows through.** Flexing purchase price, growth or margin must change outputs; static values pasted in place of formulas fail. This is the headline failure of AI-made models (Section 4). Check (D): perturb each input cell, recalc, assert at least one output changes; count inputs with zero dependents. [24]

### 1b. Pitchbook formatting (IB)

16. **Numbers agree across pages.** Same metric same value on every slide; a $50m discrepancy between two slides is treated as a firing-grade error. Check (D): extract all numeric claims by label and period across slides and assert equal after rounding. [8][24]
17. **Footnotes, sources, dates correct and present on every exhibit; confidentiality marks and page numbers present.** Check (D): each chart/table shape has an adjacent source note; footer page number present; date in footnote matches the source record. [8][15][16][17][19]
18. **Formatting consistency.** Same fonts, sizes, punctuation, alignment and spacing; double spaces and double periods are noticed by MDs. Placeholder and internal notes ("NTD") must never ship. Check (D): font-family/size histogram per role; regex for double spaces, "NTD", "TBD", "XX". [8][15][18][20]
19. **Page furniture lives on the master.** Logos, fonts, footers and page numbers come from the slide master, not typed per slide. Check (D): footer/page number placeholders inherited from layout. [17]
20. **Football field conventions.** One horizontal bar per method (trading comps, precedents, DCF, optional LBO) with low and high labelled; 52-week range shown as a visually distinct reference; current price and offer lines; ranges are chosen multiples, not the raw min and max of the whole comp set; DCF range from a sensitivity table; precedents typically sit above comps by a control premium. Check (D): bars present for each declared method, axis label units, reference line present; DCF bar endpoints equal sensitivity table min/max of a declared sub-range. [21][22]
21. **Comps table is sourced and dated.** Source and as-of date, consistent multiple formats (one decimal and "x"), median and mean rows, no cell showing a bare error. Check (D): table footers include source and date; formats per column uniform. [4][21] Specific comps selection criteria are not specified by the sources: [UNSOURCED].
22. **Layout hygiene: charts aligned, no overflow, no density that hides the point.** Misaligned charts and stray decimals damage credibility. Check (D): overlap/overflow/out-of-bounds shapes via `om.spacing`. [18]
23. **Review turns are cheap.** Seniors request many revisions and change feedback late, so the deliverable must be editable (native charts, live-linked tables, master-driven) rather than flattened images. Check (D): charts are native objects with embedded data. [15] Rationale for native objects is inference from [15]; treat as [UNSOURCED] extension.

---

## 2. MBB engagement manager / partner (deck)

What they reject: a deck whose titles do not tell the story, slides with several messages, unsourced or non-reconciling numbers, and polish defects (grid, alignment, footers).

1. **Every content slide has an action title: a full sentence stating the conclusion, not a topic.** Check (D): title length and verb presence heuristic; no title ends without a verb or is a noun phrase. (G) rates it. [23][48][50]
2. **The "title-only" read tells the whole story.** Reading only the titles in order must convey the argument; this is how partners review. Check (G): feed titles only to a grader, ask for the storyline and gaps. [48]
3. **One message per slide.** Each slide supports a single action title; content that does not prove the title is cut. Check (G): does every element support the title; (D): at most one chart or one table as the primary exhibit per slide. [23][48]
4. **Vertical logic: each title raises a "why" answered by the slide body.** Check (G): body evidence actually proves the claim; numbers in the title appear in the exhibit. [23][48]
5. **Horizontal logic: sibling slides follow a clear order (deductive, chronological, structural or by importance) and are MECE.** Check (G): grader outputs the ordering principle and flags overlaps/gaps. [23][25]
6. **Pyramid and SCQA at the top.** The answer comes first (executive summary), with situation-complication-question-answer opening. Check (G). [25][50]
7. **Ghost deck / storyboard first.** A deck of titles and sketched exhibits is agreed before building; the final deck must not drift from the approved storyline. Check (D): final titles diff against stored storyboard titles; flag unexplained changes. [25]
8. **Tracker / agenda that marks position.** Long decks carry a section tracker so the reader knows where they are. Check (D): tracker element present on section slides. [49] Mostly practitioner convention, partly [UNSOURCED].
9. **Source and date line on every exhibit, bottom-left; page numbers in footer.** Check (D): shape exists per exhibit with a source and date. [48][49]
10. **Every material number is traceable and reconciles.** A slide-to-source register (slide, claim, source file, page, retrieval date, data cut-off) is expected; numbers repeated across slides must match. Check (D): register completeness; cross-slide number agreement. [48][49]
11. **Right chart for the message, labelled, with units.** The chart must show what the title claims (e.g. the highlighted bar is the one named), axes labelled, units shown. Check (G) plus (D): axis titles and data labels present. [23][48]
12. **Grid discipline and whitespace.** Consistent margins and element alignment, no overflow, no text smaller than a floor size. Check (D): `om.spacing` plus minimum font size. [49] Exact margin/size thresholds are house rules: [UNSOURCED].
13. **No generic or "smooth but empty" language and no off-brand accents.** AI-style slides read generic; a model used an off-brand accent colour where the style guide required blue. Check (D): theme colours match template; (G): language specificity. [24][36][45]
14. **Reviewer round: "do all my action titles state conclusions?"** Check (G): run as a BYU-style feedback checklist. [51]

---

## 3. PE principal / investment committee (IC memo and diligence)

What they reject: an unsourced claim, a memo that hides the downside, returns that rely on multiple expansion, add-backs they cannot verify, and diligence with unflagged gaps.

1. **Memo follows the expected skeleton.** One-page executive summary (recommendation, size and price, 2-3 sentence thesis); thesis; company; market; competitive position; financial analysis; risk factors; terms and structure; value creation plan; diligence status; appendix with citations. Sources differ on ordering; all agree on presence. Check (D): required headings present. [27][28][29]
2. **Every key figure carries a clickable citation.** "Every key assumption should be sourced with a clickable in-line citation"; unsupported thesis claims slow approval. Check (D): each numeric claim has a linked source id that resolves to a document, page and highlighted region. [27]
3. **Appendix links to underlying documents** (models, filings, transcripts, CIM, expert-call notes, third-party reports). Check (D): all cited ids resolve. [27]
4. **Base, upside and downside cases, each with distinct and defensible assumptions.** A downside that barely dips below base signals untested assumptions. Check (D): downside differs from base by a minimum on revenue growth and margin; (G): rationale. [27][30]
5. **Returns sensitivity grids with IRR and MOIC together.** At minimum entry x exit multiple and growth x exit multiple; also leverage x exit multiple; show gross and net where relevant. Check (D): grids present, centre cell equals the base case output. [30][31]
6. **Returns do not depend on multiple expansion.** Show a no-expansion case, exit 1-2 turns below entry as a stress, and the entry price at which the hurdle fails; return bridge splits growth, multiple, deleveraging. Check (D): bridge sums to total return; no-expansion case present. [30][31] The "2.0-2.5x on paydown and growth alone" figure is one author's rule of thumb, not a standard.
7. **Hockey sticks flagged.** Projection inflections are called out and tagged for verification. Check (G). [30]
8. **QoE adjustments documented and recurrence-tested.** Each EBITDA add-back has support, is non-recurring under new ownership, and the bridge from reported to adjusted EBITDA is shown; lenders may cap add-backs (a 20-25% range is cited by vendor blogs, unverified). Check (D): every adjustment has a source id and a category; adjusted EBITDA bridge sums. [32][33][34]
9. **Revenue quality, customer concentration, working capital peg and tax exposure addressed.** Check (G): memo has concentration and NWC discussion when data exist. [33][34]
10. **Risk table per risk: description, probability, impact, mitigant or trigger.** Check (D): table columns present for every listed risk. [27][29]
11. **Diligence status: completed vs outstanding items with owners and dates; conditions on approval.** Check (D): status table present. [27]
12. **VDR completeness shown, with gaps flagged rather than papered over.** Map the buyer request list to the data-room index; mark each request fulfilled / partial / unaddressed; number requests with owner, status and due date. Check (D): coverage matrix computed from the request list vs indexed docs; unaddressed count surfaced on page one. [41][42]
13. **Audit before submission.** Check formulas, trace inputs to sources, confirm outputs are consistent across scenarios. Check (D): `om.formula`, `om.modelcheck` pass; scenario outputs reconcile. [27]
14. **Concise.** 12-25 pages is a typical memo length; one-page exec summary. Check (D): page count and exec summary length. [28] (typical, not a rule)

---

## 4. Complaints about AI finance tools and what unlocks $10K+/seat

Evidence: BankerToolBench [24] (Handshake AI and McGill, bankers from several bulge-bracket and elite boutiques, 100 tasks, 500 reviewers, April 2026): no deliverable client-ready; best model 58.1/100; Opus-class models produced polished Excel with hardcoded values so changing purchase price did not update; a deck showed $189.5bn then $201.0bn for the same period; off-brand accent colour; GPT-5.4 failure modes 41% code/formula bugs, 27% business-logic errors (e.g. cost synergies added to revenue), 13% invented missing numbers presented as sourced.

1. **Zero hardcoded outputs in models.** Output cells must be live formulas; test by flexing an input. Check (D): see 1a-15. [24]
2. **No invented numbers.** Every figure must resolve to a source record, or be explicitly flagged as an assumption. Check (D): numeric-claim to source-id coverage must be 100% with no orphan numbers. [24][26]
3. **Cross-slide consistency.** Check (D): same as 1b-16. [24]
4. **Business-logic sanity.** No synergies in revenue, EV bridge and diluted share logic correct. Check (D): domain assertions in `om.formula`/`om.modelcheck`. [24]
5. **Citations and dates match the source document.** Associates report AI output with wrong EV from a linked source, an off date buried in a footnote, a synergy number that does not tie, and slides that read "too smooth and generic". Check (D): footnote date equals source record date; EV recomputed from components. [36]
6. **Trust gap forces manual re-checking.** 59% of 510 finance professionals manually verify or recreate AI output all or most of the time; hallucinations and missing citations are the top concerns; even among those who trust AI, 84% still re-check. A product that removes re-checking (clickable proof for every figure) is the sellable difference. [26]
7. **Client-facing errors are already happening** at most financial firms surveyed. [43]
8. **Vendors' own accuracy claims are self-reported** (e.g. Daloopa >99% and hyperlinked data points); a buyer will test on their own sectors. Design for audit-by-click. [38]
9. **Microsoft itself warns Copilot output can be wrong and not to use the Copilot formula function for accuracy or reproducibility tasks.** Deterministic, code-written formulas are a selling point. [39][40]
10. **Generic ChatGPT/Copilot decks:** plain templates, overflow of bullet text, formatting breakage on export, generic corporate language, factual mistakes; vendors' own add-in notes limited template adherence. Check (D): overflow and template conformance; (G): specificity. [44][45]
11. **Rollouts that overpromise erode trust.** Users report executives promising unrealistic efficiency gains. Implication: be conservative in claims, show failure flags. [35]
12. **Price anchors.** Rogo is estimated around $3,300 per seat per year (third-party estimate); AlphaSense estimates range roughly $10,000-$20,000 per seat per year (third-party). No vendor publishes rate cards. A $10K+/seat tag implies the buyer must save an analyst-day per week with no re-checking. The last clause is [UNSOURCED] reasoning. [46][47]

---

## 5. Persona rubric (refines PLAN.md section 6)

Scoring: each persona returns per-criterion scores 0 to the weight, a total /10, blocking issues with locators (sheet!cell, slide number, memo section), and "would pay $10K+/seat? yes/no + why". Below 8.5 = blocked. Any item marked **HARD** that scores 0 caps the total at 6.0 regardless of the sum.

### 5.1 IB analyst (Goldman / Morgan Stanley style)

| # | Criterion | Wt | Pass descriptor (full marks) | Check |
|---|---|---|---|---|
| 1 | **HARD** Integrity: zero error values, BS balances and cash ties every period, checks tab all green | 2.0 | No error cells; balance diff under 0.5 in all periods; master check = 0 | D: recalc via LibreOffice, `om.modelcheck` |
| 2 | **HARD** Live model: no hardcodes in formulas; forecasts all formulas; input flex changes outputs | 2.0 | Zero non-allowlist literals in formulas; every input has dependents; flex test passes | D: literal scan + perturbation |
| 3 | Colour code and legend (blue/black/green, external links distinct) | 1.0 | 100% of cells conform; legend present | D |
| 4 | Row consistency and sign convention (one row one formula; declared sign convention; parentheses) | 1.0 | R1C1 inconsistencies = 0; convention declared and obeyed | D |
| 5 | Circularity switch and scenario toggle | 0.75 | Circuit breaker works; balances in both states | D |
| 6 | Navigability: sheet order, headers with units/currency, freeze panes, grouped not hidden, sparing named ranges, print setup | 1.0 | All present on all model tabs | D |
| 7 | Pitchbook hygiene: numbers agree across pages, sources/dates on exhibits, fonts/alignment consistent, football field and comps conventions | 1.25 | Zero cross-page mismatches; every exhibit sourced; football field per 1b-20 | D + G |
| 8 | Speed to usable: native editable objects, speed of review turns | 0.5 | Native charts/tables, master-driven footers | D |
| 9 | Would pay $10K+/seat | 0.5 | Yes if analyst would send to MD without re-checking | G |

Total 10.0.

### 5.2 MBB engagement manager

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Storyline: titles-only read gives the full argument; answer first; SCQA/pyramid | 2.0 | Grader reconstructs the recommendation from titles alone with no gaps | G |
| 2 | **HARD** Action titles and one message per slide | 1.75 | 100% content slides have a conclusion title; at most one main exhibit; body proves title | D + G |
| 3 | Horizontal and vertical logic (MECE ordering, "why" answered below) | 1.0 | Ordering principle identified; no overlaps or gaps | G |
| 4 | Chart fit: right chart, labelled, units, highlights match title | 1.25 | Every chart passes title-exhibit match | D + G |
| 5 | Sources and traceability: source and date line per exhibit; cross-slide numbers reconcile; slide-to-source register | 1.25 | Zero orphan numbers; register complete | D |
| 6 | Grid, alignment, whitespace, min font size, no overflow | 1.0 | `om.spacing` zero violations | D |
| 7 | House rules: title rule, footer and page number, tracker, no eyebrows, no AI-generic language, template colours | 1.0 | All present; language specific | D + G |
| 8 | Would pay $10K+/seat | 0.75 | Yes if EM would edit rather than rebuild | G |

Total 10.0.

### 5.3 PE principal / IC member

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Traceability: every figure has a clickable citation to a highlighted source region; no orphan numbers | 2.0 | 100% numeric claims linked and resolving | D |
| 2 | IC-memo structure complete (exec summary on one page, thesis through appendix) | 1.25 | All required sections present; exec summary has recommendation, size/price, thesis | D |
| 3 | Returns: base/upside/downside distinct; IRR and MOIC grids; no-expansion case; bridge | 1.75 | Grids centred on base; bridge sums; downside materially below base | D + G |
| 4 | QoE and add-backs documented; revenue quality, concentration, NWC covered | 1.25 | Every adjustment sourced and categorised | D + G |
| 5 | VDR completeness: request list vs index matrix; gaps flagged on page one | 1.25 | Fulfilled/partial/unaddressed counts shown; unaddressed items listed with owners | D |
| 6 | Risk coverage: probability, impact, mitigant or trigger per risk; hockey sticks flagged | 1.0 | Table complete; at least the deal-breaker risks present | D + G |
| 7 | Model integrity behind the memo (formulas and checks pass; scenarios reconcile) | 0.5 | `om.formula` and `om.modelcheck` green | D |
| 8 | Would pay $10K+/seat for this exact deliverable | 1.0 | Yes if the IC could approve without a second verification pass | G |

Total 10.0.

---

## 6. Gaps and open items

- Forum threads (WSO, Reddit) were not retrievable; criteria 1-12 rely on training sites and practitioner essays. A manual WSO pass is recommended before final grading calibration [UNSOURCED for forum-specific pet peeves].
- No bank or MBB firm style guide was found; pitchbook point sizes and margin thresholds are house rules to be set in DECISIONS.md.
- Vendor and blog sources (marked in the list) carry commercial bias; the two strongest empirical sources are [24] and [26].

---

## Sources

1. Macabacus, "Improve Financial Model Readability with Color Formatting", n.d. (page footer 2026). https://macabacus.com/blog/improving-model-readability-with-color-formatting
2. Wall Street Prep, "Financial Modeling Best Practices and Conventions", updated 2026-06-29. https://www.wallstreetprep.com/knowledge/financial-modeling-best-practices-and-conventions/
3. Breaking Into Wall Street, "Financial Modeling Best Practices: How to Give Your Excel Files a Makeover", n.d. https://breakingintowallstreet.com/kb/finance/financial-modeling-best-practices/
4. IB Interview Questions, "Formatting Standards and Color Conventions in IB Models", 2026-03-18. https://ibinterviewquestions.com/guides/valuation-investment-banking/formatting-standards-color-conventions-ib-models
5. ICAEW, "Intro to financial modelling, part 6: formula blocks and consistency", 2020 (via search snippet). https://www.icaew.com/technical/technology/excel-community/excel-community-articles/2020/intro-to-financial-modelling-part-6
6. Brixx, "What is the FAST Standard in Finance?" (FAST: Flexible, Appropriate, Structured, Transparent), n.d. https://brixx.com/blog/the-fast-standard-in-finance-explained/
7. Macabacus, "Error Trapping in Excel Through Flagging and Custom-Built Error Checks" (Model Check, 50+ checks), n.d. https://macabacus.com/blog/error-trapping-excel-flagging-custom-built-error-checks
8. Prospect Rock Partners, "The High Cost of Mistakes in Investment Banking: A Survivor's Guide", 2025-05-28. https://prospectrockpartners.com/the-high-cost-of-mistakes-in-investment-banking-a-survivors-guide/
9. PrepLounge Finance Forum, "Common mistakes in modeling tests", n.d. https://www.preplounge.com/finance-forum/common-mistakes-in-modeling-tests-23366
10. Financial Edge, "Financial Modeling Best Practices 2026", 2026. https://www.fe.training/free-resources/financial-modeling/financial-modeling-best-practices/
11. Finance Alliance, "12 financial modeling best practices to avoid frustrations", n.d. https://financealliance.io/12-financial-modeling-best-practices-to-avoid-frustrations
12. Adventures in CRE, "Circuit Breaker for Excel", n.d. https://www.adventuresincre.com/sdm_downloads/circuit-breaker-excel-hack/
13. Financial Edge, "What are Circular References in Financial Modeling", n.d. https://www.fe.training/?p=10046799
14. IB Interview Questions, "Circular Reasoning in Valuation Models", n.d. https://ibinterviewquestions.com/guides/valuation-investment-banking/circular-reasoning-valuation-models
15. Mergers & Inquisitions, "Investment Banking Pitch Books: Design, Examples & Templates", n.d. (latest comment 2025-06-07). https://mergersandinquisitions.com/investment-banking-pitch-books/
16. Financial Edge, "Investment Banking Pitch Book", n.d. https://www.fe.training/free-resources/investment-banking/investment-banking-pitch-book/
17. Corporate Finance Institute, "PowerPoint and Pitchbooks" (FMVA), n.d. https://corporatefinanceinstitute.com/resources/finpod/powerpoint-and-pitchbooks/
18. Firmex, "Is Your Pitch Book Out of Pitch?", n.d. https://www.firmex.com/resources/blog/is-your-pitch-book-out-of-pitch/
19. Acuity Knowledge Partners, "Pitchbook standardisation for a US investment bank", 2020 (snippet only; page not retrievable). https://www.acuitykp.com/wp-content/uploads/2020/04/Pitchbook-standardisation-for-a-US-investment-bank.pdf
20. Slide Genius, "The Pitfalls of Not Proofreading Your Pitch Deck", n.d. https://www.slidegenius.com/blog/the-pitfalls-of-not-proofreading-your-pitch-deck
21. Financial Edge, "Football Field Analysis", n.d. https://www.fe.training/free-resources/valuation/football-field-analysis/
22. IB Interview Questions, "Football field valuation chart guide", n.d. https://ibinterviewquestions.com/blog/football-field-valuation-chart-guide
23. think-cell, "Using the Pyramid Principle to build better PowerPoint presentations", 2023-02-07. https://www.thinkcell.com/en/resources/content-hub/using-the-pyramid-principle-to-build-better-powerpoint-presentations
24. BeRI, "AI Models Fail Investment Banking Reality Check: Zero Outputs Client-Ready" (BankerToolBench, Handshake AI and McGill), 2026-04-26. https://www.beri.net/article/ai-models-fail-investment-banking-reality-check
25. Stratrix, "Storyboard a deck" (ghost deck), n.d. https://www.stratrix.com/learn/craft/storyboard-a-deck
26. Hebbia, "7 in 10 Finance Teams Say AI Is Faster, But Most Still Double-Check Its Outputs" (Centiment survey, n=510, fielded 2026-04-28 to 05-09), 2026-06-30. https://www.hebbia.com/resources/diligence-paradox-survey
27. Hebbia, "IC Memo Best Practices for Private Equity and Private Credit", 2026-07-13. https://www.hebbia.com/resources/ic-memo-best-practices
28. F2, "What belongs in an investment committee memo in 2026", 2026. https://f2.ai/blog/what-belongs-in-an-investment-committee-memo-in-2026
29. Stanford Long-Term Investing, "Addepar: investment memos and decision making", n.d. https://longterminvesting.stanford.edu/sites/g/files/sbiybj23856/files/media/file/addepar-investment-memos-and-decision-making.pdf
30. Anthropic financial-services plugin, "ic-memo" skill (returns and sensitivity guidance), n.d. https://raw.githubusercontent.com/anthropics/financial-services/main/plugins/vertical-plugins/private-equity/skills/ic-memo/SKILL.md
31. IB Interview Questions, "LBO returns: IRR, MOIC, cash-on-cash", n.d. https://ibinterviewquestions.com/guides/valuation-investment-banking/lbo-returns-irr-moic-cash-on-cash
32. Peony, "Quality of Earnings in 2026: Add-Backs, Cost, and What Survives Scrutiny", 2026. https://www.peony.ink/blog/quality-of-earnings
33. Not Very Private Equity, "EBITDA add-backs, explained", n.d. https://www.notveryprivateequity.com/ebitda-add-backs/
34. EightX, "QofE: what buyers scrutinize", n.d. https://eightx.co/blog/qofe-what-buyers-scrutinize
35. American Banker, "Pressure, FOMO: Some big banks are rolling AI out too fast", 2026-05-15. https://www.americanbanker.com/news/pressure-fomo-some-big-banks-are-rolling-ai-out-too-fast
36. Prospect Rock Partners (M. Dennes), "Rogo was supposed to shrink the junior class; instead it's creating more work for associates and VPs", 2026-08-21. https://prospectrockpartners.com/rogo-was-supposed-to-shrink-the-junior-class-instead-its-creating-more-work-for-associates-and-vps/
37. XelPlus / Microsoft Support, Excel print area and fit-to-page guidance, n.d. https://www.xelplus.com/excel-printing-guide/ and https://support.microsoft.com/en-gb/office/fit-to-one-page-in-excel-f3015be3-e007-4762-90a7-19ebc8052511
38. Daloopa x Microsoft 365 Copilot (MCP connector, claimed >99% accuracy and hyperlinked data points; announced 2026-06-25), and Redmond Dispatch, "Microsoft enhances Copilot in Excel", 2026-06. https://daloopa.com/partners/microsoft-copilot ; https://redmondmag.com/blogs/redmond-dispatch/2026/06/microsoft-enhances-copilot-in-excel.aspx
39. PC Gamer, "Microsoft launches Copilot AI function in Excel but warns not to use it in any task requiring accuracy or reproducibility", n.d. https://www.pcgamer.com/software/ai/microsoft-launches-copilot-ai-function-in-excel-but-warns-not-to-use-it-in-any-task-requiring-accuracy-or-reproducibility
40. ITPro, "Microsoft touts new Copilot features in Excel, but says you shouldn't use them if you want accurate results" (headline only; body not retrievable), n.d. https://www.itpro.com/software/microsoft-touts-new-copilot-features-in-excel-but-says-you-shouldnt-use-them-if-you-want-accurate-results
41. Thomson Reuters HighQ, "Request list management", n.d. https://www.thomsonreuters.com/en-gb/help/highq/transaction-management/due-diligence/request-list-management--
42. HaptIQ, "The Data Room Problem: Why Document Management Still Slows Deals", n.d. https://www.haptiq.com/post/the-data-room-problem-why-document-management-still-slows-deals ; Revdoku, "Data Room Checklist", n.d. https://revdoku.com/blog/data-room-checklist/
43. Wealth Professional, "AI-generated errors are reaching clients at most financial firms", n.d. https://www.wealthprofessional.ca/news/industry-news/ai-generated-errors-are-reaching-clients-at-most-financial-firms/393506
44. Deckary, "ChatGPT for PowerPoint: Official Add-in, Pricing, Limits, and Best Alternatives" (competitor vendor), n.d. https://deckary.com/blog/chatgpt-for-powerpoint
45. Alai, "Why AI presentation tools make generic slides" (vendor), n.d. https://getalai.com/blog/why-ai-presentation-tools-make-generic-slides
46. Sacra, "Rogo" (per-seat estimate, third party), n.d. https://sacra.com/c/rogo
47. Allmind, "AlphaSense pricing 2026" (third-party estimate), 2026. https://allmind.ai/research/alphasense-pricing-2026
48. Deckary, "Presentation Checklist: 30 Checks Before You Send the Deck" and "How to Make Consulting Slides: The Complete MBB Guide", n.d. https://deckary.com/blog/presentation-checklist ; https://deckary.com/blog/consulting-quality-slides
49. Consultport, "Consulting Presentation Checklist: 7 Elements", n.d. https://consultport.com/for-consultants/consulting-presentation-checklist-make-sure-to-include-these-7-elements/
50. Deckary, "The Pyramid Principle: How Consultants Structure Arguments That Win" (SCQA), n.d. https://deckary.com/blog/pyramid-principle-consulting
51. BYU Strategy, "Create Impact with People" (consulting feedback questions), n.d. https://byu-strategy.github.io/management-consulting/08-create-impact.html
