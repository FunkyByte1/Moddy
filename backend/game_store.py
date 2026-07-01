"""Owner of installed.json's "games" section — the per-game store (schema 2).

Shape: {"games": {"<appid>": {"mods": {...}, "modloaders": {...}, "vanilla": {...},
"profiles": [...]}}}. str(appid) is the canonical game key.

Every per-game sub-store lives under the ONE top-level "games" key, so there must be
exactly one in-memory copy and one write path: mods.py, modloaders.py and profiles.py
all mutate live references obtained here and call save(). A second cache would clobber
its siblings on every read-modify-write of the section. json_store stays the dumb
(atomic, quarantining) I/O layer underneath.

(Named game_store — backend module names must not collide with decky_loader's own;
see the note in app_settings.py.)
"""

import os

import decky
import json_store

_GAMES: dict | None = None


def _path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _load() -> dict:
    global _GAMES
    if _GAMES is None:
        full = json_store.read(_path())
        import store_migration  # lazy: throwaway adopter pulls registry/steam/mods_common
        if store_migration.needs_adoption(full):
            full = store_migration.adopt(_path(), full)
        _GAMES = full.get("games") or {}
    return _GAMES


def game(appid: int) -> dict:
    """The live per-game dict ({"mods": ..., "vanilla": ..., ...}). Mutate, then save()."""
    return _load().setdefault(str(appid), {})


def section(appid: int, key: str) -> dict:
    """The live sub-dict for one game + section (created empty on first access).
    Mutate, then save()."""
    return game(appid).setdefault(key, {})


def appids() -> list[str]:
    """Every appid (as stored, string form) that has any per-game state."""
    return list(_load().keys())


def save() -> bool:
    return json_store.update_section(_path(), "games", _load())


def reset() -> None:
    """Drop the cache so the next access re-reads from disk (tests move the settings dir)."""
    global _GAMES
    _GAMES = None
