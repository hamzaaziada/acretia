# Teardown: python-pptx

repo: https://github.com/scanny/python-pptx
commit: 278b47b1dedd5b46ee84c286e77cdfb0bf4594be
licence: The MIT License (MIT) (LICENSE:1; __version__ 1.0.2 at src/pptx/__init__.py:28)
ran: yes (library probe against the cloned HEAD source: fit_text with Carlito-Bold, a stacked chart, save; and as the substrate of meshpool, Mck, mbb, swak, clean-slides, AutoPresent and pptx-mcp-server runs in this packet, which all rendered through it)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/pyp.pptx. Probe: inline script run with sys.path pointing to repos/python-pptx/src.

## Findings

- [OBSERVATION] Pure object-model library over OOXML, no layout engine: shapes are placed by EMU coordinates, layouts come from the template (Presentation default template is 4:3; I set 13.333 x 7.5 in manually). Autoshapes use <a:bodyPr rtlCol="0"> by default (src/pptx/oxml/shapes/autoshape.py:284,337).
- [OBSERVATION] Text fitting exists but is one function: TextFrame.fit_text(font_family, max_size, bold, italic, font_file) (src/pptx/text/text.py:78) backed by TextFitter, which binary-searches whole-point sizes against a PIL ImageFont file (src/pptx/text/layout.py:15-40). The probe fitted a 118-character title into 11.9 x 0.95 in at 28 pt bold with Carlito-Bold.ttf and wrote 28.0 pt. It requires the caller to pass a font file and does not handle mixed runs.
- [OBSERVATION] XL_CHART_TYPE has 73 members (src/pptx/enum/chart.py); none is a waterfall, box, funnel or sunburst, so a bridge or football field needs a stacked chart with a no-fill series, set by XML or series.format.fill.background().
- [OBSERVATION] Chart creation writes an embedded Excel workbook (XlsxWriter dependency in pyproject.toml), so charts remain editable in PowerPoint (features/cht-*.feature, tests/chart). The probe built a COLUMN_STACKED chart in one call.
- [OBSERVATION] No RTL API: only a:rtl appears as a successor element in the oxml text schema (src/pptx/oxml/text.py:297,309); paragraph direction needs raw XML.
- [OBSERVATION] No validator, no overlap or bounds checks, no archetypes. Everything in the briefs that was not a table, chart or textbox had to be assembled by callers (as every other candidate does).
- [INFERENCE] It is the right substrate for S3.3 (as the plan states): MIT, mature, native charts with embedded data, fit_text for single-style titles. What S3 needs on top is a measurement layer for multi-run, multi-paragraph text (S3.4), RTL helpers (S3.5) and a chart helper for floating bars.
- [UNKNOWN] Behaviour with Arabic shaping: not tested.

## Adopt / borrow ideas / skip

Adopt (MIT) as the primary renderer substrate. Own the layout, fit and validator layers; do not depend on fit_text for anything beyond single-style titles.
