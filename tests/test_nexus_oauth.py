"""Tests for the Nexus OAuth2 + PKCE core (nexus_oauth.py).

Pure-logic coverage — no network. _post_form (the token endpoint) is monkeypatched,
and the token bundle round-trips through the real app_settings store (temp dir via the
fake decky in _harness). Pins: PKCE S256 correctness, authorize-URL shape, and the
refresh-on-expiry branch of get_access_token (the part most likely to silently break).
"""
import asyncio
import base64
import hashlib
import json
import time
import unittest

from _harness import decky  # noqa: F401  (ensures fake decky is installed first)
import app_settings as settings
import nexus_oauth


def _reset_settings():
    """Fresh, empty settings store for each test."""
    import tempfile
    decky.DECKY_PLUGIN_SETTINGS_DIR = tempfile.mkdtemp(prefix="moddy-oauth-")
    settings._SETTINGS = None


def _make_jwt(claims: dict) -> str:
    """A fake unsigned JWT: header.payload.sig, payload = base64url(claims)."""
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'none'})}.{seg(claims)}.sig"


class PkceTest(unittest.TestCase):
    def test_challenge_is_s256_of_verifier(self):
        verifier, challenge = nexus_oauth.make_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_verifier_within_rfc_bounds_and_unpadded(self):
        verifier, challenge = nexus_oauth.make_pkce()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertNotIn("=", verifier)
        self.assertNotIn("=", challenge)

    def test_verifiers_are_unique(self):
        self.assertNotEqual(nexus_oauth.make_pkce()[0], nexus_oauth.make_pkce()[0])


class AuthorizeUrlTest(unittest.TestCase):
    def setUp(self):
        _reset_settings()
        self._id, self._uri = nexus_oauth.CLIENT_ID, nexus_oauth.REDIRECT_URI
        nexus_oauth.CLIENT_ID = "test-client"
        nexus_oauth.REDIRECT_URI = "https://moddy.gg/oauth/callback"

    def tearDown(self):
        nexus_oauth.CLIENT_ID, nexus_oauth.REDIRECT_URI = self._id, self._uri

    def test_url_carries_all_pkce_params_and_persists_verifier(self):
        url, state = nexus_oauth.build_authorize_url()
        self.assertTrue(url.startswith(nexus_oauth.AUTHORIZE_URL + "?"))
        for frag in ("response_type=code", "client_id=test-client",
                     "code_challenge_method=S256", "code_challenge=",
                     f"state={state}"):
            self.assertIn(frag, url)
        # redirect_uri is url-encoded in the query string
        self.assertIn("redirect_uri=https%3A%2F%2Fmoddy.gg%2Foauth%2Fcallback", url)
        pending = settings.get_setting(nexus_oauth._PENDING)
        self.assertEqual(pending["state"], state)
        self.assertTrue(pending["verifier"])

    def test_is_configured_tracks_client_fields(self):
        self.assertTrue(nexus_oauth.is_configured())
        nexus_oauth.CLIENT_ID = ""
        self.assertFalse(nexus_oauth.is_configured())


