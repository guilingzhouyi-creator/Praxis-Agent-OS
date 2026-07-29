"""Tests for tool_registry.py — Tool registry, mute system, plugin registration."""
from __future__ import annotations

import pytest
from l3.tool_registry import (
    TOOL_REGISTRY, register, get_tool, list_tools,
    mute_tool, unmute_tool, is_muted, list_muted, clear_mutes,
    register_plugin, unregister_plugin, register_middleware,
)


@pytest.fixture(autouse=True)
def cleanup():
    clear_mutes()
    yield


def test_register_and_get_tool():
    """A tool can be registered and retrieved by name."""
    from l3.tool_params import ToolSpec
    spec = ToolSpec(name="test_tool", category="test")
    register(spec)
    assert get_tool("test_tool") is spec


def test_get_tool_not_found():
    """get_tool returns None for unregistered tools."""
    assert get_tool("nonexistent_tool") is None


def test_mute_tool():
    """A muted tool is recognized as muted."""
    mute_tool("dangerous_tool")
    assert is_muted("dangerous_tool") is True


def test_unmute_tool():
    """An unmuted tool is not recognized as muted."""
    mute_tool("temp_mute")
    unmute_tool("temp_mute")
    assert is_muted("temp_mute") is False


def test_list_muted():
    """list_muted returns a dict with muted tool names."""
    mute_tool("tool_a")
    mute_tool("tool_b")
    muted = list_muted()
    assert "tool_a" in muted["tools"]
    assert "tool_b" in muted["tools"]


def test_clear_mutes():
    """clear_mutes removes all muted entries."""
    mute_tool("tool_x")
    clear_mutes()
    assert is_muted("tool_x") is False


def test_register_plugin():
    """A plugin can register multiple tools at once."""
    from l3.tool_params import ToolSpec
    tools = [
        ToolSpec(name="plugin_tool_1", plugin="test_plugin"),
        ToolSpec(name="plugin_tool_2", plugin="test_plugin"),
    ]
    register_plugin("test_plugin", tools)
    assert get_tool("plugin_tool_1") is not None
    assert get_tool("plugin_tool_2") is not None


def test_unregister_plugin():
    """Unregistering a plugin removes all its tools."""
    from l3.tool_params import ToolSpec
    tools = [ToolSpec(name="removable_tool", plugin="temp_plugin")]
    register_plugin("temp_plugin", tools)
    unregister_plugin("temp_plugin")
    assert get_tool("removable_tool") is None


def test_register_middleware():
    """Middleware can be registered without error."""
    def dummy_hook(tool_name, args, agent_id):
        return args
    register_middleware("pre", "test_mw", dummy_hook)
    from l3.tool_registry import _MIDDLEWARE
    assert any(m["name"] == "test_mw" for m in _MIDDLEWARE)
