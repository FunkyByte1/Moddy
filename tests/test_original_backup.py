"""Tests for durable preservation of an original (stock) game file a mod overwrites.

A mod whose destination collides with a file the game shipped (the single-file `file` installer
into a game-root game, or any loose-merge that lands on a stock path) must not destroy that file.
The transaction preserves it as `*.moddy-orig`, and uninstall / disable restore it so the game
can return to vanilla. Stock always round-trips; first capture wins so a second mod over the same
path can't clobber the true original.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, make_mod, make_game, reset_store, tree_snapshot, stub_download
import modloaders
import github
import registry


def run(coro):
    return asyncio.run(coro)


def write(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def raw_download(data: bytes):
    """A utils.download replacement that lays down raw bytes (a single-file mod payload, not a zip)."""
    async def _dl(url, dest, appid):
        with open(dest, "wb") as f:
            f.write(data)
    return _dl


class TransactionForeignPreservationTest(unittest.TestCase):
    """The _StagedInstall durable-promotion contract, in isolation."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="moddy-live-")
        self.stage = tempfile.mkdtemp(prefix="moddy-stage-")

    def staged(self, rel: str, data: bytes) -> str:
        return write(os.path.join(self.stage, rel), data)

    def test_foreign_displaced_file_preserved_as_orig(self):
        write(os.path.join(self.root, "natives/x.tex"), b"stock")
        with mods._StagedInstall(self.root, is_foreign=lambda p: True) as txn:
            txn.place(self.staged("x.tex", b"mod"), "natives/x.tex")
        self.assertEqual(read(os.path.join(self.root, "natives/x.tex")), b"mod")
        self.assertEqual(read(os.path.join(self.root, "natives/x.tex" + mods._MODDY_ORIG_SUFFIX)), b"stock")

    def test_default_no_is_foreign_discards_backup(self):
        # Without an is_foreign predicate the transaction behaves exactly as before: overwrite and
        # drop the displaced original (no .moddy-orig). Guards against a regression for callers
        # (e.g. the BepInEx merge, modloaders) that don't opt in.
        write(os.path.join(self.root, "BepInEx/plugins/a.dll"), b"old")
        with mods._StagedInstall(self.root) as txn:
            txn.place(self.staged("a.dll", b"new"), "BepInEx/plugins/a.dll")
        self.assertEqual(tree_snapshot(self.root), {"BepInEx/plugins/a.dll": b"new"})

    def test_first_capture_wins(self):
        # A true original is already saved (an earlier mod captured it) and the slot holds mod A's
        # content. Mod B overwrites: the .moddy-orig must keep the TRUE stock, not become mod A.
        write(os.path.join(self.root, "f.bin"), b"modA")
        write(os.path.join(self.root, "f.bin" + mods._MODDY_ORIG_SUFFIX), b"truestock")
        with mods._StagedInstall(self.root, is_foreign=lambda p: True) as txn:
            txn.place(self.staged("f.bin", b"modB"), "f.bin")
        self.assertEqual(read(os.path.join(self.root, "f.bin")), b"modB")
        self.assertEqual(read(os.path.join(self.root, "f.bin" + mods._MODDY_ORIG_SUFFIX)), b"truestock")

    def test_rollback_restores_foreign_file(self):
        # A failed install must still restore the original in place (durable promotion happens only
        # on a clean commit; rollback uses the transient .moddy-bak as before).
        write(os.path.join(self.root, "x.tex"), b"stock")
        before = tree_snapshot(self.root)
        with self.assertRaises(RuntimeError):
            with mods._StagedInstall(self.root, is_foreign=lambda p: True) as txn:
                txn.place(self.staged("x.tex", b"mod"), "x.tex")
                raise RuntimeError("boom")
        self.assertEqual(tree_snapshot(self.root), before)


