import os
import mods
import mods_common
import mods_pak
import mods_installers
import mods_mergetool
import mods_smapi
import mods_palworld
from install_txn import _MODDY_ORIG_SUFFIX, _STAGED_BAK_SUFFIX, _discard
from registry import GameProfile, ModInfo
import decky
import re
from mods_pak import _PAK_PATCH_RE


def mods_under_modloader(game: GameProfile, install_dir: str, removed_dirs: list[str], removed_files: list[str]) -> list[dict]:
    """Installed mods for this game whose files live within a modloader's footprint — the dirs and
    files its uninstall deletes — so removing the loader would take them with it. Returns
    [{"id", "name"}] to warn the user before a loader uninstall. A MelonLoader-style loader (whose
    own dir is separate from the Mods/ folder its mods live in) yields an empty list."""
    rdirs = [d.replace("\\", "/").strip("/") for d in (removed_dirs or []) if d]
    rfiles = {f.replace("\\", "/").strip("/") for f in (removed_files or [])}

    def under_removed(rel: str) -> bool:
        t = rel.replace("\\", "/").strip("/")
        return t in rfiles or any(t == d or t.startswith(d + "/") for d in rdirs)

    out = []
    for mod_id, rec in (mods._load_store(game.appid) or {}).items():
        if (rec.get("source") or {}).get("type") == "steamworkshop":
            continue
        if not mods_common.mod_files_present(game, install_dir, rec):
            continue
        if any(under_removed(t) for t in mods_common._record_target_relpaths(game, install_dir, rec)):
            name = (rec.get("meta") or {}).get("name") or rec.get("filename") or mod_id
            out.append({"id": mod_id, "name": name})
    return out


# In-flight install artifacts a hard crash (reboot/power-loss/kill-9) can strand mid-commit. In
# normal operation the transaction and finally blocks always clean these up; the startup sweep
# below handles the crash case. Run ONLY at startup, when no install is in flight — a live install
# legitimately holds .moddy-bak files mid-commit, and sweeping then would corrupt it.
_RUNTIME_SCRATCH_SUFFIXES = ("_staging", "_extract", "_tmp.zip", "_tmp.archive")
_MODDY_NEW_SUFFIX = ".moddy-new"
_MODDY_OLD_SUFFIX = ".moddy-old"


def sweep_runtime_scratch() -> None:
    """Delete extraction/download scratch left in the plugin runtime dir by a crash mid-install.
    Pure scratch — always safe to remove, and it reclaims disk (extracted archives can be large)."""
    runtime = decky.DECKY_PLUGIN_RUNTIME_DIR
    try:
        entries = os.listdir(runtime)
    except OSError:
        return
    for name in entries:
        if name.endswith(_RUNTIME_SCRATCH_SUFFIXES):
            _discard(os.path.join(runtime, name))


def _restore_or_discard(d: str, name: str, suffix: str, present: set) -> None:
    """For a set-aside backup `name` (ending in `suffix`) in dir `d`: if its primary is on disk the
    commit moved past it and the backup is stale → discard; if the primary is missing the crash
    left it only in the backup → restore (rename back)."""
    primary = name[: -len(suffix)]
    full = os.path.join(d, name)
    if primary in present:
        _discard(full)
    else:
        try:
            os.replace(full, os.path.join(d, primary))
        except OSError:
            pass


def _sweep_crumbs_in_dir(d: str) -> None:
    """Resolve transaction crumbs sitting directly in `d` (non-recursive). .moddy-bak/.moddy-old
    are restored if their primary is gone, else discarded; .moddy-new is discardable staging."""
    try:
        names = os.listdir(d)
    except OSError:
        return
    present = set(names)
    for name in names:
        if name.endswith(_STAGED_BAK_SUFFIX):
            _restore_or_discard(d, name, _STAGED_BAK_SUFFIX, present)
        elif name.endswith(_MODDY_OLD_SUFFIX):
            _restore_or_discard(d, name, _MODDY_OLD_SUFFIX, present)
        elif name.endswith(_MODDY_NEW_SUFFIX):
            _discard(os.path.join(d, name))


