# S3 gate spec (`scripts/verify_s3.py`)

Written by the Boss (D-027); implemented by a Sonnet gate writer who has not seen the implementers'
tests. The gate is offline: it monkeypatches `socket.socket`/`socket.create_connection` to raise for the
whole run, sets `ACRETIA_LLM_MODE=replay`, and never needs a key. Each check prints
`PASS|FAIL|SKIP <id> <one line evidence>`; exit 0 only if no FAIL. SKIP is allowed only for checks that
need LibreOffice/poppler when they are absent, and the reason is printed.

## A. Deck set (S3.10 corpus)
- A1 `evals/decks/briefs/` holds exactly 20 briefs, ≥ 3 with `lang: ar`; each has a spec that passes
  `om.deck.spec.validate` with 0 errors.
- A2 All 20 build end to end through the engine entry point (no LLM: replay/offline path) into `.pptx`
  in a temp dir; build time per deck printed.
- A3 `om.deck.validate` on all 20: **0 critical findings** in total; major count per deck printed;
  ≤ 2 major per deck.
- A4 With `soffice` present: every deck converts to PDF and `pdfinfo` page count == slide count.
- A5 Anti-slop over all text in all 20 decks (text frames, tables, chart titles, notes excluded):
  0 banned phrases, 0 em dashes, 0 emojis, 0 `!`.
- A6 House rules on every content slide of every deck: a `title_rule` line under the title spanning
  ≥ 90 % margin-to-margin; a `footer_rule`; a `page_number` whose text == slide index; no text shape
  above the title (no eyebrow).
- A7 Every data slide (archetype `data=True`) has a source line containing "Source" and an as-of date.

## B. Spec and ghost deck (S3.1/S3.2) — adversarial
- B1 `spec.validate` rejects, with the exact JSON path, each of: a top-level `x`, a nested
  `blocks.items[2].font_size`, a `fill`, a `#1A2B3C` string deep in a table cell, `rgb(1,2,3)`.
- B2 Unknown archetype id → error naming close matches.
- B3 Ghost lint flags each planted defect: 20-word title, generic "Overview" title, duplicate titles,
  missing number on a data slide, trailing full stop, em dash; and passes a clean 8-slide ghost.
- B4 The engine refuses to render an unapproved ghost deck (`GhostNotApproved`), and renders after
  `approve()`.

## C. Archetypes and native charts (S3.3)
- C1 `REGISTRY` has ≥ 35 archetype ids, including at least: exec_summary, agenda, chart_takeaways,
  ranked_bar, waterfall, stacked_bar, annotated_line, matrix_2x2, football_field, comparison_table,
  gantt, process_flow, issue_tree, market_map, kpi_row, quote, section_divider, comps_table,
  tombstones.
- C2 Every archetype builds from its own registered example blocks, renders, and validates with 0
  critical findings (one slide per archetype, one combined deck).
- C3 For every chart archetype: the chart is a native chart part (no picture), and the cached values in
  the chart XML equal the spec's series values (float tolerance 1e-9). Waterfall foots: start + deltas
  == end.
- C4 Variety of visual types: the archetype set covers ≥ 12 distinct `visual_type` values.

## D. Fit engine (S3.4)
- D1 `metrics.text_width` within 2 % of Pillow `getlength` for 10 Latin strings at 10/14/24 pt.
- D2 A body block 3× too long for its box returns `FitError` whose message matches
  `^\w+ block \d+ is \d+ words over; cut or split$`; the fitted size never goes below the floor.
- D3 A block that fits only after tightening reports steps `[reflow, tighten]` and no shrink.

## E. Validator (S3.7) — planted defects
- E1 Build one deck with python-pptx directly (not via the renderer) containing one planted defect per
  slide: overflow, overlap, contrast 2:1, 8 pt text, em dash, banned word ("leverage"), missing title
  rule, missing page number, eyebrow above title, gradient fill, outer shadow, off-palette srgb colour,
  5 type sizes on a slide, shape outside the slide. Each must be detected with the right rule **and the
  right shape id/name**. A clean house-framed slide yields 0 findings.
- E2 `scripts/validate_pptx.py` exit code 1 on the defect deck, 0 on a clean deck; `--json` parses.

