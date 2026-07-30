"""Agent AI — ai module tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentAI:
    def test_get_service_importable(self):
        from l3.agent.ai import get_service
        assert callable(get_service)

    def test_reset_service_importable(self):
        from l3.agent.ai import reset_service
        assert callable(reset_service)
