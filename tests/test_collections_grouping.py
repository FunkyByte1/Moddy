"""Tests for collection grouping on the Installed page: per-record provenance `sources` +
reference-counted "uninstall collection".

A mod is installed ONCE; installing it standalone AND via a collection just unions a membership
onto the same record. Uninstalling a collection drops that membership and removes a mod only when
its LAST source was the collection — a mod still wanted by `manual` or another collection stays.
"""
import asyncio
import types
import unittest

from _harness import reset_store  # noqa: F401 — installs the fake decky
import mods
import download_queue
import nexus_collections as nc


class RecordSourcesTest(unittest.TestCase):
    def setUp(self):
        reset_store()

    def _rec(self, mid="m1"):
        # A minimal install record (set_installed_record needs a ModInfo for source/meta; here we
        # only care about the sources map, so write the store directly the way installers leave it).
        mods.set_installed_record(1, mid, "1.0", mid)

    def test_add_source_unions_and_is_idempotent(self):
        self._rec("m1")
        mods.add_record_source(1, "m1", {"id": "collection:abc", "name": "Worldly", "image": "u.png"})
        mods.add_record_source(1, "m1", {"id": "manual", "name": "You"})
        mods.add_record_source(1, "m1", {"id": "collection:abc", "name": "Worldly"})  # repeat -> no dup, keeps image
        rec = mods.get_installed_record(1, "m1")
        self.assertEqual(rec["sources"], {
            "collection:abc": {"name": "Worldly", "image": "u.png"},
            "manual": {"name": "You", "image": ""},
        })

    def test_add_source_noop_when_no_record(self):
        mods.add_record_source(1, "ghost", {"id": "manual", "name": "You"})  # must not create a record
        self.assertIsNone(mods.get_installed_record(1, "ghost"))

    def test_sources_survive_reinstall(self):
        self._rec("m1")
        mods.add_record_source(1, "m1", {"id": "collection:abc", "name": "Worldly"})
        mods.set_installed_record(1, "m1", "2.0", "m1")  # re-install / version bump
        self.assertEqual(mods.get_installed_record(1, "m1")["sources"],
                         {"collection:abc": {"name": "Worldly", "image": ""}})

    def test_remove_source_returns_remaining_and_keeps_record(self):
        self._rec("m1")
        mods.add_record_source(1, "m1", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source(1, "m1", {"id": "manual", "name": "You"})
        remaining = mods.remove_record_source(1, "m1", "collection:abc")
        self.assertEqual(remaining, {"manual": {"name": "You", "image": ""}})
        self.assertEqual(mods.get_installed_record(1, "m1")["sources"], {"manual": {"name": "You", "image": ""}})

    def test_remove_last_source_clears_the_key(self):
        self._rec("m1")
        mods.add_record_source(1, "m1", {"id": "collection:abc", "name": "Worldly"})
        remaining = mods.remove_record_source(1, "m1", "collection:abc")
        self.assertEqual(remaining, {})
        self.assertNotIn("sources", mods.get_installed_record(1, "m1"))  # record stays, sources gone


class CollectionMembershipTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        # Three mods: one collection-only, one shared (collection + manual), one in a 2nd collection.
        for mid in ("only", "shared", "other"):
            mods.set_installed_record(1, mid, "1.0", mid)
            mods.set_installed_record(1, mid, "1.0", mid, mod=None)
        mods.add_record_source(1, "only", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source(1, "shared", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source(1, "shared", {"id": "manual", "name": "You"})
        mods.add_record_source(1, "other", {"id": "collection:xyz", "name": "Renn's"})

    def _meta_names(self):
        # preview_uninstall_collection reports meta.name (falls back to id); our minimal records have
        # no meta, so it should fall back to the id. Confirm partition by id.
        return nc.preview_uninstall_collection("abc")

    def test_collection_members_lists_only_tagged_mods(self):
        self.assertEqual(sorted(nc.collection_members("abc")), ["only", "shared"])
        self.assertEqual(nc.collection_members("xyz"), ["other"])

    def test_preview_partitions_remove_vs_keep(self):
        preview = nc.preview_uninstall_collection("abc")
        self.assertEqual(preview["remove"], ["only"])   # sole source is collection:abc
        self.assertEqual(preview["keep"], ["shared"])   # also manual -> kept

    def test_uninstall_collection_refcounts(self):
        calls = []

        async def fake_uninstall(game, install_dir, mid):
            calls.append(mid)
            mods.clear_installed_record(1, mid)
            return True

        orig_uninstall = mods.uninstall_mod
        orig_find = nc.steam.find_game_install_dir
        orig_game = nc.registry.get_game_by_appid
        mods.uninstall_mod = fake_uninstall
        nc.steam.find_game_install_dir = lambda appid: "/tmp/fake-install"
        nc.registry.get_game_by_appid = lambda appid: object()  # any truthy game
        try:
            result = asyncio.run(nc.uninstall_collection(1, "abc"))
        finally:
            mods.uninstall_mod = orig_uninstall
            nc.steam.find_game_install_dir = orig_find
            nc.registry.get_game_by_appid = orig_game

        self.assertEqual(calls, ["only"])               # only the sole-source mod was uninstalled
        self.assertEqual(result["removed"], ["only"])
        self.assertEqual(result["kept"], ["shared"])
        # The shared mod's record stays, just minus the collection tag.
        self.assertEqual(mods.get_installed_record(1, "shared")["sources"], {"manual": {"name": "You", "image": ""}})
        self.assertIsNone(mods.get_installed_record(1, "only"))


class CancelRollbackTest(unittest.TestCase):
    """Cancelling a collection mid-install must leave NOTHING the run added — but must keep a member
    that was already installed for another reason (manual / a prior collection)."""
    DOMAIN = "monsterhunterworld"

    def setUp(self):
        reset_store()
        self._save = {k: getattr(nc, k, None) for k in
                      ("fetch_manifest", "collection_mods", "installable_mods", "collection_card", "_install_one")}
        self._save_un = mods.uninstall_mod
        self._save_notes = (download_queue.note_total, download_queue.note_item, download_queue.note_warning)
        nc.steam.find_game_install_dir = lambda appid: "/tmp/fake-coll-install"
        async def _noop(*a, **k): return None
        download_queue.note_total = _noop
        download_queue.note_item = _noop
        download_queue.note_warning = _noop
        nc.fetch_manifest = lambda d, s: {"info": {"name": "Test Coll"}}
        nc.collection_card = lambda d, s: {"name": "Test Coll", "image": "tile.png"}
        nc.collection_mods = lambda mani, dom: self.mods_list
        nc.installable_mods = lambda game, ml, dom: ml

    def tearDown(self):
        for k, v in self._save.items():
            setattr(nc, k, v)
        mods.uninstall_mod = self._save_un
        download_queue.note_total, download_queue.note_item, download_queue.note_warning = self._save_notes

    def test_cancel_removes_run_mods_but_keeps_preexisting(self):
        self.mods_list = [{"mod_id": "5076", "name": "A", "author": "", "version": None, "optional": False, "choices": None},
                          {"mod_id": "100", "name": "B", "author": "", "version": None, "optional": False, "choices": None},
                          {"mod_id": "200", "name": "C", "author": "", "version": None, "optional": False, "choices": None}]
        # Mod 5076 was already installed manually BEFORE this collection run.
        pre = f"nexus.{self.DOMAIN}.5076"
        mods.set_installed_record(582010, pre, "1.0", pre)
        mods.add_record_source(582010, pre, {"id": "manual", "name": "You"})

        job = types.SimpleNamespace(cancel_requested=False)

        async def fake_install_one(game, install_dir, dom, m, source):
            mid = f"nexus.{dom}.{m['mod_id']}"
            mods.set_installed_record(game.appid, mid, "1.0", mid)
            mods.add_record_source(game.appid, mid, source)
            if m["mod_id"] == "100":      # after the 2nd mod installs, the user hits cancel
                job.cancel_requested = True
            return True
        nc._install_one = fake_install_one

        removed = []
        async def fake_uninstall(game, install_dir, mid):
            removed.append(mid); mods.clear_installed_record(game.appid, mid); return True
        mods.uninstall_mod = fake_uninstall

        result = asyncio.run(nc.run_collection(582010, self.DOMAIN, "testslug", job))
        self.assertIsNone(result)  # cancelled
        # 5076 was pre-installed (manual) → kept, collection tag dropped. 100 was added this run → removed.
        self.assertEqual(removed, [f"nexus.{self.DOMAIN}.100"])
        self.assertIsNotNone(mods.get_installed_record(582010, pre))
        self.assertEqual(mods.get_installed_record(582010, pre)["sources"], {"manual": {"name": "You", "image": ""}})
        self.assertIsNone(mods.get_installed_record(582010, f"nexus.{self.DOMAIN}.100"))
        self.assertIsNone(mods.get_installed_record(582010, f"nexus.{self.DOMAIN}.200"))  # never reached


class OptionalSelectionTest(unittest.TestCase):
    """A collection with optional mods parks once to ask which to add; the resume installs the
    required mods plus only the chosen optionals."""
    DOMAIN = "monsterhunterworld"

    def setUp(self):
        reset_store()
        self._save = {k: getattr(nc, k) for k in
                      ("fetch_manifest", "collection_mods", "installable_mods", "collection_card", "_install_one")}
        self._save_notes = (download_queue.note_total, download_queue.note_item, download_queue.note_warning)
        nc.steam.find_game_install_dir = lambda appid: "/tmp/fake-coll-install"
        async def _noop(*a, **k): return None
        download_queue.note_total = _noop
        download_queue.note_item = _noop
        download_queue.note_warning = _noop
        nc.fetch_manifest = lambda d, s: {"info": {"name": "Test Coll"}}
        nc.collection_card = lambda d, s: {"name": "Test Coll", "image": ""}
        nc.collection_mods = lambda mani, dom: self.mods_list
        nc.installable_mods = lambda game, ml, dom: [m for m in ml if not m["optional"]]
        self.mods_list = [
            {"mod_id": "1", "name": "Req", "optional": False, "file_id": "f1", "author": "", "version": None, "choices": None},
            {"mod_id": "2", "name": "OptA", "optional": True, "file_id": "f2", "author": "", "version": None, "choices": None},
            {"mod_id": "3", "name": "OptB", "optional": True, "file_id": "f3", "author": "", "version": None, "choices": None},
        ]

    def tearDown(self):
        for k, v in self._save.items():
            setattr(nc, k, v)
        download_queue.note_total, download_queue.note_item, download_queue.note_warning = self._save_notes

    def test_first_run_parks_listing_the_optionals(self):
        job = types.SimpleNamespace(variant=None, cancel_requested=False)
        res = asyncio.run(nc.run_collection(582010, self.DOMAIN, "slug", job))
        self.assertTrue(res["needs_options"])
        self.assertEqual([(o["id"], o["name"]) for o in res["options"]], [("2", "OptA"), ("3", "OptB")])
        self.assertEqual(job.name, "Collection: Test Coll")  # nicer than the slug

    def test_resume_installs_required_plus_chosen_optionals_only(self):
        installed = []
        async def fake_install_one(game, install_dir, dom, m, source):
            installed.append(m["mod_id"]); return True
        nc._install_one = fake_install_one
        job = types.SimpleNamespace(variant="2", cancel_requested=False)  # chose OptA, not OptB
        res = asyncio.run(nc.run_collection(582010, self.DOMAIN, "slug", job))
        self.assertIs(res, True)
        self.assertEqual(sorted(installed), ["1", "2"])  # required + OptA; OptB skipped

    def test_resume_with_no_choice_installs_only_required(self):
        installed = []
        async def fake_install_one(game, install_dir, dom, m, source):
            installed.append(m["mod_id"]); return True
        nc._install_one = fake_install_one
        job = types.SimpleNamespace(variant="", cancel_requested=False)  # skipped all optionals
        res = asyncio.run(nc.run_collection(582010, self.DOMAIN, "slug", job))
        self.assertIs(res, True)
        self.assertEqual(installed, ["1"])

    def test_park_omits_already_installed_optionals(self):
        orig_present = mods.installed_files_present
        mods.installed_files_present = lambda game, install_dir, mid: mid == f"nexus.{self.DOMAIN}.2"  # OptA on disk
        try:
            job = types.SimpleNamespace(variant=None, cancel_requested=False)
            res = asyncio.run(nc.run_collection(582010, self.DOMAIN, "slug", job))
        finally:
            mods.installed_files_present = orig_present
        self.assertEqual([o["id"] for o in res["options"]], ["3"])  # only OptB offered; OptA already installed

    def test_reinstall_skips_present_mods_and_claims_them(self):
        installed = []
        async def fake_install_one(game, install_dir, dom, m, source):
            installed.append(m["mod_id"]); return True
        nc._install_one = fake_install_one
        orig_present, orig_add = mods.installed_files_present, mods.add_record_source
        claimed = []
        mods.installed_files_present = lambda game, install_dir, mid: mid == f"nexus.{self.DOMAIN}.1"  # req already on disk
        mods.add_record_source = lambda appid, mid, src: claimed.append(mid)
        try:
            job = types.SimpleNamespace(variant="2", cancel_requested=False)  # chose OptA
            res = asyncio.run(nc.run_collection(582010, self.DOMAIN, "slug", job))
        finally:
            mods.installed_files_present, mods.add_record_source = orig_present, orig_add
        self.assertIs(res, True)
        self.assertEqual(installed, ["2"])                       # present required skipped; only missing OptA installed
        self.assertIn(f"nexus.{self.DOMAIN}.1", claimed)         # present member claimed for the collection


if __name__ == "__main__":
    unittest.main()
