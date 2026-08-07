"""Verify cadence tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestVerifyCadence:
    def test_importable(self):
        from l3.agent.verify_cadence import VerifyCadence

        assert callable(VerifyCadence)
