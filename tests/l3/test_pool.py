"""L3 pool base tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class TestL3Pool:
    def test_importable(self):
        from l3._pool import WorkerPool

        assert callable(WorkerPool)
