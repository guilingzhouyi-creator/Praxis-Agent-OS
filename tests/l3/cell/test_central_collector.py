"""CentralCollector — composite/delegation collector tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCentralCollector:
    def test_importable(self):
        from l3.cell.peers.central_collector import CentralCollector

        assert callable(CentralCollector)
