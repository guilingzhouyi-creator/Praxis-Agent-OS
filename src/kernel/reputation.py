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

logger = logging.getLogger(__name__)

DEFAULT_REPUTATION = 0.85
REP_MIN = 0.0
REP_MAX = 1.0
REP_TASK_SUCCESS = 0.02
REP_TASK_FAILURE = -0.05
REP_REVIEW_APPROVED = 0.01
REP_REVIEW_REJECTED = -0.03
REP_DISPUTE_UPHELD = 0.03
REP_DISPUTE_DISMISSED = -0.02


class ReputationSystem:
    """Kernel-level agent reputation storage and updates."""

    def __init__(self):
        self._reputations: dict[str, float] = {}
        self._lock = threading.Lock()

    def get(self, agent_id: str) -> float:
        with self._lock:
            return self._reputations.get(agent_id, DEFAULT_REPUTATION)

    def set(self, agent_id: str, score: float) -> None:
        clamped = max(REP_MIN, min(REP_MAX, score))
        with self._lock:
            self._reputations[agent_id] = clamped

    def adjust(self, agent_id: str, delta: float) -> float:
        with self._lock:
            current = self._reputations.get(agent_id, DEFAULT_REPUTATION)
            new = max(REP_MIN, min(REP_MAX, current + delta))
            self._reputations[agent_id] = new
            return new

    def record_task(self, agent_id: str, success: bool) -> float:
        return self.adjust(agent_id, REP_TASK_SUCCESS if success else REP_TASK_FAILURE)

    def record_review(self, agent_id: str, approved: bool) -> float:
        return self.adjust(agent_id, REP_REVIEW_APPROVED if approved else REP_REVIEW_REJECTED)

    def record_dispute(self, agent_id: str, upheld: bool) -> float:
        return self.adjust(agent_id, REP_DISPUTE_UPHELD if upheld else REP_DISPUTE_DISMISSED)

    def all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._reputations)


_reputation: ReputationSystem | None = None


def get_reputation() -> ReputationSystem:
    global _reputation
    if _reputation is None:
        _reputation = ReputationSystem()
    return _reputation


def reset_reputation() -> None:
    global _reputation
    _reputation = None
