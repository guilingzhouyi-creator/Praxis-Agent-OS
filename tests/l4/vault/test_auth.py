"""Vault auth — KeyVault, AuthService tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestKeyVault:
    def test_set_and_get(self):
        from l4.vault.auth import KeyVault
        vault = KeyVault()
        vault.set("mykey", "myvalue")
        assert vault.get("mykey") == "myvalue"

    def test_get_missing_returns_empty(self):
        from l4.vault.auth import KeyVault
        vault = KeyVault()
        assert vault.get("nonexistent") == ""

    def test_delete(self):
        from l4.vault.auth import KeyVault
        vault = KeyVault()
        vault.set("tmp", "val")
        vault.delete("tmp")
        assert vault.get("tmp") == ""

    def test_list(self):
        from l4.vault.auth import KeyVault
        vault = KeyVault()
        vault.set("k1", "v1")
        vault.set("k2", "v2")
        keys = vault.list()
        assert "k1" in keys
        assert "k2" in keys


class TestAuthService:
    def test_hash(self):
        from l4.vault.auth import AuthService
        svc = AuthService()
        h = svc.hash("password")
        assert isinstance(h, dict)
        assert h.get("success")
