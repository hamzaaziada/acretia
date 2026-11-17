"""Demo org, users, deals and synthetic PDFs (SPEC §7). Idempotent; offline; no network.

`om/pdfwrite.py` is cp1252-only, so the demo corpus has no Arabic PDFs (Arabic detection is covered by tests that
build their own fixtures). Every PDF is labelled synthetic. Apple figures are abridged from public filings."""
from __future__ import annotations

import json
import os
import textwrap

from om.pdfwrite import PDFWriter

from . import auth, db, deals, notify, state as state_mod

ORG_NAME = "Meridian Capital Partners"
USERS = (("owner@meridian.example", "Olivia Hartmann", "owner"),
         ("analyst@meridian.example", "Amir Haddad", "member"),
         ("lp@meridian.example", "Laura Pemberton", "viewer"))
DEFINITIONS = {
    "Adjusted EBITDA": ("Operating profit before depreciation and amortisation, plus non-recurring items (restructuring, "
                        "transaction costs, impairment, litigation settlements above USD 1m), excluding IFRS 16 lease "
                        "expense adjustments and any gains on asset disposals."),
    "Net Debt": ("Interest-bearing borrowings and lease liabilities less cash and cash equivalents and short-term "
                 "deposits under three months; excludes restricted cash and shareholder loans."),
}
FOOT = "Synthetic demo document for Acretia - not real company information."


def demo_password() -> str:
    return os.environ.get("ACRETIA_DEMO_PASSWORD") or "demo-password-123"


# =========================================================================== PDF builder
def _w(text: str, size: float = 10) -> float:
    """Approximate Helvetica width in points (digits 0.556 em, punctuation narrower)."""
    tot = 0.0
    for ch in text:
        tot += 0.556 if ch.isdigit() else 0.278 if ch in ",.' " else 0.333 if ch in "()-" else 0.889 if ch == "%" else 0.5
    return tot * size


def build_pdf(title: str, subtitle: str, blocks: list) -> bytes:
    """blocks: ("h", text) | ("p", text) | ("t", header_row, rows) with rows of (label, v1, v2, ...) or ("b", ...) bold."""
    pdf, W, H, L, R = PDFWriter(), 612, 792, 54, 558
    state = {"y": 0, "n": 0}

    def newpage():
        pdf.page()
        state["n"] += 1
        state["y"] = H - 64
        pdf.text(L, H - 36, subtitle, size=8)
        pdf.line(L, H - 42, R, H - 42, 0.5)
        pdf.text(L, 30, FOOT, size=7)
        pdf.text(R - 40, 30, f"Page {state['n']}", size=7)

    def need(h):
        if state["y"] - h < 56:
            newpage()
    newpage()
    pdf.text(L, state["y"], title, size=16, font="Helvetica-Bold")
    state["y"] -= 30
    for blk in blocks:
        kind = blk[0]
        if kind == "h":
            need(36)
            state["y"] -= 8
            pdf.text(L, state["y"], blk[1], size=11, font="Helvetica-Bold")
            state["y"] -= 17
        elif kind == "p":
            for para in blk[1].split("\n"):
                for ln in textwrap.wrap(para, 96) or [""]:
                    need(14)
                    pdf.text(L, state["y"], ln, size=10)
                    state["y"] -= 13
            state["y"] -= 5
        elif kind == "t":
            header, rows = blk[1], blk[2]
            ncols = len(header)
            step = (R - 250) / max(ncols - 1, 1)
            rights = [250 + step * (i + 1) for i in range(ncols - 1)]
            need(16 * min(len(rows) + 2, 8))
            pdf.text(L, state["y"], header[0], size=9, font="Helvetica-Bold")
            for rx, hv in zip(rights, header[1:]):
                pdf.text(rx - _w(hv, 9) * 1.05, state["y"], hv, size=9, font="Helvetica-Bold")
            pdf.line(L, state["y"] - 4, R, state["y"] - 4, 0.6)
            state["y"] -= 17
            for row in rows:
                bold = row[0] == "b"
                cells = row[1:] if bold else row
                need(15)
                font = "Helvetica-Bold" if bold else "Helvetica"
                pdf.text(L, state["y"], str(cells[0]), size=9, font=font)
                for rx, v in zip(rights, cells[1:]):
                    v = str(v)
                    pdf.text(rx - _w(v, 9), state["y"], v, size=9, font=font)
                state["y"] -= 14
            state["y"] -= 6
    return pdf.to_bytes()


