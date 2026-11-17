"""Offline tests for om/api/decks.py (SF.2c): deck viewer API, anchored comments, in-place revisions, compare. Zero sockets."""
import sys
import unittest
from pathlib import Path

try:
    import pptx, PIL, fontTools, lxml  # noqa: F401,E401
except ImportError as e:
    raise unittest.SkipTest(f"deck deps missing: {e}")

import io
import shutil
import types
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from test_api_grid import Harness  # noqa: E402
from test_deck_engine import spec6  # noqa: E402

from om.api import decks  # noqa: E402
from om.api.http import Response  # noqa: E402
from om.deck import engine  # noqa: E402
from om.deals import DealStore  # noqa: E402

NAME = "board-update.pptx"
_DECK = {}


def deck_bytes() -> bytes:
    if "d" not in _DECK:
        rep = engine.build(spec6(), critic=False)
        assert rep.ok and rep.data, rep.error
        _DECK["d"] = rep.data
    return _DECK["d"]


def parts_of(data: bytes):
    return decks.read_zip(data)


class DeckApiTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.deal = self.h.deal()
        store = DealStore(self.h.conn, self.h.blobs, "org_a")
        store.save_deliverable(self.deal, NAME, deck_bytes(), "pptx", "initial build")
        self.p = f"/decks/{self.deal}/{NAME}"

    def tearDown(self):
        self.h.conn.close()
        self.h.tmp.cleanup()

    def get(self, version=None, **kw):
        st, d = self.h.call("GET", self.p, query={"version": str(version)} if version else None, **kw)
        self.assertEqual(st, 200, d)
        return d

    def comment(self, slide, body, x=0.4, y=0.3):
        st, c = self.h.call("POST", self.p + "/comments", {"slide": slide, "x": x, "y": y, "body": body})
        self.assertEqual(st, 201, c)
        return c

    def slide_blobs(self, data):
        parts = parts_of(data)
        out = {}
        for n, part in enumerate(decks.slide_parts(parts), 1):
            rels = part.replace("slides/", "slides/_rels/") + ".rels"
            out[n] = (parts[part][1], parts[rels][1] if rels in parts else b"")
        return out

    def test_get_deck_slides_titles_sources_badges(self):
        d = self.get()
        self.assertEqual(d["version"], 1)
        self.assertEqual([s["n"] for s in d["slides"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(d["slides"][1]["title"], "Revenue grew to 4.7bn on stronger lending")
        self.assertEqual(d["slides"][1]["sources"][0]["text"], "Source: Company filings; as of 2026-09-30")
        self.assertTrue(d["slides"][1]["png_url"].endswith("/v/1/slides/2.png"))
        self.assertEqual(d["versions"][0]["note"], "initial build")
        self.assertIn(d["validator"]["status"], ("pass", "warn", "fail"))
        for s in d["slides"]:
            self.assertIn(s["status"], ("pass", "warn", "fail"))
            for b in s["badges"]:
                self.assertTrue(b["rule"] and b["severity"] and b["message"])
        self.assertIn("passed", d["validator"])
        self.assertEqual(self.h.call("GET", self.p, query={"version": "9"})[0], 404)
        self.assertIsNone(d["approval"])

    def test_comment_apply_changes_only_the_commented_slide(self):
        before = self.slide_blobs(deck_bytes())
        c = self.comment(2, 'Change the title to "Revenue reached 4.7bn on lending growth"')
        self.assertEqual(c["status"], "open")
        self.assertEqual(self.get()["comments"][0]["id"], c["id"])
        st, r = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 201, r)
        self.assertEqual(r["version"], 2)
        self.assertEqual(r["slides_changed"], [2])
        new = DealStore(self.h.conn, self.h.blobs, "org_a").get_version(self.deal, NAME, 2)
        after = self.slide_blobs(new)
        for n in (1, 3, 4, 5, 6):
            self.assertEqual(before[n], after[n], f"slide {n} must be byte-identical")        # parity item 38
        self.assertNotEqual(before[2][0], after[2][0])
        d2 = self.get()
        self.assertEqual(d2["version"], 2)
        self.assertEqual(d2["slides"][1]["title"], "Revenue reached 4.7bn on lending growth")
        self.assertEqual(d2["comments"], [])
        old = self.get(version=1)
        self.assertEqual(old["comments"][0]["status"], "applied")
        self.assertEqual(old["comments"][0]["applied_in_version"], 2)
        # every other zip entry is copied byte for byte
        p_old, p_new = parts_of(deck_bytes()), parts_of(new)
        diff = sorted(k for k in p_old if p_old[k][1] != p_new[k][1])
        self.assertEqual(diff, ["ppt/slides/slide2.xml"])
        # the result is still a valid deck
        self.assertEqual(len(pptx.Presentation(io.BytesIO(new)).slides), 6)

    def test_compare_reports_exactly_one_slide_changed(self):
        c = self.comment(2, "title: Revenue reached 4.7bn")
        self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        st, cmp_ = self.h.call("GET", self.p + "/compare", query={"a": "1", "b": "2"})
        self.assertEqual(cmp_["changed"], [2])
        status = {s["n"]: s["status"] for s in cmp_["slides"]}
        self.assertEqual(status, {1: "unchanged", 2: "changed", 3: "unchanged", 4: "unchanged", 5: "unchanged", 6: "unchanged"})
        self.assertIn("Revenue grew to 4.7bn on stronger lending", cmp_["slides"][1]["text_diff"]["removed"])
        self.assertIn("Revenue reached 4.7bn", cmp_["slides"][1]["text_diff"]["added"])
        self.assertFalse(cmp_["identical"])
        st, same = self.h.call("GET", self.p + "/compare", query={"a": "2", "b": "2"})
        self.assertTrue(same["identical"])

    def test_chart_switch_edits_only_the_chart_part(self):
        import pptx.enum.chart as ec
        c = self.comment(2, "Please change this to a line chart")
        st, r = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 201, r)
        new = DealStore(self.h.conn, self.h.blobs, "org_a").get_version(self.deal, NAME, 2)
        prs = pptx.Presentation(io.BytesIO(new))
        chart = next(s.chart for s in prs.slides[1].shapes if s.has_chart)
        self.assertEqual(chart.chart_type, ec.XL_CHART_TYPE.LINE_MARKERS)
        p_old, p_new = parts_of(deck_bytes()), parts_of(new)
        self.assertEqual(sorted(k for k in p_old if p_old[k][1] != p_new[k][1]), ["ppt/charts/chart1.xml"])
        cmp_ = self.h.call("GET", self.p + "/compare", query={"a": "1", "b": "2"})[1]
        self.assertEqual(cmp_["changed"], [2])                                              # chart part changed => slide changed
        c2 = self.comment(2, "make it a bar chart")
        self.h.call("POST", self.p + "/apply", {"comment_ids": [c2["id"]]})
        v3 = DealStore(self.h.conn, self.h.blobs, "org_a").get_version(self.deal, NAME, 3)
        chart = next(s.chart for s in pptx.Presentation(io.BytesIO(v3)).slides[1].shapes if s.has_chart)
        self.assertEqual(chart.chart_type, ec.XL_CHART_TYPE.BAR_CLUSTERED)

    def test_text_replace_comment(self):
        c = self.comment(4, 'Replace "31%" with "30.5%"')
        st, r = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 201)
        d = self.get()
        self.assertTrue(any("30.5%" in t for t in " ".join(d["slides"][3]["outline"]).split("\n")) or "30.5%" in " ".join(d["slides"][3]["outline"]))

    def test_accepted_slide_is_locked(self):
        st, r = self.h.call("POST", self.p + "/slides/2/accept")
        self.assertEqual(st, 200)
        self.assertTrue(self.get()["slides"][1]["accepted"])
        st, err = self.h.call("POST", self.p + "/comments", {"slide": 2, "x": 0.5, "y": 0.5, "body": "title: Nope"})
        self.assertEqual(st, 409)
        self.assertEqual(err["error"]["code"], "slide_locked")
        self.assertTrue(err["error"]["hint"])
        # a slide commented before it was accepted still cannot be applied once it is locked
        c = self.comment(4, "title: Margin steady at 31%")
        self.h.call("POST", self.p + "/slides/4/accept")
        st, err = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 409)
        st, err = self.h.call("POST", self.p + "/slides/2/regenerate")
        self.assertEqual(st, 409)
        # accepting survives a revision round of another slide (fingerprint unchanged)
        self.h.call("DELETE", self.p + "/slides/4/accept")
        st, r = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 201)
        d = self.get()
        self.assertTrue(d["slides"][1]["accepted"])
        self.assertFalse(d["slides"][3]["accepted"])
        self.h.call("DELETE", self.p + "/slides/2/accept")
        self.assertFalse(self.get()["slides"][1]["accepted"])

    def test_reorder_makes_a_version_and_keeps_acceptance(self):
        self.h.call("POST", self.p + "/slides/2/accept")
        st, r = self.h.call("POST", self.p + "/reorder", {"order": [1, 4, 3, 2, 5, 6]})
        self.assertEqual(st, 201, r)
        d = self.get()
        self.assertEqual(d["version"], 2)
        self.assertEqual([s["title"] for s in d["slides"]][1], "Margin held at 31% through the cycle")
        self.assertTrue(d["slides"][3]["accepted"])
        self.assertFalse(d["slides"][1]["accepted"])
        new = DealStore(self.h.conn, self.h.blobs, "org_a").get_version(self.deal, NAME, 2)
        self.assertEqual(len(pptx.Presentation(io.BytesIO(new)).slides), 6)
        st, err = self.h.call("POST", self.p + "/reorder", {"order": [1, 1, 3, 4, 5, 6]})
        self.assertEqual(st, 400)
        st, r = self.h.call("POST", self.p + "/reorder", {"order": [1, 2, 3, 4, 5, 6]})
        self.assertFalse(r["changed"])

    def test_rollback_restores_an_older_version(self):
        c = self.comment(2, "title: Revenue reached 4.7bn")
        self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        st, r = self.h.call("POST", self.p + "/rollback", {"version": 1})
        self.assertEqual(r["version"], 3)
        d = self.get()
        self.assertEqual(d["slides"][1]["title"], "Revenue grew to 4.7bn on stronger lending")
        self.assertEqual(self.h.call("POST", self.p + "/rollback", {"version": 7})[0], 400)

    def test_needs_model_comment_becomes_a_job_or_a_clear_error(self):
        c = self.comment(3, "Make this slide punchier and add a risks angle")
        st, err = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        self.assertEqual(st, 422)
        self.assertEqual(err["error"]["code"], "needs_model")
        self.assertTrue(err["error"]["hint"])
        calls = []

        class Svc:
            def submit(self, org_id, deal_id, prompt, inputs, agent_id=None, **kw):
                calls.append((org_id, deal_id, prompt, inputs, agent_id))
                return {"id": "job_abc123"}

        fake = types.ModuleType("om.api.jobs")
        fake.SERVICE = Svc()
        with mock.patch.dict(sys.modules, {"om.api.jobs": fake}), mock.patch("om.api.jobs", fake, create=True):
            st, r = self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
            self.assertEqual(st, 202, r)
            self.assertEqual(r["jobs"][0]["job_id"], "job_abc123")
            self.assertIsNone(r["version"])
            self.assertIn("Edit slide 3", calls[0][2])
            self.assertEqual(calls[0][3]["slide"], 3)
            st, r = self.h.call("POST", self.p + "/slides/5/regenerate", {"instruction": "tighter"})
            self.assertEqual(st, 202)
            self.assertEqual(r["job_id"], "job_abc123")

    def test_comment_validation(self):
        for body in ({"slide": 99, "x": 0.5, "y": 0.5, "body": "x"}, {"slide": 2, "x": 2, "y": 0.5, "body": "x"},
                     {"slide": 2, "x": 0.5, "y": 0.5, "body": " "}, {"slide": "a", "body": "x"}):
            st, err = self.h.call("POST", self.p + "/comments", body)
            self.assertEqual(st, 400, body)
            self.assertTrue(err["error"]["hint"])
        c = self.comment(2, "title: x y z")
        self.assertEqual(self.h.call("DELETE", self.p + f"/comments/{c['id']}")[0], 200)
        self.assertEqual(self.h.call("DELETE", self.p + f"/comments/{c['id']}")[0], 404)

    def test_png_route_returns_png_or_503_with_hint(self):
        st, res = self.h.call("GET", self.p + "/v/1/slides/2.png")
        if decks.renderer_available():
            self.assertEqual(st, 200)
            self.assertIsInstance(res, Response)
            self.assertTrue(res.body.startswith(b"\x89PNG"))
            self.assertEqual(self.h.call("GET", self.p + "/v/1/slides/99.png")[0], 404)
        else:
            self.assertEqual(st, 503)
            self.assertTrue(res["error"]["hint"])
        c = self.comment(2, "title: A fresh title for the cache")
        self.h.call("POST", self.p + "/apply", {"comment_ids": [c["id"]]})
        with mock.patch.object(decks, "renderer_available", return_value=False):
            st, err = self.h.call("GET", self.p + "/v/2/slides/1.png")
            self.assertEqual(st, 503)
            self.assertEqual(err["error"]["code"], "renderer_unavailable")
            self.assertIn("libreoffice", err["error"]["hint"].lower())

    def test_tenant_isolation_and_roles(self):
        c = self.comment(2, "title: abc def")
        for method, path, body in [
            ("GET", self.p, None), ("GET", self.p + "/v/1/slides/1.png", None),
            ("POST", self.p + "/comments", {"slide": 1, "x": 0.1, "y": 0.1, "body": "x"}),
            ("DELETE", self.p + f"/comments/{c['id']}", None), ("POST", self.p + "/apply", {"comment_ids": [c["id"]]}),
            ("POST", self.p + "/slides/1/accept", None), ("DELETE", self.p + "/slides/1/accept", None),
            ("POST", self.p + "/slides/1/regenerate", None), ("POST", self.p + "/reorder", {"order": [1]}),
            ("GET", self.p + "/compare", None), ("POST", self.p + "/rollback", {"version": 1})]:
            st, out = self.h.call(method, path, body, org="org_b")
            self.assertEqual(st, 404, (method, path, out))
        self.assertEqual(self.h.call("GET", f"/decks/{self.deal}/nope.pptx")[0], 404)
        route, _ = self.h.router.resolve("POST", "/api/v1" + self.p + "/apply")
        self.assertEqual(route.role, "member")
        from om.api.http import ApiError, RequestContext
        ctx = RequestContext(method="POST", params={"deal_id": self.deal, "name": NAME}, json={"comment_ids": [c["id"]]},
                             conn=self.h.conn, blobs=self.h.blobs, org_id="org_a", role="viewer")
        with self.assertRaises(ApiError) as cm:
            decks.apply_comments(ctx)
        self.assertEqual(cm.exception.status, 403)

    def test_parse_comment_ops(self):
        self.assertEqual(decks.parse_comment("title: New headline here")[0], {"op": "title", "text": "New headline here"})
        self.assertEqual(decks.parse_comment("Change the slide title to “Better”.")[0]["text"], "Better")
        self.assertEqual(decks.parse_comment('replace "4.7bn" with "4.8bn"')[0], {"op": "replace", "a": "4.7bn", "b": "4.8bn"})
        self.assertEqual(decks.parse_comment("switch to a column chart")[0], {"op": "chart", "kind": "column"})
        self.assertEqual(decks.parse_comment("make it feel more premium"), [])


if __name__ == "__main__":
    unittest.main()
