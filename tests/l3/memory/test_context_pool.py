"""Context pool tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestContextPool:
    def test_importable(self):
        from l3.memory.context_pool import get
        assert callable(get)
