import os
import json
import shutil
import zipfile
import decky
import github
import mods
import nexus
import ficsit
import thunderstore
import utils
from install_txn import _StagedInstall
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


def get_modloader_paths(modloader_id: str) -> list[str]:
    """Game-dir-relative paths a loader install placed (tracked for loaders installed by merging a
    whole archive, e.g. Stracker's: dinput8.dll + loader.dll + loader-config.json + nativePC/plugins/*).
    Lets uninstall remove exactly what was installed without touching the shared nativePC tree. Empty
    for loaders installed before this was tracked, or that only place declared files/dirs."""
    return list(_load_version_store().get(modloader_id, {}).get("paths") or [])


def set_modloader_version(modloader_id: str, version: str, paths: list[str] | None = None) -> None:
    store = _load_version_store()
    entry = {"version": version}
    if paths:
        entry["paths"] = list(paths)
    store[modloader_id] = entry
    _save_version_store(store)


def clear_modloader_version(modloader_id: str) -> None:
    store = _load_version_store()
    if modloader_id in store:
        del store[modloader_id]
        _save_version_store(store)


# ── ficsit (Satisfactory / SML) loader: move-out enable/disable ───────────────
# SML is a UE plugin folder under FactoryGame/Mods/. The game discovers any plugin folder there by
# its `.uplugin`, so an in-place rename to Mods/SML.disabled does NOT stop it loading (the .uplugin
# is still found inside). Disabling therefore MOVES the folder out to a game-root staging dir
# (outside the Mods/ scan roots), mirroring how zip_smod mods are disabled. is_modloader_enabled
# already reads correctly (the indicator — Mods/SML — is gone once parked); is_modloader_installed
# and uninstall must additionally look at the parked copy.

def _ficsit_loader_dir(ml: ModloaderInfo) -> str:
    """The loader's mod-folder, game-dir-relative (e.g. 'FactoryGame/Mods/SML')."""
    return (ml.dirs[0] if ml.dirs else ml.indicator) or ""


def _ficsit_parked_dir(install_dir: str, ml: ModloaderInfo) -> str:
    """Where a disabled ficsit loader is parked: game-root staging, outside the Mods/ scan roots
    (the same staging dir zip_smod/zip_folder mods use), so SML genuinely stops loading."""
    leaf = os.path.basename(_ficsit_loader_dir(ml).rstrip("/\\"))
    return os.path.join(install_dir, mods._FOLDER_DISABLED_DIR, leaf)


