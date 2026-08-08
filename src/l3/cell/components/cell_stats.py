"""CellStatsMixin — stats snapshot, think-quota, and scout-cache reuse.

Observability and quota surface of the Cell: ``stats()`` snapshot,
``pmu_snapshot()``, agent listing, think-quota re-resolution, and the
scout-result cache reuse. Composed by Cell.
"""

from __future__ import annotations

import logging
from typing import Any

from l3.agent.scout import scout_cache_get

logger = logging.getLogger(__name__)


class CellStatsMixin:
    """Stats, think quota, and scout-cache helpers."""

    # ── Scout result cache ──

    def reuse_scout_result(self, template: str, scope: dict | None = None, ttl: float = 0) -> dict | None:
        """Reuse cached scout results to avoid re-scouting."""
        return scout_cache_get(template, scope, ttl or self.max_scout_cache_ttl)

    # ── Think quota management ──

    def set_think_quota(self, distribution: str | None = None, **config: Any) -> None:
        """Set think/reasoning quota for an agent."""
        from l3.scheduler.think_registry import get_think_registry

        reg = get_think_registry()
        if distribution:
            self.distribution_mode = distribution
        if config:
            self.think_quota = {**(self.think_quota or {}), **config}
        reg.set_cell(self.cell_id, distribution=self.distribution_mode, **(self.think_quota or {}))
        active = max(1, len([a for a in self._agents.values() if a.status.name in ("IDLE", "RUNNING")]))
        for aid, info in self._agents.items():
            resolved = reg.resolve(self.cell_id, aid, active_agents=active, agent_model_config=info.model_config)
            if resolved:
                info.model_config = resolved
        logger.info(
            "cell %s: think_quota updated (distribution=%s, cfg=%s)", self.cell_id, self.distribution_mode, config
        )

    def stats(self) -> dict:
        """Return a snapshot of cell state (agents, pmu, watchdog, caches)."""
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "territory": self.territory,
                "think_distribution": self.distribution_mode,
                "think_quota": self.think_quota,
                "agents": {
                    aid: {
                        "role": info.role
                        if isinstance(info.role, str)
                        else (info.role.name if hasattr(info.role, "name") else str(info.role)),
                        "ring": info.ring,
                        "status": info.status.name,
                        "active_scouts": info.active_scouts,
                        "max_scouts": info.max_concurrent_scouts,
                        "messages": len(self._mailbox.get(aid, [])),
                        "model_config": info.model_config,
                    }
                    for aid, info in self._agents.items()
                },
                "pmu": self._pmu.stats(),
                "watchdog": self._watchdog.status(),
                "icache": self._icache.stats(),
                "mmu": self._mmu.stats(),
                "interrupt": self._interrupt.stats(),
            }

    def get_agent_ids(self) -> list[str]:
        """Return list of agent IDs registered in this cell."""
        with self._lock:
            return list(self._agents.keys())

    def get_agent_count(self) -> int:
        """Return number of agents registered in this cell."""
        with self._lock:
            return len(self._agents)

    def pmu_snapshot(self) -> dict | None:
        """Take a PMU snapshot and return it as a dict."""
        snap = self._pmu.snapshot()
        if snap is None:
            return None
        return {"timestamp": snap.timestamp, "counters": snap.counters}
