"""Memory cache — FileCache and ContextRegister tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestMemoryCache:
    def test_get_file_cache(self):
        from l3.memory.cache import get_file_cache
        assert callable(get_file_cache)

    def test_get_context_register(self):
        from l3.memory.cache import get_context_register
        assert callable(get_context_register)
