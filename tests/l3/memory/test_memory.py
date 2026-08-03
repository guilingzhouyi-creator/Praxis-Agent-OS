"""Memory core tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemory:
    def test_get_memory_importable(self):
        from l3.memory.memory import get_memory
        assert callable(get_memory)
