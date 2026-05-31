import sys
import os
import decky

# Add backend directory to path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

import games as game_registry
import steam
import modloaders
import mods
import github


class Plugin:

    async def get_supported_games(self) -> list:
        """Return all supported games with their current install and mod status."""
        result = []
        for game in game_registry.SUPPORTED_GAMES:
            install_dir = steam.find_game_install_dir(game.appid)
            modloader_installed = (
                install_dir is not None and
                modloaders.is_modloader_installed(game, install_dir)
            )
            modloader_enabled = (
                install_dir is not None and
                modloaders.is_modloader_enabled(game, install_dir)
            )
            modloader_ready = (
                install_dir is not None and
                modloaders.is_modloader_ready(game, install_dir)
            )
            installed_mods = mods.get_installed_mods(game, install_dir) if install_dir else []

            result.append({
                "name": game.name,
                "appid": game.appid,
                "modloader": game.modloader,
                "installed": install_dir is not None,
                "install_dir": install_dir or "",
                "modloader_installed": modloader_installed,
                "modloader_enabled": modloader_enabled,
                "modloader_ready": modloader_ready,
                "installed_mods": installed_mods,
                "recommended_mods": [
                    {
                        "name": m.name,
                        "description": m.description,
                        "url": m.url,
                        "filename": m.filename,
                        "author": m.author,
                        "homepage": m.homepage,
                        "thumbnail": m.thumbnail,
                        "dependencies": m.dependencies,
                    }
                    for m in game.recommended_mods
                ],
            })
        return result

    async def install_modloader(self, appid: int) -> bool:
        """Install the modloader for a game."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            decky.logger.error(f"Unknown appid: {appid}")
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            decky.logger.error(f"Game {appid} not installed")
            return False
        return await modloaders.install_modloader(game, install_dir)

    async def uninstall_modloader(self, appid: int) -> bool:
        """Uninstall the modloader for a game."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await modloaders.uninstall_modloader(game, install_dir)

    async def enable_modloader(self, appid: int) -> bool:
        """Re-enable a disabled modloader."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await modloaders.enable_modloader(game, install_dir)

    async def disable_modloader(self, appid: int) -> bool:
        """Disable the modloader without uninstalling it."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await modloaders.disable_modloader(game, install_dir)

    async def install_mod(self, appid: int, mod_filename: str, version: str | None = None) -> bool:
        """Install a recommended mod for a game, optionally at a specific version."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        mod = next((m for m in game.recommended_mods if m.filename == mod_filename), None)
        if not mod:
            decky.logger.error(f"Unknown mod: {mod_filename}")
            return False
        # If a specific version is requested, get its download URL from GitHub
        url = None
        if version and version != "latest":
            repo = github.parse_github_repo(mod.url)
            if repo:
                url = github.get_download_url_for_version(repo[0], repo[1], version, mod.filename)
                if not url:
                    decky.logger.error(f"Could not find download URL for {mod.filename} at {version}")
                    return False
        return await mods.install_mod(game, install_dir, mod, version=version, url=url)

    async def get_mod_releases(self, mod_url: str, mod_filename: str) -> list:
        """Get available releases for a mod from GitHub."""
        repo = github.parse_github_repo(mod_url)
        if not repo:
            return []
        releases = github.get_all_releases(repo[0], repo[1])
        # Filter to only releases that have the right DLL asset
        return [r for r in releases if mod_filename in r.get("download_urls", {})]

    async def check_mod_updates(self, appid: int) -> list:
        """Check which installed mods have updates available. Returns list of mod filenames with updates."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return []
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return []
        updates_available = []
        installed = mods.get_installed_mods(game, install_dir)
        installed_filenames = {m["filename"] for m in installed}
        for mod in game.recommended_mods:
            if mod.filename not in installed_filenames:
                continue
            installed_version = mods.get_installed_version(mod.filename)
            if not installed_version or installed_version == "latest":
                continue  # Can't compare if we don't know the version
            repo = github.parse_github_repo(mod.url)
            if not repo:
                continue
            latest = github.get_latest_release(repo[0], repo[1])
            if latest and latest["version"] != installed_version:
                updates_available.append({
                    "filename": mod.filename,
                    "installed_version": installed_version,
                    "latest_version": latest["version"],
                })
        return updates_available

    async def uninstall_mod(self, appid: int, mod_filename: str) -> bool:
        """Uninstall a mod from a game."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await mods.uninstall_mod(game, install_dir, mod_filename)

    async def toggle_mod(self, appid: int, mod_filename: str, enable: bool) -> bool:
        """Enable or disable a mod."""
        game = game_registry.get_game_by_appid(appid)
        if not game:
            return False
        install_dir = steam.find_game_install_dir(appid)
        if not install_dir:
            return False
        return await mods.toggle_mod(game, install_dir, mod_filename, enable)

    async def cancel_install(self) -> None:
        """Cancel any in-progress installation."""
        modloaders.cancel_install()

    async def _main(self):
        decky.logger.info("Decky Mod Manager loaded")

    async def _unload(self):
        decky.logger.info("Decky Mod Manager unloaded")

    async def _uninstall(self):
        decky.logger.info("Decky Mod Manager uninstalled")

    async def _migration(self):
        pass