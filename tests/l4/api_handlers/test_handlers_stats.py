"""API handler: stats tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestStatsHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_stats import handle_stats_query
        assert callable(handle_stats_query)
