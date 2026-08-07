"""Memory quality tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryQuality:
    def test_importable(self):
        from l3.memory.memory_quality import _score_importance

        assert callable(_score_importance)
