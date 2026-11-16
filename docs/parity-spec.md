# Parity spec: Hebbia and Rogo (public-source teardown, 2026-11-16)

Binding on the product, deck, grid, Excel and harness sessions (D-033).

**How reliable this is:**
- Every feature comes from vendor release notes (hebbia.com/blog "The Disclosure" Aug 2025–Oct 2026; rogo.com/news Nov 2025–May 2026).
- Pixel-level visuals and timings are **not public**. The time bars below are our proposals [INF].
- Hebbia is the benchmark for the grid, data-room scale and projects. Rogo is the benchmark for the banker loop: Excel plug-in, decks with an annotator, email-first agent.

## Information architecture to match

- **Agent home:**
  - an "Ask anything" box;
  - a source toggle;
  - starter tasks (deck, research, Excel model, skill).
- **Matrix:**
  - rows are documents or companies, columns are prompts;
  - follow-up columns;
  - inputs/variables;
  - Column Manager;
  - Workflow View (column dependency graph);
  - run conditions;
  - conditional formatting;
  - Matrix Chat over thousands of rows;
  - transfer filtered documents to a new Matrix or Chat;
  - a Document Source column (data-room folders);
  - export to Excel.
- **Projects:**
  - publish chats and matrices to a project (permissions inherited; chat snapshots forkable);
  - folders;
  - instructions;
  - an Activity tab;
  - breadcrumbs.
- **Agents and Skills:**
  - a library (search, tags, pin);
  - "/" skills, combinable;
  - share and import;
  - admins enable or disable individual agents;
  - scheduled agents;
  - an email agent (Hebbia Intern, Rogo Felix);
  - a pre-run source-review step;
  - a tick-and-tie agent.
- **Library** of every artifact (Rogo).
- **Memory:** visible, editable and deletable, with sources; admins control it.
- **Notifications centre; Sources/connectors dashboard; Groups.**
- **Deliverables:**
  - decks in firm branding (edit per slide, reorder, regenerate one slide);
  - native PowerPoint tables;
  - slide citations in the footer;
  - Excel citations as cell notes;
  - version history with compare and rollback;
  - a **comment-anchored slide annotator** that edits in place and never regenerates accepted slides (Rogo).
- **Plug-ins:** Excel (side panel, firm templates, link and audit tabs) and Word.
- **Mobile:** iOS. **Dark mode.** Hebbia also has an MCP/API.

## Acceptance checklist

Given/when/then, plus a time bar. H = from Hebbia, R = from Rogo.

**Grid (H)**
1. Add a natural-language column to a 5-document Matrix → cited answers stream in; first cells within 10 s.
2. A two-step creation wizard: choose documents, then split the question into columns.
3. A column run condition skips rows visibly.
4. Editing an input variable re-runs the dependent columns.
5. Column Manager: rename, reorder, edit prompt, swap model, bulk run.
6. Workflow View shows the column dependency graph.
7. Conditional formatting with AND/OR rules.
8. Transfer filtered documents to a new Matrix or Chat.
9. A Document Source column groups by data-room folder.
10. Excel export keeps values, with a logo option.
11. Matrix Chat over 1,000+ rows answers with row citations; first tokens within 5 s.
12. A 500-row grid scrolls and sorts at 60 fps.
13. A 100-file upload shows status per file, overall progress, and failure alerts.
14. Tables auto-extracted from PDFs can be exported.

**Citations (H+R)**

15. Hovering a citation previews the source within 0.5 s without leaving the view.
16. Clicking a citation opens the source scrolled to the highlighted span within 2 s.
17. A reviewer who wasn't in the demo traces a random figure to its source in under 2 min.
18. The source panel has a "download all sources" control.
19. Exported slides carry inline markers with sources in the footer.
20. A hard-coded Excel cell shows its source (note or click-through).
21. Data-provider citations render as cards with links.
22. Low-credibility web sources are excluded.
23. PDF exports keep citations and the logo.

**Agents**

24. A pre-run source-review step (which can be turned off).
25. Scheduled runs (daily, weekly, custom, a single future date) email a summary.
26. An email request returns citations and files; simple tasks under 10 min.
27. Felix-style email deck requests land in the Library and email; simple decks under 15 min.
28. Recurring monitoring by email.
29. A buyer email saves material to the project folder.
30. "/" multi-skill runs.
31. Tick-and-tie cross-checks page by page.
32. Agent search by description respects admin-disabled agents.
33. Long runs show step progress and a cancel control.

**Decks**

34. A branded 10-slide deck in under 3 min.
35. Editing one slide changes only that slide.
36. Comment anchors on the slide apply in a bulk revision in place.
37. Each annotation round is a version.
38. Accepted slides stay byte-identical when another slide is revised.
39. Version compare and rollback.
40. Template slides refresh when the Matrix data updates.
41. Tables are native and editable.

**Excel and Word**

42. Plug-in side panel workflow with firm templates.
43. Multi-tab model Q&A reconciles to the workbook's values.
44. A tab audit lists links and errors.
45. A Word plug-in drafts sections in place.
46. A generated sheet matches the structure of the reference file.

**Chat**

47. Editing an earlier message regenerates from that point.
48. Collapsible tables.
49. Inline charts: candlestick, dual-axis, debt-maturity tower.
50. CSV upload joins other sources.
51. Pasting into PowerPoint, Word or email keeps the formatting.

**Library, memory, projects**

52. The Library lists every artifact.
53. Memory entries show their source and can be edited or deleted.
54. Chats published to a project are forkable snapshots.
55. A published Matrix inherits project permissions.
56. Teammates added to a project see everything shared in it.
57. The Activity tab.

**Admin**

58. Admins can toggle agents.
59. SCIM deprovisioning.
60. A sources dashboard.
61. Spend limits by team or deal.
62. Search mirrors the connector's permissions.
63. Custom MCP tools appear for users.

**Performance and polish**

64. The shell is interactive within 3 s.
65. Dark mode is complete.
66. A notifications centre.
67. A mobile query and source view.
68. Audio keeps playing when locked (Hebbia).
69. In-app feedback on any answer.
70. A starter state, never a blank page.

## Where we must beat them, not just match

- Measured accuracy: no silent wrong numbers, every figure tied or flagged.
- Formula integrity and circularity: every competitor scored 0 at WSP.
- MENA, Arabic and IFRS/EAS depth.
- Bbox-precise citations on scanned and Arabic documents.
- Measured time saved (`docs/time-saved-baselines.md`).

## Gaps to close with our own observation

The Matrix visual spec, cell states, the column-type menu, how a citation opens (hover vs side pane), the Max run view, Felix's email round trip, the annotator's interaction model, and roles/audit UX. To close them, capture the public demo videos and pages and describe them in this document.
