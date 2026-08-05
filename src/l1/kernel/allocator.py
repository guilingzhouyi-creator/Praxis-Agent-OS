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

from .interrupt import InterruptType, fire
from .params.kernel import (
    ALLOCATOR_DEFAULT_AMOUNT,
    ALLOCATOR_DEFAULT_PRIORITY,
    ALLOCATOR_DEFAULTS,
    ALLOCATOR_DISK_RESOURCE,
    ALLOCATOR_FALLBACK_LIMIT,
    ALLOCATOR_OBSERVE_PURPOSE,
    ALLOCATOR_PCB_FLUSH_SIZE,
    ALLOCATOR_PCT_PRECISION,
    ALLOCATOR_PRESSURE_THRESHOLD,
    ALLOCATOR_SWAP_COUNT,
    ALLOCATOR_SWAP_SOURCE,
    ALLOCATOR_SWAP_TARGET,
    PROCESS_OOM_EXIT_CODE,
    RESOURCE_PRIORITY,
    RESOURCE_RING1,
    RESOURCE_RING2,
    RESOURCE_RING3,
    RESOURCE_SANDBOX_KB,
    RESOURCE_TOKENS,
)

logger = logging.getLogger(__name__)


@dataclass
class Allocation:
    """Allocation — allocation record (agent_id, resource, amount, allocated_at, expires_at)."""
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
        self._usage_counter: dict[str, dict[str, int]] = {}
        """O(1) cumulative usage counter — agent_id → {resource: used_amount}.
        Avoids O(N) sum() scan over all allocations on every alloc() call."""
        self._lock = threading.RLock()
        self._pressure_cache: tuple[float, dict] | None = None
        """Cached pressure result — invalidated on alloc/free, TTL-bound."""

    def set_limit(self, agent_id: str, resource: str, limit: int) -> dict:
        """Override an agent's resource limit for a specific resource type."""
        with self._lock:
            self._limits.setdefault(agent_id, dict(self.DEFAULTS))[resource] = limit
        return {"success": True}

    def _update_pcb(self, agent_id: str, resource: str, amount: int, is_alloc: bool) -> None:
        """Queue a PCB ResourceUsage update, flushed in batches of ALLOCATOR_PCB_FLUSH_SIZE.

        Deferred batching cuts process-table lock acquisition from once per
        alloc/free to once per 32 updates — PCB numbers lag by at most one
        batch on the calling thread, which is acceptable for accounting metrics.
        """
        buf = getattr(_pcb_thread_buffer, "entries", None)
        if buf is None:
            _pcb_thread_buffer.entries = []
            buf = _pcb_thread_buffer.entries
        buf.append((agent_id, resource, amount, is_alloc))
        if len(buf) >= ALLOCATOR_PCB_FLUSH_SIZE:
            self._flush_pcb_buffer()

    def _flush_pcb_buffer(self) -> None:
        """Apply all pending PCB updates in a single process-table lock acquisition."""
        buf = getattr(_pcb_thread_buffer, "entries", None)
        if not buf:
            return
        _pcb_thread_buffer.entries = []
        try:
            from .process import get_table
            table = get_table()
            for agent_id, resource, amount, is_alloc in buf:
                pcb = table.get_by_name(agent_id)
                if not pcb:
                    continue
                if resource == RESOURCE_TOKENS:
                    if is_alloc:
                        pcb.record_alloc(amount)
                    else:
                        pcb.record_use(amount)
        except Exception as e:
            logger.warning("allocator pcb update: %s", e)

    def alloc(self, agent_id: str, resource: str, amount: int = ALLOCATOR_DEFAULT_AMOUNT,
              purpose: str = "", ttl: float = 0.0) -> dict:
        """Allocate a resource amount for an agent. Triggers reclamation or OOM kill when limits are exceeded."""
        with self._lock:
            self._pressure_cache = None
            limits = self._limits.setdefault(agent_id, dict(self.DEFAULTS))
            allocs = self._allocations.setdefault(agent_id, [])
            counter = self._usage_counter.setdefault(agent_id, {})
            used = counter.get(resource, 0)
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
            counter[resource] = counter.get(resource, 0) + amount
            self._update_pcb(agent_id, resource, amount, is_alloc=True)
            return {"success": True, "used": used + amount, "limit": limit,
                    "remaining": limit - used - amount}

    def free(self, agent_id: str, resource: str, amount: int = ALLOCATOR_DEFAULT_AMOUNT) -> dict:
        """Release a resource amount back to the agent's pool."""
        with self._lock:
            self._pressure_cache = None
            allocs = self._allocations.get(agent_id, [])
            counter = self._usage_counter.setdefault(agent_id, {})
            freed = 0
            if allocs:
                # Single-pass rebuild: O(n) instead of O(n^2) list.remove() churn.
                kept: list[Allocation] = []
                for a in allocs:
                    if freed < amount and a.resource == resource:
                        freed += a.amount
                    else:
                        kept.append(a)
                if freed:
                    allocs[:] = kept
            if freed:
                prev = counter.get(resource, 0)
                counter[resource] = max(0, prev - freed)
            self._update_pcb(agent_id, resource, freed, is_alloc=False)
            return {"success": True, "freed": freed}

    def usage(self, agent_id: str) -> dict:
        """Return current resource usage stats for an agent."""
        with self._lock:
            limits = self._limits.setdefault(agent_id, dict(self.DEFAULTS))
            counter = self._usage_counter.setdefault(agent_id, {})
            result = {}
            for resource, limit in limits.items():
                used = counter.get(resource, 0)
                pct = round(used / limit * 100, ALLOCATOR_PCT_PRECISION) if limit else 0
                result[resource] = {"used": used, "limit": limit, "pct": pct}
            return result

    def pressure(self, threshold: float = ALLOCATOR_PRESSURE_THRESHOLD) -> dict:
        """Check which agents are above the pressure threshold across all resources.

        Uses a dirty-flag cache invalidated by alloc/free to skip O(N×M) full scan
        when no allocations have changed since the last check.
        """
        with self._lock:
            if self._pressure_cache is not None and self._pressure_cache[0] == threshold:
                return self._pressure_cache[1]
        agents_under_pressure = []
        for agent_id in self._limits:
            usage = self.usage(agent_id)
            for resource, stats in usage.items():
                if stats["pct"] >= threshold:
                    agents_under_pressure.append({"agent_id": agent_id, "resource": resource, **stats})
        result = {"under_pressure": len(agents_under_pressure) > 0,
                  "agents": agents_under_pressure, "count": len(agents_under_pressure)}
        with self._lock:
            self._pressure_cache = (threshold, result)
        return result

    def _reclaim_locked(self, agent_id: str, resource: str, needed: int) -> int:
        allocs = self._allocations.setdefault(agent_id, [])
        counter = self._usage_counter.setdefault(agent_id, {})
        now = time.time()
        reclaimed = 0
        if not allocs:
            return 0
        # Single-pass rebuild: reclaim ALL expired entries first, then observe-
        # purpose entries until `needed` is met (O(n), no list.remove() churn).
        kept: list[Allocation] = []
        for a in allocs:
            if a.resource == resource and a.expires_at > 0 and now > a.expires_at:
                reclaimed += a.amount
            else:
                kept.append(a)
        if reclaimed < needed:
            final: list[Allocation] = []
            for a in kept:
                if reclaimed < needed and ALLOCATOR_OBSERVE_PURPOSE in a.purpose.lower():
                    reclaimed += a.amount
                else:
                    final.append(a)
            kept = final
        if reclaimed:
            allocs[:] = kept
            counter[resource] = max(0, counter.get(resource, 0) - reclaimed)
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
            victim_counter = self._usage_counter.setdefault(victim, {})
            freed = 0
            for a in list(allocs):
                if a.resource == resource and freed < reclaim:
                    allocs.remove(a)
                    freed += a.amount
            if freed:
                prev = victim_counter.get(resource, 0)
                victim_counter[resource] = max(0, prev - freed)

        fire(InterruptType.OOM_KILL, agent_id=victim,
             reason=f"killed by OOM for {resource} (priority={prio}, reclaimed={freed})",
             data={"requesting_agent": requesting_agent, "resource": resource,
                   "needed": needed, "reclaimed": freed})

        # Terminate the victim process via PCB exit (which uses FSM "crash" transition)
        try:
            from .process import get_table
            pcb = get_table().get_by_name(victim)
            if pcb:
                get_table().exit(pcb.pid, exit_code=PROCESS_OOM_EXIT_CODE, reason=f"OOM killed for {resource}")
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
            counter = self._usage_counter.setdefault(agent_id, {})
            source = [a for a in allocs if a.resource == resource]
            if not source:
                return {"success": True, "moved": 0}
            to_move = source[:count]
            moved = 0
            total_amount = 0
            for a in to_move:
                total_amount += a.amount
                if target_resource == ALLOCATOR_DISK_RESOURCE:
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
            # Update counter: decrement source, increment target (if not disk)
            src_val = counter.get(resource, 0)
            counter[resource] = max(0, src_val - total_amount)
            if target_resource != ALLOCATOR_DISK_RESOURCE:
                tgt_val = counter.get(target_resource, 0)
                counter[target_resource] = tgt_val + total_amount
            return {"success": True, "moved": moved, "from": resource, "to": target_resource}

    def summary(self) -> dict:
        """Return a full allocation summary across all agents and resources."""
        with self._lock:
            result = {}
            for agent_id in self._limits:
                result[agent_id] = self.usage(agent_id)
            return result


_allocator: Allocator | None = None
_allocator_lock = threading.Lock()
_pcb_thread_buffer = threading.local()


def get_allocator() -> Allocator:
    """Get the singleton Allocator instance."""
    global _allocator
    if _allocator is None:
        with _allocator_lock:
            if _allocator is None:
                _allocator = Allocator()
    return _allocator


def reset_allocator() -> None:
    """Reset the singleton Allocator instance (for testing)."""
    global _allocator
    _allocator = None
    _pcb_thread_buffer.entries = []
