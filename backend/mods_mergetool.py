"""Generic runner for external "merge tool" mod loaders.

Some games (Fields of Mistria via MOMI; Hades via ModImporter, later) are modded by an EXTERNAL CLI
that reads every mod folder in the game's mods dir and MERGES them into a shared game file (e.g.
data.win), rebuilding it from the tool's OWN pristine backup on every run (idempotent). Moddy's job
is therefore small: download the CLI once, and call run_apply()/run_restore() after mod changes and
for loader enable/disable. All tool-specific knobs live in the loader's declarative MergeToolInfo
(registry.MergeToolInfo), so a second tool is mostly JSON.

The CLI is invoked with cwd = the game install dir (MOMI's fallback when its Steam scan misses, and
a guaranteed anchor on multi-library Decks) and a sanitised env (Steam's LD_* overrides stripped,
plus the tool's declared env like EXIT_ON_COMPLETE=true). The self-contained .NET single-file ELF
extracts its bundle at first run, so DOTNET_BUNDLE_EXTRACT_BASE_DIR/TMPDIR are pointed at a writable
scratch dir under the plugin runtime dir.
"""
import os
import glob
import asyncio
import fnmatch
import subprocess

import decky
import github
import utils
import mods_archive
import game_store
import steam

_SECTION = "mergetool"
_APPLY_TIMEOUT = 600  # seconds; patching data.win + JSONs is not instant but shouldn't hang forever
_DEBOUNCE_SEC = 1.2   # settle window: coalesce a burst of mod changes into ONE rebuild
_pending: "dict[int, asyncio.Future]" = {}  # appid -> in-flight settle-and-apply task


def merge_loader(game) -> "object | None":
    """The game's external-merge-tool loader (source.type=='external_cli' carrying a merge_tool), or None."""
    return next((ml for ml in game.modloaders
                 if ml.source.type == "external_cli" and ml.merge_tool), None)


# ── tool binary lifecycle ────────────────────────────────────────────────────

def tool_dir(ml) -> str:
    """Where the CLI binary lives — under the plugin runtime dir, NOT the game dir (survives game
    verify/uninstall and is never seen by the tool as a mod)."""
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "mergetools", ml.id)


def tool_binary_path(ml) -> str:
    cfg = ml.merge_tool
    d = tool_dir(ml)
    if cfg.asset_is_zip:
        return os.path.join(d, cfg.binary_in_zip) if cfg.binary_in_zip else os.path.join(d, cfg.asset)
    return os.path.join(d, os.path.basename(cfg.asset))


def is_tool_available(ml) -> bool:
    b = tool_binary_path(ml)
    return os.path.isfile(b) and os.access(b, os.X_OK)


async def ensure_tool_installed(game, install_dir, ml, version=None) -> bool:
    """Download the CLI asset from its GitHub release to tool_dir, extract if zipped, chmod +x, and
    record the version. Isolated bare-binary handling — does NOT go through _install_github_modloader
    (which assumes a zip payload placed in the game dir)."""
    cfg = ml.merge_tool
    if not cfg or not cfg.owner or not cfg.repo or not cfg.asset:
        decky.logger.error(f"merge tool {ml.id}: incomplete merge_tool config")
        return False
    if version:
        url = github.get_download_url_for_version(cfg.owner, cfg.repo, version, cfg.asset)
        resolved = version
    else:
        res = github.get_latest_download_url(cfg.owner, cfg.repo, cfg.asset)
        if not res:
            decky.logger.error(f"merge tool {ml.id}: asset {cfg.asset} not found in latest release")
            return False
        resolved, url = res
    if not url:
        decky.logger.error(f"merge tool {ml.id}: no download URL for {cfg.asset}@{version or 'latest'}")
        return False

    d = tool_dir(ml)
    os.makedirs(d, exist_ok=True)
    dl_dest = os.path.join(d, os.path.basename(cfg.asset))
    try:
        await utils.download(url, dl_dest, game.appid)
    except Exception as e:
        decky.logger.error(f"merge tool {ml.id}: download failed: {e}")
        return False

    if cfg.asset_is_zip:
        try:
            mods_archive.extract_archive(dl_dest, d)
        except Exception as e:
            decky.logger.error(f"merge tool {ml.id}: extract failed: {e}")
            return False
        try:
            os.remove(dl_dest)
        except OSError:
            pass

    binary = tool_binary_path(ml)
    if not os.path.isfile(binary):
        decky.logger.error(f"merge tool {ml.id}: binary not found at {binary} after install")
        return False
    try:
        os.chmod(binary, 0o755)
    except OSError as e:
        decky.logger.error(f"merge tool {ml.id}: chmod failed: {e}")
        return False

    import modloaders  # lazy: modloaders imports this module
    modloaders.set_modloader_version(game.appid, ml.id, resolved)
    decky.logger.info(f"merge tool {ml.id}: installed {cfg.asset}@{resolved}")
    return True


