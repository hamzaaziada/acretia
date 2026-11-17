# 10-K QA gold set (S5.4a)

100 cells = 10 real SEC 10-K filings x 10 diligence questions. It scores the document grid
(rows = documents, columns = questions): every answer must carry an exact quote, a page and a bbox.

## Source and licence
- Filings: the latest Form 10-K of AAPL, MSFT, KO, JNJ, PG, WMT, COST, HD, MCD, LOW, fetched from SEC EDGAR
  (`data.sec.gov/submissions`, `www.sec.gov/Archives`). SEC filings are US public records.
- NKE and PEP were first choices but LibreOffice hung (> 240 s) converting their HTML; MCD and LOW replaced them (D-S5-xx).
- The PDFs are rendered from the filing HTML by LibreOffice and trimmed to at most 25 pages that carry the answers
  (cover, employees, MD&A, income statement, balance sheet, debt, auditor's report). Raw HTML and XBRL facts are
  cached in `data/raw/tenk/` and are never committed. `manifest.json` records ticker, CIK, accession, source URL,
  fiscal year end, sha256, soffice version and the trimmed-page to original-page map.

## Files
- `pdfs/<TICKER>.pdf`, `manifest.json`: the corpus (about 1.6 MB).
- `questions.json`: q01 revenue, q02 net income, q03 diluted EPS, q04 total assets, q05 cash, q06 employees,
  q07 fiscal year end, q08 auditor, q09 state of incorporation, q10 non-current long-term debt.
- `gold.jsonl`: one cell per line: `cell_id, ticker, pdf, question_id, question, type, gold_answer, unit, gold_quote,
  gold_page` (1-based, in the trimmed PDF), `orig_page`, `xbrl_check`, optional `answer_note`.
- `build_gold.py`: the label spec (line regex, value) and generator.

## How gold was labelled
A human-style pass read each page as `om.pdfdoc` extracts it (the geometry the grid uses) and recorded the value.
`gold_quote` is copied verbatim from that extraction (consecutive lines joined by a space), so it is locatable on
`gold_page` by construction. Numbers are plain floats in the stated unit (USD millions, USD per share, or a count);
dates are ISO; text is the exact entity name. Judgement calls are in `answer_note` (for example WMT revenue is total
revenues; KO, PG and WMT net income is the amount attributable to the company; MCD "Over 150,000" and LOW full-time
associates only).

## Cross-check
q01-q05 and q10 (60 cells) are checked against SEC XBRL company facts for the same accession and fiscal year end;
`xbrl_check = {concept, value, match}`. All 60 match. q06-q09 have no XBRL check (`null`).

## Rebuild
```
python3 scripts/build_tenk_corpus.py          # fetch (SEC UA header, under 5 req/s), convert, trim, write manifest
python3 evals/tenk/build_gold.py              # regenerate gold.jsonl and the XBRL checks
python3 scripts/build_tenk_corpus.py --verify # print each PDF with its sha256 and compare to the manifest
python3 -m unittest tests.test_s5_evals -q
```
Rebuilding can change PDF bytes (so sha256 and gold pages); rerun `build_gold.py` after any rebuild.
