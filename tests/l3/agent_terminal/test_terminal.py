"""AgentTerminal — lifecycle, dispatch, status tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestAgentTerminal:
    def test_create_terminal(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="test-agent", role="reader", cell_id="cell-1")
        assert term.agent_id == "test-agent"
        assert term.role == "reader"
        assert term.cell_id == "cell-1"
        assert term._running is False

    def test_status_report(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="stat-agent")
        r = term.status_report()
        assert r["agent_id"] == "stat-agent"
        assert "status" in r

    def test_session_reachable_not_running(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="reach-agent")
        r = term.session_reachable()
        assert r.get("reachable") is False
        assert "not_running" in r.get("reason", "")

    def test_set_mode_valid(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="mode-agent")
        r = term.set_mode("assembly")
        assert r.get("success")

    def test_set_mode_invalid(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="mode-agent-2")
        r = term.set_mode("bogus")
        assert not r.get("success")

    def test_pause_resume(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="pause-agent")
        r = term.pause()
        assert r.get("success")
        assert term._paused
        r2 = term.resume()
        assert r2.get("success")
        assert not term._paused

    def test_shutdown(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="sd-agent")
        r = term.shutdown()
        assert r.get("success")
        assert r["agent_id"] == "sd-agent"

    def test_set_card_timeout(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="timeout-agent")
        r = term.set_card_timeout(30.0)
        assert r.get("success")
        assert term._card_timeout == 30.0

    def test_set_persistent_loop(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="loop-agent")
        r = term.set_persistent_loop(True)
        assert r.get("success")
        assert term._persistent_loop

    def test_reset_persistent_loop(self):
        from l3.agent_terminal import AgentTerminal

        term = AgentTerminal(agent_id="loop-agent-2")
        r = term.reset_persistent_loop()
        assert r.get("success")
