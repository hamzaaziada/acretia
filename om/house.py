"""House style: one source of truth for the grid, type scale, spacing, palette and visual grammar.

Used by the storyboard writer, the image prompts, the slides engine (layout.GUIDE), the components in
layout.py, the automatic spacing check and the graders, so they all hold slides to the same rules.
A brand can override PALETTE and FONTS; the grid and spacing rules don't change.
"""
from __future__ import annotations

CANVAS = (13.333, 7.5)

# grid (inches)
GRID = {
    "margin_x": 0.7,            # left and right margin
    "safe": 0.5,                # nothing closer than this to any edge (footer excepted)
    "title_y": 0.5, "title_h": 0.95,   # no eyebrow above it: the title is the first thing on the page
    "title_rule_y": 1.55,       # thin rule under the title, margin to margin
    "subtitle_y": 1.7,          # measure and unit under the rule
    "content_top": 2.15, "content_bottom": 6.4,
    "note_y": 6.45,             # notes and source
    "footer_rule_y": 6.95,      # thin rule above the footer
    "footer_y": 7.02,           # deck name left, page number right
}
RULE_PT = 0.75
GAPS = (0.3, 0.5)               # the only gaps allowed between blocks; one per deck
CARD_PADDING = 0.2              # text inset inside cards
TYPE = {"cover": 54, "key_message": 40, "divider": 48, "title": 24, "stat": 44, "block_heading": 16, "body": 14,
        "chart_label": 12, "label": 12, "note": 10}
MIN_BODY_PT = 14
MIN_ANY_PT = 10

PALETTE = {
    "text": "#0B1F33",          # text and dark pages
    "background": "#FFFFFF",
    "secondary": "#1F3C88",     # second series, step headers
    "panel": "#F2F3F5",         # cards and panels
    "accent": "#2251FF",        # the single emphasis colour; nothing else uses it
    "series2": "#00A9F4",
    "series3": "#1F3C88",
    "light": "#A9D8F2",         # light series, icon badges on white
    "key_message": "#C9D4FF",
    "muted": "#6B7280",         # muted text, de-emphasised bars
    "mute_bar": "#C7CCD4",
    "positive": "#0F8A5F", "negative": "#C23B22",
}
FONTS = {"heading": "Cambria", "body": "Arial"}

STYLE_GUIDE = f"""# House style (every slide)

Frame (every content slide, identical): the title at y {GRID['title_y']} in, top-left, two lines at most — NO eyebrow, kicker,
exhibit label or section tag above or beside it, ever; a thin {RULE_PT} pt rule in the text colour under the title at
y {GRID['title_rule_y']}, margin to margin; the measure-and-unit subtitle at y {GRID['subtitle_y']}; content between
y {GRID['content_top']} and {GRID['content_bottom']}; note and source at y {GRID['note_y']}; a thin rule above the footer at
y {GRID['footer_rule_y']}; footer at y {GRID['footer_y']}: deck name left, page number right, {MIN_ANY_PT} pt.
Grid (13.333 x 7.5 in): margins {GRID['margin_x']} in left and right; nothing within {GRID['safe']} in of any edge except the footer.

Spacing: gaps between blocks are all {GAPS[0]} in or all {GAPS[1]} in (one choice per deck). Blocks in a row share a top
edge and a baseline; blocks in a column share a left edge. Text sits {CARD_PADDING}-0.25 in inside its card. Equal blocks
are equal size. Whitespace is deliberate: a half-empty slide means the visual is too small, so enlarge it.

Type: content titles {TYPE['title']} pt bold, a full-sentence takeaway of 15 words or fewer, sentence case, no full
stop. Block headings {TYPE['block_heading']} pt bold. Body {MIN_BODY_PT} pt minimum. Chart labels {TYPE['chart_label']} pt.
Notes, sources and footer {MIN_ANY_PT} pt; nothing smaller. No all caps.
Emphasis: bold the important parts — in every bullet, card and callout, bold the key figure ($, %, x) and the lead-in label
("Cover:", "Buffer:"), and keep the explanation regular. Never bold a whole sentence or paragraph; if everything is bold
nothing is. The reader's eye should land on the numbers that carry the argument.
Headings and stat numbers in {FONTS['heading']}; everything else in {FONTS['body']}.

Colour: text {PALETTE['text']}; panels {PALETTE['panel']}; one emphasis colour {PALETTE['accent']} used only for the bar,
number or series that carries the message; context in muted tones ({PALETTE['mute_bar']} bars, {PALETTE['muted']} text);
secondary {PALETTE['secondary']}, {PALETTE['series2']}. If everything is accented nothing is.

Visual grammar (pick the visual from the message):
- biggest / smallest: bar or column chart, key bars in the accent, the rest muted, values on the bars, no gridlines
- change over time: line chart, labelled directly, a change badge where the change happens
- parts of a whole: stacked bar or one segmented bar (pies only with four slices or fewer)
- several items on several measures: table with one highlighted column, or a dot plot
- before and after: dot plot with an arrow, or paired bars
- steps in order: numbered chevrons, one icon per step, the output or gate under each step
- a framework of 3-8 parts: a grid of icon cards
- how parts connect: a diagram with icons and callout cards joined by thin leader lines
- one or two headline numbers: stat callouts (large number in the accent, bold label, one line of context)
- what to do about it: a takeaway or decision box
- a plan over time: a Gantt of workstreams with milestone diamonds
- cash or value walks: a waterfall that foots, totals drawn from zero

Every data slide carries: a takeaway title; a subtitle with the measure in bold and the unit ("Free cash flow, FY2022-26,
$ billion"); a visible so-what (stat callout, change badge or takeaway box); a note and source line.

Devices: direct labels instead of legends; change badges; stat callouts (two or three per
slide at most); small multiples on a shared scale; icons that stand for things — one family, one size, in filled circles
beside text; callout cards with leader lines; a numbered heading to open a section; a dark page for dense evidence at most
once per section.

Never: an eyebrow or kicker label above the title; a slide of bullets with no visual; decoration beyond the title and
footer rules (edge stripes, clip art, 3D, shadows, gradients); stock-photo clichés; em dashes; text in a drawing; a legend when direct labels fit.

Five-second test: a reader who looks for five seconds can say the message, the number that stands out, and what to do."""
