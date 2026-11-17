# Product screenshots (real app, not mocks)

Captured by the session-F Boss from the running app: `python3 -m om.api seed-demo` + `serve --demo`, `ACRETIA_LLM_MODE=replay`, frontend built from main, Chromium 1440×900, signed in as the demo owner.

| File | What it shows | State |
|---|---|---|
| `01-login.png` | Sign-in | Works; visible 380 ms after navigation |
| `02-home.png` | Agent home: "Ask anything", source toggle, starter tasks, empty-state actions | Works |
| `03-deals.png` | Deals list with the two seeded deals (6 indexed documents each) | Works |
| `04-run-not-wired.png` | Submitting "3-statement + DCF for Apple" | **Fails**: the job runtime (SF.1c) isn't merged yet, so `POST /api/v1/jobs` is 404 and the toast has no next step. Known, being fixed |

| `05-matrix-empty.png` | Matrix grid on a deal with 6 indexed documents, before the first column | Works; **defect**: no page gutter against the sidebar (being fixed) |
| `06-pdf-inspector.png` | Split-pane PDF viewer (pdf.js) with the citation inspector, on a seeded annual-report excerpt | Works |

On main but not yet screenshotted with real deliverables: model view (live recompute, audit overlay) and deck viewer (validator badges, anchored comments), because runs don't complete in the UI until the integration fixes (SF.5) land. No grader (gate, UI/UX lead, personas) has passed yet.
