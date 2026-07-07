import asyncio
import decky
import registry
import steam
import modloaders
import mods
import mods_mergetool
import bmi
import thunderstore


def _catalog_for_game(game: "registry.GameProfile") -> list[dict]:
    """The Browse catalog backing a game (BMI or Thunderstore), or [] if none / on error.
    Served from the same on-disk cache the Browse tab uses, so this is cheap to reuse."""
    try:
        if game.catalog.get("type") == "bmi" and game.catalog.get("repo"):
            return bmi.get_bmi_catalog(game.catalog["repo"], game.catalog.get("branch", "main"))
        if game.thunderstore_community:
            return thunderstore.get_community_catalog(game.thunderstore_community)
    except Exception as e:
        decky.logger.warning(f"Could not load catalog for {game.id}: {e}")
    return []


def _cached_catalog_for_game(game: "registry.GameProfile") -> "list[dict] | None":
    """The game's Browse catalog from cache ONLY — never fetches. None when not yet cached, so
    the status path can skip library classification and warm the catalog in the background instead
    of blocking on a multi-second network fetch (the cause of the ModPage blank-page wait)."""
    try:
        if game.catalog.get("type") == "bmi" and game.catalog.get("repo"):
            return bmi.get_cached_bmi_catalog(game.catalog["repo"], game.catalog.get("branch", "main"))
        if game.thunderstore_community:
            return thunderstore.get_cached_community_catalog(game.thunderstore_community)
    except Exception as e:
        decky.logger.warning(f"Could not load cached catalog for {game.id}: {e}")
    return None


def _library_full_names(packages: "list[dict]", lib_cats: list[str]) -> set[str]:
    """Lowercased catalog full_names whose categories mark them as libraries."""
    if not lib_cats:
        return set()
    lib_set = {c.lower() for c in lib_cats}
    names: set[str] = set()
    for p in packages:
        if any(c.lower() in lib_set for c in p.get("categories", [])):
            names.add(p.get("full_name", "").lower())
    names.discard("")
    return names


# Catalogs currently being warmed in the background (keyed by community / repo), so repeated
# status calls for the same game don't stack duplicate fetches.
_warming_catalogs: "set[str]" = set()


def _schedule_catalog_warm(game: "registry.GameProfile") -> None:
    """Fetch a game's Browse catalog in the background (off the event loop), then emit
    `game_status_stale` so the UI re-pulls and library mods get classified. Used by the
    status path when the catalog isn't cached yet, to keep that path instant. Deduped per
    catalog. No-op if there's no running loop (shouldn't happen — callers are async handlers)."""
    key = game.thunderstore_community or game.catalog.get("repo") or game.id
    if key in _warming_catalogs:
        return
    _warming_catalogs.add(key)

    async def _run() -> None:
        try:
            await asyncio.to_thread(_catalog_for_game, game)
        except Exception as e:  # noqa: BLE001 — a failed warm just leaves mods unclassified
            decky.logger.warning(f"Background catalog warm failed for {game.id}: {e}")
        finally:
            _warming_catalogs.discard(key)
        try:
            await decky.emit("game_status_stale", game.appid)
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        _warming_catalogs.discard(key)


