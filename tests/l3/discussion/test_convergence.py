"""Convergence tests — converge function, execution card conversion."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


class TestConvergence:
    def test_converge_unknown_card(self):
        from l3.agent.convergence import converge
        r = converge("nonexistent")
        assert not r.get("success")
        assert "unknown" in r.get("error", "")

    def test_to_execution_card(self):
        from l3.agent.convergence import to_execution_card
        from l3.card.issue import IssueCard
        issue = IssueCard(intent="test intent", domain="app/routes", agent_ids=["a"])
        card = to_execution_card(issue, summary="test convergence")
        assert card is not None
        # CardUnified: intent is in summary.title
        assert card.summary.title.startswith("test")
