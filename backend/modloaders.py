import os
import ssl
import shutil
import zipfile
import tempfile
import threading
import urllib.request
import decky
import steam
from games import GameProfile

# System CA bundle path on Steam Deck (SteamOS/Arch-based)
_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

# Cancel flag — set this to abort an in-progress install
_cancel_event = threading.Event()


def cancel_install() -> None:
    """Signal any in-progress install to cancel."""
    _cancel_event.set()


def _make_ssl_context() -> ssl.SSLContext:
    """Create an SSL context using the system CA bundle."""
    ctx = ssl.create_default_context()
    if os.path.isfile(_CA_BUNDLE):
        ctx = ssl.create_default_context(cafile=_CA_BUNDLE)
    return ctx


def _download(url: str, dest: str, appid: int) -> None:
    """
    Download a URL to a file with progress reporting and cancellation support.
    Emits 'install_progress' events (0-100) to the frontend.
    Raises Exception if cancelled.
    """
    _cancel_event.clear()
    ctx = _make_ssl_context()
    chunk_size = 65536  # 64KB chunks

    with urllib.request.urlopen(url, context=ctx) as response:
        total = int(response.headers.get('Content-Length', 0))
        downloaded = 0
        with open(dest, 'wb') as f:
            while True:
                if _cancel_event.is_set():
                    raise Exception("Installation cancelled by user")
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    percent = int(downloaded * 100 / total)
                    decky.emit('install_progress', appid, percent)


# Maps modloader type to the folder/file that indicates it's installed
MODLOADER_INDICATORS = {
    "melonloader": "MelonLoader",
    "lovely": "version.dll",
}

MODLOADER_URLS = {
    "melonloader": "https://github.com/LavaGang/MelonLoader/releases/download/v0.7.3/MelonLoader.x64.zip",
    "lovely": "https://github.com/ethangreen-dev/lovely-injector/releases/latest/download/lovely-x86_64-pc-windows-msvc.zip",
}

MELONLOADER_LAUNCH_OPTION = 'WINEDLLOVERRIDES="version=n,b" %command%'

# Files/folders MelonLoader extracts into the game directory
MELONLOADER_FILES = ["version.dll"]
MELONLOADER_DIRS = ["MelonLoader"]


def is_modloader_installed(game: GameProfile, install_dir: str) -> bool:
    """Returns True if modloader is installed (enabled or disabled)."""
    indicator = MODLOADER_INDICATORS.get(game.modloader)
    if not indicator:
        return False
    active = os.path.exists(os.path.join(install_dir, indicator))
    disabled = os.path.exists(os.path.join(install_dir, indicator + ".disabled"))
    return active or disabled


def is_modloader_enabled(game: GameProfile, install_dir: str) -> bool:
    """Returns True if modloader is installed and currently enabled."""
    indicator = MODLOADER_INDICATORS.get(game.modloader)
    if not indicator:
        return False
    return os.path.exists(os.path.join(install_dir, indicator))


def is_modloader_ready(game: GameProfile, install_dir: str) -> bool:
    """
    Returns True if the modloader has completed its first-run setup and is
    ready for mods to be installed. For MelonLoader, this means the game has
    been launched once and Il2CppAssemblies have been generated.
    """
    if game.modloader == "melonloader":
        return os.path.isdir(os.path.join(install_dir, "MelonLoader", "Il2CppAssemblies"))
    # Other modloaders are assumed ready once installed
    return is_modloader_installed(game, install_dir)


async def disable_modloader(game: GameProfile, install_dir: str) -> bool:
    """Disable modloader by renaming its files/folders to .disabled."""
    try:
        for filename in MELONLOADER_FILES:
            src = os.path.join(install_dir, filename)
            dst = src + ".disabled"
            if os.path.isfile(src):
                os.rename(src, dst)
        for dirname in MELONLOADER_DIRS:
            src = os.path.join(install_dir, dirname)
            dst = src + ".disabled"
            if os.path.isdir(src):
                os.rename(src, dst)
        decky.logger.info(f"Disabled {game.modloader}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to disable {game.modloader}: {e}")
        return False


async def enable_modloader(game: GameProfile, install_dir: str) -> bool:
    """Re-enable modloader by renaming .disabled files/folders back."""
    try:
        for filename in MELONLOADER_FILES:
            src = os.path.join(install_dir, filename + ".disabled")
            dst = os.path.join(install_dir, filename)
            if os.path.isfile(src):
                os.rename(src, dst)
        for dirname in MELONLOADER_DIRS:
            src = os.path.join(install_dir, dirname + ".disabled")
            dst = os.path.join(install_dir, dirname)
            if os.path.isdir(src):
                os.rename(src, dst)
        decky.logger.info(f"Enabled {game.modloader}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to enable {game.modloader}: {e}")
        return False


async def install_modloader(game: GameProfile, install_dir: str) -> bool:
    """Download and install the appropriate modloader for a game."""
    try:
        if game.modloader == "melonloader":
            return await _install_melonloader(install_dir, game.appid)
        elif game.modloader == "lovely":
            return await _install_lovely(install_dir, game.appid)
        else:
            decky.logger.error(f"Unknown modloader: {game.modloader}")
            return False
    except Exception as e:
        decky.logger.error(f"Failed to install {game.modloader}: {e}")
        return False


