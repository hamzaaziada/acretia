"""The built-in agent catalogue: 14 catalogue tasks (D-032) plus the editing agents and the diligence grid.

Each task has a stable `task_id` (used by the time-saved benchmark), ordered steps (id, title, engine, fn) and a
`review_minutes_estimate`: how long a reviewer should budget to check and fix the output before it is client-ready.
Step `fn` names are registered in `agents.engines.STEP_FNS`.
"""
from __future__ import annotations

TASK_IDS_14 = ("comps", "precedents", "three_statement", "dcf", "lbo", "merger", "vdr_review", "profile",
               "pitchbook_section", "teaser", "ic_memo", "earnings_update", "earnings_recap", "buyer_list")
EXTRA_TASKS = ("deck_edit", "model_edit", "diligence_grid", "tick_and_tie")


def S(fn, title, engine, seconds=3.0, tokens=0):
    return {"fn": fn, "title": title, "engine": engine, "seconds": seconds, "tokens": tokens}


_RESOLVE = S("resolve", "Resolve the company and its filings", "om.sec")
_STATEMENTS = S("statements", "Spread the financial statements from the filings", "om.statements")
_CHECK = S("check_model", "Grade the workbook (balance, checks, formula hygiene)", "om.modelcheck")
_DELIVER = S("deliver", "Save to the deal library", "om.deals")
_APPROVE = S("approve_outline", "Approve the storyline", "om.deck.ghost")
_SOURCES = ["SEC EDGAR company facts (XBRL)", "Deal documents"]

