"""Step-3 integration tests: the BepInEx merge extractors are now atomic.

A failure partway through committing the payload must leave the live game tree byte-identical to
before — no orphan files (the old bug, where half-merged files survived untracked), co-located
mods untouched, overwritten files restored, and no staging/.moddy-bak crumbs left behind.

Failure is injected by making shutil.copy2 raise on the Nth call. place() uses copy2 to land each
file, while the pre-commit extraction to staging uses copyfileobj — so this fails only the commit
phase, exactly the window the transaction must protect.
"""
import os
import tempfile
import unittest

from _harness import mods, make_mod, build_zip, reset_store, tree_snapshot, failing_copy2, bak_crumbs


class MergeAtomicityTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.scratch = tempfile.mkdtemp(prefix="moddy-scratch-")
        self.staging_parent = mods.decky.DECKY_PLUGIN_RUNTIME_DIR

    def _zip(self, entries):
        return build_zip(os.path.join(self.scratch, "fixture.zip"), entries)

    def test_failed_merge_leaves_no_orphans(self):
        # A co-located mod already lives in the shared plugins tree.
        other = os.path.join(self.install_dir, "BepInEx/plugins/Other/o.dll")
        os.makedirs(os.path.dirname(other))
        with open(other, "wb") as f:
            f.write(b"other")
        before = tree_snapshot(self.install_dir)

        tmp_zip = self._zip({
            "BepInEx/plugins/A/a.dll": b"aaa",
            "BepInEx/plugins/B/b.dll": b"bbb",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")

        with failing_copy2(fail_on=2):  # first file commits, second blows up
            with self.assertRaises(OSError):
                mods._extract_to_game_root(1, self.install_dir, mod, "1.0.0", tmp_zip)

        self.assertEqual(tree_snapshot(self.install_dir), before, "tree must be unchanged after a failed merge")
        self.assertEqual(bak_crumbs(self.install_dir), [], "no .moddy-bak crumbs left behind")
        self.assertIsNone(mods.get_installed_record(1, mod.id), "no record written for a failed install")
        # Staging scratch is cleaned up regardless of outcome.
        self.assertFalse(os.path.exists(os.path.join(self.staging_parent, "Cool_merge_staging")))

    def test_failed_merge_restores_overwritten_file(self):
        # A file the incoming mod will overwrite (mods sharing BepInEx/plugins/Language).
        shared = os.path.join(self.install_dir, "BepInEx/plugins/Language/shared.txt")
        os.makedirs(os.path.dirname(shared))
        with open(shared, "wb") as f:
            f.write(b"original")
        before = tree_snapshot(self.install_dir)

        tmp_zip = self._zip({
            "BepInEx/plugins/Language/shared.txt": b"overwritten",  # placed first
            "BepInEx/plugins/Z/z.dll": b"zzz",                       # then fail here
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")

        with failing_copy2(fail_on=2):
            with self.assertRaises(OSError):
                mods._extract_to_game_root(1, self.install_dir, mod, "1.0.0", tmp_zip)

        self.assertEqual(tree_snapshot(self.install_dir), before, "overwritten file must be restored to its original")

    def test_successful_merge_cleans_staging(self):
        tmp_zip = self._zip({"BepInEx/plugins/A/a.dll": b"aaa"})
        mod = make_mod(install_type="zip_dir", filename="Cool")
        ok = mods._extract_to_game_root(1, self.install_dir, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(os.path.join(self.staging_parent, "Cool_merge_staging")))
        self.assertEqual(bak_crumbs(self.install_dir), [])


if __name__ == "__main__":
    unittest.main()
