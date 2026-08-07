"""API handler: config tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConfigHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_config import handle_config_list

        assert callable(handle_config_list)
