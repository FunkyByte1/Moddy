"""Tests for the app_settings mtime-keyed cache.

Regression pin: the settings dict was cached once and never re-read, so an external
edit to settings.json (the README's documented way to set the Nexus key via Desktop
Mode / SSH) was masked until the next plugin restart — the Settings page showed a blank
key and NSFW off despite the file holding the real values. _load() now reloads when the
file's mtime changes.
"""
import json
import os
import tempfile
import unittest

from _harness import decky  # noqa: F401  (installs fake decky first)
import app_settings as settings


class SettingsCacheTest(unittest.TestCase):
    def setUp(self):
        decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp(prefix="moddy-settings-")
        settings._SETTINGS = None
        settings._MTIME = None

    def _write(self, data: dict, mtime: float):
        """Write settings.json and stamp a deterministic mtime (avoids coarse-clock flakiness)."""
        path = settings._path()
        with open(path, "w") as f:
            json.dump(data, f)
        os.utime(path, (mtime, mtime))

    def test_external_edit_is_picked_up_on_next_read(self):
        self._write({"nsfw_enabled": False}, mtime=1000)
        self.assertFalse(settings.get_setting("nsfw_enabled"))  # primes the cache
        # Simulate the user hand-editing the file (later mtime).
        self._write({"nsfw_enabled": True, "nexus_api_key": "ABC"}, mtime=2000)
        self.assertTrue(settings.get_setting("nsfw_enabled"))
        self.assertEqual(settings.get_setting("nexus_api_key"), "ABC")

    def test_cache_used_when_file_unchanged(self):
        self._write({"k": "v"}, mtime=1000)
        self.assertEqual(settings.get_setting("k"), "v")  # primes cache
        # Rewrite different content but keep the SAME mtime — the cache should still serve
        # the old value (proves we key on mtime, and that unchanged files don't re-read).
        self._write({"k": "changed"}, mtime=1000)
        self.assertEqual(settings.get_setting("k"), "v")

    def test_set_setting_does_not_trigger_a_reload_of_its_own_write(self):
        self._write({"a": 1}, mtime=1000)
        settings.get_setting("a")  # prime
        self.assertTrue(settings.set_setting("b", 2))
        # Both the prior key and the new one are present, and _MTIME tracks the fresh file.
        self.assertEqual(settings.get_setting("a"), 1)
        self.assertEqual(settings.get_setting("b"), 2)
        self.assertEqual(settings._MTIME, settings._file_mtime(settings._path()))


if __name__ == "__main__":
    unittest.main()
