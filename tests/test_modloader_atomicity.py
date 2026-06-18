"""Atomicity tests for the modloader installers (modloaders.py), converted to _StagedInstall.

Headline fix: installing/updating BepInEx no longer wipes a user's BepInEx/plugins/. The old
thunderstore path rmtree'd the whole BepInEx/ dir before copying the pack's back; it now merges,
overwriting only the pack's own files. The github (MelonLoader) path keeps clean-replace of its
loader-owned dirs but leaves the separate Mods/ dir untouched, and both now roll back on failure.
"""
import asyncio
import os
import tempfile
import unittest

from _harness import registry, utils, reset_store, tree_snapshot, stub_download, failing_copy2, bak_crumbs
import modloaders
import thunderstore
import github


def run(coro):
    return asyncio.run(coro)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def make_modloader(ml_id, source_type, files, dirs):
    return registry.ModloaderInfo(
        id=ml_id, name=ml_id,
        source=registry.ModSource(type=source_type, owner="o", repo="r", asset="a.zip"),
        files=files, dirs=dirs,
    )


class ThunderstoreModloaderTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(id="g", name="G", appid=1, mods_dir="BepInEx/plugins")
        self.ml = make_modloader("bepinex", "thunderstore", ["winhttp.dll"], ["BepInEx"])
        self._orig_dl, self._orig_url = utils.download, thunderstore.get_download_url
        thunderstore.get_download_url = lambda *a, **k: "http://x"

    def tearDown(self):
        utils.download, thunderstore.get_download_url = self._orig_dl, self._orig_url

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def test_update_preserves_user_plugins(self):
        # Existing BepInEx install with a user-installed plugin and an old core file.
        write(os.path.join(self.install_dir, "winhttp.dll"), b"old")
        write(os.path.join(self.install_dir, "BepInEx/core/BepInEx.Core.dll"), b"old-core")
        write(os.path.join(self.install_dir, "BepInEx/plugins/MyMod/MyMod.dll"), b"user-mod")

        # The pack ships under an inner BepInExPack/ folder.
        utils.download = stub_download(writes={
            "BepInExPack/winhttp.dll": b"new",
            "BepInExPack/BepInEx/core/BepInEx.Core.dll": b"new-core",
        })
        ok = run(modloaders._install_thunderstore_modloader(self.game, self.install_dir, self.ml, "2.0.0"))
        self.assertTrue(ok)
        # Pack files overwritten...
        with open(os.path.join(self.install_dir, "winhttp.dll"), "rb") as f:
            self.assertEqual(f.read(), b"new")
        # ...and the user's plugin survives (the whole point).
        self.assertTrue(self.exists("BepInEx/plugins/MyMod/MyMod.dll"), "user plugin must NOT be wiped on a loader update")
        self.assertEqual(bak_crumbs(self.install_dir), [])

    def test_failed_update_rolls_back(self):
        write(os.path.join(self.install_dir, "winhttp.dll"), b"old")
        write(os.path.join(self.install_dir, "BepInEx/plugins/MyMod/MyMod.dll"), b"user-mod")
        before = tree_snapshot(self.install_dir)

        utils.download = stub_download(writes={
            "BepInExPack/winhttp.dll": b"new",
            "BepInExPack/BepInEx/core/new.dll": b"new-core",
        })
        with failing_copy2(fail_on=2):  # winhttp lands, core file fails
            ok = run(modloaders._install_thunderstore_modloader(self.game, self.install_dir, self.ml, "2.0.0"))
        self.assertFalse(ok)
        self.assertEqual(tree_snapshot(self.install_dir), before, "failed loader update must restore the prior dir")
        self.assertEqual(bak_crumbs(self.install_dir), [])


class GithubModloaderTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = registry.GameProfile(id="g", name="G", appid=1, mods_dir="Mods")
        self.ml = make_modloader("melon", "github", ["version.dll"], ["MelonLoader"])
        self._orig_dl, self._orig_url = utils.download, github.get_download_url_for_version
        github.get_download_url_for_version = lambda *a, **k: "http://x"

    def tearDown(self):
        utils.download, github.get_download_url_for_version = self._orig_dl, self._orig_url

    def exists(self, rel):
        return os.path.exists(os.path.join(self.install_dir, rel))

    def test_update_replaces_loader_dir_but_keeps_user_mods(self):
        # Existing MelonLoader install + a user mod in the separate Mods/ dir.
        write(os.path.join(self.install_dir, "version.dll"), b"old")
        write(os.path.join(self.install_dir, "MelonLoader/net6/old.dll"), b"old")
        write(os.path.join(self.install_dir, "Mods/UserMod.dll"), b"user-mod")

        utils.download = stub_download(writes={"version.dll": b"new", "MelonLoader/net6/new.dll": b"new"})
        ok = run(modloaders._install_github_modloader(self.game, self.install_dir, self.ml, "2.0.0"))
        self.assertTrue(ok)
        # Loader-owned dir is cleanly replaced: new file in, stale old file gone.
        self.assertTrue(self.exists("MelonLoader/net6/new.dll"))
        self.assertFalse(self.exists("MelonLoader/net6/old.dll"), "loader dir is owned — old files replaced")
        # The user's mods dir (not part of the loader) is untouched.
        self.assertTrue(self.exists("Mods/UserMod.dll"))
        self.assertEqual(bak_crumbs(self.install_dir), [])

    def test_failed_update_restores_old_loader(self):
        write(os.path.join(self.install_dir, "version.dll"), b"old")
        write(os.path.join(self.install_dir, "MelonLoader/net6/old.dll"), b"old")
        before = tree_snapshot(self.install_dir)

        utils.download = stub_download(writes={"version.dll": b"new", "MelonLoader/net6/new.dll": b"new"})
        with failing_copy2(fail_on=2):
            ok = run(modloaders._install_github_modloader(self.game, self.install_dir, self.ml, "2.0.0"))
        self.assertFalse(ok)
        self.assertEqual(tree_snapshot(self.install_dir), before, "failed loader update must restore the old loader exactly")
        self.assertEqual(bak_crumbs(self.install_dir), [])


if __name__ == "__main__":
    unittest.main()
