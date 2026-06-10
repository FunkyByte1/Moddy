import os
import json
import shutil
import zipfile
import decky
import github
import utils
from registry import GameProfile, ModloaderInfo

# Version store — stored inside installed.json under "modloaders" key
_modloader_versions: dict = {}


def _get_store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _load_version_store() -> dict:
    global _modloader_versions
    if _modloader_versions:
        return _modloader_versions
    path = _get_store_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
                _modloader_versions = data.get("modloaders", {})
                return _modloader_versions
    except Exception as e:
        decky.logger.error(f"Failed to load modloader versions: {e}")
    _modloader_versions = {}
    return _modloader_versions


def _save_version_store(store: dict) -> None:
    global _modloader_versions
    _modloader_versions = store
    path = _get_store_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        full = {}
        if os.path.isfile(path):
            with open(path, "r") as f:
                full = json.load(f)
        full["modloaders"] = store
        with open(tmp, "w") as f:
            json.dump(full, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        decky.logger.error(f"Failed to save modloader versions: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)


def get_modloader_version(modloader_id: str) -> str | None:
    return _load_version_store().get(modloader_id, {}).get("version")


def set_modloader_version(modloader_id: str, version: str) -> None:
    store = _load_version_store()
    store[modloader_id] = {"version": version}
    _save_version_store(store)


def clear_modloader_version(modloader_id: str) -> None:
    store = _load_version_store()
    if modloader_id in store:
        del store[modloader_id]
        _save_version_store(store)


def is_modloader_installed(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml or not ml.indicator:
        return False
    return (
        os.path.exists(os.path.join(install_dir, ml.indicator)) or
        os.path.exists(os.path.join(install_dir, ml.indicator + ".disabled"))
    )


def is_modloader_enabled(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml or not ml.indicator:
        return False
    return os.path.exists(os.path.join(install_dir, ml.indicator))


def is_modloader_ready(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.ready_indicator:
        return os.path.exists(os.path.join(install_dir, ml.ready_indicator))
    return is_modloader_installed(game, install_dir, modloader_id)


async def enable_modloader(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    try:
        for f in ml.files:
            src = os.path.join(install_dir, f + ".disabled")
            if os.path.isfile(src):
                os.rename(src, os.path.join(install_dir, f))
        for d in ml.dirs:
            src = os.path.join(install_dir, d + ".disabled")
            if os.path.isdir(src):
                os.rename(src, os.path.join(install_dir, d))
        decky.logger.info(f"Enabled {modloader_id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to enable {modloader_id}: {e}")
        return False


async def disable_modloader(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    try:
        for f in ml.files:
            src = os.path.join(install_dir, f)
            if os.path.isfile(src):
                os.rename(src, src + ".disabled")
        for d in ml.dirs:
            src = os.path.join(install_dir, d)
            if os.path.isdir(src):
                os.rename(src, src + ".disabled")
        decky.logger.info(f"Disabled {modloader_id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to disable {modloader_id}: {e}")
        return False


async def uninstall_modloader(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    try:
        for f in ml.files:
            for candidate in [f, f + ".disabled"]:
                path = os.path.join(install_dir, candidate)
                if os.path.isfile(path):
                    os.remove(path)
        for d in ml.dirs:
            for candidate in [d, d + ".disabled"]:
                path = os.path.join(install_dir, candidate)
                if os.path.isdir(path):
                    shutil.rmtree(path)
        # Restore backed up version.dll if present
        bak = os.path.join(install_dir, "version.dll.deckhand_bak")
        if os.path.isfile(bak):
            os.rename(bak, os.path.join(install_dir, "version.dll"))
        clear_modloader_version(modloader_id)
        decky.logger.info(f"Uninstalled {modloader_id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {modloader_id}: {e}")
        return False


def _rollback(install_dir: str, backed_up: dict) -> None:
    try:
        for original, bak in backed_up.items():
            if os.path.isfile(bak):
                if os.path.isfile(original):
                    os.remove(original)
                shutil.copy2(bak, original)
                os.remove(bak)
            elif os.path.isdir(bak):
                if os.path.isdir(original):
                    shutil.rmtree(original)
                shutil.move(bak, original)
    except Exception as e:
        decky.logger.error(f"Rollback failed: {e}")


async def install_modloader(game: GameProfile, install_dir: str, modloader_id: str, version: str | None = None) -> bool:
    """Install a modloader for a game. Returns True on success."""
    ml = game.get_modloader(modloader_id)
    if not ml:
        decky.logger.error(f"Unknown modloader: {modloader_id}")
        return False
    if ml.source.type == "github":
        return await _install_github_modloader(game, install_dir, ml, version)
    if ml.source.type == "thunderstore":
        return await _install_thunderstore_modloader(game, install_dir, ml, version)
    decky.logger.error(f"Unsupported modloader source type: {ml.source.type}")
    return False


async def _install_thunderstore_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """Install a Thunderstore-sourced modloader (BepInExPack pattern)."""
    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.zip")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")
    try:
        if version:
            url = github.get_thunderstore_download_url(ml.source.owner, ml.source.repo, version)
            resolved_version = version
        else:
            latest = github.get_thunderstore_latest(ml.source.owner, ml.source.repo)
            if not latest:
                decky.logger.error(f"Could not resolve latest {ml.id} release from Thunderstore")
                return False
            resolved_version = latest["version"]
            url = latest["download_url"]

        decky.logger.info(f"Downloading {ml.name} {resolved_version} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(tmp_dir)

        # Thunderstore packs vary: sometimes BepInEx files are at zip root, sometimes
        # nested under a folder like BepInExPack/. Locate the directory that actually
        # contains the modloader's payload (one of ml.files, e.g. winhttp.dll), and copy
        # from there. Falls back to tmp_dir if nothing matches.
        inner_path = tmp_dir
        marker = ml.files[0] if ml.files else None
        if marker:
            for root, _dirs, files in os.walk(tmp_dir):
                if marker in files:
                    inner_path = root
                    break

        for item in os.listdir(inner_path):
            src = os.path.join(inner_path, item)
            dst = os.path.join(install_dir, item)
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        set_modloader_version(ml.id, resolved_version)
        decky.logger.info(f"{ml.name} {resolved_version} installed successfully")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"{ml.name} installation was cancelled")
        return False
    except Exception as e:
        decky.logger.error(f"{ml.name} installation failed: {e}")
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)


async def _install_github_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """Install a GitHub-sourced modloader (zip-based, like MelonLoader)."""
    # Resolve version and download URL
    if version:
        url = github.get_download_url_for_version(ml.source.owner, ml.source.repo, version, ml.source.asset)
        if not url:
            decky.logger.error(f"Could not find {ml.source.asset} for {ml.id} {version}")
            return False
        resolved_version = version
    else:
        result = github.get_latest_download_url(ml.source.owner, ml.source.repo, ml.source.asset)
        if not result:
            decky.logger.error(f"Could not resolve latest {ml.id} release")
            return False
        resolved_version, url = result

    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.zip")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")
    backed_up = {}

    try:
        decky.logger.info(f"Downloading {ml.name} {resolved_version} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        decky.logger.info(f"Extracting {ml.name}")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(tmp_dir)

        # Verify expected files
        for f in ml.files:
            if not os.path.isfile(os.path.join(tmp_dir, f)):
                raise Exception(f"Expected file missing from zip: {f}")
        for d in ml.dirs:
            if not os.path.isdir(os.path.join(tmp_dir, d)):
                raise Exception(f"Expected directory missing from zip: {d}")

        # Back up existing files
        for f in ml.files:
            dst = os.path.join(install_dir, f)
            if os.path.isfile(dst):
                bak = dst + ".deckhand_bak"
                shutil.copy2(dst, bak)
                backed_up[dst] = bak
        for d in ml.dirs:
            dst = os.path.join(install_dir, d)
            if os.path.isdir(dst):
                bak = dst + ".deckhand_bak"
                shutil.copytree(dst, bak)
                backed_up[dst] = bak

        # Move into game directory
        for f in ml.files:
            src = os.path.join(tmp_dir, f)
            dst = os.path.join(install_dir, f)
            if os.path.isfile(dst):
                os.remove(dst)
            shutil.move(src, dst)
        for d in ml.dirs:
            src = os.path.join(tmp_dir, d)
            dst = os.path.join(install_dir, d)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)

        set_modloader_version(ml.id, resolved_version)

        # Clean up backups on success
        for bak in backed_up.values():
            if os.path.isfile(bak):
                os.remove(bak)
            elif os.path.isdir(bak):
                shutil.rmtree(bak)

        decky.logger.info(f"{ml.name} {resolved_version} installed successfully")
        return True

    except utils.InstallCancelledError:
        decky.logger.info(f"{ml.name} installation was cancelled")
        _rollback(install_dir, backed_up)
        return False
    except Exception as e:
        decky.logger.error(f"{ml.name} installation failed: {e}")
        _rollback(install_dir, backed_up)
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
