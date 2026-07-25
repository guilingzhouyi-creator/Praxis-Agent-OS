"""Memory allocator — Token/ring/sandbox quota allocation and reclamation.

Like a physical memory allocator:
  alloc():    Reserve tokens or slots for an Agent
  free():     Release when done
  reclaim():  Force eviction under pressure (GC)
  swap_out(): Move cold entries from Ring → disk
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .params import (
    ALLOCATOR_DEFAULTS, ALLOCATOR_FALLBACK_LIMIT,
    ALLOCATOR_PRESSURE_THRESHOLD, ALLOCATOR_OBSERVE_PURPOSE,
    ALLOCATOR_DEFAULT_AMOUNT, ALLOCATOR_PCT_PRECISION,
    ALLOCATOR_SWAP_SOURCE, ALLOCATOR_SWAP_TARGET,
    ALLOCATOR_SWAP_COUNT, ALLOCATOR_DISK_RESOURCE,
    ALLOCATOR_DEFAULT_PRIORITY,
    RESOURCE_TOKENS, RESOURCE_RING1, RESOURCE_RING2, RESOURCE_RING3,
    RESOURCE_SANDBOX_KB, RESOURCE_PRIORITY,
)
from .interrupt import fire, InterruptType

logger = logging.getLogger(__name__)


@dataclass
class Allocation:
    agent_id: str
    resource: str
    amount: int
    allocated_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    purpose: str = ""


class Allocator:
    """Token/slot allocator with pressure-based reclamation."""

    DEFAULTS = {
        RESOURCE_TOKENS: ALLOCATOR_DEFAULTS.tokens,
        RESOURCE_RING1: ALLOCATOR_DEFAULTS.ring1,
        RESOURCE_RING2: ALLOCATOR_DEFAULTS.ring2,
        RESOURCE_RING3: ALLOCATOR_DEFAULTS.ring3,
        RESOURCE_SANDBOX_KB: ALLOCATOR_DEFAULTS.sandbox_kb,
        RESOURCE_PRIORITY: ALLOCATOR_DEFAULT_PRIORITY,
    }

    def __init__(self):
        self._limits: dict[str, dict[str, int]] = {}
        self._allocations: dict[str, list[Allocation]] = {}
        self._lock = threading.RLock()

    def set_limit(self, agent_id: str, resource: str, limit: int) -> dict:
        with self._lock:
            self._limits.setdefault(agent_id, dict(self.DEFAULTS))[resource] = limit
        return {"success": True}

    def _update_pcb(self, agent_id: str, resource: str, amount: int, is_alloc: bool) -> None:
        """Update PCB ResourceUsage for the calling agent."""
        try:
            from .process import get_table
            pcb = get_table().get_by_name(agent_id)
            if pcb:
                if resource == RESOURCE_TOKENS:
                    if is_alloc:
                        pcb.record_alloc(amount)
                    else:
                        pcb.record_use(amount)
        except Exception as e:
            logger.warning("allocator pcb update: %s", e)

    def alloc(self, agent_id: str, resource: str, amount: int = ALLOCATOR_DEFAULT_AMOUNT,
              purpose: str = "", ttl: float = 0.0) -> dict:
        with self._lock:
            limits = self._limits.setdefault(agent_id, dict(self.DEFAULTS))
            allocs = self._allocations.setdefault(agent_id, [])
            used = sum(a.amount for a in allocs if a.resource == resource)
            limit = limits.get(resource, ALLOCATOR_FALLBACK_LIMIT)
            available = limit - used

            if available < amount:
                freed = self._reclaim_locked(agent_id, resource, amount - available)
                available += freed
                if available < amount:
                    fire(InterruptType.RESOURCE_EXHAUSTION, agent_id=agent_id,
                         reason=f"{resource} exhausted ({used}/{limit})",
                         data={"resource": resource, "used": used, "limit": limit})
                    victim_freed = self._oom_kill(agent_id, resource, amount - available)
                    available += victim_freed
                    if available < amount:
                        return {"success": False, "error": f"{resource} exhausted ({used}/{limit})",
                                "used": used, "limit": limit, "pressure": True, "oom": True}

            alloc = Allocation(agent_id=agent_id, resource=resource, amount=amount,
                               purpose=purpose, expires_at=time.time() + ttl if ttl else 0)
            allocs.append(alloc)
            self._update_pcb(agent_id, resource, amount, is_alloc=True)
            return {"success": True, "used": used + amount, "limit": limit,
                    "remaining": limit - used - amount}

    def free(self, agent_id: str, resource: str, amount: int = ALLOCATOR_DEFAULT_AMOUNT) -> dict:
        with self._lock:
            allocs = self._allocations.get(agent_id, [])
            freed = 0
            for a in list(allocs):
                if a.resource == resource and freed < amount:
                    allocs.remove(a)
                    freed += a.amount
            self._update_pcb(agent_id, resource, freed, is_alloc=False)
            return {"success": True, "freed": freed}

    def usage(self, agent_id: str) -> dict:
        with self._lock:
            limits = self._limits.setdefault(agent_id, dict(self.DEFAULTS))
            allocs = self._allocations.setdefault(agent_id, [])
            result = {}
            for resource, limit in limits.items():
                used = sum(a.amount for a in allocs if a.resource == resource)
                pct = round(used / limit * 100, ALLOCATOR_PCT_PRECISION) if limit else 0
                result[resource] = {"used": used, "limit": limit, "pct": pct}
            return result

    def pressure(self, threshold: float = ALLOCATOR_PRESSURE_THRESHOLD) -> dict:
        agents_under_pressure = []
        for agent_id in self._limits:
            usage = self.usage(agent_id)
            for resource, stats in usage.items():
                if stats["pct"] >= threshold:
                    agents_under_pressure.append({"agent_id": agent_id, "resource": resource, **stats})
        return {"under_pressure": len(agents_under_pressure) > 0,
                "agents": agents_under_pressure, "count": len(agents_under_pressure)}

    def _reclaim_locked(self, agent_id: str, resource: str, needed: int) -> int:
        allocs = self._allocations.setdefault(agent_id, [])
        now = time.time()
        reclaimed = 0
        expired = [a for a in allocs if a.resource == resource and a.expires_at > 0 and now > a.expires_at]
        for a in expired:
            allocs.remove(a)
            reclaimed += a.amount
        if reclaimed >= needed:
            return reclaimed
        old = [a for a in allocs if a.resource == resource and ALLOCATOR_OBSERVE_PURPOSE in a.purpose.lower()]
        for a in old:
            if reclaimed >= needed:
                break
            allocs.remove(a)
            reclaimed += a.amount
        return reclaimed

    def _oom_kill(self, requesting_agent: str, resource: str, needed: int) -> int:
        """OOM killer — select victim, reclaim resources.

        Victim selection: lowest priority agent with the most allocations of this resource.
        Fires OOM_KILL interrupt for the victim.
        """
        candidates: list[tuple[str, int, int]] = []  # (agent, priority, alloc_count)
        with self._lock:
            for agent_id, allocs in self._allocations.items():
                if agent_id == requesting_agent:
                    continue
                count = sum(a.amount for a in allocs if a.resource == resource)
                if count > 0:
                    limits = self._limits.get(agent_id, self.DEFAULTS)
                    priority = limits.get(RESOURCE_PRIORITY, ALLOCATOR_DEFAULT_PRIORITY)
                    candidates.append((agent_id, priority, count))

        if not candidates:
            return 0

        # Sort by: lower priority first, then higher allocation count
        candidates.sort(key=lambda c: (c[1], -c[2]))
        victim, prio, total = candidates[0]
        reclaim = min(total, needed)

        with self._lock:
            allocs = self._allocations.get(victim, [])
            freed = 0
            for a in list(allocs):
                if a.resource == resource and freed < reclaim:
                    allocs.remove(a)
                    freed += a.amount

        fire(InterruptType.OOM_KILL, agent_id=victim,
             reason=f"killed by OOM for {resource} (priority={prio}, reclaimed={freed})",
             data={"requesting_agent": requesting_agent, "resource": resource,
                   "needed": needed, "reclaimed": freed})

        # Terminate the victim process: set PCB to ZOMBIE
        try:
            from .process import get_table, ProcessState
            pcb = get_table().get_by_name(victim)
            if pcb:
                get_table().set_state(pcb.pid, ProcessState.ZOMBIE)
                get_table().exit(pcb.pid, exit_code=-9, reason=f"OOM killed for {resource}")
        except Exception as e:
            logger.warning("allocator pcb update: %s", e)

        logger.critical("OOM: killed %s (priority=%d), reclaimed %d %s for %s",
                        victim, prio, freed, resource, requesting_agent)
        return freed

    def swap_out(self, agent_id: str, resource: str = ALLOCATOR_SWAP_SOURCE,
                 target_resource: str = ALLOCATOR_SWAP_TARGET, count: int = ALLOCATOR_SWAP_COUNT) -> dict:
        """Move allocations to colder resource (like swap to disk).

        ring2 → ring3: rename resource tag.
        ring3 → disk:  persist via event store, then remove from memory.
        """
        with self._lock:
            allocs = self._allocations.get(agent_id, [])
            source = [a for a in allocs if a.resource == resource]
            if not source:
                return {"success": True, "moved": 0}
            to_move = source[:count]
            moved = 0
            for a in to_move:
                if target_resource == ALLOCATOR_DISK_RESOURCE:
                    # Persist to event store before removing from memory
                    try:
                        from .persist import append
                        append("allocator.swap_out", {
                            "agent_id": agent_id, "resource": str(a.resource),
                            "amount": a.amount, "purpose": a.purpose,
                        })
                    except Exception as e:
                        logger.warning("kernel/allocator: %s", e)
                    allocs.remove(a)
                else:
                    a.resource = target_resource
                moved += 1
            return {"success": True, "moved": moved, "from": resource, "to": target_resource}

    def summary(self) -> dict:
        with self._lock:
            result = {}
            for agent_id in self._limits:
                result[agent_id] = self.usage(agent_id)
            return result


_allocator: Allocator | None = None


def get_allocator() -> Allocator:
    global _allocator
    if _allocator is None:
        _allocator = Allocator()
    return _allocator


def reset_allocator() -> None:
    global _allocator
    _allocator = None
