"""ICache — Instruction Cache (read-mostly, LFU eviction).

Stores structural Cell knowledge that changes slowly:
  - Tool definitions (ToolDef specs)
  - Card templates (CardBuilder templates)
  - HTN decomposition methods
  - Constitution rules (parsed .praxis-rules)
  - Territory maps (TERRITORY_MAP entries)
  - Agent configuration defaults

Unlike D-Cache (CellCache), I-Cache:
  - Uses LFU (Least Frequently Used) eviction, not TTL
  - Is read-mostly — writes are rare (config reload, tool registration)
  - Has a frequency decay mechanism to age out hot-but-stale entries
  - Never flushes to MemoryManager (instruction data is not episodic memory)

Integration:
  - MMU reads territory maps from I-Cache (page walk)
  - ToolPipeline reads tool specs from I-Cache on first use
  - InterruptController reads IRQ routing table from I-Cache
  - PMU tracks: icache.hits, icache.misses, icache.evictions
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from l1.kernel.params.system import ICACHE_MAX_ENTRIES, ICACHE_TTL, ICACHE_LFU_DECAY

logger = logging.getLogger(__name__)


@dataclass
class ICacheEntry:
    key: str = ""
    value: Any = None
    entry_type: str = ""          # "tool" | "template" | "htn" | "constitution" | "territory" | "config"
    frequency: int = 0            # access count (decayed)
    loaded_at: float = 0.0
    ttl: float = ICACHE_TTL
    tags: list[str] = field(default_factory=list)


class ICache:
    """Instruction Cache — LFU-evicted, read-mostly, TTL-guarded."""

    def __init__(
        self,
        cell_id: str,
        max_entries: int = ICACHE_MAX_ENTRIES,
        default_ttl: float = ICACHE_TTL,
        lfu_decay: float = ICACHE_LFU_DECAY,
        pmu: Any = None,
    ):
        self.cell_id = cell_id
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._lfu_decay = lfu_decay
        self._pmu = pmu
        self._entries: dict[str, ICacheEntry] = {}
        self._lock = threading.RLock()
        self._decay_counter = 0

    # ── Public API ────────────────────────────────────────────────

    def store(
        self,
        key: str,
        value: Any,
        *,
        entry_type: str = "",
        ttl: float = 0,
        tags: list[str] | None = None,
    ) -> None:
        """Store an entry in the I-Cache (upsert)."""
        with self._lock:
            self._entries[key] = ICacheEntry(
                key=key,
                value=value,
                entry_type=entry_type,
                loaded_at=time.time(),
                ttl=ttl or self._default_ttl,
                tags=tags or [],
            )
            self._evict_lfu()

    def load(self, key: str) -> Any | None:
        """Load a value from I-Cache. Returns None on miss or expiry."""
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                if self._pmu:
                    self._pmu.increment("icache.misses")
                return None
            if now - entry.loaded_at > entry.ttl:
                self._entries.pop(key, None)
                if self._pmu:
                    self._pmu.increment("icache.misses")
                return None
            entry.frequency += 1
            if self._pmu:
                self._pmu.increment("icache.hits")
            return entry.value

    def load_entry(self, key: str) -> ICacheEntry | None:
        """Load the full entry (with metadata), not just value."""
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now - entry.loaded_at > entry.ttl:
                self._entries.pop(key, None)
                return None
            entry.frequency += 1
            return entry

    def search(self, entry_type: str = "", tag: str = "",
               limit: int = 20) -> list[ICacheEntry]:
        """Search entries by type or tag."""
        now = time.time()
        with self._lock:
            results: list[ICacheEntry] = []
            for e in self._entries.values():
                if now - e.loaded_at > e.ttl:
                    continue
                if entry_type and e.entry_type != entry_type:
                    continue
                if tag and tag not in e.tags:
                    continue
                results.append(e)
            results.sort(key=lambda e: e.frequency, reverse=True)
            return results[:limit]

    def remove(self, key: str) -> None:
        """Remove a specific entry."""
        with self._lock:
            self._entries.pop(key, None)

    def remove_by_type(self, entry_type: str) -> int:
        """Remove all entries of a given type. Returns count."""
        with self._lock:
            keys = [k for k, e in self._entries.items() if e.entry_type == entry_type]
            for k in keys:
                self._entries.pop(k, None)
            return len(keys)

    # ── Eviction ──────────────────────────────────────────────────

    def _evict_lfu(self) -> None:
        """LFU eviction — remove least-frequently-used entries when over capacity."""
        while len(self._entries) > self._max_entries:
            if not self._entries:
                break
            lfu_key = min(self._entries, key=lambda k: self._entries[k].frequency)
            evicted = self._entries.pop(lfu_key)
            if self._pmu:
                self._pmu.increment("icache.evictions")
            logger.debug("ICache %s: evicted %s (freq=%d)", self.cell_id, lfu_key, evicted.frequency)

    def decay_frequencies(self) -> None:
        """Decay all frequency counters to age out hot-but-stale entries.
        Called periodically (e.g. every 100 accesses or by a timer).
        """
        with self._lock:
            for entry in self._entries.values():
                entry.frequency = int(entry.frequency * self._lfu_decay)

    # ── Bulk operations ───────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        with self._lock:
            return {
                "cell_id": self.cell_id,
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "default_ttl": self._default_ttl,
                "types": self._count_by_type(),
            }

    def _count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entries.values():
            counts[e.entry_type] = counts.get(e.entry_type, 0) + 1
        return counts
