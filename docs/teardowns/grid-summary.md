# Summary: PDF grid parsers for S5.1 (docling vs Marker vs MinerU vs pdfplumber)

repo: n/a (summary of grid-docling.md, grid-marker.md, grid-mineru.md, grid-pdfplumber.md)
commit: n/a (see each file; docling e16c4b71a7b7d9154ffca164accad2581aed5c9f, marker d580b63874d9c8510fa54494975b9df1e8b527d0, MinerU b4efa4b2b76ebb012c476b79bdfc6f18a95aacd6, pdfplumber 4c64b92d5caccd71c645e98e0fabb0c4dba7ff45)
licence: n/a (docling MIT; Marker code Apache-2.0 with Open RAIL-M weights; MinerU Apache-2.0 plus extra commercial and attribution terms; pdfplumber MIT)
ran: yes (all four ran on CPU, 4 vCPU, 15 GB, on the same four inputs; no GPU)

## Inputs

Real public documents, page-limited: Apple FY2026 10-K (EDGAR HTML converted to PDF with LibreOffice, 15 pp), Northern Trust FY2025 annual report/10-K (a real PDF on EDGAR, 15 of 184 pp), LifeVantage October 2023 investor presentation (EDGAR DEFA14A PDF, 20 of 86 pp), and a synthetic scan (NTRS 3 pp rasterised at 150 dpi, image-only). Reference text and word boxes: `pdftotext -bbox-layout` 24.02.0. Definitions of the metrics are in `grid-docling.md`.

## Comparison (token completeness overall, worst page in brackets; contain = share of returned boxes where at least 90 percent of the item's tokens sit inside the box)

| | docling | Marker (fast) | MinerU (basic, ONNX) | pdfplumber |
|---|---|---|---|---|
| licence (code / weights) | MIT / Apache-2.0 and CDLA-Permissive (per ledger) | Apache-2.0 / Open RAIL-M modified (revenue and funding limit) | Apache-2.0 + commercial threshold + attribution / `MinerU-4_models_onnx` has no licence tag | MIT / none |
| AAPL 10-K completeness | 0.997 (0.982) | 0.965 (0.869) | 0.994 (0.862) | 1.000 (0.999) |
| NTRS 10-K completeness | 0.999 (0.995) | 0.972 (0.904) | 0.990 (0.938) | 0.997 (0.981) |
| LFVN deck completeness | 0.975 (0.882); char 0.9999 | 0.830 (0.403); char 0.872 | 0.903 (0.417); char 0.970 | 0.969 (0.876); char 1.000 |
| scan completeness | 0.952 (0.921) | 0.965 (0.950) | 0.982 (0.954) | 0.000 (no text layer) |
| bbox contain >= 0.9: AAPL / NTRS / LFVN / scan | 0.994 / 0.998 / 0.873 / 0.940 | 1.000 / 0.991 / 0.842 / 0.944 | 1.000 / 0.994 / 0.643 / 1.000 | 0.998 / 0.985 / 0.942 / n/a |
| mean IoU AAPL / NTRS / LFVN | 0.953 / 0.754 / 0.683 | 0.837 / 0.924 / 0.742 | 0.832 / 0.872 / 0.634 | 0.888 / 0.902 / 0.730 |
| spot-check 20 passing (AAPL / NTRS / LFVN) | 20 / 20 / 18 | 20 / 20 / 14 | 20 / 20 / 13 | 20 / 20 / 19 |
| numeric table row probe AAPL / NTRS | 1.000 / 0.992 | 0.946 / 0.960 | 0.793 / 0.556 | 0.989 / 0.000 |
| seconds for 15 pp (born-digital) | 63 to 97 | 6 to 10 (model load adds 4 s) | 20 to 29 | 1 to 2 |
| native bbox form | points, bottom-left origin (convertible) | points, top-left | normalised 0 to 1 | points, top-left |
| output structure | typed document tree, table cells with row/col spans and cell boxes | block tree, tables as HTML | typed blocks, tables as HTML | text lines, rule-based grids |

