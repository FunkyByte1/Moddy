"""Thunderstore Modpacks — install a whole curated pack in one go.

A Thunderstore "modpack" is just a regular package in the **Modpacks** category whose own archive is
essentially empty (manifest.json + icon + README); the actual content is its `dependencies` list. So
installing a modpack means installing that dependency tree — NOT the modpack package itself — exactly
the same depth-first cascade a normal Browse install runs, minus the top package.

This is the Thunderstore counterpart to nexus_collections: it produces the same item/detail shapes
(CollectionItem / CollectionDetail) and stamps the same `collection:<slug>` provenance, so the whole
frontend (Collections tab, Installed-tab grouping, ref-counted uninstall) is reused unchanged — only
the user-facing noun differs ("Modpacks" vs "Collections"), applied in the UI. The slug is the
modpack's Thunderstore full_name (e.g. "BROGAN-BROPEAK").

v1 scope: required deps only at latest (Thunderstore deps carry no curator-optionals / FOMOD choices),
best-effort per mod via the shared cascade. The modpack package's own archive is never placed.
"""
import decky

import registry
import steam
import mods
import download_queue
import install_cascade
import thunderstore
import plugin_install_denylists

_MODPACK_CATEGORY = "modpacks"  # Thunderstore category name (matched case-insensitively)
_MODPACKS_PAGE = 25


def _is_thunderstore_game(appid: int):
    """The game profile if this appid's Browse venue is Thunderstore, else None. A Thunderstore game
    is one with a `thunderstore_community` and a catalog type of "thunderstore" — which is the default
    when no explicit `catalog.type` is set (most Thunderstore games, e.g. RoR2, omit it), matching the
    canonical derivation in plugin_game_status / registry."""
    game = registry.get_game_by_appid(appid)
    if not game or not game.thunderstore_community:
        return None
    if (game.catalog.get("type") or "thunderstore") != "thunderstore":
        return None
    return game


def is_modpack(pkg: dict) -> bool:
    """True if a trimmed catalog package is in Thunderstore's Modpacks category."""
    return any((c or "").lower() == _MODPACK_CATEGORY for c in pkg.get("categories", []))


def _deps(pkg: dict) -> list:
    """A modpack package's declared dependency strings ('<owner>-<name>-<version>')."""
    return (pkg.get("latest") or {}).get("dependencies", []) or []


def _modpack_item(pkg: dict) -> dict:
    """Shape a modpack package into the CollectionItem the Collections browse tab consumes."""
    latest = pkg.get("latest") or {}
    return {
        "slug": pkg["full_name"],                       # the modpack's Thunderstore full_name
        "name": pkg.get("name", "") or pkg["full_name"],
        "author": pkg.get("owner", "") or "",
        "summary": latest.get("description", "") or "",
        "mod_count": len(_deps(pkg)),
        "endorsements": pkg.get("rating_score", 0) or 0,  # Thunderstore "likes" stand in for endorsements
        "tile_image": latest.get("icon", "") or "",
    }


def game_has_modpacks(appid: int) -> bool:
    """Whether this game's Thunderstore community has ANY modpack — gates the Collections tab. Reads
    the cached catalog only (never fetches), so it's cheap on the latency-sensitive status path."""
    game = _is_thunderstore_game(appid)
    if not game:
        return False
    catalog = thunderstore.get_cached_community_catalog(game.thunderstore_community) or []
    return any(is_modpack(p) for p in catalog)


def list_modpacks_for_game(appid: int, query: str = "", page: int = 1) -> list:
    """A page of Thunderstore modpacks for the game's Collections browse tab, in CollectionItem shape.
    Filters the cached community catalog to the Modpacks category, search-matches full_name/description,
    sorts by likes, and client-paginates. Returns [] for non-Thunderstore games."""
    game = _is_thunderstore_game(appid)
    if not game:
        return []
    catalog = thunderstore.get_community_catalog(game.thunderstore_community)
    packs = [p for p in catalog if is_modpack(p) and not p.get("is_deprecated")]
    q = (query or "").strip().lower()
    if q:
        packs = [p for p in packs
                 if q in p["full_name"].lower() or q in (p.get("latest") or {}).get("description", "").lower()]
    packs.sort(key=lambda p: p.get("rating_score", 0) or 0, reverse=True)
    offset = max(0, (page - 1) * _MODPACKS_PAGE)
    return [_modpack_item(p) for p in packs[offset:offset + _MODPACKS_PAGE]]


def get_modpack_detail(appid: int, slug: str) -> dict:
    """A modpack's display detail (CollectionDetail shape): name/image/description + the mods it would
    install (its declared dependencies, resolved against the catalog for name + thumbnail). `slug` is
    the modpack's full_name. Modpack deps carry no optional flag, so every member lists optional=False.
    Returns {} for a non-Thunderstore game / unknown modpack."""
    game = _is_thunderstore_game(appid)
    if not game:
        return {}
    community = game.thunderstore_community
    pkg = thunderstore.find_package(community, slug)
    if not pkg or not is_modpack(pkg):
        return {}
    latest = pkg.get("latest") or {}
    mods_out, seen = [], set()
    for dep in _deps(pkg):
        parsed = thunderstore.parse_dep(dep)
        full_name = parsed[0] if parsed else dep
        key = full_name.lower()
        if key in seen:
            continue
        seen.add(key)
        member = thunderstore.find_package(community, full_name)
        m_latest = (member or {}).get("latest") or {}
        mods_out.append({
            "mod_id": full_name,                                  # full_name doubles as the ref/id
            "name": (member or {}).get("name") or full_name,
            "thumbnail": m_latest.get("icon", "") or "",
            "optional": False,
        })
    return {
        "slug": slug,
        "name": pkg.get("name", "") or slug,
        "image": latest.get("icon", "") or "",
        "summary": latest.get("description", "") or "",
        "mod_count": len(mods_out),
        "mods": mods_out,
    }


