# Third-party notices

This file accompanies every distribution of Acretia (source, container image or packaged app). It lists the third-party software the project adopts or bundles, with the pinned commit, the SPDX licence identifier, the copyright lines and the attribution text that the licences require. It is assembled from `license-and-repo-ledger.csv` and the LICENSE and NOTICE files read at the pinned commits (via `raw.githubusercontent.com/<owner>/<repo>/<commit>/<file>`). The ledger and `docs/ledger-notes.md` are the source of truth; regenerate this file whenever an `adopt` row is added or changed.

Scope and exclusions:

- GPL and AGPL tools (poppler, MinIO) run only as separate processes or containers reached over a subprocess or network boundary. They are not part of the Acretia application code, are not linked or imported, and are not listed here as bundled software. If an image redistributes their binaries, that image carries their own licence texts and source offers.
- Items marked `isolated_service` or `borrow_ideas` appear below only when their licence imposes an attribution or NOTICE obligation (crawl4ai, MinerU, Apache Tika, Tesseract, PPTAgent). Items with no obligation are in the ledger only.
- Apache-2.0 LICENSE files at the pinned commits carry no holder line; where a project ships a NOTICE file its text is reproduced below, otherwise the entry says so.
- Model weights and datasets are not vendored; their licences are recorded in the ledger (`docling-models`, `docling-layout-heron`) and listed here because docling downloads them at first run.

Full licence texts: the SPDX texts at https://spdx.org/licenses/ apply; each project's own LICENSE file at the pinned commit is authoritative, and is what the links below point to.

## Required attribution statements

**Crawl4AI (condition of its licence, `unclecode/crawl4ai` LICENSE, "Attribution Requirement").** Required if Crawl4AI is ever adopted or distributed; it must appear in a NOTICE or README for software distributions, in the credits for web applications and in the help output for command-line tools:

> This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai).

**MinerU (MinerU Open Source License, additional terms 2 and 3).** If Acretia offers an online service to third parties that is based on MinerU, it must clearly and prominently indicate in the product interface or in public documentation that MinerU is used. Non-compliance terminates the licence automatically. MinerU is currently an optional isolated service and is not part of the default deployment.

**Lucide icons (ISC, with portions MIT from Feather).** Reproduced in full under the Lucide entry below; the vendored copy is `reference/meshpool-harness/engines/slides/icons/LICENSE-lucide.txt` and must travel with the icons.

---

## internal/meshpool-harness

