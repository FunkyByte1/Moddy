import json
import os
from dataclasses import dataclass, field

import decky


@dataclass
class ModSource:
    type: str          # "github" | "github_source" | "thunderstore" | "url" | "steamworkshop" | "nexus" | "setup" | "ficsit" | "external_cli"
    owner: str = ""    # GitHub owner / Thunderstore author
    repo: str = ""     # GitHub repo / Thunderstore package name
    asset: str = ""    # Asset filename to download (for type="github")
    branch: str = "main"  # Branch to download (for type="github_source")
    url: str = ""      # Direct URL (for type="url")
    install_type: str = "file"  # "file" | "zip_dir" | "zip_flat" | "zip_folder" | "zip_smod" | "zip_natives" | "zip_nativepc" | "zip_smapi" | "zip_palworld" | "zip_into_game" | "steamworkshop" | "smapi_installer" | "external_merge"
    workshop_id: str = ""  # Steam Workshop published file id (for type="steamworkshop")
    nexus_domain: str = ""  # Nexus game domain slug, e.g. "slimerancher2" (for type="nexus")
    mod_id: str = ""        # Nexus mod id (for type="nexus"); file_id is resolved at install time
    mod_reference: str = ""  # ficsit.app mod_reference, e.g. "SML"/"RefinedPower" (for type="ficsit"); version id is resolved at install time
    base_dir: str = ""      # game-dir-relative subdir a loader's whole archive installs under (e.g. UE4SS → "Pal/Binaries/Win64"); "" = game root


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
    is_library: bool = False  # a library/framework for other mods — hidden from mod lists by default


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
    mod_toggle: str = "dll"                               # how a folder mod is enabled/disabled: "dll" (rename *.dll) or "lovelyignore" (.lovelyignore marker)
    native: bool = False                                  # provided by the platform (e.g. Steam Workshop) — nothing to install/enable; always "ready"
    nexus_skip_ids: list[str] = field(default_factory=list)  # Nexus mod ids (on the game's domain) that ARE this loader — skipped by collections/cascades even when the loader is installed from elsewhere (e.g. SMAPI = stardewvalley/2400, but installed from GitHub)
    config_files: dict = field(default_factory=dict)      # post-install config to write, keyed by game-dir-relative path → key-value lines (e.g. REFramework's LooseFileLoader toggle)
    uninstall_files: list[str] = field(default_factory=list)  # extra files removed on uninstall but NOT installed (e.g. REFramework runtime logs)
    uninstall_dirs: list[str] = field(default_factory=list)   # extra dirs removed on uninstall but NOT installed (e.g. REFramework's runtime-generated reframework/ config dir)
    setup: dict = field(default_factory=dict)                 # declarative host-side setup for a source.type=="setup" loader; setup.remove_files = game-dir-relative stock files parked aside to <f>.moddy-orig to ENABLE mods, restored to disable (e.g. NMS GAMEDATA/PCBANKS/DISABLEMODS.TXT)
    merge_tool: "MergeToolInfo | None" = None                 # config for a source.type=="external_cli" merge-tool loader (e.g. Fields of Mistria's MOMI); None otherwise


