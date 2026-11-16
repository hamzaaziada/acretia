# Deck-engine teardown summary (packet S1.2)

Scope: 15 candidates (13 external plus the harness slides engine and our om/ Deck Studio baseline), all run or read at a pinned commit, same 3 synthetic finance briefs (docs/teardowns/briefs/: A LBO IC update 6 slides, B public comps 8 slides, C market entry 5 slides, 19 slides total). No LLM or API key was used anywhere. Findings per candidate are in docs/teardowns/deck-<name>.md. Run artefacts (decks, PNG contact sheets, audit JSON, drivers) are outside the repo in the session scratchpad (`/tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/` and its parent s12/).

## 1. Comparison table

| Candidate | Archetypes | Layout method | Text-fit method | Validator | Native charts | RTL | Licence | Ran |
|---|---|---|---|---|---|---|---|---|
| om/ Deck Studio (baseline) | ~10 components + 8 chart kinds + table | absolute inches, layout JSON | heuristic 0.5 em (spacing.py:68) | ~25 rules incl. house rules, deck-level title/footer | yes, incl. floating bars | no | internal | yes (3/3) |
| meshpool slides engine | 16 | absolute from tokens | real metrics: PIL + Carlito, shrink loop, error at floor | schema (unknown/missing fields) + 7 QA checks | yes (6 types, no waterfall/football) | no | MIT | yes (3/3; icon archetypes blocked) |
| Mck-ppt-design-skill | 70 methods | absolute per method | heuristic (1.4 x size) | 11 QA checks, weak (passed defective decks) | no (shapes) | no | Apache-2.0 | yes (3/3) |
| mbb-ppt-generator | 84 methods | same engine as Mck | heuristic | S3 content gate + S4 render gate (caught defects) | no (shapes) | no | Apache-2.0 | yes (3/3) |
| swak/pptx-mcp (sdist, no git hash) | 53 types, 12 chart, 8 diagram | template function per type | heuristic | 33 review rules, 0-10 score | yes | no | MIT | yes (3/3) |
| clean-slides | tables + clustered/stacked/waterfall charts | template placeholders + solver | char-class heuristic | LayoutVerifier | yes (waterfall overlay) | no | MIT | yes (3/3, mapped to tables) |
| pptx-mcp-server (shjanjua; alt samos123) | 0 (shape primitives) | absolute | none | none | no | no | none (alt Apache-2.0) | partial (alt: no) |
| ginlix-ai pptx skill | 0 (guidance + audit script) | absolute, one geometry function | estimate in check.py | check.py: ~11 checks on saved file | required native | no | Apache-2.0 | partial (check.py on 19 decks) |
| PptxGenJS | primitives; 10 chart types | absolute | flags only (fit shrink/resize) | none | yes | paragraph rtlMode flag | MIT | yes (3/3) |
| python-pptx | primitives; 73 chart types | absolute (EMU) | fit_text via PIL font file | none | yes (embedded workbook) | no API | MIT | yes (probe + substrate of 7 runs) |
| PPTAgent (HEAD = skill) | 0 (free HTML) | HTML DOM to pptxgenjs | browser layout (real glyphs) | procedural review ledger, no geometry rules | tables native; charts as shapes | none found | MIT | partial (brief C only) |
| Presenton | 16 templates, 383 layouts | React templates | browser CSS | none found | unverified | none found | Apache-2.0 | no (needs LLM + stack) |
| AutoPresent | 5 helpers | model-given coordinates | flags only | none | no (images) | no | MIT | partial |
| SlideCoder | 0 | model-given from image | none | none | no | no | none (SlideMaster Apache) | partial (CGSeg only) |
| mckinsey-pptx | unknown | unknown | unknown | unknown | unknown | unknown | unknown | no (repo 404) |

Neutral audit (LangAlpha check.py --strict, fail instances on the briefs; its floors are 10 pt body and 14 pt tables, so table text at 12 pt dominates):

| Engine | Brief A | Brief B | Brief C |
|---|---|---|---|
| om/ | 0 | 77 | 8 |
| meshpool | 12 | 91 | 10 |
| Mck | 31 | 23 | 29 |
| mbb | 30 | 23 | 27 |
| swak | 32 | 113 | 31 |
| clean-slides (tables only) | 3 | 8 | 5 |
| PptxGenJS (my layout) | 0 | 76 | 8 |
| PPTAgent (hand HTML) | not run | not run | 86 |

Brief-archetype matrix (what each engine produced natively without a hack):

