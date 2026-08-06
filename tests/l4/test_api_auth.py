"""Auth token lifecycle API tests — issue/verify/revoke/refresh + handlers."""

from __future__ import annotations

import time

from l4.api_handlers.api_handlers_auth import (
    handle_auth_login,
    handle_auth_logout,
    handle_auth_refresh,
)
from l4.vault.auth import get_service, reset_service


def _reset():
    reset_service()
    return get_service()


class TestTokenLifecycle:
    def test_issue_and_verify(self):
        svc = _reset()
        r = svc.issue_token("alice", ttl=60)
        assert r["success"]
        assert r["identity"] == "alice"
        v = svc.verify_token(r["token"])
        assert v["valid"]
        assert v["identity"] == "alice"

    def test_revoked_token_rejected(self):
        svc = _reset()
        r = svc.issue_token("bob")
        assert svc.revoke_token(r["token"])["success"]
        v = svc.verify_token(r["token"])
        assert not v["valid"]
        assert "revoked" in v["error"]

    def test_missing_token(self):
        svc = _reset()
        v = svc.verify_token("")
        assert not v["valid"]

    def test_forged_signature_rejected(self):
        svc = _reset()
        r = svc.issue_token("mallory")
        token = r["token"]
        identity, expires, tid, _ = token.split("|", 3)
        forged = f"{identity}|{expires}|{tid}|{'0' * 64}"
        v = svc.verify_token(forged)
        assert not v["valid"]
        assert "signature" in v["error"]

    def test_refresh_exchanges_valid_token(self):
        svc = _reset()
        r = svc.issue_token("carol")
        r2 = svc.refresh_token(r["token"])
        assert r2["success"]
        assert r2["token"] != r["token"]
        assert svc.verify_token(r2["token"])["valid"]

    def test_refresh_rejects_revoked(self):
        svc = _reset()
        r = svc.issue_token("dave")
        svc.revoke_token(r["token"])
        r2 = svc.refresh_token(r["token"])
        assert not r2["success"]

    def test_identity_required(self):
        svc = _reset()
        assert not svc.issue_token("  ")["success"]


class TestAuthHandlers:
    def test_login_handler(self):
        _reset()
        r = handle_auth_login({"identity": "ui-user"})
        assert r["success"]
        assert r["identity"] == "ui-user"
        assert r["token"]

    def test_login_requires_identity(self):
        _reset()
        r = handle_auth_login({})
        assert not r["success"]
        assert "identity" in r["error"]

    def test_login_bad_ttl(self):
        _reset()
        r = handle_auth_login({"identity": "x", "ttl": "abc"})
        assert not r["success"]

    def test_logout_revokes(self):
        _reset()
        r = handle_auth_login({"identity": "ui-user"})
        assert handle_auth_logout({"token": r["token"]})["success"]
        assert not get_service().verify_token(r["token"])["valid"]

    def test_refresh_handler(self):
        _reset()
        r = handle_auth_login({"identity": "ui-user"})
        r2 = handle_auth_refresh({"token": r["token"]})
        assert r2["success"]
        assert r2["token"]

    def test_refresh_missing_token(self):
        _reset()
        r = handle_auth_refresh({})
        assert not r["success"]

    def test_port_registered_on_first_use(self):
        _reset()
        from l1.kernel.ports import get_port

        get_service()
        port = get_port("auth")
        r = port.issue_token("via-port")
        assert r["success"]
        assert port.verify_token(r["token"])["valid"]


class TestGatewayAuth:
    """Gateway dual-channel auth: AuthPort login tokens + static shared token."""

    def _headers(self, bearer="", x_token=None):
        h = {}
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        if x_token is not None:
            h["X-API-Token"] = x_token
        return h

    def test_login_token_passes_without_static_token(self):
        _reset()
        svc = get_service()
        r = svc.issue_token("ui-user", ttl=60)
        from l4.api.api_gateway import _auth_ok

        assert _auth_ok(self._headers(bearer=r["token"]), "")

    def test_login_token_passes_even_with_wrong_static_token(self):
        _reset()
        svc = get_service()
        r = svc.issue_token("ui-user", ttl=60)
        from l4.api.api_gateway import _auth_ok

        assert _auth_ok(self._headers(bearer=r["token"]), "static-secret")

    def test_static_bearer_token_passes(self):
        _reset()
        from l4.api.api_gateway import _auth_ok

        assert _auth_ok(self._headers(bearer="shared-token"), "shared-token")

    def test_static_bearer_mismatch_rejected(self):
        _reset()
        from l4.api.api_gateway import _auth_ok

        assert not _auth_ok(self._headers(bearer="wrong"), "shared-token")

    def test_legacy_x_api_token_header_passes(self):
        _reset()
        from l4.api.api_gateway import _auth_ok

        assert _auth_ok(self._headers(x_token="shared-token"), "shared-token")

    def test_expired_login_token_falls_back_to_static(self):
        _reset()
        svc = get_service()
        r = svc.issue_token("expiry", ttl=0.1)
        time.sleep(0.15)
        from l4.api.api_gateway import _auth_ok

        # expired login token != static token → rejected
        assert not _auth_ok(self._headers(bearer=r["token"]), "static-secret")
        # expired login token + no static token passes (open default)
        assert _auth_ok(self._headers(bearer=r["token"]), "")
        # valid static token still passes independently
        assert _auth_ok(self._headers(bearer="static-secret"), "static-secret")


class TestExpiry:
    def test_short_ttl_expires(self):
        svc = _reset()
        r = svc.issue_token("shorty", ttl=0.1)
        time.sleep(0.15)
        v = svc.verify_token(r["token"])
        assert not v["valid"]
        assert "expired" in v["error"]
