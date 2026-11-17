# UI/UX lead review 1 (D-033 grader #2)

Reviewer: UI/UX lead (specialist reviewer, not the author). Date: 2026-11-17. Build: branch `claude/inspiring-turing-08rllk`, `frontend/dist` as built, `ACRETIA_LLM_MODE=replay`, `--demo` seed.
Method: real Chromium (Playwright), 1440x900 @1x, light, dark and Arabic (RTL), plus one 390 px mobile spot-check. Roles: owner, viewer. Every journey below was driven by script against the running app; nothing is judged from code, except that I name the likely root cause where a screen showed a defect.
Screenshots: `docs/samples/product/review-1/` (39 PNGs, `NN-screen-theme.png`; 80-84 dark, 85-90 Arabic).
Labels: **[OBS]** observed in the running app. **[NOT OBS]** not exercised.

## 1. Verdict

**Overall: 6.4 / 10. BLOCK** (parity bar is 8.5).

The shell, design system, run view, model workbench, deck annotator and dark mode are close to Hebbia/Rogo parity and in places better (precedents/dependents inspector, "byte-identical" revision message, folder-grouped matrix wizard). But **the product's central promise, "click any number and land on the highlighted source" (P-J6, parity 15-17), does not work in any of the three places a banker will try it**, and the Documents tab has no way to open a document. Several first-contact details (raw i18n key in the documents table, an agent-search example that returns nothing, a matrix that looks lost after a reload) would be caught by a buyer in the first five minutes. These are not polish items; they are broken trust paths.

| Screen | Score | |
|---|---|---|
| Login | 8.5 | at parity |
| Agent home | 8.0 | near parity |
| Run view (plan, approvals, sources) | 8.0 | near parity |
| Model workbench | 8.5 | at parity, minor density issue |
| Deck viewer / annotator / compare | 7.5 | slide canvas too small, source line not linked |
| Deals list and deal workspace | 7.0 | breadcrumb and count defects |
| Documents tab | 4.0 | **blocker** (no open, raw i18n key) |
| PDF viewer + citation inspector | 4.0 | **blocker** (no highlight, 404 on cite) |
| Matrix / grid | 6.0 | **blocker** (matrix "disappears", cell open is a hidden gesture, citations dead) |
| Agents library | 6.5 | **blocker** (example search returns nothing) |
| Library | 7.5 | ok |
| Notifications | 6.0 | duplicates, no deep links |
| Settings (Users, Definitions, Templates, Connectors, Mailbox, Audit, Preferences) | 6.5 | no Memory, audit log shows ids |
| Command palette and keyboard | 7.0 | hybrid palette, j/k does nothing visible |
| Dark mode | 8.0 | complete, no defects seen |
| Arabic / RTL | 7.0 | layout mirrors well; bidi punctuation and clipping defects |
| Viewer (read-only) experience | 6.5 | deck/model correct; Ask and Users misleading |
| Mobile (390 px, spot-check only) | 7.0 | [NOT OBS] beyond Home and Run |

## 2. Per-screen findings

### 2.1 Login (`/login`) 8.5
At or above parity: split layout, three value claims in the buyer's language, EN/عربي toggle top-right, inert disabled "Sign in" until valid. [OBS] `01-login-light.png`.
Minor: the form column is vertically centred with a large empty top third; no "show password" or SSO entry (an institutional buyer will ask for SSO on screen one). Not blocking.

### 2.2 Agent home (`/`) 8.0
At or above parity: "What should we work on?" with an Ask box, a source toggle row, a deal selector, `/` skills hint, six starter tasks (one per parity starter) and a Recent runs/Recent deliverables region. [OBS] `02-home-light.png`, `82-home-dark.png`.
Issues:
- **No blocker.** Fresh state: Recent runs shows a large dashed empty box (~200 px) for a state every new user sees; and "Recent deliverables" lists "Diligence checklist.txt / other" as the first impression. Replace the seeded `.txt` with a real sample deliverable, and shrink the empty state to ~96 px with the CTA inline.
- Source toggles (`source-toggle-*`) show on/off only by a faint border change. Use a filled state plus a check so the state reads in 200 ms and in greyscale.
- The deal selector defaults to "No deal" while two deals exist and "Deal documents" is a lit source. A "Deal documents" source with "No deal" selected is contradictory; disable it until a deal is chosen.
- Starter task cards use the prompt text of "Apple" for everything. Fine for demo, but each card should show an expected time ("about 3 min") to set the P-J1 expectation (parity 34).

