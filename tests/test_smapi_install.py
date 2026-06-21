"""Tests for the zip_smapi (Stardew Valley / SMAPI) installer + the dot-prefix toggle.

A Stardew mod is a folder containing manifest.json at its top, installed under Mods/<folder>/.
Unlike zip_flat (Slime Rancher 2), zip_smapi must:
  - PRESERVE each mod's own folder (zip_flat strips a single wrapper folder),
  - KEEP manifest.json (zip_flat skips it as Thunderstore metadata),
  - fan out MULTIPLE sibling mod folders from one archive (e.g. Stardew Valley Expanded),
  - keep a content pack nested inside a mod WITH its parent (not duplicate it),
  - wrap a manifest-at-archive-root payload in a folder named after the mod,
  - toggle via a leading-dot rename (Mods/<X> <-> Mods/.<X>), not a `.disabled` suffix,
  - install atomically (rollback on a mid-commit failure).

Archives are plain zips so extract_archive takes its zipfile path (no system 7z needed).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import (
    mods, utils, make_mod, make_game, reset_store, stub_download,
    tree_snapshot, failing_copy2, bak_crumbs,
)


def run(coro):
    return asyncio.run(coro)


MANIFEST = '{"Name": "X", "UniqueID": "test.X", "Version": "1.0.0"}'


class SmapiInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-sdv-")
        self.game = make_game(mods_dir="Mods")  # Stardew: mods live in <install_dir>/Mods
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def _install(self, writes, version="1.0.0", mod_id="m", filename="Cool"):
        utils.download = stub_download(writes=writes)
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_smapi")
        res = run(mods.install_mod(self.game, self.install_dir, mod, version, "http://x"))
        return res, mod

    # ── placement ────────────────────────────────────────────────────────────
    def test_single_folder_preserves_name_and_manifest(self):
        res, mod = self._install({
            "CoolMod/manifest.json": MANIFEST,
            "CoolMod/CoolMod.dll": b"MZ\x00",
            "CoolMod/assets/x.png": b"\x89PNG",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/CoolMod/manifest.json"))   # NOT dropped (the zip_flat bug)
        self.assertTrue(self.exists("Mods/CoolMod/CoolMod.dll"))
        self.assertTrue(self.exists("Mods/CoolMod/assets/x.png"))
        self.assertFalse(self.exists("Mods/manifest.json"))          # NOT flattened (the zip_flat bug)
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["Mods/CoolMod"])

    def test_strips_outer_wrapper_folder(self):
        # Nexus downloads often wrap the mod folder in a versioned wrapper dir.
        res, mod = self._install({
            "CoolMod 1.2.3/CoolMod/manifest.json": MANIFEST,
            "CoolMod 1.2.3/CoolMod/CoolMod.dll": b"MZ",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/CoolMod/manifest.json"))
        self.assertFalse(self.exists("Mods/CoolMod 1.2.3"))
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["Mods/CoolMod"])

    def test_multiple_sibling_mod_folders(self):
        res, mod = self._install({
            "ModA/manifest.json": MANIFEST,
            "ModA/a.dll": b"A",
            "ModB/manifest.json": MANIFEST,
            "ModB/b.dll": b"B",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/ModA/manifest.json"))
        self.assertTrue(self.exists("Mods/ModB/manifest.json"))
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["Mods/ModA", "Mods/ModB"])

    def test_nested_content_pack_travels_with_parent(self):
        # A mod that bundles a content pack inside its own folder: only the parent is a top-level
        # entry; the nested manifest must NOT be placed as its own Mods/ folder.
        res, mod = self._install({
            "Big/manifest.json": MANIFEST,
            "Big/Big.dll": b"B",
            "Big/ContentPack/manifest.json": MANIFEST,
            "Big/ContentPack/data.json": b"{}",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/Big/ContentPack/manifest.json"))
        self.assertFalse(self.exists("Mods/ContentPack"))            # not duplicated to the top level
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["Mods/Big"])

    def test_manifest_at_archive_root_is_wrapped(self):
        res, mod = self._install({
            "manifest.json": MANIFEST,
            "content.json": b"{}",
        }, filename="Loose Mod")
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/Loose Mod/manifest.json"))
        self.assertTrue(self.exists("Mods/Loose Mod/content.json"))
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["Mods/Loose Mod"])

    def test_no_manifest_refuses(self):
        # An archive without any manifest.json is not a SMAPI mod — refuse and place nothing.
        res, mod = self._install({
            "readme.txt": b"hello",
            "stuff/data.bin": b"\x00",
        })
        self.assertIs(res, False)
        self.assertIsNone(mods.get_installed_record(mod.id))
        self.assertEqual(os.listdir(os.path.join(self.install_dir, "Mods")), [])

    # ── toggle (dot-prefix) ──────────────────────────────────────────────────
    def test_toggle_uses_dot_prefix(self):
        _res, mod = self._install({"CoolMod/manifest.json": MANIFEST, "CoolMod/c.dll": b"M"})

        self.assertIs(run(mods.toggle_mod(self.game, self.install_dir, mod.id, False)), True)
        self.assertFalse(self.exists("Mods/CoolMod"))
        self.assertTrue(self.exists("Mods/.CoolMod"))                # disabled = leading dot
        self.assertFalse(self.exists("Mods/CoolMod.disabled"))       # NOT the .disabled suffix
        listed = mods.get_installed_mods(self.game, self.install_dir)
        row = next(m for m in listed if m["id"] == mod.id)
        self.assertFalse(row["enabled"])                             # still listed, shown disabled

        self.assertIs(run(mods.toggle_mod(self.game, self.install_dir, mod.id, True)), True)
        self.assertTrue(self.exists("Mods/CoolMod"))
        self.assertFalse(self.exists("Mods/.CoolMod"))
        row = next(m for m in mods.get_installed_mods(self.game, self.install_dir) if m["id"] == mod.id)
        self.assertTrue(row["enabled"])

    # ── uninstall ────────────────────────────────────────────────────────────
    def test_uninstall_enabled(self):
        _res, mod = self._install({"CoolMod/manifest.json": MANIFEST, "CoolMod/c.dll": b"M"})
        self.assertIs(run(mods.uninstall_mod(self.game, self.install_dir, mod.id)), True)
        self.assertFalse(self.exists("Mods/CoolMod"))
        self.assertIsNone(mods.get_installed_record(mod.id))

    def test_uninstall_disabled_removes_dot_folder(self):
        _res, mod = self._install({"CoolMod/manifest.json": MANIFEST, "CoolMod/c.dll": b"M"})
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))
        self.assertTrue(self.exists("Mods/.CoolMod"))
        self.assertIs(run(mods.uninstall_mod(self.game, self.install_dir, mod.id)), True)
        self.assertFalse(self.exists("Mods/.CoolMod"))
        self.assertIsNone(mods.get_installed_record(mod.id))

    def test_uninstall_leaves_other_mods(self):
        _r1, mod1 = self._install({"ModA/manifest.json": MANIFEST}, mod_id="a", filename="A")
        _r2, mod2 = self._install({"ModB/manifest.json": MANIFEST}, mod_id="b", filename="B")
        run(mods.uninstall_mod(self.game, self.install_dir, mod1.id))
        self.assertFalse(self.exists("Mods/ModA"))
        self.assertTrue(self.exists("Mods/ModB/manifest.json"))      # co-resident mod survives

    # ── reinstall / update ───────────────────────────────────────────────────
    def test_reinstall_replaces_and_reenables(self):
        self._install({"CoolMod/manifest.json": MANIFEST, "CoolMod/old.dll": b"OLD"}, version="1.0.0")
        run(mods.toggle_mod(self.game, self.install_dir, "m", False))  # disable, then update over it
        res, mod = self._install({"CoolMod/manifest.json": MANIFEST, "CoolMod/new.dll": b"NEW"}, version="2.0.0")
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/CoolMod/new.dll"))
        self.assertFalse(self.exists("Mods/CoolMod/old.dll"))         # stale file gone
        self.assertFalse(self.exists("Mods/.CoolMod"))               # old disabled folder cleaned up
        self.assertEqual(mods.get_installed_record(mod.id)["version"], "2.0.0")

    # ── multi-file install (the file picker) ───────────────────────────────────
    def _multi_download(self, mapping):
        from _harness import build_zip
        async def _dl(url, dest, appid):
            build_zip(dest, mapping[url])
        utils.download = _dl

    def test_install_smapi_files_combines_multiple(self):
        # SVE-style: two chosen files, each with its own mod folder, install together under one record.
        self._multi_download({
            "u_main": {"SVE_Core/manifest.json": MANIFEST, "SVE_Core/c.dll": b"C"},
            "u_farm": {"IF2R/manifest.json": MANIFEST, "IF2R/content.json": b"{}"},
        })
        mod = make_mod(mod_id="multi", filename="SVE", install_type="zip_smapi")
        res = run(mods.install_smapi_files(self.game, self.install_dir, mod, "1.0", ["u_main", "u_farm"]))
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/SVE_Core/manifest.json"))
        self.assertTrue(self.exists("Mods/IF2R/manifest.json"))
        self.assertEqual(mods.get_installed_record("multi")["paths"], ["Mods/IF2R", "Mods/SVE_Core"])

    def test_install_smapi_files_reinstall_retires_old(self):
        self._multi_download({
            "u_main": {"SVE_Core/manifest.json": MANIFEST},
            "u_farm": {"IF2R/manifest.json": MANIFEST},
        })
        mod = make_mod(mod_id="multi", filename="SVE", install_type="zip_smapi")
        run(mods.install_smapi_files(self.game, self.install_dir, mod, "1.0", ["u_main", "u_farm"]))
        # Reinstall picking ONLY the main file — the previously-installed farm folder is retired.
        res = run(mods.install_smapi_files(self.game, self.install_dir, mod, "1.0", ["u_main"]))
        self.assertIs(res, True)
        self.assertTrue(self.exists("Mods/SVE_Core"))
        self.assertFalse(self.exists("Mods/IF2R"))
        self.assertEqual(mods.get_installed_record("multi")["paths"], ["Mods/SVE_Core"])

    # ── atomicity ────────────────────────────────────────────────────────────
    def test_failed_commit_rolls_back(self):
        # A pre-existing co-resident mod must be byte-identical after a failed install, with no
        # record and no leftover .moddy-bak crumbs.
        keep_dir = os.path.join(self.install_dir, "Mods", "Keep")
        os.makedirs(keep_dir)
        with open(os.path.join(keep_dir, "manifest.json"), "w") as f:
            f.write(MANIFEST)
        before = tree_snapshot(self.install_dir)

        utils.download = stub_download(writes={
            "New/manifest.json": MANIFEST, "New/a.dll": b"A", "New/b.dll": b"B",
        })
        mod = make_mod(mod_id="new", filename="New", install_type="zip_smapi")
        with failing_copy2(fail_on=2):  # fail mid-commit (2nd file placed into the live tree)
            res = run(mods.install_mod(self.game, self.install_dir, mod, "1.0.0", "http://x"))
        self.assertIs(res, False)
        self.assertEqual(tree_snapshot(self.install_dir), before)    # tree restored exactly
        self.assertIsNone(mods.get_installed_record("new"))
        self.assertEqual(bak_crumbs(self.install_dir), [])


if __name__ == "__main__":
    unittest.main()
