import os
import json
import decky
from registry import GameProfile, ModInfo
import utils

_INSTALLED_STORE = None


def _get_store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _load_store() -> dict:
    """Load the installed mods store from disk. Structure: {mod_id: {version, filename, enabled}}"""
    global _INSTALLED_STORE
    if _INSTALLED_STORE is not None:
        return _INSTALLED_STORE
    path = _get_store_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                data = json.load(f)
                _INSTALLED_STORE = data.get("mods", {})
                return _INSTALLED_STORE
    except Exception as e:
        decky.logger.error(f"Failed to load installed store: {e}")
    _INSTALLED_STORE = {}
    return _INSTALLED_STORE


def _save_store(store: dict) -> None:
    """Save the installed mods store to disk atomically."""
    global _INSTALLED_STORE
    _INSTALLED_STORE = store
    path = _get_store_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Read full file first to preserve modloaders section
        full = {}
        if os.path.isfile(path):
            with open(path, "r") as f:
                full = json.load(f)
        full["mods"] = store
        with open(tmp, "w") as f:
            json.dump(full, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        decky.logger.error(f"Failed to save installed store: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)


def get_installed_version(mod_id: str) -> str | None:
    store = _load_store()
    return store.get(mod_id, {}).get("version")


def set_installed_record(mod_id: str, version: str, filename: str) -> None:
    store = _load_store()
    store[mod_id] = {"version": version, "filename": filename}
    _save_store(store)


def clear_installed_record(mod_id: str) -> None:
    store = _load_store()
    if mod_id in store:
        del store[mod_id]
        _save_store(store)


def get_installed_mods(game: GameProfile, install_dir: str) -> list[dict]:
    """
    Return installed mods with id, filename, enabled state, and version.
    Scans the mods directory and cross-references with the store for version info.
    """
    mods_path = os.path.join(install_dir, game.mods_dir)
    installed = []
    if not os.path.isdir(mods_path):
        return installed

    for filename in os.listdir(mods_path):
        if filename.endswith(".dll") or filename.endswith(".dll.bak"):
            enabled = filename.endswith(".dll")
            actual_filename = filename if enabled else filename[:-4]
            # Look up mod info by filename
            mod = game.get_mod_by_filename(actual_filename)
            mod_id = mod.id if mod else actual_filename
            installed.append({
                "id": mod_id,
                "filename": actual_filename,
                "enabled": enabled,
                "version": get_installed_version(mod_id),
            })

    return installed


async def install_mod(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None = None, url: str | None = None) -> bool | None:
    """
    Download and install a mod DLL into the game's mods directory.
    Backs up the previous version as Mod.dll.vX.Y.Z.bak before replacing.
    Returns True=success, False=failed, None=cancelled.
    """
    mods_path = os.path.join(install_dir, game.mods_dir)
    os.makedirs(mods_path, exist_ok=True)
    dst = os.path.join(mods_path, mod.filename)
    tmp = dst + ".tmp"
    download_url = url
    backed_up = None
    try:
        decky.logger.info(f"Downloading {mod.name} from {download_url}")
        await utils.download(download_url, tmp, game.appid)

        # Back up existing version before replacing
        if os.path.isfile(dst):
            old_version = get_installed_version(mod.id)
            if old_version and old_version != "latest":
                bak = os.path.join(mods_path, f"{mod.filename}.v{old_version}.bak")
                os.rename(dst, bak)
                backed_up = bak
                decky.logger.info(f"Backed up {mod.filename} as {os.path.basename(bak)}")
            else:
                os.remove(dst)

        os.replace(tmp, dst)
        set_installed_record(mod.id, version or "latest", mod.filename)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        if os.path.exists(tmp):
            os.remove(tmp)
        if backed_up and os.path.isfile(backed_up) and not os.path.isfile(dst):
            os.rename(backed_up, dst)
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        if backed_up and os.path.isfile(backed_up) and not os.path.isfile(dst):
            os.rename(backed_up, dst)
        return False


def get_backed_up_versions(game: GameProfile, install_dir: str, mod_id: str) -> list[str]:
    """Return a list of previously installed versions backed up on disk."""
    mod = game.get_mod(mod_id)
    if not mod:
        return []
    mods_path = os.path.join(install_dir, game.mods_dir)
    if not os.path.isdir(mods_path):
        return []
    prefix = f"{mod.filename}.v"
    suffix = ".bak"
    versions = [
        f[len(prefix):-len(suffix)]
        for f in os.listdir(mods_path)
        if f.startswith(prefix) and f.endswith(suffix)
    ]
    return sorted(versions, reverse=True)


def delete_mod_version(game: GameProfile, install_dir: str, mod_id: str, version: str) -> bool:
    """Delete a specific backed-up version of a mod (.vX.Y.Z.bak file)."""
    mod = game.get_mod(mod_id)
    if not mod:
        return False
    mods_path = os.path.join(install_dir, game.mods_dir)
    bak_path = os.path.join(mods_path, f"{mod.filename}.v{version}.bak")
    try:
        if os.path.isfile(bak_path):
            os.remove(bak_path)
            decky.logger.info(f"Deleted backup {mod.filename} v{version}")
            return True
        decky.logger.warning(f"Backup not found: {bak_path}")
        return False
    except Exception as e:
        decky.logger.error(f"Failed to delete backup {mod.filename} v{version}: {e}")
        return False


async def uninstall_mod(game: GameProfile, install_dir: str, mod_id: str) -> bool:
    """
    Remove a mod from the mods directory.
    Removes the active .dll, toggle .bak, and all versioned backups.
    """
    mod = game.get_mod(mod_id)
    filename = mod.filename if mod else mod_id
    mods_path = os.path.join(install_dir, game.mods_dir)
    try:
        for candidate in [filename, filename + ".bak"]:
            path = os.path.join(mods_path, candidate)
            if os.path.exists(path):
                os.remove(path)
                decky.logger.info(f"Removed {candidate}")
        # Remove all versioned backups
        prefix = f"{filename}.v"
        suffix = ".bak"
        for f in os.listdir(mods_path):
            if f.startswith(prefix) and f.endswith(suffix):
                os.remove(os.path.join(mods_path, f))
                decky.logger.info(f"Removed backup {f}")
        clear_installed_record(mod_id)
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {mod_id}: {e}")
        return False


async def toggle_mod(game: GameProfile, install_dir: str, mod_id: str, enable: bool) -> bool:
    """Enable or disable a mod by renaming its DLL."""
    mod = game.get_mod(mod_id)
    filename = mod.filename if mod else mod_id
    mods_path = os.path.join(install_dir, game.mods_dir)
    try:
        if enable:
            src = os.path.join(mods_path, filename + ".bak")
            dst = os.path.join(mods_path, filename)
        else:
            src = os.path.join(mods_path, filename)
            dst = os.path.join(mods_path, filename + ".bak")
        if not os.path.exists(src):
            decky.logger.error(f"Source file not found: {src}")
            return False
        os.rename(src, dst)
        decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to toggle {mod_id}: {e}")
        return False