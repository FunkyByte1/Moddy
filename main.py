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
# Imported as `settings` for readability, but the file is app_settings.py: a bare module
# named `settings` collides with decky_loader's own `settings` module (which wins on the
# import path), so `import settings` would silently resolve to the wrong module.
import app_settings as settings
import utils
import steamworkshop_browse
import download_queue
import install_cascade


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


def _library_full_names(game: "registry.GameProfile", lib_cats: list[str]) -> set[str]:
    """Lowercased catalog full_names whose categories mark them as libraries."""
    if not lib_cats:
        return set()
    lib_set = {c.lower() for c in lib_cats}
    names: set[str] = set()
    for p in _catalog_for_game(game):
        if any(c.lower() in lib_set for c in p.get("categories", [])):
            names.add(p.get("full_name", "").lower())
    names.discard("")
    return names


def _build_game_status(game: "registry.GameProfile", libraries: "list[str] | None" = None) -> dict:
    """Build the install/mod-status dict for one supported game. Pass `libraries` (a
    pre-parsed Steam library list) when building many games at once so libraryfolders.vdf
    is read once for the whole batch rather than once per game."""
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
    lib_names = (
        _library_full_names(game, lib_cats)
        if (installed_mods_list and lib_cats) else set()
    )
    workshop = game.uses_steam_workshop()
    for im in installed_mods_list:
        # Workshop mods carry is_library on their record (from the game's
        # library_workshop_ids); don't clobber it with catalog logic.
        if workshop:
            continue
        idl = im["id"].lower()
        im["is_library"] = idl in lib_names or idl in framework_ids

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
    }


