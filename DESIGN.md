---
name: Acretia
description: Deal analysis with every number traceable to its source page.
colors:
  bg: "#F3F5F8"
  surface: "#FFFFFF"
  surface-2: "#ECF0F5"
  surface-hover: "#E4E9F0"
  border: "#D5DCE5"
  border-strong: "#B7C2D0"
  text: "#0E1A29"
  text-2: "#42536A"
  text-3: "#586A82"
  accent: "#0B6B63"
  accent-hover: "#085650"
  accent-subtle: "#E1F2F0"
  positive: "#14632F"
  positive-bg: "#E4F4EA"
  warning: "#8A3D07"
  warning-bg: "#FDF0DC"
  negative: "#B01E1E"
  negative-bg: "#FCE9E9"
  info: "#1F4FA8"
  info-bg: "#E6EEFB"
  chrome: "#0B1F33"
  chrome-text: "#C6D2E1"
  chrome-text-muted: "#93A5BC"
  chrome-active-bg: "#16314D"
  chrome-border: "#1C3652"
  chrome-accent: "#3CC9BA"
  dark-bg: "#08121C"
  dark-surface: "#0E1B2A"
  dark-surface-2: "#142536"
  dark-border: "#22364A"
  dark-text: "#E8EEF5"
  dark-text-2: "#AEBCCD"
  dark-accent: "#2DC5B5"
typography:
  body:
    fontFamily: "Inter, IBM Plex Sans Arabic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Inter, IBM Plex Sans Arabic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.04em"
  title:
    fontFamily: "Inter, IBM Plex Sans Arabic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.25
  display:
    fontFamily: "Inter, IBM Plex Sans Arabic, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.15
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "3px"
  md: "4px"
  lg: "6px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
  s8: "32px"
  s10: "40px"
  s12: "48px"
components:
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    height: "28px"
    padding: "0 10px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    height: "28px"
    padding: "0 10px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "#FFFFFF"
  badge:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-2}"
    rounded: "{rounded.sm}"
    height: "18px"
    padding: "0 6px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    height: "28px"
    padding: "0 8px"
---

## Overview

Acretia is a working instrument for deal professionals. The interface is dense, quiet and precise. It reads as a professional tool of its category, in the way a trading terminal or a well-built analytics product does: information first, decoration never, and a stable layout the user can build muscle memory on.

The visual world is a **cool, low-chroma instrument panel**. The ground is a pale blue-grey, surfaces are white, and a single deep teal carries action and selection. A near-black navy chrome bar anchors the top. Colour is used for meaning, not for atmosphere: teal for action and selection, green for pass and positive, amber for warning, red for failure, blue for links and inputs.

The product is bilingual. Arabic and RTL are first-class, and every layout uses logical CSS properties so the same component mirrors correctly.

## Colors

The palette is defined once in `frontend/src/ds/tokens.css` and mirrored in `frontend/src/ds/tokens.ts`. `scripts/check-tokens.mjs` fails the build if the two disagree. Never hard-code a colour in a component.

**Ground and surfaces.** `bg` is the page ground. `surface` is a card, panel or grid cell. `surface-2` is a recessed area, a table header or a badge. `surface-hover` is the hover state for a row or a control.

**Text.** `text` for primary content, `text-2` for secondary labels and table headers, `text-3` for metadata and disabled content. All three pass AA on `surface`.

**Accent.** `accent` is the single action colour: primary buttons, the selected cell border, the active tab underline, focus rings. `accent-subtle` is its tinted background for a selected row or an active chip. `accent-contrast` is the text colour on an accent fill.

**Semantic.** `positive`, `warning`, `negative` and `info` each have a solid and a `-bg` tint. They carry meaning only: a passing check, a stale input, a failed check, a link or an input cell. Never use them decoratively.

**Chrome.** The top bar uses `chrome` as its ground with `chrome-text` and `chrome-text-muted` for content, `chrome-active-bg` for the active item, and `chrome-accent` for the brand mark and the live indicator.

**Dark theme.** Every token has a dark counterpart, applied through `prefers-color-scheme` and overridden by `[data-theme='dark']`. The dark ground is a deep navy, not black, and the accent lightens to `#2DC5B5` to hold contrast.

## Typography

Two families. **Inter** for all interface text, with **IBM Plex Sans Arabic** as the Arabic companion and the first choice when the locale is Arabic. **JetBrains Mono** for anything the user might compare character by character: cell references, formulas, numbers in a grid, tokens, IDs.