| Archetype in briefs | Best native result | Notes |
|---|---|---|
| EBITDA bridge | swak bridge, om waterfall, clean-slides waterfall (native charts); Mck/mbb draw it from shapes | meshpool and PptxGenJS need stacked-series workarounds |
| Football field | om (hidden-first stacked bar, via Slide API) | nobody ships low/high labels, an overlap band and a current-EV line; all others fell back to a table or a stacked bar |
| 2x2 | Mck/mbb matrix_2x2, swak matrix (broken render), meshpool none | om and PptxGenJS needed hand geometry; no engine plots points by score |
| Process flow / timeline | om process_flow, meshpool roadmap and timeline, Mck/mbb chevron | Mck chevron labels clip beyond 3 chars (mbb content gate flags it) |
| Comps table (7 cols x 10 rows) | meshpool, om, PptxGenJS | swak overflowed into its source line |
| Sensitivity grid | swak sensitivity_table (heat-shaded) | others use a plain table |

## 2. What the teardown shows

- [OBSERVATION] No candidate satisfies the S3 contract end to end (model writes no coordinates, real glyph metrics with fit-or-structured-error, deterministic validator naming shape ids, native charts, RTL). The closest single piece is meshpool's spec.py plus textfit.py, which is already in our reference tree.
- [OBSERVATION] Only three engines measure text with real font files: meshpool (Carlito via PIL), python-pptx fit_text (single style) and the browser-based PPTAgent route. Every other tool uses 0.5 em style heuristics, including our om/spacing.py.
- [OBSERVATION] The self-reported quality gates were uneven: Mck reported "QA passed" on decks with overlapping cover text and clipped chevron labels; mbb's content gate failed all three briefs before rendering with exact, fixable messages; swak's review engine scored 0.9 to 3.8 of 10 but did not prevent title-underline strike-through on every slide.
- [OBSERVATION] Nobody implements RTL mirroring. PptxGenJS sets rtl="1" per paragraph, python-pptx has no API, clean-slides hard-codes rtl="0". S3.5 is greenfield.
- [OBSERVATION] Hygiene findings: SlideCoder/SlideCoder/model.py contains a committed API key string (value not recorded; do not import that file); shjanjua/pptx-mcp-server has no LICENSE; swak/pptx-mcp is unreachable on GitHub from this environment (only the PyPI sdist was analysed, so the ledger needs an sdist hash, not a git commit); mckinsey-pptx repository returned 404.
- [INFERENCE] Shape-built charts (Mck, mbb, PPTAgent HTML) look polished but are not data-bound; a banker cannot right-click Edit Data. Native data-bound charts should stay a hard requirement, as the plan says.
- [UNKNOWN] Presenton, PPTAgent's research pipelines, SlideCoder and AutoPresent generation quality: all need an LLM key, so their generative output quality is unmeasured here. PowerPoint-desktop rendering fidelity of every output is also unmeasured (LibreOffice only).

## 3. Recommended design for S3

Licence rule applied: MIT/Apache/BSD may be vendored; no GPL or proprietary candidate was found; unlicensed code (SlideCoder main code, shjanjua) is excluded entirely. Where code reuse is allowed I still recommend re-implementing, because each source has a mismatch (listed).

