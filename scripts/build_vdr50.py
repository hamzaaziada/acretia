#!/usr/bin/env python3
"""Build the S5.4b 50-document data room: evals/vdr50/ (docs, manifest.json, gold.jsonl, risk_gold.json).

  python3 scripts/build_vdr50.py            # (re)writes synthetic PDFs + manifest/gold/risk gold, verifies gold quotes
  python3 scripts/build_vdr50.py --force-arabic   # also re-run LibreOffice for the Arabic PDFs (otherwise cached files are kept)

Room = 10 real 10-K PDFs (byte-identical copies of evals/tenk/pdfs, sha256-checked; 1.6 MB) + 40 synthetic diligence documents
(34 text-layer English, 3 scanned image-only, 3 Arabic). Every number / clause is planted, so gold is known by construction;
gold quotes are re-verified against what om.pdfdoc extracts (OCR text for scanned pages) and the build fails if one is off.
Deterministic: the PDFWriter output is byte-stable; the Arabic PDFs are LibreOffice output, cached once in the repo.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from om import docparse  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402

OUT = ROOT / "evals" / "vdr50"
DOCS = OUT / "docs"
TENK = ROOT / "evals" / "tenk"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_B = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

# the column set run on every document of the room (D-032 first pass); gold is per (doc, question)
VDR_QUESTIONS = [
    {"id": "v01", "text": "Who are the parties to the agreement?", "type": "text"},
    {"id": "v02", "text": "What is the expiry date or term end date of the agreement?", "type": "date"},
    {"id": "v03", "text": "What happens upon a change of control?", "type": "text"},
    {"id": "v04", "text": "Is assignment of the agreement restricted without consent?", "type": "text"},
    {"id": "v05", "text": "Is there an exclusivity or non-compete obligation?", "type": "text"},
    {"id": "v06", "text": "Is there a most favoured nation (MFN) pricing clause?", "type": "text"},
    {"id": "v07", "text": "What is the governing law?", "type": "text"},
    {"id": "v08", "text": "What is the maximum total leverage ratio covenant?", "type": "number"},
    {"id": "v09", "text": "What was total revenue for the fiscal year?", "type": "currency"},
    {"id": "v10", "text": "Who is the independent auditor?", "type": "text"},
    {"id": "v11", "text": "What is the minimum interest coverage ratio covenant?", "type": "number"},
    {"id": "v12", "text": "What is the annual base rent or annual fee payable?", "type": "currency"},
    {"id": "v13", "text": "What is the notice period for termination?", "type": "text"},
]
QTEXT = {q["id"]: q for q in VDR_QUESTIONS}

# ------------------------------------------------------------------------------------------------ layout engine
_FONTS = {}


def _font(bold):
    from PIL import ImageFont
    k = bool(bold)
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(FONT_B if bold else FONT_R, 100)
    return _FONTS[k]


def tw(s, size, bold=False):
    return _font(bold).getlength(s) * size / 100.0


def wrap(text, width, size, bold=False):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tw(t, size, bold) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Layout:
    """Top-down text layout. ops per page: ('t',x,ytop,text,size,bold) ('l',x0,y0,x1,y1) ('r',x,ytop,w,h,fill)."""
    W, H, M, TOP, BOT = 612, 792, 54, 64, 740

    def __init__(self, footer="", header="", cols=1, body=10.0, gap=22):
        self.pages, self.footer, self.header = [], footer, header
        self.cols, self.body, self.gap = cols, body, gap
        self.lh = body * 1.32
        self.col = 0
        self._new()
        self.clause = 0
        self.sub = 0

    def _new(self):
        self.pages.append([])
        self.y = self.TOP
        self.col = 0

    @property
    def colw(self):
        return (self.W - 2 * self.M - self.gap * (self.cols - 1)) / self.cols

    @property
    def x0(self):
        return self.M + self.col * (self.colw + self.gap)

    def _ensure(self, h):
        if self.y + h > self.BOT:
            if self.col + 1 < self.cols:
                self.col += 1
                self.y = self.TOP
            else:
                self._new()

    def page_break(self):
        self._new()

    def text(self, s, size=None, bold=False, indent=0.0, space=0.0, align="l"):
        size = size or self.body
        lines = wrap(s, self.colw - indent, size, bold)
        self._ensure(len(lines[:2]) * size * 1.32)
        for ln in lines:
            self._ensure(size * 1.32)
            self.pages[-1].append(("t", self.x0 + indent, self.y, ln, size, bold))
            self.y += size * 1.32
        self.y += space

    def title(self, s):
        self.text(s, size=15, bold=True, space=6)

    def h(self, s):
        self.clause += 1
        self.sub = 0
        self.y += 3
        self.text(f"{self.clause}. {s}", size=self.body + 1, bold=True, space=2)

    def p(self, s, numbered=True):
        if numbered and self.clause:
            self.sub += 1
            s = f"{self.clause}.{self.sub} {s}"
        self.text(s, space=3.5)

    def raw(self, s, **kw):
        self.text(s, space=3.5, **kw)

    def table(self, rows, widths, header=True, size=9.0):
        rh = size * 1.7
        total = sum(widths)
        scale = min(1.0, self.colw / total)
        ws = [w * scale for w in widths]
        for i, row in enumerate(rows):
            self._ensure(rh)
            x = self.x0
            if i == 0 and header:
                self.pages[-1].append(("r", x, self.y, sum(ws), rh, (0.9, 0.9, 0.93)))
            for j, cell in enumerate(row):
                bold = (i == 0 and header)
                s = str(cell)
                if j > 0 and re.fullmatch(r"[\$\(\)\-\d,.%x ]+", s) and not bold:
                    xx = x + ws[j] - 3 - tw(s, size)
                else:
                    xx = x + 3
                self.pages[-1].append(("t", xx, self.y + 3, s, size, bold))
                x += ws[j]
            self.pages[-1].append(("l", self.x0, self.y + rh, self.x0 + sum(ws), self.y + rh))
            self.y += rh
        self.y += 6

    def finish(self):
        n = len(self.pages)
        for i, ops in enumerate(self.pages):
            if self.header:
                ops.append(("t", self.M, 36, self.header, 8, False))
            ops.append(("l", self.M, 752, self.W - self.M, 752))
            ops.append(("t", self.M, 762, self.footer, 8, False))
            pn = f"Page {i + 1} of {n}"
            ops.append(("t", self.W - self.M - tw(pn, 8), 762, pn, 8, False))
        return self.pages


FILLER = [
    "Each party shall keep complete and accurate records relating to this Agreement for a period of six years and shall make them available to the other party on reasonable request during business hours.",
    "Invoices are payable within thirty days of receipt in the currency stated in the relevant schedule, without set-off, and amounts not paid when due bear interest at two percent above the base rate.",
    "Each party shall comply with all applicable anti-bribery, sanctions and export control requirements and shall maintain adequate procedures designed to prevent any breach of them.",
    "Neither party shall be liable for delay or failure caused by events beyond its reasonable control, provided that it uses reasonable efforts to mitigate the effect of the event and resumes performance promptly.",
    "Each party shall keep the terms of this Agreement and all non-public information received from the other party confidential and shall use it only for the purposes of this Agreement.",
    "Personal data shall be processed only as required to perform this Agreement and in accordance with applicable data protection legislation, with appropriate technical and organisational safeguards.",
    "This Agreement may be executed in counterparts, each of which is an original and all of which together constitute one instrument, and signatures delivered electronically are effective.",
    "If any provision of this Agreement is held to be invalid or unenforceable, the remaining provisions continue in full force and the parties shall negotiate a valid substitute of similar effect.",
    "No failure or delay in exercising a right operates as a waiver of it, and no single or partial exercise of a right prevents any further exercise of that or any other right.",
    "This Agreement and its schedules constitute the entire agreement between the parties and supersede all prior discussions, representations and understandings on the same subject matter.",
    "Headings are for convenience only and do not affect interpretation; references to a statute include that statute as amended or re-enacted from time to time.",
    "Each party warrants that it has full power and authority to enter into and perform this Agreement and that doing so does not breach any other obligation by which it is bound.",
    "The supplier shall perform the services with reasonable skill and care, using suitably qualified personnel, and shall remedy any defect notified within a reasonable period at its own cost.",
    "Delivery dates are estimates unless stated to be of the essence; risk in the goods passes on delivery and title passes when the price has been paid in full.",
    "The parties shall appoint a relationship manager each, who shall meet quarterly to review performance, forecasts and any operational issues arising under this Agreement.",
    "Each party shall bear its own costs in connection with the negotiation and execution of this Agreement, and stamp duties, if any, shall be borne equally.",
    "A person who is not a party to this Agreement has no right to enforce any of its terms, and the parties may vary it without the consent of any such person.",
    "All amounts stated are exclusive of value added tax and similar taxes, which shall be added at the applicable rate where chargeable on a valid tax invoice.",
    "The parties acknowledge that the pricing schedule has been negotiated at arm's length and reflects the volumes, specifications and service levels described in the schedules.",
    "Quality inspections may be carried out at reasonable times on reasonable advance notice by representatives of either party, and findings shall be shared within ten business days.",
]


def fill(lay, k, seed):
    for i in range(k):
        lay.p(FILLER[(seed + i * 7) % len(FILLER)])


# ------------------------------------------------------------------------------------------------ emitters
def to_vector_pdf(pages):
    w = PDFWriter()
    for ops in pages:
        w.page()
        for op in ops:
            if op[0] == "t":
                _, x, y, s, size, bold = op
                w.text(x, Layout.H - y - size * 0.9, s, size, "Helvetica-Bold" if bold else "Helvetica")
            elif op[0] == "l":
                _, x0, y0, x1, y1 = op
                w.line(x0, Layout.H - y0, x1, Layout.H - y1, 0.5)
            elif op[0] == "r":
                _, x, y, ww, hh, fill_ = op
                w.rect(x, Layout.H - y - hh, ww, hh, fill=fill_, stroke=False)
    return w.to_bytes()


def to_scanned_pdf(pages, dpi=200, seed=7):
    """Rasterise each page at `dpi` into a grey bitmap (light noise, 0.25 degree skew) and embed it with no text layer."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import random
    rnd = random.Random(seed)
    sc = dpi / 72.0
    w = PDFWriter()
    for ops in pages:
        W, H = int(Layout.W * sc), int(Layout.H * sc)
        im = Image.new("L", (W, H), 255)
        dr = ImageDraw.Draw(im)
        for op in ops:
            if op[0] == "t":
                _, x, y, s, size, bold = op
                f = ImageFont.truetype(FONT_B if bold else FONT_R, max(8, int(round(size * sc))))
                dr.text((x * sc, y * sc), s, fill=20, font=f)
            elif op[0] == "l":
                _, x0, y0, x1, y1 = op
                dr.line((x0 * sc, y0 * sc, x1 * sc, y1 * sc), fill=60, width=2)
            elif op[0] == "r":
                _, x, y, ww, hh, _f = op
                dr.rectangle((x * sc, y * sc, (x + ww) * sc, (y + hh) * sc), fill=232)
        im = im.rotate(0.25, resample=Image.BICUBIC, fillcolor=255)
        px = im.load()
        for _ in range(int(W * H * 0.0004)):
            px[rnd.randrange(W), rnd.randrange(H)] = rnd.choice((190, 215))
        im = im.filter(ImageFilter.GaussianBlur(0.4))
        w.page()
        w.image_gray(0, 0, Layout.W, Layout.H, im.tobytes(), W, H)
    return w.to_bytes()


