"""Stagnation detection — detects agent execution deadlocks and loops.

Four patterns:

  SPINNING:          Same output repeated identically (same hash)
  OSCILLATION:       A→B→A→B alternating output pattern
  NO_DRIFT:          Progress score remains flat across iterations
  DIMINISHING_RETURNS: Each iteration makes less progress than the last

Integrates with kernel/interrupt to fire STAGNATION_DETECTED interrupts
and with ops_console for alerting.

Usage:
  from l3.agent.stagnation import StagnationDetector
  sd = StagnationDetector()
  sd.record("agent-x", "iteration 1 output...", progress=0.3)
  sd.record("agent-x", "iteration 2 output...", progress=0.35)
  result = sd.check("agent-x")  # {"stagnant": True, "pattern": "NO_DRIFT", ...}
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from l1.kernel.params.kernel import (
    STAGNATION_DIMINISHING_RATE,
    STAGNATION_MAX_ITERATIONS,
    STAGNATION_NO_DRIFT_EPSILON,
    STAGNATION_SPIN_THRESHOLD,
)
from l1.kernel.params.system import HASH_TRUNC_LONG, HASH_TRUNC_SHORT

logger = logging.getLogger(__name__)


@staticmethod
def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:HASH_TRUNC_LONG]


class StagnationDetector:
    """Detects agent execution stagnation patterns."""

    def __init__(self):
        self._agents: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._total_stagnations = 0

    def record(self, agent_id: str, output: str, progress: float = 0.0,
               iteration: int = 0) -> None:
        """Record an iteration output for an agent."""
        with self._lock:
            state = self._agents.setdefault(agent_id, {
                "history": [],        # list of content hashes
                "progress": [],       # list of progress scores
                "hash_set": set(),    # for spin detection
                "last_check": None,
            })
            h = _content_hash(output)
            state["history"].append(h)
            state["hash_set"].add(h)
            state["progress"].append(progress)
            state["last_check"] = None

    def check(self, agent_id: str) -> dict:
        """Check if an agent is stagnant.

        Returns:
          {"stagnant": False}
          or {"stagnant": True, "pattern": "SPINNING", "details": {...}}
        """
        with self._lock:
            state = self._agents.get(agent_id)
            if not state:
                return {"stagnant": False}
            history = state["history"]
            progress = state["progress"]

            # Only check every N iterations
            if len(history) < 3:
                return {"stagnant": False}

            state["last_check"] = time.time()

            # 1. SPINNING — same hash repeated
            if len(history) >= STAGNATION_SPIN_THRESHOLD:
                last_n = history[-STAGNATION_SPIN_THRESHOLD:]
                if len(set(last_n)) == 1:
                    self._total_stagnations += 1
                    self._fire(agent_id, "SPINNING",
                               f"same output repeated {STAGNATION_SPIN_THRESHOLD}x: {last_n[0]}")
                    return {"stagnant": True, "pattern": "SPINNING",
                            "hash": last_n[0], "count": STAGNATION_SPIN_THRESHOLD}

            # 2. OSCILLATION — A→B→A→B pattern
            if len(history) >= 4:
                last_4 = history[-4:]
                if last_4[0] == last_4[2] and last_4[1] == last_4[3] and last_4[0] != last_4[1]:
                    self._total_stagnations += 1
                    self._fire(agent_id, "OSCILLATION",
                               f"A→B→A→B pattern: {last_4[0][:HASH_TRUNC_SHORT]}↔{last_4[1][:HASH_TRUNC_SHORT]}")
                    return {"stagnant": True, "pattern": "OSCILLATION",
                            "hash_a": last_4[0], "hash_b": last_4[1]}

            # 3. NO_DRIFT — progress flat
            if len(progress) >= 3:
                recent = progress[-3:]
                if max(recent) - min(recent) < STAGNATION_NO_DRIFT_EPSILON:
                    self._total_stagnations += 1
                    self._fire(agent_id, "NO_DRIFT",
                               f"progress flat: {recent}")
                    return {"stagnant": True, "pattern": "NO_DRIFT",
                            "recent_progress": recent}

            # 4. DIMINISHING_RETURNS — each step makes less progress
            if len(progress) >= 4:
                deltas = [progress[i+1] - progress[i] for i in range(len(progress)-1)]
                recent_deltas = deltas[-3:]
                if all(d < STAGNATION_DIMINISHING_RATE for d in recent_deltas) and all(d >= 0 for d in recent_deltas):
                    self._total_stagnations += 1
                    self._fire(agent_id, "DIMINISHING_RETURNS",
                               f"progress deltas: {[round(d, 3) for d in recent_deltas]}")
                    return {"stagnant": True, "pattern": "DIMINISHING_RETURNS",
                            "deltas": recent_deltas}

            # 5. MAX_ITERATIONS hard cap
            if len(history) >= STAGNATION_MAX_ITERATIONS:
                self._total_stagnations += 1
                self._fire(agent_id, "MAX_ITERATIONS",
                           f"hit hard cap of {STAGNATION_MAX_ITERATIONS}")
                return {"stagnant": True, "pattern": "MAX_ITERATIONS",
                        "iterations": len(history)}

            return {"stagnant": False}

    def _fire(self, agent_id: str, pattern: str, reason: str) -> None:
        """Fire stagnation interrupt and log."""
        try:
            from l1.kernel.interrupt import InterruptType, fire
            fire(InterruptType.DEADLOCK_DETECTED, agent_id=agent_id,
                 reason=f"[{pattern}] {reason}")
        except Exception as e:
            logger.warning("stagnation check: %s", e)
        logger.warning("Stagnation [%s] %s: %s", pattern, agent_id, reason)

    def clear(self, agent_id: str) -> None:
        """Clear all stored detection state."""
        with self._lock:
            self._agents.pop(agent_id, None)

    def stats(self) -> dict:
        """Return stagnation detection statistics."""
        with self._lock:
            return {
                "tracked_agents": len(self._agents),
                "total_stagnations": self._total_stagnations,
            }

    def break_loop(self, agent_id: str, result: dict) -> dict:
        """Generate actionable break instructions when a loop is detected.

        Returns:
            {"should_break": True, "action": "skip|escalate|switch", "reason": "..."}
        """
        pattern = result.get("pattern", "")
        if pattern == "SPINNING":
            return {"should_break": True, "action": "skip",
                    "reason": f"same output repeated, skipping current tool for {agent_id}"}
        if pattern == "OSCILLATION":
            return {"should_break": True, "action": "switch",
                    "reason": f"A↔B oscillation detected, switching strategy for {agent_id}"}
        if pattern in ("NO_DRIFT", "DIMINISHING_RETURNS"):
            return {"should_break": True, "action": "escalate",
                    "reason": f"no progress ({pattern}), escalating for {agent_id}"}
        if pattern == "MAX_ITERATIONS":
            return {"should_break": True, "action": "escalate",
                    "reason": f"hit max iterations ({result.get('iterations', '?')})"}
        return {"should_break": False, "action": "", "reason": ""}


_detector: StagnationDetector | None = None


def get_detector() -> StagnationDetector:
    """Get the singleton StagnationDetector instance."""
    global _detector
    if _detector is None:
        _detector = StagnationDetector()
    return _detector


def reset_detector() -> None:
    """Reset the singleton StagnationDetector (for testing)."""
    global _detector
    _detector = None
