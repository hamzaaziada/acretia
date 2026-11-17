"""Corpus decks 01-06 (synthetic data; project names are fictional)."""
from evals.decks._lib import S, make_brief

SYN = "(synthetic)"


def d01():
    t = "Project Harbor: investment committee update"
    sl = [
        S("cover", t, {"client": "Investment Committee, Fund IV", "date": "7 October 2026"},
          visual=("stacked container cranes over a calm harbour, abstract and flat", "hero"), sec="Answer"),
        S("exec_summary", "Harbor clears our 20% IRR hurdle at 11.0x entry, with a 22.4% base case",
          {"subtitle": "Recommendation and key terms, $ million", "insights": [
              {"lead": "Price", "text": "Entry at 11.0x FY25E EBITDA of $96.0m sets the enterprise value", "figure": "$1,056m"},
              {"lead": "Returns", "text": "Gross IRR in the base case clears the 20% fund hurdle over a five-year hold", "figure": "22.4%"},
              {"lead": "Growth", "text": "EBITDA rises on price and cost savings, ahead of input-cost inflation", "figure": "+17%"},
              {"lead": "Risk", "text": "Top-3 customer renewals are the open diligence item before the bid", "figure": "31%"}],
           "so_what": {"text": "Approve a final bid of up to $1,090m EV at the 6 November deadline."}},
          src=("Sponsor model v14 (synthetic)", "Management case, Aug 2026 (synthetic)"), sec="Answer"),
        S("kpi_row", "LTM performance supports the plan: revenue up 11%, EBITDA margin up 150 bps to 17.1%",
          {"subtitle": "LTM to 30 September 2026, $ million", "highlight": 1, "kpis": [
              {"label": "LTM revenue", "value": "$561m", "context": "+11% YoY, price led", "change": {"text": "up on FY24", "direction": "up"}},
              {"label": "LTM EBITDA", "value": "$96.0m", "context": "+17% YoY, volume $9.5m", "change": {"text": "up on FY24", "direction": "up"}},
              {"label": "EBITDA margin", "value": "17.1%", "context": "+150 bps, savings 70% done", "change": {"text": "up on FY24", "direction": "up"}},
              {"label": "Net leverage at close", "value": "6.5x", "context": "Peers at 7.2x", "change": {"text": "-0.7x", "direction": "up"}}],
           "so_what": "Growth is price-led: volume adds $9.5m, below the three-year average of $11.2m."},
          src="Company financials and QoE draft, Sep 2026 (synthetic)", sec="Performance"),
        S("waterfall", "EBITDA rises 17% to $96.0m as price and savings outweigh input-cost inflation",
          {"subtitle": "EBITDA bridge, FY24 to FY25E, $ million", "number_format": "0.0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "FY24 EBITDA", "value": 82.0}, {"label": "Volume", "value": 9.5}, {"label": "Price", "value": 6.0},
                     {"label": "Input costs", "value": -4.5}, {"label": "Cost savings", "value": 5.0},
                     {"label": "Opex inflation", "value": -2.0}, {"label": "FY25E EBITDA", "value": 96.0}],
           "takeaway": "Volume adds $9.5m and price $6.0m; input costs take back $4.5m"},
          src=("Sponsor model v14 (synthetic)", "Management EBITDA bridge (synthetic)"), sec="Performance"),
        S("sensitivity_table", "Returns hold above 20% IRR at 11.0x entry across all three exit multiples",
          {"subtitle": "Gross IRR by entry and exit multiple, %", "row_label": "Entry multiple, x", "col_label": "Exit multiple, hurdle 20%",
           "row_values": [10.5, 11.0, 11.5], "col_values": [10.0, 11.0, 12.0],
           "values": [[22.9, 25.1, 27.0], [20.4, 22.4, 24.3], [18.2, 20.1, 21.9]], "base": [1, 1],
           "takeaway": "Only the 11.5x entry with a 10.0x exit falls below the hurdle"},
          src=("Sponsor model v14, base operating case (synthetic)",), sec="Returns"),
        S("annotated_line", "Net leverage falls from 6.5x at close to 3.1x by FY30E on free cash flow",
          {"subtitle": "Net debt to EBITDA, x", "number_format": "0.0", "change_unit": "x",
           "categories": ["Close", "FY26E", "FY27E", "FY28E", "FY29E", "FY30E"],
           "series": [{"name": "Total net leverage", "values": [6.5, 5.7, 4.9, 4.1, 3.5, 3.1]},
                      {"name": "Senior only", "values": [5.5, 4.8, 4.1, 3.4, 2.9, 2.5]}],
           "annotation": {"at": 2, "text": "Second lien refinanced in FY27E"},
           "takeaway": "Total leverage reaches 3.1x by FY30E from 6.5x at close"},
          src=("Sponsor model v14, debt schedule (synthetic)",), sec="Returns"),
        S("doughnut_split", "EBITDA growth drives 61% of value creation, deleveraging 27% and multiple 12%",
          {"subtitle": "Sources of equity value creation, % of total gain", "centre": "$832m",
           "slices": [{"label": "EBITDA growth", "value": 61, "key": True}, {"label": "Deleveraging", "value": 27},
                      {"label": "Multiple", "value": 12}],
           "takeaway": "Multiple expansion is only 12% of the gain, so returns do not rely on re-rating"},
          src=("Sponsor model v14, returns attribution (synthetic)",), sec="Returns"),
        S("risk_heatmap", "Two of five risks need confirmatory diligence before the 6 November final bid",
          {"subtitle": "Risk register, likelihood by impact, five-point scale", "risks": [
              {"label": "Top-3 renewals, 31% of revenue, $11m EBITDA", "likelihood": 3, "impact": 5},
              {"label": "Q4 price pass-through, $3m EBITDA", "likelihood": 3, "impact": 3},
              {"label": "Input costs above 4% inflation", "likelihood": 4, "impact": 3},
              {"label": "Management retention", "likelihood": 2, "impact": 4},
              {"label": "Second-lien refinancing in FY27E", "likelihood": 2, "impact": 3}],
           "takeaway": "Customer renewals carry the largest exposure at $11m of EBITDA if lost"},
          src=("Diligence tracker, 28 Sep 2026 (synthetic)",), sec="Risks"),
        S("timeline_milestones", "We need IC approval today to hold the 6 November final-bid date",
          {"subtitle": "Process timetable to signing, 2026", "milestones": [
              {"date": "7 Oct", "label": "IC approval", "highlight": True}, {"date": "16 Oct", "label": "Top-3 customer calls"},
              {"date": "30 Oct", "label": "Confirmatory QoE"}, {"date": "6 Nov", "label": "Final bid up to $1,090m EV", "highlight": True},
              {"date": "Dec", "label": "Signing"}], "takeaway": "Final bid of up to $1,090m EV follows IC approval on 7 Oct"},
          src=("Process letter, 12 Sep 2026 (synthetic)",), sec="Next steps"),
        S("takeaway_box", "We ask IC to approve a final bid of up to $1,090m EV today",
          {"decision": "Approve a final bid of up to $1,090m EV, with a base case of 2.8x MOIC and 22.4% gross IRR",
           "rationale": ["Returns: base case clears the 20% hurdle at 11.0x entry", "Plan: EBITDA of $96.0m is 70% savings and price led",
                         "Structure: 5.5x senior plus 1.0x second lien"],
           "risks": ["Concentration: 31% of revenue from three customers", "Pass-through: $3m of EBITDA at risk in Q4"]},
          src="Sponsor model v14 (synthetic)", sec="Next steps"),
    ]
    req = ("Draft a 10-slide Investment Committee update for Project Harbor, a mid-market LBO. Answer first: we want approval "
           "to submit a final bid of up to $1,090m EV. Cover LTM performance, the EBITDA bridge, an IRR sensitivity, "
           "deleveraging, value creation sources, the risk register and the timetable to the 6 November final bid. Synthetic data.")
    return make_brief("d01-lbo-ic-update", t, req, sl, client="Investment Committee, Fund IV", as_of="2026-09-30")


