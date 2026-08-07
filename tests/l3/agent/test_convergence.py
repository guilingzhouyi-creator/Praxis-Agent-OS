"""Convergence tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConvergence:
    def test_importable(self):
        from l3.agent.convergence import converge

        assert callable(converge)

    def test_to_execution_card_importable(self):
        from l3.agent.convergence import to_execution_card

        assert callable(to_execution_card)
