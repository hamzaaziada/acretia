"""S3.11 generative visual layer: probe, procedural art, candidate fall-through, scoring, variety rules, learning log."""
import unittest

try:
    import pptx, PIL, fontTools  # noqa: F401,E401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")
import io
import os
import random
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from om import house
from om.deck.visuals import generate, library, log, probe, procedural, score, variety

PAL = library.palette_for()


def _fresh(extra_env=None):
    env = {"ACRETIA_LLM_MODE": "", "OM_IMAGE_MODEL": "", "GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}
    env.update(extra_env or {})
    return mock.patch.dict(os.environ, env)


class Probe(unittest.TestCase):
    def test_offline_makes_no_network_call(self):
        def boom(*a, **k):
            raise AssertionError("socket used")
        with _fresh({"ACRETIA_LLM_MODE": "replay", "OM_IMAGE_MODEL": "openai", "OPENAI_API_KEY": "k"}), \
                mock.patch.object(socket, "socket", boom):
            st = probe.image_endpoint(force=True)
        self.assertFalse(st["available"])
        self.assertTrue(st["reason"])
        with _fresh(), mock.patch.object(socket, "socket", boom):
            self.assertFalse(probe.image_endpoint(force=True)["available"])

    def test_adapter_replay_and_offline_flag_make_no_call(self):
        def boom(*a, **k):
            raise AssertionError("transport used")
        class Rep:
            mode = "replay"
        with _fresh({"OM_IMAGE_MODEL": "openai", "OPENAI_API_KEY": "k"}):
            a = probe.image_endpoint(adapter=Rep(), transport=boom, force=True)
            b = probe.image_endpoint(transport=boom, force=True, offline=True)
        self.assertFalse(a["available"])
        self.assertFalse(b["available"])
        self.assertIn("replay", a["reason"])

    def test_gateway_path_not_exposed(self):
        calls = []

        def transport(url, body, headers, **kw):
            calls.append(url)
            return {"error": {"code": "gateway_path_not_exposed", "message": "/v1/images/generations"}}
        with _fresh({"OM_IMAGE_MODEL": "openai", "OPENAI_API_KEY": "k"}):
            st = probe.image_endpoint(transport=transport, force=True)
        self.assertFalse(st["available"])
        self.assertIn("gateway_path_not_exposed", st["reason"])
        self.assertEqual(len(calls), 1)

    def test_available_and_cached(self):
        import base64
        png = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(png, "PNG")
        n = []

        def transport(url, body, headers, **kw):
            n.append(1)
            return {"data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}]}
        with _fresh({"OM_IMAGE_MODEL": "openai", "OPENAI_API_KEY": "k"}):
            a = probe.image_endpoint(transport=transport, force=True)
            b = probe.image_endpoint(transport=transport)
        self.assertTrue(a["available"])
        self.assertEqual(a["provider"], "openai")
        self.assertEqual(len(n), 1)
        self.assertEqual(b["available"], True)


class Procedural(unittest.TestCase):
    def test_every_style(self):
        self.assertGreaterEqual(len(library.STYLES), 8)
        for sid in library.STYLES:
            with self.subTest(style=sid):
                png, svg, _ = procedural.render(sid, seed=3)
                im = Image.open(io.BytesIO(png))
                self.assertEqual(im.size, (1600, 900))
                im.verify()
                self.assertTrue(svg.startswith("<svg"))
                low = svg.lower()
                self.assertNotIn("<text", low)
                self.assertNotIn("gradient", low)
                self.assertLessEqual(score.color_shares(png, PAL)["accent"], .15)
                png2 = procedural.render(sid, seed=4)[0]
                self.assertGreater(score.hamming(score.phash(png), score.phash(png2)), 6)
                self.assertEqual(png, procedural.render(sid, seed=3)[0])   # seeded = reproducible

    def test_aspects_and_unseeded(self):
        self.assertEqual(Image.open(io.BytesIO(procedural.render("data_art", seed=1, aspect="1:1")[0])).size, (900, 900))
        self.assertEqual(Image.open(io.BytesIO(procedural.render("data_art", seed=1, aspect="3:2")[0])).size, (1200, 800))
        self.assertNotEqual(procedural.render("duotone_hero")[2], procedural.render("duotone_hero")[2])


class Raising:
    """Adapter whose every call fails (replay miss)."""
    def chat(self, *a, **k):
        raise RuntimeError("replay miss")


class Candidates(unittest.TestCase):
    def test_falls_through_to_procedural(self):
        cs = generate.candidates("risk map", "isometric_system", 3, adapter=Raising(), image_status={"available": False}, seed=5)
        self.assertEqual({c.source for c in cs}, {"procedural"})
        self.assertEqual(len(cs), 3)
        self.assertEqual(len({c.prompt for c in cs}), 3)
        self.assertEqual(len({c.png for c in cs}), 3)
        self.assertTrue(all(c.svg and c.png for c in cs))

    def test_image_model_first_then_svg(self):
        class Client:
            def generate(self, prompt, aspect="16:9"):
                return procedural.render("data_art", seed=1)[0]
        cs = generate.candidates("x", "data_art", 2, image_status={"available": True, "client": Client()}, seed=1)
        self.assertEqual({c.source for c in cs}, {"image_model"})
        # image model failing mid-way falls to the next tier
        class Bad:
            def generate(self, *a, **k):
                raise RuntimeError("down")
        cs = generate.candidates("x", "data_art", 2, adapter=Raising(), image_status={"available": True, "client": Bad()}, seed=1)
        self.assertEqual({c.source for c in cs}, {"procedural"})

    def test_svg_designer(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect width="80" height="90" fill="#1F3C88"/></svg>'

        class R:
            def chat(self, messages, *, json_schema=None, job_id=None, **kw):
                from types import SimpleNamespace
                return SimpleNamespace(data={"svg": svg})
        png = procedural.render("data_art", seed=2)[0]
        with mock.patch("om.images.render_svg", return_value=png):
            cs = generate.candidates("x", "data_art", 2, adapter=R(), image_status={"available": False}, seed=1)
        self.assertEqual({c.source for c in cs}, {"svg_designer"})
        with mock.patch("om.images.render_svg", return_value=None):   # no renderer installed -> procedural
            cs = generate.candidates("x", "data_art", 1, adapter=R(), image_status={"available": False}, seed=1)
        self.assertEqual(cs[0].source, "procedural")


class Scoring(unittest.TestCase):
    def test_blank_below_good(self):
        blank = io.BytesIO()
        Image.new("RGB", (1600, 900), "white").save(blank, "PNG")
        good = procedural.render("editorial_illustration", seed=1)[0]
        sb, sg = score.score(blank.getvalue(), None), score.score(good, None)
        self.assertLess(sb["overall"], sg["overall"] - 3)
        self.assertTrue(all(0 <= v <= 10 for v in sg.values()))

    def test_off_palette_and_accent_flood_penalised(self):
        im = Image.new("RGB", (1600, 900), "white")
        im.paste(Image.new("RGB", (1100, 900), PAL["accent"]), (0, 0))
        im.save(buf := io.BytesIO(), "PNG")
        self.assertLess(score.score(buf.getvalue())["accent"], 6)

    def test_choose_and_vlm(self):
        cs = generate.candidates("x", "duotone_hero", 3, adapter=None, seed=9)
        best, scores = score.choose(cs)
        self.assertIn(best.id, scores)
        self.assertEqual(max(s["final"] for s in scores.values()), scores[best.id]["final"])
        self.assertIsNone(score.vlm_score(cs[0], Raising()))

        class Crit:
            def chat(self, messages, *, json_schema=None, job_id=None, **kw):
                from types import SimpleNamespace
                url = messages[1]["content"][1]["image_url"]["url"]
                import base64
                png = base64.b64decode(url.split(",", 1)[1])
                return SimpleNamespace(data={"score": 10.0 if png == cs[2].png else 0.0})
        best, scores = score.choose(cs, adapter=Crit())
        self.assertAlmostEqual(scores[cs[2].id]["final"], (scores[cs[2].id]["overall"] + 10) / 2, places=1)


def S(n, arch, vt, boxes=((1, 1, 5, 3),)):
    return {"number": n, "archetype": arch, "visual_type": vt,
            "elements": [{"role": f"r{i}", "x": b[0], "y": b[1], "w": b[2], "h": b[3]} for i, b in enumerate(boxes)]}


class Variety(unittest.TestCase):
    def test_consecutive_duplicate(self):
        sl = [S(1, "cover", "none"), S(2, "chart", "bar", ((1, 1, 6, 4),)), S(3, "chart", "bar", ((2, 2, 3, 3),)), S(4, "text", "icons")]
        f = variety.check(sl)
        self.assertTrue(any(x["rule"] == "variety" and x["slide"] == 3 and x["severity"] == "major" for x in f))
        self.assertFalse(any(x["slide"] == 4 and "repeat" in x["message"] for x in f))

    def test_distinct_types_in_window(self):
        vts = ["bar", "line", "bar", "line"] * 3
        sl = [S(i + 1, "a%d" % (i % 3), vt, ((i % 5 + 1, 1, 4, 3),)) for i, vt in enumerate(vts)]
        self.assertTrue(any("distinct visual types" in x["message"] for x in variety.check(sl)))
        ok = [S(i + 1, "a%d" % i, "t%d" % (i % 6), ((i + 1, 1, 4, 3),)) for i in range(12)]
        self.assertFalse(any("distinct visual types" in x["message"] for x in variety.check(ok)))
        short = [S(1, "a", "t1"), S(2, "b", "t2"), S(3, "c", "t3"), S(4, "d", "t4")]   # n<10: need ceil(n/2)=2
        self.assertEqual(variety.check(short), [])

    def test_templated(self):
        sl = [S(i + 1, "content", "t0", ((1, 1, 5, 3), (7, 1, 5, 3))) for i in range(8)]
        for s in sl:
            s["archetype"] = "content"
        f = [x for x in variety.check(sl) if x["rule"] == "templated"]
        self.assertEqual(len(f), 1)
        self.assertIn("slides", f[0]["message"])
        varied = [S(i + 1, "a%d" % i, "t%d" % i, ((i + 1, i % 4 + 1, 2 + i % 3, 2), (8 - i % 5, 3, 3, 1 + i % 3))) for i in range(8)]
        self.assertFalse([x for x in variety.check(varied) if x["rule"] == "templated"])

    def test_signature_objects(self):
        class E:
            role, x, y, w, h = "title", 1.0, 1.0, 5.0, 1.0

        class Sl:
            archetype, visual_type, elements = "chart", "bar", [E()]
        self.assertEqual(variety.similarity(Sl(), Sl()), 1.0)


class Learning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deck_styles" / "scores.jsonl"
        self.addCleanup(self.tmp.cleanup)

    def test_weights_and_retirement(self):
        for i in range(5):
            log.record("data_art", deck_id="d", slide=i, candidate_id="c%d" % i, source="procedural", scores={"overall": 4.0}, path=self.path)
        for i in range(2):
            log.record("duotone_hero", deck_id="d", slide=i, candidate_id="h%d" % i, source="procedural", scores={"overall": 9.5},
                       persona=9.0, validator_ok=True, path=self.path)
        self.assertEqual(len(log.read(self.path)), 7)
        w = library.weights(self.path)
        self.assertTrue(w["data_art"]["retired"])
        self.assertAlmostEqual(w["data_art"]["score"], (21 + 20) / 8)
        self.assertFalse(w["duotone_hero"]["retired"])
        self.assertGreater(w["duotone_hero"]["score"], 7.0)
        self.assertEqual(w["bold_typographic"]["score"], 7.0)

    def test_env_default_path(self):
        with mock.patch.dict(os.environ, {"ACRETIA_DATA": self.tmp.name}):
            log.record("data_art", deck_id="d", slide=1, candidate_id="c", source="procedural", scores={"overall": 8})
            self.assertEqual(len(log.read()), 1)
        self.assertTrue((Path(self.tmp.name) / "deck_styles" / "scores.jsonl").exists())

    def test_art_direction(self):
        self.assertEqual(library.choose_art_direction({"art_direction": "annotated_map"}, rng=random.Random(1), log_path=self.path), "annotated_map")
        for i in range(6):
            log.record("data_art", deck_id="d", slide=i, candidate_id="c%d" % i, source="x", scores={"overall": 3}, path=self.path)
        picks = {library.choose_art_direction({"art_direction": "auto"}, rng=random.Random(i), log_path=self.path) for i in range(150)}
        self.assertNotIn("data_art", picks)
        self.assertGreater(len(picks), 3)   # varied, not rubber-stamped
        only = {library.choose_art_direction({"visual_kinds": ["icon_system"]}, rng=random.Random(i), log_path=self.path) for i in range(30)}
        self.assertEqual(only, {"iconographic_system"} | (only - {"iconographic_system"}) & {"iconographic_system"})
        self.assertTrue(all("icon_system" in library.STYLES[s].kinds for s in only))


if __name__ == "__main__":
    unittest.main()