1. Renderer substrate (S3.3): python-pptx (MIT) as primary, as planned, with om/pptx.py's chart XML kept for floating-bar charts (football field, waterfall) so charts stay data-bound; add a small helper that builds hidden-base stacked bars on python-pptx. PptxGenJS is not justified: it adds Node, has no waterfall type, and its only distinct feature (paragraph rtl="1") can be set by XML. Ledger decision for PptxGenJS: skip.
2. Spec and schema (S3.2): start from reference/meshpool-harness spec.py (ours, MIT): required/optional fields per archetype id, unknown-field rejection, precise error strings. Extend the archetype vocabulary with swak's finance types as ideas only (SCR executive summary, bridge kinds baseline/volume/price/mix/fx/other/total, sensitivity_table with baseline cell, tornado, RAG scorecard) and Presenton's layouts.json pattern: one machine-readable description per archetype for the model to choose from. No coordinates, fonts or colours in the schema (reject them).
3. Pre-render content gate (S3.1, S3.2): port the idea from mbb gate_check_content.py (Apache-2.0): per-archetype budgets (rows, items, label length), source and as-of required, action-title length, a cap on how often any one archetype repeats (25%) and on exec_summary (15%), and a visual-density floor (max(2, N//4)). Return structured items {slide_idx, archetype, check, message}. Write it ourselves against our schema.
4. Fit engine (S3.4): extend meshpool textfit.py (PIL ImageFont, SAFETY 0.94, 0.5 pt step) with fontTools/Pillow metrics for all theme fonts and mixed runs, then implement the plan's order reflow, tighten spacing, shrink to the floor, then a structured error naming block and word excess. Use python-pptx fit_text only for single-style titles. Do not use any heuristic-only approach (Mck, swak, clean-slides, om/spacing) as the arbiter.
5. Validator (S3.7): model validate_pptx.py on ginlix check.py (Apache-2.0): read the saved XML, resolve layout-inherited placeholders, handle groups, rotation and flips, report fail/warn/info with slide and shape ids and a --strict exit code. Merge in om/spacing.py rules (house title/footer rule, gap grid, equal cards), WCAG contrast from meshpool qa.py, and the list of swak's 33 review rules as a checklist. Fix check.py's weak spot: text deliberately layered on a shape (labels on bars) must count as contained, not as overlap.
6. Firm templates (S3.9): borrow clean-slides' model (MIT): a template plus a config YAML, fill placeholders rather than draw, with init and inspect commands; combine with Presenton's idea of cloning a layout catalogue from an uploaded PPTX.
7. Vision critic (S3.8): keep it after the validator passes; use the evidence-ledger idea from PPTAgent (hash inputs, mark renders stale on any source change) so a critic can never review an out-of-date render. Skip SlideCoder's region segmentation: shape ids from the validator are exact.
8. Arabic and RTL (S3.5): greenfield. No candidate mirrors layouts. Build it ourselves with arabic-reshaper and python-bidi for measurement, rtl="1" and algn="r" on paragraphs (the PptxGenJS attribute is the reference), and mirrored archetype geometry.
9. Archetype backlog for S3.3 (35+): from Mck/mbb (ideas, Apache-2.0 allows code but their geometry is shape-built): table_insight, scorecard, RAG status, Harvey-ball table, pyramid, temple, risk matrix, stakeholder map, decision tree, value chain, mekko, Gantt, pareto, before/after, pros/cons. From meshpool: exec_summary, numbered, roadmap, recommendation, stat_row. From om: bridge, dot_plot, process_flow, stat_callout. New and missing everywhere: football field with low/high labels, overlap band and current-EV line; 2x2 plotted from scores; comps table with median and subject rows; tombstones; issue tree; market map. Re-express every one natively on our 12-column grid with data-bound charts.
10. Eval (S3.10): use SlidesBench categories (AutoPresent, MIT code; data licence to be checked in S1.1) and the uniform check.py audit as a producer-neutral benchmark column; Presenton and PPTAgent comparisons need keyed runs and stay [UNKNOWN] until then.
11. Anti-slop alignment (S3.6): meshpool's shadowed KPI cards and side panels, Mck's per-method palettes, and swak's accent underline all violate the plan's no-shadow, one-accent rules; do not carry any of that styling over.

## 4. Ledger inputs for S1.1 (from this packet)

| Repo | Commit used | Licence first line | Suggested decision |
|---|---|---|---|
| presenton/presenton | 9af2b47dda31060d3d5070e020a0825b15c94b32 | Apache License | borrow_ideas |
| icip-cas/PPTAgent | 9dacac53ac9ef39346461063df729396551d929e | MIT License | borrow_ideas |
| para-lost/AutoPresent | 98e0c012e89469863d9c3c8bc87eac967d82b2e6 | MIT License | borrow_ideas (SlidesBench eval) |
| vinsontang1/SlideCoder | c71faa5b76caaa09e407e17c845bbabc0ed8a3fa | none (SlideMaster/ Apache) | skip (committed secret, no licence) |
| tmustier/clean-slides | c67a56a31cba898eb6e76314f80d6b3301d71975 | MIT License | borrow_ideas |
| likaku/Mck-ppt-design-skill | 49221997c05e0013c6d4f6ec4d9923e936ad058f | Apache License | borrow_ideas |
| albertojb/mbb-ppt-generator | 74169bc5672d25a762e3dde3f96ee74380ace0d8 | Apache License | borrow_ideas |
| seulee26/mckinsey-pptx | unavailable | unknown | skip (unretrievable) |
| shjanjua/pptx-mcp-server | 775ef7c5b966480e229395b3346a0009c84597b4 | none | skip |
| samos123/pptx-mcp | 7da5daa31634daf5116f82b04e3847a0c94f3330 | Apache License | skip |
| swak/pptx-mcp | sdist pptx-mcp 0.18.0, sha256 d002c1109197e13317a748a61602ad545061f4bfafae90e8f56038fe1fe61d8b (no git hash) | MIT License | borrow_ideas |
| ginlix-ai/LangAlpha (pptx skill) | 485e8ebab8599979158202a46676181deef76c6a | Apache License | borrow_ideas |
| scanny/python-pptx | 278b47b1dedd5b46ee84c286e77cdfb0bf4594be | The MIT License (MIT) | adopt |
| gitbrent/PptxGenJS | 3c9ec1b687c174952166f6a34b5e87ebf69fa469 | The MIT License (MIT) | skip (or scratch fallback only) |
