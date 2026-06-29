"""Tests for nexus_collections: reference parsing + manifest mod extraction.

(Network fetch/install are exercised on-device; these pin the pure logic — URL/slug parsing and
pulling the right Nexus mods, with their pinned files + FOMOD choices, out of a manifest.)
"""
import unittest

from _harness import reset_store  # noqa: F401 (installs the fake decky)
import nexus_collections as nc


class ParseRefTest(unittest.TestCase):
    def test_full_url_games_path(self):
        self.assertEqual(
            nc.parse_ref("https://www.nexusmods.com/games/monsterhunterworld/collections/vmu2j4", "stardewvalley"),
            ("monsterhunterworld", "vmu2j4"))

    def test_legacy_url_without_games_segment(self):
        self.assertEqual(
            nc.parse_ref("https://next.nexusmods.com/monsterhunterworld/collections/ab12CD", "x"),
            ("monsterhunterworld", "ab12CD"))

    def test_bare_slug_uses_game_domain(self):
        self.assertEqual(nc.parse_ref("vmu2j4", "monsterhunterworld"), ("monsterhunterworld", "vmu2j4"))

    def test_domain_slash_slug(self):
        self.assertEqual(nc.parse_ref("nomanssky/abc123", "monsterhunterworld"), ("nomanssky", "abc123"))

    def test_garbage_returns_none(self):
        self.assertEqual(nc.parse_ref("not a collection!!", "mhw"), (None, None))
        self.assertEqual(nc.parse_ref("", "mhw"), (None, None))


class CollectionModsTest(unittest.TestCase):
    MANIFEST = {
        "mods": [
            {"name": "Armor Pack", "optional": False, "domainName": "monsterhunterworld",
             "author": "A", "version": "1.0",
             "source": {"type": "nexus", "modId": 5076, "fileId": 24095},
             "choices": {"options": [{"name": "Body", "groups": []}]}},
            {"name": "Optional Skin", "optional": True, "domainName": "monsterhunterworld",
             "source": {"type": "nexus", "modId": 100, "fileId": 200}},
            {"name": "Other Game Mod", "optional": False, "domainName": "stardewvalley",
             "source": {"type": "nexus", "modId": 1, "fileId": 2}},
            {"name": "Bundled File", "optional": False, "domainName": "monsterhunterworld",
             "source": {"type": "bundle"}},  # non-nexus — skipped
        ]
    }

    def test_extracts_nexus_mods_for_domain(self):
        mods = nc.collection_mods(self.MANIFEST, "monsterhunterworld")
        names = [m["name"] for m in mods]
        self.assertEqual(names, ["Armor Pack", "Optional Skin"])  # other-game + non-nexus dropped

    def test_pins_file_and_carries_choices_and_optional(self):
        mods = nc.collection_mods(self.MANIFEST, "monsterhunterworld")
        armor = mods[0]
        self.assertEqual((armor["mod_id"], armor["file_id"]), ("5076", "24095"))
        self.assertFalse(armor["optional"])
        self.assertIn("options", armor["choices"])
        self.assertTrue(mods[1]["optional"])

    def test_domain_match_is_case_insensitive(self):
        self.assertEqual(len(nc.collection_mods(self.MANIFEST, "MonsterHunterWorld")), 2)


if __name__ == "__main__":
    unittest.main()
