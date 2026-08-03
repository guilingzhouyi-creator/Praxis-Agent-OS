"""CentralController — L3A + L3B + CardRegistry orchestration tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


class TestCentralController:
    def test_get_coordinator_importable(self):
        from l3.cell.peers.l3 import get_coordinator
        assert callable(get_coordinator)

    def test_central_controller_importable(self):
        from l3.cell.peers.l3 import CentralController
        assert callable(CentralController)
