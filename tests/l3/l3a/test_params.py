"""L3A — params (structural constants) tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AParams:
    def test_importable(self):
        import l3.cell.peers.l3a.params as _p
        assert _p is not None
