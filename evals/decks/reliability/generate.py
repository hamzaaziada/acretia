"""Reliability corpus: `specs(n=100, seed=7)` -> deterministic, varied DeckSpec v2 dicts (synthetic data).

Regimes: US GAAP, IFRS, MENA (3 Arabic-heavy markets). Families: pitchbook section, IC deck, earnings recap, market entry,
carve-out. Each slide generator derives title, prose and data from one fact base, so provenance stays consistent: every
number printed on a slide is a number in that slide's (or the deck's) sourced data blocks. Arabic decks use a subset of
generators that carry Arabic strings. No network, no LLM."""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AS_OF = "2026-10-31"
REGIMES = {
    "us_gaap": {"cur": "$", "src": ("Company 10-K filings (synthetic)", "Market data, Oct 2026 (synthetic)"), "acct": "US GAAP"},
    "ifrs": {"cur": "€", "src": ("Annual report, IFRS (synthetic)", "Market data, Oct 2026 (synthetic)"), "acct": "IFRS"},
    "mena": {"cur": "$", "src": ("Exchange filings, IFRS 9 (synthetic)", "Regional market data (synthetic)"), "acct": "IFRS"},
}
NAMES = ["Falcon", "Harbor", "Atlas", "Cedar", "Orion", "Meridian", "Beacon", "Keystone", "Lighthouse", "Dune", "Oasis", "Rhine",
         "Summit", "Anchor", "Nimbus", "Vertex", "Crescent", "Delta", "Echo", "Granite", "Helios", "Ivory", "Juniper", "Kestrel"]
NAMES_AR = ["الصقر", "الواحة", "النخيل", "الريادة", "الأفق", "النخبة", "الميناء", "القمة", "الهلال", "الدلتا"]
PEERS = ["Alder", "Brightwater", "Cobalt", "Delta", "Ember", "Fulcrum", "Granite", "Halyard", "Ionic", "Juno", "Kite", "Lumen"]
PEERS_AR = ["الدار", "الأفق", "رعاية الخليج", "الريادة", "الوفاء", "المنارة", "الجسر", "الوادي"]
SECTORS = ["industrial", "software", "healthcare", "consumer", "logistics", "energy services", "financial services"]
AR_FAMILIES = ("market_entry", "ic_deck", "carve_out")

FAMILY_PLANS = {
    "pitchbook": (["cover", "exec", "kpi", "combo", "comps", "ranked", "football", "tombs"],
                  ["sens", "scatter", "stackcol", "matrix", "numbered", "process", "takeaway", "recommend", "doughnut", "line"]),
    "ic_deck": (["cover", "exec", "stat", "column", "waterfall", "sens", "risk", "timeline", "takeaway"],
                ["paired", "doughnut", "ranked", "combo", "scatter", "stackcol", "harvey", "numbered", "gantt", "line"]),
    "earnings": (["cover", "exec", "kpi", "waterfall", "line", "small", "compare", "takeaway"],
                 ["combo", "paired", "ranked", "scorecard", "doughnut", "stackcol", "numbered", "column", "risk", "recommend"]),
    "market_entry": (["cover", "exec", "column", "stackbar", "matrix", "harvey", "compare", "process", "risk", "recommend"],
                     ["stat", "ranked", "doughnut", "line", "scorecard", "numbered", "timeline", "takeaway", "gantt"]),
    "carve_out": (["cover", "exec", "kpi", "waterfall", "deal", "gantt", "compare", "risk", "recommend"],
                  ["stackbar", "paired", "doughnut", "scorecard", "numbered", "process", "takeaway", "ranked", "timeline", "combo"]),
}
VTYPE = {"cover": "cover", "exec": "text", "kpi": "stat", "stat": "stat", "combo": "combo", "column": "column", "comps": "table",
         "ranked": "bar", "football": "football_field", "tombs": "grid", "sens": "table", "scatter": "scatter", "stackcol": "stacked_column",
         "stackbar": "stacked_bar", "matrix": "matrix", "numbered": "cards", "process": "flow", "takeaway": "text", "recommend": "columns",
         "doughnut": "doughnut", "line": "line", "waterfall": "waterfall", "risk": "heatmap", "timeline": "timeline", "paired": "column",
         "harvey": "table", "gantt": "timeline", "small": "small_multiples", "compare": "table", "scorecard": "table", "deal": "diagram"}
ARCH = {"cover": "cover", "exec": "exec_summary", "kpi": "kpi_row", "stat": "stat_hero", "combo": "combo_margin", "column": "column_kpi",
        "comps": "comps_table", "ranked": "ranked_bar", "football": "football_field", "tombs": "tombstones", "sens": "sensitivity_table",
        "scatter": "scatter_quadrant", "stackcol": "stacked_column", "stackbar": "stacked_bar", "matrix": "matrix_2x2",
        "numbered": "numbered_insights", "process": "process_flow", "takeaway": "takeaway_box", "recommend": "recommendation",
        "doughnut": "doughnut_split", "line": "annotated_line", "waterfall": "waterfall", "risk": "risk_heatmap",
        "timeline": "timeline_milestones", "paired": "paired_bars", "harvey": "harvey_table", "gantt": "gantt", "small": "small_multiples",
        "compare": "comparison_table", "scorecard": "scorecard", "deal": "deal_structure"}