def sweep_install_crumbs(game: GameProfile, install_dir: str) -> None:
    """Resolve in-flight install crumbs left in a game's mod directories by a crash mid-commit.
    Scoped to the bounded set of dirs Moddy writes to — the install-dir top level, mods_path, and
    each tracked record's path dirs — never a recursive walk of the whole game dir. Safe only at
    startup, when no install is in flight."""
    dirs = {install_dir}
    try:
        dirs.add(mods.resolve_mods_path(game, install_dir))
    except Exception:
        pass
    for rec in (mods._load_store(game.appid) or {}).values():
        for rel in mods_common._record_target_relpaths(game, install_dir, rec):
            parent = os.path.dirname(os.path.join(install_dir, rel))
            if parent:
                dirs.add(parent)
    for d in dirs:
        _sweep_crumbs_in_dir(d)


def _prune_empty_dirs(install_dir: str, rel_paths: list[str]) -> None:
    """After a mod's tracked files are removed, delete any now-empty parent directories up to
    (not including) the install dir. os.rmdir only removes empty directories, so a folder that
    still holds another mod's files is never touched — this is what makes per-file ownership
    safe for mods that share generic folders (e.g. BepInEx/plugins/Language)."""
    root = os.path.normpath(install_dir)
    candidates: set[str] = set()
    for rel in rel_paths:
        d = os.path.dirname(os.path.normpath(os.path.join(install_dir, rel)))
        while d != root and d.startswith(root + os.sep):
            candidates.add(d)
            d = os.path.dirname(d)
    # Deepest first, so a child is emptied before its parent is tried.
    for d in sorted(candidates, key=lambda p: p.count(os.sep), reverse=True):
        try:
            os.rmdir(d)
        except OSError:
            pass  # non-empty (another mod's files) or already gone — leave it


