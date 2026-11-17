"""Corpus decks 16, 17, 18, 20 (English; synthetic data)."""
from evals.decks._lib import S, make_brief


def d16():
    t = "Project Dune: GCC district cooling platform"
    sl = [
        S("cover", t, {"client": "Infrastructure Investment Committee", "date": "28 October 2026"},
          visual=("two-tone arches and pipes in a desert palette, duotone", "hero"), sec="Answer"),
        S("exec_summary", "A 40% stake in Dune at $1,380m EV returns 14.0% IRR on 94% contracted revenue",
          {"subtitle": "Investment case, IFRS, $ million", "insights": [
              {"lead": "Price", "text": "Enterprise value for the whole platform", "figure": "$1,380m"},
              {"lead": "Cheque", "text": "Our 40% share of the equity value", "figure": "$552m"},
              {"lead": "Contracts", "text": "Revenue is secured by 25-year capacity contracts", "figure": "94%"},
              {"lead": "Returns", "text": "Base case equity IRR against a 12% hurdle", "figure": "14.0%"}],
           "so_what": {"text": "Approve the 40% stake and exclusivity with the seller."}},
          src=("Platform model v7 (synthetic)", "Seller information memorandum (synthetic)"), sec="Answer"),
        S("stat_hero", "GCC district cooling grows to $9.6bn by 2030 and Dune holds 22% of independent capacity",
          {"subtitle": "GCC district cooling market", "stats": [
              {"value": "$9.6bn", "label": "market size in 2030E", "context": "CAGR of 7.4% from $6.4bn in 2025"},
              {"value": "22%", "label": "Dune share of independent capacity", "context": "Largest of five operators"}],
           "so_what": "Demand follows new developments in the UAE and Saudi Arabia."},
          src=("Industry reports (synthetic)", "Operator disclosures (synthetic)"), sec="Market"),
        S("market_map", "Dune leads UAE capacity at 410 kRT, ahead of four listed rivals",
          {"subtitle": "District cooling players by segment", "segments": [
              {"name": "Master developments", "players": [{"name": "Dune", "client": True}, {"name": "Falcon Cooling"}, {"name": "Palm Energy"}]},
              {"name": "Commercial towers", "players": [{"name": "Dune", "client": True}, {"name": "Crescent Cool"}, {"name": "Oasis Utilities"}, {"name": "Falcon Cooling"}]},
              {"name": "Government sites", "players": [{"name": "Dune", "client": True}, {"name": "State Utility Co"}]}],
           "takeaway": "Dune is the only independent present in all segments; capacity 410 kRT in 2026E"},
          src=("Operator disclosures (synthetic)",), sec="Market"),
        S("column_kpi", "Contracted capacity grows from 310 to 455 kRT, a 10% CAGR through FY27E",
          {"subtitle": "Contracted capacity, thousand refrigeration tons", "number_format": "0", "series_name": "Capacity",
           "categories": ["FY23", "FY24", "FY25", "FY26E", "FY27E"], "values": [310, 340, 372, 410, 455],
           "stats": [{"value": "455 kRT", "label": "contracted capacity in FY27E"}, {"value": "10%", "label": "capacity CAGR, FY23 to FY27E"}],
           "takeaway": "Every year adds at least 30 kRT of new contracts"},
          src=("Platform model v7 (synthetic)",), sec="Platform"),
        S("doughnut_split", "Capacity charges are 62% of revenue, so earnings do not depend on weather",
          {"subtitle": "Revenue by charge type, FY25, % of total", "centre": "$212m",
           "slices": [{"label": "Capacity charges", "value": 62, "key": True}, {"label": "Consumption", "value": 31}, {"label": "Connection fees", "value": 7}],
           "takeaway": "Only 31% of revenue varies with consumption"},
          src=("Platform model v7 (synthetic)",), sec="Platform"),
        S("combo_margin", "Revenue reaches $231m in FY26E at a 55% EBITDA margin",
          {"subtitle": "Revenue, $ million, and EBITDA margin, %", "number_format": "#,##0", "line_format": "0%",
           "categories": ["FY22", "FY23", "FY24", "FY25", "FY26E"], "bars": {"name": "Revenue, $m", "values": [168, 181, 196, 212, 231]},
           "line": {"name": "EBITDA margin", "values": [0.51, 0.52, 0.53, 0.54, 0.55]},
           "takeaway": "Margin has risen one point a year as fixed assets fill"},
          src=("Platform model v7 (synthetic)",), sec="Financials"),
        S("issue_tree", "Investment works if three tests hold: 94% contracted, 8.5% WACC and 14% IRR",
          {"subtitle": "Investment tests", "root": "Should we buy a 40% stake in Dune at $1,380m EV?", "branches": [
              {"name": "Is the revenue secure?", "leaves": ["94% under contracts of 25 years", "Top customer below 15% of revenue"]},
              {"name": "Is the price right?", "leaves": ["Discount rate of 8.5% WACC", "EV of $1,380m is within the DCF range"]},
              {"name": "Do returns clear the hurdle?", "leaves": ["Base case IRR of 14.0%", "Hurdle of 12% holds at 10% lower volume"]}]},
          src="Platform model v7 (synthetic)", sec="Risks"),
        S("risk_heatmap", "3 of 5 risks need mitigation: counterparty, power cost and refinancing",
          {"subtitle": "Risk register, likelihood by impact, five-point scale", "risks": [
              {"label": "Developer default on 94% contracted", "likelihood": 2, "impact": 5}, {"label": "Power cost up 20%", "likelihood": 3, "impact": 4},
              {"label": "Refinancing at 8.5% WACC or higher", "likelihood": 3, "impact": 3}, {"label": "Regulatory tariff cap", "likelihood": 2, "impact": 3},
              {"label": "Construction delay of 6 months", "likelihood": 3, "impact": 2}],
           "takeaway": "Developer default is the largest exposure, at impact 5"},
          src=("Deal team risk workshop (synthetic)",), sec="Risks"),
        S("takeaway_box", "We recommend a 40% stake at $1,380m EV for a 14.0% equity IRR",
          {"decision": "Approve a 40% stake at $1,380m EV, a $552m equity cheque, with exclusivity until 30 November",
           "rationale": ["Contracts: 94% of revenue is secured for 25 years", "Returns: 14.0% IRR clears the 12% hurdle", "Market: 22% share and a 10% capacity CAGR"],
           "risks": ["Counterparty: developer default is mitigated by escrow", "Power: a 20% cost rise is passed through in 80% of contracts"]},
          src="Platform model v7 (synthetic)", sec="Decision"),
    ]
    req = ("Write a 10-slide investment committee memo for Project Dune, a GCC district cooling platform: market, competitive position, "
           "contracted capacity, revenue quality, financials, the three investment tests, risks and the recommendation. IFRS, USD, synthetic data.")
    return make_brief("d16-gcc-infrastructure", t, req, sl, client="Infrastructure Investment Committee", as_of="2026-10-28", art="duotone_hero")


