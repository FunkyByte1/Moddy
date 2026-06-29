"""Tests for nexus_collections: reference parsing + manifest mod extraction.

(Network fetch/install are exercised on-device; these pin the pure logic — URL/slug parsing and
pulling the right Nexus mods, with their pinned files + FOMOD choices, out of a manifest.)
"""
import unittest

from _harness import reset_store  # noqa: F401 (installs the fake decky)
import registry
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


class InstallableModsTest(unittest.TestCase):
    def test_skips_the_modloader_and_optional_mods(self):
        game = registry.get_game_by_appid(582010)  # MHW — modloader is Stracker's Loader (nexus 1982)
        self.assertIsNotNone(game)
        mods = [
            {"mod_id": "1982", "optional": False, "name": "Stracker's Loader"},  # the modloader -> skip
            {"mod_id": "5076", "optional": False, "name": "Grada's Paradise"},   # a real mod -> keep
            {"mod_id": "200", "optional": True, "name": "Optional Skin"},        # optional -> skip
        ]
        result = nc.installable_mods(game, mods, "monsterhunterworld")
        self.assertEqual([m["mod_id"] for m in result], ["5076"])

    def test_skips_smapi_loader_even_though_installed_from_github(self):
        # SMAPI is Stardew's loader but installed from GitHub, not Nexus — a collection references it
        # by its Nexus id (stardewvalley/2400), which nexus_skip_ids must catch so it isn't installed
        # as a mod (the "couldn't install SMAPI" bug).
        game = registry.get_game_by_appid(413150)  # Stardew Valley
        self.assertIsNotNone(game)
        mods = [
            {"mod_id": "2400", "optional": False, "name": "SMAPI"},                 # the loader -> skip
            {"mod_id": "3753", "optional": False, "name": "Stardew Valley Expanded"},  # a real mod -> keep
        ]
        result = nc.installable_mods(game, mods, "stardewvalley")
        self.assertEqual([m["mod_id"] for m in result], ["3753"])

    def test_skips_reframework_loader_even_though_installed_from_github(self):
        # REFramework is RE4/MH-Rise's loader but installed from GitHub (praydog), not Nexus — a
        # collection references it by its Nexus id, which nexus_skip_ids must catch so it isn't
        # installed as a mod (the "couldn't install REFramework" bug). REFramework-D2D (a separate
        # rendering plugin) is NOT the loader and must still install.
        re4 = registry.get_game_by_appid(2050650)  # Resident Evil 4 — REFramework = residentevil42023/12
        self.assertIsNotNone(re4)
        re4_mods = [
            {"mod_id": "12", "optional": False, "name": "REFramework"},          # the loader -> skip
            {"mod_id": "5195", "optional": False, "name": "Some RE4 Mod"},       # a real mod -> keep
        ]
        self.assertEqual([m["mod_id"] for m in nc.installable_mods(re4, re4_mods, "residentevil42023")],
                         ["5195"])

        mhr = registry.get_game_by_appid(1446780)  # Monster Hunter Rise — REFramework = monsterhunterrise/26
        self.assertIsNotNone(mhr)
        mhr_mods = [
            {"mod_id": "26", "optional": False, "name": "REFramework"},          # the loader -> skip
            {"mod_id": "134", "optional": False, "name": "REFramework-D2D"},     # a plugin, not the loader -> keep
        ]
        self.assertEqual([m["mod_id"] for m in nc.installable_mods(mhr, mhr_mods, "monsterhunterrise")],
                         ["134"])


if __name__ == "__main__":
    unittest.main()
