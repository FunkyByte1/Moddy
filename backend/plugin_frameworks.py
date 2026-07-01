import decky
import registry
import mods
import github


async def ensure_framework(game: "registry.GameProfile", install_dir: str, key: str) -> bool:
    """Install a framework mod (e.g. Steamodded, Talisman) into the Mods folder if it
    isn't already present. Frameworks are declared per-game under `frameworks` in the
    game JSON and downloaded as GitHub branch archives into Mods/<filename>/."""
    fw = game.frameworks.get(key)
    if not fw:
        decky.logger.warning(f"No framework config '{key}' for {game.id}")
        return False
    fw_id = fw.get("id", key)
    if mods.get_installed_record(game.appid, fw_id) is not None:
        return True  # already installed
    src = fw.get("source", {})
    owner, repo = src.get("owner", ""), src.get("repo", "")
    if not owner or not repo:
        decky.logger.warning(f"Framework '{key}' for {game.id} has no GitHub source")
        return False
    url = github.get_source_url(owner, repo, src.get("branch", "main"))
    mod = registry.ModInfo(
        id=fw_id,
        name=fw.get("name", key),
        description=fw.get("description", ""),
        filename=fw.get("filename", fw_id),
        source=registry.ModSource(type="url", url=url, install_type="zip_dir"),
        author=owner,
        homepage=f"https://github.com/{owner}/{repo}",
        modloader=game.modloaders[0].id if game.modloaders else "",
    )
    decky.logger.info(f"Installing framework {fw.get('name', key)} for {game.id}")
    return bool(await mods.install_mod(game, install_dir, mod, version="latest", url=url))