def _member_closure(provider, game, ref, seen: set, out: list) -> None:
    """All full_names in the dependency closure of `ref`, regardless of installed state — the modpack's
    complete member set. Mirrors run_cascade/collect_plan's skip logic (denylist) but, unlike them,
    does NOT drop already-present mods: we need present members to CLAIM them for the modpack. Reads
    the in-memory catalog only (no downloads)."""
    key = provider.key(ref)
    if key in seen or key in provider.denylist:
        return
    seen.add(key)
    item = provider.find(game, ref)
    if item is None:
        return
    out.append(ref)
    for dep_ref, _label in provider.dep_refs(game, item, ref):
        _member_closure(provider, game, dep_ref, seen, out)


async def run_modpack(appid: int, full_name: str, job) -> "bool | None":
    """Install a modpack's whole dependency tree (best-effort, at latest), stamping the modpack's
    collection:<full_name> provenance on every member so the Installed tab groups them and a later
    "uninstall modpack" ref-counts them. The modpack package's own (empty) archive is never installed.
    Returns True if anything installed/claimed, False on failure, None on cancel. A cancel rolls back
    only the mods THIS run freshly placed (ref-counted), leaving prior/manual installs intact."""
    game = _is_thunderstore_game(appid)
    install_dir = steam.find_game_install_dir(appid)
    if not game or not install_dir:
        return False
    pkg = thunderstore.find_package(game.thunderstore_community, full_name)
    if not pkg or not is_modpack(pkg):
        decky.logger.error(f"modpack {full_name}: not found in catalog / not a modpack")
        return False

    deps = []
    for dep in _deps(pkg):
        parsed = thunderstore.parse_dep(dep)
        if parsed:
            deps.append(parsed[0])
        else:
            decky.logger.warning(f"modpack {full_name}: unparseable dependency {dep!r}")
    if not deps:
        decky.logger.error(f"modpack {full_name}: declares no installable dependencies")
        return False

    name = pkg.get("name", "") or full_name
    job.name = f"Modpack: {name}"  # nicer than the bare full_name in the queue
    sid = f"collection:{full_name}"
    source = {"id": sid, "name": name, "image": (pkg.get("latest") or {}).get("icon", "") or ""}

    denylist = plugin_install_denylists._BROWSE_DENYLIST
    provider = install_cascade.ThunderstoreProvider(denylist)

    # The complete member set (transitive closure of the modpack's deps), so we can size progress and
    # claim already-present members. Walked from the deps — the modpack package itself is never a member.
    members: list = []
    member_seen: set = set()
    for dep in deps:
        _member_closure(provider, game, dep, member_seen, members)
    # Already-installed members: claim them for this modpack (ref-counting) without re-downloading.
    present = [r for r in members
               if mods.installed_files_present(game, install_dir, provider.key(r))]
    to_download = [r for r in members if r not in present]
    await download_queue.note_total(len(to_download))

    installed_ids: list = []  # mods THIS run placed — rolled back on cancel

    async def _rollback_run() -> None:
        for mid in installed_ids:
            try:
                if not mods.remove_record_source(mid, sid):
                    await mods.uninstall_mod(game, install_dir, mid)
            except Exception as e:  # noqa: BLE001 — best-effort cleanup
                decky.logger.warning(f"modpack {full_name}: rollback of {mid} failed: {e}")

    # Claim present members up front (a re-install / overlapping modpack keeps them, ref-counted).
    # add_record_source resolves the record case-insensitively, so the catalog-cased ref is fine.
    for ref in present:
        mods.add_record_source(ref, source)

    seen: set = set()
    for dep in deps:
        if getattr(job, "cancel_requested", False):
            await _rollback_run()
            return None
        try:
            res = await install_cascade.run_cascade(
                provider, game, install_dir, dep, None, seen=seen, installed=installed_ids,
                top=True, with_deps=True, allow_missing=True, source=source,
            )
        except Exception as e:  # noqa: BLE001 — one bad mod must not abort the whole modpack
            decky.logger.error(f"modpack {full_name}: {dep} errored: {e}")
            res = False
        if res is None:
            await _rollback_run()
            return None  # cancelled mid-download
        if res is False:
            await download_queue.note_warning(f"Couldn't install {dep}")

    decky.logger.info(f"modpack {full_name}: {len(installed_ids)} newly installed, "
                      f"{len(present)} already present (of {len(members)} members)")
    return len(installed_ids) > 0 or len(present) > 0


async def enqueue_modpack(appid: int, full_name: str) -> int:
    """Queue installing a whole modpack (its dependency tree) as one background job. `full_name` is the
    modpack's Thunderstore full_name. Returns the job id, or -1 for a non-Thunderstore game."""
    game = _is_thunderstore_game(appid)
    if not game:
        return -1
    return await download_queue.enqueue(
        appid, f"Modpack: {full_name}", f"collection:{full_name}", "thunderstore",
        run=lambda job: run_modpack(appid, full_name, job),
        rollback=None,
    )
