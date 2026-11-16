"""Deck Studio: the drawn workflow end to end with stand-in models, plus each building block."""
import base64
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import images, layout, studio  # noqa: E402
from om.llm import OpenAICompatProvider, Part, Result  # noqa: E402


def png(w=40, h=24, rgb=(11, 31, 58)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")


SB = {"title": "Fund growth then return cash", "answer": "Approve $4.0B", "slides": [
    {"n": 1, "title": "Approve $4.0B of returns", "question": "What do we decide?", "exhibit": "cover", "body": ["Board meeting"], "visual": "cover", "data": []},
    {"n": 2, "title": "Cash covers the plan 2.7x", "question": "Can we afford it?", "exhibit": "bar",
     "body": ["Cash at 30 Aug 2026: $20.21B", "FY27 capex: $7.5B"], "visual": "two bars", "data": [{"label": "cash", "value": "$20.21B"}]}]}


class FakeRouter:
    def __init__(self):
        self.calls = []
        self.drafts = 0

    def available(self, stage):
        return True

    def complete_json(self, stage, system, parts, schema, **kw):
        self.calls.append((stage, [p.image is not None for p in parts]))
        props = schema["properties"]
        if "slides" in props:
            return Result(json.loads(json.dumps(SB)))
        if "question" in props and "visual" in props:                       # condense one page
            page = json.loads(parts[1].text.split("\n", 1)[1])
            return Result({**page, "body": page["body"][:2], "visual": "a bridge"})
        if "prompts" in props:
            return Result({"prompts": [{"n": 1, "prompt": "cover"}, {"n": 2, "prompt": "bars"}]})
        if "elements" in props:
            spec = json.loads(parts[0].text.split("\n", 1)[1])
            fixed = any("FIX ALL" in p.text for p in parts)
            body = spec["body"] if fixed else spec["body"][:1]          # first build drops a line -> numbers check fails
            return Result({"elements": [
                {"type": "component", "kind": "exhibit_frame", "title": spec["title"], "deck": "Deck", "page": spec["n"]},
                {"type": "text", "x": 0.7, "y": 2.15, "w": 11.93, "h": 4.1,
                 "paragraphs": [{"runs": [{"text": b, "size": 14}]} for b in body]}]})
        dims = schema["properties"]["scores"]["required"]
        good = {"headline": "fine", "scores": {d: {"score": 9, "why": "ok"} for d in dims}, "issues": []}
        bad = {"headline": "redo", "scores": {d: {"score": 6 if d == "spacing" else 8, "why": "cramped"} for d in dims},
               "issues": [{"severity": "major", "where": "chart", "issue": "bars too small", "fix": "make the bars bigger"}]}
        if any(p.text == "DRAFT:" for p in parts):
            self.drafts += 1
            return Result(good if self.drafts % 4 in (3, 0) else bad)   # both graders reject draft 1, accept draft 2
        return Result(good)


def fake_render(deck: bytes) -> list[bytes]:
    z = zipfile.ZipFile(io.BytesIO(deck))
    return [png() for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]


class FakeImages:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, references=None, **kw):
        self.calls.append((prompt, bool(references)))
        return png()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.store = studio.Studio(Path(tempfile.mkdtemp()))

    def test_auto_mode_runs_the_whole_drawing(self):
        router, imgs = FakeRouter(), FakeImages()
        p = studio.Pipeline(self.store, router, imgs, renderer=fake_render)
        rid = self.store.create("Costco capital allocation", "md", "auto", "cash $20.21B; capex $7.5B")
        run = p.advance(rid)
        self.assertEqual(run["status"], "done", run.get("error"))
        # rejected drafts are redrawn from the draft itself plus the comments
        self.assertTrue(any(ref and "make the bars bigger" in pr for pr, ref in imgs.calls))
        # the reviewer and the slides engine both got images
        self.assertTrue(any(st == "slide_review" and any(flags) for st, flags in router.calls))
        self.assertTrue(any(st == "slide_build" and any(flags) for st, flags in router.calls))
        s2 = run["slides"][1]
        self.assertTrue(any("number missing" in f for f in s2["builds"][0]["findings"]))   # dropped $7.5B line caught
        self.assertFalse(s2["builds"][0]["review"]["approve"])                             # ...and forces a rebuild
        self.assertEqual(len(s2["builds"]), 2)
        deck = self.store.read(rid, run["deck"])
        z = zipfile.ZipFile(io.BytesIO(deck))
        self.assertEqual(len([n for n in z.namelist() if n.startswith("ppt/slides/slide")]), 2)
        self.assertIn("counts", run["check"])
        self.assertTrue(run["deck_reviews"])
        # every review is a two-grader panel with dimension scores, spacing included
        panel = s2["builds"][-1]["review"]["panel"]
        self.assertEqual({g["persona"] for g in panel}, {"partner", "md"})
        self.assertTrue(all("spacing" in g["scores"] for g in panel))

    def test_no_render_means_no_sign_off(self):
        p = studio.Pipeline(self.store, FakeRouter(), FakeImages(), renderer=None, build_rounds=2, deck_rounds=1)
        run = p.advance(self.store.create("x", "md", "auto", ""))
        self.assertEqual(run["status"], "done", run.get("error"))
        self.assertFalse(run["signed_off"])

    def test_human_mode_waits_for_you(self):
        p = studio.Pipeline(self.store, FakeRouter(), FakeImages(), renderer=None)
        rid = self.store.create("x", "partner", "human", "")
        run = p.advance(rid)
        self.assertEqual((run["status"], run["slides"][0]["image_status"]), ("waiting", "waiting_human"))
        p.approve_image(rid, 1, True)
        run = p.advance(rid)
        self.assertEqual(run["slides"][1]["image_status"], "waiting_human")
        p.approve_image(rid, 2, False, ["bigger title"])
        run = p.advance(rid)
        self.assertEqual(len(run["slides"][1]["images"]), 2)
        p.approve_image(rid, 2, True)
        run = p.advance(rid)
        self.assertEqual(run["status"], "done", run.get("error"))

    def test_no_image_model_is_a_clear_error(self):
        p = studio.Pipeline(self.store, FakeRouter(), None, renderer=None)
        run = p.advance(self.store.create("x"))
        self.assertEqual(run["status"], "error")
        self.assertIn("image model", run["error"])

    def test_paths_are_safe(self):
        with self.assertRaises(ValueError):
            self.store.path("../etc", "passwd")
        with self.assertRaises(ValueError):
            self.store.path("abc", "../run.json")


