"""S5.F4: the extractive engine answers English diligence questions from Arabic contracts (lexicons, Arabic-Indic digits,
Arabic months), keeps its abstention rules and always quotes exact, locatable page text."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from om import docparse, grid  # noqa: E402
from om.grid import ExtractiveEngine  # noqa: E402

HAVE_SOFFICE = bool(shutil.which("soffice"))
Q = {
    "parties": {"id": "q1", "text": "Who are the parties to the agreement?", "type": "text"},
    "expiry": {"id": "q2", "text": "What is the expiry date or term end date of the agreement?", "type": "date"},
    "coc": {"id": "q3", "text": "What happens upon a change of control?", "type": "text"},
    "assign": {"id": "q4", "text": "Is assignment of the agreement restricted without consent?", "type": "text"},
    "excl": {"id": "q5", "text": "Is there an exclusivity or non-compete obligation?", "type": "text"},
    "mfn": {"id": "q6", "text": "Is there a most favoured nation (MFN) pricing clause?", "type": "text"},
    "law": {"id": "q7", "text": "What is the governing law?", "type": "text"},
    "rev": {"id": "q9", "text": "What was total revenue for the fiscal year?", "type": "currency"},
    "fee": {"id": "q12", "text": "What is the annual base rent or annual fee payable?", "type": "currency"},
    "notice": {"id": "q13", "text": "What is the notice period for termination?", "type": "text"},
    "eff": {"id": "q14", "text": "What is the effective date of the agreement?", "type": "date"},
}

LEASE = """<p>عقد إيجار مستودع</p>
<p>أبرم هذا العقد بين شركة النخيل العقارية (المؤجر) وشركة الواحة للتجارة (المستأجر).</p>
<p>يدفع المستأجر الإيجار السنوي الأساسي وقدره 480,000 ريال سعودي على أقساط ربع سنوية.</p>
<p>ينتهي هذا العقد في 31 ديسمبر 2030 ما لم يجدد كتابيا.</p>
<p>يخضع هذا العقد لقوانين المملكة العربية السعودية.</p>
<p>لا يجوز للمستأجر التنازل عن هذا العقد دون موافقة كتابية مسبقة من المؤجر.</p>
<p>يحق لأي من الطرفين إنهاء هذا العقد بإشعار كتابي مدته 90 يوما.</p>"""

DIST = """<p>اتفاقية توزيع</p>
<p>يمنح المنتج الموزع حق التوزيع الحصري لمنتجاته في دولة الكويت طوال مدة الاتفاقية.</p>
<p>يلتزم المنتج بأن تكون أسعار الموزع أفضل الشروط الممنوحة لأي عميل آخر.</p>
<p>تبلغ الرسوم السنوية الثابتة 1.2 مليون دينار كويتي تدفع مقدما.</p>
<p>تنتهي هذه الاتفاقية بتاريخ 15/06/2031.</p>"""

LOAN = """<p>اتفاقية قرض</p>
<p>يعتبر أي تغيير في السيطرة على المقترض حالة إخلال تتيح للمقرض تسريع السداد وإنهاء التسهيل.</p>
<p>بلغت الإيرادات الإجمالية للمقترض للسنة المالية 2023 مبلغ 44.1 مليون دولار أمريكي.</p>
<p>تاريخ سريان هذه الاتفاقية هو 1 مارس 2024.</p>"""

DECOY = """<p>اتفاقية خدمات</p>
<p>هذا العقد غير حصري ويحق للطرف الثاني التعاقد مع أي جهة أخرى.</p>
<p>يخضع هذا العقد لقوانين دولة قطر.</p>"""


def render(body: str, td: str, name: str) -> bytes:
    html = os.path.join(td, name + ".html")
    with open(html, "w", encoding="utf-8") as fh:
        fh.write('<html dir="rtl"><head><meta charset="utf-8"><style>body{font-family:"DejaVu Sans";font-size:12pt}</style></head>'
                 f'<body dir="rtl">{body}</body></html>')
    subprocess.run(["soffice", "--headless", f"-env:UserInstallation=file://{td}/profile", "--convert-to", "pdf", "--outdir", td, html],
                   capture_output=True, timeout=120)
    return Path(td, name + ".pdf").read_bytes()


class TestArabicHelpers(unittest.TestCase):
    def test_digits_and_separators_normalised(self):
        self.assertEqual(grid._afold("٤٨٠٬٠٠٠٫٥"), "480,000.5")
        self.assertEqual(grid._afold("۱۲۳"), "123")

    def test_money_parsing(self):
        m = grid._money_ar(grid._afold("الإيجار ٤٨٠٬٠٠٠ ريال سعودي سنويا"))
        self.assertEqual((m[0][1], m[0][2]), (480000.0, "SAR"))
        m = grid._money_ar(grid._afold("مبلغ 1.2 مليون دينار كويتي"))
        self.assertEqual((m[0][1], m[0][2]), (1200000.0, "KWD"))
        m = grid._money_ar(grid._afold("القيمة AED 1,250,000"))
        self.assertEqual((m[0][1], m[0][2]), (1250000.0, "AED"))
        m = grid._money_ar(grid._afold("بقيمة 2,300,000 درهم إماراتي"))
        self.assertEqual((m[0][1], m[0][2]), (2300000.0, "AED"))
        self.assertEqual(grid._money_ar(grid._afold("في سنة 2023 وعدد 90 يوما")), [])   # no currency, no amount

    def test_dates(self):
        iso = lambda s: [d[2] for d in grid._dates_ar(grid._afold(s))]
        self.assertEqual(iso("في ٣١ ديسمبر ٢٠٣٠"), ["2030-12-31"])
        self.assertEqual(iso("بتاريخ 5 كانون الثاني 2025"), ["2025-01-05"])
        self.assertEqual(iso("بتاريخ 5 تشرين الثاني 2025"), ["2025-11-05"])
        self.assertEqual(iso("15/06/2031"), ["2031-06-15"])
        self.assertEqual(iso("31 February 2030"), [])                                  # impossible date
        self.assertEqual(iso("ينتهي بتاريخ February 2029 28 ما لم"), ["2029-02-28"])   # bidi-scrambled English date
        self.assertEqual(iso("31 December 2032"), ["2032-12-31"])


@unittest.skipUnless(HAVE_SOFFICE, "LibreOffice (soffice) not installed: cannot render Arabic PDFs")
class TestArabicDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp(prefix="acretia_ar_")
        cls.docs = {}
        with mock.patch.dict(os.environ, {"ACRETIA_PARSER": "pdfdoc"}):
            for name, body in (("lease", LEASE), ("dist", DIST), ("loan", LOAN), ("decoy", DECOY)):
                cls.docs[name] = docparse.parse(render(body, cls.td, name))
        cls.eng = ExtractiveEngine()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.td, ignore_errors=True)

    def ask(self, doc, key):
        r = self.eng.answer(self.docs[doc], Q[key])
        if not r["not_found"]:
            self.assertIsNotNone(docparse.locate(self.docs[doc], r["page"], r["exact_quote"]), f"quote does not locate: {r['exact_quote']}")
        return r

    def test_lease(self):
        r = self.ask("lease", "fee")
        self.assertFalse(r["not_found"])
        self.assertEqual((r["value"], r["unit"]), (480000.0, "SAR"))
        self.assertIn("480,000", r["exact_quote"])
        r = self.ask("lease", "expiry")
        self.assertEqual((r["not_found"], r["value"]), (False, "2030-12-31"))
        r = self.ask("lease", "law")
        self.assertFalse(r["not_found"])
        self.assertIn("السعودية", r["answer"])
        r = self.ask("lease", "assign")
        self.assertFalse(r["not_found"])
        self.assertIn("التنازل", r["exact_quote"])
        r = self.ask("lease", "parties")
        self.assertFalse(r["not_found"])
        self.assertIn("النخيل", r["answer"])
        self.assertIn("الواحة", r["answer"])
        r = self.ask("lease", "notice")
        self.assertFalse(r["not_found"])
        self.assertIn("90", r["answer"])

    def test_distribution_exclusivity_mfn_fee_date(self):
        r = self.ask("dist", "excl")
        self.assertFalse(r["not_found"])
        self.assertIn("الحصري", r["exact_quote"])
        r = self.ask("dist", "mfn")
        self.assertFalse(r["not_found"])
        r = self.ask("dist", "fee")
        self.assertEqual((r["not_found"], r["value"], r["unit"]), (False, 1200000.0, "KWD"))
        r = self.ask("dist", "expiry")
        self.assertEqual(r["value"], "2031-06-15")

    def test_loan_change_of_control_revenue_effective(self):
        r = self.ask("loan", "coc")
        self.assertFalse(r["not_found"])
        self.assertIn("السيطرة", r["exact_quote"])
        r = self.ask("loan", "rev")
        self.assertEqual((r["not_found"], r["value"], r["unit"]), (False, 44100000.0, "USD"))
        r = self.ask("loan", "eff")
        self.assertEqual((r["not_found"], r["value"]), (False, "2024-03-01"))

    def test_abstains_without_the_concept(self):
        for key in ("excl", "coc", "mfn", "fee", "rev", "expiry"):       # the decoy states none of these
            r = self.ask("decoy", key)
            self.assertTrue(r["not_found"], (key, r.get("answer")))
        r = self.ask("decoy", "law")
        self.assertFalse(r["not_found"])
        self.assertIn("قطر", r["answer"])

    def test_non_exclusive_is_never_a_positive(self):
        r = self.ask("decoy", "excl")
        self.assertTrue(r["not_found"])
        self.assertNotIn("Yes", r["answer"])
        self.assertEqual(r["exact_quote"], "")


class TestEnglishUnchanged(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(grid.ENGINE_VERSION, "grid-3")

    def test_english_only_doc_has_no_arabic_candidates(self):
        self.assertEqual(grid._clause_ar(type("D", (), {"pages": []})(), "exclusivity"), [])


if __name__ == "__main__":
    unittest.main()
