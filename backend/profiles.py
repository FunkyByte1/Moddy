from datetime import datetime, timezone

import game_store


def _profiles(appid: int) -> list:
    """One game's live profiles list (see game_store); mutate + game_store.save()."""
    return game_store.game(appid).setdefault("profiles", [])


def list_profiles(appid: int) -> list[dict]:
    return list(_profiles(appid))


def _find(profiles_for_game: list[dict], name: str) -> int:
    for i, p in enumerate(profiles_for_game):
        if p.get("name") == name:
            return i
    return -1


def save_profile(appid: int, name: str, mods: list[dict]) -> bool:
    """Create or overwrite a profile. Returns True on success."""
    name = (name or "").strip()
    if not name:
        return False
    game_profiles = _profiles(appid)
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
    return game_store.save()


def rename_profile(appid: int, old_name: str, new_name: str) -> bool:
    new_name = (new_name or "").strip()
    if not new_name:
        return False
    game_profiles = _profiles(appid)
    if _find(game_profiles, new_name) >= 0 and old_name != new_name:
        return False
    idx = _find(game_profiles, old_name)
    if idx < 0:
        return False
    game_profiles[idx]["name"] = new_name
    return game_store.save()


def delete_profile(appid: int, name: str) -> bool:
    game_profiles = _profiles(appid)
    idx = _find(game_profiles, name)
    if idx < 0:
        return False
    del game_profiles[idx]
    return game_store.save()
