# Teardown: MinerU (opendatalab/MinerU)

repo: https://github.com/opendatalab/MinerU
commit: b4efa4b2b76ebb012c476b79bdfc6f18a95aacd6
licence: "MinerU Open Source License" (`LICENSE.md`): Apache-2.0 plus extra terms. (1) A separate commercial licence is required once you and your affiliates exceed 100 million monthly active users or USD 20 million monthly revenue. (2) If you offer an online service to third parties built on MinerU you must say so prominently. (3) Failure to comply terminates the licence. The model repo `opendatalab/MinerU2.5-Pro-2605-1.2B` is tagged `apache-2.0` on Hugging Face; `opendatalab/MinerU-4_models_onnx` (the weights used below) carries no licence tag in the HF API.
ran: yes (PyPI `mineru` 4.2.3 in a venv; local ONNX CPU "basic" tier through `mineru-kit parse`; remote service never used; telemetry disabled with `mineru telemetry disable`; same 4 vCPU box)

Inputs and method are identical to `grid-docling.md`. Boxes in MinerU's middle JSON are page fractions (0 to 1); I multiplied by each page's pdftotext width and height before scoring.

## Licence finding that changes the plan

- [OBSERVATION] PLAN section 0 item 1 lists MinerU as AGPL. At the pinned commit the licence is the Apache-2.0-based custom licence above, which is what the ledger row records. No copyleft clause appears in `LICENSE.md`.
- [INFERENCE] The thresholds (100M MAU or USD 20M a month) are far above Acretia's scale, and the attribution duty applies if Acretia exposes a MinerU-backed online parsing service; the practical blocker is the unlicensed weights (`MinerU-4_models_onnx` has no licence metadata).
- [UNKNOWN] The licence of the ONNX weight repo `opendatalab/MinerU-4_models_onnx` and of the older torch repo; the HF API returned `None` and no tags. Needs a manual read of the repo's card before any redistribution.

## What it is now

- [OBSERVATION] Version 4.x is no longer the 2.x pipeline CLI: `mineru --help` lists `parse`, `read`, `scan`, `watch`, `search`, `server`, `config`... ("your personal document center, built for agents"). `mineru parse` returns Markdown, picks a quality tier (`flash`, `basic`, `standard`, `advanced`) and with no local engine fails with `quality_tier_unavailable ... use --remote`. `--remote` sends the document to the mineru.net official service, which must never be used for Acretia data.
- [OBSERVATION] Working local path: `mineru-kit models download MinerU-4_models_onnx` (about 819 MB, 8 s from Hugging Face) then `mineru-kit parse <pdf> -o <dir> -f middle_json --tier basic` (the 2.x-style low-level kit). `mineru-kit hardware detect` recommended "basic" as the ceiling (flash, basic) on this CPU-only machine. Output: `docvortex.middle` schema 2.0 JSON with `pages[].blocks[]`, each block typed (`text`, `paragraph_title`, `header`, `footer`, `page_number`, `table` with `table_body` HTML and captions/footnotes, `image`, `chart`, `index`...) and a normalised `bbox`.
- [OBSERVATION] Tooling traps: `mineru server start` crashed with `OSError: AF_UNIX path too long` when `HOME` was a long path (the long scratchpad directory); it started after I set `HOME=/tmp/mh` (a symlink); but `mineru parse` still needed an engine, so I used `mineru-kit`. `mineru telemetry status` errors until the local server runs.

## Results

| doc | pages | token completeness (worst page) | char completeness | items scored | contain >= 0.9 | precision >= 0.9 | mean IoU | spot-check 20 | table row probe | inference time |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL 10-K | 15 | 0.994 (0.862) | 0.999 | 151 | 1.000 | 0.993 | 0.832 | 20/20 | 0.793 (92) | 28.8 s (0.52 pg/s); 31.8 s wall |
| NTRS 10-K | 15 | 0.990 (0.938) | 0.998 | 161 | 0.994 | 0.994 | 0.872 | 20/20 | 0.556 (124) | 20.1 s (0.75 pg/s); 22.9 s wall |
| LFVN presentation | 20 | 0.903 (0.417) | 0.970 | 235 | 0.643 | 0.643 | 0.634 | 13/20 | n/a (1 probe) | 22.8 s (0.88 pg/s); 25.6 s wall |
| NTRS synthetic scan | 3 | 0.982 (0.954) | not run | 27 | 1.000 | 1.000 | 0.834 | 20/20 (sample of 27 items) | 0.841 (44) | about 19 s wall |

- [OBSERVATION] MinerU had the best scan result of the three (0.982 token completeness and containment 1.000 on the synthetic scan) and the second-best born-digital completeness on statements (0.994, 0.990), after docling.
- [OBSERVATION] Its weak spot is table structure on financial statements: only 0.793 (AAPL) and 0.556 (NTRS) of numeric rows kept label and all numbers in one parsed row. Example from the AAPL JSON (page 1): `<td>Provision for income taxes $ 27,062</td><td>$ 20,719</td><td>$ 29,749</td>` with the header row `2026 | 2025 | 2024` above it, so the label and the first-year value are merged in one cell. This would corrupt cell-level grounding of a figure unless re-split.
- [OBSERVATION] Block-type labelling is unreliable for downstream logic: on AAPL, body sentences ("Selling, general and administrative expense increased during 2026...") are typed `header` (8 such blocks), and on LFVN the document title is split with stray spaces ("The Radoff-Sudbury G roup H as N ot Offered Any Meani n...").
- [OBSERVATION] On the presentation 0.903 token completeness (page 10 at 0.417, as for Marker, partly the fragmented text layer) and containment 0.643: 235 items include 14 `image`, 5 `chart` and 17 `image_footnote` blocks whose text came from picture OCR with no text-layer words inside the box; 7 of the 20 spot-checked items fail (for example an `image` block on page 16 with the staff names "Michelle Oborn Chief People Officer ..." and a `doc_title` with fragmented words).
- [INFERENCE] Containment numbers on slides understate usefulness for OCR'd picture text and overstate risk for text-layer text, since the reference only sees the text layer; compare the 0.970 character completeness against docling's 0.9999.
- [INFERENCE] Compared with docling in this session: faster (about 3 times), better on the synthetic scan, noticeably worse on numeric table rows. Not a replacement for S5.1's default.
- [UNKNOWN] `standard` and `advanced` tiers (VLM-backed; `MinerU2.5-Pro-2605-1.2B-GGUF` listed by `mineru-kit models show`) which might fix table structure; not downloaded because of the time box and CPU-only hardware.

## Adopt / borrow ideas / isolated service / skip for Acretia

Isolated service, optional (matches the ledger). Never call `--remote`, disable telemetry, and run only the local ONNX tier in a container if used at all. Useful as a fallback for scanned pages (best OCR containment of the three) but not for statement tables.