def _m(v: int) -> str:
    return f"({abs(v):,})" if v < 0 else f"{v:,}"


# =========================================================================== company data
def _nile() -> dict:
    yrs = ("FY2023", "FY2022", "FY2021")
    rev, cogs, sga, oth, da = (68420, 54110, 41230), (55310, 44020, 33870), (4980, 4010, 3150), (310, 240, 180), (1420, 1210, 1040)
    fin_c, fin_i = (2150, 1780, 1260), (390, 310, 220)
    gp = tuple(r - c for r, c in zip(rev, cogs))
    ebit = tuple(g - s + o for g, s, o in zip(gp, sga, oth))
    ebitda = tuple(e + d for e, d in zip(ebit, da))
    pbt = tuple(e - c + i for e, c, i in zip(ebit, fin_c, fin_i))
    tax = tuple(round(p * 0.225) for p in pbt)
    ni = tuple(p - t for p, t in zip(pbt, tax))
    return dict(
        name="ElSewedy Electric", legal="ElSewedy Electric Company S.A.E.", short="ElSewedy", ccy="EGP", unit="EGP million",
        yrs=yrs, rev=rev, cogs=cogs, gp=gp, sga=sga, oth=oth, ebit=ebit, da=da, ebitda=ebitda, fin_c=fin_c, fin_i=fin_i,
        pbt=pbt, tax=tax, ni=ni, rnd=None, debt=14800, cash=5250, lease=1180,
        one_offs=(("Restructuring - cable plant consolidation", 210), ("Transaction and advisory costs", 95),
                  ("Litigation settlement (above threshold)", 140), ("Gain on disposal of idle land", -85)),
        sector="Industrial - wires, cables and electrical products", target="ElSewedy Electric S.A.E.",
        cust="Egyptian Electricity Transmission Company", cust_what="supply of medium- and high-voltage power cables",
        cust_terms=(("Term", "Five years from 1 July 2022, renewable by mutual agreement for two further years."),
                    ("Minimum volume", "The Customer shall order not less than 4,200 tonnes of copper-equivalent cable per contract year."),
                    ("Pricing", "Price = LME copper (monthly average) plus a fabrication premium of EGP 38,500 per tonne, reviewed annually."),
                    ("Exclusivity", "The Supplier is the exclusive provider of 66 kV and 132 kV cable for the Customer's Delta region programme."),
                    ("Termination for convenience", "The Customer may terminate on 180 days' written notice; ordered but undelivered volumes remain payable."),
                    ("Change of control", "Any change of control of the Supplier requires the Customer's prior written consent, not to be unreasonably withheld; absent consent the Customer may terminate on 90 days' notice."),
                    ("Liquidated damages", "Delay damages of 0.5% of the affected order value per week, capped at 10%.")),
        market=("Egypt and the wider MENA region are investing heavily in grid expansion, renewable interconnection and "
                "urban electrification. Management estimates the addressable regional market for power and telecom cables at "
                "USD 6.4bn (2023) growing at 7-9% a year to 2028."),
        kpis=(("Revenue (EGP m)", "68,420", "54,110", "41,230"), ("Order backlog (EGP m)", "31,900", "24,400", "17,200"),
              ("Export share of revenue", "27%", "24%", "19%"), ("Copper tonnes processed (k)", "118", "109", "96"),
              ("Capacity utilisation", "81%", "76%", "70%")),
        board=(("Approval of FY2024 budget", "The Board approved the FY2024 budget with revenue of EGP 79.0bn and capex of EGP 3.2bn."),
               ("Facility Agreement covenant headroom", "The CFO reported Net Debt / Adjusted EBITDA of 1.0x against a 3.50x covenant."),
               ("Related-party transaction", "The Board noted a related-party lease of the Tenth of Ramadan warehouse at arm's-length terms (EGP 18m a year)."),
               ("Strategic review", "The Board authorised management to engage advisers on a sale process for a minority or majority stake (Project Nile).")),
        seller="the Selling Shareholders", date="14 December 2023", fac_date="14 March 2022", fac_amt="EGP 9,000 million",
    )


