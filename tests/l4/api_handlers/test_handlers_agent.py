"""API handler: agent config tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestAgentHandlers:
    def test_handle_agent_config_get_importable(self):
        from l4.api_handlers.api_handlers_agent import handle_agent_config_get

        assert callable(handle_agent_config_get)

    def test_handle_agent_config_set_importable(self):
        from l4.api_handlers.api_handlers_agent import handle_agent_config_set

        assert callable(handle_agent_config_set)