def d17():
    t = "Project Beacon: US software take-private"
    sl = [
        S("cover", t, {"client": "Sponsor deal team", "date": "9 November 2026"},
          visual=("a grid of geometric icons on tiles", "icon_system"), sec="Answer"),
        S("exec_summary", "A $41.50 offer takes Beacon private at 7.3x ARR and returns 3.0x to the sponsor",
          {"subtitle": "Take-private summary, $", "insights": [
              {"lead": "Offer", "text": "All-cash offer per share for the public shareholders", "figure": "$41.50"},
              {"lead": "Premium", "text": "Premium to the unaffected price of $31.20", "figure": "33.0%"},
              {"lead": "Value", "text": "Enterprise value as a multiple of ARR of $520m", "figure": "7.3x"},
              {"lead": "Returns", "text": "Base case sponsor money multiple over five years", "figure": "3.0x"}],
           "so_what": {"text": "Submit the offer on 16 November and seek a go-shop of 30 days."}},
          src=("Market data, 6 Nov 2026 (synthetic)", "Sponsor model v6 (synthetic)"), sec="Answer"),
        S("kpi_row", "Beacon has $520m of ARR growing 19%, with 112% net retention",
          {"subtitle": "LTM operating metrics", "highlight": 0, "kpis": [
              {"label": "ARR", "value": "$520m", "context": "+19% YoY", "change": {"text": "up", "direction": "up"}},
              {"label": "Net retention", "value": "112%", "context": "Mid-market cohorts", "change": {"text": "flat", "direction": "flat"}},
              {"label": "Free cash flow margin", "value": "19%", "context": "Rule of 38", "change": {"text": "up", "direction": "up"}},
              {"label": "Gross margin", "value": "76%", "context": "Hosting costs fall", "change": {"text": "up", "direction": "up"}}],
           "so_what": "Growth and cash flow already meet the public-to-private bar."},
          src="Company filings, LTM Sep 2026 (synthetic)", sec="Company"),
        S("scatter_quadrant", "Beacon grows faster than 5 of 7 peers but earns a margin below the median",
          {"subtitle": "ARR growth versus free cash flow margin, %", "x_title": "ARR growth, %", "y_title": "FCF margin, %", "x_format": "0", "y_format": "0",
           "points": [{"label": "Beacon", "xv": 19, "yv": 19, "subject": True}, {"label": "Cirrus", "xv": 22, "yv": 27}, {"label": "Nimbus", "xv": 17, "yv": 24},
                      {"label": "Quanta", "xv": 15, "yv": 26}, {"label": "Vertex", "xv": 13, "yv": 22}, {"label": "Lumen", "xv": 11, "yv": 21},
                      {"label": "Prism", "xv": 9, "yv": 18}, {"label": "Helm", "xv": 8, "yv": 16}],
           "stat": {"value": "-5pp", "label": "FCF margin gap to the peer median of 24%"},
           "takeaway": "A margin plan from 19% to 28% is the core of the value creation case"},
          src=("Company filings (synthetic)",), sec="Valuation"),
        S("comps_table", "Software peers trade at a median 17.5x NTM EBITDA, and Beacon's offer implies 21.0x",
          {"subtitle": "Software comparables, NTM, EV in $ billion", "compute_stats": True, "dense": True, "rows": [
              {"company": "Cirrus", "ev": 12.4, "ev_ebitda": 23.4, "pe": 36.0, "growth": 22, "margin": 27},
              {"company": "Nimbus", "ev": 8.9, "ev_ebitda": 20.6, "pe": 31.2, "growth": 17, "margin": 24},
              {"company": "Quanta", "ev": 6.7, "ev_ebitda": 18.4, "pe": 28.5, "growth": 15, "margin": 26},
              {"company": "Vertex", "ev": 5.3, "ev_ebitda": 16.6, "pe": 25.1, "growth": 13, "margin": 22},
              {"company": "Lumen", "ev": 3.8, "ev_ebitda": 14.9, "pe": 22.7, "growth": 11, "margin": 21},
              {"company": "Prism", "ev": 2.9, "ev_ebitda": 12.8, "pe": 19.4, "growth": 9, "margin": 18}],
           "takeaway": "The offer multiple of 21.0x is above the peer median of 17.5x"},
          src=("Market data, 6 Nov 2026 (synthetic)",), sec="Valuation"),
        S("tombstones", "US software take-privates cleared 6.4x to 9.2x ARR, and Beacon is at 7.3x",
          {"subtitle": "Take-private precedents, EV in $ billion, EV/ARR", "deals": [
              {"acquirer": "Sponsor A", "target": "Ledgerly", "date": "Feb 2026", "ev": 3.4, "multiple": 8.1},
              {"acquirer": "Sponsor B", "target": "Pathfinder", "date": "Apr 2026", "ev": 2.1, "multiple": 6.4},
              {"acquirer": "Sponsor C", "target": "Skyline Data", "date": "Jun 2026", "ev": 4.8, "multiple": 9.2},
              {"acquirer": "Sponsor D", "target": "Tangent", "date": "Aug 2026", "ev": 2.7, "multiple": 7.0},
              {"acquirer": "Beacon bid", "target": "Beacon", "date": "Nov 2026", "ev": 3.8, "multiple": 7.3, "highlight": True}],
           "takeaway": "The Beacon multiple of 7.3x sits inside the 6.4x to 9.2x range"},
          src=("Company announcements (synthetic)",), sec="Valuation"),
        S("sensitivity_table", "Sponsor IRR stays at or above 20.5% across all nine premium and exit cases",
          {"subtitle": "Sponsor IRR, offer premium by exit EV/ARR, %", "row_label": "Offer premium, %", "col_label": "Exit EV/ARR, x",
           "row_values": [30, 33, 36], "col_values": [6.5, 7.5, 8.5], "value_format": "0.0",
           "values": [[24.8, 27.1, 29.2], [22.6, 24.8, 26.9], [20.5, 22.6, 24.7]], "base": [1, 1],
           "takeaway": "Base case IRR is 24.8% at a 33% premium and 7.5x exit"},
          src=("Sponsor model v6 (synthetic)",), sec="Returns"),
        S("waterfall", "ARR growth adds $1,540m and margin expansion $640m to equity worth $3,636m at exit",
          {"subtitle": "Equity value bridge, entry to exit, $ million", "number_format": "#,##0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "Entry equity", "value": 1200}, {"label": "ARR growth", "value": 1540}, {"label": "Margin expansion", "value": 640},
                     {"label": "Deleveraging", "value": 256}, {"label": "Exit equity", "value": 3636}],
           "takeaway": "Entry equity of $1,200m grows 3.0x to $3,636m"},
          src=("Sponsor model v6 (synthetic)",), sec="Returns"),
        S("two_column_compare", "The offer of $41.50 beats the standalone value of $36.80 per share by 12.8%",
          {"emphasis": "a", "a": {"heading": "Accept the take-private", "metric": "$41.50", "points": [
              "Value: cash at a 33.0% premium", "Timing: close in 5 months", "Risk: shareholder vote at 50%"]},
           "b": {"heading": "Remain public", "metric": "$36.80", "points": [
              "Value: standalone DCF at 12.8% below the offer", "Timing: no deal risk", "Risk: growth slows below 19%"]},
           "verdict": "The offer exceeds the standalone value by $4.70 per share."},
          src=("Sponsor model v6 (synthetic)",), sec="Decision"),
        S("recommendation", "Submit the $41.50 offer on 16 November with a 30-day go-shop",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "this week", "owner": "Deal lead", "date": "16 Nov 2026",
               "actions": ["Submit the $41.50 offer letter", "Sign the financing commitment"]},
              {"label": "Next", "window": "30-day go-shop", "owner": "Counsel", "date": "Dec 2026",
               "actions": ["Run the 30-day go-shop", "Prepare the proxy statement"]},
              {"label": "Later", "window": "months 2 to 5", "owner": "CFO", "date": "Apr 2027",
               "actions": ["Hold the shareholder vote", "Close within 5 months"]}]},
          src="Sponsor deal plan (synthetic)", sec="Decision"),
    ]
    req = ("Prepare a 10-slide take-private recommendation for Project Beacon, a US SaaS company: the offer, operating metrics, peers, "
           "precedents, LBO returns sensitivity, value creation bridge and next steps. US GAAP, synthetic data.")
    return make_brief("d17-us-software-take-private", t, req, sl, client="Sponsor deal team", as_of="2026-11-09", art="iconographic_system")


