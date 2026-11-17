# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: the deal professional at a boutique or mid-market advisory firm.** An M&A analyst, associate or VP, or a private-equity / corporate-development associate. They work on live transactions under time pressure, often several at once, and they are personally accountable for every number that leaves their desk.

Their situation:

- They are handed a data room (CIMs, audited accounts, management accounts, filings, a management model) and asked for a view in days, not weeks.
- They already own Excel and are fast in it. They will not adopt a tool that is slower than Excel for the work they already do in Excel.
- They are judged on the quality of the analysis and on whether a number can be defended when a partner, an investment committee or a client asks "where did this come from?".
- They work on a laptop, with a mouse and a trackpad, in a browser, often with a second screen. They are frequently interrupted and come back to work in progress.

**Secondary: the reviewer.** A partner, MD or investment-committee member who did not build the analysis and needs to check it quickly. They read, they do not edit. Their question is always provenance and sanity, never mechanics.

## Product Purpose

Acretia turns a deal's documents into a defensible financial analysis: an integrated three-statement model, a DCF, comps, an LBO, a diligence grid and a deck, all built from the source documents, with every number traceable back to the page it came from.

It exists because the alternative is a week of manual spreading, and because the failure mode of that week is a number nobody can source.

Success means: a deal professional can open a deal, see what the analysis says and what needs attention, open any number, and answer "where did this come from, and which period is it?" in one action, without leaving the screen they are on.

## Positioning

Every figure in the product carries its provenance as a first-class object, not as a footnote. A cell knows its formula, its precedent chain, its period, and the document page and bounding box it ultimately rests on. The product can therefore answer "where did this number come from" for any number it shows, including numbers it calculated itself, and it can show the source page rather than describing it.

A neighbouring product can copy the model output. It cannot copy the provenance graph without rebuilding the extraction, the workbook graph and the citation layer as one system.

## Operating Context

- **Deals** are the unit of work. A deal holds documents, deliverables (workbooks, decks, grids) and runs.
- **Deliverables** are versioned. A model has versions; a version is immutable once written.
- **Runs** are agent executions that produce deliverables. They stream progress and can be re-run.
- **The model viewer** is a live spreadsheet: the user can edit an input cell and the workbook recalculates in the browser session, with a checks panel and an audit overlay.
- **The grid viewer** is a documents-by-prompts matrix where every cell is an extractive answer quoted verbatim from a page, with page and bounding box.
- **The PDF viewer** renders the source document with a text layer and highlights the cited bounding box.
- **The deck viewer** renders slides with per-span citations.
- **Roles:** owner, admin, member, viewer. A viewer reads and does not edit.
- **Languages:** English and Arabic, with full RTL mirroring. A spreadsheet's A1 origin stays top-left in both.
- **Themes:** light and dark, following the system by default.

## Capabilities and Constraints

Confirmed:

- Deterministic engines own all arithmetic: `om.formula` for formulas, `om.modelcheck` and `validate_xlsx.py` for workbooks, LibreOffice recalculation as a cross-check, `validate_pptx.py` for decks, `om.spacing` for geometry.
- `om.wbgraph` builds the workbook dependency graph and answers `explain` for any cell: formula, value, a labelled precedent tree to depth 2, the leaf inputs, and each leaf's source comment or link.
- `om.wbgraph.label_of` already composes a human label for a cell from its row label and its period header, for example `Revenue (FY2026E)`.
- Citations are stored with document, page, bounding box, quote, URL, as-of date, XBRL concept and cell locator. A citation can exist without a document when it is XBRL-backed.
- The API is stdlib-only Python. The frontend is React with a local design system in `frontend/src/ds/`.
- No live LLM calls in tests or gates. Replay fixtures only.

Undecided or open:

- Whether the cell explain drawer should also be reachable from the grid viewer and the deck viewer, or only from the model viewer. The spec proposes model first.
- Whether the deal board replaces the current Home page or sits alongside it. The spec proposes replacing it.

## Brand Commitments

- The product name is Acretia.
- The interface is English and Arabic, and RTL is a first-class requirement, not a translation layer.
- The visual register is a professional instrument: dense, quiet, precise, and trustworthy. The user's own words for the bar are "similar to something like Bloomberg", meaning fast, information-dense, keyboard-friendly and reliable, not literally a terminal aesthetic.
- The stated quality bar is parity with Hebbia and Rogo in UX, UI, features, quality and speed. `docs/parity-spec.md` is binding.

## Evidence on Hand

- `docs/parity-spec.md`: the Hebbia and Rogo teardown and the binding acceptance checklist.
- `docs/product/SPEC.md`: the product app architecture and contracts.
- `docs/samples/product/`: real screenshots of the running app, captured from the built frontend.
- `docs/samples/s4/png/`: rendered model pages.
- `docs/reviews/`: specialist review findings.
- `docs/teardowns/`: teardown findings, labelled by evidence class.
- `reference/meshpool-harness/`: prior internal work, MIT, the user's own project.

Absences that future work must not fabricate: there is no user research with named participants, no customer testimonials, no usage analytics, and no measured task timings from real users. `docs/time-saved-baselines.md` holds estimates, and they are estimates.

## Product Principles

1. **Provenance is one action away, from anywhere.** Any number the product shows can be opened to reveal its formula, its chain, its period and its source page, without navigating away from the work.
2. **The screen is a working instrument, not a document.** Density, keyboard reach and a stable layout beat whitespace and decoration. Nothing that the user needs to compare should require horizontal scrolling.
3. **The product tells the truth about its own confidence.** A proxy price, an estimate, a missing source and a failed check are all visible states, never hidden and never smoothed over.
4. **Deterministic code owns the numbers; the model owns the language.** Arithmetic, geometry, contrast and formatting are computed. Prose and art direction are generated.
5. **A reviewer's question is a first-class use case.** The product is designed for the person checking the work as much as for the person doing it.

## Accessibility & Inclusion

- Target: WCAG 2.1 AA. Contrast, focus visibility, keyboard reach and touch target size are checked, not assumed.
- Full keyboard operation of the model grid, including selection, editing, sheet stepping and opening the explain drawer.
- RTL and Arabic are required, with logical CSS properties throughout.
- Light and dark themes are both required, and both must pass contrast.