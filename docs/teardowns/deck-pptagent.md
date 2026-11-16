# Teardown: icip-cas/PPTAgent

repo: https://github.com/icip-cas/PPTAgent
commit: 9dacac53ac9ef39346461063df729396551d929e
licence: MIT License (LICENSE:1; skills/pptagent/LICENSE also MIT)
ran: partial (deterministic HTML-to-PPTX path only: init, scaffold, host-written HTML for brief C (5 slides), review-slides render, build, PNG via soffice; brief A and B not run; no LLM or authoring agent run; the converter comes from PyPI pptagent==1.1.37 pinned by skills/pptagent/requirements.txt, not from this commit)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/pptagent/c.pptx, c-sheet.png, /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/ppta-html-sheet.png (browser renders), audit/pptagent_c.json. Driver: s12/mk_ppta.py (HTML written by hand from the brief). Chromium installed via playwright into the scratchpad.

## Findings

- [OBSERVATION] At HEAD the repo no longer contains the research runtime: it holds only skills/pptagent (SKILL.md, scripts/pptagent.py, scripts/pptagent_runtime/{core,visual,config}.py, 684 lines) plus README; the README points to tags v0.2.0 (EMNLP 2025 paper code) and v1.1.38 (DeepPresenter) for the earlier systems (README.md "IMPORTANT" box). The converter comes from the PyPI package: deeppresenter/html2pptx/html2pptx.js is 2,987 lines.
- [OBSERVATION] Architecture: the host agent authors one static HTML file per slide (1280x720 for 16:9, 960x720 for 4:3, 2244x3178 for A1), then a CLI renders (Playwright), converts to PPTX, and tracks review evidence by SHA-256 in workspace-state.json (references/task-contract.md; core.py:283-345). The model controls coordinates and CSS freely, the opposite of the S3.2 rule.
- [OBSERVATION] Layout method is HTML to PPTX: DOM geometry via getBoundingClientRect is mapped to pptxgenjs positioned shapes, text boxes and tables (html2pptx.js:2, 643, 1152-1157). Text wrapping is therefore decided by the browser's real font layout, not a heuristic; the task contract warns that "font metrics can differ after PPTX export" and asks for spare width (references/task-contract.md).
- [OBSERVATION] Run result for brief C: the hand-written HTML slides (exec summary, stacked column drawn from divs, 2x2 with positioned dots, 4-phase flow, table) converted with high fidelity (out/pptagent/c-sheet.png vs browser render out/ppta-html-sheet.png). The HTML table became a native table (1 <a:tbl> in slide5.xml); the stacked chart and 2x2 became shapes, chart_parts = 0 in the audit, so there are no data-bound charts unless authors use the converter's chart placeholder path (html2pptx.js:10 comment).
- [OBSERVATION] "Validator" is mostly procedural: slide reviews must be recorded per slide (verdict + summary) and the deck review recorded before finalize (SKILL.md "Create or revise"; core.py:211-243, 433-459). The only automatic quality signal in build was an empty quality_warnings list; there are no geometric rules (overflow, alignment, contrast) in the skill itself. It relies on a multimodal reviewer.
- [OBSERVATION] Uniform check.py --strict audit of the converted deck: 29 font_size, 24 font_size_table, 31 overlap and 2 text_overflow instances (text drawn on shapes counts as overlap; my CSS used 12-15 pt table text), fonts_used Liberation Sans.
- [OBSERVATION] Default task language is "zh" (init output). No RTL handling in skills/pptagent (no whole-word rtl or bidi hit); the converter's RTL behaviour was not inspected in depth.
- [INFERENCE] HTML to PPTX is the strongest answer to text-fit fidelity because the browser measures real glyphs, but it hands full layout freedom to the model and yields shape-built charts. For S3 the idea worth keeping is the review-evidence ledger (hash of inputs, stale-render detection) and DOM-as-measurement, not the authoring contract.
- [UNKNOWN] Quality of the earlier template-induction PPTAgent / DeepPresenter research systems and their PPTEval rubric: not in this commit; would need the v0.2.0 / v1.1.38 tags.

## Adopt / borrow ideas / skip

Borrow ideas (MIT): hash-based evidence of render/review freshness for the S3.8 critic loop; use a headless browser only as an optional measurement oracle for layout checks. Skip as an engine (free-form HTML contradicts schema-only model output; charts are shapes).