AR_OK = {"cover", "exec", "kpi", "column", "ranked", "waterfall", "risk", "recommend", "compare", "process", "stackcol", "doughnut",
         "takeaway", "combo", "line", "paired", "matrix", "stat", "stackbar", "timeline"}


def n0(x) -> str:
    return f"{x:,.0f}"


def n1(x) -> str:
    return f"{x:,.1f}"


class Ctx:
    def __init__(self, rng: random.Random, regime: str, family: str, lang: str, idx: int):
        self.rng, self.regime, self.family, self.lang, self.ar = rng, regime, family, lang, lang == "ar"
        r = REGIMES[regime]
        self.cur, self.src, self.acct = r["cur"], r["src"], r["acct"]
        pool = NAMES_AR if self.ar else NAMES
        self.name = rng.choice(pool)
        self.project = f"Project {rng.choice(NAMES)}"
        self.ptitle = f"مشروع {self.name}" if self.ar else self.project
        self.sector = rng.choice(SECTORS)
        self.yrs = [f"FY{y}" for y in range(22, 27)]
        self.growth = rng.randint(4, 16)
        r0 = rng.randrange(300, 2400, 10)
        self.rev = [round(r0 * (1 + self.growth / 100) ** i) for i in range(5)]
        self.margin = [round(rng.uniform(12, 24) + 0.8 * i, 1) for i in range(5)]
        self.ebitda = round(self.rev[-1] * self.margin[-1] / 100)
        self.mult = round(rng.uniform(7, 16), 1)
        self.ev = round(self.ebitda * self.mult)
        self.peers = rng.sample(PEERS_AR if self.ar else PEERS, 7 if not self.ar else 6)
        self.deck_id = f"rel-{idx:03d}-{family.replace('_', '-')}-{regime.replace('_', '-')}"


def _pct(x):
    return f"{x:.1f}%"


# ---------------------------------------------------------------- slide generators: (ctx) -> (title, blocks, extra)
def g_cover(c):
    client = "مجلس الإدارة" if c.ar else "Board of Directors"
    return c.ptitle if c.ar else f"{c.project}: {c.family.replace('_', ' ')}", {"client": client, "date": AS_OF}, {}


def g_exec(c):
    cur = c.cur
    ins = [("القيمة" if c.ar else "Value", "قيمة المنشأة بالمليون" if c.ar else "Enterprise value in millions", f"{cur}{n0(c.ev)}m"),
           ("المضاعف" if c.ar else "Multiple", "مضاعف الأرباح التشغيلية" if c.ar else "Multiple of EBITDA", f"{c.mult:.1f}x"),
           ("النمو" if c.ar else "Growth", "نمو الإيرادات السنوي" if c.ar else "Annual revenue growth", f"{c.growth}%"),
           ("الهامش" if c.ar else "Margin", "هامش الأرباح التشغيلية" if c.ar else "EBITDA margin in the latest year", _pct(c.margin[-1]))]
    t = (f"قيمة {cur}{n0(c.ev)}m بمضاعف {c.mult:.1f}x ونمو {c.growth}%" if c.ar else
         f"{c.project} supports {cur}{n0(c.ev)}m of value at {c.mult:.1f}x EBITDA and {c.growth}% growth")
    return t, {"subtitle": "ملخص" if c.ar else f"Summary, {cur} million",
               "insights": [{"lead": a, "text": b, "figure": f} for a, b, f in ins],
               "so_what": {"text": "نوصي بالمضي قدما." if c.ar else "Proceed to the next stage of the process."}}, {}


def g_kpi(c):
    cur = c.cur
    k = [("الإيرادات" if c.ar else "Revenue", f"{cur}{n0(c.rev[-1])}m", f"{c.growth}%"),
         ("الأرباح التشغيلية" if c.ar else "EBITDA", f"{cur}{n0(c.ebitda)}m", _pct(c.margin[-1])),
         ("الهامش" if c.ar else "EBITDA margin", _pct(c.margin[-1]), _pct(c.margin[-1] - c.margin[-2])),
         ("النمو" if c.ar else "Growth", f"{c.growth}%", f"{c.growth}%")]
    t = (f"الإيرادات {cur}{n0(c.rev[-1])}m وهامش {_pct(c.margin[-1])}" if c.ar else
         f"Revenue of {cur}{n0(c.rev[-1])}m and a {_pct(c.margin[-1])} EBITDA margin lead the plan")
    return t, {"subtitle": "الأداء" if c.ar else "Latest year performance", "highlight": 0, "kpis": [
        {"label": a, "value": v, "context": ("مقارنة بالعام السابق" if c.ar else f"Context {x}"), "change": {"text": "ارتفاع" if c.ar else "up", "direction": "up"}}
        for a, v, x in k]}, {}