def _move_ficsit_loader(install_dir: str, ml: ModloaderInfo, enable: bool) -> bool:
    active = os.path.join(install_dir, _ficsit_loader_dir(ml))
    parked = _ficsit_parked_dir(install_dir, ml)
    try:
        if enable:
            if os.path.isdir(parked) and not os.path.isdir(active):
                os.makedirs(os.path.dirname(active), exist_ok=True)
                shutil.move(parked, active)
        else:
            if os.path.isdir(active):
                os.makedirs(os.path.dirname(parked), exist_ok=True)
                shutil.move(active, parked)
        mods._zipfolder_prune_staging(install_dir)
        decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {ml.id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to {'enable' if enable else 'disable'} {ml.id}: {e}")
        return False


def _uninstall_ficsit_loader(install_dir: str, ml: ModloaderInfo) -> bool:
    """Remove SML whether it's live (Mods/SML) or parked (disabled). Both forms are whole-folder, so
    rmtree covers the tracked plugin files without the per-path loop."""
    try:
        for d in (os.path.join(install_dir, _ficsit_loader_dir(ml)), _ficsit_parked_dir(install_dir, ml)):
            if os.path.isdir(d):
                shutil.rmtree(d)
        mods._zipfolder_prune_staging(install_dir)
        clear_modloader_version(ml.id)
        decky.logger.info(f"Uninstalled {ml.id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {ml.id}: {e}")
        return False


def _loader_is_foreign(game: GameProfile, install_dir: str):
    """Build the is_foreign predicate a loader install hands to _StagedInstall. A destination file
    is 'foreign' (a stock game file — e.g. a game's own version.dll that a proxy loader overwrites)
    when no installed mod and no modloader has recorded placing it; the transaction then preserves
    it as *.moddy-orig instead of dropping it on commit, and uninstall restores it. This is the
    general path that replaces the old bespoke version.dll.deckhand_bak backup. Provenance is read
    from the store, so a loader's OWN files (recorded by its prior install) are not mistaken for
    stock on upgrade — only a genuine stock file at a fresh slot is captured."""
    claimed = set(mods._claimed_paths_map(install_dir, mods.resolve_mods_path(game, install_dir)))
    for _mid, rec in (_load_version_store() or {}).items():
        for p in (rec.get("paths") or []):
            claimed.add(os.path.normpath(os.path.join(install_dir, p)))
    return lambda p: os.path.normpath(p) not in claimed


def is_modloader_installed(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.native:
        return True  # platform-provided (e.g. Steam Workshop) — nothing to install
    if ml.source.type == "ficsit":
        # SML lives at Mods/SML when enabled, or parked in the disabled-staging dir — installed if
        # either exists. (There's no <indicator>.disabled form: disabling moves the folder out.)
        return (os.path.isdir(os.path.join(install_dir, _ficsit_loader_dir(ml)))
                or os.path.isdir(_ficsit_parked_dir(install_dir, ml)))
    if ml.source.type == "setup":
        # A setup loader places no files; "installed" = its version-store entry, while
        # is_modloader_enabled tracks the live sentinel (indicator). Otherwise DISABLING it (which
        # removes the sentinel, and a setup loader has no <indicator>.disabled form) would read as
        # "not installed" — the Mod Loader tab would drop the toggle and offer to re-install, and
        # Reset Game would skip uninstalling it (main.py gates uninstall on is_modloader_installed).
        return get_modloader_version(modloader_id) is not None
    if not ml.indicator:
        return False
    return (
        os.path.exists(os.path.join(install_dir, ml.indicator)) or
        os.path.exists(os.path.join(install_dir, ml.indicator + ".disabled"))
    )


def is_modloader_enabled(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.native:
        return True
    if not ml.indicator:
        return False
    return os.path.exists(os.path.join(install_dir, ml.indicator))


def is_modloader_ready(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.native:
        return True
    if ml.ready_indicator:
        return os.path.exists(os.path.join(install_dir, ml.ready_indicator))
    return is_modloader_installed(game, install_dir, modloader_id)


async def enable_modloader(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.native:
        return True
    if ml.source.type == "ficsit":
        return _move_ficsit_loader(install_dir, ml, enable=True)  # move SML back into Mods/
    try:
        _apply_setup_removes(install_dir, ml)   # re-park setup files (e.g. NMS DISABLEMODS.TXT) on re-enable / leaving vanilla; no-op without a `setup` block
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
    if ml.native:
        return True
    if ml.source.type == "ficsit":
        return _move_ficsit_loader(install_dir, ml, enable=False)  # move SML out of Mods/ (scan roots)
    try:
        _restore_setup_removes(install_dir, ml)   # restore setup files (e.g. NMS DISABLEMODS.TXT) so mods stop loading on disable / entering vanilla; no-op without a `setup` block
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


def _remove_uninstall_artifacts(install_dir: str, ml: ModloaderInfo) -> None:
    """Remove a loader's `uninstall_files`/`uninstall_dirs` — its on-disk footprint that Moddy does
    NOT install but should clean up: REFramework's runtime-generated reframework/ dir + logs, or
    Stracker's bundled nativePC/plugins/* (MonsterLoader/QuestLoader — error-prone, intentionally not
    installed; this also clears any a previous Moddy build left behind). Empties dirs are pruned."""
    removed_files: list[str] = []
    for f in ml.uninstall_files:
        for candidate in [f, f + ".disabled"]:
            path = os.path.join(install_dir, candidate)
            if os.path.isfile(path):
                os.remove(path)
                removed_files.append(candidate)
    if removed_files:
        mods._prune_empty_dirs(install_dir, removed_files)
    for d in ml.uninstall_dirs:
        # Defensive: never let a stray/empty entry resolve to the game root and rmtree it.
        if not d or os.path.normpath(d) in (".", os.sep, ""):
            continue
        for candidate in [d, d + ".disabled"]:
            path = os.path.join(install_dir, candidate)
            if os.path.normpath(path) == os.path.normpath(install_dir):
                continue
            if os.path.isdir(path):
                shutil.rmtree(path)


async def uninstall_modloader(game: GameProfile, install_dir: str, modloader_id: str) -> bool:
    ml = game.get_modloader(modloader_id)
    if not ml:
        return False
    if ml.native:
        return True
    if ml.source.type == "ficsit":
        return _uninstall_ficsit_loader(install_dir, ml)  # whole-folder removal (live or parked)
    try:
        # Loaders installed by merging a whole archive (Stracker's: dinput8.dll, loader.dll,
        # loader-config.json, nativePC/plugins/*) tracked every placed path — remove exactly those
        # (and their .disabled forms), then prune any dirs they emptied, so the shared nativePC tree
        # and other mods' files survive.
        tracked_paths = get_modloader_paths(modloader_id)
        for relpath in tracked_paths:
            for candidate in [relpath, relpath + ".disabled"]:
                path = os.path.join(install_dir, candidate)
                if os.path.isfile(path):
                    os.remove(path)
        if tracked_paths:
            mods._prune_empty_dirs(install_dir, tracked_paths)
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
        _remove_uninstall_artifacts(install_dir, ml)
        _restore_setup_removes(install_dir, ml)  # bring back a setup loader's parked file (e.g. NMS DISABLEMODS.TXT); the placed-paths/_restore_originals path can't, since it parks files it never "placed". No-op without a `setup` block
        # Restore any stock game file this loader overwrote at install (e.g. a game's own
        # version.dll a proxy loader replaced), preserved as *.moddy-orig — the general path that
        # replaces the old bespoke version.dll.deckhand_bak restore.
        restore_candidates = [os.path.join(install_dir, p) for p in tracked_paths] + \
                             [os.path.join(install_dir, f) for f in ml.files]
        mods._restore_originals(install_dir, mods.resolve_mods_path(game, install_dir),
                                restore_candidates, modloader_id)
        clear_modloader_version(modloader_id)
        decky.logger.info(f"Uninstalled {modloader_id}")
        return True
    except Exception as e:
        decky.logger.error(f"Failed to uninstall {modloader_id}: {e}")
        return False


async def install_modloader(game: GameProfile, install_dir: str, modloader_id: str, version: str | None = None) -> "bool | str":
    """Install a modloader for a game. Returns True on success, False on failure, or the string
    "premium_required" when a Nexus-sourced loader (e.g. Stracker's Loader for MHW) can't be
    downloaded because the configured Nexus key isn't Premium — so the UI can show a specific
    message instead of a generic failure."""
    ml = game.get_modloader(modloader_id)
    if not ml:
        decky.logger.error(f"Unknown modloader: {modloader_id}")
        return False
    if ml.native:
        return True  # platform-provided (e.g. Steam Workshop) — nothing to install
    if ml.source.type == "github" and ml.source.install_type == "smapi_installer":
        ok = await _install_smapi_modloader(game, install_dir, ml, version)
    elif ml.source.type == "github":
        ok = await _install_github_modloader(game, install_dir, ml, version)
    elif ml.source.type == "thunderstore":
        ok = await _install_thunderstore_modloader(game, install_dir, ml, version)
    elif ml.source.type == "nexus":
        ok = await _install_nexus_modloader(game, install_dir, ml, version)
    elif ml.source.type == "ficsit":
        ok = await _install_ficsit_modloader(game, install_dir, ml, version)
    elif ml.source.type == "setup":
        ok = await _install_setup_modloader(game, install_dir, ml, version)
    else:
        decky.logger.error(f"Unsupported modloader source type: {ml.source.type}")
        return False
    if ok is True and ml.config_files:
        _apply_config_files(install_dir, ml)
    return ok


def _config_key(line: str) -> str:
    """The key of a REFramework config line. re2_fw_config.txt is `Key=Value` per line, so the
    key is everything before the first '=' (blank/`=`-less lines have no key)."""
    s = line.strip()
    return s.split("=", 1)[0].strip() if "=" in s else ""


def _apply_config_files(install_dir: str, ml: ModloaderInfo) -> None:
    """Write a modloader's post-install config files (e.g. REFramework's `re2_fw_config.txt` —
    in the game root, the fixed name REFramework reads for every RE Engine game — with
    `LooseFileLoader_Enabled=true`, which is what makes it read loose `natives/` mods). Each
    entry maps a game-dir-relative path to `Key=Value` lines. Existing keys are overridden and any
    unrelated lines preserved, so the rest of a user's REFramework settings (the full file it
    rewrites on a clean exit) aren't clobbered on reinstall/update."""
    for rel_path, content in ml.config_files.items():
        try:
            dst = os.path.join(install_dir, rel_path)
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            # Desired key → full line.
            desired: dict[str, str] = {}
            order: list[str] = []
            for line in content.splitlines():
                key = _config_key(line)
                if not key:
                    continue
                desired[key] = line.strip()
                order.append(key)
            out_lines: list[str] = []
            seen: set[str] = set()
            if os.path.isfile(dst):
                with open(dst, "r") as f:
                    for line in f.read().splitlines():
                        key = _config_key(line)
                        if key and key in desired:
                            out_lines.append(desired[key])  # override existing
                            seen.add(key)
                        else:
                            out_lines.append(line)  # preserve unrelated settings
            for key in order:
                if key not in seen:
                    out_lines.append(desired[key])
            with open(dst, "w") as f:
                f.write("\n".join(out_lines) + "\n")
            decky.logger.info(f"Applied config file {rel_path} for {ml.id}")
        except Exception as e:
            decky.logger.error(f"Failed to write config file {rel_path} for {ml.id}: {e}")


def _setup_remove_files(ml: ModloaderInfo) -> list[str]:
    """Game-dir-relative stock files a source.type=="setup" loader parks aside to enable mods.
    Empty for every other loader, so the apply/restore calls below are no-ops elsewhere."""
    return list((ml.setup or {}).get("remove_files", []) or [])


def _apply_setup_removes(install_dir: str, ml: ModloaderInfo) -> None:
    """ENABLE mods: park each declared stock file aside to <f>.moddy-orig (which doubles as the
    loader's 'set up' indicator) and remove it from its live path — e.g. No Man's Sky only loads
    GAMEDATA/MODS/ mods when GAMEDATA/PCBANKS/DISABLEMODS.TXT is absent. First-capture-wins: an
    existing backup is never overwritten (so re-enabling after vanilla can't clobber the genuine
    original). If the live file is absent, an empty sentinel is still written so the indicator
    reliably reports 'set up'. No-op for loaders without a `setup` block."""
    for rel in _setup_remove_files(ml):
        live = os.path.join(install_dir, rel)
        durable = live + mods._MODDY_ORIG_SUFFIX
        os.makedirs(os.path.dirname(durable) or ".", exist_ok=True)
        if os.path.lexists(durable):
            # Genuine original already captured; just clear the live file if it reappeared
            # (e.g. a game update regenerated DISABLEMODS.TXT).
            if os.path.isfile(live):
                os.remove(live)
        elif os.path.isfile(live):
            os.replace(live, durable)        # back up + remove in one atomic move
        else:
            open(durable, "w").close()       # no live file: empty sentinel still marks 'set up'


def _restore_setup_removes(install_dir: str, ml: ModloaderInfo) -> None:
    """DISABLE mods (inverse of _apply_setup_removes): restore each declared file from its
    <f>.moddy-orig sentinel and drop the sentinel. A non-empty sentinel is the captured stock file
    -> restored byte-exact. An empty sentinel (the stock file was blank, as NMS's DISABLEMODS.TXT
    is, or never existed) -> leave an empty file in place so mods stay disabled. No sentinel ->
    nothing to do. No-op for loaders without a `setup` block."""
    for rel in _setup_remove_files(ml):
        live = os.path.join(install_dir, rel)
        durable = live + mods._MODDY_ORIG_SUFFIX
        if not os.path.lexists(durable):
            continue
        if os.path.isfile(live):
            os.remove(live)
        if os.path.getsize(durable) > 0:
            os.replace(durable, live)        # restore captured stock file exactly
        else:
            os.remove(durable)               # drop empty sentinel...
            os.makedirs(os.path.dirname(live) or ".", exist_ok=True)
            open(live, "w").close()          # ...and leave an empty file so mods stay disabled


async def _install_setup_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """A source.type=="setup" loader installs no files — it performs the declared host-side setup
    (parking game files aside to enable mods). For NMS this parks GAMEDATA/PCBANKS/DISABLEMODS.TXT
    so the game loads loose mods from GAMEDATA/MODS/. No tracked paths: uninstall restores via
    _restore_setup_removes, not the placed-paths loop."""
    try:
        _apply_setup_removes(install_dir, ml)
        set_modloader_version(ml.id, version or "setup")
        decky.logger.info(f"Set up {ml.id}")
        return True
    except Exception as e:
        decky.logger.error(f"Setup loader {ml.id} failed: {e}")
        return False


async def _install_ficsit_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """Install SML (Satisfactory Mod Loader) from ficsit.app. SML is itself a ficsit mod (its
    mod_reference is on ml.source.mod_reference) — a UE-plugin .smod whose loose files (SML.uplugin,
    Binaries/Win64/*, Content/Paks/*) install into the loader's own folder, Mods/SML/ (ml.dirs[0]).
    Unlike every other Moddy loader there is NO DLL proxy or WINEDLLOVERRIDES launch option: the game
    loads plugins from Mods/ natively (it's force-Proton'd so the Win64 binaries run). Every placed
    file is tracked so uninstall removes exactly SML's footprint. `version` pins a specific ficsit
    version (from the Mod Loader tab's picker); None installs the latest."""
    ref = ml.source.mod_reference
    if not ref:
        decky.logger.error(f"{ml.id}: ficsit source missing mod_reference")
        return False
    target_dir = _ficsit_loader_dir(ml)  # e.g. "FactoryGame/Mods/SML"
    if not target_dir:
        decky.logger.error(f"{ml.id}: ficsit loader has no dirs/indicator to install into")
        return False

    if version:
        # A pinned version from the Mod Loader tab's picker: resolve its (Windows-buildable) version id.
        match = next((v for v in ficsit.list_versions(ref)
                      if v["version"] == version and ficsit.TARGET in v["targets"] and v["version_id"]), None)
        if not match:
            decky.logger.error(f"{ml.name}: version {version} not found on ficsit.app or has no {ficsit.TARGET} build")
            return False
        version_id, resolved_version = match["version_id"], version
    else:
        mod = ficsit.get_mod(ref)
        win = ficsit.windows_version(mod) if mod else None
        if not win or not win.get("version_id"):
            decky.logger.error(f"{ml.name}: no installable Windows build found on ficsit.app ({ref})")
            return False
        version_id, resolved_version = win["version_id"], (win["version"] or "latest")
    url = ficsit.download_url(version_id)

    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.smod")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")
    # A prior disable parked SML outside Mods/. Note whether it was disabled coming in (parked exists,
    # active doesn't) so we can restore that state after a successful update instead of silently
    # re-enabling it. The parked copy is retired INSIDE the transaction below — NOT rmtree'd up front —
    # so a failed download/extract can't destroy a working (installed-but-disabled) SML.
    parked = _ficsit_parked_dir(install_dir, ml)
    parked_rel = os.path.join(mods._FOLDER_DISABLED_DIR, os.path.basename(target_dir.rstrip("/\\")))
    was_disabled = os.path.isdir(parked) and not os.path.isdir(os.path.join(install_dir, target_dir))
    try:
        decky.logger.info(f"Downloading {ml.name} {resolved_version} from ficsit.app")
        await utils.download(url, tmp_archive, game.appid)

        decky.logger.info(f"Extracting {ml.name}")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        mods.extract_archive(tmp_archive, tmp_dir)   # .smod is a PK zip

        # Place every plugin file under Mods/SML/, tracking each path. Retire the old SML dir AND any
        # parked (disabled) copy first — both inside the transaction — for a clean, all-or-nothing
        # replacement: on failure they roll back (no data loss), on success they're dropped (no stale
        # files, no coexisting active+parked SML). is_foreign is NOT used here: Mods/SML is a fresh,
        # wholly Moddy-owned plugin folder (it overwrites no stock game file), so the displaced old dir
        # must simply be dropped on commit — preserving it as *.moddy-orig would litter Mods/ with an
        # SML.moddy-orig on every update.
        placed: list[str] = []
        with _StagedInstall(install_dir) as txn:
            txn.retire(target_dir)
            txn.retire(parked_rel)   # replace a disabled SML in place, rollback-safe (no up-front rmtree)
            for root, _dirs, files in os.walk(tmp_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.join(target_dir, os.path.relpath(full, tmp_dir))
                    txn.place(full, rel)
                    placed.append(rel)
        if not placed:
            decky.logger.error(f"{ml.name}: archive contained no files")
            return False

        set_modloader_version(ml.id, resolved_version, paths=sorted(placed))
        # Preserve the user's disabled state across an update: the new files committed to active
        # Mods/SML, so re-park them if SML was disabled before.
        if was_disabled:
            _move_ficsit_loader(install_dir, ml, enable=False)
        decky.logger.info(f"{ml.name} {resolved_version} installed successfully ({len(placed)} file(s))")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"{ml.name} installation was cancelled")
        return False
    except Exception as e:
        decky.logger.error(f"{ml.name} installation failed: {e}")
        return False
    finally:
        if os.path.exists(tmp_archive):
            os.remove(tmp_archive)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)


async def _install_thunderstore_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """Install a Thunderstore-sourced modloader (BepInExPack pattern)."""
    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.zip")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")
    try:
        if version:
            url = thunderstore.get_download_url(ml.source.owner, ml.source.repo, version)
            resolved_version = version
        else:
            latest = thunderstore.get_latest(ml.source.owner, ml.source.repo)
            if not latest:
                decky.logger.error(f"Could not resolve latest {ml.id} release from Thunderstore")
                return False
            resolved_version = latest["version"]
            url = latest["download_url"]

        decky.logger.info(f"Downloading {ml.name} {resolved_version} from {utils.redact_url(url)}")
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

        # Place every file under inner_path into the game dir in one transaction. This MERGES rather
        # than replacing whole dirs, so updating BepInEx overwrites only its own files and leaves a
        # user's BepInEx/plugins/ intact (the old rmtree+copytree wiped them). Any failure rolls the
        # game dir back to its prior state.
        placed: list[str] = []
        with _StagedInstall(install_dir, is_foreign=_loader_is_foreign(game, install_dir)) as txn:
            for root, _dirs, files in os.walk(inner_path):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, inner_path)
                    txn.place(full, rel)
                    placed.append(rel)

        set_modloader_version(ml.id, resolved_version, paths=sorted(placed))
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


async def _install_nexus_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> "bool | str":
    """Install a Nexus-sourced modloader (Stracker's Loader pattern). Unlike GitHub/Thunderstore
    loaders, Nexus has no public release feed, so we resolve the mod's primary file and a direct
    CDN link via the v1 API — which requires a Nexus Premium key (free accounts can't get API
    download links). Mirrors how browsed Nexus mods are fetched. Returns "premium_required" if the
    key isn't Premium. `version` is ignored: we always install the mod's current primary file (Nexus
    file ids aren't user-selectable here)."""
    domain = ml.source.nexus_domain
    mod_id = ml.source.mod_id
    if not domain or not mod_id:
        decky.logger.error(f"{ml.id}: nexus source missing nexus_domain/mod_id")
        return False

    try:
        file_id = nexus.primary_file_id(domain, mod_id)
        if not file_id:
            decky.logger.error(f"{ml.name}: no downloadable file found on Nexus ({domain}/{mod_id})")
            return False
        url = nexus.get_download_url(domain, mod_id, file_id)
    except nexus.PremiumRequired:
        decky.logger.error(f"{ml.name}: a Nexus Premium account is required to download the loader")
        return "premium_required"
    except Exception as e:
        decky.logger.error(f"{ml.name}: failed to resolve Nexus download: {e}")
        return False
    if not url:
        decky.logger.error(f"{ml.name}: could not resolve a Nexus download URL")
        return False

    mod_meta = nexus.get_mod(domain, mod_id) or {}
    resolved_version = str(mod_meta.get("version", "") or "") or "latest"

    tmp_archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.archive")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")

    try:
        decky.logger.info(f"Downloading {ml.name} {resolved_version} from Nexus")
        await utils.download(url, tmp_archive, game.appid)

        decky.logger.info(f"Extracting {ml.name}")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        mods.extract_archive(tmp_archive, tmp_dir)

        # Nexus archives often wrap the payload in a folder (e.g. "Stracker's Loader/"). Locate the
        # directory that actually holds the loader file (ml.files[0], e.g. dinput8.dll) and install
        # from there; fall back to the extract root.
        inner_path = tmp_dir
        marker = ml.files[0] if ml.files else None
        if marker:
            for root, _dirs, files in os.walk(tmp_dir):
                if marker in files:
                    inner_path = root
                    break

        for f in ml.files:
            if not os.path.isfile(os.path.join(inner_path, f)):
                raise Exception(f"Expected file missing from archive: {f}")
        for d in ml.dirs:
            if not os.path.isdir(os.path.join(inner_path, d)):
                raise Exception(f"Expected directory missing from archive: {d}")

        # Install the ENTIRE archive merged into the game root — Stracker's Loader is more than its
        # dinput8.dll proxy: the zip also ships loader.dll (the actual loader the proxy hands off to),
        # loader-config.json, and nativePC/plugins/*. Installing only dinput8.dll leaves the proxy with
        # nothing to load → the generic "Stracker's loader error" popup. Every placed path is tracked
        # so uninstall removes exactly these (never the shared nativePC tree wholesale).
        placed: list[str] = []
        with _StagedInstall(install_dir, is_foreign=_loader_is_foreign(game, install_dir)) as txn:
            for root, _dirs, files in os.walk(inner_path):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, inner_path)
                    txn.place(full, rel)
                    placed.append(rel)

        set_modloader_version(ml.id, resolved_version, paths=placed)
        decky.logger.info(f"{ml.name} {resolved_version} installed successfully ({len(placed)} file(s))")
        return True
    except utils.InstallCancelledError:
        decky.logger.info(f"{ml.name} installation was cancelled")
        return False
    except Exception as e:
        decky.logger.error(f"{ml.name} installation failed: {e}")
        return False
    finally:
        if os.path.exists(tmp_archive):
            os.remove(tmp_archive)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)


