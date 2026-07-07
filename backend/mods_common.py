import os
import mods
from registry import GameProfile, ModInfo
import decky
import utils
from install_txn import _MODDY_ORIG_SUFFIX, _discard


_LOVELYIGNORE = ".lovelyignore"


def _folder_mod_enabled(target_dirs: list[str], style: str = "dll") -> bool:
    """Whether a zip_dir folder mod is currently enabled.

    "dll"  (BepInEx): enabled iff at least one *.dll (not *.dll.disabled) exists in its
           tracked dirs — BepInEx only loads files ending in .dll. A tracked path may also
           be a bare *.dll file: some mods (e.g. Enforcer, the modular R2API libs) ship the
           DLL directly under BepInEx/plugins/ with no mod subfolder.
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
        if os.path.isdir(d):
            for _root, _dirs, files in os.walk(d):
                if any(f.endswith(".dll") for f in files):
                    return True
        # Bare DLL tracked directly (no subfolder): present .dll == enabled
        # (disabling renames it to *.dll.disabled).
        elif d.endswith(".dll") and os.path.isfile(d):
            return True
    return False


def _tracked_present(path: str) -> bool:
    """Whether a zip_dir mod's tracked path is on disk for this game — the dir/file exists,
    or (for a bare DLL) its disabled form does. Presence distinguishes a live install from
    an orphaned record whose files are gone."""
    return os.path.exists(path) or (path.endswith(".dll") and os.path.isfile(path + ".disabled"))


def mod_files_present(game: GameProfile, install_dir: str, record: dict) -> bool:
    """Whether a tracked mod's files are physically on disk for this game (enabled or disabled
    form). A record can outlive its files — uninstalling the BepInEx modloader rmtree's BepInEx/,
    deleting every plugin while their records remain — so "is it installed?" must check the disk,
    not just whether a record exists. Mirrors the per-install-type presence checks the installed
    tab's scan uses; an orphaned record (record present, files gone) returns False so a reinstall
    actually re-places the files instead of being skipped as a no-op."""
    source_type = (record.get("source") or {}).get("type")
    if source_type == "steamworkshop":
        return True  # Steam-managed subscription — files aren't under install_dir
    install_type = record.get("install_type") or (record.get("source") or {}).get("install_type") or "file"
    paths = record.get("paths")
    if install_type in ("zip_flat", "zip_natives", "zip_nativepc"):
        return _flat_mod_present(_flat_target_paths(install_dir, paths))
    if install_type in ("zip_folder", "external_merge"):
        return _zipfolder_present(install_dir, paths)
    if install_type == "zip_smapi":
        return _smapi_mod_present(_flat_target_paths(install_dir, paths))
    if install_type == "zip_dir" or paths:
        mods_path = mods.resolve_mods_path(game, install_dir)
        filename = record.get("filename") or ""
        target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]
        return any(_tracked_present(d) for d in target_dirs)
    mods_path = mods.resolve_mods_path(game, install_dir)
    filename = record.get("filename") or ""
    target = os.path.join(mods_path, filename)
    return os.path.isfile(target) or os.path.isfile(target + ".bak")


def _record_target_relpaths(game: GameProfile, install_dir: str, record: dict) -> list[str]:
    """A mod's tracked on-disk locations, install-dir-relative. paths-based records list them
    directly; folder/file records derive <mods_dir>/<filename>."""
    paths = record.get("paths")
    if paths:
        return list(paths)
    mods_path = mods.resolve_mods_path(game, install_dir)
    rel = os.path.relpath(os.path.join(mods_path, record.get("filename") or ""), install_dir)
    return [rel]


def _claimed_paths_map(appid: int, install_dir: str, mods_path: str, exclude_mod_id: str | None = None) -> dict:
    """Map every install-dir-absolute path Moddy has placed for THIS game (per its
    installed.json section) to the mod_id that claims it. Lets us tell a stock game file
    (unclaimed) from a Moddy-placed one, and spot mod-vs-mod overwrites. `exclude_mod_id`
    drops one record (the mod being installed/uninstalled) so its own paths don't count —
    e.g. on uninstall, to decide whether any OTHER mod still owns a slot before restoring
    the stock original."""
    out: dict[str, str] = {}
    for mod_id, record in (mods._load_store(appid) or {}).items():
        if mod_id == exclude_mod_id:
            continue
        paths = record.get("paths")
        if paths:
            for p in paths:
                out[os.path.normpath(os.path.join(install_dir, p))] = mod_id
        else:
            fn = record.get("filename")
            if fn:
                out[os.path.normpath(os.path.join(mods_path, fn))] = mod_id
    return out


def _overwrite_guard(appid: int, install_dir: str, mods_path: str, mod: ModInfo, dest_rels: list):
    """Build the `is_foreign` predicate a staged install passes to _StagedInstall, and log any
    mod-vs-mod overwrite among `dest_rels` (warn-and-proceed: the last install wins; the stock
    original, captured the first time any mod overwrote it, stays recoverable). is_foreign(p) is
    True when no installed record claims p — i.e. p is a stock game file or user-placed — so the
    transaction preserves it as *.moddy-orig on commit instead of discarding it. The mod's own
    prior paths ARE claimed (not foreign), so an upgrade's displaced old version is dropped as
    before, leaving the .v<ver>.bak version history to handle rollback."""
    claimed = _claimed_paths_map(appid, install_dir, mods_path)
    for rel in dest_rels:
        owner = claimed.get(os.path.normpath(os.path.join(install_dir, rel)))
        if owner and owner != mod.id:
            decky.logger.warning(
                f"{mod.name}: overwrites {rel} already provided by '{owner}' — last install wins")
    claimed_keys = set(claimed)
    return lambda p: os.path.normpath(p) not in claimed_keys


def _restore_originals(appid: int, install_dir: str, mods_path: str, abs_paths: list, exclude_mod_id: str) -> None:
    """On uninstall, move any durable *.moddy-orig stock backup back into place — but only for a
    path no OTHER installed mod still claims (last-claim restore). A path still owned by another
    mod keeps that mod's content; its stock original stays parked until the last owner goes."""
    others = set(_claimed_paths_map(appid, install_dir, mods_path, exclude_mod_id=exclude_mod_id))
    for p in abs_paths:
        durable = p + _MODDY_ORIG_SUFFIX
        if not os.path.lexists(durable) or os.path.normpath(p) in others:
            continue
        try:
            if os.path.lexists(p):
                _discard(p)
            os.replace(durable, p)
            decky.logger.info(f"Restored original {os.path.relpath(p, install_dir)}")
        except OSError as e:
            decky.logger.warning(f"Could not restore original {p}: {e}")


