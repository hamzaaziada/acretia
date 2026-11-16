# Teardown: albertojb/mbb-ppt-generator

repo: https://github.com/albertojb/mbb-ppt-generator
commit: 74169bc5672d25a762e3dde3f96ee74380ace0d8
licence: Apache License (LICENSE:1-2; NOTICE credits Kaku Li's Mck-ppt-design-skill as the engine origin)
ran: yes (3 briefs, 19 slides: S3 content gate, engine render, S4 render gate; PNG via soffice)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/mbb/{a,b,c}.pptx, sheets, per-brief gate_content.json and gate_render.json under /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/mbb/{a,b,c}/. Driver: s12/run_mbb.py.

## Findings

- [OBSERVATION] The engine is a fork of Mck-ppt-design-skill: mbb_ppt/engine.py is 4,373 lines with 84 layout methods, same API shape as MckEngine plus extras (mekko, project_gantt, journey_map, insight_rail, cover_centered...) (mbb_ppt/engine.py; NOTICE). Palette is forest green with DM Sans/Arial claimed (README.md "What you get").
- [OBSERVATION] Same layout method and same weakness as the parent: absolute geometry per method; charts drawn from shapes (grep add_chart returns no hits in mbb_ppt/*.py); bridge in out/mbb/a-3.png is identical to the parent's apart from colour.
- [OBSERVATION] The distinctive part is a machine-readable two-gate workflow. S3 content gate (references/scripts/gate_check_content.py:1-48) checks tuple arity against api-schemas.yaml, count limits (data_table <= 8 rows, horizontal_bar <= 8 items, process_chevron label <= 3 chars), source on every content slide, title length 10-120 chars, caps on executive_summary (15%) and any single layout (25%), and a visual-density floor (max(2, N//4) chart/diagram layouts for decks of 6+). `passed` is computed by code.
- [OBSERVATION] On the briefs the content gate failed all three before any rendering, each with an actionable message: A "timeline last milestone label 'Dec Sign' is 8 chars > 6; will overflow"; B "data_table.rows max 8; got 10", "horizontal_bar.items max 8; got 9", exec_summary used 3x (43%), visual density 1 where 2 required; C "process_chevron slot[0] (label) is 'Q2 to Q3 2027' (13 chars > 3)". Rendering anyway truncated the label to 'Q2' with a stderr WARN (out/mbb/c-4.png).
- [OBSERVATION] S4 render gate (gate_check_render.py, PptQA from the Mck lineage) scored the decks 38, 50 and 77 and failed all three ("fix 15 / 78 / 6 user_code_errors"), mostly text_overflow estimates of 36-43% on dense slides. Unlike the parent's "QA passed", this gate would have blocked delivery of the same defective output.
- [OBSERVATION] Text fit remains a char-count estimate (qa.py, 915 lines, identical to the parent's _estimate_text_height). No glyph metrics.
- [OBSERVATION] Uniform check.py --strict audit: 30 / 23 / 27 fail instances (a/b/c), same causes as the parent.
- [OBSERVATION] No RTL or Arabic support found.
- [OBSERVATION] The repo is agent-process heavy (CLAUDE.md, CONTEXT.md, DECISIONS.md, ROADMAP.md, experiences/*.md self-refinement log), 22 tests per README badge.
- [INFERENCE] The idea worth taking is the content gate as a first-class stage before render, with per-layout arity and budget rules and deck-level monotony caps, and the rule that `passed` is a boolean computed by code. The layouts themselves are inherited.
- [UNKNOWN] The "experiences/*.md" self-refinement loop was not exercised or evaluated.

## Adopt / borrow ideas / skip

Borrow ideas for S3.1/S3.2/S3.7: pre-render content gate with budgets, deck-level layout-share cap and visual-density floor, and structured fail items {slide_idx, layout, check, message}. Skip the engine (inherited shape-drawn charts). Apache-2.0 would allow reuse but not needed.
