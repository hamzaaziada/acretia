"""S8.2 label dictionary: G3 cases, normalisation invariance, adversarial matches, coverage."""
import random
import unittest

from om.intl import labels as L
from om.intl.concepts import key_to_concepts
from om.statements import LINES

G3_KEYS = ["revenue", "ebit", "pretax", "net_income", "assets", "current_assets", "current_liabilities", "cfo", "cfi",
           "cff", "cogs", "cash", "equity_total", "liabilities", "capex", "da"]
CONTRACT_X = ["x.zakat", "x.rou_assets", "x.lease_liabilities_current", "x.lease_liabilities_noncurrent",
              "x.lease_interest", "x.rou_depreciation", "x.eosb", "x.employee_costs", "x.raw_materials",
              "x.depreciation", "x.amortisation", "x.other_opex", "x.other_income", "x.fx_gain_loss",
              "x.share_of_associates", "x.nci_profit", "x.oci_total", "x.total_comprehensive_income",
              "x.investment_property", "x.cash_beginning", "x.cash_end", "x.fx_effect_cash", "x.selling_expenses",
              "x.admin_expenses", "x.gov_grants", "x.capitalised_dev", "x.provisions", "x.retained_earnings",
              "x.share_capital", "x.nci_equity", "x.noncurrent_assets", "x.noncurrent_liabilities", "x.eps_basic",
              "x.changes_in_inventories", "x.finance_costs_net"]

PLAIN_AR = [  # (label, key)
    ("إيرادات النشاط", "revenue"), ("المبيعات", "revenue"), ("صافي المبيعات", "revenue"),
    ("تكلفة المبيعات", "cogs"), ("تكلفة الإيرادات", "cogs"), ("مجمل الربح", "gross_profit"),
    ("مصروفات بيع وتوزيع", "x.selling_expenses"), ("مصروفات عمومية وإدارية", "x.admin_expenses"),
    ("أرباح التشغيل", "ebit"), ("الربح قبل الزكاة وضريبة الدخل", "pretax"), ("الزكاة", "x.zakat"),
    ("ضريبة الدخل", "tax"), ("صافي ربح العام", "net_income"), ("صافي الربح", "net_income"),
    ("صافي الخسارة", "net_income"), ("النقدية وما في حكمها", "cash"), ("إجمالي الأصول المتداولة", "current_assets"),
    ("إجمالي الأصول", "assets"), ("مخصص مكافأة نهاية الخدمة", "x.eosb"),
    ("التزامات عقود الإيجار", "x.lease_liabilities_noncurrent"), ("أصول حق الاستخدام", "x.rou_assets"),
    ("حقوق الملكية غير المسيطرة", "x.nci_equity"),
    ("صافي التدفقات النقدية من الأنشطة التشغيلية", "cfo"), ("فروق ترجمة عملات أجنبية", "x.fx_translation_oci"),
    ("إجمالي الأصول غير المتداولة", "x.noncurrent_assets"), ("إجمالي الالتزامات", "liabilities"),
    ("إجمالي حقوق الملكية", "equity_total"),
]
PLAIN_EN = [
    ("Revenue", "revenue"), ("Net sales", "revenue"), ("Cost of sales", "cogs"), ("Gross profit", "gross_profit"),
    ("Operating profit", "ebit"), ("Profit before zakat and income tax", "pretax"), ("Zakat", "x.zakat"),
    ("Total current assets", "current_assets"), ("Total non-current assets", "x.noncurrent_assets"),
    ("Total assets", "assets"), ("Total liabilities", "liabilities"), ("Total equity", "equity_total"),
    ("Net cash from operating activities", "cfo"), ("Net cash used in investing activities", "cfi"),
    ("Net cash from financing activities", "cff"), ("Right-of-use assets", "x.rou_assets"),
    ("Non-controlling interests", "x.nci_equity"), ("Cash and cash equivalents", "cash"),
    ("Purchase of property, plant and equipment", "capex"), ("Depreciation and amortisation", "da"),
]


def _scramble(s: str, rng: random.Random) -> str:
    """Re-spell an Arabic label with variant forms that must normalise away."""
    out = []
    for ch in s:
        if ch == "ا":
            ch = rng.choice(["ا", "أ", "إ", "آ", "ٱ"])
        elif ch == "ي":
            ch = rng.choice(["ي", "ى"])
        elif ch == "ه":
            ch = rng.choice(["ه", "ة"])
        out.append(ch)
        if "ء" <= ch <= "ي" and rng.random() < 0.25:
            out.append(rng.choice(["َ", "ُ", "ِ", "ّ", "ْ", "ـ"]))
    return "".join(out)


