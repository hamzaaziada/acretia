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
