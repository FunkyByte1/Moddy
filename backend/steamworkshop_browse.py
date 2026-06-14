"""
Steam Workshop browse catalog — keyless.

There is no Steam Web API to search/browse the Workshop without an API key, and
SteamClient exposes only the user's *subscribed* items. So the catalog is built
in two stable, keyless steps:

  1. Scrape the public Workshop browse page only for the ORDERED list of
     published file ids (the `filedetails/?id=...` links are stable URLs — the
     page's CSS classes are obfuscated and per-build, so nothing else is parsed).
  2. Resolve metadata (title/preview/description/tags/subs) for those ids via the
     keyless ISteamRemoteStorage/GetPublishedFileDetails endpoint.

Search, sort, and pagination are driven by the browse page's query params. Results
are cached in-memory per (appid, search, sort, page) for a short TTL.
"""
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request

import decky

_BROWSE_URL = "https://steamcommunity.com/workshop/browse/"
_DETAILS_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
_UA = "Mozilla/5.0 (X11; Linux x86_64) Moddy"
# SteamOS' default SSL context can't always find the cert store; point at the system
# CA bundle explicitly, matching the other backend fetchers (github.py / bmi.py).
_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
_CACHE_TTL = 600  # 10 minutes
_cache: dict[tuple, tuple[float, list]] = {}


def _ssl_ctx() -> ssl.SSLContext:
    if os.path.isfile(_CA_BUNDLE):
        return ssl.create_default_context(cafile=_CA_BUNDLE)
    return ssl.create_default_context()

# Map our sort keys to the browse page's params.
_SORTS = {
    "trend": "trend",
    "recent": "mostrecent",
    "subscribed": "totaluniquesubscribers",
    "popular": "trend",
}


def _fetch(url: str, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _browse_ids(appid: int, search: str, sort: str, page: int) -> list[str]:
    """Ordered, de-duplicated published file ids from one browse page."""
    q = {"appid": appid, "section": "readytouseitems", "p": max(1, page)}
    if search:
        q["searchtext"] = search
        q["browsesort"] = "textsearch"
    else:
        q["browsesort"] = _SORTS.get(sort, "trend")
    html = _fetch(_BROWSE_URL + "?" + urllib.parse.urlencode(q))
    seen: set[str] = set()
    ids: list[str] = []
    for fid in re.findall(r"filedetails/\?id=(\d+)", html):
        if fid not in seen:
            seen.add(fid)
            ids.append(fid)
    return ids


def _details(ids: list[str]) -> dict[str, dict]:
    """Keyless metadata for a batch of ids, keyed by published file id."""
    if not ids:
        return {}
    data = [("itemcount", str(len(ids)))]
    data += [(f"publishedfileids[{i}]", fid) for i, fid in enumerate(ids)]
    body = urllib.parse.urlencode(data).encode()
    raw = _fetch(_DETAILS_URL, data=body)
    out: dict[str, dict] = {}
    for f in json.loads(raw).get("response", {}).get("publishedfiledetails", []):
        fid = str(f.get("publishedfileid", ""))
        if fid and int(f.get("result", 0)) == 1 and not f.get("banned"):
            out[fid] = f
    return out


def _to_item(f: dict) -> dict:
    fid = str(f.get("publishedfileid", ""))
    return {
        "id": fid,
        "name": f.get("title") or f"Workshop item {fid}",
        "description": f.get("description") or "",
        "preview_url": f.get("preview_url") or "",
        "subscriptions": int(f.get("subscriptions") or 0),
        "file_size": int(f.get("file_size") or 0),
        "time_updated": int(f.get("time_updated") or 0),
        "tags": [t.get("tag") for t in f.get("tags", []) if t.get("tag")],
        "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={fid}",
    }


_req_cache: dict[str, tuple[float, list]] = {}


def get_required_items(fileid: str) -> list[str]:
    """The author-declared 'required items' (dependency file ids) for a Workshop item,
    scraped from its page's Required Items block. Steam's required-items relationship
    isn't in the keyless API, and SteamClient.SubscribeWorkshopItem doesn't cascade
    them, so Moddy resolves and subscribes them itself. Cached; [] on error."""
    fileid = str(fileid)
    hit = _req_cache.get(fileid)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    try:
        url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={fileid}"
        html = _fetch(url)
        m = re.search(r'id="RequiredItems".*?(?=workshopItemDescription|rightDetailsBlock|$)', html, re.S)
        block = m.group(0) if m else ""
        seen: set[str] = set()
        req: list[str] = []
        for x in re.findall(r"filedetails/\?id=(\d+)", block):
            if x not in seen and x != fileid:
                seen.add(x)
                req.append(x)
        _req_cache[fileid] = (time.time(), req)
        return req
    except Exception as e:
        decky.logger.error(f"Required-items fetch failed (fileid={fileid}): {e}")
        return []


def get_workshop_catalog(appid: int, search: str = "", sort: str = "trend", page: int = 1) -> list[dict]:
    """A page (~30 items) of the Workshop catalog for `appid`, in browse order.
    Returns [] on any fetch/parse error. Cached per query for a short TTL."""
    key = (int(appid), (search or "").strip().lower(), sort, int(page))
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    try:
        ids = _browse_ids(appid, search, sort, page)
        meta = _details(ids)
        items = [_to_item(meta[fid]) for fid in ids if fid in meta]
        _cache[key] = (time.time(), items)
        return items
    except Exception as e:
        decky.logger.error(f"Workshop catalog fetch failed (appid={appid}, search={search!r}, p={page}): {e}")
        return []
