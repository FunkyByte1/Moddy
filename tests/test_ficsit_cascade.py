"""Characterization tests for the ficsit.app (Satisfactory) install cascade.

The FicsitProvider drives the shared dependency cascade like Nexus/Thunderstore, with two ficsit
specifics worth pinning: (1) SML — every Satisfactory mod's declared dependency — is skipped as a
loader, not installed as a content mod; (2) optional dependencies are not auto-installed. The
ficsit.* network calls and mods.install_mod are stubbed; the depth-first / skip-already-installed
logic runs against the real store + run_cascade.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, registry, reset_store
import ficsit
import install_cascade
import download_queue


def run(coro):
    return asyncio.run(coro)


async def _anoop(*a, **k):
    return None


def _mod(ref, deps=None, target="Windows"):
    """A getModByReference-shaped payload for mod_reference `ref`."""
    return {
        "id": f"id{ref}", "name": f"Mod {ref}", "mod_reference": ref,
        "short_description": "", "logo": "", "authors": [{"user": {"username": "a"}}],
        "versions": [{
            "id": f"v{ref}", "version": "1.0", "hash": "", "size": 1,
            "dependencies": deps or [],
            "targets": [{"targetName": target}],
        }],
    }


class FicsitCascadeTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(
            id="satisfactory", name="Satisfactory", appid=526870, mods_dir="FactoryGame/Mods",
            catalog={"type": "ficsit", "install_type": "zip_smod"},
            modloaders=[registry.ModloaderInfo(
                id="sml", name="SML",
                source=registry.ModSource(type="ficsit", mod_reference="SML"),
            )],
        )
        self.installs = []          # mod ids passed to install_mod, in order
        self.mods = {}              # ref -> getModByReference payload

        async def _install_mod(game, install_dir, mod, version=None, url=None, variant=None, source=None):
            self.installs.append(mod.id)
            return True

        self._saved = {}

        def patch(obj, name, value):
            self._saved[(obj, name)] = getattr(obj, name)
            setattr(obj, name, value)

        patch(ficsit, "get_mod", lambda ref, force=False: self.mods.get(ref))
        patch(mods, "install_mod", _install_mod)
        patch(download_queue, "note_item", _anoop)
        patch(download_queue, "note_warning", _anoop)

    def tearDown(self):
        for (obj, name), value in self._saved.items():
            setattr(obj, name, value)

    def cascade(self, ref):
        provider = install_cascade.FicsitProvider(set())
        return run(install_cascade.run_cascade(
            provider, self.game, self.install_dir, ref, None, seen=set(), installed=[], top=True,
        ))

    def mark_installed_on_disk(self, key, rel):
        mods.set_installed_record(self.game.appid, key, "1.0", "f", paths=[rel])
        p = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()

    def test_installs_dependencies_depth_first(self):
        self.mods["A"] = _mod("A", deps=[{"mod_id": "B", "condition": "^1.0.0", "optional": False}])
        self.mods["B"] = _mod("B")
        self.assertTrue(self.cascade("A"))
        self.assertEqual(self.installs, ["ficsit.B", "ficsit.A"],
                         "a dependency installs before the mod that needs it")

    def test_skips_sml_loader_dependency(self):
        # Every Satisfactory mod depends on SML, but it's the loader — never installed as a mod here.
        self.mods["A"] = _mod("A", deps=[{"mod_id": "SML", "condition": "^3.0.0", "optional": False}])
        self.mods["SML"] = _mod("SML")
        self.assertTrue(self.cascade("A"))
        self.assertEqual(self.installs, ["ficsit.A"], "SML (the loader) is skipped, not installed")

    def test_skips_optional_dependency(self):
        self.mods["A"] = _mod("A", deps=[{"mod_id": "B", "condition": "^1.0.0", "optional": True}])
        self.mods["B"] = _mod("B")
        self.assertTrue(self.cascade("A"))
        self.assertEqual(self.installs, ["ficsit.A"], "optional deps aren't auto-installed")

    def test_skips_already_installed_dependency(self):
        self.mods["A"] = _mod("A", deps=[{"mod_id": "B", "condition": "^1.0.0", "optional": False}])
        self.mods["B"] = _mod("B")
        self.mark_installed_on_disk("ficsit.B", "FactoryGame/Mods/B/B.uplugin")
        self.cascade("A")
        self.assertEqual(self.installs, ["ficsit.A"], "an already-installed dep (files present) is skipped")

    def test_server_only_mod_is_not_installable(self):
        # A mod whose latest version ships no Windows (client) build can't be installed on the Deck.
        self.mods["A"] = _mod("A", target="LinuxServer")
        res = self.cascade("A")
        self.assertFalse(res)
        self.assertEqual(self.installs, [], "no Windows target -> hard failure, nothing installed")

    def test_records_dependency_passes_install_type_zip_smod(self):
        self.mods["A"] = _mod("A")
        provider = install_cascade.FicsitProvider(set())
        spec = provider.build_install(self.game, self.mods["A"], "A", None)
        self.assertEqual(spec.mod.source.install_type, "zip_smod")
        self.assertEqual(spec.mod.source.type, "ficsit")
        self.assertEqual(spec.mod.source.mod_reference, "A")
        self.assertEqual(spec.url, ficsit.download_url("vA"))
        self.assertEqual(spec.mod.filename, "A")  # the on-disk folder name SML loads from


if __name__ == "__main__":
    unittest.main()
