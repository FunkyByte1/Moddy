import json
import os
from dataclasses import dataclass, field

import decky


@dataclass
class ModInfo:
    name: str
    description: str
    url: str
    filename: str
    author: str = ""
    homepage: str = ""
    thumbnail: str = ""
    dependencies: list[str] = field(default_factory=list)  # list of filenames


@dataclass
class GameProfile:
    name: str
    appid: int
    modloader: str
    mods_dir: str
    recommended_mods: list[ModInfo] = field(default_factory=list)


def _load_games() -> list[GameProfile]:
    """Load game profiles from games.json next to this file."""
    json_path = os.path.join(os.path.dirname(__file__), "..", "games.json")
    json_path = os.path.normpath(json_path)
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
        games = []
        for g in data.get("games", []):
            mods = [
                ModInfo(
                    name=m["name"],
                    description=m.get("description", ""),
                    url=m["url"],
                    filename=m["filename"],
                    author=m.get("author", ""),
                    homepage=m.get("homepage", ""),
                    thumbnail=m.get("thumbnail", ""),
                    dependencies=m.get("dependencies", []),
                )
                for m in g.get("recommended_mods", [])
            ]
            games.append(GameProfile(
                name=g["name"],
                appid=g["appid"],
                modloader=g["modloader"],
                mods_dir=g["mods_dir"],
                recommended_mods=mods,
            ))
        decky.logger.info(f"Loaded {len(games)} game(s) from games.json")
        return games
    except Exception as e:
        decky.logger.error(f"Failed to load games.json: {e}")
        return []


SUPPORTED_GAMES: list[GameProfile] = _load_games()


def get_game_by_appid(appid: int) -> GameProfile | None:
    for game in SUPPORTED_GAMES:
        if game.appid == appid:
            return game
    return None