class SingleFileOriginalBackupTest(unittest.TestCase):
    """The single-file `file` installer into a game-root game (RE4/MHW/MHR shape, mods_dir='')."""

    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="")  # mods_path == game root
        self.mod = make_mod(mod_id="loose.dll", filename="dinput8.dll", install_type="file")
        self._real_download = mods.utils.download

    def tearDown(self):
        mods.utils.download = self._real_download

    def _dll(self, *suffix):
        return os.path.join(self.install_dir, "dinput8.dll" + "".join(suffix))

    def _install(self, payload=b"MODDLL"):
        mods.utils.download = raw_download(payload)
        return run(mods.install_mod(self.game, self.install_dir, self.mod, url="http://x"))

    def test_install_preserves_stock_then_uninstall_restores(self):
        write(self._dll(), b"STOCK")  # the game shipped a dinput8.dll
        self.assertTrue(self._install())
        self.assertEqual(read(self._dll()), b"MODDLL")
        self.assertEqual(read(self._dll(mods._MODDY_ORIG_SUFFIX)), b"STOCK")

        run(mods.uninstall_mod(self.game, self.install_dir, self.mod.id))
        self.assertEqual(read(self._dll()), b"STOCK", "uninstall must restore the stock file")
        self.assertFalse(os.path.exists(self._dll(mods._MODDY_ORIG_SUFFIX)))

    def test_no_preexisting_file_means_no_backup(self):
        # Nothing shipped at this path → nothing to preserve; uninstall just removes the mod.
        self.assertTrue(self._install())
        self.assertFalse(os.path.exists(self._dll(mods._MODDY_ORIG_SUFFIX)))
        run(mods.uninstall_mod(self.game, self.install_dir, self.mod.id))
        self.assertFalse(os.path.exists(self._dll()))

    def test_toggle_round_trips_through_vanilla(self):
        write(self._dll(), b"STOCK")
        self.assertTrue(self._install())

        # Disable → the stock file is back in the slot (vanilla), the mod is parked.
        run(mods.toggle_mod(self.game, self.install_dir, self.mod.id, enable=False))
        self.assertEqual(read(self._dll()), b"STOCK", "disable must put the stock file back")
        self.assertEqual(read(self._dll(".bak")), b"MODDLL")

        # Re-enable → the mod is live again and the stock file is re-stashed for next time.
        run(mods.toggle_mod(self.game, self.install_dir, self.mod.id, enable=True))
        self.assertEqual(read(self._dll()), b"MODDLL", "re-enable must restore the mod")
        self.assertEqual(read(self._dll(mods._MODDY_ORIG_SUFFIX)), b"STOCK")
        self.assertFalse(os.path.exists(self._dll(".bak")))

    def test_failed_install_leaves_stock_intact(self):
        write(self._dll(), b"STOCK")
        before = tree_snapshot(self.install_dir)

        async def boom(url, dest, appid):
            raise mods.utils.InstallCancelledError("cancelled")
        mods.utils.download = boom
        run(mods.install_mod(self.game, self.install_dir, self.mod, url="http://x"))
        self.assertEqual(tree_snapshot(self.install_dir), before, "a cancelled install must not touch the stock file")


class ModloaderOriginalBackupTest(unittest.TestCase):
    """A proxy loader whose version.dll overwrites a game's OWN stock version.dll: the original is
    preserved as .moddy-orig and restored on uninstall — the general path that replaced the bespoke
    version.dll.deckhand_bak handling."""

    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.ml = registry.ModloaderInfo(
            id="melon", name="melon",
            source=registry.ModSource(type="github", owner="o", repo="r", asset="a.zip"),
            files=["version.dll"], dirs=["MelonLoader"],
        )
        self.game = registry.GameProfile(id="g", name="G", appid=1, mods_dir="Mods", modloaders=[self.ml])
        self._real_download = mods.utils.download
        self._real_url = github.get_download_url_for_version
        github.get_download_url_for_version = lambda *a, **k: "http://x"

    def tearDown(self):
        mods.utils.download = self._real_download
        github.get_download_url_for_version = self._real_url

    def at(self, rel):
        return os.path.join(self.install_dir, rel)

    def _install(self):
        mods.utils.download = stub_download(writes={"version.dll": b"LOADER", "MelonLoader/net6/x.dll": b"L"})
        return run(modloaders._install_github_modloader(self.game, self.install_dir, self.ml, "1.0.0"))

    def test_stock_version_dll_preserved_and_restored(self):
        write(self.at("version.dll"), b"STOCK")  # the game shipped its own version.dll
        self.assertTrue(self._install())
        self.assertEqual(read(self.at("version.dll")), b"LOADER")
        self.assertEqual(read(self.at("version.dll" + mods._MODDY_ORIG_SUFFIX)), b"STOCK")

        run(modloaders.uninstall_modloader(self.game, self.install_dir, "melon"))
        self.assertEqual(read(self.at("version.dll")), b"STOCK", "uninstall must restore the game's version.dll")
        self.assertFalse(os.path.exists(self.at("version.dll" + mods._MODDY_ORIG_SUFFIX)))
        self.assertFalse(os.path.exists(self.at("MelonLoader")))

    def test_no_stock_file_means_no_backup(self):
        self.assertTrue(self._install())  # nothing shipped at version.dll
        self.assertFalse(os.path.exists(self.at("version.dll" + mods._MODDY_ORIG_SUFFIX)))
        run(modloaders.uninstall_modloader(self.game, self.install_dir, "melon"))
        self.assertFalse(os.path.exists(self.at("version.dll")))


if __name__ == "__main__":
    unittest.main()
