"""ApprovalGate — approval gate tests."""

from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestApprovalGate:
    def test_importable(self):
        from l3.card.approval_gate import ApprovalGate
        assert callable(ApprovalGate)
