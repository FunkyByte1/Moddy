import fetch


def get_latest_release(owner: str, repo: str) -> dict | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    data = fetch.fetch_json(url)
    if not data or "tag_name" not in data:
        return None
    return {
        "version": data["tag_name"],
        "name": data.get("name", data["tag_name"]),
        "published_at": data.get("published_at", ""),
    }


def get_all_releases(owner: str, repo: str, per_page: int = 10) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    data = fetch.fetch_json(url)
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
    data = fetch.fetch_json(url)
    if not data:
        return None
    for a in data.get("assets", []):
        if a["name"] == asset:
            return a["browser_download_url"]
    return None


def get_source_url(owner: str, repo: str, branch: str = "main") -> str:
    """Direct download URL for a GitHub repo's branch archive (source zip).
    Used for mods/frameworks distributed as repo source rather than release assets."""
    return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"


def get_latest_download_url(owner: str, repo: str, asset: str) -> tuple[str, str] | None:
    """Returns (version, download_url) for the latest release containing the given asset."""
    latest = get_latest_release(owner, repo)
    if not latest:
        return None
    url = get_download_url_for_version(owner, repo, latest["version"], asset)
    if not url:
        return None
    return latest["version"], url


def get_latest_release_assets(owner: str, repo: str) -> tuple[str, dict[str, str]] | None:
    """Returns (version, {asset_name: download_url}) for the latest release. Use this when the
    asset name embeds the version (e.g. SMAPI's `SMAPI-<ver>-installer.zip`), so the caller can
    select by pattern rather than an exact name."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    data = fetch.fetch_json(url)
    if not data or "tag_name" not in data:
        return None
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return data["tag_name"], assets
