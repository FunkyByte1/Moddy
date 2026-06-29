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
        mods.set_installed_record(mid, "1.0", mid)

    def test_add_source_unions_and_is_idempotent(self):
        self._rec("m1")
        mods.add_record_source("m1", {"id": "collection:abc", "name": "Worldly", "image": "u.png"})
        mods.add_record_source("m1", {"id": "manual", "name": "You"})
        mods.add_record_source("m1", {"id": "collection:abc", "name": "Worldly"})  # repeat -> no dup, keeps image
        rec = mods.get_installed_record("m1")
        self.assertEqual(rec["sources"], {
            "collection:abc": {"name": "Worldly", "image": "u.png"},
            "manual": {"name": "You", "image": ""},
        })

    def test_add_source_noop_when_no_record(self):
        mods.add_record_source("ghost", {"id": "manual", "name": "You"})  # must not create a record
        self.assertIsNone(mods.get_installed_record("ghost"))

    def test_sources_survive_reinstall(self):
        self._rec("m1")
        mods.add_record_source("m1", {"id": "collection:abc", "name": "Worldly"})
        mods.set_installed_record("m1", "2.0", "m1")  # re-install / version bump
        self.assertEqual(mods.get_installed_record("m1")["sources"],
                         {"collection:abc": {"name": "Worldly", "image": ""}})

    def test_remove_source_returns_remaining_and_keeps_record(self):
        self._rec("m1")
        mods.add_record_source("m1", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source("m1", {"id": "manual", "name": "You"})
        remaining = mods.remove_record_source("m1", "collection:abc")
        self.assertEqual(remaining, {"manual": {"name": "You", "image": ""}})
        self.assertEqual(mods.get_installed_record("m1")["sources"], {"manual": {"name": "You", "image": ""}})

    def test_remove_last_source_clears_the_key(self):
        self._rec("m1")
        mods.add_record_source("m1", {"id": "collection:abc", "name": "Worldly"})
        remaining = mods.remove_record_source("m1", "collection:abc")
        self.assertEqual(remaining, {})
        self.assertNotIn("sources", mods.get_installed_record("m1"))  # record stays, sources gone


class CollectionMembershipTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        # Three mods: one collection-only, one shared (collection + manual), one in a 2nd collection.
        for mid in ("only", "shared", "other"):
            mods.set_installed_record(mid, "1.0", mid)
            mods.set_installed_record(mid, "1.0", mid, mod=None)
        mods.add_record_source("only", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source("shared", {"id": "collection:abc", "name": "Worldly"})
        mods.add_record_source("shared", {"id": "manual", "name": "You"})
        mods.add_record_source("other", {"id": "collection:xyz", "name": "Renn's"})

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
            mods.clear_installed_record(mid)
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
        self.assertEqual(mods.get_installed_record("shared")["sources"], {"manual": {"name": "You", "image": ""}})
        self.assertIsNone(mods.get_installed_record("only"))


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
        mods.set_installed_record(pre, "1.0", pre)
        mods.add_record_source(pre, {"id": "manual", "name": "You"})

        job = types.SimpleNamespace(cancel_requested=False)

        async def fake_install_one(game, install_dir, dom, m, source):
            mid = f"nexus.{dom}.{m['mod_id']}"
            mods.set_installed_record(mid, "1.0", mid)
            mods.add_record_source(mid, source)
            if m["mod_id"] == "100":      # after the 2nd mod installs, the user hits cancel
                job.cancel_requested = True
            return True
        nc._install_one = fake_install_one

        removed = []
        async def fake_uninstall(game, install_dir, mid):
            removed.append(mid); mods.clear_installed_record(mid); return True
        mods.uninstall_mod = fake_uninstall

        result = asyncio.run(nc.run_collection(582010, self.DOMAIN, "testslug", job))
        self.assertIsNone(result)  # cancelled
        # 5076 was pre-installed (manual) → kept, collection tag dropped. 100 was added this run → removed.
        self.assertEqual(removed, [f"nexus.{self.DOMAIN}.100"])
        self.assertIsNotNone(mods.get_installed_record(pre))
        self.assertEqual(mods.get_installed_record(pre)["sources"], {"manual": {"name": "You", "image": ""}})
        self.assertIsNone(mods.get_installed_record(f"nexus.{self.DOMAIN}.100"))
        self.assertIsNone(mods.get_installed_record(f"nexus.{self.DOMAIN}.200"))  # never reached


if __name__ == "__main__":
    unittest.main()
