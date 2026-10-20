"""Plugin-wide settings store.

NOTE: this file is app_settings.py, NOT settings.py, on purpose. A bare module named
`settings` collides with decky_loader's own `settings` module, which sits ahead of the
plugin's backend/ dir on the import path — so `import settings` silently resolves to the
wrong module and attribute access fails at call time. Keep backend module names from
colliding with decky_loader's (settings, loader, main, helpers, plugin, browser, …).

A tiny key/value JSON store in DECKY_PLUGIN_SETTINGS_DIR, separate from installed.json
(which is per-mod install state). Holds account-global config that isn't tied to one game
— e.g. the Nexus Mods OAuth token bundle and the NSFW gate.

Credentials are stored in plaintext: Decky has no OS keyring binding and the file lives on
the user's own device under the plugin's private settings dir (chmod 0o600), so this matches
how Decky plugins persist credentials generally.
"""

import os

import decky
import json_store

_SETTINGS = None  # in-memory cache of the whole settings dict
_MTIME = None     # mtime the cache was built from, so we notice external edits to the file


def _path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def _file_mtime(path: str):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _load() -> dict:
    """Return the settings dict, re-reading the file whenever its mtime has changed since
    the cache was built. Settings can be edited on disk out-of-band (Desktop Mode / SSH), so a
    cache that never reloaded would keep serving stale values — NSFW off, a stale token — until
    the next plugin restart. Keying the cache on mtime picks external edits up on the next read.
    The file itself goes through json_store, so a corrupt one is quarantined rather than
    silently overwritten by the next save."""
    global _SETTINGS, _MTIME
    path = _path()
    mtime = _file_mtime(path)
    if _SETTINGS is not None and mtime == _MTIME:
        return _SETTINGS
    _SETTINGS = json_store.read(path)
    _MTIME = mtime
    return _SETTINGS


def get_setting(key: str, default=None):
    return _load().get(key, default)


def _persist(store: dict) -> bool:
    """Atomically write the whole settings dict and refresh the cache. Owner-only (0o600):
    the file holds the user's Nexus OAuth token. Single-user device, but this keeps the
    secret out of group/other-readable reach as a basic hardening."""
    global _SETTINGS, _MTIME
    path = _path()
    if not json_store.write(path, store, mode=0o600):
        return False
    _SETTINGS = store
    _MTIME = _file_mtime(path)  # our own write; don't mistake it for an external edit
    return True


def set_setting(key: str, value) -> bool:
    """Persist a single setting atomically. Returns True on success."""
    store = _load()
    store[key] = value
    return _persist(store)


def delete_setting(key: str) -> bool:
    """Remove a key from the store. Returns True if a key was actually removed."""
    store = _load()
    if key not in store:
        return False
    store.pop(key, None)
    return _persist(store)


# ── Nexus convenience ─────────────────────────────────────────────────────────
# OAuth token bundle: {access_token, refresh_token, expires_at}. Managed by nexus_oauth.
NEXUS_OAUTH = "nexus_oauth"


def nexus_oauth_token() -> dict:
    """The stored OAuth token bundle, or an empty dict if not signed in."""
    return get_setting(NEXUS_OAUTH) or {}