def get_installed_mods(game: GameProfile, install_dir: str) -> list[dict]:
    """
    Return installed mods with id, filename, enabled state, version, and meta.
    Source of truth: installed.json (covers multi-location mods like patchers that don't
    live under BepInEx/plugins/, and every browsed mod). Also scans the filesystem for
    legacy / manually-placed entries.
    """
    mods_path = mods.resolve_mods_path(game, install_dir)
    toggle_style = game.mod_toggle_style()
    # Bundled frameworks (e.g. Steamodded) install with the modloader and are managed from
    # the Mod Loader tab, so they're never listed as content mods.
    hidden_ids = game.bundled_framework_ids()
    installed = []
    seen_ids: set[str] = set()
    # Physical files/dirs already owned by a tracked record, so the filesystem scan
    # doesn't re-list them under a different id. This matters for flat (MelonLoader) mods:
    # a browsed Nexus mod extracts e.g. Mods/SR2GyroAim.dll, and without this its loose
    # .dll would appear a second time as an untracked entry.
    claimed_paths: set[str] = set()

    def _claim(record: dict, filename: str | None) -> None:
        paths = record.get("paths")
        if paths:
            claimed_paths.update(os.path.join(install_dir, p) for p in paths)
        elif filename:
            claimed_paths.add(os.path.join(mods_path, filename))

    # Tracked installs from installed.json.
    store = mods._load_store(game.appid)

    # Workshop games have no on-disk mods folder Moddy manages — their state is the
    # set of tracked subscriptions. List every subscribed Workshop item reconciled into
    # the store for this game (synthetic `workshop.<appid>.<fileid>` records). Skip the
    # filesystem scans entirely.
    if game.uses_steam_workshop():
        for mod_id, record in store.items():
            if mod_id in seen_ids:
                continue
            src = record.get("source") or {}
            if src.get("type") != "steamworkshop":
                continue
            seen_ids.add(mod_id)
            installed.append({
                "id": mod_id,
                "filename": record.get("filename", mod_id),
                "enabled": record.get("enabled", True),
                "version": record.get("version"),
                "meta": record.get("meta"),
                "is_library": record.get("is_library", False),
                "ignore_unused": record.get("ignore_unused", False),
                "added_at": record.get("added_at"),
                "sources": record.get("sources"),
            })
        return installed

    # Tracked installs from installed.json — browsed mods (this game's own store section).
    #    The on-disk presence check is kept for ORPHAN detection: a record can outlive its
    #    files (e.g. uninstalling the modloader rmtree'd the plugins away), and an orphaned
    #    record must not list as an installed-but-"disabled" mod.
    for mod_id, record in store.items():
        if mod_id in seen_ids or mod_id in hidden_ids:
            continue
        filename = record.get("filename")
        if not filename:
            continue
        install_type = record.get("install_type") or (record.get("source") or {}).get("install_type") or "file"
        paths = record.get("paths")
        if install_type == "zip_flat":
            target_paths = mods_common._flat_target_paths(install_dir, paths)
            if not mods_common._flat_mod_present(target_paths):
                continue  # installed for a different game
            enabled = mods_common._flat_mod_enabled(target_paths)
        elif install_type in ("zip_natives", "zip_nativepc", "zip_palworld"):
            # Loose mod (RE4 natives/, MHW nativePC/, Palworld ~mods/ + UE4SS Mods/): per-file paths
            # merged into game subdirs. Present iff any tracked file exists (active or *.disabled);
            # enabled iff the active form is on disk.
            target_paths = mods_common._flat_target_paths(install_dir, paths)
            if not mods_common._flat_mod_present(target_paths):
                continue  # installed for a different game
            enabled = mods_common._natives_mod_enabled(target_paths)
        elif install_type == "zip_smapi":
            # SMAPI mod: one or more folders under Mods/, each with a manifest.json. Present iff
            # any tracked folder exists (active or `.`-disabled); enabled iff the active form is on disk.
            target_paths = mods_common._flat_target_paths(install_dir, paths)
            if not mods_common._smapi_mod_present(target_paths):
                continue  # installed for a different game
            enabled = mods_common._smapi_mod_enabled(target_paths)
        elif install_type in ("zip_folder", "zip_smod", "external_merge"):
            # Folder-per-mod data mod (NMS GAMEDATA/MODS/; Satisfactory FactoryGame/Mods/; Fields of
            # Mistria mods/): one folder under the mods dir. Present iff it's live there OR parked in
            # the disabled-staging dir; enabled iff the live folder is on disk (will be baked next apply).
            if not mods_common._zipfolder_present(install_dir, paths):
                continue  # installed for a different game
            enabled = mods_common._zipfolder_enabled(install_dir, paths)
        elif install_type == "zip_dir" or paths:
            target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]
            if not any(mods_common._tracked_present(d) for d in target_dirs):
                continue  # installed for a different game
            enabled = mods_common._folder_mod_enabled(target_dirs, toggle_style)
        else:
            target = os.path.join(mods_path, filename)
            if os.path.isfile(target):
                enabled = True
            elif os.path.isfile(target + ".bak"):
                enabled = False
            else:
                continue  # installed for a different game
        seen_ids.add(mod_id)
        _claim(record, filename)
        installed.append({
            "id": mod_id,
            "filename": filename,
            "enabled": enabled,
            "version": record.get("version"),
            "meta": record.get("meta"),
            "ignore_unused": record.get("ignore_unused", False),
            "added_at": record.get("added_at"),
            "sources": record.get("sources"),
        })

    # 3) Filesystem scan for legacy / manually-placed entries we haven't tracked.
    #    Skip it when the "mods dir" IS the game root (e.g. RE4, mods_dir=""), where a loose-.dll
    #    scan would surface the game's own engine DLLs (Wwise Ak*, MasteringSuite, MSSpatial,
    #    steam_api64, amd_ags_x64, CrashHandler/CrashReportDll, the REFramework dinput8 loader, …)
    #    as phantom mods. Those games track their real mods via records (section 2) and keep mods
    #    as loose natives/.pak files, not bare DLLs in root — so there's nothing to discover here.
    if os.path.isdir(mods_path) and os.path.normpath(mods_path) != os.path.normpath(install_dir):
        for entry in os.listdir(mods_path):
            entry_path = os.path.join(mods_path, entry)
            if entry.endswith(".dll") or entry.endswith(".dll.bak"):
                enabled = entry.endswith(".dll")
                actual_filename = entry if enabled else entry[:-4]
                if os.path.join(mods_path, actual_filename) in claimed_paths:
                    continue  # already listed by a tracked record (e.g. a browsed Nexus mod)
                # Untracked loose .dll (legacy/manual placement): list it under its filename.
                installed.append({
                    "id": actual_filename,
                    "filename": actual_filename,
                    "enabled": enabled,
                    "version": mods.get_installed_version(game.appid, actual_filename),
                    "meta": None,
                    "added_at": None,
                })

    return installed


