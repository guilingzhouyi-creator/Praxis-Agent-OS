"""Cache document store tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCacheDoc:
    def test_importable(self):
        from l3.memory.cache_doc import CacheDocumentStore
        assert callable(CacheDocumentStore)
