# UX spec: the cell explain drawer

Owner: session F (Boss). Status: **proposed, awaiting sign-off**. Decisions are logged as `D-SF-xx`.

## 1. The problem, in the user's words

> "having a button they can press on whichever cell they want and having them figure out: 1. where this number came from 2. which actual context it came from. For example if I have a number, I want to know where it's calculated from. It tells me it's calculated from this here and it shows you a preview of that specific sheet and all that, and what that number actually is from, which year, etc."

Today the model viewer has the data but not the interaction:

- `om.wbgraph.explain` already returns the formula, a labelled precedent tree to depth 2, the leaf inputs, and each leaf's source comment or link.
- `om.wbgraph.label_of` already composes `Revenue (FY2026E)` from the row label and the period header.
- `om/api/viewers.py::model_explain` already adds the dependents, the cell note, and a `citation_token` when the cell is tied to a document.
- `CellInspector` in `frontend/src/viewers/model/panels.tsx` renders some of this in a passive right rail.

What is missing is a **button on the cell**, a **rendered preview of the source sheet**, and a **period stated as a first-class fact**. The user has to know to click a cell and then read a rail that competes with the grid for horizontal space.

## 2. The interaction

### 2.1 The affordance

Every non-empty cell in the model grid carries a small **explain button** in its top-right corner.

- It appears on hover, on keyboard focus, and on the selected cell. It is always present in the DOM so it is reachable by keyboard and by screen reader.
- It is 16px square, drawn inside the cell so it never shifts the grid, with a 12px glyph.
- It is `aria-label="Explain <ref>"`, and it is a real `<button>`, not a div.
- On the selected cell it is always visible, so the user does not have to hover to discover it.
- It is suppressed on empty cells and on the row and column headers.

**Why a button and not a right-click or a keyboard-only shortcut.** The user asked for a button. A right-click menu is invisible, and a keyboard shortcut is undiscoverable. The button is the discoverable path; the keyboard shortcut and the context menu are the fast paths for the user who has learned the tool.

### 2.2 The three ways in

| Path | Trigger | For |
|---|---|---|
| Button | Click the cell's explain button | The discoverable path, and the mouse path |
| Keyboard | `Ctrl+Enter` (or `Cmd+Enter`) on the selected cell | The fast path for a heavy user |
| Context menu | Right-click the cell, choose "Explain this cell" | The path a spreadsheet user already has in their fingers |

All three open the same drawer.

### 2.3 The drawer

A **full-width drawer anchored to the bottom of the model view**, sliding up over the grid.

- Default height: 46% of the viewport, clamped to a 320px minimum and a 560px maximum.
- The top edge is a drag handle. Dragging resizes between 25% and 85%. The height persists per user in local storage.
- The grid stays visible above it and keeps its scroll position and selection. The user never loses their place.
- `Escape` closes it and returns focus to the cell that opened it.
- It is a `role="dialog"` with `aria-modal="false"`, because the grid behind it stays interactive. Focus moves into the drawer on open and is trapped within it while it is open, with a visible close button as the first stop.
- It is not a modal. The user can still click a cell in the grid above, which re-targets the drawer to that cell without closing it.

**Why bottom and full width.** The user's complaint is horizontal scrolling. A right rail takes width from the grid, which is exactly the axis that is already tight. A bottom drawer takes height, which the grid has in surplus, and it gives the source-sheet preview the full width it needs to be readable.

### 2.4 What the drawer shows

The drawer has a fixed header and four regions. The header is always visible; the regions scroll.

**Header (always visible)**

- The cell reference, in mono, for example `DCF!C14`.
- The human label from `label_of`, for example `Terminal value (FY2031E)`. This is the "which actual context" answer, and it is the single most important string in the drawer.
- The **period chip**: the fiscal year or period the cell belongs to, derived from the period header. Rendered as a distinct chip, not as part of the label, so it can be scanned.
- The **kind chip**: `Input`, `Calculation`, `Link`, `Label`, or `Error`, from the existing `_classify`. An input is tinted `info`, a calculation is neutral, a link is `positive`, an error is `negative`.
- The value, formatted with the cell's own format.
- A close button.

**Region 1: Where this number comes from**

The formula, in mono, with each referenced cell rendered as a clickable token. Clicking a token re-targets the drawer to that cell and selects it in the grid. This is the "it tells me it's calculated from this here" answer.

Below the formula, the **precedent tree** from `explain.precedents`, rendered as an indented list to depth 2. Each row shows the cell reference, its label, its value, and its own formula if it has one. A range precedent shows as one row with its cell count and its first few values, and expands on click.

**Region 2: The source sheet preview**

This is the part that does not exist today and is the heart of the request.

A **rendered mini-grid of the source sheet**, showing the neighbourhood of the precedent cell: the 6 rows above and 6 below, and the 4 columns either side, clamped to the sheet bounds. The precedent cell is highlighted with an accent border and a tinted background. Row and column headers are shown so the user can orient.

- The preview is rendered from the same `cells` payload the main grid already receives, so it needs no new endpoint and no new fetch.
- Clicking a cell in the preview re-targets the drawer to that cell.
- A "Open in grid" button jumps the main grid to that sheet and cell and closes the drawer.
- When the precedent is on another sheet, the preview names the sheet in its header, for example `Assumptions`, and the sheet name is a link that switches the main grid.

**Region 3: The source document**

