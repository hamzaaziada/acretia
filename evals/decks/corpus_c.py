"""Corpus decks 10-13 (synthetic data; project names are fictional)."""
from evals.decks._lib import S, make_brief


def d10():
    t = "Project Anchor: liquidity and restructuring options"
    sl = [
        S("cover", t, {"client": "Board and lender steering group", "date": "9 November 2026"},
          visual=("an anchor line cutting across stacked flat shapes", "illustration"), sec="Answer"),
        S("exec_summary", "Amend and extend closes the liquidity gap and returns 78% to term lenders",
          {"subtitle": "Restructuring summary, $ million", "insights": [
              {"lead": "Gap", "text": "Liquidity turns negative in week 10 and reaches this low point", "figure": "$9m"},
              {"lead": "Leverage", "text": "Total debt is this multiple of LTM EBITDA of $78m", "figure": "11.2x"},
              {"lead": "Option", "text": "Amend and extend returns this share to term loan lenders", "figure": "78%"},
              {"lead": "New money", "text": "Sponsor and lenders inject liquidity at signing", "figure": "$60m"}],
           "so_what": {"text": "Open a 30-day standstill and agree term sheets with lenders."}},
          src=("13-week cash flow forecast (synthetic)", "Lender recovery model (synthetic)"), sec="Answer"),
        S("kpi_row", "Debt of $870m is 11.2x EBITDA and cash of $42m covers 6 weeks of outflows",
          {"subtitle": "Capital structure and liquidity, $ million", "highlight": 2, "kpis": [
              {"label": "Total debt", "value": "$870m", "context": "Three tranches", "change": {"text": "flat", "direction": "flat"}},
              {"label": "LTM EBITDA", "value": "$78m", "context": "Down from $96m", "change": {"text": "-19%", "direction": "down"}},
              {"label": "Debt / EBITDA", "value": "11.2x", "context": "Covenant at 6.0x", "change": {"text": "+3.2x", "direction": "down"}},
              {"label": "Cash", "value": "$42m", "context": "6 weeks of outflows", "change": {"text": "-$30m", "direction": "down"}}],
           "so_what": "Covenant breach is certain at the December test date."},
          src="Management accounts, Oct 2026 (synthetic)", sec="Situation"),
        S("annotated_line", "Liquidity turns negative in week 10 and bottoms at a $9m shortfall",
          {"subtitle": "Weekly liquidity, 13-week forecast, $ million", "number_format": "0", "change_unit": "m",
           "categories": [f"Wk {i}" for i in range(1, 14)],
           "series": [{"name": "Liquidity", "values": [42, 38, 33, 27, 21, 16, 12, 8, 3, -2, -9, -4, 6]}],
           "annotation": {"at": 10, "text": "Shortfall of $9m in week 11"},
           "takeaway": "Cash falls from $42m to a low of -$9m before inventory sales help"},
          src=("13-week cash flow forecast (synthetic)",), sec="Situation"),
        S("waterfall", "Interest of $29m and capex of $16m outweigh $11m of operating cash flow",
          {"subtitle": "13-week cash bridge, $ million", "number_format": "0", "prefix": "$", "suffix": "m",
           "steps": [{"label": "Opening cash", "value": 42}, {"label": "Inventory sale", "value": 12}, {"label": "Operations", "value": 11},
                     {"label": "Capex", "value": -16}, {"label": "Interest", "value": -29}, {"label": "Rent and tax", "value": -14},
                     {"label": "Week 13 cash", "value": 6}],
           "takeaway": "Inventory sales of $12m are needed to end week 13 at $6m"},
          src=("13-week cash flow forecast (synthetic)",), sec="Situation"),
        S("ranked_bar", "Debt of $870m is 11.2x EBITDA, and the $450m term loan matures in 2027",
          {"subtitle": "Debt by tranche, $ million", "number_format": "0", "series_name": "Debt", "items": [
              {"label": "Term loan, due 2027", "value": 450, "key": True}, {"label": "Senior notes, due 2028", "value": 300},
              {"label": "Revolver, due 2026", "value": 120}],
           "stat": {"value": "11.2x", "label": "total debt of $870m to LTM EBITDA of $78m"},
           "takeaway": "The revolver of $120m matures first, in 2026"},
          src=("Facility agreements (synthetic)",), sec="Options"),
        S("comparison_table", "Amend and extend returns 78% to term lenders in 4 months, the best option",
          {"subtitle": "Restructuring options, term lender view", "options": ["Amend and extend", "Debt-for-equity", "Sale of group", "Court process"],
           "highlight": 0, "rows": [
               {"criterion": "Term lender recovery", "values": ["78%", "64%", "71%", "52%"]},
               {"criterion": "Time to complete", "values": ["4 months", "6 months", "8 months", "10 months"]},
               {"criterion": "New money", "values": ["$60m", "$90m", "$0m", "$40m"]},
               {"criterion": "Execution risk", "values": ["Medium", "Medium", "High", "High"]}],
           "verdict": ["Recommended", "Fallback", "Slow", "Last resort"],
           "takeaway": "Debt-for-equity adds $30m of new money but recovers 64%"},
          src=("Lender recovery model (synthetic)", "Advisor analysis (synthetic)"), sec="Options"),
        S("paired_bars", "Senior notes recover 48% in debt-for-equity against 35% under amend and extend",
          {"subtitle": "Recovery by tranche, % of claim", "number_format": "0",
           "categories": ["Revolver", "Term loan", "Senior notes"],
           "before": {"name": "Amend and extend", "values": [100, 78, 35]}, "after": {"name": "Debt-for-equity", "values": [100, 64, 48]},
           "stat": {"value": "+13pp", "label": "gain for senior notes under debt-for-equity"},
           "takeaway": "Noteholders prefer debt-for-equity; term lenders prefer amend and extend"},
          src=("Lender recovery model (synthetic)",), sec="Options"),
        S("timeline_milestones", "A 30-day standstill leads to lender votes by 15 January",
          {"subtitle": "Restructuring timetable, 2026 to 2027", "milestones": [
              {"date": "16 Nov", "label": "Standstill signed", "highlight": True}, {"date": "30 Nov", "label": "Term sheets exchanged"},
              {"date": "15 Dec", "label": "Covenant test date"}, {"date": "15 Jan", "label": "Lender votes", "highlight": True},
              {"date": "28 Feb", "label": "Effective date"}], "takeaway": "Votes on 15 Jan precede the effective date of 28 Feb"},
          src=("Process timetable (synthetic)",), sec="Plan"),
        S("recommendation", "Open the 30-day standstill and inject $60m of new money in 4 months",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "next 30 days", "owner": "CFO", "date": "Nov 2026",
               "actions": ["Sign the standstill with lenders", "Draw the interim facility"]},
              {"label": "Next", "window": "30 to 60 days", "owner": "CEO", "date": "Jan 2027",
               "actions": ["Agree the amend-and-extend terms", "Run the lender vote on 15 Jan"]},
              {"label": "Later", "window": "60 to 120 days", "owner": "CRO", "date": "Feb 2027",
               "actions": ["Inject $60m of new money", "Reset covenants at 6.0x"]}]},
          src="Process timetable (synthetic)", sec="Plan"),
    ]
    req = ("Prepare a 10-slide restructuring options paper for Project Anchor, an over-levered retail group: liquidity runway, debt stack, "
           "options compared on recovery and time, and the recommended path with timetable. Synthetic data.")
    return make_brief("d10-restructuring-options", t, req, sl, client="Board and lender steering group", as_of="2026-11-09")


