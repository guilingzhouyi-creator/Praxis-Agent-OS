"""Memory ring layer — extracted from memory.py for modularity.

Contains MemEntry, RingLayer, and _estimate_tokens that were split out
by OpenCode during memory.py refactoring.
"""
from __future__ import annotations

import heapq
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field

from l1.kernel.params.system import (
    LOG_TRUNC_100,
    LOG_TRUNC_200,
    LOG_TRUNC_500,
    MEMORY_IMPORTANCE_BASE,
    MEMORY_IMPORTANCE_HIGH,
    MEMORY_IMPORTANCE_MODERATE,
)

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str, provider: str = "") -> int:
    """Token count estimation with optional provider-specific accuracy."""
    try:
        import tiktoken as _tk
        enc = _tk.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception as e:
        logger.warning("services/memory: %s", e)

    if provider == "anthropic":
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        eng = len(text) - cjk
        return max(1, eng // 4 + cjk)

    return max(1, len(text) // 4)


@dataclass
class MemEntry:
    id: str
    agent_id: str
    entry_type: str
    content: str
    cell_id: str = ""
    tokens: int = 0
    tags: list[str] = field(default_factory=list)
    source: str = ""
    fingerprint: str = ""
    importance: float = MEMORY_IMPORTANCE_BASE
    timestamp: float = field(default_factory=time.time)
    ttl: float = 0.0

    def __post_init__(self):
        if not self.tokens:
            self.tokens = _estimate_tokens(self.content)

    def expired(self) -> bool:
        return self.ttl > 0 and (time.time() - self.timestamp) > self.ttl

    def to_dict(self) -> dict:
        """Serialize this entry to a plain dict."""
        return asdict(self)

    def quality_note(self) -> str:
        if not self.content or not self.content.strip():
            return "empty"
        score = len(self.content) * 0.3
        if self.tags:
            score += len(self.tags) * 5
        if self.importance > MEMORY_IMPORTANCE_HIGH:
            score += 20
        elif self.importance > MEMORY_IMPORTANCE_MODERATE:
            score += 10
        if self.tokens > LOG_TRUNC_500:
            score += 15
        elif self.tokens > LOG_TRUNC_100:
            score += 5
        if score >= 40:
            return "good"
        if score >= 15:
            return "average"
        return "low"


class RingLayer:
    """Token-aware ring buffer with importance-weighted eviction."""

    def __init__(self, name: str, max_tokens: int, max_entries: int = 0, ttl: float = 0):
        self.name = name
        self.max_tokens = max_tokens
        self.max_entries = max_entries or max_tokens // 100
        self.default_ttl = ttl
        self._entries: deque[MemEntry] = deque(maxlen=self.max_entries)
        self._token_count = 0
        # Eviction heap: (importance, timestamp, id(entry)) — lowest importance + oldest first
        self._evict_heap: list[tuple[float, float, int]] = []
        # Reverse indexes for O(1) query lookups
        self._agent_index: dict[str, list[MemEntry]] = {}
        self._type_index: dict[str, list[MemEntry]] = {}
        self._tag_index: dict[str, list[MemEntry]] = {}
        self._lock = threading.Lock()

    def push(self, entry: MemEntry) -> None:
        """Push an entry into the ring layer with automatic eviction if over budget."""
        with self._lock:
            self._entries.append(entry)
            self._token_count += entry.tokens
            heapq.heappush(self._evict_heap, (entry.importance, entry.timestamp, id(entry)))
            # Update reverse indexes
            self._agent_index.setdefault(entry.agent_id, []).append(entry)
            self._type_index.setdefault(entry.entry_type, []).append(entry)
            for tag in entry.tags:
                self._tag_index.setdefault(tag, []).append(entry)
            self._evict_if_needed()

    def query(self, agent_id: str | None = None, entry_type: str | None = None,
              tag: str | None = None, limit: int = 20) -> list[MemEntry]:
        """Query entries from the ring layer with optional filters."""
        with self._lock:
            # Use reverse indexes for O(1) lookup by agent/type/tag
            if agent_id and agent_id in self._agent_index:
                candidates = self._agent_index[agent_id]
            elif entry_type and entry_type in self._type_index:
                candidates = self._type_index[entry_type]
            elif tag and tag in self._tag_index:
                candidates = self._tag_index[tag]
            else:
                candidates = self._entries
            results = [e for e in candidates if not e.expired()]
        if entry_type and not (agent_id and agent_id in self._agent_index):
            results = [e for e in results if e.entry_type == entry_type]
        if agent_id and not (agent_id and agent_id in self._agent_index):
            results = [e for e in results if e.agent_id == agent_id]
        if tag:
            results = [e for e in results if tag in e.tags]
        return results[:limit]

    def summarize(self, agent_id: str) -> str:
        """Return a text summary of recent entries for an agent."""
        with self._lock:
            entries = [e for e in self._entries if e.agent_id == agent_id and not e.expired()]
        if not entries:
            return ""
        return "\n".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_200]}" for e in entries[-10:])

    def count(self) -> int:
        """Return the current number of entries."""
        with self._lock:
            return len(self._entries)

    def token_count(self) -> int:
        """Return the current total token count."""
        with self._lock:
            return self._token_count

    def clear_agent(self, agent_id: str) -> int:
        """Remove all entries for a given agent. Returns number removed."""
        with self._lock:
            before = len(self._entries)
            # Collect entries to remove and clean indexes incrementally
            removed_entries = [e for e in self._entries if e.agent_id == agent_id]
            for e in removed_entries:
                self._entries.remove(e)
                self._token_count = max(0, self._token_count - e.tokens)
                # Clean agent index
                aid_list = self._agent_index.get(e.agent_id)
                if aid_list:
                    try:
                        aid_list.remove(e)
                    except ValueError:
                        pass
                # Clean type index
                type_list = self._type_index.get(e.entry_type)
                if type_list:
                    try:
                        type_list.remove(e)
                    except ValueError:
                        pass
                # Clean tag index
                for tag in e.tags:
                    tag_list = self._tag_index.get(tag)
                    if tag_list:
                        try:
                            tag_list.remove(e)
                        except ValueError:
                            pass
            # Rebuild eviction heap (smaller than full rebuild since only entries changed)
            for e in removed_entries:
                self._evict_heap = [(imp, ts, eid) for imp, ts, eid in self._evict_heap
                                    if eid != id(e)]
            heapq.heapify(self._evict_heap)
            return before - len(self._entries)

    def forget_cell(self, cell_id: str) -> int:
        """Remove all entries for a given cell. Returns number removed."""
        with self._lock:
            removed = [e for e in self._entries if e.cell_id == cell_id]
            for e in removed:
                self._entries.remove(e)
                self._token_count = max(0, self._token_count - e.tokens)
                for lst in (self._agent_index.get(e.agent_id),
                            self._type_index.get(e.entry_type)):
                    if lst:
                        try: lst.remove(e)
                        except ValueError: pass
                for tag in e.tags:
                    tl = self._tag_index.get(tag)
                    if tl:
                        try: tl.remove(e)
                        except ValueError: pass
            self._evict_heap = [(i, t, eid) for i, t, eid in self._evict_heap
                                if eid not in {id(e) for e in removed}]
            heapq.heapify(self._evict_heap)
            return len(removed)

    def to_dict(self) -> list[dict]:
        """Serialize all entries to a list of dicts."""
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def _evict_if_needed(self) -> None:
        """O(log n) eviction via heap — pop lowest importance + oldest entries."""
        while self._token_count > self.max_tokens and self._evict_heap:
            imp, ts, eid = heapq.heappop(self._evict_heap)
            # Skip stale heap entries (entry already removed from _entries by other paths)
            target = next((e for e in self._entries if id(e) == eid), None)
            if target is None:
                continue
            self._entries.remove(target)
            self._token_count -= target.tokens

    def _rebuild_token_count(self) -> None:
        self._token_count = sum(e.tokens for e in self._entries)
        # Rebuild eviction heap and reverse indexes
        self._evict_heap = [(e.importance, e.timestamp, id(e)) for e in self._entries]
        heapq.heapify(self._evict_heap)
        self._agent_index = {}
        self._type_index = {}
        self._tag_index = {}
        for e in self._entries:
            self._agent_index.setdefault(e.agent_id, []).append(e)
            self._type_index.setdefault(e.entry_type, []).append(e)
            for tag in e.tags:
                self._tag_index.setdefault(tag, []).append(e)


import threading
