"""Balatro Mod Index (BMI) catalog provider.

BMI is a curated GitHub *data* repo (folders of meta.json / description.md /
thumbnail.jpg) — the same index the balatro-mod-manager app uses. We read the
repo directly (one archive download, cached on disk for a day) so the catalog
never depends on anyone's private API server. Each meta.json carries a direct
`downloadURL` (a GitHub archive zip), so installs are plain direct-archive
downloads that flow through mods._install_mod_zip_dir.

Catalog items are emitted in the same shape as the trimmed Thunderstore catalog
(see thunderstore._trim_package) so the Browse UI can render them without
new types, plus a few BMI-only extras (requires_steamodded/talisman, folder_name)
used at install time.
"""

import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile

import decky

import catalog
import catalog_cache
import fetch


def _catalog_cache_path(repo: str) -> str:
    slug = repo.replace("/", "_")
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"bmi-catalog-{slug}.json")


def _archive_url(repo: str, branch: str) -> str:
    return f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"


def _thumbnail_url(repo: str, key: str, branch: str) -> str:
    # raw.githubusercontent.com path; quote the folder key (contains '@', maybe spaces).
    return (
        f"https://raw.githubusercontent.com/{repo}/{branch}/"
        f"mods/{urllib.parse.quote(key)}/thumbnail.jpg"
    )


def _iso_from_unix(ts) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts)))
    except Exception:
        return ""


def _to_item(repo: str, key: str, meta: dict, description: str, has_thumb: bool, branch: str) -> dict:
    """Map one BMI meta.json into the trimmed-Thunderstore catalog shape (+ BMI extras)."""
    title = meta.get("title") or meta.get("folderName") or key
    item = catalog.make_item(
        name=title,
        full_name=key,                          # stable id, e.g. "GhostSalt@Phanta"
        owner=meta.get("author", ""),
        package_url=meta.get("repo", ""),
        donation_link=None,
        date_updated=_iso_from_unix(meta.get("last-updated", 0)),
        rating_score=0,                         # the index has no likes/score; UI shows date instead
        categories=list(meta.get("categories", [])),
        # BMI `version` is often a git commit hash rather than semver — update
        # detection is therefore metadata-comparison (stored vs index value), not
        # semver tracking. See main.check_mod_updates (BMI sources are skipped there).
        version_number=str(meta.get("version", "") or ""),
        description=description,
        icon=_thumbnail_url(repo, key, branch) if has_thumb else "",
        download_url=meta.get("downloadURL", ""),
    )
    # BMI-only extras (ignored by the shared UI shape, consumed at install time):
    item["requires_steamodded"] = bool(meta.get("requires-steamodded", False))
    item["requires_talisman"] = bool(meta.get("requires-talisman", False))
    item["folder_name"] = meta.get("folderName") or key.split("@")[-1] or key
    return item


def _build_catalog_from_zip(repo: str, zip_bytes: bytes, branch: str) -> list[dict]:
    """Parse mods/<key>/meta.json (+ description.md, thumbnail.jpg) out of a repo archive.
    Archive members look like '<reponame>-<branch>/mods/<key>/meta.json'."""
    items: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = set(z.namelist())
        for name in names:
            if not (name.endswith("/meta.json") and "/mods/" in name):
                continue
            try:
                meta = json.loads(z.read(name).decode("utf-8"))
            except Exception as e:
                decky.logger.warning(f"BMI: skipping bad meta.json {name}: {e}")
                continue
            prefix = name[: -len("meta.json")]   # ".../mods/<key>/"
            key = prefix.rstrip("/").split("/")[-1]
            description = ""
            desc_name = prefix + "description.md"
            if desc_name in names:
                try:
                    description = z.read(desc_name).decode("utf-8", errors="replace")
                except Exception:
                    description = ""
            has_thumb = (prefix + "thumbnail.jpg") in names
            items.append(_to_item(repo, key, meta, description, has_thumb, branch))
    return items




def _fetch_bmi_catalog(repo: str, branch: str) -> list[dict]:
    """Download the BMI index archive and parse it into catalog items, ordered by
    recency. Raises on network or parse failure so the caller can fall back to a
    stale cache."""
    req = fetch.request(_archive_url(repo, branch))
    with urllib.request.urlopen(req, context=fetch.ssl_context(), timeout=60) as resp:
        zip_bytes = resp.read()
    items = _build_catalog_from_zip(repo, zip_bytes, branch)

    # The index carries no stars/downloads, and fetching either would mean a private
    # server or per-repo GitHub API calls (60 req/hr unauthenticated). So order by
    # recency instead — a free, deterministic proxy for "actively maintained". Two
    # stable passes: name A→Z, then last-updated newest-first; undated mods sink last.
    # (date_updated is ISO-8601, which sorts chronologically as a string.)
    items.sort(key=lambda it: it["name"].lower())
    items.sort(key=lambda it: it.get("date_updated", ""), reverse=True)
    decky.logger.info(f"BMI index {repo}: {len(items)} mods loaded")
    return items


def get_bmi_catalog(repo: str, branch: str = "main", force: bool = False) -> list[dict]:
    """Fetch (or load from disk cache) the BMI catalog for a repo, in the trimmed-
    Thunderstore item shape. Returns [] on failure with no cache available. When
    force=True, skip the freshness shortcut but still fall back to the existing cache
    if the network fetch fails."""
    return catalog_cache.get_or_fetch(
        _catalog_cache_path(repo),
        lambda: _fetch_bmi_catalog(repo, branch),
        force=force,
        label=f"BMI index {repo}",
    )


def find_bmi_package(repo: str, full_name: str, branch: str = "main") -> dict | None:
    """Look up a single catalog item by full_name (case-insensitive)."""
    target = full_name.lower()
    for pkg in get_bmi_catalog(repo, branch):
        if pkg["full_name"].lower() == target:
            return pkg
    return None


def refresh_bmi_catalog(repo: str, branch: str = "main") -> bool:
    """Force a fresh pull, keeping the existing cache if the fetch fails. Returns True
    only if a fresh copy was actually fetched (the cache file was rewritten)."""
    return catalog_cache.refreshed(
        _catalog_cache_path(repo),
        lambda: _fetch_bmi_catalog(repo, branch),
        label=f"BMI index {repo}",
    )
