import json
import os
import re
import urllib.request
import decky

import catalog
import catalog_cache
import fetch

# ── Thunderstore package API ──────────────────────────────────────────────────
# Uses Thunderstore's "experimental" package API (the v1 per-package endpoint
# returns 404 as of 2025). This endpoint exposes only the latest version per
# package — full version history is not available without authentication.


def _get_package(author: str, name: str) -> dict | None:
    url = f"https://thunderstore.io/api/experimental/package/{author}/{name}/"
    data = fetch.fetch_json(url)
    if not data or not isinstance(data, dict):
        return None
    return data


def get_latest(author: str, name: str) -> dict | None:
    """Get latest version info for a Thunderstore package."""
    pkg = _get_package(author, name)
    if not pkg:
        return None
    latest = pkg.get("latest")
    if not latest:
        return None
    return {
        "version": latest["version_number"],
        "name": latest["full_name"],
        "download_url": latest["download_url"],
        "dependencies": latest.get("dependencies", []),  # list of "<author>-<name>-<version>" strings
    }


def get_all_versions(author: str, name: str) -> list[dict]:
    """Return the available versions for a Thunderstore package.
    The experimental API only exposes the latest version, so this returns at most one entry.
    """
    latest = get_latest(author, name)
    if not latest:
        return []
    return [{
        "version": latest["version"],
        "name": latest["name"],
        "download_url": latest["download_url"],
        "published_at": "",
        "download_urls": {f"{author}-{name}-{latest['version']}.zip": latest["download_url"]},
    }]


def get_download_url(author: str, name: str, version: str) -> str:
    """Get direct download URL for a specific Thunderstore package version."""
    return f"https://thunderstore.io/package/download/{author}/{name}/{version}/"


# ── Thunderstore community catalog ────────────────────────────────────────────
# The community-wide catalog (api/v1/package/) lists every package and its full
# version history. For RoR2 in 2026 that's ~47 MB / 7k packages. The UI only
# needs the latest version of each package, so we trim aggressively on the
# server before handing it across the WebSocket bridge. The trimmed result is
# cached on disk with a 1-day TTL (see catalog_cache) so the Browse tab opens
# instantly and we stay courteous to the Thunderstore API; users can force a
# fresh pull from the Options menu.


def _catalog_cache_path(community: str) -> str:
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"thunderstore-catalog-{community}.json")


def _trim_package(pkg: dict) -> dict | None:
    """Reduce a Thunderstore catalog package to the fields the UI needs.
    Drops the full version history (~80% of payload weight) and keeps only the latest."""
    versions = pkg.get("versions") or []
    if not versions:
        return None
    latest = versions[0]
    return catalog.make_item(
        name=pkg.get("name", ""),
        full_name=pkg.get("full_name", ""),
        owner=pkg.get("owner", ""),
        package_url=pkg.get("package_url", ""),
        donation_link=pkg.get("donation_link"),
        date_updated=pkg.get("date_updated", ""),
        rating_score=pkg.get("rating_score", 0),
        is_deprecated=bool(pkg.get("is_deprecated", False)),
        has_nsfw_content=bool(pkg.get("has_nsfw_content", False)),
        categories=list(pkg.get("categories", [])),
        version_number=latest.get("version_number", ""),
        description=latest.get("description", ""),
        icon=latest.get("icon", ""),
        dependencies=list(latest.get("dependencies", [])),
        download_url=latest.get("download_url", ""),
        file_size=latest.get("file_size", 0),
    )


def _fetch_community_catalog(community: str) -> list[dict]:
    """Pull the raw community catalog from Thunderstore and trim it to UI-relevant
    fields. Raises on network failure or an unexpected response shape so the caller
    can fall back to a stale cache."""
    url = f"https://thunderstore.io/c/{community}/api/v1/package/"
    with urllib.request.urlopen(fetch.request(url), context=fetch.ssl_context(), timeout=30) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, list):
        raise ValueError(f"unexpected catalog shape: {type(data).__name__}")
    trimmed = [t for t in (_trim_package(p) for p in data) if t]
    decky.logger.info(
        f"Thunderstore catalog for {community}: {len(data)} packages fetched, "
        f"{len(trimmed)} trimmed entries"
    )
    return trimmed


def get_community_catalog(community: str, force: bool = False) -> list[dict]:
    """Fetch (or load from disk cache) the Thunderstore catalog for a community,
    trimmed to UI-relevant fields. Returns [] on failure with no stale cache available.
    When force=True, skip the fresh-cache shortcut and pull from the network, but
    still fall back to the existing cache if that fetch fails."""
    return catalog_cache.get_or_fetch(
        _catalog_cache_path(community),
        lambda: _fetch_community_catalog(community),
        force=force,
        label=f"Thunderstore catalog for {community}",
    )


def get_cached_community_catalog(community: str) -> "list[dict] | None":
    """The community catalog from cache only (in-memory, else on-disk at any age); None if not
    cached. Never fetches — for the latency-sensitive game-status path."""
    return catalog_cache.get_cached(_catalog_cache_path(community))


def refresh_community_catalog(community: str) -> bool:
    """Pull a fresh copy of the community catalog from Thunderstore, bypassing the
    cache-freshness check. Used by the Options-menu manual refresh. The existing
    cached catalog is kept if the fresh fetch fails, so a failed refresh never
    leaves the user with an empty catalog. Returns True only if a fresh copy was
    actually fetched (the cache file was rewritten), False if it fell back."""
    return catalog_cache.refreshed(
        _catalog_cache_path(community),
        lambda: _fetch_community_catalog(community),
        label=f"Thunderstore catalog for {community}",
    )


def find_package(community: str, full_name: str) -> dict | None:
    """Look up a single trimmed package by full_name (case-insensitive).
    Used to resolve dependencies and install browsed mods."""
    target = full_name.lower()
    for pkg in get_community_catalog(community):
        if pkg["full_name"].lower() == target:
            return pkg
    return None


_DEP_RE = re.compile(r"^(.+?)-(\d+\.\d+\.\d+(?:[+.\-][^-]+)?)$")


def parse_dep(dep: str) -> tuple[str, str] | None:
    """Parse a Thunderstore dependency string into (full_name, version).
    Dependency strings look like 'RiskofThunder-R2API_Core-5.0.10'. The trailing
    version is always semver-shaped, so we anchor on that to handle owner/package
    names that themselves contain hyphens (e.g. 'FunkFrog-and-Sipondo-ShareSuite')."""
    m = _DEP_RE.match(dep.strip())
    if not m:
        return None
    return m.group(1), m.group(2)