def _atlas() -> dict:
    yrs = ("FY2023", "FY2022", "FY2021")
    rev, cogs = (383285, 394328, 365817), (214137, 223546, 212981)
    gp = tuple(r - c for r, c in zip(rev, cogs))
    rnd, sga = (29915, 26251, 21914), (24932, 25094, 21973)
    ebit = tuple(g - a - b for g, a, b in zip(gp, rnd, sga))
    oth = (-565, -334, 258)
    da = (11519, 11104, 11284)
    pbt = tuple(e + o for e, o in zip(ebit, oth))
    tax, ni = (16741, 19300, 14527), tuple(p - t for p, t in zip(pbt, (16741, 19300, 14527)))
    return dict(
        name="Apple Inc.", legal="Apple Inc.", short="Apple", ccy="USD", unit="USD million", yrs=yrs, rev=rev, cogs=cogs, gp=gp,
        sga=sga, rnd=rnd, oth=oth, ebit=ebit, da=da, ebitda=tuple(e + d for e, d in zip(ebit, da)), fin_c=None, fin_i=None,
        pbt=pbt, tax=tax, ni=ni, debt=111088, cash=61555, lease=10408,
        one_offs=(("Restructuring and related charges", 310), ("Legal settlement (above threshold)", 480),
                  ("Transaction and advisory costs", 120), ("Gain on investment disposal", -210)),
        sector="Consumer technology - devices and services", target="Apple Inc.",
        cust="Northbridge Wireless Holdings", cust_what="carrier distribution and device financing programme",
        cust_terms=(("Term", "Four years from 1 October 2022 with automatic one-year renewals."),
                    ("Revenue share", "The Carrier receives a margin of 3.5% of net device sales and 15% of attached service subscriptions."),
                    ("Minimum commitment", "The Carrier shall purchase not less than 2.6 million units per contract year."),
                    ("Exclusivity", "No exclusivity; most-favoured-carrier pricing applies to launch-day allocation."),
                    ("Termination for convenience", "Either party may terminate on 120 days' notice after the second anniversary."),
                    ("Change of control", "A change of control of the Carrier requires the Company's prior written consent to assignment; a change of control of the Company does not require consent."),
                    ("Liquidated damages", "Shortfall against the minimum commitment is payable at USD 45 per unit.")),
        market=("Premium smartphone, wearables and services markets continue to consolidate around integrated ecosystems. "
                "Services revenue is the fastest-growing, highest-margin line. Figures are abridged from public filings."),
        kpis=(("Net sales (USD m)", "383,285", "394,328", "365,817"), ("Services net sales (USD m)", "85,200", "78,129", "68,425"),
              ("Gross margin", "44.1%", "43.3%", "41.8%"), ("Installed base (m devices)", "2,200", "2,000", "1,800"),
              ("Operating cash flow (USD m)", "110,543", "122,151", "104,038")),
        board=(("Approval of FY2024 plan", "The Board approved the FY2024 operating plan and a capital return programme of up to USD 90bn."),
               ("Credit facility covenant headroom", "The CFO reported Net Debt / Adjusted EBITDA of 0.3x against a 3.50x covenant."),
               ("Related-party transaction", "The Board reviewed a related-party engagement of a design consultancy on arm's-length terms (USD 12m)."),
               ("Strategic review", "The Board authorised management to evaluate a minority strategic investment process (Project Atlas).")),
        seller="the Company", date="9 November 2023", fac_date="5 May 2022", fac_amt="USD 25,000 million",
    )


