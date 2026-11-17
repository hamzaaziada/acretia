"""S3.3a: text and structure archetypes (cover, divider, chart_takeaways, text.py) through render + validate."""
from __future__ import annotations

import copy
import io
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

try:
    import pptx, PIL, fontTools  # noqa
    import jsonschema
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")
from pptx import Presentation

from om.deck import archetypes
from om.deck.archetypes import BuildContext, text as text_mod
from om.deck.archetypes.core import EXAMPLES as CORE_EXAMPLES, FitFailure
from om.deck.render import render
from om.deck.theme import CANVAS_W, Theme
from om.deck.validate import validate

THEME = Theme.house()
IDS = sorted(set(CORE_EXAMPLES) | set(text_mod.EXAMPLES))
VISUAL_IDS = ["cover", "section_divider", "stat_hero", "visual_text", "appendix_divider"]
AR_TITLE = "تحسن هامش الأرباح التشغيلية إلى 21% بفضل خفض التكاليف"
AR_TEXT = "الإيرادات: نمو 8% على أساس سنوي"
AR_SHORT = "نمو 8%"
AR_COVER = "مشروع أطلس"


def png() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


VISUAL = {"png": png(), "alt": "Abstract blue shapes, no text", "style": "geometric"}


def ctx(index: int = 1, rtl: bool = False, visual: dict | None = None) -> BuildContext:
    return BuildContext(THEME, index, 3, "Project Atlas", rtl=rtl, lang="ar" if rtl else "en", visual=visual)


def arabize(spec: dict, aid: str = "") -> dict:
    """Arabic title, and the first short string inside blocks replaced by Arabic text."""
    out = copy.deepcopy(spec)
    out["title"] = AR_COVER if aid in {"cover", "section_divider", "appendix_divider"} else AR_TITLE
    done = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if done:
                    return
                if isinstance(v, str) and k in {"text", "lead", "label", "name", "title", "output", "quote"}:
                    node[k] = AR_SHORT if k in {"label", "name", "lead", "output"} else AR_TEXT
                    done.append(1)
                    return
                walk(v)
        elif isinstance(node, list):
            for v in node:
                if done:
                    return
                walk(v)
    walk(out.get("blocks", {}))
    if not done:   # blocks without such a key: put it in the first string leaf
        for k, v in out["blocks"].items():
            if isinstance(v, str):
                out["blocks"][k] = AR_TEXT
                break
    return out


def build(aid: str, spec: dict, **kw):
    return archetypes.get(aid).build(spec, ctx(**kw))


def check(case: unittest.TestCase, aid: str, spec: dict, **kw):
    slide = build(aid, spec, **kw)
    data = render([slide], THEME, title="t")
    rep = validate(data)
    bad = [f for f in rep.findings if f["severity"] in ("critical", "major")]
    case.assertEqual(bad, [], f"{aid} {kw.get('rtl')}: " + "; ".join(
        f"{f['severity']} {f['rule']} {f['shape_name']}: {f['message']}" for f in bad))
    return slide, data


class Registry(unittest.TestCase):
    def test_examples_attached(self):
        ex = archetypes.examples()
        for aid in IDS:
            self.assertIn(aid, ex)
            self.assertIs(archetypes.get(aid).example, ex[aid])
        self.assertGreaterEqual(len(text_mod.EXAMPLES), 12)
        self.assertTrue(set(text_mod.EXAMPLES) <= set(archetypes.REGISTRY))

    def test_schemas_strict_and_examples_validate(self):
        for aid in IDS:
            a = archetypes.get(aid)
            self.assertIs(a.schema.get("additionalProperties"), False, aid)
            jsonschema.validate(a.example.get("blocks", {}), a.schema)
            self.assertTrue(a.visual_type, aid)