- Repository: (internal, in-repo)
- Pinned commit: n/a (copied 2026-11-16 from the user's Meshpool Harness Experiment)
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2026 Meshpool Harness contributors (LICENSE in reference/meshpool-harness/)
- Reason in ledger: User's own project; curated, secret-scanned subset in reference/meshpool-harness/ (D-016)

## docling-project/docling

- Repository: https://github.com/docling-project/docling
- Pinned commit: e16c4b71a7b7d9154ffca164accad2581aed5c9f
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright The Docling Contributors
- Reason in ledger: Default PDF parser (S5.1) with pages and bboxes; code MIT, but model weights have their own licences (README) - check each weight licence at teardown before shipping

## opendatalab/MinerU

- Repository: https://github.com/opendatalab/MinerU
- Pinned commit: b4efa4b2b76ebb012c476b79bdfc6f18a95aacd6
- SPDX licence: Apache-2.0  (ledger: Apache-2.0 + additional terms (MinerU Open Source License))
- Ledger decision: isolated_service
- Copyright:
  - © 2026 [MinerU Team]
- Additional terms (verbatim from LICENSE.md):

```text
## MinerU Open Source License

MinerU is licensed under Apache License 2.0 and is subject to the additional terms below. Except to the extent expressly modified or supplemented by these additional terms, your other rights and obligations are governed by Apache License 2.0.

**1. Commercial License and Thresholds**

MinerU may be used for commercial purposes without a separate commercial license. However, if you and your Affiliates, on a consolidated basis, meet either of the following thresholds, you must obtain a separate commercial license from [MinerU Team] before continuing such use:

a. monthly active users (MAU) exceed 100 million; or  
b. total monthly revenue exceeds USD 20 million.

**2. Online Service Attribution Obligation**

If you provide online services to third parties based on MinerU, you must clearly and prominently indicate, in the relevant product or service interface or in publicly available documentation, that MinerU is used.

**3. Termination**

Where a separate commercial license is required under Section 1 but is not obtained before continuing such use, or where the attribution obligation under Section 2 is not complied with, this License and all rights granted under this License will terminate automatically, and no further notice from the Licensor is required.

**4. Definitions**

In these additional terms, “Affiliates” means any legal entity that directly or indirectly controls, is controlled by, or is under common control with you.
“Control” means the power to direct the management and operating decisions of an entity, whether through equity ownership, voting rights, contractual arrangements, or otherwise.

The full text of Apache License 2.0 is available at https://www.apache.org/licenses/LICENSE-2.0 .

© 2026 [MinerU Team]

---

## MinerU 开源许可协议

MinerU 依据 Apache License 2.0 进行许可，并受以下附加条款约束。除本附加条款明确修改或补充之处外，您的其他权利与义务均适用 Apache License 2.0 的规定。

**1. 商业许可与门槛**

MinerU 可在无需另行取得商业许可的情况下用于商业用途。但是，如果您及您的关联方按合并口径计算，满足以下任一条件，则应当在继续该等使用前，从 [MinerU Team] 处取得单独的商业许可：

a. 月活跃用户数（MAU）超过 1 亿；或  
b. 月总收入超过 2000 万美元。

**2. 在线服务标识义务**

如果您基于 MinerU 向第三方提供在线服务，您必须在相关产品或服务的操作界面，或对外公开文档的显著位置，清晰明确地标明其使用了 MinerU。

**3. 协议终止**

凡属于依据第 1 条应当取得单独商业许可而未在继续使用前取得的情形，或者未履行第 2 条所述标识义务的，本许可及本许可项下授予您的全部权利将自动终止，且许可方无须另行通知。

**4. 定义**

在本附加条款中，“关联方”是指直接或间接控制您、受您控制，或与您处于共同控制之下的任何法律实体。
“控制”是指通过股权、表决权、合同安排或其他方式，直接或间接决定某一实体管理和经营事项的能力。

Apache License 2.0 全文见：https://www.apache.org/licenses/LICENSE-2.0 。

© 2026 [MinerU Team]
```
- Reason in ledger: Optional parser as isolated service only; extra terms: commercial licence needed above 100M MAU or 20M USD monthly revenue, and mandatory visible attribution if offered as an online service; PLAN assumed AGPL - not so at this commit; bench README still lists AGPL-3.0 for older versions

## apache/tika

- Repository: https://github.com/apache/tika
- Pinned commit: 852451e9fe81135a405fef07044b4173dc3d649e
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: isolated_service
- Copyright:
  - Copyright (c) WHATWG (Apple, Google, Mozilla, Microsoft).
  - Copyright (c) Ian F. Darwin 1986, 1987, 1989, 1990, 1991, 1992, 1994, 1995.
  - Copyright (c) 1995-2009 International Business Machines Corporation
  - Copyright 1993-2010 University Corporation for Atmospheric Research/Unidata
  - Copyright 2012 Ho Thanh Tam, www.cadkit.net
  - Copyright (c) 2009, 2010, 2013-2016 by the Brotli Authors.
  - Copyright (c) 2019 by Matthew Barber.
  - Copyright (C) 2016 Daniel Dreibrodt
- NOTICE (verbatim):

```text
Apache Tika
Copyright 2007-2026 The Apache Software Foundation

This product includes software developed at
The Apache Software Foundation (http://www.apache.org/).

Copyright 1993-2010 University Corporation for Atmospheric Research/Unidata
This software contains code derived from UCAR/Unidata's NetCDF library.

tika-readability is a Java port of Mozilla's Readability.js (https://github.com/mozilla/readability),
licensed under the Apache License 2.0:
  Readability
  Copyright (c) 2010 Arc90 Inc
  Copyright (c) 2010-2026 Mozilla and Contributors

Tika-parsers component uses CDDL/LGPL dual-licensed dependency: jhighlight (https://github.com/codelibs/jhighlight)

IPTC Photo Metadata descriptions Copyright 2010 International Press Telecommunications Council.

Tika-mimetypes.xml includes mimetype definitions that were adapted from the PRONOM Technical Registry
by The National Archives (http://www.nationalarchives.gov.uk/PRONOM/Default.aspx). PRONOM is published
under the Open Government License 3.0 (http://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
```
- Reason in ledger: Alternative unpacker as isolated Java service (S2.5); NOTICE file must ship with any redistribution

## opendataloader-project/opendataloader-bench

- Repository: https://github.com/opendataloader-project/opendataloader-bench
- Pinned commit: 7af1d8f4d0c09f51ea1a5c6ba5f66e993286d109
- SPDX licence: Apache-2.0  (ledger: Apache-2.0 (code); dataset licences not stated in repo (relies on DP-Bench/PubLayNet-style sources))
- Ledger decision: adopt
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- Reason in ledger: Table/structure recovery eval (S5.4); code Apache-2.0; check per-dataset licences before redistributing any gold data (not vendored)

## jsvine/pdfplumber

- Repository: https://github.com/jsvine/pdfplumber
- Pinned commit: 4c64b92d5caccd71c645e98e0fabb0c4dba7ff45
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2015, Jeremy Singer-Vine
- Reason in ledger: Optional backend in om/pdfdoc.py (words, fonts, rulings); already in requirements.txt; keep copyright notice

## pypdfium2-team/pypdfium2

- Repository: https://github.com/pypdfium2-team/pypdfium2
- Pinned commit: ee2be5c705e2cf86c51ffd8b884e6fd99906a931
- SPDX licence: Apache-2.0 OR BSD-3-Clause  (ledger: Apache-2.0 OR BSD-3-Clause (docs CC-BY-4.0); bundles PDFium (BSD-style) and other third-party licences)
- Ledger decision: adopt
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- The wheels bundle PDFium (BSD-style) and other third-party components; ship the wheel's own `*.dist-info/licenses` and bundled third-party licence files. Licence texts at the pinned commit: `LICENSES/Apache-2.0.txt`, `LICENSES/BSD-3-Clause.txt` (code), `LICENSES/CC-BY-4.0.txt` (docs).
- Reason in ledger: Optional raster/bbox backend (D-001); wheels bundle PDFium so ship third-party notices

## pdfminer/pdfminer.six

- Repository: https://github.com/pdfminer/pdfminer.six
- Pinned commit: a18de2a9c479b4c847538500017b449ddaec177e
- SPDX licence: MIT  (ledger: MIT (Yusuke Shinyama licence))
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2004-2016  Yusuke Shinyama <yusuke at shinyama dot jp>
- Reason in ledger: Transitive dependency of pdfplumber; keep copyright notice

## mozilla/pdf.js

- Repository: https://github.com/mozilla/pdf.js
- Pinned commit: 60aefc5b51d526e39bbcbae1c6cb760763b65b0a
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - (none in LICENSE at the pinned commit; Apache-2.0 text only; no NOTICE file at this commit)
- Reason in ledger: Vendored, pinned viewer for split-pane citation inspector (S7.1, D-023); ship LICENSE and NOTICE with vendored files

## dgunning/edgartools

- Repository: https://github.com/dgunning/edgartools
- Pinned commit: 145efc3865f8b0028abf264af33a20d2e8a436e2
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2022-present Dwight Gunning <dgunning@gmail.com>
- Reason in ledger: Primary SEC source next to om/statements.py (S2.5); SEC fair-access rules and SEC_USER_AGENT still apply

## JerBouma/FinanceToolkit

- Repository: https://github.com/JerBouma/FinanceToolkit
- Pinned commit: 245c303efcca5c317c8dcc2fff00d393e1c9ba98
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2025 Jeroen Bouma
- Reason in ledger: Ratio/analysis library fed from edgartools data (S2.5); upstream data providers (e.g. FMP) have their own terms of service, do not redistribute their data

## unclecode/crawl4ai

- Repository: https://github.com/unclecode/crawl4ai
- Pinned commit: cae74b203a33994f7e13b9052c3b0d5c93daa0e6
- SPDX licence: Apache-2.0  (ledger: Apache-2.0 + mandatory attribution clause appended to LICENSE)
- Ledger decision: borrow_ideas
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- Attribution clause appended to LICENSE (verbatim):

```text
Attribution Requirement

All distributions, publications, or public uses of this software, or derivative works based on this software, must include the following attribution:

"This product includes software developed by UncleCode (https://x.com/unclecode) as part of the Crawl4AI project (https://github.com/unclecode/crawl4ai)."

This attribution must be displayed in a prominent and easily accessible location, such as:

-   For software distributions: In a NOTICE file, README file, or equivalent documentation.
-   For publications (research papers, articles, blog posts): In the acknowledgments section or a footnote.
-   For websites/web applications: In an "About" or "Credits" section.
-   For command-line tools: In the help/usage output.

This requirement ensures proper credit is given for the use of Crawl4AI and helps promote the project.

---
```
- Reason in ledger: Web crawling reference; LICENSE appends an Attribution Requirement (text: 'This product includes software developed by UncleCode ... Crawl4AI project') for all distributions and public uses; if adopted put that line in NOTICE/README/About

## anthropics/financial-services

- Repository: https://github.com/anthropics/financial-services
- Pinned commit: 3e32c2287dcb637c184c01cc0ad82d6af7e9bb0f
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: borrow_ideas
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- Reason in ledger: Recipe structure for comps/DCF/LBO/3-statement (S4.3); permissive, but we reimplement in om/ and copy no text; if any file is vendored add NOTICE

## libraz/formulon

- Repository: https://github.com/libraz/formulon
- Pinned commit: 636e32f1158f973b549b7cc6a309959716a444e5
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - Copyright 2026 libraz
- NOTICE (verbatim):

```text
Formulon
Copyright 2026 libraz

This product includes test fixtures derived from IronCalc
(https://github.com/ironcalc/IronCalc), licensed under either
MIT License or Apache License 2.0 at the user's option.
Copyright (c) 2023 EqualTo GmbH, 2023 Nicolas Hatcher.

The fixtures are retained in tests/oracle/external/ironcalc/fixtures/.
License texts are reproduced at tests/oracle/external/ironcalc/.

This product includes data derived from the Unicode Character Database
(Unihan, Unicode 18.0.0: kTotalStrokes), Copyright (c) 1991-2026 Unicode, Inc.,
distributed under the Unicode License v3.

The extracted data is retained in tools/collation/data/unihan_total_strokes.tsv.
The license text is reproduced at tools/collation/data/UNICODE-LICENSE.txt.
```
- Reason in ledger: Independent Excel formula engine for validate_xlsx.py cross-check (S1.3/S4); WASM/pip package; keep NOTICE; evaluate fidelity at teardown

## vals-ai/finance-agent

- Repository: https://github.com/vals-ai/finance-agent
- Pinned commit: 72239d10448c9dc9654f30466372fc932f8b509f
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2025 Vals AI, Inc.
- Reason in ledger: Vals Finance Agent harness/questions for S6.3 (50 public questions); MIT code; check the public question set terms on vals.ai before redistributing

## icip-cas/PPTAgent

- Repository: https://github.com/icip-cas/PPTAgent
- Pinned commit: 9dacac53ac9ef39346461063df729396551d929e
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: borrow_ideas
- Copyright:
  - Copyright (c) 2025 ICIP-CAS
- Reason in ledger: PPTEval rubric and edit-based generation ideas (S3.10); MIT so rubric may be reimplemented with attribution

## scanny/python-pptx

- Repository: https://github.com/scanny/python-pptx
- Pinned commit: 278b47b1dedd5b46ee84c286e77cdfb0bf4594be
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2013 Steve Canny, https://github.com/scanny
- Reason in ledger: Deck writer library for engines/slides and optional extras; keep copyright notice

## fonttools/fonttools

- Repository: https://github.com/fonttools/fonttools
- Pinned commit: 50bef856fccb78de71ada1404f1433503330f1ae
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2017 Just van Rossum
- Reason in ledger: Font metrics for deterministic textfit (optional extra); keep notice

## python-pillow/Pillow

- Repository: https://github.com/python-pillow/Pillow
- Pinned commit: 9139a8f18fa8a32637846fe4a21afc118f509078
- SPDX licence: MIT-CMU  (ledger: MIT-CMU (HPND-style; LICENSE says 'MIT-CMU License'))
- Ledger decision: adopt
- Copyright:
  - Copyright © 1997-2011 by Secret Labs AB
  - Copyright © 1995-2011 by Fredrik Lundh and contributors
  - Copyright © 2010 by Jeffrey 'Alex' Clark and contributors
- Reason in ledger: Image rendering/textfit (optional extra); keep copyright notice

## mpcabd/python-arabic-reshaper

- Repository: https://github.com/mpcabd/python-arabic-reshaper
- Pinned commit: 934ef0898e5bafc59365bf2f299460ddde1f1883
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2019 Abdullah Diab
- Reason in ledger: Arabic shaping for RTL decks (S3); keep notice

## MeirKriheli/python-bidi

- Repository: https://github.com/MeirKriheli/python-bidi
- Pinned commit: 6f301fc339e883d4cb2d2cd6c7fe0d68ab480e5d
- SPDX licence: LGPL-3.0-only  (ledger: LGPL-3.0 (COPYING is GPLv3 base text, COPYING.LESSER adds LGPL; pyproject classifier LGPL))
- Ledger decision: adopt
- Copyright:
  - (none in COPYING / COPYING.LESSER, which are the GNU GPLv3 and LGPLv3 texts; author per installed package metadata: Meir Kriheli)
- Reason in ledger: RTL bidi reordering as an optional pip dependency, imported unmodified and never vendored; LGPL not GPL, but if legal objects replace with own UBA implementation

## duckdb/duckdb

- Repository: https://github.com/duckdb/duckdb
- Pinned commit: 0df17a77c6095760e479eb3851aeddf169fc86d3
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright 2018-2026 Stichting DuckDB Foundation
- Reason in ledger: Matrix storage engine (S5) behind try-import; keep notice

## tesseract-ocr/tesseract

- Repository: https://github.com/tesseract-ocr/tesseract
- Pinned commit: ddcd04239a19d3992ecc443dfa0aa025843a6614
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: isolated_service
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- Reason in ledger: OCR binary in Docker image (S7.5) called as subprocess; Apache-2.0 so redistribution requires LICENSE/NOTICE; traineddata licences also Apache-2.0

## openpyxl/openpyxl

- Repository: https://github.com/openpyxl/openpyxl
- Pinned commit: n/a (Mercurial repo on foss.heptapod.net, not git; no GitHub mirror; PyPI openpyxl 3.1.5)
- SPDX licence: MIT  (ledger: MIT (PyPI metadata; LICENCE file inside sdist not fetched))
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2010 openpyxl (read from LICENCE.rst in the installed openpyxl 3.1.5 distribution; no git commit exists)
- Reason in ledger: Optional cross-check reader for xlsx output; not used in the stdlib core; verify sdist LICENCE file before vendoring

## lucide-icons/lucide

- Repository: https://github.com/lucide-icons/lucide
- Pinned commit: 333574bdecb43e7cb4a4bb1cd21d1367cfbbee2c
- SPDX licence: ISC  (ledger: ISC (portions MIT from Feather))
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2026 Lucide Icons and Contributors
  - Copyright (c) 2013-present Cole Bemis
- Full licence text (verbatim from LICENSE at the pinned commit, with the Feather MIT section):

```text
ISC License

Copyright (c) 2026 Lucide Icons and Contributors

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

---

The following Lucide icons are derived from the Feather project:

airplay, alert-circle, alert-octagon, alert-triangle, aperture, arrow-down-circle, arrow-down-left, arrow-down-right, arrow-down, arrow-left-circle, arrow-left, arrow-right-circle, arrow-right, arrow-up-circle, arrow-up-left, arrow-up-right, arrow-up, at-sign, calendar, cast, check, chevron-down, chevron-left, chevron-right, chevron-up, chevrons-down, chevrons-left, chevrons-right, chevrons-up, circle, clipboard, clock, code, columns, command, compass, corner-down-left, corner-down-right, corner-left-down, corner-left-up, corner-right-down, corner-right-up, corner-up-left, corner-up-right, crosshair, database, divide-circle, divide-square, dollar-sign, download, external-link, feather, frown, hash, headphones, help-circle, info, italic, key, layout, life-buoy, link-2, link, loader, lock, log-in, log-out, maximize, meh, minimize, minimize-2, minus-circle, minus-square, minus, monitor, moon, more-horizontal, more-vertical, move, music, navigation-2, navigation, octagon, pause-circle, percent, plus-circle, plus-square, plus, power, radio, rss, search, server, share, shopping-bag, sidebar, smartphone, smile, square, table-2, tablet, target, terminal, trash-2, trash, triangle, tv, type, upload, x-circle, x-octagon, x-square, x, zoom-in, zoom-out

The MIT License (MIT) (for the icons listed above)

Copyright (c) 2013-present Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
- Reason in ledger: Icons already vendored in reference/meshpool-harness/engines/slides/icons (LICENSE-lucide.txt there is ISC + Feather MIT, 2013-2022 text); keep both notices; upstream commit pinned here is current HEAD, vendored copy predates it

## docling-project/docling-parse

- Repository: https://github.com/docling-project/docling-parse
- Pinned commit: 88f1c3886edea018499f3385619909b96ad06837
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - (LICENSE at the pinned commit is the MIT text with the unfilled template line 'Copyright (c) [year] [fullname]'; no holder named)
- Reason in ledger: S5.1: docling's PDF text/cell backend (transitive, pip docling-parse 7.26.0); keep notice

## docling-project/docling-core

- Repository: https://github.com/docling-project/docling-core
- Pinned commit: a8aa9dce1a80bee78bed991eb18ecbaa11bd6947
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2024 International Business Machines
- Reason in ledger: S5.1: DoclingDocument types with page provenance and bboxes (transitive, pip docling-core 2.107.1); keep notice

## huggingface.co/docling-project/docling-layout-heron

- Repository: https://huggingface.co/docling-project/docling-layout-heron
- Pinned commit: 8f39ad3c0b4c58e9c2d2c84a38465abf757272d8
- SPDX licence: Apache-2.0  (ledger: Apache-2.0 (model card))
- Ledger decision: adopt
- Copyright:
  - (model card declares the licence; no copyright line in the card; weights are downloaded by docling, not vendored)
- Reason in ledger: S5.1: layout model weights docling downloads at first run; UNPINNED WEIGHTS: docling at e16c4b71 requests revision=main (docling/datamodel/layout_model_specs.py:83-85), and the commit here is only the main HEAD read on 2026-11-16; pin before release (mirror the weights or pass an explicit revision); not vendored

## huggingface.co/docling-project/docling-models

- Repository: https://huggingface.co/docling-project/docling-models
- Pinned commit: fc0f2d45e2218ea24bce5045f58a389aed16dc23
- SPDX licence: CDLA-Permissive-2.0 AND Apache-2.0  (ledger: CDLA-Permissive-2.0 + Apache-2.0 (model card))
- Ledger decision: adopt
- Copyright:
  - (model card declares the licence; no copyright line in the card; weights are downloaded by docling, not vendored)
- Reason in ledger: S5.1: TableFormer weights docling downloads at first run; docling at e16c4b71 requests revision tag v2.3.0 (docling/models/stages/table_structure/table_structure_model.py:151), which the HF API resolves to this exact commit, and the model card at that revision declares cdla-permissive-2.0; CDLA-Permissive-2.0 allows commercial use with notice; not vendored; tag is mutable so mirror or pin the SHA before release

## pytorch/pytorch

- Repository: https://github.com/pytorch/pytorch
- Pinned commit: f81a08110bd6524e9770fecf256dead528ef2af3
- SPDX licence: BSD-3-Clause  (ledger: BSD-3-Clause (PyTorch licence))
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2016-     Facebook, Inc            (Adam Paszke)
  - Copyright (c) 2014-     Facebook, Inc            (Soumith Chintala)
  - Copyright (c) 2011-2014 Idiap Research Institute (Ronan Collobert)
  - Copyright (c) 2012-2014 Deepmind Technologies    (Koray Kavukcuoglu)
  - Copyright (c) 2011-2012 NEC Laboratories America (Koray Kavukcuoglu)
  - Copyright (c) 2011-2013 NYU                      (Clement Farabet)
  - Copyright (c) 2006-2010 NEC Laboratories America (Ronan Collobert, Leon Bottou, Iain Melvin, Jason Weston)
  - Copyright (c) 2006      Idiap Research Institute (Samy Bengio)
  - Copyright (c) 2001-2004 Idiap Research Institute (Ronan Collobert, Samy Bengio, Johnny Mariethoz)
  - Copyright (c) 2016-present, Facebook Inc. All rights reserved.
  - Copyright (c) 2016 Facebook Inc.
  - Copyright (c) 2015 Google Inc.
  - Copyright (c) 2015 Yangqing Jia
  - Copyright 2019-2020 Kakao Brain
  - Copyright (c) 2022 Cruise LLC.
  - Copyright (c) 2024 Tri Dao.
  - Copyright (c) 2021, 2023-2025 Arm Limited and/or its affiliates
  - Copyright(c) 2013, 2014, 2015, the respective contributors
  - Copyright(c) 2015, 2016 the respective contributors
- NOTICE: the pinned commit's NOTICE file lists third_party submodule notices; it ships with the PyTorch wheel and must be kept with any image containing torch. Source: https://github.com/pytorch/pytorch/blob/f81a08110bd6524e9770fecf256dead528ef2af3/NOTICE
- Reason in ledger: S5.1: transitive runtime of docling layout/table models (CPU wheel 2.15.0); optional extra only

## huggingface/transformers

- Repository: (internal, in-repo)
- Pinned commit: 36e937ae761dea806a5b9fbb382e880378ad5435
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - Copyright 2018- The Hugging Face team. All rights reserved.
- Reason in ledger: S5.1: transitive runtime of docling layout model (pip 5.23.0); optional extra only

## psycopg/psycopg

- Repository: https://github.com/psycopg/psycopg
- Pinned commit: bced8a8993064a378d5ca852215d99f73f4c6cae
- SPDX licence: LGPL-3.0-only  (ledger: LGPL-3.0)
- Ledger decision: adopt
- Copyright:
  - (none in LICENSE.txt, which is the GNU LGPL-3.0 text; no holder named in the file)
- Reason in ledger: Optional Postgres driver imported dynamically inside a try/except in om/storage.py (open_analytics Postgres DSN path) and scripts/verify_m1.py; unmodified, never vendored; NOT declared in requirements.txt or requirements-extras.txt (users install it separately with pip), so it must stay a replaceable pip install (no one-file bundle or frozen image that blocks substitution) and ship the LGPL-3.0 text with an offer of source; LICENSE.txt is LGPL-3.0 at this commit

## py-pdf/pypdf

- Repository: https://github.com/py-pdf/pypdf
- Pinned commit: d81502d8871e22b4fb03089d03f5f421829ea600
- SPDX licence: BSD-3-Clause  (ledger: BSD-3-Clause)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2006-2008, Mathieu Fenniak
  - Some contributions copyright (c) 2007, Ashish Kulkarni <kulkarni.ashish@gmail.com>
  - Some contributions copyright (c) 2014, Steve Witham <switham_github@mac-guyver.com>
- Reason in ledger: Optional pure-Python PDF text reader, try-import fallback in om/extract.py when poppler is absent; unmodified; LICENSE at this commit is the BSD 3-clause text (Mathieu Fenniak et al.)

## facebook/react (react@18.3.1)

- Repository: https://github.com/facebook/react
- Pinned commit: a87edf62d7d69705ddbcec9a24f0780b3db7535f
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) Meta Platforms, Inc. and affiliates.
- Reason in ledger: Product UI framework (frontend/, D-029, D-SF-02); react and react-dom pinned 18.3.1

## remix-run/react-router (react-router-dom@6.28.0)

- Repository: https://github.com/remix-run/react-router
- Pinned commit: 365fefc90b861c51a1a9008df5aa035f2d7dc165
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) React Training LLC 2015-2019
  - Copyright (c) Remix Software Inc. 2020-2021
  - Copyright (c) Shopify Inc. 2022-2023
- Reason in ledger: Client-side routing for the product app (frontend/, D-SF-02)

## vitejs/vite (vite@5.4.11)

- Repository: https://github.com/vitejs/vite
- Pinned commit: c54c860f9d90e4074e5321648f9c5ee9fbda7038
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2019-present, VoidZero Inc. and Vite contributors
- Reason in ledger: Build tool for frontend/ (dev dependency only; nothing ships at runtime) (D-SF-02)

## vitejs/vite-plugin-react (@vitejs/plugin-react@4.3.4)

- Repository: https://github.com/vitejs/vite-plugin-react
- Pinned commit: 2e368a65aaf8314142538c369c296e277fdfb69b
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2019-present, Yuxi (Evan) You and Vite contributors
- Reason in ledger: Vite React plugin, dev dependency only (D-SF-02)

## microsoft/TypeScript (typescript@5.6.3)

- Repository: https://github.com/microsoft/TypeScript
- Pinned commit: d48a5cf89a62a62d6c6ed53ffa18f070d9458b85
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- Reason in ledger: Type checker/compiler for frontend/, dev dependency only (D-SF-02)

## mozilla/pdf.js (pdfjs-dist@4.10.38)

- Repository: https://github.com/mozilla/pdf.js
- Pinned commit: f9bea397f817100a186d0ced2aa3d4b85813b637
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - (none in LICENSE at the pinned commit; Apache-2.0 text only; no NOTICE file at this commit)
- Reason in ledger: npm build of pdf.js for the split-pane citation inspector (S7.1, P-J6); bundled into frontend/dist with its LICENSE (D-SF-02)

## microsoft/playwright (@playwright/test@1.63.0)

- Repository: https://github.com/microsoft/playwright
- Pinned commit: 1b025d7e20a026371cd5f98ba0cdce48892737c8
- SPDX licence: Apache-2.0  (ledger: Apache-2.0)
- Ledger decision: adopt
- Copyright:
  - (no copyright line in the LICENSE file at the pinned commit)
- NOTICE (verbatim):

```text
Playwright
Copyright (c) Microsoft Corporation

This software contains code derived from the Puppeteer project (https://github.com/puppeteer/puppeteer),
available under the Apache 2.0 license (https://github.com/puppeteer/puppeteer/blob/master/LICENSE).
```
- Reason in ledger: End-to-end journey tests P-J1..P-J8 (e2e/), dev/test only; version matches the preinstalled browsers (D-SF-02)

## fontsource/font-files (@fontsource/inter@5.1.0; @fontsource/ibm-plex-sans-arabic@5.1.0)

- Repository: https://github.com/fontsource/font-files
- Pinned commit: bbd47cd9ccc1541e520a3dc9b58e24e415006197
- SPDX licence: OFL-1.1  (ledger: OFL-1.1)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2023 fontsource
- Fonts are distributed under the SIL Open Font License 1.1 (OFL-1.1); each packaged font keeps its upstream copyright and reserved font name in its package LICENSE. The font-files repository LICENSE (MIT) above covers the packaging.
- Reason in ledger: Self-hosted UI fonts (Latin + Arabic); OFL permits bundling with software; no CDN calls (CSP self only) (D-SF-02)

## fontsource/font-files (@fontsource/jetbrains-mono@5.1.1)

- Repository: https://github.com/fontsource/font-files
- Pinned commit: d8712d5a35b03982fc499ba52529897aa7b2e833
- SPDX licence: OFL-1.1  (ledger: OFL-1.1)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2023 fontsource
- Fonts are distributed under the SIL Open Font License 1.1 (OFL-1.1); each packaged font keeps its upstream copyright and reserved font name in its package LICENSE. The font-files repository LICENSE (MIT) above covers the packaging.
- Reason in ledger: Monospace for cell refs, formulas and IDs in the product UI (D-SF-02)

## lxml/lxml

- Repository: https://github.com/lxml/lxml
- Pinned commit: 74e94856b8385b16e845c834087b038438c2ceb7
- SPDX licence: BSD-3-Clause  (ledger: BSD-3-Clause)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2004 Infrae. All rights reserved.
- Reason in ledger: XML/OOXML parsing for deck sync, render, validate and house_clone (om/deck/sync.py, om/deck/render.py, om/deck/validate.py, om/deck/house_clone.py); optional extra, unmodified; keep notice

## yaml/pyyaml

- Repository: https://github.com/yaml/pyyaml
- Pinned commit: f5e4504a92f169f65350a1047dccb23bc97028be
- SPDX licence: MIT  (ledger: MIT)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2017-2021 Ingy döt Net
  - Copyright (c) 2006-2016 Kirill Simonov
- Reason in ledger: Deck spec YAML loading via safe_load only (om/deck/spec.py); optional extra with graceful fallback; keep notice

## jmcnamara/XlsxWriter

- Repository: https://github.com/jmcnamara/XlsxWriter
- Pinned commit: e943bee8c9cdf0661cfdb83d5497e0725390e41e
- SPDX licence: BSD-2-Clause  (ledger: BSD-2-Clause)
- Ledger decision: adopt
- Copyright:
  - Copyright (c) 2013-2025, John McNamara <jmcnamara@cpan.org>
- Reason in ledger: Declared in requirements.txt (XlsxWriter==3.2.9, matches tag RELEASE_3.2.9) as python-pptx's chart-workbook dependency; no direct import in om/, src/ or scripts/ (grep xlsxwriter finds only requirements.txt), it is used inside om/deck chart embedding via pptx.chart; LICENSE.txt at the pinned commit is BSD 2-Clause (Copyright (c) 2013-2025 John McNamara); keep notice