def d02():
    t = "Northwind Industrial: public comps and valuation summary"
    peers = [("Alder Machinery", 4.82, 9.9, 15.8, 6.1, 21.2), ("Brightwater Systems", 3.15, 9.6, 14.9, 4.8, 19.8),
             ("Cobalt Controls", 5.94, 10.7, 17.2, 7.4, 22.5), ("Delta Fluid Power", 2.21, 8.9, 13.4, 3.2, 17.9),
             ("Ember Components", 1.76, 9.1, 14.1, 5.5, 18.6), ("Fulcrum Industrial", 3.88, 10.8, 16.5, 6.9, 20.4),
             ("Granite Automation", 2.64, 8.3, 12.7, 2.9, 16.8), ("Halyard Tooling", 1.31, 9.4, 13.8, 4.1, 19.1)]
    rows = [{"company": n, "ev": ev, "ev_ebitda": m, "pe": pe, "growth": g, "margin": mg} for n, ev, m, pe, g, mg in peers]
    sl = [
        S("cover", t, {"client": "Board of Directors", "date": "30 October 2026"},
          visual=("overlapping gear forms in muted blues, flat editorial", "hero"), sec="Answer"),
        S("exec_summary", "Triangulated enterprise value is $912m to $980m, or 9.5x to 10.2x FY26E EBITDA",
          {"subtitle": "Valuation summary, $ million", "insights": [
              {"lead": "Range", "text": "Four methods overlap in one enterprise value band", "figure": "$912m to $980m"},
              {"lead": "Multiple", "text": "The band equals this multiple of FY26E EBITDA of $96.0m", "figure": "9.5x to 10.2x"},
              {"lead": "Discount", "text": "Northwind trades below the peer median multiple of 9.5x", "figure": "9.1x"},
              {"lead": "Cause", "text": "The gap reflects a lower EBITDA margin, not lower growth", "figure": "17.1%"}],
           "so_what": {"text": "Anchor the board discussion on the overlap of the four methods."}},
          src=("FactSet consensus, 30 Oct 2026 (synthetic)", "Sponsor valuation model (synthetic)"), sec="Answer"),
        S("comps_table", "Peers trade at a median 9.5x EV/EBITDA, and Northwind sits at 9.1x",
          {"subtitle": "Trading comparables, FY26E multiples, EV in $ billion", "compute_stats": True, "dense": True, "rows": rows,
           "takeaway": "Median EV/EBITDA is 9.5x across eight industrial peers"},
          src=("FactSet consensus, 30 Oct 2026 (synthetic)", "Company filings (synthetic)"), sec="Trading comps"),
        S("ranked_bar", "Northwind trades at 9.1x, sixth of nine peers and level with Ember",
          {"subtitle": "EV/EBITDA, FY26E, x", "number_format": "0.0\"x\"", "series_name": "EV/EBITDA", "items": [
              {"label": "Fulcrum Industrial", "value": 10.8}, {"label": "Cobalt Controls", "value": 10.7},
              {"label": "Alder Machinery", "value": 9.9}, {"label": "Brightwater Systems", "value": 9.6},
              {"label": "Halyard Tooling", "value": 9.4}, {"label": "Northwind", "value": 9.1, "key": True},
              {"label": "Ember Components", "value": 9.1}, {"label": "Delta Fluid Power", "value": 8.9},
              {"label": "Granite Automation", "value": 8.3}],
           "stat": {"value": "-0.4x", "label": "discount to the peer median of 9.5x"},
           "takeaway": "Closing the gap to the median is worth 0.4x of EBITDA"},
          src=("FactSet consensus, 30 Oct 2026 (synthetic)",), sec="Trading comps"),
        S("scatter_quadrant", "Northwind's 2.4-point margin gap, not growth, explains its discount to peers",
          {"subtitle": "EBITDA margin versus revenue growth, FY26E, %", "x_title": "Revenue growth, FY26E, %", "y_title": "EBITDA margin, FY26E, %",
           "x_format": "0.0", "y_format": "0.0", "points": [{"label": "Northwind", "xv": 5.0, "yv": 17.1, "subject": True}] +
           [{"label": n.split()[0], "xv": g, "yv": mg} for n, _, _, _, g, mg in peers],
           "stat": {"value": "-2.4pp", "label": "EBITDA margin gap to the peer median of 19.5%"},
           "takeaway": "Growth of 5.0% is in line with peers, so margin is the lever"},
          src=("FactSet consensus, 30 Oct 2026 (synthetic)",), sec="Trading comps"),
        S("tombstones", "Precedents cleared 9.5x to 11.4x LTM EBITDA, with strategic buyers at the top",
          {"subtitle": "Precedent transactions, EV in $ billion, EV/EBITDA LTM", "deals": [
              {"acquirer": "Alder Machinery", "target": "Kestrel Valves", "date": "Mar 2026", "ev": 1.24, "multiple": 11.2},
              {"acquirer": "Sponsor consortium", "target": "Larch Pumps", "date": "Jan 2026", "ev": 0.88, "multiple": 9.6},
              {"acquirer": "Cobalt Controls", "target": "Maple Drives", "date": "Nov 2025", "ev": 1.51, "multiple": 11.4},
              {"acquirer": "Sponsor consortium", "target": "Nettle Sensors", "date": "Aug 2025", "ev": 0.72, "multiple": 9.5},
              {"acquirer": "Fulcrum Industrial", "target": "Oak Gears", "date": "May 2025", "ev": 0.96, "multiple": 10.4},
              {"acquirer": "Sponsor consortium", "target": "Pine Hydraulics", "date": "Feb 2025", "ev": 0.64, "multiple": 9.9}],
           "takeaway": "Strategic buyers paid 10.4x to 11.4x; financial buyers paid 9.5x to 9.9x"},
          src=("Company announcements (synthetic)", "Deal database extract (synthetic)"), sec="Precedents"),
        S("sensitivity_table", "DCF value spans $880m to $1,090m across a 9.0% to 10.0% WACC at 2.0% growth",
          {"subtitle": "Enterprise value, WACC by terminal growth, $ million", "row_label": "WACC, %", "col_label": "Terminal growth, %",
           "row_values": [9.0, 9.5, 10.0], "col_values": [1.5, 2.0, 2.5],
           "values": [[1040, 1090, 1148], [940, 980, 1022], [840, 880, 922]], "base": [1, 1], "value_format": "#,##0",
           "takeaway": "Value falls from $1,090m to $880m as WACC rises from 9.0% to 10.0%"},
          src=("Sponsor DCF model, five-year explicit period (synthetic)",), sec="DCF"),
        S("football_field", "All four methods overlap between $912m and $980m, a midpoint of $946m",
          {"subtitle": "Enterprise value by method, $ million", "prefix": "$", "number_format": "#,##0", "current_price": 874, "implied": 946,
           "methods": [{"label": "Trading comps, 8.5x to 10.5x", "low": 816, "high": 1008},
                       {"label": "Precedents, 9.5x to 11.5x", "low": 912, "high": 1104},
                       {"label": "DCF, WACC 9.0% to 10.0%", "low": 880, "high": 1090, "key": True},
                       {"label": "LBO, 20% to 25% IRR", "low": 840, "high": 980}],
           "takeaway": "The overlap sits above the current enterprise value of $874m"},
          src=("Sponsor valuation model (synthetic)", "FactSet and deal database (synthetic)"), sec="Conclusion"),
        S("numbered_insights", "Each 100 bps of margin adds $53m of enterprise value at the peer median multiple",
          {"subtitle": "Why the margin gap matters", "insights": [
              {"title": "Margin", "text": "One point of margin on revenue, at the 9.5x peer median multiple", "figure": "$53m per 100 bps"},
              {"title": "Programme", "text": "The cost programme targets this gain by FY28, nearly closing the gap", "figure": "230 bps"},
              {"title": "Mix", "text": "Aftermarket share of sales rises, supporting the top half of the range", "figure": "28% to 35%"},
              {"title": "Revenue base", "text": "LTM revenue is the base for the margin sensitivity", "figure": "$561m"}]},
          src="Management plan (synthetic)", sec="Conclusion"),
        S("takeaway_box", "We recommend anchoring the board on $912m to $980m of enterprise value",
          {"decision": "Anchor the valuation range at $912m to $980m, or 9.5x to 10.2x FY26E EBITDA of $96.0m",
           "rationale": ["Overlap: all four methods agree inside the band", "Peers: median of 9.5x supports the midpoint",
                         "Upside: margin programme adds $53m per 100 bps"],
           "risks": ["Peer set: eight industrial manufacturers only", "DCF: sensitive to the WACC choice"]},
          src="Sponsor valuation model (synthetic)", sec="Conclusion"),
    ]
    req = ("Build a 10-slide valuation summary for the board of Northwind Industrial: public comps, precedents, DCF and a football "
           "field, with the answer first. Peers are eight US and European industrial manufacturers. All figures synthetic, as of 30 October 2026.")
    return make_brief("d02-public-comps-football-field", t, req, sl, client="Board of Directors", as_of="2026-10-30")


