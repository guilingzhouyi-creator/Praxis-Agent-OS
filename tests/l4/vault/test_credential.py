"""Tests for l4.vault.credential_vault — credential lifecycle."""

from __future__ import annotations

import os
import tempfile


class TestCredentialVault:
    """credential_vault 基本生命周期 — init/set/get/delete/export/list。"""

    def _init_vault(self):
        """每次测试使用独立临时目录初始化新 vault。"""
        import l4.vault.credential_vault as cv
        self._tmpdir = tempfile.mkdtemp()
        cv._vault.clear()
        cv._VAULT_PATH = ""
        cv._VAULT_KEY = b""
        r = cv.init_vault(self._tmpdir)
        assert r.get("success")
        return cv

    def test_init_creates_vault(self):
        """init_vault 应成功创建并返回路径。"""
        cv = self._init_vault()
        s = cv.export_vault_status()
        assert s.get("exists") is True or s.get("providers") >= 0

    def test_set_and_get(self):
        """set_credential 后 get_credential 应返回相同值。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "sk-test-123")
        val = cv.get_credential("openai", "api_key")
        assert val == "sk-test-123"

    def test_get_nonexistent(self):
        """不存在的凭据应返回空字符串。"""
        cv = self._init_vault()
        val = cv.get_credential("nonexistent", "api_key")
        assert val == ""

    def test_get_with_env_fallback(self):
        """env_fallback 应在 vault 无值时返回环境变量。"""
        cv = self._init_vault()
        os.environ["TEST_VAULT_FALLBACK"] = "env-value"
        val = cv.get_credential("test", "api_key", env_fallback="TEST_VAULT_FALLBACK")
        assert val == "env-value"
        del os.environ["TEST_VAULT_FALLBACK"]

    def test_delete_single_key(self):
        """delete_credential 应删除指定 key。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "sk-123")
        cv.set_credential("openai", "api_url", "https://api.openai.com")
        cv.delete_credential("openai", "api_key")
        val = cv.get_credential("openai", "api_key")
        assert val == ""
        # 另一个 key 仍存在
        val2 = cv.get_credential("openai", "api_url")
        assert val2 == "https://api.openai.com"

    def test_delete_entire_provider(self):
        """delete_credential 不指定 key 应删除整个 provider。"""
        cv = self._init_vault()
        cv.set_credential("anthropic", "api_key", "sk-ant-123")
        cv.set_credential("anthropic", "api_url", "https://api.anthropic.com")
        cv.delete_credential("anthropic")
        provs = cv.list_providers()
        assert all(p["provider"] != "anthropic" for p in provs)

    def test_list_providers(self):
        """list_providers 应返回所有 provider 及 key 数量（不含值）。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "sk-123")
        cv.set_credential("anthropic", "api_key", "sk-ant-123")
        provs = cv.list_providers()
        names = [p["provider"] for p in provs]
        assert "openai" in names
        assert "anthropic" in names
        for p in provs:
            assert "keys" in p
            assert "count" in p

    def test_export_vault_status(self):
        """export_vault_status 应返回统计信息。"""
        cv = self._init_vault()
        cv.set_credential("deepseek", "api_key", "sk-ds-123")
        s = cv.export_vault_status()
        assert s.get("providers") >= 1
        assert "provider_list" in s
        assert "total_keys" in s

    def test_get_credential_for_provider(self):
        """get_credential_for_provider 应返回 provider 的所有凭据。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "sk-456")
        cv.set_credential("openai", "api_url", "https://api.openai.com")
        result = cv.get_credential_for_provider("openai")
        assert result.get("api_key") == "sk-456"
        assert result.get("api_url") == "https://api.openai.com"

    def test_set_overwrites(self):
        """重复 set 应覆盖已有值。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "old-key")
        cv.set_credential("openai", "api_key", "new-key")
        val = cv.get_credential("openai", "api_key")
        assert val == "new-key"

    def test_persist_roundtrip(self):
        """set + 重新 init_vault + get 应保留值。"""
        cv = self._init_vault()
        cv.set_credential("openai", "api_key", "sk-persist")
        vault_path = cv._VAULT_PATH
        vault_key = cv._VAULT_KEY
        # 模拟重启：重置并重新初始化指向同一目录
        cv._vault.clear()
        cv._VAULT_PATH = ""
        cv._VAULT_KEY = b""
        cv.init_vault(self._tmpdir)
        cv._VAULT_KEY = vault_key  # 使用同一密钥
        cv._load_vault()
        val = cv.get_credential("openai", "api_key")
        assert val == "sk-persist", f"expected persisted value, got {val!r}"
