"""Tests for the Nexus-sourced modloader (Stracker's Loader for MHW) and the cascade's
modloader-dependency skip.

Pins the fixes for the duplicate-install bug:
  - install_nexus_modloader installs the FULL loader (dinput8.dll + bundled nativePC/plugins/*) and
    tracks the placed paths, so the loader is complete on its own;
  - uninstall removes exactly those paths and leaves other mods' nativePC files intact;
  - the install cascade skips a requirement that IS the game's Nexus modloader (so it isn't also
    installed as a mod).
"""
import asyncio
import os
import shutil
import tempfile
import unittest

from _harness import mods, registry, reset_store, build_zip
import nexus
import utils
import modloaders
import install_cascade


def run(coro):
    return asyncio.run(coro)


def _mhw_game():
    loader = registry.ModloaderInfo(
        id="strackers-loader", name="Stracker's Loader",
        source=registry.ModSource(type="nexus", nexus_domain="monsterhunterworld", mod_id="1982"),
        files=["dinput8.dll"], indicator="dinput8.dll",
    )
    return registry.GameProfile(
        id="mhw", name="Monster Hunter: World", appid=582010, mods_dir="",
        modloaders=[loader],
    )


class NexusModloaderInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="mhw-loader-")
        self.game = _mhw_game()
        self._orig = (utils.download, nexus.primary_file_id, nexus.get_download_url, nexus.get_mod)
        # A loader archive shaped like Stracker's Loader 4.0: the dinput8 proxy, the loader.dll it
        # hands off to, its config, and the bundled plugins under nativePC/plugins/.
        self.archive = build_zip(os.path.join(self.install_dir, "_loader.zip"), {
            "dinput8.dll": b"proxy",
            "loader.dll": b"loader",
            "loader-config.json": b"{}",
            "nativePC/plugins/MonsterLoader.dll": b"ml",
            "nativePC/plugins/QuestLoader.dll": b"ql",
        })
        nexus.primary_file_id = lambda d, m: "1"
        nexus.get_download_url = lambda d, m, f: "http://x"
        nexus.get_mod = lambda d, m: {"version": "4.0.1"}

        async def fake_dl(url, dest, appid, **kw):
            shutil.copy(self.archive, dest)
        utils.download = fake_dl

    def tearDown(self):
        utils.download, nexus.primary_file_id, nexus.get_download_url, nexus.get_mod = self._orig

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def test_install_places_full_loader_payload(self):
        ok = run(modloaders.install_modloader(self.game, self.install_dir, "strackers-loader"))
        self.assertIs(ok, True)
        # The proxy ALONE isn't enough — loader.dll + config + plugins must all land, or dinput8.dll
        # loads with nothing to hand off to ("Stracker's loader error").
        for rel in ("dinput8.dll", "loader.dll", "loader-config.json",
                    "nativePC/plugins/MonsterLoader.dll", "nativePC/plugins/QuestLoader.dll"):
            self.assertTrue(self.exists(rel), f"missing {rel}")
        paths = modloaders.get_modloader_paths(self.game.appid, "strackers-loader")
        self.assertIn("loader.dll", paths)
        self.assertIn("nativePC/plugins/QuestLoader.dll", paths)
        self.assertEqual(modloaders.get_modloader_version(self.game.appid, "strackers-loader"), "4.0.1")

    def test_uninstall_removes_full_loader_but_keeps_other_mods(self):
        run(modloaders.install_modloader(self.game, self.install_dir, "strackers-loader"))
        # A separate mod drops a file in the shared nativePC tree.
        other = os.path.join(self.install_dir, "nativePC", "pl", "armor.tex")
        os.makedirs(os.path.dirname(other), exist_ok=True)
        with open(other, "wb") as f:
            f.write(b"mod")

        ok = run(modloaders.uninstall_modloader(self.game, self.install_dir, "strackers-loader"))
        self.assertIs(ok, True)
        for rel in ("dinput8.dll", "loader.dll", "loader-config.json",
                    "nativePC/plugins/MonsterLoader.dll", "nativePC/plugins/QuestLoader.dll"):
            self.assertFalse(self.exists(rel), f"{rel} should be removed")
        self.assertFalse(self.exists("nativePC/plugins"))  # emptied dir pruned
        self.assertTrue(self.exists("nativePC/pl/armor.tex"))  # other mod survives


class CascadeModloaderSkipTest(unittest.TestCase):
    def test_dep_refs_skips_the_games_nexus_modloader(self):
        game = _mhw_game()
        provider = install_cascade.NexusProvider(denylist=set())
        item = {"requirements": [
            {"domain": "monsterhunterworld", "mod_id": "1982", "name": "Stracker's Loader"},
            {"domain": "monsterhunterworld", "mod_id": "8609", "name": "Some Mod"},
        ]}
        refs = provider.dep_refs(game, item, ("monsterhunterworld", "100"))
        ids = [r[0][1] for r in refs]
        self.assertEqual(ids, ["8609"])  # 1982 (the loader) skipped, real dep kept

    def test_is_game_modloader_matches_only_the_loader(self):
        game = _mhw_game()
        self.assertTrue(install_cascade._is_game_modloader(game, "monsterhunterworld", "1982"))
        self.assertTrue(install_cascade._is_game_modloader(game, "monsterhunterworld", 1982))
        self.assertFalse(install_cascade._is_game_modloader(game, "monsterhunterworld", "8609"))


if __name__ == "__main__":
    unittest.main()
