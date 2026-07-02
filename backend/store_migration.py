"""One-shot adopter: rewrite a legacy (schema-1) installed.json into the per-game
schema-2 shape game_store owns. THROWAWAY dev tooling for the single pre-alpha device —
delete this module (and its hook in game_store._load) once that device has migrated.

Legacy shape: top-level "mods" (one GLOBAL mod_id → record map), "vanilla"
({appid: snapshot}); later commits move "modloaders" and "profiles" too. Assignment:

- workshop records route by their recorded "appid" field (no disk scan needed)
- every other record is assigned to EVERY installed game whose disk actually holds its
  files (mods_common.mod_files_present — the same presence scan that used to scope the
  global store at read time). A shared Thunderstore id installed for two games becomes
  two independent records, which is precisely the point of schema 2.
- a record matching no installed game (game uninstalled, SD card absent, orphaned
  record) is stashed under top-level "unadopted_mods" — never silently dropped.
- the original file is copied aside once to installed.json.pre-schema2 as the rollback
  artifact (the rolling .bak gets overwritten with the NEW shape next session).

All heavyweight imports are function-local: game_store is imported at the top of
mods.py, and importing mods_common at module level here would re-enter the mods facade
mid-initialization (see the import-order note at the bottom of mods.py).
"""

import copy

import decky
import json_store

# Top-level legacy sections this adopter understands. Grows as profiles move
# under "games" in a later commit.
_LEGACY_KEYS = ("mods", "vanilla", "modloaders")


def needs_adoption(full: dict) -> bool:
    """A legacy file has per-game data at top level and no "games" section yet. A fresh
    or empty store must NOT trigger (nothing to adopt); a corrupt file never reaches
    here (json_store.read quarantines it and returns {})."""
    return "games" not in full and any(k in full for k in _LEGACY_KEYS)


def adopt(path: str, full: dict) -> dict:
    import shutil
    try:
        shutil.copy2(path, path + ".pre-schema2")
    except OSError:
        pass  # nothing on disk to preserve (dict-injected fixtures)

    games: dict = {}
    unadopted = _adopt_mods(full.pop("mods", None) or {}, games)
    unadopted_ml = _adopt_modloaders(full.pop("modloaders", None) or {}, games)
    for appid, snapshot in (full.pop("vanilla", None) or {}).items():
        games.setdefault(str(appid), {})["vanilla"] = snapshot

    full["games"] = games
    if unadopted:
        full["unadopted_mods"] = unadopted
        decky.logger.warning(
            f"store adoption: {len(unadopted)} record(s) matched no installed game — "
            f"kept under 'unadopted_mods' for hand recovery")
    if unadopted_ml:
        full["unadopted_modloaders"] = unadopted_ml
        decky.logger.warning(
            f"store adoption: {len(unadopted_ml)} modloader entr(ies) matched no supported "
            f"game — kept under 'unadopted_modloaders'")
    json_store.write(path, full)
    decky.logger.info(
        f"Adopted legacy installed.json into the per-game schema ({len(games)} game(s))")
    return full


def _adopt_mods(records: dict, games: dict) -> dict:
    import registry
    import steam
    import mods_common

    installed = []  # (game, install_dir) for every supported game present on disk
    for g in registry.SUPPORTED_GAMES:
        d = steam.find_game_install_dir(g.appid)
        if d:
            installed.append((g, d))

    unadopted: dict = {}
    for mod_id, rec in records.items():
        if (rec.get("source") or {}).get("type") == "steamworkshop" and rec.get("appid"):
            games.setdefault(str(rec["appid"]), {}).setdefault("mods", {})[mod_id] = rec
            continue
        placed = False
        for g, d in installed:
            if mods_common.mod_files_present(g, d, rec):
                # deepcopy: a shared id adopted into several games must not alias nested
                # meta/source dicts across them.
                games.setdefault(str(g.appid), {}).setdefault("mods", {})[mod_id] = copy.deepcopy(rec)
                placed = True
        if not placed:
            unadopted[mod_id] = rec
    return unadopted


def _adopt_modloaders(records: dict, games: dict) -> dict:
    """Route each legacy modloader version entry to the game(s) declaring that loader id.
    Loader ids are unique per game today only by registry convention, so a multi-declarer
    tie is broken by whose install dir actually shows the loader's indicator."""
    import os
    import registry
    import steam

    unadopted: dict = {}
    for ml_id, entry in records.items():
        declaring = [g for g in registry.SUPPORTED_GAMES if g.get_modloader(ml_id)]
        targets = declaring
        if len(declaring) > 1:
            hits = []
            for g in declaring:
                d = steam.find_game_install_dir(g.appid)
                ml = g.get_modloader(ml_id)
                ind = ml.indicator if ml else ""
                if d and ind and (os.path.exists(os.path.join(d, ind))
                                  or os.path.exists(os.path.join(d, ind + ".disabled"))):
                    hits.append(g)
            targets = hits or declaring
        if not targets:
            unadopted[ml_id] = entry
            continue
        for g in targets:
            games.setdefault(str(g.appid), {}).setdefault("modloaders", {})[ml_id] = copy.deepcopy(entry)
    return unadopted
