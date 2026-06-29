"""Phase 1 of the multi-file collection fix: a collection that pins SEVERAL files of one Nexus mod
must install them under ONE record (combined paths) instead of each overwriting the last.

_install_group groups by modId and, when the install type has a multi-file installer
(zip_smapi/zip_palworld), routes the file list through it (reusing the Browse file-picker machinery)
and stamps the collection provenance. Other types fall back to sequential installs (Phase 2) but log
the limitation. These stub the network + installers and assert the routing/record behaviour.
"""
import asyncio
import os
import tempfile
import types
import unittest

from _harness import reset_store, make_game, make_mod, build_zip  # noqa: F401 — installs the fake decky
import registry
import nexus
import mods
import utils
import nexus_collections as nc


def run(coro):
    return asyncio.run(coro)


class InstallGroupTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self._orig = {
            "get_download_url": nexus.get_download_url, "get_mod": nexus.get_mod,
            "install_smapi_files": mods.install_smapi_files,
            "install_palworld_files": mods.install_palworld_files,
            "install_folder_files": mods.install_folder_files,
            "add_record_source": mods.add_record_source, "_install_one": nc._install_one,
        }
        self.smapi, self.palworld, self.folder, self.sources, self.one = [], [], [], [], []

        async def fake_smapi(game, install_dir, mod, version, urls):
            self.smapi.append((mod.id, version, list(urls))); return True

        async def fake_palworld(game, install_dir, mod, version, urls):
            self.palworld.append((mod.id, version, list(urls))); return True

        async def fake_folder(game, install_dir, mod, version, urls):
            self.folder.append((mod.id, version, list(urls))); return True

        async def fake_one(game, install_dir, domain, m, source=None):
            self.one.append(m["file_id"]); return True

        nexus.get_mod = lambda domain, mod_id: {}  # offline; _mod_info falls back to manifest name/author
        nexus.get_download_url = lambda domain, mod_id, file_id: f"https://cdn/{mod_id}/{file_id}"
        mods.install_smapi_files = fake_smapi
        mods.install_palworld_files = fake_palworld
        mods.install_folder_files = fake_folder
        mods.add_record_source = lambda mid, src: self.sources.append((mid, src))
        nc._install_one = fake_one

    def tearDown(self):
        nexus.get_download_url = self._orig["get_download_url"]
        nexus.get_mod = self._orig["get_mod"]
        mods.install_smapi_files = self._orig["install_smapi_files"]
        mods.install_palworld_files = self._orig["install_palworld_files"]
        mods.install_folder_files = self._orig["install_folder_files"]
        mods.add_record_source = self._orig["add_record_source"]
        nc._install_one = self._orig["_install_one"]

    def _entries(self, mod_id, *file_ids):
        return [{"mod_id": mod_id, "file_id": f, "name": f"Mod {mod_id}", "author": "A", "version": "1.0"}
                for f in file_ids]

    SRC = {"id": "collection:test", "name": "Test Collection", "image": ""}

    def test_smapi_multifile_installs_one_record_with_all_urls(self):
        game = registry.get_game_by_appid(413150)  # Stardew Valley — zip_smapi
        res = run(nc._install_group(game, "/x", "stardewvalley", self._entries("3753", "100", "200"), self.SRC))
        self.assertIs(res, True)
        self.assertEqual(len(self.smapi), 1, "one combined install_smapi_files call")
        mid, version, urls = self.smapi[0]
        self.assertEqual(mid, "nexus.stardewvalley.3753")
        self.assertEqual(urls, ["https://cdn/3753/100", "https://cdn/3753/200"])
        self.assertEqual(self.sources, [("nexus.stardewvalley.3753", self.SRC)], "provenance stamped")
        self.assertEqual(self.palworld, [])
        self.assertEqual(self.one, [], "did not fall back to per-file single installs")

    def test_palworld_multifile_routes_to_palworld_installer(self):
        game = registry.get_game_by_appid(1623730)  # Palworld — zip_palworld
        res = run(nc._install_group(game, "/x", "palworld", self._entries("42", "1", "2"), self.SRC))
        self.assertIs(res, True)
        self.assertEqual(len(self.palworld), 1)
        self.assertEqual(self.palworld[0][2], ["https://cdn/42/1", "https://cdn/42/2"])
        self.assertEqual(self.smapi, [])

    def test_single_entry_delegates_to_install_one(self):
        game = registry.get_game_by_appid(413150)
        res = run(nc._install_group(game, "/x", "stardewvalley", self._entries("3753", "100"), self.SRC))
        self.assertIs(res, True)
        self.assertEqual(self.one, ["100"], "single file goes through the unchanged _install_one path")
        self.assertEqual(self.smapi, [], "no multi-file installer for a lone file")

    def test_folder_multifile_routes_to_folder_installer(self):
        game = registry.get_game_by_appid(275850)  # No Man's Sky — zip_folder (Phase 2)
        res = run(nc._install_group(game, "/x", "nomanssky", self._entries("1649", "5", "6"), self.SRC))
        self.assertIs(res, True)
        self.assertEqual(len(self.folder), 1)
        self.assertEqual(self.folder[0][2], ["https://cdn/1649/5", "https://cdn/1649/6"])
        self.assertEqual(self.sources, [("nexus.nomanssky.1649", self.SRC)])
        self.assertEqual(self.smapi, [])
        self.assertEqual(self.palworld, [])
        self.assertEqual(self.one, [], "did not fall back to per-file single installs")

    def test_unsupported_type_falls_back_sequential_and_warns(self):
        game = registry.get_game_by_appid(582010)  # MHW — zip_nativepc, still no multi-file installer
        res = run(nc._install_group(game, "/x", "monsterhunterworld", self._entries("5076", "5", "6"), self.SRC))
        self.assertIs(res, True)
        self.assertEqual(self.one, ["5", "6"], "both files attempted sequentially (Phase 2 limitation)")
        self.assertEqual(self.smapi, [])
        self.assertEqual(self.palworld, [])
        self.assertEqual(self.folder, [])

    def test_premium_during_url_resolution_propagates(self):
        def boom(domain, mod_id, file_id):
            raise nexus.PremiumRequired()
        nexus.get_download_url = boom
        game = registry.get_game_by_appid(413150)
        res = run(nc._install_group(game, "/x", "stardewvalley", self._entries("3753", "100", "200"), self.SRC))
        self.assertEqual(res, nc.install_cascade.PREMIUM_REQUIRED)
        self.assertEqual(self.smapi, [])


