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

    def test_t_locale_does_not_switch_active(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        adapter.set_locale("en")
        msg = adapter.t_locale("ja", "shell.command.help")
        assert msg and msg != "Show available commands"
        assert adapter.get_locale() == "en"

    def test_t_locale_missing_key_falls_back(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        result = adapter.t_locale("ja", "nonexistent.key.xyz")
        assert result == "nonexistent.key.xyz"

    def test_t_locale_substitution(self):
        from l4.adapters.i18n_yaml import YamlI18nAdapter

        adapter = YamlI18nAdapter()
        result = adapter.t_locale("zh-CN", "shell.error.unknown_command", cmd="foo")
        assert "/foo" in result


class TestLocaleFileParity:
    """locales/*.yaml — key parity and error.* catalog coverage."""

    @staticmethod
    def _flatten(data: dict, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        for k, v in data.items():
            fk = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys |= TestLocaleFileParity._flatten(v, fk)
            elif isinstance(v, str) and v:
                keys.add(fk)
        return keys

    def test_all_locales_share_identical_keys(self):
        import glob
        import os

        import yaml

        assert os.path.isdir("locales"), "test must run from repo root"
        data: dict[str, dict] = {}
        for path in sorted(glob.glob("locales/*.yaml")):
            with open(path, encoding="utf-8") as f:
                data[os.path.basename(path)] = yaml.safe_load(f)
        assert len(data) >= 4
        base = self._flatten(data["en.yaml"])
        for name, locale in data.items():
            assert self._flatten(locale) == base, f"{name} key set diverges from en.yaml"

    def test_error_catalog_covered_in_every_locale(self):
        import glob

        import yaml

        from l1.kernel.errors import catalog

        codes = set(catalog())
        assert codes, "error catalog must be non-empty"
        for path in sorted(glob.glob("locales/*.yaml")):
            with open(path, encoding="utf-8") as f:
                locale = yaml.safe_load(f)
            for code in codes:
                key = "error." + code
                assert self._flatten(locale).__contains__(key), f"{path} missing {key}"
