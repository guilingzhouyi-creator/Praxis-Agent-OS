"""Memory context tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryContext:
    def test_importable(self):
        from l3.memory.context import ContextManager

        assert callable(ContextManager)
