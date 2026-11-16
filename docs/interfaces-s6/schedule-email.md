# Schedules, monitoring and email (S6.4, parity 25-29)

Code: `src/harness/research/schedule.py`, `src/harness/research/email_io.py`. Tests: `tests/test_research_schedule.py`.

## Schedules
`ScheduleStore(path=":memory:")`: `create(org_id, user_id, request, cadence, *, cron|at|weekday, hour, minute, tz, deliver, now)`,
`get/list/update/disable/delete` (all scoped by `org_id`), `due(now)`, `dispatch_due(now, submit=jobs.submit, tracker=None)`.
Cadences: `daily` (hour, minute), `weekly` (weekday 0=Mon..6=Sun), `cron` (5 fields: ranges, lists, steps, month/day names,
vixie dom/dow OR rule), `once` (`at` ISO; naive values use `tz`). `deliver = {"email": [...], "library": bool}`.
Times are stored as UTC `...Z`. DST: a nonexistent local time fires once right after the gap; an ambiguous time fires at its
first occurrence only. Missed slots collapse into one run. `UNIQUE(schedule_id, slot)` makes a repeated tick a no-op.
`dispatch_due` strips `monitor` from the request before `jobs.submit` and sets `org_id`/`user_id` from the schedule.
The caller emails the finished result with `render_summary` to `deliver.email` (and saves it to the Library if `deliver.library`).

## Monitoring (item 28)
Request carries `monitor: {"compare_to": "last_run", "alert_on": ["new_filing", "figure_change>5%"]}`.
After a job finishes call `store.monitor_check(org_id, schedule_id, result)`: the first run sets the baseline; later runs return
alert items `{kind: figure_change|new_filing, ..., prev_citation, cur_citation}` and replace the baseline.
`diff_results(prev, cur, monitor)` matches figures on (label, period), ignores uncited figures, alerts when the change is strictly
greater than X%. New filings come from `result["filings"]` (`accession`, `url`, `filed`, `form`) or accession numbers found in
figure citations. Pass `alerts=` to `render_summary` to include them.

## Outbound email
`render_summary(result, *, deck_url=None, files=[], alerts=None) -> (subject, text, html)`: only figures with a citation that has a
source (url, or doc_id + page) and `as_of` are shown; rejected or uncitable items are counted, never shown. HTML is escaped; only
http(s) deck URLs are linked. `build_message(...)`, `send(message, transport, tracker=None, job_id=None)`.
`SMTPTransport` reads `ACRETIA_SMTP_HOST/PORT/USER`, `ACRETIA_SMTP_SECURITY` (`ssl` | `starttls`; default ssl on 465 else starttls),
password from `ACRETIA_SMTP_PASSWORD` or a `password_provider` callable. Disabled without a host; plaintext is refused (no STARTTLS
offer means no login and no send). The password never appears in `repr` or logs.

## Inbound email
`parse_request_email(eml_bytes, *, org_allowlist, project_resolver, authserv_ids=None) -> InboundRequest` or raises `InboundRejected`.
- Sender: one `From`; a display-name address that differs from the real address is rejected; the sender must match an
  `org_allowlist` entry (`{org: ["a@x.com", "@x.com"]}`). `Authentication-Results`: any `dkim/spf=fail|softfail|permerror`, or a DKIM
  `header.d` that does not align with the From domain, rejects. No results means `auth="unauthenticated"` (allowlist still required).
  Pass `authserv_ids` to trust only your own MTA's header.
- Body is data. Only the subject (else the first non-quoted body line) is used; quotes, signatures and reply history are cut. The text is
  sent as `question` inside `<email_request>...</email_request>`; embedded fence tags are removed. Nothing in the body adds recipients,
  commands or files. Replies go only to `InboundRequest.user`.
- Kinds: `deck:` subject prefix or `/deck` first line -> `deck`; `save:` / `/save`, or attachments with no text -> `save_material`;
  otherwise `research`.
- Attachments: each goes through `connectors.unpack.unpack` (zip-bomb, traversal, nesting limits); extracted files are copied into the
  directory returned by `project_resolver(org_id, user, hint)` (`hint` = `[Project]` tag in the subject, or None), with sanitised names
  and no overwrite. Failures land in `rejected_attachments`; the request still parses.

### Deck hand-off to session B's engine
`handle_inbound(inbound, submit=jobs.submit, deck_handoff=callable, tracker=...)`: `research` -> `submit(inbound.request)`;
`deck` -> `deck_handoff(inbound)` (must return a job id; the engine reads `inbound.request["question"]` as fenced data, `inbound.org_id`,
`inbound.user`, `inbound.attachments` as source files, builds the deck, saves it to the Library, and the result mail is sent to `inbound.user`).

## Latency (items 26, 27)
`LatencyTracker(path)`: `received(token)` -> `submitted(token, job_id)` -> `emailed(job_id)`; `report(job_id)` gives
`receive_to_submit_s`, `submit_to_email_s`, `total_s`, `target_s` (600 research, 900 deck) and `met_target`. `handle_inbound`,
`send(..., tracker, job_id)` and `dispatch_due(..., tracker)` record the stamps (scheduled runs count from the slot time).
