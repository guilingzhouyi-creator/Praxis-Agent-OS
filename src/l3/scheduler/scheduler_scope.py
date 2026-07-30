"""ScopeScheduler — step budget + scout quota management.
Extracted from ExecutionPlan + ScoutPool for scheduler matrix integration.
"""
from __future__ import annotations

import logging
from typing import Any

from l1.kernel.params.agent import AGENT_LOOP_DEFAULT_STEPS, SCOUT_LOOP_STEPS
from l1.kernel.params.system import MAX_SCOUTS_PER_AGENT, SCOUT_POOL_MAX
from l1.kernel.discovery import get_config as _get_config


_MAX_SCOUTS = _get_config("cell", {}).get("scout", {}).get("max_per_agent", MAX_SCOUTS_PER_AGENT) if _get_config("cell") else MAX_SCOUTS_PER_AGENT

logger = logging.getLogger(__name__)


class ScopeScheduler:
    """Manages step budgets and scout quotas per agent and card.

    Step budget: dynamic cap on tool-calling turns per execution plan.
    Scout quota: max concurrent scout delegations per agent.
    """

    def __init__(self):
        self._scout_counts: dict[str, int] = {}

    # ── Step budget ──

    def calc_step_budget(self, num_phases: int, total_steps: int, cap: int = 30) -> int:
        """Dynamic step budget: base 5 + 3 per phase + 2 per step, capped at `cap`."""
        return min(5 + 3 * num_phases + 2 * total_steps, cap)

    def default_max_steps(self) -> int:
        return AGENT_LOOP_DEFAULT_STEPS

    # ── Scout quota ──

    def check_scout_quota(self, agent_id: str) -> dict:
        """Check if agent can spawn another scout."""
        current = self._scout_counts.get(agent_id, 0)
        if current >= MAX_SCOUTS_PER_AGENT:
            return {"allowed": False, "current": current, "limit": MAX_SCOUTS_PER_AGENT}
        return {"allowed": True, "current": current, "limit": MAX_SCOUTS_PER_AGENT}

    def acquire_scout(self, agent_id: str) -> dict:
        r = self.check_scout_quota(agent_id)
        if not r["allowed"]:
            return r
        self._scout_counts[agent_id] = self._scout_counts.get(agent_id, 0) + 1
        return r

    def release_scout(self, agent_id: str) -> None:
        self._scout_counts[agent_id] = max(0, self._scout_counts.get(agent_id, 0) - 1)

    def reset_agent(self, agent_id: str) -> None:
        self._scout_counts.pop(agent_id, None)

    def stats(self) -> dict:
        return {
            "active_scouts": sum(self._scout_counts.values()),
            "agents": len(self._scout_counts),
        }


_scope_scheduler: ScopeScheduler | None = None


def get_scope_scheduler() -> ScopeScheduler:
    global _scope_scheduler
    if _scope_scheduler is None:
        _scope_scheduler = ScopeScheduler()
    return _scope_scheduler


def reset_scope_scheduler() -> None:
    global _scope_scheduler
    _scope_scheduler = None
