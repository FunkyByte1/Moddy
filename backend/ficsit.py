"""ficsit.app (Satisfactory Mod Repository) provider.

Satisfactory mods live on ficsit.app (the SMR), reached through ONE anonymous GraphQL endpoint
(api.ficsit.app/v2/query) — no API key, unlike Nexus. Browse/search is the `getMods` query
(server-side text search + paging + ordering); per-mod detail + the latest version's dependencies
come from `getModByReference`. A version's download is an anonymous redirect at
`v1/version/<id>/<target>/download` (302 → CDN; utils.download follows it).

Targets: a Satisfactory CLIENT mod ships a `Windows` build — there is NO native "Linux" client
target (only `LinuxServer`). Satisfactory on the Deck runs the Windows build under Proton (the game
is registry-flagged `requires_proton`), so we always install the `Windows` target. Its DLLs/paks are
Win64, which is exactly why the game must run under Proton for them to load.

Catalog items use the shared `catalog.CatalogItem` shape so Browse renders ficsit mods with no new
types. Install ids are `ficsit.<mod_reference>` (mod_reference is the stable, human-readable mod key,
e.g. "RefinedPower"); the version id — which changes every release — is resolved at install time.
"""

import json
import os
import time

import decky

import catalog
import fetch

GRAPHQL_URL = "https://api.ficsit.app/v2/query"
API_V1 = "https://api.ficsit.app/v1"

PAGE_SIZE = 25            # mirrors the Nexus/Workshop browse page size
TARGET = "Windows"       # the client build; runs under Proton on the Deck (see module docstring)

# Per-mod detail cache on disk (deps + latest version), beyond fetch.py's 5-min in-memory cache.
_MOD_CACHE_TTL_SECONDS = 6 * 3600

# Browse sort key -> the ficsit `getMods` order_by enum (each verified live). Unknown -> default.
_SORTS = {
    "popularity": "popularity",
    "downloads": "downloads",
    "updated": "last_version_date",
    "name": "name",
}
DEFAULT_SORT = "popularity"


# ── Search / browse (getMods) ─────────────────────────────────────────────────

_MOD_FIELDS = (
    "id name mod_reference short_description logo downloads last_version_date "
    "authors { user { username } } versions(filter:{limit:1}) { version }"
)


def _search_query(term: str, count: int, offset: int, sort: str) -> str:
    """Build the getMods query inline. The term is JSON-encoded so quotes/backslashes can't break
    or inject into the query. A search term switches ordering to `search` (relevance ranking, which
    is what a text search requires); with no term we order by the chosen sort (default popularity).
    The order_by value is taken only from the `_SORTS` whitelist, never from user input."""
    parts = [f"limit:{count}", f"offset:{offset}"]
    term = (term or "").strip()
    if term:
        parts.append(f"search:{json.dumps(term)}")
        parts.append("order_by:search")
    else:
        parts.append(f"order_by:{_SORTS.get(sort, DEFAULT_SORT)}")
    return f"{{ getMods(filter:{{{','.join(parts)}}}) {{ mods {{ {_MOD_FIELDS} }} }} }}"


def _mod_to_item(mod: dict) -> catalog.CatalogItem:
    ref = mod.get("mod_reference", "") or ""
    authors = mod.get("authors") or []
    owner = ((authors[0] or {}).get("user") or {}).get("username", "") if authors else ""
    versions = mod.get("versions") or []
    version_number = str((versions[0] or {}).get("version", "") or "") if versions else ""
    downloads = mod.get("downloads")
    return catalog.make_item(
        name=mod.get("name", "") or "",
        full_name=f"ficsit.{ref}",
        owner=owner or "",
        package_url=f"https://ficsit.app/mod/{mod.get('id', '') or ''}",
        date_updated=mod.get("last_version_date", "") or "",
        rating_score=int(downloads) if isinstance(downloads, (int, float)) else 0,
        version_number=version_number,
        description=mod.get("short_description", "") or "",
        icon=mod.get("logo", "") or "",
    )


def search(query: str = "", page: int = 1, sort: str = DEFAULT_SORT) -> list[catalog.CatalogItem]:
    """A page of ficsit.app mods, optionally filtered by a search term. Server-side paginated
    (PAGE_SIZE). No auth required. Returns [] on error."""
    offset = max(0, (page - 1) * PAGE_SIZE)
    gql = _search_query(query, PAGE_SIZE, offset, sort)
    data = fetch.post_json(GRAPHQL_URL, {"query": gql})
    if not isinstance(data, dict):
        return []
    if data.get("errors"):
        decky.logger.error(f"ficsit GraphQL errors: {data['errors']}")
        return []
    nodes = (((data.get("data") or {}).get("getMods") or {}).get("mods")) or []
    return [_mod_to_item(n) for n in nodes]


