"""Atomicity tests for the Shape-A installers — _extract_bare_dll and _extract_to_mods_folder.

These mods wholly own their BepInEx/plugins/<name>/ folder, so the atomic mechanism is a directory
swap (build the new folder in a sibling staging dir, then rename the old aside and the new in),
NOT the file-merge transaction. The bug being closed: the old code rmtree'd the existing folder
BEFORE extracting the new one, so a failed extraction left the mod gone entirely. Now a failed
install leaves the previous version exactly in place.

Failure is injected by patching the zip extractor to raise mid-way (these functions extract with
ZipFile.extract / extractall, not shutil.copy2, so failing_copy2 wouldn't hit them).
"""
import os
import tempfile
import unittest
import zipfile

from _harness import mods, make_mod, build_zip, reset_store, tree_snapshot, bak_crumbs


class _FailingExtract:
    """Patch zipfile.ZipFile.extract to raise on the Nth member, to simulate a failed extraction."""

    def __init__(self, fail_on):
        self.calls = 0
        self.fail_on = fail_on
        self._real = zipfile.ZipFile.extract

    def __enter__(self):
        outer = self

        def patched(zself, member, path=None, pwd=None):
            outer.calls += 1
            if outer.calls == outer.fail_on:
                raise OSError("simulated extraction failure")
            return outer._real(zself, member, path, pwd)

        zipfile.ZipFile.extract = patched
        return self

    def __exit__(self, *exc):
        zipfile.ZipFile.extract = self._real
        return False


class DirSwapAtomicityTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        os.makedirs(self.mods_path)
        self.scratch = tempfile.mkdtemp(prefix="moddy-scratch-")

    def _zip(self, entries):
        return build_zip(os.path.join(self.scratch, "fixture.zip"), entries)

    def exists(self, rel):
        return os.path.exists(os.path.join(self.mods_path, rel))

    def _record_version(self, mod_id, v):
        # Seed an install record so _backup_version_dir sees a prior version to snapshot.
        mod = make_mod(mod_id=mod_id, filename="Cool", install_type="zip_dir")
        mods.set_installed_record(mod_id, v, "Cool", mod=mod)

    # --- bare_dll -------------------------------------------------------------

    def test_bare_dll_install_and_swap(self):
        tmp_zip = self._zip({"Cool.dll": b"v1", "manifest.json": "{}"})
        mod = make_mod(install_type="zip_dir", filename="Cool")
        self.assertTrue(mods._extract_bare_dll(self.mods_path, mod, "1.0.0", tmp_zip))
        self.assertTrue(self.exists("Cool/Cool.dll"))
        self.assertFalse(self.exists("Cool.moddy-new"))
        self.assertFalse(self.exists("Cool.moddy-old"))

    def test_bare_dll_failed_extraction_keeps_old_install(self):
        # v1 is installed.
        self._record_version("m", "1.0.0")
        os.makedirs(os.path.join(self.mods_path, "Cool"))
        with open(os.path.join(self.mods_path, "Cool", "Cool.dll"), "wb") as f:
            f.write(b"v1")
        before = tree_snapshot(self.mods_path)

        # v2 extraction dies on the 2nd file — the v1 folder must remain intact (old bug: it was
        # already rmtree'd before extraction).
        tmp_zip = self._zip({"Cool.dll": b"v2", "Extra.dll": b"v2extra"})
        mod = make_mod(mod_id="m", install_type="zip_dir", filename="Cool")
        with _FailingExtract(fail_on=2):
            with self.assertRaises(OSError):
                mods._extract_bare_dll(self.mods_path, mod, "2.0.0", tmp_zip)
        self.assertEqual(tree_snapshot(self.mods_path), before, "failed extraction must leave v1 in place")
        self.assertFalse(self.exists("Cool.moddy-new"))
        self.assertFalse(self.exists("Cool.moddy-old"))

    def test_bare_dll_upgrade_keeps_version_backup(self):
        self._record_version("m", "1.0.0")
        os.makedirs(os.path.join(self.mods_path, "Cool"))
        with open(os.path.join(self.mods_path, "Cool", "Cool.dll"), "wb") as f:
            f.write(b"v1")

        tmp_zip = self._zip({"Cool.dll": b"v2"})
        mod = make_mod(mod_id="m", install_type="zip_dir", filename="Cool")
        self.assertTrue(mods._extract_bare_dll(self.mods_path, mod, "2.0.0", tmp_zip))
        # New version live, old version preserved as a .v1.0.0.bak snapshot.
        with open(os.path.join(self.mods_path, "Cool", "Cool.dll"), "rb") as f:
            self.assertEqual(f.read(), b"v2")
        with open(os.path.join(self.mods_path, "Cool.v1.0.0.bak", "Cool.dll"), "rb") as f:
            self.assertEqual(f.read(), b"v1")

    # --- to_mods_folder -------------------------------------------------------

    def test_mods_folder_single_wrapper_swap(self):
        tmp_zip = self._zip({"Wrapper/a.dll": b"a", "Wrapper/sub/b.dll": b"b"})
        mod = make_mod(install_type="zip_dir", filename="Cool")
        self.assertTrue(mods._extract_to_mods_folder(self.mods_path, mod, "1.0.0", tmp_zip))
        self.assertTrue(self.exists("Cool/a.dll"))
        self.assertTrue(self.exists("Cool/sub/b.dll"))
        for crumb in ("Cool.moddy-new", "Cool.moddy-old", "Cool_extract"):
            self.assertFalse(self.exists(crumb), f"{crumb} must be cleaned up")

    def test_mods_folder_multi_dir_swap(self):
        # No single wrapper: multiple top-level dirs extract straight into the staged folder.
        tmp_zip = self._zip({"A/a.dll": b"a", "B/b.dll": b"b"})
        mod = make_mod(install_type="zip_dir", filename="Cool")
        self.assertTrue(mods._extract_to_mods_folder(self.mods_path, mod, "1.0.0", tmp_zip))
        self.assertTrue(self.exists("Cool/A/a.dll"))
        self.assertTrue(self.exists("Cool/B/b.dll"))

    def test_mods_folder_failed_extraction_keeps_old_install(self):
        os.makedirs(os.path.join(self.mods_path, "Cool"))
        with open(os.path.join(self.mods_path, "Cool", "old.dll"), "wb") as f:
            f.write(b"v1")
        before = tree_snapshot(self.mods_path)

        # Multi-dir layout uses extractall; patch that to fail.
        tmp_zip = self._zip({"A/a.dll": b"a", "B/b.dll": b"b"})
        mod = make_mod(install_type="zip_dir", filename="Cool")
        real_extractall = zipfile.ZipFile.extractall
        try:
            def boom(self, *a, **k):
                raise OSError("simulated extractall failure")
            zipfile.ZipFile.extractall = boom
            with self.assertRaises(OSError):
                mods._extract_to_mods_folder(self.mods_path, mod, "2.0.0", tmp_zip)
        finally:
            zipfile.ZipFile.extractall = real_extractall
        self.assertEqual(tree_snapshot(self.mods_path), before, "failed extraction must leave the old folder in place")
        self.assertEqual(bak_crumbs(self.mods_path), [])


if __name__ == "__main__":
    unittest.main()
