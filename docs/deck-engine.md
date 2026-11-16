# Deck engine v2 (Stage 3): interface contract

Owner: session B (S3). Every S3 worker codes against this file. If a worker needs an interface that is not
here, it reports a blocker instead of inventing one that another worker will not know about.

Package: `om/deck/` (D-S3-01). Renderer: python-pptx 1.0.2 (MIT, ledger row `scanny/python-pptx`).
Measurement: fonttools (MIT) + arabic-reshaper (MIT). python-bidi (LGPL) is **not** used (D-S3-03).
The v1 Studio path (`om/studio.py`, `om/layout.py`, `om/pptx.py`) keeps working; it is not rewritten.
`om/house.py` stays the single source of truth for grid, type scale and palette.

## Pipeline

```
brief ─▶ GhostDeck (action titles only; lints + 1 LLM horizontal-logic check; approval flag)
      ─▶ DeckSpec (SlideSpec per slide: archetype id + structured blocks + source + as_of; no geometry)
      ─▶ art direction for the deck (visuals library) + N candidates per non-data visual, best kept
      ─▶ archetype.build(slide_spec, ctx) ─▶ SolvedSlide (elements with geometry, fitted text)
      ─▶ render(SolvedSlides, theme) ─▶ .pptx (native charts/tables; shape name == element id)
      ─▶ validate_pptx (deterministic; critical = blocking) ─▶ vision critic loop (≤3, after validator passes)
```

## Units, canvas, tokens

- Canvas 13.333 × 7.5 in. All geometry in **inches**, origin top-left, floats rounded to 0.01.
- 12-column grid inside the margins (`house.GRID["margin_x"]` = 0.7 in each side), gutter 0.2 in.
  `om.deck.theme.grid_x(col)` / `grid_w(span)` give exact column edges. Every content element's left
  and right edges sit on a column edge (± 0.02 in snap).
- Colours are **tokens**, never hex, everywhere above the renderer: `text`, `background`, `accent`,
  `secondary`, `series2`, `series3`, `light`, `panel`, `muted`, `mute_bar`, `positive`, `negative`,
  `key_message`. `Theme.colors[token] -> "#RRGGBB"`; the renderer writes them as scheme colours where a
  theme slot exists (`text`→dk1, `background`→lt1, `secondary`→dk2, `panel`→lt2, `accent`→accent1,
  `series2`→accent2, `series3`→accent3, `light`→accent4, `positive`→accent5, `negative`→accent6) and as
  exact srgb otherwise.
- Fonts are roles: `major` (headings, stat numbers) and `minor` (everything else). The renderer writes
  `+mj-lt` / `+mn-lt` (and `+mj-cs` / `+mn-cs` for Arabic), so every font is a theme font.
- Type sizes (pt): title 24, body 14, label 12, note/footer 10, stat 40, divider 40, cover 44. At most
  **4 distinct sizes per slide** across text frames and tables (D-S3-05); chart-internal text is 12 pt
  and does not count, but must be ≥ 10. Floors: body ≥ 10 after shrink, tables ≥ 14 → shrink floor 12 for
  dense tables only when flagged `dense: true` (comps), never below 10.

## `om.deck.model` — SolvedSlide (the only input to the renderer and the validator's oracle)

```python
@dataclass
class Run:      t: str; b: bool = False; color: str | None = None        # token
@dataclass
class Para:     runs: list[Run]; align: str = "l"; level: int = 0; bullet: bool = False; space_after: float = 4
@dataclass
class TextSpec: paras: list[Para]; size: float; font: str = "minor"; color: str = "text";
                valign: str = "t"; inset: float = 0.0; autofit: bool = False      # autofit is always False
@dataclass
class Element:
    id: str            # unique in the deck: f"s{index}.{role}[.{suffix}]", e.g. "s3.title", "s3.chart",
                       # "s3.kpi.2" -- the validator recovers the role from the id, so the role comes first
    kind: str          # text | rect | line | chart | table | image
    role: str          # title | title_rule | subtitle | body | callout | kpi | label | chart | table | visual
                       # | source | footer_rule | footer | page_number | divider | cover | decor
    x: float; y: float; w: float; h: float
    text: TextSpec | None = None
    fill: str | None = None              # token
    line: tuple[str, float] | None = None   # (token, width pt)
    chart: dict | None = None            # ChartSpec below
    table: dict | None = None            # TableSpec below
    image: dict | None = None            # {"png": bytes, "alt": str, "style": str, "candidate_id": str}
    binding: dict | None = None          # {"manifest_id": str, "kind": "chart|table|value", "format": str}
@dataclass
class SolvedSlide:
    index: int                           # 1-based page number
    archetype: str
    elements: list[Element]
    rtl: bool = False
    notes: str = ""
    visual_type: str = ""                # for variety rules: e.g. "bar", "waterfall", "illustration:isometric"
    meta: dict = field(default_factory=dict)
```

