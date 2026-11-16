# Time-saved baselines and competitor claims (researched 2026-11-16)

This is the input to the time-saved benchmark (`eval/tsb/`, PLAN.md "North-star metrics", D-032). It holds two things:

- **Human baselines (`T_h`)** per task, with source and source type.
- **What competitors claim**, so that we only claim parity or better when our own measurements support it.

Labels: [independent] (third-party test), [vendor], [customer] (self-reported), [anecdote]. Rows marked **(snippet)** were seen only in search results. Re-verify them before quoting anything externally.

## 1. What competitors claim

| Who | Claim (paraphrased) | Metric | Type | Method | Source |
|---|---|---|---|---|---|
| Rogo | Users save about 400 hrs/yr (about 10 hrs/week) | hrs/week/user | [vendor] (snippet, pre-Felix) | none stated | https://rogo.ai/news/rogo-series-a-with-khosla-ventures |
| Rogo / Baird | Top-10 power users save 5+ hrs/day; output is "85% of the way there" | hrs/day; % complete | [vendor]/[customer] | power-user subset, self-report | https://rogo.com/customers/baird-investment-banking |
| Rogo / Harbor View | 1–2 weeks saved per CIM | weeks per CIM | [vendor] (snippet) | none | https://rogo.ai/customers/harbor-view |
| Hebbia | 5–10 hrs/week per user (Fortune 100 customer) | hrs/week/user | [vendor] (snippet) | none | https://hebbia.com/industry/corporate |
| Hebbia (OpenAI page) | Bankers 30–40 hrs per deal; PE 20–30 hrs per deal | hrs/deal | [vendor] (snippet) | none | https://openai.com/index/hebbia |
| Hebbia (Anthropic case study) | "95%" is a **prompt-caching latency** figure, not analyst time | latency | [vendor] | none | https://claude.com/customers/hebbia |
| Daloopa | 2 hrs saved per ticker per earnings update (elsewhere 15–45 min per model: inconsistent); >99% accuracy | hrs/ticker | [vendor] | none | https://daloopa.com/?p=14833 |
| Daloopa | Model build: 2 days–1 week+ by hand vs 45–60 min; 50–70% saved | hrs, % | [vendor] | step estimates | https://daloopa.com/use-cases/building-models |
| Shortcut | Preferred over first-year McKinsey/Goldman analysts in 89.1% of 247 blind pairwise comparisons; humans had time caps (DCF 90 min, M&A 90, LBO 50) | win rate | [vendor] | blind grading, n=247 | https://shortcut.ai/blog/posts/analyst-benchmark |
| AlphaSense | Diligence information gathering 50–75% faster; a 6-hr task in 1 hr | % | [customer] (snippet) | none | https://www.alpha-sense.com/resources/case-studies/asset-manager-boosts-analyst-productivity/ |
| Brightwave | 3–5 associate hrs → under 30 min; data rooms to memos "in hours" | hrs | [vendor] (snippet) | none | https://www.brightwave.io/enterprise-pricing |
| Model ML | Qualitative only; no quantified claim found | — | [customer] | — | https://www.modelml.com/customers/investment-banking |
| Wall Street Prep | Apple 3-statement model, scored /10: Shortcut 5.9, Claude 5.5, Copilot 4.4, ChatGPT 2.5, vs analysts 9.4 / 7.9 / 6.4; tools took 15–60 min, analysts 1–3 hrs; every tool scored 0 on circularity | score, minutes | **[independent]** | one task, first attempt | https://wallstreetprep.com/knowledge/ranking-the-best-ai-tools-for-financial-modeling-2026 |
| Ankura | 5 tools built "structurally complete" models in 7–10 min; none production-ready | minutes | **[independent]** | single pass | https://ankura.com/insights/putting-ai-to-the-test-how-5-tools-performed-across-3-financial-models |
| BankerToolBench (ICLR 2026) | 502 bankers rated **0%** of a frontier model's outputs client-ready; the best model fails about half the rubric criteria; human time up to 21 hrs per task | pass rate | **[independent]** | 502 bankers, 100+ criteria | https://arxiv.org/abs/2604.11304 |
| Vals Finance Agent v2 | Best models about 58%; under strict scoring all below 46% | accuracy | **[independent]** | public leaderboard | https://www.vals.ai/benchmarks/fabv2 |

