"""S3.core: model round-trip, theme, python-pptx renderer, archetype registry and house frame."""
from __future__ import annotations

import base64
import importlib.util
import io
import os
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib

import unittest

try:
    import pptx, PIL, fontTools  # noqa: F401,E401
except ImportError as e:  # clean machine without deck deps: skip, do not error
    raise unittest.SkipTest(f"deck deps missing: {e}")

from lxml import etree
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE

from om.deck import archetypes
from om.deck.archetypes import BuildContext, base
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec, parse_role
from om.deck.render import read_bindings, render
from om.deck.theme import Theme, grid_w, grid_x

THEME = Theme.house()


def png() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def ctx(i: int, total: int = 5, rtl: bool = False) -> BuildContext:
    return BuildContext(THEME, i, total, "Project Atlas", rtl=rtl, lang="ar" if rtl else "en")


WATERFALL = {"type": "waterfall", "categories": ["FY25", "Price", "Volume", "Cost", "FY26"],
             "series": [{"name": "EBITDA", "values": [100, 12, -8, -4, 100]}]}


def build_deck(rtl: bool = False) -> list[SolvedSlide]:
    mk = lambda aid, i, spec: archetypes.get(aid).build(spec, ctx(i, rtl=rtl))
    title = "مشروع أطلس" if rtl else "Project Atlas"
    slides = [
        mk("cover", 1, {"title": title, "blocks": {"client": "Acme", "date": "2026-09-30"}}),
        mk("section_divider", 2, {"title": "Financial performance", "blocks": {"number": 1}}),
        mk("chart_takeaways", 3, {
            "title": "EBITDA is flat as price gains offset volume and cost drag", "source": "Company filings",
            "as_of": "2026-09-30", "notes": "speaker notes",
            "blocks": {"subtitle": "EBITDA bridge, FY25-26, $ million", "chart": WATERFALL,
                       "takeaways": ["Price: +$12m from list increases", "Volume: -$8m, mostly Q3",
                                     "Cost: 4.0% inflation absorbed"],
                       "binding": {"manifest_id": "m1", "kind": "chart", "format": "0.0"}}}),
    ]
    els = base.frame({"title": "Peer table", "source": "FactSet"}, ctx(4, rtl=rtl))
    els.append(Element("s4.table", "table", "table", 0.7, 2.0, 7.0, 2.4, table={
        "columns": ["Company", "EV/EBITDA", "Margin"], "rows": [["Acme", "12.5x", "21%"], ["Beta", "9.1x", "18%"]],
        "col_align": ["l", "r", "r"], "bold_rows": [1], "highlight_col": 1, "size": 14}))
    els.append(Element("s4.visual", "image", "visual", 8.0, 2.0, 2.0, 2.0,
                       image={"png": png(), "alt": "red square", "style": "x", "candidate_id": "c1"}))
    slides.append(base.solved({"title": "Peer table"}, ctx(4, rtl=rtl), "table_test", "table", els))
    chart_els = [Element("s5.chart", "chart", "chart", 0.7, 2.0, 6.0, 3.5, chart={
        "type": "football_field", "categories": ["DCF", "Comps"], "labels": True, "legend": False,
        "series": [{"name": "Low", "values": [80, 70]}, {"name": "High", "values": [120, 100]}]}),
        Element("s5.chart.2", "chart", "chart", 7.0, 2.0, 5.0, 3.5, chart={
            "type": "combo", "categories": ["a", "b", "c"], "labels": True, "legend": True,
            "series": [{"name": "Rev", "values": [1, 2, 3]}, {"name": "Margin", "values": [0.1, 0.2, 0.3]}]})]
    slides.append(SolvedSlide(5, "charts_test", chart_els, rtl=rtl))
    return slides


def xml_of(el) -> str:
    return etree.tostring(el).decode()


class DeckRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slides = build_deck()
        cls.data = render(cls.slides, THEME, title="Project Atlas")
        cls.prs = Presentation(io.BytesIO(cls.data))
        cls.rtl_slides = build_deck(rtl=True)
        cls.rtl_data = render(cls.rtl_slides, THEME, title="مشروع")

    def test_model_round_trip(self):
        for s in self.slides:
            d = s.to_dict()
            self.assertEqual(SolvedSlide.from_dict(d), s)
        img = next(e for s in self.slides for e in s.elements if e.kind == "image")
        d = SolvedSlide.from_dict(self.slides[3].to_dict())
        self.assertEqual(next(e for e in d.elements if e.kind == "image").image["png"], img.image["png"])
        self.assertIsInstance(self.slides[3].to_dict()["elements"][-1]["image"]["png"], str)

    def test_role_validation(self):
        self.assertEqual(parse_role("s3.kpi.2"), "kpi")
        self.assertEqual(parse_role("s12.title_rule"), "title_rule")
        with self.assertRaises(ValueError):
            Element("s3.title", "text", "body", 0, 0, 1, 1)
        with self.assertRaises(ValueError):
            parse_role("title")

    def test_theme_and_grid(self):
        t = Theme.from_dict(THEME.to_dict())
        self.assertEqual(t, THEME)
        self.assertAlmostEqual(grid_x(0), 0.7)
        self.assertAlmostEqual(grid_x(12), 12.63, places=2)
        self.assertAlmostEqual(grid_x(3) + grid_w(9), 12.63, places=1)
        self.assertAlmostEqual(grid_w(12), 11.93, places=2)

    def test_shape_names_equal_ids(self):
        for sl, solved in zip(self.prs.slides, self.slides):
            self.assertEqual([sh.name for sh in sl.shapes], [e.id for e in solved.elements])

    def test_native_charts(self):
        sh = {s.name: s for s in self.prs.slides[2].shapes}["s3.chart"]
        self.assertTrue(sh.has_chart)
        self.assertEqual(sh.chart.chart_type, XL_CHART_TYPE.COLUMN_STACKED)
        names = [s.name for s in sh.chart.plots[0].series]
        self.assertEqual(names, ["Base", "Increase", "Decrease", "Total"])
        ff = {s.name: s for s in self.prs.slides[4].shapes}
        self.assertEqual(ff["s5.chart"].chart.chart_type, XL_CHART_TYPE.BAR_STACKED)
        self.assertEqual(len(ff["s5.chart.2"].chart.plots), 2)

    def test_chart_polish_label_contrast_and_formats(self):
        from om.deck.render import contrast, fmt_number, label_token, _Ctx
        cx = _Ctx(THEME)
        self.assertEqual(label_token(cx, "secondary"), "background")
        self.assertEqual(label_token(cx, "mute_bar"), "text")
        self.assertGreaterEqual(contrast("#FFFFFF", THEME.colors["secondary"]), 4.5)
        self.assertEqual(fmt_number(-3.456, '0.0"x"'), "-3.5x")
        self.assertEqual(fmt_number(0.123, "0.0%"), "12.3%")
        ch = {s.name: s for s in self.prs.slides[2].shapes}["s3.chart"].chart
        x = xml_of(ch._chartSpace)
        self.assertIn('gapWidth val="60"', x)
        self.assertIn("&#8722;", x)
        self.assertIn('w="6350"', x)

    def test_waterfall_must_foot(self):
        bad = {**WATERFALL, "series": [{"name": "x", "values": [100, 12, -8, -4, 90]}]}
        el = Element("s1.chart", "chart", "chart", 1, 1, 5, 3, chart=bad)
        with self.assertRaises(ValueError):
            render([SolvedSlide(1, "t", [el])], THEME, title="t")

    def test_no_effects_or_style(self):
        for sl in self.prs.slides:
            parts = [xml_of(sl._element)] + [xml_of(sh.chart._chartSpace) for sh in sl.shapes
                                             if getattr(sh, "has_chart", False) and sh.has_chart]
            x = "".join(parts)
            for bad in ("<p:style", "gradFill", "outerShdw", "autofit", "spAutoFit", "normAutofit"):
                self.assertNotIn(bad, x, bad)
            for eff in (e for p in parts for e in etree.fromstring(p.encode()).iter("{http://schemas.openxmlformats.org/drawingml/2006/main}effectLst")):
                self.assertEqual(len(eff), 0)

    def test_theme_fonts_and_scheme_colours(self):
        for sl in self.prs.slides:
            x = xml_of(sl._element)
            for tf in etree.fromstring(x.encode()).iter("{http://schemas.openxmlformats.org/drawingml/2006/main}latin"):
                self.assertIn(tf.get("typeface"), ("+mj-lt", "+mn-lt"))
        self.assertIn("schemeClr", xml_of(self.prs.slides[2]._element))
        z = zipfile.ZipFile(io.BytesIO(self.data))
        th = z.read("ppt/theme/theme1.xml").decode()
        for needle in ("Cambria", "Arial", "2251FF", "0B1F33", "<a:cs typeface=\"Arial\"/>"):
            self.assertIn(needle, th)
        self.assertEqual(self.prs.slide_width, 12192000)

    def test_table_house_look(self):
        tbl = {s.name: s for s in self.prs.slides[3].shapes}["s4.table"].table
        x = xml_of(tbl._tbl)
        self.assertNotIn("tableStyleId", x)
        self.assertIn('bandRow="0"', x)
        self.assertEqual(x.count("<a:lnB"), 3 * 3)
        self.assertEqual(tbl.cell(0, 0).text, "Company")
        self.assertTrue(tbl.cell(0, 0).text_frame.paragraphs[0].runs[0].font.bold)

    def test_picture_alt_and_notes(self):
        pic = {s.name: s for s in self.prs.slides[3].shapes}["s4.visual"]
        self.assertEqual(pic._element.nvPicPr.cNvPr.get("descr"), "red square")
        self.assertEqual(self.prs.slides[2].notes_slide.notes_text_frame.text, "speaker notes")

    def test_rtl(self):
        rtl = Presentation(io.BytesIO(self.rtl_data))
        x = xml_of(rtl.slides[2]._element)
        self.assertIn('rtl="1"', x)
        self.assertNotIn('rtl="1"', xml_of(self.prs.slides[2]._element))
        self.assertIn('rtl="1"', xml_of({s.name: s for s in rtl.slides[3].shapes}["s4.table"].table._tbl))
        self.assertIn("+mn-cs", x)
        self.assertTrue(self.rtl_slides[2].rtl)
        ch = {s.name: s for s in rtl.slides[2].shapes}["s3.chart"].chart
        self.assertIn('orientation val="maxMin"', xml_of(ch._chartSpace))

    def test_bindings_round_trip(self):
        self.assertEqual(read_bindings(self.data), {"s3.chart": {"manifest_id": "m1", "kind": "chart", "format": "0.0"}})
        z = zipfile.ZipFile(io.BytesIO(self.data))
        self.assertIn("http://acretia.ai/rel/bindings", z.read("ppt/_rels/presentation.xml.rels").decode())

    def test_frame_rules(self):
        s = self.slides[2]
        roles = [e.role for e in s.elements]
        for r in ("title", "title_rule", "subtitle", "source", "footer_rule", "footer", "page_number", "chart"):
            self.assertIn(r, roles)
        self.assertNotIn("eyebrow", " ".join(e.id for e in s.elements))
        title = next(e for e in s.elements if e.role == "title")
        self.assertEqual((title.x, title.y, title.text.size), (0.7, 0.5, 24))
        self.assertNotIn("page_number", [e.role for e in self.slides[0].elements])
        self.assertNotIn("title_rule", [e.role for e in self.slides[1].elements])
        src = next(e for e in s.elements if e.role == "source")
        self.assertEqual(src.text.paras[0].runs[0].t, "Source: Company filings; as of 2026-09-30")

    def test_figure_runs(self):
        runs = base.figure_runs("Price: +$12m from list, 4.0% and 12.5x or 150 bps overall")
        bold = [r.t for r in runs if r.b]
        self.assertEqual(bold, ["Price:", "+$12m", "4.0%", "12.5x", "150 bps"])
        self.assertEqual("".join(r.t for r in runs), "Price: +$12m from list, 4.0% and 12.5x or 150 bps overall")
        self.assertFalse(any(r.b for r in base.figure_runs("plain words only")))

    def test_registry(self):
        self.assertTrue({"cover", "section_divider", "chart_takeaways"} <= set(archetypes.REGISTRY))
        with self.assertRaises(KeyError) as cm:
            archetypes.get("nope")
        self.assertIn("cover", str(cm.exception))
        self.assertIn("chart", archetypes.REGISTRY["chart_takeaways"].schema["properties"])

    @unittest.skipUnless(importlib.util.find_spec("om.deck.fit"), "om.deck.fit not present")
    def test_fit_used(self):
        self.assertNotIn("fit", self.slides[2].meta)

    @unittest.skipUnless(shutil.which("soffice"), "soffice not installed")
    def test_libreoffice_converts(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "deck.pptx")
            with open(p, "wb") as fh:
                fh.write(self.data)
            r = subprocess.run(["soffice", f"-env:UserInstallation=file://{d}/profile", "--headless",
                                "--convert-to", "pdf", "--outdir", d, p], capture_output=True, timeout=240)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.getsize(os.path.join(d, "deck.pdf")) > 1000)


if __name__ == "__main__":
    unittest.main()
