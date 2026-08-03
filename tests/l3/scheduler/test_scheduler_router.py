"""Scheduler router — L3Router and RequestPool tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSchedulerRouter:
    def test_importable(self):
        from l3.scheduler.scheduler_router import L3Router
        assert callable(L3Router)
