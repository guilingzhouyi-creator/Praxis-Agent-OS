"""Counter — tool call counting service tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCounter:
    """Counter service — record_tool, stats."""

    def test_get_counter(self):
        from l3.services.counter import get_counter

        c = get_counter()
        assert c is not None

    def test_record_tool(self):
        from l3.services.counter import get_counter

        c = get_counter()
        c.record_tool("agent-a", "read_file", success=True)
        summary = c.tool_summary()
        assert isinstance(summary, dict)
