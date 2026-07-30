"""Cell agent — agent management in cell tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCellAgent:
    def test_add_agent_importable(self):
        from l3.cell.components.cell_agent import add_agent
        assert callable(add_agent)
