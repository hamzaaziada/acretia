# Product screenshots (real app, not mocks)

Captured by the session-F Boss from the running app: `python3 -m om.api seed-demo` + `serve --demo`, `ACRETIA_LLM_MODE=replay`, frontend built from main, Chromium 1440×900, signed in as the demo owner.

| File | What it shows | State |
|---|---|---|
| `01-login.png` | Sign-in | Works; visible 380 ms after navigation |
| `02-home.png` | Agent home: "Ask anything", source toggle, starter tasks, empty-state actions | Works |
| `03-deals.png` | Deals list with the two seeded deals (6 indexed documents each) | Works |
| `04-run-not-wired.png` | Historical: the run flow before the jobs runtime merged (404) | Superseded by 07 |

| `05-matrix-empty.png` | Matrix grid on a deal with 6 indexed documents, before the first column | Works; **defect**: no page gutter against the sidebar (being fixed) |
| `06-pdf-inspector.png` | Split-pane PDF viewer (pdf.js) with the citation inspector, on a seeded annual-report excerpt | Works |

| `07-run-dcf-done.png` | Run view after "3-statement + DCF for Apple at 9% WACC": 5 steps done with per-step time/cost, 36 sources, time-saved estimate with its basis | Works end to end (replay mode: cost $0) |
| `08-model-view.png` | Model view of the produced workbook: headline outputs, sheet tabs, blue/black/green classes, cell inspector with precedents/dependents, assumptions, checks | Works; live recompute 170–240 ms (worker-measured) |
| `09-deck-view.png` | Deck viewer of the produced profile deck: thumbnails, slide canvas, validator, sources, comment annotator | Works; slide canvas leaves unused space (review pending) |
| `10-library.png` | Org-wide library of deliverables | Works |
| `11-home-dark.png` | Agent home in dark mode | Works |

Known defects being fixed (SF.7): runs without a deal create a new deal instead of attaching to the matching one; source-review selection isn't honoured yet. The UI/UX-lead review (docs/product/uiux-review-1.md) and the personas haven't passed yet.
