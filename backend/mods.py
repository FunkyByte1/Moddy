import os
import time
import decky
import game_store
import json_store
from registry import GameProfile, ModInfo
import steam

# A freshly-recorded Workshop install isn't in GetSubscribedWorkshopItems yet
# (SteamClient subscribe is async), so reconcile must not drop records this young.
_RECONCILE_GRACE_SECONDS = 180


def resolve_mods_path(game: GameProfile, install_dir: str) -> str:
    """Resolve the absolute path to the mods directory for a game."""
    if game.mods_dir_type == "proton_appdata":
        base = steam.get_proton_appdata_path(game.appid, game.mods_appdata_path)
        return os.path.join(base, game.mods_dir)
    return os.path.join(install_dir, game.mods_dir)

def _get_store_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "installed.json")


def _load_store(appid: int) -> dict:
    """One game's installed-mods map: {mod_id: {version, filename, enabled, ...}}. This is
    the LIVE cached sub-dict (game_store owns the single cache for the whole "games"
    section) — mutate it in place and persist with _save_store."""
    return game_store.section(appid, "mods")


def _save_store(appid: int, store: dict) -> None:
    """Persist one game's mods map atomically, preserving every other game and section."""
    game_store.game(appid)["mods"] = store
    game_store.save()


# ── Vanilla-mode snapshot ─────────────────────────────────────────────────────
# When a game is switched to "vanilla" (play unmodded) we disable every enabled mod and the
# modloader, recording WHAT was enabled so switching back restores exactly that state — a mod the
# user had individually disabled stays disabled. Stored as the game's "vanilla" key (present ==
# the game is vanilla), beside its "mods"/"modloaders" sections.

def get_vanilla_state(appid: int) -> dict | None:
    """The snapshot captured when this game entered vanilla mode, or None if it isn't vanilla.
    Shape: {"mods": [enabled mod ids], "modloader": <ml id or None>, "workshop": [fileids]}."""
    return game_store.game(appid).get("vanilla")


def is_game_vanilla(appid: int) -> bool:
    return get_vanilla_state(appid) is not None


def set_vanilla_state(appid: int, snapshot: dict | None) -> None:
    """Persist (snapshot) or clear (None) a game's vanilla snapshot, preserving the rest of
    installed.json. Atomic write."""
    g = game_store.game(appid)
    if snapshot is None:
        g.pop("vanilla", None)
    else:
        g["vanilla"] = snapshot
    game_store.save()


def get_installed_version(appid: int, mod_id: str) -> str | None:
    return _load_store(appid).get(mod_id, {}).get("version")


def set_installed_record(
    appid: int,
    mod_id: str,
    version: str,
    filename: str,
    paths: list[str] | None = None,
    mod: ModInfo | None = None,
    install_type: str | None = None,
) -> None:
    """Persist an install record. If `mod` is provided, source/meta/install_type are
    extracted from the ModInfo so the record is self-describing — this is what lets
    mods be uninstalled, toggled, and update-checked later from the record alone.
    `install_type`, when given, overrides the one derived from the ModInfo — used when an
    install lands in a different shape than its catalog type (e.g. a manifest-less SMAPI archive
    placed as a per-file overlay, tracked with zip_natives file semantics)."""
    store = _load_store(appid)
    record: dict = {"version": version, "filename": filename}
    # Stamp when the mod first entered the library so the Installed tab can offer a
    # "recently downloaded" sort. Preserve an existing record's timestamp across version
    # changes / re-installs so updating a mod doesn't reshuffle it to the top.
    record["added_at"] = (store.get(mod_id) or {}).get("added_at", time.time())
    # Provenance (which collection(s) / manual install brought this mod in) is set separately by
    # add_record_source after a clean install, so it must survive a re-install / version bump here —
    # same reasoning as added_at: re-installing a collection mod must not strip its grouping.
    prev_sources = (store.get(mod_id) or {}).get("sources")
    if prev_sources:
        record["sources"] = prev_sources
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
            "mod_reference": mod.source.mod_reference,
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
    if install_type is not None:
        record["install_type"] = install_type
    store[mod_id] = record
    _save_store(appid, store)


def set_ignore_unused(appid: int, mod_id: str, ignored: bool) -> bool:
    """Mark/unmark an installed mod as an intentional 'undocumented dependency' so the unused-
    libraries cleanup (the Installed tab's broom) stops flagging it. Case-insensitive on the id,
    since catalog casing can differ from what was persisted. Stores the flag only when True (drops
    it when cleared) to keep records tidy. Returns True if a record was found and updated."""
    store = _load_store(appid)
    key = mod_id if mod_id in store else next((k for k in store if k.lower() == mod_id.lower()), None)
    if key is None:
        return False
    if ignored:
        store[key]["ignore_unused"] = True
    else:
        store[key].pop("ignore_unused", None)
    _save_store(appid, store)
    return True


