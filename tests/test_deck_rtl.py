import unittest
from dataclasses import dataclass, field

try:
    import pptx, PIL, fontTools  # noqa: F401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

try:
    import arabic_reshaper  # noqa: F401
    HAVE_RESHAPER = True
except ImportError:
    HAVE_RESHAPER = False

from om.deck import metrics, rtl

AR = ("الإيرادات ارتفعت بنسبة كبيرة خلال العام المالي الحالي مدفوعة بنمو قوي في قطاع الخدمات المصرفية "
      "للأفراد والشركات مع تحسن ملحوظ في هوامش الربح التشغيلي وانخفاض تكلفة المخاطر مقارنة بالعام السابق "
      "وتوقعات إيجابية للأعوام القادمة بدعم من التحول الرقمي")


@dataclass
class Para:
    runs: list = field(default_factory=list)
    align: str = "l"


@dataclass
class TextSpec:
    paras: list


@dataclass
class Element:
    x: float
    w: float
    kind: str = "text"
    text: TextSpec | None = None
    chart: dict | None = None
    table: dict | None = None


@dataclass
class Slide:
    elements: list
    rtl: bool = False


class TestRtl(unittest.TestCase):
    def test_is_rtl(self):
        self.assertTrue(rtl.is_rtl(AR))
        self.assertTrue(rtl.is_rtl("שלום עולם"))
        self.assertFalse(rtl.is_rtl("Revenue grew 12%"))
        self.assertFalse(rtl.is_rtl("Revenue growth for الشركة was strong across all regions"))
        self.assertFalse(rtl.is_rtl("123"))

    @unittest.skipUnless(HAVE_RESHAPER, "arabic_reshaper not installed")
    def test_shape_and_width(self):
        s = rtl.shape(AR[:20])
        self.assertNotEqual(s, AR[:20])
        w = metrics.text_width(AR, 14)
        self.assertGreater(w, 0)
        naive = sum(1 for _ in AR) * 14 / 72 * 0.5
        self.assertNotAlmostEqual(w, naive, places=2)

    def test_arabic_paragraph_three_lines(self):
        m = metrics.measure(AR, 14, 3.2, rtl=True)
        self.assertGreaterEqual(m.lines, 3)
        self.assertLessEqual(m.widest_in, 3.2)

    def test_digits(self):
        self.assertEqual(rtl.digits("2025 ٢٠٢٥"), "2025 2025")
        self.assertEqual(rtl.digits("2025", "arabic-indic"), "٢٠٢٥")

    def test_mirror_x(self):
        self.assertAlmostEqual(rtl.mirror_x(0.7, 4), 13.333 - 4.7, places=2)

    def test_mirror_slide(self):
        s = Slide([
            Element(0.7, 4, text=TextSpec([Para(align="l"), Para(align="r"), Para(align="c")])),
            Element(5, 3, kind="chart", chart={"type": "bar"}),
            Element(1, 2, kind="table", table={"columns": ["a"]}),
            Element(0.7, 11.9, kind="line"),
        ])
        m = rtl.mirror(s)
        self.assertTrue(m.rtl)
        self.assertFalse(s.rtl)
        self.assertEqual(s.elements[0].x, 0.7)
        self.assertAlmostEqual(m.elements[0].x, 13.333 - 4.7, places=2)
        self.assertEqual([p.align for p in m.elements[0].text.paras], ["r", "l", "c"])
        self.assertTrue(m.elements[1].chart["rtl"])
        self.assertTrue(m.elements[2].table["rtl"])
        self.assertEqual(m.elements[2].table["columns"], ["a"])
        self.assertAlmostEqual(m.elements[3].x, 0.73, places=2)

    def test_mirror_dict(self):
        d = {"rtl": False, "elements": [{"x": 1.0, "w": 2.0, "chart": {}, "text": {"paras": [{"align": "l"}]}}]}
        m = rtl.mirror(d)
        self.assertTrue(m["rtl"])
        self.assertAlmostEqual(m["elements"][0]["x"], 13.333 - 3.0, places=2)
        self.assertTrue(m["elements"][0]["chart"]["rtl"])
        self.assertEqual(m["elements"][0]["text"]["paras"][0]["align"], "r")


if __name__ == "__main__":
    unittest.main()
