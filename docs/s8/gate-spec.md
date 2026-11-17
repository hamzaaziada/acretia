# S8 gate spec (Boss, D-027)

`scripts/verify_s8.py` is written by a Sonnet worker who has not seen the implementers' tests. It prints one line per
assertion (`PASS`/`FAIL`/`SKIP <reason>`), writes `docs/s8/gate-report.md`, and exits 0 only when every non-skipped
assertion passes and no assertion in the "never skippable" set is skipped. It makes no network calls and no model
calls (sockets are monkeypatched to raise for the whole run). It may call `tesseract`, `pdftoppm` and `pdftotext`.

Never skippable: G0, G1, G2, G3, G4, G5 (tesseract is required: install it, don't skip), G6, G7, G9, G10.

Order (D-030): G0 (anchors) must pass before the wider MENA and XBRL-gold results count.

## Shared contract the gate relies on

- `om.intl.types`: `Figure`, `ExtractedStatements`, `IntlItem(om.statements.Item)`, `IntlStatements(om.statements.Statements)`.
- `om.intl.extract.extract(pdf_path_or_bytes, *, company=None, hints=None) -> ExtractedStatements`.
- `om.intl.tieout.check(ex) -> TieReport`; `om.intl.tieout.release(ex, report=None, *, strict=True) -> IntlStatements`,
  raising `om.intl.tieout.ReleaseBlocked` when a required tie fails or a required figure is in review.
- `om.intl.review.queue(ex, report) -> list[ReviewItem]` (figure, reasons, page, bbox_norm, `crop_png` bytes or path).
- Fixtures: `tests/fixtures/intl/manifest.json` lists every synthetic fixture with its generator, sha256, kind
  (native/scanned, en/ar/bi), and the ground-truth figures (`key`, `period_end`, `value` in reporting-currency millions).

## Assertions

**G0 Anchor companies (S8.0, D-030)**: SWDY, EAST, TMGH, 2280 (Almarai), 4190 (Jarir), 2010 (SABIC), EMAAR,
ADNOCDIST, ALDAR. Data in `evals/intl/anchors/<ticker>/`.
1. `sources.json` lists ≥ 2 audited annual financial statements and ≥ 1 latest quarterly earnings release or investor
   presentation, each with URL, sha256, retrieval date, and `committed: false` unless the publisher's terms allow it
   (then the terms URL is recorded). Where a company publishes no release or presentation (e.g. EAST), a `none_published` record listing the hosts checked satisfies the release requirement; consolidated FS fall back to separate FS only when the company publishes no consolidated set, recorded as such.
2. `figures.jsonl`: full IS, BS and CF for both annual reports (every printed line, not only the model lines), each
   record with page, bbox, confidence and key (or `null` with the printed label); for both years, BS balances,
   CF ties to the change in cash, and IS/CF net income agree, either in `check()` or with a review item explaining why.
3. `release_recon.jsonl`: every headline figure in the earnings release (revenue, EBITDA or operating profit, net
   profit, and any other figure it states with a statements counterpart) is matched to a statements figure with both
   citations, and every difference ≠ 0 has a category (`adjusted_vs_reported`, `segment_vs_group`, `restatement`,
   `rounding`, `period_mismatch`, `definition`) plus a one-sentence explanation. Unexplained differences = 0.
4. `om/intl/companies/<ticker>.md` exists and covers: framework, layout quirks, non-standard lines, zakat or tax,
   IFRS 16, FX/devaluation, related parties, units, fiscal year, each with ≥ 1 page citation.
5. `qa.jsonl`: 10 analyst questions with answers; every answer has ≥ 1 citation (doc sha256 + page + bbox or a
   figure id) and every number in an answer appears in `figures.jsonl` or the release.

**G1 Licences and isolation**
1. Every third-party tool or package S8 uses (tesseract, its `ara`/`eng` traineddata, PyYAML, anything else imported in
   `om/intl/**` or `src/harness/connectors/intl_*.py` that is not stdlib or already in the ledger) has a ledger row with
   a 40-hex commit, a licence and a decision.
2. No module under `om/intl/` or `src/harness/connectors/intl_*.py` imports a GPL/AGPL package, a provider SDK
   (`anthropic`, `openai`, `google.generativeai`, …), or `fitz`/PyMuPDF (AST scan).
3. tesseract is only ever run as a subprocess (no `pytesseract`/`tesserocr` import).
4. Modules under `om/intl/` other than `om/intl/sources/**` import no network module (`urllib.request`, `http.client`,
   `socket`, `requests`, `httpx`).

**G2 Standards knowledge base**
1. Loads ≥ 7 frameworks: IFRS, EAS, SOCPA-IFRS, GCC/UAE IFRS, UK FRS 102, Ind AS, US GAAP.
2. Each framework has a statement-layout entry (P&L by function/nature, current/non-current ordering, OCI) and
   required line items.
3. Topics present with ≥ 1 difference entry each: leases (IFRS 16 / ASC 842 / EAS 49), revenue, inventory (LIFO),
   development costs, revaluation, impairment reversal, borrowing costs, associates/JVs, IAS 29, IAS 21 devaluation,
   zakat vs income tax, end-of-service benefits, government grants, EAS ↔ IFRS mapping (incl. EAS 47/48/49).
4. Every difference entry has ≥ 1 citation (standard id + section/paragraph reference + public URL) and an
   `adjustment` recipe id; every recipe id resolves to a callable in `om.intl.adjust`.
5. No-copy guard: no text field contains a quoted passage (text inside quotation marks) longer than 25 words, and every
   entry carries `authored: acretia` (own words).

**G3 Concepts and bilingual labels**
1. Every key in `om.statements.LINES` that model3 requires (revenue, ebit, pretax, net_income, assets, current_assets,
   current_liabilities, cfo, cfi, cff) plus cogs, cash, equity_total, liabilities, capex, da has ≥ 1 English and ≥ 1
   Arabic label and ≥ 1 `ifrs-full` concept.
2. Arabic normalisation invariance: hamza/alef forms (أ إ آ ا), taa marbuta/haa, alef maqsura/yaa, diacritics,
   tatweel, and Eastern Arabic or Persian digits in a label all map to the same key as the plain form.
3. Adversarial: "صافي الربح" and "صافي الخسارة" map to the same key with opposite `sign_hint`; "إجمالي الأصول المتداولة"
   maps to current_assets, not assets; "Profit before zakat and income tax" maps to pretax; a label for a component
   never maps to a total; an unknown label returns `None` or confidence < 0.5.

**G4 Number and unit parsing** (table-driven, ≥ 40 cases), including: `(1,234)`→-1234; `١٬٢٣٤٫٥`→1234.5;
`۱۲۳`→123; `(١٢٣)`→-123; `123-`→-123; `1.234.567` and `1,234,567`→1234567; `1.234,5` (comma decimal)→1234.5;
`-`, `—`, `–`, `nil`, `—` → nil; note-reference columns are not values; years in headers are not values; units:
`بالألف جنيه مصري`/`EGP '000`/`EGP thousands`→(EGP, 1e3); `SAR million`/`بالمليون ريال سعودي`→(SAR, 1e6);
`AED'000`, `US$ thousands`, `ر.س`, `ج.م`; fiscal year-end detection for 30 June, 31 March and 31 December headers in
English and Arabic (`٣٠ يونيو ٢٠٢٤`).

**G5 Extraction on synthetic fixtures (OCR required)**
1. Fixture set covers: native EN, native AR (RTL table), scanned EN, scanned AR (noise + ≤ 1.5° skew), bilingual
   two-column (EN left, AR right), non-December year end, EGP '000 and SAR million units, by-nature P&L, IFRS 16 lines,
   zakat line.
2. For every fixture: every ground-truth figure is either extracted with the exact value (|diff| ≤ 0.5 unit of the
   printed scale, sign correct) or is in the review queue; **zero** released figures are wrong.
3. Coverage: ≥ 95% of ground-truth figures are released (not in review) on native fixtures, ≥ 85% on scanned ones.
4. Every figure (released or review) has `page` within the document, `bbox_norm` within [0, 1] with x0 < x1, y0 < y1,
   `confidence` in [0, 1], and a 64-hex `sha256_span_hash`; on native fixtures the text inside the bbox (pdftotext
   `-bbox`) normalises to the figure's raw token.
5. Arabic numeral OCR character accuracy on the scanned AR fixture ≥ 99%.

**G6 Tie-out and review gate**
1. On each clean fixture `check()` passes: IS subtotals, BS balances, CF ties to change in cash, IS and CF net income
   agree, and prior-year comparatives match when two reports of the same company are given.
2. Mutation: for each fixture, perturb one figure in a tie (≥ 10 mutations total, including a digit transposition and
   a sign flip). Each must make the tie fail, put the involved figures in the review queue, and make
   `release(strict=True)` raise `ReleaseBlocked`.
3. A figure whose confidence is below the threshold and that no passing tie corroborates goes to review with reasons.
4. Each review item carries page, bbox and a PNG crop (valid PNG signature, non-empty) of the highlighted region.
5. Failed ties never reach a model: for the mutated fixtures, no code path in `om.intl` returns an `om.statements.Statements`
   without passing through `release` (AST: `IntlStatements(` is constructed only in `om/intl/tieout.py`), and
   `om.model3.build` is never given a blocked document (released object's `release_report.passed` is True).

**G7 Model support**
1. `om.model3.build` runs unchanged on a released `IntlStatements` built from a fixture (EGP, June year end), and the
   workbook's balance and cash checks are zero.
2. By-nature P&L: EBIT is computed, `basis_flags["ebit"] == "computed_by_nature"`, and the value equals revenue minus
   the listed operating expenses by nature.
3. IFRS 16 toggle: pre-IFRS 16 EBITDA = EBITDA − (right-of-use depreciation + lease interest)… numerically checked on a
   fixture; lease-adjusted net debt includes lease liabilities only when the toggle says so.
4. Zakat: shown separately, treated as a tax-like charge in the effective-rate calculation, flagged.
5. FX: balance-sheet lines at the period-end rate, flows at the period-average rate; the EGP devaluation of March 2024
   and the November 2016 float raise a `devaluation` flag for periods spanning them (rates from a committed fixture).
6. Calendarisation: a June-year-end company calendarised to December matches hand-computed weights (6/12 + 6/12) on a
   known example; March year end uses 3/12 + 9/12.

**G8 Connectors** (offline; replay fixtures only)
1. EGX, Tadawul, ESEF (filings.xbrl.org) and Companies House connectors register and list/fetch from fixtures.
2. robots.txt is honoured: a disallowed path is refused before any request.
3. Rate limit: consecutive requests to one host are ≥ the configured interval apart (fake clock).
4. A `User-Agent` that identifies Acretia is sent; Companies House reads its key only from the environment and errors
   cleanly when absent; no key literal in the repo.
5. Connectors store facts and links; nothing writes report bytes outside `data/raw/`.
6. (e954406) Companies House API + bulk iXBRL accounts (parsed with the same iXBRL reader as ESEF), KvK open dataset,
   INPI RNE, Brønnøysund (marked fragile), Ireland CRO and GLEIF LEI each have a connector with an offline fixture; GLEIF
   resolves one entity across ≥ 2 registries in a fixture. German/Spanish accounts route to `om.intl.extract`.
7. `docs/s8/source-terms.md` has one row per source: terms URL, licence, date reviewed, rate limit, what is stored.
   Personal data is minimised: officer/PSC records keep name, role and dates only (no addresses or birth dates).
8. Paid sources (Pappers, North Data, Bigdata.com) and partnerships (Third Bridge, Arbolus) exist only as interfaces
   that raise `NotConfigured`; no credentials, no purchase.

**G9 Evals** (recompute from committed per-figure results; don't trust summary numbers)
1. XBRL gold (`evals/intl/xbrl_gold/results.jsonl`): ≥ 20 filers, ≥ 5 countries, ≥ 300 figures; accuracy of released
   figures ≥ 99%; coverage ≥ 90%; every record has page, bbox and confidence.
2. MENA (`evals/intl/mena/results.jsonl`): ≥ 10 EGX and ≥ 5 Tadawul non-bank companies, ≥ 5 reports scanned or Arabic
   only, ≥ 300 hand-verified figures; accuracy of released figures ≥ 98%; coverage ≥ 70%; tie-out pass rate and Arabic
   numeral OCR character accuracy reported; verifier ≠ extractor recorded per record.
3. Standards QA (`evals/intl/standards_qa/`): 50 coverage questions plus held-out sets (`heldout.jsonl` = development, `heldout_v2.jsonl` = record, D-S8-06); the ≥ 90% bar applies to the coverage set and to held-out v2; every answer cites a KB entry and a standard reference;
   score ≥ 90% on the deterministic key-point rubric.
4. `scorecard.csv` has S8 rows matching the recomputed numbers (±0.001); any model-dependent row says `not run live`.

**G10 Hygiene**
1. No third-party report is committed: every PDF/PNG under `tests/fixtures/intl*` and `evals/intl/**` is listed in a
   manifest with a generator of ours, and regenerating with `scripts/make_intl_fixtures.py --check` reproduces the
   ground truth.
2. Secret scan over S8 files: no API keys, tokens or passwords.

**G11 North-star (D-032)**
1. Telemetry: every extraction run writes a record to `evals/intl/telemetry.jsonl` with `doc_sha256`, `pages`,
   `scanned`, `language`, `wall_seconds`, per-step seconds (`parse`, `ocr`, `extract`, `tieout`, `review`),
   `tokens` (0 when no model is called), `cost_usd` (0.0 when no model is called), `engine` and `flags`, using the
   step field names of docs/product/SPEC.md "Telemetry". p95 wall time ≤ 10 min per annual-report FS (≤ 120 pages)
   on this container's CPU; the median is reported.
2. Reliability is reported as three separate numbers per eval set (anchors, MENA, XBRL gold) and in `scorecard.csv`:
   tie-out pass rate (documents whose hard ties all pass), figure accuracy of released figures against gold, and
   flag rate (figures sent to review ÷ all figures). Zero silent wrong numbers: no released figure differs from gold
   beyond rounding without a review flag. The gate fails on any silent wrong number in any set.
3. Review time: each document's record has `review_minutes = Σ flags × minutes_per_flag(reason)` from
   `evals/intl/review_minutes.csv` (reason classes: low_ocr_conf, tie_fail, unmapped_label, comparative_mismatch,
   unit_ambiguous; each row cites a source or is marked `[INFERENCE]` with the reasoning), so `eval/tsb/` can add it
   to review-and-fix time.
4. Hand-off: `python3 open_multiples.py intl-model <pdf> --out <xlsx>` (or the equivalent `om.intl.pipeline.model_from_report`)
   turns Almarai's latest annual FS into a tied three-statement workbook through `release()` and an unchanged
   `om.model3.build`, with balance and cash checks = 0 and every Filings-sheet figure's comment carrying page and bbox.
   Runs when the anchor PDFs are cached in `data/raw/intl/`; otherwise uses the committed synthetic SAR fixture and
   prints SKIP for the live part with the reason.

**G12 Parity citation items (docs/parity-spec.md 15–17, 20)**
1. `om.intl.pipeline.locate(figure_or_citation) -> {"doc_sha256", "page", "bbox_norm", "png"}` returns the
   highlighted page crop in ≤ 2 s (p95 over 50 random figures, scanned Arabic included; timed in the gate).
2. Every Filings-sheet cell of an intl model carries a comment with doc, page and bbox, plus a link to the source URL
   when there is one (item 20).
3. Trace test: the specialist reviewer picks 10 random figures per anchor from `docs/samples/s8/<ticker>/` and traces
   each to the source page; the median time is < 2 min, recorded in `docs/s8/specialist-review.md` (item 17).
4. Clean machine: `python3 -m venv` + `pip install -r requirements.txt` + the S8 tests + `verify_s8.py` pass, with
   tesseract/poppler installed as documented system packages.

**Graders (D-033): no ✅ until all three pass**
1. This deterministic gate.
2. A specialist reviewer: a Sonnet "IFRS/EAS accountant" who is not an author, has the pdf/xlsx skills loaded, and
   grades all 9 anchors against the source reports. It grades figure accuracy, classification, the "how to read"
   notes, the analyst Q&A, and the model workbook. The score must be ≥ 8.5, recorded in `docs/s8/specialist-review.md`.
3. Four Haiku personas (IB analyst, EM, PE principal, MENA PE/IB associate), each ≥ 8.5, in `docs/s8/personas.md`.