def g_stat(c):
    mk = round(c.ev * c.rng.uniform(3, 8) / 1000, 1)
    sh = c.rng.randint(8, 24)
    t = (f"السوق {mk}bn$ والشركة تملك {sh}%" if c.ar else f"The market is worth {c.cur}{mk}bn and {c.name} holds {sh}% of it")
    return t, {"subtitle": "السوق" if c.ar else "Market position", "stats": [
        {"value": f"{c.cur}{mk}bn", "label": "حجم السوق" if c.ar else "market size", "context": f"{c.growth}%"},
        {"value": f"{sh}%", "label": "الحصة" if c.ar else "market share", "context": "الأكبر" if c.ar else "Top three"}],
        "so_what": "مجال للنمو." if c.ar else "There is room to grow."}, {}


def g_column(c):
    cagr = round(((c.rev[-1] / c.rev[0]) ** 0.25 - 1) * 100)
    t = (f"تنمو الإيرادات {cagr}% سنويا إلى {c.cur}{n0(c.rev[-1])}m" if c.ar else
         f"Revenue compounds at {cagr}% a year to {c.cur}{n0(c.rev[-1])}m")
    return t, {"subtitle": "الإيرادات" if c.ar else f"Revenue, {c.cur} million", "number_format": "#,##0", "series_name": "Revenue",
               "categories": c.yrs, "values": c.rev,
               "stats": [{"value": f"{c.cur}{n0(c.rev[-1])}m", "label": "الإيرادات الأخيرة" if c.ar else "latest revenue"},
                         {"value": f"{cagr}%", "label": "النمو السنوي" if c.ar else "revenue CAGR"}],
               "takeaway": f"الأعلى {n0(c.rev[-1])}" if c.ar else f"Revenue reaches {n0(c.rev[-1])} in the final year"}, {}


def g_combo(c):
    t = (f"الإيرادات {n0(c.rev[-1])} والهامش {_pct(c.margin[-1])}" if c.ar else
         f"Revenue reaches {c.cur}{n0(c.rev[-1])}m while margin widens to {_pct(c.margin[-1])}")
    return t, {"subtitle": "الإيرادات والهامش" if c.ar else "Revenue and EBITDA margin", "number_format": "#,##0", "line_format": "0.0%",
               "categories": c.yrs, "bars": {"name": "Revenue", "values": c.rev},
               "line": {"name": "EBITDA margin", "values": [m / 100 for m in c.margin]},
               "takeaway": f"{_pct(c.margin[0])} إلى {_pct(c.margin[-1])}" if c.ar else f"Margin rises from {_pct(c.margin[0])} to {_pct(c.margin[-1])}"}, {}


def g_waterfall(c):
    r = c.rng
    start = round(c.ebitda * r.uniform(0.75, 0.9))
    steps = [("Volume", r.randint(5, 20)), ("Price", r.randint(4, 14)), ("Input costs", -r.randint(4, 12)), ("Savings", r.randint(3, 10)),
             ("Inflation", -r.randint(2, 8))]
    steps_ar = ["الحجم", "السعر", "التكاليف", "الوفورات", "التضخم"]
    end = start + sum(v for _, v in steps)
    sl = [{"label": "البداية" if c.ar else "Start", "value": start}] + [
        {"label": (steps_ar[i] if c.ar else k), "value": v} for i, (k, v) in enumerate(steps)] + [
        {"label": "النهاية" if c.ar else "End", "value": end}]
    t = (f"ترتفع الأرباح من {start} إلى {end}" if c.ar else f"EBITDA moves from {c.cur}{start}m to {c.cur}{end}m on price and savings")
    mx = max(steps, key=lambda s: s[1])
    return t, {"subtitle": "جسر الأرباح" if c.ar else "EBITDA bridge", "number_format": "0", "prefix": c.cur, "suffix": "m", "steps": sl,
               "takeaway": f"{mx[1]}" if c.ar else f"{mx[0]} adds {c.cur}{mx[1]}m"}, {}


def g_ranked(c):
    r = c.rng
    vals = sorted([round(c.mult + r.uniform(-3.5, 3.5), 1) for _ in range(6)], reverse=True)
    items = [{"label": p, "value": v} for p, v in zip(c.peers, vals)]
    pos = r.randrange(0, 7)
    items.insert(pos, {"label": c.name, "value": c.mult, "key": True})
    items.sort(key=lambda i: -i["value"])
    med = round(statistics.median(i["value"] for i in items if not i.get("key")), 1)
    gap = round(c.mult - med, 1)
    t = (f"{c.name} عند {c.mult:.1f}x مقابل وسيط {med:.1f}x" if c.ar else f"{c.name} trades at {c.mult:.1f}x against a peer median of {med:.1f}x")
    return t, {"subtitle": "المضاعف" if c.ar else "EV/EBITDA, x", "number_format": "0.0\"x\"", "series_name": "EV/EBITDA", "items": items,
               "stat": {"value": f"{gap:+.1f}x", "label": f"الفرق عن الوسيط {med:.1f}x" if c.ar else f"versus the peer median of {med:.1f}x"},
               "takeaway": f"{med:.1f}x" if c.ar else f"The peer median is {med:.1f}x"}, {}


