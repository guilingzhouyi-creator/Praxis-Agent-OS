"""L3A — archive store/restore tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestL3AArchive:
    def test_importable(self):
        from l3.cell.peers.l3a.archive import store_session

        assert callable(store_session)