class TestNormalisation(unittest.TestCase):
    def test_ar_forms(self):
        self.assertEqual(L.normalise_ar("أرباح"), L.normalise_ar("ارباح"))
        self.assertEqual(L.normalise_ar("إيرادات"), L.normalise_ar("ايرادات"))
        self.assertEqual(L.normalise_ar("آخر"), L.normalise_ar("اخر"))
        self.assertEqual(L.normalise_ar("الزكاة"), L.normalise_ar("الزكاه"))
        self.assertEqual(L.normalise_ar("مستشفى"), L.normalise_ar("مستشفي"))
        self.assertEqual(L.normalise_ar("الإيـــرادات"), L.normalise_ar("الايرادات"))
        self.assertEqual(L.normalise_ar("الرِّبْح"), L.normalise_ar("الربح"))
        self.assertEqual(L.normalise_ar("مؤجلة"), L.normalise_ar("موجله"))

    def test_digits_and_notes(self):
        self.assertEqual(L.normalise_digits("١٢٣"), "123")
        self.assertEqual(L.normalise_digits("۱۲۳"), "123")
        base = L.normalise_ar("صافي الربح")
        for s in ["صافي الربح (إيضاح ١٢)", "صافي الربح (ايضاح 12)", "صافي الربح إيضاح رقم ۱۲", "صافي الربح (إيضاحات ٥ و ٦)",
                  "  صافي   الربح  ", "صافي-الربح:", "صافي الربح (معدلة)", "صافي الربح (معاد إدراجها)"]:
            self.assertEqual(L.normalise_ar(s), base, s)
        self.assertEqual(L.normalise_ar("ملاحظة ١٢"), L.normalise_ar("ملاحظة 12"))

    def test_en(self):
        base = L.normalise_label("Net profit")
        for s in ["NET PROFIT", "Net profit (Note 12)", "The Net Profit", "Net profit for the year", "Net profit (restated)",
                  "Net profit for the year ended 31 December 2023", "Net  profit.", "Net profit [note 5]"]:
            self.assertEqual(L.normalise_label(s), base, s)
        self.assertEqual(L.normalise_label("Non-current assets"), L.normalise_label("Noncurrent assets"))
        self.assertEqual(L.normalise_label("Selling & distribution"), L.normalise_label("selling and distribution"))

    def test_marker_stripped(self):
        self.assertEqual(L.normalise_label("Total assets (A+B)"), L.normalise_label("Total assets"))
        self.assertEqual(L.normalise_ar("إجمالي الأصول (أ+ب)"), L.normalise_ar("إجمالي الأصول"))

    def test_invariance_over_every_arabic_variant(self):
        rng = random.Random(8)
        n = 0
        for e in L.entries(lang="ar")[::7]:
            m0 = L.match(e.label)
            self.assertIsNotNone(m0, e.label)
            for _ in range(2):
                v = _scramble(e.label, rng)
                v = v.replace("1", "١").replace("2", "۲")
                m = L.match(v)
                self.assertIsNotNone(m, v)
                self.assertEqual((m.key, m.sign_hint), (m0.key, m0.sign_hint), (e.label, v))
                n += 1
        self.assertGreater(n, 500)

    def test_digit_variants_in_labels(self):
        for plain, uni in [("إجمالي الأصول (1)", "إجمالي الأصول (١)"), ("إجمالي الأصول (2)", "إجمالي الأصول (۲)")]:
            self.assertEqual(L.match(plain).key, L.match(uni).key)
        self.assertEqual(L.match("صافي الربح (إيضاح 5)").key, L.match("صافي الربح (إيضاح ٥)").key)
        self.assertEqual(L.match("صافي الربح (إيضاح ۵)").key, "net_income")

    def test_english_case_and_notes_invariance(self):
        for e in L.entries(lang="en")[::13]:
            m0 = L.match(e.label)
            for v in (e.label.upper(), e.label + " (Note 7)", "The " + e.label, e.label + " (restated)"):
                m = L.match(v)
                self.assertIsNotNone(m, v)
                self.assertEqual(m.key, m0.key, v)


