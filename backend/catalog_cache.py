"""Shared whole-catalog disk + memory cache.

The Thunderstore and BMI catalog providers both fetch a large whole-catalog
payload, parse it to the shared `catalog.CatalogItem` shape, and cache the result
on disk with a 1-day TTL plus a process-lifetime in-memory copy. The in-memory
copy is keyed by the cache file's mtime, so a force-refresh (which rewrites the
file) self-invalidates with no manual cache-busting. This module factors out that
identical machinery; each provider only supplies its own fetch-and-parse function.

A `get_supported_games()` refresh reloads catalogs on every frontend mod
toggle/install (to classify library mods), and the Browse tab + dependency
resolver reload them too — without the in-memory copy each call would re-read and
re-parse the multi-thousand-package JSON from disk.
"""

import json
import os
import time

import decky

CACHE_TTL_SECONDS = 86400  # 1 day

# Process-lifetime cache of the parsed catalog, keyed by cache_path → (mtime, packages).
_mem_catalog: dict[str, tuple[float, list[dict]]] = {}


def get_or_fetch(cache_path: str, fetch_fn, *, force: bool = False, label: str = "catalog") -> list[dict]:
    """Return the cached catalog at `cache_path`, or pull a fresh copy via `fetch_fn()`.

    `fetch_fn()` returns the parsed list of catalog items, or raises on any failure
    (network error, unexpected shape, parse error). On success the result is written
    to disk atomically and memoized. When `force=False`, a still-fresh on-disk or
    in-memory copy short-circuits the fetch. When `force=True`, the freshness shortcut
    is skipped, but a failed fetch still falls back to the existing cache. Returns []
    only when the fetch fails and there is no cache to fall back to. `label` is used
    only in log messages.
    """
    now = time.time()

    if not force:
        try:
            mtime = os.path.getmtime(cache_path)
            mem = _mem_catalog.get(cache_path)
            if mem and mem[0] == mtime and now - mtime < CACHE_TTL_SECONDS:
                # Parsed copy still matches the (still-fresh) on-disk file — skip the
                # read+parse. Past the TTL we fall through so the fetch path can refresh.
                return mem[1]
            with open(cache_path, "r") as f:
                cached = json.load(f)
            if now - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS:
                packages = cached.get("packages", [])
                _mem_catalog[cache_path] = (mtime, packages)
                return packages
        except FileNotFoundError:
            pass
        except Exception as e:
            decky.logger.warning(f"{label} cache read failed: {e}")

    try:
        packages = fetch_fn()
    except Exception as e:
        decky.logger.error(f"Failed to fetch {label}: {e}")
        return _read_stale(cache_path)

    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": now, "packages": packages}, f)
        os.replace(tmp, cache_path)
        _mem_catalog[cache_path] = (os.path.getmtime(cache_path), packages)
    except Exception as e:
        decky.logger.warning(f"{label} cache write failed: {e}")

    return packages


def refreshed(cache_path: str, fetch_fn, *, label: str = "catalog") -> bool:
    """Force a fresh pull, keeping the existing cache if the fetch fails. Returns True
    only if a fresh copy was actually fetched (the cache file was rewritten), False if
    it fell back to the existing cache.

    A successful fetch rewrites the cache file (and only then); a failed fetch falls back
    to the existing one untouched. So a bumped mtime means a fresh copy landed — no need
    to parse the whole catalog just to read its timestamp.
    """
    before = _cache_mtime(cache_path)
    get_or_fetch(cache_path, fetch_fn, force=True, label=label)
    return _cache_mtime(cache_path) > before


def _read_stale(cache_path: str) -> list[dict]:
    """Fall back to whatever packages are on disk after a failed fetch; [] if none usable."""
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "r") as f:
                return json.load(f).get("packages", [])
    except Exception:
        pass
    return []


def _cache_mtime(cache_path: str) -> float:
    try:
        return os.path.getmtime(cache_path)
    except OSError:
        return 0.0
