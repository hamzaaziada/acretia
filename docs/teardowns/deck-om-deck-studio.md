# Teardown: Acretia om/ Deck Studio (baseline)

repo: /home/user/acretia (om/layout.py, om/pptx.py, om/spacing.py, om/house.py, om/decks.py)
commit: 3a510fd06f135bd08118aba0ba07b6978bcea14e
licence: project-internal (repo's own code; no licence header)
ran: yes (3 briefs: 19 slides built via om.layout.render + om.pptx.Deck; om.spacing.check and deck_check run on every layout; rendered via soffice to PNG at 50 dpi)

Run artefacts (outside the repo): /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/om/{a,b,c}.pptx, {a,b,c}-sheet.png, plus audit JSON in /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/audit/om_*.json. Generator: s12/run_om.py (hand-mapped from the briefs; no LLM).

## Findings

- [OBSERVATION] Output is real native OOXML written without python-pptx: "Dependency-free .pptx writer ... native text, native tables and native charts (bar / column / stacked / floating football-field)" (om/pptx.py:1-10). Charts are literal-data charts (`lit_str`/`lit_num`, om/pptx.py:249-255), so values are not bound to an embedded workbook.
- [OBSERVATION] Layout method is absolute coordinates in inches on a 13.333 x 7.5 canvas, expressed as layout JSON primitives (text, shape, line, table, chart, image_crop, icon, component) (om/layout.py:28-62). Ten reusable components expand to primitives: exhibit_frame, stat_callout, change_badge, takeaway_box, process_flow, icon_grid, callout_card, numbered_heading, dot_plot, bridge (om/layout.py:396-700).
- [OBSERVATION] Archetype coverage achieved on the briefs: exec summary (text), KPI row (stat_callout x4 plus takeaway_box), EBITDA bridge (native chart kind "waterfall", out/om/a-3.png), tables (native, bold rows), ranked bar with highlighted point (point_colors, out/om/b-4.png), football field (native floating bar, but only reachable by calling Slide.chart(hidden_first=True) directly because layout._chart passes hidden_first only for the waterfall kind, om/layout.py:260-292), 2x2 (hand-placed rect/ellipse/text, out/om/c-3.png), process flow and timeline (process_flow component), stacked column. Missing as first-class archetypes: 2x2, football field, Gantt, issue tree, market map, quote, divider.
- [OBSERVATION] Text-fit is a heuristic, not font metrics: "glyphs ~ 0.5 em wide, lines 1.2 em" (om/spacing.py:68-80). Fit order (reflow, tighten, shrink) is not implemented; the validator only reports.
- [OBSERVATION] Validator rules (om/spacing.py:109-355): off-canvas, safe-margin 0.5 in, eyebrow-above-title, min 10 pt anywhere, 14 pt body, 11 pt labels and chart labels, card padding 0.2 in, overlaps, empty-card detection, content-area coverage, 25 words per block and 110 per slide, gap grid (0.3 or 0.5 in, one per slide), edge alignment, equal-card sizes, and deck rules (title rule, footer rule, page number, title and footer position consistency, lines 321-355). It returns prose messages that cite a label, not stable shape ids.
- [OBSERVATION] On the 3 briefs the validator found 8 / 5 / 27 issues (e.g. "Source ... sits 0.15 in from waterfall chart; leave at least 0.3 in", 73-word exec-summary block). Most 2x2 findings were my hand-placed quadrants: the checker is strict but has no 2x2 component to avoid them. Uniform audit with LangAlpha check.py --strict: 0 / 77 / 8 fail instances (a/b/c; b is mostly 12 pt table text below its 14 pt table floor).
- [OBSERVATION] Render quality (out/om/*-sheet.png): clean, restrained banker look, consistent title rule and footer with page number. Defects seen: exhibit_frame prints ", $m" with a leading comma when only "unit" is passed (om/layout.py:408 builds ", " + unit); waterfall bars at 9 pt data labels; deltas squashed because the axis starts at 0 (82 vs 9.5); football-field data labels show span width rather than low/high.
- [OBSERVATION] No RTL or Arabic handling: no case-insensitive whole-word match for rtl or bidi in om/*.py.
- [OBSERVATION] Offline test suite green before and after: 356 tests (python3 -m unittest discover -s tests -q).
- [INFERENCE] The strongest asset for S3 is the combination of a dependency-free chart writer (floating bars already solved) and a house-rule validator that already encodes the user's title/footer/no-eyebrow rules. The gap is breadth (archetypes), measured text fit, and a schema boundary that keeps models away from coordinates.
- [UNKNOWN] Whether the literal-data charts open without a "repair" prompt in desktop PowerPoint; only LibreOffice was available.

## Adopt / borrow ideas / skip

Adopt as the base (it is ours). Keep om/pptx.py chart XML (floating bars), om/house.py grid, and om/spacing.py rules; replace the 0.5 em heuristic with real glyph metrics (S3.4), add the missing archetypes as components, and make validator output carry shape ids (S3.7).