class TestMatching(unittest.TestCase):
    def test_plain(self):
        for lab, key in PLAIN_AR + PLAIN_EN:
            m = L.match(lab)
            self.assertIsNotNone(m, lab)
            self.assertEqual(m.key, key, lab)
            self.assertGreaterEqual(m.confidence, 0.95, lab)

    def test_exact_is_one(self):
        self.assertEqual(L.match("إيرادات النشاط").confidence, 1.0)
        self.assertEqual(L.match("Total assets").confidence, 1.0)

    def test_sign_pairs(self):
        p, n = L.match("صافي الربح"), L.match("صافي الخسارة")
        self.assertEqual(p.key, n.key)
        self.assertEqual((p.sign_hint, n.sign_hint), (1, -1))
        for pos, neg, key in [("Net profit", "Net loss", "net_income"), ("Gross profit", "Gross loss", "gross_profit"),
                              ("Operating profit", "Operating loss", "ebit"),
                              ("Profit before tax", "Loss before tax", "pretax"),
                              ("Net cash from operating activities", "Net cash used in operating activities", "cfo"),
                              ("الربح قبل الضريبة", "الخسارة قبل الضريبة", "pretax"),
                              ("صافي التدفقات النقدية من الأنشطة التشغيلية", "صافي التدفقات النقدية المستخدمة في الأنشطة التشغيلية", "cfo")]:
            a, b = L.match(pos), L.match(neg)
            self.assertEqual((a.key, b.key), (key, key), pos)
            self.assertEqual((a.sign_hint, b.sign_hint), (1, -1), pos)

    def test_signed_pl_effects(self):
        # S8.6a: these are signed P&L effects; the loss form carries -1
        self.assertEqual(L.match("Foreign exchange gain").sign_hint, 1)
        self.assertEqual(L.match("Foreign exchange loss").sign_hint, -1)
        self.assertEqual(L.match("أرباح فروق العملة").sign_hint, 1)
        self.assertEqual(L.match("خسائر فروق العملة").sign_hint, -1)
        self.assertEqual(L.match("Share of loss of associates").sign_hint, -1)
        self.assertEqual(L.match("Share of profit of associates").sign_hint, 1)
        self.assertEqual(L.match("Other income").key, "x.other_income")
        self.assertEqual(L.match("Changes in inventories of finished goods and work in progress").key,
                         "x.changes_in_inventories")

    def test_totals_vs_components(self):
        self.assertEqual(L.match("إجمالي الأصول المتداولة").key, "current_assets")
        self.assertEqual(L.match("Total non-current assets").key, "x.noncurrent_assets")
        self.assertEqual(L.match("Total current liabilities").key, "current_liabilities")
        self.assertEqual(L.match("إجمالي الالتزامات غير المتداولة").key, "x.noncurrent_liabilities")
        for comp in ["Other current assets", "Other non-current assets", "Trade receivables", "Right-of-use assets",
                     "Investment property", "Deferred tax assets", "Property, plant and equipment", "Inventories",
                     "Other current liabilities", "Trade and other payables", "Retained earnings", "Share capital",
                     "الأصول المتداولة الأخرى", "الذمم المدينة التجارية", "أصول حق الاستخدام", "الأرباح المبقاة",
                     "رأس المال", "المخزون", "الالتزامات المتداولة الأخرى", "الذمم الدائنة التجارية",
                     "Intangible assets other than goodwill", "Cash", "Goodwill"]:
            m = L.match(comp)
            self.assertIsNotNone(m, comp)
            self.assertFalse(m.is_total, (comp, m.key))
            self.assertNotIn(m.key, ("assets", "current_assets", "liabilities", "current_liabilities",
                                     "equity_total", "x.noncurrent_assets", "x.noncurrent_liabilities"), comp)

    def test_fuzzy_never_climbs_to_total(self):
        # unlisted component phrasings: must not become a total, whatever else they match
        for lab in ["Other miscellaneous current assets", "Long-term prepaid insurance assets",
                    "Trade receivables from related parties assets", "أصول متداولة أخرى متنوعة",
                    "ذمم مدينة من أطراف ذات علاقة أصول"]:
            m = L.match(lab)
            if m is not None:
                self.assertFalse(m.is_total and m.confidence >= 0.5, (lab, m))

    def test_zakat_pretax(self):
        for lab in ["Profit before zakat and income tax", "Profit before zakat and tax", "Income before zakat and income tax",
                    "الربح قبل الزكاة وضريبة الدخل", "الربح قبل الزكاة والضريبة"]:
            self.assertEqual(L.match(lab).key, "pretax", lab)
        self.assertEqual(L.match("Zakat").key, "x.zakat")
        self.assertEqual(L.match("الزكاة").key, "x.zakat")

    def test_statement_hint(self):
        self.assertEqual(L.match("Net profit", statement="CF").key, "cf_net_income")
        self.assertEqual(L.match("Net profit", statement="IS").key, "net_income")
        self.assertEqual(L.match("صافي الربح", statement="CF").key, "cf_net_income")
        self.assertEqual(L.match("صافي الربح", statement="IS").key, "net_income")
        self.assertEqual(L.match("Non-controlling interests", statement="BS").key, "x.nci_equity")
        self.assertEqual(L.match("Non-controlling interests", statement="IS").key, "x.nci_profit")
        self.assertEqual(L.match("Depreciation", statement="CF").key, "da")
        self.assertEqual(L.match("Income tax paid", statement="CF").key, "x.tax_paid")

    def test_ambiguous_without_hint_is_flagged(self):
        for n, keys in L.exact_collisions().items():
            lang = L.detect_lang(n)
            m = L.match(n)
            self.assertIsNotNone(m)
            self.assertLess(m.confidence, 1.0, n)
            self.assertIn(m.key, keys)

    def test_unknown(self):
        for lab in ["", "   ", "xyzzy", "Lorem ipsum dolor", "Page 12", "31 December 2023", "كلمات عشوائية لا معنى لها",
                    "Notes to the financial statements", "123,456", "Weather forecast", "Chief executive officer"]:
            m = L.match(lab)
            self.assertTrue(m is None or m.confidence < 0.5, (lab, m))

    def test_fuzzy_margin(self):
        # an unlisted variant close to one key matches it with moderate confidence
        m = L.match("Revenue from contracts with customers, net")
        self.assertEqual(m.key, "revenue")
        self.assertLess(m.confidence, 1.0)
        self.assertGreaterEqual(m.confidence, 0.5)
        # a mixed phrase equally near two keys is ambiguous
        m = L.match("Cost of sales and administrative expenses")
        self.assertTrue(m is None or m.confidence < 0.5, m)

    def test_bilingual_label(self):
        m = L.match("Revenue / الإيرادات")
        self.assertEqual(m.key, "revenue")
        self.assertEqual(m.lang, "bi")
        m = L.match("Total assets إجمالي الأصول")
        self.assertEqual(m.key, "assets")

    def test_no_sign_conflicts_within_a_key(self):
        seen = {}
        for e in L.entries():
            k = (e.key, e.norm)
            if k in seen:
                self.assertEqual(seen[k], e.sign_hint, e.label)
            seen[k] = e.sign_hint

    def test_one_text_one_sign_across_dictionary(self):
        by = {}
        for e in L.entries():
            by.setdefault((e.norm,), set()).add((e.key, e.sign_hint))
        for norm, s in by.items():
            keys = {k for k, _ in s}
            for k in keys:
                self.assertEqual(len({sg for kk, sg in s if kk == k}), 1, norm)


