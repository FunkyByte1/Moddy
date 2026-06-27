import decky
import registry
import steam
import nexus
import install_cascade
import mods
import download_queue
import plugin_install_denylists
import plugin_install_common


async def install_nexus_mod(appid: int, full_name: str, version: str | None = None,
                            variant: str | None = None, installed: "list | None" = None):
    """Install a Nexus mod by its `nexus.<domain>.<mod_id>` catalog id, via the Premium
    download link, recursively installing any declared same-domain Nexus requirements
    first. Returns True=success, False=failed, None=cancelled, and the string
    "premium_required" when the user's API key isn't Premium (v1 can't serve free
    downloads — those need the website's nxm:// handoff). When the mod's archive bundles
    multiple variants (e.g. RE4 stack-size .pak options) and `variant` isn't given, returns
    {"needs_variant": True, "variants": [...]} so the UI can ask which to install.
    `installed` collects the ids freshly installed this run (the queue passes the job's list so
    a parked-then-cancelled install can be rolled back); a cancel/failure rolls it back here."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "nexus":
        return False
    install_dir = steam.find_game_install_dir(appid)
    if not install_dir:
        return False
    parsed = nexus.parse_id(full_name)
    if not parsed:
        decky.logger.error(f"Bad Nexus install id: {full_name}")
        return False
    domain, mod_id = parsed
    if installed is None:
        installed = []

    # Multi-file picker (SMAPI / Stardew AND Palworld): a Nexus page can list several installable
    # files — alternate versions, platform variants (Steam vs GamePass/Xbox/Epic), or optional
    # add-ons. The `variant` channel carries the user's pick (comma-joined file ids from the
    # checklist). For Palworld most popular mods are multi-file (x2/x5/x10 tiers, Steam/GamePass),
    # so picking is the norm; non-Steam-platform files are dropped first (the Deck runs the Steam
    # build, so a GamePass io store pak won't load), which also auto-resolves a Steam/GamePass pair
    # to the single Steam file. (RE4/MHW archive-payload variants use zip_natives — they have no
    # selectable_files step and flow through the cascade below.)
    install_type = game.catalog.get("install_type")
    if install_type in ("zip_smapi", "zip_palworld"):
        if variant is None:
            files = nexus.selectable_files(domain, mod_id)
            if install_type == "zip_palworld":
                files = palworld_pick_files(files)
            if len(files) > 1:
                return {
                    "needs_variant": True,
                    "multi_select": True,  # the UI shows a checklist, not a single-pick list
                    "variants": [{"id": f["file_id"], "label": _nexus_file_label(f)}
                                 for f in files],
                }
            if install_type == "zip_palworld" and len(files) == 1:
                variant = str(files[0]["file_id"])  # the single (Steam) file — install it, not "primary"
        # else 0–1 files: nothing to choose — fall through to the normal cascade (is_primary picks).
        if variant is not None:
            file_ids = [x for x in variant.split(",") if x]
            res = await _install_nexus_multifile(
                game, install_dir, domain, mod_id, version, file_ids, seen=set(), installed=installed,
            )
            if (res is None or res is False) and installed:
                await plugin_install_common.rollback_installs(game, install_dir, installed)
            return res

    # No "N of M" pre-pass for Nexus: unlike Thunderstore's in-memory catalog, requirement
    # resolution is an uncached GraphQL call, so a pre-pass would double those calls — and a
    # rate-limited second call (the one that actually drives the cascade) could return nothing,
    # silently skipping requirements. The per-package sub-label + percent still show.
    res = await _install_nexus_recursive(
        game, install_dir, domain, mod_id, version, seen=set(), variant=variant, top=True,
        installed=installed,
    )
    # Roll back on cancel (None) or failure (False) — but NOT when parking for a variant choice
    # (a dict), which is resolved later. Requirements installed before the park are in
    # `installed`, so a subsequent cancel-at-prompt still rolls them back (via the queue hook).
    if (res is None or res is False) and installed:
        await plugin_install_common.rollback_installs(game, install_dir, installed)
    return res


async def _install_nexus_recursive(
    game: "registry.GameProfile",
    install_dir: str,
    domain: str,
    mod_id: str,
    version: str | None,
    seen: set,
    variant: str | None = None,
    top: bool = False,
    installed: "list | None" = None,
):
    """Install one Nexus mod plus its same-domain requirements (depth-first), via the shared
    cascade. Requirements install at latest; only the top-level mod honors an explicit version
    and variant. A failed requirement is best-effort (continue); a Premium-gated download aborts
    and surfaces "premium_required". Returns True/False/None/"premium_required"/needs-variant."""
    provider = install_cascade.NexusProvider(plugin_install_denylists.nexus_browse_denylist())
    return await install_cascade.run_cascade(
        provider, game, install_dir, (domain, mod_id), version,
        seen=seen, installed=installed, top=top, variant=variant,
    )


async def _install_nexus_multifile(game, install_dir, domain, mod_id, version, file_ids, *,
                                   seen, installed):
    """Install several user-chosen files of ONE Nexus SMAPI mod as a single library entry: its
    requirements first (via the shared cascade, best-effort like a normal Nexus install), then
    the chosen files downloaded and placed together under the one mod id (e.g. Stardew Valley
    Expanded's main download + its optional alternate farm). Returns
    True/False/None/"premium_required"."""
    provider = install_cascade.NexusProvider(plugin_install_denylists.nexus_browse_denylist())
    ref = (domain, mod_id)
    item = provider.find(game, ref)
    if item is None:
        return False
    seen.add(provider.key(ref))  # a requirement that lists this mod back can't re-pull it

    # 1) Requirements first (depth-first). Best-effort: a failed requirement warns but the mod
    # still installs (matches NexusProvider.deps_fatal=False).
    for dep_ref, dep_label in provider.dep_refs(game, item, ref):
        dep_res = await install_cascade.run_cascade(
            provider, game, install_dir, dep_ref, None,
            seen=seen, installed=installed, is_dependency=True,
        )
        if dep_res == install_cascade.PREMIUM_REQUIRED:
            return install_cascade.PREMIUM_REQUIRED
        if dep_res is None:
            return None
        if dep_res is False:
            decky.logger.warning(f"Dependency {dep_label} did not install (continuing)")
            await download_queue.note_warning(f"Couldn't install dependency: {dep_label}")

    # 2) Resolve a download URL for each chosen file (Premium-gated like any Nexus download).
    urls: list[str] = []
    for fid in file_ids:
        try:
            url = nexus.get_download_url(domain, mod_id, fid)
        except nexus.PremiumRequired:
            return install_cascade.PREMIUM_REQUIRED
        if url:
            urls.append(url)
    if not urls:
        decky.logger.error(f"nexus.{domain}.{mod_id}: no downloadable files among {file_ids}")
        return False

    # 3) Reuse the provider to build the ModInfo (id/meta/recorded deps), then install all chosen
    # files combined into that one record.
    spec = provider.build_install(game, item, ref, None)
    if spec == install_cascade.PREMIUM_REQUIRED:
        return install_cascade.PREMIUM_REQUIRED
    if spec is None:
        return False
    was_fresh = not mods.installed_files_present(game, install_dir, provider.key(ref))
    await download_queue.note_item(spec.mod.name)
    if spec.mod.source.install_type == "zip_palworld":
        res = await mods.install_palworld_files(game, install_dir, spec.mod, version or spec.version, urls)
    else:
        res = await mods.install_smapi_files(game, install_dir, spec.mod, version or spec.version, urls)
    if res is True and was_fresh and installed is not None:
        installed.append(spec.mod.id)
    return res


# Nexus file names that mark a non-Steam platform build (the Deck runs the Steam version, so a
# GamePass/Xbox/Epic io-store pak won't load). Substring match, case-insensitive.
_PW_NON_STEAM_MARKERS = (
    "game pass", "gamepass", "game-pass", "(xbox", "xbox app", "(epic", "epic games",
    "io store", "io-store", "iostore", "(ms ", "(microsoft", "windows store", "(gp)", "(wsa",
)


def _pw_is_iostore_version(f: dict) -> bool:
    """A GamePass io-store build is often distinguished only by its VERSION, not its name —
    e.g. DekMCM uploads `1.9` (Steam) and `1.9io` (GamePass) with the identical name "DekMCM".
    Treat a version ending in `io` (or containing io-store) as GamePass so the Deck skips it."""
    v = (f.get("version", "") or "").lower().replace(" ", "").replace("-", "").replace("_", "")
    return v.endswith("io") or "iostore" in v


def palworld_pick_files(files: list) -> list:
    """Drop clearly-non-Steam-platform files from a Palworld mod's selectable list — by name
    marker (GamePass/Xbox/Epic) OR by an io-store version (`…io`). The Deck runs the Steam build,
    so those won't load; dropping them also auto-collapses a Steam/GamePass pair to the one Steam
    file (no picker). If filtering would remove everything, keep all (best-effort)."""
    kept = [f for f in files
            if not any(m in (f.get("name", "") or "").lower() for m in _PW_NON_STEAM_MARKERS)
            and not _pw_is_iostore_version(f)]
    return kept or files


def _nexus_file_label(f: dict) -> str:
    """Picker label for one selectable Nexus file: name + version (when the version isn't already
    in the name) + category/recommended flags. Surfacing the version disambiguates same-NAMED
    files (e.g. a mod's Steam vs GamePass uploads, or two tiers sharing a display name)."""
    label = f.get("name", "") or ""
    ver = (f.get("version", "") or "").strip()
    if ver and ver.lower() not in label.lower():
        label += f" (v{ver})"
    if f.get("category") == "OPTIONAL":
        label += " (optional)"
    if f.get("is_primary"):
        label += " — recommended"
    return label
