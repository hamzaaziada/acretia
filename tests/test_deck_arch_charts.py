"""S3.3b: chart archetypes (native, data-bound), renderer chart polish, label contrast, footing, RTL."""
from __future__ import annotations

import copy
import io
import os
import shutil
import subprocess
import tempfile
import unittest

try:
    import pptx, PIL, fontTools  # noqa: F401,E401
except ImportError as e:  # clean machine without deck deps: skip, do not error
    raise unittest.SkipTest(f"deck deps missing: {e}")

from lxml import etree
from pptx import Presentation

from om.deck import archetypes
from om.deck.archetypes import BuildContext, charts
from om.deck.model import Element, SolvedSlide
from om.deck.render import MINUS, contrast, read_bindings, render
from om.deck.theme import SCHEME_SLOTS, Theme
from om.deck.validate import validate

THEME = Theme.house()
IDS = list(charts.EXAMPLES)
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_SLOT = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}
_INV = {v: k for k, v in SCHEME_SLOTS.items()}


def ctx(i: int, rtl: bool = False) -> BuildContext:
    return BuildContext(THEME, i, 20, "Project Atlas", rtl=rtl, lang="ar" if rtl else "en")


def rtl_example(aid: str) -> dict:
    ex = copy.deepcopy(archetypes.get(aid).example)
    ex["title"] = "الأرباح قبل الفوائد والضرائب ترتفع بفضل التسعير"
    ex["blocks"]["takeaway"] = "الخلاصة: التسعير والوفورات تعوّضان تضخم التكاليف بالكامل"
    return ex


def findings(data: bytes) -> list[dict]:
    return [f for f in validate(data, theme=THEME).findings if f["severity"] in ("critical", "major")]


def clr(el) -> str | None:
    if el is None:
        return None
    s = el.find(f".//{A}schemeClr")
    if s is not None:
        slot = _SLOT.get(s.get("val"), s.get("val"))
        return THEME.colors[_INV[slot]].lstrip("#")
    r = el.find(f".//{A}srgbClr")
    return r.get("val") if r is not None else None