class TestCoverage(unittest.TestCase):
    def test_counts(self):
        c = L.label_counts()
        self.assertGreaterEqual(c["en"], 400)
        self.assertGreaterEqual(c["ar"], 400)

    def test_every_lines_key_has_both_languages(self):
        for key in LINES:
            self.assertTrue(L.entries(key, "en"), key)
            self.assertTrue(L.entries(key, "ar"), key)

    def test_every_extra_key_has_both_languages(self):
        for key in CONTRACT_X:
            self.assertIn(key, L.EXTRA_KEYS)
            self.assertTrue(L.entries(key, "en"), key)
            self.assertTrue(L.entries(key, "ar"), key)
        for key in L.EXTRA_KEYS:
            self.assertTrue(key.startswith("x."))
            self.assertTrue(L.entries(key, "en") and L.entries(key, "ar"), key)

    def test_g3_keys_have_labels_and_concepts(self):
        for key in G3_KEYS:
            self.assertIn(key, LINES)
            self.assertTrue(L.entries(key, "en"), key)
            self.assertTrue(L.entries(key, "ar"), key)
            self.assertTrue(key_to_concepts(key), key)

    def test_metadata_matches_lines(self):
        for key, (st, _kind, _sign, _lab, _chain) in LINES.items():
            self.assertEqual(L.key_info(key)["statement"], st, key)
        for key in ["gross_profit", "ebit", "pretax", "net_income", "current_assets", "assets", "current_liabilities",
                    "liabilities", "equity_parent", "liabilities_equity", "equity_total", "cfo", "cfi", "cff",
                    "net_change_cash"]:
            self.assertTrue(L.key_info(key)["total"], key)
        for key in ["revenue", "cogs", "cash", "ar", "inventory", "ppe", "capex", "da"]:
            self.assertFalse(L.key_info(key)["total"], key)

    def test_entry_fields(self):
        for e in L.entries():
            self.assertIn(e.sign_hint, (1, -1))
            self.assertIn(e.lang, ("en", "ar"))
            self.assertTrue(e.norm)


if __name__ == "__main__":
    unittest.main()
