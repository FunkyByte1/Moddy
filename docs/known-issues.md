# Known issues / follow-ups

Tracked bugs we've decided to fix deliberately rather than mid-stream.

## Folder-level ownership collides for mods that share generic `plugins/` subfolders

**Status:** RESOLVED 2026-06-16 (per-file ownership). One migration caveat below.

**Fix:** the two "merge into BepInEx tree" installers (`_extract_to_game_root`,
`_extract_bepinex_subdirs`) now record every extracted file individually instead of the
2nd-level folder. Uninstall removes exactly those files and then prunes any now-empty parent
dirs via `_prune_empty_dirs` — which uses `os.rmdir` (fails on non-empty), so a folder still
holding another mod's files is never deleted. The bare-DLL / single-folder layouts
(`_extract_bare_dll`, `_extract_to_mods_folder`) were already collision-safe (dedicated
`<ModName>/` folder) and are unchanged. Verified end-to-end: installing Enforcer then
uninstalling it leaves a co-located mod's file in `plugins/Language/` intact.

**Migration caveat:** mods installed *before* this fix still carry the old directory-level
record, so uninstalling one of those can still collide. Reinstalling the mod rewrites its
record to per-file (no data migration of existing records — a disk scan can't safely tell
which files in a shared folder belong to which mod). New installs are safe automatically.

---

### Original report (kept for context)

**Status:** open — deferred (found 2026-06-16 while fixing Enforcer's "shows disabled" bug).

**Symptom:** uninstalling one mod can delete another mod's files.

**Repro:** Install `EnforcerGang-Enforcer` (RoR2). Its zip drops files directly into generic
folders under `plugins/` — `plugins/AssetBundles/`, `plugins/Language/`, `plugins/SoundBanks/` —
instead of namespacing under `plugins/Enforcer/`. The install records those folders as
*owned* by Enforcer (see `_extract_bepinex_subdirs` / `_extract_to_game_root` in
`backend/mods.py`, which track the 2nd-level dir under each BepInEx subdir). If a second mod
also writes into `plugins/Language/`, uninstalling Enforcer `rmtree`s the shared folder and
takes the other mod's files with it.

**Root cause:** ownership is tracked at the directory level (`BepInEx/<subdir>/<2nd-level>`),
which is only safe when mods namespace their files under a unique `plugins/<ModName>/`. Mods
that dump into shared/generic subfolders break that assumption. We can't fix it by recording
the parent (`plugins/`) — that's shared by everything — so the granularity has to change.

**Fix direction (needs design):**
- Track ownership per *file* (record the exact members extracted), so uninstall removes only
  the files this mod wrote and prunes now-empty dirs. This also fixes enable/disable scoping
  for these mods cleanly.
- Migration: existing records track dirs, not files — uninstall needs to keep handling the
  legacy dir-based records, or a one-time reconcile rewrites them.
- Watch the interaction with the bare-DLL handling added for Enforcer
  (`_folder_mod_enabled` / `_tracked_present` / the zip_dir toggle branch).

**Not urgent:** only bites on *uninstall* of a mod that shares a generic subfolder with
another installed mod. The "shows disabled" half of the Enforcer problem is already fixed.
