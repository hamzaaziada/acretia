"""S3.3c: tables and framework archetypes (frameworks.py)."""
from __future__ import annotations

import copy
import io
import os
import shutil
import statistics
import subprocess
import tempfile
import unittest

try:
    import pptx, PIL, fontTools  # noqa
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

from pptx import Presentation

from om.deck import archetypes
from om.deck.archetypes import BuildContext, frameworks
from om.deck.render import render
from om.deck.theme import Theme
from om.deck.validate import validate

THEME = Theme.house()
IDS = ["comparison_table", "comps_table", "sensitivity_table", "matrix_2x2", "market_map", "tombstones",
       "harvey_table", "risk_heatmap", "deal_structure", "timeline_milestones", "scorecard"]
TABLE_IDS = {"comparison_table", "comps_table", "sensitivity_table", "harvey_table", "scorecard"}
AR_TITLE = "الخيار الثاني يحقق أعلى قيمة بأقل مخاطر تنفيذ"


def ctx(i=1, rtl=False, dense=False) -> BuildContext:
    return BuildContext(THEME, i, 12, "Project Atlas", rtl=rtl, lang="ar" if rtl else "en", dense=dense)


def example(aid: str) -> dict:
    return copy.deepcopy(frameworks.EXAMPLES[aid])


def arabic_variant(aid: str) -> dict:
    ex = example(aid)
    ex["title"] = AR_TITLE
    b = ex["blocks"]
    if aid in ("comparison_table", "comps_table", "sensitivity_table", "scorecard", "harvey_table"):
        b["subtitle"] = "القيمة والمخاطر، مليار دولار"
    if aid == "comparison_table":
        b["rows"][0]["criterion"] = "قيمة حقوق الملكية"
    elif aid == "comps_table":
        b["rows"][0]["company"] = "شركة الشرق للأنظمة"
    elif aid == "sensitivity_table":
        b["col_label"] = "النمو النهائي"
    elif aid == "matrix_2x2":
        b["quadrants"][1] = "نفذ الآن"
    elif aid == "market_map":
        b["segments"][0]["name"] = "الاستحواذ"
    elif aid == "tombstones":
        b["deals"][0]["target"] = "نيوين"
    elif aid == "harvey_table":
        b["capabilities"][0]["name"] = "اتساع المنتجات"
    elif aid == "risk_heatmap":
        b["risks"][0]["label"] = "تأخر الموافقة التنظيمية لأكثر من 9 أشهر"
    elif aid == "deal_structure":
        b["entities"][0]["label"] = "صندوق الراعي"
    elif aid == "timeline_milestones":
        b["milestones"][0]["label"] = "توقيع التفويض"
    elif aid == "scorecard":
        b["kpis"][0]["name"] = "الإيرادات"
    return ex


def build(aid: str, spec: dict, rtl=False, i=1):
    return archetypes.get(aid).build(spec, ctx(i, rtl))


def findings_of(slides) -> list[dict]:
    rep = validate(render(slides, THEME, title="Frameworks"), theme=THEME)
    return [f for f in rep.findings if f["severity"] in ("critical", "major")]


def table_geometry(prs_slide, name):
    sh = {s.name: s for s in prs_slide.shapes}[name]
    xs = [sh.left / 914400]
    for c in sh.table.columns:
        xs.append(xs[-1] + c.width / 914400)
    ys = [sh.top / 914400]
    for r in sh.table.rows:
        ys.append(ys[-1] + r.height / 914400)
    return sh, xs, ys