class BuildingBlockTests(unittest.TestCase):
    def test_layout_renders_every_element_type(self):
        src = png(100, 60)
        lay = {"background": "#F7F5F0", "font": "Georgia", "elements": [
            {"type": "text", "x": .5, "y": .4, "w": 12, "h": .8, "paragraphs": [{"runs": [{"text": "Title", "size": 24, "bold": True}]}]},
            {"type": "shape", "shape": "roundRect", "x": .5, "y": 1.5, "w": 3, "h": 1, "fill": "#0B1F3A", "corner": .2,
             "paragraphs": [{"runs": [{"text": "Box", "color": "#FFFFFF"}], "align": "ctr"}]},
            {"type": "line", "x1": .5, "y1": 3, "x2": 6, "y2": 3, "arrow_end": True},
            {"type": "table", "x": .5, "y": 3.3, "w": 6, "rows": [["A", "B"], ["1", "2"]], "numeric_columns": [1]},
            {"type": "chart", "kind": "waterfall", "x": 7, "y": 1.5, "w": 5.5, "h": 3, "categories": ["Open", "FCF", "Div", "=Close"],
             "series": [{"name": "$B", "values": [20.2, 9.4, -3.6, 26.0]}]},
            {"type": "chart", "kind": "doughnut", "x": 7, "y": 4.6, "w": 3, "h": 2.5, "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]},
            {"type": "image_crop", "x": 10.5, "y": 4.6, "w": 2, "h": 1.2, "crop": [0, 0, .5, .5]},
            {"type": "bogus"}]}
        deck, warnings = layout.build_deck([lay], [src])
        self.assertEqual(warnings, ["slide 1: element 8: unknown type 'bogus'"])
        z = zipfile.ZipFile(io.BytesIO(deck))
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                ET.fromstring(z.read(n))
        self.assertTrue(any(n.startswith("ppt/media/") for n in z.namelist()))
        self.assertEqual(len([n for n in z.namelist() if n.startswith("ppt/charts/")]), 2)

    def test_crop_png(self):
        out = layout.crop_png(png(100, 60), [0.25, 0.5, 0.75, 1.0])
        w, h, rows, bpp = layout._decode_png(out)
        self.assertEqual((w, h), (50, 30))

    def test_numbers_and_overflow_checks(self):
        spec = {"title": "Cash of $20.21B covers $7.5B", "body": ["Free cash flow $9.39B"], "data": []}
        lay = {"elements": [{"type": "text", "x": 0, "y": 0, "w": 5, "h": .4, "paragraphs": [
            {"runs": [{"text": "Cash of $20.21B covers $7.5B. Free cash flow $9.38B " * 4, "size": 14}]}]}]}
        f = studio.check_numbers(spec, lay)
        self.assertIn("number missing from the slide: $9.39b", f)
        self.assertIn("number not in storyboard: $9.38b", f)
        self.assertTrue(studio.overflow(lay))

    def test_vision_parts_openai_compat(self):
        sent = {}

        def transport(url, body, headers):
            sent.update(body)
            return {"choices": [{"message": {"content": '{"ok": true}'}}]}
        prov = OpenAICompatProvider("openai", "m", "https://x", "k", "json_schema", transport)
        prov.complete_json("sys", [Part("look:", image=png())], {"type": "object", "properties": {"ok": {"type": "boolean"}}})
        content = sent["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "image_url")
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_image_providers(self):
        got = {}

        def gem(url, body, headers):
            got["gemini"] = (url, body, headers)
            return {"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"IMG").decode()}}]}}]}

        def oai(url, body, headers):
            got["openai"] = (url, body, headers)
            return {"data": [{"b64_json": base64.b64encode(b"IMG2").decode()}]}
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o", "OM_IMAGE_MODEL": ""}):
            g = images.make_image_provider("gemini", transport=gem)
            self.assertEqual(g.generate("p", references=[png()]), b"IMG")
            url, body, headers = got["gemini"]
            self.assertIn("/v1/models/gemini-nano-banana-2.1:generateContent", url)
            self.assertEqual(headers["x-goog-api-key"], "g")
            self.assertEqual(body["generationConfig"]["imageConfig"]["aspectRatio"], "16:9")
            self.assertIn("inline_data", body["contents"][0]["parts"][1])
            o = images.make_image_provider("openai", transport=oai)
            self.assertEqual(o.generate("p"), b"IMG2")
            self.assertEqual(got["openai"][1]["size"], "1536x864")
            self.assertEqual(images.configured_spec(), "gemini")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "OM_IMAGE_MODEL": ""}):
            self.assertIsNone(images.make_image_provider())

    def test_vision_stages_skip_text_only_default(self):
        from om import llm
        with mock.patch.dict(os.environ, {"OM_MODEL_DEFAULT": "deepseek:deepseek-chat", "GEMINI_API_KEY": "g", "OM_MODEL_SLIDE_REVIEW": "",
                                          "OM_MODEL_VISION": "", "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": ""}):
            self.assertEqual(llm.configured_spec("slide_review"), "gemini")
            self.assertEqual(llm.configured_spec("storyboard"), "deepseek:deepseek-chat")


if __name__ == "__main__":
    unittest.main()


class SvgImageTests(unittest.TestCase):
    def test_sanitize_strips_anything_that_reaches_out(self):
        dirty = ('<svg viewBox="0 0 10 10"><script>alert(1)</script><rect onload="x()" width="5" height="5"/>'
                 '<image href="https://evil.example/a.png"/><foreignObject><div/></foreignObject>'
                 '<rect style="fill:url(https://evil.example/f)"/><use href="#a"/></svg>')
        clean = images.sanitize_svg("here you go:\n" + dirty)
        for bad in ("script", "onload", "evil.example", "foreignObject"):
            self.assertNotIn(bad, clean)
        self.assertIn('href="#a"', clean)                      # internal references are fine

    def test_svg_drafts_revise_from_source_and_feed_the_engine(self):
        seen = []

        class Designer:
            def complete_json(self, system, parts, schema, **kw):
                seen.append([p.text[:30] for p in parts])
                return Result({"svg": '<svg viewBox="0 0 1600 900"><text x="84" y="110">Title</text></svg>'})
        prov = images.SvgImages("custom:designer", provider=Designer(), renderer=lambda svg: png())
        router = FakeRouter()
        store = studio.Studio(Path(tempfile.mkdtemp()))
        p = studio.Pipeline(store, router, prov, renderer=fake_render)
        run = p.advance(store.create("x", "md", "auto", ""))
        self.assertEqual(run["status"], "done", run.get("error"))
        first = run["slides"][0]["images"]
        self.assertTrue(first[0]["svg"].endswith(".svg"))
        self.assertTrue(any(any(t.startswith("CURRENT SVG") for t in call) for call in seen))   # draft 2 revised from source
        engine_parts = [flags for st, flags in router.calls if st == "slide_build"]
        self.assertTrue(engine_parts)


class BudgetTests(unittest.TestCase):
    def test_budget_stops_reviews_but_still_delivers_a_deck(self):
        class Costly(FakeRouter):
            def complete_json(self, stage, system, parts, schema, **kw):
                r = super().complete_json(stage, system, parts, schema, **kw)
                r.usage = {"input_tokens": 20_000, "output_tokens": 1_000}
                return r
        store = studio.Studio(Path(tempfile.mkdtemp()))
        p = studio.Pipeline(store, Costly(), FakeImages(), renderer=fake_render)
        rid = store.create("x", "md", "auto", "", {"slides": 2, "token_budget": 150_000})
        run = p.advance(rid)
        self.assertEqual(run["status"], "done", run.get("error"))
        self.assertTrue(run["deck"])
        self.assertTrue(run.get("budget_hit"))
        self.assertLessEqual(run["usage"]["tokens"], 150_000 + 25_000)        # at most one call past the line
        self.assertFalse(run["signed_off"])

    def test_generous_budget_changes_nothing(self):
        store = studio.Studio(Path(tempfile.mkdtemp()))
        p = studio.Pipeline(store, FakeRouter(), FakeImages(), renderer=fake_render)
        run = p.advance(store.create("x", "md", "auto", "", {"token_budget": 10_000_000}))
        self.assertEqual(run["status"], "done", run.get("error"))
        self.assertFalse(run.get("budget_hit"))
        self.assertGreater(run["usage"]["calls"], 5)


class RedoTests(unittest.TestCase):
    def test_redo_condenses_redraws_and_reassembles(self):
        store = studio.Studio(Path(tempfile.mkdtemp()))
        p = studio.Pipeline(store, FakeRouter(), FakeImages(), renderer=fake_render)
        rid = store.create("x", "md", "auto", "")
        run = p.advance(rid)
        self.assertEqual(run["status"], "done", run.get("error"))
        before = run["slides"][1]["spec"]["body"]
        run = p.redo(rid, [2], note="too dense", budget=500_000)
        self.assertEqual(run["status"], "done", run.get("error"))
        s2 = run["slides"][1]
        self.assertEqual(s2["previous"][0]["spec"]["body"], before)            # earlier attempt kept
        self.assertEqual(s2["spec"]["visual"], "a bridge")                        # condensed page in use
        self.assertTrue(s2["images"] and s2["builds"])                          # redrawn and rebuilt
        self.assertEqual(run["slides"][0]["previous"] if "previous" in run["slides"][0] else None, None)   # other slides untouched