**Takeaway:** no competitor publishes an audited hours-saved figure. The headline numbers to match or beat are about **10 hrs/week per user** (Rogo) and **30–40 hrs per deal** (Hebbia), both unaudited. The independent bar is harsh: 0% client-ready (BankerToolBench), and every tool below a weak analyst (WSP). Time-saved claims that leave out rework time overstate savings.

## 2. Human baselines (`T_h`) per catalogue task

| Task | Baseline range | Best source available | Confidence |
|---|---|---|---|
| 3-statement model from a 10-K | 2–3 hrs (strong analyst, standard company); 8–20 hrs for an arbitrary company's first model | WSP [independent]; WSO [anecdote] | medium |
| DCF | ~90 min | Shortcut time cap [vendor] | low |
| LBO (full) | 8–12 hrs experienced associate; 1–4 hrs in a modelling test | NYIF, WSP/BIWS [training firms] | medium |
| LBO (paper) | 5–15 min | CFI [training firm] | medium (interview test, not real work) |
| Merger accretion/dilution | 30–60 min simple; 3–6 hrs first pass | BIWS [training firm] (snippet); [anecdote] | low |
| Trading comps refresh | ~2 hrs per company per quarter; 4–8 hrs of manual filing pulls per new model | Shortcut / Daloopa [vendor] | low |
| Precedent transactions table | 6–10 hrs (attribution unverified) | [vendor blog] | very low |
| Data-room first-pass review (per 50 docs) | 20–30 hrs (at ~0.4–0.6 hr per doc) | [vendor] | low |
| Earnings model update (per ticker) | 15 min–2 hrs | Daloopa [vendor] (inconsistent) | low |
| IC memo first draft | 4–15 hrs (12–15 hrs senior associate in one case study) | [vendor] | low |
| CIM production | 1–2 weeks of saved time claimed | Rogo [vendor] | low |
| Complex end-to-end IB task | up to 21 hrs | BankerToolBench [independent] | medium |
| Company profile / one-pager, pitchbook page, teaser, buyer list, earnings recap | **no credible figure found** | — | none: needs our own timing |

## 3. How we measure, so our claim beats theirs

The weakness everywhere: no method, self-report, power-user subsets, generation time without rework, and metric slippage.

Our claim must state all of the following:
- the task definition;
- the baseline source and analyst seniority;
- `n`;
- a **blind** grading rubric (graded by personas now, real senior reviewers in the pilot);
- **review-and-rework time included**;
- the **error rate**, reported separately from speed;
- a client-ready pass rate, counted separately from "good first draft".

Steps:
1. **Now:**
   - instrumented `T_a` from the job telemetry;
   - review time estimated from the persona "edits needed" lists × a minutes-per-edit table (in `eval/tsb/`, with cited sources);
   - baselines from §2.
2. **Pilot:** 3–5 analysts on pre-registered tasks using their own documents, timing paired with and without Acretia, grading blind.
3. **Our own timing study** for the tasks with no credible baseline: profile, pitchbook page, teaser, buyer list, earnings recap.
4. **External benchmarks** in the scorecard:
   - BankerToolBench, where tasks are public;
   - Vals Finance Agent v2;
   - the WSP 3-statement task (Apple), the same prompt run through our engine.

**Target for parity:**
- per-task savings at or above the competitor claim for that task category;
- a per-user weekly figure of ≥ 10 hrs measured in the pilot;
- a client-ready rate well above the independent results (BankerToolBench 0%, WSP below a weak analyst).
