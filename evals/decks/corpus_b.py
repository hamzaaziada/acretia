"""Corpus decks 05-11 (synthetic data; project names are fictional)."""
from evals.decks._lib import S, make_brief


def d05():
    t = "Project Meridian: investment committee memo"
    entry_ebitda, entry_mult, exit_mult, exit_ebitda = 54.0, 10.5, 12.0, 118.0
    ev = round(entry_ebitda * entry_mult)                      # 567
    debt_in, debt_out, fees = 216, 266, 20
    eq_in = ev + fees - debt_in                                # 371
    exit_ev = round(exit_ebitda * exit_mult)                   # 1416
    eq_out = exit_ev - debt_out

    def irr(m, e):
        return ((m * e - debt_out) / eq_in) ** 0.2 * 100 - 100
    moic = eq_out / eq_in
    grid = [[round(irr(m, e), 1) for e in (100, 118, 130)] for m in (11.0, 12.0, 13.0)]
    base_irr = grid[1][1]
    g_up = round((exit_ebitda - entry_ebitda) * entry_mult)    # 672
    g_mult = round((exit_mult - entry_mult) * exit_ebitda)     # 177
    assert eq_in + g_up + g_mult - (debt_out - debt_in) - fees == eq_out, (eq_in, g_up, g_mult, eq_out)
    sl = [
        S("cover", t, {"client": "Investment Committee, Growth Fund II", "date": "12 November 2026"},
          visual=("stacked tiles forming a molar tooth silhouette, flat blue", "illustration"), sec="Answer"),
        S("exec_summary", f"Meridian returns {moic:.1f}x and {base_irr:.1f}% IRR from a dental platform buy-and-build",
          {"subtitle": "Investment case, $ million", "insights": [
              {"lead": "Entry", "text": "Entry at 10.5x EBITDA of $54.0m across 148 clinics", "figure": f"${ev}m"},
              {"lead": "Returns", "text": "Base case money multiple over a five-year hold", "figure": f"{moic:.1f}x"},
              {"lead": "Plan", "text": "Add-on clinics at 6.0x lift EBITDA to the exit level", "figure": f"${exit_ebitda:.0f}m"},
              {"lead": "Risk", "text": "Dentist retention after acquisition is the key diligence item", "figure": "94%"}],
           "so_what": {"text": "Approve a $371m equity commitment to the platform."}},
          src=("Deal team model v9 (synthetic)", "Management plan (synthetic)"), sec="Answer"),
        S("stat_hero", "The US dental services market is worth $34bn, and DSOs hold only 12% of clinics",
          {"subtitle": "US dental services, 2025", "stats": [
              {"value": "$34bn", "label": "annual spend on dental services", "context": "Growing 5.1% a year to 2030"},
              {"value": "12%", "label": "share of clinics owned by DSOs", "context": "Up from 8% in 2020"}],
           "so_what": "Low penetration leaves room for consolidation at 6.0x add-on multiples."},
          src=("Industry association data (synthetic)", "Market study (synthetic)"), sec="Market"),
        S("column_kpi", "EBITDA compounds at 15% a year to $54m across 148 clinics",
          {"subtitle": "EBITDA, FY21 to FY25, $ million", "number_format": "0", "series_name": "EBITDA",
           "categories": ["FY21", "FY22", "FY23", "FY24", "FY25"], "values": [31, 36, 42, 48, 54],
           "stats": [{"value": "$54m", "label": "FY25 EBITDA across 148 clinics, 17.0% margin"}, {"value": "15%", "label": "EBITDA CAGR over four years"}],
           "takeaway": "Growth comes from 31 acquired clinics and same-clinic gains"},
          src=("Company accounts, FY21 to FY25 (synthetic)",), sec="Platform"),
        S("paired_bars", "Revenue per clinic rises in every region, reaching $2.6m in the West",
          {"subtitle": "Revenue per clinic by region, FY24 versus FY25, $ million", "number_format": "0.0",
           "categories": ["Northeast", "Southeast", "Midwest", "West", "Texas"],
           "before": {"name": "FY24", "values": [1.9, 2.1, 1.7, 2.4, 2.0]}, "after": {"name": "FY25", "values": [2.1, 2.3, 1.8, 2.6, 2.2]},
           "stat": {"value": "+$0.2m", "label": "average gain per clinic"},
           "takeaway": "The Midwest lags at $1.8m and is the first target for a pricing review"},
          src=("Company accounts, FY25 (synthetic)",), sec="Platform"),
        S("waterfall", f"EBITDA growth drives ${g_up}m of value, multiple adds ${g_mult}m and net debt costs $50m",
          {"subtitle": "Equity value bridge, entry to exit, $ million", "number_format": "#,##0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "Entry equity", "value": eq_in}, {"label": "EBITDA growth", "value": g_up}, {"label": "Multiple", "value": g_mult},
                     {"label": "Net debt", "value": -(debt_out - debt_in)}, {"label": "Fees", "value": -fees},
                     {"label": "Exit equity", "value": eq_out}],
           "takeaway": f"Exit equity of ${eq_out:,}m is {moic:.1f}x the ${eq_in}m invested"},
          src=("Deal team model v9 (synthetic)",), sec="Returns"),
        S("sensitivity_table", f"IRR stays at or above {grid[0][0]:.1f}% across exit multiples of 11.0x to 13.0x",
          {"subtitle": "Gross IRR, exit multiple by FY30E EBITDA, %", "row_label": "Exit multiple, x", "col_label": "FY30E EBITDA, $m",
           "row_values": [11.0, 12.0, 13.0], "col_values": [100, 118, 130], "values": grid, "base": [1, 1],
           "takeaway": f"Base case IRR is {base_irr:.1f}% at 12.0x and $118m of EBITDA"},
          src=("Deal team model v9 (synthetic)",), sec="Returns"),
        S("risk_heatmap", "Dentist retention at 94% is the one risk that moves returns by over 3 points",
          {"subtitle": "Risk register, likelihood by impact, five-point scale", "risks": [
              {"label": "Dentist retention below 94%", "likelihood": 3, "impact": 5},
              {"label": "Add-on multiples above 6.0x", "likelihood": 3, "impact": 3},
              {"label": "Reimbursement cut of 3%", "likelihood": 2, "impact": 4},
              {"label": "Hygienist wage inflation", "likelihood": 4, "impact": 2},
              {"label": "Integration of 31 clinics", "likelihood": 3, "impact": 3}],
           "takeaway": "A retention bonus pool that vests over three years protects the largest exposure"},
          src=("Deal team risk workshop (synthetic)",), sec="Risks"),
        S("process_flow", "A four-step playbook integrates each add-on within 90 days of closing",
          {"highlight": 1, "output_label": "Output", "subtitle": "Add-on integration playbook", "steps": [
              {"name": "Close", "output": "Day 0: dentist agreements signed"}, {"name": "Migrate", "output": "Day 30: systems moved"},
              {"name": "Reprice", "output": "Day 60: fee schedule aligned"}, {"name": "Cross-sell", "output": "Day 90: hygiene hours added"}]},
          src="Operating partner playbook (synthetic)", sec="Risks"),
        S("takeaway_box", f"We recommend a $371m equity commitment for {moic:.1f}x and {base_irr:.1f}% IRR",
          {"decision": f"Approve a $371m equity commitment to the Meridian platform at {ev}m EV and 10.5x EBITDA",
           "rationale": [f"Returns: {moic:.1f}x and {base_irr:.1f}% in the base case", "Market: DSOs hold only 12% of clinics",
                         "Plan: 31 add-ons at 6.0x lift EBITDA to $118m"],
           "risks": ["Retention: 94% dentist retention is a condition", "Pricing: add-on multiples above 6.0x erode IRR"]},
          src="Deal team model v9 (synthetic)", sec="Decision"),
    ]
    req = ("Write a 10-slide investment committee memo for Project Meridian, a US dental service organisation buy-and-build: "
           "returns first, then market, platform performance, value creation bridge, sensitivity, risks and the ask. Synthetic data.")
    return make_brief("d05-ic-dental-platform", t, req, sl, client="Growth Fund II", as_of="2026-11-12")