Lines are elements with `kind="line"`, `h == 0` (horizontal) or `w == 0` (vertical).
`to_dict()/from_dict()` round-trip (PNG bytes as base64).

ChartSpec: `{"type": bar|column|stacked_bar|stacked_column|line|area|scatter|pie|doughnut|waterfall|
football_field|combo, "categories": [str], "series": [{"name": str, "values": [float|None],
"color": token?, "point_colors": {idx: token}?, "binding": manifest_id?}], "number_format": "0.0",
"labels": bool, "gridlines": False, "legend": bool, "axis_title": str?, "highlight": [idx]?}`.
Waterfall = stacked column with an invisible base series; totals drawn from zero; it must foot.
Football field = stacked bar with an invisible low series and a visible range series.

TableSpec: `{"columns": [str], "rows": [[str]], "col_align": ["l"|"r"|"c"], "bold_rows": [int],
"highlight_col": int?, "size": float, "dense": bool, "bindings": {"r,c": manifest_id}?}`.

## `om.deck.theme`

`Theme(name, colors: dict[token, hex], fonts: {"major": str, "minor": str, "major_cs": str,
"minor_cs": str}, sizes: dict, grid: dict)`. `Theme.house()` builds from `om/house.py`
(heading Cambria → major, body Arial → minor; Arabic cs fonts "Arial" with measurement proxy
Noto Sans Arabic). `Theme.to_dict/from_dict`. `grid_x(col: int) -> float` (col 0..12),
`grid_w(span: int) -> float`.

## `om.deck.render`

`render(slides: list[SolvedSlide], theme: Theme, *, title: str, template: str | None = None) -> bytes`
- Shape `name` = element `id` (the validator and critic name shapes by it). Charts, tables native.
- No autofit, no shadows, no gradients, no 3D; word wrap on; insets from the TextSpec.
- RTL slides: `a:pPr rtl="1"`, `algn="r"` default, table `rtl="1"` on `a:tblPr`, charts reversed
  category axis (`c:scaling/c:orientation maxMin`) and axis on the right; theme `cs` fonts set.
- Slide notes from `SolvedSlide.notes`. Image elements as pictures with `descr` = alt text.
- Bindings written to the shape as `<p:cNvPr descr=...>` is reserved for alt text, so bindings go to a
  deck-level custom XML part `customXml/acretia-bindings.json`-style JSON stored as a package part
  `/acretia/bindings.json` (`{element_id: binding}`), read back by `om.deck.sync`.

## `om.deck.metrics` / `om.deck.fit` / `om.deck.rtl`

```python
metrics.measure(text, size_pt, width_in, *, bold=False, font="minor", rtl=None, line_spacing=1.0)
    -> Measure(lines: int, height_in: float, widest_in: float, line_texts: list[str])
metrics.text_width(text, size_pt, *, bold=False, font="minor") -> float      # inches, single line
fit.fit_text(paras: list[Para], w, h, *, size, floor, role, block_id, inset=0.0) -> FitResult
    # order: reflow (re-wrap only) -> tighten (space_after to 0, line spacing 0.9) -> shrink 1pt steps to floor
    # -> FitError(block_id, words_over, chars_over, message="body block 2 is 38 words over; cut or split")
FitResult(ok: bool, size: float, paras: list[Para], line_spacing: float, height_in: float, steps: list[str],
          error: FitError | None)
rtl.is_rtl(text) -> bool; rtl.shape(text) -> str (reshaped for measurement only, never written to pptx);
rtl.mirror_x(x, w, canvas_w=13.333) -> float; rtl.mirror(slide: SolvedSlide) -> SolvedSlide
```
Measurement fonts (metric-compatible): Arial→Liberation Sans, Calibri→Carlito, Cambria→Caladea if
present else Liberation Serif ×1.0, Arabic→Noto Sans Arabic. Line height = 1.2 × size. A ≥ 3 %
safety margin on width. Font files are found via `fc-match`/known paths; missing fonts fall back to
DejaVu with a warning, never a crash.

