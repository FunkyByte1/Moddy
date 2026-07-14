import decky
import registry
import steam
import install_cascade
import download_queue
import plugin_install_denylists
import plugin_install_common


async def install_thunderstore_mod(
    appid: int, full_name: str, version: str | None = None, with_deps: bool = True,
    allow_missing: bool = False,
) -> bool | None:
    """Install a Thunderstore mod by full_name (e.g. 'RiskofThunder-R2API_Core'),
    recursively installing any declared dependencies first. Already-installed
    deps and denylisted modloader packages are skipped. Pass with_deps=False to install
    only the named mod and leave its dependencies out (the UI's "skip dependencies").
    allow_missing=True installs the mod even if a declared dependency isn't in the catalog
    (it's skipped instead of failing — the UI's "install anyway").
    Returns True=success, False=failed, None=cancelled."""
    game = registry.get_game_by_appid(appid)
    if not game or not game.thunderstore_community:
        return False
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return False
    # Size the cascade up front (mod + deps that aren't already installed) so the UI can show
    # "N of M". Cheap — resolves against the in-memory catalog, no downloads.
    plan: list[str] = []
    _resolve_thunderstore_plan(game, full_name, version, with_deps, set(), plan, [],
                               install_dir, plugin_install_denylists.thunderstore_browse_denylist())
    await download_queue.note_total(len(plan))
    # Atomic cancel: track the packages this run freshly installs so a cancel mid-cascade can
    # undo them, leaving the system as if the install never started. Updates of already-present
    # mods aren't tracked (a cancelled download leaves the prior version intact).
    installed_this_run: list[str] = []
    result = await _install_thunderstore_recursive(
        game, install_dir, full_name, version, seen=set(), with_deps=with_deps,
        installed_this_run=installed_this_run, allow_missing=allow_missing,
        denylist=plugin_install_denylists.thunderstore_browse_denylist(),
    )
    # Roll back on cancel (None) or hard failure (False) — either way the install didn't
    # complete, so leave no partial trace.
    if not result and installed_this_run:
        await plugin_install_common.rollback_installs(game, install_dir, installed_this_run)
    return result


def _resolve_thunderstore_plan(
    game: "registry.GameProfile", full_name: str, version: str | None,
    with_deps: bool, seen: set, plan: list, unresolved: list, install_dir: str | None = None,
    denylist: set = None,
) -> None:
    """Size the Thunderstore cascade (depth-first packages it will download, into `plan`) and
    collect declared deps not in the catalog (into `unresolved`), via the shared dry-run walk."""
    provider = install_cascade.ThunderstoreProvider(denylist)
    install_cascade.collect_plan(
        provider, game, full_name, version=version, with_deps=with_deps,
        seen=seen, plan=plan, unresolved=unresolved, install_dir=install_dir,
    )


async def _install_thunderstore_recursive(
    game: "registry.GameProfile",
    install_dir: str,
    full_name: str,
    version: str | None,
    seen: set,
    with_deps: bool = True,
    installed_this_run: "list | None" = None,
    allow_missing: bool = False,
    is_dependency: bool = False,
    denylist: set = None,
) -> bool | None:
    """Install a Thunderstore mod plus its dependencies (depth-first), via the shared cascade.
    Already-installed deps and denylisted packages are skipped; a failed/missing dependency
    aborts (unless allow_missing skips a missing one). Returns True/False/None."""
    provider = install_cascade.ThunderstoreProvider(denylist)
    return await install_cascade.run_cascade(
        provider, game, install_dir, full_name, version,
        seen=seen, installed=installed_this_run, with_deps=with_deps,
        allow_missing=allow_missing, is_dependency=is_dependency,
    )