def d06():
    t = "Project Cedar: specialty chemicals carve-out"
    sl = [
        S("cover", t, {"client": "Board of Directors", "date": "19 November 2026"},
          visual=("isometric blocks separating from a larger stack", "illustration"), sec="Answer"),
        S("exec_summary", "A trade sale of Cedar at $1,880m beats an IPO, with separation in 9 months",
          {"subtitle": "Carve-out summary, $ million", "insights": [
              {"lead": "Value", "text": "A trade sale gives the highest value of the three options", "figure": "$1,880m"},
              {"lead": "Multiple", "text": "The sale price equals this multiple of standalone EBITDA", "figure": "11.5x"},
              {"lead": "Standalone", "text": "EBITDA after new costs and transition services", "figure": "$163m"},
              {"lead": "Timing", "text": "Day-one readiness is the critical path", "figure": "9 months"}],
           "so_what": {"text": "Approve exclusive talks with the lead bidder."}},
          src=("Carve-out financials (synthetic)", "Bid summary (synthetic)"), sec="Answer"),
        S("kpi_row", "Cedar earns $196m of reported EBITDA on $1,240m of revenue, a 15.8% margin",
          {"subtitle": "Perimeter financials, FY26E, $ million", "highlight": 0, "kpis": [
              {"label": "Revenue", "value": "$1,240m", "context": "+6% on FY25", "change": {"text": "up", "direction": "up"}},
              {"label": "Reported EBITDA", "value": "$196m", "context": "15.8% margin", "change": {"text": "up", "direction": "up"}},
              {"label": "Capex", "value": "$62m", "context": "5% of revenue", "change": {"text": "flat", "direction": "flat"}},
              {"label": "Employees", "value": "2,400", "context": "In 14 sites", "change": {"text": "flat", "direction": "flat"}}],
           "so_what": "Reported EBITDA excludes the costs of running Cedar alone."},
          src="Management accounts, FY26E (synthetic)", sec="Perimeter"),
        S("waterfall", "Standalone EBITDA is $163m after $45m of standalone costs and $12m of transition services",
          {"subtitle": "Reported to standalone EBITDA, FY26E, $ million", "number_format": "0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "Reported", "value": 196}, {"label": "Allocations out", "value": 24}, {"label": "Standalone costs", "value": -45},
                     {"label": "TSA costs", "value": -12}, {"label": "Standalone", "value": 163}],
           "takeaway": "Standalone costs of $45m are the largest adjustment"},
          src=("Carve-out financials (synthetic)", "Separation plan v6 (synthetic)"), sec="Perimeter"),
        S("deal_structure", "Cedar NewCo holds 100% of the operating companies until the sale closes",
          {"subtitle": "Pre-closing structure", "entities": [
              {"id": "parent", "label": "Parent group", "sub": "Listed holding", "tier": 0},
              {"id": "newco", "label": "Cedar NewCo", "sub": "Delaware", "tier": 1, "highlight": True},
              {"id": "us", "label": "Cedar US", "sub": "Opco", "tier": 2},
              {"id": "eu", "label": "Cedar Europe", "sub": "Opco", "tier": 2},
              {"id": "asia", "label": "Cedar Asia", "sub": "Opco", "tier": 2}],
           "links": [{"from": "parent", "to": "newco", "label": "100%"}, {"from": "newco", "to": "us", "label": "100%"},
                     {"from": "newco", "to": "eu", "label": "100%"}, {"from": "newco", "to": "asia", "label": "100%"}]},
          src="Draft separation memo (synthetic)", sec="Structure"),
        S("gantt", "IT separation sets the critical path to day-one readiness in month 9",
          {"subtitle": "Separation workstreams, 2027", "today": 0.5, "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
           "workstreams": [
               {"name": "Legal entities", "bars": [{"start": 0, "end": 3, "label": "Form NewCo"}], "milestones": [{"month": 3, "label": "NewCo live"}]},
               {"name": "IT separation", "bars": [{"start": 1, "end": 8, "label": "Platform split", "highlight": True}],
                "milestones": [{"month": 8.5, "label": "Month 9: cut-over"}]},
               {"name": "TSA set-up", "bars": [{"start": 2, "end": 5, "label": "Agree services"}], "milestones": []},
               {"name": "People transfer", "bars": [{"start": 3, "end": 8, "label": "Move 2,400 staff"}], "milestones": []},
               {"name": "Financing", "bars": [{"start": 0, "end": 2}], "milestones": [{"month": 7, "label": "Funds drawn"}]}]},
          src="PMO plan v6 (synthetic)", sec="Structure"),
        S("comparison_table", "A trade sale values Cedar at $1,880m against $1,760m for an IPO",
          {"subtitle": "Exit options, $ million", "options": ["Trade sale", "IPO", "Retain"], "highlight": 0,
           "rows": [{"criterion": "Equity value", "values": ["$1,880m", "$1,760m", "$1,520m"]},
                    {"criterion": "Time to close", "values": ["7 months", "12 months", "n.a."]},
                    {"criterion": "Tax leakage", "values": ["$45m", "$20m", "$0m"]},
                    {"criterion": "Execution risk", "values": ["Low", "High", "Low"]}],
           "verdict": ["Recommended", "Window risk", "Value gap"],
           "takeaway": "A sale closes in 7 months against 12 for an IPO"},
          src=("Valuation model v4 (synthetic)",), sec="Options"),
        S("stacked_bar", "Europe and the US make up 78% of revenue, so the TSA targets two regions",
          {"subtitle": "Revenue by region, % of total", "mode": "percent", "categories": ["FY24", "FY25", "FY26E"],
           "parts": [{"name": "Europe", "values": [41, 40, 40], "key": True}, {"name": "US", "values": [36, 37, 38]},
                     {"name": "Asia", "values": [23, 23, 22]}],
           "takeaway": "Asia is 22% of revenue and needs only a light TSA"},
          src=("Management accounts (synthetic)",), sec="Options"),
        S("risk_heatmap", "3 of 5 separation risks are high impact and each needs a named owner",
          {"subtitle": "Separation risk register, five-point scale", "risks": [
              {"label": "IT cut-over slips beyond 9 months", "likelihood": 4, "impact": 5},
              {"label": "Customer consent in 3 contracts", "likelihood": 3, "impact": 4},
              {"label": "Key staff attrition above 8%", "likelihood": 3, "impact": 4},
              {"label": "Stranded costs above $45m", "likelihood": 2, "impact": 3},
              {"label": "TSA pricing dispute", "likelihood": 2, "impact": 2}],
           "takeaway": "IT cut-over is the largest exposure: likelihood 4 and impact 5"},
          src=("PMO risk workshop (synthetic)",), sec="Risks"),
        S("recommendation", "Approve exclusivity at $1,880m and a 9-month separation plan",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "next 30 days", "owner": "Deal lead", "date": "Dec 2026",
               "actions": ["Sign exclusivity at $1,880m", "Launch confirmatory diligence"]},
              {"label": "Next", "window": "months 2 to 4", "owner": "CFO", "date": "Mar 2027",
               "actions": ["Finalise the SPA and TSA scope", "Agree the $45m standalone cost plan"]},
              {"label": "Later", "window": "months 5 to 9", "owner": "COO", "date": "Sep 2027",
               "actions": ["Complete the IT cut-over", "Transfer 2,400 staff to NewCo"]}]},
          src="PMO plan v6 (synthetic)", sec="Next steps"),
    ]
    req = ("Prepare a 10-slide board paper on the carve-out of the specialty chemicals unit (Project Cedar): standalone financials, "
           "structure, separation plan, exit options (sale, IPO, retain), risks and the decision requested. Synthetic data.")
    return make_brief("d06-carve-out", t, req, sl, client="Board of Directors", as_of="2026-11-19", art="isometric_system")


