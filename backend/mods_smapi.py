import os
import mods
import mods_common
import mods_archive
from registry import ModInfo, GameProfile
import decky
import utils
from install_txn import _StagedInstall


def _smapi_commit(install_dir: str, mods_path: str, extract_root: str, staging: str,
                  mod: ModInfo, version: str | None, old_paths: list) -> bool:
    """Place every SMAPI mod folder found anywhere under `extract_root` into Mods/, transactionally.

    Shared by the single-archive (`_install_mod_zip_smapi`) and combined multi-file
    (`install_smapi_files`) paths — `extract_root` may hold one extracted archive or several (each in
    its own subdir). Finds every manifest.json, keeps only the top-most folders (a manifest nested
    inside another mod's folder is a bundled content pack that ships with its parent — placing it
    separately would duplicate it), stages each top folder verbatim, retires the previous install,
    and commits all-or-nothing. Returns False (and places nothing) if no manifest is found. Each mod
    folder keeps its own name; a manifest at an extract ROOT (no containing folder) is wrapped under a
    folder named after the mod."""
    import shutil
    extract_root = os.path.normpath(extract_root)
    manifest_dirs: list[str] = []
    for root, _dirs, files in os.walk(extract_root):
        if any(f.lower() == "manifest.json" for f in files):
            manifest_dirs.append(os.path.normpath(root))
    roots = [
        d for d in manifest_dirs
        if not any(o != d and (d + os.sep).startswith(o + os.sep) for o in manifest_dirs)
    ]
    if not roots:
        # No manifest.json anywhere — not a standalone mod, but Stardew/Nexus collections ship
        # "overlay" archives (config presets like "VERY Configured …", content/patch updates) whose
        # top folders are named after OTHER mods and merge into their folders under Mods/. Place the
        # tree file-by-file into Mods/ (preserving structure) and track it with per-file zip_natives
        # semantics so presence/toggle/uninstall work. The install txn backs up anything it overwrites
        # (.moddy-orig), so removing the overlay restores the base mod's original file.
        overlay: list[tuple[str, str]] = []
        for sub_root, _d, files in os.walk(extract_root):
            for fn in files:
                src = os.path.join(sub_root, fn)
                rel = os.path.relpath(src, extract_root)
                staged_abs = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
                shutil.copyfile(src, staged_abs)
                overlay.append((staged_abs, os.path.relpath(os.path.join(mods_path, rel), install_dir)))
        if not overlay:
            decky.logger.error(f"{mod.name}: empty archive — nothing to install")
            return False
        is_foreign = mods_common._overwrite_guard(install_dir, mods_path, mod, [r for _s, r in overlay])
        with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
            for p in old_paths:
                txn.retire(p)
                txn.retire(p + ".disabled")
            for staged_abs, install_rel in overlay:
                txn.place(staged_abs, install_rel)
        paths = sorted(r for _s, r in overlay)
        mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod, install_type="zip_natives")
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) as a config/content overlay — {len(paths)} file(s) merged into Mods/")
        return True

    placements: list[tuple[str, str]] = []   # (staged abs, install-dir-relative dest)
    created_tops: set[str] = set()
    for root in roots:
        folder = mods_archive._safe_folder_name(mod.filename) if root == extract_root else os.path.basename(root)
        for sub_root, _sub_dirs, files in os.walk(root):
            for fn in files:
                src = os.path.join(sub_root, fn)
                dest_rel = os.path.join(folder, os.path.relpath(src, root))
                staged_abs = os.path.join(staging, dest_rel)
                os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
                shutil.copyfile(src, staged_abs)
                placements.append((staged_abs, os.path.relpath(os.path.join(mods_path, dest_rel), install_dir)))
        created_tops.add(os.path.relpath(os.path.join(mods_path, folder), install_dir))

    # Commit: retire the previous install (both the active and `.`-disabled form of each tracked
    # folder), then place the new payload all-or-nothing.
    is_foreign = mods_common._overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
    with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
        for p in old_paths:
            txn.retire(p)
            txn.retire(mods_common._dotprefix_disabled(p))
        for staged_abs, install_rel in placements:
            txn.place(staged_abs, install_rel)

    paths = sorted(created_tops)
    mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {len(paths)} mod folder(s), {len(placements)} file(s)")
    return True


async def _install_mod_zip_smapi(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a single-archive SMAPI mod into Mods/ (the cascade/dependency path). A Stardew mod is
    a folder with manifest.json at its top; one Nexus archive may hold one folder, a folder nested
    under a wrapper, OR several sibling mod folders. Unlike zip_flat — which strips the wrapper folder
    and even drops manifest.json (it's in the Thunderstore metadata skip-set) — this preserves each
    mod's folder verbatim. See `_smapi_commit`. For a user multi-file pick see `install_smapi_files`."""
    import shutil

    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_tmp.archive")
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_smapi_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)

    # Previous install's tracked folders. Retired inside the commit transaction (in _smapi_commit) —
    # NOT before the download — so a dead link or cancel can't destroy the old install before ready.
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {utils.redact_url(url)}")
        await utils.download(url, tmp_archive, game.appid)
        mods_archive.extract_archive(tmp_archive, tmp_extract)
        return _smapi_commit(install_dir, mods_path, tmp_extract, staging, mod, version, old_paths)
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        if os.path.exists(tmp_archive):
            os.remove(tmp_archive)
        for p in (tmp_extract, staging):
            if os.path.exists(p):
                shutil.rmtree(p)


async def install_smapi_files(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, urls: list) -> bool | None:
    """Install MULTIPLE chosen Nexus files of one SMAPI mod (the file-picker path) as a single
    library entry. Each file is downloaded and extracted into its own subdir of one combined extract
    tree, then `_smapi_commit` places every mod folder found across all of them under Mods/ and
    records them together under the one mod id — so e.g. Stardew Valley Expanded's main download and
    its optional alternate farm install as one unit. All-or-nothing: a failure rolls back."""
    import shutil

    mods_path = mods.resolve_mods_path(game, install_dir)
    os.makedirs(mods_path, exist_ok=True)
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_smapi_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)

    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    try:
        for i, url in enumerate(urls):
            archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_f{i}.archive")
            try:
                decky.logger.info(f"Downloading {mod.name} file {i + 1}/{len(urls)} from {utils.redact_url(url)}")
                await utils.download(url, archive, game.appid)
                # Each archive into its own subdir so same-named folders across files don't collide
                # before placement; _smapi_commit walks the whole tree.
                mods_archive.extract_archive(archive, os.path.join(tmp_extract, f"f{i}"))
            finally:
                if os.path.exists(archive):
                    os.remove(archive)
        return _smapi_commit(install_dir, mods_path, tmp_extract, staging, mod, version, old_paths)
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        for p in (tmp_extract, staging):
            if os.path.exists(p):
                shutil.rmtree(p)
