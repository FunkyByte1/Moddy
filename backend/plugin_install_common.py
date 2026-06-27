import mods
import decky


async def rollback_installs(game: "registry.GameProfile", install_dir: str, ids: list) -> None:
    """Undo a cancelled install: uninstall the mods it freshly installed, newest first (so a
    mod is removed before the dependencies it sits on). Pre-existing mods aren't in this list,
    so a shared dependency installed by an earlier job is left untouched."""
    for mod_id in reversed(ids):
        try:
            await mods.uninstall_mod(game, install_dir, mod_id)
            decky.logger.info(f"Rolled back {mod_id} after cancelled install")
        except Exception as e:
            decky.logger.warning(f"Rollback of {mod_id} failed: {e}")
