# S5.4b eval report

Generated 2026-11-17 09:37 (mode: fresh). Engine: `ExtractiveEngine` grid-3 (deterministic, offline; no model calls).
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
| vdr_scanned_arabic | 30 | 15/15 | 30 | 100.0 | 0 | 0 | 0 |
| ALL | 304 | 224/80 | 300 | 98.7 | 0 | 4 | 0 |

## VDR first pass (50 documents, pdfdoc parser)

| item | value |
|---|---|
| docs | 50 |
| pages | 269 |
| ocr_pages | 3 |
| arabic_pages | 3 |
| ingest_ok | 50 |
| ingest_failed | 0 |
| ingest_s | 23.0 |
| grid_s | 5.124 |
| risk_s | 5.441 |
| total_s | 79.732 |
| first_cell_s | 0.866892 |
| cells | 650 |
| tokens_in | 0 |
| tokens_out | 0 |
| cost_usd | 0.0 |
| completeness_min | 0.9797 |
| completeness_median | 1.0 |
| cost estimate before run | {"pending_cells": 650, "est_input_tokens": 0, "est_output_tokens": 0, "est_cost_usd": 0.0, "model": "extractive", "engine": "extractive", "skipped_cells": 0, "engine_calls": 650} |
| live-LLM first pass ESTIMATE (not measured) | {"pending_cells": 650, "est_input_tokens": 766714, "est_output_tokens": 104000, "est_cost_usd": 19.30071, "model": "auto", "engine": "llm:auto", "skipped_cells": 0, "engine_calls": 650} |

## Risk detector (vdr_risk.scan_documents)

recall 1.0 (26/26); precision 0.9286 (26/28 in-scope findings; legitimate extra findings: 0); false-positive classes {"spurious_period (year < 2000 parsed from 10-K text)": 0, "conflicting_figure on the real 10-Ks (mis-paired metrics)": 0, "clause finding on a synthetic doc without that clause": 0, "missing_document for a category the room holds": 0, "other": 2}; decoys flagged: 0; Arabic recall {'gold': 2, 'found': 2}; scanned recall {'gold': 1, 'found': 1}

| type | gold | found |
|---|---|---|
| change_of_control | 6 | 6 |
| conflicting_figure | 1 | 1 |
| covenant | 4 | 4 |
| exclusivity | 8 | 8 |
| mfn | 3 | 3 |
| missing_document | 2 | 2 |
| missing_period | 2 | 2 |

Missed:

False positives (in scope, no matching gold) by type: {"conflicting_figure": 2}; first 40 non-period ones:
- conflicting_figure | 01 Financials/Audited/Audited Financial Statements FY2021.pdf p.2 | Meridian Components — Gross profit (FY2021) differs: $13.63m vs $13.27m | Gross profit 13,630,600 11,544,000
- conflicting_figure | 01 Financials/Audited/Audited Financial Statements FY2021.pdf p.2 | Meridian Components — Net income (FY2021) differs: $3.01m vs $3.13m | Net income 3,011,000 2,589,460

Spurious missing_period titles:  ...

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
   "seconds": 22.23,
   "s_per_page": 0.1111,
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
   "seconds": 18.0,
   "s_per_page": 3.0006,
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
   "seconds": 0.41,
   "s_per_page": 0.0686,
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

### vdr_scanned_arabic (0)


