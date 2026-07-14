"""Unit tests for mods.find_installed_record / installed_files_present — the case-insensitive
store lookup and the "already installed (record present AND files on disk)" query the dependency
cascades use to decide whether to skip a mod. Both were added when the cascades stopped poking
mods._load_store() directly, and previously had no tests.
"""
import os
import tempfile
import unittest

from _harness import mods, make_game, reset_store


class InstalledQueryTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.game = make_game()  # mods_dir = BepInEx/plugins
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")

    def write(self, rel):
        p = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
        return p

    # ── find_installed_record ────────────────────────────────────────────────
    def test_find_record_exact_and_case_insensitive(self):
        mods.set_installed_record(self.game.appid, "Owner-CoolMod", "1.0.0", "CoolMod", paths=["BepInEx/plugins/CoolMod/x.dll"])
        self.assertIsNotNone(mods.find_installed_record(self.game.appid, "Owner-CoolMod"), "exact-key lookup")
        self.assertIsNotNone(mods.find_installed_record(self.game.appid, "owner-coolmod"), "case-insensitive lookup")
        self.assertIsNotNone(mods.find_installed_record(self.game.appid, "OWNER-COOLMOD"))

    def test_find_record_miss_returns_none(self):
        self.assertIsNone(mods.find_installed_record(self.game.appid, "Nope-Missing"))

    def test_find_record_prefers_exact_key(self):
        # An exact-key hit must short-circuit before the case-insensitive scan.
        mods.set_installed_record(self.game.appid, "Owner-Mod", "2.3.4", "Mod", paths=["BepInEx/plugins/Mod/x.dll"])
        rec = mods.find_installed_record(self.game.appid, "Owner-Mod")
        self.assertEqual(rec.get("version"), "2.3.4")

    # ── installed_files_present ──────────────────────────────────────────────
    def test_present_false_when_files_missing(self):
        mods.set_installed_record(self.game.appid, "Owner-CoolMod", "1.0.0", "CoolMod", paths=["BepInEx/plugins/CoolMod/x.dll"])
        self.assertFalse(
            mods.installed_files_present(self.game, self.install_dir, "Owner-CoolMod"),
            "a record whose files are gone must read as NOT installed (orphan), so a reinstall isn't skipped",
        )

    def test_present_true_when_files_on_disk(self):
        mods.set_installed_record(self.game.appid, "Owner-CoolMod", "1.0.0", "CoolMod", paths=["BepInEx/plugins/CoolMod/x.dll"])
        self.write("BepInEx/plugins/CoolMod/x.dll")
        self.assertTrue(mods.installed_files_present(self.game, self.install_dir, "Owner-CoolMod"))

    def test_present_resolves_id_case_insensitively(self):
        mods.set_installed_record(self.game.appid, "Owner-CoolMod", "1.0.0", "CoolMod", paths=["BepInEx/plugins/CoolMod/x.dll"])
        self.write("BepInEx/plugins/CoolMod/x.dll")
        self.assertTrue(
            mods.installed_files_present(self.game, self.install_dir, "owner-COOLMOD"),
            "the presence query must resolve the record case-insensitively, like the Thunderstore cascade",
        )

    def test_present_false_when_untracked(self):
        self.assertFalse(mods.installed_files_present(self.game, self.install_dir, "Never-Installed"))

    def test_present_for_default_file_install(self):
        # A default 'file' install (no paths): its file lives at <mods_dir>/<filename>.
        mods.set_installed_record(self.game.appid, "Solo-FileMod", "1.0.0", "FileMod.dll")
        self.assertFalse(mods.installed_files_present(self.game, self.install_dir, "Solo-FileMod"))
        self.write("BepInEx/plugins/FileMod.dll")
        self.assertTrue(mods.installed_files_present(self.game, self.install_dir, "Solo-FileMod"))


if __name__ == "__main__":
    unittest.main()
