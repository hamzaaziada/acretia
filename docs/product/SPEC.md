# Acretia product app — architecture and contracts (session F)

Owner: session F (Boss). This document is the contract every session-F worker builds against. If code and this file disagree, this file wins until the Boss changes it. Decisions are logged as `D-SF-xx` in `DECISIONS.md`.

## 1. Shape

```
browser ──HTTPS──▶ om/api (stdlib ThreadingHTTPServer, one process)
                    ├── /api/v1/*     JSON API (versioned) + SSE streams
                    ├── /assets/*     frontend/dist (Vite build, hashed files, immutable cache)
                    └── /*            frontend/dist/index.html (SPA fallback)
                   SQLite WAL (data/app/acretia.db) · LocalBlobStore (data/app/blobs) · adapter ledger
                   engine calls: om.model3 / om.formula / om.deals / om.deck / om.grid / om.matrix / src.harness.*
```

- **Backend** `om/api/` — Python 3.10+ standard library only (D-SF-01). No framework.
- **Frontend** `frontend/` — React 18 + TypeScript + Vite, react-router-dom, pdfjs-dist; our own design system, no UI kit (D-SF-02).
- **E2E** `e2e/` — @playwright/test 1.63.0 against the real server in replay mode.
- Run: `python3 -m om.api serve --port 8791 [--data data/app] [--demo]`. `--demo` seeds the demo org (§7). Build UI: `cd frontend && npm ci && npm run build`.

## 2. Backend module map (`om/api/`)

| Module | Owns |
|---|---|
| `__init__.py`, `__main__.py` | CLI: `serve`, `seed-demo`, `create-org`, `poll-mail` |
| `db.py` | `connect(path) -> sqlite3.Connection` (WAL, `row_factory=sqlite3.Row`, foreign keys on, `check_same_thread=False`), `migrate(conn)` applying every module's `SCHEMA` from `SCHEMA_MODULES` (import-tolerant: a module that isn't there yet is skipped), `new_id(prefix)`, `now()` (UTC ISO `...Z`) |
| `http.py` | `RequestContext`, `Response` helpers, `SSE`, `ApiError`, router (`Route`, path params `{id}`), JSON body limits |
| `server.py` | handler, security headers, CSRF/Origin, session resolution, static/SPA serving, route collection from `ROUTE_MODULES` |
| `auth.py` | users, orgs, memberships, roles, password hashing, sessions, invites, routes `/auth/*`, `/org/*` |
| `audit.py` | append-only hash-chained audit log + `/audit` route |
| `deals.py` | deals/projects (wraps `om.deals.DealStore` per org), documents upload, routes `/deals/*` |
| `library.py` | deliverables: versions, diff, undo, restore, download (wraps `DealStore`), routes `/deals/{id}/deliverables/*` |
| `notify.py` | notifications table, `notify(conn, org_id, user_id|None, kind, title, body, link)`, routes `/notifications/*`, SSE `/events` |
| `jobs.py` | job store + runner threads, step events, cost from the adapter ledger, resume on restart, routes `/jobs/*` |
| `agents/` | intent planner, agent library (built-ins + saved), step executors that call engines (`agents/engines.py`) |
| `viewers.py` | document pages/text/citations, grid view data, model view (assumptions, recompute through `om.formula`, audit overlay), deck view (slides, badges, comments) |
| `firm.py` | firm setup: templates and sample decks, accounting definitions, connectors, mailbox settings |
| `mail.py` | IMAP (and maildir) poller for email-in requests |
| `security.py` | CSP string, cookie flags, rate limiter, constant-time compares, upload sniffing |

`SCHEMA_MODULES` and `ROUTE_MODULES` are tuples of dotted module names in `db.py` / `server.py`. Each listed module exposes `SCHEMA: str` (DDL, `CREATE TABLE IF NOT EXISTS`) and/or `ROUTES: list[Route]`. A worker adds its module name to those tuples **only** if it owns `db.py`/`server.py`; otherwise the Boss adds it at merge. All tuples are pre-populated with every planned module name from the table above, so workers don't need to edit them.

### 2.1 Handler contract

