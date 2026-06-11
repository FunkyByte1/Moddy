import json
import os
from dataclasses import dataclass, field

import decky


@dataclass
class ModSource:
    type: str          # "github" | "github_source" | "thunderstore" | "url"
    owner: str = ""    # GitHub owner / Thunderstore author
    repo: str = ""     # GitHub repo / Thunderstore package name
    asset: str = ""    # Asset filename to download (for type="github")
    branch: str = "main"  # Branch to download (for type="github_source")
    url: str = ""      # Direct URL (for type="url")
    install_type: str = "file"  # "file" | "zip_dir" | "zip_into_game"


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
    files: list[str] = field(default_factory=list)        # files dropped in game dir (e.g. ["winhttp.dll"])
    dirs: list[str] = field(default_factory=list)         # dirs dropped in game dir (e.g. ["BepInEx"])
    indicator: str = ""                                   # path used to detect install (relative to game dir)
    ready_indicator: str | None = None                    # optional: path that must exist to be "ready" (post-first-launch)
    launch_options: str = ""                              # Steam launch options to apply when enabled


@dataclass
class GameProfile:
    id: str
    name: str
    appid: int
    mods_dir: str
    mods_dir_type: str = "game"          # "game" or "proton_appdata"
    mods_appdata_path: str = ""          # relative path within AppData/Roaming (for proton_appdata type)
    thunderstore_community: str = ""     # Thunderstore community slug (e.g. "riskofrain2"); empty = curated-only
    implicit_deps: list[str] = field(default_factory=list)  # Thunderstore full_names treated as deps of every browsed install
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
        branch=s.get("branch", "main"),
        url=s.get("url", ""),
        install_type=s.get("install_type", "file"),
    )


_REGISTRY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "registry"))


def _require(d: dict, key: str, where: str) -> object:
    if key not in d:
        raise ValueError(f"{where}: missing required field '{key}'")
    return d[key]


def _load_modloaders() -> dict[str, ModloaderInfo]:
    """Load all modloader definitions from registry/modloaders/*.json."""
    catalog: dict[str, ModloaderInfo] = {}
    ml_dir = os.path.join(_REGISTRY_DIR, "modloaders")
    if not os.path.isdir(ml_dir):
        decky.logger.error(f"Modloader registry dir not found: {ml_dir}")
        return catalog

    for fname in sorted(os.listdir(ml_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(ml_dir, fname)
        where = f"registry/modloaders/{fname}"
        try:
            with open(path, "r") as f:
                data = json.load(f)
            ml_id = _require(data, "id", where)
            name = _require(data, "name", where)
            source = _require(data, "source", where)
            if ml_id in catalog:
                raise ValueError(f"{where}: duplicate modloader id '{ml_id}'")
            catalog[ml_id] = ModloaderInfo(
                id=ml_id,
                name=name,
                source=_parse_source(source),
                files=list(data.get("files", [])),
                dirs=list(data.get("dirs", [])),
                indicator=data.get("indicator", ""),
                ready_indicator=data.get("ready_indicator"),
                launch_options=data.get("launch_options", ""),
            )
        except Exception as e:
            decky.logger.error(f"Failed to load modloader from {where}: {e}")
    return catalog


def _load_game(path: str, ml_catalog: dict[str, ModloaderInfo]) -> GameProfile | None:
    fname = os.path.basename(path)
    where = f"registry/games/{fname}"
    try:
        with open(path, "r") as f:
            data = json.load(f)

        game_id = _require(data, "id", where)
        name = _require(data, "name", where)
        appid = _require(data, "appid", where)
        mods_dir = _require(data, "mods_dir", where)
        modloader_ids = data.get("modloader_ids", [])
        if not isinstance(modloader_ids, list) or not modloader_ids:
            raise ValueError(f"{where}: 'modloader_ids' must be a non-empty list")

        resolved_modloaders: list[ModloaderInfo] = []
        for ml_id in modloader_ids:
            ml = ml_catalog.get(ml_id)
            if ml is None:
                known = ", ".join(sorted(ml_catalog.keys())) or "(none loaded)"
                raise ValueError(
                    f"{where}: unknown modloader '{ml_id}' in modloader_ids (known: {known})"
                )
            resolved_modloaders.append(ml)

        mods = []
        for i, m in enumerate(data.get("mods", [])):
            mod_where = f"{where} mods[{i}]"
            mods.append(ModInfo(
                id=_require(m, "id", mod_where),
                name=_require(m, "name", mod_where),
                description=m.get("description", ""),
                filename=_require(m, "filename", mod_where),
                source=_parse_source(_require(m, "source", mod_where)),
                author=m.get("author", ""),
                homepage=m.get("homepage", ""),
                thumbnail=m.get("thumbnail", ""),
                modloader=m.get("modloader", ""),
                dependencies=m.get("dependencies", []),
            ))

        return GameProfile(
            id=game_id,
            name=name,
            appid=appid,
            mods_dir=mods_dir,
            mods_dir_type=data.get("mods_dir_type", "game"),
            mods_appdata_path=data.get("mods_appdata_path", ""),
            thunderstore_community=data.get("thunderstore_community", ""),
            implicit_deps=list(data.get("implicit_deps", [])),
            modloaders=resolved_modloaders,
            mods=mods,
        )
    except Exception as e:
        decky.logger.error(f"Failed to load game from {where}: {e}")
        return None


def _load_registry() -> list[GameProfile]:
    """Load all modloader and game definitions from the registry/ directory tree."""
    decky.logger.info(f"Loading registry from: {_REGISTRY_DIR}")
    ml_catalog = _load_modloaders()
    decky.logger.info(f"Loaded {len(ml_catalog)} modloader(s): {sorted(ml_catalog.keys())}")

    games: list[GameProfile] = []
    seen_ids: set[str] = set()
    seen_appids: set[int] = set()

    games_dir = os.path.join(_REGISTRY_DIR, "games")
    if not os.path.isdir(games_dir):
        decky.logger.error(f"Game registry dir not found: {games_dir}")
        return games

    for fname in sorted(os.listdir(games_dir)):
        if not fname.endswith(".json"):
            continue
        game = _load_game(os.path.join(games_dir, fname), ml_catalog)
        if game is None:
            continue
        if game.id in seen_ids:
            decky.logger.error(f"Duplicate game id '{game.id}' in {fname}; skipping")
            continue
        if game.appid in seen_appids:
            decky.logger.error(f"Duplicate game appid {game.appid} in {fname}; skipping")
            continue
        seen_ids.add(game.id)
        seen_appids.add(game.appid)
        games.append(game)

    decky.logger.info(f"Loaded {len(games)} game(s) from registry/")
    return games


SUPPORTED_GAMES: list[GameProfile] = _load_registry()


def get_game_by_appid(appid: int) -> GameProfile | None:
    return next((g for g in SUPPORTED_GAMES if g.appid == appid), None)
