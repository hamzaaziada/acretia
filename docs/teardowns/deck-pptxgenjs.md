# Teardown: PptxGenJS

repo: https://github.com/gitbrent/PptxGenJS
commit: 3c9ec1b687c174952166f6a34b5e87ebf69fa469
licence: The MIT License (MIT) (LICENSE:1; version 4.0.1 in package.json:3)
ran: yes (3 briefs, 19 slides built with a Node script requiring the repo's own dist/pptxgen.cjs.js; jszip installed from npm into a scratch folder; PNG via soffice)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/pptxgenjs/{a,b,c}.pptx, sheets, audit/pptxgenjs_*.json. Driver: s12/run_pgjs.js (hand-written layout code driven by the brief JSON).

## Findings

- [OBSERVATION] It is a library of primitives, not an archetype engine: addText, addShape (SHAPE_TYPE enum), addTable, addChart, addImage, addMedia, master slides (src/slide.ts:167-213; core-enums.ts:329). Chart types: area, bar, bar3D, bubble, bubble3D, doughnut, line, pie, radar, scatter (core-enums.ts:697-708). There is no waterfall, football-field or combo-with-hidden-series type.
- [OBSERVATION] Native charts work and are data-bound chart parts (chart_parts 1-2 in each deck audit; embedded workbook not inspected). Floating bars need a hack: a white first series in a stacked bar. In the football field the white series covers the plot gridlines, so bars appear to float but gridline segments are visibly interrupted (out/pptxgenjs/b-sheet.png slide 5). The EBITDA bridge used the same hack with a four-series stack (out/pptxgenjs/a-sheet.png slide 3) and rendered correctly, but with no data labels.
- [OBSERVATION] Default data labels round to integers on the ranked bar (10.8 shows as 11) unless a number format is set (out/pptxgenjs/b-sheet.png slide 4); catAxis/valAxis options include valAxisMinVal, barGrouping, catAxisOrientation (core-interfaces.ts:1356, 1434, 1463).
- [OBSERVATION] Text fit: only a flag. TextProps have fit: 'none' | 'shrink' | 'resize', autoFit and shrinkText (core-interfaces.ts:1014, 1105-1110). These write bodyPr autofit attributes that PowerPoint applies on edit/open; no measurement happens in the library.
- [OBSERVATION] Layout method: absolute coordinates in inches supplied by the caller; tables have auto-pagination options (autoPage* in core-interfaces.ts); no constraint solver.
- [OBSERVATION] RTL: paragraph-level rtlMode writes rtl="1" (core-interfaces.ts:1082, 1864; gen-xml.ts:840). Only that flag: no shaping, no layout mirroring.
- [OBSERVATION] Validator: none in the library. Uniform check.py --strict audit of my decks: a 0 fail / 1 warn; b 76 fail (all font_size_table at 12 pt); c 8 overlap fails (labels on shapes).
- [OBSERVATION] Output quality is as good as the caller's layout: with simple geometry the three decks are clean and typographically consistent (out/pptxgenjs/a-sheet.png), and chevron/timeline text had to use shrink to fit.
- [INFERENCE] Equivalent in capability to python-pptx for our needs, with a few conveniences (stacked chart options, rtlMode, table pagination). Since S3.3 names python-pptx as primary, PptxGenJS adds a Node dependency for little gain; its one distinct asset is the paragraph rtlMode switch, which python-pptx can set through XML.
- [UNKNOWN] Whether PowerPoint honours fit:'shrink' identically to LibreOffice; not testable here.

## Adopt / borrow ideas / skip

Skip as a dependency (ledger decision: skip or scratch fallback only). Borrow ideas: stacked-series-with-hidden-base pattern for floating bars (already in om/pptx.py), rtl="1" paragraph attribute for S3.5.
