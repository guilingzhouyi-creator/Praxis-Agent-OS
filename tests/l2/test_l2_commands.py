"""Tests for L2 Shell command handlers — core commands requiring minimal infra."""

from __future__ import annotations

import pytest

from l1.kernel.commands import get_registry, reset_registry


class TestParseAgentRef:
    """_parse_agent_ref — cell.agent parsing."""

    def test_cell_dot_agent(self):
        from l2.l2_shell.commands import _parse_agent_ref
        cell, agent = _parse_agent_ref("cell-1.agent-a")
        assert cell == "cell-1"
        assert agent == "agent-a"

    def test_bare_agent(self):
        from l2.l2_shell.commands import _parse_agent_ref
        cell, agent = _parse_agent_ref("agent-a")
        assert cell == "default"
        assert agent == "agent-a"


class TestCommandRegistry:
    """Command registration and listing."""

    def setup_method(self):
        reset_registry()

    def test_registry_list_returns_commands(self):
        reg = get_registry()
        cmds = reg.list()
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_registry_has_help(self):
        reg = get_registry()
        cmd = reg.get("help")
        assert cmd is not None

    def test_registry_get_unknown(self):
        reg = get_registry()
        cmd = reg.get("nonexistent_cmd_xyz")
        assert cmd is None


class TestCmdHelp:
    """/help command."""

    def test_help_returns_commands(self):
        from l2.l2_shell.commands import _cmd_help
        r = _cmd_help([])
        assert r.get("success")
        assert "commands" in r
        assert len(r["commands"]) > 0


class TestCmdEcho:
    """/echo command."""

    def test_echo_message(self):
        from l2.l2_shell.commands import _cmd_echo
        r = _cmd_echo(["hello", "world"])
        assert r.get("success")
        assert r.get("message") == "hello world"

    def test_echo_empty(self):
        from l2.l2_shell.commands import _cmd_echo
        r = _cmd_echo([])
        assert r.get("success")
        assert r.get("message") == ""


class TestCmdLocale:
    """/locale command."""

    def test_locale_list_available(self):
        from l2.l2_shell.commands import _cmd_locale
        r = _cmd_locale([])
        assert r.get("success")
        assert "locales" in r
        assert "current" in r

    def test_locale_set_unknown(self):
        from l2.l2_shell.commands import _cmd_locale
        r = _cmd_locale(["nonexistent_locale"])
        # Should return available locales with error or success
        assert isinstance(r, dict)


class TestCmdHistory:
    """/history command."""

    def test_history_returns_list(self):
        from l2.l2_shell.commands import _cmd_history
        r = _cmd_history([])
        assert r.get("success")

    def test_history_with_limit(self):
        from l2.l2_shell.commands import _cmd_history
        r = _cmd_history(["5"])
        assert r.get("success")


class TestCmdThink:
    """/think command — think registry."""

    def test_think_global(self):
        from l2.l2_shell.commands import _cmd_think
        r = _cmd_think(["global"])
        assert isinstance(r, dict)

    def test_think_global_set(self):
        from l2.l2_shell.commands import _cmd_think
        r = _cmd_think(["global", "reasoning_effort=high"])
        assert isinstance(r, dict)


class TestCmdVfs:
    """/vfs command — list mounts."""

    def test_vfs_mounts(self):
        from l2.l2_shell.commands import _cmd_vfs
        r = _cmd_vfs(["--mounts"])
        assert isinstance(r, dict)
        assert "mounts" in r

    def test_vfs_root(self):
        from l2.l2_shell.commands import _cmd_vfs
        r = _cmd_vfs(["/"])
        # VFS root should at least return a dict
        assert isinstance(r, dict)


class TestCmdMode:
    """/mode command."""

    def test_mode_default(self):
        from l2.l2_shell.commands import _cmd_mode
        r = _cmd_mode([])
        assert r.get("mode") in ("L3A", "DIRECT")

    def test_mode_switch(self):
        from l2.l2_shell.commands import _cmd_mode
        r = _cmd_mode(["tool", "read"])
        assert "current_tool_mode" in r or r.get("success")


class TestCmdCells:
    """/cells command."""

    def test_cells_list(self):
        from l2.l2_shell.commands import _cmd_cells
        r = _cmd_cells(["list"])
        assert isinstance(r, dict)
        assert "cells" in r or r.get("success")


class TestCmdCron:
    """/cron command."""

    def test_cron_list(self):
        from l2.l2_shell.commands import _cmd_cron
        r = _cmd_cron(["list"])
        assert isinstance(r, dict)

    def test_cron_remove_no_args(self):
        from l2.l2_shell.commands import _cmd_cron
        r = _cmd_cron(["remove"])
        assert not r.get("success")


class TestCmdTools:
    """/tools command."""

    def test_tools_list(self):
        from l2.l2_shell.commands import _cmd_tools
        r = _cmd_tools([])
        assert r.get("success")
        assert "tools" in r


class TestCmdDebug:
    """/debug command."""

    def test_debug_health(self):
        from l2.l2_shell.commands import _cmd_debug
        r = _cmd_debug(["health"])
        assert isinstance(r, dict)
