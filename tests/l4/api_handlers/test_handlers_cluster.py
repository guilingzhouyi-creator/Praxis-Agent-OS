"""API handler: cluster tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestClusterHandlers:
    def test_importable(self):
        from l4.api_handlers.api_handlers_cluster import cluster_status

        assert callable(cluster_status)
