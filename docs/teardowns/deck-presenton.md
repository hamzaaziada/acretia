# Teardown: presenton/presenton

repo: https://github.com/presenton/presenton
commit: 9af2b47dda31060d3d5070e020a0825b15c94b32
licence: Apache License (LICENSE:2, "Apache License / Version 2.0")
ran: no (the product needs an LLM provider key and a Next.js + FastAPI stack with a headless browser export, 233 .tsx files and a 552 MB checkout; none of the three briefs could be generated without a model; no template-only render path exists outside the web app). Only static reading of templates and server code was done.

## Findings

- [OBSERVATION] Architecture: two servers, servers/fastapi (generation, documents, export tasks, MCP server mcp_server.py, SQL migrations) and servers/nextjs (React UI and slide editor), shipped as Docker or Electron (README.md; docker-compose.yml). All slide layouts are React/TSX components rendered in a browser; a Next.js export route exists at servers/nextjs/app/api/export-presentation/route.ts; the FastAPI side imports python-pptx only in templates/pptx_font_utils.py and templates/fonts_and_slides_preview.py (grep), so the exact DOM-to-PPTX path was not traced.
- [OBSERVATION] Template inventory: 16 template folders under templates/ (civic, dynamic, editorial, executive, general, horizon, landmark, modern, momentum, mosaic ...), each with template.json holding id, description, layouts, fonts and theme; 383 layout entries across the 16 files; layouts.json at the root has 14 layouts with descriptions and per-component descriptions (e.g. "business_proposal_cover_layout", "annual_earnings_slide_layout", "strategy_slide_layout").
- [OBSERVATION] The LLM chooses a layout id and fills a typed schema per layout (servers/fastapi/templates/v2/schema.py, generation.py, certified_generation.py), so the model does not place coordinates: closest to the S3.2 contract among the products, with a "certified generation" variant.
- [OBSERVATION] Text-fit: a font utility with fontTools (templates/pptx_font_utils.py:1-15 imports TTFont, zipfile, XML) handles font embedding and theme font mapping for imported decks; no glyph-measurement fit loop was found in the Python search (no whole-word autofit hit in services). Overflow is handled in the browser by CSS.
- [OBSERVATION] Charts use Chart.js in the editor (servers/nextjs/components/slide-editor/charts/TemplateV2ChartJsElement.tsx) and recharts (servers/nextjs/package.json:64) via components/ui/chart.tsx, so exported charts depend on how the export maps them; native OOXML chart export was not verified.
- [OBSERVATION] Custom-template cloning from an uploaded PPTX is a headline feature (README "Create an AI-ready PowerPoint template from your PPTX"; templates/cloning.py).
- [OBSERVATION] RTL: no whole-word rtl or bidi hit in servers/nextjs/app or servers/fastapi/templates.
- [INFERENCE] The layout-id-plus-typed-schema contract and per-layout descriptions are the pattern S3.2 wants, and layouts.json shows how to describe archetypes to a model compactly. The HTML-to-PPTX export inherits the shape-built chart problem seen with PPTAgent. The stack is too heavy to adopt (Node, Docker, DB) for a standard-library core.
- [UNKNOWN] Real output quality of any template; PPTX export fidelity; whether charts are native in the exported file. These need a keyed run, so they remain unmeasured.

## Adopt / borrow ideas / skip

Borrow ideas (Apache-2.0): layout catalogue with machine-readable descriptions for model selection; template cloning from an uploaded PPTX (S3.9); "certified generation" as a precedent for schema-validated fills. Skip the codebase.