class Examples(unittest.TestCase):
    def test_ltr_clean(self):
        for aid in IDS:
            with self.subTest(aid):
                check(self, aid, archetypes.get(aid).example)

    def test_rtl_arabic_clean(self):
        for aid in IDS:
            with self.subTest(aid):
                slide, _ = check(self, aid, arabize(archetypes.get(aid).example, aid), rtl=True)
                self.assertTrue(slide.rtl)

    def test_visual_variants_clean(self):
        for aid in VISUAL_IDS:
            for rtl in (False, True):
                with self.subTest(aid=aid, rtl=rtl):
                    spec = arabize(archetypes.get(aid).example, aid) if rtl else archetypes.get(aid).example
                    check(self, aid, spec, rtl=rtl, visual=VISUAL)

    def test_shape_names_are_element_ids_and_visual_type(self):
        for aid in IDS:
            with self.subTest(aid):
                slide, data = check(self, aid, archetypes.get(aid).example)
                names = [sh.name for sh in Presentation(io.BytesIO(data)).slides[0].shapes]
                self.assertEqual(sorted(names), sorted(e.id for e in slide.elements))
                self.assertTrue(slide.visual_type)
                self.assertEqual(slide.archetype, aid)

    def test_text_that_cannot_fit_raises(self):
        spec = copy.deepcopy(archetypes.get("kpi_row").example)
        spec["blocks"]["kpis"][0]["value"] = "$2,431,772.5 million"
        with self.assertRaises(FitFailure):
            build("kpi_row", spec)

    def test_all_in_one_deck_and_smoke_render(self):
        slides = [build(aid, archetypes.get(aid).example, index=i + 1) for i, aid in enumerate(IDS)]
        data = render(slides, THEME, title="All text archetypes")
        rep = validate(data)
        bad = [f for f in rep.findings if f["severity"] in ("critical", "major")]
        self.assertEqual(bad, [], "; ".join(f"s{f['slide']} {f['rule']} {f['message']}" for f in bad))
        soffice = shutil.which("soffice")
        if not (soffice and shutil.which("pdftoppm")):
            self.skipTest("soffice or pdftoppm not installed")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "deck.pptx")
            with open(path, "wb") as fh:
                fh.write(data)
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", d, path], check=True,
                           capture_output=True, timeout=180)
            subprocess.run(["pdftoppm", "-r", "60", "-png", os.path.join(d, "deck.pdf"), os.path.join(d, "p")],
                           check=True, capture_output=True, timeout=120)
            self.assertEqual(len([f for f in os.listdir(d) if f.endswith(".png")]), len(IDS))


