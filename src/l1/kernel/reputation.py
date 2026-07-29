"""Kernel reputation system — agent trust scores for GateChain G5.

Each agent has a reputation score [0.0, 1.0] updated by:
  - task outcomes (success/failure)
  - cross-review results (approved/rejected changes)
  - dispute outcomes (upheld/dismissed)

Used by GateChain G5 for composite judgment:
  reputation >= 0.9 → high-reputation pass (tolerates G3 warn)
  reputation 0.7-0.9 → report to L3
  reputation < 0.7 → block on escalation
"""

from __future__ import annotations

import logging
import threading
import time

from l1.kernel.params.agent import (
    REP_DEFAULT_REPUTATION,
    REP_MIN,
    REP_MAX,
    REP_TASK_SUCCESS,
    REP_TASK_FAILURE,
    REP_REVIEW_APPROVED,
    REP_REVIEW_REJECTED,
    REP_DISPUTE_UPHELD,
    REP_DISPUTE_DISMISSED,
)

logger = logging.getLogger(__name__)


class ReputationSystem:
    """Kernel-level agent reputation storage and updates."""

    def __init__(self):
        self._reputations: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, agent_id: str) -> float:
        """Return the current reputation score for the given agent."""
        with self._lock:
            return self._reputations.get(agent_id, REP_DEFAULT_REPUTATION)

    def set(self, agent_id: str, score: float) -> None:
        """Set the agent's reputation score, clamped to the valid range."""
        clamped = max(REP_MIN, min(REP_MAX, score))
        with self._lock:
            self._reputations[agent_id] = clamped

    def adjust(self, agent_id: str, delta: float) -> float:
        """Apply a delta to the agent's reputation and return the new score."""
        with self._lock:
            current = self._reputations.get(agent_id, REP_DEFAULT_REPUTATION)
            new = max(REP_MIN, min(REP_MAX, current + delta))
            self._reputations[agent_id] = new
            return new

    def record_task(self, agent_id: str, success: bool) -> float:
        """Record a task outcome and return the agent's updated reputation."""
        return self.adjust(agent_id, REP_TASK_SUCCESS if success else REP_TASK_FAILURE)

    def record_review(self, agent_id: str, approved: bool) -> float:
        """Record a cross-review outcome and return the updated reputation."""
        return self.adjust(agent_id, REP_REVIEW_APPROVED if approved else REP_REVIEW_REJECTED)

    def record_dispute(self, agent_id: str, upheld: bool) -> float:
        """Record a dispute outcome and return the updated reputation."""
        return self.adjust(agent_id, REP_DISPUTE_UPHELD if upheld else REP_DISPUTE_DISMISSED)

    def all(self) -> dict[str, float]:
        """Return a snapshot of all agent reputation scores."""
        with self._lock:
            return dict(self._reputations)


_reputation: ReputationSystem | None = None


def get_reputation() -> ReputationSystem:
    """Return the singleton ReputationSystem instance, creating it if needed."""
    global _reputation
    if _reputation is None:
        _reputation = ReputationSystem()
    return _reputation


def reset_reputation() -> None:
    """Reset the singleton ReputationSystem back to None."""
    global _reputation
    _reputation = None
