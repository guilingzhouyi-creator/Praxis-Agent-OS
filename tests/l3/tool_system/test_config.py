"""ToolConfig — configuration loading, query, derived sets tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestToolConfigBasics:
    """ToolConfig classmethods (config may be empty in test env)."""

    def test_all_returns_list(self):
        from l3.tool_system.tool_config import ToolConfig
        tools = ToolConfig.all()
        assert isinstance(tools, list)

    def test_write_tool_names_returns_frozenset(self):
        from l3.tool_system.tool_config import ToolConfig
        names = ToolConfig.write_tool_names()
        assert isinstance(names, frozenset)

    def test_terminal_tool_names(self):
        from l3.tool_system.tool_config import ToolConfig
        names = ToolConfig.terminal_tool_names()
        assert isinstance(names, frozenset)

    def test_file_tool_names(self):
        from l3.tool_system.tool_config import ToolConfig
        names = ToolConfig.file_tool_names()
        assert isinstance(names, frozenset)

    def test_completions_returns_dict(self):
        from l3.tool_system.tool_config import ToolConfig
        comp = ToolConfig.completions()
        assert isinstance(comp, dict)

    def test_for_llm(self):
        from l3.tool_system.tool_config import ToolConfig
        tools = ToolConfig.all()
        result = ToolConfig.for_llm(tools[:3] if tools else [])
        assert isinstance(result, list)
