# Teardown: docling (PDF parser for S5.1)

repo: https://github.com/docling-project/docling
commit: e16c4b71a7b7d9154ffca164accad2581aed5c9f
licence: MIT (`LICENSE`, "Copyright The Docling Contributors"). Model weights are separate: the ledger records `docling-layout-heron` Apache-2.0 and `docling-models` CDLA-Permissive-2.0 + Apache-2.0 (HF model cards).
ran: yes (PyPI `docling` 2.150.1, which equals the clone's `pyproject.toml` version; docling-core 2.107.1, docling-parse 7.26.0, torch 2.15.0+cpu; default `DocumentConverter()` pipeline with no tuning; 4 vCPU, 15 GB, no GPU)

## Test inputs (all real public documents, page-limited to keep CPU time sane)

- `aapl_10k_html2pdf.pdf` (15 pp): Apple FY2026 10-K filed 2026-11-03 (accession 0000320193-26-000026, EDGAR HTML) converted with `soffice --headless --convert-to pdf` (84 pages), pages 40-54 (MD&A tables, income statement, balance sheet, cash flow). 4,397 text-layer words.
- `ntrs_10k_pdf.pdf` (15 pp): a real PDF on EDGAR, Northern Trust FY2025 annual report/10-K (accession 0000073124-26-000024, `ntrsannualreport_2025.pdf`, 184 pp), pages 97-111 (consolidated statements and notes). 9,814 words.
- `lfvn_investor_pres.pdf` (20 pp): LifeVantage October 2023 investor presentation filed as a DEFA14A exhibit on EDGAR (accession 0000849146-23-000184, 86 pp), pages 1-20: slide layout, charts, 57 pictures. 3,843 words. (A company IR-site PDF was not used; the two IR URLs I tried returned 404.)
- `ntrs_scan3p.pdf` (3 pp, synthetic): NTRS pages 3-5 of the 15-page selection rasterised at 150 dpi, grayscale, JPEG q60, re-wrapped as an image-only PDF (0 words in `pdftotext`). The original text layer is the reference. This is a clean synthetic scan, not a photocopy.

## Method

- Reference: `pdftotext -bbox-layout` (poppler 24.02.0) words with boxes per page. Scripts are in the session scratchpad (`scripts/evalgrid.py`, `charcomp.py`, `tableprobe.py`).
- Completeness: per page, multiset overlap of normalised word tokens (lower-case, punctuation-only tokens dropped) between pdftotext and everything docling returned for that page (text items plus table cells). Reported overall and worst page. Also a lenient character-level version (multiset of alphanumerics).
- Bbox fidelity: for each returned item with text (text blocks, table boxes, table cells), the words whose area is at least 50 percent inside the box. `contain` = share of the item's tokens that are inside its box; `precision` = share of in-box reference words that belong to the item (no foreign text); `iou` = box vs union box of matched words. Reported: share of items with contain >= 0.9. A random 20-item spot check (seed 7) per document.
- Table structure probe: from `pdftotext -layout`, rows shaped `label  num  num ...` (>= 2 numbers) become probes; a probe passes if one parsed table row holds the label and all the numbers.

## Results

| doc | pages | token completeness (worst page) | char completeness | items scored | contain >= 0.9 | precision >= 0.9 | mean IoU | spot-check 20 | table row probe |
|---|---|---|---|---|---|---|---|---|---|
| AAPL 10-K (HTML to PDF) | 15 | 0.997 (0.982) | 1.000 | 712 | 0.994 | 1.000 | 0.953 | 20/20 | 1.000 (92 probes) |
| NTRS 10-K (EDGAR PDF) | 15 | 0.999 (0.995) | 1.000 | 933 | 0.998 | 0.997 | 0.754 | 20/20 | 0.992 (124) |
| LFVN investor presentation | 20 | 0.975 (0.882) | 0.9999 | 464 | 0.873 | 0.864 | 0.683 | 18/20 | n/a (1 probe) |
| NTRS synthetic scan (OCR) | 3 | 0.952 (0.921) | not run | 317 | 0.940 | not recorded | 0.764 | 19/20 | 0.932 (44) |

Timings (CPU): AAPL 86.3 s for 15 pp (97.0 s on the first run), NTRS 63.5 s for 15 pp, LFVN 104.5 s for 20 pp, scan 56.1 s for 3 pp (about 19 s per page with OCR). Models downloaded once from Hugging Face on first run.

- [OBSERVATION] Out-of-page boxes: 0 of 712 / 933 / 464 / 317 items had a box outside the page; boxes come back in BOTTOMLEFT origin and were flipped with `bbox.to_top_left_origin(page_height)` using each page's own size (`scripts/run_docling.py`).
- [OBSERVATION] Born-digital completeness is effectively full: character-level 1.000 on AAPL and NTRS, 0.9999 on LFVN. Token-level 0.997 and 0.999. The AAPL worst page (0.982) is page numbering and running header tokens.
- [OBSERVATION] LFVN token completeness (0.975, worst page 18 at 0.882) is mostly a reference artefact: the presentation's text layer is broken into fragments ("fro m", "vari o us", "presentati ns"), so pdftotext words never match whole words; docling outputs the joined word. Character-level completeness is 0.9999, so nothing was dropped. A 100 percent token score is therefore not the right gate on slide decks; use a character-level or fuzzy gate as well.
- [OBSERVATION] Table structure: on the two statement documents docling's table rows kept every number with its label for 92 of 92 probes (AAPL) and 123 of 124 (NTRS). On the scan, 41 of 44 probes survived OCR with the right row.
- [OBSERVATION] Cell boxes are loose grid cells: NTRS cell mean IoU is low (table-level IoU 0.975; overall mean 0.754) while containment is 0.998. Boxes contain the text but are bigger than the text. For highlighting a cited number this is acceptable; for exact quote boxes derive the tight box from the pdftotext words inside the cell.
- [OBSERVATION] LFVN spot check: 2 of 20 items failed. "New Compensation Plan - Status" (page 18, box [1402,523,1631,543]) has zero text-layer words inside the box, and a chart caption (page 9, contain 0.43, precision 0.25) merges two lines; the first is likely text inside a picture that docling OCR'd while the PDF has no text-layer words there [INFERENCE].
- [OBSERVATION] Picture handling: 57 pictures were detected on LFVN; chart data inside pictures is not extracted as numbers by default (docling produced 7 tables on 20 pages). Not measured: whether slide charts' numbers are recoverable.
- [OBSERVATION] Output is a typed `DoclingDocument` with per-item `prov` (page number and bbox), tables as cell lists with row/column offsets and cell boxes, plus Markdown/JSON exports; this maps directly onto the planned `{answer, exact_quote, page, bbox, confidence}` Matrix cell (S5.2). Rows rebuilt from `start_row_offset_idx`/`start_col_offset_idx` in the runner.
- [INFERENCE] Speed is the cost: 4 to 6 s per born-digital page on 4 CPUs (about 19 s per scanned page), roughly 9 to 12 times slower than Marker's fast mode and about 3 times slower than MinerU basic in this session. A 300-page CIM would take 20 to 30 minutes on this machine; S5.2 needs page-level caching and a pdfplumber/pdftotext fast path for born-digital pages.
- [INFERENCE] Because the reference words and docling both read the same text layer on born-digital pages, 0.997 to 0.999 measures dropped layout regions, not recognition accuracy. Accuracy on genuinely scanned input is measured only by the synthetic scan row, which is cleaner than a real scanned exhibit.
- [UNKNOWN] A real scanned exhibit from EDGAR: none of the PDFs I found on EDGAR was image-only, so scanned-OCR performance on real photocopies, skew, stamps and handwriting is untested.
- [UNKNOWN] Memory ceiling and behaviour on a 200+ page file in one call; I limited each run to 15 to 20 pages.

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt as the default S5.1 parser (MIT code, permissive weights per the ledger). It was the only candidate with whole-page completeness above 0.997 and numeric table rows intact on both statement documents, and it returns page-and-bbox provenance natively. Wrap it behind a completeness gate that compares against pdftotext words per page (character-level for slides) and keep a pdfplumber/pdftotext fast path for pages where the text layer is clean and tables have rules.