def d03():
    t = "Entering the Gulf B2B payments market"
    sl = [
        S("cover", t, {"client": "Aurora Pay, strategy team", "date": "15 October 2026"},
          visual=("abstract map tiles with a dashed route across the Gulf", "diagram"), sec="Answer"),
        S("exec_summary", "Enter the UAE with a bank partner in 2027 and Saudi Arabia in 2029",
          {"subtitle": "Market-entry recommendation, $ billion", "insights": [
              {"lead": "Market", "text": "The Gulf B2B payments revenue pool grows by 12% a year to 2030", "figure": "$4.2bn"},
              {"lead": "Focus", "text": "The UAE and Saudi Arabia hold this share of the 2025 pool", "figure": "71%"},
              {"lead": "Economics", "text": "A bank partnership breaks even earlier than a direct licence", "figure": "Month 26"},
              {"lead": "Ask", "text": "Funding over three years and a regional lead hired in Q1 2027", "figure": "$38m"}],
           "so_what": {"text": "Approve the staged funding in the November board vote."}},
          src=("Aurora Pay strategy team (synthetic)", "Market sizing model v3 (synthetic)"), sec="Answer"),
        S("column_kpi", "The Gulf B2B payments pool grows 12% a year, from $4.2bn to $7.4bn by 2030",
          {"subtitle": "Revenue pool, 2025 to 2030E, $ billion", "number_format": "0.0", "series_name": "Revenue pool",
           "categories": ["2025", "2026E", "2027E", "2028E", "2029E", "2030E"], "values": [4.2, 4.7, 5.3, 6.0, 6.7, 7.4],
           "stats": [{"value": "$7.4bn", "label": "pool in 2030E, up from $4.2bn in 2025"}, {"value": "12%", "label": "revenue CAGR, 2025 to 2030E"}],
           "takeaway": "Growth is steady, with no year below 10%"},
          src=("Central bank data (synthetic)", "Industry interviews (synthetic)"), sec="Market"),
        S("stacked_bar", "Saudi Arabia overtakes the UAE as the largest pool, reaching $2.9bn by 2030",
          {"subtitle": "Revenue pool by country, $ billion", "mode": "absolute", "number_format": "0.0",
           "categories": ["2025", "2027E", "2030E"],
           "parts": [{"name": "UAE", "values": [1.6, 2.0, 2.6]}, {"name": "Saudi Arabia", "values": [1.4, 1.9, 2.9], "key": True},
                     {"name": "Rest of GCC", "values": [1.2, 1.4, 1.9]}],
           "takeaway": "Saudi Arabia grows from $1.4bn to $2.9bn, the fastest of the three"},
          src=("Central bank data (synthetic)", "Team analysis (synthetic)"), sec="Market"),
        S("matrix_2x2", "Only 2 of 6 Gulf markets combine attractive size with a credible path to win",
          {"subtitle": "Market screen, attractiveness by ability to win", "x_axis": {"label": "Ability to win", "low": "Low", "high": "High"},
           "y_axis": {"label": "Market attractiveness", "low": "Low", "high": "High"},
           "quadrants": ["Build capability", "Prioritise", "Deprioritise", "Opportunistic"], "target": 1,
           "items": [{"label": "UAE", "xv": 0.8, "yv": 0.78, "highlight": True}, {"label": "Saudi Arabia", "xv": 0.62, "yv": 0.9, "highlight": True},
                     {"label": "Qatar", "xv": 0.55, "yv": 0.35}, {"label": "Kuwait", "xv": 0.3, "yv": 0.4},
                     {"label": "Oman", "xv": 0.7, "yv": 0.22}, {"label": "Bahrain", "xv": 0.35, "yv": 0.15}],
           "takeaway": "UAE and Saudi Arabia score above 0.6 on both axes"},
          src=("Team scoring on 8 criteria, weighted (synthetic)",), sec="Market"),
        S("harvey_table", "Aurora leads on cash-flow tools and risk but scores 0.5 on bank distribution",
          {"subtitle": "Capability coverage by player, harvey balls from none to full", "peers": ["Aurora Pay", "Peer A", "Peer B", "Peer C"],
           "highlight": 0, "capabilities": [
               {"name": "Cash-flow tools", "values": [1, 0.5, 0.5, 0.25]}, {"name": "Risk management", "values": [1, 0.75, 0.5, 0.5]},
               {"name": "Platform and API", "values": [0.75, 0.75, 1, 0.5]}, {"name": "Regional licences", "values": [0.5, 1, 0.75, 0.75]},
               {"name": "Bank distribution", "values": [0.5, 1, 0.75, 0.75]}, {"name": "Pricing", "values": [0.75, 0.5, 0.5, 0.25]}],
           "takeaway": "Bank distribution is the gap: 0.5 against 1.0 for Peer A"},
          src=("Expert interviews (synthetic)",), sec="Entry options"),
        S("comparison_table", "A bank partnership breaks even in month 26, against month 38 for a direct licence",
          {"subtitle": "Entry options, UAE, three-year view", "options": ["Bank partnership", "Direct licence", "Acquire a player"], "highlight": 0,
           "rows": [{"criterion": "Funding need", "values": ["$38m", "$61m", "$104m"]},
                    {"criterion": "Break-even", "values": ["Month 26", "Month 38", "Month 31"]},
                    {"criterion": "First revenue", "values": ["9 months", "18 months", "3 months"]},
                    {"criterion": "Execution risk", "values": ["Medium", "High", "Medium"]}],
           "verdict": ["Recommended", "Slower", "Costly"],
           "takeaway": "Partnership needs the least capital: $38m against $61m for a licence"},
          src=("Aurora Pay entry model v2 (synthetic)",), sec="Entry options"),
        S("process_flow", "A four-phase entry takes Aurora from partner signing to a Saudi licence by month 30",
          {"highlight": 1, "output_label": "Output", "steps": [
              {"name": "Partner", "output": "Q1 2027: sponsor bank signed"}, {"name": "Pilot", "output": "Q2 2027: 20 SME clients live"},
              {"name": "Scale UAE", "output": "2028: 400 clients, 12 sales staff"}, {"name": "Saudi launch", "output": "Month 30: licence filed"}],
           "subtitle": "Entry plan, UAE first"},
          src="Aurora Pay entry plan v2 (synthetic)", sec="Plan"),
        S("risk_heatmap", "Staged funding of $38m contains the three main risks of the entry plan",
          {"subtitle": "Risk register, likelihood by impact, five-point scale", "risks": [
              {"label": "Partner dependence: one bank", "likelihood": 3, "impact": 4},
              {"label": "Saudi licensing delay beyond 12 months", "likelihood": 3, "impact": 3},
              {"label": "Price competition from incumbents", "likelihood": 4, "impact": 2},
              {"label": "Hiring the regional lead by Q1 2027", "likelihood": 2, "impact": 3}],
           "takeaway": "Partner dependence is the largest exposure and the pilot adds a second bank"},
          src=("Aurora Pay strategy team (synthetic)",), sec="Plan"),
        S("recommendation", "Approve $38m in three tranches and hire the regional lead in Q1 2027",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "November 2026", "owner": "CFO", "date": "Nov 2026",
               "actions": ["Board vote on $38m staged funding", "Open talks with two sponsor banks"]},
              {"label": "Next", "window": "Q1 2027", "owner": "CEO", "date": "Mar 2027",
               "actions": ["Hire the Dubai-based regional lead", "Sign the sponsor bank agreement"]},
              {"label": "Later", "window": "H2 2027", "owner": "COO", "date": "Sep 2027",
               "actions": ["Run the pilot with 20 SME clients", "Start the Saudi licence application"]}]},
          src="Aurora Pay entry plan v2 (synthetic)", sec="Plan"),
    ]
    req = ("Write a 10-slide market-entry strategy for Aurora Pay, a B2B payments company: should it enter the Gulf, which country first, "
           "how (partnership versus licence versus acquisition), the plan, risks and the funding ask. Synthetic figures.")
    return make_brief("d03-gulf-market-entry", t, req, sl, client="Aurora Pay", as_of="2026-10-15", art="annotated_map")


