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

## Files

- `test_staged_install.py` — unit tests for the `_StagedInstall` transaction primitive.
- `test_install_characterization.py` — locks current installer success-path behavior. One
  `expectedFailure` documents the destructive-upgrade gap that the staging refactor will close;
  drop the decorator when `zip_flat` is converted.