def g_comps(c):
    r = c.rng
    rows = []
    for p in c.peers[:6]:
        rows.append({"company": p, "ev": round(r.uniform(1.5, 15), 1), "ev_ebitda": round(c.mult + r.uniform(-3, 3), 1),
                     "pe": round(c.mult * 1.6 + r.uniform(-3, 3), 1), "growth": round(r.uniform(2, 12), 1), "margin": round(r.uniform(14, 28), 1)})
    med = round(statistics.median(x["ev_ebitda"] for x in rows), 1)
    t = f"Peers trade at a median {med:.1f}x EV/EBITDA, the benchmark for {c.name}"
    return t, {"subtitle": f"Trading comparables, EV in {c.cur} billion", "compute_stats": True, "dense": True, "rows": rows,
               "takeaway": f"Median EV/EBITDA is {med:.1f}x"}, {}


def g_football(c):
    r = c.rng
    price = round(c.ev / 100 * r.uniform(0.8, 1.2), 2)
    base = price
    ms = []
    for lab in ("DCF", "Trading comps", "Precedents", "Analyst targets"):
        lo = round(base * r.uniform(0.82, 1.0), 2)
        ms.append({"label": lab, "low": lo, "high": round(lo * r.uniform(1.15, 1.35), 2), "key": lab == "DCF"})
    hi = max(m["high"] for m in ms)
    t = f"Methods value {c.name} up to {c.cur}{hi:.2f} per share against {c.cur}{price:.2f} today"
    return t, {"subtitle": f"Equity value per share, {c.cur}", "prefix": c.cur, "number_format": "0.00", "current_price": price, "methods": ms,
               "takeaway": f"The highest range reaches {c.cur}{hi:.2f}"}, {}


def g_tombs(c):
    r = c.rng
    deals = [{"acquirer": f"Buyer {chr(65 + i)}", "target": f"{c.peers[i]} Group", "date": f"{['Jan', 'Mar', 'May', 'Jul', 'Sep', 'Oct'][i]} 2026",
              "ev": round(r.uniform(0.8, 6.0), 1), "multiple": round(c.mult + r.uniform(-2, 2.5), 1)} for i in range(6)]
    lo, hi = min(d["multiple"] for d in deals), max(d["multiple"] for d in deals)
    t = f"Precedent deals cleared {lo:.1f}x to {hi:.1f}x EBITDA"
    return t, {"subtitle": f"Precedent transactions, EV in {c.cur} billion", "deals": deals,
               "takeaway": f"The range runs from {lo:.1f}x to {hi:.1f}x"}, {}


def g_sens(c):
    r = c.rng
    rows = [round(8 + 0.5 * i, 1) for i in range(3)]
    cols = [round(1.5 + 0.5 * i, 1) for i in range(3)]
    base = c.ev
    vals = [[round(base * (1 + 0.08 * (1 - i) + 0.05 * (j - 1)) / 1) for j in range(3)] for i in range(3)]
    lo, hi = min(min(v) for v in vals), max(max(v) for v in vals)
    t = f"DCF value spans {c.cur}{n0(lo)}m to {c.cur}{n0(hi)}m across WACC and growth"
    return t, {"subtitle": f"Enterprise value, WACC by terminal growth, {c.cur} million", "row_label": "WACC, %", "col_label": "Terminal growth, %",
               "row_values": rows, "col_values": cols, "values": vals, "base": [1, 1], "value_format": "#,##0",
               "takeaway": f"Base case is {c.cur}{n0(vals[1][1])}m"}, {}


def g_scatter(c):
    r = c.rng
    pts = [{"label": c.name, "xv": float(c.growth), "yv": c.margin[-1], "subject": True}]
    for p in c.peers[:6]:
        pts.append({"label": p, "xv": round(r.uniform(2, 14), 1), "yv": round(r.uniform(12, 28), 1)})
    med = round(statistics.median(p["yv"] for p in pts[1:]), 1)
    gap = round(c.margin[-1] - med, 1)
    t = f"{c.name} earns a {c.margin[-1]:.1f}% margin against a peer median of {med:.1f}%"
    return t, {"subtitle": "Growth versus margin, %", "x_title": "Growth, %", "y_title": "EBITDA margin, %", "x_format": "0.0", "y_format": "0.0",
               "points": pts, "stat": {"value": f"{gap:+.1f}pp", "label": f"margin gap to the peer median of {med:.1f}%"},
               "takeaway": f"Margin gap is {gap:+.1f} points"}, {}


