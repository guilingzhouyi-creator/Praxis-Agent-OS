"""Context Pager — paging system between ContextManager and MemoryService.

Architecture:
  LLM inference
     ↑↓ Token window (4K)
  ContextManager (Register)     ← Working set (pages in use)
     ↑↓ Page fault / Prefetch / Swap out
  ContextPager                   ← 🆕 Paging system
     ↑↓ On-demand load / Write-back
  MemoryService (Ring 1/2/3)    ← Main memory
     ↑↓ Swap out / Archive
  Archive / JSON                 ← Swap area

Design:
  - Fixed-size Context Chunk (512 token)
  - Page table: Chunk ID → storage location (Ring 1/2/3 / Archive)
  - Page fault: load from lower storage, LRU eviction
  - Dirty page: write back on modification
  - Prefetch: predict next required Chunk
  - Sharing: multi-agent shared read-only Chunk

Lifecycle:
  ContextPager inherits BaseService (ServiceManager-managed) rather than
  using the singleton pattern (get_xxx/reset_xxx) that MemoryManager uses.
  This is intentional: ContextPager has mutable runtime state (page table,
  working set) that should be scoped to the Cell lifetime, not global.
  The two patterns coexist in the memory/ submodule to match each
  component's effective scope — global vs. Cell-scoped.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from l1.kernel.params.system import CHUNK_SIZE_TOKENS, MAX_WORKING_SET_SIZE, PAGER_RECALL_LIMIT
from l3._base import BaseService

logger = logging.getLogger(__name__)

CHUNK_SIZE_TOKENS = 512  # imported from kernel.params
MAX_WORKING_SET = MAX_WORKING_SET_SIZE  # 8 chunks in Register at once


@dataclass
class ContextChunk:
    """Context Chunk — basic unit of the paging system."""
    chunk_id: str
    data: str = ""
    tokens: int = CHUNK_SIZE_TOKENS
    mapped: bool = False        # Whether in Register
    dirty: bool = False         # Whether modified
    ring: int = 1               # 1/2/3
    agent_id: str = ""
    tags: list[str] = field(default_factory=list)
    accessed_at: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)
    shared_with: list[str] = field(default_factory=list)

    def token_count(self) -> int:
        return max(1, len(self.data) // 4)


class PageTable:
    """Page table — Chunk ID → storage location mapping."""

    def __init__(self):
        self._entries: dict[str, dict] = {}  # chunk_id → {ring, agent_id, tags, ...}
        self._lock = threading.RLock()

    def map(self, chunk_id: str, ring: int, agent_id: str = "", tags: list[str] | None = None) -> None:
        """Map a chunk_id to a storage location (ring + agent)."""
        with self._lock:
            self._entries[chunk_id] = {"ring": ring, "agent_id": agent_id, "tags": tags or []}

    def unmap(self, chunk_id: str) -> bool:
        """Remove a chunk_id mapping from the page table."""
        with self._lock:
            return self._entries.pop(chunk_id, None) is not None

    def lookup(self, chunk_id: str) -> dict | None:
        """Look up a chunk_id's storage location."""
        with self._lock:
            return self._entries.get(chunk_id)

    def query(self, agent_id: str | None = None, tag: str | None = None, ring: int | None = None) -> list[str]:
        """Query chunk IDs by agent, tag, or ring filter."""
        with self._lock:
            results = []
            for cid, entry in self._entries.items():
                if agent_id and entry.get("agent_id") != agent_id:
                    continue
                if tag and tag not in entry.get("tags", []):
                    continue
                if ring is not None and entry.get("ring") != ring:
                    continue
                results.append(cid)
            return results

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class WorkingSet:
    """Working set — chunks currently in Register (LRU cache)."""

    def __init__(self, capacity: int = MAX_WORKING_SET):
        self.capacity = capacity
        self._chunks: OrderedDict[str, ContextChunk] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, chunk_id: str) -> ContextChunk | None:
        with self._lock:
            chunk = self._chunks.get(chunk_id)
            if chunk:
                chunk.accessed_at = time.time()
                self._chunks.move_to_end(chunk_id)
            return chunk

    def put(self, chunk: ContextChunk) -> ContextChunk | None:
        """Put into working set. Returns evicted chunk (if any)."""
        evicted = None
        with self._lock:
            if chunk.chunk_id in self._chunks:
                self._chunks[chunk.chunk_id] = chunk
                self._chunks.move_to_end(chunk.chunk_id)
                return None
            if len(self._chunks) >= self.capacity:
                evicted_id, evicted_chunk = self._chunks.popitem(last=False)
                evicted = evicted_chunk
            chunk.mapped = True
            self._chunks[chunk.chunk_id] = chunk
        return evicted

    def remove(self, chunk_id: str) -> bool:
        with self._lock:
            return self._chunks.pop(chunk_id, None) is not None

    def list(self) -> list[ContextChunk]:
        with self._lock:
            return list(self._chunks.values())

    def count(self) -> int:
        with self._lock:
            return len(self._chunks)

    def is_full(self) -> bool:
        with self._lock:
            return len(self._chunks) >= self.capacity

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()


