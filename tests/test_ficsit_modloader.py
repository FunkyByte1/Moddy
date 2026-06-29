"""Lifecycle tests for the SML (Satisfactory Mod Loader) ficsit-sourced modloader.

SML installs as a wholly-Moddy-owned UE plugin folder at FactoryGame/Mods/SML/. Unlike a DLL-proxy
loader it has no stock game file to preserve, and disabling must MOVE it out of the Mods/ scan root
(an in-place rename wouldn't stop SML loading). These pin: clean install/update (no SML.moddy-orig
cruft, no stale files), the move-out enable/disable, installed-but-disabled detection, and uninstall
in both states.
"""
import asyncio
import json
import os
import tempfile
import unittest
import zipfile

from _harness import registry, utils, reset_store
import modloaders
import ficsit


def run(coro):
    return asyncio.run(coro)


def _make_smod(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


class SmlLoaderTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.get_game_by_appid(526870)
        self.assertIsNotNone(self.game, "Satisfactory must be in the registry")
        self._saved = {"get_mod": ficsit.get_mod, "download": utils.download,
                       "list_versions": ficsit.list_versions}
        ficsit.get_mod = lambda ref, force=False: {
            "id": "x", "mod_reference": ref,
            "versions": [{"id": "v1", "version": "3.12.0", "hash": "", "size": 1,
                          "targets": [{"targetName": "Windows"}], "dependencies": []}],
        }

    def tearDown(self):
        ficsit.get_mod = self._saved["get_mod"]
        utils.download = self._saved["download"]
        ficsit.list_versions = self._saved["list_versions"]

    def _serve(self, files):
        async def _dl(url, dest, appid, expected_hash=None):
            _make_smod(dest, files)
        utils.download = _dl

    def sml_dir(self, *parts):
        return os.path.join(self.install_dir, "FactoryGame", "Mods", "SML", *parts)

    def parked(self):
        return os.path.join(self.install_dir, ".moddy-disabled-mods", "SML")

    def install(self, files):
        self._serve(files)
        return run(modloaders.install_modloader(self.game, self.install_dir, "sml"))

    def test_install_places_plugin_under_mods_sml(self):
        self.assertTrue(self.install({"SML.uplugin": json.dumps({"FriendlyName": "SML"}),
                                      "Binaries/Win64/a.dll": b"DLL"}))
        self.assertTrue(os.path.isfile(self.sml_dir("SML.uplugin")))
        self.assertTrue(os.path.isfile(self.sml_dir("Binaries", "Win64", "a.dll")))
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"))
        self.assertTrue(modloaders.is_modloader_enabled(self.game, self.install_dir, "sml"))
        self.assertEqual(modloaders.get_modloader_version("sml"), "3.12.0")

    def test_update_replaces_cleanly_without_cruft(self):
        self.install({"SML.uplugin": json.dumps({"FriendlyName": "SML"}),
                      "Binaries/Win64/a.dll": b"OLD", "Config/old.ini": b"x"})
        self.install({"SML.uplugin": json.dumps({"FriendlyName": "SML"}),
                      "Binaries/Win64/a.dll": b"NEW", "Content/new.pak": b"P"})
        mods_dir = os.path.join(self.install_dir, "FactoryGame", "Mods")
        self.assertEqual(sorted(os.listdir(mods_dir)), ["SML"], "no SML.moddy-orig cruft beside SML/")
        with open(self.sml_dir("Binaries", "Win64", "a.dll"), "rb") as f:
            self.assertEqual(f.read(), b"NEW")
        self.assertFalse(os.path.exists(self.sml_dir("Config", "old.ini")), "stale file removed")
        self.assertTrue(os.path.exists(self.sml_dir("Content", "new.pak")))

    def test_disable_moves_out_enable_moves_back(self):
        self.install({"SML.uplugin": "{}"})
        self.assertTrue(run(modloaders.disable_modloader(self.game, self.install_dir, "sml")))
        self.assertFalse(os.path.isdir(self.sml_dir()))                 # left the scan root
        self.assertTrue(os.path.isfile(os.path.join(self.parked(), "SML.uplugin")))
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"),
                        "installed-but-disabled still reports installed")
        self.assertFalse(modloaders.is_modloader_enabled(self.game, self.install_dir, "sml"))
        self.assertTrue(run(modloaders.enable_modloader(self.game, self.install_dir, "sml")))
        self.assertTrue(os.path.isfile(self.sml_dir("SML.uplugin")))
        self.assertFalse(os.path.isdir(self.parked()))

    def test_update_while_disabled_preserves_disabled_state(self):
        # Updating SML while it's disabled keeps it disabled (parked, updated) — never silently
        # re-enables it — and leaves no coexisting active+parked copy.
        self.install({"SML.uplugin": json.dumps({"FriendlyName": "SML"}), "old.txt": b"OLD"})
        run(modloaders.disable_modloader(self.game, self.install_dir, "sml"))
        self.install({"SML.uplugin": json.dumps({"FriendlyName": "SML"}), "new.txt": b"NEW"})
        self.assertFalse(os.path.isdir(self.sml_dir()), "stays disabled — not re-enabled into Mods/")
        self.assertTrue(os.path.isfile(os.path.join(self.parked(), "new.txt")), "parked copy updated")
        self.assertFalse(os.path.exists(os.path.join(self.parked(), "old.txt")), "old file replaced")
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"))
        self.assertFalse(modloaders.is_modloader_enabled(self.game, self.install_dir, "sml"))

    def test_failed_update_while_disabled_preserves_installed_loader(self):
        # A failed download mid-update must NOT destroy a working, installed-but-disabled SML.
        self.install({"SML.uplugin": "{}", "keep.txt": b"KEEP"})
        run(modloaders.disable_modloader(self.game, self.install_dir, "sml"))
        async def _boom(url, dest, appid, expected_hash=None):
            raise RuntimeError("network down")
        utils.download = _boom
        self.assertFalse(run(modloaders.install_modloader(self.game, self.install_dir, "sml")))
        # The disabled SML survives intact, and the version store stays consistent with disk.
        self.assertTrue(os.path.isfile(os.path.join(self.parked(), "keep.txt")), "parked SML preserved")
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"))
        self.assertEqual(modloaders.get_modloader_version("sml"), "3.12.0")

    def test_install_pinned_version_resolves_that_version(self):
        # The Mod Loader tab's version picker passes a specific version; install it (not latest).
        ficsit.list_versions = lambda ref, limit=25: [
            {"version": "3.12.0", "version_id": "vNEW", "targets": ["Windows"]},
            {"version": "3.11.0", "version_id": "vOLD", "targets": ["Windows", "WindowsServer"]},
        ]
        captured = {}
        async def _dl(url, dest, appid, expected_hash=None):
            captured["url"] = url
            _make_smod(dest, {"SML.uplugin": "{}"})
        utils.download = _dl
        self.assertTrue(run(modloaders.install_modloader(self.game, self.install_dir, "sml", "3.11.0")))
        self.assertEqual(modloaders.get_modloader_version("sml"), "3.11.0")
        self.assertIn("vOLD", captured["url"])  # pinned version's id, not the latest

    def test_install_pinned_version_missing_windows_build_fails(self):
        ficsit.list_versions = lambda ref, limit=25: [
            {"version": "3.10.0", "version_id": "vSrv", "targets": ["LinuxServer", "WindowsServer"]},
        ]
        self.assertFalse(run(modloaders.install_modloader(self.game, self.install_dir, "sml", "3.10.0")))

    def test_uninstall_while_enabled(self):
        self.install({"SML.uplugin": "{}"})
        self.assertTrue(run(modloaders.uninstall_modloader(self.game, self.install_dir, "sml")))
        self.assertFalse(os.path.isdir(self.sml_dir()))
        self.assertFalse(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"))
        self.assertIsNone(modloaders.get_modloader_version("sml"))

    def test_uninstall_while_disabled_removes_parked(self):
        self.install({"SML.uplugin": "{}"})
        run(modloaders.disable_modloader(self.game, self.install_dir, "sml"))
        self.assertTrue(run(modloaders.uninstall_modloader(self.game, self.install_dir, "sml")))
        self.assertFalse(os.path.isdir(self.parked()))
        self.assertFalse(modloaders.is_modloader_installed(self.game, self.install_dir, "sml"))


if __name__ == "__main__":
    unittest.main()
