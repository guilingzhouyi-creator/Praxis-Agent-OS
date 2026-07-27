"""CellMmu + CellTlb — Memory Management Unit with TLB for Cell.

Translates "territory address" (a path pattern like "src/") to a
physical Agent ID with ring-level clearance.  The TLB caches the N
most recent translations for fast dispatch.

Architecture:
  MMU is the translation authority.
  TLB is the fast-path cache backed by MMU (page walk on miss).

Translation flow:
  1. TLB lookup(territory_pattern) → agent_id (fast path)
  2. On miss: MMU.page_walk(territory_pattern, icache) → agent_id
  3. TLB caches the result
  4. On territory reassignment: TLB.flush()

Integration:
  - TLB backed by I-Cache (territory maps stored as "territory.*" entries)
  - PMU tracks: tlb.hits, tlb.misses, tlb.flushes
  - Watchdog on_crash → TLB.flush_agent(dead_agent_id)
  - InterruptController NMI → TLB.flush_all() on constitution violation
  - Cell.remove_agent() → TLB.flush_agent()
  - Cell.add_agent() → TLB.flush_territory(new_agent_territory)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import TLB_MAX_ENTRIES, TLB_DEFAULT_RING, TLB_CLEARANCE_FALLBACK

logger = logging.getLogger(__name__)


@dataclass
class TlbEntry:
    """A cached territory → agent translation."""
    territory_pattern: str = ""
    agent_id: str = ""
    ring: int = TLB_DEFAULT_RING
    valid: bool = True
    loaded_at: float = 0.0
    hit_count: int = 0


class CellTlb:
    """Translation Lookaside Buffer — caches territory→agent mappings.

    Thread-safe.  Limited-size CAM-style cache with LFU-like
    eviction (lowest hit_count evicted first).
    """

    def __init__(self, max_entries: int = TLB_MAX_ENTRIES, pmu: Any = None):
        self._max_entries = max_entries
        self._pmu = pmu
        self._entries: dict[str, TlbEntry] = {}
        self._lock = threading.RLock()

    # ── Lookup ────────────────────────────────────────────────────

    def lookup(self, territory_pattern: str) -> TlbEntry | None:
        """Look up a cached translation.  Returns None on miss."""
        with self._lock:
            entry = self._entries.get(territory_pattern)
            if entry is None or not entry.valid:
                if self._pmu:
                    self._pmu.increment("tlb.misses")
                return None
            entry.hit_count += 1
            if self._pmu:
                self._pmu.increment("tlb.hits")
            return entry

    # ─── Fill ─────────────────────────────────────────────────────

    def fill(self, territory_pattern: str, agent_id: str,
             ring: int = TLB_DEFAULT_RING) -> None:
        """Insert or update a TLB entry."""
        with self._lock:
            self._entries[territory_pattern] = TlbEntry(
                territory_pattern=territory_pattern,
                agent_id=agent_id,
                ring=ring,
                loaded_at=time.time(),
            )
            self._evict()

    def fill_many(self, mappings: dict[str, tuple[str, int]]) -> None:
        """Batch fill multiple territory→agent mappings."""
        with self._lock:
            for pattern, (agent_id, ring) in mappings.items():
                self._entries[pattern] = TlbEntry(
                    territory_pattern=pattern,
                    agent_id=agent_id,
                    ring=ring,
                    loaded_at=time.time(),
                )
            self._evict()

    # ── Flush ─────────────────────────────────────────────────────

    def flush_agent(self, agent_id: str) -> int:
        """Invalidate all entries for a given agent.  Returns count."""
        with self._lock:
            count = 0
            for entry in self._entries.values():
                if entry.agent_id == agent_id and entry.valid:
                    entry.valid = False
                    count += 1
            if count and self._pmu:
                self._pmu.increment("tlb.flushes")
            return count

    def flush_territory(self, territory_pattern: str) -> bool:
        """Invalidate a specific territory entry."""
        with self._lock:
            entry = self._entries.get(territory_pattern)
            if entry and entry.valid:
                entry.valid = False
                if self._pmu:
                    self._pmu.increment("tlb.flushes")
                return True
            return False

    def flush_all(self) -> int:
        """Invalidate ALL entries.  Returns count."""
        with self._lock:
            count = sum(1 for e in self._entries.values() if e.valid)
            for e in self._entries.values():
                e.valid = False
            if count and self._pmu:
                self._pmu.increment("tlb.flushes")
            return count

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            valid = [e for e in self._entries.values() if e.valid]
            return {
                "entries": len(valid),
                "max_entries": self._max_entries,
                "agents": list({e.agent_id for e in valid}),
                "patterns": [e.territory_pattern for e in valid],
            }

    # ── Internal ──────────────────────────────────────────────────

    def _evict(self) -> None:
        """Evict lowest-hit-count entries when over capacity."""
        while len(self._entries) > self._max_entries:
            if not self._entries:
                break
            victim = min(self._entries.values(), key=lambda e: e.hit_count)
            self._entries.pop(victim.territory_pattern)


class CellMmu:
    """Memory Management Unit — territory → agent translation authority.

    Uses TLB as fast path, falls back to page walk (I-Cache → config).
    """

    def __init__(self, cell_id: str, tlb: CellTlb | None = None, icache: Any = None):
        self.cell_id = cell_id
        self._tlb = tlb or CellTlb()
        self._icache = icache
        self._lock = threading.RLock()

    @property
    def tlb(self) -> CellTlb:
        return self._tlb

    # ── Translation ───────────────────────────────────────────────

    def resolve(self, territory_pattern: str,
                agents: dict[str, Any] | None = None) -> dict:
        """Resolve a territory pattern to an agent.

        Returns {"agent_id": str, "ring": int} or
                {"agent_id": "", "ring": 0, "error": str} on miss.

        Translation cascade:
          1. TLB lookup (fast path)
          2. Page walk: I-Cache lookup (medium path)
          3. Fallback: agents dict scan (slow path)
        """
        # 1. TLB fast path
        cached = self._tlb.lookup(territory_pattern)
        if cached:
            return {"agent_id": cached.agent_id, "ring": cached.ring}

        # 2. Page walk — I-Cache
        if self._icache:
            territory_map = self._icache.load(f"territory.{territory_pattern}")
            if territory_map and isinstance(territory_map, dict):
                agent_id = territory_map.get("agent_id", "")
                ring = territory_map.get("ring", TLB_DEFAULT_RING)
                self._tlb.fill(territory_pattern, agent_id, ring)
                return {"agent_id": agent_id, "ring": ring}

        # 3. Fallback — agents dict scan
        if agents:
            best_match = None
            best_ring = TLB_DEFAULT_RING
            for aid, info in agents.items():
                terr = getattr(info, "territory", info.get("territory", [])) if isinstance(info, dict) else info.territory
                ring = getattr(info, "ring", info.get("ring", TLB_DEFAULT_RING)) if isinstance(info, dict) else info.ring
                for t in terr:
                    if territory_pattern.startswith(t) or t.startswith(territory_pattern):
                        if best_match is None or len(t) > len(getattr(best_match, "territory", [None])[0] if hasattr(best_match, "territory") else ""):
                            best_match = (aid, ring)
            if best_match:
                agent_id, ring = best_match
                self._tlb.fill(territory_pattern, agent_id, ring)
                return {"agent_id": agent_id, "ring": ring}

        return {"agent_id": "", "ring": 0, "error": f"no agent for territory: {territory_pattern}"}

    def resolve_many(self, patterns: list[str],
                     agents: dict[str, Any] | None = None) -> dict[str, dict]:
        """Batch resolve multiple territory patterns."""
        return {p: self.resolve(p, agents) for p in patterns}

    # ── Cache warming ─────────────────────────────────────────────

    def warm_from_agents(self, agents: dict[str, Any]) -> None:
        """Pre-fill TLB from known agent territory mappings."""
        mappings: dict[str, tuple[str, int]] = {}
        for aid, info in agents.items():
            terr = getattr(info, "territory", info.get("territory", [])) if isinstance(info, dict) else info.territory
            ring = getattr(info, "ring", info.get("ring", TLB_DEFAULT_RING)) if isinstance(info, dict) else info.ring
            for t in terr:
                mappings[t] = (aid, ring)
        self._tlb.fill_many(mappings)

    def flush_agent(self, agent_id: str) -> int:
        """Flush all TLB entries for an agent.  Returns count."""
        return self._tlb.flush_agent(agent_id)

    def flush_all(self) -> int:
        """Flush entire TLB."""
        return self._tlb.flush_all()

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "tlb": self._tlb.stats(),
        }
