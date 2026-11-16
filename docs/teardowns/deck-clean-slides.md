# Teardown: tmustier/clean-slides

repo: https://github.com/tmustier/clean-slides
commit: c67a56a31cba898eb6e76314f80d6b3301d71975
licence: MIT License (LICENSE:1)
ran: yes (3 briefs: table-type slides via `pptx generate` YAML, charts via `pptx charts` JSON, 19 slides' worth of content; PNG via soffice)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/cleanslides/{a,b,c}-tables.pptx, {a-3,b-4,b-5,c-2}-chart.pptx and PNGs, YAML/JSON specs alongside. Driver: s12/mk_cs.py. Installed with pip install -e inside a venv.

## Findings

- [OBSERVATION] Deliberately narrow: "a text table tool, not a presentation platform" (README.md "What it doesn't do"). One YAML spec = one slide with a title, subtitle and a table (rows, cols, col/row headers, row_overrides, inline **bold**, icon indicators, sidebars) (docs/INPUT-SCHEMA.md). Charts are a separate alpha JSON path: clustered, stacked, waterfall (docs/CHARTS.md).
- [OBSERVATION] Layout method is template-placeholder based: a bundled or user template (.clean-slides/template.pptx plus config.yaml) supplies layouts; the tool fills title/subtitle placeholders and places the table with a solver (clean_slides/solver.py:1-25: column sizing, row sizing, verification). Template cloning is first-class (pptx init -t corporate.pptx, README/SKILL.md "Setup").
- [OBSERVATION] Fit method is a character-class width heuristic, not font metrics: narrow/wide/upper/digit factors and a Georgia 1.05 factor (clean_slides/text_metrics.py:11-25); the solver tries sizing then a LayoutVerifier reports issues (verification.py:30-97).
- [OBSERVATION] Briefs' non-table slides had to be mapped onto tables (exec summary and bullets as a one-column table, KPIs as a 2-row table, timeline and process flow as a 2-row table, 2x2 as a 2x2 table, out/cleanslides/{a,b,c}-tables.pptx); EBITDA bridge, ranked bar, football field and stacked column went through the chart path (4 separate one-slide files). Table output is crisp and minimal (hairline rules, bold row headers in accent colour, out/cleanslides/a-tables-sheet.png) but body text is small (12-14 pt) and large dead space remains below tables; no table borders in the default template.
- [OBSERVATION] Native charts: waterfall is built from stacked series with connector lines and "overlay labels" (out/cleanslides/a-3-chart-1.png: correct bridge, but duplicate labels, data-label and overlay both shown). The football field became a plain stacked bar with a visible first series (b-5-chart-1.png) and the chart title overlaps the first bar. Each chart file is a separate 4:3 one-slide deck (500 x 375 px at 50 dpi, a-3-chart-1.png), not a chart inside the 16:9 table deck; merging needs pptx insert.
- [OBSERVATION] Inspection and edit tooling is a real strength: pptx show/slide/shape/xml/edit/batch/render/crop/merge/verify (pptx --help). pptx validate flagged "Column headers disabled" notes without failing.
- [OBSERVATION] RTL: only default `rtlCol="0"` / `rtl="0"` attributes written by xml_helpers.py:80,132,244; no RTL support.
- [OBSERVATION] Uniform check.py --strict audit: 3 / 8 / 5 fail instances for the table decks (text_overflow estimates), with 13-25 warnings each.
- [INFERENCE] The valuable ideas are the placeholder-filling model (build into a client's layouts, which is S3.9) and the inspect/edit/merge CLI. As an S3 engine it is too narrow.
- [UNKNOWN] Whether the solver's row heights match PowerPoint (only LibreOffice available).

## Adopt / borrow ideas / skip

Borrow ideas (MIT permits reuse): template init + config.yaml for firm templates (S3.9), the placeholder-based fill, and the inspection CLI for debugging. Skip it as a primary renderer.