# ------------------------------------------------------------------------------------------------ documents
ENTITY = "Meridian Components Holdings, Inc."
SHORT = "Meridian"
DOCS_SPEC: list[dict] = []     # filled by add()


def add(path, kind, pdf_fn, facts=None, nf=None, risks=None, language="en", scanned=False, room="vdr_en", pages_min=1, note=""):
    DOCS_SPEC.append({"path": path, "kind": kind, "fn": pdf_fn, "facts": facts or [], "nf": nf or [], "risks": risks or [],
                      "language": language, "scanned": scanned, "room": room, "note": note})


def F(qid, answer, quote, unit=None, alt=None):
    d = {"qid": qid, "answer": answer, "quote": quote}
    if unit:
        d["unit"] = unit
    if alt:
        d["alt"] = alt
    return d


def P(qid, answer, rx, unit=None, n=1):
    """Gold picked from what pdfdoc extracts (Arabic text comes out in visual order): the first line matching rx (+ n-1 following)."""
    d = F(qid, answer, None, unit)
    d["pick"] = (rx, n)
    return d


def contract(title, ref, parties, date_s, clauses, filler=3, cols=1, seed=0, scan=False, footer=None, body=10.0):
    """clauses: list of (heading, [paragraph, ...]). Returns pages."""
    lay = Layout(footer=footer or f"{ref} | CONFIDENTIAL - Meridian virtual data room", cols=1, body=body)
    lay.title(title)
    lay.raw(f"Reference {ref}. Dated {date_s}.")
    lay.raw(f"This Agreement is made between {parties}.")
    for hd, paras in clauses:
        lay.h(hd)
        for ptxt in paras:
            lay.p(ptxt)
        fill(lay, filler, seed + lay.clause)
    lay.raw("Signed by the duly authorised representatives of the parties on the date first written above.")
    return lay.finish()


def contract2(title, ref, parties, date_s, clauses, filler=3, seed=0, footer=None):
    """Two-column body under a one-column title block."""
    lay = Layout(footer=footer or f"{ref} | CONFIDENTIAL - Meridian virtual data room", cols=1)
    lay.title(title)
    lay.raw(f"Reference {ref}. Dated {date_s}.")
    lay.raw(f"This Agreement is made between {parties}.")
    lay.cols = 2
    lay.y += 4
    for hd, paras in clauses:
        lay.h(hd)
        for ptxt in paras:
            lay.p(ptxt)
        fill(lay, filler, seed + lay.clause)
    lay.raw("Signed by the duly authorised representatives of the parties.")
    return lay.finish()


