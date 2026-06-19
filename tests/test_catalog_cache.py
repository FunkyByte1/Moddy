"""Unit tests for catalog_cache — the shared whole-catalog disk+memory cache used by the
Thunderstore and BMI providers. Covers the fresh / in-memory / on-disk / forced paths, the
on-disk format, the stale-fallback-on-fetch-failure behavior, and refreshed()'s True/False
contract. (catalog_cache was extracted from thunderstore.py + bmi.py and previously had no tests.)
"""
import json
import os
import tempfile
import unittest

# _harness installs the fake `decky` module and puts backend/ on sys.path.
from _harness import reset_store
import catalog_cache


class CountingFetch:
    """A fetch_fn that records its call count and returns a fixed payload (or raises)."""

    def __init__(self, payload=None, raises=None):
        self.payload = payload if payload is not None else [{"full_name": "A-B", "name": "B"}]
        self.raises = raises
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.payload


class CatalogCacheTest(unittest.TestCase):
    def setUp(self):
        reset_store()
        catalog_cache._mem_catalog.clear()  # process-lifetime cache must not leak across tests
        self.dir = tempfile.mkdtemp(prefix="moddy-cache-")
        self.path = os.path.join(self.dir, "catalog.json")

    def test_first_call_fetches_writes_and_serves_from_memory(self):
        fetch = CountingFetch()
        r1 = catalog_cache.get_or_fetch(self.path, fetch, label="t")
        self.assertEqual(r1, [{"full_name": "A-B", "name": "B"}])
        self.assertEqual(fetch.calls, 1)
        # On-disk format is pinned: {fetched_at, packages}.
        with open(self.path) as f:
            disk = json.load(f)
        self.assertIn("fetched_at", disk)
        self.assertEqual(disk["packages"], r1)
        # Second call serves from the in-memory cache — no second fetch.
        r2 = catalog_cache.get_or_fetch(self.path, fetch, label="t")
        self.assertEqual(r2, r1)
        self.assertEqual(fetch.calls, 1)

    def test_fresh_disk_cache_served_after_memory_cleared(self):
        catalog_cache.get_or_fetch(self.path, CountingFetch(), label="t")
        catalog_cache._mem_catalog.clear()  # simulate a fresh process; the on-disk cache is still fresh
        fetch = CountingFetch(payload=[{"full_name": "X-Y", "name": "Y"}])
        r = catalog_cache.get_or_fetch(self.path, fetch, label="t")
        self.assertEqual(fetch.calls, 0, "a fresh on-disk cache must be served without fetching")
        self.assertEqual(r, [{"full_name": "A-B", "name": "B"}])

    def test_stale_disk_cache_triggers_refetch(self):
        # Hand-write a cache whose fetched_at is far past the TTL.
        with open(self.path, "w") as f:
            json.dump({"fetched_at": 0, "packages": [{"full_name": "OLD", "name": "old"}]}, f)
        catalog_cache._mem_catalog.clear()
        fetch = CountingFetch(payload=[{"full_name": "NEW", "name": "new"}])
        r = catalog_cache.get_or_fetch(self.path, fetch, label="t")
        self.assertEqual(fetch.calls, 1, "a stale (past-TTL) cache must trigger a re-fetch")
        self.assertEqual(r, [{"full_name": "NEW", "name": "new"}])

    def test_force_bypasses_fresh_cache(self):
        catalog_cache.get_or_fetch(self.path, CountingFetch(), label="t")
        fetch = CountingFetch(payload=[{"full_name": "NEW", "name": "new"}])
        r = catalog_cache.get_or_fetch(self.path, fetch, force=True, label="t")
        self.assertEqual(fetch.calls, 1, "force=True must skip the fresh-cache shortcut")
        self.assertEqual(r, [{"full_name": "NEW", "name": "new"}])

    def test_failed_fetch_falls_back_to_stale_cache(self):
        catalog_cache.get_or_fetch(self.path, CountingFetch(), label="t")  # seed disk + memory
        catalog_cache._mem_catalog.clear()
        boom = CountingFetch(raises=RuntimeError("network down"))
        r = catalog_cache.get_or_fetch(self.path, boom, force=True, label="t")
        self.assertEqual(r, [{"full_name": "A-B", "name": "B"}],
                         "a failed fetch must return the stale cache, not []")

    def test_failed_fetch_with_no_cache_returns_empty(self):
        boom = CountingFetch(raises=RuntimeError("network down"))
        r = catalog_cache.get_or_fetch(self.path, boom, label="t")
        self.assertEqual(r, [], "a failed fetch with no cache to fall back to returns []")

    def test_refreshed_reports_success_vs_fallback(self):
        catalog_cache.get_or_fetch(self.path, CountingFetch(), label="t")  # an existing cache to refresh over
        ok = catalog_cache.refreshed(self.path, CountingFetch(payload=[{"full_name": "N", "name": "n"}]), label="t")
        self.assertTrue(ok, "refreshed must report True when a fresh copy is fetched (cache file rewritten)")
        boom = CountingFetch(raises=RuntimeError("down"))
        fell_back = catalog_cache.refreshed(self.path, boom, label="t")
        self.assertFalse(fell_back, "refreshed must report False when it falls back to the existing cache")
        # The fallback must have left the prior cache intact.
        self.assertEqual(catalog_cache.get_or_fetch(self.path, CountingFetch(raises=AssertionError("should not fetch")), label="t"),
                         [{"full_name": "N", "name": "n"}])


if __name__ == "__main__":
    unittest.main()
