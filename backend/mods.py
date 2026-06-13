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


def set_installed_record(
    mod_id: str,
    version: str,
    filename: str,
    paths: list[str] | None = None,
    mod: ModInfo | None = None,
) -> None:
    """Persist an install record. If `mod` is provided, source/meta/install_type are
    extracted from the ModInfo so the record is self-describing — this is what lets
    browsed Thunderstore mods (which aren't in the curated registry) be uninstalled,
    toggled, and update-checked later without needing a curated lookup."""
    store = _load_store()
    record: dict = {"version": version, "filename": filename}
    if paths:
        record["paths"] = paths
    if mod is not None:
        record["source"] = {
            "type": mod.source.type,
            "owner": mod.source.owner,
            "repo": mod.source.repo,
            "asset": mod.source.asset,
            "install_type": mod.source.install_type,
        }
        record["meta"] = {
            "name": mod.name,
            "author": mod.author,
            "description": mod.description,
            "homepage": mod.homepage,
            "thumbnail": mod.thumbnail,
            "modloader": mod.modloader,
            "dependencies": list(mod.dependencies),
        }
        record["install_type"] = mod.source.install_type
    store[mod_id] = record
    _save_store(store)


def get_installed_record(mod_id: str) -> dict | None:
    """Return the full persisted install record for a mod, or None if untracked."""
    return _load_store().get(mod_id)


def clear_installed_record(mod_id: str) -> None:
    store = _load_store()
    if mod_id in store:
        del store[mod_id]
        _save_store(store)


def _mod_target_dirs(mod: ModInfo, mods_path: str, install_dir: str, paths: list[str] | None) -> list[str]:
    """Resolve the directories that hold a zip_dir mod's DLLs on disk."""
    if paths:
        return [os.path.join(install_dir, p) for p in paths]
    return [os.path.join(mods_path, mod.filename)]


_LOVELYIGNORE = ".lovelyignore"


def _folder_mod_enabled(target_dirs: list[str], style: str = "dll") -> bool:
    """Whether a zip_dir folder mod is currently enabled.

    "dll"  (BepInEx): enabled iff at least one *.dll (not *.dll.disabled) exists in its
           tracked dirs — BepInEx only loads files ending in .dll.
    "lovelyignore" (Lovely/Steamodded): Lua mods have no DLLs; Lovely and Steamodded skip
           any mod folder containing a top-level `.lovelyignore` file. Enabled iff the mod
           folder exists and none of its tracked dirs carries that marker.
    """
    if style == "lovelyignore":
        exists = False
        for d in target_dirs:
            if not os.path.isdir(d):
                continue
            exists = True
            if os.path.isfile(os.path.join(d, _LOVELYIGNORE)):
                return False
        return exists
    for d in target_dirs:
        if not os.path.isdir(d):
            continue
        for _root, _dirs, files in os.walk(d):
            if any(f.endswith(".dll") for f in files):
                return True
    return False


