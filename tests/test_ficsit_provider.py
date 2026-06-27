"""Unit tests for the ficsit.app provider helpers (no network): id parsing, download URL, version
target filtering, dependency extraction, sort mapping, and catalog-item shaping."""
import unittest

from _harness import reset_store  # noqa: F401  (installs the fake decky before importing ficsit)
import ficsit


def _mod(ref, targets, deps=None):
    return {
        "id": f"id{ref}", "name": f"Mod {ref}", "mod_reference": ref,
        "short_description": "desc", "logo": "logo.webp",
        "authors": [{"user": {"username": "owner"}}],
        "last_version_date": "2026-06-01T00:00:00Z", "downloads": 1234,
        "versions": [{
            "id": f"v{ref}", "version": "1.2.3", "hash": "h", "size": 9,
            "dependencies": deps or [],
            "targets": [{"targetName": t} for t in targets],
        }],
    }


class FicsitProviderHelpersTest(unittest.TestCase):
    def test_parse_id(self):
        self.assertEqual(ficsit.parse_id("ficsit.RefinedPower"), "RefinedPower")
        self.assertEqual(ficsit.parse_id("ficsit.SML"), "SML")
        self.assertIsNone(ficsit.parse_id("nexus.foo.1"))
        self.assertIsNone(ficsit.parse_id("ficsit."))
        self.assertIsNone(ficsit.parse_id(""))

    def test_download_url_targets_windows(self):
        self.assertEqual(ficsit.download_url("abc"),
                         "https://api.ficsit.app/v1/version/abc/Windows/download")

    def test_windows_version_present(self):
        v = ficsit.windows_version(_mod("A", ["LinuxServer", "Windows", "WindowsServer"]))
        self.assertEqual(v, {"version": "1.2.3", "version_id": "vA", "hash": "h", "size": 9})

    def test_windows_version_absent_for_server_only(self):
        self.assertIsNone(ficsit.windows_version(_mod("A", ["LinuxServer", "WindowsServer"])))

    def test_windows_version_none_when_no_versions(self):
        self.assertIsNone(ficsit.windows_version({"versions": []}))

    def test_dependencies_passthrough(self):
        deps = [{"mod_id": "SML", "condition": "^3.0.0", "optional": False}]
        self.assertEqual(ficsit.dependencies(_mod("A", ["Windows"], deps)), deps)
        self.assertEqual(ficsit.dependencies({"versions": []}), [])

    def test_sort_whitelist(self):
        self.assertEqual(ficsit._SORTS["updated"], "last_version_date")
        self.assertIn("popularity", ficsit._SORTS)
        # An unknown sort falls back to the default inside the query builder, never injected raw.
        q = ficsit._search_query("", 25, 0, "bogus")
        self.assertIn(f"order_by:{ficsit._SORTS[ficsit.DEFAULT_SORT]}", q)

    def test_search_query_escapes_term_and_uses_relevance(self):
        q = ficsit._search_query('be"lt', 25, 0, "popularity")
        self.assertIn("order_by:search", q)           # a term switches to relevance ranking
        self.assertIn('search:"be\\"lt"', q)          # JSON-encoded, can't break out of the string

    def test_mod_to_item_shape(self):
        item = ficsit._mod_to_item(_mod("RefinedPower", ["Windows"]))
        self.assertEqual(item["full_name"], "ficsit.RefinedPower")
        self.assertEqual(item["owner"], "owner")
        self.assertEqual(item["rating_score"], 1234)
        self.assertEqual(item["package_url"], "https://ficsit.app/mod/idRefinedPower")
        self.assertEqual(item["latest"]["version_number"], "1.2.3")
        self.assertEqual(item["latest"]["icon"], "logo.webp")
        self.assertEqual(item["date_updated"], "2026-06-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