async def install_mod(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None = None, url: str | None = None, variant: str | None = None, source: dict | None = None) -> "bool | None | dict":
    """
    Download and install a mod into the game's mods directory.
    Supports two install types:
    - "file": single DLL, backs up previous version as Mod.dll.vX.Y.Z.bak
    - "zip_dir": extracts zip as a folder into the mods directory
    Returns True=success, False=failed, None=cancelled. For "zip_natives" with multiple variants
    and no `variant` chosen, returns {"needs_variant": True, "variants": [...]}.

    `source` records provenance for the Installed-page grouping: {"id": "collection:<slug>",
    "name": <display>} for a collection install, defaulting to {"id":"manual"} for a direct
    install. It's stamped only on a fully-successful install (result is True) so a parked /
    failed / cancelled install never groups a mod that isn't there.
    """
    mods_path = mods.resolve_mods_path(game, install_dir)
    os.makedirs(mods_path, exist_ok=True)

    result = await _install_dispatch(game, install_dir, mods_path, mod, version, url, variant)
    if result is True:
        mods.add_record_source(game.appid, mod.id, source or {"id": "manual", "name": "You"})
    return result


async def _install_dispatch(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None, variant: str | None) -> "bool | None | dict":
    if mod.source.install_type == "zip_dir":
        return await mods_installers._install_mod_zip_dir(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_flat":
        return await mods_installers._install_mod_zip_flat(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_natives":
        return await mods_installers._install_mod_zip_natives(game, install_dir, mod, version, url, variant)
    if mod.source.install_type == "zip_nativepc":
        return await mods_installers._install_mod_zip_nativepc(game, install_dir, mod, version, url, variant)
    if mod.source.install_type == "zip_smapi":
        return await mods_smapi._install_mod_zip_smapi(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_folder":
        return await mods_installers._install_mod_zip_folder(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "external_merge":
        return await mods_installers._install_mod_external_merge(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_smod":
        return await mods_installers._install_mod_zip_smod(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_palworld":
        return await mods_palworld._install_mod_zip_palworld(game, install_dir, mods_path, mod, version, url)
    # Guard: only the single-file installer is a safe default. An unrecognized install_type
    # must NOT silently fall through to it — that once dumped a raw mod archive into RE4's
    # game dir (the `nexus-<id>` file). Fail loudly instead.
    if mod.source.install_type not in ("", "file"):
        decky.logger.error(
            f"Unknown install_type '{mod.source.install_type}' for {mod.name}; refusing to install"
        )
        return False
    return await mods_common._install_mod_file(game, install_dir, mods_path, mod, version, url)


def get_backed_up_versions(game: GameProfile, install_dir: str, mod_id: str) -> list[str]:
    """Return a list of previously installed versions backed up on disk."""
    record = mods.get_installed_record(game.appid, mod_id) or {}
    filename = record.get("filename")
    if not filename:
        return []
    mods_path = mods.resolve_mods_path(game, install_dir)
    if not os.path.isdir(mods_path):
        return []
    prefix = f"{filename}.v"
    suffix = ".bak"
    versions = [
        f[len(prefix):-len(suffix)]
        for f in os.listdir(mods_path)
        if f.startswith(prefix) and f.endswith(suffix)
    ]
    return sorted(versions, reverse=True)


def delete_mod_version(game: GameProfile, install_dir: str, mod_id: str, version: str) -> bool:
    """Delete a specific backed-up version of a mod (.vX.Y.Z.bak file)."""
    record = mods.get_installed_record(game.appid, mod_id) or {}
    filename = record.get("filename")
    if not filename:
        return False
    mods_path = mods.resolve_mods_path(game, install_dir)
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


async def uninstall_mod(game: GameProfile, install_dir: str, mod_id: str) -> bool:
    """
    Remove a mod from the mods directory.
    Handles file-based, folder-based, and multi-location (paths-tracked) mods.
    Removes all versioned backups too. Every mod is uninstalled using its persisted
    record in installed.json.
    """
    import shutil
    mods_path = mods.resolve_mods_path(game, install_dir)
    store = mods._load_store(game.appid)
    record = store.get(mod_id, {})

    # Steam Workshop mods: the frontend unsubscribes via SteamClient (which deletes
    # the files); the backend just drops the tracking record.
    rec_source = record.get("source") or {}
    source_type = rec_source.get("type")
    if source_type == "steamworkshop":
        fileid = rec_source.get("workshop_id") or ""
        if fileid:
            mods._mark_unsub_pending(fileid)  # don't let reconcile re-add it mid-unsubscribe
        mods.clear_installed_record(game.appid, mod_id)
        return True

    filename = record.get("filename", mod_id)
    paths = record.get("paths")
    install_type = record.get("install_type") or rec_source.get("install_type")
    is_dir_mod = install_type == "zip_dir"
    try:
        if paths:
            # Multi-location install (e.g. BepInEx patcher, flat MelonLoader mod) — clean each
            # tracked path. A flat mod that's currently disabled has its DLL renamed to
            # *.dll.disabled, so remove that variant too.
            for relpath in paths:
                full = os.path.join(install_dir, relpath)
                # A SMAPI mod that's currently disabled lives at Mods/.<X>, not Mods/<X>.disabled.
                cands = [full, full + ".disabled"]
                if install_type == "zip_smapi":
                    cands.append(mods_common._dotprefix_disabled(full))
                if install_type in ("zip_folder", "zip_smod", "external_merge"):
                    cands.append(mods_common._zipfolder_disabled_path(install_dir, relpath))  # a disabled mod is parked outside the scan roots
                for cand in cands:
                    if os.path.isdir(cand):
                        shutil.rmtree(cand)
                        decky.logger.info(f"Removed {os.path.relpath(cand, install_dir)}")
                    elif os.path.isfile(cand):
                        os.remove(cand)
                        decky.logger.info(f"Removed {os.path.relpath(cand, install_dir)}")
            # Also clean a legacy mods_path/<filename> folder if one was left from a previous install
            legacy = os.path.join(mods_path, filename)
            if os.path.isdir(legacy):
                shutil.rmtree(legacy)
                decky.logger.info(f"Removed legacy {filename}/")
            # Restore any stock game file this mod overwrote at install, for slots no other mod
            # still claims. Done before the prune so the restored file keeps its parent dir.
            mods_common._restore_originals(game.appid, install_dir, mods_path, [os.path.join(install_dir, p) for p in paths], mod_id)
            # Per-file records (BepInEx merge / RE4 natives) leave empty dirs behind — prune
            # them, but only when empty so a shared folder another mod uses survives.
            _prune_empty_dirs(install_dir, paths)
            mods_common._zipfolder_prune_staging(install_dir)  # tidy the NMS disabled-staging dir if now empty
            mods.clear_installed_record(game.appid, mod_id)
            # If a .pak mod was removed, close the numbering gap so the remaining pak mods keep
            # loading (and keep their relative load-order/priority).
            if any(_PAK_PATCH_RE.match(os.path.basename(p)) for p in paths):
                mods_pak._renumber_pak_mods(game.appid, install_dir)
            if install_type == "external_merge":
                # Rebuild the shared game file (data.win) from the remaining mod folders.
                ml = mods_mergetool.merge_loader(game)
                if ml:
                    await mods_mergetool.run_apply(game, install_dir, ml)
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
            # Restore a stock game file this single-file mod overwrote (mods_dir = game root).
            mods_common._restore_originals(game.appid, install_dir, mods_path, [os.path.join(mods_path, filename)], mod_id)
        mods.clear_installed_record(game.appid, mod_id)
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
            marker = os.path.join(d, mods_common._LOVELYIGNORE)
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
    Every mod uses its persisted record in installed.json.
    """
    mods_path = mods.resolve_mods_path(game, install_dir)
    store = mods._load_store(game.appid)
    record = store.get(mod_id, {})

    # Steam Workshop enable/disable: the active/inactive flip happens in the frontend
    # via SetWorkshopItemsDisabledLocally (keeps the files, no unsubscribe). Here we
    # just persist the resulting enabled state so Moddy lists and snapshots it correctly.
    rec_source = record.get("source") or {}
    if rec_source.get("type") == "steamworkshop":
        mods.set_mod_enabled(game.appid, mod_id, enable)
        decky.logger.info(f"Workshop mod {mod_id} enabled={enable}")
        return True

    install_type = record.get("install_type") or rec_source.get("install_type")
    filename = record.get("filename", mod_id)

    if install_type == "zip_flat":
        # Flat-loader mod (MelonLoader): toggle every tracked *.dll between active and
        # *.dll.disabled so the loader skips it. Asset-only mods have nothing to toggle.
        target_paths = mods_common._flat_target_paths(install_dir, record.get("paths"))
        renamed = 0
        try:
            for base in target_paths:
                # Walk dirs; flip plain file paths directly.
                candidates = []
                if os.path.isdir(base):
                    for root, _dirs, files in os.walk(base):
                        candidates += [os.path.join(root, f) for f in files]
                else:
                    candidates = [base, base + ".disabled"]
                for c in candidates:
                    if enable and c.endswith(".dll.disabled") and os.path.isfile(c):
                        os.rename(c, c[:-len(".disabled")])
                        renamed += 1
                    elif not enable and c.endswith(".dll") and os.path.isfile(c):
                        os.rename(c, c + ".disabled")
                        renamed += 1
            if renamed == 0:
                decky.logger.warning(f"No DLLs to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({renamed} dll{'s' if renamed != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

    if install_type in ("zip_natives", "zip_nativepc", "zip_palworld"):
        # Loose mod (RE4 natives/, MHW nativePC/, Palworld ~mods/ + UE4SS Mods/): the loader/engine
        # matches files by exact name, so disabling renames every tracked file to *.disabled (and
        # enabling renames back). For Palworld this turns `X_P.pak` → `X_P.pak.disabled` (no longer a
        # *.pak the engine loads) and removes a UE4SS mod's `enabled.txt` (so it stops auto-loading).
        target_paths = mods_common._flat_target_paths(install_dir, record.get("paths"))
        done: list[tuple[str, str]] = []  # (from, to) completed renames — rolled back on a mid-loop error
        try:
            for p in target_paths:
                if enable:
                    if os.path.isfile(p + ".disabled") and not os.path.isfile(p):
                        os.rename(p + ".disabled", p)
                        done.append((p + ".disabled", p))
                else:
                    if os.path.isfile(p):
                        os.rename(p, p + ".disabled")
                        done.append((p, p + ".disabled"))
            if not done:
                decky.logger.warning(f"No files to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({len(done)} file{'s' if len(done) != 1 else ''})")
            return True
        except Exception as e:
            # A mod can span two subsystems (a Palworld LogicMods pak + its UE4SS Lua folder), so a
            # half-done toggle would leave it inconsistent — undo the renames already made.
            for src, dst in reversed(done):
                try:
                    os.rename(dst, src)
                except OSError:
                    pass
            decky.logger.error(f"Failed to toggle {mod_id} (rolled back {len(done)} rename(s)): {e}")
            return False

    if install_type == "zip_smapi":
        # SMAPI mod: SMAPI skips any folder under Mods/ whose name starts with '.', so toggle
        # each tracked mod folder between `Mods/<X>` and `Mods/.<X>`. Non-destructive and
        # exactly what the in-game mod-manager mods do.
        target_paths = mods_common._flat_target_paths(install_dir, record.get("paths"))
        renamed = 0
        try:
            for p in target_paths:
                disabled = mods_common._dotprefix_disabled(p)
                if enable:
                    if os.path.exists(disabled) and not os.path.exists(p):
                        os.rename(disabled, p)
                        renamed += 1
                else:
                    if os.path.exists(p):
                        os.rename(p, disabled)
                        renamed += 1
            if renamed == 0:
                decky.logger.warning(f"No folders to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({renamed} folder{'s' if renamed != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

    if install_type in ("zip_folder", "zip_smod", "external_merge"):
        # Folder-per-mod mod (NMS GAMEDATA/MODS/; Satisfactory FactoryGame/Mods/ + Mods/GameFeatures/;
        # Fields of Mistria mods/): the loader/merge-tool discovers any folder under its scan roots, so
        # an in-place `.disabled` rename does NOT hide a mod. Disabling MOVES each tracked folder out
        # into a game-root staging dir (outside the scan roots); enabling moves it back. For an
        # external-merge game the moved-out set is then re-baked by the tool (rebuild-on-change).
        import shutil
        paths = record.get("paths") or []
        moved = 0
        try:
            for rel in paths:
                active = os.path.join(install_dir, rel)
                parked = mods_common._zipfolder_disabled_path(install_dir, rel)
                if enable:
                    if os.path.isdir(parked) and not os.path.isdir(active):
                        os.makedirs(os.path.dirname(active), exist_ok=True)
                        shutil.move(parked, active)
                        moved += 1
                else:
                    if os.path.isdir(active):
                        os.makedirs(os.path.dirname(parked), exist_ok=True)
                        shutil.move(active, parked)
                        moved += 1
            if moved == 0:
                decky.logger.warning(f"No folders to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            mods_common._zipfolder_prune_staging(install_dir)
            if install_type == "external_merge":
                ml = mods_mergetool.merge_loader(game)
                if ml and not await mods_mergetool.run_apply(game, install_dir, ml):
                    decky.logger.error(f"Toggled {filename} but the merge tool failed to apply — reapply to retry")
                    return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({moved} folder{'s' if moved != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

    if install_type == "zip_dir":
        paths = record.get("paths")
        target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]

        if game.mod_toggle_style() == "lovelyignore":
            return _toggle_lovelyignore(target_dirs, mod_id, filename, enable)

        renamed = 0
        try:
            for d in target_dirs:
                if os.path.isdir(d):
                    for root, _dirs, files in os.walk(d):
                        for f in files:
                            if enable and f.endswith(".dll.disabled"):
                                os.rename(os.path.join(root, f), os.path.join(root, f[:-len(".disabled")]))
                                renamed += 1
                            elif not enable and f.endswith(".dll"):
                                os.rename(os.path.join(root, f), os.path.join(root, f + ".disabled"))
                                renamed += 1
                elif d.endswith(".dll"):
                    # Bare DLL tracked directly (no subfolder), e.g. Enforcer / modular R2API.
                    if enable and os.path.isfile(d + ".disabled") and not os.path.isfile(d):
                        os.rename(d + ".disabled", d)
                        renamed += 1
                    elif not enable and os.path.isfile(d):
                        os.rename(d, d + ".disabled")
                        renamed += 1
            if renamed == 0:
                decky.logger.warning(f"No DLLs to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({renamed} dll{'s' if renamed != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

    # Single-file mod (install_type "file"/""). Toggle parks the mod between <name> and <name>.bak.
    # If the mod overwrote a stock game file (mods_dir = game root), a durable *.moddy-orig holds
    # the original: disabling must put that original back in the slot the mod vacates, and enabling
    # must re-stash it — otherwise "disabled" leaves a hole instead of vanilla.
    live = os.path.join(mods_path, filename)
    parked = live + ".bak"
    durable = live + _MODDY_ORIG_SUFFIX
    try:
        if enable:
            if not os.path.exists(parked):
                decky.logger.error(f"Source file not found: {parked}")
                return False
            if os.path.exists(live):
                # The slot holds the stock file we restored on disable — re-stash it (first
                # capture wins: keep an existing .moddy-orig and just drop the live copy).
                if not os.path.lexists(durable):
                    os.replace(live, durable)
                else:
                    _discard(live)
            os.rename(parked, live)
        else:
            if not os.path.exists(live):
                decky.logger.error(f"Source file not found: {live}")
                return False
            os.rename(live, parked)
            if os.path.lexists(durable):
                os.replace(durable, live)  # stock back into the vacated slot
        decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to toggle {mod_id}: {e}")
        return False