CATALOGUE: dict[str, dict] = {
    "comps": {
        "name": "Trading comps",
        "description": "Spread trading comparables for a target against its peer set: EV/EBITDA, EV/revenue, P/E, margins and growth, "
                       "with quartile statistics and every input traced to the filings. Add 'football field' for the valuation summary.",
        "tags": ["valuation", "excel", "comps"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}, {"name": "peers", "type": "list[string]"}],
        "steps": [_RESOLVE, _STATEMENTS, S("peers", "Gather the peer filings", "om.sec"),
                  S("build_comps", "Build the comps workbook", "om.comps", 6), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 20, "requires": ["om.comps"],
    },
    "precedents": {
        "name": "Precedent transactions",
        "description": "Build a precedent transactions table from announced deals: date, target, acquirer, EV, EV/EBITDA and EV/revenue, each sourced to the deal filing.",
        "tags": ["valuation", "excel", "m&a"],
        "inputs": [{"name": "sector", "type": "string"}, {"name": "ticker", "type": "string"}],
        "steps": [_RESOLVE, S("build_precedents", "Assemble precedent transactions", "om.precedents", 8), _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 45, "requires": ["om.precedents"],
    },
    "three_statement": {
        "name": "Integrated three-statement model",
        "description": "Income statement, balance sheet and cash flow built from the latest filings with a revolver, interest circularity, "
                       "scenarios and a Checks tab. Every historical number is a blue input traced to its XBRL concept.",
        "tags": ["modelling", "excel", "three-statement"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}, {"name": "years", "type": "int"}],
        "steps": [_RESOLVE, _STATEMENTS, S("build_three_statement", "Build the integrated model", "om.model3", 5), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 15, "requires": ["om.model3"],
    },
    "dcf": {
        "name": "DCF valuation",
        "description": "Unlevered DCF on a tied three-statement model: CAPM WACC, perpetuity-growth and exit-multiple terminal values, "
                       "cross-checks and sensitivity tables. Override with '9% WACC' or 'terminal growth 2.5%'.",
        "tags": ["valuation", "excel", "dcf"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}, {"name": "wacc", "type": "percent"},
                   {"name": "terminal_growth", "type": "percent"}],
        "steps": [_RESOLVE, _STATEMENTS, S("build_dcf", "Build the model and DCF", "om.model3", 5), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 15, "requires": ["om.model3"],
    },
    "lbo": {
        "name": "LBO model",
        "description": "Sponsor returns model: sources and uses, TLB/senior notes/PIK, cash sweep, exit and IRR/MOIC sensitivities on the target's filings.",
        "tags": ["valuation", "excel", "lbo", "private equity"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}, {"name": "premium", "type": "percent"}],
        "steps": [_RESOLVE, _STATEMENTS, S("build_lbo", "Build the LBO", "om.lbo", 5), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 30, "requires": ["om.lbo"],
    },
    "merger": {
        "name": "Merger model (accretion / dilution)",
        "description": "Acquirer and target combined: purchase price, financing mix, synergies, pro forma EPS accretion/dilution and sensitivities.",
        "tags": ["valuation", "excel", "m&a"],
        "inputs": [{"name": "ticker", "type": "string", "required": True, "label": "acquirer"}, {"name": "target", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("counterparty", "Resolve the target's filings", "om.sec"),
                  S("build_merger", "Build the merger model", "om.merger", 6), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 30, "requires": ["om.merger"],
    },
    "vdr_review": {
        "name": "Data-room first-pass review",
        "description": "First pass over a CIM or virtual data room: missing documents against the checklist, period gaps, red flags and conflicting "
                       "figures across documents, each finding quoted to its page.",
        "tags": ["diligence", "data room"],
        "inputs": [{"name": "deal_id", "type": "string", "required": True}],
        "steps": [S("load_documents", "Load the deal's documents", "om.api.documents"),
                  S("vdr_scan", "Scan for gaps, red flags and conflicts", "om.vdr_risk", 6), _DELIVER],
        "outputs": ["json"], "review_minutes_estimate": 90, "requires": ["om.vdr_risk"],
    },
    "profile": {
        "name": "Company profile",
        "description": "One-page company profile deck: growth, margins, cash generation and balance sheet from the filings, with action titles you approve first.",
        "tags": ["deck", "profile"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("deck_outline", "Draft the storyline", "om.deck.ghost"), _APPROVE,
                  S("deck_render", "Render and validate the deck", "om.deck", 6), _DELIVER],
        "outputs": ["pptx"], "review_minutes_estimate": 25, "requires": ["om.deck"],
    },
    "pitchbook_section": {
        "name": "Pitchbook section",
        "description": "A pitchbook section on the company's financial profile: chart-led slides with action titles, sources and validator badges.",
        "tags": ["deck", "pitchbook"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("deck_outline", "Draft the storyline", "om.deck.ghost"), _APPROVE,
                  S("deck_render", "Render and validate the deck", "om.deck", 6), _DELIVER],
        "outputs": ["pptx"], "review_minutes_estimate": 35, "requires": ["om.deck"],
    },
    "teaser": {
        "name": "Teaser",
        "description": "A short anonymised-style teaser deck: investment highlights and key financials from the filings.",
        "tags": ["deck", "sell-side"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("deck_outline", "Draft the storyline", "om.deck.ghost"), _APPROVE,
                  S("deck_render", "Render and validate the deck", "om.deck", 5), _DELIVER],
        "outputs": ["pptx"], "review_minutes_estimate": 25, "requires": ["om.deck"],
    },
    "ic_memo": {
        "name": "IC memo first draft",
        "description": "Investment committee memo first draft: situation, financial profile, valuation view and key risks, drafted from the spread filings.",
        "tags": ["memo", "private equity"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("prose_memo", "Draft the memo", "adapter", 8, 2500), _DELIVER],
        "outputs": ["docx"], "review_minutes_estimate": 60, "requires": [],
    },
    "earnings_update": {
        "name": "Earnings model roll-forward",
        "description": "Roll the existing model forward for the latest reported period: new actuals in, your assumptions kept, changes listed.",
        "tags": ["modelling", "excel", "earnings"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("prior_model", "Find the model to roll forward", "om.deals"),
                  S("roll_forward", "Roll the model forward", "om.rollforward", 5), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 10, "requires": ["om.rollforward"],
    },
    "earnings_recap": {
        "name": "Earnings recap",
        "description": "A one-page recap of the latest reported results against the prior year: growth, margin and cash flow, with the sources.",
        "tags": ["memo", "earnings"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("prose_recap", "Draft the recap", "adapter", 6, 1500), _DELIVER],
        "outputs": ["docx"], "review_minutes_estimate": 20, "requires": [],
    },
    "buyer_list": {
        "name": "Buyer list",
        "description": "Strategic and sponsor buyer universe with the rationale for each, drafted for review.",
        "tags": ["memo", "sell-side", "m&a"],
        "inputs": [{"name": "ticker", "type": "string", "required": True}],
        "steps": [_RESOLVE, _STATEMENTS, S("prose_buyers", "Draft the buyer universe", "adapter", 8, 2000), _DELIVER],
        "outputs": ["docx"], "review_minutes_estimate": 40, "requires": [],
    },
    # ---------------------------------------------------------------- editing and diligence helpers
    "deck_edit": {
        "name": "Edit a deck",
        "description": "Apply a change to an existing deck, such as retitling a slide, and save it as a new version you can diff or undo.",
        "tags": ["deck", "edit"],
        "inputs": [{"name": "deck", "type": "string"}, {"name": "edits", "type": "list"}],
        "steps": [S("load_deck", "Open the deck", "om.deals"), S("edit_deck", "Apply the edit", "om.deck", 3),
                  S("validate_deck", "Validate the deck", "om.deck.validate"), _DELIVER],
        "outputs": ["pptx"], "review_minutes_estimate": 5, "requires": [],
    },
    "model_edit": {
        "name": "Edit a model",
        "description": "Change assumptions in an existing workbook (for example WACC), recalculate every dependent cell and save a new version.",
        "tags": ["modelling", "excel", "edit"],
        "inputs": [{"name": "model", "type": "string"}, {"name": "changes", "type": "object"}],
        "steps": [S("load_model", "Open the model", "om.deals"), S("edit_model", "Apply and recalculate", "om.wbedit", 3), _CHECK, _DELIVER],
        "outputs": ["xlsx"], "review_minutes_estimate": 5, "requires": [],
    },
    "diligence_grid": {
        "name": "Diligence grid",
        "description": "Ask the same questions of every document in the deal and get a grid of quoted answers with page references.",
        "tags": ["diligence", "grid"],
        "inputs": [{"name": "questions", "type": "list[string]"}],
        "steps": [S("load_documents", "Load the deal's documents", "om.api.documents"),
                  S("grid_answer", "Answer each question per document", "om.matrix", 5), _DELIVER],
        "outputs": ["json"], "review_minutes_estimate": 30, "requires": [],
    },
    "tick_and_tie": {
        "name": "Tick and tie",
        "description": "Cross-check the numbers across the deal's decks and models: conflicting figures, unit mix-ups and broken sums.",
        "tags": ["qa", "diligence"],
        "inputs": [],
        "steps": [S("load_deliverables", "Collect the deal's decks and models", "om.deals"),
                  S("tie_out", "Tie every figure out", "om.consistency", 4), _DELIVER],
        "outputs": ["json"], "review_minutes_estimate": 10, "requires": [],
    },
}

# optional output asks usable on any valuation task (planner turns them into an extra step)
OUTPUT_STEPS = {
    "football_field": S("football_field", "Football field (DCF range)", "om.deck", 4),
}

# "/" skills: slash name -> task_id or output ask
SKILLS = {
    "comps": "comps", "trading-comps": "comps", "precedents": "precedents", "dcf": "dcf", "lbo": "lbo", "merger": "merger",
    "three-statement": "three_statement", "model": "three_statement", "3-statement": "three_statement",
    "profile": "profile", "one-pager": "profile", "pitchbook": "pitchbook_section", "teaser": "teaser",
    "ic-memo": "ic_memo", "memo": "ic_memo", "recap": "earnings_recap", "earnings-recap": "earnings_recap",
    "earnings": "earnings_update", "roll-forward": "earnings_update", "buyers": "buyer_list", "buyer-list": "buyer_list",
    "vdr": "vdr_review", "data-room": "vdr_review", "grid": "diligence_grid", "tick-tie": "tick_and_tie", "tick-and-tie": "tick_and_tie",
    "edit-deck": "deck_edit", "edit-model": "model_edit",
    "football-field": "output:football_field", "football": "output:football_field",
}


def task(task_id: str) -> dict:
    return CATALOGUE[task_id]


def builtin_id(task_id: str) -> str:
    return f"agt_builtin_{task_id}"


def task_of_builtin(agent_id: str) -> str | None:
    if agent_id and agent_id.startswith("agt_builtin_") and agent_id[len("agt_builtin_"):] in CATALOGUE:
        return agent_id[len("agt_builtin_"):]
    return None
