# S5.4b eval report

Generated 2026-11-17 09:20 (mode: offline (cached DB)). Engine: `ExtractiveEngine` grid-2 (deterministic, offline; no model calls).
LLM engine: not run live (D-021: no endpoint/keys in this session); no replay fixtures exist for these rooms.

## 10-K QA (10 real filings x 10 questions)

| metric | value |
|---|---|
| cells | 100 |
| value accuracy (target >= 0.70) | 1.000 |
| quote located on cited page | 1.000 |
| cited page == gold page | 0.930 |
| success (value right and quote on page) | 1.000 |
| wrong_but_confident / missed / silent | 0 / 0 / 0 |

By question:

| question | n | value ok | quote on page | page match |
|---|---|---|---|---|
| q01 | 10 | 10 | 10 | 9 |
| q02 | 10 | 10 | 10 | 8 |
| q03 | 10 | 10 | 10 | 8 |
| q04 | 10 | 10 | 10 | 10 |
| q05 | 10 | 10 | 10 | 10 |
| q06 | 10 | 10 | 10 | 10 |
| q07 | 10 | 10 | 10 | 10 |
| q08 | 10 | 10 | 10 | 8 |
| q09 | 10 | 10 | 10 | 10 |
| q10 | 10 | 10 | 10 | 10 |

## Reliability (D-032): all gold cells

| room | n | found/not_found | success | success % | wrong_but_confident | missed | silent |
|---|---|---|---|---|---|---|---|
| tenk | 100 | 100/0 | 100 | 100.0 | 0 | 0 | 0 |
| vdr_en | 174 | 109/65 | 170 | 97.7 | 0 | 4 | 0 |
| vdr_scanned_arabic | 30 | 15/15 | 22 | 73.3 | 0 | 8 | 0 |
| ALL | 304 | 224/80 | 292 | 96.0 | 0 | 12 | 0 |

## VDR first pass (50 documents, pdfdoc parser)

| item | value |
|---|---|
| docs | 50 |
| pages | 269 |
| ocr_pages | 3 |
| arabic_pages | 3 |
| ingest_ok | 50 |
| ingest_failed | 0 |
| ingest_s | 24.862 |
| grid_s | 4.978 |
| risk_s | 18.526 |
| total_s | 94.63 |
| first_cell_s | 0.333945 |
| cells | 650 |
| tokens_in | 0 |
| tokens_out | 0 |
| cost_usd | 0.0 |
| completeness_min | 0.9797 |
| completeness_median | 1.0 |
| cost estimate before run | {"pending_cells": 650, "est_input_tokens": 0, "est_output_tokens": 0, "est_cost_usd": 0.0, "model": "extractive", "engine": "extractive", "skipped_cells": 0, "engine_calls": 650} |
| live-LLM first pass ESTIMATE (not measured) | {"pending_cells": 650, "est_input_tokens": 766714, "est_output_tokens": 104000, "est_cost_usd": 19.30071, "model": "auto", "engine": "llm:auto", "skipped_cells": 0, "engine_calls": 650} |

## Risk detector (vdr_risk.scan_documents)

recall 0.7692 (20/26); precision 0.1825 (23/126 in-scope findings; legitimate extra findings: 0); false-positive classes {"spurious_period (year < 2000 parsed from 10-K text)": 65, "conflicting_figure on the real 10-Ks (mis-paired metrics)": 9, "clause finding on a synthetic doc without that clause": 0, "missing_document for a category the room holds": 0, "other": 29}; decoys flagged: 0; Arabic recall {'gold': 2, 'found': 0}; scanned recall {'gold': 1, 'found': 1}

| type | gold | found |
|---|---|---|
| change_of_control | 6 | 6 |
| conflicting_figure | 1 | 0 |
| covenant | 4 | 4 |
| exclusivity | 8 | 3 |
| mfn | 3 | 3 |
| missing_document | 2 | 2 |
| missing_period | 2 | 2 |

Missed:
- exclusivity 02 Legal/Material Contracts/Customers/Customer Agreement - Northwind.pdf
- exclusivity 02 Legal/Material Contracts/Suppliers/Supplier Agreement - Tundra.pdf
- exclusivity 04 Corporate/Board Minutes/Board Minutes - February 2025.pdf
- exclusivity 04 Corporate/Board Minutes/Board Resolution - May 2024 (Arabic).pdf
- exclusivity 02 Legal/Material Contracts/Suppliers/Supplier Agreement - Gulf Materials (Arabic).pdf
- conflicting_figure 01 Financials/CIM/Confidential Information Memorandum - Excerpt.pdf

