# S3.3 archetype packet brief (shared by the three archetype workers)

Read: `docs/deck-engine.md` (contract), `om/house.py` STYLE_GUIDE (visual grammar, devices, "Never" list),
`om/deck/archetypes/__init__.py`, `om/deck/archetypes/base.py` (frame, content_box, text_el, line_el,
fitted, figure_runs, solved, eid), `om/deck/archetypes/core.py` (the pattern to copy: `chart_takeaways`),
`om/deck/model.py`, `om/deck/theme.py` (grid_x/grid_w), `om/deck/validate.py` (what is checked).
Ideas (MIT, user's own): `reference/meshpool-harness/engines/slides/archetypes.py`, `renderer.py`.

## Every archetype
- `@register(id, schema=..., visual_type=..., data=...)` with a strict JSON-schema fragment for `blocks`
  (`additionalProperties: false`, minItems/maxItems that keep the slide readable), and an entry in the
  module-level `EXAMPLES = {id: {"title": ..., "blocks": {...}, "source": ..., "as_of": ...}}` with
  realistic finance content (numbers, units, a so-what). The registry attaches `EXAMPLES` automatically.
- Returns `base.solved(...)` with the house frame from `base.frame` (title, title rule, subtitle with
  the measure in bold and the unit, source + as-of line on data slides, footer rule, footer, page number).
  Never an eyebrow, kicker or section tag above the title.
- Geometry only from `theme.grid_x/grid_w` (12 columns inside 0.7 in margins, 0.2 in gutters) and the
  house grid rows; one gap value per deck (`ctx.gap`). Left/right edges on column edges.
- All text through `base.fitted(...)` with floors (body 14 → floor 12; tables 12, dense tables 10);
  never rely on autofit. On `FitError` raise it (the content step cuts or splits), do not silently clip.
- ≤ 4 distinct font sizes per slide across text and tables (title 24, body 14, label 12, note 10 is the
  default set; a stat callout at 40 replaces label 12 on that slide).
- Bold key figures via `base.figure_runs` (never a whole sentence bold). One accent colour, used only on
  the bar/number/series that carries the message; context in `mute_bar`/`muted`; text `text`.
- A visible so-what on every data slide (stat callout, change badge or takeaway box).
- Direct labels instead of legends; no gridlines; data labels readable: dark labels on light fills,
  `background` labels on dark fills, or labels outside the bar end.
- No gradients, shadows, 3D, rounded-card grids (≤ 2 `roundRect`), clip art, emojis, em dashes, `!`.
- Text-free visuals only (`ctx.visual` PNG from the visual layer); no words drawn inside images.
- RTL: must work with `ctx.rtl=True` (base.solved mirrors); text aligned right; no left-only assumptions.

## Every archetype's tests (your test file)
For each id in your module: build from `EXAMPLES[id]` (LTR) and again with `rtl=True` and Arabic text in
the title and one block, render with `om.deck.render.render`, run `om.deck.validate.validate` on the
bytes and assert **0 critical and 0 major** findings (print them on failure); assert the shape names
are the element ids, the archetype's `visual_type` is set, and for chart archetypes the chart is a
native chart part whose cached values equal the spec values. Also render all your examples into one
deck and, if `soffice` is on PATH, convert to PDF + `pdftoppm -r 60` PNGs into a temp dir (smoke only).
