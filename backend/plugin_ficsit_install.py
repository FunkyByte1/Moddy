import decky
import registry
import steam
import ficsit
import install_cascade
import plugin_install_denylists
import plugin_install_common


async def install_ficsit_mod(appid: int, full_name: str, version: str | None = None,
                             installed: "list | None" = None):
    """Install a ficsit mod by its `ficsit.<mod_reference>` catalog id, recursively installing its
    (non-loader, non-optional) ficsit dependencies first via the shared cascade. SML — every mod's
    dependency — is skipped (managed by the modloader system). Returns True=success, False=failed,
    None=cancelled. `installed` collects the ids freshly installed this run (the queue passes the
    job's list so a cancel/failure rolls them back)."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "ficsit":
        return False
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return False
    ref = ficsit.parse_id(full_name)
    if not ref:
        decky.logger.error(f"Bad ficsit install id: {full_name}")
        return False
    if installed is None:
        installed = []
    provider = install_cascade.FicsitProvider(plugin_install_denylists.ficsit_browse_denylist())
    res = await install_cascade.run_cascade(
        provider, game, install_dir, ref, version, seen=set(), installed=installed, top=True,
    )
    if (res is None or res is False) and installed:
        await plugin_install_common.rollback_installs(game, install_dir, installed)
    return res
