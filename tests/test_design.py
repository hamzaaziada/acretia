"""House style: icons, components, the spacing check and the frame rules."""
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om import house, icons, layout, spacing  # noqa: E402
from om.grading import verdict  # noqa: E402

A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def framed(*elements):
    return {"elements": [{"type": "component", "kind": "exhibit_frame", "title": "A takeaway title", "deck": "D", "page": 2}, *elements]}


class DesignTests(unittest.TestCase):
    def test_every_icon_is_valid_geometry(self):
        self.assertGreaterEqual(len(icons.ICONS), 60)
        for name in icons.ICONS:
            g = icons.custgeom(name)
            root = ET.fromstring(f'<x xmlns:a="{A}">{g}</x>')
            self.assertTrue(list(root.iter(f"{{{A}}}path")), name)
        self.assertEqual(icons.find("supply chain logistics")[0], "truck")
        self.assertNotIn("lightbulb", " ".join(icons.ICONS))

    def test_arc_conversion_closes_a_circle(self):
        subs = icons._path_cmds("M3 12A9 9 0 1 1 21 12A9 9 0 1 1 3 12")
        last = subs[0][-1][1][-1]
        self.assertAlmostEqual(last[0], 3, places=6)
        self.assertAlmostEqual(last[1], 12, places=6)

    def test_frame_has_rules_and_no_eyebrow(self):
        els = layout.expand(framed())["elements"]
        roles = {e.get("role") for e in els}
        self.assertIn("title_rule", roles)
        self.assertIn("footer_rule", roles)
        self.assertEqual(spacing.deck_check([framed(), framed()]), [])
        eyebrow = framed({"type": "text", "x": 0.7, "y": 0.15, "w": 3, "h": 0.3, "paragraphs": [{"runs": [{"text": "SECTION", "size": 10}]}]})
        self.assertTrue(any("eyebrow" in f for f in spacing.check(eyebrow)))
        bare = {"elements": [{"type": "text", "x": 0.7, "y": 0.5, "w": 11, "h": 0.9, "paragraphs": [{"runs": [{"text": "Title", "size": 24}]}]}]}
        self.assertEqual(len(spacing.deck_check([bare, bare])), 3)

    def test_spacing_rules(self):
        good = framed({"type": "component", "kind": "icon_grid", "x": 0.7, "y": 2.15, "w": 11.93, "h": 1.9, "cols": 3,
                       "items": [{"icon": "coins", "title": "A", "text": "Saves up to $3.0B a year"}] * 3},
                     {"type": "component", "kind": "takeaway_box", "x": 0.7, "y": 4.35, "w": 11.93, "h": 1.9, "heading": "So what", "text": "Act now"})
        self.assertEqual(spacing.check(good), [])
        half = framed({"type": "component", "kind": "icon_grid", "x": 0.7, "y": 2.15, "w": 11.93, "h": 1.9, "cols": 3,
                       "items": [{"icon": "coins", "title": "A", "text": "Saves up to $3.0B a year"}] * 3})
        self.assertTrue(any("half empty" in f for f in spacing.check(half)))
        tall = framed({"type": "component", "kind": "icon_grid", "x": 0.7, "y": 2.15, "w": 11.93, "h": 4.1, "cols": 3,
                       "items": [{"icon": "coins", "title": "A", "text": "Short"}] * 3})
        self.assertTrue(any("mostly empty" in f for f in spacing.check(tall)))
        bad = framed({"type": "shape", "shape": "rect", "x": 0.7, "y": 2.15, "w": 5.5, "h": 4.1, "fill": "#F2F3F5", "inset": 0.05,
                      "valign": "t", "paragraphs": [{"runs": [{"text": "Body at eleven points that fills the card " * 12, "size": 11}]}]},
                     {"type": "shape", "shape": "rect", "x": 6.62, "y": 2.21, "w": 6.0, "h": 4.1, "fill": "#F2F3F5"})
        found = " | ".join(spacing.check(bad))
        for needle in ("14 pt minimum", "padding", "tops differ", "gap of 0.42"):
            self.assertIn(needle, found)

    def test_verdict_is_tough(self):
        self.assertTrue(verdict({"a": 8, "b": 8}, [])["sign_off"])
        self.assertFalse(verdict({"a": 9, "b": 6}, [])["sign_off"])                       # one dimension under 7
        self.assertFalse(verdict({"a": 8, "b": 7}, [])["sign_off"])                       # overall 7.5
        self.assertFalse(verdict({"a": 9, "b": 9}, [{"severity": "major"}])["sign_off"])  # any major issue

    def test_components_render(self):
        lay = framed({"type": "component", "kind": "process_flow", "x": 0.7, "y": 2.15, "w": 11.93, "h": 4.1,
                       "steps": [{"title": "One", "text": "x", "icon": "flag"}, {"title": "Two", "text": "y", "icon": "target"}]},
                     {"type": "component", "kind": "dot_plot", "x": 0.7, "y": 2.15, "w": 6, "h": 3, "rows": [{"label": "A", "before": 1, "after": 2}]},
                     {"type": "component", "kind": "callout_card", "x": 8, "y": 2.2, "w": 3, "h": 1, "title": "T", "target": [10, 5]},
                     {"type": "component", "kind": "stat_callout", "x": 8, "y": 4, "value": "$9.4B", "label": "L"},
                     {"type": "component", "kind": "change_badge", "x": 9, "y": 5, "text": "+22"},
                     {"type": "component", "kind": "numbered_heading", "x": 1, "y": 3, "number": 1, "title": "T"},
                     {"type": "component", "kind": "takeaway_box", "x": 1, "y": 5, "w": 4, "heading": "So what", "text": "t"})
        deck, warnings = layout.build_deck([lay])
        self.assertEqual(warnings, [])
        self.assertIn("$9.4B", layout.texts(lay))

    def test_house_grid_is_consistent(self):
        G = house.GRID
        self.assertLess(G["title_y"] + G["title_h"], G["title_rule_y"])
        self.assertLess(G["title_rule_y"], G["subtitle_y"])
        self.assertLess(G["content_bottom"], G["note_y"])
        self.assertLess(G["note_y"], G["footer_rule_y"])
        self.assertLess(G["footer_rule_y"], G["footer_y"])
        self.assertNotIn("label_y", G)


if __name__ == "__main__":
    unittest.main()
