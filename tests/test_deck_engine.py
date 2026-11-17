"""Deck engine entry point (S3.int): end-to-end build, provenance, determinism, ghost gate, telemetry, CLI. Offline."""
import unittest

try:
    import pptx, PIL, fontTools  # noqa: F401,E401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

import copy
import io
import json
import os
import socket
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.contracts import Job  # noqa: E402
from om.deck import archetypes, engine, provenance  # noqa: E402
from om.deck import ghost as G  # noqa: E402
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec  # noqa: E402


def _chart(kind, cats, vals, name="Revenue"):
    return {"type": kind, "categories": cats, "series": [{"name": name, "values": vals}]}


def spec6(lang="en") -> dict:
    ar = lang == "ar"
    t = (lambda en, a: a if ar else en)
    return {
        "deck_id": "atlas-" + lang, "title": t("Project Atlas board update", "تحديث مجلس الإدارة لمشروع أطلس"),
        "lang": lang, "client": "Acme Bank", "as_of": "2026-09-30", "art_direction": "auto", "theme": "house",
        "slides": [
            {"id": "s1", "archetype": "cover", "title": t("Project Atlas board update", "تحديث مجلس الإدارة لمشروع أطلس"),
             "blocks": {"client": "Acme Bank", "date": "2026-09-30"}, "as_of": "2026-09-30",
             "visual": {"concept": "a bridge between two banks", "kind": "illustration"}},
            {"id": "s2", "archetype": "chart_takeaways", "title": t("Revenue grew to 4.7bn on stronger lending", "نمت الإيرادات إلى 4.7 مليار"),
             "source": "Company filings", "as_of": "2026-09-30",
             "blocks": {"subtitle": t("Revenue, $ billion", "الإيرادات، مليار دولار"),
                        "chart": _chart("column", ["FY23", "FY24", "FY25"], [3.9, 4.2, 4.7]),
                        "takeaways": [t("Revenue: 4.7bn in FY25", "الإيرادات: 4.7 مليار"),
                                      t("FY24: 4.2bn base year", "السنة السابقة: 4.2 مليار"),
                                      t("FY23: 3.9bn starting point", "البداية: 3.9 مليار")]}},
            {"id": "s3", "archetype": "section_divider", "title": t("Valuation and returns", "التقييم والعوائد"),
             "blocks": {"number": 2}},
            {"id": "s4", "archetype": "chart_takeaways", "title": t("Margin held at 31% through the cycle", "الهامش ثابت عند 31%"),
             "source": "Company filings", "as_of": "2026-09-30",
             "blocks": {"subtitle": t("EBITDA margin, %", "هامش الأرباح، %"),
                        "chart": _chart("line", ["FY23", "FY24", "FY25"], [29, 30, 31], "Margin"),
                        "takeaways": [t("FY25 margin: 31%", "هامش السنة: 31%"), t("FY24 margin: 30%", "هامش السابقة: 30%"),
                                      t("FY23 margin: 29%", "هامش الأولى: 29%")]}},
            {"id": "s5", "archetype": "chart_takeaways", "title": t("Costs fell to 48 points of income", "التكاليف عند 48 نقطة"),
             "source": "Company filings", "as_of": "2026-09-30",
             "blocks": {"subtitle": t("Cost to income, %", "التكلفة إلى الدخل، %"),
                        "chart": _chart("bar", ["FY24", "FY25"], [52, 48], "Cost to income"),
                        "takeaways": [t("FY25: 48% cost to income", "السنة: 48%"), t("FY24: 52% cost to income", "السابقة: 52%"),
                                      t("Cost to income improved year on year", "تحسنت التكلفة إلى الدخل")]}},
            {"id": "s6", "archetype": "section_divider", "title": t("Appendix", "الملحق"), "blocks": {}},
        ],
    }


class NoNetwork(unittest.TestCase):
    """Every socket creation raises for the whole class: the engine must be fully offline without an adapter."""

    @classmethod
    def setUpClass(cls):
        def boom(*a, **k):
            raise AssertionError("network used")
        cls._p = mock.patch.object(socket, "socket", boom)
        cls._p.start()
        cls._d = tempfile.TemporaryDirectory()
        cls._e = mock.patch.dict(os.environ, {"ACRETIA_DATA": cls._d.name, "ACRETIA_LLM_MODE": "",
                                              "OM_IMAGE_MODEL": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""})
        cls._e.start()

    @classmethod
    def tearDownClass(cls):
        cls._e.stop()
        cls._p.stop()
        cls._d.cleanup()

    def out(self, name="deck.pptx") -> str:
        return str(Path(self._d.name) / name)