def statements(fy, rev, ni, assets, cash, auditor, note_year, prior, pages=3, seed=0):
    lay = Layout(footer=f"{SHORT} audited financial statements FY{fy} | CONFIDENTIAL", header=f"{ENTITY}")
    lay.title(f"{ENTITY} - Audited Financial Statements for the year ended 31 December {fy}")
    lay.raw("Independent Auditor's Report to the shareholders of " + ENTITY + ".")
    lay.raw(f"We have audited the accompanying consolidated financial statements for the fiscal year ended 31 December {fy}.")
    lay.raw(f"The auditor of the group is {auditor}, Chartered Accountants.")
    lay.raw("Signed " + auditor + f", 14 March {fy + 1}.")
    lay.page_break()
    lay.title("Consolidated statement of operations (USD)")
    lay.table([["", f"FY{fy}", f"FY{fy - 1}"],
               ["Total revenue", f"{rev:,}", f"{prior:,}"],
               ["Cost of sales", f"({int(rev * 0.62):,})", f"({int(prior * 0.63):,})"],
               ["Gross profit", f"{int(rev * 0.38):,}", f"{int(prior * 0.37):,}"],
               ["Operating expenses", f"({int(rev * 0.27):,})", f"({int(prior * 0.28):,})"],
               ["Net income", f"{ni:,}", f"{int(ni * 0.86):,}"]], [230, 110, 110])
    lay.page_break()
    lay.title("Consolidated balance sheet (USD)")
    lay.table([["", f"31 Dec {fy}", f"31 Dec {fy - 1}"],
               ["Cash and cash equivalents", f"{cash:,}", f"{int(cash * 0.8):,}"],
               ["Trade receivables", f"{int(rev * 0.14):,}", f"{int(prior * 0.14):,}"],
               ["Total assets", f"{assets:,}", f"{int(assets * 0.92):,}"],
               ["Total liabilities", f"{int(assets * 0.55):,}", f"{int(assets * 0.52):,}"]], [230, 110, 110])
    lay.raw(note_year)
    return lay.finish()


def mgmt(month, year, rev):
    lay = Layout(footer=f"Management accounts {month} {year} | UNAUDITED", header=f"{ENTITY} - management reporting pack")
    lay.title(f"Management Accounts - {month} {year} (unaudited)")
    lay.table([["USD", "Month", "Budget", "Prior year"],
               ["Revenue for the month", f"{rev:,}", f"{int(rev * 1.04):,}", f"{int(rev * 0.93):,}"],
               ["Gross margin", f"{int(rev * 0.38):,}", f"{int(rev * 0.39):,}", f"{int(rev * 0.34):,}"],
               ["Operating costs", f"({int(rev * 0.27):,})", f"({int(rev * 0.26):,})", f"({int(rev * 0.26):,})"],
               ["EBITDA", f"{int(rev * 0.15):,}", f"{int(rev * 0.17):,}", f"{int(rev * 0.11):,}"]], [190, 90, 90, 90])
    lay.raw(f"Headcount at month end was {410 + len(month) * 3}. Order intake was in line with the budget.")
    return lay.finish()


