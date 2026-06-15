"""Nexus Mods provider.

Nexus is two-headed and both heads use the same personal `apikey` header:
- v2 GraphQL (api.nexusmods.com/v2/graphql) for browse/search — the v1 REST API has no
  text search. Free-text search is the `nameStemmed` filter with op WILDCARD.
- v1 REST for per-mod details, file lists, and the download link.

v1 SCOPE = Premium downloads only. The v1 download_link endpoint returns a direct CDN URL
for Premium accounts; free accounts get HTTP 403 (they'd need the website's nxm:// handoff,
which is out of scope). A 403 is surfaced to the user as "requires Nexus Premium".

Catalog items are emitted in the shared `catalog.CatalogItem` shape so the Browse UI renders
Nexus mods with no new types. Install ids are `nexus.<domain>.<mod_id>`; the file_id is NOT
part of the id (it changes every update) — it's resolved from the file list at install time.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

import decky

import catalog
import fetch
# app_settings.py, aliased: a bare `settings` module collides with decky_loader.settings.
import app_settings as settings

API_V1 = "https://api.nexusmods.com/v1"
GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"

# Nexus's API Acceptable Use Policy asks every request to identify the application via
# Application-Name (kept consistent across versions) and Application-Version (current
# release). Keep APP_VERSION in sync with plugin.json on release.
APP_NAME = "Moddy"
APP_VERSION = "0.2.0-alpha.1"

PAGE_SIZE = 25  # mirrors the Workshop browse page size

# Per-mod v1 metadata cache on disk. Nexus enforces daily + hourly rate-limit caps, so we
# cache mod.json well beyond fetch.py's 5-min in-memory cache (which only covers bursts).
_MOD_CACHE_TTL_SECONDS = 6 * 3600


class PremiumRequired(Exception):
    """The download_link endpoint returned 403 — the user's key isn't Premium."""


class MissingApiKey(Exception):
    """No Nexus API key has been configured in settings."""


def _headers() -> dict:
    key = settings.nexus_api_key()
    if not key:
        raise MissingApiKey()
    return {
        "apikey": key,
        "Application-Name": APP_NAME,
        "Application-Version": APP_VERSION,
    }


# ── Search (v2 GraphQL) ───────────────────────────────────────────────────────

_NODE_FIELDS = "nodes { modId name summary uploader { name } pictureUrl version updatedAt } totalCount"


def _search_query(domain: str, term: str, count: int, offset: int) -> str:
    """Build the GraphQL mods-search query inline. Values are JSON-encoded so terms with
    quotes/backslashes can't break or inject into the query. The filter is built inline
    (not via variables) because that exact shape was verified live; `nameStemmed`/WILDCARD
    is the tokenized full-text search the website uses, omitted entirely for empty terms."""
    parts = [f"gameDomainName:{{value:{json.dumps(domain)},op:EQUALS}}"]
    if term:
        parts.append(f"nameStemmed:{{value:{json.dumps(term)},op:WILDCARD}}")
    filter_str = ",".join(parts)
    return (
        f"{{ mods(filter:{{{filter_str}}}, count:{count}, offset:{offset}) "
        f"{{ {_NODE_FIELDS} }} }}"
    )


def _node_to_item(domain: str, node: dict) -> catalog.CatalogItem:
    mod_id = node.get("modId")
    return catalog.make_item(
        name=node.get("name", "") or "",
        full_name=f"nexus.{domain}.{mod_id}",
        owner=(node.get("uploader") or {}).get("name", "") or "",
        package_url=f"https://www.nexusmods.com/{domain}/mods/{mod_id}",
        date_updated=node.get("updatedAt", "") or "",
        version_number=str(node.get("version", "") or ""),
        description=node.get("summary", "") or "",
        icon=node.get("pictureUrl", "") or "",
    )


def search(domain: str, query: str = "", page: int = 1) -> list[catalog.CatalogItem]:
    """A page of Nexus mods for a game domain, optionally filtered by a search term.
    Returns [] on error or when no API key is set. Server-side paginated (PAGE_SIZE)."""
    query = (query or "").strip()
    offset = max(0, (page - 1) * PAGE_SIZE)
    try:
        headers = _headers()
    except MissingApiKey:
        decky.logger.warning("Nexus search skipped: no API key configured")
        return []

    gql = _search_query(domain, query, PAGE_SIZE, offset)
    data = fetch.post_json(GRAPHQL_URL, {"query": gql}, headers=headers)
    if not isinstance(data, dict):
        return []
    if data.get("errors"):
        decky.logger.error(f"Nexus GraphQL errors: {data['errors']}")
        return []
    nodes = (((data.get("data") or {}).get("mods") or {}).get("nodes")) or []
    return [_node_to_item(domain, n) for n in nodes]


# ── Requirements / dependencies (v2 GraphQL) ──────────────────────────────────
# A mod's required mods live under modRequirements.nexusRequirements.nodes (each a
# ModRequirement with modId/modName/externalRequirement/url). v1 REST has no equivalent.

_URL_DOMAIN_RE = re.compile(r"nexusmods\.com/([^/]+)/mods/(\d+)")


def _parse_mod_url(url: str) -> tuple[str, str]:
    """Pull (domain_slug, mod_id) out of a Nexus mod URL, or ("","") if it isn't one.
    The ModRequirement carries a numeric gameId (not the slug) and sometimes a modId of "0"
    for manually-added requirements, so the url is the reliable source for both."""
    m = _URL_DOMAIN_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else ("", "")


_GAME_ID_CACHE: dict[str, str] = {}


def game_id(domain: str) -> str | None:
    """The numeric Nexus game id for a domain slug (e.g. slimerancher2 → 4823), via v1.
    Cached for the process. The GraphQL `mods` filter requires this (not the slug) when
    filtering by modId."""
    if domain in _GAME_ID_CACHE:
        return _GAME_ID_CACHE[domain]
    try:
        headers = _headers()
    except MissingApiKey:
        return None
    data = fetch.fetch_json(f"{API_V1}/games/{domain}.json", headers=headers)
    if isinstance(data, dict) and data.get("id") is not None:
        gid = str(data["id"])
        _GAME_ID_CACHE[domain] = gid
        return gid
    return None


def _requirements_query(game_id_value: str, mod_id: str) -> str:
    return (
        f"{{ mods(filter:{{gameId:{{value:{json.dumps(str(game_id_value))},op:EQUALS}}, "
        f"modId:{{value:{json.dumps(str(mod_id))},op:EQUALS}}}}, count:1) "
        f"{{ nodes {{ modId modRequirements {{ nexusRequirements {{ nodes "
        f"{{ modId modName externalRequirement url }} }} }} }} }} }}"
    )


def get_requirements(domain: str, mod_id: str) -> list[dict]:
    """The Nexus mods this mod declares as requirements. Each entry: {mod_id, name, domain,
    external}. `domain` is parsed from the requirement's url (falls back to the parent's
    domain). Returns [] on error / no API key / no declared requirements."""
    try:
        headers = _headers()
    except MissingApiKey:
        return []
    gid = game_id(domain)
    if not gid:
        decky.logger.error(f"Could not resolve Nexus game id for {domain}; skipping requirements")
        return []
    data = fetch.post_json(GRAPHQL_URL, {"query": _requirements_query(gid, mod_id)}, headers=headers)
    if not isinstance(data, dict):
        return []
    if data.get("errors"):
        decky.logger.error(f"Nexus requirements errors: {data['errors']}")
        return []
    nodes = (((data.get("data") or {}).get("mods") or {}).get("nodes")) or []
    if not nodes:
        return []
    reqs = (((nodes[0].get("modRequirements") or {}).get("nexusRequirements") or {}).get("nodes")) or []
    out: list[dict] = []
    for r in reqs:
        url_domain, url_modid = _parse_mod_url(r.get("url", ""))
        rid = r.get("modId")
        rid = str(rid) if rid is not None else ""
        # Manually-added requirements often come back with modId "0" but a real mod url —
        # recover the id from the url. A requirement with no resolvable Nexus mod id (purely
        # off-site/external) can't be installed, so skip it.
        if rid in ("", "0"):
            rid = url_modid
        if not rid or rid == "0":
            decky.logger.info(f"Skipping unresolvable requirement of {domain}/{mod_id} (url={r.get('url','')!r})")
            continue
        out.append({
            "mod_id": rid,
            "name": r.get("modName", "") or "",
            "domain": url_domain or domain,
            "external": bool(r.get("externalRequirement", False)),
        })
    return out


# ── Per-mod details + files (v1 REST) ─────────────────────────────────────────

def _mod_cache_path(domain: str, mod_id: str) -> str:
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"nexus-mod-{domain}-{mod_id}.json")


def get_mod(domain: str, mod_id: str, force: bool = False) -> dict | None:
    """v1 mod metadata (name, summary, version, author, picture_url, …) for one mod,
    disk-cached for 6h to respect Nexus rate limits. Returns None on error."""
    cache_path = _mod_cache_path(domain, mod_id)
    now = time.time()
    if not force:
        try:
            if os.path.isfile(cache_path):
                with open(cache_path, "r") as f:
                    cached = json.load(f)
                if now - cached.get("fetched_at", 0) < _MOD_CACHE_TTL_SECONDS:
                    return cached.get("mod")
        except Exception as e:
            decky.logger.warning(f"Nexus mod cache read failed for {domain}/{mod_id}: {e}")

    try:
        headers = _headers()
    except MissingApiKey:
        return None
    data = fetch.fetch_json(f"{API_V1}/games/{domain}/mods/{mod_id}.json", headers=headers)
    if not isinstance(data, dict):
        # Fall back to a stale cache if the fetch failed
        try:
            if os.path.isfile(cache_path):
                with open(cache_path, "r") as f:
                    return json.load(f).get("mod")
        except Exception:
            pass
        return None

    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": now, "mod": data}, f)
        os.replace(tmp, cache_path)
    except Exception as e:
        decky.logger.warning(f"Nexus mod cache write failed for {domain}/{mod_id}: {e}")
    return data


def get_files(domain: str, mod_id: str) -> list[dict]:
    """The file list for a mod (v1). Each entry has file_id, category_name, file_name, …."""
    try:
        headers = _headers()
    except MissingApiKey:
        return []
    data = fetch.fetch_json(f"{API_V1}/games/{domain}/mods/{mod_id}/files.json", headers=headers)
    if not isinstance(data, dict):
        return []
    return list(data.get("files") or [])


def primary_file_id(domain: str, mod_id: str) -> str | None:
    """The id of the mod's primary downloadable file: the one Nexus marks MAIN, else the
    most recently uploaded. Returns None if the mod has no files."""
    files = get_files(domain, mod_id)
    if not files:
        return None
    main = [f for f in files if (f.get("category_name") or "").upper() == "MAIN"]
    chosen = main or files
    # Highest file_id == most recent upload, a stable tiebreaker.
    best = max(chosen, key=lambda f: f.get("file_id", 0))
    fid = best.get("file_id")
    return str(fid) if fid is not None else None


def get_download_url(domain: str, mod_id: str, file_id: str) -> str | None:
    """Resolve a direct CDN download URL for a file (v1 download_link).
    Raises PremiumRequired on HTTP 403 (free account). Returns None on other errors."""
    url = f"{API_V1}/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json"
    try:
        headers = _headers()
    except MissingApiKey:
        return None
    try:
        req = fetch.request(url, headers=headers)
        with urllib.request.urlopen(req, context=fetch.ssl_context(), timeout=15) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise PremiumRequired()
        decky.logger.error(f"Nexus download_link failed ({e.code}) for {domain}/{mod_id}/{file_id}")
        return None
    except Exception as e:
        decky.logger.error(f"Nexus download_link failed for {domain}/{mod_id}/{file_id}: {e}")
        return None
    # Response is a list of {URI, name, short_name}; the first is the recommended CDN.
    if isinstance(data, list) and data:
        uri = data[0].get("URI") or ""
        # Nexus CDN URLs derived from the file name can contain literal spaces (e.g.
        # "Classic Flashlight Version 1.0.0-….zip"); urllib rejects unencoded spaces.
        # Only spaces are unsafe here — the md5/expires query params are already encoded.
        return uri.replace(" ", "%20") or None
    return None


def get_latest(domain: str, mod_id: str) -> dict | None:
    """Latest version string for a Nexus mod (for update checks). Compares the v1 mod
    `version` field against the installed version."""
    mod = get_mod(domain, mod_id)
    if not mod:
        return None
    return {"version": str(mod.get("version", "") or "")}


# ── id helpers ────────────────────────────────────────────────────────────────

def parse_id(full_name: str) -> tuple[str, str] | None:
    """Parse a `nexus.<domain>.<mod_id>` install id into (domain, mod_id).
    domain slugs never contain dots, so a simple 3-way split is safe."""
    parts = (full_name or "").split(".")
    if len(parts) != 3 or parts[0] != "nexus" or not parts[2]:
        return None
    return parts[1], parts[2]