False positives (in scope, no matching gold) by type: {"conflicting_figure": 9, "missing_period": 94}; first 40 non-period ones:
- conflicting_figure | 01 Financials/10-K/COST 10-K.pdf p.6 | Debt (FY2026) differs: $69 vs $2.2 billion | Repayments of long-term debt in 2026 totaled $69, as compared to $103 in 2025.
- conflicting_figure | 01 Financials/10-K/HD 10-K.pdf p.6 | Revenue (FY2025) differs: $307 million vs $79 million vs $164.7 billion vs $5.2 billion | A stronger U.S. dollar compared to fiscal 2024 negatively impacted net sales by $307 million in fisc
- conflicting_figure | 01 Financials/10-K/AAPL 10-K.pdf p.9 | Gross margin (FY2024) differs: 233602% vs 225465% | Gross margin 233,602 195,201 180,683
- conflicting_figure | 01 Financials/10-K/JNJ 10-K.pdf p.5 | Operating cash flow (FY2025) differs: $24.5 vs $24.5 billion vs $16.3 billion | $24.5 Cash flow from operations
- conflicting_figure | 01 Financials/10-K/JNJ 10-K.pdf p.5 | Net income (FY2025) differs: $26.8 vs $79 million vs $14.2 billion | $26.8 Net Earnings
- conflicting_figure | 01 Financials/10-K/JNJ 10-K.pdf p.11 | Net income (FY2023) differs: $26,804 vs $0.2 billion | Net earnings $26,804 14,066 35,153
- conflicting_figure | 01 Financials/10-K/KO 10-K.pdf p.2 | Employees (FY2024) differs: 69,700 vs 1 vs 2 vs 355,000 | 2025 and 2024, our Company had approximately 65,900 and 69,700 employees, respectively, of which app
- conflicting_figure | 01 Financials/10-K/MSFT 10-K.pdf p.7 | EPS (FY2025) differs: $17.95 vs $6.89 vs $14.23 vs $11.95 vs $0.43 | Diluted earnings per share 17.95 13.64 32%
- conflicting_figure | 01 Financials/10-K/MSFT 10-K.pdf p.7 | Gross margin (FY2025) differs: 225465% vs 1485800% vs 1459200% vs 1565600% vs 1542800% vs 1630200% | Gross margin 225,465 193,893 16%

Spurious missing_period titles: Missing 2024-04, Missing 2024-05, Missing 2024-06, Missing 2024-07, Missing 2024-08, Missing 2024-09, Missing 2024-10, Missing 2024-12, Missing FY1935, Missing FY1936, Missing FY1937, Missing FY1938 ...

## opendataloader-bench

{
 "status": "run",
 "commit": "7af1d8f4d0c09f51ea1a5c6ba5f66e993286d109",
 "docs_total": 200,
 "engines": {
  "acretia-pdfdoc": {
   "docs": 200,
   "pages": 200,
   "parse_failures": 0,
   "seconds": 23.25,
   "s_per_page": 0.1163,
   "score": {
    "overall_mean": 0.6473,
    "nid_mean": 0.8268,
    "nid_s_mean": 0.8051,
    "teds_mean": 0.0,
    "teds_s_mean": 0.0,
    "mhs_mean": 0.3885,
    "mhs_s_mean": 0.4774
   },
   "backend": "pdfdoc",
   "ocr": "off",
   "command": "cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-pdfdoc --prediction-root pred_acretia --engine acretia-pdfdoc --log-level WARNING"
  },
  "acretia-docling-first6": {
   "docs": 6,
   "pages": 6,
   "parse_failures": 0,
   "seconds": 18.1,
   "s_per_page": 3.0162,
   "score": {
    "overall_mean": 0.9348,
    "nid_mean": 0.9348,
    "nid_s_mean": 0.9348,
    "teds_mean": null,
    "teds_s_mean": null,
    "mhs_mean": 0.9423,
    "mhs_s_mean": 1.0
   },
   "backend": "docling",
   "ocr": "off",
   "command": "cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-docling-first6 --prediction-root pred_acretia --engine acretia-docling-first6 --log-level WARNING"
  },
  "acretia-pdfdoc-first6": {
   "docs": 6,
   "pages": 6,
   "parse_failures": 0,
   "seconds": 0.48,
   "s_per_page": 0.08,
   "score": {
    "overall_mean": 0.6382,
    "nid_mean": 0.9669,
    "nid_s_mean": 0.9669,
    "teds_mean": null,
    "teds_s_mean": null,
    "mhs_mean": 0.0,
    "mhs_s_mean": 0.0
   },
   "backend": "pdfdoc",
   "ocr": "off",
   "command": "cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-pdfdoc-first6 --prediction-root pred_acretia --engine acretia-pdfdoc-first6 --log-level WARNING"
  }
 }
}

## docling on the 10 10-Ks

{
 "parser": "docling",
 "docs": 10,
 "ingest_ok": 10,
 "ingest_failed": 0,
 "pages": 209,
 "ingest_s": 1215.4,
 "s_per_page": 5.82,
 "workers": 2,
 "engine_version": "grid-2",
 "grid_first_cell_s": 0.494958,
 "score": {
  "n": 100,
  "success": 99,
  "wrong_but_confident": 0,
  "missed": 1,
  "silent": 0,
  "success_rate": 0.99,
  "n_found": 100,
  "n_not_found": 0,
  "value_accuracy": 0.99,
  "quote_on_page": 0.99,
  "page_match": 0.92
 },
 "backends": [
  "docling"
 ],
 "ingest_timing_from": "first docling ingest (parse cached since)"
}

## Failures by cell id

### tenk (0)


### vdr_en (4)

- `vdr_en:Management Accounts January 2025:v09` [missed] status not_found (gold p.1)
- `vdr_en:Management Accounts June 2025:v09` [missed] status not_found (gold p.1)
- `vdr_en:Budget and Forecast FY2025:v09` [missed] status not_found (gold p.1)
- `vdr_en:Confidential Information Memorandum - Excerpt:v09` [missed] status not_found (gold p.1)

### vdr_scanned_arabic (8)

- `vdr_scanned_arabic:Board Minutes - November 2024 (scanned):v10` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Lease Agreement - Jebel Ali (Arabic):v12` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Lease Agreement - Jebel Ali (Arabic):v02` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Board Resolution - May 2024 (Arabic):v09` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Board Resolution - May 2024 (Arabic):v05` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Supplier Agreement - Gulf Materials (Arabic):v12` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Supplier Agreement - Gulf Materials (Arabic):v02` [missed] status not_found (gold p.1)
- `vdr_scanned_arabic:Supplier Agreement - Gulf Materials (Arabic):v05` [missed] status not_found (gold p.1)

