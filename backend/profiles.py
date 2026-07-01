import os
from datetime import datetime, timezone

import decky
import json_store


def _get_store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _load_full() -> dict:
    return json_store.read(_get_store_path())


def _save_full(full: dict) -> bool:
    return json_store.write(_get_store_path(), full)


def list_profiles(game_id: str) -> list[dict]:
    full = _load_full()
    return list(full.get("profiles", {}).get(game_id, []))


def _find(profiles_for_game: list[dict], name: str) -> int:
    for i, p in enumerate(profiles_for_game):
        if p.get("name") == name:
            return i
    return -1


def save_profile(game_id: str, name: str, mods: list[dict]) -> bool:
    """Create or overwrite a profile. Returns True on success."""
    name = (name or "").strip()
    if not name:
        return False
    full = _load_full()
    profiles_root = full.setdefault("profiles", {})
    game_profiles = profiles_root.setdefault(game_id, [])
    record = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mods": [
            {"id": m["id"], "enabled": bool(m.get("enabled")), "version": m.get("version")}
            for m in mods
        ],
    }
    idx = _find(game_profiles, name)
    if idx >= 0:
        game_profiles[idx] = record
    else:
        game_profiles.append(record)
    return _save_full(full)


def rename_profile(game_id: str, old_name: str, new_name: str) -> bool:
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    full = _load_full()
    game_profiles = full.get("profiles", {}).get(game_id, [])
    if _find(game_profiles, new_name) >= 0 and old_name != new_name:
        return False
    idx = _find(game_profiles, old_name)
    if idx < 0:
        return False
    game_profiles[idx]["name"] = new_name
    return _save_full(full)


def delete_profile(game_id: str, name: str) -> bool:
    full = _load_full()
    game_profiles = full.get("profiles", {}).get(game_id, [])
    idx = _find(game_profiles, name)
    if idx < 0:
        return False
    del game_profiles[idx]
    return _save_full(full)
