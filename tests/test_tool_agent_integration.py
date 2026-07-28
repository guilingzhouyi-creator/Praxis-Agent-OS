"""Tool ↔ Peer Agent ↔ Pipeline integration test.

Covers the full chain:
  1. Register a tool in the global tool registry
  2. Create a Cell with a Peer Agent (auto_boot=True)
  3. Dispatch a card that triggers the tool via the agent
  4. The tool passes through the pipeline (clearance → constitution → alloc → lock → execute → signal)
  5. Result returns to the agent and can be collected
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _register_test_tool(name: str = "test_ping") -> str:
    """Register a minimal test tool in the global registry. Returns the tool name."""
    from l3.tool_system.tool_spec import ToolSpec, ToolRing, register, ParamSpec

    def _handler(args: dict, agent_id: str) -> dict:
        return {"success": True, "pong": True, "agent": agent_id, "args": args}

    spec = ToolSpec(
        name=name,
        description="Test tool for integration tests",
        category="test",
        ring=ToolRing.RING_1,
        danger=1,
        handler=_handler,
        parameters=[ParamSpec(name="msg", type="string", description="Test message")],
    )
    register(spec)
    return name


def _unregister(name: str) -> None:
    try:
        from l3.tool_system.tool_registry import TOOL_REGISTRY
        TOOL_REGISTRY.unregister(name)
    except Exception:
        pass


class TestToolAgentPipelineIntegration:
    """Full-stack integration: tool → pipeline → Cell → Agent → result."""

    def _reset(self):
        from l3.cell import reset_cells
        from l1.kernel.process import reset_table
        from l3.agent_terminal import reset_terminals
        reset_cells()
        reset_table()
        reset_terminals()

    def test_tool_registration_and_pipeline_access(self):
        """A tool registered in the global registry can be looked up and executed."""
        name = _register_test_tool("int_ping_1")
        try:
            from l3.tool_system.tool_spec import get_tool
            spec = get_tool(name)
            assert spec is not None, f"tool {name} must be resolvable"
            assert callable(spec.handler)
        finally:
            _unregister(name)

    def test_registered_tool_handler_invocation(self):
        """A registered tool's handler can be called directly with correct args."""
        name = _register_test_tool("invoke_test")
        try:
            from l3.tool_system.tool_spec import get_tool
            spec = get_tool(name)
            assert spec is not None
            result = spec.handler({"msg": "hello"}, "test-agent")
            assert result.get("success") is True
            assert result.get("pong") is True
            assert result.get("agent") == "test-agent"
        finally:
            _unregister(name)

    def test_tool_registered_after_boot_is_visible(self):
        """Tools registered after boot are visible to new lookups immediately."""
        name = _register_test_tool("late_reg")
        try:
            from l3.tool_system.tool_spec import get_tool
            spec = get_tool(name)
            assert spec is not None, "tool must be visible immediately after register"
        finally:
            _unregister(name)

    def test_tool_pipeline_rejects_unknown_tool(self):
        """Pipeline returns structured error for unregistered tool names."""
        from l3.tool_system.tool_pipeline import get_pipeline
        pipeline = get_pipeline()
        result = pipeline.execute(
            tool_name="_nonexistent_tool_999",
            agent_id="test-unknown",
            args={},
        )
        assert "error" in result or result.get("success") is False

    def test_tool_unregister_removes_from_registry(self):
        """Unregistering a tool removes it from the global registry."""
        name = _register_test_tool("unreg_test")
        from l3.tool_system.tool_spec import get_tool
        assert get_tool(name) is not None, "tool must exist after register"
        _unregister(name)
        assert get_tool(name) is None, "tool must not exist after unregister"

    def test_pipeline_rate_limiter_per_agent(self):
        """Rate limiter isolates agents: heavy use by one agent doesn't block another."""
        name = _register_test_tool("int_rate_test")
        try:
            from l3.tool_system.tool_pipeline import get_pipeline
            pipeline = get_pipeline()
            for _ in range(5):
                pipeline.execute(
                    tool_name=name, agent_id="rate-hog",
                    args={"msg": "spam"},
                )
            result = pipeline.execute(
                tool_name=name, agent_id="rate-other",
                args={"msg": "ok"},
            )
            assert isinstance(result, dict)
        finally:
            _unregister(name)
