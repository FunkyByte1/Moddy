import json
import ssl
import os
import urllib.request
import decky

_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def _fetch_json(url: str) -> dict | list | None:
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    req = urllib.request.Request(url, headers={"User-Agent": "DeckyModManager/1.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
            return json.loads(response.read().decode())
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

def get_thunderstore_latest(author: str, name: str) -> dict | None:
    """Get latest version info for a Thunderstore package."""
    url = f"https://thunderstore.io/api/v1/package/{author}/{name}/"
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return None
    versions = data.get("versions", [])
    if not versions:
        return None
    latest = versions[0]  # Thunderstore returns newest first
    return {
        "version": latest["version_number"],
        "name": latest["full_name"],
        "download_url": latest["download_url"],
    }


def get_thunderstore_all_versions(author: str, name: str) -> list[dict]:
    """Get all versions for a Thunderstore package."""
    url = f"https://thunderstore.io/api/v1/package/{author}/{name}/"
    data = _fetch_json(url)
    if not data or not isinstance(data, dict):
        return []
    versions = data.get("versions", [])
    return [
        {
            "version": v["version_number"],
            "name": v["full_name"],
            "download_url": v["download_url"],
            "published_at": v.get("date_created", ""),
            "download_urls": {f"{author}-{name}-{v['version_number']}.zip": v["download_url"]},
        }
        for v in versions
    ]


def get_thunderstore_download_url(author: str, name: str, version: str) -> str:
    """Get direct download URL for a specific Thunderstore package version."""
    return f"https://thunderstore.io/package/download/{author}/{name}/{version}/"