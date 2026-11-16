"""S3.8 vision critic loop: scripted fake adapters / fake transports only, never the network."""
from __future__ import annotations

import copy
import json
import os
import shutil
import socket
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from om.deck import critic
from om.deck.archetypes import BuildContext, base
from om.deck.model import Element, Para, Run, SolvedSlide, TextSpec
from om.deck.render import render
from om.deck.theme import Theme, grid_w, grid_x
from om.deck.validate import Report
from src.harness.adapter import Adapter

THEME = Theme.house()
KEY = "sk-test-key-0123456789"


def make_slide(index: int = 1) -> SolvedSlide:
    c = BuildContext(THEME, index, 1, "Deck", rtl=False, lang="en")
    els = base.frame({"title": "Revenue grows 12% on price", "source": "Filings"}, c)
    _, y, _, _ = base.content_box(c)
    els.append(Element(f"s{index}.body", "text", "body", grid_x(0), y, grid_w(5), 1.5,
                       text=TextSpec([Para([Run("Revenue up ", b=False), Run("12%", b=True)])], size=14)))
    els.append(Element(f"s{index}.callout", "text", "callout", grid_x(7), y, grid_w(5), 1.5,
                       text=TextSpec([Para([Run("Margin ", b=False), Run("30%", b=True)])], size=14)))
    return SolvedSlide(index, "test", els)


def el(slide: SolvedSlide, eid: str) -> Element:
    return next(e for e in slide.elements if e.id == eid)


def verdict(ok=True, score=9.0, issues=(), patch=None) -> SimpleNamespace:
    return SimpleNamespace(data={"ok": ok, "score": score, "issues": list(issues), "patch": patch})


def move_patch(x: float, target: str = "s1.callout") -> dict:
    return {"slide_index": 1, "ops": [{"op": "move", "target": target, "args": {"x": x}}], "reason": "align"}


class FakeAdapter:
    def __init__(self, *queue):
        self.queue, self.calls = list(queue), []

    def chat(self, messages, *, json_schema=None, job_id=None, **kw):
        self.calls.append({"messages": messages, "schema": json_schema, "job_id": job_id})
        return self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]