def g_stackcol(c):
    a = [c.rng.randint(30, 40) + 4 * i for i in range(3)]
    b = [c.rng.randint(25, 35) for _ in range(3)]
    d = [100 - x - y for x, y in zip(a, b)]
    parts = [{"name": "الأول" if c.ar else "Core", "values": a, "key": True}, {"name": "الثاني" if c.ar else "Growth", "values": b},
             {"name": "الثالث" if c.ar else "Other", "values": d}]
    t = (f"الحصة الأولى ترتفع من {a[0]}% إلى {a[-1]}%" if c.ar else f"Core revenue rises from {a[0]}% to {a[-1]}% of the mix")
    return t, {"subtitle": "المزيج" if c.ar else "Revenue mix, % of total", "mode": "percent", "categories": c.yrs[-3:], "parts": parts,
               "takeaway": f"{a[-1]}%" if c.ar else f"Core is {a[-1]}% in the latest year"}, {}


def g_stackbar(c):
    cats = ["2025", "2027E", "2030E"]
    p1 = [round(c.rev[-1] / 1000 * f, 1) for f in (1.0, 1.25, 1.6)]
    p2 = [round(x * c.rng.uniform(0.7, 0.9), 1) for x in p1]
    p3 = [round(x * c.rng.uniform(0.4, 0.6), 1) for x in p1]
    t = (f"الأول يصل إلى {p1[-1]} مليار" if c.ar else f"The largest market reaches {c.cur}{p1[-1]}bn by 2030")
    return t, {"subtitle": "السوق" if c.ar else f"Revenue pool by market, {c.cur} billion", "mode": "absolute", "number_format": "0.0", "categories": cats,
               "parts": [{"name": "الأول" if c.ar else "Market A", "values": p1, "key": True}, {"name": "الثاني" if c.ar else "Market B", "values": p2},
                         {"name": "الثالث" if c.ar else "Market C", "values": p3}],
               "takeaway": f"{p1[-1]}" if c.ar else f"Market A grows from {c.cur}{p1[0]}bn to {c.cur}{p1[-1]}bn"}, {}


def g_matrix(c):
    r = c.rng
    labels = (["السوق أ", "السوق ب", "السوق ج", "السوق د", "السوق هـ"] if c.ar else [f"Market {x}" for x in "ABCDE"])
    xs = [round(r.uniform(0.15, 0.9), 2) for _ in labels]
    ys = [round(r.uniform(0.15, 0.9), 2) for _ in labels]
    xs[0], ys[0] = 0.82, 0.86
    items = [{"label": l, "xv": x, "yv": y, "highlight": i == 0} for i, (l, x, y) in enumerate(zip(labels, xs, ys))]
    t = (f"{labels[0]} يتجاوز 0.82 في المحورين" if c.ar else f"{labels[0]} scores 0.82 on ability to win and 0.86 on attractiveness")
    return t, {"subtitle": "الفرز" if c.ar else "Market screen", "x_axis": {"label": "القدرة" if c.ar else "Ability to win"},
               "y_axis": {"label": "الجاذبية" if c.ar else "Attractiveness"},
               "quadrants": ["أ", "ب", "ج", "د"] if c.ar else ["Build", "Pursue now", "Deprioritise", "Opportunistic"], "target": 1, "items": items,
               "takeaway": "الأولوية" if c.ar else "One market clears both bars"}, {}


def g_numbered(c):
    figs = [f"{c.cur}{n0(c.ev * f)}m" for f in (0.05, 0.08, 0.12)]
    t = f"Three levers add {figs[0]}, {figs[1]} and {figs[2]} of value"
    return t, {"subtitle": "Value levers", "insights": [
        {"title": "Pricing", "text": "Price realisation on the contract base", "figure": figs[0]},
        {"title": "Mix", "text": "Shift toward higher margin lines", "figure": figs[1]},
        {"title": "Costs", "text": "Procurement and footprint savings", "figure": figs[2]}]}, {}


def g_process(c):
    w = c.rng.randint(10, 16)
    steps = (["البدء", "التجربة", "التوسع", "الإطلاق"] if c.ar else ["Launch", "Pilot", "Scale", "Go live"])
    outs = [f"الأسبوع {k}" if c.ar else f"Week {k}" for k in (2, 5, 9, w)]
    t = (f"أربع مراحل في {w} أسبوعا" if c.ar else f"A four-step plan reaches go-live in {w} weeks")
    return t, {"highlight": 1, "output_label": "المخرج" if c.ar else "Milestone", "subtitle": "الخطة" if c.ar else "Plan",
               "steps": [{"name": s, "output": o} for s, o in zip(steps, outs)]}, {}


def g_takeaway(c):
    t = (f"نوصي بقيمة {c.cur}{n0(c.ev)}m" if c.ar else f"We recommend proceeding at {c.cur}{n0(c.ev)}m of enterprise value")
    return t, {"decision": f"الموافقة على {c.cur}{n0(c.ev)}m عند {c.mult:.1f}x" if c.ar else f"Approve {c.cur}{n0(c.ev)}m at {c.mult:.1f}x EBITDA",
               "rationale": (["القيمة: ضمن النطاق", "النمو: ثابت"] if c.ar else [f"Growth: {c.growth}% a year", f"Margin: {_pct(c.margin[-1])}"]),
               "risks": ["التنفيذ" if c.ar else "Execution: integration timing"]}, {}


