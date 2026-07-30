"""Tests for Auth service — key management, signing, encryption, hash."""

from __future__ import annotations

import pytest

from l4.vault.auth import KeyVault, AuthService, get_service, reset_service


class TestKeyVault:
    def test_set_and_get(self):
        kv = KeyVault()
        kv.set("my_key", "my_value")
        assert kv.get("my_key") == "my_value"

    def test_get_missing_returns_default(self):
        kv = KeyVault()
        assert kv.get("nonexistent") == ""
        assert kv.get("nonexistent", "fallback") == "fallback"

    def test_delete_existing(self):
        kv = KeyVault()
        kv.set("k", "v")
        assert kv.delete("k") is True
        assert kv.get("k") == ""

    def test_delete_missing(self):
        kv = KeyVault()
        assert kv.delete("nonexistent") is False

    def test_list(self):
        kv = KeyVault()
        kv.set("a", "1")
        kv.set("b", "2")
        keys = kv.list()
        assert len(keys) == 2
        assert "a" in keys
        assert "b" in keys


class TestAuthService:
    def setup_method(self):
        reset_service()

    def test_sign_and_verify(self):
        svc = AuthService()
        r = svc.sign("hello")
        assert r["success"]
        assert "signature" in r
        vr = svc.verify("hello", r["signature"])
        assert vr["valid"] is True

    def test_verify_wrong_data(self):
        svc = AuthService()
        r = svc.sign("hello")
        vr = svc.verify("world", r["signature"])
        assert vr["valid"] is False

    def test_sign_with_custom_key(self):
        svc = AuthService()
        r = svc.sign("data", key="aabb" * 8)
        assert r["success"]

    def test_hash_default(self):
        svc = AuthService()
        r = svc.hash("test")
        assert r["success"]
        assert r["algorithm"] == "sha256"
        assert len(r["hash"]) == 64

    def test_hash_unsupported_algorithm(self):
        svc = AuthService()
        r = svc.hash("test", algorithm="nonexistent")
        assert not r["success"]

    def test_encrypt_decrypt_roundtrip(self):
        svc = AuthService()
        er = svc.encrypt("secret data")
        if not er["success"]:
            pytest.skip("cryptography not installed")
        dr = svc.decrypt(er["encrypted"], er["key"])
        assert dr["success"]
        assert dr["decrypted"] == "secret data"

    def test_decrypt_wrong_key(self):
        svc = AuthService()
        er = svc.encrypt("data")
        if not er["success"]:
            pytest.skip("cryptography not installed")
        dr = svc.decrypt(er["encrypted"], "wrong-key")
        assert not dr["success"]

    def test_vault_set_get(self):
        svc = AuthService()
        svc.vault_set("my_key", "my_value")
        r = svc.vault_get("my_key")
        assert r["found"] is True
        assert r["length"] == 8

    def test_vault_get_missing(self):
        svc = AuthService()
        r = svc.vault_get("nonexistent")
        assert r["found"] is False

    def test_vault_list(self):
        svc = AuthService()
        svc.vault_set("k1", "v1")
        svc.vault_set("k2", "v2")
        r = svc.vault_list()
        assert r["count"] == 2

    def test_get_service_singleton(self):
        reset_service()
        s1 = get_service()
        s2 = get_service()
        assert s1 is s2

    def test_reset_service(self):
        reset_service()
        s = get_service()
        vk = s.vault_get("service_key")
        assert vk["found"] is True
        reset_service()
        s2 = get_service()
        # After reset, service_key should still be set by _on_start
        vk2 = s2.vault_get("service_key")
        assert vk2["found"] is True
