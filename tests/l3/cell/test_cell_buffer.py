"""Cell buffer tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCellBuffer:
    def test_importable(self):
        from l3.cell.components.cell_buffer import CircularBuffer

        assert callable(CircularBuffer)