async def uninstall_modloader(game: GameProfile, install_dir: str) -> bool:
    """Remove the modloader from a game's install directory (handles both enabled and disabled state)."""
    bak = os.path.join(install_dir, "version.dll.deckhand_bak")
    removed = []
    try:
        for filename in MELONLOADER_FILES:
            for candidate in [filename, filename + ".disabled"]:
                path = os.path.join(install_dir, candidate)
                if os.path.isfile(path):
                    os.remove(path)
                    removed.append(('file', path))
        for dirname in MELONLOADER_DIRS:
            for candidate in [dirname, dirname + ".disabled"]:
                path = os.path.join(install_dir, candidate)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    removed.append(('dir', path))
        # Restore backed up version.dll if it exists
        if os.path.isfile(bak):
            os.rename(bak, os.path.join(install_dir, "version.dll"))
        decky.logger.info(f"Uninstalled {game.modloader} from {install_dir}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {game.modloader}: {e}")
        return False


async def _install_melonloader(install_dir: str, appid: int) -> bool:
    """
    Download and install MelonLoader into the game directory with full rollback on failure.

    Steps:
      1. Download zip to a tmp file
      2. Extract to a temp directory
      3. Verify expected files exist
      4. Back up existing version.dll and MelonLoader/ if present
      5. Move files into the game directory
      6. Set the Steam launch option
      7. On any failure: roll back all changes
    """
    url = MODLOADER_URLS["melonloader"]
    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "melonloader_tmp.zip")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "melonloader_extract")
    backed_up = {}  # maps original path -> backup path

    try:
        # Step 1: Download
        decky.logger.info(f"Downloading MelonLoader from {url}")
        _download(url, tmp_zip, appid)

        # Step 2: Extract to temp dir
        decky.logger.info("Extracting MelonLoader to temp directory")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(tmp_dir)

        # Step 3: Verify expected files exist in extracted output
        for filename in MELONLOADER_FILES:
            if not os.path.isfile(os.path.join(tmp_dir, filename)):
                raise Exception(f"Expected file missing from zip: {filename}")
        for dirname in MELONLOADER_DIRS:
            if not os.path.isdir(os.path.join(tmp_dir, dirname)):
                raise Exception(f"Expected directory missing from zip: {dirname}")

        # Step 4: Back up existing files
        for filename in MELONLOADER_FILES:
            dst = os.path.join(install_dir, filename)
            if os.path.isfile(dst):
                bak = dst + ".deckhand_bak"
                shutil.copy2(dst, bak)
                backed_up[dst] = bak
                decky.logger.info(f"Backed up {filename}")
        for dirname in MELONLOADER_DIRS:
            dst = os.path.join(install_dir, dirname)
            if os.path.isdir(dst):
                bak = dst + ".deckhand_bak"
                shutil.copytree(dst, bak)
                backed_up[dst] = bak
                decky.logger.info(f"Backed up {dirname}/")

        # Step 5: Move files into game directory
        decky.logger.info("Moving MelonLoader files into game directory")
        for filename in MELONLOADER_FILES:
            src = os.path.join(tmp_dir, filename)
            dst = os.path.join(install_dir, filename)
            if os.path.isfile(dst):
                os.remove(dst)
            shutil.move(src, dst)
        for dirname in MELONLOADER_DIRS:
            src = os.path.join(tmp_dir, dirname)
            dst = os.path.join(install_dir, dirname)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)

        # Step 6: Set launch option
        decky.logger.info("Setting Steam launch option")
        if not steam.set_launch_options(appid, MELONLOADER_LAUNCH_OPTION):
            raise Exception("Failed to set Steam launch option")

        # Clean up backups on success
        for bak in backed_up.values():
            if os.path.isfile(bak):
                os.remove(bak)
            elif os.path.isdir(bak):
                shutil.rmtree(bak)

        decky.logger.info("MelonLoader installed successfully")
        return True

    except Exception as e:
        decky.logger.error(f"MelonLoader installation failed: {e} — rolling back")
        _rollback_melonloader(install_dir, backed_up)
        return False

    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)


def _rollback_melonloader(install_dir: str, backed_up: dict) -> None:
    """Remove any installed files and restore backups."""
    try:
        # Remove anything we moved in
        for filename in MELONLOADER_FILES:
            dst = os.path.join(install_dir, filename)
            if os.path.isfile(dst) and dst not in backed_up:
                os.remove(dst)
        for dirname in MELONLOADER_DIRS:
            dst = os.path.join(install_dir, dirname)
            if os.path.isdir(dst) and dst not in backed_up:
                shutil.rmtree(dst)
        # Restore backups
        for original, bak in backed_up.items():
            if os.path.isfile(bak):
                if os.path.isfile(original):
                    os.remove(original)
                shutil.move(bak, original)
            elif os.path.isdir(bak):
                if os.path.isdir(original):
                    shutil.rmtree(original)
                shutil.move(bak, original)
        decky.logger.info("Rollback complete")
    except Exception as e:
        decky.logger.error(f"Rollback failed: {e}")


async def _install_lovely(install_dir: str, appid: int) -> bool:
    """Download and extract the Lovely injector into the game directory."""
    url = MODLOADER_URLS["lovely"]
    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "lovely_tmp.zip")
    try:
        decky.logger.info(f"Downloading Lovely from {url}")
        _download(url, tmp_zip, appid)
        decky.logger.info("Extracting Lovely")
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(install_dir)
        decky.logger.info("Lovely installed successfully")
        return True
    except Exception as e:
        decky.logger.error(f"Lovely installation failed: {e}")
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)