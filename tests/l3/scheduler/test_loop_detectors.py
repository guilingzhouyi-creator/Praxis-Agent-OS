"""Loop detectors — tool loop detection tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestLoopDetectors:
    def test_importable(self):
        from l3.scheduler.loop_detectors import ToolLoopDetector

        assert callable(ToolLoopDetector)
