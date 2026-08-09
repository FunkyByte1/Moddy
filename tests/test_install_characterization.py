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
        mod = make_mod(install_type="zip_dir", filename="Cool", owner="Team", repo="Cool")
        ok = mods._extract_to_game_root(1, self.install_dir, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        # BepInEx/* members land verbatim; root-level files follow r2modman's default rule
        # into the per-mod plugins folder (mods like Cloudburst read their icon.png there).
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Cool/Cool.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/patchers/Cool/patch.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Team-Cool/manifest.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Team-Cool/icon.png")))
        rec = mods.get_installed_record(1, mod.id)
        self.assertEqual(rec["paths"], [
            "BepInEx/patchers/Cool/patch.dll",
            "BepInEx/plugins/Cool/Cool.dll",
            "BepInEx/plugins/Team-Cool/icon.png",
            "BepInEx/plugins/Team-Cool/manifest.json",
        ])

    def test_extract_to_game_root_keeps_root_level_plugin_dll(self):
        """SeekersPatcher shape: BepInEx/patchers/* plus the package's PLUGIN half as a
        root-level DLL. Dropping the root DLL leaves BepInDependency chains unsatisfiable
        and (for SeekersPatcher specifically) breaks the SotS addressables remap."""
        tmp_zip = self._zip({
            "BepInEx/patchers/SeekersPatcher/SeekersPatcher.dll": b"patcher",
            "SeekersPatcherDLL.dll": b"plugin-half",
            "manifest.json": "{}",
        })
        mod = make_mod(mod_id="pseudopulse-SeekersPatcher", install_type="zip_dir",
                       filename="SeekersPatcher", owner="pseudopulse", repo="SeekersPatcher")
        ok = mods._extract_to_game_root(1, self.install_dir, mod, "1.0.0", tmp_zip)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(os.path.join(
            self.install_dir, "BepInEx/patchers/SeekersPatcher/SeekersPatcher.dll")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.install_dir, "BepInEx/plugins/pseudopulse-SeekersPatcher/SeekersPatcherDLL.dll")))

    def test_extract_bepinex_subdirs(self):
        tmp_zip = self._zip({
            "plugins/Cool/Cool.dll": b"dll",
            "manifest.json": "{}",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool", owner="Team", repo="Cool")
        ok = mods._extract_bepinex_subdirs(1, self.install_dir, mod, "1.0.0", tmp_zip, {"plugins"})
        self.assertTrue(ok)
        # plugins/ content lands in a per-mod <Owner>-<Name>/ subfolder (r2modman layout);
        # root-level metadata joins it there rather than being dropped.
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Team-Cool/Cool/Cool.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "BepInEx/manifest.json")))
        rec = mods.get_installed_record(1, mod.id)
        self.assertEqual(rec["paths"], [
            "BepInEx/plugins/Team-Cool/Cool/Cool.dll",
            "BepInEx/plugins/Team-Cool/manifest.json",
        ])

    def test_extract_bepinex_subdirs_patchers_and_core(self):
        tmp_zip = self._zip({
            "plugins/Cool.dll": b"dll",
            "patchers/CoolPatcher.dll": b"patch",
            "monomod/Cool.mm.dll": b"mm",
            "core/CoreLib.dll": b"core",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool", owner="Team", repo="Cool")
        ok = mods._extract_bepinex_subdirs(1, self.install_dir, mod, "1.0.0", tmp_zip,
                                           {"plugins", "patchers", "monomod", "core"})
        self.assertTrue(ok)
        # plugins/patchers/monomod are per-mod; core/ merges as-is (loader plumbing, fixed paths).
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Team-Cool/Cool.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/patchers/Team-Cool/CoolPatcher.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/monomod/Team-Cool/Cool.mm.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/core/CoreLib.dll")))

    def test_extract_bepinex_subdirs_no_shared_folder_collision(self):
        """Two packages both shipping plugins/assetbundles/ must not merge into one shared
        folder — mods enumerate "their" assetbundles dir wholesale at runtime, and loading
        another mod's bundle crashes Unity's content load (the RoR2 SurvivorDLC 73% hang)."""
        zip_a = build_zip(os.path.join(self.scratch, "a.zip"), {
            "plugins/MSU.Runtime.dll": b"msu",
            "plugins/assetbundles/runtimebundle": b"msu-bundle",
        })
        zip_b = build_zip(os.path.join(self.scratch, "b.zip"), {
            "plugins/Starstorm2.dll": b"ss2",
            "plugins/assetbundles/ss2bundle": b"ss2-bundle",
        })
        mod_a = make_mod(mod_id="TeamMoonstorm-MSU", install_type="zip_dir", filename="MSU",
                         owner="TeamMoonstorm", repo="MSU")
        mod_b = make_mod(mod_id="TeamMoonstorm-Starstorm2", install_type="zip_dir", filename="Starstorm2",
                         owner="TeamMoonstorm", repo="Starstorm2")
        self.assertTrue(mods._extract_bepinex_subdirs(1, self.install_dir, mod_a, "1.0.0", zip_a, {"plugins"}))
        self.assertTrue(mods._extract_bepinex_subdirs(1, self.install_dir, mod_b, "1.0.0", zip_b, {"plugins"}))
        base = os.path.join(self.install_dir, "BepInEx/plugins")
        self.assertTrue(os.path.isfile(os.path.join(base, "TeamMoonstorm-MSU/assetbundles/runtimebundle")))
        self.assertTrue(os.path.isfile(os.path.join(base, "TeamMoonstorm-Starstorm2/assetbundles/ss2bundle")))
        # No shared assetbundles dir at the plugins root.
        self.assertFalse(os.path.exists(os.path.join(base, "assetbundles")))

    def test_extract_bepinex_subdirs_reinstall_retires_old_flat_layout(self):
        """A reinstall must remove the files the previous install placed (recorded `paths`),
        even when the layout moved — otherwise BepInEx double-loads the stale flat copy."""
        tmp_zip = self._zip({"plugins/Cool.dll": b"v2"})
        mod = make_mod(install_type="zip_dir", filename="Cool", owner="Team", repo="Cool")
        # Simulate a pre-existing install under the OLD flat layout.
        old_flat = os.path.join(self.install_dir, "BepInEx/plugins/Cool.dll")
        os.makedirs(os.path.dirname(old_flat))
        with open(old_flat, "wb") as f:
            f.write(b"v1")
        mods.set_installed_record(1, mod.id, "0.9.0", mod.filename, paths=["BepInEx/plugins/Cool.dll"], mod=mod)
        ok = mods._extract_bepinex_subdirs(1, self.install_dir, mod, "1.0.0", tmp_zip, {"plugins"})
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(old_flat))
        self.assertTrue(os.path.isfile(os.path.join(self.install_dir, "BepInEx/plugins/Team-Cool/Cool.dll")))
        rec = mods.get_installed_record(1, mod.id)
        self.assertEqual(rec["paths"], ["BepInEx/plugins/Team-Cool/Cool.dll"])

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
        ok = mods._extract_bare_dll(1, mods_path, mod, "1.0.0", tmp_zip)
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
        ok = mods._extract_to_mods_folder(1, mods_path, mod, "1.0.0", tmp_zip)
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
        rec = mods.get_installed_record(1, mod.id)
        self.assertEqual(rec["paths"], ["Mods/Cool.dll"])

    def test_zip_flat_failed_upgrade_keeps_old_install(self):
        """A v1 mod is installed, then a v2 upgrade is attempted but the download dies. The old v1
        files must survive — previously they were deleted before the download even started (the
        destructive-pre-clear bug, fixed by downloading before any cleanup)."""
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
