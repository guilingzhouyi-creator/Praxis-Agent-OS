"""Memory ring layer — extracted from memory.py for modularity.

Contains MemEntry, RingLayer, and _estimate_tokens that were split out
by OpenCode during memory.py refactoring.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any
from l1.kernel.params.system import (
    LOG_TRUNC_100, LOG_TRUNC_200, LOG_TRUNC_500,
    MEMORY_IMPORTANCE_BASE, MEMORY_IMPORTANCE_HIGH, MEMORY_IMPORTANCE_MODERATE,
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
        self._lock = threading.Lock()

    def push(self, entry: MemEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            self._token_count += entry.tokens
            self._evict_if_needed()

    def query(self, agent_id: str | None = None, entry_type: str | None = None,
              tag: str | None = None, limit: int = 20) -> list[MemEntry]:
        with self._lock:
            results = [e for e in self._entries if not e.expired()]
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if entry_type:
            results = [e for e in results if e.entry_type == entry_type]
        if tag:
            results = [e for e in results if tag in e.tags]
        return results[:limit]

    def summarize(self, agent_id: str) -> str:
        with self._lock:
            entries = [e for e in self._entries if e.agent_id == agent_id and not e.expired()]
        if not entries:
            return ""
        return "\n".join(f"[{e.entry_type}] {e.content[:LOG_TRUNC_200]}" for e in entries[-10:])

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def token_count(self) -> int:
        with self._lock:
            return self._token_count

    def clear_agent(self, agent_id: str) -> int:
        with self._lock:
            before = len(self._entries)
            self._entries = deque([e for e in self._entries if e.agent_id != agent_id], maxlen=self.max_entries)
            self._rebuild_token_count()
            return before - len(self._entries)

    def forget_cell(self, cell_id: str) -> int:
        with self._lock:
            before = len(self._entries)
            self._entries = deque([e for e in self._entries if e.cell_id and e.cell_id != cell_id], maxlen=self.max_entries)
            self._rebuild_token_count()
            return before - len(self._entries)

    def to_dict(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def _evict_if_needed(self) -> None:
        while self._token_count > self.max_tokens and self._entries:
            oldest = min(self._entries, key=lambda e: (e.importance, e.timestamp))
            self._entries.remove(oldest)
            self._token_count -= oldest.tokens

    def _rebuild_token_count(self) -> None:
        self._token_count = sum(e.tokens for e in self._entries)


import threading
