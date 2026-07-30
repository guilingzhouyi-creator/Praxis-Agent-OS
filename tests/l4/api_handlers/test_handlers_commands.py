"""API handler: commands tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestCommandsHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_commands import handle_commands_list
        assert callable(handle_commands_list)
