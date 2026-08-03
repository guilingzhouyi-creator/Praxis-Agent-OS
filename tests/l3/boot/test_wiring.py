"""Boot wiring — dependency wiring tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestWiring:
    def test_importable(self):
        from l3.boot.wiring import wire_defaults
        assert callable(wire_defaults)