```python
Route(method: str, pattern: str, handler: Callable[[RequestContext], Any], role: str = "member", csrf: bool = True)
# pattern like "/api/v1/deals/{deal_id}/deliverables/{name}"; role in {"public","viewer","member","owner"}

class RequestContext:
    method: str; path: str
    params: dict[str, str]        # path params
    query: dict[str, str]         # first value of each query key
    body: bytes; json: Any        # json is None when the body is empty / not JSON
    headers: Mapping[str, str]
    conn: sqlite3.Connection      # per-request connection (thread-local)
    blobs: BlobStore
    data_dir: Path
    user: dict | None             # {"id","email","name","locale"}
    org_id: str | None; role: str | None   # from the session's active membership
    session_id: str | None
    def audit(self, action: str, target: str = "", detail: dict | None = None) -> None
    def require(self, role: str) -> None   # raises ApiError(403, "forbidden", ...)

# Handlers return one of:
#   dict | list                      -> 200 application/json
#   (status: int, dict | list)       -> that status, JSON
#   Response(status, body: bytes, content_type, headers={}) -> raw (downloads)
#   SSE(iterator_of_(event: str, data: dict))  -> text/event-stream, flushed per event, 15 s keep-alive comments
# Raise ApiError(status, code, message, hint=None) for errors.
```

Error body (every non-2xx): `{"error": {"code": "snake_case", "message": "human sentence", "hint": "what to do next"}}`. **No dead ends**: `hint` is mandatory for 4xx except 404 on a resource the caller can't see.

### 2.2 Security invariants (enforced by tests and the gate)

