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
base64, json, time, urllib) — NO `xml`/other stripped imports, which crash the whole
backend at load (see reference_decky_no_xml_stdlib memory).

═══════════════════════════════════════════════════════════════════════════════════
CONFIG BELOW IS PENDING NEXUS'S REPLY. The registration email delivered client_id +
redirect URI as an unrendered image; Phase 0 is getting them re-sent as plain text.
Until CLIENT_ID is filled in, is_configured() is False and the app behaves as
"not signed in" (Browse/collections show the sign-in empty-state; nothing crashes).
═══════════════════════════════════════════════════════════════════════════════════
"""

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

# ── OAuth client config (see PENDING banner above) ────────────────────────────
CLIENT_ID = ""  # TODO(nexus): fill from registration email (plain-text resend)
# The redirect URI Nexus registered ("your other example" — loopback was rejected).
# Whatever it is, it must match the authorize/token requests byte-for-byte.
REDIRECT_URI = ""  # TODO(nexus): fill from registration email
# Space-delimited. Expect at least "openid profile email"; confirm the download scope.
SCOPES = "openid profile email"  # TODO(nexus): confirm granted scopes

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
