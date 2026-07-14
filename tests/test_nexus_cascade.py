"""Characterization tests for the Nexus install cascade in plugin_nexus_install.

The Nexus cascade (_install_nexus_recursive) is a near-duplicate of the Thunderstore one and the
planned ModProvider refactor unifies the two, so its behavior needs pinning too: depth-first
requirement install, skip-already-installed, and the cross-domain-requirement skip that's specific
to Nexus. Driven through plugin_nexus_install with the nexus.* I/O and mods.install_mod stubbed; the
skip check runs against the real store + mods.installed_files_present.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, reset_store
import plugin_nexus_install
import nexus
import download_queue


def run(coro):
    return asyncio.run(coro)


async def _anoop(*a, **k):
    return None


class NexusCascadeTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(
            id="g", name="G", appid=1, mods_dir="",
            catalog={"type": "nexus", "nexus_domain": "testgame", "install_type": "zip_flat"},
        )

        self.installs = []            # mod ids passed to install_mod, in order
        self.requirements = {}        # mod_id -> [ {domain, mod_id, name}, ... ]

        async def _install_mod(game, install_dir, mod, version=None, url=None, variant=None, source=None):
            self.installs.append(mod.id)
            return True

        self._saved = {}

        def patch(mod_obj, name, value):
            self._saved[(mod_obj, name)] = getattr(mod_obj, name)
            setattr(mod_obj, name, value)

        patch(nexus, "get_mod", lambda domain, mod_id, force=False: {
            "name": f"Mod{mod_id}", "summary": "", "author": "a", "version": "1.0", "picture_url": "",
        })
        patch(nexus, "get_requirements", lambda domain, mod_id: self.requirements.get(mod_id, []))
        patch(nexus, "primary_file_id", lambda domain, mod_id: "fid")
        patch(nexus, "get_download_url", lambda domain, mod_id, file_id: "http://dl")
        patch(mods, "install_mod", _install_mod)
        patch(download_queue, "note_item", _anoop)
        patch(download_queue, "note_warning", _anoop)

    def tearDown(self):
        for (mod_obj, name), value in self._saved.items():
            setattr(mod_obj, name, value)

    def cascade(self, mod_id):
        return run(plugin_nexus_install._install_nexus_recursive(
            self.game, self.install_dir, "testgame", mod_id, None, set(), installed=[],
        ))

    def mark_installed_on_disk(self, key, rel):
        mods.set_installed_record(self.game.appid, key, "1.0", "f", paths=[rel])
        p = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()

    def test_installs_requirements_depth_first(self):
        self.requirements["100"] = [{"domain": "testgame", "mod_id": "200", "name": "Dep"}]
        res = self.cascade("100")
        self.assertTrue(res)
        self.assertEqual(self.installs, ["nexus.testgame.200", "nexus.testgame.100"],
                         "a same-domain requirement installs before the mod that needs it")

    def test_skips_already_installed_requirement(self):
        self.requirements["100"] = [{"domain": "testgame", "mod_id": "200", "name": "Dep"}]
        self.mark_installed_on_disk("nexus.testgame.200", "mods/Dep/dep.dll")
        self.cascade("100")
        self.assertEqual(self.installs, ["nexus.testgame.100"], "an already-installed requirement (files present) is skipped")

    def test_cross_domain_requirement_is_skipped_not_installed(self):
        # A requirement in a different game's Nexus domain can't be installed in this game's context.
        self.requirements["100"] = [{"domain": "othergame", "mod_id": "999", "name": "Foreign"}]
        res = self.cascade("100")
        self.assertTrue(res)
        self.assertEqual(self.installs, ["nexus.testgame.100"], "a cross-domain requirement is skipped, not installed")


if __name__ == "__main__":
    unittest.main()
