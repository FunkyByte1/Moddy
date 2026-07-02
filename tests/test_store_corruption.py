"""installed.json corruption handling (json_store).

A corrupt store must not brick the plugin: the bad file is quarantined aside as
installed.json.corrupt-<ts> (kept for hand recovery), reads return an empty store, and
subsequent saves rebuild a fresh file — the pre-json_store behavior was an empty-looking
library whose saves ALL failed (each save re-read the corrupt file to preserve sections).
The once-per-session .bak snapshot is the recovery source of last resort, and must never
be clobbered by a rebuilt-from-scratch store after a quarantine.
"""
import json
import os
import unittest

from _harness import decky, mods, reset_store

import game_store
import json_store
import modloaders
import profiles


def _store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _quarantined() -> list[str]:
    d = decky.DECKY_PLUGIN_SETTINGS_DIR
    return [f for f in os.listdir(d) if ".corrupt-" in f]


def _write_raw(text: str) -> None:
    with open(_store_path(), "w") as f:
        f.write(text)


class TestStoreCorruption(unittest.TestCase):
    def setUp(self):
        reset_store()
        json_store._quarantined.clear()

    def test_corrupt_store_is_quarantined_and_reads_empty(self):
        _write_raw('{"mods": {"trunc')
        self.assertEqual(mods._load_store(1), {})
        self.assertEqual(len(_quarantined()), 1)
        self.assertFalse(os.path.exists(_store_path()))  # moved aside, not left in place

    def test_saves_work_again_after_quarantine(self):
        _write_raw("not json at all")
        self.assertEqual(mods._load_store(1), {})
        mods.set_installed_record(1, "test.mod", "1.0", "TestMod")
        game_store.reset()  # drop the cache; force a re-read from disk
        rec = mods.get_installed_record(1, "test.mod")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["version"], "1.0")
        self.assertEqual(len(_quarantined()), 1)

    def test_wrong_shape_counts_as_corrupt(self):
        _write_raw(json.dumps(["valid json", "but not an object"]))
        self.assertEqual(json_store.read(_store_path()), {})
        self.assertEqual(len(_quarantined()), 1)

    def test_bak_snapshot_on_first_clean_read(self):
        mods.set_installed_record(1, "test.mod", "1.0", "TestMod")
        game_store.reset()
        mods._load_store(1)
        with open(_store_path() + ".bak") as f:
            self.assertEqual(json.load(f)["games"]["1"]["mods"]["test.mod"]["version"], "1.0")

    def test_bak_survives_quarantine(self):
        path = _store_path()
        good = {"mods": {"test.mod": {"version": "1.0", "filename": "TestMod"}}}
        with open(path + ".bak", "w") as f:
            json.dump(good, f)
        _write_raw("garbage")
        self.assertEqual(json_store.read(path), {})
        # A store rebuilt after the quarantine must not overwrite the last good snapshot.
        json_store.write(path, {"mods": {}})
        self.assertEqual(json_store.read(path)["mods"], {})
        with open(path + ".bak") as f:
            self.assertEqual(json.load(f), good)

    def test_quarantine_is_reported_for_the_ui(self):
        _write_raw("{oops")
        self.assertEqual(json_store.quarantine_events(), [])
        mods._load_store(1)
        events = json_store.quarantine_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["file"], "installed.json")
        self.assertIn(".corrupt-", events[0]["to"])
        # A clean read reports nothing new.
        game_store.reset()
        mods.set_installed_record(1, "test.mod", "1.0", "TestMod")
        mods._load_store(1)
        self.assertEqual(len(json_store.quarantine_events()), 1)

    def test_writes_are_stamped_with_schema_and_plugin_version(self):
        decky.DECKY_PLUGIN_VERSION = "9.9.9"
        try:
            json_store.write(_store_path(), {"mods": {}})
        finally:
            del decky.DECKY_PLUGIN_VERSION
        data = json_store.read(_store_path())
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["written_by"], "9.9.9")

    def test_update_section_preserves_other_sections(self):
        path = _store_path()
        json_store.write(path, {"mods": {"a": {"version": "1"}}, "vanilla": {"42": {"mods": []}}})
        json_store.update_section(path, "modloaders", {"bepinex": {"version": "5.4"}})
        data = json_store.read(path)
        self.assertEqual(data["mods"], {"a": {"version": "1"}})
        self.assertEqual(data["vanilla"], {"42": {"mods": []}})
        self.assertEqual(data["modloaders"], {"bepinex": {"version": "5.4"}})

    def test_all_sections_recover_after_one_quarantine(self):
        _write_raw("{oops")
        # First reader quarantines; the rest see a clean empty store, and every writer works.
        self.assertEqual(mods._load_store(1), {})
        self.assertIsNone(modloaders.get_modloader_version(1, "bepinex"))
        self.assertEqual(profiles.list_profiles("game1"), [])
        self.assertEqual(len(_quarantined()), 1)
        mods.set_installed_record(1, "test.mod", "1.0", "TestMod")
        modloaders.set_modloader_version(1, "bepinex", "5.4")
        self.assertTrue(profiles.save_profile("game1", "main", []))
        full = json_store.read(_store_path())
        self.assertEqual(full["games"]["1"]["mods"]["test.mod"]["version"], "1.0")
        self.assertEqual(full["games"]["1"]["modloaders"]["bepinex"]["version"], "5.4")
        self.assertEqual(full["profiles"]["game1"][0]["name"], "main")


if __name__ == "__main__":
    unittest.main()
