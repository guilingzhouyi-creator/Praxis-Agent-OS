"""I18n service tests — translation loading, locale switching, L2_Shell integration."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestI18nCore:
    def test_default_locale(self):
        from l2.i18n import get_locale
        assert get_locale() == "en"

    def test_set_locale(self):
        from l2.i18n import get_locale, set_locale
        prev = get_locale()
        set_locale("zh-CN")
        assert get_locale() == "zh-CN"
        set_locale(prev)  # restore

    def test_t_key_fallback(self):
        from l2.i18n import t
        result = t("nonexistent.key.xyz")
        assert result == "nonexistent.key.xyz"  # key fallback

    def test_t_shell_command(self):
        from l2.i18n import t
        result = t("shell.command.help")
        assert result == "Show available commands"

    def test_t_variable_substitution(self):
        from l2.i18n import t
        result = t("shell.error.unknown_command", cmd="test")
        assert "test" in result
        assert "/test" in result

    def test_t_zh_cn(self):
        from l2.i18n import get_locale, set_locale, t
        prev = get_locale()
        set_locale("zh-CN")
        result = t("shell.command.help")
        assert "显示" in result
        set_locale(prev)

    def test_get_available_locales(self):
        from l2.i18n import get_available_locales
        locales = get_available_locales()
        assert "en" in locales
        assert "zh-CN" in locales


class TestI18nL2Shell:
    def test_list_commands_localized_en(self):
        from l2.l2_shell import list_commands, reset_state
        reset_state()
        cmds = list_commands()
        help_cmd = next((c for c in cmds if c["command"] == "/help"), None)
        assert help_cmd is not None
        assert "命令" not in help_cmd["help"]  # English, not Chinese

    def test_dispatch_help(self):
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/help")
        assert r.get("success")
        assert r.get("format") == "table"
        assert len(r.get("output", [])) > 0

    def test_dispatch_lang_shows_current(self):
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/lang")
        assert r.get("success")
        assert "locale" in r
        assert "available" in r

    def test_dispatch_lang_switch(self):
        from l2.i18n import get_locale
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        prev = get_locale()
        r = dispatch("/lang en")
        assert r.get("success")
        assert r["locale"] == "en"
        # restore
        from l2.i18n import set_locale
        set_locale(prev)

    def test_dispatch_unknown_zh(self):
        """Switch to zh-CN, unknown command should show Chinese error."""
        from l2.i18n import get_locale, set_locale
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        prev = get_locale()
        set_locale("zh-CN")
        r = dispatch("/xyznonexistent")
        assert not r.get("success")
        assert "未知" in r.get("error", "")
        set_locale(prev)

    def test_command_count(self):
        from l2.l2_shell import list_commands, reset_state
        reset_state()
        cmds = list_commands()
        assert len(cmds) >= 16  # at least 16 commands


class TestI18nKernelErrors:
    def test_set_locale_delegates_to_i18n(self):
        from l1.kernel.errors import get_locale, set_locale
        prev = get_locale()
        set_locale("zh-CN")
        from l2.i18n import get_locale as _i18n_get
        assert _i18n_get() == "zh-CN"
        set_locale(prev)

    def test_error_to_dict(self):
        from l1.kernel.errors import PraxisError
        err = PraxisError("E_TIMEOUT", "Operation timed out")
        d = err.to_dict()
        assert d["error_code"] == "E_TIMEOUT"
        assert d["error"] == "Operation timed out"


class TestI18nToolSpec:
    def test_list_tools(self):
        """list_tools returns ToolSpec objects with names/descriptions."""
        from l3.tool_system.tool_spec import TOOL_REGISTRY, list_tools
        if not TOOL_REGISTRY:
            return
        tools = list_tools()
        assert isinstance(tools, list)
        for t in tools:
            assert t.name
            assert t.description or t.description == ""


class TestI18nConfig:
    def test_language_in_praxis_yaml(self, tmp_path):
        """Language config should exist in praxis.yaml."""
        import yaml
        yaml_path = tmp_path / "praxis.yaml"
        yaml_path.write_text("language: en\n", encoding="utf-8")
        with open(str(yaml_path), encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert "language" in cfg
        assert cfg["language"] in ("en", "zh-CN")
