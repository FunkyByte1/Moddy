"""Atomicity tests for the zip_flat (MelonLoader) installer after the _StagedInstall conversion.

zip_flat is the harder case: it clears the previous install (which may include whole directories)
and the cleanup is now part of the commit transaction. These assert that a failed upgrade — at the
download OR mid-commit — leaves the prior install byte-identical, and that a successful upgrade
fully replaces it (no stale files from the old version).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import (
    mods, utils, make_mod, make_game, reset_store, tree_snapshot, stub_download,
    failing_copy2, bak_crumbs,
)


def run(coro):
    return asyncio.run(coro)


class FlatAtomicityTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="Mods")
        self.mods_path = os.path.join(self.install_dir, "Mods")
        os.makedirs(self.mods_path)
        self.staging_parent = mods.decky.DECKY_PLUGIN_RUNTIME_DIR
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def _install(self, writes, version):
        utils.download = stub_download(writes=writes)
        mod = make_mod(install_type="zip_flat", filename="Cool")
        return run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, version, "http://x")), mod

    def test_install_with_directory_entry(self):
        # A mod that ships a DLL plus an asset folder: the folder is a top-level tracked entry.
        ok, mod = self._install({"Cool.dll": b"v1", "assets/data.bin": b"data"}, "1.0.0")
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(self.mods_path, "Cool.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.mods_path, "assets", "data.bin")))
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["Mods/Cool.dll", "Mods/assets"])  # top-level entries

    def test_failed_upgrade_midcommit_restores_dir_install(self):
        # v1 ships a DLL and an asset directory.
        self._install({"Cool.dll": b"v1", "assets/old.bin": b"oldasset"}, "1.0.0")
        before = tree_snapshot(self.mods_path)

        # v2 downloads fine but the commit dies on the 2nd file. The old install — including the
        # retired assets/ directory — must come back intact.
        utils.download = stub_download(writes={"Cool.dll": b"v2", "assets/new.bin": b"newasset"})
        mod = make_mod(install_type="zip_flat", filename="Cool")
        with failing_copy2(fail_on=2):
            res = run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, "2.0.0", "http://x"))
        self.assertFalse(res)  # install reports failure
        self.assertEqual(tree_snapshot(self.mods_path), before, "failed mid-commit upgrade must restore the old install")
        self.assertEqual(bak_crumbs(self.install_dir), [])
        self.assertFalse(os.path.exists(os.path.join(self.staging_parent, "Cool_flat_staging")))

    def test_successful_upgrade_replaces_old_install(self):
        # v1 has a DLL and an asset folder that v2 drops entirely.
        self._install({"Cool.dll": b"v1", "assets/old.bin": b"oldasset"}, "1.0.0")
        ok, mod = self._install({"Cool.dll": b"v2"}, "2.0.0")
        self.assertTrue(ok)
        snap = tree_snapshot(self.mods_path)
        self.assertEqual(snap.get("Cool.dll"), b"v2")
        self.assertNotIn("assets/old.bin", snap, "stale files from the old version must be gone")
        self.assertEqual(bak_crumbs(self.install_dir), [])
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["Mods/Cool.dll"])

    def test_reinstall_over_disabled_mod(self):
        # A disabled flat mod has its DLL renamed to *.dll.disabled; reinstalling must clear that
        # form and land an enabled DLL (matching the prior clean-slate behavior).
        ok, mod = self._install({"Cool.dll": b"v1"}, "1.0.0")
        os.rename(os.path.join(self.mods_path, "Cool.dll"), os.path.join(self.mods_path, "Cool.dll.disabled"))
        ok2, _ = self._install({"Cool.dll": b"v2"}, "1.0.0")
        self.assertTrue(ok2)
        self.assertTrue(os.path.isfile(os.path.join(self.mods_path, "Cool.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.mods_path, "Cool.dll.disabled")))


if __name__ == "__main__":
    unittest.main()
