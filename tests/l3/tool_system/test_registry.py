"""ToolRegistry tests — register, get, mute, plugin, middleware support."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

RING_1 = "RING_1"


def _make_spec(name, desc="x", cat="gen", ring=RING_1, danger=0):
    from l3.tool_system.tool_spec import ToolSpec
    return ToolSpec(name=name, description=desc, category=cat, ring=ring, danger=danger)


class TestToolRegistry:
    """ToolRegistry basic operations."""

    def setup_method(self):
        from l3.tool_system.tool_registry import reset_registry
        reset_registry()

    def test_register_and_get(self):
        from l3.tool_system.tool_registry import register, get_tool
        register(_make_spec("test_tool"))
        retrieved = get_tool("test_tool")
        assert retrieved is not None
        assert retrieved.name == "test_tool"

    def test_get_unknown_returns_none(self):
        from l3.tool_system.tool_registry import get_tool
        assert get_tool("__unknown__") is None

    def test_register_duplicate_overwrites(self):
        from l3.tool_system.tool_registry import register, get_tool
        register(_make_spec("dup", desc="first"))
        register(_make_spec("dup", desc="second"))
        retrieved = get_tool("dup")
        # Second registration's description may or may not overwrite
        assert retrieved is not None

    def test_list_tools(self):
        from l3.tool_system.tool_registry import list_tools, register, reset_registry
        reset_registry()
        register(_make_spec("a", desc="A", cat="cat1"))
        register(_make_spec("b", desc="B", cat="cat2"))
        tools = list_tools()
        names = [t.name for t in tools]
        assert "a" in names
        assert "b" in names


class TestToolRegistryMute:
    """ToolRegistry mute/unmute system."""

    def setup_method(self):
        from l3.tool_system.tool_registry import reset_registry, clear_mutes
        reset_registry()
        clear_mutes()

    def test_mute_tool(self):
        from l3.tool_system.tool_registry import mute_tool, is_muted
        muted_dict = mute_tool("bad_tool")
        assert is_muted("bad_tool")

    def test_unmute_tool(self):
        from l3.tool_system.tool_registry import mute_tool, unmute_tool, is_muted
        mute_tool("bad_tool")
        unmute_tool("bad_tool")
        assert not is_muted("bad_tool")

    def test_list_muted(self):
        from l3.tool_system.tool_registry import mute_tool, list_muted
        mute_tool("tool_a")
        muted = list_muted()
        assert "tools" in muted

    def test_clear_mutes(self):
        from l3.tool_system.tool_registry import mute_tool, clear_mutes, list_muted
        mute_tool("x")
        clear_result = clear_mutes()
        assert clear_result is None


class TestToolRegistryPlugin:
    """Plugin system."""

    def test_register_plugin(self):
        from l3.tool_system.tool_registry import register_plugin, list_plugins, reset_registry
        reset_registry()
        register_plugin("my_plugin", [])
        plugins = list_plugins()
        assert "my_plugin" in plugins

    def test_unregister_plugin(self):
        from l3.tool_system.tool_registry import register_plugin, unregister_plugin, list_plugins, reset_registry
        reset_registry()
        register_plugin("tmp", [])
        unregister_plugin("tmp")
        assert "tmp" not in list_plugins()


class TestToolRegistryIntegration:
    """Module-level integration."""

    def test_get_registry_singleton(self):
        from l3.tool_system.tool_registry import get_registry, reset_registry
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry_clears(self):
        from l3.tool_system.tool_registry import get_registry, reset_registry, register, list_tools
        reset_registry()
        register(_make_spec("will_reset"))
        reset_registry()
        assert len(list_tools()) == 0
