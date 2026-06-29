"""Nexus Collections — install a whole curated collection in one go.

A collection is a curator's list of mods (+ the FOMOD installer choices they made). We fetch the
collection's manifest (a tiny tar shipped at its download_link), then install each mod through the
normal Nexus install path, but: pinned to the collection's exact fileId, FOMOD choices replayed
(mapped onto the engine's selections — see fomod.selections_from_choices), and NON-interactively
(no wizard/variant prompt — COLLECTION_AUTO) since one job installs many mods.

v1 scope: mods for THIS game's Nexus domain, required mods (optional ones are skipped + noted),
best-effort per mod (a failure warns and continues). Bundled curator files and load-order (modRules)
are not applied — rare for the games Moddy supports. See project_fomod_support / the collections memo.
"""
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit, urlunsplit

import decky

import registry
import app_settings as settings  # bare `settings` collides with decky_loader.settings
import steam
import nexus
import fetch
import mods
import mods_fomod
import mods_archive
import download_queue
import install_cascade

_COLLECTION_URL_RE = re.compile(r"nexusmods\.com/(?:games/)?([a-z0-9]+)/collections/([A-Za-z0-9]+)", re.I)
_API_BASE = "https://api.nexusmods.com"


def parse_ref(text: str, default_domain: str) -> "tuple[str | None, str | None]":
    """Resolve a collection reference to (domain, slug). Accepts a Nexus collection URL
    (…/games/<domain>/collections/<slug> or the older …/<domain>/collections/<slug>), a
    `<domain>/<slug>` pair, or a bare `<slug>` (uses the current game's domain)."""
    text = (text or "").strip()
    m = _COLLECTION_URL_RE.search(text)
    if m:
        return m.group(1).lower(), m.group(2)
    if "/" in text and " " not in text:
        d, _, s = text.partition("/")
        if d and re.fullmatch(r"[A-Za-z0-9]+", s):
            return d.lower(), s
    if re.fullmatch(r"[A-Za-z0-9]+", text):
        return default_domain, text
    return None, None


def _esc(s: str) -> str:
    return json.dumps(s)[1:-1]  # escape for inlining into the GraphQL string


_COLLECTIONS_PAGE = 25


def game_has_collections(appid: int) -> bool:
    """Whether this game's Nexus venue has ANY collections at all — adult OR not, ignoring the NSFW
    setting. Drives whether to show the Collections tab: presence reflects "this game has collections"
    (so a game with none, e.g. Slime Rancher 2, hides the tab), while the list inside still filters
    adult content per the setting. False for non-Nexus games / no API key / on error."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "nexus":
        return False
    domain = game.catalog.get("nexus_domain", "")
    if not domain:
        return False
    gql = ('{ collectionsV2(count:1, filter:{gameDomain:{value:"%s",op:EQUALS}}){ nodes { slug } } }'
           % _esc(domain))
    try:
        data = fetch.post_json(nexus.GRAPHQL_URL, {"query": gql}, headers=nexus._headers())
    except nexus.MissingApiKey:
        return False
    if not isinstance(data, dict) or data.get("errors"):
        return False
    return bool((((data.get("data") or {}).get("collectionsV2") or {}).get("nodes")) or [])


def list_collections_for_game(appid: int, query: str = "", page: int = 1) -> list:
    """A page of collections for a game whose Browse source is Nexus, for the in-app collections
    list. Sorted by endorsements; adult collections excluded unless the NSFW setting is on (matching
    the mods catalog). Returns [] for non-Nexus games / no API key / on error."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "nexus":
        return []
    domain = game.catalog.get("nexus_domain", "")
    if not domain:
        return []
    include_adult = bool(settings.get_setting("nexus_include_adult", False))
    offset = max(0, (page - 1) * _COLLECTIONS_PAGE)
    parts = ['gameDomain:{value:"%s",op:EQUALS}' % _esc(domain)]
    if query and len(query) >= 2:
        parts.append('generalSearch:{value:"%s",op:WILDCARD}' % _esc(query))
    if not include_adult:
        parts.append("adultContent:{value:false,op:EQUALS}")
    gql = ('{ collectionsV2(count:%d, offset:%d, filter:{%s}, sort:[{endorsements:{direction:DESC}}]){ '
           'nodes { slug name summary endorsements tileImage{url} user{name} '
           'latestPublishedRevision{ modCount } } } }' % (_COLLECTIONS_PAGE, offset, ",".join(parts)))
    try:
        data = fetch.post_json(nexus.GRAPHQL_URL, {"query": gql}, headers=nexus._headers())
    except nexus.MissingApiKey:
        return []
    if not isinstance(data, dict) or data.get("errors"):
        decky.logger.error(f"collections list error: {data.get('errors') if isinstance(data, dict) else data}")
        return []
    nodes = (((data.get("data") or {}).get("collectionsV2") or {}).get("nodes")) or []
    out = []
    for n in nodes:
        rev = n.get("latestPublishedRevision") or {}
        out.append({
            "slug": n.get("slug", ""),
            "name": n.get("name", "") or n.get("slug", ""),
            "author": (n.get("user") or {}).get("name", "") or "",
            "summary": n.get("summary", "") or "",
            "mod_count": rev.get("modCount", 0) or 0,
            "endorsements": n.get("endorsements", 0) or 0,
            "tile_image": (n.get("tileImage") or {}).get("url", "") or "",
        })
    return out