# ---- registry of the synthetic documents
def build_registry():
    A = add
    # ------------------------------------------------ 01 Financials
    for fy, rev, ni, assets, cash, prior in [(2021, 35870000, 3011000, 41200000, 5120000, 31200000),
                                              (2022, 39410000, 3634000, 45900000, 6240000, 35870000),
                                              (2024, 48250000, 5021000, 58800000, 9310000, 44100000)]:
        aud = "Whitfield & Crane LLP"
        q = f"Total revenue {rev:,} {prior:,}"
        A(f"01 Financials/Audited/Audited Financial Statements FY{fy}.pdf", "audited_financials",
          (lambda fy=fy, rev=rev, ni=ni, assets=assets, cash=cash, prior=prior, aud=aud:
           statements(fy, rev, ni, assets, cash, aud, f"The financial statements were approved by the board on 14 March {fy + 1}.", prior)),
          facts=[F("v09", rev, q, "usd"), F("v10", aud, f"The auditor of the group is {aud}, Chartered Accountants.")],
          nf=["v03", "v08"],
          risks=([{"type": "conflicting_figure", "role": "base", "metric": "revenue FY2024"}] if fy == 2024 else []))
    for mi, (mon, rev) in enumerate([("January", 3910000), ("February", 3840000), ("March", 4120000), ("April", 4060000),
                                      ("June", 4290000)]):
        A(f"01 Financials/Management Accounts/Management Accounts {mon} 2025.pdf", "management_accounts",
          (lambda mon=mon, rev=rev: mgmt(mon, 2025, rev)), facts=[F("v09", rev, f"Revenue for the month {rev:,}", "usd")] if mi in (0, 4) else [],
          nf=["v10", "v12"] if mi in (1, 3) else [])
    A("01 Financials/Budget/Budget and Forecast FY2025.pdf", "budget",
      lambda: (lambda lay: (lay.title("Budget and forecast for FY2025 (USD)"),
                            lay.table([["", "FY2025 budget", "FY2025 forecast"], ["Total revenue", "51,400,000", "50,900,000"],
                                       ["EBITDA", "7,800,000", "7,500,000"]], [200, 120, 120]), lay.finish())[-1])(Layout(footer="Budget FY2025 | CONFIDENTIAL")),
      facts=[F("v09", 51400000, "Total revenue 51,400,000 50,900,000", "usd")], nf=["v07"])
    A("01 Financials/CIM/Confidential Information Memorandum - Excerpt.pdf", "cim",
      lambda: _cim(),
      facts=[F("v09", 52900000, "Total revenue for the fiscal year ended 31 December 2024 was USD 52,900,000.", "usd")],
      nf=["v03", "v10"], risks=[{"type": "conflicting_figure", "role": "conflict", "metric": "revenue FY2024"}])

    # ------------------------------------------------ 02 Legal / material contracts: customers
    cust = [
        ("Northwind Aerospace Ltd", "CUST-014", "31 December 2028", "England and Wales", "ninety (90) days", 2200000,
         "Northwind Aerospace Ltd shall have the benefit of most favoured nation pricing: the prices charged shall be no less favourable than those offered to any other customer purchasing comparable volumes.",
         "Meridian shall not supply any competing aerospace customer in the Territory during the term of this Agreement and Northwind is the exclusive customer for the Product Line.",
         "Either party may terminate this Agreement for convenience on ninety (90) days written notice.",
         "If Meridian undergoes a change of control, Northwind Aerospace Ltd may terminate this Agreement by written notice within sixty days.", False),
        ("Castellan Retail Group plc", "CUST-021", "30 June 2027", "Delaware", "one hundred eighty (180) days", 1750000,
         None, None, "Either party may terminate this Agreement for convenience on one hundred eighty (180) days written notice.",
         "A change of control of Meridian requires Castellan's prior written consent, failing which this Agreement shall terminate automatically.", False),
        ("Brightline Utilities Inc.", "CUST-033", "15 March 2029", "New York", "sixty (60) days", 3100000,
         "Pricing under this Agreement shall be subject to a most favoured nation adjustment, with a retroactive rebate of any price difference payable within thirty days of an audit.",
         None, "Brightline may terminate this Agreement for convenience on sixty (60) days written notice.", None, False),
        ("Orion Medical Systems GmbH", "CUST-040", "31 October 2026", "Germany", "ninety (90) days", 980000,
         None, "Orion Medical Systems GmbH shall purchase the Components exclusively from Meridian for the duration of this Agreement.",
         "Either party may terminate this Agreement on ninety (90) days written notice.", None, False),
    ]
    for i, (cn, ref, exp, law, notice, fee, mfn, excl, term, coc, twocol) in enumerate(cust):
        parties = f"{ENTITY} (the Supplier) and {cn} (the Customer)"
        clauses = [("Supply", [f"The Supplier shall supply and the Customer shall purchase the Components in accordance with the order forecast agreed under this Agreement."]),
                   ("Term", [f"This Agreement expires on {exp} unless renewed in writing.", term]),
                   ("Pricing", [f"The annual base fee payable by the Customer under this Agreement is ${fee:,}."] + ([mfn] if mfn else []) +
                    ["Prices are fixed for each contract year and are reviewed annually by the relationship managers."])]
        res = []
        if excl:
            res.append(("Exclusivity", [excl]))
        if coc:
            res.append(("Change of control", [coc]))
        res.append(("Assignment", [f"Neither party may assign or transfer this Agreement without the prior written consent of the other party, such consent not to be unreasonably withheld."]))
        res.append(("Governing law", [f"This Agreement is governed by the laws of {law}."]))
        clauses += res
        facts = [F("v01", ENTITY, f"This Agreement is made between {parties}."),
                 F("v02", exp, f"This Agreement expires on {exp} unless renewed in writing."),
                 F("v04", "prior written consent", "Neither party may assign or transfer this Agreement without the prior written consent of the other party, such consent not to be unreasonably withheld."),
                 F("v07", law, f"This Agreement is governed by the laws of {law}."),
                 F("v12", fee, f"The annual base fee payable by the Customer under this Agreement is ${fee:,}.", "usd"),
                 F("v13", notice, term)]
        nf = []
        risks = []
        if mfn:
            facts.append(F("v06", "most favoured nation", mfn))
            risks.append({"type": "mfn"})
        else:
            nf.append("v06")
        if excl:
            facts.append(F("v05", "exclusive", excl))
            risks.append({"type": "exclusivity"})
        else:
            nf.append("v05")
        if coc:
            facts.append(F("v03", "change of control", coc))
            risks.append({"type": "change_of_control"})
        else:
            nf.append("v03")
        facts = [f for f in facts if f["qid"] in ("v01", "v02", "v03", "v04", "v05", "v06", "v07", "v12", "v13")]
        nf += ["v08"]
        title = f"Customer Supply Agreement - {cn}"
        A(f"02 Legal/Material Contracts/Customers/Customer Agreement - {cn.split()[0]}.pdf", "customer_contract",
          (lambda t=title, r=ref, p=parties, c=clauses, tc=twocol, s=i:
           (contract2 if tc else contract)(t, r, p, "1 July 2024", c, filler=4, seed=s * 3)),
          facts=facts, nf=nf, risks=risks)

    # ------------------------------------------------ suppliers (incl. decoys)
    sup = [
        ("Apex Alloys Ltd", "SUP-102", "30 September 2029", "England and Wales", "one hundred twenty (120) days", 4800000,
         "Apex Alloys Ltd shall be the exclusive supplier of aluminium alloy billet to Meridian and Meridian shall purchase its requirements exclusively from Apex.", "exclusive supplier", "exclusivity", None),
        ("Helix Polymers Inc.", "SUP-115", "31 May 2027", "Ohio", "thirty (30) days", 650000,
         "Nothing in this Agreement grants either party exclusivity and Meridian remains free to purchase polymers from other suppliers.", "exclusivity", None, None),
        ("Tundra Logistics LLC", "SUP-131", "31 January 2028", "Texas", "sixty (60) days", 1240000,
         "Tundra Logistics LLC shall not provide the services to any other manufacturer of the Components within the Territory for the term of this Agreement.", "shall not provide", "exclusivity", None),
        ("Solace Packaging Co.", "SUP-140", "28 February 2027", "California", "forty-five (45) days", 310000,
         "The prices in this Agreement are subject to a most favoured customer clause: Meridian shall receive pricing no less favourable than that offered to any other customer of the supplier.", "most favoured customer", "mfn", None),
    ]
    for i, (sn, ref, exp, law, notice, fee, special, ans, rtype, _x) in enumerate(sup):
        parties = f"{sn} (the Supplier) and {ENTITY} (the Buyer)"
        qid = "v06" if rtype == "mfn" else "v05"
        term = f"Either party may terminate this Agreement on {notice} written notice."
        clauses = [("Supply", ["The Supplier shall supply the materials described in the schedules at the prices set out in them."]),
                   ("Term", [f"This Agreement expires on {exp}.", term]),
                   ("Charges", [f"The annual base fee payable by the Buyer is ${fee:,}."]),
                   ("Dealing with others" if qid == "v05" else "Pricing parity", [special]),
                   ("Assignment", ["Neither party may assign this Agreement without the prior written consent of the other party."]),
                   ("Governing law", [f"This Agreement is governed by the laws of {law}."])]
        facts = [F("v01", sn, f"This Agreement is made between {parties}."), F("v02", exp, f"This Agreement expires on {exp}."),
                 F(qid, ans, special), F("v07", law, f"This Agreement is governed by the laws of {law}."),
                 F("v12", fee, f"The annual base fee payable by the Buyer is ${fee:,}.", "usd"), F("v13", notice, term),
                 F("v04", "prior written consent", "Neither party may assign this Agreement without the prior written consent of the other party.")]
        nf = ["v03", "v09"] + (["v06"] if qid == "v05" else ["v05"])
        risks = [{"type": rtype}] if rtype else []
        decoy = [{"type": "exclusivity", "decoy": True}] if rtype is None else []
        A(f"02 Legal/Material Contracts/Suppliers/Supplier Agreement - {sn.split()[0]}.pdf", "supplier_contract",
          (lambda t=f"Supplier Agreement - {sn}", r=ref, p=parties, c=clauses, s=i: contract(t, r, p, "15 January 2024", c, filler=3, seed=s * 5 + 1)),
          facts=facts, nf=nf, risks=risks, note="decoy: negated exclusivity" if decoy else "")
        if decoy:
            DOCS_SPEC[-1]["decoys"] = decoy
    # ------------------------------------------------ leases
    leases = [("Harbour Point Industrial Estate", "Redwood Properties Ltd", "31 March 2032", "England and Wales", 480000, "six (6) months"),
              ("Unit 14, Lakeside Business Park", "Lakeside Estates LLC", "30 November 2027", "Ohio", 212000, "ninety (90) days"),
              ("Plot 7, Northern Logistics Hub", "Hub Realty Partners", "31 July 2030", "Texas", 365000, "one hundred eighty (180) days")]
    for i, (prem, ll, exp, law, rent, notice) in enumerate(leases):
        parties = f"{ll} (the Landlord) and {ENTITY} (the Tenant)"
        clauses = [("Premises", [f"The Landlord lets the premises known as {prem} to the Tenant."]),
                   ("Term and rent", [f"The lease term expires on {exp}.", f"The annual base rent payable by the Tenant is ${rent:,}, payable quarterly in advance."]),
                   ("Break", [f"The Tenant may end this lease by giving {notice} written notice to the Landlord."]),
                   ("Alienation", ["The Tenant shall not assign or sublet the premises without the prior written consent of the Landlord."]),
                   ("Governing law", [f"This lease is governed by the laws of {law}."])]
        facts = [F("v01", ll, f"This Agreement is made between {parties}."), F("v02", exp, f"The lease term expires on {exp}."),
                 F("v12", rent, f"The annual base rent payable by the Tenant is ${rent:,}, payable quarterly in advance.", "usd"),
                 F("v07", law, f"This lease is governed by the laws of {law}."),
                 F("v13", notice, f"The Tenant may end this lease by giving {notice} written notice to the Landlord.")]
        A(f"02 Legal/Leases/Lease - {prem.split(',')[0]}.pdf", "lease",
          (lambda t=f"Lease of {prem}", r=f"LSE-0{i + 1}", p=parties, c=clauses, s=i: contract(t, r, p, "1 April 2022", c, filler=3, seed=s + 11)),
          facts=facts, nf=["v03", "v08", "v06"] if i == 0 else ["v09"])
    # ------------------------------------------------ 03 Debt
    def credit():
        lay = Layout(footer="CA-2023-01 Credit Agreement | CONFIDENTIAL", cols=1)
        lay.title("Senior Secured Credit Agreement")
        lay.raw("Reference CA-2023-01. Dated 30 June 2023.")
        lay.raw(f"This Agreement is made between Harborview Bank, N.A. (the Lender) and {ENTITY} (the Borrower).")
        lay.h("Definitions")
        lay.p("Change of Control means any person or group acquiring more than fifty percent of the voting equity of the Borrower.")
        lay.p("Total Leverage Ratio means the ratio of Total Debt to Consolidated EBITDA for the most recent four fiscal quarters.")
        fill(lay, 6, 3)
        lay.h("Facilities")
        lay.p("The Lender makes available to the Borrower a term loan facility of $40,000,000 and a revolving facility of $15,000,000.")
        lay.p("The Maturity Date is 30 June 2029.")
        fill(lay, 7, 5)
        lay.h("Financial covenants")
        lay.p("The Borrower shall not permit the Total Leverage Ratio as of the last day of any fiscal quarter to exceed 3.50 to 1.00.")
        lay.p("The Borrower shall not permit the Interest Coverage Ratio as of the last day of any fiscal quarter to be less than 4.00 to 1.00.")
        lay.p("The Borrower shall deliver a compliance certificate with each set of quarterly financial statements.")
        fill(lay, 7, 9)
        lay.h("Events of default")
        lay.p("It shall be an Event of Default if a Change of Control occurs, whereupon the Lender may accelerate all outstanding amounts.")
        lay.p("The Borrower shall not create or permit any lien over its assets other than permitted liens.")
        fill(lay, 8, 13)
        lay.h("Transfers")
        lay.p("The Borrower may not assign or transfer any of its rights or obligations under this Agreement without the prior written consent of the Lender.")
        fill(lay, 6, 17)
        lay.h("Governing law")
        lay.p("This Agreement is governed by the laws of New York.")
        lay.raw("Signed by the duly authorised representatives of the parties.")
        return lay.finish()
    A("03 Debt/Credit Agreement - Harborview Bank.pdf", "credit_agreement", credit,
      facts=[F("v01", "Harborview Bank, N.A.", f"This Agreement is made between Harborview Bank, N.A. (the Lender) and {ENTITY} (the Borrower)."),
             F("v02", "2029-06-30", "The Maturity Date is 30 June 2029."),
             F("v03", "event of default", "It shall be an Event of Default if a Change of Control occurs, whereupon the Lender may accelerate all outstanding amounts."),
             F("v04", "prior written consent", "The Borrower may not assign or transfer any of its rights or obligations under this Agreement without the prior written consent of the Lender."),
             F("v07", "New York", "This Agreement is governed by the laws of New York."),
             F("v08", 3.5, "The Borrower shall not permit the Total Leverage Ratio as of the last day of any fiscal quarter to exceed 3.50 to 1.00."),
             F("v11", 4.0, "The Borrower shall not permit the Interest Coverage Ratio as of the last day of any fiscal quarter to be less than 4.00 to 1.00.")],
      nf=["v06", "v09"],
      risks=[{"type": "covenant", "detail": "leverage 3.5x"}, {"type": "covenant", "detail": "interest coverage 4x"},
             {"type": "change_of_control"}, {"type": "covenant", "detail": "negative covenant liens"}])

    def amend():
        lay = Layout(footer="CA-2023-01 Amendment No. 1 | CONFIDENTIAL")
        lay.title("Amendment No. 1 to the Senior Secured Credit Agreement")
        lay.raw(f"This Amendment is made between Harborview Bank, N.A. (the Lender) and {ENTITY} (the Borrower).")
        lay.h("Amendment")
        lay.p("The Total Leverage Ratio covenant is amended so that the Borrower shall not permit the Total Leverage Ratio to exceed 4.00 to 1.00 for the fiscal quarters ending during 2025.")
        fill(lay, 4, 21)
        lay.h("Governing law")
        lay.p("This Amendment is governed by the laws of New York.")
        return lay.finish()
    A("03 Debt/Amendment No. 1 - Credit Agreement.pdf", "amendment", amend,
      facts=[F("v08", 4.0, "The Total Leverage Ratio covenant is amended so that the Borrower shall not permit the Total Leverage Ratio to exceed 4.00 to 1.00 for the fiscal quarters ending during 2025."),
             F("v07", "New York", "This Amendment is governed by the laws of New York.")],
      nf=["v09", "v06"], risks=[{"type": "covenant", "detail": "leverage 4x"}])

    def secdoc():
        lay = Layout(footer="SEC-2023-02 Security Agreement | CONFIDENTIAL")
        lay.title("Security Agreement")
        lay.raw(f"This Agreement is made between {ENTITY} (the Grantor) and Harborview Bank, N.A. (the Secured Party).")
        lay.h("Grant")
        lay.p("The Grantor grants the Secured Party a first-ranking security interest over its inventory, receivables and equipment.")
        fill(lay, 9, 25)
        lay.h("Governing law")
        lay.p("This Agreement is governed by the laws of New York.")
        return lay.finish()
    A("03 Debt/Security Agreement.pdf", "security_agreement", secdoc,
      facts=[F("v07", "New York", "This Agreement is governed by the laws of New York.")], nf=["v08", "v09"])

    # ------------------------------------------------ 04 Corporate
    def captable():
        lay = Layout(footer="Capitalisation table | CONFIDENTIAL")
        lay.title("Capitalisation Table - fully diluted (as at 31 December 2024)")
        lay.table([["Holder", "Class", "Shares", "Fully diluted %"], ["Founders Trust", "Common", "4,200,000", "42.0%"],
                   ["Altus Growth Partners II", "Series A Preferred", "2,500,000", "25.0%"],
                   ["Management option pool", "Options", "1,300,000", "13.0%"], ["Other holders", "Common", "2,000,000", "20.0%"],
                   ["Total", "", "10,000,000", "100.0%"]], [190, 120, 90, 90])
        return lay.finish()
    A("04 Corporate/Cap Table.pdf", "cap_table", captable,
      facts=[], nf=["v01", "v07", "v09"])
    minutes = [("12 March 2024", "The Board approved the audited financial statements for FY2023 and resolved to renew the credit facilities.",
                "Board Minutes - March 2024"),
               ("18 September 2024", "The Board noted that the Total Leverage Ratio stood at 3.1 times at the end of the second quarter and approved the negotiation of Amendment No. 1.",
                "Board Minutes - September 2024"),
               ("5 February 2025", "The Board authorised management to enter into exclusivity discussions with a prospective acquirer for a period of sixty days.",
                "Board Minutes - February 2025")]
    for i, (d, res, t) in enumerate(minutes):
        def mk(d=d, res=res, t=t, i=i):
            lay = Layout(footer=f"{t} | CONFIDENTIAL")
            lay.title(f"Minutes of a meeting of the Board of Directors of {ENTITY} held on {d}")
            lay.raw("Present: the directors listed in the attendance register. The chair confirmed a quorum.")
            if i == 1:
                lay.cols = 2
            lay.h("Resolutions")
            lay.p(res)
            fill(lay, 4 if i != 1 else 14, 31 + i)
            return lay.finish()
        A(f"04 Corporate/Board Minutes/{t}.pdf", "board_minutes", mk,
          facts=[F("v05", "exclusivity", res)] if i == 2 else [], nf=["v07", "v08"] if i < 2 else ["v10"],
          risks=([{"type": "exclusivity"}] if i == 2 else []))
    def articles():
        lay = Layout(footer="Certificate of incorporation | CONFIDENTIAL")
        lay.title(f"Certificate of Incorporation of {ENTITY}")
        lay.raw("The name of the corporation is " + ENTITY + ". Its registered office is in the State of Delaware.")
        lay.h("Purpose")
        lay.p("The corporation may engage in any lawful act or activity for which corporations may be organised under the General Corporation Law of Delaware.")
        fill(lay, 3, 37)
        return lay.finish()
    A("04 Corporate/Certificate of Incorporation.pdf", "corporate", articles, facts=[], nf=["v09", "v08", "v06"])
    # ------------------------------------------------ 05 HR
    emp = [("Dana Whitmore", "Chief Executive Officer", 420000, "twelve (12) months", True),
           ("Priya Raman", "Chief Financial Officer", 335000, "six (6) months", True),
           ("Tomas Berg", "Vice President, Operations", 245000, "three (3) months", False)]
    for i, (n, role, sal, notice, coc) in enumerate(emp):
        parties = f"{ENTITY} (the Company) and {n} (the Executive)"
        clauses = [("Position", [f"The Executive is employed as {role}."]),
                   ("Remuneration", [f"The annual base salary payable to the Executive is ${sal:,}."]),
                   ("Termination", [f"The Company or the Executive may terminate this Agreement on {notice} written notice."])]
        facts = [F("v01", n, f"This Agreement is made between {parties}."), F("v12", sal, f"The annual base salary payable to the Executive is ${sal:,}.", "usd"),
                 F("v13", notice, f"The Company or the Executive may terminate this Agreement on {notice} written notice.")]
        risks = []
        if coc:
            s = "If a change of control of the Company occurs, the Executive may terminate this Agreement and receive a payment of twelve months base salary."
            clauses.append(("Change of control", [s]))
            facts.append(F("v03", "change of control", s))
            risks.append({"type": "change_of_control"})
        s2 = "During employment and for twelve months afterwards the Executive shall not compete with the Company in the Territory."
        if i == 0:
            clauses.append(("Restrictive covenants", [s2]))
            facts.append(F("v05", "compete", s2))
            risks.append({"type": "exclusivity"})
        clauses.append(("Governing law", ["This Agreement is governed by the laws of Delaware."]))
        facts.append(F("v07", "Delaware", "This Agreement is governed by the laws of Delaware."))
        A(f"05 HR/Employment Agreement - {n}.pdf", "employment", (lambda t=f"Executive Employment Agreement - {n}", r=f"EMP-0{i + 1}", p=parties, c=clauses, s=i:
                                                                  contract(t, r, p, "1 February 2023", c, filler=2, seed=s + 41)),
          facts=facts, nf=[] if coc and i == 0 else ["v06", "v08"], risks=risks)
    # ------------------------------------------------ 06 Tax / 07 Insurance
    def tax():
        lay = Layout(footer="Corporate tax computation FY2023 | CONFIDENTIAL")
        lay.title("Corporate Income Tax Return Summary - FY2023")
        lay.table([["Item", "USD"], ["Taxable income", "4,412,000"], ["Federal income tax", "926,520"], ["State income tax", "198,540"]], [260, 120])
        fill(lay, 2, 51)
        return lay.finish()
    A("06 Tax/Tax Return Summary FY2023.pdf", "tax_return", tax, facts=[], nf=["v07", "v10"])
    def ins():
        lay = Layout(footer="Certificate of insurance | CONFIDENTIAL")
        lay.title("Certificate of Insurance")
        lay.raw(f"Insured: {ENTITY}. Policy period 1 January 2025 to 31 December 2025.")
        lay.table([["Cover", "Limit (USD)"], ["General liability", "5,000,000"], ["Product liability", "10,000,000"]], [220, 120])
        return lay.finish()
    A("07 Insurance/Certificate of Insurance 2025.pdf", "insurance", ins, facts=[], nf=["v07", "v09"])

    # ------------------------------------------------ scanned (image-only) documents
    def scan_cust():
        lay = Layout(footer="Scanned copy | CUST-052", body=11.5)
        lay.title("Customer Supply Agreement - Vantage Rail Services")
        lay.raw(f"This Agreement is made between {ENTITY} (the Supplier) and Vantage Rail Services plc (the Customer).")
        lay.h("Term")
        lay.p("This Agreement expires on 31 August 2028 unless renewed in writing.")
        lay.h("Charges")
        lay.p("The annual base fee payable by the Customer is $1,640,000.")
        lay.h("Change of control")
        lay.p("If Meridian undergoes a change of control, Vantage Rail Services plc may terminate this Agreement by written notice.")
        lay.h("Governing law")
        lay.p("This Agreement is governed by the laws of Scotland.")
        return lay.finish()
    A("02 Legal/Material Contracts/Customers/Customer Agreement - Vantage (scanned).pdf", "customer_contract", scan_cust, scanned=True,
      room="vdr_scanned_arabic",
      facts=[F("v02", "2028-08-31", "This Agreement expires on 31 August 2028 unless renewed in writing."),
             F("v12", 1640000, "The annual base fee payable by the Customer is $1,640,000.", "usd"),
             F("v03", "change of control", "If Meridian undergoes a change of control, Vantage Rail Services plc may terminate this Agreement by written notice."),
             F("v07", "Scotland", "This Agreement is governed by the laws of Scotland.")], nf=["v08", "v06"],
      risks=[{"type": "change_of_control"}])

    def scan_lease():
        lay = Layout(footer="Scanned copy | LSE-04", body=11.5)
        lay.title("Lease Amendment - Riverside Depot")
        lay.raw(f"This Amendment is made between Riverside Estates Ltd (the Landlord) and {ENTITY} (the Tenant).")
        lay.h("Rent")
        lay.p("The annual base rent payable by the Tenant is increased to $298,000 with effect from 1 January 2025.")
        lay.h("Term")
        lay.p("The lease term expires on 31 December 2031.")
        lay.h("Governing law")
        lay.p("This Amendment is governed by the laws of Illinois.")
        return lay.finish()
    A("02 Legal/Leases/Lease Amendment - Riverside (scanned).pdf", "lease", scan_lease, scanned=True, room="vdr_scanned_arabic",
      facts=[F("v12", 298000, "The annual base rent payable by the Tenant is increased to $298,000 with effect from 1 January 2025.", "usd"),
             F("v02", "2031-12-31", "The lease term expires on 31 December 2031."),
             F("v07", "Illinois", "This Amendment is governed by the laws of Illinois.")], nf=["v03", "v10"])

    def scan_min():
        lay = Layout(footer="Scanned copy | Board minutes", body=11.5)
        lay.title(f"Minutes of the Board of Directors of {ENTITY} held on 20 November 2024")
        lay.raw("Present: the directors listed in the attendance register. The chair confirmed a quorum.")
        lay.h("Resolutions")
        lay.p("The Board resolved to appoint Whitfield & Crane LLP as the independent auditor for the year ending 31 December 2025.")
        lay.p("The Board noted that the Interest Coverage Ratio stood at 5.2 times at the end of the third quarter.")
        return lay.finish()
    A("04 Corporate/Board Minutes/Board Minutes - November 2024 (scanned).pdf", "board_minutes", scan_min, scanned=True,
      room="vdr_scanned_arabic",
      facts=[F("v10", "Whitfield & Crane LLP", "The Board resolved to appoint Whitfield & Crane LLP as the independent auditor for the year ending 31 December 2025.")],
      nf=["v07", "v08"])

    # ------------------------------------------------ Arabic (LibreOffice, RTL) - html built in build_arabic()
    ar = _arabic_specs()
    for a in ar:
        A(a["path"], a["kind"], None, facts=a["facts"], nf=a["nf"], risks=a["risks"], language="ar", room="vdr_scanned_arabic",
          note=a.get("note", ""))
        DOCS_SPEC[-1]["html"] = a["html"]


