"""export_logs bundles the installed.json store (live + .bak + quarantined copies)
alongside the logs, and still excludes settings.json (it holds the Nexus API key)."""
import asyncio
import os
import tempfile
import unittest
import zipfile

from _harness import decky, reset_store

import plugin_diagnostics


class TestDiagnosticsExport(unittest.TestCase):
    def setUp(self):
        reset_store()
        decky.DECKY_PLUGIN_LOG_DIR = tempfile.mkdtemp(prefix="moddy-logs-")
        self.settings = decky.DECKY_PLUGIN_SETTINGS_DIR

    def _write(self, dirpath, name, text="x"):
        path = os.path.join(dirpath, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_export_bundles_logs_store_and_quarantine_but_not_settings(self):
        self._write(decky.DECKY_PLUGIN_LOG_DIR, "plugin.log", "log line")
        self._write(self.settings, "installed.json", '{"schema": 1, "mods": {}}')
        self._write(self.settings, "installed.json.bak", '{"schema": 1, "mods": {}}')
        self._write(self.settings, "installed.json.corrupt-1751400000", "{garbage")
        self._write(self.settings, "settings.json", '{"nexus_api_key": "SECRET"}')

        dest = asyncio.run(plugin_diagnostics.export_logs())
        self.assertIsNotNone(dest)
        with zipfile.ZipFile(dest) as zf:
            names = set(zf.namelist())
        os.remove(dest)
        self.assertIn("moddy-info.txt", names)
        self.assertIn("logs/plugin.log", names)
        self.assertIn("store/installed.json", names)
        self.assertIn("store/installed.json.bak", names)
        self.assertIn("store/installed.json.corrupt-1751400000", names)
        self.assertNotIn("settings.json", names)
        self.assertFalse(any("settings.json" in n for n in names))

    def test_export_survives_missing_store(self):
        self._write(decky.DECKY_PLUGIN_LOG_DIR, "plugin.log")
        dest = asyncio.run(plugin_diagnostics.export_logs())
        self.assertIsNotNone(dest)
        with zipfile.ZipFile(dest) as zf:
            names = set(zf.namelist())
        os.remove(dest)
        self.assertIn("logs/plugin.log", names)
        self.assertFalse(any(n.startswith("store/") for n in names))


if __name__ == "__main__":
    unittest.main()
