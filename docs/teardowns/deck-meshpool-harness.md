# Teardown: reference/meshpool-harness slides engine

repo: /home/user/acretia/reference/meshpool-harness/engines/slides (vendored reference copy of the user's own harness)
commit: 3a510fd06f135bd08118aba0ba07b6978bcea14e (acretia repo HEAD; no separate upstream hash)
licence: MIT License (reference/meshpool-harness/LICENSE:1, "Copyright (c) 2026 Meshpool Harness contributors")
ran: yes (3 briefs, 19 slides: validate, render, QA, soffice PNG; icon-dependent archetypes could not run, see below)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/meshpool/{a,b,c}.pptx and sheets; specs in s12/specs/meshpool-*.json (hand-mapped from the briefs by s12/mk_meshpool.py).

## Findings

- [OBSERVATION] Spec-first design: a model writes JSON, a deterministic python-pptx renderer owns layout (engines/slides/engine.py:1-3; spec.py:1-28). Sixteen slide types: title, section, bullets, two_column, chart, table, kpi, timeline, quote, image_text plus exec_summary, numbered, cards, roadmap, stat_row, recommendation (spec.py:9-23, archetypes.py:290-297).
- [OBSERVATION] Schema rejects unknown fields and missing required ones with fix-ready messages (spec.py:44-52); soft style limits: 5 bullets, 15 words per bullet, 20 words per title (spec.py:24-28); label-style titles are warned (spec.py:52-54).
- [OBSERVATION] Text fit uses real font metrics: PIL ImageFont on Carlito (Calibri-metric) files, wrap and height computed with a 0.94 safety factor, shrink loop from preferred to minimum size in 0.5 pt steps, and a RenderError when even the minimum overflows (textfit.py:1-52, renderer.py:110-117).
- [OBSERVATION] Layout is absolute inches from design tokens (theme.py:1-30; MARGIN_X 0.6, BODY_TOP 1.75), 16:9, no constraint solver; content is placed per archetype by hand-written geometry.
- [OBSERVATION] Charts are native python-pptx charts: bar, column, stacked_column, line, pie, doughnut (renderer.py:22-28, add_chart at renderer.py:264). No waterfall, no football field, no 2x2, no process flow: the briefs' EBITDA bridge became a plain column chart with negative bars (out/meshpool/a-3.png, labels collide on small negatives).
- [OBSERVATION] QA rules (qa.py:43-112): slide_count, out_of_bounds, empty_placeholder, low_contrast (WCAG ratio), text_overflow, overlap, font_families. It flagged the brief-C roadmap chevron "PhaseName4: FFFFFF on 5A86E6 (3.5:1)" and returned non-zero.
- [OBSERVATION] The cards, numbered and stat_row archetypes need Lucide SVG icons, but engines/slides/icons/ contains only LICENSE-lucide.txt in this checkout, so brief C's 2x2 failed with FileNotFoundError for circle-dot.svg and was replaced by a bullets slide (spec: s12/specs/meshpool-c.json). Also cairosvg is a hard dependency of the icon path.
- [OBSERVATION] Output quality (out/meshpool/*-sheet.png): neat, readable, but visually generic (one accent, shadowed KPI cards, shadowed side panel). Roadmap chevrons read "Phase 1. 1. Partner" (double numbering because my labels were pre-numbered and the renderer prefixes again). Table column widths are heuristic: "Owner" wrapped to "Own / er" in a narrow column (out/meshpool/c-5.png).
- [OBSERVATION] Uniform check.py --strict audit: 12 / 91 / 10 fail instances (a/b/c), all font-size floors (tables below 14 pt, footers).
- [OBSERVATION] No RTL handling found (no whole-word rtl/bidi in engines/slides/*.py).
- [INFERENCE] This is the closest existing match to the S3 contract (schema-rejected spec, fit-or-error text, QA). Its weakness is breadth: no finance archetypes (bridge, football field, 2x2, comps) and shadows/cards that conflict with the S3.6 anti-slop list.
- [UNKNOWN] Pipeline (pipeline.py, 411 lines) and the LLM loop (engine.py) were not exercised: no keys exist here.

## Adopt / borrow ideas / skip

Adopt the spec validator pattern, the Carlito/PIL fit loop with a structured error (feeds S3.4 directly), and the contrast check. Do not adopt the shadowed card look or the Lucide icon dependency. Port as code (own licence permitting) into the S3 engine.
