import unittest
import warnings
from dataclasses import dataclass, field

from om.deck import fit, metrics

try:
    from om.deck.model import Para, Run
except Exception:  # model.py not written yet: minimal local fallback
    @dataclass
    class Run:
        t: str
        b: bool = False

    @dataclass
    class Para:
        runs: list
        align: str = "l"
        level: int = 0
        bullet: bool = False
        space_after: float = 4


WORDS = "revenue growth margin expansion drives durable returns across segments".split()


def text_of(n):
    return " ".join(WORDS[i % len(WORDS)] for i in range(n))


def P(t, **k):
    return Para([Run(t)], **k)


class TestMetrics(unittest.TestCase):
    def test_width_vs_pillow(self):
        from PIL import ImageFont
        for fam, bold in (("Arial", False), ("Arial", True), ("Calibri", False)):
            path = metrics._resolve(fam, bold)
            self.assertTrue(path, fam)
            f = ImageFont.truetype(path, 100)
            s = "Revenue growth was 12.5% in FY2025"
            ref = f.getlength(s) / 100 * 14 / 72
            got = metrics.text_width(s, 14, bold=bold, font=fam)
            self.assertAlmostEqual(got / ref, 1.0, delta=0.02)

    def test_roles(self):
        self.assertGreater(metrics.text_width("Hello world", 14, font="major"), 0)
        self.assertGreater(metrics.text_width("Hello world", 14, bold=True),
                           metrics.text_width("Hello world", 14))

    def test_wrap_60_words(self):
        m = metrics.measure(text_of(60), 14, 4.0)
        self.assertTrue(8 <= m.lines <= 14, m.lines)
        self.assertEqual(len(m.line_texts), m.lines)
        self.assertAlmostEqual(m.height_in, m.lines * 1.2 * 14 / 72)
        self.assertLessEqual(m.widest_in, 4.0)

    def test_hard_newline_and_long_word(self):
        self.assertEqual(metrics.measure("a\nb\nc", 14, 4).lines, 3)
        m = metrics.measure("x" * 200, 14, 2.0)
        self.assertGreater(m.lines, 1)
        self.assertLessEqual(m.widest_in, 2.0)

    def test_line_spacing(self):
        a = metrics.measure("a\nb", 14, 4)
        b = metrics.measure("a\nb", 14, 4, line_spacing=0.9)
        self.assertAlmostEqual(b.height_in, a.height_in * 0.9)

    def test_para_height_bullets_and_bold(self):
        ps = [P(text_of(30)), P(text_of(30))]
        plain = metrics.para_height(ps, 4, 14, space_after_pt=0)
        bul = metrics.para_height([P(text_of(30), bullet=True), P(text_of(30), bullet=True)], 4, 14, space_after_pt=0)
        self.assertGreaterEqual(bul, plain)
        bold = metrics.para_height([Para([Run(text_of(30), b=True)])], 4, 14, space_after_pt=0)
        self.assertGreaterEqual(bold, metrics.para_height([P(text_of(30))], 4, 14, space_after_pt=0))
        sa = metrics.para_height(ps, 4, 14)
        self.assertAlmostEqual(sa - plain, 8 / 72)

    def test_missing_font_falls_back_with_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            self.assertGreater(metrics.text_width("hello", 14, font="NoSuchFontXYZ"), 0)
        self.assertTrue(any("falling back" in str(x.message) for x in w))


class TestFit(unittest.TestCase):
    def test_reflow_only(self):
        r = fit.fit_text([P(text_of(10))], 6, 3, size=14, floor=10, role="body", block_id="s1.body.1")
        self.assertTrue(r.ok)
        self.assertEqual(r.size, 14)
        self.assertEqual(r.steps, ["reflow"])

    def test_tighten_only(self):
        paras = [P(text_of(6)) for _ in range(6)]   # 6 one-line paras with space_after 4
        need = metrics.para_height(paras, 6, 14)
        nosp = metrics.para_height(paras, 6, 14, space_after_pt=0)
        h = (need + nosp) / 2
        r = fit.fit_text(paras, 6, h, size=14, floor=10, role="body", block_id="s1.body.1")
        self.assertTrue(r.ok)
        self.assertEqual(r.size, 14)
        self.assertTrue(any(s.startswith("tighten") for s in r.steps))
        self.assertFalse(any(s.startswith("shrink") for s in r.steps))

    def test_shrink(self):
        paras = [P(text_of(40))]
        h14 = metrics.para_height(paras, 4, 14, line_spacing=0.9, space_after_pt=0)
        r = fit.fit_text(paras, 4, h14 * 0.85, size=14, floor=10, role="body", block_id="s2.body.1")
        self.assertTrue(r.ok)
        self.assertLess(r.size, 14)
        self.assertGreaterEqual(r.size, 10)
        self.assertTrue(any(s.startswith("shrink") for s in r.steps))

    def test_error(self):
        paras = [P(text_of(120))]
        r = fit.fit_text(paras, 4, 1.0, size=14, floor=10, role="body", block_id="s4.body.2")
        self.assertFalse(r.ok)
        e = r.error
        self.assertEqual(e.block_id, "s4.body.2")
        self.assertTrue(0 < e.words_over < 120)
        self.assertEqual(e.message, f"body block 2 is {e.words_over} words over; cut or split")
        self.assertGreater(e.chars_over, 0)

    def test_title_two_line_rule(self):
        self.assertTrue(fit.fit_title("Short title", 8).ok)
        long = text_of(40)
        t = fit.fit_title(long, 8)
        self.assertFalse(t.ok)
        self.assertGreater(t.words_over, 0)
        self.assertTrue(fit.fit_title(text_of(12), 8).lines <= 2)


if __name__ == "__main__":
    unittest.main()