def d11():
    t = "Project Lighthouse: valuation summary for the board"
    sl = [
        S("cover", t, {"client": "Board of Directors, Lighthouse Corp", "date": "13 November 2026"},
          visual=("huge segmented numerals as flat geometric forms", "hero"), sec="Answer"),
        S("exec_summary", "The $58.00 offer sits above the midpoint of four of six valuation methods",
          {"subtitle": "Valuation summary, $ per share", "insights": [
              {"lead": "Offer", "text": "All-cash offer from the bidder, per share", "figure": "$58.00"},
              {"lead": "Premium", "text": "Premium to the unaffected share price of $44.10", "figure": "31.5%"},
              {"lead": "DCF", "text": "The standalone DCF midpoint sits near the offer", "figure": "$59.00"},
              {"lead": "Peers", "text": "The offer implies this multiple against a peer median of 11.4x", "figure": "12.6x"}],
           "so_what": {"text": "Recommend the board accept the offer, subject to the fairness opinion."}},
          src=("Market data, 12 Nov 2026 (synthetic)", "Advisor valuation model (synthetic)"), sec="Answer"),
        S("football_field", "The $58.00 offer is above the unaffected price of $44.10 and inside four ranges",
          {"subtitle": "Equity value per share by method, $", "prefix": "$", "number_format": "0.00", "current_price": 44.10, "implied": 58.00,
           "methods": [{"label": "DCF, WACC 8.5% to 9.5%", "low": 52.00, "high": 66.00, "key": True},
                       {"label": "Trading comps", "low": 46.00, "high": 58.00}, {"label": "Precedent transactions", "low": 50.00, "high": 64.00},
                       {"label": "Premiums paid", "low": 55.00, "high": 62.00}, {"label": "52-week range", "low": 38.50, "high": 49.80},
                       {"label": "Analyst targets", "low": 47.00, "high": 60.00}],
           "takeaway": "The offer is above the 52-week high of $49.80"},
          src=("Advisor valuation model (synthetic)", "Market data, 12 Nov 2026 (synthetic)"), sec="Valuation"),
        S("annotated_line", "The share price peaked at $49.80 in August and closed unaffected at $44.10",
          {"subtitle": "Month-end share price, last 12 months, $", "number_format": "0.00", "change_unit": "$",
           "categories": ["Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov"],
           "series": [{"name": "Lighthouse", "values": [41.2, 39.6, 38.5, 40.1, 42.8, 44.7, 47.9, 49.8, 48.2, 46.4, 45.0, 44.1]}],
           "annotation": {"at": 7, "text": "52-week high of $49.80"},
           "takeaway": "The offer of $58.00 is above every month-end close"},
          src=("Market data, 12 Nov 2026 (synthetic)",), sec="Valuation"),
        S("ranked_bar", "The offer is a 31.5% premium and 16.5% above the 52-week high",
          {"subtitle": "Offer premium by reference point, %", "number_format": "0.0", "series_name": "Premium", "items": [
              {"label": "Unaffected price", "value": 31.5, "key": True}, {"label": "30-day VWAP", "value": 27.8},
              {"label": "90-day VWAP", "value": 24.7}, {"label": "52-week high", "value": 16.5}],
           "stat": {"value": "31.5%", "label": "premium to the unaffected price of $44.10"},
           "takeaway": "Premiums paid in comparable deals range from 25% to 40%"},
          src=("Market data, 12 Nov 2026 (synthetic)", "Deal database extract (synthetic)"), sec="Valuation"),
        S("comps_table", "Peers trade at a median 11.4x EBITDA, and the offer implies 12.6x",
          {"subtitle": "Trading comparables, NTM multiples, EV in $ billion", "compute_stats": True, "dense": True, "rows": [
              {"company": "Beacon Systems", "ev": 8.4, "ev_ebitda": 13.1, "pe": 19.4, "growth": 7.8, "margin": 24.6},
              {"company": "Harbor Controls", "ev": 6.2, "ev_ebitda": 12.0, "pe": 18.1, "growth": 6.9, "margin": 23.0},
              {"company": "Keystone Devices", "ev": 5.1, "ev_ebitda": 11.6, "pe": 17.0, "growth": 6.1, "margin": 22.2},
              {"company": "Summit Instruments", "ev": 4.3, "ev_ebitda": 11.2, "pe": 16.6, "growth": 5.4, "margin": 21.5},
              {"company": "Pioneer Sensors", "ev": 3.2, "ev_ebitda": 10.4, "pe": 15.2, "growth": 4.6, "margin": 20.1},
              {"company": "Vector Optics", "ev": 2.6, "ev_ebitda": 9.7, "pe": 14.3, "growth": 3.8, "margin": 18.8}],
           "takeaway": "The offer multiple of 12.6x is above the peer median of 11.4x"},
          src=("Market data, 12 Nov 2026 (synthetic)",), sec="Valuation"),
        S("tombstones", "Precedent deals cleared 10.2x to 13.4x EBITDA, with the offer at 12.6x",
          {"subtitle": "Precedent transactions, EV in $ billion, EV/EBITDA", "deals": [
              {"acquirer": "Our bidder", "target": "Lighthouse Corp", "date": "Nov 2026", "ev": 5.4, "multiple": 12.6, "highlight": True},
              {"acquirer": "Strategic A", "target": "Prism Optics", "date": "Jun 2026", "ev": 3.1, "multiple": 13.4},
              {"acquirer": "Sponsor B", "target": "Orion Sensing", "date": "Mar 2026", "ev": 2.4, "multiple": 10.2},
              {"acquirer": "Strategic C", "target": "Delta Controls", "date": "Jan 2026", "ev": 4.2, "multiple": 12.9},
              {"acquirer": "Strategic D", "target": "Nova Devices", "date": "Oct 2025", "ev": 1.9, "multiple": 11.5},
              {"acquirer": "Sponsor E", "target": "Quill Systems", "date": "Jul 2025", "ev": 2.8, "multiple": 11.1}],
           "takeaway": "Strategic buyers paid 11.5x to 13.4x; the offer is within that band"},
          src=("Company announcements (synthetic)",), sec="Valuation"),
        S("sensitivity_table", "DCF value per share spans $50.60 to $76.20 across WACC and terminal growth",
          {"subtitle": "Value per share, WACC by terminal growth, $", "row_label": "WACC, %", "col_label": "Terminal growth, %",
           "row_values": [8.0, 8.5, 9.0, 9.5, 10.0], "col_values": [2.0, 2.5, 3.0, 3.5, 4.0], "value_format": "0.00",
           "values": [[58.10, 61.40, 65.30, 70.10, 76.20], [53.20, 55.90, 59.00, 62.80, 67.50], [49.00, 51.20, 53.80, 56.90, 60.60],
                      [45.40, 47.30, 49.50, 52.10, 55.20], [42.30, 43.90, 45.80, 48.00, 50.60]], "base": [1, 2],
           "takeaway": "The base case of $59.00 is at 8.5% WACC and 3.0% growth"},
          src=("Advisor DCF model, management plan (synthetic)",), sec="Valuation"),
        S("two_column_compare", "Accepting at $58.00 beats the standalone value of $51.00 per share",
          {"emphasis": "a", "a": {"heading": "Accept the offer", "metric": "$58.00", "points": [
              "Value: cash certainty at a 31.5% premium", "Timing: closing within 6 months", "Risk: regulatory approval only"]},
           "b": {"heading": "Remain standalone", "metric": "$51.00", "points": [
              "Value: the plan needs three years of delivery", "Timing: no closing risk", "Risk: input costs and execution"]},
           "verdict": "Accepting is worth $7.00 per share more than the risk-adjusted standalone value."},
          src=("Advisor valuation model (synthetic)",), sec="Conclusion"),
        S("takeaway_box", "We recommend the board approve the $58.00 per share cash offer",
          {"decision": "Approve the $58.00 per share all-cash offer, a 31.5% premium, subject to the fairness opinion",
           "rationale": ["Value: above four of six valuation ranges", "Premium: above the 25% to 40% band midpoint", "Certainty: cash with 6 months to close"],
           "risks": ["Approval: regulatory review may extend closing", "Price: DCF upside to $66.00 is not captured"]},
          src="Advisor valuation model (synthetic)", sec="Conclusion"),
    ]
    req = ("Write a 10-slide valuation summary for the board of Lighthouse Corp, a US listed company receiving a $58.00 per share cash offer: "
           "football field, share price history, premium analysis, comps, precedents, DCF sensitivity and a recommendation. Synthetic data.")
    return make_brief("d11-fairness-valuation", t, req, sl, client="Board of Directors", as_of="2026-11-13", art="bold_typographic")


