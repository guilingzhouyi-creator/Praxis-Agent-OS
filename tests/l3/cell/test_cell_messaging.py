"""Cell messaging tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCellMessaging:
    def test_importable(self):
        from l3.cell.components.cell_messaging import CellMessagingMixin
        assert callable(CellMessagingMixin)
