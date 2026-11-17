# UX spec: the deal board

Owner: session F (Boss). Status: **proposed, awaiting sign-off**. Decisions are logged as `D-SF-xx`.

## 1. The problem, in the user's words

> "It allows them to track and have a dashboard up front and then we have a super small dashboard, like 'deal, deal, deal, deal. This is happening, this is happening, this is happening, etc.'"

Today `frontend/src/pages/Home.tsx` is a starter-task list: a few prompt cards and a recent-items table. It answers "what can I do?" and not "what is happening?". A user with six live deals has no single screen that tells them where each one stands and what needs them.

The user's own description of the shape is a **strip of deal cards**, each one small, each one saying what is happening. That is the design.

## 2. The screen

The deal board replaces the current Home page at `/`. It has three bands, top to bottom.

### 2.1 Band 1: the attention strip

A single row of **signal chips**, one per thing that needs the user today. Each chip is a filter: clicking it narrows the board below.

Signals, in priority order:

| Signal | Condition | Tone |
|---|---|---|
| `Documents failed to index` | any deal has `counts.failed > 0` | negative |
| `Checks failing` | a deal's latest model version has a failing check | negative |
| `Indexing` | any deal has documents in `indexing` or `queued` | info |
| `Runs in progress` | any deal has a job in `running` | info |
| `No model yet` | a deal has documents but no model deliverable | warning |
| `Stale` | a deal's `updated_at` is more than 7 days old and it is `active` | warning |

Each chip reads `3 deals` or `1 deal`, and the strip is empty when nothing needs attention, in which case it shows a single quiet line: `Nothing needs your attention.`

**Why a strip and not a notification list.** The user asked for "this is happening, this is happening". A chip that filters is both the alert and the way to act on it, in one control.

### 2.2 Band 2: the deal cards

A responsive grid of deal cards, three across at 1440px, two at 1100px, one below 760px. Each card is a fixed-height tile, roughly 180px, so the grid scans as a grid.

**Card anatomy**

- **Top line:** the deal name, and the status pill (`active`, `on hold`, `closed`).
- **Second line:** the target and the sector, in `text-2`, truncated with a title attribute.
- **The signal line:** the one thing that is happening, in the card's own words. This is the "this is happening" the user asked for. Examples: `Indexing 12 of 40 documents`, `Model v4 ready, 2 checks failing`, `No model yet`, `Last updated 9 days ago`. When nothing is happening, it reads `Up to date`.
- **The figures row:** up to three headline figures from the deal's latest model, when one exists. Which figures is a firm-level setting, defaulting to the model's own named outputs. Each figure is a label and a value in tabular numerals. When there is no model, the row is absent, not empty.
- **The footer:** the counts, as small text: `40 docs`, `3 deliverables`, `2 runs`. And a relative timestamp.

**Card states**

- **Loading:** a skeleton card of the same height, so the grid does not reflow.
- **Empty deal:** a card with no documents reads `No documents yet` and offers `Upload documents` as the card's action.
- **Failed:** a card with failed documents carries a negative left border and the failure count in the signal line.

**Card interaction**

- The whole card is a link to the deal. It is a real `<a>`, so middle-click and open-in-new-tab work.
- Hovering raises the card to `shadow-1` and shows a small action row: `Open`, `Run`, `Upload`.
- The card is keyboard focusable and `Enter` opens it.
- Right-clicking a card opens the same context menu as the deal row in the deals list.

### 2.3 Band 3: the recent activity rail

A single column below the cards, collapsed by default to three rows, with a `Show all` control. It reuses the existing `activity()` payload: jobs, uploads, deliverable versions, comments and deal events, newest first, each row naming the deal it belongs to.

This is the "what happened while I was away" answer, and it is deliberately below the fold because it is the least urgent band.

## 3. What the backend must add

The board needs one new endpoint, because the current `list_deals` returns counts but not the signal state or the headline figures.

**`GET /deals/board`** returns, per deal:

```
{
  "deal_id": str,
  "name": str,
  "target": str,
  "sector": str,
  "status": str,
  "updated_at": str,
  "counts": { "documents": int, "indexed": int, "failed": int, "deliverables": int, "jobs": int },
  "indexing": { "total": int, "indexed": int, "indexing": int, "queued": int, "failed": int, "progress": float },
  "latest_model": { "name": str, "version": int, "updated_at": str } | null,
  "checks": { "pass": int, "fail": int, "warn": int } | null,
  "headline": [ { "label": str, "value": float | null, "fmt": str, "ref": str } ],
  "signals": [ str ]
}
```

- `indexing` reuses the existing `overall()` function.
- `checks` reuses the existing model check payload for the latest model version.
- `headline` reads the model's named outputs. Which cells are headline is a firm-level setting; when it is unset, the endpoint returns the model's own output list, capped at three.
- `signals` is computed server-side so the strip and the cards cannot disagree.

The endpoint is one query per deal for the counts, plus one workbook read per deal that has a model. For a board of 20 deals that is acceptable; if it is not, the workbook read is cached by `(deal_id, version)`.

## 4. Copy

| Key | English |
|---|---|
| `board.title` | `Deals` |
| `board.attention` | `Needs attention` |
| `board.nothing` | `Nothing needs your attention.` |
| `board.signal.failed` | `{n} deals with failed documents` |
| `board.signal.checks` | `{n} deals with failing checks` |
| `board.signal.indexing` | `{n} deals indexing` |
| `board.signal.running` | `{n} runs in progress` |
| `board.signal.noModel` | `{n} deals with no model yet` |
| `board.signal.stale` | `{n} deals not touched in a week` |
| `board.card.indexing` | `Indexing {done} of {total} documents` |
| `board.card.modelReady` | `Model v{version} ready` |
| `board.card.checksFailing` | `{n} checks failing` |
| `board.card.noModel` | `No model yet` |
| `board.card.noDocs` | `No documents yet` |
| `board.card.upToDate` | `Up to date` |
| `board.card.stale` | `Last updated {days} days ago` |
| `board.card.docs` | `{n} docs` |
| `board.card.deliverables` | `{n} deliverables` |
| `board.card.runs` | `{n} runs` |
| `board.empty.title` | `No deals yet` |
| `board.empty.body` | `Create a deal to start. Upload the documents and Acretia builds the model, the deck and the grid.` |
| `board.empty.action` | `Create a deal` |
| `board.activity` | `Recent activity` |
| `board.showAll` | `Show all` |

Copy rules: sentence case, no exclamation marks, no em dash or en dash as punctuation, and a signal always names the count and the thing, never a bare `Alert`.

## 5. Acceptance

1. `/` renders the board, not the starter-task list.
2. The attention strip shows one chip per signal that has a non-zero count, and no chip for a zero count.
3. Clicking a chip filters the cards to the matching deals, and the chip shows as active.
4. Each card states the deal name, status, target, sector, the current signal line, the counts and a relative timestamp.
5. A card for a deal with a model shows up to three headline figures in tabular numerals.
6. A card for a deal with no model omits the figures row rather than showing zeros.
7. A card for a deal with failed documents carries a negative left border.
8. The whole card is a link, and middle-click opens a new tab.
9. The board renders correctly in Arabic RTL and in both themes.
10. At 1440px the board shows three cards across; at 1100px two; below 760px one.
11. Loading shows skeleton cards of the same height, so the grid does not reflow.
12. The activity rail is collapsed to three rows by default.
13. No live LLM call is made to render the board.

## 6. What this spec does not cover

- Portfolio-level analytics, such as total deal value or a pipeline funnel. The board is a status surface, not an analytics surface.
- Customisable card layouts or a user-chosen set of headline figures. The firm-level setting is the first step; per-user layout is a later decision.
- Real-time push. The board refreshes on focus and on a 60-second interval. The existing SSE stream is used for the indexing and run signals when the user is on the page.