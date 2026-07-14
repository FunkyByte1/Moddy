import os
import shutil
import decky
import registry
import steam
import mods
import modloaders


async def reset_game(appid: int) -> dict:
    """Reset a game to its unmodded state: uninstall every tracked mod, then every
    installed modloader, then remove any orphaned mods directory left behind.
    Returns a summary: {ok, mods_removed, modloader_removed}.
    Order matters — mods are removed before the modloader so their install records
    get cleared while their files still exist (uninstalling the modloader wipes the
    whole BepInEx/ tree, which would orphan those records)."""
    import shutil
    game = registry.get_game_by_appid(appid)
    if not game:
        return {"ok": False, "mods_removed": 0, "modloader_removed": False}
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return {"ok": False, "mods_removed": 0, "modloader_removed": False}

    mods_removed = 0
    failures = 0
    for entry in mods.get_installed_mods(game, install_dir):
        if await mods.uninstall_mod(game, install_dir, entry["id"]):
            mods_removed += 1
        else:
            failures += 1

    modloader_removed = False
    for ml in game.modloaders:
        if not modloaders.is_modloader_installed(game, install_dir, ml.id):
            continue
        if await modloaders.uninstall_modloader(game, install_dir, ml.id):
            modloader_removed = True
        else:
            failures += 1

    # Clean up an orphaned mods directory (e.g. MelonLoader's Mods/ folder, which
    # lives outside the modloader dir and so survives its uninstall). For BepInEx
    # this path sits under BepInEx/ and is already gone — the guard makes it a no-op.
    # CRITICAL: never rmtree when the "mods dir" IS the game root (mods_dir="", e.g. RE4) —
    # that would delete the entire game. Such games keep mods as tracked loose/.pak files
    # (already removed by the per-mod uninstall loop above), so there's no dir to orphan.
    try:
        mods_path = mods.resolve_mods_path(game, install_dir)
        if os.path.isdir(mods_path) and os.path.normpath(mods_path) != os.path.normpath(install_dir):
            shutil.rmtree(mods_path)
            decky.logger.info(f"Removed orphaned mods dir {mods_path}")
    except Exception as e:
        decky.logger.error(f"Failed to remove mods dir during reset: {e}")
        failures += 1

    decky.logger.info(
        f"Reset {game.name}: removed {mods_removed} mod(s), "
        f"modloader_removed={modloader_removed}, failures={failures}"
    )
    return {
        "ok": failures == 0,
        "mods_removed": mods_removed,
        "modloader_removed": modloader_removed,
    }


async def set_game_vanilla_mode(appid: int, vanilla: bool) -> dict:
    """Switch a game between modded and vanilla WITHOUT deleting anything. Entering vanilla
    disables every enabled mod and the modloader, recording what was on; leaving restores
    exactly that state (a mod the user had individually disabled stays disabled). Nothing is
    re-downloaded — files are just toggled aside, so it's instant and reversible.

    File-based mods and the modloader are handled here. Steam Workshop items aren't file-based
    (Steam owns them), so they're reported back as `workshop` fileids for the frontend to flip
    via SteamClient; `modloader_id` is returned when the loader was toggled so the frontend can
    add/remove its launch options. Returns a summary dict."""
    game = registry.get_game_by_appid(appid)
    if not game:
        return {"ok": False, "vanilla": vanilla}
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return {"ok": False, "vanilla": vanilla}

    failures = 0
    if vanilla:
        if mods.is_game_vanilla(appid):
            return {"ok": True, "vanilla": True, "noop": True}
        snapshot_mods: list[str] = []
        workshop: list[str] = []
        for entry in mods.get_installed_mods(game, install_dir):
            if not entry.get("enabled", True):
                continue
            rec = mods.get_installed_record(game.appid, entry["id"]) or {}
            if (rec.get("source") or {}).get("type") == "steamworkshop":
                fileid = (rec.get("source") or {}).get("workshop_id")
                if fileid:
                    workshop.append(fileid)
                continue
            snapshot_mods.append(entry["id"])

        disabled = 0
        for mod_id in snapshot_mods:
            if await mods.toggle_mod(game, install_dir, mod_id, False):
                disabled += 1
            else:
                failures += 1

        modloader_id = None
        if game.modloaders:
            ml = game.modloaders[0]
            if modloaders.is_modloader_enabled(game, install_dir, ml.id):
                if await modloaders.disable_modloader(game, install_dir, ml.id):
                    modloader_id = ml.id
                else:
                    failures += 1

        mods.set_vanilla_state(appid, {"mods": snapshot_mods, "modloader": modloader_id, "workshop": workshop})
        decky.logger.info(f"{game.name} → vanilla: disabled {disabled} mod(s), modloader={modloader_id}, {len(workshop)} workshop")
        return {
            "ok": failures == 0, "vanilla": True,
            "mods_disabled": disabled, "modloader_id": modloader_id, "workshop": workshop,
        }

    # Leaving vanilla — restore the recorded state.
    snap = mods.get_vanilla_state(appid)
    if snap is None:
        return {"ok": True, "vanilla": False, "noop": True}

    modloader_id = snap.get("modloader")
    if modloader_id and game.get_modloader(modloader_id):
        if not await modloaders.enable_modloader(game, install_dir, modloader_id):
            failures += 1

    enabled = 0
    for mod_id in snap.get("mods", []):
        # Skip a mod that was uninstalled while vanilla — its record is gone.
        if mods.get_installed_record(game.appid, mod_id) is None:
            continue
        if await mods.toggle_mod(game, install_dir, mod_id, True):
            enabled += 1
        else:
            failures += 1

    mods.set_vanilla_state(appid, None)
    decky.logger.info(f"{game.name} → modded: re-enabled {enabled} mod(s), modloader={modloader_id}")
    return {
        "ok": failures == 0, "vanilla": False,
        "mods_enabled": enabled, "modloader_id": modloader_id, "workshop": snap.get("workshop", []),
    }
