"""AgentRuntime tests — lifecycle, tick, status, emit."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestAgentRuntime:
    """AgentRuntime creation and basic API."""

    def test_create_runtime(self):
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="test-agent")
        assert rt.agent_id == "test-agent"
        assert isinstance(rt.territory, list)

    def test_create_with_territory(self):
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="reader", territory=["src/", "docs/"])
        assert rt.agent_id == "reader"
        assert "src/" in rt.territory

    def test_idle_tick(self):
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="idle-agent")
        r = rt.tick()
        assert r.get("success")
        assert r.get("idle")

    def test_status_returns_dict(self):
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="stat-agent")
        st = rt.status()
        assert isinstance(st, dict)
        assert st["agent_id"] == "stat-agent"

    def test_on_registers_handler(self):
        from l1.kernel.event import SignalType
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="handler-agent")
        calls = []

        def handler(sig):
            calls.append(sig)

        rt.on(SignalType.TASK_ASSIGN, handler)
        assert SignalType.TASK_ASSIGN in rt._handlers

    def test_emit_no_error(self):
        from l1.kernel.event import SignalType
        from l5.agent_runtime import AgentRuntime

        rt = AgentRuntime(agent_id="emit-agent")
        rt.emit(SignalType.TASK_ASSIGN, target="cell", data={"msg": "hello"})
        # No assertion needed — just verify no exception
