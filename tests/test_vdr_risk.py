"""VDR gap and risk detector (S5.3): offline, synthetic PDFs, deterministic."""
import json
import re
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import vdr_risk as vr  # noqa: E402
from om.pdfwrite import PDFWriter  # noqa: E402
from om.rooms import Rooms  # noqa: E402
from om.search import Index  # noqa: E402

HAS_PDF = bool(shutil.which("pdftotext"))

CREDIT = [
    ["CREDIT AGREEMENT dated as of 1 March 2024 among Falcon Holdings, as Borrower, and the Lender.",
     "Section 7.1 Financial Covenants. The Borrower shall not permit the Total Net Leverage Ratio to exceed 3.50 to 1.00 as of the last day of any fiscal quarter.",
     "Section 7.2 Negative Covenants. The Borrower shall not incur any additional Indebtedness or create any Liens on its assets."],
    ["Section 8.1 Events of Default. A Change of Control shall constitute an Event of Default and the Lender may accelerate all amounts outstanding.",
     "\"Change of Control\" means any person acquiring more than 50% of the voting shares of the Borrower."],
]
CUSTOMER = [
    ["CUSTOMER AGREEMENT between Falcon Holdings and Acme Corp.",
     "Pricing. Falcon represents that prices charged to Acme are no less favorable than prices charged to any other customer, with a refund of any difference.",
     "Territory. Falcon shall be the exclusive supplier of the Products to Acme in the Territory."],
]
SUPPLIER = [
    ["SUPPLIER AGREEMENT between Widgets Ltd and Falcon Holdings.",
     "Nothing herein shall be construed as creating an exclusive relationship between the parties.",
     "Widgets grants Falcon a non-exclusive licence to use the Widgets trademarks.",
     "There is no change of control provision in this Agreement.",
     "\"Change of Control\" means any transfer of more than 50% of the shares of a party."],
]
FS21 = [["FY2021 AUDITED FINANCIAL STATEMENTS. Report of the independent auditor.", "Revenue for FY2021 was $80.0 million."]]
FS23 = [["FY2023 AUDITED FINANCIAL STATEMENTS. Report of the independent auditor.", "Revenue for FY2023 was $120.0 million."]]
CIM = [["CONFIDENTIAL INFORMATION MEMORANDUM.", "Revenue for FY2023 was $125.0 million."]]
MGMT = {q: [[f"MANAGEMENT ACCOUNTS Q{q} 2024.", "Unaudited management accounts for the quarter."]] for q in (1, 2, 4)}

DOCS = {"Credit Agreement.pdf": CREDIT, "Customer Agreement - Acme.pdf": CUSTOMER, "Supplier Agreement - Widgets.pdf": SUPPLIER,
        "FY2021 Audited Financial Statements.pdf": FS21, "FY2023 Audited Financial Statements.pdf": FS23, "CIM.pdf": CIM,
        **{f"Q{q} 2024 Management Accounts.pdf": MGMT[q] for q in MGMT}}


def pdf_bytes(pages):
    w = PDFWriter()
    for lines in pages:
        w.page()
        y = 740
        for ln in lines:
            for piece in textwrap.wrap(ln, 88):
                w.text(50, y, piece, size=9)
                y -= 13
            y -= 6
    return w.to_bytes()


def page_text(lines):
    return " ".join(" ".join(textwrap.wrap(ln, 88)) for ln in lines)


def docs_list(with_pdf=True):
    out = []
    for i, (name, pages) in enumerate(DOCS.items(), 1):
        d = {"doc_id": i, "name": name, "pages": [page_text(p) for p in pages]}
        if with_pdf:
            d["pdf"] = pdf_bytes(pages)
        out.append(d)
    return out


def by_type(res, t):
    return [f for f in res["findings"] if f["type"] == t]


class DetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = docs_list()
        cls.res = vr.scan_documents(cls.docs)
        cls.names = {d["doc_id"]: d["name"] for d in cls.docs}
        cls.pages = {(d["doc_id"], i + 1): t for d in cls.docs for i, t in enumerate(d["pages"])}

    def of(self, typ, name):
        return [f for f in by_type(self.res, typ) if f["doc_name"] == name]

    def test_covenant_with_threshold(self):
        f = self.of("covenant", "Credit Agreement.pdf")
        maint = [x for x in f if x["severity"] == "high"]
        self.assertEqual(len(maint), 1)
        self.assertEqual(maint[0]["page"], 1)
        self.assertIn("3.5x", maint[0]["detail"])
        neg = [x for x in f if x["severity"] == "medium"]
        self.assertEqual(len(neg), 1)
        self.assertIn("Liens", neg[0]["quote"])

    def test_change_of_control_operative_only(self):
        f = self.of("change_of_control", "Credit Agreement.pdf")
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["severity"], f[0]["page"]), ("high", 2))
        self.assertTrue(f[0]["quote"].startswith("A Change of Control"))     # the definition sentence is not a finding

    def test_mfn_and_exclusivity(self):
        m = self.of("mfn", "Customer Agreement - Acme.pdf")
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["severity"], "high")                   # refund language
        e = self.of("exclusivity", "Customer Agreement - Acme.pdf")
        self.assertEqual(len(e), 1)
        self.assertEqual(e[0]["severity"], "high")
        self.assertIn("exclusive supplier", e[0]["quote"])

    def test_decoy_contract_has_zero_clause_findings(self):
        clause = [f for f in self.res["findings"] if f["doc_name"] == "Supplier Agreement - Widgets.pdf"
                  and f["type"] in ("change_of_control", "covenant", "mfn", "exclusivity")]
        self.assertEqual(clause, [])

    def test_missing_period_annual_and_quarter(self):
        mp = {f["title"]: f for f in by_type(self.res, "missing_period")}
        self.assertEqual(set(mp), {"Missing FY2022", "Missing Q3 2024"})
        self.assertEqual(mp["Missing FY2022"]["severity"], "high")
        self.assertEqual(mp["Missing Q3 2024"]["severity"], "medium")
        self.assertEqual({r["doc_name"] for r in mp["Missing FY2022"]["related"]},
                         {"FY2021 Audited Financial Statements.pdf", "FY2023 Audited Financial Statements.pdf"})

    def test_expected_periods_and_months(self):
        r = vr.scan_documents(self.docs, expected_periods=["FY2024", "Q1 2024", "FY2023"])
        titles = {f["title"] for f in by_type(r, "missing_period")}
        self.assertIn("Missing FY2024", titles)
        self.assertNotIn("Missing FY2023", titles)
        self.assertNotIn("Missing Q1 2024", titles)
        months = [{"doc_id": i, "name": f"Management Accounts {m}.txt", "pages": ["Management accounts."]}
                  for i, m in enumerate(["January 2024", "2024-02", "May 2024"], 1)]
        t = {f["title"] for f in by_type(vr.scan_documents(months), "missing_period")}
        self.assertEqual(t, {"Missing 2024-03", "Missing 2024-04"})

    def test_checklist(self):
        miss = {f["title"]: f["severity"] for f in by_type(self.res, "missing_document")}
        self.assertEqual(miss["Missing: Capitalisation table"], "high")
        self.assertNotIn("Missing: Debt / credit agreements", miss)
        self.assertNotIn("Missing: Audited financial statements", miss)
        self.assertNotIn("Missing: Management accounts", miss)
        self.assertEqual(miss["Missing: Leases"], "medium")

    def test_conflicting_revenue(self):
        c = by_type(self.res, "conflicting_figure")
        self.assertEqual(len(c), 1)
        f = c[0]
        self.assertEqual(f["severity"], "high")
        both = {f["doc_name"]} | {r["doc_name"] for r in f["related"]}
        self.assertEqual(both, {"FY2023 Audited Financial Statements.pdf", "CIM.pdf"})
        self.assertIn("FY2023", f["title"])

    def test_quotes_and_locations(self):
        names = {v: k for k, v in self.names.items()}
        for f in self.res["findings"]:
            if f["doc_id"] is None:
                self.assertEqual((f["page"], f["quote"], f["bbox_norm"]), (None, "", None))
                continue
            self.assertIn(f["quote"], self.pages[(f["doc_id"], f["page"])], f["title"])
            for r in f["related"]:
                self.assertIn(r["quote"], self.pages[(r["doc_id"], r["page"])])
            self.assertFalse(f.get("locate_failed"), f["title"])
            b = f["bbox_norm"]
            self.assertEqual(len(b), 4)
            self.assertTrue(all(0 <= v <= 1 for v in b) and b[0] < b[2] and b[1] < b[3])
            self.assertRegex(f["sha256_span_hash"], r"^[0-9a-f]{64}$")
            for r in f["related"]:
                self.assertRegex(r["sha256_span_hash"], r"^[0-9a-f]{64}$")
        self.assertTrue(names)

    def test_custom_locate_and_failure(self):
        calls = []

        def loc(doc, page, quote):
            calls.append((doc["doc_id"], page))
            return {"bbox_norm": (0.1, 0.1, 0.9, 0.2), "sha256_span_hash": "a" * 64}
        r = vr.scan_documents(self.docs, locate=loc)
        self.assertTrue(calls)
        self.assertTrue(all(f["bbox_norm"] == (0.1, 0.1, 0.9, 0.2) for f in r["findings"] if f["doc_id"] is not None))
        r = vr.scan_documents(self.docs, locate=lambda d, p, q: None)
        cl = [f for f in r["findings"] if f["doc_id"] is not None]
        self.assertTrue(cl and all(f["bbox_norm"] is None and f["sha256_span_hash"] is None and f["locate_failed"] for f in cl))
        r = vr.scan_documents(self.docs, locate=lambda d, p, q: {"bbox_norm": (0, 0, 2, 1), "sha256_span_hash": "zz"})
        self.assertTrue(all(f["bbox_norm"] is None for f in r["findings"]))      # invalid boxes are rejected, never passed through

    def test_text_only_docs_have_no_boxes(self):
        r = vr.scan_documents(docs_list(with_pdf=False))
        cl = [f for f in r["findings"] if f["doc_id"] is not None]
        self.assertTrue(cl and all(f["bbox_norm"] is None and not f.get("locate_failed") for f in cl))

    def test_deterministic(self):
        again = vr.scan_documents(docs_list())
        self.assertEqual(json.dumps(again["findings"], sort_keys=True, default=str), json.dumps(self.res["findings"], sort_keys=True, default=str))
        ids = [f["id"] for f in self.res["findings"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", i) for i in ids))

    def test_summary_and_dedupe(self):
        s = self.res["summary"]
        self.assertEqual(s["documents"], len(self.docs))
        self.assertEqual(sum(s["by_type"].values()), len(self.res["findings"]))
        dup = [{"doc_id": 1, "name": "Loan.pdf", "pages": ["The Borrower shall not permit the Leverage Ratio to exceed 4.00 to 1.00. " * 3]}]
        self.assertEqual(len(by_type(vr.scan_documents(dup), "covenant")), 1)

    def test_more_decoys(self):
        txt = ("This Agreement does not contain a change of control clause. Supplier does not compete with Customer. "
               "The Company reports its leverage ratio quarterly. Either party may assign this Agreement to an affiliate. "
               "Customer may terminate for convenience on 30 days notice.")
        r = vr.scan_documents([{"doc_id": 1, "name": "Misc.txt", "pages": [txt]}])
        self.assertEqual([f for f in r["findings"] if f["doc_id"] == 1], [])


@unittest.skipUnless(HAS_PDF, "pdftotext not installed")
class RoomTests(unittest.TestCase):
    def test_scan_room(self):
        with tempfile.TemporaryDirectory() as td:
            idx = Index(Path(td) / "s.db")
            rooms = Rooms(idx, Path(td))
            rid = rooms.create("Falcon")
            for name, pages in DOCS.items():
                rooms.add_file(rid, name, pdf_bytes(pages))
            res = vr.scan_room(idx, rooms, rid)
            again = vr.scan_room(idx, rooms, rid)
            self.assertEqual(json.dumps(res["findings"], default=str), json.dumps(again["findings"], default=str))
            self.assertEqual({f["title"] for f in by_type(res, "missing_period")}, {"Missing FY2022", "Missing Q3 2024"})
            self.assertEqual(len(by_type(res, "conflicting_figure")), 1)
            self.assertEqual(len([f for f in by_type(res, "covenant") if f["severity"] == "high"]), 1)
            self.assertEqual(len(by_type(res, "change_of_control")), 1)
            self.assertEqual([f for f in res["findings"] if f["doc_name"] == "Supplier Agreement - Widgets.pdf"
                              and f["type"] in ("change_of_control", "covenant", "mfn", "exclusivity")], [])
            self.assertIn("Missing: Capitalisation table", {f["title"] for f in by_type(res, "missing_document")})
            texts = {}
            for d in rooms.documents(rid):
                for c in idx.db.execute("SELECT text, section FROM chunks WHERE doc_id=?", (d["doc_id"],)):
                    texts.setdefault((d["doc_id"], int(re.search(r"p\.(\d+)", c["section"]).group(1))), []).append(c["text"])
            for f in res["findings"]:
                if f["doc_id"] is None:
                    continue
                self.assertTrue(any(f["quote"] in t for t in texts[(f["doc_id"], f["page"])]), f["title"])
                self.assertFalse(f.get("locate_failed"), f["title"])
                self.assertEqual(len(f["bbox_norm"]), 4)
                self.assertRegex(f["sha256_span_hash"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
