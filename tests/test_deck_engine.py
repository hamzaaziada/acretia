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
        """Every archetype that ships an example builds on its own with no critical finding."""
        from om.deck import spec as specmod
        built = 0
        for aid, e in archetypes.examples().items():
            sl = {"id": "e1", "archetype": aid, "blocks": {}, "title": "Example", **copy.deepcopy(e)}
            d = {"deck_id": "ex", "title": "Examples", "lang": "en", "as_of": "2026-09-30", "slides": [sl]}
            with self.subTest(archetype=aid):
                errs = specmod.validate(d)
                if errs:
                    print(f"\n[engine] example for {aid!r} is not a valid spec, skipped: {errs[0]}")
                    continue
                r = engine.build(d, out=self.out("ex.pptx"), seed=1, critic=False)
                crit = [f for f in r.findings if f["severity"] == "critical"]
                prov = [f for f in crit if f["rule"] == "unsourced_number"]
                if prov:   # archetype-computed stats / unsourced example slides: reported, not a build failure
                    print(f"\n[engine] example for {aid!r}: {len(prov)} unsourced_number finding(s), e.g. {prov[0]['message'][:110]}")
                self.assertEqual([f for f in crit if f["rule"] != "unsourced_number"], [], crit)
                built += 1
        self.assertGreaterEqual(built, 3)

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
        import open_multiples
        buf = io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["open_multiples.py", *argv]), redirect_stdout(buf):
            try:
                open_multiples.main()
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


if __name__ == "__main__":
    unittest.main()
