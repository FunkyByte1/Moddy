import asyncio
import sys
import os
import decky

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

import registry
import steam
import modloaders
import mods
import profiles
import github
import thunderstore
import bmi
import nexus
import ficsit
# Imported as `settings` for readability, but the file is app_settings.py: a bare module
# named `settings` collides with decky_loader's own `settings` module (which wins on the
# import path), so `import settings` would silently resolve to the wrong module.
import app_settings as settings
import utils
import steamworkshop_browse
import download_queue
import install_cascade
import plugin_game_status
import plugin_install_denylists
import plugin_install_common
import plugin_nexus_install
import nexus_collections
import thunderstore_modpacks
import plugin_thunderstore_install
import plugin_ficsit_install
import plugin_frameworks
import plugin_game_lifecycle
import plugin_diagnostics

# Re-export the moved game-status helpers so existing `main._build_game_status(...)` call sites
# (and tests) keep resolving after the verbatim move into plugin_game_status.
def _is_thunderstore_game(appid: int) -> bool:
    """True if this appid's Browse venue is Thunderstore — used to route the venue-agnostic Collections
    RPCs to the Thunderstore-modpacks backend instead of the Nexus-collections one. Thunderstore is the
    default catalog type for a game with a `thunderstore_community` and no explicit `catalog.type` (the
    same derivation as plugin_game_status' catalog_type)."""
    game = registry.get_game_by_appid(appid)
    if not game or not game.thunderstore_community:
        return False
    return (game.catalog.get("type") or "thunderstore") == "thunderstore"


_build_game_status = plugin_game_status._build_game_status
_catalog_for_game = plugin_game_status._catalog_for_game
_cached_catalog_for_game = plugin_game_status._cached_catalog_for_game
_library_full_names = plugin_game_status._library_full_names
_schedule_catalog_warm = plugin_game_status._schedule_catalog_warm