def d04():
    t = "Project Falcon: sell-side valuation and buyer universe"
    sl = [
        S("cover", t, {"client": "Falcon Cloud shareholders", "date": "31 October 2026"},
          visual=("overlapping flat shapes suggesting a rising bird, editorial", "hero"), sec="Answer"),
        S("exec_summary", "Falcon supports an enterprise value of $1.9bn to $2.3bn, or 7.9x to 9.6x forward revenue",
          {"subtitle": "Sell-side summary, FY26E, $ million", "insights": [
              {"lead": "Value", "text": "Peers, precedents and the DCF point to one range", "figure": "$1.9bn to $2.3bn"},
              {"lead": "Multiple", "text": "The range equals this multiple of FY26E revenue of $240m", "figure": "7.9x to 9.6x"},
              {"lead": "Quality", "text": "Annual recurring revenue grows at this rate with high retention", "figure": "24%"},
              {"lead": "Buyers", "text": "Three strategic buyers combine fit and balance sheet", "figure": "$2.5bn"}],
           "so_what": {"text": "Launch a targeted process to 40 buyers in November 2026."}},
          src=("Company model (synthetic)", "Buyer screen (synthetic)"), sec="Answer"),
        S("kpi_row", "Falcon combines 24% growth, 118% net retention and a Rule of 40 score of 41",
          {"subtitle": "FY26E operating metrics", "highlight": 1, "kpis": [
              {"label": "ARR", "value": "$226m", "context": "Enterprise led", "change": {"text": "+24% YoY", "direction": "up"}},
              {"label": "Net revenue retention", "value": "118%", "context": "Cohorts expand", "change": {"text": "+3 pts", "direction": "up"}},
              {"label": "Gross margin", "value": "78%", "context": "Cloud hosting scale", "change": {"text": "+2 pts", "direction": "up"}},
              {"label": "Rule of 40", "value": "41", "context": "Growth plus FCF margin", "change": {"text": "+6 pts", "direction": "up"}}],
           "so_what": "Quality of revenue supports a premium to the peer median."},
          src="Company model (synthetic)", sec="Business"),
        S("combo_margin", "Revenue reaches $240m in FY26E and the free cash flow margin reaches 17%",
          {"subtitle": "Revenue, $ million, and free cash flow margin, %", "number_format": "#,##0", "line_format": "0%",
           "categories": ["FY22", "FY23", "FY24", "FY25", "FY26E"], "bars": {"name": "Revenue, $m", "values": [112, 138, 171, 205, 240]},
           "line": {"name": "FCF margin", "values": [0.04, 0.08, 0.12, 0.15, 0.17]},
           "takeaway": "Scale lifts the free cash flow margin from 4% to 17% in four years"},
          src=("Company model (synthetic)",), sec="Business"),
        S("stacked_column", "Enterprise customers grow to 58% of ARR from 44% in FY24, lifting retention",
          {"subtitle": "ARR mix by customer segment, % of ARR", "mode": "percent", "categories": ["FY24", "FY25", "FY26E"],
           "parts": [{"name": "Enterprise", "values": [44, 51, 58], "key": True}, {"name": "Mid-market", "values": [34, 32, 29]},
                     {"name": "SMB", "values": [22, 17, 13]}],
           "takeaway": "SMB falls to 13% of ARR, removing the main churn pool"},
          src=("Company model (synthetic)",), sec="Business"),
        S("comps_table", "Peers trade at a median 22.4x NTM EBITDA; Falcon's 24% growth earns the top half",
          {"subtitle": "Software peers, NTM multiples, EV in $ billion", "compute_stats": True, "dense": True, "rows": [
              {"company": "Cirrus Software", "ev": 14.2, "ev_ebitda": 31.2, "pe": 44.0, "growth": 19, "margin": 31},
              {"company": "Nimbus Systems", "ev": 9.8, "ev_ebitda": 26.8, "pe": 38.5, "growth": 17, "margin": 28},
              {"company": "Quanta Data", "ev": 7.4, "ev_ebitda": 24.1, "pe": 35.2, "growth": 14, "margin": 26},
              {"company": "Vertex Cloud", "ev": 5.1, "ev_ebitda": 20.7, "pe": 30.8, "growth": 12, "margin": 24},
              {"company": "Lumen Analytics", "ev": 3.6, "ev_ebitda": 18.3, "pe": 27.4, "growth": 10, "margin": 22},
              {"company": "Prism Workflow", "ev": 2.9, "ev_ebitda": 15.9, "pe": 24.1, "growth": 8, "margin": 19}],
           "takeaway": "Median NTM EV/EBITDA is 22.4x against Falcon's growth of 24%"},
          src=("Market data, 30 Oct 2026 (synthetic)",), sec="Valuation"),
        S("tombstones", "Scaled software precedents cleared 6.8x to 9.1x forward revenue",
          {"subtitle": "Precedent software deals, EV in $ billion, EV/forward revenue", "deals": [
              {"acquirer": "Sponsor A", "target": "Ledger Cloud", "date": "Jan 2026", "ev": 3.9, "multiple": 8.4},
              {"acquirer": "Strategic B", "target": "Pathway HR", "date": "Mar 2026", "ev": 2.8, "multiple": 7.9},
              {"acquirer": "Strategic C", "target": "Orbit Security", "date": "May 2026", "ev": 4.6, "multiple": 9.1},
              {"acquirer": "Sponsor D", "target": "Kite Billing", "date": "Jun 2026", "ev": 1.7, "multiple": 6.8},
              {"acquirer": "Sponsor E", "target": "Helm Data", "date": "Aug 2026", "ev": 2.2, "multiple": 7.2},
              {"acquirer": "Strategic F", "target": "Tern Devices", "date": "Sep 2026", "ev": 3.3, "multiple": 8.8}],
           "takeaway": "Strategic buyers paid 8.8x to 9.1x; sponsors paid 6.8x to 8.4x"},
          src=("Company announcements (synthetic)",), sec="Valuation"),
        S("matrix_2x2", "Three buyers pair strategic fit with cash above $2.5bn, led by Orbit",
          {"subtitle": "Buyer screen, strategic fit by capacity to pay", "x_axis": {"label": "Capacity to pay, cash above $2.5bn", "low": "Low", "high": "High"},
           "y_axis": {"label": "Strategic fit", "low": "Low", "high": "High"},
           "quadrants": ["Fit, limited cash", "Priority buyers", "Deprioritise", "Cash, weak fit"], "target": 1,
           "items": [{"label": "Orbit", "xv": 0.86, "yv": 0.88, "highlight": True}, {"label": "Vertex", "xv": 0.74, "yv": 0.8, "highlight": True},
                     {"label": "Nimbus", "xv": 0.68, "yv": 0.7, "highlight": True}, {"label": "Quanta", "xv": 0.3, "yv": 0.76},
                     {"label": "Lumen", "xv": 0.2, "yv": 0.3}, {"label": "Prism", "xv": 0.82, "yv": 0.25}],
           "takeaway": "Three buyers sit in the top-right quadrant of the screen"},
          src=("Buyer screen, 31 Oct 2026 (synthetic)",), sec="Process"),
        S("process_flow", "A 14-week process takes Falcon from launch to signing by March 2027",
          {"highlight": 2, "output_label": "Milestone", "subtitle": "Sale process, launch to signing", "steps": [
              {"name": "Launch", "output": "Week 2: teaser to 40 buyers"}, {"name": "First round", "output": "Week 6: indicative offers"},
              {"name": "Management", "output": "Week 9: five management meetings"}, {"name": "Final bids", "output": "Week 12: binding offers"},
              {"name": "Signing", "output": "Week 14: SPA signed"}]},
          src="Process plan (synthetic)", sec="Process"),
        S("recommendation", "Launch in November 2026 with 40 buyers to sign by March 2027",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "November 2026", "owner": "Deal lead", "date": "Nov 2026",
               "actions": ["Finalise the teaser and the data room", "Approve the buyer list of 40"]},
              {"label": "Next", "window": "December 2026", "owner": "CFO", "date": "Jan 2027",
               "actions": ["Run management meetings", "Collect indicative offers at week 6"]},
              {"label": "Later", "window": "Q1 2027", "owner": "CEO", "date": "Mar 2027",
               "actions": ["Negotiate the SPA with two finalists", "Sign at week 14"]}]},
          src="Process plan (synthetic)", sec="Process"),
    ]
    req = ("Prepare the valuation and buyer-universe section of a sell-side pitchbook for Falcon Cloud (Project Falcon), a US software "
           "company: operating quality, trading comps, precedents, the buyer screen and the process timetable. 10 slides, synthetic data.")
    return make_brief("d04-sell-side-pitchbook", t, req, sl, client="Falcon Cloud shareholders", as_of="2026-10-31", art="editorial_illustration")


ALL = [d01, d02, d03, d04]