class Build(NoNetwork):
    def test_six_slides_end_to_end(self):
        t0 = time.perf_counter()
        r = engine.build(spec6(), out=self.out("six.pptx"), seed=7)
        dt = time.perf_counter() - t0
        print(f"\n[engine] 6-slide build: {dt:.2f} s (report total {r.total_seconds} s)")
        crit = [f for f in r.findings if f["severity"] == "critical"]
        self.assertEqual(crit, [], crit)
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.slides, 6)
        self.assertTrue(Path(r.path).stat().st_size > 10_000)
        self.assertEqual(r.critical, 0)
        self.assertFalse(r.image_probe["available"])
        self.assertTrue(r.art_direction)
        self.assertEqual(r.critic, "critic: not run live")
        self.assertEqual(r.tokens, 0)
        self.assertEqual(r.cost_usd, 0)
        self.assertEqual(len(r.numbers_digest), 64)

    def test_registry_examples_build(self):
        """FP-S3-b: every registered archetype's example builds (cover + one slide) with 0 critical findings of any rule
        (spec, unsourced_number, citation, validator) and at most 1 major finding on the example slide."""
        from om.deck import spec as specmod
        ids = sorted(archetypes.examples())
        self.assertEqual(set(ids), set(archetypes.REGISTRY), "every archetype must ship an example")
        self.assertGreaterEqual(len(ids), 40)
        for aid in ids:
            sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(archetypes.examples()[aid])}
            slides = [sl] if aid == "cover" else [
                {"id": "c0", "archetype": "cover", "title": "Examples", "blocks": {"client": "Acme", "date": "2026-09-30"},
                 "as_of": "2026-09-30"}, sl]
            d = {"deck_id": "ex", "title": "Examples", "lang": "en", "as_of": "2026-09-30", "slides": slides}
            with self.subTest(archetype=aid):
                errs = specmod.validate(d)
                self.assertEqual(errs, [], [str(e) for e in errs])
                r = engine.build(d, out=self.out("ex.pptx"), seed=1, critic=False)
                idx = len(slides)
                crit = [f for f in r.findings if f["severity"] == "critical"]
                major = [f for f in r.findings if f["severity"] == "major" and f["slide"] == idx]
                show = "\n".join(f"  {f['severity']} {f['rule']} slide {f['slide']}: {f['message']}" for f in r.findings)
                self.assertEqual(crit, [], f"{aid}: critical findings\n{show}")
                self.assertLessEqual(len(major), 1, f"{aid}: more than one major finding\n{show}")
                self.assertTrue(r.ok, r.error)

    def test_arabic_rtl(self):
        r = engine.build(spec6("ar"), out=self.out("ar.pptx"), seed=3)
        self.assertEqual([f for f in r.findings if f["severity"] == "critical"], [])
        import zipfile
        z = zipfile.ZipFile(r.path)
        xml = z.read("ppt/slides/slide2.xml").decode("utf-8")
        self.assertIn('rtl="1"', xml)

    def test_timings_and_job(self):
        r = engine.build(spec6(), out=self.out("job.pptx"), seed=1, job_id="job-1")
        for k in ("spec_validate", "image_probe", "art_direction", "visuals", "build", "variety", "provenance", "render",
                  "validate", "critic", "write"):
            self.assertIn(k, r.timings)
        job = Job.from_dict(r.job)
        job.validate()
        self.assertEqual(job.id, "job-1")
        self.assertEqual(job.status, "succeeded")
        self.assertTrue(all("ms" in s.detail for s in job.steps))
        d = r.to_dict()
        json.dumps(d, default=str)
        self.assertNotIn("data", d)

    def test_spec_error_fails_run(self):
        d = spec6()
        d["slides"][1]["blocks"]["chart"]["series"][0]["values"] = "nope"
        r = engine.build(d, out=self.out("bad.pptx"))
        self.assertFalse(r.ok)
        self.assertTrue(any(f["rule"] == "spec" for f in r.findings))
        self.assertEqual(Job.from_dict(r.job).status, "failed")

    def test_fit_failure_is_structured_and_strict_flag(self):
        d = spec6()
        d["slides"][1]["blocks"]["takeaways"][0] = " ".join(["word"] * 200)
        r = engine.build(d, out=self.out("fit.pptx"))
        self.assertFalse(r.ok)
        self.assertTrue(r.failed_slides)
        self.assertEqual(r.failed_slides[0]["id"], "s2")
        self.assertIn("cut or split", " ".join(f["message"] for f in r.findings))
        r2 = engine.build(d, out=self.out("fit2.pptx"), strict=False)
        self.assertEqual(r2.slides, 5)
        self.assertTrue(Path(r2.path).exists())