def collection_card(domain: str, slug: str) -> dict:
    """A collection's display card — {name, image} — for stamping onto each mod it installs so the
    Installed page can show the collection's name + tile icon (matching the Collections browse tab).
    Falls back to {name: slug, image: ""} on any error so an install never fails over cosmetics."""
    gql = ('{ collection(slug:"%s", domainName:"%s", viewAdultContent:true){ name tileImage{url} } }'
           % (_esc(slug), _esc(domain)))
    try:
        data = fetch.post_json(nexus.GRAPHQL_URL, {"query": gql}, headers=nexus._headers())
    except Exception:  # noqa: BLE001 — cosmetic; never block an install
        return {"name": slug, "image": ""}
    coll = ((data.get("data") or {}).get("collection") or {}) if isinstance(data, dict) else {}
    return {"name": coll.get("name") or slug, "image": (coll.get("tileImage") or {}).get("url", "") or ""}


def get_collection_detail(appid: int, slug: str) -> dict:
    """A collection's display detail for the UI — name, tile image, description, and its mod list
    (name + thumbnail + optional flag, deduped by mod). Drives the Collections browse-tab detail
    (list the mods you'd install) and the Installed-tab collection panel (description + members).
    Returns {} for a non-Nexus game / no API key / on error. One light GraphQL call (no tar download)."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "nexus":
        return {}
    domain = game.catalog.get("nexus_domain", "")
    if not domain:
        return {}
    gql = ('{ collection(slug:"%s", domainName:"%s", viewAdultContent:true){ name summary tileImage{url} '
           'latestPublishedRevision { modCount modFiles { optional file { mod { name modId pictureUrl } } } } } }'
           % (_esc(slug), _esc(domain)))
    try:
        data = fetch.post_json(nexus.GRAPHQL_URL, {"query": gql}, headers=nexus._headers())
    except nexus.MissingApiKey:
        return {}
    if not isinstance(data, dict) or data.get("errors"):
        decky.logger.error(f"collection {slug} detail error: {data.get('errors') if isinstance(data, dict) else data}")
        return {}
    coll = (data.get("data") or {}).get("collection")
    if not coll:
        return {}
    rev = coll.get("latestPublishedRevision") or {}
    mods_out, seen = [], set()
    for mf in (rev.get("modFiles") or []):
        mod = ((mf.get("file") or {}).get("mod")) or {}
        mid = mod.get("modId")
        if mid is None or mid in seen:  # a mod can appear via several files — list it once
            continue
        seen.add(mid)
        mods_out.append({
            "mod_id": str(mid),
            "name": mod.get("name") or f"mod {mid}",
            "thumbnail": mod.get("pictureUrl", "") or "",
            "optional": bool(mf.get("optional")),
        })
    return {
        "slug": slug,
        "name": coll.get("name") or slug,
        "image": (coll.get("tileImage") or {}).get("url", "") or "",
        "summary": coll.get("summary", "") or "",
        "mod_count": rev.get("modCount", 0) or 0,
        "mods": mods_out,
    }


def _download_link_path(domain: str, slug: str) -> "tuple[str, str] | None":
    """GraphQL: collection slug -> (name, download_link API path) for its latest published revision."""
    gql = ('{ collection(slug:"%s", domainName:"%s", viewAdultContent:true){ name '
           'latestPublishedRevision { downloadLink } } }' % (_esc(slug), _esc(domain)))
    data = fetch.post_json(nexus.GRAPHQL_URL, {"query": gql}, headers=nexus._headers())
    if not isinstance(data, dict) or data.get("errors"):
        decky.logger.error(f"collection {slug}: GraphQL error {data.get('errors') if isinstance(data, dict) else data}")
        return None
    coll = (data.get("data") or {}).get("collection")
    if not coll:
        return None
    link = ((coll.get("latestPublishedRevision") or {}).get("downloadLink")) or ""
    return (coll.get("name") or slug, link) if link else None


def _enc_url(u: str) -> str:
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%:@"), p.query, p.fragment))


def _download(url: str, dest: str) -> None:
    req = fetch.request(_enc_url(url))  # CDN link is pre-signed — no auth header needed
    with urllib.request.urlopen(req, context=fetch.ssl_context(), timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def fetch_manifest(domain: str, slug: str) -> "dict | None":
    """Download + parse a collection's manifest (collection.json inside its download_link tar).
    Returns the parsed manifest, or None if the collection isn't found / can't be fetched."""
    nm = _download_link_path(domain, slug)
    if not nm:
        return None
    _name, path = nm
    link = _API_BASE + path
    try:
        req = fetch.request(link, headers=nexus._headers())
        with urllib.request.urlopen(req, context=fetch.ssl_context(), timeout=30) as r:
            dl = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise nexus.PremiumRequired()
        decky.logger.error(f"collection {slug}: download_link failed ({e.code})")
        return None
    uri = (((dl or {}).get("download_links") or [{}])[0]).get("URI")
    if not uri:
        return None
    runtime = decky.DECKY_PLUGIN_RUNTIME_DIR
    arc = os.path.join(runtime, f"collection_{slug}.archive")
    ext = os.path.join(runtime, f"collection_{slug}_x")
    try:
        _download(uri, arc)
        if os.path.exists(ext):
            shutil.rmtree(ext)
        mods_archive.extract_archive(arc, ext)
        with open(os.path.join(ext, "collection.json"), "rb") as f:
            return json.load(f)
    finally:
        if os.path.exists(arc):
            os.remove(arc)
        if os.path.exists(ext):
            shutil.rmtree(ext)


def collection_mods(manifest: dict, domain: str) -> list:
    """Pull the installable Nexus mods for `domain` out of a manifest: (mod_id, file_id, name,
    author, version, optional, choices). Skips non-Nexus / other-game / malformed entries."""
    out = []
    for m in (manifest.get("mods") or []):
        src = m.get("source") or {}
        if src.get("type") != "nexus" or not src.get("modId") or not src.get("fileId"):
            continue
        if (m.get("domainName") or "").lower() != domain.lower():
            continue
        out.append({
            "mod_id": str(src["modId"]),
            "file_id": str(src["fileId"]),
            "name": m.get("name") or f"mod {src['modId']}",
            "author": m.get("author") or "",
            "version": m.get("version"),
            "optional": bool(m.get("optional")),
            "choices": m.get("choices"),
        })
    return out


def installable_mods(game, mods_list: list, domain: str) -> list:
    """The required mods a collection install should actually place: required (not optional), minus
    the game's modloader (e.g. MHW's Stracker's Loader, nexus 1982) — that's managed by the modloader
    system, not installed as a mod, so a collection must skip it (else it shows up as a stray mod)."""
    return [m for m in mods_list
            if not m["optional"] and not install_cascade._is_game_modloader(game, domain, m["mod_id"])]


def _mod_info(game, domain: str, mod_id: str, name: str, author: str) -> registry.ModInfo:
    # Fetch the mod's page info so the Installed entry has a description + thumbnail (the manifest
    # only carries name/author); fall back to the manifest values if the lookup fails.
    info = nexus.get_mod(domain, mod_id) or {}
    return registry.ModInfo(
        id=f"nexus.{domain}.{mod_id}",
        name=info.get("name") or name,
        description=info.get("summary", "") or "",
        filename=f"nexus-{mod_id}",
        source=registry.ModSource(
            type="nexus", install_type=game.catalog.get("install_type", "zip_flat"),
            nexus_domain=domain, mod_id=str(mod_id),
        ),
        author=info.get("author") or info.get("uploaded_by") or author,
        homepage=f"https://www.nexusmods.com/{domain}/mods/{mod_id}",
        thumbnail=info.get("picture_url", "") or "",
        modloader=game.modloaders[0].id if game.modloaders else "",
    )


async def _install_one(game, install_dir: str, domain: str, m: dict, source: dict | None = None):
    """Install one collection mod at its pinned file, replaying FOMOD choices (or defaults), never
    parking. Returns True / False / None(cancel) / PREMIUM_REQUIRED. `source` stamps the mod's
    Installed-page provenance (collection:<slug>) so it can be grouped + ref-count-uninstalled."""
    try:
        url = nexus.get_download_url(domain, m["mod_id"], m["file_id"])
    except nexus.PremiumRequired:
        return install_cascade.PREMIUM_REQUIRED
    if not url:
        return False
    mod = _mod_info(game, domain, m["mod_id"], m["name"], m["author"])
    # FOMOD mods: replay the curator's choices (a dict the engine maps by name); everything else
    # installs non-interactively (FOMOD defaults / first variant) via the COLLECTION_AUTO sentinel.
    variant = json.dumps(m["choices"]) if m.get("choices") else mods_fomod.COLLECTION_AUTO
    return await mods.install_mod(game, install_dir, mod, m.get("version"), url, variant, source=source)


async def run_collection(appid: int, domain: str, slug: str, job) -> "bool | None | str":
    """Install every required mod in a collection (best-effort). Returns True if any installed,
    False if none did, None on cancel, "premium_required" if the account isn't Premium."""
    game = registry.get_game_by_appid(appid)
    install_dir = steam.find_game_install_dir(appid)
    if not game or not install_dir:
        return False
    try:
        manifest = fetch_manifest(domain, slug)
    except nexus.PremiumRequired:
        return "premium_required"
    except nexus.MissingApiKey:
        return False
    except Exception as e:  # noqa: BLE001
        decky.logger.error(f"collection {slug}: fetch failed: {e}")
        return False
    if not manifest:
        decky.logger.error(f"collection {slug}: not found / no manifest")
        return False

    mods_list = collection_mods(manifest, domain)
    required = installable_mods(game, mods_list, domain)  # required, minus the modloader
    optional_mods = [m for m in mods_list
                     if m["optional"] and not install_cascade._is_game_modloader(game, domain, m["mod_id"])]
    coll_name = (manifest.get("info") or {}).get("name") or slug
    job.name = f"Collection: {coll_name}"  # nicer than the bare slug in the queue + the optional picker

    # Let the user pick which curator-optional mods to add (cosmetic / mutually-exclusive variant
    # picks). Park ONCE on the first run to ask — nothing is installed yet, so a cancel/dismiss leaves
    # the game untouched; the resume carries the chosen mod_ids (comma-joined; empty = add none). Rides
    # the same park/resume rails as the FOMOD wizard / file picker. Skipped when there are no optionals.
    def _present(m) -> bool:
        return mods.installed_files_present(game, install_dir, f"nexus.{domain}.{m['mod_id']}")

    chosen_optional: list = []
    if optional_mods:
        if getattr(job, "variant", None) is None:
            # Offer only optionals NOT already on disk — a re-install shouldn't re-list ones you have.
            # Already-installed optionals stay put (they're skipped below as present). No new ones to
            # offer (all present) → don't park, just top up the required mods.
            offerable = [m for m in optional_mods if not _present(m)]
            if offerable:
                return {"needs_options": True, "options": [
                    {"id": m["mod_id"], "name": m["name"], "file_id": m["file_id"]} for m in offerable]}
        else:
            chosen_ids = {x for x in (job.variant or "").split(",") if x}
            chosen_optional = [m for m in optional_mods if m["mod_id"] in chosen_ids]
    to_install = required + chosen_optional

    # Provenance stamped on every mod this collection installs, so the Installed page can group them
    # (name + tile icon) and offer a ref-counted "Uninstall collection". Tile image from the collection
    # card (cosmetic — failures fall back to no image).
    card = collection_card(domain, slug)
    sid = f"collection:{slug}"
    source = {"id": sid, "name": coll_name, "image": card.get("image", "")}

    # A re-install / top-up: members already on disk (a prior install, or a mod installed manually /
    # by another collection) are CLAIMED for this collection (so uninstall-collection ref-counts them)
    # and skipped — only the missing ones are (re)downloaded. That's what lets a re-install cheaply
    # restore deleted mods and add newly-chosen optionals without re-fetching the whole set.
    to_install_missing = []
    for m in to_install:
        if _present(m):
            mods.add_record_source(f"nexus.{domain}.{m['mod_id']}", source)
        else:
            to_install_missing.append(m)
    already_present = len(to_install) - len(to_install_missing)
    await download_queue.note_total(len(to_install_missing))
    installed = 0
    installed_ids: list[str] = []  # mods THIS run placed — torn down if the user cancels

    async def _rollback_run() -> None:
        # Cancel means "install nothing": ref-counted teardown of just the mods this run added. A mod
        # that was already installed (e.g. manually, or by an earlier run) keeps its other sources and
        # stays — we only drop THIS collection's claim and remove a mod orphaned by that.
        for mid in installed_ids:
            try:
                remaining = mods.remove_record_source(mid, sid)
                if not remaining:
                    await mods.uninstall_mod(game, install_dir, mid)
            except Exception as e:  # noqa: BLE001 — best-effort cleanup
                decky.logger.warning(f"collection {slug}: rollback of {mid} failed: {e}")

    for m in to_install_missing:
        if getattr(job, "cancel_requested", False):
            await _rollback_run()
            return None
        await download_queue.note_item(m["name"])
        try:
            res = await _install_one(game, install_dir, domain, m, source)
        except Exception as e:  # noqa: BLE001 — one bad mod must not abort the collection
            decky.logger.error(f"collection {slug}: {m['name']} errored: {e}")
            res = False
        if res is True:
            installed += 1
            installed_ids.append(f"nexus.{domain}.{m['mod_id']}")  # the id _mod_info/install_mod recorded
        elif res == install_cascade.PREMIUM_REQUIRED:
            return "premium_required"
        elif res is None:
            await _rollback_run()
            return None  # cancelled mid-download
        else:
            await download_queue.note_warning(f"Couldn't install {m['name']}")
    # Optionals the user left out — but only the ones not already installed (an installed optional they
    # didn't re-select isn't "skipped", it's still there). Name them so they can be added by hand.
    skipped_optional = [m for m in optional_mods if m not in chosen_optional and not _present(m)]
    if skipped_optional:
        names = ", ".join(m["name"] for m in skipped_optional)
        decky.logger.info(f"collection {slug}: skipped {len(skipped_optional)} optional mod(s): {names}")
        await download_queue.note_warning(f"Skipped {len(skipped_optional)} optional mod(s): {names}")
    decky.logger.info(f"collection {slug}: {installed} newly installed, {already_present} already present "
                      f"(of {len(to_install)})")
    return installed > 0 or already_present > 0