class RunCollectionGroupingTest(unittest.TestCase):
    """End-to-end-ish: a manifest with two files of one modId + one single-file mod must produce a
    SINGLE combined install for the duplicated modId, not two overwriting installs."""

    def setUp(self):
        reset_store()
        self._orig = {
            "fetch_manifest": nc.fetch_manifest, "collection_card": nc.collection_card,
            "find_game_install_dir": nc.steam.find_game_install_dir,
            "get_download_url": nexus.get_download_url, "get_mod": nexus.get_mod,
            "install_smapi_files": mods.install_smapi_files, "install_mod": mods.install_mod,
            "note_total": nc.download_queue.note_total, "note_item": nc.download_queue.note_item,
            "note_warning": nc.download_queue.note_warning,
        }
        self.smapi, self.single = [], []

        async def fake_smapi(game, install_dir, mod, version, urls):
            self.smapi.append((mod.id, list(urls))); return True

        async def fake_install_mod(game, install_dir, mod, version=None, url=None, variant=None, source=None):
            self.single.append(mod.id); return True

        async def _noop(*a, **k):
            return None

        nc.fetch_manifest = lambda domain, slug: {
            "info": {"name": "Test"},
            "mods": [
                {"name": "SVE", "optional": False, "domainName": "stardewvalley", "author": "A", "version": "1",
                 "source": {"type": "nexus", "modId": 3753, "fileId": 100}},
                {"name": "SVE Alt Farm", "optional": False, "domainName": "stardewvalley", "author": "A", "version": "1",
                 "source": {"type": "nexus", "modId": 3753, "fileId": 200}},  # SAME modId, 2nd file
                {"name": "Automate", "optional": False, "domainName": "stardewvalley", "author": "A", "version": "2",
                 "source": {"type": "nexus", "modId": 1063, "fileId": 300}},
            ],
        }
        nc.collection_card = lambda domain, slug: {"image": ""}
        nc.steam.find_game_install_dir = lambda appid: "/tmp/moddy-nonexistent-game"
        nexus.get_mod = lambda domain, mod_id: {}
        nexus.get_download_url = lambda domain, mod_id, file_id: f"https://cdn/{mod_id}/{file_id}"
        mods.install_smapi_files = fake_smapi
        mods.install_mod = fake_install_mod
        nc.download_queue.note_total = _noop
        nc.download_queue.note_item = _noop
        nc.download_queue.note_warning = _noop

    def tearDown(self):
        nc.fetch_manifest = self._orig["fetch_manifest"]
        nc.collection_card = self._orig["collection_card"]
        nc.steam.find_game_install_dir = self._orig["find_game_install_dir"]
        nexus.get_download_url = self._orig["get_download_url"]
        nexus.get_mod = self._orig["get_mod"]
        mods.install_smapi_files = self._orig["install_smapi_files"]
        mods.install_mod = self._orig["install_mod"]
        nc.download_queue.note_total = self._orig["note_total"]
        nc.download_queue.note_item = self._orig["note_item"]
        nc.download_queue.note_warning = self._orig["note_warning"]

    def test_duplicate_modid_collapses_to_one_combined_install(self):
        job = types.SimpleNamespace(name="", variant=None, cancel_requested=False)
        res = run(nc.run_collection(413150, "stardewvalley", "test", job))
        self.assertTrue(res)
        # The two files of mod 3753 became ONE combined install_smapi_files call with both urls...
        self.assertEqual(len(self.smapi), 1)
        self.assertEqual(self.smapi[0], ("nexus.stardewvalley.3753",
                                         ["https://cdn/3753/100", "https://cdn/3753/200"]))
        # ...and the lone mod 1063 went through the normal single-file path.
        self.assertEqual(self.single, ["nexus.stardewvalley.1063"])


