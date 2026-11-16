# S1 specialist review: licence compliance and technical due diligence

Reviewer: independent specialist (OSS licence compliance / tech diligence). Scope: `license-and-repo-ledger.csv`, `docs/ledger-notes.md`, `docs/teardowns/*.md`, `docs/buyer-research.md`, `scripts/verify_s1.py`. Date 2026-11-16. Read-only review; nothing else modified.

## Verdict: PASS WITH FIXES   Score: 7.5/10

The ledger is accurate against primary sources and handles the hard cases well. It records Marker and MinerU as non-copyleft with restricted weights or terms, which corrects PLAN v2. Teardowns are unusually well evidenced. Four things stop a clean pass:
- the gate has a false-pass bug;
- the gate's self-test fails (9/10);
- an undeclared provider SDK sits in `requirements.txt`;
- there is no NOTICE / third-party notices artefact, although the ledger repeatedly says one must ship.

## Findings

| id | sev | file:line | evidence | fix |
|---|---|---|---|---|
| F1 | High | `requirements.txt:1`; `scripts/verify_s1.py:144-153` | `anthropic>=1.0` is declared but has no ledger row (ledger has only `anthropics/skills` and `anthropics/financial-services`). The gate passes anyway because it checks `key not in " ".join(repo names)` as a substring, and "anthropic" is a substring of "anthropics/...". Same flaw lets any short name false-pass (e.g. `lxml` inside another name). It is also a provider SDK dependency, which CLAUDE.md allows only in `src/harness/adapter.py`; whether it is imported elsewhere is the S2 CI grep's job, but the dependency itself is unledgered. | Add a ledger row (`anthropics/anthropic-sdk-python`, pinned commit, MIT, decision). Make the gate match exact `owner/name` or the repo basename, not a substring. Add a negative test for it. |
| F2 | High | `scripts/verify_s1.py` self-test | Running the gate gives `FAIL self-test: scanners flag module-level fitz and unguarded uno ... AssertionError: fitz not flagged by import check: []`, so the stage gate is 9/10 and cannot be signed off. It means the isolation scanner may not catch a module-level `import fitz` (AGPL), the control the gate is meant to prove. | Fix the scanner or the self-test fixture so a module-level `fitz` / `pymupdf` import is flagged. The gate must be 10/10 before PROGRESS.md marks S1 done. |
| F3 | High | repo root; `ledger-notes.md` | There is no `NOTICE`, `THIRD_PARTY_NOTICES` or equivalent. The ledger says "ship LICENSE and NOTICE" for pdf.js, Tika, tesseract, pypdfium2/PDFium, formulon and Lucide, and requires the crawl4ai attribution line and the MinerU online-service attribution. No file collects those obligations and nothing in the gate checks one exists. | Create `THIRD_PARTY_NOTICES.md` generated from the ledger (every `adopt` and bundled row), with the Lucide ISC + Feather MIT text and the PDFium notices. Add a gate check. Add a deploy-time checklist for the attribution clauses. |
| F4 | Med | ledger `psycopg/psycopg` row | The row says psycopg is "listed in requirements-extras.txt only". `requirements-extras.txt` has 4 lines (pdfplumber, duckdb, docling, formulon) and no psycopg. The statement is false. The code imports it dynamically (`om/storage.py`), so the ledger claim and the packaging are out of sync. | Correct the row or add the extra. For LGPL compliance, document that psycopg must stay a replaceable pip install (no PyInstaller one-file bundle or frozen image that blocks substitution), and ship the LGPL text and offer of source. |
| F5 | Med | ledger / ledger-notes | The ledger is missing the transitive and installed packages that reach a shipped docling image: rapidocr 3.10.0 and its model weights (installed here), opencv-python-headless (Apache-2.0 plus bundled third-party), numpy, pandas, scipy, shapely, xlsxwriter, `docling-ibm-models`, the EasyOCR family. Only docling, docling-parse, docling-core, torch and transformers are covered. Whether they are ledgered depends on how the "declared deps" rule is defined, but a buyer's SCA scan of the docling image will list them. The gate only checks declared and imported names. | Generate a transitive-closure SBOM (`pip-licenses` or CycloneDX) for the docling extra and the base install. Add a gate check that no installed distribution has a GPL/AGPL/SSPL/unknown licence without a ledger entry. |
| F6 | Med | ledger `docling-project/docling-models` | The pin `fc0f2d45...` differs from the current HF revision `2199320...` (checked via the HF API). The licence list (CDLA-Permissive-2.0 + Apache-2.0) is correct on HEAD. I did not confirm the card at the older revision. The weights are not vendored, but `docling` downloads whichever revision it hardcodes. | State in the notes that the pin is the revision docling's code requests (cite the file/line), or re-pin and re-read the card. |
| F7 | Med | `docs/buyer-research.md:33` (criterion 16) | "a $50m discrepancy between two slides is treated as a firing-grade error [8][24]". Source [8] (Prospect Rock) was fetched: it calls a mismatch "a rounding error, but unacceptable nonetheless" and says a Senior VP reacted dramatically. It says nothing about firing, and "$50m" is not tied to a consequence. This is an overstatement, and it feeds persona grading. | Reword to what [8] supports: number mismatches across pages are "unacceptable" and "signal you can't be trusted with more meaningful work". Drop "firing-grade". |
| F8 | Med | `docs/buyer-research.md` s.1b and s.5 (criteria 17, 18, 23; [15]) | [15] (Mergers & Inquisitions) supports consistent punctuation, footnotes and dates, and late senior changes ("v44"). It does not discuss sources. The page also quotes a reply that "banks care less about style than substance". Citing it for "source notes on every exhibit" and for "native charts" stretches it. (Criterion 23's native-object rationale is already marked [UNSOURCED].) | Split the criteria so each cites only what the source says, and add a caveat on the style-versus-substance comment. |
| F9 | Low | `docs/buyer-research.md:101` / [46][47] | The Rogo $3,300/seat figure is confirmed on Sacra. The AlphaSense $10-20K range on Allmind is itself attributed to Sacra and is "not an AlphaSense rate card"; the research marks it third-party, which is correct. The page also contains a "$10K+ implies an analyst-day per week" claim that is flagged [UNSOURCED]. | Nothing blocking. Cite the secondary-source chain explicitly. |
| F10 | Low | [35] American Banker | The article reports "rumblings of discontent" on tech websites, not its own finding. Research text says "Users report executives promising unrealistic efficiency gains", which is fair, but the phrase "rolling out too fast" is the article's headline claim, not data. | Mark it as anecdotal. |
| F11 | Low | `buyer-research.md` items [19], [40] | [19] (Acuity) and [40] (ITPro) are marked in the bibliography as snippet or headline only. They are disclosed, so this is acceptable. The gate shows 8 [UNSOURCED] markers; I confirmed the ones I saw are honest. The research admits WSO and Reddit were not retrievable, though PLAN S1.4 asked for them (see `buyer-research.md:159`). | Schedule the manual WSO/Reddit pass before persona calibration, as the document itself recommends. |
| F12 | Low | ledger `openpyxl`, `swak/pptx-mcp`, `mckinsey-pptx` | `openpyxl` has no commit pin and its sdist LICENCE was not read, yet it is `adopt` and installed. The two "not found" rows are `skip` and pass the gate by an explicit n/a justification. | Fetch the openpyxl sdist LICENCE and record its hash. |
| F13 | Info | `ledger` / PLAN s.0.1 | `anthropics/skills`: PLAN says source-available, but the ledger found Apache-2.0 per skill. The ledger keeps `borrow_ideas` with zero copying. This is the conservative and correct handling. | None. |

## Weight, dataset and obligation handling

- **FinanceBench (CC-BY-NC-4.0, confirmed via the HF API):** The ledger restricts it to local internal scoring, never shipped. That is consistent with PLAN S6.3. Caveat for diligence: published scorecards that quote FinanceBench results to prospects are commercial use of derived output. The ledger does not address this, so add a line to the evals decision that FinanceBench numbers may be reported only as an internal benchmark and not in sales material without Patronus's permission. Not a blocker for S1.
- **SpreadsheetBench (CC-BY-SA-4.0, confirmed in the README):** Handled as local-only, not redistributed. Share-alike would not reach Acretia code, but it would reach any derivative dataset. The ledger says do not vendor, which is correct.
- **Marker weights (modified OpenRAIL-M; README confirms free for research, personal use and startups under $5M funding/revenue):** Handled as `isolated_service`. Note: "isolated service" does not cure a commercial weights restriction. A paying customer deployment needs a Datalab licence or exclusion. The ledger says "teardown/benchmark only", which is right. Make sure Marker never reaches the default deploy.
- **MinerU (Apache-2.0 plus extra terms, confirmed at `LICENSE.md`: 100M MAU / USD 20M monthly revenue, online-service attribution, automatic termination):** Correctly described. The termination clause means an attribution lapse voids the licence, so it belongs on the F3 notices checklist.
- **docling weights:** layout-heron is Apache-2.0 (HF API). docling-models is CDLA-Permissive-2.0 + Apache-2.0 (HF API; see F6 for the revision caveat).
- **crawl4ai (attribution clause confirmed at the end of LICENSE):** Handled (`borrow_ideas`, line to be added if ever adopted).
- **LGPL:** python-bidi (COPYING.LESSER confirmed; installed, not imported) and psycopg (LGPL-3.0 confirmed; dynamic import in try/except, unmodified) are handled correctly. See F4 for the packaging condition.
- **MPL (D-S1-02, LibreOffice pyuno):** MPL-2.0 is file-level copyleft, so an in-process import of `uno` is fine provided no LibreOffice files are modified or vendored. The gate allow-lists exactly `om/recalc.py` and fails other imports. This is sound. `COPYING` also carries GPLv3 text for some components. The soffice binary is used only as a subprocess, so it is not a problem.
- **Redis / MinIO / PyMuPDF / poppler:** Correct, with isolation and a pin of Redis 7.2 or a fork. Poppler pdftotext as a subprocess is fine.

## Verified OK (primary sources re-fetched at the pinned commits)

Licence and decision confirmed for these 27 rows:
- datalab-to/marker (LICENSE, MODEL_LICENSE, README), opendatalab/MinerU (LICENSE.md, thresholds quoted);
- unclecode/crawl4ai (attribution tail), MeirKriheli/python-bidi (COPYING.LESSER), psycopg/psycopg (LGPL-3.0);
- docling (MIT), OpenBB (blanket Apache-2.0 header), libraz/formulon (Apache-2.0), RUCKBReasoning/SpreadsheetBench (README CC BY SA 4.0);
- patronus-ai/financebench (no LICENSE: 404; HF card cc-by-nc-4.0), minio/minio (AGPLv3), redis/redis (tri-licence statement), vals-ai/finance-agent (MIT);
- virattt/dexter (no LICENSE: 404), dgunning/edgartools (`LICENSE.txt` MIT), JerBouma/FinanceToolkit (`LICENSE.txt` MIT), PyMuPDF (AGPLv3), duckdb (MIT);
- tesseract (Apache-2.0), apache/tika (Apache-2.0), anthropics/skills (`skills/pptx/LICENSE.txt` Apache-2.0), anthropics/financial-services (Apache-2.0);
- the two docling HF model cards.

The decisions follow PLAN section 0.1 in every one of the 27: no copyleft row is `adopt`, and the source-available and unusual cases are `isolated_service` or `borrow_ideas`.

Other checks:
- **Teardown evidence.** 11 file:line `[OBSERVATION]` claims were re-fetched at the pinned commits and all hold:
  - dexter `agent.ts:128`, `:149`, `:282`; `scratchpad.ts:66`, `:97`, `:131`; `api.ts:4`, `:44`;
  - edgartools `pyproject.toml:80-86`, `:140-142`;
  - presenton `package.json:64` (recharts), `pptx_font_utils.py:1-15` (fontTools import);
  - Marker README lines 52-58 vendor benchmark numbers, correctly flagged as "vendor numbers, not reproduced";
  - PPTAgent `core.py:283`, `:211`.
  The teardowns also state methods and denominators for their measurements (docling completeness, bbox IoU, probe counts, timings, hardware), and mark vendor claims and synthetic inputs honestly. They label the synthetic scan as synthetic, mark scan performance on real documents as `[UNKNOWN]`, and downgrade a "likely" to `[INFERENCE]`. The gate reports 280 labelled findings with 200 observations, and I found no unlabelled findings in the files I read. Recommendations (docling as default parser with a pdftotext completeness gate; Marker as isolated and gated; formulon as a third engine, with the correct finding that the npm `formulon` is a different, Salesforce-formula package) follow from the evidence.
- **Not reproducible by me:** timing and completeness numbers (they need the session scratchpad scripts, which are not in the repo; the notes refer to `scripts/evalgrid.py` etc. in "the session scratchpad"). Recommend committing those scripts under `scripts/teardown/` so the observations are reproducible. This is a Low finding (F14).
- **Buyer research.** Ten citations were fetched and confirmed:
  - BeRI [24] (500 bankers, none client-ready, Handshake AI and McGill, 2026-04-26);
  - Hebbia survey [26] (about 71%, n=510, Centiment, 2026-04-28 to 05-09);
  - Wall Street Prep [2] (blue/black/green; expenses negative; no hardcodes in formulas; it does not mention parentheses, but criterion 6 does not cite it for that);
  - Sacra [46] ($3,300/seat); Allmind [47] (range attributed to Sacra, caveated);
  - American Banker [35] (2026-05-15);
  - M&I [15], partially (see F8); Prospect Rock [8], partially (see F7);
  - FE football field [21] (bars, 52-week range, share price line, DCF from WACC/g flex);
  - the Anthropic ic-memo raw file [30] (returns and sensitivity guidance).
  There were no dead links in the sample. Unsourced items are mostly marked honestly and matter little.

## Score rationale

7.5/10. The licence work itself is strong (primary-source verified, with the PLAN's wrong assumptions corrected and logged). The deductions come from the gate and the due-diligence artefacts: a substring false pass that hides an unledgered SDK, a failing self-test, no consolidated notices file, no transitive SBOM, and a few overstated or over-attributed claims in the buyer research. Fix F1-F3 and F7 to reach about 9.