class TokenLifecycleTest(unittest.TestCase):
    def setUp(self):
        _reset_settings()
        self._id, self._uri = nexus_oauth.CLIENT_ID, nexus_oauth.REDIRECT_URI
        nexus_oauth.CLIENT_ID = "test-client"
        nexus_oauth.REDIRECT_URI = "https://moddy.gg/oauth/callback"
        self._real_post = nexus_oauth._post_form

    def tearDown(self):
        nexus_oauth.CLIENT_ID, nexus_oauth.REDIRECT_URI = self._id, self._uri
        nexus_oauth._post_form = self._real_post

    def _stub_post(self, response):
        self._captured = {}
        def fake(fields):
            self._captured = fields
            return response
        nexus_oauth._post_form = fake

    def test_not_signed_in_when_no_token(self):
        with self.assertRaises(nexus_oauth.NotSignedIn):
            nexus_oauth.get_access_token()
        self.assertFalse(nexus_oauth.is_signed_in())

    def test_valid_token_returned_without_refresh(self):
        settings.set_setting(settings.NEXUS_OAUTH, {
            "access_token": "live", "refresh_token": "r", "expires_at": time.time() + 3600,
        })
        self._stub_post(None)  # would fail if a refresh were attempted
        self.assertEqual(nexus_oauth.get_access_token(), "live")

    def test_expired_token_triggers_refresh(self):
        settings.set_setting(settings.NEXUS_OAUTH, {
            "access_token": "old", "refresh_token": "r-old", "expires_at": time.time() - 5,
        })
        self._stub_post({"access_token": "new", "refresh_token": "r-new", "expires_in": 3600})
        self.assertEqual(nexus_oauth.get_access_token(), "new")
        self.assertEqual(self._captured["grant_type"], "refresh_token")
        self.assertEqual(self._captured["refresh_token"], "r-old")
        # New bundle persisted with a future expiry.
        bundle = settings.nexus_oauth_token()
        self.assertEqual(bundle["access_token"], "new")
        self.assertGreater(bundle["expires_at"], time.time())

    def test_refresh_response_without_new_refresh_token_keeps_old(self):
        settings.set_setting(settings.NEXUS_OAUTH, {
            "access_token": "old", "refresh_token": "keep-me", "expires_at": time.time() - 5,
        })
        self._stub_post({"access_token": "new", "expires_in": 3600})  # no refresh_token
        nexus_oauth.get_access_token()
        self.assertEqual(settings.nexus_oauth_token()["refresh_token"], "keep-me")

    def test_failed_refresh_signs_out(self):
        settings.set_setting(settings.NEXUS_OAUTH, {
            "access_token": "old", "refresh_token": "r", "expires_at": time.time() - 5,
        })
        self._stub_post(None)  # token endpoint rejects the refresh
        with self.assertRaises(nexus_oauth.NotSignedIn):
            nexus_oauth.get_access_token()
        self.assertFalse(nexus_oauth.is_signed_in())

    def test_exchange_code_rejects_state_mismatch(self):
        settings.set_setting(nexus_oauth._PENDING, {"verifier": "v", "state": "expected"})
        self._stub_post({"access_token": "x", "refresh_token": "y", "expires_in": 1})
        self.assertFalse(nexus_oauth.exchange_code("code", "WRONG"))
        self.assertFalse(nexus_oauth.is_signed_in())

    def test_exchange_code_stores_token_on_success(self):
        settings.set_setting(nexus_oauth._PENDING, {"verifier": "v", "state": "s"})
        self._stub_post({"access_token": "a", "refresh_token": "b", "expires_in": 3600})
        self.assertTrue(nexus_oauth.exchange_code("thecode", "s"))
        self.assertEqual(self._captured["grant_type"], "authorization_code")
        self.assertEqual(self._captured["code"], "thecode")
        self.assertEqual(self._captured["code_verifier"], "v")
        self.assertTrue(nexus_oauth.is_signed_in())
        # Pending state is cleared one-shot.
        self.assertEqual(settings.get_setting(nexus_oauth._PENDING), {})


class UsernameTest(unittest.TestCase):
    def setUp(self):
        _reset_settings()

    def test_reads_name_claim_from_jwt(self):
        settings.set_setting(settings.NEXUS_OAUTH, {
            "access_token": _make_jwt({"name": "DeckModder"}),
            "refresh_token": "r", "expires_at": time.time() + 3600,
        })
        self.assertEqual(nexus_oauth.username(), "DeckModder")

    def test_none_when_signed_out(self):
        self.assertIsNone(nexus_oauth.username())


class ConfigTest(unittest.TestCase):
    """Guard the Nexus-confirmed client config so an accidental edit is caught."""
    def test_confirmed_client_values(self):
        self.assertEqual(nexus_oauth.CLIENT_ID, "moddy")
        self.assertEqual(nexus_oauth.REDIRECT_URI, "http://127.0.0.1:53682/callback")
        self.assertEqual(nexus_oauth.SCOPES, "public openid profile")
        self.assertTrue(nexus_oauth.is_configured())


class _FakeReader:
    def __init__(self, data: bytes):
        self._data = data

    async def readline(self):
        line, sep, rest = self._data.partition(b"\n")
        self._data = rest
        return line + sep


class _FakeWriter:
    def __init__(self):
        self.buffer = bytearray()
        self.closed = False

    def write(self, data):
        self.buffer.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True


