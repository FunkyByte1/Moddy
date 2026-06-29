"""Path-traversal ("Zip Slip") guards on the manual archive-extraction loops.

zipfile.extractall/extract sanitise `..` themselves, but the hand-rolled `z.open() + os.path.join`
loops in _merge_zip_into_tree (BepInEx/Thunderstore merges) and _install_mod_zip_flat (MelonLoader)
build the destination from the RAW member name and bypass that. A crafted mod archive whose entry is
`BepInEx/../../../../home/deck/.bashrc` would otherwise land outside both the staging dir and the
install dir. mods_archive.safe_rel() rejects those before any byte is written. See the security
review notes — a traversal write is worse than "mods are code already" because it lands files that
execute WITHOUT launching the modded game (~/.bashrc, autostart).
"""
import asyncio
import os
import tempfile
import unittest

from _harness import mods, utils, make_mod, make_game, reset_store, stub_download
import mods_archive  # noqa: E402 — _harness puts backend/ on sys.path


def run(coro):
    return asyncio.run(coro)


class SafeRelTest(unittest.TestCase):
    def test_allows_normal_paths(self):
        self.assertEqual(mods_archive.safe_rel("BepInEx/plugins/Mod/x.dll"),
                         os.path.normpath("BepInEx/plugins/Mod/x.dll"))

    def test_allows_inner_dotdot_that_stays_contained(self):
        # a/../b normalises to b — still inside the target, so it's fine.
        self.assertEqual(mods_archive.safe_rel("a/../b.dll"), "b.dll")

    def test_rejects_leading_traversal(self):
        with self.assertRaises(ValueError):
            mods_archive.safe_rel("../escaped.dll")

    def test_rejects_deep_traversal_under_prefix(self):
        with self.assertRaises(ValueError):
            mods_archive.safe_rel("BepInEx/../../../../home/deck/.bashrc")

    def test_rejects_absolute_path(self):
        with self.assertRaises(ValueError):
            mods_archive.safe_rel("/etc/cron.d/evil")

    def test_rejects_backslash_traversal(self):
        with self.assertRaises(ValueError):
            mods_archive.safe_rel("..\\..\\evil.dll")


class FlatInstallZipSlipTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game(mods_dir="Mods")
        self.mods_path = os.path.join(self.install_dir, "Mods")
        os.makedirs(self.mods_path)
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def test_traversal_entry_is_rejected_and_nothing_escapes(self):
        # A zip carrying a legit DLL alongside a traversal entry aiming above the install dir.
        utils.download = stub_download(writes={"Good.dll": b"v1", "../../escaped.dll": b"PWNED"})
        mod = make_mod(install_type="zip_flat", filename="Cool")
        res = run(mods._install_mod_zip_flat(self.game, self.install_dir, self.mods_path, mod, "1.0.0", "http://x"))

        self.assertFalse(res)  # install bails rather than placing a half-payload
        # The malicious file lands nowhere — not above the install dir, not inside it.
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.install_dir), "escaped.dll")))
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "escaped.dll")))
        # All-or-nothing: the legit file from the same archive isn't placed either.
        self.assertFalse(os.path.exists(os.path.join(self.mods_path, "Good.dll")))


class MergeInstallZipSlipTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        self.install_dir = tempfile.mkdtemp(prefix="moddy-game-")
        self.game = make_game()  # BepInEx/plugins
        self.mods_path = os.path.join(self.install_dir, "BepInEx", "plugins")
        os.makedirs(self.mods_path)
        self._orig_download = utils.download

    def tearDown(self):
        utils.download = self._orig_download

    def test_bepinex_prefixed_traversal_is_rejected(self):
        # Passes the `startswith("BepInEx/")` select() check but escapes via `..`.
        utils.download = stub_download(writes={
            "BepInEx/plugins/Real/real.dll": b"v1",
            "BepInEx/../../../../escaped.dll": b"PWNED",
        })
        mod = make_mod(install_type="zip_dir", filename="Cool")
        res = run(mods._install_mod_zip_dir(self.game, self.install_dir, self.mods_path, mod, "1.0.0", "http://x"))

        self.assertFalse(res)
        self.assertFalse(os.path.exists(os.path.join(self.install_dir, "escaped.dll")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.install_dir), "escaped.dll")))


class RedactUrlTest(unittest.TestCase):
    def test_strips_nexus_signed_query(self):
        url = "https://cf-files.nexusmods.com/cdn/2050650/123/Mod.zip?md5=SECRET&expires=99&user_id=42"
        self.assertEqual(utils.redact_url(url),
                         "https://cf-files.nexusmods.com/cdn/2050650/123/Mod.zip")

    def test_leaves_query_less_urls_intact(self):
        url = "https://github.com/owner/repo/releases/download/v1/loader.zip"
        self.assertEqual(utils.redact_url(url), url)


class DownloadSchemeTest(unittest.TestCase):
    def test_file_scheme_refused(self):
        with self.assertRaises(Exception) as cm:
            run(utils.download("file:///etc/passwd", "/tmp/moddy-should-not-write", 1))
        self.assertIn("HTTP", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