def _backup_version_dir(appid: int, dst_dir: str, mod_id: str) -> None:
    """Copy the currently-installed folder to <dir>.v<old>.bak for the version-history feature,
    when a versioned install is present. Best-effort and independent of atomicity — it preserves a
    snapshot of the version being replaced (see get_backed_up_versions / delete_mod_version)."""
    import shutil
    if not os.path.isdir(dst_dir):
        return
    old_version = mods.get_installed_version(appid, mod_id)
    if old_version and old_version != "latest":
        bak = dst_dir + f".v{old_version}.bak"
        if os.path.exists(bak):
            _discard(bak)
        shutil.copytree(dst_dir, bak)


def _atomic_dir_swap(dst_dir: str, staged_dir: str) -> None:
    """Replace dst_dir with the fully-built staged_dir as atomically as the filesystem allows, for
    a mod that wholly owns its folder. The existing dst_dir is renamed aside first and restored if
    the move fails, so dst_dir is never left missing or half-populated. staged_dir must be on the
    same filesystem as dst_dir (a sibling), so the move is a rename rather than a copy."""
    import shutil
    os.makedirs(os.path.dirname(dst_dir), exist_ok=True)
    aside = dst_dir + ".moddy-old"
    if os.path.lexists(aside):
        _discard(aside)  # stale crumb from an earlier crashed run
    had_old = os.path.lexists(dst_dir)
    if had_old:
        os.rename(dst_dir, aside)
    try:
        shutil.move(staged_dir, dst_dir)
    except Exception:
        if had_old and not os.path.lexists(dst_dir):
            os.rename(aside, dst_dir)  # put the old install back
        raise
    if had_old:
        _discard(aside)


async def _install_mod_file(game: GameProfile, install_dir: str, mods_path: str, mod: ModInfo, version: str | None, url: str | None) -> bool | None:
    """Install a single-file mod (DLL), backing up the previous version. When mods_path is the
    game root (mods_dir=""), the destination filename can collide with a stock game file; that
    original is preserved durably as *.moddy-orig so uninstall/disable can restore vanilla."""
    dst = os.path.join(mods_path, mod.filename)
    tmp = dst + ".tmp"
    backed_up = None
    try:
        decky.logger.info(f"Downloading {mod.name} from {utils.redact_url(url)}")
        await utils.download(url, tmp, game.appid)

        if os.path.isfile(dst):
            claimed = _claimed_paths_map(game.appid, install_dir, mods_path)
            owner = claimed.get(os.path.normpath(dst))
            if owner and owner != mod.id:
                decky.logger.warning(
                    f"{mod.name}: overwrites {mod.filename} already provided by '{owner}' — last install wins")
            old_version = mods.get_installed_version(game.appid, mod.id)
            durable = dst + _MODDY_ORIG_SUFFIX
            if old_version and old_version != "latest":
                bak = os.path.join(mods_path, f"{mod.filename}.v{old_version}.bak")
                os.rename(dst, bak)
                backed_up = bak
                decky.logger.info(f"Backed up {mod.filename} as {os.path.basename(bak)}")
            elif owner is None and not os.path.lexists(durable):
                # A file Moddy never placed — a stock game file. Preserve it instead of deleting,
                # so uninstall can put vanilla back. First capture wins (guarded by lexists).
                os.rename(dst, durable)
                backed_up = durable
                decky.logger.info(f"Preserved original {mod.filename} as {os.path.basename(durable)}")
            else:
                os.remove(dst)

        os.replace(tmp, dst)
        mods.set_installed_record(game.appid, mod.id, version or "latest", mod.filename, mod=mod)
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


