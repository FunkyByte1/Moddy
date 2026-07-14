"""Nexus Mods OAuth2 + PKCE.

Replaces the personal `apikey` header (see the note atop nexus.py) with a per-user
OAuth token, as required by Nexus for distributed apps. Public-app flow: Authorization
Code + PKCE (no client secret). The access token is a JWT; both the v1 REST and v2
GraphQL APIs accept it as `Authorization: Bearer <token>`, so nexus.py only swaps the
header — every existing call site is untouched.

Token bundle {access_token, refresh_token, expires_at} lives in app_settings (same
plaintext, 0o600, single-user-device trust model the key used). get_access_token()
transparently refreshes an expired token before returning it.

Stdlib only, and only the modules Decky's stripped sandbox ships (secrets, hashlib,
base64, json, time, urllib, asyncio) — NO `xml`/other stripped imports, which crash the
whole backend at load (see reference_decky_no_xml_stdlib memory). The loopback callback
listener uses asyncio (the plugin's own loop), NOT http.server, for the same reason.

Login handoff = a loopback redirect (RFC 8252): Moddy opens the authorize URL in the
browser and runs a one-shot local HTTP listener on 127.0.0.1:53682 to catch Nexus's
redirect-with-code — no copy-paste. See the "Loopback callback listener" section below.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import urllib.request

import decky

import fetch
import app_settings as settings

# ── OAuth client config (confirmed by Nexus 2026-07-12) ───────────────────────
# Public client (Authorization Code + PKCE, no secret). Nexus also sent a client
# secret "just in case" — deliberately NOT used/stored: the client ships on-device and
# the repo is public, so a secret can't be kept confidential here.
CLIENT_ID = "moddy"
# Loopback redirect Nexus registered; must match the authorize/token requests
# byte-for-byte (host, port, and /callback path).
REDIRECT_URI = "http://127.0.0.1:53682/callback"
# Space-delimited, exactly the granted scopes (Nexus: public, openid, profile).
SCOPES = "public openid profile"

AUTHORIZE_URL = "https://users.nexusmods.com/oauth/authorize"
TOKEN_URL = "https://users.nexusmods.com/oauth/token"

# Refresh this many seconds before the token actually expires, to avoid racing a
# request against expiry.
_EXPIRY_SKEW_SECONDS = 60


class NotSignedIn(Exception):
    """No usable Nexus OAuth token (never signed in, or refresh failed)."""


def is_configured() -> bool:
    """Whether the OAuth client has been provisioned yet. False until CLIENT_ID and
    REDIRECT_URI are filled from Nexus's registration reply — callers treat an
    unconfigured client as simply 'not signed in' rather than erroring."""
    return bool(CLIENT_ID and REDIRECT_URI)


# ── PKCE ──────────────────────────────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    """URL-safe base64 without padding, per RFC 7636."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for a fresh PKCE (S256) exchange.
    The verifier is a high-entropy 43–128 char string; the challenge is its
    URL-safe-base64 SHA-256."""
    verifier = _b64url(secrets.token_bytes(64))  # ~86 chars, within RFC bounds
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ── Transient login state ─────────────────────────────────────────────────────
# The verifier + state generated at start_login must survive until the code comes
# back (and a backend reload in between), so they live in settings, not memory.
_PENDING = "nexus_oauth_pending"


def build_authorize_url() -> tuple[str, str]:
    """Begin a login: generate PKCE + state, persist the verifier, and return
    (authorize_url, state). Caller opens authorize_url in a browser."""
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    settings.set_setting(_PENDING, {"verifier": verifier, "state": state})
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}", state


# ── Token endpoint ────────────────────────────────────────────────────────────

def _post_form(fields: dict) -> dict | None:
    """POST application/x-www-form-urlencoded to the token endpoint (OAuth2 requires
    form encoding, not JSON — so fetch.post_json can't be used). Returns the decoded
    JSON body, or None on any network/HTTP error (logged)."""
    body = urllib.parse.urlencode(fields).encode("ascii")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        req = fetch.request(TOKEN_URL, headers=headers, data=body, method="POST")
        with urllib.request.urlopen(req, context=fetch.ssl_context(), timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        decky.logger.error(f"Nexus OAuth token request failed: {e}")
        return None


def _store_token(payload: dict) -> bool:
    """Persist a token response, computing an absolute expiry from expires_in."""
    access = payload.get("access_token")
    if not access:
        return False
    expires_in = payload.get("expires_in", 0)
    bundle = {
        "access_token": access,
        # Nexus returns a rotating refresh token; fall back to the prior one if a
        # refresh response omits it.
        "refresh_token": payload.get("refresh_token", ""),
        "expires_at": time.time() + expires_in,
    }
    if not bundle["refresh_token"]:
        prev = settings.nexus_oauth_token() or {}
        bundle["refresh_token"] = prev.get("refresh_token", "")
    return settings.set_setting(settings.NEXUS_OAUTH, bundle)


def exchange_code(code: str, state: str) -> bool:
    """Exchange an authorization code for tokens, validating the returned state
    against the one we stashed. Returns True on success (token stored)."""
    pending = settings.get_setting(_PENDING) or {}
    if not pending.get("verifier") or pending.get("state") != state:
        decky.logger.error("Nexus OAuth: state mismatch or no pending login")
        return False
    payload = _post_form({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pending["verifier"],
    })
    settings.set_setting(_PENDING, {})  # one-shot: clear regardless of outcome
    if not payload:
        return False
    return _store_token(payload)


def _refresh(refresh_token: str) -> str | None:
    """Trade a refresh token for a fresh access token. Returns the new access token,
    or None (and clears the stored bundle) if the refresh is rejected."""
    payload = _post_form({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    })
    if payload and _store_token(payload):
        return payload["access_token"]
    # Refresh failed (revoked / expired) — force a fresh sign-in.
    sign_out()
    return None


def get_access_token() -> str:
    """Return a currently-valid access token, refreshing if it's within the skew
    window of expiry. Raises NotSignedIn if there's no token or the refresh fails."""
    if not is_configured():
        raise NotSignedIn()
    bundle = settings.nexus_oauth_token()
    if not bundle or not bundle.get("access_token"):
        raise NotSignedIn()
    if time.time() >= bundle.get("expires_at", 0) - _EXPIRY_SKEW_SECONDS:
        token = _refresh(bundle.get("refresh_token", ""))
        if not token:
            raise NotSignedIn()
        return token
    return bundle["access_token"]


# ── Account status / sign-out ─────────────────────────────────────────────────

def is_signed_in() -> bool:
    bundle = settings.nexus_oauth_token()
    return bool(bundle and bundle.get("access_token"))


def username() -> str | None:
    """Best-effort display name from the access-token JWT claims (no signature
    check — the token came from the token endpoint over TLS and is only used for
    display). Returns None if unavailable."""
    bundle = settings.nexus_oauth_token()
    if not bundle or not bundle.get("access_token"):
        return None
    try:
        claims_seg = bundle["access_token"].split(".")[1]
        claims_seg += "=" * (-len(claims_seg) % 4)  # restore base64 padding
        claims = json.loads(base64.urlsafe_b64decode(claims_seg))
        return claims.get("name") or claims.get("username") or claims.get("preferred_username")
    except Exception:
        return None


def sign_out() -> None:
    settings.set_setting(settings.NEXUS_OAUTH, {})


# ── Loopback callback listener (RFC 8252) ─────────────────────────────────────
# After the user approves in the browser, Nexus redirects to
# http://127.0.0.1:53682/callback?code=...&state=... . We run a one-shot local HTTP
# listener to catch that redirect so login needs no copy-paste. asyncio (the plugin's
# own event loop), not http.server — same stripped-stdlib caution as the module header.
_LOOPBACK_HOST = "127.0.0.1"
_LOOPBACK_PORT = 53682                    # the port baked into REDIRECT_URI
_LOGIN_TIMEOUT_SECONDS = 300             # give the user 5 min to sign in, then give up

_login_server: "asyncio.AbstractServer | None" = None
_login_result: "asyncio.Future | None" = None

_PAGE_OK = (
    "<!doctype html><meta charset=utf-8><title>Moddy</title>"
    "<div style='font-family:sans-serif;text-align:center;margin-top:20vh;color:#1a9fff'>"
    "<h2>Signed in to Nexus Mods</h2>"
    "<p style='color:#333'>You can close this and return to Moddy.</p></div>"
)
_PAGE_ERR = (
    "<!doctype html><meta charset=utf-8><title>Moddy</title>"
    "<div style='font-family:sans-serif;text-align:center;margin-top:20vh;color:#d33'>"
    "<h2>Sign-in didn't complete</h2>"
    "<p style='color:#333'>Return to Moddy and try again.</p></div>"
)


def _write_http(writer: "asyncio.StreamWriter", body: str, status: str = "200 OK") -> None:
    raw = body.encode("utf-8")
    head = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(raw)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("latin-1")
    writer.write(head + raw)


async def _handle_callback(reader: "asyncio.StreamReader", writer: "asyncio.StreamWriter") -> None:
    """Handle one connection to the loopback listener. Resolves _login_result only for the
    real /callback (carrying code or error); other hits (favicon probes) get a 404 and the
    listener keeps waiting."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=10)
        # "GET /callback?code=...&state=... HTTP/1.1"
        target = request_line.decode("latin-1", "replace").split(" ")
        parsed = urllib.parse.urlparse(target[1] if len(target) >= 2 else "")
        query = urllib.parse.parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        error = (query.get("error") or [""])[0]
        if parsed.path.rstrip("/") == "/callback" and (code or error):
            _write_http(writer, _PAGE_OK if code and not error else _PAGE_ERR)
            if _login_result is not None and not _login_result.done():
                _login_result.set_result({"code": code, "state": state, "error": error})
        else:
            _write_http(writer, _PAGE_ERR, status="404 Not Found")
    except Exception as e:  # noqa: BLE001 — a bad probe must not kill the listener
        decky.logger.warning(f"Nexus OAuth callback read failed: {e}")
    finally:
        try:
            await writer.drain()
            writer.close()
        except Exception:
            pass


async def cancel_login() -> None:
    """Tear down any in-flight login: close the listener and drop the pending result."""
    global _login_server, _login_result
    if _login_server is not None:
        _login_server.close()
        try:
            await _login_server.wait_closed()
        except Exception:
            pass
        _login_server = None
    if _login_result is not None and not _login_result.done():
        _login_result.cancel()
    _login_result = None


async def start_login() -> dict:
    """Begin a loopback login: bind the local listener and return the authorize URL for
    the caller to open in a browser. {ok, authorize_url} on success, else {ok:False, reason}."""
    global _login_server, _login_result
    if not is_configured():
        return {"ok": False, "reason": "not_configured"}
    await cancel_login()  # clear any stale in-flight login first
    loop = asyncio.get_running_loop()
    _login_result = loop.create_future()
    try:
        _login_server = await asyncio.start_server(_handle_callback, _LOOPBACK_HOST, _LOOPBACK_PORT)
    except OSError as e:
        decky.logger.error(f"Nexus OAuth: cannot bind {_LOOPBACK_HOST}:{_LOOPBACK_PORT}: {e}")
        _login_result = None
        return {"ok": False, "reason": "port_in_use"}
    url, _state = build_authorize_url()
    return {"ok": True, "authorize_url": url}


async def wait_login() -> dict:
    """Await the browser redirect (up to the login timeout), then exchange the code.
    {ok:True, username} on success; {ok:False, reason} on timeout / user-deny / failure.
    Always tears the listener down before returning."""
    if _login_result is None:
        return {"ok": False, "reason": "no_login_in_progress"}
    try:
        cb = await asyncio.wait_for(_login_result, timeout=_LOGIN_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        await cancel_login()
        return {"ok": False, "reason": "timeout"}
    await cancel_login()
    if cb.get("error") or not cb.get("code"):
        return {"ok": False, "reason": cb.get("error") or "no_code"}
    # exchange_code makes a blocking token POST — run it off the event loop.
    ok = await asyncio.get_running_loop().run_in_executor(
        None, exchange_code, cb["code"], cb["state"])
    return {"ok": True, "username": username()} if ok else {"ok": False, "reason": "exchange_failed"}
