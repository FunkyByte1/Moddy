"""Moddy's own update check (moddy_update).

Decky doesn't update URL-installed plugins, so this check is the only way an installed build
hears about a newer one. It compares the commit stamped into the running version with the
release manifest, announces each new release once, and must tolerate any manifest shape: old
builds will be reading manifests written long after they shipped.
"""
import unittest
from unittest import mock

from _harness import reset_store

import app_settings as settings
import fetch
import moddy_update


def _manifest(**over) -> dict:
    m = {"version": "2026.11.1+bbbbbbb", "commit": "bbbbbbb" + "0" * 33,
         "published_at": "2026-11-01T00:00:00Z", "download_url": "https://example.invalid/m.zip"}
    m.update(over)
    return m


class TestModdyUpdate(unittest.TestCase):
    def setUp(self):
        reset_store()
        settings._SETTINGS = None
        settings._MTIME = None

    def _check(self, version: str, manifest) -> dict:
        with mock.patch.object(fetch, "VERSION", version), \
                mock.patch.object(fetch, "fetch_json", return_value=manifest):
            return moddy_update.check()

    def test_newer_build_is_reported_and_announced_once(self):
        first = self._check("2026.10.18+aaaaaaa", _manifest())
        self.assertTrue(first["update_available"])
        self.assertTrue(first["notify"])
        self.assertEqual(first["latest"], "2026.11.1+bbbbbbb")
        second = self._check("2026.10.18+aaaaaaa", _manifest())
        self.assertTrue(second["update_available"])
        self.assertFalse(second["notify"])

    def test_same_commit_is_up_to_date(self):
        r = self._check("2026.11.1+bbbbbbb", _manifest())
        self.assertFalse(r["update_available"])
        self.assertFalse(r["notify"])

    def test_local_build_never_reports_an_update(self):
        r = self._check("2026.10.18", _manifest())
        self.assertTrue(r["dev_build"])
        self.assertFalse(r["update_available"])

    def test_notice_reaches_up_to_date_builds(self):
        r = self._check("2026.11.1+bbbbbbb", _manifest(notice="  Please update  "))
        self.assertEqual(r["notice"], "Please update")

    def test_unreachable_feed(self):
        r = self._check("2026.10.18+aaaaaaa", None)
        self.assertFalse(r["update_available"])
        self.assertIsNotNone(r["error"])

    def test_force_bypasses_the_fetch_cache(self):
        with mock.patch.object(fetch, "VERSION", "2026.11.1+bbbbbbb"), \
                mock.patch.object(fetch, "fetch_json", return_value=_manifest()) as fj:
            moddy_update.check()
            moddy_update.check(force=True)
        self.assertEqual([c.kwargs.get("fresh") for c in fj.call_args_list], [False, True])

    def test_tolerates_odd_manifests(self):
        for m in ({}, {"version": 5, "commit": None, "notice": ["x"]}, {"version": "2026.11.1+bbbbbbb"}):
            r = self._check("2026.10.18+aaaaaaa", m)
            self.assertIsNone(r["error"])
            self.assertIsNone(r["notice"])
        # No commit field: falls back to the version's build metadata.
        self.assertTrue(self._check("2026.10.18+aaaaaaa", {"version": "2026.11.1+bbbbbbb"})["update_available"])


if __name__ == "__main__":
    unittest.main()
