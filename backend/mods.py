import os
import ssl
import json
import urllib.request
import decky
from games import GameProfile, ModInfo

_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
_VERSION_STORE = None


def _get_version_store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed_versions.json")


def _load_version_store() -> dict:
    """Load the installed mod versions from disk."""
    global _VERSION_STORE
    if _VERSION_STORE is not None:
        return _VERSION_STORE
    path = _get_version_store_path()
    try:
        if os.path.isfile(path):
            with open(path, "r") as f:
                _VERSION_STORE = json.load(f)
                return _VERSION_STORE
    except Exception as e:
        decky.logger.error(f"Failed to load version store: {e}")
    _VERSION_STORE = {}
    return _VERSION_STORE


def _save_version_store(store: dict) -> None:
    """Save the installed mod versions to disk atomically."""
    global _VERSION_STORE
    _VERSION_STORE = store
    path = _get_version_store_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(store, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        decky.logger.error(f"Failed to save version store: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)


def get_installed_version(filename: str) -> str | None:
    """Get the installed version of a mod by filename."""
    store = _load_version_store()
    return store.get(filename, {}).get("version")


def set_installed_version(filename: str, version: str, url: str) -> None:
    """Record the installed version of a mod."""
    store = _load_version_store()
    store[filename] = {"version": version, "url": url}
    _save_version_store(store)


def clear_installed_version(filename: str) -> None:
    """Remove the installed version record for a mod."""
    store = _load_version_store()
    if filename in store:
        del store[filename]
        _save_version_store(store)


def _download(url: str, dest: str) -> None:
    """Download a URL to a file using the system CA bundle for SSL verification."""
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    req = urllib.request.Request(url, headers={"User-Agent": "DeckyModManager/1.0"})
    with urllib.request.urlopen(req, context=ctx) as response:
        with open(dest, 'wb') as f:
            f.write(response.read())


def get_installed_mods(game: GameProfile, install_dir: str) -> list[dict]:
    """Return a list of installed mods with their enabled/disabled state and version."""
    mods_path = os.path.join(install_dir, game.mods_dir)
    installed = []
    if not os.path.isdir(mods_path):
        return installed
    for filename in os.listdir(mods_path):
        if filename.endswith(".dll"):
            installed.append({
                "filename": filename,
                "enabled": True,
                "version": get_installed_version(filename),
            })
        elif filename.endswith(".dll.bak"):
            bare = filename[:-4]
            installed.append({
                "filename": bare,
                "enabled": False,
                "version": get_installed_version(bare),
            })
    return installed


def delete_mod_version(game: GameProfile, install_dir: str, filename: str, version: str) -> bool:
    """Delete a specific backed-up version of a mod (.vX.Y.Z.bak file)."""
    mods_path = os.path.join(install_dir, game.mods_dir)
    bak_path = os.path.join(mods_path, f"{filename}.v{version}.bak")
    try:
        if os.path.isfile(bak_path):
            os.remove(bak_path)
            decky.logger.info(f"Deleted backup {filename} v{version}")
            return True
        decky.logger.warning(f"Backup not found: {bak_path}")
        return False
    except Exception as e:
        decky.logger.error(f"Failed to delete backup {filename} v{version}: {e}")
        return False


async def install_mod(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None = None, url: str | None = None) -> bool:
    """
    Download and install a mod DLL into the game's mods directory.
    If a previous version is installed, backs it up as Mod.dll.vX.Y.Z.bak.
    If version/url are provided, use them; otherwise use the mod's default URL.
    """
    mods_path = os.path.join(install_dir, game.mods_dir)
    os.makedirs(mods_path, exist_ok=True)
    dst = os.path.join(mods_path, mod.filename)
    tmp = dst + ".tmp"
    download_url = url or mod.url
    backed_up = None
    try:
        decky.logger.info(f"Downloading {mod.name} from {download_url}")
        _download(download_url, tmp)

        # Back up existing version before replacing
        if os.path.isfile(dst):
            old_version = get_installed_version(mod.filename)
            if old_version and old_version != "latest":
                bak = os.path.join(mods_path, f"{mod.filename}.v{old_version}.bak")
                os.rename(dst, bak)
                backed_up = bak
                decky.logger.info(f"Backed up {mod.filename} as {os.path.basename(bak)}")
            else:
                os.remove(dst)

        os.replace(tmp, dst)
        set_installed_version(mod.filename, version or "latest", download_url)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        # Restore backup if we moved it
        if backed_up and os.path.isfile(backed_up) and not os.path.isfile(dst):
            os.rename(backed_up, dst)
        return False


def get_backed_up_versions(game: GameProfile, install_dir: str, filename: str) -> list[str]:
    """Return a list of previously installed versions backed up on disk."""
    mods_path = os.path.join(install_dir, game.mods_dir)
    versions = []
    if not os.path.isdir(mods_path):
        return versions
    prefix = f"{filename}.v"
    suffix = ".bak"
    for f in os.listdir(mods_path):
        if f.startswith(prefix) and f.endswith(suffix):
            version = f[len(prefix):-len(suffix)]
            versions.append(version)
    return sorted(versions, reverse=True)


async def uninstall_mod(game: GameProfile, install_dir: str, filename: str) -> bool:
    """
    Remove a mod DLL from the mods directory.
    Removes the active .dll, toggle .bak, and all versioned backups (.vX.Y.Z.bak).
    """
    mods_path = os.path.join(install_dir, game.mods_dir)
    try:
        # Remove active and toggle-disabled versions
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
                path = os.path.join(mods_path, f)
                os.remove(path)
                decky.logger.info(f"Removed backup {f}")
        clear_installed_version(filename)
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {filename}: {e}")
        return False


async def toggle_mod(game: GameProfile, install_dir: str, filename: str, enable: bool) -> bool:
    """Enable or disable a mod by renaming its DLL."""
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
        decky.logger.error(f"Failed to toggle {filename}: {e}")
        return False