class Determinism(NoNetwork):
    def test_same_numbers_different_visuals(self):
        a = engine.build(spec6(), out=self.out("a.pptx"), seed=1)
        b = engine.build(spec6(), out=self.out("b.pptx"), seed=2)
        c = engine.build(spec6(), out=self.out("c.pptx"), seed=1)
        self.assertEqual(a.numbers_digest, b.numbers_digest)
        self.assertEqual(a.numbers_digest, c.numbers_digest)
        ha = [v["kept"]["png_sha256"] for v in a.visuals]
        hb = [v["kept"]["png_sha256"] for v in b.visuals]
        hc = [v["kept"]["png_sha256"] for v in c.visuals]
        self.assertTrue(ha)
        self.assertNotEqual(ha, hb)
        self.assertEqual(ha, hc)
        self.assertEqual(a.art_direction, c.art_direction)

    def test_different_data_different_digest(self):
        d = spec6()
        d["slides"][1]["blocks"]["chart"]["series"][0]["values"][2] = 4.8
        d["slides"][1]["blocks"]["takeaways"][0] = "Revenue: 4.8bn in FY25"
        self.assertNotEqual(engine.build(spec6(), seed=1).numbers_digest, engine.build(d, seed=1).numbers_digest)


class Provenance(NoNetwork):
    def test_unsourced_number_in_takeaway_is_critical(self):
        d = spec6()
        d["slides"][1]["blocks"]["takeaways"][1] = "FY24: 4.2bn base year, up 99% on peers"
        r = engine.build(d, out=self.out("prov.pptx"), seed=1)
        hits = [f for f in r.findings if f["rule"] == "unsourced_number"]
        self.assertEqual(len(hits), 1, hits)
        self.assertEqual(hits[0]["severity"], "critical")
        self.assertEqual(hits[0]["shape_name"], "s2.callout.2")
        self.assertIn("s2.callout.2", hits[0]["message"])
        self.assertIn("99%", hits[0]["message"])
        self.assertFalse(r.ok)

    def test_unsourced_number_in_title(self):
        d = spec6()
        d["slides"][3]["title"] = "Margin held at 44% through the cycle"
        hits = [f for f in engine.build(d, seed=1).findings if f["rule"] == "unsourced_number"]
        self.assertEqual([h["shape_name"] for h in hits], ["s4.title"])

    def _slide(self, text, idx=1, role="body"):
        el = Element(f"s{idx}.{role}", "text", role, 1, 1, 5, 1, text=TextSpec([Para([Run(text)])], 14))
        return SolvedSlide(idx, "x", [el])

    def test_format_equivalence(self):
        sp = {"slides": [{"id": "a", "source": "S", "blocks": {"kpis": [{"label": "Rev", "value": "$1.1bn"}],
                                                               "margin": 0.38, "multiple": "12.5x"}}]}
        for text in ("1,100 m", "1100", "$1.1bn", "38%", "12.5x", "0.38", "Revenue of $1.1bn, 38% margin at 12.5x"):
            self.assertEqual(provenance.check(sp, [self._slide(text)]), [], text)
        for text in ("$1.3bn", "41%", "12.9x"):
            self.assertEqual(len(provenance.check(sp, [self._slide(text)])), 1, text)

    def test_ignored_tokens(self):
        sp = {"slides": [{"id": "a", "blocks": {}}]}
        for text in ("Updated in 2026", "As of 2026-09-30 and 30 September 2026", "FY25 and Q3 results", "10-K filing",
                     "Step 3 follows", "the 3rd option"):
            self.assertEqual(provenance.check(sp, [self._slide(text)]), [], text)
        el = Element("s1.callout.1", "text", "callout", 1, 1, 5, 1,
                     text=TextSpec([Para([Run("1  ", b=True), Run("Plain takeaway")])], 14))
        self.assertEqual(provenance.check(sp, [SolvedSlide(1, "x", [el])]), [])

    def test_unsourced_slide_data_does_not_count_and_prose_is_not_a_source(self):
        no_src = {"slides": [{"id": "a", "blocks": {"value": 4.7}}]}
        self.assertEqual(len(provenance.check(no_src, [self._slide("4.7bn")])), 1)
        prose = {"slides": [{"id": "a", "source": "S", "blocks": {"takeaways": ["Revenue 4.7bn"]}}]}
        self.assertEqual(len(provenance.check(prose, [self._slide("4.7bn")])), 1)

    def test_manifest_and_values_count(self):
        sp = {"slides": [{"id": "a", "blocks": {}}]}
        man = {"values": {"rev": 4700.0}}
        self.assertEqual(provenance.check(sp, [self._slide("$4.7bn")], manifest=man), [])
        self.assertEqual(provenance.check(sp, [self._slide("$4.7bn")], values={"x": 4.7e9}), [])

    def test_table_cells_checked(self):
        sp = {"slides": [{"id": "a", "source": "S", "blocks": {"rows": [["Acme", "12.0x"]]}}]}
        el = Element("s1.table", "table", "table", 1, 1, 5, 3, table={"columns": ["Name", "EV/EBITDA"], "rows": [["Acme", "12.0x"], ["Beta", "9.9x"]]})
        f = provenance.check(sp, [SolvedSlide(1, "x", [el])])
        self.assertEqual([x["shape_name"] for x in f], ["s1.table"])
        self.assertIn("9.9x", f[0]["message"])


