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


def request(url: str) -> urllib.request.Request:
    """Build a urllib Request carrying our User-Agent."""
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def fetch_json(url: str) -> dict | list | None:
    """GET and JSON-decode a URL, with a short in-memory cache keyed by URL.
    Returns None on any network/parse error (logged)."""
    now = time.time()
    cached = _cache.get(url)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        with urllib.request.urlopen(request(url), context=ssl_context(), timeout=10) as response:
            data = json.loads(response.read().decode())
            _cache[url] = (now, data)
            return data
    except Exception as e:
        decky.logger.error(f"Failed to fetch {url}: {e}")
        return None