When the cell, or any of its leaf inputs, carries a `citation_token`, this region shows the citation: the document name, the page, the quote, the as-of date, and the XBRL concept when there is one.

- A **page thumbnail** is rendered from the stored bounding box, using the same PDF page renderer the PDF viewer already uses. The cited region is highlighted.
- Clicking the thumbnail opens the PDF viewer at that page with the citation highlighted, in a new tab, so the user does not lose the model.
- When the citation is XBRL-backed and has no document, the region shows the concept, the accession and the as-of date, and says plainly that there is no page to show.
- When there is no citation at all, the region says so: `No source document is linked to this cell.` It does not hide, because a missing source is information.

**Region 4: What this number feeds**

The dependents from `explain.dependents`, with the total count. Each row is clickable and re-targets the drawer. This answers the reverse question, "if I change this, what moves?", which is the question a user asks immediately after the first one.

### 2.5 The leaf inputs, stated as facts

The `explain.inputs` list is the honest answer to "where did this actually come from". Each leaf input is shown with:

- its cell reference and label,
- its value,
- its **source comment** when the workbook carries one,
- its **link** when the workbook carries one, rendered as a clickable external link,
- its **period**, from the same period-header derivation as the header chip.

A leaf input with no source comment and no link is shown as `No source recorded`, in `text-3`. It is not hidden and it is not guessed at.

## 3. What the backend must add

The current `model_explain` response is close but not sufficient. Three additions, all cheap:

1. **`period` on the cell and on every node.** `label_of` already computes the period header internally. Expose it as its own field so the frontend does not have to parse it out of the label string. Add `period` to `info()` in `om/wbgraph.py::explain` and to the dependents in `model_explain`.
2. **`sheet` on every node.** The cell key already contains it, but exposing it as a field removes string parsing from the frontend and makes the preview's sheet header trivial.
3. **`citation_token` on leaf inputs, not only on the root cell.** Today `model_explain` attaches a token only to the root cell and only when it has no formula. A leaf input is exactly the cell that has a source document, so the token belongs there. Extend `_citation_tokens` lookup to the `inputs` list.

No new endpoint is required. The source-sheet preview is rendered client-side from the `cells` payload the model view already holds.

## 4. The horizontal scrolling fix

The user named horizontal scrolling as a core complaint. Three changes, in order of impact:

1. **Pin the label columns.** Column A and B, which carry the row labels, are frozen on horizontal scroll. This is the single biggest win, because the user can always see what a row is.
2. **Fit-to-width by default.** On open, the grid sizes columns to fit the viewport when the sheet has 12 or fewer data columns. A "Fit" control in the toolbar toggles between fit and natural width.
3. **The drawer replaces the rail.** Moving the inspector to the bottom returns the rail's width to the grid, which is roughly 320px of horizontal space recovered at 1440px.

## 5. Copy

All strings go through `useI18n` and need both English and Arabic. Proposed English copy:

| Key | English |
|---|---|
| `explain.button` | `Explain {ref}` |
| `explain.title` | `Where this number comes from` |
| `explain.period` | `Period` |
| `explain.kind.input` | `Input` |
| `explain.kind.calc` | `Calculation` |
| `explain.kind.link` | `Link` |
| `explain.kind.label` | `Label` |
| `explain.kind.error` | `Error` |
| `explain.formula` | `Formula` |
| `explain.precedents` | `Calculated from` |
| `explain.preview` | `Source sheet` |
| `explain.openInGrid` | `Open in grid` |
| `explain.source` | `Source document` |
| `explain.noSource` | `No source document is linked to this cell.` |
| `explain.noSourceRecorded` | `No source recorded` |
| `explain.xbrlOnly` | `This figure comes from the filing's XBRL data. There is no page to show.` |
| `explain.dependents` | `Feeds into` |
| `explain.inputs` | `Inputs behind this number` |
| `explain.empty` | `This cell is empty.` |
| `explain.error` | `Could not load this cell's detail.` |
| `explain.retry` | `Try again` |

Copy rules: sentence case, no exclamation marks, no em dash or en dash as punctuation, and never a bare "Error" without saying what failed and what to do.

## 6. Acceptance

The drawer is done when all of these hold:

1. Every non-empty cell in the model grid has a keyboard-reachable explain button.
2. Clicking it opens the drawer without moving the grid's scroll position or losing the selection.
3. The header states the cell reference, the human label and the period.
4. The formula renders with clickable cell tokens that re-target the drawer.
5. The precedent tree renders to depth 2 with labels and values.
6. The source-sheet preview renders the neighbourhood with the precedent highlighted, and clicking a preview cell re-targets the drawer.
7. A cell with a citation shows the document, page, quote and a highlighted page thumbnail.
8. A cell with no citation says so explicitly.
9. A leaf input with no source comment and no link says `No source recorded`.
10. `Escape` closes the drawer and returns focus to the originating cell.
11. The drawer is fully operable by keyboard alone.
12. The drawer renders correctly in Arabic RTL and in both themes.
13. At 1280px, the model grid does not scroll horizontally to reach a data column.
14. No new endpoint is added, and no live LLM call is made.

## 7. What this spec does not cover

- The same drawer in the grid viewer and the deck viewer. The grid viewer already has a `Dock` with a cell tab; extending it is a follow-up packet, not this one.
- Editing from inside the drawer. The drawer is read-only in this packet. Editing stays in the grid.
- A full dependency graph visualisation. The tree and the dependents list are the answer; a node-link diagram is a later, separate decision.