def get_installed_record(appid: int, mod_id: str) -> dict | None:
    """Return the full persisted install record for a mod, or None if untracked."""
    return _load_store(appid).get(mod_id)


def find_installed_record(appid: int, mod_id: str) -> dict | None:
    """Like get_installed_record, but case-insensitive on the mod id. Install ids come
    from catalogs whose casing may differ from what was originally persisted, so an
    exact-key miss falls back to a case-insensitive scan of the store keys."""
    store = _load_store(appid)
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
    record = find_installed_record(game.appid, mod_id)
    return record is not None and mods_common.mod_files_present(game, install_dir, record)


def set_mod_enabled(appid: int, mod_id: str, enabled: bool) -> None:
    """Persist a mod's enabled flag in its install record. Used by Workshop mods,
    whose enable/disable is a local Steam flag (SetWorkshopItemsDisabledLocally,
    applied in the frontend) rather than file presence on disk."""
    store = _load_store(appid)
    if mod_id in store:
        store[mod_id]["enabled"] = enabled
        _save_store(appid, store)


# Workshop unsubscribe is async (SteamClient), so just-deleted items still appear in
# GetSubscribedWorkshopItems for a moment. We tombstone them so reconcile doesn't re-add
# the record the user just removed (the mirror of the install grace period).
def _load_pending_unsub() -> dict:
    return json_store.read(_get_store_path()).get("workshop_unsub", {})


def _save_pending_unsub(pending: dict) -> None:
    json_store.update_section(_get_store_path(), "workshop_unsub", pending)


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
    """Build an installed.json record for a subscribed Workshop mod. The record lives in
    its game's own store; the `appid` field is kept purely as self-description (routing
    no longer needs it). Metadata comes from what Steam reported for the subscription."""
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
    store = _load_store(game.appid)
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
        _save_store(game.appid, store)
    return changed


def clear_installed_record(appid: int, mod_id: str) -> None:
    store = _load_store(appid)
    if mod_id in store:
        del store[mod_id]
        _save_store(appid, store)


def _find_record_key(store: dict, mod_id: str) -> str | None:
    """Resolve mod_id to an actual store key, case-insensitively (catalog casing can drift)."""
    if mod_id in store:
        return mod_id
    target = mod_id.lower()
    for k in store:
        if k.lower() == target:
            return k
    return None


def add_record_source(appid: int, mod_id: str, source: dict) -> None:
    """Record where an installed mod came from: union a provenance source into the record's
    `sources` map ({id -> {"name", "image"}}). `source` = {"id": "manual" | "collection:<slug>",
    "name": <display>, "image": <tile url>}. Idempotent: installing a mod that's already present
    just adds the new membership, never duplicates the mod. A re-add refreshes name/image but keeps
    a prior non-empty value when the new one is blank. No-op if the mod has no record yet."""
    sid = (source or {}).get("id")
    if not sid:
        return
    store = _load_store(appid)
    key = _find_record_key(store, mod_id)
    if key is None:
        return
    sources = store[key].get("sources") or {}
    prev = sources.get(sid)
    prev = prev if isinstance(prev, dict) else ({"name": prev} if prev else {})
    sources[sid] = {
        "name": source.get("name") or prev.get("name") or sid,
        "image": source.get("image") or prev.get("image") or "",
    }
    store[key]["sources"] = sources
    _save_store(appid, store)


def remove_record_source(appid: int, mod_id: str, source_id: str) -> dict:
    """Drop one provenance source from a record's `sources` map (the ref-counting step behind
    "uninstall collection"). Returns the REMAINING sources map ({} if none left, so the caller
    can decide whether the mod itself should be removed). No-op-safe on missing record/source."""
    store = _load_store(appid)
    key = _find_record_key(store, mod_id)
    if key is None:
        return {}
    sources = store[key].get("sources") or {}
    sources.pop(source_id, None)
    if sources:
        store[key]["sources"] = sources
    else:
        store[key].pop("sources", None)
    _save_store(appid, store)
    return sources


def set_workshop_meta(game: GameProfile, fileid: str, name: str, thumbnail: str, description: str) -> bool:
    """Update a Workshop record's display metadata in place (used right after a Browse
    install so the real name shows immediately). Only touches the synthetic record for
    this file."""
    mod_id = f"workshop.{game.appid}.{fileid}"
    store = _load_store(game.appid)
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
    _save_store(game.appid, store)
    return True


