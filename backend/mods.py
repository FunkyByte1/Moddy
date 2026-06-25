import os
import json
import re
import time
import decky
from registry import GameProfile, ModInfo
import steam
import utils

# A freshly-recorded Workshop install isn't in GetSubscribedWorkshopItems yet
# (SteamClient subscribe is async), so reconcile must not drop records this young.
_RECONCILE_GRACE_SECONDS = 180


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


# ── Vanilla-mode snapshot ─────────────────────────────────────────────────────
# When a game is switched to "vanilla" (play unmodded) we disable every enabled mod and the
# modloader, recording WHAT was enabled so switching back restores exactly that state — a mod the
# user had individually disabled stays disabled. Stored under installed.json's own "vanilla" key,
# keyed by appid, alongside (never clobbering) the "mods" and "modloaders" sections.

def _read_full_store() -> dict:
    try:
        path = _get_store_path()
        if os.path.isfile(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        decky.logger.error(f"Failed to read installed store: {e}")
    return {}


def get_vanilla_state(appid: int) -> dict | None:
    """The snapshot captured when this game entered vanilla mode, or None if it isn't vanilla.
    Shape: {"mods": [enabled mod ids], "modloader": <ml id or None>, "workshop": [fileids]}."""
    return (_read_full_store().get("vanilla") or {}).get(str(appid))


def is_game_vanilla(appid: int) -> bool:
    return get_vanilla_state(appid) is not None


def set_vanilla_state(appid: int, snapshot: dict | None) -> None:
    """Persist (snapshot) or clear (None) a game's vanilla snapshot, preserving the rest of
    installed.json. Atomic write."""
    path = _get_store_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        full = _read_full_store()
        vanilla = full.get("vanilla") or {}
        if snapshot is None:
            vanilla.pop(str(appid), None)
        else:
            vanilla[str(appid)] = snapshot
        if vanilla:
            full["vanilla"] = vanilla
        else:
            full.pop("vanilla", None)
        with open(tmp, "w") as f:
            json.dump(full, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        decky.logger.error(f"Failed to save vanilla state: {e}")
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
    mods be uninstalled, toggled, and update-checked later from the record alone."""
    store = _load_store()
    record: dict = {"version": version, "filename": filename}
    # Stamp when the mod first entered the library so the Installed tab can offer a
    # "recently downloaded" sort. Preserve an existing record's timestamp across version
    # changes / re-installs so updating a mod doesn't reshuffle it to the top.
    record["added_at"] = (store.get(mod_id) or {}).get("added_at", time.time())
    if paths:
        record["paths"] = paths
    if mod is not None:
        record["source"] = {
            "type": mod.source.type,
            "owner": mod.source.owner,
            "repo": mod.source.repo,
            "asset": mod.source.asset,
            "install_type": mod.source.install_type,
            "workshop_id": mod.source.workshop_id,
            "nexus_domain": mod.source.nexus_domain,
            "mod_id": mod.source.mod_id,
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


def find_installed_record(mod_id: str) -> dict | None:
    """Like get_installed_record, but case-insensitive on the mod id. Install ids come
    from catalogs whose casing may differ from what was originally persisted, so an
    exact-key miss falls back to a case-insensitive scan of the store keys."""
    store = _load_store()
    record = store.get(mod_id)
    if record is not None:
        return record
    target = mod_id.lower()
    for k, v in store.items():
        if k.lower() == target:
            return v
    return None


def installed_files_present(game: GameProfile, install_dir: str, mod_id: str) -> bool:
    """True if `mod_id` has an install record (matched case-insensitively) AND its tracked
    files are actually on disk. The dependency cascades use this to decide whether a mod is
    already installed: a record alone isn't enough, because uninstalling a modloader can
    orphan records whose files are gone, and a stale record must not turn a reinstall into a
    silent no-op."""
    record = find_installed_record(mod_id)
    return record is not None and mod_files_present(game, install_dir, record)


def set_mod_enabled(mod_id: str, enabled: bool) -> None:
    """Persist a mod's enabled flag in its install record. Used by Workshop mods,
    whose enable/disable is a local Steam flag (SetWorkshopItemsDisabledLocally,
    applied in the frontend) rather than file presence on disk."""
    store = _load_store()
    if mod_id in store:
        store[mod_id]["enabled"] = enabled
        _save_store(store)


# Workshop unsubscribe is async (SteamClient), so just-deleted items still appear in
# GetSubscribedWorkshopItems for a moment. We tombstone them so reconcile doesn't re-add
# the record the user just removed (the mirror of the install grace period).
def _load_pending_unsub() -> dict:
    path = _get_store_path()
    if os.path.isfile(path):
        try:
            with open(path, "r") as f:
                return json.load(f).get("workshop_unsub", {})
        except Exception as e:
            decky.logger.error(f"Failed to load pending unsubscribes: {e}")
    return {}


def _save_pending_unsub(pending: dict) -> None:
    path = _get_store_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        full = {}
        if os.path.isfile(path):
            with open(path, "r") as f:
                full = json.load(f)
        full["workshop_unsub"] = pending
        with open(tmp, "w") as f:
            json.dump(full, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        decky.logger.error(f"Failed to save pending unsubscribes: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)


def _mark_unsub_pending(fileid: str) -> None:
    if not fileid:
        return
    pending = _load_pending_unsub()
    pending[str(fileid)] = time.time()
    _save_pending_unsub(pending)


def _clear_unsub_pending(fileid: str) -> None:
    if not fileid:
        return
    pending = _load_pending_unsub()
    if str(fileid) in pending:
        del pending[str(fileid)]
        _save_pending_unsub(pending)


def _workshop_record(
    fileid: str, appid: int, name: str, thumbnail: str, description: str,
    filename: str, is_library: bool = False,
) -> dict:
    """Build an installed.json record for a subscribed Workshop mod. `appid` scopes the
    (globally-keyed) store to a game; metadata comes from what Steam reported for the
    subscription."""
    return {
        "version": "subscribed",
        "filename": filename,
        "appid": appid,
        "install_type": "steamworkshop",
        "is_library": bool(is_library),
        "added_at": time.time(),
        "source": {
            "type": "steamworkshop", "owner": "", "repo": "", "asset": "",
            "install_type": "steamworkshop", "workshop_id": fileid,
        },
        "meta": {
            "name": name,
            "author": "",
            "description": description,
            "homepage": f"https://steamcommunity.com/sharedfiles/filedetails/?id={fileid}",
            "thumbnail": thumbnail,
            "modloader": "steamworkshop",
            "dependencies": [],
        },
    }


def reconcile_workshop(game: GameProfile, items: list[dict]) -> bool:
    """Sync installed.json with the game's ACTUAL Steam Workshop subscriptions,
    supplied by the frontend (GetSubscribedWorkshopItems). Adds a record for every
    subscribed item — the Steam-provided title/preview as a synthetic
    `workshop.<appid>.<fileid>` entry — and drops records for this game whose item is
    no longer subscribed. Existing records (and their enabled flags) are preserved.
    Returns True if anything changed.

    Each item is {id, name?, thumbnail?, description?}. An empty list is a valid
    "nothing subscribed" state and will clear this game's Workshop records; the
    frontend must pass None (skip) rather than [] when the query actually failed."""
    store = _load_store()
    subscribed = {str(it.get("id") or "").strip(): it for it in items if str(it.get("id") or "").strip()}
    lib_ids = set(game.library_workshop_ids)
    now = time.time()
    changed = False

    # A pending unsubscribe clears once Steam drops it from the subscribed set (or after
    # the grace window as a safety) — until then we ignore that item so reconcile doesn't
    # re-add a record the user just deleted.
    pending = _load_pending_unsub()
    pending_changed = False
    for fid in list(pending.keys()):
        if fid not in subscribed or (now - pending[fid]) >= _RECONCILE_GRACE_SECONDS:
            del pending[fid]
            pending_changed = True
    if pending_changed:
        _save_pending_unsub(pending)

    # 1) ensure a record exists for each subscribed item, and keep is_library current
    #    on existing records too (so library-list edits take effect without reinstalling)
    for fid, it in subscribed.items():
        if fid in pending:
            continue  # just unsubscribed; Steam hasn't dropped it yet
        mod_id = f"workshop.{game.appid}.{fid}"
        want_lib = fid in lib_ids
        name = it.get("name") or ""
        thumb = it.get("thumbnail") or ""
        desc = it.get("description") or ""
        # Map the item's required-item file ids to synthetic Moddy mod ids so the UI's
        # dependents logic works.
        deps = [f"workshop.{game.appid}.{c}" for c in (it.get("dependencies") or [])]
        if mod_id not in store:
            rec = _workshop_record(
                fid, game.appid, name or f"Workshop item {fid}", thumb, desc,
                name or fid, is_library=want_lib,
            )
            rec["meta"]["dependencies"] = deps
            store[mod_id] = rec
            changed = True
        else:
            # Refresh metadata on an existing record. A Browse install starts as a
            # placeholder ("Workshop item <id>", no deps) until the Steam details
            # arrive on a later reconcile — this is what fixes those names/deps.
            rec = store[mod_id]
            meta = rec.setdefault("meta", {})
            if name and meta.get("name") != name:
                meta["name"] = name
                if rec.get("filename") in (None, "", fid):
                    rec["filename"] = name
                changed = True
            if thumb and meta.get("thumbnail") != thumb:
                meta["thumbnail"] = thumb
                changed = True
            if desc and meta.get("description") != desc:
                meta["description"] = desc
                changed = True
            if deps and meta.get("dependencies") != deps:
                meta["dependencies"] = deps
                changed = True
        if store[mod_id].get("is_library") != want_lib:
            store[mod_id]["is_library"] = want_lib
            changed = True

    # 2) drop this game's Workshop records that are no longer subscribed
    for mod_id in list(store.keys()):
        rec = store[mod_id]
        src = rec.get("source") or {}
        if src.get("type") != "steamworkshop":
            continue
        if rec.get("appid") != game.appid:
            continue  # belongs to a different game
        if src.get("workshop_id", "") not in subscribed:
            # Don't drop a just-installed record whose subscription hasn't shown up in
            # GetSubscribedWorkshopItems yet (SteamClient subscribe is async).
            if (now - rec.get("added_at", 0)) < _RECONCILE_GRACE_SECONDS:
                continue
            del store[mod_id]
            changed = True

    # 3) collapse duplicates: one record per subscribed item. A legacy record under a
    #    different id is superseded by the synthetic one created above — drop the orphan,
    #    carrying over a disabled flag so a deliberately-disabled mod stays disabled.
    for mod_id in list(store.keys()):
        rec = store[mod_id]
        src = rec.get("source") or {}
        if src.get("type") != "steamworkshop":
            continue
        if rec.get("appid") != game.appid:
            continue
        wid = src.get("workshop_id", "")
        if not wid:
            continue
        canonical = f"workshop.{game.appid}.{wid}"
        if mod_id != canonical and canonical in store:
            if not rec.get("enabled", True):
                store[canonical]["enabled"] = False
            del store[mod_id]
            changed = True

    if changed:
        _save_store(store)
    return changed


def clear_installed_record(mod_id: str) -> None:
    store = _load_store()
    if mod_id in store:
        del store[mod_id]
        _save_store(store)


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
    or (for a bare DLL) its disabled form does. Scopes globally-keyed records to the game
    whose files are actually installed."""
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
    if install_type == "zip_folder":
        return _zipfolder_present(install_dir, paths)
    if install_type == "zip_smapi":
        return _smapi_mod_present(_flat_target_paths(install_dir, paths))
    if install_type == "zip_dir" or paths:
        mods_path = resolve_mods_path(game, install_dir)
        filename = record.get("filename") or ""
        target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]
        return any(_tracked_present(d) for d in target_dirs)
    mods_path = resolve_mods_path(game, install_dir)
    filename = record.get("filename") or ""
    target = os.path.join(mods_path, filename)
    return os.path.isfile(target) or os.path.isfile(target + ".bak")


def _record_target_relpaths(game: GameProfile, install_dir: str, record: dict) -> list[str]:
    """A mod's tracked on-disk locations, install-dir-relative. paths-based records list them
    directly; folder/file records derive <mods_dir>/<filename>."""
    paths = record.get("paths")
    if paths:
        return list(paths)
    mods_path = resolve_mods_path(game, install_dir)
    rel = os.path.relpath(os.path.join(mods_path, record.get("filename") or ""), install_dir)
    return [rel]


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
    for mod_id, rec in (_load_store() or {}).items():
        if (rec.get("source") or {}).get("type") == "steamworkshop":
            continue
        if not mod_files_present(game, install_dir, rec):
            continue
        if any(under_removed(t) for t in _record_target_relpaths(game, install_dir, rec)):
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
        dirs.add(resolve_mods_path(game, install_dir))
    except Exception:
        pass
    for rec in (_load_store() or {}).values():
        for rel in _record_target_relpaths(game, install_dir, rec):
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
    mods_path = resolve_mods_path(game, install_dir)
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
    store = _load_store()

    # Workshop games have no on-disk mods folder Moddy manages — their state is the
    # set of tracked subscriptions. List every subscribed Workshop item reconciled into
    # the store for this game (synthetic `workshop.<appid>.<fileid>` records). Skip the
    # filesystem scans entirely.
    if game.uses_steam_workshop():
        for mod_id, record in store.items():
            if mod_id in seen_ids:
                continue
            src = record.get("source") or {}
            if src.get("type") != "steamworkshop" or record.get("appid") != game.appid:
                continue
            seen_ids.add(mod_id)
            installed.append({
                "id": mod_id,
                "filename": record.get("filename", mod_id),
                "enabled": record.get("enabled", True),
                "version": record.get("version"),
                "meta": record.get("meta"),
                "is_library": record.get("is_library", False),
                "added_at": record.get("added_at"),
            })
        return installed

    # Tracked installs from installed.json — browsed mods.
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
        if install_type == "zip_flat":
            target_paths = _flat_target_paths(install_dir, paths)
            if not _flat_mod_present(target_paths):
                continue  # installed for a different game
            enabled = _flat_mod_enabled(target_paths)
        elif install_type in ("zip_natives", "zip_nativepc"):
            # Loose mod (RE4 natives/, MHW nativePC/): per-file paths merged into the game root.
            # Present iff any tracked file exists (active or *.disabled); enabled iff the active
            # form is on disk.
            target_paths = _flat_target_paths(install_dir, paths)
            if not _flat_mod_present(target_paths):
                continue  # installed for a different game
            enabled = _natives_mod_enabled(target_paths)
        elif install_type == "zip_smapi":
            # SMAPI mod: one or more folders under Mods/, each with a manifest.json. Present iff
            # any tracked folder exists (active or `.`-disabled); enabled iff the active form is on disk.
            target_paths = _flat_target_paths(install_dir, paths)
            if not _smapi_mod_present(target_paths):
                continue  # installed for a different game
            enabled = _smapi_mod_enabled(target_paths)
        elif install_type == "zip_folder":
            # Folder-per-mod data mod (NMS): one folder under GAMEDATA/MODS/. Present iff it's live
            # there OR parked in the disabled-staging dir; enabled iff the live folder is on disk.
            if not _zipfolder_present(install_dir, paths):
                continue  # installed for a different game
            enabled = _zipfolder_enabled(install_dir, paths)
        elif install_type == "zip_dir" or paths:
            target_dirs = [os.path.join(install_dir, p) for p in paths] if paths else [os.path.join(mods_path, filename)]
            if not any(_tracked_present(d) for d in target_dirs):
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
        _claim(record, filename)
        installed.append({
            "id": mod_id,
            "filename": filename,
            "enabled": enabled,
            "version": record.get("version"),
            "meta": record.get("meta"),
            "added_at": record.get("added_at"),
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
                    "version": get_installed_version(actual_filename),
                    "meta": None,
                    "added_at": None,
                })

    return installed


async def install_mod(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None = None, url: str | None = None, variant: str | None = None) -> "bool | None | dict":
    """
    Download and install a mod into the game's mods directory.
    Supports two install types:
    - "file": single DLL, backs up previous version as Mod.dll.vX.Y.Z.bak
    - "zip_dir": extracts zip as a folder into the mods directory
    Returns True=success, False=failed, None=cancelled. For "zip_natives" with multiple variants
    and no `variant` chosen, returns {"needs_variant": True, "variants": [...]}.
    """
    mods_path = resolve_mods_path(game, install_dir)
    os.makedirs(mods_path, exist_ok=True)

    if mod.source.install_type == "zip_dir":
        return await _install_mod_zip_dir(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_flat":
        return await _install_mod_zip_flat(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_natives":
        return await _install_mod_zip_natives(game, install_dir, mod, version, url, variant)
    if mod.source.install_type == "zip_nativepc":
        return await _install_mod_zip_nativepc(game, install_dir, mod, version, url, variant)
    if mod.source.install_type == "zip_smapi":
        return await _install_mod_zip_smapi(game, install_dir, mods_path, mod, version, url)
    if mod.source.install_type == "zip_folder":
        return await _install_mod_zip_folder(game, install_dir, mods_path, mod, version, url)
    # Guard: only the single-file installer is a safe default. An unrecognized install_type
    # must NOT silently fall through to it — that once dumped a raw mod archive into RE4's
    # game dir (the `nexus-<id>` file). Fail loudly instead.
    if mod.source.install_type not in ("", "file"):
        decky.logger.error(
            f"Unknown install_type '{mod.source.install_type}' for {mod.name}; refusing to install"
        )
        return False
    return await _install_mod_file(game, install_dir, mods_path, mod, version, url)


def set_workshop_meta(game: GameProfile, fileid: str, name: str, thumbnail: str, description: str) -> bool:
    """Update a Workshop record's display metadata in place (used right after a Browse
    install so the real name shows immediately). Only touches the synthetic record for
    this file."""
    mod_id = f"workshop.{game.appid}.{fileid}"
    store = _load_store()
    rec = store.get(mod_id)
    if not rec:
        return False
    meta = rec.setdefault("meta", {})
    if name:
        meta["name"] = name
        if rec.get("filename") in (None, "", fileid):
            rec["filename"] = name
    if thumbnail:
        meta["thumbnail"] = thumbnail
    if description:
        meta["description"] = description
    _save_store(store)
    return True


async def install_synthetic_workshop(game: GameProfile, mod_id: str, fileid: str) -> bool:
    """Record a Workshop subscription by its synthetic id. The frontend has already
    subscribed via SteamClient; reconcile enriches title/deps on the next refresh."""
    _clear_unsub_pending(fileid)
    store = _load_store()
    if mod_id not in store:
        store[mod_id] = _workshop_record(
            fileid, game.appid, f"Workshop item {fileid}", "", "", fileid,
            is_library=fileid in game.library_workshop_ids,
        )
        _save_store(store)
    return True


# The atomic file-placement primitive lives in install_txn so the modloader installers can share
# it without importing this (much larger) module. Re-exported here since the installers below and
# the test suite reference them as mods._StagedInstall etc.
from install_txn import _MODDY_ORIG_SUFFIX, _STAGED_BAK_SUFFIX, _discard, _StagedInstall  # noqa: E402,F401


def _claimed_paths_map(install_dir: str, mods_path: str, exclude_mod_id: str | None = None) -> dict:
    """Map every install-dir-absolute path Moddy has placed (per installed.json) to the mod_id
    that claims it. Lets us tell a stock game file (unclaimed) from a Moddy-placed one, and spot
    mod-vs-mod overwrites. `exclude_mod_id` drops one record (the mod being installed/uninstalled)
    so its own paths don't count — e.g. on uninstall, to decide whether any OTHER mod still owns a
    slot before restoring the stock original."""
    out: dict[str, str] = {}
    for mod_id, record in (_load_store() or {}).items():
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


def _overwrite_guard(install_dir: str, mods_path: str, mod: ModInfo, dest_rels: list):
    """Build the `is_foreign` predicate a staged install passes to _StagedInstall, and log any
    mod-vs-mod overwrite among `dest_rels` (warn-and-proceed: the last install wins; the stock
    original, captured the first time any mod overwrote it, stays recoverable). is_foreign(p) is
    True when no installed record claims p — i.e. p is a stock game file or user-placed — so the
    transaction preserves it as *.moddy-orig on commit instead of discarding it. The mod's own
    prior paths ARE claimed (not foreign), so an upgrade's displaced old version is dropped as
    before, leaving the .v<ver>.bak version history to handle rollback."""
    claimed = _claimed_paths_map(install_dir, mods_path)
    for rel in dest_rels:
        owner = claimed.get(os.path.normpath(os.path.join(install_dir, rel)))
        if owner and owner != mod.id:
            decky.logger.warning(
                f"{mod.name}: overwrites {rel} already provided by '{owner}' — last install wins")
    claimed_keys = set(claimed)
    return lambda p: os.path.normpath(p) not in claimed_keys


def _restore_originals(install_dir: str, mods_path: str, abs_paths: list, exclude_mod_id: str) -> None:
    """On uninstall, move any durable *.moddy-orig stock backup back into place — but only for a
    path no OTHER installed mod still claims (last-claim restore). A path still owned by another
    mod keeps that mod's content; its stock original stays parked until the last owner goes."""
    others = set(_claimed_paths_map(install_dir, mods_path, exclude_mod_id=exclude_mod_id))
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


def _backup_version_dir(dst_dir: str, mod_id: str) -> None:
    """Copy the currently-installed folder to <dir>.v<old>.bak for the version-history feature,
    when a versioned install is present. Best-effort and independent of atomicity — it preserves a
    snapshot of the version being replaced (see get_backed_up_versions / delete_mod_version)."""
    import shutil
    if not os.path.isdir(dst_dir):
        return
    old_version = get_installed_version(mod_id)
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
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp, game.appid)

        if os.path.isfile(dst):
            claimed = _claimed_paths_map(install_dir, mods_path)
            owner = claimed.get(os.path.normpath(dst))
            if owner and owner != mod.id:
                decky.logger.warning(
                    f"{mod.name}: overwrites {mod.filename} already provided by '{owner}' — last install wins")
            old_version = get_installed_version(mod.id)
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

        set_installed_record(mod.id, version or "latest", mod.filename,
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


_THUNDERSTORE_METADATA_FILES = {"manifest.json", "icon.png", "readme.md", "changelog.md", "license", "license.md", "license.txt"}


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

        _backup_version_dir(dst_dir, mod.id)  # version-history snapshot of the install being replaced
        _atomic_dir_swap(dst_dir, staged)
        set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
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

        _backup_version_dir(dst_dir, mod.id)  # version-history snapshot of the install being replaced
        _atomic_dir_swap(dst_dir, staged)
        set_installed_record(mod.id, version or "latest", mod.filename, mod=mod)
        decky.logger.info(f"Installed {mod.name} ({version or 'latest'})")
        return True
    finally:
        for p in (staged, tmp_extract):
            if os.path.exists(p):
                _discard(p)


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
    old_paths = (_load_store().get(mod.id) or {}).get("paths") or []
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
        is_foreign = _overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
        with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
            for p in old_paths:
                txn.retire(p)
            for staged_abs, install_rel in placements:
                txn.place(staged_abs, install_rel)

        paths = sorted(os.path.relpath(os.path.join(mods_path, t), install_dir) for t in created_tops)
        set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
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


def _safe_folder_name(name: str) -> str:
    """A filesystem-safe Mods/ subfolder name derived from a mod's name, for the rare SMAPI
    archive that ships manifest.json at its root with no containing folder. Strips path separators
    and a leading dot (a leading dot would mark the folder disabled to SMAPI)."""
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip().lstrip(".")
    return cleaned or "Mod"


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
        decky.logger.error(f"{mod.name}: no manifest.json in archive — not a SMAPI mod, refusing to install")
        return False

    placements: list[tuple[str, str]] = []   # (staged abs, install-dir-relative dest)
    created_tops: set[str] = set()
    for root in roots:
        folder = _safe_folder_name(mod.filename) if root == extract_root else os.path.basename(root)
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
    is_foreign = _overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
    with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
        for p in old_paths:
            txn.retire(p)
            txn.retire(_dotprefix_disabled(p))
        for staged_abs, install_rel in placements:
            txn.place(staged_abs, install_rel)

    paths = sorted(created_tops)
    set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
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
    old_paths = (_load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_archive, game.appid)
        extract_archive(tmp_archive, tmp_extract)
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


def _is_archive_junk(rel: str) -> bool:
    """macOS zip cruft that must never be placed into a mod folder or counted when deciding whether
    a single wrapper folder should be stripped: the `__MACOSX/` metadata tree, `.DS_Store`, and
    AppleDouble `._*` resource forks. Nexus archives zipped on macOS routinely carry these."""
    parts = rel.replace("\\", "/").split("/")
    if "__MACOSX" in parts:
        return True
    base = parts[-1]
    return base == ".DS_Store" or base.startswith("._")


def _folder_commit(install_dir: str, mods_path: str, extract_root: str, staging: str,
                   mod: ModInfo, version: str | None, old_paths: list) -> bool:
    """Place an extracted archive as ONE folder <mods_dir>/<mod>/, transactionally. For folder-per-
    mod games (No Man's Sky: each mod is its own folder under GAMEDATA/MODS/). Strips a single
    redundant top-level wrapper dir so a wrapped mod doesn't nest twice. Format-agnostic — whatever
    the archive holds (.pak, or unpacked .MBIN/.EXML) lands verbatim in the mod's folder. macOS zip
    junk (__MACOSX/, .DS_Store, ._*) is dropped so it neither defeats the wrapper strip nor litters
    the mod folder. Retires the previous install (active and `.disabled` form) and commits
    all-or-nothing."""
    import shutil
    extract_root = os.path.normpath(extract_root)
    # Strip a single redundant top-level wrapper folder (and only that). Ignore macOS junk siblings
    # when deciding — a lone real wrapper riding next to __MACOSX/ or .DS_Store must still be stripped.
    real_entries = [e for e in os.listdir(extract_root) if not _is_archive_junk(e)]
    src_root = extract_root
    if len(real_entries) == 1 and os.path.isdir(os.path.join(extract_root, real_entries[0])):
        src_root = os.path.join(extract_root, real_entries[0])

    folder = _safe_folder_name(mod.filename)   # one folder per mod, named for the mod (dot-stripped)
    placements: list[tuple[str, str]] = []     # (staged abs, install-dir-relative dest)
    for sub_root, _dirs, files in os.walk(src_root):
        for fn in files:
            src = os.path.join(sub_root, fn)
            rel = os.path.relpath(src, src_root)
            if _is_archive_junk(rel):
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
    is_foreign = _overwrite_guard(install_dir, mods_path, mod, [r for _s, r in placements])
    with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
        for p in old_paths:
            txn.retire(p)                      # retire() already sets aside <mod> AND <mod>.disabled
            # A previously-disabled mod is parked outside MODS/ — retire that too so reinstalling
            # over a disabled mod replaces it (and rolls back) instead of orphaning the parked copy.
            txn.retire(os.path.join(_FOLDER_DISABLED_DIR, os.path.basename(p.rstrip("/\\"))))
        for staged_abs, install_rel in placements:
            txn.place(staged_abs, install_rel)

    # Track the single top folder; toggling renames it to <mod>.disabled, so presence/enabled use
    # the flat/.disabled helpers (_flat_mod_present / _smapi_mod_enabled).
    set_installed_record(mod.id, version or "latest", mod.filename, paths=[top_rel], mod=mod)
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
    old_paths = (_load_store().get(mod.id) or {}).get("paths") or []
    try:
        decky.logger.info(f"Downloading {mod.name} from {url}")
        await utils.download(url, tmp_archive, game.appid)
        extract_archive(tmp_archive, tmp_extract)
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


async def install_smapi_files(game: GameProfile, install_dir: str, mod: ModInfo, version: str | None, urls: list) -> bool | None:
    """Install MULTIPLE chosen Nexus files of one SMAPI mod (the file-picker path) as a single
    library entry. Each file is downloaded and extracted into its own subdir of one combined extract
    tree, then `_smapi_commit` places every mod folder found across all of them under Mods/ and
    records them together under the one mod id — so e.g. Stardew Valley Expanded's main download and
    its optional alternate farm install as one unit. All-or-nothing: a failure rolls back."""
    import shutil

    mods_path = resolve_mods_path(game, install_dir)
    os.makedirs(mods_path, exist_ok=True)
    tmp_extract = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_extract")
    staging = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_smapi_staging")
    for p in (tmp_extract, staging):
        if os.path.exists(p):
            shutil.rmtree(p)

    old_paths = (_load_store().get(mod.id) or {}).get("paths") or []
    try:
        for i, url in enumerate(urls):
            archive = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"{mod.filename}_f{i}.archive")
            try:
                decky.logger.info(f"Downloading {mod.name} file {i + 1}/{len(urls)} from {url}")
                await utils.download(url, archive, game.appid)
                # Each archive into its own subdir so same-named folders across files don't collide
                # before placement; _smapi_commit walks the whole tree.
                extract_archive(archive, os.path.join(tmp_extract, f"f{i}"))
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


def _system_env() -> dict:
    """A copy of the environment with Steam's dynamic-linker overrides stripped, for shelling out to
    system binaries. Decky runs the plugin under Steam, which exports LD_LIBRARY_PATH/LD_PRELOAD
    pointing at Steam's bundled libs (an incompatible libreadline/libstdc++). A system binary like
    `7z` — or the `/bin/sh` it spawns — then dies with `symbol lookup error: … undefined symbol`
    (e.g. rl_trim_arg_from_keyseq from readline). Removing these lets the child resolve system libs."""
    return {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "LD_PRELOAD")}


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract a mod archive into dest_dir. RE4/MHW/Nexus mods ship as .zip, .7z, or .rar;
    Python's zipfile only handles zip, so 7z/rar are handed to the system `7z` (ships on
    SteamOS). Routes by magic bytes since the downloaded file may carry no extension."""
    import zipfile, subprocess
    import shutil as _sh
    os.makedirs(dest_dir, exist_ok=True)
    with open(archive_path, "rb") as f:
        magic = f.read(8)
    if magic[:2] == b"PK":
        with zipfile.ZipFile(archive_path, "r") as z:
            z.extractall(dest_dir)
        return
    sevenzip = _sh.which("7z") or _sh.which("7za") or _sh.which("7zz") or _sh.which("7zr")
    for cand in ("/usr/bin/7z", "/usr/bin/7zz", "/usr/bin/7za"):
        if not sevenzip and os.path.isfile(cand):
            sevenzip = cand
    if not sevenzip:
        raise Exception("system 7z not found — cannot extract a .7z/.rar mod archive")
    result = subprocess.run(
        [sevenzip, "x", "-y", f"-o{dest_dir}", archive_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_system_env(),
    )
    if result.returncode != 0:
        raise Exception(f"7z failed: {result.stderr.decode(errors='replace')[:200]}")


# re_chunk_000.pak.patch_NNN.pak  (groups: prefix, number, ".pak", optional ".disabled")
_PAK_PATCH_RE = re.compile(r"^(re_chunk_000\.pak\.patch_)(\d+)(\.pak)(\.disabled)?$", re.IGNORECASE)


def _next_pak_slot(install_dir: str) -> int:
    """Lowest unused re_chunk patch number above every existing one. RE4 loads
    `re_chunk_000.pak.patch_NNN.pak` in order with higher numbers overriding lower; the base
    game occupies the low numbers, so a mod pak must sit above the highest present. Counts
    `.disabled` mod paks too, so a disabled mod's slot isn't handed to another mod. Returns
    max(existing)+1 (1 if somehow none exist)."""
    highest = 0
    try:
        for name in os.listdir(install_dir):
            m = _PAK_PATCH_RE.match(name)
            if m:
                highest = max(highest, int(m.group(2)))
    except Exception:
        pass
    return highest + 1


def _renumber_pak_mods(install_dir: str) -> None:
    """Keep Moddy's RE4 `.pak` mods packed contiguously right above the base game's paks, so a
    gap left by uninstalling/disabling one can't stop the engine loading the rest. Preserves
    their relative order — which is load priority (a higher patch number overrides a lower one),
    matching authors' "install this after other X mods" guidance — renaming files and updating
    each owning record's `paths` in place. A no-op when already contiguous.

    A pak is "Moddy's" iff some installed record lists it; everything else at patch_NNN is the
    base game, whose highest number is the ceiling we pack above."""
    store = _load_store()

    # active basename -> owning mod_id, for every pak any record claims.
    owner_of: dict[str, str] = {}
    for mod_id, rec in store.items():
        for p in (rec.get("paths") or []):
            base = os.path.basename(p)
            if _PAK_PATCH_RE.match(base):
                owner_of[base] = mod_id

    try:
        names = os.listdir(install_dir)
    except Exception:
        return

    ceiling = 0
    mod_paks = []  # (current_num, on_disk_name, disabled, owner_id, active_basename)
    for name in names:
        m = _PAK_PATCH_RE.match(name)
        if not m:
            continue
        num, disabled = int(m.group(2)), bool(m.group(4))
        active_base = m.group(1) + m.group(2) + m.group(3)
        owner = owner_of.get(active_base)
        if owner is None:
            if not disabled:
                ceiling = max(ceiling, num)  # a base-game pak
        else:
            mod_paks.append((num, name, disabled, owner, active_base))

    # Compact downward in ascending order (each target slot is freed before it's needed).
    mod_paks.sort(key=lambda t: t[0])
    target = ceiling
    changed = False
    for _num, name, disabled, owner, active_base in mod_paks:
        target += 1
        new_active = f"re_chunk_000.pak.patch_{target:03d}.pak"
        new_name = new_active + (".disabled" if disabled else "")
        if new_name == name:
            continue
        try:
            os.rename(os.path.join(install_dir, name), os.path.join(install_dir, new_name))
        except Exception as e:
            decky.logger.error(f"pak renumber: failed to rename {name} -> {new_name}: {e}")
            continue
        rec = store.get(owner)
        if rec and rec.get("paths"):
            rec["paths"] = [new_active if os.path.basename(p) == active_base else p for p in rec["paths"]]
        changed = True
        decky.logger.info(f"pak renumber: {name} -> {new_name}")
    if changed:
        _save_store(store)


def _detect_variants(extract_dir: str) -> list[dict]:
    """List the selectable payloads in an extracted loose-file (zip_natives / zip_nativepc) mod
    archive. A payload is a directory that directly holds a `.pak`, or that contains a `natives/`
    (RE4) or `nativePC/` (MHW) subtree. Most mods have exactly one; some bundle several
    mutually-exclusive options the user must choose between (e.g. RE4's "Max Stack Sizes" ships 21
    `.pak` variants — 0999/9999/x02…, each in its own folder with a modinfo.ini). Returns
    [{"id": <path relative to extract_dir>, "label": <folder name>}], sorted; 0 or 1 entries means
    no choice is needed."""
    payload_dirs: set[str] = set()
    for root, dirs, files in os.walk(extract_dir):
        in_natives = (os.sep + "natives" + os.sep) in (root + os.sep).lower()
        if not in_natives and any(f.lower().endswith(".pak") for f in files):
            payload_dirs.add(root)              # a folder holding a .pak
        for d in dirs:
            if d.lower() in ("natives", "nativepc"):
                payload_dirs.add(root)          # the parent of a natives/ or nativePC/ tree
    variants = []
    for d in sorted(payload_dirs):
        rel = os.path.relpath(d, extract_dir)
        variants.append({"id": rel, "label": os.path.basename(d) if rel != "." else "(default)"})
    return variants


# Files that are mod-manager metadata / documentation rather than game assets — skipped when
# wrapping a Fluffy-packaged mod (no nativePC/ folder) into the loader's folder.
_LOOSE_METADATA_NAMES = {"modinfo.ini", "desktop.ini", "thumbs.db"}
_LOOSE_METADATA_EXTS = {".txt", ".md", ".url", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".pdf", ".html"}

# Top-level folder names that appear directly inside MHW's nativePC/. Used to tell a real content
# folder (keep it — `pl/…` must become `nativePC/pl/…`) from a "<Mod Name>/" wrapper folder (descend
# into it) when a Fluffy archive has a single top-level dir. Stracker plugins live in nativePC/plugins.
_MHW_NATIVEPC_DIRS = {
    "pl", "npc", "em", "common", "stage", "ui", "gui", "vfx", "sound", "se", "wp", "facial",
    "equip", "quest", "gm", "hm", "it", "id", "motion", "demo", "title", "map", "hit", "ce",
    "cs", "sm", "mc", "scaffold", "shell", "archon", "assets", "animation", "chunk", "stm",
    "plugins", "loader", "nativepc",
}


def _looks_like_nativepc_content(name: str) -> bool:
    return name.lower() in _MHW_NATIVEPC_DIRS


def _is_loose_metadata(rel: str) -> bool:
    """True for a wrap-loose archive entry that's mod-manager metadata or a preview/readme, not a
    game asset. Only top-level entries are screened (assets nested inside content folders, e.g. a
    `pl/.../foo.png` texture sidecar, are kept) — so this matches RE4's modinfo.ini/screenshot skip
    but is scoped to the archive root."""
    if os.sep in rel:
        return False  # nested file — part of the content tree, keep it
    name = os.path.basename(rel).lower()
    if name in _LOOSE_METADATA_NAMES:
        return True
    return os.path.splitext(name)[1] in _LOOSE_METADATA_EXTS


def _strip_loose_wrapper(search_root: str) -> str:
    """If the payload is entirely inside a single "<Mod Name>/" wrapper directory (e.g.
    "<Mod Name>/pl/…", with at most metadata files beside it), return that inner dir so the content
    isn't buried a level too deep. A lone top-level dir is only treated as a wrapper when its name
    is NOT a known nativePC content folder — otherwise `pl/…` (an armor mod touching only `pl`) would
    be wrongly stripped to `f_equip/…`. The Fluffy norm — content folders directly at the root next
    to modinfo.ini — has multiple dirs or a content-named dir, so it's returned unchanged."""
    try:
        entries = os.listdir(search_root)
    except OSError:
        return search_root
    dirs = [e for e in entries if os.path.isdir(os.path.join(search_root, e))]
    nonmeta_files = [e for e in entries if not os.path.isdir(os.path.join(search_root, e)) and not _is_loose_metadata(e)]
    if len(dirs) == 1 and not nonmeta_files and not _looks_like_nativepc_content(dirs[0]):
        return os.path.join(search_root, dirs[0])
    return search_root


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
    old_paths = (_load_store().get(mod.id) or {}).get("paths") or []

    # When the queue parks this install to ask which variant to use, we keep the extracted archive
    # so the resume can install the choice without downloading again. `park` tells the finally not
    # to delete that extract; `reuse` (a chosen variant + a cache already on disk) skips the fetch.
    park = False
    try:
        reuse = variant is not None and os.path.isdir(tmp_extract)
        if reuse:
            decky.logger.info(f"Resuming {mod.name} from cached archive (variant {variant!r})")
        else:
            if os.path.exists(tmp_extract):
                shutil.rmtree(tmp_extract)
            decky.logger.info(f"Downloading {mod.name} from {url}")
            await utils.download(url, tmp_archive, game.appid)
            extract_archive(tmp_archive, tmp_extract)

        # Resolve which payload to install. Multiple variants + no choice → ask the UI.
        variants = _detect_variants(tmp_extract)
        valid_ids = {v["id"] for v in variants}
        if variant is not None:
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
            payload_root = _strip_loose_wrapper(search_root)
            for root, _dirs, files in os.walk(payload_root):
                for fn in files:
                    if _is_loose_metadata(os.path.relpath(os.path.join(root, fn), payload_root)):
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
            payload_root = _strip_loose_wrapper(search_root)
            autorun_dirs = sorted(
                (os.path.join(r, d) for r, ds, _f in os.walk(payload_root) for d in ds if d.lower() == "autorun"),
                key=lambda p: p.count(os.sep),
            )
            base = autorun_dirs[0] if autorun_dirs else payload_root
            if any(fn.lower().endswith(".lua") for _r, _d, fs in os.walk(base) for fn in fs):
                for root, _dirs, files in os.walk(base):
                    for fn in files:
                        rel = os.path.relpath(os.path.join(root, fn), base)
                        if _is_loose_metadata(rel):
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
        is_foreign = _overwrite_guard(install_dir, resolve_mods_path(game, install_dir), mod,
                                      [r for _f, r in natives_placements])
        with _StagedInstall(install_dir, is_foreign=is_foreign) as txn:
            for p in old_paths:
                txn.retire(p)
            for full, rel in natives_placements:
                txn.place(full, rel)
                paths.append(rel)
            for src in pak_srcs:
                rel = f"re_chunk_000.pak.patch_{_next_pak_slot(install_dir):03d}.pak"
                txn.place(src, rel)
                paths.append(rel)

        paths.sort()
        set_installed_record(mod.id, version or "latest", mod.filename, paths=paths, mod=mod)
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


