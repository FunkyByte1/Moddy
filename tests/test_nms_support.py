"""No Man's Sky support: the zip_folder installer + .disabled folder toggle, the data-driven
"setup" loader (parks GAMEDATA/PCBANKS/DISABLEMODS.TXT aside to enable mods and restores it to
disable), the native↔workshop decoupling, and the vanilla-mode round-trip.

NMS mods are folder-per-mod under GAMEDATA/MODS/<mod>/ with NO loader to download — the game loads
any mod folder present only when DISABLEMODS.TXT is absent. So a "setup loader" parks that blank
file aside on install/enable and restores it on disable/uninstall. Archives are plain zips so
extract_archive takes its zipfile path (no system 7z needed).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import (
    mods, utils, registry, make_mod, make_game, reset_store, stub_download,
    tree_snapshot, failing_copy2, bak_crumbs,
)
import modloaders
import main
import steam


def run(coro):
    return asyncio.run(coro)


def write(path, data=b""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


DISABLEMODS = "GAMEDATA/PCBANKS/DISABLEMODS.TXT"
SENTINEL = DISABLEMODS + mods._MODDY_ORIG_SUFFIX


def nms_setup_loader():
    return registry.ModloaderInfo(
        id="nms-setup", name="No Man's Sky Mod Support",
        source=registry.ModSource(type="setup"),
        indicator=SENTINEL,
        setup={"remove_files": [DISABLEMODS]},
    )


# ── zip_folder installer + .disabled folder toggle ─────────────────────────────
class ZipFolderInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-nms-")
        self.game = make_game(mods_dir="GAMEDATA/MODS")
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def _install(self, writes, version="1.0.0", mod_id="m", filename="CoolMod"):
        utils.download = stub_download(writes=writes)
        mod = make_mod(mod_id=mod_id, filename=filename, install_type="zip_folder")
        res = run(mods.install_mod(self.game, self.install_dir, mod, version, "http://x"))
        return res, mod

    def test_loose_files_go_into_own_folder(self):
        res, mod = self._install({"GLITCH.MBIN": b"M", "readme.txt": b"hi"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/GLITCH.MBIN"))
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/readme.txt"))  # whole folder kept (isolated)
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["paths"], ["GAMEDATA/MODS/CoolMod"])

    def test_macos_junk_sibling_does_not_defeat_wrapper_strip(self):
        # macOS-zipped Nexus archive: a real wrapper folder rides next to __MACOSX/ and .DS_Store.
        # The junk must not defeat the single-wrapper strip nor land in the mod folder.
        res, mod = self._install({
            "RealMod/big.pak": b"P",
            "__MACOSX/RealMod/._big.pak": b"junk",
            ".DS_Store": b"junk",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/big.pak"))    # stripped to right depth
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/RealMod"))   # not double-nested
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/__MACOSX"))  # junk not copied in
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/.DS_Store"))
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["paths"], ["GAMEDATA/MODS/CoolMod"])

    def test_macos_junk_skipped_in_multi_entry_archive(self):
        # No single wrapper (two real top entries) but junk rides along — junk is skipped, mods kept.
        res, mod = self._install({
            "a.mbin": b"A", "b.mbin": b"B", ".DS_Store": b"junk", "__MACOSX/._a.mbin": b"junk",
        })
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/a.mbin"))
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/b.mbin"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/.DS_Store"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/__MACOSX"))

    def test_single_wrapper_folder_stripped(self):
        # Nexus archives often wrap everything in one folder; strip it so we don't nest twice.
        res, mod = self._install({"BetterPlanets 2.1/big.pak": b"P", "BetterPlanets 2.1/x.mbin": b"M"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/big.pak"))
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/x.mbin"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/BetterPlanets 2.1"))

    def test_pak_mod_also_supported(self):
        res, mod = self._install({"mymod.pak": b"PAKDATA"})
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/mymod.pak"))

    def test_empty_archive_refuses(self):
        res, mod = self._install({})
        self.assertIs(res, False)
        self.assertIsNone(mods.get_installed_record(self.game.appid, mod.id))

    def test_toggle_moves_folder_out_of_mods(self):
        # NMS scans MODS/ recursively (device-confirmed), so disabling must MOVE the folder out of
        # MODS/ entirely — an in-place .disabled rename would still be loaded.
        _res, mod = self._install({"x.mbin": b"M"})
        self.assertIs(run(mods.toggle_mod(self.game, self.install_dir, mod.id, False)), True)
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod.disabled"))   # NOT an in-place rename
        self.assertTrue(self.exists(".moddy-disabled-mods/CoolMod/x.mbin"))
        row = next(m for m in mods.get_installed_mods(self.game, self.install_dir) if m["id"] == mod.id)
        self.assertFalse(row["enabled"])

        self.assertIs(run(mods.toggle_mod(self.game, self.install_dir, mod.id, True)), True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/x.mbin"))
        self.assertFalse(self.exists(".moddy-disabled-mods/CoolMod"))
        self.assertFalse(self.exists(".moddy-disabled-mods"))             # staging pruned when empty
        row = next(m for m in mods.get_installed_mods(self.game, self.install_dir) if m["id"] == mod.id)
        self.assertTrue(row["enabled"])

    def test_uninstall_removes_parked_disabled_mod(self):
        _res, mod = self._install({"x.mbin": b"M"})
        run(mods.toggle_mod(self.game, self.install_dir, mod.id, False))  # parked out of MODS/
        self.assertTrue(self.exists(".moddy-disabled-mods/CoolMod"))
        self.assertIs(run(mods.uninstall_mod(self.game, self.install_dir, mod.id)), True)
        self.assertFalse(self.exists(".moddy-disabled-mods/CoolMod"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod"))
        self.assertIsNone(mods.get_installed_record(self.game.appid, mod.id))

    def test_uninstall_leaves_co_resident_mod(self):
        self._install({"a.mbin": b"A"}, mod_id="a", filename="ModA")
        self._install({"b.mbin": b"B"}, mod_id="b", filename="ModB")
        run(mods.uninstall_mod(self.game, self.install_dir, "a"))
        self.assertFalse(self.exists("GAMEDATA/MODS/ModA"))
        self.assertTrue(self.exists("GAMEDATA/MODS/ModB/b.mbin"))

    def test_reinstall_replaces_stale_files(self):
        self._install({"old.mbin": b"OLD"}, version="1.0.0")
        res, mod = self._install({"new.mbin": b"NEW"}, version="2.0.0")
        self.assertIs(res, True)
        self.assertTrue(self.exists("GAMEDATA/MODS/CoolMod/new.mbin"))
        self.assertFalse(self.exists("GAMEDATA/MODS/CoolMod/old.mbin"))
        self.assertEqual(mods.get_installed_record(self.game.appid, mod.id)["version"], "2.0.0")

    def test_failed_commit_rolls_back(self):
        keep = os.path.join(self.install_dir, "GAMEDATA", "MODS", "Keep")
        write(os.path.join(keep, "k.mbin"), b"K")
        before = tree_snapshot(self.install_dir)
        utils.download = stub_download(writes={"a.mbin": b"A", "b.mbin": b"B", "c.mbin": b"C"})
        mod = make_mod(mod_id="new", filename="New", install_type="zip_folder")
        with failing_copy2(fail_on=2):
            res = run(mods.install_mod(self.game, self.install_dir, mod, "1.0.0", "http://x"))
        self.assertIs(res, False)
        self.assertEqual(tree_snapshot(self.install_dir), before)   # byte-identical
        self.assertIsNone(mods.get_installed_record(self.game.appid, "new"))
        self.assertEqual(bak_crumbs(self.install_dir), [])


# ── the data-driven "setup" loader (DISABLEMODS.TXT) ──────────────────────────
class NmsSetupLoaderTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        modloaders._modloader_versions = {}   # NOT cleared by reset_store
        self.install_dir = tempfile.mkdtemp(prefix="moddy-nms-")
        self.ml = nms_setup_loader()
        self.game = registry.GameProfile(id="nms", name="NMS", appid=275850,
                                         mods_dir="GAMEDATA/MODS", modloaders=[self.ml])

    def at(self, rel):
        return os.path.join(self.install_dir, rel)

    def installed(self):
        return modloaders.is_modloader_installed(self.game, self.install_dir, "nms-setup")

    def enabled(self):
        return modloaders.is_modloader_enabled(self.game, self.install_dir, "nms-setup")

    def test_install_parks_disablemods_then_uninstall_restores(self):
        write(self.at(DISABLEMODS), b"")  # the game ships a BLANK DISABLEMODS.TXT
        self.assertIs(run(modloaders.install_modloader(self.game, self.install_dir, "nms-setup")), True)
        self.assertFalse(os.path.exists(self.at(DISABLEMODS)))   # parked aside → mods load
        self.assertTrue(os.path.exists(self.at(SENTINEL)))
        self.assertTrue(self.installed() and self.enabled()
                        and modloaders.is_modloader_ready(self.game, self.install_dir, "nms-setup"))

        run(modloaders.uninstall_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertTrue(os.path.exists(self.at(DISABLEMODS)))    # blank file back → mods off
        self.assertFalse(os.path.exists(self.at(SENTINEL)))
        self.assertFalse(self.enabled())

    def test_install_when_no_disablemods_creates_marker(self):
        # File-absent branch: still create the sentinel so the loader reports 'set up'.
        self.assertIs(run(modloaders.install_modloader(self.game, self.install_dir, "nms-setup")), True)
        self.assertTrue(os.path.exists(self.at(SENTINEL)))
        self.assertTrue(self.enabled())
        # Disable (e.g. entering vanilla) must leave a DISABLEMODS.TXT so mods stay off.
        run(modloaders.disable_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertTrue(os.path.exists(self.at(DISABLEMODS)))
        self.assertFalse(os.path.exists(self.at(SENTINEL)))
        self.assertFalse(self.enabled())
        # Re-enable parks it again.
        run(modloaders.enable_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertFalse(os.path.exists(self.at(DISABLEMODS)))
        self.assertTrue(os.path.exists(self.at(SENTINEL)))
        self.assertTrue(self.enabled())

    def test_disable_keeps_installed_true(self):
        # Regression: disabling the setup loader removes the live sentinel, but it must still report
        # INSTALLED (tracked via the version store) — else the Mod Loader tab drops the toggle and
        # offers to re-install, and Reset Game skips uninstalling it.
        write(self.at(DISABLEMODS), b"")
        run(modloaders.install_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertTrue(self.installed() and self.enabled())
        run(modloaders.disable_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertFalse(self.enabled())
        self.assertTrue(self.installed())   # still installed while disabled
        run(modloaders.uninstall_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertFalse(self.installed())  # gone for real after uninstall

    def test_first_capture_wins_on_reenable(self):
        # A genuine original is already captured; re-enabling (leaving vanilla) while a regenerated
        # DISABLEMODS.TXT exists must NOT overwrite the captured original.
        write(self.at(SENTINEL), b"TRUESTOCK")
        write(self.at(DISABLEMODS), b"REGENERATED")
        run(modloaders.enable_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertEqual(read(self.at(SENTINEL)), b"TRUESTOCK")   # not clobbered
        self.assertFalse(os.path.exists(self.at(DISABLEMODS)))    # live placeholder cleared

    def test_nonblank_original_restored_exactly(self):
        write(self.at(DISABLEMODS), b"DO-NOT-LOSE")
        run(modloaders.install_modloader(self.game, self.install_dir, "nms-setup"))
        run(modloaders.uninstall_modloader(self.game, self.install_dir, "nms-setup"))
        self.assertEqual(read(self.at(DISABLEMODS)), b"DO-NOT-LOSE")  # byte-exact restore


# ── native↔workshop decoupling ─────────────────────────────────────────────────
class WorkshopDecouplingTest(unittest.TestCase):
    def setUp(self):
        reset_store()

    def test_setup_loader_game_is_not_workshop(self):
        g = registry.GameProfile(id="nms", name="NMS", appid=275850, mods_dir="GAMEDATA/MODS",
                                 modloaders=[nms_setup_loader()])
        self.assertFalse(g.uses_steam_workshop())

    def test_steamworkshop_source_is_workshop(self):
        ml = registry.ModloaderInfo(id="sw", name="SW", source=registry.ModSource(type="steamworkshop"), native=True)
        g = registry.GameProfile(id="w", name="W", appid=9, mods_dir="X", modloaders=[ml])
        self.assertTrue(g.uses_steam_workshop())

    def test_setup_game_lists_zip_folder_mod_via_fs_scan(self):
        # The setup-loader game must NOT take the Workshop early-return in get_installed_mods, so a
        # zip_folder record backed by an on-disk folder is listed.
        install_dir = tempfile.mkdtemp(prefix="moddy-nms-")
        g = registry.GameProfile(id="nms", name="NMS", appid=275850, mods_dir="GAMEDATA/MODS",
                                 modloaders=[nms_setup_loader()])
        mod = make_mod(mod_id="m", filename="CoolMod", install_type="zip_folder")
        mods.set_installed_record(g.appid, "m", "1.0", "CoolMod", paths=["GAMEDATA/MODS/CoolMod"], mod=mod)
        write(os.path.join(install_dir, "GAMEDATA", "MODS", "CoolMod", "x.mbin"), b"M")
        listed = mods.get_installed_mods(g, install_dir)
        self.assertEqual([m["id"] for m in listed], ["m"])
        self.assertTrue(listed[0]["enabled"])


# ── vanilla-mode round-trip ────────────────────────────────────────────────────
class NmsVanillaTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        modloaders._modloader_versions = {}
        self.install_dir = tempfile.mkdtemp(prefix="moddy-nms-")
        self.ml = nms_setup_loader()
        self.game = registry.GameProfile(id="nms", name="NMS", appid=275850,
                                         mods_dir="GAMEDATA/MODS", modloaders=[self.ml])
        self.plugin = main.Plugin()
        self._saved = {}

        def patch(obj, name, value):
            self._saved[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)
        patch(registry, "get_game_by_appid", lambda appid: self.game)
        patch(steam, "find_game_install_dir", lambda appid: self.install_dir)

        # Loader set up (mods enabled): sentinel present, DISABLEMODS.TXT parked away.
        write(os.path.join(self.install_dir, SENTINEL), b"")
        # One enabled zip_folder mod.
        mod = make_mod(mod_id="modA", filename="CoolMod", install_type="zip_folder")
        mods.set_installed_record(self.game.appid, "modA", "1.0", "CoolMod", paths=["GAMEDATA/MODS/CoolMod"], mod=mod)
        write(os.path.join(self.install_dir, "GAMEDATA", "MODS", "CoolMod", "x.mbin"), b"M")

    def tearDown(self):
        for (obj, name), value in self._saved.items():
            setattr(obj, name, value)

    def exists(self, *rel):
        return os.path.exists(os.path.join(self.install_dir, *rel))

    def test_enter_then_leave_restores(self):
        res = run(self.plugin.set_game_vanilla_mode(275850, True))
        self.assertTrue(res["ok"])
        self.assertEqual(res["modloader_id"], "nms-setup")
        self.assertEqual(res["mods_disabled"], 1)
        # Vanilla: DISABLEMODS.TXT restored (mods off), sentinel gone, mod folder parked.
        self.assertTrue(mods.is_game_vanilla(275850))
        self.assertTrue(self.exists(DISABLEMODS))
        self.assertFalse(self.exists(SENTINEL))
        self.assertTrue(self.exists(".moddy-disabled-mods", "CoolMod"))   # mod moved out of MODS/
        self.assertFalse(self.exists("GAMEDATA", "MODS", "CoolMod"))

        res = run(self.plugin.set_game_vanilla_mode(275850, False))
        self.assertTrue(res["ok"])
        self.assertEqual(res["mods_enabled"], 1)
        # Back to modded: DISABLEMODS.TXT parked again, sentinel back, mod folder live.
        self.assertFalse(mods.is_game_vanilla(275850))
        self.assertFalse(self.exists(DISABLEMODS))
        self.assertTrue(self.exists(SENTINEL))
        self.assertTrue(self.exists("GAMEDATA", "MODS", "CoolMod"))
        self.assertFalse(self.exists(".moddy-disabled-mods", "CoolMod"))


if __name__ == "__main__":
    unittest.main()