def d07():
    t = "Project Orion: buy-side diligence summary"
    sl = [
        S("cover", t, {"client": "Orion Holdings, deal team", "date": "5 November 2026"},
          visual=("clean line schematic of a freight network", "diagram"), sec="Answer"),
        S("exec_summary", "Diligence supports $79.3m of adjusted EBITDA and a price of up to $872m",
          {"subtitle": "Diligence conclusions, $ million", "insights": [
              {"lead": "Earnings", "text": "Quality of earnings adjustments lift reported EBITDA of $74.0m", "figure": "$79.3m"},
              {"lead": "Price", "text": "At 11.0x the adjusted EBITDA implies this enterprise value", "figure": "$872m"},
              {"lead": "Concentration", "text": "The top-5 customers account for this share of revenue", "figure": "46%"},
              {"lead": "Working capital", "text": "A normalised peg is set above the seller proposal", "figure": "$38m"}],
           "so_what": {"text": "Proceed to signing with three price protections."}},
          src=("Quality of earnings report (synthetic)", "Commercial diligence (synthetic)"), sec="Answer"),
        S("waterfall", "Adjusted EBITDA is $79.3m after $4.5m of one-offs and $3.6m of contract run-rate",
          {"subtitle": "Quality of earnings bridge, LTM, $ million", "number_format": "0.0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "Reported EBITDA", "value": 74.0}, {"label": "One-off costs", "value": 4.5}, {"label": "Out-of-period", "value": -2.8},
                     {"label": "Contract run-rate", "value": 3.6}, {"label": "Adjusted EBITDA", "value": 79.3}],
           "takeaway": "Out-of-period items reduce EBITDA by $2.8m"},
          src=("Quality of earnings report (synthetic)",), sec="Financial"),
        S("scorecard", "Margins improved while growth slowed, and cash conversion fell to 78% in the latest quarter",
          {"subtitle": "KPI scorecard, last five quarters", "periods": ["Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26"], "kpis": [
              {"name": "Revenue ($m)", "format": "usd_m", "values": [168, 172, 175, 181, 184]},
              {"name": "EBITDA margin", "format": "pct", "values": [12.9, 13.1, 13.2, 13.4, 13.6]},
              {"name": "Cash conversion", "format": "pct", "values": [86, 84, 83, 80, 78], "good_up": True},
              {"name": "Utilisation", "format": "pct", "values": [81, 82, 82, 80, 79]}],
           "takeaway": "Cash conversion fell 8 points in four quarters to 78%"},
          src=("Management accounts (synthetic)",), sec="Financial"),
        S("stacked_bar", "The top-5 customers are 46% of revenue and their contracts run to 2028",
          {"subtitle": "Revenue by customer group, % of total", "mode": "percent", "categories": ["FY24", "FY25", "LTM"],
           "parts": [{"name": "Top 5", "values": [41, 44, 46], "key": True}, {"name": "Next 15", "values": [27, 26, 25]},
                     {"name": "Others", "values": [32, 30, 29]}],
           "takeaway": "Concentration rose 5 points in two years, to 46%"},
          src=("Commercial diligence (synthetic)",), sec="Commercial"),
        S("harvey_table", "Orion beats the market on network density and trails on digital booking at 0.5",
          {"subtitle": "Capability coverage versus the market, harvey balls from none to full", "peers": ["Target", "Peer A", "Peer B", "Peer C"],
           "highlight": 0, "capabilities": [
               {"name": "Network density", "values": [1, 0.75, 0.5, 0.5]}, {"name": "Fleet age", "values": [0.75, 0.5, 0.5, 0.25]},
               {"name": "Digital booking", "values": [0.5, 1, 0.75, 0.75]}, {"name": "Customer service", "values": [0.75, 0.75, 0.5, 0.5]},
               {"name": "Pricing power", "values": [0.75, 0.5, 0.75, 0.25]}],
           "takeaway": "Digital booking is the gap: 0.5 against 1.0 for Peer A"},
          src=("Customer interviews (synthetic)",), sec="Commercial"),
        S("risk_heatmap", "3 findings carry price protection: renewals, tax and the working capital peg",
          {"subtitle": "Findings, likelihood by impact, five-point scale", "risks": [
              {"label": "Top-5 contract renewals in 2028", "likelihood": 3, "impact": 5},
              {"label": "Transfer pricing exposure of $9m", "likelihood": 3, "impact": 3},
              {"label": "Working capital peg gap of $38m", "likelihood": 4, "impact": 3},
              {"label": "Fleet capex backlog of $22m", "likelihood": 2, "impact": 3},
              {"label": "Driver retention", "likelihood": 2, "impact": 2}],
           "takeaway": "Renewal risk is the largest exposure and an earn-out of 5% covers it"},
          src=("Diligence workstream leads (synthetic)",), sec="Risks"),
        S("comparison_table", "Three price protections move $31m of risk back to the seller",
          {"subtitle": "Proposed protections, $ million", "options": ["Seller offer", "Our counter"], "highlight": 1,
           "rows": [{"criterion": "Working capital peg", "values": ["$31m", "$38m"]},
                    {"criterion": "Tax indemnity cap", "values": ["$5m", "$9m"]},
                    {"criterion": "Earn-out on renewals", "values": ["None", "5%"]}],
           "verdict": ["Insufficient", "Recommended"], "takeaway": "Our counter lifts the peg by $7m and the tax cap by $4m"},
          src=("SPA term sheet, draft 3 (synthetic)",), sec="Price"),
        S("timeline_milestones", "Signing by 4 December needs the three protections agreed by 20 November",
          {"subtitle": "Path to signing, 2026", "milestones": [
              {"date": "5 Nov", "label": "Diligence summary"}, {"date": "12 Nov", "label": "Counter sent"},
              {"date": "20 Nov", "label": "Protections agreed", "highlight": True}, {"date": "27 Nov", "label": "SPA final form"},
              {"date": "4 Dec", "label": "Signing", "highlight": True}], "takeaway": "Signing needs agreement on 20 Nov"},
          src=("Deal timetable (synthetic)",), sec="Price"),
        S("takeaway_box", "We recommend signing at up to $872m with the three protections in place",
          {"decision": "Sign at up to $872m EV, or 11.0x adjusted EBITDA of $79.3m, with the three protections",
           "rationale": ["Earnings: adjusted EBITDA is $79.3m after $4.5m of one-offs", "Price: 11.0x is in line with precedents",
                         "Protection: peg of $38m and tax cap of $9m"],
           "risks": ["Concentration: top-5 customers are 46% of revenue", "Renewals: 2028 expiries covered by a 5% earn-out"]},
          src="Quality of earnings report (synthetic)", sec="Decision"),
    ]
    req = ("Summarise buy-side due diligence for Project Orion, a logistics acquisition, in 10 slides for the deal team: quality of earnings, "
           "KPIs, customer concentration, commercial position, findings with price protection and the path to signing. Synthetic data.")
    return make_brief("d07-buy-side-diligence", t, req, sl, client="Orion Holdings", as_of="2026-11-05")