class ProvenanceWave3(NoNetwork):
    """D-S3-11: derived values, deck-wide sources, citations, and the rule still biting."""

    def _slide(self, text, idx=1, role="body", meta=None):
        el = Element(f"s{idx}.{role}", "text", role, 1, 1, 5, 1, text=TextSpec([Para([Run(text)])], 14))
        return SolvedSlide(idx, "x", [el], meta=meta or {})

    def test_planted_unsourced_number_in_every_data_example_is_still_critical(self):
        for aid in ("waterfall", "comps_table", "exec_summary", "scorecard"):
            sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(archetypes.examples()[aid])}
            sl["title"] = "Valuation rises 987% on the new plan"
            d = {"deck_id": "ex", "title": "Examples", "lang": "en", "as_of": "2026-09-30", "slides": [sl]}
            with self.subTest(archetype=aid):
                hits = [f for f in engine.build(d, seed=1, critic=False).findings if f["rule"] == "unsourced_number"]
                self.assertEqual([h["shape_name"] for h in hits], ["s1.title"])
                self.assertEqual(hits[0]["severity"], "critical")

    def test_derived_value_counts_but_only_that_value(self):
        sp = {"slides": [{"id": "a", "blocks": {}}]}
        meta = {"derived": [{"value": 11.2, "from": ["blocks.rows[0].ev_ebitda"]}]}
        self.assertEqual(provenance.check(sp, [self._slide("Median 11.2x", meta=meta)]), [])
        self.assertEqual(len(provenance.check(sp, [self._slide("Median 11.9x", meta=meta)])), 1)
        self.assertEqual(len(provenance.check(sp, [self._slide("Median 11.2x")])), 1)     # not declared

    def test_archetype_declares_its_computed_figures(self):
        from om.deck.archetypes import core  # noqa: F401
        for aid, expect in (("comps_table", 11.2), ("waterfall", 32.0), ("football_field", None), ("scorecard", 8.0)):
            sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(archetypes.examples()[aid])}
            ctx = archetypes.BuildContext(theme=__import__("om.deck.theme", fromlist=["Theme"]).Theme.house(), index=1,
                                          total=1, deck_title="T")
            out = archetypes.get(aid).build(sl, ctx)
            vals = [d["value"] for d in out.meta.get("derived", [])]
            self.assertTrue(vals, aid)
            if expect is not None:
                self.assertTrue(any(abs(v - expect) < 1e-6 for v in vals), (aid, vals))

    def test_prose_number_traces_to_a_later_slide_of_the_deck(self):
        sp = {"slides": [{"id": "a", "blocks": {}},
                         {"id": "b", "source": "Filings", "blocks": {"kpis": [{"label": "Rev", "value": "$4.7bn"}]}}]}
        s1 = self._slide("Revenue reached $4.7bn", idx=1)
        self.assertEqual(provenance.check(sp, [s1, self._slide("x", idx=2)]), [])
        self.assertEqual(len(provenance.check(sp, [self._slide("Revenue reached $4.9bn", idx=1)])), 1)
        # slide b has no source -> its data does not count for slide a
        sp["slides"][1].pop("source")
        self.assertEqual(len(provenance.check(sp, [s1, self._slide("x", idx=2)])), 1)

    def test_no_data_anywhere_stays_critical(self):
        sp = {"slides": [{"id": "a", "source": "S", "blocks": {"value": 3.1}}, {"id": "b", "source": "S", "blocks": {}}]}
        f = provenance.check(sp, [self._slide("Margin 44%", idx=2)])
        self.assertEqual([x["rule"] for x in f], ["unsourced_number"])


