"""Memory context tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryContext:
    def test_importable(self):
        from l3.memory.memory_context import build_context

        assert callable(build_context)