def d12():
    t = "Redwood Industries: third quarter FY26 board update"
    sl = [
        S("cover", t, {"client": "Board of Directors", "date": "18 November 2026"},
          visual=("layered flat forest and factory shapes", "hero"), sec="Answer"),
        S("exec_summary", "Redwood grew revenue 5.6% to $842m, and the cost programme has delivered $48m",
          {"subtitle": "Quarterly summary, $ million", "insights": [
              {"lead": "Revenue", "text": "Third quarter revenue grew on price and volume", "figure": "$842m"},
              {"lead": "Earnings", "text": "Adjusted EBITDA margin improved on cost savings", "figure": "17.9%"},
              {"lead": "Savings", "text": "Cost programme savings captured year to date", "figure": "$48m"},
              {"lead": "Decisions", "text": "Three approvals are requested at this meeting", "figure": "$65m"}],
           "so_what": {"text": "Approve the plant 4 capex, the dividend increase and the buyback."}},
          src=("Management accounts, Q3 FY26 (synthetic)", "Cost programme tracker (synthetic)"), sec="Answer"),
        S("agenda", "Today we cover results, the cost programme and the decisions",
          {"current": 0, "items": [{"title": "Q3 results", "detail": "Revenue, margin and KPIs", "time": "15 min"},
                                   {"title": "Cost programme", "detail": "Savings and timetable", "time": "15 min"},
                                   {"title": "Decisions", "detail": "Capex, dividend, buyback", "time": "20 min"}]}, sec="Answer"),
        S("kpi_row", "Third quarter revenue of $842m and adjusted EBITDA of $151m both beat plan",
          {"subtitle": "Q3 FY26 versus plan, $ million", "highlight": 1, "kpis": [
              {"label": "Revenue", "value": "$842m", "context": "+5.6% YoY, plan $825m", "change": {"text": "beat", "direction": "up"}},
              {"label": "Adjusted EBITDA", "value": "$151m", "context": "Plan $142m", "change": {"text": "beat", "direction": "up"}},
              {"label": "EBITDA margin", "value": "17.9%", "context": "+90 bps YoY", "change": {"text": "up", "direction": "up"}},
              {"label": "Free cash flow", "value": "$96m", "context": "Plan $88m", "change": {"text": "beat", "direction": "up"}}],
           "so_what": "All four measures beat plan."},
          src="Management accounts, Q3 FY26 (synthetic)", sec="Results"),
        S("combo_margin", "Revenue grew to $842m over five quarters while margin widened to 17.9%",
          {"subtitle": "Revenue, $ million, and adjusted EBITDA margin, %", "number_format": "#,##0", "line_format": "0.0%",
           "categories": ["Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26"], "bars": {"name": "Revenue, $m", "values": [797, 811, 818, 830, 842]},
           "line": {"name": "EBITDA margin", "values": [0.170, 0.172, 0.174, 0.177, 0.179]},
           "takeaway": "Margin has widened for five quarters, from 17.0% to 17.9%"},
          src=("Management accounts (synthetic)",), sec="Results"),
        S("paired_bars", "Margin improves in four of five divisions, with Packaging up 2.1 points to 15.4%",
          {"subtitle": "Adjusted EBITDA margin by division, Q3 FY25 versus Q3 FY26, %", "number_format": "0.0",
           "categories": ["Packaging", "Industrial", "Consumer", "Energy", "Medical"],
           "before": {"name": "Q3 FY25", "values": [13.3, 18.2, 16.1, 21.4, 19.0]}, "after": {"name": "Q3 FY26", "values": [15.4, 19.0, 16.8, 22.1, 18.6]},
           "stat": {"value": "+0.9pp", "label": "average margin change across divisions"},
           "takeaway": "Medical is the only division down, by 0.4 points to 18.6%"},
          src=("Management accounts (synthetic)",), sec="Results"),
        S("scorecard", "Four of five operating KPIs improved, but backlog slipped 1.4% to $1,055m",
          {"subtitle": "KPI scorecard, last five quarters", "periods": ["Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26"], "kpis": [
              {"name": "On-time delivery", "format": "pct", "values": [91, 92, 92, 94, 95]},
              {"name": "Scrap rate", "format": "pct", "values": [3.1, 3.0, 2.8, 2.6, 2.4], "good_up": False},
              {"name": "Net debt / EBITDA", "format": "x", "values": [2.9, 2.8, 2.6, 2.5, 2.3], "good_up": False},
              {"name": "Backlog ($m)", "format": "usd_m", "values": [980, 1010, 1040, 1070, 1055]}],
           "takeaway": "Net debt to EBITDA fell to 2.3x from 2.9x a year ago"},
          src=("Management accounts (synthetic)",), sec="Results"),
        S("gantt", "The cost programme has captured $48m and finishes the last wave by month 9",
          {"subtitle": "Cost programme waves, FY27", "today": 2.5, "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
           "workstreams": [
               {"name": "Procurement", "bars": [{"start": 0, "end": 4, "label": "Wave 2 tenders"}], "milestones": [{"month": 4.5, "label": "$20m captured"}]},
               {"name": "Footprint", "bars": [{"start": 2, "end": 8, "label": "Close two plants", "highlight": True}], "milestones": [{"month": 7.6, "label": "Month 9 done"}]},
               {"name": "Shared services", "bars": [{"start": 1, "end": 5, "label": "Move to hub"}], "milestones": []},
               {"name": "Automation", "bars": [{"start": 3, "end": 8, "label": "Line upgrades"}], "milestones": []}]},
          src="Cost programme tracker (synthetic)", sec="Cost programme"),
        S("recommendation", "Approve $65m of plant 4 capex, a 6% dividend increase and a $200m buyback",
          {"subtitle": "Decisions requested", "phases": [
              {"label": "Capex", "window": "plant 4", "owner": "COO", "date": "Dec 2026",
               "actions": ["Approve $65m for the plant 4 line", "Payback of 3.5 years at base volumes"]},
              {"label": "Dividend", "window": "FY27", "owner": "CFO", "date": "Jan 2027",
               "actions": ["Raise the quarterly dividend by 6%", "Payout ratio stays at 38% of earnings"]},
              {"label": "Buyback", "window": "12 months", "owner": "CFO", "date": "Nov 2027",
               "actions": ["Authorise a $200m repurchase programme", "Keep net debt to EBITDA at 2.3x"]}]},
          src="Management proposal (synthetic)", sec="Decisions"),
    ]
    req = ("Write a 9-slide third-quarter board update for Redwood Industries, a US manufacturer: results versus plan, margin trend, "
           "divisional margins, KPI scorecard, cost programme status and three decisions requested. Synthetic data.")
    return make_brief("d12-board-update", t, req, sl, client="Board of Directors", as_of="2026-11-18")


