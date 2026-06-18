"""Tests for mods.mod_files_present — the disk-presence check that gates the install "already
installed; skipping" shortcut.

The bug it fixes: uninstalling the BepInEx modloader rmtree's BepInEx/, deleting every plugin's
files while their installed.json records remain. The cascade used to treat a mod as installed
whenever a record existed, so reinstalling completed instantly without re-placing files and the
mod never reappeared. Presence must be judged from the disk, not the record.
"""
import os
import tempfile
import unittest

from _harness import mods, make_mod, make_game, reset_store


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def register(mod_id, filename, install_type, paths=None):
    mod = make_mod(mod_id=mod_id, filename=filename, install_type=install_type)
    mods.set_installed_record(mod_id, "1.0.0", filename, paths=paths, mod=mod)
    return mods.get_installed_record(mod_id)


class ModPresenceTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="BepInEx/plugins")

    def test_zip_dir_present_then_orphaned(self):
        rec = register("m", "Cool", "zip_dir", paths=["BepInEx/plugins/Cool/Cool.dll"])
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll"))
        self.assertTrue(mods.mod_files_present(self.game, self.install_dir, rec))

        # Simulate a BepInEx uninstall wiping the plugin tree — the record stays.
        import shutil
        shutil.rmtree(os.path.join(self.install_dir, "BepInEx"))
        self.assertFalse(mods.mod_files_present(self.game, self.install_dir, rec),
                         "orphaned record (files gone) must read as NOT present")

    def test_zip_dir_disabled_form_counts_as_present(self):
        rec = register("m", "Cool", "zip_dir", paths=["BepInEx/plugins/Cool/Cool.dll"])
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll.disabled"))
        self.assertTrue(mods.mod_files_present(self.game, self.install_dir, rec))

    def test_zip_flat_present(self):
        game = make_game(mods_dir="Mods")
        rec = register("m", "Cool", "zip_flat", paths=["Mods/Cool.dll"])
        self.assertFalse(mods.mod_files_present(game, self.install_dir, rec))
        touch(os.path.join(self.install_dir, "Mods/Cool.dll"))
        self.assertTrue(mods.mod_files_present(game, self.install_dir, rec))

    def test_file_present_and_bak(self):
        rec = register("m", "Cool.dll", "file")
        mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        self.assertFalse(mods.mod_files_present(self.game, self.install_dir, rec))
        touch(os.path.join(mods_path, "Cool.dll"))
        self.assertTrue(mods.mod_files_present(self.game, self.install_dir, rec))
        # Disabled form (.bak) also counts as present.
        os.rename(os.path.join(mods_path, "Cool.dll"), os.path.join(mods_path, "Cool.dll.bak"))
        self.assertTrue(mods.mod_files_present(self.game, self.install_dir, rec))

    def test_steamworkshop_record_is_authoritative(self):
        # Workshop files are Steam-managed (not under install_dir), so the record is authoritative.
        mod = make_mod(mod_id="w", filename="WS", install_type="steamworkshop")
        mod.source.type = "steamworkshop"
        mods.set_installed_record("w", "1.0.0", "WS", mod=mod)
        rec = mods.get_installed_record("w")
        self.assertTrue(mods.mod_files_present(self.game, self.install_dir, rec))


class ModsUnderModloaderTest(unittest.TestCase):
    """mods_under_modloader — which installed mods a loader uninstall would delete (used to warn)."""

    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")

    def test_bepinex_lists_plugins_under_its_dir(self):
        game = make_game(mods_dir="BepInEx/plugins")
        register("m", "Cool", "zip_dir", paths=["BepInEx/plugins/Cool/Cool.dll"])
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll"))
        # An absent (orphaned) mod must NOT be listed.
        register("gone", "Gone", "zip_dir", paths=["BepInEx/plugins/Gone/Gone.dll"])

        affected = mods.mods_under_modloader(game, self.install_dir, ["BepInEx"], ["winhttp.dll"])
        ids = {m["id"] for m in affected}
        self.assertEqual(ids, {"m"})  # present plugin listed; orphaned "gone" excluded
        self.assertTrue(affected[0]["name"])  # carries a display name for the dialog

    def test_melonloader_does_not_list_mods_in_separate_dir(self):
        # MelonLoader's own dir is MelonLoader/; mods live in Mods/, which a loader uninstall
        # (rmtree of MelonLoader/ + version.dll) leaves untouched — so nothing is at risk.
        game = make_game(mods_dir="Mods")
        register("m", "Cool", "zip_flat", paths=["Mods/Cool.dll"])
        touch(os.path.join(self.install_dir, "Mods/Cool.dll"))

        affected = mods.mods_under_modloader(game, self.install_dir, ["MelonLoader"], ["version.dll"])
        self.assertEqual(affected, [])


if __name__ == "__main__":
    unittest.main()
