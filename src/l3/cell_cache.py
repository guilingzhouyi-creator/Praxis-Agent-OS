"""CellCache — per-Cell L2 shared cache with Hot Ring + Index Chain + KV + flush.

Architecture (in SoC terms):
  L2 sits between per-Agent L1 (ContextRegister, AgentTerminal cache)
  and the global L3 (MemoryManager R1/R2/R3) / L4 (R4Agent Archive).

                          MemoryManager (L3 global)
                               │ flush / promote
                          ┌────┴────┐
                          │ CellCache (L2, per-Cell)
                          │  ┌─ Hot Ring:  deque[IndexEntry]  ← latest summaries
                          │  │   Ring eviction, full→flush→L3
                          │  ├─ Index Chain: dict[key→IndexEntry]
                          │  │   Longer-lived, summary points to full value location
                          │  └─ KV Cache:   dict[key→CellCacheEntry]
                          │      TTL-managed, evict→flush→L3
                          └─────────┬─────────┘
                                    │ inject / lookup / search
                             Agents within the Cell (share hot data)
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from l1.kernel.params.system import CELL_CACHE_HOT_SIZE, CELL_CACHE_INDEX_SIZE, CELL_CACHE_KV_SIZE
from l1.kernel.params.system import CELL_CACHE_HOT_TTL, CELL_CACHE_INDEX_TTL, CELL_CACHE_KV_TTL
from l3.cell_types import CellCacheEntry, IndexEntry

logger = logging.getLogger(__name__)


class CellCache:
    """Per-Cell L2 shared cache — agents in the same Cell share hot data here.

    Three storage tiers:
      1. Hot Ring — deque of IndexEntry (latest N summaries, ring eviction).
      2. Index Chain — dict[str, IndexEntry] (keyed index with location pointer).
      3. KV Cache — dict[str, CellCacheEntry] (full value, TTL-managed).

    Flush path: evicted entries → memory.remember(ring=2/3) — never dropped.
    """

    def __init__(
        self,
        cell_id: str,
        hot_size: int = CELL_CACHE_HOT_SIZE,
        index_size: int = CELL_CACHE_INDEX_SIZE,
        kv_size: int = CELL_CACHE_KV_SIZE,
        hot_ttl: float = CELL_CACHE_HOT_TTL,
        index_ttl: float = CELL_CACHE_INDEX_TTL,
        kv_ttl: float = CELL_CACHE_KV_TTL,
        pmu: Any = None,
    ):
        self.cell_id = cell_id
        self._pmu = pmu
        # Hot Ring — deque of IndexEntry, newest at right
        self._hot: deque[IndexEntry] = deque(maxlen=hot_size)
        # Index Chain — survives hot eviction, maps key → IndexEntry
        self._index: dict[str, IndexEntry] = {}
        # KV Cache — full value store
        self._kv: dict[str, CellCacheEntry] = {}
        self._hot_size = hot_size
        self._index_size = index_size
        self._kv_size = kv_size
        self._hot_ttl = hot_ttl
        self._index_ttl = index_ttl
        self._kv_ttl = kv_ttl
        # LRU ordering for index & kv eviction
        self._index_order: list[str] = []
        self._kv_order: list[str] = []
        # Stats
        self._hits = 0
        self._misses = 0
        self._inject_count = 0
        self._flush_count = 0

    # ── Public API ────────────────────────────────────────────────

    def inject(
        self,
        key: str,
        value: Any,
        *,
        summary: str,
        agent_id: str,
        entry_type: str,
        importance: float = 0.5,
        ttl: float = 0,
    ) -> dict:
        """Inject an entry into the Cell L2 cache.

        - Summary (≤200 chars) goes to Hot Ring + Index Chain.
        - Full value goes to KV Cache.
        - Immediately visible to all agents in this Cell.
        """
        if not key or not summary:
            return {"success": False, "error": "key and summary required"}

        # Truncate summary to 200 chars
        summary = summary[:200]
        now = time.time()
        hot_ttl = ttl or self._hot_ttl
        kv_ttl = ttl or self._kv_ttl
        idx_ttl = max(hot_ttl * 3, self._index_ttl)  # index outlives hot

        # Build entries
        idx = IndexEntry(
            key=key, summary=summary, agent_id=agent_id,
            entry_type=entry_type, importance=importance,
            timestamp=now, location="hot", ttl=idx_ttl,
        )
        kv = CellCacheEntry(
            key=key, value=value, summary=summary,
            agent_id=agent_id, entry_type=entry_type,
            cell_id=self.cell_id, tokens=max(1, len(str(value)) // 4),
            importance=importance, ttl=kv_ttl, timestamp=now,
        )

        # 1. Hot Ring — push to deque (auto-evicts via maxlen)
        self._hot.append(idx)

        # 2. Index Chain — upsert, manage size
        if key not in self._index:
            self._index_order.append(key)
        self._index[key] = idx
        self._evict_index()

        # 3. KV Cache — upsert, manage size
        if key not in self._kv:
            self._kv_order.append(key)
        self._kv[key] = kv
        self._evict_kv()

        self._inject_count += 1
        if self._pmu:
            self._pmu.increment("cache.injections")
        return {"success": True, "key": key, "cell_id": self.cell_id}

    def lookup(self, key: str) -> CellCacheEntry | None:
        """Look up a full cached value by exact key.

        Checks: Hot Ring → KV Cache (fast path).
        If the entry was previously demoted to L3/R4, returns None
        and the caller should fall back to memory.recall().
        """
        now = time.time()

        # Check KV Cache first
        entry = self._kv.get(key)
        if entry and not entry.expired(now):
            self._hits += 1
            if self._pmu:
                self._pmu.increment("cache.hits")
            self._touch_kv(key)
            return entry

        # Check Index — maybe the value is at L3/R4
        idx = self._index.get(key)
        if idx and not idx.expired(now):
            self._hits += 1
            if self._pmu:
                self._pmu.increment("cache.hits")
            if idx.location in ("l3", "r4"):
                # Value is demoted; return None but let caller know via index
                return None

        self._misses += 1
        if self._pmu:
            self._pmu.increment("cache.misses")
        return None

    def search(self, query: str, limit: int = 10) -> list[IndexEntry]:
        """Search the Index Chain by keyword in summaries.

        Low-token-cost pre-check — read the summary before deciding
        whether to fetch the full value.
        """
        now = time.time()
        results: list[IndexEntry] = []
        q = query.lower()

        # Search Hot Ring first (newest)
        for entry in reversed(self._hot):
            if not entry.expired(now) and q in entry.summary.lower():
                results.append(entry)
                if len(results) >= limit:
                    return results

        # Then Index Chain
        for entry in self._index.values():
            if not entry.expired(now) and q in entry.summary.lower():
                # Avoid duplicating hot entries already in results
                if not any(r.key == entry.key for r in results):
                    results.append(entry)
                    if len(results) >= limit:
                        return results

        return results

    def promote(self, key: str, summary: str, value: Any,
                location: str = "l3", importance: float = 0.5) -> dict:
        """Promote a demoted entry back into the KV cache.

        Called when memory.recall() finds data relevant to this Cell.
        """
        entry = CellCacheEntry(
            key=key, value=value, summary=summary[:200],
            agent_id="system", entry_type="promoted",
            cell_id=self.cell_id, tokens=max(1, len(str(value)) // 4),
            importance=importance, ttl=self._kv_ttl,
        )
        if key not in self._kv:
            self._kv_order.append(key)
        self._kv[key] = entry
        self._evict_kv()

        # Update index location
        if key in self._index:
            self._index[key].location = "kv"
        self._inject_count += 1
        if self._pmu:
            self._pmu.increment("cache.promotions")
        return {"success": True, "key": key, "action": "promoted"}

    def flush(self) -> int:
        """Flush all expired entries to MemoryManager.

        Evicted KV entries → memory.remember(ring=2).
        Hot Ring entries are already IndexEntries (summaries only),
        so we only flush full values from KV.
        """
        from l3.memory import get_memory

        now = time.time()
        mem = get_memory()
        count = 0

        expired_keys = [
            k for k, e in self._kv.items()
            if e.expired(now)
        ]
        for key in expired_keys:
            entry = self._kv.pop(key, None)
            if entry is None:
                continue
            # Update index location
            idx = self._index.get(key)
            if idx:
                idx.location = "l3"

            # Persist to MemoryManager Ring 2 (short-term)
            try:
                mem.remember(
                    agent_id=entry.agent_id,
                    cell_id=self.cell_id,
                    entry_type=entry.entry_type,
                    content=entry.value if isinstance(entry.value, str) else str(entry.value),
                    ring=2,
                    importance=entry.importance,
                    tags=["cell_cache", entry.entry_type, self.cell_id],
                )
                count += 1
            except Exception as e:
                logger.warning("CellCache flush: %s", e)

        # Also evict expired index entries (keep them lean)
        self._index_order = [k for k in self._index_order if k in self._index]
        expired_idx = [
            k for k, e in self._index.items()
            if e.expired(now)
        ]
        for key in expired_idx:
            self._pop_from_list(self._index_order, key)
            self._index.pop(key, None)

        if count:
            self._flush_count += count
            if self._pmu:
                self._pmu.increment("cache.flushes", delta=count)
            logger.info("CellCache %s: flushed %d entries to L3", self.cell_id, count)
        return count

    def get_cell_context(self, max_tokens: int = 2048) -> str:
        """Build a Cell-level LLM context string from Hot Ring + Index.

        Returns top-k entries sorted by importance, trimmed to max_tokens.
        Used by AgentLoop to inject cross-agent awareness with minimal token cost.
        """
        now = time.time()
        candidates: list[IndexEntry] = []

        # Hot Ring (newest)
        for e in self._hot:
            if not e.expired(now) and e.importance >= 0.3:
                candidates.append(e)

        # Index chain — fill remaining with high-importance entries
        existing_keys = {e.key for e in candidates}
        for e in self._index.values():
            if not e.expired(now) and e.key not in existing_keys and e.importance >= 0.4:
                candidates.append(e)

        # Sort by importance desc, timestamp desc
        candidates.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)

        lines: list[str] = []
        tokens = 0
        for e in candidates:
            line = f"[{e.entry_type}] {e.summary} (key={e.key}, location={e.location})"
            estimate = max(1, len(line) // 4)
            if tokens + estimate > max_tokens:
                break
            lines.append(line)
            tokens += estimate

        if not lines:
            return ""
        return f"--- Cell {self.cell_id} Shared Context ---\n" + "\n".join(lines)

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "cell_id": self.cell_id,
            "hot_size": len(self._hot),
            "hot_max": self._hot_size,
            "index_size": len(self._index),
            "index_max": self._index_size,
            "kv_size": len(self._kv),
            "kv_max": self._kv_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(total, 1) * 100, 1),
            "inject_count": self._inject_count,
            "flush_count": self._flush_count,
        }

    def clear(self) -> None:
        """Clear all cached data (called on Cell shutdown)."""
        self._hot.clear()
        self._index.clear()
        self._kv.clear()
        self._index_order.clear()
        self._kv_order.clear()
        logger.info("CellCache %s: cleared", self.cell_id)

    # ── Internal helpers ──────────────────────────────────────────

    def _evict_index(self) -> None:
        while len(self._index) > self._index_size and self._index_order:
            oldest = self._index_order.pop(0)
            idx = self._index.pop(oldest, None)
            if idx and idx.location == "hot":
                # Index entry being evicted — nothing to flush (summaries only)
                pass

    def _evict_kv(self) -> None:
        while len(self._kv) > self._kv_size and self._kv_order:
            oldest = self._kv_order.pop(0)
            entry = self._kv.pop(oldest, None)
            if entry:
                # Flush to MemoryManager
                try:
                    from l3.memory import get_memory
                    mem = get_memory()
                    mem.remember(
                        agent_id=entry.agent_id,
                        cell_id=self.cell_id,
                        entry_type=entry.entry_type,
                        content=entry.value if isinstance(entry.value, str) else str(entry.value),
                        ring=2,
                        importance=entry.importance,
                        tags=["cell_cache", entry.entry_type, self.cell_id],
                    )
                    self._flush_count += 1
                except Exception as e:
                    logger.warning("CellCache evict flush: %s", e)
                # Update index location
                idx = self._index.get(oldest)
                if idx:
                    idx.location = "l3"

    def _touch_kv(self, key: str) -> None:
        """Move key to end of KV LRU order."""
        self._pop_from_list(self._kv_order, key)
        self._kv_order.append(key)

    @staticmethod
    def _pop_from_list(lst: list[str], key: str) -> None:
        try:
            lst.remove(key)
        except ValueError:
            pass
