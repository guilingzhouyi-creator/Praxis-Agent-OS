"""Scheduler scope — scope-based scheduling tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSchedulerScope:
    def test_importable(self):
        from l3.scheduler.scheduler_scope import ScopeScheduler
        assert callable(ScopeScheduler)