class LoopbackListenerTest(unittest.TestCase):
    """The one-shot loopback listener that catches Nexus's redirect-with-code."""
    def setUp(self):
        _reset_settings()
        nexus_oauth._login_server = None
        nexus_oauth._login_result = None
        self._real_exchange = nexus_oauth.exchange_code
        self._real_username = nexus_oauth.username

    def tearDown(self):
        nexus_oauth.exchange_code = self._real_exchange
        nexus_oauth.username = self._real_username
        nexus_oauth._login_server = None
        nexus_oauth._login_result = None

    def test_callback_resolves_future_and_writes_ok_page(self):
        async def go():
            nexus_oauth._login_result = asyncio.get_running_loop().create_future()
            writer = _FakeWriter()
            await nexus_oauth._handle_callback(
                _FakeReader(b"GET /callback?code=abc&state=xyz HTTP/1.1\r\n"), writer)
            return nexus_oauth._login_result, writer
        fut, writer = asyncio.run(go())
        self.assertTrue(fut.done())
        self.assertEqual(fut.result(), {"code": "abc", "state": "xyz", "error": ""})
        self.assertIn(b"200 OK", bytes(writer.buffer))
        self.assertTrue(writer.closed)

    def test_favicon_probe_does_not_resolve(self):
        async def go():
            nexus_oauth._login_result = asyncio.get_running_loop().create_future()
            writer = _FakeWriter()
            await nexus_oauth._handle_callback(
                _FakeReader(b"GET /favicon.ico HTTP/1.1\r\n"), writer)
            return nexus_oauth._login_result, writer
        fut, writer = asyncio.run(go())
        self.assertFalse(fut.done())          # keeps waiting for the real callback
        self.assertIn(b"404 Not Found", bytes(writer.buffer))

    def test_wait_login_no_login_in_progress(self):
        nexus_oauth._login_result = None
        self.assertEqual(asyncio.run(nexus_oauth.wait_login()),
                         {"ok": False, "reason": "no_login_in_progress"})

    def test_wait_login_success_exchanges_and_returns_username(self):
        nexus_oauth.exchange_code = lambda code, state: True
        nexus_oauth.username = lambda: "DeckModder"
        async def go():
            nexus_oauth._login_result = asyncio.get_running_loop().create_future()
            nexus_oauth._login_result.set_result({"code": "c", "state": "s", "error": ""})
            return await nexus_oauth.wait_login()
        self.assertEqual(asyncio.run(go()), {"ok": True, "username": "DeckModder"})

    def test_wait_login_propagates_provider_error(self):
        async def go():
            nexus_oauth._login_result = asyncio.get_running_loop().create_future()
            nexus_oauth._login_result.set_result({"code": "", "state": "", "error": "access_denied"})
            return await nexus_oauth.wait_login()
        self.assertEqual(asyncio.run(go()), {"ok": False, "reason": "access_denied"})

    def test_wait_login_exchange_failure(self):
        nexus_oauth.exchange_code = lambda code, state: False
        async def go():
            nexus_oauth._login_result = asyncio.get_running_loop().create_future()
            nexus_oauth._login_result.set_result({"code": "c", "state": "s", "error": ""})
            return await nexus_oauth.wait_login()
        self.assertEqual(asyncio.run(go()), {"ok": False, "reason": "exchange_failed"})

    def test_start_login_not_configured(self):
        saved = nexus_oauth.CLIENT_ID
        nexus_oauth.CLIENT_ID = ""
        try:
            self.assertEqual(asyncio.run(nexus_oauth.start_login()),
                             {"ok": False, "reason": "not_configured"})
        finally:
            nexus_oauth.CLIENT_ID = saved

    def test_start_then_cancel_binds_and_tears_down(self):
        async def go():
            started = await nexus_oauth.start_login()
            up = nexus_oauth._login_server is not None
            await nexus_oauth.cancel_login()
            return started, up
        started, up = asyncio.run(go())
        self.assertTrue(started["ok"], started)
        self.assertTrue(started["authorize_url"].startswith(nexus_oauth.AUTHORIZE_URL))
        self.assertTrue(up)
        self.assertIsNone(nexus_oauth._login_server)


if __name__ == "__main__":
    unittest.main()
