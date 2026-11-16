"""Tests for om.deck.slop and om.deck.validate (S3.6/S3.7): each rule fires on a bad case, is silent on a clean one."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import pptx, PIL, fontTools  # noqa: F401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

from om.deck import slop
from om.deck.validate import validate

ROOT = Path(__file__).resolve().parent.parent
CW = (13.333 - 1.4 - 2.2) / 12


def gx(col: int) -> float:
    return 0.7 + col * (CW + 0.2)


def gr(col: int) -> float:
    return 0.7 + col * (CW + 0.2) - 0.2


class Deck:
    def __init__(self):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)

    def slide(self):
        return self.prs.slides.add_slide(self.prs.slide_layouts[6])

    def bytes(self) -> bytes:
        b = io.BytesIO()
        self.prs.save(b)
        return b.getvalue()


def text(slide, name, x, y, w, h, t, size=14, bold=False, color=None, fill=None, inset=0.0, align=None, font=None):
    s = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    s.name = name
    tf = s.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(inset)
    parts = t if isinstance(t, list) else [(t, bold)]
    p = tf.paragraphs[0]
    if align:
        p.alignment = align
    for tt, b in parts:
        r = p.add_run()
        r.text = tt
        r.font.size = Pt(size)
        r.font.bold = b
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
        if font:
            r.font.name = font
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = RGBColor.from_string(fill)
    return s


def line(slide, name, x1, y, x2):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y), Inches(x2), Inches(y))
    c.name = name
    return c


def frame(slide, n=1, title="Revenue grew 12% as pricing held", rule=True, footer_rule=True, page=True):
    text(slide, f"s{n}.title", 0.7, 0.5, 11.933, 0.95, title, 24, True)
    if rule:
        line(slide, f"s{n}.title_rule", 0.7, 1.55, 12.633)
    if footer_rule:
        line(slide, f"s{n}.footer_rule", 0.7, 6.95, 12.633)
    text(slide, f"s{n}.footer", 0.7, 7.02, 6, 0.3, "Acretia", 10)
    if page:
        text(slide, f"s{n}.page_number", 11.633, 7.02, 1.0, 0.3, str(n), 10, align=PP_ALIGN.RIGHT)


def good_body(slide, n=1):
    text(slide, f"s{n}.body", gx(0), 2.15, gr(6) - gx(0), 2.0,
         [("Revenue: ", True), ("grew ", False), ("12%", True), (" to ", False), ("$1.2bn", True), (" on price.", False)], 14)


def rules(rep, rule=None):
    return [f for f in rep.findings if rule is None or f["rule"] == rule]


class SlopTests(unittest.TestCase):
    def rules(self, t, **kw):
        return {r for r, _ in slop.lint_text(t, **kw)}

    def test_banned(self):
        for t in ["We leverage data", "Unlock value", "A seamless, robust plan", "It's important to note this",
                  "In today's fast-paced world", "Synergies emerge", "نقلة نوعية في السوق"]:
            self.assertIn("banned_phrase", self.rules(t), t)
        self.assertNotIn("banned_phrase", self.rules("Net leverage fell to 2.1x"))
        self.assertNotIn("banned_phrase", self.rules("Leveraged buyout of the target"))

    def test_punctuation(self):
        self.assertIn("punctuation", self.rules("Cost — down"))
        self.assertIn("punctuation", self.rules("Cost – down"))
        self.assertNotIn("punctuation", self.rules("FY24–25 range"))
        self.assertIn("punctuation", self.rules("Great \U0001F680"))
        self.assertIn("punctuation", self.rules("Win!"))
        self.assertIn("punctuation", self.rules("مبروك!"))
        self.assertIn("punctuation", self.rules("GROWTH accelerates"))
        self.assertNotIn("punctuation", self.rules("EBITDA and AAPL and EBIT grew"))
        self.assertIn("punctuation", self.rules("Revenue grew.", kind="title"))
        self.assertNotIn("punctuation", self.rules("Revenue grew."))

    def test_lint_spec(self):
        spec = {"title": "Deck", "slides": [{"id": "s1", "title": "Fine title", "blocks": {"a": ["ok", "robust plan"]}},
                                            {"id": "s2", "title": "Ends with stop."}]}
        f = slop.lint_spec(spec)
        self.assertEqual({(x["slide"], x["rule"]) for x in f}, {(1, "banned_phrase"), (2, "punctuation")})
        self.assertIn("slides[0].blocks.a[1]", f[0]["shape_name"] + f[1]["shape_name"])


class ValidateTests(unittest.TestCase):
    def one(self, build, **kw):
        d = Deck()
        s = d.slide()
        build(s)
        return validate(d.bytes(), **kw)

    def test_clean_house_slide(self):
        def b(s):
            frame(s)
            good_body(s)
        rep = self.one(b)
        self.assertEqual(rep.findings, [], rep.findings)
        self.assertTrue(rep.ok)

    def test_overflow_height(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(3) - gx(0), 0.4, "Long text that wraps over many lines in a small box. " * 6, 14)
        r = rules(self.one(b), "overflow")
        self.assertEqual(r[0]["shape_name"], "s1.body")
        self.assertEqual(r[0]["severity"], "critical")

    def test_overflow_wide_word(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, 1.0, 2.0, "Internationalisation", 14)
        self.assertTrue(rules(self.one(b), "overflow"))

    def test_overflow_arabic(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(3) - gx(0), 0.4, "نمت الإيرادات بنسبة كبيرة خلال العام المالي الماضي بفضل التسعير والحجم " * 4, 14)
        self.assertTrue(rules(self.one(b), "overflow"))

    def test_bounds_and_safe_margin(self):
        def b(s):
            frame(s)
            good_body(s)
            text(s, "s1.label", 12.0, 3.0, 2.0, 0.5, "Off slide", 12)
            text(s, "s1.label.2", 0.2, 4.0, 1.5, 0.5, "Edge", 12)
        rep = self.one(b)
        self.assertEqual([f["shape_name"] for f in rules(rep, "bounds")], ["s1.label"])
        self.assertIn("s1.label.2", [f["shape_name"] for f in rules(rep, "safe_margin")])

    def test_overlap(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 2.0, "Left", 14)
            text(s, "s1.callout", gx(3), 3.0, gr(9) - gx(3), 2.0, "Right", 14)
        self.assertTrue(rules(self.one(b), "overlap"))

    def test_text_on_panel_is_not_overlap(self):
        def b(s):
            frame(s)
            r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(gx(0)), Inches(2.15), Inches(gr(6) - gx(0)), Inches(3))
            r.name = "s1.visual"
            r.fill.solid()
            r.fill.fore_color.rgb = RGBColor.from_string("F2F3F5")
            text(s, "s1.body", gx(0) + 0.2, 2.35, gr(6) - gx(0) - 0.4, 1.0, "Inside", 14)
        self.assertEqual(rules(self.one(b), "overlap"), [])

    def test_contrast(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "Pale", 14, color="BBBBBB")
        self.assertTrue(rules(self.one(b), "contrast"))

        def ok(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "Dark on panel", 14, color="FFFFFF", fill="0B1F33")
        self.assertEqual(rules(self.one(ok), "contrast"), [])

    def test_contrast_large_text_threshold(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "Big", 28, color="949494")   # ~3:1
        self.assertEqual(rules(self.one(b), "contrast"), [])

    def test_font_floor(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "tiny", 9)
            text(s, "s1.callout", gx(7), 2.15, gr(12) - gx(7), 1.0, "mid", 11)
        rep = self.one(b)
        fl = {f["shape_name"]: f["severity"] for f in rules(rep, "font_floor")}
        self.assertEqual(fl["s1.body"], "critical")
        self.assertNotIn("s1.callout", fl)

        def b2(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "eleven", 11)
        self.assertEqual(rules(self.one(b2), "font_floor")[0]["severity"], "major")

    def test_xml_checks(self):
        d = Deck()
        frame(d.slide())
        raw = d.bytes()
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as zi, zipfile.ZipFile(out, "w") as zo:
            for n in zi.namelist():
                zo.writestr(n, zi.read(n))
            zo.writestr("customXml/bad.xml", "<a><b></a>")
        rep = validate(out.getvalue())
        self.assertTrue(any("bad.xml" in f["message"] for f in rules(rep, "xml")))
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as zi, zipfile.ZipFile(out, "w") as zo:
            for n in zi.namelist():
                data = zi.read(n)
                if n == "ppt/slides/_rels/slide1.xml.rels":
                    data = data.replace(b"</Relationships>", b'<Relationship Id="rId99" Type="http://x/y" Target="../media/none.png"/></Relationships>')
                zo.writestr(n, data)
        self.assertTrue(any("none.png" in f["message"] for f in rules(validate(out.getvalue()), "xml")))

    def test_house_rules_missing(self):
        def b(s):
            frame(s, rule=False, footer_rule=False, page=False)
            good_body(s)
        rep = self.one(b)
        self.assertTrue(rules(rep, "house_title_rule"))
        self.assertEqual(len(rules(rep, "house_footer")), 2)

    def test_page_number_must_match(self):
        def b(s):
            frame(s)
            good_body(s)
            for sh in s.shapes:
                if sh.name == "s1.page_number":
                    sh.text_frame.paragraphs[0].runs[0].text = "7"
        self.assertTrue(rules(self.one(b), "house_footer"))

    def test_eyebrow(self):
        def b(s):
            frame(s)
            good_body(s)
            text(s, "s1.label", 0.7, 0.5, 2.0, 0.3, "MARKET UPDATE", 12)
        self.assertTrue(rules(self.one(b), "house_eyebrow"))

    def test_cover_and_divider_exemptions(self):
        def b(s):
            text(s, "s1.cover", 0.7, 2.5, 11.933, 1.5, "Acme", 44, True)
            line(s, "s1.footer_rule", 0.7, 6.95, 12.633)
            text(s, "s1.title", 0.7, 0.5, 11.933, 0.95, "Acme overview", 24, True)
        rep = self.one(b)
        self.assertEqual(rules(rep, "house_title_rule"), [])
        self.assertEqual(rules(rep, "house_footer"), [])

    def test_banned_and_punctuation(self):
        def b(s):
            frame(s, title="We leverage data — and win!")
            good_body(s)
        rep = self.one(b)
        self.assertTrue(rules(rep, "banned_phrase"))
        self.assertTrue(rules(rep, "punctuation"))
        self.assertEqual(rules(rep, "banned_phrase")[0]["shape_name"], "s1.title")

    def test_slop_effects(self):
        def b(s):
            frame(s)
            good_body(s)
            body = [x for x in s.shapes if x.name == "s1.body"][0]
            sppr = body._element.spPr
            etree.SubElement(sppr, "{http://schemas.openxmlformats.org/drawingml/2006/main}effectLst").append(
                etree.Element("{http://schemas.openxmlformats.org/drawingml/2006/main}outerShdw"))
        r = rules(self.one(b), "slop_effects")
        self.assertEqual(r[0]["shape_name"], "s1.body")

    def test_grid(self):
        def b(s):
            frame(s)
            text(s, "s1.body", 0.95, 2.15, 4.0, 1.0, "Off grid", 14)
        rep = self.one(b)
        self.assertEqual(rules(rep, "grid")[0]["shape_name"], "s1.body")
        self.assertEqual(rules(self.one(lambda s: (frame(s), good_body(s))), "grid"), [])

    def test_type_sizes(self):
        def b(s):
            frame(s)
            for i, sz in enumerate((11, 12, 13, 14)):
                text(s, f"s1.label.{i}", gx(i * 3), 2.15, gr(i * 3 + 3) - gx(i * 3), 0.5, "x", sz)
        self.assertTrue(rules(self.one(b), "type_sizes"))

    def test_theme_font_and_color(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "Comic", 14, color="FF00FF", font="Comic Sans MS")
        rep = self.one(b)
        self.assertEqual(rules(rep, "theme_font")[0]["shape_name"], "s1.body")
        self.assertIn("FF00FF", rules(rep, "theme_color")[0]["message"])

    def test_whitespace(self):
        def b(s):
            frame(s)
            r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(1.6), Inches(11.933), Inches(5.3))
            r.name = "s1.visual"
            r.fill.solid()
            r.fill.fore_color.rgb = RGBColor.from_string("F2F3F5")
        self.assertTrue(rules(self.one(b), "whitespace"))

    def test_rounded_cards(self):
        def b(s):
            frame(s)
            for i in range(3):
                r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(gx(i * 4)), Inches(2.2), Inches(gr(i * 4 + 4) - gx(i * 4)), Inches(2))
                r.name = f"s1.callout.{i}"
                r.fill.solid()
                r.fill.fore_color.rgb = RGBColor.from_string("F2F3F5")
        self.assertTrue(rules(self.one(b), "rounded_cards"))

    def test_chart_font(self):
        def b(s):
            frame(s)
            cd = CategoryChartData()
            cd.categories = ["a", "b"]
            cd.add_series("s", (1, 2))
            gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(gx(0)), Inches(2.15), Inches(gr(6) - gx(0)), Inches(3), cd)
            gf.name = "s1.chart"
            gf.chart.font.size = Pt(8)
        self.assertTrue(rules(self.one(b), "chart_font"))

    def test_bold_figures(self):
        def b(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, gr(6) - gx(0), 1.0, "Revenue grew 12% to $1.2bn at 8.5x", 14)
        r = rules(self.one(b), "bold_figures")
        self.assertEqual(r[0]["severity"], "minor")
        self.assertEqual(rules(self.one(lambda s: (frame(s), good_body(s))), "bold_figures"), [])

    def test_foreign_shapes_get_generic_checks_only(self):
        def b(s):
            text(s, "TextBox 1", 0.7, 2.0, 5.0, 1.0, "Plain deck", 14)
        rep = self.one(b)
        self.assertEqual([f for f in rep.findings if f["rule"].startswith("house_")], [])


class CliTests(unittest.TestCase):
    def run_cli(self, build, *args):
        d = Deck()
        build(d.slide())
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "d.pptx"
            p.write_bytes(d.bytes())
            return subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_pptx.py"), str(p), *args],
                                  capture_output=True, text=True, cwd=ROOT)

    def test_exit_codes(self):
        good = self.run_cli(lambda s: (frame(s), good_body(s)))
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

        def bad(s):
            frame(s)
            text(s, "s1.body", gx(0), 2.15, 1.0, 0.3, "Overflowing text " * 20, 14)
        r = self.run_cli(bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn('"s1.body" · overflow', r.stdout)
        j = self.run_cli(bad, "--json", "--severity", "critical")
        data = json.loads(j.stdout)
        self.assertFalse(data["ok"])
        self.assertTrue(all(f["severity"] == "critical" for f in data["findings"]))


if __name__ == "__main__":
    unittest.main()