class Citations(NoNetwork):
    def _deck(self, sources, text, *, source="Company filings"):
        sl = {"id": "s1", "archetype": "chart_takeaways", "title": "Revenue grew on stronger lending",
              "source": source, "as_of": "2026-09-30",
              "blocks": {"subtitle": "Revenue, $ billion", "chart": _chart("column", ["FY24", "FY25"], [4.2, 4.7]),
                         "takeaways": [text, "FY24: 4.2bn base year", "Lending led the gain"]}}
        if sources is not None:
            sl["sources"] = sources
        return {"deck_id": "c", "title": "Cites", "lang": "en", "as_of": "2026-09-30", "slides": [sl]}

    def test_sources_render_as_numbered_note_line(self):
        from om.deck import archetypes as A
        from om.deck.theme import Theme
        sl = self._deck(["Company 10-K, FY25", "Broker consensus"], "Revenue: 4.7bn in FY25 [1]")["slides"][0]
        els = A.get("chart_takeaways").build(sl, A.BuildContext(Theme.house(), 1, 1, "Cites")).elements
        src = next(e for e in els if e.role == "source")
        txt = "".join(r.t for p in src.text.paras for r in p.runs)
        self.assertEqual(txt, "Source: [1] Company 10-K, FY25; [2] Broker consensus; as of 2026-09-30")
        self.assertEqual(src.text.size, 10)

    def test_single_source_keeps_the_plain_format(self):
        from om.deck import archetypes as A
        from om.deck.theme import Theme
        sl = self._deck(None, "Revenue: 4.7bn in FY25")["slides"][0]
        els = A.get("chart_takeaways").build(sl, A.BuildContext(Theme.house(), 1, 1, "Cites")).elements
        src = next(e for e in els if e.role == "source")
        self.assertEqual("".join(r.t for p in src.text.paras for r in p.runs), "Source: Company filings; as of 2026-09-30")

    def test_resolved_markers_build_clean_and_are_not_numbers(self):
        r = engine.build(self._deck(["Company 10-K", "Broker consensus"], "Revenue: 4.7bn in FY25 [1][2]"),
                         out=self.out("cite.pptx"), seed=1, critic=False)
        self.assertEqual([f for f in r.findings if f["severity"] == "critical"], [])

    def test_dangling_marker_is_a_critical_citation_finding(self):
        r = engine.build(self._deck(["Company 10-K"], "Revenue: 4.7bn in FY25 [3]"), out=self.out("cite.pptx"),
                         seed=1, critic=False)
        hits = [f for f in r.findings if f["rule"] == "citation"]
        self.assertEqual(len(hits), 1, r.findings)
        self.assertEqual(hits[0]["severity"], "critical")
        self.assertIn("[3]", hits[0]["message"])
        self.assertFalse(r.ok)

    def test_marker_without_any_source_list_resolves_against_single_source(self):
        ok = engine.build(self._deck(None, "Revenue: 4.7bn in FY25 [1]"), seed=1, critic=False)
        bad = engine.build(self._deck(None, "Revenue: 4.7bn in FY25 [2]"), seed=1, critic=False)
        self.assertEqual([f for f in ok.findings if f["rule"] == "citation"], [])
        self.assertEqual(len([f for f in bad.findings if f["rule"] == "citation"]), 1)

    def test_markers_in_table_cells_are_checked(self):
        sp = {"slides": [{"id": "a", "source": "S", "sources": ["One"], "blocks": {}}]}
        el = Element("s1.table", "table", "table", 1, 1, 5, 3, table={"columns": ["A", "B"], "rows": [["x [1]", "y [2]"]]})
        f = provenance.check(sp, [SolvedSlide(1, "x", [el])])
        self.assertEqual([(x["rule"], x["shape_name"]) for x in f], [("citation", "s1.table")])
        self.assertIn("[2]", f[0]["message"])

    def test_at_least_six_data_examples_carry_markers(self):
        import re
        n = 0
        for aid, e in archetypes.examples().items():
            if archetypes.get(aid).data and re.search(r"\[\d\]", json.dumps(e)):
                n += 1
                self.assertTrue(e.get("sources"), aid)
        self.assertGreaterEqual(n, 6)


class ThemeContrast(unittest.TestCase):
    def test_house_positive_passes_aa_as_text_and_fill(self):
        from om.deck.theme import Theme

        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

        def ratio(a, b):
            la, lb = sorted((lum(a), lum(b)), reverse=True)
            return (la + 0.05) / (lb + 0.05)
        th = Theme.house().colors
        self.assertGreaterEqual(ratio(th["positive"], "#FFFFFF"), 4.5)
        self.assertGreaterEqual(ratio(th["positive"], th["panel"]), 4.5)


class GhostGate(NoNetwork):
    def ghost(self):
        return G.GhostDeck("d", "brief", "en", [G.GhostSlide("s1", "Acme board update", "", "cover", "")])

    def test_unapproved_refused(self):
        r = engine.build(spec6(), out=self.out("g.pptx"), ghost=self.ghost(), require_ghost_approval=True)
        self.assertFalse(r.ok)
        self.assertIsNone(r.path)
        self.assertFalse(Path(self.out("g.pptx")).exists())
        self.assertTrue(any(f["rule"] == "ghost_not_approved" for f in r.findings))
        self.assertEqual(Job.from_dict(r.job).status, "failed")

    def test_approved_builds(self):
        g = G.approve(self.ghost(), "hamza")
        r = engine.build(spec6(), out=self.out("g2.pptx"), ghost=g, require_ghost_approval=True, seed=1)
        self.assertTrue(r.ok, r.error)


