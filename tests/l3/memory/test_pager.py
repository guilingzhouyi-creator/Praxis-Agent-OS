"""Pager tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestPager:
    def test_importable(self):
        from l3.memory.pager import PageTable
        assert callable(PageTable)
