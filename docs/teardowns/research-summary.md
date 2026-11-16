# Summary: research-agent and data-source teardowns for S4.3, S6.1, S6.2

repo: n/a (summary of research-gpt-researcher.md, research-dexter.md, research-finrobot.md, research-edgartools.md, research-financetoolkit.md)
commit: n/a (gpt-researcher ddd4db36208d9c8e49f3b2436efda97baecb5433, dexter 534f6be455523c5926eba72bdaf4f914555be5c9, FinRobot 63e1884a42ea7b729551a5424b4bd6a65af636e0, edgartools 145efc3865f8b0028abf264af33a20d2e8a436e2, FinanceToolkit 245c303efcca5c317c8dcc2fff00d393e1c9ba98)
licence: n/a (gpt-researcher Apache-2.0; dexter MIT per README only, no LICENSE file; FinRobot Apache-2.0 plus trademark policy; edgartools MIT; FinanceToolkit MIT)
ran: partial (edgartools and FinanceToolkit ran fully, including their MCP servers over stdio; gpt-researcher, dexter and FinRobot ran only their offline parts because no LLM keys exist here)

## Comparison

| | gpt-researcher | dexter | FinRobot | edgartools | FinanceToolkit |
|---|---|---|---|---|---|
| role | web research agent | finance ReAct agent | equity-research pipeline | SEC data library | ratios and models library |
| ran | partial (prompts rendered offline) | partial (317 tests pass, real Scratchpad driven) | partial (grounding audit executed) | yes | yes |
| key needed | LLM plus Tavily | LLM plus financialdatasets.ai | LLM plus FMP/Finnhub | none (SEC user agent only) | FMP for the MCP; none for custom statements |
| output | prose plus URL list | prose answer | opinion report | typed facts with accession | DataFrames |
| MCP | none in repo | none | none | yes, 13 tools | yes, 28 tools, key required |
| decision | borrow ideas | borrow ideas | borrow ideas | adopt (optional extra) | adopt library, skip MCP |

- [OBSERVATION] Only edgartools could supply a verifiable figure end to end: its AAPL FY2026 revenue (478,834,000,000), net income (132,175,000,000) and total assets (404,548,000,000) equalled our cached SEC companyfacts, and each `FinancialFact` carries accession, filing date, period end and form.
- [OBSERVATION] edgartools' MCP trend output carries only value and period, with no accession or filing date, so provenance must be added in the router or taken from the Python API.
- [OBSERVATION] FinanceToolkit runs offline on SEC-derived statements through its `income`, `balance` and `cash` arguments (two-level ticker and line-item index), but its keyless default falls back to Yahoo Finance and its MCP server refuses without an FMP key.
- [OBSERVATION] None of the three agents emits what S6.2 requires. gpt-researcher writes prose with URLs only; dexter's scratchpad logs tool, args, result and timestamp but no source id or as-of; FinRobot's numeric-grounding audit accepts any digit.
- [OBSERVATION] PLAN S6.1 credits dexter with "task planning with self-reflection"; at the pinned commit only the JSONL scratchpad and soft tool-call limits exist, and dexter has no LICENSE file.
- [INFERENCE] The best reusable parts are small patterns, not packages: gpt-researcher's sub-query planner, shared visited-URL set and breadth/depth learnings with a citations map; dexter's append-only scratchpad and soft call limits; FinRobot's step contract (validator, `deterministic`, `critical`, degrade markers) and compute-versus-narrative split.
- [UNKNOWN] Live quality, cost and latency of all three agents on finance questions; needs keys supplied by the user (D-021).

## Recommendation for S6

1. Build a small Python research loop on the harness router: planner step, then tool calls (edgartools, FinanceToolkit on SEC frames, crawl4ai, Matrix, Excel daemon), each appending to the hash-chained evidence bundle with source id, as-of, page and bbox.
2. Replace the writer with a structured emitter producing only SlideSpecs and Excel payloads; every figure row needs `{value, source_id, quote, page, as_of}` and is rejected otherwise. Keep a deterministic grounding check stricter than FinRobot's (a number must match a logged fact).
3. Borrow from gpt-researcher (planner, URL de-dup, curator), dexter (scratchpad, soft limits with similarity warnings) and FinRobot (step flags, degrade semantics). Copy no code from dexter.
4. Use edgartools as the SEC source through the Python API; keep `om.sec` as offline cross-check. Disable FinanceToolkit's Yahoo fallback.

## Adopt / borrow ideas / isolated service / skip for Acretia

Adopt edgartools (optional extra) and the FinanceToolkit library on SEC data; borrow ideas from gpt-researcher, dexter and FinRobot; skip all three agents as runtimes and both MCP servers as core dependencies.
