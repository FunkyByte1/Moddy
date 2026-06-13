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
import bmi
import utils


def _catalog_for_game(game: "registry.GameProfile") -> list[dict]:
    """The Browse catalog backing a game (BMI or Thunderstore), or [] if none / on error.
    Served from the same on-disk cache the Browse tab uses, so this is cheap to reuse."""
    try:
        if game.catalog.get("type") == "bmi" and game.catalog.get("repo"):
            return bmi.get_bmi_catalog(game.catalog["repo"], game.catalog.get("branch", "main"))
        if game.thunderstore_community:
            return github.get_thunderstore_community_catalog(game.thunderstore_community)
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


class Plugin:

    async def get_supported_appids(self) -> list[int]:
        """Return the list of Steam appids this plugin supports — used by the frontend to gate the context-menu patch."""
        return [g.appid for g in registry.SUPPORTED_GAMES]

    async def get_supported_games(self) -> list:
        """Return all supported games with current install and mod status."""
        result = []
        for game in registry.SUPPORTED_GAMES:
            install_dir = steam.find_game_install_dir(game.appid)

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
            for im in installed_mods_list:
                idl = im["id"].lower()
                im["is_library"] = idl in lib_names or idl in framework_ids

            result.append({
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
                # Which Browse catalog backs this game: "bmi", "thunderstore", or "" (curated-only).
                "catalog_type": game.catalog.get("type") or ("thunderstore" if game.thunderstore_community else ""),
                # Catalog categories the UI treats as "library" (hidden by default).
                "library_categories": lib_cats,
                "installed": install_dir is not None,
                "install_dir": install_dir or "",
                "modloader_installed": modloader_installed,
                "modloader_enabled": modloader_enabled,
                "modloader_ready": modloader_ready,
                "installed_mods": installed_mods_list,
                "mods": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "description": m.description,
                        "filename": m.filename,
                        "author": m.author,
                        "homepage": m.homepage,
                        "thumbnail": m.thumbnail,
                        "modloader": m.modloader,
                        "dependencies": m.dependencies,
                        "is_library": m.is_library,
                        "source": {
                            "type": m.source.type,
                            "owner": m.source.owner,
                            "repo": m.source.repo,
                            "asset": m.source.asset,
                            "install_type": m.source.install_type,
                            "workshop_id": m.source.workshop_id,
                        },
                    }
                    for m in game.mods
                ],
            })
        return result

    async def install_modloader(self, appid: int, version: str | None = None) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        ok = await modloaders.install_modloader(game, install_dir, game.modloaders[0].id, version)
        if ok:
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

    async def uninstall_modloader(self, appid: int) -> bool:
        game = registry.get_game_by_appid(appid)
        if not game or not game.modloaders:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        # Remove bundled frameworks first — they're part of the loader, not content mods.
        for fw_id in game.bundled_framework_ids():
            if mods.get_installed_record(fw_id) is not None:
                await mods.uninstall_mod(game, install_dir, fw_id)
        return await modloaders.uninstall_modloader(game, install_dir, game.modloaders[0].id)

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
        """Install a mod. Returns True=success, False=failed, None=cancelled."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        mod = game.get_mod(mod_id)
        if not mod:
            decky.logger.error(f"Unknown mod: {mod_id}")
            return False

        url = None
        resolved_version = version

        if mod.source.type == "github":
            if version:
                url = github.get_download_url_for_version(
                    mod.source.owner, mod.source.repo, version, mod.source.asset
                )
                if not url:
                    decky.logger.error(f"Could not find download URL for {mod_id} at {version}")
                    return False
            else:
                result = github.get_latest_download_url(
                    mod.source.owner, mod.source.repo, mod.source.asset
                )
                if result:
                    resolved_version, url = result
                else:
                    decky.logger.error(f"Could not resolve latest release for {mod_id}")
                    return False
        elif mod.source.type == "thunderstore":
            if version:
                url = github.get_thunderstore_download_url(mod.source.owner, mod.source.repo, version)
                resolved_version = version
            else:
                latest = github.get_thunderstore_latest(mod.source.owner, mod.source.repo)
                if not latest:
                    decky.logger.error(f"Could not resolve latest Thunderstore release for {mod_id}")
                    return False
                resolved_version = latest["version"]
                url = latest["download_url"]
        elif mod.source.type == "url":
            url = mod.source.url
        elif mod.source.type == "steamworkshop":
            # No download/URL — install == subscribe via the running Steam client.
            return await mods.install_workshop_mod(game, mod)
        else:
            decky.logger.error(f"Unsupported mod source type: {mod.source.type}")
            return False

        return await mods.install_mod(game, install_dir, mod, version=resolved_version, url=url)

    async def get_mod_releases(self, appid: int, mod_id: str) -> list:
        """Get available releases for a mod (curated or browsed)."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        mod = game.get_mod(mod_id)
        if mod:
            if mod.source.type == "github":
                releases = github.get_all_releases(mod.source.owner, mod.source.repo)
                return [r for r in releases if mod.source.asset in r.get("download_urls", {})]
            if mod.source.type == "thunderstore":
                return github.get_thunderstore_all_versions(mod.source.owner, mod.source.repo)
            return []  # github_source and others don't have versioned releases
        # Browsed mod — look up by full_name in the community catalog
        if game.thunderstore_community:
            pkg = github.find_thunderstore_package(game.thunderstore_community, mod_id)
            if pkg:
                return github.get_thunderstore_all_versions(pkg["owner"], pkg["name"])
        return []

    async def check_mod_updates(self, appid: int) -> list:
        """Check which installed mods have updates available. Walks installed.json
        (not game.mods) so browsed Thunderstore mods get checked the same way."""
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
            mod = game.get_mod(mod_id)
            if mod:
                source_type, owner, repo, asset = mod.source.type, mod.source.owner, mod.source.repo, mod.source.asset
            else:
                source = (mods.get_installed_record(mod_id) or {}).get("source") or {}
                source_type, owner, repo, asset = source.get("type", ""), source.get("owner", ""), source.get("repo", ""), source.get("asset", "")
            if not owner or not repo:
                continue
            if source_type == "github":
                latest = github.get_latest_release(owner, repo)
            elif source_type == "thunderstore":
                latest = github.get_thunderstore_latest(owner, repo)
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
        return github.get_thunderstore_community_catalog(game.thunderstore_community)

    async def refresh_thunderstore_catalog(self, appid: int) -> bool:
        """Force a fresh catalog pull from Thunderstore, keeping the existing cache
        if the fetch fails. Returns True only if a fresh copy was actually fetched."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return False
        return github.refresh_thunderstore_community_catalog(game.thunderstore_community)

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
        return await mods.install_mod(game, install_dir, mod, version=target_version, url=url)

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
        url = github.get_github_source_url(owner, repo, src.get("branch", "main"))
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
        "ebkr-r2modman",
        "kesomannen-galemodmanager",
        "thunderstore-lovely",  # Balatro injector — installed via the Mod Loader tab, not as a Mods/ plugin
    }

    async def get_browse_denylist(self) -> list[str]:
        """Lowercase full_names the Browse tab should hide and cascade-install should skip."""
        return sorted(self._BROWSE_DENYLIST)

    async def install_thunderstore_mod(
        self, appid: int, full_name: str, version: str | None = None
    ) -> bool | None:
        """Install a Thunderstore mod by full_name (e.g. 'RiskofThunder-R2API_Core'),
        recursively installing any declared dependencies first. Already-installed
        deps and denylisted modloader packages are skipped.
        Returns True=success, False=failed, None=cancelled."""
        game = registry.get_game_by_appid(appid)
        if not game or not game.thunderstore_community:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await self._install_thunderstore_recursive(
            game, install_dir, full_name, version, seen=set()
        )

    async def _install_thunderstore_recursive(
        self,
        game: "registry.GameProfile",
        install_dir: str,
        full_name: str,
        version: str | None,
        seen: set,
    ) -> bool | None:
        key = full_name.lower()
        if key in seen:
            return True
        seen.add(key)
        # Skip modloaders/mod-managers that shouldn't be installed as plugins
        if key in self._BROWSE_DENYLIST:
            decky.logger.info(f"Skipping denylisted package {full_name}")
            return True
        # Skip if already installed (lookup is case-insensitive against installed.json keys)
        existing = mods.get_installed_record(full_name)
        if existing is None:
            # Fallback: scan store keys case-insensitively in case the catalog uses
            # different casing than what was originally persisted
            for k in (mods._load_store() or {}).keys():
                if k.lower() == key:
                    existing = mods.get_installed_record(k)
                    break
        if existing and version is None:
            decky.logger.info(f"{full_name} already installed; skipping")
            return True
        pkg = github.find_thunderstore_package(game.thunderstore_community, full_name)
        if not pkg:
            decky.logger.error(f"Thunderstore package not found in catalog: {full_name}")
            return False
        latest = pkg.get("latest", {})
        # Install deps first (depth-first). Always use the catalog's latest version for deps —
        # the version pinned in the dep string is just the minimum the parent was tested against.
        # Implicit deps (declared per-game) cover cases where the Thunderstore manifest
        # doesn't list a runtime requirement — e.g. RoR2 mods that need Newtonsoft.Json from
        # RoR2BepInExPack but never list it as a manifest dep.
        explicit_deps: list[str] = []
        for dep_str in latest.get("dependencies", []):
            parsed = github.parse_thunderstore_dep(dep_str)
            if not parsed:
                decky.logger.warning(f"Could not parse dep string '{dep_str}' for {full_name}")
                continue
            explicit_deps.append(parsed[0])
        dep_full_names = list(game.implicit_deps) + explicit_deps
        for dep_full_name in dep_full_names:
            dep_result = await self._install_thunderstore_recursive(
                game, install_dir, dep_full_name, None, seen
            )
            if dep_result is None:
                return None  # propagate cancellation
            if not dep_result:
                decky.logger.warning(
                    f"Dependency {dep_full_name} of {full_name} failed to install; continuing"
                )
        target_version = version or latest.get("version_number")
        if version:
            url = github.get_thunderstore_download_url(pkg["owner"], pkg["name"], version)
        else:
            url = latest.get("download_url")
        if not url or not target_version:
            decky.logger.error(f"Could not resolve download URL for {full_name}")
            return False
        ml_id = game.modloaders[0].id if game.modloaders else ""
        mod = registry.ModInfo(
            id=pkg["full_name"],
            name=pkg["name"],
            description=latest.get("description", ""),
            filename=pkg["name"],
            source=registry.ModSource(
                type="thunderstore",
                owner=pkg["owner"],
                repo=pkg["name"],
                install_type="zip_dir",
            ),
            author=pkg["owner"],
            homepage=pkg.get("package_url", ""),
            thumbnail=latest.get("icon", ""),
            modloader=ml_id,
            dependencies=list(latest.get("dependencies", [])),
        )
        return await mods.install_mod(game, install_dir, mod, version=target_version, url=url)

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
        try:
            mods_path = mods.resolve_mods_path(game, install_dir)
            if os.path.isdir(mods_path):
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

    async def _unload(self):
        decky.logger.info("Decky Mod Manager unloaded")

    async def _uninstall(self):
        decky.logger.info("Decky Mod Manager uninstalled")

    async def _migration(self):
        pass