def g_recommend(c):
    amt = round(c.ev * 0.1)
    t = (f"نوصي بتمويل {c.cur}{n0(amt)}m على ثلاث مراحل" if c.ar else f"Approve {c.cur}{n0(amt)}m in three phases starting now")
    ph = [("الآن" if c.ar else "Now", "30 days"), ("التالي" if c.ar else "Next", "60 days"), ("لاحقا" if c.ar else "Later", "90 days")]
    return t, {"subtitle": "الخطوات" if c.ar else "Next steps", "phases": [
        {"label": l, "window": w, "owner": "المالية" if c.ar else "CFO", "date": d,
         "actions": ([f"اعتماد {c.cur}{n0(amt)}m", "بدء التنفيذ"] if c.ar else [f"Release {c.cur}{n0(amt)}m", "Start delivery"])}
        for (l, w), d in zip(ph, ("2026-12-15", "2027-02-15", "2027-04-15"))]}, {}


def g_doughnut(c):
    a, b = c.rng.randint(40, 55), c.rng.randint(20, 30)
    cc = 100 - a - b
    t = (f"الشريحة الأولى {a}% من الإجمالي" if c.ar else f"The largest segment is {a}% of the {c.cur}{n0(c.rev[-1])}m total")
    return t, {"subtitle": "التوزيع" if c.ar else "Mix by segment, % of total", "centre": f"{c.cur}{n0(c.rev[-1])}m"[:9],
               "slices": [{"label": "أ" if c.ar else "Segment A", "value": a, "key": True}, {"label": "ب" if c.ar else "Segment B", "value": b},
                          {"label": "ج" if c.ar else "Segment C", "value": cc}],
               "takeaway": f"{b}%" if c.ar else f"Segment B is {b}% of the total"}, {}


def g_line(c):
    pts = [round(c.margin[0] + 0.35 * i + c.rng.uniform(-0.3, 0.3), 2) for i in range(8)]
    peer = [round(p - 0.8 + c.rng.uniform(-0.2, 0.2), 2) for p in pts]
    q = [f"Q{(i % 4) + 1} {25 + i // 4}" for i in range(8)]
    t = (f"الهامش يرتفع إلى {pts[-1]:.2f}%" if c.ar else f"Margin recovers to {pts[-1]:.2f}% after the cost programme")
    return t, {"subtitle": "الهامش" if c.ar else "EBITDA margin, quarterly, %", "number_format": "0.00", "change_unit": "pp", "categories": q,
               "series": [{"name": c.name, "values": pts}, {"name": "Peers" if not c.ar else "الأقران", "values": peer}],
               "annotation": {"at": 3, "text": "الإجراءات" if c.ar else "Programme starts"},
               "takeaway": f"{pts[-1]:.2f}%" if c.ar else f"Latest margin is {pts[-1]:.2f}% against {peer[-1]:.2f}% for peers"}, {}


def g_risk(c):
    r = c.rng
    k = r.randint(8, 25)
    risks = [{"label": f"{x} of {k}%" if not c.ar else f"{x} {k}%", "likelihood": r.randint(2, 4), "impact": r.randint(2, 5)}
             for x in (["Revenue shortfall", "Cost overrun", "Approval delay", "Churn"] if not c.ar else ["نقص الإيرادات", "تجاوز التكلفة", "تأخر الموافقة", "الاستقطاب"])]
    t = (f"مخاطر بحدود {k}% تتطلب خطة" if c.ar else f"Four risks of up to {k}% need an owner before close")
    return t, {"subtitle": "السجل" if c.ar else "Risk register, five-point scale", "risks": risks,
               "takeaway": f"{k}%" if c.ar else f"The largest swing is {k}%"}, {}


def g_timeline(c):
    t = "Signing on 15 December keeps closing on track for 2027" if not c.ar else "التوقيع في 15 ديسمبر يحافظ على الإغلاق"
    return t, {"subtitle": "الجدول" if c.ar else "Timetable", "milestones": [
        {"date": "15 Nov", "label": "قرار" if c.ar else "Decision"}, {"date": "30 Nov", "label": "عناية" if c.ar else "Diligence"},
        {"date": "15 Dec", "label": "توقيع" if c.ar else "Signing", "highlight": True}, {"date": "Mar", "label": "موافقات" if c.ar else "Approvals"},
        {"date": "Jun", "label": "إغلاق" if c.ar else "Closing", "highlight": True}]}, {}


