# opendataloader-bench (S5.4b)

Code: Apache-2.0, pinned `7af1d8f4d0c09f51ea1a5c6ba5f66e993286d109` (ledger row exists). Dataset licences are unstated, so **nothing is vendored**: the clone lives in `data/raw/odl_bench/` (gitignored) and its own `src/evaluator.py` is run in place on our markdown output.

Reproduce: `python3 scripts/eval_s5.py` (clones, converts with `om.docparse`, runs the evaluator; `--offline` replays `results.json`). Needs `pip install apted rapidfuzz beautifulsoup4 lxml`.

Our markdown: heading blocks as `##`, table blocks as pipe tables, header/footer dropped. OCR off (so image-only pages score as empty). Docling rows are a subset only, because docling costs seconds per page on this CPU.

| engine | docs | s/page | overall | NID | TEDS | MHS |
|---|---|---|---|---|---|---|
| acretia-pdfdoc | 200 | 0.1163 | 0.6473 | 0.8268 | 0.0 | 0.3885 |
| acretia-docling-first6 | 6 | 3.0162 | 0.9348 | 0.9348 | None | 0.9423 |
| acretia-pdfdoc-first6 | 6 | 0.08 | 0.6382 | 0.9669 | None | 0.0 |

Commands run:

- `cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-pdfdoc --prediction-root pred_acretia --engine acretia-pdfdoc --log-level WARNING`
- `cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-docling-first6 --prediction-root pred_acretia --engine acretia-docling-first6 --log-level WARNING`
- `cd data/raw/odl_bench && python3 src/evaluator.py --ground-truth-dir subset_gt_acretia-pdfdoc-first6 --prediction-root pred_acretia --engine acretia-pdfdoc-first6 --log-level WARNING`

Reading: pdfdoc has no table structure (TEDS 0.0) and no heading levels, so its overall is 0.65 against docling 0.93 on the same 6 documents; those numbers are our parser on this subset, not a claim against the published leaderboard (different hardware, subset).