class ChartArchetypeTests(unittest.TestCase):
    def test_registry(self):
        self.assertGreaterEqual(len(IDS), 12)
        for aid in IDS:
            a = archetypes.get(aid)
            self.assertTrue(a.data, aid)
            self.assertTrue(a.visual_type, aid)
            self.assertFalse(a.schema.get("additionalProperties", True), aid)
            self.assertIn("takeaway", a.schema["required"])
            self.assertIn("subtitle", a.schema["required"])
            self.assertIn("source", archetypes.get(aid).example)
            self.assertIn("as_of", archetypes.get(aid).example)

    def build(self, aid: str, rtl: bool = False) -> SolvedSlide:
        ex = rtl_example(aid) if rtl else archetypes.get(aid).example
        return archetypes.get(aid).build(ex, ctx(1, rtl))

    def test_each_example_clean_ltr_and_rtl(self):
        for aid in IDS:
            for rtl in (False, True):
                with self.subTest(aid=aid, rtl=rtl):
                    s = self.build(aid, rtl)
                    data = render([s], THEME, title="t")
                    bad = findings(data)
                    self.assertEqual(bad, [], f"{aid} rtl={rtl}: {bad}")
                    prs = Presentation(io.BytesIO(data))
                    self.assertEqual([sh.name for sh in prs.slides[0].shapes], [e.id for e in s.elements])
                    self.assertEqual(s.visual_type, archetypes.get(aid).visual_type)
                    self.assertEqual(s.rtl, rtl)
                    self.assertTrue(any(e.kind == "chart" for e in s.elements))

    def test_native_chart_cached_values_equal_spec(self):
        for aid in IDS:
            s = self.build(aid)
            prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
            shapes = {sh.name: sh for sh in prs.slides[0].shapes}
            for el in s.elements:
                if el.kind != "chart":
                    continue
                sh = shapes[el.id]
                self.assertTrue(sh.has_chart, aid)
                spec = el.chart
                got = [list(sr.values) for pl in sh.chart.plots for sr in pl.series]
                t = spec["type"]
                with self.subTest(aid=aid):
                    if t == "waterfall":
                        base, up, dn, tot = got[:4]
                        vals = spec["series"][0]["values"]
                        for i, v in enumerate(vals):
                            seen = [x[i] for x in (up, dn, tot) if x[i] is not None]
                            self.assertEqual(len(seen), 1)
                            self.assertAlmostEqual(seen[0], abs(v))
                    elif t == "football_field":
                        lo, w = got[0], got[1]
                        for i, (a, b) in enumerate(zip(spec["series"][0]["values"], spec["series"][1]["values"])):
                            self.assertAlmostEqual(lo[i], a)
                            self.assertAlmostEqual(lo[i] + w[i], b)
                    else:
                        for sv, g in zip(spec["series"], got):
                            self.assertEqual([None if x is None else round(float(x), 6) for x in sv["values"]],
                                             [None if x is None else round(float(x), 6) for x in g], aid)

    def test_waterfall_foots_and_rejects_bad_bridge(self):
        s = self.build("waterfall")
        vals = next(e for e in s.elements if e.kind == "chart").chart["series"][0]["values"]
        self.assertEqual(vals[0] + sum(vals[1:-1]), vals[-1])
        ex = copy.deepcopy(archetypes.get("waterfall").example)
        ex["blocks"]["steps"][-1]["value"] = 450
        with self.assertRaises(ValueError):
            archetypes.get("waterfall").build(ex, ctx(1))

    def test_waterfall_signed_labels_true_minus(self):
        s = self.build("waterfall")
        data = render([s], THEME, title="t")
        prs = Presentation(io.BytesIO(data))
        ch = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
        texts = [t.text for t in ch._chartSpace.iter(f"{A}t")]
        self.assertIn("+58", texts)
        self.assertIn(f"{MINUS}31", texts)
        self.assertNotIn("-31", texts)
        self.assertIn("444", texts)
        self.assertNotIn("+444", texts)

    def test_labels_readable_on_dark_fills(self):
        checked = 0
        specs = [self.build(a) for a in IDS]
        # also the default (labels inside) waterfall from the generic path
        wf = Element("s1.chart", "chart", "chart", 0.7, 2.0, 8.0, 4.0, chart={
            "type": "waterfall", "categories": ["A", "B", "C", "D", "E"], "labels": True, "number_format": "0",
            "series": [{"name": "x", "values": [100, 40, -30, 12, 122]}]})
        specs.append(SolvedSlide(1, "t", [wf]))
        for s in specs:
            prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
            for sh in prs.slides[0].shapes:
                if not getattr(sh, "has_chart", False) or not sh.has_chart:
                    continue
                for ser in sh.chart._chartSpace.iter(f"{C}ser"):
                    fill = clr(ser.find(f"{C}spPr/{A}solidFill"))
                    dpt = {int(d.find(f"{C}idx").get("val")): clr(d.find(f"{C}spPr/{A}solidFill"))
                           for d in ser.findall(f"{C}dPt")}
                    dls = ser.find(f"{C}dLbls")
                    if dls is None:
                        continue
                    pos = dls.find(f"{C}dLblPos")
                    inside = pos is not None and pos.get("val") == "ctr"
                    sl = clr(dls.find(f"{C}txPr"))
                    if fill and inside and sl and dls.find(f"{C}dLbl") is None:
                        bg, tx = THEME.colors["background"].lstrip("#"), THEME.colors["text"].lstrip("#")
                        need = min(4.5, max(contrast(bg, fill), contrast(tx, fill)))
                        self.assertGreaterEqual(contrast(sl, fill), need - 1e-9, f"series label {sl} on {fill}")
                        checked += 1
                    for d in dls.findall(f"{C}dLbl"):
                        pt = dpt.get(int(d.find(f"{C}idx").get("val")), fill)
                        dpos = d.find(f"{C}dLblPos")
                        if dpos is not None and dpos.get("val") in ("outEnd", "inBase", "r", "l", "t", "b"):
                            continue
                        lc = clr(d.find(f"{C}tx")) or sl
                        if pt and lc:
                            self.assertGreaterEqual(contrast(lc, pt), 4.5, f"point label {lc} on {pt}")
                            checked += 1
        self.assertGreater(checked, 8)

    def test_value_axis_hidden_on_labelled_bars_and_hairline_axis(self):
        for aid in ("ranked_bar", "paired_bars", "column_kpi", "stacked_bar"):
            s = self.build(aid)
            prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
            ch = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
            self.assertIn(ch._chartSpace.find(f".//{C}valAx/{C}delete").get("val"), (None, "1", "true"), aid)
            ln = ch._chartSpace.find(f".//{C}catAx/{C}spPr/{A}ln")
            self.assertEqual(ln.get("w"), "6350", aid)
            self.assertEqual(ch._chartSpace.find(f".//{C}gapWidth").get("val"), "60", aid)

    def test_line_end_labels_no_legend_marker_on_last_point_only(self):
        s = self.build("annotated_line")
        prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
        ch = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
        cs = ch._chartSpace
        self.assertFalse(ch.has_legend)
        for ser in cs.iter(f"{C}ser"):
            self.assertEqual(ser.find(f"{C}marker/{C}symbol").get("val"), "none")
            dpts = ser.findall(f"{C}dPt")
            self.assertEqual(len(dpts), 1)
            self.assertEqual(dpts[0].find(f"{C}idx").get("val"), "7")
            dl = ser.find(f"{C}dLbls/{C}dLbl")
            self.assertEqual(dl.find(f"{C}showSerName").get("val"), "1")
            self.assertEqual(dl.find(f"{C}idx").get("val"), "7")

    def test_scatter_labelled_points_and_median_lines(self):
        s = self.build("scatter_quadrant")
        el = next(e for e in s.elements if e.kind == "chart")
        names = el.chart["categories"]
        prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
        ch = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
        xml = etree.tostring(ch._chartSpace).decode()
        for n in names:
            self.assertIn(n, xml)
        pts = el.chart["series"][0]
        self.assertAlmostEqual(el.chart["series"][1]["values"][0], sorted(pts["values"])[len(pts["values"]) // 2])
        self.assertEqual(len(list(ch.plots[0].series)), 3)

    def test_combo_secondary_axis(self):
        s = self.build("combo_margin")
        prs = Presentation(io.BytesIO(render([s], THEME, title="t")))
        ch = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
        self.assertEqual(len(ch._chartSpace.findall(f".//{C}valAx")), 2)
        self.assertEqual(len(ch.plots), 2)

    def test_bindings_pass_through(self):
        for aid, expect in (("ranked_bar", "m-peer-ev-ebitda"), ("waterfall", "m-ebitda-bridge"),
                            ("annotated_line", "m-nim"), ("combo_margin", "m-revenue")):
            s = self.build(aid)
            el = next(e for e in s.elements if e.kind == "chart")
            self.assertEqual(el.binding, {"manifest_id": expect, "kind": "chart"}, aid)
            self.assertEqual(read_bindings(render([s], THEME, title="t"))[el.id]["manifest_id"], expect)
        self.assertIsNone(next(e for e in self.build("stacked_bar").elements if e.kind == "chart").binding)

    def test_house_rules(self):
        for aid in IDS:
            s = self.build(aid)
            roles = [e.role for e in s.elements]
            for r in ("title", "title_rule", "subtitle", "source", "footer", "page_number", "chart"):
                self.assertIn(r, roles, aid)
            self.assertTrue(any(e.role == "callout" or e.role == "badge" for e in s.elements), aid)
            sub = next(e for e in s.elements if e.role == "subtitle")
            self.assertTrue(sub.text.paras[0].runs[0].b, aid)
            for e in s.elements:
                if e.kind == "chart":
                    self.assertFalse(e.chart["legend"], aid)
                    self.assertFalse(e.chart["gridlines"], aid)

    def test_bad_input_raises(self):
        with self.assertRaises(ValueError):
            archetypes.get("ranked_bar").build({"title": "x", "blocks": {"subtitle": "s"}}, ctx(1))
        ex = copy.deepcopy(archetypes.get("ranked_bar").example)
        del ex["source"]
        with self.assertRaises(ValueError):
            archetypes.get("ranked_bar").build(ex, ctx(1))

    def test_all_examples_one_deck_and_libreoffice_smoke(self):
        slides = [archetypes.get(a).build(archetypes.get(a).example, ctx(i + 1)) for i, a in enumerate(IDS)]
        data = render(slides, THEME, title="charts")
        self.assertEqual(findings(data), [])
        if not shutil.which("soffice"):
            self.skipTest("soffice not installed")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "deck.pptx")
            with open(p, "wb") as fh:
                fh.write(data)
            r = subprocess.run(["soffice", f"-env:UserInstallation=file://{d}/profile", "--headless",
                                "--convert-to", "pdf", "--outdir", d, p], capture_output=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreater(os.path.getsize(os.path.join(d, "deck.pdf")), 1000)
            if shutil.which("pdftoppm"):
                subprocess.run(["pdftoppm", "-r", "60", "-png", os.path.join(d, "deck.pdf"), os.path.join(d, "p")],
                               capture_output=True, timeout=300)
                self.assertTrue([f for f in os.listdir(d) if f.endswith(".png")])


class ReservedKeysAndDerived(unittest.TestCase):
    """FP-S3-b: scatter coordinates are xv/yv (D-S3-10); computed badge and stat figures are declared (D-S3-11)."""

    def test_every_chart_example_is_a_valid_spec(self):
        from om.deck import spec
        for aid in IDS:
            d = {"deck_id": "d", "title": "T", "lang": "en", "as_of": "2026-09-30",
                 "slides": [{"id": "s1", "archetype": aid, "blocks": {}, "title": "Example",
                             **copy.deepcopy(archetypes.get(aid).example)}]}
            with self.subTest(aid):
                self.assertEqual([str(e) for e in spec.validate(d)], [])

    def test_scatter_points_use_xv_yv(self):
        ex = archetypes.get("scatter_quadrant").example
        self.assertTrue(all({"xv", "yv"} <= set(p) and "x" not in p and "y" not in p for p in ex["blocks"]["points"]))
        out = archetypes.get("scatter_quadrant").build(copy.deepcopy(dict(ex, id="s1")), ctx(1))
        self.assertTrue(any(e.kind == "chart" for e in out.elements))

    def test_computed_figures_are_declared(self):
        def derived(aid):
            out = archetypes.get(aid).build(copy.deepcopy(dict(archetypes.get(aid).example, id="s1")), ctx(1))
            return [d["value"] for d in out.meta.get("derived", [])]
        wf = derived("waterfall")
        self.assertTrue(any(abs(v - 32) < 1e-9 for v in wf))                       # EBITDA delta in the badge
        self.assertTrue(any(abs(v - 0.37) < 1e-9 for v in derived("annotated_line")))
        self.assertTrue(any(abs(v - 4.2) < 1e-9 for v in derived("combo_margin")))
        self.assertTrue(any(abs(v - 158) < 1 for v in derived("football_field")))   # implied value per share

    def test_markers_and_sources_in_examples_resolve(self):
        import re
        for aid in IDS:
            ex = archetypes.get(aid).example
            marks = {int(m) for m in re.findall(r"\[(\d)\]", str(ex["blocks"]))}
            self.assertLessEqual(max(marks, default=0), len(ex.get("sources", [])), aid)


if __name__ == "__main__":
    unittest.main()
