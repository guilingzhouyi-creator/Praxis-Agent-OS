"""Think registry — scheduled think cycle tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestThinkRegistry:
    def test_importable(self):
        from l3.scheduler.think_registry import ThinkQuotaRegistry

        assert callable(ThinkQuotaRegistry)
