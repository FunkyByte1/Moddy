"""Tests for Thunderstore modpacks (thunderstore_modpacks).

A modpack is a Thunderstore package in the Modpacks category whose `dependencies` are the mods it
bundles; installing it means installing that dependency tree (NOT the empty modpack package itself),
stamped with the modpack's `collection:<full_name>` provenance so the Installed tab can group it and
ref-count an uninstall. These pin: the catalog list/has/detail shaping, and run_modpack's source
stamping, present-member claiming, "never install the modpack package", and cancel rollback.

I/O boundaries are stubbed (thunderstore catalog lookups, mods.install_mod / uninstall_mod, queue
progress, registry/steam resolution); the skip + provenance logic runs against the REAL store +
mods.installed_files_present, so this also integration-tests the ref-counting.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, reset_store
import thunderstore_modpacks as tm
import nexus_collections  # the (venue-neutral) uninstall_collection / preview, reused for modpacks
import thunderstore
import catalog
import download_queue
import steam


def run(coro):
    return asyncio.run(coro)


async def _anoop(*a, **k):
    return None


class _Job:
    def __init__(self):
        self.name = ""
        self.cancel_requested = False


class ThunderstoreModpacksTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(
            id="ror2", name="Risk of Rain 2", appid=632360, mods_dir="BepInEx/plugins",
            thunderstore_community="riskofrain2",  # no explicit catalog.type → inferred "thunderstore"
        )
        self.catalog = {}            # full_name.lower() -> CatalogItem
        self.installs = []           # (mod.id, source_id) passed to install_mod, in order
        self.install_results = {}    # id -> result override (default True)
        self.rolled_back = []        # ids uninstalled by rollback

        async def _install_mod(game, install_dir, mod, version=None, url=None, variant=None, source=None):
            self.installs.append((mod.id, (source or {}).get("id")))
            res = self.install_results.get(mod.id, True)
            if res is True:
                # Mimic the real install_mod: write the record + files on disk and stamp provenance, so
                # presence checks and ref-counting see reality across multiple installs.
                rel = f"BepInEx/plugins/{mod.filename}/{mod.filename}.dll"
                mods.set_installed_record(game.appid, mod.id, version or "1.0.0", mod.filename, paths=[rel])
                p = os.path.join(install_dir, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "w").close()
                mods.add_record_source(game.appid, mod.id, source or {"id": "manual", "name": "You"})
            return res

        async def _uninstall_mod(game, install_dir, mod_id):
            self.rolled_back.append(mod_id)
            return True

        self._saved = {}

        def patch(obj, name, value):
            self._saved[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)

        self._catalog_list = lambda community, force=False: list(self.catalog.values())
        patch(thunderstore, "find_package", lambda community, fn: self.catalog.get(fn.lower()))
        patch(thunderstore, "get_community_catalog", self._catalog_list)
        patch(thunderstore, "get_cached_community_catalog", self._catalog_list)
        patch(mods, "install_mod", _install_mod)
        patch(mods, "uninstall_mod", _uninstall_mod)
        patch(download_queue, "note_item", _anoop)
        patch(download_queue, "note_total", _anoop)
        patch(download_queue, "note_warning", _anoop)
        patch(registry, "get_game_by_appid", lambda appid: self.game)
        patch(steam, "find_game_install_dir", lambda appid: self.install_dir)

    def tearDown(self):
        for (obj, name), value in self._saved.items():
            setattr(obj, name, value)

    # ── helpers ────────────────────────────────────────────────────────────────
    def add_pkg(self, full_name, deps=(), categories=(), likes=0, icon="", version="1.0.0"):
        owner, _, name = full_name.partition("-")
        self.catalog[full_name.lower()] = catalog.make_item(
            name=name or full_name, full_name=full_name, owner=owner or "owner",
            categories=list(categories), rating_score=likes, version_number=version,
            description="d", icon=icon, dependencies=[f"{d}-1.0.0" for d in deps],
            download_url=f"https://dl.example/{full_name}.zip",
        )

    def add_modpack(self, full_name, deps=(), **kw):
        self.add_pkg(full_name, deps=deps, categories=["Modpacks"], **kw)

    def mark_installed_on_disk(self, full_name, rel="BepInEx/plugins/{name}/{name}.dll"):
        name = full_name.split("-", 1)[-1]
        rel = rel.format(name=name)
        mods.set_installed_record(self.game.appid, full_name, "1.0.0", name, paths=[rel])
        p = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()

    def sources_of(self, mod_id):
        rec = mods.find_installed_record(self.game.appid, mod_id)
        return set((rec or {}).get("sources", {}).keys())

    # ── catalog shaping ──────────────────────────────────────────────────────────
    def test_is_modpack(self):
        self.add_pkg("A-Plain")
        self.add_modpack("A-Pack")
        self.assertFalse(tm.is_modpack(self.catalog["a-plain"]))
        self.assertTrue(tm.is_modpack(self.catalog["a-pack"]))

    def test_list_modpacks_filters_and_shapes(self):
        self.add_pkg("Owner-PlainMod", likes=999)            # not a modpack — excluded
        self.add_modpack("Curator-BigPack", deps=["A-One", "B-Two"], likes=50, icon="i.png")
        items = tm.list_modpacks_for_game(632360)
        self.assertEqual([i["slug"] for i in items], ["Curator-BigPack"])
        it = items[0]
        self.assertEqual(it["author"], "Curator")
        self.assertEqual(it["mod_count"], 2)
        self.assertEqual(it["endorsements"], 50)
        self.assertEqual(it["tile_image"], "i.png")

    def test_list_modpacks_sorted_by_likes(self):
        # Modpacks need >=1 installable (non-loader) dependency to count (is_installable_modpack).
        self.add_modpack("X-Low", deps=["A-One"], likes=1)
        self.add_modpack("X-High", deps=["A-One"], likes=100)
        self.add_modpack("X-Mid", deps=["A-One"], likes=10)
        self.assertEqual([i["slug"] for i in tm.list_modpacks_for_game(632360)],
                         ["X-High", "X-Mid", "X-Low"])

    def test_list_modpacks_non_thunderstore_game_is_empty(self):
        self.game.thunderstore_community = ""  # not a Thunderstore game anymore
        self.assertEqual(tm.list_modpacks_for_game(632360), [])

    def test_game_has_modpacks(self):
        self.add_pkg("Owner-PlainMod")
        self.assertFalse(tm.game_has_modpacks(632360))
        self.add_modpack("Curator-Pack", deps=["A-One"])  # needs an installable (non-loader) dep to count
        self.assertTrue(tm.game_has_modpacks(632360))

    def test_loader_only_or_empty_modpack_is_not_installable(self):
        # A 'Modpacks'-tagged pack whose only dep is the (denylisted) loader ships its own content
        # and is a mis-tagged mod, not a real modpack (Megabonk's Rizzotto-Megamod). It must NOT be
        # listed or gate the Collections tab. An empty-dep 'modpack' is excluded for the same reason.
        self.add_modpack("Rizzotto-Megamod", deps=["BepInEx-BepInExPack"])  # loader only → denylisted
        self.add_modpack("Empty-Pack")                                       # no deps at all
        self.assertFalse(tm.game_has_modpacks(632360))
        self.assertEqual(tm.list_modpacks_for_game(632360), [])

    def test_modpack_detail_lists_members(self):
        self.add_pkg("A-One", icon="one.png")
        self.add_modpack("Curator-Pack", deps=["A-One", "B-Two"])  # B-Two absent from catalog
        d = tm.get_modpack_detail(632360, "Curator-Pack")
        self.assertEqual(d["slug"], "Curator-Pack")
        self.assertEqual(d["mod_count"], 2)
        members = {m["mod_id"]: m for m in d["mods"]}
        self.assertEqual(members["A-One"]["thumbnail"], "one.png")
        self.assertEqual(members["A-One"]["name"], "One")
        self.assertFalse(members["A-One"]["optional"])
        self.assertIn("B-Two", members)  # listed even though it isn't in the catalog (falls back to full_name)

    # ── install ──────────────────────────────────────────────────────────────────
    def test_run_modpack_installs_members_with_modpack_source(self):
        self.add_pkg("A-One")
        self.add_pkg("B-Two", deps=["A-One"])  # transitive dep
        self.add_modpack("Curator-Pack", deps=["B-Two"])
        res = run(tm.run_modpack(632360, "Curator-Pack", _Job()))
        self.assertTrue(res)
        installed_ids = [i[0] for i in self.installs]
        self.assertEqual(installed_ids, ["A-One", "B-Two"], "deps install depth-first")
        self.assertNotIn("Curator-Pack", installed_ids, "the modpack package itself is never installed")
        for _id, sid in self.installs:
            self.assertEqual(sid, "collection:Curator-Pack", "every member is stamped with the modpack source")

    def test_run_modpack_claims_already_present_member(self):
        self.add_pkg("A-One")
        self.add_modpack("Curator-Pack", deps=["A-One"])
        self.mark_installed_on_disk("A-One")  # already on disk (e.g. installed manually)
        mods.add_record_source(self.game.appid, "A-One", {"id": "manual", "name": "You"})
        res = run(tm.run_modpack(632360, "Curator-Pack", _Job()))
        self.assertTrue(res)
        self.assertEqual(self.installs, [], "a present member isn't re-downloaded")
        self.assertEqual(self.sources_of("A-One"), {"manual", "collection:Curator-Pack"},
                         "a present member is claimed for the modpack, keeping its prior source")

    def test_run_modpack_cancel_rolls_back_fresh_installs(self):
        self.add_pkg("A-One")
        self.add_pkg("B-Two")
        self.add_modpack("Curator-Pack", deps=["A-One", "B-Two"])
        self.install_results["B-Two"] = None  # cancel mid-install on the second member
        res = run(tm.run_modpack(632360, "Curator-Pack", _Job()))
        self.assertIsNone(res)
        self.assertEqual(self.rolled_back, ["A-One"], "the freshly-installed member is rolled back on cancel")

    def test_run_modpack_sets_job_name(self):
        self.add_pkg("A-One")
        self.add_modpack("Curator-Pack", deps=["A-One"])
        job = _Job()
        run(tm.run_modpack(632360, "Curator-Pack", job))
        self.assertEqual(job.name, "Modpack: Pack")

    def test_two_overlapping_modpacks_refcount_on_uninstall(self):
        # The real-world case: two installed modpacks that share dependencies (e.g. SurvivorDLC and
        # Eclipsed_Shores both pull BepInExPack/R2API). A shared mod must be claimed by BOTH, shown
        # once, and survive uninstalling one of them; an exclusive mod is removed with its only owner.
        self.add_pkg("Co-Shared")
        self.add_pkg("Co-ExclusiveA")
        self.add_pkg("Co-ExclusiveB")
        self.add_modpack("Co-Pack1", deps=["Co-Shared", "Co-ExclusiveA"])
        self.add_modpack("Co-Pack2", deps=["Co-Shared", "Co-ExclusiveB"])
        self.assertTrue(run(tm.run_modpack(632360, "Co-Pack1", _Job())))
        # Second pack: Co-Shared is already on disk → claimed (not re-installed), Co-ExclusiveB fresh.
        self.installs.clear()
        self.assertTrue(run(tm.run_modpack(632360, "Co-Pack2", _Job())))
        self.assertNotIn("Co-Shared", [i[0] for i in self.installs], "a present shared mod isn't re-downloaded")
        self.assertEqual(self.sources_of("Co-Shared"), {"collection:Co-Pack1", "collection:Co-Pack2"})
        self.assertEqual(self.sources_of("Co-ExclusiveA"), {"collection:Co-Pack1"})

        # Uninstall Pack1: shared mod kept (Pack2 still needs it), exclusive-to-Pack1 removed.
        res = run(nexus_collections.uninstall_collection(632360, "Co-Pack1"))
        self.assertEqual(res["removed"], ["Co-ExclusiveA"])
        self.assertEqual(res["kept"], ["Co-Shared"])
        self.assertEqual(self.rolled_back, ["Co-ExclusiveA"], "only the orphaned exclusive mod is deleted from disk")
        self.assertEqual(self.sources_of("Co-Shared"), {"collection:Co-Pack2"}, "shared mod now owned by Pack2 alone")

    def test_run_modpack_unknown_pack_fails(self):
        self.assertFalse(run(tm.run_modpack(632360, "Nope-Missing", _Job())))


if __name__ == "__main__":
    unittest.main()