async def install_synthetic_workshop(game: GameProfile, mod_id: str, fileid: str) -> bool:
    """Record a Workshop subscription by its synthetic id. The frontend has already
    subscribed via SteamClient; reconcile enriches title/deps on the next refresh."""
    _clear_unsub_pending(fileid)
    store = _load_store(game.appid)
    if mod_id not in store:
        store[mod_id] = _workshop_record(
            fileid, game.appid, f"Workshop item {fileid}", "", "", fileid,
            is_library=fileid in game.library_workshop_ids,
        )
        _save_store(game.appid, store)
    return True


# The atomic file-placement primitive lives in install_txn so the modloader installers can share
# it without importing this (much larger) module. Re-exported here since the installers below and
# the test suite reference them as mods._StagedInstall etc.
from install_txn import _MODDY_ORIG_SUFFIX, _STAGED_BAK_SUFFIX, _discard, _StagedInstall, recover_journals  # noqa: E402,F401


# Re-export the split submodules' public API so `mods.<name>` keeps working for main.py / other
# backend modules / tests. (The bare-import hack means these must be flat siblings, not a package.)
# These imports sit at the BOTTOM of mods.py (after the store/vanilla/workshop defs above) so the
# split modules, which do `import mods` to reach the store helpers, find a fully-initialized module.
#
# IMPORTANT: `mods` must be the entry point — never import a mods_* submodule before `mods`. A
# submodule imported first runs `import mods`, which re-enters this facade mid-initialization and
# raises a circular ImportError (the `from mods_* import (...)` re-exports below aren't defined
# yet). main.py and the test harness both `import mods` first, so this holds in practice.
import mods_common      # noqa: E402
import mods_archive     # noqa: E402
import mods_pak         # noqa: E402
import mods_installers  # noqa: E402
import mods_smapi       # noqa: E402
import mods_palworld    # noqa: E402
import mods_crud        # noqa: E402

from mods_common import (  # noqa: F401
    _LOVELYIGNORE, _folder_mod_enabled, _tracked_present, _record_target_relpaths,
    mod_files_present, _flat_target_paths, _flat_mod_present,
    _flat_mod_enabled, _natives_mod_enabled, _dotprefix_disabled,
    _smapi_mod_present, _smapi_mod_enabled, _zipfolder_disabled_path,
    _zipfolder_present, _zipfolder_enabled, _zipfolder_prune_staging,
    _claimed_paths_map, _overwrite_guard, _restore_originals, _backup_version_dir,
    _atomic_dir_swap, _install_mod_file, _FOLDER_DISABLED_DIR,
)
from mods_archive import (  # noqa: F401
    _system_env, extract_archive, _is_archive_junk, _safe_folder_name, _detect_variants,
    _looks_like_nativepc_content, _is_loose_metadata, _strip_loose_wrapper,
    _LOOSE_METADATA_NAMES, _LOOSE_METADATA_EXTS, _MHW_NATIVEPC_DIRS,
)
from mods_pak import (  # noqa: F401
    _PAK_PATCH_RE, _next_pak_slot, _renumber_pak_mods,
)
from mods_installers import (  # noqa: F401
    _THUNDERSTORE_METADATA_FILES, _install_mod_zip_dir, _merge_zip_into_tree,
    _extract_to_game_root, _extract_bepinex_subdirs, _extract_bare_dll,
    _extract_to_mods_folder, _install_mod_zip_flat, _folder_commit,
    _install_mod_zip_folder, _smod_plugin_root, _install_mod_zip_smod,
    _install_mod_loose_merge, _install_mod_zip_natives, _install_mod_zip_nativepc,
    install_folder_files, install_external_merge_files, _install_mod_external_merge, discard_natives_cache,
)
from mods_smapi import (  # noqa: F401
    _smapi_commit, _install_mod_zip_smapi, install_smapi_files,
)
from mods_palworld import (  # noqa: F401
    _PALWORLD_PAK_EXTS, _PALWORLD_PAKS_DIR, _PALWORLD_UE4SS_MODS_DIR, _PW_CANON,
    _pw_remap_ue4ss, _pw_pak_dest, _pw_is_lua, _pw_lua_placements,
    _palworld_placements, _palworld_commit, _install_mod_zip_palworld,
    install_palworld_files,
)
from mods_crud import (  # noqa: F401
    mods_under_modloader, _RUNTIME_SCRATCH_SUFFIXES, _MODDY_NEW_SUFFIX,
    _MODDY_OLD_SUFFIX, sweep_runtime_scratch, _restore_or_discard,
    _sweep_crumbs_in_dir, sweep_install_crumbs, _prune_empty_dirs,
    get_installed_mods, install_mod, get_backed_up_versions,
    delete_mod_version, uninstall_mod, _toggle_lovelyignore, toggle_mod,
)