class Polish(unittest.TestCase):
    def test_agenda_accent_only_on_current_item(self):
        spec = archetypes.get("agenda").example
        cur = spec["blocks"]["current"]
        slide = build("agenda", spec)
        for e in slide.elements:
            accented = bool(e.text) and (e.text.color == "accent" or any(r.color == "accent" for p in e.text.paras
                                                                          for r in p.runs))
            if accented:
                self.assertTrue(e.id.endswith(f".{cur + 1}"), f"{e.id} uses the accent but is not the current item")
        self.assertTrue(any(e.text and e.id == f"s1.body.{cur + 1}" and e.text.paras[0].runs[0].color == "accent"
                            for e in slide.elements))
        others = [e for e in slide.elements if e.id.startswith("s1.body.") and e.id != f"s1.body.{cur + 1}"]
        self.assertTrue(others and all(e.text.paras[0].runs[0].color == "muted" for e in others))
        self.assertFalse(any(e.fill == "accent" for e in slide.elements))

    def test_agenda_current_out_of_range(self):
        spec = copy.deepcopy(archetypes.get("agenda").example)
        spec["blocks"]["current"] = 9
        with self.assertRaises(ValueError):
            build("agenda", spec)

    def test_gantt_bars_on_month_columns(self):
        spec = archetypes.get("gantt").example
        months, ws = spec["blocks"]["months"], spec["blocks"]["workstreams"]
        x0, mw = text_mod.gantt_geometry(len(months))
        slide = build("gantt", spec)
        by_id = {e.id: e for e in slide.elements}
        for i, w in enumerate(ws):
            for k, bar in enumerate(w["bars"]):
                e = by_id[f"s1.decor.bar{i + 1}_{k + 1}"]
                self.assertAlmostEqual(e.x, x0 + bar["start"] * mw, delta=0.02)
                self.assertAlmostEqual(e.x + e.w, x0 + (bar["end"] + 1) * mw, delta=0.02)
            for k, ms in enumerate(w["milestones"]):
                e = by_id[f"s1.decor.ms{i + 1}_{k + 1}"]
                self.assertAlmostEqual(e.x + e.w / 2, x0 + ms["month"] * mw, delta=0.02)
        for i in range(len(months)):
            m = by_id[f"s1.decor.m{i}"]
            self.assertAlmostEqual(m.x, x0 + i * mw, delta=0.02)
        today = by_id["s1.decor.today"]
        self.assertEqual(today.kind, "line")
        self.assertAlmostEqual(today.x, x0 + spec["blocks"]["today"] * mw, delta=0.02)
        self.assertEqual(today.line[0], "accent")

    def test_gantt_bar_outside_months_rejected(self):
        spec = copy.deepcopy(archetypes.get("gantt").example)
        spec["blocks"]["workstreams"][0]["bars"][0]["end"] = 40
        with self.assertRaises(ValueError):
            build("gantt", spec)

    def test_process_flow_step_count_enforced_by_schema(self):
        a = archetypes.get("process_flow")
        steps = a.example["blocks"]["steps"]
        for n in (4, 5, 6):
            jsonschema.validate({"steps": steps[:n] if n <= len(steps) else steps}, a.schema)
            slide = build("process_flow", {"title": "Steps", "blocks": {"steps": steps[:n]}})
            self.assertEqual(len([e for e in slide.elements if e.role == "label"]), n)
        for n in (3, 7):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({"steps": (steps * 2)[:n]}, a.schema)
            with self.assertRaises(ValueError):
                build("process_flow", {"title": "Steps", "blocks": {"steps": (steps * 2)[:n]}})

    def test_recommendation_needs_three_phases(self):
        a = archetypes.get("recommendation")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({"phases": a.example["blocks"]["phases"][:2]}, a.schema)

    def test_numbered_insights_uses_no_round_cards(self):
        slide, data = check(self, "numbered_insights", archetypes.get("numbered_insights").example)
        self.assertNotIn(b"roundRect", Presentation(io.BytesIO(data)).slides[0].shapes._spTree.xml.encode())

    def test_issue_tree_uses_straight_connectors(self):
        slide = build("issue_tree", archetypes.get("issue_tree").example)
        lines = [e for e in slide.elements if e.role == "connector"]
        self.assertTrue(lines)
        self.assertTrue(all(e.kind == "line" and (e.h == 0 or e.w == 0) for e in lines))

    def test_chart_takeaways_cards_equal_and_aligned_with_chart(self):
        slide = build("chart_takeaways", archetypes.get("chart_takeaways").example)
        chart = next(e for e in slide.elements if e.role == "chart")
        panels = [e for e in slide.elements if e.role == "panel"]
        badges = [e for e in slide.elements if e.role == "badge"]
        self.assertEqual(len(panels), 3)
        self.assertEqual(len({p.h for p in panels}), 1)
        self.assertAlmostEqual(panels[0].y, chart.y, delta=0.01)
        self.assertAlmostEqual(panels[-1].y + panels[-1].h, chart.y + chart.h, delta=0.02)
        self.assertTrue(all(b.fill == "accent" and b.y == p.y and b.h == p.h for b, p in zip(badges, panels)))


