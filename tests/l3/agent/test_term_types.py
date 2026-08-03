"""Agent terminal types tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTermTypes:
    def test_importable(self):
        from l3.agent._term_types import TerminalCard
        assert callable(TerminalCard)
