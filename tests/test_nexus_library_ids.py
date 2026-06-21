"""Tests for per-game Nexus "library" mods (catalog.library_ids).

Nexus has no library categorization, so specific framework deps (e.g. RE4's REFramework Direct2D /
Lua API) are listed by hand per game and stamped is_library by the backend — hidden from Browse by
default and treated as libraries once installed. Pins:
  - registry.nexus_library_ids derives the full install-id set from catalog.library_ids,
  - the live RE4 profile lists mods 83 + 2670 (guards the registry JSON edit),
  - get_nexus_catalog stamps is_library on those ids only,
  - _build_game_status stamps is_library on installed mods with those ids only.
"""
import asyncio
import tempfile
import unittest

from _harness import mods, registry, reset_store
import main
import nexus
import steam
import catalog


def run(coro):
    return asyncio.run(coro)


RE4_APPID = 2050650
LIB_83 = "nexus.residentevil42023.83"
LIB_2670 = "nexus.residentevil42023.2670"


class NexusLibraryIdsHelperTest(unittest.TestCase):
    def test_helper_derives_full_ids_from_catalog(self):
        game = registry.GameProfile(
            id="g", name="G", appid=1, mods_dir="",
            catalog={"type": "nexus", "nexus_domain": "residentevil42023", "library_ids": ["83", "2670"]},
        )
        self.assertEqual(registry.nexus_library_ids(game), {LIB_83, LIB_2670})

    def test_helper_empty_without_library_ids(self):
        game = registry.GameProfile(
            id="g", name="G", appid=1, mods_dir="",
            catalog={"type": "nexus", "nexus_domain": "residentevil42023"},
        )
        self.assertEqual(registry.nexus_library_ids(game), set())

    def test_helper_empty_for_non_nexus_catalog(self):
        game = registry.GameProfile(
            id="g", name="G", appid=1, mods_dir="",
            catalog={"type": "thunderstore", "library_ids": ["83"]},
        )
        self.assertEqual(registry.nexus_library_ids(game), set())

    def test_live_re4_profile_lists_the_two_framework_mods(self):
        game = registry.get_game_by_appid(RE4_APPID)
        self.assertIsNotNone(game)
        self.assertEqual(registry.nexus_library_ids(game), {LIB_83, LIB_2670})


class NexusCatalogStampTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.plugin = main.Plugin()
        self._orig_search = nexus.search

        def fake_search(domain, query="", page=1, include_adult=False, sort="popularity"):
            return [
                catalog.make_item(name="Direct2D", full_name=LIB_83, owner="x"),
                catalog.make_item(name="Some Mod", full_name="nexus.residentevil42023.999", owner="y"),
            ]
        nexus.search = fake_search

    def tearDown(self):
        nexus.search = self._orig_search

    def test_stamps_is_library_only_on_listed_ids(self):
        items = run(self.plugin.get_nexus_catalog(RE4_APPID))
        by_id = {it["full_name"]: it for it in items}
        self.assertTrue(by_id[LIB_83]["is_library"])
        self.assertFalse(by_id["nexus.residentevil42023.999"]["is_library"])


class NexusInstalledStampTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.tmp = tempfile.mkdtemp(prefix="moddy-re4-")
        self._orig = (steam.find_game_install_dir, mods.get_installed_mods)
        steam.find_game_install_dir = lambda appid, libraries=None: self.tmp
        self.installed = [
            {"id": LIB_83, "filename": "d2d", "enabled": True, "version": "1.0"},
            {"id": "nexus.residentevil42023.10", "filename": "mod", "enabled": True, "version": "1.0"},
        ]
        mods.get_installed_mods = lambda game, install_dir: self.installed

    def tearDown(self):
        steam.find_game_install_dir, mods.get_installed_mods = self._orig

    def test_installed_library_mod_is_flagged(self):
        game = registry.get_game_by_appid(RE4_APPID)
        status = main._build_game_status(game)
        by_id = {im["id"]: im for im in status["installed_mods"]}
        self.assertTrue(by_id[LIB_83]["is_library"])
        self.assertFalse(by_id["nexus.residentevil42023.10"]["is_library"])


if __name__ == "__main__":
    unittest.main()