1. **Sessions**: cookie `acr_session` = 32-byte random token (urlsafe b64); DB stores only `sha256(token)`. Flags `HttpOnly; SameSite=Strict; Path=/`, plus `Secure` when the request came over HTTPS or `ACRETIA_SECURE_COOKIES=1`. Idle expiry 12 h, absolute 7 days. Logout deletes the row.
2. **CSRF**: every non-GET/HEAD/OPTIONS route with `csrf=True` requires (a) `Origin` (or `Referer` when Origin is absent) whose host:port equals the `Host` header or is listed in `ACRETIA_ALLOWED_ORIGINS`, and (b) header `X-CSRF-Token` equal to the session's CSRF token (returned by `GET /api/v1/auth/me` and `POST /auth/login`; stored hashed). Failure → 403 `csrf_failed`. Login/signup use Origin check only.
3. **Passwords**: `hashlib.scrypt(n=2**14, r=8, p=1, dklen=32)`, 16-byte salt, stored as `scrypt$n$r$p$salt_b64$hash_b64`; min length 10; constant-time compare. Login rate limit: 10 failures / 15 min per email+IP → 429 with hint.
4. **Tenancy**: every tenant table has `org_id TEXT NOT NULL`; every query on it filters `org_id = ctx.org_id`. A resource from another org returns **404** (never 403, never leaks existence). `tests/test_api_tenancy.py` creates two orgs and asserts every GET/POST/PATCH/DELETE route in `ROUTES` with an id param returns 404 cross-org (route table driven, so new routes are covered automatically).
5. **RBAC**: `viewer` < `member` < `owner`. viewer: read-only. member: create deals, run agents, upload, comment, edit assumptions. owner: everything + firm setup, users/roles, connectors, mailbox, audit log export. Enforced by `Route.role` and re-checked in handlers that mutate org settings.
6. **Headers on every response**: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`. API responses add `Cache-Control: no-store`. No inline scripts or styles in `index.html` (Vite build must not emit any; React `style={}` attributes are fine because they are DOM properties, not inline `<style>`).
7. **Host guard**: when bound to localhost, `Host` must be `localhost`/`127.0.0.1`/`[::1]` with the bound port (DNS-rebinding guard, as in `om/web.py`). When bound elsewhere, `ACRETIA_ALLOWED_HOSTS` is required at startup.
8. **Uploads**: max 200 MB per request, filenames sanitised (`[^\w.\- ]` → `_`, no path parts), type sniffed from magic bytes (PDF, XLSX/PPTX/DOCX zip, ZIP, EML, PNG/JPEG, CSV/TXT); zips go through the existing ZipSlip/bomb-safe unpacker (`src/harness/connectors` if present, else a local safe unpacker with the same limits: ≤ 10k entries, ≤ 2 GB uncompressed, ratio ≤ 200, no absolute/`..` paths).
9. **Secrets**: no key, token or password in `frontend/` or in any API response. Connector/mailbox secrets are stored encrypted-at-rest with a key from `ACRETIA_SECRET_KEY` (HMAC-SHA256 keystream, stdlib) and are write-only through the API (GET returns `"••••"` + last 4).
10. **Audit**: every mutating request and every agent step writes an audit row: `seq, org_id, user_id, action, target, detail_json, ip, ua, at, prev_hash, hash` (`hash = sha256(prev_hash + canonical JSON of the row)`). `GET /api/v1/audit/verify` (owner) re-walks the chain.
11. **Model calls** only via `src/harness/adapter.py`. In tests and gates `ACRETIA_LLM_MODE=replay`; zero sockets.
12. **Email**: the app never sends email unless the org owner sets `mail.send_enabled=true` (default false; there is no SMTP code path at all unless it is true).

## 3. Data model (SQLite)

All ids are `prefix_` + 16 hex (`org_`, `usr_`, `ses_`, `deal-`(DealStore), `job_`, `ntf_`, `doc_`, `agt_`, `cmt_`, `tpl_`, `con_`).

- `orgs(id, name, slug UNIQUE, locale, created_at, settings_json)`
- `users(id, email UNIQUE COLLATE NOCASE, name, password_hash, locale DEFAULT 'en', created_at, disabled INT)`
- `memberships(org_id, user_id, role CHECK(role IN ('owner','member','viewer')), created_at, PRIMARY KEY(org_id,user_id))`
- `sessions(id, token_hash UNIQUE, csrf_hash, user_id, org_id, created_at, last_seen, ip, ua)`
- `invites(id, org_id, email, role, token_hash, created_by, created_at, accepted_at)`
- `audit_log(org_id, seq, user_id, action, target, detail_json, ip, ua, at, prev_hash, hash, PRIMARY KEY(org_id, seq))`
- deals: reuse `om.deals` tables (`deals`, `deal_memory_versions`, `deal_deliverables`) via `DealStore(conn, blobs, org_id)`; plus `deal_meta(org_id, deal_id, status, sector, target, created_by, updated_at)` and `documents(id, org_id, deal_id, name, kind, sha256, size, pages, status, progress, lang, created_at, error)`.
- `jobs(id, org_id, deal_id, user_id, agent_id, kind, prompt, status, plan_json, steps_json, tokens, cost_usd, started_at, finished_at, error, source CHECK(source IN ('app','email','schedule','api')), resume_from INT)`
- `job_events(job_id, seq, at, type, data_json, PRIMARY KEY(job_id, seq))` — the stream; SSE replays from `Last-Event-ID`.
- `notifications(id, org_id, user_id NULL, kind, title, body, link, created_at, read_at)`
- `comments(id, org_id, deal_id, target_kind, target_ref, slide_or_cell, body, author_id, created_at, status, job_id)`
- `agents(id, org_id, name, description, kind, steps_json, prompt_template, created_by, shared INT, created_at, builtin INT)`
- `firm_assets(id, org_id, kind CHECK(kind IN ('template','sample_deck','sample_model','logo')), name, sha256, size, created_at, style_json)`
- `connectors(id, org_id, kind, name, config_json, secret_enc, status, last_sync, created_at)`
- `mailbox(org_id PRIMARY KEY, kind CHECK(kind IN ('imap','maildir')), host, port, username, secret_enc, folder, path, poll_seconds, allowed_senders_json, send_enabled INT DEFAULT 0, last_uid, last_poll, status)`

Firm accounting definitions (Adjusted EBITDA, Net Debt, …) live in `orgs.settings_json["definitions"]` and are copied into each new deal's `DealMemory.definitions` (deal can override).

## 4. API (all under `/api/v1`, JSON, cookies)

| Method & path | Role | Purpose |
|---|---|---|
| `POST /auth/signup` | public | `{email,password,name,org_name}` → creates org + owner; disabled unless `ACRETIA_ALLOW_SIGNUP=1` or no orgs exist |
| `POST /auth/login` / `POST /auth/logout` / `GET /auth/me` | public / viewer / viewer | me → `{user, org, role, orgs:[...], csrf_token}` |
| `POST /auth/switch-org` | viewer | `{org_id}` (must be a member) |
| `POST /auth/invites/accept` | public | `{token, name, password}` |
| `GET/POST /org/members`, `PATCH/DELETE /org/members/{user_id}`, `POST /org/invites` | owner (GET: member) | users & roles; cannot remove/demote the last owner |
| `GET /audit?limit&before`, `GET /audit/verify`, `GET /audit/export.csv` | owner | |
| `GET/POST /deals`, `GET/PATCH /deals/{deal_id}` | viewer/member | deal workspace header: name, target, sector, status, counts |
| `POST /deals/{deal_id}/documents` (multipart or raw with `X-Filename`) ; `GET /deals/{deal_id}/documents`; `GET /documents/{doc_id}`; `GET /documents/{doc_id}/file`; `GET /documents/{doc_id}/pages/{n}/text` | member / viewer | upload/index with progress (indexing runs as a job) |
| `GET /deals/{deal_id}/deliverables`; `GET .../deliverables/{name}/versions`; `GET .../versions/{v}/download`; `GET .../diff?a=&b=`; `POST .../undo`; `POST .../restore {version}` | viewer / member | library |
| `POST /jobs {prompt, deal_id?, agent_id?, inputs?}` → `{job}`; `GET /jobs?deal_id&status`; `GET /jobs/{id}`; `GET /jobs/{id}/events` (SSE); `POST /jobs/{id}/cancel`; `POST /jobs/{id}/resume`; `POST /jobs/{id}/approve {step, payload}` (ghost-deck approval gate) | member / viewer | agent runs |
| `GET /agents`; `POST /agents`; `PATCH/DELETE /agents/{id}`; `POST /agents/{id}/run` | viewer / member | agent library (built-ins are read-only) |
| `GET /notifications?unread=1`; `POST /notifications/{id}/read`; `POST /notifications/read-all`; `GET /events` (SSE: notifications + job status for the org) | viewer | |
| `GET /citations/{token}` → `{doc_id, page, bbox_norm, quote, as_of, url, doc_name}` | viewer | resolve a citation token used by any viewer |
| `GET /deals/{deal_id}/grid` ; `POST /deals/{deal_id}/grid/columns`; `POST /deals/{deal_id}/grid/rows`; `GET /deals/{deal_id}/grid/estimate` | viewer / member | matrix view (S5 engine when present; `om.matrix` extractive fallback) |
| `GET /models/{deal_id}/{name}` → sheets, cells (value, formula, style class input/calc/link, citation token), assumptions list; `POST /models/{deal_id}/{name}/recompute {changes:{"Sheet!A1": value}}` → changed cells + checks; `POST .../save` → new deliverable version | viewer / member | model view |
| `GET /decks/{deal_id}/{name}` → slides (png preview urls, titles, sources, validator badges); `GET /decks/{deal_id}/{name}/slides/{n}.png`; `POST /decks/{deal_id}/{name}/comments {slide, body}` → starts an edit job | viewer / member | deck view |
| `GET/PUT /firm/definitions`; `GET/POST/DELETE /firm/assets`; `GET/POST/PATCH/DELETE /firm/connectors`; `GET/PUT /firm/mailbox`; `POST /firm/mailbox/test` | owner (GET: member) | firm setup |
| `GET /healthz` | public | `{ok, version, llm_mode, engines:{deck:bool, grid:bool, excel:bool, research:bool, intl:bool}}` |

Pagination: `?limit` (≤ 200, default 50) and `?cursor`; responses `{items, next_cursor}`.

## 5. Jobs and agents

Job lifecycle: `queued → planning → running → (awaiting_approval → running)* → done | failed | cancelled`. Statuses map onto `om.contracts.STATUS` where they overlap; the API uses the list above.

Event types on `/jobs/{id}/events` (each persisted in `job_events` before it is sent):

| type | data |
|---|---|
| `plan` | `{steps:[{id,title,tool,engine}], estimate:{cost_usd, seconds}}` |
| `step` | `{id, status: running|done|failed|skipped, title, detail, started_at, finished_at, cost_usd, tokens}` |
| `source` | `{citation_token, doc_name, page, quote, url, as_of}` |
| `log` | `{level, message}` |
| `approval` | `{step_id, kind:"ghost_deck"|"assumptions", payload}` — job pauses in `awaiting_approval` |
| `deliverable` | `{deal_id, name, version, kind, url}` |
| `cost` | `{tokens, cost_usd}` (running totals from the adapter ledger, per job id) |
| `status` | `{status, error?, hint?}` |

Resumability: each step's output is checkpointed (`steps_json`). On server start, jobs in `planning|running` are re-queued and continue from the first step not `done`. `POST /jobs/{id}/resume` does the same for `failed` jobs.

Planner: **rule-first** (D-SF-06). `agents/planner.py` maps the prompt to a built-in agent with regexes/keywords + entity extraction (tickers, company names from the deal, WACC/assumption overrides like "9% WACC"); only unmatched prompts go to the adapter (`json_schema` output, replay fixtures in tests). Built-in agents (P-J8) cover the 14 catalogue tasks of PLAN "North-star metrics" (D-032), each with a stable `task_id` used by the time-saved benchmark: `comps` (trading comps), `precedents`, `three_statement`, `dcf`, `lbo`, `merger`, `vdr_review` (CIM/VDR first pass, per 50 docs), `profile` (company profile / one-pager), `pitchbook_section`, `teaser`, `ic_memo`, `earnings_update` (model roll-forward), `earnings_recap`, `buyer_list`. Plus the editing agents `deck_edit` and `model_edit`, and `diligence_grid` (used by `vdr_review`).

**Telemetry (D-032).** Every step records `started_at`, `finished_at`, `seconds`, `tokens`, `cost_usd` and `engine`; the job records totals plus `wall_seconds`. These are in `steps_json` and in the `step` events. A delivered job also gets `time_saved = {task_id, t_h_minutes:{low,mid,high,source}, t_a_minutes, pct}` from the baselines table (`docs/time-saved-baselines.md`, parsed by `eval/tsb/baselines.py`), where `t_a_minutes` = wall time + estimated review/fix minutes (§11). The run view and the command bar show it as an estimate with its source until it is human-validated.

Engine adapters (`agents/engines.py`) — each returns artefact bytes plus citations and is feature-detected (`healthz.engines`):
- Excel: `om.model3.build(statements, assumptions=...)`; later S4 (`om.lbo`, `om.merger`, `om.comps`, `om.rollforward`, `om.manifest`, `om.validate_xlsx`) when importable.
- Deck: S3 `om.deck` render when importable; until then `om.studio`/`om.pptx` path. Ghost deck via `om.deck.ghost` (landed).
- Grid: S5 `om.grid` when importable; else `om.matrix.answer_row_extractive`.
- Research: S6 `src.harness.research` (session A, S6.0 interface) when importable; else `om.ask`.
- Statements: `om.statements` from cached SEC data, or the offline fixture `tests/fixtures/api/companyfacts_*.json` in demo/replay mode.

A missing engine is never faked: the step fails with `status: failed`, `hint: "The <deck> engine hasn't landed yet; …"`, and the job continues with the steps that can run.

## 6. Frontend

Routes: `/login`, `/` (Home: command bar, recent runs, deals), `/deals/:id` (workspace tabs: Overview · Documents · Grid · Models · Decks · Library · Activity), `/runs/:jobId` (agent run view), `/deals/:id/docs/:docId?page=&cite=` (PDF + inspector), `/deals/:id/models/:name`, `/deals/:id/decks/:name`, `/agents`, `/notifications`, `/settings/{firm,definitions,templates,users,connectors,mailbox,audit}`.

Design system (`frontend/src/ds/`): tokens as CSS custom properties (`--acr-*`), light + dark, 4 px spacing grid, 13 px base UI size, tabular numerals everywhere numbers appear, Inter / IBM Plex Sans Arabic / JetBrains Mono. Institutional palette: ink navy, slate neutrals, one accent, semantic green/amber/red that pass WCAG AA (4.5:1 text, 3:1 UI). Logical CSS properties only (`margin-inline-start`, never `margin-left`) so `dir="rtl"` flips correctly. Components: Button, IconButton, Input, Select, Tabs, Table (virtualised, sticky header, keyboard nav), Badge, Pill, Toast, Dialog (focus-trapped), Drawer, SplitPane, CommandPalette, Kbd, EmptyState (always has a next action), Skeleton, ProgressBar, Stepper, Tooltip, Avatar, Sidebar.

Keyboard: `⌘K`/`Ctrl+K` command bar, `g d` deals, `g a` agents, `g n` notifications, `g s` settings, `?` shortcut sheet, `j/k` list nav, `Esc` close, `[`/`]` prev/next slide or page, `c` comment (deck), `e` edit cell (model).

i18n: `frontend/src/i18n/{en,ar}.json`, `t(key)`; switching to Arabic sets `<html lang="ar" dir="rtl">`; numbers keep Latin digits by default with a per-user setting for Arabic-Indic digits; every string in the UI comes from the catalogues (gate checks no missing keys in `ar`).

API client (`frontend/src/api/`): `fetch` with `credentials: "same-origin"`, auto `X-CSRF-Token`, typed responses mirroring §4, `EventSource` for SSE with reconnect + `Last-Event-ID`.

## 7. Demo / offline mode

`python3 -m om.api seed-demo --data <dir>` creates org **Meridian Capital Partners** (owner `owner@meridian.example` / password from `ACRETIA_DEMO_PASSWORD`, default `demo-password-123` for local only), a member and a viewer, deals "Project Nile — ElSewedy Electric" and "Project Atlas — Apple Inc.", demo documents (synthetic PDFs generated with `om/pdfwrite.py`, EN + AR text where possible), and the offline company-facts fixture. All agent runs in demo mode use `ACRETIA_LLM_MODE=replay` and fixtures; nothing touches the network.

## 8. Gate spec — `scripts/verify_product.py` (written by a different worker from the implementers)

Exits 0 only if all of these pass; prints one PASS/FAIL line per check:

1. Full offline suite green (`python3 -m unittest discover -s tests -q`).
2. Ledger: every package in `frontend/package.json` (deps + devDeps) has a ledger row (match on package name inside the repo column); no GPL/AGPL/SSPL/BUSL licence in `frontend/package-lock.json` packages (scan `license` fields of all installed packages under `frontend/node_modules` when present).
3. No provider SDK imports in `om/api/` (AST: `anthropic`, `openai`, `google.generativeai`, `cohere`, `mistralai`).
4. `frontend` builds (`npm ci && npm run build`, skipped with a reason if `npm` is absent) and `frontend/dist/index.html` has no inline `<script>` bodies, no inline `style=` attributes, no `http(s)://` script/style/font URLs.
5. Secret scan of `frontend/dist` and `frontend/src`: no strings matching `sk-[A-Za-z0-9]{20,}`, `AKIA[0-9A-Z]{16}`, `-----BEGIN`, `xox[bap]-`, `ghp_`, `ACRETIA_SECRET_KEY` values.
6. Server boots on a free port with a temp data dir in demo mode; `/api/v1/healthz` ok; every response carries the §2.2(6) headers.
7. Auth adversarial: wrong password 401; 11th failure 429; cookie flags HttpOnly + SameSite=Strict; session token not present in any JSON body; logout invalidates the cookie; a forged cookie → 401.
8. CSRF adversarial: POST without `X-CSRF-Token` → 403; with wrong token → 403; with cross `Origin: https://evil.example` → 403; with correct token and Origin → 2xx.
9. Tenancy adversarial: two orgs; for every route with an id param, cross-org access → 404, never 200/403; listing endpoints never include the other org's ids (exhaustive over the route table exported at `om.api.server.all_routes()`).
10. RBAC: viewer gets 403 on every mutating route; member gets 403 on owner routes; cannot demote the last owner (409 with hint).
11. Audit chain: after the run, `/audit/verify` ok; tampering one row in the DB (direct SQL) makes verify fail at that seq.
12. Jobs: a `comps`/`dcf` run in replay mode streams `plan → step* → deliverable → status:done`; SSE resume with `Last-Event-ID` replays no duplicates; killing and restarting the server mid-job resumes from the first unfinished step; cost events are monotonic and match the ledger total for the job.
13. Library: a deliverable has ≥ 2 versions after an edit; diff non-empty; undo restores byte-identical bytes (sha256).
14. Model view: recompute after changing an assumption changes dependent cells, values match `om.formula` evaluating the saved workbook, and checks (BS balances, cash ties) stay green.
15. Email-in: with a maildir mailbox fixture, `poll-mail` turns an allowed sender's email into a job; a non-member sender is rejected and audited; no SMTP/socket send happens (monkeypatched `smtplib`, `socket.create_connection` asserted unused for send).
16. Playwright journeys P-J1…P-J8 pass (`cd e2e && npx playwright test --trace off`), skipped with a reason only if browsers are absent. Each journey saves screenshots to `e2e/artifacts/<journey>/` (gitignored) for the persona gate.
17. Accessibility: axe-free static checks in Playwright — every page has `lang`, one `h1`, labelled inputs, focus visible, colour tokens contrast ≥ 4.5:1 (computed from the token file); Arabic run: `dir=rtl` and no element with physical `left/right` margins in computed styles of the shell.

