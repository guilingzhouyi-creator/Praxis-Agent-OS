"""Statecharts — agent state machine tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestStatecharts:
    def test_importable(self):
        from l3.services.statecharts import AgentStatecharts
        assert callable(AgentStatecharts)
