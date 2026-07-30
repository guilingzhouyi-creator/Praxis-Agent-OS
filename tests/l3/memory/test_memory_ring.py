"""Memory ring tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryRing:
    def test_importable(self):
        from l3.memory.memory_ring import MemEntry
        assert callable(MemEntry)
