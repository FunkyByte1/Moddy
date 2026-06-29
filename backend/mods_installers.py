import os
import json
import mods
import mods_common
import mods_archive
import mods_fomod
import mods_pak
from registry import GameProfile, ModInfo
import decky
import utils
from install_txn import _StagedInstall, _discard


_THUNDERSTORE_METADATA_FILES = {"manifest.json", "icon.png", "readme.md", "changelog.md", "license", "license.md", "license.txt"}


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


def _merge_zip_into_tree(install_dir: str, mod: ModInfo, version: str | None, tmp_zip: str, select) -> bool:
    """Merge selected zip members into the live install_dir tree atomically.

    `select(member)` maps a zip member to its install-dir-relative destination, or returns None to
    skip it (metadata, unwanted top-level entries). Members are first extracted to a staging dir
    OUTSIDE the live tree, then committed in one _StagedInstall transaction — so the game dir is
    never touched until the whole payload is on disk, and any failure (bad zip, disk full) rolls
    back to the prior state instead of leaving a half-merged mod the manager can't even see.

    Each placed file is tracked individually as `paths` (not the 2nd-level dir): mods that dump
    into shared folders like BepInEx/plugins/Language would otherwise "own" them, and uninstall
    would delete a co-located mod's files. Uninstall prunes the now-empty dirs. See
    docs/known-issues.md.
    """
    import zipfile, shutil
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_merge_staging")
    if os.path.exists(staging):
        shutil.rmtree(staging)
    placements: list[tuple[str, str]] = []  # (staged absolute path, install-dir-relative dest)
    try:
        with zipfile.ZipFile(tmp_zip, "r") as z:
            for member in z.namelist():
                if member.endswith("/"):
                    continue
                rel = select(member)
                if rel is None:
                    continue
                staged_abs = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
                with z.open(member) as src, open(staged_abs, "wb") as out:
                    shutil.copyfileobj(src, out)
                placements.append((staged_abs, rel))

        with _StagedInstall(install_dir) as txn:
            for staged_abs, rel in placements:
                txn.place(staged_abs, rel)

        mods.set_installed_record(mod.id, version or "latest", mod.filename,
                             paths=sorted(rel for _src, rel in placements), mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — merged into BepInEx tree")
        return True
    finally:
        if os.path.exists(staging):
            shutil.rmtree(staging)


def _extract_to_game_root(install_dir: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Extract only the BepInEx/* members of the zip into the game's install dir.
    Records which files under BepInEx/ this mod owns, so uninstall can clean up. Other top-level
    zip entries (manifest.json, icon.png, README.md) are skipped to keep the game root clean.
    """
    return _merge_zip_into_tree(
        install_dir, mod, version, tmp_zip,
        select=lambda m: m if m.startswith("BepInEx/") else None,
    )


def _extract_bepinex_subdirs(install_dir: str, mod: ModInfo, version: str | None, tmp_zip: str, subdirs: set) -> bool:
    """Thunderstore "modern" layout: zip has plugins/, patchers/, monomod/, or core/ at
    its root. These are BepInEx subdirectories — merge them into the game's BepInEx/
    tree so files land at e.g. BepInEx/plugins/<modname>/<dll>. Stray top-level files
    (manifest.json, icon.png, README.md) are skipped to keep BepInEx clean.
    """
    return _merge_zip_into_tree(
        install_dir, mod, version, tmp_zip,
        select=lambda m: f"BepInEx/{m}" if m.split("/")[0] in subdirs else None,
    )


def _extract_bare_dll(mods_path: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Install a bare-DLL Thunderstore mod: loose .dll/.pdb files at the zip root
    (plus possibly sidecar asset folders) extracted into BepInEx/plugins/<mod.filename>/.
    Thunderstore metadata files (manifest.json, icon.png, README.md, CHANGELOG.md, LICENSE)
    are skipped to keep the plugin folder clean."""
    import zipfile
    dst_dir = os.path.join(mods_path, mod.filename)
    staged = dst_dir + ".moddy-new"  # sibling: same filesystem, so the swap is a rename
    if os.path.exists(staged):
        _discard(staged)
    try:
        os.makedirs(staged)
        extracted = 0
        with zipfile.ZipFile(tmp_zip, "r") as z:
            for member in z.namelist():
                if member.endswith("/"):
                    continue
                parts = member.split("/")
                # Skip Thunderstore metadata at the zip root
                if len(parts) == 1 and parts[0].lower() in _THUNDERSTORE_METADATA_FILES:
                    continue
                z.extract(member, staged)
                extracted += 1

        mods_common._backup_version_dir(dst_dir, mod.id)  # version-history snapshot of the install being replaced
        mods_common._atomic_dir_swap(dst_dir, staged)
        mods.set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {extracted} files in bare-DLL layout")
        return True
    finally:
        if os.path.exists(staged):
            _discard(staged)


def _extract_to_mods_folder(mods_path: str, mod: ModInfo, version: str | None, tmp_zip: str) -> bool:
    """Extract the zip as a single folder under BepInEx/plugins/<mod.filename>/.
    Backs up the existing folder if one is present.
    """
    import zipfile, shutil
    dst_dir = os.path.join(mods_path, mod.filename)
    staged = dst_dir + ".moddy-new"      # sibling: same filesystem, so the swap is a rename
    tmp_extract = dst_dir + "_extract"   # scratch for stripping a single wrapper folder
    for p in (staged, tmp_extract):
        if os.path.exists(p):
            _discard(p)
    try:
        with zipfile.ZipFile(tmp_zip, "r") as z:
            members = z.namelist()
            top_dirs = {m.split("/")[0] for m in members if m.split("/")[0]}
            if len(top_dirs) == 1:
                z.extractall(tmp_extract)
                shutil.move(os.path.join(tmp_extract, next(iter(top_dirs))), staged)
            else:
                os.makedirs(staged)
                z.extractall(staged)

        mods_common._backup_version_dir(dst_dir, mod.id)  # version-history snapshot of the install being replaced
        mods_common._atomic_dir_swap(dst_dir, staged)
        mods.set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
        return True
    finally:
        for p in (staged, tmp_extract):
            if os.path.exists(p):
                _discard(p)


async def _install_mod_zip_flat(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a flat-loader mod (e.g. MelonLoader): extract the archive's contents directly
    into the mods dir so DLLs sit at the top level where the loader scans, stripping a single
    redundant wrapper folder if the whole archive is nested under one. Tracks the created
    top-level entries as `paths` so uninstall/toggle can find them. Reinstall overwrites a
    previous install's tracked paths first."""
    import zipfile
    import shutil

    tmp_zip = os.path.join(mods_path, f"{mod.filename}_tmp.zip")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_flat_staging")
    if os.path.exists(staging):
        shutil.rmtree(staging)

    # Previous install's tracked top-level entries (files or dirs). Cleared as part of the commit
    # transaction below — NOT before the download — so a dead link can't destroy the old install.
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_zip, game.appid)

        # Extract to staging (outside the live tree), computing each file's destination with a
        # single redundant wrapper folder stripped and Thunderstore metadata skipped.
        placements: list[tuple[str, str]] = []  # (staged absolute path, install-dir-relative dest)
        created_tops: set[str] = set()
        with zipfile.ZipFile(tmp_zip, "r") as z:
            members = [m for m in z.namelist() if m and not m.endswith("/")]
            top_level = {m.split("/")[0] for m in members}
            # If everything lives under a single wrapper folder, strip that one level so the
            # DLL lands at Mods/<dll> rather than Mods/<wrapper>/<dll>.
            strip = ""
            if len(top_level) == 1 and any("/" in m for m in members):
                strip = next(iter(top_level)) + "/"
            for m in members:
                base = m.split("/")[-1]
                if base.lower() in _THUNDERSTORE_METADATA_FILES:
                    continue
                rel = m[len(strip):] if strip and m.startswith(strip) else m
                if not rel:
                    continue
                staged_abs = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
                with z.open(m) as src, open(staged_abs, "wb") as out:
                    shutil.copyfileobj(src, out)
                placements.append((staged_abs, os.path.relpath(os.path.join(mods_path, rel), install_dir)))
                created_tops.add(rel.split("/")[0])

        # Commit: retire the previous install and place the new files all-or-nothing. retire runs
        # before place so a new file never displaces one this same transaction just wrote.
        is_foreign = mods_common._overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
        with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
            for p in old_paths:
                txn.retire(p)
            for staged_abs, install_rel in placements:
                txn.place(staged_abs, install_rel)

        paths = sorted(os.path.relpath(os.path.join(mods_path, t), install_dir) for t in created_tops)
        mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {len(created_tops)} entries flat into mods dir")
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
        if os.path.exists(staging):
            shutil.rmtree(staging)


def _folder_commit(install_dir: str, mods_path: str, extract_root: str, staging: str,
                   mod: ModInfo, version: str | None, old_paths: list, folder: str | None = None) -> bool:
    """Place an extracted archive as ONE folder <mods_dir>/<folder>/, transactionally. For folder-per-
    mod games (No Man's Sky: each mod is its own folder under GAMEDATA/MODS/; Satisfactory: each mod
    is a UE plugin folder under FactoryGame/Mods/). Format-agnostic — whatever the archive holds
    (.pak, unpacked .MBIN/.EXML, or a UE plugin's Content/Binaries) lands verbatim in the mod's
    folder. macOS zip junk (__MACOSX/, .DS_Store, ._*) is dropped so it neither defeats the wrapper
    strip nor litters the mod folder. Retires the previous install (active and `.disabled` form) and
    commits all-or-nothing.

    `folder` is the destination subfolder under mods_path (it may contain a separator, e.g.
    Satisfactory's "GameFeatures/<ModRef>"). When None, it's derived from the mod's name and a single
    redundant top-level wrapper dir is stripped; when given, the archive's files go directly under it
    (the caller already determined the exact layout, e.g. from the .uplugin)."""
    import shutil
    extract_root = os.path.normpath(extract_root)
    if folder is None:
        # Strip a single redundant top-level wrapper folder (and only that). Ignore macOS junk
        # siblings when deciding — a lone real wrapper next to __MACOSX/ or .DS_Store still strips.
        real_entries = [e for e in os.listdir(extract_root) if not mods_archive._is_archive_junk(e)]
        src_root = extract_root
        if len(real_entries) == 1 and os.path.isdir(os.path.join(extract_root, real_entries[0])):
            src_root = os.path.join(extract_root, real_entries[0])
        folder = mods_archive._safe_folder_name(mod.filename)   # one folder per mod, named for the mod (dot-stripped)
    else:
        # Caller supplied the exact destination subfolder — the archive's loose files belong directly
        # under it (no wrapper strip; a UE plugin's root holds <ModRef>.uplugin + Content/ + Binaries/).
        src_root = extract_root
    placements: list[tuple[str, str]] = []     # (staged abs, install-dir-relative dest)
    for sub_root, _dirs, files in os.walk(src_root):
        for fn in files:
            src = os.path.join(sub_root, fn)
            rel = os.path.relpath(src, src_root)
            if mods_archive._is_archive_junk(rel):
                continue                       # don't copy macOS cruft into the mod folder
            dest_rel = os.path.join(folder, rel)
            staged_abs = os.path.join(staging, dest_rel)
            os.makedirs(os.path.dirname(staged_abs), exist_ok=True)
            shutil.copyfile(src, staged_abs)
            placements.append((staged_abs, os.path.relpath(os.path.join(mods_path, dest_rel), install_dir)))
    if not placements:
        decky.logger.error(f"{mod.name}: archive had no files — refusing to install")
        return False

    top_rel = os.path.relpath(os.path.join(mods_path, folder), install_dir)
    is_foreign = mods_common._overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
    with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
        for p in old_paths:
            txn.retire(p)                      # retire() already sets aside <mod> AND <mod>.disabled
            # A previously-disabled mod is parked outside MODS/ — retire that too so reinstalling
            # over a disabled mod replaces it (and rolls back) instead of orphaning the parked copy.
            txn.retire(os.path.join(mods_common._FOLDER_DISABLED_DIR, os.path.basename(p.rstrip("/\\"))))
        for staged_abs, install_rel in placements:
            txn.place(staged_abs, install_rel)

    # Track the single top folder; toggling renames it to <mod>.disabled, so presence/enabled use
    # the flat/.disabled helpers (_flat_mod_present / _smapi_mod_enabled).
    mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=[top_rel], mod=mod)
    decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — folder {folder}/ ({len(placements)} file(s))")
    return True


async def _install_mod_zip_folder(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a folder-per-mod data mod (No Man's Sky): download, extract (.zip/.7z/.rar via
    extract_archive), and place the whole archive as one folder under GAMEDATA/MODS/<mod>/. See
    _folder_commit. Disable = rename the folder to <mod>.disabled; uninstall removes both forms."""
    import shutil
    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_tmp.archive")
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_folder_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)
    # Previous install's tracked folder — retired inside the commit transaction (not before the
    # download), so a dead link or cancel can't destroy the old install before the new one is ready.
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_archive, game.appid)
        mods_archive.extract_archive(tmp_archive, tmp_extract)
        return _folder_commit(install_dir, mods_path, tmp_extract, staging, mod, version, old_paths)
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


def _smod_plugin_root(extract_root: str, mod: ModInfo) -> "tuple[str, str] | None":
    """Locate the UE plugin inside an extracted .smod and decide where it installs, mirroring
    ficsit-cli. Returns (target_subfolder, plugin_root_dir): the Mods/ subfolder — the ModReference,
    or "GameFeatures/<ModRef>" when the `.uplugin` sets `GameFeature: true` (the game/SML scan both
    roots) — and the directory that actually holds the plugin's loose files (the archive root, or a
    wrapper dir if the .smod nested one). The ModReference is the `.uplugin` filename stem, which is
    what the folder MUST be named to load. Returns None when the archive has no `.uplugin` anywhere
    (a malformed .smod we refuse rather than silently mis-install). os.walk is top-down so a uplugin
    at the archive root wins over any nested one."""
    found = None
    for root, _dirs, files in os.walk(extract_root):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), extract_root)
            if fn.lower().endswith(".uplugin") and not mods_archive._is_archive_junk(rel):
                found = (root, fn)
                break
        if found:
            break
    if not found:
        return None
    plugin_root, uplugin = found
    ref = mods_archive._safe_folder_name(uplugin[: -len(".uplugin")]) or mods_archive._safe_folder_name(mod.filename)
    game_feature = False
    try:
        # UE writes UTF-8; some .uplugin files carry a BOM — utf-8-sig handles both and drops the
        # locale dependency (a decode/parse failure would silently lose the GameFeature flag).
        with open(os.path.join(plugin_root, uplugin), encoding="utf-8-sig") as f:
            game_feature = bool(json.load(f).get("GameFeature", False))
    except Exception as e:
        decky.logger.warning(f"{mod.name}: could not read .uplugin GameFeature flag ({e}); using Mods/{ref}")
    folder = os.path.join("GameFeatures", ref) if game_feature else ref
    return folder, plugin_root


async def _install_mod_zip_smod(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a Satisfactory mod (.smod) — an SML/UE plugin. The .smod is a zip of the plugin's
    loose files (<ModRef>.uplugin, Content/, Binaries/Win64/, …); it's extracted into one folder
    under FactoryGame/Mods/, named for the mod's ModReference (or Mods/GameFeatures/<ModRef>/ when the
    uplugin sets GameFeature). Reuses the folder-per-mod machinery (NMS): one tracked top folder,
    move-out disable (SML scans Mods/ + Mods/GameFeatures/, so a disabled mod must leave those roots),
    uninstall removes both forms. See _folder_commit / _smod_plugin_root."""
    import shutil
    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_tmp.smod")
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_smod_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)
    # Previous install's tracked folder — retired inside the commit transaction (not before the
    # download), so a dead link or cancel can't destroy the old install before the new one is ready.
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_archive, game.appid)
        mods_archive.extract_archive(tmp_archive, tmp_extract)   # .smod is a PK zip
        target = _smod_plugin_root(tmp_extract, mod)
        if target is None:
            decky.logger.error(f"{mod.name}: .smod contained no .uplugin — refusing to install")
            return False
        folder, plugin_root = target
        # plugin_root is where the loose plugin files actually live (archive root, or a wrapper dir);
        # passing it as extract_root lands them directly under Mods/<folder>/, never nested.
        return _folder_commit(install_dir, mods_path, plugin_root, staging, mod, version, old_paths, folder=folder)
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


async def _install_mod_loose_merge(
    game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, url: str | None,
    variant: str | None = None, *, folders: tuple[str, ...], lowercase: bool, handle_paks: bool, wrap_loose: bool = False,
) -> "bool | None | dict":
    """Install a Capcom-style loose-file mod from its archive (zip/7z/rar) by merging one or more
    top-level `<folder>/` trees into the game ROOT, where a dinput8 loader reads them. Each placed
    tree's top component is normalized to the canonical `folder` name (the registry casing), so an
    archive that ships `NativePC/` or `Natives/` still lands in the canonical dir; casing INSIDE the
    tree is preserved (RE4 also lowercases the whole path — see below). Two games use this:
    - RE4 (folders=("natives","reframework"), lowercase=True, handle_paks=True): merged into the root
      where REFramework reads them — `natives/` is the loose-file asset tree, and `reframework/` holds
      REFramework plugins/scripts (e.g. reframework/plugins/reframework-d2d.dll, reframework/autorun/*.lua),
      so plugin mods install through the normal flow instead of failing as "nothing to install". Paths
      are lowercased (RE4 requests lowercase; the Deck FS is case-sensitive, so `natives/STM/...` wouldn't
      be found otherwise). `.pak` content mods are re_chunk patches the engine loads natively — Moddy slots
      each just above the highest existing patch so it overrides the base game, assigning the number itself
      to avoid colliding with the mod's original name or another mod's slot.
    - MHW (folders=("nativePC",), lowercase=False, handle_paks=False, wrap_loose=True): merged into the
      root where Stracker's Loader reads it. Casing is preserved. `wrap_loose` handles the common
      Fluffy-Mod-Manager packaging where the archive has NO `nativePC/` folder — just `modinfo.ini`
      + a preview image + the content folders (`pl/`, `stm/`, …) at the root: those content folders
      ARE the nativePC payload, so they're wrapped under `nativePC/` (metadata/images skipped).
    If the archive bundles multiple variants and none was chosen, returns
    `{"needs_variant": True, "variants": [...]}` so the UI can ask which to install; pass the
    chosen variant's `id` back as `variant` to install just that one.
    Every placed file is tracked in `paths` (install-dir-relative) so uninstall/toggle act
    per-file — loose mods all merge into a shared tree, so the folder can't be treated as one unit."""
    import shutil

    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_tmp.archive")
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")

    # Previous install's tracked files (active or disabled). Retired inside the commit transaction
    # below — NOT here — so a dead download, or a parked-then-cancelled variant pick, can't destroy
    # the old install before the new one is ready.
    old_paths = (mods._load_store().get(mod.id) or {}).get("paths") or []

    # When the queue parks this install to ask which variant to use, we keep the extracted archive
    # so the resume can install the choice without downloading again. `park` tells the finally not
    # to delete that extract; `reuse` (a chosen variant + a cache already on disk) skips the fetch.
    park = False
    fomod_staged: str | None = None
    try:
        reuse = variant is not None and os.path.isdir(tmp_extract)
        if reuse:
            decky.logger.info(f"Resuming {mod.name} from cached archive (variant {variant!r})")
        else:
            if os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract)
            decky.logger.info(f"Downloading {mod.name} from {url}")
            await utils.download(url, tmp_archive, game.appid)
            mods_archive.extract_archive(tmp_archive, tmp_extract)

        # A FOMOD scripted installer takes precedence over the folder-variant heuristic: if the
        # archive ships fomod/ModuleConfig.xml, resolve it (not its option folders, which would be
        # mis-read as mutually-exclusive variants, dropping required ones) into a staging tree and
        # install THAT. prepare() returns a {"needs_fomod"} dict to PARK for the wizard when there
        # are real choices (resumed with the wizard's JSON selections via the `variant` channel),
        # else stages the default/selected file set. The staged tree is the mod's logical root, so
        # `wrap_loose` maps it under the canonical folder.
        fomod_cfg = mods_fomod.find_config(tmp_extract)
        fomod_result = mods_fomod.prepare(tmp_extract, fomod_cfg, mod.name, variant) if fomod_cfg else None
        if isinstance(fomod_result, dict):
            park = True
            return fomod_result
        if isinstance(fomod_result, str):
            fomod_staged = fomod_result

        if fomod_staged is not None:
            search_root = fomod_staged
            wrap_loose = True
        else:
            # Resolve which payload to install. Multiple variants + no choice → ask the UI.
            variants = mods_archive._detect_variants(tmp_extract)
            valid_ids = {v["id"] for v in variants}
            if variant == mods_fomod.COLLECTION_AUTO:
                # non-interactive (collection) install: take the first/default payload, never park
                search_root = os.path.join(tmp_extract, variants[0]["id"]) if len(variants) > 1 else tmp_extract
            elif variant is not None:
                if variant not in valid_ids:
                    decky.logger.error(f"{mod.name}: unknown variant {variant!r}")
                    return False
                search_root = os.path.join(tmp_extract, variant)
            elif len(variants) > 1:
                decky.logger.info(f"{mod.name}: {len(variants)} variants — asking user to choose")
                park = True
                return {"needs_variant": True, "variants": variants}
            else:
                search_root = tmp_extract

        # Build the placement plan from the staging tree — read-only, the live game dir is untouched
        # until the commit transaction below.
        # 1. Loose-file payload: for each canonical merge folder, the shallowest matching `<folder>/`
        #    tree in the archive, merged into the game root under the canonical name. RE4 merges both
        #    natives/ (assets) and reframework/ (plugins/scripts); MHW merges nativePC/ only. RE4
        #    lowercases (it requests lowercase paths and the Deck FS is case-sensitive); MHW preserves
        #    casing (Stracker's matches the mod's original path).
        def _place(full: str, inner_rel: str, folder: str) -> tuple[str, str]:
            rel = os.path.join(folder, inner_rel) if inner_rel != "." else folder
            return (full, rel.lower() if lowercase else rel)

        natives_placements: list[tuple[str, str]] = []  # (staged src, install-dir-relative dest)
        for folder in folders:
            matches = []
            for root, dirs, _files in os.walk(search_root):
                for d in dirs:
                    if d.lower() == folder.lower():
                        matches.append(os.path.join(root, d))
            matches.sort(key=lambda p: p.count(os.sep))
            if not matches:
                continue
            top = matches[0]  # shallowest tree for this folder (descends through any wrapper dir)
            for root, _dirs, files in os.walk(top):
                for fn in files:
                    full = os.path.join(root, fn)
                    natives_placements.append(_place(full, os.path.relpath(full, top), folder))
        if not natives_placements and wrap_loose:
            # No <folder>/ in the archive (Fluffy packaging): the content at the payload root IS the
            # folder's payload. Place every non-metadata file under the (single) canonical folder,
            # preserving its path. A single wrapper dir holding everything (e.g. "<Mod Name>/pl/…") is
            # descended into so we don't bury the tree one level too deep; content-at-root (the Fluffy
            # norm) is used as-is.
            payload_root = mods_archive._strip_loose_wrapper(search_root)
            for root, _dirs, files in os.walk(payload_root):
                for fn in files:
                    if mods_archive._is_loose_metadata(os.path.relpath(os.path.join(root, fn), payload_root)):
                        continue
                    full = os.path.join(root, fn)
                    natives_placements.append(_place(full, os.path.relpath(full, payload_root), folders[0]))
        if not natives_placements and "reframework" in folders:
            # REFramework script mod packaged WITHOUT the reframework/ wrapper — a bare autorun
            # script (foo.lua) or a loose `autorun/` tree at the archive root. The author expects
            # the user to drop it into reframework/autorun/ by hand; REFramework loads Lua from
            # there, so wrap the payload under reframework/autorun/ (companion data files alongside
            # the script come too; metadata/readmes are skipped). Gated on a .lua actually being
            # present so a genuinely-unrecognized archive still fails rather than dumping junk there.
            payload_root = mods_archive._strip_loose_wrapper(search_root)
            autorun_dirs = sorted(
                (os.path.join(r, d) for r, ds, _f in os.walk(payload_root) for d in ds if d.lower() == "autorun"),
                key=lambda p: p.count(os.sep),
            )
            base = autorun_dirs[0] if autorun_dirs else payload_root
            if any(fn.lower().endswith(".lua") for _r, _d, fs in os.walk(base) for fn in fs):
                for root, _dirs, files in os.walk(base):
                    for fn in files:
                        rel = os.path.relpath(os.path.join(root, fn), base)
                        if mods_archive._is_loose_metadata(rel):
                            continue
                        natives_placements.append(
                            _place(os.path.join(root, fn), os.path.join("autorun", rel), "reframework"))

        # 2. .pak content mods (RE4 only). Skip any .pak inside a <folder>/ tree (those are assets,
        #    copied above).
        pak_srcs = []
        if handle_paks:
            skip = tuple(os.sep + f.lower() + os.sep for f in folders)
            for root, _dirs, files in os.walk(search_root):
                rp = (root + os.sep).lower()
                if any(s in rp for s in skip):
                    continue
                for fn in files:
                    if fn.lower().endswith(".pak"):
                        pak_srcs.append(os.path.join(root, fn))
            pak_srcs.sort()

        if not natives_placements and not pak_srcs:
            folders_desc = " or ".join(f + "/" for f in folders)
            decky.logger.error(f"{mod.name}: archive has no {folders_desc} folder{' or .pak file' if handle_paks else ''} — nothing to install")
            return False

        # Commit: retire the previous install and place the new payload all-or-nothing. Pak slots are
        # assigned HERE, not during prepare, so each reads the live dir as paks land — and a retired
        # old pak (renamed to *.moddy-bak) drops out of the slot scan, so an upgrade reclaims its slot
        # instead of stacking a new number on top.
        paths: list[str] = []
        # .pak content lands in fresh numbered slots (never an overwrite); only the loose natives/
        # files can collide, so the conflict scan covers those. Stock files (unclaimed) the merge
        # displaces are preserved as *.moddy-orig on commit.
        is_foreign = mods_common._overwrite_guard(install_dir, mods.resolve_mods_path(game, install_dir), mod,
                                      [r for _f, r in natives_placements])
        with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
            for p in old_paths:
                txn.retire(p)
            for full, rel in natives_placements:
                txn.place(full, rel)
                paths.append(rel)
            for src in pak_srcs:
                rel = f"re_chunk_000.pak.patch_{mods_pak._next_pak_slot(install_dir):03d}.pak"
                txn.place(src, rel)
                paths.append(rel)

        paths.sort()
        mods.set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
        n_pak = sum(1 for p in paths if p.lower().startswith("re_chunk_000.pak.patch_"))
        n_nat = len(paths) - n_pak
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'}) — {n_nat} natives file(s), {n_pak} pak(s)")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"Install of {mod.name} was cancelled")
        return None
    except Exception as e:
        decky.logger.error(f"Failed to install {mod.name}: {e}")
        return False
    finally:
        if os.path.exists(tmp_archive):
            os.remove(tmp_archive)
        # Keep the extracted archive when parked for a variant choice; the resume reuses it.
        if not park and os.path.exists(tmp_extract):
            shutil.rmtree(tmp_extract)
        if fomod_staged and os.path.exists(fomod_staged):
            shutil.rmtree(fomod_staged, ignore_errors=True)


async def _install_mod_zip_natives(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, url: str | None, variant: str | None = None) -> "bool | None | dict":
    """RE4 loose-file install: merge lowercased `natives/` (assets) and `reframework/` (REFramework
    plugins/scripts) trees into the game root and slot `.pak` content mods. See _install_mod_loose_merge."""
    return await _install_mod_loose_merge(
        game, install_dir, mod, version, url, variant,
        folders=("natives", "reframework"), lowercase=True, handle_paks=True,
    )


async def _install_mod_zip_nativepc(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, url: str | None, variant: str | None = None) -> "bool | None | dict":
    """MHW loose-file install: merge a case-preserved `nativePC/` tree into the game root, where
    Stracker's Loader reads it. No `.pak` slotting. Fluffy-packaged mods (no nativePC/ folder, just
    content folders + modinfo.ini) are wrapped into nativePC/. See _install_mod_loose_merge."""
    return await _install_mod_loose_merge(
        game, install_dir, mod, version, url, variant,
        folders=("nativePC",), lowercase=False, handle_paks=False, wrap_loose=True,
    )


def discard_natives_cache(filename: str) -> None:
    """Drop the extracted-archive cache left behind by a parked variant install (used when the
    user cancels at the variant prompt instead of resuming). Best-effort."""
    import shutil
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{filename}_extract")
    try:
        if os.path.isdir(tmp_extract):
            shutil.rmtree(tmp_extract)
    except Exception as e:
        decky.logger.warning(f"Failed to discard natives cache {tmp_extract}: {e}")
