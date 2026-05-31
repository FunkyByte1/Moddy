import json
import ssl
import re
import urllib.request
import decky

_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def _make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    return ctx


import os


def _fetch_json(url: str) -> dict | list | None:
    """Fetch JSON from a URL using the system CA bundle."""
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


def parse_github_repo(url: str) -> tuple[str, str] | None:
    """
    Extract owner and repo name from a GitHub releases URL.
    e.g. https://github.com/ThatFinnDev/Starlight/releases/... -> ("ThatFinnDev", "Starlight")
    """
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)/releases', url)
    if match:
        return match.group(1), match.group(2)
    return None


def get_latest_release(owner: str, repo: str) -> dict | None:
    """Get the latest release info from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    data = _fetch_json(url)
    if not data or "tag_name" not in data:
        return None
    return {
        "version": data["tag_name"],
        "name": data.get("name", data["tag_name"]),
        "published_at": data.get("published_at", ""),
        "body": data.get("body", ""),
    }


def get_all_releases(owner: str, repo: str, per_page: int = 10) -> list[dict]:
    """Get a list of releases from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    data = _fetch_json(url)
    if not data or not isinstance(data, list):
        return []
    releases = []
    for release in data:
        if release.get("draft") or release.get("prerelease"):
            continue
        # Find the DLL asset download URL
        assets = release.get("assets", [])
        dll_assets = [a for a in assets if a["name"].endswith(".dll")]
        releases.append({
            "version": release["tag_name"],
            "name": release.get("name", release["tag_name"]),
            "published_at": release.get("published_at", ""),
            "download_urls": {a["name"]: a["browser_download_url"] for a in dll_assets},
        })
    return releases


def get_download_url_for_version(owner: str, repo: str, version: str, filename: str) -> str | None:
    """Get the download URL for a specific version and filename."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{version}"
    data = _fetch_json(url)
    if not data:
        return None
    assets = data.get("assets", [])
    for asset in assets:
        if asset["name"] == filename:
            return asset["browser_download_url"]
    return None