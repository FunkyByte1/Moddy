"""Tests for the ignore_unused flag (mods.set_ignore_unused).

Lets a user mark an installed library as an intentional/undocumented dependency so the
Installed tab's unused-libraries cleanup ("broom") stops flagging it. Stored on the install
record; the flag is surfaced to the frontend by get_installed_mods, which does the actual
unused-graph filtering.
"""
import unittest

from _harness import mods, reset_store


class SetIgnoreUnusedTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        # A minimal tracked record is enough — set_ignore_unused only edits the store entry.
        mods.set_installed_record("Some.Library", version="1.0.0", filename="Some.Library")

    def test_sets_and_clears_the_flag(self):
        self.assertTrue(mods.set_ignore_unused("Some.Library", True))
        self.assertTrue(mods.get_installed_record("Some.Library").get("ignore_unused"))
        # Clearing drops the key entirely (kept tidy), not stores False.
        self.assertTrue(mods.set_ignore_unused("Some.Library", False))
        self.assertNotIn("ignore_unused", mods.get_installed_record("Some.Library"))

    def test_case_insensitive_match(self):
        # Catalog ids can differ in casing from what was persisted.
        self.assertTrue(mods.set_ignore_unused("some.library", True))
        self.assertTrue(mods.get_installed_record("Some.Library").get("ignore_unused"))

    def test_returns_false_for_unknown_mod(self):
        self.assertFalse(mods.set_ignore_unused("Not.Installed", True))


if __name__ == "__main__":
    unittest.main()
