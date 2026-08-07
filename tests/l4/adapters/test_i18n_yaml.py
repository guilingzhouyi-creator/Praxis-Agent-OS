"""Adapter: YamlI18nAdapter tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestYamlI18nAdapter:
    """YamlI18nAdapter — translation loading and lookup."""

    def test_get_available(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        locales = adapter.get_available()
        assert isinstance(locales, list)
        assert "en" in locales

    def test_get_locale_default(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        assert adapter.get_locale() == "en"

    def test_set_locale(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        adapter.set_locale("zh-CN")
        assert adapter.get_locale() == "zh-CN"
        adapter.set_locale("en")

    def test_t_returns_string(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        result = adapter.t("shell.command.help")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_t_missing_key_falls_back(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        result = adapter.t("nonexistent.key.xyz")
        assert result == "nonexistent.key.xyz"