# =========================================================================== document builders
def _income_statement(c) -> bytes:
    rows = [("Revenue", *map(_m, c["rev"])), ("Cost of sales", *map(lambda v: _m(-v), c["cogs"])), ("b", "Gross profit", *map(_m, c["gp"]))]
    if c.get("rnd"):
        rows += [("Research and development", *map(lambda v: _m(-v), c["rnd"]))]
    rows += [("Selling, general and administrative", *map(lambda v: _m(-v), c["sga"]))]
    if not c.get("rnd"):
        rows += [("Other operating income", *map(_m, c["oth"]))]
    rows += [("b", "Operating profit (EBIT)", *map(_m, c["ebit"]))]
    if c["fin_c"]:
        rows += [("Finance costs", *map(lambda v: _m(-v), c["fin_c"])), ("Finance income", *map(_m, c["fin_i"]))]
    else:
        rows += [("Other income / (expense), net", *map(_m, c["oth"]))]
    rows += [("b", "Profit before tax", *map(_m, c["pbt"])), ("Income tax", *map(lambda v: _m(-v), c["tax"])),
             ("b", "Net income", *map(_m, c["ni"]))]
    return build_pdf(f"{c['legal']} - Annual Report FY2023 (excerpt)", f"{c['name']} | Annual report excerpt | {c['unit']}", [
        ("h", "Management discussion"),
        ("p", f"{c['name']} delivered revenue of {c['ccy']} {_m(c['rev'][0])} million in FY2023, a change of "
              f"{(c['rev'][0] / c['rev'][1] - 1) * 100:+.1f}% on FY2022. Gross margin was {c['gp'][0] / c['rev'][0] * 100:.1f}% "
              f"and operating margin {c['ebit'][0] / c['rev'][0] * 100:.1f}%. Depreciation and amortisation was "
              f"{_m(c['da'][0])} million, giving reported EBITDA of {_m(c['ebitda'][0])} million."),
        ("h", f"Consolidated income statement ({c['unit']})"),
        ("t", ("Line item", *c["yrs"]), rows),
        ("h", "Selected balance sheet items at year end"),
        ("t", ("Item", "FY2023"), [("Interest-bearing borrowings", _m(c["debt"])), ("Lease liabilities", _m(c["lease"])),
                                    ("Cash and cash equivalents", _m(c["cash"])),
                                    ("b", "Net debt (as defined by the firm)", _m(c["debt"] + c["lease"] - c["cash"]))]),
        ("p", "Note 12. Borrowings are unsecured except for project finance facilities. See the Facility Agreement for "
              "covenants and change-of-control provisions."),
    ])


def _qoe(c) -> bytes:
    adj = sum(v for _, v in c["one_offs"])
    rows = [("Reported EBITDA", _m(c["ebitda"][0]))] + [(f"  {n}", _m(v)) for n, v in c["one_offs"]] + [
        ("b", "Adjusted EBITDA", _m(c["ebitda"][0] + adj))]
    nd = c["debt"] + c["lease"] - c["cash"]
    return build_pdf(f"{c['name']} - Quality of earnings: EBITDA bridge", f"{c['name']} | Quality of earnings | {c['unit']}", [
        ("h", "Purpose"),
        ("p", "This schedule bridges reported EBITDA to Adjusted EBITDA using the firm definition: operating profit before "
              "depreciation and amortisation plus non-recurring items. Items are shown with the sign applied to EBITDA."),
        ("h", f"EBITDA bridge FY2023 ({c['unit']})"),
        ("t", ("Item", "FY2023"), rows),
        ("h", "Net debt bridge at 31 December 2023"),
        ("t", ("Item", "Amount"), [("Interest-bearing borrowings", _m(c["debt"])), ("Lease liabilities", _m(c["lease"])),
                                    ("Less: cash and cash equivalents", _m(-c["cash"])), ("b", "Net debt", _m(nd))]),
        ("p", f"Net debt / Adjusted EBITDA is {nd / (c['ebitda'][0] + adj):.2f}x. Adjustments were reviewed against "
              "supporting invoices and board papers; the litigation settlement requires legal confirmation."),
    ])


