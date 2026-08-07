"""API handler: monitor tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestMonitorHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_monitor import handle_monitor_events

        assert callable(handle_monitor_events)
