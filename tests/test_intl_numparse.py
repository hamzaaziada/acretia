import unittest
from datetime import date

from om.intl.numparse import (detect_unit, normalise_digits, parse_number, parse_period_header)

NUMBERS = [  # token, kwargs, value, kind
    ("(1,234)", {}, -1234.0, "number"),
    ("١٬٢٣٤٫٥", {}, 1234.5, "number"),
    ("۱۲۳", {}, 123.0, "number"),
    ("(١٢٣)", {}, -123.0, "number"),
    ("123-", {}, -123.0, "number"),
    ("-123", {}, -123.0, "number"),
    ("−123", {}, -123.0, "number"),
    ("–123", {}, -123.0, "number"),
    ("1.234.567", {}, 1234567.0, "number"),
    ("1,234,567", {}, 1234567.0, "number"),
    ("1.234,5", {}, 1234.5, "number"),
    ("1,234.5", {}, 1234.5, "number"),
    ("(1.234,50)", {}, -1234.5, "number"),
    ("12,5", {}, 12.5, "number"),
    ("0,123", {}, 0.123, "number"),
    ("1.234", {"decimal": ","}, 1234.0, "number"),
    ("1,234", {"decimal": ","}, 1.234, "number"),
    ("1 234 567", {}, 1234567.0, "number"),
    ("1 234 567", {}, 1234567.0, "number"),
    ("1 234", {}, 1234.0, "number"),
    ("‎(‎1,234)‏", {}, -1234.0, "number"),
    ("؜-٥٠", {}, -50.0, "number"),
    ("٣٫٥", {}, 3.5, "number"),
    ("(٣٫٥)", {}, -3.5, "number"),
    ("0", {}, 0.0, "number"),
    ("4,507,558", {}, 4507558.0, "number"),
    ("(2,737,892)", {}, -2737892.0, "number"),
    ("2024", {"context": "value"}, 2024.0, "number"),
    ("1,234.50-", {}, -1234.5, "number"),
    ("12.5%", {}, 12.5, "percent"),
    ("٪١٢", {}, 12.0, "percent"),
    ("(5.0%)", {}, -5.0, "percent"),
    ("-", {}, 0.0, "nil"),
    ("—", {}, 0.0, "nil"),
    ("–", {}, 0.0, "nil"),
    ("nil", {}, 0.0, "nil"),
    ("NIL", {}, 0.0, "nil"),
    ("--", {}, 0.0, "nil"),
    ("12(a)", {}, None, "note_ref"),
    ("إيضاح 5", {}, None, "note_ref"),
    ("Note 12", {}, None, "note_ref"),
    ("5", {"context": "note"}, None, "note_ref"),
    ("5,6", {"context": "note"}, None, "note_ref"),
    ("2024", {}, None, "year"),
    ("2024", {"context": "header"}, None, "year"),
    ("٢٠٢٣", {"context": "header"}, None, "year"),
    ("abc", {}, None, "text"),
    ("", {}, None, "text"),
    ("12 ABC", {}, None, "text"),
]


class ParseNumber(unittest.TestCase):
    def test_table(self):
        for tok, kw, value, kind in NUMBERS:
            with self.subTest(token=tok, kw=kw):
                p = parse_number(tok, **kw)
                self.assertEqual(p.kind, kind)
                if value is None:
                    self.assertIsNone(p.value)
                else:
                    self.assertAlmostEqual(p.value, value, places=6)
                self.assertEqual(p.is_nil, kind == "nil")
                if kind == "number":
                    self.assertEqual(p.negative, value < 0)

    def test_normalise(self):
        self.assertEqual(normalise_digits("٠١٢٣٤٥٦٧٨٩"), "0123456789")
        self.assertEqual(normalise_digits("۰۱۲۳۴۵۶۷۸۹"), "0123456789")
        self.assertEqual(normalise_digits("١٬٢٣٤٫٥"), "1,234.5")
        self.assertEqual(normalise_digits("‏‎1؜"), "1")


UNITS = [
    ("EGP '000", ("EGP", 1e3)),
    ("EGP thousands", ("EGP", 1e3)),
    ("بالألف جنيه مصري", ("EGP", 1e3)),
    ("جنيه مصري بالآلاف", ("EGP", 1e3)),
    ("(جميع المبالغ بالألف جنيه مصري)", ("EGP", 1e3)),
    ("SAR million", ("SAR", 1e6)),
    ("بالمليون ريال سعودي", ("SAR", 1e6)),
    ("ريال سعودي بالآلاف", ("SAR", 1e3)),
    ("(All amounts in SAR million)", ("SAR", 1e6)),
    ("AED'000", ("AED", 1e3)),
    ("AED thousand", ("AED", 1e3)),
    ("AED ’000", ("AED", 1e3)),
    ("درهم إماراتي", ("AED", None)),
    ("US$ thousands", ("USD", 1e3)),
    ("USD millions", ("USD", 1e6)),
    ("ر.س", ("SAR", None)),
    ("ج.م", ("EGP", None)),
    ("(in thousands of Egyptian Pounds)", ("EGP", 1e3)),
    ("EUR billion", ("EUR", 1e9)),
    ("الفوائد المدينة", (None, None)),
    ("Total assets", (None, None)),
    ("", (None, None)),
]


class Units(unittest.TestCase):
    def test_table(self):
        for text, want in UNITS:
            with self.subTest(text=text):
                self.assertEqual(detect_unit(text), want)


PERIODS = [
    ("31 December 2024", date(2024, 12, 31)),
    ("30 June 2024", date(2024, 6, 30)),
    ("31 March 2025", date(2025, 3, 31)),
    ("As at 31/12/2024", date(2024, 12, 31)),
    ("2024-06-30", date(2024, 6, 30)),
    ("June 30, 2024", date(2024, 6, 30)),
    ("For the year ended 30 September 2023", date(2023, 9, 30)),
    ("December 2024", date(2024, 12, 31)),
    ("٣٠ يونيو ٢٠٢٤", date(2024, 6, 30)),
    ("31 ديسمبر 2024", date(2024, 12, 31)),
    ("للسنة المنتهية في ٣١ مارس ٢٠٢٥", date(2025, 3, 31)),
    ("عن السنة المنتهية في 31 ديسمبر ٢٠٢٣م", date(2023, 12, 31)),
    ("٣١/١٢/٢٠٢٤", date(2024, 12, 31)),
    ("30 حزيران 2024", date(2024, 6, 30)),
    ("31 كانون الأول 2023", date(2023, 12, 31)),
    ("2024 ديسمبر 31", date(2024, 12, 31)),
    ("hello", None),
    ("31 Foo 2024", None),
    ("31 June 2024", None),
]


class Periods(unittest.TestCase):
    def test_table(self):
        for text, want in PERIODS:
            with self.subTest(text=text):
                self.assertEqual(parse_period_header(text), want)


if __name__ == "__main__":
    unittest.main()
