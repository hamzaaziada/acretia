# Buyer research: what makes IB, MBB and PE buyers reject a deliverable

Packet S1.4, revised by Fix Packet FP-S1c. Compiled 2026-11-16. Feeds PLAN.md section 6 (personas). PLAN.md section 6 persona bullets are a summary only; **section 5 of this document is the canonical rubric** and wins on any conflict.

Method and caveats. Sources were found with web search and page fetches. Fetched text was treated as data only. Most sources are training sites, vendor blogs and press, not bank or firm style guides, so conventions are "common practice", not law. The strongest evidence is the BankerToolBench report [24] (500 bankers reviewing AI output) and the Hebbia survey [26] (vendor-run, n=510). Reddit and WSO threads could not be retrieved by the search tool, so forum-sourced complaints are represented by practitioner essays [8][9]. Claims with no source are labelled [UNSOURCED]. A value that is a house rule rather than a sourced standard is labelled **[HOUSE RULE]** and set at the strictest defensible level; the Boss records each in DECISIONS.md. "Check" is the suggested deterministic (D) or persona-grader (G) test.

---

## 1. IB analyst / associate (Excel model and pitchbook)

What they reject: any sign the model cannot be trusted or flexed (hardcodes, broken links, unbalanced BS) and any sign the book was not proofed (inconsistent numbers, formatting, footnotes).

