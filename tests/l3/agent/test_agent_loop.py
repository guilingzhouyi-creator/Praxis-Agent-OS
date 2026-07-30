"""Agent loop tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentLoop:
    def test_importable(self):
        from l3.agent.agent_loop import AgentLoop
        assert callable(AgentLoop)
