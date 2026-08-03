"""Swapping daemon — background memory pressure management.

Moves entries between working/short/long-term memory rings:
  _swap_out_working: ring1 -> ring2/ring3 (on pressure)
  _compact_short_term: ring2 -> ring3 (periodic)
  swap_in: ring3 -> ring1 (on access miss, reversing swap_out)

Design doc promises bidirectional swap but only _swap_out existed.
swap_in() is the missing reverse direction — restores cold data on demand.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from l1.kernel.params.system import LOG_TRUNC_100

from .allocator import get_allocator
from .params.kernel import (
    SWAPPER_COMPACT_IMPORTANCE,
    SWAPPER_DEFAULT_INTERVAL,
    SWAPPER_PRESSURE_HIGH,
    SWAPPER_PRESSURE_LOW,
    SWAPPER_RECALL_LIMIT,
    SWAPPER_SWAP_COUNT,
    SWAPPER_SWAP_OUT_IMPORTANCE,
)

logger = logging.getLogger(__name__)


class Swapper:
    """Background memory pressure manager."""

    def __init__(self, interval: float = SWAPPER_DEFAULT_INTERVAL,
                 memory_service=None):
        self.interval = interval
        self._running = True
        self._mem = memory_service
        self._total_swapped_out = 0
        self._total_compactions = 0

    def set_memory(self, mem: Any) -> None:
        """Wire MemoryService to the swapper (called from boot.py).  Idempotent."""
        if self._mem is not None and self._thread and self._thread.is_alive():
            logger.warning("swapper already wired, skipping duplicate set_memory")
            return
        self._mem = mem
        logger.info("swapper wired to memory service")
        self._alloc = get_allocator()
        self._total_swapped_out = 0
        self._total_compactions = 0
        self._pager_bridge = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("swapper started (interval=%ds)", self.interval)

    def _loop(self) -> None:
        while self._running:
            time.sleep(self.interval)
            try:
                self._tick()
            except Exception as e:
                logger.error("swapper tick error: %s", e)

    def _tick(self) -> None:
        stats = self._mem.stats()
        pressure = self._alloc.pressure(threshold=SWAPPER_PRESSURE_LOW)
        if not pressure["under_pressure"]:
            return
        w_pct = stats["working"]["pct"]
        s_pct = stats["short"]["pct"]
        l_pct = stats["long"]["pct"]
        logger.info("pressure: W=%d%% S=%d%% L=%d%%", w_pct, s_pct, l_pct)
        if w_pct >= SWAPPER_PRESSURE_HIGH:
            n = self._swap_out_working()
            logger.warning("swapped out %d entries from working memory", n)
        if s_pct >= SWAPPER_PRESSURE_HIGH:
            n = self._compact_short_term()
            logger.warning("compacted %d short-term entries", n)
        if l_pct >= SWAPPER_PRESSURE_HIGH:
            logger.warning("LONG-TERM MEMORY FULL")

    def swap_in(self, entry_id: str) -> dict:
        """Restore a swapped-out entry from long-term back to working set."""
        if not self._mem:
            return {"success": False, "error": "no memory service"}
        try:
            # Find the entry across rings via ID lookup (use generous limit to avoid truncation)
            ring3_entries = self._mem.recall(rings=[3], limit=SWAPPER_RECALL_LIMIT)
            entry = next((e for e in ring3_entries if e.id == entry_id), None)
            if not entry:
                return {"success": False, "error": f"entry not found: {entry_id}"}

            # Preserve all original metadata for the restore
            new_id = self._mem.remember(
                agent_id=entry.agent_id,
                entry_type=entry.entry_type,
                content=entry.content,
                tags=entry.tags,
                source=entry.source,
                importance=entry.importance,
                cell_id=entry.cell_id,
                ring=1,
            )
            self._total_swapped_out -= 1
            return {"success": True, "entry": {
                "id": new_id,
                "agent_id": entry.agent_id,
                "entry_type": entry.entry_type,
                "content": entry.content[:LOG_TRUNC_100],
                "cell_id": entry.cell_id,
                "importance": entry.importance,
            }}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _swap_out_working(self, count: int = SWAPPER_SWAP_COUNT) -> int:
        if not self._mem or not hasattr(self._mem, "working"):
            return 0
        entries = self._mem.working()[:count]
        for e in entries:
            try:
                target_ring = 3 if e.importance < SWAPPER_SWAP_OUT_IMPORTANCE else 2
                self._mem.promote(e.id, target_ring=target_ring)
                self._total_swapped_out += 1
                logger.debug("swapped %s ring1 → ring%d (importance=%.2f)", e.id, target_ring, e.importance)
            except Exception as err:
                logger.warning("swap out %s failed: %s", getattr(e, 'id', '?'), err)
        return len(entries)

    def _compact_short_term(self) -> int:
        if not self._mem or not hasattr(self._mem, "short_term"):
            return 0
        entries = self._mem.short_term()
        compacted = 0
        for e in entries:
            try:
                if e.importance < SWAPPER_COMPACT_IMPORTANCE and e.ttl > 0 and e.expired():
                    self._mem.promote(e.id, target_ring=3)
                    compacted += 1
                    self._total_compactions += 1
                    logger.debug("compacted %s ring2 → ring3", e.id)
            except Exception as err:
                logger.warning("compact %s failed: %s", getattr(e, 'id', '?'), err)
        return compacted

    def stop(self) -> None:
        self._running = False

    def stats(self) -> dict:
        return {"swapped_out": getattr(self, '_total_swapped_out', 0), "compactions": self._total_compactions}


_swapper: Swapper | None = None
_swapper_lock = threading.Lock()


def get_swapper(interval: float = SWAPPER_DEFAULT_INTERVAL, memory_service=None) -> Swapper:
    global _swapper
    if _swapper is None:
        with _swapper_lock:
            if _swapper is None:
                _swapper = Swapper(interval, memory_service)
    return _swapper


def reset_swapper() -> None:
    global _swapper
    if _swapper:
        _swapper.stop()
    _swapper = None
