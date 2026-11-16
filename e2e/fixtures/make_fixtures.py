#!/usr/bin/env python3
"""Generate the e2e fixtures (synthetic, deterministic): VDR zip, 100-file batch, table PDF, pptx, csv, eml.

usage: make_fixtures.py OUTDIR
Arabic note: om.pdfwrite is WinAnsi-only, so the two Arabic-named documents carry Arabic file names and
transliterated Arabic-language body text; the app's own Arabic extraction is judged by the S5 gates, not here.
"""
import base64
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from om.pdfwrite import PDFWriter  # noqa: E402
from om.pptx import Deck  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
many = out / "many"
many.mkdir(exist_ok=True)

TOPICS = ["Share Purchase Agreement", "Financial Statements FY2024", "Customer Contract", "Lease Agreement", "Tax Memo",
          "Board Minutes", "Employment Agreement", "Loan Facility", "Insurance Schedule", "IP Licence"]


def pdf(title, lines, pages=2):
    w = PDFWriter()
    for p in range(pages):
        w.page()
        w.text(72, 720, title, 16, "Helvetica-Bold")
        y = 690
        for ln in lines:
            w.text(72, y, ln, 10)
            y -= 16
        w.text(72, 60, f"Page {p + 1}", 8)
    return w.to_bytes()


def body(i, topic):
    return [f"Document {i:03d}: {topic} for Project Nile.",
            "Revenue for FY2024 was EGP 4,120 million; Adjusted EBITDA was EGP 612 million.",
            "Net debt at 31 December 2024 was EGP 1,035 million.",
            "Change of control requires lender consent under clause 14.2.",
            "Governing law: Arab Republic of Egypt. Term: five years from the effective date."]


with zipfile.ZipFile(out / "vdr.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for i in range(1, 51):
        t = TOPICS[i % len(TOPICS)]
        z.writestr(f"Legal/{i:03d}-{t.replace(' ', '-')}.pdf", pdf(f"{t} #{i}", body(i, t)))
    for i in (1, 2):
        z.writestr(f"Arabic/تقرير-{i}.pdf",
                   pdf(f"Taqrir sanawi {i} (Arabic-language annual report)",
                       ["Al-iradat: 4,120 million jineh misri.", "Sareh al-arbah: 612 million."]))

for i in range(1, 101):
    (many / f"batch-{i:03d}.pdf").write_bytes(pdf(f"Batch document {i}", body(i, "Batch"), pages=1))
(many / "corrupt.pdf").write_bytes(b"%PDF-1.4\nthis is not really a pdf \x00\x01\x02")

w = PDFWriter()
w.page()
w.text(72, 720, "Segment revenue table", 14, "Helvetica-Bold")
y = 690
for r in (("Segment", "FY2023", "FY2024"), ("Cables", "2,310", "2,780"), ("Transformers", "1,020", "1,340")):
    for j, c in enumerate(r):
        w.text(72 + j * 150, y, c, 10)
    y -= 18
(out / "table.pdf").write_bytes(w.to_bytes())

d = Deck("Firm template")
d.cover("Firm template", "Sample master")
d.content("Section title", "Subtitle", source="Source: company filings")
(out / "template.pptx").write_bytes(d.save())
d = Deck("Sample deck")
d.cover("Sample IC deck", "House style")
for k in range(3):
    d.content(f"Sample slide {k + 1}", "House style", source="Source: sample")
(out / "sample-deck.pptx").write_bytes(d.save())
(out / "peers.csv").write_text("ticker,name,ev_ebitda\nELSWEDY,ElSewedy Electric,6.1\nPRYSMY,Prysmian,8.4\nNEXANS,Nexans,6.9\n")

att = base64.encodebytes((out / "table.pdf").read_bytes()).decode()
eml = (
    "From: owner@meridian.example\nTo: agent@meridian.example\nSubject: Buyer material for Project Atlas\n"
    "Message-ID: <buyer1@gate.example>\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=BOUND\n\n"
    "--BOUND\nContent-Type: text/plain; charset=utf-8\n\nPlease save the attached material to the project folder for Apple.\n\n"
    "--BOUND\nContent-Type: application/pdf; name=\"buyer-table.pdf\"\nContent-Transfer-Encoding: base64\n"
    "Content-Disposition: attachment; filename=\"buyer-table.pdf\"\n\n" + att + "\n--BOUND--\n"
)
(out / "buyer-material.eml").write_text(eml)
print("fixtures written to", out)
