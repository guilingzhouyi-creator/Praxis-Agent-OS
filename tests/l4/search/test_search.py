"""Search service tests — search and replace functions."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestSearch:
    def test_search_importable(self):
        from l4.search.search import search

        assert callable(search)

    def test_replace_importable(self):
        from l4.search.search import replace

        assert callable(replace)
