# Teardown: FinanceToolkit (JerBouma/FinanceToolkit)

repo: https://github.com/JerBouma/FinanceToolkit
commit: 245c303efcca5c317c8dcc2fff00d393e1c9ba98
licence: MIT (`LICENSE.txt`, "Copyright (c) 2025 Jeroen Bouma")
ran: yes (PyPI `financetoolkit` 2.3.4 with the `[mcp]` extra in a venv, plus `edgartools`; no FMP key; ran keyless Toolkit, custom-statement input built from edgartools data, and the local MCP server over stdio)

## Test 1: can it run without an FMP key, or on edgartools/SEC data?

- [OBSERVATION] Keyless default: `Toolkit(["AAPL"], enforce_source="YahooFinance")` returned a 41-row income statement with Revenue 478,834,000,000 for fiscal 2026 (2.3 s). Without a key and without a statement, the toolkit falls back to Yahoo Finance (README line 88: "automatically switches to Yahoo Finance as a secondary source"). Forcing `enforce_source="FinancialModelingPrep"` without a key raised `ValueError: Please input an API key from FinancialModelingPrep...`. Yahoo Finance was contacted from this session during the test only (`curl` to `query1.finance.yahoo.com` returned 200).
- [INFERENCE] The Yahoo fallback is an unofficial data path with no SLA or licence for redistribution and sits outside the host list in `DECISIONS.md`; production use must be gated or disabled.
- [OBSERVATION] SEC data can replace it. `Toolkit.__init__` accepts `balance`, `income`, `cash`, `historical` DataFrames and a `format_location` for custom normalisation (`financetoolkit/toolkit_controller.py:165-169,222-230`); supplied statements are used as given "and never replaced by downloaded ones" (`:564-567` comment). The expected shape is a two-level index (ticker, line item) with years as columns: passing a flat frame raised `ValueError: The income statement needs two index levels: the ticker and the line item, e.g. ('AAPL', 'Total Assets')`.
- [OBSERVATION] I built an income frame from edgartools' AAPL 10-K (mapping `Net sales` to `Revenue`, `Cost of sales` to `Cost of Goods Sold`, `Gross margin` to `Gross Profit`, `Operating income`, `Net income`; `pd.concat({"AAPL": frame})`) and `Toolkit(["AAPL"], income=frame, benchmark_ticker=None).get_income_statement()` returned it unchanged: Revenue 391,035,000,000 / 416,161,000,000 / 478,834,000,000 for 2024 to 2026, Gross Profit 233,602,000,000 for 2026, Net Income 132,175,000,000. No network call was needed for that statement. The line-item names must match FinanceToolkit's generic names (`financetoolkit/normalization/income.csv`, for example `revenue -> Revenue`), so a mapping table is required for ratios to compute.
- [UNKNOWN] Whether the ratio families (`ratios`, `models` DuPont/Altman/WACC/DCF) run fully offline on custom statements plus custom prices; the toolkit also wants price history for valuation ratios, which I did not supply, and `historical` has its own required shape. Not tested.

## Test 2: MCP server

- [OBSERVATION] Local server: console script `financetoolkit-mcp` (`pyproject.toml:75`); extra `mcp` pulls `fastmcp>=3.4.2` and `mcp[cli]` (`pyproject.toml:59-62`). Run over stdio it initialised as "Finance Toolkit Analyst 2.3.4" and listed 28 tools: 25 router tools (efficiency, liquidity, profitability, solvency, valuation, breadth, momentum, overlap, volatility, models, performance, risk, econometrics, etf, portfolio, portfolio_performance, options, government, macroeconomics, environment, jobs, rates, fixed_income, discovery, market_data) and 3 search utilities (`search_metric_categories`, `search_by_category`, `search_metrics`). Each router tool takes `indicator` (an enum such as `get_gross_margin`), `tickers`, `start_date`, `end_date`, `quarterly`, `growth`, `lag`, `trailing`, `show_columns`, `limit`.
- [OBSERVATION] Without a key, `profitability {"indicator":"get_gross_margin","tickers":["AAPL"]}` returned (not an error flag, a message) "A FinancialModelingPrep API key is required for this tool. Local setup: set FINANCIAL_MODELING_PREP_API_KEY ... Hosted setup: sign in on the server's authorization page ..." So the MCP path does not use the Yahoo fallback and offers no way to pass custom statements (the router tool schema has no `balance`/`income`/`cash` parameters).
- [OBSERVATION] A hosted server exists at `https://financetoolkit.jeroenbouma.com/mcp` using OAuth to collect the user's FMP key (README lines 543-545). Using it would send tickers and keys to a third-party host, which `CLAUDE.md` forbids unless listed in `DECISIONS.md`.
- [INFERENCE] The MCP server is a thin wrapper over the Python toolkit; for Acretia the useful surface is the Python library (ratio and model formulas over our own statements), called in-process with SEC-derived frames.
- [UNKNOWN] Formula parity of FinanceToolkit's ratios (for example margins, ROIC, WACC) against our `om.statements` definitions; the README Q&A section describes deviations from other sources but I did not diff definitions.
- [UNKNOWN] Licence terms of FMP data (a paid vendor) if a key is later used: separate from the MIT code.

## Adopt / borrow ideas / isolated service / skip for Acretia

Borrow ideas and optionally adopt the library for formula coverage (MIT; ratios, DuPont, WACC) fed with SEC data through its `income`/`balance`/`cash` arguments, with a documented name-mapping table and the Yahoo fallback disabled. Skip the hosted MCP server and the local MCP server (key required; no custom-statement input).