class NoNetwork(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(socket, "socket", side_effect=AssertionError("network access in a test"))
        p.start()
        self.addCleanup(p.stop)
        r = mock.patch.object(critic, "rasterize", lambda data, **kw: [b"\x89PNG-fake"] * 1)
        r.start()
        self.addCleanup(r.stop)
        self.slide = make_slide()


class LoopTests(NoNetwork):
    def test_a_move_is_applied_snapped_and_revalidated(self):
        ad = FakeAdapter(verdict(False, 6, [{"shape": "s1.callout", "problem": "off grid", "severity": "major"}],
                                 move_patch(grid_x(6) + 0.04)), verdict(True, 9))
        calls = []

        def val(data, theme=None):
            calls.append(1)
            return Report()
        out, rep = critic.loop([self.slide], THEME, adapter=ad, title="Deck", validate=val)
        self.assertEqual(len(ad.calls), 2)
        self.assertEqual(rep["loops"], 2)
        self.assertEqual(rep["critic"], "critic: ok")
        self.assertEqual(len(calls), 2)                      # baseline + one re-validation after the patch
        callout = el(out[0], "s1.callout")
        self.assertEqual(callout.x, grid_x(6))               # snapped to the column edge
        self.assertEqual(callout.w, grid_w(5))
        self.assertEqual(el(self.slide, "s1.callout").x, grid_x(7))      # input not mutated
        self.assertEqual(len(rep["patches_applied"]), 1)
        self.assertEqual(rep["slides"][1]["score"], 9.0)

    def test_b_always_complaining_stops_at_three_loops(self):
        ad = FakeAdapter(verdict(False, 4, patch=move_patch(grid_x(6))), verdict(False, 4, patch=move_patch(grid_x(7))),
                         verdict(False, 4, patch=move_patch(grid_x(6))), verdict(False, 4, patch=move_patch(grid_x(7))))
        out, rep = critic.loop([self.slide], THEME, adapter=ad, title="Deck", validate=lambda d, theme=None: Report())
        self.assertEqual(len(ad.calls), 3)
        self.assertEqual(rep["loops"], 3)
        self.assertEqual(rep["critic"], "critic: max loops reached")

    def test_c_validator_critical_means_critic_never_called(self):
        ad = FakeAdapter(verdict())
        crit = Report([{"severity": "critical", "rule": "overflow", "slide": 1, "shape_id": 1, "shape_name": "s1.body", "message": "x"}])
        out, rep = critic.loop([self.slide], THEME, adapter=ad, title="Deck", validate=lambda d, theme=None: crit)
        self.assertEqual(ad.calls, [])
        self.assertEqual(rep["critic"], "critic: skipped (validator critical)")
        self.assertIs(out[0], self.slide)

    def test_d_unknown_ids_and_raw_colours_are_dropped(self):
        patch = {"slide_index": 1, "ops": [
            {"op": "move", "target": "s1.ghost", "args": {"x": 1.0}},
            {"op": "set_style", "target": "s1.body", "args": {"color": "#FF0000"}},
            {"op": "set_font_size", "target": "s1.body", "args": {"size": 17}},
            {"op": "set_style", "target": "s1.body", "args": {"font": "Comic Sans"}},
            {"op": "explode", "target": "s1.body", "args": {}},
            {"op": "set_style", "target": "s1.body", "args": {"color": "accent"}}]}
        ad = FakeAdapter(verdict(False, 5, [{"shape": "s1.nowhere", "problem": "?", "severity": "major"}], patch))
        c = critic.critique(b"png", self.slide, adapter=ad, job_id="j")
        self.assertEqual([o["op"] for o in c["patch"]["ops"]], ["set_style"])
        self.assertEqual(c["patch"]["ops"][0]["args"], {"color": "accent"})
        self.assertEqual(len(c["dropped"]), 5)
        self.assertEqual(c["issues"], [])                    # issue naming an unknown shape is discarded
        self.assertEqual(ad.calls[0]["job_id"], "j")
        only_bad = {"slide_index": 1, "ops": [{"op": "move", "target": "s9.x", "args": {"x": 1}}]}
        c2 = critic.critique(b"png", self.slide, adapter=FakeAdapter(verdict(False, 3, patch=only_bad)))
        self.assertIsNone(c2["patch"])
        self.assertFalse(c2["ok"] and bool(c2["patch"]))

    def test_e_overflow_patch_is_refused_and_new_critical_is_rolled_back(self):
        huge = " ".join(["overflowing"] * 400)
        new, applied, refused = critic.apply_patch_ex(
            self.slide, {"slide_index": 1, "ops": [{"op": "set_text", "target": "s1.body", "args": {"text": huge}}]}, THEME)
        self.assertEqual(applied, [])
        self.assertIn("overflow", refused[0]["reason"])
        self.assertEqual(el(new, "s1.body").text.paras[0].runs[0].t, "Revenue up ")
        out_of_bounds = critic.apply_patch(self.slide, {"slide_index": 1, "ops": [
            {"op": "move", "target": "s1.callout", "args": {"y": 7.4}}]}, THEME)
        self.assertEqual(el(out_of_bounds, "s1.callout").y, el(self.slide, "s1.callout").y)

        base_bytes = render([self.slide], THEME, title="Deck")
        bad = {"severity": "critical", "rule": "overlap", "slide": 1, "shape_id": 2, "shape_name": "s1.callout", "message": "new"}
        val = lambda d, theme=None: Report() if d == base_bytes else Report([bad])      # noqa: E731
        ad = FakeAdapter(verdict(False, 5, patch=move_patch(grid_x(6))), verdict(True, 8))
        out, rep = critic.loop([self.slide], THEME, adapter=ad, title="Deck", validate=val)
        self.assertEqual(len(rep["patches_rolled_back"]), 1)
        self.assertEqual(rep["patches_applied"], [])
        self.assertEqual(el(out[0], "s1.callout").x, grid_x(7))

    def test_f_replay_without_fixture_is_not_run_live(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"ACRETIA_LLM_FIXTURES": td}):
            ad = Adapter("https://llm.meshpool.ai/v1", None, "m", mode="replay")
            out, rep = critic.loop([self.slide], THEME, adapter=ad, title="Deck")
        self.assertEqual(rep["critic"], "critic: not run live")
        self.assertIs(out[0], self.slide)
        self.assertEqual(rep["slides"], {})                  # no score was invented
        _, rep2 = critic.loop([self.slide], THEME, adapter=None, title="Deck")
        self.assertEqual(rep2["critic"], "critic: not run live")


class AdapterIntegration(NoNetwork):
    def test_request_body_carries_an_image_part(self):
        content = json.dumps({"ok": True, "score": 9, "issues": [], "patch": None})
        calls = []

        def transport(url, body, headers, stream=False):
            calls.append(body)
            return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        ad = Adapter("https://llm.meshpool.ai/v1", KEY, "m", transport=transport, mode="live")
        c = critic.critique(b"\x89PNG-fake", self.slide, adapter=ad, job_id="j1")
        self.assertTrue(c["ok"])
        self.assertEqual(c["score"], 9.0)
        parts = calls[0]["messages"][-1]["content"]
        self.assertTrue(any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,")
                            for p in parts))
        text = next(p["text"] for p in parts if p.get("type") == "text")
        self.assertIn("s1.callout", text)
        self.assertIn("response_format", calls[0])


@unittest.skipUnless(shutil.which("soffice") and shutil.which("pdftoppm"), "needs soffice and pdftoppm")
class RasterizeTests(unittest.TestCase):
    def test_one_slide_deck_gives_one_png(self):
        data = render([make_slide()], THEME, title="Deck")
        pngs = critic.rasterize(data, dpi=40)
        self.assertEqual(len(pngs), 1, critic.rasterize.last_reason)
        self.assertTrue(pngs[0].startswith(b"\x89PNG"))

    def test_missing_tools_return_empty_with_reason(self):
        with mock.patch.object(critic, "_tools", lambda: (None, None)):
            self.assertEqual(critic.rasterize(b"x"), [])
        self.assertIn("not installed", critic.rasterize.last_reason)


if __name__ == "__main__":
    unittest.main()
