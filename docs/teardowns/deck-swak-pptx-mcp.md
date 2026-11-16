# Teardown: swak/pptx-mcp

repo: https://github.com/swak/pptx-mcp (GitHub returns "could not read Username" / HTTP 404 from this environment, so the git repo could not be cloned; the PyPI sdist pptx-mcp 0.18.0, which lists that repo as Homepage, was inspected instead)
commit: UNKNOWN (no git hash obtainable; analysed sdist pptx_mcp-0.18.0.tar.gz sha256 d002c1109197e13317a748a61602ad545061f4bfafae90e8f56038fe1fe61d8b)
licence: MIT License (LICENSE:1 in the sdist; PKG-INFO "License-Expression: MIT")
ran: yes (3 briefs, 19 slides via DeckGenerator and ReviewEngine called as a Python library, no MCP server and no LLM; PNG via soffice). Caveat: commit unpinned, so the ledger row for this repo must record the sdist hash, not a git hash.

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/swak/{a,b,c}.pptx, sheets, {a,b,c}-review.json. Driver: s12/run_swak.py (definitions validated by the package's own pydantic models).

## Findings

- [OBSERVATION] 53 slide types in a pydantic SlideType enum (title, section, content, ..., waterfall, executive_summary (SCR), scorecard (RAG), sensitivity_table, tornado_chart, heatmap, bridge, matrix, gantt, ... plus education types such as quiz) (pptx_mcp/models/slides.py; enum printed at run time). 12 chart types (ChartType). 8 diagram types in pptx_mcp/engine/diagrams/.
- [OBSERVATION] Spec boundary is a typed pydantic model (PresentationDefinition, SlideDefinition with ~70 typed optional fields). Invalid input fails at validation with field paths (my first run failed on "metadata: Field required" and "callout.body: Field required"). The model can still set positions, colours and fonts per element (TextBox, Position, TextStyle), so it does not meet the S3.2 "no coordinates from the model" rule unless restricted.
- [OBSERVATION] Layout method is template functions per slide type in engine/layouts.py with brand-token spacing (e.g. render_timeline_slide, layouts.py:1110), python-pptx output; native charts via python-pptx; bridge and waterfall are native stacked charts with hidden base (out/swak/a-3.png).
- [OBSERVATION] Financial archetypes present that others lack: bridge (baseline/volume/price/mix/fx/other/total kinds), sensitivity_table with baseline highlighting and heat shading (out/swak/a-4.png renders a gold-intensity heatmap grid), tornado, scorecard.
- [OBSERVATION] Review engine: 33 rules in 8 categories (README "Review Engine"), pptx-level spatial checks (overlap > 0.05 in, bounds, spacing 0.1 in, text overflow heuristic, whitespace ratio), WCAG contrast, font hierarchy, accent overuse, action-title and provenance rules. Scores were 0.9, 3.8 and 2.3 out of 10 with 89 / 53 / 48 issues, mostly whitespace "info" and layout warnings.
- [OBSERVATION] Text-fit is heuristic: no font-file measurement (no ImageFont, getlength or fontTools hits under pptx_mcp/), only bounding-box estimates in review/spatial.py:212 (check_text_overflow).
- [OBSERVATION] Output defects visible in the renders: the accent underline sits at a fixed y and strikes through the second line of every two-line title (out/swak/a-sheet.png, all slides); "$96.0m" KPI wraps to "$96.0 / m" and overlaps its label; matrix slide (c-3) renders only two quadrant headers and has an unreadable vertical y-axis label; the comps table's last row collides with the source line (b-3); exec-summary SCR panel shortens "Complication" to "Complicatio / n" (a-1). The repo's own review engine did not stop these.
- [OBSERVATION] Uniform check.py --strict audit: 32 / 113 / 31 fail instances (a/b/c), the worst of the field.
- [OBSERVATION] No RTL or Arabic support found in pptx_mcp/.
- [INFERENCE] Best archetype taxonomy and review-rule list of any candidate, but the layout engine is not robust enough to adopt: defects appear on ordinary content. Its models/slides.py is a useful vocabulary for S3.2 (SCR exec summary, bridge kinds, sensitivity table, scorecard).
- [UNKNOWN] Planner agents (agents/planner.py, content_mapper.py, iterator.py) and the plan cache were not run; they presumably call an LLM through the MCP host.

## Adopt / borrow ideas / skip

Borrow ideas (MIT would allow code reuse, but no pinned commit and visible layout defects): the slide-type vocabulary and field names for bridge, sensitivity_table, tornado, scorecard, SCR executive_summary; the 33-rule review list as a checklist for validate_pptx.py. Skip the renderer.