## 9. Journey scripts (e2e) — acceptance per PLAN P-J1…P-J8

- **P-J1 Ask**: log in → `⌘K` → "Spread trading comps for Apple vs peers and add a football field" → plan visible with steps, cost and elapsed time → steps stream → deliverable appears in the deal library → open it. Also: email-in variant via maildir fixture produces a run with `source=email`. Coverage (D-032): every one of the 14 catalogue tasks is started once from the command bar (by prompt) and once from the agent library, and each reaches `done` or fails with a hint naming the missing engine stage; the run view shows per-step time/cost and the time-saved estimate.
- **P-J2 Deal workspace**: create deal → upload a zip with ≥ 50 PDFs (fixture generator; 2 Arabic) → documents index with progress → open Grid → add a question column → cost estimate shown → cells fill → gaps/risks panel → click a cell → PDF opens at page with the bbox highlighted.
- **P-J3 Model**: "3-statement + DCF for Apple" → model view → change WACC → dependent cells and valuation update live → audit overlay shows blue/black/green and check status → download xlsx → new version in library.
- **P-J4 Deck**: "Profile deck from this model" → ghost deck appears → approve (edit one title first) → slides render with validator badges → comment "make slide 2 a waterfall" → new version → diff shows the change → undo.
- **P-J5 Earnings**: trigger roll-forward on a deal with a model → model and deck re-versioned → diff shown → notification in the bell.
- **P-J6 Trust**: click a sourced number in the model view, a grid cell and a deck source line → split-pane PDF with the highlight, page number, as-of date and source link.
- **P-J7 Firm setup**: owner uploads a template + a sample deck, sets the Adjusted EBITDA and Net Debt definitions, invites a viewer, adds a connector, configures the mailbox (send disabled) → viewer logs in and can't mutate anything; a new deal carries the firm definitions.
- **P-J8 Agent library**: pick the built-in "Comps" agent → run → save a custom agent (prompt chain) shared to the org → a member of the org sees it and runs it → run history lists both runs.