def d13():
    t = "Project Keystone: acquisition financing proposal"

    def cover_calc(sofr, ebitda_pct):
        e = 135 * (1 + ebitda_pct / 100)
        interest = 650 * (sofr + 3.75) / 100 + 300 * 8.1 / 100
        return round(e / interest, 2)
    grid = [[cover_calc(r, p) for p in (-10, 0, 10)] for r in (3.5, 4.0, 4.5, 5.0)]
    sl = [
        S("cover", t, {"client": "Sponsor investment committee and lenders", "date": "12 November 2026"},
          visual=("orthogonal flow schematic with nodes and elbow connectors", "diagram"), sec="Answer"),
        S("exec_summary", "A $950m debt package at 7.0x funds the $1,350m purchase with $480m of equity",
          {"subtitle": "Financing summary, $ million", "insights": [
              {"lead": "Debt", "text": "Term loan B and senior notes fund the acquisition", "figure": "$950m"},
              {"lead": "Equity", "text": "Sponsor equity completes the sources of funds", "figure": "$480m"},
              {"lead": "Leverage", "text": "Total debt to EBITDA at closing", "figure": "7.0x"},
              {"lead": "Cost", "text": "Blended cash cost of the package", "figure": "7.9%"}],
           "so_what": {"text": "Launch syndication to lenders on 16 November."}},
          src=("Financing term sheet v4 (synthetic)", "Sponsor model v12 (synthetic)"), sec="Answer"),
        S("deal_structure", "The $650m term loan sits at BidCo, below $300m of senior notes at the holdco",
          {"subtitle": "Financing structure at closing, $ million", "entities": [
              {"id": "sponsor", "label": "Sponsor fund", "sub": "$480m equity", "tier": 0},
              {"id": "holdco", "label": "Holdco", "sub": "$300m notes", "tier": 1},
              {"id": "bidco", "label": "BidCo", "sub": "$650m TLB", "tier": 2, "highlight": True}],
           "links": [{"from": "sponsor", "to": "holdco", "label": "100%"}, {"from": "holdco", "to": "bidco", "label": "100%"}]},
          src="Financing term sheet v4 (synthetic)", sec="Structure"),
        S("stacked_bar", "Debt of $950m and equity of $480m fund the $1,350m price and $80m of costs",
          {"subtitle": "Sources and uses at closing, $ million", "mode": "absolute", "number_format": "#,##0",
           "categories": ["Sources", "Uses"],
           "parts": [{"name": "Term loan B", "values": [650, 0]}, {"name": "Senior notes", "values": [300, 0]},
                     {"name": "Sponsor equity", "values": [480, 0], "key": True}, {"name": "Purchase price", "values": [0, 1350]},
                     {"name": "Fees and cash", "values": [0, 80]}],
           "takeaway": "Sponsor equity of $480m funds the balance of the purchase"},
          src=("Sponsor model v12 (synthetic)",), sec="Structure"),
        S("comparison_table", "A term loan B at S+375 is the cheapest of three structures at 7.9%",
          {"subtitle": "Debt alternatives for the $650m senior tranche", "options": ["Term loan B", "Unitranche", "High-yield bond"], "highlight": 0,
           "rows": [{"criterion": "Pricing", "values": ["S+375", "S+525", "8.1% fixed"]},
                    {"criterion": "Blended cost", "values": ["7.9%", "9.2%", "8.6%"]},
                    {"criterion": "Call protection", "values": ["6 months", "24 months", "36 months"]},
                    {"criterion": "Execution time", "values": ["6 weeks", "4 weeks", "8 weeks"]}],
           "verdict": ["Recommended", "Faster", "Costlier"],
           "takeaway": "The unitranche costs 9.2% against 7.9% for the term loan B"},
          src=("Lender soundings (synthetic)",), sec="Structure"),
        S("annotated_line", "Total leverage falls from 7.0x at closing to 3.8x by FY31E",
          {"subtitle": "Debt to EBITDA, x", "number_format": "0.0", "change_unit": "x",
           "categories": ["Close", "FY27E", "FY28E", "FY29E", "FY30E", "FY31E"],
           "series": [{"name": "Total leverage", "values": [7.0, 6.3, 5.6, 4.9, 4.3, 3.8]},
                      {"name": "Senior leverage", "values": [4.8, 4.3, 3.8, 3.3, 2.8, 2.4]}],
           "annotation": {"at": 3, "text": "Notes callable from FY29E"},
           "takeaway": "Senior leverage reaches 2.4x by FY31E"},
          src=("Sponsor model v12, base case (synthetic)",), sec="Credit"),
        S("sensitivity_table", f"Interest cover stays above {min(min(r) for r in grid):.1f}x even with EBITDA down 10% and SOFR at 5.0%",
          {"subtitle": "Interest cover, SOFR by EBITDA change, x", "row_label": "SOFR, %", "col_label": "EBITDA change, %",
           "row_values": [3.5, 4.0, 4.5, 5.0], "col_values": [-10, 0, 10], "values": grid, "base": [1, 1], "value_format": "0.00",
           "takeaway": f"Base interest cover is {grid[1][1]:.2f}x at SOFR 4.0%"},
          src=("Sponsor model v12 (synthetic)",), sec="Credit"),
        S("risk_heatmap", "3 of 4 financing risks are covered by a hedge, cap or call option",
          {"subtitle": "Financing risk register, five-point scale", "risks": [
              {"label": "SOFR above 5.0%", "likelihood": 3, "impact": 3}, {"label": "Syndication shortfall of $100m", "likelihood": 2, "impact": 4},
              {"label": "Covenant headroom below 25%", "likelihood": 2, "impact": 5}, {"label": "Flex of 50 bps on pricing", "likelihood": 3, "impact": 2}],
           "takeaway": "Hedging 70% of the term loan covers the rate risk"},
          src=("Sponsor treasury (synthetic)",), sec="Credit"),
        S("process_flow", "Syndication runs 6 weeks from launch on 16 November to funding",
          {"highlight": 1, "output_label": "Milestone", "subtitle": "Syndication process", "steps": [
              {"name": "Launch", "output": "Week 0: lender meeting"}, {"name": "Commitments", "output": "Week 2: bids due"},
              {"name": "Allocate", "output": "Week 3: allocations set"}, {"name": "Document", "output": "Week 5: credit agreement"},
              {"name": "Fund", "output": "Week 6: funds drawn"}]},
          src="Syndication plan (synthetic)", sec="Process"),
        S("recommendation", "Approve the $950m financing and launch syndication on 16 November",
          {"subtitle": "Next steps", "phases": [
              {"label": "Now", "window": "this week", "owner": "Sponsor IC", "date": "Nov 2026",
               "actions": ["Approve the $950m debt package", "Sign the commitment papers"]},
              {"label": "Next", "window": "weeks 1 to 3", "owner": "Treasury", "date": "Dec 2026",
               "actions": ["Run the lender meeting on 16 November", "Hedge 70% of the term loan"]},
              {"label": "Later", "window": "weeks 4 to 6", "owner": "CFO", "date": "Jan 2027",
               "actions": ["Sign the credit agreement", "Draw funds at week 6"]}]},
          src="Syndication plan (synthetic)", sec="Process"),
    ]
    req = ("Prepare a 10-slide acquisition financing proposal for Project Keystone: sources and uses, structure, term loan versus unitranche versus "
           "bond, deleveraging, interest cover sensitivity, risks and syndication plan. Synthetic data.")
    return make_brief("d13-debt-financing", t, req, sl, client="Sponsor investment committee", as_of="2026-11-12", art="line_art_schematic")


ALL = [d10, d11, d12, d13]