The scale is 11 / 12 / 13 / 15 / 20 / 28. Body is 13px. 11px is reserved for uppercase section labels and badges. 28px is reserved for a single headline figure on a page.

Numbers are tabular. Any column of figures uses `font-variant-numeric: tabular-nums` so digits align. In Arabic locales, digits render in the locale's numeral system through the `arabicDigits` option, and the grid subtree stays `dir="ltr"` because a spreadsheet's A1 origin is always top-left.

## Layout

A 4px spacing grid, exposed as `--acr-s-1` through `--acr-s-12`. Use the token, never a raw pixel value.

The shell is a fixed 224px sidebar, a 44px top bar, and a scrolling content area. The sidebar collapses to icons below 1100px and becomes a drawer below 760px.

Rows are 28px high and controls are 28px high, so a table row and a toolbar line up. The large control height is 34px.

**Density is the point.** A deal professional compares many numbers at once. Prefer a 28px row with 12px of horizontal padding over a 44px row with 20px. Prefer a visible column header over a tooltip.

**Horizontal scrolling is a failure.** Any table or grid that the user must read across must fit the viewport at 1280px, or pin its identifying columns and scroll only the data columns. A grid that scrolls sideways to reach the number the user came for is a bug, not a trade-off.

## Elevation & Depth

Three shadow levels, and no more.

- `shadow-1`: a resting card or a sticky table header.
- `shadow-2`: a popover, a dropdown menu, a tooltip.
- `shadow-3`: a modal dialog, a drawer, a command palette.

Depth is otherwise carried by borders and background steps, not by shadow. A panel is a 1px `border` on a `surface` ground. A recessed area is `surface-2` with no border. Do not stack a shadow on a bordered panel.

## Shapes

Radii are small and consistent: 3px for badges and chips, 4px for buttons, inputs and cells, 6px for panels, cards and dialogs. Nothing is fully rounded except avatars, status dots and the toggle track.

Borders are 1px. A selected cell uses a 2px accent border drawn inside the cell so it does not shift the grid. Focus is a 2px accent ring with a 1px offset, and it is never removed.

## Components

The design system lives in `frontend/src/ds/`. Import from `../ds`, never from a file inside it.

- **Button**: 28px, 4px radius, 1px `border-strong`. Variants `primary` (accent fill), `ghost` (no border), `danger`. Sizes `sm` (24px), `md` (28px), `lg` (34px). An icon-only button is square and carries an `aria-label`.
- **Badge**: 18px, 3px radius, tinted background, no border. Tones `neutral`, `accent`, `positive`, `warning`, `negative`, `info`. Optional 6px leading dot.
- **Panel**: `surface` ground, 1px border, 6px radius, with an optional head row carrying a title and actions.
- **Table**: sticky header on `surface-2`, 28px rows, 1px row separators, tabular numerals, right-aligned numeric columns.
- **Tabs**: underline style, 2px accent underline on the active tab, keyboard arrow navigation.
- **Input**: 28px, 4px radius, 1px border, accent focus ring. An input cell in a model grid is tinted `info-bg` with `info` text, because an input is a different kind of thing from a calculation.
- **SplitPane**: a draggable divider between two panes, with a keyboard-operable handle and a persisted share.
- **Overlay family**: Dialog, Drawer, Menu, Popover, Tooltip, CommandPalette. All trap focus, restore focus on close, and close on Escape.

## Do's and Don'ts

**Do**

- Use a token for every colour, space, radius and font size.
- Use logical properties (`inline-size`, `padding-inline`, `border-block-end`) so RTL mirrors for free.
- Keep the grid subtree `dir="ltr"` and mirror only the surrounding chrome.
- Use tabular numerals in every column of figures.
- Give every icon-only control an `aria-label` and every interactive element a visible focus state.
- Show a loading skeleton rather than a spinner in a content area, and keep the previous content visible while refreshing.
- State the truth about a number: a proxy, an estimate, a missing source and a failed check are all visible states.

**Don't**

- Hard-code a hex value, a pixel gap or a font size in a component.
- Use a semantic colour decoratively.
- Introduce a second accent colour.
- Let a table scroll horizontally to reach the column the user came for.
- Hide a number's provenance behind a hover-only affordance, because hover does not exist on touch and is not discoverable.
- Add a shadow to a bordered panel.
- Use an em dash or an en dash as punctuation in interface copy.