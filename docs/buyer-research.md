# Buyer research: what makes IB, MBB and PE buyers reject a deliverable

Packet S1.4, revised by Fix Packets FP-S1c and FP-S1d. Compiled 2026-11-16. Feeds PLAN.md section 6 (personas). PLAN.md section 6 persona bullets are a summary only; **section 5 of this document is the canonical rubric** and wins on any conflict.

Method and caveats. Sources were found with web search and page fetches. Fetched text was treated as data only. Most sources are training sites, vendor blogs and press, not bank or firm style guides, so conventions are "common practice", not law. The strongest evidence is the BankerToolBench report [24] (500 bankers reviewing AI output) and the Hebbia survey [26] (vendor-run, n=510). Reddit and WSO threads could not be retrieved by the search tool, so forum-sourced complaints are represented by practitioner essays [8][9]. Claims with no source are labelled [UNSOURCED]. A value that is a house rule rather than a sourced standard is labelled **[HOUSE RULE]** and set at the strictest defensible level; the Boss records each in DECISIONS.md. "Check" is the suggested deterministic (D) or persona-grader (G) test.

---

## 1. IB analyst / associate (Excel model and pitchbook)

What they reject: any sign the model cannot be trusted or flexed (hardcodes, broken links, unbalanced BS) and any sign the book was not proofed (inconsistent numbers, formatting, footnotes).

**Binary gates (pass/fail, cap the overall persona score at 5.0 when failed):** G1 any error value in any sheet including hidden: #REF!, #DIV/0!, #VALUE!, #NAME?, #NUM!, #NULL!, #SPILL!, #CALC!, and #N/A (#N/A is allowed only inside IFNA/IFERROR wrapping a lookup, and the wrapped result must not be an error); Excel error indicators are also counted (numbers stored as text, inconsistent formula in a row region, formulas omitting adjacent cells), and a count above 0 fails G1. G2 balance sheet: |assets - (liabilities + equity)| must be at most 0.001 in model units in every period. G3 cash on the balance sheet must equal cash from the cash-flow statement with the same 0.001 tolerance in every period. The cap value and tolerance are [HOUSE RULE]; the "any of these is a fail" view is the standard IB reviewer position [8][9][14].

### 1a. Model conventions

