"""Scheduler core — agent scheduling tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestScheduler:
    def test_importable(self):
        from l3.scheduler.scheduler import Scheduler

        assert callable(Scheduler)

    def test_get_scheduler_importable(self):
        from l3.scheduler.scheduler import get_scheduler

        assert callable(get_scheduler)
