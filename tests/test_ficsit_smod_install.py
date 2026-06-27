"""End-to-end tests for the zip_smod install type (Satisfactory .smod / SML plugins).

A .smod is a zip of a UE plugin's loose files (<ModRef>.uplugin, Content/, Binaries/Win64/). It
installs as one folder under FactoryGame/Mods/<ModRef>/ — or Mods/GameFeatures/<ModRef>/ when the
uplugin sets GameFeature — reusing the folder-per-mod (NMS) machinery: move-out disable + whole-
folder uninstall. These pin the placement, the GameFeature split, the move-out toggle, and that the
folder is named by the ModReference (uplugin stem), which is what SML loads by.
"""
import asyncio
import json
import os
import tempfile
import unittest

from _harness import mods, utils, make_game, make_mod, reset_store, stub_download


def run(coro):
    return asyncio.run(coro)


class SmodInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(appid=526870, mods_dir="FactoryGame/Mods")
        self._saved_download = utils.download

    def tearDown(self):
        utils.download = self._saved_download

    def _mod(self, ref="CoolMod", filename=None):
        return make_mod(mod_id=f"ficsit.{ref}", filename=filename or ref,
                        install_type="zip_smod", mod_reference=ref)

    def _smod(self, ref="CoolMod", game_feature=False):
        up = {"FriendlyName": ref, "Version": 1}
        if game_feature:
            up["GameFeature"] = True
        return {f"{ref}.uplugin": json.dumps(up), f"Content/Paks/{ref}.pak": b"PAKDATA"}

    def install(self, mod, writes):
        utils.download = stub_download(writes=writes)
        return run(mods.install_mod(self.game, self.install_dir, mod, version="1.0", url="http://x"))

    def mods_dir(self, *parts):
        return os.path.join(self.install_dir, "FactoryGame", "Mods", *parts)

    def parked(self, ref):
        return os.path.join(self.install_dir, ".moddy-disabled-mods", ref)

    def test_installs_into_mods_modref_folder(self):
        self.assertTrue(self.install(self._mod("CoolMod"), self._smod("CoolMod")))
        self.assertTrue(os.path.isfile(self.mods_dir("CoolMod", "CoolMod.uplugin")))
        self.assertTrue(os.path.isfile(self.mods_dir("CoolMod", "Content", "Paks", "CoolMod.pak")))
        self.assertEqual(mods.get_installed_record("ficsit.CoolMod")["paths"],
                         ["FactoryGame/Mods/CoolMod"])

    def test_game_feature_goes_to_gamefeatures_subdir(self):
        self.assertTrue(self.install(self._mod("FeatureMod"), self._smod("FeatureMod", game_feature=True)))
        self.assertTrue(os.path.isfile(self.mods_dir("GameFeatures", "FeatureMod", "FeatureMod.uplugin")))
        self.assertFalse(os.path.isdir(self.mods_dir("FeatureMod")))
        self.assertEqual(mods.get_installed_record("ficsit.FeatureMod")["paths"],
                         ["FactoryGame/Mods/GameFeatures/FeatureMod"])

    def test_folder_named_by_uplugin_not_catalog_filename(self):
        # Folder MUST be the ModReference (uplugin stem) — that's the name SML loads by — even if the
        # catalog filename differs.
        self.assertTrue(self.install(self._mod("CoolMod", filename="wrong-name"), self._smod("CoolMod")))
        self.assertTrue(os.path.isdir(self.mods_dir("CoolMod")))
        self.assertFalse(os.path.isdir(self.mods_dir("wrong-name")))

    def test_wrapped_archive_installs_unnested(self):
        # A .smod that nests its files under a wrapper dir must still land directly in Mods/<ModRef>/,
        # with GameFeature read from the (nested) uplugin — not produce Mods/<x>/<wrapper>/...
        wrapped = {"CoolMod/CoolMod.uplugin": json.dumps({"FriendlyName": "CoolMod", "GameFeature": True}),
                   "CoolMod/Content/x.pak": b"P"}
        self.assertTrue(self.install(self._mod("CoolMod"), wrapped))
        self.assertTrue(os.path.isfile(self.mods_dir("GameFeatures", "CoolMod", "CoolMod.uplugin")))
        self.assertTrue(os.path.isfile(self.mods_dir("GameFeatures", "CoolMod", "Content", "x.pak")))
        self.assertFalse(os.path.isdir(self.mods_dir("GameFeatures", "CoolMod", "CoolMod")))

    def test_archive_without_uplugin_is_refused(self):
        # No .uplugin anywhere = a malformed .smod; refuse rather than mis-install a folder SML can't load.
        self.assertFalse(self.install(self._mod("CoolMod"), {"Content/x.pak": b"P", "readme.txt": b"hi"}))
        self.assertFalse(os.path.isdir(self.mods_dir("CoolMod")))
        self.assertIsNone(mods.get_installed_record("ficsit.CoolMod"))

    def test_disable_moves_folder_out_then_reenable_moves_back(self):
        self.install(self._mod("CoolMod"), self._smod("CoolMod"))
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "ficsit.CoolMod", False)))
        # An in-place rename wouldn't hide it from SML, so the folder must LEAVE Mods/.
        self.assertFalse(os.path.isdir(self.mods_dir("CoolMod")))
        self.assertTrue(os.path.isfile(os.path.join(self.parked("CoolMod"), "CoolMod.uplugin")))
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "ficsit.CoolMod", True)))
        self.assertTrue(os.path.isfile(self.mods_dir("CoolMod", "CoolMod.uplugin")))
        self.assertFalse(os.path.isdir(self.parked("CoolMod")))

    def test_game_feature_mod_toggle_and_uninstall_roundtrip(self):
        # The GameFeatures/<ModRef> path (a separator in the tracked rel) must round-trip through the
        # basename-keyed staging dir and back, and uninstall must clear both forms.
        self.install(self._mod("FeatureMod"), self._smod("FeatureMod", game_feature=True))
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "ficsit.FeatureMod", False)))
        self.assertFalse(os.path.isdir(self.mods_dir("GameFeatures", "FeatureMod")))
        self.assertTrue(os.path.isfile(os.path.join(self.parked("FeatureMod"), "FeatureMod.uplugin")))
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "ficsit.FeatureMod", True)))
        self.assertTrue(os.path.isfile(self.mods_dir("GameFeatures", "FeatureMod", "FeatureMod.uplugin")))
        run(mods.toggle_mod(self.game, self.install_dir, "ficsit.FeatureMod", False))
        self.assertTrue(run(mods.uninstall_mod(self.game, self.install_dir, "ficsit.FeatureMod")))
        self.assertFalse(os.path.isdir(self.parked("FeatureMod")))
        self.assertIsNone(mods.get_installed_record("ficsit.FeatureMod"))

    def test_installed_listing_tracks_enabled_state(self):
        self.install(self._mod("CoolMod"), self._smod("CoolMod"))
        listed = {m["id"]: m for m in mods.get_installed_mods(self.game, self.install_dir)}
        self.assertTrue(listed["ficsit.CoolMod"]["enabled"])
        run(mods.toggle_mod(self.game, self.install_dir, "ficsit.CoolMod", False))
        listed = {m["id"]: m for m in mods.get_installed_mods(self.game, self.install_dir)}
        self.assertIn("ficsit.CoolMod", listed)         # still present (parked), now disabled
        self.assertFalse(listed["ficsit.CoolMod"]["enabled"])

    def test_uninstall_removes_folder_and_record(self):
        self.install(self._mod("CoolMod"), self._smod("CoolMod"))
        self.assertTrue(run(mods.uninstall_mod(self.game, self.install_dir, "ficsit.CoolMod")))
        self.assertFalse(os.path.isdir(self.mods_dir("CoolMod")))
        self.assertIsNone(mods.get_installed_record("ficsit.CoolMod"))

    def test_uninstall_while_disabled_removes_parked_folder(self):
        self.install(self._mod("CoolMod"), self._smod("CoolMod"))
        run(mods.toggle_mod(self.game, self.install_dir, "ficsit.CoolMod", False))
        self.assertTrue(run(mods.uninstall_mod(self.game, self.install_dir, "ficsit.CoolMod")))
        self.assertFalse(os.path.isdir(self.parked("CoolMod")))
        self.assertIsNone(mods.get_installed_record("ficsit.CoolMod"))

    def test_reinstall_replaces_cleanly(self):
        self.install(self._mod("CoolMod"), self._smod("CoolMod"))
        # Reinstall with a different payload file — the folder is retired then replaced (no stale file).
        utils.download = stub_download(writes={"CoolMod.uplugin": json.dumps({"FriendlyName": "CoolMod"}),
                                               "Content/Paks/New.pak": b"NEW"})
        self.assertTrue(run(mods.install_mod(self.game, self.install_dir, self._mod("CoolMod"),
                                             version="2.0", url="http://x")))
        self.assertTrue(os.path.isfile(self.mods_dir("CoolMod", "Content", "Paks", "New.pak")))
        self.assertFalse(os.path.isfile(self.mods_dir("CoolMod", "Content", "Paks", "CoolMod.pak")))


if __name__ == "__main__":
    unittest.main()