# ── apply / restore (the rebuild step) ───────────────────────────────────────

async def run_apply(game, install_dir, ml) -> bool:
    """Rebuild the game's shared file from the current mod folders. Clears the tool's stale pristine
    backups first if the game was updated (else the tool would revert the update). Idempotent."""
    if not is_tool_available(ml):
        decky.logger.error(f"merge tool {ml.id}: binary unavailable; cannot apply")
        return False
    cfg = ml.merge_tool
    if _buildid_changed(game.appid, install_dir):
        _clear_stale_backups(install_dir, cfg)
    ok = _run(ml, install_dir, list(cfg.apply_argv))
    sect = game_store.section(game.appid, _SECTION)
    sect["last_apply_ok"] = ok
    if ok:
        sect["applied"] = True
        sect["last_buildid"] = steam.get_build_id(game.appid)
    game_store.save()
    return ok


async def run_restore(game, install_dir, ml) -> bool:
    """Restore the game to pristine (unbake all mods) via the tool's restore command."""
    if not is_tool_available(ml):
        decky.logger.error(f"merge tool {ml.id}: binary unavailable; cannot restore")
        return False
    cfg = ml.merge_tool
    ok = _run(ml, install_dir, list(cfg.restore_argv))
    if ok:
        sect = game_store.section(game.appid, _SECTION)
        sect["applied"] = False
        game_store.save()
    return ok


async def request_apply(game, install_dir, ml) -> None:
    """Coalesce a burst of mod changes into ONE rebuild. Marks the game dirty and (re)schedules a
    single settle-then-apply task, so installing/deleting a HANDFUL of mods rebuilds data.win once
    instead of once per mod. The rebuild fires once the install queue is idle AND no newer change has
    landed for _DEBOUNCE_SEC. Returns immediately — the mod op no longer blocks on the (slow) rebuild.
    A crash before it fires leaves the dirty flag set; recover_pending() flushes it on next startup."""
    appid = game.appid
    game_store.section(appid, _SECTION)["dirty"] = True
    game_store.save()
    try:
        await decky.emit("game_status_stale", appid)  # UI shows "Applying mods…"
    except Exception:
        pass
    prev = _pending.get(appid)
    if prev is not None and not prev.done():
        prev.cancel()
    _pending[appid] = asyncio.ensure_future(_settle_and_apply(game, install_dir, ml))


async def _settle_and_apply(game, install_dir, ml) -> None:
    import download_queue  # lazy — avoid an import cycle
    appid = game.appid
    try:
        while True:
            await asyncio.sleep(_DEBOUNCE_SEC)
            if not download_queue.is_active():  # don't rebuild mid-batch; wait for the queue to drain
                break
    except asyncio.CancelledError:
        return  # a newer change rescheduled us — let that task do the (single) rebuild
    if game_store.section(appid, _SECTION).get("dirty"):
        game_store.section(appid, _SECTION)["dirty"] = False
        game_store.save()
        await run_apply(game, install_dir, ml)
        try:
            await decky.emit("game_status_stale", appid)  # clear "Applying mods…" once baked
        except Exception:
            pass
    _pending.pop(appid, None)


def is_apply_pending(appid: int) -> bool:
    """True while a coalesced rebuild is queued/running (mods staged but not yet baked in) — the UI
    shows 'Applying mods…' so the user doesn't launch mid-rebuild."""
    return bool(game_store.section(appid, _SECTION).get("dirty"))


async def flush_pending(appid: int) -> bool:
    """Apply now if a rebuild is pending — startup recovery for a dirty flag left by a crash/unload.
    Returns True if it rebuilt, False if nothing was pending / couldn't resolve the game."""
    import registry  # lazy
    if not game_store.section(appid, _SECTION).get("dirty"):
        return False
    game = registry.get_game_by_appid(appid)
    ml = merge_loader(game) if game else None
    install_dir = steam.find_game_install_dir(appid)
    if not game or not ml or not install_dir or not is_tool_available(ml):
        return False
    game_store.section(appid, _SECTION)["dirty"] = False
    game_store.save()
    return await run_apply(game, install_dir, ml)


async def recover_pending() -> None:
    """On plugin startup, flush any external-merge game left with a pending rebuild (dirty flag)."""
    for appid_str in list(game_store.appids()):
        try:
            appid = int(appid_str)
        except (TypeError, ValueError):
            continue
        try:
            await flush_pending(appid)
        except Exception as e:
            decky.logger.error(f"merge tool: recover_pending failed for {appid}: {e}")


