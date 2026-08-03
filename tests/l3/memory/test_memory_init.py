"""Memory init tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryInit:
    def test_snapshot_path_importable(self):
        from l3.memory.memory_init import _snapshot_path
        assert callable(_snapshot_path)