async def _install_smapi_modloader(game: GameProfile, install_dir: str, ml: ModloaderInfo, version: str | None = None) -> bool:
    """Install SMAPI for Stardew Valley — the Proton / Windows-build path.

    SMAPI is a launcher REPLACEMENT, not a WINEDLLOVERRIDES DLL proxy like every other Moddy loader:
    the Windows SMAPI files are dropped into the game folder and the game is then launched via
    StardewModdingAPI.exe through the loader's sed-rewrite launch option (applied by the frontend,
    not here). SMAPI ships from GitHub (Pathoschild/SMAPI) as an interactive INSTALLER, not a plain
    file tree — the runnable files live in `internal/windows/install.dat` (a zip renamed to .dat). We
    extract the installer, extract install.dat into the game folder, then synthesize
    `StardewModdingAPI.deps.json` by copying the game's `Stardew Valley.deps.json` (the documented
    manual-install step). Every placed file is tracked so uninstall removes exactly SMAPI's footprint
    (including the two helper mods it bundles under Mods/) and never the user's other mods."""
    # The installer asset name embeds the version (SMAPI-<ver>-installer.zip), so it can't be a fixed
    # asset string in the registry — resolve it from the release here.
    if version:
        asset = f"SMAPI-{version}-installer.zip"
        url = github.get_download_url_for_version(ml.source.owner, ml.source.repo, version, asset)
        resolved_version = version
    else:
        latest = github.get_latest_release_assets(ml.source.owner, ml.source.repo)
        if not latest:
            decky.logger.error(f"Could not resolve latest {ml.id} release from GitHub")
            return False
        resolved_version, assets = latest
        # Pick "SMAPI-<ver>-installer.zip", NOT the "-installer-double-zipped.zip" browser variant.
        url = next(
            (u for n, u in assets.items() if n.endswith("-installer.zip") and "double-zipped" not in n),
            None,
        )
    if not url:
        decky.logger.error(f"{ml.name}: could not resolve a SMAPI installer download URL")
        return False

    tmp_zip = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_tmp.zip")
    tmp_dir = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_extract")
    tmp_payload = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{ml.id}_payload")
    try:
        decky.logger.info(f"Downloading {ml.name} {resolved_version} from {utils.redact_url(url)}")
        await utils.download(url, tmp_zip, game.appid)

        for d in (tmp_dir, tmp_payload):
            if os.path.exists(d):
                shutil.rmtree(d)
        os.makedirs(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(tmp_dir)

        # Locate internal/windows/install.dat — the Windows payload that drops into the game folder.
        # (The Proton path runs the Windows build, so we install that, not internal/linux.)
        dat_path = None
        for root, _dirs, files in os.walk(tmp_dir):
            if "install.dat" in files and os.path.basename(root).lower() == "windows":
                dat_path = os.path.join(root, "install.dat")
                break
        if not dat_path:
            raise Exception("SMAPI installer did not contain internal/windows/install.dat")

        os.makedirs(tmp_payload)
        with zipfile.ZipFile(dat_path, "r") as z:  # install.dat is a zip renamed to .dat
            z.extractall(tmp_payload)

        # Synthesize StardewModdingAPI.deps.json from the game's deps file (manual-install step 3) so
        # .NET resolves the game's dependencies when launched via SMAPI.
        game_deps = os.path.join(install_dir, "Stardew Valley.deps.json")
        if os.path.isfile(game_deps):
            shutil.copyfile(game_deps, os.path.join(tmp_payload, "StardewModdingAPI.deps.json"))
        else:
            decky.logger.warning(
                f"{ml.name}: 'Stardew Valley.deps.json' not found in game folder — SMAPI may fail to "
                "start (is the game installed and up to date?)"
            )

        # Merge the whole payload into the game folder, tracking each placed file so uninstall removes
        # exactly SMAPI's footprint and leaves the user's other mods under Mods/ intact.
        placed: list[str] = []
        with _StagedInstall(install_dir, is_foreign=_loader_is_foreign(game, install_dir)) as txn:
            for root, _dirs, files in os.walk(tmp_payload):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, tmp_payload)
                    txn.place(full, rel)
                    placed.append(rel)

        set_modloader_version(ml.id, resolved_version, paths=placed)
        decky.logger.info(f"{ml.name} {resolved_version} installed successfully ({len(placed)} file(s))")
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
        for d in (tmp_dir, tmp_payload):
            if os.path.exists(d):
                shutil.rmtree(d)


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

    try:
        decky.logger.info(f"Downloading {ml.name} {resolved_version} from {utils.redact_url(url)}")
        await utils.download(url, tmp_zip, game.appid)

        decky.logger.info(f"Extracting {ml.name}")
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(tmp_dir)

        if ml.source.base_dir:
            # Merge the ENTIRE archive under install_dir/<base_dir>/ — the zip's root contents install
            # into a game subdir, not the game root (UE4SS: dwmapi.dll + ue4ss/ at the zip root →
            # Pal/Binaries/Win64/). ml.files/dirs are full game-dir-relative paths (used by
            # indicator/enable/disable/uninstall). On UPDATE we retire only the loader's OWN previously-
            # placed files (the tracked paths), NOT the whole base_dir tree: Win64/ue4ss/Mods/ also holds
            # the user's Lua mods, so wholesale-retiring it would wipe them. is_foreign is NOT used: the
            # loader's files are wholly Moddy-owned, so the displaced old files are dropped on commit,
            # not littered as *.moddy-orig.
            # Verify the archive ships what we expect, by BASENAME (base_dir archives carry ml.files/
            # dirs' contents at the zip root, not under their full game-relative path). Aborts cleanly
            # before the transaction if a future release restructured/renamed the payload — better than
            # committing a proxy with no runtime and reporting success.
            if ml.files and not os.path.isfile(os.path.join(tmp_dir, os.path.basename(ml.files[0]))):
                raise Exception(f"Expected proxy file missing from zip: {os.path.basename(ml.files[0])}")
            for d in ml.dirs:
                dn = os.path.basename(d.rstrip("/\\"))
                if not os.path.isdir(os.path.join(tmp_dir, dn)):
                    raise Exception(f"Expected directory missing from zip: {dn}")
            # Preserve the user's disabled state across an update: re-disable after committing. First
            # un-park (rename ue4ss.disabled → ue4ss) so the retire/place act on the tracked (enabled)
            # paths in place — otherwise the tracked-path retire would miss the parked files and leave
            # an orphaned ue4ss.disabled/.
            was_disabled = (is_modloader_installed(game, install_dir, ml.id)
                            and not is_modloader_enabled(game, install_dir, ml.id))
            if was_disabled:
                await enable_modloader(game, install_dir, ml.id)
            placed: list[str] = []
            with _StagedInstall(install_dir) as txn:
                for rel in get_modloader_paths(ml.id):   # retire only the prior install's own files
                    txn.retire(rel)
                for f in ml.files:
                    txn.retire(f)
                for root, _dirs, files in os.walk(tmp_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        rel = os.path.join(ml.source.base_dir, os.path.relpath(full, tmp_dir))
                        txn.place(full, rel)
                        placed.append(rel)
            set_modloader_version(ml.id, resolved_version, paths=sorted(placed))
            if was_disabled:
                await disable_modloader(game, install_dir, ml.id)
            decky.logger.info(f"{ml.name} {resolved_version} installed under {ml.source.base_dir} ({len(placed)} file(s))")
            return True

        # Verify expected files
        for f in ml.files:
            if not os.path.isfile(os.path.join(tmp_dir, f)):
                raise Exception(f"Expected file missing from zip: {f}")
        for d in ml.dirs:
            if not os.path.isdir(os.path.join(tmp_dir, d)):
                raise Exception(f"Expected directory missing from zip: {d}")

        # Place the loader's files and dirs into the game dir in one transaction. Its dirs (e.g.
        # MelonLoader/) are loader-owned, so retire them first for a clean replacement (no stale
        # files from an old version); a failure rolls the game dir back to its prior state. A stock
        # game file the loader's proxy (e.g. version.dll) overwrites is preserved as *.moddy-orig,
        # replacing the old bespoke .deckhand_bak backup/rollback dance.
        placed: list[str] = []
        with _StagedInstall(install_dir, is_foreign=_loader_is_foreign(game, install_dir)) as txn:
            for d in ml.dirs:
                txn.retire(d)
            for f in ml.files:
                txn.place(os.path.join(tmp_dir, f), f)
                placed.append(f)
            for d in ml.dirs:
                dsrc = os.path.join(tmp_dir, d)
                for root, _dirs, files in os.walk(dsrc):
                    for fn in files:
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, tmp_dir)
                        txn.place(full, rel)
                        placed.append(rel)

        set_modloader_version(ml.id, resolved_version, paths=sorted(placed))
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
