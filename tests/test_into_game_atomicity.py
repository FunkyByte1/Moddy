"""Atomicity tests for mods._install_mod_zip_into_game (the `zip_into_game` install type).

This installer merges a zip's inner folder into the game root (the BepInExPack pattern). It used
to copy straight into install_dir — rmtree-ing existing directories first, with extraction scratch
written *inside* the live dir and no transaction — so a crash mid-copy left a half-written game dir
and a loader (re)install wiped a user's BepInEx/plugins/. It now stages outside the live tree and
commits via _StagedInstall, mirroring modloaders._install_thunderstore_modloader. These tests pin
the three guarantees: merge (don't wipe co-located files), rollback on failure, and no scratch in
the live dir.
"""
import asyncio
import os
import tempfile
import unittest

# _harness installs the fake `decky` module in sys.modules on import, so it must come first.
from _harness import (
    mods, utils, reset_store,
    make_game, make_mod, stub_download, failing_copy2, tree_snapshot, bak_crumbs,
)
import decky


def run(coro):
    return asyncio.run(coro)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


class ZipIntoGameAtomicityTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(appid=1)
        # filename matches the inner pack folder, the way BepInExPack ships (BepInExPack/<files>).
        self.mod = make_mod(mod_id="bepinex.pack", filename="BepInExPack", install_type="zip_into_game")
        self._orig_dl = utils.download

    def tearDown(self):
        utils.download = self._orig_dl

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def test_merges_and_preserves_user_plugins(self):
        # Existing install with a pack core file and a user-installed plugin.
        write(os.path.join(self.install_dir, "winhttp.dll"), b"old")
        write(os.path.join(self.install_dir, "BepInEx/core/BepInEx.Core.dll"), b"old-core")
        write(os.path.join(self.install_dir, "BepInEx/plugins/MyMod/MyMod.dll"), b"user-mod")

        utils.download = stub_download(writes={
            "BepInExPack/winhttp.dll": b"new",
            "BepInExPack/BepInEx/core/BepInEx.Core.dll": b"new-core",
        })
        res = run(mods._install_mod_zip_into_game(self.game, self.install_dir, self.mod, "2.0.0", "http://x"))
        self.assertTrue(res)
        # Pack files overwritten...
        self.assertEqual(read(os.path.join(self.install_dir, "winhttp.dll")), b"new")
        self.assertEqual(read(os.path.join(self.install_dir, "BepInEx/core/BepInEx.Core.dll")), b"new-core")
        # ...and the user's plugin survives the merge (the whole point — the old rmtree wiped it).
        self.assertTrue(self.exists("BepInEx/plugins/MyMod/MyMod.dll"), "user plugin must NOT be wiped")
        self.assertEqual(read(os.path.join(self.install_dir, "BepInEx/plugins/MyMod/MyMod.dll")), b"user-mod")
        self.assertEqual(bak_crumbs(self.install_dir), [])

    def test_failed_install_rolls_back(self):
        write(os.path.join(self.install_dir, "winhttp.dll"), b"old")
        write(os.path.join(self.install_dir, "BepInEx/plugins/MyMod/MyMod.dll"), b"user-mod")
        before = tree_snapshot(self.install_dir)

        utils.download = stub_download(writes={
            "BepInExPack/winhttp.dll": b"new",
            "BepInExPack/BepInEx/core/new.dll": b"new-core",
        })
        with failing_copy2(fail_on=2):  # one file commits, the next fails mid-transaction
            res = run(mods._install_mod_zip_into_game(self.game, self.install_dir, self.mod, "2.0.0", "http://x"))
        self.assertFalse(res)
        self.assertEqual(tree_snapshot(self.install_dir), before, "a failed install must restore the prior dir exactly")
        self.assertEqual(bak_crumbs(self.install_dir), [])

    def test_cancel_returns_none_and_leaves_dir_untouched(self):
        write(os.path.join(self.install_dir, "winhttp.dll"), b"old")
        before = tree_snapshot(self.install_dir)

        utils.download = stub_download(raises=utils.InstallCancelledError())
        res = run(mods._install_mod_zip_into_game(self.game, self.install_dir, self.mod, "2.0.0", "http://x"))
        self.assertIsNone(res, "a cancelled install returns None (not False), per the dispatch contract")
        self.assertEqual(tree_snapshot(self.install_dir), before)

    def test_no_scratch_written_into_the_live_dir(self):
        utils.download = stub_download(writes={"BepInExPack/winhttp.dll": b"new"})
        run(mods._install_mod_zip_into_game(self.game, self.install_dir, self.mod, "2.0.0", "http://x"))
        # The old code wrote `<name>_tmp.zip` / `<name>_extract` into install_dir; the new code keeps
        # all scratch in the runtime dir and cleans it up.
        leftover = [n for n in os.listdir(self.install_dir) if n.endswith(("_tmp.zip", "_extract"))]
        self.assertEqual(leftover, [], "extraction/download scratch must not land in the live game dir")
        runtime = decky.DECKY_PLUGIN_RUNTIME_DIR
        runtime_scratch = [n for n in os.listdir(runtime) if n.startswith("BepInExPack_into_game")]
        self.assertEqual(runtime_scratch, [], "runtime scratch must be cleaned up after install")


if __name__ == "__main__":
    unittest.main()
