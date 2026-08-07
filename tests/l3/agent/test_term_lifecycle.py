"""Agent terminal lifecycle tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestTermLifecycle:
    def test_importable(self):
        from l3.agent._term_lifecycle import run_cache_keepalive

        assert callable(run_cache_keepalive)