def _cim():
    lay = Layout(footer="CIM excerpt | STRICTLY CONFIDENTIAL", header="Project Meridian - Confidential Information Memorandum")
    lay.title("Financial summary")
    lay.raw("Total revenue for the fiscal year ended 31 December 2024 was USD 52,900,000.")
    lay.raw("Management expects continued growth supported by long-term customer relationships.")
    lay.table([["USD", "FY2023", "FY2024"], ["Total revenue", "44,100,000", "52,900,000"], ["Adjusted EBITDA", "7,300,000", "8,900,000"]], [200, 110, 110])
    return lay.finish()


def _arabic_specs():
    css = ('<style>@page{size:A4;margin:2.2cm}body{font-family:"DejaVu Sans","FreeSerif";font-size:12pt;line-height:1.7}'
           'h1{font-size:17pt}td,th{border:1px solid #444;padding:4px 8px}table{border-collapse:collapse;width:100%}</style>')

    def page(body):
        return f'<html dir="rtl" lang="ar"><head><meta charset="utf-8">{css}</head><body dir="rtl">{body}</body></html>'
    lease = page(
        "<h1>عقد إيجار - مستودع جبل علي</h1>"
        "<p>الرقم المرجعي: LSE-AR-01 &#8207;|&#8207; التاريخ: 1 January 2023</p>"
        "<table><tr><th>البند</th><th>القيمة</th></tr>"
        "<tr><td>الإيجار السنوي</td><td dir='ltr'>AED 1,250,000</td></tr>"
        "<tr><td>تاريخ انتهاء الإيجار</td><td dir='ltr'>31 December 2032</td></tr>"
        "<tr><td>القانون الواجب التطبيق</td><td>قوانين دولة الإمارات العربية المتحدة</td></tr></table>"
        "<p>أبرم هذا العقد بين شركة جبل علي العقارية (المؤجر) وشركة ميريديان للمكونات (المستأجر).</p>"
        "<p>يلتزم المستأجر بدفع الإيجار السنوي البالغ 1,250,000 درهم إماراتي على أقساط ربع سنوية مقدمة.</p>"
        "<p>لا يجوز للمستأجر التنازل عن هذا العقد أو التأجير من الباطن دون موافقة كتابية مسبقة من المؤجر.</p>"
        "<p>يحق لأي من الطرفين إنهاء هذا العقد بإشعار كتابي مدته 90 يوماً.</p>")
    res = page(
        "<h1>قرار مجلس الإدارة</h1>"
        "<p>قرار مجلس إدارة شركة ميريديان للمكونات المنعقد بتاريخ 14 May 2024.</p>"
        "<p>قرر المجلس الموافقة على تعيين شركة ويتفيلد وكرين مدققاً مستقلاً للحسابات للسنة المالية المنتهية في 31 December 2024.</p>"
        "<p>قرر المجلس تفويض الإدارة بالدخول في مفاوضات حصرية مع مستثمر محتمل لمدة 60 يوماً.</p>"
        "<p>بلغت الإيرادات الإجمالية للسنة المالية 2023 مبلغ 44,100,000 دولار أمريكي.</p>")
    sup = page(
        "<h1>عقد توريد - شركة الخليج للمواد</h1>"
        "<p>الرقم المرجعي: SUP-AR-07 &#8207;|&#8207; التاريخ: 1 March 2024</p>"
        "<p>أبرم هذا العقد بين شركة الخليج للمواد (المورد) وشركة ميريديان للمكونات (المشتري).</p>"
        "<p>يكون المورد المورد الحصري لمادة الألمنيوم للمشتري ولا يجوز للمشتري شراء هذه المادة من أي مورد آخر خلال مدة العقد.</p>"
        "<p>الرسوم السنوية الأساسية التي يدفعها المشتري هي 2,300,000 درهم إماراتي.</p>"
        "<p>ينتهي هذا العقد بتاريخ 28 February 2029 ما لم يجدد كتابياً.</p>"
        "<p>يخضع هذا العقد لقوانين دولة الإمارات العربية المتحدة.</p>")
    return [
        {"path": "02 Legal/Leases/Lease Agreement - Jebel Ali (Arabic).pdf", "kind": "lease", "html": lease,
         "facts": [P("v12", 1250000, r"AED 1,250,000", unit="aed"), P("v02", "2032-12-31", r"31 December 2032")],
         "nf": ["v08", "v10", "v06"], "risks": []},
        {"path": "04 Corporate/Board Minutes/Board Resolution - May 2024 (Arabic).pdf", "kind": "board_minutes", "html": res,
         "facts": [P("v09", 44100000, r"44,100,000", unit="usd"), P("v05", "SELF", r"60", n=1)],
         "nf": ["v07", "v08", "v11"], "risks": [{"type": "exclusivity", "lang": "ar"}]},
        {"path": "02 Legal/Material Contracts/Suppliers/Supplier Agreement - Gulf Materials (Arabic).pdf", "kind": "supplier_contract", "html": sup,
         "facts": [P("v12", 2300000, r"2,300,000", unit="aed"), P("v02", "2029-02-28", r"February 2029 28"),
                   P("v05", "SELF", r"المورد الحصري", n=2)],
         "nf": ["v08", "v06", "v10"], "risks": [{"type": "exclusivity", "lang": "ar"}]},
    ]


