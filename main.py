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
import utils


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

            result.append({
                "id": game.id,
                "name": game.name,
                "appid": game.appid,
                "modloader": ml_id or "",
                "modloader_name": ml.name if ml else "",
                "modloader_launch_options": ml.launch_options if ml else "",
                "modloader_needs_first_launch": bool(ml and ml.ready_indicator),
                "thunderstore_community": game.thunderstore_community,
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
                        "source": {
                            "type": m.source.type,
                            "owner": m.source.owner,
                            "repo": m.source.repo,
                            "asset": m.source.asset,
                            "install_type": m.source.install_type,
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
        return await modloaders.install_modloader(game, install_dir, game.modloaders[0].id, version)

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

    # Thunderstore packages that should never be installed as plugins via Browse —
    # modloaders (already provided by Mod Loader tab) and desktop mod-manager apps.
    # Case-insensitive comparison. Frontend uses get_browse_denylist() to keep these
    # off the Browse list too.
    _BROWSE_DENYLIST = {
        "bbepis-bepinexpack",
        "riskofthunder-bepinexpack",
        "ebkr-r2modman",
        "kesomannen-galemodmanager",
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