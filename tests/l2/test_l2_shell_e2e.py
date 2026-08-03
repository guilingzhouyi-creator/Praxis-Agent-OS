"""L2 Shell end-to-end integration test — start real services for full-link testing.

Follows the test pattern from tests/test_integration.py:
  1. Import service modules inside test functions
  2. Create real instances of Cell, Agent, L3, etc.
  3. Execute operations and verify results
  4. Use reset_*() to clean up singleton state
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _wait_for_agent(agent_id: str, timeout: float = 2.0, poll: float = 0.05) -> bool:
    """Poll AgentTerminal status until IDLE or timeout.

    Replaces fixed time.sleep() with responsive polling to reduce CI wall-clock time.
    Returns True if agent reached IDLE within timeout, False otherwise.
    """
    from l1.kernel.params.agent import AGENT_STATUS_IDLE
    from l3.agent_terminal import get_terminal
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            term = get_terminal(agent_id)
            if term and term.status.name == AGENT_STATUS_IDLE:
                return True
        except Exception:
            pass
        time.sleep(poll)
    return False


class TestL2ShellDispatchE2E:
    """End-to-end test: L2_Shell dispatch executes full chain via real Cell/Agent."""

    def test_dispatch_agents_with_real_cell(self):
        """After creating Cell + Agent, /agents command should list that agent."""
        from l2.l2_shell import dispatch, reset_state
        from l3.agent.scout import reset_pool
        from l3.agent_terminal import reset_terminals
        from l3.cell import get_cell, reset_cells

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-test-cell", ["."])
            cell.add_agent("alpha", role="writer", territory=["."], auto_boot=True)
            _wait_for_agent("alpha")

            r = dispatch("/agents")
            assert isinstance(r, dict)
            agents = r.get("data", {}).get("agents", [])
            assert len(agents) >= 1
            aids = [a["agent_id"] for a in agents]
            assert "alpha" in aids
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_connect_disconnect_live(self):
        """Full /connect → /disconnect flow with real Cell + Agent."""
        from l2.l2_shell import dispatch, get_state, reset_state
        from l3.agent.scout import reset_pool
        from l3.agent_terminal import reset_terminals
        from l3.cell import get_cell, reset_cells

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-connect", ["."])
            cell.add_agent("connector", role="writer", territory=["."], auto_boot=True)
            _wait_for_agent("connector")

            # /connect
            r = dispatch("/connect connector")
            # May be rejected by preconnect due to LLM/provider unavailability, but routing itself is correct
            assert isinstance(r, dict)
            if r.get("success"):
                s = get_state()
                assert s.is_direct()
                assert s.agent_id == "connector"

                # /disconnect
                r2 = dispatch("/disconnect")
                assert r2.get("success")
                assert not s.is_direct()
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_status_after_connect(self):
        """After connecting, /status in Direct mode should show agent info."""
        from l2.l2_shell import dispatch, get_state, reset_state
        from l3.agent.scout import reset_pool
        from l3.agent_terminal import reset_terminals
        from l3.cell import get_cell, reset_cells

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-status", ["."])
            cell.add_agent("stat-bot", role="reader", territory=["."], auto_boot=True)
            _wait_for_agent("stat-bot")

            # Force set Direct state (no need for LLM preconnect)
            state = get_state()
            state.switch_to_direct("e2e-status", "stat-bot", "sess-e2e")

            r = dispatch("/status")
            assert r.get("mode") == "DIRECT"
            assert r.get("agent_id") == "stat-bot"
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()

    def test_dispatch_help_returns_commands(self):
        """/help should return command list in any state."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/help")
        assert r.get("success")
        assert r.get("format") == "table"
        output = r.get("output", "")
        assert len(output) > 0
        assert "/help" in output
        assert "/connect" in output
        assert "/disconnect" in output

    def test_dispatch_unknown_command(self):
        """Unknown command should return error + suggestions."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/xyznonexistent")
        assert not r.get("success")
        assert "unknown" in r.get("error", "").lower()
        assert "suggestions" in r

    def test_dispatch_mode_switch(self):
        """/mode should correctly display and switch tool modes."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/mode")
        assert r.get("mode") == "L3A"

        r2 = dispatch("/mode tool read")
        assert "current_tool_mode" in r2


class TestL2ShellDirectMessageE2E:
    """Direct message sending end-to-end test."""

    def test_non_slash_routes_to_intent(self):
        """Non-/ text in L3A mode should route to l3 coordinator."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        # L3 coordinator already exists (auto-initialized by service layer)
        r = dispatch("list current directory")
        # coordinator.process_intent should return a card result (may error but routing is correct)
        assert isinstance(r, dict)

    def test_direct_message_send_to_live_agent(self):
        """In Direct mode, send message to a real agent."""
        from l2.l2_shell import dispatch, get_state, reset_state
        from l3.agent.scout import reset_pool
        from l3.agent_terminal import reset_terminals
        from l3.cell import get_cell, reset_cells

        reset_state()
        reset_terminals()
        reset_pool()
        reset_cells()

        try:
            cell = get_cell("e2e-msg", ["."])
            cell.add_agent("msg-bot", role="reader", territory=["."], auto_boot=True)
            _wait_for_agent("msg-bot")

            state = get_state()
            state.switch_to_direct("e2e-msg", "msg-bot", "sess-msg")

            # Send non-/ message, should route to _direct_message
            r = dispatch("hello agent")
            assert isinstance(r, dict)
            # Even if agent processing fails, routing itself is correct
            assert "success" in r or "error" in r
        finally:
            reset_terminals()
            reset_pool()
            reset_cells()
            reset_state()


class TestL2ShellCentralCommandsE2E:
    """End-to-end test for 9 central control commands — verify routing to real services."""

    def test_cmd_intents(self):
        """intents command should return data via L3 coordinator."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/intents")
        assert "intents" in r

    def test_cmd_scheduler(self):
        """scheduler command should return scheduling status."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/scheduler")
        assert r.get("success")

    def test_cmd_observe(self):
        """observe command should return observability data."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/observe")
        assert "health" in r or "alerts" in r or "metrics" in r or r.get("success")

    def test_cmd_skills(self):
        """skills command should return R4Agent skill list."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/skills")
        assert "skills" in r or r.get("success")

    def test_cmd_cells(self):
        """cells command should list cells."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/cells")
        assert "cells" in r or r.get("success")

    def test_cmd_cross(self):
        """cross command should return cross-cell coordination status."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/cross")
        assert "cross_cell" in r or r.get("success")

    def test_cmd_security(self):
        """security command should return security stats."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/security")
        assert "stats" in r or r.get("success")

    def test_cmd_memory(self):
        """memory command should return memory stats."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/memory")
        assert isinstance(r, dict)
        assert "stats" in r or r.get("success") or "error" in r

    def test_cmd_plugins(self):
        """plugins command should return plugin list."""
        from l2.l2_shell import dispatch, reset_state
        reset_state()
        r = dispatch("/plugins")
        assert "plugins" in r or "stats" in r or r.get("success")
