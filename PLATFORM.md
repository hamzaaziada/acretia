# Platform plan: research, matrix and model agent on open data

The goal is one tool that covers what bankers and investors use three products for today, built on open-source parts and legally reusable data. Every answer, cell and number links back to the source document it came from.

| Capability | Benchmark product | What we build |
|---|---|---|
| Search and monitor documents | AlphaSense | Hybrid keyword + semantic search over filings, transcripts, broker PDFs and news, with saved searches, alerts and topic and sentiment tracking |
| Ask questions across many documents | Hebbia (Matrix) | A grid of documents × questions. An agent answers each cell with a citation to the exact page and passage, then exports to Excel |
| Build models | Shortcut | An AI spreadsheet agent that writes real formulas, pulls live data from our API (`=OM.FIELD("AAPL","ev_ebitda_ltm")`), and builds comps, precedents and DCF/LBO templates |
| Data | Multiples / CapIQ | **acretia**: fundamentals, multiples, M&A precedents, funding rounds and a taxonomy, all from filings |

## Architecture

```
            ┌──────────── Web app (Next.js) ─────────────┐   Excel add-in (Office.js)   MCP server
            │  Search · Matrix · Sheets · Comps · Alerts │          │                     │
            └───────────────┬────────────────────────────┘          │                     │
                            ▼                                       ▼                     ▼
                     API (FastAPI, OpenAPI)  ◄─────────────── same endpoints ─────────────┘
          ┌─────────────┬──────────┴──────────┬───────────────────┬─────────────────┐
          ▼             ▼                     ▼                   ▼                 ▼
   Search service   Matrix agent        Sheet agent          Data API          Alert engine
   (hybrid index)   (cell workers)      (formula planner)   (acretia)   (saved queries)
          │             │                     │                   │
          └──────┬──────┴─────────┬───────────┘                   │
                 ▼                ▼                               ▼
        Document store      LLM gateway (Claude;            Postgres (facts, deals,
        (S3 + Postgres,     provider-agnostic, JSON         entities) + DuckDB/Parquet
        pgvector/OpenSearch) schemas, citation spans)        (history)
                 ▲
     Ingestion (Dagster): EDGAR, IR sites, broker PDFs, news RSS, user uploads → parse → chunk → embed
```

## Open-source building blocks

| Layer | Default choice | Notes |
|---|---|---|
| Ingestion and orchestration | Dagster | Schedules, retries, lineage |
| PDF and HTML parsing | Docling, PyMuPDF, pdfplumber, plus our `htmltables` | A VLM fallback for scanned or complex tables |
| Search index | OpenSearch (BM25) + pgvector or Qdrant | Hybrid retrieval, then reranking |
| Embeddings and reranker | bge-m3 / e5 (multilingual, so Arabic works), bge-reranker | Self-hosted |
| LLM | Claude via a gateway | Structured output, citations, tool use |
| Spreadsheet UI | Univer (Apache-2.0) | Excel-like grid with a formula engine. Avoid GPL engines in a closed product |
| Excel | Office.js custom functions | `=OM.FIELD()`, `=OM.SERIES()`, `=OM.PRECEDENTS()` |
| Backend | FastAPI, Postgres, Redis | Auth, rate limits, change feed |
| Frontend | Next.js + shadcn/ui | |

## Content sources (legal reuse)

| Content | Source | Status |
|---|---|---|
| Filings (10-K/Q, 8-K, proxies, S-4, 20-F) | SEC EDGAR | Done for fundamentals and M&A |
| EU/UK annual reports | filings.xbrl.org, Companies House | Planned |
| Earnings call transcripts | **No free licensed source.** Options: transcribe company-hosted webcasts for internal use, or license from a vendor. Republishing third-party transcripts is not allowed | Decision needed |
| Broker research | Open MENA broker PDFs (QNB FS, Al Rajhi and others). Store facts plus a link, never re-host | Planned |
| News | Publisher RSS plus links; store facts and summaries, not articles | Planned |
| User uploads | CIMs, data rooms, models: private to the workspace | Planned |

## Phases

1. **Data layer:** fundamentals and M&A precedents are done. Form D rounds and a monthly history are next.
2. **Document search:** done for EDGAR (FTS5 keyword search, sections, facets, trends, saved searches and alerts, web UI). Semantic re-ranking is next.
3. **Matrix:** done (cited answers, a quote-verification check, incremental columns, CSV export, web UI). It has an extractive engine that needs no API key and a Claude engine for when a key is added.
3c. **Sheets:** done. The formula engine, data functions (`OM`, `MATRIX`), templates built to banking conventions (comps, precedents, DCF, LBO) and .xlsx export are built. The Sheets agent is done: plain-English edits, server-side plan validation, scratch-copy calculation with up to two self-repair rounds, preview with Apply/Discard, and slash commands that need no model. It is routed on the `sheets_agent` stage.
3d. **Model-agnostic AI:** done. A provider router (Claude SDK plus any OpenAI-compatible API including DeepSeek) with per-stage models, schema validation and repair, and model-independent grounding.
3b. **Data rooms (VDRs):** done. Upload files, folders or VDR ZIP exports; parse PDF, Office, HTML and email with page citations; connectors for Box, SharePoint/OneDrive, Dropbox and synced folders; room-scoped Search and Matrix. Next: authentication and users, OCR for scanned PDFs, and Google Drive.
3e. **Slides:** done. Native, editable PowerPoint for comps, company profiles, DCF valuation (football field, sensitivity, method-divergence check), funding-market updates and Ask answers; exported from Sheets, Funding Rounds and Ask, or `deck` on the command line.
3g. **Deck Studio:** done (needs model keys to run). Storyboard as a partner or MD → per-slide prompts asking for strong visuals → image model drafts → reviewer or human approval loop → vision slides engine rebuilds each approved image as native, editable PowerPoint → correctness review loop (render vs image, numbers vs storyboard) → .pptx plus consistency check.
3f. **Consistency check:** done. Decks, workbooks and data rooms: cross-slide and cross-document conflicts, totals and medians, prose arithmetic, margin and growth math, bridges, SEC tie-out, error cells and failing checks. Rules first; an optional model stage (`check`) adds grounded extraction and reviews each mismatch.
4. **Sheets agent:** a Univer grid plus an agent that plans models, writes formulas against our API, and explains each cell.
5. **Monitoring:** saved searches, alerts on new filings, guidance changes and deal announcements.
6. **Excel add-in and MCP server.**
7. **MENA and EU coverage**, and the broker-PDF street-estimates layer.

## Principles

- Every number and answer carries provenance: the document, page or accession number, and the text span.
- Forward estimates are labelled by source (`guidance`, `street`, `model`, `licensed`).
- No data from multiples.vc or other vendors' databases in the pipeline. Paid inputs (prices, transcripts, estimates) go through explicit licences.
