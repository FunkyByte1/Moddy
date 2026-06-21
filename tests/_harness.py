"""Shared test harness for the backend mod-install code.

The backend modules (`mods`, `utils`, `steam`, `registry`, `fetch`) all `import decky`,
which only exists inside the Decky plugin runtime. We stand up a fake `decky` module in
`sys.modules` before importing anything from `backend/`, pointing its settings/runtime dirs
at throwaway temp dirs so the installed.json store and extraction scratch live in isolation.

Tests import via this harness so the fake is always installed first:

    from _harness import mods, utils, registry, make_mod, make_game, build_zip, reset_store
"""
import os
import sys
import types
import json
import shutil
import tempfile
import zipfile

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
_BACKEND = os.path.join(_REPO_ROOT, "backend")


def _install_fake_decky() -> types.ModuleType:
    if "decky" in sys.modules:
        return sys.modules["decky"]
    decky = types.ModuleType("decky")

    class _Logger:
        # Capture nothing; tests assert on filesystem state, not log lines.
        def info(self, *a, **k):
            pass

        error = warning = debug = info

    decky.logger = _Logger()
    decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp(prefix="moddy-settings-")
    decky.DECKY_PLUGIN_RUNTIME_DIR = tempfile.mkdtemp(prefix="moddy-runtime-")
    decky.DECKY_USER_HOME = tempfile.mkdtemp(prefix="moddy-home-")

    async def _emit(*a, **k):
        return None

    decky.emit = _emit
    sys.modules["decky"] = decky
    return decky


decky = _install_fake_decky()
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
# Also expose the repo root so tests can `import main` (the plugin entrypoint lives there, not in
# backend/). Without this the cascade tests error at collection with "No module named 'main'".
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import mods       # noqa: E402
import utils      # noqa: E402
import registry   # noqa: E402


def reset_store() -> None:
    """Point the installed.json store at a fresh temp dir and drop the in-memory cache, so
    each test starts with an empty store and can't see another test's records."""
    decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp(prefix="moddy-settings-")
    decky.DECKY_PLUGIN_RUNTIME_DIR = tempfile.mkdtemp(prefix="moddy-runtime-")
    mods._INSTALLED_STORE = None


def make_game(appid: int = 1, mods_dir: str = "BepInEx/plugins") -> "registry.GameProfile":
    """A minimal game whose mods dir is install_dir/<mods_dir>. mods_dir='' means the game root
    (the RE4 shape)."""
    return registry.GameProfile(
        id=f"game{appid}", name=f"Game {appid}", appid=appid, mods_dir=mods_dir,
    )


def make_mod(mod_id: str = "test.mod", filename: str = "TestMod",
             install_type: str = "file", **source_kw) -> "registry.ModInfo":
    src = registry.ModSource(type="thunderstore", install_type=install_type, **source_kw)
    return registry.ModInfo(
        id=mod_id, name=mod_id, description="", filename=filename, source=src,
    )


def build_zip(path: str, entries: dict) -> str:
    """Write a zip at `path` whose members are `entries` {arcname: bytes|str}. Returns `path`."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for arcname, data in entries.items():
            if isinstance(data, str):
                data = data.encode()
            z.writestr(arcname, data)
    return path


def tree_snapshot(root: str) -> dict:
    """Map every file under `root` to its bytes. Used to assert a failed install left the live
    tree byte-identical to before."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            with open(full, "rb") as f:
                out[os.path.relpath(full, root)] = f.read()
    return out


class failing_copy2:
    """Context manager that replaces shutil.copy2 with one that delegates to the real call but
    raises on the `fail_on`-th invocation. _StagedInstall.place() uses copy2 to land each file
    while staging extraction uses copyfileobj, so this fails only the commit phase — the window
    the transaction must protect."""

    def __init__(self, fail_on: int):
        import shutil
        self._shutil = shutil
        self.calls = 0
        self.fail_on = fail_on
        self._real = shutil.copy2

    def __enter__(self):
        self._shutil.copy2 = self
        return self

    def __exit__(self, *exc):
        self._shutil.copy2 = self._real
        return False

    def __call__(self, src, dst, *a, **k):
        self.calls += 1
        if self.calls == self.fail_on:
            raise OSError("simulated disk failure")
        return self._real(src, dst, *a, **k)


def bak_crumbs(root: str) -> list[str]:
    """Every leftover .moddy-bak transaction artifact under `root` (should be empty post-commit)."""
    return [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".moddy-bak")]


def stub_download(*, writes: dict | None = None, raises: Exception | None = None):
    """Build a replacement for utils.download. If `raises`, it raises that (e.g. a generic
    Exception or utils.InstallCancelledError) after doing nothing. Otherwise it writes a zip
    built from `writes` (an entries dict) to the requested dest, mimicking a finished download."""
    async def _download(url, dest, appid):
        if raises is not None:
            raise raises
        build_zip(dest, writes or {})
    return _download