def _flat_target_paths(install_dir: str, paths: list[str] | None) -> list[str]:
    """Absolute paths of a flat (zip_flat) mod's tracked top-level entries."""
    return [os.path.join(install_dir, p) for p in (paths or [])]


def _flat_mod_present(target_paths: list[str]) -> bool:
    """Whether a flat mod's files exist on disk (enabled OR disabled form). Used to scope a
    browsed flat mod to the game whose install dir actually holds it."""
    for p in target_paths:
        if os.path.exists(p) or os.path.exists(p + ".disabled"):
            return True
    return False


def _flat_mod_enabled(target_paths: list[str]) -> bool:
    """Whether a flat mod is enabled. MelonLoader loads `*.dll` directly from Mods/, so a
    disabled mod has its DLL renamed to `*.dll.disabled`. Enabled iff a tracked .dll is in
    active form; for asset-only mods (no tracked DLL) presence == enabled."""
    dll_paths = [p for p in target_paths if p.endswith(".dll")]
    if dll_paths:
        return any(os.path.isfile(p) for p in dll_paths)
    return any(os.path.exists(p) for p in target_paths)


def _natives_mod_enabled(target_paths: list[str]) -> bool:
    """Whether an RE4 loose (zip_natives) mod is enabled. REFramework's loose loader reads
    files under natives/ by exact path, so a disabled mod has each tracked file renamed to
    `*.disabled`. Enabled iff any tracked file is present in its active (non-disabled) form."""
    return any(os.path.isfile(p) for p in target_paths)


def _dotprefix_disabled(path: str) -> str:
    """The disabled form of a SMAPI mod folder: a leading dot on its basename
    (Mods/CoolMod -> Mods/.CoolMod). SMAPI ignores any entry under Mods/ whose name starts
    with '.', so renaming the folder this way disables the mod non-destructively — unlike the
    `.disabled` suffix the dll/natives loaders use, the marker is a prefix on the basename."""
    head, base = os.path.split(path.rstrip(os.sep))
    return os.path.join(head, "." + base)


def _smapi_mod_present(target_paths: list[str]) -> bool:
    """Whether a SMAPI (zip_smapi) mod's folders exist on disk in either form (enabled
    `Mods/<X>` or dot-disabled `Mods/.<X>`). Scopes a browsed mod to the game whose Mods/
    folder actually holds it — the install store is shared across games."""
    return any(os.path.exists(p) or os.path.exists(_dotprefix_disabled(p)) for p in target_paths)


def _smapi_mod_enabled(target_paths: list[str]) -> bool:
    """Whether a SMAPI mod is enabled — i.e. any tracked folder is present in its active
    (non-dot-prefixed) form. Disabling renames every tracked folder to its `.`-prefixed name."""
    return any(os.path.exists(p) for p in target_paths)


# zip_folder (No Man's Sky) disabled mods are parked here, at the game root OUTSIDE GAMEDATA/MODS/.
# The game scans GAMEDATA/MODS/ RECURSIVELY (device-confirmed), so an in-place `<mod>.disabled`
# rename does NOT hide a mod — a disabled mod must physically leave the MODS/ tree.
_FOLDER_DISABLED_DIR = ".moddy-disabled-mods"


def _zipfolder_disabled_path(install_dir: str, active_rel: str) -> str:
    """Where a disabled zip_folder mod is parked (game-root staging dir, outside MODS/)."""
    return os.path.join(install_dir, _FOLDER_DISABLED_DIR, os.path.basename(active_rel.rstrip("/\\")))


def _zipfolder_present(install_dir: str, paths: list[str] | None) -> bool:
    """A zip_folder mod is present (for this game) if its folder is live in MODS/ (enabled) or parked
    in the staging dir (disabled). Scopes a globally-keyed record to the game that actually holds it."""
    for rel in (paths or []):
        if os.path.isdir(os.path.join(install_dir, rel)) or os.path.isdir(_zipfolder_disabled_path(install_dir, rel)):
            return True
    return False


def _zipfolder_enabled(install_dir: str, paths: list[str] | None) -> bool:
    """Enabled iff the mod's folder is live under MODS/ (not parked in the disabled staging dir)."""
    return any(os.path.isdir(os.path.join(install_dir, rel)) for rel in (paths or []))


def _zipfolder_prune_staging(install_dir: str) -> None:
    """Remove the disabled-staging dir if it's now empty (keeps the game root tidy)."""
    staging = os.path.join(install_dir, _FOLDER_DISABLED_DIR)
    try:
        if os.path.isdir(staging) and not os.listdir(staging):
            os.rmdir(staging)
    except OSError:
        pass
