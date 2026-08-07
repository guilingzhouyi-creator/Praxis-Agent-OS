"""Agent terminal handlers tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTermHandlers:
    def test_importable(self):
        from l3.agent._term_handlers import register_action

        assert callable(register_action)
