"""L3A — types (shared enums and dataclasses) tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3ATypes:
    def test_importable(self):
        from l3.cell.peers.l3a.types import CardType
        assert callable(CardType)
