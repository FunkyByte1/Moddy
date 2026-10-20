"""Checks whether a newer Moddy build has been published.

Decky only offers updates for plugins installed from its store, so a copy installed from
get.moddy.gg never hears about fixes on its own. This module is how it finds out: the release
workflow publishes a small manifest next to the zip, and the UI compares it with the running
build and tells the user to reinstall.

The manifest is also the one channel that reaches every build already in the wild, so it can
carry a free-form `notice` (e.g. "this build has a data-loss bug, update now"). Keep reading
the fields below tolerant: old builds will be parsing manifests written years later.

Manifest (moddy-latest.json):
    {"version": "2026.10.18+abc1234", "commit": "<full sha>", "published_at": "<iso8601>",
     "download_url": "...zip", "notice": "optional text"}

(Named moddy_update, not update/updater — backend module names must not collide with
decky_loader's own; see the note in app_settings.py.)
"""

import fetch
import app_settings as settings

# The rolling release the install URL points at. Builds published from another channel later
# should point at that channel's manifest instead.
MANIFEST_URL = "https://github.com/FunkyByte1/Moddy/releases/download/nightly/moddy-latest.json"

# Last manifest version the user was toasted about, so each new build is announced once.
_NOTIFIED_KEY = "update_notified_version"


def _build_commit(version: str) -> str:
    """The short SHA the release workflow stamps as semver build metadata ("2026.10.18+abc1234"),
    or "" for a local build (deploy.sh / a hand-built zip), which can't be compared."""
    return version.split("+", 1)[1].strip() if "+" in version else ""


def check(force: bool = False) -> dict:
    """{current, latest, update_available, notify, notice, download_url, dev_build, error}.

    `force` skips the 5-minute fetch cache (the "Check for updates" button), so a release
    published moments ago shows up.

    `notify` is True the first time a given newer version is seen (then remembered), so the UI
    can toast once per release instead of on every load. `notice` is passed through whether or
    not there's an update, so it can also reach users who are already current."""
    current = fetch.VERSION
    commit = _build_commit(current)
    result = {
        "current": current,
        "latest": None,
        "update_available": False,
        "notify": False,
        "notice": None,
        "download_url": None,
        "dev_build": not commit,
        "error": None,
    }
    manifest = fetch.fetch_json(MANIFEST_URL, fresh=force)
    if not isinstance(manifest, dict):
        result["error"] = "Couldn't reach the update server"
        return result

    latest = manifest.get("version")
    latest = latest if isinstance(latest, str) else None
    latest_commit = manifest.get("commit")
    latest_commit = latest_commit if isinstance(latest_commit, str) else _build_commit(latest or "")
    notice = manifest.get("notice")
    download_url = manifest.get("download_url")
    result.update(
        latest=latest,
        notice=(notice.strip() or None) if isinstance(notice, str) else None,
        download_url=download_url if isinstance(download_url, str) else None,
    )

    if commit and latest_commit and not latest_commit.startswith(commit):
        result["update_available"] = True
        if settings.get_setting(_NOTIFIED_KEY) != latest:
            settings.set_setting(_NOTIFIED_KEY, latest)
            result["notify"] = True
    return result