class Adapters(NoNetwork):
    class Fake:
        mode = "live"
        model = "m"

        def __init__(self):
            self.calls = 0

        def chat(self, messages, *, json_schema=None, job_id=None, **kw):
            self.calls += 1
            raise RuntimeError("no model in tests")

    def test_live_adapter_failure_never_breaks_build_and_critic_is_reported(self):
        ad = self.Fake()
        with mock.patch("om.deck.critic.rasterize", side_effect=RuntimeError("no rasterizer"), create=True):
            r = engine.build(spec6(), out=self.out("live.pptx"), adapter=ad, seed=1, n_candidates=2)
        self.assertTrue(r.ok, (r.error, [f for f in r.findings if f["severity"] == "critical"]))
        self.assertTrue(r.critic.startswith("critic"))
        self.assertGreater(ad.calls, 0)          # SVG designer was tried through the adapter, then fell back to procedural
        self.assertTrue(all(c["source"] == "procedural" for v in r.visuals for c in v["candidates"]))

    def test_replay_adapter_is_offline(self):
        ad = self.Fake()
        ad.mode = "replay"
        r = engine.build(spec6(), adapter=ad, seed=1)
        self.assertIn("replay", r.image_probe["reason"])
        self.assertEqual(r.critic, "critic: not run live")

    def test_no_critic_flag(self):
        self.assertEqual(engine.build(spec6(), critic=False, seed=1).critic, "critic: disabled")


class FromBrief(NoNetwork):
    def brief(self):
        g = G.GhostDeck("atlas-en", "brief", "en", [G.GhostSlide("s1", "Project Atlas board update", "", "cover", "")])
        return {"brief": "Board update", "ghost": g.to_dict(), "spec": spec6()}

    def test_offline_spec_needs_approval(self):
        r = engine.deck_from_brief(self.brief(), out=self.out("fb0.pptx"))
        self.assertIsNone(r["pptx"])
        self.assertFalse(r["report"]["ok"])
        self.assertFalse(r["ghost"]["approved"])
        self.assertFalse(Path(self.out("fb0.pptx")).exists())

    def test_offline_spec_builds_when_approved(self):
        r = engine.deck_from_brief(self.brief(), approve=True, out=self.out("fb1.pptx"), seed=1)
        self.assertEqual(r["report"]["mode"], "offline-spec")
        self.assertTrue(r["report"]["ok"], r["report"].get("error"))
        self.assertTrue(Path(r["pptx"]).exists())
        self.assertTrue(r["ghost"]["approved"])
        r = engine.deck_from_brief(self.brief(), approve=lambda g: False, out=self.out("fb2.pptx"))
        self.assertIsNone(r["pptx"])

    def test_no_adapter_no_spec(self):
        r = engine.deck_from_brief("just text")
        self.assertEqual(r["report"]["mode"], "unavailable")

    def test_live_adapter_drafts_ghost_and_spec(self):
        draft = {"deck_title": "Atlas", "sections": ["A"],
                 "slides": [{"title": "Project Atlas board update", "section": "A", "archetype_hint": "cover", "purpose": "p"}]}
        logic = {"reads_as_argument": True, "governing_thought": "g", "issues": []}
        replies = [draft, logic, spec6()]

        class Ad:
            mode = "live"

            def chat(self, messages, *, json_schema=None, job_id=None, **kw):
                return SimpleNamespace(text="", data=replies.pop(0), usage={"input_tokens": 10, "output_tokens": 5}, cost_usd=0.001)
        r = engine.deck_from_brief("Board update", adapter=Ad(), approve=True, out=self.out("fb3.pptx"), seed=1, critic=False)
        self.assertEqual(r["report"]["mode"], "live")
        self.assertTrue(r["report"]["ok"], r["report"].get("error"))
        self.assertGreater(r["report"]["tokens"], 0)


class Cli(NoNetwork):
    def run_cli(self, *argv):
        import acretia
        buf = io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["acretia.py", *argv]), redirect_stdout(buf):
            try:
                acretia.main()
            except SystemExit as e:
                code = e.code or 0
        return code, buf.getvalue()

    def write_spec(self, d, name="spec.yaml") -> str:
        import yaml
        p = Path(self._d.name) / name
        p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        return str(p)

    def test_exit_zero_and_summary(self):
        out = self.out("cli.pptx")
        code, text = self.run_cli("slides", "build", self.write_spec(spec6()), "--out", out, "--seed", "3", "--no-critic")
        self.assertEqual(code, 0, text)
        self.assertIn("slides: 6", text)
        self.assertIn("critical: 0", text)
        self.assertTrue(Path(out).exists())

    def test_exit_one_on_critical_and_json(self):
        d = spec6()
        d["slides"][1]["blocks"]["takeaways"][0] = "Revenue: 9.9bn in FY25"
        code, text = self.run_cli("slides", "build", self.write_spec(d, "bad.yaml"), "--out", self.out("cli2.pptx"), "--json")
        self.assertEqual(code, 1)
        rep = json.loads(text)
        self.assertGreaterEqual(rep["critical"], 1)
        self.assertIn("job", rep)


