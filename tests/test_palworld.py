"""Tests for the Palworld zip_palworld install type — the three Nexus archive shapes (modelled on
real mods the maintainer pasted), placement, the natives-style .disabled toggle, and uninstall.

Shapes:
  A) full Pal/ tree   (DekModConfigMenu: a UE4SS Lua mod + a LogicMods .pak) -> merged into Pal/
  B) bare pak         (Better Night Light: BNLnew_P.pak) -> Pal/Content/Paks/~mods/
  C) loose UE4SS mod  (NoFoodDecay: enabled.txt + Scripts/main.lua) -> Pal/Binaries/Win64/ue4ss/Mods/<Name>/
"""
import asyncio
import os
import tempfile
import unittest
import zipfile

from _harness import mods, utils, registry, make_game, make_mod, reset_store, stub_download
import modloaders
import github


def run(coro):
    return asyncio.run(coro)


class PalworldInstallTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(appid=1623730, mods_dir="Pal/Content/Paks/~mods")
        self._saved_download = utils.download

    def tearDown(self):
        utils.download = self._saved_download

    def _mod(self, mod_id="nexus.palworld.1", filename="nexus-1"):
        return make_mod(mod_id=mod_id, filename=filename, install_type="zip_palworld")

    def install(self, writes, mod=None):
        utils.download = stub_download(writes=writes)
        return run(mods.install_mod(self.game, self.install_dir, mod or self._mod(),
                                    version="1.0", url="http://x"))

    def g(self, *parts):
        return os.path.join(self.install_dir, *parts)

    # ── Shape A: full Pal/ tree (paks self-locate; lua mod self-locates) ──────────
    def test_shape_a_full_pal_tree(self):
        writes = {
            "Pal/Binaries/Win64/Mods/DekModConfigMenu/enabled.txt": b"",
            "Pal/Binaries/Win64/Mods/DekModConfigMenu/Scripts/main.lua": b"-- lua",
            "Pal/Content/Paks/LogicMods/DekModConfigMenu_P.pak": b"PAK",
        }
        self.assertTrue(self.install(writes))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/DekModConfigMenu/enabled.txt")))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/DekModConfigMenu/Scripts/main.lua")))
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/LogicMods/DekModConfigMenu_P.pak")))

    def test_shape_a_without_pal_wrapper(self):
        # Same mod but the archive ships Binaries/ + Content/ at the root (no Pal/ wrapper) — must
        # still land under the game's Pal/.
        writes = {
            "Binaries/Win64/Mods/Dek/enabled.txt": b"",
            "Content/Paks/LogicMods/Dek_P.pak": b"PAK",
        }
        self.assertTrue(self.install(writes))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/Dek/enabled.txt")))
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/LogicMods/Dek_P.pak")))

    # ── Shape B: bare pak ─────────────────────────────────────────────────────────
    def test_shape_b_bare_pak(self):
        self.assertTrue(self.install({"BNLnew_P.pak": b"PAK"}))
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/~mods/BNLnew_P.pak")))
        rec = mods.get_installed_record("nexus.palworld.1")
        self.assertEqual(rec["paths"], [os.path.join("Pal", "Content", "Paks", "~mods", "BNLnew_P.pak")])

    def test_shape_b_pak_set_with_sidecars(self):
        # IO-store mods ship .pak + .ucas + .utoc; all three go to ~mods/.
        self.assertTrue(self.install({"Mod_P.pak": b"P", "Mod_P.ucas": b"C", "Mod_P.utoc": b"T"}))
        for ext in ("pak", "ucas", "utoc"):
            self.assertTrue(os.path.isfile(self.g(f"Pal/Content/Paks/~mods/Mod_P.{ext}")))

    # ── Shape C: loose UE4SS Lua mod ──────────────────────────────────────────────
    def test_shape_c_loose_lua_uses_catalog_filename(self):
        mod = self._mod(filename="NoFoodDecay")
        self.assertTrue(self.install({"enabled.txt": b"", "Scripts/main.lua": b"-- lua"}, mod))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/NoFoodDecay/enabled.txt")))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/NoFoodDecay/Scripts/main.lua")))

    def test_shape_c_wrapped_folder_names_the_mod(self):
        self.assertTrue(self.install({"CoolMod/enabled.txt": b"", "CoolMod/Scripts/main.lua": b"x"}))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/CoolMod/enabled.txt")))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/CoolMod/Scripts/main.lua")))
        self.assertFalse(os.path.isdir(self.g("Pal/Binaries/Win64/ue4ss/Mods/CoolMod/CoolMod")))

    def test_empty_or_junk_archive_refused(self):
        self.assertFalse(self.install({"readme.txt": b"hi", "preview.png": b"img"}))
        self.assertIsNone(mods.get_installed_record("nexus.palworld.1"))

    # ── Toggle + uninstall (reuse the natives .disabled machinery) ────────────────
    def test_pak_toggle_disables_by_rename(self):
        self.install({"BNLnew_P.pak": b"PAK"})
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "nexus.palworld.1", False)))
        self.assertFalse(os.path.isfile(self.g("Pal/Content/Paks/~mods/BNLnew_P.pak")))
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/~mods/BNLnew_P.pak.disabled")))
        self.assertTrue(run(mods.toggle_mod(self.game, self.install_dir, "nexus.palworld.1", True)))
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/~mods/BNLnew_P.pak")))

    def test_lua_toggle_removes_enabled_marker(self):
        mod = self._mod(filename="NoFoodDecay")
        self.install({"enabled.txt": b"", "Scripts/main.lua": b"x"}, mod)
        run(mods.toggle_mod(self.game, self.install_dir, "nexus.palworld.1", False))
        # UE4SS auto-loads a folder only if enabled.txt is present; disabling renames it away.
        self.assertFalse(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/NoFoodDecay/enabled.txt")))
        listed = {m["id"]: m for m in mods.get_installed_mods(self.game, self.install_dir)}
        self.assertIn("nexus.palworld.1", listed)
        self.assertFalse(listed["nexus.palworld.1"]["enabled"])

    def test_uninstall_removes_all_tracked_files(self):
        self.install({
            "Pal/Binaries/Win64/Mods/Dek/enabled.txt": b"",
            "Pal/Content/Paks/LogicMods/Dek_P.pak": b"PAK",
        })
        self.assertTrue(run(mods.uninstall_mod(self.game, self.install_dir, "nexus.palworld.1")))
        self.assertFalse(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/Dek/enabled.txt")))
        self.assertFalse(os.path.isfile(self.g("Pal/Content/Paks/LogicMods/Dek_P.pak")))
        self.assertIsNone(mods.get_installed_record("nexus.palworld.1"))

    def test_uninstall_while_disabled_removes_disabled_files(self):
        self.install({"BNLnew_P.pak": b"PAK"})
        run(mods.toggle_mod(self.game, self.install_dir, "nexus.palworld.1", False))
        self.assertTrue(run(mods.uninstall_mod(self.game, self.install_dir, "nexus.palworld.1")))
        self.assertFalse(os.path.isfile(self.g("Pal/Content/Paks/~mods/BNLnew_P.pak.disabled")))
        self.assertIsNone(mods.get_installed_record("nexus.palworld.1"))

    def test_toggle_rolls_back_on_midloop_failure(self):
        # A Shape-A mod spans two subsystems (LogicMods pak + UE4SS Lua) — a half-done disable would
        # leave it inconsistent, so a mid-loop rename error must roll the whole toggle back.
        self.install({"Pal/Content/Paks/LogicMods/Dek_P.pak": b"P",
                      "Pal/Binaries/Win64/Mods/Dek/enabled.txt": b""})
        real_rename, calls = os.rename, {"n": 0}

        def flaky(src, dst, *a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated mid-toggle failure")
            return real_rename(src, dst, *a, **k)

        os.rename = flaky
        try:
            ok = run(mods.toggle_mod(self.game, self.install_dir, "nexus.palworld.1", False))
        finally:
            os.rename = real_rename
        self.assertFalse(ok)
        # Both halves back in their original (enabled) form — nothing left half-disabled.
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/LogicMods/Dek_P.pak")))
        self.assertTrue(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/Dek/enabled.txt")))
        self.assertFalse(os.path.isfile(self.g("Pal/Content/Paks/LogicMods/Dek_P.pak.disabled")))
        self.assertFalse(os.path.isfile(self.g("Pal/Binaries/Win64/ue4ss/Mods/Dek/enabled.txt.disabled")))


class PalworldPlacementUnitTest(unittest.TestCase):
    """Direct checks on the pure classifier for edge cases."""
    def _tree(self, files):
        root = tempfile.mkdtemp(prefix="pw-extract-")
        for rel, data in files.items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
        return root

    def _dests(self, files, filename="nexus-1"):
        root = self._tree(files)
        mod = make_mod(mod_id="nexus.palworld.1", filename=filename, install_type="zip_palworld")
        placements = mods._palworld_placements(root, mod)
        return sorted(d.replace("\\", "/") for _s, d in (placements or []))

    def test_structured_beats_loose_pak(self):
        # A pak inside a Content/ structure stays at its path, not flattened to ~mods/.
        self.assertEqual(
            self._dests({"Content/Paks/LogicMods/X_P.pak": b"P"}),
            ["Pal/Content/Paks/LogicMods/X_P.pak"],
        )

    def test_bare_pak_goes_to_mods(self):
        self.assertEqual(self._dests({"X_P.pak": b"P"}), ["Pal/Content/Paks/~mods/X_P.pak"])

    def test_loose_lua_root_uses_filename(self):
        self.assertEqual(
            self._dests({"enabled.txt": b"", "Scripts/main.lua": b"x"}, filename="MyMod"),
            ["Pal/Binaries/Win64/ue4ss/Mods/MyMod/Scripts/main.lua",
             "Pal/Binaries/Win64/ue4ss/Mods/MyMod/enabled.txt"],
        )

    def test_unknown_archive_returns_none(self):
        root = self._tree({"readme.md": b"hi"})
        self.assertIsNone(mods._palworld_placements(root, make_mod(install_type="zip_palworld")))

    def test_mixed_loose_pak_and_lua_places_both(self):
        # A LogicMods pak + its UE4SS Lua config, shipped loose (no Pal/ wrapper): BOTH halves install.
        self.assertEqual(
            self._dests({"BigMod_P.pak": b"P", "enabled.txt": b"", "Scripts/main.lua": b"x"}, filename="Big"),
            ["Pal/Binaries/Win64/ue4ss/Mods/Big/Scripts/main.lua",
             "Pal/Binaries/Win64/ue4ss/Mods/Big/enabled.txt",
             "Pal/Content/Paks/~mods/BigMod_P.pak"],
        )

    def test_loose_pak_beside_structured_tree_kept(self):
        # A bare pak shipped next to a structured Pal/ tree goes to ~mods/, not dropped.
        self.assertEqual(
            self._dests({"Content/Paks/LogicMods/A_P.pak": b"A", "Loose_P.pak": b"B"}),
            ["Pal/Content/Paks/LogicMods/A_P.pak", "Pal/Content/Paks/~mods/Loose_P.pak"],
        )

    def test_lowercase_segments_canonicalized(self):
        # An odd-cased structured archive must land in the engine's exact-cased dirs.
        self.assertEqual(
            self._dests({"content/paks/logicmods/X_P.pak": b"P",
                         "binaries/win64/mods/Foo/enabled.txt": b""}),
            ["Pal/Binaries/Win64/ue4ss/Mods/Foo/enabled.txt", "Pal/Content/Paks/LogicMods/X_P.pak"],
        )

    def test_uppercase_pak_extension_lowercased(self):
        self.assertEqual(self._dests({"BNL_P.PAK": b"P"}), ["Pal/Content/Paks/~mods/BNL_P.pak"])

    def test_bare_logicmods_pak_routed_to_logicmods(self):
        # A blueprint mod's pak under LogicMods/ must go to Content/Paks/LogicMods/ (BPModLoaderMod
        # scans there), not the generic ~mods/ — real mods Pal Analyzer / Pal Info ship this way.
        self.assertEqual(self._dests({"LogicMods/PalAnalyzer.pak": b"P"}),
                         ["Pal/Content/Paks/LogicMods/PalAnalyzer.pak"])
        self.assertEqual(self._dests({"LogicMods/PalInfo.pak": b"P", "LogicMods/PalInfo.ucas": b"C",
                                      "LogicMods/PalInfo.utoc": b"T"}),
                         ["Pal/Content/Paks/LogicMods/PalInfo.pak",
                          "Pal/Content/Paks/LogicMods/PalInfo.ucas",
                          "Pal/Content/Paks/LogicMods/PalInfo.utoc"])

    def test_regular_pak_still_goes_to_mods(self):
        self.assertEqual(self._dests({"Cool_P.pak": b"P"}), ["Pal/Content/Paks/~mods/Cool_P.pak"])

    def test_loose_logicmods_keeps_modconfig_companion(self):
        # Mod 146 (Basic Minimap): a blueprint mod ships pak + *.modconfig.json + .png loose in
        # LogicMods/ — all land in Content/Paks/LogicMods/ so DekMCM reads the config. A dropped
        # modconfig.json = the mod is absent from the config menu (the bug this fixes).
        self.assertEqual(
            self._dests({"LogicMods/DekBasicMinimap_P.pak": b"P",
                         "LogicMods/DekBasicMinimap_P.modconfig.json": b"{}",
                         "LogicMods/DekBasicMinimap_P.png": b"img"}),
            ["Pal/Content/Paks/LogicMods/DekBasicMinimap_P.modconfig.json",
             "Pal/Content/Paks/LogicMods/DekBasicMinimap_P.pak",
             "Pal/Content/Paks/LogicMods/DekBasicMinimap_P.png"],
        )

    def test_shape_a_lua_path_remapped_to_ue4ss(self):
        # A legacy archive shipping its Lua under Binaries/Win64/Mods/ (e.g. DekMCM) must land in
        # ue4ss/Mods/ where RE-UE4SS 3.x loads it.
        self.assertEqual(
            self._dests({"Pal/Binaries/Win64/Mods/DekModConfigMenu/Scripts/main.lua": b"x"}),
            ["Pal/Binaries/Win64/ue4ss/Mods/DekModConfigMenu/Scripts/main.lua"],
        )


class Ue4ssLoaderTest(unittest.TestCase):
    """UE4SS (Palworld): a github loader that merges its whole archive under base_dir
    Pal/Binaries/Win64/ (dwmapi.dll proxy + ue4ss/), with the WINEDLLOVERRIDES launch option."""
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.get_game_by_appid(1623730)
        self._saved = {"dl": utils.download, "gh": github.get_latest_download_url}
        github.get_latest_download_url = lambda o, r, a: ("3.0.1", "http://x")

    def tearDown(self):
        utils.download = self._saved["dl"]
        github.get_latest_download_url = self._saved["gh"]

    def serve(self, files):
        async def _dl(url, dest, appid):
            with zipfile.ZipFile(dest, "w") as z:
                for n, d in files.items():
                    z.writestr(n, d)
        utils.download = _dl

    def w(self, *p):
        return os.path.join(self.install_dir, *p)

    def install(self, files=None):
        self.serve(files or {"dwmapi.dll": b"DLL", "ue4ss/UE4SS.dll": b"X", "ue4ss/Mods/mods.json": b"[]"})
        return run(modloaders.install_modloader(self.game, self.install_dir, "ue4ss-palworld"))

    def test_installs_under_win64(self):
        self.assertTrue(self.install())
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/dwmapi.dll")))
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/ue4ss/UE4SS.dll")))
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/ue4ss/Mods/mods.json")))
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "ue4ss-palworld"))
        self.assertTrue(modloaders.is_modloader_enabled(self.game, self.install_dir, "ue4ss-palworld"))
        self.assertEqual(modloaders.get_modloader_version("ue4ss-palworld"), "3.0.1")

    def test_missing_proxy_dll_fails(self):
        self.assertFalse(self.install({"ue4ss/UE4SS.dll": b"X"}))  # no dwmapi.dll in the archive

    def test_missing_ue4ss_dir_fails(self):
        # A restructured archive (proxy but no ue4ss/ runtime) must fail, not commit a broken loader.
        self.assertFalse(self.install({"dwmapi.dll": b"DLL"}))
        self.assertFalse(modloaders.is_modloader_installed(self.game, self.install_dir, "ue4ss-palworld"))

    def test_update_while_disabled_stays_disabled_no_orphan(self):
        self.install({"dwmapi.dll": b"OLD", "ue4ss/UE4SS.dll": b"X"})
        user = self.w("Pal/Binaries/Win64/ue4ss/Mods/MyMod/enabled.txt")
        os.makedirs(os.path.dirname(user))
        open(user, "w").close()
        run(modloaders.disable_modloader(self.game, self.install_dir, "ue4ss-palworld"))
        self.assertFalse(modloaders.is_modloader_enabled(self.game, self.install_dir, "ue4ss-palworld"))
        self.install({"dwmapi.dll": b"NEW", "ue4ss/UE4SS.dll": b"Y"})  # update while disabled
        self.assertTrue(modloaders.is_modloader_installed(self.game, self.install_dir, "ue4ss-palworld"))
        self.assertFalse(modloaders.is_modloader_enabled(self.game, self.install_dir, "ue4ss-palworld"),
                         "updating a disabled loader keeps it disabled")
        self.assertFalse(os.path.isdir(self.w("Pal/Binaries/Win64/ue4ss")), "no live ue4ss/ while disabled")
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/ue4ss.disabled/Mods/MyMod/enabled.txt")),
                        "user Lua mod preserved across an update-while-disabled")

    def test_enable_disable_renames_proxy(self):
        self.install()
        self.assertTrue(run(modloaders.disable_modloader(self.game, self.install_dir, "ue4ss-palworld")))
        self.assertFalse(os.path.isfile(self.w("Pal/Binaries/Win64/dwmapi.dll")))
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/dwmapi.dll.disabled")))
        self.assertFalse(modloaders.is_modloader_enabled(self.game, self.install_dir, "ue4ss-palworld"))
        self.assertTrue(run(modloaders.enable_modloader(self.game, self.install_dir, "ue4ss-palworld")))
        self.assertTrue(os.path.isfile(self.w("Pal/Binaries/Win64/dwmapi.dll")))

    def test_update_replaces_loader_but_preserves_user_mods(self):
        # User Lua mods live under ue4ss/Mods/ (where RE-UE4SS scans) — INSIDE the loader's base dir.
        # A loader update must replace the loader's own files (incl. built-in mods) WITHOUT wiping the
        # user's mods, so it retires only the prior install's tracked files, not the whole tree.
        self.install({"dwmapi.dll": b"OLD", "ue4ss/old.txt": b"x",
                      "ue4ss/Mods/BPModLoaderMod/main.lua": b"old-builtin"})
        user = self.w("Pal/Binaries/Win64/ue4ss/Mods/MyMod/enabled.txt")
        os.makedirs(os.path.dirname(user))
        open(user, "w").close()
        self.install({"dwmapi.dll": b"NEW", "ue4ss/new.txt": b"y",
                      "ue4ss/Mods/BPModLoaderMod/main.lua": b"new-builtin"})
        self.assertNotIn("dwmapi.dll.moddy-orig", os.listdir(self.w("Pal/Binaries/Win64")))
        self.assertFalse(os.path.exists(self.w("Pal/Binaries/Win64/ue4ss/old.txt")), "stale package file replaced")
        with open(self.w("Pal/Binaries/Win64/ue4ss/Mods/BPModLoaderMod/main.lua")) as f:
            self.assertEqual(f.read(), "new-builtin", "built-in mod updated")
        self.assertTrue(os.path.isfile(user), "user Lua mod under ue4ss/Mods/ survives a loader update")

    def test_uninstall_removes_loader_and_its_mods(self):
        # Lua mods live under the loader's ue4ss/ dir, so uninstalling UE4SS removes them too
        # (get_modloader_uninstall_impact warns which). Pak mods in Content/Paks/ are untouched.
        self.install()
        user = self.w("Pal/Binaries/Win64/ue4ss/Mods/MyMod/enabled.txt")
        os.makedirs(os.path.dirname(user))
        open(user, "w").close()
        self.assertTrue(run(modloaders.uninstall_modloader(self.game, self.install_dir, "ue4ss-palworld")))
        self.assertFalse(os.path.isfile(self.w("Pal/Binaries/Win64/dwmapi.dll")))
        self.assertFalse(os.path.isdir(self.w("Pal/Binaries/Win64/ue4ss")))
        self.assertFalse(os.path.isfile(user), "uninstalling UE4SS removes its ue4ss/Mods/ folder")


class PalworldMultifileTest(unittest.TestCase):
    """install_palworld_files — the file-picker path: download + combine several chosen Nexus files
    (a version/Steam variant + optional add-ons) under one record."""
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(appid=1623730, mods_dir="Pal/Content/Paks/~mods")
        self._saved = utils.download

    def tearDown(self):
        utils.download = self._saved

    def _serve(self, per_url):
        async def _dl(url, dest, appid):
            with zipfile.ZipFile(dest, "w") as z:
                for n, da in per_url[url].items():
                    z.writestr(n, da)
        utils.download = _dl

    def g(self, *p):
        return os.path.join(self.install_dir, *p)

    def test_combines_chosen_files_into_one_record(self):
        self._serve({"u1": {"PalInfo_P.pak": b"P"},
                     "u2": {"MyMod/enabled.txt": b"", "MyMod/Scripts/main.lua": b"x"}})
        mod = make_mod(mod_id="nexus.palworld.1", filename="nexus-1", install_type="zip_palworld")
        self.assertTrue(run(mods.install_palworld_files(self.game, self.install_dir, mod, "1.0", ["u1", "u2"])))
        paths = {p.replace(os.sep, "/") for p in mods.get_installed_record("nexus.palworld.1")["paths"]}
        self.assertIn("Pal/Content/Paks/~mods/PalInfo_P.pak", paths)
        self.assertIn("Pal/Binaries/Win64/ue4ss/Mods/MyMod/enabled.txt", paths)
        self.assertTrue(os.path.isfile(self.g("Pal/Content/Paks/~mods/PalInfo_P.pak")))

    def test_last_file_wins_on_collision(self):
        self._serve({"u1": {"X_P.pak": b"OLD"}, "u2": {"X_P.pak": b"NEW"}})
        mod = make_mod(mod_id="nexus.palworld.2", filename="nexus-2", install_type="zip_palworld")
        run(mods.install_palworld_files(self.game, self.install_dir, mod, "1.0", ["u1", "u2"]))
        with open(self.g("Pal/Content/Paks/~mods/X_P.pak"), "rb") as f:
            self.assertEqual(f.read(), b"NEW")


class PalworldFilterTest(unittest.TestCase):
    """_palworld_pick_files — drops non-Steam-platform files so the Deck (Steam build) doesn't try a
    GamePass/Xbox/Epic io-store pak, and auto-collapses a Steam/GamePass pair to the Steam file."""
    def setUp(self):
        import main
        self.plugin = main.Plugin()

    def _files(self, *names):
        return [{"name": n, "category": "MAIN", "file_id": str(i), "is_primary": False}
                for i, n in enumerate(names)]

    def test_drops_nonsteam_platform_files(self):
        kept = self.plugin._palworld_pick_files(
            self._files("Mod (STEAM)", "Mod (Game Pass)", "Mod (XBOX APP)", "Mod (Epic)"))
        self.assertEqual([k["name"] for k in kept], ["Mod (STEAM)"])

    def test_keeps_version_variants(self):
        self.assertEqual(len(self.plugin._palworld_pick_files(self._files("Mod x2", "Mod x5", "Mod x10"))), 3)

    def test_keeps_steam_plus_neutral_addon(self):
        # Steam build + a Mod Config File -> both kept (the picker offers base + add-on).
        kept = self.plugin._palworld_pick_files(self._files("Pal Info (STEAM)", "Pal Info (GAMEPASS)", "Pal Info Config"))
        self.assertEqual([k["name"] for k in kept], ["Pal Info (STEAM)", "Pal Info Config"])

    def test_fallback_keeps_all_when_only_nonsteam(self):
        only = self._files("Mod (Game Pass)")
        self.assertEqual(len(self.plugin._palworld_pick_files(only)), 1)

    def test_drops_iostore_version_when_name_is_identical(self):
        # DekMCM: same display name, version 1.9 (Steam) vs 1.9io (GamePass) — drop the io one.
        files = [{"name": "DekMCM", "version": "1.9", "category": "MAIN", "file_id": "1", "is_primary": True},
                 {"name": "DekMCM", "version": "1.9io", "category": "MAIN", "file_id": "2", "is_primary": False}]
        self.assertEqual([k["version"] for k in self.plugin._palworld_pick_files(files)], ["1.9"])

    def test_label_disambiguates_by_version(self):
        import main
        rec = {"name": "DekMCM", "version": "1.9", "category": "MAIN", "is_primary": True}
        self.assertEqual(main.Plugin._nexus_file_label(rec), "DekMCM (v1.9) — recommended")
        opt = {"name": "Config", "version": "1.0", "category": "OPTIONAL", "is_primary": False}
        self.assertEqual(main.Plugin._nexus_file_label(opt), "Config (v1.0) (optional)")
        # version already in the name isn't duplicated
        dup = {"name": "Mod v2.5", "version": "2.5", "category": "MAIN", "is_primary": False}
        self.assertEqual(main.Plugin._nexus_file_label(dup), "Mod v2.5")


if __name__ == "__main__":
    unittest.main()
