import sys
import os
import decky

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

import registry
import steam
import modloaders
import mods
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
        """Get available releases for a mod."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        mod = game.get_mod(mod_id)
        if not mod:
            return []
        if mod.source.type == "github":
            releases = github.get_all_releases(mod.source.owner, mod.source.repo)
            return [r for r in releases if mod.source.asset in r.get("download_urls", {})]
        if mod.source.type == "thunderstore":
            return github.get_thunderstore_all_versions(mod.source.owner, mod.source.repo)
        return []  # github_source and others don't have versioned releases

    async def check_mod_updates(self, appid: int) -> list:
        """Check which installed mods have updates available."""
        game = registry.get_game_by_appid(appid)
        if not game:
            return []
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return []
        installed = mods.get_installed_mods(game, install_dir)
        installed_ids = {m["id"] for m in installed}
        updates = []
        for mod in game.mods:
            if mod.id not in installed_ids:
                continue
            installed_version = mods.get_installed_version(mod.id)
            if not installed_version or installed_version == "latest":
                continue
            if mod.source.type == "github":
                latest = github.get_latest_release(mod.source.owner, mod.source.repo)
                if latest and latest["version"] != installed_version:
                    updates.append({
                        "id": mod.id,
                        "installed_version": installed_version,
                        "latest_version": latest["version"],
                    })
            elif mod.source.type == "thunderstore":
                latest = github.get_thunderstore_latest(mod.source.owner, mod.source.repo)
                if latest and latest["version"] != installed_version:
                    updates.append({
                        "id": mod.id,
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

    async def cancel_install(self) -> None:
        utils.cancel_install()

    async def _main(self):
        decky.logger.info("Decky Mod Manager loaded")

    async def _unload(self):
        decky.logger.info("Decky Mod Manager unloaded")

    async def _uninstall(self):
        decky.logger.info("Decky Mod Manager uninstalled")

    async def _migration(self):
        pass