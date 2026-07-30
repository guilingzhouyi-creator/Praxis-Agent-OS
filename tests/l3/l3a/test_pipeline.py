"""L3A — pipeline (managed tool output / oversized tool result spill) tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3APipeline:
    def test_importable(self):
        from l3.cell.peers.l3a.pipeline import bound
        assert callable(bound)
