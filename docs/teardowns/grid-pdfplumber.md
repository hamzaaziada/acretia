# Teardown: pdfplumber (lightweight baseline)

repo: https://github.com/jsvine/pdfplumber
commit: 4c64b92d5caccd71c645e98e0fabb0c4dba7ff45
licence: MIT (`LICENSE.txt`, "Copyright (c) 2015, Jeremy Singer-Vine"); depends on pdfminer.six (MIT) and pypdfium2
ran: yes (PyPI `pdfplumber` 0.11.10 in a venv; `extract_text_lines()` and `find_tables()` with default settings)

Inputs and method are identical to `grid-docling.md`. Items are text lines plus whole tables from `find_tables()`; table rows come from `table.extract()`.

## Results

| doc | pages | token completeness (worst page) | char completeness | items scored | contain >= 0.9 | precision >= 0.9 | mean IoU | spot-check 20 | table row probe | time |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL 10-K | 15 | 1.000 (0.999) | 1.000 | 488 | 0.998 | 0.998 | 0.888 | 20/20 | 0.989 (92) | 1.1 s |
| NTRS 10-K | 15 | 0.997 (0.981) | 1.000 | 793 | 0.985 | 0.984 | 0.902 | 20/20 | 0.000 (124) | 1.7 s |
| LFVN presentation | 20 | 0.969 (0.876) | 1.000 | 483 | 0.942 | 0.888 | 0.730 | 19/20 | n/a (1 probe) | 1.3 s |
| NTRS synthetic scan | 3 | 0.000 (no text layer) | 0.000 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

- [OBSERVATION] Text completeness is 0.997 to 1.000 on born-digital text because it reads the same text layer as `pdftotext`; it is roughly 50 to 100 times faster than docling (1 to 2 s versus 63 to 105 s).
- [OBSERVATION] Tables work only when the page has ruling lines. On the HTML-to-PDF 10-K, `find_tables()` found 17 tables and 0.989 of numeric rows (91 of 92 probes) kept label and numbers in one row. On the NTRS PDF it found 2 tables on 15 pages and 0 of 124 probes were recovered as rows; the statements there are whitespace-aligned.
- [OBSERVATION] LFVN boxes: contain 0.942 but IoU 0.730 and only 0.178 of line boxes at IoU >= 0.8, because slide text lines merge across columns.
- [OBSERVATION] Image-only PDFs yield nothing (0 words), so there is no scanned-page path.
- [OBSERVATION] No reading order, no layout labels (heading/footnote/caption), no cell-level structure beyond rule-detected grids.
- [INFERENCE] pdfplumber, or poppler's `pdftotext -bbox-layout` (same words, same speed), is the right fast path and completeness oracle for S5.1: use it to decide per page whether a heavier parser is needed (no text layer, or table-rich page without rulings) and to produce tight word boxes for quote highlighting inside docling's loose cell boxes.
- [UNKNOWN] Behaviour with text-based tables using `vertical_strategy="text"` tuned per document; I ran defaults only.

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt as the lightweight fast path and completeness oracle (MIT, pure Python, 1 to 2 s per document), not as the primary table parser: it recovers statement rows only when rulings exist and does nothing for scans.
