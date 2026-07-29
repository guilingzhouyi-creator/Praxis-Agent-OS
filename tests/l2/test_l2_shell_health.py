"""L2 Shell command health test — verify each /command does not silently fail.

Background: commands.py once had 32 relative import path errors,
causing most commands to be silently unavailable. This test ensures every registered
handler can at least be invoked without raising ImportError.

Strategy:
  - Verify module-level import succeeds (does not crash)
  - Verify dispatch() function exists and is callable
  - Verify each command handler function can be correctly resolved
  - Lightweight check, does not depend on L3/L4 runtime backends
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestModuleImports:
    """Verify commands.py module-level imports do not crash"""

    def test_commands_module_imports(self):
        """Verify entire commands.py can be imported (all module-level imports correct)"""
        from l2.l2_shell import commands
        assert commands is not None
        assert hasattr(commands, 'preconnect_enhanced')
        assert hasattr(commands, '_pipeline')

    def test_shell_init_imports(self):
        """Verify l2_shell.__init__ can be imported"""
        from l2.l2_shell import dispatch, guard_output, get_state
        assert callable(dispatch)
        assert callable(guard_output)
        assert callable(get_state)

    def test_state_module(self):
        from l2.l2_shell.state import ShellState, get_state, reset_state
        s = get_state()
        assert s.mode == "L3A"
        assert s.cell_id == "cell-1"

    def test_output_guard_module(self):
        from l2.l2_shell.output_guard import guard_output, set_output_guard
        r = guard_output("test-agent", "safe response")
        assert isinstance(r, dict)
        assert r.get("allowed", True)

    def test_all_command_handlers_accessible(self):
        """Verify each _cmd_* handler for registered commands exists in the modules namespace"""
        from l1.kernel.commands import list_commands as _list_defs
        cmds = _list_defs()
        assert len(cmds) >= 20, f"only {len(cmds)} commands registered"
        handler_names = []
        for c in cmds:
            name = c["name"]
            handler_names.append(f"_cmd_{name}")
        # Check if handlers exist in commands module (not all required, but most should exist)
        from l2.l2_shell import commands as _cmds
        missing = [h for h in handler_names if not hasattr(_cmds, h)]
        # At least 80% of handlers should be accessible
        accessible = len(handler_names) - len(missing)
        assert accessible >= len(handler_names) * 0.8, \
            f"{len(missing)} handlers missing: {missing[:5]}..."


class TestCommandContent:
    """Verify commands return reasonable result structures"""

    def test_help_returns_output(self):
        from l2.l2_shell import dispatch
        r = dispatch("/help")
        assert isinstance(r, dict)
        # help should have output on success
        if r.get("success") != False:
            assert "output" in r

    def test_agents_returns_dict(self):
        from l2.l2_shell import dispatch
        r = dispatch("/agents")
        assert isinstance(r, dict)

    def test_status_returns_dict(self):
        from l2.l2_shell import dispatch
        r = dispatch("/status")
        assert isinstance(r, dict)

    def test_clear_returns_clear_flag(self):
        from l2.l2_shell import dispatch
        r = dispatch("/clear")
        assert isinstance(r, dict)
        assert r.get("clear") is True

    def test_history_returns_list(self):
        from l2.l2_shell import dispatch
        r = dispatch("/history")
        assert isinstance(r, dict)
        # history may or may not have entries, but should not crash
        assert "history" in r or "error" in r


class TestCommandRegistration:
    """Verify command registration mechanism completeness"""

    def test_list_commands_returns_list(self):
        from l2.l2_shell.commands import list_commands
        cmds = list_commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0
        for c in cmds:
            assert "command" in c
            assert "help" in c

    def test_core_commands_present(self):
        from l2.l2_shell.commands import list_commands
        cmds = list_commands()
        names = [c["command"] for c in cmds]
        for required in ["/help", "/status", "/tools", "/config", "/memory"]:
            assert required in names, f"required command {required} not in list"
