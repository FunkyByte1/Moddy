"""Vanilla-mode round-trip: switching a game to unmodded and back without deleting anything.

Entering vanilla disables every ENABLED mod and the modloader, recording what was on; leaving
restores exactly that — a mod the user had individually disabled must STAY disabled. Driven through
main.Plugin with registry/steam stubbed, but acting on real files via the real toggle_mod /
enable_modloader / disable_modloader, so it integration-tests the whole flow.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, reset_store, make_mod
import main
import steam


def run(coro):
    return asyncio.run(coro)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class VanillaModeTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.ml = registry.ModloaderInfo(
            id="melon", name="MelonLoader",
            source=registry.ModSource(type="github", owner="o", repo="r", asset="a.zip"),
            files=["version.dll"], dirs=["MelonLoader"], indicator="version.dll",
        )
        self.game = registry.GameProfile(id="g", name="G", appid=1, mods_dir="Mods", modloaders=[self.ml])
        self.plugin = main.Plugin()

        self._saved = {}

        def patch(obj, name, value):
            self._saved[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        self.patch = patch
        patch(registry, "get_game_by_appid", lambda appid: self.game)
        patch(steam, "find_game_install_dir", lambda appid: self.install_dir)

        # Modloader installed + enabled.
        write(os.path.join(self.install_dir, "version.dll"), b"loader")
        write(os.path.join(self.install_dir, "MelonLoader", "net6", "x.dll"), b"core")

        # Mod A enabled; Mod B individually disabled by the user (.disabled on disk).
        self._record("modA", "ModA")
        write(os.path.join(self.install_dir, "Mods", "ModA.dll"), b"A")
        self._record("modB", "ModB")
        write(os.path.join(self.install_dir, "Mods", "ModB.dll.disabled"), b"B")

    def tearDown(self):
        for (obj, name), value in self._saved.items():
            setattr(obj, name, value)

    def _record(self, mod_id, filename):
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_flat")
        mods.set_installed_record(self.game.appid, mod_id, "1.0", filename,
                                  paths=[f"Mods/{filename}.dll"], mod=mod)

    def exists(self, *rel):
        return os.path.exists(os.path.join(self.install_dir, *rel))

    def test_enter_then_leave_restores_prior_state(self):
        res = run(self.plugin.set_game_vanilla_mode(1, True))
        self.assertTrue(res["ok"])
        self.assertEqual(res["modloader_id"], "melon")
        self.assertEqual(res["mods_disabled"], 1)  # only the enabled one (ModA)

        # Everything that was on is now off; the loader's tree is parked.
        self.assertTrue(mods.is_game_vanilla(1))
        self.assertFalse(self.exists("version.dll"))
        self.assertTrue(self.exists("version.dll.disabled"))
        self.assertTrue(self.exists("MelonLoader.disabled"))
        self.assertTrue(self.exists("Mods", "ModA.dll.disabled"))
        self.assertFalse(self.exists("Mods", "ModA.dll"))
        # ModB was already disabled and stays exactly as it was.
        self.assertTrue(self.exists("Mods", "ModB.dll.disabled"))

        res = run(self.plugin.set_game_vanilla_mode(1, False))
        self.assertTrue(res["ok"])
        self.assertEqual(res["mods_enabled"], 1)

        # Loader and ModA are back; ModB is STILL disabled (faithful restore, not "enable all").
        self.assertFalse(mods.is_game_vanilla(1))
        self.assertTrue(self.exists("version.dll"))
        self.assertTrue(self.exists("MelonLoader", "net6", "x.dll"))
        self.assertTrue(self.exists("Mods", "ModA.dll"))
        self.assertFalse(self.exists("Mods", "ModA.dll.disabled"))
        self.assertTrue(self.exists("Mods", "ModB.dll.disabled"), "a user-disabled mod must stay disabled after vanilla")
        self.assertFalse(self.exists("Mods", "ModB.dll"))

    def test_enter_is_idempotent(self):
        run(self.plugin.set_game_vanilla_mode(1, True))
        res = run(self.plugin.set_game_vanilla_mode(1, True))
        self.assertTrue(res.get("noop"))
        # Snapshot not overwritten with an empty set.
        self.assertEqual(mods.get_vanilla_state(1)["mods"], ["modA"])

    def test_leave_when_not_vanilla_is_noop(self):
        res = run(self.plugin.set_game_vanilla_mode(1, False))
        self.assertTrue(res.get("noop"))

    def test_mod_uninstalled_while_vanilla_is_skipped_on_restore(self):
        run(self.plugin.set_game_vanilla_mode(1, True))
        # User removes ModA's record while vanilla (e.g. uninstalled it). Restore must not choke.
        mods.clear_installed_record(self.game.appid, "modA")
        res = run(self.plugin.set_game_vanilla_mode(1, False))
        self.assertTrue(res["ok"])
        self.assertEqual(res["mods_enabled"], 0)
        self.assertFalse(mods.is_game_vanilla(1))


class VanillaStateStoreTest(unittest.TestCase):
    """The snapshot store sits beside the mods/modloaders sections and never clobbers them."""

    def setUp(self):
        reset_store()

    def test_set_get_clear_preserves_other_sections(self):
        mod = make_mod(mod_id="m", filename="M", install_type="zip_flat")
        mods.set_installed_record(1, "m", "1.0", "M", paths=["Mods/M.dll"], mod=mod)

        mods.set_vanilla_state(7, {"mods": ["m"], "modloader": "ml", "workshop": []})
        self.assertTrue(mods.is_game_vanilla(7))
        self.assertEqual(mods.get_vanilla_state(7)["mods"], ["m"])
        # The mods section is intact after writing the vanilla section.
        self.assertIsNotNone(mods.get_installed_record(1, "m"))

        mods.set_vanilla_state(7, None)
        self.assertFalse(mods.is_game_vanilla(7))
        self.assertIsNotNone(mods.get_installed_record(1, "m"), "clearing vanilla must not touch mods")


if __name__ == "__main__":
    unittest.main()
