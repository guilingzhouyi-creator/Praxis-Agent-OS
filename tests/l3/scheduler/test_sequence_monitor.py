"""Sequence monitor — n-gram anomaly detection tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSequenceMonitor:
    def test_importable(self):
        from l3.scheduler.sequence_monitor import SequenceMonitor
        assert callable(SequenceMonitor)