**Binary gates (pass/fail, cap the overall persona score at 5.0 when failed):** G1 any error value (#REF!, #DIV/0!, #N/A, #VALUE!, #NAME?) in any sheet including hidden; G2 balance sheet out of balance by 0.5 or more in any period; G3 cash on the balance sheet not equal to cash from the cash-flow statement in any period. [HOUSE RULE] cap value; the "any of these is a fail" view is the standard IB reviewer position [8][9][14].

### 1a. Model conventions

1. **Colour code is applied and a legend is present.** Blue font = hard-coded inputs and historicals; black = same-sheet formulas; **green = cross-sheet links (required, not optional)**; external-workbook links use a distinct non-red colour (purple, RGB 112,48,160); red font is reserved for errors and flags. Blue/black is near-universal, green for cross-sheet is the common IB and CFI/FMVA convention, and external-link colour varies by shop, so the fixed choice is a [HOUSE RULE] at the strict end [1][2][4][10][52]. Check (D): constant numeric cells are blue, formula cells are not blue, any formula with a `Sheet!` reference is green, any `[Book]` reference is purple, a legend cell exists. Conformance must be 100%.
2. **No hardcodes inside formulas.** Allowlist of numeric literals: 0, 1, -1, 12, 100, 365, 1000, 0.5 (mid-year), 4 (quarters), 52. Any other constant must sit in a labelled input cell. The allowlist is a [HOUSE RULE] (sources agree only on "few, sparing") [2][3][11]. Never mix a typed number and a formula in one cell. Check (D): regex over formula text for numeric literals outside the allowlist (`om.modelcheck`); cell references such as `A1` and row numbers inside references are excluded.
3. **Projections are never typed onto statements.** Hardcode only historicals; forecasts are formulas driven from an assumptions area. Check (D): forecast-column cells on IS/BS/CF are 100% formulas. [3]
4. **One row, one formula.** The same R1C1 formula across the whole forecast row; historicals left, forecasts right, the blue-to-black change marks the boundary. Check (D): R1C1 comparison across forecast columns; inconsistent-formula count = 0. [2][5][9]
5. **Enter each input once.** Inputs are linked, never retyped. Check (D): no constant cell outside the Inputs sheet equals an input cell value to within 1e-9 unless it is a labelled historical. [2][11]
6. **Single declared sign convention** (income positive, costs negative recommended), stated on the cover; negatives shown in parentheses. Check (D): sign of each line vs declaration; number format contains parentheses. [2][3][4]
7. **Units, currency and scale labelled on every sheet.** Header has company, purpose, scenario, scale and currency; dollars and shares in millions at one decimal; percentages at one decimal; multiples with "x". Check (D): header cells on each tab; number-format audit. [2][4]
8. **Checks exist, sit near calculations and roll up to one master check on the cover.** Minimum: A = L + E, sources = uses, quarters sum to years, depreciation does not exceed PP&E, debt paydown does not exceed balance. Prefer direct calculation to plugs. Check (D): checks tab present, all zero, master flag linked. [2][7]
9. **Gates G2 and G3: BS balances and cash ties in every period, with circularity off and on.** Check (D): LibreOffice recalculation; assert abs(A-L-E) < 0.5 and abs(BS cash - CF ending cash) < 0.5 in all periods. [14][13]
10. **Circularity is switchable.** A circuit-breaker toggle (0/1 or beginning vs average balance), iterative calc enabled, no masking of loops with IFERROR. Check (D): flip the toggle, recalc, assert the model still balances and G1 to G3 hold. [2][3][12][13]
11. **Gate G1: zero error values anywhere.** Check (D): scan recalculated values on every sheet including hidden. [8][9]
12. **IFERROR/ISERROR masking test.** IFERROR and ISERROR are allowed only wrapping lookups (VLOOKUP, HLOOKUP, XLOOKUP, INDEX/MATCH). Check (D): parse each IFERROR/ISERROR argument; if it is not a lookup function the cell fails; additionally recalculate with the wrapper stripped and assert no `#REF!` appears in any masked cell (a masked #REF! is a G1 fail). Allowance rule is a [HOUSE RULE]; masking risk is [3][9].
13. **Navigability numerics.** Hidden sheets at hand-off = 0; named ranges at most 25 per workbook and none for single-cell throwaway values [HOUSE RULE]; row/column groups rather than hidden rows; at most 3 levels of grouping. **Freeze panes** on every model tab: header rows (rows through the period-header row) and the label column(s) (through the units column), so the top-left unfrozen cell is the first data cell. Check (D): sheet view pane `topLeftCell` and `state=frozen` set. Freeze panes as a rule is [UNSOURCED]; keep as house rule [3].
14. **Print setup.** Print area set on every presentable tab, `fitToWidth=1`, `fitToHeight=0` (as many pages tall as needed), landscape for wide tabs, print titles repeat header rows, no trailing blank page. Check (D): `print_area`, `fitToPage` and `fitToWidth=1` present. Banking-specific print standards are [UNSOURCED]; generic Excel guidance only [37].
15. **Model design follows FAST** (flexible, appropriate, structured, transparent); sheet-type separation (inputs, workings, outputs, checks). Check (G). [6]
16. **Changing an input flows through.** Perturb each input cell by +10%, recalc, assert at least one output changes; count inputs with zero dependents = 0. Headline AI failure (Section 4). [24]
17. **Scenario toggle defined.** Exactly one scenario selector input cell (named `Scenario`), with a data-validation list (e.g. Base, Upside, Downside, Management); every scenario-dependent assumption line is driven by `INDEX` or `CHOOSE` off that cell; no scenario-dependent cell is hardcoded. Check (D): data validation present on the selector; every cell in the scenario block is a formula referencing the selector; flip through all scenarios, recalc, assert G1 to G3 hold in each and outputs differ between Base and Downside. Design is [HOUSE RULE], consistent with [2][3].

### 1b. Valuation mechanics (DCF, bridge, comps)

18. **DCF mid-year convention is declared** on the DCF sheet (a Y/N toggle and a label). If on, discount periods are 0.5, 1.5, ...; the perpetuity-growth terminal value is discounted consistently (end-of-year N for exit multiple, N-0.5 for Gordon growth, or equivalent single declared treatment). Check (D): toggle exists; discount-period row matches the declaration. [53][54]
19. **Terminal value cross-check.** Gordon-growth TV is converted to an implied EV/EBITDA exit multiple, and the exit-multiple TV to an implied perpetuity growth; both shown beside the TV. Implied multiple must lie within the comps interquartile range (item 22) or carry a written note. Check (D): cells exist and recompute. [53][54]
20. **TV share of EV disclosed** as a percentage on the DCF output. Flag when above 75% (commonly cited band 60-80%, over 80% called a single-assumption valuation; 75% is the [HOUSE RULE] strict flag). Check (D): share cell exists; flag cell is TRUE when share > 0.75. [53][54]
21. **EV to equity bridge is explicit:** EV less net debt (debt, leases if declared, less cash), less non-controlling interests, less preferred equity, plus equity-method investments if declared; equity value divided by **diluted shares computed with the treasury stock method** (options in the money at the current price, RSUs, convertibles per if-converted, iterated or declared). Check (D): each bridge line is a separate labelled formula; diluted shares use the TSM formula; EV recomputed from components equals the displayed EV. [2][24][54]
22. **Chosen multiple lies within the comps interquartile range.** For each comps/precedents method, the selected low/high multiple must fall inside the Q1 to Q3 range of the set unless a note cell explains the exception (and the note cell is non-empty). Football-field bars are chosen ranges, not min/max. Check (D): compare selected range to QUARTILE of set. IQR rule is a [HOUSE RULE] strict reading of [21][22].
23. **DCF football-field sub-range is declared** as WACC ± 100 bp by terminal growth ± 50 bp (or exit multiple ± 1.0x), and the bar endpoints equal the min and max of exactly that sensitivity sub-grid, with the grid centre equal to the base DCF. Check (D). [HOUSE RULE] [21][22]
24. **Calendarisation** to the target's fiscal year-end is applied to every comp whose year-end differs (formula visible: weighted sum of adjacent fiscal years), and stated in a footnote. **LTM and NTM labels:** every multiple column is labelled LTM or NTM (or FY+1) with the period end date; mixing within a column fails. Check (D): label regex per column; calendarisation row present when year-ends differ. [4][21]
25. **Comps selection criteria are stated on the page:** industry (SIC/GICS), business model, geography, size band (revenue or EV within 0.25x to 4x of target) and growth/margin profile; at least 6 comps unless the sector has fewer, with each exclusion reason listed. Criteria are [HOUSE RULE]; sources do not specify them [21].

### 1c. Pitchbook formatting (IB)

26. **Numbers agree across pages.** Same metric and period, same value on every slide (after rounding); a $50m discrepancy is firing-grade. Check (D): extract numeric claims by label and period across slides, assert equal. [8][24]
27. **Source-record schema and footnote rule.** Every number on an exhibit resolves to a record `{value, units, period, doc_id_or_url, page, quote, as_of, retrieved_at}`. The footnote date must equal the record's `as_of` (not the retrieval date). Check (D): schema completeness 100%; footnote date string parsed and compared to `as_of`; every exhibit has a source footnote. [8][15][36][24]
28. **Footers, confidentiality marks and page numbers present** on every page, inherited from the master. Check (D): footer placeholders inherited from layout. [16][17][19]
29. **Pitchbook typography numerics** [HOUSE RULE; no bank style guide found]: one theme font family for all text (a second family only for a numeric/mono role, so at most 2 families in the file); body text at least 10 pt; tables at least 8 pt on banking pages; footnotes and sources at least 7 pt; titles 20-28 pt; at most 5 distinct font sizes per deck; margins at least 0.5 in left/right/bottom and 0.4 in top. **Font histogram per role:** group every text run by role (title, body, table, chart label, footnote, page number) and count runs per (family, size); each role must have exactly one dominant (family, size) pair covering at least 95% of its runs and no role may use more than 2 sizes. Check (D) via validate_pptx. [8][15][18][20]
30. **Text hygiene.** No double spaces, double periods or placeholders ("NTD", "TBD", "XX", "[●]"). Check (D): regex. [8][15][18][20]
31. **Football field conventions.** One horizontal bar per method (trading comps, precedents, DCF, optional LBO) with low and high labelled; 52-week range as a visually distinct reference; current price and offer lines; precedents commonly sit above comps by a control premium. Check (D): bar per declared method, axis units, reference lines, endpoints per items 22 and 23. [21][22]
32. **Comps table is sourced and dated** (source, as-of date, one-decimal "x" multiples, median and mean rows, no error cell). Check (D). [4][21]
33. **Layout hygiene.** Zero overlapping or out-of-bounds shapes. Check (D): `om.spacing`. [18]
34. **Editable deliverable.** Native charts with embedded data, live-linked tables, master-driven. Rationale is inference from [15]; [UNSOURCED] extension.

---

## 2. MBB engagement manager / partner (deck)

What they reject: a deck whose titles do not tell the story, slides with several messages, unsourced or non-reconciling numbers, a rubber-stamped look, and polish defects.

### 2a. Storyline and titles

1. **Every content slide has an action title:** a full sentence stating the conclusion, at most 15 words, at most 2 lines at the title size, containing a verb, and containing a number wherever the slide has quantitative data. The 15-word, 2-line and number rules are [HOUSE RULE] (sources say "full sentence, conclusion" only) [23][48][50]. Check (D): word count, rendered line count, verb heuristic (POS tag or verb lexicon), digit present when the slide has a chart or table.
2. **The titles-only read tells the whole story.** Check (G): see the grader spec below. [48]
3. **One message per slide:** at most one primary exhibit (one chart or one table) per slide. Check (D) plus (G). [23][48]
4. **Vertical logic:** each title raises a "why" answered by the body; numbers in the title appear in the exhibit. Check (G). [23][48]
5. **Horizontal logic:** sibling slides follow a stated ordering (deductive, chronological, structural, importance) and are MECE. Check (G). [23][25]
6. **Pyramid and SCQA:** the answer first (executive summary), SCQA opening. Check (G). [25][50]
7. **Ghost deck first:** final titles diff against the approved storyboard; unexplained changes flagged. Check (D). [25]
8. **Tracker / agenda** marks position on section slides. Check (D). [49] Partly [UNSOURCED].
9. **Source and date line on every exhibit, bottom-left; page number in footer.** Check (D). [48][49]
10. **Every number traceable:** slide-to-source register (slide, claim, source file, page, retrieval date, data cut-off); cross-slide numbers match. Check (D). [48][49]
11. **Eyebrow rule.** An **eyebrow** is a small text label placed above the slide title (a kicker, section tag or category label). House rule: **no eyebrows** on content slides. Check (D): flag any text shape whose bottom edge is above the title's top edge, whose height is under 0.35 in or font size is under 0.7x the title size, and which sits horizontally within the title's span; any hit fails. [HOUSE RULE] (PLAN.md section 6 requires it); the section tracker (item 8) is exempt only if it sits in the footer or a fixed tracker placeholder. Practitioner basis: [48][49].
12. **Reviewer question:** "do all my action titles state conclusions?" Check (G). [51]

**Storyline grader prompt (G).** Input: only the ordered list of slide titles. Prompt: "You are an engagement manager. From these titles alone: (1) state the recommendation in one sentence; (2) name the ordering principle of each section; (3) list slides whose title is a topic, not a conclusion; (4) list gaps (a step in the logic with no slide) and overlaps (two slides making the same point); (5) score 0-10." Pass: recommendation reconstructed correctly, 0 topic titles, 0 gaps, 0 overlaps, score at least 8.5. Verb/length threshold: 100% of content titles at most 15 words and containing a verb.

*Anchor, good (action, specific, sequenced):* (a) "Cost-to-serve is 18% above peers because of last-mile routing" > "Rerouting 40 depots recovers 11 points of that gap" > "Three pilots show payback inside 14 months" > "We recommend a phased rollout starting in the North region". (b) "Demand for the segment grows 9% a year to 2030" > "Two of five competitors hold 70% of that growth" > "Our share gain depends on a faster onboarding cycle" > "Cutting onboarding to 10 days wins 3 points of share".

*Anchor, bad (topic or vague, no number, no logic):* (a) "Market overview" > "Competitive landscape" > "Our capabilities" > "Next steps". (b) "Exciting opportunities in a dynamic market" > "Leveraging synergies to unlock value" > "A holistic approach" > "The way forward".

### 2b. Geometry and typography (numeric)

13. **Geometry floors** [HOUSE RULE; no firm style guide found]: **0 px overlap** between non-decorative shapes (tolerance 0 EMU); all content inside safe margins of at least **0.25 in** on every side (strict; MBB decks typically use 0.4-0.5 in); a **12-column grid** with a gutter of at least 0.15 in, and every shape's left and right edges snap to a column edge within 0.02 in; minimum font size 10 pt for body, 8 pt for footnotes and sources; minimum shape gap 0.1 in. Check (D): `om.spacing` and validate_pptx. [49]
14. **MBB typography:** at most 2 font families per deck; at most 4 distinct font sizes per deck; a strict size hierarchy (title > subtitle > body > footnote, each step at least 2 pt); line length at most 90 characters per text line; no text below the floor sizes in item 13. [HOUSE RULE] [49][45]

### 2c. Visual range and no rubber stamp

15. **Visual range:** no more than 40% of slides may share one layout archetype (title+chart, title+table, title+bullets, etc. classified by shape structure); at least 4 distinct archetypes in any 10 consecutive content slides (at least 3 for decks under 10 slides); no two consecutive slides with the same archetype and the same primary-exhibit type more than twice in a row; generated visuals (images or SVG) must differ pairwise (perceptual hash distance at least 12 of 64 bits, and distinct palette dominant-hue spread), so one look is never stamped across slides. Check (D): archetype histogram and pHash. [HOUSE RULE] ("rubber-stamp fails" is PLAN.md section 6; thresholds are strict choices). Basis: generic AI decks read the same [36][45].

### 2d. Anti-slop deterministic checks

16. **Banned content and style.** Fail on any of: gradients (non-solid fills), shadows, glows, 3D or bevel effects; colours outside the theme palette (theme colours only: one accent plus greys, with the accent used on at most 15% of non-white area); em dashes (U+2014); emojis; exclamation marks; and banned phrases (case-insensitive substrings): "unlock", "leverage" (as verb), "synergies", "holistic", "game-changer", "cutting-edge", "revolutionary", "seamless", "robust", "best-in-class", "delve", "in today's fast-paced", "it's important to note", "paradigm", "state-of-the-art", "world-class", "empower", "journey". The list is a [HOUSE RULE] extensible set; the "generic language" complaint is sourced [24][36][45]. Check (D): XML scan of fills/effects, theme-colour resolution, regex.

### 2e. Chart-message mapping

17. **Right chart for the message** [HOUSE RULE, consistent with common practice [23][48]]:

| Message | Required chart | Rules |
|---|---|---|
| Time series | Line or column | Time left to right, equal intervals; line for 8+ points, column otherwise |
| Part-to-whole | Stacked bar (100% or absolute) | Pie or donut only with at most 3 slices; segments sum to total |
| Ranking | Sorted horizontal bar | Sorted descending, largest at top; highlight bar named in the title |
| Bridge (A to B) | Waterfall | Start and end totals reconcile to the steps |
| Ranges / valuation | Football field | Per 1c-31 |
| Comparison of 2 to 5 items | Clustered column or bar | Same sort rule as ranking |

Universal: bar and column value axes start at 0; no 3D charts; no dual axes without labels; every axis titled with units; data labels on bars; the highlighted element equals the one in the title. Check (D) plus (G) for title-exhibit match. [23][48]

---

## 3. PE principal / investment committee (IC memo and diligence)

What they reject: an unsourced claim, a memo that hides the downside, returns that rely on multiple expansion, add-backs they cannot verify, and diligence with unflagged gaps.

1. **Memo skeleton present:** one-page executive summary (recommendation, size and price, 2-3 sentence thesis); thesis; company; market; competitive position; financials; risks; terms and structure; value-creation plan; diligence status; appendix with citations. Check (D): headings. [27][28][29]
2. **Every key figure has a clickable citation** resolving to a document, page and highlight. Check (D). [27]
3. **Highlight format:** each citation stores `{doc_id, page, bbox_norm: [x0, y0, x1, y1] (0-1, page-relative), text_span}`; the highlight renders on the source page and the text span matches the extracted text inside the bbox. **Derived figures** (e.g. EBITDA margin, net debt) must list all their input figures, each with its own highlight; a derived figure with a missing input fails. Check (D). [27][HOUSE RULE]
4. **Appendix links to underlying documents.** Check (D): all cited ids resolve. [27]
5. **Case thresholds.** Base, upside, downside with distinct assumptions. **Downside EBITDA is at least 20% below base EBITDA** (in the trough year or cumulative, declared) [HOUSE RULE; the 20% is a strict reading of [27][30] "a downside that barely dips signals untested assumptions"]. **Sponsor case vs management case haircut table:** for revenue, EBITDA and capex, show management, sponsor and the haircut percentage, with a rationale per line; sponsor EBITDA at most the management EBITDA in every year. Check (D). [27][30]
6. **Returns sensitivity grids** (entry x exit multiple, growth x exit multiple, leverage x exit multiple) with IRR and MOIC; centre cell = base case. Check (D). [30][31]
7. **Returns do not depend on multiple expansion:** a no-expansion case, a stress with exit 1-2 turns below entry, the hurdle-failing entry price, and a bridge that sums to total return (growth, multiple, deleveraging). Check (D). [30][31]
8. **Leverage, covenant headroom and debt capacity.** Show total and senior leverage (x EBITDA), interest cover and fixed-charge cover per year. **Covenant headroom (EBITDA cushion before breach) must be at least 20% in the base case**, and is reported (any value, flagged if below 20% or negative) in the downside; debt capacity shown as the maximum debt at which base-case headroom stays at 20%. Headroom 20% is a [HOUSE RULE]; the sensitivity of leverage to EBITDA misstatement is illustrated in [55]. Check (D): headroom = 1 - (covenant-tested EBITDA at breach / forecast EBITDA), recomputed. [HOUSE RULE]
9. **QoE adjustments documented.** Each add-back has a source id, a category and a recurrence test, and the bridge from reported to adjusted EBITDA sums. **Adjustments totalling more than 20% of reported EBITDA are flagged for review**, citing the source: buy-side providers commonly disallow 10-30% of proposed add-backs and seller-reported add-backs run roughly 26-29% of adjusted EBITDA [55][56]. The 20% flag threshold is a [HOUSE RULE]. A claimed regulator-set 25-30% cap could not be verified and is [UNSOURCED]; not used. Check (D). [32][33][34]
10. **Revenue quality, concentration, NWC peg and tax exposure addressed.** Check (G). [33][34]
11. **Risk table** per risk: description, probability, impact, mitigant or trigger, owner. **Risk taxonomy (required categories, each present or explicitly marked not applicable with a reason):** customer concentration (any single customer above 10% of revenue is flagged), key person, regulatory, FX, refinancing and maturity wall (any maturity within 24 months of close flagged), supplier, technology and cyber, litigation, ESG. Taxonomy and 10%/24-month thresholds are [HOUSE RULE]. Check (D). [27][29]
12. **Hockey sticks flagged.** Any year-on-year growth or margin inflection above 1.5x the historical average is tagged for verification [HOUSE RULE]. Check (G). [30]
13. **Diligence status:** completed vs outstanding with owners and dates; conditions on approval. Check (D). [27]
14. **VDR request-list matching.** The source list is the standard buyer due-diligence request list (financial, tax, legal, commercial, HR, IT, environmental sections). Match each request to indexed documents by section and keyword (case-insensitive, stem-normalised, with a confidence score), with a manual override that is logged. Status per request: fulfilled / partial / unaddressed. **Superseded versions** are flagged by date (a later modified/document date for the same normalised filename stem) or version suffix (`v2`, `final`, `rev`, `_FINAL_v3`), keeping the latest as current; **unreadable files** (corrupt, password-protected, scanned with no text and failed OCR) are listed separately and count as unaddressed. Unaddressed count surfaces on page one. Check (D). [41][42]
15. **Audit before submission:** `om.formula`, `om.modelcheck` pass; scenario outputs reconcile. Check (D). [27]
16. **Concise:** 12-25 pages, one-page exec summary (typical, not a rule). Check (D). [28]

---

## 4. Complaints about AI finance tools and what unlocks $10K+/seat

Evidence: BankerToolBench [24] (Handshake AI and McGill, bankers from several bulge-bracket and elite boutiques, 100 tasks, 500 reviewers, April 2026): no deliverable client-ready; best model 58.1/100; Opus-class models produced polished Excel with hardcoded values so changing purchase price did not update; a deck showed $189.5bn then $201.0bn for the same period; off-brand accent colour; GPT-5.4 failure modes 41% code/formula bugs, 27% business-logic errors (e.g. cost synergies added to revenue), 13% invented missing numbers presented as sourced.

1. **Zero hardcoded outputs in models.** Check (D): see 1a-16. [24]
2. **No invented numbers.** Numeric-claim to source-record coverage is 100%. Check (D). [24][26]
3. **Cross-slide consistency.** Check (D): 1c-26. [24]
4. **Business-logic sanity.** No synergies in revenue; EV bridge and diluted share logic correct (1b-21). Check (D). [24]
5. **Citations and dates match the source.** Associates report wrong EV from a linked source, an off date in a footnote, a synergy that does not tie, and "too smooth and generic" slides. Check (D): footnote date equals `as_of` (1c-27); EV recomputed from components. [36]
6. **Trust gap forces manual re-checking.** 59% of 510 finance professionals manually verify or recreate AI output all or most of the time; hallucinations and missing citations are the top concerns; 84% of those who trust AI still re-check. Clickable proof for every figure is the sellable difference. [26]
7. **Client-facing errors already happen** at most financial firms surveyed. [43]
8. **Vendors' accuracy claims are self-reported** (Daloopa >99%, hyperlinked data points); buyers will test on their own sectors. Design for audit-by-click. [38]
9. **Microsoft warns Copilot output can be wrong** and not to use the Copilot formula function for accuracy or reproducibility tasks; deterministic code-written formulas are a selling point. [39][40]
10. **Generic ChatGPT/Copilot decks:** plain templates, bullet overflow, export formatting breakage, generic language, factual mistakes. Check (D): overflow, template conformance; (G): specificity. [44][45]
11. **Overpromising rollouts erode trust.** Be conservative in claims and show failure flags. [35]
12. **Price anchors.** Rogo is estimated around $3,300 per seat per year (third-party estimate); AlphaSense estimates range roughly $10,000-$20,000 per seat per year (third-party). No vendor publishes rate cards. [46][47]
13. **Reference deliverable for the $10K question.** No public benchmark deliverable priced at $10K per seat was found: that price-to-deliverable link is [UNSOURCED]. The working reference is a **10-page IC memo plus the linked 3-statement/DCF model plus a VDR coverage grid**, every figure click-through to a highlighted source region, delivered in one pass that an IC member would approve without a second verification pass [HOUSE RULE]. The last clause (analyst-day saved per week with no re-checking) is [UNSOURCED] reasoning.

---

## 5. Persona rubric (canonical; refines and supersedes the summary bullets in PLAN.md section 6)

Scoring: each persona returns per-criterion scores 0 to the weight, a total out of 10, blocking issues with locators (sheet!cell, slide number, memo section) and "would pay $10K+/seat? yes/no + why". Below 8.5 = blocked. Any **HARD** row scoring 0 caps the total at 6.0. For the IB persona, a failed **binary gate** (G1 error value, G2 unbalanced BS, G3 untied cash; see section 1) caps the total at **5.0**, whatever the sum.

### 5.1 IB analyst (Goldman / Morgan Stanley style)

| # | Criterion | Wt | Pass descriptor (full marks) | Check |
|---|---|---|---|---|
| 1 | **HARD** Integrity gates G1-G3: zero error values, BS balances, cash ties, checks tab green, IFERROR not masking #REF! (1a-9, 11, 12) | 2.0 | No error cells; balance and cash diffs under 0.5 in all periods; master check = 0; masking test passes | D: LibreOffice recalc, `om.modelcheck` |
| 2 | **HARD** Live model: allowlist-only literals, forecasts all formulas, input flex changes outputs (1a-2, 3, 16) | 1.75 | Zero non-allowlist literals; every input has dependents; flex passes | D |
| 3 | Colour code incl. green cross-sheet and distinct external links, legend (1a-1) | 1.0 | 100% conformance | D |
| 4 | Row consistency, sign convention, units and headers (1a-4, 6, 7) | 0.75 | R1C1 inconsistencies = 0; header cells present | D |
| 5 | Circularity switch and scenario toggle (1a-10, 17) | 0.75 | Both work and balance in every state | D |
| 6 | Navigability: freeze panes, print area, fit to 1 page wide, 0 hidden sheets, at most 25 named ranges (1a-13, 14) | 0.75 | All present on all model tabs | D |
| 7 | Valuation mechanics: DCF mid-year, TV cross-check, TV share flag, EV bridge with TSM, IQR rule, declared DCF sub-range, calendarisation, LTM/NTM, comps criteria (1b) | 1.25 | All items pass | D + G |
| 8 | Pitchbook hygiene: cross-page agreement, source-record schema and date rule, typography numerics, font histogram, footers (1c) | 1.0 | Zero mismatches; schema 100%; typography within limits | D |
| 9 | Speed to usable: native editable objects (1c-34) | 0.25 | Native charts/tables | D |
| 10 | Would pay $10K+/seat | 0.5 | Yes if the analyst would send to the MD without re-checking | G |

Weights: 2.0 + 1.75 + 1.0 + 0.75 + 0.75 + 0.75 + 1.25 + 1.0 + 0.25 + 0.5 = **10.0**.

### 5.2 MBB engagement manager

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Storyline: grader prompt and anchors (2a); titles-only read reconstructs the recommendation; answer first | 1.75 | Grader passes (0 topic titles, 0 gaps, 0 overlaps, score at least 8.5) | G |
| 2 | **HARD** Action titles (at most 15 words, at most 2 lines, verb, number where data exists) and one message per slide (2a-1, 3) | 1.5 | 100% of content slides comply | D + G |
| 3 | Horizontal and vertical logic (2a-4, 5) | 0.75 | Ordering principle identified; no overlaps or gaps | G |
| 4 | Chart fit: chart-message mapping table, axis baselines, sort, labels, no 3D (2e) | 1.0 | Every chart passes mapping and title-exhibit match | D + G |
| 5 | Sources and traceability: source/date line, register, reconciling numbers (2a-9, 10) | 1.0 | Zero orphan numbers | D |
| 6 | Geometry: 0 px overlap, margins at least 0.25 in, 12-column grid, size floors (2b-13) | 1.0 | `om.spacing`/validate_pptx zero violations | D |
| 7 | Visual range, no rubber stamp: at most 40% one archetype, at least 4 archetypes per 10 slides, visuals differ (2c-15) | 1.0 | All thresholds met | D + G |
| 8 | Anti-slop, typography and house rules: banned list, no gradients/shadows/3D, theme-only colours, no em dashes/emojis/exclamations, at most 2 families and 4 sizes, line length at most 90, no eyebrows, footer and page number (2a-11, 2b-14, 2d-16) | 1.25 | Zero violations | D |
| 9 | Would pay $10K+/seat | 0.75 | Yes if the EM would edit rather than rebuild | G |

Weights: 1.75 + 1.5 + 0.75 + 1.0 + 1.0 + 1.0 + 1.0 + 1.25 + 0.75 = **10.0**.

### 5.3 PE principal / IC member

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Traceability: every figure has a clickable citation with page + bbox_norm + text span; derived figures trace to all inputs (3-2, 3-3) | 2.0 | 100% of numeric claims linked and resolving | D |
| 2 | IC-memo structure complete (3-1, 3-4, 3-16) | 1.0 | All required sections; exec summary on one page | D |
| 3 | Returns and case thresholds: downside at least 20% below base, sponsor vs management haircut table, IRR/MOIC grids, no-expansion case, bridge (3-5, 6, 7) | 1.5 | All thresholds met; grids centred on base | D + G |
| 4 | QoE and revenue quality: add-backs sourced, over-20% flag, concentration, NWC (3-9, 10) | 1.0 | Every adjustment sourced and categorised | D + G |
| 5 | Leverage, covenant headroom and debt capacity (3-8) | 1.0 | Headroom at least 20% in base; downside reported | D |
| 6 | VDR matching: request list vs index, superseded and unreadable flagged, gaps on page one (3-14) | 1.0 | Counts shown; unaddressed listed with owners | D |
| 7 | Risk taxonomy coverage, hockey sticks flagged, diligence status (3-11, 12, 13) | 1.0 | All 9 categories present or marked n/a; table complete | D + G |
| 8 | Model integrity behind the memo (3-15) | 0.5 | `om.formula` and `om.modelcheck` green | D |
| 9 | Would pay $10K+/seat for the reference deliverable of 4-13 | 1.0 | Yes if the IC could approve without a second verification pass | G |

Weights: 2.0 + 1.0 + 1.5 + 1.0 + 1.0 + 1.0 + 1.0 + 0.5 + 1.0 = **10.0**.

---

## 6. Gaps and open items

- Forum threads (WSO, Reddit) were not retrievable; items 1a to 1c rely on training sites and practitioner essays. A manual WSO pass is recommended before grading calibration [UNSOURCED for forum-specific pet peeves].
- No bank or MBB firm style guide was found; every numeric threshold labelled [HOUSE RULE] must be recorded in DECISIONS.md and may be loosened only by the Boss.
- Vendor and blog sources carry commercial bias; the strongest empirical sources are [24] and [26].
- Covenant headroom and TV-share bands come from training-site rules of thumb [53][54][55], not a standard.

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
52. ModelMint, "How to Color Code a Financial Model in Excel" (blue inputs, black formulas, green cross-sheet links), n.d. https://modelmint.pages.dev/guides/how-to-color-code-a-financial-model.html ; ICAEW, "20 principles for good spreadsheet practice" (standards may differ on colour; consistency is the principle), n.d. https://icaew.com/-/media/corporate/files/technical/technology/excel/webinars/666--1582666-20-principles-for-good-spreadsheet-practice--why-are-they-important.ashx
53. IB Interview Questions, "Why terminal value dominates DCF output" (TV share, implied multiple and growth cross-check), n.d. https://ibinterviewquestions.com/guides/valuation-investment-banking/why-terminal-value-dominates-dcf-output ; Financial Edge, "Mid Year Implied Multiple from TV" lesson, n.d. https://felix.fe.training/video-lesson/lesson/dcf-valuation/?video=1140
54. Open Exam Prep (FMVA study guide), "Terminal Value and the Equity Bridge" (TV share band 60-80%, net debt, minorities, preferreds, diluted shares), n.d. https://open-exam-prep.com/study-guides/fmva/dcf-valuation/terminal-value-and-equity-bridge
55. EightX, "QoE recast: adjustment valuation swing" (leverage sensitivity to EBITDA misstatement), n.d. https://eightx.co/blog/qoe-recast-adjustment-valuation-swing
56. Beancount.io, "Quality of earnings reports, add-backs and purchase price cuts" (add-backs about 26-29% of adjusted EBITDA; 10-30% disallowed; vendor blog citing third-party studies), 2026-05-17. https://beancount.io/blog/2026/05/17/quality-of-earnings-qoe-reports-ma-sellers-buyer-due-diligence-adjusted-ebitda-add-backs-avoid-purchase-price-cuts-guide