def _facility(c) -> bytes:
    return build_pdf(f"Facility Agreement - {c['legal']} (extract)", f"{c['name']} | Facility Agreement dated {c['fac_date']} | extract", [
        ("p", f"Between {c['legal']} (the Borrower) and the Lenders named in Schedule 1, for a committed term and revolving "
              f"facility of {c['fac_amt']} (the Facility)."),
        ("h", "1. Definitions"),
        ("p", "'Change of Control' means any person, or group of persons acting in concert, acquiring (directly or indirectly) "
              "more than 30 per cent of the voting share capital of the Borrower, or the right to appoint or remove a majority "
              "of its board of directors."),
        ("p", "'Net Debt' and 'EBITDA' have the meanings given in Schedule 4 (Financial Covenants)."),
        ("h", "7.4 Change of Control"),
        ("p", "Upon a Change of Control the Borrower shall promptly notify the Agent. No Lender is obliged to fund a new "
              "Utilisation, and any Lender may, by notice to the Agent within 30 days of the notification, cancel its "
              "Commitment and require repayment of its participation, together with accrued interest, within 30 days of that notice."),
        ("h", "22. Financial covenants"),
        ("t", ("Covenant", "Threshold", "FY2023 actual"), [("Net Debt / EBITDA (maximum)", "3.50x", "see QoE"),
                                                            ("Interest cover (minimum)", "3.00x", "above 3.0x"),
                                                            ("Tangible net worth (minimum)", f"{c['ccy']} 1,000m", "compliant")]),
        ("h", "23. Restricted payments and disposals"),
        ("p", "The Borrower shall not declare dividends exceeding 50 per cent of consolidated net income in any financial "
              "year while a Default is continuing, nor dispose of assets with a book value above 10 per cent of total assets "
              "in aggregate without the consent of the Majority Lenders."),
        ("h", "26. Events of Default"),
        ("p", "Non-payment; breach of financial covenants not remedied within 15 Business Days; cross-default above "
              f"{c['ccy']} 150 million; insolvency; unlawfulness; material adverse change."),
        ("h", "34. Governing law"),
        ("p", "This Agreement is governed by English law. The courts of England have exclusive jurisdiction."),
    ])


def _contract(c) -> bytes:
    return build_pdf(f"Commercial agreement - {c['cust']} (extract)", f"{c['name']} | Customer contract | extract", [
        ("p", f"Agreement between {c['legal']} (the Supplier) and {c['cust']} (the Customer) for the {c['cust_what']}."),
        ("h", "Key terms"),
        *[x for t, txt in c["cust_terms"] for x in (("p", f"{t}. {txt}"),)],
        ("h", "Warranties and limitation of liability"),
        ("p", "The Supplier warrants conformity to the agreed specification for 24 months. Aggregate liability is limited to "
              "125% of the fees paid in the preceding contract year, excluding wilful misconduct."),
        ("h", "Governing law"),
        ("p", "Governed by the laws of the Supplier's jurisdiction; disputes are referred to arbitration under ICC rules."),
    ])


def _minutes(c) -> bytes:
    blocks = [("p", f"Minutes of the meeting of the Board of Directors of {c['legal']} held on {c['date']}. "
                    "Present: Chair, Chief Executive Officer, Chief Financial Officer, four non-executive directors, the General "
                    "Counsel (secretary). Quorum confirmed.")]
    for i, (t, txt) in enumerate(c["board"], 1):
        blocks += [("h", f"{i}. {t}"), ("p", txt)]
    blocks += [("h", "Resolutions"), ("p", "The Board resolved to approve items 1 and 4 and to note items 2 and 3. "
                                            "There being no further business, the meeting closed.")]
    return build_pdf(f"Board Minutes - {c['date']}", f"{c['name']} | Board of Directors | minutes", blocks)


def _cim(c) -> bytes:
    return build_pdf(f"{c['name']} - Confidential Information Memorandum (excerpt)", f"{c['name']} | CIM excerpt | strictly confidential", [
        ("h", "Investment highlights"),
        ("p", f"1. Leading position in {c['sector'].lower()}.\n2. Diversified customer base and resilient cash conversion.\n"
              "3. Clear operational levers: pricing, mix and procurement.\n4. Experienced management team with a long track record."),
        ("h", "Market"),
        ("p", c["market"]),
        ("h", "Key performance indicators"),
        ("t", ("KPI", *c["yrs"]), [tuple(k) for k in c["kpis"]]),
        ("h", "Process"),
        ("p", f"Indicative offers are invited from qualified investors. {c['seller'].capitalize()} reserve the right to amend the "
              "process at any time. This document is for evaluation only and does not constitute an offer."),
    ])


def _docs(c) -> list:
    return [("01 Financials", "Annual Report FY2023 (excerpt).pdf", _income_statement(c)),
            ("01 Financials", "Quality of Earnings - EBITDA bridge.pdf", _qoe(c)),
            ("02 Legal", "Facility Agreement (extract).pdf", _facility(c)),
            ("03 Commercial", f"Customer contract - {c['cust']}.pdf", _contract(c)),
            ("04 Corporate", "Board Minutes - Q4 2023.pdf", _minutes(c)),
            ("05 Marketing", "Confidential Information Memorandum (excerpt).pdf", _cim(c))]