def get_installed_mods(game: GameProfile, install_dir: str) -> list[dict]:
    """
    Return installed mods with id, filename, enabled state, version, and meta.
    Source of truth: installed.json (covers multi-location mods like patchers that don't
    live under BepInEx/plugins/, and browsed Thunderstore mods that aren't in the curated
    registry at all). Also scans the filesystem for legacy / manually-placed entries.
    """
    mods_path = resolve_mods_path(game, install_dir)
    toggle_style = game.mod_toggle_style()
    # Bundled frameworks (e.g. Steamodded) install with the modloader and are managed from
    # the Mod Loader tab, so they're never listed as content mods.
    hidden_ids = game.bundled_framework_ids()
    installed = []
    seen_ids: set[str] = set()

    # 1) Tracked installs from installed.json — curated mods (have a game.mods entry)
    store = _load_store()
    for mod in game.mods:
        record = store.get(mod.id)
        if not record:
            continue
        seen_ids.add(mod.id)
        paths = record.get("paths")
        if mod.source.install_type == "zip_dir" or paths:
            enabled = _folder_mod_enabled(_mod_target_dirs(mod, mods_path, install_dir, paths), toggle_style)
        else:
            target = os.path.join(mods_path, mod.filename)
            enabled = os.path.isfile(target)
        installed.append({
            "id": mod.id,
            "filename": mod.filename,
            "enabled": enabled,
            "version": record.get("version"),
            "meta": record.get("meta"),
        })

    # 2) Tracked installs from installed.json — browsed mods (no curated game.mods entry).
    #    The store is keyed only by mod_id and shared across all games, so scope each
    #    browsed mod to THIS game by requiring its files to physically exist under this
    #    game's install dir (enabled or disabled form). Without this, mods installed for
    #    one game leak into every other game's list as "disabled".
    for mod_id, record in store.items():
        if mod_id in seen_ids or mod_id in hidden_ids:
            continue
        filename = record.get("filename")
        if not filename:
            continue
        install_type = record.get("install_type") or (record.get("source") or {}).get("install_type") or "file"
        paths = record.get("paths")
        if install_type == "zip_dir" or paths:
            target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]
            if not any(os.path.exists(d) for d in target_dirs):
                continue  # installed for a different game
            enabled = _folder_mod_enabled(target_dirs, toggle_style)
        else:
            target = os.path.join(mods_path, filename)
            if os.path.isfile(target):
                enabled = True
            elif os.path.isfile(target + ".bak"):
                enabled = False
            else:
                continue  # installed for a different game
        seen_ids.add(mod_id)
        installed.append({
            "id": mod_id,
            "filename": filename,
            "enabled": enabled,
            "version": record.get("version"),
            "meta": record.get("meta"),
        })

    # 3) Filesystem scan for legacy / manually-placed entries we haven't tracked
    if os.path.isdir(mods_path):
        for entry in os.listdir(mods_path):
            entry_path = os.path.join(mods_path, entry)
            if entry.endswith(".dll") or entry.endswith(".dll.bak"):
                enabled = entry.endswith(".dll")
                actual_filename = entry if enabled else entry[:-4]
                mod = game.get_mod_by_filename(actual_filename)
                if mod and mod.id in seen_ids:
                    continue
                mod_id = mod.id if mod else actual_filename
                installed.append({
                    "id": mod_id,
                    "filename": actual_filename,
                    "enabled": enabled,
                    "version": get_installed_version(mod_id),
                    "meta": None,
                })
            elif os.path.isdir(entry_path) and not entry.endswith(".bak"):
                mod = game.get_mod_by_filename(entry)
                if not mod or mod.id in seen_ids:
                    continue
                installed.append({
                    "id": mod.id,
                    "filename": entry,
                    "enabled": True,
                    "version": get_installed_version(mod.id),
                    "meta": None,
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
        return await _install_mod_zip_dir(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_into_game":
        return await _install_mod_zip_into_game(game, install_dir, mod, version, url)
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
        set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
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


async def _install_mod_zip_dir(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a Thunderstore-style zip mod.

    Smart-detects layout:
    - `BepInEx/` at zip root: merge into the game's BepInEx tree (e.g. HookGenPatcher).
    - `plugins/`/`patchers/`/`monomod/`/`core/` at zip root: modern Thunderstore layout —
      same merge but the zip omits the `BepInEx/` prefix.
    - Otherwise: extract as a single folder under BepInEx/plugins/<mod.filename>/.
    """
    import zipfile

    tmp_zip = os.path.join(mods_path, f"{mod.filename}_tmp.zip")
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        with zipfile.ZipFile(tmp_zip, "r") as z:
            members = z.namelist()
            top_level = {m.split("/")[0] for m in members if m and m != "/"}
            top_files = [m for m in members if "/" not in m or not m.split("/")[1]]

        if "BepInEx" in top_level:
            return _extract_to_game_root(install_dir, mod, version, tmp_zip)
        bepinex_subdirs = top_level & {"plugins", "patchers", "monomod", "core"}
        if bepinex_subdirs:
            return _extract_bepinex_subdirs(install_dir, mod, version, tmp_zip, bepinex_subdirs)
        # Bare-DLL layout: no recognized BepInEx folders, but loose .dll files at the
        # zip root (e.g. PaladinMod, BiggerBazaar, Aetherium). Common Thunderstore shape.
        if any(f.lower().endswith(".dll") for f in top_files):
            return _extract_bare_dll(mods_path, mod, version, tmp_zip)
        return _extract_to_mods_folder(mods_path, mod, version, tmp_zip)
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)


def _extract_to_game_root(install_dir: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Extract only the BepInEx/* members of the zip into the game's install dir.
    Records which 2nd-level dirs under BepInEx/ this mod owns, so uninstall can clean up.
    Other top-level zip entries (manifest.json, icon.png, README.md) are skipped to keep the
    game root clean.
    """
    import zipfile
    extracted_dirs = set()
    with zipfile.ZipFile(tmp_zip, "r") as z:
        for member in z.namelist():
            if not member.startswith("BepInEx/"):
                continue
            parts = member.rstrip("/").split("/")
            # parts[0]=='BepInEx', parts[1] is the subdir (patchers/plugins/monomod), parts[2] is the mod-owned dir
            if len(parts) >= 3:
                extracted_dirs.add("/".join(parts[:3]))
            z.extract(member, install_dir)
    set_installed_record(mod.id, version or "latest", mod.filename, paths=sorted(extracted_dirs), mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — merged into BepInEx tree")
    return True


def _extract_bepinex_subdirs(install_dir: str, mod: ModInfo, version: str | None, tmp_zip: str, subdirs: set) -> bool:
    """Thunderstore "modern" layout: zip has plugins/, patchers/, monomod/, or core/ at
    its root. These are BepInEx subdirectories — merge them into the game's BepInEx/
    tree so files land at e.g. BepInEx/plugins/<modname>/<dll>. Stray top-level files
    (manifest.json, icon.png, README.md) are skipped to keep BepInEx clean.
    """
    import zipfile
    bepinex_root = os.path.join(install_dir, "BepInEx")
    extracted_dirs = set()
    with zipfile.ZipFile(tmp_zip, "r") as z:
        for member in z.namelist():
            parts = member.split("/")
            if not parts or parts[0] not in subdirs:
                continue
            # Track ownership of <subdir>/<mod-dir>/ so uninstall can clean up.
            if len(parts) >= 2 and parts[1]:
                extracted_dirs.add(f"BepInEx/{parts[0]}/{parts[1]}")
            z.extract(member, bepinex_root)
    set_installed_record(mod.id, version or "latest", mod.filename, paths=sorted(extracted_dirs), mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — merged into BepInEx tree")
    return True


_THUNDERSTORE_METADATA_FILES = {"manifest.json", "icon.png", "readme.md", "changelog.md", "license", "license.md", "license.txt"}


def _extract_bare_dll(mods_path: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Install a bare-DLL Thunderstore mod: loose .dll/.pdb files at the zip root
    (plus possibly sidecar asset folders) extracted into BepInEx/plugins/<mod.filename>/.
    Thunderstore metadata files (manifest.json, icon.png, README.md, CHANGELOG.md, LICENSE)
    are skipped to keep the plugin folder clean."""
    import zipfile, shutil
    dst_dir = os.path.join(mods_path, mod.filename)

    if os.path.isdir(dst_dir):
        old_version = get_installed_version(mod.id)
        if old_version and old_version != "latest":
            bak = dst_dir + f".v{old_version}.bak"
            shutil.copytree(dst_dir, bak)
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir)

    extracted = 0
    with zipfile.ZipFile(tmp_zip, "r") as z:
        for member in z.namelist():
            if member.endswith("/"):
                continue
            parts = member.split("/")
            top = parts[0]
            # Skip Thunderstore metadata at the zip root
            if len(parts) == 1 and top.lower() in _THUNDERSTORE_METADATA_FILES:
                continue
            z.extract(member, dst_dir)
            extracted += 1

    set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {extracted} files in bare-DLL layout")
    return True


def _extract_to_mods_folder(mods_path: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Extract the zip as a single folder under BepInEx/plugins/<mod.filename>/.
    Backs up the existing folder if one is present.
    """
    import zipfile, shutil
    dst_dir = os.path.join(mods_path, mod.filename)

    if os.path.isdir(dst_dir):
        old_version = get_installed_version(mod.id)
        if old_version and old_version != "latest":
            bak = dst_dir + f".v{old_version}.bak"
            shutil.copytree(dst_dir, bak)
        shutil.rmtree(dst_dir)

    with zipfile.ZipFile(tmp_zip, "r") as z:
        members = z.namelist()
        top_dirs = {m.split("/")[0] for m in members if m.split("/")[0]}
        if len(top_dirs) == 1:
            tmp_extract = dst_dir + "_extract"
            z.extractall(tmp_extract)
            extracted = os.path.join(tmp_extract, next(iter(top_dirs)))
            shutil.move(extracted, dst_dir)
            shutil.rmtree(tmp_extract)
        else:
            os.makedirs(dst_dir)
            z.extractall(dst_dir)

    set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
    return True


async def _install_mod_zip_into_game(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """
    Install a zip mod by extracting a named inner folder's contents into install_dir.
    Used for BepInExPack which has BepInExPack/<files> and we want <files> in the game root.
    """
    import zipfile, shutil
    tmp_zip = os.path.join(install_dir, f"{mod.filename}_tmp.zip")
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        with zipfile.ZipFile(tmp_zip, "r") as z:
            members = z.namelist()
            # Find the inner folder (e.g. "BepInExPack/")
            top_dirs = set(m.split("/")[0] for m in members if "/" in m)
            inner_folder = mod.filename + "/"  # e.g. "BepInExPack/"

            # Find matching inner folder, fall back to first dir
            target = inner_folder if any(m.startswith(inner_folder) for m in members) else (list(top_dirs)[0] + "/" if top_dirs else "")

            tmp_dir = os.path.join(install_dir, f"{mod.filename}_extract")
            if os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir)
            os.makedirs(tmp_dir)
            z.extractall(tmp_dir)

            inner_path = os.path.join(tmp_dir, target.rstrip("/")) if target else tmp_dir

            # Copy contents of inner folder into install_dir
            if os.path.isdir(inner_path):
                for item in os.listdir(inner_path):
                    src = os.path.join(inner_path, item)
                    dst = os.path.join(install_dir, item)
                    if os.path.isdir(src):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
            else:
                # No inner folder, extract everything to install_dir
                for item in os.listdir(tmp_dir):
                    src = os.path.join(tmp_dir, item)
                    dst = os.path.join(install_dir, item)
                    if os.path.isdir(src):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)

        set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) into game dir")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)
        tmp_dir = os.path.join(install_dir, f"{mod.filename}_extract")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)


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
    Handles file-based, folder-based, and multi-location (paths-tracked) mods.
    Removes all versioned backups too. Browsed Thunderstore mods that aren't in the
    curated registry are uninstalled using the persisted record in installed.json.
    """
    import shutil
    mod = game.get_mod(mod_id)
    mods_path = resolve_mods_path(game, install_dir)
    store = _load_store()
    record = store.get(mod_id, {})
    filename = mod.filename if mod else record.get("filename", mod_id)
    paths = record.get("paths")
    install_type = (
        mod.source.install_type if mod
        else record.get("install_type") or (record.get("source") or {}).get("install_type")
    )
    is_dir_mod = install_type == "zip_dir"
    try:
        if paths:
            # Multi-location install (e.g. BepInEx patcher) — clean each tracked path
            for relpath in paths:
                full = os.path.join(install_dir, relpath)
                if os.path.isdir(full):
                    shutil.rmtree(full)
                    decky.logger.info(f"Removed {relpath}")
                elif os.path.isfile(full):
                    os.remove(full)
                    decky.logger.info(f"Removed {relpath}")
            # Also clean a legacy mods_path/<filename> folder if one was left from a previous install
            legacy = os.path.join(mods_path, filename)
            if os.path.isdir(legacy):
                shutil.rmtree(legacy)
                decky.logger.info(f"Removed legacy {filename}/")
            clear_installed_record(mod_id)
            return True
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


def _toggle_lovelyignore(target_dirs: list[str], mod_id: str, filename: str, enable: bool) -> bool:
    """Enable/disable a Lovely/Steamodded Lua mod by removing/creating a `.lovelyignore`
    marker in each of the mod's folders. Returns False if no mod folder was found."""
    touched = 0
    try:
        for d in target_dirs:
            if not os.path.isdir(d):
                continue
            touched += 1
            marker = os.path.join(d, _LOVELYIGNORE)
            if enable:
                if os.path.isfile(marker):
                    os.remove(marker)
            elif not os.path.isfile(marker):
                with open(marker, "w"):
                    pass
        if touched == 0:
            decky.logger.warning(f"No mod folder to {'enable' if enable else 'disable'} for {mod_id}")
            return False
        decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} (.lovelyignore)")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to toggle {mod_id}: {e}")
        return False


async def toggle_mod(game: GameProfile, install_dir: str, mod_id: str, enable: bool) -> bool:
    """Enable or disable a mod.

    File-based mods: renames the DLL between `<name>` and `<name>.bak`.
    Folder-based (zip_dir) mods, "dll" style (BepInEx): walks the mod's tracked dirs and
      renames every `*.dll` ↔ `*.dll.disabled`. BepInEx's plugin scanner only matches
      `*.dll`, so the renamed files are skipped on next launch.
    Folder-based (zip_dir) mods, "lovelyignore" style (Lovely/Steamodded): Lua mods have no
      DLLs, so disabling drops a `.lovelyignore` marker in the mod folder (and enabling
      removes it). Both Lovely and Steamodded skip any folder containing that file.
    Takes effect on next game launch — modloaders scan once at startup.
    Browsed mods (no curated ModInfo) use the persisted record.
    """
    mod = game.get_mod(mod_id)
    mods_path = resolve_mods_path(game, install_dir)
    store = _load_store()
    record = store.get(mod_id, {})
    install_type = (
        mod.source.install_type if mod
        else record.get("install_type") or (record.get("source") or {}).get("install_type")
    )
    filename = mod.filename if mod else record.get("filename", mod_id)

    if install_type == "zip_dir":
        paths = record.get("paths")
        if mod:
            target_dirs = _mod_target_dirs(mod, mods_path, install_dir, paths)
        else:
            target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]

        if game.mod_toggle_style() == "lovelyignore":
            return _toggle_lovelyignore(target_dirs, mod_id, filename, enable)

        renamed = 0
        try:
            for d in target_dirs:
                if not os.path.isdir(d):
                    continue
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        if enable and f.endswith(".dll.disabled"):
                            os.rename(os.path.join(root, f), os.path.join(root, f[:-len(".disabled")]))
                            renamed += 1
                        elif not enable and f.endswith(".dll"):
                            os.rename(os.path.join(root, f), os.path.join(root, f + ".disabled"))
                            renamed += 1
            if renamed == 0:
                decky.logger.warning(f"No DLLs to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({renamed} dll{'s' if renamed != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

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