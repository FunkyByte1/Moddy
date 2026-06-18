"""Characterization tests for enable/disable (toggle_mod).

Toggle is rename-only and infers state from disk (no record write), so it doesn't need the
staging/transaction treatment that installs do. But it's core, previously untested behavior, and
mods.py is under active refactor — these lock the on-disk effect of each install shape's toggle so
a future change can't silently regress it.

Shapes covered: file (.bak), zip_flat (*.dll.disabled), zip_natives (*.disabled on every tracked
file), zip_dir DLL-style (per-file paths from the merge installers AND folder-walk for
bare_dll/to_mods_folder), and zip_dir lovelyignore-style (.lovelyignore marker).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, make_mod, make_game, reset_store


def run(coro):
    return asyncio.run(coro)


def register(mod_id, filename, install_type, paths=None):
    """Persist an install record the way the real installers do, so toggle reads a realistic record."""
    mod = make_mod(mod_id=mod_id, filename=filename, install_type=install_type)
    mods.set_installed_record(mod_id, "1.0.0", filename, paths=paths, mod=mod)
    return mod


def touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class ToggleCharacterization(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    # --- file-based: <name> <-> <name>.bak ------------------------------------

    def test_file_based(self):
        game = make_game(mods_dir="BepInEx/plugins")
        register("m", "Cool.dll", "file")
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool.dll"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool.dll.bak"))
        self.assertFalse(self.exists("BepInEx/plugins/Cool.dll"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool.dll"))
        self.assertFalse(self.exists("BepInEx/plugins/Cool.dll.bak"))

    # --- zip_flat: *.dll <-> *.dll.disabled -----------------------------------

    def test_zip_flat(self):
        game = make_game(mods_dir="Mods")
        register("m", "Cool", "zip_flat", paths=["Mods/Cool.dll"])
        touch(os.path.join(self.install_dir, "Mods/Cool.dll"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("Mods/Cool.dll.disabled"))
        self.assertFalse(self.exists("Mods/Cool.dll"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertTrue(self.exists("Mods/Cool.dll"))

    # --- zip_natives: every tracked file <-> *.disabled -----------------------

    def test_zip_natives_flips_all_tracked_files(self):
        game = make_game(mods_dir="")  # RE4: mods live in the game root
        register("m", "Cool", "zip_natives", paths=["natives/stm/a.tex", "natives/stm/b.mesh"])
        touch(os.path.join(self.install_dir, "natives/stm/a.tex"))
        touch(os.path.join(self.install_dir, "natives/stm/b.mesh"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("natives/stm/a.tex.disabled"))
        self.assertTrue(self.exists("natives/stm/b.mesh.disabled"))
        self.assertFalse(self.exists("natives/stm/a.tex"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertTrue(self.exists("natives/stm/a.tex"))
        self.assertTrue(self.exists("natives/stm/b.mesh"))

    # --- zip_dir, DLL-style ---------------------------------------------------

    def test_zip_dir_per_file_paths(self):
        # The shape produced by the merge installers: paths point at individual DLLs.
        game = make_game(mods_dir="BepInEx/plugins")
        register("m", "Cool", "zip_dir", paths=["BepInEx/plugins/Cool/Cool.dll"])
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool/Cool.dll.disabled"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool/Cool.dll"))

    def test_zip_dir_folder_walk_leaves_non_dll_files(self):
        # The shape produced by bare_dll / to_mods_folder: no paths, toggle walks the mod folder
        # and flips only *.dll, leaving assets alone.
        game = make_game(mods_dir="BepInEx/plugins")
        register("m", "Cool", "zip_dir")  # no paths -> walks mods_path/<filename>
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll"))
        touch(os.path.join(self.install_dir, "BepInEx/plugins/Cool/data.txt"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool/Cool.dll.disabled"))
        self.assertTrue(self.exists("BepInEx/plugins/Cool/data.txt"), "non-DLL assets must not be touched")

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertTrue(self.exists("BepInEx/plugins/Cool/Cool.dll"))

    # --- zip_dir, lovelyignore-style (Lovely / Steamodded) --------------------

    def test_zip_dir_lovelyignore(self):
        ml = registry.ModloaderInfo(id="lovely", name="Lovely",
                                    source=registry.ModSource(type="github"), mod_toggle="lovelyignore")
        game = make_game(mods_dir="Mods")
        game.modloaders = [ml]
        register("m", "MyLua", "zip_dir")
        touch(os.path.join(self.install_dir, "Mods/MyLua/main.lua"))

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", False)))
        self.assertTrue(self.exists("Mods/MyLua/.lovelyignore"), "disable drops a .lovelyignore marker")
        self.assertTrue(self.exists("Mods/MyLua/main.lua"), "files are left in place")

        self.assertTrue(run(mods.toggle_mod(game, self.install_dir, "m", True)))
        self.assertFalse(self.exists("Mods/MyLua/.lovelyignore"), "enable removes the marker")

    # --- no-op guard ----------------------------------------------------------

    def test_toggle_returns_false_when_nothing_to_do(self):
        game = make_game(mods_dir="Mods")
        register("m", "Cool", "zip_flat", paths=["Mods/Cool.dll"])
        # No file on disk for this game (e.g. installed for a different game) -> nothing renamed.
        self.assertFalse(run(mods.toggle_mod(game, self.install_dir, "m", False)))


if __name__ == "__main__":
    unittest.main()