def d18():
    t = "Project Rhine: strategic review of Rheinwerk AG"
    sl = [
        S("cover", t, {"client": "Supervisory Board, Rheinwerk AG", "date": "16 November 2026"},
          visual=("a river delta drawn as layered organic and geometric shapes", "illustration"), sec="Answer"),
        S("exec_summary", "Separating Automation lifts the sum of the parts to €46.00 per share against €38.40 today",
          {"subtitle": "Strategic review summary, IFRS, € million", "insights": [
              {"lead": "Gap", "text": "Sum-of-the-parts value per share against the current price", "figure": "€46.00"},
              {"lead": "Earnings", "text": "IFRS EBITDA on revenue of €3,420m", "figure": "€412m"},
              {"lead": "Option", "text": "A spin-off of Automation takes this long to complete", "figure": "9 months"},
              {"lead": "Balance sheet", "text": "Net debt to EBITDA excluding leases", "figure": "1.6x"}],
           "so_what": {"text": "Mandate a spin-off of Automation for a 2027 listing."}},
          src=("Annual report FY25, IFRS (synthetic)", "Advisor SOTP model (synthetic)"), sec="Answer"),
        S("kpi_row", "Rheinwerk earns €412m of IFRS EBITDA, a 12.0% margin, with net debt at 1.6x",
          {"subtitle": "FY26E group, IFRS, € million", "highlight": 1, "kpis": [
              {"label": "Revenue", "value": "€3,420m", "context": "+4.1% YoY", "change": {"text": "up", "direction": "up"}},
              {"label": "IFRS EBITDA", "value": "€412m", "context": "12.0% margin", "change": {"text": "up", "direction": "up"}},
              {"label": "Net debt", "value": "€640m", "context": "Excludes leases", "change": {"text": "down", "direction": "up"}},
              {"label": "Lease liabilities", "value": "€310m", "context": "IFRS 16", "change": {"text": "flat", "direction": "flat"}}],
           "so_what": "Net debt of €640m is 1.6x IFRS EBITDA before leases."},
          src="Annual report FY25, IFRS (synthetic)", sec="Group"),
        S("waterfall", "Removing IFRS 16 lease effects lowers EBITDA from €412m to €354m",
          {"subtitle": "IFRS EBITDA to pre-IFRS 16 EBITDA, € million", "number_format": "0", "prefix": "€", "suffix": "m",
           "steps": [{"label": "IFRS EBITDA", "value": 412}, {"label": "Lease depreciation", "value": -46}, {"label": "Lease interest", "value": -12},
                     {"label": "Pre-IFRS 16", "value": 354}],
           "takeaway": "Lease costs of €58m are 14% of IFRS EBITDA"},
          src=("Annual report FY25, IFRS 16 note (synthetic)",), sec="Group"),
        S("stacked_bar", "Automation is 35% of revenue and Europe is 62% of group sales",
          {"subtitle": "Revenue by division and region, % of group", "mode": "percent", "categories": ["By division", "By region"],
           "parts": [{"name": "Automation | Europe", "values": [35, 62], "key": True}, {"name": "Drives | Americas", "values": [41, 24]},
                     {"name": "Components | Asia", "values": [24, 14]}],
           "takeaway": "Automation, at 35% of revenue, has the clearest listing profile"},
          src=("Annual report FY25 segment note (synthetic)",), sec="Divisions"),
        S("small_multiples", "Automation margin rises 3.4 points to 15.1%, while Components stays below 9%",
          {"subtitle": "EBITDA margin by division, FY23 to FY26E, %", "number_format": "0.0",
           "panels": [{"title": "Automation", "categories": ["FY23", "FY24", "FY25", "FY26E"], "values": [11.7, 12.9, 14.0, 15.1]},
                      {"title": "Drives", "categories": ["FY23", "FY24", "FY25", "FY26E"], "values": [12.4, 12.1, 12.6, 12.9]},
                      {"title": "Components", "categories": ["FY23", "FY24", "FY25", "FY26E"], "values": [8.8, 8.1, 8.4, 8.7]}],
           "takeaway": "Automation has gained 3.4 points since FY23"},
          src=("Annual report FY25 segment note (synthetic)",), sec="Divisions"),
        S("comparison_table", "A spin-off of Automation delivers €46.00 per share, €3.00 more than a sale",
          {"subtitle": "Strategic options, € per share", "options": ["Spin-off", "Sale of Automation", "Hold"], "highlight": 0,
           "rows": [{"criterion": "Value per share", "values": ["€46.00", "€43.00", "€38.40"]},
                    {"criterion": "Time to complete", "values": ["9 months", "7 months", "n.a."]},
                    {"criterion": "Tax leakage", "values": ["€0m", "€64m", "€0m"]},
                    {"criterion": "Execution risk", "values": ["Medium", "Medium", "Low"]}],
           "verdict": ["Recommended", "Tax cost", "Discount"], "takeaway": "The spin-off avoids €64m of tax leakage"},
          src=("Advisor SOTP model (synthetic)",), sec="Options"),
        S("football_field", "Every method values Rheinwerk above the current share price of €38.40",
          {"subtitle": "Equity value per share by method, €", "prefix": "€", "number_format": "0.00", "current_price": 38.40, "implied": 46.00,
           "methods": [{"label": "Sum of the parts", "low": 41.00, "high": 52.00, "key": True}, {"label": "DCF", "low": 39.00, "high": 50.00},
                       {"label": "Trading comps", "low": 36.00, "high": 46.00}, {"label": "Precedents", "low": 44.00, "high": 55.00},
                       {"label": "Analyst targets", "low": 37.00, "high": 48.00}],
           "takeaway": "Only the trading comps range starts below the current price of €38.40"},
          src=("Advisor SOTP model (synthetic)", "Market data, 13 Nov 2026 (synthetic)"), sec="Options"),
        S("process_flow", "A five-step plan lists Automation within 9 months of the board mandate",
          {"highlight": 2, "output_label": "Output", "subtitle": "Spin-off workplan", "steps": [
              {"name": "Mandate", "output": "Month 0: supervisory board decision"}, {"name": "Carve-out accounts", "output": "Month 3: IFRS accounts for Automation"},
              {"name": "Governance", "output": "Month 5: board and capital structure"}, {"name": "Prospectus", "output": "Month 7: filing"},
              {"name": "Listing", "output": "Month 9: first day of trading"}]},
          src="Advisor workplan (synthetic)", sec="Next steps"),
        S("takeaway_box", "We recommend a spin-off of Automation for €46.00 per share in 9 months",
          {"decision": "Mandate the spin-off of Automation, targeting a listing in 9 months and €46.00 per share of value",
           "rationale": ["Value: €46.00 against €38.40 today", "Tax: no leakage against €64m on a sale", "Margin: Automation at 15.1% earns a premium multiple"],
           "risks": ["Execution: carve-out accounts in 3 months", "Market: listing window in 2027"]},
          src="Advisor SOTP model (synthetic)", sec="Next steps"),
    ]
    req = ("Write a 10-slide strategic review for the supervisory board of Rheinwerk AG, a European industrial group reporting under IFRS in EUR: "
           "group financials with IFRS 16, divisions, options (spin-off, sale, hold), valuation and the workplan. Synthetic data.")
    return make_brief("d18-ifrs-european-industrial", t, req, sl, client="Supervisory Board", as_of="2026-11-16")