class InstallFolderFilesTest(unittest.TestCase):
    """The real install_folder_files (NMS zip_folder): several files of one mod overlaid into a single
    mod folder, one record, all files present — the actual Phase 2 behaviour, no stubbing the installer."""

    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-nms-")
        self.game = make_game(mods_dir="GAMEDATA/MODS")
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def _multi_download(self, mapping):
        async def _dl(url, dest, appid, expected_hash=None):
            build_zip(dest, mapping[url])
        return _dl

    def test_two_files_merge_into_one_folder(self):
        # Two pinned files of mod 1649: one .pak each (the q8gqsb "In The Wild" / "Near Shelters" shape).
        utils.download = self._multi_download({
            "u0": {"InTheWild.pak": b"wild"},
            "u1": {"NearShelters.pak": b"shelters"},
        })
        mod = make_mod(mod_id="nexus.nomanssky.1649", filename="nexus-1649", install_type="zip_folder")
        res = run(mods.install_folder_files(self.game, self.install_dir, mod, "1.0", ["u0", "u1"]))
        self.assertIs(res, True)
        folder = os.path.join(self.install_dir, "GAMEDATA", "MODS", "nexus-1649")
        self.assertTrue(os.path.isfile(os.path.join(folder, "InTheWild.pak")), "first file present")
        self.assertTrue(os.path.isfile(os.path.join(folder, "NearShelters.pak")), "second file present (not overwritten)")
        rec = mods.get_installed_record(mod.id)
        self.assertEqual(rec["paths"], ["GAMEDATA/MODS/nexus-1649"], "one tracked folder for the merged mod")


if __name__ == "__main__":
    unittest.main()
