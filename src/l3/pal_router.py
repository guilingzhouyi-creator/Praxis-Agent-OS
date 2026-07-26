"""PAL Router — Progressive Adaptive LLM routing with cost optimization.

Three tiers with auto-escalation on failure and auto-downgrade on success.
Tier selection is based on task complexity scoring.

Usage:
  from l3.pal_router import get_router
  router = get_router()
  tier = router.select("analyze codebase", tools=5, depth=3)
  router.record_outcome("analyze codebase", tier, success=True)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any

from l1.kernel.params.api import (
    PAL_FRUGAL_COST,
    PAL_STANDARD_COST,
    PAL_FRONTIER_COST,
    PAL_FRUGAL_THRESHOLD,
    PAL_STANDARD_THRESHOLD,
    PAL_ESCALATE_AFTER,
    PAL_DOWNGRADE_AFTER,
    PAL_DEFAULT_TIER,
)

logger = logging.getLogger(__name__)

TIERS = ("frugal", "standard", "frontier")
TIER_COST = {"frugal": PAL_FRUGAL_COST, "standard": PAL_STANDARD_COST, "frontier": PAL_FRONTIER_COST}


def complexity_score(tokens: int = 0, tools: int = 0, depth: int = 0) -> float:
    """Score task complexity (0.0–1.0)."""
    norm_tokens = min(tokens / 4000, 1.0)
    norm_tools = min(tools / 5, 1.0)
    norm_depth = min(depth / 5, 1.0)
    return 0.30 * norm_tokens + 0.30 * norm_tools + 0.40 * norm_depth


def complexity_to_tier(score: float) -> str:
    if score < PAL_FRUGAL_THRESHOLD:
        return "frugal"
    if score < PAL_STANDARD_THRESHOLD:
        return "standard"
    return "frontier"


class PALRouter:
    """Progressive Adaptive LLM Router — cost-optimized tier selection."""

    def __init__(self):
        self._pattern_history: dict[str, dict] = {}  # pattern_hash → {tier, failures, successes}
        self._lock = threading.Lock()
        self._total_calls = 0
        self._total_cost = 0
        self._escalations = 0
        self._downgrades = 0

    def _pattern_key(self, task_description: str) -> str:
        """Hash task into a similarity pattern key."""
        norm = task_description.strip().lower()
        return hashlib.sha256(norm.encode()).hexdigest()[:16]

    def _jaccard_similarity(self, a: str, b: str) -> float:
        """Compare two task descriptions for pattern matching."""
        set_a = set(a.strip().lower().split()[:20])
        set_b = set(b.strip().lower().split()[:20])
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def select(self, task: str, tools: int = 0, depth: int = 0,
               tokens: int = 0, prefer_tier: str = "") -> str:
        """Select the optimal tier for a task.

        Args:
            task: task description (used for pattern matching across calls)
            tools: number of tools potentially needed
            depth: execution/AC nesting depth
            tokens: estimated token count
            prefer_tier: override tier (e.g. "frontier" for critical tasks)

        Returns: "frugal" | "standard" | "frontier"
        """
        if prefer_tier in TIERS:
            return prefer_tier

        # Score fresh complexity
        score = complexity_score(tokens, tools, depth)
        tier = complexity_to_tier(score)

        # Check pattern history for inherited preference
        pkey = self._pattern_key(task)
        with self._lock:
            for existing_key, entry in list(self._pattern_history.items()):
                if self._jaccard_similarity(task, existing_key) >= 0.80:
                    tier = entry.get("tier", tier)
                    break

            self._pattern_history.setdefault(pkey, {"tier": tier, "failures": 0, "successes": 0,
                                                      "last_seen": time.time()})
            self._total_calls += 1
            self._total_cost += TIER_COST.get(tier, 1)

        return tier

    def record_outcome(self, task: str, tier: str, success: bool) -> None:
        """Record task outcome for auto-escalation/downgrade.

        On consecutive failures: escalate tier (frugal→standard→frontier)
        On consecutive successes: downgrade tier (frontier→standard→frugal)
        """
        pkey = self._pattern_key(task)
        with self._lock:
            entry = self._pattern_history.get(pkey)
            if not entry:
                return

            entry["last_seen"] = time.time()

            if success:
                entry["successes"] += 1
                entry["failures"] = 0
                # Downgrade after sustained success
                if entry["successes"] >= PAL_DOWNGRADE_AFTER:
                    current = TIERS.index(entry["tier"])
                    if current > 0:
                        entry["tier"] = TIERS[current - 1]
                        entry["successes"] = 0
                        self._downgrades += 1
                        logger.info("PAL downgraded %s→%s (%s)", TIERS[current], entry["tier"], task[:40])
            else:
                entry["failures"] += 1
                entry["successes"] = 0
                # Escalate after consecutive failures
                if entry["failures"] >= PAL_ESCALATE_AFTER:
                    current = TIERS.index(entry["tier"])
                    if current < len(TIERS) - 1:
                        entry["tier"] = TIERS[current + 1]
                        entry["failures"] = 0
                        self._escalations += 1
                        logger.info("PAL escalated %s→%s (%s)", TIERS[current], entry["tier"], task[:40])

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_calls": self._total_calls,
                "total_cost_units": self._total_cost,
                "escalations": self._escalations,
                "downgrades": self._downgrades,
                "patterns": len(self._pattern_history),
                "tier_distribution": {
                    t: sum(1 for e in self._pattern_history.values() if e["tier"] == t)
                    for t in TIERS
                },
            }


_router: PALRouter | None = None


def get_router() -> PALRouter:
    global _router
    if _router is None:
        _router = PALRouter()
    return _router


def reset_router() -> None:
    global _router
    _router = None
