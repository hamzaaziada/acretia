# S8 gate spec (Boss, D-027)

`scripts/verify_s8.py` is written by a Sonnet worker who has not seen the implementers' tests. It prints one line per
assertion (`PASS`/`FAIL`/`SKIP <reason>`), writes `docs/s8/gate-report.md`, and exits 0 only when every non-skipped
assertion passes and no assertion in the "never skippable" set is skipped. It makes no network calls and no model
calls (sockets are monkeypatched to raise for the whole run). It may call `tesseract`, `pdftoppm` and `pdftotext`.

Never skippable: G1, G2, G3, G4, G5 (tesseract is required: install it, don't skip), G6, G7, G9, G10.

## Shared contract the gate relies on

- `om.intl.types`: `Figure`, `ExtractedStatements`, `IntlItem(om.statements.Item)`, `IntlStatements(om.statements.Statements)`.
- `om.intl.extract.extract(pdf_path_or_bytes, *, company=None, hints=None) -> ExtractedStatements`.
- `om.intl.tieout.check(ex) -> TieReport`; `om.intl.tieout.release(ex, report=None, *, strict=True) -> IntlStatements`,
  raising `om.intl.tieout.ReleaseBlocked` when a required tie fails or a required figure is in review.
- `om.intl.review.queue(ex, report) -> list[ReviewItem]` (figure, reasons, page, bbox_norm, `crop_png` bytes or path).
- Fixtures: `tests/fixtures/intl/manifest.json` lists every synthetic fixture with its generator, sha256, kind
  (native/scanned, en/ar/bi), and the ground-truth figures (`key`, `period_end`, `value` in reporting-currency millions).

## Assertions

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

**G9 Evals** (recompute from committed per-figure results; don't trust summary numbers)
1. XBRL gold (`evals/intl/xbrl_gold/results.jsonl`): ≥ 20 filers, ≥ 5 countries, ≥ 300 figures; accuracy of released
   figures ≥ 99%; coverage ≥ 90%; every record has page, bbox and confidence.
2. MENA (`evals/intl/mena/results.jsonl`): ≥ 10 EGX and ≥ 5 Tadawul non-bank companies, ≥ 5 reports scanned or Arabic
   only, ≥ 300 hand-verified figures; accuracy of released figures ≥ 98%; coverage ≥ 70%; tie-out pass rate and Arabic
   numeral OCR character accuracy reported; verifier ≠ extractor recorded per record.
3. Standards QA (`evals/intl/standards_qa/`): 50 questions; every answer cites a KB entry and a standard reference;
   score ≥ 90% on the deterministic key-point rubric.
4. `scorecard.csv` has S8 rows matching the recomputed numbers (±0.001); any model-dependent row says `not run live`.

**G10 Hygiene**
1. No third-party report is committed: every PDF/PNG under `tests/fixtures/intl*` and `evals/intl/**` is listed in a
   manifest with a generator of ours, and regenerating with `scripts/make_intl_fixtures.py --check` reproduces the
   ground truth.
2. Secret scan over S8 files: no API keys, tokens or passwords.