async def enqueue_collection(appid: int, ref_text: str) -> int:
    """Resolve a collection reference and enqueue a single job that installs it. Returns the job id,
    or -1 if the game isn't a Nexus game or the reference is for a different game / unparseable."""
    game = registry.get_game_by_appid(appid)
    if not game or game.catalog.get("type") != "nexus":
        return -1
    domain = game.catalog.get("nexus_domain", "")
    d, slug = parse_ref(ref_text, domain)
    if not slug or (d and d != domain):
        decky.logger.error(f"collection ref {ref_text!r}: unparseable or wrong game (domain {domain})")
        return -1
    return await download_queue.enqueue(
        appid, f"Collection: {slug}", f"collection:{slug}", "nexus",
        run=lambda job: run_collection(appid, domain, slug, job),
    )


def collection_members(slug: str) -> list:
    """Mod ids currently tagged as belonging to collection `slug` (any game), from their records."""
    sid = f"collection:{slug}"
    return [mid for mid, rec in mods._load_store().items() if sid in (rec.get("sources") or {})]


def preview_uninstall_collection(slug: str) -> dict:
    """What "Uninstall collection <slug>" would do, WITHOUT touching anything: which member mods
    would be removed (sole source is this collection) vs kept (also manual / in another collection).
    Lets the UI show an honest "removes N · keeps M" summary before the user commits."""
    sid = f"collection:{slug}"
    store = mods._load_store()
    remove, keep = [], []
    for mid, rec in store.items():
        sources = rec.get("sources") or {}
        if sid not in sources:
            continue
        name = (rec.get("meta") or {}).get("name") or mid
        (keep if [k for k in sources if k != sid] else remove).append(name)
    return {"remove": remove, "keep": keep}


async def uninstall_collection(appid: int, slug: str) -> dict:
    """Ref-counted "remove this collection": drop the collection:<slug> membership from each of its
    mods; a mod whose last source was this collection is uninstalled, one still wanted by `manual`
    or another collection STAYS (no surprise removals). Returns {removed, kept} mod-id lists."""
    game = registry.get_game_by_appid(appid)
    install_dir = steam.find_game_install_dir(appid)
    if not game or not install_dir:
        return {"removed": [], "kept": []}
    sid = f"collection:{slug}"
    removed, kept = [], []
    for mid in collection_members(slug):
        remaining = mods.remove_record_source(mid, sid)
        if remaining:
            kept.append(mid)  # still wanted by manual / another collection — leave its files
        else:
            try:
                await mods.uninstall_mod(game, install_dir, mid)
                removed.append(mid)
            except Exception as e:  # noqa: BLE001 — one bad removal must not abort the rest
                decky.logger.error(f"uninstall collection {slug}: {mid} failed: {e}")
    decky.logger.info(f"collection {slug}: removed {len(removed)}, kept {len(kept)}")
    return {"removed": removed, "kept": kept}