class FrameworkArchetypeTests(unittest.TestCase):
    def test_registered_with_examples(self):
        self.assertGreaterEqual(len(IDS), 11)
        for aid in IDS:
            a = archetypes.get(aid)
            self.assertIn(aid, frameworks.EXAMPLES)
            self.assertEqual(a.schema.get("additionalProperties"), False, aid)
            self.assertEqual(a.data, aid in TABLE_IDS | {"tombstones", "risk_heatmap"}, aid)
            self.assertEqual(archetypes.examples().get(aid), frameworks.EXAMPLES[aid])

    def test_examples_clean_ltr_and_rtl(self):
        for rtl in (False, True):
            for aid in IDS:
                with self.subTest(aid=aid, rtl=rtl):
                    spec = arabic_variant(aid) if rtl else example(aid)
                    s = build(aid, spec, rtl=rtl)
                    self.assertEqual(s.archetype, aid)
                    self.assertEqual(s.visual_type, archetypes.get(aid).visual_type)
                    self.assertEqual(s.rtl, rtl)
                    bad = findings_of([s])
                    self.assertEqual(bad, [], "\n".join(f"{f['severity']} {f['rule']} {f['shape_name']}: {f['message']}"
                                                        for f in bad))
                    prs = Presentation(io.BytesIO(render([s], THEME, title="x")))
                    self.assertEqual([sh.name for sh in prs.slides[0].shapes], [e.id for e in s.elements])

    def test_house_rules(self):
        for aid in IDS:
            s = build(aid, example(aid))
            roles = [e.role for e in s.elements]
            for r in ("title", "title_rule", "subtitle", "footer_rule", "page_number"):
                self.assertIn(r, roles, aid)
            self.assertLessEqual(sum(1 for e in s.elements if e.kind == "rect" and e.id.count("roundRect")), 2)
            sizes = {e.text.size for e in s.elements if e.text} | {e.table["size"] for e in s.elements if e.table}
            self.assertLessEqual(len(sizes), 4, (aid, sizes))
            if aid in TABLE_IDS:
                self.assertTrue(any(e.kind == "table" for e in s.elements))
                self.assertTrue(any(e.role == "callout" for e in s.elements), "so-what")
            if aid in TABLE_IDS | {"tombstones", "risk_heatmap"}:
                self.assertTrue(example(aid).get("source") and example(aid).get("as_of"))
                self.assertIn("source", roles)

    def test_all_examples_one_deck_and_smoke(self):
        slides = [build(aid, example(aid), i=i + 1) for i, aid in enumerate(IDS)]
        data = render(slides, THEME, title="Frameworks")
        rep = validate(data, theme=THEME)
        self.assertEqual([f for f in rep.findings if f["severity"] in ("critical", "major")], [])
        soffice, ppm = shutil.which("soffice"), shutil.which("pdftoppm")
        if not (soffice and ppm):
            self.skipTest("soffice or pdftoppm not installed")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.pptx")
            with open(p, "wb") as fh:
                fh.write(data)
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", d, p], check=True,
                           capture_output=True, timeout=240)
            subprocess.run([ppm, "-r", "60", "-png", os.path.join(d, "f.pdf"), os.path.join(d, "pg")], check=True,
                           capture_output=True, timeout=120)
            self.assertEqual(len([f for f in os.listdir(d) if f.endswith(".png")]), len(IDS))

    def test_strict_schema_rejects_unknown_keys(self):
        for aid in IDS:
            sch = archetypes.get(aid).schema
            self.assertFalse(sch["additionalProperties"])
            self.assertIn("subtitle", sch["properties"])

    # ------------------------------------------------------------ specifics
    def test_sensitivity_base_outline_on_base_cell(self):
        spec = example("sensitivity_table")
        for rtl in (False, True):
            s = build("sensitivity_table", spec, rtl=rtl)
            prs = Presentation(io.BytesIO(render([s], THEME, title="x")))
            slide = prs.slides[0]
            tbl, xs, ys = table_geometry(slide, "s1.table")
            out = {sh.name: sh for sh in slide.shapes}["s1.decor.base"]
            bi, bj = spec["blocks"]["base"]
            c = bj + 1
            widths = [b - a for a, b in zip(xs, xs[1:])]
            if rtl:
                cx1 = xs[-1] - sum(widths[:c])
                cx0 = cx1 - widths[c]
            else:
                cx0, cx1 = xs[c], xs[c + 1]
            cy0, cy1 = ys[bi + 1], ys[bi + 2]
            self.assertAlmostEqual(out.left / 914400, cx0, delta=0.03, msg=f"rtl={rtl}")
            self.assertAlmostEqual((out.left + out.width) / 914400, cx1, delta=0.03)
            self.assertAlmostEqual(out.top / 914400, cy0, delta=0.03)
            self.assertAlmostEqual((out.top + out.height) / 914400, cy1, delta=0.03)
            self.assertEqual(tbl.table.cell(bi + 1, bj + 1).text, "$53.80")
            xml = out._element.xml
            self.assertIn("accent1", xml)
            self.assertIn("noFill", xml)

    def test_comps_median_mean_computed(self):
        spec = example("comps_table")
        rows = spec["blocks"]["rows"]
        spec["blocks"]["rows"][0]["pe"] = None  # a missing value is ignored by the statistics
        s = build("comps_table", spec)
        tbl = next(e for e in s.elements if e.kind == "table").table["rows"]
        med, mean = tbl[-2], tbl[-1]
        self.assertEqual(med[0], "Median")
        self.assertEqual(mean[0], "Mean")
        ev = [r["ev_ebitda"] for r in rows]
        pe = [r["pe"] for r in rows if r["pe"] is not None]
        self.assertEqual(med[2], f"{statistics.median(ev):.1f}x")
        self.assertEqual(mean[2], f"{statistics.fmean(ev):.1f}x")
        self.assertEqual(med[3], f"{statistics.median(pe):.1f}x")
        self.assertEqual(mean[3], f"{statistics.fmean(pe):.1f}x")
        self.assertEqual(med[5], f"{statistics.median([r['margin'] for r in rows]):.1f}%")
        self.assertEqual(tbl[0][3], "n.a.")
        spec_t = next(e for e in s.elements if e.kind == "table").table
        self.assertEqual(spec_t["bold_rows"], [len(tbl) - 2, len(tbl) - 1])
        self.assertEqual(spec_t["col_align"], ["l"] + ["r"] * 5)
        st = frameworks.comps_stats([{"ev": 1, "ev_ebitda": 2.0, "pe": 3, "growth": 4, "margin": 5},
                                     {"ev": 3, "ev_ebitda": 4.0, "pe": 5, "growth": 6, "margin": 7},
                                     {"ev": 8, "ev_ebitda": 9.0, "pe": 1, "growth": 2, "margin": 3}])
        self.assertEqual(st["median"]["ev"], 3)
        self.assertAlmostEqual(st["mean"]["ev_ebitda"], 5.0)

    def test_comps_stats_required_without_compute(self):
        spec = example("comps_table")
        spec["blocks"]["compute_stats"] = False
        with self.assertRaises(ValueError):
            build("comps_table", spec)
        spec["blocks"]["median"] = {"ev": 5.0, "ev_ebitda": 11.0, "pe": 17.0, "growth": 6.0, "margin": 22.0}
        spec["blocks"]["mean"] = {"ev": 6.0, "ev_ebitda": 12.0, "pe": 18.0, "growth": 6.5, "margin": 22.5}
        s = build("comps_table", spec)
        self.assertEqual(next(e for e in s.elements if e.kind == "table").table["rows"][-2][2], "11.0x")

    def test_dense_comps_allows_ten_point(self):
        spec = example("comps_table")
        spec["blocks"]["rows"] = spec["blocks"]["rows"] + spec["blocks"]["rows"][:2]
        spec["blocks"]["dense"] = False
        with self.assertRaises(ValueError):
            build("comps_table", spec)
        spec["blocks"]["dense"] = True
        s = build("comps_table", spec)
        self.assertEqual(next(e for e in s.elements if e.kind == "table").table["size"], 10)
        self.assertEqual(findings_of([s]), [])

    def test_table_bindings_passed_through(self):
        spec = example("scorecard")
        spec["blocks"]["bindings"] = {"0,2": "m_rev_q3", "1,5": "m_margin_q3"}
        spec["blocks"]["bindings_format"] = "0.0"
        s = build("scorecard", spec)
        el = next(e for e in s.elements if e.kind == "table")
        self.assertEqual(el.binding, {"kind": "table", "bindings": {"0,2": "m_rev_q3", "1,5": "m_margin_q3"},
                                      "header_rows": 1, "format": "0.0"})
        from om.deck.render import read_bindings
        self.assertEqual(read_bindings(render([s], THEME, title="x"))["s1.table"]["bindings"]["0,2"], "m_rev_q3")

    def test_comparison_highlight_and_verdict(self):
        s = build("comparison_table", example("comparison_table"))
        t = next(e for e in s.elements if e.kind == "table").table
        self.assertEqual(t["highlight_col"], 2)
        self.assertEqual(t["bold_rows"], [len(t["rows"]) - 1])
        self.assertEqual(t["rows"][-1][0], "Verdict")
        rule = next(e for e in s.elements if e.id == "s1.rule.highlight")
        self.assertEqual(rule.line[0], "accent")
        self.assertLess(rule.line[1], 3)

    def test_harvey_ball_fill_fraction(self):
        for v in (0, 0.25, 0.5, 0.75, 1):
            ch = frameworks.harvey_chart(v)
            self.assertEqual(ch["type"], "pie")
            self.assertAlmostEqual(ch["series"][0]["values"][0], v)
            self.assertAlmostEqual(sum(ch["series"][0]["values"]), 1.0)
        spec = example("harvey_table")
        spec["blocks"]["capabilities"][0]["values"] = [0, 0.25, 0.5, 0.75]
        s = build("harvey_table", spec)
        prs = Presentation(io.BytesIO(render([s], THEME, title="x")))
        shapes = {sh.name: sh for sh in prs.slides[0].shapes}
        for c, v in enumerate([0, 0.25, 0.5, 0.75], 1):
            sh = shapes[f"s1.decor.ball1_{c}"]
            self.assertTrue(sh.has_chart)
            vals = list(sh.chart.plots[0].series[0].values)
            self.assertAlmostEqual(vals[0] / (vals[0] + vals[1]), v, places=3)
        full = list(shapes["s1.decor.ball2_1"].chart.plots[0].series[0].values)
        self.assertEqual(full, [1.0, 0.0])

    def test_scorecard_markers_use_semantic_tokens(self):
        s = build("scorecard", example("scorecard"))
        marks = {e.id: e for e in s.elements if e.role == "decor"}
        # revenue up and good, leverage down and good, churn up and bad, backlog down and bad
        runs = {k: (v.text.paras[0].runs[0].t, v.text.paras[0].runs[0].color) for k, v in marks.items()}
        self.assertEqual(runs["s1.decor.change1"], ("▲", "positive"))
        self.assertEqual(runs["s1.decor.change3"], ("▼", "positive"))
        self.assertEqual(runs["s1.decor.change4"], ("▲", "negative"))
        self.assertEqual(runs["s1.decor.change5"], ("▼", "negative"))
        txt, d = frameworks.kpi_change([23.1, 24.0], "pct")
        self.assertEqual((txt, d), ("+0.9 pp", 1))
        self.assertEqual(frameworks.kpi_change([100, 90], "usd_m"), ("−10.0%", -1))

    def test_matrix_target_tinted_and_dots_in_bounds(self):
        s = build("matrix_2x2", example("matrix_2x2"))
        quads = [e for e in s.elements if e.role == "quadrant"]
        self.assertEqual([q.fill for q in quads], [None, "panel", None, None])
        dots = [e for e in s.elements if e.id.startswith("s1.decor.item")]
        self.assertEqual(len(dots), 6)
        for d in dots:
            self.assertGreaterEqual(d.x, 0.7)
            self.assertLessEqual(d.x + d.w, 12.65)

    def test_market_map_chips_square_and_client_accent(self):
        s = build("market_map", example("market_map"))
        chips = [e for e in s.elements if e.role == "chip"]
        self.assertEqual(sum(1 for c in chips if c.fill == "accent"), 3)
        prs = Presentation(io.BytesIO(render([s], THEME, title="x")))
        self.assertNotIn("roundRect", prs.slides[0].shapes._spTree.xml)

    def test_tombstones_square_panels(self):
        s = build("tombstones", example("tombstones"))
        prs = Presentation(io.BytesIO(render([s], THEME, title="x")))
        self.assertLessEqual(prs.slides[0].shapes._spTree.xml.count("roundRect"), 2)
        self.assertEqual(len([e for e in s.elements if e.role == "tombstone"]), 6)

    def test_deal_structure_connectors_orthogonal(self):
        s = build("deal_structure", example("deal_structure"))
        conns = [e for e in s.elements if e.role == "connector"]
        self.assertGreaterEqual(len(conns), 8)
        for c in conns:
            self.assertTrue(c.w == 0 or c.h == 0, c.id)
        labels = [e.text.paras[0].runs[0].t for e in s.elements if e.id.startswith("s1.decor.pct")]
        self.assertEqual(labels, ["70%", "30%", "100%", "100%"])

    def test_risk_heatmap_cells_and_dots(self):
        s = build("risk_heatmap", example("risk_heatmap"))
        cells = [e for e in s.elements if e.id.startswith("s1.decor.cell")]
        self.assertEqual(len(cells), 25)
        self.assertEqual({c.fill for c in cells}, {"panel", "key_message", "light", "series2"})
        self.assertEqual(len([e for e in s.elements if e.id.startswith("s1.decor.dot")]), 6)

    def test_timeline_alternates_above_below(self):
        s = build("timeline_milestones", example("timeline_milestones"))
        axis = next(e for e in s.elements if e.role == "axis")
        labels = [e for e in s.elements if e.id.startswith("s1.decor.label")]
        side = [e.y < axis.y for e in labels]
        self.assertEqual(side, [True, False, True, False, True, False])
        self.assertEqual(len([e for e in s.elements if e.id.startswith("s1.decor.diamond")]), 6)

    def test_missing_takeaway_and_bad_shapes_raise(self):
        spec = example("scorecard")
        del spec["blocks"]["takeaway"]
        with self.assertRaises(ValueError):
            build("scorecard", spec)
        spec = example("market_map")
        spec["blocks"]["segments"] = spec["blocks"]["segments"] + [copy.deepcopy(spec["blocks"]["segments"][0])] * 2
        with self.assertRaises(ValueError):
            build("market_map", spec)


if __name__ == "__main__":
    unittest.main()