## 10. Persona gate inputs

`e2e/artifacts/**.png` (light, dark and Arabic RTL screenshots of every journey's key screens) plus the produced xlsx/pptx. Three Haiku personas (PLAN §6) score; the PE principal must answer "would pay $10K+/seat" = yes. Scores and blockers are recorded in `docs/product/persona-gate.md`.

## 11. Measurement harness (D-032; owned by session F)

`eval/tsb/` and `eval/reliability/`. Replay mode in CI; live runs on the user's Mac (D-021). Nothing here may claim a human-validated number.

- `eval/tsb/baselines.py`: parses `docs/time-saved-baselines.md` (on main since 37faf7a; its §2 table has columns Task | Baseline range | Best source available | Confidence, with free-text ranges such as "2–3 hrs", "~90 min", "15 min–2 hrs", "20–30 hrs (at ~0.4–0.6 hr per doc)"). It maps each row to the task_ids by an explicit name table (3-statement → `three_statement`, DCF → `dcf`, LBO (full) → `lbo`, Merger → `merger`, Trading comps refresh → `comps`, Precedent transactions → `precedents`, Data-room first-pass review → `vdr_review`, Earnings model update → `earnings_update`, IC memo → `ic_memo`; the "no credible figure" row → `profile`, `pitchbook_section`, `teaser`, `buyer_list`, `earnings_recap`). It takes the first range in a cell as the primary (strong-analyst) range, normalises it to minutes, and sets `mid` to the geometric mean of low and high. It returns `{task_id: {t_h_low, t_h_mid, t_h_high, confidence, source, raw}}`. Tasks with no credible figure report `baseline: own timing study needed` and no number; a number is never invented. A parse failure is an error, never a silent default. §1 competitor claims are parsed into `competitor_claims[]` (who, claim, type `[vendor]|[customer]|[independent]`, source) and printed beside each task's result, labelled with their type.
- **Fixed benchmark row: WSP Apple 3-statement** (the doc's §1 [independent] Wall Street Prep task, same prompt). It runs the `three_statement` agent on Apple and reports wall time, the deterministic grade (`om.modelcheck`/`validate_xlsx`) and a circularity check (interest circularity modelled and converging = pass). The independent bar is shown beside it: tools took 15–60 min and scored 2.5–5.9/10 against analysts at 6.4–9.4; every tool scored 0 on circularity.
- **Method (baselines doc §3).** `T_a` is instrumented (job wall time + review and rework). Speed, error rate and client-ready rate are reported **separately**: client-ready = deterministic gates pass, persona ≥ 8.5, no blocking issue. Persona grading is blind: personas get the deliverable without the tool name or timing. `eval/tsb/pilot.md` holds the paired-timing pilot protocol for 3–5 analysts: the same task, human vs Acretia+review, counterbalanced order, blind rubric. Until the pilot runs, every row is labelled `estimate`.
- `eval/tsb/edit_minutes.csv`: minutes-per-edit table by edit class (typo/label, number fix, formula fix, chart change, slide restructure, missing section, sourcing fix, formatting), each with a cited source or marked `[INFERENCE]` with the reasoning; the review/fix estimate is Σ(persona "edits needed" × minutes).
- `eval/tsb/run.py`: for each of the 14 tasks × n briefs (n ≥ 10; briefs in `eval/tsb/briefs.yaml`, US + IFRS + MENA), runs the job through `om.api.jobs` in-process, records `T_a = wall + review_fix`, and writes `eval/tsb/report.md` + `eval/tsb/results.csv`: per task median, IQR, n, `1 − T_a/T_h` (low/mid/high), and the status column `estimate | human-validated`. Persona edit lists come from replayed persona outputs in CI.
- `eval/reliability/run.py`: every journey's agent across ≥ 100 varied companies/briefs (`eval/reliability/corpus.yaml`): success rate (target ≥ 97%), silent-wrong-number count (target 0: every number in every deliverable is either tied to a citation/xbrl concept or carries a flag; checked by walking the manifest/citations), determinism (two runs, byte-identical numbers), resume-after-failure rate (inject a failure mid-job, resume, compare with a clean run), p95 latency, cost per deliverable → `eval/reliability/report.md`.
- `scripts/verify_product.py` check 18: both harnesses run in replay mode on a reduced set (14 tasks × 2 briefs; 20 reliability briefs) and produce reports with the required columns; silent wrong numbers = 0 and determinism = 100% on that set.

## 12. Test hooks (`data-testid`) — shared by implementers and the e2e gate writer

Stable kebab-case ids; e2e tests select only by these, by role or by accessible name. Every list item adds `data-id="<resource id>"`.

- Shell: `app-shell`, `sidebar`, `nav-home`, `nav-deals`, `nav-library`, `nav-agents`, `nav-notifications`, `nav-settings`, `org-switcher`, `user-menu`, `locale-toggle`, `theme-toggle`, `notif-bell`, `notif-count`, `notif-drawer`, `notif-item`, `shortcut-sheet`, `toast`.
- Login: `login-email`, `login-password`, `login-submit`, `login-error`.
- Agent home: `ask-input`, `ask-submit`, `source-toggle-<deal|filings|firm|web>`, `deal-chip`, `starter-task` (with `data-task=<task_id>`), `skill-picker`, `skill-chip`, `recent-runs`, `run-row`.
- Command palette: `cmdk`, `cmdk-input`, `cmdk-item`.
- Run view: `run-view`, `run-status` (text = status), `run-cancel`, `run-resume`, `run-step` (with `data-status`), `run-cost`, `run-tokens`, `run-elapsed`, `run-time-saved`, `approval-card` (with `data-kind`), `approval-approve`, `ghost-title-input`, `source-chip` (with `data-token`), `citation-popover`, `download-sources`, `deliverable-link` (with `data-kind`), `feedback-up`, `feedback-down`.
- Deals: `deals-table`, `deal-row`, `new-deal`, `new-deal-name`, `new-deal-submit`, `deal-tab-<overview|documents|grid|models|decks|library|activity>`, `breadcrumbs`.
- Documents: `upload-dropzone`, `upload-input`, `upload-progress`, `doc-row` (with `data-status`), `doc-open`.
- Library: `library-table`, `deliverable-row`, `versions-drawer`, `version-row`, `version-download`, `version-diff`, `diff-view`, `undo-button`, `restore-button`.
- Agents: `agents-search`, `agent-card` (with `data-agent=<task_id or id>`), `agent-run`, `agent-pin`, `agent-enabled-toggle`, `new-agent`, `agent-name`, `agent-prompts`, `agent-shared`, `agent-save`.
- Settings: `members-table`, `invite-button`, `invite-email`, `invite-role`, `invite-submit`, `invite-link`, `role-select`, `audit-table`, `audit-verify`, `audit-export`, `definitions-form`, `definition-<key>`, `template-upload`, `connector-add`, `mailbox-form`, `mailbox-send-enabled`.
- PDF inspector: `pdf-viewer`, `pdf-page` (with `data-page`), `bbox-highlight`, `inspector-panel`, `inspector-page`, `inspector-asof`, `inspector-source-link`, `inspector-quote`.
- Grid: `grid`, `grid-cell` (with `data-row`, `data-col`, `data-state`), `grid-add-column`, `column-prompt`, `column-submit`, `grid-estimate`, `grid-wizard`, `column-manager`, `workflow-view`, `grid-export`, `grid-chat-input`, `risks-panel`.
- Model view: `model-view`, `sheet-tab`, `model-cell` (with `data-ref="Sheet!A1"`, `data-class=input|calc|link`), `assumption-input` (with `data-ref`), `recompute-status`, `audit-overlay-toggle`, `check-badge` (with `data-status`), `model-download`, `model-save`.
- Deck view: `deck-view`, `slide-thumb`, `slide-canvas`, `validator-badge` (with `data-status`), `slide-source-line`, `comment-pin`, `comment-input`, `comment-submit`, `apply-comments`, `version-compare`, `deck-download`.
