# Teardown: likaku/Mck-ppt-design-skill

repo: https://github.com/likaku/Mck-ppt-design-skill
commit: 49221997c05e0013c6d4f6ec4d9923e936ad058f
licence: Apache License (LICENSE:1-2, "Apache License / Version 2.0"; pyproject.toml also declares Apache-2.0; NOTICE must be retained)
ran: yes (3 briefs, 19 slides through DeckBuilder.build plus the repo's own qa.analyze; PNG render via soffice)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/mck/{a,b,c}.pptx, sheets, audit/mck_*.json. Driver: s12/run_mck.py (storyline hand-mapped from the briefs; no LLM; repo code executed only inside a venv).

## Findings

- [OBSERVATION] A Python class MckEngine with 70 layout methods (ast count over mck_ppt/engine.py; README claims 62-67), each taking positional tuples: executive_summary(headline, items[(num,title,desc)]), metric_cards, data_table, table_insight, matrix_2x2(quadrants[(label,color,desc)]), process_chevron, timeline, waterfall(items[(label,value,'base'|'up'|'down')]), horizontal_bar, stacked_bar, grouped_bar, scorecard, kpi_tracker, etc. (mck_ppt/engine.py; categories listed at mck_ppt/__main__.py:17-35). DeckBuilder.build runs a storyline [{type, data}] (mck_ppt/deck_builder.py:21-66).
- [OBSERVATION] Layout method is hard-coded absolute geometry per method on a 13.333 x 7.5 canvas with left margin 0.8 in and content top 1.3 in (mck_ppt/constants.py:49-66). Fonts: Georgia headings, Arial body, KaiTi for East Asian (constants.py:81-83). Defaults are Chinese: toc title '目录', table_insight insight_title '启示：' (engine.py signatures).
- [OBSERVATION] Charts are NOT native: grep -c add_chart over mck_ppt/*.py returns 0 for every file; bar, stacked, waterfall and donut are drawn from rectangles and block arcs (engine.py:1688-2060). The result is editable shapes but not data-bound charts; numbers cannot be re-edited as data.
- [OBSERVATION] No text measurement with real glyph metrics: qa._estimate_text_height uses font size x 1.4 line height and a char-count wrap estimate (mck_ppt/qa.py:217-260). Layouts hard-code character budgets instead.
- [OBSERVATION] QA module covers body overflow, text overflow, whitespace/dead zones, shape overlap (tolerance 0.02 in), min font 8 pt, text-line collision, peer-font consistency, chart legend overflow, connectors, global checks (mck_ppt/qa.py:71-73, 304-837), with a 0-100 score. On the 3 briefs it reported "QA passed" for all, yet the PNGs show a cover title overlapping its subtitle (out/mck/b-1.png), chevron step circles clipping multi-word labels (out/mck/c-4.png, "20 / 28" and "Q3 / 27"), and the horizontal-bar last row colliding with the source line (out/mck/b-4.png). The gate is weaker than its claim.
- [OBSERVATION] Layout quality on content slides is good: action title with rule, navy/grey palette, whitespace, page "n/N" footer (out/mck/a-sheet.png). Waterfall is the most convincing shape-drawn bridge (out/mck/a-3.png) but a 'down' item given as a positive number prints "+4.5" in red because the API takes absolute values.
- [OBSERVATION] Uniform check.py --strict audit: 31 / 23 / 29 fail instances (a/b/c), dominated by font floors (14 pt table text), text_overflow estimates and one overlap on brief B.
- [OBSERVATION] No RTL or Arabic support found (no whole-word rtl/bidi in mck_ppt/).
- [INFERENCE] Breadth of finance-relevant archetypes is the attraction (waterfall, matrix, chevron, timeline, scorecard, harvey ball), but the geometry is per-method magic numbers with no solver, so every layout carries its own overflow risk; porting layouts would mean re-expressing them on our grid.
- [UNKNOWN] The optional cover-image path calls a third-party image API (pyproject extras: tencentcloud-sdk-python, rembg); not run.

## Adopt / borrow ideas / skip

Borrow ideas (Apache-2.0 allows code reuse with NOTICE retained, but the shape-drawn charts and magic-number layouts do not fit our native-chart, solver-first design). Take the archetype list (table_insight, scorecard/RAG, harvey-ball table, pyramid, temple, risk matrix) as a backlog for S3.3, and the post-build QA scoring idea. Skip the code itself.
