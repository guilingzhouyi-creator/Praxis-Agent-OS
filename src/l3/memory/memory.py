"""MemoryManager — agent memory with context window + ring tiers.

Ring model:
  Ring 1 (working) — ephemeral in-memory
  Ring 2 (short)   — JSONL append-only session log
  Ring 3 (long)    — SQLite FTS5 searchable knowledge

The manager composes four domain mixins: persist (MemoryPersistMixin),
ingest (remember/promote/get_entry), query (recall/context/quality/search),
and compact (pressure/compact/stub_compact/stats).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from l1.kernel.params.system import (
    MEMORY_RING_LONG_BUDGET,
    MEMORY_RING_LONG_TTL,
    MEMORY_RING_SHORT_BUDGET,
    MEMORY_RING_SHORT_TTL,
    MEMORY_RING_WORKING_BUDGET,
    MEMORY_RING_WORKING_TTL,
)

from .memory_compact import MemoryCompactMixin
from .memory_ingest import MemoryIngestMixin
from .memory_persist import MemoryPersistMixin
from .memory_query import MemoryQueryMixin
from .memory_ring import RingLayer

logger = logging.getLogger(__name__)


class MemoryManager(MemoryPersistMixin, MemoryIngestMixin, MemoryQueryMixin, MemoryCompactMixin):
    """Agent memory manager — context window + ring tiers."""

    def __init__(
        self,
        working_budget: int = MEMORY_RING_WORKING_BUDGET,
        short_budget: int = MEMORY_RING_SHORT_BUDGET,
        long_budget: int = MEMORY_RING_LONG_BUDGET,
    ):
        self.working = RingLayer("working", working_budget, ttl=MEMORY_RING_WORKING_TTL)
        self.short = RingLayer("short", short_budget, ttl=MEMORY_RING_SHORT_TTL)
        self.long = RingLayer("long", long_budget, ttl=MEMORY_RING_LONG_TTL)
        self._persist_dir: Path | None = None
        # Dirty-entry tracking: set of entry IDs changed since last persist
        self._dirty_short: set[str] = set()
        self._dirty_long: set[str] = set()
        self._lock = threading.Lock()

    def set_persist_dir(self, path: str) -> None:
        """Set the persistence directory for Ring 2 (JSONL) and Ring 3 (SQLite).

        Called by boot.py during startup and shutdown_to_memories().
        """
        self._persist_dir = Path(path)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    # ── Persistence: dual storage ──
    #   Ring 2 → JSONL (append-only session log)
    #   Ring 3 → SQLite FTS5 (full-text searchable knowledge)
    #   Ring 1 → in-memory only (ephemeral)

    def forget_agent(self, agent_id: str, ring: int = 0) -> dict:
        """Remove all memory entries for a given agent from all rings."""
        if ring == 1:
            return {"working": self.working.clear_agent(agent_id)}
        if ring == 2:
            return {"short": self.short.clear_agent(agent_id)}
        if ring == 3:
            return {"long": self.long.clear_agent(agent_id)}
        return {
            "working": self.working.clear_agent(agent_id),
            "short": self.short.clear_agent(agent_id),
            "long": self.long.clear_agent(agent_id),
        }

    def forget_cell(self, cell_id: str) -> dict:
        """Remove all memory entries for a given cell from all rings."""
        return {
            "working": self.working.forget_cell(cell_id),
            "short": self.short.forget_cell(cell_id),
            "long": self.long.forget_cell(cell_id),
        }

    def _ring(self, n: int) -> RingLayer:
        return {1: self.working, 2: self.short, 3: self.long}.get(n, self.working)

    def _ttl_for(self, ring: int) -> float:
        return {1: MEMORY_RING_WORKING_TTL, 2: MEMORY_RING_SHORT_TTL, 3: MEMORY_RING_LONG_TTL}.get(ring, 0)


_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    """Get the singleton MemoryManager instance."""
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory


def reset_memory() -> None:
    """Reset the singleton MemoryManager instance (for testing)."""
    global _memory
    _memory = None
