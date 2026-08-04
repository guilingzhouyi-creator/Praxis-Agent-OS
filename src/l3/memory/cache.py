"""Multi-level cache — Cell/Agent/Scope isolation with tagging.

Cache levels:
  CELL:    Shared across all agents in the Cell (same territory = same result)
  AGENT:   Per-agent cache (Agent A reads /foo → Agent B misses)
  SCOPE:   Scoped by (agent, ring, territory) combination

Tags for selective invalidation:
  tag:agent:<id>, tag:ring:<n>, tag:territory:<path>, tag:type:<type>
  
Write by any agent → invalidates all cache entries for that path.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from l1.kernel.params.system import CACHE_DEFAULT_TTL, FILE_CACHE_MAX_ENTRIES, FILE_CACHE_TTL

logger = logging.getLogger(__name__)


class CacheEntry:
    """CacheEntry — cache entry."""
    def __init__(self, key: str, value: Any, tags: set[str] | None = None,
                 ttl: float = FILE_CACHE_TTL):
        self.key = key
        self.value = value
        self.tags = tags or set()
        self.created_at = time.time()
        self.expires_at = time.time() + ttl

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


class IsolatedCache:
    """Multi-level cache with agent/territory/ring isolation.

    Usage:
      cache = IsolatedCache(cell_id="cell-1")
      
      # Agent-scoped: only this agent can hit it
      cache.get("file:/project/foo.py", scope="agent:agent_a")
      
      # Cell-scoped: any agent in the cell can hit it
      cache.get("file:/project/bar.py", scope="cell")
      
      # Write invalidates all scopes
      cache.invalidate("file:/project/foo.py")

    Peer Agent has two delegation modes, both sharing this cache:
      - Scout:  async, pool-managed, parallel  → cache.get(agent_id="scout-xxx")
      - SubAgent: sync, blocking, serial        → cache.get(agent_id="sub-xxx")
    Cache hit accounting is per-agent_id so both modes are tracked independently.
    """

    def __init__(self, cell_id: str = "default", max_entries: int = FILE_CACHE_MAX_ENTRIES):
        self.cell_id = cell_id
        self.max_entries = max_entries
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._hits_by_agent: dict[str, int] = {}
        self._misses_by_agent: dict[str, int] = {}

    def _make_key(self, raw_key: str, scope: str = "cell", agent_id: str = "",
                  ring: int = 1, territory: list[str] | None = None) -> str:
        """Build scoped cache key."""
        if scope == "agent" and agent_id:
            return f"{raw_key}::agent={agent_id}"
        if scope == "scope" and agent_id:
            t = "_".join(territory or []) or "_"
            return f"{raw_key}::agent={agent_id}::ring={ring}::territory={t}"
        return raw_key  # cell scope

    def get(self, raw_key: str, scope: str = "cell",
            agent_id: str = "", ring: int = 1,
            territory: list[str] | None = None) -> Any | None:
        """Get cache entry. Returns None on miss or expiry.
        
        Tracks per-agent hit/miss for both Scout and SubAgent delegation.
        LRU: moves to end on hit so eviction targets coldest entries.
        """
        key = self._make_key(raw_key, scope, agent_id, ring, territory)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                if agent_id:
                    self._misses_by_agent[agent_id] = self._misses_by_agent.get(agent_id, 0) + 1
                return None
            if entry.expired:
                del self._entries[key]
                self._misses += 1
                if agent_id:
                    self._misses_by_agent[agent_id] = self._misses_by_agent.get(agent_id, 0) + 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            if agent_id:
                self._hits_by_agent[agent_id] = self._hits_by_agent.get(agent_id, 0) + 1
            return entry.value

    def set(self, raw_key: str, value: Any, scope: str = "cell",
            agent_id: str = "", ring: int = 1,
            territory: list[str] | None = None,
            tags: set[str] | None = None,
            ttl: float = FILE_CACHE_TTL) -> None:
        """Store cache entry with scoping."""
        key = self._make_key(raw_key, scope, agent_id, ring, territory)
        all_tags = set(tags or [])
        all_tags.add(f"raw:{raw_key}")
        if agent_id:
            all_tags.add(f"agent:{agent_id}")
        all_tags.add(f"ring:{ring}")
        for t in territory or []:
            all_tags.add(f"territory:{t}")
        all_tags.add(f"scope:{scope}")

        with self._lock:
            self._entries[key] = CacheEntry(key, value, all_tags, ttl)
            self._entries.move_to_end(key)
            self._evict()

    def invalidate(self, raw_key: str, scope: str = "",
                   agent_id: str = "") -> int:
        """Invalidate cache entries by raw_key.
        
        scope="" means all scopes.
        agent_id="" means all agents.
        """
        with self._lock:
            tag = f"raw:{raw_key}"
            keys = [k for k, e in self._entries.items() if tag in (e.tags or set())]
            if scope:
                keys = [k for k in keys if f"scope:{scope}" in (self._entries[k].tags or set())]
            if agent_id:
                keys = [k for k in keys if f"agent:{agent_id}" in (self._entries[k].tags or set())]
            for k in keys:
                del self._entries[k]
            return len(keys)

    def invalidate_by_tag(self, tag: str) -> int:
        """Invalidate all entries with a specific tag.
        
        Tags: agent:<id>, ring:<n>, territory:<path>, raw:<path>, scope:<level>
        """
        with self._lock:
            keys = [k for k, e in self._entries.items() if tag in (e.tags or set())]
            for k in keys:
                del self._entries[k]
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            by_agent = {}
            for aid in set(list(self._hits_by_agent.keys()) + list(self._misses_by_agent.keys())):
                h = self._hits_by_agent.get(aid, 0)
                m = self._misses_by_agent.get(aid, 0)
                by_agent[aid] = {"hits": h, "misses": m, "hit_rate": round(h / max(h + m, 1) * 100, 1)}
            return {
                "entries": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(self._hits + self._misses, 1) * 100, 1),
                "cell_id": self.cell_id,
                "by_agent": by_agent,
            }

    def agent_stats(self, agent_id: str) -> dict:
        """Per-agent cache hit/miss for a specific agent (Peer, Scout, or SubAgent)."""
        with self._lock:
            h = self._hits_by_agent.get(agent_id, 0)
            m = self._misses_by_agent.get(agent_id, 0)
            return {
                "agent_id": agent_id,
                "hits": h,
                "misses": m,
                "hit_rate": round(h / max(h + m, 1) * 100, 1),
            }

    def _evict(self) -> None:
        """LRU eviction: pop the least-recently-used entry."""
        while len(self._entries) > self.max_entries:
            if not self._entries:
                break
            self._entries.popitem(last=False)


# ── Context register (unchanged, stays shared) ──

class ContextRegister:
    """Cell-level shared context store — remains shared, no isolation."""

    def __init__(self, max_entries: int = 200):
        self.max_entries = max_entries
        self._entries: list[dict] = []
        self._lock = threading.Lock()

    def store(self, key: str, value: Any, agent_id: str = "",
              entry_type: str = "observation", ttl: float = CACHE_DEFAULT_TTL) -> str:
        with self._lock:
            self._entries.append({
                "key": key, "value": value, "agent_id": agent_id,
                "type": entry_type, "timestamp": time.time(),
                "expires_at": time.time() + ttl,
            })
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries:]
            return f"ctx-{len(self._entries)}"

    def get(self, key: str, default: Any = None) -> Any:
        now = time.time()
        with self._lock:
            for entry in reversed(self._entries):
                if entry["key"] == key and now < entry.get("expires_at", now):
                    return entry["value"]
        return default

    def recent(self, limit: int = 20) -> list[dict]:
        now = time.time()
        with self._lock:
            return [{"key": e["key"], "value": e["value"], "agent_id": e["agent_id"],
                     "type": e["type"], "timestamp": e["timestamp"]}
                    for e in self._entries[-limit:] if now < e.get("expires_at", now)]

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "max_entries": self.max_entries}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


# ── Cell-level singletons ──

_caches: dict[str, IsolatedCache] = {}
_context_registers: dict[str, ContextRegister] = {}
_lock = threading.Lock()


def get_file_cache(cell_id: str = "default") -> IsolatedCache:
    with _lock:
        if cell_id not in _caches:
            _caches[cell_id] = IsolatedCache(cell_id)
        return _caches[cell_id]


def get_context_register(cell_id: str = "default") -> ContextRegister:
    with _lock:
        if cell_id not in _context_registers:
            _context_registers[cell_id] = ContextRegister()
        return _context_registers[cell_id]


def reset_caches() -> None:
    global _caches, _context_registers
    _caches.clear()
    _context_registers.clear()


# ── LLM KV Cache stats tracking ──

_llm_cache_stats = {"total_calls": 0, "hit_tokens": 0, "miss_tokens": 0}
_llm_cache_lock = threading.Lock()


def record_llm_call(hit_tokens: int = 0, miss_tokens: int = 0) -> None:
    """Record an LLM call with KV cache hit/miss stats."""
    with _llm_cache_lock:
        _llm_cache_stats["total_calls"] += 1
        _llm_cache_stats["hit_tokens"] += hit_tokens
        _llm_cache_stats["miss_tokens"] += miss_tokens


def get_llm_cache_stats() -> dict:
    """Get LLM KV cache hit/miss statistics."""
    with _llm_cache_lock:
        total = _llm_cache_stats["hit_tokens"] + _llm_cache_stats["miss_tokens"]
        return {
            "total_calls": _llm_cache_stats["total_calls"],
            "hit_tokens": _llm_cache_stats["hit_tokens"],
            "miss_tokens": _llm_cache_stats["miss_tokens"],
            "hit_rate": round(_llm_cache_stats["hit_tokens"] / total * 100, 1) if total > 0 else 0.0,
        }