class Plugin:

    async def get_supported_appids(self) -> list[int]:
        """Return the list of Steam appids this plugin supports — used by the frontend to gate the context-menu patch."""
        return [g.appid for g in registry.SUPPORTED_GAMES]

    async def get_supported_games(self) -> list:
        """Return all supported games with current install and mod status."""
        # Parse the Steam library list once for the whole batch instead of per game.
        libraries = steam.find_steam_libraries()
        return [plugin_game_status._build_game_status(game, libraries) for game in registry.SUPPORTED_GAMES]

    async def get_game_status(self, appid: int) -> dict | None:
        """Return install/mod status for a single supported game (or None if unsupported).
        The per-mod-action refresh only needs the game being configured, so this avoids
        recomputing status (install-dir resolution + a full installed-mods scan) for every
        other supported game on every toggle/install. Behaviourally identical to picking
        this appid out of get_supported_games()."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return None
        # Read the catalog from cache only so this never blocks on a network fetch — the ModPage
        # gates its whole render on this call, so a synchronous catalog pull here showed a blank
        # page for seconds (notably RoR2's large Thunderstore catalog). If the catalog isn't cached
        # yet, classification is skipped now and warmed out-of-band; `game_status_stale` then tells
        # the UI to re-pull so library mods get hidden once it lands.
        status = plugin_game_status._build_game_status(game, blocking_catalog=False)
        if (status["installed"] and status["installed_mods"]
                and registry.library_categories(game)
                and plugin_game_status._cached_catalog_for_game(game) is None):
            plugin_game_status._schedule_catalog_warm(game)
        return status

    async def install_modloader(self, appid: int, version: str | None = None) -> "bool | str":
        """Returns True on success, False on failure, or "premium_required" when a Nexus-sourced
        loader can't be downloaded without a Premium key (the UI shows a specific message)."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        ok = await modloaders.install_modloader(game, install_dir, game.modloaders[0].id, version)
        if ok is True:
            # Bundled frameworks (e.g. Steamodded) ship with the loader since nearly every
            # mod needs them. Best-effort: a framework hiccup doesn't fail the loader install.
            for key, _fw in game.bundled_frameworks():
                await plugin_frameworks.ensure_framework(game, install_dir, key)
        return ok

    async def get_modloader_version(self, appid: int) -> str | None:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return None
        return modloaders.get_modloader_version(game.modloaders[0].id)

    async def get_modloader_releases(self, appid: int) -> list:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return []
        ml = game.modloaders[0]
        if ml.source.type == "ficsit":
            # SML is a ficsit mod; offer its recent Windows-buildable versions in the picker. The
            # download is resolved at install time by version, so download_urls is left empty here.
            return [
                {"version": v["version"], "name": v["version"], "published_at": "", "download_urls": {}}
                for v in ficsit.list_versions(ml.source.mod_reference)
                if ficsit.TARGET in v["targets"]
            ]
        if ml.source.type != "github":
            return []
        releases = github.get_all_releases(ml.source.owner, ml.source.repo)
        return [r for r in releases if ml.source.asset in r.get("download_urls", {})]

    async def check_modloader_update(self, appid: int) -> dict | None:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return None
        ml = game.modloaders[0]
        installed = modloaders.get_modloader_version(ml.id)
        if not installed:
            return None
        if ml.source.type == "ficsit":
            # SML is itself a ficsit mod; check its latest version (it commonly needs updating right
            # after a Satisfactory game update, which breaks the old loader).
            latest = ficsit.get_latest(ml.source.mod_reference)
            if not latest or latest["version"] == installed:
                return None
            return {"installed": installed, "latest": latest["version"]}
        if ml.source.type != "github":
            return None
        latest = github.get_latest_release(ml.source.owner, ml.source.repo)
        if not latest or latest["version"] == installed:
            return None
        return {"installed": installed, "latest": latest["version"]}

    async def get_modloader_uninstall_impact(self, appid: int) -> list:
        """Installed mods that uninstalling the loader would delete (its uninstall rmtree's the
        loader's dirs, e.g. BepInEx/, taking the plugins under them). Returns [{id, name}] so the
        UI can warn before removing. Empty for loaders whose mods live elsewhere (MelonLoader's
        Mods/). Bundled frameworks are loader infrastructure, not user mods, so they're excluded."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return []
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return []
        ml = game.modloaders[0]
        fw_ids = set(game.bundled_framework_ids())
        return [m for m in mods.mods_under_modloader(game, install_dir, ml.dirs, ml.files)
                if m["id"] not in fw_ids]

    async def uninstall_modloader(self, appid: int) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        ml = game.modloaders[0]
        # Mods living under the loader's footprint lose their files when it's removed; capture them
        # now (while present) so their now-dead records can be cleared afterward, keeping the store
        # honest. The UI warns the user about this before calling.
        orphaned = mods.mods_under_modloader(game, install_dir, ml.dirs, ml.files)
        # Remove bundled frameworks first — they're part of the loader, not content mods.
        for fw_id in game.bundled_framework_ids():
            if mods.get_installed_record(fw_id) is not None:
                await mods.uninstall_mod(game, install_dir, fw_id)
        ok = await modloaders.uninstall_modloader(game, install_dir, ml.id)
        if ok:
            for m in orphaned:
                mods.clear_installed_record(m["id"])
        return ok

    async def enable_modloader(self, appid: int) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await modloaders.enable_modloader(game, install_dir, game.modloaders[0].id)

    async def disable_modloader(self, appid: int) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await modloaders.disable_modloader(game, install_dir, game.modloaders[0].id)

    async def install_mod(self, appid: int, mod_id: str, version: str | None = None) -> bool | None:
        """Record a Steam Workshop subscription (synthetic id workshop.<appid>.<fileid>);
        the frontend has already subscribed via SteamClient.
        Returns True=success, False=failed, None=cancelled."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        parts = mod_id.split(".")
        if game.uses_steam_workshop() and len(parts) == 3 and parts[0] == "workshop" and parts[2].isdigit():
            return await mods.install_synthetic_workshop(game, mod_id, parts[2])
        decky.logger.error(f"Unknown mod: {mod_id}")
        return False

    async def get_mod_releases(self, appid: int, mod_id: str) -> list:
        """Get available releases for a browsed Thunderstore mod (by full_name)."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        if game.thunderstore_community:
            pkg = thunderstore.find_package(game.thunderstore_community, mod_id)
            if pkg:
                return thunderstore.get_all_versions(pkg["owner"], pkg["name"])
        return []

    async def check_mod_updates(self, appid: int) -> list:
        """Check which installed mods have updates available. Walks installed.json so
        every browsed mod is checked from its persisted source record."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return []
        installed = mods.get_installed_mods(game, install_dir)
        updates = []
        for entry in installed:
            mod_id = entry["id"]
            installed_version = entry.get("version")
            if not installed_version or installed_version == "latest":
                continue
            source = (mods.get_installed_record(mod_id) or {}).get("source") or {}
            source_type, owner, repo = source.get("type", ""), source.get("owner", ""), source.get("repo", "")
            nexus_domain, nexus_mod_id = source.get("nexus_domain", ""), source.get("mod_id", "")
            if source_type == "github":
                if not owner or not repo:
                    continue
                latest = github.get_latest_release(owner, repo)
            elif source_type == "thunderstore":
                if not owner or not repo:
                    continue
                latest = thunderstore.get_latest(owner, repo)
            elif source_type == "nexus":
                if not nexus_domain or not nexus_mod_id:
                    continue
                latest = nexus.get_latest(nexus_domain, nexus_mod_id)
            elif source_type == "ficsit":
                mod_reference = source.get("mod_reference", "")
                if not mod_reference:
                    continue
                latest = ficsit.get_latest(mod_reference)
            else:
                continue
            if latest and latest["version"] != installed_version:
                updates.append({
                    "id": mod_id,
                    "installed_version": installed_version,
                    "latest_version": latest["version"],
                })
        return updates

    async def uninstall_mod(self, appid: int, mod_id: str) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await mods.uninstall_mod(game, install_dir, mod_id)

    async def get_workshop_catalog(self, appid: int, search: str = "", sort: str = "trend", page: int = 1) -> list:
        """A page (~30 items) of the Steam Workshop catalog for a workshop game,
        in browse order. Keyless (scrapes ids + resolves via GetPublishedFileDetails).
        Returns [] for non-workshop games or on error."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.uses_steam_workshop():
            return []
        return steamworkshop_browse.get_workshop_catalog(appid, search, sort, page)

    async def get_workshop_required_items(self, appid: int, fileid: str) -> list:
        """The dependency (required items) declared by a Workshop item, with metadata, so
        the frontend can subscribe them (SteamClient.SubscribeWorkshopItem doesn't cascade)
        and stamp their real names immediately."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.uses_steam_workshop():
            return []
        return steamworkshop_browse.get_required_items_detailed(str(fileid))

    async def set_workshop_meta(self, appid: int, fileid: str, name: str, thumbnail: str, description: str) -> bool:
        """Stamp real metadata onto a just-installed Workshop record so it shows its name
        immediately, rather than the 'Workshop item <id>' placeholder until the next
        reconcile."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.uses_steam_workshop():
            return False
        return mods.set_workshop_meta(game, str(fileid), name, thumbnail, description)

    async def reconcile_workshop_subscriptions(self, appid: int, items: list) -> bool:
        """Sync installed.json with the game's actual Steam Workshop subscriptions
        (the frontend supplies them via GetSubscribedWorkshopItems). Returns True if
        the tracked set changed. The frontend must NOT call this when its query failed
        — an empty list legitimately means "nothing subscribed" and clears records."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.uses_steam_workshop():
            return False
        return mods.reconcile_workshop(game, items or [])

    async def toggle_mod(self, appid: int, mod_id: str, enable: bool) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await mods.toggle_mod(game, install_dir, mod_id, enable)

    async def get_backed_up_versions(self, appid: int, mod_id: str) -> list:
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return []
        return mods.get_backed_up_versions(game, install_dir, mod_id)

    async def delete_mod_version(self, appid: int, mod_id: str, version: str) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return mods.delete_mod_version(game, install_dir, mod_id, version)

    async def get_thunderstore_catalog(self, appid: int) -> list:
        """Return the trimmed Thunderstore catalog for the game's community, or [] if
        the game has no thunderstore_community configured. Cached on disk for 30 min."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return []
        return thunderstore.get_community_catalog(game.thunderstore_community)

    async def refresh_thunderstore_catalog(self, appid: int) -> bool:
        """Force a fresh catalog pull from Thunderstore, keeping the existing cache
        if the fetch fails. Returns True only if a fresh copy was actually fetched."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return False
        return thunderstore.refresh_community_catalog(game.thunderstore_community)

    # ── Balatro Mod Index (BMI) catalog ───────────────────────────────────────
    async def get_bmi_catalog(self, appid: int) -> list:
        """Return the BMI catalog (trimmed-Thunderstore item shape) for a game whose
        Browse source is BMI, or [] otherwise. Cached on disk for 1 day."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "bmi" or not game.catalog.get("repo"):
            return []
        return bmi.get_bmi_catalog(game.catalog["repo"], game.catalog.get("branch", "main"))

    async def refresh_bmi_catalog(self, appid: int) -> bool:
        """Force a fresh BMI catalog pull, keeping the existing cache if the fetch fails.
        Returns True only if a fresh copy was actually fetched."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "bmi" or not game.catalog.get("repo"):
            return False
        return bmi.refresh_bmi_catalog(game.catalog["repo"], game.catalog.get("branch", "main"))

    async def install_bmi_mod(self, appid: int, mod_id: str, version: str | None = None) -> bool | None:
        """Install a BMI mod by its catalog full_name. Installs any required framework
        (Steamodded / Talisman) into the Mods folder first, then the mod itself from its
        direct downloadURL. Returns True=success, False=failed, None=cancelled."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "bmi" or not game.catalog.get("repo"):
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        item = bmi.find_bmi_package(game.catalog["repo"], mod_id, game.catalog.get("branch", "main"))
        if not item:
            decky.logger.error(f"BMI mod not found in catalog: {mod_id}")
            return False

        # Frameworks first (best-effort — a framework failure is logged but doesn't abort
        # the mod install, matching the Thunderstore dependency behaviour).
        if item.get("requires_steamodded"):
            await plugin_frameworks.ensure_framework(game, install_dir, "steamodded")
        if item.get("requires_talisman"):
            await plugin_frameworks.ensure_framework(game, install_dir, "talisman")

        latest = item.get("latest", {})
        url = latest.get("download_url")
        if not url:
            decky.logger.error(f"BMI mod {mod_id} has no downloadURL")
            return False
        target_version = version or latest.get("version_number") or "latest"
        mod = registry.ModInfo(
            id=item["full_name"],
            name=item["name"],
            description=latest.get("description", ""),
            filename=item["folder_name"],
            source=registry.ModSource(type="url", url=url, install_type="zip_dir"),
            author=item.get("owner", ""),
            homepage=item.get("package_url", ""),
            thumbnail=latest.get("icon", ""),
            modloader=game.modloaders[0].id if game.modloaders else "",
            dependencies=[],
        )
        await download_queue.set_sublabel(mod.name)
        return await mods.install_mod(game, install_dir, mod, version=target_version, url=url)

    # ── Nexus Mods catalog ────────────────────────────────────────────────────
    async def get_nexus_catalog(self, appid: int, query: str = "", page: int = 1,
                                include_adult: bool | None = None,
                                sort: str = nexus.DEFAULT_SORT) -> list:
        """A page (~25 items) of the Nexus catalog for a game whose Browse source is Nexus,
        searched server-side by `query` via the v2 GraphQL API. Returns [] for non-Nexus
        games, on error, or when no Nexus API key is configured.

        `include_adult` is driven per-fetch by the Browse filter's "Show NSFW" toggle. When
        the caller omits it, fall back to the `nexus_include_adult` setting key. `sort` picks
        the server-side order from the Browse filter's "Sort By" dropdown."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "nexus":
            return []
        domain = game.catalog.get("nexus_domain", "")
        if not domain:
            return []
        # Adult mods are hidden by default; the Browse filter's NSFW toggle opts in per-fetch.
        if include_adult is None:
            include_adult = bool(settings.get_setting("nexus_include_adult", False))
        results = nexus.search(domain, query, page, bool(include_adult), sort)
        deny = plugin_install_denylists.nexus_browse_denylist()
        lib_ids = registry.nexus_library_ids(game)
        out = []
        for it in results:
            fn = it.get("full_name", "").lower()
            if fn in deny:
                continue
            if fn in lib_ids:
                it["is_library"] = True  # framework dep (e.g. Direct2D) — hidden from Browse by default
            out.append(it)
        return out

    # The Collections tab is venue-agnostic: a game has one Browse venue, so its "collections" are
    # whatever that venue calls them — Nexus collections or Thunderstore modpacks. Both backends expose
    # the same list/has/detail/enqueue surface (CollectionItem / CollectionDetail shapes), so these
    # RPCs just route by the game's catalog type and the one frontend tab serves both (the user-facing
    # "Modpacks" vs "Collections" noun is applied in the UI).
    async def get_collections_catalog(self, appid: int, query: str = "", page: int = 1) -> list:
        """A page of the game's collections/modpacks for the Collections browse tab (slug/name/author/
        summary/mod_count/endorsements/tile_image). Nexus adult collections are gated by NSFW."""
        if _is_thunderstore_game(appid):
            return thunderstore_modpacks.list_modpacks_for_game(appid, query, page)
        return nexus_collections.list_collections_for_game(appid, query, page)

    async def game_has_collections(self, appid: int) -> bool:
        """Whether this game's venue has ANY collections/modpacks — gates the Collections tab so games
        with none (e.g. Slime Rancher 2) don't show an empty tab."""
        if _is_thunderstore_game(appid):
            return thunderstore_modpacks.game_has_modpacks(appid)
        return nexus_collections.game_has_collections(appid)

    async def get_collection_detail(self, appid: int, slug: str) -> dict:
        """A collection/modpack's detail — {name, image, summary, mod_count, mods:[{mod_id,name,
        thumbnail,optional}]} — for the browse-tab detail and the Installed-tab panel."""
        if _is_thunderstore_game(appid):
            return thunderstore_modpacks.get_modpack_detail(appid, slug)
        return nexus_collections.get_collection_detail(appid, slug)

    async def install_nexus_mod(self, appid: int, full_name: str, version: str | None = None,
                                variant: str | None = None, installed: "list | None" = None):
        """Install a Nexus mod by its `nexus.<domain>.<mod_id>` catalog id, via the Premium
        download link, recursively installing any declared same-domain Nexus requirements
        first. Returns True=success, False=failed, None=cancelled, and the string
        "premium_required" when the user's API key isn't Premium (v1 can't serve free
        downloads — those need the website's nxm:// handoff). When the mod's archive bundles
        multiple variants (e.g. RE4 stack-size .pak options) and `variant` isn't given, returns
        {"needs_variant": True, "variants": [...]} so the UI can ask which to install.
        `installed` collects the ids freshly installed this run (the queue passes the job's list so
        a parked-then-cancelled install can be rolled back); a cancel/failure rolls it back here."""
        return await plugin_nexus_install.install_nexus_mod(appid, full_name, version, variant, installed)

    # ── ficsit.app (Satisfactory) catalog ──────────────────────────────────────
    async def get_ficsit_catalog(self, appid: int, query: str = "", page: int = 1,
                                 sort: str = ficsit.DEFAULT_SORT) -> list:
        """A page (~25 items) of the ficsit.app catalog for a game whose Browse source is ficsit
        (Satisfactory), searched server-side by `query` via the anonymous GraphQL API (no API key).
        Returns [] for non-ficsit games or on error. The Satisfactory Mod Loader (SML) is filtered
        out — it's installed via the Mod Loader tab, and every mod declares it as a dependency."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "ficsit":
            return []
        results = ficsit.search(query, page, sort)
        deny = plugin_install_denylists.ficsit_browse_denylist()
        return [it for it in results if it.get("full_name", "").lower() not in deny]

    async def install_ficsit_mod(self, appid: int, full_name: str, version: str | None = None,
                                 installed: "list | None" = None):
        """Install a ficsit mod by its `ficsit.<mod_reference>` catalog id, recursively installing its
        (non-loader, non-optional) ficsit dependencies first via the shared cascade. SML — every mod's
        dependency — is skipped (managed by the modloader system). Returns True=success, False=failed,
        None=cancelled. `installed` collects the ids freshly installed this run (the queue passes the
        job's list so a cancel/failure rolls them back)."""
        return await plugin_ficsit_install.install_ficsit_mod(appid, full_name, version, installed)

    # ── Plugin settings (account-global; e.g. the Nexus API key) ───────────────
    async def get_setting(self, key: str):
        return settings.get_setting(key)

    async def set_setting(self, key: str, value) -> bool:
        return settings.set_setting(key, value)

    # ── Diagnostics ────────────────────────────────────────────────────────────
    async def export_logs(self) -> str | None:
        """Bundle Moddy's logs + a small system-info file into one zip the user can
        attach to a bug report. Writes to the Deck's Desktop (easy to find and drag
        into a browser upload), falling back to the user's home, and returns the full
        path. Deliberately excludes settings.json so the Nexus API key never leaves
        the device."""
        return await plugin_diagnostics.export_logs()

    async def get_browse_denylist(self) -> list[str]:
        """Lowercase install ids the UI should treat as 'not a real dependency' — modloaders,
        mod-manager apps (Thunderstore + Nexus), and every game's implicit deps (modloader cores
        like RiskofThunder-RoR2BepInExPack that the cascade injects into each install, so no mod
        declares them) — so they're hidden from Browse, never flagged as a missing dependency, and
        never offered as an 'unused library'.

        Implicit deps are unioned in only here, NOT into _BROWSE_DENYLIST: that set is what the
        install cascade uses to *skip* installs, and the modloader cores must still get installed."""
        implicit = {dep.lower() for g in registry.SUPPORTED_GAMES for dep in g.implicit_deps}
        return sorted(plugin_install_denylists._BROWSE_DENYLIST | plugin_install_denylists.nexus_browse_denylist()
                      | plugin_install_denylists.ficsit_browse_denylist() | implicit)

    async def get_unresolved_dependencies(self, appid: int, full_name: str, with_deps: bool = True) -> list:
        """Declared dependencies of `full_name` that aren't in the catalog (so they can't be
        installed). Resolves the dependency tree up front; if anything looks missing, refreshes the
        catalog once and re-resolves first — a "missing" dep is most often just a stale cache. The
        UI calls this before installing so it can warn / offer "install anyway". Empty = all good."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return []
        unresolved: list[str] = []
        plugin_thunderstore_install._resolve_thunderstore_plan(
            game, full_name, None, with_deps, set(), [], unresolved, None, plugin_install_denylists._BROWSE_DENYLIST)
        if unresolved:
            # Could be a stale catalog — pull a fresh copy and re-resolve before reporting.
            thunderstore.refresh_community_catalog(game.thunderstore_community)
            unresolved = []
            plugin_thunderstore_install._resolve_thunderstore_plan(
                game, full_name, None, with_deps, set(), [], unresolved, None, plugin_install_denylists._BROWSE_DENYLIST)
        return unresolved

    async def install_thunderstore_mod(
        self, appid: int, full_name: str, version: str | None = None, with_deps: bool = True,
        allow_missing: bool = False,
    ) -> bool | None:
        """Install a Thunderstore mod by full_name (e.g. 'RiskofThunder-R2API_Core'),
        recursively installing any declared dependencies first. Already-installed
        deps and denylisted modloader packages are skipped. Pass with_deps=False to install
        only the named mod and leave its dependencies out (the UI's "skip dependencies").
        allow_missing=True installs the mod even if a declared dependency isn't in the catalog
        (it's skipped instead of failing — the UI's "install anyway").
        Returns True=success, False=failed, None=cancelled."""
        return await plugin_thunderstore_install.install_thunderstore_mod(appid, full_name, version, with_deps, allow_missing)

    async def reset_game(self, appid: int) -> dict:
        """Reset a game to its unmodded state: uninstall every tracked mod, then every
        installed modloader, then remove any orphaned mods directory left behind.
        Returns a summary: {ok, mods_removed, modloader_removed}.
        Order matters — mods are removed before the modloader so their install records
        get cleared while their files still exist (uninstalling the modloader wipes the
        whole BepInEx/ tree, which would orphan those records)."""
        return await plugin_game_lifecycle.reset_game(appid)

    async def is_game_vanilla(self, appid: int) -> bool:
        """Whether the game is currently in vanilla (play-unmodded) mode."""
        return mods.is_game_vanilla(appid)

    async def set_game_vanilla_mode(self, appid: int, vanilla: bool) -> dict:
        """Switch a game between modded and vanilla WITHOUT deleting anything. Entering vanilla
        disables every enabled mod and the modloader, recording what was on; leaving restores
        exactly that state (a mod the user had individually disabled stays disabled). Nothing is
        re-downloaded — files are just toggled aside, so it's instant and reversible.

        File-based mods and the modloader are handled here. Steam Workshop items aren't file-based
        (Steam owns them), so they're reported back as `workshop` fileids for the frontend to flip
        via SteamClient; `modloader_id` is returned when the loader was toggled so the frontend can
        add/remove its launch options. Returns a summary dict."""
        return await plugin_game_lifecycle.set_game_vanilla_mode(appid, vanilla)

    async def cancel_install(self) -> None:
        utils.cancel_install()

    # ── Background download queue ─────────────────────────────────────────────
    # Catalog installs that fetch archives via utils.download (Thunderstore / BMI) are enqueued
    # and drained by a single serial worker, so the UI can show a queue + per-item progress
    # without blocking. The existing install_* methods are reused as the job bodies.
    # The job body is `run(job)`; Thunderstore/BMI ignore the job arg, Nexus reads job.variant
    # (set when the user resolves a parked variant prompt) and job.installed (so a parked cancel
    # can roll back what was installed so far).
    async def enqueue_thunderstore(self, appid: int, full_name: str, name: str,
                                   version: str | None = None, with_deps: bool = True,
                                   allow_missing: bool = False) -> int:
        return await download_queue.enqueue(
            appid, name or full_name, full_name, "thunderstore",
            lambda job: self.install_thunderstore_mod(appid, full_name, version, with_deps, allow_missing),
        )

    async def enqueue_bmi(self, appid: int, mod_id: str, name: str,
                          version: str | None = None) -> int:
        return await download_queue.enqueue(
            appid, name or mod_id, mod_id, "bmi",
            lambda job: self.install_bmi_mod(appid, mod_id, version),
        )

    async def enqueue_nexus(self, appid: int, full_name: str, name: str,
                            version: str | None = None) -> int:
        parsed = nexus.parse_id(full_name)
        mod_id = parsed[1] if parsed else ""
        return await download_queue.enqueue(
            appid, name or full_name, full_name, "nexus",
            run=lambda job: self.install_nexus_mod(appid, full_name, version, job.variant, installed=job.installed),
            # If the user cancels at the variant prompt, undo the requirements installed so far and
            # drop the cached archive the resume would have reused. Resolved at call time (not
            # captured at enqueue) so it works even if the install dir wasn't known when enqueued.
            rollback=lambda job: self._rollback_job(appid, job.installed),
            cleanup=(lambda: mods.discard_natives_cache(f"nexus-{mod_id}")) if mod_id else None,
        )

    async def enqueue_ficsit(self, appid: int, full_name: str, name: str,
                             version: str | None = None) -> int:
        """Queue a ficsit (Satisfactory) install. Like Nexus it cascades dependencies server-side;
        unlike Nexus there's no Premium gate or variant prompt, so the run is a plain install whose
        freshly-placed ids the queue rolls back on cancel/failure."""
        return await download_queue.enqueue(
            appid, name or full_name, full_name, "ficsit",
            run=lambda job: self.install_ficsit_mod(appid, full_name, version, installed=job.installed),
            rollback=lambda job: self._rollback_job(appid, job.installed),
        )

    async def enqueue_collection(self, appid: int, ref: str) -> int:
        """Queue installing a whole collection/modpack as one job. For Nexus, `ref` is a collection URL
        or slug (its required mods at pinned files, curator FOMOD choices replayed). For Thunderstore,
        `ref` is the modpack's full_name (its dependency tree, at latest). Returns the job id, or -1 if
        the game's venue doesn't match / the ref is unusable."""
        if _is_thunderstore_game(appid):
            return await thunderstore_modpacks.enqueue_modpack(appid, ref)
        return await nexus_collections.enqueue_collection(appid, ref)

    async def preview_uninstall_collection(self, slug: str) -> dict:
        """Preview "Uninstall collection <slug>": {remove:[names], keep:[names]} — keep = mods also
        installed manually or in another collection, so the UI can warn before removing."""
        return nexus_collections.preview_uninstall_collection(slug)

    async def uninstall_collection(self, appid: int, slug: str) -> dict:
        """Ref-counted removal of a whole collection: drop each member's collection:<slug> tag,
        uninstall mods whose last source it was, keep those still wanted elsewhere. Returns
        {removed:[ids], kept:[ids]}."""
        return await nexus_collections.uninstall_collection(appid, slug)

    async def _rollback_job(self, appid: int, ids: list) -> None:
        game = registry.get_game_by_appid(appid)
        install_dir = steam.find_game_install_dir(appid) if game else None
        if game and install_dir and ids:
            await plugin_install_common.rollback_installs(game, install_dir, ids)

    async def resume_download_job(self, job_id: int, variant: str) -> bool:
        return await download_queue.resume(job_id, variant)

    # Workshop stays inline: Steam downloads the content itself after a client-side subscribe,
    # so there's no download for the queue to track.

    async def cancel_download_job(self, job_id: int) -> bool:
        return await download_queue.cancel(job_id)

    async def clear_finished_downloads(self, appid: int | None = None) -> None:
        await download_queue.clear_finished(appid)

    async def clear_download_job(self, job_id: int) -> bool:
        return await download_queue.clear_job(job_id)

    async def get_download_queue(self) -> list:
        """Snapshot of the queue so a freshly-mounted UI can hydrate before any event fires."""
        return download_queue.snapshot()

    async def get_profiles(self, appid: int) -> list:
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        return profiles.list_profiles(game.id)

    async def save_profile(self, appid: int, name: str) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        installed = mods.get_installed_mods(game, install_dir)
        snapshot = [
            {"id": m["id"], "enabled": m["enabled"], "version": m.get("version")}
            for m in installed
        ]
        return profiles.save_profile(game.id, name, snapshot)

    async def rename_profile(self, appid: int, old_name: str, new_name: str) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        return profiles.rename_profile(game.id, old_name, new_name)

    async def delete_profile(self, appid: int, name: str) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        return profiles.delete_profile(game.id, name)

    async def _main(self):
        decky.logger.info("Decky Mod Manager loaded")
        # Startup-only crumb sweep: resolve any install artifacts a hard crash stranded mid-commit
        # (restore set-aside backups whose file is gone, drop stale ones and scratch). Safe here
        # because nothing is installing yet; never run while a job is in flight.
        try:
            # First: replay any write-ahead install journal a crash stranded mid-commit — roll an
            # interrupted install back (or a fully-placed one forward). Runs before the crumb sweep so
            # it restores displaced originals (the sweep would otherwise "commit forward" half a mod).
            mods.recover_journals()
            mods.sweep_runtime_scratch()
            for game in registry.SUPPORTED_GAMES:
                install_dir = steam.find_game_install_dir(game.appid)
                if install_dir:
                    mods.sweep_install_crumbs(game, install_dir)
        except Exception as e:
            decky.logger.warning(f"Install-crumb sweep failed: {e}")

    async def _unload(self):
        download_queue.shutdown()
        decky.logger.info("Decky Mod Manager unloaded")

    async def _uninstall(self):
        decky.logger.info("Decky Mod Manager uninstalled")

    async def _migration(self):
        pass