def g_paired(c):
    cats = ["أ", "ب", "ج", "د"] if c.ar else ["Retail", "Corporate", "SME", "Wealth"]
    b = [round(c.rng.uniform(40, 60), 1) for _ in cats]
    a = [round(x - c.rng.uniform(-1, 4), 1) for x in b]
    best = max(a)
    t = (f"أفضل نسبة {best:.1f}% بعد البرنامج" if c.ar else f"Cost-to-income improves in most lines, with the highest at {best:.1f}%")
    return t, {"subtitle": "النسبة" if c.ar else "Cost-to-income by division, %", "number_format": "0.0", "categories": cats,
               "before": {"name": "FY25", "values": b}, "after": {"name": "FY26", "values": a},
               "stat": {"value": f"{(sum(a) - sum(b)) / len(a):+.1f}pp", "label": "average change"},
               "takeaway": f"{best:.1f}%" if c.ar else f"The highest ratio is {best:.1f}%"}, {}


def g_harvey(c):
    caps = ["المنصة", "التسعير", "التوزيع", "المخاطر"] if c.ar else ["Platform", "Pricing", "Distribution", "Risk"]
    vals = [[0.25 * c.rng.randint(1, 4) for _ in range(3)] for _ in caps]
    vals[0][0] = 1
    t = (f"{c.name} يتصدر المنصة عند 1.0" if c.ar else f"{c.name} leads on platform at 1.0 and trails on distribution")
    return t, {"subtitle": "القدرات" if c.ar else "Capability coverage", "peers": [c.name, "A", "B"], "highlight": 0,
               "capabilities": [{"name": n, "values": v} for n, v in zip(caps, vals)], "takeaway": "1.0"}, {}


def g_gantt(c):
    m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
    t = "The critical path is IT separation, finishing in month 8"
    return t, {"subtitle": "Workstreams", "today": 0.5, "months": m, "workstreams": [
        {"name": "Legal", "bars": [{"start": 0, "end": 3, "label": "SPA"}], "milestones": []},
        {"name": "IT", "bars": [{"start": 1, "end": 7, "label": "Split", "highlight": True}], "milestones": [{"month": 7.3, "label": "Month 8: cut-over"}]},
        {"name": "People", "bars": [{"start": 3, "end": 7, "label": "Transfer"}], "milestones": []}]}, {}


def g_small(c):
    pans = []
    for p in ("Snacks", "Frozen", "Beverages"):
        v = [c.rng.randint(-2, 8) for _ in range(4)]
        pans.append({"title": p, "categories": ["Q1", "Q2", "Q3", "Q4"], "values": v})
    top = max(pans, key=lambda p: p["values"][-1])
    t = f"{top['title']} leads with {top['values'][-1]}% growth in the latest quarter"
    return t, {"subtitle": "Growth by segment, %", "number_format": "0", "panels": pans, "takeaway": f"{top['values'][-1]}%"}, {}


def g_compare(c):
    r = c.rng
    a, b, d = (round(c.ev * f) for f in (0.92, 1.0, 0.85))
    cur = c.cur
    if c.ar:
        opts, rows, ver = ["أ", "ب", "ج"], [("القيمة", [f"{cur}{n0(a)}m", f"{cur}{n0(b)}m", f"{cur}{n0(d)}m"]), ("المدة", ["6", "9", "12"]),
                                          ("المخاطر", ["منخفضة", "متوسطة", "عالية"])], ["بديل", "موصى به", "أبطأ"]
        t = f"الخيار ب أعلى قيمة عند {cur}{n0(b)}m"
        tk = f"{cur}{n0(b)}m"
    else:
        opts, ver = ["Sell", "Merge", "Hold"], ["Lower", "Recommended", "Gap"]
        rows = [("Equity value", [f"{cur}{n0(a)}m", f"{cur}{n0(b)}m", f"{cur}{n0(d)}m"]), ("Time to close", ["6 months", "9 months", "n.a."]),
                ("Execution risk", ["Low", "Medium", "Low"])]
        t = f"Merging delivers {cur}{n0(b)}m, the highest value of the three options"
        tk = f"Merge is worth {cur}{n0(b)}m against {cur}{n0(a)}m for a sale"
    return t, {"subtitle": "الخيارات" if c.ar else "Options", "options": opts, "highlight": 1,
               "rows": [{"criterion": k, "values": v} for k, v in rows], "verdict": ver, "takeaway": tk}, {}


def g_scorecard(c):
    t = f"Margin rose to {c.margin[-1]:.1f}% while growth held at {c.growth}%"
    return t, {"subtitle": "KPI scorecard", "periods": ["Q1", "Q2", "Q3", "Q4"], "kpis": [
        {"name": "Revenue ($m)", "format": "usd_m", "values": [round(c.rev[-1] / 4 * f) for f in (0.96, 0.99, 1.02, 1.04)]},
        {"name": "EBITDA margin", "format": "pct", "values": [c.margin[-1] - 0.9, c.margin[-1] - 0.6, c.margin[-1] - 0.2, c.margin[-1]]},
        {"name": "Growth", "format": "pct", "values": [c.growth - 1.0, c.growth - 0.5, c.growth, c.growth]}],
        "takeaway": f"{c.margin[-1]:.1f}%"}, {}


