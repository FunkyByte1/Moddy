"""Atomicity tests for the zip_natives (RE4) installer after the _StagedInstall conversion.

zip_natives is the trickiest convert: it merges a natives/ tree into the game root AND slots .pak
files by scanning the live dir. The conversion moves pak-slot assignment into the commit (so a
retired old pak frees its slot for an upgrade to reclaim) and moves the old-install cleanup into
the transaction (so a dead download — or a parked-then-cancelled variant pick — can't destroy it).

Archives are plain zips so _extract_archive takes its zipfile path (no system 7z needed).
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


class NativesAtomicityTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-re4-")
        self.game = make_game(mods_dir="")  # RE4: mods live in the game root
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def _install(self, writes, version, variant=None, mod_id="m", filename="Cool"):
        utils.download = stub_download(writes=writes)
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_natives")
        res = run(mods._install_mod_zip_natives(self.game, self.install_dir, mod, version, "http://x", variant))
        return res, mod

    # --- success paths --------------------------------------------------------

    def test_natives_install_lowercases_paths(self):
        res, mod = self._install({"natives/STM/Item/Cool.tex": b"tex", "modinfo.ini": "x"}, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("natives/stm/item/cool.tex"))  # RE4 needs lowercase
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["natives/stm/item/cool.tex"])

    def test_pak_install_slots_above_base_game(self):
        # A base-game pak occupies slot 1; the mod pak must land just above it.
        with open(os.path.join(self.install_dir, "re_chunk_000.pak.patch_001.pak"), "wb") as f:
            f.write(b"base")
        res, mod = self._install({"MyMod/mod.pak": b"pak"}, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("re_chunk_000.pak.patch_002.pak"))
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["re_chunk_000.pak.patch_002.pak"])

    # --- reframework/ merge (REFramework plugins & scripts) -------------------

    def test_reframework_plugin_merges_into_root(self):
        # REFramework plugins (e.g. Direct2D) ship a reframework/ tree, NOT natives/ and no .pak.
        # Before, the installer rejected them ("nothing to install"); reframework/ is now a merge root.
        res, mod = self._install({"reframework/plugins/reframework-d2d.dll": b"dll", "README.txt": "x"}, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("reframework/plugins/reframework-d2d.dll"))
        self.assertFalse(self.exists("README.txt"))  # docs beside the tree aren't installed
        self.assertEqual(mods.get_installed_record(mod.id)["paths"], ["reframework/plugins/reframework-d2d.dll"])

    def test_reframework_casing_canonicalized_and_lowercased(self):
        # An archive shipping "REFramework/AutoRun/…" lands in the canonical, lowercased path.
        res, _ = self._install({"REFramework/AutoRun/MyLib.lua": b"lua"}, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("reframework/autorun/mylib.lua"))

    def test_reframework_wrapper_dir_descended(self):
        # Many archives wrap the reframework/ tree under a "<Mod Name>/" dir; the shallowest tree wins.
        res, _ = self._install({"REFramework-D2D/reframework/plugins/d2d.dll": b"dll"}, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("reframework/plugins/d2d.dll"))
        self.assertFalse(self.exists("reframework-d2d/reframework/plugins/d2d.dll"))

    def test_natives_and_reframework_both_merge(self):
        # A mod bundling both an asset tree and a plugin: both land in the game root.
        res, mod = self._install({
            "natives/stm/a.tex": b"tex",
            "reframework/plugins/p.dll": b"dll",
        }, "1.0.0")
        self.assertTrue(res)
        self.assertTrue(self.exists("natives/stm/a.tex"))
        self.assertTrue(self.exists("reframework/plugins/p.dll"))
        self.assertEqual(
            sorted(mods.get_installed_record(mod.id)["paths"]),
            ["natives/stm/a.tex", "reframework/plugins/p.dll"],
        )

    def test_reframework_toggle_and_uninstall(self):
        _, mod = self._install({"reframework/plugins/d2d.dll": b"dll"}, "1.0.0")
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))
        self.assertFalse(self.exists("reframework/plugins/d2d.dll"))
        self.assertTrue(self.exists("reframework/plugins/d2d.dll.disabled"))
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, True))
        self.assertTrue(self.exists("reframework/plugins/d2d.dll"))
        run(mods.uninstall_mod(self.game, self.install_dir, mod.id))
        self.assertFalse(self.exists("reframework/plugins/d2d.dll"))
        self.assertIsNone(mods.get_installed_record(mod.id))

    # --- rollback -------------------------------------------------------------

    def test_failed_midcommit_upgrade_restores_natives_install(self):
        self._install({"natives/stm/a.tex": b"v1a", "natives/stm/b.tex": b"v1b"}, "1.0.0")
        before = tree_snapshot(self.install_dir)

        # v2 downloads/extracts fine, but the 2nd file fails to commit.
        utils.download = stub_download(writes={"natives/stm/a.tex": b"v2a", "natives/stm/b.tex": b"v2b"})
        mod = make_mod(mod_id="m", filename="Cool", install_type="zip_natives")
        with failing_copy2(fail_on=2):
            res = run(mods._install_mod_zip_natives(self.game, self.install_dir, mod, "2.0.0", "http://x"))
        self.assertFalse(res)
        self.assertEqual(tree_snapshot(self.install_dir), before, "failed upgrade must restore the v1 natives files")
        self.assertEqual(bak_crumbs(self.install_dir), [])

    # --- pak slot reclaim on upgrade -----------------------------------------

    def test_pak_upgrade_reclaims_same_slot(self):
        with open(os.path.join(self.install_dir, "re_chunk_000.pak.patch_001.pak"), "wb") as f:
            f.write(b"base")
        self._install({"MyMod/mod.pak": b"pakv1"}, "1.0.0")
        self.assertTrue(self.exists("re_chunk_000.pak.patch_002.pak"))

        # Upgrading must reuse slot 002 (the retired old pak frees it), not stack onto 003.
        res, mod = self._install({"MyMod/mod.pak": b"pakv2"}, "2.0.0")
        self.assertTrue(res)
        self.assertFalse(self.exists("re_chunk_000.pak.patch_003.pak"), "must not stack a new slot")
        with open(os.path.join(self.install_dir, "re_chunk_000.pak.patch_002.pak"), "rb") as f:
            self.assertEqual(f.read(), b"pakv2")
        self.assertEqual(bak_crumbs(self.install_dir), [])

    # --- variant parking must not destroy the old install ---------------------

    def test_variant_park_leaves_old_install_intact(self):
        # v1 is a simple natives mod.
        self._install({"natives/stm/a.tex": b"v1"}, "1.0.0")
        before = tree_snapshot(self.install_dir)

        # "Upgrade" to an archive bundling two pak variants with no choice made: the installer must
        # park (ask the UI) WITHOUT having touched the existing install.
        utils.download = stub_download(writes={"OptionA/a.pak": b"a", "OptionB/b.pak": b"b"})
        mod = make_mod(mod_id="m", filename="Cool", install_type="zip_natives")
        res = run(mods._install_mod_zip_natives(self.game, self.install_dir, mod, "2.0.0", "http://x"))
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("needs_variant"))
        self.assertEqual(len(res["variants"]), 2)
        self.assertEqual(tree_snapshot(self.install_dir), before, "parking a variant pick must not disturb the old install")

    def test_variant_resume_installs_chosen_payload(self):
        # Park on a two-variant archive, then resume with a choice: the cached extract is reused
        # (no second download) and only the chosen variant's pak is committed.
        utils.download = stub_download(writes={"OptionA/a.pak": b"aaa", "OptionB/b.pak": b"bbb"})
        mod = make_mod(mod_id="m", filename="Cool", install_type="zip_natives")
        parked = run(mods._install_mod_zip_natives(self.game, self.install_dir, mod, "1.0.0", "http://x"))
        self.assertTrue(parked.get("needs_variant"))
        chosen = parked["variants"][0]["id"]  # "OptionA"

        # Resume: download must NOT run again (reuse the cached extract), so stub it to fail loudly.
        utils.download = stub_download(raises=AssertionError("resume must not re-download"))
        res = run(mods._install_mod_zip_natives(self.game, self.install_dir, mod, "1.0.0", "http://x", chosen))
        self.assertTrue(res)
        self.assertTrue(self.exists("re_chunk_000.pak.patch_001.pak"))
        self.assertEqual(bak_crumbs(self.install_dir), [])


if __name__ == "__main__":
    unittest.main()