def d20():
    t = "Project Oasis: acquisition of an Egyptian bank"
    sl = [
        S("cover", t, {"client": "Board of Gulf Union Bank", "date": "2 November 2026"},
          visual=("abstract map tiles with a dashed route between two regions", "diagram"), sec="Answer"),
        S("exec_summary", "Acquiring Delta Bank at 1.35x book is 6.8% accretive and keeps CET1 at 13.9%",
          {"subtitle": "Transaction summary, IFRS 9, $ million", "insights": [
              {"lead": "Price", "text": "Equity value at 1.35x price to book of $960m", "figure": "$1,296m"},
              {"lead": "Accretion", "text": "EPS accretion in the first full year", "figure": "6.8%"},
              {"lead": "Capital", "text": "Pro forma CET1 ratio against 15.1% today", "figure": "13.9%"},
              {"lead": "Quality", "text": "Delta's NPL ratio with provision coverage of 142%", "figure": "3.9%"}],
           "so_what": {"text": "Approve a non-binding offer and start confirmatory diligence."}},
          src=("Delta Bank accounts, IFRS 9 (synthetic)", "Acquirer model v5 (synthetic)"), sec="Answer"),
        S("scorecard", "Delta earns a 17.8% ROE with 3.9% NPLs, and NPL coverage rose to 142%",
          {"subtitle": "Delta Bank KPI scorecard, last five periods", "periods": ["H1 24", "H2 24", "H1 25", "H2 25", "H1 26"], "kpis": [
              {"name": "ROE", "format": "pct", "values": [15.2, 16.1, 16.9, 17.4, 17.8]},
              {"name": "NPL ratio", "format": "pct", "values": [5.1, 4.8, 4.4, 4.1, 3.9], "good_up": False},
              {"name": "NPL coverage", "format": "pct", "values": [118, 124, 130, 137, 142]},
              {"name": "CET1 ratio", "format": "pct", "values": [15.1, 15.4, 15.8, 16.0, 16.2]}],
           "takeaway": "Coverage of 142% against NPLs of 3.9% is above the sector norm"},
          src=("Delta Bank accounts, IFRS 9 (synthetic)",), sec="Target"),
        S("paired_bars", "Delta's cost-to-income ratio improves by 1.8 points on average, led by retail",
          {"subtitle": "Cost-to-income by business line, FY24 versus FY25, %", "number_format": "0.0",
           "categories": ["Retail", "Corporate", "SME", "Treasury", "Cards"],
           "before": {"name": "FY24", "values": [58.2, 41.5, 52.4, 31.0, 49.8]}, "after": {"name": "FY25", "values": [53.9, 40.2, 50.1, 30.6, 50.3]},
           "stat": {"value": "-1.8pp", "label": "average change across the five lines"},
           "takeaway": "Cards is the one line that worsened, to 50.3%"},
          src=("Delta Bank accounts, IFRS 9 (synthetic)",), sec="Target"),
        S("ranked_bar", "The 1.35x offer is the third highest of 8 Egyptian bank multiples",
          {"subtitle": "Price to book, Egyptian banks, x", "number_format": "0.00\"x\"", "series_name": "P/B", "items": [
              {"label": "Nile Commercial", "value": 1.62}, {"label": "Pyramid Bank", "value": 1.48}, {"label": "Offer for Delta", "value": 1.35, "key": True},
              {"label": "Cairo Merchant", "value": 1.31}, {"label": "Delta Bank, unaffected", "value": 1.08}, {"label": "Alex Trust", "value": 1.04},
              {"label": "Suez Finance", "value": 0.97}, {"label": "Delta Valley", "value": 0.91}],
           "stat": {"value": "+25%", "label": "premium to the unaffected 1.08x multiple"},
           "takeaway": "The offer is above the peer median of 1.19x"},
          src=("Market data, 30 Oct 2026 (synthetic)",), sec="Valuation"),
        S("comparison_table", "A share swap keeps CET1 at 14.4%, against 13.9% for an all-cash deal",
          {"subtitle": "Consideration structures", "options": ["All cash", "Share swap", "Mixed 50/50"], "highlight": 2,
           "rows": [{"criterion": "Pro forma CET1", "values": ["13.9%", "14.4%", "14.1%"]},
                    {"criterion": "EPS accretion", "values": ["6.8%", "4.9%", "5.9%"]},
                    {"criterion": "New shares issued", "values": ["0m", "212m", "106m"]},
                    {"criterion": "Seller preference", "values": ["High", "Low", "Medium"]}],
           "verdict": ["CET1 cost", "Dilutive", "Recommended"], "takeaway": "The mixed structure gives 5.9% accretion at 14.1% CET1"},
          src=("Acquirer model v5 (synthetic)",), sec="Valuation"),
        S("sensitivity_table", "Accretion stays positive from 4.2% to 9.4% across price and cost savings cases",
          {"subtitle": "EPS accretion, price to book by cost savings, %", "row_label": "Price to book, x", "col_label": "Cost savings, $m",
           "row_values": [1.25, 1.35, 1.45], "col_values": [20, 35, 50], "value_format": "0.0",
           "values": [[5.1, 7.3, 9.4], [4.6, 6.8, 8.9], [4.2, 6.4, 8.5]], "base": [1, 1],
           "takeaway": "The base case of 6.8% needs cost savings of $35m"},
          src=("Acquirer model v5 (synthetic)",), sec="Valuation"),
        S("risk_heatmap", "3 of 4 regulatory and currency risks need conditions before a binding offer",
          {"subtitle": "Risk register, likelihood by impact, five-point scale", "risks": [
              {"label": "Central bank approval beyond 6 months", "likelihood": 3, "impact": 5}, {"label": "EGP devaluation of 20%", "likelihood": 3, "impact": 4},
              {"label": "NPL coverage drops below 120%", "likelihood": 2, "impact": 4}, {"label": "Key banker attrition of 15%", "likelihood": 3, "impact": 3}],
           "takeaway": "Central bank approval is the largest exposure, at impact 5"},
          src=("Deal team workshop (synthetic)",), sec="Risks"),
        S("gantt", "Closing takes 9 months, led by central bank approval and systems integration",
          {"subtitle": "Closing and integration plan, 2027", "today": 0.5, "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
           "workstreams": [
               {"name": "Diligence", "bars": [{"start": 0, "end": 2, "label": "Confirmatory"}], "milestones": [{"month": 2.4, "label": "SPA signed"}]},
               {"name": "Approvals", "bars": [{"start": 2, "end": 7, "label": "Central bank review", "highlight": True}], "milestones": [{"month": 7.4, "label": "Approval"}]},
               {"name": "Financing", "bars": [{"start": 1, "end": 4, "label": "Capital plan"}], "milestones": []},
               {"name": "Integration", "bars": [{"start": 4, "end": 8.5, "label": "Systems and brand"}], "milestones": []}]},
          src="Closing plan (synthetic)", sec="Next steps"),
        S("takeaway_box", "We recommend a non-binding offer at 1.35x book, or $1,296m",
          {"decision": "Approve a non-binding offer of 1.35x book, $1,296m, in a mixed structure with 14.1% pro forma CET1",
           "rationale": ["Accretion: 5.9% in the mixed structure", "Quality: ROE of 17.8% and NPLs of 3.9%", "Capital: CET1 stays above 14.1%"],
           "risks": ["Approval: central bank review may exceed 6 months", "Currency: EGP devaluation of 20% cuts earnings"]},
          src="Acquirer model v5 (synthetic)", sec="Next steps"),
    ]
    req = ("Prepare a 10-slide board paper for Gulf Union Bank on acquiring Delta Bank Egypt (Project Oasis): target quality, valuation versus peers, "
           "consideration structures, accretion sensitivity, regulatory and currency risks and the closing plan. IFRS 9, USD, synthetic data.")
    return make_brief("d20-mena-bank-ma", t, req, sl, client="Board of Gulf Union Bank", as_of="2026-11-02")


ALL = [d16, d17, d18, d20]
