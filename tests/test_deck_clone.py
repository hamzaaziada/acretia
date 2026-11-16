"""S3.9: firm template cloner."""
from __future__ import annotations

import os
import re
import tempfile
import unittest
import zipfile

from lxml import etree
from pptx import Presentation
from pptx.util import Inches, Pt

from om.deck.house_clone import HouseProfile, clone, contrast
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
from om.deck.render import render
from om.deck.theme import Theme

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
CLIENT = {"dk1": "112233", "lt1": "FFFFFF", "dk2": "334455", "lt2": "EEEEEE", "accent1": "AA0044",
          "accent2": "0088CC", "accent3": "00AA55", "accent4": "FFCC00", "accent5": "228822", "accent6": "CC2200"}


def _theme_edit(prs, colors: dict, major="Georgia", minor="Verdana") -> None:
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    part = prs.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(part.blob)
    cs = root.find(f".//{{{A}}}clrScheme")
    for slot, val in colors.items():
        el = cs.find(f"{{{A}}}{slot}")
        for ch in list(el):
            el.remove(ch)
        etree.SubElement(el, f"{{{A}}}srgbClr").set("val", val)
    fs = root.find(f".//{{{A}}}fontScheme")
    fs.find(f"{{{A}}}majorFont/{{{A}}}latin").set("typeface", major)
    fs.find(f"{{{A}}}minorFont/{{{A}}}latin").set("typeface", minor)
    part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def make_template(path: str, colors=CLIENT, title_xywh=(0.9, 0.35, 11.0, 0.8)) -> str:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    _theme_edit(prs, colors)
    lay = prs.slide_layouts[1]  # Title and Content
    for ph in lay.placeholders:
        k = str(ph.placeholder_format.type)
        if "TITLE" in k:
            ph.left, ph.top, ph.width, ph.height = (Inches(v) for v in title_xywh)
        elif "BODY" in k or "OBJECT" in k:
            ph.left, ph.top, ph.width, ph.height = Inches(0.9), Inches(2.0), Inches(11.0), Inches(4.3)
    prs.save(path)
    return path


def make_sample(path: str, title_pt: float, body_pt: float, left: float, rule: bool) -> str:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    for _ in range(2):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        t = s.shapes.add_textbox(Inches(left), Inches(0.4), Inches(10), Inches(0.8))
        t.name = "Title 1"
        r = t.text_frame.paragraphs[0].add_run()
        r.text = "Headline"
        r.font.size = Pt(title_pt)
        b = s.shapes.add_textbox(Inches(left), Inches(2), Inches(10), Inches(2))
        r = b.text_frame.paragraphs[0].add_run()
        r.text = "Body"
        r.font.size = Pt(body_pt)
        if rule:
            s.shapes.add_connector(1, Inches(left), Inches(1.4), Inches(12.6), Inches(1.4))
    prs.save(path)
    return path


class CloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def test_extracts_theme_fonts_and_title_box(self):
        tpl = make_template(os.path.join(self.d, "client.pptx"))
        p = clone(tpl)
        th = p.theme()
        self.assertEqual(th.colors["accent"], "#AA0044")
        self.assertEqual(th.colors["text"], "#112233")
        self.assertEqual(th.colors["secondary"], "#334455")
        self.assertEqual(th.fonts["major"], "Georgia")
        self.assertEqual(th.fonts["minor"], "Verdana")
        self.assertAlmostEqual(p.grid["margin_x"], 0.9, 2)
        self.assertAlmostEqual(p.grid["title_y"], 0.35, 2)
        self.assertAlmostEqual(p.grid["title_h"], 0.8, 2)
        self.assertAlmostEqual(p.grid["content_top"], 2.0, 2)
        self.assertAlmostEqual(p.grid["content_bottom"], 6.3, 2)
        self.assertEqual(p.layout_name, "Title and Content")
        self.assertTrue(any(e.startswith("colors.accent") for e in p.evidence))
        # fonts cs empty in the default theme -> house fallback with evidence
        self.assertTrue(any("fonts.major_cs" in e and "fallback" in e for e in p.evidence))

    def test_potx_content_type_is_read(self):
        src = make_template(os.path.join(self.d, "c.pptx"))
        potx = os.path.join(self.d, "c.potx")
        with zipfile.ZipFile(src) as zi, zipfile.ZipFile(potx, "w") as zo:
            for it in zi.infolist():
                b = zi.read(it.filename)
                if it.filename == "[Content_Types].xml":
                    b = b.replace(b"presentationml.presentation.main+xml", b"presentationml.template.main+xml")
                zo.writestr(it, b)
        self.assertEqual(clone(potx).theme().fonts["major"], "Georgia")

    def test_sample_decks_modal_sizes_margin_rule(self):
        tpl = make_template(os.path.join(self.d, "c.pptx"))
        samples = [make_sample(os.path.join(self.d, f"s{i}.pptx"), 28, 16, 0.8, True) for i in range(3)]
        p = clone(tpl, samples)
        self.assertEqual(p.sizes["title"], 28.0)
        self.assertEqual(p.sizes["body"], 16.0)
        self.assertAlmostEqual(p.grid["margin_x"], 0.8, 2)
        self.assertTrue(p.sizes["title_rule"])
        p2 = clone(tpl, [make_sample(os.path.join(self.d, "n.pptx"), 28, 16, 0.8, False)])
        self.assertFalse(p2.sizes["title_rule"])

    def test_out_of_range_falls_back_with_note(self):
        tpl = make_template(os.path.join(self.d, "c.pptx"))
        p = clone(tpl, [make_sample(os.path.join(self.d, "s.pptx"), 12, 16, 0.8, False)])
        self.assertEqual(p.sizes["title"], Theme.house().sizes["title"])
        self.assertTrue(any("sizes.title" in e and "outside" in e for e in p.evidence))

    def test_low_contrast_falls_back(self):
        bad = dict(CLIENT, dk1="F5F5F5", lt1="FFFFFF")
        p = clone(make_template(os.path.join(self.d, "c.pptx"), colors=bad))
        house = Theme.house()
        self.assertEqual(p.theme().colors["text"], house.colors["text"])
        self.assertGreaterEqual(contrast(p.theme().colors["text"], p.theme().colors["background"]), 4.5)
        self.assertTrue(any("contrast" in e for e in p.evidence))

    def test_title_box_outside_range_falls_back(self):
        p = clone(make_template(os.path.join(self.d, "c.pptx"), title_xywh=(3.5, 0.35, 8.0, 0.8)))
        self.assertEqual(p.grid["margin_x"], Theme.house().grid["margin_x"])

    def test_json_roundtrip(self):
        p = clone(make_template(os.path.join(self.d, "c.pptx")))
        path = os.path.join(self.d, "profile.json")
        p.save(path)
        q = HouseProfile.load(path)
        self.assertEqual(q.to_dict(), p.to_dict())
        self.assertEqual(q.theme().fonts, p.theme().fonts)

    def test_render_with_template_has_client_theme(self):
        tpl = make_template(os.path.join(self.d, "c.pptx"))
        prof = clone(tpl)
        el = Element(id="s1.title", kind="text", role="title", x=0.9, y=0.35, w=8, h=0.8,
                     text=TextSpec([Para([Run("Hello")])], 24))
        data = render([SolvedSlide(1, "x", [el])], prof.theme(), title="t", template=tpl)
        with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
            theme_xml = z.read("ppt/theme/theme1.xml").decode()
        self.assertIn("Georgia", theme_xml)
        self.assertIn("AA0044", theme_xml)
        self.assertEqual(len(Presentation(__import__("io").BytesIO(data)).slides), 1)
        self.assertEqual(prof.theme().fonts["major"], "Georgia")


if __name__ == "__main__":
    unittest.main()
