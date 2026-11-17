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


def mk(name, *pages, doc_id=None):
    return {"doc_id": doc_id or abs(hash(name)) % 10**8, "name": name, "pages": list(pages)}


def scan(*docs, **kw):
    return vr.scan_documents([dict(d, doc_id=i) for i, d in enumerate(docs, 1)], locate=lambda *a: None, **kw)


def titles(res, t):
    return sorted(f["title"] for f in by_type(res, t))


class PeriodPrecisionTests(unittest.TestCase):
    def test_narrative_years_are_not_coverage(self):
        k = mk("Acme 10-K.pdf", "FORM 10-K\nFor the fiscal year ended December 31, 2024\nAcme Corporation\n(Exact name of registrant)",
               "We were founded in 1935 and opened our first plant in FY1962. Our 2008 restructuring and the FY2011 recall are described below. "
               "In March 2023 and in June 2020 we refinanced. Revenue for fiscal 2019 was lower than in fiscal 2016.")
        res = scan(k, mk("Audited Financial Statements FY2024.pdf", "Acme Corporation\nAudited financial statements for the year ended 31 December 2024"))
        self.assertEqual(titles(res, "missing_period"), [])

    def test_years_outside_sane_window_ignored(self):
        self.assertIsNone(vr.period_of("Annual accounts FY1935"))
        self.assertIsNone(vr.period_of("Accounts FY2099"))
        self.assertEqual(vr.period_of("Accounts FY2023"), ("annual", 2023))

    def test_unrelated_filers_are_not_one_series(self):
        docs = [mk(f"{t} 10-K.pdf", f"FORM 10-K\nFor the fiscal year ended December 31, {y}\n{n}\n(Exact name of registrant as specified in its charter)")
                for t, y, n in (("AAA", 2018, "Alpha Dynamics, Inc."), ("BBB", 2022, "Bravo Foods Corporation"), ("CCC", 2025, "Charlie Motors Inc."))]
        self.assertEqual(titles(scan(*docs), "missing_period"), [])

    def test_gap_inside_one_companys_series_is_found(self):
        docs = [mk(f"Zenith Corp 10-K FY{y}.pdf", f"FORM 10-K\nFor the fiscal year ended December 31, {y}\nZenith Corporation") for y in (2021, 2023)]
        docs += [mk("Other 10-K FY2019.pdf", "FORM 10-K\nFor the fiscal year ended December 31, 2019\nOmega Industries Inc.")]
        self.assertEqual(titles(scan(*docs), "missing_period"), ["Missing FY2022"])

    def test_monthly_series_gap_and_no_body_months(self):
        docs = [mk(f"Management Accounts {m} 2025.pdf", f"Nimbus Holdings, Inc. - management reporting pack\nManagement Accounts - {m} 2025",
                   "Signed on 14 March 2019 and refinanced in September 2021.") for m in ("January", "February", "April")]
        self.assertEqual(titles(scan(*docs), "missing_period"), ["Missing 2025-03"])


STMT = ("{co}\n{co} - Audited financial statements\n{unit}\n{hdr}\n{row}\n")


class ConflictPrecisionTests(unittest.TestCase):
    def fs(self, co="Acme Holdings, Inc.", unit="(USD in thousands)", hdr="FY2024 FY2023", row="Total revenue 48,213 44,100", name="Audited FS FY2024.pdf"):
        return mk(name, STMT.format(co=co, unit=unit, hdr=hdr, row=row))

    def test_units_normalise_across_formats(self):
        agree = [self.fs(), mk("CIM.pdf", "Project Acme - Information Memorandum", "Total revenue for the fiscal year ended 31 December 2024 was $48.2m.")]
        self.assertEqual(by_type(scan(*agree), "conflicting_figure"), [])
        for fig in ("$48.2 million", "USD 48,213,000", "$0.0482 billion"):
            r = scan(self.fs(), mk("CIM.pdf", "Project Acme - Information Memorandum", f"Total revenue for FY2024 was {fig}."))
            self.assertEqual(by_type(r, "conflicting_figure"), [], fig)

    def test_cim_vs_audited_conflict_across_formats(self):
        r = scan(self.fs(), mk("CIM.pdf", "Project Acme - Information Memorandum", "Total revenue for the fiscal year ended 31 December 2024 was $52.9m."))
        c = by_type(r, "conflicting_figure")
        self.assertEqual(len(c), 1)
        involved = {c[0]["doc_name"]} | {x["doc_name"] for x in c[0]["related"]}
        self.assertEqual(involved, {"Audited FS FY2024.pdf", "CIM.pdf"})
        self.assertEqual(c[0]["period"], "FY2024")
        self.assertIn("52.9m", c[0]["quote"] + c[0]["related"][0]["quote"])

    def test_fx_effect_is_not_revenue(self):
        a = mk("Acme annual report.pdf", "Acme Corporation Annual Report", "Revenue for FY2025 was $164.7 billion. A stronger dollar reduced revenue by $307 million in fiscal 2025. "
               "The currency effect on revenue for FY2025 was $307 million. Revenue in the Americas segment for FY2025 was $79 million.")
        b = mk("Acme investor deck.pdf", "Acme Corporation investor presentation", "Revenue for FY2025 was $164.7 billion.")
        self.assertEqual(by_type(scan(a, b), "conflicting_figure"), [])

    def test_different_companies_never_paired(self):
        a = mk("A 10-K.pdf", "Alpha Dynamics, Inc.\n(USD in millions)\nFY2025 FY2024\nTotal revenue 900 850")
        b = mk("B 10-K.pdf", "Bravo Foods Corporation\n(USD in millions)\nFY2025 FY2024\nTotal revenue 120 110")
        self.assertEqual(by_type(scan(a, b), "conflicting_figure"), [])

    def test_percent_mis_parse_rejected(self):
        a = mk("Acme 10-K.pdf", "Acme Corporation\n(USD in millions)\nFY2025 FY2024 FY2023\nGross margin 225,465 193,893 180,683")
        b = mk("Acme deck.pdf", "Acme Corporation investor presentation\nFY2025 FY2024\nGross margin 22546500% 41.2%")
        self.assertEqual(vr._doc_facts(a), [])
        self.assertEqual([f for f in vr._doc_facts(b) if f.value > 100], [])
        self.assertEqual(by_type(scan(a, b), "conflicting_figure"), [])

    def test_real_margin_conflict_still_found(self):
        a = mk("Acme FS.pdf", "Acme Corporation\nFY2024 FY2023\nGross margin 41.2% 40.1%")
        b = mk("Acme deck.pdf", "Acme Corporation investor presentation\nFY2024 FY2023\nGross margin 43.9% 40.1%")
        c = by_type(scan(a, b), "conflicting_figure")
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["period"], "FY2024")

    def test_budget_and_projection_columns_skipped(self):
        a = mk("Acme budget.pdf", "Acme Corporation\n(USD in thousands)\nFY2025 budget FY2025 forecast\nTotal revenue 51,400 50,900")
        self.assertEqual(vr._doc_facts(a), [])


