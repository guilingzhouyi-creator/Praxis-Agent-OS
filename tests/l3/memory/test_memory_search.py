"""Memory search tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemorySearch:
    def test_importable(self):
        from l3.memory.memory_search import search_long_term
        assert callable(search_long_term)
