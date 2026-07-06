import registry


# Thunderstore packages that should never be installed as plugins via Browse —
# modloaders (already provided by Mod Loader tab) and desktop mod-manager apps.
# Case-insensitive comparison. Frontend uses get_browse_denylist() to keep these
# off the Browse list too.
_BROWSE_DENYLIST = {
    "bbepis-bepinexpack",
    "riskofthunder-bepinexpack",
    "bepinex-bepinexpack_peak",  # PEAK modloader — installed via the Mod Loader tab, not as a plugin
    "bepinex-bepinexpack_etg",  # Enter the Gungeon modloader — installed via the Mod Loader tab, not as a plugin
    "denikson-bepinexpack_valheim",  # Valheim modloader — installed via the Mod Loader tab; mods declare it as a dep
    "bepinex-bepinexpack_rounds",  # ROUNDS modloader — installed via the Mod Loader tab; mods declare it as a dep
    "ebkr-r2modman",
    "kesomannen-galemodmanager",
    "thunderstore-lovely",  # Balatro injector — installed via the Mod Loader tab, not as a Mods/ plugin
}

# Nexus mods (by `nexus.<domain>.<mod_id>` install id, lowercase) that are tools/managers or
# loaders, not game content — never install them as a requirement, and hide them from Browse.
# Nexus-sourced modloaders (e.g. MHW's Stracker's Loader) are added automatically from the
# registry by nexus_browse_denylist(); only list loaders/tools that AREN'T a registered Nexus
# modloader here (e.g. a loader distributed off-Nexus but mirrored on it).
_NEXUS_DENYLIST = {
    "nexus.residentevil42023.14",  # Fluffy Mod Manager (desktop app, not an in-game mod)
    "nexus.residentevil42023.12",  # REFramework — installed via the Mod Loader tab (GitHub
    # source), but also mirrored on Nexus, so hide that listing
    "nexus.monsterhunterrise.7",  # Fluffy Mod Manager 5000 (desktop app, not an in-game mod)
    "nexus.monsterhunterrise.26",  # REFramework — installed via the Mod Loader tab (GitHub
    # source), but also mirrored on Nexus, so hide that listing
    "nexus.monsterhunterrise.181",  # HunterPie v2 — external .NET overlay app, not an in-game
    # mod; runs as a separate process (Moddy can't install/run it)
    "nexus.stardewvalley.2400",  # SMAPI — installed via the Mod Loader tab (GitHub source), but
    # also mirrored on Nexus where ~every mod lists it as a required
    # mod; hide that listing and skip it as a dependency (it has no
    # manifest.json, so zip_smapi would reject it anyway)
    "nexus.site.818",  # Fluffy Mod Manager 5000 (site-wide Nexus listing some mods require)
    "nexus.palworld.1121",  # UE4SS Prepackaged — the loader, installed via the Mod Loader
    # tab (GitHub Okaetsu/RE-UE4SS), also listed on Nexus; hide it
    "nexus.palworld.3405",  # RE-UE4SS (Experimental) Linux — same loader, another listing
}


def nexus_browse_denylist() -> set[str]:
    """The full set of Nexus install ids (nexus.<domain>.<mod_id>, lowercase) to keep out of
    Browse AND out of the dependency cascade: the hand-curated _NEXUS_DENYLIST plus every game's
    Nexus-sourced modloader, derived from the registry so a newly-added Nexus modloader is hidden
    automatically (no second place to update)."""
    ids = set(_NEXUS_DENYLIST)
    for g in registry.SUPPORTED_GAMES:
        for ml in g.modloaders:
            s = ml.source
            if s.type == "nexus" and s.nexus_domain and s.mod_id:
                ids.add(f"nexus.{s.nexus_domain}.{s.mod_id}".lower())
    return ids


def ficsit_browse_denylist() -> set[str]:
    """Lowercase ficsit install ids (ficsit.<mod_reference>) to keep out of Browse and the
    dependency cascade: every game's ficsit-sourced modloader (Satisfactory's SML), derived from
    the registry so a newly-added ficsit loader is hidden automatically (no second place to update)."""
    ids: set[str] = set()
    for g in registry.SUPPORTED_GAMES:
        for ml in g.modloaders:
            if ml.source.type == "ficsit" and ml.source.mod_reference:
                ids.add(f"ficsit.{ml.source.mod_reference}".lower())
    return ids


def thunderstore_browse_denylist() -> set[str]:
    """The full set of Thunderstore package ids ('<owner>-<name>', lowercase) to keep out of Browse
    AND skip in the dependency cascade: the hand-curated _BROWSE_DENYLIST (legacy generic packs +
    desktop mod-manager apps) plus every game's Thunderstore-sourced modloader, derived from the
    registry so a newly-added BepInEx variant (e.g. BepInExPack_IL2CPP) is hidden automatically —
    no second place to update. Mirrors nexus_browse_denylist()/ficsit_browse_denylist()."""
    ids = set(_BROWSE_DENYLIST)
    for g in registry.SUPPORTED_GAMES:
        for ml in g.modloaders:
            s = ml.source
            if s.type == "thunderstore" and s.owner and s.repo:
                ids.add(f"{s.owner}-{s.repo}".lower())
    return ids
