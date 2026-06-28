"""Tests for the Nexus search-query builder (_search_query).

The headline pin: free-text search uses the `name` filter (case-insensitive substring), NOT
`nameStemmed`. nameStemmed stems the index but not the query, so an inflected term ("diablos")
can't match the stored stem ("diablo") and returns nothing — even though `name` matches "Diablos".
This guards the fix; the actual match behaviour was verified live against the v2 GraphQL API.
"""
import unittest

from _harness import reset_store  # noqa: F401  (ensures fake decky is installed)
import nexus


class NexusSearchQueryTest(unittest.TestCase):
    def test_uses_name_substring_not_stemmed(self):
        q = nexus._search_query("monsterhunterworld", "diablos", 25, 0)
        self.assertIn('name:{value:"diablos",op:WILDCARD}', q)
        self.assertNotIn("nameStemmed", q)

    def test_short_term_skips_the_filter(self):
        # WILDCARD rejects 1-char terms server-side, so the filter is omitted (show the game list).
        q = nexus._search_query("monsterhunterworld", "d", 25, 0)
        self.assertNotIn("name:{value", q)
        self.assertIn("gameDomainName", q)

    def test_adult_excluded_by_default_included_on_opt_in(self):
        excluded = nexus._search_query("mhw", "armor", 25, 0, include_adult=False)
        self.assertIn("adultContent:{value:false,op:EQUALS}", excluded)
        included = nexus._search_query("mhw", "armor", 25, 0, include_adult=True)
        self.assertNotIn("adultContent", included)

    def test_term_is_json_encoded_against_injection(self):
        # A term with a quote must be escaped, not break out of the filter string.
        q = nexus._search_query("mhw", 'evil"}', 25, 0)
        self.assertIn(r'name:{value:"evil\"}",op:WILDCARD}', q)


if __name__ == "__main__":
    unittest.main()
