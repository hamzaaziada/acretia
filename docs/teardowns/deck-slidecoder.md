# Teardown: vinsontang1/SlideCoder

repo: https://github.com/vinsontang1/SlideCoder
commit: c71faa5b76caaa09e407e17c845bbabc0ed8a3fa
licence: no top-level LICENSE file; SlideMaster/LICENSE is "Apache License" (training code adopted from LLaMA-Factory); the SlideCoder/ code itself is therefore unlicensed (all rights reserved by default)
ran: partial (only the deterministic CGSeg image segmentation, SlideCoder/block_based.py, on one rendered slide image; the LLM stages (describer, coder, assembler, RAG) were not run)

Run artefacts: /tmp/claude-0/-home-user-acretia/e1d17012-803b-575a-9195-afc7303c9ca6/scratchpad/s12/out/slidecoder/ (ref-3.png input, seg/ref-3/ref-3_info.json, _annotated.png and 5 box crops).

## Findings

- [OBSERVATION] Task is reference-image-to-code: given a design image, produce python-pptx code that reproduces it (README.md sections "Slide2Code", "SlideCoder"; paper EMNLP 2025). It is not a brief-to-deck generator; none of the three finance briefs maps onto it.
- [OBSERVATION] Pipeline files: block_based.py (CGSeg: grid complexity map, connected-region detection, recursive boxes), get_description_AIagent.py (LLM describer), generated_ppt_code_AIagent.py (LLM coder), rag.py with db/FBK.txt and db/TBK.txt (retrieved API-knowledge snippets), run_all_code.py (assemble) (file list, line counts 40-729).
- [OBSERVATION] The deterministic CGSeg stage ran locally on a rendered brief-C 2x2 slide at 100 dpi and produced 5 region boxes plus an annotated image in under a second, with defaults grid 32, threshold 1.5, surrounding 0.5, depth 2 (block_based.py:467-492; ref-3_info.json). Requires opencv, numpy, tqdm.
- [OBSERVATION] SECURITY: SlideCoder/model.py:13-14 contains a hard-coded OpenAI-style API key string and a third-party base_url (openkey.cloud) in committed source. The value is deliberately not reproduced here; it was not used and no request was made. Treat the repo as untrusted and never import model.py.
- [OBSERVATION] Layout method: absolute coordinates inferred from the image by the model; text-fit: none; charts: images or shapes inferred; validator: none; RTL: none found.
- [OBSERVATION] SlideMaster/ holds fine-tuning scripts (train.sh, merge.sh) for a vLLM model; Slide2Code/Slide2Code.csv lists pptx URLs for the benchmark (copyright reasons given in README).
- [INFERENCE] The only transferable idea is segmenting a rendered slide into regions to point a vision critic at specific boxes (S3.8). Our validator will name shape ids instead, which is stronger because it is exact.
- [UNKNOWN] Benchmark numbers and the quality of the generated code: not reproducible without model access.

## Adopt / borrow ideas / skip

Skip (no licence for the main code, committed secret, wrong task). At most note the region-segmentation idea for the vision critic; do not copy code.