### 2.3 Run view (`/runs/:id`) 8.0
At or above parity: step list with live status, cost/tokens/elapsed card, time-saved card honestly labelled "Estimate, not yet human-validated", source review approval inline in the plan, second approval for the ghost deck with editable titles, reorder and remove, Cancel run, deliverable card with Open. [OBS] `04-run-approval-light.png`, `05-run-done-light.png`, `10-ghost-deck-light.png`, `84-run-dark.png`.
Blocking issues:
- **B1. Source chip click is a dead end.** `/runs/:id` > `[data-testid=source-chip]` (any of the 36 SEC-filing chips) > click navigates to `/deals/:deal/docs/null?cite=...` and shows "Document not found" (`22` captured, then removed; reproducible). A filing citation with no stored document must open a **source card** (concept, value, period, as-of, link to EDGAR), not a 404 route. Fix: route citations by `kind`; `filings` and data-provider citations render a card (parity 21).
Other issues:
- Task label under the title says "DCF valuation" for a request "3-statement + DCF for Apple at 9% WACC" and "Company profile" for a deck. This is the agent name, not what the user asked. Label it "Agent: DCF valuation" or hide it when it repeats the title.
- Elapsed timer runs (00:03, 00:04, 00:05) while the run is "Awaiting approval". Pause it and show "Waiting for you".
- Plan header "Estimate $0.00 · 00:17": a $0.00 estimate reads as a bug. Show "Estimate not available in replay" or hide.
- Source chips: eight chips collapse to repeated "Apple Inc. 10-K FY2026 (SEC EDGAR)" labels three times. Chip labels must be unique ("Revenue FY2026 · 10-K p.41"). The hover popover wraps mid-token ("us-\ngaap:RevenueFromContractWithCustomerExcludi") and overlaps the next chips (`06-citation-hover-light.png`). Break on `:` or truncate with a copy button.
- Notification bell count goes 1 > 2 > ... > 7 within one session because each approval and finish is a separate notification (see 2.9).

