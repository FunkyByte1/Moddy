import json
import ssl
import os
import time
import urllib.request
import decky

_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
_USER_AGENT = "Moddy/0.1.0 (+https://github.com/FunkyByte1/Moddy)"
_CACHE_TTL_SECONDS = 300  # 5 min — covers double-clicks and rapid "Check for Updates" without hiding fresh releases for long
_cache: dict[str, tuple[float, dict | list]] = {}


def _fetch_json(url: str) -> dict | list | None:
    now = time.time()
    cached = _cache.get(url)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            data = json.loads(response.read().decode())
            _cache[url] = (now, data)
            return data
    except Exception as e:
        decky.logger.error(f"Failed to fetch {url}: {e}")
        return None


def get_latest_release(owner: str, repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    data = _fetch_json(url)
    if not data or "tag_name" not in data:
        return None
    return {
        "version": data["tag_name"],
        "name": data.get("name", data["tag_name"]),
        "published_at": data.get("published_at", ""),
    }


def get_all_releases(owner: str, repo: str, per_page: int = 10) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    data = _fetch_json(url)
    if not data or not isinstance(data, list):
        return []
    releases = []
    for release in data:
        if release.get("draft") or release.get("prerelease"):
            continue
        assets = release.get("assets", [])
        releases.append({
            "version": release["tag_name"],
            "name": release.get("name", release["tag_name"]),
            "published_at": release.get("published_at", ""),
            "download_urls": {a["name"]: a["browser_download_url"] for a in assets},
        })
    return releases


def get_download_url_for_version(owner: str, repo: str, version: str, asset: str) -> str | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{version}"
    data = _fetch_json(url)
    if not data:
        return None
    for a in data.get("assets", []):
        if a["name"] == asset:
            return a["browser_download_url"]
    return None


def get_latest_download_url(owner: str, repo: str, asset: str) -> tuple[str, str] | None:
    """Returns (version, download_url) for the latest release containing the given asset."""
    latest = get_latest_release(owner, repo)
    if not latest:
        return None
    url = get_download_url_for_version(owner, repo, latest["version"], asset)
    if not url:
        return None
    return latest["version"], url


# ── Thunderstore API ──────────────────────────────────────────────────────────
# Uses Thunderstore's "experimental" package API (the v1 per-package endpoint
# returns 404 as of 2025). This endpoint exposes only the latest version per
# package — full version history is not available without authentication.

def _get_thunderstore_package(author: str, name: str) -> dict | None:
    url = f"https://thunderstore.io/api/experimental/package/{author}/{name}/"
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return None
    return data


def get_thunderstore_latest(author: str, name: str) -> dict | None:
    """Get latest version info for a Thunderstore package."""
    pkg = _get_thunderstore_package(author, name)
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


def get_thunderstore_all_versions(author: str, name: str) -> list[dict]:
    """Return the available versions for a Thunderstore package.
    The experimental API only exposes the latest version, so this returns at most one entry.
    """
    latest = get_thunderstore_latest(author, name)
    if not latest:
        return []
    return [{
        "version": latest["version"],
        "name": latest["name"],
        "download_url": latest["download_url"],
        "published_at": "",
        "download_urls": {f"{author}-{name}-{latest['version']}.zip": latest["download_url"]},
    }]


def get_thunderstore_download_url(author: str, name: str, version: str) -> str:
    """Get direct download URL for a specific Thunderstore package version."""
    return f"https://thunderstore.io/package/download/{author}/{name}/{version}/"