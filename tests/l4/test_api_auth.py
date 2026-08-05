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


class TestExpiry:
    def test_short_ttl_expires(self):
        svc = _reset()
        r = svc.issue_token("shorty", ttl=0.1)
        time.sleep(0.15)
        v = svc.verify_token(r["token"])
        assert not v["valid"]
        assert "expired" in v["error"]