1. **Colour code is applied and a legend is present.** Blue font = hard-coded inputs and historicals; black = same-sheet formulas; **green = cross-sheet links (required, not optional)**; external-workbook links use a distinct non-red colour (purple, RGB 112,48,160); red font is reserved for errors and flags. Blue/black is near-universal, green for cross-sheet is the common IB and CFI/FMVA convention, and external-link colour varies by shop, so the fixed choice is a [HOUSE RULE] at the strict end [1][2][4][10][52]. Check (D): constant numeric cells are blue, formula cells are not blue, any formula with a `Sheet!` reference is green, any `[Book]` reference is purple, a legend cell exists. Conformance must be 100%.
2. **No hardcodes inside formulas.** Allowlist of numeric literals: 0, 1, -1, 12, 100, 365, 1000, 0.5 (mid-year), 4 (quarters), 52. Any other constant must sit in a labelled input cell. The allowlist is a [HOUSE RULE] (sources agree only on "few, sparing") [2][3][11]. Never mix a typed number and a formula in one cell. Check (D): regex over formula text for numeric literals outside the allowlist (`om.modelcheck`); cell references such as `A1` and row numbers inside references are excluded.
3. **Projections are never typed onto statements.** Hardcode only historicals; forecasts are formulas driven from an assumptions area. Check (D): forecast-column cells on IS/BS/CF are 100% formulas. [3]
4. **One row, one formula.** The same R1C1 formula across the whole forecast row; historicals left, forecasts right, the blue-to-black change marks the boundary. Check (D): R1C1 comparison across forecast columns; inconsistent-formula count = 0. [2][5][9]
5. **Enter each input once.** Inputs are linked, never retyped. Check (D): no constant cell outside the Inputs sheet equals an input cell value to within 1e-9 unless it is a labelled historical. [2][11]
6. **Single declared sign convention** (income positive, costs negative recommended), stated on the cover; negatives shown in parentheses. Check (D): sign of each line vs declaration; number format contains parentheses. [2][3][4]
7. **Units, currency and scale labelled on every sheet.** Header has company, purpose, scenario, scale and currency; dollars and shares in millions at one decimal; percentages at one decimal; multiples with "x". Check (D): header cells on each tab; number-format audit. [2][4]
8. **Checks exist, sit near calculations and roll up to one master check on the cover.** Minimum: A = L + E, sources = uses, quarters sum to years, depreciation does not exceed PP&E, debt paydown does not exceed balance. Prefer direct calculation to plugs. Check (D): checks tab present, all zero, master flag linked. [2][7]
9. **Gates G2 and G3: BS balances and cash ties in every period, with circularity off and on.** Check (D): LibreOffice recalculation; assert abs(A-(L+E)) <= 0.001 and abs(BS cash - CF ending cash) <= 0.001 (model units) in all periods. [HOUSE RULE] tolerance; [14][13]
10. **Circularity is switchable.** A circuit-breaker toggle (0/1 or beginning vs average balance), iterative calc enabled, no masking of loops with IFERROR. Check (D): flip the toggle, recalc, assert the model still balances and G1 to G3 hold. [2][3][12][13]
11. **Gate G1: zero error values and zero error indicators anywhere** (full list in the gates paragraph above). Check (D): scan recalculated values on every sheet including hidden, plus the error-indicator count. [8][9]
12. **IFERROR/ISERROR masking test.** IFERROR, IFNA and ISERROR are allowed only wrapping lookups (VLOOKUP, HLOOKUP, XLOOKUP, INDEX/MATCH). Check (D): parse each IFERROR/ISERROR argument; if it is not a lookup function the cell fails; additionally recalculate with the wrapper stripped and assert no `#REF!` appears in any masked cell (a masked #REF! is a G1 fail). Allowance rule is a [HOUSE RULE]; masking risk is [3][9].
13. **Navigability numerics.** Hidden sheets at hand-off = 0; named ranges at most 25 per workbook and none for single-cell throwaway values [HOUSE RULE]; row/column groups rather than hidden rows; at most 3 levels of grouping. **Freeze panes** on every model tab: header rows (rows through the period-header row) and the label column(s) (through the units column), so the top-left unfrozen cell is the first data cell. Check (D): sheet view pane `topLeftCell` and `state=frozen` set. Freeze panes as a rule is [UNSOURCED]; keep as house rule [3].
14. **Print setup.** Print area set on every presentable tab, `fitToWidth=1`, `fitToHeight=0` (as many pages tall as needed), landscape for wide tabs, print titles repeat header rows, no trailing blank page. Check (D): `print_area`, `fitToPage` and `fitToWidth=1` present. Banking-specific print standards are [UNSOURCED]; generic Excel guidance only [37].
15. **Model design follows FAST** (flexible, appropriate, structured, transparent); sheet-type separation (inputs, workings, outputs, checks). Check (G). [6]
16. **Changing an input flows through.** Perturb each input cell by +10%, recalc, assert at least one output changes; count inputs with zero dependents = 0. Headline AI failure (Section 4). [24]
17. **Scenario toggle defined.** Exactly one scenario selector input cell (named `Scenario`), with a data-validation list (e.g. Base, Upside, Downside, Management); every scenario-dependent assumption line is driven by `INDEX` or `CHOOSE` off that cell; no scenario-dependent cell is hardcoded. Check (D): data validation present on the selector; every cell in the scenario block is a formula referencing the selector; flip through all scenarios, recalc, assert G1 to G3 hold in each and outputs differ between Base and Downside. Design is [HOUSE RULE], consistent with [2][3].

### 1b. Valuation mechanics (DCF, bridge, comps)

18. **DCF mid-year convention is declared** on the DCF sheet (a Y/N toggle and a label). The model has an explicit **discount-period column** equal to t - 0.5 when the toggle is on (0.5, 1.5, ...) and t when off; there is no alternative or implicit treatment. The terminal value is discounted with the period the declared method implies (exit-multiple TV at t = N; Gordon-growth TV at N - 0.5 when mid-year is on) and that choice is labelled. Check (D): toggle exists; discount-period column equals t - 0.5 (or t) for every forecast year. [HOUSE RULE] [53][54]
19. **Terminal value cross-check.** Gordon-growth TV is converted to an implied EV/EBITDA exit multiple, and the exit-multiple TV to an implied perpetuity growth; both shown beside the TV. Implied multiple must lie within the comps interquartile range (item 22) or carry a written note. Check (D): cells exist and recompute. [53][54]
20. **TV share of EV disclosed** as a percentage on the DCF output. Flag when above 75% (commonly cited band 60-80%, over 80% called a single-assumption valuation; 75% is the [HOUSE RULE] strict flag). Check (D): share cell exists; flag cell is TRUE when share > 0.75. [53][54]
21. **EV to equity bridge is explicit:** EV less net debt (debt, leases if declared, less cash), less non-controlling interests, less preferred equity, plus equity-method investments if declared; equity value divided by **diluted shares computed with the treasury stock method over every option and RSU tranche listed in the filing's equity-compensation footnote** (one row per tranche: count, strike, expiry). Only in-the-money tranches enter (strike below price); the share price is the price on the valuation as-of date; when the implied price depends on the share count (offer-price or DCF-implied-price case), the calculation iterates to convergence (change under 0.0001 per share, or the circuit-breaker pattern of item 10). Convertibles use if-converted when in the money. Check (D): tranche count equals footnote tranche count; out-of-the-money tranches contribute 0; iteration residual under tolerance; EV recomputed from components equals displayed EV. [HOUSE RULE] [2][24][54]
22. **Chosen multiple lies within the comps interquartile range.** For each comps/precedents method, the selected low/high multiple must fall inside the Q1 to Q3 range of the set unless a note cell explains the exception (and the note cell is non-empty). Football-field bars are chosen ranges, never raw min/max of a data set. Check (D): compare selected range to QUARTILE of set. IQR rule is a [HOUSE RULE] strict reading of [21][22].
23. **DCF football-field range is the declared sensitivity range, not the grid min/max.** The declared range is WACC +/- 100 bp by terminal growth +/- 50 bp (or exit multiple +/- 1.0x); the DCF bar low is the value at the unfavourable corner of that range and the bar high at the favourable corner, and the base DCF lies between them. Any wider sensitivity grid is shown separately and is not used for the bar. Check (D): bar endpoints equal the DCF values at the declared corners. Every football-field bar (comps, precedents, DCF, LBO) is a declared chosen range in the same way. [HOUSE RULE] [21][22]
24. **Calendarisation** to the target's fiscal year-end is applied to every comp whose year-end differs (formula visible: weighted sum of adjacent fiscal years), and stated in a footnote. **LTM and NTM labels:** every multiple column is labelled LTM or NTM (or FY+1) with the period end date; mixing within a column fails. Check (D): label regex per column; calendarisation row present when year-ends differ. [4][21]
25. **Comps selection criteria are stated on the page:** industry (SIC/GICS), business model, geography, size band (revenue or EV within 0.25x to 4x of target) and growth/margin profile; at least 6 comps unless the sector has fewer, with each exclusion reason listed. Criteria are [HOUSE RULE]; sources do not specify them [21].

### 1c. Pitchbook formatting (IB)

26. **Numbers agree across pages.** Same metric and period, same value on every slide (after rounding); a $50m discrepancy is firing-grade. Check (D): extract numeric claims by label and period across slides, assert equal. [8][24]
27. **One citation/source-record schema everywhere** (used by exhibits, memo and register): `{doc_id, page, bbox_norm[x0,y0,x1,y1], text_span, quote, value, units, period, as_of, retrieved_at, url?}` (`url` optional, `bbox_norm` page-relative 0-1). 100% of numeric claims on every exhibit resolve to a record. The footnote date must equal the record's `as_of` (not `retrieved_at`). Check (D): schema completeness 100%; footnote date parsed and compared to `as_of`; every exhibit has a source footnote. [HOUSE RULE] [8][15][36][24]
28. **Footers, confidentiality marks and page numbers present** on every page, inherited from the master. Check (D): footer placeholders inherited from layout. [16][17][19]
29. **Pitchbook typography numerics** [HOUSE RULE; no bank style guide found]: one theme font family for all text (a second family only for a numeric/mono role, so at most 2 families in the file); body text at least 10 pt; tables at least 8 pt on banking pages; footnotes and sources at least 8 pt (same floor on every page type); titles 20-28 pt; at most 5 distinct font sizes per deck; margins at least 0.5 in on left, right and bottom and at least 0.4 in on top. **Font histogram per role:** group every text run by role (title, body, table, chart label, footnote, page number) and count runs per (family, size); each role must have exactly one dominant (family, size) pair covering at least 95% of its runs and no role may use more than 2 sizes. Check (D) via validate_pptx. [8][15][18][20]
30. **Text hygiene.** No double spaces, double periods or placeholders ("NTD", "TBD", "XX", "[●]"). Check (D): regex. [8][15][18][20]
31. **Football field conventions.** One horizontal bar per method (trading comps, precedents, DCF, optional LBO) with low and high labelled; 52-week range as a visually distinct reference; current price and offer lines; precedents commonly sit above comps by a control premium. Check (D): bar per declared method, axis units, reference lines, endpoints per items 22 and 23. [21][22]
32. **Comps table is sourced and dated** (source, as-of date, one-decimal "x" multiples, median and mean rows, no error cell). Check (D). [4][21]
33. **Layout hygiene.** Zero overlapping or out-of-bounds shapes. Check (D): `om.spacing`. [18]
34. **Editable deliverable.** Native charts with embedded data, live-linked tables, master-driven. Check (D): every chart is a chart graphic frame with an embedded workbook that opens and whose series match the plotted values; zero picture shapes standing in for a chart or table (any picture over 10% of slide area on an exhibit slide must be tagged as a generated visual and contain no data); tables are table objects. Rationale is inference from [15]; extension is [UNSOURCED], check is [HOUSE RULE].

### 1d. Further mechanics

35. **Volatile functions banned in calculation cells:** OFFSET, INDIRECT, TODAY, NOW, RAND, RANDBETWEEN. Allowed only in one labelled cover cell (e.g. print date) that no calculation references. Check (D): formula-text scan; dependents of any volatile cell = 0. [HOUSE RULE] [3]
36. **External workbook links = 0.** No `[Book]` references, no external-link parts in the package, no defined names pointing outside. Check (D): parse the xlsx package. This tightens item 1 (purple is for tolerated links in non-deliverable working files only). [HOUSE RULE] [2][52]
37. **Draft/confidentiality legend on every page** of the deck and every printable model tab (e.g. "Draft - Strictly Private and Confidential" or the declared status text), inherited from the master/header. Check (D): legend text present in master, layout or header/footer on 100% of pages. [15][16][17]
38. **Valuation date and stub period.** One valuation-date input cell; the first forecast period is a stub (year fraction = (fiscal year end - valuation date)/365), the stub cash flow is scaled by the fraction, and discount periods for later years are offset by it; mid-year timing applies to the stub as stub/2. Net debt and share price use the same as-of date. Check (D): stub fraction formula present, in [0,1], and changing the valuation date changes EV. [HOUSE RULE] [54]
39. **LBO mechanics (when an LBO is included).** Sources and uses table with sources = uses (difference 0.001 or less); a debt schedule per tranche (opening, mandatory amortisation, optional paydown, closing, interest); a cash sweep driven by cash available for debt service (sweep % input) and capped at the tranche balance; fees capitalised or expensed as declared; exit equity = exit EV - net debt; **IRR and MoM cross-checked**: the IRR from the cash-flow series must match an XIRR recomputation on dated flows within 0.01 percentage points, and MoM = exit equity / entry equity. Check (D). [HOUSE RULE] [31]
40. **Accretion/dilution mechanics (when a merger model is included).** Pro forma EPS = (acquirer net income + target net income + after-tax synergies - after-tax financing cost - incremental D&A on write-ups) / (acquirer shares + new shares issued); shares issued = stock consideration / acquirer price; the breakeven synergies and the premium-to-EPS sensitivity are shown; cost synergies never enter revenue (see Section 4-4). Check (D): recompute pro forma EPS from components; sources = uses. [HOUSE RULE] [24]

---

## 2. MBB engagement manager / partner (deck)

What they reject: a deck whose titles do not tell the story, slides with several messages, unsourced or non-reconciling numbers, a rubber-stamped look, and polish defects.

### 2a. Storyline and titles

1. **Every content slide has an action title:** a full sentence stating the conclusion, at most 15 words, at most 2 lines at the title size, containing a verb, and containing a number wherever the slide has quantitative data. The 15-word, 2-line and number rules are [HOUSE RULE] (sources say "full sentence, conclusion" only) [23][48][50]. Check (D): word count at most 15; rendered line count at most 2 at the title size; **verb check method: lexicon plus morphology, as implemented in `om/contracts.py::action_title_lint`** (at least 4 words and at least one auxiliary or lexicon verb, an inflected form of one, or a word ending -ed/-ing/-ize/-ise/-ify, after the first word; bare noun phrases such as "Revenue by segment" rejected); threshold 100% of content titles; a digit is present when the slide has a chart or table.
2. **The titles-only read tells the whole story.** Check (G): see the grader spec below. [48]
3. **One message per slide:** at most one primary exhibit (one chart or one table) per slide. Check (D) plus (G). [23][48]
4. **Vertical logic:** each title raises a "why" answered by the body; numbers in the title appear in the exhibit. Check (G). [23][48]
5. **Horizontal logic:** sibling slides follow a stated ordering (deductive, chronological, structural, importance) and are MECE. Check (G). [23][25]
6. **Pyramid and SCQA executive summary.** The answer comes first. Slide 2 (or the first content slide) is an executive summary with four labelled parts: Situation, Complication, Question, Answer. Check (D): exactly one executive-summary slide in the first 3 slides containing the four labels (or four consistently marked blocks) and an Answer that restates the final recommendation title; (G) rates the logic. [25][50]
7. **Ghost deck first and ghost-deck diff.** A ghost deck of titles is approved before building. The rendered titles must equal the approved ghost titles, slide by slide; any difference must appear in a logged diff with a reason, or the check fails. Check (D): title-for-title string comparison; unlogged differences = 0. [25]
8. **Tracker / agenda** marks position on section slides. Check (D). [49] Partly [UNSOURCED].
9. **Source and date line on every exhibit, bottom-left; page number in footer.** Check (D). [48][49]
10. **Every number traceable:** slide-to-source register (slide, claim, source file, page, retrieval date, data cut-off); cross-slide numbers match. Check (D). [48][49]
11. **Eyebrow rule.** An **eyebrow** is a small text label placed above the slide title (a kicker, section tag or category label). House rule: **no eyebrows** on content slides. Check (D): flag any text shape whose bottom edge is above the title's top edge, whose height is under 0.35 in or font size is under 0.7x the title size, and which sits horizontally within the title's span; any hit fails. [HOUSE RULE] (PLAN.md section 6 requires it); the section tracker (item 8) is exempt only if it sits in the footer or a fixed tracker placeholder. Practitioner basis: [48][49].
12. **Reviewer question:** "do all my action titles state conclusions?" Check (G). [51]

**Storyline grader prompt (G).** Input: only the ordered list of slide titles. Prompt: "You are an engagement manager. From these titles alone: (1) state the recommendation in one sentence; (2) name the ordering principle of each section; (3) list slides whose title is a topic, not a conclusion; (4) list gaps (a step in the logic with no slide) and overlaps (two slides making the same point); (5) score 0-10." Pass: recommendation reconstructed correctly, 0 topic titles, 0 gaps, 0 overlaps, score at least 8.5. Verb/length threshold: 100% of content titles at most 15 words and containing a verb.

*Anchor, good (action, specific, sequenced):* (a) "Cost-to-serve is 18% above peers because of last-mile routing" > "Rerouting 40 depots recovers 11 points of that gap" > "Three pilots show payback inside 14 months" > "We recommend a phased rollout starting in the North region". (b) "Demand for the segment grows 9% a year to 2030" > "Two of five competitors hold 70% of that growth" > "Our share gain depends on a faster onboarding cycle" > "Cutting onboarding to 10 days wins 3 points of share".

*Anchor, bad (topic or vague, no number, no logic):* (a) "Market overview" > "Competitive landscape" > "Our capabilities" > "Next steps". (b) "Exciting opportunities in a dynamic market" > "Leveraging synergies to unlock value" > "A holistic approach" > "The way forward".

### 2b. Geometry and typography (numeric)

13. **Geometry floors** [HOUSE RULE; no firm style guide found]: **overlap tolerance 0 EMU** between non-decorative shapes; all content inside margins of at least **0.4 in** on the left, right and bottom (and 0.4 in on top below the title zone start), strict versus the typical 0.4-0.5 in; a **12-column grid** with a gutter of at least 0.15 in, every shape's left and right edges snapping to a column edge within 0.02 in; minimum font size 10 pt for body and **8 pt for footnotes and sources** (same floor as IB pages); minimum shape gap 0.1 in. **Whitespace floor:** at least 15% of each slide's area is unoccupied (area not covered by any shape's bounding box, union computed, background excluded). Check (D): `om.spacing` and validate_pptx. [49]
14. **MBB typography:** at most 2 font families per deck; at most 4 distinct font sizes per deck; a strict size hierarchy (title > subtitle > body > footnote, each step at least 2 pt); line length at most 90 characters per text line; no text below the floor sizes in item 13. [HOUSE RULE] [49][45]

### 2c. Visual range and no rubber stamp

15. **Visual range (the palette stays theme-locked, see 16; range comes from layout, archetype and generated imagery, not from colour).** No more than 40% of slides may share one layout archetype (title+chart, title+table, title+bullets, split, full-bleed visual, etc., classified by shape structure); at least 4 distinct archetypes in any 10 consecutive content slides (at least 3 for decks under 10 slides); no archetype on more than 2 consecutive slides; layout variety: at least 3 distinct layout placeholders or grid-span patterns per 10 slides; **generated visuals (images or SVG) must differ pairwise: perceptual-hash Hamming distance of at least 10 of 64 bits**. There is no hue-based test. Check (D): archetype histogram, run-length check, layout count, pHash matrix. [HOUSE RULE] ("rubber-stamp fails" is PLAN.md section 6; thresholds are strict choices). Basis: generic AI decks read the same [36][45].

### 2d. Anti-slop deterministic checks

16. **Banned content and style.** Fail on any of: gradients (non-solid fills), shadows, glows, 3D or bevel effects; colours outside the theme palette (theme colours only: **one accent plus greys**); **accent coverage at most 15% of the slide's non-background area, where background is the theme bg colour, evaluated on both the light and the dark theme**; em dashes (U+2014); emojis; exclamation marks. Banned phrases use **whole-word, case-insensitive regex matching** with these exact patterns: (a) body and titles: `\b(unlock|unlocks|unlocked|unlocking|holistic|game-changer|game-changing|cutting-edge|revolutionary|seamless|seamlessly|best-in-class|delve|delves|paradigm|state-of-the-art|world-class|empower|empowers|empowered|empowering)\b`, `\bin today's fast-paced\b`, `\bit's important to note\b`; (b) verb use of leverage, body and titles: `\bleverag(e|es|ed|ing) (our|the|its|their|this|these|existing|new)\b` (the noun "leverage" in financial text, e.g. "net leverage 4.5x", is not matched); (c) **titles and headlines only** (not body finance text): `\b(journey|robust|synergies)\b`. List and exemptions are a [HOUSE RULE]; the "generic language" complaint is sourced [24][36][45]. Check (D): XML scan of fills/effects, theme-colour resolution, area calculation, regex.

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


### 2f. Editability, image hygiene and grader calibration

18. **Native, editable charts required.** Every chart is a native chart object with an embedded workbook; chart images are not allowed. Check (D): zero picture shapes that render a chart (picture on an exhibit slide not tagged generated-visual) and every chart part has an embedded workbook. [HOUSE RULE] [15][44]
19. **No text baked into generated images.** Every generated image is OCR-scanned; at most 5 characters may be detected. Titles, labels and numbers are native text. Check (D): OCR character count per image at most 5. [HOUSE RULE]
20. **Storyline grader calibration.** Before the grader scores a deck, it must score the four anchor sequences below correctly: both good sequences at least 8.5 and both bad sequences at most 4.0, with every topic title in the bad sequences listed. If the grader misses either band, its deck score is discarded and rerun. The full grader prompt and anchors are given inline in 2a (above); no external file is needed. Check (G) with (D) on the calibration result. [HOUSE RULE]

---

## 3. PE principal / investment committee (IC memo and diligence)

What they reject: an unsourced claim, a memo that hides the downside, returns that rely on multiple expansion, add-backs they cannot verify, a model that does not tie to the memo, and diligence with unflagged gaps.

1. **Memo sections are enumerated and all present:** (1) executive summary and recommendation (one page: recommendation, size and price, 2-3 sentence thesis), (2) investment thesis, (3) business, (4) market, (5) management, (6) financials and QoE, (7) entry valuation and price, (8) sources and uses, (9) returns (base, upside, downside), (10) value-creation plan, (11) risks and mitigants (9-category taxonomy, item 14), (12) tax, (13) diligence findings and open items, (14) appendix with citations. Sources differ on ordering; all agree on presence. Check (D): all 14 headings present, in a declared order. [27][28][29]
2. **Fund IC template conformance.** When the fund supplies its own IC template, the tool takes a section map `{fund_section -> memo_section(s)}`; every fund section must map to at least one memo section, unmapped fund sections are flagged, and the output page order follows the fund's template. When no template is supplied, item 1 is the default. Check (D): map completeness 100%; order matches. [HOUSE RULE] [27]
3. **Every numeric claim has a citation: 100% of numeric claims, everywhere** (text, tables, charts, footnotes, appendix). One schema for all deliverables: `{doc_id, page, bbox_norm[x0,y0,x1,y1], text_span, quote, value, units, period, as_of, retrieved_at, url?}`. Check (D): coverage 100%; each citation resolves to a document, page and highlighted region. [27][HOUSE RULE]
4. **Highlight and derived figures.** The highlight renders on the source page at `bbox_norm` and `text_span` equals the text extracted inside the box. A **derived figure** (margin, net debt, growth, multiple) lists every input figure, each with its own citation; a missing input fails. Check (D). [27][HOUSE RULE]
5. **Memo-to-model tie-out.** Every number in the memo equals a model cell identified by a manifest id (`{manifest_id, sheet, cell, value, format}`); after rounding to the displayed precision, the memo value equals the recalculated cell value. Orphan memo numbers = 0; changed model cells without a memo update = 0. Check (D). [HOUSE RULE] [24][27]
6. **Appendix links to underlying documents** (models, filings, transcripts, CIM, expert-call notes, third-party reports). Check (D): all cited doc ids resolve. [27]
7. **Cases and haircuts.** Base, upside and downside with distinct assumptions. **Downside EBITDA is at least 20% below base EBITDA** in the declared trough year [HOUSE RULE; strict reading of "a downside that barely dips signals untested assumptions" [27][30]]. **Sponsor vs management table:** revenue, EBITDA and capex per year, management, sponsor and haircut %, with a rationale; sponsor EBITDA at most management EBITDA every year. Check (D). [27][30]
8. **Returns conventions** [HOUSE RULE]: default hold 5 years; hurdle **20% gross IRR and 2.5x MoM** (both must be met to pass; shown with net returns where fees are declared); annual end-of-period cash flows, with the IRR cross-checked against an XIRR recomputation on dated flows (difference at most 0.1 percentage point); entry multiple x exit multiple grid in **0.5x steps across +/- 1.0x** (5 x 5); leverage grid at base +/- 0.5x; growth x exit multiple grid; IRR and MoM in every grid; centre cell equals the base output. Check (D). [30][31]
9. **Returns do not depend on multiple expansion:** a no-expansion case (exit = entry), a stress case with exit 1-2 turns below entry, the entry price at which the hurdle fails, and a returns bridge (EBITDA growth, multiple, deleveraging) that sums to total return. Check (D). [30][31] The "2.0-2.5x on paydown and growth alone" figure is one author's rule of thumb, not a standard.
10. **Leverage, covenant headroom and debt capacity.** Per year: total and senior leverage (x EBITDA), interest cover, fixed-charge cover. **Covenant headroom = 1 - (EBITDA at which the covenant breaches / forecast EBITDA); at least 20% in the base case in every year; reported in the downside** and flagged if below 20% or negative. **Debt capacity** = maximum debt at which base-case headroom stays at or above 20% and the downside does not breach. The 20% headroom is a [HOUSE RULE]; the sensitivity of leverage to an EBITDA misstatement is illustrated in [55]. Check (D): recomputed.
11. **QoE add-backs.** Each add-back has a source id, a category and a recurrence test, and the bridge from reported to adjusted EBITDA sums. **Flag for review when total add-backs exceed 20% of adjusted EBITDA** (basis declared: adjusted EBITDA = reported EBITDA + add-backs; ratio = add-backs / adjusted EBITDA). Sources aligned to that basis: [56] reports seller add-backs at roughly 26-29% of adjusted EBITDA across sale processes and 10-30% of proposed add-backs disallowed by buy-side providers, so a 20% flag sits below the reported average; [55] shows how a lower sustainable EBITDA raises effective leverage. A claimed regulator-set 25-30% cap is unverified and [UNSOURCED]; not used. The 20% threshold is a [HOUSE RULE]. Check (D). [32][33][34]
12. **NWC peg test.** Peg = trailing-12-month average NWC computed from 12 monthly balances; seasonality noted (peak and trough month, range as % of the average); delivered NWC at close compared with the peg. Fail if the peg is built from fewer than 12 monthly points or from a single year-end balance. Check (D). [HOUSE RULE] [33][34]
13. **Revenue-quality checks.** Recurring revenue % (definition declared), top-10 customer share, net and gross revenue retention, churn and cohort retention where data exist; where data do not exist, the item is marked [UNKNOWN] rather than omitted. Check (D) for presence, (G) for interpretation. [33][34]
14. **Risk table and taxonomy.** Per risk: description, probability, impact, mitigant or trigger, owner. **Required categories, each present or marked not applicable with a reason:** customer concentration (single customer above 10% of revenue flagged), key person, regulatory, FX, refinancing and maturity wall (maturity within 24 months of close flagged), supplier, technology and cyber, litigation, ESG. Taxonomy and thresholds are a [HOUSE RULE]. Check (D). [27][29]
15. **Hockey sticks flagged (tag D).** A forecast is tagged "hockey stick" when its revenue or EBITDA forecast CAGR exceeds 1.5x the trailing 3-year CAGR, or its annual margin expansion exceeds 1.5x the trailing 3-year average annual margin change; each tag has a verification note. Check (D): recompute CAGRs and tag. [HOUSE RULE] [30]
16. **Diligence status:** completed vs outstanding with owners and dates; conditions on approval. Check (D). [27]
17. **VDR request-list matching.** The request list is the versioned **Acretia buyer request list v1** (Appendix A, 75 items across corporate, financial, tax, legal, commercial, HR, IT, environmental). Matching rule: a data-room document matches a request when it is in the **same section and the keyword Jaccard similarity is at least 0.3** (keywords = lowercased, stop-word-removed, stem-normalised tokens of the request text and of the document title plus first 200 words), or by a **logged manual override** (who, when, why). Status per request: fulfilled / partial / unaddressed. **Every unaddressed request gets an owner** (and a due date). **Superseded versions** are flagged by date (a later document date for the same normalised filename stem) or version suffix (`v2`, `rev`, `final`, `_FINAL_v3`), the latest being current; **unreadable files** (corrupt, password-protected, no text after failed OCR) are listed separately and count as unaddressed. The unaddressed count appears on page one. Check (D). [41][42]
18. **Data security and confidentiality** [HOUSE RULE; no public standard for this product class found]: organisation-level access control (SSO/RBAC, deal-level permissions); **no training on client data** (contractual statement plus a technical control: client content excluded from any training or evaluation pipeline); **configurable data residency** (region selectable per organisation); **audit log** (immutable, who/what/when for every view, export and model call, exportable); **deletion on request** (data, derived indexes and caches deleted within 30 days, with confirmation). Ingested documents are treated as data, never instructions. Check (D) for configuration and log evidence, (G) for the written policy.
19. **Audit before submission:** `om.formula` and `om.modelcheck` pass; scenario outputs reconcile. Check (D). [27]
20. **Length.** The IC memo body is 10-25 pages with a one-page executive summary (typical, not a rule). Reviewed by (G) only; not a (D) check. [28]

---

## 4. Complaints about AI finance tools and what unlocks $10K+/seat

Evidence: BankerToolBench [24] (Handshake AI and McGill, bankers from several bulge-bracket and elite boutiques, 100 tasks, 500 reviewers, April 2026): no deliverable client-ready; best model 58.1/100; Opus-class models produced polished Excel with hardcoded values so changing purchase price did not update; a deck showed $189.5bn then $201.0bn for the same period; off-brand accent colour; GPT-5.4 failure modes 41% code/formula bugs, 27% business-logic errors (e.g. cost synergies added to revenue), 13% invented missing numbers presented as sourced.

1. **Zero hardcoded outputs in models.** Check (D): see 1a-3 and 1a-16. [24]
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
13. **Reference deliverable and price link (non-scored commentary).** No public benchmark deliverable priced at $10K per seat was found: the price-to-deliverable link is [UNSOURCED] and carries **no scoring weight** in Section 5. The working reference deliverable is a **12-page IC memo** (inside the 10-25 page range of 3-20), plus the linked 3-statement/DCF model, plus a VDR coverage grid, with every figure click-through to a highlighted source region. Personas may comment on willingness to pay; the comment is recorded but not scored. [HOUSE RULE]

---

## 5. Persona rubric (canonical; refines and supersedes the summary bullets in PLAN.md section 6)

Scoring: each persona returns per-criterion scores 0 to the weight, a total out of 10, blocking issues with locators (sheet!cell, slide number, memo section), and a **non-scored** comment "would pay $10K+/seat? yes/no + why" (recorded, never scored, see 4-13). Below 8.5 = blocked. Any **HARD** row scoring 0 caps the total at 6.0. For the IB persona, a failed **binary gate** (G1 error values or indicators, G2 unbalanced BS, G3 untied cash; see section 1) caps the total at **5.0**, whatever the sum.

### 5.1 IB analyst (Goldman / Morgan Stanley style)

| # | Criterion | Wt | Pass descriptor (full marks) | Check |
|---|---|---|---|---|
| 1 | **HARD** Integrity gates G1-G3: zero error values and indicators, BS balances and cash ties within 0.001, checks tab green, IFERROR/IFNA only around lookups (1a-9, 11, 12) | 2.0 | No error cells or indicators; diffs at most 0.001 in all periods; master check = 0; masking test passes | D: LibreOffice recalc, `om.modelcheck` |
| 2 | **HARD** Live model: allowlist-only literals, forecasts all formulas, input flex changes outputs, no volatile functions, external links = 0 (1a-2, 3, 16; 1d-35, 36) | 1.75 | Zero non-allowlist literals; every input has dependents; flex passes; no volatile or external links | D |
| 3 | Colour code incl. green cross-sheet, distinct external colour, legend (1a-1) | 0.75 | 100% conformance | D |
| 4 | Row consistency, sign convention, units and headers (1a-4, 6, 7) | 0.75 | R1C1 inconsistencies = 0; header cells present | D |
| 5 | Circularity switch and scenario toggle (1a-10, 17) | 0.75 | Both work and balance in every state | D |
| 6 | Navigability: freeze panes, print area, fit to 1 page wide, 0 hidden sheets, at most 25 named ranges (1a-13, 14) | 0.5 | All present on all model tabs | D |
| 7 | Valuation mechanics: valuation date and stub, DCF mid-year column, TV cross-check and share flag, EV bridge with tranche TSM, IQR rule, declared DCF range, calendarisation, LTM/NTM, comps criteria (1b; 1d-38) | 1.0 | All items pass | D + G |
| 8 | Transaction mechanics: LBO (S&U, debt schedule, sweep, IRR vs XIRR) and accretion/dilution where included (1d-39, 40) | 1.0 | All items pass; N/A rows are declared | D |
| 9 | Pitchbook hygiene: cross-page agreement, one citation schema and date rule, typography numerics, font histogram, draft/confidentiality legend, footers (1c-26 to 33; 1d-37) | 1.0 | Zero mismatches; schema 100%; typography within limits; legend on 100% of pages | D |
| 10 | Editable deliverable: native charts and tables with embedded data (1c-34) | 0.5 | Zero chart images; embedded workbooks open | D |

Weights: 2.0 + 1.75 + 0.75 + 0.75 + 0.75 + 0.5 + 1.0 + 1.0 + 1.0 + 0.5 = **10.0**.

### 5.2 MBB engagement manager

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Storyline: SCQA executive summary, ghost-deck diff equal or logged, grader passes calibration anchors then reconstructs the recommendation from titles alone (2a-2, 6, 7; 2f-20) | 1.75 | Calibration passed; grader: 0 topic titles, 0 gaps, 0 overlaps, score at least 8.5; unlogged ghost diffs = 0 | G + D |
| 2 | **HARD** Action titles (at most 15 words, at most 2 lines, verb by lexicon + morphology, number where data exists) and one message per slide (2a-1, 3) | 1.5 | 100% of content slides comply | D + G |
| 3 | Horizontal and vertical logic (2a-4, 5) | 0.5 | Ordering principle identified; no overlaps or gaps | G |
| 4 | Chart fit: chart-message mapping, axis baselines, sort order, labels, no 3D (2e-17) | 1.0 | Every chart passes mapping and title-exhibit match | D + G |
| 5 | Sources and traceability: source/date line, register, reconciling numbers (2a-9, 10) | 0.75 | Zero orphan numbers | D |
| 6 | Geometry: 0 EMU overlap, margins at least 0.4 in, 12-column grid, size floors, whitespace at least 15% per slide (2b-13) | 1.0 | `om.spacing`/validate_pptx zero violations | D |
| 7 | Visual range: at most 40% one archetype, at least 4 archetypes per 10, no archetype over 2 consecutive, pHash distance at least 10 of 64 (2c-15) | 1.0 | All thresholds met | D + G |
| 8 | Anti-slop, typography and house rules: banned patterns, no gradients/shadows/3D, one accent at most 15% coverage, no em dashes/emojis/exclamations, at most 2 families and 4 sizes, line length at most 90, no eyebrows, footer and page number (2a-11; 2b-14; 2d-16) | 1.5 | Zero violations | D |
| 9 | Editability and image hygiene: native charts, no text baked into images, OCR at most 5 characters (2f-18, 19) | 1.0 | Zero chart images; OCR at most 5 per image | D |

Weights: 1.75 + 1.5 + 0.5 + 1.0 + 0.75 + 1.0 + 1.0 + 1.5 + 1.0 = **10.0**.

### 5.3 PE principal / IC member

| # | Criterion | Wt | Pass descriptor | Check |
|---|---|---|---|---|
| 1 | **HARD** Traceability: 100% of numeric claims cited with the single schema; page + bbox_norm + text span; derived figures trace to all inputs; memo-to-model tie-out by manifest id (3-3, 4, 5) | 2.0 | 100% of numeric claims linked and resolving; orphan memo numbers = 0 | D |
| 2 | Memo structure: 14 enumerated sections, fund-template conformance, appendix links (3-1, 2, 6) | 1.25 | All sections present; template map complete | D |
| 3 | Returns and case thresholds: downside at least 20% below base, haircut table, conventions (5y, 20% IRR / 2.5x, XIRR check, grid steps), no-expansion case, bridge (3-7, 8, 9) | 1.5 | All thresholds met; grids centred on base | D + G |
| 4 | QoE, NWC peg and revenue quality: add-backs sourced and flagged above 20% of adjusted EBITDA, 12-month peg, recurring %, concentration (3-11, 12, 13) | 1.0 | Every adjustment sourced; peg from 12 months | D + G |
| 5 | Leverage, covenant headroom and debt capacity (3-10) | 0.75 | Headroom at least 20% in base; downside reported | D |
| 6 | VDR matching against Acretia buyer request list v1: Jaccard 0.3 rule, overrides logged, superseded and unreadable flagged, owners on unaddressed (3-17; Appendix A) | 1.0 | Counts shown; every unaddressed item has an owner | D |
| 7 | Risk taxonomy (9 categories), hockey sticks tagged, diligence status (3-14, 15, 16) | 0.75 | All categories present or n/a with reason | D + G |
| 8 | Model integrity behind the memo (3-19) | 0.75 | `om.formula` and `om.modelcheck` green | D |
| 9 | Data security and confidentiality: access control, no training on client data, residency, audit log, deletion (3-18) | 1.0 | All five controls evidenced | D + G |

Weights: 2.0 + 1.25 + 1.5 + 1.0 + 0.75 + 1.0 + 0.75 + 0.75 + 1.0 = **10.0**.

---

## 6. Gaps and open items

- Forum threads (WSO, Reddit) were not retrievable; items 1a to 1c rely on training sites and practitioner essays. A manual WSO pass is recommended before grading calibration [UNSOURCED for forum-specific pet peeves].
- No bank or MBB firm style guide was found; every numeric threshold labelled [HOUSE RULE] must be recorded in DECISIONS.md and may be loosened only by the Boss.
- Vendor and blog sources carry commercial bias; the strongest empirical sources are [24] and [26].
- Covenant headroom and TV-share bands come from training-site rules of thumb [53][54][55], not a standard.
- The $10K price-to-deliverable link is [UNSOURCED] and unscored (4-13). Appendix A is an original house list, not a published standard.

---

## Appendix A. Acretia buyer request list v1

Version 1.0 (75 items, eight sections: corporate, financial, tax, legal, commercial, HR, IT, environmental). Compiled as a generic buyer-side diligence list from the structure described in [41][42]; wording is original and the list is a [HOUSE RULE] default that a fund list may replace (then it is versioned as a new list id). Matching rule (3-17): same section and keyword Jaccard at least 0.3 between the request text and the candidate document, or a logged manual override. Every unaddressed item gets an owner.

| ID | Section | Request |
|---|---|---|
| A-001 | Corporate | Certificate of incorporation, bylaws and all amendments |
| A-002 | Corporate | Organisation chart showing all legal entities and ownership percentages |
| A-003 | Corporate | Capitalisation table with all classes, options, warrants and convertibles |
| A-004 | Corporate | Board and committee minutes for the last three years |
| A-005 | Corporate | Shareholder and voting agreements |
| A-006 | Corporate | List of subsidiaries, joint ventures and minority investments |
| A-007 | Corporate | Prior acquisitions and divestitures with agreements |
| A-008 | Corporate | Management biographies and organisation structure |
| A-009 | Financial | Audited financial statements for the last three fiscal years |
| A-010 | Financial | Monthly management accounts for the last 36 months |
| A-011 | Financial | Trailing twelve month income statement balance sheet and cash flow |
| A-012 | Financial | Quality of earnings report or EBITDA adjustment schedule |
| A-013 | Financial | Monthly net working capital balances for the last 24 months |
| A-014 | Financial | Revenue by customer product and geography for three years |
| A-015 | Financial | Gross margin by product line and cost of goods sold detail |
| A-016 | Financial | Budget and forecast for the current year and five-year plan |
| A-017 | Financial | Capital expenditure history split maintenance and growth |
| A-018 | Financial | Debt schedule with maturities rates and covenants |
| A-019 | Financial | Credit agreements and compliance certificates |
| A-020 | Financial | Accounts receivable and payable ageing reports |
| A-021 | Financial | Off-balance-sheet liabilities leases and guarantees |
| A-022 | Financial | Auditor management letters and internal control findings |
| A-023 | Tax | Federal state and foreign income tax returns for three years |
| A-024 | Tax | Tax audits examinations and correspondence with authorities |
| A-025 | Tax | Sales use and VAT filings and exposure analysis |
| A-026 | Tax | Transfer pricing documentation and intercompany agreements |
| A-027 | Tax | Deferred tax asset and liability schedule and net operating losses |
| A-028 | Tax | Tax structure chart and any tax rulings or holidays |
| A-029 | Tax | Payroll tax filings and worker classification review |
| A-030 | Tax | Uncertain tax positions and tax reserves |
| A-031 | Legal | Material customer contracts and change of control provisions |
| A-032 | Legal | Material supplier and distribution contracts |
| A-033 | Legal | Pending threatened or settled litigation and claims |
| A-034 | Legal | Regulatory licences permits and compliance correspondence |
| A-035 | Legal | Intellectual property register patents trademarks and licences |
| A-036 | Legal | Real property leases and ownership documents |
| A-037 | Legal | Insurance policies and claims history |
| A-038 | Legal | Data privacy policies breach notices and regulator inquiries |
| A-039 | Legal | Related party transactions and agreements |
| A-040 | Legal | Non-compete exclusivity and most-favoured-nation clauses |
| A-041 | Commercial | Market study or third-party industry report |
| A-042 | Commercial | Customer list with revenue concentration and tenure |
| A-043 | Commercial | Customer churn retention and cohort analysis |
| A-044 | Commercial | Pricing history discounts and rebate programmes |
| A-045 | Commercial | Sales pipeline backlog and bookings by quarter |
| A-046 | Commercial | Competitor analysis and market share data |
| A-047 | Commercial | Customer references and satisfaction surveys or NPS |
| A-048 | Commercial | Product roadmap and development pipeline |
| A-049 | Commercial | Sales and marketing organisation and channel strategy |
| A-050 | Commercial | Top supplier list with spend concentration |
| A-051 | Commercial | Warranty returns and product liability history |
| A-052 | Commercial | Recurring revenue definition and contract renewal schedule |
| A-053 | HR | Employee census with role tenure location and compensation |
| A-054 | HR | Employment agreements for senior management and key employees |
| A-055 | HR | Equity incentive plans and outstanding awards |
| A-056 | HR | Benefit plans pension obligations and retiree liabilities |
| A-057 | HR | Union and collective bargaining agreements |
| A-058 | HR | Employee turnover and hiring data for three years |
| A-059 | HR | Employment claims disputes and investigations |
| A-060 | HR | Key person dependency and succession plans |
| A-061 | IT | Systems architecture and application inventory |
| A-062 | IT | Cybersecurity policies penetration tests and incident log |
| A-063 | IT | Software licences and open source usage report |
| A-064 | IT | Disaster recovery and business continuity plans |
| A-065 | IT | Major IT vendor contracts and cloud hosting agreements |
| A-066 | IT | Technology roadmap and technical debt assessment |
| A-067 | IT | Data protection certifications SOC 2 and ISO 27001 reports |
| A-068 | IT | Capitalised software development costs and headcount |
| A-069 | IT | Customer data inventory and retention policy |
| A-070 | Environmental | Environmental permits and compliance audits |
| A-071 | Environmental | Phase I and Phase II environmental site assessments |
| A-072 | Environmental | Hazardous materials waste and remediation liabilities |
| A-073 | Environmental | Health and safety incident records and citations |
| A-074 | Environmental | ESG policies emissions data and sustainability reporting |
| A-075 | Environmental | Climate and physical risk assessment of key sites |

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