class Visuals(unittest.TestCase):
    def test_visual_set_with_alt_text(self):
        for aid in VISUAL_IDS:
            with self.subTest(aid):
                slide = build(aid, archetypes.get(aid).example, visual=VISUAL)
                pics = [e for e in slide.elements if e.kind == "image"]
                self.assertEqual(len(pics), 1)
                self.assertEqual(pics[0].role, "visual")
                self.assertEqual(pics[0].image["alt"], VISUAL["alt"])
                self.assertTrue(pics[0].image["png"])

    def test_alt_text_falls_back_when_visual_has_none(self):
        slide = build("visual_text", archetypes.get("visual_text").example, visual={"png": png()})
        self.assertTrue(next(e for e in slide.elements if e.kind == "image").image["alt"])

    def test_without_visual_no_image_no_hole(self):
        for aid in VISUAL_IDS:
            with self.subTest(aid):
                slide = build(aid, archetypes.get(aid).example)
                self.assertFalse([e for e in slide.elements if e.kind == "image"])
                body = [e for e in slide.elements if e.role not in
                        ("footer", "footer_rule", "page_number", "title_rule", "subtitle", "source")]
                right = max(e.x + e.w for e in body)
                self.assertGreater(right, CANVAS_W * 0.45, f"{aid} leaves the right side empty")

    def test_full_bleed_art_panel_on_cover_and_divider(self):
        for aid in ("cover", "section_divider", "appendix_divider"):
            with self.subTest(aid):
                slide = build(aid, archetypes.get(aid).example, visual=VISUAL)
                pic = next(e for e in slide.elements if e.kind == "image")
                self.assertEqual((pic.y, pic.h), (0.0, 7.5))
                self.assertAlmostEqual(pic.x + pic.w, CANVAS_W, delta=0.02)
                self.assertGreaterEqual(pic.x, 7.0)

    def test_stat_hero_without_art_or_so_what_spreads_stats(self):
        spec = copy.deepcopy(archetypes.get("stat_hero").example)
        spec["blocks"].pop("so_what")
        slide, _ = check(self, "stat_hero", spec)
        kpis = [e for e in slide.elements if e.role == "kpi"]
        self.assertEqual(len(kpis), 2)
        self.assertNotEqual(kpis[0].x, kpis[1].x)


class ReservedKeysAndDerived(unittest.TestCase):
    """FP-S3-b: reserved spec keys (D-S3-10) and declared figures (D-S3-11) for the text archetypes."""

    def _deck(self, aid, ex):
        return {"deck_id": "d", "title": "T", "lang": "en", "as_of": "2026-09-30",
                "slides": [{"id": "s1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(ex)}]}

    def test_every_text_example_is_a_valid_spec(self):
        from om.deck import spec
        for aid in IDS:
            with self.subTest(aid):
                self.assertEqual([str(e) for e in spec.validate(self._deck(aid, archetypes.get(aid).example))], [])

    def test_two_column_compare_uses_a_and_b(self):
        from om.deck import spec
        ex = archetypes.get("two_column_compare").example
        self.assertEqual({"a", "b"} <= set(ex["blocks"]), True)
        self.assertNotIn("left", ex["blocks"])
        old = copy.deepcopy(ex)
        old["blocks"]["left"], old["blocks"]["right"] = old["blocks"].pop("a"), old["blocks"].pop("b")
        errs = spec.validate(self._deck("two_column_compare", old))
        self.assertTrue(any("left" in str(e) for e in errs))
        out = archetypes.get("two_column_compare").build(dict(ex, id="s1"), BuildContext(THEME, 1, 3, "Atlas"))
        self.assertTrue(any(e.id.endswith("label.a") for e in out.elements) and any(e.id.endswith("label.b") for e in out.elements))

    def test_agenda_declares_its_times(self):
        out = archetypes.get("agenda").build(dict(archetypes.get("agenda").example, id="s1"),
                                             BuildContext(THEME, 1, 3, "Atlas"))
        self.assertEqual(sorted(d["value"] for d in out.meta["derived"]), [10.0, 10.0, 15.0, 15.0, 25.0])

    def test_numbered_insights_figure_in_both_layouts(self):
        ex = copy.deepcopy(archetypes.get("numbered_insights").example)
        for layout, n in (("grid", 4), ("row", 3)):
            ex["blocks"]["layout"] = layout
            ex["blocks"]["insights"] = ex["blocks"]["insights"][:n]
            out = archetypes.get("numbered_insights").build(dict(ex, id="s1"), BuildContext(THEME, 1, 3, "Atlas"))
            self.assertEqual(len([e for e in out.elements if e.role == "kpi"]), n, layout)
            data = render([out], THEME, title="T")
            bad = [f for f in validate(data, theme=THEME).findings if f["severity"] in ("critical", "major")]
            self.assertEqual(bad, [], (layout, bad))


if __name__ == "__main__":
    unittest.main()
