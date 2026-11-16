# Teardown: pptx-mcp-server (two repos share the name)

The plan's "pptx-mcp-server" is ambiguous: PyPI/Glama list several. Two GitHub repos whose pyproject name is exactly "pptx-mcp-server" were cloned. swak's separate "pptx-mcp" is in deck-swak-pptx-mcp.md.

repo: https://github.com/shjanjua/pptx-mcp-server
commit: 775ef7c5b966480e229395b3346a0009c84597b4
licence: none found (no LICENSE file; pyproject.toml has no licence field) so all rights reserved by default
ran: partial (create_presentation_from_spec executed from tools/create.py with a hand-written spec covering brief A slides 1, 2 and 6; no MCP transport; other tools not run)

repo (alt): https://github.com/samos123/pptx-mcp
commit (alt): 7da5daa31634daf5116f82b04e3847a0c94f3330
licence (alt): Apache License (LICENSE:1-2)
ran (alt): no (read only: 12 low-level FastMCP tools that need an LLM to place each shape; not executed)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/pmcp/a.pptx and a-sheet.png. Driver: s12/run_pmcp.py (module loaded by path, python -I).

## Findings

- [OBSERVATION] shjanjua: JSON spec of absolute-positioned shapes: textbox, rectangle, rounded_rectangle, oval, image, line, each with left/top/width/height in inches, fill, font, paragraphs (tools/create.py:91-163). No tables, no charts, no archetypes. Companion tools: inventory (text extraction with positions), replace, rearrange, thumbnail grids, OOXML access (tools/*.py; README features).
- [OBSERVATION] Run result: three slides built from the spec rendered cleanly (out/pmcp/a-sheet.png) because I computed every coordinate myself; the library contributes no layout, fit or validation. check.py --strict: 0 fail, 1 warn (zero_size line).
- [OBSERVATION] Text fit: only word_wrap and margins; no measurement or autofit logic in tools/create.py:185-225.
- [OBSERVATION] shjanjua has no LICENSE file and no licence field in pyproject.toml; README.md:355 only credits the MCP protocol, not any code source.
- [INFERENCE] Its tool module names (inventory, replace, rearrange, thumbnail, ooxml) resemble the PPTX helper scripts in Anthropic's skills repository, which PLAN.md section 0 classes as source-available; I did not compare code, so derivation is unproven.
- [OBSERVATION] samos123: server.py (1,261 lines) has 12 @mcp.tool decorators, including create_or_clear_presentation, add_slide, add_title_and_content, add_textbox, add_shape (flowchart shapes), add_connector, delete_shape, modify_shape, add_picture, get_slide_content_description, get_slide_image (LibreOffice render to PNG for visual self-check) (server.py:204-662; README.md). Tool-per-shape design means a model spends one call per element and chooses all coordinates.
- [OBSERVATION] Neither repo has a validator, RTL support (no whole-word rtl/bidi hit), or native charts.
- [INFERENCE] Both are thin MCP wrappers over python-pptx. The render-and-look-back tool (samos123 get_slide_image) is the only idea relevant to the S3.8 critic loop, and we already have soffice to PNG.
- [UNKNOWN] Which of these (or neither) the plan meant by "pptx-mcp-server"; S1.1 should record the intended repo or drop the row.

## Adopt / borrow ideas / skip

Skip both. shjanjua has no licence and possible provenance issues; samos123 is Apache-2.0 but offers nothing beyond python-pptx calls.
