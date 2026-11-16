# Teardown: Marker (datalab-to/marker)

repo: https://github.com/datalab-to/marker
commit: d580b63874d9c8510fa54494975b9df1e8b527d0
licence: code Apache-2.0 (`LICENSE`); model weights under "AI Pubs Open RAIL-M (Modified)" (`MODEL_LICENSE`). README line 88: "free for research, personal use, and startups under $5M funding/revenue"; commercial use of the weights beyond that needs a paid licence from Datalab. The dependency `surya-ocr` (clone commit 253888005c21865f0ded5d50872727f2a3b307f1, version 0.24.0) is also Apache-2.0 code with the same OpenRAIL-M weights note.
ran: yes (PyPI `marker-pdf` 2.2.0 in a venv, CPU torch 2.15.0+cpu, default CPU mode which is `fast`; the clone HEAD is 2.2.1; same 4 vCPU box; models fetched automatically, 17 files)

Inputs and method are identical to `grid-docling.md` (AAPL HTML 10-K to PDF, NTRS EDGAR PDF, LifeVantage presentation, synthetic scan). Command: `marker_single <pdf> --output_dir <dir> --output_format json --disable_image_extraction`. Items are the leaf blocks of the JSON tree plus whole tables; boxes are PDF points in page space.

## Licence finding that changes the plan

- [OBSERVATION] PLAN section 0 item 1 lists Marker as GPL. At the pinned commit the code licence is Apache-2.0 (`LICENSE` first lines "Apache License Version 2.0"; the PyPI `METADATA` of marker-pdf 2.2.0 also says `License: Apache-2.0`), and the ledger row already records Apache-2.0 for code and Open RAIL-M for weights.
- [INFERENCE] The real constraint is the weights licence, not copyleft: an Acretia deployment above the revenue/funding threshold would need a commercial licence from Datalab. That is a commercial-terms risk, not an import-into-core prohibition, but the "isolated service only" rule in PLAN section 0 remains a sound posture until legal reviews `MODEL_LICENSE`.
- [UNKNOWN] Which weight sets the default `fast` mode uses (README says "~18 MB Indra ONNX weights") and their individual licence; the old `datalab-to/surya_layout` HF repo is tagged `cc-by-nc-sa-4.0` (HF API), so non-commercial terms may attach to some weights. The `MODEL_LICENSE` text is the governing document; I did not get a legal reading.

## Results

| doc | pages | token completeness (worst page) | char completeness | items scored | contain >= 0.9 | precision >= 0.9 | mean IoU | spot-check 20 | table row probe | wall time |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL 10-K | 15 | 0.965 (0.869) | 0.968 | 146 | 1.000 | 0.986 | 0.837 | 20/20 | 0.946 (92) | 9.9 s (Marker log); 13.9 s wall |
| NTRS 10-K | 15 | 0.972 (0.904) | 0.973 | 110 | 0.991 | 0.991 | 0.924 | 20/20 | 0.960 (124) | 6.1 s; 9.9 s wall |
| LFVN presentation | 20 | 0.830 (0.403) | 0.872 | 120 | 0.842 | 0.817 | 0.742 | 14/20 | n/a (1 probe) | 8.5 s; 12.3 s wall |
| NTRS synthetic scan | 3 | 0.965 (0.950) | not run | 18 | 0.944 | 0.944 | 0.870 | 17/18 (only 18 items, so all were checked) | 1.000 (44) | about 6 s wall |

- [OBSERVATION] Marker is by far the fastest here: 6 to 10 s for 15 to 20 pages on CPU, against 63 to 105 s for docling and 20 to 29 s for MinerU basic. Output tree: `Page` with typed children (`SectionHeader`, `Text`, `Table`, `ListGroup`, `PageHeader`, `PageFooter`...), each with `bbox` in points and `polygon`; tables come as HTML.
- [OBSERVATION] It drops content. On AAPL page 12 a whole paragraph ("The Company presents derivative assets and liabilities at their gross fair values in the Consolidated Balance Sheets.") is absent: `grep -c "derivative assets"` on the JSON returns 0 while `pdftotext` shows it on that page. AAPL page 7's running footer ("See accompanying Notes...", "Apple Inc. | 2026 Form 10-K | 33") is missing. Page header/footer blocks are emitted for some pages (12 `PageHeader`, 3 `PageFooter` in the AAPL JSON) but not all.
- [OBSERVATION] On the presentation, whole regions disappear: LFVN page 10 has 0.403 token completeness (100 reference tokens missing, including the title "The Radoff-Sudbury Group..."), page 9 0.568. Docling on the same pages: 0.915 and 0.919 (reference-fragmentation artefact) with 0.999+ character completeness. Marker's fast mode is not safe for slide decks without a completeness gate.
- [OBSERVATION] Table rows: 0.946 (AAPL) and 0.960 (NTRS) of numeric probes kept label and numbers in one row, slightly below docling; bboxes are tighter than docling's cells on NTRS (mean IoU 0.924 vs 0.754, 0.909 of items at IoU >= 0.8).
- [OBSERVATION] Bbox fidelity of what it does return is good: contain >= 0.9 for 100 percent (AAPL) and 99.1 percent (NTRS) of items; 0 out-of-page boxes. On LFVN the 6 failing spot items include a table box whose header cells contain "2020 | 2021 | 2022 | 2023" with zero words inside the box (page 8), and a text block "App - Timeline" with none (page 18).
- [OBSERVATION] README claims (vendor numbers, not reproduced): "Marker fast ... 71.0 at 23.6 pg/s ... beating docling (67.5)" and "balanced ... 80.5" on a benchmark named OmniParseBench (README lines 52-58, 65-68). My CPU run reached about 1.1 to 2.5 pages per second (wall time including model load, 15 pages in 6.1 to 13.9 s), and completeness below docling on three of three documents, so the vendor ranking did not carry over to the completeness metric used here.
- [INFERENCE] Marker is attractive as a cheap first pass or for bulk born-digital triage, but its dropped paragraphs make it unfit as the system of record for diligence quotes unless a per-page pdftotext completeness check re-routes dropped pages to docling.
- [UNKNOWN] `balanced` and `vllm` modes (GPU) and their completeness; not runnable on this CPU-only box.
- [UNKNOWN] Whether the dropped AAPL paragraph is a layout-classification miss in `fast` mode or filtered as a footnote-like block; I did not run `--mode no_ocr` or `--force_ocr` to compare.

## Adopt / borrow ideas / isolated service / skip for Acretia

Isolated service (optional), matching the ledger. Do not import it into core: the weights licence has revenue and funding limits and the output is incomplete without a gate. Use only as an optional speed path behind a pdftotext completeness check; docling stays the default.