@dataclass
class MergeToolInfo:
    """Config for an external CLI that MERGES all active mods into a shared game file (rebuild-on-
    change), rather than placing per-mod files. Carried by a source.type=="external_cli" modloader
    and consumed by mods_mergetool. Declarative so a second tool (e.g. Hades' ModImporter) is mostly
    JSON: only the zip-vs-bare-binary unpack differs in code."""
    tool_id: str                                              # "momi" | "modimporter" — escape-hatch key, rarely branched on
    owner: str                                                # GitHub owner, e.g. "Garethp"
    repo: str                                                 # GitHub repo, e.g. "Mods-of-Mistria-Installer"
    asset: str                                                # release asset name (Linux), e.g. "ModsOfMistriaInstaller-cli-linux"
    asset_is_zip: bool = False                                # False = bare binary; True = zip → extract + find binary_in_zip
    binary_in_zip: str = ""                                   # binary path/glob inside the zip when asset_is_zip
    apply_argv: list[str] = field(default_factory=list)       # argv for "apply" (default run); [] = bare run
    restore_argv: list[str] = field(default_factory=lambda: ["--uninstall"])  # argv for "restore to pristine"
    env: dict = field(default_factory=dict)                   # extra env for the CLI, e.g. {"EXIT_ON_COMPLETE": "true"}
    tool_owns_backup: bool = True                             # tool keeps its own pristine copy (MOMI's data.bak.win); Moddy never supplies a clean file
    backup_glob: list[str] = field(default_factory=list)      # tool backup files (game-dir-relative) cleared before reapply after a game update (e.g. ["data.bak.win", "*.bak.json"])
    high_risk_glob: str = ""                                  # in-mod glob flagging a fragile native mod (e.g. "aurie/*.dll")
    high_risk_policy: str = "warn"                            # "deny" | "warn" | "allow" for high_risk_glob hits


@dataclass
class GameProfile:
    id: str
    name: str
    appid: int
    mods_dir: str
    mods_dir_type: str = "game"          # "game" or "proton_appdata"
    mods_appdata_path: str = ""          # relative path within AppData/Roaming (for proton_appdata type)
    thunderstore_community: str = ""     # Thunderstore community slug (e.g. "riskofrain2"); empty = no Thunderstore catalog
    implicit_deps: list[str] = field(default_factory=list)  # Thunderstore full_names treated as deps of every browsed install
    catalog: dict = field(default_factory=dict)          # Browse catalog source, e.g. {"type": "bmi", "repo": "...", "branch": "main"}
    library_workshop_ids: list[str] = field(default_factory=list)  # Workshop file ids treated as libraries (Haste tags are unreliable)
    frameworks: dict = field(default_factory=dict)       # framework-mod defs keyed by requirement flag (e.g. "steamodded")
    requires_proton: bool = False        # True for games with a native Linux build whose mods are Windows-built (BepInEx winhttp.dll): they only load when the game is forced to run under Proton
    modloaders: list[ModloaderInfo] = field(default_factory=list)

    def get_modloader(self, modloader_id: str) -> ModloaderInfo | None:
        return next((ml for ml in self.modloaders if ml.id == modloader_id), None)

    def uses_steam_workshop(self) -> bool:
        """True if this game's mods are delivered via Steam Workshop subscriptions rather than
        files Moddy downloads into a mods folder. Discriminated by the modloader's source type
        ("steamworkshop"), NOT by `native`: other non-downloadable loaders (e.g. a source.type
        "setup" loader that only parks a game file aside, like NMS) are native-ish but are still
        file-on-disk mod games and must take the normal filesystem scan, not the Workshop path."""
        return any(ml.source.type == "steamworkshop" for ml in self.modloaders)

    def mod_toggle_style(self) -> str:
        """How folder mods are enabled/disabled for this game, derived from its modloaders.
        "lovelyignore" for Lovely/Steamodded games (Lua mods, no DLLs); "dll" otherwise."""
        for ml in self.modloaders:
            if ml.mod_toggle == "lovelyignore":
                return "lovelyignore"
        return "dll"

    def bundled_frameworks(self) -> list[tuple[str, dict]]:
        """Frameworks flagged `bundled` — installed/removed alongside the modloader and
        hidden from the Mods list (they're infrastructure, like the loader itself).
        Returns (key, framework-def) pairs, e.g. ("steamodded", {...})."""
        return [(k, fw) for k, fw in self.frameworks.items() if fw.get("bundled")]

    def bundled_framework_ids(self) -> set[str]:
        """Mod ids of the bundled frameworks (e.g. {"balatro.steamodded"})."""
        return {fw.get("id", k) for k, fw in self.bundled_frameworks()}