def g_deal(c):
    p = c.rng.randint(55, 80)
    t = f"The sponsor holds {p}% of Holdco, which owns 100% of the target"
    return t, {"subtitle": "Structure at closing", "entities": [
        {"id": "s", "label": "Sponsor", "sub": "Fund", "tier": 0}, {"id": "o", "label": "Co-investor", "sub": "Fund", "tier": 0},
        {"id": "h", "label": "Holdco", "sub": "Parent", "tier": 1, "highlight": True}, {"id": "t", "label": "Target", "sub": "Opco", "tier": 2}],
        "links": [{"from": "s", "to": "h", "label": f"{p}%"}, {"from": "o", "to": "h", "label": f"{100 - p}%"}, {"from": "h", "to": "t", "label": "100%"}]}, {}


GEN = {"cover": g_cover, "exec": g_exec, "kpi": g_kpi, "stat": g_stat, "column": g_column, "combo": g_combo, "waterfall": g_waterfall,
       "ranked": g_ranked, "comps": g_comps, "football": g_football, "tombs": g_tombs, "sens": g_sens, "scatter": g_scatter,
       "stackcol": g_stackcol, "stackbar": g_stackbar, "matrix": g_matrix, "numbered": g_numbered, "process": g_process,
       "takeaway": g_takeaway, "recommend": g_recommend, "doughnut": g_doughnut, "line": g_line, "risk": g_risk, "timeline": g_timeline,
       "paired": g_paired, "harvey": g_harvey, "gantt": g_gantt, "small": g_small, "compare": g_compare, "scorecard": g_scorecard,
       "deal": g_deal}
NO_SRC = {"cover"}


def _plan(c: Ctx, n: int) -> list[str]:
    core, extra = FAMILY_PLANS[c.family]
    if c.ar:
        core = [k for k in core if k in AR_OK]
        extra = [k for k in extra if k in AR_OK] + ["combo", "line", "paired"]
    plan = list(core)
    pool = [k for k in extra if k not in plan]
    c.rng.shuffle(pool)
    while len(plan) < n and pool:                                    # insert extras before the closing slide
        plan.insert(len(plan) - 1, pool.pop())
    plan = plan[:n - 1] + [plan[-1]] if len(plan) > n else plan
    return plan


def _fix_adjacent(plan: list[str]) -> list[str]:
    for i in range(1, len(plan)):
        if ARCH[plan[i]] == ARCH[plan[i - 1]] and VTYPE[plan[i]] == VTYPE[plan[i - 1]]:
            for j in range(i + 1, len(plan)):
                if ARCH[plan[j]] != ARCH[plan[i - 1]]:
                    plan[i], plan[j] = plan[j], plan[i]
                    break
    return plan


def build_spec(idx: int, rng: random.Random) -> dict:
    regime = ["us_gaap", "ifrs", "mena"][idx % 3]
    family = list(FAMILY_PLANS)[(idx // 3) % 5]
    ar = idx % 16 == 5                                               # 6 of 100
    if ar:
        regime, family = "mena", AR_FAMILIES[(idx // 16) % 3]
    c = Ctx(rng, regime, family, "ar" if ar else "en", idx)
    n = 10 if rng.random() < 0.38 else rng.choice([6, 7, 8, 9, 11, 12])
    plan = _fix_adjacent(_plan(c, n))
    slides = []
    for i, key in enumerate(plan, 1):
        title, blocks, _ = GEN[key](c)
        s = {"id": f"s{i}", "archetype": ARCH[key], "title": title, "blocks": blocks}
        if key not in NO_SRC:
            s["source"] = "; ".join(c.src)
            s["sources"] = list(c.src)
            s["as_of"] = AS_OF
            if isinstance(blocks.get("takeaway"), str) and key not in ("takeaway",):
                blocks["takeaway"] = blocks["takeaway"].rstrip(". ") + " [1]"
        if key == "cover":
            s["visual"] = {"concept": f"abstract {c.sector} forms", "kind": rng.choice(["hero", "illustration"])}
        slides.append(s)
    art = "auto" if idx % 4 else ["editorial_illustration", "isometric_system", "line_art_schematic", "data_art", "duotone_hero",
                                  "annotated_map", "iconographic_system", "bold_typographic"][(idx // 4) % 8]
    return {"deck_id": c.deck_id, "title": slides[0]["title"], "lang": c.lang, "client": f"{c.name} board", "as_of": AS_OF,
            "art_direction": art, "theme": "house", "slides": slides}


def specs(n: int = 100, seed: int = 7) -> list[dict]:
    """`n` deterministic DeckSpecs; the same (n, seed) always gives the same list."""
    rng = random.Random(seed)
    return [build_spec(i, random.Random(rng.randrange(2 ** 31))) for i in range(n)]


if __name__ == "__main__":
    ss = specs(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
    print(len(ss), "specs;", sum(len(s["slides"]) == 10 for s in ss), "with 10 slides;", sum(s["lang"] == "ar" for s in ss), "Arabic")