- [OBSERVATION] Ranking on completeness plus numeric table structure for the statement documents: docling first (0.997 to 0.999, 92/92 and 123/124 numeric rows intact), MinerU and pdfplumber next on completeness but with weak table rows, Marker last (drops whole paragraphs on AAPL page 12 and entire regions on LFVN pages 9 and 10).
- [OBSERVATION] Ranking on speed: pdfplumber (1 to 2 s), Marker (6 to 10 s), MinerU (20 to 29 s), docling (63 to 105 s). Scan speed: Marker about 6 s, MinerU about 19 s, docling 56 s for 3 pages.
- [OBSERVATION] On slides, token completeness is a poor metric: the LifeVantage text layer is fragmented ("fro m", "vari o us"), so character-level completeness (docling 0.9999, pdfplumber 1.000, MinerU 0.970, Marker 0.872) says more than token-level. Docling and pdfplumber lose nothing; Marker and MinerU lose real content on the pages with picture-heavy layouts.
- [OBSERVATION] Licence assumptions in PLAN section 0 item 1 are outdated: at the pinned commits Marker's code is Apache-2.0 (not GPL) and MinerU's licence is Apache-2.0 plus two extra terms (not AGPL). The ledger rows already say so. The constraints that remain are weight licences (Marker's Open RAIL-M revenue/funding limit; unknown licence for MinerU's ONNX weights).
- [INFERENCE] The selection is robust to our biases: docling wins on the dimension S5 cares most about (a figure with its label in one row, with page and bbox for the evidence bundle), and the margin is largest on the statement documents where citing the right number matters.
- [UNKNOWN] Real scanned exhibits, skewed or photographed pages, non-English or RTL documents, and files above 20 pages per call: none tested.
- [UNKNOWN] Whether docling's accuracy holds on 200-page CIMs with embedded chart images; chart-number extraction was not measured for any parser.

## Recommendation for S5.1

1. Default parser: docling (MIT, pinned version, models pinned by HF revision as in the ledger), wrapped per page so one slow or failing page does not block a document.
2. Page router and completeness gate (deterministic, before any LLM): run `pdftotext -bbox-layout` on every page. For each docling page compute token completeness; accept if at least 0.97 token or at least 0.995 character completeness (the character fallback covers fragmented slide text); otherwise mark the page `incomplete` and re-run it with docling's force-OCR option or send it to the optional isolated service. Pages with no text layer go straight to OCR. Observed for docling: per-page token completeness was at least 0.982 on both statement documents; on the deck 6 of 20 pages fell below the 0.97 token gate but none below the 0.995 character gate (worst page 0.9989).
3. Tight boxes for evidence: keep docling's block and cell provenance for navigation, but when the evidence bundle stores a quote's `bbox` take the union of the pdftotext words inside the matched cell, because docling's cell boxes are loose (NTRS cell IoU 0.61 versus containment 0.998). Store `bbox_norm` as page fractions in [0, 1] (S5 gate: 100 percent of cells in range; observed 0 out-of-page boxes in every parser).
4. Fast path: for born-digital pages whose pdftotext words reproduce the cell text, a pdfplumber or pdftotext pass is enough and 50 to 100 times cheaper; use docling only for pages with tables or layout. Cache by (file hash, page).
5. Optional services only: Marker (speed, but gate its output; weights licence review needed) and MinerU (best scan containment; weak on statement rows; never `--remote`, telemetry off). Neither is imported into core. Ship neither until the weights licences are cleared.
6. Gate additions for `verify_s5.py`: completeness per page, numeric-row probe on a fixed statement fixture (target at least 0.98 where docling scored 0.992 to 1.000), and a synthetic-scan fixture (docling 0.952 token completeness; require at least 0.93).

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt docling as the S5.1 default, pdfplumber (or `pdftotext -bbox-layout`) as the fast path and completeness oracle, and keep Marker and MinerU as optional isolated services behind the same gate.
