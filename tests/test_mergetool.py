"""Tests for the external merge-tool framework (mods_mergetool) and the Fields of Mistria wiring.

Pure-logic only — the CLI subprocess itself is integration-tested on device. Covers: the registry
parsing of the declarative merge_tool config, the Fields game routing to install_type external_merge,
the Aurie high-risk detector, and the game-update staleness semantics (is_stale vs _buildid_changed).
"""
import os
import asyncio
import tempfile
import unittest

from _harness import registry, reset_store
import mods_mergetool as mt
import game_store
import download_queue


class MergeToolRegistryTest(unittest.TestCase):
    def test_momi_loader_parses_merge_tool(self):
        ml = registry._load_modloaders().get("momi")
        self.assertIsNotNone(ml)
        self.assertEqual(ml.source.type, "external_cli")
        cfg = ml.merge_tool
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.tool_id, "momi")
        self.assertEqual(cfg.owner, "Garethp")
        self.assertEqual(cfg.asset, "ModsOfMistriaInstaller-cli-linux")
        self.assertFalse(cfg.asset_is_zip)
        self.assertEqual(cfg.restore_argv, ["--uninstall"])
        self.assertEqual(cfg.env.get("EXIT_ON_COMPLETE"), "true")
        self.assertTrue(cfg.tool_owns_backup)
        self.assertIn("data.bak.win", cfg.backup_glob)
        self.assertEqual(cfg.high_risk_glob, "aurie/*.dll")
        self.assertEqual(cfg.high_risk_policy, "deny")

    def test_fields_game_routes_to_external_merge(self):
        game = registry.get_game_by_appid(2142790)
        self.assertIsNotNone(game)
        self.assertEqual(game.mods_dir, "mods")
        self.assertFalse(game.requires_proton)
        self.assertEqual(game.catalog.get("install_type"), "external_merge")
        ml = mt.merge_loader(game)
        self.assertIsNotNone(ml)
        self.assertEqual(ml.id, "momi")

    def test_a_non_merge_game_has_no_merge_loader(self):
        game = registry.get_game_by_appid(632360)  # Risk of Rain 2 (BepInEx)
        if game:
            self.assertIsNone(mt.merge_loader(game))


class HighRiskDetectorTest(unittest.TestCase):
    def setUp(self):
        self.cfg = registry._load_modloaders()["momi"].merge_tool

    def _mod(self, rel_files):
        root = tempfile.mkdtemp(prefix="moddy-mod-")
        for rel in rel_files:
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        return root

    def test_aurie_dll_is_high_risk(self):
        self.assertTrue(mt.detect_high_risk(self._mod(["MyMod/aurie/thing.dll"]), self.cfg))

    def test_asset_mod_is_not_high_risk(self):
        self.assertFalse(mt.detect_high_risk(
            self._mod(["MyMod/manifest.json", "MyMod/sprites/a.png", "MyMod/fiddle/x.json"]), self.cfg))

    def test_empty_glob_never_flags(self):
        cfg = registry._load_modloaders()["momi"].merge_tool
        cfg.high_risk_glob = ""
        self.assertFalse(mt.detect_high_risk(self._mod(["MyMod/aurie/thing.dll"]), cfg))


class StalenessTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.appid = 2142790
        self._orig_buildid = mt.steam.get_build_id

    def tearDown(self):
        mt.steam.get_build_id = self._orig_buildid

    def test_not_stale_when_never_applied(self):
        mt.steam.get_build_id = lambda appid, libraries=None: "500"
        # No last_buildid recorded → nothing baked → not stale.
        self.assertFalse(mt.is_stale(self.appid))

    def test_stale_when_buildid_changed_after_apply(self):
        game_store.section(self.appid, "mergetool")["last_buildid"] = "100"
        game_store.save()
        mt.steam.get_build_id = lambda appid, libraries=None: "200"
        self.assertTrue(mt.is_stale(self.appid))

    def test_not_stale_when_buildid_unchanged(self):
        game_store.section(self.appid, "mergetool")["last_buildid"] = "100"
        game_store.save()
        mt.steam.get_build_id = lambda appid, libraries=None: "100"
        self.assertFalse(mt.is_stale(self.appid))

    def test_is_applied_defaults_true_then_reflects_flag(self):
        self.assertTrue(mt.is_applied(self.appid))       # default before any apply/restore
        game_store.section(self.appid, "mergetool")["applied"] = False
        game_store.save()
        self.assertFalse(mt.is_applied(self.appid))


class CoalesceTest(unittest.TestCase):
    """The debounced-rebuild bookkeeping (the async settle timer itself is integration-only)."""
    def setUp(self):
        reset_store()
        self.appid = 2142790

    def test_is_apply_pending_reflects_dirty(self):
        self.assertFalse(mt.is_apply_pending(self.appid))
        game_store.section(self.appid, "mergetool")["dirty"] = True
        game_store.save()
        self.assertTrue(mt.is_apply_pending(self.appid))

    def test_flush_pending_is_noop_when_not_dirty(self):
        self.assertFalse(asyncio.run(mt.flush_pending(self.appid)))

    def test_download_queue_idle_by_default(self):
        self.assertFalse(download_queue.is_active())


if __name__ == "__main__":
    unittest.main()