# ── Per-mod detail + dependencies (getModByReference) ─────────────────────────

_DETAIL_FIELDS = (
    "id name mod_reference short_description logo "
    "authors { user { username } } "
    "versions(filter:{limit:1}) { id version hash size "
    "dependencies { mod_id condition optional } targets { targetName } }"
)


def _mod_cache_path(mod_reference: str) -> str:
    safe = mod_reference.replace("/", "_").replace("\\", "_")
    return os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, f"ficsit-mod-{safe}.json")


def get_mod(mod_reference: str, force: bool = False) -> dict | None:
    """Full mod detail (incl. the latest version's id/hash/deps/targets) for one mod by its
    mod_reference, disk-cached for 6h. Returns None on error / unknown mod (falling back to a stale
    cache if the network fetch fails)."""
    cache_path = _mod_cache_path(mod_reference)
    now = time.time()
    if not force:
        try:
            if os.path.isfile(cache_path):
                with open(cache_path) as f:
                    cached = json.load(f)
                if now - cached.get("fetched_at", 0) < _MOD_CACHE_TTL_SECONDS:
                    return cached.get("mod")
        except Exception as e:
            decky.logger.warning(f"ficsit mod cache read failed for {mod_reference}: {e}")

    gql = f"{{ getModByReference(modReference:{json.dumps(mod_reference)}) {{ {_DETAIL_FIELDS} }} }}"
    data = fetch.post_json(GRAPHQL_URL, {"query": gql})
    # A real fetch failure (network/HTTP/parse error) returns non-dict; a clean GraphQL "mod not
    # found" returns a dict with getModByReference == null. Only the former should fall back to a
    # stale cache — a definitively removed mod must resolve to None, not resurrect past its TTL.
    fetch_ok = isinstance(data, dict)
    mod = None
    if fetch_ok:
        if data.get("errors"):
            decky.logger.error(f"ficsit getModByReference errors for {mod_reference}: {data['errors']}")
        mod = (data.get("data") or {}).get("getModByReference")
    if mod is None:
        if not fetch_ok:
            try:
                if os.path.isfile(cache_path):
                    with open(cache_path) as f:
                        return json.load(f).get("mod")
            except Exception:
                pass
        return None

    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": now, "mod": mod}, f)
        os.replace(tmp, cache_path)
    except Exception as e:
        decky.logger.warning(f"ficsit mod cache write failed for {mod_reference}: {e}")
    return mod


def _latest_version(mod: dict) -> dict | None:
    """The mod's latest version record (raw), or None if it has no versions."""
    versions = (mod or {}).get("versions") or []
    return versions[0] if versions else None


def windows_version(mod: dict) -> dict | None:
    """The latest version's INSTALLABLE detail for the Windows (Proton) client, or None when the mod
    has no version or its latest version ships no `Windows` target (a server-only mod can't run on
    the client). Returns {version, version_id, hash, size}."""
    v = _latest_version(mod)
    if not v:
        return None
    targets = {(t or {}).get("targetName") for t in (v.get("targets") or [])}
    if TARGET not in targets:
        return None
    return {
        "version": str(v.get("version", "") or ""),
        "version_id": v.get("id", "") or "",
        "hash": v.get("hash", "") or "",
        "size": v.get("size", 0) or 0,
    }


def dependencies(mod: dict) -> list[dict]:
    """The latest version's declared dependencies, each {mod_id, condition, optional}. mod_id is the
    dependency's mod_reference (e.g. "SML", "ModularUI")."""
    v = _latest_version(mod)
    return list(v.get("dependencies") or []) if v else []


def download_url(version_id: str) -> str:
    """The anonymous download endpoint for a version's Windows build. Resolves (302) to the CDN;
    utils.download follows the redirect transparently."""
    return f"{API_V1}/version/{version_id}/{TARGET}/download"


def get_latest(mod_reference: str) -> dict | None:
    """Latest version string for a mod (for update checks). None on error / no versions."""
    mod = get_mod(mod_reference)
    v = _latest_version(mod) if mod else None
    if not v:
        return None
    return {"version": str(v.get("version", "") or "")}


def parse_id(full_name: str) -> str | None:
    """Parse a `ficsit.<mod_reference>` install id into the mod_reference, or None if malformed.
    mod_references are alphanumeric by ficsit convention, so the prefix split is unambiguous."""
    if not full_name or not full_name.startswith("ficsit."):
        return None
    ref = full_name[len("ficsit."):]
    return ref or None
