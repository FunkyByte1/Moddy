"""The schema-1 → schema-2 adopter (store_migration): a legacy installed.json with
top-level "mods"/"modloaders"/"profiles"/"vanilla" is rewritten into per-game "games"
keying on first store access. THROWAWAY like the adopter itself — delete both once the
maintainer's device has migrated.

Routing rules under test: workshop records go by their recorded appid (no disk scan);
every other mod record lands in EVERY installed game whose disk holds its files (a
shared Thunderstore id becomes independent per-game records); modloaders go to the
game declaring the loader id; profiles map slug → appid; vanilla passes through;
workshop_unsub stays global; anything unmatchable is kept under unadopted_*, never
dropped. The original file is preserved as installed.json.pre-schema2.
"""
import json
import os
import tempfile
import unittest

from _harness import decky, mods, make_game, reset_store

import game_store
import json_store
import registry
import steam
import store_migration


def _store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _place_file(install_dir: str, rel: str) -> None:
    path = os.path.join(install_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("x")


LEGACY = {
    "schema": 1,
    "mods": {
        "OnlyA-Mod": {"version": "1.0", "filename": "OnlyA.dll"},
        "Shared-Lib": {"version": "2.0", "filename": "Shared.dll"},
        "workshop.303.111": {
            "version": "subscribed", "filename": "thing", "appid": 303,
            "source": {"type": "steamworkshop", "workshop_id": "111"},
        },
        "Ghost-Mod": {"version": "9.9", "filename": "Ghost.dll"},
    },
    "modloaders": {"bepinex-a": {"version": "5.4.21", "paths": ["winhttp.dll"]}},
    "profiles": {"game101": [{"name": "p1", "created_at": "t", "mods": []}]},
    "vanilla": {"202": {"mods": ["Shared-Lib"], "modloader": None, "workshop": []}},
    "workshop_unsub": {"999": 123.0},
}


class TestStoreMigration(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.dir_a = tempfile.mkdtemp(prefix="moddy-game-a-")
        self.dir_b = tempfile.mkdtemp(prefix="moddy-game-b-")
        self.game_a = make_game(appid=101)
        self.game_a.modloaders = [registry.ModloaderInfo(
            id="bepinex-a", name="BepInEx", source=registry.ModSource(type="github"),
            indicator="winhttp.dll",
        )]
        self.game_b = make_game(appid=202)
        self._orig_games = registry.SUPPORTED_GAMES
        self._orig_find = steam.find_game_install_dir
        registry.SUPPORTED_GAMES = [self.game_a, self.game_b]
        steam.find_game_install_dir = lambda appid: {101: self.dir_a, 202: self.dir_b}.get(appid)
        # On-disk fixture: OnlyA lives in game A; Shared lives in BOTH games; Ghost nowhere.
        _place_file(self.dir_a, "BepInEx/plugins/OnlyA.dll")
        _place_file(self.dir_a, "BepInEx/plugins/Shared.dll")
        _place_file(self.dir_b, "BepInEx/plugins/Shared.dll")

    def tearDown(self):
        registry.SUPPORTED_GAMES = self._orig_games
        steam.find_game_install_dir = self._orig_find

    def _write_legacy(self, data=None) -> None:
        with open(_store_path(), "w") as f:
            json.dump(data if data is not None else LEGACY, f)

    def _adopted(self) -> dict:
        """Trigger adoption through the normal path (first store access) and return the
        rewritten file."""
        mods._load_store(101)
        return json_store.read(_store_path())

    def test_record_lands_only_in_the_game_holding_its_files(self):
        self._write_legacy()
        full = self._adopted()
        self.assertIn("OnlyA-Mod", full["games"]["101"]["mods"])
        self.assertNotIn("OnlyA-Mod", (full["games"].get("202") or {}).get("mods", {}))

    def test_shared_id_is_copied_into_every_holding_game(self):
        self._write_legacy()
        full = self._adopted()
        a = full["games"]["101"]["mods"]["Shared-Lib"]
        b = full["games"]["202"]["mods"]["Shared-Lib"]
        self.assertEqual(a["version"], "2.0")
        self.assertEqual(b["version"], "2.0")
        # Independent records from here on — the point of schema 2.
        mods.set_installed_record(101, "Shared-Lib", "3.0", "Shared.dll")
        self.assertEqual(mods.get_installed_version(101, "Shared-Lib"), "3.0")
        self.assertEqual(mods.get_installed_version(202, "Shared-Lib"), "2.0")

    def test_workshop_record_routes_by_recorded_appid_without_disk(self):
        self._write_legacy()
        full = self._adopted()
        self.assertIn("workshop.303.111", full["games"]["303"]["mods"])

    def test_unmatched_record_is_stashed_not_dropped(self):
        self._write_legacy()
        full = self._adopted()
        self.assertIn("Ghost-Mod", full.get("unadopted_mods", {}))
        for g in full["games"].values():
            self.assertNotIn("Ghost-Mod", g.get("mods", {}))

    def test_modloader_routes_to_declaring_game(self):
        self._write_legacy()
        full = self._adopted()
        self.assertEqual(full["games"]["101"]["modloaders"]["bepinex-a"]["version"], "5.4.21")
        self.assertNotIn("modloaders", full)

    def test_profiles_map_slug_to_appid(self):
        self._write_legacy()
        full = self._adopted()
        self.assertEqual(full["games"]["101"]["profiles"][0]["name"], "p1")
        self.assertNotIn("profiles", full)

    def test_vanilla_and_workshop_unsub_pass_through(self):
        self._write_legacy()
        full = self._adopted()
        self.assertEqual(full["games"]["202"]["vanilla"]["mods"], ["Shared-Lib"])
        self.assertEqual(full["workshop_unsub"], {"999": 123.0})

    def test_original_file_preserved_and_schema_stamped(self):
        self._write_legacy()
        full = self._adopted()
        self.assertEqual(full["schema"], 2)
        with open(_store_path() + ".pre-schema2") as f:
            self.assertEqual(json.load(f), LEGACY)

    def test_adoption_runs_once(self):
        self._write_legacy()
        self._adopted()
        self.assertFalse(store_migration.needs_adoption(json_store.read(_store_path())))
        game_store.reset()
        self.assertEqual(mods.get_installed_version(101, "OnlyA-Mod"), "1.0")  # still reads fine

    def test_fresh_or_empty_store_does_not_trigger(self):
        self.assertFalse(store_migration.needs_adoption({}))
        mods._load_store(101)  # no file at all
        self.assertFalse(os.path.exists(_store_path() + ".pre-schema2"))

    def test_corrupt_legacy_file_takes_the_quarantine_path(self):
        with open(_store_path(), "w") as f:
            f.write('{"mods": {"trunc')
        self.assertEqual(mods._load_store(101), {})
        self.assertFalse(os.path.exists(_store_path() + ".pre-schema2"))
        crumbs = [f for f in os.listdir(decky.DECKY_PLUGIN_SETTINGS_DIR) if ".corrupt-" in f]
        self.assertEqual(len(crumbs), 1)


if __name__ == "__main__":
    unittest.main()
