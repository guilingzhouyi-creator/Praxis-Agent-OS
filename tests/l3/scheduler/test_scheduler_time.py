"""Scheduler time — time-based scheduling tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSchedulerTime:
    def test_importable(self):
        from l3.scheduler.scheduler_time import TimeScheduler
        assert callable(TimeScheduler)
