"""Store schema guard (json_store).

Rolling back to an older Moddy is a supported path (per-SHA nightlies are kept for it), so an
older build will meet a store file written by a newer one. It must not re-save that file: it
would stamp its own schema number onto data in a shape it doesn't understand, and the next
upgrade would then migrate already-migrated data. The file stays read-only for the session and
anything that would need a store write to be tracked (placing mod files) is refused up front.
Older files are upgraded on read through json_store.MIGRATIONS.
"""
import json
import os
import stat
import unittest
from unittest import mock

from _harness import decky, mods, reset_store

import app_settings as settings
import game_store
import json_store
from install_txn import StoreReadOnlyError, _StagedInstall


def _store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _write_raw(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f)


def _read_raw(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


class TestNewerSchema(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.future = {"schema": json_store.SCHEMAS["installed.json"] + 1,
                       "games": {"1": {"mods": {"a": {"version": "9"}}}}, "new_section": {}}
        _write_raw(_store_path(), self.future)

    def test_read_returns_data_but_marks_read_only(self):
        self.assertEqual(json_store.read(_store_path())["new_section"], {})
        self.assertFalse(json_store.is_writable(_store_path()))
        events = json_store.read_only_events()
        self.assertIn({"file": "installed.json", "schema": self.future["schema"],
                       "supported": json_store.SCHEMAS["installed.json"]}, events)

    def test_saves_are_refused_and_file_untouched(self):
        mods.set_installed_record(1, "test.mod", "1.0", "TestMod")
        self.assertFalse(game_store.save())
        self.assertEqual(_read_raw(_store_path()), self.future)

    def test_staged_install_refuses_before_touching_the_tree(self):
        install_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "game")
        os.makedirs(install_dir)
        with self.assertRaises(StoreReadOnlyError):
            with _StagedInstall(install_dir):
                self.fail("placement must not start")
        self.assertEqual(os.listdir(install_dir), [])

    def test_non_integer_schema_is_read_only(self):
        _write_raw(_store_path(), {"schema": "3", "games": {}})
        game_store.reset()
        self.assertFalse(game_store.writable())


class TestMigrations(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.current = json_store.SCHEMAS["installed.json"]

    def test_older_file_is_upgraded_on_read_and_saved_at_current(self):
        _write_raw(_store_path(), {"schema": self.current - 1, "old": 1})
        step = lambda d: {"games": {"1": {"mods": {"m": {"was": d.pop("old")}}}}}
        with mock.patch.dict(json_store.MIGRATIONS["installed.json"], {self.current - 1: step}):
            self.assertEqual(game_store.section(1, "mods"), {"m": {"was": 1}})
            self.assertTrue(game_store.save())  # save() re-reads the file, so it migrates again
        on_disk = _read_raw(_store_path())
        self.assertEqual(on_disk["schema"], self.current)
        self.assertNotIn("old", on_disk)

    def test_missing_migration_step_leaves_file_read_only(self):
        _write_raw(_store_path(), {"schema": self.current - 1, "games": {}})
        with mock.patch.dict(json_store.MIGRATIONS["installed.json"], clear=True):
            self.assertFalse(game_store.writable())

    def test_unstamped_file_reads_as_current(self):
        _write_raw(_store_path(), {"games": {}})
        self.assertTrue(game_store.writable())


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        reset_store()
        settings._SETTINGS = None
        settings._MTIME = None

    def test_settings_written_owner_only_with_schema(self):
        self.assertTrue(settings.set_setting("k", "v"))
        path = settings._path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(_read_raw(path)["schema"], json_store.SCHEMAS["settings.json"])

    def test_corrupt_settings_are_quarantined_not_overwritten(self):
        with open(settings._path(), "w") as f:
            f.write('{"nexus_oauth": {"access_tok')
        self.assertIsNone(settings.get_setting("nexus_oauth"))
        corrupt = [f for f in os.listdir(decky.DECKY_PLUGIN_SETTINGS_DIR) if ".corrupt-" in f]
        self.assertEqual(len(corrupt), 1)

    def test_settings_from_newer_build_are_not_overwritten(self):
        future = {"schema": json_store.SCHEMAS["settings.json"] + 1, "k": "v"}
        _write_raw(settings._path(), future)
        self.assertEqual(settings.get_setting("k"), "v")
        self.assertFalse(settings.set_setting("k", "other"))
        self.assertEqual(_read_raw(settings._path()), future)


if __name__ == "__main__":
    unittest.main()
