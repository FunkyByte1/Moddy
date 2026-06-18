# Backend tests

Pure-stdlib `unittest` (no pytest dependency). Run from this directory:

```sh
cd tests && python3 -m unittest discover -p "test_*.py"
```

Backend modules `import decky`, which only exists in the Decky runtime. `_harness.py` stands up
a fake `decky` in `sys.modules` (with throwaway settings/runtime dirs) before importing anything
from `backend/`, so always import backend code *through the harness*:

```python
from _harness import mods, utils, registry, make_mod, make_game, build_zip, reset_store, stub_download, tree_snapshot
```

- `reset_store()` — fresh, empty installed.json store per test (call in `setUp`).
- `stub_download(writes=..., raises=...)` — replace `utils.download` to lay down a fixture
  archive or simulate a failed/cancelled download.
- `tree_snapshot(root)` — `{relpath: bytes}` of a tree, for asserting a failed install left it
  byte-identical.
- `failing_copy2(fail_on=N)` — context manager that makes `shutil.copy2` raise on its Nth call,
  to inject a mid-commit failure (`place()` uses copy2; staging extraction uses copyfileobj).
- `bak_crumbs(root)` — leftover `.moddy-bak` transaction artifacts (should be empty post-commit).

## Files

- `test_staged_install.py` — unit tests for the `_StagedInstall` transaction primitive.
- `test_install_characterization.py` — locks current installer success-path behavior.
- `test_merge_atomicity.py` — the zip_dir BepInEx merge installers roll back cleanly on failure.
- `test_flat_atomicity.py` — the zip_flat (MelonLoader) installer: failed/mid-commit upgrades
  restore the prior install (incl. retired directories); successful upgrades fully replace it.
- `test_natives_atomicity.py` — the zip_natives (RE4) installer: natives-path lowercasing, pak
  slotting above the base game, mid-commit rollback, slot reclaim on upgrade, variant parking that
  leaves the old install intact, and variant resume committing the chosen payload.
- `test_dirswap_atomicity.py` — the Shape-A folder-owning installers (bare_dll / to_mods_folder):
  atomic directory swap, failed extraction leaves the prior version intact, version-history
  backup preserved, single-wrapper and multi-dir layouts.
- `test_mod_presence.py` — mods.mod_files_present: an orphaned record (files deleted by a
  modloader uninstall, record left behind) reads as NOT present, so a reinstall re-places files
  instead of being skipped as already-installed.
- `test_modloader_atomicity.py` — the modloader installers (modloaders.py): a BepInEx update
  merges (preserving the user's BepInEx/plugins/), a MelonLoader update cleanly replaces its own
  dir while leaving Mods/ untouched, and both roll back on a failed update.

The atomic file-placement primitive (`_StagedInstall`, `_discard`) lives in `backend/install_txn.py`
and is shared by both `mods.py` and `modloaders.py`; `mods._StagedInstall` re-exports it.
- `test_toggle_characterization.py` — locks the on-disk effect of enable/disable for each install
  shape. Toggle is rename-only (no record write) so it isn't part of the staging work, but it's
  core behavior worth pinning while mods.py is under refactor.