def get_backed_up_versions(game: GameProfile, install_dir: str, mod_id: str) -> list[str]:
    """Return a list of previously installed versions backed up on disk."""
    record = get_installed_record(mod_id) or {}
    filename = record.get("filename")
    if not filename:
        return []
    mods_path = resolve_mods_path(game, install_dir)
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
    record = get_installed_record(mod_id) or {}
    filename = record.get("filename")
    if not filename:
        return False
    mods_path = resolve_mods_path(game, install_dir)
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
    mods_path = resolve_mods_path(game, install_dir)
    store = _load_store()
    record = store.get(mod_id, {})

    # Steam Workshop mods: the frontend unsubscribes via SteamClient (which deletes
    # the files); the backend just drops the tracking record.
    rec_source = record.get("source") or {}
    source_type = rec_source.get("type")
    if source_type == "steamworkshop":
        fileid = rec_source.get("workshop_id") or ""
        if fileid:
            _mark_unsub_pending(fileid)  # don't let reconcile re-add it mid-unsubscribe
        clear_installed_record(mod_id)
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
                    cands.append(_dotprefix_disabled(full))
                if install_type == "zip_folder":
                    cands.append(_zipfolder_disabled_path(install_dir, relpath))  # a disabled mod is parked outside MODS/
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
            _restore_originals(install_dir, mods_path, [os.path.join(install_dir, p) for p in paths], mod_id)
            # Per-file records (BepInEx merge / RE4 natives) leave empty dirs behind — prune
            # them, but only when empty so a shared folder another mod uses survives.
            _prune_empty_dirs(install_dir, paths)
            _zipfolder_prune_staging(install_dir)  # tidy the NMS disabled-staging dir if now empty
            clear_installed_record(mod_id)
            # If a .pak mod was removed, close the numbering gap so the remaining pak mods keep
            # loading (and keep their relative load-order/priority).
            if any(_PAK_PATCH_RE.match(os.path.basename(p)) for p in paths):
                _renumber_pak_mods(install_dir)
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
            _restore_originals(install_dir, mods_path, [os.path.join(mods_path, filename)], mod_id)
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
    Every mod uses its persisted record in installed.json.
    """
    mods_path = resolve_mods_path(game, install_dir)
    store = _load_store()
    record = store.get(mod_id, {})

    # Steam Workshop enable/disable: the active/inactive flip happens in the frontend
    # via SetWorkshopItemsDisabledLocally (keeps the files, no unsubscribe). Here we
    # just persist the resulting enabled state so Moddy lists and snapshots it correctly.
    rec_source = record.get("source") or {}
    if rec_source.get("type") == "steamworkshop":
        set_mod_enabled(mod_id, enable)
        decky.logger.info(f"Workshop mod {mod_id} enabled={enable}")
        return True

    install_type = record.get("install_type") or rec_source.get("install_type")
    filename = record.get("filename", mod_id)

    if install_type == "zip_flat":
        # Flat-loader mod (MelonLoader): toggle every tracked *.dll between active and
        # *.dll.disabled so the loader skips it. Asset-only mods have nothing to toggle.
        target_paths = _flat_target_paths(install_dir, record.get("paths"))
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

    if install_type in ("zip_natives", "zip_nativepc"):
        # Loose mod (RE4 natives/, MHW nativePC/): the loader matches files by exact path, so
        # disabling renames every tracked file to *.disabled (and enabling renames back). These are
        # game assets (.tex/.mesh/.spck…), not .dll, so we flip all tracked files, not just DLLs.
        target_paths = _flat_target_paths(install_dir, record.get("paths"))
        renamed = 0
        try:
            for p in target_paths:
                if enable:
                    if os.path.isfile(p + ".disabled") and not os.path.isfile(p):
                        os.rename(p + ".disabled", p)
                        renamed += 1
                else:
                    if os.path.isfile(p):
                        os.rename(p, p + ".disabled")
                        renamed += 1
            if renamed == 0:
                decky.logger.warning(f"No files to {'enable' if enable else 'disable'} for {mod_id}")
                return False
            decky.logger.info(f"{'Enabled' if enable else 'Disabled'} {filename} ({renamed} file{'s' if renamed != 1 else ''})")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to toggle {mod_id}: {e}")
            return False

    if install_type == "zip_smapi":
        # SMAPI mod: SMAPI skips any folder under Mods/ whose name starts with '.', so toggle
        # each tracked mod folder between `Mods/<X>` and `Mods/.<X>`. Non-destructive and
        # exactly what the in-game mod-manager mods do.
        target_paths = _flat_target_paths(install_dir, record.get("paths"))
        renamed = 0
        try:
            for p in target_paths:
                disabled = _dotprefix_disabled(p)
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

    if install_type == "zip_folder":
        # Folder-per-mod data mod (NMS): the game scans GAMEDATA/MODS/ RECURSIVELY (device-confirmed),
        # so an in-place rename does NOT hide a mod. Disabling MOVES each tracked folder out of MODS/
        # into a game-root staging dir; enabling moves it back.
        import shutil
        paths = record.get("paths") or []
        moved = 0
        try:
            for rel in paths:
                active = os.path.join(install_dir, rel)
                parked = _zipfolder_disabled_path(install_dir, rel)
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
            _zipfolder_prune_staging(install_dir)
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