class ContextPager(BaseService):
    """Context Pager — paging system.

    Flow:
      fetch(chunk_id)      → Page fault: load from MemoryService → working set
      prefetch(chunk_ids)  → Prefetch: load ahead into working set
      flush(chunk_id)      → Write-back: dirty chunk → MemoryService
      evict()              → Evict: LRU eviction, write dirty pages back
    """

    def __init__(self):
        super().__init__("pager")
        self.working_set = WorkingSet()
        self.page_table = PageTable()
        self._mem = None  # lazy import
        self._stats = {"faults": 0, "prefetches": 0, "flushes": 0, "evictions": 0}
        self._lock = threading.RLock()

    @property
    def _memory(self):
        if self._mem is None:
            from l3.memory.memory import get_memory
            self._mem = get_memory()
        return self._mem

    def _on_start(self) -> dict:
        return {"success": True, "working_set": self.working_set.capacity}

    def _on_stop(self) -> dict:
        self.flush_all()
        self.working_set.clear()
        self.page_table.clear()
        return {"success": True}

    # ── Core paging operations ──

    def fetch(self, chunk_id: str, agent_id: str = "") -> dict:
        """Page fault: load chunk from MemoryService into working set."""
        # 1. Check working set
        chunk = self.working_set.get(chunk_id)
        if chunk:
            return {"success": True, "chunk": chunk, "source": "working_set", "fault": False}

        # 2. Page fault — load from MemoryService
        entry = self._load_from_memory(chunk_id, agent_id)
        if not entry:
            return {"success": False, "error": f"chunk {chunk_id} not found in memory or archive"}

        chunk = ContextChunk(
            chunk_id=chunk_id, data=entry["data"], tokens=entry.get("tokens", CHUNK_SIZE_TOKENS),
            ring=entry.get("ring", 1), agent_id=entry.get("agent_id", agent_id),
            tags=entry.get("tags", []),
        )

        # 3. Put into working set, handle eviction
        evicted = self.working_set.put(chunk)
        if evicted and evicted.dirty:
            self._flush(evicted)

        self.page_table.map(chunk_id, chunk.ring, agent_id, chunk.tags)
        with self._lock:
            self._stats["faults"] += 1

        return {"success": True, "chunk": chunk, "source": f"ring_{chunk.ring}", "fault": True}

    def prefetch(self, chunk_ids: list[str], agent_id: str = "") -> dict:
        """Prefetch: load multiple chunks ahead of time."""
        loaded = []
        for cid in chunk_ids:
            if not self.working_set.get(cid):
                r = self.fetch(cid, agent_id)
                if r["success"]:
                    loaded.append(cid)
        with self._lock:
            self._stats["prefetches"] += len(loaded)
        return {"success": True, "prefetched": loaded, "count": len(loaded)}

    def flush(self, chunk_id: str) -> dict:
        """Write-back: flush dirty chunk to MemoryService."""
        chunk = self.working_set.get(chunk_id)
        if not chunk:
            return {"success": False, "error": "chunk not in working set"}
        if not chunk.dirty:
            return {"success": True, "note": "not dirty"}
        return self._flush(chunk)

    def flush_all(self) -> dict:
        """Flush all dirty chunks."""
        flushed = 0
        for chunk in self.working_set.list():
            if chunk.dirty:
                self._flush(chunk)
                flushed += 1
        return {"success": True, "flushed": flushed}

    def _flush(self, chunk: ContextChunk) -> dict:
        """Actual write-back operation."""
        self._memory.remember(
            agent_id=chunk.agent_id, entry_type="chunk",
            content=chunk.data, tags=chunk.tags,
            ring=chunk.ring,
        )
        chunk.dirty = False
        with self._lock:
            self._stats["flushes"] += 1
        return {"success": True, "chunk_id": chunk.chunk_id, "ring": chunk.ring}

    def evict(self, chunk_id: str) -> dict:
        """Force evict a specific chunk."""
        chunk = self.working_set.get(chunk_id)
        if not chunk:
            return {"success": False, "error": "chunk not in working set"}
        if chunk.dirty:
            self._flush(chunk)
        self.working_set.remove(chunk_id)
        self.page_table.unmap(chunk_id)
        with self._lock:
            self._stats["evictions"] += 1
        return {"success": True, "chunk_id": chunk_id}

    def share(self, chunk_id: str, target_agent_id: str) -> dict:
        """Share chunk with other agents (COW: copy-on-write)."""
        chunk = self.working_set.get(chunk_id)
        if not chunk:
            return {"success": False, "error": "chunk not in working set"}
        if target_agent_id not in chunk.shared_with:
            chunk.shared_with.append(target_agent_id)
        return {"success": True, "chunk_id": chunk_id, "shared_with": chunk.shared_with}

    # ── Helpers ──

    def _load_from_memory(self, chunk_id: str, agent_id: str) -> dict | None:
        """Load chunk data from MemoryService."""
        results = self._memory.recall(agent_id=agent_id, limit=PAGER_RECALL_LIMIT)
        for entry in results:
            if chunk_id in entry.tags:
                return {"data": entry.content, "ring": 1, "agent_id": entry.agent_id, "tags": entry.tags, "tokens": max(1, len(entry.content) // 4)}
        results = self._memory.recall(agent_id=agent_id, limit=PAGER_RECALL_LIMIT, rings=[2, 3])
        for entry in results:
            if chunk_id in entry.tags:
                return {"data": entry.content, "ring": 3, "agent_id": entry.agent_id, "tags": entry.tags}
        return None

    def stats(self) -> dict:
        with self._lock:
            ws = self.working_set.list()
            return {
                "working_set": {"count": len(ws), "capacity": self.working_set.capacity,
                                "chunks": [c.chunk_id for c in ws]},
                "page_table": {"entries": self.page_table.count()},
                "operations": dict(self._stats),
            }


_service: ContextPager | None = None


def get_service() -> ContextPager:
    global _service
    if _service is None:
        _service = ContextPager()
    return _service


def reset_service() -> None:
    global _service
    if _service:
        _service.stop()
    _service = None
