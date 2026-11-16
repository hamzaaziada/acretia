# Teardown: gpt-researcher (assafelovic/gpt-researcher)

repo: https://github.com/assafelovic/gpt-researcher
commit: ddd4db36208d9c8e49f3b2436efda97baecb5433
licence: Apache-2.0 (`LICENSE`, unmodified Apache text)
ran: partial (no LLM or search keys exist in this environment. Installed PyPI `gpt-researcher` 0.17.0 in a venv with `OPENAI_API_KEY` unset, imported it, and rendered its prompt templates offline; read the planner, conductor, curator, deep-research, report-prompt and multi-agent code in the clone, `pyproject.toml` version 0.17.0. The retrieval, scraping, embedding and LLM steps were not executed)

## Structure (file:line in the clone)

- [OBSERVATION] Planner: `ResearchConductor.plan_research(query, ...)` at `gpt_researcher/skills/researcher.py:86` first fetches initial search results, then calls `plan_research_outline(query, search_results, agent_role_prompt, cfg, report_type, retriever_names)` (`gpt_researcher/actions/query_processing.py:158`) which asks the LLM for sub-queries; each planned sub-query is emitted as a `query_planned` event (`researcher.py:114-119`).
- [OBSERVATION] Conductor: `conduct_research` (`researcher.py:121`) loops over sub-queries; `_process_sub_query` (`:544`) searches, scrapes, compresses to relevant context; helpers for URLs (`:269`), vector store (`:289`), web (`:322`) and MCP (`:434-516`, `:689`). `visited_urls` is deliberately shared with sub-researchers so URLs are not fetched twice (comment at `researcher.py:132-135`).
- [OBSERVATION] Context compression: embedding-based `ContextCompressor` and `WrittenContentCompressor` in `gpt_researcher/context/compression.py:48,98,148` (needs an embedding provider and key).
- [OBSERVATION] Source curation: `SourceCurator.curate_sources(source_data, max_results=10)` ranks sources by credibility and relevance with an LLM (`gpt_researcher/skills/curator.py:38`, prompt at `gpt_researcher/prompts.py:319`).
- [OBSERVATION] Deep research: a breadth x depth tree (`DeepResearchSkill`, defaults breadth 4, depth 2, concurrency 2 at `gpt_researcher/skills/deep_research.py:257-263`); `deep_research(query, breadth, depth, learnings, citations, visited_urls)` accumulates `learnings` and a `citations` dict per branch (`deep_research.py:396-420`), with `ResearchProgress` state (`:246-254`).
- [OBSERVATION] State kept: `research_sources` (list of scraped sources with title, content, images; `gpt_researcher/agent.py:156`), `visited_urls` (`:166`), accessors `get_research_sources` / `add_research_sources` (`:694,702`). No hash chain, no as-of date per source, no quoted passage.
- [OBSERVATION] Report writer: `generate_report_prompt` (`gpt_researcher/prompts.py:262-300`) asks for a "detailed report ... at least {total_words} words", APA references, "You MUST write all used source urls at the end of the report" and markdown hyperlinks. The rendered prompt (offline run) is 2,257 characters and contains the instruction "Use in-text citation references in apa format and make it with markdown hyperlink ...". Search-query prompt (`prompts.py:213`) rendered at 556 characters and instructs the model to "Assume the current date is November 16, 2026" and return a JSON list of plain-language queries.
- [OBSERVATION] Multi-agent variant (`multi_agents/agents/orchestrator.py:66-90`, LangGraph `StateGraph`): nodes `browser` -> `planner` -> `human` (plan review) -> `researcher` (parallel) -> `writer` -> `fact_checker` -> `visualizer` -> `publisher`. The fact checker (`multi_agents/agents/fact_checker.py:10-33`) sends the full draft to one LLM call with a "diligent Fact Checker Agent" system prompt; it does not recheck against stored sources.
- [OBSERVATION] Retrievers: default `RETRIEVER: "tavily"` (`gpt_researcher/config/variables/default.py:4`), so the default path needs a Tavily key plus an LLM key. `ReportSource` enum covers web, local documents, hybrid (`gpt_researcher/utils/enum.py:30-38`). `evals/` holds `hallucination_eval`, `quality_eval`, `simple_evals`, `context_filter`. `mcp-server/` in the repo is only a README.
- [OBSERVATION] Offline run: `PromptFamily.generate_search_queries_prompt(...)` and `generate_report_prompt(question, "ctx", "web")` rendered with no keys; importing the package pulled a large LangChain dependency set into the venv.

## Fit for S6.1 and S6.2

- [INFERENCE] Reusable: the sub-query planner pattern, the shared `visited_urls` set, source curation, and the breadth/depth tree with per-branch `learnings` and `citations` (that tree maps well onto "gather evidence facts for a deck").
- [INFERENCE] Conflicts with PLAN section 0 and S6.2: the writer produces free prose, web search by default, and URL-level citation with no quote, page, bbox or as-of date; S6.2 allows only SlideSpecs and Excel input payloads and rejects any figure without a verifiable source and as-of date. The writer, publisher and fact-checker nodes would have to be replaced by a structured emitter that fills `{figure, source_id, quote, page, as_of}` rows through the harness router.
- [INFERENCE] As the S6.1 "base" the dependency weight and its default web-first assumption make a vendored fork heavier than a small planner that reuses the router; Apache-2.0 allows either route.
- [UNKNOWN] Quality, cost and latency of a real run on a finance question (needs keys); the repo's `evals/` score on a finance set; how `query_domains` restricts retrieval to SEC and IR domains in practice.

## Adopt / borrow ideas / isolated service / skip for Acretia

Borrow ideas (planner prompt and sub-query fan-out, source curator, breadth/depth learnings with a citations map, URL de-duplication). Do not adopt the package as the runtime: its output contract (prose plus URLs) is the opposite of S6.2, and a fork would have to rewrite the writer, curator and fact-check nodes around the evidence bundle.