def d08():
    t = "Atlas Foods: third quarter FY26 earnings recap"
    sl = [
        S("cover", t, {"client": "Equity research, consumer staples", "date": "4 November 2026"},
          visual=("abstract grain and bar shapes, warm greys", "hero"), sec="Answer"),
        S("exec_summary", "Atlas beat on EPS by 6% and raised full-year guidance to $4.05 to $4.15",
          {"subtitle": "Third quarter FY26, per share unless stated", "insights": [
              {"lead": "EPS", "text": "Adjusted EPS beat the consensus estimate of $1.00", "figure": "$1.06"},
              {"lead": "Sales", "text": "Organic sales growth beat on pricing and mix", "figure": "+4.8%"},
              {"lead": "Margin", "text": "Gross margin expanded as input costs eased", "figure": "34.2%"},
              {"lead": "Guide", "text": "Full-year EPS guidance was raised from $3.95 to $4.05", "figure": "$4.05 to $4.15"}],
           "so_what": {"text": "We raise our price target and keep an overweight rating."}},
          src=("Company earnings release, 3 Nov 2026 (synthetic)", "Consensus survey (synthetic)"), sec="Answer"),
        S("kpi_row", "Third quarter EPS of $1.06 beat consensus of $1.00 on 4.8% organic growth",
          {"subtitle": "Third quarter FY26 versus consensus", "highlight": 0, "kpis": [
              {"label": "Adjusted EPS", "value": "$1.06", "context": "Consensus $1.00", "change": {"text": "+6.0% beat", "direction": "up"}},
              {"label": "Net sales", "value": "$3.42bn", "context": "Consensus $3.38bn", "change": {"text": "+4.8% org.", "direction": "up"}},
              {"label": "Gross margin", "value": "34.2%", "context": "+110 bps on 33.1%", "change": {"text": "up", "direction": "up"}},
              {"label": "Free cash flow", "value": "$410m", "context": "Prior year $355m", "change": {"text": "+15.5%", "direction": "up"}}],
           "so_what": "Margin, not volume, drove the beat."},
          src="Company earnings release, 3 Nov 2026 (synthetic)", sec="Results"),
        S("waterfall", "EPS rose $0.12 to $1.06 as price and cost savings outweighed higher marketing",
          {"subtitle": "Adjusted EPS bridge, Q3 FY25 to Q3 FY26, $ per share", "number_format": "0.00", "prefix": "$", "suffix": "",
           "steps": [{"label": "Q3 FY25", "value": 0.94}, {"label": "Price and mix", "value": 0.11}, {"label": "Volume", "value": 0.02},
                     {"label": "Input costs", "value": 0.06}, {"label": "Marketing", "value": -0.05}, {"label": "Tax and other", "value": -0.02},
                     {"label": "Q3 FY26", "value": 1.06}],
           "takeaway": "Price and mix add $0.11 and input costs add $0.06"},
          src=("Company earnings release, 3 Nov 2026 (synthetic)",), sec="Results"),
        S("annotated_line", "Gross margin reaches 34.2%, 110 bps above last year, as input costs ease",
          {"subtitle": "Gross margin, quarterly, %", "number_format": "0.0", "change_unit": "pp",
           "categories": ["Q4 FY24", "Q1 FY25", "Q2 FY25", "Q3 FY25", "Q4 FY25", "Q1 FY26", "Q2 FY26", "Q3 FY26"],
           "series": [{"name": "Atlas gross margin", "values": [32.4, 32.8, 32.9, 33.1, 33.4, 33.6, 33.9, 34.2]},
                      {"name": "Peer median", "values": [33.0, 33.1, 33.2, 33.3, 33.4, 33.5, 33.6, 33.7]}],
           "annotation": {"at": 4, "text": "Commodity costs peak in Q4 FY25"},
           "takeaway": "Atlas now earns 0.5 points more than the peer median of 33.7%"},
          src=("Company filings (synthetic)", "Peer filings, median of six (synthetic)"), sec="Results"),
        S("small_multiples", "Three of four segments grew sales, with Snacks up 7% and Beverages down 2%",
          {"subtitle": "Net sales growth by segment, last four quarters, %", "number_format": "0",
           "panels": [{"title": "Snacks", "categories": ["Q4", "Q1", "Q2", "Q3"], "values": [4, 5, 6, 7]},
                      {"title": "Frozen", "categories": ["Q4", "Q1", "Q2", "Q3"], "values": [2, 3, 3, 4]},
                      {"title": "Beverages", "categories": ["Q4", "Q1", "Q2", "Q3"], "values": [1, 0, -1, -2]},
                      {"title": "Pet food", "categories": ["Q4", "Q1", "Q2", "Q3"], "values": [3, 4, 4, 5]}],
           "takeaway": "Beverages has declined for three quarters, by 2% in Q3"},
          src=("Company segment disclosure (synthetic)",), sec="Results"),
        S("comparison_table", "Guidance for FY26 EPS rose by $0.10 to $4.05 to $4.15, above consensus of $4.02",
          {"subtitle": "Full-year FY26 guidance, per share unless stated", "options": ["Prior guide", "New guide", "Consensus"], "highlight": 1,
           "rows": [{"criterion": "Adjusted EPS", "values": ["$3.95 to $4.05", "$4.05 to $4.15", "$4.02"]},
                    {"criterion": "Organic growth", "values": ["3% to 4%", "4% to 5%", "4.1%"]},
                    {"criterion": "Gross margin", "values": ["33.5%", "34.0%", "33.8%"]}],
           "verdict": ["Superseded", "Raised", "Below"], "takeaway": "The new guide is $0.03 above consensus at the low end"},
          src=("Company earnings release (synthetic)", "Consensus survey (synthetic)"), sec="Outlook"),
        S("takeaway_box", "We raise our price target to $78 and keep the overweight rating",
          {"decision": "Raise the price target to $78 from $72, 18.4x FY27E EPS, and keep the overweight rating",
           "rationale": ["Earnings: FY26E EPS rises to $4.10", "Margin: input costs support 34.0% gross margin", "Cash: free cash flow up 15.5%"],
           "risks": ["Beverages: sales decline of 2% may spread", "Marketing: spend rose in Q3"]},
          src="Research model (synthetic)", sec="Outlook"),
    ]
    req = ("Write an 8-slide third-quarter earnings recap for Atlas Foods, a US consumer staples company: the beat, bridge, margin trend, "
           "segments, guidance changes and our rating. Synthetic figures.")
    return make_brief("d08-earnings-recap", t, req, sl, client="Equity research", as_of="2026-11-04")