DEALS = (("Project Nile — ElSewedy Electric", _nile), ("Project Atlas — Apple Inc.", _atlas))


# =========================================================================== seeding
def _ensure_org(conn, pw) -> tuple[str, dict]:
    row = conn.execute("SELECT id FROM orgs WHERE name=?", (ORG_NAME,)).fetchone()
    ids = {}
    if row is None:
        res = auth.create_org(conn, ORG_NAME, USERS[0][0], pw, USERS[0][1])
        org_id, ids[USERS[0][0]] = res["org_id"], res["user_id"]
    else:
        org_id = row["id"]
    for email, name, role in USERS:
        u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        uid = u["id"] if u else auth.create_user(conn, email, pw, name)
        if not conn.execute("SELECT 1 FROM memberships WHERE org_id=? AND user_id=?", (org_id, uid)).fetchone():
            auth.add_membership(conn, org_id, uid, role)
        ids[email] = uid
    r = conn.execute("SELECT settings_json FROM orgs WHERE id=?", (org_id,)).fetchone()
    settings = json.loads(r["settings_json"] or "{}")
    if not settings.get("definitions"):
        settings["definitions"] = dict(DEFINITIONS)
        conn.execute("UPDATE orgs SET settings_json=? WHERE id=?", (json.dumps(settings, sort_keys=True), org_id))
    return org_id, ids


def seed(data_dir, state=None) -> dict:
    """Create or top up the demo data in `data_dir`. Safe to run repeatedly."""
    st = state or state_mod.create(data_dir, demo=True)
    conn = st.conn()
    db.migrate(conn)
    pw = demo_password()
    org_id, ids = _ensure_org(conn, pw)
    owner = ids[USERS[0][0]]
    store = st.deal_store(conn, org_id)
    out = {"org_id": org_id, "deals": {}, "documents_added": 0}
    first_run = conn.execute("SELECT COUNT(*) FROM audit_log WHERE org_id=? AND action='demo.seed'", (org_id,)).fetchone()[0] == 0
    for name, factory in DEALS:
        c = factory()
        row = conn.execute("SELECT deal_id FROM deals WHERE org_id=? AND name=?", (org_id, name)).fetchone()
        deal_id = row["deal_id"] if row else deals.create_deal_record(
            conn, store, org_id, owner, name, target=c["target"], sector=c["sector"], status="active")
        out["deals"][name] = deal_id
        for folder, fname, data in _docs(c):
            if conn.execute("SELECT 1 FROM documents WHERE org_id=? AND deal_id=? AND name=? AND folder=?",
                            (org_id, deal_id, fname, folder)).fetchone():
                continue
            doc_id = db.new_id("doc")
            conn.execute("INSERT INTO documents(id,org_id,deal_id,name,kind,sha256,size,created_at,folder,uploaded_by) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?)", (doc_id, org_id, deal_id, fname, "pdf", st.blobs.put(data), len(data),
                                                          db.now(), folder, owner))
            deals.index_document_sync(st, doc_id)
            out["documents_added"] += 1
        if not store.history(deal_id, "Diligence checklist.txt"):
            lines = [f"{name} - diligence checklist", "", "[ ] Quality of earnings bridge reviewed", "[ ] Facility Agreement change-of-control clause",
                     "[ ] Customer contract termination rights", "[ ] Board minutes - related-party items"]
            store.save_deliverable(deal_id, "Diligence checklist.txt", "\n".join(lines).encode(), "other", "first draft")
            lines[2] = "[x] Quality of earnings bridge reviewed"
            lines.append("[ ] Management accounts reconciliation")
            store.save_deliverable(deal_id, "Diligence checklist.txt", "\n".join(lines).encode(), "other", "QoE reviewed")
    if first_run:
        notify.notify(conn, org_id, None, "welcome", "Welcome to Acretia",
                      "Two demo deals with data-room documents are ready. Open a deal to review documents.", "/")
        st.audit(conn, org_id, owner, "demo.seed", f"org:{org_id}", {"deals": len(DEALS)})
    out["users"] = {e: ids[e] for e, _n, _r in USERS}
    out["password_env"] = "ACRETIA_DEMO_PASSWORD"
    return out
