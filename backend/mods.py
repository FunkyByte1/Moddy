import os
import json
import decky
from registry import GameProfile, ModInfo
import steam
import utils


def resolve_mods_path(game: GameProfile, install_dir: str) -> str:
    """Resolve the absolute path to the mods directory for a game."""
    if game.mods_dir_type == "proton_appdata":
        base = steam.get_proton_appdata_path(game.appid, game.mods_appdata_path)
        return os.path.join(base, game.mods_dir)
    return os.path.join(install_dir, game.mods_dir)

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
    Handles both file-based (.dll) and folder-based mods.
    """
    mods_path = resolve_mods_path(game, install_dir)
    installed = []
    if not os.path.isdir(mods_path):
        return installed

    for entry in os.listdir(mods_path):
        entry_path = os.path.join(mods_path, entry)

        # File-based mods (.dll)
        if entry.endswith(".dll") or entry.endswith(".dll.bak"):
            enabled = entry.endswith(".dll")
            actual_filename = entry if enabled else entry[:-4]
            mod = game.get_mod_by_filename(actual_filename)
            mod_id = mod.id if mod else actual_filename
            installed.append({
                "id": mod_id,
                "filename": actual_filename,
                "enabled": enabled,
                "version": get_installed_version(mod_id),
            })

        # Folder-based mods (zip_dir install type)
        elif os.path.isdir(entry_path) and not entry.endswith(".bak"):
            mod = game.get_mod_by_filename(entry)
            if mod:
                installed.append({
                    "id": mod.id,
                    "filename": entry,
                    "enabled": True,  # folders are always enabled
                    "version": get_installed_version(mod.id),
                })

    return installed


async def install_mod(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None = None, url: str | None = None) -> bool | None:
    """
    Download and install a mod into the game's mods directory.
    Supports two install types:
    - "file": single DLL, backs up previous version as Mod.dll.vX.Y.Z.bak
    - "zip_dir": extracts zip as a folder into the mods directory
    Returns True=success, False=failed, None=cancelled.
    """
    mods_path = resolve_mods_path(game, install_dir)
    os.makedirs(mods_path, exist_ok=True)

    if mod.source.install_type == "zip_dir":
        return await _install_mod_zip_dir(game, mods_path, mod, version, url)
    return await _install_mod_file(game, mods_path, mod, version, url)


async def _install_mod_file(game: GameProfile, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a single-file mod (DLL), backing up the previous version."""
    dst = os.path.join(mods_path, mod.filename)
    tmp = dst + ".tmp"
    backed_up = None
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp, game.appid)

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


async def _install_mod_zip_dir(game: GameProfile, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a zip-based mod by extracting it as a folder into the mods directory."""
    import zipfile, shutil
    tmp_zip = os.path.join(mods_path, f"{mod.filename}_tmp.zip")
    dst_dir = os.path.join(mods_path, mod.filename)
    backed_up = None
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        # Back up existing folder
        if os.path.isdir(dst_dir):
            old_version = get_installed_version(mod.id)
            if old_version and old_version != "latest":
                bak = dst_dir + f".v{old_version}.bak"
                shutil.copytree(dst_dir, bak)
                backed_up = bak
            shutil.rmtree(dst_dir)

        # Extract zip — look for a single top-level folder inside the zip
        with zipfile.ZipFile(tmp_zip, "r") as z:
            members = z.namelist()
            top_dirs = set(m.split("/")[0] for m in members if m.split("/")[0])
            if len(top_dirs) == 1:
                # Extract to a temp dir then rename to mod.filename
                tmp_dir = dst_dir + "_extract"
                z.extractall(tmp_dir)
                extracted = os.path.join(tmp_dir, list(top_dirs)[0])
                shutil.move(extracted, dst_dir)
                shutil.rmtree(tmp_dir)
            else:
                # Extract directly into a folder named mod.filename
                os.makedirs(dst_dir)
                z.extractall(dst_dir)

        set_installed_record(mod.id, version or "latest", mod.filename)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        if os.path.exists(tmp_zip): os.remove(tmp_zip)
        if os.path.isdir(dst_dir): shutil.rmtree(dst_dir)
        if backed_up and os.path.isdir(backed_up): shutil.move(backed_up, dst_dir)
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        if os.path.exists(tmp_zip): os.remove(tmp_zip)
        if os.path.isdir(dst_dir): shutil.rmtree(dst_dir)
        if backed_up and os.path.isdir(backed_up): shutil.move(backed_up, dst_dir)
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)


def get_backed_up_versions(game: GameProfile, install_dir: str, mod_id: str) -> list[str]:
    """Return a list of previously installed versions backed up on disk."""
    mod = game.get_mod(mod_id)
    if not mod:
        return []
    mods_path = resolve_mods_path(game, install_dir)
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
    mods_path = resolve_mods_path(game, install_dir)
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
    Handles both file-based and folder-based mods.
    Removes all versioned backups too.
    """
    import shutil
    mod = game.get_mod(mod_id)
    filename = mod.filename if mod else mod_id
    mods_path = resolve_mods_path(game, install_dir)
    is_dir_mod = mod and mod.source.install_type == "zip_dir"
    try:
        if is_dir_mod:
            # Remove folder and any backed-up versions
            dst = os.path.join(mods_path, filename)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
                decky.logger.info(f"Removed {filename}/")
            # Remove versioned backups
            for entry in os.listdir(mods_path):
                if entry.startswith(f"{filename}.v") and entry.endswith(".bak") and os.path.isdir(os.path.join(mods_path, entry)):
                    shutil.rmtree(os.path.join(mods_path, entry))
                    decky.logger.info(f"Removed backup {entry}")
        else:
            for candidate in [filename, filename + ".bak"]:
                path = os.path.join(mods_path, candidate)
                if os.path.exists(path):
                    os.remove(path)
                    decky.logger.info(f"Removed {candidate}")
            # Remove versioned backups
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
    """Enable or disable a mod by renaming its DLL. Folder-based mods cannot be toggled."""
    mod = game.get_mod(mod_id)
    if mod and mod.source.install_type == "zip_dir":
        decky.logger.warning(f"Cannot toggle folder-based mod {mod_id}")
        return False
    filename = mod.filename if mod else mod_id
    mods_path = resolve_mods_path(game, install_dir)
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