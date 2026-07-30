"""Convention — card convention protocol tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConvention:
    def test_importable(self):
        from l3.card.convention import ConventionProtocol
        assert callable(ConventionProtocol)
