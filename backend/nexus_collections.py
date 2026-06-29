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


def _mod_info(game, domain: str, mod_id: str, name: str, author: str) -> registry.ModInfo:
    return registry.ModInfo(
        id=f"nexus.{domain}.{mod_id}",
        name=name,
        description="",
        filename=f"nexus-{mod_id}",
        source=registry.ModSource(
            type="nexus", install_type=game.catalog.get("install_type", "zip_flat"),
            nexus_domain=domain, mod_id=str(mod_id),
        ),
        author=author,
        homepage=f"https://www.nexusmods.com/{domain}/mods/{mod_id}",
        modloader=game.modloaders[0].id if game.modloaders else "",
    )


async def _install_one(game, install_dir: str, domain: str, m: dict):
    """Install one collection mod at its pinned file, replaying FOMOD choices (or defaults), never
    parking. Returns True / False / None(cancel) / PREMIUM_REQUIRED."""
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
    return await mods.install_mod(game, install_dir, mod, m.get("version"), url, variant)


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
    required = [m for m in mods_list if not m["optional"]]
    skipped = len(mods_list) - len(required)
    await download_queue.note_total(len(required))
    installed = 0
    for m in required:
        if getattr(job, "cancel_requested", False):
            return None
        await download_queue.note_item(m["name"])
        try:
            res = await _install_one(game, install_dir, domain, m)
        except Exception as e:  # noqa: BLE001 — one bad mod must not abort the collection
            decky.logger.error(f"collection {slug}: {m['name']} errored: {e}")
            res = False
        if res is True:
            installed += 1
        elif res == install_cascade.PREMIUM_REQUIRED:
            return "premium_required"
        elif res is None:
            return None  # cancelled mid-download
        else:
            await download_queue.note_warning(f"Couldn't install {m['name']}")
    if skipped:
        await download_queue.note_warning(f"{skipped} optional mod(s) skipped")
    decky.logger.info(f"collection {slug}: installed {installed}/{len(required)} required mods")
    return installed > 0


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
