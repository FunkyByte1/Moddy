import json
import os
from dataclasses import dataclass, field

import decky


@dataclass
class ModSource:
    type: str          # "github" | "url"
    owner: str = ""    # GitHub owner
    repo: str = ""     # GitHub repo
    asset: str = ""    # Asset filename to download
    url: str = ""      # Direct URL (for type="url")


@dataclass
class ModInfo:
    id: str
    name: str
    description: str
    filename: str
    source: ModSource
    author: str = ""
    homepage: str = ""
    thumbnail: str = ""
    modloader: str = ""
    dependencies: list[str] = field(default_factory=list)  # list of mod IDs


@dataclass
class ModloaderInfo:
    id: str
    name: str
    source: ModSource


@dataclass
class GameProfile:
    id: str
    name: str
    appid: int
    mods_dir: str
    modloaders: list[ModloaderInfo] = field(default_factory=list)
    mods: list[ModInfo] = field(default_factory=list)

    def get_modloader(self, modloader_id: str) -> ModloaderInfo | None:
        return next((ml for ml in self.modloaders if ml.id == modloader_id), None)

    def get_mod(self, mod_id: str) -> ModInfo | None:
        return next((m for m in self.mods if m.id == mod_id), None)

    def get_mod_by_filename(self, filename: str) -> ModInfo | None:
        return next((m for m in self.mods if m.filename == filename), None)


def _parse_source(s: dict) -> ModSource:
    return ModSource(
        type=s.get("type", "github"),
        owner=s.get("owner", ""),
        repo=s.get("repo", ""),
        asset=s.get("asset", ""),
        url=s.get("url", ""),
    )


def _load_registry() -> list[GameProfile]:
    """Load game profiles from registry.json next to this file."""
    json_path = os.path.join(os.path.dirname(__file__), "..", "registry.json")
    json_path = os.path.normpath(json_path)
    decky.logger.info(f"Loading registry from: {json_path}")
    try:
        with open(json_path, "r") as f:
            data = json.load(f)

        if data.get("version") != 2:
            decky.logger.error(f"Unsupported registry version: {data.get('version')}")
            return []

        games = []
        for g in data.get("games", []):
            modloaders = [
                ModloaderInfo(
                    id=ml["id"],
                    name=ml["name"],
                    source=_parse_source(ml["source"]),
                )
                for ml in g.get("modloaders", [])
            ]
            mods = [
                ModInfo(
                    id=m["id"],
                    name=m["name"],
                    description=m.get("description", ""),
                    filename=m["filename"],
                    source=_parse_source(m["source"]),
                    author=m.get("author", ""),
                    homepage=m.get("homepage", ""),
                    thumbnail=m.get("thumbnail", ""),
                    modloader=m.get("modloader", ""),
                    dependencies=m.get("dependencies", []),
                )
                for m in g.get("mods", [])
            ]
            games.append(GameProfile(
                id=g["id"],
                name=g["name"],
                appid=g["appid"],
                mods_dir=g["mods_dir"],
                modloaders=modloaders,
                mods=mods,
            ))

        decky.logger.info(f"Loaded {len(games)} game(s) from registry.json")
        return games
    except Exception as e:
        decky.logger.error(f"Failed to load registry.json: {e}")
        return []


SUPPORTED_GAMES: list[GameProfile] = _load_registry()


def get_game_by_appid(appid: int) -> GameProfile | None:
    return next((g for g in SUPPORTED_GAMES if g.appid == appid), None)