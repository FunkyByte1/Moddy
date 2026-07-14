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

import json
import os

import decky

_SETTINGS = None  # in-memory cache of the whole settings dict


def _path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def _load() -> dict:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS
    path = _path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                _SETTINGS = json.load(f)
                return _SETTINGS
    except Exception as e:
        decky.logger.error(f"Failed to load settings: {e}")
    _SETTINGS = {}
    return _SETTINGS


def get_setting(key: str, default=None):
    return _load().get(key, default)


def _persist(store: dict) -> bool:
    """Atomically write the whole settings dict (temp file + rename) and refresh the cache."""
    global _SETTINGS
    path = _path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(store, f, indent=2)
        os.replace(tmp, path)
        # Owner-only: the file holds the user's Nexus OAuth token. Single-user device, but this
        # keeps the secret out of group/other-readable reach as a basic hardening.
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        _SETTINGS = store
        return True
    except Exception as e:
        decky.logger.error(f"Failed to save settings: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False


def set_setting(key: str, value) -> bool:
    """Persist a single setting atomically. Returns True on success."""
    store = _load()
    store[key] = value
    return _persist(store)


def delete_setting(key: str) -> bool:
    """Remove a key from the store (used to purge the legacy Nexus API key after OAuth).
    Returns True if a key was actually removed."""
    store = _load()
    if key not in store:
        return False
    store.pop(key, None)
    return _persist(store)


# ── Nexus convenience ─────────────────────────────────────────────────────────
# Legacy personal API key. Auth now goes through the OAuth token below (see nexus_oauth.py);
# this constant survives only so the one-time on-load purge can find and delete a stale key.
NEXUS_API_KEY = "nexus_api_key"

# OAuth token bundle: {access_token, refresh_token, expires_at}. Managed by nexus_oauth.
NEXUS_OAUTH = "nexus_oauth"


def nexus_oauth_token() -> dict:
    """The stored OAuth token bundle, or an empty dict if not signed in."""
    return get_setting(NEXUS_OAUTH) or {}