async def reapply(appid: int) -> dict:
    """User-triggered rebuild of an external-merge game's shared file from the current mod set — used
    after a Steam game update wiped the baked mods (see is_stale). run_apply clears the tool's stale
    pristine backups first so the update is preserved. Returns {"ok": bool, "reason": str}."""
    import registry  # lazy — avoid registry load cost at module import
    game = registry.get_game_by_appid(appid)
    if not game:
        return {"ok": False, "reason": "unknown game"}
    ml = merge_loader(game)
    if not ml:
        return {"ok": False, "reason": "not an external-merge game"}
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return {"ok": False, "reason": "game not installed"}
    if not is_tool_available(ml):
        return {"ok": False, "reason": "mod tool not installed"}
    ok = await run_apply(game, install_dir, ml)
    return {"ok": ok, "reason": "" if ok else "the mod tool failed to apply"}


def is_applied(appid: int) -> bool:
    """Whether mods are currently baked in (loader 'enabled'). Defaults True so a freshly-installed
    loader reads as enabled until an explicit restore."""
    return bool(game_store.section(appid, _SECTION).get("applied", True))


def last_apply_ok(appid: int) -> bool:
    return bool(game_store.section(appid, _SECTION).get("last_apply_ok", True))


# ── helpers ──────────────────────────────────────────────────────────────────

def _run(ml, install_dir, argv) -> bool:
    binary = tool_binary_path(ml)
    try:
        result = subprocess.run(
            [binary, *argv], cwd=install_dir, env=_merge_env(ml),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=_APPLY_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        decky.logger.error(f"merge tool {ml.id}: timed out after {_APPLY_TIMEOUT}s")
        return False
    except Exception as e:
        decky.logger.error(f"merge tool {ml.id}: failed to run: {e}")
        return False
    if result.returncode != 0:
        err = result.stderr.decode(errors="replace").strip()[:300] if result.stderr else f"exit {result.returncode}"
        decky.logger.error(f"merge tool {ml.id}: {' '.join(argv) or '(apply)'} failed: {err}")
        return False
    return True


def _merge_env(ml) -> dict:
    env = mods_archive._system_env()  # strip Steam's LD_LIBRARY_PATH/LD_PRELOAD
    scratch = os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "mergetools", "_scratch")
    os.makedirs(scratch, exist_ok=True)
    env["DOTNET_BUNDLE_EXTRACT_BASE_DIR"] = scratch  # self-contained .NET ELF extracts here on first run
    env["TMPDIR"] = scratch
    env.setdefault("HOME", decky.DECKY_USER_HOME)
    env.update(ml.merge_tool.env)  # e.g. EXIT_ON_COMPLETE=true
    return env


def _clear_stale_backups(install_dir, cfg) -> None:
    """Delete the tool's own pristine backups (data.bak.win, *.bak.json) so a game update becomes the
    new baseline. Walks the game dir (skipping the mods subdir) matching each glob against basenames."""
    patterns = list(cfg.backup_glob or [])
    if not patterns:
        return
    removed = 0
    for root, dirs, files in os.walk(install_dir):
        if "mods" in dirs:
            dirs.remove("mods")  # never touch mod folders
        for name in files:
            if any(fnmatch.fnmatch(name, pat) for pat in patterns):
                try:
                    os.remove(os.path.join(root, name))
                    removed += 1
                except OSError:
                    pass
    if removed:
        decky.logger.info(f"merge tool: cleared {removed} stale backup file(s) after game update")


def _buildid_changed(appid: int, install_dir: str) -> bool:
    cur = steam.get_build_id(appid)
    if not cur:
        return False  # can't tell — don't clear backups on a false signal
    last = game_store.section(appid, _SECTION).get("last_buildid")
    return cur != last


def is_stale(appid: int) -> bool:
    """True if the game was updated (build id changed) SINCE mods were last applied — Steam overwrote
    the shared game file, so the baked mods are gone until a reapply. False when mods were never
    applied (nothing baked to be stale) — unlike _buildid_changed, which treats first-apply as changed
    so run_apply harmlessly clears (absent) backups."""
    last = game_store.section(appid, _SECTION).get("last_buildid")
    if not last:
        return False
    cur = steam.get_build_id(appid)
    return bool(cur) and cur != last


def detect_high_risk(mod_root: str, cfg) -> bool:
    """Whether an extracted mod contains a high-risk native payload (e.g. Aurie aurie/*.dll)."""
    glob_pat = getattr(cfg, "high_risk_glob", "") if cfg else ""
    if not glob_pat:
        return False
    for root, _dirs, files in os.walk(mod_root):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), mod_root).replace(os.sep, "/")
            if fnmatch.fnmatch(rel, glob_pat) or fnmatch.fnmatch(rel, "*/" + glob_pat):
                return True
    return False
