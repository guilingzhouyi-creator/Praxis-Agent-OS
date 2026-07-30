"""Result store tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestResultStore:
    def test_importable(self):
        from l3.memory.result_store import get_result_store
        assert callable(get_result_store)
