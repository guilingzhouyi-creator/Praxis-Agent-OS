"""L3A — API routing tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AApi:
    def test_importable(self):
        from l3.cell.peers.l3a.api import dispatch
        assert callable(dispatch)
