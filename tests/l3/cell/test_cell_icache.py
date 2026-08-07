"""Cell icache — instruction cache tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCellICache:
    def test_importable(self):
        from l3.cell.components.cell_icache import ICache

        assert callable(ICache)
