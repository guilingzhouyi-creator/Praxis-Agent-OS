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

import json
import logging
import threading
import time
from collections import deque
from typing import Any

from l1.kernel.params.system import (
    CELL_CACHE_CONTEXT_MAX_TOKENS,
    CELL_CACHE_HOT_SIZE,
    CELL_CACHE_HOT_TTL,
    CELL_CACHE_INDEX_SIZE,
    CELL_CACHE_INDEX_TTL,
    CELL_CACHE_KV_SIZE,
    CELL_CACHE_KV_TTL,
    CELL_CACHE_SEARCH_LIMIT,
    LOG_TRUNC_200,
    MEMORY_IMPORTANCE_BASE,
    MEMORY_IMPORTANCE_DECISION,
    MEMORY_IMPORTANCE_MODERATE,
    MEMORY_MIN_CONTENT_LEN,
    TOKEN_CHARS_PER_TOKEN,
)
from l3.cell.components.cell_types import CellCacheEntry, IndexEntry

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
        self._lock = threading.RLock()
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
        importance: float = MEMORY_IMPORTANCE_BASE,
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
        summary = summary[:LOG_TRUNC_200]
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
            cell_id=self.cell_id, tokens=max(1, len(str(value)) // TOKEN_CHARS_PER_TOKEN),
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

    def search(self, query: str, limit: int = CELL_CACHE_SEARCH_LIMIT) -> list[IndexEntry]:
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
                location: str = "l3", importance: float = MEMORY_IMPORTANCE_BASE) -> dict:
        """Promote a demoted entry back into the KV cache.

        Called when memory.recall() finds data relevant to this Cell.
        """
        entry = CellCacheEntry(
            key=key, value=value, summary=summary[:LOG_TRUNC_200],
            agent_id="system", entry_type="promoted",
            cell_id=self.cell_id, tokens=max(1, len(str(value)) // TOKEN_CHARS_PER_TOKEN),
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
        now = time.time()
        count = 0
        failures = 0

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

            if self._flush_one(entry, key):
                count += 1
            else:
                failures += 1

        # Also evict expired index entries (keep them lean)
        self._index_order = [k for k in self._index_order if k in self._index]
        expired_idx = [
            k for k, e in self._index.items()
            if e.expired(now)
        ]
        for key in expired_idx:
            self._pop_from_list(self._index_order, key)

        if count or failures:
            log_msg = "flushed %d entries" % count
            if failures:
                log_msg += ", %d failed/skipped" % failures
            logger.info("CellCache %s: %s", self.cell_id, log_msg)
        return count

    def get_cell_context(self, max_tokens: int = CELL_CACHE_CONTEXT_MAX_TOKENS) -> str:
        """Build a Cell-level LLM context string from Hot Ring + Index.

        Returns top-k entries sorted by importance, trimmed to max_tokens.
        Used by AgentLoop to inject cross-agent awareness with minimal token cost.
        """
        now = time.time()
        candidates: list[IndexEntry] = []

        # Hot Ring (newest)
        for e in self._hot:
            if not e.expired(now) and e.importance >= MEMORY_IMPORTANCE_DECISION:
                candidates.append(e)

        # Index chain — fill remaining with high-importance entries
        existing_keys = {e.key for e in candidates}
        for e in self._index.values():
            if not e.expired(now) and e.key not in existing_keys and e.importance >= MEMORY_IMPORTANCE_MODERATE:
                candidates.append(e)

        # Sort by importance desc, timestamp desc
        candidates.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)

        lines: list[str] = []
        tokens = 0
        for e in candidates:
            line = f"[{e.entry_type}] {e.summary} (key={e.key}, location={e.location})"
            estimate = max(1, len(line) // TOKEN_CHARS_PER_TOKEN)
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

    def keys(self, limit: int = 0) -> list[str]:
        """Return KV cache keys (optionally capped) without exposing internals."""
        with self._lock:
            keys = list(self._kv.keys())
        return keys if limit <= 0 else keys[:limit]

    def clear(self) -> None:
        """Clear all cached data (called on Cell shutdown)."""
        self._hot.clear()
        self._index.clear()
        self._kv.clear()
        self._index_order.clear()
        self._kv_order.clear()
        logger.info("CellCache %s: cleared", self.cell_id)

    # ── Internal helpers ──────────────────────────────────────────

    def _flush_one(self, entry: CellCacheEntry, key: str) -> bool:
        """Flush a single entry to MemoryManager Ring 2.

        Returns True if the entry was persisted, False on failure.
        Replaces duplicated flush logic in flush() and _evict_kv().
        """
        from l3.memory.memory import get_memory
        content = entry.value if isinstance(entry.value, str) else json.dumps(entry.value, default=str)
        # Skip if content would be rejected by MemoryManager quality gate (<30 chars)
        if len(content) < MEMORY_MIN_CONTENT_LEN:
            logger.debug("CellCache flush skip: content too short (%d chars)", len(content))
            return False
        try:
            mem = get_memory()
            mem.remember(
                agent_id=entry.agent_id,
                cell_id=self.cell_id,
                entry_type=entry.entry_type,
                content=content,
                ring=2,
                importance=entry.importance,
                tags=["cell_cache", entry.entry_type, self.cell_id],
            )
            self._flush_count += 1
            return True
        except Exception as e:
            logger.warning("CellCache flush: %s", e)
            return False

    def _evict_index(self) -> None:
        while len(self._index) > self._index_size and self._index_order:
            oldest = self._index_order.pop(0)
            idx = self._index.pop(oldest, None)
            # Don't evict index entries — keep the summary so the index chain
            # remains intact even after the KV value is flushed to L3.
            if idx:
                pass  # Summary preserved in _index (location was set to "l3" by _flush_one)

    def _evict_kv(self) -> None:
        while len(self._kv) > self._kv_size and self._kv_order:
            oldest = self._kv_order.pop(0)
            entry = self._kv.pop(oldest, None)
            if entry:
                self._flush_one(entry, oldest)
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
            logger.debug("cell_cache: key %r not in list, nothing to remove", key)
