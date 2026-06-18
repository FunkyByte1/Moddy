"""Characterization tests: lock the CURRENT success-path behavior of each installer so the
Tier-1 staging/transaction refactor can prove it preserves "given this archive, these exact
files land here and this record is written". These are a safety net, not a spec — if the
refactor intentionally changes a path, update the expectation here in the same change.

One test (`test_zip_flat_failed_upgrade_*`) is marked expectedFailure: it asserts the TARGET
behavior (a failed upgrade leaves the old install intact). It documents today's destructive-
pre-clear bug and flips to passing when the fix lands; drop the decorator then.
"""
import asyncio
import os
import unittest

from _harness import mods, utils, make_mod, make_game, build_zip, reset_store, stub_download, tree_snapshot


def run(coro):
    return asyncio.run(coro)


class ExtractorCharacterization(unittest.TestCase):
    """The four synchronous zip_dir extractors, driven directly with a fixture zip on disk."""

    def setUp(self):
        reset_store()
        import tempfile
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.scratch = tempfile.mkdtemp(prefix="moddy-scratch-")

    def _zip(self, entries):
        return build_zip(os.path.join(self.scratch, "fixture.zip"), entries)

    def test_extract_to_game_root(self):
        tmp_zip = self._zip({
            "BepInEx/plugins/Cool/Cool.dll": b"dll",
            "BepInEx/patchers/Cool/patch.dll": b"patch",
            "manifest.json": "{}",
            "icon.png": b"png",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")
        ok = mods._extract_to_game_root(self.install_dir, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        # Only BepInEx/* members land; metadata files are skipped.
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/patchers/Cool/patch.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "manifest.json")))
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["BepInEx/patchers/Cool/patch.dll", "BepInEx/plugins/Cool/Cool.dll"])

    def test_extract_bepinex_subdirs(self):
        tmp_zip = self._zip({
            "plugins/Cool/Cool.dll": b"dll",
            "manifest.json": "{}",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")
        ok = mods._extract_bepinex_subdirs(self.install_dir, mod, "1.0.0", tmp_zip, {"plugins"})
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "BepInEx/manifest.json")))
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["BepInEx/plugins/Cool/Cool.dll"])

    def test_extract_bare_dll(self):
        mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        os.makedirs(mods_path)
        tmp_zip = self._zip({
            "Cool.dll": b"dll",
            "Cool.pdb": b"pdb",
            "manifest.json": "{}",
            "README.md": "hi",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")
        ok = mods._extract_bare_dll(mods_path, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(mods_path, "Cool", "Cool.dll")))
        self.assertTrue(os.path.isfile(os.path.join(mods_path, "Cool", "Cool.pdb")))
        # Metadata at zip root is skipped.
        self.assertFalse(os.path.exists(os.path.join(mods_path, "Cool", "manifest.json")))
        self.assertFalse(os.path.exists(os.path.join(mods_path, "Cool", "README.md")))

    def test_extract_to_mods_folder_single_wrapper(self):
        mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        os.makedirs(mods_path)
        tmp_zip = self._zip({
            "Wrapper/a.dll": b"a",
            "Wrapper/sub/b.dll": b"b",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")
        ok = mods._extract_to_mods_folder(mods_path, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        # The single wrapper folder is stripped: contents land under <filename>/.
        self.assertTrue(os.path.isfile(os.path.join(mods_path, "Cool", "a.dll")))
        self.assertTrue(os.path.isfile(os.path.join(mods_path, "Cool", "sub", "b.dll")))
        # The _extract scratch dir is cleaned up.
        self.assertFalse(os.path.exists(os.path.join(mods_path, "Cool_extract")))


class ZipFlatCharacterization(unittest.TestCase):
    """zip_flat (MelonLoader) — async, driven through a stubbed utils.download."""

    def setUp(self):
        reset_store()
        import tempfile
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="Mods")
        self.mods_path = os.path.join(self.install_dir, "Mods")
        os.makedirs(self.mods_path)
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def test_zip_flat_install_success(self):
        utils.download = stub_download(writes={"Cool.dll": b"v1", "manifest.json": "{}"})
        mod = make_mod(install_type="zip_flat", filename="Cool")
        ok = run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, "1.0.0", "http://x"))
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(self.mods_path, "Cool.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.mods_path, "manifest.json")))
        # The temp zip is cleaned up.
        self.assertFalse(os.path.exists(os.path.join(self.mods_path, "Cool_tmp.zip")))
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["Mods/Cool.dll"])

    @unittest.expectedFailure
    def test_zip_flat_failed_upgrade_keeps_old_install(self):
        """TARGET behavior (currently fails): a v1 mod is installed, then a v2 upgrade is
        attempted but the download dies. The old v1 files must survive — today they're deleted
        before the download even starts (the destructive-pre-clear bug)."""
        utils.download = stub_download(writes={"Cool.dll": b"v1"})
        mod = make_mod(install_type="zip_flat", filename="Cool")
        run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, "1.0.0", "http://x"))
        before = tree_snapshot(self.mods_path)

        utils.download = stub_download(raises=Exception("network died"))
        run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, "2.0.0", "http://x"))
        after = tree_snapshot(self.mods_path)
        self.assertEqual(before, after, "failed upgrade must leave the old install untouched")


if __name__ == "__main__":
    unittest.main()