# ------------------------------------------------------------------------------------------------ build
def sha(b):
    return hashlib.sha256(b).hexdigest()


def soffice_pdf(html, out_pdf):
    with tempfile.TemporaryDirectory(prefix="vdr50_ar_") as td:
        src = Path(td) / "doc.html"
        src.write_text(html, encoding="utf-8")
        r = subprocess.run(["soffice", "--headless", "-env:UserInstallation=file:///tmp/lo_profile_vdr50", "--convert-to", "pdf:writer_web_pdf_Export",
                            "--outdir", td, str(src)], capture_output=True, text=True, timeout=180)
        got = Path(td) / "doc.pdf"
        if not got.exists():
            raise RuntimeError("soffice failed: " + r.stdout[-300:] + r.stderr[-300:])
        out_pdf.write_bytes(got.read_bytes())


def build(force_arabic=False):
    DOCS_SPEC.clear()
    build_registry()
    DOCS.mkdir(parents=True, exist_ok=True)
    docs, gold_rows = [], []
    for spec in DOCS_SPEC:
        path = DOCS / spec["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if spec["language"] == "ar":
            if force_arabic or not path.exists():
                soffice_pdf(spec["html"], path)
            data = path.read_bytes()
        else:
            pages = spec["fn"]()
            data = to_scanned_pdf(pages) if spec["scanned"] else to_vector_pdf(pages)
            path.write_bytes(data)
        spec["sha"], spec["bytes"] = sha(data), len(data)
    # real 10-Ks (referenced)
    tman = json.loads((TENK / "manifest.json").read_text())
    tenk_docs = []
    for f in tman["filings"]:
        p = TENK / f["pdf"]
        rel = f"01 Financials/10-K/{f['ticker']} 10-K.pdf"
        dst = DOCS / rel                       # byte-identical copy of evals/tenk/pdfs (sha256 checked below): the room is self-contained
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        assert sha(dst.read_bytes()) == f["sha256"], f"{f['ticker']}: tenk PDF drifted from its manifest sha256"
        tenk_docs.append({"path": rel, "ref": f"evals/vdr50/docs/{rel}", "kind": "10-K", "source": f"evals/tenk/{f['pdf']}",
                          "language": "en", "scanned": False, "room": "tenk", "sha256": f["sha256"], "bytes": p.stat().st_size, "planted": []})
    entries = tenk_docs
    for s in DOCS_SPEC:
        entries.append({"path": s["path"], "ref": f"evals/vdr50/docs/{s['path']}", "kind": s["kind"], "language": s["language"],
                        "scanned": s["scanned"], "room": s["room"], "sha256": s["sha"], "bytes": s["bytes"],
                        "planted": [{"qid": f["qid"], "answer": f["answer"]} for f in s["facts"]], "note": s["note"]})
    assert len(entries) == 50, f"room has {len(entries)} documents, need exactly 50"
    return entries


def locate_quote(parsed, quote):
    hits = []
    for pg in parsed.pages:
        if docparse.locate(parsed, pg.number, quote):
            hits.append(pg.number)
    return hits


def verify_and_gold(entries):
    """Parse every synthetic doc with pdfdoc (OCR for scanned pages), find each gold quote's page, write gold.jsonl."""
    rows, problems = [], []
    by_path = {s["path"]: s for s in DOCS_SPEC}
    for e in entries:
        s = by_path.get(e["path"])
        if not s:
            continue
        data = (ROOT / e["ref"]).read_bytes()
        parsed = docparse.parse(data, backend="pdfdoc")
        e["pages"] = len(parsed.pages)
        for f in s["facts"]:
            if f.get("pick"):
                rx, n = f["pick"]
                lines = [l.text for pg in parsed.pages for l in pg.lines]
                i = next((k for k, t in enumerate(lines) if re.search(rx, t)), None)
                if i is None:
                    problems.append((e["path"], f["qid"], "pick regex found no line: " + rx))
                    continue
                f["quote"] = " ".join(lines[i:i + n])
                if f["answer"] == "SELF":
                    f["answer"] = f["quote"]
            hits = locate_quote(parsed, f["quote"])
            if not hits:
                problems.append((e["path"], f["qid"], "quote not found by pdfdoc: " + f["quote"][:70]))
                continue
            q = QTEXT[f["qid"]]
            if q["type"] == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f["answer"])):
                f["answer"] = datetime.strptime(f["answer"], "%d %B %Y").strftime("%Y-%m-%d")
            rows.append({"cell_id": f"{e['room']}:{Path(e['path']).stem}:{f['qid']}", "room": s["room"], "doc": e["path"], "doc_sha256": e["sha256"],
                         "question_id": f["qid"], "question": q["text"], "type": q["type"], "expect": "found",
                         "gold_answer": f["answer"], "unit": f.get("unit"), "gold_quote": f["quote"], "gold_page": hits[0],
                         "language": s["language"], "scanned": s["scanned"]})
        for qid in s["nf"]:
            q = QTEXT[qid]
            rows.append({"cell_id": f"{e['room']}:{Path(e['path']).stem}:{qid}", "room": s["room"], "doc": e["path"], "doc_sha256": e["sha256"],
                         "question_id": qid, "question": q["text"], "type": q["type"], "expect": "not_found", "gold_answer": None, "unit": None,
                         "gold_quote": "", "gold_page": None, "language": s["language"], "scanned": s["scanned"]})
    return rows, problems


