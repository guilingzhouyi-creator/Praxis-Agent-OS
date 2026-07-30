"""API diff handlers — structured diff, history, colors."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestDiffHandlers:
    def test_diff_structured_importable(self):
        from l4.api.api_handlers_diff import diff_structured
        assert callable(diff_structured)

    def test_diff_history_importable(self):
        from l4.api.api_handlers_diff import diff_history
        assert callable(diff_history)

    def test_diff_colors_importable(self):
        from l4.api.api_handlers_diff import diff_colors
        assert callable(diff_colors)