class ClauseRecallTests(unittest.TestCase):
    def kinds(self, text, typ="exclusivity"):
        res = scan(mk("Contract.pdf", text))
        return [f for f in by_type(res, typ)]

    def test_prohibition_exclusivity(self):
        for t in ("The Distributor shall not purchase the Products from any other supplier during the Term.",
                  "Zeta will not appoint any other distributor for the Products in the Territory.",
                  "4.1 Vendor shall not provide the services to any competing\nmanufacturer within the Territory during the term.",
                  "The Company shall not sell to any competitor of the Customer in the Field.",
                  "The Board authorised management to enter into exclusivity negotiations with a bidder for sixty days.",
                  "Northwind is the exclusive customer for the Product Line."):
            self.assertEqual(len(self.kinds(t)), 1, t)

    def test_prohibition_decoys(self):
        for t in ("Nothing in this Agreement prevents the Buyer from purchasing the Products from any other supplier.",
                  "The Supplier shall not be required to supply any other customer on these terms.",
                  "The Buyer shall not disclose Confidential Information to any third party.",
                  "Meridian remains free to purchase polymers from other suppliers and this Agreement is non-exclusive.",
                  "All amounts stated are exclusive of value added tax.",
                  "Neither party shall assign this Agreement to any other person without consent."):
            self.assertEqual(self.kinds(t), [], t)

    def test_wrapped_line_quote_is_exact_substring(self):
        page = "4. Dealing\n4.1 Vendor shall not provide the services to any other\nmanufacturer within the Territory.\n4.2 Fees are due monthly."
        f = by_type(scan(mk("C.pdf", page)), "exclusivity")
        self.assertEqual(len(f), 1)
        self.assertIn(f[0]["quote"], page)
        self.assertTrue(f[0]["quote"].startswith("4.1") and f[0]["quote"].endswith("Territory."))

    def test_arabic_clauses(self):
        pos = {"exclusivity": ["يلتزم المشتري بشراء المنتجات بشكل حصري من المورد ولا يجوز له الشراء من أي مورد آخر خلال مدة العقد.",
                               "قرر المجلس تفويض الإدارة بالدخول في مفاوضات حصرية مع مستثمر محتمل لمدة ستين يوما.",
                               "لا يجوز للمورد توريد المنتجات إلى أي موزع آخر داخل المنطقة."],
               "change_of_control": ["في حال تغيير السيطرة على الشركة يحق للطرف الآخر إنهاء هذا العقد بإشعار كتابي."],
               "mfn": ["يحصل العميل على شروط الدولة الأكثر رعاية طوال مدة العقد."],
               "covenant": ["يجب على المقترض الحفاظ على نسبة الدين إلى الأرباح لا تزيد عن 3.5x في نهاية كل ربع."]}
        for typ, sents in pos.items():
            for t in sents:
                self.assertEqual(len(self.kinds(t, typ)), 1, (typ, t))
                self.assertIn(self.kinds(t, typ)[0]["quote"], t)

    def test_arabic_decoys_and_negation(self):
        for typ, t in (("exclusivity", "هذا العقد غير حصري ويجوز للمشتري الشراء من أي مورد آخر."),
                       ("exclusivity", "لا يوجد في هذا العقد ما يمنح أي طرف حقا حصريا."),
                       ("exclusivity", "تشمل الخدمات الاستشارات والتدريب على سبيل المثال لا الحصر."),
                       ("change_of_control", "لا يوجد في هذا العقد أي تغيير في السيطرة يستوجب موافقة الطرف الآخر."),
                       ("change_of_control", "تحدد هذه المادة مدة العقد وطريقة السداد بالدولار الأمريكي."),
                       ("mfn", "تلتزم الشركة بدفع الأجور في موعدها المحدد.")):
            self.assertEqual(self.kinds(t, typ), [], (typ, t))


if __name__ == "__main__":
    unittest.main()
