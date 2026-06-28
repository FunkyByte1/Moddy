"""Characterization tests for the Thunderstore install cascade in plugin_thunderstore_install.

These pin the *observable behavior* of the recursive dependency install — depth-first ordering,
skip-already-installed, skip-denylisted, with_deps gating, missing-dependency handling, the
"N of M" plan pre-pass, and rollback-on-partial-failure — BEFORE the planned refactor that moves
this logic behind a ModProvider protocol. They're the net the refactor must keep green.

The cascade is driven through plugin_thunderstore_install — and main.Plugin for the public-entry
rollback test — with the I/O boundaries stubbed: thunderstore.find_package (the catalog),
mods.install_mod / mods.uninstall_mod (placement + rollback), download_queue progress, and
registry/steam resolution. The skip logic runs against the REAL store +
mods.installed_files_present, so this also integration-tests that helper.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, reset_store
import main
import plugin_thunderstore_install
import thunderstore
import catalog
import download_queue
import steam


def run(coro):
    return asyncio.run(coro)


async def _anoop(*a, **k):
    return None


class ThunderstoreCascadeTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(
            id="g", name="G", appid=1, mods_dir="BepInEx/plugins", thunderstore_community="testcom",
        )
        self.plugin = main.Plugin()
        self.denylist = set()        # lowercase install ids the cascade skips; a test overrides it

        self.catalog = {}            # full_name.lower() -> CatalogItem
        self.installs = []           # mod ids passed to install_mod, in order
        self.install_results = {}    # id -> result override (default True)
        self.rolled_back = []        # ids uninstalled by rollback

        async def _install_mod(game, install_dir, mod, version=None, url=None, variant=None):
            self.installs.append(mod.id)
            return self.install_results.get(mod.id, True)

        async def _uninstall_mod(game, install_dir, mod_id):
            self.rolled_back.append(mod_id)
            return True

        self._saved = {}

        def patch(mod_obj, name, value):
            self._saved[(mod_obj, name)] = getattr(mod_obj, name)
            setattr(mod_obj, name, value)

        patch(thunderstore, "find_package", lambda community, fn: self.catalog.get(fn.lower()))
        patch(mods, "install_mod", _install_mod)
        patch(mods, "uninstall_mod", _uninstall_mod)
        patch(download_queue, "note_item", _anoop)
        patch(download_queue, "note_total", _anoop)
        patch(download_queue, "note_warning", _anoop)
        patch(registry, "get_game_by_appid", lambda appid: self.game)
        patch(steam, "find_game_install_dir", lambda appid: self.install_dir)

    def tearDown(self):
        for (mod_obj, name), value in self._saved.items():
            setattr(mod_obj, name, value)

    # ── helpers ──────────────────────────────────────────────────────────────
    def add_pkg(self, full_name, deps=(), version="1.0.0"):
        owner, _, name = full_name.partition("-")
        self.catalog[full_name.lower()] = catalog.make_item(
            name=name or full_name, full_name=full_name, owner=owner or "owner",
            package_url=f"https://thunderstore.io/p/{full_name}", version_number=version,
            description="d", icon="", dependencies=[f"{d}-1.0.0" for d in deps],
            download_url=f"https://dl.example/{full_name}.zip",
        )

    def mark_installed_on_disk(self, full_name, rel="BepInEx/plugins/{name}/{name}.dll"):
        name = full_name.split("-", 1)[-1]
        rel = rel.format(name=name)
        mods.set_installed_record(full_name, "1.0.0", name, paths=[rel])
        p = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()

    def cascade(self, full_name, **kw):
        kw.setdefault("seen", set())
        kw.setdefault("installed_this_run", [])
        return run(plugin_thunderstore_install._install_thunderstore_recursive(
            self.game, self.install_dir, full_name, None, denylist=self.denylist, **kw))

    # ── tests ────────────────────────────────────────────────────────────────
    def test_installs_dependencies_depth_first(self):
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB"])
        res = self.cascade("OwnerA-ModA")
        self.assertTrue(res)
        self.assertEqual(self.installs, ["OwnerB-ModB", "OwnerA-ModA"], "deps install before the mod that needs them")

    def test_skips_already_installed_dependency(self):
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB"])
        self.mark_installed_on_disk("OwnerB-ModB")  # present record + files on disk
        self.cascade("OwnerA-ModA")
        self.assertEqual(self.installs, ["OwnerA-ModA"], "an already-installed dep (files present) is skipped")

    def test_orphaned_record_is_reinstalled(self):
        # Record exists but its files are gone (e.g. modloader uninstall wiped them) -> NOT a skip.
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB"])
        mods.set_installed_record("OwnerB-ModB", "1.0.0", "ModB", paths=["BepInEx/plugins/ModB/ModB.dll"])  # no file written
        self.cascade("OwnerA-ModA")
        self.assertEqual(self.installs, ["OwnerB-ModB", "OwnerA-ModA"], "an orphaned record must not skip the reinstall")

    def test_skips_denylisted_dependency(self):
        self.denylist = {"ownerc-modc"}  # the cascade skips this dependency
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerC-ModC")
        self.add_pkg("OwnerA-ModA", deps=["OwnerC-ModC", "OwnerB-ModB"])
        self.cascade("OwnerA-ModA")
        self.assertNotIn("OwnerC-ModC", self.installs, "a denylisted dependency is skipped")
        self.assertEqual(self.installs, ["OwnerB-ModB", "OwnerA-ModA"])

    def test_with_deps_false_installs_only_named_mod(self):
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB"])
        self.cascade("OwnerA-ModA", with_deps=False)
        self.assertEqual(self.installs, ["OwnerA-ModA"], "with_deps=False installs only the named mod")

    def test_missing_dependency_aborts_then_allow_missing_skips(self):
        self.add_pkg("OwnerA-ModA", deps=["OwnerMissing-Dep"])  # dep absent from the catalog
        res = self.cascade("OwnerA-ModA")
        self.assertFalse(res, "a missing dependency aborts the cascade by default")
        self.assertEqual(self.installs, [], "the mod is not installed when a dep can't be resolved")

        self.installs.clear()
        res = self.cascade("OwnerA-ModA", allow_missing=True)
        self.assertTrue(res, "allow_missing installs the mod, skipping the unresolved dep")
        self.assertEqual(self.installs, ["OwnerA-ModA"])

    def test_rollback_undoes_freshly_installed_on_partial_failure(self):
        # A needs B and C; B installs, C fails -> the whole cascade rolls back B (via the public entry).
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerC-ModC")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB", "OwnerC-ModC"])
        self.install_results["OwnerC-ModC"] = False
        res = run(self.plugin.install_thunderstore_mod(1, "OwnerA-ModA"))
        self.assertFalse(res)
        self.assertEqual(self.rolled_back, ["OwnerB-ModB"], "a partial install is rolled back; only freshly-installed mods are undone")
        self.assertNotIn("OwnerA-ModA", self.installs, "the named mod is never installed once a dep fails")

    def test_resolve_plan_orders_deps_before_parent_and_drops_installed(self):
        self.add_pkg("OwnerB-ModB")
        self.add_pkg("OwnerA-ModA", deps=["OwnerB-ModB"])
        plan = []
        plugin_thunderstore_install._resolve_thunderstore_plan(
            self.game, "OwnerA-ModA", None, True, set(), plan, [], self.install_dir, self.denylist)
        self.assertEqual(plan, ["OwnerB-ModB", "OwnerA-ModA"], "plan sizes deps before the parent (depth-first)")

        self.mark_installed_on_disk("OwnerB-ModB")
        plan2 = []
        plugin_thunderstore_install._resolve_thunderstore_plan(
            self.game, "OwnerA-ModA", None, True, set(), plan2, [], self.install_dir, self.denylist)
        self.assertEqual(plan2, ["OwnerA-ModA"], "an already-installed dep drops out of the plan count")


if __name__ == "__main__":
    unittest.main()
