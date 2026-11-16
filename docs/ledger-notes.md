# Licence ledger notes (S1.1)

Companion to `license-and-repo-ledger.csv`. Commits were pinned with `git ls-remote <url> HEAD` on 2026-11-16. Licence text was read from the file at that commit via `raw.githubusercontent.com/<owner>/<name>/<commit>/<file>`, not from memory. Lucide's licence file under `reference/meshpool-harness/engines/slides/icons/` was read locally.

## Repos that needed identification

- **formulon** -> `libraz/formulon` (web search: headless Excel 365 calculation engine, C++17/WASM/Python). LICENSE starts "Apache License Version 2.0".
- **dexter** -> `virattt/dexter` (autonomous financial research agent; README matches PLAN's use). No LICENSE file at the commit; README "License" section says MIT. Treated as ideas only.
- **SlidesBench** -> lives inside `para-lost/AutoPresent` (`slidesbench/` directory), so it shares the AutoPresent row. AutoPresent LICENSE first line "MIT License".
- **SlideCoder** -> `vinsontang1/SlideCoder` (linked from the EMNLP 2025 paper; a mirror under `vinsontang2126` was ignored). No LICENSE file; README has no licence text. Ideas from the paper only.
- **Mck-ppt-design-skill** -> `likaku/Mck-ppt-design-skill`. LICENSE: Apache License 2.0.
- **mbb-ppt-generator** -> `albertojb/mbb-ppt-generator`, a derivative of Mck-ppt-design-skill. LICENSE: Apache License 2.0.
- **clean-slides** -> `tmustier/clean-slides`. LICENSE first line "MIT License".
- **pptx-mcp-server** -> `knorq-ai/pptx-mcp-server` (PyPI `pptx-mcp-server`, has a McKinsey theme preset and layout engine). LICENSE "MIT License". Another repo with a similar name, `samos123/pptx-mcp` (Apache-2.0), exists but was not selected because it has no McKinsey theme.
- **swak/pptx-mcp** -> not found as a git repo: `git ls-remote https://github.com/swak/pptx-mcp` returns nothing; only a PyPI package `pptx-mcp` credited to swak. Row is `n/a (not found ...)`, decision `skip`.
- **mckinsey-pptx** -> no repository of that name found (tried `github.com/mckinsey/pptx` and a web search). Row is `n/a (not found ...)`, decision `skip`. Closest matches have their own rows.
- **ginlix-ai pptx skill** -> `ginlix-ai/LangAlpha`, directory `skills/pptx` per skill directories. Root LICENSE is Apache License 2.0, but `skills/pptx/SKILL.md` returns 404 at the pinned commit, so the path has moved or been removed. Confirm at teardown.
- **Vals Finance Agent** -> `vals-ai/finance-agent`. LICENSE: "MIT License, Copyright (c) 2025 Vals AI, Inc."
- **FinanceBench** -> `patronus-ai/financebench` (150-example open sample). No LICENSE file. The HuggingFace dataset card API for `PatronusAI/financebench` says `cc-by-nc-4.0`.
- **opendataloader-bench** -> `opendataloader-project/opendataloader-bench`; its parser `opendataloader-project/opendataloader-pdf` is added as a comparator row. Both Apache License 2.0.
- **SpreadsheetBench** -> `RUCKBReasoning/SpreadsheetBench`. No LICENSE file; README says "hosted with the CC BY SA 4.0 License".
- **OpenBB** -> `OpenBB-finance/OpenBB`. Root LICENSE first lines: "Copyright (c) 2021-2026 OpenBB Inc. All files in this repository are licensed under the Apache License, Version 2.0." No per-module exception at this commit. PLAN flagged an Aug-2026 per-module licence change, so re-check at adoption time.
- **crawl4ai** -> LICENSE is Apache-2.0 with an appended "Attribution Requirement" section. All distributions and public uses must carry: "This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai)." This is stricter than plain Apache-2.0.
- **Marker** -> `datalab-to/marker`. PLAN says GPL, but LICENSE at the commit is Apache License 2.0 and pyproject says `Apache-2.0`. The weights are under a modified AI Pubs Open RAIL-M (`MODEL_LICENSE`; README: free for research, personal use and startups under 5M USD funding/revenue). Kept as `isolated_service` because of the weights.
- **MinerU** -> `opendatalab/MinerU`. LICENSE.md first line "MinerU Open Source License": Apache-2.0 plus extra terms (commercial licence above 100M MAU or 20M USD monthly revenue; visible attribution for online services; automatic termination on breach). PLAN says AGPL; not so at this commit, but the opendataloader-bench README still lists it as AGPL-3.0 (older versions).
- **anthropics/skills** -> no root LICENSE (404). `skills/pptx|docx|xlsx|pdf|skill-creator|frontend-design|mcp-builder/LICENSE.txt` are each Apache License 2.0 (checked: no "all rights reserved" text), and the README says the document skills are open source (Apache 2.0). PLAN assumed proprietary; kept `borrow_ideas` with zero copying because the repo has no single licence and a per-skill re-check is needed before any reuse.
- **anthropics/financial-services** -> LICENSE is Apache License 2.0; README "License" section says "Apache License 2.0". PLAN's "Apache-2.0?" is confirmed.
- **docling** -> LICENSE first line "MIT License"; README: "The Docling codebase is under MIT license. For individual model usage, please refer to the model licenses found in the original packages." Weight licences are an open item.
- **openpyxl** -> Mercurial repo at `foss.heptapod.net/openpyxl/openpyxl` (git ls-remote fails), no GitHub mirror, so `commit_hash` is `n/a`. PyPI metadata says MIT, version 3.1.5. The sdist LICENCE file was not fetched.
- **poppler** -> `gitlab.freedesktop.org/poppler/poppler`, HEAD pinned via `git ls-remote https://gitlab.freedesktop.org/poppler/poppler.git`. COPYING is GPLv2, COPYING3 is GPLv3, and the README says "Poppler is licensed under the GPL, not the LGPL".
- **LibreOffice** -> `git.libreoffice.org/core` HEAD equals the GitHub mirror `LibreOffice/core` HEAD (7b2a56bf...). `COPYING.MPL` is Mozilla Public License 2.0, `COPYING` is GPLv3 text, and the README says it is "based on copyleft licenses".
- **python-bidi** -> `COPYING` begins with GNU GPL v3 text and `COPYING.LESSER` adds the LGPL; the pyproject classifier is LGPL. Recorded as LGPL-3.0.
- **Pillow** -> LICENSE says "Pillow is licensed under the open source MIT-CMU License".
- **redis** -> `LICENSE.txt` at the commit says Redis 8+ is tri-licensed (RSALv2, SSPLv1, AGPLv3) and 7.2 and earlier are BSD-3-Clause.
- **minio** -> LICENSE is GNU AGPL v3.
- **pypdfium2** -> no root LICENSE; `LICENSES/Apache-2.0.txt` exists and the README states "Apache-2.0 / BSD-3-Clause" for the code and CC-BY-4.0 for docs. It bundles PDFium (BSD-style).
- **Lucide** -> upstream LICENSE first line "ISC License, Copyright (c) 2026 Lucide Icons and Contributors". The vendored `LICENSE-lucide.txt` starts "ISC License; Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT)". Keep that file with the icons.
- **Additions not named in PLAN** (named in PLATFORM.md, DECISIONS.md or PLAN stage text): PyMuPDF, FastAPI, vLLM, Ollama, MinIO, Redis, PostgreSQL, opendataloader-pdf.

## Copyleft, source-available and proprietary items

| Item | Licence | Isolation plan |
|---|---|---|
| Marker (`datalab-to/marker`) | Apache-2.0 code, Open RAIL-M modified weights | Separate Docker service over HTTP; weights restricted commercially; never imported |
| MinerU | Apache-2.0 + revenue/MAU threshold + attribution | Separate Docker service over HTTP; show attribution if exposed online |
| PyMuPDF | AGPL-3.0 | `skip`; use pdfplumber, pypdfium2 and pdfminer.six |
| poppler | GPL-2.0-or-later / GPL-3.0 | `pdftotext` subprocess in Docker image only; no linking |
| LibreOffice | MPL-2.0 plus GPL/LGPL components | `soffice` subprocess only (recalc and render) |
| MinIO | AGPL-3.0 | Optional unmodified container, S3 HTTP only |
| Redis 8+ | RSALv2 / SSPLv1 / AGPLv3 | Pin 7.2 (BSD-3-Clause) image or use a permissive fork; separate container |
| python-bidi | LGPL-3.0 | Optional pip dependency, unmodified, never vendored |
| FinanceBench dataset | CC-BY-NC-4.0 | Local internal scoring only; never vendor or ship |
| SpreadsheetBench data | CC-BY-SA-4.0 | Use locally; do not copy into this repo |
| crawl4ai | Apache-2.0 + attribution clause | Add the required line to NOTICE if ever adopted |
| dexter, SlideCoder, FinanceBench repo | no LICENSE file | Ideas only |
| swak/pptx-mcp, mckinsey-pptx | not found | `skip` |

## Import-name → ledger row map

Every third-party (non-stdlib) module imported under `om/`, `src/`, `scripts/` and `open_multiples.py` (top-level, function-level, try/except and constant `importlib.import_module`), found by AST walk against `sys.stdlib_module_names`, maps to a ledger row `owner/repo` below. FP-R2 added `psycopg` and `pypdf`.

| import_name | ledger repo | decision |
|---|---|---|
| `psycopg` | `psycopg/psycopg` | adopt (LGPL-3.0, optional, dynamic import, unmodified) |
| `pypdf` | `py-pdf/pypdf` | adopt (BSD-3-Clause, optional) |
| `pdfplumber` | `jsvine/pdfplumber` | see ledger |
| `duckdb` | `duckdb/duckdb` | see ledger |
| `edgar` | `dgunning/edgartools` | see ledger |
| `crawl4ai` | `unclecode/crawl4ai` | see ledger (attribution clause) |
| `arabic_reshaper` | `mpcabd/python-arabic-reshaper` | adopt (MIT; om/deck/rtl.py, om/deck/validate.py) |
| `docling_core` | `docling-project/docling-core` | adopt (MIT; om/docparse.py) |
| `lxml` | `lxml/lxml` | adopt (BSD-3-Clause; om/deck/*) |
| `yaml` | `yaml/pyyaml` | adopt (MIT; om/deck/spec.py) |
| `fontTools` | `fonttools/fonttools` | adopt (MIT, optional textfit extra) |
| `uno` | `LibreOffice/core` | isolated_service (MPL-2.0; lazy import in om/recalc.py from the system soffice Python, never vendored) |
| `com` | `LibreOffice/core` | isolated_service (`com.sun.star.*` UNO bindings, om/recalc.py) |

Names that differ from the repo, kept for future imports (rows already in the ledger): `bidi → MeirKriheli/python-bidi`, `PIL → python-pillow/Pillow`, `pptx → scanny/python-pptx`, `fitz → pymupdf/PyMuPDF`, `redis → redis/redis`.

LibreOffice note (D-S1-02): `soffice` runs as a separate headless process. The pyuno client bridge (MPL-2.0: `uno`, `com.sun.star`) is imported lazily, only in `om/recalc.py`, inside a function body or try/except, never at module top level. The S1 gate allow-lists exactly `(om/recalc.py, uno)` and `(om/recalc.py, com)` and fails any other in-process import of an `isolated_service` row.

## Distribution → ledger row map

One line per distribution declared in `requirements.txt` or `requirements-extras.txt` (there is no `pyproject.toml`), plus the optional or transitive distributions the code imports. Distribution names are the PyPI names, matched case-insensitively. A gate maps exactly on the left name; it must not use substring matching (specialist F1).

Declared in `requirements.txt` / `requirements-extras.txt`:

- PyYAML → yaml/pyyaml
- python-pptx → scanny/python-pptx
- XlsxWriter → jmcnamara/XlsxWriter
- lxml → lxml/lxml
- Pillow → python-pillow/Pillow
- fonttools → fonttools/fonttools
- arabic-reshaper → mpcabd/python-arabic-reshaper
- openpyxl → openpyxl/openpyxl
- pdfplumber → jsvine/pdfplumber
- duckdb → duckdb/duckdb
- docling → docling-project/docling
- formulon → libraz/formulon

Imported or pulled in, not declared in a requirements file:

- psycopg → psycopg/psycopg
- pypdf → py-pdf/pypdf
- edgartools → dgunning/edgartools
- python-bidi → MeirKriheli/python-bidi
- pdfminer.six → pdfminer/pdfminer.six
- docling-core → docling-project/docling-core
- docling-parse → docling-project/docling-parse
- torch → pytorch/pytorch
- transformers → huggingface/transformers
- pypdfium2 → pypdfium2-team/pypdfium2

`anthropic` is no longer declared (FP-S1b): `grep -rn "import anthropic\|from anthropic" --include=*.py .` outside `reference/` matches only `tests/test_grid.py:521`, which asserts that no provider SDK is imported. D-020 and `src/harness/adapter.py` are the only model path, which speaks to providers over HTTP, so no `anthropics/anthropic-sdk-python` row is needed. Add one (and the dependency) only if an SDK import is ever approved inside the adapter.

`XlsxWriter` is pinned to the commit of tag `RELEASE_3.2.9` (`e943bee8...`) because `requirements.txt` pins 3.2.9. Its only consumer is python-pptx chart embedding via `om/deck/render.py` (`slide.shapes.add_chart`); no file imports `xlsxwriter` directly.

## Transitive dependencies policy

Transitive packages (for example rapidocr, opencv-python-headless, shapely, scipy, numpy, pandas, tqdm, orjson, certifi, the docling-ibm-models and EasyOCR family) are covered by their parent's ledger row plus a CI licence report, not by one ledger row each. The rule:

- Every direct or declared distribution has an exact row (map above).
- CI produces a licence report of the installed environment for each shipped image (`pip-licenses --format=json`, or a CycloneDX SBOM) and fails if any distribution is GPL, AGPL, SSPL, a non-commercial licence, or has no licence metadata, unless the distribution is named in the exceptions below.
- A transitive package that is imported directly by our code gets its own row (that is how pypdf, psycopg and edgartools were added).
- Attribution and notice texts of transitive packages ride in the image's own licence report; `THIRD_PARTY_NOTICES.md` lists only the ledger rows.

Inspection done on 2026-11-16 from `importlib.metadata` of this environment (171 installed distributions; docling, torch, formulon and transformers are not installed here, so docling's own closure could not be listed from metadata and must be generated in the docling image by the CI report):

| Distribution | Licence (metadata) | Pulled in by | Assessment |
|---|---|---|---|
| rapidocr 3.10.0 | Apache-2.0 | docling OCR extra | permissive; its model weights have their own licence, check in the docling image |
| opencv-python-headless 5.0.0.93 | Apache-2.0 (wheel bundles third-party libs) | rapidocr | permissive; wheels bundle third-party native libraries, read the wheel's third-party licence file in the image [UNKNOWN] |
| shapely 2.2.0 | BSD-3-Clause | rapidocr | permissive; wheels bundle native libraries (GEOS is LGPL) [INFERENCE, check in the image] |
| scipy 1.18.1 | BSD | docling closure | permissive; wheels bundle native runtime libraries [UNKNOWN, check in the image] |
| numpy 2.5.3, pandas 3.0.5 | BSD-3-Clause family | edgartools, docling | permissive |
| certifi 2026.10.18 | MPL-2.0 | requests, httpx | file-level copyleft; unmodified, fine |
| tqdm 4.70.1 | MPL-2.0 AND MIT | edgartools, rapidocr | file-level copyleft; unmodified, fine |
| orjson 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | edgartools | file-level copyleft; unmodified, fine |
| python-bidi 0.6.12 | LGPL-3.0 | optional RTL | LGPL: keep a replaceable pip install, no one-file bundle |
| psycopg | LGPL-3.0 | optional Postgres | same LGPL condition (row above) |
| cuda-toolkit 13.2.2 | no licence metadata (NVIDIA EULA expected) | cuda-bindings, a GPU torch build | proprietary redistribution terms; ship the CPU torch wheel in the docling image (ledger row pytorch says CPU wheel) |
| httpxthrottlecache 0.7.0 | no licence metadata | edgartools | unknown; read its repository licence before shipping an image that includes edgartools |
| launchpadlib, lazr.*, wadllib, PyGObject, python-apt | LGPL / GPL | this operating system, not Acretia | not part of any shipped image; ignore |

[INFERENCE] Copyleft or proprietary risks to watch in docling's own closure, none confirmed because docling is not installed here; the CI report in the docling image must confirm or clear each: an `opencv-python` (non-headless) or `PyMuPDF` pulled by an OCR or PDF extra (AGPL for PyMuPDF; our docling extra must not install it), `python-bidi` (LGPL, above), LGPL or MPL packages (MPL is file-level and fine if unmodified; LGPL needs the replaceable-install condition), and GPU wheels (`nvidia-*`, `cuda-*`, proprietary EULA). The CI report fails the build on any of these that are not listed above.

## Docling weights (revision note, FP-S1b)

Checked at docling commit `e16c4b71` and with the Hugging Face API on 2026-11-16:

- `docling-project/docling-models` (TableFormer): docling requests revision tag `v2.3.0` (`docling/models/stages/table_structure/table_structure_model.py:151`). The HF API resolves `v2.3.0` to `fc0f2d45e2218ea24bce5045f58a389aed16dc23`, the commit in the ledger row, and the card at that revision declares `cdla-permissive-2.0`. This closes specialist F6 for this row. A tag can move, so mirror the weights or pass the SHA before release.
- `docling-project/docling-layout-heron`: docling requests `revision="main"` (`docling/datamodel/layout_model_specs.py:83-85`). The commit in the ledger row is only the `main` HEAD read on 2026-11-16. These are unpinned weights; pin before release.

## Other decisions in FP-S1b

- psycopg row corrected: it is not declared in any requirements file (specialist F4).
- `THIRD_PARTY_NOTICES.md` added at the repo root. It is hand-assembled from the pinned LICENSE and NOTICE files listed in the ledger; regenerate it whenever an `adopt` row is added.
- FinanceBench numbers may be quoted only as an internal benchmark, never in sales material, without Patronus AI's permission (CC-BY-NC-4.0; specialist weights note).
