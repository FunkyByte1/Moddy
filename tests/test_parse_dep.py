"""Unit tests for thunderstore.parse_dep — the dependency-string parser that splits a
Thunderstore dep ("Owner-Package-1.2.3") into (full_name, version). It anchors on the trailing
semver so it handles owner/package names that themselves contain hyphens, which is the whole
reason it's a regex and not a naive rsplit. Pure function; previously untested.
"""
import unittest

from _harness import reset_store  # noqa: F401  (imported for its sys.path / fake-decky side effects)
import thunderstore


class ParseDepTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(thunderstore.parse_dep("RiskofThunder-R2API_Core-5.0.10"),
                         ("RiskofThunder-R2API_Core", "5.0.10"))

    def test_owner_or_package_with_hyphens(self):
        # The trailing semver is the anchor, so hyphenated owner/package names survive intact.
        self.assertEqual(thunderstore.parse_dep("FunkFrog-and-Sipondo-ShareSuite-2.5.1"),
                         ("FunkFrog-and-Sipondo-ShareSuite", "2.5.1"))

    def test_prerelease_or_build_suffix(self):
        self.assertEqual(thunderstore.parse_dep("Owner-Mod-1.2.3-beta"), ("Owner-Mod", "1.2.3-beta"))

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(thunderstore.parse_dep("  Owner-Mod-1.0.0  "), ("Owner-Mod", "1.0.0"))

    def test_no_version_returns_none(self):
        self.assertIsNone(thunderstore.parse_dep("Owner-Mod"))
        self.assertIsNone(thunderstore.parse_dep("NoVersionHere"))

    def test_non_semver_tail_returns_none(self):
        self.assertIsNone(thunderstore.parse_dep("Owner-Mod-notaversion"))
        self.assertIsNone(thunderstore.parse_dep("Owner-Mod-1.2"))


if __name__ == "__main__":
    unittest.main()