class TakeawayProvenanceAndSolve(NoNetwork):
    """FP-S3-c: singular `takeaway` is prose (never a source); engine returns solved slides without a render spy."""

    def _deck(self, aid, **over):
        sl = {"id": "e1", "archetype": aid, **copy.deepcopy(archetypes.examples()[aid])}
        sl.update(over)
        return {"deck_id": "ex", "title": "Examples", "lang": "en", "as_of": "2026-09-30", "slides": [sl]}

    def test_takeaway_is_a_prose_key(self):
        for k in ("takeaway", "so_what", "callout", "verdict", "rationale", "note", "caption"):
            self.assertIn(k, provenance.PROSE_KEYS)

    def test_planted_unsourced_number_in_takeaway_is_critical(self):
        for aid in ("waterfall", "doughnut_split", "stacked_bar", "tombstones"):
            d = self._deck(aid)
            d["slides"][0]["blocks"]["takeaway"] = "Value rises 987% on the new plan"
            with self.subTest(archetype=aid):
                hits = [f for f in engine.build(d, seed=1, critic=False).findings if f["rule"] == "unsourced_number"]
                self.assertTrue(any("callout" in h["shape_name"] and "987" in h["message"] for h in hits), hits)
                self.assertTrue(all(h["severity"] == "critical" for h in hits))

    def test_takeaway_cannot_vouch_for_itself(self):
        d = self._deck("waterfall")
        d["slides"][0]["blocks"]["takeaway"] = "Savings add $777m"
        d["slides"][0]["blocks"]["steps"][1]["note"] = "also $777m"      # prose-ish key inside data: not a source
        hits = [f for f in engine.build(d, seed=1, critic=False).findings if f["rule"] == "unsourced_number"]
        self.assertTrue(hits)

    def test_return_slides_and_solve(self):
        d = self._deck("waterfall")
        rep = engine.build(d, seed=1, critic=False)
        self.assertIsNone(rep.solved)
        rep2 = engine.build(d, seed=1, critic=False, return_slides=True)
        self.assertEqual(len(rep2.solved), 1)
        self.assertIsInstance(rep2.solved[0], SolvedSlide)
        self.assertNotIn("solved", rep2.to_dict())
        self.assertEqual(len(rep2.to_dict(include_solved=True)["solved"]), 1)
        slides, rep3 = engine.solve(d, seed=1, critic=False)
        self.assertEqual(len(slides), 1)
        self.assertIsNone(rep3.data)                                     # nothing rendered
        self.assertEqual(rep3.error, "")
        self.assertEqual(slides[0].to_dict(), rep2.solved[0].to_dict())

    def test_revise_has_no_mock(self):
        src = (Path(__file__).resolve().parents[1] / "om" / "deck" / "revise.py").read_text()
        self.assertNotIn("mock", src)


class FPS3fProvenanceAndSizes(unittest.TestCase):
    def test_year_with_trailing_punctuation_is_a_year(self):
        for t in ("by 2030, we expect", "in 2027.", "(2026)", "until 2031; then", "FY ends 1999:"):
            self.assertEqual(provenance.tokens(t), [], t)
        self.assertTrue(provenance.tokens("2030m"))
        self.assertTrue(provenance.tokens("$2030"))
        self.assertTrue(provenance.tokens("1,234, up"))

    def test_every_example_keeps_four_type_sizes_in_ltr_and_arabic(self):
        import re
        import zlib
        from om.deck import spec as specmod
        words = ["الإيرادات", "السوق", "النمو", "الأرباح", "التمويل", "المخاطر", "القيمة", "العملاء", "الشركة"]
        skip = {"direction", "mode", "id", "type", "from", "to", "kind", "format", "key", "style", "color", "align",
                "value_format", "axis_format", "bindings_format", "archetype", "tone", "status", "shape", "icon",
                "unit", "bindings", "pattern", "position", "side", "fill", "token"}
        rx = re.compile(r"(?<![\w$.\-])[A-Za-z]{2,}(?![\w%.\-])")

        def conv(n, k=None):
            if isinstance(n, str):
                return n if k in skip else rx.sub(lambda m: words[zlib.crc32(m.group(0).encode()) % len(words)], n)
            if isinstance(n, list):
                return [conv(x, k) for x in n]
            if isinstance(n, dict):
                return {a: conv(v, a) for a, v in n.items()}
            return n

        with tempfile.TemporaryDirectory() as tmp:
            for aid, ex in sorted(archetypes.examples().items()):
                for lang in ("en", "ar"):
                    body = copy.deepcopy(ex) if lang == "en" else conv(copy.deepcopy(ex))
                    sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **body}
                    slides = [sl] if aid == "cover" else [
                        {"id": "c0", "archetype": "cover", "title": "Examples", "blocks": {"client": "Acme",
                         "date": "2026-09-30"}, "as_of": "2026-09-30"}, sl]
                    d = {"deck_id": "ex", "title": "Examples", "lang": lang, "as_of": "2026-09-30", "slides": slides}
                    with self.subTest(archetype=aid, lang=lang):
                        r = engine.build(d, out=os.path.join(tmp, "x.pptx"), seed=1, critic=False)
                        self.assertEqual([f for f in r.findings if f["severity"] == "critical"], [])
                        self.assertEqual([f for f in r.findings if f["rule"] == "type_sizes"], [])


