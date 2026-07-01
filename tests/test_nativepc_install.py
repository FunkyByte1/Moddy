"""Tests for the zip_nativepc (Monster Hunter: World) installer.

zip_nativepc shares its core (_install_mod_loose_merge) with RE4's zip_natives, so the atomicity
of merge/rollback is already covered by test_natives_atomicity. These tests pin the behaviours
that DIFFER for MHW + Stracker's Loader:
  - the loose tree is `nativePC/` (not `natives/`),
  - casing is PRESERVED (Stracker's matches the mod's original path; RE4 lowercases),
  - there is NO `.pak` slotting,
  - per-file tracking, toggle (rename to *.disabled), and uninstall still work.

Archives are plain zips so extract_archive takes its zipfile path (no system 7z needed).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import (
    mods, utils, make_mod, make_game, reset_store, stub_download,
)


def run(coro):
    return asyncio.run(coro)


class NativePCInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-mhw-")
        self.game = make_game(mods_dir="")  # MHW: mods live in the game root
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def _install(self, writes, version="1.0.0", variant=None, mod_id="m", filename="Cool"):
        utils.download = stub_download(writes=writes)
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_nativepc")
        res = run(mods._install_mod_zip_nativepc(self.game, self.install_dir, mod, version, "http://x", variant))
        return res, mod

    def test_nativepc_merges_into_root_preserving_case(self):
        res, mod = self._install({
            "nativePC/pl/f_equip/Body.tex": b"tex",
            "modinfo.ini": "x",  # ignored metadata beside the tree
        })
        self.assertTrue(res)
        # Case is preserved (unlike RE4's lowercasing) — Stracker's matches the original path.
        self.assertTrue(self.exists("nativePC/pl/f_equip/Body.tex"))
        self.assertFalse(self.exists("nativepc/pl/f_equip/body.tex"))
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["paths"], ["nativePC/pl/f_equip/Body.tex"])

    def test_nativepc_unwraps_wrapper_folder(self):
        # Many MHW mods wrap nativePC/ inside a "<Mod Name>/" folder; the shallowest tree is used.
        res, _ = self._install({"Cool Armor/nativePC/pl/armor.mod3": b"m"})
        self.assertTrue(res)
        self.assertTrue(self.exists("nativePC/pl/armor.mod3"))

    def test_canonicalizes_nativepc_casing(self):
        # An archive that ships "NativePC/" must still land in the canonical "nativePC/".
        res, mod = self._install({"NativePC/pl/a.tex": b"t"})
        self.assertTrue(res)
        self.assertTrue(self.exists("nativePC/pl/a.tex"))
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["paths"], ["nativePC/pl/a.tex"])

    def test_fluffy_packaging_wraps_content_into_nativepc(self):
        # The dominant MHW Nexus shape (Fluffy Mod Manager): NO nativePC/ folder, just modinfo.ini +
        # a preview image + the content folders at the root. The content must be wrapped into
        # nativePC/, and the metadata/preview must NOT be installed.
        res, mod = self._install({
            "modinfo.ini": "name=Cool",
            "preview.jpg": b"img",
            "README.txt": "hi",
            "pl/f_equip/Body.tex": b"t",
            "stm/foo.tex": b"t2",
        })
        self.assertTrue(res)
        self.assertTrue(self.exists("nativePC/pl/f_equip/Body.tex"))
        self.assertTrue(self.exists("nativePC/stm/foo.tex"))
        self.assertFalse(self.exists("nativePC/modinfo.ini"))
        self.assertFalse(self.exists("nativePC/preview.jpg"))
        self.assertFalse(self.exists("nativePC/README.txt"))
        self.assertEqual(
            sorted(mods.get_installed_record(self.game.appid, mod.id)["paths"]),
            ["nativePC/pl/f_equip/Body.tex", "nativePC/stm/foo.tex"],
        )

    def test_fluffy_single_wrapper_dir_is_stripped(self):
        # When everything sits under one "<Mod Name>/" wrapper (no nativePC/), descend into it so the
        # tree isn't buried a level too deep. "Cool Mod" is not a nativePC content folder, so it's a
        # wrapper.
        res, _ = self._install({"Cool Mod/pl/a.tex": b"t", "Cool Mod/readme.txt": "x"})
        self.assertTrue(res)
        self.assertTrue(self.exists("nativePC/pl/a.tex"))
        self.assertFalse(self.exists("nativePC/Cool Mod/pl/a.tex"))

    def test_lone_content_folder_is_not_stripped(self):
        # A mod touching only one content folder (e.g. an armor mod → just `pl/`) also presents as a
        # single top-level dir + metadata, but `pl` is real nativePC content and must NOT be stripped.
        res, mod = self._install({"pl/f_equip/Body.tex": b"t", "modinfo.ini": "x", "preview.jpg": b"i"})
        self.assertTrue(res)
        self.assertTrue(self.exists("nativePC/pl/f_equip/Body.tex"))
        self.assertFalse(self.exists("nativePC/f_equip/Body.tex"))
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["paths"], ["nativePC/pl/f_equip/Body.tex"])

    def test_no_content_only_metadata_fails(self):
        # An archive with nothing but metadata has nothing to install.
        res, _ = self._install({"modinfo.ini": "x", "preview.png": b"img"})
        self.assertFalse(res)

    def test_no_pak_slotting(self):
        # A stray .pak in an MHW archive must NOT be slotted as an re_chunk patch (RE4-only).
        res, _ = self._install({"nativePC/pl/a.tex": b"t", "extra.pak": b"pak"})
        self.assertTrue(res)
        self.assertFalse(self.exists("re_chunk_000.pak.patch_001.pak"))
        self.assertFalse(self.exists("re_chunk_000.pak.patch_002.pak"))

    def test_toggle_and_uninstall(self):
        _, mod = self._install({"nativePC/pl/a.tex": b"t", "nativePC/pl/b.tex": b"t2"})
        # Disable renames every tracked file to *.disabled.
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))
        self.assertFalse(self.exists("nativePC/pl/a.tex"))
        self.assertTrue(self.exists("nativePC/pl/a.tex.disabled"))
        # Re-enable renames them back.
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, True))
        self.assertTrue(self.exists("nativePC/pl/a.tex"))
        # Uninstall removes all tracked files and the record.
        run(mods.uninstall_mod(self.game, self.install_dir, mod.id))
        self.assertFalse(self.exists("nativePC/pl/a.tex"))
        self.assertFalse(self.exists("nativePC/pl/b.tex"))
        self.assertIsNone(mods.get_installed_record(self.game.appid, mod.id))


if __name__ == "__main__":
    unittest.main()
