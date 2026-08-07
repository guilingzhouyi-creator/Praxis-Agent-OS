"""Agent terminal convention tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTermConvention:
    def test_importable(self):
        from l3.agent._term_convention import convention_handler

        assert callable(convention_handler)