def risk_gold(entries):
    out = []
    # planted by omission / gap
    out.append({"type": "missing_period", "label": "FY2023", "doc": None, "note": "audited statements FY2021, FY2022, FY2024 present; FY2023 absent"})
    out.append({"type": "missing_period", "label": "2025-05", "doc": None, "note": "management accounts Jan-Apr and Jun 2025 present; May absent"})
    out.append({"type": "missing_document", "label": "ip_schedule", "doc": None, "note": "no IP schedule in the room"})
    out.append({"type": "missing_document", "label": "litigation", "doc": None, "note": "no litigation schedule in the room"})
    for s in DOCS_SPEC:
        for r in s["risks"]:
            out.append({"type": r["type"], "doc": s["path"], "language": s["language"], "scanned": s["scanned"], "role": r.get("role"),
                        "metric": r.get("metric"), "detail": r.get("detail")})
        for d in s.get("decoys", []):
            out.append({"type": d["type"], "doc": s["path"], "decoy": True, "language": s["language"]})
    return out


def main(argv=None):
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--force-arabic", action="store_true")
    a = ap.parse_args(argv)
    entries = build(a.force_arabic)
    rows, problems = verify_and_gold(entries)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps({"version": 1, "documents": len(entries), "questions": VDR_QUESTIONS, "entity": ENTITY,
                                                    "files": entries}, indent=1, ensure_ascii=False) + "\n")
    (OUT / "gold.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (OUT / "risk_gold.json").write_text(json.dumps(risk_gold(entries), indent=1, ensure_ascii=False) + "\n")
    syn = sum(1 for e in entries if e["room"] != "tenk")
    print(f"{len(entries)} documents ({syn} synthetic, {sum(1 for e in entries if e['room']=='tenk')} real 10-K refs); "
          f"{len(rows)} gold cells ({sum(1 for r in rows if r['expect']=='not_found')} not_found)")
    for p in problems:
        print("PROBLEM", *p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
