# Paired-timing pilot protocol (3 to 5 analysts)

Purpose: replace the replay estimates in `eval/tsb/report.md` with measured numbers. Until this pilot runs, every TSB row stays `status = estimate` and nothing is quoted externally (baselines doc section 3, SPEC section 11, D-032).

Status: **protocol only; not yet run.** No pilot data exists in this repository.

## 1. Design

- **Participants:** 3 to 5 analysts or associates (IB, PE or corporate finance), at least one second-year or above, recruited by the user. Record seniority (years of experience) for each; the baseline claim must state it.
- **Tasks, pre-registered before any timing:** one task per participant-session from the 14 catalogue tasks, chosen from the user's own live work where possible so that documents are real. At least the five tasks with no credible published baseline (company profile, pitchbook page, teaser, buyer list, earnings recap) are included, because their `T_h` can come only from this pilot.
- **Paired and counterbalanced:** every participant does comparable tasks in two arms.
  - Arm H (human): the analyst's normal tools, no Acretia.
  - Arm A (assisted): Acretia run, then the analyst reviews and fixes until the deliverable is client-ready by their own standard.
  - Order is counterbalanced (half start with H, half with A) and the two tasks within a pair are matched by type and size (same task type, different company, similar filing length). Use a Latin-square assignment, written down in advance.
  - A washout of at least one working day separates the two arms for the same participant.
- **Sample size is small by design.** Report medians and the full list of per-participant values, never a mean with a confidence interval that implies more than n = 3 to 5 supports.

## 2. What is measured

Per session, with a screen timer or a time-tracking sheet started by the participant:

| Field | Definition |
|---|---|
| `t_h` | Wall-clock minutes, arm H, from receiving the brief to the participant declaring the deliverable client-ready. |
| `t_a_wall` | Minutes from submitting the brief in Acretia to the deliverable event (from job telemetry, not self-reported). |
| `t_a_review` | Minutes the analyst spends reviewing and fixing after delivery, until client-ready. This is the term the replay run only estimates. |
| `t_a` | `t_a_wall + t_a_review`. This is the number compared with `t_h`. Generation time without rework is never reported as time saved. |
| `edits` | A list of every edit made in arm A, each tagged with an edit class from `eval/tsb/edit_minutes.csv` and its real minutes. This replaces the `[INFERENCE]` minutes table. |
| `errors_found` | Count of wrong numbers, broken formulas or unsourced figures found by the analyst in the Acretia output (error rate, reported separately from speed). |
| `client_ready_first_pass` | Yes or no: would the reviewer send the first-pass output to a client or IC without edits? Reported separately from "good first draft". |
| `blocking_issues` | Free text, one line each. |

Also record: task definition, company, document set and page count, the model and mode used (live, model name), and the Acretia build commit.

## 3. Blind rubric grading

- Each deliverable (both arms) is stripped of tool names, file metadata, timing and arm labels, given random IDs, and graded by one senior reviewer (VP level or above) who did not take part in the session.
- The reviewer scores the same rubric for both arms: the per-deliverable criteria in `docs/buyer-research.md` section 5, plus an overall 0 to 10 score and a binary "client-ready" call.
- The reviewer is told only that deliverables come from analysts, not which arm. If the reviewer can identify the arm from the content (for example canned text), record it and exclude that item from the blind comparison, noting the exclusion.
- Persona grading (Haiku) runs on the same stripped files in parallel; its score is reported next to the human score, never in place of it.

## 4. Analysis and what may be claimed

- Per task: median `t_h`, median `t_a`, and `1 - t_a / t_h`, with n and the individual points shown. Error rate and client-ready rate are separate columns.
- A figure becomes `human-validated` only when (a) the protocol above was followed, (b) the rubric grade of arm A is not below arm H on the client-ready call, and (c) the saving is at or above the published competitor claim for that task type (baselines doc section 1), compared like for like (hours per task versus hours per week are not interchangeable).
- Per-user weekly figure (target of at least 10 hrs per week): measured only from a one-week diary study of the same participants on their own work after the paired sessions, reported as the median of the participants, with the diary method stated. It is not extrapolated from task savings.
- Anything below those bars is published as measured and labelled `estimate` or `not met`. The pilot results go in `eval/tsb/report.md` under a separate heading, and the replay estimates stay visible beside them.

## 5. Consent and data handling

- **Informed consent** in writing before any session: purpose (benchmarking a product, not assessing the individual), what is recorded (timings, edit lists, the deliverables), who sees it, and the right to stop at any time and have their data deleted.
- **No personal performance scoring.** Results are reported per task and per seniority band; participants are identified by code (P1 to P5). The key linking codes to names is held by the user only, outside the repository.
- **Client and employer data.** Do not use documents the participant is not permitted to share. Use public filings, the user's own documents, or synthetic data. If a participant's employer forbids use of a third-party tool on real deal material, run the pilot on public companies only.
- **Where data goes.** Live runs send data only to the model endpoint named in `DECISIONS.md` through the adapter (D-021), with the user's key on the user's machine. Raw timings and edit lists are stored locally under a path outside the repository (the report contains only aggregates and anonymised per-session rows). No keys, names or client documents are committed.
- **Retention.** Raw session files are deleted 90 days after the final report unless the participant agrees otherwise in writing.
- **Compensation and independence.** If participants are paid, payment is fixed and not tied to the result. The person who grades must not be the person who built the product.

## 6. Failure modes the protocol guards against

- Self-selection of easy tasks: tasks are pre-registered and drawn from live work, not chosen after seeing output.
- Learning effects: counterbalanced order and matched, different companies.
- Hidden rework: `t_a_review` is timed, not estimated.
- Metric slippage: one definition of `t_a` and of client-ready, written before the first session.