## `om.deck.spec` — DeckSpec v2 (what a model writes)

```json
{"deck_id": "...", "title": "...", "lang": "en|ar", "client": "...", "as_of": "2026-09-30",
 "art_direction": "auto|<style id>", "theme": "house|<profile id>",
 "slides": [{"id": "s1", "archetype": "exec_summary", "title": "Action title ≤15 words",
             "blocks": {...archetype-specific...}, "source": "...", "as_of": "...", "notes": "...",
             "visual": {"concept": "...", "kind": "illustration|hero|diagram|icon_system|none"}}]}
```
Schema-rejected anywhere in a spec: keys `x, y, w, h, left, top, width, height, font, font_size,
size, color, colour, fill, rgb, hex` and any `#RRGGBB` string value. Each archetype publishes a
JSON-schema fragment for its `blocks` (`archetypes.REGISTRY[id].schema`).

## `om.deck.archetypes`

`REGISTRY: dict[str, Archetype]`, auto-discovered from modules in the package (pkgutil), so adding a
module needs no edit to `__init__.py`.
```python
@register("waterfall", schema={...}, visual_type="waterfall", data=True)
def build(slide: dict, ctx: BuildContext) -> SolvedSlide
BuildContext(theme, index, total, deck_title, rtl, lang, gap=0.3, visual: dict | None, manifest: dict | None)
base.frame(slide, ctx) -> list[Element]    # title, title_rule, subtitle?, source/note, footer_rule, footer, page_number
base.content_box(ctx) -> (x, y, w, h)       # area between subtitle and note line
```
Every content slide gets the house frame. Cover and divider archetypes skip the title rule but keep
the footer rule + page number (except the cover, which has no page number).

## `om.deck.visuals` (S3.11)

`library.STYLES` (≥ 8 visual languages with prompt templates, SVG-designer rules and palette usage);
`probe.image_endpoint(router=None) -> {"available": bool, "reason": str, "checked_at": iso}` (run every
deck run); `generate.candidates(concept, style, n=3, *, router, seed) -> list[Candidate]` using the image
model if available, else the SVG designer through `om/llm.py`, else (offline/replay miss) the
procedural generator; `score.score(candidate, theme) -> dict` (deterministic) + optional VLM score;
`choose(...)`; `variety.check(slides) -> list[Finding]`; `variety.signature(slide)`; `log.record(...)`
appends to `data/deck_styles/scores.jsonl` and `library.weights()` prefers winners.

## Findings (validator, slop, variety, critic)

`{"severity": "critical|major|minor", "rule": "overflow|overlap|bounds|grid|contrast|font_floor|
type_sizes|banned_phrase|punctuation|xml|house_title_rule|house_footer|house_eyebrow|theme_font|
theme_color|whitespace|slop|variety|...", "slide": int, "shape_id": int|None, "shape_name": str|None,
"message": str}`. `scripts/validate_pptx.py deck.pptx [--json]` exits 1 on any critical finding.

## Additions (wave 3)

- Element kinds `shape` (`shape={"prst": "chevron|homePlate|diamond|ellipse|triangle|downTriangle|rect"}`,
  fill/line tokens, optional text) and `connector` (`connector={"type": "elbow|straight", "start": [x, y],
  "end": [x, y], "arrow": bool}`) render as native PowerPoint autoshapes/connectors (FP-S3-a).
- Reserved spec keys apply to archetype blocks too: data coordinates use `xv`/`yv`, option columns use
  `a`/`b` (D-S3-10).
- Provenance: archetype-computed figures (medians, totals, CAGR, implied values) are declared by the
  archetype in `SolvedSlide.meta["derived"] = [{"value": float, "from": [paths]}]` and count as sourced;
  prose numbers must appear in a sourced data block of the same slide or any slide of the deck (D-S3-11).
- Citations (#19): a slide's `sources` list (or single `source`) renders as `Source: [1] ...; [2] ...`
  in the note line; text/cells may carry `[n]` markers that must resolve to that list.
