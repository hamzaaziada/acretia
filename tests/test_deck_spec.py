"""DeckSpec v2: load/validate/dump. Offline."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from om.deck import spec  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "decks"


def has_registry() -> bool:
    try:
        from om.deck import archetypes  # noqa: F401
        return bool(archetypes.REGISTRY)
    except Exception:
        return False


class LoadTests(unittest.TestCase):
    def test_yaml_and_json_fixtures_equal(self):
        y, j = spec.load(FIX / "sample_spec.yaml"), spec.load(FIX / "sample_spec.json")
        self.assertEqual(y, j)
        self.assertEqual(spec.load(str(FIX / "sample_spec.yaml")), y)

    def test_load_text_and_roundtrip(self):
        d = spec.load(FIX / "sample_spec.json")
        self.assertEqual(spec.load(spec.dump_json(d)), d)
        self.assertEqual(spec.load(spec.dump_yaml(d)), d)

    def test_yaml_is_safe_load(self):
        with self.assertRaises(Exception):
            spec.load("a: !!python/object/apply:os.system ['echo hi']")

    def test_non_mapping_rejected(self):
        with self.assertRaises(ValueError):
            spec.load("- 1\n- 2\n")


class ValidateTests(unittest.TestCase):
    def deck(self):
        return json.loads(json.dumps(spec.load(FIX / "sample_spec.json")))

    def paths(self, d, **kw):
        return {e.path: e.message for e in spec.validate(d, **kw)}

    def test_fixture_valid_apart_from_registry(self):
        errs = [e for e in spec.validate(self.deck()) if "archetype" not in e.path and "blocks" not in e.path]
        self.assertEqual(errs, [])

    def test_missing_and_bad_top_level(self):
        d = self.deck()
        del d["deck_id"]
        d["lang"] = "fr"
        d["as_of"] = "30/09/2026"
        p = self.paths(d)
        self.assertIn("$.deck_id", p)
        self.assertIn("$.lang", p)
        self.assertIn("$.as_of", p)

    def test_bad_visual_kind_and_duplicate_id(self):
        d = self.deck()
        d["slides"][0]["visual"]["kind"] = "photo"
        d["slides"][1]["id"] = "s1"
        p = self.paths(d)
        self.assertIn("$.slides[0].visual.kind", p)
        self.assertIn("$.slides[1].id", p)

    def test_forbidden_key_exact_path(self):
        d = self.deck()
        d["slides"][1]["blocks"]["chart"]["series"][0]["color"] = "accent"
        d["slides"][0]["blocks"]["font_size"] = 12
        p = self.paths(d)
        self.assertIn("$.slides[1].blocks.chart.series[0].color", p)
        self.assertIn("$.slides[0].blocks.font_size", p)
        self.assertIn("come from the engine", p["$.slides[0].blocks.font_size"])

    def test_hex_and_rgb_values_rejected(self):
        d = self.deck()
        d["slides"][0]["blocks"]["bullets"][0] = "paint it #FF0000"
        d["slides"][1]["blocks"]["chart"]["series"][0]["name"] = "rgb(1,2,3)"
        p = self.paths(d)
        self.assertIn("$.slides[0].blocks.bullets[0]", p)
        self.assertIn("$.slides[1].blocks.chart.series[0].name", p)

    @unittest.skipUnless(has_registry(), "om.deck.archetypes not available")
    def test_unknown_archetype_close_matches(self):
        d = self.deck()
        d["slides"][0]["archetype"] = "exec_sumary"
        msg = self.paths(d)["$.slides[0].archetype"]
        self.assertIn("unknown archetype", msg)

    def test_skeleton_skips_blocks(self):
        d = self.deck()
        d["slides"][0]["blocks"] = {}
        d["slides"][0]["source"] = ""
        self.assertEqual([e for e in spec.validate(d, skeleton=True) if "archetype" not in e.path], [])


if __name__ == "__main__":
    unittest.main()
