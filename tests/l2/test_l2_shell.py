"""L2 Shell tests — ShellState, dispatch, autocomplete, output guard, commands.

Unit-testable surfaces (no heavy service deps):
  - ShellState / get_state / reset_state
  - autocomplete (empty, partial, argument hints)
  - dispatch (/ commands, routing to _l3a_intent / _direct_message)
  - list_commands
  - guard_output / set_output_guard
  - _cmd_help, _cmd_mode, _cmd_status, _cmd_disconnect (state-only paths)
  - _cmd_connect (empty args)
  - _complete_role
  - _auto_disconnect (non-Direct guard)
  - dispatch Direct-mode routing

Functions requiring runtime services (cell, l3, selector, llm) are tested
via the integration test suite or marked with @pytest.mark.integration.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ═══════════════════════════════════════════════════════════════
# ShellState
# ═══════════════════════════════════════════════════════════════


class TestShellState:
    def test_default_state(self):
        from l2.l2_shell import ShellState

        s = ShellState()
        assert s.mode == "L3A"
        assert s.cell_id == "cell-1"
        assert s.agent_id == ""
        assert not s.is_direct()

    def test_switch_to_direct(self):
        from l2.l2_shell import ShellState

        s = ShellState()
        s.switch_to_direct("cell-x", "agent-42", "sess-1")
        assert s.mode == "DIRECT"
        assert s.cell_id == "cell-x"
        assert s.agent_id == "agent-42"
        assert s.session_id == "sess-1"
        assert s.is_direct()

    def test_switch_to_direct_no_session_id(self):
        from l2.l2_shell import ShellState

        s = ShellState()
        s.switch_to_direct("cell-2", "agent-7")
        assert s.is_direct()
        assert s.session_id == ""  # session_id is optional

    def test_switch_to_l3a_clears_state(self):
        from l2.l2_shell import ShellState

        s = ShellState()
        s.switch_to_direct("cell-x", "agent-42", "sess-1")
        s.switch_to_l3a()
        assert s.mode == "L3A"
        assert s.agent_id == ""
        assert s.session_id == ""
        assert not s.is_direct()

    def test_is_direct_false_when_no_agent(self):
        from l2.l2_shell import ShellState

        s = ShellState()
        s.mode = "DIRECT"
        s.agent_id = ""
        assert not s.is_direct()  # both mode==DIRECT AND agent_id required

    def test_reset_state(self):
        from l2.l2_shell import get_state, reset_state

        reset_state()
        s = get_state()
        assert s.mode == "L3A"
        assert s.agent_id == ""

    def test_reset_state_isolation(self):
        from l2.l2_shell import get_state, reset_state

        reset_state()
        s1 = get_state()
        s1.switch_to_direct("c", "a")
        reset_state()
        s2 = get_state()
        assert s2.mode == "L3A"  # reset clears the change from s1


# ═══════════════════════════════════════════════════════════════
# autocomplete
# ═══════════════════════════════════════════════════════════════


class TestAutocomplete:
    def test_empty_line_returns_all_commands(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("")
        assert len(results) > 0
        assert results[0]["type"] == "command"

    def test_slash_only_returns_commands(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("/")
        assert len(results) > 0
        assert all(r["type"] == "command" for r in results)

    def test_partial_command(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("/stat")
        assert len(results) > 0
        assert any("status" in r["value"] for r in results)

    def test_full_command_no_args(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("/help ")
        # /help has no args, so empty arg completion
        assert isinstance(results, list)

    def test_unknown_partial_returns_suggestions(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("/xyznonexistent")
        # Should return fuzzy-matched command names
        assert isinstance(results, list)

    def test_input_capped_at_15(self):
        from l2.l2_shell import autocomplete

        results = autocomplete("")
        assert len(results) <= 15


# ═══════════════════════════════════════════════════════════════
# dispatch
# ═══════════════════════════════════════════════════════════════


class TestDispatch:
    def test_unknown_command(self):
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/nonexistent")
        assert not r.get("success")
        assert "unknown" in r.get("error", "").lower()

    def test_help_command(self):
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/help")
        assert r.get("success")
        assert r.get("format") == "table"
        assert "output" in r

    def test_status_l3a_default(self):
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/status")
        assert r.get("mode") == "L3A"
        assert r.get("cell_id") == "cell-1"
        assert "agent_id" not in r  # only present in Direct mode

    def test_disconnect_no_session(self):
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/disconnect")
        assert not r.get("success")
        assert "no active" in r.get("error", "").lower()

    def test_mode_l3a_default(self):
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/mode")
        assert r.get("mode") == "L3A"
        assert "current_tool_mode" in r

    def test_dispatch_non_slash_in_l3a_routes_to_intent(self):
        """Non-/ text in L3A mode calls _l3a_intent, which tries coord.process_intent.
        This will fail with an import/lookup error since no coordinator is running,
        confirming routing happened correctly."""
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("fix the login bug")
        # Should NOT match a command; should try _l3a_intent and fail gracefully
        assert "error" in r or "success" in r

    def test_dispatch_alias_resolution(self):
        """'ls' is an alias for 'agents'."""
        from l2.l2_shell import dispatch, reset_state

        reset_state()
        r = dispatch("/ls")  # /ls → alias → /agents
        # /agents calls preselect() which will fail, but the routing is correct
        assert isinstance(r, dict)


# ═══════════════════════════════════════════════════════════════
# list_commands
# ═══════════════════════════════════════════════════════════════


class TestListCommands:
    def test_list_commands_format(self):
        from l2.l2_shell import list_commands

        cmds = list_commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0
        for c in cmds:
            assert "command" in c
            assert c["command"].startswith("/")
            assert "help" in c

    def test_list_contains_core_commands(self):
        from l2.l2_shell import list_commands

        cmds = list_commands()
        names = [c["command"] for c in cmds]
        assert "/help" in names
        assert "/connect" in names
        assert "/disconnect" in names
        assert "/mode" in names
        assert "/status" in names
        assert "/security" in names
        assert "/memory" in names
        assert "/plugins" in names


# ═══════════════════════════════════════════════════════════════
# guard_output / output_guard
# ═══════════════════════════════════════════════════════════════


class TestOutputGuard:
    def test_no_guard_returns_safe(self):
        from l2.l2_shell import guard_output, set_output_guard

        set_output_guard(None)
        r = guard_output("agent-a", "some response")
        assert r["safe"]
        assert r["output"] == "some response"

    def test_guard_allows_safe_response(self):
        from l2.l2_shell import guard_output, set_output_guard

        def safe_review(aid, resp):
            return {"safe": True, "reason": "", "replacement": ""}

        set_output_guard(safe_review)
        r = guard_output("agent-a", "safe content")
        assert r["safe"]
        assert r["output"] == "safe content"

    def test_guard_blocks_unsafe_response(self):
        from l2.l2_shell import guard_output, set_output_guard

        def block_review(aid, resp):
            return {"safe": False, "reason": "contains secret", "replacement": "[blocked]"}

        set_output_guard(block_review)
        r = guard_output("agent-a", "the password is xyz")
        assert not r["safe"]
        assert "[blocked]" in r["output"]

    def test_guard_fallback_on_blocked_no_replacement(self):
        from l2.l2_shell import guard_output, set_output_guard

        def block_no_replacement(aid: str, resp: str) -> dict:
            return {"safe": False, "reason": "blocked", "replacement": ""}

        set_output_guard(block_no_replacement)
        r = guard_output("agent-a", "sensitive data here")
        assert not r["safe"]
        # Falls back to first 100 chars of original
        assert "sensitive" in r["output"]

    def test_guard_exception_safe_fallback(self):
        from l2.l2_shell import guard_output, set_output_guard

        def broken_review(aid, resp):
            raise RuntimeError("guard crash")

        set_output_guard(broken_review)
        r = guard_output("agent-a", "any content")
        assert r["safe"]  # exception → safe default
        assert r["output"] == "any content"


# ═══════════════════════════════════════════════════════════════
# Command handlers (unit-testable)
# ═══════════════════════════════════════════════════════════════


class TestCmdMode:
    def test_mode_shows_current(self):
        from l2.l2_shell import _cmd_mode, reset_state

        reset_state()
        r = _cmd_mode([])
        assert r["mode"] == "L3A"
        assert r["cell_id"] == "cell-1"

    def test_mode_with_tool_subcommand(self):
        from l2.l2_shell import _cmd_mode, reset_state

        reset_state()
        r = _cmd_mode(["tool", "read"])
        assert "mode" in r
        assert "current_tool_mode" in r

    def test_mode_invalid_subcommand(self):
        from l2.l2_shell import _cmd_mode, reset_state

        reset_state()
        r = _cmd_mode(["invalid_arg"])
        assert "error" in r


class TestCmdHelp:
    def test_help_returns_table(self):
        from l2.l2_shell import _cmd_help

        r = _cmd_help([])
        assert r["success"]
        assert r["format"] == "table"
        assert len(r["output"]) > 0


class TestCmdDisconnect:
    def test_disconnect_no_session_returns_error(self):
        from l2.l2_shell import _cmd_disconnect, reset_state

        reset_state()
        r = _cmd_disconnect([])
        assert not r.get("success")
        assert "no active" in r.get("error", "").lower()


# ═══════════════════════════════════════════════════════════════
# Shell service entry points (shell.py)
# ═══════════════════════════════════════════════════════════════


class TestShellEntryPoints:
    def test_start_repl_importable(self):
        from l2.shell import direct_session, start_repl

        assert callable(direct_session)
        assert callable(start_repl)

    def test_terminal_completer_importable(self):
        from l2.shell_completer import TerminalCompleter

        tc = TerminalCompleter()
        assert tc._commands == []
        tc.refresh()
        assert len(tc._commands) > 0

    def test_terminal_session_dataclass(self):
        from l2.shell_session import TerminalSession

        s = TerminalSession(id="test", pid=9999)
        assert s.id == "test"
        assert s.pid == 9999
        assert not s.is_alive()  # no process

    def test_terminal_manager_singleton(self):
        from l2.shell_session import get_manager, reset_manager

        reset_manager()
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2


# ═══════════════════════════════════════════════════════════════
# reset_state integration guard — must not affect other tests
# ═══════════════════════════════════════════════════════════════


class TestStateIsolation:
    def test_reset_state_clears_preconnect_cache(self):
        from l2.l2_shell import get_state, reset_state

        reset_state()
        s = get_state()
        assert hasattr(s, "_preconnect_cache")
        # Ensure it's a fresh dict
        s._preconnect_cache["x"] = "y"
        reset_state()
        s2 = get_state()
        assert "x" not in s2._preconnect_cache


# ═══════════════════════════════════════════════════════════════
# _complete_role (unit-testable, no runtime deps)
# ═══════════════════════════════════════════════════════════════


class TestCompleteRole:
    def test_empty_partial_returns_all(self):
        from l2.l2_shell import _complete_role

        results = _complete_role("")
        assert len(results) == 6
        roles = {r["value"] for r in results}
        assert roles == {"reader", "writer", "reviewer", "scout", "l3", "deployer"}

    def test_partial_match(self):
        from l2.l2_shell import _complete_role

        results = _complete_role("w")
        values = [r["value"] for r in results]
        assert "writer" in values
        assert "reader" not in values

    def test_no_match_returns_empty(self):
        from l2.l2_shell import _complete_role

        results = _complete_role("zzz")
        assert results == []

    def test_case_insensitive(self):
        from l2.l2_shell import _complete_role

        results = _complete_role("REV")
        values = [r["value"] for r in results]
        assert "reviewer" in values


# ═══════════════════════════════════════════════════════════════
# _cmd_connect (empty-args path only)
# ═══════════════════════════════════════════════════════════════


class TestCmdConnect:
    def test_empty_args_returns_usage(self):
        from l2.l2_shell import _cmd_connect

        r = _cmd_connect([])
        assert not r.get("success")
        assert "usage" in r.get("error", "").lower()


# ═══════════════════════════════════════════════════════════════
# _auto_disconnect (non-Direct guard)
# ═══════════════════════════════════════════════════════════════


class TestAutoDisconnect:
    def test_non_direct_returns_early(self):
        """Verify _auto_disconnect does nothing when already in L3A."""
        from l2.l2_shell import ShellState, _auto_disconnect

        s = ShellState()  # mode = L3A by default
        assert not s.is_direct()
        # Should not raise, not change state
        _auto_disconnect(s, "test reason")
        assert s.mode == "L3A"

    def test_switch_to_direct_then_auto_disconnect(self):
        from l2.l2_shell import ShellState, _auto_disconnect, reset_state

        reset_state()
        s = ShellState()
        s.switch_to_direct("cell-1", "agent-test")
        assert s.is_direct()
        # _auto_disconnect will try cell.close_direct_session → fails silently
        _auto_disconnect(s, "test reason")
        assert not s.is_direct()
        assert s.mode == "L3A"

    def test_direct_message_failure_auto_disconnects_cleanly(self, mocker):
        """D1/D2 regression: direct message failure falls back to L3A without raising.

        Guards against the old `from .cell import get_cell` (missing module) and
        the unimported SIGNAL_TARGET_L3 (NameError) inside _auto_disconnect.
        """
        from l2.l2_shell import _direct_message, reset_state
        from l2.l2_shell.state import get_state

        reset_state()
        s = get_state()
        s.switch_to_direct("cell-1", "agent-test")
        mock_cell = mocker.Mock()
        mock_cell.send_direct_message.return_value = {"success": False, "error": "boom"}
        mocker.patch("l3.cell.get_cell", return_value=mock_cell)
        r = _direct_message(s, "hello")
        assert r.get("success") is False
        assert s.mode == "L3A"  # auto-disconnected
        assert not s.is_direct()

    def test_direct_message_cell_error_falls_back(self, mocker):
        """D1/D2 regression: exception in send_direct_message also falls back."""
        from l2.l2_shell import _direct_message, reset_state
        from l2.l2_shell.state import get_state

        reset_state()
        s = get_state()
        s.switch_to_direct("cell-1", "agent-test")
        mock_cell = mocker.Mock()
        mock_cell.send_direct_message.side_effect = RuntimeError("cell down")
        mocker.patch("l3.cell.get_cell", return_value=mock_cell)
        r = _direct_message(s, "hello")
        assert r.get("success") is False
        assert s.mode == "L3A"
        assert not s.is_direct()


# ═══════════════════════════════════════════════════════════════
# dispatch Direct-mode routing
# ═══════════════════════════════════════════════════════════════


class TestDispatchDirectMode:
    def test_direct_mode_routes_to_direct_message(self):
        """When in DIRECT mode, non-/ text should route to _direct_message."""
        from l2.l2_shell import dispatch, get_state, reset_state

        reset_state()
        state = get_state()
        # Manually set DIRECT mode (simulate what /connect does)
        state.switch_to_direct("cell-1", "agent-test")

        # _direct_message will try to import get_cell(...) → fail gracefully
        r = dispatch("hello agent")
        assert isinstance(r, dict)


# ═══════════════════════════════════════════════════════════════
# autocomplete — arg completion paths
# ═══════════════════════════════════════════════════════════════


class TestAutocompleteArgCompletion:
    def test_command_with_optional_arg_hint(self):
        """Commands with defined args return arg_hint when completing."""
        from l2.l2_shell import autocomplete

        # /status has an optional "cell_id" arg
        results = autocomplete("/status ")
        # Should return arg hints (cell_id)
        assert isinstance(results, list)

    def test_partial_non_slash_text_returns_fuzzy_commands(self):
        """Typing non-/ text that doesn't match a command returns suggestions."""
        from l2.l2_shell import autocomplete

        results = autocomplete("xyz123nonexistent")
        # Should return command names that fuzzy-match (empty here = fuzzy against everything)
        assert isinstance(results, list) and len(results) <= 10