def d09():
    t = "US regional banks: third quarter sector update"
    sl = [
        S("cover", t, {"client": "Financial institutions group", "date": "10 November 2026"},
          visual=("data dots drifting across a grid in blue and grey", "hero"), sec="Answer"),
        S("exec_summary", "Regional bank margins turned up in Q3 as NIM reached 3.38%, and valuations lag",
          {"subtitle": "Sector summary, 24 regional banks", "insights": [
              {"lead": "Margin", "text": "Sector net interest margin recovers on fixed-asset repricing", "figure": "3.38%"},
              {"lead": "Funding", "text": "Non-interest deposits stabilise as a share of funding", "figure": "24%"},
              {"lead": "Capital", "text": "Median CET1 ratio sits comfortably above requirements", "figure": "11.2%"},
              {"lead": "Valuation", "text": "The sector trades at a discount to tangible book", "figure": "1.4x"}],
           "so_what": {"text": "Favour banks with high deposit growth and low securities losses."}},
          src=("Company filings, Q3 2026 (synthetic)", "Market data, 6 Nov 2026 (synthetic)"), sec="Answer"),
        S("annotated_line", "Sector NIM rose to 3.38% in Q3, 21 bps above its Q1 2026 low",
          {"subtitle": "Median net interest margin, quarterly, %", "number_format": "0.00", "change_unit": "pp",
           "categories": ["Q1 25", "Q2 25", "Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26"],
           "series": [{"name": "Regional bank median", "values": [3.31, 3.26, 3.22, 3.19, 3.17, 3.28, 3.38]},
                      {"name": "Large bank median", "values": [2.62, 2.64, 2.66, 2.68, 2.70, 2.73, 2.75]}],
           "annotation": {"at": 4, "text": "Low point after funding costs peak"},
           "takeaway": "Regional banks earn 3.38% against 2.75% for large banks"},
          src=("Company filings (synthetic)", "FFIEC call reports (synthetic)"), sec="Earnings"),
        S("stacked_column", "Non-interest deposits stabilise at 24% of funding after falling from 31% in 2022",
          {"subtitle": "Deposit mix, year end, % of total deposits", "mode": "percent",
           "categories": ["2022", "2023", "2024", "2025", "Q3 26"],
           "parts": [{"name": "Non-interest bearing", "values": [31, 27, 25, 24, 24], "key": True},
                     {"name": "Savings and money market", "values": [44, 46, 47, 48, 48]}, {"name": "Time deposits", "values": [25, 27, 28, 28, 28]}],
           "takeaway": "The mix has been stable at 24% for three quarters"},
          src=("Company filings (synthetic)",), sec="Earnings"),
        S("scatter_quadrant", "Returns explain valuation: each point of ROTCE is worth about 0.1x of tangible book",
          {"subtitle": "Price to tangible book versus ROTCE, 10 banks", "x_title": "ROTCE, %", "y_title": "Price to tangible book, x",
           "x_format": "0.0", "y_format": "0.0", "points": [
               {"label": "Northgate", "xv": 17.2, "yv": 2.0}, {"label": "Harbor Trust", "xv": 15.8, "yv": 1.8}, {"label": "Summit", "xv": 14.1, "yv": 1.6},
               {"label": "Pinecrest", "xv": 12.9, "yv": 1.5}, {"label": "Lakeshore", "xv": 11.5, "yv": 1.3, "subject": True},
               {"label": "Ridgeway", "xv": 10.4, "yv": 1.2}, {"label": "Cedar Valley", "xv": 9.1, "yv": 1.0}, {"label": "Mesa", "xv": 8.2, "yv": 0.9}],
           "stat": {"value": "0.1x", "label": "valuation per point of ROTCE across the set"},
           "takeaway": "Lakeshore trades at 1.3x with 11.5% ROTCE, in line with the line of fit"},
          src=("Company filings (synthetic)", "Market data, 6 Nov 2026 (synthetic)"), sec="Valuation"),
        S("ranked_bar", "Lakeshore trades at 1.3x tangible book, fifth of 8 and below the 1.4x median",
          {"subtitle": "Price to tangible book, x", "number_format": "0.0\"x\"", "series_name": "P/TBV", "items": [
              {"label": "Northgate", "value": 2.0}, {"label": "Harbor Trust", "value": 1.8}, {"label": "Summit", "value": 1.6},
              {"label": "Pinecrest", "value": 1.5}, {"label": "Lakeshore", "value": 1.3, "key": True}, {"label": "Ridgeway", "value": 1.2},
              {"label": "Cedar Valley", "value": 1.0}, {"label": "Mesa", "value": 0.9}],
           "stat": {"value": "-0.1x", "label": "discount to the peer median of 1.4x"},
           "takeaway": "Re-rating to the median adds 0.1x of tangible book"},
          src=("Market data, 6 Nov 2026 (synthetic)",), sec="Valuation"),
        S("comps_table", "The sector median trades at 1.4x tangible book with 12.9% ROTCE and 11.2% CET1",
          {"subtitle": "Regional bank comparables, EV not shown, multiples on Q3 2026", "dense": True, "compute_stats": True, "rows": [
              {"company": "Northgate", "ev": 21.4, "ev_ebitda": 9.8, "pe": 11.2, "growth": 6.1, "margin": 41.0},
              {"company": "Harbor Trust", "ev": 14.2, "ev_ebitda": 9.1, "pe": 10.6, "growth": 5.4, "margin": 38.5},
              {"company": "Summit", "ev": 11.8, "ev_ebitda": 8.4, "pe": 9.9, "growth": 4.7, "margin": 36.2},
              {"company": "Pinecrest", "ev": 9.3, "ev_ebitda": 7.9, "pe": 9.4, "growth": 4.1, "margin": 34.8},
              {"company": "Lakeshore", "ev": 7.6, "ev_ebitda": 7.2, "pe": 8.8, "growth": 3.6, "margin": 33.1}],
           "takeaway": "Median price to earnings is 9.9x on 4.7% revenue growth"},
          src=("Market data, 6 Nov 2026 (synthetic)",), sec="Valuation"),
        S("numbered_insights", "Three screens identify 4 of the 24 banks where earnings can beat consensus",
          {"subtitle": "Stock-selection screens", "layout": "row", "insights": [
              {"title": "Deposit growth", "text": "Deposits growing faster than loans fund margin expansion", "figure": "+5.2%"},
              {"title": "Securities losses", "text": "Unrealised losses below this share of tangible equity", "figure": "12%"},
              {"title": "Credit costs", "text": "Net charge-offs at or below the sector median", "figure": "0.31%"}]},
          src="Screening model (synthetic)", sec="Positioning"),
        S("takeaway_box", "We prefer four banks with deposit growth above 5% and unrealised losses below 12%",
          {"decision": "Overweight banks with deposit growth above 5.2% and securities losses below 12% of tangible equity",
           "rationale": ["Margin: NIM of 3.38% is still rising", "Valuation: 1.4x tangible book lags returns",
                         "Capital: CET1 of 11.2% supports buybacks"],
           "risks": ["Credit: charge-offs of 0.31% could rise", "Rates: a flat curve caps margin gains"]},
          src="Screening model (synthetic)", sec="Positioning"),
    ]
    req = ("Write a 9-slide third-quarter sector update on US regional banks for the financial institutions group: net interest margin, "
           "funding mix, valuation versus returns, comparables and our stock-selection screens. Synthetic data, as of 10 November 2026.")
    return make_brief("d09-sector-update-banks", t, req, sl, client="Financial institutions group", as_of="2026-11-10", art="data_art")


ALL = [d05, d06, d07, d08, d09]
