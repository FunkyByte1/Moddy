"""Tests for nexus.primary_file_id file selection.

A Nexus mod page can list several MAIN files (e.g. Stardew Valley Expanded's optional alternate
farms are MAIN too). Picking the newest-uploaded MAIN file then grabs the add-on instead of the
mod, so the author's `is_primary` flag must win. Regression test for SVE/DCBurger installing the
wrong file.
"""
import unittest

import _harness  # noqa: F401 — installs the fake `decky` + backend sys.path
import nexus


class PrimaryFileIdTest(unittest.TestCase):
    def setUp(self):
        self._orig = nexus.get_files

    def tearDown(self):
        nexus.get_files = self._orig

    def _stub(self, files):
        nexus.get_files = lambda domain, mod_id: files

    def test_is_primary_wins_over_newer_main(self):
        # The SVE case: the optional alternate farm is MAIN and newer, but the author flagged the
        # real mod as primary.
        self._stub([
            {"file_id": 100, "category_name": "MAIN", "is_primary": True,  "file_name": "Stardew Valley Expanded"},
            {"file_id": 200, "category_name": "MAIN", "is_primary": False, "file_name": "Immersive Farm 2 Remastered"},
        ])
        self.assertEqual(nexus.primary_file_id("stardewvalley", "3753"), "100")

    def test_falls_back_to_newest_main_when_no_primary(self):
        self._stub([
            {"file_id": 10, "category_name": "MAIN", "file_name": "old"},
            {"file_id": 20, "category_name": "MAIN", "file_name": "new"},
            {"file_id": 30, "category_name": "OPTIONAL", "file_name": "optional-newest"},
        ])
        self.assertEqual(nexus.primary_file_id("d", "1"), "20")  # newest MAIN, not the newer OPTIONAL

    def test_falls_back_to_newest_any_when_no_main(self):
        self._stub([
            {"file_id": 5, "category_name": "OPTIONAL", "file_name": "a"},
            {"file_id": 9, "category_name": "MISCELLANEOUS", "file_name": "b"},
        ])
        self.assertEqual(nexus.primary_file_id("d", "1"), "9")

    def test_no_files(self):
        self._stub([])
        self.assertIsNone(nexus.primary_file_id("d", "1"))

    def test_primary_without_file_id_ignored(self):
        # A malformed primary entry (no file_id) must not be chosen; fall through to MAIN.
        self._stub([
            {"category_name": "MAIN", "is_primary": True, "file_name": "broken"},
            {"file_id": 42, "category_name": "MAIN", "is_primary": False, "file_name": "ok"},
        ])
        self.assertEqual(nexus.primary_file_id("d", "1"), "42")


class SelectableFilesTest(unittest.TestCase):
    """nexus.selectable_files filters to MAIN+OPTIONAL and sorts primary-first — drives the
    multi-file picker (e.g. SVE's main download + optional alternate farms)."""

    def setUp(self):
        self._orig = nexus.get_files

    def tearDown(self):
        nexus.get_files = self._orig

    def _stub(self, files):
        nexus.get_files = lambda domain, mod_id: files

    def test_filters_and_sorts(self):
        self._stub([
            {"file_id": 1, "category_name": "MAIN", "is_primary": False, "name": "B Main"},
            {"file_id": 2, "category_name": "MAIN", "is_primary": True, "name": "A Main"},
            {"file_id": 3, "category_name": "OPTIONAL", "name": "Addon"},
            {"file_id": 4, "category_name": "OLD_VERSION", "name": "old"},
            {"file_id": 5, "category_name": "ARCHIVED", "name": "arch"},
            {"file_id": 6, "category_name": "MISCELLANEOUS", "name": "docs"},
        ])
        files = nexus.selectable_files("d", "1")
        self.assertEqual([f["file_id"] for f in files], ["2", "1", "3"])  # primary, then MAIN, then OPTIONAL
        self.assertTrue(files[0]["is_primary"])
        self.assertEqual(files[2]["category"], "OPTIONAL")

    def test_single_file_no_choice(self):
        self._stub([{"file_id": 9, "category_name": "MAIN", "is_primary": True, "name": "only"}])
        self.assertEqual(len(nexus.selectable_files("d", "1")), 1)  # caller skips the picker for <2


if __name__ == "__main__":
    unittest.main()