def _vt_deck(n=8, **extra):
    sl = [{"id": "c0", "archetype": "cover", "title": "Visual deck", "blocks": {"client": "Acme", "date": "2026-09-30"},
           "as_of": "2026-09-30"}]
    for i in range(1, n + 1):
        b = copy.deepcopy(archetypes.examples()["visual_text"])
        b["title"] = f"Onboarding gets faster in step {i}"
        sl.append({"id": f"v{i}", "archetype": "visual_text", **b})
    return {"deck_id": "vis", "title": "Visual deck", "lang": "en", "as_of": "2026-09-30", "slides": sl, **extra}


def _images(r):
    return {s.index for s in r.solved if any(e.kind == "image" for e in s.elements)}


class ContentVisuals(NoNetwork):
    def test_uses_visual_capable_deck_has_at_least_40_percent_art_on_content_slides(self):
        arch = archetypes.REGISTRY["visual_text"]
        with mock.patch.object(arch, "uses_visual", True, create=True):
            r = engine.build(_vt_deck(8), seed=3, critic=False, return_slides=True)
        self.assertTrue(r.ok, r.error)
        content = [p for p in r.visual_plan if p["content"]]
        self.assertEqual(len(content), 8)
        imgs = _images(r)
        with_art = [p for p in content if p["slide"] in imgs]
        self.assertGreaterEqual(len(with_art), 4, r.visual_plan)           # >= 40 % of 8
        self.assertLessEqual(len(with_art), 5)                             # not wallpaper
        for p in content:
            self.assertEqual(p["visual"], p["slide"] in imgs, p)
            self.assertTrue(p["reason"])
        kinds = [p["kind"] for p in r.visual_plan if p["visual"]]
        self.assertTrue(all(a != b for a, b in zip(kinds, kinds[1:])), kinds)    # neighbours differ in kind
        self.assertGreaterEqual(len(set(kinds)), 3)
        kept = [v["kept"]["png_sha256"] for v in r.visuals]
        self.assertEqual(len(kept), len(set(kept)))                         # no two identical images

    def test_lowest_data_density_gets_the_art(self):
        arch = archetypes.REGISTRY["visual_text"]
        d = _vt_deck(8)
        d["slides"][3]["blocks"]["points"] = ["Time: 12 days", "Cost: 31% lower", "Volume: 4.2x", "Quality: 9 of 10"]
        with mock.patch.object(arch, "uses_visual", True, create=True):
            plan = engine.plan_visuals(d["slides"], archetypes.REGISTRY)
        row = next(p for p in plan if p["id"] == "v3")
        self.assertFalse(row["visual"], row)
        self.assertEqual(sum(p["visual"] and p["content"] for p in plan), 5)

    def test_spec_visual_kind_path_and_none(self):
        d = _vt_deck(4)
        d["slides"][1]["visual"] = {"concept": "a clock", "kind": "diagram"}
        d["slides"][2]["visual"] = {"kind": "none"}
        plan = engine.plan_visuals(d["slides"], archetypes.REGISTRY)
        by = {p["id"]: p for p in plan}
        self.assertTrue(by["v1"]["visual"])
        self.assertEqual(by["v1"]["kind"], "diagram")
        self.assertFalse(by["v2"]["visual"])
        self.assertIn("none", by["v2"]["reason"])
        r = engine.build(d, seed=2, critic=False, return_slides=True)
        self.assertTrue(r.ok, r.error)
        self.assertIn(2, _images(r))
        self.assertNotIn(3, _images(r))
        self.assertEqual(r.visuals[0]["kind"], "diagram")

    def test_chart_and_table_archetypes_never_get_art(self):
        d = {"deck_id": "x", "title": "T", "lang": "en", "as_of": "2026-09-30", "slides": []}
        for i, aid in enumerate(("chart_takeaways", "comps_table", "ranked_bar"), 1):
            d["slides"].append({"id": f"d{i}", "archetype": aid, "title": "Example", **copy.deepcopy(archetypes.examples()[aid]),
                                "visual": {"concept": "x", "kind": "hero"}})
        with mock.patch.object(archetypes.REGISTRY["chart_takeaways"], "uses_visual", True, create=True):
            plan = engine.plan_visuals(d["slides"], archetypes.REGISTRY)
        self.assertFalse(any(p["visual"] for p in plan), plan)

    def test_claims_findings_reach_the_report(self):
        d = _vt_deck(1)
        d["slides"][1]["title"] = "Onboarding cuts cost by 77%"
        r = engine.build(d, seed=1, critic=False)
        self.assertIn("claim_unsupported", [f["rule"] for f in r.findings])
        self.assertIn("claims", r.timings)


if __name__ == "__main__":
    unittest.main()