class Plugin:

    async def get_supported_appids(self) -> list[int]:
        """Return the list of Steam appids this plugin supports — used by the frontend to gate the context-menu patch."""
        return [g.appid for g in registry.SUPPORTED_GAMES]

    async def get_supported_games(self) -> list:
        """Return all supported games with current install and mod status."""
        # Parse the Steam library list once for the whole batch instead of per game.
        libraries = steam.find_steam_libraries()
        return [_build_game_status(game, libraries) for game in registry.SUPPORTED_GAMES]

    async def get_game_status(self, appid: int) -> dict | None:
        """Return install/mod status for a single supported game (or None if unsupported).
        The per-mod-action refresh only needs the game being configured, so this avoids
        recomputing status (install-dir resolution + a full installed-mods scan) for every
        other supported game on every toggle/install. Behaviourally identical to picking
        this appid out of get_supported_games()."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return None
        return _build_game_status(game)

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
                await self._ensure_framework(game, install_dir, key)
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
            await self._ensure_framework(game, install_dir, "steamodded")
        if item.get("requires_talisman"):
            await self._ensure_framework(game, install_dir, "talisman")

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
                                include_adult: bool | None = None) -> list:
        """A page (~25 items) of the Nexus catalog for a game whose Browse source is Nexus,
        searched server-side by `query` via the v2 GraphQL API. Returns [] for non-Nexus
        games, on error, or when no Nexus API key is configured.

        `include_adult` is driven per-fetch by the Browse filter's "Show NSFW" toggle. When
        the caller omits it, fall back to the `nexus_include_adult` setting key."""
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "nexus":
            return []
        domain = game.catalog.get("nexus_domain", "")
        if not domain:
            return []
        # Adult mods are hidden by default; the Browse filter's NSFW toggle opts in per-fetch.
        if include_adult is None:
            include_adult = bool(settings.get_setting("nexus_include_adult", False))
        results = nexus.search(domain, query, page, bool(include_adult))
        return [it for it in results if it.get("full_name", "").lower() not in self._NEXUS_DENYLIST]

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
        game = registry.get_game_by_appid(appid)
        if not game or game.catalog.get("type") != "nexus":
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        parsed = nexus.parse_id(full_name)
        if not parsed:
            decky.logger.error(f"Bad Nexus install id: {full_name}")
            return False
        domain, mod_id = parsed
        if installed is None:
            installed = []
        # No "N of M" pre-pass for Nexus: unlike Thunderstore's in-memory catalog, requirement
        # resolution is an uncached GraphQL call, so a pre-pass would double those calls — and a
        # rate-limited second call (the one that actually drives the cascade) could return nothing,
        # silently skipping requirements. The per-package sub-label + percent still show.
        res = await self._install_nexus_recursive(
            game, install_dir, domain, mod_id, version, seen=set(), variant=variant, top=True,
            installed=installed,
        )
        # Roll back on cancel (None) or failure (False) — but NOT when parking for a variant choice
        # (a dict), which is resolved later. Requirements installed before the park are in
        # `installed`, so a subsequent cancel-at-prompt still rolls them back (via the queue hook).
        if (res is None or res is False) and installed:
            await self._rollback_installs(game, install_dir, installed)
        return res

    async def _install_nexus_recursive(
        self,
        game: "registry.GameProfile",
        install_dir: str,
        domain: str,
        mod_id: str,
        version: str | None,
        seen: set,
        variant: str | None = None,
        top: bool = False,
        installed: "list | None" = None,
    ):
        """Install one Nexus mod plus its same-domain requirements (depth-first), via the shared
        cascade. Requirements install at latest; only the top-level mod honors an explicit version
        and variant. A failed requirement is best-effort (continue); a Premium-gated download aborts
        and surfaces "premium_required". Returns True/False/None/"premium_required"/needs-variant."""
        provider = install_cascade.NexusProvider(self._NEXUS_DENYLIST)
        return await install_cascade.run_cascade(
            provider, game, install_dir, (domain, mod_id), version,
            seen=seen, installed=installed, top=top, variant=variant,
        )

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
        import glob
        import time
        import zipfile
        try:
            log_dir = decky.DECKY_PLUGIN_LOG_DIR
            home = getattr(decky, "DECKY_USER_HOME", None) or decky.HOME
            desktop = os.path.join(home, "Desktop")
            dest_dir = desktop if os.path.isdir(desktop) else home
            ts = time.strftime("%Y%m%d-%H%M%S")
            dest = os.path.join(dest_dir, f"moddy-logs-{ts}.zip")

            # System info, so reports carry version/env without us having to ask for it.
            info = [
                f"Moddy {getattr(decky, 'DECKY_PLUGIN_VERSION', '?')}",
                f"Decky {getattr(decky, 'DECKY_VERSION', '?')}",
                f"Platform: {sys.platform}",
                f"Exported: {ts}",
                "",
                "Supported games:",
            ]
            for game in registry.SUPPORTED_GAMES:
                install_dir = steam.find_game_install_dir(game.appid)
                state = "installed" if install_dir else "not installed"
                info.append(f"  - {game.name} ({game.appid}): {state}")

            log_files = [p for p in glob.glob(os.path.join(log_dir, "*")) if os.path.isfile(p)]
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("moddy-info.txt", "\n".join(info) + "\n")
                for path in log_files:
                    zf.write(path, arcname=os.path.join("logs", os.path.basename(path)))

            decky.logger.info(f"Exported {len(log_files)} log file(s) to {dest}")
            return dest
        except Exception as e:
            decky.logger.error(f"Log export failed: {e}")
            return None

    async def _ensure_framework(self, game: "registry.GameProfile", install_dir: str, key: str) -> bool:
        """Install a framework mod (e.g. Steamodded, Talisman) into the Mods folder if it
        isn't already present. Frameworks are declared per-game under `frameworks` in the
        game JSON and downloaded as GitHub branch archives into Mods/<filename>/."""
        fw = game.frameworks.get(key)
        if not fw:
            decky.logger.warning(f"No framework config '{key}' for {game.id}")
            return False
        fw_id = fw.get("id", key)
        if mods.get_installed_record(fw_id) is not None:
            return True  # already installed
        src = fw.get("source", {})
        owner, repo = src.get("owner", ""), src.get("repo", "")
        if not owner or not repo:
            decky.logger.warning(f"Framework '{key}' for {game.id} has no GitHub source")
            return False
        url = github.get_source_url(owner, repo, src.get("branch", "main"))
        mod = registry.ModInfo(
            id=fw_id,
            name=fw.get("name", key),
            description=fw.get("description", ""),
            filename=fw.get("filename", fw_id),
            source=registry.ModSource(type="url", url=url, install_type="zip_dir"),
            author=owner,
            homepage=f"https://github.com/{owner}/{repo}",
            modloader=game.modloaders[0].id if game.modloaders else "",
        )
        decky.logger.info(f"Installing framework {fw.get('name', key)} for {game.id}")
        return bool(await mods.install_mod(game, install_dir, mod, version="latest", url=url))

    # Thunderstore packages that should never be installed as plugins via Browse —
    # modloaders (already provided by Mod Loader tab) and desktop mod-manager apps.
    # Case-insensitive comparison. Frontend uses get_browse_denylist() to keep these
    # off the Browse list too.
    _BROWSE_DENYLIST = {
        "bbepis-bepinexpack",
        "riskofthunder-bepinexpack",
        "bepinex-bepinexpack_peak",  # PEAK modloader — installed via the Mod Loader tab, not as a plugin
        "bepinex-bepinexpack_etg",  # Enter the Gungeon modloader — installed via the Mod Loader tab, not as a plugin
        "ebkr-r2modman",
        "kesomannen-galemodmanager",
        "thunderstore-lovely",  # Balatro injector — installed via the Mod Loader tab, not as a Mods/ plugin
    }

    # Nexus mods (by `nexus.<domain>.<mod_id>` install id, lowercase) that are tools/managers, not
    # game content — never install them as a requirement, and hide them from Browse.
    _NEXUS_DENYLIST = {
        "nexus.residentevil42023.14",  # Fluffy Mod Manager (desktop app, not an in-game mod)
    }

    async def get_browse_denylist(self) -> list[str]:
        """Lowercase install ids the UI should treat as 'not a real dependency' — modloaders,
        mod-manager apps (Thunderstore + Nexus), and every game's implicit deps (modloader cores
        like RiskofThunder-RoR2BepInExPack that the cascade injects into each install, so no mod
        declares them) — so they're hidden from Browse, never flagged as a missing dependency, and
        never offered as an 'unused library'.

        Implicit deps are unioned in only here, NOT into _BROWSE_DENYLIST: that set is what the
        install cascade uses to *skip* installs, and the modloader cores must still get installed."""
        implicit = {dep.lower() for g in registry.SUPPORTED_GAMES for dep in g.implicit_deps}
        return sorted(self._BROWSE_DENYLIST | self._NEXUS_DENYLIST | implicit)

    async def get_unresolved_dependencies(self, appid: int, full_name: str, with_deps: bool = True) -> list:
        """Declared dependencies of `full_name` that aren't in the catalog (so they can't be
        installed). Resolves the dependency tree up front; if anything looks missing, refreshes the
        catalog once and re-resolves first — a "missing" dep is most often just a stale cache. The
        UI calls this before installing so it can warn / offer "install anyway". Empty = all good."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return []
        unresolved: list[str] = []
        self._resolve_thunderstore_plan(game, full_name, None, with_deps, set(), [], unresolved)
        if unresolved:
            # Could be a stale catalog — pull a fresh copy and re-resolve before reporting.
            thunderstore.refresh_community_catalog(game.thunderstore_community)
            unresolved = []
            self._resolve_thunderstore_plan(game, full_name, None, with_deps, set(), [], unresolved)
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
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        # Size the cascade up front (mod + deps that aren't already installed) so the UI can show
        # "N of M". Cheap — resolves against the in-memory catalog, no downloads.
        plan: list[str] = []
        self._resolve_thunderstore_plan(game, full_name, version, with_deps, set(), plan, [], install_dir)
        await download_queue.note_total(len(plan))
        # Atomic cancel: track the packages this run freshly installs so a cancel mid-cascade can
        # undo them, leaving the system as if the install never started. Updates of already-present
        # mods aren't tracked (a cancelled download leaves the prior version intact).
        installed_this_run: list[str] = []
        result = await self._install_thunderstore_recursive(
            game, install_dir, full_name, version, seen=set(), with_deps=with_deps,
            installed_this_run=installed_this_run, allow_missing=allow_missing,
        )
        # Roll back on cancel (None) or hard failure (False) — either way the install didn't
        # complete, so leave no partial trace.
        if not result and installed_this_run:
            await self._rollback_installs(game, install_dir, installed_this_run)
        return result

    def _resolve_thunderstore_plan(
        self, game: "registry.GameProfile", full_name: str, version: str | None,
        with_deps: bool, seen: set, plan: list, unresolved: list, install_dir: str | None = None,
    ) -> None:
        """Size the Thunderstore cascade (depth-first packages it will download, into `plan`) and
        collect declared deps not in the catalog (into `unresolved`), via the shared dry-run walk."""
        provider = install_cascade.ThunderstoreProvider(self._BROWSE_DENYLIST)
        install_cascade.collect_plan(
            provider, game, full_name, version=version, with_deps=with_deps,
            seen=seen, plan=plan, unresolved=unresolved, install_dir=install_dir,
        )

    async def _rollback_installs(self, game: "registry.GameProfile", install_dir: str, ids: list) -> None:
        """Undo a cancelled install: uninstall the mods it freshly installed, newest first (so a
        mod is removed before the dependencies it sits on). Pre-existing mods aren't in this list,
        so a shared dependency installed by an earlier job is left untouched."""
        for mod_id in reversed(ids):
            try:
                await mods.uninstall_mod(game, install_dir, mod_id)
                decky.logger.info(f"Rolled back {mod_id} after cancelled install")
            except Exception as e:
                decky.logger.warning(f"Rollback of {mod_id} failed: {e}")

    async def _install_thunderstore_recursive(
        self,
        game: "registry.GameProfile",
        install_dir: str,
        full_name: str,
        version: str | None,
        seen: set,
        with_deps: bool = True,
        installed_this_run: "list | None" = None,
        allow_missing: bool = False,
        is_dependency: bool = False,
    ) -> bool | None:
        """Install a Thunderstore mod plus its dependencies (depth-first), via the shared cascade.
        Already-installed deps and denylisted packages are skipped; a failed/missing dependency
        aborts (unless allow_missing skips a missing one). Returns True/False/None."""
        provider = install_cascade.ThunderstoreProvider(self._BROWSE_DENYLIST)
        return await install_cascade.run_cascade(
            provider, game, install_dir, full_name, version,
            seen=seen, installed=installed_this_run, with_deps=with_deps,
            allow_missing=allow_missing, is_dependency=is_dependency,
        )

    async def reset_game(self, appid: int) -> dict:
        """Reset a game to its unmodded state: uninstall every tracked mod, then every
        installed modloader, then remove any orphaned mods directory left behind.
        Returns a summary: {ok, mods_removed, modloader_removed}.
        Order matters — mods are removed before the modloader so their install records
        get cleared while their files still exist (uninstalling the modloader wipes the
        whole BepInEx/ tree, which would orphan those records)."""
        import shutil
        game = registry.get_game_by_appid(appid)
        if not game:
            return {"ok": False, "mods_removed": 0, "modloader_removed": False}
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return {"ok": False, "mods_removed": 0, "modloader_removed": False}

        mods_removed = 0
        failures = 0
        for entry in mods.get_installed_mods(game, install_dir):
            if await mods.uninstall_mod(game, install_dir, entry["id"]):
                mods_removed += 1
            else:
                failures += 1

        modloader_removed = False
        for ml in game.modloaders:
            if not modloaders.is_modloader_installed(game, install_dir, ml.id):
                continue
            if await modloaders.uninstall_modloader(game, install_dir, ml.id):
                modloader_removed = True
            else:
                failures += 1

        # Clean up an orphaned mods directory (e.g. MelonLoader's Mods/ folder, which
        # lives outside the modloader dir and so survives its uninstall). For BepInEx
        # this path sits under BepInEx/ and is already gone — the guard makes it a no-op.
        # CRITICAL: never rmtree when the "mods dir" IS the game root (mods_dir="", e.g. RE4) —
        # that would delete the entire game. Such games keep mods as tracked loose/.pak files
        # (already removed by the per-mod uninstall loop above), so there's no dir to orphan.
        try:
            mods_path = mods.resolve_mods_path(game, install_dir)
            if os.path.isdir(mods_path) and os.path.normpath(mods_path) != os.path.normpath(install_dir):
                shutil.rmtree(mods_path)
                decky.logger.info(f"Removed orphaned mods dir {mods_path}")
        except Exception as e:
            decky.logger.error(f"Failed to remove mods dir during reset: {e}")
            failures += 1

        decky.logger.info(
            f"Reset {game.name}: removed {mods_removed} mod(s), "
            f"modloader_removed={modloader_removed}, failures={failures}"
        )
        return {
            "ok": failures == 0,
            "mods_removed": mods_removed,
            "modloader_removed": modloader_removed,
        }

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

    async def _rollback_job(self, appid: int, ids: list) -> None:
        game = registry.get_game_by_appid(appid)
        install_dir = steam.find_game_install_dir(appid) if game else None
        if game and install_dir and ids:
            await self._rollback_installs(game, install_dir, ids)

    async def resume_download_job(self, job_id: int, variant: str) -> bool:
        return await download_queue.resume(job_id, variant)

    # Workshop stays inline: Steam downloads the content itself after a client-side subscribe,
    # so there's no download for the queue to track.

    async def cancel_download_job(self, job_id: int) -> bool:
        return await download_queue.cancel(job_id)

    async def clear_finished_downloads(self) -> None:
        await download_queue.clear_finished()

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