# S5.1 teardown: docling vs pdfdoc backend on a real 10-K

Input: Apple 10-K (accession 0000320193-26-000026, `aapl-20260926.htm`, 1.65 MB) fetched from SEC EDGAR, converted with
`soffice --headless --convert-to pdf` (84 pages, 2.7 MB). Files kept under `/tmp/claude-0/s51/` (not committed).
Benchmarked an 8-page subset (source pages 1, 2, 3, 20, 44, 45, 46, 47) on CPU, docling 2.150.1 (layout-heron weights cached).
Completeness = token recall of `pdftotext -layout` text in the block text (threshold 0.97).

## Completeness before recovery (per subset page)
| page (src) | pdfdoc | docling | docling after recovery |
|---|---|---|---|
| 1 (1) | 1.000 | 0.161 | 1.000 |
| 2 (2) | 1.000 | 0.000 | 1.000 |
| 3 (3) | 1.000 | 0.000 | 1.000 |
| 4 (20) | 1.000 | 0.997 | 0.997 |
| 5-8 (44-47) | 1.000 | 1.000 | 1.000 |

- [OBSERVATION] Pages 1-3 of the LibreOffice rendering contain the iXBRL hidden header as one long unbroken token run (`false2026FY0000320193P1Y...`). Docling emitted a single page-sized text block (bbox ~[0.10,0.03,0.95,0.95]) and lost 84-100% of the raw tokens; the guard fired on all three pages, added 47/56/56 `recovered` line blocks and logged `page N: docling dropped X% of raw tokens; recovered K lines`.
- [OBSERVATION] On the real statement pages (income statement, balance sheet, cash flows) docling reached 1.000 with no recovery, producing `table` blocks whose text includes all cell values (e.g. `Total net sales 478,834 416,161 391,035`).
- [OBSERVATION] pdfdoc is trivially 1.000 against pdftotext because both read the same text layer; the metric only discriminates layout backends that rebuild text.
- [INFERENCE] Silent token loss is a real failure mode of layout models on dense or odd pages, so the guard must stay on for every layout backend, not only OCR.

## Timing
- [OBSERVATION] pdfdoc (pdfplumber + pdftotext): 0.8 s for 8 pages. Docling: 2.9 s converter load when weights are cached (first process load ~15 s cold), 52 s for the 8 pages (~6.5 s/page, CPU only).
- [INFERENCE] A full 84-page 10-K would take roughly 9 minutes on docling here, so the grid should cache `ParsedDoc.to_dict()` by `doc_id` and run docling off the request path.
- [UNKNOWN] GPU speed-up and behaviour with OCR on scanned filings were not measured.

## Table handling
- [OBSERVATION] Docling labelled the statement tables as `table` items with `data.table_cells`; our mapper joins cell texts in item order (no row/column structure kept in `Block`). pdfdoc marks a block `table` only when every line has 3+ wide gaps, so it misses ruled tables with few columns.
- [UNKNOWN] Cell-level bboxes are not exposed in `Block`; exact citation of a single number relies on `locate()` over pdfdoc word geometry, not the table block.

## Bbox fidelity
- [OBSERVATION] Docling BOTTOMLEFT point boxes converted with the page size (612x792) land on pdfdoc word boxes: for 29 non-recovered blocks the union of pdfdoc words whose centres fall inside the block differs from the docling bbox by a median of 0.0012 (normalised, max edge) and p90 0.0235.
- [INFERENCE] The p90 tail is docling padding/merging of neighbouring lines, so block boxes are fine for layout display but exact citations must use `locate()` word unions (hash is computed on those).
- [OBSERVATION] A synthetic PDF test confirms docling's block centre sits within 0.02 of the pdfdoc word centre.

## Decisions supported
- Default `auto` = docling if importable else pdfdoc; docling errors fall back to pdfdoc with a warning.
- Marker/MinerU are reachable only through `om/parse_services.py` (HTTP, no import); [UNKNOWN] their output quality on filings is not tested here (no service available offline).
