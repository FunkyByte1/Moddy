"""Unit tests for the _StagedInstall transaction primitive, in isolation from any installer.

Proves the core guarantee before it's wired into real install paths: on clean exit the new
files are placed and backups dropped; on ANY exception the live tree is restored byte-for-byte
— files we created removed, files we displaced or retired put back, directories we created
pruned. utils.InstallCancelledError is just another exception here and must roll back too.
"""
import os
import tempfile
import unittest

from _harness import mods, utils, tree_snapshot


def write(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


class StagedInstallTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="moddy-live-")     # the live game tree
        self.stage = tempfile.mkdtemp(prefix="moddy-stage-")    # where "downloaded" files sit

    def staged(self, rel: str, data: bytes = b"new") -> str:
        return write(os.path.join(self.stage, rel), data)

    # --- commit ---------------------------------------------------------------

    def test_commit_places_new_files(self):
        with mods._StagedInstall(self.root) as txn:
            txn.place(self.staged("a.dll"), "BepInEx/plugins/a.dll")
            txn.place(self.staged("b.dll"), "BepInEx/plugins/sub/b.dll")
        self.assertEqual(tree_snapshot(self.root), {
            "BepInEx/plugins/a.dll": b"new",
            "BepInEx/plugins/sub/b.dll": b"new",
        })

    def test_commit_overwrites_and_drops_backup(self):
        write(os.path.join(self.root, "BepInEx/plugins/a.dll"), b"old")
        with mods._StagedInstall(self.root) as txn:
            txn.place(self.staged("a.dll", b"new"), "BepInEx/plugins/a.dll")
        # New content wins, and no .moddy-bak crumb survives a successful commit.
        self.assertEqual(tree_snapshot(self.root), {"BepInEx/plugins/a.dll": b"new"})

    # --- rollback -------------------------------------------------------------

    def test_rollback_on_exception_restores_tree(self):
        write(os.path.join(self.root, "BepInEx/plugins/keep.dll"), b"keep")
        write(os.path.join(self.root, "BepInEx/plugins/over.dll"), b"old")
        before = tree_snapshot(self.root)
        with self.assertRaises(RuntimeError):
            with mods._StagedInstall(self.root) as txn:
                txn.place(self.staged("over.dll", b"new"), "BepInEx/plugins/over.dll")  # overwrite
                txn.place(self.staged("fresh.dll"), "BepInEx/plugins/new/fresh.dll")    # brand new
                raise RuntimeError("boom mid-install")
        self.assertEqual(tree_snapshot(self.root), before, "tree must be byte-identical after rollback")

    def test_rollback_prunes_created_dirs(self):
        with self.assertRaises(RuntimeError):
            with mods._StagedInstall(self.root) as txn:
                txn.place(self.staged("x.dll"), "BepInEx/plugins/deep/x.dll")
                raise RuntimeError("boom")
        # The directories we made for the doomed file are gone (no empty BepInEx/plugins/deep left).
        self.assertFalse(os.path.exists(os.path.join(self.root, "BepInEx")))

    def test_rollback_keeps_preexisting_dirs(self):
        os.makedirs(os.path.join(self.root, "BepInEx", "plugins", "Other"))
        write(os.path.join(self.root, "BepInEx/plugins/Other/o.dll"), b"other")
        with self.assertRaises(RuntimeError):
            with mods._StagedInstall(self.root) as txn:
                txn.place(self.staged("x.dll"), "BepInEx/plugins/x.dll")
                raise RuntimeError("boom")
        # A co-located mod's dir and files must survive our rollback.
        self.assertTrue(os.path.isfile(os.path.join(self.root, "BepInEx/plugins/Other/o.dll")))

    def test_cancellation_rolls_back(self):
        write(os.path.join(self.root, "a.dll"), b"old")
        before = tree_snapshot(self.root)
        with self.assertRaises(utils.InstallCancelledError):
            with mods._StagedInstall(self.root) as txn:
                txn.place(self.staged("a.dll", b"new"), "a.dll")
                raise utils.InstallCancelledError("cancelled")
        self.assertEqual(tree_snapshot(self.root), before)

    # --- retire (upgrade old-file cleanup) ------------------------------------

    def test_retire_then_fail_restores_old_install(self):
        # Old install: two files, one of which the new version won't replace.
        write(os.path.join(self.root, "Mods/Cool.dll"), b"v1")
        write(os.path.join(self.root, "Mods/Cool.extra"), b"v1extra")
        before = tree_snapshot(self.root)
        with self.assertRaises(Exception):
            with mods._StagedInstall(self.root) as txn:
                txn.retire("Mods/Cool.dll")
                txn.retire("Mods/Cool.extra")
                txn.place(self.staged("Cool.dll", b"v2"), "Mods/Cool.dll")
                raise Exception("download of remaining files failed")
        self.assertEqual(tree_snapshot(self.root), before, "failed upgrade must restore the old install exactly")

    def test_retire_handles_disabled_form(self):
        # A disabled mod's file lives as *.disabled; retire must set it aside too.
        write(os.path.join(self.root, "natives/x.pak.disabled"), b"v1")
        with self.assertRaises(Exception):
            with mods._StagedInstall(self.root) as txn:
                txn.retire("natives/x.pak")  # active form absent; .disabled present
                raise Exception("boom")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "natives/x.pak.disabled")))

    def test_retire_then_commit_removes_old(self):
        write(os.path.join(self.root, "Mods/Old.dll"), b"v1")
        with mods._StagedInstall(self.root) as txn:
            txn.retire("Mods/Old.dll")
            txn.place(self.staged("New.dll"), "Mods/New.dll")
        snap = tree_snapshot(self.root)
        self.assertNotIn("Mods/Old.dll", snap)
        self.assertEqual(snap.get("Mods/New.dll"), b"new")


if __name__ == "__main__":
    unittest.main()
