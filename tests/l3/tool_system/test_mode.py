"""ToolMode tests — mode get/set/init."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestToolMode:
    """Tool mode get/set/reset."""

    def test_get_mode_returns_string(self):
        from l3.tool_system.tool_mode import get_mode, init_tool_mode

        init_tool_mode()
        mode = get_mode()
        assert isinstance(mode, str)

    def test_set_mode(self):
        from l3.tool_system.tool_mode import get_mode, init_tool_mode, set_mode

        init_tool_mode()
        prev = get_mode()
        set_mode("read")
        assert get_mode() == "read"
        set_mode(prev)

    def test_init_tool_mode_returns_dict(self):
        from l3.tool_system.tool_mode import init_tool_mode

        result = init_tool_mode()
        assert isinstance(result, dict)
        assert "mode" in result
