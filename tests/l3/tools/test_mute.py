"""Tests for tool mute/disable system."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestToolMute:
    def test_mute_unmute_tool(self):
        from l3.tool_system.tool_spec import mute_tool, unmute_tool, is_muted, clear_mutes
        clear_mutes()
        mute_tool("run_in_terminal")
        assert is_muted("run_in_terminal")
        unmute_tool("run_in_terminal")
        assert not is_muted("run_in_terminal")

    def test_mute_category(self):
        from l3.tool_system.tool_spec import mute_category, unmute_category, is_muted, clear_mutes
        from l3.tool_system.tool_spec import register, ToolSpec
        clear_mutes()
        spec = ToolSpec(name="test_net_tool", description="test", category="network",
                        ring="ring_1", danger=0, handler=lambda a, b: {"ok": True})
        register(spec)
        mute_category("network")
        assert is_muted("test_net_tool")
        unmute_category("network")
        assert not is_muted("test_net_tool")

    def test_mute_ring(self):
        from l3.tool_system.tool_spec import mute_ring, unmute_ring, is_muted, clear_mutes
        from l3.tool_system.tool_spec import register, ToolSpec
        clear_mutes()
        spec = ToolSpec(name="test_danger_tool", description="test", category="generic",
                        ring="ring_3", danger=5, handler=lambda a, b: {"ok": True})
        register(spec)
        mute_ring("ring_3")
        assert is_muted("test_danger_tool")
        unmute_ring("ring_3")
        assert not is_muted("test_danger_tool")

    def test_execute_muted_returns_error(self):
        from l3.tool_system.tool_spec import mute_tool, clear_mutes, execute_tool_spec
        from l3.tool_system.tool_spec import register, ToolSpec
        clear_mutes()
        def handler(args, agent):
            return {"success": True, "data": "ok"}
        spec = ToolSpec(name="test_mutable", description="test", category="generic",
                        ring="ring_1", danger=0, handler=handler)
        register(spec)
        r = execute_tool_spec("test_mutable", {}, "agent")
        assert r.get("success")
        mute_tool("test_mutable")
        r = execute_tool_spec("test_mutable", {}, "agent")
        assert not r.get("success")
        assert r.get("muted")

    def test_list_muted(self):
        from l3.tool_system.tool_spec import mute_tool, mute_category, clear_mutes, list_muted
        clear_mutes()
        mute_tool("foo")
        mute_category("bar")
        result = list_muted()
        assert "foo" in result["tools"]
        assert "bar" in result["categories"]