## F. Arabic / RTL (S3.5)
- F1 For each Arabic deck: every paragraph with Arabic text has `rtl="1"` and right alignment
  (unless centred); titles are right-aligned and their box mirrors the LTR position (x' = 13.333 − x − w,
  ±0.02 in); tables have `rtl="1"`; bar/column charts have reversed category axis orientation.
- F2 No Arabic presentation-form code points (U+FB50–U+FDFF, U+FE70–U+FEFF) appear in any slide XML
  (text is stored logical Unicode; reshaping is for measurement only).
- F3 Theme has a `cs` font for major and minor.

## G. Theme, template cloner and model sync (S3.9)
- G1 Run fonts in all 20 decks are theme references (`+mj-*`/`+mn-*`) or theme font names; no `gradFill`,
  `outerShdw`, `sp3d`, `scene3d` anywhere.
- G2 Cloner: create a client `.potx` fixture in the gate (python-pptx; custom theme colours + fonts
  + a title placeholder at a non-house position); `house_clone` extracts a profile with those fonts and
  colours; a deck built with that profile/template uses the client's theme fonts/colours and validates
  with 0 critical.
- G3 Sync mutation test: build a deck whose chart, table cell and KPI value are bound to ModelManifest
  ids; mutate one bound value in the model; re-sync (sockets blocked, no LLM) → only the bound shapes'
  XML changes (diff every slide part before/after: all other parts byte-identical); the new value appears
  in the chart cache / cell / KPI text; mutating an unbound value changes nothing; a binding to a
  missing manifest id raises a clear error.

## H. Vision critic loop (S3.8)
- H1 With a fake VLM (injected; returns a SlideRepairPatch naming a real shape id), the loop applies the
  patch, re-validates, and stops at ≤ 3 loops; a fake that always complains stops at exactly 3.
- H2 The critic is not called when the validator reports a critical finding.
- H3 In replay mode with sockets blocked, a deck build completes and records `critic: not run live`.

## I. Creative visual layer (S3.11)
- I1 Image probe runs on every build and returns unavailable offline without opening a socket; the
  status is recorded in the build report.
- I2 Every non-data visual in the 20 decks was chosen from ≥ 3 candidates; the build report lists the
  candidate scores and the kept id.
- I3 0 `variety` / `templated` findings across the 20 decks; ≥ 6 distinct art directions used across
  the 20 decks; no two consecutive slides share archetype + visual type.
- I4 A planted rubber-stamp deck (10 slides, same archetype and layout) is flagged `templated`.
- I5 Style scores are appended to the style log (temp `ACRETIA_DATA`), one row per kept visual.
- I6 Two builds of the same brief with different seeds produce different visuals (PNG hashes differ)
  while every number/chart XML is identical (deterministic polish, generative art).

## J. Hygiene
- J1 AST scan: no `openai`, `anthropic`, `google.generativeai` imports under `om/deck/`; model calls go
  through `src/harness/adapter.py` (or `om/llm.py`'s adapter-backed router).
- J2 `scorecard.csv` has one S3 row per brief × model; rows that need a live model say
  `not run live`; no numeric score is present in a `not run live` row; offline deterministic metrics
  (validator criticals, majors, variety, build seconds) are filled.
- J3 Full unit suite is not re-run by the gate (the Boss runs it), but the gate imports every
  `om.deck` module without error.

## K. North-star metrics (D-032)
- K1 Reliability run: `evals/decks/reliability/` generates ≥ 100 varied specs (US GAAP, IFRS, MENA
  companies; pitchbook section, IC deck, earnings recap, market entry, carve-out; ≥ 3 Arabic) and builds
  them all offline. ≥ 97 % build with 0 critical validator findings; the success rate is printed.
- K2 Zero `unsourced_number` findings across the 20 corpus decks and the reliability run.
- K3 Determinism: building each of 5 sampled specs twice with different seeds gives identical
  `numbers_digest` and different kept-visual hashes.
- K4 Speed: p50 wall-clock for the 10-slide decks in the reliability run is < 300 s (offline; printed
  with p90), and every BuildReport carries per-step timings, tokens and cost_usd (0 offline) in its Job.
- K5 Every persona run writes an "edits needed" list per slide with shape ids to
  `evals/decks/edits/<deck_id>.json` (checked for presence and shape-id validity against the deck).