### 2.4 Model workbench (`/deals/:id/models/:name`) 8.5
At or above parity and the strongest screen: sheet tabs, formula bar, KPI strip, "All checks pass" badge, audit overlay, precedents and dependents with values, assumptions panel with Ask / Checks / Audit tabs; viewer correctly gets disabled inputs and Save. Live recompute: editing "WACC step" showed "Recalculated in 244 ms, 55 cells updated". [OBS] `07-model-light.png`, `61-model-dcf-light.png`, `83-model-dark.png`.
Issues:
- **Density**: the right panel takes ~360 px at 1440, leaving 4.5 visible year columns on IS and fewer on DCF (`61`). Make the panel collapsible (`\`), default narrower (300 px), and remember it.
- Breadcrumb reads "Deal / AAPL_dcf_model.xlsx": it says the literal word "Deal", not "Project Atlas — Apple Inc.". Same on the PDF page. Use the deal name.
- Filtering assumptions by "WACC" shows only "WACC step" (a sensitivity step). The requested 9% WACC is a calculated cell (CAPM) with no direct override control. A banker who says "use 9% WACC" expects to see and edit "WACC: 9.0%". Add an "Override WACC" input in the Assumptions switches.
- "Save as new version" is greyed with "No unsaved changes" both on the same row; fine, but the greyed teal button reads as disabled-error. Hide it until dirty.
- The `[ ]` sheets and `E` edit hints at the bottom right are 10 px; discoverability only. Raise to 11-12 px.

### 2.5 Deck viewer (`/deals/:id/decks/:name`) 7.5
At or above parity: thumbnail rail, validator badge, per-slide source line, `c` comment mode with pin, apply comments to a new version ("Version 2 created: slides 2 changed. Every other slide is byte-identical."), Compare modal with before/after thumbnails, strikethrough title diff and Roll back, versions dropdown. Pinning "title: Apple at a glance" and applying it worked in ~4.0 s, and compare showed exactly one changed slide. Viewer role gets a read-only deck. [OBS] `12`, `14`, `17`, `66`, `81-deck`.
Blocking/major issues:
- **B2. The slide is too small.** The canvas is 574 px wide in a 600 px pane vertically floated in a 780 px-tall panel with ~220 px of dead grey above and below; slide body text is ~6 px and unreadable (`12-deck-light.png`). A reviewer cannot annotate what they cannot read. Fit the slide to the pane width (min 800 px at 1440), top-align, and add zoom (`+`/`-`, fit).
- **B3. Source line "not linked to a document"** (slide 2 inspector): the P-J6 requirement for a deck source line is a click-through to the highlighted span. Link it or hide the claim.
- Version dropdown text is truncated and leaks an internal job id: "v1 · Agent run job_79dbe8f78..." and "v2 · Revision round: 1 commer". Use "v1 · Generated · 09:19" and "v2 · 1 comment applied · 09:20".
- After clicking, the comment pin marker is not drawn on the slide until submitted; the pin popover then covers the slide area being discussed (`14`). Anchor the popover beside the pin; show a numbered pin immediately.
- Cover slide is mostly blank (title plus a 7 px subtitle); the first thing a banker sees should not look unfinished. (Deck design quality belongs to the MBB-designer grader; flagged for it.)
- Missing breadcrumb on this screen.

### 2.6 Deals and deal workspace (`/deals`, `/deals/:id`) 7.0
At parity: deals table, tabs with counts, Overview with runs table, standing instructions, firm accounting definitions, Activity tab with versions and who did what. [OBS] `19-deal-overview-light.png`.
Issues:
- **Grid tab count and empty state are wrong after use.** The tab shows "Grid 0" and "No diligence grid yet / Open the grid" even after a matrix with 3 columns exists.
- The Overview runs table includes a stale "awaiting approval" run created minutes ago, with no Resume affordance on the row.
- Activity entries show "Agent run job_2e43..." raw ids. Use the agent and request names.
- Overview stat strip (Documents 6 / Library 3 / Runs 3 / Updated) is generic; for a deal workspace the useful KPIs are coverage, open risks, last model/deck version. Low priority.
- The Apple deal ships the ElSewedy-style documents (annual report, facility agreement, QoE) rebranded as Apple, so a buyer sees a mismatch. Data issue, but it will appear in every demo.

### 2.7 Documents tab 4.0
**B4. Documents cannot be opened from the list, and a raw i18n key is shown.** `/deals/:id?tab=documents` > STATUS column renders `docs.status.indexed` for all six rows (`data-status="indexed"`), and the row has no Open action: the UI offers the open link only for `status==='ready'`, while the API returns `indexed`. Clicking, double-clicking or Enter on a row does nothing (tested). This also means the "no missing keys in `ar`" gate is not covering API status values. Fix: map `indexed` > "Ready", render Open for every readable status, make the whole row a link (`doc-open`), and add a status-enum i18n test.
Other: PAGES/LANGUAGE/SIZE columns are fine; no per-file progress surface was exercised [NOT OBS: no upload run] (parity 13).

### 2.8 PDF viewer and citation inspector (`/deals/:id/docs/:docId`) 4.0
The viewer itself is good (page box, zoom presets, search in document, download, citations inspector with page and as-of). [OBS] direct URL `21` (removed; reproducible).
**B5. Citation click-through does not highlight.** From a matrix cell: `grid-cell` > double-click > `source-chip` "Annual Report FY2023 (excerpt).pdf p.1" opens `/docs/doc_...?page=1&cite=gc_578b...` in ~2.5 s, but the inspector reads "No citation selected", "Citations in this document: 0", and `bbox-highlight` count is 0 after 7 s. `GET /api/v1/citations/gc_578b...` returns 404 (grid citation tokens are not resolvable by the citations endpoint). This fails parity 16 and 17 and the flagship P-J6. Fix: resolve `gc_` tokens, or write grid citations into the same table; scroll to and flash the span; show quote, page, as-of, source link. Acceptance: Playwright asserts `bbox-highlight` count >= 1 and `inspector-quote` equals the cell quote.
Other: breadcrumb "Deal / file" (literal "Deal"); inspector has a lot of empty space but nothing like "download all sources".

### 2.9 Matrix / grid (`/deals/:id/grid`) 6.0
At or above parity: 2-step wizard grouped by data-room folder (parity 2, 9), question splitting into one column per question with editable name, prompt and type, cells stream (first cell at ~0.4 s in replay [replay timing only]), confidence and Re-run and per-table CSV in the cell panel (parity 14), Excel export with logo and cell-note options (parity 10), variables bar, Workflow view, Column Manager with run selected/all and reorder. [OBS] `24`, `28`, `31`, `34`, `81-grid-dark`, `86-grid-ar`.
Blocking issues:
- **B6. The matrix looks lost after any reload.** Visiting `/grid` silently creates an empty "Matrix"; the page then selects the first grid in the list. After creating "Diligence matrix" and reloading, the page shows "Matrix 6 rows x 0 cols / Add your first column" and the user's work is only reachable through a small "Switch Matrix" select. (Select options: `Matrix`, `Diligence matrix`.) Do not auto-create; select the most recently modified grid; persist `?grid=` on creation; fix the Deal tab count.
- **B7. Opening a cell is an undiscoverable gesture.** Single click only selects; the detail panel opens on double-click. The tiny link icon with a count (10 px, `.vw-cell__src`, no click handler) looks like the citation affordance but does nothing. Make a single click open the panel (or Enter), and make the marker open the source (parity 15-16: hover preview <0.5 s). Currently no hover preview exists on grid citations.
- **B8. Answer quality shown in cells is extractive fragments, not answers**, e.g. "Change Control Clause" for the Annual Report: "Agreement for covenants and change-of-control provisions." (a cross-reference sentence, not a clause); "Top Customers" for the customer contract: "Apple Inc. | Customer contract | extract" (a page header). A buyer reads this as wrong. Graded by the diligence-lead grader, but UI mitigation is required now: show confidence per cell on the grid (a coloured edge), and show "Low confidence" for fragments.
Other issues:
- Page title is the generic "Matrix" with a tiny "Matrix" subtitle chip repeated; no breadcrumb or deal name; the deal context is lost on the most data-dense page. Add `Deals / Project Atlas / Matrix`.
- Grid does not fill its container: columns are fixed ~264 px and ~75 px of blank sits at the right edge at 1440 (`28`). Let columns flex.
- Three competing primary actions in the toolbar and empty state: "+ Column" (primary), "New Matrix" (secondary), and a green "New Matrix" in the empty state, whose label does not match its heading ("Add your first column"). The empty state CTA should be "Add column".
- Truncated cell text ends with an ellipsis colliding with the citation marker ("... net sales..🔗1"). Reserve space for the marker.
- Workflow view with no dependencies is a column of three boxes with a hint; acceptable. Conditional formatting (parity 7) and transfer filtered documents (parity 8) have no visible controls.
- Column Manager: each row repeats the name ("Select Change Control Clause" checkbox label beside the name). Expanded state for rename/prompt/model swap not verified [NOT OBS].
- Arabic: column order is mirrored correctly but text direction in cells is wrong (see 2.14).

### 2.10 Agents (`/agents`) 6.5
At parity on structure: search, tag chips, cards with tags, Built-in label, enable toggle (admin), pin icon, Run, New agent dialog with a prompt chain and share-with-firm. Run opens a dialog with deal and request. [OBS] `39-agents-light.png`, `72` (removed).
- **B9. The placeholder example returns nothing.** Search "value a company" (the placeholder's own suggestion) shows "No agent matches". "value" returns 1; "valuation" 6; "dcf" 1. Search is an AND of every word, including stop-words. Use fuzzy and token-OR ranking, ignore stop-words, and match on description (parity 32).
- Card footers repeat "Enabled for the firm" with a checkbox on every card; to a non-admin this is noise. Show a toggle only for admins and a small badge otherwise.
- Pin icon (top right of each card) is 12 px and has no tooltip.
- Tag chip row is 17 chips with no counts and no "selected" state visible [NOT OBS: selection state].

### 2.11 Library (`/library`) 7.5
At parity: filterable table by type/deal, Open/Download/Versions, versions drawer with Current/Restore, compare selects, "Undo last change". [OBS] `08-library-light.png`.
Issues: "Diligence checklist.txt / other" appears twice (one per deal) with only a Download action; no preview; type "other" is a dead label. Library row action text buttons ("Open Download Versions") are unlabelled for keyboard order [NOT OBS: tab order].

### 2.12 Notifications (`/notifications`, bell) 6.0
- Each run generates "Run needs your approval" **twice** plus "Run finished": 7 unread after two runs and a few clicks (`69-notifications-light.png`). Collapse to one per event; resolve "needs approval" when approved.
- Rows are not obviously clickable and have no deep link or avatar/context; no relative grouping (Today). Parity 66 needs "go to run" in one click.
- Unread dots in teal vs read state indistinguishable in the sidebar count; counts reach 7 within minutes.

### 2.13 Settings 6.5
Users: invite, role select, remove; owner row protected; viewer sees "Only owners can invite" (good) but then "No other users yet / Invite colleagues..." with an Invite button, which is false and misleading. [OBS] `41`.
- **Memory is absent** (parity 53): there is no Memory page; `/settings/memory` silently renders Preferences. Needs list with source, edit, delete.
- Audit log (`47`): USER shows `usr_09aecaacfc7d3d49`; ACTION includes raw route strings "POST /deals/{deal_id}/grids/split" and "auth.login" repeated ~40 times; TARGET and IP are clipped off-screen at 1440 (horizontal scroll). Resolve names, humanise actions, collapse repeated logins, and make the table fit.
- Sidebar shows lock icons on "Users" and "Audit log" for the owner; the lock reads as "locked to you" not "owner-only". Show the lock only to non-owners.
- Connectors (0 sources, 0 healthy) and Templates are well-written empty states with a next action. Mailbox form: dense but complete [NOT OBS: save].
- No SCIM, spend limits or custom MCP tools UI (parity 59, 61, 63) [NOT OBS: no controls found].

### 2.14 Command palette, keyboard 7.0
Ctrl+K opens quickly; typing "apple" returns Deals and Library results; `?` opens the shortcut sheet; `g d/a/n/s` work; Esc closes. [OBS] `52`, `53` (removed).
- The palette is an **Ask box with a deal selector** (textarea input, "No deal" select) that also searches. Enter is ambiguous: "run or open". Hybrid behaviour will cause accidental runs. Make the query field an input with explicit "Ask Acretia: <text>" as the first row.
- `j`/`k` on the Deals table produced no visible or programmatic focus change in my test (the keyboard shortcut sheet advertises "Move through a table"); `Enter` did not open a row. [OBS: could not observe an active-row change.] `[`/`]`, `c`, `e` (spec §6) are on-screen hints but absent from the sheet.
- Sheet is missing the screen-specific shortcuts.

### 2.15 Dark mode 8.0
Complete on Home, Run, Model, Deck, Grid; status colours stay legible, tokens consistent, the white slide on a dark pane is correct (`80-84`). Minor: the left nav is already navy in light so the theme change is invisible there (fine); the green numbers in model cells on dark (`83-model-dark.png`) are a touch saturated for sustained reading. No missing backgrounds seen. Contrast spot-checks: body text, teal links on dark, amber "awaiting approval" pill all appear above 4.5:1 [visual estimate, not measured].

### 2.16 Arabic / RTL 7.0
Layout mirroring is genuinely good: sidebar right, breadcrumbs, KPI order, side panel flips left, toolbars reverse, model sheet kept LTR for numbers (correct). [OBS] `85-deck-ar`, `86-grid-ar`, `87-home-ar`, `88-model-ar`, `89-pdf-ar`, `90-run-ar`.
Defects:
- **Bidi punctuation:** trailing punctuation jumps to the start of English strings: ".Project Atlas — Apple Inc" in table and cards, ".Agreement for covenants ... provisions" and "?What is the change of control clause" in the cell panel (`86`). Wrap embedded data in `<bdi>` or `dir="auto"` isolates.
- Truncation clips the wrong side in RTL: version dropdown shows "ound: 1 comment(s) applied to" (`85`); matrix cell "...ersified customer base and". Use `text-overflow` with logical direction on the container.
- The grid column order and the third column "Net Debt" is hidden under the side panel with no scroll cue.
- Home: starter-task titles mix Arabic with "DCF" / "Apple Inc" in a way that breaks line wrapping ("Inc. من أحدث إفصاحاتها" reads out of order).
- Digits default Latin (per spec) and the toggle is at Preferences and in the user menu; good.

### 2.17 Viewer role 6.5
Correct: deck shows no comment/apply/regenerate; model inputs read-only and Save disabled; API POST returns 403.
Issues: Home Ask box and Run button are enabled for a viewer, the click shows a red toast "The run could not be started. This action needs member access. Ask an owner of org_8078eb6fe1d11b76 for member access." (`65-viewer-ask-light.png`). Disable the box with "View-only access" and never print an org id. "New deal" is also offered to a viewer [OBS]; Users page shows the false empty state.

### 2.18 Mobile (390 px) [NOT OBS beyond Home and Run]
No horizontal scroll on Home or Run; the sidebar collapses to a hamburger; plan list and breadcrumbs wrap well (`56-mobile-run-light.png`). Parity 67 (query and source view) was not exercised on a phone.

## 3. Cross-cutting issues

1. **Trust path integrity (B1, B3, B5, B7):** four different citation sources, none lands on a highlighted span.
2. **Raw identifiers leak** into UI: `docs.status.indexed`, `job_79dbe8f7...`, `usr_09aecaac...`, `org_8078eb6f...`, `docs/null`, and the literal breadcrumb "Deal".
3. **Breadcrumbs inconsistent**: present on Run and Deal, "Deal /" on Model and PDF, absent on Deck and Grid.
4. **Microcopy**: "Matrix / Matrix", "DCF valuation" under a different request, "$0.00 estimate".
5. **Accessibility**: focus ring is visible on inputs and the shortcut sheet; text sizes 10-11 px in grid markers, sheet hints and pin icons are below the readable floor; `5.1` contrast on the amber pills and green numbers on dark is borderline [visual]. Touch targets of 12 px pin and link icons are below 24 px. Not a full WCAG audit.
6. **Performance** (replay mode): shell interactive about 1.5 s after login; run completes in ~2 s; first cell ~0.4 s; compare modal ~1.5 s. Real-model latency [NOT OBS].

## 4. Parity checklist (items 1-70)

PASS / PARTIAL / FAIL with evidence; "NO" = not observable in this session.

1 PASS: new matrix of 6 docs, 3 cited columns, first cell at ~0.4 s (replay only).
2 PASS: 2-step wizard, folder-grouped documents, split into columns.
3 NO: no run-condition UI exercised.
4 NO: variables bar present ("Add variable"), re-run on edit not exercised.
5 PARTIAL: Column Manager with run selected/all, reorder; rename/prompt/model swap not seen.
6 PARTIAL: Workflow view renders column nodes; no dependency edges to verify.
7 FAIL: no conditional-formatting control found.
8 FAIL: no "transfer to new Matrix/Chat" control found.
9 PASS: rows grouped under "01 Financials ... 05 Marketing".
10 PARTIAL: Export dialog offers logo header and source quote as cell notes; file not opened.
11 NO: Chat tab exists, not exercised at 1,000 rows.
12 NO: only 6 rows.
13 NO: no upload run; dropzone copy says per-file status.
14 PASS: per-table CSV links in the cell panel.
15 PARTIAL: run-view chip hover popover in <0.7 s (PASS); grid citation marker has no hover (FAIL).
16 FAIL: grid click-through opens the PDF with no highlight (404 on `gc_` token); run chip opens `docs/null`.
17 FAIL: tracing a figure to its span is not possible in under 2 min because no highlight exists.
18 PASS: "Download all sources" on the run view.
19 PARTIAL: slides carry "Source: ..." footer line; inline markers not verified; PPTX not opened.
20 NO: workbook cell notes not inspected (inspector shows precedents only).
21 NO: no data-provider card observed.
22 NO.
23 NO: PDF export not exercised.
24 PASS: source review approval step with "Skip this review next time".
25 NO: no scheduling UI observed.
26 NO.
27 NO.
28 NO.
29 NO.
30 PARTIAL: "/ for skills" hint and `skill-picker`; multi-skill run not exercised.
31 NO.
32 FAIL: search for "value a company" returns nothing; enable toggle exists, disabled-agent behaviour not tested.
33 PASS: step progress with per-step cost/time and Cancel run.
34 PARTIAL: 5-slide deck in ~5 s replay; 10-slide real timing NO.
35 PASS: one slide changed per revision, shown in compare.
36 PASS: comment pin, "title: Apple at a glance" applied in place (~4 s).
37 PASS: each round is a new version (v2 with message).
38 PASS: "Every other slide is byte-identical" asserted on the version created.
39 PASS: compare modal and "Roll back to v1"; library Restore.
40 NO: no Matrix>deck refresh seen.
41 NO: PPTX tables not opened.
42 NO.
43 PARTIAL: model "Ask" tab ("answers come from the workbook cells") present, no Q&A run.
44 PARTIAL: "Audit" tab in the model panel exists; contents not read.
45 NO.
46 NO.
47 NO.
48 NO.
49 NO.
50 NO.
51 NO.
52 PASS: Library lists the model, deck and checklist across deals, filterable.
53 FAIL: no Memory UI.
54 NO.
55 NO.
56 NO.
57 PASS: deal Activity tab lists runs and versions with actor (ids leak).
58 PASS: per-agent firm enable toggle.
59 NO.
60 PARTIAL: connectors dashboard with sources/healthy/indexed/last checked, empty.
61 NO.
62 NO.
63 NO.
64 PASS: shell usable ~1.5 s after login (replay, local).
65 PASS: dark mode complete on all key screens.
66 PARTIAL: bell drawer and page exist; duplicates and no deep links.
67 PARTIAL: 390 px Home/Run fine; query/source view not exercised.
68 NO.
69 PARTIAL: thumbs on the run view only; no per-answer or per-cell feedback seen.
70 PASS: starter tasks and next-action empty states on Home, Connectors, Templates, Grid.

Tally of the 70: PASS 18, PARTIAL 14, FAIL 6, NO (not observable) 32.

## 5. Top 15 fixes (ranked by buyer impact)

Each line: area; what; acceptance check.

1. **Citation resolver and highlight**: `om/api/citations.py`, grid citation minting, `frontend/src/viewers/*`. Resolve `gc_*` tokens (or store grid citations in `citations`), open the PDF at the page and scroll to and flash `bbox-highlight`; fill inspector quote/page/as-of/source link. Acceptance: e2e from a matrix cell, a run chip and a deck source line each end on a PDF with `bbox-highlight` >= 1 and `inspector-quote` matching the cell, in <= 2 s.
2. **Filing citations without a document**: `frontend/src/features/citations.tsx`. Never navigate to `docs/null`; for `kind=filing` open a source card (concept, value, period, as-of, EDGAR link). Acceptance: clicking any of 36 run chips never shows "Document not found".
3. **Documents tab**: `frontend/src/features/Documents.tsx`, `i18n/*.json`. Map API status `indexed` to a localised "Ready", show Open for every readable status, make the row a link. Acceptance: no text matching `/\w+\.\w+\.\w+/` in the table in EN, AR; row click opens `/docs/:id`; i18n test iterates the status enum.
4. **Matrix persistence**: grid page and deal Grid tab. No auto-creation of an empty grid; open the most recently modified; keep `?grid=`; fix tab count. Acceptance: create, reload, still see 3 columns; tab shows "Grid 1".
5. **Cell open and citation affordance**: grid cells. Single click or Enter opens the panel; marker opens the source with a hover preview (<0.5 s). Acceptance: `grid-cell` click shows `cell-panel`; hover on marker shows preview.
6. **Agent search**: `frontend/src/pages/Agents.tsx`, API search. Token-OR ranking, stop-word removal, description match. Acceptance: "value a company" returns "DCF valuation" first; "buyer list" and "data room review" return one result each.
7. **Deck canvas size**: deck viewer. Slide fits the pane width and top-aligns, zoom control; text readable at 1440. Acceptance: canvas width >= 800 px at 1440 and body text >= 9 px rendered.
8. **Deck source line link and version labels**: deck inspector, version select. Source line opens the cited span; versions labelled "v2 · 1 comment applied · 09:20" without job ids. Acceptance: no `job_` string visible; source line has `href`.
9. **Raw ids and breadcrumbs sweep**: shell. Breadcrumb on every deal-scoped page with the deal name (Model, PDF, Deck, Grid); resolve `usr_`/`org_`/`job_` to names in Audit, Activity, toasts. Acceptance: a Playwright text scan for `/(usr|org|job|doc)_[0-9a-f]{8}/` finds nothing on the 12 key screens.
10. **Viewer role**: Home, Deals, Users. Disable Ask/Run and hide New deal for viewers with "View-only access"; fix the false "No other users yet" empty state; remove org ids from errors. Acceptance: viewer Run is `disabled`; no toast on click.
11. **Notifications**: bell and page. One notification per event, "needs approval" resolves on approve, each row deep-links to its run and groups by day. Acceptance: a run with one approval and a finish creates 2 notifications, not 3.
12. **Memory page and audit readability**: Settings. Add Memory with source, edit, delete; humanise Audit (names, plain actions, collapse logins), fit width. Acceptance: `/settings/memory` lists entries with Delete; audit table shows no `usr_`.
13. **Arabic bidi and truncation**: shell, tables, panels. Wrap data strings in `<bdi>`/`dir=auto`; logical truncation. Acceptance: in `dir=rtl`, text content of `.acr-strong` data nodes does not start with `.` or `?`; version dropdown shows its start, not its end.
14. **Model workbench**: model view. Collapsible and narrower right panel; explicit WACC override input; breadcrumb with deal name. Acceptance: panel collapse key; "WACC" filter returns the WACC override.
15. **Command palette and keyboard**: palette, tables. Separate "Ask Acretia" row from search results; make `j/k` move a visible active row and `Enter` open; add all shortcuts to the sheet. Acceptance: on `/deals`, `j j k` moves `aria-selected` to row 2; Enter opens the deal.

## 6. What to re-test after fixes
Re-run all journeys in light, dark and Arabic; the citation e2e (fix 1-2) is the gate for this review. I will not raise the score above 7.5 while any citation path ends in a 404, an empty inspector or a non-highlighted PDF, and the Documents tab has no Open action.