def _parse_source(s: dict) -> ModSource:
    return ModSource(
        type=s.get("type", "github"),
        owner=s.get("owner", ""),
        repo=s.get("repo", ""),
        asset=s.get("asset", ""),
        branch=s.get("branch", "main"),
        url=s.get("url", ""),
        install_type=s.get("install_type", "file"),
        workshop_id=str(s.get("workshop_id", "")),
        nexus_domain=s.get("nexus_domain", ""),
        mod_id=str(s.get("mod_id", "")),
        mod_reference=s.get("mod_reference", ""),
        base_dir=s.get("base_dir", ""),
    )


def _parse_merge_tool(d: "dict | None") -> "MergeToolInfo | None":
    if not d:
        return None
    return MergeToolInfo(
        tool_id=d.get("tool_id", ""),
        owner=d.get("owner", ""),
        repo=d.get("repo", ""),
        asset=d.get("asset", ""),
        asset_is_zip=bool(d.get("asset_is_zip", False)),
        binary_in_zip=d.get("binary_in_zip", ""),
        apply_argv=[str(x) for x in d.get("apply_argv", [])],
        restore_argv=[str(x) for x in d.get("restore_argv", ["--uninstall"])],
        env={str(k): str(v) for k, v in dict(d.get("env", {})).items()},
        tool_owns_backup=bool(d.get("tool_owns_backup", True)),
        backup_glob=[str(x) for x in d.get("backup_glob", [])],
        high_risk_glob=d.get("high_risk_glob", ""),
        high_risk_policy=d.get("high_risk_policy", "warn"),
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
                mod_toggle=data.get("mod_toggle", "dll"),
                native=bool(data.get("native", False)),
                nexus_skip_ids=[str(x) for x in data.get("nexus_skip_ids", [])],
                config_files=dict(data.get("config_files", {})),
                uninstall_files=list(data.get("uninstall_files", [])),
                uninstall_dirs=list(data.get("uninstall_dirs", [])),
                setup=dict(data.get("setup", {})),
                merge_tool=_parse_merge_tool(data.get("merge_tool")),
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

        return GameProfile(
            id=game_id,
            name=name,
            appid=appid,
            mods_dir=mods_dir,
            mods_dir_type=data.get("mods_dir_type", "game"),
            mods_appdata_path=data.get("mods_appdata_path", ""),
            thunderstore_community=data.get("thunderstore_community", ""),
            implicit_deps=list(data.get("implicit_deps", [])),
            catalog=dict(data.get("catalog", {})),
            library_workshop_ids=[str(x) for x in data.get("library_workshop_ids", [])],
            frameworks=dict(data.get("frameworks", {})),
            requires_proton=bool(data.get("requires_proton", False)),
            modloaders=resolved_modloaders,
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


# Catalog categories that mark a mod as a library/framework for other mods rather
# than something a user installs directly. Keyed by Browse catalog type; a game can
# override via `catalog.library_categories` in its registry JSON.
_DEFAULT_LIBRARY_CATEGORIES = {
    "bmi": ["API"],
    "thunderstore": ["Libraries"],
}


def library_categories(game: GameProfile) -> list[str]:
    """The catalog categories that count as "library" for this game. Read from
    `catalog.library_categories` if set, else defaulted by catalog type. Empty list
    means the game has no library concept (e.g. Steam Workshop, with no catalog)."""
    explicit = game.catalog.get("library_categories")
    if explicit is not None:
        return list(explicit)
    catalog_type = game.catalog.get("type") or ("thunderstore" if game.thunderstore_community else "")
    return list(_DEFAULT_LIBRARY_CATEGORIES.get(catalog_type, []))


def nexus_library_ids(game: GameProfile) -> set[str]:
    """Full install ids (`nexus.<domain>.<mod_id>`, lowercased) that the game marks as
    libraries via `catalog.library_ids`. Nexus has no library categorization, so these are
    listed by hand per game (e.g. RE4's REFramework Direct2D / Lua API — framework deps other
    mods need, not content). Empty unless the catalog is Nexus with a domain."""
    if game.catalog.get("type") != "nexus":
        return set()
    domain = game.catalog.get("nexus_domain", "")
    if not domain:
        return set()
    return {f"nexus.{domain}.{mid}".lower() for mid in game.catalog.get("library_ids", [])}