def _build_game_status(game: "registry.GameProfile", libraries: "list[str] | None" = None,
                       *, blocking_catalog: bool = True) -> dict:
    """Build the install/mod-status dict for one supported game. Pass `libraries` (a
    pre-parsed Steam library list) when building many games at once so libraryfolders.vdf
    is read once for the whole batch rather than once per game.

    With `blocking_catalog=False` the library classification reads the Browse catalog from
    cache only (never fetching), so the call can't block on the network — installed mods come
    back unclassified if the catalog isn't cached yet. The latency-sensitive single-game status
    path uses this and warms the catalog out-of-band; the full-list path keeps the fetch."""
    install_dir = steam.find_game_install_dir(game.appid, libraries)

    # Use the first modloader defined for the game
    ml = game.modloaders[0] if game.modloaders else None
    ml_id = ml.id if ml else None

    modloader_installed = bool(
        install_dir and ml_id and
        modloaders.is_modloader_installed(game, install_dir, ml_id)
    )
    modloader_enabled = bool(
        install_dir and ml_id and
        modloaders.is_modloader_enabled(game, install_dir, ml_id)
    )
    modloader_ready = bool(
        install_dir and ml_id and
        modloaders.is_modloader_ready(game, install_dir, ml_id)
    )
    installed_mods_list = mods.get_installed_mods(game, install_dir) if install_dir else []

    # Flag library mods so the UI can hide them from the mod lists by default.
    # A mod is a library if its catalog entry carries a library category
    # ("Libraries" on Thunderstore, "API" on BMI) or it's a declared framework
    # (Steamodded, Talisman) — both are infrastructure for other mods, not things
    # users browse for directly. The catalog lookup is skipped when there are no
    # installed mods to classify, so it never runs for unmodded games.
    lib_cats = registry.library_categories(game)
    framework_ids = {fw.get("id", k).lower() for k, fw in game.frameworks.items()}
    if installed_mods_list and lib_cats:
        packages = _catalog_for_game(game) if blocking_catalog else _cached_catalog_for_game(game)
    else:
        packages = []
    lib_names = _library_full_names(packages or [], lib_cats)
    # Nexus has no library categories, so library Nexus mods are listed per game (catalog.library_ids).
    nexus_lib_ids = registry.nexus_library_ids(game)
    workshop = game.uses_steam_workshop()
    for im in installed_mods_list:
        # Workshop mods carry is_library on their record (from the game's
        # library_workshop_ids); don't clobber it with catalog logic.
        if workshop:
            continue
        idl = im["id"].lower()
        im["is_library"] = idl in lib_names or idl in framework_ids or idl in nexus_lib_ids

    return {
        "id": game.id,
        "name": game.name,
        "appid": game.appid,
        "modloader": ml_id or "",
        "modloader_name": ml.name if ml else "",
        "modloader_launch_options": ml.launch_options if ml else "",
        "modloader_needs_first_launch": bool(ml and ml.ready_indicator),
        # Frameworks bundled with the loader (e.g. Steamodded) — shown on the Mod Loader tab.
        "modloader_bundled": [fw.get("name", k) for k, fw in game.bundled_frameworks()],
        "thunderstore_community": game.thunderstore_community,
        # Which Browse catalog backs this game: "bmi", "thunderstore", "nexus", or "" (Steam Workshop).
        "catalog_type": game.catalog.get("type") or ("thunderstore" if game.thunderstore_community else ""),
        # Catalog categories the UI treats as "library" (hidden by default).
        "library_categories": lib_cats,
        "installed": install_dir is not None,
        "install_dir": install_dir or "",
        "modloader_installed": modloader_installed,
        "modloader_enabled": modloader_enabled,
        "modloader_ready": modloader_ready,
        # Games with a native Linux build whose Windows-built mods only load under Proton. When
        # set, the UI shows a "force Proton" prompt unless a compat tool is already configured.
        # current_compat_tool is only read (config.vdf) for these games, never for the whole list.
        "requires_proton": game.requires_proton,
        "current_compat_tool": steam.get_compat_tool(game.appid) if game.requires_proton else "",
        "installed_mods": installed_mods_list,
        # In "vanilla" (play-unmodded) mode every mod + the modloader are toggled off but kept on
        # disk; the UI shows a banner and offers a one-tap switch back.
        "vanilla": mods.is_game_vanilla(game.appid),
        # External-merge games (Fields of Mistria/MOMI): true when the game was updated since mods
        # were last baked into the shared file, so Steam wiped them — the UI offers "reapply mods".
        "merge_tool_stale": bool(
            install_dir and installed_mods_list
            and mods_mergetool.merge_loader(game) and mods_mergetool.is_stale(game.appid)
        ),
        # External-merge games: mods were staged (installed/deleted/toggled) but the shared game file
        # hasn't been rebuilt yet — the UI shows an "Apply mods" prompt (deployment model), and the
        # changes won't appear in-game until applied. Suppressed in vanilla mode (pristine is the goal
        # there, so there's nothing to apply until the user leaves vanilla).
        "merge_tool_pending": bool(
            install_dir and mods_mergetool.merge_loader(game)
            and mods_mergetool.is_apply_pending(game.appid) and not mods.is_game_vanilla(game.appid)
        ),
    }
