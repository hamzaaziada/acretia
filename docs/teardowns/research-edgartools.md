# Teardown: edgartools (dgunning/edgartools)

repo: https://github.com/dgunning/edgartools
commit: 145efc3865f8b0028abf264af33a20d2e8a436e2
licence: MIT (`LICENSE.txt`, "Copyright (c) 2022-present Dwight Gunning"; `edgar/__about__.py` SPDX header `MIT`)
ran: yes (PyPI `edgartools` 6.2.0 plus the `[ai]` extra, which installed `mcp` 1.30.0, in a venv; identity set through `EDGAR_IDENTITY="Acretia hamza@meshpool.ai"` for SEC requests only; local data dir in the scratchpad; the clone HEAD may be newer than 6.2.0)

## Test 1: pull AAPL's latest 10-K financials

- [OBSERVATION] `Company("AAPL").get_filings(form="10-K").latest()` returned accession `0000320193-26-000026`, filed 2026-11-03, period 2026-09-26. `filing.obj().financials` exposes `income_statement()`, `balance_sheet()`, `cash_flow_statement()`, `comprehensive_income()`, `statement_of_equity()` and helper getters (`get_revenue`, `get_net_income`, `get_operating_cash_flow`, `get_total_assets`, `get_free_cash_flow`, ...). Whole run including download: 2.1 s.
- [OBSERVATION] Values: revenue 478,834,000,000; net income 132,175,000,000; operating cash flow 145,097,000,000; total assets 404,548,000,000 (fiscal 2026). They equal the values in our cached SEC companyfacts (`data/raw/sec/companyfacts/CIK0000320193.json.gz`: Revenue 478,834,000,000 FY2026 form 10-K, NetIncomeLoss 132,175,000,000, Assets 404,548,000,000). The income statement frame has 77 rows with columns for three fiscal years, XBRL concept names, labels, standard concept names, dimension members (iPhone, Products...), and balance/weight/sign attributes.
- [OBSERVATION] `company.get_facts()` returned in 0.7 s; each `FinancialFact` carries `concept`, `value`, `unit`, `fiscal_year`, `fiscal_period`, `period_end`, `filing_date`, `form_type`, `accession`, `dimensions`, `confidence_score`, `data_quality`, `is_audited`. That is the provenance Acretia's evidence bundle needs (accession plus filing date plus period) without extra lookups.
- [OBSERVATION] A to_dataframe path can be mis-keyed: `fact.to_dataframe()` returned `None` for a single `FinancialFact` and statement frames used `"2026-09-26"` or `"2026-09-26 (FY)"` column names depending on the method, so parsing needs a normaliser.

## Test 2: MCP server

- [OBSERVATION] Yes, it ships an MCP server: console script `edgartools-mcp = "edgar.ai.mcp.server:main"` (`pyproject.toml:140-142`), optional extra `ai` pins `mcp>=1.28.1,<2.0.0` (with an explanatory comment that mcp 2.0 removed the decorator API, `pyproject.toml:80-86`). Source under `edgar/ai/mcp/` with one module per tool.
- [OBSERVATION] I spoke MCP over stdio with the official `mcp` client: `initialize` returned server `edgartools 6.2.0`; `tools/list` returned 13 tools: `edgar_company`, `edgar_search`, `edgar_filing`, `edgar_read`, `edgar_compare`, `edgar_ownership`, `edgar_monitor`, `edgar_trends`, `edgar_screen`, `edgar_text_search`, `edgar_fund`, `edgar_proxy`, `edgar_notes`.
- [OBSERVATION] `edgar_company {"identifier":"AAPL"}` returned `success: true` JSON (27,146 characters) with profile (SIC 3571, shares outstanding 14,532,182,000, public float 3,647,099,000,000) and a rendered income statement. `edgar_trends {"identifier":"AAPL","concepts":["revenue","net_income"],"periods":3}` returned revenue 478,834,000,000 / 416,161,000,000 / 391,035,000,000 with growth 15.1 percent / 6.4 percent and a 10.7 percent CAGR. The first call with a wrong argument name (`metric`) returned a structured error with suggestions rather than crashing.
- [OBSERVATION] The trend values carry only `value` and `period`; no accession number or filing date in the tool output, so the harness router must add provenance itself (for example by also calling `edgar_filing`, or wrapping `Company.get_facts()` directly in Python where `accession` and `filing_date` are available).
- [OBSERVATION] Tool descriptions begin "Use this for ..." and answers are JSON with `success`, `data`, `suggestions`, which suits a router. Dependencies at runtime include `httpxthrottlecache` and `truststore`; SEC rate limiting is handled in the library (`pyproject.toml` comment lines 70-75).
- [INFERENCE] Within Acretia use the Python API through the harness router (typed facts with accession, as-of and form), and treat the MCP server as an optional external entry point, not a core dependency; the in-process path avoids a second process and keeps provenance.
- [UNKNOWN] Behaviour under SEC's 10 requests per second limit with parallel Matrix and research agents (I made a few requests, well under 5 per second); behaviour on filings with restated or custom XBRL (not tested beyond AAPL); the `[ai]` extra's extra packages (`tiktoken`, `starlette`, `uvicorn`) in a hardened image.

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt as an optional extra (MIT, pinned wheel) for SEC filings, XBRL facts and statements in S4.3, S5.3 and S6.1, always through the harness router with accession, filing date and as-of recorded in the evidence bundle. Keep our own `om.sec` client as the offline fallback and cross-check (the values matched exactly), and treat the 13-tool MCP server as an optional external interface.
