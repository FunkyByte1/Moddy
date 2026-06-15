import json
import os
import ssl
import time
import urllib.request
import decky

CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
USER_AGENT = "Moddy/0.1.0 (+https://github.com/FunkyByte1/Moddy)"

_CACHE_TTL_SECONDS = 300  # 5 min — covers double-clicks and rapid "Check for Updates" without hiding fresh releases for long
_cache: dict[str, tuple[float, dict | list]] = {}


def ssl_context() -> ssl.SSLContext:
    """SSL context preferring the system CA bundle when present (Steam Deck's
    Python ships without one wired up, so we point at it explicitly)."""
    if os.path.isfile(CA_BUNDLE):
        return ssl.create_default_context(cafile=CA_BUNDLE)
    return ssl.create_default_context()


def request(
    url: str,
    headers: dict | None = None,
    data: bytes | None = None,
    method: str | None = None,
) -> urllib.request.Request:
    """Build a urllib Request carrying our User-Agent, plus any extra headers (e.g. a
    Nexus `apikey`). Pass `data`/`method` for non-GET calls (GraphQL POST)."""
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, headers=merged, data=data, method=method)


def fetch_json(url: str, headers: dict | None = None) -> dict | list | None:
    """GET and JSON-decode a URL, with a short in-memory cache keyed by URL.
    Returns None on any network/parse error (logged). `headers` (e.g. an apikey) are
    NOT part of the cache key — callers that vary auth per URL must cache themselves."""
    now = time.time()
    cached = _cache.get(url)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        with urllib.request.urlopen(request(url, headers=headers), context=ssl_context(), timeout=10) as response:
            data = json.loads(response.read().decode())
            _cache[url] = (now, data)
            return data
    except Exception as e:
        decky.logger.error(f"Failed to fetch {url}: {e}")
        return None


def post_json(url: str, payload: dict, headers: dict | None = None) -> dict | list | None:
    """POST a JSON body and JSON-decode the response. Uncached (request bodies vary).
    Returns None on any network/parse error (logged)."""
    body = json.dumps(payload).encode()
    merged = {"Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    try:
        req = request(url, headers=merged, data=body, method="POST")
        with urllib.request.urlopen(req, context=ssl_context(), timeout=15) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        decky.logger.error(f"Failed to POST {url}: {e}")
        return None
