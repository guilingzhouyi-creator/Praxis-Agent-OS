"""Scout — scout agent tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestScout:
    def test_get_pool_importable(self):
        from l3.agent.scout import get_pool
        assert callable(get_pool)

    def test_scout_cache_clear_importable(self):
        from l3.agent.scout import scout_cache_clear
        assert callable(scout_cache_clear)
