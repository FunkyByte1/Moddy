"""Tests for the startup crumb sweep — resolving install artifacts a hard crash strands mid-commit.

Normal installs clean these up; only a kill-9/reboot during a commit leaves them. The sweep
restores a set-aside backup whose primary file is gone (the crash hit between "move aside" and
"write new"), discards stale backups whose primary is back, drops discardable staging, and clears
runtime scratch.
"""
import os
import tempfile
import unittest

from _harness import mods, make_mod, make_game, reset_store


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def mkdir(path):
    os.makedirs(path, exist_ok=True)
    return path


class RuntimeScratchSweepTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.runtime = mods.decky.DECKY_PLUGIN_RUNTIME_DIR

    def test_clears_scratch_dirs_and_temps(self):
        mkdir(os.path.join(self.runtime, "Cool_merge_staging"))
        mkdir(os.path.join(self.runtime, "Mod_extract"))
        touch(os.path.join(self.runtime, "Mod_tmp.zip"))
        touch(os.path.join(self.runtime, "Mod_tmp.archive"))
        touch(os.path.join(self.runtime, "keep.json"))  # unrelated runtime file stays

        mods.sweep_runtime_scratch()

        leftovers = set(os.listdir(self.runtime))
        self.assertEqual(leftovers, {"keep.json"})


class InstallCrumbSweepTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="BepInEx/plugins")
        self.mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        os.makedirs(self.mods_path)
        # A tracked record so its path dir (BepInEx/plugins/Cool/) is in the sweep scope.
        mod = make_mod(mod_id="m", filename="Cool", install_type="zip_dir")
        mods.set_installed_record("m", "1.0.0", "Cool", paths=["BepInEx/plugins/Cool/Cool.dll"], mod=mod)

    def exists(self, *parts):
        return os.path.exists(os.path.join(self.install_dir, *parts))

    def test_bak_restored_when_primary_missing(self):
        # Crash between set-aside and write: the file lives only in its .moddy-bak.
        cool_dir = os.path.join(self.mods_path, "Cool")
        touch(os.path.join(cool_dir, "Cool.dll.moddy-bak"), b"orig")
        mods.sweep_install_crumbs(self.game, self.install_dir)
        self.assertTrue(self.exists("BepInEx/plugins/Cool/Cool.dll"))
        self.assertFalse(self.exists("BepInEx/plugins/Cool/Cool.dll.moddy-bak"))
        with open(os.path.join(self.mods_path, "Cool", "Cool.dll"), "rb") as f:
            self.assertEqual(f.read(), b"orig")

    def test_bak_discarded_when_primary_present(self):
        # Commit moved past this file: primary is the new version, the .moddy-bak is stale.
        touch(os.path.join(self.install_dir, "winhttp.dll"), b"new")
        touch(os.path.join(self.install_dir, "winhttp.dll.moddy-bak"), b"old")
        mods.sweep_install_crumbs(self.game, self.install_dir)
        self.assertFalse(self.exists("winhttp.dll.moddy-bak"))
        with open(os.path.join(self.install_dir, "winhttp.dll"), "rb") as f:
            self.assertEqual(f.read(), b"new")  # the new version is left untouched

    def test_moddy_old_restored_when_primary_missing(self):
        # Shape-A swap interrupted after renaming the old folder aside, before moving new in.
        old_dir = os.path.join(self.mods_path, "Folder.moddy-old")
        touch(os.path.join(old_dir, "a.dll"), b"old")
        mods.sweep_install_crumbs(self.game, self.install_dir)
        self.assertTrue(self.exists("BepInEx/plugins/Folder/a.dll"))
        self.assertFalse(self.exists("BepInEx/plugins/Folder.moddy-old"))

    def test_moddy_old_discarded_when_primary_present(self):
        mkdir(os.path.join(self.mods_path, "Folder"))
        touch(os.path.join(self.mods_path, "Folder", "new.dll"), b"new")
        mkdir(os.path.join(self.mods_path, "Folder.moddy-old"))
        mods.sweep_install_crumbs(self.game, self.install_dir)
        self.assertFalse(self.exists("BepInEx/plugins/Folder.moddy-old"))
        self.assertTrue(self.exists("BepInEx/plugins/Folder/new.dll"))

    def test_moddy_new_discarded(self):
        # Pure staging scratch — always removed (a missing primary is covered by .moddy-old).
        mkdir(os.path.join(self.mods_path, "Folder.moddy-new"))
        touch(os.path.join(self.mods_path, "Folder.moddy-new", "x.dll"))
        mods.sweep_install_crumbs(self.game, self.install_dir)
        self.assertFalse(self.exists("BepInEx/plugins/Folder.moddy-new"))


if __name__ == "__main__":
    unittest.main()
